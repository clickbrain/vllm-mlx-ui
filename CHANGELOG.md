# Changelog — vllm-mlx Dashboard UI

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
