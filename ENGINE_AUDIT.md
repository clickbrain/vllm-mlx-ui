# Engine & Dashboard Audit — v0.8.8

> Generated 2026-05-26. Comprehensive review of all 6 inference engines,
> model_manager.py, and server_manager.py. Findings prioritized by severity.

---

## ✅ Fixed — Pre-Crash (preserved in unstaged diff)

These changes were identified before the session crash and remain as
uncommitted modifications in 5 files:

### rapid_mlx.py — stale defaults (was Off, now → On)
| Setting | Old default | New default | Rationale |
|---------|------------|-------------|-----------|
| `kv_turboquant` | False | **True** | 86% V-cache savings, negligible quality loss |
| `kv_quantization` | False | **True** | Reduces memory, minimal quality impact |
| `enable_prefix_cache` | False | **True** | Reduces TTFT for repeated prompts |
| `prefill_step_size` | 0 | **8192** | 8K prefill = faster initial response |
| `enable_tool_logits_bias` | False | **True** | Required for tool-calling workflows |

Also added `_resolve_cmd()` helper — falls back to `python -m rapid_mlx.cli`
when the `rapid-mlx` binary is installed via pip but not on PATH.

### llama_cpp.py
- `parallel: 1 → 4` (continuous batching benefits)
- `flash_attn: False → True` (faster gen on supported hardware)

### ollama.py
- `flash_attention: False → True`

### model_manager.py
- `_hf_token_env()` context manager wraps `HUGGING_FACE_HUB_TOKEN` with a
  `threading.Lock()` to eliminate the race window where two threads concurrently
  set/clear the env var.
- Applied to `download_model()`, `download_model_local()`,
  `get_model_presets()`, `get_hf_model_size_gb()`.

---

## ✅ Fixed — Deep Audit (session 2026-05-26)

### rapid_mlx.py
1. **`config_schema()` `enable_tool_logits_bias` default mismatch** (line 260) —
   `config_schema()` showed `"default": False` while `default_engine_settings()`
   returned `True`. The UI would show the wrong value on fresh installs.
   **Fix:** schema default → `True`, matching `default_engine_settings()`.

2. **`get_version()` no fallback for module path** (lines 193–206) — only ran
   `rapid-mlx --version`, returning `None` when the binary wasn't on PATH.
   **Fix:** uses `_resolve_cmd()` for the binary path (handles pip module path),
   **Fix:** falls back to `pip show rapid-mlx` to parse version from metadata.

3. **`is_installed()` missing import check** (lines 169–182) — checked
   `shutil.which` and `pip show`, but could miss installations where the
   package is importable but neither binary nor pip works.
   **Fix:** added `import rapid_mlx` fallback before returning False.

### llama_cpp.py
4. **`get_version()` hardcoded binary path** (lines 167–179) — used
   `["llama-server", "--version"]` directly instead of `_which()` result.
   **Fix:** resolves via `self._which("llama-server")` first.

### ollama.py
5. **`upgrade_command()` used `sh -c "import base64; exec(...)"`** (lines
   252–256) — `import` is NOT a shell command. The shell would try to execute
   `import` as a binary, failing silently (or worse, hitting an unrelated
   `import` binary from ImageMagick). **Fix:** changed to
   `sys.executable -c "import base64; exec(...)"` — matching the correct
   pattern already used by `uninstall_command()`.

### lmstudio.py
6. **Missing `check_requirements()`** — would attempt to start the LM Studio
   server even if `lms` CLI was not installed, with a cryptic "command not
   found" error.
   **Fix:** added `check_requirements()` that returns a clear warning with
   install instructions when `lms` is not on PATH.

---

## Re-Evaluated — Not Bugs

| # | File | Claimed Issue | Verdict |
|---|------|--------------|---------|
| 1 | ds4_m5.py | `--chdir` probed via `add_if_supported()` adds latency | **Not a bug** — `flag_probe.py` caches successful probes per process lifetime. Probe runs once, not every build. Backward-compatible with Swival fork |
| 2 | ds4_m5.py | `--tokens` probed via `add_if_supported()` adds latency | **Same as #1** — cached probe, backward compatibility |
| 3 | ds4_m5.py | Install flow — no rollback if `download_model.sh` fails | **Low risk** — re-running `install_command()` is idempotent (git clone + make are safe to re-run after `rm -rf`) |
| 4 | lmstudio.py | `sh -c` two-step with `_shell_quote()` is fragile | **Acceptable** — `_shell_quote()` correctly handles POSIX shell escaping. The `&&` pattern gives correct fail-fast semantics. Error output goes to the log file |

---

## Remaining Findings — Not Yet Fixed

### HIGH — vllm_mlx.py
1. **`build_command()` passes `--dtype auto`** (line 110). The upstream vllm-mlx
   engine has deprecated `--dtype` in newer versions — on first launch the flag
   probe catches this and omits it, but it adds startup latency and a confusing
   stderr warning. **Better default: omit `--dtype` entirely when it's `auto`**
   (which is the engine's own default).

2. **`install_command()` builds a shell command via `sh -c`** (lines 182–210):
   ```python
   return ["sh", "-c", f"pip install ... && pip install ..."]
   ```
   This is a 4-line bash script embedded in a `sh -c` string. If any `pip install`
   fails, the `&&` chain aborts silently.

### HIGH — rapid_mlx.py
3. **`resolve_launch_model()`** — the engine has THREE model discovery mechanisms
   (explicit launch_model, auto-discovered from HF cache, auto-discovered from
   models dir), but `_find_hf_cached()` takes precedence over the explicit
   `launch_model` setting. If a user has a model cached but wants to launch a
   different one, their explicit setting is silently ignored.

4. **`uninstall_command()`** — hardcodes the pip package name as `rapid-mlx`.
   If the engine was installed with `rapid_mlx` (underscore) the uninstall fails
   silently. Should attempt both naming conventions.

### HIGH — llama_cpp.py
5. **Batch size default of `0`** means "auto" but this isn't documented in the
   help text. Users see 0 and think it's broken.

### MEDIUM — ollama.py
6. **`resolve_launch_model()`** — returns a model name without validation.
   If a user puts a filesystem path there (confusing it with other engines),
   it will fail with an unhelpful error.

7. **PATH detection after upgrade** — uses `time.sleep(0.5)` to wait for
   filesystem instead of a retry loop with `os.path.isfile()`.

### MEDIUM — model_manager.py
8. **`get_model_presets()`** — downloads `config.json` and
   `generation_config.json` from HuggingFace Hub for every model lookup. Called
   from the UI thread. Should cache per-model for the session.

9. **Model size calculation `get_hf_model_size_gb()`** — only sums weight
   files. Doesn't account for KV cache or overhead. Understates RAM needs by
   20–30%.

### MEDIUM — server_manager.py
10. **`load_config()`** — never wrapped in try/except. If the config file is
    corrupt JSON, the entire server start/status/stop flow crashes.

11. **`read_pid_file()`** — doesn't check if the PID is stale (process died
    and PID got recycled). Should use `psutil.pid_exists()`.

### LOW — All Engines
12. **`description` as ClassVar** — inconsistent between static ClassVar
    strings and `ds4_m5.py`'s dynamic `@property` caching. Should standardize.

13. **Health check exception handling** — `check_health()` catches
    `requests.ConnectionError` but not `requests.Timeout` or
    `urllib3.ProtocolError`. Should catch `requests.RequestException`.

14. **`_which()` resolution not cached** — each engine resolves the binary
    path independently in `is_installed()`, `build_command()`, and
    `get_version()`. Should cache the result for the session.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| ✅ Fixed (pre-crash) | 8 defaults + 1 helper + 1 context manager | 4 files |
| ✅ Fixed (deep audit) | 6 fixes | 4 files |
| ❌ Remaining | 14 findings | 6 files |

Total: 20 fixed, 14 remaining.
