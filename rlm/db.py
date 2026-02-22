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
    # --- Facts table (structured knowledge extracted from episodes) ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            fact_text TEXT NOT NULL,
            source_entry_id TEXT NOT NULL,
            entity TEXT,
            fact_type TEXT NOT NULL DEFAULT 'observation',
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at REAL NOT NULL,
            superseded_by TEXT,
            FOREIGN KEY (source_entry_id) REFERENCES entries(id) ON DELETE CASCADE
        )
    """)

    # FTS5 for facts
    facts_fts_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='facts_fts'"
    ).fetchone()

    if not facts_fts_exists:
        conn.execute("""
            CREATE VIRTUAL TABLE facts_fts USING fts5(
                fact_text,
                entity,
                fact_type,
                content='facts',
                content_rowid='rowid',
                tokenize='porter unicode61'
            )
        """)

    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
            INSERT INTO facts_fts(rowid, fact_text, entity, fact_type)
            VALUES (new.rowid, new.fact_text, new.entity, new.fact_type);
        END;

        CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, fact_text, entity, fact_type)
            VALUES ('delete', old.rowid, old.fact_text, old.entity, old.fact_type);
        END;

        CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, fact_text, entity, fact_type)
            VALUES ('delete', old.rowid, old.fact_text, old.entity, old.fact_type);
            INSERT INTO facts_fts(rowid, fact_text, entity, fact_type)
            VALUES (new.rowid, new.fact_text, new.entity, new.fact_type);
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


def find_entries_by_source_name(source_name: str) -> list[dict]:
    """Find all entries with a given source_name (metadata only, no content)."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, summary, tags, timestamp, source, source_name, char_count
           FROM entries WHERE source_name = ?
           ORDER BY timestamp DESC""",
        (source_name,),
    ).fetchall()
    return [_row_to_index_dict(row) for row in rows]


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


def get_stats() -> dict:
    """Return aggregate statistics about the memory store."""
    conn = _get_conn()

    row = conn.execute("""
        SELECT
            COUNT(*) AS total_entries,
            COALESCE(SUM(char_count), 0) AS total_chars,
            COALESCE(AVG(char_count), 0) AS avg_chars,
            COALESCE(MIN(char_count), 0) AS min_chars,
            COALESCE(MAX(char_count), 0) AS max_chars,
            COALESCE(MIN(timestamp), 0) AS oldest_ts,
            COALESCE(MAX(timestamp), 0) AS newest_ts
        FROM entries
    """).fetchone()

    # Count by source type
    source_rows = conn.execute(
        "SELECT source, COUNT(*) AS cnt, SUM(char_count) AS chars FROM entries GROUP BY source"
    ).fetchall()
    by_source = {r["source"]: {"count": r["cnt"], "chars": r["chars"] or 0} for r in source_rows}

    # Top 15 tags by frequency
    tag_rows = conn.execute("SELECT tags FROM entries").fetchall()
    tag_counts: dict[str, int] = {}
    for tr in tag_rows:
        for tag in json.loads(tr["tags"]):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:15]

    # Size distribution
    size_rows = conn.execute("""
        SELECT
            SUM(CASE WHEN char_count <= 2000 THEN 1 ELSE 0 END) AS small,
            SUM(CASE WHEN char_count > 2000 AND char_count <= 10000 THEN 1 ELSE 0 END) AS medium,
            SUM(CASE WHEN char_count > 10000 AND char_count <= 50000 THEN 1 ELSE 0 END) AS large,
            SUM(CASE WHEN char_count > 50000 THEN 1 ELSE 0 END) AS huge
        FROM entries
    """).fetchone()

    # Database file size
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

    return {
        "total_entries": row["total_entries"],
        "total_chars": row["total_chars"],
        "avg_chars": round(row["avg_chars"]),
        "min_chars": row["min_chars"],
        "max_chars": row["max_chars"],
        "oldest_timestamp": row["oldest_ts"],
        "newest_timestamp": row["newest_ts"],
        "by_source": by_source,
        "top_tags": top_tags,
        "unique_tags": len(tag_counts),
        "size_distribution": {
            "small (≤2KB)": size_rows["small"] or 0,
            "medium (2-10KB)": size_rows["medium"] or 0,
            "large (10-50KB)": size_rows["large"] or 0,
            "huge (>50KB)": size_rows["huge"] or 0,
        },
        "db_file_size": db_size,
    }


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


_SYSTEM_TAGS = frozenset({
    "session", "conversation", "summary", "session-summary",
    "full-transcript", "transcript",
})


def list_recent_tags(days: int = 7) -> dict[str, int]:
    """Return tags from recently archived sessions (last N days), excluding system tags."""
    import time

    conn = _get_conn()
    cutoff = time.time() - (days * 86400)
    rows = conn.execute(
        """SELECT tags FROM entries
           WHERE timestamp > ?
             AND (source LIKE '%session%' OR source = 'stdin')""",
        (cutoff,),
    ).fetchall()
    tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in json.loads(row["tags"]):
            if tag.lower() not in _SYSTEM_TAGS:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return dict(sorted(tag_counts.items(), key=lambda x: (-x[1], x[0])))


def list_tags_for_tagged_entries(required_tag: str, limit: int = 10) -> dict[str, int]:
    """Return tag counts from entries that have required_tag, excluding system tags."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT e.tags FROM entries e, json_each(e.tags) AS jt
           WHERE LOWER(jt.value) = LOWER(?)""",
        (required_tag,),
    ).fetchall()
    tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in json.loads(row["tags"]):
            if tag.lower() not in _SYSTEM_TAGS:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))
    return dict(sorted_tags[:limit])


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


# --- Facts operations ---


def insert_fact(
    fact_id: str,
    fact_text: str,
    source_entry_id: str,
    entity: str | None,
    fact_type: str,
    confidence: float,
    created_at: float,
    auto_commit: bool = True,
) -> None:
    """Insert a new fact."""
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO facts
           (id, fact_text, source_entry_id, entity, fact_type, confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (fact_id, fact_text, source_entry_id, entity, fact_type, confidence, created_at),
    )
    if auto_commit:
        conn.commit()


def search_facts_fts(
    query: str,
    fact_type: str | None = None,
    max_results: int = 20,
    include_superseded: bool = False,
) -> list[dict]:
    """Full-text search across facts with BM25 ranking.

    Returns only active (non-superseded) facts by default.
    """
    conn = _get_conn()
    match_expr = _build_match_expr(query)
    if not match_expr:
        return []

    where_clauses = ["facts_fts MATCH ?"]
    params: list = [match_expr]

    if not include_superseded:
        where_clauses.append("f.superseded_by IS NULL")

    if fact_type:
        where_clauses.append("f.fact_type = ?")
        params.append(fact_type)

    where_sql = " AND ".join(where_clauses)
    params.append(max_results)

    sql = f"""
        SELECT f.id, f.fact_text, f.source_entry_id, f.entity,
               f.fact_type, f.confidence, f.created_at, f.superseded_by,
               bm25(facts_fts, 3.0, 2.0, 1.0) AS rank
        FROM facts_fts fts
        JOIN facts f ON f.rowid = fts.rowid
        WHERE {where_sql}
        ORDER BY rank
        LIMIT ?
    """

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        simple_expr = _build_simple_match(query)
        if not simple_expr:
            return []
        params[0] = simple_expr
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

    return [_fact_row_to_dict(row) for row in rows]


def list_facts(
    source_entry_id: str | None = None,
    fact_type: str | None = None,
    entity: str | None = None,
    include_superseded: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List facts with optional filtering."""
    conn = _get_conn()

    where_clauses = []
    params: list = []

    if source_entry_id:
        where_clauses.append("source_entry_id = ?")
        params.append(source_entry_id)
    if fact_type:
        where_clauses.append("fact_type = ?")
        params.append(fact_type)
    if entity:
        where_clauses.append("LOWER(entity) = LOWER(?)")
        params.append(entity)
    if not include_superseded:
        where_clauses.append("superseded_by IS NULL")

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM facts{where_sql}", params
    ).fetchone()[0]

    rows = conn.execute(
        f"""SELECT id, fact_text, source_entry_id, entity, fact_type,
                   confidence, created_at, superseded_by
            FROM facts{where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    return [_fact_row_to_dict(row) for row in rows], total


def supersede_fact(old_fact_id: str, new_fact_id: str) -> bool:
    """Mark an old fact as superseded by a new one."""
    conn = _get_conn()
    cursor = conn.execute(
        "UPDATE facts SET superseded_by = ? WHERE id = ? AND superseded_by IS NULL",
        (new_fact_id, old_fact_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_fact(fact_id: str) -> bool:
    """Delete a single fact."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
    conn.commit()
    return cursor.rowcount > 0


def delete_facts_for_entry(entry_id: str) -> int:
    """Delete all facts linked to a given source entry. Returns count deleted."""
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM facts WHERE source_entry_id = ?", (entry_id,)
    )
    conn.commit()
    return cursor.rowcount


def count_facts() -> int:
    """Return total number of facts."""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]


def find_facts_by_entity(entity: str, fact_type: str | None = None) -> list[dict]:
    """Find active facts for a given entity (for contradiction detection)."""
    conn = _get_conn()
    if fact_type:
        rows = conn.execute(
            """SELECT id, fact_text, source_entry_id, entity, fact_type,
                      confidence, created_at, superseded_by
               FROM facts
               WHERE LOWER(entity) = LOWER(?) AND fact_type = ?
                 AND superseded_by IS NULL
               ORDER BY created_at DESC""",
            (entity, fact_type),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, fact_text, source_entry_id, entity, fact_type,
                      confidence, created_at, superseded_by
               FROM facts
               WHERE LOWER(entity) = LOWER(?) AND superseded_by IS NULL
               ORDER BY created_at DESC""",
            (entity,),
        ).fetchall()
    return [_fact_row_to_dict(row) for row in rows]


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


def _fact_row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a facts table row to a dict."""
    d = dict(row)
    # Add score from BM25 rank if present
    if "rank" in d:
        d["score"] = round(-d.pop("rank"), 2)
    return d
