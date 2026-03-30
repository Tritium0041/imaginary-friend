"""
文物数据 - 根据《时空拍卖行》规则书定义的36张文物卡
"""
from ..models import Era, Rarity, AuctionType, Artifact

# 古代文物 (12张)
ANCIENT_ARTIFACTS = [
    Artifact(id="anc_01", name="王朝玉玺", era=Era.ANCIENT, rarity=Rarity.LEGENDARY,
             time_cost=9, base_value=8, auction_type=AuctionType.SEALED, keywords=["权力", "历史"]),
    Artifact(id="anc_02", name="汉莫拉比法典碑", era=Era.ANCIENT, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.OPEN, keywords=["权力", "数据"]),
    Artifact(id="anc_03", name="图坦卡蒙面具", era=Era.ANCIENT, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.OPEN, keywords=["宗教", "艺术"]),
    Artifact(id="anc_04", name="武士刀·村正", era=Era.ANCIENT, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.SEALED, keywords=["战争", "艺术"]),
    Artifact(id="anc_05", name="玛雅太阳历石", era=Era.ANCIENT, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.SEALED, keywords=["宗教", "空间"]),
    Artifact(id="anc_06", name="维京战盾", era=Era.ANCIENT, rarity=Rarity.COMMON,
             time_cost=3, base_value=4, auction_type=AuctionType.OPEN, keywords=["战争", "交通"]),
    Artifact(id="anc_07", name="希腊大理石像", era=Era.ANCIENT, rarity=Rarity.COMMON,
             time_cost=-3, base_value=4, auction_type=AuctionType.SEALED, keywords=["生命", "经济"]),
    Artifact(id="anc_08", name="兵马俑士兵", era=Era.ANCIENT, rarity=Rarity.COMMON,
             time_cost=3, base_value=4, auction_type=AuctionType.OPEN, keywords=["生命", "历史"]),
    Artifact(id="anc_09", name="梵文贝叶经", era=Era.ANCIENT, rarity=Rarity.COMMON,
             time_cost=3, base_value=4, auction_type=AuctionType.SEALED, keywords=["数据", "科技"]),
    Artifact(id="anc_10", name="苏美尔泥板", era=Era.ANCIENT, rarity=Rarity.COMMON,
             time_cost=-3, base_value=4, auction_type=AuctionType.OPEN, keywords=["经济", "交通"]),
    Artifact(id="anc_11", name="罗马金币", era=Era.ANCIENT, rarity=Rarity.COMMON,
             time_cost=0, base_value=2, auction_type=AuctionType.SEALED, keywords=["能源", "空间"]),
    Artifact(id="anc_12", name="青铜古镜", era=Era.ANCIENT, rarity=Rarity.COMMON,
             time_cost=0, base_value=2, auction_type=AuctionType.OPEN, keywords=["能源", "科技"]),
]

# 近代文物 (12张)
MODERN_ARTIFACTS = [
    Artifact(id="mod_01", name="登月旗帜", era=Era.MODERN, rarity=Rarity.LEGENDARY,
             time_cost=9, base_value=8, auction_type=AuctionType.SEALED, keywords=["空间", "历史"]),
    Artifact(id="mod_02", name="瓦特蒸汽机原型", era=Era.MODERN, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.OPEN, keywords=["能源", "战争"]),
    Artifact(id="mod_03", name="初版个人电脑", era=Era.MODERN, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.OPEN, keywords=["科技", "数据"]),
    Artifact(id="mod_04", name="Enigma 密码机", era=Era.MODERN, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.SEALED, keywords=["战争", "数据"]),
    Artifact(id="mod_05", name="印象派画作", era=Era.MODERN, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.SEALED, keywords=["艺术", "经济"]),
    Artifact(id="mod_06", name="早期宇航服", era=Era.MODERN, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.OPEN, keywords=["空间", "生命"]),
    Artifact(id="mod_07", name="T 型车模型", era=Era.MODERN, rarity=Rarity.COMMON,
             time_cost=-3, base_value=4, auction_type=AuctionType.SEALED, keywords=["交通", "经济"]),
    Artifact(id="mod_08", name="第一张黑胶唱片", era=Era.MODERN, rarity=Rarity.COMMON,
             time_cost=3, base_value=4, auction_type=AuctionType.OPEN, keywords=["艺术", "科技"]),
    Artifact(id="mod_09", name="无声电影胶卷", era=Era.MODERN, rarity=Rarity.COMMON,
             time_cost=3, base_value=4, auction_type=AuctionType.SEALED, keywords=["生命", "历史"]),
    Artifact(id="mod_10", name="签名电吉他", era=Era.MODERN, rarity=Rarity.COMMON,
             time_cost=-3, base_value=4, auction_type=AuctionType.OPEN, keywords=["权力", "宗教"]),
    Artifact(id="mod_11", name="柏林墙碎块", era=Era.MODERN, rarity=Rarity.COMMON,
             time_cost=0, base_value=2, auction_type=AuctionType.SEALED, keywords=["权力", "宗教"]),
    Artifact(id="mod_12", name="铁皮机器人玩具", era=Era.MODERN, rarity=Rarity.COMMON,
             time_cost=0, base_value=2, auction_type=AuctionType.OPEN, keywords=["能源", "交通"]),
]

# 未来文物 (12张)
FUTURE_ARTIFACTS = [
    Artifact(id="fut_01", name="戴森球蓝图", era=Era.FUTURE, rarity=Rarity.LEGENDARY,
             time_cost=9, base_value=8, auction_type=AuctionType.OPEN, keywords=["能源", "空间"]),
    Artifact(id="fut_02", name="反重力核心", era=Era.FUTURE, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.OPEN, keywords=["能源", "交通"]),
    Artifact(id="fut_03", name="觉醒 AI 芯片", era=Era.FUTURE, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.SEALED, keywords=["生命", "数据"]),
    Artifact(id="fut_04", name="传送门密钥", era=Era.FUTURE, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.OPEN, keywords=["交通", "空间"]),
    Artifact(id="fut_05", name="时间胶囊 3000", era=Era.FUTURE, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.SEALED, keywords=["历史", "数据"]),
    Artifact(id="fut_06", name="暗物质样本", era=Era.FUTURE, rarity=Rarity.RARE,
             time_cost=6, base_value=6, auction_type=AuctionType.SEALED, keywords=["战争", "科技"]),
    Artifact(id="fut_07", name="全息记忆体", era=Era.FUTURE, rarity=Rarity.COMMON,
             time_cost=-3, base_value=4, auction_type=AuctionType.OPEN, keywords=["艺术", "生命"]),
    Artifact(id="fut_08", name="赛博义肢", era=Era.FUTURE, rarity=Rarity.COMMON,
             time_cost=3, base_value=4, auction_type=AuctionType.SEALED, keywords=["经济", "科技"]),
    Artifact(id="fut_09", name="零点电池", era=Era.FUTURE, rarity=Rarity.COMMON,
             time_cost=3, base_value=4, auction_type=AuctionType.OPEN, keywords=["权力", "宗教"]),
    Artifact(id="fut_10", name="星舰残骸板", era=Era.FUTURE, rarity=Rarity.COMMON,
             time_cost=-3, base_value=4, auction_type=AuctionType.SEALED, keywords=["战争", "历史"]),
    Artifact(id="fut_11", name="火星殖民船票", era=Era.FUTURE, rarity=Rarity.COMMON,
             time_cost=0, base_value=2, auction_type=AuctionType.OPEN, keywords=["经济", "宗教"]),
    Artifact(id="fut_12", name="脑机接口耳机", era=Era.FUTURE, rarity=Rarity.COMMON,
             time_cost=0, base_value=2, auction_type=AuctionType.SEALED, keywords=["权力", "艺术"]),
]

# 所有文物
ALL_ARTIFACTS = ANCIENT_ARTIFACTS + MODERN_ARTIFACTS + FUTURE_ARTIFACTS


def get_shuffled_artifact_deck() -> list[Artifact]:
    """获取洗混后的文物牌库"""
    import random
    deck = [a.model_copy() for a in ALL_ARTIFACTS]
    random.shuffle(deck)
    return deck
