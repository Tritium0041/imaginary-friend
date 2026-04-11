"""
DocStore — 基于 TinyDB 的文档数据库封装

提供 4 个固定表（global, players, zones, logs）和 MongoDB 风格的更新操作符。
GM Agent 通过 6 个固定工具操作此存储层。
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from tinydb import TinyDB, Query, where
from tinydb.storages import MemoryStorage

logger = logging.getLogger(__name__)

CORE_TABLES = ("global", "players", "zones", "logs")


class DocStore:
    """TinyDB 文档数据库封装，提供 MongoDB 风格的 CRUD 操作。"""

    def __init__(self) -> None:
        self._db = TinyDB(storage=MemoryStorage)
        self._tables: dict[str, Any] = {}
        for name in CORE_TABLES:
            self._tables[name] = self._db.table(name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find(self, table: str, query: dict | None = None) -> list[dict]:
        """查找符合条件的文档。query 为空时返回全部。"""
        tbl = self._get_table(table)
        if not query:
            docs = tbl.all()
        else:
            cond = self._build_condition(query)
            docs = tbl.search(cond)
        return [self._export(d) for d in docs]

    def insert(self, table: str, document: dict) -> dict:
        """插入新文档。返回插入后的文档（含 doc_id）。"""
        tbl = self._get_table(table)
        doc = copy.deepcopy(document)
        doc_id = tbl.insert(doc)
        result = tbl.get(doc_id=doc_id)
        return self._export(result)

    def update(self, table: str, query: dict, update: dict) -> dict:
        """
        更新匹配文档。支持 MongoDB 风格操作符：
          $set  — 设置字段值
          $inc  — 数值增减
          $push — 向数组追加元素
          $pull — 从数组移除匹配元素

        也支持直接字段赋值（无操作符前缀视为 $set）。
        返回 {"matched": n, "modified": n}。
        """
        tbl = self._get_table(table)
        cond = self._build_condition(query)
        matched_docs = tbl.search(cond)

        if not matched_docs:
            return {"matched": 0, "modified": 0}

        modified = 0
        for doc in matched_docs:
            changes = self._apply_update_ops(doc, update)
            if changes:
                tbl.update(changes, doc_ids=[doc.doc_id])
                modified += 1

        return {"matched": len(matched_docs), "modified": modified}

    def delete(self, table: str, query: dict) -> dict:
        """删除匹配文档。返回 {"deleted": n}。"""
        tbl = self._get_table(table)
        cond = self._build_condition(query)
        matched = tbl.search(cond)
        if not matched:
            return {"deleted": 0}
        doc_ids = [d.doc_id for d in matched]
        tbl.remove(doc_ids=doc_ids)
        return {"deleted": len(doc_ids)}

    def snapshot(self) -> dict:
        """返回完整数据库快照（JSON 可序列化）。"""
        result: dict[str, Any] = {}
        for name in CORE_TABLES:
            tbl = self._tables[name]
            result[name] = [self._export(d) for d in tbl.all()]
        return result

    def snapshot_for_player(self, player_id: str) -> dict:
        """
        返回面向特定玩家的快照：
        - global 和 zones 完整返回
        - players 中仅当前玩家返回完整数据，其他玩家过滤 private_ 前缀字段和 hand 字段
        - logs 完整返回
        """
        result = self.snapshot()
        filtered_players = []
        for p in result.get("players", []):
            if p.get("_id") == player_id:
                filtered_players.append(p)
            else:
                public = {}
                for k, v in p.items():
                    if k.startswith("private_") or k == "hand":
                        continue
                    public[k] = v
                filtered_players.append(public)
        result["players"] = filtered_players
        return result

    def clear(self) -> None:
        """清空所有表。"""
        for tbl in self._tables.values():
            tbl.clear_cache()
            tbl.truncate()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_table(self, table: str) -> Any:
        if table not in self._tables:
            raise ValueError(
                f"Unknown table '{table}'. Valid tables: {', '.join(CORE_TABLES)}"
            )
        return self._tables[table]

    @staticmethod
    def _export(doc: Any) -> dict:
        """将 TinyDB Document 转为普通 dict。"""
        if doc is None:
            return {}
        d = dict(doc)
        return d

    def _build_condition(self, query: dict) -> Any:
        """
        将 dict query 转换为 TinyDB 查询条件。
        支持：
          {"_id": "value"}           → 精确匹配
          {"field": {"$gt": 10}}     → 比较查询
          {"a": 1, "b": 2}          → AND 组合
        """
        conditions = []
        for key, val in query.items():
            if isinstance(val, dict):
                for op, operand in val.items():
                    cond = self._comparison_op(key, op, operand)
                    conditions.append(cond)
            else:
                conditions.append(where(key) == val)

        if not conditions:
            return Query().noop()
        result = conditions[0]
        for c in conditions[1:]:
            result = result & c
        return result

    @staticmethod
    def _comparison_op(key: str, op: str, operand: Any) -> Any:
        field = where(key)
        ops = {
            "$gt": field > operand,
            "$gte": field >= operand,
            "$lt": field < operand,
            "$lte": field <= operand,
            "$ne": field != operand,
            "$eq": field == operand,
        }
        if op in ops:
            return ops[op]
        raise ValueError(f"Unsupported query operator: {op}")

    @staticmethod
    def _apply_update_ops(doc: dict, update: dict) -> dict:
        """
        解析更新操作符并返回要写入的字段变更 dict。
        支持 $set, $inc, $push, $pull。
        无操作符前缀的键视为 $set。
        """
        changes: dict[str, Any] = {}
        has_operators = any(k.startswith("$") for k in update)

        if not has_operators:
            # 无操作符，视为直接赋值 ($set)
            changes.update(update)
            return changes

        for op, fields in update.items():
            if op == "$set":
                for k, v in fields.items():
                    changes[k] = v

            elif op == "$inc":
                for k, delta in fields.items():
                    current = doc.get(k, 0)
                    changes[k] = current + delta

            elif op == "$push":
                for k, item in fields.items():
                    current = list(doc.get(k, []))
                    current.append(item)
                    changes[k] = current

            elif op == "$pull":
                for k, match in fields.items():
                    current = list(doc.get(k, []))
                    if isinstance(match, dict):
                        # 按字段匹配移除：{"hand": {"name": "Ancient Vase"}}
                        filtered = [
                            elem for elem in current
                            if not _dict_matches(elem, match)
                        ]
                    else:
                        # 简单值移除
                        filtered = [elem for elem in current if elem != match]
                    changes[k] = filtered

            else:
                raise ValueError(f"Unsupported update operator: {op}")

        return changes


def _dict_matches(elem: Any, match: dict) -> bool:
    """检查 elem 是否匹配 match 中的所有键值对。"""
    if not isinstance(elem, dict):
        return False
    return all(elem.get(k) == v for k, v in match.items())
