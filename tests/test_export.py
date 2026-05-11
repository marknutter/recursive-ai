"""Tests for export_session() — Claude Code JSONL format."""

import json
import os
import tempfile
import unittest

from rlm.export import (
    _parse_entries,
    export_session,
    extract_text_from_content,
)


def _write_jsonl(lines):
    """Write a list of dicts as a JSONL temp file, return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for line in lines:
        f.write(json.dumps(line) + "\n")
    f.close()
    return f.name


class TestExtractTextFromContent(unittest.TestCase):
    def test_thinking_blocks_skipped(self):
        """Thinking blocks should be silently skipped."""
        content = [
            {"type": "thinking", "thinking": "Let me consider..."},
            {"type": "text", "text": "Here's my answer."},
        ]
        texts, tool_calls = extract_text_from_content(content)
        self.assertEqual(texts, ["Here's my answer."])
        self.assertEqual(tool_calls, [])

    def test_tool_use_still_works(self):
        """Claude Code's tool_use blocks should still work."""
        content = [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/foo"}},
        ]
        texts, tool_calls = extract_text_from_content(content)
        self.assertEqual(texts, [])
        self.assertEqual(len(tool_calls), 1)
        self.assertIn("Read", tool_calls[0])


class TestParseEntries(unittest.TestCase):
    def test_claude_code_entries(self):
        path = _write_jsonl([
            {"type": "user", "timestamp": "T1", "message": {"role": "user", "content": "hello"}},
            {"type": "assistant", "timestamp": "T2", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
            {"type": "summary", "data": "ignored"},
        ])
        entries = _parse_entries(path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0], "user")
        self.assertEqual(entries[1][0], "assistant")
        os.unlink(path)


class TestExportSessionClaudeCode(unittest.TestCase):
    """Ensure Claude Code format still works after refactor."""

    def test_basic_claude_code_export(self):
        path = _write_jsonl([
            {"type": "user", "timestamp": "2026-01-01T10:00:00Z",
             "message": {"role": "user", "content": "What time is it?"}},
            {"type": "assistant", "timestamp": "2026-01-01T10:00:05Z",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "I don't have a clock."}]}},
        ])
        result = export_session(path)
        self.assertIn("2 messages", result)
        self.assertIn("What time is it?", result)
        self.assertIn("clock", result)
        os.unlink(path)

    def test_trivial_confirmation_collapsed(self):
        path = _write_jsonl([
            {"type": "user", "timestamp": "T1", "message": {"role": "user", "content": "Do something"}},
            {"type": "assistant", "timestamp": "T2", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
            {"type": "user", "timestamp": "T3", "message": {"role": "user", "content": "ok"}},
        ])
        result = export_session(path)
        self.assertIn("[User confirmed]", result)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
