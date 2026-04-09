"""
GM Agent 实现 - 游戏主控
负责流程推进、规则裁定、状态管理
使用通用引擎: GameDefinition → ToolGenerator/ToolRouter/PromptGenerator → UniversalGameManager
"""
from __future__ import annotations

import json
import logging
import random
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
import anthropic

from ..utils import bind_context


logger = logging.getLogger(__name__)

# 需要 GMAgent 直接拦截的特殊工具（不走 ToolRouter）
_SPECIAL_TOOLS = frozenset({"request_player_action", "ask_human_ruling", "broadcast_message"})

# 通用 AI 性格库 — 不依赖任何特定游戏
_AI_PERSONALITIES = [
    {"name": "策略家", "style": "你深思熟虑，善于制定长期计划，决策果断。"},
    {"name": "冒险家", "style": "你喜欢高风险高回报的决策，直觉敏锐，行动大胆。"},
    {"name": "外交家", "style": "你圆滑得体，善于谈判与交涉，关注每一个交易机会。"},
    {"name": "观察者", "style": "你沉着冷静，善于观察对手行为模式，伺机而动。"},
    {"name": "收藏家", "style": "你对高价值物品情有独钟，愿意为心仪之物出高价。"},
    {"name": "搅局者", "style": "你喜欢出其不意，有时候破坏对手的计划比自己获胜更有趣。"},
    {"name": "均衡者", "style": "你追求稳健平衡的发展策略，不把鸡蛋放在一个篮子里。"},
    {"name": "投机者", "style": "你善于抓住市场波动中的机会，低买高卖是你的信条。"},
]


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
    api_request_count: int = 0
    api_input_tokens: int = 0
    api_output_tokens: int = 0
    api_cache_creation_input_tokens: int = 0
    api_cache_read_input_tokens: int = 0


class GMAgent:
    """GM Agent - 游戏主控（通用引擎）"""
    
    def __init__(
        self, 
        game_definition: Any,
        config: Optional[GMConfig] = None,
        on_output: Optional[Callable[[str | dict[str, Any]], None]] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.config = config or GMConfig()
        self.api_key = api_key
        self.base_url = base_url
        self.game_definition = game_definition
        
        # 创建 Anthropic 客户端
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        
        self.session: Optional[GameSession] = None
        self.on_output = on_output or print
        
        # 通用引擎组件
        from ..core.tool_generator import ToolGenerator
        from ..core.prompt_generator import PromptGenerator
        from ..core.universal_manager import UniversalGameManager

        self.universal_mgr = UniversalGameManager(game_definition)
        self._tool_gen = ToolGenerator()
        self._prompt_gen = PromptGenerator()
        self.tools = self._tool_gen.generate(game_definition)
        self.tool_router: Optional[Any] = None  # 初始化后创建

    def _emit_text(self, text: str):
        """发出普通文本消息。"""
        self.on_output(text)

    def _emit_ai_message(self, player_id: str, player_name: str, message: str):
        """发出带 AI 标签的结构化消息。"""
        payload = {
            "type": "ai_message",
            "player_id": player_id,
            "player_name": player_name,
            "content": message,
        }
        self.on_output(payload)

    def _record_response_usage(self, response: Any):
        """累积 Anthropic usage，供 API 层展示真实上下文消耗。"""
        if self.session is None:
            return
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        def _to_non_negative_int(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        self.session.api_request_count += 1
        self.session.api_input_tokens += _to_non_negative_int(
            getattr(usage, "input_tokens", 0)
        )
        self.session.api_output_tokens += _to_non_negative_int(
            getattr(usage, "output_tokens", 0)
        )
        self.session.api_cache_creation_input_tokens += _to_non_negative_int(
            getattr(usage, "cache_creation_input_tokens", 0)
        )
        self.session.api_cache_read_input_tokens += _to_non_negative_int(
            getattr(usage, "cache_read_input_tokens", 0)
        )
    
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

        # 特殊工具拦截
        if name == "request_player_action":
            result = self._handle_player_action_request(
                args["player_id"],
                args.get("action_type", "general"),
                args.get("context", ""),
            )
        elif name == "ask_human_ruling":
            result = self._handle_human_ruling_request(
                args["question"],
                args.get("options", []),
            )
        elif name == "broadcast_message":
            msg = args.get("message", "")
            self._emit_text(f"\n🎭 【GM播报】{msg}\n")
            if self.tool_router:
                self.tool_router.route("broadcast_message", args)
            result = {"success": True}
        elif self.tool_router:
            result = self.tool_router.route(name, args)
        else:
            result = {"error": f"未知工具: {name}"}

        if isinstance(result, dict) and result.get("error"):
            gm_logger.warning("GM tool failed: %s -> %s", name, result.get("error"))
        else:
            gm_logger.info("GM tool completed: %s", name)
        return result

    def _handle_player_action_request(
        self,
        player_id: str,
        action_type: str,
        context: str,
    ) -> dict:
        """处理玩家行动请求"""
        mgr = self.universal_mgr
        if not mgr or not mgr.game_state:
            return {"error": "游戏尚未初始化"}

        players = mgr.game_state.players
        player = players.get(player_id)
        if not player:
            return {"error": f"玩家 {player_id} 不存在"}

        if player.is_human:
            self.session.is_waiting_for_human = True
            self.session.pending_action = action_type
            self._emit_text(f"\n⏳ 等待 {player.name} 行动: {context}\n")
            return {
                "waiting": True,
                "player_id": player_id,
                "player_name": player.name,
                "action_type": action_type,
                "context": context,
            }
        else:
            agent = self.session.player_agents.get(player_id)
            if agent:
                game_state_dict = mgr.get_game_state()
                response = agent.decide(context, game_state_dict)
                self._emit_ai_message(
                    player_id=player_id,
                    player_name=player.name,
                    message=response["message"],
                )
                return {
                    "player_id": player_id,
                    "player_name": player.name,
                    "action": response.get("action"),
                    "message": response.get("message"),
                }
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
        
        self._emit_text(msg)
        return {"waiting": True, "question": question, "options": options}
    
    def start_game(
        self,
        player_names: list[tuple[str, bool]],
        game_id: Optional[str] = None,
    ) -> str:
        """开始新游戏"""
        gm_logger = bind_context(logger, game_id=game_id)
        gm_logger.info("Starting game session")

        result = self.universal_mgr.initialize_game(
            game_id=game_id,
            player_names=player_names,
        )
        if result.get("error"):
            gm_logger.error("Game initialization failed: %s", result["error"])
            return f"初始化失败: {result['error']}"

        game_id = result["game_id"]

        # ToolRouter 需要在 manager 初始化之后创建
        from ..core.tool_generator import ToolRouter
        self.tool_router = ToolRouter(self.game_definition, self.universal_mgr)

        # 创建会话
        self.session = GameSession(game_id=game_id)
        gm_logger = bind_context(logger, game_id=game_id)
        gm_logger.info("Game session created")

        # 为 AI 玩家创建 Agent
        self._create_ai_agents(player_names)

        # 用 PromptGenerator 生成系统 Prompt
        system_prompt = self._prompt_gen.generate(self.game_definition, self.tools)
        system_prompt += f"\n\n---\n\n## 当前游戏信息\n\n游戏 ID: {game_id}\n玩家列表:\n"
        for i, (name, is_human) in enumerate(player_names):
            player_type = "人类玩家" if is_human else "AI玩家"
            system_prompt += f"- player_{i}: {name} ({player_type})\n"

        self.session.messages = [
            Message(role="system", content=system_prompt)
        ]

        self._emit_text(f"\n🎲 游戏 {game_id} 已创建！（通用引擎 - {self.game_definition.name}）\n")
        gm_logger.info("Game startup announcement sent")

        # 触发 GM 开始游戏
        game_def = self.game_definition
        first_phase = game_def.phases[0].name if game_def.phases else "第一阶段"
        return self.process(
            f"游戏已初始化完成。请开始主持 {game_def.name}：从 {first_phase} 开始。"
        )

    def _create_ai_agents(self, player_names: list[tuple[str, bool]]):
        """为 AI 玩家创建 PlayerAgent"""
        ai_count = sum(1 for _, is_human in player_names if not is_human)
        if ai_count == 0:
            return
        personalities = random.sample(
            _AI_PERSONALITIES,
            min(ai_count, len(_AI_PERSONALITIES)),
        )
        if ai_count > len(personalities):
            personalities = personalities * ((ai_count // len(personalities)) + 1)
        ai_idx = 0
        for i, (name, is_human) in enumerate(player_names):
            if not is_human:
                player_id = f"player_{i}"
                self.session.player_agents[player_id] = PlayerAgent(
                    player_id=player_id,
                    player_name=name,
                    personality=personalities[ai_idx],
                    game_name=self.game_definition.name,
                    model=self.config.model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                ai_idx += 1
    
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
            ""
        )
        
        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system_content,
            tools=self.tools,
            messages=messages_for_api,
        )
        self._record_response_usage(response)
        gm_logger.info("Claude response received (stop_reason=%s)", response.stop_reason)
        
        # 处理响应
        return self._process_response(response)
    
    def _latest_user_text_message(self) -> str:
        if not self.session:
            return ""
        for message in reversed(self.session.messages):
            if message.role != "user":
                continue
            if isinstance(message.content, str):
                return message.content
        return ""

    def _should_enforce_play_function_card_tool_use(
        self,
        content_blocks: list[Any],
        enforcement_attempts: int,
    ) -> bool:
        if enforcement_attempts > 0:
            return False
        latest_user_text = self._latest_user_text_message().strip().lower()
        if not latest_user_text:
            return False
        if any(neg in latest_user_text for neg in ("不使用功能卡", "不用功能卡", "不打出功能卡", "不发动功能卡")):
            return False
        requested_card_play = (
            ("功能卡" in latest_user_text and any(v in latest_user_text for v in ("使用", "打出", "发动")))
            or "play card" in latest_user_text
            or "use card" in latest_user_text
        )
        if not requested_card_play:
            return False
        has_tool_use = any(getattr(block, "type", None) == "tool_use" for block in content_blocks)
        return not has_tool_use

    def _process_response(self, response, enforcement_attempts: int = 0) -> str:
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
                    self._emit_text(block.text)
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
                        if tool_results:
                            self.session.messages.append(
                                Message(role="user", content=tool_results)
                            )
                        return result_text
            
            # 添加助手消息和工具结果
            self.session.messages.append(
                Message(role="assistant", content=assistant_content_serialized)
            )
            if tool_results:
                self.session.messages.append(
                    Message(role="user", content=tool_results)
                )
            
            # 继续对话
            messages_for_api = [
                {"role": m.role, "content": m.content}
                for m in self.session.messages
                if m.role != "system"
            ]
            
            system_content = next(
                (m.content for m in self.session.messages if m.role == "system"),
                ""
            )
            
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_content,
                tools=self.tools,
                messages=messages_for_api,
            )
            self._record_response_usage(response)
            gm_logger.info("Claude follow-up received (stop_reason=%s)", response.stop_reason)
        
        final_content = self._serialize_assistant_content(response.content)
        if self._should_enforce_play_function_card_tool_use(response.content, enforcement_attempts):
            gm_logger.warning("Card play narration without tool_use detected; requesting correction")
            self.session.messages.append(
                Message(role="assistant", content=final_content if final_content else result_text)
            )
            self.session.messages.append(
                Message(
                    role="user",
                    content=(
                        "你刚才在叙述中处理了功能卡，但没有调用 play_function_card 工具。"
                        "请基于当前状态重新回复：若玩家尝试使用功能卡，必须先调用 play_function_card 完成结算；"
                        "禁止仅文字描述用卡结果。"
                    ),
                )
            )
            messages_for_api = [
                {"role": m.role, "content": m.content}
                for m in self.session.messages
                if m.role != "system"
            ]
            system_content = next(
                (m.content for m in self.session.messages if m.role == "system"),
                ""
            )
            followup = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_content,
                tools=self.tools,
                messages=messages_for_api,
            )
            self._record_response_usage(followup)
            gm_logger.info(
                "Claude correction follow-up received (stop_reason=%s)",
                followup.stop_reason,
            )
            return self._process_response(followup, enforcement_attempts=enforcement_attempts + 1)

        # 最终文本响应
        for block in response.content:
            if block.type == "text":
                result_text += block.text
                self._emit_text(block.text)
        
        self.session.messages.append(
            Message(role="assistant", content=final_content if final_content else result_text)
        )
        gm_logger.info("GM response processing completed")
        
        return result_text


class PlayerAgent:
    """玩家 Agent - AI 对手（通用版）"""
    
    def __init__(
        self,
        player_id: str,
        player_name: str,
        personality: dict[str, str],
        game_name: str,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.player_id = player_id
        self.player_name = player_name
        self.personality = personality
        self.game_name = game_name
        self.model = model
        
        # 创建 Anthropic 客户端
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        
        self.memory: list[str] = []
    
    def _build_system_prompt(self) -> str:
        """构建通用 Agent 系统提示"""
        persona = self.personality.get("name", "AI")
        style = self.personality.get("style", "你是一个理性的决策者。")
        return f"""你是《{self.game_name}》桌游中的一名AI玩家。

你的角色是「{persona}」。
{style}

## 行动指南

1. 根据当前游戏状态和你的策略倾向做出决策
2. 你的思考过程不会被其他玩家看到
3. 只输出你的行动决定和想说的话
4. 保持角色人设进行游戏

## 重要规则

- 仔细阅读游戏状态，做出合理的决策
- 注意观察其他玩家的行为模式
- 根据当前资源和局势灵活调整策略
"""

    def _extract_response_text(self, content_blocks: Any) -> str:
        """从 Anthropic blocks 中提取文本，忽略 thinking/tool_use 等非文本块。"""
        if not content_blocks:
            return ""
        texts: list[str] = []
        for block in content_blocks:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text = getattr(block, "text", "")
                if text:
                    texts.append(str(text))
                continue
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    texts.append(str(text))
        return "\n".join(texts).strip()
    
    def decide(self, context: str, game_state: dict) -> dict:
        """做出决策"""
        player_state = game_state.get('players', {}).get(self.player_id, {})
        
        state_summary = "当前游戏状态:\n"
        state_summary += f"- 回合: {game_state.get('current_round', 1)}\n"
        state_summary += f"- 阶段: {game_state.get('current_phase', 'unknown')}\n"

        # 展示玩家资源
        for key, value in player_state.items():
            if key in ('name', 'is_human'):
                continue
            if isinstance(value, (int, float, str, bool)):
                state_summary += f"- 你的{key}: {value}\n"

        # 记忆
        if self.memory:
            recent_memory = self.memory[-5:]
            state_summary += "\n近期记忆:\n"
            for m in recent_memory:
                state_summary += f"  - {m}\n"
        
        prompt = f"""{state_summary}

GM 请求你行动: {context}

请做出你的决策。记住保持你的角色人设。
"""
        
        # 调用 Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            temperature=0.8,
            system=self._build_system_prompt(),
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = self._extract_response_text(getattr(response, "content", []))
        
        # 记录到记忆
        self.memory.append(f"行动: {context} -> {response_text[:100]}...")
        if len(self.memory) > 20:
            self.memory = self.memory[-20:]
        
        # 解析响应
        return self._parse_response(response_text, context)
    
    def _parse_response(self, response: str, context: str) -> dict:
        """解析 Agent 响应"""
        import re
        action = None
        
        response_lower = response.lower()
        
        # 出价
        if "出价" in response or "bid" in response_lower:
            numbers = re.findall(r'\d+', response)
            if numbers:
                action = {"type": "bid", "amount": int(numbers[0])}
        
        # 放弃/跳过
        elif "放弃" in response or "pass" in response_lower or "跳过" in response:
            action = {"type": "pass"}
        
        # 交易提议
        elif "交易" in response or "trade" in response_lower:
            action = {"type": "trade", "proposal": response}
        
        # 出售给系统
        elif "出售" in response or "sell" in response_lower:
            action = {"type": "sell", "proposal": response}
        
        # 功能卡使用
        elif "使用" in response and "卡" in response:
            action = {"type": "use_card", "proposal": response}
        
        return {
            "action": action,
            "message": response,
            "player_id": self.player_id
        }
