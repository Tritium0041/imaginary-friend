"""
LLM 结构化提取器 (LlmExtractor)

使用多轮 Claude 调用从 PDF 文本中提取 GameDefinition。
每轮聚焦一个维度：
- 第1轮：游戏元信息（名称、玩家数、简介）
- 第2轮：资源与分类系统
- 第3轮：游戏对象（牌/棋子/物品）
- 第4轮：阶段与流程
- 第5轮：特殊机制与胜利条件
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ..core.game_definition import GameDefinition

logger = logging.getLogger(__name__)

# 各轮提取的 Prompt 模板
EXTRACTION_PROMPTS = {
    "meta": """你是一个桌游规则分析专家。请从以下规则书文本中提取游戏的基本元信息。

请返回一个 JSON 对象，包含以下字段：
- id: 游戏的英文标识符（小写下划线）
- name: 游戏的中文名称
- name_en: 游戏的英文名称（如果有）
- description: 一句话游戏简介
- gameplay_overview: 游戏流程概述（300-1000字），用自然语言描述这个游戏怎么玩，包括核心机制、回合流程、玩家互动方式等
- version: 版本号（默认 "1.0"）
- player_count_min: 最少玩家数
- player_count_max: 最多玩家数

只返回 JSON，不要其他文字。

规则书文本：
{text}""",

    "resources": """你是一个桌游规则分析专家。请从以下规则书文本中提取游戏的资源和分类系统。

请返回一个 JSON 对象，包含：

1. "resources": 资源列表，每个资源包含：
   - id: 英文标识符
   - name: 中文名称
   - scope: "player"（玩家级）或 "global"（全局）
   - initial_value: 初始值
   - min_value: 最小值（可选）
   - max_value: 最大值（可选）

2. "categories": 分类列表，每个分类包含：
   - id: 英文标识符
   - name: 中文名称
   - values: 值列表，每个值有 id 和 name
   - has_multiplier: 是否有倍率机制（布尔值）
   - initial_multiplier: 初始倍率值（如果有）
   - multiplier_range: [最小值, 最大值]（如果有）

只返回 JSON，不要其他文字。

规则书文本：
{text}""",

    "objects": """你是一个桌游规则分析专家。请从以下规则书文本中提取游戏对象类型和具体实例。

请返回一个 JSON 对象，包含：

1. "object_types": 对象类型列表，每个类型包含：
   - id: 英文标识符
   - name: 中文名称
   - deck_name: 牌库名称（如果是卡牌类型；否则为 null）
   - area_name: 对应区域名称（可选）
   - properties: 属性列表，每个属性有：
     - id: 英文标识符
     - name: 中文名称
     - type: "integer" | "float" | "text" | "boolean" | "enum" | "category_ref" | "string_list"
     - category_ref: 引用的分类 ID（type 为 category_ref 时）

2. "objects": 对象实例字典，键为 object_type 的 id，值为实例列表：
   每个实例有 id, name, properties（属性值字典）

3. "zones": 公共区域列表，每个区域有：
   - id: 英文标识符
   - name: 中文名称
   - object_type: 存放的对象类型 ID
   - auto_refill: 自动补充规则（可选），包含 source（来源牌库）和 target_size（目标数量表达式）

只返回 JSON，不要其他文字。

规则书文本：
{text}""",

    "phases": """你是一个桌游规则分析专家。请从以下规则书文本中提取游戏阶段和流程。

请返回一个 JSON 对象，包含：

1. "phases": 阶段列表（按执行顺序），每个阶段包含：
   - id: 英文标识符
   - name: 中文名称
   - auto: 是否自动执行（布尔值）
   - actions: 该阶段的主要行动描述列表

2. "phase_order": 阶段 ID 的执行顺序列表

只返回 JSON，不要其他文字。

规则书文本：
{text}""",

    "victory_and_mechanics": """你是一个桌游规则分析专家。请从以下规则书文本中提取胜利条件和特殊机制。

请返回一个 JSON 对象，包含：

1. "victory": 胜利条件对象
   - formula: 计分公式（文本描述或数学表达式）
   - end_conditions: 游戏结束条件列表
   - set_bonuses: 套装奖励列表（可选），每个包含 name, condition, bonus

2. "special_mechanics": 特殊机制列表，每个包含：
   - id: 英文标识符
   - name: 中文名称
   - description: 详细规则描述

只返回 JSON，不要其他文字。

规则书文本：
{text}""",
}


class LlmExtractor:
    """使用 LLM 从规则书文本提取 GameDefinition"""

    def __init__(self, client=None, model: str = "claude-sonnet-4-20250514"):
        self._client = client
        self.model = model

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def extract(self, rules_text: str) -> GameDefinition:
        """从规则书文本提取完整 GameDefinition"""
        logger.info("Starting LLM extraction (5 rounds)...")

        # 第1轮：元信息
        meta = self._extract_round("meta", rules_text)
        logger.info("Round 1 (meta) complete: %s", meta.get("name", "?"))

        # 第2轮：资源与分类
        resources_data = self._extract_round("resources", rules_text)
        logger.info(
            "Round 2 (resources) complete: %d resources, %d categories",
            len(resources_data.get("resources", [])),
            len(resources_data.get("categories", [])),
        )

        # 第3轮：对象
        objects_data = self._extract_round("objects", rules_text)
        logger.info(
            "Round 3 (objects) complete: %d types",
            len(objects_data.get("object_types", [])),
        )

        # 第4轮：阶段
        phases_data = self._extract_round("phases", rules_text)
        logger.info(
            "Round 4 (phases) complete: %d phases",
            len(phases_data.get("phases", [])),
        )

        # 第5轮：胜利条件和特殊机制
        victory_data = self._extract_round("victory_and_mechanics", rules_text)
        logger.info("Round 5 (victory/mechanics) complete")

        # 组装 GameDefinition
        game_def_data = {
            **meta,
            **resources_data,
            **objects_data,
            **phases_data,
            **victory_data,
            "rules_text": rules_text[:5000],
        }

        return GameDefinition(**game_def_data)

    def _extract_round(self, round_name: str, text: str) -> dict:
        """执行一轮 LLM 提取"""
        prompt_template = EXTRACTION_PROMPTS[round_name]
        prompt = prompt_template.format(text=text[:15000])

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            # 跳过 ThinkingBlock，提取第一个 TextBlock 的文本
            content = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    content = block.text
                    break

            # 尝试从 markdown 代码块中提取 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON from round '%s': %s", round_name, e)
            return {}
        except Exception as e:
            logger.error("LLM extraction round '%s' failed: %s", round_name, e)
            return {}

    def extract_dry_run(self, rules_text: str) -> dict[str, str]:
        """干运行模式 — 只返回要发送给 LLM 的 prompt（不实际调用）"""
        prompts = {}
        for round_name, template in EXTRACTION_PROMPTS.items():
            prompts[round_name] = template.format(text=rules_text[:15000])
        return prompts
