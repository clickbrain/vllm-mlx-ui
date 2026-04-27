# Dashboard User Guide

The vllm-mlx Dashboard (vmUI) is a full-featured web interface for running, managing, and benchmarking local AI models on Apple Silicon. It provides a no-code way to load models, start the inference server, chat, benchmark performance, and configure advanced settings.

## Installation

### Homebrew (Recommended)

```bash
brew tap clickbrain/vllm-mlx-ui
brew install vllm-mlx-ui
vllm-mlx-ui
```

Updates ship automatically. When a new version is available, a notification appears in the UI and you can update with one click.

### pip (Developers)

```bash
pip install vllm-mlx-ui
vllm-mlx-ui
```

## Getting Started

After starting `vllm-mlx-ui`, open your browser to **http://localhost:7860**.

The dashboard is organized into six main sections in the sidebar:

| Section | Purpose |
|---------|---------|
| **Chat** | Chat with loaded models, switch presets |
| **Models** | Browse, search, download, and manage models |
| **Serve** | Start/stop the inference server, view live metrics |
| **Benchmarks** | Run performance and quality tests, view history |
| **Settings** | Configure all server and engine options |
| **Docs** | Browse documentation (you are here) |

---

## Chat

The Chat page lets you have conversations with any loaded model through the running inference server.

### Conversation Presets

The five preset buttons at the top — **Chat, Code, Creative, Analysis, Precise** — instantly apply parameter tunings suited for each task:

| Preset | Temperature | Top-p | Behavior |
|--------|-------------|-------|---------|
| **Chat** | 0.7 | 0.9 | Balanced, conversational |
| **Code** | 0.2 | 0.95 | Deterministic, accurate |
| **Creative** | 1.0 | 0.98 | Expressive, diverse |
| **Analysis** | 0.4 | 0.9 | Careful, structured |
| **Precise** | 0.1 | 0.85 | Factual, minimal |

The **Optimal** button opens the parameters panel and applies recommended settings for the current model automatically.

### Background Conversations

Conversations continue in the background even if you navigate to another tab. You can return to the Chat tab at any time to see the latest output.

### Model Selection

A model must be running (see the **Serve** tab) before you can chat. The active model is shown at the top of the chat panel.

---

## Models

The Models section has three tabs: **Library**, **Find**, and **Favorites**.

### Library

Your Library shows all models currently downloaded to your machine. From here you can:

- **Load** a model into the server with one click
- **Delete** a model to free disk space
- See model size, quantization, and context length
- Mark models as **Favorites** for quick access

### Find

Search Hugging Face for new MLX-compatible models.

**Company Quick-Filters**: Click any provider chip at the top — Meta, Qwen, Google, Microsoft, Mistral, Apple, DeepSeek, MLX Community — to instantly search for models from that organization.

**Hide Downloaded**: Enabled by default. Toggle to see models you already have.

**Filter Bar**: Narrow search results by:

| Filter | Description |
|--------|-------------|
| **Fit** | Whether the model fits in your available RAM |
| **Max size (GB)** | Upper limit on model size |
| **Min downloads** | Popularity threshold |
| **Min likes** | Community approval threshold |

**Result columns**: Name, Fit, Size, Downloads, Likes, and **Trending** (weekly HuggingFace popularity score).

To download a model, click its row and then click **Download**.

### Favorites

Models you've starred appear here for one-click access.

---

## Serve

The Serve tab is the control center for the inference server.

### Live Metrics (top of page)

Real-time performance indicators update every second:

- **Tokens/sec** — current generation throughput
- **Requests** — active concurrent requests
- **Memory Used** — RAM consumed by the model and cache (e.g., 14.8 / 64 GB)
- **Memory %** — percentage of total system RAM in use
- **Uptime** — time since server started

### Starting and Stopping

Use the **Start Server** button to load the selected model and begin serving. The status indicator changes to green and shows the server URL.

**Release Memory** frees the model's GPU/unified-memory allocation without fully stopping the management server. Use this to reclaim memory between model loads or before running memory-intensive tasks.

### Connection Info

The **Connection Info** panel shows the current server endpoint details:

- **Local URL** — `http://127.0.0.1:8000` (default)
- **Network URL** — your machine's IP address for remote clients
- **API Key** — displayed if authentication is enabled
- **OpenAI-compatible** — works as a drop-in replacement for the OpenAI Python SDK

### Remote Access

To allow other devices on your network to connect, enable **Remote Access** in the Connection Info section. This binds the server to `0.0.0.0` so clients on the same network can reach it.

For secure remote access over the internet, use an SSH tunnel or a reverse proxy; do not expose the port directly without authentication.

---

## Benchmarks

The Benchmarks section has four tabs: **Live**, **Run Tests**, **History**, and **Advisor**.

### Live

The Live tab shows real-time server metrics while the server is running.

**Cache Statistics** — shows KV-cache hit rate, total cache blocks, and occupied blocks. Requires the server to be running with `--use-paged-cache` enabled.

**Requests Over Time** — a time-series chart of request throughput. Use the range selector to zoom to the last hour, last 6 hours, or full day. Click and drag to select a custom time range.

**GPU Memory** — unified memory usage over time. Same time-range controls as the requests chart.

### Run Tests

Run standardized benchmarks to measure model performance.

#### Setting Up a Test Run

1. **Select models** — check one or more models from the left panel
2. **Select test suites** — choose Speed, Quality, or both
3. **Name the run** — give the run a descriptive label so you can find it in History later
4. **Click Run Benchmarks** — progress is shown inline with the running status on the button

#### Test Suites

| Suite | What it measures |
|-------|-----------------|
| **Speed** | Tokens per second, time to first token, latency at various concurrency levels |
| **Quality — GSM8K** | Math reasoning accuracy (grade-school math problems) |
| **Quality — MMLU** | Multi-domain knowledge accuracy (57 academic subjects) |
| **Quality — HumanEval** | Code generation accuracy (Python function completion) |

Quality tests run **without streaming** to ensure fair, reproducible accuracy measurements. Speed tests run with streaming to capture real-world latency.

#### Performance Settings

All performance-impacting Settings options (Continuous Batching, Paged KV Cache, GPU Memory Utilization, etc.) can be toggled individually before a benchmark run so you can compare the same model with and without each feature enabled.

#### Live Results

While a run is in progress:

- The **Run Benchmarks** button shows a **Running** pill
- A **live log** panel below the button streams test progress, showing which question is being answered and pass/fail status for each item
- Speed and Quality score boxes update progressively as results arrive
- Click **Stop Run** at any time to abort all in-progress tests

#### Results Summary

After a run completes:

- **Speed** box: tok/s, TTFT (time to first token), and concurrency scaling
- **Quality** box: overall accuracy % and per-suite breakdown

### History

All completed runs are saved and searchable.

**Filters** — narrow the list by:
- Search term (run name or model name)
- Date range
- Performance level (fast / average / slow)
- Test type (Speed, Quality, or both)

**Comparing Runs** — select exactly two runs from the list, then click **Compare 2 Runs**. A side-by-side comparison card appears showing differences in speed and quality scores between the two runs.

**Charts** — select any run(s) from the list to see charts of all tested models' performance metrics for that run.

### Advisor

*(Coming soon)* — The Advisor tab will analyze your benchmark history and recommend the best model for your specific hardware, use-case, and performance requirements.

---

## Settings

The Settings page controls all aspects of the inference engine. Settings take effect on the next server start unless otherwise noted.

### Safety

**Trust Remote Code** — allows running custom model code from the HuggingFace repository when loading the model. Required for some models that include custom tokenizers or architecture patches not yet merged into Transformers. Enable only for models from sources you trust, as this executes arbitrary Python code on your machine.

### Memory & Cache

**GPU Memory Utilization** — percentage of unified memory that the inference engine may use for the model and KV cache (default: 90%). Reduce to 70–80% if other applications are competing for memory.

**KV Cache Quantization** — compresses the KV cache from float16 to int8, halving its memory footprint. Requires Paged KV Cache to be enabled. Useful for large models with long contexts.

**Paged KV Cache** — stores the KV cache in fixed-size blocks rather than contiguous allocations. Enables prefix sharing between users with the same system prompt, and provides better memory fragmentation. Recommended for multi-user deployments.

**SSD KV Cache Directory** — offloads the oldest KV cache blocks to an SSD to extend effective cache size beyond available RAM. Click **Browse** to select a folder with sufficient free space. An SSD is strongly recommended; avoid using the system drive.

### Inference Engine

**Continuous Batching** — processes multiple concurrent user requests in a single batched inference pass. Enables 1.5–3× higher throughput when multiple users are sending requests simultaneously. When disabled (default), requests are processed one at a time for maximum single-user throughput.

### API & Observability

**Prometheus Metrics** — exposes a `/metrics` endpoint in the OpenMetrics format. Connect any [Prometheus](https://prometheus.io)-compatible monitoring tool (Grafana, Datadog, etc.) to collect inference metrics over time.

**Rerank Model** — pre-loads a [cross-encoder reranking model](https://www.sbert.net/docs/cross_encoder/pretrained_models.html) at startup. Used by RAG pipelines to re-score retrieved documents before passing them to the LLM. Adds a `/v1/rerank` endpoint.

### Fleet

Manage multiple vllm-mlx instances across machines on your network. Auto-detection of other vmUI instances on your local network is in development.

---

## Remote Access

### Local Network

1. Open **Settings → Connection** and enable **Remote Access**
2. Restart the server
3. Other devices on your network can reach the API at `http://<your-mac-ip>:8000`

The Network URL is always shown in the **Serve → Connection Info** panel.

### Secure Tunneling (Internet)

Use an SSH tunnel for secure remote access without exposing ports:

```bash
# On the remote machine:
ssh -L 8000:127.0.0.1:8000 user@your-mac
# Then use http://localhost:8000 on the remote machine
```

---

## Updating

When a new release is available, the dashboard shows a notification banner. Click **Update** to install the latest version via Homebrew automatically. Do not run `brew upgrade` manually — always update through the UI to ensure a clean, coordinated upgrade.

---

## Troubleshooting

### Server won't start

- Check that a model is selected in the Library tab
- Verify no other process is using port 8000: `lsof -i :8000`
- Check **Serve → Live Log** for error messages
- Try **Release Memory** first if a previous session didn't clean up

### Chat returns errors

- Ensure the server is **Running** (green indicator in Serve tab)
- The model must be fully loaded before sending the first request
- Check Settings for any unsupported option combinations

### Benchmark quality tests fail with 422 errors

- The model name must match the currently loaded model. Reload the server with the desired model first
- If using `model="default"`, verify the server started successfully

### Docs show 404

- Rebuild the package: `pip install -e .` (developer install)
- Homebrew: run `brew reinstall vllm-mlx-ui`

### Memory issues

- Reduce **GPU Memory Utilization** in Settings to 70%
- Enable **KV Cache Quantization** to reduce cache memory
- Use **Release Memory** between model switches
