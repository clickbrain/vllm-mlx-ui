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

# Must be on main
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "  ✗ Must be on 'main' branch (currently on '${CURRENT_BRANCH}')."
  exit 1
fi

# Working tree must be clean (no uncommitted changes sneak into the release commit)
if ! git diff --exit-code --quiet || ! git diff --cached --exit-code --quiet; then
  echo "  ✗ Working tree has uncommitted changes. Commit or stash before releasing."
  git status --short
  exit 1
fi

# Sync with origin before any modifications so no unreviewed upstream commits
# enter the release tag. Fail fast if not current rather than silently rebasing
# mid-release.
echo "→ Syncing with origin/main..."
git fetch origin
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse origin/main)
if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
  echo "  ✗ Branch is not current with origin/main."
  echo "    Local : ${LOCAL_SHA:0:12}"
  echo "    Remote: ${REMOTE_SHA:0:12}"
  echo "    Run:  git pull --rebase  then re-run QA and sign off before releasing."
  exit 1
fi

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
# Allow "nothing to commit" for backend-only releases where no UI assets changed
git diff --cached --quiet && echo "  (no new files to commit — skipping release commit)" || git commit -m "${TAG}: release

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

# ── 5. Tag and push code + tag together ────────────────────
echo "→ Tagging and pushing code..."
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
    echo ""
    echo "  ⚠ Tag ${TAG} was already pushed. To complete the formula update manually:"
    echo "    1. Wait a minute, then check: curl -sI ${TARBALL_URL}"
    echo "    2. SHA256: curl -sL ${TARBALL_URL} | shasum -a 256"
    echo "    3. Update Formula/vllm-mlx-ui.rb (url, sha256, version)"
    echo "    4. git add Formula/ && git commit -m 'chore: update formula to ${TAG}' && git push"
    echo "    5. Clone tap and repeat: https://github.com/${TAP_REPO}"
    exit 1
  fi
  sleep 2
done

# ── 7. Compute SHA256 ──────────────────────────────────────
echo "→ Computing SHA256..."
SHA256=$(curl -sL "$TARBALL_URL" | shasum -a 256 | cut -d' ' -f1)
echo "  sha256: ${SHA256}"

# ── 8. Update formula in main repo ─────────────────────────
# NOTE: This commit is intentionally AFTER the tag. The SHA256 requires the
# GitHub tarball, which requires the tag to already be pushed — unavoidable
# circular dependency. The formula in this repo is cosmetic/reference only;
# Homebrew reads from the tap repo (homebrew-vllm-mlx-ui). This post-tag
# commit is the established pattern for every release in this project.
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
# Copy the full formula from the main repo so post_install, install steps, caveats,
# and all other formula body changes are always in sync with the main repo.
# Then patch in the correct URL/SHA/version computed above.
cp "${REPO_ROOT}/Formula/vllm-mlx-ui.rb" "$TAP_FORMULA"
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
