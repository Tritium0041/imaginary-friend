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

    def test_rejects_non_pdf(self, client):
        resp = client.post(
            "/api/games/upload-rules",
            files={"file": ("rules.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"]

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

        fake_doc = MagicMock()
        fake_doc.sha256 = "abc123"
        fake_doc.full_text = "game rules text"

        fake_game_def = MagicMock()
        fake_game_def.name = "Test Game"
        fake_game_def.id = "test_game"
        fake_game_def.model_dump.return_value = {"id": "test_game", "name": "Test Game"}

        with patch("src.parser.pdf_extractor.PdfExtractor") as MockPdf, \
             patch("src.parser.llm_extractor.LlmExtractor") as MockLlm, \
             patch("src.parser.cache_manager.CacheManager") as MockCache, \
             patch("src.core.game_loader.save_game_definition"), \
             patch("anthropic.Anthropic") as MockAnthropic:

            MockPdf.return_value.extract_from_bytes.return_value = fake_doc
            MockCache.return_value.get_game_def.return_value = None
            MockCache.return_value.set_game_def.return_value = None
            MockLlm.return_value.extract.return_value = fake_game_def

            resp = client.post(
                "/api/games/upload-rules",
                files={"file": ("rules.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"api_key": "sk-test-key-from-client"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["game_definition"]["name"] == "Test Game"

            # Verify client key was used
            MockAnthropic.assert_called_once_with(api_key="sk-test-key-from-client")

    def test_falls_back_to_env_key(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key")

        fake_doc = MagicMock()
        fake_doc.sha256 = "def456"
        fake_doc.full_text = "rules"

        fake_game_def = MagicMock()
        fake_game_def.name = "Env Game"
        fake_game_def.id = "env_game"
        fake_game_def.model_dump.return_value = {"id": "env_game", "name": "Env Game"}

        with patch("src.parser.pdf_extractor.PdfExtractor") as MockPdf, \
             patch("src.parser.llm_extractor.LlmExtractor") as MockLlm, \
             patch("src.parser.cache_manager.CacheManager") as MockCache, \
             patch("src.core.game_loader.save_game_definition"), \
             patch("anthropic.Anthropic") as MockAnthropic:

            MockPdf.return_value.extract_from_bytes.return_value = fake_doc
            MockCache.return_value.get_game_def.return_value = None
            MockCache.return_value.set_game_def.return_value = None
            MockLlm.return_value.extract.return_value = fake_game_def

            resp = client.post(
                "/api/games/upload-rules",
                files={"file": ("rules.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
            assert resp.status_code == 200
            MockAnthropic.assert_called_once_with(api_key="sk-env-key")

    def test_cached_result_returned(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-key")

        fake_doc = MagicMock()
        fake_doc.sha256 = "cached_hash"

        cached_def = MagicMock()
        cached_def.name = "Cached Game"
        cached_def.model_dump.return_value = {"id": "cached", "name": "Cached Game"}

        with patch("src.parser.pdf_extractor.PdfExtractor") as MockPdf, \
             patch("src.parser.cache_manager.CacheManager") as MockCache:

            MockPdf.return_value.extract_from_bytes.return_value = fake_doc
            MockCache.return_value.get_game_def.return_value = cached_def

            resp = client.post(
                "/api/games/upload-rules",
                files={"file": ("rules.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"api_key": "sk-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "cached"
            assert "Cached Game" in data["message"]
