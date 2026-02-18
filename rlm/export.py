"""Export a Claude Code session transcript to readable text for memory ingestion.

Reads the JSONL session file, extracts human and assistant messages,
strips tool call noise, and outputs a compact conversation format.

Compression passes:
- Strip skill prompt injections (biggest win: ~84% of user content)
- Strip command-message XML tags
- Strip system-reminder blocks
- Collapse trivial user confirmations into [User confirmed]
- Compress tool-call-only assistant messages
- Strip boilerplate assistant openers
- Compact formatting (shorter headers, no excess blank lines)
- Detect and truncate pasted terminal output
"""

import json
import re


# Trivial confirmations — user messages that add no information
TRIVIAL_CONFIRMATIONS = {
    "yes", "yeah", "yep", "yup", "y", "ok", "okay", "k",
    "sure", "sounds good", "go ahead", "do it", "proceed",
    "go for it", "looks good", "lgtm", "approved", "confirm",
    "continue", "next", "perfect", "great", "thanks", "thank you",
    "cool", "nice", "awesome", "right", "correct", "exactly",
    "agreed", "fine", "done", "got it",
}

# Boilerplate openers to strip from assistant messages
BOILERPLATE_PATTERNS = [
    re.compile(r"^(Let me |I'll |I will |Sure[,!] |Great[,!] |Perfect[,!] |"
               r"Absolutely[,!] |Of course[,!] |Good question[,!] |"
               r"Great question[,!] |Excellent[,!] |Alright[,!] )"
               r"(check|look|help|take a look|examine|review|investigate|"
               r"search|explore|read|see|find|get|start|do that|handle that)"
               r"[^.]*?\.\s*", re.IGNORECASE),
]

# Patterns indicating pasted terminal output
TERMINAL_INDICATORS = re.compile(
    r"^[$❯>]|"           # Command prompts
    r"^\s*(error|Error|ERROR|warning|Warning|WARN|Traceback|"
    r"at [\w.]+\(|File \"|npm ERR|FAILED|PASS|✓|✗|"
    r"^\d+\s+(passing|failing|pending))",
    re.MULTILINE,
)


def extract_text_from_content(content):
    """Extract readable text from message content (string or list of blocks)."""
    if isinstance(content, str):
        text = _strip_system_reminders(content.strip())
        text = _strip_command_xml(text)
        return text

    if isinstance(content, list):
        texts = []
        tool_calls = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text = block.get("text", "").strip()
                    text = _strip_system_reminders(text)
                    # Skip skill prompt injections entirely
                    if _is_skill_prompt(text):
                        continue
                    text = _strip_command_xml(text)
                    if text:
                        texts.append(text)
                elif block.get("type") == "tool_use":
                    tool = block.get("name", "unknown")
                    inp = block.get("input", {})
                    tool_calls.append(_summarize_tool_call(tool, inp))
                elif block.get("type") == "tool_result":
                    pass  # Skip tool results — they're verbose
            elif isinstance(block, str):
                text = block.strip()
                text = _strip_system_reminders(text)
                if text and not _is_skill_prompt(text):
                    texts.append(text)

        # Return text + tool calls separately so we can detect tool-only messages
        return texts, tool_calls

    return [str(content)[:500]], []


def _summarize_tool_call(tool, inp):
    """Create a one-line summary of a tool call."""
    if tool == "Bash":
        cmd = inp.get("command", "")
        return f"[Tool: Bash] {cmd[:200]}"
    elif tool == "Read":
        return f"[Tool: Read] {inp.get('file_path', '')}"
    elif tool == "Write":
        return f"[Tool: Write] {inp.get('file_path', '')}"
    elif tool == "Edit":
        return f"[Tool: Edit] {inp.get('file_path', '')}"
    elif tool == "Task":
        return f"[Tool: Task] {inp.get('description', '')}"
    elif tool == "Grep":
        return f"[Tool: Grep] {inp.get('pattern', '')}"
    elif tool == "Glob":
        return f"[Tool: Glob] {inp.get('pattern', '')}"
    else:
        return f"[Tool: {tool}]"


def _strip_system_reminders(text):
    """Remove <system-reminder>...</system-reminder> blocks from text."""
    return re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL).strip()


def _strip_command_xml(text):
    """Extract the actual user command from command-message XML, discard the XML wrapper."""
    # Pattern: <command-message>cmd</command-message>\n<command-name>/cmd</command-name>\n<command-args>args</command-args>
    match = re.match(
        r"<command-message>\s*(\S+)\s*</command-message>\s*"
        r"<command-name>\s*/(\S+)\s*</command-name>\s*"
        r"(?:<command-args>\s*(.*?)\s*</command-args>)?",
        text, re.DOTALL
    )
    if match:
        cmd_name = match.group(2)
        cmd_args = match.group(3) or ""
        return f"/{cmd_name} {cmd_args}".strip()
    return text


def _is_skill_prompt(text):
    """Detect if a text block is an injected skill prompt (not user content).

    Skill prompts are large instructional blocks injected when the user invokes
    a slash command like /recall or /rlm. They contain things like CLI references,
    step-by-step instructions, etc. — useful for the agent but noise for memory.
    """
    indicators = [
        "Base directory for this skill:",
        "CLI Quick Reference",
        "## Step 1:",
        "## Parse Arguments",
        "You are retrieving",
        "You are performing",
        "**Your job:**",
        "**All commands must be prefixed with:**",
    ]
    # Skill prompts are typically >500 chars and contain multiple indicators
    if len(text) < 500:
        return False
    matches = sum(1 for ind in indicators if ind in text)
    return matches >= 2


def _is_trivial_confirmation(text):
    """Check if a user message is a trivial confirmation."""
    normalized = text.strip().lower().rstrip(".!,")
    # Exact match
    if normalized in TRIVIAL_CONFIRMATIONS:
        return True
    # Very short messages that are just confirmations with minor variation
    if len(normalized) < 20 and any(normalized.startswith(c) for c in TRIVIAL_CONFIRMATIONS):
        return True
    return False


def _strip_boilerplate(text):
    """Remove boilerplate opener phrases from assistant messages."""
    for pattern in BOILERPLATE_PATTERNS:
        text = pattern.sub("", text, count=1)
    return text.strip()


def _compress_pasted_output(text, max_lines=6):
    """Detect and truncate pasted terminal output in user messages."""
    lines = text.split("\n")
    if len(lines) < 10:
        return text

    # Count terminal-like lines
    terminal_lines = sum(1 for line in lines if TERMINAL_INDICATORS.search(line))
    if terminal_lines < len(lines) * 0.3:
        return text

    # This looks like pasted terminal output — truncate
    head = lines[:3]
    tail = lines[-3:]
    omitted = len(lines) - 6
    return "\n".join(head + [f"[...{omitted} lines of terminal output...]"] + tail)


def export_session(jsonl_path, output_path=None):
    """Convert a session JSONL to a compressed conversation transcript.

    Args:
        jsonl_path: Path to the Claude Code .jsonl session file.
        output_path: If provided, write to this file. Otherwise return text.

    Returns:
        The exported transcript as a string.
    """
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

            result = extract_text_from_content(content)

            # Handle both old format (string) and new format (texts, tool_calls)
            if isinstance(result, tuple):
                texts, tool_calls = result
            else:
                texts = [result] if result else []
                tool_calls = []

            has_text = any(t.strip() for t in texts)

            if not has_text and not tool_calls:
                continue

            # Skip very short assistant streaming artifacts
            combined_text = "\n".join(t for t in texts if t.strip())
            if role == "assistant" and len(combined_text) < 3 and not tool_calls:
                continue

            messages.append({
                "role": role,
                "timestamp": timestamp,
                "texts": texts,
                "tool_calls": tool_calls,
                "has_text": has_text,
            })

    # Deduplicate assistant messages — streaming creates many incremental updates
    # Keep only the longest version for each consecutive run
    deduped = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg["role"] == "assistant":
            best = msg
            best_len = sum(len(t) for t in msg["texts"])
            j = i + 1
            while j < len(messages) and messages[j]["role"] == "assistant":
                candidate_len = sum(len(t) for t in messages[j]["texts"])
                if candidate_len > best_len:
                    best = messages[j]
                    best_len = candidate_len
                j += 1
            deduped.append(best)
            i = j
        else:
            deduped.append(msg)
            i += 1

    # --- Compression passes ---

    compressed = []
    for idx, msg in enumerate(deduped):
        role = msg["role"]
        texts = msg["texts"]
        tool_calls = msg["tool_calls"]
        has_text = msg["has_text"]

        combined = "\n".join(t for t in texts if t.strip())

        if role == "user":
            # Collapse trivial confirmations
            if _is_trivial_confirmation(combined):
                compressed.append({
                    "role": "user",
                    "timestamp": msg["timestamp"],
                    "text": "[User confirmed]",
                })
                continue

            # Compress pasted terminal output
            combined = _compress_pasted_output(combined)

            compressed.append({
                "role": "user",
                "timestamp": msg["timestamp"],
                "text": combined,
            })

        elif role == "assistant":
            # Compress tool-call-only messages (no substantive text)
            if not has_text and tool_calls:
                tool_names = [tc.split("]")[0].replace("[Tool: ", "") for tc in tool_calls]
                compressed.append({
                    "role": "assistant",
                    "timestamp": msg["timestamp"],
                    "text": f"[Ran {len(tool_calls)} tools: {', '.join(tool_names)}]",
                })
                continue

            # Strip boilerplate openers
            combined = _strip_boilerplate(combined)

            # Include tool calls inline if there's also text
            if tool_calls:
                combined = combined + "\n" + "\n".join(tool_calls)

            if combined.strip():
                compressed.append({
                    "role": "assistant",
                    "timestamp": msg["timestamp"],
                    "text": combined,
                })

    # Format output — compact headers
    output_lines = []
    output_lines.append(f"# Session Transcript ({len(compressed)} messages)")
    output_lines.append(f"# Source: {jsonl_path}")
    output_lines.append("")

    for msg in compressed:
        ts = msg["timestamp"][:19].replace("T", " ") if msg["timestamp"] else ""
        # Compact timestamp: just HH:MM
        short_ts = ts[11:16] if len(ts) >= 16 else ts
        role_label = "User" if msg["role"] == "user" else "Claude"

        output_lines.append(f"[{short_ts}] {role_label}:")
        output_lines.append(msg["text"])
        output_lines.append("")

    output_text = "\n".join(output_lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(output_text)

    return output_text
