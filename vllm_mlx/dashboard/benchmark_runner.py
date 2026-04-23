# SPDX-License-Identifier: Apache-2.0
"""
Benchmark runner for the vllm-mlx dashboard.

Executes vllm-mlx-bench as a subprocess, streams output back to the caller,
and persists results history to ~/.vllm_mlx_ui/benchmark_results.json.
"""

import json
import shutil
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


def run_benchmark(
    model: str,
    prompts: int = 5,
    max_tokens: int = 256,
    is_mllm: bool = False,
    video: bool = False,
    output_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Run vllm-mlx-bench and return a result dict.
    Streams each output line through output_callback if provided.
    """
    _ensure_state_dir()

    binary = shutil.which("vllm-mlx-bench")
    cmd = [binary] if binary else [sys.executable, "-m", "vllm_mlx.benchmark"]

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
