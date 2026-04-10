"""Tests for game management features: narrative field, manage page, delete endpoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.game_definition import GameDefinition
from src.core.prompt_generator import PromptGenerator
from src.api import server


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


# ---- GameDefinition narrative field ----

class TestGameplayOverviewField:
    """Test the gameplay_overview field on GameDefinition."""

    def test_default_empty(self):
        gd = GameDefinition(name="Test")
        assert gd.gameplay_overview == ""

    def test_set_and_serialize(self):
        gd = GameDefinition(name="Test", gameplay_overview="This is how you play.")
        data = gd.model_dump()
        assert data["gameplay_overview"] == "This is how you play."
        restored = GameDefinition(**data)
        assert restored.gameplay_overview == "This is how you play."

    def test_chronos_has_gameplay_overview(self):
        path = PROJECT_ROOT / "src" / "games" / "chronos_auction" / "definition.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        gd = GameDefinition(**data)
        assert len(gd.gameplay_overview) > 100


# ---- PromptGenerator narrative injection ----

class TestPromptGeneratorNarrative:
    """Test that gameplay_overview appears in generated prompt."""

    def test_overview_in_prompt(self):
        gd = GameDefinition(
            name="Test",
            description="A test game.",
            gameplay_overview="Players take turns rolling dice and moving tokens.",
        )
        prompt = PromptGenerator().generate(gd)
        assert "游戏流程概述" in prompt
        assert "rolling dice" in prompt

    def test_no_overview_section_when_empty(self):
        gd = GameDefinition(name="Test")
        prompt = PromptGenerator().generate(gd)
        assert "游戏流程概述" not in prompt


# ---- Manage page endpoint ----

class TestManagePage:
    """Test GET /manage returns HTML."""

    def test_manage_returns_html(self, client):
        resp = client.get("/manage")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "游戏管理" in resp.text
        assert "manage.js" in resp.text
        assert "manage.css" in resp.text


# ---- Play page has manage link ----

class TestPlayPageManageLink:
    """Test /play page includes link to /manage."""

    def test_play_has_manage_link(self, client):
        resp = client.get("/play")
        assert resp.status_code == 200
        assert "/manage" in resp.text
        assert "游戏管理" in resp.text


# ---- DELETE endpoint ----

class TestDeleteGameDefinition:
    """Test DELETE /api/games/definitions/{game_id}."""

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/games/definitions/nonexistent_game_xyz")
        assert resp.status_code == 404

    def test_delete_builtin_returns_403(self, client):
        resp = client.delete("/api/games/definitions/chronos_auction")
        assert resp.status_code == 403
        assert "内置" in resp.json()["detail"]

    def test_delete_cached_game(self, client, tmp_path):
        fake_def = {"id": "test_delete_me", "name": "DeleteMe", "player_count_min": 2, "player_count_max": 4}
        fake_file = tmp_path / "test_delete_me.json"
        fake_file.write_text(json.dumps(fake_def), encoding="utf-8")

        fake_game_info = {
            "id": "test_delete_me",
            "name": "DeleteMe",
            "source": "cached",
            "path": str(fake_file),
        }

        with patch("src.core.game_loader.discover_games", return_value=[fake_game_info]):
            resp = client.delete("/api/games/definitions/test_delete_me")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
            assert not fake_file.exists()
