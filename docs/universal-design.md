# 通用桌游 Agent 系统设计方案

> **文档版本**: v1.0  
> **分支**: `universal`  
> **前置文档**: `docs/architecture-analysis.md`

---

## 1. 设计目标

### 1.1 核心目标

构建一个**通用桌游 Agent 框架**，用户只需上传桌游规则书 PDF，系统即可：

1. **自动解析**规则书，提取游戏结构化定义
2. **自动生成**适配该游戏的状态管理器、工具集和 GM Prompt
3. **缓存**生成结果，支持增量更新和人工微调
4. 最终提供一个可玩的 AI 驱动桌游体验

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **规则驱动** | 游戏逻辑来自规则文本，而非硬编码 |
| **渐进增强** | PDF 自动解析为主，人工微调为辅 |
| **向后兼容** | 现有《时空拍卖行》应作为通用框架的一个"游戏实例" |
| **分层解耦** | 核心引擎 / 游戏定义 / 适配层 / 接口层 严格分离 |
| **可缓存** | 规则解析和代码生成的结果可持久化，避免重复消耗 |

---

## 2. 分层架构设计

### 2.1 四层架构

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: 接口层 (Interface Layer)                                │
│  ┌───────────┐  ┌───────────┐  ┌──────────────────────────┐    │
│  │  CLI      │  │  Web API  │  │  规则微调 UI              │    │
│  │  main.py  │  │  FastAPI  │  │  (查看/编辑 GameDefinition)│    │
│  └───────────┘  └───────────┘  └──────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Agent 层 (Agent Layer)                                  │
│  ┌────────────────────────┐  ┌────────────────────────────────┐ │
│  │  GM Agent (通用)        │  │  Player Agent (通用)          │ │
│  │  - 接收 GameDefinition │  │  - 接收角色定义               │ │
│  │  - 动态工具集          │  │  - 策略注入                   │ │
│  │  - 规则 Prompt 注入    │  │  - 自然语言交互               │ │
│  └────────────────────────┘  └────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: 游戏定义层 (Game Definition Layer)                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  GameDefinition                                          │   │
│  │  - 元信息 (名称、简介、玩家数范围)                        │   │
│  │  - 资源类型定义 (货币、积分、卡牌类型...)                 │   │
│  │  - 游戏对象定义 (卡牌、Token、棋盘...)                    │   │
│  │  - 阶段与流程定义 (Phase Graph)                           │   │
│  │  - 规则文本 (用于 GM Prompt 注入)                         │   │
│  │  - 工具集定义 (需要的工具 Schema)                         │   │
│  │  - 胜利条件定义                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────┐  ┌────────────────────────────────┐   │
│  │  PDF 解析器          │  │  GameDefinition 缓存           │   │
│  │  (规则书 → 定义)     │  │  (.json / .yaml)               │   │
│  └──────────────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: 核心引擎层 (Core Engine Layer)                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  UniversalGameManager                                    │   │
│  │  - 通用状态存储 (动态 Pydantic 模型)                     │   │
│  │  - 通用原子工具 (转移、修改、查询、抽牌...)              │   │
│  │  - 名称解析引擎 (_resolve_named_item)                    │   │
│  │  - 事件循环与日志                                        │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 层间依赖关系

```
接口层 → Agent 层 → 游戏定义层 → 核心引擎层
  │                      │
  └──────────────────────┘ (接口层直接读取 GameDefinition 用于展示/编辑)
```

每一层只依赖其下层，不可反向依赖。

---

## 3. 核心概念：GameDefinition

### 3.1 GameDefinition Schema

`GameDefinition` 是整个通用框架的中心数据结构，描述"一个桌游是什么"。

```yaml
# 示例：将《时空拍卖行》表示为 GameDefinition

game:
  name: "时空拍卖行"
  name_en: "Chronos Auction House"
  description: "穿梭于各个平行宇宙的古董商在拍卖会上竞拍稀世珍宝"
  player_count:
    min: 3
    max: 5
  version: "1.0"

# ---- 资源系统 ----
resources:
  - id: money
    name: "资金"
    icon: "💰"
    initial_value: 20
    min_value: 0
    max_value: null
    
  - id: victory_points
    name: "胜利点数"
    icon: "🏆"
    initial_value: 0
    min_value: 0
    
  - id: stability
    name: "时空稳定性"
    icon: "⏳"
    scope: global          # global = 全局共享，player = 每个玩家独立
    initial_value: 100
    min_value: 0
    max_value: 100

# ---- 分类系统 ----
categories:
  - id: era
    name: "时代"
    values:
      - { id: ancient, name: "古代", icon: "🟡" }
      - { id: modern, name: "近代", icon: "🔵" }
      - { id: future, name: "未来", icon: "🟣" }
    has_multiplier: true
    multiplier_range: [0.5, 2.5]
    initial_multiplier: 1.0

  - id: rarity
    name: "稀有度"
    values:
      - { id: legendary, name: "传奇", icon: "★" }
      - { id: rare, name: "稀有", icon: "●" }
      - { id: common, name: "常见", icon: "○" }

# ---- 游戏对象类型 ----
object_types:
  - id: artifact
    name: "文物"
    properties:
      - { id: era, type: category_ref, category: era }
      - { id: rarity, type: category_ref, category: rarity }
      - { id: base_value, type: integer, min: 0 }
      - { id: time_cost, type: integer }
      - { id: auction_type, type: enum, values: [open, sealed] }
      - { id: keywords, type: string_list }
    deck_name: "文物牌库"
    
  - id: function_card
    name: "功能卡"
    properties:
      - { id: effect, type: text }
      - { id: category, type: enum, values: [disruption, multiplier, auction] }
    deck_name: "功能卡库"
    hand_limit: null       # 无上限
    
  - id: event_card
    name: "事件卡"
    properties:
      - { id: effect, type: text }
      - { id: category, type: enum, values: [disruption, multiplier, auction] }
    area_name: "事件区"
    area_size: 2

# ---- 公共区域 ----
zones:
  - id: auction_pool
    name: "拍卖区"
    object_type: artifact
    auto_refill:
      source: artifact_deck
      target_size: "player_count + 1"
      extra_condition: "stability < 30 → +1"
      
  - id: system_warehouse
    name: "系统仓库"
    object_type: artifact
    
  - id: discard_pile
    name: "弃牌堆"
    object_type: artifact

# ---- 阶段定义 ----
phases:
  - id: setup
    name: "初始化"
    auto: true             # 系统自动执行
    
  - id: excavation
    name: "挖掘阶段"
    actions:
      - refill_auction_pool
      - "每3回合抽1张功能卡"
    
  - id: auction
    name: "拍卖阶段"
    actions:
      - "对拍卖区每件文物进行拍卖（公开或密封）"
    player_interaction: sequential_polling   # 需要依次询问玩家
    
  - id: trading
    name: "交易阶段"
    actions:
      - "玩家间自由交易"
      - "可出售文物给系统"
    player_interaction: sequential_polling
    
  - id: buyback
    name: "回购拍卖阶段"
    trigger_condition: "偶数回合 或 system_warehouse.count >= 6"
    
  - id: event
    name: "事件阶段"
    actions:
      - "对事件区事件投票"
      - "执行得票最高的事件"
    
  - id: vote
    name: "投票阶段"
    actions:
      - "起始玩家发起倍率调整提议"
      - "所有玩家投票"
    
  - id: stabilize
    name: "稳定阶段"
    actions:
      - "玩家可弃卡或捐资金修复稳定性"
    player_interaction: sequential_polling

phase_order: [excavation, auction, trading, buyback, event, vote, stabilize]

# ---- 胜利条件 ----
victory:
  formula: "sum(artifact.base_value * era_multiplier[artifact.era]) + (money / 10) + set_bonus"
  end_conditions:
    - "artifact_deck 为空且拍卖结束"
    - "stability == 0"
  set_bonuses:
    - { name: "时空博学家", condition: "拥有3个不同时代各至少1件文物", bonus: 5 }
    - { name: "时代专精者", condition: "同一时代3件文物", bonus: 5 }
    - { name: "关键词收集者", condition: "同一关键词3件文物", bonus: 5 }

# ---- 特殊机制 ----
special_mechanics:
  - id: sealed_auction
    name: "密封竞标"
    description: "所有玩家同时秘密出价，最高出价者获胜"
    
  - id: open_auction  
    name: "公开拍卖"
    description: "依次出价，pass不可重入，最高出价者获胜"

# ---- 规则全文 ----
rules_text: |
  （从 PDF 提取的完整规则文本，用于注入 GM Prompt）
  ...
```

### 3.2 GameDefinition 的 Pydantic 模型

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class ResourceScope(str, Enum):
    PLAYER = "player"
    GLOBAL = "global"

class ResourceDef(BaseModel):
    """资源类型定义"""
    id: str
    name: str
    icon: str = ""
    scope: ResourceScope = ResourceScope.PLAYER
    initial_value: int = 0
    min_value: Optional[int] = 0
    max_value: Optional[int] = None

class CategoryValue(BaseModel):
    """分类值"""
    id: str
    name: str
    icon: str = ""

class CategoryDef(BaseModel):
    """分类系统定义"""
    id: str
    name: str
    values: list[CategoryValue]
    has_multiplier: bool = False
    multiplier_range: tuple[float, float] = (0.5, 2.5)
    initial_multiplier: float = 1.0

class PropertyDef(BaseModel):
    """对象属性定义"""
    id: str
    type: str  # "integer", "text", "enum", "category_ref", "string_list"
    category: Optional[str] = None
    values: Optional[list[str]] = None
    min: Optional[int] = None
    max: Optional[int] = None

class ObjectTypeDef(BaseModel):
    """游戏对象类型定义"""
    id: str
    name: str
    properties: list[PropertyDef]
    deck_name: Optional[str] = None
    hand_limit: Optional[int] = None

class ZoneDef(BaseModel):
    """公共区域定义"""
    id: str
    name: str
    object_type: str
    auto_refill: Optional[dict] = None

class PhaseDef(BaseModel):
    """游戏阶段定义"""
    id: str
    name: str
    auto: bool = False
    actions: list[str] = Field(default_factory=list)
    player_interaction: Optional[str] = None
    trigger_condition: Optional[str] = None

class VictoryDef(BaseModel):
    """胜利条件定义"""
    formula: str
    end_conditions: list[str]
    set_bonuses: list[dict] = Field(default_factory=list)

class GameDefinition(BaseModel):
    """通用游戏定义 — 描述一个桌游的完整结构"""
    name: str
    name_en: str = ""
    description: str = ""
    player_count_min: int = 2
    player_count_max: int = 6
    version: str = "1.0"
    
    resources: list[ResourceDef] = Field(default_factory=list)
    categories: list[CategoryDef] = Field(default_factory=list)
    object_types: list[ObjectTypeDef] = Field(default_factory=list)
    zones: list[ZoneDef] = Field(default_factory=list)
    phases: list[PhaseDef] = Field(default_factory=list)
    phase_order: list[str] = Field(default_factory=list)
    victory: Optional[VictoryDef] = None
    special_mechanics: list[dict] = Field(default_factory=list)
    
    rules_text: str = ""  # 完整规则文本（用于 GM Prompt）
    
    # 游戏对象实例数据
    objects: dict[str, list[dict]] = Field(default_factory=dict)
    # 例如: {"artifact": [{name: "王朝玉玺", era: "ancient", ...}, ...]}
```

---

## 4. PDF 规则书解析流程

### 4.1 整体流程

```
┌──────────┐     ┌───────────────┐     ┌──────────────────┐
│ PDF 文件 │────►│ 文本提取器    │────►│ 结构化文本       │
│ (上传)   │     │ (PyMuPDF等)   │     │ (分章节、分段落) │
└──────────┘     └───────────────┘     └──────────────────┘
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │ LLM 结构化   │
                                       │ 提取 Agent   │
                                       │ (多轮对话)   │
                                       └──────────────┘
                                              │
                      ┌───────────────────────┼────────────────────┐
                      ▼                       ▼                    ▼
               ┌────────────┐         ┌────────────┐       ┌────────────┐
               │ 游戏元信息 │         │ 游戏对象   │       │ 规则文本   │
               │ 提取       │         │ 提取       │       │ 清洗       │
               └────────────┘         └────────────┘       └────────────┘
                      │                       │                    │
                      ▼                       ▼                    ▼
               ┌─────────────────────────────────────────────────────┐
               │              GameDefinition (草稿)                  │
               └─────────────────────────────────────────────────────┘
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │ 验证 & 微调  │
                                       │ (人工 UI)    │
                                       └──────────────┘
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │ GameDefinition│
                                       │ (最终版)     │
                                       │ + 缓存到磁盘 │
                                       └──────────────┘
```

### 4.2 Step 1: PDF 文本提取

```python
# 使用 PyMuPDF (fitz) 提取
import fitz

def extract_pdf_text(pdf_path: str) -> list[dict]:
    """提取 PDF 文本，保留结构信息"""
    doc = fitz.open(pdf_path)
    sections = []
    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" in block:
                text = " ".join(
                    span["text"]
                    for line in block["lines"]
                    for span in line["spans"]
                )
                font_size = max(
                    span["size"]
                    for line in block["lines"]
                    for span in line["spans"]
                )
                sections.append({
                    "page": page_num + 1,
                    "text": text.strip(),
                    "font_size": font_size,
                    "is_heading": font_size > 14,  # 启发式判断标题
                })
    return sections
```

**输出**：带结构标注的文本列表（页码、字号、是否为标题）

### 4.3 Step 2: LLM 结构化提取

使用 Claude 进行多轮提取，每轮聚焦不同维度：

**第一轮：游戏元信息**
```
System: 你是一个桌游规则分析师。请从以下规则书文本中提取游戏的基本信息。

提取以下字段：
- 游戏名称（中文/英文）
- 游戏简介
- 玩家人数范围
- 游戏目标
- 胜利条件

请以 JSON 格式返回。
```

**第二轮：资源与分类系统**
```
System: 请从规则书中提取所有资源类型和分类系统。

资源类型示例：金币、生命值、胜利点数等
分类系统示例：阵营、颜色、种族、时代等

对每种资源，提取：初始值、范围、是否全局共享
对每种分类，提取：所有分类值、是否有倍率机制
```

**第三轮：游戏对象**
```
System: 请从规则书中提取所有游戏对象类型（卡牌、Token、棋子等）。

对每种对象类型，提取：
- 名称和属性字段
- 是否有牌库/手牌概念
- 每个实例的具体数据（如有）
```

**第四轮：阶段与流程**
```
System: 请从规则书中提取回合结构和阶段流程。

对每个阶段，提取：
- 名称
- 执行的行动
- 是否需要玩家交互
- 触发条件（如有）
- 阶段的执行顺序
```

**第五轮：特殊机制**
```
System: 请提取规则书中的特殊机制，如：
- 拍卖方式（公开/密封）
- 投票机制
- 交易规则
- 触发事件
- 特殊胜利条件
```

### 4.4 Step 3: 组装 GameDefinition

将多轮提取的结果组装为 `GameDefinition` 对象：

```python
class RulebookParser:
    """规则书解析器"""
    
    def __init__(self, client: anthropic.Anthropic):
        self.client = client
    
    async def parse(self, pdf_path: str) -> GameDefinition:
        """解析 PDF 规则书，返回 GameDefinition"""
        
        # Step 1: 提取文本
        sections = extract_pdf_text(pdf_path)
        full_text = "\n".join(s["text"] for s in sections)
        
        # Step 2: 多轮 LLM 提取
        meta = await self._extract_meta(full_text)
        resources = await self._extract_resources(full_text)
        categories = await self._extract_categories(full_text)
        object_types, objects = await self._extract_objects(full_text)
        phases = await self._extract_phases(full_text)
        victory = await self._extract_victory(full_text)
        mechanics = await self._extract_mechanics(full_text)
        
        # Step 3: 组装
        return GameDefinition(
            name=meta["name"],
            name_en=meta.get("name_en", ""),
            description=meta.get("description", ""),
            player_count_min=meta.get("min_players", 2),
            player_count_max=meta.get("max_players", 6),
            resources=resources,
            categories=categories,
            object_types=object_types,
            zones=self._infer_zones(object_types, phases),
            phases=phases,
            phase_order=[p.id for p in phases if not p.auto],
            victory=victory,
            special_mechanics=mechanics,
            rules_text=full_text,
            objects=objects,
        )
    
    async def _extract_meta(self, text: str) -> dict:
        """提取游戏元信息"""
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system="你是桌游规则分析师。请从规则书中提取游戏基本信息，以 JSON 返回。",
            messages=[{"role": "user", "content": f"规则书内容：\n\n{text}"}],
        )
        return json.loads(response.content[0].text)
    
    # ... 其他提取方法类似
```

### 4.5 Step 4: 人工微调界面

提供 Web UI 让用户查看和修改 LLM 提取的 GameDefinition：

```
┌─────────────────────────────────────────────────────┐
│ 📋 游戏定义编辑器 - 时空拍卖行                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│ 📌 基本信息                                         │
│ ┌─────────────┬──────────────────────────────────┐  │
│ │ 游戏名称    │ [时空拍卖行                    ] │  │
│ │ 玩家人数    │ [3] ~ [5]                       │  │
│ │ 简介        │ [穿梭于各个平行宇宙的古董商...] │  │
│ └─────────────┴──────────────────────────────────┘  │
│                                                     │
│ 💰 资源系统                        [+ 添加资源]     │
│ ┌──────┬──────┬────────┬───────┬──────────────────┐ │
│ │ ID   │ 名称 │ 初始值 │ 范围  │ 作用域           │ │
│ ├──────┼──────┼────────┼───────┼──────────────────┤ │
│ │money │ 资金 │ 20     │ 0~∞   │ 🔵 每个玩家     │ │
│ │vp    │ VP   │ 0      │ 0~∞   │ 🔵 每个玩家     │ │
│ │stab  │ 稳定 │ 100    │ 0~100 │ 🔴 全局共享     │ │
│ └──────┴──────┴────────┴───────┴──────────────────┘ │
│                                                     │
│ 🏷️ 分类系统                        [+ 添加分类]     │
│ ┌──────┬──────┬─────────────────┬────────────────┐  │
│ │ ID   │ 名称 │ 分类值          │ 倍率           │  │
│ ├──────┼──────┼─────────────────┼────────────────┤  │
│ │era   │ 时代 │ 古代/近代/未来  │ ✅ 0.5~2.5    │  │
│ │rarity│ 稀有 │ 传奇/稀有/常见  │ ❌            │  │
│ └──────┴──────┴─────────────────┴────────────────┘  │
│                                                     │
│ 🃏 游戏对象        [文物] [功能卡] [事件卡]         │
│ ┌──────────────────────────────────────────────┐    │
│ │ 文物 (36张)                    [+ 添加]      │    │
│ │ ┌──────┬───────────┬──────┬──────┬─────────┐ │    │
│ │ │ 名称 │ 时代      │ 稀有 │ 价值 │ 消耗    │ │    │
│ │ ├──────┼───────────┼──────┼──────┼─────────┤ │    │
│ │ │ 王朝 │ 🟡 古代   │ ★   │ 8    │ 9       │ │    │
│ │ │ ...  │ ...       │ ...  │ ...  │ ...     │ │    │
│ │ └──────┴───────────┴──────┴──────┴─────────┘ │    │
│ └──────────────────────────────────────────────┘    │
│                                                     │
│ 📐 阶段流程                        [+ 添加阶段]     │
│ [挖掘] → [拍卖] → [交易] → [回购] → [事件] →      │
│ [投票] → [稳定]                                     │
│                                                     │
│ 🏆 胜利条件                                         │
│ ┌──────────────────────────────────────────────┐    │
│ │ 公式: 文物价值×时代倍率 + 资金/10 + 套装奖励 │    │
│ │ 结束: 牌库空 或 稳定性=0                     │    │
│ └──────────────────────────────────────────────┘    │
│                                                     │
│         [💾 保存]  [🔄 重新解析]  [▶️ 开始游戏]     │
└─────────────────────────────────────────────────────┘
```

---

## 5. 通用状态管理器自动生成

### 5.1 从 GameDefinition 生成 Pydantic 模型

```python
from pydantic import create_model, Field

class ModelGenerator:
    """从 GameDefinition 自动生成 Pydantic 模型"""
    
    def generate(self, game_def: GameDefinition) -> dict[str, type]:
        """返回生成的模型类字典"""
        models = {}
        
        # 1. 生成枚举类
        for cat in game_def.categories:
            enum_cls = self._create_enum(cat)
            models[f"{cat.id}_enum"] = enum_cls
        
        # 2. 生成游戏对象模型
        for obj_type in game_def.object_types:
            model_cls = self._create_object_model(obj_type, game_def.categories)
            models[obj_type.id] = model_cls
        
        # 3. 生成玩家状态模型
        models["player_state"] = self._create_player_state(
            game_def.resources, game_def.object_types
        )
        
        # 4. 生成全局状态模型
        models["global_state"] = self._create_global_state(
            game_def.resources, game_def.categories, 
            game_def.zones, game_def.phases
        )
        
        # 5. 生成完整游戏状态
        models["game_state"] = self._create_game_state(models)
        
        return models
    
    def _create_enum(self, category: CategoryDef):
        """从分类定义创建枚举"""
        from enum import Enum
        return Enum(
            category.id.title(),
            {v.id.upper(): v.id for v in category.values}
        )
    
    def _create_player_state(self, resources, object_types):
        """生成玩家状态模型"""
        fields = {
            "id": (str, ...),
            "name": (str, ...),
            "is_human": (bool, False),
        }
        
        # 添加每个玩家级资源
        for res in resources:
            if res.scope == ResourceScope.PLAYER:
                fields[res.id] = (int, Field(default=res.initial_value))
        
        # 添加每种可持有对象的列表
        for obj_type in object_types:
            if obj_type.deck_name:  # 有牌库 = 可持有
                fields[f"{obj_type.id}s"] = (list, Field(default_factory=list))
        
        return create_model("PlayerState", **fields)
    
    def _create_global_state(self, resources, categories, zones, phases):
        """生成全局状态模型"""
        fields = {
            "game_id": (str, ...),
            "current_round": (int, Field(default=1)),
            "current_phase": (str, Field(default="setup")),
        }
        
        # 全局资源
        for res in resources:
            if res.scope == ResourceScope.GLOBAL:
                fields[res.id] = (int, Field(default=res.initial_value))
        
        # 倍率
        for cat in categories:
            if cat.has_multiplier:
                fields[f"{cat.id}_multipliers"] = (
                    dict, 
                    Field(default_factory=lambda c=cat: {
                        v.id: c.initial_multiplier for v in c.values
                    })
                )
        
        # 区域
        for zone in zones:
            fields[zone.id] = (list, Field(default_factory=list))
        
        return create_model("GlobalState", **fields)
```

### 5.2 从 GameDefinition 生成工具集

```python
class ToolGenerator:
    """从 GameDefinition 自动生成 GM 工具定义"""
    
    def generate(self, game_def: GameDefinition) -> list[dict]:
        """返回工具定义列表 (Claude tool schema)"""
        tools = []
        
        # 通用工具（所有游戏都有）
        tools.append(self._get_state_tool())
        tools.append(self._broadcast_tool())
        tools.append(self._request_action_tool())
        tools.append(self._set_phase_tool(game_def.phases))
        
        # 资源修改工具
        for res in game_def.resources:
            tools.append(self._resource_modify_tool(res))
        
        # 对象转移工具
        for obj_type in game_def.object_types:
            tools.append(self._transfer_tool(obj_type))
            if obj_type.deck_name:
                tools.append(self._draw_tool(obj_type))
        
        # 分类倍率工具
        for cat in game_def.categories:
            if cat.has_multiplier:
                tools.append(self._multiplier_tool(cat))
        
        # 特殊机制工具
        for mechanic in game_def.special_mechanics:
            tools.extend(self._mechanic_tools(mechanic))
        
        return tools
    
    def _resource_modify_tool(self, resource: ResourceDef) -> dict:
        """生成资源修改工具"""
        scope_desc = "指定玩家" if resource.scope == ResourceScope.PLAYER else "全局"
        return {
            "name": f"update_{resource.id}",
            "description": f"修改{scope_desc}的{resource.name}",
            "input_schema": {
                "type": "object",
                "properties": {
                    **({"player_id": {"type": "string"}} 
                       if resource.scope == ResourceScope.PLAYER else {}),
                    "delta": {
                        "type": "integer",
                        "description": f"{resource.name}变化量"
                    }
                },
                "required": ["delta"] + (
                    ["player_id"] if resource.scope == ResourceScope.PLAYER else []
                )
            }
        }
```

### 5.3 从 GameDefinition 生成 GM Prompt

```python
class PromptGenerator:
    """从 GameDefinition 生成 GM System Prompt"""
    
    def generate(self, game_def: GameDefinition) -> str:
        """生成完整的 GM system prompt"""
        
        sections = [
            self._header(game_def),
            self._game_overview(game_def),
            self._setup_rules(game_def),
            self._phase_rules(game_def),
            self._special_mechanics(game_def),
            self._victory_rules(game_def),
            self._gm_guidelines(game_def),
            self._tool_usage_guide(game_def),
        ]
        
        # 如果有原始规则文本，附加作为参考
        if game_def.rules_text:
            sections.append(f"\n## 原始规则参考\n\n{game_def.rules_text}")
        
        return "\n\n".join(sections)
    
    def _header(self, game_def: GameDefinition) -> str:
        return f"""# {game_def.name} 游戏规则书

你是 {game_def.name} 的游戏主持人 (GM)。你负责主持整局游戏，确保规则正确执行，并为玩家提供沉浸式体验。"""
    
    def _game_overview(self, game_def: GameDefinition) -> str:
        return f"""## 游戏概述

{game_def.description}

- 玩家人数: {game_def.player_count_min}~{game_def.player_count_max} 人
- 游戏目标: {game_def.victory.formula if game_def.victory else '未定义'}"""
    
    # ... 其他生成方法
```

---

## 6. 缓存机制设计

### 6.1 缓存层次

```
┌─────────────────────────────────────────────────┐
│ Level 1: PDF 文本缓存                            │
│ 键: sha256(pdf_file)                            │
│ 值: 提取的结构化文本                             │
│ 位置: cache/pdf_texts/{hash}.json               │
│ 失效: PDF 文件变化时                             │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│ Level 2: GameDefinition 缓存                     │
│ 键: sha256(pdf_file) + model_version             │
│ 值: GameDefinition JSON                          │
│ 位置: cache/game_defs/{game_name}_{hash}.json   │
│ 失效: PDF 变化 或 LLM 模型升级时                 │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│ Level 3: 生成产物缓存                            │
│ 键: sha256(GameDefinition JSON)                  │
│ 值: 生成的模型代码 + 工具定义 + GM Prompt        │
│ 位置: cache/generated/{game_name}/               │
│   ├── models.py                                  │
│   ├── tools.json                                 │
│   ├── gm_prompt.md                               │
│   └── meta.json (生成时间、来源等)               │
│ 失效: GameDefinition 变化时                      │
└─────────────────────────────────────────────────┘
```

### 6.2 缓存管理器

```python
import hashlib
import json
from pathlib import Path

class CacheManager:
    """游戏定义与生成产物缓存管理"""
    
    CACHE_DIR = Path("cache")
    
    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    def get_pdf_hash(self, pdf_path: str) -> str:
        """计算 PDF 文件哈希"""
        with open(pdf_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    
    def get_definition_hash(self, game_def: GameDefinition) -> str:
        """计算 GameDefinition 哈希"""
        json_str = game_def.model_dump_json(exclude={"rules_text"})
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def load_game_definition(self, game_name: str) -> GameDefinition | None:
        """尝试从缓存加载 GameDefinition"""
        cache_dir = self.CACHE_DIR / "game_defs"
        for f in cache_dir.glob(f"{game_name}_*.json"):
            try:
                return GameDefinition.model_validate_json(f.read_text())
            except Exception:
                continue
        return None
    
    def save_game_definition(self, game_def: GameDefinition):
        """保存 GameDefinition 到缓存"""
        cache_dir = self.CACHE_DIR / "game_defs"
        cache_dir.mkdir(parents=True, exist_ok=True)
        pdf_hash = "manual"  # 或关联的 PDF 哈希
        path = cache_dir / f"{game_def.name}_{pdf_hash}.json"
        path.write_text(game_def.model_dump_json(indent=2), encoding="utf-8")
    
    def load_generated(self, game_name: str, def_hash: str) -> dict | None:
        """尝试从缓存加载生成产物"""
        gen_dir = self.CACHE_DIR / "generated" / game_name
        meta_path = gen_dir / "meta.json"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())
        if meta.get("definition_hash") != def_hash:
            return None
        return {
            "tools": json.loads((gen_dir / "tools.json").read_text()),
            "gm_prompt": (gen_dir / "gm_prompt.md").read_text(),
            "meta": meta,
        }
    
    def save_generated(self, game_name: str, def_hash: str, 
                       tools: list, gm_prompt: str):
        """保存生成产物到缓存"""
        gen_dir = self.CACHE_DIR / "generated" / game_name
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "tools.json").write_text(json.dumps(tools, indent=2, ensure_ascii=False))
        (gen_dir / "gm_prompt.md").write_text(gm_prompt, encoding="utf-8")
        (gen_dir / "meta.json").write_text(json.dumps({
            "definition_hash": def_hash,
            "game_name": game_name,
        }, indent=2))
```

### 6.3 增量更新

当用户通过微调界面修改 GameDefinition 时：

```python
class IncrementalUpdater:
    """增量更新器 — 只重新生成变化的部分"""
    
    def update(self, old_def: GameDefinition, new_def: GameDefinition):
        """比较新旧定义，只重新生成变化的部分"""
        changes = self._diff(old_def, new_def)
        
        if changes.get("resources_changed"):
            # 重新生成资源相关工具
            ...
        
        if changes.get("object_types_changed"):
            # 重新生成对象模型和转移工具
            ...
        
        if changes.get("phases_changed"):
            # 重新生成阶段流程部分的 Prompt
            ...
        
        if changes.get("rules_text_changed"):
            # 只更新 GM Prompt 中的规则文本部分
            ...
        
        # 始终重新生成 GM Prompt（因为它是整体性的）
        # 但可以缓存不变的部分
```

---

## 7. 从现有代码到通用框架的改造路径

### 7.1 渐进式改造策略

保持现有《时空拍卖行》功能不变，逐步引入通用化层。

```
Phase 1: 引入 GameDefinition
    │  - 创建 GameDefinition Pydantic 模型
    │  - 将《时空拍卖行》的硬编码数据表示为 GameDefinition 实例
    │  - 验证：原有测试全部通过
    ↓
Phase 2: 抽取通用引擎
    │  - 从 GameManager 中拆分出 UniversalGameManager（通用原子操作）
    │  - 将游戏特定逻辑（事件结算、功能卡效果）移入 GameAdapter
    │  - 验证：原有测试全部通过
    ↓
Phase 3: 动态工具生成
    │  - 实现 ToolGenerator（从 GameDefinition 生成工具 Schema）
    │  - 实现 PromptGenerator（从 GameDefinition 生成 GM Prompt）
    │  - 验证：用生成的工具 + Prompt 运行《时空拍卖行》，效果等同
    ↓
Phase 4: PDF 解析
    │  - 实现 PDF 文本提取
    │  - 实现 LLM 结构化提取（多轮对话）
    │  - 实现缓存机制
    │  - 验证：上传《时空拍卖行》规则书 PDF，自动生成等价 GameDefinition
    ↓
Phase 5: 微调界面
    │  - 实现 GameDefinition 编辑 Web UI
    │  - 支持从 PDF 自动填充 + 人工修正
    │  - 验证：端到端流程（上传 PDF → 编辑 → 开始游戏）
    ↓
Phase 6: 多游戏支持
       - 尝试用其他桌游规则书测试通用性
       - 识别和解决框架限制
       - 持续优化 LLM 提取准确度
```

### 7.2 文件结构演进

```
board_game_agent/
├── src/
│   ├── core/                    # 【新增】核心引擎层
│   │   ├── game_definition.py   # GameDefinition 模型
│   │   ├── universal_manager.py # 通用 GameManager
│   │   ├── model_generator.py   # 动态模型生成
│   │   ├── tool_generator.py    # 动态工具生成
│   │   └── prompt_generator.py  # 动态 Prompt 生成
│   │
│   ├── parser/                  # 【新增】规则书解析
│   │   ├── pdf_extractor.py     # PDF 文本提取
│   │   ├── llm_extractor.py     # LLM 结构化提取
│   │   └── cache_manager.py     # 缓存管理
│   │
│   ├── games/                   # 【新增】游戏实例
│   │   └── chronos_auction/     # 时空拍卖行（从原有代码迁移）
│   │       ├── definition.json  # GameDefinition 实例
│   │       ├── adapter.py       # 游戏特定适配逻辑
│   │       └── data/            # 原有的牌库数据
│   │
│   ├── agents/                  # 【改造】Agent 层
│   │   ├── gm_agent.py          # 改为接收动态工具集
│   │   └── player_agent.py      # 独立出 PlayerAgent
│   │
│   ├── models/                  # 【保留】基础模型（向后兼容）
│   ├── tools/                   # 【保留】原有工具（向后兼容）
│   ├── data/                    # 【保留】原有数据（向后兼容）
│   ├── api/                     # 【改造】新增规则上传/编辑端点
│   └── utils/                   # 【保留】通用工具
│
├── cache/                       # 【新增】缓存目录
│   ├── pdf_texts/
│   ├── game_defs/
│   └── generated/
│
├── docs/                        # 【新增】文档
│   ├── architecture-analysis.md
│   └── universal-design.md
│
└── tests/                       # 【扩展】新增通用框架测试
    ├── test_game_definition.py
    ├── test_model_generator.py
    ├── test_tool_generator.py
    ├── test_pdf_parser.py
    └── ...（原有测试保留）
```

---

## 8. 风险与挑战

### 8.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| PDF 解析质量不稳定 | 生成的 GameDefinition 不准确 | 多轮 LLM 提取 + 人工微调界面兜底 |
| LLM 结构化提取幻觉 | 提取出不存在的规则 | 每轮提取后校验，提供原文引用 |
| 游戏机制多样性超出 Schema | 某些桌游无法用 GameDefinition 表示 | Schema 设计保留扩展点（special_mechanics） |
| 自动结算逻辑难以通用化 | 事件/卡牌效果用自然语言描述，难以转代码 | 将复杂效果交给 GM Agent 理解并手动执行 |
| 动态生成的工具性能 | 运行时模型创建可能有开销 | 缓存生成结果，启动时一次性加载 |

### 8.2 设计权衡

| 决策点 | 选项 A | 选项 B | 推荐 |
|--------|--------|--------|------|
| 事件效果处理 | 用 DSL 形式化所有效果 | 交给 GM 用自然语言理解 | **B**：更灵活，利用 LLM 优势 |
| GameDefinition 格式 | JSON (机器友好) | YAML (人类友好) | **JSON**：Pydantic 原生支持，可提供 YAML 转换 |
| 缓存存储 | 文件系统 | SQLite | **文件系统**：简单可靠，易于版本控制 |
| 工具生成 | 完全静态生成 | 部分动态 + 部分 GM 自由发挥 | **混合**：基础工具静态生成，复杂逻辑交给 GM |

### 8.3 范围控制

**第一阶段**（本分支重点）：
- ✅ GameDefinition Schema 设计
- ✅ 架构分析文档
- ✅ 通用化设计方案文档

**后续阶段**（按优先级）：
1. 实现 GameDefinition 模型 + 将《时空拍卖行》转为实例
2. 实现通用 GameManager + ToolGenerator
3. 实现 PDF 解析器
4. 实现缓存机制
5. 实现微调 UI

---

## 9. 总结

本设计方案的核心思路是：

1. **引入 GameDefinition 中间表示** — 作为"任意桌游"的结构化描述
2. **PDF → GameDefinition → 运行时** — 三步转换流水线
3. **优先自动，可以微调** — LLM 提取为主，人工编辑为辅
4. **渐进式改造** — 保持现有代码可运行，逐步替换为通用实现
5. **利用 GM 主控架构优势** — 复杂规则交给 LLM 理解，代码只做原子操作

现有代码的 GM 主控设计理念（"代码只做存储，GM 决定一切"）天然适合通用化——只要我们能把"一个桌游是什么"形式化为 `GameDefinition`，剩下的就是自动生成存储模型和原子工具，然后把规则文本注入 GM Prompt。
