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

# ── 2b. st.fragment misuse — check for time.sleep + st.rerun() polling loops ─
# @st.fragment(run_every=N) is the CORRECT way to do live updates — it refreshes
# only its own area without a full-page grey fade.
# What IS bad: a bare time.sleep() at the END of a page function that acts as a
# polling loop (the old "sleep then rerun the whole page" anti-pattern).
# One-time action handlers (sleep 0.5 after a button click) are fine.
# Heuristic: flag only if time.sleep appears at top indentation level of a page
# function (i.e., 8-space indent = top of page body), NOT inside an if/with block.
if python3 -c "
import sys
lines = open('$DASHBOARD/_ui.py').read().splitlines()
for i, ln in enumerate(lines):
    # Only flag sleep at page-function top level (8 spaces = top of def body)
    stripped = ln.lstrip()
    indent = len(ln) - len(stripped)
    if ('time.sleep' in ln or '_time.sleep' in ln) and indent == 8:
        # Only flag sleep values >= 2s (polling intervals, not action-feedback delays)
        import re
        m = re.search(r'sleep\((\d+(?:\.\d+)?)\)', ln)
        if m and float(m.group(1)) < 2:
            continue
        next3 = ' '.join(lines[i:i+4])
        if 'st.rerun()' in next3:
            print(f'Line {i+1}: top-level time.sleep+rerun polling loop')
            sys.exit(1)
" 2>/dev/null; then
  ok "No top-level time.sleep+st.rerun() polling loops (good)"
else
  fail "time.sleep(N≥2) + st.rerun() at page top-level — use @st.fragment(run_every=N) instead to avoid grey-fade"
fi
if grep -qn "fragment.*run_every\|run_every.*fragment" "$DASHBOARD"/_ui.py 2>/dev/null; then
  ok "@st.fragment(run_every=...) used for live updates (correct pattern — no full-page fade)"
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
# New process is now launched from app.py's finally block, not update_checker.py
if grep -q "start_new_session=True" "$DASHBOARD"/app.py 2>/dev/null; then
  ok "Relaunch subprocess has start_new_session=True (in app.py)"
else
  fail "start_new_session=True missing from app.py relaunch block — new process may be killed with parent"
fi

# ── 2f. Critical server_manager public API must be present ───────────────
_sm_missing=""
for fn in start_server stop_server kill_stale_server get_server_status check_health load_config save_config; do
  if ! grep -q "^def ${fn}(" "$DASHBOARD"/server_manager.py 2>/dev/null; then
    _sm_missing="$_sm_missing $fn"
  fi
done
if [[ -z "$_sm_missing" ]]; then
  ok "server_manager.py public API complete"
else
  fail "server_manager.py missing functions:$_sm_missing"
fi

# ── 2g. Runtime import check — all attributes used by _ui.py ─────────────
if python3 -c "
from vllm_mlx.dashboard import server_manager as sm, model_manager as mm, benchmark_runner as br

sm_needed = ['start_server','stop_server','kill_stale_server','get_server_status','check_health',
             'load_config','save_config','get_logs','get_metrics','get_cache_stats','clear_cache',
             'get_server_url','PID_FILE','STATE_DIR','CONFIG_FILE','REASONING_PARSERS','TOOL_CALL_PARSERS',
             '_load_local_config']
mm_needed = ['delete_model','download_model','get_cache_total_size','get_cached_models',
             'get_hf_cache_dir','get_model_presets','search_mlx_models']
br_needed = ['clear_all_results','delete_result','load_results','RESULTS_FILE','run_benchmark']

all_missing = []
for mod, name, needed in [(sm,'sm',sm_needed),(mm,'mm',mm_needed),(br,'br',br_needed)]:
    missing = [f'{name}.{x}' for x in needed if not hasattr(mod, x)]
    all_missing.extend(missing)
if all_missing: raise SystemExit('Missing: ' + ', '.join(all_missing))
" 2>&1; then
  ok "All dashboard module attributes verified at runtime"
else
  fail "Dashboard module import check failed — see above"
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

# ── 5. Runtime safety checks ────────────────────────────────────────────
echo ""
echo "5. Runtime safety"

# 5a. Unguarded mlx.core import in Streamlit process (Process B)
# Importing mlx.core without checking sys.modules first initializes Metal GPU
# in the wrong process, wasting 200-500 MB of unified memory permanently.
if python3 -c "
import re, sys
for fname in ['$DASHBOARD/_ui.py', '$DASHBOARD/benchmark_runner.py']:
    lines = open(fname).read().splitlines()
    for i, ln in enumerate(lines):
        if re.search(r'^\s+import mlx\.core', ln):
            # Check that the preceding few lines contain a sys.modules guard
            context = '\n'.join(lines[max(0, i-3):i+1])
            if 'sys.modules' not in context:
                print(f'{fname}:{i+1}: unguarded import mlx.core — use sys.modules guard')
                sys.exit(1)
" 2>&1; then
  ok "No unguarded 'import mlx.core' in Streamlit/benchmark process code"
else
  fail "Unguarded 'import mlx.core' in Process B — triggers Metal init, wastes 200-500 MB. Use: if \"mlx.core\" in sys.modules: ..."
fi

# 5b. startup_model_behavior must be read in app.py (not just saved in _ui.py)
if grep -q "startup_model_behavior" "$DASHBOARD/app.py" 2>/dev/null; then
  ok "startup_model_behavior is read and acted on in app.py"
else
  fail "startup_model_behavior is saved in _ui.py but never read in app.py — normal restarts will never auto-start the model"
fi

# 5c. Streaming proxy must NOT return StreamingResponse inside async-with httpx.AsyncClient
# If it does, the client is closed before FastAPI iterates the generator.
if python3 -c "
import re, sys
text = open('$DASHBOARD/mgmt_server.py').read()
lines = text.splitlines()
in_client = False
client_indent = None
for i, ln in enumerate(lines):
    stripped = ln.lstrip()
    if not stripped:
        continue
    indent = len(ln) - len(stripped)
    if re.search(r'async with httpx\.AsyncClient', ln):
        in_client = True
        client_indent = indent
    elif in_client:
        if indent <= client_indent and stripped:
            in_client = False  # exited the with block
        elif 'return StreamingResponse' in ln:
            print(f'Line {i+1}: StreamingResponse returned inside async with httpx.AsyncClient — client closes before generator runs')
            sys.exit(1)
" 2>&1; then
  ok "Streaming proxy: httpx client not prematurely closed"
else
  fail "StreamingResponse returned inside 'async with httpx.AsyncClient' — move client creation inside the generator"
fi

# 5d. Direct CONFIG_FILE.write_text() in _ui.py bypasses save_config()
# save_config() provides backup, remote sync, and _LOCAL_ONLY_KEYS stripping
if python3 -c "
import re, sys
text = open('$DASHBOARD/_ui.py').read()
hits = [i+1 for i, ln in enumerate(text.splitlines()) if re.search(r'CONFIG_FILE\.write_text\b', ln)]
if hits:
    print('Direct CONFIG_FILE.write_text() at lines: ' + ', '.join(map(str, hits)))
    sys.exit(1)
" 2>&1; then
  ok "No direct CONFIG_FILE.write_text() calls in _ui.py (all writes go through save_config)"
else
  fail "_ui.py has direct CONFIG_FILE.write_text() call(s) — use sm.save_config() to get backup + remote sync + _LOCAL_ONLY_KEYS stripping"
fi

# 5e. force_release_memory must protect the Streamlit subprocess PID
if grep -q "STREAMLIT_PID_FILE" "$DASHBOARD/server_manager.py" 2>/dev/null; then
  ok "force_release_memory() protects the Streamlit subprocess PID (STREAMLIT_PID_FILE)"
else
  fail "STREAMLIT_PID_FILE not found in server_manager.py — remote Release Memory will kill the Streamlit dashboard"
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
