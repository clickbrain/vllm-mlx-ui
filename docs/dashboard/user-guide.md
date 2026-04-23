# vllm-mlx Dashboard — Complete User Guide

A visual, no-terminal interface for running powerful AI models entirely on your Mac. No cloud, no subscriptions, no data leaving your machine.

---

## Table of Contents

1. [What Is This?](#1-what-is-this)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [Starting the Dashboard](#4-starting-the-dashboard)
5. [First-Time Setup](#5-first-time-setup)
6. [The Sidebar](#6-the-sidebar)
7. [Overview Page](#7-overview-page)
8. [Server Page](#8-server-page)
9. [Models Page](#9-models-page)
10. [Benchmarks Page](#10-benchmarks-page)
11. [Chat Page](#11-chat-page)
12. [Settings Page](#12-settings-page)
13. [Remote Access](#13-remote-access)
14. [Connecting External AI Apps](#14-connecting-external-ai-apps)
15. [Security](#15-security)
16. [Updates](#16-updates)
17. [Troubleshooting](#17-troubleshooting)
18. [Privacy](#18-privacy)
19. [Where Files Are Stored](#19-where-files-are-stored)

---

## 1. What Is This?

**vllm-mlx Dashboard** is a web-based control panel for the [vllm-mlx](https://github.com/waybarrios/vllm-mlx) inference engine — the software that runs large AI language models on Apple Silicon Macs. 

The dashboard gives you a graphical interface for everything: downloading models, starting and stopping the server, chatting with AI models, running performance benchmarks, and configuring network access — all without ever opening a terminal.

### What it does

| Page | What you can do |
|------|-----------------|
| 📊 Overview | See live server health, memory usage, and request traffic charts |
| 🖥️ Server | Start/stop the server, configure every option, view logs |
| 📦 Models | Download, search, switch, and delete AI models |
| ⚡ Benchmarks | Measure how fast your models run; compare models side by side |
| 💬 Chat | Have conversations with your local AI models |
| ⚙️ Settings | Updates, remote access, security, network settings |

### How it works

When you start the dashboard, two things run on your Mac:
- **Inference server** (port 8000) — the engine that actually runs AI models
- **Dashboard UI** (port 8501) — the web interface you see in your browser
- **Management API** (port 8502) — enables remote control from another device

You can also connect the dashboard to a vllm-mlx server running on **another Mac on your network**, so you can chat and manage models remotely.

---

## 2. Requirements

| Requirement | Details |
|-------------|---------|
| **Mac hardware** | Apple Silicon (M1, M2, M3, or M4 chip) |
| **macOS version** | macOS 13 Ventura or later (macOS 14 Sonoma or 15 Sequoia recommended) |
| **RAM** | 8 GB minimum; 16 GB+ recommended for larger models |
| **Disk space** | 3–5 GB for software + storage for models (2–50 GB each) |
| **Internet** | Required for downloading models; not required to run them |

> **Remote dashboard:** If you only want to control a remote server from a MacBook, you can run the remote-only install on any Mac (Intel or Apple Silicon, macOS 12+).

---

## 3. Installation

### Option A — Homebrew (Recommended)

Homebrew is the easiest install method. It automatically handles all dependencies and makes the `vllm-mlx-ui` command always available in your terminal.

**If you don't have Homebrew**, install it first (opens in Terminal):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Install vllm-mlx-ui:**
```bash
# Add the source (one time only)
brew tap clickbrain/vllm-mlx-ui https://github.com/clickbrain/vllm-mlx-ui

# Install (takes 3–10 minutes)
brew install --HEAD clickbrain/vllm-mlx-ui/vllm-mlx-ui
```

Start the dashboard any time with:
```bash
vllm-mlx-ui
```

---

### Option A2 — curl Installer (No Homebrew Required)

Run this single line in Terminal:
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install.sh)
```

The installer will:
1. Install vllm-mlx and all required Python packages
2. Install the dashboard
3. Download a starter model (~2 GB) so you can start immediately
4. Create a **"Start vllm-mlx.command"** shortcut on your Desktop

After installing, double-click the Desktop shortcut — your browser will open to the dashboard automatically.

---

### Option B — Remote Dashboard Only

Use this if you have a **second Mac** (like a MacBook) that you want to use to control the AI server running on another Mac (like a Mac Studio).

Run on the second Mac (the one that will just control, not run AI):
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install-remote.sh)
```

This installs only the dashboard interface — no AI models or GPU software. See [Section 13: Remote Access](#13-remote-access) to connect it to your server Mac.

---

### Option C — Developer Install

```bash
git clone https://github.com/clickbrain/vllm-mlx-ui.git
cd vllm-mlx-ui
pip install -e '.[ui]'
vllm-mlx-ui
```

---

### Choosing the right method

| Your situation | Use |
|---------------|-----|
| New user on Apple Silicon Mac | **Option A (Homebrew)** |
| Quick setup without Homebrew | **Option A2 (curl)** |
| MacBook controlling a Mac Studio | **Option B (remote)** |
| Developer / want to edit the code | **Option C (clone)** |

---

### Uninstalling

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/uninstall.sh)
```

This removes the software. Your downloaded AI models (stored in `~/.cache/huggingface/`) are left untouched — you can reinstall without re-downloading models.

---

## 4. Starting the Dashboard

**Homebrew / curl install:**
```bash
vllm-mlx-ui
```

**Desktop shortcut** (curl install): Double-click "Start vllm-mlx.command" on your Desktop.

**Direct Streamlit** (developer):
```bash
streamlit run vllm_mlx/dashboard/_ui.py
```

The dashboard opens automatically in your browser at `http://localhost:8501`.

---

## 5. First-Time Setup

When you open the dashboard for the first time, here is the recommended flow:

1. **Go to 📦 Models** → click "⬇️ Download Starter Model" to get `Llama-3.2-3B-Instruct-4bit` (~2 GB, fast, works on all Apple Silicon Macs). Or search for a different model.

2. **Go to 🖥️ Server** → click "▶ Start Server". The server loads your model into GPU memory (this takes 15–60 seconds depending on model size).

3. **Go to 💬 Chat** → start chatting with your local AI.

That's it. The entire AI runs on your Mac — nothing goes to the internet.

---

## 6. The Sidebar

The sidebar is always visible on the left and contains:

### Server status pill

Shows the current server state at a glance:
- 🟢 **Server running** — the server is healthy and ready
- 🟡 **Starting…** — a model is loading into memory
- 🔴 **Server stopped** — the server is not running

From the sidebar you can also:
- Click **▶ Start Server** (when stopped)
- Click **⏹ Stop Server** (when running)

### Quick model switcher

When you have downloaded models, a dropdown appears in the sidebar labelled "⚡ Quick switch model". Select a different model and click **Switch now** to change the active model without navigating to the Server page. The server will restart with the new model.

### Navigation buttons

Click any page name to navigate:
- 📊 Overview
- 🖥️ Server
- 📦 Models
- ⚡ Benchmarks
- 💬 Chat
- ⚙️ Settings

### Update available banner

When a new version of the dashboard is available, a yellow "⬆️ N update available" badge appears at the bottom of the sidebar with an **Update Now & Restart** button.

### Local / Remote toggle

If you have configured a remote server in Settings, a radio button appears in the sidebar to switch between controlling **this Mac** (Local) or **the remote server** (Remote). See [Section 13: Remote Access](#13-remote-access).

### Shutdown button

**⏹ Shutdown** at the bottom of the sidebar stops the inference server and closes the dashboard process entirely.

---

## 7. Overview Page

The Overview page shows a live dashboard of server activity. It automatically refreshes every 5 seconds (adjustable in Settings).

### Status banner

A coloured banner at the top shows the current state:
- 🟢 **Server running** — includes the loaded model name, model type (LLM or vision), and PID
- 🟡 **Server starting** — model is loading; no metrics yet
- 🔴 **Server stopped** — links you to the Server page

### Metric tiles (8 live counters)

| Metric | What it means |
|--------|---------------|
| ⏱ Uptime | How long the server has been running (HH:MM:SS) |
| 📨 Active | Requests currently being processed |
| ⏳ Queued | Requests waiting to start |
| ✅ Completed | Total requests processed since server start |
| 📝 Prompt tokens | Total input tokens processed |
| 💬 Output tokens | Total output tokens generated |
| 🔧 Metal memory | Current GPU/unified memory in use (GB) |
| 📈 Peak memory | Highest memory usage recorded (GB) |

### Live charts

Two charts refresh in real time:
- **Requests over time** — active vs. queued requests (area chart, last 10 minutes)
- **Metal GPU memory (GB)** — memory consumption over time

### Active requests table

When requests are in flight, a table shows each one with status and details.

### Cache statistics

Expandable panel showing prefix cache hit/miss statistics (only visible when the server is running).

---

## 8. Server Page

The Server page is the control centre for the inference server. Everything that affects how the AI runs is configured here.

### Status banner + action buttons

The top of the page shows a detailed status card:
- When **running and healthy**: shows PID, loaded model name, and model type
- When **starting**: shows a loading indicator and live log output so you can see progress
- When **stopped**: shows the last few log lines so you can diagnose failures

**Buttons:**
- **▶ Start Server** — starts the server with the current configuration
- **⏹ Stop** — gracefully stops the server
- **🔄 Restart** — stops and immediately restarts with any pending config changes

### Connection info card

When the server is running, a card appears showing:
- All available URLs for connecting clients (LAN IP, localhost, hostname)
- The model ID to use in OpenAI clients
- Your API key (if set)
- The management API URL (for remote dashboard control)

### Configuration

#### Model selection

- **Main model** dropdown — lists all locally downloaded models. Select the model to run.
- **✏️ Enter manually…** option — type any HuggingFace model ID if it's not in your library yet
- **💾 Size on disk** — shown below the dropdown for the selected model
- **✨ Load optimal settings** button — reads the model's HuggingFace model card and automatically fills in the best context length, architecture, and multimodal settings

#### Optional models
- **Embedding model** — pre-load a model for the `/v1/embeddings` endpoint (for semantic search, RAG)
- **Rerank model** — pre-load a model for the `/v1/rerank` endpoint

#### Network settings

| Setting | What it does |
|---------|-------------|
| **Served model name** | Override the model name returned by `/v1/models`. Use this if your client expects a specific name like `gpt-4`. |
| **Listen on** | `127.0.0.1` = only this Mac; `0.0.0.0` = accessible from other devices on your network |
| **Port** | Port number for the inference server (default: 8000) |
| **API key** | Optional password to protect the server. Any client must send this key to be allowed. |
| **Rate limit** | Maximum requests per minute (0 = unlimited) |

#### Generation settings

| Setting | What it does |
|---------|-------------|
| **Continuous batching** | Processes multiple requests simultaneously for better throughput with multiple users |
| **Context length** | Maximum tokens the model can handle (prompt + response combined). Higher uses more RAM. |
| **Reasoning parser** | Extracts hidden chain-of-thought reasoning (e.g. from DeepSeek-R1 `<think>` blocks) into a separate field |
| **Tool / function call parser** | Required for apps that use tools/function calling. `auto` works for most models. |

#### Memory & performance

| Setting | What it does |
|---------|-------------|
| **GPU memory utilisation** | Fraction of your Mac's unified RAM to allocate to the model (default: 90%) |
| **Prefix cache** | Caches repeated prompt prefixes to speed up subsequent requests. Recommended: on. |
| **Cache memory cap** | Limits how much RAM the prefix cache can consume (0 = ~20% of available) |
| **KV cache quantization** | Compresses the KV cache to use less memory. Small quality trade-off. |
| **Paged KV cache** | Advanced memory management. Try this if large batches run out of memory. |
| **Multi-token prediction (MTP)** | Generates multiple tokens simultaneously. Only for models with built-in MTP support. |

#### Advanced settings

| Setting | What it does |
|---------|-------------|
| **Stream interval** | How many tokens to batch before sending to the client (1 = smoothest streaming) |
| **Trust remote code** | Allows model code to run during loading. Only enable if you trust the model source. |
| **Vision / multimodal mode (MLLM)** | Enables image/video input. Auto-detected for most vision models. |
| **Expose Prometheus /metrics** | Enables the `/metrics` endpoint for monitoring tools |
| **Offline mode** | Never contacts HuggingFace. Only uses already-downloaded models. |

### Saving configuration

Click **💾 Save configuration** to save changes. If the server is running, a restart button appears — click it to apply the new settings immediately.

### Cache controls

When the server is running, two buttons appear:
- **🗑 Clear all caches** — clears all cached data
- **🗑 Clear prefix cache** — clears only the prompt prefix cache (frees memory without restarting)

### Server logs

The bottom of the page shows the raw server log. Use the slider to choose how many lines to display (50–500). Click **🔄 Refresh logs** to reload.

---

## 9. Models Page

The Models page has three tabs: My library, Search, and Download by ID.

### My library tab

Shows all models currently downloaded on this Mac.

**Summary metrics:**
- Total disk space used across all models
- Total number of models downloaded
- Cache location on disk
- Disk usage pie chart (shown when you have more than one model)

**For each model in the list:**
- Full model ID with a link to its HuggingFace model card (↗)
- File path on disk
- Size on disk (GB)
- **⚡ Switch** button — activates this model (restarts the server if one is running). A confirmation step shows how much memory will be used.
- **✓ Active** badge — shown on the currently loaded model
- **🗑 Delete** button — removes the model from disk (shows a confirmation prompt first)

### Search mlx-community tab

Search the [mlx-community](https://huggingface.co/mlx-community) collection on HuggingFace — thousands of models optimised for Apple Silicon.

**Quick filter buttons:** Llama, Qwen, Gemma, Mistral, Phi, DeepSeek, Falcon, Mamba — click any to instantly search that model family.

**Filter controls:**
| Filter | Options |
|--------|---------|
| **Sort by** | Downloads, Likes, Most recent, Name A–Z |
| **Quantization** | Any, 4-bit, 8-bit, 3-bit, 6-bit, fp16/bf16 |
| **Model size** | Any, <1B, 1–3B, 3–8B, 8–30B, 30–70B, >70B |

**Results table columns:**
- Model ID (✓ badge if already downloaded)
- ⬇️ Download count
- ❤️ Likes count
- Quantization bits
- ↗ Card link (opens HuggingFace model card)
- **⬇️ Get** button to download

> **Tip:** 4-bit quantized models are the best balance of quality and speed on most Macs. For an 8 GB Mac, stay at 3B parameters or smaller. For 16 GB, 7–8B models work well. For 32 GB+, 13–30B models are excellent.

### Download by ID tab

If you know the exact HuggingFace model ID (e.g. from browsing [huggingface.co/mlx-community](https://huggingface.co/mlx-community)), paste it here.

- **Model ID field** — paste the full ID, e.g. `mlx-community/Llama-3.2-3B-Instruct-4bit`
- **HuggingFace token** — required only for gated (restricted-access) models. Get your token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

---

## 10. Benchmarks Page

The Benchmarks page lets you measure exactly how fast your models run on your hardware, and compare results across models and over time.

> **Note:** Benchmarks load the model directly and do not require the inference server to be running. Close other heavy applications first for accurate results.

### Run benchmark tab

**Configuration:**
| Setting | What it controls |
|---------|-----------------|
| **Model** | Which downloaded model to benchmark (defaults to currently active model) |
| **Prompts** | Number of test prompts to run (1–20). More prompts = more accurate average. |
| **Max tokens per response** | How many tokens each response generates (64–1024) |
| **Vision / multimodal (MLLM)** | Enable if benchmarking a vision model |
| **Video benchmark** | Enable for video-capable multimodal models |

Click **🚀 Run benchmark** to start. You'll see live output as the benchmark runs.

**After the benchmark:**
- ✅ success banner
- **Tokens / sec** — higher is better; measures generation speed
- **TTFT (ms)** — Time To First Token; lower is better; measures how fast the model starts responding
- Full JSON result (expandable)

Results are automatically saved for later comparison.

### History & charts tab

**Summary table** showing all past benchmark runs:
- Run number, model name, date, number of prompts, max tokens
- tok/s (tokens per second)
- TTFT (ms) — time to first token
- TPOT (ms) — time per output token

**Charts:**
- **Throughput comparison** — bar chart comparing tokens/sec across all models
- **Time to first token** — bar chart comparing TTFT across all models (lower = better)

**Detailed results** — expandable section for each run showing full JSON data and a **🗑 Delete** button to remove individual runs.

**🗑 Clear all results** — removes the entire benchmark history.

---

## 11. Chat Page

The Chat page provides a full conversational interface to your local AI models, with persistent history, multiple simultaneous conversations, and per-chat settings.

> The inference server must be running to use Chat. If it's stopped, you'll see a button to go to the Server page and start it.

### Starting a conversation

Type in the **"Type your message…"** box at the bottom and press Enter. The AI responds in real time (streaming by default).

If this is the first message in a new chat, the conversation is automatically titled based on your first message.

### Chat history (sidebar)

The left sidebar on the Chat page shows all your saved conversations.

**Creating and managing chats:**
- **➕ New chat** — starts a blank conversation
- Click any chat title to switch to it
- **⭐ / ☆** — star/unstar a conversation to pin it to the top
- **✕** — delete a conversation (immediate, no undo)
- **Rename this chat** text box — change a chat's title

Starred conversations appear at the top of the list under "⭐ Favourites".

### Per-chat model selector

Each conversation can use a different model. The **Model** dropdown in the Chat sidebar shows all your downloaded models. If you switch to a model that isn't currently loaded, the server will automatically restart with the new model when you send your next message.

### Generation parameters

Adjust these sliders in the Chat sidebar to fine-tune responses:

| Parameter | Range | Effect |
|-----------|-------|--------|
| **Temperature** | 0.0 – 2.0 | Higher = more creative/random; lower = more predictable |
| **Max tokens** | 64 – 8192 | Maximum response length |
| **Top-p** | 0.1 – 1.0 | Controls diversity; 0.9 is a good default |
| **Stream response** | On/Off | Show response as it's generated (on) vs. wait for full response (off) |

### System prompt

The **System prompt** text area lets you give the AI standing instructions — e.g. "You are a helpful coding assistant. Be concise." This is sent invisibly with every message in the conversation.

### Attaching files

**Images** (vision models only): If your loaded model supports vision (models with names like `llava`, `qwen2-vl`, `pixtral`, or models configured as multimodal), a file uploader appears for attaching `.jpg`, `.png`, `.webp`, or `.gif` images.

**Text and code files**: Any chat session supports attaching text/code files. Supported formats include `.txt`, `.md`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.csv`, `.sh`, and many more. Files over 100 KB are automatically truncated. The file content is prepended to your message for context.

### Reasoning trace

Models that generate chain-of-thought reasoning (e.g. DeepSeek-R1, Qwen3 with reasoning mode) display a collapsible **"🧠 Reasoning trace"** section under each response, showing the model's internal thinking.

### Token usage

Each assistant response shows the number of prompt tokens and completion tokens used, so you can track context usage.

### Switching models mid-conversation

If the chat's selected model differs from the currently loaded model, a warning banner appears at the top of the chat. Click **⚡ Switch** to restart the server with the chat's model, then continue the conversation.

---

## 12. Settings Page

The Settings page controls system-level configuration: updates, authentication tokens, network access, remote connections, security, and startup behaviour.

### 🔄 Updates

Shows the current version of all components and whether updates are available.

**Components tracked:**
- **vllm-mlx-ui (dashboard)** — the web interface you're using
- **vllm-mlx** — the underlying inference engine
- **mlx-lm** and **huggingface-hub** — Python dependency libraries

**Re-check now** — forces an immediate update check (bypasses the 1-hour cache).

When an update is available:
- An update command is shown
- **⬆️ Update Now & Restart** button — runs the update in the background with live output, then automatically relaunches the dashboard

> Updates pull from the official upstream repositories. The update command installs the latest version of every component.

### 🔑 HuggingFace

Set your HuggingFace access token here. This is required to download **gated models** (models that require agreeing to terms on HuggingFace). Get your token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

The token is stored in your current session. You can also enter it per-download on the Models page.

### 📊 Dashboard

**Overview auto-refresh interval** — how often the Overview page polls for new metrics. Range: 2–60 seconds. Default: 5 seconds. Lower values = smoother charts; higher values = less CPU usage.

### 🖥️ Server Startup

Controls what happens automatically when you restart the dashboard:

| Option | Behaviour |
|--------|-----------|
| **🔄 Auto-load last model** | Starts the server immediately using the last model you had loaded |
| **❓ Ask me each time** | Shows a model picker when the dashboard starts |
| **⏸ Manual** | Does nothing on startup — you start the server when ready |

### 📁 Storage

Shows the file paths for all persistent data:

| Data | Location |
|------|---------|
| Config & logs | `~/.vllm_mlx_ui/` |
| Benchmark results | `~/.vllm_mlx_ui/benchmark_results.json` |
| HuggingFace model cache | `~/.cache/huggingface/hub/` |
| HuggingFace cache total size | Shown as a metric |

### 🌐 Remote Access

Controls whether other devices on your network can open the **dashboard** in their browser.

| Setting | Options |
|---------|---------|
| **Dashboard accessible from** | `127.0.0.1` (this Mac only) or `0.0.0.0` (anyone on your network) |
| **Dashboard port** | Default: 8501 |

Click **💾 Save & show connection info** to save. If you changed the address or port, a restart prompt appears — click **🔄 Restart Now** to apply the change immediately.

When set to `0.0.0.0`, a table of URLs appears showing every network interface address that can be shared with other devices.

> **Note:** This controls the dashboard web UI. To allow other devices to use the **inference server** (for AI clients like Continue, Cursor, etc.), use the **Listen on** setting on the Server page.

### 🔗 Remote Server

Configure a vllm-mlx server running on **another machine** so you can control it from this dashboard. See [Section 13: Remote Access](#13-remote-access) for detailed setup.

### 🔒 Security

Shows a security status summary:
- Warns if the inference server or dashboard is network-accessible without an API key
- Confirms when both APIs are properly protected
- Shows when everything is safely bound to localhost only

### 🔄 Auto Model Switch (Proxy)

When enabled, the management API (port 8502) acts as an OpenAI-compatible proxy with automatic model switching. If your chat client requests a model that isn't currently loaded, the server automatically restarts with that model before responding.

**Proxy URLs table** — lists all the proxy base URLs for each network interface. Use `http://<your-mac>:8502/v1` as the base URL in OpenAI-compatible clients that need multi-model switching.

### 🔌 Built-in Gradio Chat

vllm-mlx also ships with a minimal Gradio chat interface separate from this dashboard. Launch it from a terminal:
```bash
vllm-mlx-chat --model mlx-community/Llama-3.2-3B-Instruct-4bit
```
Opens at `http://127.0.0.1:7860`.

### ℹ️ About

Shows installed versions: vllm-mlx, dashboard UI, Python, macOS version, MLX device (GPU). Links to the Changelog and Security Guide.

---

## 13. Remote Access

Remote access lets you control a **Mac Studio or desktop Mac** running vllm-mlx from a **MacBook or other device** on the same network — without leaving the AI server page open on the server Mac.

### Architecture

```
Mac Studio (server Mac)
├── vllm-mlx inference server  :8000   (AI processing)
├── Management API             :8502   (remote control)
└── Dashboard (optional)       :8501   (can be left closed)

MacBook (client)
└── Dashboard                  :8501   (controls server above)
```

### Step 1 — Configure the server Mac

On the Mac running the inference server:

1. Open the dashboard and go to **Settings → 🌐 Remote Access**
2. Change "Dashboard accessible from" to **`0.0.0.0 — anyone on my local network`**
3. Click **💾 Save & show connection info** → **🔄 Restart Now**
4. Note the dashboard URL shown (e.g. `http://BradStudio.local:8501`)

Also, on the **Server page**:
1. Under Configuration → Network, set "Listen on" to **`0.0.0.0 — all network interfaces`**
2. Click **💾 Save configuration**
3. Restart the server

### Step 2 — Set up the client Mac (MacBook)

If you only want to control the server Mac without running any local AI yourself, run the remote-only installer on the MacBook:
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/clickbrain/vllm-mlx-ui/main/install-remote.sh)
```

### Step 3 — Connect to the remote server

On the MacBook's dashboard:
1. Go to **⚙️ Settings → 🔗 Remote Server**
2. Fill in:
   - **Inference server URL**: `http://BradStudio.local:8000` (do NOT include `/v1`)
   - **Management API URL**: `http://BradStudio.local:8502`
   - **Management API key**: if you set one on the server (recommended)
3. Click **💾 Save remote connection**

A live connection test runs automatically — you'll see ✅ if it's working.

### Step 4 — Switch to remote mode

In the MacBook's dashboard sidebar, a connection toggle appears:
- **🖥 Local machine** — controls the MacBook itself
- **🌐 BradStudio.local** — controls the remote server

Select the remote option to route all operations (start/stop, model downloads, chat) to the server Mac.

### What works remotely

| Feature | Works in remote mode |
|---------|---------------------|
| Start / stop / restart server | ✅ |
| View server status and logs | ✅ |
| Download models (to remote server) | ✅ |
| Delete models (from remote server) | ✅ |
| Switch active model | ✅ |
| Chat (goes through remote inference) | ✅ |
| Run benchmarks | ❌ (run on server Mac directly) |
| Change server configuration | ✅ |

### Firewall notes

If the client can't reach the server, check macOS Firewall on the server Mac:
- **System Settings → Network → Firewall → Options**
- Make sure `vllm-mlx-ui` (or `python3`) is allowed to accept incoming connections
- Required ports: **8000** (inference), **8502** (management)

---

## 14. Connecting External AI Apps

Once the inference server is running, any OpenAI-compatible app can connect to it. This is a standard API — no plugins or special integration needed.

### Basic connection settings

| Setting | Value |
|---------|-------|
| **Base URL** | `http://127.0.0.1:8000/v1` (local) or `http://<your-mac-ip>:8000/v1` (network) |
| **API Key** | Blank (or your key if you set one in Server settings) |
| **Model** | Any model ID you have downloaded, e.g. `mlx-community/Llama-3.2-3B-Instruct-4bit` |

The **Server page connection card** shows the exact URL and model ID to copy-paste into any client.

### Compatible apps

| App | How to configure |
|-----|----------------|
| **Continue** (VS Code extension) | Settings → Model Provider → OpenAI-compatible; paste base URL + model ID |
| **Cursor** | Settings → AI → OpenAI API Base; paste base URL |
| **Open WebUI** | Settings → Connections → OpenAI API; paste base URL |
| **LM Studio** | Local Server → OpenAI Compatible Server; point client at port 8000 |
| **Chatbox** | Settings → AI Provider → OpenAI API; paste base URL |
| **Msty** | Connections → Add → OpenAI; paste base URL |
| **Any OpenAI SDK** | Set `base_url` to your server URL |

### Python example

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="none",  # or your key if configured
)

response = client.chat.completions.create(
    model="mlx-community/Llama-3.2-3B-Instruct-4bit",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

### Auto Model Switch proxy

Enable **Auto Model Switch** in Settings to use port 8502 as a smart proxy. Point your client at:
```
http://<your-mac>:8502/v1
```

Now when your client requests any model by name in the `model` field, the server will automatically switch to that model before responding — no manual restarts needed.

### API endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/chat/completions` | Chat (OpenAI-compatible) |
| `POST /v1/completions` | Text completion |
| `POST /v1/embeddings` | Text embeddings (requires embedding model) |
| `POST /v1/rerank` | Reranking (requires rerank model) |
| `GET /v1/models` | List available models |
| `GET /health` | Server health check |
| `GET /metrics` | Prometheus metrics (if enabled) |

---

## 15. Security

### Default state (safe)

By default, both the inference server and dashboard are bound to `127.0.0.1` — only accessible from the same Mac. No external device can reach them.

### When you open to the network

If you change either server to `0.0.0.0` (all interfaces), anyone on your local network can connect. To protect your servers:

**Set an API key on the inference server:**
- Server page → Configuration → **API key** field
- Any client must send this key as `Authorization: Bearer <key>`

**Set a Management API key:**
- Settings → Remote Server → **Management API key** field
- Protects the start/stop, model download, and config endpoints

The **Settings → 🔒 Security** section shows warnings when keys are missing and the server is network-accessible.

### Best practices

| Scenario | Recommendation |
|----------|----------------|
| Just using on this Mac | No changes needed — defaults are secure |
| Sharing with MacBook on home Wi-Fi | Consider setting an API key for the inference server |
| Using on a public or office network | Set API keys for both servers; consider VPN |
| Shared home server | Set both API keys; only expose on 0.0.0.0 if needed |

---

## 16. Updates

The dashboard checks for updates once per hour and shows a banner when one is available.

### What gets updated

The update command (`brew upgrade --fetch-HEAD vllm-mlx-ui`) updates:
- **vllm-mlx-ui** — the dashboard you're using
- **vllm-mlx** — the inference engine (from waybarrios/vllm-mlx, the upstream source)
- **mlx-lm** and **huggingface-hub** — Python library dependencies

### How to update

**From the sidebar:** Click the "⬆️ Update available" badge → **Update Now & Restart**

**From Settings → 🔄 Updates:** Click **⬆️ Update Now & Restart**

**From the terminal (any time):**
```bash
brew upgrade --fetch-HEAD vllm-mlx-ui
```

### After updating

The dashboard relaunches automatically after a successful update. Your downloaded models, chat history, benchmarks, and configuration are all preserved — updates never delete your data.

---

## 17. Troubleshooting

### Dashboard won't start

```bash
# Homebrew install:
brew reinstall --HEAD clickbrain/vllm-mlx-ui/vllm-mlx-ui

# pip install:
pip install --upgrade 'vllm-mlx[ui]'
```

### "command not found: vllm-mlx-ui"

Your PATH may not include the install location. Use Homebrew (Option A) to ensure the command is always available, or run the full path printed by the installer (e.g. `/opt/homebrew/Caskroom/miniconda/base/bin/vllm-mlx-ui`).

### No models in the library

Go to **Models → Search mlx-community** and download a model, or use **Download by ID**. Recommended starter model: `mlx-community/Llama-3.2-3B-Instruct-4bit` (~2 GB).

### Server stuck on "Starting…"

This is normal — large models can take 60+ seconds to load into memory. Watch the live log (expander on the Server page) to see what's happening. If it's been more than 2 minutes without progress, click Stop and check the log for error messages.

### Port already in use

If the server fails to start with "address already in use", the Server page will show a **🔪 Kill stale server** button — click it to clear the stuck process, then try starting again.

If the dashboard itself can't start because port 8501 is taken, run:
```bash
vllm-mlx-ui --server.port 8502
```
Or change the dashboard port in Settings before restarting.

### Can't connect from another device

1. Make sure the inference server is set to **0.0.0.0** in Server → Listen on
2. Make sure the server is actually running (green banner in Overview)
3. Use the IP address shown in the Server page connection card
4. Check macOS Firewall: System Settings → Network → Firewall → allow `vllm-mlx-ui` / `python3`
5. Make sure both devices are on the same Wi-Fi or Ethernet network

### Remote dashboard shows connection error

- Verify the server Mac has the dashboard running (`vllm-mlx-ui` command must be active)
- Try using the IP address instead of `.local` hostname
- Check port 8502 is allowed through the server Mac's firewall
- See [Section 13: Remote Access](#13-remote-access) for full setup steps

### Benchmarks show no tokens/sec data

This can happen if the model failed to load or the benchmark process was interrupted. Check that:
1. The model ID is correct and the model is fully downloaded
2. No other process is using the GPU heavily
3. Try with **Prompts = 1** and a low **Max tokens** value first

### Out of memory errors

- Try a smaller model or a more heavily quantized version (e.g. 4-bit instead of 8-bit)
- Reduce **GPU memory utilisation** in Server settings to 0.85 or lower
- Enable **KV cache quantization** to compress the cache
- Restart your Mac to free any leaked GPU memory from other apps

### "TypeError: Importing a module script failed" in browser

This is a browser caching issue. Hard-reload the page: **Cmd+Shift+R** (Mac) or **Ctrl+Shift+R** (Windows/Linux).

---

## 18. Privacy

**Your AI. Your data. Full stop.**

- **Everything runs locally.** All inference, chat, and processing happens on your Mac. No cloud, no subscription, no usage limits.
- **Conversations never leave your device.** Chat history is stored in `~/.vllm_mlx_ui/chats.json` on your Mac only.
- **Prompts and model outputs are never transmitted.** The AI runs entirely on your Apple Silicon chip.
- **Streamlit telemetry is disabled.** The dashboard framework normally collects anonymous stats — we explicitly disable this at startup.

The only times this software contacts the internet are actions you explicitly trigger:

| Action | Destination | Data sent |
|--------|-------------|-----------|
| Download a model | `huggingface.co` | The model ID |
| Search for models | `huggingface.co` | Your search query |
| Check for updates | `api.github.com`, `pypi.org` | Nothing (read-only public API) |

No account required. No telemetry. No analytics. No backdoors.

---

## 19. Where Files Are Stored

| Data | Path |
|------|------|
| Configuration | `~/.vllm_mlx_ui/server_config.json` |
| Server PID | `~/.vllm_mlx_ui/server.pid` |
| Server logs | `~/.vllm_mlx_ui/server.log` |
| Chat history | `~/.vllm_mlx_ui/chats.json` |
| Benchmark results | `~/.vllm_mlx_ui/benchmark_results.json` |
| Downloaded AI models | `~/.cache/huggingface/hub/` |

All these files are stored in your home directory on your Mac. None are uploaded anywhere.

**Switching install methods:** Your downloaded models live in `~/.cache/huggingface/hub/` — completely separate from the software. You can uninstall and reinstall using a different method without losing any models.

**Backup:** To back up your settings, chat history, and benchmarks, copy the `~/.vllm_mlx_ui/` folder. To back up models, copy `~/.cache/huggingface/hub/`.

---

*Dashboard documentation for vllm-mlx-ui. The underlying vllm-mlx inference engine is maintained by [waybarrios](https://github.com/waybarrios/vllm-mlx) and contributors.*
