# vllm-mlx Dashboard UI with local and remote network access

A comprehensive macOS web dashboard for [vllm-mlx](https://github.com/waybarrios/vllm-mlx) — the high-performance Apple Silicon LLM inference server. Run powerful AI models completely locally: no cloud, no subscriptions, no data leaving your Mac.

> **Note:** This UI was fully designed and coded by AI (GitHub Copilot / Claude). It is offered as a contribution to the vllm-mlx community.

---

## What It Does

The vllm-mlx Dashboard gives you a beautiful, zero-configuration web UI to control every aspect of your local AI server — no terminal knowledge required.

📖 **[→ Full User Guide](docs/dashboard/user-guide.md)** — complete documentation for every feature, page, and setting.

| Feature | Description |
|---------|-------------|
| 📊 **Overview** | Live metrics (tokens/sec, GPU memory, latency), server health at a glance |
| 🖥️ **Server** | Start / stop / restart the server, full configuration with dropdowns, all connection URLs shown |
| 📦 **Models** | Browse your downloaded models, search the mlx-community on HuggingFace, download by ID, one-click model switching, model card links |
| ⚡ **Benchmarks** | Run performance benchmarks, compare models, view historical results with charts |
| 💬 **Chat** | Built-in chat with full history, named conversations, per-chat model switching |
| ⚙️ **Settings** | Network access, remote server control, auto model-switch proxy |

---

## Requirements

- **macOS 13 (Ventura) or later**
- **Apple Silicon Mac** (M1, M2, M3, or M4)  
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
brew tap clickbrain/vllm-mlx-ui https://github.com/clickbrain/vllm-mlx-ui

# 2. Install (takes 3–10 minutes on first run)
brew install --HEAD clickbrain/vllm-mlx-ui/vllm-mlx-ui
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
brew untap clickbrain/vllm-mlx-ui
```

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
pip install --upgrade "git+https://github.com/clickbrain/vllm-mlx-ui.git#egg=vllm-mlx[ui]"
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
pip install --upgrade "git+https://github.com/clickbrain/vllm-mlx-ui.git#egg=vllm-mlx[ui]"
```

**Uninstalling (remote install):**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/uninstall.sh)
```

---

### Option C — Clone the repository (developers)

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

Or directly with Streamlit:

```bash
streamlit run vllm_mlx/dashboard/_ui.py
```

The dashboard opens at `http://localhost:8501`.

---

## Features In Detail

### 📊 Overview Page

- Live server health banner (running / starting / stopped)
- Real-time metrics: tokens per second, time to first token, GPU memory, active requests
- Charts refreshing every 5 seconds (configurable)
- One-click navigation to Server settings

### 🖥️ Server Page

**Connection Info Card** (shown when server is running):
- Your LAN IP address and the correct base URL for OpenAI clients
- The loaded model ID (ready to copy-paste into any client)
- API key (if configured)
- Management API URL for remote control

**Configuration:**
- All settings are dropdowns and number inputs — no guessing required
- **Load Optimal Settings** button reads the model's HuggingFace card and pre-fills context length, architecture, temperature
- Network settings: listen on localhost only or all interfaces for LAN access
- Port, API key, embedding model, rerank model
- Cache controls (clear all caches / prefix cache)
- Full server log viewer

**Quick Switch** (sidebar): Change the active model with one click, without navigating to the Models page.

### 📦 Models Page

**My Library tab:**
- All downloaded models with disk usage
- Disk usage pie chart
- One-click **⚡ Switch** to activate a model (auto-restarts server with optimal settings)
- **↗ Model Card** link to view on HuggingFace
- Safe delete with confirmation

**Search mlx-community tab:**
- Search all of [mlx-community](https://huggingface.co/mlx-community) on HuggingFace
- Filter by: quantization bits (4-bit, 8-bit, etc.), model size (1B–70B+)
- Sort by: downloads, likes, name
- **↗ Card** link for each result
- ✓ badge on already-downloaded models
- One-click download

**Download by ID tab:**
- Paste any HuggingFace model ID
- Supports private/gated models with HuggingFace token

### ⚡ Benchmarks Page

- Run benchmarks against the currently loaded model
- Configure: prompt, max tokens, number of runs
- Results: tokens/sec, time to first token, total latency
- Historical benchmark chart comparing all results
- Export / delete benchmark history

### 💬 Chat Page

- Full chat history with **named conversations**
- Create, rename, delete chats
- **Per-chat model selector** — each conversation can use a different model
- Auto-title from first message
- Streaming responses
- System prompt support
- All Streamlit chat features: message history, clear chat

### ⚙️ Settings Page

**Network Access:**
- Set the dashboard host/port
- Enable LAN access with one toggle — shows the shareable URL

**Remote Server:**
- Enter inference API URL and management API URL for a remote vllm-mlx machine
- API key support
- Live health check — confirms the connection is working
- When connected, all operations run on the remote machine

**Auto Model Switch Proxy:**
- When enabled, the management API (port 8502) becomes an OpenAI-compatible proxy
- If your chat client requests a model that isn't loaded, the server automatically restarts with the correct model
- Shows the exact proxy URL to paste into your client

---

## Remote Access Architecture

```
┌─────────────────────────────────────┐
│  Your Mac (Apple Silicon)           │
│                                     │
│  vllm-mlx inference server :8000   │
│  Management API            :8502   │
│  Streamlit dashboard       :8501   │
└─────────────────────────────────────┘
           ↕ LAN / WiFi / Thunderbolt Bridge
┌─────────────────────────────────────┐
│  Another device (any OS)            │
│                                     │
│  Remote dashboard only              │
│  (controls the Mac above)           │
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
Inference server URL:  http://192.168.x.x:8000
Management API URL:    http://192.168.x.x:8502
```

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

Then use `http://192.168.200.1:8000` and `http://192.168.200.1:8502` in Settings.

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
├── _ui.py              # Main Streamlit app (all 6 pages)
├── app.py              # CLI entry point + mgmt server launch
├── server_manager.py   # Server lifecycle, config, remote-aware
├── model_manager.py    # HuggingFace Hub integration, remote-aware
├── benchmark_runner.py # Benchmark execution + history
├── mgmt_server.py      # FastAPI management API (port 8502)
└── __init__.py

.streamlit/
└── config.toml         # iFrame support, CORS settings

install.sh              # Full installer (vllm-mlx + UI + model)
install-remote.sh       # Remote-only installer (UI only)
```

State is stored in `~/.vllm_mlx_ui/`:
- `server_config.json` — all configuration
- `server.pid` — PID of the running server
- `server.log` — server log output
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
pip install 'vllm-mlx[ui]'
vllm-mlx-ui
```

**"No models found":** Go to Models → Search or Download by ID to get your first model.

**Server stuck on "Starting":** The model is loading into memory. Large models (7B+) can take 30–60 seconds. Check the log expander on the Server page for errors.

**Can't connect from another device:** In Server settings, change "Listen on" to `0.0.0.0 — all network interfaces` and restart.

**Remote dashboard can't reach server:** Make sure the Mac running vllm-mlx has "Listen on 0.0.0.0" enabled in Server settings. Check that your firewall allows ports 8000 and 8502 *(System Settings → Network → Firewall → Options → add `vllm-mlx-ui`)*.

**Remote connection is very slow or laggy:** You may be connecting via a `.local` hostname which resolves to IPv6 first, adding 3–6 s per request. Go to **⚙️ Settings → Remote Server** and enter the IPv4 address instead (e.g. `http://192.168.68.74:8000`). The settings page will show you the resolved IP after you save. See [Remote Access Architecture](#remote-access-architecture) for full setup instructions.

**Remote connection shows local machine RAM on Benchmarks page:** This was fixed in v0.3.3. Run `brew update && brew upgrade vllm-mlx-ui` on both machines.

**"ScriptRunContext" warnings flooding the terminal:** These were caused by the dashboard library being imported from the management API process. Fixed in v0.3.5. Run `brew update && brew upgrade vllm-mlx-ui`.

---

## Authorship Note

This dashboard UI was entirely designed and implemented by AI (GitHub Copilot powered by Claude). It is offered to the vllm-mlx community as an open-source contribution. The underlying vllm-mlx inference engine is the work of [waybarrios](https://github.com/waybarrios/vllm-mlx) and contributors.

---

## License

Apache 2.0 — same as vllm-mlx.
