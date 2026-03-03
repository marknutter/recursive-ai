"""Parse OpenCode session exports into compressed transcripts.

OpenCode exports sessions as a single JSON object (not JSONL):

    {
      "info": { "id": "...", "directory": "...", "title": "...",
                "time": { "created": <epoch_ms> } },
      "messages": [
        { "info": { "role": "user"|"assistant", "time": {...} },
          "parts": [{ "type": "text", "content": "..." }, ...] }
      ]
    }

This module parses that format into the (role, timestamp, content) tuples
that export._compress_and_format() expects, then runs the shared pipeline.
"""

import json
from datetime import datetime, timezone


def _epoch_ms_to_iso(epoch_ms):
    """Convert epoch milliseconds to ISO 8601 string."""
    if not epoch_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, OSError):
        return ""


def _parse_opencode_parts(parts):
    """Convert OpenCode message parts to the content-block format.

    Maps OpenCode part types to the format extract_text_from_content() handles:
      - text.content → {"type": "text", "text": ...}
      - tool-invocation → {"type": "tool_use", "name": ..., "input": ...}
      - tool-result → {"type": "tool_result"} (skipped by extract_text_from_content)
      - reasoning → skipped entirely (like thinking blocks)

    Returns a list of content blocks.
    """
    blocks = []
    for part in parts:
        ptype = part.get("type", "")

        if ptype == "text":
            text = part.get("content", "") or part.get("text", "")
            if text:
                blocks.append({"type": "text", "text": text})

        elif ptype == "tool-invocation":
            tool_name = part.get("toolName", "") or part.get("name", "unknown")
            tool_input = part.get("input", {}) or part.get("args", {})
            # Normalize tool_input — OpenCode may serialize as string
            if isinstance(tool_input, str):
                try:
                    tool_input = json.loads(tool_input)
                except (json.JSONDecodeError, TypeError):
                    tool_input = {"raw": tool_input}
            blocks.append({
                "type": "tool_use",
                "name": tool_name,
                "input": tool_input,
            })

        elif ptype == "tool-result":
            # Skip tool results (same as Claude Code's tool_result handling)
            blocks.append({"type": "tool_result"})

        elif ptype == "reasoning":
            # Skip reasoning blocks (same as thinking blocks)
            pass

        # Other unknown types are silently ignored

    return blocks


def _parse_opencode_messages(data):
    """Parse OpenCode JSON export into (role, timestamp, content) tuples.

    Args:
        data: Parsed JSON dict from an OpenCode export file.

    Returns:
        List of (role, timestamp, content) tuples compatible with
        export._compress_and_format().
    """
    entries = []
    messages = data.get("messages", [])

    for msg in messages:
        info = msg.get("info", {})
        role = info.get("role", "")

        # Skip non-user/assistant roles (e.g., "system")
        if role not in ("user", "assistant"):
            continue

        # Extract timestamp — try info.time.created (epoch ms), then info.createdAt
        time_info = info.get("time", {})
        created_ms = time_info.get("created") or time_info.get("createdAt")
        timestamp = _epoch_ms_to_iso(created_ms) if created_ms else ""

        # Convert parts to content blocks
        parts = msg.get("parts", [])
        content = _parse_opencode_parts(parts)

        if content:
            entries.append((role, timestamp, content))

    return entries


def export_opencode_session(json_path, output_path=None):
    """Convert an OpenCode JSON export to a compressed transcript.

    Args:
        json_path: Path to an OpenCode session export JSON file.
        output_path: If provided, write to this file. Otherwise return text.

    Returns:
        The compressed transcript as a string.
    """
    from rlm.export import _compress_and_format

    with open(json_path, "r") as f:
        data = json.load(f)

    parsed = _parse_opencode_messages(data)
    return _compress_and_format(parsed, source_label=json_path, output_path=output_path)


def get_session_id(data):
    """Extract the session ID from an OpenCode export.

    Args:
        data: Parsed JSON dict from an OpenCode export file.

    Returns:
        Session ID string, or None if not found.
    """
    info = data.get("info", {})
    return info.get("id")


def get_session_directory(data):
    """Extract the working directory from an OpenCode export.

    Args:
        data: Parsed JSON dict from an OpenCode export file.

    Returns:
        Directory path string, or None if not found.
    """
    info = data.get("info", {})
    return info.get("directory")
