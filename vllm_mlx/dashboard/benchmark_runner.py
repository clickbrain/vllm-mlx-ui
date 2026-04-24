# SPDX-License-Identifier: Apache-2.0
"""
Benchmark runner for the vllm-mlx dashboard.

Executes vllm-mlx-bench as a subprocess, streams output back to the caller,
and persists results history to ~/.vllm_mlx_ui/benchmark_results.json.
"""

import json
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
    if not RESULTS_FILE.exists():
        return []
    try:
        with open(RESULTS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_result(result: dict[str, Any]) -> None:
    _ensure_state_dir()
    results = load_results()
    results.append(result)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def delete_result(index: int) -> None:
    results = load_results()
    if 0 <= index < len(results):
        results.pop(index)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2)


def clear_all_results() -> None:
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
