"""
动态 Pydantic 模型生成器

从 GameDefinition 自动生成运行时 Pydantic 模型：
- 枚举类（从 categories）
- 游戏对象模型（从 object_types）
- PlayerState 模型（从 resources + object_types）
- GlobalState 模型（从 resources + categories + zones + phases）
- GameState 模型
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, create_model

from .game_definition import (
    CategoryDef,
    GameDefinition,
    ObjectTypeDef,
    PropertyDef,
    PropertyType,
    ResourceScope,
)


class ModelGenerator:
    """从 GameDefinition 动态生成 Pydantic 模型"""

    def generate(self, game_def: GameDefinition) -> dict[str, Any]:
        """
        返回生成的模型类字典。

        键包括:
        - "{category_id}_enum": 枚举类
        - "{object_type_id}": 对象模型类
        - "player_state": 玩家状态模型
        - "global_state": 全局状态模型
        - "game_state": 完整游戏状态模型
        """
        models: dict[str, Any] = {}

        # 1. 生成枚举类
        for cat in game_def.categories:
            enum_cls = self._create_enum(cat)
            models[f"{cat.id}_enum"] = enum_cls

        # 2. 生成游戏对象模型
        for obj_type in game_def.object_types:
            model_cls = self._create_object_model(obj_type, game_def)
            models[obj_type.id] = model_cls

        # 3. 生成玩家状态模型
        models["player_state"] = self._create_player_state(game_def, models)

        # 4. 生成全局状态模型
        models["global_state"] = self._create_global_state(game_def, models)

        # 5. 生成完整游戏状态
        models["game_state"] = self._create_game_state(models)

        return models

    @staticmethod
    def _create_enum(category: CategoryDef) -> type:
        """从分类定义创建枚举"""
        members = {v.id.upper(): v.id for v in category.values}
        return Enum(category.id.title(), members, type=str)

    def _create_object_model(
        self, obj_type: ObjectTypeDef, game_def: GameDefinition
    ) -> type[BaseModel]:
        """从对象类型定义创建 Pydantic 模型"""
        fields: dict[str, Any] = {
            "id": (str, ...),
            "name": (str, ...),
        }

        for prop in obj_type.properties:
            field_type, field_default = self._property_to_field(prop, game_def)
            fields[prop.id] = (field_type, field_default)

        model_name = "".join(
            part.capitalize() for part in obj_type.id.split("_")
        )
        return create_model(model_name, **fields)

    def _create_player_state(
        self, game_def: GameDefinition, models: dict[str, Any]
    ) -> type[BaseModel]:
        """生成玩家状态模型"""
        fields: dict[str, Any] = {
            "id": (str, ...),
            "name": (str, ...),
            "is_human": (bool, False),
            "has_acted": (bool, False),
        }

        # 添加每个玩家级资源
        for res in game_def.resources:
            if res.scope == ResourceScope.PLAYER:
                fields[res.id] = (int, Field(default=res.initial_value))

        # 添加每种可持有对象的列表
        for obj_type in game_def.object_types:
            if obj_type.deck_name:
                list_field_name = f"{obj_type.id}s"
                fields[list_field_name] = (list, Field(default_factory=list))

        return create_model("PlayerState", **fields)

    def _create_global_state(
        self, game_def: GameDefinition, models: dict[str, Any]
    ) -> type[BaseModel]:
        """生成全局状态模型"""
        fields: dict[str, Any] = {
            "game_id": (str, ...),
            "current_round": (int, Field(default=1)),
            "max_rounds": (int, Field(default=10)),
            "current_phase": (str, Field(default="setup")),
            "current_player_id": (Optional[str], None),
            "turn_order": (list[str], Field(default_factory=list)),
            "start_player_idx": (int, 0),
            "active_effects": (list[str], Field(default_factory=list)),
        }

        # 全局资源
        for res in game_def.resources:
            if res.scope == ResourceScope.GLOBAL:
                fields[res.id] = (int, Field(default=res.initial_value))

        # 倍率系统
        for cat in game_def.categories:
            if cat.has_multiplier:
                default_multipliers = {
                    v.id: cat.initial_multiplier for v in cat.values
                }
                fields[f"{cat.id}_multipliers"] = (
                    dict[str, float],
                    Field(default_factory=lambda d=default_multipliers: dict(d)),
                )

        # 牌库和弃牌堆（per object_type with deck_name）
        for obj_type in game_def.object_types:
            if obj_type.deck_name:
                # 牌库
                deck_field = f"{obj_type.id}_deck"
                fields[deck_field] = (list, Field(default_factory=list))
                # 弃牌堆
                discard_field = f"{obj_type.id}_discard_pile"
                fields[discard_field] = (list, Field(default_factory=list))

        # 公共区域
        for zone in game_def.zones:
            # 跳过已经通过牌库/弃牌堆覆盖的区域
            if zone.id.endswith("_discard_pile"):
                continue
            if zone.id not in fields:
                fields[zone.id] = (list, Field(default_factory=list))

        # 事件区（如果对象类型有 area_name）
        for obj_type in game_def.object_types:
            if obj_type.area_name:
                area_field = f"{obj_type.id}_area"
                if area_field not in fields:
                    fields[area_field] = (list, Field(default_factory=list))

        return create_model("GlobalState", **fields)

    @staticmethod
    def _create_game_state(models: dict[str, Any]) -> type[BaseModel]:
        """生成完整游戏状态"""
        player_state_cls = models["player_state"]
        global_state_cls = models["global_state"]
        fields: dict[str, Any] = {
            "global_state": (global_state_cls, ...),
            "players": (dict[str, player_state_cls], Field(default_factory=dict)),
            "action_log": (list[str], Field(default_factory=list)),
        }
        return create_model("GameState", **fields)

    @staticmethod
    def _property_to_field(
        prop: PropertyDef, game_def: GameDefinition
    ) -> tuple[type, Any]:
        """将属性定义转为 Pydantic 字段类型和默认值"""
        match prop.type:
            case PropertyType.INTEGER:
                return int, Field(default=prop.default if prop.default is not None else 0)
            case PropertyType.FLOAT:
                return float, Field(default=prop.default if prop.default is not None else 0.0)
            case PropertyType.TEXT:
                return str, Field(default=prop.default if prop.default is not None else "")
            case PropertyType.BOOLEAN:
                return bool, Field(default=prop.default if prop.default is not None else False)
            case PropertyType.ENUM:
                return str, Field(default=prop.default if prop.default is not None else "")
            case PropertyType.CATEGORY_REF:
                return str, Field(default=prop.default if prop.default is not None else "")
            case PropertyType.STRING_LIST:
                return list[str], Field(default_factory=list)
            case _:
                return str, Field(default="")
