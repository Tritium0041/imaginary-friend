"""Tests for DocStore — TinyDB document store wrapper."""
from __future__ import annotations

import pytest
from src.core.doc_store import DocStore


class TestDocStoreBasicCRUD:
    def test_insert_and_find(self):
        ds = DocStore()
        result = ds.insert("global", {"_id": "state", "round": 1})
        assert result["_id"] == "state"
        assert result["round"] == 1

        found = ds.find("global", {"_id": "state"})
        assert len(found) == 1
        assert found[0]["round"] == 1

    def test_find_all(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "name": "Alice"})
        ds.insert("players", {"_id": "p2", "name": "Bob"})
        all_players = ds.find("players")
        assert len(all_players) == 2

    def test_find_empty(self):
        ds = DocStore()
        found = ds.find("global", {"_id": "nonexistent"})
        assert found == []

    def test_delete(self):
        ds = DocStore()
        ds.insert("zones", {"_id": "deck", "cards": [1, 2, 3]})
        result = ds.delete("zones", {"_id": "deck"})
        assert result["deleted"] == 1
        assert ds.find("zones", {"_id": "deck"}) == []

    def test_delete_no_match(self):
        ds = DocStore()
        result = ds.delete("zones", {"_id": "nonexistent"})
        assert result["deleted"] == 0

    def test_invalid_table(self):
        ds = DocStore()
        with pytest.raises(ValueError, match="Unknown table"):
            ds.find("invalid_table", {})


class TestDocStoreUpdateOperators:
    def test_set(self):
        ds = DocStore()
        ds.insert("global", {"_id": "state", "phase": "setup", "round": 1})
        result = ds.update("global", {"_id": "state"}, {"$set": {"phase": "bidding", "round": 2}})
        assert result["modified"] == 1
        doc = ds.find("global", {"_id": "state"})[0]
        assert doc["phase"] == "bidding"
        assert doc["round"] == 2

    def test_inc(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "gold": 20, "vp": 0})
        ds.update("players", {"_id": "p1"}, {"$inc": {"gold": -5, "vp": 3}})
        doc = ds.find("players", {"_id": "p1"})[0]
        assert doc["gold"] == 15
        assert doc["vp"] == 3

    def test_push(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "hand": []})
        ds.update("players", {"_id": "p1"}, {"$push": {"hand": {"name": "Card A", "value": 5}}})
        doc = ds.find("players", {"_id": "p1"})[0]
        assert len(doc["hand"]) == 1
        assert doc["hand"][0]["name"] == "Card A"

    def test_pull_dict_match(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "hand": [
            {"name": "Card A", "value": 5},
            {"name": "Card B", "value": 3},
        ]})
        ds.update("players", {"_id": "p1"}, {"$pull": {"hand": {"name": "Card A"}}})
        doc = ds.find("players", {"_id": "p1"})[0]
        assert len(doc["hand"]) == 1
        assert doc["hand"][0]["name"] == "Card B"

    def test_pull_simple_value(self):
        ds = DocStore()
        ds.insert("zones", {"_id": "deck", "items": ["a", "b", "c"]})
        ds.update("zones", {"_id": "deck"}, {"$pull": {"items": "b"}})
        doc = ds.find("zones", {"_id": "deck"})[0]
        assert doc["items"] == ["a", "c"]

    def test_combined_operators(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "gold": 20, "hand": []})
        ds.update("players", {"_id": "p1"}, {
            "$inc": {"gold": -3},
            "$push": {"hand": {"name": "Sword"}},
        })
        doc = ds.find("players", {"_id": "p1"})[0]
        assert doc["gold"] == 17
        assert len(doc["hand"]) == 1

    def test_update_no_match(self):
        ds = DocStore()
        result = ds.update("players", {"_id": "nobody"}, {"$set": {"x": 1}})
        assert result["matched"] == 0
        assert result["modified"] == 0

    def test_direct_assignment(self):
        ds = DocStore()
        ds.insert("global", {"_id": "s", "phase": "old"})
        ds.update("global", {"_id": "s"}, {"phase": "new"})
        doc = ds.find("global", {"_id": "s"})[0]
        assert doc["phase"] == "new"


class TestDocStoreComparisonQueries:
    def test_gt(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "gold": 5})
        ds.insert("players", {"_id": "p2", "gold": 15})
        found = ds.find("players", {"gold": {"$gt": 10}})
        assert len(found) == 1
        assert found[0]["_id"] == "p2"

    def test_lte(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "gold": 10})
        ds.insert("players", {"_id": "p2", "gold": 20})
        found = ds.find("players", {"gold": {"$lte": 10}})
        assert len(found) == 1
        assert found[0]["_id"] == "p1"

    def test_ne(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "role": "human"})
        ds.insert("players", {"_id": "p2", "role": "ai"})
        found = ds.find("players", {"role": {"$ne": "human"}})
        assert len(found) == 1
        assert found[0]["_id"] == "p2"


class TestDocStoreSnapshot:
    def test_full_snapshot(self):
        ds = DocStore()
        ds.insert("global", {"_id": "state", "round": 1})
        ds.insert("players", {"_id": "p1", "gold": 10})
        snap = ds.snapshot()
        assert "global" in snap
        assert "players" in snap
        assert "zones" in snap
        assert "logs" in snap
        assert len(snap["global"]) == 1
        assert len(snap["players"]) == 1

    def test_snapshot_for_player_hides_private(self):
        ds = DocStore()
        ds.insert("players", {"_id": "p1", "gold": 10, "hand": [{"name": "Secret"}], "private_strategy": "bluff"})
        ds.insert("players", {"_id": "p2", "gold": 15, "hand": [{"name": "Card A"}], "private_strategy": "safe"})

        snap = ds.snapshot_for_player("p1")
        p1 = next(p for p in snap["players"] if p["_id"] == "p1")
        p2 = next(p for p in snap["players"] if p["_id"] == "p2")

        # p1 sees all their own data
        assert "hand" in p1
        assert "private_strategy" in p1

        # p2's private data is hidden from p1
        assert "hand" not in p2
        assert "private_strategy" not in p2
        assert "gold" in p2  # public fields visible

    def test_clear(self):
        ds = DocStore()
        ds.insert("global", {"_id": "s"})
        ds.insert("players", {"_id": "p1"})
        ds.clear()
        assert ds.find("global") == []
        assert ds.find("players") == []
