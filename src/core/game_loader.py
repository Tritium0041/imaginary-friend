"""
游戏加载器 — 扫描并加载游戏规则（rules.md + metadata.json）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

GAMES_DIR = Path(__file__).parent.parent / "games"


def discover_games() -> list[dict[str, str]]:
    """扫描所有可用游戏，返回简要信息列表"""
    games: list[dict[str, str]] = []

    if not GAMES_DIR.is_dir():
        return games

    for subdir in sorted(GAMES_DIR.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith("_"):
            continue
        rules_file = subdir / "rules.md"
        meta_file = subdir / "metadata.json"
        if rules_file.exists() and meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                games.append({
                    "id": subdir.name,
                    "name": meta.get("game_name", subdir.name),
                    "path": str(subdir),
                })
            except Exception as e:
                logger.warning("Failed to read %s: %s", meta_file, e)

    return games


def load_game_rules(game_id: str) -> Optional[tuple[str, dict[str, Any]]]:
    """
    按 game_id 加载游戏规则。
    返回 (rules_md, metadata) 或 None。
    """
    for info in discover_games():
        if info["id"] == game_id:
            game_dir = Path(info["path"])
            rules_md = (game_dir / "rules.md").read_text(encoding="utf-8")
            metadata = json.loads(
                (game_dir / "metadata.json").read_text(encoding="utf-8")
            )
            return rules_md, metadata
    return None


def load_game_rules_from_path(game_dir: str | Path) -> tuple[str, dict[str, Any]]:
    """从指定目录加载游戏规则。"""
    game_dir = Path(game_dir)
    rules_md = (game_dir / "rules.md").read_text(encoding="utf-8")
    metadata = json.loads(
        (game_dir / "metadata.json").read_text(encoding="utf-8")
    )
    return rules_md, metadata


def save_game_rules(
    game_id: str,
    rules_md: str,
    metadata: dict[str, Any],
    target_dir: str | Path | None = None,
) -> Path:
    """保存游戏规则到 src/games/ 目录，返回保存目录路径。"""
    base = Path(target_dir) if target_dir else GAMES_DIR
    game_dir = base / game_id
    game_dir.mkdir(parents=True, exist_ok=True)

    (game_dir / "rules.md").write_text(rules_md, encoding="utf-8")
    (game_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved game rules '%s' to %s", game_id, game_dir)
    return game_dir
