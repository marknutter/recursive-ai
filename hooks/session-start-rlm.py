#!/usr/bin/env python3
"""
RLM SessionStart Hook - Inject recent project context at session start

Fires when a Claude Code session starts (new, resumed, or after compaction).
Searches memory for recent work on the current project and injects a brief
summary as additionalContext, giving the agent immediate continuity without
requiring the user to ask about previous sessions.

Output format: JSON with optional additionalContext field.
"""

import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta


def log(msg: str):
    print(f"[RLM-SessionStart] {msg}", file=sys.stderr)


def get_project_root() -> Path:
    """Get git project root, or cwd if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return Path.cwd()


def get_project_name() -> str:
    """Get project directory name."""
    return get_project_root().name


def find_rlm_project() -> Path | None:
    """Find the RLM project root by resolving this file's symlink."""
    # This file is symlinked from ~/.claude/hooks/ → {rlm_root}/hooks/
    rlm_root = Path(__file__).resolve().parent.parent
    if (rlm_root / "rlm" / "cli.py").exists():
        return rlm_root
    return None


def run_rlm(rlm_root: Path, *args) -> str:
    """Run an rlm CLI command and return stdout."""
    result = subprocess.run(
        ["uv", "run", "rlm", *args],
        capture_output=True,
        text=True,
        cwd=rlm_root,
    )
    return result.stdout.strip()


def get_recent_project_memories(rlm_root: Path, project_name: str) -> str:
    """List recent conversations about this project from memory."""
    # Use memory-list with project tag to find recent conversations
    # This is more reliable than recall for "what was I working on" queries
    output = run_rlm(
        rlm_root,
        "memory-list",
        "--tags", f"conversation,{project_name}",
        "--limit", "3",
    )

    return output


def build_context_summary(memories_output: str, project_name: str) -> str | None:
    """Build a compact context summary from memory search results."""
    if not memories_output or "0 entries total" in memories_output or "No matches" in memories_output:
        return None

    lines = memories_output.strip().split("\n")

    # Extract just the memory list portion (entries with IDs and summaries)
    entries = []
    for line in lines:
        line = line.strip()
        if line and line.startswith("m_"):
            # Format: "m_abc123  Summary text  [tags]  (size)"
            parts = line.split("  ")
            if len(parts) >= 2:
                entry_id = parts[0].strip()
                summary = parts[1].strip() if len(parts) > 1 else ""
                entries.append(f"- {summary} (entry: {entry_id})")

    if not entries:
        return None

    summary_lines = [
        f"## Recent Memory: {project_name}",
        "",
        f"Found {len(entries)} recent conversation(s) about this project in RLM memory:",
        "",
    ] + entries + [
        "",
        "Use `rlm_recall` (MCP tool) or `/rlm \"query\"` to retrieve full details from any of these.",
    ]

    return "\n".join(summary_lines)


def main():
    rlm_root = find_rlm_project()
    if not rlm_root:
        # RLM not installed — exit silently
        print(json.dumps({}))
        sys.exit(0)

    project_name = get_project_name()

    try:
        log(f"Checking memory for recent work on: {project_name}")
        memories = get_recent_project_memories(rlm_root, project_name)
        context = build_context_summary(memories, project_name)

        if context:
            log(f"Found recent memories — injecting context")
            print(json.dumps({"additionalContext": context}))
        else:
            log(f"No recent memories for {project_name} — no context injected")
            print(json.dumps({}))

    except Exception as err:
        log(f"Error: {err}")
        # Don't fail session start if memory lookup fails
        print(json.dumps({}))
        sys.exit(0)


if __name__ == "__main__":
    main()
