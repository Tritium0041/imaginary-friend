"""
统一文档解析器 — 根据文件扩展名分发到对应的提取器。
支持 PDF、DOCX、MD 三种格式。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md"}


@dataclass
class RawDocument:
    """统一的原始文档表示。"""

    filename: str
    sha256: str
    raw_text: str
    format: str  # "pdf", "docx", "md"

    @property
    def full_text(self) -> str:
        return self.raw_text


def parse_file(file_path: str | Path) -> RawDocument:
    """从文件路径解析文档。根据扩展名自动选择解析器。"""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format: '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext == ".docx":
        return _parse_docx(file_path)
    else:
        return _parse_md(file_path)


def parse_bytes(data: bytes, filename: str) -> RawDocument:
    """从字节流解析文档。根据文件名扩展名自动选择解析器。"""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format: '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    sha256 = hashlib.sha256(data).hexdigest()

    if ext == ".pdf":
        return _parse_pdf_bytes(data, filename, sha256)
    elif ext == ".docx":
        return _parse_docx_bytes(data, filename, sha256)
    else:
        return _parse_md_bytes(data, filename, sha256)


# ------------------------------------------------------------------
# Internal dispatchers
# ------------------------------------------------------------------

def _parse_pdf(file_path: Path) -> RawDocument:
    from src.parser.pdf_extractor import PdfExtractor

    extractor = PdfExtractor()
    doc = extractor.extract(str(file_path))
    return RawDocument(
        filename=doc.filename,
        sha256=doc.sha256,
        raw_text=doc.full_text,
        format="pdf",
    )


def _parse_pdf_bytes(data: bytes, filename: str, sha256: str) -> RawDocument:
    from src.parser.pdf_extractor import PdfExtractor

    extractor = PdfExtractor()
    doc = extractor.extract_from_bytes(data, filename)
    return RawDocument(
        filename=doc.filename,
        sha256=doc.sha256,
        raw_text=doc.full_text,
        format="pdf",
    )


def _parse_docx(file_path: Path) -> RawDocument:
    from src.parser.docx_extractor import DocxExtractor

    extractor = DocxExtractor()
    doc = extractor.extract(file_path)
    return RawDocument(
        filename=doc.filename,
        sha256=doc.sha256,
        raw_text=doc.full_text,
        format="docx",
    )


def _parse_docx_bytes(data: bytes, filename: str, sha256: str) -> RawDocument:
    from src.parser.docx_extractor import DocxExtractor

    extractor = DocxExtractor()
    doc = extractor.extract_from_bytes(data, filename)
    return RawDocument(
        filename=doc.filename,
        sha256=doc.sha256,
        raw_text=doc.full_text,
        format="docx",
    )


def _parse_md(file_path: Path) -> RawDocument:
    from src.parser.md_extractor import MdExtractor

    extractor = MdExtractor()
    doc = extractor.extract(file_path)
    return RawDocument(
        filename=doc.filename,
        sha256=doc.sha256,
        raw_text=doc.full_text,
        format="md",
    )


def _parse_md_bytes(data: bytes, filename: str, sha256: str) -> RawDocument:
    from src.parser.md_extractor import MdExtractor

    extractor = MdExtractor()
    doc = extractor.extract_from_bytes(data, filename)
    return RawDocument(
        filename=doc.filename,
        sha256=doc.sha256,
        raw_text=doc.full_text,
        format="md",
    )
