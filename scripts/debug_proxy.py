#!/usr/bin/env python3
"""
debug_proxy.py — transparent HTTP proxy between Kilroy and vllm-mlx.

Logs every request with a fingerprint hash, detects duplicates in real time,
and prints timing diffs so you can show Chuck exactly when duplicate requests
arrive and how long apart they are.

Usage:
    python3 scripts/debug_proxy.py [--listen 8001] [--target http://localhost:8000]

    Point Kilroy's ai_url at http://localhost:8001 (no /v1 needed).
    The proxy automatically rewrites /chat/completions → /v1/chat/completions.

Output example:
    [12:34:56.123] REQ #1  POST /chat/completions → /v1/chat/completions  fp=a3f7c2  msgs=4
    [12:34:56.891] REQ #2  POST /chat/completions → /v1/chat/completions  fp=a3f7c2  ⚠ DUPLICATE of #1 (+0.768s)
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiohttp import web

logging.basicConfig(
    level=logging.DEBUG,
    format="%(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("proxy")

# in-flight fingerprint → (req_num, timestamp)
_in_flight: dict[str, tuple[int, float]] = {}
# recently-completed fingerprint → (req_num, finish_timestamp)
# kept for RECENT_TTL seconds so sequential duplicates are also flagged
_recent: dict[str, tuple[int, float]] = {}
RECENT_TTL = 60.0
_req_counter = 0


def _fingerprint(method: str, path: str, body: bytes) -> str:
    return hashlib.sha256(f"{method}:{path}:".encode() + body).hexdigest()[:8]


def _ts() -> str:
    t = time.time()
    ms = int((t % 1) * 1000)
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{ms:03d}"


def _parse_body_info(body: bytes, content_type: str) -> dict:
    info: dict = {"chars": len(body)}
    if "json" in content_type and body:
        try:
            data = json.loads(body)
            msgs = data.get("messages", [])
            info["msgs"] = len(msgs)
            info["roles"] = [m.get("role", "?") for m in msgs]
            info["model"] = data.get("model", "?")
            info["max_tokens"] = data.get("max_tokens")
            info["stream"] = data.get("stream")
            info["tools"] = len(data.get("tools") or [])
        except Exception:
            pass
    return info


def _log(line: str, duplicate: bool = False) -> None:
    if duplicate:
        # Yellow ANSI
        sys.stdout.write(f"\033[93m{line}\033[0m\n")
    else:
        sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _effective_prefix(incoming_path: str, configured_prefix: str) -> str:
    """Return the prefix to prepend when forwarding.

    - If a prefix was explicitly set via --target URL path, always use it.
    - Otherwise auto-prepend /v1 for paths that don't already start with /v1.
      This handles Kilroy configurations where ai_url has no /v1 suffix.
    """
    if configured_prefix:
        return configured_prefix
    if not incoming_path.startswith("/v1"):
        return "/v1"
    return ""


async def proxy_handler(request: web.Request) -> web.StreamResponse:
    global _req_counter

    target_base: str = request.app["target"]
    configured_prefix: str = request.app["path_prefix"]

    try:
        body = await request.read()
    except Exception as exc:
        _log(f"[{_ts()}]  ERROR reading request body: {exc}")
        return web.Response(status=400, text=str(exc))

    content_type = request.headers.get("Content-Type", "")
    incoming_path = request.path
    fp = _fingerprint(request.method, incoming_path, body)
    info = _parse_body_info(body, content_type)

    _req_counter += 1
    req_num = _req_counter
    now = time.time()

    # Purge stale recent entries
    stale = [k for k, (_, ts) in _recent.items() if now - ts > RECENT_TTL]
    for k in stale:
        del _recent[k]

    # Duplicate detection — catches both concurrent and sequential duplicates
    dup_of = None
    dup_delta = None
    if fp in _in_flight:
        orig_num, orig_ts = _in_flight[fp]
        dup_of = orig_num
        dup_delta = now - orig_ts
    elif fp in _recent:
        orig_num, orig_ts = _recent[fp]
        dup_of = orig_num
        dup_delta = now - orig_ts

    _in_flight[fp] = (req_num, now)

    prefix = _effective_prefix(incoming_path, configured_prefix)
    forwarded_path = prefix + incoming_path if prefix else incoming_path

    # Build log line
    parts = [
        f"[{_ts()}]",
        f"REQ #{req_num:>3}",
        f"{request.method} {incoming_path}",
    ]
    if prefix:
        parts.append(f"→ {forwarded_path}")
    parts.append(f"fp={fp}")
    for k in ("model", "msgs", "chars", "max_tokens", "stream", "tools"):
        if k in info:
            parts.append(f"{k}={info[k]}")
    parts.append(f"ip={request.remote}")

    if dup_of is not None:
        parts.append(f"⚠️  DUPLICATE of #{dup_of} (+{dup_delta:.3f}s)")
        _log("  ".join(parts), duplicate=True)
    else:
        _log("  ".join(parts))

    # Forward to target with prefix applied to the full rel_url (path + query)
    rel = str(request.rel_url)  # e.g. /chat/completions?foo=bar
    # rel starts with incoming_path; replace just the path portion with forwarded_path
    if prefix:
        rel = forwarded_path + rel[len(incoming_path):]
    target_url = target_base.rstrip("/") + rel

    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }

    try:
        session: aiohttp.ClientSession = request.app["session"]
        async with session.request(
            request.method,
            target_url,
            headers=forward_headers,
            data=body,
            timeout=aiohttp.ClientTimeout(total=600),
        ) as upstream:
            resp_headers = {
                k: v for k, v in upstream.headers.items()
                if k.lower() not in ("transfer-encoding", "content-encoding")
            }
            resp = web.StreamResponse(status=upstream.status, headers=resp_headers)
            await resp.prepare(request)

            t0 = time.time()
            chunk_count = 0
            total_bytes = 0
            async for chunk in upstream.content.iter_chunked(4096):
                await resp.write(chunk)
                chunk_count += 1
                total_bytes += len(chunk)

            await resp.write_eof()
            elapsed = time.time() - t0
            _log(
                f"[{_ts()}]     #{req_num:>3} ← DONE  "
                f"status={upstream.status}  chunks={chunk_count}  "
                f"bytes={total_bytes}  elapsed={elapsed:.2f}s"
            )

    except Exception as exc:
        _log(f"[{_ts()}]     #{req_num:>3} ← ERROR  {exc}")
        if not resp.prepared:  # type: ignore[possibly-undefined]
            return web.Response(status=502, text=str(exc))

    finally:
        if fp in _in_flight and _in_flight[fp][0] == req_num:
            del _in_flight[fp]
        # Remember this fingerprint so sequential duplicates are caught
        _recent[fp] = (req_num, time.time())

    return resp


async def make_app(target: str) -> web.Application:
    app = web.Application(client_max_size=100 * 1024 * 1024)

    # Split target URL into base (scheme+host+port) and explicit path prefix.
    # e.g. "http://localhost:8000/v1" → base="http://localhost:8000", prefix="/v1"
    parsed = urlsplit(target)
    base = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    path_prefix = parsed.path.rstrip("/")  # "" or "/v1" etc.

    app["target"] = base
    app["path_prefix"] = path_prefix

    async def _on_startup(app: web.Application) -> None:
        app["session"] = aiohttp.ClientSession()

    async def _on_cleanup(app: web.Application) -> None:
        await app["session"].close()

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_route("*", "/{path_info:.*}", proxy_handler)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug proxy for vllm-mlx duplicate request detection")
    parser.add_argument("--listen", type=int, default=8001, help="Port to listen on (default: 8001)")
    parser.add_argument("--target", default="http://localhost:8000",
                        help="Target vllm-mlx URL (default: http://localhost:8000)")
    args = parser.parse_args()

    parsed = urlsplit(args.target)
    explicit_prefix = parsed.path.rstrip("/")

    sys.stdout.write(f"🔍 Debug proxy listening on http://localhost:{args.listen}\n")
    sys.stdout.write(f"   Forwarding to: {args.target}\n")
    if explicit_prefix:
        sys.stdout.write(f"   Path prefix: {explicit_prefix} (prepended to all requests)\n")
    else:
        sys.stdout.write(f"   Auto /v1 prefix: ON — /chat/completions → /v1/chat/completions\n")
    sys.stdout.write(f"   Point Kilroy at: http://localhost:{args.listen}  (no /v1 in ai_url)\n")
    sys.stdout.write(f"   Duplicate requests shown in yellow with ⚠️\n\n")
    sys.stdout.flush()

    web.run_app(
        make_app(args.target),
        host="127.0.0.1",
        port=args.listen,
        access_log=None,
        print=lambda *_: None,  # suppress aiohttp's own startup banner
    )


if __name__ == "__main__":
    main()
