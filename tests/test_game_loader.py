"""Tests for game_loader and new API endpoints"""
import json
import pytest
from pathlib import Path

from src.core.game_loader import discover_games, load_game_rules, save_game_rules


class TestGameLoader:
    def test_discover_returns_required_fields(self):
        games = discover_games()
        for g in games:
            assert "id" in g
            assert "name" in g
            assert "path" in g

    def test_load_nonexistent(self):
        result = load_game_rules("nonexistent_game_xyz")
        assert result is None

    def test_save_and_load(self, tmp_path):
        rules_md = "# Test Game\n\nRules here."
        metadata = {"game_name": "Test Save Game", "player_count_min": 2, "player_count_max": 4}
        path = save_game_rules("test_save", rules_md, metadata, target_dir=tmp_path)
        assert path.exists()
        assert (path / "rules.md").exists()
        assert (path / "metadata.json").exists()
        data = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        assert data["game_name"] == "Test Save Game"


class TestNewAPIEndpoints:
    """Test the new game API endpoints using FastAPI TestClient"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from src.api.server import app
        return TestClient(app)

    def test_get_definition_not_found(self, client):
        resp = client.get("/api/games/definitions/nonexistent_xyz")
        assert resp.status_code == 404

    def test_root_updated(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "通用桌游" in data["message"]
        assert data["version"] == "0.3.0"

    def test_upload_rules_rejects_unsupported(self, client):
        resp = client.post(
            "/api/games/upload-rules",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
