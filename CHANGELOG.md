# Changelog — vllm-mlx Dashboard UI

All notable changes to the dashboard UI are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Dashboard UI version is tracked separately from the core vllm-mlx version.

---

## [UI 1.4.0] — 2026-04-22

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
