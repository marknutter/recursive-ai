# RLM: Recursive Language Model Analysis + Episodic Memory

## Mission Statement

**RLM enables AI agents to think beyond their context windows while maintaining perfect memory across sessions.**

### Core Innovation: Two-Part System

#### 1. Best-in-Class RLM Analysis
Implement the recursive analysis technique from the research paper:
- **Scan → Chunk → Extract → Analyze** large codebases and documents without context bloat
- Parallel subagent dispatch for efficient multi-scale analysis
- Never load full content into main context - orchestrator sees metadata, subagents see content
- Multiple chunking strategies: files, functions, headings, semantic, lines

#### 2. Episodic Memory (The Innovation)
Automatic persistent memory that survives context limits and session boundaries:
- **Auto-archive context windows** before compaction → stored in `~/.rlm/memory/`
- **Recall using RLM** - retrieve past conversations efficiently without context bloat
- **Full-fidelity storage** via SQLite + FTS5 - no data loss, fast search
- **Smart retrieval** - use RLM chunking on large memory matches

### Why This Matters

**Most AI agents have amnesia.** When context fills up or sessions end, they forget everything.

**MCP and RAG** give agents access to external knowledge (databases, APIs, documents) but don't preserve **the agent's own conversation history** across sessions.

**RLM + Episodic Memory** solves this by:
- Storing the agent's full conversation history
- Using RLM to efficiently recall relevant past context
- Maintaining continuity across arbitrarily long timespans
- Enabling agents to learn from their own past interactions

### The Technique

1. **Store in full** - SQLite backend preserves complete conversations and documents
2. **Index with FTS5** - Fast keyword search with BM25 ranking and Porter stemming
3. **Retrieve with RLM** - Use recursive chunking to analyze large matches efficiently
4. **No context bloat** - Summaries and targeted extracts only, never full dumps

**Result:** An AI agent that can work with infinite context and perfect recall.

---

# Implementation Roadmap

## Version History
- **0.1** — Core RLM analysis (scan/chunk/extract/dispatch loop, skill prompt)
- **0.2** — Persistent memory (SQLite FTS5, recall pipeline, grep pre-filtering, graduated dispatch, self-improving strategies, chat data ingestion)
- **0.3** — Auto-recall infrastructure (MCP server, conversation archiving hooks, zero-footprint install, export moved into package, global MCP config)
- **0.4** — Compression + quality (semantic tagging, two-tier storage, structural compression, session summaries, `json_each()` tag filtering, `rlm stats`) ← **current**
- **1.0** — Public release (PyPI packaging, relocatable install, stable API, external testing)

## Phase 1: Core RLM ✅ COMPLETE
- [x] Scan, chunk, extract, session management
- [x] Multiple chunking strategies (functions, files, headings, semantic, lines)
- [x] Subagent dispatch pattern
- [x] Skill prompt with clear modes
- [x] Tag filtering in SQL (`json_each()` for exact matching)

## Phase 2: Episodic Memory ✅ COMPLETE
- [x] SQLite + FTS5 backend with batch transaction optimization (21x speedup)
- [x] Memory storage API (`/rlm remember`) and recall API (`/rlm recall`)
- [x] Hook-based auto-archiving (PreCompact + SessionEnd hooks)
- [x] RLM-powered recall with size detection + chunking guidance
- [x] Self-improving retrieval via learned patterns
- [x] WAL mode enabled for concurrent read/write performance

## Phase 3: Auto-Recall + Quality ✅ COMPLETE
- [x] MCP server (`mcp/server.py`) exposing 5 tools as native operations
- [x] SessionStart hook injecting recent project context
- [x] Semantic tagging (LLM + keyword extraction fallback)
- [x] Two-tier storage (summary + compressed transcript, linked by session_id)
- [x] Structural compression (strips skill prompts — 63% reduction)
- [x] Session summary generator (`rlm/summarize.py`)
- [x] `rlm stats` command

## Phase 4: Remaining Improvements 📋 (Planned)

### Analysis Engine
- [ ] Adaptive chunk sizing based on content density
- [ ] Cross-file dependency awareness (include imports/callers in same chunk)
- [ ] AST-aware chunking for more languages (JS/TS, Go, Rust)
- [ ] Confidence-based early termination for subagent dispatch
- [ ] Result deduplication across subagents

### Memory Intelligence
- [ ] Memory importance scoring (information density, decision count, topic novelty)
- [ ] Memory consolidation (synthesize patterns across related conversations)
- [ ] Forgetting curve (boost frequently-recalled memories, decay stale ones)
- [x] Content deduplication (detect and skip re-archived sessions)
- [ ] Retention policies (auto-compress old memories >30 days)

### Schema & Search
- [ ] Temporal indexing (fast queries like "what was I doing last Tuesday")
- [ ] Relationship tracking (link continuation sessions, superseding decisions)
- [ ] Configurable BM25 weights for different content types
- [ ] Ranked tag search (weight exact matches higher than partial)

### Developer Experience
- [x] Memory dashboard (TUI to browse/search/manage)
- [ ] Export/import (backup and migration between machines)
- [ ] Privacy controls (mark memories as "do not recall", auto-redact secrets)
- [ ] Documentation and examples

## Phase 5: Cross-Platform & Distribution 📋 (Planned)

### Library-ification
- [ ] Provider-agnostic hook interface (abstract `PreCompact`, `SessionEnd`, etc.)
- [ ] Generic transcript format with platform adapters
- [ ] Abstract skill/prompt interface

### Platform Adapters
- [ ] Cursor (MCP support exists — test immediately)
- [ ] OpenAI Codex (research extension points)
- [ ] Gemini Code Assist, Windsurf, Aider

### Packaging
- [ ] PyPI package (`pip install rlm` / `uv pip install rlm`)
- [ ] Comprehensive documentation and getting-started guide
- [ ] Test with at least one external user

### 1.0 Release Criteria
- Installable via `pip install rlm` without cloning the repo
- No hardcoded paths — install works on any machine
- Documented, stable CLI and MCP API
- Tested by at least one person who isn't the author

---

# Completed Feature Details

## Auto-Recall (MCP Server) ✅

All 5 MCP tools available as native operations in terminal Claude Code sessions:
- `rlm_recall` — search memory by query + optional tag filter
- `rlm_remember` — store new memories
- `rlm_memory_list` — browse entries by tag
- `rlm_memory_extract` — extract full content with optional grep
- `rlm_forget` — delete entries

SessionStart hook injects recent project context automatically.

**Known limitation:** Omnara ignores `additionalContext` from hooks. Terminal sessions provide the full experience.

## Semantic Tagging ✅

LLM-based tag extraction with keyword fallback. Generates 5-10 semantic tags per archived conversation. Tags like `mcp`, `hooks`, `architecture-decision` dramatically improve recall quality.

## Transcript Compression ✅

Two-tier storage with structural compression:
- **Summary entry** (~1KB): decisions, questions, commits, files modified
- **Compressed transcript** (~60KB): skill prompts stripped, boilerplate removed, formatting compacted
- Both linked by shared `session_id` tag
- Key finding: 84% of user content was injected skill prompts

## Tag Filtering ✅

Replaced `LIKE`-based tag filtering with `json_each()` for exact matching. No more substring false positives (e.g., `"mcp"` matching `"mcp-server"`).
