#!/usr/bin/env python3
"""
RLM PreCompact Hook - Archive conversation to episodic memory

Saves full conversation transcript to ~/.rlm/memory/ before compaction,
enabling cross-session memory and context continuity.
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Absolute path to the RLM project — hooks run from any directory
RLM_PROJECT = Path.home() / "Kode" / "recursive-ai"


def log(msg: str):
    print(f"[RLM-PreCompact] {msg}", file=sys.stderr)


def get_project_name() -> str:
    """Get current project directory name from git root, or cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip()).name
    except subprocess.CalledProcessError:
        return Path.cwd().name


def get_session_file() -> Path | None:
    """Find the most recent .jsonl session file."""
    projects_dir = Path.home() / ".claude" / "projects"

    if not projects_dir.exists():
        return None

    # Find most recent .jsonl file across all projects
    session_files = list(projects_dir.glob("**/*.jsonl"))
    if not session_files:
        return None

    return max(session_files, key=lambda p: p.stat().st_mtime)


def mark_as_archived(session_file: Path):
    """Create marker file to prevent duplicate archiving."""
    marker = session_file.with_suffix(session_file.suffix + ".rlm-archived")
    marker.write_text(datetime.now().isoformat())


def main():
    try:
        session_file = get_session_file()

        if not session_file:
            log("No active session file found - skipping archive")
            sys.exit(0)

        project_name = get_project_name()

        log(f"Archiving conversation before compaction...")
        log(f"Project: {project_name}")
        log(f"Session: {session_file.name}")

        # Export session transcript via rlm CLI
        result = subprocess.run(
            ["uv", "run", "--project", str(RLM_PROJECT), "rlm", "export-session", str(session_file)],
            capture_output=True,
            text=True,
            check=True,
        )

        transcript = result.stdout

        if not transcript or not transcript.strip():
            log("Empty transcript - skipping archive")
            sys.exit(0)

        # Store in RLM memory
        timestamp = datetime.now().strftime("%Y-%m-%d")
        tags = f"conversation,session,{project_name},{timestamp}"
        summary = f"Conversation in {project_name} on {timestamp}"

        subprocess.run(
            ["uv", "run", "--project", str(RLM_PROJECT), "rlm", "remember", "--stdin", "--tags", tags, "--summary", summary],
            input=transcript,
            text=True,
            check=True,
            capture_output=True,
        )

        # Mark as archived to prevent duplicate archiving
        mark_as_archived(session_file)

        log(f"✓ Conversation archived to ~/.rlm/memory/")
        log(f"  Tags: {tags}")
        log(f"  Size: {len(transcript):,} chars")

    except Exception as err:
        log(f"Error: {err}")
        # Don't fail compaction if archiving fails
        sys.exit(0)


if __name__ == "__main__":
    main()
