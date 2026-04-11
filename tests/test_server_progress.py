"""Web 进度事件测试。"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api import server
from src.core.doc_store import DocStore


class FakeGMAgent:
    """避免外部模型调用的测试替身。"""

    def __init__(self, rules_md="", metadata=None, config=None, on_output=None, api_key=None, base_url=None):
        self.config = config
        self.on_output = on_output or (lambda _msg: None)
        self.api_key = api_key
        self.base_url = base_url
        self.rules_md = rules_md
        self.metadata = metadata or {}
        self.session = None
        self.doc_store = DocStore()

    def start_game(self, player_names, game_id=None):
        gid = game_id or "progress01"
        self.session = SimpleNamespace(
            game_id=gid,
            is_waiting_for_human=True,
            messages=[],
            api_request_count=0,
            api_input_tokens=0,
            api_output_tokens=0,
            api_cache_creation_input_tokens=0,
            api_cache_read_input_tokens=0,
            player_info={
                "player_0": {"name": "测试玩家", "is_human": True},
                "player_1": {"name": "AI玩家1", "is_human": False},
                "player_2": {"name": "AI玩家2", "is_human": False},
            },
        )
        # Initialize DocStore with some test data
        self.doc_store.insert("global", {"_id": "global_state", "current_round": 1, "current_phase": "setup"})
        self.doc_store.insert("players", {
            "_id": "player_0", "name": "测试玩家", "gold": 20, "vp": 0,
            "hand": [{"id": "c1", "name": "Fake Card", "description": "desc", "effect": "effect"}],
            "artifacts": [],
        })
        self.doc_store.insert("players", {"_id": "player_1", "name": "AI玩家1", "gold": 20, "vp": 0, "hand": [], "artifacts": []})
        self.doc_store.insert("players", {"_id": "player_2", "name": "AI玩家2", "gold": 20, "vp": 0, "hand": [], "artifacts": []})

        self.on_output("fake-startup-message")
        self.on_output(
            {
                "type": "ai_message",
                "player_id": "player_1",
                "player_name": "AI玩家1",
                "content": "### AI 开场发言\n- 准备竞价",
            }
        )
        return "ok"

    def process(self, action):
        self.on_output(f"fake-action:{action}")
        self.on_output(
            {
                "type": "ai_message",
                "player_id": "player_2",
                "player_name": "AI玩家2",
                "content": f"我回应：`{action}`",
            }
        )
        if self.session:
            self.session.is_waiting_for_human = False
        return "ok"


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


def test_create_game_returns_progress_events(monkeypatch):
    monkeypatch.setattr(server, "GMAgent", FakeGMAgent)
    server.active_games.clear()

    with TestClient(server.app) as client:
        response = client.post(
            "/api/games",
            json={
                "player_name": "测试玩家",
                "ai_count": 2,
                "api_key": "test-key",
                "base_url": "",
                "model": "fake-model",
                "game_id": "chronos_auction",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["progress_events"]
        assert all(evt["scope"] == "create_game" for evt in payload["progress_events"])
        assert any(evt.get("status") == "completed" and evt.get("percent") == 100 for evt in payload["progress_events"])
        assert "context_metrics" in payload["state"]
        assert set(payload["state"]["context_metrics"].keys()) >= {
            "message_count",
            "estimated_chars",
            "estimated_tokens",
            "max_response_tokens",
            "api_request_count",
            "api_input_tokens",
            "api_output_tokens",
            "api_total_tokens",
            "api_cache_creation_input_tokens",
            "api_cache_read_input_tokens",
        }
        assert any(msg["kind"] == "gm" and msg["content"] == "fake-startup-message" for msg in payload["messages"])
        assert any(
            msg["kind"] == "ai" and msg["player_name"] == "AI玩家1" and "AI 开场发言" in msg["content"]
            for msg in payload["messages"]
        )


def test_action_returns_progress_events(monkeypatch):
    monkeypatch.setattr(server, "GMAgent", FakeGMAgent)
    server.active_games.clear()

    with TestClient(server.app) as client:
        create_response = client.post(
            "/api/games",
            json={
                "player_name": "测试玩家",
                "ai_count": 2,
                "api_key": "test-key",
                "base_url": "",
                "model": "fake-model",
                "game_id": "chronos_auction",
            },
        )
        assert create_response.status_code == 200
        game_id = create_response.json()["game_id"]

        action_response = client.post(
            f"/api/games/{game_id}/action",
            json={"action": "我出价 12"},
        )
        assert action_response.status_code == 200
        payload = action_response.json()
        assert payload["action_id"]
        assert any(evt["scope"] == "action" for evt in payload["progress_events"])
        assert any(evt.get("status") == "completed" and evt.get("percent") == 100 for evt in payload["progress_events"])
        assert "context_metrics" in payload["state"]
        assert payload["state"]["context_metrics"]["estimated_tokens"] >= 0
        assert payload["state"]["context_metrics"]["api_total_tokens"] >= 0
        assert any(
            msg["kind"] == "gm" and "fake-action:我出价 12" in msg["content"]
            for msg in payload["messages"]
        )
        assert any(
            msg["kind"] == "ai" and msg["player_id"] == "player_2" and "我回应" in msg["content"]
            for msg in payload["messages"]
        )


def test_state_includes_viewer_hand_cards(monkeypatch):
    monkeypatch.setattr(server, "GMAgent", FakeGMAgent)
    server.active_games.clear()

    with TestClient(server.app) as client:
        create_response = client.post(
            "/api/games",
            json={
                "player_name": "测试玩家",
                "ai_count": 2,
                "api_key": "test-key",
                "base_url": "",
                "model": "fake-model",
                "game_id": "chronos_auction",
            },
        )
        assert create_response.status_code == 200
        payload = create_response.json()
        state = payload["state"]
        assert state["viewer_player_id"] == "player_0"
        assert "viewer_hand_items" in state
        assert isinstance(state["viewer_hand_items"], list)
        assert len(state["viewer_hand_items"]) >= 1
        first_card = state["viewer_hand_items"][0]
        assert set(first_card.keys()) == {"id", "name", "description", "effect"}
        assert first_card["id"]
        assert first_card["name"]


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
