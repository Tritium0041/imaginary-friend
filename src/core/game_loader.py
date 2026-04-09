"""
游戏加载器 — 扫描并加载可用的 GameDefinition 实例
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .game_definition import GameDefinition

logger = logging.getLogger(__name__)

GAMES_DIR = Path(__file__).parent.parent / "games"
CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "game_defs"


def discover_games() -> list[dict[str, str]]:
    """扫描所有可用游戏，返回简要信息列表"""
    games: list[dict[str, str]] = []

    # 1) 扫描 src/games/ 下的内置游戏
    if GAMES_DIR.is_dir():
        for subdir in sorted(GAMES_DIR.iterdir()):
            def_file = subdir / "definition.json"
            if subdir.is_dir() and def_file.exists():
                try:
                    data = json.loads(def_file.read_text(encoding="utf-8"))
                    game_id = data.get("id") or subdir.name
                    games.append({
                        "id": game_id,
                        "name": data.get("name", subdir.name),
                        "source": "builtin",
                        "path": str(def_file),
                    })
                except Exception as e:
                    logger.warning("Failed to read %s: %s", def_file, e)

    # 2) 扫描 cache/game_defs/ 下的用户导入游戏
    if CACHE_DIR.is_dir():
        for json_file in sorted(CACHE_DIR.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                game_id = data.get("id", json_file.stem)
                # 避免与内置游戏重复
                if any(g["id"] == game_id for g in games):
                    continue
                games.append({
                    "id": game_id,
                    "name": data.get("name", json_file.stem),
                    "source": "cached",
                    "path": str(json_file),
                })
            except Exception as e:
                logger.warning("Failed to read %s: %s", json_file, e)

    return games


def load_game_definition(game_id: str) -> Optional[GameDefinition]:
    """按 game_id 加载 GameDefinition"""
    for info in discover_games():
        if info["id"] == game_id:
            path = Path(info["path"])
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("id"):
                data["id"] = game_id
            return GameDefinition(**data)

    return None


def load_game_definition_from_path(path: str | Path) -> GameDefinition:
    """从指定路径加载 GameDefinition"""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return GameDefinition(**data)


def save_game_definition(game_def: GameDefinition, target_dir: str | Path | None = None) -> Path:
    """保存 GameDefinition 到 cache 目录，返回保存路径"""
    target = Path(target_dir) if target_dir else CACHE_DIR
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{game_def.id}.json"
    path.write_text(
        json.dumps(game_def.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved GameDefinition '%s' to %s", game_def.name, path)
    return path
