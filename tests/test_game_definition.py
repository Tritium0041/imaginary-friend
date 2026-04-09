"""
测试 GameDefinition 模型 — 加载、序列化、校验
"""
import json
import tempfile
from pathlib import Path

import pytest

from src.core.game_definition import (
    AutoRefillDef,
    CategoryDef,
    CategoryValue,
    GameDefinition,
    GameObjectInstance,
    ObjectTypeDef,
    PhaseDef,
    PropertyDef,
    PropertyType,
    ResourceDef,
    ResourceScope,
    SetBonusDef,
    SpecialMechanicDef,
    VictoryDef,
    ZoneDef,
)

CHRONOS_DEF_PATH = Path(__file__).parent.parent / "src" / "games" / "chronos_auction" / "definition.json"


class TestGameDefinitionModel:
    """测试 GameDefinition Pydantic 模型基础功能"""

    def test_minimal_definition(self):
        """最小有效 GameDefinition"""
        gd = GameDefinition(name="测试游戏")
        assert gd.name == "测试游戏"
        assert gd.player_count_min == 2
        assert gd.player_count_max == 6
        assert gd.resources == []
        assert gd.categories == []
        assert gd.object_types == []

    def test_resource_def(self):
        """资源定义验证"""
        r = ResourceDef(id="gold", name="金币", icon="💰", initial_value=10)
        assert r.scope == ResourceScope.PLAYER
        assert r.min_value == 0
        assert r.max_value is None

    def test_global_resource(self):
        """全局资源"""
        r = ResourceDef(id="stability", name="稳定性", scope=ResourceScope.GLOBAL,
                        initial_value=100, max_value=100)
        assert r.scope == ResourceScope.GLOBAL
        assert r.max_value == 100

    def test_category_def(self):
        """分类定义验证"""
        c = CategoryDef(
            id="color",
            name="颜色",
            values=[
                CategoryValue(id="red", name="红"),
                CategoryValue(id="blue", name="蓝"),
            ],
        )
        assert len(c.values) == 2
        assert not c.has_multiplier

    def test_category_with_multiplier(self):
        """带倍率的分类"""
        c = CategoryDef(
            id="era",
            name="时代",
            values=[CategoryValue(id="ancient", name="古代")],
            has_multiplier=True,
            multiplier_range=(0.5, 2.5),
            initial_multiplier=1.0,
        )
        assert c.has_multiplier
        assert c.multiplier_range == (0.5, 2.5)

    def test_property_def_types(self):
        """属性定义各类型"""
        p_int = PropertyDef(id="value", type=PropertyType.INTEGER, min=0)
        p_enum = PropertyDef(id="color", type=PropertyType.ENUM, values=["red", "blue"])
        p_cat = PropertyDef(id="era", type=PropertyType.CATEGORY_REF, category="era")
        p_list = PropertyDef(id="tags", type=PropertyType.STRING_LIST)

        assert p_int.type == PropertyType.INTEGER
        assert p_enum.values == ["red", "blue"]
        assert p_cat.category == "era"
        assert p_list.type == PropertyType.STRING_LIST

    def test_object_type_def(self):
        """对象类型定义"""
        ot = ObjectTypeDef(
            id="card",
            name="卡牌",
            properties=[PropertyDef(id="value", type=PropertyType.INTEGER)],
            deck_name="主牌库",
            hand_limit=7,
        )
        assert ot.deck_name == "主牌库"
        assert ot.hand_limit == 7

    def test_phase_def(self):
        """阶段定义"""
        p = PhaseDef(
            id="auction",
            name="拍卖阶段",
            actions=["竞拍文物"],
            player_interaction="sequential_polling",
        )
        assert not p.auto
        assert p.player_interaction == "sequential_polling"

    def test_victory_def(self):
        """胜利条件定义"""
        v = VictoryDef(
            formula="sum(card.value)",
            end_conditions=["牌库为空"],
            set_bonuses=[SetBonusDef(name="全集", condition="收集全套", bonus=10)],
        )
        assert len(v.set_bonuses) == 1

    def test_zone_with_auto_refill(self):
        """带自动补充的区域"""
        z = ZoneDef(
            id="market",
            name="市场",
            object_type="card",
            auto_refill=AutoRefillDef(
                source="card_deck",
                target_size="player_count + 1",
            ),
        )
        assert z.auto_refill is not None
        assert z.auto_refill.source == "card_deck"


class TestGameDefinitionHelpers:
    """测试 GameDefinition 辅助方法"""

    @pytest.fixture
    def sample_def(self):
        return GameDefinition(
            name="测试",
            resources=[
                ResourceDef(id="gold", name="金币", scope=ResourceScope.PLAYER),
                ResourceDef(id="hp", name="生命", scope=ResourceScope.GLOBAL),
            ],
            categories=[
                CategoryDef(id="color", name="颜色", values=[
                    CategoryValue(id="red", name="红"),
                ]),
                CategoryDef(id="era", name="时代", values=[
                    CategoryValue(id="ancient", name="古"),
                ], has_multiplier=True),
            ],
            object_types=[
                ObjectTypeDef(id="card", name="卡牌", deck_name="牌库"),
                ObjectTypeDef(id="token", name="标记"),
            ],
            zones=[ZoneDef(id="market", name="市场", object_type="card")],
            phases=[
                PhaseDef(id="setup", name="初始化", auto=True),
                PhaseDef(id="main", name="主阶段"),
            ],
        )

    def test_get_resource(self, sample_def):
        assert sample_def.get_resource("gold") is not None
        assert sample_def.get_resource("missing") is None

    def test_get_player_resources(self, sample_def):
        player_res = sample_def.get_player_resources()
        assert len(player_res) == 1
        assert player_res[0].id == "gold"

    def test_get_global_resources(self, sample_def):
        global_res = sample_def.get_global_resources()
        assert len(global_res) == 1
        assert global_res[0].id == "hp"

    def test_get_category(self, sample_def):
        assert sample_def.get_category("color") is not None
        assert sample_def.get_category("missing") is None

    def test_get_categories_with_multiplier(self, sample_def):
        cats = sample_def.get_categories_with_multiplier()
        assert len(cats) == 1
        assert cats[0].id == "era"

    def test_get_object_type(self, sample_def):
        assert sample_def.get_object_type("card") is not None
        assert sample_def.get_object_type("missing") is None

    def test_get_holdable_object_types(self, sample_def):
        holdable = sample_def.get_holdable_object_types()
        assert len(holdable) == 1
        assert holdable[0].id == "card"

    def test_get_zone(self, sample_def):
        assert sample_def.get_zone("market") is not None
        assert sample_def.get_zone("missing") is None

    def test_get_phase(self, sample_def):
        assert sample_def.get_phase("setup") is not None
        assert sample_def.get_phase("missing") is None


class TestChronosAuctionDefinition:
    """测试时空拍卖行的 GameDefinition 加载"""

    @pytest.fixture
    def chronos_def(self):
        return GameDefinition.load_from_file(CHRONOS_DEF_PATH)

    def test_load_from_json(self, chronos_def):
        """能从 JSON 文件加载"""
        assert chronos_def.name == "时空拍卖行"
        assert chronos_def.name_en == "Chronos Auction House"

    def test_player_count(self, chronos_def):
        assert chronos_def.player_count_min == 3
        assert chronos_def.player_count_max == 5

    def test_resources(self, chronos_def):
        """验证资源定义"""
        assert len(chronos_def.resources) == 3
        money = chronos_def.get_resource("money")
        assert money is not None
        assert money.initial_value == 20
        assert money.scope == ResourceScope.PLAYER

        stability = chronos_def.get_resource("stability")
        assert stability is not None
        assert stability.scope == ResourceScope.GLOBAL
        assert stability.initial_value == 100
        assert stability.max_value == 100

    def test_categories(self, chronos_def):
        """验证分类系统"""
        assert len(chronos_def.categories) == 2
        era = chronos_def.get_category("era")
        assert era is not None
        assert len(era.values) == 3
        assert era.has_multiplier
        era_ids = {v.id for v in era.values}
        assert era_ids == {"ancient", "modern", "future"}

        rarity = chronos_def.get_category("rarity")
        assert rarity is not None
        assert len(rarity.values) == 3
        assert not rarity.has_multiplier

    def test_object_types(self, chronos_def):
        """验证对象类型"""
        assert len(chronos_def.object_types) == 3

        artifact = chronos_def.get_object_type("artifact")
        assert artifact is not None
        assert artifact.deck_name == "文物牌库"
        assert len(artifact.properties) == 6

        func_card = chronos_def.get_object_type("function_card")
        assert func_card is not None
        assert func_card.deck_name == "功能卡库"

        event_card = chronos_def.get_object_type("event_card")
        assert event_card is not None
        assert event_card.area_name == "事件区"
        assert event_card.area_size == 2

    def test_zones(self, chronos_def):
        """验证公共区域"""
        assert len(chronos_def.zones) == 5
        auction_pool = chronos_def.get_zone("auction_pool")
        assert auction_pool is not None
        assert auction_pool.auto_refill is not None
        assert auction_pool.auto_refill.source == "artifact_deck"

    def test_phases(self, chronos_def):
        """验证阶段定义"""
        assert len(chronos_def.phases) == 9
        setup = chronos_def.get_phase("setup")
        assert setup is not None
        assert setup.auto

        auction = chronos_def.get_phase("auction")
        assert auction is not None
        assert auction.player_interaction == "sequential_polling"

    def test_phase_order(self, chronos_def):
        """验证阶段顺序"""
        assert chronos_def.phase_order == [
            "excavation", "auction", "trading", "buyback",
            "event", "vote", "stabilize",
        ]

    def test_victory(self, chronos_def):
        """验证胜利条件"""
        assert chronos_def.victory is not None
        assert len(chronos_def.victory.end_conditions) == 2
        assert len(chronos_def.victory.set_bonuses) == 3

    def test_special_mechanics(self, chronos_def):
        """验证特殊机制"""
        assert len(chronos_def.special_mechanics) == 4
        mechanic_ids = {m.id for m in chronos_def.special_mechanics}
        assert "sealed_auction" in mechanic_ids
        assert "open_auction" in mechanic_ids

    def test_artifact_objects(self, chronos_def):
        """验证文物对象实例 — 36 张"""
        artifacts = chronos_def.objects.get("artifact", [])
        assert len(artifacts) == 36

        # 验证每个时代各 12 张
        era_counts = {}
        for a in artifacts:
            era = a.properties["era"]
            era_counts[era] = era_counts.get(era, 0) + 1
        assert era_counts == {"ancient": 12, "modern": 12, "future": 12}

        # 验证 ID 唯一
        ids = [a.id for a in artifacts]
        assert len(ids) == len(set(ids))

    def test_function_card_objects(self, chronos_def):
        """验证功能卡对象实例 — 24 张"""
        cards = chronos_def.objects.get("function_card", [])
        assert len(cards) == 24

        # 验证 ID 唯一
        ids = [c.id for c in cards]
        assert len(ids) == len(set(ids))

        # 验证分类分布
        cat_counts = {}
        for c in cards:
            cat = c.properties["category"]
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        assert cat_counts == {"disruption": 10, "multiplier": 7, "auction": 7}

    def test_event_card_objects(self, chronos_def):
        """验证事件卡对象实例 — 24 张"""
        cards = chronos_def.objects.get("event_card", [])
        assert len(cards) == 24

        ids = [c.id for c in cards]
        assert len(ids) == len(set(ids))

        cat_counts = {}
        for c in cards:
            cat = c.properties["category"]
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        assert cat_counts == {"disruption": 8, "multiplier": 8, "auction": 8}

    def test_artifact_properties_match_original(self, chronos_def):
        """验证文物属性与原始数据一致（抽样检查）"""
        artifacts = chronos_def.objects.get("artifact", [])
        artifacts_by_id = {a.id: a for a in artifacts}

        # 王朝玉玺
        jade_seal = artifacts_by_id["anc_01"]
        assert jade_seal.name == "王朝玉玺"
        assert jade_seal.properties["era"] == "ancient"
        assert jade_seal.properties["rarity"] == "legendary"
        assert jade_seal.properties["base_value"] == 8
        assert jade_seal.properties["time_cost"] == 9
        assert jade_seal.properties["auction_type"] == "sealed"
        assert jade_seal.properties["keywords"] == ["权力", "历史"]

        # 戴森球蓝图
        dyson = artifacts_by_id["fut_01"]
        assert dyson.name == "戴森球蓝图"
        assert dyson.properties["era"] == "future"
        assert dyson.properties["rarity"] == "legendary"
        assert dyson.properties["auction_type"] == "open"


class TestGameDefinitionSerialization:
    """测试序列化和反序列化"""

    def test_roundtrip_json(self):
        """JSON 序列化往返"""
        gd = GameDefinition(
            name="测试",
            resources=[ResourceDef(id="gold", name="金币")],
            categories=[
                CategoryDef(
                    id="color",
                    name="颜色",
                    values=[CategoryValue(id="red", name="红")],
                )
            ],
            objects={
                "item": [
                    GameObjectInstance(
                        id="item_01",
                        name="宝剑",
                        properties={"attack": 5},
                    )
                ]
            },
        )
        json_str = gd.model_dump_json()
        restored = GameDefinition.model_validate_json(json_str)
        assert restored.name == gd.name
        assert len(restored.resources) == 1
        assert len(restored.objects["item"]) == 1

    def test_save_and_load_file(self):
        """文件保存和加载"""
        gd = GameDefinition(
            name="文件测试",
            resources=[ResourceDef(id="hp", name="生命值", scope=ResourceScope.GLOBAL)],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_def.json"
            gd.save_to_file(path)
            assert path.exists()

            loaded = GameDefinition.load_from_file(path)
            assert loaded.name == "文件测试"
            assert loaded.resources[0].id == "hp"
            assert loaded.resources[0].scope == ResourceScope.GLOBAL

    def test_chronos_roundtrip(self):
        """时空拍卖行 JSON 完整往返"""
        original = GameDefinition.load_from_file(CHRONOS_DEF_PATH)
        json_str = original.model_dump_json()
        restored = GameDefinition.model_validate_json(json_str)
        assert restored.name == original.name
        assert len(restored.objects["artifact"]) == 36
        assert len(restored.objects["function_card"]) == 24
        assert len(restored.objects["event_card"]) == 24
