# Universal Board Game Agent System

通用桌游 Agent 系统 — 支持通过上传规则书 PDF 自动适配任意桌游，由 AI 驱动的智能游戏体验。

## 功能特性

- 🎲 **通用桌游引擎** — 通过 GameDefinition 描述任意桌游，自动生成工具集和 GM Prompt
- 📄 **PDF 规则书解析** — 上传桌游规则书 PDF，AI 自动提取结构化游戏定义
- 🏛️ **内置示例游戏** — 《时空拍卖行》作为 GameDefinition 范例，演示引擎能力
- 🎮 单人对战 2-4 个 AI 对手
- 🤖 GM Agent 由 Claude 大语言模型驱动
- 💬 自然语言交互
- 🌐 Web + CLI 双模式

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
# 启动后选择已导入的游戏 / 从 PDF 导入新游戏
```

**Web 模式:**
```bash
python run_server.py
# 访问 http://localhost:8000/play
```

## 项目结构

```
board_game_agent/
├── src/
│   ├── core/              # 通用引擎核心
│   │   ├── game_definition.py  # GameDefinition 数据模型
│   │   ├── universal_manager.py # 通用 GameManager
│   │   ├── model_generator.py   # 动态 Pydantic 模型生成
│   │   ├── tool_generator.py    # 工具 Schema 自动生成
│   │   ├── prompt_generator.py  # GM Prompt 自动生成
│   │   └── game_loader.py       # 游戏加载与发现
│   ├── parser/            # PDF 规则书解析
│   │   ├── pdf_extractor.py     # PDF 文本提取
│   │   ├── llm_extractor.py     # LLM 结构化提取
│   │   └── cache_manager.py     # 三级缓存管理
│   ├── games/             # 游戏实例
│   │   └── chronos_auction/     # 内置示例游戏
│   │       ├── definition.json  # GameDefinition 数据
│   │       └── adapter.py       # 可选适配器（引擎不依赖）
│   ├── models/            # 原版数据模型（向后兼容）
│   ├── tools/             # 原版工具（向后兼容）
│   ├── agents/            # Agent 实现
│   │   ├── gm_agent.py         # GM Agent
│   │   └── rules_prompt.md     # 规则提示
│   └── api/               # Web API
│       └── server.py           # FastAPI 服务
├── cache/                 # 缓存目录
├── tests/                 # 测试
├── docs/                  # 设计文档
├── main.py                # 命令行入口
├── run_server.py          # Web 服务入口
└── requirements.txt       # 依赖
```

## 通用引擎架构

### 核心流程

```
PDF 规则书 → PdfExtractor → LlmExtractor → GameDefinition
                                                  ↓
                                          ModelGenerator → 动态 Pydantic 模型
                                          ToolGenerator  → Claude 工具 Schema
                                          PromptGenerator → GM 系统 Prompt
                                                  ↓
                                      UniversalGameManager（原子操作引擎）
                                                  ↓
                                           GM Agent（LLM 驱动决策）
```

### GameDefinition

GameDefinition 是整个框架的核心数据结构，描述一个桌游的完整规则：

- **资源系统** (resources) — 金币、胜利点、生命值等
- **分类系统** (categories) — 文物时代、卡牌类型等
- **游戏对象** (object_types) — 卡牌、棋子、骰子等
- **区域定义** (zones) — 公共牌池、弃牌堆等
- **阶段流程** (phases) — 回合结构与阶段顺序
- **胜利条件** (victory) — 计分公式与终局条件

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/games` | POST | 创建游戏（支持 `game_definition_name` 参数） |
| `/api/games/definitions` | GET | 列出所有可用 GameDefinition |
| `/api/games/definitions/{id}` | GET | 获取指定 GameDefinition |
| `/api/games/definitions/{id}` | PUT | 更新（微调）GameDefinition |
| `/api/games/upload-rules` | POST | 上传 PDF 规则书，解析为 GameDefinition |
| `/api/games/{game_id}` | GET | 获取游戏状态 |
| `/api/games/{game_id}/action` | POST | 执行游戏行动 |
| `/ws/{game_id}` | WebSocket | 实时游戏通信 |

## 日志与缓存

- **日志**: 默认输出到控制台与 `logs/app.log`，可通过 `LOG_LEVEL`、`LOG_FILE` 环境变量调整
- **缓存**: 三级缓存系统
  - L1: PDF 文本缓存 (避免重复提取)
  - L2: GameDefinition 缓存 (避免重复 LLM 调用)
  - L3: 生成产物缓存 (工具 Schema + Prompt)

## 技术栈

- **后端**: Python 3.12 + FastAPI + Claude API (Anthropic SDK)
- **数据模型**: Pydantic v2 (含动态模型生成)
- **PDF 解析**: PyMuPDF
- **前端**: 原生 HTML/CSS/ES Modules
- **通信**: WebSocket 实时流式推送

## 许可证

MIT License
