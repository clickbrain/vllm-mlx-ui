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
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  vllm-mlx dashboard pre-deploy checks"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Syntax check ────────────────────────────────────────────────────────
echo "1. Python syntax"
for f in "$DASHBOARD"/_ui.py "$DASHBOARD"/server_manager.py \
          "$DASHBOARD"/mgmt_server.py "$DASHBOARD"/update_checker.py \
          "$DASHBOARD"/app.py; do
  if python3 -m py_compile "$f" 2>&1; then
    ok "$(basename "$f")"
  else
    fail "$(basename "$f") — syntax error"
  fi
done

echo ""
echo "2. Forbidden patterns"

# ── 2a. Deprecated Streamlit use_container_width ──────────────────────────
if grep -rn "use_container_width" "$DASHBOARD"/ --include="*.py" -q; then
  fail "use_container_width found (use width=\"stretch\" or width=\"content\")"
  grep -rn "use_container_width" "$DASHBOARD"/ --include="*.py" | head -5
else
  ok "No deprecated use_container_width"
fi

# ── 2b. st.fragment with run_every on LARGE sections ─────────────────────
# Acceptable: fragment covers only a small status banner (loading state).
# NOT acceptable: fragment covers an entire page or large content area.
# Check that no fragment with run_every wraps more than ~10 lines of content.
# Simple heuristic: flag if run_every fragment appears outside an if-block
# that guards a loading/starting state.
# For now, only flag if it appears at top-level page scope (not inside an if).
_frag_raw=$(grep -n "fragment.*run_every\|run_every.*fragment" "$DASHBOARD"/_ui.py 2>/dev/null || true)
if [[ -n "$_frag_raw" ]]; then
  # Verify each occurrence is inside a conditional loading guard
  _bad=0
  while IFS= read -r line; do
    lineno=$(echo "$line" | cut -d: -f1)
    # Check the 3 lines before this one for a guard like 'if status["running"] and not status["healthy"]'
    context=$(sed -n "$((lineno-4)),$((lineno-1))p" "$DASHBOARD"/_ui.py 2>/dev/null)
    if ! echo "$context" | grep -q "not.*healthy\|loading\|starting"; then
      echo "  ⚠️  Unguarded @st.fragment(run_every=...) at line $lineno — verify it only covers a small area"
      _bad=1
    fi
  done <<< "$_frag_raw"
  if [[ $_bad -eq 0 ]]; then
    ok "@st.fragment(run_every=...) present but guarded to loading state only (OK)"
  else
    fail "@st.fragment(run_every=...) found outside a loading guard — may cause large-area grey-fade"
  fi
else
  ok "No @st.fragment(run_every=...) polling"
fi

# ── 2c. Wrong brew command in UI text ────────────────────────────────────
if grep -rn "reinstall.*--fetch-HEAD\|--fetch-HEAD.*reinstall" "$DASHBOARD"/ --include="*.py" -q; then
  fail "brew reinstall --fetch-HEAD found — --fetch-HEAD is invalid for reinstall; use brew upgrade --fetch-HEAD"
  grep -rn "reinstall.*--fetch-HEAD\|--fetch-HEAD.*reinstall" "$DASHBOARD"/ --include="*.py" | head -5
else
  ok "No invalid brew reinstall --fetch-HEAD"
fi

# ── 2d. Direct inference port calls in remote code paths ────────────────
# Remote mode must route everything through the mgmt API, not localhost:8000
# Only flag actual HTTP requests to localhost/127.0.0.1:8000, not config defaults
if grep -rn "requests\.\(get\|post\|delete\|put\).*localhost:8000\|requests\.\(get\|post\|delete\|put\).*127\.0\.0\.1:8000" "$DASHBOARD"/server_manager.py -q 2>/dev/null; then
  fail "Direct requests.* call to localhost:8000 found in server_manager.py — remote paths must use mgmt API proxy"
  grep -rn "requests\.\(get\|post\|delete\|put\).*localhost:8000\|requests\.\(get\|post\|delete\|put\).*127\.0\.0\.1:8000" "$DASHBOARD"/server_manager.py | head -5
else
  ok "No raw localhost:8000 HTTP calls in server_manager.py"
fi

# ── 2e. Relaunch subprocess must have start_new_session=True ────────────
if grep -q "start_new_session=True" "$DASHBOARD"/update_checker.py 2>/dev/null; then
  ok "Relaunch subprocess has start_new_session=True"
else
  fail "start_new_session=True missing from update_checker.py relaunch() — new process will die when parent os._exit()s"
fi

# ── 3. Config consistency: max_tokens / max_request_tokens ──────────────
echo ""
echo "3. Config consistency"
if grep -n "max_request_tokens" "$DASHBOARD"/_ui.py | grep -q "max_tokens"; then
  ok "max_request_tokens synced to max_tokens in save path"
else
  fail "max_request_tokens not synced to max_tokens in _ui.py save path — check config save block"
fi

# ── 4. README / docs ────────────────────────────────────────────────────
echo ""
echo "4. Documentation"
if grep -rn "reinstall.*--fetch-HEAD\|--fetch-HEAD.*reinstall" "$REPO/README.md" -q 2>/dev/null; then
  fail "README.md contains invalid brew reinstall --fetch-HEAD"
else
  ok "README.md: no invalid reinstall command"
fi

# ── Summary ──────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $FAIL -eq 0 ]]; then
  echo "  ✅ All $PASS checks passed — safe to deploy"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  exit 0
else
  echo "  ❌ $FAIL check(s) failed, $PASS passed — DO NOT deploy"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  exit 1
fi
