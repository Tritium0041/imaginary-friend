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


class FakeGMAgent:
    """避免外部模型调用的测试替身。"""

    def __init__(self, config=None, game_mgr=None, on_output=None, api_key=None, base_url=None):
        self.config = config
        self.game_mgr = game_mgr
        self.on_output = on_output or (lambda _msg: None)
        self.api_key = api_key
        self.base_url = base_url
        self.session = None

    def start_game(self, player_names, game_id=None):
        result = self.game_mgr.initialize_game(
            game_id=game_id or "progress01",
            player_names=player_names,
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "failed")
        self.session = SimpleNamespace(
            game_id=result["game_id"],
            is_waiting_for_human=True,
        )
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
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["progress_events"]
        assert all(evt["scope"] == "create_game" for evt in payload["progress_events"])
        assert any(evt.get("status") == "completed" and evt.get("percent") == 100 for evt in payload["progress_events"])
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
        assert any(
            msg["kind"] == "gm" and "fake-action:我出价 12" in msg["content"]
            for msg in payload["messages"]
        )
        assert any(
            msg["kind"] == "ai" and msg["player_id"] == "player_2" and "我回应" in msg["content"]
            for msg in payload["messages"]
        )


def test_public_state_includes_player_artifacts(monkeypatch):
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
            },
        )
        assert create_response.status_code == 200
        payload = create_response.json()
        players = payload["state"]["players"]
        assert players
        sample_player = next(iter(players.values()))
        assert "artifacts" in sample_player
        assert isinstance(sample_player["artifacts"], list)
