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

    assistant_entry = agent.session.messages[-1]
    assert assistant_entry.role == "assistant"
    assert isinstance(assistant_entry.content, list)
    assert assistant_entry.content[1]["type"] == "tool_use"
    assert assistant_entry.content[1]["name"] == "request_player_action"

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
