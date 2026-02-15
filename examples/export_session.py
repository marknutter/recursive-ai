"""Export a Claude Code session transcript to readable text for memory ingestion.

Reads the JSONL session file, extracts human and assistant messages,
strips tool call noise, and outputs a readable conversation format.
"""

import json
import sys
import re
from pathlib import Path


def extract_text_from_content(content):
    """Extract readable text from message content (string or list of blocks)."""
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        texts.append(text)
                elif block.get("type") == "tool_use":
                    tool = block.get("name", "unknown")
                    inp = block.get("input", {})
                    # Summarize tool calls concisely
                    if tool == "Bash":
                        cmd = inp.get("command", "")
                        texts.append(f"[Tool: Bash] {cmd[:200]}")
                    elif tool == "Read":
                        texts.append(f"[Tool: Read] {inp.get('file_path', '')}")
                    elif tool == "Write":
                        texts.append(f"[Tool: Write] {inp.get('file_path', '')}")
                    elif tool == "Edit":
                        texts.append(f"[Tool: Edit] {inp.get('file_path', '')}")
                    elif tool == "Task":
                        desc = inp.get("description", "")
                        texts.append(f"[Tool: Task] {desc}")
                    elif tool == "Grep":
                        texts.append(f"[Tool: Grep] {inp.get('pattern', '')}")
                    elif tool == "Glob":
                        texts.append(f"[Tool: Glob] {inp.get('pattern', '')}")
                    else:
                        texts.append(f"[Tool: {tool}]")
                elif block.get("type") == "tool_result":
                    # Skip tool results — they're verbose
                    pass
            elif isinstance(block, str):
                if block.strip():
                    texts.append(block.strip())
        return "\n".join(texts)

    return str(content)[:500]


def export_session(jsonl_path, output_path=None):
    """Convert a session JSONL to readable conversation text."""
    messages = []

    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = entry.get("type")
            if msg_type not in ("user", "assistant"):
                continue

            timestamp = entry.get("timestamp", "")
            message = entry.get("message", {})
            role = message.get("role", msg_type)
            content = message.get("content", "")

            text = extract_text_from_content(content)
            if not text:
                continue

            # Skip duplicate/incremental assistant messages (streaming artifacts)
            # Only keep messages with substantial content
            if role == "assistant" and len(text) < 3:
                continue

            messages.append({
                "role": role,
                "timestamp": timestamp,
                "text": text,
            })

    # Deduplicate assistant messages — streaming creates many incremental updates
    # Keep only the longest version for each parentUuid
    deduped = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg["role"] == "assistant":
            # Look ahead for consecutive assistant messages, keep the longest
            best = msg
            j = i + 1
            while j < len(messages) and messages[j]["role"] == "assistant":
                if len(messages[j]["text"]) > len(best["text"]):
                    best = messages[j]
                j += 1
            deduped.append(best)
            i = j
        else:
            deduped.append(msg)
            i += 1

    # Format output
    output_lines = []
    output_lines.append("# Claude Code Session Transcript")
    output_lines.append(f"# Source: {jsonl_path}")
    output_lines.append(f"# Messages: {len(deduped)}")
    output_lines.append("")

    for msg in deduped:
        ts = msg["timestamp"][:19].replace("T", " ") if msg["timestamp"] else ""
        role_label = "USER" if msg["role"] == "user" else "CLAUDE"

        output_lines.append(f"--- [{ts}] {role_label} ---")
        output_lines.append(msg["text"])
        output_lines.append("")

    output_text = "\n".join(output_lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(output_text)
        print(f"Exported {len(deduped)} messages to {output_path}")
        print(f"Size: {len(output_text):,} chars")
    else:
        print(output_text)

    return output_text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python export_session.py <session.jsonl> [output.txt]")
        sys.exit(1)

    jsonl_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    export_session(jsonl_path, output_path)
