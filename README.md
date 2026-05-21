# vllm-mlx Dashboard UI

A fast, modern web dashboard for managing local AI inference on Apple Silicon. Run LLMs, multimodal models, and DeepSeek V4 locally — no cloud, no subscriptions, no data leaving your Mac.

📖 **[→ Full User Guide](docs/dashboard/user-guide.md)** | **[→ Releases](https://github.com/clickbrain/vllm-mlx-ui/releases)** | **[→ Changelog](CHANGELOG.md)**

---

## What It Does

The dashboard gives you a zero-configuration web UI (Vue 3, served at **http://localhost:8502**) to manage every aspect of local AI inference — no terminal knowledge required.

| Feature | Description |
|---------|-------------|
| 🤖 **6 Inference Engines** | vllm-mlx, DeepSeek V4 Flash (ds4), Rapid-MLX, llama.cpp, Ollama, LM Studio — install, configure, upgrade from the UI |
| 🖥️ **Serve** | Start / stop / restart any engine, full configuration, live connection URLs, log viewer |
| 📦 **Models** | Browse downloaded models, search HuggingFace, download by ID, one-click model switching, virtual-scrolled list |
| ⚡ **Benchmarks** | Speed, quality (GSM8K / MMLU / HumanEval / MATH / IFEval), custom prompts, multi-model comparison bar charts with 95% confidence intervals |
| 💬 **Chat** | Full chat history, named conversations, live HTML preview in code blocks, streaming responses |
| ⚙️ **Settings** | Per-engine configuration, remote machine management, multi-machine fleet support |
| 📑 **Docs** | Full documentation browsable in-app at `/docs` |
| ⌨️ **Command Palette** | `Cmd+K` quick navigation and action launcher |

---

## Requirements

- **macOS 13 (Ventura) or later**
- **Apple Silicon Mac** (M1–M5)  
  *(Remote-only dashboard works on any OS with Python 3.10+)*
- **Python 3.10 or later**

---

## Installation

### Which method is right for you?

| Scenario | Recommended method |
|----------|--------------------|
| New user on Apple Silicon Mac | **Homebrew** (easiest — always on PATH) |
| Quick one-line install without Homebrew | **curl installer** |
| Second device to control the AI Mac remotely | **Remote installer** (Option B) |
| Developer wanting editable source | **Clone** (Option C) |

**You do not need to choose between local and remote.** The full install lets your Mac both run the AI server AND be controlled from other devices — just enable network access in **Settings**.

---

### Option A — Homebrew (recommended for new users)

Homebrew puts `vllm-mlx-ui` permanently on your PATH so the command always works, even outside conda or pyenv sessions.

```bash
# 1. Add the tap (one time only)
brew tap clickbrain/vllm-mlx-ui

# 2. Install (takes 3–10 minutes on first run)
brew install vllm-mlx-ui
```

After install, start the dashboard with:
```bash
vllm-mlx-ui
```

**Upgrading (Homebrew):**
```bash
brew update && brew upgrade vllm-mlx-ui
```
`brew update` fetches the latest formula from the tap (required for third-party taps — `brew upgrade` alone won't see new versions). This upgrades the UI, the inference engine, and all Python dependencies in one step.

**Uninstalling (Homebrew):**
```bash
brew uninstall vllm-mlx-ui
brew untap clickbrain/vllm-mlx-ui```

> **Don't have Homebrew?** Get it at [brew.sh](https://brew.sh) or run:
> ```bash
> /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
> ```

---

### Option A2 — curl installer (no Homebrew required)

Run this on the Apple Silicon Mac that will host the AI server:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install.sh)
```

This will:
- Install vllm-mlx and all ML dependencies
- Install the dashboard UI
- Download the starter model: `mlx-community/Llama-3.2-3B-Instruct-4bit` (~2 GB)
- Create a **"Start vllm-mlx.command"** shortcut on your Desktop
- Print the exact command to run if `vllm-mlx-ui` isn't on your PATH

**After install:** Double-click the Desktop shortcut. Your browser opens automatically to the dashboard.

**Upgrading (curl install):**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install.sh)
```

**Uninstalling (curl install):**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/uninstall.sh)
```

> **Troubleshooting — "command not found: vllm-mlx-ui":**
> The installer prints the exact full path to use, e.g.:
> ```
> /opt/homebrew/Caskroom/miniconda/base/bin/vllm-mlx-ui
> ```
> Run that path directly, or switch to the Homebrew install method above — Homebrew always puts commands on PATH.

> **To allow remote access from other devices:** Go to **Server → Configuration** and change *Listen on* to `0.0.0.0 — all network interfaces`, then restart. The Server page will show all your IP addresses to share with clients.

---

### Option B — Remote Dashboard Only

Run this on any Mac (or Linux machine) that will **control** a vllm-mlx server running on another machine. No AI model or GPU software is installed locally.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install-remote.sh)
```

This will:
- Install only the dashboard libraries (Streamlit, Plotly, etc.)
- Create a **"vllm-mlx Remote.command"** shortcut on your Desktop

**After install:**
1. Double-click the Desktop shortcut
2. Go to **⚙️ Settings → 🔗 Remote Server**
3. Enter the IP address of the Mac running vllm-mlx (shown on that Mac's Server page)
4. You now have full remote control — start/stop server, manage models, chat

**Upgrading (remote install):**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install-remote.sh)
```

**Uninstalling (remote install):**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/uninstall.sh)
```

---

### Option C — Clone the repository (contributors / developers)

> **Regular users should use the Homebrew install (Option A1) instead.**

```bash
git clone https://github.com/clickbrain/vllm-mlx-ui.git
cd vllm-mlx-ui
pip install -e '.[ui]'
vllm-mlx-ui
```

**Upgrading (cloned repo):**
```bash
cd vllm-mlx-ui
git pull
pip install -e '.[ui]'
```

**Uninstalling (cloned repo):**
```bash
pip uninstall vllm-mlx
rm -rf ~/Desktop/"Start vllm-mlx.command"
# Optionally remove settings and chat history:
rm -rf ~/.vllm_mlx_ui
```

---

### Switching between install methods

Your downloaded AI models are stored in `~/.cache/huggingface/hub/` — completely separate from the software. You can uninstall and reinstall using any method without losing any models.

---

### Uninstalling (all methods)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/uninstall.sh)
```

Removes the package (pip or Homebrew), Desktop shortcut, and optionally your settings, chat history, and downloaded models.

---

## Starting the Dashboard

```bash
vllm-mlx-ui
```

The dashboard opens automatically at **http://localhost:8502**.

> The management API and Vue UI are both served by the same FastAPI/uvicorn process on port 8502. The inference engine runs separately on port 8000.

---

## Features In Detail

### 🤖 Inference Engines

Six engines are built in. Install, configure, and upgrade each from **Settings → Engines**:

| Engine | Best for |
|--------|----------|
| **vllm-mlx** | General-purpose MLX inference (text, multimodal, audio) |
| **DeepSeek V4 Flash (ds4)** | DeepSeek V4 Flash GGUF — native Metal, M5 optimised via `audreyt/ds4` fork |
| **Rapid-MLX** | Faster MLX inference variant |
| **llama.cpp** | GGUF models, broad compatibility |
| **Ollama** | Pre-packaged models, easy model library |
| **LM Studio** | Connect to a running LM Studio instance |

Engine cards show system requirement errors (blocks install) and memory advisories before you attempt an install.

### 🖥️ Serve Page

- Start / stop / restart the active engine
- Full engine configuration (all settings rendered from engine schema)
- Live connection URLs — base URL, chat endpoint, OpenAI-compatible API
- Quick model switch for standard engines; fixed-model label for single-model engines (e.g. ds4)
- Full server log viewer with auto-scroll

### 📦 Models Page

- **My Library** — all downloaded models with disk usage, pie chart, one-click Switch, HuggingFace card link, safe delete
- **Find Models** — search HuggingFace with filters (size range, quantization, fit level); Apply Filters re-fetches up to 100 results
- **Download by ID** — paste any HuggingFace model ID; supports private/gated models with HF token
- Virtual-scrolled list handles thousands of models without lag

### ⚡ Benchmarks Page

- **Speed** — tokens/sec and TTFT across N runs, accurate timing (skips buffered streams)
- **Quality** — GSM8K, MMLU, HumanEval, MATH, IFEval with authentic test data; each result includes 95% bootstrap confidence intervals and per-run hardware fingerprint (chip, RAM, OS, MLX version)
- **Custom Prompts** — run your own prompts, per-prompt results table
- **Multi-model comparison** — bar charts comparing speed and quality across models
- Benchmark history with export and delete

### 💬 Chat Page

- Full chat history with named conversations, auto-title from first message
- Per-chat model selector; conversation presets (Chat / Code / Creative / Analysis / Precise)
- Streaming responses with live markdown rendering
- **Live HTML preview** — HTML code blocks get a Preview button that renders in a sandboxed iframe with Mobile / Tablet / Desktop / Full size presets

### ⚙️ Settings Page

- Per-engine configuration panels
- **Multi-machine fleet** — add remote machines (host + port), switch the active machine; all API calls route to the selected machine automatically
- **Auto Model Switch Proxy** — port 8502 acts as an OpenAI proxy; client model requests trigger automatic server reload with the right model
- Network access: localhost or LAN (`0.0.0.0`)

### ⌨️ Command Palette (`Cmd+K`)

Quick-launch navigation to any page or action from anywhere in the UI.

---

## Remote Access Architecture

```
┌─────────────────────────────────────┐
│  Your Mac (Apple Silicon)           │
│                                     │
│  Inference engine (e.g. vllm-mlx)  :8000  │
│  Dashboard + Management API        :8502  │
└─────────────────────────────────────┘
           ↕ LAN / WiFi / Thunderbolt Bridge
┌─────────────────────────────────────┐
│  Another device (any OS)            │
│  Dashboard only — controls Mac above│
└─────────────────────────────────────┘
```

The management API (port 8502) handles:
- `GET/POST /server/start` — start the server
- `POST /server/stop` — stop the server
- `GET /server/status` — health and PID
- `GET /server/logs` — last N log lines
- `GET/POST /config` — read / write config
- `GET /models` — list downloaded models
- `POST /models/download` — download a model
- `DELETE /models/{id}` — delete a model
- `GET /memory/stats` — unified memory usage
- `POST /memory/release` — release memory (GC + Metal cache)
- `POST /v1/chat/completions` — OpenAI proxy with auto model switching

### Setting Up Remote Access (Recommended Method)

**Use IP addresses, not `.local` hostnames.**  macOS mDNS advertises both IPv6 link-local (`fe80::…`) and IPv4 addresses for `.local` names. Many HTTP clients attempt IPv6 first; since link-local IPv6 requires a network interface scope ID that URLs cannot encode, connections fail and time out (up to 3 s each) before falling back to IPv4. The dashboard resolves this automatically when you save a `.local` hostname, but using an IP address directly is faster and works on every network.

**Step 1 — Find your server's IP address**

On the server Mac, open the dashboard and go to **Server → Connection Info**. You'll see all available IP addresses. Copy the one that matches how you're connecting:

| Connection type | Address to use |
|-----------------|----------------|
| Same Wi-Fi network | `192.168.x.x` or `10.x.x.x` |
| Thunderbolt Bridge (fastest) | `192.168.200.x` (after static IP config — see below) |
| USB-C/Thunderbolt link-local | `169.254.x.x` |

You can also run this in Terminal on the server Mac:
```bash
# Wi-Fi address (en0 or en1):
ipconfig getifaddr en0

# All IPs:
ifconfig | awk '/^[a-z]/{iface=$1} /inet /{print iface, $2}'
```

**Step 2 — Enter the URLs in Settings**

On the client Mac, open the dashboard → **⚙️ Settings → 🔗 Remote Server** and enter:
```
Inference server URL:  http://192.168.x.x:8000/v1
Management API URL:    http://192.168.x.x:8502
```
> `/v1` is optional in the inference URL — the dashboard strips it automatically if present.

After saving, a green ✅ appears if the connection works. If you entered a `.local` hostname, the settings page will show you the resolved IPv4 address and suggest switching to it.

### Thunderbolt Bridge (macOS-to-macOS, fastest option)

If you're connecting two Macs with a Thunderbolt cable, configure static IPs on the Thunderbolt Bridge interface for a reliable, 40 Gbps dedicated connection:

**On the server Mac** (System Settings → Network → Thunderbolt Bridge):
- Configure IPv4: **Manually**
- IP Address: `192.168.200.1`
- Subnet Mask: `255.255.255.0`
- Router: *(leave blank)*

**On the client Mac** (same section):
- Configure IPv4: **Manually**
- IP Address: `192.168.200.2`
- Subnet Mask: `255.255.255.0`
- Router: *(leave blank)*

Then use `http://192.168.200.1:8000/v1` and `http://192.168.200.1:8502` in Settings.

> **Why Thunderbolt over Wi-Fi?** Thunderbolt Bridge is a direct 40 Gbps link between the two machines — no router, no Wi-Fi contention. Inference responses stream with < 1 ms network latency instead of the typical 5–20 ms over Wi-Fi.

---

## OpenAI Client Configuration

Once the server is running, use these settings in any OpenAI-compatible app:

| Setting | Value |
|---------|-------|
| Base URL | `http://<your-mac-ip>:8000/v1` |
| API Key | *(leave blank, or set one in Server settings)* |
| Model | *(any model ID you have downloaded)* |

Compatible clients: Open WebUI, Chatbox, LM Studio, Continue (VS Code), Cursor, any app with OpenAI base URL support.

### Auto Model Switch

Enable **Auto Model Switch** in Settings to use port 8502 as the base URL. Then changing the model in your client automatically reloads the server with the correct model:

```
Base URL: http://<your-mac-ip>:8502/v1
```

---

## File Layout

```
vllm_mlx/dashboard/
├── mgmt_server.py      # FastAPI app — serves Vue UI + all /api/* endpoints (port 8502)
├── app.py              # CLI entry point, process management, browser open
├── server_manager.py   # Engine lifecycle, config, remote-aware
├── model_manager.py    # HuggingFace Hub integration, download queue
├── benchmark_runner.py # Speed/quality/custom benchmark execution + history
├── quality_runner.py   # GSM8K, MMLU, HumanEval graders
├── update_checker.py   # Version checking for UI + engines
├── engines/            # Engine adapters (ds4_m5, vllm_mlx, rapid_mlx, llama_cpp, ollama, lm_studio)
├── ui_dist/            # Built Vue 3 frontend (committed, served by FastAPI)
└── __init__.py         # Version

ui/                     # Vue 3 source (npm run build → ui_dist/)
```

State is stored in `~/.vllm_mlx_ui/`:
- `config.json` — all configuration
- `server.pid` — PID of the running inference engine
- `server.log` — engine log output
- `benchmark_results.json` — benchmark history
- `chats.json` — chat history

---

## 🔒 Privacy & Data Ownership

**Your AI. Your data. Full stop.**

vllm-mlx is built on a simple principle: AI should run on *your* hardware, under *your* control, with none of your data leaving your machine. This dashboard exists to make that as easy as possible.

- **Everything runs locally.** Inference, chat, benchmarks, model management — all of it happens on your Mac. No cloud, no subscription, no usage limits.
- **Your conversations never leave your device.** Chat history is stored in `~/.vllm_mlx_ui/chats.json` on your Mac and nowhere else.
- **Your prompts and model outputs are never transmitted.** The AI runs entirely on your Apple Silicon chip. No third-party servers see your queries or responses.
- **Streamlit telemetry is disabled.** The dashboard framework (Streamlit) normally collects anonymous usage stats. We explicitly disable this at startup — it never runs.

The only times this software contacts the internet are actions you explicitly trigger:

| Action | Destination | What is sent |
|--------|-------------|--------------|
| Download a model | `huggingface.co` | The model ID you requested |
| Search for models | `huggingface.co` | Your search query |
| Check for updates | `api.github.com`, `pypi.org` | Nothing — these are read-only public API calls |

No account required. No telemetry. No analytics. No backdoors.

---

## Troubleshooting

**Dashboard won't start:**
```bash
brew update && brew upgrade vllm-mlx-ui
vllm-mlx-ui
```

**"No models found":** Go to Models → Search or Download by ID to get your first model.

**Server stuck on "Starting":** The model is loading into memory. Large models (7B+) can take 30–60 seconds. Check the log expander on the Server page for errors.

**Can't connect from another device:** In Server settings, change "Listen on" to `0.0.0.0 — all network interfaces` and restart.

**Remote dashboard can't reach server:** Make sure the Mac running the inference engine has "Listen on 0.0.0.0" enabled in Serve settings. Check that your firewall allows ports 8000 and 8502 *(System Settings → Network → Firewall → Options → add `vllm-mlx-ui`)*.

**Remote connection is very slow or laggy:** You may be connecting via a `.local` hostname which resolves to IPv6 first, adding 3–6 s per request. Go to **⚙️ Settings → Machines** and enter the IPv4 address instead (e.g. `http://192.168.68.74:8502`). See [Remote Access Architecture](#remote-access-architecture) for full setup instructions.

---

## Authorship Note

This dashboard UI was entirely designed and implemented by AI (GitHub Copilot powered by Claude). It is offered to the vllm-mlx community as an open-source contribution. The underlying vllm-mlx inference engine is the work of [waybarrios](https://github.com/waybarrios/vllm-mlx) and contributors.

---

## License

Apache 2.0 — same as vllm-mlx.
