"""
Tools — 6 个固定工具的 Schema 定义与执行逻辑。

替代旧的 ToolGenerator 动态工具生成。
GM Agent 仅通过这 6 个工具与游戏状态交互。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Tool Schema 定义（Anthropic Claude Tool Format）
# ------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "db_find",
        "description": (
            "查找数据库中符合条件的文档。"
            "可用的表: global（全局状态）, players（玩家）, zones（区域/容器）, logs（日志）。"
            "query 为空 {} 时返回该表全部文档。"
            "支持精确匹配: {\"_id\": \"player_1\"} 和比较查询: {\"gold\": {\"$gt\": 10}}。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "enum": ["global", "players", "zones", "logs"],
                    "description": "要查询的表名",
                },
                "query": {
                    "type": "object",
                    "description": "查询条件。为空对象 {} 时返回全部文档。",
                },
            },
            "required": ["table", "query"],
        },
    },
    {
        "name": "db_insert",
        "description": (
            "向数据库表中插入一个新文档。"
            "可用的表: global, players, zones, logs。"
            "建议为每个文档设置 _id 字段以便后续查询。"
            "logs 表用于记录不可变的游戏日志。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "enum": ["global", "players", "zones", "logs"],
                    "description": "要插入的表名",
                },
                "document": {
                    "type": "object",
                    "description": "要插入的文档内容。建议包含 _id 字段。",
                },
            },
            "required": ["table", "document"],
        },
    },
    {
        "name": "db_update",
        "description": (
            "更新数据库中匹配的文档。支持 MongoDB 风格的更新操作符：\n"
            "- $set: 设置字段值。示例: {\"$set\": {\"current_phase\": \"bidding\"}}\n"
            "- $inc: 数值增减。示例: {\"$inc\": {\"gold\": -5, \"score\": 2}}\n"
            "- $push: 向数组追加元素。示例: {\"$push\": {\"hand\": {\"name\": \"Card A\", \"value\": 10}}}\n"
            "- $pull: 从数组移除匹配元素。示例: {\"$pull\": {\"hand\": {\"name\": \"Card A\"}}}\n"
            "可组合使用多个操作符。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "enum": ["global", "players", "zones", "logs"],
                    "description": "要更新的表名",
                },
                "query": {
                    "type": "object",
                    "description": "匹配条件，指定要更新哪些文档",
                },
                "update": {
                    "type": "object",
                    "description": "更新操作。使用 $set/$inc/$push/$pull 操作符。",
                },
            },
            "required": ["table", "query", "update"],
        },
    },
    {
        "name": "db_delete",
        "description": (
            "从数据库表中删除匹配的文档。"
            "谨慎使用此工具，删除操作不可逆。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "enum": ["global", "players", "zones", "logs"],
                    "description": "要删除的表名",
                },
                "query": {
                    "type": "object",
                    "description": "匹配条件，指定要删除哪些文档",
                },
            },
            "required": ["table", "query"],
        },
    },
    {
        "name": "request_player_action",
        "description": (
            "向指定玩家请求行动输入。调用后 GM 线程将挂起，等待玩家回复。"
            "context 应包含当前局势描述和可选行动提示，帮助玩家做出决策。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "string",
                    "description": "玩家的 _id",
                },
                "context": {
                    "type": "string",
                    "description": "当前局势描述和行动提示",
                },
            },
            "required": ["player_id", "context"],
        },
    },
    {
        "name": "broadcast_message",
        "description": (
            "向所有玩家广播一条文本消息。用于宣布游戏事件、回合开始、结果等。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "要广播的消息内容",
                },
            },
            "required": ["message"],
        },
    },
]


def get_tool_schemas() -> list[dict[str, Any]]:
    """返回 6 个固定工具的 Schema（用于 Anthropic API tools 参数）。"""
    return TOOL_SCHEMAS


class ToolExecutor:
    """工具执行器 — 将工具调用路由到 DocStore 或交互处理器。"""

    def __init__(self, doc_store: Any) -> None:
        from src.core.doc_store import DocStore

        self._store: DocStore = doc_store

    def execute(self, tool_name: str, tool_input: dict) -> dict[str, Any]:
        """执行工具调用，返回结果 dict。"""
        handler = getattr(self, f"_handle_{tool_name}", None)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(tool_input)
        except Exception as e:
            logger.exception("Tool execution error: %s(%s)", tool_name, tool_input)
            return {"error": str(e)}

    def _handle_db_find(self, params: dict) -> dict:
        table = params["table"]
        query = params.get("query", {})
        results = self._store.find(table, query)
        return {"results": results, "count": len(results)}

    def _handle_db_insert(self, params: dict) -> dict:
        table = params["table"]
        document = params["document"]
        inserted = self._store.insert(table, document)
        return {"inserted": inserted}

    def _handle_db_update(self, params: dict) -> dict:
        table = params["table"]
        query = params["query"]
        update = params["update"]
        result = self._store.update(table, query, update)
        return result

    def _handle_db_delete(self, params: dict) -> dict:
        table = params["table"]
        query = params["query"]
        result = self._store.delete(table, query)
        return result

    def _handle_request_player_action(self, params: dict) -> dict:
        # This is intercepted by GMAgent before reaching here.
        # If it reaches here, return a marker for the agent loop.
        return {
            "waiting": True,
            "player_id": params["player_id"],
            "context": params["context"],
        }

    def _handle_broadcast_message(self, params: dict) -> dict:
        message = params["message"]
        logger.info("Broadcast: %s", message)
        return {"sent": True, "message": message}
