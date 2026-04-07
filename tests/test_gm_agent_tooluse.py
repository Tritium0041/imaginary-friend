"""GM tool_use 会话回放测试。"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.agents.gm_agent as gm_agent_mod


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class _FakeResponse:
    stop_reason: str
    content: list
    usage: object | None = None


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


class _FakeMessagesAPI:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No fake responses left")
        return self._responses.pop(0)


class _FakeAnthropicClient:
    def __init__(self, responses: list[_FakeResponse]):
        self.messages = _FakeMessagesAPI(responses)


def _build_agent(monkeypatch, responses: list[_FakeResponse]):
    holder: dict[str, _FakeAnthropicClient] = {}

    class _FakeAnthropic:
        def __init__(self, **_kwargs):
            client = _FakeAnthropicClient(responses)
            holder["client"] = client
            self.messages = client.messages

    monkeypatch.setattr(gm_agent_mod.anthropic, "Anthropic", _FakeAnthropic)
    agent = gm_agent_mod.GMAgent()
    agent.session = gm_agent_mod.GameSession(game_id="game_tu01")
    agent.session.messages = [gm_agent_mod.Message(role="system", content="system prompt")]
    return agent, holder["client"]


def test_waiting_tool_use_message_keeps_structured_content(monkeypatch):
    responses = [
        _FakeResponse(
            stop_reason="tool_use",
            content=[
                _FakeTextBlock("等待玩家行动"),
                _FakeToolUseBlock(
                    id="call_1",
                    name="request_player_action",
                    input={"player_id": "player_0", "action_type": "bid", "context": "竞价"},
                ),
            ],
        ),
        _FakeResponse(
            stop_reason="end_turn",
            content=[_FakeTextBlock("收到玩家行动，继续流程")],
        ),
    ]
    agent, client = _build_agent(monkeypatch, responses)

    def _fake_execute(_name: str, _args: dict):
        agent.session.is_waiting_for_human = True
        agent.session.pending_action = "bid"
        return {"waiting": True}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute)

    first_result = agent.process("开始拍卖")
    assert "等待玩家行动" in first_result
    assert len(client.messages.calls) == 1

    assistant_entry = next(msg for msg in reversed(agent.session.messages) if msg.role == "assistant")
    assert assistant_entry.role == "assistant"
    assert isinstance(assistant_entry.content, list)
    assert assistant_entry.content[1]["type"] == "tool_use"
    assert assistant_entry.content[1]["name"] == "request_player_action"
    tool_result_entry = agent.session.messages[-1]
    assert tool_result_entry.role == "user"
    assert isinstance(tool_result_entry.content, list)
    assert tool_result_entry.content[0]["type"] == "tool_result"

    agent.process("我出价 10")
    assert len(client.messages.calls) == 2
    second_call_messages = client.messages.calls[1]["messages"]
    assistant_payload = next(
        msg["content"] for msg in second_call_messages if msg["role"] == "assistant"
    )
    assert isinstance(assistant_payload, list)
    assert any(block.get("type") == "tool_use" for block in assistant_payload)
    assert "ToolUseBlock(" not in str(assistant_payload)


def test_tool_use_roundtrip_sends_structured_assistant_content(monkeypatch):
    responses = [
        _FakeResponse(
            stop_reason="tool_use",
            content=[
                _FakeTextBlock("调用工具中"),
                _FakeToolUseBlock(
                    id="call_2",
                    name="get_game_state",
                    input={"include_private": True},
                ),
            ],
        ),
        _FakeResponse(
            stop_reason="end_turn",
            content=[_FakeTextBlock("工具执行完毕")],
        ),
    ]
    agent, client = _build_agent(monkeypatch, responses)
    monkeypatch.setattr(agent, "_execute_tool", lambda _name, _args: {"success": True})

    result = agent.process("继续")
    assert "调用工具中" in result
    assert "工具执行完毕" in result
    assert len(client.messages.calls) == 2

    followup_messages = client.messages.calls[1]["messages"]
    assistant_payload = next(
        msg["content"] for msg in followup_messages if msg["role"] == "assistant"
    )
    assert isinstance(assistant_payload, list)
    assert assistant_payload[1]["type"] == "tool_use"
    assert assistant_payload[1]["id"] == "call_2"

    tool_result_payload = followup_messages[-1]
    assert tool_result_payload["role"] == "user"
    assert isinstance(tool_result_payload["content"], list)
    assert tool_result_payload["content"][0]["type"] == "tool_result"


def test_ai_player_action_emits_structured_ai_message(monkeypatch):
    agent, _client = _build_agent(monkeypatch, responses=[])
    outputs: list[object] = []
    agent.on_output = outputs.append

    class _FakePlayer:
        id = "player_1"
        name = "AI玩家1"
        is_human = False

    class _FakePlayerAgent:
        def decide(self, context, _state):
            return {"action": {"type": "pass"}, "message": f"AI 决策: {context}"}

    class _FakeGameMgr:
        def __init__(self):
            self.game_state = self

        def get_player(self, player_id):
            if player_id == "player_1":
                return _FakePlayer()
            return None

        def get_game_state(self):
            return {"players": {}}

    agent.game_mgr = _FakeGameMgr()
    agent.session.player_agents["player_1"] = _FakePlayerAgent()

    result = agent._handle_player_action_request("player_1", "bid", "请出价")
    assert result["player_id"] == "player_1"
    assert any(isinstance(x, dict) and x.get("type") == "ai_message" for x in outputs)
    payload = next(x for x in outputs if isinstance(x, dict) and x.get("type") == "ai_message")
    assert payload["player_name"] == "AI玩家1"
    assert "AI 决策" in payload["content"]


def test_player_agent_decide_tolerates_none_highest_bid(monkeypatch):
    """回归测试：auction_pool 的 current_highest_bid 为 None 时不应崩溃。"""
    monkeypatch.setattr(gm_agent_mod.anthropic, "Anthropic", lambda **_kwargs: object())

    class _Identity:
        @staticmethod
        def get_system_prompt_addition():
            return "测试身份"

    agent = gm_agent_mod.PlayerAgent(
        player_id="player_1",
        identity=_Identity(),
    )

    class _FakeTextBlock:
        type = "text"
        text = "我放弃"

    class _FakeResp:
        content = [_FakeTextBlock()]

    class _FakeMessages:
        @staticmethod
        def create(**_kwargs):
            return _FakeResp()

    class _FakeClient:
        messages = _FakeMessages()

    agent.client = _FakeClient()

    game_state = {
        "current_round": 1,
        "current_phase": "auction",
        "players": {
            "player_1": {"money": 20, "victory_points": 0, "artifacts": [], "function_cards": []},
            "player_2": {"money": 20, "victory_points": 0, "artifacts": [], "function_cards": []},
        },
        "auction_pool": [
            {
                "artifact": {"id": "anc_01", "name": "测试文物", "era": "ancient", "base_value": 10},
                "current_highest_bid": None,
                "current_highest_bidder": None,
            }
        ],
    }

    result = agent.decide("请决定是否出价", game_state)
    assert result["player_id"] == "player_1"
    assert result["action"] == {"type": "pass"}


def test_player_agent_decide_ignores_thinking_block(monkeypatch):
    """回归测试：首个 block 为 thinking 时，decide 不应因 .text 崩溃。"""
    monkeypatch.setattr(gm_agent_mod.anthropic, "Anthropic", lambda **_kwargs: object())

    class _Identity:
        @staticmethod
        def get_system_prompt_addition():
            return "测试身份"

    agent = gm_agent_mod.PlayerAgent(
        player_id="player_1",
        identity=_Identity(),
    )

    class _FakeThinkingBlock:
        type = "thinking"
        thinking = "先分析局势"

    class _FakeResp:
        content = [_FakeThinkingBlock(), _FakeTextBlock("我出价 12 金币")]

    class _FakeMessages:
        @staticmethod
        def create(**_kwargs):
            return _FakeResp()

    class _FakeClient:
        messages = _FakeMessages()

    agent.client = _FakeClient()
    game_state = {
        "current_round": 1,
        "current_phase": "auction",
        "players": {
            "player_1": {"money": 20, "victory_points": 0, "artifacts": [], "function_cards": []},
            "player_2": {"money": 20, "victory_points": 0, "artifacts": [], "function_cards": []},
        },
        "auction_pool": [],
    }

    result = agent.decide("请决定是否出价", game_state)
    assert result["player_id"] == "player_1"
    assert result["message"] == "我出价 12 金币"
    assert result["action"] == {"type": "bid", "amount": 12}


def test_usage_is_accumulated_across_tool_use_roundtrip(monkeypatch):
    responses = [
        _FakeResponse(
            stop_reason="tool_use",
            content=[
                _FakeTextBlock("调用工具中"),
                _FakeToolUseBlock(
                    id="call_3",
                    name="get_game_state",
                    input={"include_private": True},
                ),
            ],
            usage=_FakeUsage(
                input_tokens=120,
                output_tokens=24,
                cache_creation_input_tokens=40,
                cache_read_input_tokens=10,
            ),
        ),
        _FakeResponse(
            stop_reason="end_turn",
            content=[_FakeTextBlock("完成")],
            usage=_FakeUsage(
                input_tokens=80,
                output_tokens=16,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=8,
            ),
        ),
    ]
    agent, _client = _build_agent(monkeypatch, responses)
    monkeypatch.setattr(agent, "_execute_tool", lambda _name, _args: {"success": True})

    agent.process("继续")
    assert agent.session is not None
    assert agent.session.api_request_count == 2
    assert agent.session.api_input_tokens == 200
    assert agent.session.api_output_tokens == 40
    assert agent.session.api_cache_creation_input_tokens == 40
    assert agent.session.api_cache_read_input_tokens == 18
