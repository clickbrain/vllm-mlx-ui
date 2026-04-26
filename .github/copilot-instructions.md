# vllm-mlx-ui Copilot Instructions

## ⚠️ CRITICAL: WHO WE ARE — READ THIS FIRST

**This repo is `Clickbrain/vllm-mlx-ui`.**

We are a **dashboard UI and management layer** built ON TOP of inference engines.
We are NOT a fork. We are NOT an inference engine project.

The inference engines (vllm-mlx, llama.cpp, Ollama, etc.) are **upstream packages we install**.
We ALWAYS install them from their upstream repositories. We NEVER modify their source code.

---

## ⛔ THE ABSOLUTE HARD RULE

**NEVER modify any file in `vllm_mlx/` except `vllm_mlx/dashboard/`.**

The entire `vllm_mlx/` package (except `vllm_mlx/dashboard/`) is upstream code from
`waybarrios/vllm-mlx`. It must be treated as a read-only installed dependency.

Specifically, NEVER touch:
- `vllm_mlx/server.py`
- `vllm_mlx/engine/`
- `vllm_mlx/api/`
- `vllm_mlx/paged_cache.py`, `prefix_cache.py`, `ssd_cache.py`
- `vllm_mlx/mcp/`
- `vllm_mlx/models/`
- `vllm_mlx/constrained/`
- `vllm_mlx/reasoning/`
- `vllm_mlx/tool_parsers/`
- Any other `vllm_mlx/` file NOT inside `vllm_mlx/dashboard/`

**If you find a bug in upstream engine code:**
- Do NOT patch it here
- Note it for a PR submission to the upstream project
- Work around it via CLI args or UI settings if possible

**Files we OWN and CAN freely modify:**
- `vllm_mlx/dashboard/` — our management server backend
- `ui/` — Vue 3 dashboard frontend
- `docs/` — documentation
- `tests/` — tests for our dashboard/UI code only
- `scripts/` — build and deploy scripts
- `.github/` — CI and Copilot config

---

## Project Identity

**`Clickbrain/vllm-mlx-ui`** — a cross-platform UI for managing local AI inference.

- Manages one or more inference engines (vllm-mlx, llama.cpp, Ollama, Remote)
- Engines are INSTALLED packages, not our code
- Our value: the dashboard, benchmarking, chat UI, model management, Kilroy Forge integration
- Future product: **Kilroy Forge** — distributed AI inference swarm platform

**Git remotes:**
- `origin` → `https://github.com/clickbrain/vllm-mlx-ui.git` ← our repo
- `upstream` → `https://github.com/waybarrios/vllm-mlx.git` ← pull only, never push, never modify

**Deploy workflow:**
```bash
bash scripts/validate_dashboard.sh
rsync -a --delete /Users/bradn/Documents/dev/vllm-mlx/ /tmp/vllm-mlx-ui-repo/ --exclude='.git'
cd /tmp/vllm-mlx-ui-repo && git add -A && git commit -m "..." && git push
```

---

## Build & Install

```bash
pip install -e ".[dev]"          # development install
pip install -e ".[dev,audio]"    # with audio support
pip install -e ".[dev,vision]"   # with vision/torch support
```

## Testing

```bash
# Default: runs only unit tests (excludes slow and integration markers)
pytest tests/

# Single test file
pytest tests/test_paged_cache.py -v

# Single test function
pytest tests/test_paged_cache.py::test_eviction -v

# Slow tests (require MLX/model loading — Apple Silicon only)
pytest tests/ -m slow --run-slow

# Integration tests (require a running server)
pytest tests/ -m integration --server-url http://localhost:8000

# With coverage
pytest --cov=vllm_mlx tests/
```

Tests split into two groups:
- **Unit tests** (no MLX): `test_mcp_security`, `test_reasoning_parser`, `test_tool_parsers`, `test_api_models`, `test_anthropic_adapter`, etc. — run anywhere.
- **MLX-dependent tests**: `test_llm`, `test_mllm`, `test_server`, `test_paged_cache`, `test_batching`, etc. — require Apple Silicon with MLX.

## Linting & Type Checking

```bash
ruff check vllm_mlx/ tests/ --select E,F,W --ignore E402,E501,E731,F811,F841
black vllm_mlx/ tests/
mypy vllm_mlx/ --ignore-missing-imports
```

CI runs ruff + black on every PR. mypy is `continue-on-error`.

## Architecture

The project is an OpenAI/Anthropic-compatible inference server for Apple Silicon using MLX as the backend.

**Request flow:**
1. `server.py` (FastAPI) — auth, routing, endpoint logic
2. `engine/` — selects Simple or Batched engine based on `--continuous-batching` flag
3. `models/llm.py` or `models/mllm.py` — wraps mlx-lm / mlx-vlm
4. Post-processing: tool call parsing (`tool_parsers/`), reasoning extraction (`reasoning/`), streaming (`api/streaming.py`)

**Two engine modes:**
- `SimpleEngine` (`engine/simple.py`) — direct mlx-lm wrapper, single user, max throughput
- `BatchedEngine` (`engine/batched.py`) — `AsyncEngineCore` with continuous batching, scheduler, multi-user

**Two model types:**
- `LLM` (`models/llm.py`) — text-only via mlx-lm
- `MLLM` (`models/mllm.py`) — multimodal via mlx-vlm (images, video, Gemma 3/4)

Model type is auto-detected at startup via `model_registry.py`.

**Key subsystems:**
- `paged_cache.py` + `prefix_cache.py` — vLLM-style paged KV cache with LRU eviction and prefix sharing
- `scheduler.py` / `mllm_scheduler.py` — request scheduling for batched mode
- `tool_parsers/` — 12+ parsers for different model tool-call formats (hermes, llama, qwen, gemma4, etc.)
- `reasoning/` — parsers for `<think>` tags (qwen3, deepseek_r1, gemma4, harmony)
- `mcp/` — Model Context Protocol client/server integration
- `api/anthropic_adapter.py` — translates Anthropic Messages API → internal format
- `constrained/` — JSON schema-based constrained decoding via lm-format-enforcer
- `audio/` — STT (Whisper) and TTS (Kokoro, Chatterbox, VibeVoice, VoxCPM) via mlx-audio

## Key Conventions

**License header:** Every `.py` source file starts with `# SPDX-License-Identifier: Apache-2.0`.

**Python version target:** 3.10+ (use `list[str] | None` union syntax, not `Optional[list[str]]`).

**Async throughout:** All engine methods (`generate`, `stream_generate`, `chat`, `stream_chat`) are async. New endpoints should be `async def`.

**BaseEngine contract:** Both `SimpleEngine` and `BatchedEngine` implement `BaseEngine` (ABC in `engine/base.py`). New engine capabilities must be added to the ABC first.

**Tool parsers pattern:** Extend `AbstractToolParser` in `tool_parsers/abstract_tool_parser.py`. Register in `tool_parsers/auto_tool_parser.py`.

**Reasoning parsers pattern:** Extend `BaseReasoningParser` in `reasoning/base.py`.

**Pydantic models** for all API request/response types live in `api/models.py` and `api/anthropic_models.py`.

**Slow/integration test markers:** Tag tests that load real models with `@pytest.mark.slow`. Tag tests that need a live server with `@pytest.mark.integration`. Both are skipped by default.

**mlx-audio is optional:** It conflicts with mlx-lm versioning. It lives in `[audio]` optional deps and is imported with try/except guards.

**Gemma 3 context workaround:** The `GEMMA3_SLIDING_WINDOW` env var patches mlx-vlm's RotatingKVCache at runtime. Document env var overrides for model-specific patches.
