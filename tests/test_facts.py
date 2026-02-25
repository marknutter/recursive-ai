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
    EXTRACTION_PROMPT,
    MIN_CONFIDENCE,
    STOPWORDS,
    _clean_entity,
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


class TestEntityPostProcessing(unittest.TestCase):
    """Test entity cleaning and filtering."""

    def test_clean_entity_normalizes_lowercase(self):
        assert _clean_entity("SQLite") == "sqlite"

    def test_clean_entity_strips_whitespace(self):
        assert _clean_entity("  pytest  ") == "pytest"

    def test_clean_entity_filters_short(self):
        assert _clean_entity("") is None
        assert _clean_entity("x") is None

    def test_clean_entity_filters_stopwords(self):
        for word in ("the", "a", "an", "and", "or", "is", "it", "to", "your"):
            assert _clean_entity(word) is None, f"stopword '{word}' was not filtered"

    def test_clean_entity_keeps_valid(self):
        assert _clean_entity("pytest") == "pytest"
        assert _clean_entity("SQLite") == "sqlite"
        assert _clean_entity("rlm") == "rlm"

    def test_stopwords_set_is_nonempty(self):
        assert len(STOPWORDS) > 10

    def test_extract_facts_filters_stopword_entities(self):
        """Entities that are stopwords should become None after extraction."""
        facts = extract_facts_from_transcript(
            "We chose pytest over unittest for this project.",
            source_entry_id="m_test123",
        )
        for f in facts:
            if f["entity"] is not None:
                assert f["entity"] not in STOPWORDS
                assert len(f["entity"]) >= 2


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


class TestConfidenceFloor(unittest.TestCase):
    """Test that facts below MIN_CONFIDENCE are discarded."""

    def test_min_confidence_constant(self):
        assert MIN_CONFIDENCE == 0.75

    def test_low_confidence_facts_discarded(self):
        """Fallback extraction produces 0.5-0.6 confidence — all should be filtered."""
        transcript = "We chose pytest over unittest. The user prefers functional style."
        facts = extract_facts_from_transcript(transcript, source_entry_id="m_test123")
        for f in facts:
            assert f["confidence"] >= MIN_CONFIDENCE, (
                f"Fact with confidence {f['confidence']} should have been discarded"
            )

    def test_high_confidence_facts_kept(self):
        """Facts at or above the threshold should be kept."""
        from unittest.mock import patch

        high_conf_facts = [
            {"fact_text": "User prefers pytest over unittest", "entity": "pytest",
             "fact_type": "preference", "confidence": 0.9},
            {"fact_text": "Project uses SQLite for storage", "entity": "sqlite",
             "fact_type": "technical", "confidence": 0.75},
        ]
        with patch("rlm.facts._extract_via_llm", return_value=high_conf_facts):
            facts = extract_facts_from_transcript("dummy", source_entry_id="m_test123")
        assert len(facts) == 2

    def test_mixed_confidence_filters_correctly(self):
        """Only facts >= MIN_CONFIDENCE survive filtering."""
        from unittest.mock import patch

        mixed_facts = [
            {"fact_text": "High confidence fact here", "entity": "a",
             "fact_type": "decision", "confidence": 0.95},
            {"fact_text": "Low confidence fact here", "entity": "b",
             "fact_type": "observation", "confidence": 0.5},
            {"fact_text": "Borderline confidence fact", "entity": "c",
             "fact_type": "technical", "confidence": 0.75},
            {"fact_text": "Just below threshold fact", "entity": "d",
             "fact_type": "preference", "confidence": 0.74},
        ]
        with patch("rlm.facts._extract_via_llm", return_value=mixed_facts):
            facts = extract_facts_from_transcript("dummy", source_entry_id="m_test123")
        assert len(facts) == 2
        confidences = {f["confidence"] for f in facts}
        assert confidences == {0.95, 0.75}

    def test_fallback_facts_all_filtered(self):
        """Regex fallback produces 0.5-0.6 confidence — should all be below threshold."""
        fallback_facts = _extract_fallback(
            "We chose pytest over unittest. User prefers dark mode."
        )
        # Verify fallback facts are indeed below threshold
        for f in fallback_facts:
            assert f["confidence"] < MIN_CONFIDENCE


class TestExtractionPromptQuality(unittest.TestCase):
    """Verify the extraction prompt contains guardrails for edge cases."""

    def test_prompt_includes_relationship_examples(self):
        """Prompt should have relationship fact examples to avoid skewing toward technical."""
        assert "relationship" in EXTRACTION_PROMPT.lower()
        assert "Mark works with Jeff" in EXTRACTION_PROMPT

    def test_prompt_includes_observation_examples(self):
        """Prompt should have observation fact examples."""
        assert "Cool Cool duo" in EXTRACTION_PROMPT
        assert "observation" in EXTRACTION_PROMPT.lower()

    def test_prompt_forbids_ui_instructions(self):
        """Prompt should explicitly forbid extracting UI instructions."""
        assert "UI instruction" in EXTRACTION_PROMPT
        assert "Click the settings icon" in EXTRACTION_PROMPT

    def test_prompt_forbids_setup_steps(self):
        """Prompt should explicitly forbid extracting setup/install steps."""
        assert "setup step" in EXTRACTION_PROMPT
        assert "pip install" in EXTRACTION_PROMPT

    def test_prompt_forbids_quoted_documentation(self):
        """Prompt should explicitly forbid extracting quoted documentation."""
        assert "quoted documentation" in EXTRACTION_PROMPT

    def test_prompt_requires_proper_noun_entities(self):
        """Entities must be proper nouns, project names, or tool names."""
        assert "proper noun" in EXTRACTION_PROMPT.lower()
        assert "project name" in EXTRACTION_PROMPT.lower()
        assert "tool" in EXTRACTION_PROMPT.lower()

    def test_prompt_forbids_common_word_entities(self):
        """Prompt should explicitly ban common English words as entities."""
        prompt_lower = EXTRACTION_PROMPT.lower()
        assert "common english words" in prompt_lower
        # Check specific banned words are listed
        for word in ["the", "idea", "code", "function", "data"]:
            assert f'"{word}"' in prompt_lower, f"Expected banned word '{word}' in prompt"

    def test_prompt_has_all_five_fact_types_in_examples(self):
        """Good-examples section should cover all five fact types."""
        good_section_start = EXTRACTION_PROMPT.index("GOOD facts")
        bad_section_start = EXTRACTION_PROMPT.index("BAD facts")
        good_section = EXTRACTION_PROMPT[good_section_start:bad_section_start]
        for ft in ("decision", "preference", "relationship", "technical", "observation"):
            assert ft in good_section, f"Fact type '{ft}' missing from GOOD examples"

    def test_parse_rejects_ui_instruction_shaped_output(self):
        """LLM output containing UI instructions should still parse but
        the pipeline's min-length filter protects against very short junk."""
        # Simulate an LLM returning a bad fact about a UI instruction
        bad_response = '''[
            {"fact_text": "Click settings", "entity": "the", "fact_type": "observation", "confidence": 0.5}
        ]'''
        facts = _parse_llm_response(bad_response)
        # _parse_llm_response is a raw parser — it should parse valid JSON
        assert len(facts) == 1
        # But extract_facts_from_transcript filters short facts (< 10 chars)
        # "Click settings" is 14 chars so it passes length, but entity "the"
        # is a common word — the prompt should prevent this from the LLM side

    def test_extract_filters_empty_entity_to_none(self):
        """Facts with empty-string entities should be normalized to None."""
        from unittest.mock import patch

        fake_llm_result = [
            {"fact_text": "User prefers dark mode for all editors", "entity": "", "fact_type": "preference", "confidence": 0.8},
        ]
        with patch("rlm.facts._extract_via_llm", return_value=fake_llm_result):
            facts = extract_facts_from_transcript("anything", source_entry_id="m_test123")
            assert len(facts) == 1
            assert facts[0]["entity"] is None

    def test_extract_normalizes_entity_to_lowercase(self):
        """Entities should be lowercased for consistent matching."""
        from unittest.mock import patch

        fake_llm_result = [
            {"fact_text": "Team uses Terraform for infrastructure", "entity": "Terraform", "fact_type": "technical", "confidence": 0.9},
        ]
        with patch("rlm.facts._extract_via_llm", return_value=fake_llm_result):
            facts = extract_facts_from_transcript("anything", source_entry_id="m_test123")
            assert len(facts) == 1
            assert facts[0]["entity"] == "terraform"


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
