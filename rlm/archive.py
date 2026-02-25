"""Shared archival logic for PreCompact and SessionEnd hooks.

Implements two-tier storage:
1. Summary entry (~1-4KB) — concise highlights for fast recall
2. Full transcript (~50-80KB) — compressed conversation for drill-down

Both entries share a session_id tag for linking.

Content deduplication: uses session JSONL filename as identifier.
Skips if file unchanged since last archive, replaces if new content exists.

The smart_remember() function generalizes the pipeline (semantic tags,
summary generation, facts extraction) to work with ANY content type,
not just .jsonl session files.
"""

import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from rlm import db, memory

# Content above this threshold gets two-tier storage (summary + full content).
# Below this, a single entry is stored with smart tags.
SUMMARY_THRESHOLD = 4000

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


def smart_remember(
    content: str,
    source: str,
    source_name: str | None = None,
    user_tags: list[str] | None = None,
    label: str | None = None,
    dedup: bool = False,
    log_prefix: str = "Remember",
) -> dict:
    """Run content through the smart remember pipeline.

    Pipeline: semantic tags → summary (if large) → store → facts extraction.

    For content above SUMMARY_THRESHOLD, creates two entries:
      1. Summary entry (small, dense — primary search target)
      2. Full content entry (for drill-down)

    For smaller content, creates a single entry with smart tags.

    Args:
        content: The text to remember.
        source: Source type (e.g., "text", "file", "session", "url", "stdin").
        source_name: Identifier for dedup (e.g., filename, URL).
        user_tags: Caller-provided tags to include.
        label: Human-readable label for the entry.
        dedup: If True and source_name given, replace existing entries.
        log_prefix: Prefix for log messages.

    Returns:
        Dict with: summary_id, content_id (if two-tier), facts_count, tags.
    """
    from rlm.semantic_tags import extract_semantic_tags, combine_tags
    from rlm.summarize import generate_summary

    memory.init_memory_store()

    user_tags = user_tags or []

    # Dedup: remove existing entries with same source_name
    if dedup and source_name:
        existing = db.find_entries_by_source_name(source_name)
        if existing:
            log(log_prefix, f"Replacing {len(existing)} existing entries for {source_name}")
            for entry in existing:
                db.delete_entry(entry["id"])

    # Step 1: Generate semantic tags
    log(log_prefix, "Extracting semantic tags...")
    semantic_tags = extract_semantic_tags(content)
    base_str = ",".join(user_tags) if user_tags else ""
    if base_str or semantic_tags:
        all_tags_str = combine_tags(base_str, semantic_tags) if base_str else ",".join(semantic_tags)
        all_tags = [t.strip() for t in all_tags_str.split(",") if t.strip()]
    else:
        all_tags = []

    if semantic_tags:
        log(log_prefix, f"Semantic tags: {', '.join(semantic_tags)}")

    result = {"tags": all_tags, "facts_count": 0}
    facts_input = None  # Track best input for fact extraction

    # Step 2: Store entries
    if len(content) > SUMMARY_THRESHOLD:
        # Two-tier: summary + full content
        log(log_prefix, "Generating summary...")
        summary_text = generate_summary(content)

        summary_entry_tags = ["summary"] + all_tags
        summary_label = label or f"Summary: {source_name or source}"
        summary_result = memory.add_memory(
            content=summary_text,
            tags=summary_entry_tags,
            source=f"{source}-summary",
            source_name=source_name,
            summary=summary_label,
        )
        result["summary_id"] = summary_result["id"]
        result["summary"] = summary_result["summary"]
        log(log_prefix, f"  Summary: {len(summary_text):,} chars")

        content_entry_tags = ["full-content"] + all_tags
        content_label = f"Full content: {source_name or source}"
        content_result = memory.add_memory(
            content=content,
            tags=content_entry_tags,
            source=source,
            source_name=source_name,
            summary=content_label,
        )
        result["content_id"] = content_result["id"]
        log(log_prefix, f"  Full content: {len(content):,} chars")

        primary_entry_id = summary_result["id"]

        # Use summary for fact extraction — it's already distilled and
        # high-signal, avoiding the lossy head/tail truncation of raw
        # transcripts that drops mid-conversation context.  (#47)
        facts_input = summary_text
    else:
        # Single entry with smart tags
        entry_result = memory.add_memory(
            content=content,
            tags=all_tags if all_tags else None,
            source=source,
            source_name=source_name,
            summary=label,
        )
        result["summary_id"] = entry_result["id"]
        result["summary"] = entry_result["summary"]
        log(log_prefix, f"  Stored: {len(content):,} chars")
        primary_entry_id = entry_result["id"]

    # Step 3: Extract structured facts
    # For large content, use the summary (dense, no truncation needed).
    # For small content, use the raw content directly.
    facts_text = facts_input or content
    log(log_prefix, "Extracting structured facts...")
    try:
        from rlm.facts import extract_facts_from_transcript, store_facts

        raw_facts = extract_facts_from_transcript(
            facts_text, source_entry_id=primary_entry_id,
        )
        if raw_facts:
            stored_count = store_facts(raw_facts)
            result["facts_count"] = stored_count
            log(log_prefix, f"  Facts: {stored_count} extracted and stored")
        else:
            log(log_prefix, "  Facts: none extracted")
    except Exception as e:
        log(log_prefix, f"  Facts extraction failed (non-fatal): {e}")

    return result


def archive_session(session_file: Path, hook_name: str = "Archive", cwd: str | None = None):
    """Export, compress, and store a session via the smart remember pipeline.

    Deduplication: uses the session JSONL filename as an identifier.
    - If no prior archive exists for this file → archive normally
    - If file size is unchanged since last archive → skip
    - If file has grown → delete old entries and re-archive

    Args:
        session_file: Path to the Claude Code .jsonl session file.
        hook_name: Log prefix (e.g., "PreCompact" or "SessionEnd").
        cwd: Working directory for project name detection.

    Returns:
        True if archival succeeded, False otherwise.
    """
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

    # --- Export transcript ---
    project_name = get_project_name(cwd=cwd)
    session_id = f"s_{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now().strftime("%Y-%m-%d")

    log(hook_name, f"Archiving session...")
    log(hook_name, f"Project: {project_name}, Session ID: {session_id}")

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

    # --- Run through smart pipeline ---
    base_tags = ["conversation", "session", project_name, timestamp, session_id]
    label = f"Session: {project_name} on {timestamp}"

    smart_remember(
        content=transcript,
        source="session",
        source_name=session_filename,
        user_tags=base_tags,
        label=label,
        dedup=False,  # Already handled above
        log_prefix=hook_name,
    )

    log(hook_name, f"Archived to ~/.rlm/memory/ (session: {session_id})")

    # Update marker with current file size
    mark_as_archived(session_file, file_size=current_file_size)

    return True
