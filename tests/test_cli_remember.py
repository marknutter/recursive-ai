"""Tests for `rlm remember` no-args session archival path."""

import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Use a temporary database for tests
_test_db_dir = tempfile.mkdtemp(prefix="rlm-test-remember-")
os.environ.setdefault("RLM_MEMORY_DIR", _test_db_dir)

import rlm.db as db_mod
db_mod.MEMORY_DIR = _test_db_dir
db_mod.DB_PATH = os.path.join(_test_db_dir, "memory.db")

from rlm.cli import cmd_remember


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


class TestRememberNoArgs(unittest.TestCase):
    """Test the no-args path that archives the active session."""

    @patch("rlm.cli.archive")
    def test_no_args_calls_archive_session(self, mock_archive):
        """No args should find and archive the active session."""
        fake_path = Path("/tmp/fake-session.jsonl")
        mock_archive.get_session_file.return_value = fake_path
        mock_archive.archive_session.return_value = True

        with patch("builtins.print") as mock_print:
            cmd_remember(_make_args())

        mock_archive.get_session_file.assert_called_once()
        mock_archive.archive_session.assert_called_once_with(
            fake_path, hook_name="Manual", cwd=os.getcwd(),
        )
        output = mock_print.call_args[0][0]
        assert "Session archived" in output

    @patch("rlm.cli.archive")
    def test_no_args_already_archived(self, mock_archive):
        """When dedup kicks in, should print 'already archived'."""
        fake_path = Path("/tmp/fake-session.jsonl")
        mock_archive.get_session_file.return_value = fake_path
        mock_archive.archive_session.return_value = False

        with patch("builtins.print") as mock_print:
            cmd_remember(_make_args())

        output = mock_print.call_args[0][0]
        assert "already archived" in output.lower()

    @patch("rlm.cli.archive")
    def test_no_args_no_session_file(self, mock_archive):
        """When no active session exists, should print error and exit."""
        mock_archive.get_session_file.return_value = None

        with patch("builtins.print"), self.assertRaises(SystemExit) as ctx:
            cmd_remember(_make_args())

        self.assertEqual(ctx.exception.code, 1)

    @patch("rlm.cli.archive.smart_remember")
    def test_content_arg_routes_through_smart(self, mock_sr):
        """Providing content should route through smart_remember, not archive_session."""
        mock_sr.return_value = {
            "summary_id": "m_test",
            "summary": "test",
            "tags": ["t"],
            "facts_count": 0,
        }
        with patch("builtins.print") as mock_print:
            cmd_remember(_make_args(content="hello world"))

        mock_sr.assert_called_once()
        _, kwargs = mock_sr.call_args
        assert kwargs["content"] == "hello world"
        assert kwargs["source"] == "text"
        output = mock_print.call_args[0][0]
        assert "Memory stored" in output


if __name__ == "__main__":
    unittest.main()
