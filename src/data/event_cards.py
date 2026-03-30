"""
事件卡数据 - 根据《时空拍卖行》规则书定义的24张事件卡
"""
from ..models import EventCard


# 破坏Build方向 (8张)
DISRUPTION_EVENTS = [
    EventCard(
        id="event_01",
        name="时空震荡",
        effect="持有文物消耗总和最高的玩家必须弃置1件文物到弃牌堆。",
        category="disruption"
    ),
    EventCard(
        id="event_02",
        name="时空扭曲",
        effect="所有玩家同时将最左侧一张文物卡传递给下家（若无文物则跳过）。",
        category="disruption"
    ),
    EventCard(
        id="event_03",
        name="连锁抛售",
        effect="持有文物数量≥3的所有玩家，必须立即选择一张文物半价出售给系统（向下取整）。",
        category="disruption"
    ),
    EventCard(
        id="event_04",
        name="收藏审查",
        effect="所有玩家展示其持有的所有文物，持有同一时代文物最多的玩家必须弃置该时代的1件文物。",
        category="disruption"
    ),
    EventCard(
        id="event_05",
        name="文物贬值",
        effect="持有文物总数最多的玩家，其所有文物的基础价值在本回合出售时-2（最低为1）。",
        category="disruption"
    ),
    EventCard(
        id="event_06",
        name="文物充公",
        effect="所有持有传奇文物（价值为9）的玩家，每持有1件传奇文物需支付10资金，否则该文物被没收到弃牌堆。",
        category="disruption"
    ),
    EventCard(
        id="event_07",
        name="强制拍卖",
        effect="从起始玩家开始，每位玩家必须选择自己的1件文物进行公开拍卖（起拍价为基础价值×当前倍率×0.5），原持有者也可参与竞拍。",
        category="disruption"
    ),
    EventCard(
        id="event_08",
        name="收藏洗牌",
        effect="所有玩家将各自持有的文物卡牌面朝下洗混，然后按顺时针方向每人抽取与之前相同数量的文物（随机重新分配）。",
        category="disruption"
    ),
]

# 调整倍率方向 (8张)
MULTIPLIER_EVENTS = [
    EventCard(
        id="event_09",
        name="两极反转",
        effect="立即交换当前倍率最高与最低时代的倍率值。",
        category="multiplier"
    ),
    EventCard(
        id="event_10",
        name="市场崩盘",
        effect="立即将所有时代倍率各下降0.5（受×0.5下限限制）。",
        category="multiplier"
    ),
    EventCard(
        id="event_11",
        name="市场繁荣",
        effect="立即将所有时代倍率各上升0.5（受×2.5上限限制）。",
        category="multiplier"
    ),
    EventCard(
        id="event_12",
        name="倍率锁定",
        effect="下回合的投票阶段，禁止进行任何倍率调整投票。",
        category="multiplier"
    ),
    EventCard(
        id="event_13",
        name="古代热潮",
        effect="立即将古代时代倍率设置为×2.0，其他时代倍率各-0.5（受限制）。",
        category="multiplier"
    ),
    EventCard(
        id="event_14",
        name="未来狂热",
        effect="立即将未来时代倍率设置为×2.0，其他时代倍率各-0.5（受限制）。",
        category="multiplier"
    ),
    EventCard(
        id="event_15",
        name="近代复兴",
        effect="立即将近代时代倍率设置为×2.0，其他时代倍率各-0.5（受限制）。",
        category="multiplier"
    ),
    EventCard(
        id="event_16",
        name="倍率竞价",
        effect="从起始玩家开始，每位玩家可以支付5资金来指定一个时代的倍率上升0.5或下降0.5。",
        category="multiplier"
    ),
]

# 操纵拍卖方向 (8张)
AUCTION_EVENTS = [
    EventCard(
        id="event_17",
        name="拍卖狂热",
        effect="下回合所有公开拍卖的成交价+5。",
        category="auction"
    ),
    EventCard(
        id="event_18",
        name="市场萧条",
        effect="下回合所有拍卖的成交价-3（最低为1）。",
        category="auction"
    ),
    EventCard(
        id="event_19",
        name="暗箱操作",
        effect="下回合所有拍卖区的文物卡保持背面朝上进行密封拍卖，直到成交付款后方可翻开查看。",
        category="auction"
    ),
    EventCard(
        id="event_20",
        name="密封强制",
        effect="下回合所有拍卖改为密封竞标方式进行。",
        category="auction"
    ),
    EventCard(
        id="event_21",
        name="公开强制",
        effect="下回合所有拍卖改为公开拍卖方式进行。",
        category="auction"
    ),
    EventCard(
        id="event_22",
        name="拍卖加速",
        effect="下回合拍卖阶段，每次拍卖的最低加价改为3。",
        category="auction"
    ),
    EventCard(
        id="event_23",
        name="功能禁令",
        effect="下回合的拍卖阶段，所有玩家禁止使用任何功能卡。",
        category="auction"
    ),
    EventCard(
        id="event_24",
        name="拍卖限价",
        effect="下回合所有拍卖的最高出价上限为8，超过8的出价视为无效。",
        category="auction"
    ),
]

# 所有事件卡
ALL_EVENT_CARDS = DISRUPTION_EVENTS + MULTIPLIER_EVENTS + AUCTION_EVENTS


def get_shuffled_event_deck() -> list[EventCard]:
    """获取洗混后的事件卡牌库"""
    import random
    deck = [c.model_copy(deep=True) for c in ALL_EVENT_CARDS]
    random.shuffle(deck)
    return deck


# 按类型分类
EVENT_CATEGORIES = {
    "disruption": DISRUPTION_EVENTS,   # 破坏Build方向
    "multiplier": MULTIPLIER_EVENTS,   # 调整倍率方向
    "auction": AUCTION_EVENTS,         # 操纵拍卖方向
}
