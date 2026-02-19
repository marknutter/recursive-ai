#!/usr/bin/env python3
"""
RLM SessionEnd Hook — Archive conversation on session end.

Uses two-tier storage: summary entry (for fast recall) + full transcript (for drill-down).
Skips if already archived by PreCompact hook within the last 60 seconds.
Reads transcript_path and cwd from stdin JSON provided by Claude Code.
"""

import json
import sys
import time
from pathlib import Path

# Resolve symlink to find the RLM project root dynamically.
RLM_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RLM_PROJECT))

from rlm.archive import get_session_file, mark_as_archived, archive_session


def parse_hook_input() -> dict:
    """Read the JSON hook input from stdin."""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def was_recently_archived(session_file: Path) -> bool:
    """Check if session was archived in the last 60 seconds."""
    marker = session_file.with_suffix(session_file.suffix + ".rlm-archived")
    if not marker.exists():
        return False
    age_seconds = time.time() - marker.stat().st_mtime
    return age_seconds < 60


def main():
    try:
        hook_input = parse_hook_input()

        # Get session file from stdin transcript_path (reliable), or fall back
        session_file = None
        path = hook_input.get("transcript_path")
        if path:
            p = Path(path)
            if p.exists():
                session_file = p

        if not session_file:
            session_file = get_session_file()

        if not session_file:
            print("[RLM-SessionEnd] No session file found", file=sys.stderr)
            sys.exit(0)

        if was_recently_archived(session_file):
            print("[RLM-SessionEnd] Already archived by PreCompact — skipping", file=sys.stderr)
            sys.exit(0)

        cwd = hook_input.get("cwd")
        if archive_session(session_file, hook_name="RLM-SessionEnd", cwd=cwd):
            mark_as_archived(session_file)

    except Exception as err:
        print(f"[RLM-SessionEnd] Error: {err}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
