"""Generate concise session summaries from conversation transcripts.

Produces a ~2-5KB highlights document capturing decisions, problems solved,
key outcomes, and files modified. Used as the primary search target in
two-tier memory storage (summary + full transcript).

Two approaches:
1. LLM-based: Send transcript to Claude for intelligent summarization
2. Fallback: Extract structured highlights via pattern matching
"""

import os
import re
import subprocess
import sys

SUMMARY_PROMPT = """Summarize this conversation into a concise session report (~2000-4000 characters).

Structure your summary as:

## Session Summary
One paragraph overview of what was accomplished.

## Key Decisions
- Bullet points of decisions made and why

## Problems Solved
- What issues were encountered and how they were resolved

## Files Modified
- List of files created, edited, or deleted (if mentioned)

## Open Items
- Anything left unfinished or flagged for future work

Rules:
- Be specific: include names, paths, numbers, and technical details
- Skip pleasantries and filler — only substantive content
- If the conversation is mostly Q&A or exploration with no decisions, say so
- Keep total output under 4000 characters

Conversation:
---
{transcript}
---

Summary:"""


def generate_summary(transcript: str, max_input_chars: int = 15000) -> str:
    """Generate a concise session summary from a conversation transcript.

    Args:
        transcript: The compressed conversation transcript.
        max_input_chars: Maximum chars to send to LLM (default 15000).

    Returns:
        A ~2-5KB summary string.
    """
    # Truncate for LLM context limits
    if len(transcript) > max_input_chars:
        head_size = int(max_input_chars * 0.6)
        tail_size = max_input_chars - head_size
        truncated = (
            transcript[:head_size]
            + "\n\n...[middle of conversation omitted]...\n\n"
            + transcript[-tail_size:]
        )
    else:
        truncated = transcript

    prompt = SUMMARY_PROMPT.format(transcript=truncated)

    try:
        # Try Claude CLI
        try:
            result = subprocess.run(
                ["claude", "--no-conversation"],
                input=prompt,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Try Claude API
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            import requests

            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            data = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            }
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=data,
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]

    except Exception as e:
        print(f"[Summarize] LLM unavailable, using fallback: {e}", file=sys.stderr)

    # Fallback: extract structured highlights
    return extract_summary_fallback(transcript)


def extract_summary_fallback(transcript: str) -> str:
    """Extract a structured summary without LLM assistance.

    Parses the transcript for:
    - User questions (messages ending in ?)
    - Decision language ("decided", "let's go with", etc.)
    - Commit messages from git commands
    - Files from Tool: Write/Edit lines
    - First and last substantive exchanges
    """
    lines = transcript.split("\n")

    # Parse messages from the compact format: [HH:MM] Role:\n content
    messages = []
    current_role = None
    current_text = []

    for line in lines:
        header = re.match(r"^\[[\d:]+\]\s+(User|Claude):", line)
        if header:
            if current_role and current_text:
                messages.append((current_role, "\n".join(current_text).strip()))
            current_role = header.group(1)
            current_text = []
        elif current_role:
            current_text.append(line)

    if current_role and current_text:
        messages.append((current_role, "\n".join(current_text).strip()))

    # Extract components
    user_questions = []
    decisions = []
    commits = []
    files_modified = set()
    topics = []

    decision_patterns = re.compile(
        r"(decided|let's go with|the approach is|we'll use|going with|"
        r"chose|choosing|settled on|the plan is|agreed to|"
        r"the solution|implemented|the fix is|resolved by)",
        re.IGNORECASE,
    )

    for role, text in messages:
        if role == "User":
            # Capture questions
            for sent in re.split(r"[.!]\s+", text):
                if sent.strip().endswith("?") and len(sent) > 20:
                    user_questions.append(sent.strip())

        if role == "Claude":
            # Capture decisions
            for sent in re.split(r"\n", text):
                if decision_patterns.search(sent) and len(sent) > 30:
                    decisions.append(sent.strip()[:200])

        # Capture commit messages
        for match in re.finditer(r'\[Tool: Bash\] .*?git commit -m ["\']?(.*?)(?:["\']|$)', text):
            msg = match.group(1)[:150]
            if msg:
                commits.append(msg)
        for match in re.finditer(r"git commit.*?<<.*?EOF\n(.*?)(?:\n|$)", text):
            msg = match.group(1)[:150]
            if msg:
                commits.append(msg)

        # Capture files
        for match in re.finditer(r"\[Tool: (?:Write|Edit)\]\s+(.+)", text):
            files_modified.add(match.group(1).strip())

    # Build summary
    parts = []
    parts.append("## Session Summary")

    # First and last substantive exchanges give overview
    substantive = [(r, t) for r, t in messages if len(t) > 50]
    if substantive:
        first_user = next((t for r, t in substantive if r == "User"), "")
        if first_user:
            parts.append(f"Session started with: {first_user[:200]}")
        parts.append(f"Total messages: {len(messages)}")
    parts.append("")

    if user_questions:
        parts.append("## Key Questions")
        for q in user_questions[:8]:
            parts.append(f"- {q[:200]}")
        parts.append("")

    if decisions:
        parts.append("## Key Decisions")
        for d in decisions[:8]:
            parts.append(f"- {d}")
        parts.append("")

    if commits:
        parts.append("## Commits")
        for c in commits[:6]:
            parts.append(f"- {c}")
        parts.append("")

    if files_modified:
        parts.append("## Files Modified")
        for f in sorted(files_modified)[:15]:
            parts.append(f"- {f}")
        parts.append("")

    # If we didn't find much structure, include opening and closing exchanges
    if not decisions and not commits:
        parts.append("## Notable Exchanges")
        for role, text in substantive[:3]:
            prefix = "User" if role == "User" else "Claude"
            parts.append(f"**{prefix}:** {text[:300]}")
            parts.append("")
        if len(substantive) > 6:
            parts.append("...")
            for role, text in substantive[-2:]:
                prefix = "User" if role == "User" else "Claude"
                parts.append(f"**{prefix}:** {text[:300]}")
                parts.append("")

    return "\n".join(parts)
