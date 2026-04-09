"""Tests for PDF parser pipeline (pdf_extractor, cache_manager, llm_extractor prompts)"""
import hashlib
import json
import os
import tempfile
import pytest

import fitz  # PyMuPDF

from src.parser.pdf_extractor import PdfExtractor, StructuredDocument, TextBlock
from src.parser.cache_manager import CacheManager
from src.parser.llm_extractor import LlmExtractor, EXTRACTION_PROMPTS
from src.core.game_definition import GameDefinition


# ========== PDF Extractor ==========

class TestPdfExtractor:
    def _create_test_pdf(self, tmp_path, text_blocks=None) -> str:
        """创建一个简单的测试 PDF"""
        if text_blocks is None:
            text_blocks = [
                ("Game Rules", 18.0, True),
                ("This is a board game for 2-4 players.", 12.0, False),
                ("Setup", 16.0, True),
                ("Each player gets 10 gold.", 12.0, False),
            ]

        pdf_path = str(tmp_path / "test.pdf")
        doc = fitz.open()
        page = doc.new_page()

        y = 72
        for text, font_size, is_bold in text_blocks:
            fontname = "helv"
            page.insert_text(
                (72, y),
                text,
                fontsize=font_size,
                fontname=fontname,
            )
            y += font_size + 10

        doc.save(pdf_path)
        doc.close()
        return pdf_path

    def test_extract_returns_structured_doc(self, tmp_path):
        pdf_path = self._create_test_pdf(tmp_path)
        extractor = PdfExtractor()
        doc = extractor.extract(pdf_path)
        assert isinstance(doc, StructuredDocument)
        assert doc.page_count == 1
        assert len(doc.blocks) > 0
        assert doc.sha256

    def test_extract_preserves_text(self, tmp_path):
        pdf_path = self._create_test_pdf(tmp_path)
        extractor = PdfExtractor()
        doc = extractor.extract(pdf_path)
        full_text = doc.full_text
        assert "Game Rules" in full_text
        assert "10 gold" in full_text

    def test_extract_detects_headings(self, tmp_path):
        pdf_path = self._create_test_pdf(tmp_path)
        extractor = PdfExtractor(heading_font_size_threshold=14.0)
        doc = extractor.extract(pdf_path)
        headings = [b for b in doc.blocks if b.is_heading]
        assert len(headings) >= 1

    def test_extract_sections(self, tmp_path):
        pdf_path = self._create_test_pdf(tmp_path)
        extractor = PdfExtractor(heading_font_size_threshold=14.0)
        doc = extractor.extract(pdf_path)
        sections = doc.sections
        assert isinstance(sections, list)
        assert len(sections) >= 1

    def test_extract_from_bytes(self, tmp_path):
        pdf_path = self._create_test_pdf(tmp_path)
        with open(pdf_path, "rb") as f:
            data = f.read()
        extractor = PdfExtractor()
        doc = extractor.extract_from_bytes(data, "test.pdf")
        assert doc.filename == "test.pdf"
        assert doc.page_count == 1

    def test_sha256_consistent(self, tmp_path):
        pdf_path = self._create_test_pdf(tmp_path)
        extractor = PdfExtractor()
        doc1 = extractor.extract(pdf_path)
        doc2 = extractor.extract(pdf_path)
        assert doc1.sha256 == doc2.sha256

    def test_file_not_found(self):
        extractor = PdfExtractor()
        with pytest.raises(FileNotFoundError):
            extractor.extract("/nonexistent/path.pdf")


# ========== Cache Manager ==========

class TestCacheManager:
    def test_l1_set_and_get(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        sha = "abc123"
        data = {"text": "hello", "pages": 3}
        cm.set_pdf_text(sha, data)
        result = cm.get_pdf_text(sha)
        assert result == data

    def test_l1_miss(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        assert cm.get_pdf_text("nonexistent") is None

    def test_l2_set_and_get(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        game_def = GameDefinition(
            id="test",
            name="Test",
            version="1.0",
            player_count_min=2,
            player_count_max=4,
            resources=[],
            categories=[],
            object_types=[],
            phases=[],
        )
        cm.set_game_def("sha123", game_def)
        result = cm.get_game_def("sha123")
        assert result is not None
        assert result.name == "Test"

    def test_l2_miss(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        assert cm.get_game_def("nonexistent") is None

    def test_l3_set_and_get_json(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        tools = [{"name": "tool1"}]
        cm.set_generated("my_game", "tools.json", tools)
        result = cm.get_generated("my_game", "tools.json")
        assert result == tools

    def test_l3_set_and_get_text(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        prompt = "You are a GM..."
        cm.set_generated("my_game", "gm_prompt.md", prompt)
        result = cm.get_generated("my_game", "gm_prompt.md")
        assert result == prompt

    def test_l3_miss(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        assert cm.get_generated("nonexistent", "tools.json") is None

    def test_list_cached_games(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        game_def = GameDefinition(
            id="test",
            name="Test Game",
            version="1.0",
            player_count_min=2,
            player_count_max=4,
            resources=[],
            categories=[],
            object_types=[],
            phases=[],
        )
        cm.set_game_def("sha1", game_def)
        games = cm.list_cached_games()
        assert len(games) == 1
        assert games[0]["name"] == "Test Game"

    def test_clear_cache(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        cm.set_pdf_text("sha1", {"text": "test"})
        cm.clear_cache(level=1)
        assert cm.get_pdf_text("sha1") is None


# ========== LLM Extractor (dry run / prompts) ==========

class TestLlmExtractor:
    def test_extraction_prompts_exist(self):
        assert "meta" in EXTRACTION_PROMPTS
        assert "resources" in EXTRACTION_PROMPTS
        assert "objects" in EXTRACTION_PROMPTS
        assert "phases" in EXTRACTION_PROMPTS
        assert "victory_and_mechanics" in EXTRACTION_PROMPTS

    def test_dry_run_returns_all_prompts(self):
        extractor = LlmExtractor(client="dummy")
        prompts = extractor.extract_dry_run("Some game rules text...")
        assert len(prompts) == 5
        for key, prompt in prompts.items():
            assert "Some game rules text" in prompt

    def test_prompts_include_text_placeholder(self):
        for key, template in EXTRACTION_PROMPTS.items():
            assert "{text}" in template, f"Template '{key}' missing {{text}} placeholder"

    def test_prompts_request_json(self):
        for key, template in EXTRACTION_PROMPTS.items():
            assert "JSON" in template, f"Template '{key}' should mention JSON output"
