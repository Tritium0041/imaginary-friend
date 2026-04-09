# 《时空拍卖行》桌游 Agent 系统 —— 现有代码架构分析文档

> **文档版本**: v1.0  
> **分支**: `universal`  
> **目的**: 为通用桌游 Agent 系统的设计提供现有代码基础分析

---

## 1. 项目概述

### 1.1 项目定位

本项目是一个 **LLM 驱动的单人桌游 AI 对战系统**，为开源桌游《时空拍卖行》(Chronos Auction House) 实现了完整的 AI 游戏主持（GM）与对手模拟。

**核心设计理念**："代码只做存储，GM 决定一切"。

系统采用 **GM 主控架构**：一个中央 GM Agent 作为"大脑"负责所有流程推进和规则裁定，代码层只提供原子操作工具和数据存储。这意味着游戏逻辑不是硬编码在状态机中，而是通过 LLM 理解规则文本来驱动。

### 1.2 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.11+ | 主语言 |
| Pydantic 2.x | 数据模型验证 |
| Anthropic Claude API | LLM 推理引擎 |
| FastAPI | Web 后端 |
| WebSocket | 实时推送 |
| uvicorn | ASGI 服务器 |
| pytest | 测试框架 |

### 1.3 运行方式

- **命令行模式**: `python main.py` — 交互式终端体验
- **Web 模式**: `python run_server.py` — FastAPI 服务 (http://localhost:8000)

---

## 2. 系统架构

### 2.1 三层架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│  表现层 (Presentation Layer)                                     │
│  ┌─────────────────┐  ┌─────────────────────────────────────┐   │
│  │  CLI (main.py)  │  │  Web (FastAPI + WebSocket)          │   │
│  │  终端交互        │  │  REST API + 实时事件流              │   │
│  └─────────────────┘  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│  Agent 逻辑层 (Agent Logic Layer)                                │
│  ┌────────────────────────┐  ┌────────────────────────────────┐ │
│  │  GM Agent (主控)        │  │  Player Agent (子 Agent)      │ │
│  │  - 流程推进             │  │  - 策略决策                   │ │
│  │  - 规则裁定             │  │  - 自然语言交互               │ │
│  │  - 工具编排             │  │  - 身份与性格系统             │ │
│  │  - Claude API 调用循环  │  │  - 独立 Claude API 调用       │ │
│  └────────────────────────┘  └────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│  状态存储与工具层 (State & Tools Layer)                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  GameManager (全局单例)                                   │   │
│  │  - Pydantic 数据模型 (GameState / PlayerState / ...)     │   │
│  │  - 20+ 原子操作工具                                      │   │
│  │  - 数据验证、日志记录                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  游戏数据 (src/data/)                                     │   │
│  │  - 文物牌库 (36张) / 事件牌库 (24张) / 功能卡库 (24张)   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户输入 (文本)
    │
    ▼
GM Agent.process(user_input)
    │
    ├──► Claude API 调用 (messages + tools)
    │         │
    │         ▼
    │    Claude 返回 (text + tool_use)
    │         │
    │         ├── tool_use → _execute_tool() → GameManager.方法()
    │         │                                     │
    │         │                                     ▼
    │         │                              修改 GameState (内存)
    │         │                                     │
    │         │                              返回工具结果
    │         │                                     │
    │         ├── 继续调用 Claude (携带工具结果) ◄───┘
    │         │
    │         └── stop_reason == "end_turn" → 完成
    │
    ▼
输出消息 (on_output 回调)
    │
    ├── CLI: 直接 print
    └── Web: 通过 event_queue → WebSocket 广播
```

### 2.3 核心实体关系

```
GameManager (全局单例)
  └── GameState
       ├── GlobalState (公共状态)
       │    ├── game_id, current_round, max_rounds
       │    ├── current_phase: GamePhase (9个阶段)
       │    ├── stability: int (0-100%)
       │    ├── era_multipliers: {ancient/modern/future → float}
       │    ├── auction_pool: List[AuctionItem]
       │    │    └── AuctionItem
       │    │         ├── artifact: Artifact
       │    │         ├── auction_type: open/sealed
       │    │         ├── current_highest_bid / bidder
       │    │         └── sealed_bids: Dict[player_id, int]
       │    ├── artifact_deck: List[Artifact]       (文物牌库)
       │    ├── card_deck: List[FunctionCard]        (功能卡库)
       │    ├── event_deck: List[EventCard]          (事件卡库)
       │    ├── system_warehouse: List[Artifact]     (系统仓库)
       │    ├── event_area: List[EventCard]          (当前事件区)
       │    ├── discard_pile / card_discard_pile / event_discard_pile
       │    ├── active_effects: List[str]            (持续性效果)
       │    └── turn_order / current_player_id / start_player_idx
       │
       └── players: Dict[player_id, PlayerState]
            ├── id, name, is_human
            ├── money: int (初始 20)
            ├── victory_points: int
            ├── artifacts: List[Artifact]
            ├── function_cards: List[FunctionCard]
            ├── vote_yes / vote_no: bool
            ├── has_acted: bool
            └── current_bid: Optional[int]
```

---

## 3. 模块详细分析

### 3.1 src/models/ — 数据模型层

#### game_state.py (216 行)

**核心枚举类**：

| 枚举 | 值 | 说明 |
|------|-----|------|
| `Era` | ancient, modern, future | 3 个时代 |
| `GamePhase` | setup, excavation, auction, trading, buyback, event, vote, stabilize, game_over | 9 个游戏阶段 |
| `AuctionType` | open, sealed | 公开拍卖 / 密封竞标 |
| `Rarity` | legendary, rare, common | 稀有度 |

**核心 Pydantic 模型**：

- `Artifact` — 文物：id、name、era、rarity、base_value、time_cost、auction_type、keywords
- `FunctionCard` — 功能卡：id、name、effect、description
- `EventCard` — 事件卡：id、name、effect、description、category
- `PlayerState` — 玩家状态：资金、VP、持有文物/卡牌、投票标记
- `AuctionItem` — 拍卖物品：artifact + 竞拍状态
- `GlobalState` — 全局状态：回合、阶段、稳定性、倍率、各牌库
- `GameState` — 完整状态：global_state + players + action_log

**关键方法**：
- `GameState.get_public_state()` — 返回公开可见部分（密封出价隐藏）
- `GameState.add_log(message)` — 添加带回合号前缀的日志

**耦合分析**：此文件**高度游戏特定**。`Era` 的三个值、`GamePhase` 的九个阶段、`Artifact` 的字段（time_cost、keywords 等）都是《时空拍卖行》独有的。通用化需要将这些模型参数化。

#### identity.py (131 行)

**AI 角色系统**：

- `SpeakingStyle` — 5 种说话风格（aggressive/cautious/smooth/mysterious/friendly）
- `StrategyPreference` — 5 种策略倾向（collector/saboteur/manipulator/opportunist/balanced）
- `AgentIdentity` — 身份模型：name + speaking_style + strategy_preference + preferred_era + description
- `get_system_prompt_addition()` — 生成注入到 Player Agent system prompt 的身份描述文本
- 8 个预设身份（维克托·罗斯柴尔德、艾莉丝·陈 等）

**耦合分析**：性格系统框架（SpeakingStyle/StrategyPreference）**中等通用**，可适用于多种桌游。但预设身份和策略描述文本（如"收集特定时代文物"）是游戏特定的。

### 3.2 src/data/ — 游戏数据层

#### artifacts.py (~100 行)

36 张文物卡，按时代分三组：
- `ANCIENT_ARTIFACTS` (12 张)：王朝玉玺、汉莫拉比法典碑 等
- `MODERN_ARTIFACTS` (12 张)：登月旗帜、瓦特蒸汽机 等
- `FUTURE_ARTIFACTS` (12 张)：戴森球蓝图、反重力核心 等

每张文物卡包含 id、name、era、rarity、time_cost、base_value、auction_type、keywords。

提供 `get_shuffled_artifact_deck()` 返回洗混后的完整牌库。

#### event_cards.py (~180 行)

24 张事件卡，分三类：
- `DISRUPTION_EVENTS` (8 张)：时空震荡、连锁抛售、文物充公 等
- `MULTIPLIER_EVENTS` (8 张)：两极反转、市场崩盘、市场繁荣 等
- `AUCTION_EVENTS` (8 张)：拍卖狂热、暗箱操作、密封强制 等

#### function_cards.py (~180 行)

24 张功能卡，分三类：
- `DISRUPTION_CARDS` (10 张)：赝品指控、拍卖劫持 等
- `MULTIPLIER_CARDS` (7 张)：倍率冲击、倍率固锁 等
- `AUCTION_CARDS` (7 张)：密标窥探、价格锚定 等

**耦合分析**：此模块**完全游戏特定**，是最需要通用化的部分。通用框架需要能从规则书自动生成等价的数据定义。

### 3.3 src/agents/ — Agent 逻辑层

#### gm_agent.py (45 KB, ~800+ 行)

这是系统最核心的文件，实现了 GM Agent 和 Player Agent。

**类结构**：

```python
@dataclass GMConfig       # model, max_tokens, temperature
@dataclass Message         # role, content, name
@dataclass GameSession     # game_id, messages, player_agents, API 使用追踪

class GMAgent:
    # 初始化
    __init__(config, game_mgr, on_output, api_key, base_url)
    
    # 输出
    _emit_text(text)
    _emit_ai_message(player_id, player_name, message)
    
    # API 使用追踪
    _record_response_usage(response)
    
    # 工具定义 (19 个工具)
    _define_tools() → list[dict]
    
    # 核心流程
    start_game(player_names, game_id)   # 初始化游戏
    process(user_input)                 # 处理用户输入
    _process_response(response)         # 响应处理循环
    _execute_tool(name, args)           # 工具执行分派
    
    # Player Agent 交互
    _handle_player_action(player_id, action_type, context)

class PlayerAgent:
    __init__(player_id, identity, gm_agent)
    _build_system_prompt()              # 注入身份信息
    decide(context, game_state)         # 调用 Claude 做决策
```

**工具定义 (19 个)**：

| 类别 | 工具名 | 功能 |
|------|--------|------|
| 状态查询 | `get_game_state` | 获取完整/公开状态 |
| 资产修改 | `update_player_asset` | 修改资金/VP |
| 物品转移 | `transfer_item` | 转移文物/功能卡 |
| 全局更新 | `update_global_status` | 修改稳定性/倍率/阶段/回合 |
| 拍卖区 | `add_artifact_to_pool` | 添加文物到拍卖区 |
| 拍卖区 | `refill_auction_pool` | 补充拍卖区 |
| 卡牌管理 | `draw_function_cards` | 为玩家抽卡 |
| 卡牌管理 | `draw_event_to_area` | 翻事件卡 |
| 事件 | `resolve_event` | 执行事件 |
| 功能卡 | `play_function_card` | 打出功能卡 |
| 密封竞标 | `record_sealed_bid` | 记录出价 |
| 密封竞标 | `reveal_sealed_bids` | 揭示结果 |
| 公开拍卖 | `get_auction_state` | 查询拍卖状态 |
| 公开拍卖 | `update_open_auction_bid` | 更新出价 |
| 公开拍卖 | `finalize_open_auction` | 结算拍卖 |
| 玩家管理 | `set_current_player` | 设置当前玩家 |
| 玩家管理 | `get_players_for_action` | 获取行动列表 |
| 玩家管理 | `request_player_action` | 请求玩家行动 |
| 交易 | `execute_trade` | 执行交易 |
| 交易 | `sell_artifact_to_system` | 出售给系统 |
| 通信 | `broadcast_message` | 广播消息 |
| 裁定 | `ask_human_ruling` | 请求人类裁定 |

**GM 工具调用循环**：

```
process(user_input):
    messages.append({"role": "user", "content": user_input})
    while True:
        response = client.messages.create(messages=..., tools=...)
        _record_response_usage(response)
        
        if response.stop_reason == "end_turn":
            break
            
        if response.stop_reason == "tool_use":
            for tool_call in response.content:
                result = _execute_tool(tool_call.name, tool_call.input)
                messages.append(tool_result)
            continue
```

**耦合分析**：
- **高度耦合**：19 个工具的 JSON Schema 定义、`_execute_tool` 的分派逻辑
- **可复用**：GMAgent 的消息循环框架、PlayerAgent 的身份注入模式、API 使用追踪

#### rules_prompt.md (220 行)

完整的游戏规则书，作为 GM system prompt 的一部分注入。内容包括：

1. 游戏背景与目标
2. 初始设置规则（20 资金、2 功能卡、玩家数+1 文物…）
3. 7 个回合阶段的详细规则
4. 拍卖流程（公开/密封）
5. 时空稳定性机制
6. 套装奖励
7. **GM 必须遵守的强制流程规则**（公开拍卖循环轮询、密封竞标流程、交易阶段轮询…）
8. **工具使用指南**（名称参数约束、功能卡结算强约束…）

**耦合分析**：**完全游戏特定**。通用化时需要从 PDF 自动生成等价的规则 prompt。

### 3.4 src/tools/ — 工具层

#### game_tools.py (84 KB, ~1800+ 行)

`GameManager` 类提供所有原子操作。这是系统中最大的文件。

**核心机制**：

1. **名称参数解析** (`_resolve_named_item`)：
   - 三层匹配：精确名称 → 模糊名称（前缀/后缀） → 拒绝 ID
   - 使用 `_is_disallowed_identifier_reference()` 检测并拒绝 ID 格式
   - 所有涉及物品引用的工具都使用此机制

2. **自动弃牌堆重洗**：
   - `_reshuffle_function_discard_if_needed()` — 功能卡牌库空时自动重洗弃牌堆
   - `_reshuffle_event_discard_if_needed()` — 事件卡同理

3. **事件自动结算** (`_apply_event_effect`)：
   - 24 张事件卡中，部分可自动结算（市场崩盘→所有倍率-0.5、两极反转→交换最高/最低倍率…）
   - 需要手动结算的返回 `manual_resolution_required=True`

4. **功能卡自动结算**：
   - 24 张功能卡中，部分可自动执行（赝品指控→价值-2、倍率冲击→倍率±0.5…）
   - 需要额外参数的返回提示信息

5. **公开拍卖完整流程**：
   - `get_auction_state` → `update_open_auction_bid` → `finalize_open_auction`
   - 结算时自动转移文物、扣除资金、扣减稳定性

6. **交易系统**：
   - `execute_trade` — 原子执行双方物品/资金交换，完整验证
   - `sell_artifact_to_system` — 出售价 = 基础价值 × 时代倍率，危机区-5

**耦合分析**：**高度游戏特定**。事件/功能卡的自动结算逻辑、倍率系统、稳定性机制都是硬编码。但 `_resolve_named_item`、物品转移框架等底层机制可复用。

### 3.5 src/api/ — Web 接口层

#### server.py (~400 行)

**核心类**：

- `GameCreateRequest` — Pydantic 请求模型
- `GameActionRequest` — 行动请求模型
- `GameRuntime` — 游戏运行时上下文（GM + GameManager + event_queue + action_lock）
- `ConnectionManager` — WebSocket 连接池管理

**API 端点**：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/game` | 创建游戏 |
| POST | `/game/{game_id}/action` | 提交玩家行动 |
| GET | `/game/{game_id}/state` | 获取当前状态 |
| WS | `/ws/{game_id}` | 实时事件流 |

**流式事件处理** (`_run_gm_action`)：

```
1. 获取 action_lock（序列化 GM 调用）
2. emit_progress("received", 8%)
3. emit_progress("processing", 30%)
4. asyncio.to_thread(gm.process, action)  — 异步执行 GM
5. 收集 on_output 回调的所有消息
6. emit_progress("streaming", 65%)
7. 构建 state_snapshot（含 context_metrics）
8. emit_progress("completed", 100%)
```

**context_metrics 追踪**：

```python
{
    "message_count": int,
    "estimated_tokens": int,      # 基于字符数估算
    "api_request_count": int,
    "api_input_tokens": int,
    "api_output_tokens": int,
    "api_cache_creation_input_tokens": int,
    "api_cache_read_input_tokens": int,
}
```

**耦合分析**：**低耦合**。Web 层几乎不包含游戏特定逻辑，仅依赖 GMAgent 和 GameManager 的接口。通用化时几乎不需要修改。

### 3.6 src/utils/ — 工具层

#### logging_config.py (~80 行)

- 日志格式：`%(asctime)s | %(levelname)s | %(name)s | game_id=%(game_id)s action_id=%(action_id)s | %(message)s`
- `_ContextDefaultsFilter` — 自动补齐 game_id/action_id 为 "-"
- `bind_context(logger, game_id, action_id)` — 创建上下文绑定的 LoggerAdapter
- `setup_logging(level, log_file)` — 初始化控制台 + 文件日志

**耦合分析**：**完全通用**，无需修改。

---

## 4. 关键交互流程

### 4.1 公开拍卖流程

```
GM: "开始拍卖【王朝玉玺】(公开拍卖)"
    │
    ├── get_auction_state("王朝玉玺")
    │
    ├── 循环轮询 (active_bidders = 所有玩家):
    │   │
    │   ├── request_player_action(player_0, "bid", "当前拍卖【王朝玉玺】...")
    │   │   ├── 人类 → 暂停等待输入 (is_waiting_for_human = True)
    │   │   └── AI → PlayerAgent.decide(context, state)
    │   │
    │   ├── 出价 → update_open_auction_bid("王朝玉玺", player_id, amount)
    │   └── Pass → 从 active_bidders 移除（不可重入）
    │
    ├── 终止: active_bidders ≤ 1
    │
    └── finalize_open_auction("王朝玉玺")
        → 转移文物给赢家、扣资金、扣稳定性
```

### 4.2 密封竞标流程

```
GM: "开始密封竞标【登月旗帜】"
    │
    ├── 依次询问每个玩家:
    │   request_player_action(player_id, "bid", context)
    │   → record_sealed_bid(player_id, "登月旗帜", amount)
    │
    ├── 全部出价完毕
    │
    └── reveal_sealed_bids("登月旗帜")
        → 比较所有出价，平局按行动顺序裁定
        → 扣除赢家资金、转移文物、扣减稳定性
```

### 4.3 功能卡使用流程

```
玩家: "我打出【赝品指控】，指定 AI玩家1 的【王朝玉玺】"
    │
    ├── GM 识别功能卡使用意图
    │
    ├── play_function_card(
    │       player_id="player_0",
    │       card_name="赝品指控",
    │       target_player_id="player_1"
    │   )
    │   ├── 验证玩家持有该卡
    │   ├── 验证目标玩家/文物存在
    │   ├── 执行效果: artifact.base_value -= 2 (最低0)
    │   └── 弃置功能卡到弃牌堆
    │
    └── GM 宣布结果 (broadcast_message)
```

### 4.4 交易流程

```
GM: "交易阶段开始"
    │
    ├── 按行动顺序轮询每个玩家:
    │   request_player_action(player_id, "trade", context)
    │   │
    │   ├── 发起交易:
    │   │   execute_trade(
    │   │       from_player_id, to_player_id,
    │   │       from_offers={money: 5, artifact_names: ["王朝玉玺"]},
    │   │       to_offers={money: 0, artifact_names: ["登月旗帜"]}
    │   │   )
    │   │
    │   ├── 出售给系统:
    │   │   sell_artifact_to_system(player_id, "维京战盾")
    │   │   → 价格 = base_value × era_multiplier (危机区-5)
    │   │
    │   └── 跳过
    │
    └── 所有玩家轮询完毕 → 进入下一阶段
```

---

## 5. 耦合度矩阵

| 组件 | 文件 | 行数 | 游戏耦合度 | 通用化改造难度 | 说明 |
|------|------|------|-----------|--------------|------|
| 数据模型 | models/game_state.py | 216 | 🔴 高 | 中 | 枚举值、字段都游戏特定，需参数化 |
| 身份系统 | models/identity.py | 131 | 🟡 中 | 低 | 框架通用，预设数据游戏特定 |
| 文物数据 | data/artifacts.py | 100 | 🔴 高 | 低 | 完全替换为动态加载 |
| 事件数据 | data/event_cards.py | 180 | 🔴 高 | 低 | 完全替换为动态加载 |
| 功能卡数据 | data/function_cards.py | 180 | 🔴 高 | 低 | 完全替换为动态加载 |
| GM Agent | agents/gm_agent.py | ~800 | 🟡 中 | 高 | 框架通用，工具定义需动态生成 |
| 规则 Prompt | agents/rules_prompt.md | 220 | 🔴 高 | 低 | 完全替换为 PDF 提取内容 |
| 游戏工具 | tools/game_tools.py | ~1800 | 🔴 高 | 高 | 需拆分为通用工具 + 游戏工具 |
| Web API | api/server.py | ~400 | 🟢 低 | 低 | 几乎不需修改 |
| 日志工具 | utils/logging_config.py | ~80 | 🟢 低 | 无 | 完全通用 |
| CLI 入口 | main.py | 148 | 🟡 中 | 低 | 修改游戏选择逻辑即可 |

---

## 6. 设计决策记录

### 6.1 GM 主控 vs 状态机

**选择**：GM 主控（LLM 驱动流程）

**原因**：
- LLM 更擅长理解复杂规则和做出自适应决策
- 避免代码中对所有游戏阶段的硬编码状态转换
- 易于应对规则书未覆盖的边缘情况
- **对通用化极为有利**：只需替换规则 prompt 即可适配新游戏

### 6.2 名称参数强制

**限制**：所有工具禁止使用内部 ID，必须通过名称引用

**原因**：
- 模拟真实游戏中玩家只知道物品名称的场景
- 防止 GM 利用内部 ID "作弊"
- 强制 GM 通过公开信息做决策

### 6.3 功能卡 tool 强制

**限制**：GM 叙述中提到使用功能卡时，必须同时调用 `play_function_card` 工具

**原因**：
- 确保游戏状态与 GM 叙述同步
- 防止 LLM "幻觉"——声称执行了实际上没发生的操作
- 便于后端追踪每一步操作

### 6.4 单例 GameManager

**选择**：模块级单例 `game_manager = GameManager()`

**原因**：
- 简化状态访问，避免传递引用
- CLI 和 Web 模式下共享同一个管理器实例
- 注意：Web 模式下每个游戏有独立的 GameManager 实例

### 6.5 WebSocket 流式推送

**选择**：事件队列 + 异步广播

**原因**：
- 实时体验，避免客户端长时间等待
- 支持多客户端同时观看同一局游戏
- 进度事件让前端可以显示"GM 正在思考..."

---

## 7. 测试覆盖分析

### 7.1 测试文件概览

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| test_cards.py | ~5 | 牌库完整性：数量、ID 唯一性、属性有效性 |
| test_game_tools.py | ~15 | GameManager 核心工具：初始化、资产修改、物品转移、拍卖、交易 |
| test_gm_agent_tooluse.py | ~8 | GM Agent 工具调用集成：工具分派、参数验证、错误处理 |
| test_server_progress.py | ~6 | Web 服务器：进度事件、状态快照、WebSocket 消息 |

**总计**：34 个测试全部通过 (`pytest -q`)

### 7.2 测试覆盖盲区

- 无 Player Agent 决策测试
- 无端到端完整游戏流程测试
- 无事件/功能卡自动结算的单元测试覆盖（部分在集成测试中间接覆盖）
- 无并发/多游戏实例测试

---

## 8. 通用化可行性评估

### 8.1 有利因素

1. **GM 主控架构天然适合通用化**：游戏逻辑在 prompt 中而非代码中，替换 prompt 即可适配新游戏
2. **三层分离清晰**：表现层完全通用，可直接复用
3. **Pydantic 模型易于动态生成**：可通过 `create_model()` 在运行时构建模型
4. **工具定义是 JSON Schema**：可从游戏定义自动生成

### 8.2 挑战

1. **game_tools.py 体量巨大 (84KB)**：自动结算逻辑深度绑定游戏规则，需要重构
2. **工具定义与执行耦合**：工具的 JSON Schema 和实现代码在同一个类中
3. **缺乏游戏定义抽象层**：当前没有"什么是一个游戏"的抽象概念
4. **事件/功能卡效果的形式化**：自然语言描述的效果难以自动转化为代码

### 8.3 推荐改造路径

```
Phase 1: 引入 GameDefinition 抽象层
    ↓
Phase 2: 将硬编码数据抽取为 JSON/YAML 配置
    ↓
Phase 3: 实现 PDF 解析 → GameDefinition 生成
    ↓
Phase 4: 实现通用工具自动生成
    ↓
Phase 5: 缓存与增量更新
```

详细设计方案见 `docs/universal-design.md`。
