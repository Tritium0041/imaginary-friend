"""
Markdown 文件读取器 — 直接读取 .md 文件内容。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MdDocument:
    """Markdown 文件读取结果。"""

    filename: str
    sha256: str
    text: str

    @property
    def full_text(self) -> str:
        return self.text


class MdExtractor:
    """从 Markdown 文件中读取文本内容。"""

    def extract(self, file_path: str | Path) -> MdDocument:
        """从文件路径读取。"""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Markdown file not found: {file_path}")

        sha256 = self._compute_sha256(file_path)
        text = file_path.read_text(encoding="utf-8")

        logger.info(
            "Read %d characters from Markdown: %s", len(text), file_path.name
        )
        return MdDocument(filename=file_path.name, sha256=sha256, text=text)

    def extract_from_bytes(self, data: bytes, filename: str) -> MdDocument:
        """从字节流读取。"""
        sha256 = hashlib.sha256(data).hexdigest()
        text = data.decode("utf-8")
        logger.info("Read %d characters from Markdown bytes: %s", len(text), filename)
        return MdDocument(filename=filename, sha256=sha256, text=text)

    @staticmethod
    def _compute_sha256(file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
