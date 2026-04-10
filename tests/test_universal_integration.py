"""Integration tests: GMAgent universal mode + Server integration."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.game_definition import GameDefinition
from src.core.game_loader import load_game_definition, discover_games
from src.core.tool_generator import ToolGenerator, ToolRouter
from src.core.prompt_generator import PromptGenerator
from src.core.universal_manager import UniversalGameManager
from src.agents.gm_agent import GMAgent, GMConfig


# ---- Fixtures ----

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
        ],
        categories=[],
        object_types=[],
        phases=[
            {"id": "main", "name": "Main Phase", "description": "The main phase"},
        ],
        victory_conditions=[],
    )


# ---- Fake Anthropic ----

@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeResponse:
    stop_reason: str
    content: list
    usage: object | None = None


class _FakeMessagesAPI:
    def __init__(self):
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(
            stop_reason="end_turn",
            content=[_FakeTextBlock("🎲 游戏开始！")],
        )


class _FakeAnthropicClient:
    def __init__(self):
        self.messages = _FakeMessagesAPI()


# ---- GMAgent Universal Mode Tests ----

class TestGMAgentUniversalInit:
    """Test that GMAgent initializes correctly."""

    def test_universal_mode_attributes(self, chronos_def):
        gm = GMAgent(game_definition=chronos_def, on_output=lambda x: None)
        assert gm.universal_mgr is not None
        assert gm.game_definition is chronos_def

    def test_universal_tools_generated(self, chronos_def):
        gm = GMAgent(game_definition=chronos_def, on_output=lambda x: None)
        tool_names = {t["name"] for t in gm.tools}
        assert "get_game_state" in tool_names
        assert "request_player_action" in tool_names
        assert "ask_human_ruling" in tool_names
        assert "broadcast_message" in tool_names

    def test_universal_tools_match_generator(self, chronos_def):
        gm = GMAgent(game_definition=chronos_def, on_output=lambda x: None)
        gen = ToolGenerator()
        expected = gen.generate(chronos_def)
        assert len(gm.tools) == len(expected)
        expected_names = {t["name"] for t in expected}
        actual_names = {t["name"] for t in gm.tools}
        assert actual_names == expected_names


class TestGMAgentUniversalStartGame:
    """Test universal mode start_game."""

    def test_start_game_initializes_state(self, chronos_def):
        outputs = []
        gm = GMAgent(game_definition=chronos_def, on_output=outputs.append)
        gm.client = _FakeAnthropicClient()

        result = gm.start_game(
            player_names=[("Alice", True), ("Bob", False), ("Charlie", False)],
            game_id="test-001",
        )

        assert gm.session is not None
        assert gm.session.game_id == "test-001"
        assert gm.tool_router is not None
        assert gm.universal_mgr.game_state is not None

        # Check players were created
        players = gm.universal_mgr.game_state.players
        assert len(players) == 3
        assert players["player_0"].is_human is True
        assert players["player_1"].is_human is False
        assert players["player_2"].is_human is False

    def test_start_game_creates_ai_agents(self, chronos_def):
        gm = GMAgent(game_definition=chronos_def, on_output=lambda x: None)
        gm.client = _FakeAnthropicClient()

        gm.start_game(
            player_names=[("Alice", True), ("Bob", False), ("Charlie", False)],
            game_id="test-002",
        )

        assert "player_1" in gm.session.player_agents
        assert "player_2" in gm.session.player_agents
        assert "player_0" not in gm.session.player_agents

    def test_start_game_uses_prompt_generator(self, chronos_def):
        gm = GMAgent(game_definition=chronos_def, on_output=lambda x: None)
        gm.client = _FakeAnthropicClient()

        gm.start_game(
            player_names=[("Alice", True), ("Bob", False), ("Charlie", False)],
            game_id="test-003",
        )

        system_msg = next(
            m for m in gm.session.messages if m.role == "system"
        )
        # PromptGenerator should have included game name
        assert chronos_def.name in system_msg.content


class TestGMAgentUniversalExecuteTool:
    """Test _execute_tool routing in universal mode."""

    def _make_gm(self, game_def):
        gm = GMAgent(game_definition=game_def, on_output=lambda x: None)
        gm.client = _FakeAnthropicClient()
        gm.start_game(
            player_names=[("Alice", True), ("Bob", False), ("Charlie", False)],
            game_id="tool-test",
        )
        return gm

    def test_get_game_state_routed(self, chronos_def):
        gm = self._make_gm(chronos_def)
        result = gm._execute_tool("get_game_state", {})
        assert isinstance(result, dict)
        assert "players" in result

    def test_broadcast_message_emits(self, chronos_def):
        outputs = []
        gm = GMAgent(game_definition=chronos_def, on_output=outputs.append)
        gm.client = _FakeAnthropicClient()
        gm.start_game(
            player_names=[("Alice", True), ("Bob", False), ("Charlie", False)],
            game_id="broadcast-test",
        )

        result = gm._execute_tool("broadcast_message", {"message": "Hello!"})
        assert result == {"success": True}
        assert any("Hello!" in str(o) for o in outputs)

    def test_request_player_action_human_waits(self, chronos_def):
        gm = self._make_gm(chronos_def)
        result = gm._execute_tool(
            "request_player_action",
            {"player_id": "player_0", "action_type": "bid", "context": "出价"},
        )
        assert result["waiting"] is True
        assert gm.session.is_waiting_for_human is True

    def test_ask_human_ruling_waits(self, chronos_def):
        gm = self._make_gm(chronos_def)
        result = gm._execute_tool(
            "ask_human_ruling",
            {"question": "如何裁定？", "options": ["A", "B"]},
        )
        assert result["waiting"] is True

    def test_unknown_tool_returns_error(self, chronos_def):
        gm = self._make_gm(chronos_def)
        result = gm._execute_tool("nonexistent_tool", {})
        assert "error" in result


class TestUniversalManagerIsHuman:
    """Test initialize_game is_human parameter handling."""

    def test_tuple_format(self, chronos_def):
        mgr = UniversalGameManager(chronos_def)
        result = mgr.initialize_game(
            player_names=[("Alice", True), ("Bob", False), ("Charlie", True)],
        )
        assert result.get("status") == "initialized"
        assert mgr.game_state.players["player_0"].is_human is True
        assert mgr.game_state.players["player_1"].is_human is False
        assert mgr.game_state.players["player_2"].is_human is True

    def test_str_format_defaults(self, chronos_def):
        mgr = UniversalGameManager(chronos_def)
        result = mgr.initialize_game(
            player_names=["Alice", "Bob", "Charlie"],
        )
        assert result.get("status") == "initialized"
        assert mgr.game_state.players["player_0"].is_human is True
        assert mgr.game_state.players["player_1"].is_human is False
        assert mgr.game_state.players["player_2"].is_human is False


class TestToolRouterIntegration:
    """Test ToolRouter routes to UniversalGameManager."""

    def test_route_get_game_state(self, chronos_def):
        mgr = UniversalGameManager(chronos_def)
        mgr.initialize_game(player_names=[("P1", True), ("P2", False), ("P3", False)])
        router = ToolRouter(chronos_def, mgr)

        result = router.route("get_game_state", {})
        assert isinstance(result, dict)
        assert "players" in result

    def test_route_set_current_player(self, chronos_def):
        mgr = UniversalGameManager(chronos_def)
        mgr.initialize_game(player_names=[("P1", True), ("P2", False), ("P3", False)])
        router = ToolRouter(chronos_def, mgr)

        result = router.route("set_current_player", {"player_id": "player_0"})
        assert "current_player" in result or result.get("success") is True

    def test_route_unknown_tool(self, chronos_def):
        mgr = UniversalGameManager(chronos_def)
        mgr.initialize_game(player_names=[("P1", True), ("P2", False), ("P3", False)])
        router = ToolRouter(chronos_def, mgr)

        result = router.route("nonexistent", {})
        assert "error" in result


class TestGameDefinitionDiscovery:
    """Test game loader integration."""

    def test_discover_games_returns_list(self):
        games = discover_games()
        assert isinstance(games, list)

    def test_load_chronos_definition(self):
        game_def = load_game_definition("chronos_auction")
        assert game_def is not None
        assert game_def.name != ""

    def test_load_nonexistent_returns_none(self):
        result = load_game_definition("nonexistent_game_xyz")
        assert result is None


class TestServerCreateGameIntegration:
    """Test server create_game with game_definition_name (unit-level mock)."""

    def test_game_create_request_model(self):
        from src.api.server import GameCreateRequest
        req = GameCreateRequest(
            player_name="Alice",
            ai_count=2,
            api_key="test-key",
            game_definition_name="chronos_auction",
        )
        assert req.game_definition_name == "chronos_auction"

    def test_game_create_request_default(self):
        from src.api.server import GameCreateRequest
        req = GameCreateRequest(
            player_name="Alice",
            ai_count=2,
            api_key="test-key",
        )
        assert req.game_definition_name == ""


class TestPromptGeneratorIntegration:
    """Test PromptGenerator produces valid prompt with tools."""

    def test_generate_with_tools(self, chronos_def):
        gen = PromptGenerator()
        tool_gen = ToolGenerator()
        tools = tool_gen.generate(chronos_def)
        prompt = gen.generate(chronos_def, tools)
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert chronos_def.name in prompt

    def test_generate_simple_def(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "Test Game" in prompt
