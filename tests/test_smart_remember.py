"""Tests for the smart_remember() pipeline and its integration into cmd_remember."""

import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Use a temporary database for tests
_test_db_dir = tempfile.mkdtemp(prefix="rlm-test-smart-")
os.environ.setdefault("RLM_MEMORY_DIR", _test_db_dir)

import rlm.db as db_mod
db_mod.MEMORY_DIR = _test_db_dir
db_mod.DB_PATH = os.path.join(_test_db_dir, "memory.db")

from rlm import db, memory
from rlm.archive import smart_remember, SUMMARY_THRESHOLD


def _make_args(**kwargs):
    """Build an argparse.Namespace with remember defaults."""
    defaults = {
        "content": None,
        "file": None,
        "url": None,
        "stdin": False,
        "tags": None,
        "summary": None,
        "depth": 2,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _clean_db():
    """Remove all entries and facts for a fresh test."""
    conn = db._get_conn()
    conn.execute("DELETE FROM facts")
    conn.execute("DELETE FROM entries")
    conn.commit()


class TestSmartRememberSmallContent(unittest.TestCase):
    """Test smart_remember with content below SUMMARY_THRESHOLD (single entry)."""

    def setUp(self):
        _clean_db()

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=["python", "testing"])
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_small_content_single_entry(self, mock_facts, mock_tags):
        """Small content creates one entry, not two-tier."""
        result = smart_remember(
            content="Short text to remember",
            source="text",
        )

        self.assertIn("summary_id", result)
        self.assertNotIn("content_id", result)
        self.assertIn("python", result["tags"])
        self.assertIn("testing", result["tags"])

        # Verify single entry in DB
        entries, total = db.list_all_entries()
        self.assertEqual(total, 1)

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=["debug"])
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_user_tags_combined_with_semantic(self, mock_facts, mock_tags):
        """User-provided tags and semantic tags should both appear."""
        result = smart_remember(
            content="Some content about debugging",
            source="text",
            user_tags=["manual-tag", "project-x"],
        )

        self.assertIn("manual-tag", result["tags"])
        self.assertIn("project-x", result["tags"])
        self.assertIn("debug", result["tags"])

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_label_used_as_summary(self, mock_facts, mock_tags):
        """A provided label should be used as the entry summary."""
        result = smart_remember(
            content="Content here",
            source="text",
            label="My custom label",
        )

        entry = db.get_entry(result["summary_id"])
        self.assertIn("My custom label", entry["summary"])


class TestSmartRememberLargeContent(unittest.TestCase):
    """Test smart_remember with content above SUMMARY_THRESHOLD (two-tier)."""

    def setUp(self):
        _clean_db()

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=["architecture"])
    @patch("rlm.summarize.generate_summary", return_value="Generated summary text.")
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_large_content_two_entries(self, mock_facts, mock_summary, mock_tags):
        """Content above threshold creates both summary and full-content entries."""
        large = "x" * (SUMMARY_THRESHOLD + 100)
        result = smart_remember(content=large, source="file")

        self.assertIn("summary_id", result)
        self.assertIn("content_id", result)

        # Two entries in DB
        entries, total = db.list_all_entries()
        self.assertEqual(total, 2)

        # Summary entry has the right source
        summary_entry = db.get_entry(result["summary_id"])
        self.assertEqual(summary_entry["source"], "file-summary")
        self.assertIn("summary", summary_entry["tags"])

        # Content entry has the original source
        content_entry = db.get_entry(result["content_id"])
        self.assertEqual(content_entry["source"], "file")
        self.assertIn("full-content", content_entry["tags"])

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    @patch("rlm.summarize.generate_summary", return_value="A summary.")
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_summary_generation_called_for_large(self, mock_facts, mock_summary, mock_tags):
        """generate_summary should be called for large content."""
        large = "y" * (SUMMARY_THRESHOLD + 1)
        smart_remember(content=large, source="test")
        mock_summary.assert_called_once()

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_summary_not_called_for_small(self, mock_facts, mock_tags):
        """generate_summary should NOT be called for small content."""
        with patch("rlm.summarize.generate_summary") as mock_summary:
            smart_remember(content="small", source="test")
            mock_summary.assert_not_called()


class TestSmartRememberDedup(unittest.TestCase):
    """Test source_name-based deduplication."""

    def setUp(self):
        _clean_db()

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_dedup_replaces_existing(self, mock_facts, mock_tags):
        """With dedup=True, existing entries with same source_name are replaced."""
        # First store
        smart_remember(
            content="version 1",
            source="file",
            source_name="/path/to/file.md",
            dedup=True,
        )
        entries1, total1 = db.list_all_entries()
        self.assertEqual(total1, 1)

        # Second store with same source_name
        smart_remember(
            content="version 2",
            source="file",
            source_name="/path/to/file.md",
            dedup=True,
        )
        entries2, total2 = db.list_all_entries()
        self.assertEqual(total2, 1)  # Still one entry, old was replaced

        # Content should be updated
        entry = db.get_entry(entries2[0]["id"])
        self.assertEqual(entry["content"], "version 2")

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_no_dedup_adds_new(self, mock_facts, mock_tags):
        """With dedup=False, new entries are added alongside existing."""
        smart_remember(
            content="version 1",
            source="file",
            source_name="/path/to/file.md",
            dedup=False,
        )
        smart_remember(
            content="version 2",
            source="file",
            source_name="/path/to/file.md",
            dedup=False,
        )
        _, total = db.list_all_entries()
        self.assertEqual(total, 2)


class TestSmartRememberFacts(unittest.TestCase):
    """Test that facts extraction runs and stores facts."""

    def setUp(self):
        _clean_db()

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    def test_facts_extracted_and_stored(self, mock_tags):
        """Facts from the content should be stored in the DB."""
        content = "We chose pytest over unittest for this project. Also decided on SQLite."
        # Use real fallback extraction (no LLM in tests)
        result = smart_remember(content=content, source="text")

        # Should have at least attempted facts extraction
        self.assertIn("facts_count", result)

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    @patch("rlm.facts.extract_facts_from_transcript", side_effect=Exception("LLM down"))
    def test_facts_failure_nonfatal(self, mock_facts, mock_tags):
        """Facts extraction failure should not prevent storage."""
        result = smart_remember(content="Some content", source="text")

        # Entry should still be created
        self.assertIn("summary_id", result)
        entry = db.get_entry(result["summary_id"])
        self.assertIsNotNone(entry)


class TestSmartRememberFallback(unittest.TestCase):
    """Test graceful fallback when LLM is unavailable."""

    def setUp(self):
        _clean_db()

    @patch("rlm.semantic_tags.extract_semantic_tags", return_value=[])
    @patch("rlm.facts.extract_facts_from_transcript", return_value=[])
    def test_no_semantic_tags_still_stores(self, mock_facts, mock_tags):
        """Content should be stored even if semantic tag extraction returns empty."""
        result = smart_remember(content="Plain text", source="text")

        self.assertIn("summary_id", result)
        entry = db.get_entry(result["summary_id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["content"], "Plain text")


class TestCmdRememberSmartPipeline(unittest.TestCase):
    """Test that cmd_remember routes all paths through smart_remember."""

    def setUp(self):
        _clean_db()

    @patch("rlm.cli.archive.smart_remember")
    def test_text_routes_through_smart(self, mock_sr):
        """Positional text should go through smart_remember."""
        from rlm.cli import cmd_remember

        mock_sr.return_value = {
            "summary_id": "m_test1",
            "summary": "test",
            "tags": ["a"],
            "facts_count": 0,
        }
        with patch("builtins.print"):
            cmd_remember(_make_args(content="remember this"))

        mock_sr.assert_called_once()
        _, kwargs = mock_sr.call_args
        self.assertEqual(kwargs["source"], "text")
        self.assertEqual(kwargs["content"], "remember this")

    @patch("rlm.cli.archive.smart_remember")
    def test_file_routes_through_smart(self, mock_sr):
        """--file should go through smart_remember."""
        from rlm.cli import cmd_remember

        mock_sr.return_value = {
            "summary_id": "m_test2",
            "summary": "file test",
            "tags": ["b"],
            "facts_count": 0,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("File content here")
            tmpfile = f.name

        try:
            with patch("builtins.print"):
                cmd_remember(_make_args(file=tmpfile))

            mock_sr.assert_called_once()
            _, kwargs = mock_sr.call_args
            self.assertEqual(kwargs["source"], "file")
            self.assertEqual(kwargs["source_name"], tmpfile)
            self.assertTrue(kwargs["dedup"])
        finally:
            os.unlink(tmpfile)

    @patch("rlm.cli.archive.smart_remember")
    def test_stdin_routes_through_smart(self, mock_sr):
        """--stdin should go through smart_remember."""
        from rlm.cli import cmd_remember

        mock_sr.return_value = {
            "summary_id": "m_test3",
            "summary": "stdin test",
            "tags": ["c"],
            "facts_count": 0,
        }

        with patch("sys.stdin") as mock_stdin, patch("builtins.print"):
            mock_stdin.read.return_value = "piped content"
            cmd_remember(_make_args(stdin=True))

        mock_sr.assert_called_once()
        _, kwargs = mock_sr.call_args
        self.assertEqual(kwargs["source"], "stdin")
        self.assertEqual(kwargs["content"], "piped content")

    @patch("rlm.cli.archive.smart_remember")
    @patch("rlm.cli.export.export_session")
    def test_jsonl_file_exports_then_smart(self, mock_export, mock_sr):
        """--file with .jsonl should run export-session then smart_remember."""
        from rlm.cli import cmd_remember

        mock_export.return_value = "exported transcript content"
        mock_sr.return_value = {
            "summary_id": "m_test4",
            "summary": "session",
            "tags": ["d"],
            "facts_count": 0,
        }

        # Create a dummy .jsonl file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"human"}\n')
            tmpfile = f.name

        try:
            with patch("builtins.print"):
                cmd_remember(_make_args(file=tmpfile))

            mock_export.assert_called_once_with(tmpfile)
            mock_sr.assert_called_once()
            _, kwargs = mock_sr.call_args
            self.assertEqual(kwargs["content"], "exported transcript content")
            self.assertEqual(kwargs["source"], "file")
        finally:
            os.unlink(tmpfile)

    @patch("rlm.cli.url_fetcher.fetch_url")
    @patch("rlm.cli.archive.smart_remember")
    def test_url_routes_through_smart(self, mock_sr, mock_fetch):
        """--url should fetch then route through smart_remember."""
        from rlm.cli import cmd_remember

        mock_fetch.return_value = ("Page content here", "html")
        mock_sr.return_value = {
            "summary_id": "m_test5",
            "summary": "url test",
            "tags": ["e"],
            "facts_count": 0,
        }

        with patch("builtins.print"):
            cmd_remember(_make_args(url="https://example.com/docs"))

        mock_fetch.assert_called_once_with("https://example.com/docs")
        mock_sr.assert_called_once()
        _, kwargs = mock_sr.call_args
        self.assertEqual(kwargs["content"], "Page content here")
        self.assertEqual(kwargs["source"], "url")
        self.assertTrue(kwargs["dedup"])

    def test_user_tags_passed_through(self):
        """User-provided --tags should be passed to smart_remember."""
        from rlm.cli import cmd_remember

        with patch("rlm.cli.archive.smart_remember") as mock_sr, \
             patch("builtins.print"):
            mock_sr.return_value = {
                "summary_id": "m_test6",
                "summary": "tag test",
                "tags": ["foo", "bar"],
                "facts_count": 0,
            }
            cmd_remember(_make_args(content="tagged content", tags="foo,bar"))

            _, kwargs = mock_sr.call_args
            self.assertEqual(kwargs["user_tags"], ["foo", "bar"])


class TestSmartRememberWithRealFallback(unittest.TestCase):
    """Integration test: smart_remember with real fallback extractors (no LLM)."""

    def setUp(self):
        _clean_db()

    def test_end_to_end_small_content(self):
        """Full pipeline with small content — uses keyword fallback for tags."""
        result = smart_remember(
            content="We chose pytest over unittest for testing. The database uses sqlite.",
            source="text",
        )

        self.assertIn("summary_id", result)
        self.assertIsInstance(result["tags"], list)
        entry = db.get_entry(result["summary_id"])
        self.assertIsNotNone(entry)

    def test_end_to_end_large_content(self):
        """Full pipeline with large content — generates summary + content entries."""
        large = "We chose pytest for this project.\n" * 500  # ~16.5K chars
        result = smart_remember(content=large, source="file", source_name="test.md")

        self.assertIn("summary_id", result)
        self.assertIn("content_id", result)

        # Both entries should exist
        summary = db.get_entry(result["summary_id"])
        content = db.get_entry(result["content_id"])
        self.assertIsNotNone(summary)
        self.assertIsNotNone(content)


if __name__ == "__main__":
    unittest.main()
