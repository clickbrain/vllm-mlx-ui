# AGENTS.md — vllm-mlx-ui

> This file is the **single source of truth** for all AI agents (Copilot, Claude, etc.) working on this repo. Read it before making any changes.

---

## ⚠️ MANDATORY RELEASE CHECKLIST — EVERY RELEASE, NO EXCEPTIONS

**Before running `scripts/release.sh`**, ALL of the following must be complete:

### 1. CHANGELOG.md — Required
- Add a `## vX.Y.Z — YYYY-MM-DD` section at the TOP of `CHANGELOG.md`
- Every change must be documented: features added, bugs fixed, behavior changed
- Be specific — include what broke, what was fixed, and why. Bad: "Fix ds4 bug". Good: "Fix ds4 `build_command()` passing `--ctx` before `--host`, causing a parse error on ds4-server ≥ 0.3"
- The CHANGELOG entry is the release notes shown on GitHub Releases — users read it

### 2. README.md — Update when needed
- **Feature table**: update when a new capability is added or removed
- **Requirements**: update when OS/hardware requirements change (e.g. new Apple chip support)
- **Engine list**: update when an engine is added, removed, or renamed
- **Troubleshooting**: update when a fix changes a known workaround
- **File layout**: update when the architecture changes significantly
- Do NOT leave stale version numbers, wrong ports, or removed features in the README

### 3. docs/ — Update when needed
- `docs/dashboard/user-guide.md`: update when UI pages, features, or workflows change
- `docs/getting-started/installation.md`: update when install steps change
- `docs/reference/cli.md`: update when CLI flags change
- `docs/reference/configuration.md`: update when config keys are added/removed
- Engine-specific docs: update when engine config schema changes

### 4. GitHub Release — AUTOMATIC via release.sh
- `scripts/release.sh` calls `gh release create --generate-notes` automatically
- **Never push a tag manually** — always use `scripts/release.sh`
- Verify on GitHub after every release: https://github.com/clickbrain/vllm-mlx-ui/releases
- The latest release on GitHub MUST match the version in `vllm_mlx/dashboard/__init__.py`

### 5. App help links — Verify before release
- All `href` links in the Vue UI must point to real pages
- The `/docs` route must load correctly with the latest docs content
- External links (GitHub, HuggingFace, Prometheus) must still be valid

### ENFORCEMENT
**If a PR or release is missing any of the above, it is incomplete.** Do not mark a task done, do not run release.sh, until the docs are updated. "I'll update docs later" is not acceptable.

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

### 2026-05-02 — Phase 2-5 Implementation Complete
**Phase 2 — Frontend Polish (8/8 tasks)**
- Lazy-loaded routes (`router/index.ts`)
- Trimmed highlight.js bundle (~147KB → ~30KB)
- Visibility-aware polling (pauses on tab hide)
- 5 shared components: `ErrorBanner`, `Spinner`, `EmptyState`, `ToggleSwitch`, `ModelSelector`
- Global toast notification system (`stores/toast.ts` + `ToastNotification.vue`)
- Mobile navigation with hamburger menu (<720px)
- ARIA labels + `:focus-visible` styles across all views
- `ConfirmModal` focus trap + Escape handler
- Commit: `089e1cd` (PR #33 pending review)

**Phase 3 — Backend Stability (7/7 tasks)**
- Thread-safe shared state with `threading.Lock()` in `server_manager`, `model_manager`, `update_checker`
- Immutable `DEFAULT_CONFIG` via `MappingProxyType`
- Proper semver comparison in `update_checker` (fixes `1.2.10` < `1.2.2` bug)
- Removed silent `catch {}` blocks in `SettingsView`, `ModelsView`

**Phase 4 — Performance (2/2 editable tasks)**
- Batch polling endpoint `GET /poll` — 4 sequential requests → 1 per cycle (~75% reduction)
- Bundle analysis with `rollup-plugin-visualizer` (`npm run analyze`)

**Phase 5 — Architecture & Features (8/8 tasks)**
- 5.8: History mode routing (`createWebHistory`)
- 5.5: i18n infrastructure (`vue-i18n@11`, `en-US` locale)
- 5.6: First-run onboarding tour (`TourOverlay.vue`, `useTourStore`)
- 5.3: Command palette (`Cmd+K`) with `CommandPalette.vue`, `useCommandPaletteStore`
- 5.2: Integration tests for Tour & CommandPalette (vitest + @pinia/testing, 8 passing)
- 5.7: Virtual scrolling for `ModelsView` (`vue-virtual-scroller`)
- 5.4: Enhanced benchmark comparison visualization (bar charts)
- 5.1: DI container plan (`di-plan.md`), initial `provideStores()` in `main.ts`
- Commit: `fbad52b` (PR #34 created)

**Total Progress:** 32/37 editable tasks complete (5 upstream tasks tracked for PRs to `waybarrios/vllm-mlx`).
**Branches:** `feat/phase-2-4-polish-stability-perf` (PR #33), `feat/phase-5-architecture-features` (PR #34).

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

### 2026-05-01 → 2026-05-08 — Engine Upgrade Fixes (v0.5.11–v0.5.14)

**Summary:** Engine upgrade commands were embedded inline in the `sh -c` string alongside `brew upgrade` and `pip install`. Because the Python script contained newlines and semicolons that weren't shell-quoted, the shell re-parsed them as separate commands — `python3 -c import` instead of `python3 -c "import base64; exec(...)"` — which broke the `&&` chain and silently prevented ALL engine upgrades AND could interfere with the main chain.

Three failed attempts before the correct fix:
1. **Base64-encode** the script (`ollama.py`) — didn't fix shell re-parsing of the joined argv
2. **`shlex.quote()`** each arg (`update_checker.py`) — correct in isolation but still embedded in `&&` chain
3. **Correct fix:** Remove engine clauses from `upgrade_command()` entirely. Run them as separate `subprocess.run(argv_list)` calls in `_do_upgrade()` — no shell, no `&&`, no ambiguity.

**Critical rule — NEVER DO THIS:**
- Do NOT embed Python scripts (or any argv with spaces/semicolons) inside a `sh -c` string via `" ".join(argv)`. The shell re-parses spaces and metacharacters, destroying argument boundaries.
- Do NOT mix engine upgrades into the same shell pipeline as `brew upgrade` / `pip install`. If an engine command breaks (even with `|| true`), it can silently break the `&&` chain.
- **Always run engine upgrades as separate `subprocess.run(argv_list)` calls** — one call per engine, `check=False`, iterated in the `_do_upgrade()` thread function.

**Files changed:**
- `vllm_mlx/dashboard/update_checker.py` — Replaced `_engine_upgrade_clauses()` (returned shell-quoted strings) with `engine_upgrade_commands()` (returns `list[list[str]]` argv lists). Added `_resolve_pip_bin()` helper. Removed engine clauses from `upgrade_command()`.
- `vllm_mlx/dashboard/mgmt_server.py` — `_do_upgrade()` now runs `subprocess.run(cmd)` for main upgrade, then iterates `engine_cmds` with individual `subprocess.run(ec)` calls.
- `vllm_mlx/dashboard/engines/ollama.py` — `upgrade_command()` still base64-encodes the script (harmless, but not executed through shell anymore).

**Releases:** v0.5.11–v0.5.14

### 2026-05-09 — v0.5.15: Ollama asset URL, engine save-and-restart, partial config fix

**Ollama upgrade** — The CLI binary is now distributed as `ollama-darwin.tgz` instead of `.zip`.  Rewrote the upgrade script to query the GitHub releases API for the dynamic asset URL (match prefix `ollama-darwin`) instead of hardcoding the filename.  Future asset renames or format changes will not break the upgrade.

**Engine selection not persisting** — Two bugs:
1. `SettingsView.vue:92` — `saveEngineAndRestart()` had an early return `if (selectedEngine.value === serverStore.engineId) return`.  When polling updated the store before the user clicked Save & Restart, the function silently returned without restarting.  **Fix:** Always attempt restart when explicitly clicked.
2. `mgmt_server.py:236` — `set_config()` saved partial dicts (`{"engine_id": "rapid-mlx"}`) directly, overwriting the entire config file and losing all other settings.  **Fix:** Merge incoming data with the existing config before saving.

**Serve page engine badge** — Always shows `Engine: <id>` when the server is running (previously hidden for the default engine).

**Release:** v0.5.15

### 2026-05-09 — v0.5.16: Remove hanging sudo, ~/.local/bin fallback, verified end-to-end

**Ollama upgrade** — Two more bugs fixed:
1. `sudo cp` + `sudo chmod` removed from upgrade script — these hung for 30s waiting for a password in the non-interactive background subprocess, causing a silent timeout failure
2. When target dir (`/usr/local/bin/`) is not writable, falls back to `~/.local/bin/ollama` instead of failing

**Verified end-to-end:** Ran the actual subprocess command — downloaded 134MB, extracted 79MB binary, installed to `~/.local/bin/ollama`, exit code 0.

**Release:** v0.5.16

### 2026-05-09 — v0.5.17: Auto-add ~/.local/bin to PATH when falling back

**PATH setup** — When the upgrade script falls back to `~/.local/bin/ollama`, it now:
1. Detects the user's shell from `$SHELL` (zsh/bash/fish)
2. Finds the appropriate rc file (`.zshenv`/`.zshrc`, `.bash_profile`/`.bashrc`, `config.fish`)
3. Checks if `$HOME/.local/bin` is already configured in the rc file
4. If not, appends `if [ -d "$HOME/.local/bin" ]; then export PATH="$HOME/.local/bin:$PATH"; fi`
5. Prints a message telling the user to restart their shell

This ensures `which ollama` resolves to the new version even for desktop app users.

**Files changed:**
- `vllm_mlx/dashboard/engines/ollama.py:179-211` — PATH setup logic after install

### 2026-05-10 — v0.5.21: Find tab filter apply button

**Problem:** Client-side filters (size range, fit level, download range) only operated on the 25 pre-fetched HF results. Setting `sizeMin=7GB` silently reduced display to 0–1 results with no way to re-fetch.

**Fix:** Added `filtersPending` ref that activates when any filter input changes. "Apply Filters" button appears in the filter panel. Clicking re-fetches from HF with `limit=100` (4× default page size), then applies client-side filters on the larger pool. "Showing X of Y results matching filters" summary provides visibility.

**Files changed:**
- `ui/src/views/ModelsView.vue` — `filtersPending` ref, `markFiltersDirty()`, `applyFilters()`, `preFilterCount` computed, Apply button + filter summary in template, CSS

**Release:** v0.5.21

### 2026-05-12 — v0.6.0: ds4-m5 inference engine (DeepSeek V4 Flash)

**New engine:** `ds4-m5` — native Metal/CUDA inference engine for DeepSeek V4 Flash GGUF models, forked from antirez/ds4 with M5 optimisations.

**Files added:**
- `vllm_mlx/dashboard/engines/ds4_m5.py` — Full engine adapter with:
  - `detect_apple_chip()` / `is_m5_chip()` — reads `sysctl machdep.cpu.brand_string` to detect M1–M5
  - `_total_ram_gb()` — reads `sysctl hw.memsize` to detect available RAM
  - `_recommended_quant()` — picks `q2-imatrix` (<256 GB) or `q4-imatrix` (≥256 GB)
  - `install_command()` — `git clone -b m5` → `make` → `download_model.sh <auto-detected quant>`
  - `build_command()` — launches `ds4-server` with host/port/ctx/kv-disk flags
  - `upgrade_command()` — `git pull + make clean + make`
  - `config_schema()` — quantization selector (auto-defaults to RAM-appropriate quant), context window, KV cache dir/size, MTP draft, thinking toggle
  - Dynamic description shows chip badge (M5 badge when on M5) + RAM detection + auto-selected quant + hardware requirements table

**Files modified:**
- `vllm_mlx/dashboard/engines/registry.py` — Import and register Ds4M5Engine in `_BUILTINS`
- `ui/src/views/SettingsView.vue` — `white-space: pre-line` on `.engine-card-desc` for multi-line requirement display

**Release:** v0.6.0

### 2026-05-XX — ds4 engine adapter rewrite (antirez/audreyt forks)

**Problem:** `ds4_m5.py` was using `Swival/ds4-m5` which:
- Missing `/v1/responses` endpoint (Codex CLI / OpenAI Responses API)
- Wrong HF model repo (`swival/DeepSeek-V4-Flash-GGUF` vs actual `antirez/deepseek-v4-gguf`)
- Advertised M5 speedup was measured against an old antirez baseline, not valid
- Less maintained than the original

**Fix:** Rewrote `ds4_m5.py` to auto-select correct fork by chip:
- M5 and newer → `audreyt/ds4` (M5 Metal Tensor, ~10% gen speedup, same endpoints)
- M1–M4 → `antirez/ds4` (original, authoritative, by Salvatore Sanfilippo)

**Key changes:**
- `_select_fork()` / `_detect_installed_fork()` — fork selection and git remote detection
- `_chip_generation()` + `is_m5_or_newer()` — future-proof M5+ detection (M6/M7 safe)
- `_ds4_dir()` — `~/.local/share/ds4` (new) with fallback to `~/.local/share/ds4-m5` (legacy)
- `_MODEL_HF_REPO` — fixed to `antirez/deepseek-v4-gguf`
- `build_command()` — added `--chdir` (Metal shader resolution), M5-only `--mt auto`, normalized all paths to absolute
- `max_output_tokens` default — 384000 (from 65536) per antirez coding agent recommendation
- `upgrade_command()` — Swival users: migration command that clones correct fork + copies gguf dir (no 87GB re-download)
- `latest_version()` — tracks the installed fork's GitHub API (not always antirez)
- `install_command()` — clones correct fork based on chip, `main` branch (no `-b m5`)
- Engine `name` — "DeepSeek V4 Flash (ds4)", `release_url` → antirez/ds4


**Context:** User wants to rename this project (`vllm-mlx-ui` / `clickbrain/vllm-mlx-ui`) to a new name. Full audit completed — ~1800 references across ~70 files. Key findings:
- **Python package** `vllm_mlx/` is ~50% upstream code (waybarrios/vllm-mlx — DO NOT MODIFY) and ~50% our dashboard code
- **Upstream code** (`vllm_mlx/server.py`, `engine/`, `models/`, etc.) must stay as-is or be PR'd to upstream
- **Our code** in `vllm_mlx/dashboard/`, `ui/`, `docs/`, `scripts/`, `Formula/`, `.github/`, root files — all editable
- **Homebrew formula** `Formula/vllm-mlx-ui.rb` with class `VllmMlxUi`
- **State dir** `~/.vllm_mlx_ui/` used in ~14 files
- **Config dir** `~/.config/vllm-mlx-ui/engines/` and `~/.config/vllm-mlx-ui/config.json`
- **Entry point group** `vllm_mlx_ui.engines` for plugin discovery
- **TOUR_KEY** = `'vllm-mlx-ui-tour-completed'` in `ui/src/stores/tour.ts`
- **Biggest decision:** whether to rename the `vllm_mlx/` Python package dir or just the project wrapper
- When user says "rename notes" or "name change notes" — refer here
