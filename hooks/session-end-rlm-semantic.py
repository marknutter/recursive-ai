#!/usr/bin/env python3
"""
RLM SessionEnd Hook with Semantic Tagging - Archive conversation on session end

Saves conversation transcript to episodic memory when session ends,
with LLM-generated semantic tags for improved recall quality.
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime
import time

# Resolve symlink to find the RLM project root dynamically.
# This file is symlinked from ~/.claude/hooks/ → {rlm_root}/hooks/
RLM_PROJECT = Path(__file__).resolve().parent.parent

# Add RLM project to path for imports
sys.path.insert(0, str(RLM_PROJECT))

from rlm.semantic_tags import extract_semantic_tags, combine_tags


def log(msg: str):
    print(f"[RLM-SessionEnd] {msg}", file=sys.stderr)


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


def was_recently_archived(session_file: Path) -> bool:
    """Check if session was archived in the last 60 seconds."""
    marker = session_file.with_suffix(session_file.suffix + ".rlm-archived")

    if not marker.exists():
        return False

    age_seconds = time.time() - marker.stat().st_mtime
    return age_seconds < 60


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

        # Skip if recently archived by PreCompact hook
        if was_recently_archived(session_file):
            log("Session already archived by PreCompact hook - skipping")
            sys.exit(0)

        project_name = get_project_name()

        log(f"Archiving session on end...")
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

        # Extract semantic tags from the transcript
        log("Extracting semantic tags...")
        semantic_tags = extract_semantic_tags(transcript)

        # Build combined tags
        timestamp = datetime.now().strftime("%Y-%m-%d")
        base_tags = f"conversation,session,{project_name},{timestamp}"

        if semantic_tags:
            tags = combine_tags(base_tags, semantic_tags)
            log(f"Generated semantic tags: {', '.join(semantic_tags)}")
        else:
            tags = base_tags
            log("No semantic tags generated (using base tags only)")

        summary = f"Conversation in {project_name} on {timestamp}"

        # Store in RLM memory with enriched tags
        subprocess.run(
            ["uv", "run", "--project", str(RLM_PROJECT), "rlm", "remember", "--stdin", "--tags", tags, "--summary", summary],
            input=transcript,
            text=True,
            check=True,
            capture_output=True,
        )

        # Mark as archived to prevent duplicate archiving
        mark_as_archived(session_file)

        log(f"✓ Session archived to ~/.rlm/memory/")
        log(f"  Tags: {tags}")
        log(f"  Size: {len(transcript):,} chars")

    except Exception as err:
        log(f"Error: {err}")
        # Don't fail session end if archiving fails
        sys.exit(0)


if __name__ == "__main__":
    main()