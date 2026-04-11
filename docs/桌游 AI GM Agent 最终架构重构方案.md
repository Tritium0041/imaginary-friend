# 桌游 AI GM Agent 最终架构重构方案

本文档定义了 `board_game_agent` 项目从"强类型 Schema 提取"向"文档型状态存储 + 完整规则注入"演进的最终技术决策。所有模块的修改方向均为确定性结论。

## 1. 状态存储层 (State Storage)

**废弃 `ModelGenerator` 和所有动态 Pydantic 模型。**

系统状态管理重构为基于 **TinyDB** 的文档数据库（Document Store）。系统不预设任何游戏特定的字段，仅提供基础的集合（Table）和文档（Document）结构。

### 1.1 核心数据结构
TinyDB 实例固定包含以下四个核心表（Table）：
- `global`: 存储全局变量（如当前回合、当前阶段、公共资源池）。通常只包含一个文档 `{"_id": "global_state", ...}`。
- `players`: 存储玩家实体。每个文档代表一个玩家，包含其私有状态（如金币、手牌、得分、负面状态）。
- `zones`: 存储游戏区域和对象容器（如牌库、弃牌堆、拍卖区、版图格子）。
- `logs`: 存储不可变的结构化游戏日志。

### 1.2 状态隔离与可见性
系统不再通过强类型字段区分公开/私有信息。GM Agent 在查询状态时，系统返回完整 TinyDB 快照；在向前端广播状态时，系统根据 `players` 表中的 `_id` 过滤私有字段（如手牌数组），仅向对应玩家发送完整数据。

## 2. 规则提取层 (Rule Extraction)

**废弃 `LlmExtractor` 的 5 轮结构化提取逻辑。废弃 `GameDefinition` 强类型模型。**

### 2.1 提取目标变更
解析的目标从"提取结构化 JSON"变更为"生成高保真 Markdown 规则手册"。

### 2.2 多格式支持与提取流程
1. **多格式解析**：系统必须支持 **PDF、DOCX、MD** 三种格式的规则书上传。
   - PDF：使用 `PyMuPDF` (fitz) 提取文本。
   - DOCX：使用 `python-docx` 提取文本。
   - MD：直接读取文本内容。
2. **文本清洗**：提取原始文本后，通过单轮 LLM 调用进行排版清洗，修复换行断层，识别并格式化表格和列表。
3. **元数据提取**：通过单轮 LLM 调用提取极简的元数据（游戏名称、玩家人数范围、一句话简介），用于大厅展示。
4. **持久化**：将清洗后的完整 Markdown 文本作为 `rules.md` 缓存，不再截断前 15000 字符。

## 3. 工具层 (Tool Layer)

**废弃 `ToolGenerator`。不再为每种资源和对象生成专属工具（如 `update_gold`, `transfer_card`）。**

系统仅向 GM Agent 暴露 6 个固定工具。

### 3.1 数据库操作工具 (CRUD)
基于 TinyDB 的 API 封装以下工具：
- `db_find(table: str, query: dict)`: 查找符合条件的文档。
- `db_insert(table: str, document: dict)`: 插入新文档。
- `db_update(table: str, query: dict, update: dict)`: 更新文档。必须支持 MongoDB 风格的更新操作符（在 TinyDB 上层封装实现）：
  - `$set`: 设置字段值。
  - `$inc`: 增减数值。
  - `$push`: 向数组追加元素。
  - `$pull`: 从数组移除元素。
- `db_delete(table: str, query: dict)`: 删除文档。

### 3.2 交互工具
- `request_player_action(player_id: str, context: str)`: 挂起 GM 线程，向指定玩家请求行动输入。
- `broadcast_message(message: str)`: 向所有玩家广播文本消息。

## 4. GM Agent 层 (GM Agent) 与 KV Cache 优化

**废弃 `PromptGenerator` 基于 JSON Schema 拼接的提示词。**

为了最大化复用 Anthropic 的 Prompt Caching（KV Cache），降低长文本规则书带来的 Token 成本和延迟，必须对注入策略进行严格的分层设计。Anthropic 的缓存机制要求前缀必须**完全一致**才能命中缓存 [1]。

### 4.1 静态上下文分离与缓存断点 (Cache Breakpoints)
将绝对不会随游戏进程改变的内容放在最前面，并设置明确的缓存断点（`cache_control: {"type": "ephemeral"}`）：

1. **工具定义 (Tools)**：6 个固定工具的 Schema。这是最稳定的前缀。
2. **系统指令 (System Prompt - 静态部分)**：
   - 角色定义与行为准则。
   - 工具使用规范与 `$inc`/`$push` 示例。
   - **完整规则手册 (`rules.md`)**：这是占用 Token 最多的部分，必须保持绝对静态。
   - **【断点 1】**：在此处设置第一个 `cache_control`。这保证了无论游戏进行到哪一步，规则书和工具定义的 KV Cache 都能被 100% 复用。

### 4.2 动态上下文注入策略
游戏状态（TinyDB 快照）是高频变动的，**绝对不能**放在 System Prompt 的静态缓存区内，否则会导致前缀哈希改变，使规则书的缓存全部失效 [1]。

**动态状态注入方案**：
- 废弃在 System Prompt 中拼接 `当前游戏信息` 的做法。
- 将 TinyDB 的最新 JSON 快照作为一条独立的 `User` 消息，或者附加在每次需要 GM 决策的 `User` 消息末尾。
- **【断点 2】（可选）**：如果使用 Anthropic 的自动缓存（Automatic caching），可以在请求的顶层设置 `cache_control`，系统会自动将不断增长的对话历史（Message History）也纳入缓存 [1]。

### 4.3 游戏生命周期控制
- **初始化**：游戏开始时，GM Agent 首次被唤醒，根据规则手册自主调用 `db_insert` 初始化 `global`、`players` 和 `zones` 表（如发初始手牌、设置初始金币）。
- **状态流转**：GM Agent 完全依靠自身对规则的理解，决定何时调用 `db_update` 推进回合，何时调用 `request_player_action` 等待输入。系统不再维护 `current_phase` 的硬编码流转逻辑。

## 5. 前端与接口层 (Frontend & API)

### 5.1 状态下发
WebSocket 广播的状态数据不再是强类型的 `GameState`，而是 TinyDB 的 JSON 树。

### 5.2 动态渲染
前端废弃基于固定字段（如 `gold`, `health`）的硬编码 UI。改为基于 JSON 树的动态渲染：
- 遍历 `players` 表，将所有数值型字段渲染为资源徽章，将所有数组型字段渲染为卡牌/物品列表。
- 遍历 `zones` 表，渲染公共区域。

### 5.3 交互输入
前端向后端发送的行动请求统一为自然语言字符串（如 "我出价 5 金币购买时代令牌"），由 GM Agent 接收并解析，不再使用结构化的 `action_type` 和 `payload`。

---

## References
[1] Anthropic. Prompt caching - Claude API Docs. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
