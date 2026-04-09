"""Tests for ToolGenerator and ToolRouter"""
import json
import os
import pytest

from src.core.game_definition import GameDefinition
from src.core.tool_generator import ToolGenerator, ToolRouter
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
                ],
            },
        ],
        objects={
            "gem": [
                {"id": "g1", "name": "Ruby", "properties": {"value": 5}},
                {"id": "g2", "name": "Sapphire", "properties": {"value": 3}},
            ],
        },
        zones=[],
        phases=[
            {"id": "setup", "name": "Setup"},
            {"id": "play", "name": "Play"},
        ],
        victory={"formula": "highest total", "end_conditions": ["game over"]},
    )


class TestToolGenerator:
    def test_generate_returns_list(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_universal_tools_present(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        names = {t["name"] for t in tools}
        assert "get_game_state" in names
        assert "set_current_player" in names
        assert "broadcast_message" in names
        assert "advance_round" in names
        assert "request_player_action" in names

    def test_resource_tools_generated(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        names = {t["name"] for t in tools}
        assert "update_gold" in names
        assert "update_pool" in names

    def test_player_resource_requires_player_id(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        gold_tool = next(t for t in tools if t["name"] == "update_gold")
        assert "player_id" in gold_tool["input_schema"]["required"]

    def test_global_resource_no_player_id_required(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        pool_tool = next(t for t in tools if t["name"] == "update_pool")
        assert "player_id" not in pool_tool["input_schema"]["required"]

    def test_object_tools_generated(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        names = {t["name"] for t in tools}
        assert "transfer_gem" in names
        assert "draw_gem" in names

    def test_multiplier_tools_generated(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        names = {t["name"] for t in tools}
        assert "update_color_multiplier" in names

    def test_phase_tool_has_valid_phases(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        phase_tool = next(t for t in tools if t["name"] == "update_phase")
        assert "setup" in phase_tool["input_schema"]["properties"]["new_phase"]["enum"]
        assert "play" in phase_tool["input_schema"]["properties"]["new_phase"]["enum"]

    def test_all_tools_have_required_keys(self, simple_def):
        gen = ToolGenerator()
        tools = gen.generate(simple_def)
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_chronos_tools(self, chronos_def):
        gen = ToolGenerator()
        tools = gen.generate(chronos_def)
        names = {t["name"] for t in tools}
        assert "update_money" in names
        assert "transfer_artifact" in names
        assert "draw_artifact" in names
        assert "draw_function_card" in names
        assert "draw_event_card" in names
        assert "update_era_multiplier" in names


class TestToolRouter:
    def test_router_basic(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        router = ToolRouter(simple_def, mgr)
        assert router.has_tool("get_game_state")
        assert router.has_tool("update_gold")
        assert not router.has_tool("nonexistent")

    def test_route_get_state(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        router = ToolRouter(simple_def, mgr)
        result = router.route("get_game_state", {})
        assert "game_id" in result
        assert "players" in result

    def test_route_update_resource(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        router = ToolRouter(simple_def, mgr)
        result = router.route("update_gold", {"player_id": "player_0", "delta": -3})
        assert result["new_value"] == 7

    def test_route_update_multiplier(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        router = ToolRouter(simple_def, mgr)
        result = router.route("update_color_multiplier", {"value_id": "red", "delta": 0.5})
        assert result["new_multiplier"] == 1.5

    def test_route_unknown_tool(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        router = ToolRouter(simple_def, mgr)
        result = router.route("nonexistent", {})
        assert "error" in result

    def test_route_draw(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        router = ToolRouter(simple_def, mgr)
        result = router.route("draw_gem", {"count": 1, "target_player_id": "player_0"})
        assert "error" not in result
        assert len(result["drawn"]) == 1

    def test_route_phase(self, simple_def):
        mgr = UniversalGameManager(simple_def)
        mgr.initialize_game(player_names=["A", "B"])
        router = ToolRouter(simple_def, mgr)
        result = router.route("update_phase", {"new_phase": "play"})
        assert result["new_phase"] == "play"
