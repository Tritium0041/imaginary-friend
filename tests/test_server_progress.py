"""Web 进度事件测试。"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api import server


def test_build_progress_event_clamps_percent():
    event = server._build_progress_event(
        scope="action",
        stage="testing",
        message="x",
        percent=140,
    )
    assert event["percent"] == 100

    event = server._build_progress_event(
        scope="action",
        stage="testing",
        message="x",
        percent=-1,
    )
    assert event["percent"] == 0


def test_context_metrics_include_api_usage_when_available():
    runtime = SimpleNamespace(
        gm=SimpleNamespace(
            session=SimpleNamespace(
                messages=[
                    SimpleNamespace(role="user", name=None, content="请开始"),
                    SimpleNamespace(role="assistant", name=None, content="好的"),
                ],
                api_request_count=3,
                api_input_tokens=400,
                api_output_tokens=120,
                api_cache_creation_input_tokens=70,
                api_cache_read_input_tokens=25,
            ),
            config=SimpleNamespace(max_tokens=4096),
        )
    )

    metrics = server._build_context_metrics(runtime)
    assert metrics["api_request_count"] == 3
    assert metrics["api_input_tokens"] == 400
    assert metrics["api_output_tokens"] == 120
    assert metrics["api_total_tokens"] == 520
    assert metrics["api_cache_creation_input_tokens"] == 70
    assert metrics["api_cache_read_input_tokens"] == 25
    assert metrics["estimated_tokens"] >= 0


def test_context_metrics_default_api_usage_to_zero():
    runtime = SimpleNamespace(
        gm=SimpleNamespace(
            session=SimpleNamespace(
                messages=[SimpleNamespace(role="user", name=None, content="hello")]
            ),
            config=SimpleNamespace(max_tokens=2048),
        )
    )

    metrics = server._build_context_metrics(runtime)
    assert metrics["api_request_count"] == 0
    assert metrics["api_input_tokens"] == 0
    assert metrics["api_output_tokens"] == 0
    assert metrics["api_total_tokens"] == 0
    assert metrics["api_cache_creation_input_tokens"] == 0
    assert metrics["api_cache_read_input_tokens"] == 0
