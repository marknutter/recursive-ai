"""Shared archival logic for PreCompact and SessionEnd hooks.

Implements two-tier storage:
1. Summary entry (~1-4KB) — concise highlights for fast recall
2. Full transcript (~50-80KB) — compressed conversation for drill-down

Both entries share a session_id tag for linking.
"""

import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Resolve to find the RLM project root (this file lives in rlm/)
RLM_PROJECT = Path(__file__).resolve().parent.parent


def log(prefix: str, msg: str):
    print(f"[{prefix}] {msg}", file=sys.stderr)


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
    session_files = list(projects_dir.glob("**/*.jsonl"))
    if not session_files:
        return None
    return max(session_files, key=lambda p: p.stat().st_mtime)


def mark_as_archived(session_file: Path):
    """Create marker file to prevent duplicate archiving."""
    marker = session_file.with_suffix(session_file.suffix + ".rlm-archived")
    marker.write_text(datetime.now().isoformat())


def _store_memory(content: str, tags: str, summary: str):
    """Store a memory entry via the rlm CLI."""
    subprocess.run(
        [
            "uv", "run", "--project", str(RLM_PROJECT),
            "rlm", "remember", "--stdin",
            "--tags", tags,
            "--summary", summary,
        ],
        input=content,
        text=True,
        check=True,
        capture_output=True,
    )


def archive_session(session_file: Path, hook_name: str = "Archive"):
    """Export, compress, summarize, and store a session as two memory entries.

    Args:
        session_file: Path to the Claude Code .jsonl session file.
        hook_name: Log prefix (e.g., "PreCompact" or "SessionEnd").

    Returns:
        True if archival succeeded, False otherwise.
    """
    # Import here to avoid circular imports at module level
    from rlm.semantic_tags import extract_semantic_tags, combine_tags
    from rlm.summarize import generate_summary

    project_name = get_project_name()
    session_id = f"s_{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now().strftime("%Y-%m-%d")

    log(hook_name, f"Archiving session...")
    log(hook_name, f"Project: {project_name}, Session ID: {session_id}")

    # Step 1: Export compressed transcript
    result = subprocess.run(
        [
            "uv", "run", "--project", str(RLM_PROJECT),
            "rlm", "export-session", str(session_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    transcript = result.stdout

    if not transcript or not transcript.strip():
        log(hook_name, "Empty transcript - skipping")
        return False

    # Step 2: Generate semantic tags
    log(hook_name, "Extracting semantic tags...")
    semantic_tags = extract_semantic_tags(transcript)
    base_tags = f"conversation,session,{project_name},{timestamp},{session_id}"

    if semantic_tags:
        tags = combine_tags(base_tags, semantic_tags)
        log(hook_name, f"Semantic tags: {', '.join(semantic_tags)}")
    else:
        tags = base_tags

    # Step 3: Generate summary
    log(hook_name, "Generating session summary...")
    summary_text = generate_summary(transcript)

    # Step 4: Store summary entry (small, dense — primary search target)
    summary_tags = combine_tags(f"summary,session-summary,{tags}", [])
    summary_label = f"Session summary: {project_name} on {timestamp}"
    _store_memory(summary_text, summary_tags, summary_label)
    log(hook_name, f"  Summary: {len(summary_text):,} chars")

    # Step 5: Store full transcript (larger, for drill-down)
    transcript_tags = combine_tags(f"transcript,full-transcript,{tags}", [])
    transcript_label = f"Full transcript: {project_name} on {timestamp}"
    _store_memory(transcript, transcript_tags, transcript_label)
    log(hook_name, f"  Transcript: {len(transcript):,} chars")

    log(hook_name, f"Archived to ~/.rlm/memory/ (session: {session_id})")
    log(hook_name, f"  Tags: {tags}")

    return True
