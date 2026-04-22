#!/usr/bin/env bash
# ============================================================
#  vllm-mlx Remote Dashboard Installer
#
#  Use this on a Mac (or Linux machine) that does NOT run
#  the AI server itself.  It installs only the lightweight
#  browser dashboard so you can control a vllm-mlx server
#  running on another machine on your network.
#
#  After installing, open the dashboard and go to
#  Settings → Remote Server to enter the server's IP address.
#  You can change it any time without reinstalling.
#
#  Usage:
#    bash install-remote.sh
#
#  Requirements:
#    - Python 3.10 or later  (any OS, any CPU)
# ============================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}ℹ️  $*${RESET}"; }
success() { echo -e "${GREEN}✅ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${RESET}"; }
error()   { echo -e "${RED}❌ $*${RESET}"; exit 1; }
step()    { echo -e "\n${BOLD}── $* ──${RESET}"; }

echo -e "${BOLD}"
echo "  vllm-mlx  —  Remote Dashboard Installer"
echo -e "${RESET}"
echo "  This installs a lightweight control panel (~30 MB)."
echo "  No AI model or GPU software will be installed."
echo "  All settings (server IP, ports) are configured inside the dashboard."
echo ""

# ── Check Python ─────────────────────────────────────────────
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
    error "Python 3.10+ not found. Install it from https://www.python.org/downloads/ then re-run this script."
fi

# ── Install dashboard deps ─────────────────────────────────────
step "Installing dashboard libraries"
info "Installing Streamlit, Plotly, Pandas, httpx (no MLX / no model weights)…"
"$PYTHON" -m pip install --upgrade pip -q
"$PYTHON" -m pip install "streamlit>=1.30.0" "plotly>=5.0.0" "pandas>=2.0.0" "requests" "httpx>=0.27.0" "fastapi" "uvicorn" -q
success "Dashboard libraries installed"

# ── Download dashboard files from GitHub ─────────────────────
step "Downloading dashboard files"
INSTALL_DIR="$HOME/.vllm_mlx_remote"
mkdir -p "$INSTALL_DIR"

REPO="clickbrain/vllm-mlx-ui"
GITHUB_RAW="https://raw.githubusercontent.com/${REPO}/main"

# Fallback to upstream repo if clickbrain/vllm-mlx-ui is unavailable
if ! curl -fsSL --head "${GITHUB_RAW}/vllm_mlx/dashboard/_ui.py" &>/dev/null; then
    GITHUB_RAW="https://raw.githubusercontent.com/waybarrios/vllm-mlx/main"
    info "Using waybarrios/vllm-mlx source"
fi

FILES=(
    "vllm_mlx/dashboard/_ui.py"
    "vllm_mlx/dashboard/server_manager.py"
    "vllm_mlx/dashboard/model_manager.py"
    "vllm_mlx/dashboard/benchmark_runner.py"
    "vllm_mlx/dashboard/mgmt_server.py"
    "vllm_mlx/dashboard/__init__.py"
    "vllm_mlx/dashboard/app.py"
)
mkdir -p "$INSTALL_DIR/vllm_mlx/dashboard"
touch "$INSTALL_DIR/vllm_mlx/__init__.py"

for FILE in "${FILES[@]}"; do
    DEST="$INSTALL_DIR/$FILE"
    info "  $FILE"
    curl -fsSL "$GITHUB_RAW/$FILE" -o "$DEST" || error "Failed to download $FILE — check your internet connection."
done

# Streamlit config to allow iFrame embedding
mkdir -p "$INSTALL_DIR/.streamlit"
cat > "$INSTALL_DIR/.streamlit/config.toml" << 'TOML'
[server]
enableXsrfProtection = false
enableCORS = false

[browser]
gatherUsageStats = false
TOML

success "Dashboard files downloaded to $INSTALL_DIR"

# ── Create launch shortcut ────────────────────────────────────
step "Creating launch shortcut"

if [[ "$(uname -s)" == "Darwin" ]]; then
    LAUNCH_SCRIPT="$HOME/Desktop/vllm-mlx Remote.command"
    cat > "$LAUNCH_SCRIPT" << LAUNCH
#!/usr/bin/env bash
cd "$INSTALL_DIR"
echo "Starting vllm-mlx remote dashboard…"
"$PYTHON" -m streamlit run vllm_mlx/dashboard/_ui.py
LAUNCH
    chmod +x "$LAUNCH_SCRIPT"
    success "Shortcut created: 'vllm-mlx Remote.command' on your Desktop"
else
    LAUNCH_SCRIPT="$HOME/start-vllm-mlx-remote.sh"
    cat > "$LAUNCH_SCRIPT" << LAUNCH
#!/usr/bin/env bash
cd "$INSTALL_DIR"
"$PYTHON" -m streamlit run vllm_mlx/dashboard/_ui.py
LAUNCH
    chmod +x "$LAUNCH_SCRIPT"
    success "Shortcut created: ~/start-vllm-mlx-remote.sh"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  Remote dashboard installed! 🎉                      ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
if [[ "$(uname -s)" == "Darwin" ]]; then
    echo -e "  • Double-click ${BOLD}'vllm-mlx Remote.command'${RESET} on your Desktop"
else
    echo -e "  • Run: ${BOLD}~/start-vllm-mlx-remote.sh${RESET}"
fi
echo ""
echo -e "  ${BOLD}First-time setup (takes 30 seconds):${RESET}"
echo "  1. The dashboard opens in your browser automatically"
echo "  2. Click ⚙️ Settings in the left sidebar"
echo "  3. Scroll to 🔗 Remote Server"
echo "  4. Enter the IP address of the Mac running vllm-mlx"
echo "     Example: http://192.168.1.42:8000 and http://192.168.1.42:8502"
echo "  5. Click Save — you now have full remote control"
echo ""
echo "  You can change the server address any time in Settings without reinstalling."
echo ""
