#!/usr/bin/env bash
# dev-ui.sh — starts the DEV mgmt_server on port 8502 (detached), then launches
# the Vue dev server in the foreground.
#
# The mgmt_server is started with nohup so it survives Vite exits and Ctrl+C.
# Its PID is saved to /tmp/vmui-mgmt-server.pid for clean shutdown.
#
# Usage (one terminal is enough):
#   cd /Users/bradn/Documents/dev/vllm-mlx
#   bash scripts/dev-ui.sh
#
# Then open http://localhost:5173
# Logs:  tail -f /tmp/vmui-mgmt.log

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="/tmp/vmui-mgmt-server.pid"

# Kill any previously saved mgmt_server instance
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ]; then
    echo "Stopping previous mgmt_server (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 0.5
  fi
  rm -f "$PID_FILE"
fi

# Also kill anything currently bound to 8502
EXISTING=$(lsof -ti tcp:8502 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
  echo "Stopping existing process on port 8502 (PID $EXISTING)..."
  kill "$EXISTING" 2>/dev/null || true
  sleep 1
fi

echo "Starting dev mgmt_server on 0.0.0.0:8502 (detached)..."
cd "$REPO"
nohup python3 -m vllm_mlx.dashboard.mgmt_server --host 0.0.0.0 --port 8502 > /tmp/vmui-mgmt.log 2>&1 &
MGMT_PID=$!
echo "$MGMT_PID" > "$PID_FILE"
echo "Dev mgmt_server running (PID $MGMT_PID)"
echo "Logs: tail -f /tmp/vmui-mgmt.log"

# Wait up to 10s for the server to accept connections
echo -n "Waiting for mgmt_server..."
for i in $(seq 1 20); do
  sleep 0.5
  if curl -s http://localhost:8502/health >/dev/null 2>&1; then
    echo " ready."
    break
  fi
  echo -n "."
done

# On exit: print info but do NOT kill the detached server
trap 'echo ""; echo "mgmt_server still running (PID $MGMT_PID). Stop with: kill $MGMT_PID"' EXIT

echo "Starting Vue dev server → http://localhost:5173"
cd "$REPO/ui" && npm run dev
