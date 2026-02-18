#!/usr/bin/env python3
"""
RLM SessionEnd Hook — Archive conversation on session end.

Uses two-tier storage: summary entry (for fast recall) + full transcript (for drill-down).
Skips if already archived by PreCompact hook within the last 60 seconds.
"""

import sys
import time
from pathlib import Path

# Resolve symlink to find the RLM project root dynamically.
RLM_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RLM_PROJECT))

from rlm.archive import get_session_file, mark_as_archived, archive_session


def was_recently_archived(session_file: Path) -> bool:
    """Check if session was archived in the last 60 seconds."""
    marker = session_file.with_suffix(session_file.suffix + ".rlm-archived")
    if not marker.exists():
        return False
    age_seconds = time.time() - marker.stat().st_mtime
    return age_seconds < 60


def main():
    try:
        session_file = get_session_file()
        if not session_file:
            print("[RLM-SessionEnd] No session file found", file=sys.stderr)
            sys.exit(0)

        if was_recently_archived(session_file):
            print("[RLM-SessionEnd] Already archived by PreCompact — skipping", file=sys.stderr)
            sys.exit(0)

        if archive_session(session_file, hook_name="RLM-SessionEnd"):
            mark_as_archived(session_file)

    except Exception as err:
        print(f"[RLM-SessionEnd] Error: {err}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
