# Issue: Add structured fact extraction to archiving pipeline

**Title:** feat: Extract structured facts from archived conversations during archiving

**Priority:** High — this is the single highest-value improvement to the recall pipeline

## Summary

During archiving (PreCompact/SessionEnd hooks), RLM currently stores a 2-tier format: ~1KB summary + ~60KB compressed transcript. While effective for episode-level recall, this is still closer to "raw conversation storage" than structured knowledge — making precise fact retrieval harder than it needs to be.

We should add a **fact extraction post-processing step** that pulls discrete facts, decisions, preferences, and relationships out of conversations and stores them as structured, independently queryable entries.

## Motivation

Inspired by [@rohit4verse's post on X](https://x.com/rohit4verse/status/2012925228159295810) and the [Martian-Engineering/agent-memory](https://github.com/Martian-Engineering/agent-memory) project, which implements a three-layer memory system (knowledge graph + daily notes + tacit knowledge). Their core insight: **"Memory is infrastructure, not a feature"** — and embeddings measure similarity, not truth. You need structure, timestamps, and maintenance.

RLM's metadata-first orchestration and subagent dispatch are architecturally superior for scale, but we're leaving value on the table by not extracting structured knowledge from archived episodes. Right now, to answer "what testing framework does the user prefer?", the recall pipeline has to:

1. FTS5 search across episode summaries (which may not mention testing)
2. Dispatch subagents to read full transcripts (expensive)
3. Hope the answer is in one of the top-ranked episodes

With structured facts, the answer would be a direct database hit.

## Proposed Approach

### 1. Fact extraction pass during archiving

When PreCompact/SessionEnd hooks fire, run an additional extraction step (via Claude API or subagent) that identifies:

- **Discrete facts and decisions** — "user chose pytest over unittest for project X"
- **User preferences and patterns** — "prefers functional style", "always wants tests"
- **Entity relationships** — "project A depends on library B"
- **Corrections/updates** — supersede previously stored knowledge when preferences change

This would run after summary generation and semantic tag extraction in `archive.py`, using the same compressed transcript as input.

### 2. New `facts` FTS5 table

Store extracted facts in a separate FTS5 table alongside the existing `entries` table:

```sql
CREATE TABLE facts (
    id TEXT PRIMARY KEY,               -- f_<uuid>
    fact_text TEXT NOT NULL,            -- The atomic fact
    source_entry_id TEXT NOT NULL,      -- FK to entries.id (episode it came from)
    entity TEXT,                        -- Primary entity ("pytest", "project-rlm", etc.)
    fact_type TEXT NOT NULL,            -- decision, preference, relationship, technical, observation
    confidence REAL DEFAULT 1.0,       -- Extraction confidence (0.0-1.0)
    created_at REAL NOT NULL,          -- Unix timestamp
    superseded_by TEXT,                -- FK to facts.id if this fact was later corrected
    FOREIGN KEY (source_entry_id) REFERENCES entries(id)
);

CREATE VIRTUAL TABLE facts_fts USING fts5(
    fact_text,
    entity,
    fact_type,
    content='facts',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Auto-sync triggers (same pattern as entries_fts)
```

### 3. Contradiction detection

When a new fact conflicts with an existing one (e.g., framework preference changed), flag the old fact as superseded rather than deleting it:

```python
def check_contradictions(new_fact, existing_facts):
    """Find facts that the new fact might supersede."""
    # Match on same entity + same fact_type
    candidates = db.search_facts(
        entity=new_fact.entity,
        fact_type=new_fact.fact_type
    )
    for candidate in candidates:
        if is_contradictory(new_fact, candidate):
            db.update_fact(candidate.id, superseded_by=new_fact.id)
```

This preserves history — you can answer "what testing framework does the user prefer?" (latest non-superseded fact) and also "what testing frameworks has the user used over time?" (all facts for that entity).

### 4. Recall pipeline integration

Extend the recall pipeline to search facts alongside episode summaries:

```python
def recall(query, tags=None):
    # Existing: search episode summaries
    episodes = db.search_fts(query, tags)

    # New: also search facts table
    facts = db.search_facts_fts(query)

    # Merge results, facts ranked higher for precision queries
    return merge_results(episodes, facts)
```

For the MCP `rlm_recall` tool, fact results would appear in a separate section:

```
## Relevant Facts
- [preference] User prefers pytest over unittest (from session 2026-02-15)
- [decision] Chose SQLite+FTS5 over vector DB for memory (from session 2026-01-20)

## Related Episodes
- Session summary: recursive-ai on 2026-02-15 (entry: m_abc123)
```

### 5. Extraction prompt

The quality of this prompt is make-or-break. It needs to extract specific, non-obvious facts — not generic observations:

```
Given this conversation transcript, extract discrete, specific facts.

GOOD facts (specific, actionable, non-obvious):
- "User chose pytest over unittest for the RLM project"
- "User prefers zero external dependencies in Python projects"
- "Project RLM uses SQLite FTS5 for memory search, not vector embeddings"
- "User considers over-engineering a bigger risk than under-engineering"

BAD facts (generic, obvious, useless):
- "User likes clean code"
- "User is working on a software project"
- "User uses Python"

For each fact, provide:
- fact_text: The atomic fact (one sentence)
- entity: Primary entity it relates to
- fact_type: one of [decision, preference, relationship, technical, observation]
- confidence: 0.0-1.0 (how confident based on transcript evidence)
```

## Integration points in existing code

| File | Change |
|---|---|
| `rlm/db.py` | Add `facts` + `facts_fts` schema, `insert_fact()`, `search_facts_fts()`, contradiction detection queries |
| `rlm/archive.py` | Add fact extraction step after summary generation (~line 155) |
| `rlm/memory.py` | Add `search_facts()` wrapper, merge facts into recall results |
| `rlm/cli.py` | Add `rlm facts` subcommand (list/search/show facts), extend `recall` output |
| `mcp/server.py` | Extend `rlm_recall` to include fact results, optionally add `rlm_facts` tool |
| `hooks/session-start-rlm.py` | Optionally inject top relevant facts alongside session summaries |

## Estimated effort

| Component | Lines | Time |
|---|---|---|
| Schema + DB operations (`db.py`) | ~150-200 | 2-3 days |
| Extraction logic + prompt (`archive.py`, new `facts.py`) | ~200-300 | 3-4 days |
| Contradiction detection | ~100-150 | 1-2 days |
| Recall integration (`memory.py`, `cli.py`) | ~150-200 | 2-3 days |
| MCP + hooks integration | ~50-100 | 1 day |
| Backfill script (extract facts from existing 337+ entries) | ~100 | 1 day |
| **Total** | **~750-1050** | **~2 weeks** |

## Relationship to existing roadmap

This aligns with Phase 4 plans for:
- Memory importance scoring (fact confidence provides this)
- Consolidation and forgetting curves (superseded_by chain provides this)
- Cross-entry relationship awareness (entity + fact_type provide this)

## What we're NOT doing

- **Vector embeddings / hybrid search** — FTS5 + grep gating + subagent dispatch already achieves strong recall. No need for embedding infrastructure.
- **Knowledge graph** — A full graph DB is overkill. The `entity` + `fact_type` + `superseded_by` columns give us lightweight relationship tracking without graph complexity.
- **File-based storage** — SQLite is strictly better for search, atomicity, and concurrent access.

## References

- [@rohit4verse's X post](https://x.com/rohit4verse/status/2012925228159295810) — persistent memory architecture for AI agents
- [Martian-Engineering/agent-memory](https://github.com/Martian-Engineering/agent-memory) — three-layer implementation (knowledge graph + daily notes + tacit knowledge)
- Core insight borrowed: separate "what happened" (episodes) from "what is known" (facts)

## Labels

`enhancement`, `memory`, `recall`, `high-priority`
