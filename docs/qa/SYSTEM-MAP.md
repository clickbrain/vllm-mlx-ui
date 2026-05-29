# vllm-mlx-ui System Map
<!-- QA Living Document — update when any module changes -->
<!-- Last updated: 2026-05-29 by QA Guardian -->

This document is the authoritative reference for QA Guardian code reviews.
Every module, function, data flow, and architectural constraint is listed here.
When you change code, update the relevant section of this file.

---

## Architecture Overview

```
User
 │
 ▼
Vue 3 SPA (ui/src/)          ← served from mgmt_server on port 8502
 │  Pinia stores              ← state management
 │  api/client.ts             ← HTTP wrapper, auth, error handling
 │
 ▼
mgmt_server.py (FastAPI)     ← management API, port 8502
 │  _check_auth               ← X-Api-Key gate on all mutating endpoints
 │  /v1/* proxy               ← forwards to inference server (port 8000)
 │  /poll                     ← batched status endpoint (status+metrics+memory+config)
 │
 ├──▶ server_manager.py       ← subprocess lifecycle, config persistence
 │     └──▶ engines/          ← engine adapters (build_command, is_installed, …)
 │
 ├──▶ model_manager.py        ← HF Hub search, download queue, cache management
 │
 ├──▶ benchmark_runner.py     ← TPS/TTFT benchmark runs (custom + quality)
 │
 ├──▶ chat_store.py           ← SQLite chat persistence (WAL mode)
 │
 ├──▶ update_checker.py       ← version checks, upgrade orchestration
 │
 └──▶ hardware.py             ← sysctl-based chip/RAM detection
```

**State directory**: `~/.vllm_mlx_ui/`  
**Chat DB**: `~/.vllm_mlx_ui/chats.db`  
**Config**: `~/.vllm_mlx_ui/server_config.json`  
**Server state**: `~/.vllm_mlx_ui/server_state.json`  
**Server log**: `~/.vllm_mlx_ui/server.log`

---

## Backend Modules

### `vllm_mlx/dashboard/__init__.py`
- Exports `__version__` — single source of truth for dashboard version
- **QA rule**: version must match `pyproject.toml` `version` field before every release

---

### `vllm_mlx/dashboard/app.py`
Entry point called from `vllm-mlx-ui` CLI. Launches mgmt_server in background thread, handles startup flag files, and blocks waiting for signals.

**Key functions:**
- `main()` — parses CLI args, calls `server_manager.save_config()`, starts mgmt_server

**State files touched:** `~/.vllm_mlx_ui/ui.pid`, auto-start flags

---

### `vllm_mlx/dashboard/mgmt_server.py` (3484 lines)
The FastAPI management API. Single file containing all REST endpoints, background threads, the OpenAI-compatible proxy, and the SPA file server.

#### Middleware stack (top-to-bottom):
1. `_PermissiveHeadersMiddleware` — injects `Content-Security-Policy: frame-ancestors *`, removes `X-Frame-Options`. Pure ASGI, no BaseHTTPMiddleware overhead.
2. `CORSMiddleware` — `allow_origins=["*"]` — safe because mutating endpoints require `X-Api-Key`

#### Background threads:
| Thread | Purpose | Stop event |
|--------|---------|------------|
| `_update_scheduler_thread` | Checks for updates 15s after startup, then every hour | `_update_scheduler_stop` |
| `_benchmark_thread` | Runs benchmark jobs | `_benchmark_stop_event` |
| `_compare_thread` | Runs benchmark comparison jobs | `_compare_stop_event` |

All threads are tracked by module-level refs and joined (3s timeout) on `shutdown` event.

#### Request metrics:
- `_RECENT_REQUESTS: list[dict]` — rolling 200-request window
- `_RECENT_REQUESTS_LOCK: threading.Lock` — protects the list
- `_record_request()` — called by proxy endpoints after each completion
- `_get_live_metrics()` — computes avg/p50/p95 TTFT and TPS from 5-min window

#### Auth:
- `_get_auth_key()` — reads from `server_manager.load_config()["mgmt_api_key"]`; falls back to `os.environ["VMUI_MGMT_API_KEY"]`
- `_check_auth(x_api_key)` — FastAPI dependency; raises 403 if key is set and doesn't match; **no-ops if key is empty** (⚠ open network)

#### Endpoints (grouped):

**Health & Status**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Liveness check; returns `{"status":"ok"}` |
| GET | `/hardware` | No | Chip, RAM, OS, versions (cached 60s) |
| GET | `/status` | Yes | `server_manager.get_server_status()` |
| GET | `/poll` | Yes | Batched: status + metrics + memory + config + updates in one call |

**Server Control**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/start` | Yes | `server_manager.start_server(config)` |
| POST | `/stop` | Yes | `server_manager.stop_server()` |
| POST | `/server/load` | Yes | Hot-swap model (stop→reconfigure→start) |
| POST | `/memory/release` | Yes | `server_manager.force_release_memory()` |

**Configuration**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/config` | Yes | `server_manager.load_config()` |
| POST | `/config` | Yes | Merge-save config (deep-merge with existing) |
| GET | `/config/mgmt-key` | Yes | Returns masked key |
| POST | `/config/mgmt-key` | Yes | Set/clear management API key |
| POST | `/config/model-settings` | Yes | Per-model settings |
| GET | `/config/model-settings/{id}` | Yes | Per-model settings |
| GET/POST | `/startup-at-login` | Yes | LaunchAgent management |

**Models**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/models/cached` | Yes | Local HF cache + engine-discovered models |
| GET | `/models/gguf-files` | Yes | GGUF files scanned from disk |
| GET | `/models/cache_size` | Yes | Total cache GB |
| POST | `/models/download` | Yes | Queue HF download |
| GET | `/models/download_status/{id}` | Yes | Download progress |
| DELETE | `/models/{id}` | Yes | Delete cached model |
| GET | `/models/search` | Yes | HF Hub search |
| GET | `/models/presets` | Yes | Optimal settings for a model |
| POST | `/models/scores` | Yes | Batch fit-level scores |

**Engines**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/engines` | Yes | All registered engines with status |
| POST | `/engines/reload` | Yes | Reload engine registry |
| GET | `/engines/{id}/config-schema` | Yes | Engine settings fields |
| POST | `/engines/{id}/install` | Yes | pip install (SSE progress stream) |
| POST | `/engines/{id}/uninstall` | Yes | pip uninstall |

**Benchmarks**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/benchmarks` | Yes | Saved benchmark results |
| DELETE | `/benchmarks/{id}` | Yes | Delete one result |
| DELETE | `/benchmarks` | Yes | Clear all results |
| POST | `/benchmark/run` | Yes | Start benchmark run |
| GET | `/benchmark/output/{id}` | Yes | Stream benchmark output |
| POST | `/benchmark/stop/{id}` | Yes | Stop benchmark |
| POST | `/quality-benchmark/run` | Yes | Start quality benchmark |
| GET | `/quality-benchmark/output/{id}` | Yes | Stream quality benchmark output |
| POST | `/quality-benchmark/stop/{id}` | Yes | Stop quality benchmark |
| POST | `/custom-benchmark/run` | Yes | Start custom benchmark |
| GET | `/custom-benchmark/output/{id}` | Yes | Stream custom benchmark output |
| POST | `/custom-benchmark/stop/{id}` | Yes | Stop custom benchmark |

**Updates**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/updates` | Yes | Check for available updates |
| POST | `/updates/install` | Yes | Trigger upgrade (brew/pip) |
| GET | `/updates/install-status` | Yes | Upgrade progress |
| GET | `/updates/discovered-features` | Yes | New features detected post-upgrade |
| DELETE | `/updates/discovered-features` | Yes | Dismiss features |

**Chat**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/chats` | Yes | List conversations |
| GET | `/chats/draft` | Yes | Get or create draft conversation |
| GET | `/chats/{id}` | Yes | Get conversation + messages |
| DELETE | `/chats` | Yes | Delete all conversations |
| DELETE | `/chats/{id}` | Yes | Delete one conversation |
| POST via proxy | `/v1/chat/completions` | No | Proxied to inference server; saves to chat store |

**Fleet / Network**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/network/interfaces` | Yes | Local network interfaces |
| GET | `/network/scan` | Yes | mDNS scan for other vllm-mlx-ui nodes |
| GET | `/fleet/discover` | Yes | Multi-machine fleet discovery |
| GET | `/auto_switch_enabled` | Yes | Whether auto model-switch is on |
| POST | `/auto_switch_enabled` | Yes | Toggle auto model-switch |

**OpenAI-Compatible Proxy** (`/v1/*`)
- `POST /v1/chat/completions` — full streaming proxy; records metrics; saves to chat store
- `POST /v1/completions` — non-chat completions proxy
- `GET/POST /v1/*` (passthrough) — all other `/v1/` paths forwarded as-is

**SPA / Docs**
- `GET /api/docs/{path}` — serve markdown doc files from `docs/`
- `GET /api/docs` — table of contents
- All unmatched GETs → `ui_dist/index.html` (SPA catch-all); must be LAST

⚠ **QA Rule**: Chat API routes must be registered BEFORE the SPA catch-all. FastAPI matches in definition order.

---

### `vllm_mlx/dashboard/server_manager.py` (1720 lines)
Subprocess lifecycle management. All config I/O. All state file I/O.

#### State files:
| File | Purpose |
|------|---------|
| `server_state.json` | Runtime: `{pid, port, host, model, engine_id}` |
| `server_config.json` | Persisted user config |
| `server.pid` | Legacy — superseded by `server_state.json` |
| `server.log` | Inference server stdout/stderr |

#### Config schema (`_DEFAULT_CONFIG`):
- `config_version: 2` — schema version for migrations
- `engine_id: "vllm-mlx"` — selected inference engine
- `engine_settings: {}` — engine-specific settings keyed by engine_id
- `model: ""` — canonical HF repo ID
- `host/port: 127.0.0.1/8000`
- `mgmt_api_key: ""` — if empty, management API is open
- `max_tokens: 16384` / `max_request_tokens: 131072`
- `continuous_batching, reasoning_parser, tool_call_parser, enable_auto_tool_choice`
- `gpu_memory_utilization: 0.90`
- `startup_model_behavior: "auto"` — `auto|ask|none`
- `hf_token, offline_mode, auto_model_switch`

#### Key functions:
| Function | Description |
|----------|-------------|
| `load_config()` | Returns merged DEFAULT_CONFIG + saved JSON. Cached 1.5s in local mode. |
| `save_config(config)` | Writes `server_config.json`; resets local config cache. |
| `_migrate_config(saved)` | Adds missing keys from DEFAULT_CONFIG on load. |
| `start_server(config)` | Kills stale PIDs, builds command via engine, starts subprocess, writes PID file. Returns `(ok, message)`. |
| `stop_server()` | SIGTERM → wait 5s → SIGKILL → wait 3s. Returns `(ok, message)`. |
| `get_server_status()` | Returns `{running, healthy, pid, model, engine_id, crash_log}`. Reads process state + health probe. |
| `check_health(config)` | HTTP GET to `{engine.health_path}`; returns `(bool, dict)`. |
| `get_logs(last_n_lines)` | Tail of `server.log`; always returns `list[str]`. |
| `_is_mtplx_model(model_id)` | Detects MTPLX models by checking for `mtplx_runtime.json` sidecar in HF cache. |
| `_apply_mtplx_engine_switch(config)` | If model is MTPLX, switches `engine_id` to `lightning-mlx`. Returns `(new_config, switched_engine_id)`. |
| `force_release_memory()` | `mlx.core.metal.clear_cache()` + gc + `malloc_trim(0)`. |

#### Thread safety:
- `_server_state_lock` — protects `_last_crash_log` and `_intentional_stop_in_progress`
- `_resolved_urls_lock` — protects `_resolved_urls` mDNS cache
- `_local_cfg_lock` — protects `_local_cfg_cache` and `_local_cfg_ts`
- `_HF_TOKEN_LOCK` (in model_manager) — protects env var mutation

---

### `vllm_mlx/dashboard/engines/` — Engine Adapters

All engines extend `BaseEngine` (ABC). Registry in `engines/registry.py`.

#### `BaseEngine` contract (engines/base.py):
| Method | Required | Description |
|--------|----------|-------------|
| `build_command(config)` | ✅ | Returns `list[str]` argv |
| `is_installed()` | ✅ | Returns bool |
| `get_version()` | ✅ | Returns version string or None |
| `config_schema()` | Optional | Dynamic settings fields |
| `get_discovered_models()` | Optional | Engine-local model discovery |
| `build_env(config)` | Optional | Extra env vars for subprocess |
| `validate_model_id(id)` | Optional | Validates a model identifier |
| `resolve_launch_model(config)` | Optional | Engine-specific model alias |
| `get_fixed_model_display()` | Optional | For single-model engines (ds4) |
| `check_requirements()` | Optional | System requirements check |
| `check_warnings()` | Optional | Runtime advisory check |
| `latest_version()` | Optional | Latest PyPI version |
| `install_command()` | Optional | Default: `pip install --upgrade` |
| `uninstall_command()` | Optional | Default: `pip uninstall -y` |
| `upgrade_command()` | Optional | Default: None (not supported) |

**Well-known capability strings**: `tool_calls`, `vision`, `audio`, `continuous_batching`, `prefix_cache`, `kv_quantization`, `paged_cache`, `reasoning`, `metrics`, `embedding`, `rerank`, `mtp`, `ssd_cache`

#### Registered engines:

| Engine ID | Class | Install | Fixed Model | MTPLX | Notes |
|-----------|-------|---------|-------------|-------|-------|
| `vllm-mlx` | `VllmMlxEngine` | bundled | No | No | Default; upstream vllm-mlx package |
| `rapid-mlx` | `RapidMlxEngine` | pip | No | No | mlx-lm fork, faster startup |
| `lightning-mlx` | `LightningMlxEngine` | pip (git) | No | **Yes** | Required for MTPLX models |
| `llama-cpp` | `LlamaCppEngine` | pip | No | No | GGUF via llama-cpp-python |
| `ds4` | `Ds4M5Engine` | git clone | Yes (DeepSeek V4) | No | Auto-selects antirez/audreyt fork by chip |
| `ollama` | `OllamaEngine` | external | No | No | Ollama daemon |
| `lmstudio` | `LmStudioEngine` | external | No | No | LM Studio local server |
| `external-api` | `ExternalApiEngine` | bundled | No | No | Remote OpenAI-compatible API |
| `apple-fm` | `AppleFmEngine` | bundled | No | No | Apple Foundation Models (macOS 26+) |

⚠ **QA Rule**: Any model with `mtplx_runtime.json` in its HF cache directory MUST use `lightning-mlx` engine. `server_manager._is_mtplx_model()` detects this and `_apply_mtplx_engine_switch()` enforces it.

---

### `vllm_mlx/dashboard/model_manager.py` (1044 lines)
HuggingFace integration, download queue, fit-level scoring.

**Fit levels** (model size / total RAM):
| Level | Threshold | Emoji |
|-------|-----------|-------|
| `perfect` | < 50% | 🟢 |
| `good` | 50-70% | 🟡 |
| `marginal` | 70-85% | 🟠 |
| `too_tight` | > 85% | 🔴 |

**Key functions:**
| Function | Description |
|----------|-------------|
| `search_mlx_models(query, limit)` | HF Hub search for mlx-community models |
| `search_hf_models(query, limit)` | Broader HF search with fit scoring |
| `get_cached_models()` | Lists models in HF cache dir + engine-discovered models |
| `download_model(model_id, ...)` | Routes to local or remote download |
| `download_model_local(model_id, ...)` | HF Hub download with progress callback |
| `delete_model(model_id)` | Removes from HF cache dir |
| `get_download_status(model_id)` | Current download progress dict |
| `get_model_presets(model_id)` | Optimal settings (context, tokens, quantization) |
| `estimate_size_from_name(model_id)` | Heuristic size estimate from model name |
| `get_hf_model_size_gb(model_id)` | Exact size from HF model card |
| `check_model_fit(model_id)` | Returns `{fit_level, size_gb, total_ram_gb}` |
| `scan_gguf_files(base_dir)` | Finds GGUF files on disk |

**`DownloadManager`** (singleton):
- Thread-per-download model; downloads run in daemon threads
- `_monitor_threads: dict[str, Thread]` — tracked for cleanup
- Download status stored in module-level dict; pruned after 5 min

---

### `vllm_mlx/dashboard/chat_store.py` (245 lines)
SQLite chat persistence. WAL mode. Every operation opens a fresh connection (no shared connection across threads).

**DB schema:**
```sql
conversations (id, title, model, engine, is_draft, created_at, updated_at, message_count)
messages (id, conversation_id, role, content, reasoning, ttft_ms, tps, model, created_at)
```

**Key functions:**
| Function | Description |
|----------|-------------|
| `init_db()` | Create tables; called on startup |
| `list_conversations(limit)` | Returns list without messages |
| `save_conversation(id, title, model, engine, messages, is_draft)` | Upsert + message replace |
| `get_conversation(id)` | Returns full conversation with messages |
| `get_latest_draft()` | Returns the most recent `is_draft=1` conversation |
| `delete_conversation(id)` | Delete one conversation + messages (cascade) |
| `delete_all_conversations()` | Delete everything; returns count |

**Limits**: title 500 chars, content 1MB, reasoning 2MB, 2000 msgs/conversation

**Chat save flow**: `POST /v1/chat/completions` proxy → stream to client → on stream end → `chat_store.save_conversation()` with full message history.

**Draft ID**: stored in browser `localStorage` as `vmui_draft_id`

---

### `vllm_mlx/dashboard/update_checker.py` (889 lines)
Version checks for vllm-mlx-ui (this project), inference engines, and pip packages.

**Install method detection** (`_detect_install_method()`):
- `brew` — running from `/opt/homebrew/Cellar/vllm-mlx-ui/`
- `dev` — running from a git repo (editable install)
- `pip` — other pip install

**Check functions:**
| Function | Description |
|----------|-------------|
| `check_updates(force)` | Main function; returns `list[PackageInfo]`. Cached 1 hour. |
| `get_cached_updates()` | Returns cache without triggering a refresh |
| `bust_cache()` | Invalidates the 1-hour cache |
| `engine_upgrade_commands()` | Returns `list[list[str]]` — one argv per engine upgrade |
| `upgrade_command()` | Returns the main upgrade argv (`brew upgrade` or `pip install`) |
| `relaunch()` | Restarts the dashboard process using `PENDING_ENGINE_REINSTALLS_FILE` |
| `discover_new_features()` | Diffs engine config schemas before/after upgrade to find new options |
| `snapshot_engine_schemas()` | Saves pre-upgrade engine schemas to disk for diff |

**Thread safety**: `_cache_lock: threading.Lock` protects `_cache` dict

---

### `vllm_mlx/dashboard/benchmark_runner.py` (723 lines)
Executes performance benchmarks by calling the inference server's `/v1/chat/completions` endpoint directly.

**Functions:**
| Function | Description |
|----------|-------------|
| `run_benchmark(model_id, ...)` | Runs N warmup + M timed requests; returns `BenchmarkResult` |
| `run_custom_benchmark(model_id, prompts, ...)` | Runs against a list of custom prompts |
| `run_live_benchmark(model_id, ...)` | Real-time streaming benchmark |
| `pre_flight_check(model_id, config)` | Verifies memory, engine, MTPLX requirements before running |
| `load_results() / save_result() / delete_result()` | Persist results to `~/.vllm_mlx_ui/benchmarks.json` |

**MTPLX-awareness**: `pre_flight_check()` detects MTPLX models and requires `lightning-mlx` engine. Benchmark cannot run against an MTPLX model on the wrong engine.

---

### `vllm_mlx/dashboard/hardware.py` (99 lines)
Apple Silicon hardware detection via `sysctl`.

**Functions:**
| Function | Description |
|----------|-------------|
| `detect_chip()` | Returns chip string, e.g. `"Apple M4 Pro"` |
| `chip_generation(chip_str)` | Returns `"M1"` through `"M5"` or `"unknown"` |
| `total_ram_gb()` | Returns total unified memory in GB |
| `os_version()` | Returns macOS version string |
| `mlx_version()` | Returns installed mlx version |
| `fingerprint()` | Returns `{chip, chip_gen, total_ram_gb, os_version, python_version, mlx_version, dashboard_version}` |

---

### `vllm_mlx/dashboard/quality_runner.py` (1074 lines)
Runs structured quality evaluation benchmarks (accuracy on defined test suites).

---

### `vllm_mlx/dashboard/startup_manager.py` (123 lines)
LaunchAgent management for macOS login-item startup. Creates/removes plist in `~/Library/LaunchAgents/`.

---

### `vllm_mlx/dashboard/llm_benchmark_cache.py` (342 lines)
SQLite cache for benchmark results shared across machines. WAL mode.

---

### `vllm_mlx/dashboard/model_family_resolver.py` (306 lines)
Pattern-matching heuristics to map model IDs to model families (Qwen, Llama, Mistral, etc.) for display and preset selection.

---

## Frontend Modules (ui/src/)

### `api/client.ts`
Minimal fetch wrapper for the management API.
- Base URL: `/api` in dev (Vite proxy → port 8502), `""` in prod
- Auth: `X-Api-Key` header from `localStorage["vmui_mgmt_api_key"]`
- `authRequired: Ref<boolean>` — set to `true` on 401; cleared by `AuthUnlockPanel`
- Exports: `api.get<T>()`, `api.post<T>()`, `api.delete<T>()`

---

### Pinia Stores

#### `stores/server.ts` (440 lines)
Manages inference server state, polling, and config.

**State:**
- `status: Ref<ServerStatus>` — `{running, healthy, pid, crash_log, health}`
- `metrics: Ref<Metrics>` — TPS, TTFT, token counts, active requests
- `memory: Ref<MemoryStats>` — system RAM pressure
- `config: Ref<ServerConfig>` — current server config
- `modelId: Ref<string>` — currently loaded model
- `engineId: Ref<string>` — currently active engine

**Key actions:**
| Action | Description |
|--------|-------------|
| `startPolling()` | Every 3s: calls `fetchAllBatched()` (one `/poll` call), pauses on tab hide |
| `fetchAllBatched()` | GET `/poll` → updates status/metrics/memory/config atomically |
| `startServer(config)` | POST `/start` |
| `stopServer()` | POST `/stop` |
| `loadModel(modelId, engine)` | POST `/server/load` |

**Polling design**: Uses `document.addEventListener('visibilitychange')` to pause when tab is hidden. Falls back to individual API calls if server doesn't support `/poll`.

---

#### `stores/models.ts` (603 lines)
Manages model library, downloads, benchmarks, and MTPLX install flow.

**State:**
- `cachedModels: Ref<Model[]>` — local HF cache + engine-discovered
- `hfModels: Ref<HFModel[]>` — HF search results
- `downloadQueue: Ref<DownloadQueueItem[]>` — active downloads
- `pendingInstall: Ref<PendingInstall | null>` — set when `loadModel()` gets `needs_install`

**`loadModel(modelId, engine?)` — critical path:**
```
loadModel(id, engine?)
  ├─ POST /server/load
  ├─ response.status === "needs_install"
  │    └─ sets pendingInstall → triggers global InstallEngineModal
  ├─ response.status === "ok"
  │    └─ success; serverStore updates via next poll
  └─ error → sets actionError
```

**`retryLoadAfterInstall()` — post-install retry:**
- Called by `InstallEngineModal` after install completes
- Max 2 retry attempts (`_attempt` counter on `pendingInstall` object)
- After 3 failures: surfaces `actionError`, clears `pendingInstall`

**MTPLX rule**: Backend detects MTPLX sidecar and returns `needs_install` with `engine: "lightning-mlx"` if not installed. Frontend sets `pendingInstall` → global modal installs `lightning-mlx` → retry.

---

#### `stores/chat.ts` (108 lines)
Manages chat conversation list and current conversation.
- Draft conversation ID in `localStorage["vmui_draft_id"]`
- Auto-saves after every stream completion

---

#### `stores/updates.ts` (169 lines)
One-shot update checks on sidebar/settings mount. No periodic polling.

---

#### `stores/toast.ts` (61 lines)
Global toast notification system. Methods: `info()`, `success()`, `warning()`, `error()`.

---

#### `stores/machines.ts` (123 lines)
Multi-machine fleet management. Tracks known machines, active machine selection, switches `api/client.ts` base URL.

---

#### Other stores:
- `stores/benchmarkRun.ts` — active benchmark job state
- `stores/benchmarkFavorites.ts` — saved benchmark favorites
- `stores/commandPalette.ts` — `Cmd+K` command palette
- `stores/tour.ts` — first-run onboarding tour state

---

### Views

#### `views/ServeView.vue` (1458 lines)
Main inference control panel. Engine/model selection, server start/stop, metrics display.

**Model loading entry points**: engine dropdown selection + model dropdown selection. Both call `modelsStore.loadModel()`. Both display the global `InstallEngineModal` via `pendingInstall`.

**⚠ QA Rule**: Both entry points MUST use `modelsStore.loadModel()` — never call `/server/load` directly from a view.

**Local vs global install modal**: ServeView has a *local* `InstallEngineModal` for the "Apply & Restart" engine-selection flow (not a model load). The global modal (in `App.vue`) handles model loads. These are separate flows; do not merge them.

---

#### `views/ChatView.vue` (2096 lines)
Chat interface. Model/engine selection via dropdowns.

**`switchModel(modelId)` — model change:**
1. Sets `switchingModel.value = true` (forces select re-render on completion)
2. Calls `modelsStore.loadModel(modelId)`
3. On `needs_install`: global modal handles it
4. Sets `switchingModel.value = false` in `finally` block

**`switchEngine(engineId)` — engine change:**
- Same pattern with `switchingEngine.value`

---

#### `views/ModelsView.vue` (1578 lines)
Model library, HF search, download management, benchmarks.

**`handleLoad(modelId)` — load from models page:**
1. Calls `modelsStore.loadModel(modelId)`
2. On `needs_install`: clears `loadError`, global modal handles it
3. On error: sets `loadError`

---

#### `views/BenchmarkView.vue` (3344 lines)
Benchmark configuration, running, results display, comparison charts.

---

#### `views/SettingsView.vue` (1649 lines)
Engine management (install/uninstall/upgrade), server config, fleet management, update settings.

**Form validation** (add-machine form):
- `validateHost()` — accepts IPv4 (per-octet 0-255) or RFC hostname
- Port range: 1-65535
- Duplicate detection: blocks adding existing host:port

---

### Shared Components

| Component | Purpose |
|-----------|---------|
| `InstallEngineModal.vue` | Install engine + retry model load. Global instance in `App.vue` + local in `ServeView.vue`. |
| `ConfirmModal.vue` | Accessible confirmation dialog. Focus trap + Escape handler. |
| `ToastNotification.vue` | Toast stack, teleported to body. Auto-dismiss. |
| `ErrorBanner.vue` | Dismissable error banner with `role="alert"` |
| `Spinner.vue` | Loading indicator with `role="status"` |
| `EmptyState.vue` | Empty state placeholder |
| `ToggleSwitch.vue` | Accessible boolean toggle |
| `ModelSelector.vue` | Model dropdown with loading state |
| `CommandPalette.vue` | `Cmd+K` command palette |
| `TourOverlay.vue` | First-run onboarding tour |
| `AuthUnlockPanel.vue` | API key entry when server requires auth |

---

## Critical Data Flows

### 1. Starting the inference server
```
SettingsView or ServeView
  → serverStore.startServer(config)
  → POST /start
  → mgmt_server.start()
  → server_manager.start_server(config)
    ├─ _apply_mtplx_engine_switch(config)   ← auto-switches to lightning-mlx if MTPLX model
    ├─ engine.build_command(config)
    ├─ engine.build_env(config)
    ├─ subprocess.Popen(cmd)
    └─ _write_server_state(pid, config)
```

### 2. Loading a model (hot-swap)
```
Any view (ServeView / ChatView / ModelsView)
  → modelsStore.loadModel(modelId, engine?)
  → POST /server/load {model_id, engine_id}
  → mgmt_server.load_model()
    ├─ _is_mtplx_model(model_id) → if MTPLX and lightning-mlx not installed
    │    → return {status: "needs_install", engine: "lightning-mlx"}
    │    → frontend: sets pendingInstall → InstallEngineModal
    ├─ server_manager.stop_server()
    ├─ save_config({model, engine_id})
    └─ server_manager.start_server(new_config)
```

### 3. Installing an engine
```
InstallEngineModal (or SettingsView)
  → POST /engines/{id}/install
  → mgmt_server.install_engine() [SSE stream]
    → subprocess: pip install <package>
    → streams stdout lines to client
  → on completion: emit('installed')
  → retryLoadAfterInstall() ← called by InstallEngineModal after install
```

### 4. Polling cycle
```
serverStore.startPolling() → every 3s
  → GET /poll
  → mgmt_server.poll()
    → server_manager.get_server_status()
    → server_manager.get_metrics()  (only if running)
    → server_manager.get_memory_stats()
    → server_manager.load_config()
    → update_checker.get_cached_updates()
  → atomically updates status/metrics/memory/config/updates in store
```

### 5. Chat save flow
```
User sends message in ChatView
  → POST /v1/chat/completions (streams response)
  → mgmt_server proxy_chat()
    → forwards to inference server port 8000
    → measures TTFT, streams chunks to client, measures TPS
    → on stream end: records metrics via _record_request()
    → saves conversation via chat_store.save_conversation()
```

---

## Known Architectural Constraints

1. **Formula commit after tag** — SHA256 of the release tarball requires the tarball; the tarball requires the git tag. The formula commit is always post-tag. This is intentional, not a bug.

2. **CORS open** — `allow_origins=["*"]` is safe because all mutating endpoints require `X-Api-Key`. Management endpoints are protected; the CORS policy enables OpenAI-compatible clients.

3. **`check_same_thread=False` in SQLite** — `chat_store.py` opens a fresh connection per operation, so this is safe. No shared connection state.

4. **Dual InstallEngineModal instances** — `App.vue` hosts the global one (model loads). `ServeView.vue` hosts a local one (engine selection → Apply & Restart). These handle different flows and must not be merged.

5. **`config["model"]` is always the canonical HF repo ID** — engine-specific launch aliases go in `config["engine_settings"][engine_id]["launch_model"]`. This invariant must be maintained.

6. **mDNS IPv6 fallback** — `.local` hostnames resolve to both IPv6 link-local (fe80::) and IPv4. Python requests tries IPv6 first; link-local IPv6 lacks scope IDs so it always times out. `_force_ipv4_url()` and `_resolved_urls` cache solve this.

---

## File Ownership Boundary

**EDIT FREELY** (our code):
- `vllm_mlx/dashboard/` — everything in here
- `ui/` — entire frontend
- `docs/`, `tests/`, `scripts/`, `.github/`

**NEVER TOUCH** (upstream `waybarrios/vllm-mlx`):
- `vllm_mlx/server.py`, `engine/`, `models/`, `paged_cache.py`, `prefix_cache.py`, `ssd_cache.py`, `mcp/`, `constrained/`, `reasoning/`, `tool_parsers/`
