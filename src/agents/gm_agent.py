"""
GM Agent 实现 - 游戏主控
负责流程推进、规则裁定、状态管理

新架构: DocStore(TinyDB) + 7 固定工具 + Markdown 规则注入 + Prompt Caching
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
import anthropic

from ..utils import bind_context
from ..core.doc_store import DocStore
from ..core.tools import ToolExecutor, get_tool_schemas


logger = logging.getLogger(__name__)

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

# GM 系统指令（静态部分 — 进入 Prompt Cache）
_GM_SYSTEM_INSTRUCTIONS = """\
# 角色定义

你是一位专业的桌游 AI Game Master (GM)。你的职责是：
1. 严格按照规则手册主持游戏
2. 使用数据库工具管理游戏状态
3. 在合适的时机向玩家请求行动
4. 公正地裁定规则争议
5. 用生动的语言描述游戏进程

# 工具使用规范

你只有 7 个工具可以使用：

## 数据库操作工具
- **db_find**: 查询游戏状态。始终先查询再修改。
- **db_insert**: 插入新文档（初始化玩家、区域等）。
- **db_update**: 更新文档。使用 MongoDB 风格操作符：
  - `$set`: 设置字段值 → `{"$set": {"current_phase": "bidding"}}`
  - `$inc`: 数值增减 → `{"$inc": {"gold": -5, "score": 2}}`
  - `$push`: 数组追加 → `{"$push": {"hand": {"name": "Card A"}}}`
  - `$pull`: 数组移除 → `{"$pull": {"hand": {"name": "Card A"}}}`
  - 可组合多个操作符 → `{"$inc": {"gold": -3}, "$push": {"items": {"name": "X"}}}`
- **db_delete**: 删除文档（谨慎使用）。
- **db_shuffle**: 随机打乱指定文档中某个数组字段的元素顺序。用于洗牌、随机化顺序等。
  - 示例: `db_shuffle(table="zones", query={"_id": "deck"}, field="cards")`

## 数据库表结构
- **global**: 全局状态（回合数、阶段、公共资源池等）。建议用 `_id: "global_state"` 的单文档。
- **players**: 玩家实体（每人一个文档，`_id` 为 player_id）。包含资源、手牌、得分等。
- **zones**: 游戏区域和容器（牌库、弃牌堆、拍卖区等）。
- **logs**: 不可变的游戏日志。

## 交互工具
- **request_player_action**: 向指定玩家请求行动。提供清晰的上下文描述。
- **broadcast_message**: 向所有玩家广播消息。

# 行为准则

1. **查询优先**: 修改状态前，先用 db_find 查询当前状态。
2. **原子操作**: 每次只修改一个文档，确保一致性。
3. **日志记录**: 重要操作后，用 db_insert 写入 logs 表。
4. **公平公正**: 严格按规则执行，不偏袒任何玩家。
5. **叙事丰富**: 用生动的语言描述游戏进程，营造沉浸感。

# 游戏生命周期

1. **初始化**: 收到开始指令后，根据规则手册自主调用 db_insert 初始化所有表。
2. **主循环**: 推进游戏阶段，在需要时请求玩家行动。
3. **结算**: 游戏结束时，计算最终得分并宣布结果。
"""


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
    name: Optional[str] = None


@dataclass
class GameSession:
    """游戏会话"""
    game_id: str
    gm_config: GMConfig = field(default_factory=GMConfig)
    messages: list[Message] = field(default_factory=list)
    player_agents: dict[str, "PlayerAgent"] = field(default_factory=dict)
    player_info: dict[str, dict[str, Any]] = field(default_factory=dict)
    is_waiting_for_human: bool = False
    pending_action: Optional[str] = None
    api_request_count: int = 0
    api_input_tokens: int = 0
    api_output_tokens: int = 0
    api_cache_creation_input_tokens: int = 0
    api_cache_read_input_tokens: int = 0


class GMAgent:
    """
    GM Agent - 游戏主控

    新架构：DocStore + 6 固定工具 + Markdown 规则 + Prompt Caching
    """

    def __init__(
        self,
        rules_md: str,
        metadata: dict[str, Any],
        config: Optional[GMConfig] = None,
        on_output: Optional[Callable[[str | dict[str, Any]], None]] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.config = config or GMConfig()
        self.api_key = api_key
        self.base_url = base_url
        self.rules_md = rules_md
        self.metadata = metadata
        self.game_name = metadata.get("game_name", "Unknown Game")

        # Anthropic 客户端
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)

        # DocStore 和工具执行器
        self.doc_store = DocStore()
        self.tool_executor = ToolExecutor(self.doc_store)
        self.tools = get_tool_schemas()

        self.session: Optional[GameSession] = None
        self.on_output = on_output or print

    # ------------------------------------------------------------------
    # System Prompt — 静态分层设计（Prompt Caching）
    # ------------------------------------------------------------------

    def _build_system_messages(self) -> list[dict[str, Any]]:
        """
        构建分层 System Prompt，优化 Anthropic KV Cache：
        1. 静态指令（角色 + 工具规范）
        2. 完整规则手册（最大 Token 占用，设 cache_control 断点）
        """
        return [
            {
                "type": "text",
                "text": _GM_SYSTEM_INSTRUCTIONS,
            },
            {
                "type": "text",
                "text": f"# 游戏规则手册\n\n{self.rules_md}",
                "cache_control": {"type": "ephemeral"},
            },
        ]

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _emit_text(self, text: str):
        self.on_output(text)

    def _emit_ai_message(self, player_id: str, player_name: str, message: str):
        payload = {
            "type": "ai_message",
            "player_id": player_id,
            "player_name": player_name,
            "content": message,
        }
        self.on_output(payload)

    # ------------------------------------------------------------------
    # API usage tracking
    # ------------------------------------------------------------------

    def _record_response_usage(self, response: Any):
        if self.session is None:
            return
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        def _int(v: Any) -> int:
            try:
                return max(0, int(v or 0))
            except (TypeError, ValueError):
                return 0

        self.session.api_request_count += 1
        self.session.api_input_tokens += _int(getattr(usage, "input_tokens", 0))
        self.session.api_output_tokens += _int(getattr(usage, "output_tokens", 0))
        self.session.api_cache_creation_input_tokens += _int(
            getattr(usage, "cache_creation_input_tokens", 0)
        )
        self.session.api_cache_read_input_tokens += _int(
            getattr(usage, "cache_read_input_tokens", 0)
        )

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _serialize_assistant_content(self, content_blocks: list[Any]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for block in content_blocks:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                serialized.append({"type": "text", "text": getattr(block, "text", "")})
                continue
            if block_type == "tool_use":
                serialized.append({
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}),
                })
                continue
            if hasattr(block, "model_dump"):
                serialized.append(block.model_dump())
                continue
            if isinstance(block, dict):
                serialized.append(block)
                continue
            serialized.append({"type": "text", "text": str(block)})
        return serialized

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, args: dict) -> Any:
        game_id = self.session.game_id if self.session else None
        gm_logger = bind_context(logger, game_id=game_id)
        gm_logger.info("Executing tool: %s", name)

        if name == "request_player_action":
            result = self._handle_player_action_request(
                args["player_id"],
                args.get("context", ""),
            )
        elif name == "broadcast_message":
            msg = args.get("message", "")
            self._emit_text(f"\n🎭 【GM播报】{msg}\n")
            result = self.tool_executor.execute(name, args)
        else:
            result = self.tool_executor.execute(name, args)

        if isinstance(result, dict) and result.get("error"):
            gm_logger.warning("Tool failed: %s -> %s", name, result.get("error"))
        else:
            gm_logger.info("Tool completed: %s", name)
        return result

    def _handle_player_action_request(self, player_id: str, context: str) -> dict:
        """处理玩家行动请求"""
        player_info = self.session.player_info.get(player_id, {})
        player_name = player_info.get("name", player_id)
        is_human = player_info.get("is_human", False)

        if is_human:
            self.session.is_waiting_for_human = True
            self.session.pending_action = "action"
            self._emit_text(f"\n⏳ 等待 {player_name} 行动: {context}\n")
            return {
                "waiting": True,
                "player_id": player_id,
                "player_name": player_name,
                "context": context,
            }
        else:
            agent = self.session.player_agents.get(player_id)
            if agent:
                state_snapshot = self.doc_store.snapshot()
                response = agent.decide(context, state_snapshot)
                self._emit_ai_message(
                    player_id=player_id,
                    player_name=player_name,
                    message=response["message"],
                )
                return {
                    "player_id": player_id,
                    "player_name": player_name,
                    "action": response.get("action"),
                    "message": response.get("message"),
                }
            return {"error": f"未找到玩家 {player_id} 的 Agent"}

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def start_game(
        self,
        player_names: list[tuple[str, bool]],
        game_id: Optional[str] = None,
    ) -> str:
        """开始新游戏 — GM 自主初始化状态"""
        game_id = game_id or str(uuid.uuid4())[:8]
        gm_logger = bind_context(logger, game_id=game_id)
        gm_logger.info("Starting game session")

        # 创建会话
        self.session = GameSession(game_id=game_id)

        # 记录玩家信息
        for i, (name, is_human) in enumerate(player_names):
            pid = f"player_{i}"
            self.session.player_info[pid] = {
                "name": name,
                "is_human": is_human,
            }

        # 为 AI 玩家创建 Agent
        self._create_ai_agents(player_names)

        # 准备 system prompt（静态，缓存友好）
        system_messages = self._build_system_messages()
        self.session.messages = [
            Message(role="system", content=system_messages)
        ]

        self._emit_text(f"\n🎲 游戏 {game_id} 已创建！（{self.game_name}）\n")
        gm_logger.info("Game session created")

        # 构建初始化指令
        player_list = "\n".join(
            f"- {f'player_{i}'}: {name} ({'人类玩家' if is_human else 'AI玩家'})"
            for i, (name, is_human) in enumerate(player_names)
        )
        init_prompt = (
            f"游戏 ID: {game_id}\n"
            f"玩家列表:\n{player_list}\n\n"
            f"请根据规则手册初始化游戏：\n"
            f"1. 用 db_insert 初始化 global 表（回合、阶段、公共资源等）\n"
            f"2. 用 db_insert 为每个玩家创建 players 文档（初始资源、手牌等）\n"
            f"3. 用 db_insert 初始化 zones 表（牌库、区域等）\n"
            f"4. 初始化完成后，开始主持第一个阶段。"
        )
        return self.process(init_prompt)

    def _create_ai_agents(self, player_names: list[tuple[str, bool]]):
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
                    game_name=self.game_name,
                    model=self.config.model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                ai_idx += 1

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    def process(self, user_input: str) -> str:
        """处理用户输入并推进游戏"""
        if not self.session:
            return "游戏尚未开始，请先调用 start_game()"
        gm_logger = bind_context(logger, game_id=self.session.game_id)
        gm_logger.info("Processing GM input")

        if self.session.is_waiting_for_human:
            self.session.is_waiting_for_human = False
            self.session.pending_action = None

        # 动态状态注入：在 user 消息中附加 DocStore 快照
        state_snapshot = self.doc_store.snapshot()
        enriched_input = (
            f"{user_input}\n\n"
            f"---\n当前游戏状态快照:\n"
            f"```json\n{json.dumps(state_snapshot, ensure_ascii=False, indent=2)}\n```"
        )

        self.session.messages.append(Message(role="user", content=enriched_input))

        # 构建 API 请求
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

        return self._process_response(response)

    def _process_response(self, response) -> str:
        result_text = ""
        game_id = self.session.game_id if self.session else None
        gm_logger = bind_context(logger, game_id=game_id)

        while response.stop_reason == "tool_use":
            tool_results = []
            assistant_content = response.content
            assistant_content_serialized = self._serialize_assistant_content(assistant_content)

            for block in assistant_content:
                if block.type == "text":
                    result_text += block.text
                    self._emit_text(block.text)
                elif block.type == "tool_use":
                    tool_result = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })

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

            self.session.messages.append(
                Message(role="assistant", content=assistant_content_serialized)
            )
            if tool_results:
                self.session.messages.append(
                    Message(role="user", content=tool_results)
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

        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)

        self.memory: list[str] = []

    def _build_system_prompt(self) -> str:
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
        """做出决策 — 接收 DocStore 快照"""
        # 从快照中提取当前玩家状态
        players = game_state.get("players", [])
        player_state = {}
        for p in players:
            if p.get("_id") == self.player_id:
                player_state = p
                break

        global_state = game_state.get("global", [{}])
        if global_state:
            global_state = global_state[0] if isinstance(global_state, list) else global_state

        state_summary = "当前游戏状态:\n"
        state_summary += f"- 全局: {json.dumps(global_state, ensure_ascii=False)}\n"

        for key, value in player_state.items():
            if key in ("_id", "name", "is_human"):
                continue
            if isinstance(value, (int, float, str, bool)):
                state_summary += f"- 你的{key}: {value}\n"
            elif isinstance(value, list):
                state_summary += f"- 你的{key}: {len(value)} 项\n"

        if self.memory:
            recent = self.memory[-5:]
            state_summary += "\n近期记忆:\n"
            for m in recent:
                state_summary += f"  - {m}\n"

        prompt = f"{state_summary}\nGM 请求你行动: {context}\n\n请做出你的决策。记住保持你的角色人设。\n"

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            temperature=0.8,
            system=self._build_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = self._extract_response_text(getattr(response, "content", []))

        self.memory.append(f"行动: {context} -> {response_text[:100]}...")
        if len(self.memory) > 20:
            self.memory = self.memory[-20:]

        return self._parse_response(response_text, context)

    def _parse_response(self, response: str, context: str) -> dict:
        import re
        action = None
        response_lower = response.lower()

        if "出价" in response or "bid" in response_lower:
            numbers = re.findall(r'\d+', response)
            if numbers:
                action = {"type": "bid", "amount": int(numbers[0])}
        elif "放弃" in response or "pass" in response_lower or "跳过" in response:
            action = {"type": "pass"}
        elif "交易" in response or "trade" in response_lower:
            action = {"type": "trade", "proposal": response}
        elif "出售" in response or "sell" in response_lower:
            action = {"type": "sell", "proposal": response}
        elif "使用" in response and "卡" in response:
            action = {"type": "use_card", "proposal": response}

        return {
            "action": action,
            "message": response,
            "player_id": self.player_id,
        }
