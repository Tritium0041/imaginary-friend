"""Tests for document_parser (multi-format parsing)."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.parser.document_parser import parse_file, parse_bytes, RawDocument


class TestParseFile:
    def test_parse_md_file(self, tmp_path):
        md = tmp_path / "rules.md"
        md.write_text("# Game Rules\n\nThis is a game.", encoding="utf-8")
        result = parse_file(str(md))
        assert isinstance(result, RawDocument)
        assert "Game Rules" in result.raw_text
        assert result.format == "md"
        assert result.sha256

    def test_parse_md_preserves_content(self, tmp_path):
        content = "# Title\n\n## Section A\n\n- item 1\n- item 2\n"
        md = tmp_path / "test.md"
        md.write_text(content, encoding="utf-8")
        result = parse_file(str(md))
        assert result.raw_text == content

    def test_sha256_consistent(self, tmp_path):
        md = tmp_path / "rules.md"
        md.write_text("test content", encoding="utf-8")
        r1 = parse_file(str(md))
        r2 = parse_file(str(md))
        assert r1.sha256 == r2.sha256

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_file("/nonexistent/path.md")


class TestParseBytes:
    def test_parse_md_bytes(self):
        content = b"# Rules\n\nPlay the game."
        result = parse_bytes(content, "rules.md")
        assert isinstance(result, RawDocument)
        assert "Rules" in result.raw_text
        assert result.filename == "rules.md"

    def test_unsupported_format(self):
        with pytest.raises(ValueError, match="Unsupported"):
            parse_bytes(b"data", "rules.xyz")
