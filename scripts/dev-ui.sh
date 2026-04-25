#!/usr/bin/env bash
# dev-ui.sh — starts the DEV mgmt_server on port 8502, then launches the Vue dev server.
#
# The Homebrew vllm-mlx-ui also starts a mgmt_server on 8502.  This script kills
# any process already bound to that port first, then starts the dev repo version
# so all the new endpoints (/server/load, /models/search, /benchmark/run, etc.)
# are available to the Vue UI.
#
# Usage (one terminal is enough):
#   cd /Users/bradn/Documents/dev/vllm-mlx
#   bash scripts/dev-ui.sh
#
# Then open http://localhost:5173

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Kill whatever is already on 8502 (Homebrew mgmt_server, if running)
EXISTING=$(lsof -ti tcp:8502 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
  echo "Stopping existing process on port 8502 (PID $EXISTING)..."
  kill "$EXISTING" 2>/dev/null || true
  sleep 1
fi

echo "Starting dev mgmt_server on port 8502..."
python3 -c "
import sys; sys.path.insert(0, '$REPO')
from vllm_mlx.dashboard.mgmt_server import start_mgmt_server
start_mgmt_server(host='127.0.0.1', port=8502)
" &
MGMT_PID=$!
echo "Dev mgmt_server running (PID $MGMT_PID)"

# Wait for it to accept connections
for i in $(seq 1 10); do
  sleep 0.5
  curl -s http://localhost:8502/health >/dev/null 2>&1 && break
done

echo "Starting Vue dev server → http://localhost:5173"
cd "$REPO/ui" && npm run dev

# Cleanup on exit
kill $MGMT_PID 2>/dev/null || true
