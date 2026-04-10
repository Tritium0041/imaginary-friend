"""
通用游戏管理器 (UniversalGameManager)

基于 GameDefinition 提供通用的原子操作工具，不依赖任何特定游戏的硬编码逻辑。
所有方法均为原子操作，供 GM Agent 通过工具调用。

设计原则：
- 代码只做存储和验证，GM 决定一切
- 通过名称引用对象（禁止使用内部 ID）
- 每个方法返回操作结果字典
"""
from __future__ import annotations

import logging
import math
import random
import re
import uuid
from typing import Any, Callable, Optional, TypeVar

from .game_definition import (
    GameDefinition,
    GameObjectInstance,
    ObjectTypeDef,
    ResourceScope,
)
from .model_generator import ModelGenerator

logger = logging.getLogger(__name__)
TLookup = TypeVar("TLookup")


class UniversalGameManager:
    """通用游戏管理器 — 基于 GameDefinition 的原子操作引擎"""

    def __init__(self, game_def: GameDefinition):
        self.game_def = game_def
        self.model_gen = ModelGenerator()
        self.models = self.model_gen.generate(game_def)
        self.game_state: Any = None  # 动态生成的 GameState 实例
        logger.info("UniversalGameManager initialized for '%s'", game_def.name)

    # ========== 名称解析引擎 ==========

    @staticmethod
    def _normalize_lookup_text(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _is_disallowed_identifier_reference(normalized_ref: str) -> bool:
        if not normalized_ref:
            return False
        disallowed_patterns = (
            r"(?:func|event|card|item|obj)[_\-\s]*\d+",
            r"(?:token)[_\-\s#]*\d+",
            r"第\s*\d+\s*(?:件|号|個|个)?",
        )
        return any(re.fullmatch(pattern, normalized_ref) for pattern in disallowed_patterns)

    def _resolve_named_item(
        self,
        items: list[TLookup],
        item_ref: str,
        *,
        name_getter: Callable[[TLookup], str],
        id_getter: Callable[[TLookup], str],
    ) -> tuple[TLookup | None, list[TLookup], bool]:
        """
        通过名称查找物品。

        Returns:
            (found_item, candidates, was_id_reference)
            - found_item: 精确匹配到的物品 (None if not found)
            - candidates: 模糊匹配的候选列表
            - was_id_reference: 是否使用了被禁止的 ID 引用
        """
        normalized_ref = self._normalize_lookup_text(item_ref)
        if not normalized_ref:
            return None, [], False
        if self._is_disallowed_identifier_reference(normalized_ref):
            return None, [], True

        # 检查是否匹配 ID（禁止）
        for item in items:
            if self._normalize_lookup_text(id_getter(item)) == normalized_ref:
                return None, [], True

        # 精确名称匹配
        exact = [
            item for item in items
            if self._normalize_lookup_text(name_getter(item)) == normalized_ref
        ]
        if len(exact) == 1:
            return exact[0], exact, False
        if len(exact) > 1:
            return None, exact, False

        # 模糊匹配（子串）
        partial = [
            item for item in items
            if normalized_ref in self._normalize_lookup_text(name_getter(item))
            or self._normalize_lookup_text(name_getter(item)) in normalized_ref
        ]
        if len(partial) == 1:
            return partial[0], partial, False
        if len(partial) > 1:
            return None, partial, False

        return None, [], False

    # ========== 游戏初始化 ==========

    def initialize_game(
        self,
        game_id: str | None = None,
        player_names: list | None = None,
        max_rounds: int = 10,
    ) -> dict[str, Any]:
        """根据 GameDefinition 初始化游戏。

        player_names 支持两种格式:
          - list[str]: 纯名称列表（第一个玩家默认为人类）
          - list[tuple[str, bool]]: (名称, is_human) 列表
        """
        if game_id is None:
            game_id = str(uuid.uuid4())[:8]

        if player_names is None:
            player_names = ["玩家"]

        # 统一为 (name, is_human) 格式
        normalized: list[tuple[str, bool]] = []
        for i, entry in enumerate(player_names):
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                normalized.append((str(entry[0]), bool(entry[1])))
            else:
                normalized.append((str(entry), i == 0))

        if len(normalized) < self.game_def.player_count_min:
            return {"error": f"玩家数量不足，最少需要 {self.game_def.player_count_min} 人"}
        if len(normalized) > self.game_def.player_count_max:
            return {"error": f"玩家数量过多，最多支持 {self.game_def.player_count_max} 人"}

        PlayerState = self.models["player_state"]
        GlobalState = self.models["global_state"]
        GameState = self.models["game_state"]

        # 创建玩家
        players = {}
        for i, (name, is_human) in enumerate(normalized):
            pid = f"player_{i}"
            player = PlayerState(
                id=pid,
                name=name,
                is_human=is_human,
            )
            players[pid] = player

        # 创建全局状态
        global_state = GlobalState(
            game_id=game_id,
            max_rounds=max_rounds,
            turn_order=list(players.keys()),
        )

        # 创建游戏状态
        self.game_state = GameState(
            global_state=global_state,
            players=players,
        )

        # 初始化牌库
        self._initialize_decks()

        self._add_log(f"游戏 '{self.game_def.name}' 已初始化，{len(normalized)} 位玩家")

        return {
            "status": "initialized",
            "game_id": game_id,
            "success": True,
            "players": [{"id": pid, "name": p.name} for pid, p in players.items()],
        }

    def _initialize_decks(self):
        """从 GameDefinition 的对象实例初始化所有牌库"""
        gs = self.game_state.global_state
        for obj_type in self.game_def.object_types:
            if not obj_type.deck_name:
                continue

            instances = self.game_def.objects.get(obj_type.id, [])
            deck_data = []
            for inst in instances:
                item_dict = {"id": inst.id, "name": inst.name}
                item_dict.update(inst.properties)
                deck_data.append(item_dict)

            random.shuffle(deck_data)
            deck_field = f"{obj_type.id}_deck"
            if hasattr(gs, deck_field):
                setattr(gs, deck_field, deck_data)

    # ========== 状态查询 ==========

    def get_game_state(self, include_private: bool = False) -> dict[str, Any]:
        """获取游戏状态"""
        err = self._ensure_game()
        if err:
            return err

        gs = self.game_state.global_state
        result: dict[str, Any] = {
            "game_id": gs.game_id,
            "current_round": gs.current_round,
            "max_rounds": gs.max_rounds,
            "current_phase": gs.current_phase,
            "current_player_id": gs.current_player_id,
            "turn_order": gs.turn_order,
            "active_effects": gs.active_effects,
        }

        # 全局资源
        for res in self.game_def.get_global_resources():
            if hasattr(gs, res.id):
                result[res.id] = getattr(gs, res.id)

        # 倍率
        for cat in self.game_def.get_categories_with_multiplier():
            mult_field = f"{cat.id}_multipliers"
            if hasattr(gs, mult_field):
                result[mult_field] = getattr(gs, mult_field)

        # 牌库数量
        for obj_type in self.game_def.object_types:
            if obj_type.deck_name:
                deck_field = f"{obj_type.id}_deck"
                discard_field = f"{obj_type.id}_discard_pile"
                if hasattr(gs, deck_field):
                    result[f"{deck_field}_count"] = len(getattr(gs, deck_field))
                if hasattr(gs, discard_field):
                    result[f"{discard_field}_count"] = len(getattr(gs, discard_field))

        # 公共区域内容
        for zone in self.game_def.zones:
            if hasattr(gs, zone.id):
                zone_items = getattr(gs, zone.id)
                result[zone.id] = self._items_to_public_list(zone_items)

        # 事件区
        for obj_type in self.game_def.object_types:
            if obj_type.area_name:
                area_field = f"{obj_type.id}_area"
                if hasattr(gs, area_field):
                    result[area_field] = getattr(gs, area_field)

        # 玩家信息
        players_info = {}
        for pid, player in self.game_state.players.items():
            pinfo: dict[str, Any] = {"name": player.name}
            for res in self.game_def.get_player_resources():
                if hasattr(player, res.id):
                    pinfo[res.id] = getattr(player, res.id)
            for obj_type in self.game_def.get_holdable_object_types():
                list_field = f"{obj_type.id}s"
                if hasattr(player, list_field):
                    items = getattr(player, list_field)
                    pinfo[f"{obj_type.id}_count"] = len(items)
                    if include_private or player.is_human:
                        pinfo[f"{obj_type.id}s"] = self._items_to_public_list(items)
            players_info[pid] = pinfo
        result["players"] = players_info

        return result

    # ========== 资源修改 ==========

    def update_resource(
        self,
        resource_id: str,
        delta: int,
        player_id: str | None = None,
    ) -> dict[str, Any]:
        """修改资源值"""
        err = self._ensure_game()
        if err:
            return err

        res_def = self.game_def.get_resource(resource_id)
        if not res_def:
            return {"error": f"未知资源类型: {resource_id}"}

        if res_def.scope == ResourceScope.GLOBAL:
            target = self.game_state.global_state
        else:
            if not player_id:
                return {"error": f"玩家级资源 '{resource_id}' 需要指定 player_id"}
            player = self.game_state.players.get(player_id)
            if not player:
                return {"error": f"未找到玩家: {player_id}"}
            target = player

        if not hasattr(target, resource_id):
            return {"error": f"目标对象上没有资源字段: {resource_id}"}

        old_value = getattr(target, resource_id)
        new_value = old_value + delta

        # 应用约束
        if res_def.min_value is not None:
            new_value = max(new_value, res_def.min_value)
        if res_def.max_value is not None:
            new_value = min(new_value, res_def.max_value)

        setattr(target, resource_id, new_value)

        scope_desc = f"玩家 {player_id}" if player_id else "全局"
        self._add_log(
            f"{scope_desc} {res_def.name}: {old_value} → {new_value} (delta={delta:+d})"
        )

        return {
            "resource": resource_id,
            "old_value": old_value,
            "new_value": new_value,
            "delta": delta,
        }

    # ========== 物品转移 ==========

    def transfer_object(
        self,
        object_type_id: str,
        object_name: str,
        from_location: str,
        to_location: str,
    ) -> dict[str, Any]:
        """在不同位置间转移游戏对象"""
        err = self._ensure_game()
        if err:
            return err

        obj_type = self.game_def.get_object_type(object_type_id)
        if not obj_type:
            return {"error": f"未知对象类型: {object_type_id}"}

        # 解析来源位置的物品列表
        from_items = self._get_items_at_location(object_type_id, from_location)
        if from_items is None:
            return {"error": f"无效的来源位置: {from_location}"}

        # 查找物品
        item, candidates, id_used = self._resolve_named_item(
            from_items,
            object_name,
            name_getter=lambda x: x.get("name", "") if isinstance(x, dict) else getattr(x, "name", ""),
            id_getter=lambda x: x.get("id", "") if isinstance(x, dict) else getattr(x, "id", ""),
        )

        if id_used:
            return {"error": f"请使用物品名称而非 ID 进行引用"}
        if item is None:
            if candidates:
                names = [
                    c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                    for c in candidates
                ]
                return {"error": f"找到多个匹配: {names}，请精确指定"}
            return {"error": f"在 {from_location} 中未找到 '{object_name}'"}

        # 解析目标位置
        to_items = self._get_items_at_location(object_type_id, to_location)
        if to_items is None:
            return {"error": f"无效的目标位置: {to_location}"}

        # 执行转移
        from_items.remove(item)
        to_items.append(item)

        item_name = item.get("name", "") if isinstance(item, dict) else getattr(item, "name", "")
        self._add_log(f"转移 {obj_type.name} '{item_name}': {from_location} → {to_location}")

        return {
            "transferred": item_name,
            "from": from_location,
            "to": to_location,
        }

    # ========== 抽牌 ==========

    def draw_from_deck(
        self,
        object_type_id: str,
        count: int = 1,
        target_player_id: str | None = None,
        target_zone_id: str | None = None,
    ) -> dict[str, Any]:
        """从牌库抽牌到玩家手牌或公共区域"""
        err = self._ensure_game()
        if err:
            return err

        obj_type = self.game_def.get_object_type(object_type_id)
        if not obj_type:
            return {"error": f"未知对象类型: {object_type_id}"}
        if not obj_type.deck_name:
            return {"error": f"'{obj_type.name}' 没有牌库概念"}

        gs = self.game_state.global_state
        deck_field = f"{object_type_id}_deck"
        deck = getattr(gs, deck_field, [])

        # 自动重洗弃牌堆
        if len(deck) < count:
            self._reshuffle_discard(object_type_id)
            deck = getattr(gs, deck_field, [])

        actual_count = min(count, len(deck))
        if actual_count == 0:
            return {"error": f"{obj_type.deck_name} 已空"}

        drawn = deck[:actual_count]
        setattr(gs, deck_field, deck[actual_count:])

        # 放入目标
        if target_player_id:
            player = self.game_state.players.get(target_player_id)
            if not player:
                return {"error": f"未找到玩家: {target_player_id}"}
            hand_field = f"{object_type_id}s"
            hand = getattr(player, hand_field, [])
            hand.extend(drawn)
            dest_desc = f"玩家 {player.name}"
        elif target_zone_id:
            zone_items = self._get_zone_items(target_zone_id)
            if zone_items is None:
                return {"error": f"未找到区域: {target_zone_id}"}
            zone_items.extend(drawn)
            dest_desc = target_zone_id
        else:
            return {"error": "需要指定 target_player_id 或 target_zone_id"}

        drawn_names = [
            d.get("name", "") if isinstance(d, dict) else getattr(d, "name", "")
            for d in drawn
        ]
        self._add_log(f"从 {obj_type.deck_name} 抽取 {actual_count} 张到 {dest_desc}: {drawn_names}")

        return {
            "drawn": drawn_names,
            "count": actual_count,
            "destination": dest_desc,
            "deck_remaining": len(getattr(gs, deck_field, [])),
        }

    # ========== 阶段流转 ==========

    def update_phase(self, new_phase: str) -> dict[str, Any]:
        """更新游戏阶段"""
        err = self._ensure_game()
        if err:
            return err

        phase_def = self.game_def.get_phase(new_phase)
        if not phase_def:
            valid = [p.id for p in self.game_def.phases]
            return {"error": f"无效的阶段: {new_phase}，有效值: {valid}"}

        old_phase = self.game_state.global_state.current_phase
        self.game_state.global_state.current_phase = new_phase
        self._add_log(f"阶段变更: {old_phase} → {new_phase}")

        return {"old_phase": old_phase, "new_phase": new_phase}

    def advance_round(self) -> dict[str, Any]:
        """推进到下一回合"""
        err = self._ensure_game()
        if err:
            return err

        gs = self.game_state.global_state
        old_round = gs.current_round
        gs.current_round += 1

        # 重置所有玩家的行动标记
        for player in self.game_state.players.values():
            player.has_acted = False

        # 轮换起始玩家
        if gs.turn_order:
            gs.start_player_idx = (gs.start_player_idx + 1) % len(gs.turn_order)

        self._add_log(f"进入第 {gs.current_round} 回合")

        return {
            "old_round": old_round,
            "new_round": gs.current_round,
        }

    # ========== 倍率修改 ==========

    def update_multiplier(
        self,
        category_id: str,
        value_id: str,
        delta: float,
    ) -> dict[str, Any]:
        """修改分类倍率"""
        err = self._ensure_game()
        if err:
            return err

        cat = self.game_def.get_category(category_id)
        if not cat:
            return {"error": f"未知分类: {category_id}"}
        if not cat.has_multiplier:
            return {"error": f"分类 '{cat.name}' 没有倍率机制"}

        valid_ids = {v.id for v in cat.values}
        if value_id not in valid_ids:
            return {"error": f"无效的分类值: {value_id}，有效值: {valid_ids}"}

        gs = self.game_state.global_state
        mult_field = f"{category_id}_multipliers"
        multipliers = getattr(gs, mult_field, {})

        old_value = multipliers.get(value_id, cat.initial_multiplier)
        new_value = round(old_value + delta, 2)

        # 应用约束
        min_mult, max_mult = cat.multiplier_range
        new_value = max(min_mult, min(max_mult, new_value))

        multipliers[value_id] = new_value

        value_name = next((v.name for v in cat.values if v.id == value_id), value_id)
        self._add_log(f"{cat.name} '{value_name}' 倍率: {old_value} → {new_value}")

        return {
            "category": category_id,
            "value": value_id,
            "old_multiplier": old_value,
            "new_multiplier": new_value,
        }

    # ========== 玩家管理 ==========

    def set_current_player(self, player_id: str) -> dict[str, Any]:
        """设置当前行动玩家"""
        err = self._ensure_game()
        if err:
            return err
        if player_id not in self.game_state.players:
            return {"error": f"未找到玩家: {player_id}"}
        self.game_state.global_state.current_player_id = player_id
        return {"current_player": player_id}

    def mark_player_acted(self, player_id: str) -> dict[str, Any]:
        """标记玩家已行动"""
        err = self._ensure_game()
        if err:
            return err
        player = self.game_state.players.get(player_id)
        if not player:
            return {"error": f"未找到玩家: {player_id}"}
        player.has_acted = True
        return {"player": player_id, "has_acted": True}

    def get_players_for_action(self) -> dict[str, Any]:
        """获取待行动玩家列表"""
        err = self._ensure_game()
        if err:
            return err
        pending = [
            {"id": pid, "name": p.name, "is_human": p.is_human}
            for pid, p in self.game_state.players.items()
            if not p.has_acted
        ]
        return {"pending_players": pending}

    # ========== 通信 ==========

    def broadcast_message(self, message: str, sender: str = "system") -> dict[str, Any]:
        """广播消息"""
        self._add_log(f"[{sender}] {message}")
        return {"broadcast": message, "sender": sender}

    # ========== 内部辅助 ==========

    def _ensure_game(self) -> dict[str, Any] | None:
        """确保游戏已初始化"""
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        return None

    def _add_log(self, message: str):
        """添加日志"""
        if self.game_state:
            round_num = self.game_state.global_state.current_round
            self.game_state.action_log.append(f"[回合{round_num}] {message}")

    def _get_items_at_location(
        self, object_type_id: str, location: str
    ) -> list | None:
        """获取指定位置的物品列表"""
        gs = self.game_state.global_state

        # 玩家手牌
        if location in self.game_state.players:
            player = self.game_state.players[location]
            hand_field = f"{object_type_id}s"
            if hasattr(player, hand_field):
                return getattr(player, hand_field)
            return None

        # 牌库
        deck_field = f"{object_type_id}_deck"
        if location == deck_field or location == "deck":
            if hasattr(gs, deck_field):
                return getattr(gs, deck_field)

        # 弃牌堆
        discard_field = f"{object_type_id}_discard_pile"
        if location == discard_field or location == "discard" or location == "discard_pile":
            if hasattr(gs, discard_field):
                return getattr(gs, discard_field)

        # 公共区域
        if hasattr(gs, location):
            return getattr(gs, location)

        # 事件区
        area_field = f"{object_type_id}_area"
        if location == area_field or location == "area":
            if hasattr(gs, area_field):
                return getattr(gs, area_field)

        return None

    def _get_zone_items(self, zone_id: str) -> list | None:
        """获取公共区域的物品列表"""
        gs = self.game_state.global_state
        if hasattr(gs, zone_id):
            return getattr(gs, zone_id)
        return None

    def _reshuffle_discard(self, object_type_id: str):
        """将弃牌堆洗回牌库"""
        gs = self.game_state.global_state
        deck_field = f"{object_type_id}_deck"
        discard_field = f"{object_type_id}_discard_pile"

        deck = getattr(gs, deck_field, [])
        discard = getattr(gs, discard_field, [])
        if deck or not discard:
            return

        reshuffled = list(discard)
        random.shuffle(reshuffled)
        setattr(gs, deck_field, reshuffled)
        setattr(gs, discard_field, [])

        obj_type = self.game_def.get_object_type(object_type_id)
        type_name = obj_type.name if obj_type else object_type_id
        self._add_log(f"{type_name} 弃牌堆已洗回牌库")

    @staticmethod
    def _items_to_public_list(items: list) -> list[dict]:
        """将物品列表转为公开可见的字典列表"""
        result = []
        for item in items:
            if isinstance(item, dict):
                result.append(item)
            elif hasattr(item, "model_dump"):
                result.append(item.model_dump())
            else:
                result.append({"value": str(item)})
        return result
