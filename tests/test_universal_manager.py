"""Tests for UniversalGameManager"""
import json
import os
import pytest

from src.core.game_definition import GameDefinition
from src.core.universal_manager import UniversalGameManager


@pytest.fixture
def chronos_def():
    path = os.path.join(
        os.path.dirname(__file__),
        "..", "src", "games", "chronos_auction", "definition.json",
    )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return GameDefinition(**data)


@pytest.fixture
def simple_def():
    return GameDefinition(
        id="test_game",
        name="Test Game",
        version="1.0",
        player_count_min=2,
        player_count_max=4,
        resources=[
            {"id": "gold", "name": "Gold", "scope": "player", "initial_value": 10},
            {"id": "pool", "name": "Pool", "scope": "global", "initial_value": 50},
        ],
        categories=[
            {
                "id": "color",
                "name": "Color",
                "values": [
                    {"id": "red", "name": "Red"},
                    {"id": "blue", "name": "Blue"},
                ],
                "has_multiplier": True,
                "initial_multiplier": 1.0,
                "multiplier_range": [0.5, 3.0],
            },
        ],
        object_types=[
            {
                "id": "gem",
                "name": "Gem",
                "deck_name": "Gem Deck",
                "properties": [
                    {"id": "value", "name": "Value", "type": "integer"},
                    {"id": "color", "name": "Color", "type": "category_ref", "category_ref": "color"},
                ],
            },
        ],
        objects={
            "gem": [
                {"id": "g1", "name": "Ruby", "properties": {"value": 5, "color": "red"}},
                {"id": "g2", "name": "Sapphire", "properties": {"value": 3, "color": "blue"}},
                {"id": "g3", "name": "Garnet", "properties": {"value": 2, "color": "red"}},
            ],
        },
        zones=[
            {
                "id": "market",
                "name": "Market",
                "object_type": "gem",
                "auto_refill": {"source": "gem_deck", "target_size": "2"},
            },
        ],
        phases=[
            {"id": "setup", "name": "Setup"},
            {"id": "play", "name": "Play"},
            {"id": "end", "name": "End"},
        ],
        victory={"formula": "highest total wins", "end_conditions": ["game ends"]},
    )


@pytest.fixture
def mgr(simple_def):
    m = UniversalGameManager(simple_def)
    m.initialize_game(player_names=["Alice", "Bob"])
    return m


@pytest.fixture
def chronos_mgr(chronos_def):
    m = UniversalGameManager(chronos_def)
    m.initialize_game(player_names=["Alice", "Bob", "Carol"])
    return m


# ========== 初始化 ==========

class TestInitialization:
    def test_init_returns_status(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        result = mgr.initialize_game(player_names=["A", "B"])
        assert result["status"] == "initialized"
        assert len(result["players"]) == 2

    def test_init_too_few_players(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        result = mgr.initialize_game(player_names=["Only"])
        assert "error" in result

    def test_init_too_many_players(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        result = mgr.initialize_game(player_names=["A", "B", "C", "D", "E"])
        assert "error" in result

    def test_init_sets_player_resources(self, mgr):
        for player in mgr.game_state.players.values():
            assert player.gold == 10

    def test_init_sets_global_resources(self, mgr):
        assert mgr.game_state.global_state.pool == 50

    def test_init_creates_deck(self, mgr):
        deck = mgr.game_state.global_state.gem_deck
        assert len(deck) == 3  # 3 gems in definition

    def test_init_chronos(self, chronos_mgr):
        assert chronos_mgr.game_state is not None
        gs = chronos_mgr.game_state.global_state
        assert gs.game_id is not None
        assert len(chronos_mgr.game_state.players) == 3


# ========== 状态查询 ==========

class TestStateQuery:
    def test_get_state_before_init(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        result = mgr.get_game_state()
        assert "error" in result

    def test_get_state_returns_data(self, mgr):
        state = mgr.get_game_state()
        assert "game_id" in state
        assert "players" in state
        assert "current_round" in state
        assert state["pool"] == 50

    def test_get_state_shows_player_resources(self, mgr):
        state = mgr.get_game_state()
        for pid, pinfo in state["players"].items():
            assert "gold" in pinfo


# ========== 资源修改 ==========

class TestResourceUpdate:
    def test_update_player_resource(self, mgr):
        r = mgr.update_resource("gold", -3, "player_0")
        assert r["old_value"] == 10
        assert r["new_value"] == 7

    def test_update_global_resource(self, mgr):
        r = mgr.update_resource("pool", -10)
        assert r["new_value"] == 40

    def test_update_player_resource_without_pid(self, mgr):
        r = mgr.update_resource("gold", 5)
        assert "error" in r

    def test_update_unknown_resource(self, mgr):
        r = mgr.update_resource("mana", 5)
        assert "error" in r

    def test_update_unknown_player(self, mgr):
        r = mgr.update_resource("gold", 5, "nobody")
        assert "error" in r

    def test_update_resource_respects_min(self, simple_def):
        simple_def.resources[0].min_value = 0
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        r = mgr.update_resource("gold", -999, "player_0")
        assert r["new_value"] == 0


# ========== 物品转移 ==========

class TestTransferObject:
    def test_transfer_from_deck_to_player(self, mgr):
        deck = mgr.game_state.global_state.gem_deck
        first_gem_name = deck[0]["name"]
        r = mgr.transfer_object("gem", first_gem_name, "gem_deck", "player_0")
        assert r["transferred"] == first_gem_name
        assert r["to"] == "player_0"
        assert len(mgr.game_state.players["player_0"].gems) == 1

    def test_transfer_not_found(self, mgr):
        r = mgr.transfer_object("gem", "Nonexistent", "gem_deck", "player_0")
        assert "error" in r

    def test_transfer_id_reference_rejected(self, mgr):
        r = mgr.transfer_object("gem", "item_1", "gem_deck", "player_0")
        assert "error" in r

    def test_transfer_invalid_location(self, mgr):
        deck = mgr.game_state.global_state.gem_deck
        name = deck[0]["name"]
        r = mgr.transfer_object("gem", name, "nowhere", "player_0")
        assert "error" in r


# ========== 抽牌 ==========

class TestDrawFromDeck:
    def test_draw_to_player(self, mgr):
        r = mgr.draw_from_deck("gem", count=1, target_player_id="player_0")
        assert "error" not in r
        assert len(r["drawn"]) == 1
        assert len(mgr.game_state.players["player_0"].gems) == 1

    def test_draw_to_zone(self, mgr):
        r = mgr.draw_from_deck("gem", count=2, target_zone_id="market")
        assert "error" not in r
        assert len(r["drawn"]) == 2
        assert len(mgr.game_state.global_state.market) == 2

    def test_draw_no_target(self, mgr):
        r = mgr.draw_from_deck("gem", count=1)
        assert "error" in r

    def test_draw_unknown_type(self, mgr):
        r = mgr.draw_from_deck("potion", count=1, target_player_id="player_0")
        assert "error" in r

    def test_draw_exceeds_deck(self, mgr):
        r = mgr.draw_from_deck("gem", count=10, target_player_id="player_0")
        assert r["count"] == 3  # only 3 gems

    def test_draw_reshuffle_discard(self, mgr):
        # Draw all, put one in discard, then draw
        mgr.draw_from_deck("gem", count=3, target_player_id="player_0")
        assert len(mgr.game_state.global_state.gem_deck) == 0

        # Move one to discard
        player_gems = mgr.game_state.players["player_0"].gems
        gem = player_gems.pop(0)
        mgr.game_state.global_state.gem_discard_pile.append(gem)

        r = mgr.draw_from_deck("gem", count=1, target_player_id="player_1")
        assert "error" not in r
        assert len(r["drawn"]) == 1


# ========== 阶段流转 ==========

class TestPhaseManagement:
    def test_update_phase(self, mgr):
        r = mgr.update_phase("play")
        assert r["old_phase"] == "setup"
        assert r["new_phase"] == "play"

    def test_update_invalid_phase(self, mgr):
        r = mgr.update_phase("nonexistent")
        assert "error" in r

    def test_advance_round(self, mgr):
        r = mgr.advance_round()
        assert r["old_round"] == 1
        assert r["new_round"] == 2

    def test_advance_round_resets_acted(self, mgr):
        mgr.mark_player_acted("player_0")
        assert mgr.game_state.players["player_0"].has_acted is True
        mgr.advance_round()
        assert mgr.game_state.players["player_0"].has_acted is False


# ========== 倍率修改 ==========

class TestMultiplier:
    def test_update_multiplier(self, mgr):
        r = mgr.update_multiplier("color", "red", 0.5)
        assert r["old_multiplier"] == 1.0
        assert r["new_multiplier"] == 1.5

    def test_multiplier_clamped(self, mgr):
        r = mgr.update_multiplier("color", "red", 10.0)
        assert r["new_multiplier"] == 3.0  # max is 3.0

    def test_multiplier_unknown_category(self, mgr):
        r = mgr.update_multiplier("style", "red", 1.0)
        assert "error" in r

    def test_multiplier_unknown_value(self, mgr):
        r = mgr.update_multiplier("color", "green", 1.0)
        assert "error" in r


# ========== 玩家管理 ==========

class TestPlayerManagement:
    def test_set_current_player(self, mgr):
        r = mgr.set_current_player("player_0")
        assert r["current_player"] == "player_0"
        assert mgr.game_state.global_state.current_player_id == "player_0"

    def test_set_unknown_player(self, mgr):
        r = mgr.set_current_player("ghost")
        assert "error" in r

    def test_mark_acted(self, mgr):
        r = mgr.mark_player_acted("player_0")
        assert r["has_acted"] is True
        assert mgr.game_state.players["player_0"].has_acted is True

    def test_get_pending_players(self, mgr):
        mgr.mark_player_acted("player_0")
        r = mgr.get_players_for_action()
        ids = [p["id"] for p in r["pending_players"]]
        assert "player_0" not in ids
        assert "player_1" in ids


# ========== 通信 ==========

class TestBroadcast:
    def test_broadcast(self, mgr):
        r = mgr.broadcast_message("Hello!", sender="GM")
        assert r["broadcast"] == "Hello!"
        assert "[GM] Hello!" in mgr.game_state.action_log[-1]


# ========== 名称解析 ==========

class TestNameResolution:
    def test_exact_match(self, mgr):
        items = [{"id": "g1", "name": "Ruby"}, {"id": "g2", "name": "Sapphire"}]
        found, _, id_used = mgr._resolve_named_item(
            items, "Ruby",
            name_getter=lambda x: x["name"],
            id_getter=lambda x: x["id"],
        )
        assert found is not None
        assert found["name"] == "Ruby"
        assert not id_used

    def test_id_reference_rejected(self, mgr):
        items = [{"id": "g1", "name": "Ruby"}]
        found, _, id_used = mgr._resolve_named_item(
            items, "g1",
            name_getter=lambda x: x["name"],
            id_getter=lambda x: x["id"],
        )
        assert found is None
        assert id_used

    def test_partial_match(self, mgr):
        items = [{"id": "g1", "name": "Red Ruby"}, {"id": "g2", "name": "Blue Sapphire"}]
        found, _, _ = mgr._resolve_named_item(
            items, "Ruby",
            name_getter=lambda x: x["name"],
            id_getter=lambda x: x["id"],
        )
        assert found is not None
        assert found["name"] == "Red Ruby"

    def test_ambiguous_match(self, mgr):
        items = [{"id": "g1", "name": "Red Gem"}, {"id": "g2", "name": "Red Stone"}]
        found, candidates, _ = mgr._resolve_named_item(
            items, "Red",
            name_getter=lambda x: x["name"],
            id_getter=lambda x: x["id"],
        )
        assert found is None
        assert len(candidates) == 2

    def test_disallowed_id_pattern(self, mgr):
        items = [{"id": "func_1", "name": "Fireball"}]
        found, _, id_used = mgr._resolve_named_item(
            items, "func_1",
            name_getter=lambda x: x["name"],
            id_getter=lambda x: x["id"],
        )
        assert found is None
        assert id_used


# ========== Chronos 集成 ==========

class TestChronosIntegration:
    def test_chronos_init_player_money(self, chronos_mgr):
        for player in chronos_mgr.game_state.players.values():
            assert player.money == 20

    def test_chronos_multipliers(self, chronos_mgr):
        gs = chronos_mgr.game_state.global_state
        assert "ancient" in gs.era_multipliers
        assert gs.era_multipliers["ancient"] == 1.0

    def test_chronos_artifact_deck(self, chronos_mgr):
        gs = chronos_mgr.game_state.global_state
        assert len(gs.artifact_deck) == 36

    def test_chronos_draw_artifact(self, chronos_mgr):
        r = chronos_mgr.draw_from_deck("artifact", count=3, target_zone_id="auction_pool")
        assert "error" not in r
        assert len(r["drawn"]) == 3
        assert len(chronos_mgr.game_state.global_state.auction_pool) == 3

    def test_chronos_update_money(self, chronos_mgr):
        r = chronos_mgr.update_resource("money", -5, "player_0")
        assert r["new_value"] == 15

    def test_chronos_update_era_multiplier(self, chronos_mgr):
        r = chronos_mgr.update_multiplier("era", "ancient", 1.0)
        assert r["new_multiplier"] == 2.0

    def test_chronos_phase_flow(self, chronos_mgr):
        r = chronos_mgr.update_phase("event")
        assert r["new_phase"] == "event"
        r = chronos_mgr.update_phase("auction")
        assert r["new_phase"] == "auction"
