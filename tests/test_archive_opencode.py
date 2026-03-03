"""Tests for archive_opencode_session() — OpenCode session archival."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_EXPORT = os.path.join(FIXTURES_DIR, "opencode_export_sample.json")


class TestArchiveOpencodeSession(unittest.TestCase):
    @patch("rlm.archive.get_project_name", return_value="test-project")
    @patch("rlm.archive.smart_remember")
    @patch("rlm.archive.memory")
    def test_basic_archival(self, mock_memory, mock_smart_remember, mock_proj):
        """Archiving a valid session should call smart_remember with correct params."""
        mock_smart_remember.return_value = {
            "summary_id": "m_test123",
            "tags": ["conversation", "opencode"],
            "facts_count": 2,
        }

        from rlm.archive import archive_opencode_session

        result = archive_opencode_session(SAMPLE_EXPORT, cwd="/tmp/test-project")

        self.assertTrue(result)
        mock_smart_remember.assert_called_once()

        call_kwargs = mock_smart_remember.call_args[1]
        self.assertEqual(call_kwargs["source"], "session")
        self.assertEqual(call_kwargs["source_name"], "opencode:abc123-def456-ghi789")
        self.assertIn("opencode", call_kwargs["user_tags"])
        self.assertIn("conversation", call_kwargs["user_tags"])
        self.assertTrue(call_kwargs["dedup"])
        self.assertIn("OpenCode", call_kwargs["label"])

    @patch("rlm.archive.get_project_name", return_value="my-project")
    @patch("rlm.archive.smart_remember")
    @patch("rlm.archive.memory")
    def test_project_name_from_cwd(self, mock_memory, mock_smart_remember, mock_proj):
        """When cwd is provided, project name should come from get_project_name(cwd)."""
        mock_smart_remember.return_value = {
            "summary_id": "m_test", "tags": [], "facts_count": 0,
        }

        from rlm.archive import archive_opencode_session

        archive_opencode_session(SAMPLE_EXPORT, cwd="/tmp/my-project")

        # get_project_name called with the cwd
        mock_proj.assert_called_with(cwd="/tmp/my-project")

        call_kwargs = mock_smart_remember.call_args[1]
        self.assertIn("my-project", call_kwargs["user_tags"])

    @patch("rlm.archive.get_project_name", return_value="my-app")
    @patch("rlm.archive.smart_remember")
    @patch("rlm.archive.memory")
    def test_project_name_from_json_directory(self, mock_memory, mock_smart_remember, mock_proj):
        """When no cwd, project name should come from JSON info.directory."""
        mock_smart_remember.return_value = {
            "summary_id": "m_test", "tags": [], "facts_count": 0,
        }

        from rlm.archive import archive_opencode_session

        archive_opencode_session(SAMPLE_EXPORT, cwd=None)

        # get_project_name called with the JSON directory
        mock_proj.assert_called_with(cwd="/Users/dev/projects/my-app")

        call_kwargs = mock_smart_remember.call_args[1]
        self.assertIn("my-app", call_kwargs["user_tags"])

    @patch("rlm.archive.get_project_name", return_value="unknown")
    @patch("rlm.archive.smart_remember")
    @patch("rlm.archive.memory")
    def test_empty_session_skipped(self, mock_memory, mock_smart_remember, mock_proj):
        """Empty session (no messages) should return False."""
        data = {"info": {"id": "empty-session"}, "messages": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            json_path = f.name

        from rlm.archive import archive_opencode_session

        try:
            result = archive_opencode_session(json_path)
            self.assertFalse(result)
            mock_smart_remember.assert_not_called()
        finally:
            os.unlink(json_path)

    @patch("rlm.archive.smart_remember")
    @patch("rlm.archive.memory")
    def test_no_session_id_skipped(self, mock_memory, mock_smart_remember):
        """Session without an ID should return False."""
        data = {
            "info": {},
            "messages": [
                {"info": {"role": "user", "time": {"created": 1709500000000}},
                 "parts": [{"type": "text", "content": "hello"}]},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            json_path = f.name

        from rlm.archive import archive_opencode_session

        try:
            result = archive_opencode_session(json_path)
            self.assertFalse(result)
            mock_smart_remember.assert_not_called()
        finally:
            os.unlink(json_path)

    @patch("rlm.archive.get_project_name", return_value="my-app")
    @patch("rlm.archive.smart_remember")
    @patch("rlm.archive.memory")
    def test_dedup_uses_session_id(self, mock_memory, mock_smart_remember, mock_proj):
        """Archiving twice with same session ID should use dedup=True."""
        mock_smart_remember.return_value = {
            "summary_id": "m_first", "tags": [], "facts_count": 0,
        }

        from rlm.archive import archive_opencode_session

        archive_opencode_session(SAMPLE_EXPORT)
        archive_opencode_session(SAMPLE_EXPORT)

        # Both calls should use dedup=True
        for call in mock_smart_remember.call_args_list:
            self.assertTrue(call[1]["dedup"])
            self.assertEqual(call[1]["source_name"], "opencode:abc123-def456-ghi789")

    @patch("rlm.archive.get_project_name", return_value="my-app")
    @patch("rlm.archive.smart_remember")
    @patch("rlm.archive.memory")
    def test_transcript_passed_to_smart_remember(self, mock_memory, mock_smart_remember, mock_proj):
        """The compressed transcript content should be passed to smart_remember."""
        mock_smart_remember.return_value = {
            "summary_id": "m_test", "tags": [], "facts_count": 0,
        }

        from rlm.archive import archive_opencode_session

        archive_opencode_session(SAMPLE_EXPORT)

        call_kwargs = mock_smart_remember.call_args[1]
        content = call_kwargs["content"]
        # Should contain the compressed transcript
        self.assertIn("Session Transcript", content)
        self.assertIn("authentication bug", content)


if __name__ == "__main__":
    unittest.main()
