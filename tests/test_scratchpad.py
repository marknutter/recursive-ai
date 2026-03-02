"""Tests for the scratchpad module — short-lived working memory."""

import os
import tempfile
import time
import unittest

# Use a temporary database for all tests (must be set before rlm.db is imported)
_test_db_dir = tempfile.mkdtemp(prefix="rlm-test-scratchpad-")
os.environ.setdefault("RLM_MEMORY_DIR", _test_db_dir)

import rlm.db as db_mod

db_mod.MEMORY_DIR = _test_db_dir
db_mod.DB_PATH = os.path.join(_test_db_dir, "memory.db")

from rlm import db, scratchpad


class TestScratchpadDBOperations(unittest.TestCase):
    """Test scratchpad table CRUD via db module."""

    def setUp(self):
        conn = db._get_conn()
        conn.execute("DELETE FROM scratchpad")
        conn.commit()

    def test_insert_and_get(self):
        now = time.time()
        db.insert_scratchpad(
            entry_id="scratch-test001",
            label="Auth scan findings",
            content="Found 3 issues in auth module.",
            tags=["security", "auth"],
            created_at=now,
            expires_at=now + 3600,
            analysis_session="sess-abc",
        )
        entry = db.get_scratchpad_entry("scratch-test001")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], "scratch-test001")
        self.assertEqual(entry["label"], "Auth scan findings")
        self.assertEqual(entry["content"], "Found 3 issues in auth module.")
        self.assertEqual(entry["tags"], ["security", "auth"])
        self.assertEqual(entry["analysis_session"], "sess-abc")

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(db.get_scratchpad_entry("scratch-doesnotexist"))

    def test_delete_entry(self):
        now = time.time()
        db.insert_scratchpad(
            entry_id="scratch-del01",
            label="Delete me",
            content="temp content",
            tags=[],
            created_at=now,
            expires_at=now + 3600,
        )
        self.assertTrue(db.delete_scratchpad_entry("scratch-del01"))
        self.assertIsNone(db.get_scratchpad_entry("scratch-del01"))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(db.delete_scratchpad_entry("scratch-ghost"))

    def test_list_excludes_expired_by_default(self):
        now = time.time()
        db.insert_scratchpad(
            entry_id="scratch-active",
            label="Active",
            content="active content",
            tags=[],
            created_at=now,
            expires_at=now + 3600,
        )
        db.insert_scratchpad(
            entry_id="scratch-expired",
            label="Expired",
            content="expired content",
            tags=[],
            created_at=now - 7200,
            expires_at=now - 3600,  # already expired
        )
        entries = db.list_scratchpad_entries(include_expired=False)
        ids = [e["id"] for e in entries]
        self.assertIn("scratch-active", ids)
        self.assertNotIn("scratch-expired", ids)

    def test_list_include_expired(self):
        now = time.time()
        db.insert_scratchpad(
            entry_id="scratch-active2",
            label="Active",
            content="active",
            tags=[],
            created_at=now,
            expires_at=now + 3600,
        )
        db.insert_scratchpad(
            entry_id="scratch-expired2",
            label="Expired",
            content="expired",
            tags=[],
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        entries = db.list_scratchpad_entries(include_expired=True)
        ids = [e["id"] for e in entries]
        self.assertIn("scratch-active2", ids)
        self.assertIn("scratch-expired2", ids)

    def test_clear_all(self):
        now = time.time()
        for i in range(3):
            db.insert_scratchpad(
                entry_id=f"scratch-clr{i}",
                label=f"Entry {i}",
                content="content",
                tags=[],
                created_at=now,
                expires_at=now + 3600,
            )
        deleted = db.clear_scratchpad(expired_only=False)
        self.assertEqual(deleted, 3)
        self.assertEqual(len(db.list_scratchpad_entries(include_expired=True)), 0)

    def test_clear_expired_only(self):
        now = time.time()
        db.insert_scratchpad(
            entry_id="scratch-keep",
            label="Keep",
            content="keep",
            tags=[],
            created_at=now,
            expires_at=now + 3600,
        )
        db.insert_scratchpad(
            entry_id="scratch-prune",
            label="Prune",
            content="prune",
            tags=[],
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        deleted = db.clear_scratchpad(expired_only=True)
        self.assertEqual(deleted, 1)
        remaining = db.list_scratchpad_entries(include_expired=True)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], "scratch-keep")

    def test_tags_round_trip(self):
        now = time.time()
        tags = ["analysis", "security", "in-progress"]
        db.insert_scratchpad(
            entry_id="scratch-tags",
            label="Tag test",
            content="content",
            tags=tags,
            created_at=now,
            expires_at=now + 3600,
        )
        entry = db.get_scratchpad_entry("scratch-tags")
        self.assertEqual(entry["tags"], tags)


class TestScratchpadHighLevel(unittest.TestCase):
    """Test scratchpad module API (save, get, list_entries, clear, promote)."""

    def setUp(self):
        conn = db._get_conn()
        conn.execute("DELETE FROM scratchpad")
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM facts")
        conn.commit()

    def test_save_returns_metadata(self):
        result = scratchpad.save(
            "Intermediate finding: 3 auth bugs",
            label="auth-scan-step1",
            tags=["auth", "security"],
            ttl_hours=12,
        )
        self.assertIn("id", result)
        self.assertTrue(result["id"].startswith("scratch-"))
        self.assertEqual(result["label"], "auth-scan-step1")
        self.assertEqual(result["tags"], ["auth", "security"])
        self.assertEqual(result["ttl_hours"], 12)
        self.assertGreater(result["expires_at"], result["created_at"])
        self.assertAlmostEqual(
            result["expires_at"] - result["created_at"], 12 * 3600, delta=5
        )

    def test_save_auto_label_from_content(self):
        result = scratchpad.save("Found SQL injection vulnerability in user login form")
        # When label not provided, returned dict has empty label (input passthrough),
        # but the stored DB entry derives label from content[:60]
        self.assertEqual(result["label"], "")
        entry = scratchpad.get(result["id"])
        self.assertIn("Found SQL injection", entry["label"])

    def test_get_returns_full_entry(self):
        saved = scratchpad.save("Full content here", label="test-get")
        entry = scratchpad.get(saved["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["content"], "Full content here")
        self.assertEqual(entry["label"], "test-get")

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(scratchpad.get("scratch-doesnotexist"))

    def test_list_entries_active_only(self):
        scratchpad.save("Active entry", label="active", ttl_hours=24)
        # Insert an already-expired entry directly via db
        now = time.time()
        db.insert_scratchpad(
            entry_id="scratch-oldexp",
            label="Expired entry",
            content="old content",
            tags=[],
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        entries = scratchpad.list_entries(include_expired=False)
        labels = [e["label"] for e in entries]
        self.assertIn("active", labels)
        self.assertNotIn("Expired entry", labels)

    def test_clear_all(self):
        scratchpad.save("entry 1", ttl_hours=1)
        scratchpad.save("entry 2", ttl_hours=2)
        n = scratchpad.clear(expired_only=False)
        self.assertEqual(n, 2)
        self.assertEqual(scratchpad.list_entries(include_expired=True), [])

    def test_clear_expired_only(self):
        scratchpad.save("keep this", ttl_hours=24)
        now = time.time()
        db.insert_scratchpad(
            entry_id="scratch-xexp",
            label="Expired",
            content="expired",
            tags=[],
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        n = scratchpad.clear(expired_only=True)
        self.assertEqual(n, 1)
        remaining = scratchpad.list_entries(include_expired=True)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["label"], "keep this")

    def test_default_ttl_is_24h(self):
        result = scratchpad.save("content with default ttl")
        self.assertEqual(result["ttl_hours"], 24)
        self.assertAlmostEqual(
            result["expires_at"] - result["created_at"], 24 * 3600, delta=5
        )

    def test_analysis_session_association(self):
        result = scratchpad.save(
            "Session finding", analysis_session="rlm-sess-xyz"
        )
        entry = scratchpad.get(result["id"])
        self.assertEqual(entry["analysis_session"], "rlm-sess-xyz")

    def test_promote_moves_to_long_term_memory(self):
        saved = scratchpad.save(
            "Important: we decided to use SQLite for storage.",
            label="arch-decision",
            tags=["architecture"],
        )
        entry_id = saved["id"]

        # Promote with additional tags
        mem_entry = scratchpad.promote(entry_id, tags=["promoted"])

        self.assertIsNotNone(mem_entry)
        # Should be in long-term memory
        long_term = db.get_entry(mem_entry["id"])
        self.assertIsNotNone(long_term)
        self.assertIn("architecture", long_term["tags"])
        self.assertIn("scratchpad", long_term["tags"])
        self.assertIn("promoted", long_term["tags"])

        # Should be removed from scratchpad
        self.assertIsNone(scratchpad.get(entry_id))

    def test_promote_nonexistent_returns_none(self):
        result = scratchpad.promote("scratch-ghost")
        self.assertIsNone(result)

    def test_promote_uses_custom_summary(self):
        saved = scratchpad.save("Long detailed analysis content...", label="orig-label")
        mem_entry = scratchpad.promote(saved["id"], summary="Custom memory summary")
        long_term = db.get_entry(mem_entry["id"])
        self.assertEqual(long_term["summary"], "Custom memory summary")

    def test_promote_merges_tags_without_duplicates(self):
        saved = scratchpad.save("content", tags=["alpha", "beta"])
        mem_entry = scratchpad.promote(saved["id"], tags=["beta", "gamma"])
        long_term = db.get_entry(mem_entry["id"])
        tags = long_term["tags"]
        # beta should only appear once
        self.assertEqual(tags.count("beta"), 1)
        self.assertIn("alpha", tags)
        self.assertIn("gamma", tags)


class TestScratchpadFormatting(unittest.TestCase):
    """Test format_entry_list and format_entry output."""

    def test_format_entry_list_empty(self):
        output = scratchpad.format_entry_list([])
        self.assertEqual(output, "No scratchpad entries.")

    def test_format_entry_list_shows_count(self):
        now = time.time()
        entries = [
            {
                "id": "scratch-aaa",
                "label": "First entry",
                "tags": ["foo"],
                "content": "some content",
                "created_at": now,
                "expires_at": now + 3600,
                "analysis_session": None,
            },
            {
                "id": "scratch-bbb",
                "label": "Second entry",
                "tags": [],
                "content": "more content",
                "created_at": now,
                "expires_at": now + 7200,
                "analysis_session": "sess-1",
            },
        ]
        output = scratchpad.format_entry_list(entries)
        self.assertIn("2", output)
        self.assertIn("scratch-aaa", output)
        self.assertIn("scratch-bbb", output)
        self.assertIn("First entry", output)

    def test_format_entry_shows_expired(self):
        now = time.time()
        entry = {
            "id": "scratch-exp",
            "label": "Old entry",
            "tags": [],
            "content": "old",
            "created_at": now - 7200,
            "expires_at": now - 1,
        }
        output = scratchpad.format_entry_list([entry])
        self.assertIn("EXPIRED", output)

    def test_format_entry_full(self):
        now = time.time()
        entry = {
            "id": "scratch-full",
            "label": "Full test",
            "tags": ["a", "b"],
            "content": "The actual content text.",
            "created_at": now,
            "expires_at": now + 3600,
            "analysis_session": "sess-xyz",
        }
        output = scratchpad.format_entry(entry)
        self.assertIn("scratch-full", output)
        self.assertIn("Full test", output)
        self.assertIn("a, b", output)
        self.assertIn("sess-xyz", output)
        self.assertIn("The actual content text.", output)
