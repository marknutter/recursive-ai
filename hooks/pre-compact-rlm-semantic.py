#!/usr/bin/env python3
"""
RLM PreCompact Hook — Archive conversation before compaction.

Uses two-tier storage: summary entry (for fast recall) + full transcript (for drill-down).
"""

import sys
from pathlib import Path

# Resolve symlink to find the RLM project root dynamically.
RLM_PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RLM_PROJECT))

from rlm.archive import get_session_file, mark_as_archived, archive_session


def main():
    try:
        session_file = get_session_file()
        if not session_file:
            print("[RLM-PreCompact] No session file found", file=sys.stderr)
            sys.exit(0)

        if archive_session(session_file, hook_name="RLM-PreCompact"):
            mark_as_archived(session_file)

    except Exception as err:
        print(f"[RLM-PreCompact] Error: {err}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
