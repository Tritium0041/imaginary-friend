"""
缓存管理器 (CacheManager)

两级缓存：
- Level 1: 原始文本缓存 (sha256 → raw text JSON)，支持 PDF/DOCX/MD
- Level 2: 清洗后的规则缓存 (sha256 → rules.md + metadata.json)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / "cache"


class CacheManager:
    """两级缓存管理器"""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.l1_dir = self.cache_dir / "raw_text"
        self.l2_dir = self.cache_dir / "cleaned_rules"
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in (self.l1_dir, self.l2_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ========== Level 1: 原始文本缓存 ==========

    def get_raw_text(self, sha256: str) -> Optional[str]:
        """获取缓存的原始文本"""
        path = self.l1_dir / f"{sha256}.txt"
        if path.exists():
            logger.debug("L1 cache hit: %s", sha256[:12])
            return path.read_text(encoding="utf-8")
        return None

    def set_raw_text(self, sha256: str, text: str):
        """缓存原始文本"""
        path = self.l1_dir / f"{sha256}.txt"
        path.write_text(text, encoding="utf-8")
        logger.debug("L1 cache set: %s", sha256[:12])

    # ========== Level 2: 规则缓存 ==========

    def get_rules(self, sha256: str) -> Optional[tuple[str, dict[str, Any]]]:
        """获取缓存的 rules.md + metadata。返回 (rules_md, metadata) 或 None。"""
        game_dir = self.l2_dir / sha256
        rules_file = game_dir / "rules.md"
        meta_file = game_dir / "metadata.json"
        if rules_file.exists() and meta_file.exists():
            logger.debug("L2 cache hit: %s", sha256[:12])
            rules_md = rules_file.read_text(encoding="utf-8")
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            return rules_md, metadata
        return None

    def set_rules(self, sha256: str, rules_md: str, metadata: dict[str, Any]):
        """缓存 rules.md + metadata"""
        game_dir = self.l2_dir / sha256
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "rules.md").write_text(rules_md, encoding="utf-8")
        (game_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("L2 cache set: %s", sha256[:12])

    # ========== 工具方法 ==========

    def list_cached_games(self) -> list[dict]:
        """列出所有缓存的游戏"""
        games = []
        if not self.l2_dir.exists():
            return games
        for subdir in self.l2_dir.iterdir():
            meta_file = subdir / "metadata.json"
            if subdir.is_dir() and meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    games.append({
                        "id": subdir.name,
                        "name": meta.get("game_name", "unknown"),
                    })
                except Exception:
                    continue
        return games

    def clear_cache(self, level: Optional[int] = None):
        """清除缓存"""
        import shutil
        if level is None or level == 1:
            if self.l1_dir.exists():
                shutil.rmtree(self.l1_dir)
                self.l1_dir.mkdir(parents=True, exist_ok=True)
        if level is None or level == 2:
            if self.l2_dir.exists():
                shutil.rmtree(self.l2_dir)
                self.l2_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Cache cleared (level=%s)", level or "all")
