# Changelog — vllm-mlx Dashboard UI

## v0.8.85 — 2026-05-30

### Fixed
- **Find Models search couldn't find non-MLX models** (e.g. `apple/DiffuCoder-7B-cpGRPO`) — the search always passed `filter=mlx` to the HuggingFace API, which excludes models without the `mlx` tag. Added an "MLX models only" checkbox to the Find tab (defaults ON — existing behavior unchanged). When unchecked, searches all of HuggingFace.
- Fixed three logic bugs exposed when the toggle is OFF: client-side `is_mlx` filter now conditional on toggle; `preFilterCount` now counts all results (not just MLX) when toggle is OFF; `searchHFMore`/Load More now correctly inherits the toggle state so appended pages match the original query.

---

## v0.8.84 — 2026-05-30

### Fixed
- **Diffusion engine install failed** — `pip install git+https://github.com/MacPaw/Fast-dLLM-mlx` fails because the repo has multiple top-level packages with no explicit setuptools config. Fixed by cloning the repo, injecting a `setup.cfg` that pins `fast_dllm_mlx`, and installing with `--no-build-isolation`. Verified end-to-end.
- **Lightning-MLX shows "not installed" after brew upgrade** — `get_package_name()` returned `"lightning-mlx"` (not on PyPI), so `process_pending_engine_reinstalls()` did `pip install lightning-mlx` after upgrade → failed silently. Fixed to return the git URL so auto-reinstall works after upgrade.
- **Diffusion-MLX pending reinstall loop** — `get_package_name()` was returning the engine ID (`diffusion-mlx`, not on PyPI), causing a silent `pip install diffusion-mlx` failure after every brew upgrade. Now returns `""` to skip auto-reinstall; user reinstalls via UI when needed.
- Manually installed `lightning-mlx` into the current (0.8.83) Homebrew venv so users who already upgraded see it as installed immediately.

---

## v0.8.83 — 2026-05-30

### Fixed
- **Apple FM engine would not start** — `build_command()` was passing `"serve"` as a positional argument (treated as a chat prompt by apfel), causing the model to generate PHP server code instead of starting. Fixed to use the correct `--serve` flag. ([apple_fm.py])
- Updated default port fallback from 8000 to 11434 (apfel's native default) in case config omits the port field.

---

## v0.8.82 — 2026-05-30

### Fixed
- **Diffusion engine Python 3.13 compatibility** — The Homebrew venv runs Python 3.11, but
  `fast-dllm-mlx` requires Python 3.13+. The engine now discovers a compatible Python
  interpreter at runtime instead of using `sys.executable`.
  - Discovery order: `python3.13` on PATH (conda/miniconda preferred), known conda base paths,
    `python3.14`, then `python3` — accepts the first interpreter that reports `>= 3.13`.
  - `diffusion_server.py` is now launched by absolute path using the discovered interpreter
    (it has no `vllm_mlx` imports, so it works with any Python that has its deps).
  - `install_command()` installs `fastapi`, `uvicorn`, `pydantic`, `mlx-lm`, `huggingface_hub`,
    and `fast-dllm-mlx` into the discovered Python's environment.
  - `is_installed()` checks importability via subprocess in the discovered Python (not the
    vmui venv), with a 30-second result cache to avoid UI polling slowness.
  - `check_requirements()` now returns an error only if no Python 3.13+ can be found at all,
    rather than always failing because the vmui venv is 3.11.

## v0.8.81 — 2026-05-30

### Added
- **Apple Foundation Model (apple-fm) now benchmarkable** — the Benchmark tab now shows a
  `"Apple On-Device LLM (~3B)"` entry when apple-fm is the active engine and `apfel` is installed.
  Clicking Run benchmarks against the currently running apfel server (no model loading needed).
  - `/models/cached` injects a synthetic `"apple-fm/fixed"` entry for fixed-model engines.
  - Benchmark `_run()` detects `"/fixed"` model IDs and routes to the running server via
    `run_live_benchmark()` with the engine's correct health path (`/v1/models` for apfel vs `/health`
    for most engines).
  - `run_live_benchmark()` now accepts an optional `health_path` parameter (default: `/health`)
    so engines that use a different health endpoint can be benchmarked without errors.

### Fixed
- **Benchmark model list uses API-provided name** — model entries returned from `/models/cached`
  with a `name` field (e.g. fixed-model engines, engine-discovered models) now display their
  correct readable name in the Benchmark tab instead of the raw last path component of the ID.


### Changed
- **Diffusion MLX engine now uses Fast-dLLM-mlx** (MacPaw/Fast-dLLM-mlx) instead of the experimental mlx-lm PR branch.
  - Fast-dLLM-mlx uses KV-cache reuse and confidence-threshold parallel token finalization: 20 steps delivers quality comparable to 256 naive steps — ~5–10× faster generation.
  - No longer depends on `Goekdeniz-Guelmez/mlx-lm@adding-DiffuCoder` (unstable PR branch). Requires Python ≥ 3.13.
  - Install via Settings → Engines → Diffusion MLX → Install (now installs `fast-dllm-mlx` from GitHub).
  - Removed `alg` config field (fast-dllm-mlx uses `confidence_threshold` only). Added `block_length` (default 32) and `threshold` (default 0.9) config fields.
  - Default steps changed from 256 → 20 (equivalent quality, much faster).
  - Usage/token counts now accurate: `prompt_tokens` and `completion_tokens` populated from model response.
  - Special token stripping removed — fast-dllm-mlx decodes with `skip_special_tokens=True`.

### Added
- **Diffusion model benchmarking** — diffusion models can now be benchmarked via the Benchmark tab.
  - Auto-detected by engine ID (`diffusion-mlx`) or by model name keywords (diffucoder, diffusion, etc.).
  - `run_diffusion_benchmark()` in `benchmark_runner.py`: starts a temporary `diffusion_server.py` subprocess, waits for `/health`, runs `run_live_benchmark()` against it, then tears it down.
  - If a diffusion server is already running at port 8511, it is reused (no restart needed).
  - Results stored in the same `~/.vllm_mlx_ui/benchmark_results.json` as other benchmark results.
  - `_is_diffusion_model()` helper in `server_manager.py` detects diffusion models by name keywords.

## v0.8.79 — 2026-05-30

### Added
- **Diffusion MLX engine** — new built-in engine adapter for Dream-architecture masked-diffusion language models (e.g. Apple's DiffuCoder family). Adds a `Diffusion MLX` entry in the Settings engine list with a one-click Install button. Once installed, select it as the active engine and point it at `mlx-community/DiffuCoder-7B-cpGRPO-8bit` (or any Dream-compatible MLX model) to chat with it in the Chat UI.
  - Ships a standalone `diffusion_server.py` that exposes an OpenAI-compatible `/v1/chat/completions` endpoint so the existing Chat UI requires no changes.
  - Diffusion generation is all-at-once (bidirectional denoising over N steps) — no per-token streaming. The chat UI shows a spinner until generation completes (~5–15 s for 256 steps on a 7B model).
  - Configurable: denoising steps (32–1024, default 256), temperature, unmasking algorithm (entropy/origin/maskgit_plus/topk_margin).
  - Requires mlx-lm with Dream support. Install via the Settings panel; uses `Goekdeniz-Guelmez/mlx-lm@adding-DiffuCoder` (mlx-lm PR #270). When that PR merges, `pip install --upgrade mlx-lm` suffices.
  - DiffuCoder-7B-cpGRPO-8bit is already visible in the Find tab (it has the `mlx` tag on HuggingFace).

## v0.8.78 — 2026-05-30

### Fixed
- **Shutdown leaves rapid-mlx running as an orphan** — the Shutdown button in the dashboard only killed the UI process (vllm-mlx-ui) but left the inference engine (rapid-mlx) running with no way to stop it from the UI. Fixed: `/shutdown` now calls `stop_server()` to gracefully terminate the inference engine before killing the dashboard process.

## v0.8.77 — 2026-05-30

### Fixed
- **OOM crash from uncapped generation** — when Kilroy (or any client) sends requests with no `max_tokens`, rapid-mlx ran unboundedly. After ~17,664 tokens the MLX Metal allocator hit its resource limit (`[metal::malloc] Resource limit (499000) exceeded`), crashing the inference. This was NOT a RAM issue (61 GB free); it was Metal's internal buffer-object count limit being exhausted.
  - `proxy_default_max_tokens` default changed from `0` (disabled) to `32768`. The proxy now caps uncapped requests at 32K tokens, giving ample room for thinking + long responses while preventing infinite generation.
  - `gpu_memory_utilization` default changed from `0.0` (unset) to `0.85`. This passes `--gpu-memory-utilization 0.85` to rapid-mlx, raising the Metal allocation ceiling to 85% of device memory (~109 GB on 128 GB machines).
  - Config migration v3→v4 auto-applies both fixes to existing installs on next dashboard restart.
  - Fresh installs via Homebrew get both settings written into the initial `server_config.json`.

## v0.8.76 — 2026-05-30

### Fixed
- **Kilroy requests returning 404** — when Kilroy's API base URL is set to `http://host:port/v1/chat/completions` (with path) instead of `http://host:port`, the OpenAI SDK doubles the path to `/v1/chat/completions/chat/completions`, resulting in a silent 404. Added a catch route for the doubled path that forwards to the real endpoint. Fix your Kilroy base URL to `http://localhost:8502` (no path suffix) for the cleanest setup; the server-side catch is a safety net.

## v0.8.75 — 2026-05-29

### Fixed
- **In-app upgrade to 0.8.74 was hanging** — the Homebrew tap formula (`homebrew-vllm-mlx-ui`) was not receiving full formula body updates from the main repo; `release.sh` only patched URL/SHA/version via `sed`, leaving the old `post_install` (which auto-downloaded a 1.8 GB model) in the tap. Upgraded installs would therefore re-trigger the download on every `brew upgrade`. Fixed by rewriting `release.sh` step 9 to `cp` the full formula from the main repo before patching version fields, ensuring tap and main repo are always in sync.

## v0.8.74 — 2026-05-29

### Fixed
- **vllm-mlx still appearing in Updates panel** — the update checker had a hardcoded `_check_vllm()` function that queried PyPI for `vllm-mlx` regardless of whether it was installed. Removed it. Hidden engines (like the deprecated vllm-mlx adapter) are now skipped by the engine loop as well.

### Changed
- **Default model changed** from `mlx-community/Llama-3.2-3B-Instruct-4bit` to `qwen3.5-9b` — better quality, full reasoning support, faster on M2+.
- **Auto-download removed from `post_install`** — brew upgrade no longer blocks downloading a 1.8 GB starter model. Models are managed via the dashboard or `rapid-mlx pull <alias>`.

## v0.8.73 — 2026-05-29

### Breaking Change — vllm-mlx engine removed, rapid-mlx is now the default
**Existing installs are automatically migrated on first launch.**

- **rapid-mlx is now the primary and default local inference engine.** It delivers faster TPS, better model alias support, and actively maintained reasoning/tool-call parsers for all current models (Qwen3, Gemma4, DeepSeek, Llama, etc.)
- **vllm-mlx (PyPI package) removed** from the system. The stale `vllm-mlx 0.3.0` PyPI package was overwriting engine files with outdated code and polluting the Python namespace. It served no purpose once rapid-mlx is installed.
- **Config migration (v2 → v3):** Any saved config with `engine_id: "vllm-mlx"` is automatically rewritten to `"rapid-mlx"` on first load. No manual action required.
- **Brew formula updated:** `pip install vllm-mlx` replaced with `pip uninstall vllm-mlx` + `pip install rapid-mlx`. Existing installations cleaned on upgrade.
- **`proxy_default_max_tokens` default changed from 4096 → 0** (disabled). The previous 4096 cap was counterproductive for rapid-mlx: it overrode rapid-mlx's own thinking-token budget (6144 tokens for reasoning models), capping thinking models before they could produce an answer. rapid-mlx manages token budgets correctly on its own. Existing installs where the value was 4096 are reset to 0 on migration.
- **`max_tokens` default raised from 16384 → 32768.** Gives reasoning models (Qwen3, DeepSeek) sufficient headroom to think *and* produce a full answer. Existing installs with the old 16384 default are updated on migration.
- **`vllm-mlx-ui` is the only script entry point** in the package. The old `vllm-mlx`, `vllm-mlx-chat`, `vllm-mlx-text-chat`, and `vllm-mlx-bench` script entries pointed to upstream engine code that rapid-mlx was already replacing; they are removed. The `rapid-mlx` CLI is now provided directly by the rapid-mlx package.
- **Orphan process detection** now includes `rapid-mlx` and `rapid_mlx` process markers.

## v0.8.72 — 2026-05-29

### Fixed
- **OOM crash cycle eliminated** — the recurring "4.3-minute requests, 0 TPS" pattern was caused by Kilroy (and other external clients) sending requests with no `max_tokens` limit. The engine would generate until Metal GPU memory was exhausted (~4.3 min), abort with 0 tokens, recover, then repeat. The proxy now applies a configurable `proxy_default_max_tokens` cap (default: 4096) when a client sends no limit. This does NOT affect requests that explicitly set `max_tokens`. Configurable in Settings.
- **Clear request log** — `DELETE /debug/requests` endpoint added. Clears both the in-memory deque and the persistent `~/.vllm_mlx_ui/request_log.jsonl` file. Accessible via the "Clear Log" button in the System Monitor page.

### Added
- **Live engine status panel** in System Monitor (formerly Diagnostics). Shows real-time Metal memory (active/peak GB), generation TPS, running/waiting request counts, KV cache hit rate and memory utilization, and per-request progress bars with token counts. Polls the engine's `/v1/status` endpoint every 3 seconds.
- **OOM detection** in request log — requests that took >5 seconds and returned 0 completion tokens are flagged as likely OOM events with a red badge. The System Monitor shows a warning banner when OOM events are present, with a link to the Settings fix.
- **Proxy Default Max Tokens** setting in Settings → Network & Access. Controls the cap applied to uncapped client requests. Default: 4096. Set to 0 to disable (not recommended). Range: 0–131072.

## v0.8.71 — 2026-05-29

### Fixed
- **Model name normalization** — proxy now replaces whatever model name the client sends with the actually-loaded model before forwarding. Prevents accidental hot-swaps (multi-minute restarts) when external apps like Kilroy have a different model name configured. Applied to both `/v1/chat/completions` and `/v1/completions`. Not applied when auto-model-switch is intentionally triggering a swap.
- **Context window governor** — new `max_context_messages` config option (default 0 = unlimited). When set, the proxy trims conversation history to keep all system messages + the last N turns before forwarding. Prevents O(n²) attention cost from long histories causing very low TPS. Tool-call orphan safety included: if the trim boundary lands mid-tool-call, orphaned `role: tool` messages are dropped to prevent 400 errors from inference engines. Not applied to external API engines.
- External API engine guard added to context governor — remote API users are not affected.

### Added
- **Max Context Messages** setting in Settings → Network & Access. Number input (0 = unlimited). Recommended: 20 for general use, 10 for large models.

## v0.8.69 — 2026-05-29

### Added
- **Diagnostics page** (`/diagnostics`): New UI view accessible from the sidebar that shows a
  live-refreshing table of all proxied inference requests. Makes it easy to compare Kilroy vs
  built-in chat traffic without using `curl`. Key features:
  - **Summary by source** table: groups requests by client (Kilroy, Browser, Python, curl) and
    shows request count, average TPS, and what percentage used streaming vs batch mode.
  - **Per-request detail** table: Time, Source (parsed from User-Agent), Model, Mode (stream/batch
    badge), TTFT, Duration, TPS, Proxy overhead. Newest requests at top.
  - **Non-streaming warning**: orange banner when `stream: false` requests are detected, explaining
    that batch mode waits for all tokens before returning — the most common cause of perceived
    slowness in external apps.
  - **"How to Read This"** reference section explaining each metric.
  - Auto-refreshes every 5 seconds.

## v0.8.68 — 2026-05-29

### Added
- **Persistent request log** (`~/.vllm_mlx_ui/request_log.jsonl`): Every inference request
  proxied through port 8502 is now appended to a JSONL log file that survives server restarts.
  Rotates at 5 MB (keeps the latter half). Fields per record: `time`, `ttft_ms`, `duration_ms`,
  `tps`, `proxy_overhead_ms`, `stream`, `user_agent`, `client_ip`, `completion_tokens`, `model`.
- **Live request stream** (`GET /debug/requests/stream`): SSE endpoint that emits each request
  as it completes. Watch in real-time with `curl -N http://localhost:8502/debug/requests/stream`.
  Replays the last 10 entries on connect so you have immediate context.
- **`GET /debug/requests`** now reads from the persistent log file (survives restarts) and
  defaults to returning the last 100 entries. Returns `log_path` in the response so you know
  where to `tail -f` directly.

## v0.8.67 — 2026-05-29

### Added
- **Diagnostic request tracing** (`GET /debug/requests`): New authenticated endpoint returns the last
  N inference requests (default 50) with full timing breakdown — `ttft_ms`, `duration_ms`,
  `proxy_overhead_ms`, `stream`, `user_agent`, `client_ip`, `completion_tokens`, `model`, and human-
  readable `time`. Use this to compare requests from external clients (e.g. Kilroy) vs the built-in
  chat side-by-side to identify bottlenecks.
- **Proxy overhead measurement**: Each request now records `proxy_overhead_ms` — the time from HTTP
  request received → engine request start — covering auth check, config read, and process check.
  For model-switch requests this also includes model load time.
- **Request metadata**: `stream`, `user_agent`, and `client_ip` are now recorded for every proxied
  request. `stream: false` means the client waits for all tokens before seeing any output, which is
  the most common reason external apps appear slow compared to the built-in streaming chat.

## v0.8.66 — 2026-05-29

### Fixed
- **Critical: Server fails to start with `ImportError: cannot import name 'UnsafeRemoteURLError'`**:
  The Homebrew formula's `pip install --upgrade vllm-mlx>=0.1.0` step installed `rapid_mlx` 0.6.68
  (published 2026-05-28) into the same `vllm_mlx/` Python namespace.  When `rapid_mlx` installed
  after `vllm-mlx`, its `mllm.py` overwrote `vllm-mlx`'s version — which lacks `UnsafeRemoteURLError`
  — while `vllm-mlx`'s `server.py` remained and still imported it, causing an immediate crash on
  every `brew install` or `brew upgrade`.  Fix: removed `vllm-mlx>=0.1.0` from the formula's
  upgrade step.  Our `vllm_mlx/` package is fully self-contained (synced from upstream via git),
  so the PyPI `vllm-mlx` package was never needed and only caused harm.
- **Embeddings version floor**: Added `mlx-embeddings>=0.1.0` to the formula's upgrade step and
  bumped `pyproject.toml` from `>=0.0.5` to `>=0.1.0` to ensure the latest stable release is used.

## v0.8.65 — 2026-05-29

### Fixed
- **MTPLX model name shows "local"**: `lightning-mlx serve` defaults `served_model_name` to
  `"local"` when `--served-model-name` is not passed, causing the UI to display "local" as the
  model name instead of the real HF repo ID.  `LightningMlxEngine.build_command()` now always
  passes `--served-model-name <canonical_hf_repo_id>` so `/v1/status` returns the correct model
  name.  The flag is omitted when no model is configured (empty/missing key) to avoid passing an
  empty string.  When a `launch_model` alias override is active, the alias is still passed to the
  serve command while the canonical HF repo ID is used for the display name.
- **Engine shows "vllm-mlx" instead of "lightning-mlx" during/after restart**: The `/poll`
  endpoint defaulted `runtime.engine_id` to the hardcoded string `"vllm-mlx"` when
  `server_state.json` was absent (cleared by `stop_server()`).  The frontend always overrides
  `config.engine_id` with `runtime.engine_id`, so during the restart gap the correct
  `"lightning-mlx"` config value was silently overwritten.  Fix: `/poll` now falls back to
  `cfg.get("engine_id", "vllm-mlx")` (saved config) instead of the hardcoded string.  Also
  eliminated a redundant `sm.load_config()` call in the same endpoint.

## v0.8.64 — 2026-05-29

### Fixed
- **MTPLX / lightning-mlx 500 error on load — root cause fix**: When lightning-mlx was installed
  via pip into the Homebrew venv, its binary (`lightning-mlx`) resided in the venv's `bin/`
  directory which is NOT on `$PATH`.  `shutil.which("lightning-mlx")` returned `None`; the
  `lightning_mlx.cli` Python module fallback also doesn't exist.  `_resolve_cmd()` returned `[]`,
  causing `build_command()` to raise a `RuntimeError`, which propagated uncaught to a HTTP 500.
  **Fix**: `BaseEngine._which()` now also checks `os.path.join(os.path.dirname(sys.executable), cmd)`
  — i.e. the same venv `bin/` where `pip install` places binaries.  This fixes both
  `lightning-mlx` and `rapid-mlx` (which had the same latent bug).
- **`rapid-mlx` venv bin detection**: `RapidMlxEngine.is_installed()` also used `shutil.which`
  directly — updated to use `self._which()` for consistent venv-aware detection.
- **lightning-mlx wrong model alias**: The `_HF_TO_ALIAS` map incorrectly mapped the 8-bit MTPLX
  models (e.g. `samuelfaj/Qwopus3.6-35B-A3B-v1-8bit-MTPLX-Optimized-Speed`) to the generic alias
  `qwopus3.6-35b`, which in lightning-mlx 0.6.10 resolves to the 6-bit variant.  Updated aliases
  to use the explicit `-8bit` and `-4bit` suffixed aliases (e.g. `qwopus3.6-35b-8bit`), ensuring
  the correct quantization is loaded from cache.  For models not in the alias map, the full HF
  repo ID is passed directly (lightning-mlx accepts both aliases and HF repo IDs).
- **`_build_command()` raises unhandled RuntimeError**: Added try/except around the
  `_build_command(config)` call in `start_server()` so that engine command-building failures
  surface as clean `(False, "Failed to build launch command …")` return values instead of
  propagating as uncaught exceptions to FastAPI (which then returns a raw 500 with no detail).
- **`apple_fm.py` build command uses bare `"apfel"` string**: `build_command()` passed the string
  `"apfel"` directly to Popen instead of resolving the binary path. Now uses `self._which("apfel") or "apfel"`
  for consistent venv-aware lookup. `is_installed()` also simplified to use `self._which()`.
- **Dead code in `lightning_mlx.py`**: Removed duplicate `return False`, dead `importlib.util.find_spec`
  branch (lightning-mlx has no `lightning_mlx` Python module), and dead `enable_ngram` elif branch
  (key not in `config_schema`).


### Fixed
- **InstallEngineModal timer fires after user closes modal** — A 1200ms `setTimeout` in
  `InstallEngineModal` was firing even after the user clicked Close, calling
  `retryLoadAfterInstall()` with a null `pendingInstall` reference.  The model silently never
  loaded.  Fixed: `retryTimer` ref is now cleared in both `handleCancel()` and `onUnmounted()`.
- **retryLoadAfterInstall infinite loop** — If the backend kept returning `needs_install` after
  installation, `retryLoadAfterInstall()` would spin indefinitely with no user feedback.  Fixed:
  max 2 retry attempts; surfaces an error message after 3 failed attempts.
- **ChatView model dropdown stuck on wrong model after needs_install** — After a `needs_install`
  response the `<select>` `:value` binding didn't re-render because the bound value hadn't changed.
  Fixed: `switchingModel` ref in `switchModel()` forces a re-render via try/finally flip.
- **ModelsView stale error banner during install** — The `loadError` banner from a previous crash
  stayed visible when the install modal opened.  Fixed: `loadError` is cleared in the
  `needs_install` branch of `handleLoad()`.

### Infrastructure
- **QA sign-off gate in release.sh** — `scripts/release.sh` now requires a green sign-off token
  from the QA Guardian before any release.  Missing, stale, or RED sign-offs hard-block the
  script.  Sign-off is written by `scripts/qa-sign-off.sh`.
- **Release script hardening** — Added branch guard (must be on `main`), clean working-tree check
  (no uncommitted WIP in the release), and pre-flight divergence check that replaces the
  mid-release `git pull --rebase`.  Added partial-failure recovery hints to tarball timeout and
  formula update steps.

## v0.8.62 — 2026-05-29

### Fixed
- **MTPLX models not loading from engine/model dropdowns** — The ServeView model dropdown detected
  MTPLX models, switched the engine picker to `lightning-mlx`, and then returned early without
  actually loading the model.  The user was left with a wrong engine selected and no model load.
  Fixed: the early return is removed.  `loadModel()` is always called; the backend handles MTPLX
  detection and either installs lightning-mlx (if missing) or auto-switches and loads.
- **No install prompt when selecting MTPLX model from ChatView** — The ChatView model dropdown
  called `modelsStore.loadModel()` and silently discarded the result.  A `needs_install` response
  would set nothing visible, causing the dropdown to revert with no explanation.  Fixed via global
  install modal (see below).
- **Engine dropdown blank until API response** — The ServeView engine selector showed no options
  while the `/engines` API call was in-flight, appearing broken.  Fixed: a fallback `<option>` now
  shows the current engine ID immediately, before the full list loads.
- **Engine dropdown not updating after model switch** — After loading an MTPLX model (which
  auto-switches the engine to `lightning-mlx`), the engine picker still showed the old engine.
  Fixed: the engine watcher now always syncs from `serverStore.engineId` whenever the server's
  engine changes, as long as the user hasn't manually selected a different engine.

### Added
- **Global install modal** — `InstallEngineModal` is now mounted globally in `App.vue` and driven
  by new `modelsStore.pendingInstall` state.  Any call to `loadModel()` — from the Models page,
  ChatView, ServeView, or any future entry point — that receives a `needs_install` response will
  automatically show the install modal with live pip install progress.  After installation
  completes, the modal retries the original model load automatically.  This replaces the previous
  pattern where each view had to handle `needs_install` locally (and most didn't).

## v0.8.61 — 2026-05-29

### Fixed
- **Rapid MLX (and other pip engines) not persisting after Install Updates & Restart** — When using
  a Homebrew install, clicking "Install Updates & Restart" runs `brew upgrade vllm-mlx-ui` which
  creates a fresh venv.  Pip-installed engines (rapid-mlx, lightning-mlx) were upgraded into the
  _old_ venv but the app restarted into the _new_ venv where they were missing.  Fix: before the
  upgrade, the list of installed pip engines is saved to
  `~/.vllm_mlx_ui/pending_engine_reinstalls.json`.  On first startup in the new venv that file is
  detected and each engine is automatically reinstalled via `pip install --upgrade <pkg>` in a
  background thread, then the file is deleted.  This is a no-op for non-brew installs.

### Fixed
- **MTPLX load: "nothing happens" when `engine_id` is already `lightning-mlx`** — When the user's saved config had `engine_id = "lightning-mlx"` (from a previous auto-switch) but lightning-mlx was not installed, `_apply_mtplx_engine_switch` returned early with no warning, causing `start_server()` to fail with a 500 error that showed an unhelpful banner instead of the install modal. Now checks `is_installed()` even when the config already says `lightning-mlx` — returns `{needs_install}` in both cases.

### Added
- **MTPLX badge on model cards** — Models whose name contains "mtplx" now show an "⚡ Lightning MLX" chip in the model list, making it immediately clear they require the lightning-mlx engine.
- **Benchmark auto-switch for MTPLX models** — When a benchmark run includes an MTPLX model and lightning-mlx is installed, the benchmark system automatically switches to the lightning-mlx engine, starts the server, runs the benchmark, then restores the original engine for any subsequent non-MTPLX models. If lightning-mlx is not installed, the benchmark continues with vllm-mlx and warns about degraded performance.

## v0.8.59 — 2026-05-30

### Fixed
- **MTPLX auto-install modal wired in both paths**: when switching to an MTPLX model via the Models page (`/server/load`) OR via the Serve page Apply & Restart button, if lightning-mlx is not installed, a terminal-style install modal now appears automatically — no more silent failure or raw 500 errors.
- **`/start` endpoint returns `needs_install` signal**: when `engine_id` is `lightning-mlx` and it is not installed, the start endpoint returns `{"needs_install": "lightning-mlx"}` (HTTP 200) instead of `{"ok": false}` (which the frontend ignored, causing a silent 2-minute timeout).
- **`InstallEngineModal` template tag added to `ModelsView`**: the modal component was imported and wired in the script but its `<template>` tag was missing — now present with correct event bindings.
- **`InstallEngineModal` also added to `ServeView`**: handles the Apply & Restart path for MTPLX models.


### Fixed

- **MTPLX load: 500 error with no message** — When loading an MTPLX model from the Models page, the app returned "API error 500: /server/load" with no further information. Root cause: the API client threw `new Error('API error 500: ...')` without reading FastAPI's `{"detail": "..."}` response body. Fixed `client.ts` to parse the error body and surface the `detail` string directly.

- **MTPLX load: server killed before checking lightning-mlx** — `/server/load` stopped the currently running server (`stop_server()`) before calling `start_server()`, which then failed the lightning-mlx check and left nothing running. Reordered: MTPLX engine check now runs first; if lightning-mlx is not installed, returns HTTP 422 with install instructions WITHOUT stopping the running server.

- **MTPLX load: config saved with wrong engine_id** — Config was saved to disk with the old `engine_id` (vllm-mlx) before the engine auto-switch logic ran. Config is now saved after the engine switch so the engine selector updates correctly.

- **MTPLX load: engine switch not shown** — When lightning-mlx IS installed, the engine switch was silently applied with no user feedback. Now shows a toast notification and returns `engine_id` in the response so the Models page can display it.

### Added

- **lightning-mlx engine** — First-class support for the [lightning-mlx](https://github.com/samuelfaj/lightning-mlx) inference engine, which delivers 2–5× higher throughput on MTPLX-packaged models (Qwen3.5 MoE speculative decoding via MTP sidecar). Install via `pip install git+https://github.com/samuelfaj/lightning-mlx.git`. Configure via Settings → Inference Engine → Lightning MLX.

- **MTPLX model auto-switch** — When a model whose name contains "mtplx" is selected (e.g. `Qwopus3.6-35B-A3B-v1-8bit-MTPLX-Optimized-Speed`), the app automatically switches to the lightning-mlx engine. If lightning-mlx is installed, the engine is switched transparently and the config is saved. If it is not installed, the user receives a clear error with the install command instead of silently running on the slower engine. The Serve page also detects MTPLX models in the model picker and auto-selects lightning-mlx with a toast notification, so the user always has the correct engine before clicking Apply & Restart.

## v0.8.56 — 2026-05-29

### Fixed

- **Benchmark model-switch: false `⚠ stop_server` warning** — During multi-model benchmark runs, switching models emitted `[⚠ stop_server: Error stopping server: [Errno 1] Operation not permitted]` before proceeding to load the next model successfully. Root cause: `os.killpg()` raised `PermissionError` when the inference server's PID had already exited and been reused by an unrelated process (stale state file). Fixes: (1) `PermissionError` is now caught alongside `ProcessLookupError` in both SIGTERM and SIGKILL paths in `stop_server()` — treated as "already gone, clear state and continue"; (2) the `⚠ stop_server` warning in the benchmark stream is now suppressed when the subsequent `start_server()` succeeds, since the stop failure was non-fatal.

- **Benchmark quality: false MTPLX incompatibility warning** — Removed incorrect pre-suite warning that claimed MTPLX-named models require a `lightning-mlx` runtime and would produce 0% accuracy. This was based on an incorrect hypothesis from a prior session. MTPLX models run fine on standard mlx-lm/vllm-mlx.

## v0.8.55 — 2026-05-29

### Improved

- **Models Directory: Browse button** — The Models Directory field in Settings → Storage now has a `Browse…` button in edit mode. Opens a native directory picker via the `/browse-directory` backend endpoint instead of requiring manual path entry. Matches the existing UX of the SSD KV Cache Directory field.

## v0.8.54 — 2026-05-29

### Fixed

- **Onboarding: TourOverlay blocks SetupGuide on fresh install** — On a true fresh install, both `TourOverlay` (triggered by missing `vllm-mlx-ui-tour-completed` in localStorage) and `SetupGuide` activated simultaneously. Because `TourOverlay` uses `z-index: 9999` and teleports to `<body>`, it completely covered the SetupGuide, making onboarding invisible to new users. Fix: added a `watch` on `showSetupGuide` in `ServeView.vue` that calls `tourStore.skip()` when the setup guide is active. The tour is suppressed; users will encounter it after setup when the main UI is functional.

- **Onboarding: SetupGuide flash on existing install** — `showSetupGuide` evaluated before `fetchEngines()` completed, causing a brief flash of the setup guide even on machines with engines installed. Fixed by adding `enginesLoaded` ref (set in `fetchEngines()` finally block) as a gate condition.

## v0.8.53 — 2026-05-29

### Added

- **Guided onboarding for fresh installs (SetupGuide)** — New users no longer see an empty Serve page with unexplained `AUTH_REQUIRED` errors. When no inference engine is installed, a 5-step guided walkthrough appears automatically:
  - **Step 1 — Welcome:** Shows detected hardware (chip + RAM) so users understand what models will fit.
  - **Step 2 — Install engine:** vllm-mlx installs automatically with real-time streaming log output. All other engines (rapid-mlx, Ollama, ds4, LM Studio, Remote) are shown with install buttons so users can add them too.
  - **Step 3 — Download a model:** Hardware-aware model recommendations (models are pre-filtered to fit detected RAM). Download progress is shown inline.
  - **Step 4 — Configure server:** Port, context window, host binding, and thinking-mode toggle explained in plain language.
  - **Step 5 — Launch:** Summary card and Start Server button. Completion sets `localStorage.vmui_setup_complete = '1'` so the guide doesn't re-appear.

- **Hardware detection endpoint (`GET /hardware`)** — New unauthenticated endpoint returns `{"chip": "Apple M5 Max", "ram_gb": 128}` on macOS; returns `{"chip": "Unknown", "ram_gb": 0}` on other platforms. Used by SetupGuide for hardware-aware model recommendations.

- **AuthUnlockPanel** — For existing installs that have an `mgmt_api_key` set in `~/.vllm_mlx_ui/config.json`: if the browser has no key saved, a dismissable overlay prompts for it with the config file path as a hint. Skippable for servers with no key.

### Fixed

- **Fresh install: `AUTH_REQUIRED` on every page** — On first launch, the dashboard was calling `_init_default_api_key()` which generated a random `secrets.token_urlsafe(32)` key and wrote it to `~/.vllm_mlx_ui/config.json`. The browser had no key in `localStorage`, so every API call returned 401. Settings showed `⚠ Failed to load settings: AUTH_REQUIRED` with no recovery path. Fix: removed the auto-key generation call. The `mgmt_api_key` field defaults to `""` (no auth required) — users who want auth can set a key manually in Settings → Remote Server.

## v0.8.52 — 2026-05-28

### Fixed

- **Find Models: Max Age filter never filtered anything** — The filter computed `cutoffMs = Date.now() - maxAgeMonths * msPerMonth` (an absolute Unix timestamp, ~1.74 trillion ms) and compared it against `ageMs = Date.now() - modelDate` (a duration, ~tens of billions of ms for a year-old model). A duration is always smaller than an absolute timestamp, so the condition `ageMs <= cutoffMs` was always true and no models were ever removed. Fixed: renamed to `maxAgeMs = maxAgeMonths * msPerMonth` (a plain duration) and compare against it directly — models older than the selected threshold are now correctly excluded.



### Fixed

- **Stale PID causes "Server is already running" when inference server has crashed** — `_is_process_alive(pid)` was checking only whether an OS process with the stored PID existed (via `os.kill(pid, 0)`). After a crash, the OS can reuse that PID for a completely different process, which passes the alive check — so the dashboard declares the server running and refuses to restart it, leaving port 8000 empty. Every subsequent benchmark or chat request then gets `ConnectionRefused`. Fixed: after the PID alive check, we now verify the server is actually accepting connections on its configured port (`_port_in_use`). If the port is empty, we compare the process creation time against `started_at` from the state file (±60 s tolerance) to distinguish "still loading model" from "stale PID". Stale state is cleared and the server restarts cleanly.

- **Quality benchmark: pre-flight connectivity check aborts suite early with clear error** — Before running 20 questions, the benchmark now calls `GET /v1/models` (single fast request, no generation overhead). If the server is unreachable, the suite aborts immediately with a human-readable message instead of printing 20 "got ?, expected X" lines followed by an obscure connection error.

- **Quality benchmark: MTPLX architecture warning** — Models with "MTPLX" in the name (e.g. `samuelfaj/Qwen3.6-35B-A3B-8bit-MTPLX-Optimized-Speed`) use the `qwen3-next-mtp` architecture which requires the `lightning-mlx` runtime. Standard mlx-lm does not support this architecture and produces 0 tokens. The benchmark now detects this by name and prints a clear warning before starting the suite so the user knows why all answers will be empty, instead of silently showing 0% accuracy.



### Fixed

- **Homebrew install exits cleanly** — `brew upgrade` was returning exit code 1 after every install due to orjson's compiled `.so` file not having enough Mach-O header space for Homebrew's dylib relocation step. Added a pre-patch in the formula's `install` hook that changes the orjson install-name ID from `@rpath/...` to `@loader_path/...` before Homebrew's relocator runs. The relocator only rewrites `@rpath` and `@executable_path` entries, so it now skips orjson entirely. Python loads extension modules via `dlopen(full_path)` so this change has no runtime effect.

## v0.8.49 — 2026-05-28

### Fixed

- **Version bump** — v0.8.48 was published twice: once as the initial simple fix (remove `enable_thinking` entirely) and once as the improved retry-logic version. Users who upgraded to the first v0.8.48 would not receive the retry improvement. This release carries identical code to the correct v0.8.48 (the retry version) under a new version number so the upgrade path is unambiguous.

## v0.8.48 — 2026-05-28

### Fixed

- **Quality benchmark: improved enable_thinking handling — best of both worlds** — v0.8.47 fixed empty responses for custom Qwen3 templates (MTPLX etc.) by removing `enable_thinking: False` entirely, but that meant all thinking models would now generate full reasoning chains during benchmarks — inflating `completion_tokens`, slowing runs, and making token/sec metrics incomparable across models. v0.8.48 introduces a smarter two-attempt strategy: (1) first try with `enable_thinking: False` so standard Qwen3/DeepSeek-R1 models skip thinking and produce fast, comparable results; (2) if the response comes back empty (chunks=0, reasoning_chunks=0 — the fingerprint of a template exception), log the fallback and retry the same request without `enable_thinking` so the model thinks naturally. `_strip_thinking()` removes the `<think>…</think>` block before grading and the `reasoning_content` fallback handles reasoning-parser cases. Standard models pay zero extra cost; MTPLX/custom templates get one silent retry.

## v0.8.47 — 2026-05-28

### Fixed

- **Quality benchmark: MTPLX / custom Qwen3 fine-tunes return empty responses (chunks=0)** — Root cause: the benchmark was sending `"enable_thinking": false` and `"chat_template_kwargs": {"enable_thinking": false}` in the request body. The upstream engine's `_stream_generate_text` passes `enable_thinking=False` directly to `tokenizer.apply_chat_template()` — but only catches `TypeError` when the template rejects an unknown kwarg. Custom Qwen3 fine-tunes (including MTPLX-optimized models) may use templates that raise a Jinja2 `TemplateError` instead of `TypeError` when `enable_thinking` is not defined in their template. That non-TypeError exception propagates through `_ensure_sse_terminal` which swallows it, emits only `data:[DONE]`, and returns HTTP 200. Our code then sees `chunks=0` and `reasoning_chunks=0`. Fixed: the benchmark no longer sends `enable_thinking` or `chat_template_kwargs` at all. The model thinks naturally; if the server has a reasoning parser active, thinking tokens land in `reasoning_content` and our fallback promotes them to `text`; without a reasoning parser, `<think>…</think>` appears inline in `content` and `_strip_thinking()` removes it before grading.

## v0.8.46 — 2026-05-28

### Fixed

- **Quality benchmark: Qwen3 thinking models still return "got ?" with reasoning parser enabled** — When the vllm-mlx server has a reasoning parser configured (e.g., `--reasoning-parser qwen3`), the server checks `request.enable_thinking is not False` to decide whether to skip it. Previously, the benchmark only sent `"chat_template_kwargs": {"enable_thinking": false}` — which disables thinking at the tokenizer template level but leaves `request.enable_thinking = None`, so the reasoning parser still ran. With the reasoning parser active and thinking disabled at the template level, all generated tokens (the answer) were routed to `reasoning_content` in phase `pre_think` (no `<think>` tag appeared, so the state machine treated every token as implicit reasoning). The `content` stream stayed empty, and the `reasoning_content` fallback still worked in some cases — but only if the reasoning text survived `_strip_thinking()` without being wiped. Fixed: benchmark requests now send `"enable_thinking": false` at the **top level** of the JSON body (in addition to `chat_template_kwargs`). This sets `request.enable_thinking = False` on the server, which (a) disables the reasoning parser entirely and (b) passes `enable_thinking=False` to the chat template — ensuring answer tokens flow directly to `content`.

- **Silent empty-response failures** — If the inference server returned an error chunk in the SSE stream (e.g., `data: {"error": {...}}`), the benchmark swallowed it silently and returned an empty response. Fixed: the SSE parser now logs a warning when an error field is present in a chunk. Additionally, a warning is emitted when both `content` and `reasoning_content` streams are empty at the end of a request, including the target URL and model name for easier diagnosis.

## v0.8.45 — 2026-05-28

### Fixed

- **In-app upgrade silently aborts on Apple Silicon** — The upgrade command included `pip install --upgrade ... vllm` where `vllm` is the Linux/NVIDIA GPU inference engine (no macOS ARM wheel). On Apple Silicon this pip step could hang trying to build from source, eventually hitting the 300-second timeout. When the timeout fires, the upgrade thread returns early — the `RELAUNCH_FLAG` is never written and the app never restarts. Fixed: removed `vllm` from the pip install step in both the Homebrew and pip upgrade paths.

- **Homebrew upgrade ran unnecessary pip step** — After `brew upgrade vllm-mlx-ui` the command also ran `pip install --upgrade mlx-lm huggingface-hub` inside the Homebrew cellar venv. `brew upgrade` already pins and installs all formula dependencies; the extra pip step could override managed versions with incompatible ones. Fixed: Homebrew upgrade path now runs only `git pull && brew upgrade vllm-mlx-ui`.

## v0.8.44 — 2026-05-28

### Fixed

- **`_strip_thinking()` regex too aggressive** — The unclosed `<think>` block fix in v0.8.43 used `re.sub(r"<think>.*", ...)` which stripped any `<think>` tag anywhere in the text, including mid-sentence ones like `"Hello<think> no close"` → `"Hello"`. Fixed: the regex now anchors to the start of the text (`^\s*<think>.*`) so only `<think>` blocks at the beginning of a response (the real-world truncated-thinking case) are stripped. Mid-text `<think>` tags are preserved unchanged.

## v0.8.43 — 2026-05-28

### Fixed

- **Quality benchmark: ALL questions return "got ?, expected X" — root cause fixed** — The benchmark was routing ALL requests to the configured remote server URL (e.g. LM Studio at `http://127.0.0.1:1234`) instead of the local inference server it had just started. Root cause: `server_url` was captured once before the benchmark thread using `sm.get_server_url()`, which returns the remote URL when `remote_server_url` is set in config. Fixed: `server_url` is now computed inside the per-model loop as `http://{host}:{port}` — always targeting the local inference server that the benchmark started and is managing. This was the primary cause of 0% accuracy on all suites across all models.

- **Thinking models burn all tokens on reasoning, emit no answer** — Models like Qwen3 with `enable_thinking=True` (the default) can fill `max_tokens` entirely with `<think>` reasoning tokens and emit zero answer tokens. Fixed: benchmark requests now include `"chat_template_kwargs": {"enable_thinking": false}` to disable thinking mode. This forces the answer into `content` tokens where the graders expect it.

- **Unclosed `<think>` blocks produce empty graded text** — If a model emits `<think>...` but runs out of tokens before `</think>`, the previous `_strip_thinking()` regex left the entire thinking block in place. The second pass now strips `<think>.*` to end-of-string to handle this case.

## v0.8.42 — 2026-05-29

### Fixed

- **Quality benchmark: all answers "?" for thinking models** — Models like Qwen3, gpt-oss-20b, and other chain-of-thought models send their actual answer inside `delta.reasoning_content` with an empty `delta.content`. Every grader returned "?" because `content` was blank. Fixed: `_stream_completion()` now accumulates `reasoning_content` chunks and falls back to using the full reasoning text as the answer when `content` is empty. Benchmarks now score correctly for all thinking models.

- **LM Studio version shows ASCII art banner** — Newer `lms` CLI versions output a figlet/slant-font banner around the version. The dashboard was extracting raw output lines including the banner, showing garbage like `/ / / |/ / / __/ /___ _____/ (_)__ /` in the LM Studio card. Fixed: `get_version()` now strips ANSI escapes, filters out lines where ≥70% of characters are ASCII-art characters (`/\_|-* `), then applies the semver regex to clean lines only. Falls back to `lms --version` if `lms version` yields nothing.

- **Apple FM shows "not installed" after Save & Restart or Start at Login** — `is_installed()` used only `shutil.which("apfel")` which relies on the process PATH. The management server process (started from Homebrew or as a LaunchAgent) often runs with a minimal PATH that excludes `/opt/homebrew/bin`. After a page refresh the engine appeared uninstalled. Fixed: `is_installed()` now also checks `/opt/homebrew/bin/apfel`, `/usr/local/bin/apfel`, and `~/.local/bin/apfel` as fallbacks.

- **Serve page shows wrong model name for Apple FM engine** — When Apple Foundation Model engine was active, the hero model name showed the stale config `model_id` from the previous engine session (e.g. "Olmo-3-7B-Instruct-8bit") instead of "Apple On-Device LLM (~3B)". Fixed: `heroModelName` now prefers the engine's `fixed_model_display` over the raw config model ID for fixed-model engines.

- **Benchmark history: floating delete bar not visible when scrolled** — The "Delete N selected" toolbar existed at the top of the history list but disappeared off-screen as users scrolled down to check items. Fixed: added a `<Teleport to="body">` floating action bar (fixed position, bottom-center) that appears whenever any history runs are selected, with Compare / View Details / Delete buttons and a clear (✕) button. Slides in with a smooth transition.

## v0.8.41 — 2026-05-28

### Added

- **Benchmark failure alerts** — benchmarks (speed, quality, custom) now immediately fire a toast notification when they fail, showing the specific error message (out of memory, connection refused, timeout, etc.) instead of silently showing only a red "Error" badge.
- **Server crash toast** — when the inference server crashes unexpectedly while it was running, the dashboard now shows an error toast: "⚠️ Inference server crashed — check Serve page for logs". Previously there was no notification.
- **Error line highlighting in benchmark output log** — lines containing errors (`[✗`, `request error:`, OOM messages) are now shown in red in the benchmark output log, making failures immediately visible in long output.
- **OOM detection in speed benchmark results** — speed benchmark now checks the final result for `out_of_memory` error and shows a human-readable toast ("model too large for available RAM") instead of silently setting phase to 'done' with no result.
- **Quality/custom benchmark abort on server timeout** — if the inference server does not start within the wait timeout, the benchmark now immediately aborts the affected model run and sets the error state (no more requests fired at a dead server).

## v0.8.40 — 2026-05-28

### Fixed

- **Quality benchmark fails with "Connection refused" when server not running** — The benchmark endpoint only started the inference server when the requested model differed from the one in config. If the model already matched but the server was simply not running, it skipped the start block and immediately fired 20 HTTP requests at a closed port. Fixed: before each model run, the endpoint now checks if the server is actually accepting requests (`GET /v1/models`). If not responding, it starts the server unconditionally — regardless of whether the model needs to change.


### Fixed

- **Benchmark History: selecting runs had no delete action** — Checking one or more runs in the History tab showed "Compare N runs" / "View details" but provided no way to act on the selection with a delete. Added a red "Delete N selected" button to the toolbar that appears whenever any runs are checked. It clears the selection immediately (so the UI is responsive) then deletes each run in sequence.


### Fixed

- **Speed benchmark output log missing** — During speed-only benchmarks the "Running" panel showed only a spinner with no output. Fixed: the benchmark backend now streams output lines per model run to a `/benchmark/output` endpoint; the frontend polls it every 1.5 s and renders a live log (`<pre>`) exactly like quality benchmarks.

- **Speed benchmark banner incorrectly said "Server not running — requires server"** — The banner for speed mode was a red error telling users to go to the Serve page first. In reality, speed benchmarks auto-start the server per model just like quality benchmarks. Fixed: replaced the RED error banner with a single unified YELLOW advisory banner for all modes: "Server not running — it will be started automatically for each model when the benchmark begins."

- **Model badge stuck on wrong model during multi-model benchmarks** — The "running / queued" badge on each model row used `serverStore.modelId` (the global serve-page model), which doesn't update as the benchmark cycles through models. Fixed: the backend now returns `current_model` in `/benchmark/status`; the frontend tracks `speedCurrentModel` and uses it for the badge, so it correctly shows which model is active during a run.

- **Engine selector in Benchmarks corrupted global config** — Changing the benchmark engine wrote immediately to `/config` via `POST /config { engine_id }`, which overwrote the global config and caused subsequent benchmarks (including Advisor) to record the wrong engine. Fixed: the engine selector no longer writes to global config; instead `engine_id` is passed as a request field in the `/benchmark/run` POST body and used only for that run.

- **Backend `/benchmark/run` now accepts `engine_id` override** — Passing `engine_id` in the run request body uses that engine for the server snapshot without touching the saved config. Advisor speed benchmarks also pass `engine_id`.

- **Speed benchmark status shows current model name** — When a benchmark is running, the spinner line now shows `"Benchmarking: <model> (N/M)"` instead of the static text "Benchmarking tok/s against live server…".


### Fixed

- **Apple Foundation Model shows stale model name in status bar** — The sidebar status bar was displaying `serverStore.modelId` (which holds the model ID from the previous engine's config, e.g. `Olmo-3-7B-Instruct-8bit`) when Apple Foundation Model was active. Fixed: when the active engine returns a `fixed_model_display` (e.g. `"Apple On-Device LLM (~3B)"`), the status bar now shows that instead.

- **Apple Foundation Model chat returns no response** — `buildBody()` was sending `model: 'Olmo-3-7B-Instruct-8bit'` to apfel's OpenAI-compatible endpoint. Apfel validates the model field and returns 404/400 for unrecognized IDs. Fixed: the `model` field is now omitted from the request body for engines that have a `fixed_model_display`, so apfel uses its built-in default.

- **Apple Foundation Model chat model picker shows nothing** — The chat header hid the model picker when `modelsStore.models.length === 0`. Apple FM has no cached HuggingFace models so the picker was hidden with no label. Fixed: a static label badge (`"Apple On-Device LLM (~3B)"`) is now shown in the chat header for fixed-model engines.

- **Apple Foundation Model "No model loaded" warning shown incorrectly** — The warning appeared even when a fixed-model engine was active. Fixed to check `fixedModelDisplay` before showing the warning.

### Changed

- **Benchmarks: "Run Tests" is now the default tab** — Previously "Advisor" was the first/default tab; "Run Tests" is now first and the default on load.

- **Benchmarks: Engine selector in Run Tests** — When multiple inference engines are installed, a dropdown now appears in the "Configure & run" column allowing the user to choose which engine is used for the benchmark run. The selector is hidden when only one engine is installed.

## v0.8.36 — 2026-05-28

### Fixed

- **Start at login never actually starts the app** — `RunAtLoad` was intentionally
  removed in v0.8.35 to prevent the plist-load from killing the current session.
  But a LaunchAgent without `RunAtLoad = true` is never executed by macOS at login —
  it is merely registered. The app appeared "enabled" but did nothing on restart.
  Fixed: `RunAtLoad = true` is back in the plist. `launchctl load` is no longer
  called when the toggle is enabled (so no double-start); macOS reads the plist at
  the next login and starts the app then.

- **Start at login silently breaks after `brew upgrade`** — `_resolve_binary()`
  used `os.path.realpath()` which resolved the `/opt/homebrew/bin/vllm-mlx-ui`
  symlink to its versioned Cellar path (e.g. `.../0.8.35/bin/vllm-mlx-ui`). After
  a `brew upgrade` the plist still contained the old path, pointing to a
  non-existent binary. Fixed: use the stable Homebrew symlink
  `/opt/homebrew/bin/vllm-mlx-ui` directly, which always points to the
  currently-installed version.

- **LM Studio version shows ASCII art lines with `(` and `)`** — The previous
  fix added a fallback that returned "the first non-art line", but the
  ASCII-art filter regex `[_\s\-=|/\\#*+~^.]+` did not include `(` or `)`.
  Lines like `/ / / |/ / / __/ /___ _____/ (_)__ / ___/ / / _/` passed the
  filter and were returned as the version string. Removed the unreliable fallback
  entirely — `get_version()` now returns `None` when no semver is found. Also
  upgraded the ANSI escape-code stripper from `\x1b\[[0-9;]*m` (SGR only) to the
  comprehensive CSI pattern `\x1b\[[0-?]*[ -/]*[@-~]` which handles all
  VT100/ANSI control sequences, not just colour codes.

## v0.8.35 — 2026-05-28

### Fixed

- **Start at login kills current session** — The LaunchAgent plist was written with
  `RunAtLoad = True`. When `launchctl load -w` was called to activate the plist,
  macOS immediately spawned a second `vllm-mlx-ui` process. That second instance
  ran the startup logic ("Stopping previous instance(s)"), killed the running server,
  and replaced the session — causing the Settings page to reload and show engines
  (e.g. apfel) as "not installed". Fixed by removing `RunAtLoad` from the plist
  (defaults to False). The LaunchAgent now starts only at actual login, not when
  the toggle is first enabled.

- **Start at login — engines show as "not installed" after login** — Processes
  launched by launchctl have a minimal `PATH` that does not include
  `/opt/homebrew/bin`. `shutil.which("apfel")` (and similar) returned `None`,
  making Homebrew-installed engines appear uninstalled. Fixed by adding an explicit
  `EnvironmentVariables.PATH` to the plist that includes all standard Homebrew and
  system binary locations.

- **LM Studio version still shows ASCII art** — ANSI stripping was working but the
  semver regex `(\d+\.\d+\.\d+)` required three version parts and missed two-part
  versions like `0.3`. Also, the fallback returned the first line of output even if
  it was a pure ASCII-art line (`__ __ ___ ______`). Fixed the regex to accept
  two-part versions (`v?(\d+\.\d+(?:\.\d+)?[\w.-]*)`) and the fallback now skips
  lines consisting only of ASCII art characters.

## v0.8.34 — 2026-05-28

### Added

- **Start at login (macOS)** — New toggle in Settings → Preferences lets users choose whether
  vllm-mlx-ui launches automatically at macOS login. When enabled, a LaunchAgent plist is written
  to `~/Library/LaunchAgents/com.clickbrain.vllm-mlx-ui.plist` and loaded immediately via
  `launchctl load`. Disabling it unloads and removes the plist. The toggle is only shown on macOS.
  Startup output is logged to `~/.vllm_mlx_ui/startup.log`.

## v0.8.33 — 2026-05-28

### Fixed

- **Apple Foundation Model install fails** — `install_command()` used
  `brew install Arthur-Ficial/apfel/apfel` which requires a tap repo named
  `homebrew-apfel` that does not exist. The correct tap is
  `Arthur-Ficial/tap` (`homebrew-tap`). Fixed to
  `brew install Arthur-Ficial/tap/apfel`.

## v0.8.32 — 2026-05-28

### Fixed

- **LM Studio version display garbled with ANSI codes** — `lms version` outputs a
  coloured ASCII-art banner with ANSI escape sequences. `get_version()` was taking the
  raw first line and returning it as-is, causing Settings to show `[38;5;166m __ __ ___`
  garbage. Now strips all ANSI codes and extracts the semver string (e.g. `0.3.12`)
  from anywhere in the output.

## v0.8.31 — 2026-05-28

### Fixed

- **Apple Foundation Model warning label** — Engine cards showing `requirements_warnings`
  displayed a hardcoded "⚡ Low Available Memory" title for all warnings regardless of
  content. The Apple FM engine's warnings (e.g. "Apple Intelligence may not be enabled")
  have nothing to do with memory. Changed to generic "⚠ Warnings" label that fits all
  engines.

## v0.8.30 — 2026-05-28

### Fixed

- **Reverted v0.8.29 cap on `max_request_tokens`** — v0.8.29 capped `max_request_tokens`
  at 32,768 and rejected any client request above that with HTTP 400.  This was wrong:
  clients that explicitly send a large `max_tokens` should get what they asked for.  The
  correct behaviour is to honor client-specified values while only protecting the case
  where no `max_tokens` is sent at all (fixed in v0.8.28 via the 16,384 default).
  `max_request_tokens` is restored to the model's context window (131,072 for 131K
  context models) so clients can request any output length the model supports.

- **Restored `max_request_tokens` preset from model context window** — When a model is
  selected, `max_request_tokens` is correctly set to the model's context window so the
  engine knows its ceiling.  `max_tokens` (the default generation length used when the
  client sends none) remains at 16,384 and is never overwritten by model selection.

## v0.8.29 — 2026-05-28

### Fixed

- **Kilroy (and any client that explicitly sends a large `max_tokens`) still getting
  37-minute responses after v0.8.28** — v0.8.28 fixed the default generation length
  (`max_tokens: 16384`) but `max_request_tokens` was still being set to 131,072 by
  model preset selection.  `max_request_tokens` is the hard ceiling: the vllm-mlx engine
  accepts any client request with `max_tokens ≤ max_request_tokens`.  With the ceiling
  at 131,072, a client that explicitly sends `max_tokens: 131072` bypassed the default
  entirely and still generated 131K tokens.  Fix: model selection no longer writes
  `max_request_tokens` from the model's context window.  The default value (32768) is
  preserved, so any client sending `max_tokens > 32768` now gets an immediate HTTP 400
  error instead of a 37-minute silent hang.  32,768 output tokens is ~24,000 words —
  a very generous cap that covers all realistic use cases.

- **Model selection no longer corrupts token limits at all** — Both `max_tokens` (default
  generation length) and `max_request_tokens` (client output cap) are now left untouched
  when selecting a model.  The model's context window is stored as `context_length` for
  display purposes only.  Users control token limits explicitly in Settings.

## v0.8.28 — 2026-05-28

### Fixed

- **Root cause of Kilroy / external API clients getting 37-minute responses** — Selecting
  any model in the UI called `get_model_presets()` which reads the model's context window
  from HuggingFace (e.g. 131,072 for Qwen3-based models) and silently overwrote **both**
  `max_tokens` AND `max_request_tokens` in `server_config.json`.  These are two different
  settings: `max_request_tokens` is the maximum context a client may send (correctly = context
  window), but `max_tokens` is the **default generation length** used when a client sends
  `max_tokens: null` — it should never be set to the full context window.  With
  `max_tokens=131072`, every Kilroy request with no explicit token cap caused the thinking
  model to fill the entire 131K context with `<think>` reasoning before attempting to
  answer, taking ~37 minutes at 60 t/s and producing no visible reply.  Fix: selecting a
  model now only updates `max_request_tokens` from the model's context window; `max_tokens`
  (the generation cap) is never touched by model selection.

- **`max_tokens` default lowered from 32768 to 16384** — The previous default of 32768 was
  already too large for thinking models.  16384 provides a sane upper bound for generation
  length (roughly 12,000 words of output) while still supporting multi-turn conversations
  and tool-call chains without exhausting the context window.

## v0.8.27 — 2026-05-28

### Fixed

- **P0 regression from v0.8.26: `SyntaxError` on startup** — The edit that added
  `is_server_process_running()` to `server_manager.py` accidentally dropped the
  `def set_server_healthy() -> None:` function definition line.  The orphaned function
  body caused a `SyntaxError` (name used prior to `global` declaration) that prevented
  the entire module from importing, crashing the app immediately on launch.

## v0.8.26 — 2026-05-28

### Fixed

- **P0: 10+ minute request hangs when inference engine is actively generating** — Every request
  through the `/v1/chat/completions` proxy triggered an HTTP health probe to port 8000 on the
  inference server (`check_health()` → `GET /health`).  The vllm-mlx simple engine is
  single-threaded: while generating tokens it cannot respond to `/health`, so the probe timed out
  (2 s timeout) and returned `healthy: False`.  The proxy then entered a 60-iteration × 4 s retry
  loop — up to **240 seconds** of waiting before forwarding a new request.  All concurrent
  requests from Kilroy queued behind this loop, causing "no response for 10+ minutes" symptoms
  despite the engine running at 71+ tok/s when measured directly.

  Fixed by replacing the per-request HTTP health probe with a fast PID-only liveness check
  (`is_server_process_running()` — no HTTP).  The wait loop now only activates when the inference
  server process has not yet started (e.g. a model is still loading after a dashboard swap), which
  is the only case where waiting is correct.  When the process is alive and generating, requests
  are forwarded immediately without any blocking probe.

## v0.8.25 — 2026-05-27

### Fixed

- **Dashboard TOKENS/SEC shows 0.0, TTFT (AVG) and REQUESTS (5M) always show "—"** — `ttftMsAvg`
  and `liveMetrics` were defined in the Pinia `useServerStore` but not included in its `return`
  statement. The store computed `tps` (tokens/sec) only, so TTFT and request-count metrics were
  permanently `undefined` in the UI regardless of what `/poll` returned.
  Added `ttftMsAvg` and `liveMetrics` to the store's return so all three dashboard stat cards
  now show real data.

- **`/v1/completions` proxy did not record requests to live metrics** — The `proxy_completions`
  handler forwarded requests but never called `_record_request()`, so completions (non-chat)
  requests were invisible to the rolling TTFT/TPS tracking window.
  Both streaming and non-streaming completions paths now record TTFT, duration, and token count.

## v0.8.24 — 2026-05-27

### Fixed

- **P0: All requests returned 500 after upgrade to v0.8.23** — `MutableHeaders` (Starlette)
  does not have a `.pop()` method. The pure ASGI middleware replacement for `BaseHTTPMiddleware`
  called `headers.pop("X-Frame-Options", None)` which raised `AttributeError` on every response.
  Fixed to use `del headers["x-frame-options"]` with an existence check.

## v0.8.23 — 2026-05-27

### Fixed

- **P0: External API calls (Kilroy, OpenAI SDK clients) received slow responses and duplicate replies**
  — Root cause: `sm.get_server_status()` (synchronous, blocking HTTP) was called from the async
  `proxy_chat` handler on **every request**, freezing the asyncio event loop for up to 2s per call
  (full timeout if the inference server was busy). This cascaded: slow health check → 60-iteration
  wait loop → Kilroy timeout → retry → both requests completed → duplicate replies.
  Fix: wrapped all `sm.get_server_status()` calls in proxy hot-path with `asyncio.to_thread()`.

- **P0: Client disconnect (timeout/abort) did not cancel upstream inference** — When a client
  disconnected mid-stream, the proxy continued running the inference request to completion, holding
  GPU/memory and queuing the client's retry behind it. Added `await request.is_disconnected()` checks
  inside every streaming loop (`proxy_chat`, model-switch path, `proxy_completions`, `proxy_v1_passthrough`).

- **P1: Non-streaming proxy path held resources after client disconnect** — Non-streaming
  `proxy_chat` and `proxy_completions` now race the inference call against a disconnect poller;
  if the client disconnects first, the fetch is cancelled (HTTP 499) and GPU is freed immediately.

- **P1: `BaseHTTPMiddleware` created a task group + memory channel per request** — Each SSE chunk
  flowed through an `anyio` memory object stream (one context switch per token). Replaced
  `_PermissiveHeadersMiddleware` with a pure ASGI middleware that intercepts only the
  `http.response.start` message to inject CORS headers. Zero per-chunk overhead.

## v0.8.22 — 2026-05-28

### Fixed

- **P0: All engines except `openai-compatible` silently failed to start (regression from v0.8.20)**
  — The `install_method == "external"` guard added for apple-fm inadvertently caught ollama,
  llama-cpp, ds4, and lm-studio (which have had `install_method = "external"` since day one).
  Guard is now ID-based: only `"openai-compatible"` gets the no-op bypass. Also updated
  `install_method` to `"brew"` in `ollama.py`, `llama_cpp.py`, and `ds4_m5.py` for correctness.

- **P1: `/v1/{path}` catch-all proxy was buffered** — The passthrough route used
  `.request()` which waited for the full response body before streaming, breaking SSE clients
  and causing long delays on streaming completions routed through this path. Rewrote to use
  `.stream()` with `StreamingResponse`.

- **P1: Quality benchmark emitted timeout/ready log messages on every poll tick** — `_cb()`
  was called inside the wait loop body rather than after it. Timeout and "ready" messages now
  fire exactly once at the correct outcome.

- **P2: Polling overlap in frontend** — `startPolling()` had no in-flight guard. On slow
  connections, multiple overlapping `/poll` requests could queue up and arrive out of order.
  Fixed with `_inFlight` boolean flag.

- **P2: `restartTimer` interval never cleared in `SettingsView.vue`** — The engine restart
  countdown `setInterval` was not cleaned up on component unmount, causing a memory leak.
  Added `onUnmounted` cleanup.

- **P2: `stop_server()` did not clear state file on unexpected exceptions** — If an error
  occurred during the kill sequence, `_clear_server_state()` was never called, leaving a
  stale PID file that would cause "server already running" errors on the next start.

- **P2: `_quality_runs` dict accessed without holding `_quality_lock`** — The poll endpoint
  `quality_benchmark_output` and `stop_quality_benchmark` read/mutated `_quality_runs` without
  the lock. All three access sites now hold `_quality_lock`.

- **P2: `_prune_quality_runs()` iterated/deleted `_quality_runs` without the lock** — Fixed
  to hold `_quality_lock` during the prune sweep.

### Performance

- **Inference process orphan prevention** — `stop_server()` now calls `os.killpg(pid, SIGTERM)`
  (kill whole process group) instead of `os.kill(pid, SIGTERM)`. Since `start_new_session=True`
  makes the engine its own session leader, only `killpg` reliably kills MLX/Metal worker
  subprocesses that hold GPU memory. Without this, orphaned workers degraded TTFT on the next
  model load.

- **Port release wait after stop** — After confirming process death, `stop_server()` now waits
  up to 2 s for the listening port to be released before returning. Eliminates the spurious
  "⚠️ Port already in use" error when restarting an engine immediately after stopping it.

## v0.8.21 — 2026-05-27

### Performance

- **`load_config()` disk I/O on every `/poll` call eliminated** — Added a 1.5-second
  in-process TTL cache for local mode config reads. The `/poll` endpoint fires every 3 s;
  without this cache it read `server_config.json` from disk on every cycle.
  `save_config()` resets the cache timestamp to ensure config changes propagate within
  1.5 s. Remote/Streamlit mode is unaffected — it uses the existing 10 s session_state cache.

### Fixed

- **`model_manager._mgmt_base()` skipped IPv4 URL cache** — The duplicate helper in
  `model_manager.py` called `_force_ipv4_url()` directly instead of delegating to
  `server_manager._mgmt_url()` (which caches the DNS result). On `.local` mDNS hostnames
  this caused a full DNS lookup on every model operation. Simplified both `_mgmt_base()`
  and `_mgmt_headers()` in `model_manager.py` to delegate to the server_manager equivalents.

### Tests

- Fixed `test_apple_fm_engine.py::TestIdentity::test_install_method_is_external` — this
  test was asserting the old buggy value (`"external"`); updated to assert `"brew"` which
  is the correct value required for `apfel serve` to actually launch.

## v0.8.20 — 2026-05-30

### Fixed

- **Apple Foundation Model engine (apple-fm) never started** — `AppleFMEngine` had
  `install_method = "external"` which caused `start_server()` to return
  `"External API engine ready"` immediately without launching the `apfel serve` process.
  Changed to `install_method = "brew"` (the correct value — apfel is a Homebrew binary).
  The `ExternalApiEngine` ("openai-compatible") remains the only engine with
  `install_method = "external"` and the guard remains valid for that engine.
- **Apple FM health check targeting wrong endpoint** — Added `health_path = "/v1/models"`
  to `AppleFMEngine`. The default was `/health` which apfel doesn't expose; it now hits
  the correct OpenAI-compatible endpoint directly instead of relying on the fallback.
- **Apple FM blocked by "No model selected" at start** — Fixed both the
  `/start` endpoint pre-check and `start_server()` to skip the model-required gate for
  engines that advertise a fixed built-in model via `get_fixed_model_display()`.
  apple-fm (and any future single-model engine) can now start without a model being
  configured by the user.
- **`_download_status` memory leak** — Completed and errored download entries accumulated
  in the in-memory dict indefinitely. Added `completed_at` timestamps and a 5-minute TTL
  prune that runs on each `GET /models/download_status` poll.
- **`check_warnings()` dead code in `apple_fm.py`** — Removed redundant `import os` and
  `import platform` inside the function body (already imported at module level). Simplified
  the macOS version check from a three-branch `if/elif/else` with two `pass` arms to a
  single `if parts[0] < 26` guard.

## v0.8.19 — 2026-05-30

### Fixed

- **Orphan inference processes degrading TTFT after restart** — `stop_server()` was calling `os.kill(pid,
  SIGTERM)` which only sends the signal to the top-level inference process. Since subprocesses are launched
  with `start_new_session=True`, the child becomes its own session and process group leader — making `pid`
  identical to the process group ID. MLX worker threads and Metal processes that the engine spawned
  survived the stop, held GPU memory, and competed with the next model load. Fixed by switching to
  `os.killpg(pid, signal.SIGTERM)` / `os.killpg(pid, signal.SIGKILL)` so the entire process group is
  terminated. Wrapped in `try/except ProcessLookupError` for the already-dead case.
- **Spurious "port already in use" error on quick restart** — after the inference process dies, the kernel
  may hold the listening socket briefly before releasing the port. `stop_server()` now polls
  `_port_in_use()` for up to 2 seconds after confirming process death, so `start_server()` gets a clean
  port on immediate restart.
- **External API engine launching a zombie `sleep(999999)` process** — `ExternalApiEngine.build_command()`
  returns a no-op sleep process as a placeholder because the proxy layer handles routing. But
  `start_server()` had no guard for engines with `install_method == "external"`, so any code path that
  called it directly (e.g. benchmark compare) would spawn that sleep process. Fixed: `start_server()` now
  returns `(True, "External API engine ready")` immediately for external engines without touching
  subprocesses.
- **Per-token layout thrashing during streaming** — `scrollToBottom()` was called on every SSE token delta
  chunk (`await scrollToBottom()` inside the streaming for-loop). Each call forces `await nextTick()` and a
  synchronous `el.scrollTop = el.scrollHeight` layout recalculation. At 50-100 tokens/second this fired
  50-100 forced layout operations per second, causing visible jank and slowing the JS event loop during
  generation. Fixed using a `requestAnimationFrame` throttle (`scheduleScrollToBottom()`): many per-token
  calls coalesce into one scroll per animation frame (~16ms). Synchronous `scrollToBottom(force=true)` is
  preserved for send/receive start/end/abort paths.
- **`ollama.py` upgrade script TOCTOU race on temp files** — `tempfile.mktemp()` returns a path without
  creating the file, leaving a race window where another process can claim the same name. Replaced with
  `tempfile.NamedTemporaryFile(delete=False)` (atomically claims the temp file path) and
  `tempfile.mkdtemp()` (atomically creates the temp directory).



### Fixed
- **"Engine lm-studio is not installed" crash at startup** — `LmStudioEngine.is_installed()` was checking
  whether the LM Studio daemon was running in addition to whether the binary existed. If LM Studio was
  installed but the app was closed (daemon stopped), `is_installed()` returned `False`, blocking any attempt
  to start the server and causing the `FileNotFoundError: 'lms'` crash. Fixed to check binary existence
  only; runtime state checks belong in `check_requirements()` which already handled this correctly.
- **Shell injection risk in `lmstudio.py` `build_command()`** — `lms_bin` was not shell-quoted in the
  `sh -c` template string. Both `lms_bin` and `launch_model` are now wrapped with `_shell_quote()`.
- **Double-response / repeating answers in Chat UI** — SSE streaming loop in `ChatView.vue` used `break`
  inside the inner `for (const line of lines)` loop on `[DONE]`. This only exited the for loop, not the
  outer `while (true)` loop. If the server sent any bytes after `[DONE]`, they were appended to the same
  message bubble as a second response. Fixed using a labeled outer loop (`outer: while ...`) so
  `break outer` on `[DONE]` exits completely and stops all further processing.
- **`ExternalApiEngine.install_command()` would try to pip-install a non-existent package** — the base
  class default inherits `pip install openai-compatible` which is not a real PyPI package. Added override
  that raises `NotImplementedError` with a clear message: configure API URL + key in Settings.
- **`RapidMlxEngine.upgrade_command()` returned `None`** — rapid-mlx is a pip-managed package but had
  no `upgrade_command()` override, so "Check for Updates" could never upgrade it. Fixed to return
  `pip install --upgrade rapid-mlx`.


### Fixed
- **Duplicate reply bug** — `_switch_and_stream()` was yielding `_sse_delta(notice)` + `_sse_delta("\n\n")`
  before the real inference stream. ChatView appends every `delta.content` to the same message bubble, so
  users saw "⏳ Switching model…\n\nActual response" concatenated together. The notice is now sent as an
  SSE comment (`": switching-to MODEL\n\n"`) which all SSE clients silently ignore, and the `"\n\n"` delta
  is removed entirely.
- **Pre-warm was always a no-op from `/server/load`** — `start_server()` is non-blocking; the immediate
  `_fire_warmup()` call after it always found `healthy = False` and returned early. Fixed by replacing
  the direct call with a background thread that polls until healthy (up to 120 s), then fires warmup.
  Warmup from `_hot_swap_if_needed()` already worked correctly and is unchanged.
- **3× `load_config()` disk reads per proxy request** — `proxy_chat()` called `sm.load_config()` twice
  at lines 1519 and 1524, and `_needs_hot_swap()` called it a third time internally. All three reads are
  now merged into one; `_needs_hot_swap()` accepts an optional pre-loaded `cfg` dict to avoid the
  redundant disk read.
- **Same double `load_config()` in `proxy_completions()`** — same fix applied.
- **`import json` inside streaming chunk generators** — the `json` module was imported inside the hot
  streaming loop in both `_switch_and_stream()` and the normal `_stream()` generator. Changed to use the
  top-level `_json` alias.
- **Non-streaming TTFT inflated** — `_record_request(start, dur, dur, ct, m)` was passing full request
  duration as the TTFT for non-streaming responses. Non-streaming has no "first byte" concept, so TTFT
  is now `None` for this path, keeping aggregate TTFT averages accurate.
- **`_sse_delta()` had inline `import json as _j`** — moved to top-level `_json` alias.
- **`_fire_warmup()` created a new `httpx.Client` on every call** — replaced with a module-level
  `_warmup_http_client` singleton via `_get_warmup_client()`.
- **`_get_httpx_client()` had no connection pool config** — added
  `Limits(max_connections=20, max_keepalive_connections=10)` and explicit 300 s / 10 s connect timeout
  to reduce TCP overhead for high-frequency proxy calls.



### Fixed
- **External API engine auto-start spawned useless sleep process** — When `engine_id = "openai-compatible"`
  was set and `startup_model_behavior=auto`, the CLI auto-start path called `start_server()` which spawns
  `python -c "import time; time.sleep(999999)"`. This process was alive but useless — `_external_api_mode`
  was never set, health checks failed, and the UI showed wrong status. Now `_start_or_mark_external()`
  calls `sm.set_server_healthy()` directly for external API engines — no local process, correct status.
- **Fallback priority wrong — experimental engines were chosen before stable ones** — `_BUILTINS` order
  put `AppleFMEngine` and `Ds4M5Engine` ahead of `VllmMlxEngine` and `RapidMlxEngine`. Auto-fallback
  iterates ENGINES in insertion order, so users with `apfel` installed could get `apple-fm` as the
  fallback engine instead of the bundled, stable `vllm-mlx`. New order: `vllm-mlx`, `rapid-mlx`,
  `ollama`, `lm-studio`, `llama-cpp`, `ds4-m5`, `openai-compatible`, `apple-fm`.
- **`openai-compatible` engine selected as auto-fallback** — `ExternalApiEngine.is_installed()` always
  returns `True` (it has no binary), so it could be picked as fallback for broken engines. It requires
  manual API key + base URL configuration and cannot meaningfully auto-start. `_try_engine_fallback()`
  now explicitly skips `openai-compatible` as a fallback candidate.
- **`LmStudioEngine._is_daemon_running()` called twice per `list_engines()` pass** — both `is_installed()`
  and `check_requirements()` ran `lms server status` (3s subprocess) in the same request. Added 5-second
  TTL cache at module level so the subprocess fires at most once per 5 seconds.
- **`LmStudioEngine.build_command()` sh PID mismatch** — When `launch_model` was set, the command used
  `sh -c "lms load X && lms server start"`. The stored PID pointed to `sh`, not `lms`, so SIGTERM killed
  the shell but left the `lms server start` process as an orphan. Fixed with `exec lms server start` as
  the final command so the shell is replaced by the lms process.
- **`AppleFMEngine.check_warnings()` always showed rate-limit advisory** — Even on machines without
  `apfel` installed, the rate-limit warning was unconditionally appended. Now gated on `is_installed()`.
- **`AppleFMEngine.check_requirements()` ran `brew tap` subprocess unnecessarily** — This added latency
  and spawned a subprocess just to silently ignore the result (`if result.returncode != 0: pass`). Removed.
- **`list_engines()` blocked on network calls every request** — `latest_version()` made PyPI/GitHub API
  calls synchronously for every engine on every `/engines` request. Added a 5-minute TTL cache so
  network calls happen at most once per engine per 5 minutes.
- **`_is_external_api_engine()` read config file on every proxy request** — Called `sm.load_config()`
  (disk I/O) on every `/v1/chat/completions` proxy. Added a 2-second TTL cache; cache is invalidated
  immediately when `engine_id` changes via `POST /config`.

### Added
- **17 new tests** in `tests/test_engine_management_fixes.py` covering all 7 fixes above.



### Fixed
- **LM Studio daemon check** — `LmStudioEngine.is_installed()` now verifies the LM Studio
  daemon is actually running (via `lms server status`), not just that the `lms` binary exists.
  Previously, having the `lms` binary installed but LM Studio app closed caused `lms server
  start` to exit immediately with "daemon is not running" — bypassing the pre-flight check and
  never triggering engine auto-fallback.
- **Auto-fallback for desktop-app engines** — startup engine fallback now also fires when the
  configured engine is a desktop-app type (`install_method="external"`, e.g. LM Studio) and the
  server exited immediately, not just when the binary is missing entirely.
- **`check_requirements()`** — LM Studio settings panel now shows "LM Studio app is not running.
  Open LM Studio, then try again." when the binary is present but the daemon is not active.

## v0.8.14 — 2026-05-27

### Fixed
- **LM Studio CLI detection** — `LmStudioEngine.is_installed()` now checks
  `/usr/local/bin/lms` and `~/.lmstudio/bin/lms` in addition to `$PATH`. The Homebrew-managed
  Python process does not inherit the user's shell `$PATH`, so machines that had LM Studio
  installed but reported "not found" will now be detected correctly.
- **Auto engine fallback** — on startup, if the configured engine is not installed, the app
  now automatically switches to the first available installed engine (priority order:
  vllm-mlx → rapid-mlx → ollama → llama-cpp → ds4) instead of warning and leaving the user
  stuck with a broken config.
- **Noisy "Operation failed" log messages** — two health-poll log lines in `mgmt_server.py`
  that printed full tracebacks during normal model-load wait cycles are now `debug`-level with
  a descriptive message. Two `quality_runner.py` exception messages now include the specific
  server URL / context instead of the generic "Operation failed".

## v0.8.13 — 2026-05-27

### Fixed
- **Engine pre-flight check** — `POST /start` no longer throws an unhandled ASGI 500 when the
  configured engine binary is not on PATH (e.g. `lms` for LM Studio, `llama-server` for
  llama.cpp). `start_server()` now calls `engine.is_installed()` before attempting to launch,
  returning `{"ok": false, "message": "Engine 'lm-studio' is not installed..."}` instead of
  crashing with `FileNotFoundError`. A secondary `try/except` around `subprocess.Popen` catches
  any race-condition where `is_installed()` passes but the binary disappears before exec.
  This fixes the crash reported on machines with a stale `engine_id: lm-studio` in
  `~/.vllm_mlx_ui/server_config.json` after upgrading from an older release.
- **Tests** — 7 new unit tests in `tests/test_server_manager_preflight.py` covering both the
  pre-flight path and the `Popen` safety net.

## v0.8.12 — 2026-05-27

### Added
- **OpenAI-Compatible API engine** (`openai-compatible`) — proxy any `/v1/chat/completions`
  request to a remote OpenAI-compatible provider (OpenAI, Groq, OpenRouter, Together AI,
  Anthropic proxy, self-hosted, etc.). No local inference process is needed. Configure the
  API base URL, API key, and comma-separated enabled model IDs in Settings → Engine. The
  dashboard proxy forwards requests transparently with correct `Authorization` headers.
  "Start" marks the engine as active immediately; "Stop" disconnects it. Auto-model-switch
  updates the config model without restarting any process. Full tests added:
  `tests/test_external_api_engine.py` (17 tests).

- **Apple Foundation Model engine** (`apple-fm`) — wraps the community `apfel` tool
  (`brew install Arthur-Ficial/apfel/apfel`) to expose Apple's on-device ~3B LLM (Apple
  Intelligence) via an OpenAI-compatible server. Requires macOS 26, Apple Silicon, and Apple
  Intelligence enabled in System Settings. Supports tool calling. Single fixed model — no
  model selection needed. Full tests added: `tests/test_apple_fm_engine.py` (36 tests).

## v0.8.11 — 2026-05-28

### Fixed
- **`chat_store.init_db` crash on every startup** — `sqlite3.executescript()` always issues an
  implicit `COMMIT` before running, which closed the `BEGIN` transaction we opened manually.
  The subsequent explicit `con.execute("COMMIT")` then raised `OperationalError: cannot commit
  — no transaction is active`, logged as a warning on every launch. Fixed by replacing
  `executescript(...)` with individual `con.execute()` calls so the explicit `BEGIN … COMMIT`
  block works correctly. Tables and indexes are created correctly either way, so no data
  migration is needed.
- **Engine card shows no active selection when selected engine not installed** — v0.8.10 changed
  the `active` CSS class condition to `selectedEngine === eng.id && eng.installed`, hiding the
  selection indicator when the configured engine fails its `is_installed()` check (e.g. binary
  not on PATH, or detection error). With no card highlighted the user could believe no engine
  is selected and accidentally click an uninstalled engine (e.g. lm-studio), writing that
  engine id to config and causing a `FileNotFoundError: lms` on next start. Restored the
  condition to `selectedEngine === eng.id` so the selected engine is always highlighted.
  Also removed the click guard (`eng.installed ? selectEngine : undefined`) so users can
  always click a card to select it, matching the behaviour before v0.8.10.

## v0.8.9 — 2026-05-27

### Fixed
- **Engine audit fixes** — 7 actionable findings resolved from ENGINE_AUDIT.md:
  - **rapid_mlx `uninstall_command()`** now tries both `rapid-mlx` (hyphen) and `rapid_mlx`
    (underscore) naming conventions, fixing silent uninstall failures when the engine was
    installed with the alternate name.
  - **ollama `resolve_launch_model()`** validates that the model tag isn't a filesystem path
    (common mistake when switching from path-based engines like llama.cpp or ds4-m5). If a
    path-like value is detected, it logs a warning and falls back to `config["model"]`.
  - **`get_model_presets()`** caches results per model_id for the session lifetime, eliminating
    redundant HF Hub API calls (config.json + generation_config.json fetched once, not on
    every UI model lookup).
  - **`get_hf_model_size_gb()`** now applies a 25 % KV cache / runtime overhead multiplier
    so `check_model_fit()` reports more realistic memory requirements (previously only
    summed weight files, understating RAM needs by 20–30 %).
  - **`BaseEngine.description`** type hint relaxed from `ClassVar[str]` to `str`, allowing
    ds4_m5.py's dynamic `@property`-based description (which depends on detected hardware)
    without type-checker confusion.
  - **`_read_server_state()`** stale PID handling — verified that the existing crash-log
    capture + `_try_adopt_server()` flow in `get_server_status()` already correctly handles
    stale PIDs. No change needed.
  - **`_which()` caching** — evaluated and deemed unnecessary: `shutil.which()` is
    sub-millisecond and caching could produce stale results after mid-session installs.

## v0.8.8 — 2026-05-26

### Fixed
- **Model switch from Serve view was broken (405 error)** — `load_model()` at `mgmt_server.py:744` was a complete, working implementation (stops running server, saves new model config, starts server with new model) but was missing its `@app.post("/server/load")` route decorator, so the route was never registered. Frontend calls to `POST /server/load` returned HTTP 405. Added the missing decorator.

## v0.8.7 — 2026-05-26

### Fixed
- **Software Updates still not showing new releases on old versions** — `_brew_latest_version()` now falls back to the GitHub releases API tag when `brew info --json` returns the same version as installed (indicating a stale cache that even `_refresh_tap()` didn't resolve). This eliminates the chicken-and-egg problem where the update checker couldn't detect its own update.

## v0.8.6 — 2026-05-26

### Fixed
- **Software Updates not detecting new releases** — `_brew_latest_version()` in `update_checker.py` called `brew info --json` without refreshing the local tap first, returning the stale cached version for hours until Homebrew's auto-update triggered. Added `_refresh_tap()` which does a fast-forward `git fetch` + `git pull --ff-only` on the `clickbrain/homebrew-vllm-mlx-ui` tap repository before reading the formula version.

## v0.8.5 — 2026-05-26

### Fixed
- **Engine install error handling** — `install_engine()` `_stream()` wrapped in try/except so subprocess spawn failures are streamed as install output instead of crashing with HTTP 500. Frontend now handles all non-2xx responses (`installEngine()`, `uninstallEngine()`) with user-visible error banners instead of silently reading JSON error bodies as plain text.
- **Rapid-MLX `is_installed()` PATH-independent detection** — Added `pip show rapid-mlx` fallback so installs are recognized even when the Python bin directory isn't on the process PATH.
- **ds4-m5 `_model_get_version()` stores HH SHA + LFS OID** — Model version now persists HF API metadata in `.model_version.json` and checks GGUF existence first, preventing stale version files from reporting a version when no model is installed.

### Added
- **Auto model weight upgrades** — After "Install Updates & Restart", the system re-downloads GGUF files for engines with model updates available. `refresh_model_version()` updates the stored SHA/OID after a successful weight upgrade.

## v0.8.4 — 2026-05-25

### Added
- **Model family scoring system** — Three-tier resolution pipeline (curated table → base_model tag → prefix heuristic) that maps every HF model to a canonical family with release date, architecture type, and benchmark scores. `model_families.json` curates ~80 families. Fixes the root cause of re-upload wins: Outlier-Ai Qwen2.5-Coder-32B re-upload (April 2026) correctly resolves to the Qwen2.5-Coder family (September 2024), losing "Best for Code" to genuinely newer models.
- **Qwen3-Coder-Next support** — Added to curated table (Feb 2026, 80B MoE, 3B active). Unlisted variants (e.g. `qwen3-coder-ultra`) are caught by a new prefix-heuristic fallback: normalized model names that share ≥60% of their characters with a known family key inherit that family's release date and scores. This handles future model variants without requiring a table update.
- **Max-age filter granularity** — Settings now offers: 2 weeks, 1, 2, 3, 4, 5, 6, 12, 18 months, or Any Age (replaced the old 6/12/18/24/36 month set).

### Changed
- **Scoring weights** — popularity signal removed, benchmark increased from 30% → 35%, recency reduced from 25% → 20%. Final weights: name/tag affinity 35%, benchmark 35%, recency 20%, utilization 10%.
- **Recency uses family release date** — Derivatives (fine-tunes, quants, re-uploads) use their base model family's release date for recency calculation, not the HF repo creation date. Originals without a base_model tag keep their own createdAt. This prevents re-upload timestamp gaming.
- **Benchmark scores merge family + leaderboard data** — Family data scores are preferred when non-null (always available for known families). The leaderboard cache acts as a supplement, not the primary source.
- **Max-age filter options** — replaced 6/12/18/24/36 months with 2wk/1mo/2mo/3mo/4mo/5mo/6mo/12mo/18mo/Any Age.

### Fixed
- **HF search now uses `full=true`** — Returns `cardData.base_model` and `config` in the initial response, eliminating the need for per-model round-trips to resolve family relationships. The family resolver batches all results in one pass.

### Added
- **Feature discovery after upgrades** — After "Install Updates & Restart", the system snapshots each engine's config schema before upgrading and diffs it against the post-upgrade schemas. Any new settings keys found (e.g. `mtp_draft`, `thinking`) are surfaced in a "New Features Discovered" banner in Settings. The banner persists across the process restart and can be dismissed with "Got it".
- **GET/DELETE `/updates/discovered-features` API** — Frontend fetches discovered features after server comes back from upgrade. DELETE clears them.
- **Engine ordering in Settings** — `list_engines()` sorts installed engines first, then not-installed; ds4-m5 sinks to bottom on non-M5 hardware (checked via `is_m5_or_newer()`).

### Fixed
- **Feature discovery survives process restart** — Discovered features are now persisted to `~/.vllm_mlx_ui/discovered_features.json` so they aren't lost when the management process kills itself during upgrade.

## v0.8.2 — 2026-05-23

### Fixed
- **Upgrade hardened — all pip operations use `sys.executable -m pip`** — `engine_upgrade_commands()` and `upgrade_command()` now use the running Python's pip (`sys.executable -m pip`) instead of a resolved `pip_bin` binary. This guarantees upgrades always target the same Python environment the management process runs in, eliminating the bug where brew cellar pip resolved to the wrong venv and upgrades silently targeted a different environment.
- **`_resolve_pip_bin()` removed** — no longer needed; all pip operations go through `sys.executable -m pip`.
- **Phantom updates eliminated** — `_check_ui()` uses `_brew_latest_version()` (reads `brew info --json` formula version) on brew installs, matching what `brew upgrade` actually installs. `_check_vllm()` uses `_pypi_latest("vllm-mlx")` instead of `_github_latest_tag()`, matching the pip install source. No more "update available" when the install mechanism can't deliver.
- **`VllmMlxEngine.upgrade_command()` restored** — returns `[sys.executable, "-m", "pip", "install", "--upgrade", "vllm-mlx"]`, replacing the deleted `upgrade_command()` that was routing through `engine_upgrade_commands()` with a resolved pip binary.
- **SPA catch-all resilience** — if `index.html` is missing (stale process after brew upgrade pruned the old cellar), returns a friendly 503 message instead of a 500 Internal Server Error.
- **Homebrew formula updated in both repos** (`clickbrain/vllm-mlx-ui` and `clickbrain/homebrew-vllm-mlx-ui`).

## v0.8.1 — 2026-05-22

### Fixed
- **vllm-mlx engine now updates correctly** — Changed `install_method` from `"bundled"` to `"pip"` so the engine is included in the global upgrade flow and its `latest_version()` check works. Added `get_package_name()` override for correct PyPI package name. Added an "⬆ Update" button on the engine card when a newer version is available (clicking it runs `pip install --upgrade vllm-mlx`).

## v0.8.0 — 2026-06-12

### Added
- **Serve page — "Ready to Start" resume card** — When a model is configured but the server is stopped (the most common daily state), the Serve page now shows a contextual "Ready to Start" card displaying the configured model name and engine, with a prominent ▶ Start Server button. Previously the page showed only metric cards with dashes, giving no clear call-to-action for returning users. The resume card does not appear when there is no model configured (shows the discovery empty state instead) or when a server crash log is present (shows the crash banner instead).
- **Command palette enrichment (Cmd+K)** — The command palette now dynamically lists "Load [model]" commands for every downloaded model, allowing power users to switch models without navigating away. Also added: "Release Memory" server command, "Find Models" navigation shortcut, and context-aware server command labels that include the current model or engine name (e.g. "Start Server — Qwen3-14B-4bit").
- **Removed redundant engine badge from Live Metrics header** — "Engine: vllm-mlx" label in the metrics section header was redundant with both the running hero banner and the sidebar status row. Removed to reduce visual noise.


### Added
- **Per-model Trust Remote Code** — A "Trust code" toggle on the Serve page lets you enable `--trust-remote-code` for a specific model without affecting the global setting. Per-model overrides are stored in config and checked first; the global setting acts as fallback. The global setting description in Settings now explains it is a fallback with per-model overrides available on the Serve page.
- **vllm-mlx engine upgrade** — The vllm-mlx engine now provides an `upgrade_command()` that runs `pip install --upgrade vllm-mlx` when "Check for Updates" triggers a full upgrade.
- **Advisor contextual empty state** — The Advisor tab now shows a contextual message when the server is not running ("Start the inference server on the Serve page first"), when no models are selected, or when ready to run — instead of a single generic prompt.
- **Documentation** — New `docs/reference/model-scoring.md` documents the full Best Choice scoring algorithm (5 signals, weights, hard exclusion rules, badge reason format). `docs/dashboard/user-guide.md` rewritten to cover all v0.7.1–v0.7.9 features. `docs/index.md` Key Features list updated with all current capabilities. `docs/reference/models.md` recommended models updated to Qwen3 series; new Finding Models section with RAM fit table and use-case filter explanation.

## v0.7.8 — 2026-06-12

### Fixed
- **Sidebar status row truncation** — engine name was `max-width: 60px` causing immediate overflow. Reworked to a 2-line stacked layout: engine name on top (bold, full width), model short-name below (smaller, muted), status dot aligned to first line. Both fields now use `text-overflow: ellipsis` at full sidebar width.
- **Model Finder scoring used wrong date field** — `computeRecencyScore()` was reading `last_modified` (HF repo's last file modification date, which is touched by README edits, safety patches, and metadata changes) instead of `createdAt` (the actual model publish date). This caused 2-year-old models with a recent README update to score as freshly released. Now uses `created_at` (from HF `createdAt`) as the primary recency signal. Model cards now display "Published: &lt;date&gt;" instead of "Updated: &lt;date&gt;" when the publish date is available.

## v0.7.7 — 2026-05-23

### Model Finder — Bug Fixes

- **Use-case pills now work** — clicking Chat / Code / Reasoning / Vision now sends a use-case-specific search query to HuggingFace (`instruct`, `code`, `thinking`, `vision`). Previously the Chat pill sent an empty string, making results identical to the initial load and appearing broken
- **Search input stays in sync** — when a use-case pill is clicked, the search box updates to reflect the active query so that subsequent sort or filter operations use the correct base query
- **Refresh indicator** — a subtle animated bar now appears while results are being refreshed (e.g. after clicking a use-case pill), so users get immediate visual feedback instead of a silent wait
- **"Unknown fit" gauge hidden for models without size data** — the RAM fit bar now only renders when the model size is actually known; previously `—` (a truthy string) caused every unsized model to show a gray "Unknown fit" bar
- **Backend sort fallback** — the HuggingFace sort parameter now falls back to `downloads` when an unrecognised sort value is passed, instead of `lastModified`

### Model Finder — Size Estimation Improvements

- Added `Mistral NeMo` (12B) to the known-sizes table — the name contains no explicit B count so size was previously unknown
- Added `Codestral Mamba` (7.3B) and `Codestral` (22B) — no B count in base model names
- Added `DeepSeek V3` (671B) — the V3 model ID contains a date stamp (`-0324`) not a B count; now correctly shows "Too large" on most hardware
- All distilled variants (e.g. `DeepSeek-R1-0528-7B`) still parse via regex and are unaffected by the above entries

## v0.7.6 — 2026-05-22

### Serve Page — Status Hero & Empty State
- **Running hero** — when a server is running, a prominent banner now appears below the page header showing the active model name, engine badge, Tok/s, uptime, and free RAM at a glance
- **Empty state** — when no model is configured, the Serve page now shows an inviting CTA with a "Browse Models →" link instead of a blank layout
- **Engine-aware endpoints** — the Connection Info endpoint table now adapts to the active engine: Embeddings only shown for engines that support it (`vllm-mlx`, `rapid-mlx`, `Ollama`); ds4 engine shows its additional `/v1/responses` and `/v1/messages` endpoints

### Model Finder — Polish
- **Fit size note** — model cards with a size estimate now show "Estimated — actual usage varies by model architecture" below the RAM gauge

### Navigation
- **Chat moved below Benchmarks** — nav order is now Serve → Models → Benchmarks → Chat → Settings, reflecting that Serve and Models are the core workflow; Chat is a secondary tool

### Model Finder — Bug Fixes
- **Fix: Use-case pills now trigger search** — Clicking a use-case pill (Chat / Code / Reasoning / Vision) now automatically re-fetches HuggingFace results sorted by downloads using use-case-specific query terms (`code`, `thinking`, `vision`). Previously, clicking a pill did nothing because `bestChoices` scored a stale pool of recently-updated obscure models.
- **Fix: Default sort changed from `last_modified` to `downloads`** — All 6 call sites (`doSearch`, `onFindTabActivated`, `searchCompany`, `applyFilters`, `loadMore`, initial `sortCol` ref) now default to `downloads` sort with `limit=100`. This ensures the pool is the most-popular 100 models rather than the most-recently-touched 50 obscure ones.
- **Fix: Date field corrected** — Model cards now show "Updated: <date>" (previously "Released: <date>"). The HuggingFace `last_modified` field is the date of the last weight push, not the original release date. Invalid/missing dates now display "Date unknown" (validated with `Number.isNaN`).
- **Fix: Missing sizes show `—`** — `sizeLabel` now returns `"—"` instead of `null` when no size is available, preventing blank size cells.
- **New: Best Choice elevated section** — Models scoring as Best Choice winners are surfaced in a highlighted section above regular results (deduplicated from the main list). Section is hidden while searching and only shown when winners exist.
- **UX: Company chips label** — "Browse:" renamed to "Quick Search:" for clarity.

### Navigation — Changes
- **Chat moved above Benchmarks** in the sidebar (P1.4 from UI audit).
- **Sidebar engine/model selects removed** — Replaced with a compact read-only status row (running dot + engine + model name). Clicking it navigates to the Serve page where full controls live. Engine/model switching logic is preserved in the Serve page and Chat page.
- **RAM gauge "models fit" hint** — Shows estimated max parameter count (`~NB param models fit`) below the available RAM gauge based on a 4-bit quantisation heuristic (~0.55 GB/billion params).
- **Fleet hint copy fixed** — Changed "Click ↺ to find servers on your network" → "Use the scan button above to find servers on your network."

### Chat — Auto-Start
- **Auto-start inference server on send** (P1.3) — When a message is sent but the server isn't running, the Chat view now automatically starts the server and waits up to 90 seconds for it to become healthy before sending. Shows "Starting server…" placeholder and a spinner. Previously showed a static error pointing users to the Serve page.

### Benchmarks — Tab Order
- **Advisor tab is now first** — Tab order changed from `[Live, Run Tests, History, Advisor]` to `[Advisor, Live, Run Tests, History]`. Default active tab is now Advisor.

### Other
- **Dashboard version in footer** — Sidebar footer version now reads from the `/poll` endpoint response (`dashboard_version`) instead of the hardcoded `v0.1.0`.
- **TourOverlay CSS token fix** — `var(--bg1)` (undefined token) replaced with `var(--bg-surface)`.
- **`server.ts`** — `dashboardVersion` ref added to poll cycle and exported from store.


- **Fix: Vision badge gate** — Non-vision text models can no longer win "Best for Vision". Added per-use-case minimum affinity gates: Vision requires affinity ≥ 0.80 (must match vision model patterns), Code ≥ 0.40, Reasoning ≥ 0.35, Chat ≥ 0.30. Previously, a well-benchmarked recent text model could win a Vision badge simply because no actual vision model was in the result set.
- **Fix: Too-large models excluded from Best Choice** — Models where `size_gb / total_ram ≥ 0.92` are now hard-disqualified from all Best Choice badges. Previously they could receive a badge despite the card simultaneously showing "Too large" fit status.
- **Fix: Scores fetched after sort/filter changes** — `fetchModelScores()` is now called after `applyFilters()`, `toggleSortDir()`, and `onSortChange()`. Previously, changing sort order or applying filters without re-fetching left new models with neutral (no-data) scores, degrading badge accuracy.
- **Fix: Compound model suffix normalization** — `normalize_model_id()` now loops suffix stripping until stable (max 6 passes). `Qwen2.5-7B-Instruct-MLX-4bit` → `qwen2.5-7b` (was incorrectly `qwen2.5-7b-instruct`). Affects any model with stacked suffixes like `-instruct-mlx-4bit` or `-chat-hf-4bit`.

## v0.7.3 — 2026-05-21

- **Feature: Multi-signal Best Choice scoring engine** — Replaced the old "most downloads that fits" heuristic with a full multi-signal scoring system. Each model is scored on five dimensions: (1) name/tag affinity to the use case (35%), (2) empirical benchmark quality from a curated database (30%), (3) recency — punishes stale models (25%), (4) hardware utilization — peaks at 55–72% RAM fill (10%), (5) popularity via log-scaled download count (10%). Score threshold 0.35 required for a badge.
- **Feature: Per-use-case Best Choice badges** — Four separate Best Choice winners computed simultaneously — one each for Chat, Code, Reasoning, and Vision. A single model can win multiple categories. Badges appear as colored stripes at the top of the winning model card with the label and a one-line reason string (size fit, quality score, age).
- **Feature: Use-case selector bar** — Always-visible bar above search results showing 💬 Chat / 💻 Code / 🧠 Reasoning / 🖼️ Vision pills. Click to focus badge competition on one category. Click again to deselect. "Max age" dropdown (default 18 months) provides a hard cutoff to exclude outdated models from winning.
- **Feature: ~80-family benchmark fallback database** — Covers Qwen3, Qwen2.5, Llama 3.x, Gemma 3, Mistral, DeepSeek R1/V3, Phi-4, Yi-1.5, Command-R, and more. Instantly available at startup with no network dependency. Optional HF Open LLM Leaderboard enrichment runs in background 20s after startup, refreshes every 24h.
- **Fix: Model name normalization** — `Meta-Llama-3-8B-Instruct-4bit` now correctly maps to the `llama-3-8b` benchmark family (was returning no-score due to `meta-` prefix not being stripped from the model filename component).
- **Fix: BenchmarkConfig orphan code** — Removed 4-line TypeScript fragment left over from the `BenchmarkConfig` interface insertion that caused an esbuild parse error (`Unexpected "}"` at models.ts:128).
- **UX: Improved model cards** — Capability tags (parameter count, quantization level, Instruct/Vision/Code/Thinking) now extracted from model ID and HF tags and shown as chips on every search result card.

## v0.7.2 — 2026-05-21

- **Perf: Hot-path imports moved to module level** — `psutil`, `get_engine`, and `ENGINES` no longer re-imported inside every health-check/build-command call in `server_manager.py`. rglob TTL cache added to `get_partial_download_bytes()` in `model_manager.py` (2s TTL, eliminates repetitive I/O from polling thread).
- **Perf: Shared httpx client** — `mgmt_server.py` now uses a single module-level `httpx.AsyncClient` instead of creating a new connection per proxy request (6 sites fixed). Blocking `open()`/`os.walk()` offloaded to `asyncio.to_thread()`.
- **Perf: ds4 description cached** — `Ds4M5Engine.description` property now caches the full description string (including fork selection, hardware detection, subprocess calls) per-instance instead of recomputing on every access.
- **Perf: Benchmark results retention** — `benchmark_runner.py` now prunes results older than 90 days on each save. `load_results()` made thread-safe via reentrant `RLock`.
- **Fix: B904 exception chaining** — 18 `raise HTTPException()` in `except` blocks in `mgmt_server.py` now use `from exc`/`from None` to prevent misleading tracebacks.
- **Fix: _ps.Process() stale alias** — `server_manager.py` health checks were referencing an undefined `_ps` name; fixed to `psutil.Process()`.
- **Refactor: SIM105 contextlib.suppress** — 13 `try/except: pass` blocks replaced with `contextlib.suppress` across 6 files (`app.py`, `chat_store.py`, `server_manager.py`, `ds4_m5.py`, `registry.py`, `model_manager.py`).
- **Refactor: Inner imports cleaned up** — `quality_runner.py`, `engines/ollama.py`, `model_manager.py` moved lazy imports to module level. Dead `token_count` variable removed from `quality_runner.py`.
- **Refactor: Engine UI ordering** — Engine list in Settings now sorts installed engines first, not-installed after. DeepSeek V4 Flash (ds4) sinks to bottom on non-M5 hardware.
- **Chore: Import ordering** — ruff I001 auto-fixed across 10+ dashboard files.

## v0.7.1 — 2026-05-21

- **Feature: Available RAM warning on model cards** — When a model fits the machine's total hardware RAM but cannot load right now due to insufficient free memory, a yellow inline warning appears on that card showing the exact amount of free memory and suggesting closing apps. The warning does not appear when the server is not running (no memory data available) or when a model is already flagged as too large for the hardware.
- **Feature: "Best Choice" recommendation badge** — One model card per search result page is highlighted with a green "✦ Best Choice" banner. The selection algorithm picks the most-downloaded model that (1) fits in total RAM with "perfect" or "good" rating, (2) is an Instruct/Chat model for typical usage, and (3) is not a tiny embed stub. Falls back to best-fit non-instruct model when no instruct models qualify. The banner subtitle dynamically reflects the actual reason: "Fits your hardware · popular · Instruct/Vision/Code/Reasoning".



- **Feature: Quality benchmark audit — 11 bugs found and fixed** — A comprehensive audit of the quality benchmark pipeline (`quality_runner.py`) discovered and fixed 11 bugs that were silently corrupting results:
  - **MATH runner crash**: `KeyError` on `q["problem"]` — dataset field is `"question"`. Every MATH benchmark run returned zero results.
  - **IFEval runner crash**: `KeyError` on `q["instruction"]` — dataset field is `"question"`. Every IFEval benchmark run returned zero results.
  - **IFEval score inflation**: `grade_ifeval()` returned `True` for any unrecognized constraint type (fail-open). Changed to fail-closed (`return False`) — 20+ constraint types were being auto-graded as correct.
  - **20 missing IFEval constraint handlers** implemented: `min_chars`, `contains_punctuation`, `line_count`, `min_emojis`, `sentence_count_exact`, `contains_word_and_max_chars`, `exact_word_count_with_word`, `comma_list`, `word_count_min`, `every_sentence_contains`, `min_word_length`, `line_word_count`, `sentences_start_different`, `three_sentences_second_question`, `word_count_and_position`, `json_structure`, `alliteration`, `dialogue`.
  - **2 ungradable IFEval questions removed** (`simple_sentences`, `rhymes_with`) — IFEval is now 38 questions instead of 40.
  - **`json_structure` constraint had duplicate `type` key** in question data (`{"type": "json_structure", ..., "type": "dict"}`). Last duplicate silently overwrote the constraint type, causing all JSON-structure evaluations to parse incorrectly. Fixed to `expected_type`.
  - **`grade_mmlu()` regex missed lowercase A-D** — only matched uppercase. Added `re.IGNORECASE`.
  - **`_math_answer_match()` couldn't handle operator spacing variance** — `e-2` vs `e - 2` failed string comparison. Added operator space normalization via `re.sub(r"\s*([+\-*/=<>!])\s*", ...)`.
  - **`_stream_completion()` crashed on empty `choices` array** — SSE stream can emit usage-only chunks with `choices: []` before the final `[DONE]`. Changed to safe access: `(obj.get("choices") or [])` with guard.
  - **`_sentences()` consumed sentence delimiter** — `re.split(r"[.!?]", text)` removed the period, colon, or question mark from each sentence. Changed to `re.findall(r"[^.!?]+[.!?]", text)` which preserves punctuation.
  - **`hardware.fingerprint()` uncached** — Called 3 sequential `sysctl` subprocesses (5s timeout each) every time. Added `@functools.lru_cache(maxsize=1)`.
- **Feature: MATH benchmark suite** — 50 competition math problems from MATH dataset (`grade_math()` with boxed answer extraction and operator-spacing-normalized string/numeric fallback matching).
- **Feature: IFEval benchmark suite** — 38 verifiable instruction-following tasks with 26 constraint-type handlers. Fail-closed grading: unrecognized constraint types return `False` instead of being auto-counted as correct.
- **Feature: Bootstrap 95% confidence intervals** — Every quality suite result now includes `accuracy_ci_95` via `bootstrap_ci()` (1000 resamples). Displayed inline on benchmark history badges (±X%) and comparison table cells, with tooltip showing full range.
- **Feature: Hardware fingerprint on benchmark results** — chip model, generation, total RAM, OS version, Python version, MLX version, and dashboard version captured at run time and persisted with every benchmark history entry.
- **Feature: Capability tags on model search results** — HFSearchResult cards now display auto-detected capability badges: parameter count (7B, 70B), quantization level (4-bit, 8-bit), and content type (Instruct, Vision, Code, Thinking, Embed, Audio). Extracted from model name and HF tags.
- **Feature: Model search sort direction** — Model search now supports ascending/descending sort direction. Sort toggle button in the Find tab passes `direction` parameter to the server, which queries HF API with the correct `direction` param.
- **Feature: MATH and IFEval columns in benchmark comparison table** — The compare-history benchmark table now includes MATH and IFEval accuracy columns alongside GSM8K, MMLU, and HumanEval.
- **Fix: Model pagination** — `search_hf_models()` now correctly slices from `offset` instead of always from 0. Fetch limit increased from 100 to 500 to support deeper pagination. `has_more` detection now checks `len(results) > offset + limit` instead of `len(results) > len(sliced)`.
- **Fix: Fit level uses total RAM** — `computeFitLevel()` now uses the machine's total unified memory (hardware spec) instead of currently available RAM. Fit classification is now stable across runs regardless of memory pressure. Default search page size increased from 25 to 50.
- **Fix: Thinking tokens stripped before grading** — All quality benchmark suites now strip `[... thinking ...]` / `<think>...</think>` blocks from model output before grading, preventing reasoning tokens from contaminating answer extraction.
- **Quality: 118 unit tests** — Comprehensive test coverage for all grading functions (`grade_gsm8k`, `grade_mmlu`, `grade_math`, `grade_humaneval`, `grade_ifeval`), streaming, sentence splitting, thinking removal, bootstrap CI, MMLU message construction, and question data integrity (every question has required keys, IFEval has no duplicate types, all constraint types have handlers).
- **Quality: Ruff clean** — Import ordering fixed (`E402`), ambiguous variable names renamed (`E741`), unused import removed.
- **UX: Hardware context panel in benchmark run detail** — The Run Detail section now shows hardware context (chip, RAM, macOS version, MLX version) for every benchmark run, making cross-machine comparisons transparent.

## v0.6.29 — 2026-05-20

- **Fix: Chat history was being wiped on reload** — Critical route ordering bug: `GET /chats` and `GET /chats/{id}` were registered AFTER the SPA catch-all (`/{full_path:path}`), so FastAPI returned `index.html` for all chat API requests. `JSON.parse(html)` silently threw SyntaxError and the frontend fell back to empty state. All 6 `/chats` endpoints are now registered before the catch-all.
- **Fix: Cannot navigate to non-Serve tabs from Chat page** — `ModelsView.vue` was missing `defineOptions({ name: 'ModelsView' })`, causing a KeepAlive component name mismatch that blocked tab navigation when Chat was active. All KeepAlive-included views now have explicit component names.
- **Fix: Engine/Model selectors inconsistent between Chat and other pages** — Chat header now uses the same `model-picker-wrap` + `model-picker-label` + `model-select` CSS pattern as the Serve page, with Engine listed first then Model everywhere (Chat, Serve, sidebar all consistent).

## v0.6.28 — 2026-05-20

- **Feature: Chat history is now persisted server-side** — Chat conversations are saved to a SQLite database (`~/.vllm_mlx_ui/chats.db`). History survives browser data clears, private-mode sessions, Safari eviction, and app upgrades. Previously all history was stored only in `localStorage` and could be silently wiped.
- **Feature: Active session auto-saved as draft** — After every completed response (including stopped streams), the current conversation is saved as a server-side draft. If `localStorage` is empty when you return (e.g., after a browser restart), the active session is automatically restored from the draft.
- **Feature: Saved chats lazy-load from server** — The saved chat list loads summaries from the server on mount and merges with any local-only entries. Full message content is fetched on demand when you click a saved chat (avoiding unnecessary data transfer for long chats).
- **Feature: Delete syncs to server** — Deleting a saved chat from the sidebar now removes it from the server database as well as `localStorage`.

## v0.6.27 — 2026-05-20

- **Fix: Optimal button now works for all engines and models** — Previously the Optimal button defaulted to 2048 max output tokens for any model that isn't on HuggingFace (ds4/DeepSeek GGUF, Ollama, local models), because the HF metadata fetch failed silently and the fallback ignored the model ID string. Now the model family (deepseek, qwen3, llama, etc.) is inferred directly from the model_id string, so `ds4:deepseek-v4-flash` correctly resolves to the DeepSeek family even when offline.
- **Fix: Optimal button accounts for reasoning models** — DeepSeek and Qwen3 generate `<think>...</think>` tokens that count against max_tokens before the actual answer begins. A complex coding question can consume 10,000+ thinking tokens. The Optimal button now sets max output tokens to 16,384 for reasoning models (chat/code) and 32,768 for analysis mode, instead of the previous 2,048.
- **Fix: Optimal button uses machine RAM** — Token recommendations are now tiered by available memory: <16 GB → capped at 4,096; <32 GB → capped at 8,192; ≥32 GB → full caps. Prevents context pressure degrading generation quality on smaller machines.
- **Fix: Optimal button respects server ceiling** — Recommended max output tokens never exceed the server's configured `max_tokens` limit.
- **Fix: Default max output tokens raised** — The default for new model sessions was 2,048; raised to 8,192 to avoid truncating responses from modern models.
- **UX: Parameters panel label clarified** — "Max tokens" renamed to "Max output tokens" with a tooltip explaining the difference between output tokens and the model's context window, and noting that reasoning models need 16K+.
- **UX: Optimal button shows what was applied** — A 4-second info banner appears after clicking Optimal showing the model family, machine RAM, temperature, and max_tokens that were set.

## v0.6.26 — 2026-05-20

- **Fix: Selecting a DeepSeek model now auto-switches engine** — on the Serve page, picking a model that belongs to a specific engine (e.g. the ds4 GGUF discovered by the ds4-m5 engine) now automatically switches the Engine dropdown to that engine and shows the "Apply & Restart" button. Previously the engine stayed unchanged and the model couldn't load. The `Model` interface now carries `engine` and `source` fields so the frontend can act on engine-ownership metadata returned by the backend.

## v0.6.25 — 2026-05-19

- **Fix: Settings page text contrast** — engine card description text was using `--tx-muted` (`#636366`, dark grey) which was hard to read on dark backgrounds. Switched to `--tx-secondary` (`#AEAEB2`). Warning list items changed from pale amber `#fcd34d` to `--tx-primary` (white) so the text is readable; the amber border/background still communicates the warning state. Both warning title and list items bumped from 12px to 13px.

## v0.6.24 — 2026-05-19

- **Fix: Blank page on load (critical)** — `useMachinesStore` called `watch(activeMachine, ..., { immediate: true })` before `const activeMachine = computed(...)` was declared. JavaScript's temporal dead zone (TDZ) caused a `ReferenceError: Cannot access 'activeMachine' before initialization` at app startup, preventing Vue from mounting. Moved the computed declaration above the watch. This bug has been present since Phase 5 was released.

## v0.6.23 — 2026-05-19

- **Fix: Blank page after in-app upgrade** — The browser was caching the old `index.html` (with old asset hash) after an upgrade. The new JS bundle has a different content-hash filename, so the stale HTML pointed to a file that no longer existed, producing a blank white page. Fixed two ways: (1) the server now sends `Cache-Control: no-store` on every `index.html` response so browsers never cache it; (2) the post-upgrade reload now navigates to `/` with `window.location.href` instead of `window.location.reload()` to guarantee a fresh HTTP request for the HTML.

## v0.6.22 — 2026-05-19

- **Fix: Settings form validation** — the Add Machine form now validates IPv4 address format (per-octet 0–255 range check), hostname format (RFC-compliant), port range (1–65535), and duplicate detection (blocks adding a host:port already in the fleet). The port input also enforces `min=1 max=65535` at the HTML level. Clear inline error messages are shown for every failure condition.
- **Fix: Background thread cleanup on shutdown** — benchmark and engine-comparison threads are now tracked by reference at module level. The FastAPI shutdown handler signals their stop events and joins them (3 s timeout each) so in-flight benchmark runs flush results cleanly instead of being killed mid-run.
- **Fix: `brew doctor` warning** — removed a stale v0.5.5 formula file that had been left at the root of the Homebrew tap repo. Homebrew expects formulas exclusively inside `Formula/`; the orphaned root copy was causing a spurious warning.
- **Fix: `release.sh` now creates GitHub Releases** — every tag push now calls `gh release create --generate-notes` so GitHub Releases stay in sync with git tags automatically.
- **Docs: README rewritten for Vue 3 / FastAPI architecture** — removed all Streamlit references, corrected port to 8502, documented all 6 built-in engines, current features (command palette, HTML preview, multi-machine fleet, virtual scroll, benchmark comparison), and updated file layout.
- **Docs: CHANGELOG backfilled for v0.6.9–v0.6.21** — release notes were missing for 9 versions; all entries now documented with technical detail.

## v0.6.21 — 2026-05-19

- **Engine system requirements checking** — `BaseEngine` gains `check_requirements()` and `check_warnings()` abstract methods. Engines can now report unmet hardware/OS requirements (errors) and advisory conditions (e.g. low available RAM, warnings). The Settings engine card shows a red error panel and hides the Install button when requirements are not met; a yellow advisory panel appears for warnings that don't block install.
- **ds4 engine rewrite: antirez/audreyt fork auto-selection** — `Ds4M5Engine` now auto-selects the correct upstream fork based on chip generation: M5 and newer use `audreyt/ds4` (Metal Tensor 4 optimised), M1–M4 use `antirez/ds4` (original, authoritative). `_detect_installed_fork()` reads the git remote to identify what is already installed. `upgrade_command()` includes a migration path for users on the legacy `Swival/ds4-m5` fork — clones correct fork and re-uses the existing GGUF directory (no 87 GB re-download).
- **ds4 requirements checks** — ds4 `check_requirements()` verifies macOS (not Linux/Windows), Apple Silicon (not Intel), and minimum 24 GB unified memory. `check_warnings()` warns when current free memory is below the recommended minimum for the selected quantization.
- **`_chip_generation()` / `is_m5_or_newer()`** — future-proof chip detection handles M6, M7, etc. without hardcoded version ceilings.
- **Engine registry: `requirements_errors` / `requirements_warnings` fields** — `list_engines()` now includes these in every engine dict so the UI can render them without an extra API call.

## v0.6.19 — 2026-05-19

- **Fix: ds4 install path** — resolved edge case where `_ds4_dir()` returned the legacy `~/.local/share/ds4-m5` path on machines that had never installed ds4, causing the install command to target the wrong directory. Now consistently returns `~/.local/share/ds4` for fresh installs with legacy fallback only when the old directory actually exists on disk.

## v0.6.18 — 2026-05-18

- **ds4: Metal Tensor 4 acceleration (`--mt auto`)** — `build_command()` now probes the ds4 binary for `--mt` flag support (via `flag_probe`) and adds `--mt auto` when present. Provides ~1.86× prefill speedup on M5 Max hardware. Falls back gracefully on older chips that don't support the flag.
- **ds4: Reproducible output toggle** — new `reproducible` boolean setting (default `true`) in the ds4 engine config. When enabled, sets `DS4_REPRODUCIBLE=1` in the subprocess environment, which injects seed 42 and stable tool-call IDs so every run with the same prompt produces the same output. Recommended for auditability; can be disabled for varied responses.
- **Fix: chat markdown renderer improvements** — `MarkdownMessage.vue` code block rendering fixes for edge cases with nested backtick strings and language-detection accuracy.

## v0.6.17 — 2026-05-18

- **Fix: remote machine API routing** — replaced the hardcoded `BASE = import.meta.env.DEV ? '/api' : ''` constant in `api/client.ts` with a dynamic `getBase()` / `setApiBase()` function pair. `machines.ts` now watches the active machine and calls `setApiBase()` immediately when the selection changes (including on startup via `immediate: true`). This fixes all API calls (chat completions, preset loading, docs, settings saves) failing to route to the correct remote machine after switching.

## v0.6.16 — 2026-05-18

- **Chat: live HTML preview** — code blocks with `language-html` or `language-htm` now show a **Preview** toggle button after streaming completes. Clicking it renders the HTML in a sandboxed `<iframe>` directly below the code block with size presets (Mobile / Tablet / Desktop / Full) and an open-in-new-tab button. The preview is never shown while streaming to avoid partial-render flicker.

## v0.6.15 — 2026-05-17

- **Runtime flag capability probing (`engines/flag_probe.py`)** — new module that runs `<binary> --help` once per session and caches the flags found. `build_command()` in all engine adapters now calls `flag_probe.add_if_supported()` before adding optional flags, so the dashboard never passes flags that the installed binary version doesn't support. Probe failures (binary not installed, timeout) fall back to optimistic behaviour for backward compatibility.
- **vllm-mlx, rapid-mlx, llama.cpp engine adapters updated** — all three use `flag_probe` to guard optional flags (e.g. `--api-key`, `--continuous-batching`, `--kv-cache-type`) that vary across binary versions.
- **New management endpoint** — `GET /engines/<id>/flags` returns the probed flag set for a given engine binary, useful for debugging compatibility issues.

## v0.6.14 — 2026-05-16

- **Fix: ds4 engine description rendering** — `SettingsView.vue` engine card description now uses `white-space: pre-line` so multi-line hardware requirement tables in the ds4 description display correctly instead of collapsing to a single line.
- **Fix: ds4 engine config cleanup** — removed stale `kv_disk_dir` and `kv_disk_size` config schema fields that referenced a non-existent ds4 flag, preventing spurious `--kv-disk-dir` arguments from being passed on launch.

## v0.6.13 — 2026-05-16

- **Fix: ds4 `build_command()` cleanup** — removed `--chdir` workaround that was added for Metal shader path resolution; the flag does not exist in the ds4 binary and caused a launch failure. Metal shaders resolve correctly without it when the binary is invoked from its own directory via the engine adapter.

## v0.6.12 — 2026-05-15

- **ds4 engine: auto-select antirez/audreyt fork (initial implementation)** — `_select_fork()` chooses `audreyt/ds4` on M5+, `antirez/ds4` otherwise. `install_command()` clones the correct fork. `_ds4_dir()` normalised to `~/.local/share/ds4` with legacy fallback. `_MODEL_HF_REPO` corrected to `antirez/deepseek-v4-gguf`.
- **Fix: mgmt_server `set_config` deep-merge** — `POST /config` previously overwrote the entire config file with only the fields in the request body, losing all other settings. Now merges the incoming dict over the existing config before saving.

## v0.6.11 — 2026-05-15

- **Fix: ds4 `max_output_tokens` default** — raised from 65536 to 384000 per antirez/ds4 project recommendation for coding agent workloads. The previous default caused early truncation on long multi-turn conversations.
- **Fix: ds4 `_recommended_quant()` memory thresholds** — adjusted quant selection thresholds to match antirez's published recommendations: `q2-imatrix` for < 256 GB, `q4-imatrix` for ≥ 256 GB unified memory.

## v0.6.10 — 2026-05-15

- **ds4: Think Max mode context guard** — default context size raised to 393 216 tokens (384k). Added automatic `"thinking": {"type": "disabled"}` injection in `mgmt_server.py` when the ds4 engine is active and the server was started with `ctx_size < 393216`. The ds4 "high effort" thinking mode has a hardcoded ~1024-token budget; exhausting it on multi-turn conversations causes the model to return zero answer tokens. Think Max (no budget limit) requires `--ctx ≥ 393216`.
- **Fix: context size help text** — updated config schema description to document the 393k minimum for Think Max mode and the approximate memory cost (~7.5 GB for the context buffer).

## v0.6.9 — 2026-05-14

- **Fixed-model engine support in Serve page** — engines that manage their own model (e.g. ds4) now show a static read-only label instead of the model dropdown. `BaseEngine` gains a `fixed_model_display` property; when non-`None`, `ServeView.vue` renders the label and suppresses the model selector. Engine switching no longer propagates the current HF model ID to a fixed-model engine, preventing it from overwriting the engine's own model config.

## v0.6.8 — 2026-05-14

- **ds4-m5: model now auto-discovered after install** — `GET /models/cached` appends engine-discovered GGUF models tagged `source=engine`; `start_server()` auto-populates model from engine when empty; install endpoint auto-registers model in config after successful download.
- **ds4-m5: update checking tracks model weights separately** — `hf_model_latest()`, `model_update_available()`, `model_upgrade_command()` added; `check_updates()` creates independent `PackageInfo` for model weights alongside engine binary updates.
- **Fix: `urllib.request.urlopen` double-namespace in `ds4_m5.py`** — `import urllib.request as _urllib` followed by `_urllib.request.urlopen` caused `AttributeError` caught by bare `except`, making `latest_version()` and `hf_model_latest()` silently return `None`. Fixed to `_urllib.urlopen()`.
- **Tests:** 18 unit tests for `Ds4M5Engine` (`get_discovered_models`, `_model_get_version`, `hf_model_latest`, `model_update_available`, `model_upgrade_command`) and `BaseEngine.get_discovered_models` default.
- **Removed: upstream vLLM (NVIDIA) engine** — the `VllmMetalEngine` adapter has been deleted from the registry. The `vllm` pip package (v0.19.1) has been uninstalled. vLLM (Metal) is no longer available as an engine option. Use `vllm-mlx`, `rapid-mlx`, or another engine for Apple Silicon GPU inference.
- **Removed:** `[vllm]` optional dependencies from `pyproject.toml`.

## v0.6.7 — 2026-05-14

- Fix: **vLLM (Metal) no longer passes `--device mps`** — vLLM >= 0.18 removed the `--device` CLI flag. The engine now lets vLLM auto-detect the device (falls back to CPU on Apple Silicon). For GPU inference on Mac, use the vllm-mlx or Rapid-MLX engines.

## v0.6.6 — 2026-05-14

- Fix: **vLLM (Metal) engine crash on Apple Silicon** — `vllm-mlx` v0.3.0 registers a `MLXPlatform` plugin via entry points that conflicts with NVIDIA vLLM when both packages are installed. The `VllmMetalEngine` subprocess now sets `VLLM_PLUGINS=""` to prevent the MLX platform plugin from hijacking platform detection. Fixes `AttributeError: 'MLXPlatform' object has no attribute 'fp8_dtype'`.

## v0.3.80 — 2026-04-27

- Fix: **Benchmark tok/s now accurate for all models** — was dividing `completion_tokens` (total including buffered thinking) by `gen_time` (only the streaming window after first token), giving impossible numbers like 9700 tok/s on a 9B model; fixed to divide by total wall-clock time from request start, giving true effective throughput
- Feature: **"Enable thinking mode" toggle in Custom benchmark** — thinking is off by default (faster, accurate metrics); check the box to benchmark models with full reasoning enabled

## v0.3.79 — 2026-04-27

- Fix: **Custom and quality benchmarks now disable thinking mode** — added `enable_thinking: false` to all benchmark requests; thinking models (Qwen3, etc.) were spending 30-40s on internal reasoning before streaming any tokens, reporting impossible tok/s numbers and misleading TTFT values; with thinking disabled, models respond immediately with accurate timing metrics

## v0.3.78 — 2026-04-28

- Fix: **`brew upgrade vllm-mlx-ui` permanently fixed** — root cause identified: Homebrew 5.x defaults to a 24-hour auto-update throttle (`HOMEBREW_AUTO_UPDATE_SECS=86400`), meaning `brew upgrade` skips all tap git-fetches for up to 24 hours after any prior `brew` invocation; this is why the formula update in v0.3.77 (which was correct and immediate) still wasn't visible with `brew upgrade` alone; dashboard "Install Updates" already used `brew update && brew upgrade` (bypasses throttle); fix: added `export HOMEBREW_AUTO_UPDATE_SECS=300` to `~/.zshenv` (5-minute throttle); formula caveats now document the correct upgrade command and the env var recommendation

## v0.3.77 — 2026-04-27

- Fix: **`brew upgrade` now always delivers the latest version** — the GitHub Actions bot approach created an unavoidable 2-4 minute window after every release where the formula wasn't updated; if `brew upgrade` ran in that window it always showed the old version; root fix: `release.sh` now computes SHA256 and updates the formula itself (synchronously, ~10s after tag push), and the bot is permanently disabled so there is no more race condition; when `release.sh` exits, `brew upgrade` works immediately

## v0.3.76 — 2026-04-27

- Fix: **Custom benchmark "No response received" with Qwen3/thinking models** — models like Qwen3 stream output into `delta.reasoning_content` (thinking tokens) rather than `delta.content`; with only 512 max_tokens the thinking could consume the entire budget leaving no `content` tokens; fixed by accepting either field as valid output; also raised default max_tokens from 512 → 2048 and added a configurable max tokens selector (512 / 1024 / 2048 / 4096) in the custom benchmark UI

## v0.3.75 — 2026-04-27

- Fix: **Install Updates & Restart no longer fails to come back** — the new process was spawning and immediately trying to bind port 8502 while the old process still owned it, causing the new process to crash silently; fixed by spawning `vllm-mlx-ui` (full entry point) with a 4-second delay so the old process exits and releases the port first
- Fix: **Release script no longer drops formula updates** — removed the formula push from `release.sh` entirely; the GitHub Actions bot is now the sole owner of formula updates, with `git pull --rebase` added so it never fails on concurrent pushes

## v0.3.74 — 2026-04-27

- Fix: **Custom benchmark "list index out of range" crash** — when `stream_options: {include_usage: true}` is set, the server sends a final SSE chunk with `choices: []` (empty list); indexing into it caused `IndexError`; fixed in both `run_custom_benchmark` and `run_live_benchmark`
- Fix: **Run Benchmarks button greyed out when server not running** — custom/quality/combined modes manage the server lifecycle themselves (stop → load model → start); only speed mode actually requires a pre-running server; updated button disabled condition, banner message, and guard logic accordingly

## v0.3.73 — 2026-04-27

- Fix: **Custom benchmark "list index out of range"** — initial fix attempt (partial; replaced by v0.3.74)

## v0.3.72 — 2026-04-27

- Release: Re-release of v0.3.71 with formula update and fix for missing `_TEST_PROMPTS` definition that would cause a `NameError` when running the speed benchmark

## v0.3.71 — 2026-04-27

- Feature: **Custom Prompts benchmark mode** — new "Custom Prompts" tab in Run Tests; enter your own prompts, run them against any cached model, and get a per-prompt results table showing TTFT, tok/s, and total response time; results saved to benchmark history with `benchmark_type: custom`

## v0.3.70 — 2026-04-27

- Fix: **Speed benchmark no longer reports impossible T/s values** (e.g. 6430 T/s for a 9B model) — root causes: (1) `gen_time` was measured from first content token to last SSE frame including non-content frames, so a buffered response gave near-zero gen_time → astronomical TPS; (2) token count used word-splitting (~0.75× real tokens). Fixed by tracking `last_content_time` (updated only on content chunks), using server-reported `completion_tokens` via `stream_options: {include_usage: true}`, falling back to `chars / 4` estimate, and skipping any run where all tokens arrived in under 100 ms (buffered stream — TPS is physically unmeasurable)

## v0.3.69 — 2026-04-28

- Fix: **Downloads no longer disappear when navigating away from Models/Find** — `ModelsView` is now kept alive by Vue's `KeepAlive` so the component (and its download queue UI) is never destroyed on tab navigation; added `onActivated` hook to refresh the model list and re-attach any polling that may have been interrupted; `pollDownloadStatus` no longer clears its interval on a transient network error so in-flight downloads survive brief connectivity hiccups

## v0.3.68 — 2026-04-28

- Fix: **GSM8K, MMLU, HumanEval now use real official benchmark data** — replaced placeholder/hand-written questions with authentic test sets: 25 questions from the OpenAI grade-school-math test split (official GSM8K), 25 questions from the Hendrycks MMLU test set spanning multiple subjects (abstract_algebra, mathematics, physics, biology, computer_science, history, sociology, philosophy), and 20 problems from the OpenAI HumanEval benchmark; scores are now comparable to published model leaderboards

## v0.3.67 — 2026-04-28

- Fix: **3-model benchmark (2/3 ran bug)** — `stop_server()` sent SIGKILL but didn't wait for the process to die before returning; `start_server()` now also retries the port-in-use check for up to 5s before failing; added stop_server warning to quality benchmark log so failures are visible
- Fix: **Speed (tok/s) and TTFT always showing `—` for quality/combined runs** — quality benchmark results were saved without `avg_tps`/`avg_ttft_ms` flat fields and `overall_speed`; fixed backend to include all three; also updated frontend `parseTps`/`parseTtft` to read `overall_speed` so existing history records show speed metrics too

## v0.3.66 — 2026-04-27

- Fix: **Benchmark run persists when navigating away** — moved run state (`benchRunning`, `qualityPhase`, `qualityLines`, `qualityRunId`, etc.) into a singleton Pinia store (`benchmarkRun`); polling timers moved to module-level variables outside `setup()` so they survive component remount regardless of KeepAlive behaviour; reconnect logic on `onMounted` re-attaches poll if a run is active; `onUnmounted` no longer stops polls while a run is in progress
- Feature: **Pulsing dot on "Run Tests" tab** — visible from any sub-tab so the user always knows a benchmark is running
- Fix: Auto-switch to "Run Tests" tab on `onActivated` when a benchmark is running

## v0.3.65 — 2026-04-27

- Fix: **GSM8K/MMLU always returning `?`** — `max_tokens` was 512 for quality benchmarks; reasoning models (Qwen3, DeepSeek-R1) spend all 512 tokens on `<think>` blocks before the answer, so the server's reasoning parser stripped the thinking content and returned an empty string; raised to 4096 (GSM8K/MMLU) and 2048 (HumanEval); stream timeout raised from 90 s to 300 s
- Fix: **Defensive `<think>` stripping in graders** — added `_strip_thinking()` helper that removes `<think>…</think>` blocks before number/letter extraction; guards against servers with reasoning parsing disabled
- Fix: **Update Available pill wrapping** — changed last grid column from fixed `140px` to `auto` and added `white-space: nowrap` + reduced font-size to 11px so the chip never wraps

## v0.3.64 — 2026-04-27

- Feature: **Model search & filter in Benchmarks** — Run Tests and Advisor model selectors now include a live search box (filter by name), size range dropdown (All / < 4 GB / 4–8 GB / 8–16 GB / > 16 GB), quantization dropdown (dynamically populated from installed models), a result count, and All / None quick-select buttons; filters are shared between both tabs; quant level now shown in the model description row

## v0.3.63 — 2026-04-27

- Fix: **Commit ui_dist built assets** — the compiled Vue bundle was not committed after v0.3.60–v0.3.62 UI changes; dev/local installs (`pip install -e .`) serve directly from `vllm_mlx/dashboard/ui_dist/` and were showing the pre-Advisor stale build; ui_dist now contains the correct build (Advisor tab, Performance Settings, Run Tests, fleet auto-detect, font size increases)

## v0.3.62 — 2026-04-27

- Fix: **Multi-model benchmark false-ready detection** — after switching models the server was declared ready as soon as the process started, but the model may still be loading; now polls `GET /v1/models` (up to 120 s) and only proceeds when the inference port actually responds 200



- Fix: **Benchmark runs survive navigation** — BenchmarkView added to KeepAlive; polling timers keep running when navigating to other pages; Live tab polling pauses/resumes cleanly on deactivate/activate
- Fix: **Multi-model quality benchmarks** — `/quality-benchmark/run` now accepts `model_ids`; backend iterates over each selected model, switching the server between them and restoring the original model when done; all results saved to history
- Fix: **`/benchmark/status` endpoint restored** — missing `@app.get` decorator was causing the endpoint to never register (500 errors on status polls)



- Feature: **Benchmark Performance Settings** — collapsible "Performance Settings" section in the Run Tests config; toggle Continuous Batching, Paged KV Cache, KV Cache Quantization, GPU Memory %, and Prefill Step Size per benchmark run; if settings differ from current server config the server auto-restarts before the test runs
- Feature: **AI Advisor tab** — select a task type (Code, Math, Knowledge, Fast, General, Summarisation), choose models to evaluate, click Analyse; runs targeted quality + speed benchmarks and ranks models with a weighted score recommendation
- Feature: **Fleet Auto-Detect** — "Scan Network" button in Settings › Fleet scans the local /24 subnet for machines running vllm-mlx-ui; discovered machines can be added with one click (`GET /fleet/discover` backend endpoint)



- Fix: font size increase was not visible — 228 hard-coded pixel `font-size` values across all Vue components were bypassing the CSS token system; bumped each +2px programmatically; body base font also raised from `--text-sm` (15px) to `--text-base` (17px)



- Fix: after `brew upgrade`, the `/restart` and `/updates/install` endpoints now correctly resolve the **new** Python executable via the stable `/opt/homebrew/opt/vllm-mlx-ui` symlink instead of the deleted old Cellar path — fixes "button says restarting but nothing happens" after an upgrade

## v0.3.57 — 2026-04-27

- Chat: navigating to another tab no longer aborts an in-progress generation — conversation continues in the background (`KeepAlive` + `defineOptions({ name: 'ChatView' })`)
- Chat: returning to the Chat tab auto-scrolls to the latest message via `onActivated`
- Chat: each mode button (Chat, Code, Creative, Analysis, Precise) now has a descriptive tooltip explaining its temperature setting and what it's suited for
- Chat: Optimal button tooltip clarifies that it tunes temperature, top-p, repeat-penalty, and max-tokens for the selected mode + model

## v0.3.56 — 2026-04-27

- Docs: bundled full documentation into `vllm_mlx/dashboard/docs_dist/` so docs work in the Homebrew-installed version (fixes "404" error in Docs tab)
- Docs: Dashboard User Guide completely rewritten to reflect the current UI — covers all 6 sections (Chat, Models, Serve, Benchmarks, Settings, Docs), all new features including company chips, filter bar, trending scores, Run Tests tab, History compare, Settings improvements
- Docs: In-page section TOC panel — when viewing a doc with 2+ headings, a right-side panel shows all h2/h3 headings with scroll-spy highlighting of the current section
- Docs: Heading anchors — every h2/h3 heading has a `¶` link icon on hover; clicking copies the deep-link URL hash
- Docs: URL hash navigation — deep-linking to `#section-name` scrolls to that section after page load


- UI: Settings — GPU Memory Utilization now displays as a percentage (e.g. 90%) instead of a decimal
- UI: Settings — SSD KV Cache Directory has a Browse… button that opens a native macOS folder picker
- UI: Settings — Improved descriptions for Trust Remote Code (explains what it does and the risks), GPU Memory Utilization, KV Cache Quantization, Paged KV Cache, SSD KV Cache, Continuous Batching, Prometheus Metrics (with link), and Rerank Model (with link)
- Backend: `GET /browse-directory` endpoint opens native macOS folder dialog via AppleScript

## v0.3.54 — 2026-04-27

- UI: Models Find — company quick-search chips (Meta, Qwen, Google, Microsoft, Mistral, Apple, DeepSeek, MLX Community)
- UI: Models Find — filter bar: Fit level, Max size, Min downloads, Min likes
- UI: Models Find — "Hide Downloaded" now defaults to ON
- UI: Models Find — Trending column now shows real trendingScore data from HuggingFace
- UI: Models Find — column headers now align correctly with data rows
- UI: App-wide — base font size increased by 2pt across the whole type scale (xs: 13, sm: 15, base: 17, lg: 19, xl: 24)
- Backend: `search_hf_models` now returns `trending_score` from HuggingFace `trendingScore` field

## v0.3.53 — 2026-04-27

- UI: Benchmark tab renamed "Run Tests"; run button renamed "Run Benchmarks"
- UI: Run Tests — add optional run name field to label benchmark runs in history
- UI: Run Tests — Stop Run button to cancel in-flight benchmarks (sets stop flag on quality runner)
- UI: Run Tests — quality log shown inline in right column directly below the Run button
- UI: Run Tests — model list now shows `running` / `queued` / `loaded` states during a run
- Backend: `/quality-benchmark/stop/{run_id}` endpoint — signals the quality runner to stop between questions
- Backend: `run_quality_benchmark` accepts `stop_event: threading.Event` to support graceful stop
- Backend: `label` field saved with both speed and quality benchmark results
- UI: History — search/filter bar (by model name or label, type filter: All/Speed/Quality)
- UI: History — run labels displayed in history rows
- UI: History — Compare panel adds visual bar charts for Speed (tok/s) and Quality (overall %)
- UI: Live tab — chart range selector for Requests Over Time and GPU Memory charts (1h / 6h / 24h); defaults to 24h

## v0.3.52 — 2026-04-27

- Fix: Memory Used and Memory % now show consistent values — both now derived from `(total - available)` rather than psutil's `vm.used` which under-reports on macOS
- UI: Serve page — Live Metrics moved to top of page (immediately visible after server state)
- UI: Serve page — Base URL and Model ID quick-copy cards moved inside Connection Info section
- Fix: Release Memory tooltip was misleading ("Stop server…") — clarified that the server stays up; it only clears MLX cache and runs OS-level memory compaction

## v0.3.51 — 2026-04-27

- Fix: Benchmark quality runner was sending requests without `model` field → 422 errors on all quality/combined runs
- Fix: Cache Statistics now shows engine_cache data (hit rate, hits, misses, etc.) even when mlx_vlm soft-error is present; soft error shown as a footnote
- Fix: "Compare N runs" button in History now scrolls to the comparison panel
- Fix: In-app Docs now bundled with the installed package — no more 404 after `brew upgrade`
  - Formula now copies `docs/` → `vllm_mlx/dashboard/docs_dist/` during build
  - `pyproject.toml` package-data includes `docs_dist/**/*`

## v0.3.50 — 2026-04-26

- Fix: `AttributeError: module has no attribute '_detect_install_method'` crash in Software Updates endpoint (missing `def` line in `update_checker.py`)
- UI: Benchmark panel now two-column — models on left (step 1), tests on right (step 2); right side dims with prompt when no model selected; Run always disabled until a model is chosen


All notable changes to the dashboard UI are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Dashboard UI version is tracked separately from the core vllm-mlx version.

## [0.3.49] — 2026-04-27

### Changed
- Unified benchmark: quality runner now uses streaming for all questions
  - TTFT and tok/s captured per question at zero extra cost; log lines show TTFT inline
  - Results include `speed` per suite and `overall_speed` aggregate
- Benchmark tab: replaced Speed/Quality checkboxes with 3-way mode selector
  - **Speed + Quality** (default) — one pass captures accuracy + TTFT + tok/s
  - **Speed only** — dedicated synthetic benchmark for isolated throughput
  - **Quality only** — accuracy scores with speed shown as bonus stats
- Result card shows speed stats row (tok/s, TTFT, total tokens) below accuracy scores

## [0.3.48] — 2026-04-27

### Fixed
- Benchmark tab: restored model selector; was lost in v0.3.46 rewrite
  - Shows all cached models as checkboxes; defaults to currently-running model
  - Speed benchmark runs against all selected models (multi-model comparison)
  - "running" badge highlights the currently-active model

## [0.3.47] — 2026-04-27

### Fixed
- Quality benchmark silently failing: API client returns data directly (not `{ data: T }`);
  fixed `{ data }` destructuring in all three benchmark poll calls so quality runs
  actually start and results display correctly

## [0.3.46] — 2026-04-27

### Added
- **Quality benchmarks** — GSM8K (math), MMLU (knowledge), HumanEval (coding) run against
  the live inference server; 25/25/15 questions bundled inline, no downloads required
- **Unified Benchmark tab** — Speed + Quality suites selectable via checkboxes, single
  Run button; both run concurrently against the running server
- **History tab** (replaces Saved) — most-recent run highlighted, checkboxes for
  side-by-side comparison, per-run delete, speed + quality badges per row
- Quality results persisted to shared benchmark history (`~/.vllm_mlx_ui/benchmark_results.json`)
- Extended `BenchmarkHistoryEntry` with optional `benchmark_type`, `overall_score`, `suites`
- Removed separate Speed/Quality/Saved tabs — folded into Benchmark + History



### Added
- **`--auto-model-switch` flag** — when enabled, requests that specify a different model name
  automatically hot-swap the loaded model instead of returning a 404.
  - `_validate_model_name` replaced by async `_ensure_model_ready` in `server.py`
  - Uses `ResidencyManager.shutdown()` → `register_model()` → `ensure_loaded()` sequence
  - Concurrent switch requests serialized via `_model_switch_lock`
  - Dashboard `server_manager.py` passes `--auto-model-switch` to the server when
    `auto_model_switch: true` is set in config (already defaulted to `true`)
  - CLI flag `--auto-model-switch` added in `cli.py`

## [0.3.44] — 2026-04-27

### Fixed
- **Install Update never upgraded vllm-mlx / huggingface-hub when running from conda/dev**
  — server was running from `/opt/miniconda3` (non-homebrew), so `upgrade_command()` used
  the pip path which tried `git+github install && pip deps`. If the git install failed,
  the `&&` chain stopped and deps were never upgraded.
  Non-homebrew path now runs `pip install --upgrade vllm-mlx mlx-lm huggingface-hub`
  directly (no git install step). Homebrew path changed `&&` → `;` so pip dep upgrade
  runs even when `brew upgrade` exits 0 with "already up-to-date".

## [0.3.39] — 2026-04-26

### Fixed
- **vllm-mlx / huggingface-hub still not upgraded** — `upgrade_command()` only ran
  `brew upgrade vllm-mlx-ui`; the formula's pip install step won't upgrade already-satisfying
  packages. Now explicitly pip-upgrades `vllm-mlx`, `mlx-lm`, and `huggingface-hub` using
  the *running venv's own pip* (`sys.executable/../pip`) after the brew upgrade, so all
  packages update correctly regardless of formula version.

## [0.3.40] — 2026-04-26

### Fixed
- **Homebrew tap naming violation causing unreliable upgrades** — tap repo was `clickbrain/vllm-mlx-ui`
  (full app repo), which violated Homebrew convention. Taps must be named `homebrew-<name>`.
  Created dedicated lightweight tap repo `clickbrain/homebrew-vllm-mlx-ui` containing only
  the formula. `brew tap clickbrain/vllm-mlx-ui` now works without an explicit URL, and
  `brew update` reliably pulls the latest formula on every `brew upgrade`.
- **Added GitHub Actions auto-update workflow** — pushing a version tag to the app repo now
  automatically computes the sha256 and updates the formula in the tap repo, eliminating
  the manual formula-bump step that was causing stale tap versions.
- Updated README install instructions to use the new tap (no explicit URL needed).

## [0.3.41] — 2026-04-26

### Fixed
- **`post_install` fails with `PermissionError` on every upgrade** — `post_install` always
  tried to re-download the starter model even when it was already cached from a prior install.
  On upgrades, a running server holds a lock on the HuggingFace cache directory, causing
  `[Errno 1] Operation not permitted`. Now checks for
  `~/.cache/huggingface/hub/models--mlx-community--Llama-3.2-3B-Instruct-4bit` first and
  skips the download entirely if the model is present.

## [0.3.42] — 2026-04-26

### Added
- **Benchmark favorites** — save any benchmark run with a name using the new ☆ Save
  button in the results header. Saved runs persist in `localStorage` across sessions.
  The configure view shows a "Saved Benchmarks" panel listing all favorites with model
  names, average t/s, and the config used. Click any saved run to restore its results
  instantly. Each entry can be deleted individually.

## [0.3.43] — 2026-04-26

### Fixed
- **Update checker always showed vllm-mlx as outdated (false positive)** — A stale
  `vllm_mlx.egg-info` with `Name: vllm-mlx, Version: 0.2.8` was present in the project
  root from a prior editable install of the upstream engine. Python's `importlib.metadata`
  found this file (relative path) before the real `vllm_mlx-0.2.9.dist-info` in the
  brew venv, causing the update checker to always report 0.2.8 installed and offer an
  upgrade that could never change anything.
  - Deleted the stale `vllm_mlx.egg-info` from the project root.
  - Hardened `_installed_version()` to prefer `.dist-info` entries inside the running
    venv's site-packages over `.egg-info` files found via relative path resolution, so
    this class of false-positive cannot recur.

---

---

---

---

---

---

## [0.3.38] — 2026-04-26

### Fixed
- **vllm-mlx and huggingface-hub never actually upgraded** — the Homebrew formula's install
  block only ran `pip install --upgrade mlx-lm huggingface-hub`. `vllm-mlx` was installed
  only via `pip install .` (the formula package), which pip won't upgrade if the currently
  installed version already satisfies the declared version range. Added `vllm-mlx` to the
  explicit `--upgrade` line so all three key packages are upgraded on every `brew upgrade`.

---

## [0.3.37] — 2026-04-26

### Fixed
- **Version always showed `0.3.30`** — `importlib.metadata.version("vllm-mlx-ui")` silently
  failed in dev/conda environments (the running Python had no package metadata for
  vllm-mlx-ui), falling back to the stale hardcoded `"0.3.30"`. Replaced the try/except
  pattern with a direct hardcoded version string in `__init__.py`, kept in sync with
  `pyproject.toml` as part of our standard version bump process.

---

## [0.3.36] — 2026-04-26

### Fixed
- **Update flow broken — button stuck, no feedback, versions not updating** — multiple bugs:
  - `installing` ref never reset to `false` on success (button stuck in loading state forever)
  - No progress feedback during the ~35s brew upgrade + restart wait
  - `vllm-mlx-ui` update detection never fired for stable semver installs (only worked for
    `HEAD-<sha>` nightly builds; tarball installs like `v0.3.35` always showed "up to date")
  - Install method detection fell through to `pip` in dev/terminal mode because
    `shutil.which("vllm-mlx-ui")` returned nothing; now also checks `sys.prefix` and
    `HOMEBREW_PREFIX` env var
  - Update cache not invalidated after upgrade (versions showed stale data for up to 1 hour)
- **Update progress now visible**: frontend polls `/updates/install-status` every 2s and shows
  "Running brew upgrade…", "Server restarting…", "Done! Reloading…" phase messages
- **3-minute timeout**: if the server never comes back, a clear error message is shown instead
  of leaving the button stuck indefinitely

---

## [0.3.35] — 2026-04-26

### Fixed
- **Blank main panel on all pages** — `CollapsibleSection.vue` and `ConfirmModal.vue` were
  missing all import statements and `defineProps` declarations (lost during the doc pass).
  `CollapsibleSection` used `ref`, `onMounted`, and `props` without importing them.
  `ConfirmModal` referenced `title`, `message`, `confirmLabel`, `destructive` props without
  declaring them. These components are used on every view, causing runtime crashes.
- Added Python-based import scanner to catch this class of issue going forward.

---



### Fixed
- **Blank page on all routes** — `AppTopbar.vue` was missing all import statements
  (`ref`, `computed`, `useRoute`, `useRouter`, `useUpdatesStore`). These were lost
  during the documentation pass. Caused a `ReferenceError: Can't find variable: useRoute`
  crash in the setup function, blanking every page.

---



### Added
- **Multimodal image attachment in Chat** — when an MLLM (vision) model is loaded, an
  image attachment button appears in the chat input. Supports file picker and drag-and-drop.
  Images are sent in OpenAI vision content-array format. Attached images display as
  thumbnails in user message bubbles.
- **`isMultimodal` store computed** — `server.ts` now exposes `isMultimodal` derived from
  the `/health` endpoint's `model_type` field (`"mllm"` vs `"llm"`).

### Fixed
- **Build failure: missing `Props` interfaces** — `AppButton`, `AppBadge`, and `StatusPill`
  had their TypeScript `Props` interface declarations accidentally removed during the
  documentation pass, causing a complete Vue build failure. Restored all three.
- **Syntax error in `server_manager.py`** — `global _last_crash_log` declaration was
  inside a `with` block after first use of the variable, causing a Python `SyntaxError`.
  Moved declaration to the top of `get_server_status()`.
- **README: stale `pip install` upgrade instructions** — replaced with `brew upgrade` and
  re-running the appropriate install script. Homebrew is the canonical install method.

### Docs
- Comprehensive JSDoc / Vue comment / test-docstring pass across all UI source files.
- All test functions in `test_anthropic_adapter.py`, `test_api_utils.py`,
  `test_paged_cache.py` now have docstrings (120 added).

---

## [UI 1.6.0] — 2026-04-24

### Fixed
- **HF-wide model search returns no results** — replaced `HfApi().list_models()` (breaks
  silently when `huggingface_hub` version changes) with a direct call to the stable
  HuggingFace REST API (`https://huggingface.co/api/models`). Sorted by downloads, full
  tag list preserved, `is_mlx` auto-detected from tags.
- **GPU memory utilisation shows 1% instead of 90%** — the Server configuration slider
  used `value=0.90` with `format="%.0f%%"`: `%.0f` on `0.90` rounds to `"1"`. Fixed by
  switching to an integer range (50–99) with `format="%d%%"`. The stored config value
  is still a float (divided by 100 on save).
- **Thunderbolt Bridge interface labelled "virtual network"** — `bridge0` (macOS
  Thunderbolt Bridge) is now explicitly detected and labelled "Thunderbolt Bridge"
  in the network connections list. Generic `bridge*` interfaces retain the "virtual
  network" label.
- **Download by ID: no duplicate check** — added a pre-download warning when the
  requested model ID already exists in the local library (`get_cached_models()` check).
- **Download by ID: no progress feedback** — added a "Scroll up to see download progress
  in the queue panel" info message after a download is enqueued.

---

## [UI 1.5.0] — 2026-04-24

### Fixed
- **Model fit indicators used wrong RAM total on remote connections** — `check_model_fit()`
  was called once per search result row, each call making an HTTP request to the remote
  machine to get total RAM. With 50 results this caused request timeouts and silently
  fell back to the local machine's RAM. Fixed by calling `get_total_ram_gb()` once
  before the search loop and passing `total_gb=` to every `check_model_fit()` call.
- **Remote download queue panel showed no progress** — the download-tracking panel now
  polls `GET /models/download_status/{id}` on the remote Studio machine and displays
  live status. Both the Search tab and Download by ID tab write to
  `session_state["_remote_dl_tracking"]`, so the panel reflects all in-flight downloads.
  Auto-refresh triggers whenever any local or remote download is active.


### Fixed
- **install.sh: critical bug** — installer was downloading vllm-mlx from
  `waybarrios/vllm-mlx` (upstream without dashboard code), causing
  `ModuleNotFoundError: No module named 'vllm_mlx.dashboard'` on first launch.
  Now installs from `clickbrain/vllm-mlx-ui` which includes the dashboard.
- **install.sh: launch shortcut robustness** — the generated `Start vllm-mlx.command`
  now sources conda `profile.d` scripts before launching, and resolves the exact
  Python bin directory at install time. This fixes "command not found: vllm-mlx-ui"
  errors when double-clicking outside a conda terminal session.
- **install.sh: completion message** — corrected "Playground" → "Chat".

### Added
- **uninstall.sh** — Interactive uninstaller. Removes the pip package (or Homebrew
  formula), Desktop shortcut, and `~/.vllm_mlx_ui/` state directory. Offers to
  remove only mlx-community models, all HF cache models, or neither — with size
  information shown before each prompt.
- **Homebrew formula** (`Formula/vllm-mlx-ui.rb`) — Install via:
  ```
  brew tap clickbrain/vllm-mlx-ui https://github.com/clickbrain/vllm-mlx-ui
  brew install --HEAD clickbrain/vllm-mlx-ui/vllm-mlx-ui
  ```
  The formula creates an isolated Python venv inside Homebrew's `libexec/` and
  symlinks all entry points (`vllm-mlx`, `vllm-mlx-ui`, etc.) into Homebrew's
  `bin/` so they are always on PATH without any conda activation.

---



### Added
- **Text/code file uploads in Chat** — A file uploader is now always visible on the
  Chat page, accepting `.txt`, `.py`, `.js`, `.ts`, `.md`, `.json`, `.yaml`, `.sh`,
  `.c`, `.cpp`, `.java`, `.rs`, `.go`, `.sql`, and many more extensions.  The file
  content is prepended to the user's message as a fenced code block (100 KB cap with
  a visible warning for large files).  Works for all models — not just vision models.
- **Chat history: per-chat ⭐ favourite toggle** — Each chat row in the sidebar now
  shows a star button.  Starred chats are pinned to the top of the chat list under a
  "Favourites" heading; unstarred chats appear below.  State is persisted in
  `chats.json`.
- **Chat history: per-chat ✕ delete button** — Every chat row now has an inline
  delete button.  Previously only the active chat could be deleted.
- **Gradio & extension info** in Settings page — explains how to launch the
  built-in `vllm-mlx-chat` Gradio UI and how to extend the Streamlit dashboard.

### Fixed
- Chat sidebar: duplicate indented delete code (orphaned from refactor) removed.
- `"starred"` key back-filled for existing chats on first load; no migration needed.

---

## [UI 1.3.0] — 2026-04-22

### Security
- **Auto model-switch proxy** now validates that the requested model is already
  cached on the server before swapping.  Uncached model IDs are silently ignored,
  preventing remote clients from triggering arbitrary downloads.
- **HuggingFace token** is now cleared from the process environment immediately
  after `download_model()` and `get_model_presets()` complete (`finally` block).
- New **🔒 Security** section in Settings page warns when servers are bound to
  `0.0.0.0` with no API keys configured.
- Added `docs/SECURITY.md` with full risk assessment and deployment guidance.

### Fixed
- `install-remote.sh`: corrected GitHub repo from `brad-sandbox/vllm-mlx-ui`
  to `clickbrain/vllm-mlx-ui` (primary URL was always 404-ing).
- Models library: excluded metadata-only stub entries (0.00 GB phantom models
  caused by `get_model_presets()` downloading `config.json` and creating a tiny
  HF cache entry).  Now requires ≥ 50 MB **and** at least one weight-file
  extension to appear in the library.

### Added
- **Most Recent** sort option on the Search mlx-community tab (sorts by
  `last_modified` date descending).
- `CHANGELOG.md` and `docs/SECURITY.md`.
- `__version__` added to `vllm_mlx/dashboard/__init__.py`.

### Changed
- `install.sh`: detects existing vllm-mlx installation and shows upgrade notice
  instead of silently reinstalling.
- `install.sh`: checks HF cache before downloading the starter model; skips
  download if already cached (idempotent re-runs).
- `install-remote.sh`: now installs `huggingface-hub` (required for model search
  and preset loading in the remote dashboard).

---

## [UI 1.2.0] — 2026-04-21

### Added
- **All-interface IP detection**: replaced single `gethostbyname()` with
  `_get_all_local_addresses()` that parses `ifconfig` output to return every
  IPv4 interface (Wi-Fi, Ethernet, Thunderbolt link-local, VPN) plus `.local`
  mDNS hostname.  Applied everywhere: Server page, after model switch, Settings
  network section, auto-switch proxy URLs.
- `_connection_info_block()` shared helper used consistently across all pages.
- iFrame embedding support via `.streamlit/config.toml` and FastAPI
  `X-Frame-Options: ALLOWALL` / `Content-Security-Policy: frame-ancestors *`
  headers.
- Apache 2.0 `LICENSE` file.
- `README_UI.md`: comprehensive feature documentation with 3-option install
  table and clone instructions.
- Public GitHub repository: `https://github.com/clickbrain/vllm-mlx-ui`.

### Changed
- Playground renamed to **Chat** throughout the UI.
- Fixed `NameError: name 'config' is not defined` on Models page.

---

## [UI 1.1.0] — 2026-04-20

### Added
- **Chat history** with named conversations (`~/.vllm_mlx_ui/chats.json`).
  Create, rename, delete chats; auto-title from first message.
- **Per-chat model selector**: each conversation can use a different model.
- **Auto model-switch proxy**: `POST /v1/chat/completions` on port 8502 detects
  when the client requests a different model and hot-swaps automatically.
- Management API (`mgmt_server.py`, port 8502) for full remote control:
  start/stop server, config, model downloads, benchmarks, logs, metrics.
- Remote-aware `server_manager` and `model_manager`: all operations route via
  HTTP to the management API when `remote_mgmt_url` is configured.
- `install-remote.sh`: lightweight installer for non-server machines.

### Fixed
- HuggingFace `list_models()` compatibility: runtime inspection of supported
  kwargs avoids errors on newer Hub versions that removed `direction` /
  `fetch_config`.

---

## [UI 1.0.0] — 2026-04-19

### Added
- Initial 6-page Streamlit dashboard:
  - **Overview**: live metrics, health banner, sparkline charts
  - **Server**: start/stop/restart, full configuration form with dropdowns
  - **Models**: library, mlx-community search (filter/sort), download by ID,
    one-click model switching with optimal preset loading
  - **Benchmarks**: run benchmarks, historical chart, export/delete
  - **Chat**: OpenAI-compatible chat UI with streaming
  - **Settings**: network access, remote server, auto model-switch
- `server_manager.py`: server process lifecycle, config persistence
- `model_manager.py`: HuggingFace Hub integration, preset loading
- `benchmark_runner.py`: benchmark execution and history
- `app.py`: entry point; starts Streamlit + management API thread
- `pyproject.toml`: `[ui]` optional extras, `vllm-mlx-ui` entry point
- `install.sh`: full Apple Silicon installer with Desktop shortcut
