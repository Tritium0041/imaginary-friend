"""
游戏状态数据模型 - 《时空拍卖行》桌游 Agent 系统
定义玩家实体、全局状态、物品等核心数据结构
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class Era(str, Enum):
    """时代枚举（3个时代）"""
    ANCIENT = "ancient"      # 古代
    MODERN = "modern"        # 近代
    FUTURE = "future"        # 未来


class GamePhase(str, Enum):
    """游戏阶段"""
    SETUP = "setup"              # 初始化
    EXCAVATION = "excavation"    # 挖掘阶段
    AUCTION = "auction"          # 拍卖阶段
    TRADING = "trading"          # 交易阶段
    BUYBACK = "buyback"          # 回购拍卖阶段
    EVENT = "event"              # 事件阶段
    VOTE = "vote"                # 投票阶段
    STABILIZE = "stabilize"      # 稳定阶段
    GAME_OVER = "game_over"      # 游戏结束


class AuctionType(str, Enum):
    """拍卖类型"""
    OPEN = "open"        # 公开拍卖
    SEALED = "sealed"    # 密封竞标


class Rarity(str, Enum):
    """稀有度"""
    LEGENDARY = "legendary"  # ★ 传奇
    RARE = "rare"            # ● 稀有
    COMMON = "common"        # ○ 常见


class Artifact(BaseModel):
    """文物/藏品"""
    id: str
    name: str
    era: Era
    rarity: Rarity = Rarity.COMMON
    base_value: int = Field(ge=0, description="基础价值 💎")
    time_cost: int = Field(default=0, description="时空消耗 ⏳")
    auction_type: AuctionType = AuctionType.OPEN
    keywords: List[str] = Field(default_factory=list, description="套装关键字")
    description: str = ""
    
    
class FunctionCard(BaseModel):
    """功能卡"""
    id: str
    name: str
    effect: str
    description: str = ""


class EventCard(BaseModel):
    """事件卡"""
    id: str
    name: str
    effect: str
    description: str = ""
    category: str = ""


class PlayerState(BaseModel):
    """玩家状态"""
    id: str
    name: str
    is_human: bool = False
    
    # 资产（初始资金20，不是100）
    money: int = Field(default=20, ge=0, description="当前资金")
    victory_points: int = Field(default=0, ge=0, description="投票点数 VP")
    
    # 持有物品
    artifacts: List[Artifact] = Field(default_factory=list, description="持有的文物")
    function_cards: List[FunctionCard] = Field(default_factory=list, description="持有的功能卡")
    
    # 投票标记
    vote_yes: bool = True   # ✅ 标记可用
    vote_no: bool = True    # ❌ 标记可用
    
    # 本轮状态
    has_acted: bool = False
    current_bid: Optional[int] = None  # 当前出价（密封竞标时使用）


class AuctionItem(BaseModel):
    """拍卖中的物品"""
    artifact: Artifact
    auction_type: AuctionType
    current_highest_bid: int = 0
    current_highest_bidder: Optional[str] = None
    sealed_bids: Dict[str, int] = Field(default_factory=dict, description="密封竞标的出价记录")


class GlobalState(BaseModel):
    """全局游戏状态"""
    # 基础信息
    game_id: str
    current_round: int = Field(default=1, ge=1, description="当前回合")
    max_rounds: int = Field(default=10, ge=1, description="最大回合数")
    current_phase: GamePhase = GamePhase.SETUP
    
    # 时空稳定性 (0-100%)
    stability: int = Field(default=100, ge=0, le=100, description="时空稳定性")
    
    # 时代倍率（范围 0.5~2.5，初始1.0）
    era_multipliers: Dict[str, float] = Field(
        default_factory=lambda: {
            "ancient": 1.0,
            "modern": 1.0,
            "future": 1.0
        },
        description="各时代的价值倍率 (0.5~2.5)"
    )
    
    # 公共区域
    auction_pool: List[AuctionItem] = Field(default_factory=list, description="拍卖区")
    artifact_deck: List[Artifact] = Field(default_factory=list, description="文物牌库")
    card_deck: List[FunctionCard] = Field(default_factory=list, description="功能卡牌库")
    card_discard_pile: List[FunctionCard] = Field(default_factory=list, description="功能卡弃牌堆")
    event_deck: List[EventCard] = Field(default_factory=list, description="事件卡牌库")
    system_warehouse: List[Artifact] = Field(default_factory=list, description="系统仓库（玩家出售的文物）")
    event_area: List[EventCard] = Field(default_factory=list, description="事件区（2张事件）")
    event_discard_pile: List[EventCard] = Field(default_factory=list, description="事件弃牌堆")
    discard_pile: List[Artifact] = Field(default_factory=list, description="弃牌堆")
    active_effects: List[str] = Field(default_factory=list, description="持续性效果标记")
    
    # 当前行动
    current_player_id: Optional[str] = None
    turn_order: List[str] = Field(default_factory=list, description="行动顺序")
    start_player_idx: int = 0  # 起始玩家索引


class GameState(BaseModel):
    """完整游戏状态"""
    global_state: GlobalState
    players: Dict[str, PlayerState] = Field(default_factory=dict)
    
    # 游戏日志
    action_log: List[str] = Field(default_factory=list, description="行动日志")
    
    def get_player(self, player_id: str) -> Optional[PlayerState]:
        """获取玩家状态"""
        return self.players.get(player_id)
    
    def get_current_player(self) -> Optional[PlayerState]:
        """获取当前行动玩家"""
        if self.global_state.current_player_id:
            return self.players.get(self.global_state.current_player_id)
        return None
    
    def add_log(self, message: str):
        """添加日志"""
        self.action_log.append(f"[回合{self.global_state.current_round}] {message}")
    
    def get_public_state(self) -> dict:
        """获取公开状态（供所有玩家查看）"""
        return {
            "current_round": self.global_state.current_round,
            "current_phase": self.global_state.current_phase.value,
            "stability": self.global_state.stability,
            "era_multipliers": self.global_state.era_multipliers,
            "auction_pool": [
                {
                    "artifact": item.artifact.model_dump(),
                    "auction_type": item.auction_type.value,
                    "current_highest_bid": item.current_highest_bid if item.auction_type == AuctionType.OPEN else None,
                    "current_highest_bidder": item.current_highest_bidder if item.auction_type == AuctionType.OPEN else None,
                }
                for item in self.global_state.auction_pool
            ],
            "system_warehouse": [a.model_dump() for a in self.global_state.system_warehouse],
            "event_area": [e.model_dump() for e in self.global_state.event_area],
            "artifact_deck_count": len(self.global_state.artifact_deck),
            "function_deck_count": len(self.global_state.card_deck),
            "function_discard_count": len(self.global_state.card_discard_pile),
            "event_deck_count": len(self.global_state.event_deck),
            "event_discard_count": len(self.global_state.event_discard_pile),
            "active_effects": list(self.global_state.active_effects),
            "players": {
                pid: {
                    "name": p.name,
                    "money": p.money,
                    "victory_points": p.victory_points,
                    "artifact_count": len(p.artifacts),
                    "card_count": len(p.function_cards),
                }
                for pid, p in self.players.items()
            },
            "current_player": self.global_state.current_player_id,
            "turn_order": self.global_state.turn_order,
        }
