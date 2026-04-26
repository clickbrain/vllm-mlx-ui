# Inference Engine Abstraction Architecture

This document describes the current engine system and the design for supporting multiple inference backends beyond MLX.

---

## 1. Current Architecture

### BaseEngine ABC (`engine/base.py`)

`BaseEngine` defines the contract all engines must satisfy:

| Member | Type | Purpose |
|---|---|---|
| `model_name` | `@property` | Identifies the loaded model |
| `is_mllm` | `@property` | True if model supports images/video |
| `tokenizer` | `@property` | Access to the tokenizer |
| `preserve_native_tool_format` | property (r/w) | Whether tool messages stay in native format |
| `start()` | `async` | Load model and initialise resources |
| `stop()` | `async` | Release resources |
| `generate()` | `async` | Non-streaming text generation |
| `stream_generate()` | `async` generator | Streaming text generation |
| `chat()` | `async` | Non-streaming chat completion |
| `stream_chat()` | `async` generator | Streaming chat completion |
| `get_stats()` | sync | Engine metrics (optional override) |
| `get_cache_stats()` | sync | Cache metrics (optional override) |

All generation parameters (`max_tokens`, `temperature`, `top_p`, `stop`, `**kwargs`) are passed through at call time; the engine is stateless between requests.

### SimpleEngine (`engine/simple.py`)

`SimpleEngine` wraps `mlx-lm` / `mlx-vlm` directly with no batching overhead.

- **Best for**: single-user, maximum throughput, low latency
- **Concurrency**: serialised (one request at a time)
- **LLM path**: delegates to `MLXLanguageModel` (`models/llm.py`)
- **MLLM path**: delegates to `MLXMultimodalLM` (`models/mllm.py`)
- **Key features**: SpecPrefill (attention-sparse prefill), native MTP speculative decoding, configurable prefill step size
- **State**: holds a single model object; no scheduler

### BatchedEngine (`engine/batched.py`)

`BatchedEngine` wraps `AsyncEngineCore` (LLM) or `MLLMScheduler` (MLLM) for continuous batching.

- **Best for**: multi-user serving, higher throughput under concurrency
- **Concurrency**: many requests in flight simultaneously via async queue
- **LLM path**: `AsyncEngineCore` with `SchedulerConfig` (paged/prefix KV cache, chunked prefill, MTP, KV quantisation, SSD cache tiering)
- **MLLM path**: `MLLMScheduler` handles vision encoding + batched generation via `MLLMBatchGenerator`; all requests (text-only and multimodal) route through `MLLMScheduler`
- **State**: holds scheduler, engine core, and tokenizer/processor

### How Model Type Is Detected

At startup, `is_mllm_model(model_name)` in `api/utils.py` scans the model name string against `MLLM_PATTERNS` — a list of name fragments that identify known multimodal families (LLaVA, Qwen-VL, Gemma 3/4, Pixtral, InternVL, etc.). The `--mllm` CLI flag can force multimodal mode regardless of the name. Both `SimpleEngine` and `BatchedEngine` record the result as `_is_mllm` at construction time.

### Engine Instantiation (CLI)

`cli.py` calls `server.load_model(...)` with:
- `use_batching=args.continuous_batching` — selects `BatchedEngine` vs `SimpleEngine`
- `force_mllm=args.mllm` — overrides auto-detection
- A fully-populated `SchedulerConfig` when `--continuous-batching` is set

---

## 2. Multi-Engine Vision

The goal is to let vllm-mlx act as a unified OpenAI-compatible front-end that can delegate inference to whichever backend best fits the hardware, model format, and task.

### Proposed Engine Family

| Engine | Backend | Platforms | Model Formats | Notes |
|---|---|---|---|---|
| `MLXEngine` | mlx-lm / mlx-vlm | Apple Silicon | `.safetensors` (HF) | Current engine, renamed/wrapped |
| `LlamaCppEngine` | llama-server subprocess | macOS · Linux · Windows | `.gguf` | CPU + Metal/CUDA/Vulkan offload |
| `OllamaEngine` | Ollama subprocess or HTTP | macOS · Linux · Windows | Any (Ollama pulls) | Manages Ollama lifecycle |
| `RemoteEngine` | HTTP (OpenAI-compatible) | Any (client only) | Any | OpenRouter, remote vLLM, etc. |

Each engine is an independent Python package/module. The `[extras]` in `pyproject.toml` gate the optional dependencies:

```toml
[project.optional-dependencies]
llama-cpp  = ["llama-cpp-python>=0.3"]
ollama     = ["ollama>=0.4"]
# remote needs no extra deps (httpx already required)
```

---

## 3. EngineRegistry Design

`EngineRegistry` is the single entry point for engine selection. It replaces the direct `SimpleEngine`/`BatchedEngine` construction in `server.load_model`.

```python
from dataclasses import dataclass, field
from enum import Enum

class EngineType(str, Enum):
    MLX        = "mlx"
    LLAMA_CPP  = "llama_cpp"
    OLLAMA     = "ollama"
    REMOTE     = "remote"

@dataclass
class EngineInfo:
    engine_type: EngineType
    version: str
    platform: str              # e.g. "darwin-arm64"
    supported_formats: list[str]   # e.g. [".safetensors", ".gguf"]
    supports_vision: bool
    supports_audio: bool
    available: bool
    notes: str = ""

@dataclass
class BenchmarkResult:
    engine_type: EngineType
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    ttft_ms: float             # time-to-first-token
    throughput_tok_s: float
    peak_memory_mb: float
    timestamp: float = field(default_factory=lambda: __import__("time").time())


class EngineRegistry:
    """Auto-selects and manages inference engines."""

    def select_engine(self, model_id: str, task: str) -> "BaseEngine":
        """
        Select best available engine for a model+task combination.

        Selection order: benchmark results (if cached) → format heuristics
        → platform defaults → fallback chain.
        """
        ...

    def list_available_engines(self) -> list[EngineInfo]:
        """Return info for all engines that are installed and runnable."""
        ...

    def install_engine(self, engine_type: EngineType) -> None:
        """
        Download and install an engine binary (e.g. llama-server).

        Raises EngineInstallError if installation fails.
        """
        ...

    def register_benchmark(self, result: BenchmarkResult) -> None:
        """Store a benchmark result for future selection decisions."""
        ...

    def get_benchmark(
        self, engine_type: EngineType, model_id: str
    ) -> BenchmarkResult | None:
        """Retrieve the most recent benchmark for an engine+model pair."""
        ...
```

The registry persists benchmark results to `~/.cache/vllm-mlx/benchmarks.json` so they survive restarts.

---

## 4. Engine Selection Criteria

Selection is evaluated in priority order:

### 4.1 Explicit Override
If the user passes `--engine mlx|llama_cpp|ollama|remote`, use that engine unconditionally.

### 4.2 Cached Benchmark
If a benchmark result exists for `(engine, model_id)`, prefer the engine with the highest `throughput_tok_s` among all available engines that support the task.

### 4.3 Model Format Heuristics

| File / ID Pattern | Preferred Engine |
|---|---|
| Ends with `.gguf` or path contains `gguf` | `LlamaCppEngine` |
| HF repo with `.safetensors` weights | `MLXEngine` (Apple Silicon) or `LlamaCppEngine` (others) |
| `ollama://` prefix | `OllamaEngine` |
| `http://` or `https://` prefix | `RemoteEngine` |

### 4.4 Platform Detection

```python
import platform, sys

def _default_engine_for_platform() -> EngineType:
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return EngineType.MLX        # Apple Silicon: MLX is fastest
    return EngineType.LLAMA_CPP      # Linux / Windows / Intel Mac: llama.cpp
```

### 4.5 Task Requirements

| Task | Required Engine Capability |
|---|---|
| Vision (images/video) | `supports_vision=True` |
| Audio STT/TTS | `supports_audio=True` |
| Embeddings | `supports_embeddings=True` |
| Tool calling | Any (handled in post-processing layer) |
| Reasoning (`<think>`) | Any (handled in post-processing layer) |

### 4.6 Fallback Chain

```
MLXEngine → LlamaCppEngine → OllamaEngine → RemoteEngine → Error
```

Each step is attempted only if the previous engine is not available (`is_available()` returns False) or does not support the requested model/task.

---

## 5. Extended BaseEngine ABC

The following abstract methods would be added to `engine/base.py`:

```python
@abstractmethod
def engine_info(self) -> EngineInfo:
    """
    Return metadata about this engine implementation.

    Must be a classmethod-compatible call (no model loaded required).
    """
    pass

@classmethod
@abstractmethod
def is_available(cls) -> bool:
    """
    Return True if this engine can run on the current machine.

    Checks: binary presence, library import, platform compatibility.
    Must not require a loaded model.
    """
    pass

@abstractmethod
async def supports_model(self, model_id: str) -> bool:
    """
    Return True if this engine can load the given model.

    May inspect local cache, model card, or file extension.
    Must not actually load the model.
    """
    pass

@abstractmethod
async def benchmark(
    self,
    model_id: str,
    prompt: str = "The quick brown fox",
    max_tokens: int = 128,
    runs: int = 3,
) -> BenchmarkResult:
    """
    Run a standardised benchmark for model+engine.

    Returns the median of `runs` measurements.
    """
    pass
```

Additionally, the existing `get_stats()` and `get_cache_stats()` stubs become abstract to ensure all engines expose consistent telemetry.

---

## 6. Integration Path

Adding a new engine must not break the existing MLX path. Follow these steps:

### Step 1 — Implement the engine class

Create `vllm_mlx/engine/<name>.py` implementing `BaseEngine`. Run the existing test suite to ensure no regressions.

```
vllm_mlx/engine/
  base.py          ← add new abstract methods here first
  simple.py        ← existing MLX simple engine (no changes)
  batched.py       ← existing MLX batched engine (no changes)
  llama_cpp.py     ← new
  ollama.py        ← new
  remote.py        ← new
  registry.py      ← new EngineRegistry
```

### Step 2 — Add optional dependency

Add to `pyproject.toml` under `[project.optional-dependencies]`. The engine import must be guarded with `try/except ImportError` so missing deps fail gracefully.

### Step 3 — Register in EngineRegistry

Add `EngineType.<NAME>` to the enum and add a corresponding `_ENGINE_CLASSES` entry in `registry.py`.

### Step 4 — Update CLI

Add `--engine` argument to `cli.py`. When not provided, `EngineRegistry.select_engine()` is used. When provided, the named engine is used directly (with a clear error if not available).

### Step 5 — Smoke test

Add a unit test in `tests/test_engine_registry.py` that mocks `is_available()` and verifies selection logic. No real model loading required.

### Step 6 — Document

Update this file with the new engine's capabilities, format support, and any known limitations.

---

## 7. Model Switching

### 7.1 Current Limitation

A model is loaded once at server start by `server.load_model()`. Changing the model requires a full process restart. There is no API to load or unload models at runtime.

### 7.2 Hot-Swap (same architecture, different weights)

Hot-swap is possible when the tokenizer and model architecture are identical (e.g., swapping between quantisation levels of the same base model).

**Proposed flow:**
1. `POST /v1/models/load` → engine acquires a write lock, loads new weights into the existing model object in-place, releases lock.
2. In-flight requests drain on the old weights before the lock is acquired (or fail with 503 if timeout exceeded).
3. `GET /v1/models/loaded` returns the new model name.

Hot-swap is supported only by `MLXEngine`; `LlamaCppEngine` must restart `llama-server`.

### 7.3 Cold-Swap (different architecture)

Cold-swap requires unloading the current model, freeing Metal/GPU memory, and loading a completely different model. All in-flight requests must complete or be cancelled first.

**Proposed flow:**
1. `POST /v1/models/load` with `{"model": "<new-model>", "mode": "cold"}` (default when hot-swap not possible)
2. Server sets a drain flag: new requests receive 503 `"model switching in progress"`.
3. Server waits for in-flight requests to finish (configurable timeout, default 30 s).
4. `engine.stop()` is called, memory is freed.
5. A new engine is constructed and `engine.start()` is called.
6. Drain flag is cleared; server resumes serving.

### 7.4 Model Management API

```
POST /v1/models/load
  Body: { "model": "<model_id>", "engine": "mlx|llama_cpp|...", "mode": "hot|cold|auto" }
  Returns: { "status": "loading|loaded|error", "model": "...", "engine": "..." }

GET  /v1/models/loaded
  Returns: list of currently loaded models with engine, format, and memory usage

DELETE /v1/models/{model_id}
  Unloads the model and frees resources (cold path only)
```

These endpoints are authenticated (require API key if `--api-key` is set) and rate-limited to prevent rapid churn.
