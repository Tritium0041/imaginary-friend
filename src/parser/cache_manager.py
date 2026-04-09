"""
缓存管理器 (CacheManager)

三级缓存：
- Level 1: PDF 文本缓存 (sha256 → StructuredDocument JSON)
- Level 2: GameDefinition 缓存 (sha256 + model → definition.json)
- Level 3: 生成产物缓存 (tools.json + gm_prompt.md)
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

from ..core.game_definition import GameDefinition

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / "cache"


class CacheManager:
    """多级缓存管理器"""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.l1_dir = self.cache_dir / "pdf_text"
        self.l2_dir = self.cache_dir / "game_defs"
        self.l3_dir = self.cache_dir / "generated"
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in (self.l1_dir, self.l2_dir, self.l3_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ========== Level 1: PDF 文本缓存 ==========

    def get_pdf_text(self, sha256: str) -> Optional[dict]:
        """获取缓存的 PDF 文本"""
        path = self.l1_dir / f"{sha256}.json"
        if path.exists():
            logger.debug("L1 cache hit: %s", sha256[:12])
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def set_pdf_text(self, sha256: str, data: dict):
        """缓存 PDF 文本"""
        path = self.l1_dir / f"{sha256}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("L1 cache set: %s", sha256[:12])

    # ========== Level 2: GameDefinition 缓存 ==========

    def get_game_def(self, sha256: str, model_version: str = "default") -> Optional[GameDefinition]:
        """获取缓存的 GameDefinition"""
        key = f"{sha256}_{model_version}"
        path = self.l2_dir / f"{key}.json"
        if path.exists():
            logger.debug("L2 cache hit: %s", key[:20])
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return GameDefinition(**data)
        return None

    def set_game_def(self, sha256: str, game_def: GameDefinition, model_version: str = "default"):
        """缓存 GameDefinition"""
        key = f"{sha256}_{model_version}"
        path = self.l2_dir / f"{key}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(game_def.model_dump(), f, ensure_ascii=False, indent=2)
        logger.debug("L2 cache set: %s", key[:20])

    # ========== Level 3: 生成产物缓存 ==========

    def get_generated(self, game_id: str, artifact_type: str) -> Optional[Any]:
        """获取缓存的生成产物"""
        path = self.l3_dir / game_id / f"{artifact_type}"
        if path.exists():
            logger.debug("L3 cache hit: %s/%s", game_id, artifact_type)
            with open(path, "r", encoding="utf-8") as f:
                if artifact_type.endswith(".json"):
                    return json.load(f)
                return f.read()
        return None

    def set_generated(self, game_id: str, artifact_type: str, data: Any):
        """缓存生成产物"""
        game_dir = self.l3_dir / game_id
        game_dir.mkdir(parents=True, exist_ok=True)
        path = game_dir / f"{artifact_type}"
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(data, (dict, list)):
                json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(data))
        logger.debug("L3 cache set: %s/%s", game_id, artifact_type)

    # ========== 工具方法 ==========

    def list_cached_games(self) -> list[dict]:
        """列出所有缓存的 GameDefinition"""
        games = []
        for path in self.l2_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                games.append({
                    "file": path.name,
                    "id": data.get("id", "unknown"),
                    "name": data.get("name", "unknown"),
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
        if level is None or level == 3:
            if self.l3_dir.exists():
                shutil.rmtree(self.l3_dir)
                self.l3_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Cache cleared (level=%s)", level or "all")
