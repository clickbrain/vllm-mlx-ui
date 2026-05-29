#!/usr/bin/env bash
# qa-sign-off.sh — Write a QA sign-off token that release.sh requires.
#
# Usage: ./scripts/qa-sign-off.sh <GREEN|YELLOW|RED> ["summary"]
#
# Called by the QA Guardian agent at the end of every review.
# release.sh will refuse to proceed unless this file exists and matches HEAD.

set -euo pipefail

VERDICT="${1:-}"
SUMMARY="${2:-No summary provided}"

if [[ -z "$VERDICT" ]]; then
  echo "Usage: $0 <GREEN|YELLOW|RED> [\"summary\"]"
  exit 1
fi

case "$VERDICT" in
  GREEN|YELLOW|RED) ;;
  *)
    echo "✗ Invalid verdict '$VERDICT'. Must be GREEN, YELLOW, or RED."
    exit 1
    ;;
esac

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIGNOFF_FILE="${REPO_ROOT}/.qa-signoff"
HEAD_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

cat > "$SIGNOFF_FILE" <<EOF
VERDICT=${VERDICT}
COMMIT=${HEAD_SHA}
TIMESTAMP=${TIMESTAMP}
SUMMARY=${SUMMARY}
EOF

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  QA Sign-off recorded"
echo "  Verdict  : ${VERDICT}"
echo "  Commit   : ${HEAD_SHA:0:12}"
echo "  Time     : ${TIMESTAMP}"
echo "  Summary  : ${SUMMARY}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ "$VERDICT" == "RED" ]]; then
  echo ""
  echo "  🔴 RED verdict — release.sh will BLOCK until issues are fixed."
  echo "     Fix all blocking issues, then re-run QA and sign off GREEN or YELLOW."
fi
