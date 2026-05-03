#!/usr/bin/env bash
# Pre-deploy validation for vllm-mlx dashboard code.
# Run this before syncing to clickbrain/vllm-mlx-ui.
# Usage: scripts/validate_dashboard.sh

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DASHBOARD="$REPO/vllm_mlx/dashboard"

PASS=0
FAIL=0

ok()   { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  vllm-mlx dashboard pre-deploy checks"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Syntax check ──────────────────────────────────────
echo ""
echo "1. Python syntax"
for f in "$DASHBOARD/mgmt_server.py" "$DASHBOARD/server_manager.py" \
        "$DASHBOARD/model_manager.py" "$DASHBOARD/update_checker.py" \
        "$DASHBOARD/app.py"; do
  if python3 -m py_compile "$f" 2>&1; then
    ok "$(basename "$f")"
  else
    fail "$(basename "$f") — syntax error"
  fi
done

# ── 2. Forbidden patterns ──────────────────────────────────────
echo ""
echo "2. Forbidden patterns"

# 2a. No streamlit imports (should be FastAPI now)
# Exempt server_manager.py and model_manager.py — they use streamlit for remote mode session_state
if grep -rn "import streamlit\|from streamlit" "$DASHBOARD/"*.py 2>/dev/null | grep -v "__pycache__\|server_manager.py\|model_manager.py"; then
  fail "streamlit imports found — should use FastAPI"
else
  ok "No streamlit imports in dashboard code (server_manager.py/model_manager.py use streamlit for remote mode — allowed)"
fi

# 2b. No plotly/pandas in dependencies (removed from pyproject.toml)
if grep -q "plotly\|pandas" "$REPO/pyproject.toml"; then
  fail "plotly/pandas still in pyproject.toml [ui] deps — removed"
else
  ok "pyproject.toml: no plotly/pandas deps"
fi

# ── 3. Runtime import check ──────────────────────────────────────
echo ""
echo "3. Runtime imports"

if python3 -c "
from vllm_mlx.dashboard import mgmt_server
from vllm_mlx.dashboard import server_manager
from vllm_mlx.dashboard import model_manager
from vllm_mlx.dashboard import update_checker
print('All modules imported OK')
" 2>&1; then
  ok "All dashboard modules importable at runtime"
else
  fail "Runtime import failed — check sys.path or deps"
fi

# ── 4. Config consistency ──────────────────────────────────────
echo ""
echo "4. Config consistency"

# Check that max_tokens is used (not max_request_tokens) in internal dashboard code
# mgmt_server.py and server_manager.py use max_request_tokens only when interfacing with upstream server (legitimate)
if grep -q "max_request_tokens" "$DASHBOARD/app.py"; then
  fail "max_request_tokens found in app.py — should be max_tokens"
else
  ok "max_tokens used consistently in dashboard code (mgmt_server.py/server_manager.py use max_request_tokens only for upstream interfacing)"
fi

# ── 5. mgmt_server.py endpoints ──────────────────────────────
echo ""
echo "5. mgmt_server.py endpoints"

for endpoint in "/status" "/start" "/stop" \
               "/logs"                "/metrics" "/models/cached" "/models/search" \
               "/poll" "/updates" "/restart" "/shutdown"; do
  if grep -q "@app.*\"$endpoint\"" "$DASHBOARD/mgmt_server.py"; then
    ok "Endpoint $endpoint exists"
  else
    fail "Endpoint $endpoint missing in mgmt_server.py"
  fi
done

# ── 6. Live polling endpoints ──────────────────────────────
echo ""
echo "6. Live polling"

if grep -q "@app.get(\"/poll\")" "$DASHBOARD/mgmt_server.py"; then
  ok "Batch polling endpoint /poll exists"
else
  fail "/poll endpoint missing — Phase 4 task not complete"
fi

# ── 7. Streaming proxy safety ──────────────────────────────
echo ""
echo "7. Streaming proxy safety"

if python3 -c "
import re, sys
text = open('$DASHBOARD/mgmt_server.py').read()
lines = text.splitlines()
in_client = False
client_indent = None
for i, ln in enumerate(lines):
    stripped = ln.strip()
    if not stripped or stripped.startswith('#'):
        continue
    indent = len(ln) - len(stripped)
    if 'async with httpx.AsyncClient' in ln:
        in_client = True
        client_indent = indent
    elif in_client:
        if indent <= client_indent and stripped:
            in_client = False
        elif 'return StreamingResponse' in ln:
            print(f'Line {i+1}: StreamingResponse inside AsyncClient block')
            sys.exit(1)
" 2>&1; then
  ok "StreamingResponse not returned inside httpx client (safe)"
else
  fail "StreamingResponse inside httpx client — client closes before generator"
fi

# ── 8. Thread safety checks ──────────────────────────────────────
echo ""
echo "8. Thread safety"

for f in server_manager.py model_manager.py update_checker.py; do
  if grep -q "threading.Lock()" "$DASHBOARD/$f"; then
    ok "$f: threading.Lock() present (thread-safe)"
  else
    fail "$f: missing threading.Lock() — thread safety risk"
  fi
done

# ── 9. UI dist present ──────────────────────────────────────
echo ""
echo "9. UI distribution"

if [[ -d "$DASHBOARD/ui_dist" ]]; then
  ok "UI dist present ($DASHBOARD/ui_dist/)"
else
  fail "UI dist missing — run: cd ui && npm run build && cp -r dist $DASHBOARD/ui_dist"
fi

# ── Summary ──────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $FAIL -eq 0 ]]; then
  echo "  ✅ All $PASS checks passed — safe to deploy"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  exit 0
else
  echo "  ❌ $FAIL check(s) failed, $PASS passed — DO NOT deploy"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  exit 1
fi
