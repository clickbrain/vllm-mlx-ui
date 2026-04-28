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
# Pull first to avoid rejection if any commits landed on origin since we started
git pull --rebase
git push origin main "${TAG}"

# 6. Wait for GitHub to generate the tarball (usually ready in < 10s)
TARBALL_URL="https://github.com/clickbrain/vllm-mlx-ui/archive/refs/tags/${TAG}.tar.gz"
echo "→ Waiting for GitHub tarball to become available..."
for i in $(seq 1 30); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$TARBALL_URL")
  if [[ "$STATUS" == "200" ]]; then
    echo "  ✓ Tarball ready (attempt ${i})"
    break
  fi
  if [[ "$i" == "30" ]]; then
    echo "  ✗ Tarball not available after 60s — aborting"
    exit 1
  fi
  sleep 2
done

# 7. Compute SHA256
echo "→ Computing SHA256..."
SHA256=$(curl -sL "$TARBALL_URL" | shasum -a 256 | cut -d' ' -f1)
echo "  sha256: ${SHA256}"

# 8. Update formula in-place — this is the ONLY formula update; the bot is disabled
echo "→ Updating Homebrew formula..."
sed -i '' "s|url \"https://github.com/clickbrain/vllm-mlx-ui/archive/refs/tags/v[^\"]*\"|url \"${TARBALL_URL}\"|" Formula/vllm-mlx-ui.rb
sed -i '' "s|sha256 \"[a-f0-9]*\"|sha256 \"${SHA256}\"|" Formula/vllm-mlx-ui.rb
sed -i '' "s|version \"[^\"]*\"|version \"${VERSION}\"|" Formula/vllm-mlx-ui.rb

git add Formula/vllm-mlx-ui.rb
git commit -m "chore: update formula to ${TAG}

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Released ${TAG} — formula already updated."
echo "     brew upgrade vllm-mlx-ui is ready NOW."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
