#!/usr/bin/env python3
"""
RLM PreCompact Hook - Archive conversation to episodic memory

Saves full conversation transcript to ~/.rlm/memory/ before compaction,
enabling cross-session memory and context continuity.
"""

import subprocess
import sys
from pathlib import Path
import os
from datetime import datetime


def log(msg: str):
    print(f"[RLM-PreCompact] {msg}", file=sys.stderr)


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


def get_session_file() -> Path | None:
    """Find the most recent .jsonl session file."""
    sessions_dir = Path.home() / ".claude" / "sessions"

    if not sessions_dir.exists():
        return None

    # Find most recent .jsonl file
    session_files = list(sessions_dir.glob("*.jsonl"))
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

        project_root = get_project_root()
        project_name = get_project_name()
        export_script = project_root / "examples" / "export_session.py"

        # Check if we're in the recursive-ai project with export script
        if not export_script.exists():
            log("Export script not found - install RLM to enable episodic memory")
            sys.exit(0)

        log(f"Archiving conversation before compaction...")
        log(f"Project: {project_name}")
        log(f"Session: {session_file.name}")

        # Export session transcript
        result = subprocess.run(
            ["uv", "run", "python", str(export_script), str(session_file)],
            capture_output=True,
            text=True,
            cwd=project_root,
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
            ["uv", "run", "rlm", "remember", "--stdin", "--tags", tags, "--summary", summary],
            input=transcript,
            text=True,
            cwd=project_root,
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
