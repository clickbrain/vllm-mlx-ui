# SPDX-License-Identifier: Apache-2.0
"""
Server-side chat history persistence.

Uses SQLite with WAL journal mode.  Every operation opens a fresh connection
so FastAPI's sync-in-threadpool model never shares a connection across threads.

DB location: ~/.vllm_mlx_ui/chats.db
Schema version tracked in PRAGMA user_version for future migrations.
"""

import logging
import sqlite3
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

# Maximum sizes to prevent runaway disk usage
_MAX_TITLE_LEN     = 500
_MAX_CONTENT_LEN   = 1_000_000   # 1 MB per message content
_MAX_REASONING_LEN = 2_000_000   # 2 MB per reasoning trace
_MAX_MSGS_PER_CONV = 2_000


def _db_path() -> Path:
    from .server_manager import STATE_DIR
    return STATE_DIR / "chats.db"


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    """
    Open a short-lived SQLite connection with WAL, FK enforcement, and a
    5-second busy timeout.  ``isolation_level=None`` puts the connection in
    autocommit mode so callers manage transactions explicitly.
    """
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA foreign_keys=ON")
        yield con
    finally:
        con.close()


def init_db() -> None:
    """Create tables and indexes if they don't exist.  Called once on startup."""
    import os
    import stat

    with _conn() as con:
        con.execute("BEGIN")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id           TEXT    PRIMARY KEY,
                title        TEXT    NOT NULL,
                model        TEXT    NOT NULL DEFAULT '',
                engine       TEXT    NOT NULL DEFAULT '',
                is_draft     INTEGER NOT NULL DEFAULT 0,
                created_at   INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT    NOT NULL,
                role            TEXT    NOT NULL,
                content         TEXT    NOT NULL,
                reasoning       TEXT,
                position        INTEGER NOT NULL,
                UNIQUE(conversation_id, position),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_id);

            CREATE INDEX IF NOT EXISTS idx_conv_updated
                ON conversations(updated_at DESC);
        """)
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version < _SCHEMA_VERSION:
            con.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        con.execute("COMMIT")

    # Restrict file permissions — chats may contain sensitive prompts
    db_file = _db_path()
    with suppress(Exception):
        os.chmod(db_file, stat.S_IRUSR | stat.S_IWUSR)


def list_conversations(limit: int = 200) -> list[dict[str, Any]]:
    """Return conversation summaries (no messages) ordered by updated_at DESC."""
    with _conn() as con:
        rows = con.execute(
            """SELECT id, title, model, engine, is_draft,
                      created_at, updated_at, message_count
               FROM conversations
               ORDER BY updated_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_conversation(
    id: str,
    title: str,
    model: str,
    engine: str,
    messages: list[dict[str, Any]],
    is_draft: bool = False,
    created_at: int | None = None,
) -> None:
    """
    Upsert a conversation and atomically replace all its messages.

    Uses BEGIN IMMEDIATE to prevent writer-writer conflicts under concurrent
    FastAPI threadpool calls.
    """
    now = int(time.time() * 1000)

    # Enforce hard limits
    title = (title or "Untitled")[:_MAX_TITLE_LEN]
    safe_msgs = messages[:_MAX_MSGS_PER_CONV]

    with _conn() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            # Preserve created_at if the row already exists
            existing = con.execute(
                "SELECT created_at FROM conversations WHERE id=?", (id,)
            ).fetchone()
            eff_created_at = existing["created_at"] if existing else (created_at or now)

            con.execute(
                """INSERT INTO conversations
                       (id, title, model, engine, is_draft, created_at, updated_at, message_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       title=excluded.title,
                       model=excluded.model,
                       engine=excluded.engine,
                       is_draft=excluded.is_draft,
                       updated_at=excluded.updated_at,
                       message_count=excluded.message_count""",
                (id, title, model or "", engine or "", int(is_draft),
                 eff_created_at, now, len(safe_msgs)),
            )

            # Replace messages (explicit DELETE so FK cascade isn't required)
            con.execute("DELETE FROM messages WHERE conversation_id=?", (id,))
            con.executemany(
                """INSERT INTO messages
                       (conversation_id, role, content, reasoning, position)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        id,
                        m.get("role", "user")[:20],
                        (m.get("content") or "")[:_MAX_CONTENT_LEN],
                        ((m.get("reasoning") or None) and
                         m["reasoning"][:_MAX_REASONING_LEN]),
                        i,
                    )
                    for i, m in enumerate(safe_msgs)
                ],
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def get_conversation(id: str) -> dict[str, Any] | None:
    """Return a full conversation with messages, or None if not found."""
    with _conn() as con:
        conv = con.execute(
            """SELECT id, title, model, engine, is_draft,
                      created_at, updated_at, message_count
               FROM conversations WHERE id=?""",
            (id,),
        ).fetchone()
        if not conv:
            return None
        msgs = con.execute(
            """SELECT role, content, reasoning
               FROM messages
               WHERE conversation_id=?
               ORDER BY position""",
            (id,),
        ).fetchall()
    result = dict(conv)
    result["messages"] = [dict(m) for m in msgs]
    return result


def get_latest_draft() -> dict[str, Any] | None:
    """Return the most recently updated draft conversation with messages, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM conversations WHERE is_draft=1 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return get_conversation(row["id"])


def delete_conversation(id: str) -> bool:
    """Delete a conversation and all its messages. Returns True if it existed."""
    with _conn() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("DELETE FROM messages WHERE conversation_id=?", (id,))
            cur = con.execute("DELETE FROM conversations WHERE id=?", (id,))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return cur.rowcount > 0


def delete_all_conversations() -> int:
    """Delete all conversations and messages. Returns count of conversations deleted."""
    with _conn() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("DELETE FROM messages")
            cur = con.execute("DELETE FROM conversations")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return cur.rowcount
