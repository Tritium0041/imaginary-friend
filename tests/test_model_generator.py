"""Tests for ModelGenerator"""
import json
import os
import pytest

from src.core.game_definition import GameDefinition
from src.core.model_generator import ModelGenerator


@pytest.fixture
def game_def():
    path = os.path.join(
        os.path.dirname(__file__),
        "..", "src", "games", "chronos_auction", "definition.json",
    )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return GameDefinition(**data)


@pytest.fixture
def simple_game_def():
    """最小的 GameDefinition 用于隔离测试"""
    return GameDefinition(
        id="test_game",
        name="Test Game",
        version="1.0",
        player_count_min=2,
        player_count_max=4,
        resources=[
            {"id": "gold", "name": "Gold", "scope": "player", "initial_value": 10},
            {"id": "market_pool", "name": "Market Pool", "scope": "global", "initial_value": 100},
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
                    {"id": "color", "name": "Color", "type": "category_ref", "category_ref": "color"},
                ],
            },
        ],
        objects={
            "card": [
                {"id": "c1", "name": "Red One", "properties": {"value": 1, "color": "red"}},
                {"id": "c2", "name": "Blue Two", "properties": {"value": 2, "color": "blue"}},
                {"id": "c3", "name": "Red Three", "properties": {"value": 3, "color": "red"}},
            ],
        },
        zones=[],
        phases=[
            {"id": "setup", "name": "Setup"},
            {"id": "play", "name": "Play"},
        ],
        victory={"formula": "highest total wins", "end_conditions": ["game ends"]},
    )


class TestModelGeneratorBasic:
    def test_generate_returns_dict(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        assert isinstance(models, dict)

    def test_enum_created(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        assert "color_enum" in models
        enum_cls = models["color_enum"]
        assert hasattr(enum_cls, "RED")
        assert hasattr(enum_cls, "BLUE")

    def test_object_model_created(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        assert "card" in models
        card_cls = models["card"]
        instance = card_cls(id="c1", name="Test", value=5, color="red")
        assert instance.name == "Test"
        assert instance.value == 5

    def test_player_state_has_resources(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        ps_cls = models["player_state"]
        player = ps_cls(id="p1", name="Alice")
        assert player.gold == 10
        assert hasattr(player, "cards")

    def test_global_state_has_resources(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        gs_cls = models["global_state"]
        gs = gs_cls(game_id="test")
        assert gs.market_pool == 100
        assert hasattr(gs, "color_multipliers")

    def test_global_state_multipliers_default(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        gs_cls = models["global_state"]
        gs = gs_cls(game_id="test")
        assert gs.color_multipliers == {"red": 1.0, "blue": 1.0}

    def test_global_state_has_deck_fields(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        gs_cls = models["global_state"]
        gs = gs_cls(game_id="test")
        assert hasattr(gs, "card_deck")
        assert hasattr(gs, "card_discard_pile")

    def test_game_state_created(self, simple_game_def):
        gen = ModelGenerator()
        models = gen.generate(simple_game_def)
        assert "game_state" in models
        gs_cls = models["global_state"]
        ps_cls = models["player_state"]
        game_cls = models["game_state"]
        game = game_cls(
            global_state=gs_cls(game_id="test"),
            players={"p1": ps_cls(id="p1", name="Alice")},
        )
        assert game.global_state.game_id == "test"
        assert "p1" in game.players


class TestChronosModels:
    def test_chronos_generates_all_expected_keys(self, game_def):
        gen = ModelGenerator()
        models = gen.generate(game_def)
        assert "era_enum" in models
        assert "artifact" in models
        assert "function_card" in models
        assert "event_card" in models
        assert "player_state" in models
        assert "global_state" in models
        assert "game_state" in models

    def test_chronos_era_enum(self, game_def):
        gen = ModelGenerator()
        models = gen.generate(game_def)
        era = models["era_enum"]
        assert hasattr(era, "ANCIENT")
        assert hasattr(era, "MODERN")
        assert hasattr(era, "FUTURE")

    def test_chronos_artifact_model(self, game_def):
        gen = ModelGenerator()
        models = gen.generate(game_def)
        artifact_cls = models["artifact"]
        art = artifact_cls(
            id="a1", name="Test Artifact",
            era="ancient", base_value=100, description="test"
        )
        assert art.era == "ancient"
        assert art.base_value == 100

    def test_chronos_player_state_resources(self, game_def):
        gen = ModelGenerator()
        models = gen.generate(game_def)
        ps_cls = models["player_state"]
        player = ps_cls(id="p1", name="Test")
        assert player.money == 20
        assert hasattr(player, "artifacts")
        assert hasattr(player, "function_cards")

    def test_chronos_global_state_multipliers(self, game_def):
        gen = ModelGenerator()
        models = gen.generate(game_def)
        gs_cls = models["global_state"]
        gs = gs_cls(game_id="test")
        assert "ancient" in gs.era_multipliers
        assert gs.era_multipliers["ancient"] == 1.0
