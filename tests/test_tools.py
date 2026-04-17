"""Tests for fixed tool schemas and ToolExecutor."""
from __future__ import annotations

import pytest
from src.core.tools import TOOL_SCHEMAS, get_tool_schemas, ToolExecutor
from src.core.doc_store import DocStore


class TestToolSchemas:
    def test_has_seven_tools(self):
        assert len(TOOL_SCHEMAS) == 7

    def test_tool_names(self):
        names = {t["name"] for t in TOOL_SCHEMAS}
        assert names == {
            "db_find", "db_insert", "db_update", "db_delete",
            "db_shuffle", "request_player_action", "broadcast_message",
        }

    def test_each_has_required_fields(self):
        for tool in TOOL_SCHEMAS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_get_tool_schemas_returns_same(self):
        assert get_tool_schemas() is TOOL_SCHEMAS


class TestToolExecutor:
    @pytest.fixture
    def executor(self):
        store = DocStore()
        return ToolExecutor(store)

    def test_db_insert_and_find(self, executor):
        result = executor.execute("db_insert", {
            "table": "players",
            "document": {"_id": "p1", "name": "Alice", "gold": 20},
        })
        assert "inserted" in result
        assert result["inserted"]["_id"] == "p1"

        found = executor.execute("db_find", {
            "table": "players",
            "query": {"_id": "p1"},
        })
        assert found["count"] == 1
        assert found["results"][0]["name"] == "Alice"

    def test_db_update(self, executor):
        executor.execute("db_insert", {
            "table": "global",
            "document": {"_id": "state", "round": 1},
        })
        result = executor.execute("db_update", {
            "table": "global",
            "query": {"_id": "state"},
            "update": {"$inc": {"round": 1}},
        })
        assert result["modified"] == 1

        found = executor.execute("db_find", {
            "table": "global",
            "query": {"_id": "state"},
        })
        assert found["results"][0]["round"] == 2

    def test_db_delete(self, executor):
        executor.execute("db_insert", {
            "table": "zones",
            "document": {"_id": "deck", "count": 36},
        })
        result = executor.execute("db_delete", {
            "table": "zones",
            "query": {"_id": "deck"},
        })
        assert result["deleted"] == 1

    def test_request_player_action(self, executor):
        result = executor.execute("request_player_action", {
            "player_id": "p1",
            "context": "请出价",
        })
        assert result["waiting"] is True
        assert result["player_id"] == "p1"

    def test_broadcast_message(self, executor):
        result = executor.execute("broadcast_message", {
            "message": "第一轮开始！",
        })
        assert result["sent"] is True
        assert result["message"] == "第一轮开始！"

    def test_unknown_tool(self, executor):
        result = executor.execute("nonexistent_tool", {})
        assert "error" in result

    def test_db_shuffle_basic(self, executor):
        executor.execute("db_insert", {
            "table": "zones",
            "document": {"_id": "deck", "cards": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
        })
        result = executor.execute("db_shuffle", {
            "table": "zones",
            "query": {"_id": "deck"},
            "field": "cards",
        })
        assert result["matched"] == 1
        assert result["shuffled"] == 1
        found = executor.execute("db_find", {
            "table": "zones",
            "query": {"_id": "deck"},
        })
        cards = found["results"][0]["cards"]
        assert sorted(cards) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    def test_db_shuffle_no_match(self, executor):
        result = executor.execute("db_shuffle", {
            "table": "zones",
            "query": {"_id": "nonexistent"},
            "field": "cards",
        })
        assert result["matched"] == 0
        assert result["shuffled"] == 0

    def test_db_shuffle_field_not_array(self, executor):
        executor.execute("db_insert", {
            "table": "zones",
            "document": {"_id": "board", "size": 10},
        })
        result = executor.execute("db_shuffle", {
            "table": "zones",
            "query": {"_id": "board"},
            "field": "size",
        })
        assert result["matched"] == 1
        assert result["shuffled"] == 0

    def test_db_shuffle_field_missing(self, executor):
        executor.execute("db_insert", {
            "table": "zones",
            "document": {"_id": "empty_zone"},
        })
        result = executor.execute("db_shuffle", {
            "table": "zones",
            "query": {"_id": "empty_zone"},
            "field": "cards",
        })
        assert result["matched"] == 1
        assert result["shuffled"] == 0
