"""SQLite FTS5 database backend for persistent memory.

Replaces the JSON index + individual entry files with a single SQLite
database at ~/.rlm/memory/memory.db. Uses FTS5 for full-text search
with BM25 ranking and Porter stemming.

Zero external dependencies -- sqlite3 is in Python's stdlib.
"""

import atexit
import json
import os
import re
import sqlite3
import threading

MEMORY_DIR = os.path.expanduser("~/.rlm/memory")
DB_PATH = os.path.join(MEMORY_DIR, "memory.db")

# Thread-local connections (sqlite3 objects can't cross threads)
_local = threading.local()


def _cleanup():
    """Close connection on process exit."""
    close()


atexit.register(_cleanup)


def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(_local.conn)
    return _local.conn


def _init_schema(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    # Main entries table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            timestamp REAL NOT NULL,
            source TEXT NOT NULL DEFAULT 'text',
            source_name TEXT,
            char_count INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL DEFAULT '',
            chunks TEXT  -- JSON array of chunk metadata, NULL if not chunked
        )
    """)

    # FTS5 virtual table -- check if it exists before creating.
    # FTS5 virtual tables don't support IF NOT EXISTS reliably.
    # Note: TEXT PRIMARY KEY still has an implicit rowid in SQLite
    # (unless WITHOUT ROWID is declared). The FTS5 content sync
    # relies on this implicit rowid via the triggers below.
    fts_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'"
    ).fetchone()

    if not fts_exists:
        conn.execute("""
            CREATE VIRTUAL TABLE entries_fts USING fts5(
                summary,
                tags,
                content,
                content='entries',
                content_rowid='rowid',
                tokenize='porter unicode61'
            )
        """)

    # Triggers to keep FTS index in sync with entries table
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
            INSERT INTO entries_fts(rowid, summary, tags, content)
            VALUES (new.rowid, new.summary, new.tags, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, summary, tags, content)
            VALUES ('delete', old.rowid, old.summary, old.tags, old.content);
        END;

        CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, summary, tags, content)
            VALUES ('delete', old.rowid, old.summary, old.tags, old.content);
            INSERT INTO entries_fts(rowid, summary, tags, content)
            VALUES (new.rowid, new.summary, new.tags, new.content);
        END;
    """)
    conn.commit()


def close():
    """Close the thread-local connection."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


# --- CRUD operations ---


def insert_entry(
    entry_id: str,
    summary: str,
    tags: list[str],
    timestamp: float,
    source: str,
    source_name: str | None,
    char_count: int,
    content: str,
    chunks: list[dict] | None = None,
    auto_commit: bool = True,
) -> None:
    """Insert a new memory entry. Replaces if entry_id already exists.

    Args:
        auto_commit: If False, caller must commit manually. Use False for bulk inserts.
    """
    conn = _get_conn()
    tags_json = json.dumps(tags)
    chunks_json = json.dumps(chunks) if chunks is not None else None
    conn.execute(
        """INSERT OR REPLACE INTO entries (id, summary, tags, timestamp, source,
                                           source_name, char_count, content, chunks)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entry_id, summary, tags_json, timestamp, source, source_name,
         char_count, content, chunks_json),
    )
    if auto_commit:
        conn.commit()


def source_name_exists(source_name: str) -> bool:
    """Check if an entry with this source_name already exists."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM entries WHERE source_name = ? LIMIT 1", (source_name,)
    ).fetchone()
    return row is not None


def get_entry(entry_id: str) -> dict | None:
    """Load a full memory entry by ID. Returns None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM entries WHERE id = ?", (entry_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def delete_entry(entry_id: str) -> bool:
    """Delete an entry. Returns True if found and deleted."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    conn.commit()
    return cursor.rowcount > 0


def count_entries() -> int:
    """Return total number of entries."""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    return row[0]


def list_all_entries(
    tags: list[str] | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """List entries with optional tag filtering and pagination.

    Returns (entries, total_count) where entries are metadata-only dicts
    (no content field).
    """
    conn = _get_conn()

    if tags:
        # Filter: entry must have at least one matching tag
        # Use json_each() for exact tag matching (no substring false positives)
        tag_placeholders = ",".join(["?" for _ in tags])
        tag_params = [t.strip().lower() for t in tags]

        total = conn.execute(
            f"""SELECT COUNT(DISTINCT e.id) FROM entries e, json_each(e.tags) j
                WHERE j.value IN ({tag_placeholders})""",
            tag_params,
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT DISTINCT e.id, e.summary, e.tags, e.timestamp,
                       e.source, e.source_name, e.char_count
                FROM entries e, json_each(e.tags) j
                WHERE j.value IN ({tag_placeholders})
                ORDER BY e.timestamp DESC
                LIMIT ? OFFSET ?""",
            tag_params + [limit, offset],
        ).fetchall()
    else:
        total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        rows = conn.execute(
            """SELECT id, summary, tags, timestamp, source, source_name, char_count
               FROM entries ORDER BY timestamp DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()

    entries = [_row_to_index_dict(row) for row in rows]
    return entries, total


def list_all_tags() -> dict[str, int]:
    """Return all tags with frequency counts."""
    conn = _get_conn()
    rows = conn.execute("SELECT tags FROM entries").fetchall()
    tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in json.loads(row["tags"]):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return dict(sorted(tag_counts.items(), key=lambda x: (-x[1], x[0])))


# --- FTS5 search ---


def search_fts(
    query: str,
    tags: list[str] | None = None,
    max_results: int = 20,
) -> list[dict]:
    """Full-text search with BM25 ranking.

    Uses Porter stemming (configured at table creation).
    Column weights: summary=3.0, tags=2.0, content=1.0
    """
    conn = _get_conn()

    # Build FTS5 match expression from query terms
    match_expr = _build_match_expr(query)
    if not match_expr:
        return []

    if tags:
        tag_placeholders = ",".join(["?" for _ in tags])
        tag_params = [t.strip().lower() for t in tags]

        sql = f"""
            SELECT e.id, e.summary, e.tags, e.timestamp, e.source,
                   e.source_name, e.char_count,
                   bm25(entries_fts, 3.0, 2.0, 1.0) AS rank
            FROM entries_fts fts
            JOIN entries e ON e.rowid = fts.rowid
            WHERE entries_fts MATCH ?
              AND e.id IN (
                  SELECT DISTINCT e2.id FROM entries e2, json_each(e2.tags) j
                  WHERE j.value IN ({tag_placeholders})
              )
            ORDER BY rank
            LIMIT ?
        """
        params = [match_expr] + tag_params + [max_results]
    else:
        sql = """
            SELECT e.id, e.summary, e.tags, e.timestamp, e.source,
                   e.source_name, e.char_count,
                   bm25(entries_fts, 3.0, 2.0, 1.0) AS rank
            FROM entries_fts fts
            JOIN entries e ON e.rowid = fts.rowid
            WHERE entries_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        params = [match_expr, max_results]

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # If the FTS query syntax is invalid, fall back to simple term search
        simple_expr = _build_simple_match(query)
        if not simple_expr:
            return []
        params[0] = simple_expr
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

    results = []
    for row in rows:
        entry = _row_to_index_dict(row)
        # BM25 returns negative scores (lower = better match),
        # convert to positive for display
        entry["score"] = round(-row["rank"], 2)
        results.append(entry)

    return results


def get_snippets(
    query: str,
    entry_id: str,
    max_tokens: int = 30,
) -> str | None:
    """Get FTS5 snippet for a specific entry matching a query."""
    conn = _get_conn()
    match_expr = _build_match_expr(query)
    if not match_expr:
        return None

    try:
        row = conn.execute(
            """SELECT snippet(entries_fts, 2, '>>>', '<<<', '...', ?)
               FROM entries_fts fts
               JOIN entries e ON e.rowid = fts.rowid
               WHERE entries_fts MATCH ? AND e.id = ?""",
            (max_tokens, match_expr, entry_id),
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


# --- Migration support ---


def import_entry_from_json(entry_data: dict, auto_commit: bool = True) -> None:
    """Import a single entry from the old JSON format.

    Expects a dict with: id, summary, tags, timestamp, source,
    source_name, char_count, content, and optionally chunks.

    Args:
        auto_commit: If False, caller must commit manually. Use False for bulk imports.
    """
    insert_entry(
        entry_id=entry_data["id"],
        summary=entry_data.get("summary", ""),
        tags=entry_data.get("tags", []),
        timestamp=entry_data.get("timestamp", 0.0),
        source=entry_data.get("source", "text"),
        source_name=entry_data.get("source_name"),
        char_count=entry_data.get("char_count", len(entry_data.get("content", ""))),
        content=entry_data.get("content", ""),
        chunks=entry_data.get("chunks"),
        auto_commit=auto_commit,
    )


def commit() -> None:
    """Manually commit the current transaction."""
    conn = _get_conn()
    conn.commit()


def rebuild_fts_index() -> None:
    """Rebuild the FTS index from scratch. Use after bulk imports."""
    conn = _get_conn()
    conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
    conn.commit()


# --- Internal helpers ---


def _build_match_expr(query: str) -> str:
    """Build an FTS5 MATCH expression from a natural language query.

    Converts "iraq war opinions" into a query that FTS5 understands.
    Uses OR so any term matching is sufficient (the ranking handles relevance).
    """
    # Extract words (same pattern as the old _tokenize but keep all words >= 2 chars)
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query.lower())
    words = [w for w in words if len(w) >= 2]
    if not words:
        return ""

    # Use OR to cast a wide net; BM25 handles ranking
    # Wrap each word to prevent FTS5 syntax errors from special chars
    escaped = [f'"{w}"' for w in words]
    return " OR ".join(escaped)


def _build_simple_match(query: str) -> str:
    """Fallback: build a very simple match expression."""
    words = re.findall(r"[a-zA-Z]+", query.lower())
    words = [w for w in words if len(w) >= 3]
    if not words:
        return ""
    return " OR ".join(f'"{w}"' for w in words)


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a full database row to a dict (with content)."""
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    if d.get("chunks"):
        d["chunks"] = json.loads(d["chunks"])
    return d


def _row_to_index_dict(row: sqlite3.Row) -> dict:
    """Convert a row to an index-style dict (no content)."""
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d.pop("content", None)
    d.pop("chunks", None)
    d.pop("rank", None)
    return d
