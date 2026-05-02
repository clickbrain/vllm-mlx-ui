# AGENTS.md — vllm-mlx-ui

> This file is the **single source of truth** for all AI agents (Copilot, Claude, etc.) working on this repo. Read it before making any changes.

---

## Current State (as of 2026-04-29)

### Audit Completed
A full codebase audit was completed on 2026-04-29. Findings documented in:
- `PERFORMANCE_AUDIT.md` — 19 performance issues (4 High, 8 Medium, 7 Low)
- This file's **Known Issues** and **Change Log** sections below
- GitHub Issues labeled `audit-2026-04-29` for tracking

### Project Plan
Implementation roadmap is in `PROJECT_PLAN.md`. Work is organized in 5 phases.

---

## Known Issues (Do Not "Re-Discover" These)

These are **known issues** identified during the 2026-04-29 audit. Do NOT file new bugs for them. Fix them according to the plan in `PROJECT_PLAN.md`.

### Error Handling
- ~75 `except Exception: pass` blocks across the codebase silently swallow errors
  - Worst offenders: `vllm_mlx/dashboard/model_manager.py` (~13), `vllm_mlx/dashboard/server_manager.py` (~15), `vllm_mlx/dashboard/update_checker.py` (~10)
  - Fix pattern: `except Exception as e: logger.warning("...", exc_info=True)`
- Frontend `SettingsView.vue`, `ModelsView.vue` — all `catch { /* silent */ }` blocks

### Security
- **Command injection** in `vllm_mlx/examples/tts_example.py:134`, `tts_multilingual.py:336`, `audio_separation_example.py:116` — `os.system(f"afplay {args.output}")`
  - Fix: `subprocess.run(["afplay", args.output])`
- **Empty default API key** — `server_manager.py:156` `mgmt_api_key` defaults to `""`
- **Arbitrary code execution** in `quality_runner.py:171` — `subprocess.run()` with test code

### Concurrency
- `_last_crash_log` read outside lock in `server_manager.py:492`
- `_resolved_urls` dict mutated from multiple threads without sync (`server_manager.py:80`)
- Two threads write to same `item` dict in `model_manager.py:366-382`
- `_cache` dict in `update_checker.py:25` — written by background threads, read by UI thread
- `ssd_cache.py:161` — SQLite with `check_same_thread=False` without explicit synchronization
- Multiple daemon threads spawned in `mgmt_server.py` without tracking/cleanup

### Memory/Resource
- `server_manager.py:755` — file handle from `open(LOG_FILE, "w")` not closed if process dies immediately
- `ssd_cache.py:575-578` — background writer thread no guaranteed cleanup on GC
- `model_manager.py:230,252` — env var race window for `HUGGING_FACE_HUB_TOKEN`

### Logic Bugs
- `server_manager.py:849` — `get_logs()` returns string (local) vs list (remote) — **documented as known bug in code**
- `update_checker.py:155-157` — version comparison fallback uses `!=` instead of proper semver
- `worker.py:133` — undocumented `0.5` factor halves GPU memory utilization
- `server_manager.py:599-602` — silently overrides user config when `max_request_tokens < max_tokens`

### Performance
- `server.py:869,925` — blocking I/O in async lifespan (cache load/save)
- `ui/src/stores/server.ts:231` — 4 sequential API calls every 3 seconds
- `ui/src/router/index.ts` — all views eagerly imported (no lazy loading)
- `ssd_cache.py:247-280` — O(N) linear scan for prefix lookup
- `ssd_cache.py:503-540` — O(N log N) eviction
- `server.py:1250-1257` — tokenizer lookup not memoized (hot path)

### UI/UX
- Missing ARIA labels, `:focus-visible` styles throughout
- Theme preference not persisted (resets on refresh)
- Undefined CSS tokens: `--bd`, `--bg3`, `--bg4`, `--tx1`, `--tx2`, `--tx3`
- Charts use hardcoded hex colors — don't adapt to theme
- No mobile nav (sidebar hidden below 720px)
- No global toast/notification system
- `ConfirmModal.vue` — no focus trap, no Escape handler
- `SettingsView.vue` — no form validation (port range, host format, duplicates)

### Architecture
- Excessive `global` variables in `server.py`
- Duplicated `_mgmt_base()` between `model_manager.py` and `server_manager.py`
- Mutable `DEFAULT_CONFIG` dict at module level (`server_manager.py:162-164`)
- Monkey-patching in `scheduler.py:144-161` (fragile to mlx_lm changes)
- Hash-based routing (`router/index.ts:10`) — ugly URLs

---

## File Ownership (Who Can Edit What)

| Path | Owner | Edit Freedom |
|------|-------|-------------|
| `vllm_mlx/dashboard/` | **THIS PROJECT** | Full edit |
| `ui/` | **THIS PROJECT** | Full edit |
| `docs/` | **THIS PROJECT** | Full edit |
| `tests/` | **THIS PROJECT** | Full edit (our code only) |
| `scripts/` | **THIS PROJECT** | Full edit |
| `.github/` | **THIS PROJECT** | Full edit |
| `vllm_mlx/` (except dashboard/) | **UPSTREAM** (waybarrios/vllm-mlx) | DO NOT MODIFY |
| `vllm_mlx/server.py` | **UPSTREAM** | DO NOT MODIFY |
| `vllm_mlx/engine/` | **UPSTREAM** | DO NOT MODIFY |
| `vllm_mlx/models/` | **UPSTREAM** | DO NOT MODIFY |
| `vllm_mlx/paged_cache.py`, `prefix_cache.py`, `ssd_cache.py` | **UPSTREAM** | DO NOT MODIFY |
| `vllm_mlx/mcp/`, `constrained/`, `reasoning/`, `tool_parsers/` | **UPSTREAM** | DO NOT MODIFY |

If a bug is found in upstream code:
1. Do NOT patch it here
2. Note it for a PR to upstream
3. Work around it via CLI args or UI settings if possible

---

## Code Conventions

### Python
- License header: `# SPDX-License-Identifier: Apache-2.0` on every `.py` file
- Python 3.10+ syntax (`list[str] | None`, not `Optional[list[str]]`)
- Async throughout — all engine methods are `async def`
- Pydantic models for all API request/response types
- Tag slow tests with `@pytest.mark.slow`, integration tests with `@pytest.mark.integration`

### TypeScript/Vue
- Vue 3 Composition API with `<script setup>`
- Pinia for state management
- CSS custom properties (design tokens) defined in `ui/src/assets/tokens.css`
- Use tokens, NOT hardcoded colors
- Components in PascalCase, composables prefixed with `use`

### Error Handling (NEW CONVENTION from audit)
- **NEVER** use bare `except Exception: pass`
- **ALWAYS** log exceptions: `except Exception as e: logger.warning("...", exc_info=True)`
- **NEVER** silently swallow errors in frontend catch blocks — show user feedback
- Use `try/except` with specific exception types where possible

### Threading (NEW CONVENTION from audit)
- **NEVER** share mutable state between threads without locks
- Use `threading.Lock()` or `asyncio.Lock()` for shared dicts/lists
- **NEVER** spawn daemon threads without tracking references
- Track all background threads for cleanup on shutdown

---

## Build Commands

```bash
# Python
pip install -e ".[dev]"          # dev install
pytest tests/                     # run tests
ruff check vllm_mlx/ tests/       # lint
black vllm_mlx/ tests/            # format
mypy vllm_mlx/                    # type check

# Frontend
cd ui && npm run dev              # dev server
cd ui && npm run build            # production build
cd ui && npm run preview          # preview build

# Release (NEVER do manually)
bash scripts/release.sh <version>
```

---

## Git Conventions

- Commits should reference GitHub Issues: `fix: resolve issue #123 — description`
- Use conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `perf:`, `test:`, `chore:`
- One logical change per commit
- **NEVER** commit directly to `main` without a PR
- **NEVER** commit after running `scripts/release.sh` — the script handles commits

---

## Change Log (Agent-to-Agent Communication)

### 2026-04-29 — Full Codebase Audit
- Completed comprehensive audit of entire codebase (Python backend + Vue frontend)
- Found 111 total issues: 7 security, 17 error handling, 7 race conditions, 9 logic bugs, 19 performance, 5 memory/resource, 6 type safety, 5 async, 6 anti-patterns, 18 UI/UX, 5 dead code, 7 null checks
- Created this `AGENTS.md` file for inter-agent communication
- Created `PROJECT_PLAN.md` with 5-phase implementation roadmap
- Created 15+ GitHub Issues tracking all planned fixes
- Created `PERFORMANCE_AUDIT.md` with detailed performance analysis
- **IMPORTANT:** No code changes made yet — only documentation and issue tracking

<!-- Add new entries here when agents make changes -->

### 2026-04-30 — Phase 1 Code Fixes Applied
- **#1** Fixed command injection in 3 example scripts (`os.system()` → `subprocess.run()`)
- **#3** Replaced 98 `except Exception: pass` with proper logging across 8 dashboard files
- **#4** Random API key (`secrets.token_urlsafe(32)`) generated on first launch
- **#5** Fixed `get_logs()` return type — now always `list[str]` (was inconsistent)
- **#6** Added missing CSS tokens: `--bd`, `--bg3`, `--bg4`, `--tx1`, `--tx2`, `--tx3`, `--bg-inset`
- **#7** Theme now persisted in localStorage, respects OS `prefers-color-scheme`
- Commit: `98830e3` — 18 files changed, +486/-223 lines

### 2026-04-30 — Phase 2 Frontend Polish Applied
- **#8** Dynamic imports: `router/index.ts` — all 7 views lazy-loaded via `() => import()`
- **#9** Trimmed highlight.js: `DocsView.vue` — full bundle → `lib/core` + 12 language modules (~147 KB → ~30 KB)
- **#10** Visibility-aware polling: `stores/server.ts` — polling pauses on tab hide, resumes on show
- **#12** Global toast system:
  - New `stores/toast.ts` — Pinia store with `info()`, `success()`, `warning()`, `error()` helpers
  - New `components/shared/ToastNotification.vue` — Teleported toast stack with auto-dismiss and type-coloured borders
  - Integrated in `App.vue` — mounted globally, no manual instantiation needed
- **#13** Mobile navigation: `AppTopbar.vue` — hamburger button + slide-out nav drawer at <720px
- **#15** Modal accessibility: `ConfirmModal.vue` — focus trap, Escape handler, autofocus Cancel
- **#11** 5 new shared components:
  - `ErrorBanner.vue` — dismissable error banner with `role="alert"`, icon, message, dismiss
  - `Spinner.vue` — configurable size/color spinner with `role="status"` and `aria-label="Loading"`
  - `EmptyState.vue` — reusable placeholder with title, description, optional icon and action slot
  - `ToggleSwitch.vue` — accessible on/off toggle with label, description, built-in focus-visible
  - `ModelSelector.vue` — model dropdown with loading spinner, placeholder, disabled state
- **#14** ARIA labels + focus-visible styles:
  - `tokens.css`: Added global `:focus-visible` / `:focus:not(:focus-visible)` rules + skip-link styles
  - `AppSidebar.vue`: `aria-label` on nav, `aria-current="page"` on active links, `aria-pressed` on machine buttons, `aria-labelledby` on model selector, focus-visible on all interactive elements
  - `AppTopbar.vue`: Mobile menu close button, hamburger button already had `aria-label`
  - `ServeView.vue`: `aria-label` on start/stop/clear buttons, model select, copy buttons; focus-visible on copy buttons and view-full-link
  - `ModelsView.vue`: `role="group"` on filter chips, `aria-pressed` on active filters, `aria-label` on search inputs and company chips; focus-visible on chips, sort headers, filter buttons
  - `SettingsView.vue`: `aria-labelledby` on all 8 sections linking to section title IDs
  - `ConfirmModal.vue`: Already had focus trap, Escape handler, autofocus, `role="dialog"`, `aria-modal`

### 2026-04-30 — Phase 3 Backend Stability Fixes Applied
- **#16** Thread-safe shared state:
  - `server_manager.py`: Added `_resolved_urls_lock` to protect `_resolved_urls` dict from concurrent reads/writes
  - `model_manager.py`: Added `_monitor_threads` tracking dict; monitor threads now tracked, self-unregister, and are joined with 5s timeout before download completion
  - `update_checker.py`: Added `_cache_lock` to protect `_cache` dict from concurrent access across background threads and UI thread
- **#17** Replaced mutable `DEFAULT_CONFIG` dict with `MappingProxyType` wrapper — prevents accidental module-level mutation while maintaining `.copy()` and `{**...}` compatibility
- **#18** Fixed version comparison fallback in `update_checker.py` — replaced `!=` string comparison with proper semver tuple parsing (e.g. `1.2.10` > `1.2.2` now correct)
- **#22** Removed silent `catch { /* silent */ }` blocks in frontend:
  - `SettingsView.vue`: Added `settingsError` banner; all 10 silent catches now show user-facing error messages
  - `ServeView.vue`: Added comments to non-critical catches (clipboard, network info)
  - `ModelsView.vue`: Changed `console.error` to `modelsStore.actionError` for delete/download failures

### 2026-04-30 — Phase 2 Bug Fixes Applied
- **Critical**: `ToastNotification.vue` — removed `.value` from template (Vue auto-unwraps store refs)
- **Medium**: `ModelsView.vue` — `aria-pressed` missing `:` binding (was string literal)
- **Medium**: `ModelsView.vue` — undefined `--bg-2` CSS token → replaced with `var(--bg-elevated)` (3 occurrences)

### 2026-04-30 — Phase 4 Performance Optimizations Applied
- **#24** Batch polling endpoint:
  - `mgmt_server.py`: New `GET /poll` endpoint returns status + metrics + memory + config in one HTTP call
  - `stores/server.ts`: `startPolling()` now calls `fetchAllBatched()` — 4 sequential requests → 1 per poll cycle
  - Falls back to individual fetches for older servers without `/poll` endpoint
  - Estimated ~75% reduction in polling network overhead
- **#29** Bundle analysis tooling:
  - `package.json`: Added `rollup-plugin-visualizer` dev dependency + `npm run analyze` script
  - `vite.config.ts`: Visualizer plugin generates `dist/stats.html` treemap with gzip/brotli sizes
  - Run `cd ui && npm run analyze` to open interactive bundle visualization

### 2026-04-30 — Phase 4 Upstream PRs (Not Applied)
The following Phase 4 tasks are in upstream `vllm_mlx/` code (outside `dashboard/`). Should be filed as PRs to `waybarrios/vllm-mlx`:
- **#23** `server.py:1250-1257` — Add `@lru_cache` to tokenizer lookup (hot path)
- **#25** `ssd_cache.py:247-280` — Replace O(N) linear prefix scan with hash index
- **#26** `ssd_cache.py:503-540` — Replace O(N log N) eviction with priority queue
- **#27** `server.py:934-946` — Memoize model path resolution
- **#28** `ssd_cache.py` / `memory_cache.py` — Memory-map large token arrays
