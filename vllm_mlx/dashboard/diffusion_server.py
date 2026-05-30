# SPDX-License-Identifier: Apache-2.0
"""Diffusion model inference server for Dream-architecture models.

A lightweight FastAPI server that loads Dream-architecture diffusion language
models (e.g. DiffuCoder) and exposes an OpenAI-compatible API endpoint.
Launched as a subprocess by DiffusionMlxEngine.

Uses MacPaw's Fast-dLLM-mlx backend which adds KV-cache reuse and
confidence-threshold parallel token finalization for substantially faster
inference than naive Dream generation (~20 steps ≈ 256 naive steps).

Usage (launched by DiffusionMlxEngine, not directly):
    python /path/to/vllm_mlx/dashboard/diffusion_server.py \
        --model mlx-community/DiffuCoder-7B-cpGRPO-8bit \
        --port 8511

Requires fast-dllm-mlx (installed via DiffusionMlxEngine.install_command()):
    python3.13 -m pip install "git+https://github.com/MacPaw/Fast-dLLM-mlx"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [diffusion-server] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── Globals populated at startup ──────────────────────────────────────────────
_model = None
_tokenizer = None
_model_id: str = ""
_default_steps: int = 24
_default_temperature: float = 0.4
_default_block_length: int = 32
_default_threshold: float = 0.9

app = FastAPI(title="DiffusionMLX", version="0.2.0")


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    # Fast-dLLM specific (passed as extra fields by informed clients)
    steps: int | None = None
    block_length: int | None = None
    threshold: float | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_prompt(messages: list[ChatMessage], tokenizer: Any) -> str:
    """Apply the model's chat template to a list of messages."""
    msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
    try:
        if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
            return tokenizer.apply_chat_template(
                msg_dicts,
                tokenize=False,
                add_generation_prompt=True,
            )
    except Exception as exc:
        logger.warning("apply_chat_template failed, falling back to manual format: %s", exc)

    # Manual Qwen-style fallback (DiffuCoder uses Qwen's chat template)
    parts = []
    for m in messages:
        role = m.role
        if role == "system":
            parts.append(f"<|im_start|>system\n{m.content}<|im_end|>")
        elif role == "user":
            parts.append(f"<|im_start|>user\n{m.content}<|im_end|>")
        elif role == "assistant":
            parts.append(f"<|im_start|>assistant\n{m.content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def _round_up_to_multiple(n: int, m: int) -> int:
    """Round n up to the nearest multiple of m."""
    return math.ceil(n / m) * m


def _run_generation(request: ChatCompletionRequest) -> tuple[str, int, int, float]:
    """Run diffusion generation. Returns (text, prompt_tokens, completion_tokens, tps)."""
    try:
        from fast_dllm_mlx import DreamGenerationConfig, stream_diffusion_generate
    except ImportError as exc:
        raise RuntimeError(
            "fast-dllm-mlx not found. "
            "Install with: pip install 'git+https://github.com/MacPaw/Fast-dLLM-mlx'"
        ) from exc

    prompt = _build_prompt(request.messages, _tokenizer)
    steps = request.steps or _default_steps
    temperature = request.temperature if request.temperature is not None else _default_temperature
    block_length = request.block_length or _default_block_length
    threshold = request.threshold if request.threshold is not None else _default_threshold
    max_new_tokens_raw = request.max_tokens or 256

    # Fast-dLLM requires max_new_tokens to be a multiple of block_length.
    # Round up; also ensure steps is divisible by num_blocks.
    max_new_tokens = _round_up_to_multiple(max_new_tokens_raw, block_length)
    num_blocks = max_new_tokens // block_length
    # Round steps up to the nearest multiple of num_blocks.
    steps = _round_up_to_multiple(steps, num_blocks)

    cfg = DreamGenerationConfig(
        steps=steps,
        temperature=temperature,
        alg="confidence_threshold",
        threshold=threshold,
        block_length=block_length,
        dual_cache=True,
        max_new_tokens=max_new_tokens,
    )

    logger.info(
        "Diffusion generate: steps=%d block_length=%d threshold=%.2f temperature=%.2f "
        "max_new_tokens=%d (requested %d)",
        steps, block_length, threshold, temperature, max_new_tokens, max_new_tokens_raw,
    )
    t0 = time.perf_counter()

    final_response = None
    for response in stream_diffusion_generate(_model, _tokenizer, prompt, generation_config=cfg):
        final_response = response

    elapsed = time.perf_counter() - t0

    if final_response is None:
        return "", 0, 0, 0.0

    text = final_response.text  # fast_dllm_mlx decodes with skip_special_tokens=True
    prompt_tokens = getattr(final_response, "prompt_tokens", 0)
    completion_tokens = getattr(final_response, "generation_tokens", len(text.split()))
    tps = getattr(final_response, "generation_tps", None) or (
        completion_tokens / elapsed if elapsed > 0 else 0.0
    )
    logger.info(
        "Generation done: %d prompt + %d completion tokens in %.2fs (%.1f tok/s)",
        prompt_tokens, completion_tokens, elapsed, tps,
    )
    return text, prompt_tokens, completion_tokens, tps


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": _model_id}


@app.get("/v1/models")
def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": _model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "diffusion-mlx",
                "capabilities": {"diffusion": True},
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, raw_request: Request) -> Any:
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        loop = asyncio.get_running_loop()
        text, prompt_tokens, completion_tokens, tps = await loop.run_in_executor(
            None, _run_generation, request
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if request.stream:
        # Simulate SSE: send full response as a single chunk, then [DONE].
        def _sse() -> Any:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": _model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_sse(), media_type="text/event-stream")

    return JSONResponse({
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": _model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "x_diffusion_tps": round(tps, 1),
    })


# ── Startup ───────────────────────────────────────────────────────────────────

def _load_model(model_id: str) -> None:
    """Load the Dream model into globals. Called once at server startup."""
    global _model, _tokenizer, _model_id

    logger.info("Loading Dream model: %s", model_id)

    try:
        from fast_dllm_mlx import load
    except ImportError:
        logger.error(
            "fast-dllm-mlx not found. Install with:\n"
            "  pip install 'git+https://github.com/MacPaw/Fast-dLLM-mlx'"
        )
        sys.exit(1)

    try:
        _model, _tokenizer = load(model_id)
        _model_id = model_id
        logger.info("Model loaded: %s", model_id)
    except Exception as exc:
        logger.error("Failed to load model %s: %s", model_id, exc, exc_info=True)
        sys.exit(1)


def main() -> None:
    global _default_steps, _default_temperature, _default_block_length, _default_threshold

    parser = argparse.ArgumentParser(description="Diffusion model inference server (Fast-dLLM-mlx)")
    parser.add_argument("--model", required=True, help="HuggingFace model ID or local path")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8511, help="Bind port")
    parser.add_argument("--steps", type=int, default=24, help="Denoising steps (default 24)")
    parser.add_argument("--temperature", type=float, default=0.4, help="Sampling temperature")
    parser.add_argument("--block-length", type=int, default=32,
                        help="Tokens per denoising block (default 32)")
    parser.add_argument("--threshold", type=float, default=0.9,
                        help="Confidence threshold for early token finalization (default 0.9)")
    parser.add_argument("--hf-cache", default="", help="HuggingFace cache directory")
    args = parser.parse_args()

    if args.hf_cache:
        os.environ["HF_HUB_CACHE"] = args.hf_cache

    _default_steps = args.steps
    _default_temperature = args.temperature
    _default_block_length = args.block_length
    _default_threshold = args.threshold

    _load_model(args.model)

    logger.info("Starting diffusion server on %s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
