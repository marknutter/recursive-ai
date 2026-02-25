"""Tests for structured fact extraction and storage."""

import os
import tempfile
import time
import unittest

# Use a temporary database for all tests
_test_db_dir = tempfile.mkdtemp(prefix="rlm-test-facts-")
os.environ.setdefault("RLM_MEMORY_DIR", _test_db_dir)

# Patch db.py paths BEFORE import
import rlm.db as db_mod
db_mod.MEMORY_DIR = _test_db_dir
db_mod.DB_PATH = os.path.join(_test_db_dir, "memory.db")

from rlm import db
from rlm.facts import (
    _extract_fallback,
    _parse_llm_response,
    extract_facts_from_transcript,
    format_facts,
    store_facts,
)


def _seed_entry():
    """Insert a dummy entry to satisfy FK constraint."""
    db.insert_entry(
        entry_id="m_test123",
        summary="test entry",
        tags=["test"],
        timestamp=time.time(),
        source="text",
        source_name=None,
        char_count=100,
        content="test content",
    )


class TestFactsDBOperations(unittest.TestCase):
    """Test facts table CRUD operations."""

    def setUp(self):
        """Ensure clean facts table for each test."""
        conn = db._get_conn()
        conn.execute("DELETE FROM facts")
        conn.execute("DELETE FROM entries")
        conn.commit()
        _seed_entry()

    def test_insert_and_list(self):
        db.insert_fact(
            fact_id="f_test001",
            fact_text="User prefers pytest over unittest",
            source_entry_id="m_test123",
            entity="pytest",
            fact_type="preference",
            confidence=0.9,
            created_at=time.time(),
        )

        facts, total = db.list_facts()
        assert total == 1
        assert facts[0]["fact_text"] == "User prefers pytest over unittest"
        assert facts[0]["entity"] == "pytest"
        assert facts[0]["fact_type"] == "preference"

    def test_search_fts(self):
        db.insert_fact(
            fact_id="f_test002",
            fact_text="Project uses SQLite FTS5 for memory search",
            source_entry_id="m_test123",
            entity="sqlite",
            fact_type="technical",
            confidence=0.95,
            created_at=time.time(),
        )

        results = db.search_facts_fts("sqlite memory search")
        assert len(results) >= 1
        assert "SQLite" in results[0]["fact_text"]

    def test_supersede_fact(self):
        now = time.time()
        db.insert_fact(
            fact_id="f_old",
            fact_text="User prefers unittest",
            source_entry_id="m_test123",
            entity="testing",
            fact_type="preference",
            confidence=0.8,
            created_at=now - 100,
        )
        db.insert_fact(
            fact_id="f_new",
            fact_text="User prefers pytest",
            source_entry_id="m_test123",
            entity="testing",
            fact_type="preference",
            confidence=0.9,
            created_at=now,
        )

        # Supersede old fact
        result = db.supersede_fact("f_old", "f_new")
        assert result is True

        # Default list should only show active facts
        facts, total = db.list_facts()
        assert total == 1
        assert facts[0]["id"] == "f_new"

        # Including superseded shows both
        facts_all, total_all = db.list_facts(include_superseded=True)
        assert total_all == 2

    def test_delete_facts_for_entry(self):
        db.insert_fact(
            fact_id="f_del1",
            fact_text="Fact one",
            source_entry_id="m_test123",
            entity="test",
            fact_type="observation",
            confidence=0.5,
            created_at=time.time(),
        )
        db.insert_fact(
            fact_id="f_del2",
            fact_text="Fact two",
            source_entry_id="m_test123",
            entity="test",
            fact_type="observation",
            confidence=0.5,
            created_at=time.time(),
        )

        deleted = db.delete_facts_for_entry("m_test123")
        assert deleted == 2
        facts, total = db.list_facts()
        assert total == 0

    def test_find_facts_by_entity(self):
        db.insert_fact(
            fact_id="f_ent1",
            fact_text="Python is the main language",
            source_entry_id="m_test123",
            entity="python",
            fact_type="technical",
            confidence=0.9,
            created_at=time.time(),
        )

        results = db.find_facts_by_entity("python")
        assert len(results) == 1
        assert results[0]["entity"] == "python"

        # Case-insensitive
        results = db.find_facts_by_entity("Python")
        assert len(results) == 1

    def test_filter_by_fact_type(self):
        now = time.time()
        db.insert_fact(
            fact_id="f_type1",
            fact_text="Chose React for frontend",
            source_entry_id="m_test123",
            entity="react",
            fact_type="decision",
            confidence=0.8,
            created_at=now,
        )
        db.insert_fact(
            fact_id="f_type2",
            fact_text="Prefers functional components",
            source_entry_id="m_test123",
            entity="react",
            fact_type="preference",
            confidence=0.7,
            created_at=now,
        )

        decisions, _ = db.list_facts(fact_type="decision")
        assert len(decisions) == 1
        assert decisions[0]["fact_type"] == "decision"

    def test_count_facts(self):
        assert db.count_facts() == 0
        db.insert_fact(
            fact_id="f_cnt1",
            fact_text="A fact",
            source_entry_id="m_test123",
            entity="x",
            fact_type="observation",
            confidence=0.5,
            created_at=time.time(),
        )
        assert db.count_facts() == 1


class TestFactExtraction(unittest.TestCase):
    """Test fact extraction logic."""

    def test_parse_llm_response_valid_json(self):
        response = '''[
            {"fact_text": "User prefers pytest", "entity": "pytest", "fact_type": "preference", "confidence": 0.9}
        ]'''
        facts = _parse_llm_response(response)
        assert len(facts) == 1
        assert facts[0]["fact_text"] == "User prefers pytest"

    def test_parse_llm_response_with_markdown_fences(self):
        response = '''```json
[{"fact_text": "Uses SQLite", "entity": "sqlite", "fact_type": "technical", "confidence": 0.8}]
```'''
        facts = _parse_llm_response(response)
        assert len(facts) == 1

    def test_parse_llm_response_invalid(self):
        facts = _parse_llm_response("This is not JSON at all")
        assert facts == []

    def test_fallback_returns_empty(self):
        """Fallback is disabled — should always return empty list (see #50)."""
        transcript = "We chose pytest over unittest for this project. Also decided on SQLite."
        facts = _extract_fallback(transcript)
        assert facts == []

    def test_fallback_returns_empty_for_preferences(self):
        """Fallback is disabled — preference patterns should not match."""
        transcript = "The user prefers functional programming. They always use type hints."
        facts = _extract_fallback(transcript)
        assert facts == []

    def test_extract_returns_empty_without_llm(self):
        """Without LLM, extraction returns empty list (no fallback)."""
        facts = extract_facts_from_transcript("plain text", source_entry_id="m_test123")
        assert facts == []

    def test_extract_returns_empty_for_decisions_without_llm(self):
        """Decision-like text should not produce facts without LLM."""
        facts = extract_facts_from_transcript(
            "We chose SQLite for storage", source_entry_id="m_test123"
        )
        assert facts == []


class TestStoreFactsWithContradiction(unittest.TestCase):
    """Test fact storage with contradiction detection."""

    def setUp(self):
        conn = db._get_conn()
        conn.execute("DELETE FROM facts")
        conn.execute("DELETE FROM entries")
        conn.commit()
        _seed_entry()

    def test_supersedes_conflicting_facts(self):
        now = time.time()

        # Store an initial fact
        old_facts = [{
            "fact_id": "f_old_pref",
            "fact_text": "User prefers unittest",
            "source_entry_id": "m_test123",
            "entity": "testing",
            "fact_type": "preference",
            "confidence": 0.8,
            "created_at": now - 100,
        }]
        store_facts(old_facts)

        # Store a new conflicting fact
        new_facts = [{
            "fact_id": "f_new_pref",
            "fact_text": "User now prefers pytest",
            "source_entry_id": "m_test123",
            "entity": "testing",
            "fact_type": "preference",
            "confidence": 0.9,
            "created_at": now,
        }]
        store_facts(new_facts)

        # Only the new fact should be active
        active, _ = db.list_facts(include_superseded=False)
        assert len(active) == 1
        assert active[0]["id"] == "f_new_pref"

        # Both should exist when including superseded
        all_facts, _ = db.list_facts(include_superseded=True)
        assert len(all_facts) == 2


class TestFormatFacts(unittest.TestCase):
    """Test fact formatting."""

    def test_format_empty(self):
        assert format_facts([]) == "No facts found."

    def test_format_with_facts(self):
        facts = [{
            "id": "f_001",
            "fact_text": "Uses pytest for testing",
            "entity": "pytest",
            "fact_type": "preference",
            "confidence": 0.9,
            "superseded_by": None,
        }]
        output = format_facts(facts)
        assert "pytest" in output
        assert "preference" in output
        assert "90%" in output


if __name__ == "__main__":
    unittest.main()
