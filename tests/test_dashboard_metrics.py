# SPDX-License-Identifier: Apache-2.0
"""Tests for dashboard live metrics (Tier 1b: RequestMetricsTracker)."""

from __future__ import annotations

import time

import pytest

from vllm_mlx.dashboard.mgmt_server import (
    _RECENT_REQUESTS,
    _RECENT_REQUESTS_LOCK,
    _MAX_RECENT,
    _get_live_metrics,
    _record_request,
)


@pytest.fixture(autouse=True)
def _reset_tracker():
    """Clear the global ring buffer before each test."""
    with _RECENT_REQUESTS_LOCK:
        _RECENT_REQUESTS.clear()
    yield


def test_empty_returns_nulls():
    result = _get_live_metrics()
    assert result["ttft_ms_avg"] is None
    assert result["tps_avg"] is None
    assert result["requests_window"] == 0
    assert result["requests_total"] == 0


def test_single_request():
    _record_request(start=time.time() - 10, ttft=0.5, duration=5.0, completion_tokens=100, model="test-model")
    result = _get_live_metrics()
    assert result["requests_window"] == 1
    assert result["requests_total"] == 1
    assert result["ttft_ms_avg"] == 500.0
    assert result["ttft_ms_p50"] == 500.0
    assert result["ttft_ms_p95"] is None  # need >= 20 samples
    assert result["tps_avg"] == pytest.approx(20.0, rel=0.1)
    assert result["tps_p50"] == pytest.approx(20.0, rel=0.1)


def test_ttft_none_when_no_first_byte():
    _record_request(start=time.time() - 10, ttft=None, duration=5.0, completion_tokens=100, model="test-model")
    result = _get_live_metrics()
    assert result["ttft_ms_avg"] is None
    assert result["requests_window"] == 1


def test_multiple_requests_p50():
    for i in range(5):
        _record_request(start=time.time() - i, ttft=0.1 * (i + 1), duration=2.0, completion_tokens=50, model="m")
    result = _get_live_metrics()
    assert result["requests_window"] == 5
    assert result["ttft_ms_p50"] == 300.0  # middle of [100, 200, 300, 400, 500]


def test_ttft_p95_requires_20():
    for i in range(19):
        _record_request(start=time.time() - i, ttft=0.1, duration=1.0, completion_tokens=10, model="m")
    result = _get_live_metrics()
    assert result["ttft_ms_p95"] is None
    # Add one more to cross the threshold
    _record_request(start=time.time(), ttft=0.1, duration=1.0, completion_tokens=10, model="m")
    result = _get_live_metrics()
    assert result["ttft_ms_p95"] is not None


def test_max_entries_trimmed():
    overflow = _MAX_RECENT + 50
    for i in range(overflow):
        _record_request(start=time.time() - i, ttft=0.1, duration=1.0, completion_tokens=10, model="m")
    with _RECENT_REQUESTS_LOCK:
        assert len(_RECENT_REQUESTS) <= _MAX_RECENT


def test_sliding_window_expiry(monkeypatch):
    times = [100.0, 100.0, 500.0]
    monkeypatch.setattr("vllm_mlx.dashboard.mgmt_server.time.time", lambda: times.pop(0))
    _record_request(start=0, ttft=0.1, duration=1.0, completion_tokens=10, model="a")
    _record_request(start=0, ttft=0.2, duration=2.0, completion_tokens=50, model="b")
    result = _get_live_metrics()
    assert result["requests_window"] == 0  # both expired (ts=100, now=500 => diff=400 > 300)
    assert result["requests_total"] == 2


def test_zero_duration_skipped_from_tps():
    _record_request(start=time.time() - 5, ttft=0.1, duration=0.0, completion_tokens=10, model="m")
    result = _get_live_metrics()
    assert result["requests_window"] == 1
    assert result["tps_avg"] is None  # skipped because duration is 0


def test_zero_tokens_skipped_from_tps():
    _record_request(start=time.time() - 5, ttft=0.1, duration=2.0, completion_tokens=0, model="m")
    result = _get_live_metrics()
    assert result["requests_window"] == 1
    assert result["tps_avg"] is None


def test_thread_safety():
    import threading
    errors = []

    def writer(n):
        try:
            for _ in range(n):
                _record_request(start=time.time(), ttft=0.1, duration=1.0, completion_tokens=10, model="t")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(50,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    result = _get_live_metrics()
    assert result["requests_total"] == 200


# ── Pre-warm (Tier 1c) ────────────────────────────────────────────────────


def test_fire_warmup_skips_when_not_healthy(monkeypatch):
    from vllm_mlx.dashboard.mgmt_server import _fire_warmup
    monkeypatch.setattr("vllm_mlx.dashboard.server_manager.get_server_status", lambda: {"healthy": False})
    posts = []

    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kw):
            posts.append((url, kw))

    monkeypatch.setattr("vllm_mlx.dashboard.mgmt_server._httpx", type("h", (), {"Client": FakeClient})())
    _fire_warmup()
    assert len(posts) == 0


def test_fire_warmup_sends_request(monkeypatch):
    from vllm_mlx.dashboard.mgmt_server import _fire_warmup
    monkeypatch.setattr("vllm_mlx.dashboard.server_manager.get_server_status", lambda: {"healthy": True})
    monkeypatch.setattr("vllm_mlx.dashboard.server_manager.load_config", lambda: {
        "port": 8080, "host": "127.0.0.1", "model": "test/model",
    })
    posts = []

    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kw):
            posts.append((url, kw))
            return type("r", (), {"status_code": 200, "raise_for_status": lambda: None})()

    monkeypatch.setattr("vllm_mlx.dashboard.mgmt_server._httpx", type("h", (), {"Client": FakeClient})())
    _fire_warmup()
    assert len(posts) == 1
    url, kwargs = posts[0]
    assert url == "http://127.0.0.1:8080/v1/chat/completions"
    assert kwargs["json"]["model"] == "test/model"
    assert kwargs["json"]["max_tokens"] == 1
    assert kwargs["json"]["stream"] is False
