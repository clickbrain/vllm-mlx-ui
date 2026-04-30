# vLLM-MLX-UI Performance Audit

**Date:** 2026-04-29
**Scope:** Python backend (`vllm_mlx/`) + Vue.js frontend (`ui/`)
**Categories:** 12 performance issue categories

---

## 1. N+1 Queries / Inefficient Loops

### 1.1 SSD Cache Prefix Lookup — O(N) Full Scan
- **File:** `vllm_mlx/ssd_cache.py:247-280`
- **Issue:** `lookup_prefix()` iterates ALL entries where `num_tokens <= query_len` to find best prefix match. No index or tree structure.
- **Severity:** High (grows linearly with cache size)
- **Fix:** Add a sorted index (e.g., by token prefix hash) or use the SQLite index more effectively for prefix-based lookups instead of scanning.

### 1.2 Trie DFS for Longest Match
- **File:** `vllm_mlx/prefix_cache.py:153-163`
- **Issue:** `_search_longer_match` uses DFS on the trie which can be expensive with deep tries containing many nodes.
- **Severity:** Medium
- **Fix:** Track longest match during forward traversal instead of separate DFS pass.

### 1.3 Tool Arguments Coercion — Nested Loops
- **File:** `vllm_mlx/server.py:1126-1170`
- **Issue:** `_coerce_tool_arguments` scans the full tools list for every single tool call argument, creating O(T×A) complexity.
- **Severity:** Low (T is small in practice)
- **Fix:** Build a tool_name→schema lookup dict once, then O(1) per argument.

---

## 2. Unnecessary Computation

### 2.1 Repeated `getattr` Config Extraction
- **File:** `vllm_mlx/scheduler.py:159-194`, `vllm_mlx/engine/batched.py:123-167`, `vllm_mlx/mllm_scheduler.py:28-63`
- **Issue:** Each scheduler/engine extracts the same config values with `getattr(model_config, ..., default)` repeatedly on every initialization and in some cases per-request.
- **Severity:** Low (one-time per init, but scattered across 3+ files)
- **Fix:** Create a shared config extraction helper or dataclass.

### 2.2 Sanitize Log Text — Character-by-Character
- **File:** `vllm_mlx/server.py:551-567`
- **Issue:** `_sanitize_log_text` builds a list of characters one-by-one checking each char. Works but could use regex for clarity and potential speedup.
- **Severity:** Low (only used for log output)
- **Fix:** Use `re.sub(r'[^\x20-\x7E\n\r\t]', '', text)`.

---

## 3. Missing Caching

### 3.1 Tokenizer Lookup Not Memoized
- **File:** `vllm_mlx/server.py:1250-1257`
- **Issue:** `_get_engine_tokenizer` performs `hasattr`/`getattr` checks every call. Called per-request in completion/chat/streaming endpoints.
- **Severity:** Medium (hot path, called per-request)
- **Fix:** Cache tokenizer reference at server init or use `@functools.lru_cache(maxsize=1)`.

### 3.2 Model Path Resolution
- **File:** `vllm_mlx/server.py:934-946`
- **Issue:** `_resolve_model_path` calls `resolve_model_path` from utils on every request. The resolution logic (searching model directories) could be cached.
- **Severity:** Medium
- **Fix:** Cache resolved paths with `@lru_cache` keyed by model identifier.

---

## 4. Inefficient Data Structures

### 4.1 SSD Cache Entry List
- **File:** `vllm_mlx/ssd_cache.py:71-83`
- **Issue:** `CacheEntry` stored in plain Python `list` and `dict`. For large SSD caches with thousands of entries, list scans for eviction and lookup become expensive.
- **Severity:** Medium
- **Fix:** The SQLite index helps but in-memory data structures could use `SortedDict` or a proper LRU/LFU structure.

### 4.2 Request Tracking Sets
- **File:** `vllm_mlx/memory_cache.py:79-82`
- **Issue:** `_active_requests: Set[str]` is fine for O(1) membership, but `_evicting_requests: Dict[str, int]` dict scans in `_can_evict()` at line 854.
- **Severity:** Low
- **Fix:** Already using set for membership; dict lookup is O(1). No change needed.

---

## 5. String Concatenation in Loops

### 5.1 Response Content to Text
- **File:** `vllm_mlx/server.py:1363-1373`
- **Status:** ✅ Already correct — uses `text_parts` list then `''.join()`. No issue.

### 5.2 Error Message Building
- **File:** `vllm_mlx/server.py:1263-1277`
- **Issue:** Error messages built with multiple f-string concatenations in loop. Minor but noticeable in hot error paths.
- **Severity:** Low
- **Fix:** Already using list+join pattern. No change needed.

---

## 6. Blocking Async Operations

### 6.1 Blocking Cache Load/Save in Lifespan
- **File:** `vllm_mlx/server.py:869, 925`
- **Issue:** `_load_prefix_cache_from_disk()` and `_save_prefix_cache_to_disk()` are called directly in async lifespan context without `asyncio.to_thread()`. These are I/O-heavy operations that block the event loop.
- **Severity:** High (blocks entire async event loop during startup/shutdown)
- **Fix:** Wrap with `await asyncio.to_thread(_load_prefix_cache_from_disk, ...)` and same for save.

### 6.2 Blocking File Read in Dashboard
- **File:** `vllm_mlx/dashboard/app.py:109`
- **Issue:** PID file read with synchronous `open().read()` in what could be an async context.
- **Severity:** Low (CLI tool, not a hot path)
- **Fix:** Minor; acceptable for CLI usage.

---

## 7. Large File Reads Without Streaming

### 7.1 Binary Token File Reads
- **File:** `vllm_mlx/memory_cache.py:1211`, `vllm_mlx/ssd_cache.py` (multiple locations)
- **Issue:** Entire token arrays read from binary `.bin` files into memory at once with `np.fromfile()`. For large prefix caches with millions of tokens, this can spike memory.
- **Severity:** Medium
- **Fix:** Consider memory-mapped files (`np.memmap`) for read-only access to avoid loading entire arrays.

### 7.2 Model File Loading
- **File:** `vllm_mlx/server.py:960-986`
- **Issue:** `load_model` loads entire model into memory. Expected for MLX but no progress feedback or streaming status.
- **Severity:** Low (expected behavior for model loading)
- **Fix:** Add progress callbacks if `mlx_lm` supports them.

---

## 8. Missing Pagination

### 8.1 Model List Endpoint
- **File:** `vllm_mlx/server.py:994-1007` (`GET /v1/models`)
- **Issue:** Returns ALL available models in a single response. No pagination, filtering, or limit parameters.
- **Severity:** Low (model count is typically small)
- **Fix:** Add `?limit=`, `?offset=`, `?search=` query params for future-proofing.

### 8.2 Dashboard Log Endpoint
- **File:** `vllm_mlx/server.py:570-590` (`GET /logs`)
- **Issue:** Returns entire log buffer (up to `max_lines=2000`) without pagination.
- **Severity:** Low
- **Fix:** Add `?tail=N`, `?before=timestamp` params.

---

## 9. Inefficient Algorithms

### 9.1 SSD Cache Eviction Strategy
- **File:** `vllm_mlx/ssd_cache.py:503-540`
- **Issue:** Eviction scans all entries to find candidates, sorting by a composite score. O(N log N) per eviction cycle.
- **Severity:** Medium
- **Fix:** Maintain a heap or priority queue for eviction candidates.

### 9.2 Memory Cache Shrink Logic
- **File:** `vllm_mlx/memory_cache.py:700-750`
- **Issue:** `_shrink_to_target()` iterates through sessions and token counts repeatedly until target is met. Could be optimized with a single pass using pre-sorted data.
- **Severity:** Low (only triggered under memory pressure)
- **Fix:** Pre-sort sessions by eviction priority and evict in one pass.

---

## 10. Bundle Size Issues

### 10.1 Heavy Dependencies Eagerly Bundled
- **File:** `ui/package.json`
- **Dependencies:** `chart.js` (~200KB), `highlight.js` (~300KB with all languages), `marked` (~40KB), `dompurify` (~20KB)
- **Issue:** All dependencies bundled into main chunk. No tree-shaking configuration for `highlight.js` languages.
- **Severity:** High
- **Fix:** 
  - Import only needed highlight.js languages
  - Code-split chart.js into benchmark view only
  - Consider lighter alternatives (e.g., `mark.js` instead of `marked`)

### 10.2 No Bundle Analysis
- **File:** `ui/vite.config.ts`
- **Issue:** No `rollup-plugin-visualizer` or similar bundle analysis plugin configured.
- **Severity:** Low
- **Fix:** Add `vite-bundle-visualizer` plugin for development.

---

## 11. Missing Lazy Loading

### 11.1 Router Views Eagerly Imported
- **File:** `ui/src/router/index.ts:1-34`
- **Issue:** All view components imported synchronously at top of file:
  ```typescript
  import DashboardView from '../views/DashboardView.vue'
  import ServeView from '../views/ServeView.vue'
  import ModelsView from '../views/ModelsView.vue'
  // ... etc
  ```
- **Severity:** Medium (blocks initial page load)
- **Fix:** Use dynamic imports:
  ```typescript
  const DashboardView = () => import('../views/DashboardView.vue')
  ```

### 11.2 Components Not Lazy Loaded
- **File:** `ui/src/views/` (all views)
- **Issue:** Chart component, markdown renderer, and highlight.js loaded in views that may not be visited.
- **Severity:** Medium
- **Fix:** Use `defineAsyncComponent` for heavy components inside views.

---

## 12. Render Performance Issues

### 12.1 Aggressive Polling with Multiple API Calls
- **File:** `ui/src/stores/server.ts:231-237`
- **Issue:** Every 3 seconds, polling calls 4 APIs sequentially:
  1. `fetchStatus()` → `/api/status`
  2. `fetchMemory()` → `/api/memory`
  3. `fetchConfig()` → `/api/config`
  4. `fetchMetrics()` → `/api/metrics` (if `isRunning`)
- **Severity:** Medium (causes network overhead and potential UI jank)
- **Fix:**
  - Batch into single `/api/status-all` endpoint
  - Increase interval to 5s
  - Use `requestIdleCallback` for non-urgent updates
  - Skip polling when tab is not visible (`document.visibilityState`)

### 12.2 Chat localStorage Read on Every Init
- **File:** `ui/src/stores/chat.ts:20-25`
- **Issue:** `JSON.parse(localStorage.getItem('chat_sessions') || '[]')` runs on store initialization. If localStorage is large, this blocks store setup.
- **Severity:** Low
- **Fix:** Lazy-load chat sessions on first access.

### 12.3 Reactive State Spread
- **File:** `ui/src/stores/server.ts` (entire file, ~268 lines)
- **Issue:** Store has many reactive properties (`status`, `memory`, `config`, `metrics`, `logs`, `benchmark`, etc.) that all update on each poll cycle. Vue's reactivity system tracks all of them even if the current view only needs a subset.
- **Severity:** Low-Medium
- **Fix:** Split into multiple stores (serverStatus, serverMemory, serverConfig) or use `computed()` selectors in components.

---

## Summary by Severity

| Severity | Count | Priority |
|----------|-------|----------|
| High | 4 | Fix immediately |
| Medium | 8 | Plan for next sprint |
| Low | 7 | Backlog / nice-to-have |

## Quick Wins (Highest ROI)

1. **Lazy-load router views** (`ui/src/router/index.ts`) — 10 lines changed, immediate impact on initial load
2. **Wrap blocking I/O in `asyncio.to_thread`** (`vllm_mlx/server.py:869,925`) — prevents event loop blocking
3. **Import only needed highlight.js languages** (`ui/package.json`) — reduce bundle by ~200KB
4. **Add visibility-aware polling** (`ui/src/stores/server.ts:231`) — eliminate wasted API calls when tab hidden
5. **Cache tokenizer reference** (`vllm_mlx/server.py:1250`) — simple memoization on hot path
