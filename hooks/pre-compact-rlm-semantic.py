#!/usr/bin/env python3
"""
RLM PreCompact Hook — Archive conversation before compaction.

Uses two-tier storage: summary entry (for fast recall) + full transcript (for drill-down).
Reads transcript_path and cwd from stdin JSON provided by Claude Code.
"""

import json
import sys
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
            print("[RLM-PreCompact] No session file found", file=sys.stderr)
            sys.exit(0)

        cwd = hook_input.get("cwd")
        if archive_session(session_file, hook_name="RLM-PreCompact", cwd=cwd):
            mark_as_archived(session_file)

    except Exception as err:
        print(f"[RLM-PreCompact] Error: {err}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
