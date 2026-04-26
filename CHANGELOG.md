# Changelog — vllm-mlx Dashboard UI

All notable changes to the dashboard UI are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Dashboard UI version is tracked separately from the core vllm-mlx version.

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
