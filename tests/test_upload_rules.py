"""Tests for the /api/games/upload-rules endpoint."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

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


class TestUploadRulesValidation:
    """Test file validation in upload_rules."""

    def test_rejects_unsupported_format(self, client):
        resp = client.post(
            "/api/games/upload-rules",
            files={"file": ("rules.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"] or "DOCX" in resp.json()["detail"]

    def test_rejects_empty_file(self, client):
        resp = client.post(
            "/api/games/upload-rules",
            files={"file": ("rules.pdf", b"", "application/pdf")},
        )
        assert resp.status_code == 400
        assert "空" in resp.json()["detail"]

    def test_rejects_missing_api_key(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        resp = client.post(
            "/api/games/upload-rules",
            files={"file": ("rules.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert resp.status_code == 400
        assert "API Key" in resp.json()["detail"]


class TestUploadRulesApiKey:
    """Test api_key form field handling."""

    def test_uses_client_api_key(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        fake_raw_doc = MagicMock()
        fake_raw_doc.sha256 = "abc123"
        fake_raw_doc.raw_text = "game rules text"

        fake_result = MagicMock()
        fake_result.rules_md = "# Rules\n\nGame rules."
        fake_result.metadata = {"game_name": "Test Game"}

        with patch("src.parser.document_parser.parse_bytes", return_value=fake_raw_doc), \
             patch("src.parser.rule_cleaner.RuleCleaner") as MockCleaner, \
             patch("src.parser.cache_manager.CacheManager") as MockCache, \
             patch("src.core.game_loader.save_game_rules"), \
             patch("anthropic.Anthropic") as MockAnthropic:

            MockCache.return_value.get_rules.return_value = None
            MockCache.return_value.set_rules.return_value = None
            MockCleaner.return_value.clean.return_value = fake_result

            resp = client.post(
                "/api/games/upload-rules",
                files={"file": ("rules.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"api_key": "sk-test-key-from-client"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["metadata"]["game_name"] == "Test Game"

            MockAnthropic.assert_called_once_with(api_key="sk-test-key-from-client")

    def test_falls_back_to_env_key(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key")

        fake_raw_doc = MagicMock()
        fake_raw_doc.sha256 = "def456"
        fake_raw_doc.raw_text = "rules"

        fake_result = MagicMock()
        fake_result.rules_md = "# Rules"
        fake_result.metadata = {"game_name": "Env Game"}

        with patch("src.parser.document_parser.parse_bytes", return_value=fake_raw_doc), \
             patch("src.parser.rule_cleaner.RuleCleaner") as MockCleaner, \
             patch("src.parser.cache_manager.CacheManager") as MockCache, \
             patch("src.core.game_loader.save_game_rules"), \
             patch("anthropic.Anthropic") as MockAnthropic:

            MockCache.return_value.get_rules.return_value = None
            MockCache.return_value.set_rules.return_value = None
            MockCleaner.return_value.clean.return_value = fake_result

            resp = client.post(
                "/api/games/upload-rules",
                files={"file": ("rules.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
            assert resp.status_code == 200
            MockAnthropic.assert_called_once_with(api_key="sk-env-key")

    def test_cached_result_returned(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-key")

        fake_raw_doc = MagicMock()
        fake_raw_doc.sha256 = "cached_hash"

        cached_rules = "# Cached Rules"
        cached_meta = {"game_name": "Cached Game"}

        with patch("src.parser.document_parser.parse_bytes", return_value=fake_raw_doc), \
             patch("src.parser.cache_manager.CacheManager") as MockCache, \
             patch("src.core.game_loader.save_game_rules"):

            MockCache.return_value.get_rules.return_value = (cached_rules, cached_meta)

            resp = client.post(
                "/api/games/upload-rules",
                files={"file": ("rules.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"api_key": "sk-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "cached"
            assert "Cached Game" in data["message"]
