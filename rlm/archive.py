"""Shared archival logic for PreCompact and SessionEnd hooks.

Implements two-tier storage:
1. Summary entry (~1-4KB) — concise highlights for fast recall
2. Full transcript (~50-80KB) — compressed conversation for drill-down

Both entries share a session_id tag for linking.

Content deduplication: uses session JSONL filename as identifier.
Skips if file unchanged since last archive, replaces if new content exists.
"""

import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from rlm import db, memory

# Resolve to find the RLM project root (this file lives in rlm/)
RLM_PROJECT = Path(__file__).resolve().parent.parent


def log(prefix: str, msg: str):
    print(f"[{prefix}] {msg}", file=sys.stderr)


def get_project_name(cwd: str | None = None) -> str:
    """Get current project directory name from git root, or cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
            cwd=cwd,
        )
        return Path(result.stdout.strip()).name
    except subprocess.CalledProcessError:
        return Path(cwd).name if cwd else Path.cwd().name


def get_session_file() -> Path | None:
    """Find the most recent .jsonl session file."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return None
    session_files = list(projects_dir.glob("**/*.jsonl"))
    if not session_files:
        return None
    return max(session_files, key=lambda p: p.stat().st_mtime)


def mark_as_archived(session_file: Path, file_size: int | None = None):
    """Create marker file to prevent duplicate archiving.

    Stores the file size so we can detect changes on next archive attempt.
    """
    marker = session_file.with_suffix(session_file.suffix + ".rlm-archived")
    size = file_size if file_size is not None else session_file.stat().st_size
    marker.write_text(f"{datetime.now().isoformat()}\n{size}")


def read_archived_size(session_file: Path) -> int | None:
    """Read the file size stored in the archive marker, if it exists."""
    marker = session_file.with_suffix(session_file.suffix + ".rlm-archived")
    if not marker.exists():
        return None
    try:
        lines = marker.read_text().strip().split("\n")
        if len(lines) >= 2:
            return int(lines[1])
    except (ValueError, OSError):
        pass
    return None


def archive_session(session_file: Path, hook_name: str = "Archive", cwd: str | None = None):
    """Export, compress, summarize, and store a session as two memory entries.

    Deduplication: uses the session JSONL filename as an identifier.
    - If no prior archive exists for this file → archive normally
    - If file size is unchanged since last archive → skip
    - If file has grown → delete old entries and re-archive

    Args:
        session_file: Path to the Claude Code .jsonl session file.
        hook_name: Log prefix (e.g., "PreCompact" or "SessionEnd").

    Returns:
        True if archival succeeded, False otherwise.
    """
    # Import here to avoid circular imports at module level
    from rlm.semantic_tags import extract_semantic_tags, combine_tags
    from rlm.summarize import generate_summary

    memory.init_memory_store()

    session_filename = session_file.name
    current_file_size = session_file.stat().st_size

    # --- Dedup check ---
    # First check the marker file (fast, no DB query needed)
    archived_size = read_archived_size(session_file)
    if archived_size is not None and archived_size == current_file_size:
        log(hook_name, f"Already archived, file unchanged ({session_filename}) — skipping")
        return False

    # File has changed or no marker — check DB for existing entries to replace
    existing = db.find_entries_by_source_name(session_filename)
    if existing:
        log(hook_name, f"Session has new content — replacing {len(existing)} old entries")
        for entry in existing:
            db.delete_entry(entry["id"])

    # --- Archive ---
    project_name = get_project_name(cwd=cwd)
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
    base_tags = [
        "conversation", "session", project_name, timestamp, session_id,
    ]

    if semantic_tags:
        all_tags = combine_tags(",".join(base_tags), semantic_tags)
        log(hook_name, f"Semantic tags: {', '.join(semantic_tags)}")
    else:
        all_tags = ",".join(base_tags)

    # Step 3: Generate summary
    log(hook_name, "Generating session summary...")
    summary_text = generate_summary(transcript)

    # Step 4: Store summary entry (small, dense — primary search target)
    summary_tags_str = combine_tags(f"summary,session-summary,{all_tags}", [])
    summary_tags_list = [t.strip() for t in summary_tags_str.split(",") if t.strip()]
    summary_label = f"Session summary: {project_name} on {timestamp}"
    memory.add_memory(
        content=summary_text,
        tags=summary_tags_list,
        source="session-summary",
        source_name=session_filename,
        summary=summary_label,
    )
    log(hook_name, f"  Summary: {len(summary_text):,} chars")

    # Step 5: Store full transcript (larger, for drill-down)
    transcript_tags_str = combine_tags(f"transcript,full-transcript,{all_tags}", [])
    transcript_tags_list = [t.strip() for t in transcript_tags_str.split(",") if t.strip()]
    transcript_label = f"Full transcript: {project_name} on {timestamp}"
    memory.add_memory(
        content=transcript,
        tags=transcript_tags_list,
        source="session-transcript",
        source_name=session_filename,
        summary=transcript_label,
    )
    log(hook_name, f"  Transcript: {len(transcript):,} chars")

    log(hook_name, f"Archived to ~/.rlm/memory/ (session: {session_id})")

    # Update marker with current file size
    mark_as_archived(session_file, file_size=current_file_size)

    return True
