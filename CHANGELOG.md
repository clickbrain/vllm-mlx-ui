# Changelog — vllm-mlx Dashboard UI
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
