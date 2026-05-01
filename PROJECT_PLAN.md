# Project Plan — vllm-mlx-ui Stabilization

**Created:** 2026-04-29  
**Source:** Full codebase audit findings  
**Status:** Ready to execute

---

## Overview

After a comprehensive audit finding **111 issues** across the codebase, this plan organizes fixes into 5 phases, ordered by risk and ROI. Each phase targets a specific area of the codebase and can be worked on independently (though phases should be executed in order).

---

## Phase 1: Critical Fixes (Week 1)

**Goal:** Eliminate security vulnerabilities and most damaging bugs.  
**Risk if skipped:** High — security exposure, silent failures, event loop blocking.

| # | Task | Files | Est. Time | GitHub Issue |
|---|------|-------|-----------|--------------|
| 1.1 | Fix command injection in example scripts | `examples/tts_example.py`, `tts_multilingual.py`, `audio_separation_example.py` | 30 min | #1 |
| 1.2 | Replace `except Exception: pass` with logging | 10+ files (model_manager, server_manager, update_checker, server) | 4 hours | #2 |
| 1.3 | Fix blocking I/O in async lifespan | `server.py:869,925` | 30 min | #3 |
| 1.4 | Generate random default API key | `server_manager.py:156` | 30 min | #4 |
| 1.5 | Fix return type inconsistency in `get_logs()` | `server_manager.py:849` | 30 min | #5 |
| 1.6 | Define missing CSS tokens | `tokens.css`, `ChatView.vue` | 1 hour | #6 |
| 1.7 | Persist theme + respect OS preference | `AppTopbar.vue` | 1 hour | #7 |

**Deliverable:** No critical security issues, no silent error swallowing, non-blocking startup.

---

## Phase 2: Frontend Polish (Week 2)

**Goal:** Modernize UI, improve accessibility, fix UX issues.  
**Risk if skipped:** Medium — poor UX, accessibility violations, mobile unusable.

| # | Task | Files | Est. Time | GitHub Issue |
|---|------|-------|-----------|--------------|
| 2.1 | Dynamic imports for router views | `router/index.ts` | 1 hour | #8 |
| 2.2 | Trim highlight.js bundle | `ui/package.json`, component imports | 1 hour | #9 |
| 2.3 | Visibility-aware polling | `stores/server.ts` | 2 hours | #10 |
| 2.4 | Create shared components (5) | `components/ModelSelector.vue`, `Spinner.vue`, `ErrorBanner.vue`, `EmptyState.vue`, `ToggleSwitch.vue` | 6 hours | #11 |
| 2.5 | Global toast/notification system | New `Toast.vue` component + store | 4 hours | #12 |
| 2.6 | Mobile navigation | `AppSidebar.vue` | 4 hours | #13 |
| 2.7 | ARIA labels + focus styles | All Vue components | 4 hours | #14 |
| 2.8 | Modal accessibility (focus trap, Escape) | `ConfirmModal.vue` | 1 hour | #15 |

**Deliverable:** Accessible, mobile-friendly UI with consistent patterns and feedback.

---

## Phase 3: Backend Stability (Week 3)

**Goal:** Thread safety, proper resource management, robust error handling.  
**Risk if skipped:** High — race conditions, resource leaks, crashes under load.

| # | Task | Files | Est. Time | GitHub Issue |
|---|------|-------|-----------|--------------|
| 3.1 | Thread-safe shared state | `server_manager.py`, `model_manager.py`, `update_checker.py` | 4 hours | #16 |
| 3.2 | Replace mutable DEFAULT_CONFIG | `server_manager.py:162-164` | 1 hour | #17 |
| 3.3 | Fix version comparison fallback | `update_checker.py:155-157` | 1 hour | #18 |
| 3.4 | Close file handles properly | `server_manager.py:755`, `ssd_cache.py:575` | 1 hour | #19 |
| 3.5 | Remove monkey-patching in scheduler | `scheduler.py:144-161` | 3 hours | #20 |
| 3.6 | Add proper form validation | `SettingsView.vue`, `ServeView.vue` | 3 hours | #21 |
| 3.7 | Silent error handling in frontend | `SettingsView.vue`, `ModelsView.vue` | 2 hours | #22 |

**Deliverable:** Thread-safe backend, proper resource cleanup, validated inputs.

---

## Phase 4: Performance Optimization (Week 4)

**Goal:** Reduce latency, improve throughput, shrink bundle.  
**Risk if skipped:** Medium — sluggish UI, slow startup, wasted resources.

| # | Task | Files | Est. Time | GitHub Issue |
|---|------|-------|-----------|--------------|
| 4.1 | Cache tokenizer with lru_cache | `server.py:1250-1257` | 30 min | #23 |
| 4.2 | Batch polling endpoint | `mgmt_server.py`, `stores/server.ts` | 3 hours | #24 |
| 4.3 | SSD cache indexing | `ssd_cache.py:247-280` | 6 hours | #25 |
| 4.4 | Eviction priority queue | `ssd_cache.py:503-540` | 4 hours | #26 |
| 4.5 | Memoize model path resolution | `server.py:934-946` | 1 hour | #27 |
| 4.6 | Memory-map large token arrays | `ssd_cache.py`, `memory_cache.py` | 4 hours | #28 |
| 4.7 | Add bundle analysis tooling | `vite.config.ts` | 1 hour | #29 |

**Deliverable:** Faster startup, responsive UI, efficient caching.

---

## Phase 5: Architecture & Features (Week 5+)

**Goal:** Structural improvements, new features, better DX.  
**Risk if skipped:** Low — these are enhancements, not fixes.

| # | Task | Est. Time | GitHub Issue |
|---|------|-----------|--------------|
| 5.1 | Refactor global state to DI | 1-2 weeks | #30 |
| 5.2 | Add integration tests | 1 week | #31 |
| 5.3 | Command palette (Cmd+K) | 3 days | #32 |
| 5.4 | Benchmark comparison visualization | 3 days | #33 |
| 5.5 | i18n infrastructure | 2 days | #34 |
| 5.6 | Onboarding/first-run tour | 2 days | #35 |
| 5.7 | Virtual scrolling for long lists | 3 days | #36 |
| 5.8 | Switch to history mode routing | 2 days | #37 |

**Deliverable:** Cleaner architecture, richer features, internationalization.

---

## Issue Labels

All issues created with these labels:
- `audit-2026-04-29` — tagged from this audit
- `phase-1` through `phase-5` — indicates which phase
- `security`, `bug`, `enhancement`, `performance`, `accessibility` — category
- `quick-win` — high ROI, low effort (Phase 1 items)

---

## Dependencies Between Phases

```
Phase 1 (Critical) ──────────────────────────────────────────┐
       ↓                                                      │
Phase 2 (Frontend) ── depends on Phase 1 (no silent errors) ─┤
       ↓                                                      │
Phase 3 (Backend)  ── can run parallel to Phase 2 ───────────┤
       ↓                                                      │
Phase 4 (Perf)     ── depends on Phase 3 (stable backend) ───┤
       ↓                                                      │
Phase 5 (Features) ── depends on Phases 1-4 (stable base) ───┘
```

**Recommended execution order:** Phase 1 → Phase 2 + Phase 3 (parallel) → Phase 4 → Phase 5

---

## Progress Tracking

- [x] Phase 1: Critical Fixes (7/7 tasks)
- [x] Phase 2: Frontend Polish (8/8 tasks)
- [x] Phase 3: Backend Stability (7/7 tasks)
- [x] Phase 4: Performance (2/2 editable tasks; 5 upstream → PRs)
- [ ] Phase 5: Architecture & Features (0/8 tasks)

**Total:** 24/37 editable tasks complete (5 upstream tasks tracked for PRs)
