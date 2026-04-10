"""
通用桌游 GameDefinition 数据模型

GameDefinition 是通用桌游框架的核心数据结构，描述"一个桌游是什么"。
它定义了游戏的资源系统、分类系统、对象类型、公共区域、阶段流程、
胜利条件、特殊机制等所有结构化信息。

通过将桌游规则形式化为 GameDefinition，系统可以：
1. 自动生成状态管理器（动态 Pydantic 模型）
2. 自动生成 GM 工具集（Claude tool schema）
3. 自动生成 GM 系统 Prompt
4. 缓存并复用生成结果
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class ResourceScope(str, Enum):
    """资源作用域"""
    PLAYER = "player"   # 每个玩家独立
    GLOBAL = "global"   # 全局共享


class ResourceDef(BaseModel):
    """资源类型定义（如：金币、生命值、胜利点数）"""
    id: str
    name: str
    icon: str = ""
    scope: ResourceScope = ResourceScope.PLAYER
    initial_value: int = 0
    min_value: Optional[int] = 0
    max_value: Optional[int] = None


class CategoryValue(BaseModel):
    """分类中的一个取值"""
    id: str
    name: str
    icon: str = ""


class CategoryDef(BaseModel):
    """分类系统定义（如：阵营、颜色、时代）"""
    id: str
    name: str
    values: list[CategoryValue]
    has_multiplier: bool = False
    multiplier_range: tuple[float, float] = (0.5, 2.5)
    initial_multiplier: float = 1.0


class PropertyType(str, Enum):
    """属性数据类型"""
    INTEGER = "integer"
    TEXT = "text"
    ENUM = "enum"
    CATEGORY_REF = "category_ref"
    STRING_LIST = "string_list"
    BOOLEAN = "boolean"
    FLOAT = "float"


class PropertyDef(BaseModel):
    """游戏对象的属性定义"""
    id: str
    type: PropertyType
    name: str = ""
    category: Optional[str] = None  # PropertyType.CATEGORY_REF 时引用的分类 ID
    values: Optional[list[str]] = None  # PropertyType.ENUM 时的可选值
    min: Optional[int] = None
    max: Optional[int] = None
    default: Optional[Any] = None


class ObjectTypeDef(BaseModel):
    """游戏对象类型定义（如：卡牌、Token、棋子）"""
    id: str
    name: str
    properties: list[PropertyDef] = Field(default_factory=list)
    deck_name: Optional[str] = None     # 有牌库概念时的牌库名称
    hand_limit: Optional[int] = None    # 手牌上限（None 表示无限制）
    area_name: Optional[str] = None     # 公共展示区名称
    area_size: Optional[int] = None     # 展示区容量


class AutoRefillDef(BaseModel):
    """自动补充规则"""
    source: str                          # 来源牌库 ID
    target_size: str                     # 目标数量表达式（如 "player_count + 1"）
    extra_condition: Optional[str] = None  # 额外条件（如 "stability < 30 → +1"）


class ZoneDef(BaseModel):
    """公共区域定义（如：拍卖区、弃牌堆）"""
    id: str
    name: str
    object_type: str                     # 存放的对象类型 ID
    auto_refill: Optional[AutoRefillDef] = None


class PhaseDef(BaseModel):
    """游戏阶段定义"""
    id: str
    name: str
    auto: bool = False                   # 是否系统自动执行
    actions: list[str] = Field(default_factory=list)
    player_interaction: Optional[str] = None  # sequential_polling / simultaneous / none
    trigger_condition: Optional[str] = None   # 触发条件表达式


class SetBonusDef(BaseModel):
    """套装奖励定义"""
    name: str
    condition: str
    bonus: int


class VictoryDef(BaseModel):
    """胜利条件定义"""
    formula: str
    end_conditions: list[str]
    set_bonuses: list[SetBonusDef] = Field(default_factory=list)


class SpecialMechanicDef(BaseModel):
    """特殊机制定义"""
    id: str
    name: str
    description: str


class GameObjectInstance(BaseModel):
    """游戏对象实例数据（如一张具体的卡牌）"""
    id: str
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GameDefinition(BaseModel):
    """
    通用游戏定义 — 描述一个桌游的完整结构。

    这是整个通用框架的中心数据结构。用户可以通过以下方式创建：
    1. 从 PDF 规则书自动解析
    2. 手动编写 JSON/YAML
    3. 通过 Web UI 可视化编辑
    """
    # 元信息
    id: str = ""
    name: str
    name_en: str = ""
    description: str = ""
    player_count_min: int = 2
    player_count_max: int = 6
    version: str = "1.0"

    # 资源系统
    resources: list[ResourceDef] = Field(default_factory=list)

    # 分类系统
    categories: list[CategoryDef] = Field(default_factory=list)

    # 游戏对象类型
    object_types: list[ObjectTypeDef] = Field(default_factory=list)

    # 公共区域
    zones: list[ZoneDef] = Field(default_factory=list)

    # 阶段定义
    phases: list[PhaseDef] = Field(default_factory=list)
    phase_order: list[str] = Field(default_factory=list)

    # 胜利条件
    victory: Optional[VictoryDef] = None

    # 特殊机制
    special_mechanics: list[SpecialMechanicDef] = Field(default_factory=list)

    # 游戏流程概述（≤1000字，帮助 LLM 理解游戏玩法）
    gameplay_overview: str = ""

    # 完整规则文本（用于 GM Prompt 注入）
    rules_text: str = ""

    # 游戏对象实例数据，按对象类型分组
    # 例如: {"artifact": [GameObjectInstance(...)], "function_card": [...]}
    objects: dict[str, list[GameObjectInstance]] = Field(default_factory=dict)

    # --- 辅助方法 ---

    def get_resource(self, resource_id: str) -> Optional[ResourceDef]:
        """根据 ID 查找资源定义"""
        for r in self.resources:
            if r.id == resource_id:
                return r
        return None

    def get_category(self, category_id: str) -> Optional[CategoryDef]:
        """根据 ID 查找分类定义"""
        for c in self.categories:
            if c.id == category_id:
                return c
        return None

    def get_object_type(self, type_id: str) -> Optional[ObjectTypeDef]:
        """根据 ID 查找对象类型定义"""
        for o in self.object_types:
            if o.id == type_id:
                return o
        return None

    def get_zone(self, zone_id: str) -> Optional[ZoneDef]:
        """根据 ID 查找区域定义"""
        for z in self.zones:
            if z.id == zone_id:
                return z
        return None

    def get_phase(self, phase_id: str) -> Optional[PhaseDef]:
        """根据 ID 查找阶段定义"""
        for p in self.phases:
            if p.id == phase_id:
                return p
        return None

    def get_player_resources(self) -> list[ResourceDef]:
        """获取所有玩家级资源"""
        return [r for r in self.resources if r.scope == ResourceScope.PLAYER]

    def get_global_resources(self) -> list[ResourceDef]:
        """获取所有全局资源"""
        return [r for r in self.resources if r.scope == ResourceScope.GLOBAL]

    def get_categories_with_multiplier(self) -> list[CategoryDef]:
        """获取所有带倍率机制的分类"""
        return [c for c in self.categories if c.has_multiplier]

    def get_holdable_object_types(self) -> list[ObjectTypeDef]:
        """获取玩家可持有的对象类型（有 deck_name 的类型）"""
        return [o for o in self.object_types if o.deck_name]

    @classmethod
    def load_from_file(cls, path: str | Path) -> GameDefinition:
        """从 JSON 文件加载 GameDefinition"""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def save_to_file(self, path: str | Path) -> None:
        """保存 GameDefinition 到 JSON 文件"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2, exclude_none=True))
