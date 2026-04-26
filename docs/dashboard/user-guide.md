# vllm-mlx Dashboard — User Guide

A local, no-cloud web interface for running AI language models on Apple Silicon. Everything runs on your Mac; no data leaves your machine.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Installation & First Launch](#2-installation--first-launch)
3. [Navigation](#3-navigation)
4. [Serve](#4-serve)
5. [Models](#5-models)
6. [Benchmarks & Data](#6-benchmarks--data)
7. [Chat](#7-chat)
8. [Settings](#8-settings)
9. [Remote Access](#9-remote-access)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Overview

The **vllm-mlx dashboard** is a Vue 3 single-page application served by a FastAPI management server. It gives you a graphical interface for:

- Starting and stopping the inference server
- Downloading and managing models from HuggingFace
- Running performance benchmarks
- Chatting with locally-running models
- Configuring the server and managing a fleet of remote machines

The management API runs on port **8502** by default and serves the compiled Vue UI as static files. The inference engine itself listens on port **8000**.

---

## 2. Installation & First Launch

```bash
pip install vllm-mlx
vllm-mlx-ui
```

The dashboard opens automatically at **http://127.0.0.1:8502/**. If it does not open, navigate there manually in your browser.

On first launch, go to **Models → Find** to download a model before starting the server.

---

## 3. Navigation

The sidebar on the left contains five navigation items:

| Item | Path | Purpose |
|------|------|---------|
| **Serve** | `/serve` | Start/stop the inference server, view live metrics |
| **Models** | `/models` | Browse cached models, search and download from HuggingFace |
| **Benchmarks** | `/benchmarks` | Live metrics, speed benchmarks, saved results, cost analysis |
| **Settings** | `/settings` | Updates, fleet, preferences, storage |
| **Chat** | `/chat` | Send messages to the running model |

The sidebar also shows the currently loaded model name and a memory gauge (unified memory used / total).

---

## 4. Serve

The Serve page is the main control centre for the inference engine.

### Starting and stopping

- **Start** — launches the inference server with the configured model and settings.
- **Stop** — gracefully shuts down the server.
- **Restart** — stops then immediately starts again (useful after config changes).

The model selector at the top right lets you switch models while the server is running; selecting a different model triggers a hot-reload.

### Status indicators

| Indicator | Meaning |
|-----------|---------|
| Green dot — Running | Server is up and accepting requests |
| Yellow dot — Starting | Model is loading; requests will queue |
| Red dot — Stopped | Server is not running |
| Crash banner (red) | Server exited unexpectedly; last 20 log lines shown |

### Live metrics

Four metric cards update in real time:

- **Tokens / sec** — current generation throughput
- **Memory Used / Total** — unified memory consumed by the model
- **Memory %** — warns visually above 75 %
- **Uptime** — time since last start

### Server configuration

Expand **Server Configuration** to view and edit:

| Field | Description |
|-------|-------------|
| **Model** | HuggingFace model ID currently loaded |
| **Port** | Inference server port (default 8000) |
| **Context size** | Maximum KV-cache context length |
| **Max tokens** | Default maximum output length per request |

Click **Save** to persist changes. A restart is required for most changes to take effect.

### Connection info

Expand **Connection Info** to see the base URL and all network interfaces the server is reachable on. The **Via Dashboard Proxy** section shows URLs for connecting remote clients through the management API proxy.

### Cache management

Two buttons let you free memory without restarting:

- **Clear All Cache** — flushes the entire KV cache
- **Clear Prefix Cache** — flushes only the prompt-prefix cache

### Server logs

Expand **Server Logs** to see the last 200 lines of inference server output.

---

## 5. Models

The Models page has two tabs: **Library** and **Find**.

### Library tab

Shows all models already downloaded to your machine. For each model:

- Model name and size on disk
- Best benchmark result (tok/s) if a benchmark has been run
- A link to run a benchmark for that model
- **Delete** button to remove the model from disk

Use the search box to filter the list by name.

### Find tab

Search HuggingFace for MLX-format models. Trending models load automatically. You can:

- Type a query and press **Search** (or Enter)
- Toggle **MLX only** to restrict results to quantised MLX models
- Sort by **downloads**, **likes**, or **trending** by clicking column headers
- Click **Download** on any result to queue it for download

Active downloads appear as a progress list at the top of the page.

---

## 6. Benchmarks & Data

The Benchmarks page is tabbed.

### Live tab

Real-time view of a running server:

- **8 metric cards** — uptime, active/queued/completed requests, prompt tokens, output tokens, GPU memory, peak memory
- **Requests over time** and **GPU memory** line charts (updated every 3 seconds)
- **Active requests table** — ID, model, tokens generated, elapsed time
- **Cache statistics** panel — KV-cache internals from the inference engine

### Speed tab

Runs offline benchmarks against downloaded models (or a live server if the target model is already loaded). Configure number of prompts and max tokens, select models, and start a run. Results stream in real time and are saved automatically.

### Quality tab

Coming soon — will run MMLU, GSM8K, and HumanEval evaluations.

### Saved tab

Shows all previous benchmark runs as a list (date, model name, avg tok/s). Individual runs can be deleted.

**Cost Analysis** appears at the top of the Saved tab. It reads your benchmark history and computes equivalent cloud API costs:

| Tier | Models | Input rate | Output rate |
|------|--------|-----------|------------|
| Small | <7B params | $0.15 / 1M tokens | $0.60 / 1M tokens |
| Medium | 7–30B params | $0.30 / 1M tokens | $1.20 / 1M tokens |
| Large | 30B+ params | $2.50 / 1M tokens | $10.00 / 1M tokens |

Rates are based on GPT-4o-mini (small), Claude Haiku (medium), and GPT-4o (large). The panel shows total estimated cost to date and an estimated monthly savings figure.

### Advisor tab

Coming soon — will recommend models and configurations for specific tasks.

---

## 7. Chat

The Chat page lets you converse with the running model.

### Sending messages

Type in the input box and press **Enter** (or the send button). Responses stream token by token when **Stream** is enabled.

### Message actions

Each assistant message has icon buttons for:

- **Copy** — copies the message text to clipboard
- **Regenerate** — re-runs the last prompt
- **Edit** — edits your previous message and resends

### System prompt

Click the document icon in the header to expand the **system prompt** field. Type any instructions you want the model to follow throughout the conversation.

### Parameters panel

Click the sliders icon to open the parameters panel on the right:

| Parameter | Description |
|-----------|-------------|
| **Stream** | Stream tokens as they generate |
| **Temp** | Temperature — higher = more creative output |
| **Top-P** | Nucleus sampling threshold |
| **Max tokens** | Maximum output length |
| **Optimal** button | Applies recommended settings for the currently loaded model |

### Saving conversations

Click the **Save** button in the header to save the current conversation. Saved chats appear in the left panel and can be reloaded or deleted.

### Model selector

A model picker in the header lets you switch models mid-session. Selecting a different model triggers a hot-swap on the inference server.

---

## 8. Settings

### Software Updates

Shows available updates for `vllm-mlx` and its dependencies. Click **Check for updates** and then **Update** to install.

### Fleet

Add remote vllm-mlx instances by entering a name, host/IP, and port. Fleet machines appear in the sidebar memory gauge for at-a-glance status.

### Preferences

| Option | Default | Description |
|--------|---------|-------------|
| Auto-start server on launch | Off | Start the inference server when the dashboard opens |
| Open browser on start | On | Open the browser tab automatically on `vllm-mlx-ui` launch |

### Storage

Shows the model cache path, total disk used by downloaded models, and the config file location.

---

## 9. Remote Access

You can connect to a vllm-mlx instance running on another machine on your local network.

1. On the **server** machine, run `vllm-mlx-ui` as normal.
2. Note the management API address printed in the terminal (e.g. `http://192.168.1.10:8502/`).
3. On the **client** machine, open that URL in a browser.

For security, set a management API key in **Settings** on the server. Clients connecting without the key will receive a 401 error.

> Do not expose port 8502 or 8000 directly to the internet without a management API key set. Use an SSH tunnel or reverse proxy for untrusted networks.

---

## 10. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Dashboard doesn't open | Check that `vllm-mlx-ui` is still running in your terminal. Navigate to `http://127.0.0.1:8502/` manually. |
| Server won't start | Check **Server Logs** for the error. Common causes: model not downloaded, port already in use, insufficient RAM. |
| Chat returns errors | Ensure the server status is **Running** (green dot) on the Serve page before chatting. |
| Model download stalls | Go to **Models → Library** and check the download queue. HuggingFace rate limits can cause pauses — try again after a minute. |
| Out-of-memory crash | The model is too large for your RAM. Try a more aggressively quantised variant (e.g. 4-bit instead of 8-bit) or a smaller model. |
| Cost Analysis shows no data | Run at least one benchmark from the Speed tab first. Cost estimates are derived from benchmark history. |
