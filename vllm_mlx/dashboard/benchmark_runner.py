# SPDX-License-Identifier: Apache-2.0
"""
Benchmark runner for the vllm-mlx dashboard.

Executes vllm-mlx-bench as a subprocess, streams output back to the caller,
and persists results history to ~/.vllm_mlx_ui/benchmark_results.json.
"""

import contextlib
import json
import logging
import statistics
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from vllm_mlx.dashboard.hardware import fingerprint as _hw_fingerprint

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".vllm_mlx_ui"
RESULTS_FILE = STATE_DIR / "benchmark_results.json"
_SCHEMA_VERSION = 2
_save_lock = threading.RLock()
_RESULT_RETENTION_DAYS = 90


def _ensure_state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def _prune_old_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove results older than ``_RESULT_RETENTION_DAYS`` from the list."""
    cutoff = datetime.now(timezone.utc).timestamp() - _RESULT_RETENTION_DAYS * 86400
    kept: list[dict[str, Any]] = []
    for r in results:
        ts = r.get("timestamp")
        if ts:
            try:
                parsed = datetime.fromisoformat(ts).timestamp()
                if parsed < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
        kept.append(r)
    return kept


def load_results() -> list[dict[str, Any]]:
    """Load all persisted benchmark results from disk.

    Thread-safe: acquires ``_save_lock``.  Callers that already hold the lock
    (``save_result``, ``delete_result``) may call this without deadlock since
    the lock is reentrant (``RLock``).

    Returns:
        List of result dicts, or an empty list if the file is missing or corrupt.
    """
    with _save_lock:
        if not RESULTS_FILE.exists():
            return []
        try:
            with open(RESULTS_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            return []


def save_result(result: dict[str, Any]) -> None:
    """Append a benchmark result dict to the persisted results file.

    Uses a threading lock and atomic rename (write to .tmp then replace) to
    prevent data loss when two benchmark threads finish simultaneously.

    Args:
        result: A benchmark result dict to append.
    """
    _ensure_state_dir()
    with _save_lock:
        results = load_results()
        results = _prune_old_results(results)
        results.append(result)
        tmp = RESULTS_FILE.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(results, f, indent=2)
            tmp.replace(RESULTS_FILE)
        except Exception:
            with contextlib.suppress(Exception):
                tmp.unlink()
            raise


def delete_result(index: int) -> None:
    """Remove a benchmark result by its list index and persist the change.

    Args:
        index: Zero-based index into the results list. Out-of-range values are
            silently ignored.
    """
    with _save_lock:
        results = load_results()
        if 0 <= index < len(results):
            results.pop(index)
            tmp = RESULTS_FILE.with_suffix(".tmp")
            try:
                with open(tmp, "w") as f:
                    json.dump(results, f, indent=2)
                tmp.replace(RESULTS_FILE)
            except Exception:
                with contextlib.suppress(Exception):
                    tmp.unlink()
                raise


def clear_all_results() -> None:
    """Delete the entire benchmark results file from disk."""
    if RESULTS_FILE.exists():
        RESULTS_FILE.unlink()


def estimate_model_memory(model_id: str) -> float | None:
    """Return estimated model memory requirement in GB, or None if unknown."""
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == model_id and repo.repo_type == "model":
                return repo.size_on_disk / (1024 ** 3)
    except Exception:
        logger.warning("Operation failed", exc_info=True)
    return None


def get_available_memory_gb() -> tuple[float, float]:
    """Return (available_gb, total_gb) of system unified memory."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.available / (1024 ** 3), vm.total / (1024 ** 3)
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return 0.0, 0.0


def pre_flight_check(
    model_id: str,
    safety_margin: float = 0.80,
) -> dict:
    """
    Check if the model is likely to fit in memory before running.

    Returns a dict with keys:
      - will_fit: bool | None (None = unknown)
      - model_gb: float | None
      - available_gb: float
      - total_gb: float
      - warning: str | None   (human-readable warning message, or None)
    """
    model_gb = estimate_model_memory(model_id)
    available_gb, total_gb = get_available_memory_gb()

    if model_gb is None or available_gb == 0.0:
        return {
            "will_fit": None,
            "model_gb": model_gb,
            "available_gb": available_gb,
            "total_gb": total_gb,
            "warning": None,
        }

    # safety_margin=0.80: use at most 80% of available unified memory.
    # The 1.25x multiplier accounts for KV cache + runtime overhead
    # (~25% of model weights is a conservative estimate).
    # Conservative by design — better to warn than to OOM mid-benchmark.
    # Rough heuristic: model weights + ~25% for KV cache / overhead
    required_gb = model_gb * 1.25
    will_fit = required_gb <= available_gb * safety_margin
    warning = None
    if not will_fit:
        warning = (
            f"This model needs ~{required_gb:.1f} GB but only {available_gb:.1f} GB "
            f"of {total_gb:.0f} GB unified memory is available. "
            f"The benchmark will likely crash with an out-of-memory error."
        )
    elif required_gb > available_gb * 0.60:
        warning = (
            f"This model needs ~{required_gb:.1f} GB and {available_gb:.1f} GB is "
            f"available — it will fit but memory is tight. "
            f"Use fewer prompts or lower max tokens to reduce peak usage."
        )

    return {
        "will_fit": will_fit,
        "model_gb": model_gb,
        "available_gb": available_gb,
        "total_gb": total_gb,
        "warning": warning,
    }


def _clear_memory(callback: "Callable[[str], None] | None" = None) -> None:
    """
    Best-effort memory clearing before a benchmark run.
    - Runs Python GC in this process
    - Clears the MLX Metal buffer cache ONLY if MLX is already loaded in this
      process (importing it here would initialize Metal and waste 200-500 MB)
    - Pauses briefly to give macOS time to reclaim memory from recently-stopped processes
    """
    import gc as _gc
    _gc.collect()
    try:
        if "mlx.core" in sys.modules:
            sys.modules["mlx.core"].clear_cache()
    except Exception:
        logger.warning("Failed to clear MLX cache", exc_info=True)
    if callback:
        callback("🧹 Clearing memory before benchmark…\n")
    time.sleep(1.5)


# Preamble runs in the benchmark subprocess BEFORE the benchmark module loads.
# Clearing MLX cache here (not in the parent process) is intentional:
# the clear happens before the model is loaded, so we maximize available VRAM.
# Using -c flag (not a shell script) prevents shell injection and gives precise
# control over the subprocess environment.
# Inline preamble run inside the benchmark subprocess — clears MLX cache before
# the model is loaded, then hands off to the real benchmark module.
_BENCH_PREAMBLE = (
    "import gc; gc.collect();"
    "\ntry:\n import mlx.core as _mx; _mx.clear_cache()\nexcept Exception: pass"
    "\nimport runpy, sys; runpy.run_module('vllm_mlx.benchmark', run_name='__main__', alter_sys=True)"
)


def run_benchmark(
    model: str,
    prompts: int = 3,
    max_tokens: int = 128,
    is_mllm: bool = False,
    video: bool = False,
    output_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Run vllm-mlx-bench and return a result dict.
    Clears memory (GC + MLX cache) before launching. Streams each output line
    through output_callback if provided.
    """
    _ensure_state_dir()

    # Clear memory in the parent process and pause before launching
    _clear_memory(output_callback)

    # Always use sys.executable with the preamble so we can clear the MLX
    # Metal cache inside the subprocess before any model weights are loaded.
    cmd = [sys.executable, "-c", _BENCH_PREAMBLE]

    output_file = STATE_DIR / f"bench_{uuid.uuid4().hex}.json"
    cmd += [
        "--model", model,
        "--prompts", str(prompts),
        "--max-tokens", str(max_tokens),
        "--output", str(output_file),
    ]
    cmd += ["--temperature", "0.0"]
    if is_mllm:
        cmd += ["--mllm"]
    if video:
        cmd += ["--video"]

    output_lines: list[str] = []
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if proc.stdout is None:
            raise RuntimeError("Popen returned None stdout despite PIPE setting")
        for line in proc.stdout:
            output_lines.append(line)
            if output_callback:
                output_callback(line)
        proc.stdout.close()
        proc.wait()
        success = proc.returncode == 0
    except Exception as e:
        success = False
        output_lines.append(f"Error: {e}\n")
        if proc is not None:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass

    raw_output = "".join(output_lines)

    # Metal OOM messages vary across macOS and mlx versions; check multiple
    # patterns to catch all known forms:
    # - Native Metal allocator errors ("Metal", "allocation failed")
    # - mlx allocator exceptions ("MemoryError", "out of memory")
    # - Standard C++ bad_alloc propagated up from Metal ("std::bad_alloc")
    # Detect Metal out-of-memory crash — give a specific error code so the
    # UI can show an actionable message instead of a generic failure.
    _OOM_SIGNALS = (
        "outofmemory",
        "out of memory",
        "insufficient memory",
        "kIOGPUCommandBufferCallbackErrorOutOfMemory",
        "METAL] Command buffer execution failed",
        "std::bad_alloc",
    )
    is_oom = not success and any(
        sig.lower() in raw_output.lower() for sig in _OOM_SIGNALS
    )

    ts = datetime.now(timezone.utc).isoformat()
    try:
        # Try to parse the JSON output file written by vllm-mlx-bench --output
        if output_file.exists():
            try:
                with open(output_file) as f:
                    data = json.load(f)
                data.setdefault("model", model)
                data["timestamp"] = ts
                data["prompts"] = prompts
                data["max_tokens"] = max_tokens
                data["success"] = success
                data["schema_version"] = _SCHEMA_VERSION
                data["result_type"] = "subprocess"
                if is_oom:
                    data["error"] = "out_of_memory"
                save_result(data)
                return data
            except Exception:
                logger.warning("Operation failed", exc_info=True)

        # Fallback — store raw output for debugging
        result: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "result_type": "subprocess",
            "model": model,
            "timestamp": ts,
            "prompts": prompts,
            "max_tokens": max_tokens,
            "success": success,
            "raw_output": raw_output,
        }
        if is_oom:
            result["error"] = "out_of_memory"
        save_result(result)
        return result
    finally:
        with contextlib.suppress(Exception):
            output_file.unlink(missing_ok=True)


def run_custom_benchmark(
    model_id: str,
    custom_prompts: list[str],
    server_url: str = "http://127.0.0.1:8000",
    max_tokens: int = 512,
    output_callback: Callable[[str], None] | None = None,
    label: str = "",
    stop_event: Any | None = None,
    enable_thinking: bool = False,
    server_settings: dict[str, Any] | None = None,
    dashboard_version: str = "",
) -> dict[str, Any]:
    """Run a custom-prompt benchmark against the running inference server.

    Unlike run_live_benchmark(), callers supply the exact prompt list.
    Returns per-prompt metrics: TTFT, tok/s, and total response time.
    """
    import requests as _req

    _ensure_state_dir()

    if output_callback:
        output_callback(f"Running custom benchmark against {server_url}\n")
        output_callback(f"Model: {model_id} · {len(custom_prompts)} prompts · max_tokens {max_tokens}\n\n")

    per_prompt: list[dict[str, Any]] = []
    raw_lines: list[str] = []

    # Verify the server is running
    try:
        health = _req.get(f"{server_url}/health", timeout=5)
        if health.status_code != 200:
            raise RuntimeError("Inference server not responding")
    except Exception as e:
        result: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "result_type": "custom",
            "model": model_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "benchmark_type": "custom",
            "custom_prompts": custom_prompts,
            "max_tokens": max_tokens,
            "enable_thinking": enable_thinking,
            "server_settings": server_settings or {},
            "dashboard_version": dashboard_version,
            "success": False,
            "per_prompt": [],
            "error": f"Server not reachable: {e}",
            "raw_output": str(e),
            "label": label,
        }
        save_result(result)
        return result

    for i, prompt in enumerate(custom_prompts):
        if stop_event and stop_event.is_set():
            break

        short = prompt[:70] + ("…" if len(prompt) > 70 else "")
        if output_callback:
            output_callback(f"[{i+1}/{len(custom_prompts)}] {short}\n")

        start = time.monotonic()
        first_token_time: float | None = None
        last_content_time: float | None = None
        char_count = 0
        content_char_count = 0  # excludes reasoning_content (thinking tokens)
        completion_tokens: int | None = None

        try:

            if first_token_time is not None and char_count > 0:
                ttft_ms = round((first_token_time - start) * 1000, 1)
                total_ms = round((last_content_time - start) * 1000, 1) if last_content_time else ttft_ms
                if completion_tokens:
                    actual_tokens = completion_tokens
                else:
                    # Fallback: use only visible content chars (not thinking tokens) to
                    # avoid inflating TPS when reasoning_content is streamed.
                    fallback_chars = content_char_count if content_char_count else char_count
                    actual_tokens = max(1, round(fallback_chars / 4))
                # Use total wall-clock time (not just streaming window) so tok/s is
                # accurate even when thinking tokens are buffered server-side before
                # any streaming begins.
                total_elapsed = total_ms / 1000.0
                tps: float | None = round(actual_tokens / total_elapsed, 1) if total_elapsed > 0.01 else None

                row: dict[str, Any] = {
                    "prompt": prompt,
                    "ttft_ms": ttft_ms,
                    "tps": tps,
                    "total_ms": total_ms,
                    "tokens": actual_tokens,
                }
                per_prompt.append(row)

                tps_str = f"{tps:.1f} tok/s" if tps is not None else "TPS n/a (buffered)"
                raw_lines.append(
                    f"  TTFT {ttft_ms:.0f}ms · {tps_str} · total {total_ms:.0f}ms · {actual_tokens} tokens"
                )
                if output_callback:
                    output_callback(
                        f"  TTFT {ttft_ms:.0f}ms  |  {tps_str}  |  total {total_ms:.0f}ms  |  {actual_tokens} tokens\n\n"
                    )
            else:
                per_prompt.append({"prompt": prompt, "error": "No response received"})
                raw_lines.append("  (no response)")
                if output_callback:
                    output_callback("  ✗ No response received\n\n")

        except Exception as e:
            per_prompt.append({"prompt": prompt, "error": str(e)})
            raw_lines.append(f"  Error: {e}")
            if output_callback:
                output_callback(f"  ✗ Error: {e}\n\n")

    valid = [r for r in per_prompt if "error" not in r]
    tps_vals = [r["tps"] for r in valid if r.get("tps") is not None]
    ttft_vals = [r["ttft_ms"] for r in valid]
    total_vals = [r["total_ms"] for r in valid]

    result = {
        "schema_version": _SCHEMA_VERSION,
        "result_type": "custom",
        "model": model_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmark_type": "custom",
        "custom_prompts": custom_prompts,
        "max_tokens": max_tokens,
        "enable_thinking": enable_thinking,
        "server_settings": server_settings or {},
        "dashboard_version": dashboard_version,
        "success": len(valid) > 0,
        "per_prompt": per_prompt,
        "avg_tps": round(statistics.mean(tps_vals), 2) if tps_vals else None,
        "avg_ttft_ms": round(statistics.mean(ttft_vals), 1) if ttft_vals else None,
        "avg_total_ms": round(statistics.mean(total_vals), 1) if total_vals else None,
        "raw_output": "\n".join(raw_lines),
        "label": label,
        "hardware": _hw_fingerprint(),
    }
    if not result["success"]:
        result["error"] = "No successful prompts completed"

    save_result(result)
    return result


_TEST_PROMPTS = [
    "Explain the concept of machine learning in simple terms.",
    "Write a short story about a robot learning to paint.",
    "What are the key differences between Python and JavaScript?",
    "Describe the water cycle in three sentences.",
    "What is the Pythagorean theorem and how is it used?",
]


def run_live_benchmark(
    model_id: str,
    server_url: str = "http://127.0.0.1:8000",
    prompts: int = 10,
    max_tokens: int = 256,
    output_callback: Callable[[str], None] | None = None,
    label: str = "",
    stop_event: threading.Event | None = None,
    server_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Benchmark the RUNNING inference server by sending live requests.

    Unlike run_benchmark(), this does not load the model — it uses the already-running
    inference server. Results are stored in the benchmark history.
    """
    import requests as _req

    _ensure_state_dir()

    if output_callback:
        output_callback(f"Running live benchmark against {server_url}...\n")
        output_callback(f"Model: {model_id}\nPrompts: {prompts}\nMax tokens: {max_tokens}\n")

    ttft_list: list[float] = []        # per-run TTFT in milliseconds
    e2e_tps_list: list[float] = []     # per-run e2e TPS (tokens / wall-clock)
    gen_tps_list: list[float] = []     # per-run gen TPS ((tokens-1) / post-first-token)
    raw_lines: list[str] = []

    # Verify the server is running
    try:
        health = _req.get(f"{server_url}/health", timeout=5)
        if health.status_code != 200:
            raise RuntimeError("Inference server not responding")
    except Exception as e:
        result: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "result_type": "live",
            "model": model_id,
            "label": label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompts": prompts,
            "max_tokens": max_tokens,
            "server_settings": server_settings,
            "success": False,
            "error": f"Server not reachable: {e}",
            "raw_output": str(e),
        }
        save_result(result)
        return result

    # Warmup: two throwaway requests to prime KV cache and JIT kernels before measuring
    _WARMUP_PROMPTS = ["Hello!", "What is 2+2?"]
    if output_callback:
        output_callback("[warmup] Running 2 warmup requests (not measured)...\n")
    for wp in _WARMUP_PROMPTS:
        try:
            wr = _req.post(
                f"{server_url}/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": wp}],
                    "max_tokens": 32,
                    "stream": True,
                    "temperature": 0.0,
                },
                stream=True,
                timeout=60,
            )
            for _chunk in wr.iter_lines():
                pass
        except Exception as we:
            logger.warning("Warmup request failed (non-fatal): %s", we)
    if output_callback:
        output_callback("[warmup] done\n")

    for i in range(prompts):
        if stop_event and stop_event.is_set():
            if output_callback:
                output_callback("[stopped] Benchmark interrupted.\n")
            break
        prompt = _TEST_PROMPTS[i % len(_TEST_PROMPTS)]
        if output_callback:
            output_callback(f"\n[{i+1}/{prompts}] {prompt[:60]}...\n")

        start = time.monotonic()
        first_token_time: float | None = None
        last_content_time: float | None = None
        char_count = 0          # sum of content char lengths for token estimation
        content_char_count = 0  # content only (excludes reasoning_content thinking tokens)
        completion_tokens: int | None = None   # from server usage field (preferred)
        finish_reason: str | None = None

        try:

            # Skip truncated responses — they make TPS look artificially high
            if finish_reason == "length":
                raw_lines.append(
                    f"Run {i+1}: skipped (finish_reason=length — response was truncated)"
                )
                if output_callback:
                    output_callback(
                        f"  → skipped: response truncated (hit max_tokens={max_tokens})\n"
                    )
                continue

            if first_token_time is not None and char_count > 0:
                ttft = first_token_time - start
                total_elapsed = (last_content_time or first_token_time) - start
                # Use server's completion_tokens if available; else estimate from
                # visible content chars only (not thinking tokens) at 4 chars/token.
                if completion_tokens:
                    actual_tokens = completion_tokens
                else:
                    fallback_chars = content_char_count if content_char_count else char_count
                    actual_tokens = max(1, round(fallback_chars / 4))
                gen_time = (last_content_time - first_token_time) if last_content_time else 0.0

                # e2e TPS = total tokens / total wall-clock (includes TTFT)
                e2e_tps = actual_tokens / total_elapsed if total_elapsed > 0.01 else 0
                # gen TPS = (tokens - 1) / post-first-token window
                # (the first token is accounted for in TTFT, not generation throughput)
                gen_tps = max(0, actual_tokens - 1) / gen_time if gen_time > 0.1 else 0

                # Sanity check: if all tokens arrived in under 100 ms the
                # server buffered the entire response before streaming it —
                # gen_time is meaningless.  Keep TTFT but skip gen TPS.
                if gen_time < 0.1 and actual_tokens > 5:
                    ttft_list.append(ttft * 1000)
                    raw_lines.append(
                        f"Run {i+1}: gen TPS skipped (buffered stream), "
                        f"TTFT {ttft*1000:.0f}ms, {actual_tokens} tokens"
                    )
                    if output_callback:
                        output_callback(
                            f"  → gen TPS skipped (server buffered response), "
                            f"TTFT {ttft*1000:.0f}ms\n"
                        )
                else:
                    ttft_list.append(ttft * 1000)
                    e2e_tps_list.append(e2e_tps)
                    gen_tps_list.append(gen_tps)
                    raw_lines.append(
                        f"Run {i+1}: e2e {e2e_tps:.1f} tok/s, gen {gen_tps:.1f} tok/s, "
                        f"TTFT {ttft*1000:.0f}ms, {actual_tokens} tokens"
                    )
                    if output_callback:
                        output_callback(
                            f"  → e2e {e2e_tps:.1f} tok/s | gen {gen_tps:.1f} tok/s "
                            f"(TTFT {ttft*1000:.0f}ms)\n"
                        )
        except Exception as e:
            raw_lines.append(f"Run {i+1} error: {e}")
            if output_callback:
                output_callback(f"  Error: {e}\n")

    success = len(ttft_list) > 0
    avg_e2e_tps = statistics.mean(e2e_tps_list) if e2e_tps_list else 0.0
    avg_gen_tps = statistics.mean(gen_tps_list) if gen_tps_list else 0.0
    # avg_tps kept for backward compatibility — equals avg_gen_tps (the more meaningful metric)
    avg_tps = avg_gen_tps
    median_tps = statistics.median(gen_tps_list) if gen_tps_list else 0.0
    min_tps = min(gen_tps_list) if gen_tps_list else 0.0
    max_tps = max(gen_tps_list) if gen_tps_list else 0.0
    avg_ttft_ms = statistics.mean(ttft_list) if ttft_list else 0.0

    result = {
        "schema_version": _SCHEMA_VERSION,
        "result_type": "live",
        "model": model_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts_requested": prompts,
        "prompts_completed": len(ttft_list),
        "max_tokens": max_tokens,
        "success": success,
        "label": label,
        "server_settings": server_settings,
        # Primary metrics
        "avg_gen_tps": round(avg_gen_tps, 2),
        "avg_e2e_tps": round(avg_e2e_tps, 2),
        "avg_ttft_ms": round(avg_ttft_ms, 1),
        # Legacy aliases (kept for backward compatibility with existing UI consumers)
        "avg_tps": round(avg_tps, 2),
        "median_tps": round(median_tps, 2),
        "min_tps": round(min_tps, 2),
        "max_tps": round(max_tps, 2),
        # Raw samples for statistical analysis
        "ttft_samples_ms": [round(v, 1) for v in ttft_list],
        "e2e_tps_samples": [round(v, 2) for v in e2e_tps_list],
        "gen_tps_samples": [round(v, 2) for v in gen_tps_list],
        "raw_output": "\n".join(raw_lines),
        "live": True,  # legacy flag — result_type: "live" is the canonical field
        "hardware": _hw_fingerprint(),
    }
    if not success:
        result["error"] = "No successful runs completed"

    save_result(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Diffusion model benchmarking
# ─────────────────────────────────────────────────────────────────────────────

_DIFFUSION_SERVER_PORT = 8511
_DIFFUSION_SERVER_STARTUP_TIMEOUT = 180  # seconds — model load can be slow


def run_diffusion_benchmark(
    model_id: str,
    prompts: int = 6,
    max_tokens: int = 128,
    output_callback: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
    engine_settings: dict[str, Any] | None = None,
    port: int = _DIFFUSION_SERVER_PORT,
) -> dict[str, Any]:
    """Benchmark a Dream-architecture diffusion model via Fast-dLLM-mlx.

    Starts a temporary diffusion_server.py subprocess for the given model,
    runs run_live_benchmark() against it, then tears the server down.

    Diffusion models do NOT support streaming so TTFT equals full generation
    time.  Use avg_e2e_tps as the primary throughput metric.
    """
    import requests as _req

    es = engine_settings or {}
    steps = int(es.get("steps", 24))
    block_length = int(es.get("block_length", 32))
    threshold = float(es.get("threshold", 0.9))
    temperature = float(es.get("temperature", 0.4))

    server_url = f"http://127.0.0.1:{port}"

    def _cb(msg: str) -> None:
        if output_callback:
            output_callback(msg)

    _cb(f"[diffusion-bench] Starting diffusion server for: {model_id}\n")
    _cb(f"[diffusion-bench] steps={steps} block_length={block_length} threshold={threshold}\n")

    # Reuse an already-running server at this port if it has the right model loaded.
    server_already_running = False
    try:
        resp = _req.get(f"{server_url}/health", timeout=3)
        if resp.status_code == 200:
            loaded_model = resp.json().get("model", "")
            if loaded_model == model_id:
                server_already_running = True
                _cb(f"[diffusion-bench] Reusing existing server at {server_url}\n")
            else:
                _cb(f"[diffusion-bench] Port {port} has different model ({loaded_model}) — starting fresh.\n")
    except Exception:
        pass

    proc: subprocess.Popen | None = None

    try:
        if not server_already_running:
            cmd = [
                sys.executable, "-m", "vllm_mlx.dashboard.diffusion_server",
                "--model", model_id,
                "--port", str(port),
                "--steps", str(steps),
                "--block-length", str(block_length),
                "--threshold", str(threshold),
                "--temperature", str(temperature),
            ]
            _cb(f"[diffusion-bench] Launching: {' '.join(cmd)}\n")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Poll /health until the server is ready.
            deadline = time.monotonic() + _DIFFUSION_SERVER_STARTUP_TIMEOUT
            started = False
            while time.monotonic() < deadline:
                if stop_event and stop_event.is_set():
                    _cb("[diffusion-bench] Stopped while waiting for server startup.\n")
                    return _diffusion_bench_error(model_id, "Stopped before server was ready")
                if proc.poll() is not None:
                    _cb("[diffusion-bench] Server exited early (check system logs for details).\n")
                    return _diffusion_bench_error(model_id, f"Server process exited with code {proc.returncode}")
                try:
                    h = _req.get(f"{server_url}/health", timeout=3)
                    if h.status_code == 200:
                        started = True
                        break
                except Exception:
                    pass
                time.sleep(3)

            if not started:
                _cb("[diffusion-bench] Timeout waiting for server startup.\n")
                return _diffusion_bench_error(model_id, "Server startup timeout")

            _cb("[diffusion-bench] Server ready.\n")

        result = run_live_benchmark(
            model_id=model_id,
            server_url=server_url,
            prompts=prompts,
            max_tokens=max_tokens,
            output_callback=output_callback,
            label="diffusion",
            stop_event=stop_event,
            server_settings={
                "engine_id": "diffusion-mlx",
                "steps": steps,
                "block_length": block_length,
                "threshold": threshold,
                "temperature": temperature,
            },
        )
        return result

    finally:
        if proc is not None and proc.poll() is None:
            _cb("[diffusion-bench] Stopping server...\n")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            _cb("[diffusion-bench] Server stopped.\n")


def _diffusion_bench_error(model_id: str, error: str) -> dict[str, Any]:
    """Return a failed benchmark result dict."""
    result: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "result_type": "live",
        "model": model_id,
        "label": "diffusion",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "error": error,
        "raw_output": error,
    }
    save_result(result)
    return result
