"""Tests for PromptGenerator"""
import json
import os
import pytest

from src.core.game_definition import GameDefinition
from src.core.prompt_generator import PromptGenerator
from src.core.tool_generator import ToolGenerator


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
        name_en="Test Game EN",
        version="1.0",
        description="A simple test game.",
        player_count_min=2,
        player_count_max=4,
        resources=[
            {"id": "gold", "name": "Gold", "scope": "player", "initial_value": 10},
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
                "id": "card",
                "name": "Card",
                "deck_name": "Card Deck",
                "properties": [
                    {"id": "value", "name": "Value", "type": "integer"},
                ],
            },
        ],
        objects={"card": [{"id": "c1", "name": "Red Card", "properties": {"value": 1}}]},
        zones=[],
        phases=[
            {"id": "setup", "name": "Setup", "actions": ["Initialize game"]},
            {"id": "play", "name": "Play"},
        ],
        victory={"formula": "highest score", "end_conditions": ["end of game"]},
        rules_text="Full rules text here.",
    )


class TestPromptGeneratorBasic:
    def test_generate_returns_string(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_contains_game_name(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "Test Game" in prompt
        assert "Test Game EN" in prompt

    def test_contains_description(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "A simple test game" in prompt

    def test_contains_resources(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "Gold" in prompt
        assert "10" in prompt

    def test_contains_categories(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "Color" in prompt
        assert "Red" in prompt
        assert "Blue" in prompt

    def test_contains_phases(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "Setup" in prompt
        assert "Play" in prompt

    def test_contains_victory(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "highest score" in prompt

    def test_contains_rules_text(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "Full rules text here" in prompt

    def test_contains_tool_guide(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "工具使用指南" in prompt

    def test_with_tools_list(self, simple_def):
        prompt_gen = PromptGenerator()
        tool_gen = ToolGenerator()
        tools = tool_gen.generate(simple_def)
        prompt = prompt_gen.generate(simple_def, tools=tools)
        assert "get_game_state" in prompt
        assert "update_gold" in prompt

    def test_contains_general_guidelines(self, simple_def):
        gen = PromptGenerator()
        prompt = gen.generate(simple_def)
        assert "通用指南" in prompt


class TestChronosPrompt:
    def test_chronos_prompt(self, chronos_def):
        gen = PromptGenerator()
        prompt = gen.generate(chronos_def)
        assert "时空拍卖行" in prompt
        assert "Chronos Auction House" in prompt

    def test_chronos_has_era_section(self, chronos_def):
        gen = PromptGenerator()
        prompt = gen.generate(chronos_def)
        assert "时代" in prompt

    def test_chronos_has_phases(self, chronos_def):
        gen = PromptGenerator()
        prompt = gen.generate(chronos_def)
        assert "游戏阶段" in prompt
        assert "excavation" in prompt or "挖掘" in prompt

    def test_chronos_has_victory(self, chronos_def):
        gen = PromptGenerator()
        prompt = gen.generate(chronos_def)
        assert "胜利条件" in prompt

    def test_chronos_full_with_tools(self, chronos_def):
        prompt_gen = PromptGenerator()
        tool_gen = ToolGenerator()
        tools = tool_gen.generate(chronos_def)
        prompt = prompt_gen.generate(chronos_def, tools=tools)
        assert "update_money" in prompt
        assert "transfer_artifact" in prompt
        assert len(prompt) > 500
