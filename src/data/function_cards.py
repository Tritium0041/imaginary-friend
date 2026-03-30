"""
功能卡数据 - 根据《时空拍卖行》规则书定义的24张功能卡
"""
from ..models import FunctionCard

# 破坏Build方向 (10张)
DISRUPTION_CARDS = [
    FunctionCard(
        id="func_01", 
        name="赝品指控",
        effect="指定场上或任意玩家持有的一件文物，该文物的基础价值永久-2（最低为0）。",
        description="破坏对手的高价值文物"
    ),
    FunctionCard(
        id="func_02",
        name="快速调包",
        effect="将拍卖区中的一张文物与牌堆顶文物交换（新文物立即翻开）。",
        description="改变拍卖区的文物"
    ),
    FunctionCard(
        id="func_03",
        name="拍卖劫持",
        effect="取消当前正在进行的拍卖，该文物进入弃牌堆，所有已出价金返还。",
        description="强制取消拍卖"
    ),
    FunctionCard(
        id="func_04",
        name="强制征收",
        effect="指定一名玩家，强制与其交换一件文物，交换价格固定为10资金（由你支付给对方）。",
        description="强制交易文物"
    ),
    FunctionCard(
        id="func_05",
        name="文物封存",
        effect="指定对手的一张文物，该文物本回合禁止出售、交易，且不计入套装奖励。",
        description="暂时冻结文物"
    ),
    FunctionCard(
        id="func_06",
        name="套装破坏者",
        effect="指定一名对手，查看其所有文物，选择其中一张强制其以半价出售给系统（向下取整）。",
        description="强制对手出售文物"
    ),
    FunctionCard(
        id="func_07",
        name="收藏劫掠",
        effect="指定一名玩家，从其手中随机抽取一张文物卡（需支付其5资金作为补偿）。",
        description="抢夺对手文物"
    ),
    FunctionCard(
        id="func_08",
        name="时空置换",
        effect="选择场上两名玩家（可包括自己），强制他们交换一件文物（双方各自选择要交换出去的文物）。",
        description="强制两人交换文物"
    ),
    FunctionCard(
        id="func_09",
        name="伪造鉴定",
        effect="指定任意玩家持有的一件文物，将其时代属性改为你指定的一个时代。",
        description="改变文物时代"
    ),
    FunctionCard(
        id="func_10",
        name="黑市没收",
        effect="本回合拍卖阶段结束时使用，选择本回合任意一名竞拍成功的玩家，将其刚获得的文物转移给你（需支付其成交价的80%，向上取整）。",
        description="截胡他人拍得的文物"
    ),
]

# 调整倍率方向 (7张)
MULTIPLIER_CARDS = [
    FunctionCard(
        id="func_11",
        name="倍率冲击",
        effect="立即将指定一个时代的倍率上升或下降0.5（仍受×0.5到×2.5限制）。",
        description="直接调整倍率"
    ),
    FunctionCard(
        id="func_12",
        name="倍率固锁",
        effect="在投票阶段前使用，指定一个时代，本回合该时代倍率不可通过投票调整。",
        description="锁定倍率"
    ),
    FunctionCard(
        id="func_13",
        name="市场操纵",
        effect="在投票阶段使用，你可以额外发起一次倍率调整提议（不占用正常提议次数）。",
        description="额外发起提议"
    ),
    FunctionCard(
        id="func_14",
        name="倍率互换",
        effect="立即交换任意两个时代的当前倍率值。",
        description="交换两个时代倍率"
    ),
    FunctionCard(
        id="func_15",
        name="事件预测",
        effect="查看事件牌堆顶3张卡牌，按任意顺序放回。",
        description="预知事件"
    ),
    FunctionCard(
        id="func_16",
        name="强制平衡",
        effect="立即将所有时代倍率重置为×1.0。",
        description="重置所有倍率"
    ),
    FunctionCard(
        id="func_17",
        name="投票操控",
        effect="在投票阶段使用，本回合你的每个投票标记（✅/❌）计为2票。",
        description="双倍投票权"
    ),
]

# 操纵拍卖方向 (7张)
AUCTION_CARDS = [
    FunctionCard(
        id="func_18",
        name="密标窥探",
        effect="密封竞标中，可以偷看一名玩家的出价筹码。",
        description="偷看密封出价"
    ),
    FunctionCard(
        id="func_19",
        name="密标干扰",
        effect="密封竞标中，强制指定一名玩家提前亮出其出价（其他玩家随后亮出）。",
        description="破坏密封竞标"
    ),
    FunctionCard(
        id="func_20",
        name="价格锚定",
        effect="公开拍卖开始前使用，设定本次拍卖的价格上限（必须≥当前出价+3），后续所有出价不得超过此上限。",
        description="限制最高出价"
    ),
    FunctionCard(
        id="func_21",
        name="费用减免",
        effect="在你竞拍成功后使用，本次拍卖的成交价-5（最低为1）。",
        description="减少支付金额"
    ),
    FunctionCard(
        id="func_22",
        name="恶意抬价",
        effect="公开拍卖中使用，立即将当前出价提高50%（向上取整）。",
        description="抬高当前出价"
    ),
    FunctionCard(
        id="func_23",
        name="代理竞标",
        effect="密封竞标中可握持两组筹码，亮出时选择其中一组为有效出价，另一组收回。",
        description="双重出价选择"
    ),
    FunctionCard(
        id="func_24",
        name="拍卖情报",
        effect="挖掘阶段使用，查看文物牌堆顶5张卡牌，选择其中任意张按任意顺序放置在拍卖区，其余放回牌堆底。",
        description="控制拍卖区文物"
    ),
]

# 所有功能卡
ALL_FUNCTION_CARDS = DISRUPTION_CARDS + MULTIPLIER_CARDS + AUCTION_CARDS


def get_shuffled_function_deck() -> list[FunctionCard]:
    """获取洗混后的功能卡牌库"""
    import random
    deck = [c.model_copy() for c in ALL_FUNCTION_CARDS]
    random.shuffle(deck)
    return deck


# 按类型分类
CARD_CATEGORIES = {
    "disruption": DISRUPTION_CARDS,    # 破坏Build方向
    "multiplier": MULTIPLIER_CARDS,    # 调整倍率方向
    "auction": AUCTION_CARDS,          # 操纵拍卖方向
}
