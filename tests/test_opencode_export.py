"""Tests for OpenCode session export parsing and compression."""

import json
import os
import tempfile
import unittest

from rlm.opencode_export import (
    _epoch_ms_to_iso,
    _parse_opencode_messages,
    _parse_opencode_parts,
    export_opencode_session,
    get_session_directory,
    get_session_id,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_EXPORT = os.path.join(FIXTURES_DIR, "opencode_export_sample.json")


class TestEpochMsToIso(unittest.TestCase):
    def test_valid_timestamp(self):
        # 2024-03-04T00:00:00Z
        result = _epoch_ms_to_iso(1709510400000)
        self.assertIn("2024-03-04", result)

    def test_zero_returns_empty(self):
        self.assertEqual(_epoch_ms_to_iso(0), "")

    def test_none_returns_empty(self):
        self.assertEqual(_epoch_ms_to_iso(None), "")

    def test_invalid_returns_empty(self):
        self.assertEqual(_epoch_ms_to_iso("not-a-number"), "")


class TestParseOpencodeParts(unittest.TestCase):
    def test_text_part(self):
        parts = [{"type": "text", "content": "Hello world"}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "text")
        self.assertEqual(blocks[0]["text"], "Hello world")

    def test_text_with_text_key(self):
        """Some OpenCode versions may use 'text' instead of 'content'."""
        parts = [{"type": "text", "text": "Hello"}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(blocks[0]["text"], "Hello")

    def test_tool_invocation(self):
        parts = [{"type": "tool-invocation", "toolName": "Bash", "input": {"command": "ls"}}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "tool_use")
        self.assertEqual(blocks[0]["name"], "Bash")
        self.assertEqual(blocks[0]["input"]["command"], "ls")

    def test_tool_invocation_string_input(self):
        """Tool input may be a JSON string."""
        parts = [{"type": "tool-invocation", "toolName": "Read", "input": '{"file_path": "/tmp/f"}'}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(blocks[0]["input"]["file_path"], "/tmp/f")

    def test_tool_result_produces_skip_block(self):
        parts = [{"type": "tool-result", "content": "some output"}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "tool_result")

    def test_reasoning_skipped(self):
        parts = [{"type": "reasoning", "content": "thinking..."}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(len(blocks), 0)

    def test_unknown_type_skipped(self):
        parts = [{"type": "some-future-type", "data": "ignored"}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(len(blocks), 0)

    def test_mixed_parts(self):
        parts = [
            {"type": "reasoning", "content": "thinking..."},
            {"type": "text", "content": "Here's what I found."},
            {"type": "tool-invocation", "toolName": "Bash", "input": {"command": "git status"}},
            {"type": "tool-result", "content": "on branch main"},
        ]
        blocks = _parse_opencode_parts(parts)
        # reasoning skipped, text + tool_use + tool_result = 3
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0]["type"], "text")
        self.assertEqual(blocks[1]["type"], "tool_use")
        self.assertEqual(blocks[2]["type"], "tool_result")

    def test_empty_text_skipped(self):
        parts = [{"type": "text", "content": ""}]
        blocks = _parse_opencode_parts(parts)
        self.assertEqual(len(blocks), 0)


class TestParseOpencodeMessages(unittest.TestCase):
    def test_basic_messages(self):
        data = {
            "info": {"id": "test"},
            "messages": [
                {"info": {"role": "user", "time": {"created": 1709500000000}},
                 "parts": [{"type": "text", "content": "hello"}]},
                {"info": {"role": "assistant", "time": {"created": 1709500010000}},
                 "parts": [{"type": "text", "content": "hi there"}]},
            ],
        }
        entries = _parse_opencode_messages(data)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0], "user")
        self.assertEqual(entries[1][0], "assistant")
        # Timestamps should be ISO strings
        self.assertIn("2024-03-03", entries[0][1])

    def test_system_role_skipped(self):
        data = {
            "info": {"id": "test"},
            "messages": [
                {"info": {"role": "system", "time": {"created": 1709500000000}},
                 "parts": [{"type": "text", "content": "system prompt"}]},
                {"info": {"role": "user", "time": {"created": 1709500001000}},
                 "parts": [{"type": "text", "content": "hello"}]},
            ],
        }
        entries = _parse_opencode_messages(data)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][0], "user")

    def test_empty_parts_skipped(self):
        data = {
            "info": {"id": "test"},
            "messages": [
                {"info": {"role": "user", "time": {"created": 1709500000000}},
                 "parts": []},
            ],
        }
        entries = _parse_opencode_messages(data)
        self.assertEqual(len(entries), 0)

    def test_no_messages(self):
        data = {"info": {"id": "test"}, "messages": []}
        entries = _parse_opencode_messages(data)
        self.assertEqual(len(entries), 0)


class TestExportOpencodeSession(unittest.TestCase):
    def test_sample_fixture(self):
        result = export_opencode_session(SAMPLE_EXPORT)
        self.assertIn("Session Transcript", result)
        self.assertIn("fix the authentication bug", result)
        self.assertIn("Found the bug", result)
        # Reasoning should NOT appear
        self.assertNotIn("Let me think about", result)
        # Tool result raw content should NOT appear (the test file output)
        self.assertNotIn("PASS src/auth.test.ts", result)
        # Trivial confirmation should be collapsed
        self.assertIn("[User confirmed]", result)

    def test_output_to_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            out_path = f.name
        try:
            result = export_opencode_session(SAMPLE_EXPORT, output_path=out_path)
            with open(out_path) as f:
                written = f.read()
            self.assertEqual(result, written)
        finally:
            os.unlink(out_path)

    def test_empty_session(self):
        data = {"info": {"id": "empty"}, "messages": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            json_path = f.name
        try:
            result = export_opencode_session(json_path)
            self.assertIn("0 messages", result)
        finally:
            os.unlink(json_path)

    def test_tool_only_assistant_message(self):
        """Assistant message with only tool calls should be compressed."""
        data = {
            "info": {"id": "test"},
            "messages": [
                {"info": {"role": "user", "time": {"created": 1709500000000}},
                 "parts": [{"type": "text", "content": "run tests"}]},
                {"info": {"role": "assistant", "time": {"created": 1709500010000}},
                 "parts": [
                     {"type": "tool-invocation", "toolName": "Bash",
                      "input": {"command": "npm test"}},
                 ]},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            json_path = f.name
        try:
            result = export_opencode_session(json_path)
            self.assertIn("[Ran 1 tools: Bash]", result)
        finally:
            os.unlink(json_path)

    def test_reasoning_only_message_excluded(self):
        """Assistant message with only reasoning parts should be excluded."""
        data = {
            "info": {"id": "test"},
            "messages": [
                {"info": {"role": "user", "time": {"created": 1709500000000}},
                 "parts": [{"type": "text", "content": "explain this"}]},
                {"info": {"role": "assistant", "time": {"created": 1709500010000}},
                 "parts": [{"type": "reasoning", "content": "deep thoughts..."}]},
                {"info": {"role": "assistant", "time": {"created": 1709500020000}},
                 "parts": [{"type": "text", "content": "Here is the explanation."}]},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            json_path = f.name
        try:
            result = export_opencode_session(json_path)
            self.assertNotIn("deep thoughts", result)
            self.assertIn("Here is the explanation", result)
        finally:
            os.unlink(json_path)


class TestGetSessionMetadata(unittest.TestCase):
    def test_get_session_id(self):
        with open(SAMPLE_EXPORT) as f:
            data = json.load(f)
        self.assertEqual(get_session_id(data), "abc123-def456-ghi789")

    def test_get_session_directory(self):
        with open(SAMPLE_EXPORT) as f:
            data = json.load(f)
        self.assertEqual(get_session_directory(data), "/Users/dev/projects/my-app")

    def test_missing_id(self):
        self.assertIsNone(get_session_id({"info": {}}))

    def test_missing_directory(self):
        self.assertIsNone(get_session_directory({"info": {}}))


if __name__ == "__main__":
    unittest.main()
