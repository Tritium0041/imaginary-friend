"""
缓存管理器 (CacheManager)

缓存 LLM 清洗后的规则（sha256 → rules.md + metadata.json），
避免重复调用 LLM（每次需要几分钟且有费用）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / "cache"


class CacheManager:
    """LLM 清洗结果缓存"""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.rules_dir = self.cache_dir / "cleaned_rules"
        self.rules_dir.mkdir(parents=True, exist_ok=True)

    def get_rules(self, sha256: str) -> Optional[tuple[str, dict[str, Any]]]:
        """获取缓存的 rules.md + metadata。返回 (rules_md, metadata) 或 None。"""
        game_dir = self.rules_dir / sha256
        rules_file = game_dir / "rules.md"
        meta_file = game_dir / "metadata.json"
        if rules_file.exists() and meta_file.exists():
            logger.debug("Cache hit: %s", sha256[:12])
            rules_md = rules_file.read_text(encoding="utf-8")
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            return rules_md, metadata
        return None

    def set_rules(self, sha256: str, rules_md: str, metadata: dict[str, Any]):
        """缓存 rules.md + metadata"""
        game_dir = self.rules_dir / sha256
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "rules.md").write_text(rules_md, encoding="utf-8")
        (game_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("Cache set: %s", sha256[:12])

    def clear_cache(self):
        """清除所有缓存"""
        import shutil
        if self.rules_dir.exists():
            shutil.rmtree(self.rules_dir)
            self.rules_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Cache cleared")
