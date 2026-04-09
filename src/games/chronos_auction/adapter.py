"""
时空拍卖行 (Chronos Auction House) 适配器

包含从通用操作中提取的游戏特定逻辑：
- 事件卡自动结算效果
- 功能卡特殊效果
- 拍卖（密封竞标 + 公开拍卖）结算
- 时代倍率刷新

GM Agent 可以直接通过适配器方法触发这些逻辑。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..core.universal_manager import UniversalGameManager

logger = logging.getLogger(__name__)


class ChronosAuctionAdapter:
    """时空拍卖行游戏特定逻辑适配器"""

    def __init__(self, manager: UniversalGameManager):
        self.manager = manager

    # ========== 事件卡效果 ==========

    def apply_event_effect(
        self, event_name: str
    ) -> dict[str, Any]:
        """解析并应用事件卡的自动效果。
        
        这里只演示可自动化的效果模式。
        复杂的条件效果由 GM Agent 通过工具调用组合实现。
        """
        gs = self.manager.game_state
        if gs is None:
            return {"error": "游戏未初始化"}

        global_state = gs.global_state
        event_area = getattr(global_state, "event_card_area", [])

        # 在事件区找到该事件
        event = None
        for e in event_area:
            name = e.get("name", "") if isinstance(e, dict) else getattr(e, "name", "")
            if name == event_name:
                event = e
                break

        if event is None:
            return {"error": f"事件区中未找到事件: {event_name}"}

        effect = event.get("effect", "") if isinstance(event, dict) else ""
        results = {"event": event_name, "effect": effect, "actions": []}

        # 倍率调整类效果（通过关键词匹配）
        era_keywords = {
            "古代": "ancient", "中世纪": "medieval",
            "近代": "modern", "未来": "future",
        }
        for era_cn, era_id in era_keywords.items():
            if "倍率" in effect and era_cn in effect:
                if "提升" in effect or "增加" in effect or "+1" in effect:
                    r = self.manager.update_multiplier("era", era_id, 1.0)
                    results["actions"].append(r)
                elif "降低" in effect or "减少" in effect or "-1" in effect:
                    r = self.manager.update_multiplier("era", era_id, -1.0)
                    results["actions"].append(r)

        return results

    # ========== 拍卖结算 ==========

    def settle_sealed_auction(
        self,
        item_name: str,
        bids: dict[str, int],
    ) -> dict[str, Any]:
        """密封竞标结算 — 最高出价者获得物品"""
        if not bids:
            return {"error": "没有出价"}

        winner_id = max(bids, key=lambda k: bids[k])
        winning_bid = bids[winner_id]

        results: dict[str, Any] = {
            "type": "sealed_auction",
            "item": item_name,
            "winner": winner_id,
            "winning_bid": winning_bid,
            "all_bids": bids,
            "actions": [],
        }

        # 所有出价者扣钱
        for pid, bid in bids.items():
            r = self.manager.update_resource("coins", -bid, pid)
            results["actions"].append(r)

        # 转移物品给赢家
        r = self.manager.transfer_object(
            "artifact", item_name, "auction_display", winner_id
        )
        results["actions"].append(r)

        return results

    def settle_open_auction(
        self,
        item_name: str,
        winner_id: str,
        winning_bid: int,
    ) -> dict[str, Any]:
        """公开拍卖结算 — 指定赢家和出价"""
        results: dict[str, Any] = {
            "type": "open_auction",
            "item": item_name,
            "winner": winner_id,
            "winning_bid": winning_bid,
            "actions": [],
        }

        # 扣钱
        r = self.manager.update_resource("coins", -winning_bid, winner_id)
        results["actions"].append(r)

        # 转移物品
        r = self.manager.transfer_object(
            "artifact", item_name, "auction_display", winner_id
        )
        results["actions"].append(r)

        return results

    # ========== 回合间自动处理 ==========

    def auto_refill_zones(self) -> dict[str, Any]:
        """自动补充公共区域"""
        results = {"refilled": []}
        for zone in self.manager.game_def.zones:
            if zone.auto_refill:
                gs = self.manager.game_state.global_state
                zone_items = getattr(gs, zone.id, [])
                current_count = len(zone_items)
                # 解析 target_size 表达式
                target_size = self._parse_target_size(zone.auto_refill.target_size)
                to_draw = target_size - current_count
                if to_draw > 0:
                    r = self.manager.draw_from_deck(
                        zone.object_type, to_draw, target_zone_id=zone.id
                    )
                    results["refilled"].append({
                        "zone": zone.id,
                        "drawn": to_draw,
                        "result": r,
                    })
        return results

    def _parse_target_size(self, expr: str) -> int:
        """简单解析 target_size 表达式"""
        try:
            return int(expr)
        except ValueError:
            pass
        # "player_count + 1" 类型表达式
        if "player_count" in expr:
            player_count = len(self.manager.game_state.players)
            expr_eval = expr.replace("player_count", str(player_count))
            try:
                return int(eval(expr_eval))
            except Exception:
                return player_count
        return 3  # 默认值

    # ========== 分数计算 ==========

    def calculate_scores(self) -> dict[str, Any]:
        """根据时空拍卖行规则计算最终得分"""
        gs = self.manager.game_state
        if gs is None:
            return {"error": "游戏未初始化"}

        scores = {}
        global_state = gs.global_state

        # 获取倍率
        multipliers = getattr(global_state, "era_multipliers", {})

        for pid, player in gs.players.items():
            artifacts = getattr(player, "artifacts", [])
            total = 0
            details = []

            for art in artifacts:
                if isinstance(art, dict):
                    name = art.get("name", "")
                    base = art.get("base_value", 0)
                    era = art.get("era", "")
                else:
                    name = getattr(art, "name", "")
                    base = getattr(art, "base_value", 0)
                    era = getattr(art, "era", "")

                mult = multipliers.get(era, 1.0)
                score = int(base * mult)
                total += score
                details.append({
                    "name": name,
                    "base_value": base,
                    "era": era,
                    "multiplier": mult,
                    "score": score,
                })

            scores[pid] = {
                "name": player.name,
                "artifact_score": total,
                "coins": getattr(player, "coins", 0),
                "total": total + getattr(player, "coins", 0),
                "details": details,
            }

        return {"scores": scores}
