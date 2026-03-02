"""Scratchpad: short-lived working memory for in-progress RLM analyses.

Based on the "Everything is Context" paper's concept of scratchpad files as
temporary working memory that exists between analysis steps but doesn't
permanently occupy long-term memory.

Scratchpad entries:
- Are stored in the same SQLite DB as long-term memory (separate table)
- Auto-expire after a configurable TTL (default: 24 hours)
- Can be promoted to long-term memory when the analysis is complete
- Are associated with an optional RLM analysis session ID

Usage:
    from rlm import scratchpad

    # Save intermediate analysis state
    entry = scratchpad.save("Found 3 security issues in auth module", label="auth-scan")

    # Get an entry
    entry = scratchpad.get(entry_id)

    # List active entries
    entries = scratchpad.list_entries()

    # Promote to long-term memory
    memory_id = scratchpad.promote(entry_id, tags=["security", "auth"])

    # Clear all entries (or just expired ones)
    scratchpad.clear()
"""

import time
import uuid
from typing import Optional

from rlm import db, memory

DEFAULT_TTL_HOURS = 24


def save(
    content: str,
    label: str = "",
    tags: list[str] | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    analysis_session: str | None = None,
) -> dict:
    """Save a scratchpad entry.

    Args:
        content: The text content to save (intermediate analysis results, notes, etc.)
        label: Short human-readable label for this entry
        tags: Optional list of tags for later filtering/searching
        ttl_hours: Hours until this entry auto-expires (default: 24)
        analysis_session: Optional RLM session ID this entry is associated with

    Returns:
        Dict with entry metadata (id, label, created_at, expires_at, etc.)
    """
    memory.init_memory_store()

    now = time.time()
    entry_id = f"scratch-{uuid.uuid4().hex[:12]}"
    expires_at = now + (ttl_hours * 3600)

    db.insert_scratchpad(
        entry_id=entry_id,
        label=label or content[:60].replace("\n", " "),
        content=content,
        tags=tags or [],
        created_at=now,
        expires_at=expires_at,
        analysis_session=analysis_session,
    )

    return {
        "id": entry_id,
        "label": label,
        "char_count": len(content),
        "tags": tags or [],
        "created_at": now,
        "expires_at": expires_at,
        "analysis_session": analysis_session,
        "ttl_hours": ttl_hours,
    }


def get(entry_id: str) -> dict | None:
    """Retrieve a scratchpad entry by ID.

    Returns the full entry dict including content, or None if not found.
    Note: Returns the entry even if expired (callers can check expires_at).
    """
    memory.init_memory_store()
    return db.get_scratchpad_entry(entry_id)


def list_entries(include_expired: bool = False) -> list[dict]:
    """List scratchpad entries.

    Args:
        include_expired: If True, include entries past their TTL.

    Returns:
        List of entry metadata dicts (content is included).
    """
    memory.init_memory_store()
    return db.list_scratchpad_entries(include_expired=include_expired)


def clear(expired_only: bool = False) -> int:
    """Clear scratchpad entries.

    Args:
        expired_only: If True, only remove expired entries. Otherwise removes all.

    Returns:
        Number of entries deleted.
    """
    memory.init_memory_store()
    return db.clear_scratchpad(expired_only=expired_only)


def delete(entry_id: str) -> bool:
    """Delete a specific scratchpad entry.

    Returns:
        True if found and deleted, False if not found.
    """
    memory.init_memory_store()
    return db.delete_scratchpad_entry(entry_id)


def promote(
    entry_id: str,
    tags: list[str] | None = None,
    summary: str | None = None,
) -> dict | None:
    """Promote a scratchpad entry to long-term memory.

    Reads the scratchpad entry, stores it via the memory system, then
    deletes it from the scratchpad.

    Args:
        entry_id: ID of the scratchpad entry to promote
        tags: Additional tags to attach (merged with entry's existing tags)
        summary: Override the memory summary (defaults to entry label)

    Returns:
        The new memory entry dict, or None if entry not found.
    """
    memory.init_memory_store()

    entry = db.get_scratchpad_entry(entry_id)
    if entry is None:
        return None

    # Merge tags: entry tags + any new tags
    all_tags = list(entry.get("tags", []))
    if tags:
        for t in tags:
            if t not in all_tags:
                all_tags.append(t)

    # Add scratchpad provenance tag
    if "scratchpad" not in all_tags:
        all_tags.append("scratchpad")

    mem_summary = summary or entry.get("label") or entry["content"][:80]

    result = memory.add_memory(
        content=entry["content"],
        tags=all_tags,
        source="scratchpad",
        source_name=entry_id,
        summary=mem_summary,
    )

    # Remove from scratchpad now that it's in long-term memory
    db.delete_scratchpad_entry(entry_id)

    return result


def format_entry_list(entries: list[dict]) -> str:
    """Format a list of scratchpad entries for CLI display."""
    if not entries:
        return "No scratchpad entries."

    import datetime

    lines = [f"Scratchpad entries ({len(entries)}):\n"]
    now = time.time()

    for e in entries:
        entry_id = e["id"]
        label = e.get("label") or "(no label)"
        tags = e.get("tags", [])
        char_count = len(e.get("content", ""))
        created = datetime.datetime.fromtimestamp(e["created_at"]).strftime("%Y-%m-%d %H:%M")
        expires = e["expires_at"]

        if expires <= now:
            ttl_str = "EXPIRED"
        else:
            remaining_h = (expires - now) / 3600
            if remaining_h < 1:
                ttl_str = f"expires in {int(remaining_h * 60)}m"
            else:
                ttl_str = f"expires in {remaining_h:.1f}h"

        line = f"  {entry_id}  {label[:50]}"
        if tags:
            line += f"  [{', '.join(tags[:3])}]"
        line += f"  ({char_count:,} chars, {created}, {ttl_str})"
        if e.get("analysis_session"):
            line += f"  session={e['analysis_session']}"
        lines.append(line)

    return "\n".join(lines)


def format_entry(entry: dict) -> str:
    """Format a single scratchpad entry for CLI display."""
    import datetime

    now = time.time()
    created = datetime.datetime.fromtimestamp(entry["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
    expires = entry["expires_at"]

    if expires <= now:
        ttl_str = "EXPIRED"
    else:
        remaining_h = (expires - now) / 3600
        if remaining_h < 1:
            ttl_str = f"expires in {int(remaining_h * 60)}m"
        else:
            ttl_str = f"expires in {remaining_h:.1f}h"

    lines = [
        f"ID:       {entry['id']}",
        f"Label:    {entry.get('label') or '(none)'}",
        f"Created:  {created}",
        f"Expires:  {ttl_str}",
        f"Tags:     {', '.join(entry.get('tags', [])) or '(none)'}",
        f"Size:     {len(entry.get('content', '')):,} chars",
    ]
    if entry.get("analysis_session"):
        lines.append(f"Session:  {entry['analysis_session']}")
    lines.append("")
    lines.append(entry.get("content", ""))
    return "\n".join(lines)
