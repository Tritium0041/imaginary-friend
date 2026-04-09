"""
PDF 文本提取器 (PdfExtractor)

使用 PyMuPDF 从 PDF 规则书中提取结构化文本。
保留页码、标题层级等结构信息，以便后续 LLM 提取。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class TextBlock:
    """一个文本块"""
    text: str
    page: int
    font_size: float = 0.0
    is_bold: bool = False
    is_heading: bool = False


@dataclass
class StructuredDocument:
    """结构化文档"""
    filename: str
    sha256: str
    page_count: int
    blocks: list[TextBlock] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """获取完整文本"""
        lines = []
        current_page = -1
        for block in self.blocks:
            if block.page != current_page:
                current_page = block.page
                lines.append(f"\n--- 第 {current_page + 1} 页 ---\n")
            if block.is_heading:
                lines.append(f"\n## {block.text}\n")
            else:
                lines.append(block.text)
        return "\n".join(lines)

    @property
    def sections(self) -> list[dict]:
        """按标题分割为章节列表"""
        result = []
        current_section = {"title": "前言", "content": [], "page": 0}

        for block in self.blocks:
            if block.is_heading:
                if current_section["content"]:
                    current_section["content"] = "\n".join(current_section["content"])
                    result.append(current_section)
                current_section = {
                    "title": block.text,
                    "content": [],
                    "page": block.page,
                }
            else:
                current_section["content"].append(block.text)

        if current_section["content"]:
            current_section["content"] = "\n".join(current_section["content"])
            result.append(current_section)

        return result


class PdfExtractor:
    """PDF 文本提取器"""

    def __init__(self, heading_font_size_threshold: float = 14.0):
        self.heading_threshold = heading_font_size_threshold

    def extract(self, pdf_path: str | Path) -> StructuredDocument:
        """从 PDF 文件提取结构化文本"""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        sha256 = self._compute_sha256(pdf_path)

        doc = fitz.open(str(pdf_path))
        blocks: list[TextBlock] = []
        page_count = doc.page_count

        for page_idx in range(page_count):
            page = doc.load_page(page_idx)
            page_blocks = self._extract_page_blocks(page, page_idx)
            blocks.extend(page_blocks)

        doc.close()
        logger.info("Extracted %d blocks from %s (%d pages)", len(blocks), pdf_path.name, page_count)

        return StructuredDocument(
            filename=pdf_path.name,
            sha256=sha256,
            page_count=page_count,
            blocks=blocks,
        )

    def extract_from_bytes(self, data: bytes, filename: str = "upload.pdf") -> StructuredDocument:
        """从字节数据提取"""
        sha256 = hashlib.sha256(data).hexdigest()

        doc = fitz.open(stream=data, filetype="pdf")
        blocks: list[TextBlock] = []

        for page_idx in range(doc.page_count):
            page = doc.load_page(page_idx)
            page_blocks = self._extract_page_blocks(page, page_idx)
            blocks.extend(page_blocks)

        page_count = doc.page_count
        doc.close()

        return StructuredDocument(
            filename=filename,
            sha256=sha256,
            page_count=page_count,
            blocks=blocks,
        )

    def _extract_page_blocks(self, page, page_idx: int) -> list[TextBlock]:
        """提取单页文本块"""
        blocks: list[TextBlock] = []

        # 使用 dict 模式获取详细的文本信息
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 只处理文本块
                continue

            for line in block.get("lines", []):
                text_parts = []
                max_font_size = 0.0
                is_bold = False

                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    text_parts.append(text)
                    font_size = span.get("size", 0.0)
                    max_font_size = max(max_font_size, font_size)
                    font_name = span.get("font", "").lower()
                    if "bold" in font_name or "heavy" in font_name:
                        is_bold = True

                line_text = " ".join(text_parts).strip()
                if not line_text:
                    continue

                is_heading = (
                    max_font_size >= self.heading_threshold
                    or (is_bold and len(line_text) < 50)
                )

                blocks.append(TextBlock(
                    text=line_text,
                    page=page_idx,
                    font_size=max_font_size,
                    is_bold=is_bold,
                    is_heading=is_heading,
                ))

        return blocks

    @staticmethod
    def _compute_sha256(file_path: Path) -> str:
        """计算文件 SHA256"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
