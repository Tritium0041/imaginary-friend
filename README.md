# Universal Board Game Agent System

通用桌游 Agent 系统 — 支持通过上传规则书（PDF/DOCX/Markdown）自动适配任意桌游，由 AI 驱动的智能游戏体验。

## 功能特性

- 🎲 **文档驱动架构** — 上传规则书即可开玩，无需结构化定义
- 📄 **多格式规则书解析** — 支持 PDF、DOCX、Markdown 格式
- 🗄️ **TinyDB 文档存储** — 灵活的 JSON 文档型状态管理，支持任意桌游数据结构
- 🔧 **6 个固定工具** — GM 通过 CRUD + 交互工具自主管理游戏状态
- ⚡ **Prompt Caching** — 静态规则书缓存，降低 API 成本
- 🎨 **前后端分离** — 纯静态前端 + FastAPI 后端，三栏式游戏界面
- 🏛️ **内置示例游戏** — 上传规则书即可创建新游戏
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
# 启动后选择已有游戏 / 从文件导入新游戏（支持 PDF/DOCX/MD）
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
│   ├── core/              # 核心引擎
│   │   ├── doc_store.py       # TinyDB 文档数据库封装
│   │   ├── tools.py           # 6 个固定工具定义与执行
│   │   └── game_loader.py     # 游戏发现与加载
│   ├── parser/            # 规则书解析
│   │   ├── pdf_extractor.py   # PDF 文本提取 (PyMuPDF)
│   │   ├── docx_extractor.py  # DOCX 文本提取 (python-docx)
│   │   ├── md_extractor.py    # Markdown 文件读取
│   │   ├── document_parser.py # 多格式统一入口
│   │   ├── rule_cleaner.py    # LLM 清洗 + 元数据提取
│   │   └── cache_manager.py   # 两级缓存管理
│   ├── games/             # 游戏实例（上传的游戏存储于此）
│   │   └── {game_id}/
│   │       ├── rules.md       # 完整 Markdown 规则手册
│   │       └── metadata.json  # 极简元数据
│   ├── agents/            # Agent 实现
│   │   └── gm_agent.py       # GM Agent (Prompt Caching)
│   └── api/               # Web API
│       ├── server.py          # FastAPI 后端
│       └── static/            # 前端静态资源
│           ├── common.css     # 共享基础样式
│           ├── play.html      # 游戏页面（三栏布局）
│           ├── play.css       # 游戏页面样式
│           ├── app.js         # 游戏页面逻辑
│           ├── manage.html    # 管理页面
│           ├── manage.css     # 管理页面样式
│           └── manage.js      # 管理页面逻辑
├── cache/                 # 缓存目录
├── tests/                 # 测试
│   └── mock_server/       # 前端可视化测试用 Mock 服务器
├── docs/                  # 设计文档
├── main.py                # 命令行入口
├── run_server.py          # Web 服务入口
└── requirements.txt       # 依赖
```

## 架构

### 核心流程

```
规则书 (PDF/DOCX/MD)
        ↓
  DocumentParser → 原始文本提取
        ↓
  RuleCleaner (2 轮 LLM)
    ├── 第 1 轮: 文本清洗 → rules.md (完整 Markdown 规则手册)
    └── 第 2 轮: 元数据提取 → metadata.json (游戏名、人数等)
        ↓
  GMAgent (rules_md + metadata)
    ├── System Prompt: 角色定义 + 工具规范 + rules.md [缓存]
    ├── DocStore: TinyDB 内存文档库 (global/players/zones/logs)
    └── 6 个固定工具: db_find/insert/update/delete + 交互工具
        ↓
  GM 自主管理游戏全流程
```

### 6 个固定工具

| 工具 | 说明 |
|------|------|
| `db_find` | 查询 DocStore 数据 |
| `db_insert` | 插入文档 |
| `db_update` | 更新文档 (支持 `$set`, `$inc`, `$push`, `$pull`) |
| `db_delete` | 删除文档 |
| `request_player_action` | 请求玩家输入 |
| `broadcast_message` | 广播消息 |

### DocStore 数据表

| 表名 | 说明 |
|------|------|
| `global` | 全局游戏状态（回合数、阶段等） |
| `players` | 玩家数据（资源、手牌、状态等） |
| `zones` | 公共区域（牌池、弃牌堆等） |
| `logs` | 游戏日志（追加写入） |

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/games` | POST | 创建游戏（`game_id` 参数） |
| `/api/games/definitions` | GET | 列出所有可用游戏 |
| `/api/games/definitions/{id}` | GET | 获取游戏规则 |
| `/api/games/definitions/{id}` | DELETE | 删除用户上传的游戏 |
| `/api/games/upload-rules` | POST | 上传规则书 (PDF/DOCX/MD) |
| `/api/games/{game_id}` | GET | 获取游戏状态 (DocStore 快照) |
| `/api/games/{game_id}/action` | POST | 执行游戏行动 |
| `/ws/{game_id}` | WebSocket | 实时游戏通信 |

## 日志与缓存

- **日志**: 默认输出到控制台与 `logs/app.log`，可通过 `LOG_LEVEL`、`LOG_FILE` 环境变量调整
- **缓存**: 两级缓存系统
  - L1: 原始文本缓存（避免重复提取 PDF/DOCX）
  - L2: 清洗后的 rules.md + metadata.json

## 技术栈

- **后端**: Python 3.12 + FastAPI + Claude API (Anthropic SDK)
- **状态存储**: TinyDB (内存模式，JSON 文档型)
- **PDF 解析**: PyMuPDF
- **DOCX 解析**: python-docx
- **前端**: 原生 HTML/CSS/ES Modules
- **通信**: WebSocket 实时流式推送

## 许可证

MIT License
