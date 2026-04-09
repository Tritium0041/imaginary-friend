"""
动态工具生成器 (ToolGenerator)

从 GameDefinition 自动生成 GM Agent 的工具 JSON Schema 列表。
工具分为：
- 通用工具（所有游戏共用）
- 资源工具（按 resources 生成）
- 对象工具（按 object_types 生成）
- 倍率工具（按 categories with multiplier 生成）
- 特殊机制工具（按 special_mechanics 生成）
"""
from __future__ import annotations

from typing import Any

from .game_definition import GameDefinition, ResourceScope


class ToolGenerator:
    """从 GameDefinition 动态生成工具 JSON Schema"""

    def generate(self, game_def: GameDefinition) -> list[dict[str, Any]]:
        """生成完整工具列表"""
        tools: list[dict[str, Any]] = []

        # 通用工具
        tools.extend(self._universal_tools())

        # 资源工具
        tools.extend(self._resource_tools(game_def))

        # 对象工具
        tools.extend(self._object_tools(game_def))

        # 倍率工具
        tools.extend(self._multiplier_tools(game_def))

        # 阶段工具
        tools.extend(self._phase_tools(game_def))

        # 特殊机制工具
        tools.extend(self._special_mechanic_tools(game_def))

        return tools

    @staticmethod
    def _universal_tools() -> list[dict[str, Any]]:
        """所有游戏通用的工具"""
        return [
            {
                "name": "get_game_state",
                "description": "获取当前游戏完整状态",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "include_private": {
                            "type": "boolean",
                            "description": "是否包含私有信息（如玩家手牌详情）",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "set_current_player",
                "description": "设置当前行动玩家",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {
                            "type": "string",
                            "description": "玩家ID",
                        },
                    },
                    "required": ["player_id"],
                },
            },
            {
                "name": "mark_player_acted",
                "description": "标记玩家已完成行动",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {
                            "type": "string",
                            "description": "玩家ID",
                        },
                    },
                    "required": ["player_id"],
                },
            },
            {
                "name": "get_players_for_action",
                "description": "获取尚未行动的玩家列表",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "advance_round",
                "description": "推进到下一回合",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "broadcast_message",
                "description": "向所有玩家广播消息",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "广播消息内容",
                        },
                        "sender": {
                            "type": "string",
                            "description": "发送者标识",
                        },
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "request_player_action",
                "description": "请求玩家执行行动。对人类玩家暂停等待输入，对AI玩家调用其决策",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {
                            "type": "string",
                            "description": "目标玩家ID",
                        },
                        "action_type": {
                            "type": "string",
                            "description": "行动类型",
                        },
                        "context": {
                            "type": "string",
                            "description": "行动上下文描述",
                        },
                    },
                    "required": ["player_id", "action_type"],
                },
            },
            {
                "name": "ask_human_ruling",
                "description": "向人类玩家请求规则裁定",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "需要裁定的问题",
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选方案",
                        },
                    },
                    "required": ["question"],
                },
            },
        ]

    @staticmethod
    def _resource_tools(game_def: GameDefinition) -> list[dict[str, Any]]:
        """按资源定义生成工具"""
        tools = []
        for res in game_def.resources:
            if res.scope == ResourceScope.PLAYER:
                tools.append({
                    "name": f"update_{res.id}",
                    "description": f"修改玩家的{res.name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "player_id": {
                                "type": "string",
                                "description": "玩家ID",
                            },
                            "delta": {
                                "type": "integer",
                                "description": f"{res.name}变化量（正数增加，负数减少）",
                            },
                        },
                        "required": ["player_id", "delta"],
                    },
                })
            else:
                tools.append({
                    "name": f"update_{res.id}",
                    "description": f"修改全局{res.name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "delta": {
                                "type": "integer",
                                "description": f"{res.name}变化量（正数增加，负数减少）",
                            },
                        },
                        "required": ["delta"],
                    },
                })
        return tools

    @staticmethod
    def _object_tools(game_def: GameDefinition) -> list[dict[str, Any]]:
        """按对象类型生成工具"""
        tools = []
        for obj_type in game_def.object_types:
            # 转移工具
            tools.append({
                "name": f"transfer_{obj_type.id}",
                "description": f"转移{obj_type.name} — 必须使用名称而非ID",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": f"{obj_type.name}名称（禁止填写ID）",
                        },
                        "from_location": {
                            "type": "string",
                            "description": "来源位置（玩家ID、牌库名、区域ID）",
                        },
                        "to_location": {
                            "type": "string",
                            "description": "目标位置（玩家ID、牌库名、区域ID）",
                        },
                    },
                    "required": ["object_name", "from_location", "to_location"],
                },
            })

            # 抽牌工具
            if obj_type.deck_name:
                tools.append({
                    "name": f"draw_{obj_type.id}",
                    "description": f"从{obj_type.deck_name}抽取{obj_type.name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "count": {
                                "type": "integer",
                                "description": "抽取数量",
                            },
                            "target_player_id": {
                                "type": "string",
                                "description": "目标玩家ID（与 target_zone_id 二选一）",
                            },
                            "target_zone_id": {
                                "type": "string",
                                "description": "目标区域ID（与 target_player_id 二选一）",
                            },
                        },
                        "required": ["count"],
                    },
                })

        return tools

    @staticmethod
    def _multiplier_tools(game_def: GameDefinition) -> list[dict[str, Any]]:
        """按有倍率的分类生成工具"""
        tools = []
        for cat in game_def.get_categories_with_multiplier():
            value_names = [v.name for v in cat.values]
            value_ids = [v.id for v in cat.values]
            tools.append({
                "name": f"update_{cat.id}_multiplier",
                "description": (
                    f"修改{cat.name}倍率。"
                    f"可选值: {', '.join(value_names)}。"
                    f"范围: {cat.multiplier_range[0]} ~ {cat.multiplier_range[1]}"
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "value_id": {
                            "type": "string",
                            "description": f"{cat.name}值ID",
                            "enum": value_ids,
                        },
                        "delta": {
                            "type": "number",
                            "description": "倍率变化量（正数提升，负数降低）",
                        },
                    },
                    "required": ["value_id", "delta"],
                },
            })
        return tools

    @staticmethod
    def _phase_tools(game_def: GameDefinition) -> list[dict[str, Any]]:
        """阶段流转工具"""
        phase_ids = [p.id for p in game_def.phases]
        return [
            {
                "name": "update_phase",
                "description": f"切换游戏阶段。有效阶段: {', '.join(phase_ids)}",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "new_phase": {
                            "type": "string",
                            "description": "新阶段ID",
                            "enum": phase_ids,
                        },
                    },
                    "required": ["new_phase"],
                },
            },
        ]

    @staticmethod
    def _special_mechanic_tools(game_def: GameDefinition) -> list[dict[str, Any]]:
        """特殊机制工具 — GM 通过描述了解如何使用"""
        tools = []
        for mech in game_def.special_mechanics:
            # 根据机制类型生成相应工具
            if "auction" in mech.id.lower() or "bid" in mech.id.lower():
                # 拍卖相关
                tools.append({
                    "name": f"execute_{mech.id}",
                    "description": f"执行特殊机制: {mech.name}。规则: {mech.description}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "params": {
                                "type": "object",
                                "description": "机制参数（根据规则描述传入）",
                            },
                        },
                        "required": [],
                    },
                })
            elif "trade" in mech.id.lower():
                tools.append({
                    "name": f"execute_{mech.id}",
                    "description": f"执行特殊机制: {mech.name}。规则: {mech.description}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "player_a": {"type": "string", "description": "交易方A"},
                            "player_b": {"type": "string", "description": "交易方B"},
                            "params": {
                                "type": "object",
                                "description": "交易细节",
                            },
                        },
                        "required": ["player_a", "player_b"],
                    },
                })
            else:
                # 通用特殊机制
                tools.append({
                    "name": f"execute_{mech.id}",
                    "description": f"执行特殊机制: {mech.name}。规则: {mech.description}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "params": {
                                "type": "object",
                                "description": "机制参数（根据规则描述传入）",
                            },
                        },
                        "required": [],
                    },
                })
        return tools


class ToolRouter:
    """工具调用路由器 — 将工具名分发到 UniversalGameManager 方法"""

    def __init__(self, game_def: GameDefinition, manager):
        self.game_def = game_def
        self.manager = manager
        self._routes = self._build_routes()

    def _build_routes(self) -> dict[str, callable]:
        """构建工具名 → 处理函数的映射"""
        routes = {}

        # 通用工具
        routes["get_game_state"] = self._handle_get_game_state
        routes["set_current_player"] = self._handle_set_current_player
        routes["mark_player_acted"] = self._handle_mark_player_acted
        routes["get_players_for_action"] = self._handle_get_players_for_action
        routes["advance_round"] = self._handle_advance_round
        routes["broadcast_message"] = self._handle_broadcast_message
        routes["update_phase"] = self._handle_update_phase

        # 资源工具
        for res in self.game_def.resources:
            tool_name = f"update_{res.id}"
            routes[tool_name] = self._make_resource_handler(res.id, res.scope)

        # 对象工具
        for obj_type in self.game_def.object_types:
            routes[f"transfer_{obj_type.id}"] = self._make_transfer_handler(obj_type.id)
            if obj_type.deck_name:
                routes[f"draw_{obj_type.id}"] = self._make_draw_handler(obj_type.id)

        # 倍率工具
        for cat in self.game_def.get_categories_with_multiplier():
            routes[f"update_{cat.id}_multiplier"] = self._make_multiplier_handler(cat.id)

        return routes

    def route(self, tool_name: str, params: dict) -> dict:
        """路由工具调用"""
        handler = self._routes.get(tool_name)
        if handler:
            return handler(params)
        return {"error": f"未知工具: {tool_name}"}

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._routes

    # --- 通用工具处理器 ---

    def _handle_get_game_state(self, params: dict) -> dict:
        return self.manager.get_game_state(
            include_private=params.get("include_private", False)
        )

    def _handle_set_current_player(self, params: dict) -> dict:
        return self.manager.set_current_player(params["player_id"])

    def _handle_mark_player_acted(self, params: dict) -> dict:
        return self.manager.mark_player_acted(params["player_id"])

    def _handle_get_players_for_action(self, params: dict) -> dict:
        return self.manager.get_players_for_action()

    def _handle_advance_round(self, params: dict) -> dict:
        return self.manager.advance_round()

    def _handle_broadcast_message(self, params: dict) -> dict:
        return self.manager.broadcast_message(
            params["message"], sender=params.get("sender", "GM")
        )

    def _handle_update_phase(self, params: dict) -> dict:
        return self.manager.update_phase(params["new_phase"])

    # --- 工厂方法创建参数化处理器 ---

    def _make_resource_handler(self, resource_id: str, scope):
        def handler(params: dict) -> dict:
            player_id = params.get("player_id")
            delta = params.get("delta", 0)
            return self.manager.update_resource(resource_id, delta, player_id)
        return handler

    def _make_transfer_handler(self, object_type_id: str):
        def handler(params: dict) -> dict:
            return self.manager.transfer_object(
                object_type_id,
                params["object_name"],
                params["from_location"],
                params["to_location"],
            )
        return handler

    def _make_draw_handler(self, object_type_id: str):
        def handler(params: dict) -> dict:
            return self.manager.draw_from_deck(
                object_type_id,
                count=params.get("count", 1),
                target_player_id=params.get("target_player_id"),
                target_zone_id=params.get("target_zone_id"),
            )
        return handler

    def _make_multiplier_handler(self, category_id: str):
        def handler(params: dict) -> dict:
            return self.manager.update_multiplier(
                category_id,
                params["value_id"],
                params.get("delta", 0),
            )
        return handler
