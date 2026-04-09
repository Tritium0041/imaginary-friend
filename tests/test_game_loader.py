"""Tests for game_loader and new API endpoints"""
import json
import pytest
from pathlib import Path

from src.core.game_loader import discover_games, load_game_definition, save_game_definition
from src.core.game_definition import GameDefinition


class TestGameLoader:
    def test_discover_finds_builtin_chronos(self):
        games = discover_games()
        ids = [g["id"] for g in games]
        assert "chronos_auction" in ids

    def test_discover_returns_required_fields(self):
        games = discover_games()
        for g in games:
            assert "id" in g
            assert "name" in g
            assert "source" in g
            assert "path" in g

    def test_load_chronos(self):
        gd = load_game_definition("chronos_auction")
        assert gd is not None
        assert gd.id == "chronos_auction"
        assert gd.name == "时空拍卖行"

    def test_load_nonexistent(self):
        gd = load_game_definition("nonexistent_game_xyz")
        assert gd is None

    def test_save_and_discover(self, tmp_path):
        gd = GameDefinition(
            id="test_save",
            name="Test Save Game",
            version="1.0",
            player_count_min=2,
            player_count_max=4,
            resources=[],
            categories=[],
            object_types=[],
            phases=[],
        )
        path = save_game_definition(gd, target_dir=tmp_path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["id"] == "test_save"
        assert data["name"] == "Test Save Game"


class TestNewAPIEndpoints:
    """Test the new game definition API endpoints using FastAPI TestClient"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from src.api.server import app
        return TestClient(app)

    def test_list_definitions(self, client):
        resp = client.get("/api/games/definitions")
        assert resp.status_code == 200
        data = resp.json()
        assert "definitions" in data
        ids = [d["id"] for d in data["definitions"]]
        assert "chronos_auction" in ids

    def test_get_definition(self, client):
        resp = client.get("/api/games/definitions/chronos_auction")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "chronos_auction"
        assert data["name"] == "时空拍卖行"

    def test_get_definition_not_found(self, client):
        resp = client.get("/api/games/definitions/nonexistent_xyz")
        assert resp.status_code == 404

    def test_root_updated(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "通用桌游" in data["message"]
        assert data["version"] == "0.3.0"

    def test_upload_rules_rejects_non_pdf(self, client):
        resp = client.post(
            "/api/games/upload-rules",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
