"""
动态 Prompt 生成器 (PromptGenerator)

从 GameDefinition 自动生成 GM Agent 的系统 Prompt。
包含：游戏概述、初始设置、阶段流程、胜利条件、工具使用指南。
"""
from __future__ import annotations

from typing import Any

from .game_definition import GameDefinition, ResourceScope


class PromptGenerator:
    """从 GameDefinition 动态生成 GM 系统 Prompt"""

    def generate(self, game_def: GameDefinition, tools: list[dict] | None = None) -> str:
        """生成完整的 GM 系统 Prompt"""
        sections = [
            self._header(game_def),
            self._game_overview(game_def),
            self._setup_instructions(game_def),
            self._resources_section(game_def),
            self._categories_section(game_def),
            self._object_types_section(game_def),
            self._zones_section(game_def),
            self._phases_section(game_def),
            self._victory_section(game_def),
            self._special_mechanics_section(game_def),
            self._tool_usage_guide(game_def, tools),
            self._general_guidelines(),
        ]

        if game_def.rules_text:
            sections.append(self._rules_reference(game_def))

        return "\n\n".join(s for s in sections if s)

    @staticmethod
    def _header(game_def: GameDefinition) -> str:
        name = game_def.name
        if game_def.name_en:
            name += f" ({game_def.name_en})"
        return f"# {name} — 游戏主持人 (GM) 指南"

    @staticmethod
    def _game_overview(game_def: GameDefinition) -> str:
        lines = ["## 游戏概述", ""]
        lines.append(f"你是 **{game_def.name}** 的游戏主持人 (GM)。")
        lines.append("你负责主持整局游戏，确保规则正确执行，并为玩家提供沉浸式体验。")
        if game_def.description:
            lines.append(f"\n**游戏简介**: {game_def.description}")
        lines.append(f"\n- 玩家人数: {game_def.player_count_min}~{game_def.player_count_max}")
        return "\n".join(lines)

    @staticmethod
    def _setup_instructions(game_def: GameDefinition) -> str:
        lines = ["## 游戏设置", ""]
        lines.append("游戏开始时，你需要完成以下设置：")
        idx = 1

        for res in game_def.resources:
            if res.scope == ResourceScope.PLAYER:
                lines.append(f"{idx}. 每位玩家获得 **{res.initial_value} {res.name}**")
                idx += 1
            else:
                lines.append(f"{idx}. {res.name}初始值为 **{res.initial_value}**")
                idx += 1

        for cat in game_def.categories:
            if cat.has_multiplier:
                lines.append(
                    f"{idx}. 所有{cat.name}倍率初始为 ×{cat.initial_multiplier}"
                )
                idx += 1

        for zone in game_def.zones:
            if zone.auto_refill:
                lines.append(
                    f"{idx}. {zone.name}初始填充目标: {zone.auto_refill.target_size}"
                )
                idx += 1

        return "\n".join(lines)

    @staticmethod
    def _resources_section(game_def: GameDefinition) -> str:
        if not game_def.resources:
            return ""
        lines = ["## 资源系统", ""]
        for res in game_def.resources:
            scope = "玩家级" if res.scope == ResourceScope.PLAYER else "全局"
            constraint = ""
            if res.min_value is not None or res.max_value is not None:
                parts = []
                if res.min_value is not None:
                    parts.append(f"最小值={res.min_value}")
                if res.max_value is not None:
                    parts.append(f"最大值={res.max_value}")
                constraint = f"（{', '.join(parts)}）"
            lines.append(f"- **{res.name}** ({scope}): 初始值 {res.initial_value}{constraint}")
        return "\n".join(lines)

    @staticmethod
    def _categories_section(game_def: GameDefinition) -> str:
        if not game_def.categories:
            return ""
        lines = ["## 分类系统", ""]
        for cat in game_def.categories:
            value_names = ", ".join(v.name for v in cat.values)
            lines.append(f"### {cat.name}")
            lines.append(f"可选值: {value_names}")
            if cat.has_multiplier:
                lines.append(
                    f"- 倍率范围: ×{cat.multiplier_range[0]} ~ ×{cat.multiplier_range[1]}"
                )
                lines.append(f"- 初始倍率: ×{cat.initial_multiplier}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _object_types_section(game_def: GameDefinition) -> str:
        if not game_def.object_types:
            return ""
        lines = ["## 游戏对象", ""]
        for obj_type in game_def.object_types:
            lines.append(f"### {obj_type.name}")
            if obj_type.deck_name:
                lines.append(f"- 牌库: {obj_type.deck_name}")
            count = len(game_def.objects.get(obj_type.id, []))
            lines.append(f"- 总数: {count}")
            if obj_type.properties:
                prop_names = ", ".join(p.name for p in obj_type.properties)
                lines.append(f"- 属性: {prop_names}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _zones_section(game_def: GameDefinition) -> str:
        if not game_def.zones:
            return ""
        lines = ["## 公共区域", ""]
        for zone in game_def.zones:
            lines.append(f"- **{zone.name}** (ID: {zone.id}): 存放{zone.object_type}")
            if zone.auto_refill:
                lines.append(f"  - 自动补充到: {zone.auto_refill.target_size}")
        return "\n".join(lines)

    @staticmethod
    def _phases_section(game_def: GameDefinition) -> str:
        if not game_def.phases:
            return ""
        lines = ["## 游戏阶段", ""]
        order = game_def.phase_order or [p.id for p in game_def.phases]
        for i, phase_id in enumerate(order, 1):
            phase = game_def.get_phase(phase_id)
            if phase:
                auto_tag = " (自动)" if phase.auto else ""
                lines.append(f"### {i}. {phase.name} ({phase.id}){auto_tag}")
                if phase.actions:
                    for action in phase.actions:
                        lines.append(f"  - {action}")
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _victory_section(game_def: GameDefinition) -> str:
        if not game_def.victory:
            return ""
        lines = ["## 胜利条件", ""]
        v = game_def.victory
        if v.formula:
            lines.append(f"**计分公式**: `{v.formula}`")
        if v.end_conditions:
            lines.append("\n**游戏结束条件**:")
            for cond in v.end_conditions:
                lines.append(f"- {cond}")
        if v.set_bonuses:
            lines.append("\n**套装奖励**:")
            for bonus in v.set_bonuses:
                lines.append(f"- {bonus.name}: {bonus.condition} → +{bonus.bonus}分")
        return "\n".join(lines)

    @staticmethod
    def _special_mechanics_section(game_def: GameDefinition) -> str:
        if not game_def.special_mechanics:
            return ""
        lines = ["## 特殊机制", ""]
        for mech in game_def.special_mechanics:
            lines.append(f"### {mech.name}")
            lines.append(mech.description)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _tool_usage_guide(game_def: GameDefinition, tools: list[dict] | None) -> str:
        lines = ["## 工具使用指南", ""]
        lines.append("你通过调用以下工具来操作游戏：")
        lines.append("")

        lines.append("### 核心原则")
        lines.append("- **禁止使用内部 ID 引用物品**：必须使用物品名称")
        lines.append("- **每次操作都是原子的**：一个工具调用完成一个操作")
        lines.append("- **先查询再操作**：调用 `get_game_state` 确认状态后再做修改")
        lines.append("")

        if tools:
            lines.append("### 可用工具列表")
            for tool in tools:
                lines.append(f"- `{tool['name']}`: {tool['description']}")

        return "\n".join(lines)

    @staticmethod
    def _general_guidelines() -> str:
        return """## 通用指南

### 你的职责
1. 严格按照游戏规则推进流程
2. 公正裁判所有争议
3. 提供沉浸式的游戏解说
4. 确保每位玩家都有机会行动

### 行为准则
- 每个阶段开始时，用 `broadcast_message` 宣布阶段名称和主要内容
- 需要玩家行动时，用 `request_player_action` 请求
- 遇到规则模糊时，用 `ask_human_ruling` 询问
- 每次状态变更后，简要说明变更内容
- 保持游戏节奏，避免不必要的等待"""

    @staticmethod
    def _rules_reference(game_def: GameDefinition) -> str:
        return f"""## 完整规则参考

以下是游戏的完整规则文本，在裁定时以此为准：

---
{game_def.rules_text}
---"""
