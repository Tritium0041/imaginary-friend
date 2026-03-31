"""
GM Agent 实现 - 游戏主控
负责流程推进、规则裁定、状态管理
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
import anthropic

from ..tools.game_tools import game_manager, GameManager
from ..models import GamePhase, get_random_identities
from ..utils import bind_context


# 加载规则 Prompt
RULES_PROMPT_PATH = Path(__file__).parent / "rules_prompt.md"
RULES_PROMPT = RULES_PROMPT_PATH.read_text(encoding="utf-8") if RULES_PROMPT_PATH.exists() else ""
logger = logging.getLogger(__name__)


@dataclass
class GMConfig:
    """GM 配置"""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class Message:
    """消息"""
    role: str  # "user", "assistant", "system"
    content: str | list[dict[str, Any]]
    name: Optional[str] = None  # 发言者名称


@dataclass 
class GameSession:
    """游戏会话"""
    game_id: str
    gm_config: GMConfig = field(default_factory=GMConfig)
    messages: list[Message] = field(default_factory=list)
    player_agents: dict[str, "PlayerAgent"] = field(default_factory=dict)
    is_waiting_for_human: bool = False
    pending_action: Optional[str] = None


class GMAgent:
    """GM Agent - 游戏主控"""
    
    def __init__(
        self, 
        config: Optional[GMConfig] = None,
        game_mgr: Optional[GameManager] = None,
        on_output: Optional[Callable[[str], None]] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.config = config or GMConfig()
        self.game_mgr = game_mgr or game_manager
        self.api_key = api_key
        self.base_url = base_url
        
        # 创建 Anthropic 客户端
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        
        self.session: Optional[GameSession] = None
        self.on_output = on_output or print
        
        # 工具定义
        self.tools = self._define_tools()
    
    def _define_tools(self) -> list[dict]:
        """定义 GM 可用的工具"""
        return [
            {
                "name": "get_game_state",
                "description": "获取当前游戏状态，包括回合数、阶段、玩家资产、拍卖区物品等",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "include_private": {
                            "type": "boolean",
                            "description": "是否包含私有信息（如玩家手牌）",
                            "default": True
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "update_player_asset",
                "description": "修改玩家的资金或胜利点数",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {"type": "string", "description": "玩家ID"},
                        "money_delta": {"type": "integer", "description": "资金变化量"},
                        "vp_delta": {"type": "integer", "description": "VP变化量"}
                    },
                    "required": ["player_id"]
                }
            },
            {
                "name": "transfer_item",
                "description": "转移文物或功能卡",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "item_type": {"type": "string", "enum": ["artifact", "card"]},
                        "item_id": {"type": "string"},
                        "from_location": {"type": "string"},
                        "to_location": {"type": "string"}
                    },
                    "required": ["item_type", "item_id", "from_location", "to_location"]
                }
            },
            {
                "name": "update_global_status",
                "description": "更新全局游戏状态（稳定性、倍率、阶段、回合）",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stability_delta": {"type": "integer"},
                        "era_multiplier_changes": {
                            "type": "object",
                            "description": "时代倍率变化，如 {\"ancient\": 0.1}"
                        },
                        "new_phase": {
                            "type": "string",
                            "enum": [
                                "setup",
                                "excavation",
                                "auction",
                                "trading",
                                "buyback",
                                "event",
                                "vote",
                                "stabilize",
                                "game_over"
                            ]
                        },
                        "next_round": {"type": "boolean"}
                    },
                    "required": []
                }
            },
            {
                "name": "add_artifact_to_pool",
                "description": "向拍卖区添加文物",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "name": {"type": "string"},
                        "era": {"type": "string", "enum": ["ancient", "modern", "future"]},
                        "base_value": {"type": "integer"},
                        "auction_type": {"type": "string", "enum": ["open", "sealed"]},
                        "description": {"type": "string"}
                    },
                    "required": ["artifact_id", "name", "era", "base_value"]
                }
            },
            {
                "name": "draw_function_cards",
                "description": "为指定玩家抽取功能卡",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {"type": "string"},
                        "count": {"type": "integer", "default": 1}
                    },
                    "required": ["player_id"]
                }
            },
            {
                "name": "refill_auction_pool",
                "description": "补充拍卖区文物到目标数量",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "target_size": {"type": "integer"},
                        "extra_slots": {"type": "integer", "default": 0}
                    },
                    "required": []
                }
            },
            {
                "name": "draw_event_to_area",
                "description": "翻开一张事件卡到事件区",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "max_area_size": {"type": "integer", "default": 2}
                    },
                    "required": []
                }
            },
            {
                "name": "resolve_event",
                "description": "执行事件区中的事件并结算效果",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "refill_area": {"type": "boolean", "default": True}
                    },
                    "required": ["event_id"]
                }
            },
            {
                "name": "play_function_card",
                "description": "玩家打出功能卡并执行效果",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {"type": "string"},
                        "card_id": {"type": "string"},
                        "target_player_id": {"type": "string"},
                        "target_era": {"type": "string", "enum": ["ancient", "modern", "future"]},
                        "secondary_era": {"type": "string", "enum": ["ancient", "modern", "future"]},
                        "multiplier_delta": {"type": "number", "default": 0.5}
                    },
                    "required": ["player_id", "card_id"]
                }
            },
            {
                "name": "record_sealed_bid",
                "description": "记录密封竞标出价",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {"type": "string"},
                        "auction_item_id": {"type": "string"},
                        "bid_amount": {"type": "integer"}
                    },
                    "required": ["player_id", "auction_item_id", "bid_amount"]
                }
            },
            {
                "name": "reveal_sealed_bids",
                "description": "揭示密封竞标结果",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "auction_item_id": {"type": "string"}
                    },
                    "required": ["auction_item_id"]
                }
            },
            {
                "name": "set_current_player",
                "description": "设置当前行动玩家",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {"type": "string"}
                    },
                    "required": ["player_id"]
                }
            },
            {
                "name": "request_player_action",
                "description": "请求玩家执行行动。对于人类玩家会暂停等待输入，对于AI玩家会调用其决策。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_id": {"type": "string"},
                        "action_type": {
                            "type": "string",
                            "enum": ["bid", "pass", "trade", "play_card", "choose"]
                        },
                        "context": {"type": "string", "description": "行动上下文描述"}
                    },
                    "required": ["player_id", "action_type", "context"]
                }
            },
            {
                "name": "ask_human_ruling",
                "description": "向人类玩家请求规则裁定",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["question"]
                }
            },
            {
                "name": "broadcast_message",
                "description": "向所有玩家广播消息（游戏播报）",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"}
                    },
                    "required": ["message"]
                }
            }
        ]

    def _serialize_assistant_content(self, content_blocks: list[Any]) -> list[dict[str, Any]]:
        """将 SDK block 序列化为 Anthropic messages 可回放格式。"""
        serialized: list[dict[str, Any]] = []
        for block in content_blocks:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                serialized.append(
                    {
                        "type": "text",
                        "text": getattr(block, "text", ""),
                    }
                )
                continue
            if block_type == "tool_use":
                serialized.append(
                    {
                        "type": "tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    }
                )
                continue

            if hasattr(block, "model_dump"):
                serialized.append(block.model_dump())  # type: ignore[call-arg]
                continue
            if isinstance(block, dict):
                serialized.append(block)
                continue
            serialized.append({"type": "text", "text": str(block)})
        return serialized
    
    def _execute_tool(self, name: str, args: dict) -> Any:
        """执行工具调用"""
        game_id = self.session.game_id if self.session else None
        gm_logger = bind_context(logger, game_id=game_id)
        gm_logger.info("Executing GM tool: %s", name)
        if name == "get_game_state":
            result = self.game_mgr.get_game_state(args.get("include_private", True))
        elif name == "update_player_asset":
            result = self.game_mgr.update_player_asset(
                args["player_id"],
                args.get("money_delta", 0),
                args.get("vp_delta", 0)
            )
        elif name == "transfer_item":
            result = self.game_mgr.transfer_item(
                args["item_type"],
                args["item_id"],
                args["from_location"],
                args["to_location"]
            )
        elif name == "update_global_status":
            result = self.game_mgr.update_global_status(
                args.get("stability_delta", 0),
                args.get("era_multiplier_changes"),
                args.get("new_phase"),
                args.get("next_round", False)
            )
        elif name == "add_artifact_to_pool":
            result = self.game_mgr.add_artifact_to_pool(
                args["artifact_id"],
                args["name"],
                args["era"],
                args["base_value"],
                args.get("auction_type", "open"),
                args.get("description", "")
            )
        elif name == "draw_function_cards":
            result = self.game_mgr.draw_function_cards(
                args["player_id"],
                args.get("count", 1),
            )
        elif name == "refill_auction_pool":
            result = self.game_mgr.refill_auction_pool(
                args.get("target_size"),
                args.get("extra_slots", 0),
            )
        elif name == "draw_event_to_area":
            result = self.game_mgr.draw_event_to_area(
                args.get("max_area_size", 2),
            )
        elif name == "resolve_event":
            result = self.game_mgr.resolve_event(
                args["event_id"],
                args.get("refill_area", True),
            )
        elif name == "play_function_card":
            result = self.game_mgr.play_function_card(
                args["player_id"],
                args["card_id"],
                args.get("target_player_id"),
                args.get("target_era"),
                args.get("secondary_era"),
                args.get("multiplier_delta", 0.5),
            )
        elif name == "record_sealed_bid":
            result = self.game_mgr.record_sealed_bid(
                args["player_id"],
                args["auction_item_id"],
                args["bid_amount"]
            )
        elif name == "reveal_sealed_bids":
            result = self.game_mgr.reveal_sealed_bids(args["auction_item_id"])
        elif name == "set_current_player":
            result = self.game_mgr.set_current_player(args["player_id"])
        elif name == "request_player_action":
            result = self._handle_player_action_request(
                args["player_id"],
                args["action_type"],
                args["context"]
            )
        elif name == "ask_human_ruling":
            result = self._handle_human_ruling_request(
                args["question"],
                args.get("options", [])
            )
        elif name == "broadcast_message":
            self.on_output(f"\n🎭 【GM播报】{args['message']}\n")
            result = {"success": True}
        else:
            result = {"error": f"未知工具: {name}"}

        if isinstance(result, dict) and result.get("error"):
            gm_logger.warning(
                "GM tool failed: %s -> %s",
                name,
                result.get("error"),
            )
        else:
            gm_logger.info("GM tool completed: %s", name)
        return result
    
    def _handle_player_action_request(
        self, 
        player_id: str, 
        action_type: str, 
        context: str
    ) -> dict:
        """处理玩家行动请求"""
        player = self.game_mgr.game_state.get_player(player_id)
        if not player:
            return {"error": f"玩家 {player_id} 不存在"}
        
        if player.is_human:
            # 人类玩家：设置等待状态
            self.session.is_waiting_for_human = True
            self.session.pending_action = action_type
            self.on_output(f"\n⏳ 等待 {player.name} 行动: {context}\n")
            return {
                "waiting": True,
                "player_id": player_id,
                "player_name": player.name,
                "action_type": action_type,
                "context": context
            }
        else:
            # AI 玩家：调用 Player Agent
            agent = self.session.player_agents.get(player_id)
            if agent:
                response = agent.decide(context, self.game_mgr.get_game_state())
                self.on_output(f"\n🤖 {player.name}: {response['message']}\n")
                return {
                    "player_id": player_id,
                    "player_name": player.name,
                    "action": response.get("action"),
                    "message": response.get("message")
                }
            else:
                return {"error": f"未找到玩家 {player_id} 的 Agent"}
    
    def _handle_human_ruling_request(self, question: str, options: list[str]) -> dict:
        """处理规则裁定请求"""
        self.session.is_waiting_for_human = True
        self.session.pending_action = "ruling"
        
        msg = f"\n⚠️ 【规则裁定请求】\n{question}\n"
        if options:
            msg += "选项:\n"
            for i, opt in enumerate(options, 1):
                msg += f"  {i}. {opt}\n"
        
        self.on_output(msg)
        return {"waiting": True, "question": question, "options": options}
    
    def start_game(
        self,
        player_names: list[tuple[str, bool]],
        game_id: Optional[str] = None,
    ) -> str:
        """开始新游戏"""
        gm_logger = bind_context(logger, game_id=game_id)
        gm_logger.info("Starting game session")
        # 初始化游戏状态
        result = self.game_mgr.initialize_game(
            game_id=game_id,
            player_names=player_names,
        )

        if not result.get("success"):
            gm_logger.error("Game initialization failed: %s", result.get("error"))
            return f"初始化失败: {result.get('error')}"
        
        game_id = result["game_id"]
        
        # 创建会话
        self.session = GameSession(game_id=game_id)
        gm_logger = bind_context(logger, game_id=game_id)
        gm_logger.info("Game session created")
        
        # 为 AI 玩家创建 Agent
        ai_count = sum(1 for _, is_human in player_names if not is_human)
        if ai_count > 0:
            identities = get_random_identities(ai_count)
            ai_idx = 0
            for i, (name, is_human) in enumerate(player_names):
                if not is_human:
                    player_id = f"player_{i}"
                    self.session.player_agents[player_id] = PlayerAgent(
                        player_id=player_id,
                        identity=identities[ai_idx],
                        model=self.config.model,
                        api_key=self.api_key,
                        base_url=self.base_url,
                    )
                    ai_idx += 1
            gm_logger.info("Initialized AI player agents: %s", ai_count)
        
        # 构建系统提示
        system_prompt = f"""{RULES_PROMPT}

---

## 当前游戏信息

游戏 ID: {game_id}
玩家列表:
"""
        for i, (name, is_human) in enumerate(player_names):
            player_type = "人类玩家" if is_human else "AI玩家"
            system_prompt += f"- player_{i}: {name} ({player_type})\n"
        
        # 初始消息
        self.session.messages = [
            Message(role="system", content=system_prompt)
        ]
        
        self.on_output(f"\n🎲 游戏 {game_id} 已创建！\n")
        gm_logger.info("Game startup announcement sent")
        
        # 触发 GM 开始游戏
        return self.process(
            "游戏已初始化完成（含初始功能卡发放、拍卖区和事件区准备）。"
            "请开始主持游戏：从挖掘阶段开始，先检查拍卖区是否需要补到玩家数+1件，再进入拍卖阶段。"
        )
    
    def process(self, user_input: str) -> str:
        """处理用户输入并推进游戏"""
        if not self.session:
            return "游戏尚未开始，请先调用 start_game()"
        gm_logger = bind_context(logger, game_id=self.session.game_id)
        gm_logger.info("Processing GM input")
        
        # 如果正在等待人类输入
        if self.session.is_waiting_for_human:
            self.session.is_waiting_for_human = False
            self.session.pending_action = None
        
        # 添加用户消息
        self.session.messages.append(Message(role="user", content=user_input))
        
        # 调用 Claude
        messages_for_api = [
            {"role": m.role, "content": m.content}
            for m in self.session.messages
            if m.role != "system"
        ]
        
        system_content = next(
            (m.content for m in self.session.messages if m.role == "system"),
            RULES_PROMPT
        )
        
        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system_content,
            tools=self.tools,
            messages=messages_for_api,
        )
        gm_logger.info("Claude response received (stop_reason=%s)", response.stop_reason)
        
        # 处理响应
        return self._process_response(response)
    
    def _process_response(self, response) -> str:
        """处理 API 响应"""
        result_text = ""
        game_id = self.session.game_id if self.session else None
        gm_logger = bind_context(logger, game_id=game_id)
        
        while response.stop_reason == "tool_use":
            # 处理工具调用
            tool_results = []
            assistant_content = response.content
            assistant_content_serialized = self._serialize_assistant_content(assistant_content)
            
            for block in assistant_content:
                if block.type == "text":
                    result_text += block.text
                    self.on_output(block.text)
                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id
                    
                    # 执行工具
                    tool_result = self._execute_tool(tool_name, tool_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(tool_result, ensure_ascii=False)
                    })
                    
                    # 如果需要等待人类输入，暂停循环
                    if isinstance(tool_result, dict) and tool_result.get("waiting"):
                        gm_logger.info("GM waiting for human input")
                        self.session.messages.append(
                            Message(role="assistant", content=assistant_content_serialized)
                        )
                        return result_text
            
            # 添加助手消息和工具结果
            self.session.messages.append(
                Message(role="assistant", content=assistant_content_serialized)
            )
            
            # 继续对话
            messages_for_api = [
                {"role": m.role, "content": m.content}
                for m in self.session.messages
                if m.role != "system"
            ]
            messages_for_api.append({"role": "user", "content": tool_results})
            
            system_content = next(
                (m.content for m in self.session.messages if m.role == "system"),
                RULES_PROMPT
            )
            
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_content,
                tools=self.tools,
                messages=messages_for_api,
            )
            gm_logger.info("Claude follow-up received (stop_reason=%s)", response.stop_reason)
        
        # 最终文本响应
        for block in response.content:
            if block.type == "text":
                result_text += block.text
                self.on_output(block.text)
        
        final_content = self._serialize_assistant_content(response.content)
        self.session.messages.append(
            Message(role="assistant", content=final_content if final_content else result_text)
        )
        gm_logger.info("GM response processing completed")
        
        return result_text


class PlayerAgent:
    """玩家 Agent - AI 对手"""
    
    def __init__(
        self,
        player_id: str,
        identity: Any,  # AgentIdentity
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.player_id = player_id
        self.identity = identity
        self.model = model
        
        # 创建 Anthropic 客户端
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        
        self.memory: list[str] = []  # 简单的局内记忆
    
    def _build_system_prompt(self) -> str:
        """构建 Agent 系统提示"""
        return f"""你是《时空拍卖行》桌游中的一名AI玩家。

{self.identity.get_system_prompt_addition()}

## 行动指南

1. 根据当前游戏状态和你的策略倾向做出决策
2. 你的思考过程不会被其他玩家看到
3. 只输出你的行动决定和想说的话
4. 行动格式示例:
   - 出价: "我出价 25 金币"
   - 放弃: "我放弃竞拍"
   - 交易提议: "我想用 20 金币换你的那件远古花瓶"

## 重要规则

- 出价不能超过你的资金
- 根据文物价值和时代倍率评估是否值得购买
- 注意观察其他玩家的行为模式
"""
    
    def decide(self, context: str, game_state: dict) -> dict:
        """做出决策"""
        # 构建提示
        state_summary = f"""
当前游戏状态:
- 回合: {game_state.get('current_round', 1)}
- 阶段: {game_state.get('current_phase', 'unknown')}
- 你的资金: {game_state.get('players', {}).get(self.player_id, {}).get('money', 0)}
- 你的VP: {game_state.get('players', {}).get(self.player_id, {}).get('victory_points', 0)}
"""
        
        if game_state.get('auction_pool'):
            state_summary += "\n拍卖区物品:\n"
            for item in game_state['auction_pool']:
                artifact = item.get('artifact', {})
                state_summary += f"  - {artifact.get('name', '未知')} ({artifact.get('era', '?')}): 基础价值 {artifact.get('base_value', 0)}\n"
        
        prompt = f"""{state_summary}

GM 请求你行动: {context}

请做出你的决策。记住保持你的角色人设。"""
        
        # 调用 Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            temperature=0.8,
            system=self._build_system_prompt(),
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = response.content[0].text if response.content else ""
        
        # 记录到记忆
        self.memory.append(f"行动: {context} -> {response_text}")
        if len(self.memory) > 20:
            self.memory = self.memory[-20:]
        
        # 解析响应
        return self._parse_response(response_text, context)
    
    def _parse_response(self, response: str, context: str) -> dict:
        """解析 Agent 响应"""
        action = None
        
        # 简单的关键词匹配
        response_lower = response.lower()
        if "出价" in response or "bid" in response_lower:
            # 尝试提取数字
            import re
            numbers = re.findall(r'\d+', response)
            if numbers:
                action = {"type": "bid", "amount": int(numbers[0])}
        elif "放弃" in response or "pass" in response_lower:
            action = {"type": "pass"}
        elif "交易" in response or "trade" in response_lower:
            action = {"type": "trade", "proposal": response}
        
        return {
            "action": action,
            "message": response,
            "player_id": self.player_id
        }
