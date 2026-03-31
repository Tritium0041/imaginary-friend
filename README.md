# 时空拍卖行 (Chronos Auction House)

一个由 AI 驱动的单人桌游体验系统。

## 功能特性

- 🎮 单人对战 2-4 个 AI 对手
- 🤖 AI 由 Claude 大语言模型驱动
- 🎭 GM Agent 自动主持游戏流程
- 💬 自然语言交互
- 🔒 密封竞标机制

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 设置 API Key

```bash
export ANTHROPIC_API_KEY=your-api-key
```

### 3. 运行游戏

**命令行模式:**
```bash
python main.py
```

**Web 模式:**
```bash
python run_server.py
# 访问 http://localhost:8000/play
```

## 日志与进度条

- 日志：
  - 默认同时输出到控制台与 `logs/app.log`
  - 可通过环境变量调整：
    - `LOG_LEVEL`（默认 `INFO`）
    - `LOG_FILE`（默认 `logs/app.log`）

- Web 端加载进度条（仅游戏内异步流程）：
  - 创建游戏（`/api/games`）
  - 执行动作（WebSocket / HTTP fallback）
  - WebSocket 断线重连

## 项目结构

```
board_game_agent/
├── src/
│   ├── models/          # 数据模型
│   │   ├── game_state.py   # 游戏状态
│   │   └── identity.py     # Agent 身份库
│   ├── tools/           # MCP 工具
│   │   └── game_tools.py   # 游戏操作
│   ├── agents/          # Agent 实现
│   │   ├── gm_agent.py     # GM Agent
│   │   └── rules_prompt.md # 规则提示
│   └── api/             # Web API
│       └── server.py       # FastAPI 服务
├── tests/               # 测试
├── main.py              # 命令行入口
├── run_server.py        # Web 服务入口
└── requirements.txt     # 依赖
```

## 游戏规则

### 游戏目标
获得最高胜利点数 (VP)。

### 游戏流程
1. **初始化** - 加载文物/功能/事件牌库；每位玩家发 2 张功能卡；翻开 2 张事件卡
2. **挖掘阶段** - 抽取文物进入拍卖区（补到玩家数+1；稳定性警告区会额外补1）
3. **拍卖阶段** - 竞拍文物
4. **交易阶段** - 玩家间交易
5. **回购拍卖阶段** - 偶数回合或系统仓库触发
6. **事件阶段** - 事件区事件结算并补牌
7. **投票阶段** - 倍率提议与投票
8. **稳定阶段** - 稳定性修复与危机处理
9. **回合推进** - 每 3 回合所有玩家自动抽 1 张功能卡

### 拍卖类型
- **公开拍卖**: 依次出价，最高者得
- **密封竞标**: 同时秘密出价，揭示后最高者得

## 技术架构

- **后端**: Python + FastAPI + Claude API
- **前端**: 原生 HTML/CSS/ES Modules（工程化拆分到 `src/api/static/`）
- **通信**: WebSocket 实时流式推送（GM 消息分片渲染 + HTTP 降级）
- **状态管理**: 内存字典

## 开发计划

- [x] 阶段一: 状态存储与基础工具
- [x] 阶段二: GM Agent 核心循环
- [x] 阶段三: Player Agent 接入
- [x] 阶段四: Web UI 开发

## 许可证

MIT License
