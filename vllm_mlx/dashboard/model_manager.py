# SPDX-License-Identifier: Apache-2.0
"""
Model management for the vllm-mlx dashboard.

Provides HuggingFace Hub integration: search models in mlx-community,
list locally cached models, download, and delete.

When remote_mgmt_url is configured in server_manager, model operations
(cached list, download, delete) are routed to the remote machine via the
management API, so models are stored on the server, not on this machine.
"""

import os
from pathlib import Path
from typing import Any, Callable

import requests as _requests


def _mgmt_base() -> str | None:
    """Return the management API base URL if remote mode is active.

    Returns None when the UI session has the connection toggle set to "local".
    """
    try:
        import streamlit as _st
        if _st.session_state.get("connection_mode", "local") == "local":
            return None
    except Exception:
        pass
    from . import server_manager as sm
    cfg = sm._load_local_config()
    url = cfg.get("remote_mgmt_url", "").strip()
    return url.rstrip("/") if url else None


def _mgmt_headers() -> dict[str, str]:
    from . import server_manager as sm
    cfg = sm._load_local_config()
    key = cfg.get("mgmt_api_key", "").strip()
    return {"X-Api-Key": key} if key else {}


def search_mlx_models(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """Search models in the mlx-community org on HuggingFace Hub."""
    from huggingface_hub import HfApi

    api = HfApi()
    try:
        kwargs: dict[str, Any] = dict(
            author="mlx-community",
            search=query if query.strip() else None,
            limit=limit,
            sort="downloads",
        )
        import inspect
        sig = inspect.signature(api.list_models)
        if "direction" in sig.parameters:
            kwargs["direction"] = -1
        if "fetch_config" in sig.parameters:
            kwargs["fetch_config"] = False
        models = list(api.list_models(**kwargs))
        # Sort by downloads descending (fallback if direction unsupported)
        models.sort(key=lambda m: getattr(m, "downloads", 0) or 0, reverse=True)
    except Exception as e:
        return [{"error": str(e)}]

    results = []
    for m in models:
        tags = list(getattr(m, "tags", []) or [])
        results.append(
            {
                "id": m.id,
                "downloads": getattr(m, "downloads", 0) or 0,
                "likes": getattr(m, "likes", 0) or 0,
                "tags": tags,
                "last_modified": str(getattr(m, "lastModified", "") or ""),
            }
        )
    return results


def get_cached_models() -> list[dict[str, Any]]:
    """Return all HuggingFace model repos cached on the server (local or remote).

    Only returns repos that contain actual model weight files (safetensors, npz,
    bin, gguf, etc.) — metadata-only stubs created by config.json prefetches are
    excluded.  Also filters out repos smaller than 50 MB.
    """
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.get(f"{mgmt}/models/cached", headers=_mgmt_headers(), timeout=10)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []
    try:
        from huggingface_hub import scan_cache_dir

        # Extensions that indicate real model weights are present
        WEIGHT_SUFFIXES = {
            ".safetensors", ".bin", ".pt", ".pth", ".gguf",
            ".npz", ".ggml", ".q4_0", ".q4_1", ".q8_0",
        }
        MIN_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB — metadata stubs are always tiny

        cache_info = scan_cache_dir()
        models = []
        for repo in cache_info.repos:
            if repo.repo_type != "model":
                continue
            if repo.size_on_disk < MIN_SIZE_BYTES:
                continue  # metadata-only stub — skip

            # Check that at least one weight file exists in any revision
            has_weights = False
            for rev in repo.revisions:
                for f in rev.files:
                    if Path(f.file_path).suffix.lower() in WEIGHT_SUFFIXES:
                        has_weights = True
                        break
                if has_weights:
                    break
            if not has_weights:
                continue

            models.append(
                {
                    "id": repo.repo_id,
                    "size_gb": round(repo.size_on_disk / (1024**3), 2),
                    "size_bytes": repo.size_on_disk,
                    "revisions": len(list(repo.revisions)),
                    "path": str(repo.repo_path),
                }
            )
        return sorted(models, key=lambda m: m["size_bytes"], reverse=True)
    except Exception:
        return []


def download_model(
    model_id: str,
    hf_token: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Download a model to the server (local or remote) from HuggingFace Hub."""
    mgmt = _mgmt_base()
    if mgmt:
        try:
            payload: dict[str, Any] = {"model_id": model_id, "token": hf_token or ""}
            r = _requests.post(f"{mgmt}/models/download", json=payload,
                               headers=_mgmt_headers(), timeout=15)
            d = r.json()
            return d.get("ok", False), d.get("message", str(r.status_code))
        except Exception as e:
            return False, f"Could not reach management API: {e}"

    if hf_token:
        os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

    try:
        from huggingface_hub import snapshot_download
        local_dir = snapshot_download(
            repo_id=model_id,
            local_files_only=False,
        )
        return True, f"Downloaded to {local_dir}"
    except Exception as e:
        return False, str(e)
    finally:
        if hf_token:
            os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)


def get_download_status(model_id: str) -> dict[str, Any]:
    """Poll remote download status (no-op in local mode)."""
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.get(f"{mgmt}/models/download_status/{model_id}",
                              headers=_mgmt_headers(), timeout=5)
            return r.json() if r.status_code == 200 else {"status": "unknown"}
        except Exception:
            return {"status": "error"}
    return {"status": "local"}


def delete_model(model_id: str) -> tuple[bool, str]:
    """Delete a cached model from the server (local or remote)."""
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.delete(f"{mgmt}/models/{model_id}",
                                 headers=_mgmt_headers(), timeout=15)
            if r.status_code == 200:
                return True, f"Deleted {model_id}"
            return False, f"API error {r.status_code}: {r.text}"
        except Exception as e:
            return False, f"Could not reach management API: {e}"

    try:
        from huggingface_hub import scan_cache_dir

        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == model_id:
                commit_hashes = [rev.commit_hash for rev in repo.revisions]
                strategy = cache_info.delete_revisions(*commit_hashes)
                strategy.execute()
                freed = round(strategy.expected_freed_size / (1024**3), 2)
                return True, f"Deleted {model_id} (freed {freed} GB)"
        return False, f"Model '{model_id}' not found in cache."
    except Exception as e:
        return False, str(e)


def get_cache_total_size() -> float:
    """Return total HuggingFace cache size in GB (on the server)."""
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.get(f"{mgmt}/models/cache_size", headers=_mgmt_headers(), timeout=5)
            return float(r.json().get("size_gb", 0.0))
        except Exception:
            return 0.0
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()
        return round(cache_info.size_on_disk / (1024**3), 2)
    except Exception:
        return 0.0


def get_model_presets(model_id: str, hf_token: str | None = None) -> dict[str, Any]:
    """
    Fetch model config.json from HuggingFace and extract recommended settings.

    Returns a dict with any of: max_tokens, context_length, architecture,
    model_type_hint, is_vision, bits, rope_scaling.
    Empty dict if the card cannot be read.
    """
    import json as _json

    from huggingface_hub import hf_hub_download

    if hf_token:
        os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

    presets: dict[str, Any] = {}
    try:
        config_path = hf_hub_download(
            repo_id=model_id,
            filename="config.json",
            local_files_only=False,
        )
        with open(config_path) as f:
            cfg = _json.load(f)

        # Context / sequence length
        ctx = (
            cfg.get("max_position_embeddings")
            or cfg.get("n_ctx")
            or cfg.get("seq_length")
            or cfg.get("max_sequence_length")
        )
        if ctx and isinstance(ctx, int):
            presets["context_length"] = ctx
            presets["max_tokens"] = min(ctx, 131072)

        # Architecture
        archs = cfg.get("architectures") or []
        if archs:
            presets["architecture"] = archs[0]

        # Model type
        model_type = cfg.get("model_type", "")
        if model_type:
            presets["model_type_hint"] = model_type

        # Rope scaling info
        rope = cfg.get("rope_scaling")
        if rope:
            presets["rope_scaling"] = rope

        # Vision / multimodal detection
        vision_types = {"llava", "idefics", "pali", "qwen2_vl", "pixtral",
                        "gemma3", "gemma4", "internvl", "cogvlm", "phi3_v", "mipha"}
        arch_lower = (archs[0] if archs else "").lower()
        if (
            any(x in model_type.lower() for x in vision_types)
            or any(x in arch_lower for x in {"vision", "llava", "vl", "pixtral"})
            or any(x in model_id.lower() for x in {"-vl-", "-vision", "llava", "idefics", "pixtral"})
        ):
            presets["is_vision"] = True

        # Quantisation bits from model ID
        name_lower = model_id.lower()
        for bits, patterns in {4: ["4bit", "4-bit", "q4"], 8: ["8bit", "8-bit", "q8"],
                                3: ["3bit", "3-bit"], 6: ["6bit", "6-bit"]}.items():
            if any(p in name_lower for p in patterns):
                presets["bits"] = bits
                break

        # Default temperature hint (some model cards embed this in generation_config.json)
        try:
            gen_path = hf_hub_download(
                repo_id=model_id,
                filename="generation_config.json",
                local_files_only=False,
            )
            with open(gen_path) as f:
                gen = _json.load(f)
            temp = gen.get("temperature")
            if temp and isinstance(temp, (int, float)) and 0 < temp <= 2:
                presets["recommended_temperature"] = float(temp)
        except Exception:
            pass

    except Exception:
        pass
    finally:
        if hf_token:
            os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)

    return presets


def get_hf_cache_dir() -> str:
    """Return the HuggingFace cache directory path."""
    hf_home = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    return os.path.join(hf_home, "hub")
