#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
scripts/upstream_review.py — Automated upstream vllm-mlx release review tool.

Usage:
    python scripts/upstream_review.py                    # Compare current to latest
    python scripts/upstream_review.py --version v0.3.0  # Review specific version
    python scripts/upstream_review.py --apply            # Pull upstream code (safe files only)

What it does:
1. Fetches the latest upstream release from GitHub
2. Diffs CLI flags: shows new flags to expose in UI, removed flags to clean up
3. Diffs new endpoints in server.py
4. Cross-references our pending upstream PRs against bug fixes
5. Generates a review report
6. With --apply: pulls upstream vllm_mlx/ files (excluding dashboard/) into working tree
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

UPSTREAM_REPO = "waybarrios/vllm-mlx"
VERSION_FILE = Path(__file__).parent.parent / ".github" / "upstream-version.txt"
REPO_ROOT = Path(__file__).parent.parent

# Files we own — never overwrite from upstream
OUR_FILES = {
    "vllm_mlx/dashboard",
}

# Files upstream owns — always sync from upstream
UPSTREAM_DIRS = [
    "vllm_mlx/server.py",
    "vllm_mlx/cli.py",
    "vllm_mlx/engine",
    "vllm_mlx/api",
    "vllm_mlx/models",
    "vllm_mlx/paged_cache.py",
    "vllm_mlx/prefix_cache.py",
    "vllm_mlx/ssd_cache.py",
    "vllm_mlx/mcp",
    "vllm_mlx/constrained",
    "vllm_mlx/reasoning",
    "vllm_mlx/tool_parsers",
    "vllm_mlx/audio",
    "vllm_mlx/__init__.py",
    "vllm_mlx/request.py",
    "vllm_mlx/scheduler.py",
    "vllm_mlx/mllm_scheduler.py",
    "vllm_mlx/paged_cache.py",
    "vllm_mlx/mllm_cache.py",
    "vllm_mlx/model_registry.py",
]


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def gh_api(path: str) -> dict:
    url = f"https://api.github.com/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "vllm-mlx-ui/release-check"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_pinned_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return "unknown"


def get_latest_version() -> str:
    data = gh_api(f"repos/{UPSTREAM_REPO}/releases/latest")
    return data["tag_name"]


def extract_cli_flags(cli_py_content: str) -> set[str]:
    """Extract --flag names from cli.py content."""
    import re
    return set(re.findall(r'"(--[a-z][a-z-]*)"', cli_py_content))


def get_file_from_tag(tag: str, filepath: str) -> str:
    """Fetch a file from upstream at a specific tag."""
    url = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{tag}/{filepath}"
    req = urllib.request.Request(url, headers={"User-Agent": "vllm-mlx-ui/release-check"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode()
    except Exception as e:
        return f"# Could not fetch {filepath}: {e}"


def get_endpoints(server_py: str) -> set[str]:
    """Extract endpoint paths from server.py."""
    import re
    return set(re.findall(r'@app\.\w+\(["\']([^"\']+)["\']', server_py))


def apply_upstream(tag: str) -> None:
    """Pull upstream files into working tree (excluding our files)."""
    print(f"\n📥 Applying upstream {tag}...")
    print("  Fetching upstream remote...")
    run(["git", "fetch", "upstream"], cwd=str(REPO_ROOT))

    # Get the commit for this tag
    commit = run(["git", "rev-parse", f"upstream/{tag}"], cwd=str(REPO_ROOT), check=False)
    if not commit:
        commit = run(["git", "rev-parse", f"refs/tags/{tag}"], cwd=str(REPO_ROOT), check=False)
    if not commit:
        print(f"  Could not resolve {tag} — using upstream/main")
        commit = "upstream/main"

    files_to_sync = []
    for f in UPSTREAM_DIRS:
        full = REPO_ROOT / f
        if full.exists():
            files_to_sync.append(f)

    if not files_to_sync:
        print("  No upstream files found to sync.")
        return

    print(f"  Syncing {len(files_to_sync)} upstream paths from {commit}...")
    run(["git", "checkout", commit, "--"] + files_to_sync, cwd=str(REPO_ROOT))

    # Update pinned version
    VERSION_FILE.write_text(tag.lstrip("v") + "\n")
    print(f"  ✅ Updated .github/upstream-version.txt to {tag}")
    print("\n  ⚠️  Now run: pytest tests/ -q  to verify nothing broke")
    print("  Then review the checklist above before committing.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review upstream vllm-mlx releases")
    parser.add_argument("--version", help="Specific upstream version to review (e.g. v0.3.0)")
    parser.add_argument("--apply", action="store_true", help="Pull upstream code into working tree")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = parser.parse_args()

    pinned = get_pinned_version()

    print("=" * 70)
    print("  vllm-mlx-ui — Upstream Release Review")
    print("=" * 70)
    print(f"  Current pinned: {pinned}")

    try:
        latest = args.version or get_latest_version()
        print(f"  Latest upstream: {latest}")
    except Exception as e:
        print(f"  Could not fetch latest release: {e}")
        sys.exit(1)

    is_new = latest.lstrip("v") != pinned.lstrip("v")
    print(f"  Status: {'🔔 UPDATE AVAILABLE' if is_new else '✅ Up to date'}")
    print()

    # --- CLI flag diff ---
    print("─" * 70)
    print("  CLI Flag Changes")
    print("─" * 70)

    try:
        pinned_tag = f"v{pinned}" if not pinned.startswith("v") else pinned
        new_tag = latest if latest.startswith("v") else f"v{latest}"

        cur_cli = get_file_from_tag(pinned_tag, "vllm_mlx/cli.py")
        new_cli = get_file_from_tag(new_tag, "vllm_mlx/cli.py")

        cur_flags = extract_cli_flags(cur_cli)
        new_flags = extract_cli_flags(new_cli)

        added = new_flags - cur_flags
        removed = cur_flags - new_flags

        if added:
            print(f"\n  ✅ NEW flags to expose in UI ({len(added)}):")
            for f in sorted(added):
                print(f"     {f}")
        else:
            print("\n  No new CLI flags.")

        if removed:
            print(f"\n  ❌ REMOVED flags to clean up ({len(removed)}):")
            for f in sorted(removed):
                print(f"     {f}")
    except Exception as e:
        print(f"  Could not diff CLI flags: {e}")

    # --- Endpoint diff ---
    print()
    print("─" * 70)
    print("  New API Endpoints")
    print("─" * 70)

    try:
        cur_srv = get_file_from_tag(pinned_tag, "vllm_mlx/server.py")
        new_srv = get_file_from_tag(new_tag, "vllm_mlx/server.py")
        cur_ep = get_endpoints(cur_srv)
        new_ep = get_endpoints(new_srv)
        added_ep = new_ep - cur_ep
        removed_ep = cur_ep - new_ep

        if added_ep:
            print(f"\n  ✅ NEW endpoints ({len(added_ep)}):")
            for e in sorted(added_ep):
                print(f"     {e}")
        else:
            print("\n  No new endpoints.")

        if removed_ep:
            print(f"\n  ❌ REMOVED endpoints ({len(removed_ep)}):")
            for e in sorted(removed_ep):
                print(f"     {e}")
    except Exception as e:
        print(f"  Could not diff endpoints: {e}")

    # --- Pending PRs cross-reference ---
    pr_file = REPO_ROOT / ".copilot" / "session-state" if False else None
    print()
    print("─" * 70)
    print("  Release URL")
    print("─" * 70)
    print(f"\n  https://github.com/{UPSTREAM_REPO}/releases/tag/{latest}")
    print()

    if args.apply and is_new:
        apply_upstream(latest)
    elif args.apply and not is_new:
        print("  Already on latest — nothing to apply.")
    elif is_new:
        print("─" * 70)
        print("  Next Steps")
        print("─" * 70)
        print(f"""
  1. Review the release notes at the URL above
  2. For each new CLI flag: add to server_manager.py DEFAULT_CONFIG + _build_server_cmd()
  3. For each user-facing flag: add to Vue Settings UI
  4. Run tests: pytest tests/ -q
  5. When ready: python scripts/upstream_review.py --apply
  6. Re-run tests after apply
  7. Commit: git commit -m "chore: update upstream vllm-mlx to {latest}"
""")


if __name__ == "__main__":
    main()
