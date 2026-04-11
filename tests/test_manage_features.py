"""Tests for game management features: manage page, delete endpoint."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api import server


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


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

    def test_delete_game(self, client, tmp_path):
        fake_dir = tmp_path / "test_delete_me"
        fake_dir.mkdir()
        (fake_dir / "rules.md").write_text("# Rules", encoding="utf-8")
        (fake_dir / "metadata.json").write_text('{"game_name": "DeleteMe"}', encoding="utf-8")

        fake_game_info = {
            "id": "test_delete_me",
            "name": "DeleteMe",
            "path": str(fake_dir),
        }

        with patch("src.core.game_loader.discover_games", return_value=[fake_game_info]):
            resp = client.delete("/api/games/definitions/test_delete_me")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
            assert not fake_dir.exists()


# ---- Chronos Auction rules.md ----

class TestChronosAuctionRules:
    """Test the built-in Chronos Auction game data."""

    def test_rules_md_exists(self):
        path = PROJECT_ROOT / "src" / "games" / "chronos_auction" / "rules.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "时空拍卖行" in content
        assert "拍卖" in content

    def test_metadata_json_exists(self):
        path = PROJECT_ROOT / "src" / "games" / "chronos_auction" / "metadata.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["game_name"] == "时空拍卖行"
        assert data["player_count_min"] == 3
        assert data["player_count_max"] == 5
