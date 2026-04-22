#!/usr/bin/env bash
# ============================================================
#  vllm-mlx Installer
#  Installs vllm-mlx + the dashboard UI on Apple Silicon Macs
#  and downloads the default Llama 3.2 3B model.
#
#  Usage:
#    bash install.sh
#
#  Requirements:
#    - macOS 13 (Ventura) or later
#    - Apple Silicon (M1 / M2 / M3 / M4)
#    - Python 3.10 or later
# ============================================================

set -euo pipefail

# ── Colours ─────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}ℹ️  $*${RESET}"; }
success() { echo -e "${GREEN}✅ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${RESET}"; }
error()   { echo -e "${RED}❌ $*${RESET}"; exit 1; }
step()    { echo -e "\n${BOLD}── $* ──${RESET}"; }

echo -e "${BOLD}"
echo "  ██╗   ██╗██╗     ██╗     ███╗   ███╗    ███╗   ███╗██╗     ██╗  ██╗"
echo "  ██║   ██║██║     ██║     ████╗ ████║    ████╗ ████║██║     ╚██╗██╔╝"
echo "  ██║   ██║██║     ██║     ██╔████╔██║    ██╔████╔██║██║      ╚███╔╝ "
echo "  ╚██╗ ██╔╝██║     ██║     ██║╚██╔╝██║    ██║╚██╔╝██║██║      ██╔██╗ "
echo "   ╚████╔╝ ███████╗███████╗██║ ╚═╝ ██║    ██║ ╚═╝ ██║███████╗██╔╝ ██╗"
echo "    ╚═══╝  ╚══════╝╚══════╝╚═╝     ╚═╝    ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝"
echo -e "${RESET}"
echo -e "  Welcome! This installer sets up vllm-mlx on your Apple Silicon Mac."
echo -e "  It will install the software and download a starter AI model (~2 GB)."
echo ""

# ── Check: macOS ────────────────────────────────────────────
step "Checking your Mac"
OS=$(uname -s)
ARCH=$(uname -m)
[[ "$OS" == "Darwin" ]] || error "This installer is for macOS only."
[[ "$ARCH" == "arm64" ]] || error "This installer requires Apple Silicon (M1/M2/M3/M4). Your Mac uses $ARCH."
MACOS_VER=$(sw_vers -productVersion)
success "macOS $MACOS_VER on Apple Silicon detected"

# ── Check: Python ───────────────────────────────────────────
step "Checking Python"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        VER=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJOR=${VER%%.*}; MINOR=${VER##*.}
        if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 10 ]]; then
            PYTHON="$candidate"
            success "Found $candidate (Python $VER)"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    warn "Python 3.10+ not found."
    echo ""
    echo "  Please install Python first, then run this script again."
    echo ""
    echo "  Option A — Homebrew (recommended):"
    echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "    brew install python@3.11"
    echo ""
    echo "  Option B — Download from python.org:"
    echo "    https://www.python.org/downloads/macos/"
    echo ""
    exit 1
fi

# ── Check: pip ──────────────────────────────────────────────
step "Checking pip"
"$PYTHON" -m pip --version &>/dev/null || error "pip is not available. Run: $PYTHON -m ensurepip --upgrade"
success "pip is available"

# ── Upgrade pip & setuptools ────────────────────────────────
step "Updating pip"
"$PYTHON" -m pip install --upgrade pip setuptools wheel -q
success "pip updated"

# ── Install vllm-mlx with UI extras ─────────────────────────
step "Installing vllm-mlx"

# Detect if we are inside the repo (developer mode) or running standalone
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if vllm-mlx is already installed
ALREADY_INSTALLED=false
if "$PYTHON" -m pip show vllm-mlx &>/dev/null 2>&1; then
    INSTALLED_VER=$("$PYTHON" -m pip show vllm-mlx 2>/dev/null | grep '^Version:' | awk '{print $2}')
    warn "vllm-mlx ${INSTALLED_VER} is already installed — upgrading to latest…"
    ALREADY_INSTALLED=true
else
    info "This installs vllm-mlx plus the dashboard, chart libraries, and all"
    info "required dependencies (MLX, HuggingFace Hub, FastAPI, etc.)"
    info "This may take 2–5 minutes on a fast connection…"
    echo ""
fi
if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    info "Detected repo directory — installing in editable mode"
    "$PYTHON" -m pip install -e "$SCRIPT_DIR[ui]" -q
else
    info "Downloading and installing from GitHub…"
    GITHUB_REPO="https://github.com/waybarrios/vllm-mlx.git"
    "$PYTHON" -m pip install "vllm-mlx[ui] @ git+${GITHUB_REPO}" -q
fi
success "vllm-mlx installed"

# ── Verify the CLI entry points ──────────────────────────────
step "Verifying installation"
for cmd in vllm-mlx vllm-mlx-ui; do
    if "$PYTHON" -m pip show vllm-mlx &>/dev/null && command -v "$cmd" &>/dev/null; then
        success "$cmd command is available"
    else
        # Try via python -m path
        warn "$cmd not found in PATH — this is usually fine, see note below"
    fi
done

# ── Download starter model ───────────────────────────────────
step "Downloading starter model"
MODEL="mlx-community/Llama-3.2-3B-Instruct-4bit"
info "Model: $MODEL"
info "Size: approximately 1.8 GB"
info "This is a fast, capable AI model that works well on all Apple Silicon Macs."
echo ""

"$PYTHON" - << PYEOF
import sys
MODEL = "$MODEL"
print("  Checking if model is already downloaded…")
try:
    from huggingface_hub import try_to_load_from_cache, scan_cache_dir
    # Check if this model already has weight files in the cache
    cache_info = scan_cache_dir()
    for repo in cache_info.repos:
        if repo.repo_id == MODEL and repo.size_on_disk > 50 * 1024 * 1024:
            for rev in repo.revisions:
                for f in rev.files:
                    if any(f.file_path.endswith(ext) for ext in ('.safetensors', '.npz', '.bin', '.gguf')):
                        print(f"  ✅ Model already cached at: {repo.repo_path}")
                        sys.exit(0)
except Exception:
    pass  # Fall through to download

print("  Connecting to HuggingFace Hub…")
try:
    from huggingface_hub import snapshot_download
    print("  Downloading — this may take a few minutes…")
    path = snapshot_download(
        repo_id=MODEL,
        local_files_only=False,
        ignore_patterns=["*.pt", "*.bin", "original/*"],
    )
    print(f"  ✅ Model downloaded to: {path}")
except Exception as e:
    print(f"  ⚠️  Download failed: {e}")
    print("  You can download it later from the Models tab in the dashboard.")
    sys.exit(0)
PYEOF

# ── Create launch script ─────────────────────────────────────
step "Creating launch shortcut"
LAUNCH_SCRIPT="$HOME/Desktop/Start vllm-mlx.command"
cat > "$LAUNCH_SCRIPT" << LAUNCH
#!/usr/bin/env bash
# Double-click this file to start the vllm-mlx dashboard
cd "\$HOME"
echo "Starting vllm-mlx dashboard…"
if command -v vllm-mlx-ui &>/dev/null; then
    vllm-mlx-ui
else
    $PYTHON -m vllm_mlx.dashboard.app
fi
LAUNCH
chmod +x "$LAUNCH_SCRIPT"
success "Launch shortcut created on your Desktop: 'Start vllm-mlx.command'"

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  Installation complete! 🎉                 ║${RESET}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}To start the dashboard:${RESET}"
echo ""
echo -e "  • Double-click  ${BOLD}'Start vllm-mlx.command'${RESET}  on your Desktop"
echo -e "  • Or run in Terminal:  ${BOLD}vllm-mlx-ui${RESET}"
echo ""
echo -e "  ${BOLD}Quick start:${RESET}"
echo -e "  1. The dashboard will open in your browser automatically"
echo -e "  2. Go to the ${BOLD}Server${RESET} page — your starter model is already selected"
echo -e "  3. Click ${BOLD}▶ Start Server${RESET}"
echo -e "  4. Go to ${BOLD}Playground${RESET} to start chatting!"
echo ""
