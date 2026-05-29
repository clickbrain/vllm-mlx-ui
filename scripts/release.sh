#!/usr/bin/env bash
# release.sh — Atomic release script for vllm-mlx-ui
#
# Usage: ./scripts/release.sh 0.3.70
#
# Does ALL steps in order. If any step fails, it stops with a clear error.
# Never bump the version manually — use this script so nothing gets missed.
#
# Handles:
#   - Main repo: bump → build → commit → tag → push
#   - Tap repo: clone → update formula → commit → push

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>  (e.g. $0 0.3.70)"
  exit 1
fi

TAG="v${VERSION}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAP_REPO="clickbrain/homebrew-vllm-mlx-ui"
TAP_CLONE_DIR=""

cleanup() {
  if [[ -n "$TAP_CLONE_DIR" && -d "$TAP_CLONE_DIR" ]]; then
    rm -rf "$TAP_CLONE_DIR"
  fi
}
trap cleanup EXIT

cd "$REPO_ROOT"

# ── QA Gate ────────────────────────────────────────────────
# release.sh REQUIRES a passing QA sign-off on the current commit.
# Run the QA Guardian agent and then: scripts/qa-sign-off.sh GREEN "summary"

SIGNOFF_FILE="${REPO_ROOT}/.qa-signoff"

if [[ ! -f "$SIGNOFF_FILE" ]]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  🔴 BLOCKED — No QA sign-off found."
  echo ""
  echo "  Before releasing, run the QA Guardian agent and then:"
  echo "    scripts/qa-sign-off.sh GREEN \"summary of findings\""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

# Read sign-off values
SIGNOFF_VERDICT=$(grep '^VERDICT=' "$SIGNOFF_FILE" | cut -d= -f2)
SIGNOFF_COMMIT=$(grep '^COMMIT=' "$SIGNOFF_FILE" | cut -d= -f2)
SIGNOFF_SUMMARY=$(grep '^SUMMARY=' "$SIGNOFF_FILE" | cut -d= -f2-)
HEAD_SHA=$(git rev-parse HEAD)

if [[ "$SIGNOFF_COMMIT" != "$HEAD_SHA" ]]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  🔴 BLOCKED — QA sign-off is stale."
  echo ""
  echo "  Sign-off commit : ${SIGNOFF_COMMIT:0:12}"
  echo "  Current HEAD    : ${HEAD_SHA:0:12}"
  echo ""
  echo "  New commits have been made since the last QA review."
  echo "  Re-run QA Guardian and sign off on the current commit:"
  echo "    scripts/qa-sign-off.sh GREEN \"summary\""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

if [[ "$SIGNOFF_VERDICT" == "RED" ]]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  🔴 BLOCKED — QA verdict is RED."
  echo ""
  echo "  Summary: ${SIGNOFF_SUMMARY}"
  echo ""
  echo "  Fix all blocking issues, then re-run QA Guardian and sign off."
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

# ── Pre-flight checks ──────────────────────────────────────

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Releasing vllm-mlx-ui ${VERSION}"
echo "  QA: ${SIGNOFF_VERDICT} — ${SIGNOFF_SUMMARY}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check that the tag doesn't already exist
if git tag -l "$TAG" | grep -q .; then
  echo "  ✗ Tag ${TAG} already exists locally."
  echo "    Delete it first:  git tag -d ${TAG} && git push origin --delete ${TAG}"
  exit 1
fi

if git ls-remote --tags origin "$TAG" 2>/dev/null | grep -q .; then
  echo "  ✗ Tag ${TAG} already exists on remote (origin)."
  echo "    Delete it first:  git tag -d ${TAG} && git push origin --delete ${TAG}"
  exit 1
fi

# Check we can reach the tap repo before doing any work
echo "→ Checking tap repo access..."
if ! git ls-remote "https://github.com/${TAP_REPO}.git" HEAD &>/dev/null; then
  echo "  ✗ Cannot read tap repo ${TAP_REPO}. Check your GitHub access."
  exit 1
fi

# ── 1. Bump version ────────────────────────────────────────
echo "→ Bumping version..."
sed -i '' "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" vllm_mlx/dashboard/__init__.py
sed -i '' "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml

# ── 2. Build Vue UI ────────────────────────────────────────
echo "→ Building Vue UI..."
npm run build --prefix ui

# ── 3. Sync dist into Python package ───────────────────────
echo "→ Syncing dist..."
rm -rf vllm_mlx/dashboard/ui_dist
cp -r ui/dist vllm_mlx/dashboard/ui_dist

# ── 4. Commit everything ───────────────────────────────────
echo "→ Committing..."
git add -A
git commit -m "${TAG}: release

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

# ── 5. Tag and push code + tag together ────────────────────
echo "→ Tagging and pushing code..."
git pull --rebase
git tag "${TAG}"
git push origin main "${TAG}"

# ── 5b. Create GitHub Release ──────────────────────────────
echo "→ Creating GitHub Release..."
gh release create "${TAG}" \
  --title "${TAG}" \
  --generate-notes \
  --repo "clickbrain/vllm-mlx-ui"
echo "  ✓ GitHub Release created"

# ── 6. Wait for GitHub to generate the tarball ─────────────
TARBALL_URL="https://github.com/clickbrain/vllm-mlx-ui/archive/refs/tags/${TAG}.tar.gz"
echo "→ Waiting for GitHub tarball to become available..."
for i in $(seq 1 45); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$TARBALL_URL")
  if [[ "$STATUS" == "200" || "$STATUS" == "302" ]]; then
    echo "  ✓ Tarball ready (attempt ${i})"
    break
  fi
  if [[ "$i" == "45" ]]; then
    echo "  ✗ Tarball not available after 90s — aborting"
    exit 1
  fi
  sleep 2
done

# ── 7. Compute SHA256 ──────────────────────────────────────
echo "→ Computing SHA256..."
SHA256=$(curl -sL "$TARBALL_URL" | shasum -a 256 | cut -d' ' -f1)
echo "  sha256: ${SHA256}"

# ── 8. Update formula in main repo ─────────────────────────
echo "→ Updating Homebrew formula in main repo..."
sed -i '' "s|url \"https://github.com/clickbrain/vllm-mlx-ui/archive/refs/tags/v[^\"]*\"|url \"${TARBALL_URL}\"|" Formula/vllm-mlx-ui.rb
sed -i '' "s|sha256 \"[a-f0-9]*\"|sha256 \"${SHA256}\"|" Formula/vllm-mlx-ui.rb
sed -i '' "s|version \"[^\"]*\"|version \"${VERSION}\"|" Formula/vllm-mlx-ui.rb

git add Formula/vllm-mlx-ui.rb
git commit -m "chore: update formula to ${TAG}

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main

# ── 9. Push same formula to the Homebrew tap repo ──────────
echo "→ Updating Homebrew formula in tap repo (${TAP_REPO})..."
TAP_CLONE_DIR="$(mktemp -d)"
git clone "https://github.com/${TAP_REPO}.git" "$TAP_CLONE_DIR"

TAP_FORMULA="${TAP_CLONE_DIR}/Formula/vllm-mlx-ui.rb"
sed -i '' "s|url \"https://github.com/clickbrain/vllm-mlx-ui/archive/refs/tags/v[^\"]*\"|url \"${TARBALL_URL}\"|" "$TAP_FORMULA"
sed -i '' "s|sha256 \"[a-f0-9]*\"|sha256 \"${SHA256}\"|" "$TAP_FORMULA"
sed -i '' "s|version \"[^\"]*\"|version \"${VERSION}\"|" "$TAP_FORMULA"

git -C "$TAP_CLONE_DIR" add -A
git -C "$TAP_CLONE_DIR" commit -m "chore: update formula to ${TAG}"
git -C "$TAP_CLONE_DIR" push origin main
echo "  ✓ Tap repo updated"

rm -f "${SIGNOFF_FILE}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Released ${TAG}"
echo "     brew update && brew upgrade vllm-mlx-ui"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
