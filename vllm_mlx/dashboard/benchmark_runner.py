# SPDX-License-Identifier: Apache-2.0
"""
Benchmark runner for the vllm-mlx dashboard.

Executes vllm-mlx-bench as a subprocess, streams output back to the caller,
and persists results history to ~/.vllm_mlx_ui/benchmark_results.json.
"""

import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

STATE_DIR = Path.home() / ".vllm_mlx_ui"
RESULTS_FILE = STATE_DIR / "benchmark_results.json"


def _ensure_state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def load_results() -> list[dict[str, Any]]:
    """Load all persisted benchmark results from disk.

    Returns:
        List of result dicts, or an empty list if the file is missing or corrupt.
    """
    if not RESULTS_FILE.exists():
        return []
    try:
        with open(RESULTS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_result(result: dict[str, Any]) -> None:
    """Append a benchmark result dict to the persisted results file.

    Args:
        result: A benchmark result dict to append.
    """
    _ensure_state_dir()
    results = load_results()
    results.append(result)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def delete_result(index: int) -> None:
    """Remove a benchmark result by its list index and persist the change.

    Args:
        index: Zero-based index into the results list. Out-of-range values are
            silently ignored.
    """
    results = load_results()
    if 0 <= index < len(results):
        results.pop(index)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2)


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
        pass
    return None


def get_available_memory_gb() -> tuple[float, float]:
    """Return (available_gb, total_gb) of system unified memory."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.available / (1024 ** 3), vm.total / (1024 ** 3)
    except Exception:
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
        pass
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

    output_file = STATE_DIR / f"bench_{int(time.time())}.json"
    cmd += [
        "--model", model,
        "--prompts", str(prompts),
        "--max-tokens", str(max_tokens),
        "--output", str(output_file),
    ]
    if is_mllm:
        cmd += ["--mllm"]
    if video:
        cmd += ["--video"]

    output_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            output_lines.append(line)
            if output_callback:
                output_callback(line)
        proc.wait()
        success = proc.returncode == 0
    except Exception as e:
        success = False
        output_lines.append(f"Error: {e}\n")

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

    # Try to parse the JSON output file written by vllm-mlx-bench --output
    if output_file.exists():
        try:
            with open(output_file) as f:
                data = json.load(f)
            data.setdefault("model", model)
            data["timestamp"] = datetime.now().isoformat()
            data["prompts"] = prompts
            data["max_tokens"] = max_tokens
            data["success"] = success
            if is_oom:
                data["error"] = "out_of_memory"
            save_result(data)
            return data
        except Exception:
            pass

    # Fallback — store raw output for debugging
    result: dict[str, Any] = {
        "model": model,
        "timestamp": datetime.now().isoformat(),
        "prompts": prompts,
        "max_tokens": max_tokens,
        "success": success,
        "raw_output": raw_output,
    }
    if is_oom:
        result["error"] = "out_of_memory"
    save_result(result)
    return result


def run_custom_benchmark(
    model_id: str,
    custom_prompts: list[str],
    server_url: str = "http://127.0.0.1:8000",
    max_tokens: int = 512,
    output_callback: Callable[[str], None] | None = None,
    label: str = "",
    stop_event: Any | None = None,
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
            "model": model_id,
            "timestamp": datetime.utcnow().isoformat(),
            "benchmark_type": "custom",
            "custom_prompts": custom_prompts,
            "max_tokens": max_tokens,
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
        completion_tokens: int | None = None
        content_buffer = ""

        try:
            resp = _req.post(
                f"{server_url}/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "stream": True,
                    "temperature": 0.0,
                    "stream_options": {"include_usage": True},
                },
                stream=True,
                timeout=300,
            )
            resp.raise_for_status()

            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                usage = data.get("usage") or {}
                if usage.get("completion_tokens"):
                    completion_tokens = int(usage["completion_tokens"])
                choices = data.get("choices") or []
                delta = choices[0].get("delta", {}) if choices else {}
                # Accept reasoning_content (thinking tokens from Qwen3 etc.) as valid
                # output — otherwise thinking can exhaust max_tokens with no delta.content.
                content = delta.get("content") or delta.get("reasoning_content") or ""
                if content:
                    now = time.monotonic()
                    if first_token_time is None:
                        first_token_time = now
                    last_content_time = now
                    char_count += len(content)
                    content_buffer += content

            if first_token_time is not None and char_count > 0:
                ttft_ms = round((first_token_time - start) * 1000, 1)
                total_ms = round((last_content_time - start) * 1000, 1) if last_content_time else ttft_ms
                actual_tokens = completion_tokens if completion_tokens else max(1, char_count // 4)
                gen_time = (last_content_time - first_token_time) if last_content_time else 0.0

                tps: float | None = None
                if gen_time >= 0.1 or actual_tokens <= 5:
                    tps = round(actual_tokens / gen_time, 1) if gen_time > 0.01 else None

                row: dict[str, Any] = {
                    "prompt": prompt,
                    "ttft_ms": ttft_ms,
                    "tps": tps,
                    "total_ms": total_ms,
                    "tokens": actual_tokens,
                    "buffered": tps is None and actual_tokens > 5,
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
        "model": model_id,
        "timestamp": datetime.utcnow().isoformat(),
        "benchmark_type": "custom",
        "custom_prompts": custom_prompts,
        "max_tokens": max_tokens,
        "success": len(valid) > 0,
        "per_prompt": per_prompt,
        "avg_tps": round(statistics.mean(tps_vals), 2) if tps_vals else None,
        "avg_ttft_ms": round(statistics.mean(ttft_vals), 1) if ttft_vals else None,
        "avg_total_ms": round(statistics.mean(total_vals), 1) if total_vals else None,
        "raw_output": "\n".join(raw_lines),
        "label": label,
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
    prompts: int = 3,
    max_tokens: int = 256,
    output_callback: Callable[[str], None] | None = None,
    label: str = "",
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

    tps_list: list[float] = []
    ttft_list: list[float] = []
    raw_lines: list[str] = []

    # Verify the server is running
    try:
        health = _req.get(f"{server_url}/health", timeout=5)
        if health.status_code != 200:
            raise RuntimeError("Inference server not responding")
    except Exception as e:
        result: dict[str, Any] = {
            "model": model_id,
            "timestamp": datetime.utcnow().isoformat(),
            "prompts": prompts,
            "max_tokens": max_tokens,
            "success": False,
            "error": f"Server not reachable: {e}",
            "raw_output": str(e),
        }
        save_result(result)
        return result

    for i in range(prompts):
        prompt = _TEST_PROMPTS[i % len(_TEST_PROMPTS)]
        if output_callback:
            output_callback(f"\n[{i+1}/{prompts}] {prompt[:60]}...\n")

        start = time.monotonic()
        first_token_time: float | None = None
        last_content_time: float | None = None
        char_count = 0          # sum of content char lengths for token estimation
        completion_tokens: int | None = None   # from server usage field (preferred)
        content_buffer = ""

        try:
            resp = _req.post(
                f"{server_url}/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "stream": True,
                    "temperature": 0.0,
                    # Ask the server to include token usage in the final chunk
                    "stream_options": {"include_usage": True},
                },
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                # Capture server-reported token counts when available
                usage = data.get("usage") or {}
                if usage.get("completion_tokens"):
                    completion_tokens = int(usage["completion_tokens"])
                choices = data.get("choices") or []
                delta = choices[0].get("delta", {}) if choices else {}
                # Accept reasoning_content (thinking tokens from Qwen3 etc.) as valid
                # output — otherwise thinking can exhaust max_tokens with no delta.content.
                content = delta.get("content") or delta.get("reasoning_content") or ""
                if content:
                    now = time.monotonic()
                    if first_token_time is None:
                        first_token_time = now
                    last_content_time = now
                    char_count += len(content)
                    content_buffer += content

            if first_token_time is not None and char_count > 0:
                ttft = first_token_time - start
                # Use server's completion_tokens if available; else estimate
                # at 4 chars/token (better than word-splitting).
                actual_tokens = completion_tokens if completion_tokens else max(1, char_count // 4)
                gen_time = (last_content_time - first_token_time) if last_content_time else 0.0

                # Sanity check: if all tokens arrived in under 100 ms the
                # server buffered the entire response before streaming it —
                # gen_time is meaningless.  Keep TTFT but skip TPS.
                if gen_time < 0.1 and actual_tokens > 5:
                    ttft_list.append(ttft)
                    raw_lines.append(
                        f"Run {i+1}: TPS skipped (buffered stream), "
                        f"TTFT {ttft*1000:.0f}ms, {actual_tokens} tokens"
                    )
                    if output_callback:
                        output_callback(
                            f"  → TPS skipped (server buffered response), "
                            f"TTFT {ttft*1000:.0f}ms\n"
                        )
                else:
                    tps = actual_tokens / gen_time if gen_time > 0.01 else 0
                    ttft_list.append(ttft)
                    tps_list.append(tps)
                    raw_lines.append(
                        f"Run {i+1}: {tps:.1f} tok/s, TTFT {ttft*1000:.0f}ms, {actual_tokens} tokens"
                    )
                    if output_callback:
                        output_callback(f"  → {tps:.1f} tok/s (TTFT {ttft*1000:.0f}ms)\n")
        except Exception as e:
            raw_lines.append(f"Run {i+1} error: {e}")
            if output_callback:
                output_callback(f"  Error: {e}\n")

    success = len(tps_list) > 0
    avg_tps = statistics.mean(tps_list) if tps_list else 0.0
    median_tps = statistics.median(tps_list) if tps_list else 0.0
    min_tps = min(tps_list) if tps_list else 0.0
    max_tps = max(tps_list) if tps_list else 0.0
    avg_ttft_ms = statistics.mean(ttft_list) * 1000 if ttft_list else 0.0

    result = {
        "model": model_id,
        "timestamp": datetime.utcnow().isoformat(),
        "prompts": prompts,
        "max_tokens": max_tokens,
        "success": success,
        "avg_tps": round(avg_tps, 2),
        "median_tps": round(median_tps, 2),
        "min_tps": round(min_tps, 2),
        "max_tps": round(max_tps, 2),
        "avg_ttft_ms": round(avg_ttft_ms, 1),
        "raw_output": "\n".join(raw_lines),
        "live": True,  # flag to distinguish from subprocess benchmark
        "label": label,
    }
    if not success:
        result["error"] = "No successful runs completed"

    save_result(result)
    return result
