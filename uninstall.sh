#!/usr/bin/env bash
# ============================================================
#  vllm-mlx Uninstaller
#  Removes vllm-mlx, the dashboard UI, and optionally the
#  downloaded models and all saved data.
#
#  Usage:
#    bash uninstall.sh
#
#  What it removes:
#    - The vllm-mlx Python package (pip or Homebrew)
#    - The Desktop launch shortcut
#    - Dashboard state: server config, logs, benchmark results,
#      chat history (~/.vllm_mlx_ui/)
#    - Optionally: downloaded AI models (~/.cache/huggingface/hub/)
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
echo "  vllm-mlx Uninstaller"
echo -e "${RESET}"
echo "  This will remove vllm-mlx and the dashboard from your Mac."
echo ""

# ── Confirm ──────────────────────────────────────────────────
read -r -p "  Are you sure you want to uninstall? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

# ── Detect Python ────────────────────────────────────────────
step "Detecting Python installation"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        info "Using $candidate"
        break
    fi
done

# ── Remove pip package ───────────────────────────────────────
step "Removing vllm-mlx package"

BREW_INSTALLED=false
if command -v brew &>/dev/null && brew list --formula 2>/dev/null | grep -q "^vllm-mlx-ui$"; then
    info "Detected Homebrew install"
    brew uninstall vllm-mlx-ui && success "Homebrew formula removed" || warn "brew uninstall failed — continuing"
    BREW_INSTALLED=true
fi

if [[ -n "$PYTHON" ]] && "$PYTHON" -m pip show vllm-mlx &>/dev/null 2>&1; then
    "$PYTHON" -m pip uninstall vllm-mlx -y && success "pip package removed" || warn "pip uninstall failed — may already be removed"
elif [[ "$BREW_INSTALLED" == "false" ]]; then
    info "vllm-mlx pip package not found — already uninstalled or not installed via pip"
fi

# ── Remove Desktop shortcut ──────────────────────────────────
step "Removing Desktop shortcut"
SHORTCUT="$HOME/Desktop/Start vllm-mlx.command"
if [[ -f "$SHORTCUT" ]]; then
    rm "$SHORTCUT"
    success "Removed '$SHORTCUT'"
else
    info "Desktop shortcut not found — skipping"
fi

# ── Remove dashboard state directory ────────────────────────
step "Removing dashboard state"
STATE_DIR="$HOME/.vllm_mlx_ui"
if [[ -d "$STATE_DIR" ]]; then
    info "Found: $STATE_DIR"
    info "Contents: server config, logs, benchmark results, chat history"
    read -r -p "  Remove $STATE_DIR? [y/N] " REMOVE_STATE
    if [[ "$REMOVE_STATE" =~ ^[Yy]$ ]]; then
        rm -rf "$STATE_DIR"
        success "Removed $STATE_DIR"
    else
        info "Skipped — your chat history and settings are preserved."
    fi
else
    info "State directory not found — skipping"
fi

# ── Optionally remove downloaded models ─────────────────────
step "Downloaded AI models"
HF_CACHE="${HF_HOME:-$HOME/.cache/huggingface}"
if [[ -d "$HF_CACHE/hub" ]]; then
    HF_SIZE=$(du -sh "$HF_CACHE/hub" 2>/dev/null | cut -f1 || echo "unknown")
    echo ""
    warn "Your downloaded AI models are stored at:"
    echo "    $HF_CACHE/hub   ($HF_SIZE)"
    echo ""
    echo "  These are large files downloaded from HuggingFace."
    echo "  They are NOT removed automatically — models can be reused by other tools."
    echo ""
    read -r -p "  Remove ALL downloaded models? This frees ${HF_SIZE} of disk space. [y/N] " REMOVE_MODELS
    if [[ "$REMOVE_MODELS" =~ ^[Yy]$ ]]; then
        # Only remove mlx-community models to be safe
        MLX_CACHE="$HF_CACHE/hub/models--mlx-community"
        if [[ -d "$MLX_CACHE" ]]; then
            MLX_SIZE=$(du -sh "$MLX_CACHE" 2>/dev/null | cut -f1 || echo "unknown")
            read -r -p "  Remove only mlx-community models ($MLX_SIZE)? [Y/n] " MLX_ONLY
            if [[ ! "$MLX_ONLY" =~ ^[Nn]$ ]]; then
                rm -rf "$MLX_CACHE"
                success "Removed mlx-community model cache ($MLX_SIZE freed)"
            else
                rm -rf "$HF_CACHE/hub"
                success "Removed entire HuggingFace model cache ($HF_SIZE freed)"
            fi
        else
            rm -rf "$HF_CACHE/hub"
            success "Removed HuggingFace model cache ($HF_SIZE freed)"
        fi
    else
        info "Model cache preserved at $HF_CACHE/hub"
    fi
else
    info "No HuggingFace cache found — skipping"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  Uninstall complete!                       ║${RESET}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════╝${RESET}"
echo ""
echo "  vllm-mlx has been removed from your Mac."
echo ""
echo "  To reinstall in the future:"
echo "    bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install.sh)"
echo ""
