#!/usr/bin/env bash
# release.sh — Atomic release script for vllm-mlx-ui
#
# Usage: ./scripts/release.sh 0.3.70
#
# Does ALL steps in order. If any step fails, it stops with a clear error.
# Never bump the version manually — use this script so nothing gets missed.

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>  (e.g. $0 0.3.70)"
  exit 1
fi

TAG="v${VERSION}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Releasing vllm-mlx-ui ${VERSION}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Bump version in Python package
echo "→ Bumping version..."
sed -i '' "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" vllm_mlx/dashboard/__init__.py
sed -i '' "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml

# 2. Build Vue UI
echo "→ Building Vue UI..."
npm run build --prefix ui

# 3. Sync dist into Python package
echo "→ Syncing dist..."
rm -rf vllm_mlx/dashboard/ui_dist
cp -r ui/dist vllm_mlx/dashboard/ui_dist

# 4. Commit everything
echo "→ Committing..."
git add -A
git commit -m "${TAG}: release

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

# 5. Tag and push code + tag together
echo "→ Tagging and pushing code..."
git tag "${TAG}"
git push origin main "${TAG}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Released ${TAG} — the GitHub Actions bot will update the"
echo "     Homebrew formula automatically. brew upgrade vllm-mlx-ui"
echo "     will deliver this version once the bot finishes (~1 min)."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
