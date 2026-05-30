# SPDX-License-Identifier: Apache-2.0
"""Diffusion model inference server for Dream-architecture models.

A lightweight FastAPI server that loads Dream-architecture diffusion language
models (e.g. DiffuCoder) and exposes an OpenAI-compatible API endpoint.
Launched as a subprocess by DiffusionMlxEngine.

Diffusion generation is bidirectional: all output tokens are refined in
parallel across N denoising steps. This means there is no per-token stream
— the model produces nothing until the final denoising step completes.
The server simulates SSE streaming by sending the full response as a single
chunk immediately when generation finishes.

Usage (launched by the engine adapter, not directly):
    python -m vllm_mlx.dashboard.diffusion_server \\
        --model mlx-community/DiffuCoder-7B-cpGRPO-8bit \\
        --port 8511

Requires mlx-lm with Dream support (mlx-lm PR #270 or later release).
Install: pip install "git+https://github.com/Goekdeniz-Guelmez/mlx-lm@adding-DiffuCoder"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
_default_steps: int = 256
_default_temperature: float = 0.4
_default_alg: str = "entropy"

app = FastAPI(title="DiffusionMLX", version="0.1.0")


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
    # Diffusion-specific (passed as extra fields by informed clients)
    steps: int | None = None
    alg: str | None = None


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


def _clean_response_text(text: str) -> str:
    """Strip special tokens and pad tokens from the generated text."""
    for token in ("<|dlm_pad|>", "<|im_end|>", "<|endoftext|>"):
        text = text.split(token)[0]
    return text.strip()


def _run_generation(request: ChatCompletionRequest) -> tuple[str, int, float]:
    """Run diffusion generation. Returns (text, token_count, tps)."""
    try:
        from mlx_lm.generate_diffusion import DreamGenerationConfig, stream_diffusion_generate
    except ImportError as exc:
        raise RuntimeError(
            "Dream model support not found in mlx-lm. "
            "Install with: pip install 'git+https://github.com/Goekdeniz-Guelmez/mlx-lm@adding-DiffuCoder'"
        ) from exc

    prompt = _build_prompt(request.messages, _tokenizer)
    steps = request.steps or _default_steps
    temperature = request.temperature if request.temperature is not None else _default_temperature
    alg = request.alg or _default_alg
    max_new_tokens = request.max_tokens or 256

    cfg = DreamGenerationConfig(
        steps=steps,
        temperature=temperature,
        alg=alg,
        max_new_tokens=max_new_tokens,
    )

    logger.info(
        "Diffusion generate: steps=%d alg=%s temperature=%.2f max_new_tokens=%d",
        steps, alg, temperature, max_new_tokens,
    )
    t0 = time.perf_counter()

    final_response = None
    for response in stream_diffusion_generate(_model, _tokenizer, prompt, generation_config=cfg):
        final_response = response

    elapsed = time.perf_counter() - t0

    if final_response is None:
        return "", 0, 0.0

    text = _clean_response_text(final_response.text)
    tokens = getattr(final_response, "generation_tokens", len(text.split()))
    tps = tokens / elapsed if elapsed > 0 else 0.0
    logger.info("Generation done: %d tokens in %.2fs (%.1f tok/s)", tokens, elapsed, tps)
    return text, tokens, tps


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
        loop = asyncio.get_event_loop()
        text, token_count, tps = await loop.run_in_executor(None, _run_generation, request)
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
            "prompt_tokens": 0,
            "completion_tokens": token_count,
            "total_tokens": token_count,
        },
        "x_diffusion_tps": round(tps, 1),
    })


# ── Startup ───────────────────────────────────────────────────────────────────

def _load_model(model_id: str) -> None:
    """Load the Dream model into globals. Called once at server startup."""
    global _model, _tokenizer, _model_id

    logger.info("Loading Dream model: %s", model_id)

    try:
        from mlx_lm.generate_diffusion import DreamGenerationConfig  # noqa: F401 — import check
    except ImportError:
        logger.error(
            "Dream model support not found in mlx-lm. "
            "Install the PR branch:\n"
            "  pip install 'git+https://github.com/Goekdeniz-Guelmez/mlx-lm@adding-DiffuCoder'"
        )
        sys.exit(1)

    try:
        from mlx_lm import load
        _model, _tokenizer = load(model_id, trust_remote_code=True)
        _model_id = model_id
        logger.info("Model loaded: %s", model_id)
    except Exception as exc:
        logger.error("Failed to load model %s: %s", model_id, exc, exc_info=True)
        sys.exit(1)


def main() -> None:
    global _default_steps, _default_temperature, _default_alg

    parser = argparse.ArgumentParser(description="Diffusion model inference server")
    parser.add_argument("--model", required=True, help="HuggingFace model ID or local path")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8511, help="Bind port")
    parser.add_argument("--steps", type=int, default=256, help="Denoising steps (default 256)")
    parser.add_argument("--temperature", type=float, default=0.4, help="Sampling temperature")
    parser.add_argument("--alg", default="entropy",
                        choices=["origin", "maskgit_plus", "topk_margin", "entropy"],
                        help="Unmasking algorithm")
    parser.add_argument("--hf-cache", default="", help="HuggingFace cache directory")
    args = parser.parse_args()

    if args.hf_cache:
        os.environ["HF_HUB_CACHE"] = args.hf_cache

    _default_steps = args.steps
    _default_temperature = args.temperature
    _default_alg = args.alg

    _load_model(args.model)

    logger.info("Starting diffusion server on %s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
