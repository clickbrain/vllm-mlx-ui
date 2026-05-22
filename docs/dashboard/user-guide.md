# Dashboard User Guide

The vllm-mlx Dashboard (vmUI) is a full-featured web interface for running, managing, and benchmarking local AI models on Apple Silicon. It provides a no-code way to find the right model, start the inference server, chat, run quality benchmarks, and configure advanced settings — for both first-time users and inference experts.

## Installation

### Homebrew (Recommended)

```bash
brew tap clickbrain/vllm-mlx-ui
brew install vllm-mlx-ui
vllm-mlx-ui
```

When a new release is available, a notification banner appears in the UI. Click **Update** to install the latest version automatically. Do not run `brew upgrade` manually — always update through the UI for a coordinated upgrade.

### pip (Developers)

```bash
pip install vllm-mlx-ui
vllm-mlx-ui
```

## Navigation

After starting `vllm-mlx-ui`, open your browser to **http://localhost:7860**.

The sidebar organizes the app into five main sections in priority order:

| Section | Purpose |
|---------|---------|
| **Serve** | Start/stop the inference server, view live metrics |
| **Models** | Find, download, and manage models |
| **Benchmarks** | Run quality and speed tests; get model recommendations |
| **Chat** | Chat with loaded models |
| **Settings** | Configure all server and engine options |

### Status Row

The bottom of the sidebar always shows the active engine and loaded model:

```
● vllm-mlx
  Qwen3-14B-4bit
```

The dot is green when the server is running, gray when stopped. Click the status row to jump directly to the Serve page.

---

## Serve

The Serve tab is the control center for the inference server.

### Running Hero

When a server is running, a prominent banner at the top of the page shows:

- **Active model name** and **engine badge**
- **Tok/s** — current generation throughput
- **Uptime** — time since server started
- **Free RAM** — unified memory available

### Empty State

If no model has been configured yet, the Serve page shows a **Browse Models** button that takes you directly to the Model Finder.

### Live Metrics

Real-time performance indicators update every few seconds:

- **Tokens/sec** — generation throughput
- **Requests** — active concurrent requests
- **Memory Used** — RAM consumed by the model and cache
- **Memory %** — percentage of total system RAM in use
- **Uptime** — time since server started

### Starting and Stopping

Use the **Start Server** button to load the selected model and begin serving. The status indicator changes to green and shows the server URL.

**Release Memory** frees the model's GPU/unified-memory allocation without fully stopping the management server. Use this to reclaim memory between model loads.

### Connection Info

The **Connection Info** panel shows the current server endpoint details:

- **Local URL** — `http://127.0.0.1:8000` (default)
- **Network URL** — your machine's IP address for remote clients
- **API Key** — displayed if authentication is enabled

The endpoint table adapts to the active engine — only endpoints supported by that engine are shown:

| Engine | Endpoints shown |
|--------|----------------|
| vllm-mlx | Chat, Completions, Embeddings, Models, Health |
| rapid-mlx | Chat, Completions, Models, Health |
| Ollama | Chat, Completions, Embeddings, Models, Health |
| llama.cpp | Chat, Completions, Models, Health |
| DeepSeek ds4 | Chat, Completions, Responses, Messages, Health |

### Remote Access

To allow other devices on your network to connect, enable **Remote Access** in Settings. This binds the server to `0.0.0.0` so clients on the same network can reach it. The Network URL is always shown in Connection Info.

For secure remote access over the internet, use an SSH tunnel:

```bash
# On the remote machine:
ssh -L 8000:127.0.0.1:8000 user@your-mac
# Then use http://localhost:8000 on the remote machine
```

---

## Models

The Models section has three tabs: **Library**, **Find**, and **Favorites**.

### Library

Your Library shows all models downloaded to your machine. From here you can:

- **Load** a model into the server with one click
- **Delete** a model to free disk space
- See model size, quantization, and context length
- Mark models as **Favorites** for quick access

### Find

The Find tab searches HuggingFace for MLX-compatible models and helps you pick the best one for your hardware and use case.

#### Best Choice Badges

At the top of results, up to four **Best For** cards highlight the highest-scoring model in each category — Chat, Code, Reasoning, and Vision — based on a multi-signal algorithm:

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| Name/tag affinity | 35% | Does the model name signal this use case? |
| Benchmark quality | 30% | MMLU, HumanEval, MATH, GPQA, IFEval scores |
| Recency | 25% | How recently the model was published |
| Hardware utilization | 10% | Model fills 55–72% of total RAM (optimal band) |
| Popularity | 10% | Log-scaled download count |

See [Best Choice Scoring](model-scoring.md) for the full algorithm.

Each badge shows a reason string: `40.0 GB · 62% of your RAM · ~87% quality score · 4mo old`

**Max Age filter** (default: 18 months) — models older than this are excluded from Best Choice. Adjust using the dropdown in the use-case bar. Set to "No limit" to include all ages.

#### Use-Case Pills

The **💬 Chat / 💻 Code / 🧠 Reasoning / 🖼️ Vision** pills above the results focus the search and scoring on one category. Clicking a pill re-fetches HuggingFace results with use-case-specific query terms and highlights the winner for that category. Click again to deselect.

#### RAM Fit Indicators

Each model card shows a RAM fit gauge:

| Status | Meaning |
|--------|---------|
| 🟢 Perfect | Uses 55–85% of total RAM — optimal |
| 🟡 Good | Uses 30–55% — capable but underutilizes hardware |
| 🟠 Marginal | Uses 85–92% — fits but leaves little headroom |
| 🔴 Too large | Exceeds 92% — likely OOM |

A **yellow warning** also appears when a model fits your total hardware RAM but cannot load right now due to insufficient free memory. The warning shows exactly how much free memory is available and suggests closing other applications.

Size estimates are computed from the model name and are approximate — actual memory usage varies by model architecture.

#### Model Cards

Each result card shows:

- **Capability tags** — parameter count (7B, 70B), quantization (4-bit, 8-bit), type (Instruct, Vision, Code, Thinking)
- **Published date** — when the model was originally released on HuggingFace
- **Downloads and likes**
- **RAM fit gauge**

#### Quick Search (Company Filters)

Click a provider chip — Meta, Qwen, Google, Microsoft, Mistral, Apple, DeepSeek, MLX Community — to instantly search for models from that organization.

#### Filter Bar

| Filter | Description |
|--------|-------------|
| **Fit** | Whether the model fits in your total RAM |
| **Min size / Max size (GB)** | Size range filter |
| **Min downloads** | Popularity threshold |
| **Min likes** | Community approval threshold |

After changing size or download filters, click **Apply Filters** to re-fetch a larger result pool (100 models) with the filters applied.

#### Sorting

Sort results by Downloads, Likes, or Last Modified, in ascending or descending order. Sorting by Downloads (default) gives the most-used models first.

#### Hide Downloaded

Enabled by default — hides models you already have. Toggle to see your full library alongside new results.

### Favorites

Models you've starred appear here for one-click access.

---

## Benchmarks

The Benchmarks section has four tabs in this order: **Advisor**, **Live**, **Run Tests**, and **History**.

### Advisor

The Advisor analyzes your benchmark history and hardware to recommend the best model for your machine and use case. It combines:

- Your actual measured performance results from past benchmark runs
- Your hardware profile (chip, total RAM)
- Use-case preferences

The Advisor shows an empty state with guidance when no benchmarks have been run yet.

### Live

Real-time server metrics while the server is running.

**Cache Statistics** — KV-cache hit rate, total cache blocks, and occupied blocks. Requires `--use-paged-cache`.

**Requests Over Time** and **GPU Memory** — time-series charts with range selector (last hour, 6 hours, full day). Click and drag to zoom.

### Run Tests

Run standardized benchmarks to measure model performance.

#### Setting Up a Test Run

1. **Select models** — check one or more models from the left panel
2. **Select test suites** — choose Speed, Quality, or both
3. **Name the run** — give it a label for History
4. **Click Run Benchmarks**

#### Test Suites

| Suite | What it measures |
|-------|-----------------|
| **Speed** | Tokens/sec, time to first token, concurrency scaling |
| **Quality — GSM8K** | Grade-school math reasoning |
| **Quality — MMLU** | Multi-domain knowledge (57 subjects) |
| **Quality — HumanEval** | Python code generation |
| **Quality — MATH** | Competition math (50 problems) |
| **Quality — IFEval** | Instruction-following (38 verifiable tasks) |

Quality tests run without streaming for reproducibility. Results include **95% confidence intervals** (±%) so you can judge statistical significance.

#### Live Results

While running, a live log streams pass/fail status per question. Speed and Quality boxes update progressively. Click **Stop Run** to abort.

### History

All completed runs are saved and searchable.

**Filters** — by search term, date range, performance level, and test type.

**Comparing Runs** — select exactly two runs, then click **Compare 2 Runs**. A side-by-side card shows differences in speed and quality, including confidence intervals per suite.

**Hardware fingerprint** — every run records chip model, generation, RAM, OS version, Python version, MLX version, and dashboard version for reproducible comparisons.

---

## Chat

The Chat page lets you have conversations with any loaded model.

### Auto-Start

If you send a message when the server isn't running, Chat automatically starts the server using your current engine and model settings, waits up to 90 seconds for it to become healthy, then sends your message. A "Starting server…" status appears in the chat input while waiting.

### Conversation Presets

Five preset buttons at the top instantly apply parameter tunings:

| Preset | Temperature | Top-p | Behavior |
|--------|-------------|-------|---------|
| **Chat** | 0.7 | 0.9 | Balanced, conversational |
| **Code** | 0.2 | 0.95 | Deterministic, accurate |
| **Creative** | 1.0 | 0.98 | Expressive, diverse |
| **Analysis** | 0.4 | 0.9 | Careful, structured |
| **Precise** | 0.1 | 0.85 | Factual, minimal |

### Chat Persistence

Conversations are saved automatically to a local SQLite database (`~/.vllm_mlx_ui/chats.db`). Your history persists across restarts. A draft conversation is preserved so you can pick up mid-conversation after navigating away.

---

## Settings

The Settings page controls all aspects of the inference engine. Settings take effect on the next server start.

### Engine Selection

Choose which inference engine to use — vllm-mlx, rapid-mlx, Ollama, llama.cpp, or DeepSeek ds4. Click **Save & Restart** to apply. The engine choice persists across restarts.

### Safety

**Trust Remote Code** — allows running custom model code from HuggingFace when loading the model. Required for some models with custom tokenizers or architecture patches. Enable only for trusted sources — this executes arbitrary Python code.

### Memory & Cache

**GPU Memory Utilization** — percentage of unified memory the engine may use (default: 90%). Reduce to 70–80% if other applications compete for memory.

**KV Cache Quantization** — compresses the KV cache from float16 to int8, halving its footprint. Requires Paged KV Cache.

**Paged KV Cache** — stores the KV cache in fixed-size blocks. Enables prefix sharing and reduces fragmentation. Recommended for multi-user deployments.

**SSD KV Cache Directory** — offloads old KV cache blocks to SSD to extend effective cache beyond RAM.

### Inference

**Continuous Batching** — processes multiple concurrent requests in one batched inference pass. Enables 1.5–3× higher throughput for multiple users.

### API & Observability

**Prometheus Metrics** — exposes `/metrics` in OpenMetrics format for Grafana, Datadog, and similar tools.

**Rerank Model** — pre-loads a cross-encoder reranking model. Adds `/v1/rerank` for RAG pipelines.

### Fleet

Manage multiple vllm-mlx instances across machines on your network. Use the scan button to find other vmUI servers on your local network.

---

## Troubleshooting

### Server won't start

- Check that a model is selected (Serve page model picker or Library tab)
- Verify no other process is using port 8000: `lsof -i :8000`
- Check **Serve → Live Log** for error messages
- Try **Release Memory** first if a previous session didn't clean up

### Chat returns errors

- Ensure the server is **Running** (green dot in sidebar and Serve page)
- If Auto-Start timed out (90s), check that the model is downloaded and not too large for available RAM
- Check Settings for unsupported option combinations

### Best Choice shows old models

- Check the **Max Age** setting in the use-case bar (default 18 months) — reduce it to see only recent models
- Ensure results are sorted by **Downloads** (not Last Modified) for a representative model pool
- Click a use-case pill to focus the search on models designed for that task

### Benchmark quality tests fail with 422 errors

- The model name must match the currently loaded model. Reload the server with the desired model first.

### Docs show 404

- Developer install: `pip install -e .`
- Homebrew: `brew reinstall vllm-mlx-ui`

### Memory issues

- Reduce **GPU Memory Utilization** in Settings to 70%
- Enable **KV Cache Quantization** to reduce cache memory
- Use **Release Memory** between model switches
