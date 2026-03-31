"""项目日志配置。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

DEFAULT_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | "
    "game_id=%(game_id)s action_id=%(action_id)s | %(message)s"
)


class _ContextDefaultsFilter(logging.Filter):
    """为日志记录补齐上下文字段，避免格式化报错。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "game_id"):
            record.game_id = "-"
        if not hasattr(record, "action_id"):
            record.action_id = "-"
        return True


def _parse_level(level_name: str) -> int:
    parsed = logging.getLevelName(level_name.upper())
    if isinstance(parsed, str):
        return logging.INFO
    return parsed


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
) -> None:
    """初始化根日志器（控制台 + 文件）。"""
    root_logger = logging.getLogger()
    if getattr(root_logger, "_chronos_logging_initialized", False):
        return

    log_level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).strip() or "INFO"
    log_level = _parse_level(log_level_name)
    file_target = (log_file or os.environ.get("LOG_FILE", "logs/app.log")).strip() or "logs/app.log"
    log_path = Path(file_target).expanduser()
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
    defaults_filter = _ContextDefaultsFilter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(defaults_filter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(defaults_filter)

    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger._chronos_logging_initialized = True  # type: ignore[attr-defined]


def bind_context(
    logger: logging.Logger,
    *,
    game_id: Optional[str] = None,
    action_id: Optional[str] = None,
) -> logging.LoggerAdapter:
    """返回绑定上下文后的 logger adapter。"""
    context: dict[str, str] = {}
    if game_id:
        context["game_id"] = game_id
    if action_id:
        context["action_id"] = action_id
    return logging.LoggerAdapter(logger, context)
