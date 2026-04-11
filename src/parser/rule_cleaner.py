"""
RuleCleaner — 2 轮 LLM 调用：文本清洗 + 元数据提取。

替代旧的 LlmExtractor 5 轮结构化 JSON 提取。
输出：完整 Markdown 规则手册 + 极简元数据。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CLEAN_PROMPT = """\
你是一个专业的桌游规则手册编辑。你的任务是将以下从文件中提取的原始文本清洗为结构清晰的 Markdown 格式规则手册。

要求：
1. 修复换行断层（合并被错误断开的段落）
2. 识别并格式化表格（使用 Markdown 表格语法）
3. 识别并格式化列表（有序/无序列表）
4. 保留所有原始内容，不要删减或总结任何规则细节
5. 使用适当的 Markdown 标题层级（#, ##, ### 等）
6. 保留所有数值、公式、特殊术语
7. 输出纯 Markdown，不要添加任何额外的说明文字

原始文本：
{raw_text}
"""

METADATA_PROMPT = """\
从以下桌游规则手册中提取极简元数据。仅返回 JSON，不要添加任何其他文字。

JSON 格式：
{{
  "game_name": "游戏名称",
  "player_count_min": 最少玩家数(整数),
  "player_count_max": 最多玩家数(整数),
  "description": "一句话简介（不超过50字）"
}}

规则手册：
{rules_text}
"""


@dataclass
class CleanResult:
    """清洗结果。"""

    rules_md: str
    metadata: dict[str, Any]


class RuleCleaner:
    """
    2 轮 LLM 规则清洗器。

    Round 1: 原始文本 → 格式化 Markdown 规则手册
    Round 2: Markdown → 极简元数据 JSON
    """

    def __init__(self, client: Any, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = client
        self._model = model

    def clean(self, raw_text: str) -> CleanResult:
        """执行 2 轮清洗，返回 rules_md + metadata。"""
        logger.info("Round 1: Cleaning raw text → Markdown (%d chars)", len(raw_text))
        rules_md = self._round1_clean(raw_text)
        logger.info("Round 1 complete: %d chars → %d chars", len(raw_text), len(rules_md))

        logger.info("Round 2: Extracting metadata from rules")
        metadata = self._round2_metadata(rules_md)
        logger.info("Round 2 complete: %s", metadata)

        return CleanResult(rules_md=rules_md, metadata=metadata)

    def clean_dry_run(self, raw_text: str) -> dict[str, str]:
        """返回将要发送的 prompt（不调用 API）。"""
        return {
            "round1_prompt": CLEAN_PROMPT.format(raw_text=raw_text[:500] + "..."),
            "round2_prompt": METADATA_PROMPT.format(rules_text="[cleaned rules]"),
        }

    def _round1_clean(self, raw_text: str) -> str:
        prompt = CLEAN_PROMPT.format(raw_text=raw_text)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._extract_text(response)

    def _round2_metadata(self, rules_text: str) -> dict[str, Any]:
        # Only send first 5000 chars for metadata extraction (sufficient)
        truncated = rules_text[:5000] if len(rules_text) > 5000 else rules_text
        prompt = METADATA_PROMPT.format(rules_text=truncated)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = self._extract_text(response)
        return self._parse_json(text)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """从 Anthropic 响应中提取文本。"""
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """从响应文本中提取 JSON。"""
        # Try direct parse
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        if "```" in text:
            start = text.find("```")
            end = text.rfind("```")
            if start != end:
                block = text[start:end]
                # Remove ```json or ``` prefix
                first_newline = block.find("\n")
                if first_newline != -1:
                    block = block[first_newline + 1:]
                try:
                    return json.loads(block.strip())
                except json.JSONDecodeError:
                    pass

        # Fallback: try to find JSON object in text
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to parse metadata JSON, returning defaults")
        return {
            "game_name": "Unknown Game",
            "player_count_min": 2,
            "player_count_max": 4,
            "description": "",
        }
