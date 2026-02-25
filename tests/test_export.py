"""Tests for export_session() — Claude Code and OpenClaw JSONL formats."""

import json
import os
import tempfile
import unittest

from rlm.export import (
    _detect_openclaw_format,
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


class TestDetectFormat(unittest.TestCase):
    def test_openclaw_format_detected(self):
        path = _write_jsonl([
            {"type": "session", "version": 3, "id": "abc", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        ])
        self.assertTrue(_detect_openclaw_format(path))
        os.unlink(path)

    def test_claude_code_format_detected(self):
        path = _write_jsonl([
            {"type": "user", "message": {"role": "user", "content": "hello"}, "timestamp": "2026-01-01T00:00:00Z"},
        ])
        self.assertFalse(_detect_openclaw_format(path))
        os.unlink(path)

    def test_empty_file(self):
        path = _write_jsonl([])
        self.assertFalse(_detect_openclaw_format(path))
        os.unlink(path)


class TestExtractTextFromContent(unittest.TestCase):
    def test_toolCall_block(self):
        """OpenClaw's toolCall blocks should be extracted like tool_use."""
        content = [
            {"type": "text", "text": "Running a command."},
            {"type": "toolCall", "name": "Bash", "arguments": {"command": "ls -la"}},
        ]
        texts, tool_calls = extract_text_from_content(content)
        self.assertEqual(texts, ["Running a command."])
        self.assertEqual(len(tool_calls), 1)
        self.assertIn("Bash", tool_calls[0])
        self.assertIn("ls -la", tool_calls[0])

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
    def test_openclaw_entries(self):
        path = _write_jsonl([
            {"type": "session", "version": 3, "id": "x", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "model_change", "modelId": "claude-sonnet-4-5"},
            {"type": "message", "timestamp": "2026-01-01T00:01:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}},
            {"type": "message", "timestamp": "2026-01-01T00:02:00Z",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "hi back"}]}},
            {"type": "message", "timestamp": "2026-01-01T00:03:00Z",
             "message": {"role": "toolResult", "content": [{"type": "text", "text": "tool output"}]}},
        ])
        entries = _parse_entries(path, is_openclaw=True)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0], "user")
        self.assertEqual(entries[1][0], "assistant")
        os.unlink(path)

    def test_claude_code_entries(self):
        path = _write_jsonl([
            {"type": "user", "timestamp": "T1", "message": {"role": "user", "content": "hello"}},
            {"type": "assistant", "timestamp": "T2", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
            {"type": "summary", "data": "ignored"},
        ])
        entries = _parse_entries(path, is_openclaw=False)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0], "user")
        self.assertEqual(entries[1][0], "assistant")
        os.unlink(path)


class TestExportSessionOpenClaw(unittest.TestCase):
    def test_basic_openclaw_export(self):
        path = _write_jsonl([
            {"type": "session", "version": 3, "id": "test-id", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "message", "timestamp": "2026-01-01T10:30:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "What is 2+2?"}]}},
            {"type": "message", "timestamp": "2026-01-01T10:30:05Z",
             "message": {"role": "assistant", "content": [
                 {"type": "thinking", "thinking": "Simple math..."},
                 {"type": "text", "text": "The answer is 4."},
             ]}},
        ])
        result = export_session(path)
        self.assertIn("Session Transcript (2 messages)", result)
        self.assertIn("What is 2+2?", result)
        self.assertIn("The answer is 4.", result)
        # Thinking should NOT appear
        self.assertNotIn("Simple math", result)
        os.unlink(path)

    def test_openclaw_tool_calls(self):
        """toolCall blocks produce tool summaries; toolResult lines are skipped."""
        path = _write_jsonl([
            {"type": "session", "version": 3, "id": "t", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "message", "timestamp": "2026-01-01T10:00:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "list files"}]}},
            {"type": "message", "timestamp": "2026-01-01T10:00:05Z",
             "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "Here are the files."},
                 {"type": "toolCall", "name": "Bash", "id": "tc1", "arguments": {"command": "ls"}},
             ]}},
            {"type": "message", "timestamp": "2026-01-01T10:00:06Z",
             "message": {"role": "toolResult", "content": [{"type": "text", "text": "file1\nfile2"}]}},
        ])
        result = export_session(path)
        # toolResult content should not appear
        self.assertNotIn("file1", result)
        # toolCall should be summarized inline
        self.assertIn("[Tool: Bash]", result)
        self.assertIn("Here are the files.", result)
        os.unlink(path)

    def test_openclaw_skips_metadata_lines(self):
        """model_change, thinking_level_change, custom lines should be ignored."""
        path = _write_jsonl([
            {"type": "session", "version": 3, "id": "x", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "model_change", "modelId": "claude-sonnet-4-5"},
            {"type": "thinking_level_change", "thinkingLevel": "low"},
            {"type": "custom", "customType": "model-snapshot", "data": {}},
            {"type": "message", "timestamp": "2026-01-01T10:00:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}},
        ])
        result = export_session(path)
        self.assertIn("1 messages", result)
        self.assertIn("hello", result)
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


class TestExportRealOpenClawSession(unittest.TestCase):
    """Integration test with the real OpenClaw session file (skipped if not present)."""

    REAL_SESSION = os.path.expanduser(
        "~/.openclaw/agents/main/sessions/8b25f314-e745-4ca0-bb5c-0f993dcfed3d.jsonl"
    )

    @unittest.skipUnless(
        os.path.exists(os.path.expanduser(
            "~/.openclaw/agents/main/sessions/8b25f314-e745-4ca0-bb5c-0f993dcfed3d.jsonl"
        )),
        "Real OpenClaw session file not present",
    )
    def test_real_session_exports(self):
        result = export_session(self.REAL_SESSION)
        self.assertIn("Session Transcript", result)
        # Should have extracted a non-trivial number of messages
        # The file has 439 message lines, dedup should still yield many
        self.assertIn("User:", result)
        self.assertIn("Claude:", result)
        # No raw JSON should leak through
        self.assertNotIn('"type": "session"', result)
        self.assertNotIn('"type": "model_change"', result)


if __name__ == "__main__":
    unittest.main()
