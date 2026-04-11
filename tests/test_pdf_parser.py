"""Tests for PDF parser pipeline (pdf_extractor, cache_manager)"""
import json
import pytest

import fitz  # PyMuPDF

from src.parser.pdf_extractor import PdfExtractor, StructuredDocument, TextBlock
from src.parser.cache_manager import CacheManager


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
    def test_set_and_get_rules(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        rules_md = "# Test Game\n\nRules here."
        metadata = {"game_name": "Test", "player_count_min": 2, "player_count_max": 4}
        cm.set_rules("sha123", rules_md, metadata)
        result = cm.get_rules("sha123")
        assert result is not None
        assert result[0] == rules_md
        assert result[1]["game_name"] == "Test"

    def test_miss(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        assert cm.get_rules("nonexistent") is None

    def test_clear_cache(self, tmp_path):
        cm = CacheManager(cache_dir=tmp_path / "cache")
        cm.set_rules("sha1", "# Rules", {"game_name": "X"})
        cm.clear_cache()
        assert cm.get_rules("sha1") is None
        assert cm.get_rules("sha2") is None
