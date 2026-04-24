# frozen_string_literal: true

# Homebrew formula for vllm-mlx-ui
# Tap:  brew tap clickbrain/vllm-mlx-ui https://github.com/clickbrain/vllm-mlx-ui
# Install: brew install clickbrain/vllm-mlx-ui/vllm-mlx-ui
#
# This formula installs the vllm-mlx inference server and the browser-based
# dashboard UI into an isolated Python virtual environment managed by Homebrew.
# All entry-point commands (vllm-mlx, vllm-mlx-ui) are symlinked into
# Homebrew's bin/ directory, so they are always on PATH.

class VllmMlxUi < Formula
  desc "Apple Silicon LLM inference server with browser-based dashboard UI"
  homepage "https://github.com/clickbrain/vllm-mlx-ui"

  # Stable release — brew upgrade works normally with this URL.
  url "https://github.com/clickbrain/vllm-mlx-ui/archive/refs/tags/v0.3.15.tar.gz"
  sha256 "565b44a1182673f416c5db6030eab19c1a15c4d83e15e839e9566a67a6f17b3d"
  version "0.3.15"

  # HEAD install: always gets the latest code from main branch.
  # Install with:  brew install --HEAD clickbrain/vllm-mlx-ui/vllm-mlx-ui
  head "https://github.com/clickbrain/vllm-mlx-ui.git", branch: "main"

  # Requires Apple Silicon — MLX only runs on Apple Silicon Macs
  depends_on arch: :arm64
  depends_on "python@3.11"

  # Don't let Homebrew rewrite dylib IDs inside the Python venv — the paths
  # are too long for the Mach-O header and the relinking isn't needed anyway.
  skip_clean "libexec"

  # ── Install ───────────────────────────────────────────────
  def install
    python = Formula["python@3.11"].opt_bin/"python3.11"
    venv   = libexec/"venv"

    # Create an isolated virtual environment
    system python, "-m", "venv", venv

    # Upgrade pip so it respects the build-system.requires in pyproject.toml.
    # pyproject.toml requires setuptools>=68, which includes setuptools.backends.legacy.
    # pip's build isolation downloads this automatically when building.
    system venv/"bin/pip", "install", "--upgrade", "pip"

    # Install the package with the [ui] extra (streamlit, plotly, pandas, httpx).
    system venv/"bin/pip", "install", ".[ui]"

    # Explicitly upgrade key dependencies to their latest compatible versions.
    # pip install . above satisfies minimum version constraints but won't
    # necessarily pick the newest release.  Upgrading explicitly ensures the
    # inference library and model-download tooling are always current.
    system venv/"bin/pip", "install", "--upgrade", "mlx-lm", "huggingface-hub"

    # Install stable launcher scripts into Homebrew's bin.
    #
    # We deliberately DO NOT use write_env_script / write_exec_script here.
    # Those helpers hardcode the versioned Cellar path inside the script body
    # (e.g. /opt/homebrew/Cellar/vllm-mlx-ui/0.3.15/libexec/...).  Every brew
    # upgrade writes a new Cellar path, changing the file's content and hash.
    # macOS Application Firewall keyed its allow-rule on that hash, so the rule
    # silently broke after every upgrade — forcing the user to re-authorise.
    #
    # Instead we write a tiny script whose body is IDENTICAL across every
    # version: it resolves its own real path at runtime and exec's the matching
    # venv binary from a stable relative offset (../libexec/venv/bin/<cmd>).
    # The ALF hash never changes → the firewall rule persists forever.
    %w[vllm-mlx vllm-mlx-ui vllm-mlx-chat vllm-mlx-bench].each do |cmd|
      next unless (venv/"bin"/cmd).exist?

      (bin/cmd).write <<~SH
        #!/bin/bash
        _s="$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")"
        exec "$(dirname "$_s")/../libexec/venv/bin/#{cmd}" "$@"
      SH
      (bin/cmd).chmod 0755
    end
  end

  # ── Post-install message ──────────────────────────────────
  def caveats
    <<~EOS
      ✅  vllm-mlx and the dashboard UI are installed.

      To start the dashboard:
          vllm-mlx-ui

      The browser will open automatically at http://127.0.0.1:8501

      Quick start:
        1. Go to the Server page
        2. Select a model from the dropdown and click ▶ Start Server
        3. Go to Chat to start chatting!

      To download the recommended starter model (~1.8 GB), run:
          python3.11 -c "from huggingface_hub import snapshot_download; \\
            snapshot_download('mlx-community/Llama-3.2-3B-Instruct-4bit')"

      Docs & source:  https://github.com/clickbrain/vllm-mlx-ui
    EOS
  end

  # ── Smoke test ────────────────────────────────────────────
  test do
    # Verify the package is importable (fast, no GPU required)
    system Formula["python@3.11"].opt_bin/"python3.11",
           "-c", "import vllm_mlx; import vllm_mlx.dashboard.app"
  end
end
