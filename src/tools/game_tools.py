"""
游戏工具函数 - MCP 工具实现
提供原子操作供 GM Agent 调用，不包含游戏流程逻辑
"""
from __future__ import annotations

import logging
from typing import Optional
import uuid
import random
import math
import re
from ..models import (
    Era,
    GamePhase,
    AuctionType,
    Artifact,
    FunctionCard,
    Rarity,
    PlayerState,
    AuctionItem,
    GlobalState,
    GameState,
)
from ..data import (
    get_shuffled_artifact_deck,
    get_shuffled_function_deck,
    get_shuffled_event_deck,
)
from ..utils import bind_context

logger = logging.getLogger(__name__)


class GameManager:
    """游戏管理器 - 提供原子操作工具"""
    
    def __init__(self):
        self.game_state: Optional[GameState] = None
        logger.info("GameManager initialized")

    def _ensure_game(self) -> tuple[Optional[GameState], Optional[GlobalState], Optional[dict]]:
        if self.game_state is None:
            return None, None, {"error": "游戏未初始化"}
        return self.game_state, self.game_state.global_state, None

    def _reshuffle_function_discard_if_needed(self):
        assert self.game_state is not None
        gs = self.game_state.global_state
        if gs.card_deck:
            return
        if not gs.card_discard_pile:
            return
        gs.card_deck = [c.model_copy(deep=True) for c in gs.card_discard_pile]
        random.shuffle(gs.card_deck)
        gs.card_discard_pile.clear()
        self.game_state.add_log("功能卡弃牌堆已洗回牌库")

    def _reshuffle_event_discard_if_needed(self):
        assert self.game_state is not None
        gs = self.game_state.global_state
        if gs.event_deck:
            return
        if not gs.event_discard_pile:
            return
        gs.event_deck = [e.model_copy(deep=True) for e in gs.event_discard_pile]
        random.shuffle(gs.event_deck)
        gs.event_discard_pile.clear()
        self.game_state.add_log("事件卡弃牌堆已洗回牌库")

    @staticmethod
    def _normalize_lookup_text(value: str) -> str:
        return value.strip().lower()

    def _resolve_auction_item_reference(
        self,
        item_ref: str,
    ) -> tuple[int | None, AuctionItem | None]:
        """解析拍卖区物品引用，支持真实ID、位置别名与名称匹配。"""
        assert self.game_state is not None
        pool = self.game_state.global_state.auction_pool
        normalized_ref = self._normalize_lookup_text(item_ref)
        if not normalized_ref:
            return None, None

        for idx, auction_item in enumerate(pool):
            if self._normalize_lookup_text(auction_item.artifact.id) == normalized_ref:
                return idx, auction_item

        alias_patterns = (
            r"(?:artifact|item|auction(?:_item)?)?[_\-\s#]*([1-9]\d*)",
            r"文物[_\-\s#]*([1-9]\d*)",
            r"第\s*([1-9]\d*)\s*(?:件|号|個|个)?",
        )
        for pattern in alias_patterns:
            matched = re.fullmatch(pattern, normalized_ref)
            if not matched:
                continue
            index = int(matched.group(1)) - 1
            if 0 <= index < len(pool):
                return index, pool[index]
            return None, None

        exact_name_matches = [
            (idx, auction_item)
            for idx, auction_item in enumerate(pool)
            if self._normalize_lookup_text(auction_item.artifact.name) == normalized_ref
        ]
        if len(exact_name_matches) == 1:
            return exact_name_matches[0]

        partial_name_matches = [
            (idx, auction_item)
            for idx, auction_item in enumerate(pool)
            if normalized_ref in self._normalize_lookup_text(auction_item.artifact.name)
            or self._normalize_lookup_text(auction_item.artifact.name) in normalized_ref
        ]
        if len(partial_name_matches) == 1:
            return partial_name_matches[0]

        return None, None

    def _list_auction_pool_brief(self) -> list[dict[str, str]]:
        assert self.game_state is not None
        return [
            {
                "id": auction_item.artifact.id,
                "name": auction_item.artifact.name,
                "alias": f"artifact_{idx + 1}",
            }
            for idx, auction_item in enumerate(self.game_state.global_state.auction_pool)
        ]
    
    def initialize_game(
        self, 
        game_id: str | None = None,
        player_names: list[tuple[str, bool]] | None = None,  # (name, is_human)
        max_rounds: int = 10,
        initial_money: int = 20,
    ) -> dict:
        """
        初始化新游戏
        
        Args:
            game_id: 游戏ID，默认自动生成
            player_names: 玩家列表，每项为 (名称, 是否人类)
            max_rounds: 最大回合数
            initial_money: 初始资金
            
        Returns:
            初始化结果信息
        """
        if game_id is None:
            game_id = str(uuid.uuid4())[:8]
        game_logger = bind_context(logger, game_id=game_id)
        game_logger.info(
            "Initializing game (players=%s, max_rounds=%s, initial_money=%s)",
            len(player_names or []),
            max_rounds,
            initial_money,
        )
        
        if player_names is None:
            player_names = [("玩家", True)]
        
        # 创建全局状态并加载牌库
        global_state = GlobalState(
            game_id=game_id,
            max_rounds=max_rounds,
            current_phase=GamePhase.SETUP,
            artifact_deck=get_shuffled_artifact_deck(),
            card_deck=get_shuffled_function_deck(),
            event_deck=[e.model_copy(deep=True) for e in get_shuffled_event_deck()],
        )

        # 创建玩家并发初始手牌
        players: dict[str, PlayerState] = {}
        turn_order: list[str] = []
        for i, (name, is_human) in enumerate(player_names):
            player_id = f"player_{i}"
            players[player_id] = PlayerState(
                id=player_id,
                name=name,
                is_human=is_human,
                money=initial_money,
            )
            turn_order.append(player_id)

        global_state.turn_order = turn_order
        self.game_state = GameState(global_state=global_state, players=players)
        game_logger.info("Global state and players created")

        # 每位玩家发2张功能卡
        initial_dealt_cards = 0
        for player_id in turn_order:
            draw_result = self.draw_function_cards(player_id=player_id, count=2)
            if "error" in draw_result:
                game_logger.error("Initial function draw failed: %s", draw_result["error"])
                return draw_result
            initial_dealt_cards += draw_result["drawn_count"]

        # 拍卖区初始填充 玩家数+1 张文物
        target_pool_size = len(players) + 1
        refill_result = self.refill_auction_pool(target_size=target_pool_size)
        if "error" in refill_result:
            game_logger.error("Initial auction refill failed: %s", refill_result["error"])
            return refill_result

        # 事件区初始翻开2张事件卡
        for _ in range(2):
            draw_event_result = self.draw_event_to_area()
            if "error" in draw_event_result:
                game_logger.error("Initial event draw failed: %s", draw_event_result["error"])
                return draw_event_result

        self.game_state.add_log(
            f"游戏初始化完成，共 {len(players)} 名玩家；"
            f"已发放功能卡 {initial_dealt_cards} 张；"
            f"拍卖区 {len(self.game_state.global_state.auction_pool)} 件；"
            f"事件区 {len(self.game_state.global_state.event_area)} 张"
        )
        game_logger.info("Game initialized successfully")

        return {
            "success": True,
            "game_id": game_id,
            "player_count": len(players),
            "message": f"游戏 {game_id} 创建成功",
            "initial_cards_dealt": initial_dealt_cards,
            "initial_auction_pool_count": len(self.game_state.global_state.auction_pool),
            "initial_event_count": len(self.game_state.global_state.event_area),
        }
    
    def get_game_state(self, include_private: bool = False) -> dict:
        """
        获取游戏状态
        
        Args:
            include_private: 是否包含私有信息（仅 GM 可用）
            
        Returns:
            游戏状态字典
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        if include_private:
            return self.game_state.model_dump()
        else:
            return self.game_state.get_public_state()
    
    def get_player_private_state(self, player_id: str) -> dict:
        """
        获取玩家私有状态（手牌等）
        
        Args:
            player_id: 玩家ID
            
        Returns:
            玩家完整状态
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        player = self.game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}
        
        return player.model_dump()

    def draw_function_cards(self, player_id: str, count: int = 1) -> dict:
        """为指定玩家抽取功能卡"""
        game_state, gs, error = self._ensure_game()
        if error:
            return error
        assert game_state is not None and gs is not None
        game_logger = bind_context(logger, game_id=gs.game_id)

        if count <= 0:
            return {"error": "抽卡数量必须大于0"}

        player = game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}

        drawn_cards: list[FunctionCard] = []
        for _ in range(count):
            self._reshuffle_function_discard_if_needed()
            if not gs.card_deck:
                break
            drawn_cards.append(gs.card_deck.pop(0))

        if not drawn_cards:
            game_logger.warning("Function draw failed: deck empty")
            return {"error": "功能卡牌库为空，无法抽牌"}

        player.function_cards.extend(drawn_cards)
        game_state.add_log(f"{player.name} 抽取功能卡 {len(drawn_cards)} 张")
        game_logger.info("Function cards drawn for %s: %s", player_id, len(drawn_cards))

        return {
            "success": True,
            "player_id": player_id,
            "drawn_count": len(drawn_cards),
            "drawn_cards": [c.model_dump() for c in drawn_cards],
            "remaining_deck_count": len(gs.card_deck),
        }

    def refill_auction_pool(self, target_size: int | None = None, extra_slots: int = 0) -> dict:
        """从文物牌库补充拍卖区到目标数量"""
        game_state, gs, error = self._ensure_game()
        if error:
            return error
        assert game_state is not None and gs is not None
        game_logger = bind_context(logger, game_id=gs.game_id)

        if target_size is None:
            target_size = len(game_state.players) + 1
        if target_size < 0:
            return {"error": "target_size 不能为负数"}
        if extra_slots < 0:
            return {"error": "extra_slots 不能为负数"}

        effective_target = target_size + extra_slots
        # 稳定性进入警告区，拍卖区每次多补1张
        if gs.stability < 30:
            effective_target += 1

        added: list[Artifact] = []
        while len(gs.auction_pool) < effective_target and gs.artifact_deck:
            artifact = gs.artifact_deck.pop(0)
            gs.auction_pool.append(
                AuctionItem(artifact=artifact, auction_type=artifact.auction_type)
            )
            added.append(artifact)

        if added:
            game_state.add_log(
                f"补充拍卖区 {len(added)} 件文物（当前 {len(gs.auction_pool)}/{effective_target}）"
            )
            game_logger.info(
                "Auction pool refilled: added=%s current=%s target=%s",
                len(added),
                len(gs.auction_pool),
                effective_target,
            )

        return {
            "success": True,
            "target_size": effective_target,
            "added_count": len(added),
            "added_artifacts": [a.model_dump() for a in added],
            "auction_pool_count": len(gs.auction_pool),
            "remaining_artifact_deck_count": len(gs.artifact_deck),
            "deck_exhausted": len(gs.artifact_deck) == 0 and len(gs.auction_pool) < effective_target,
        }

    def draw_event_to_area(self, max_area_size: int = 2) -> dict:
        """翻开一张事件卡到事件区"""
        game_state, gs, error = self._ensure_game()
        if error:
            return error
        assert game_state is not None and gs is not None
        game_logger = bind_context(logger, game_id=gs.game_id)

        if max_area_size <= 0:
            return {"error": "事件区容量必须大于0"}
        if len(gs.event_area) >= max_area_size:
            return {"error": f"事件区已满（{len(gs.event_area)}/{max_area_size}）"}

        self._reshuffle_event_discard_if_needed()
        if not gs.event_deck:
            game_logger.warning("Event draw failed: deck empty")
            return {"error": "事件卡牌库为空，无法补充事件区"}

        event_card = gs.event_deck.pop(0)
        gs.event_area.append(event_card)
        game_state.add_log(f"事件区翻开新事件: {event_card.name}")
        game_logger.info("Event drawn to area: %s", event_card.id)

        return {
            "success": True,
            "event": event_card.model_dump(),
            "event_area_count": len(gs.event_area),
            "remaining_event_deck_count": len(gs.event_deck),
        }

    def _apply_event_effect(self, event_card: EventCard) -> dict:
        """应用事件卡的可自动结算效果"""
        assert self.game_state is not None
        gs = self.game_state.global_state
        changes: list[str] = []
        manual_required = False

        def clamp_multiplier(v: float) -> float:
            return max(0.5, min(2.5, round(v, 1)))

        if event_card.id == "event_10":  # 市场崩盘
            for era_key in list(gs.era_multipliers.keys()):
                gs.era_multipliers[era_key] = clamp_multiplier(gs.era_multipliers[era_key] - 0.5)
            changes.append("所有时代倍率 -0.5（下限×0.5）")
        elif event_card.id == "event_11":  # 市场繁荣
            for era_key in list(gs.era_multipliers.keys()):
                gs.era_multipliers[era_key] = clamp_multiplier(gs.era_multipliers[era_key] + 0.5)
            changes.append("所有时代倍率 +0.5（上限×2.5）")
        elif event_card.id == "event_09":  # 两极反转
            sorted_items = sorted(gs.era_multipliers.items(), key=lambda kv: kv[1])
            low_key, low_val = sorted_items[0]
            high_key, high_val = sorted_items[-1]
            gs.era_multipliers[low_key], gs.era_multipliers[high_key] = high_val, low_val
            changes.append(f"交换倍率：{low_key} <-> {high_key}")
        elif event_card.id in {"event_13", "event_14", "event_15"}:  # 时代热潮
            target = {
                "event_13": "ancient",
                "event_14": "future",
                "event_15": "modern",
            }[event_card.id]
            for era_key in list(gs.era_multipliers.keys()):
                if era_key == target:
                    gs.era_multipliers[era_key] = 2.0
                else:
                    gs.era_multipliers[era_key] = clamp_multiplier(gs.era_multipliers[era_key] - 0.5)
            changes.append(f"{target} 时代倍率设为×2.0，其余时代 -0.5")
        elif event_card.id == "event_01":  # 时空震荡
            candidates = [
                (pid, p, sum(max(0, a.time_cost) for a in p.artifacts))
                for pid, p in self.game_state.players.items()
            ]
            if candidates:
                max_cost = max(x[2] for x in candidates)
                top_players = [x for x in candidates if x[2] == max_cost]
                top_players.sort(key=lambda x: self.game_state.global_state.turn_order.index(x[0]))
                chosen_pid, chosen_player, _ = top_players[0]
                if chosen_player.artifacts:
                    discard_artifact = max(chosen_player.artifacts, key=lambda a: a.time_cost)
                    chosen_player.artifacts.remove(discard_artifact)
                    gs.discard_pile.append(discard_artifact)
                    changes.append(
                        f"{chosen_player.name} 弃置文物 {discard_artifact.name}（时空震荡）"
                    )
                else:
                    changes.append(f"{chosen_player.name} 无文物可弃置（时空震荡）")
            else:
                changes.append("无玩家可执行时空震荡")
        elif event_card.id == "event_03":  # 连锁抛售
            affected = 0
            for player in self.game_state.players.values():
                if len(player.artifacts) >= 3:
                    artifact = max(player.artifacts, key=lambda a: a.base_value)
                    player.artifacts.remove(artifact)
                    sell_price = math.floor(artifact.base_value * gs.era_multipliers[artifact.era.value] * 0.5)
                    player.money += max(0, sell_price)
                    gs.system_warehouse.append(artifact)
                    affected += 1
            changes.append(f"连锁抛售生效，影响玩家 {affected} 名")
        elif event_card.id == "event_06":  # 文物充公
            total_confiscated = 0
            for player in self.game_state.players.values():
                legendary_cards = [a for a in player.artifacts if a.rarity == Rarity.LEGENDARY]
                for artifact in list(legendary_cards):
                    if player.money >= 10:
                        player.money -= 10
                    else:
                        player.artifacts.remove(artifact)
                        gs.discard_pile.append(artifact)
                        total_confiscated += 1
            changes.append(f"文物充公生效，被没收传奇文物 {total_confiscated} 件")
        elif event_card.id == "event_12":
            gs.active_effects.append("ban_vote_adjustment_next_round")
            changes.append("下回合禁止倍率投票调整")
        elif event_card.id == "event_17":
            gs.active_effects.append("auction_price_bonus_5_next_round")
            changes.append("下回合公开拍卖成交价 +5")
        elif event_card.id == "event_18":
            gs.active_effects.append("auction_price_penalty_3_next_round")
            changes.append("下回合拍卖成交价 -3（最低1）")
        elif event_card.id == "event_19":
            gs.active_effects.append("hidden_auction_next_round")
            changes.append("下回合拍卖文物背面进行")
        elif event_card.id == "event_20":
            gs.active_effects.append("force_sealed_next_round")
            changes.append("下回合所有拍卖强制密封竞标")
        elif event_card.id == "event_21":
            gs.active_effects.append("force_open_next_round")
            changes.append("下回合所有拍卖强制公开拍卖")
        elif event_card.id == "event_22":
            gs.active_effects.append("auction_min_raise_3_next_round")
            changes.append("下回合拍卖最低加价为3")
        elif event_card.id == "event_23":
            gs.active_effects.append("ban_function_cards_auction_next_round")
            changes.append("下回合拍卖阶段禁止使用功能卡")
        elif event_card.id == "event_24":
            gs.active_effects.append("auction_bid_cap_8_next_round")
            changes.append("下回合拍卖最高出价上限8")
        else:
            manual_required = True
            changes.append("该事件需 GM 手动结算")

        if changes:
            self.game_state.add_log(f"事件结算 [{event_card.name}]: {'；'.join(changes)}")

        return {
            "success": True,
            "event_id": event_card.id,
            "event_name": event_card.name,
            "changes": changes,
            "manual_resolution_required": manual_required,
        }

    def resolve_event(self, event_id: str, refill_area: bool = True) -> dict:
        """执行事件区中的一张事件卡并按规则补充事件区"""
        game_state, gs, error = self._ensure_game()
        if error:
            return error
        assert game_state is not None and gs is not None
        game_logger = bind_context(logger, game_id=gs.game_id)

        event_index = next((i for i, e in enumerate(gs.event_area) if e.id == event_id), None)
        if event_index is None:
            game_logger.warning("Resolve event failed: missing event %s", event_id)
            return {"error": f"事件区不存在事件 {event_id}"}

        event_card = gs.event_area.pop(event_index)
        effect_result = self._apply_event_effect(event_card)
        gs.event_discard_pile.append(event_card)

        refill_result = None
        if refill_area and len(gs.event_area) < 2:
            refill_result = self.draw_event_to_area()
        game_logger.info("Event resolved: %s", event_id)

        return {
            "success": True,
            "resolved_event": event_card.model_dump(),
            "effect_result": effect_result,
            "refill_result": refill_result,
            "event_area_count": len(gs.event_area),
        }

    def play_function_card(
        self,
        player_id: str,
        card_id: str,
        target_player_id: str | None = None,
        target_era: str | None = None,
        secondary_era: str | None = None,
        multiplier_delta: float = 0.5,
    ) -> dict:
        """打出功能卡并执行可自动结算的效果"""
        game_state, gs, error = self._ensure_game()
        if error:
            return error
        assert game_state is not None and gs is not None
        game_logger = bind_context(logger, game_id=gs.game_id)

        player = game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}

        card = next((c for c in player.function_cards if c.id == card_id), None)
        if card is None:
            return {"error": f"玩家 {player_id} 没有功能卡 {card_id}"}

        def clamp_multiplier(v: float) -> float:
            return max(0.5, min(2.5, round(v, 1)))

        # 先验证参数，避免非法输入时消耗卡牌
        if card.id == "func_11":
            if target_era not in gs.era_multipliers:
                return {"error": "倍率冲击需要 target_era=ancient/modern/future"}
            if multiplier_delta == 0:
                return {"error": "multiplier_delta 不能为0"}
        elif card.id == "func_14":
            if target_era not in gs.era_multipliers or secondary_era not in gs.era_multipliers:
                return {"error": "倍率互换需要 target_era 和 secondary_era"}
        elif card.id == "func_12":
            if target_era not in gs.era_multipliers:
                return {"error": "倍率固锁需要 target_era=ancient/modern/future"}
        elif card.id == "func_07":
            if not target_player_id:
                return {"error": "收藏劫掠需要 target_player_id"}
            target_player = game_state.get_player(target_player_id)
            if target_player is None:
                return {"error": f"目标玩家 {target_player_id} 不存在"}
            if not target_player.artifacts:
                return {"error": f"目标玩家 {target_player.name} 没有文物可抽取"}
            if player.money < 5:
                return {"error": f"{player.name} 资金不足，收藏劫掠需要支付5资金"}

        player.function_cards.remove(card)
        gs.card_discard_pile.append(card)

        changes: list[str] = []
        manual_required = False

        if card.id == "func_11":
            gs.era_multipliers[target_era] = clamp_multiplier(gs.era_multipliers[target_era] + multiplier_delta)
            changes.append(f"{target_era} 倍率调整为 {gs.era_multipliers[target_era]:.1f}")
        elif card.id == "func_14":
            gs.era_multipliers[target_era], gs.era_multipliers[secondary_era] = (
                gs.era_multipliers[secondary_era],
                gs.era_multipliers[target_era],
            )
            changes.append(f"交换倍率：{target_era} <-> {secondary_era}")
        elif card.id == "func_16":
            for era_key in list(gs.era_multipliers.keys()):
                gs.era_multipliers[era_key] = 1.0
            changes.append("所有时代倍率重置为×1.0")
        elif card.id == "func_12":
            gs.active_effects.append(f"lock_multiplier_{target_era}_this_round")
            changes.append(f"本回合锁定 {target_era} 倍率不可投票调整")
        elif card.id == "func_17":
            gs.active_effects.append(f"double_vote_{player_id}_this_round")
            changes.append(f"{player.name} 本回合投票权翻倍")
        elif card.id == "func_15":
            preview = [e.model_dump() for e in gs.event_deck[:3]]
            changes.append("已查看事件牌堆顶3张")
            game_state.add_log(f"{player.name} 使用事件预测，查看事件牌堆顶3张")
            return {
                "success": True,
                "player_id": player_id,
                "card": card.model_dump(),
                "changes": changes,
                "preview_events": preview,
                "manual_resolution_required": False,
            }
        elif card.id == "func_07":
            target_player = game_state.get_player(target_player_id)
            assert target_player is not None
            artifact = random.choice(target_player.artifacts)
            target_player.artifacts.remove(artifact)
            player.artifacts.append(artifact)
            player.money -= 5
            target_player.money += 5
            changes.append(f"{player.name} 从 {target_player.name} 夺取文物 {artifact.name} 并支付5资金")
        else:
            manual_required = True
            changes.append("该功能卡效果需 GM 手动结算")

        game_state.add_log(f"{player.name} 使用功能卡 [{card.name}]：{'；'.join(changes)}")
        game_logger.info("Function card played: %s by %s", card_id, player_id)

        return {
            "success": True,
            "player_id": player_id,
            "card": card.model_dump(),
            "changes": changes,
            "manual_resolution_required": manual_required,
        }
    
    def update_player_asset(
        self, 
        player_id: str, 
        money_delta: int = 0,
        vp_delta: int = 0,
    ) -> dict:
        """
        修改玩家资产
        
        Args:
            player_id: 玩家ID
            money_delta: 资金变化量（可为负）
            vp_delta: VP变化量
            
        Returns:
            操作结果
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        player = self.game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}
        
        new_money = player.money + money_delta
        if new_money < 0:
            return {"error": f"资金不足，当前 {player.money}，需要 {-money_delta}"}
        
        player.money = new_money
        player.victory_points += vp_delta
        
        changes = []
        if money_delta != 0:
            changes.append(f"资金 {'+' if money_delta > 0 else ''}{money_delta}")
        if vp_delta != 0:
            changes.append(f"VP {'+' if vp_delta > 0 else ''}{vp_delta}")
        
        self.game_state.add_log(f"{player.name}: {', '.join(changes)}")
        
        return {
            "success": True,
            "player_id": player_id,
            "new_money": player.money,
            "new_vp": player.victory_points,
        }
    
    def transfer_item(
        self,
        item_type: str,  # "artifact" 或 "card"
        item_id: str,
        from_location: str,  # player_id, "auction_pool", "deck"
        to_location: str,
    ) -> dict:
        """
        转移物品
        
        Args:
            item_type: 物品类型 ("artifact" 或 "card")
            item_id: 物品ID
            from_location: 来源位置
            to_location: 目标位置
            
        Returns:
            操作结果
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        # 查找物品
        item = None
        requested_item_id = item_id
        resolved_item_id = item_id
        
        if item_type == "artifact":
            # 从来源获取文物
            if from_location == "deck":
                for i, a in enumerate(self.game_state.global_state.artifact_deck):
                    if a.id == item_id:
                        item = self.game_state.global_state.artifact_deck.pop(i)
                        break
            elif from_location == "discard":
                for i, a in enumerate(self.game_state.global_state.discard_pile):
                    if a.id == item_id:
                        item = self.game_state.global_state.discard_pile.pop(i)
                        break
            elif from_location == "warehouse":
                for i, a in enumerate(self.game_state.global_state.system_warehouse):
                    if a.id == item_id:
                        item = self.game_state.global_state.system_warehouse.pop(i)
                        break
            elif from_location == "auction_pool":
                index, auction_item = self._resolve_auction_item_reference(item_id)
                if index is not None and auction_item is not None:
                    item = self.game_state.global_state.auction_pool.pop(index).artifact
                    resolved_item_id = item.id
            elif from_location in self.game_state.players:
                player = self.game_state.players[from_location]
                for i, a in enumerate(player.artifacts):
                    if a.id == item_id:
                        item = player.artifacts.pop(i)
                        break
            
            if item is None:
                if from_location == "auction_pool":
                    return {
                        "error": f"未找到文物 {item_id} 在 {from_location}",
                        "available_auction_items": self._list_auction_pool_brief(),
                    }
                return {"error": f"未找到文物 {item_id} 在 {from_location}"}
            
            # 放入目标位置
            if to_location == "deck":
                self.game_state.global_state.artifact_deck.append(item)
            elif to_location == "discard":
                self.game_state.global_state.discard_pile.append(item)
            elif to_location == "warehouse":
                self.game_state.global_state.system_warehouse.append(item)
            elif to_location == "auction_pool":
                self.game_state.global_state.auction_pool.append(
                    AuctionItem(artifact=item, auction_type=item.auction_type)
                )
            elif to_location in self.game_state.players:
                self.game_state.players[to_location].artifacts.append(item)
            else:
                return {"error": f"无效的目标位置 {to_location}"}
        
        elif item_type == "card":
            # 功能卡转移逻辑类似
            if from_location == "deck":
                for i, c in enumerate(self.game_state.global_state.card_deck):
                    if c.id == item_id:
                        item = self.game_state.global_state.card_deck.pop(i)
                        break
            elif from_location == "card_discard":
                for i, c in enumerate(self.game_state.global_state.card_discard_pile):
                    if c.id == item_id:
                        item = self.game_state.global_state.card_discard_pile.pop(i)
                        break
            elif from_location in self.game_state.players:
                player = self.game_state.players[from_location]
                for i, c in enumerate(player.function_cards):
                    if c.id == item_id:
                        item = player.function_cards.pop(i)
                        break
            
            if item is None:
                return {"error": f"未找到功能卡 {item_id} 在 {from_location}"}
            
            if to_location == "deck":
                self.game_state.global_state.card_deck.append(item)
            elif to_location == "card_discard":
                self.game_state.global_state.card_discard_pile.append(item)
            elif to_location in self.game_state.players:
                self.game_state.players[to_location].function_cards.append(item)
            else:
                return {"error": f"无效的目标位置 {to_location}"}
        else:
            return {"error": f"无效的物品类型 {item_type}"}

        resolved_item_id = item.id
        
        self.game_state.add_log(f"物品转移: {item.name} 从 {from_location} 到 {to_location}")
        
        return {
            "success": True,
            "item_type": item_type,
            "item_id": resolved_item_id,
            "requested_item_id": requested_item_id,
            "item_name": item.name,
            "from": from_location,
            "to": to_location,
        }
    
    def update_global_status(
        self,
        stability_delta: int = 0,
        era_multiplier_changes: dict[str, float] | None = None,
        new_phase: str | None = None,
        next_round: bool = False,
    ) -> dict:
        """
        更新全局状态
        
        Args:
            stability_delta: 稳定性变化
            era_multiplier_changes: 时代倍率变化 {"ancient": 0.1, ...}
            new_phase: 新阶段
            next_round: 是否进入下一回合
            
        Returns:
            操作结果
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        gs = self.game_state.global_state
        changes = []
        
        if stability_delta != 0:
            gs.stability = max(0, min(100, gs.stability + stability_delta))
            changes.append(f"稳定性 {'+' if stability_delta > 0 else ''}{stability_delta} -> {gs.stability}")
        
        if era_multiplier_changes:
            for era_str, delta in era_multiplier_changes.items():
                try:
                    era = Era(era_str)
                    era_key = era.value
                    gs.era_multipliers[era_key] = max(0.5, min(2.5, gs.era_multipliers[era_key] + delta))
                    changes.append(f"{era.value}倍率 -> {gs.era_multipliers[era_key]:.1f}")
                except ValueError:
                    return {"error": f"无效的时代 {era_str}"}
        
        if new_phase:
            try:
                gs.current_phase = GamePhase(new_phase)
                changes.append(f"阶段 -> {new_phase}")
            except ValueError:
                return {"error": f"无效的阶段 {new_phase}"}
        
        if next_round:
            gs.current_round += 1
            changes.append(f"回合 -> {gs.current_round}")
            # 重置玩家行动状态
            for player in self.game_state.players.values():
                player.has_acted = False
            # 每3回合全员抽1张功能卡
            if gs.current_round % 3 == 0:
                for player_id in self.game_state.players:
                    draw_result = self.draw_function_cards(player_id=player_id, count=1)
                    if "error" in draw_result:
                        return draw_result
                changes.append("每3回合功能卡补充：全员抽1张")
        
        if changes:
            self.game_state.add_log(f"全局状态更新: {', '.join(changes)}")
        
        return {
            "success": True,
            "changes": changes,
            "current_round": gs.current_round,
            "current_phase": gs.current_phase.value,
            "stability": gs.stability,
        }
    
    def record_sealed_bid(
        self,
        player_id: str,
        auction_item_id: str,
        bid_amount: int,
    ) -> dict:
        """
        记录密封竞标出价
        
        Args:
            player_id: 玩家ID
            auction_item_id: 拍卖物品ID
            bid_amount: 出价金额
            
        Returns:
            操作结果（不泄露其他人的出价）
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        player = self.game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}
        
        if bid_amount > player.money:
            return {"error": f"出价 {bid_amount} 超过持有资金 {player.money}"}
        
        if bid_amount < 0:
            return {"error": "出价不能为负数"}
        
        # 找到拍卖物品
        _index, auction_item = self._resolve_auction_item_reference(auction_item_id)
        
        if auction_item is None:
            return {
                "error": f"未找到拍卖物品 {auction_item_id}",
                "available_auction_items": self._list_auction_pool_brief(),
            }
        
        # 记录出价（不公开）
        auction_item.sealed_bids[player_id] = bid_amount
        player.current_bid = bid_amount
        
        return {
            "success": True,
            "player_id": player_id,
            "item_id": auction_item.artifact.id,
            "requested_item_id": auction_item_id,
            "message": "出价已记录",
        }
    
    def reveal_sealed_bids(self, auction_item_id: str) -> dict:
        """
        揭示密封竞标结果（仅 GM 可调用）
        
        Args:
            auction_item_id: 拍卖物品ID
            
        Returns:
            竞标结果，包含所有出价和赢家
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        _index, auction_item = self._resolve_auction_item_reference(auction_item_id)
        
        if auction_item is None:
            return {
                "error": f"未找到拍卖物品 {auction_item_id}",
                "available_auction_items": self._list_auction_pool_brief(),
            }
        
        if not auction_item.sealed_bids:
            return {"error": "没有出价记录"}
        
        # 找出最高出价
        bids = auction_item.sealed_bids
        winner_id = max(bids.keys(), key=lambda k: bids[k])
        winning_bid = bids[winner_id]
        
        # 处理平局（出价相同时，按行动顺序先出价者获胜）
        max_bid = winning_bid
        candidates = [pid for pid, bid in bids.items() if bid == max_bid]
        if len(candidates) > 1:
            # 按 turn_order 选择最先的
            for pid in self.game_state.global_state.turn_order:
                if pid in candidates:
                    winner_id = pid
                    break
        
        winner = self.game_state.players.get(winner_id)
        
        self.game_state.add_log(
            f"密封竞标揭晓 [{auction_item.artifact.name}]: "
            f"赢家 {winner.name if winner else winner_id}，出价 {winning_bid}"
        )
        
        return {
            "success": True,
            "item_id": auction_item.artifact.id,
            "requested_item_id": auction_item_id,
            "item_name": auction_item.artifact.name,
            "all_bids": {
                self.game_state.players[pid].name: bid 
                for pid, bid in bids.items()
            },
            "winner_id": winner_id,
            "winner_name": winner.name if winner else winner_id,
            "winning_bid": winning_bid,
        }
    
    def set_current_player(self, player_id: str) -> dict:
        """设置当前行动玩家"""
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        if player_id not in self.game_state.players:
            return {"error": f"玩家 {player_id} 不存在"}
        
        self.game_state.global_state.current_player_id = player_id
        player = self.game_state.players[player_id]
        
        return {
            "success": True,
            "current_player_id": player_id,
            "current_player_name": player.name,
            "is_human": player.is_human,
        }
    
    def mark_player_acted(self, player_id: str) -> dict:
        """标记玩家已行动"""
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        player = self.game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}
        
        player.has_acted = True
        player.current_bid = None
        
        return {"success": True, "player_id": player_id}
    
    def add_artifact_to_pool(
        self,
        artifact_id: str,
        name: str,
        era: str,
        base_value: int,
        auction_type: str = "open",
        description: str = "",
    ) -> dict:
        """向拍卖池添加文物"""
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        try:
            era_enum = Era(era)
            auction_enum = AuctionType(auction_type)
        except ValueError as e:
            return {"error": str(e)}
        
        artifact = Artifact(
            id=artifact_id,
            name=name,
            era=era_enum,
            base_value=base_value,
            description=description,
        )
        
        auction_item = AuctionItem(
            artifact=artifact,
            auction_type=auction_enum,
        )
        
        self.game_state.global_state.auction_pool.append(auction_item)
        self.game_state.add_log(f"文物入场: {name} ({era})")
        
        return {
            "success": True,
            "artifact_id": artifact_id,
            "name": name,
            "auction_type": auction_type,
        }
    
    def get_action_log(self, limit: int = 20) -> list[str]:
        """获取最近的行动日志"""
        if self.game_state is None:
            return []
        return self.game_state.action_log[-limit:]

    def get_auction_state(self, auction_item_id: str) -> dict:
        """
        获取拍卖物品的当前状态，包括活跃竞价者列表
        
        Args:
            auction_item_id: 拍卖物品ID
            
        Returns:
            拍卖状态信息
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        _index, auction_item = self._resolve_auction_item_reference(auction_item_id)
        if auction_item is None:
            return {
                "error": f"未找到拍卖物品 {auction_item_id}",
                "available_auction_items": self._list_auction_pool_brief(),
            }
        
        return {
            "success": True,
            "item_id": auction_item.artifact.id,
            "item_name": auction_item.artifact.name,
            "auction_type": auction_item.auction_type.value,
            "current_highest_bid": auction_item.current_highest_bid,
            "current_highest_bidder": auction_item.current_highest_bidder,
            "all_players": list(self.game_state.players.keys()),
            "turn_order": self.game_state.global_state.turn_order,
        }

    def update_open_auction_bid(
        self,
        auction_item_id: str,
        player_id: str,
        bid_amount: int,
    ) -> dict:
        """
        更新公开拍卖的出价
        
        Args:
            auction_item_id: 拍卖物品ID
            player_id: 出价玩家ID
            bid_amount: 出价金额
            
        Returns:
            操作结果
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        player = self.game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}
        
        if bid_amount > player.money:
            return {"error": f"出价 {bid_amount} 超过持有资金 {player.money}"}
        
        _index, auction_item = self._resolve_auction_item_reference(auction_item_id)
        if auction_item is None:
            return {
                "error": f"未找到拍卖物品 {auction_item_id}",
                "available_auction_items": self._list_auction_pool_brief(),
            }
        
        if auction_item.auction_type != AuctionType.OPEN:
            return {"error": "该物品不是公开拍卖类型"}
        
        if bid_amount <= auction_item.current_highest_bid:
            return {
                "error": f"出价必须高于当前最高价 {auction_item.current_highest_bid}",
                "current_highest_bid": auction_item.current_highest_bid,
            }
        
        auction_item.current_highest_bid = bid_amount
        auction_item.current_highest_bidder = player_id
        
        self.game_state.add_log(
            f"公开拍卖 [{auction_item.artifact.name}]: {player.name} 出价 {bid_amount}"
        )
        
        return {
            "success": True,
            "item_id": auction_item.artifact.id,
            "item_name": auction_item.artifact.name,
            "player_id": player_id,
            "player_name": player.name,
            "bid_amount": bid_amount,
        }

    def finalize_open_auction(
        self,
        auction_item_id: str,
    ) -> dict:
        """
        结算公开拍卖：将文物转移给最高出价者，扣除资金，扣减稳定性
        
        Args:
            auction_item_id: 拍卖物品ID
            
        Returns:
            结算结果
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        index, auction_item = self._resolve_auction_item_reference(auction_item_id)
        if auction_item is None:
            return {
                "error": f"未找到拍卖物品 {auction_item_id}",
                "available_auction_items": self._list_auction_pool_brief(),
            }
        
        winner_id = auction_item.current_highest_bidder
        winning_bid = auction_item.current_highest_bid
        
        if winner_id is None or winning_bid <= 0:
            # 流拍：无人出价
            self.game_state.global_state.auction_pool.pop(index)
            self.game_state.global_state.discard_pile.append(auction_item.artifact)
            self.game_state.add_log(
                f"拍卖流拍 [{auction_item.artifact.name}]: 无人出价，文物进入弃牌堆"
            )
            return {
                "success": True,
                "result": "no_sale",
                "item_id": auction_item.artifact.id,
                "item_name": auction_item.artifact.name,
                "message": "无人出价，拍卖流拍",
            }
        
        winner = self.game_state.get_player(winner_id)
        if winner is None:
            return {"error": f"赢家 {winner_id} 不存在"}
        
        if winner.money < winning_bid:
            return {"error": f"赢家资金不足: 需要 {winning_bid}，实际 {winner.money}"}
        
        # 扣除资金
        winner.money -= winning_bid
        
        # 转移文物
        artifact = self.game_state.global_state.auction_pool.pop(index).artifact
        winner.artifacts.append(artifact)
        
        # 扣减稳定性
        stability_cost = artifact.time_cost
        gs = self.game_state.global_state
        gs.stability = max(0, gs.stability - stability_cost)
        
        self.game_state.add_log(
            f"拍卖成交 [{artifact.name}]: {winner.name} 以 {winning_bid} 金币获得，"
            f"稳定性 -{stability_cost} (当前 {gs.stability}%)"
        )
        
        return {
            "success": True,
            "result": "sold",
            "item_id": artifact.id,
            "item_name": artifact.name,
            "winner_id": winner_id,
            "winner_name": winner.name,
            "winning_bid": winning_bid,
            "stability_cost": stability_cost,
            "current_stability": gs.stability,
        }

    def get_players_for_action(self, action_type: str = "general") -> dict:
        """
        获取需要进行某类行动的玩家列表
        
        Args:
            action_type: 行动类型 ("auction", "trade", "vote", "stabilize", "general")
            
        Returns:
            玩家列表和相关状态
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        turn_order = self.game_state.global_state.turn_order
        players_info = []
        
        for player_id in turn_order:
            player = self.game_state.players.get(player_id)
            if player is None:
                continue
            players_info.append({
                "player_id": player_id,
                "name": player.name,
                "is_human": player.is_human,
                "money": player.money,
                "victory_points": player.victory_points,
                "artifact_count": len(player.artifacts),
                "card_count": len(player.function_cards),
                "has_acted": player.has_acted,
            })
        
        return {
            "success": True,
            "action_type": action_type,
            "turn_order": turn_order,
            "players": players_info,
            "current_player_id": self.game_state.global_state.current_player_id,
        }

    def execute_trade(
        self,
        from_player_id: str,
        to_player_id: str,
        from_offers: dict,
        to_offers: dict,
    ) -> dict:
        """
        执行玩家间交易
        
        Args:
            from_player_id: 发起方玩家ID
            to_player_id: 接收方玩家ID
            from_offers: 发起方提供的物品 {"money": int, "artifact_ids": list, "card_ids": list}
            to_offers: 接收方提供的物品 {"money": int, "artifact_ids": list, "card_ids": list}
            
        Returns:
            交易结果
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        from_player = self.game_state.get_player(from_player_id)
        to_player = self.game_state.get_player(to_player_id)
        
        if from_player is None:
            return {"error": f"玩家 {from_player_id} 不存在"}
        if to_player is None:
            return {"error": f"玩家 {to_player_id} 不存在"}
        
        # 验证资金
        from_money = from_offers.get("money", 0)
        to_money = to_offers.get("money", 0)
        
        if from_money > from_player.money:
            return {"error": f"{from_player.name} 资金不足: 需要 {from_money}，实际 {from_player.money}"}
        if to_money > to_player.money:
            return {"error": f"{to_player.name} 资金不足: 需要 {to_money}，实际 {to_player.money}"}
        
        # 验证并收集文物
        from_artifacts = []
        for artifact_id in from_offers.get("artifact_ids", []):
            artifact = next((a for a in from_player.artifacts if a.id == artifact_id), None)
            if artifact is None:
                return {"error": f"{from_player.name} 没有文物 {artifact_id}"}
            from_artifacts.append(artifact)
        
        to_artifacts = []
        for artifact_id in to_offers.get("artifact_ids", []):
            artifact = next((a for a in to_player.artifacts if a.id == artifact_id), None)
            if artifact is None:
                return {"error": f"{to_player.name} 没有文物 {artifact_id}"}
            to_artifacts.append(artifact)
        
        # 验证并收集功能卡
        from_cards = []
        for card_id in from_offers.get("card_ids", []):
            card = next((c for c in from_player.function_cards if c.id == card_id), None)
            if card is None:
                return {"error": f"{from_player.name} 没有功能卡 {card_id}"}
            from_cards.append(card)
        
        to_cards = []
        for card_id in to_offers.get("card_ids", []):
            card = next((c for c in to_player.function_cards if c.id == card_id), None)
            if card is None:
                return {"error": f"{to_player.name} 没有功能卡 {card_id}"}
            to_cards.append(card)
        
        # 执行交易
        # 资金转移
        from_player.money -= from_money
        to_player.money += from_money
        to_player.money -= to_money
        from_player.money += to_money
        
        # 文物转移
        for artifact in from_artifacts:
            from_player.artifacts.remove(artifact)
            to_player.artifacts.append(artifact)
        for artifact in to_artifacts:
            to_player.artifacts.remove(artifact)
            from_player.artifacts.append(artifact)
        
        # 功能卡转移
        for card in from_cards:
            from_player.function_cards.remove(card)
            to_player.function_cards.append(card)
        for card in to_cards:
            to_player.function_cards.remove(card)
            from_player.function_cards.append(card)
        
        # 计算 VP 奖励 (交易额/2)
        total_money_traded = from_money + to_money
        vp_reward = total_money_traded // 2
        if vp_reward > 0:
            from_player.victory_points += vp_reward
            to_player.victory_points += vp_reward
        
        # 记录日志
        trade_details = []
        if from_money > 0:
            trade_details.append(f"{from_player.name} 支付 {from_money} 金币")
        if to_money > 0:
            trade_details.append(f"{to_player.name} 支付 {to_money} 金币")
        if from_artifacts:
            trade_details.append(f"{from_player.name} 给出文物: {', '.join(a.name for a in from_artifacts)}")
        if to_artifacts:
            trade_details.append(f"{to_player.name} 给出文物: {', '.join(a.name for a in to_artifacts)}")
        if from_cards:
            trade_details.append(f"{from_player.name} 给出功能卡: {', '.join(c.name for c in from_cards)}")
        if to_cards:
            trade_details.append(f"{to_player.name} 给出功能卡: {', '.join(c.name for c in to_cards)}")
        
        self.game_state.add_log(f"交易完成: {'; '.join(trade_details)}" + (f" (双方各获得 {vp_reward} VP)" if vp_reward > 0 else ""))
        
        return {
            "success": True,
            "from_player": from_player.name,
            "to_player": to_player.name,
            "from_offers": {
                "money": from_money,
                "artifacts": [a.name for a in from_artifacts],
                "cards": [c.name for c in from_cards],
            },
            "to_offers": {
                "money": to_money,
                "artifacts": [a.name for a in to_artifacts],
                "cards": [c.name for c in to_cards],
            },
            "vp_reward": vp_reward,
        }

    def sell_artifact_to_system(
        self,
        player_id: str,
        artifact_id: str,
    ) -> dict:
        """
        玩家出售文物给系统
        
        Args:
            player_id: 玩家ID
            artifact_id: 文物ID
            
        Returns:
            出售结果
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        player = self.game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}
        
        artifact = next((a for a in player.artifacts if a.id == artifact_id), None)
        if artifact is None:
            return {"error": f"玩家没有文物 {artifact_id}"}
        
        # 计算出售价格
        era_key = artifact.era.value
        multiplier = self.game_state.global_state.era_multipliers.get(era_key, 1.0)
        base_price = int(artifact.base_value * multiplier)
        
        # 危机区惩罚
        if self.game_state.global_state.stability < 15:
            base_price = max(0, base_price - 5)
        
        # 执行出售
        player.artifacts.remove(artifact)
        player.money += base_price
        self.game_state.global_state.system_warehouse.append(artifact)
        
        self.game_state.add_log(
            f"系统回购: {player.name} 出售 [{artifact.name}] 获得 {base_price} 金币"
        )
        
        return {
            "success": True,
            "player_id": player_id,
            "player_name": player.name,
            "artifact_id": artifact_id,
            "artifact_name": artifact.name,
            "sell_price": base_price,
            "era": era_key,
            "multiplier": multiplier,
        }

    def get_tradeable_assets(self, player_id: str) -> dict:
        """
        获取玩家可交易的资产列表
        
        Args:
            player_id: 玩家ID
            
        Returns:
            可交易资产信息
        """
        if self.game_state is None:
            return {"error": "游戏未初始化"}
        
        player = self.game_state.get_player(player_id)
        if player is None:
            return {"error": f"玩家 {player_id} 不存在"}
        
        era_multipliers = self.game_state.global_state.era_multipliers
        stability = self.game_state.global_state.stability
        
        artifacts_info = []
        for artifact in player.artifacts:
            era_key = artifact.era.value
            multiplier = era_multipliers.get(era_key, 1.0)
            sell_price = int(artifact.base_value * multiplier)
            if stability < 15:
                sell_price = max(0, sell_price - 5)
            artifacts_info.append({
                "id": artifact.id,
                "name": artifact.name,
                "era": era_key,
                "base_value": artifact.base_value,
                "current_sell_price": sell_price,
            })
        
        cards_info = []
        for card in player.function_cards:
            cards_info.append({
                "id": card.id,
                "name": card.name,
                "effect": card.effect,
            })
        
        return {
            "success": True,
            "player_id": player_id,
            "player_name": player.name,
            "money": player.money,
            "artifacts": artifacts_info,
            "function_cards": cards_info,
        }


# 全局游戏管理器实例
game_manager = GameManager()
