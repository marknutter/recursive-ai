"""Persistent long-term memory system.

Stores knowledge entries in ~/.rlm/memory/ with a lightweight index
for fast search and bounded output. Follows the same patterns as state.py:
file-based JSON persistence, error dicts, atomic writes.
"""

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

MEMORY_DIR = os.path.expanduser("~/.rlm/memory")
ENTRIES_DIR = os.path.join(MEMORY_DIR, "entries")
INDEX_PATH = os.path.join(MEMORY_DIR, "index.json")

# Words to exclude from auto-tagging
STOP_WORDS = {
    "the", "and", "for", "that", "this", "with", "from", "are", "was",
    "were", "been", "being", "have", "has", "had", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall", "not",
    "but", "into", "about", "than", "then", "when", "where", "which",
    "while", "also", "each", "other", "some", "such", "only", "very",
    "just", "over", "after", "before", "between", "through", "during",
    "without", "again", "further", "once", "here", "there", "all", "both",
    "more", "most", "same", "own", "too", "any", "how", "what", "who",
    "whom", "why", "these", "those", "above", "below", "under", "use",
    "used", "using", "because", "like", "make", "made",
}


def init_memory_store():
    """Create memory directories and index if they don't exist."""
    os.makedirs(ENTRIES_DIR, exist_ok=True)
    if not os.path.isfile(INDEX_PATH):
        _save_index([])


def load_index() -> list[dict]:
    """Load the memory index."""
    if not os.path.isfile(INDEX_PATH):
        return []
    try:
        with open(INDEX_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(entries: list[dict]):
    """Write the full index atomically (tempfile + rename)."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=MEMORY_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp_path, INDEX_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def add_memory(
    content: str,
    tags: list[str] | None = None,
    source: str = "text",
    source_name: str | None = None,
    summary: str | None = None,
) -> dict:
    """Store a new memory entry.

    Returns dict with id, summary, tags, char_count.
    """
    init_memory_store()

    entry_id = "m_" + uuid.uuid4().hex[:12]
    timestamp = time.time()

    if summary is None:
        summary = _auto_summary(content)
    else:
        summary = summary[:80]

    if tags is None:
        tags = _auto_tags(content)
    else:
        tags = [t.strip().lower() for t in tags if t.strip()]

    # Build full entry
    entry = {
        "id": entry_id,
        "summary": summary,
        "tags": tags,
        "timestamp": timestamp,
        "source": source,
        "source_name": source_name,
        "char_count": len(content),
        "content": content,
    }

    # Chunk large content
    if len(content) > 10000:
        entry["chunks"] = _chunk_content(content, entry_id)

    # Write entry file
    entry_path = os.path.join(ENTRIES_DIR, f"{entry_id}.json")
    with open(entry_path, "w") as f:
        json.dump(entry, f, indent=2)

    # Update index
    index = load_index()
    index_entry = {
        "id": entry_id,
        "summary": summary,
        "tags": tags,
        "timestamp": timestamp,
        "source": source,
        "source_name": source_name,
        "char_count": len(content),
    }
    index.append(index_entry)
    _save_index(index)

    return {
        "id": entry_id,
        "summary": summary,
        "tags": tags,
        "char_count": len(content),
    }


def get_memory(entry_id: str) -> dict:
    """Load a full memory entry by ID."""
    entry_path = os.path.join(ENTRIES_DIR, f"{entry_id}.json")
    if not os.path.isfile(entry_path):
        return {"error": f"Memory entry not found: {entry_id}"}
    try:
        with open(entry_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to load entry: {e}"}


def get_memory_content(entry_id: str, chunk_id: str | None = None) -> str:
    """Extract content from a memory entry.

    If chunk_id provided, return only that chunk's content.
    """
    entry = get_memory(entry_id)
    if "error" in entry:
        return f"Error: {entry['error']}"

    content = entry.get("content", "")

    if chunk_id and "chunks" in entry:
        for chunk in entry["chunks"]:
            if chunk["chunk_id"] == chunk_id:
                start = chunk["start_char"]
                end = chunk["end_char"]
                return content[start:end]
        return f"Error: Chunk {chunk_id} not found in entry {entry_id}"

    return content


def search_index(
    query: str,
    tags: list[str] | None = None,
    max_results: int = 20,
    deep: bool = False,
) -> list[dict]:
    """Search the memory index by keyword scoring.

    Scoring:
    - +3 for each query keyword found in summary
    - +2 for each query keyword matching a tag exactly
    - +1 for partial matches (keyword is substring of tag or summary word)
    - If deep=True, also scan entry content (+1 per keyword found in content)
    """
    index = load_index()
    if not index:
        return []

    keywords = _tokenize(query)
    if not keywords:
        return index[:max_results]

    # Filter by tags if provided
    if tags:
        tags_lower = {t.strip().lower() for t in tags}
        index = [e for e in index if tags_lower & set(e.get("tags", []))]

    scored = []
    for entry in index:
        score = 0
        summary_lower = entry.get("summary", "").lower()
        entry_tags = [t.lower() for t in entry.get("tags", [])]

        for kw in keywords:
            # Exact match in summary words
            if kw in summary_lower.split():
                score += 3
            # Substring match in summary
            elif kw in summary_lower:
                score += 1

            # Exact tag match
            if kw in entry_tags:
                score += 2
            else:
                # Partial tag match
                for tag in entry_tags:
                    if kw in tag or tag in kw:
                        score += 1
                        break

        # Deep search: scan actual content
        if deep:
            content = _load_content_for_search(entry["id"])
            if content:
                content_lower = content.lower()
                for kw in keywords:
                    if kw in content_lower:
                        score += 1

        if score > 0:
            scored.append({**entry, "score": score})

    scored.sort(key=lambda x: (-x["score"], -x.get("timestamp", 0)))
    return scored[:max_results]


def _load_content_for_search(entry_id: str) -> str | None:
    """Load just the content field from an entry for search purposes."""
    entry_path = os.path.join(ENTRIES_DIR, f"{entry_id}.json")
    if not os.path.isfile(entry_path):
        return None
    try:
        with open(entry_path, "r") as f:
            entry = json.load(f)
        return entry.get("content", "")
    except (json.JSONDecodeError, OSError):
        return None


def delete_memory(entry_id: str) -> dict:
    """Remove a memory entry and update the index."""
    entry_path = os.path.join(ENTRIES_DIR, f"{entry_id}.json")
    if not os.path.isfile(entry_path):
        return {"error": f"Memory entry not found: {entry_id}"}

    try:
        os.unlink(entry_path)
    except OSError as e:
        return {"error": f"Failed to delete entry: {e}"}

    index = load_index()
    index = [e for e in index if e["id"] != entry_id]
    _save_index(index)

    return {"status": "deleted", "id": entry_id}


def list_tags() -> dict[str, int]:
    """Return all tags with their frequency counts."""
    index = load_index()
    tag_counts: dict[str, int] = {}
    for entry in index:
        for tag in entry.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return dict(sorted(tag_counts.items(), key=lambda x: (-x[1], x[0])))


def format_index_summary(
    entries: list[dict] | None = None,
    tags: list[str] | None = None,
    offset: int = 0,
    limit: int = 50,
    max_chars: int = 4000,
) -> str:
    """Format index entries into bounded human-readable summary."""
    if entries is None:
        entries = load_index()

    if tags:
        tags_lower = {t.strip().lower() for t in tags}
        entries = [e for e in entries if tags_lower & set(e.get("tags", []))]

    total = len(entries)
    entries = entries[offset:offset + limit]

    lines = [f"Memory Store: {total} entries total"]
    if offset > 0 or len(entries) < total:
        lines[0] += f" (showing {offset + 1}-{offset + len(entries)})"
    lines.append("")

    for entry in entries:
        eid = entry["id"]
        summary = entry.get("summary", "")
        entry_tags = ", ".join(entry.get("tags", []))
        chars = entry.get("char_count", 0)
        source = entry.get("source", "text")

        line = f"  {eid}  {summary}"
        if entry_tags:
            line += f"  [{entry_tags}]"
        line += f"  ({chars:,} chars, {source})"
        lines.append(line)

        current = "\n".join(lines)
        if len(current) > max_chars - 100:
            remaining = total - entries.index(entry) - 1
            if remaining > 0:
                lines.append(f"\n  ... and {remaining} more entries (use --offset to paginate)")
            break

    return "\n".join(lines)


def format_search_results(results: list[dict], max_chars: int = 4000) -> str:
    """Format search results into bounded output."""
    if not results:
        return "No matching memories found."

    lines = [f"Found {len(results)} matching memories:\n"]

    for r in results:
        eid = r["id"]
        summary = r.get("summary", "")
        score = r.get("score", 0)
        entry_tags = ", ".join(r.get("tags", []))
        chars = r.get("char_count", 0)

        line = f"  [{score:2d}] {eid}  {summary}"
        if entry_tags:
            line += f"  [{entry_tags}]"
        line += f"  ({chars:,} chars)"
        lines.append(line)

        current = "\n".join(lines)
        if len(current) > max_chars - 100:
            remaining = len(results) - results.index(r) - 1
            if remaining > 0:
                lines.append(f"\n  ... and {remaining} more results")
            break

    return "\n".join(lines)


# --- Internal helpers ---


def _auto_summary(content: str) -> str:
    """Generate a summary from content.

    Uses the first meaningful line, stripped of markdown formatting.
    """
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip markdown heading markers
        line = re.sub(r"^#+\s*", "", line)
        # Strip code fences
        if line.startswith("```"):
            continue
        # Strip markdown formatting
        line = re.sub(r"[*_`~]", "", line)
        line = line.strip()
        if line:
            if len(line) > 80:
                # Truncate at word boundary
                line = line[:80]
                last_space = line.rfind(" ")
                if last_space > 40:
                    line = line[:last_space]
            return line

    return content[:80].strip() if content else "(empty)"


def _auto_tags(content: str) -> list[str]:
    """Extract candidate tags from content via word frequency."""
    # Tokenize
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", content.lower())
    words = [w for w in words if len(w) > 3 and w not in STOP_WORDS]

    # Count frequencies
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1

    # Keep words appearing 2+ times, sorted by frequency
    candidates = [(w, c) for w, c in freq.items() if c >= 2]
    candidates.sort(key=lambda x: -x[1])

    return [w for w, _ in candidates[:8]]


def _tokenize(text: str) -> list[str]:
    """Tokenize a query string into lowercase keywords."""
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
    return [w for w in words if len(w) > 2 and w not in STOP_WORDS]


def _chunk_content(content: str, entry_id: str) -> list[dict]:
    """Split large content into chunks using blank-line boundaries.

    Returns list of chunk metadata dicts (not content itself).
    """
    import hashlib

    target_size = 5000  # chars per chunk
    chunks = []
    paragraphs = re.split(r"\n\s*\n", content)

    current_start = 0
    current_text = ""

    for para in paragraphs:
        if current_text and len(current_text) + len(para) > target_size:
            # Emit current chunk
            end_char = current_start + len(current_text)
            chunk_id = "mc_" + hashlib.md5(
                f"{entry_id}:{current_start}:{end_char}".encode()
            ).hexdigest()[:10]
            chunks.append({
                "chunk_id": chunk_id,
                "start_char": current_start,
                "end_char": end_char,
                "char_count": len(current_text),
                "preview": current_text[:80].strip(),
            })
            current_start = end_char
            current_text = para
        else:
            if current_text:
                current_text += "\n\n" + para
            else:
                current_text = para

    # Emit final chunk
    if current_text:
        end_char = current_start + len(current_text)
        chunk_id = "mc_" + hashlib.md5(
            f"{entry_id}:{current_start}:{end_char}".encode()
        ).hexdigest()[:10]
        chunks.append({
            "chunk_id": chunk_id,
            "start_char": current_start,
            "end_char": end_char,
            "char_count": len(current_text),
            "preview": current_text[:80].strip(),
        })

    return chunks
