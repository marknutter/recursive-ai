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

### Memory Types

**Episodic Memory** (primary focus):
- Agent's own conversation history
- "What did we discuss about X last week?"
- Auto-captured before context compaction
- Retrieved using RLM to avoid re-bloating context

**Semantic Memory** (secondary feature):
- External knowledge ingested via `/rlm remember`
- Documents, codebases, reference materials
- Same storage and retrieval as episodic memories
- Useful but not the main innovation

### The Technique

1. **Store in full** - SQLite backend preserves complete conversations and documents
2. **Index with FTS5** - Fast keyword search with BM25 ranking
3. **Retrieve with RLM** - Use recursive chunking to analyze large matches efficiently
4. **No context bloat** - Summaries and targeted extracts only, never full dumps

**Result:** An AI agent that can work with infinite context and perfect recall.

---

# Implementation Roadmap

## Phase 1: Solidify Core RLM ✅ (Mostly Complete)
- [x] Scan, chunk, extract, session management
- [x] Multiple chunking strategies
- [x] Subagent dispatch pattern
- [x] Skill prompt with clear modes
- [ ] Performance optimization (tag filtering in SQL)
- [ ] Documentation and examples

## Phase 2: Episodic Memory Foundation ✅ (COMPLETE - Core Features)
- [x] SQLite + FTS5 backend
- [x] Batch transaction optimization (21x speedup)
- [x] Memory storage API (`/rlm remember`)
- [x] Memory recall API (`/rlm recall`)
- [x] **Hook-based auto-archiving** (PreCompact + SessionEnd hooks)
- [x] **RLM-powered recall** (size detection + chunking guidance)
- [ ] Conversation transcript schema (optional enhancement)
- [ ] Session metadata tracking (optional enhancement)

## Phase 3: Unified Retrieval 📋 (Planned)
- [ ] Unified search across episodic + semantic memories
- [ ] Smart recall: use RLM when matches are large
- [ ] Context-aware retrieval (temporal proximity, relevance scoring)
- [ ] Memory summarization (compress old conversations)
- [ ] Performance monitoring and learned patterns

## Phase 4: Semantic Memory (External Knowledge) 📋 (Planned)
- [ ] Bulk ingestion CLI (`/rlm ingest-directory`)
- [ ] Generic ingestion examples (CSV, JSON, Markdown)
- [ ] Large file handling (use RLM chunking during ingestion)
- [ ] Incremental updates (detect changed files)
- [ ] Source path tracking (re-extract on demand)

## Phase 5: Polish & Distribution 📋 (Planned)
- [ ] Comprehensive documentation
- [ ] Migration guides
- [ ] Performance benchmarks
- [ ] Example workflows
- [ ] Public release preparation

---

# Current Focus: Phase 2 - Episodic Memory

## Immediate Next Steps

### 1. Hook-Based Auto-Archiving ✅ COMPLETE
**Goal:** Automatically save context before compaction

**Tasks:**
- [x] Create pre-compaction hook in Claude Code
- [x] Extract full conversation transcript on trigger
- [x] Store in `~/.rlm/memory/` with metadata (timestamp, project, session_id)
- [x] Add tags: `conversation`, `session`, project name, date
- [ ] Test: verify context survives compaction (needs manual testing)

**Files to modify:**
- Hook configuration (Claude Code integration)
- `examples/export_session.py` (already exists, enhance it)
- `rlm/memory.py` (add conversation-specific ingestion)

### 2. RLM-Powered Recall ✅ COMPLETE
**Goal:** Use chunking when retrieving large memories

**Tasks:**
- [x] Detect when recalled memory is too large (>10KB)
- [x] Apply RLM chunking to large memory matches
- [x] Document workflow in skill prompt
- [x] Return summary + targeted extracts instead of full content
- [ ] Test with real large conversation memories (needs manual testing)

**Files to modify:**
- `rlm/cli.py` (`cmd_recall` function)
- `skill/SKILL.md` (document recall mode behavior)
- `rlm/memory.py` (add chunk-aware retrieval)

### 3. Conversation Schema Enhancement
**Goal:** Structure for episodic memory storage

**Tasks:**
- [ ] Add conversation-specific fields to database schema
- [ ] Track: session_id, project_path, participants, turn_count
- [ ] Index by temporal proximity (recent conversations)
- [ ] Query API: "conversations from last week about X"

**Files to modify:**
- `rlm/db.py` (schema updates)
- `rlm/cli.py` (conversation-aware queries)

---

# Backlog TODOs

## Skill Prompt Improvements

- [x] **Enforce subagent-only content access.** Tighten SKILL.md to make it explicit that extracted content must go *into subagent prompts*, never into the main orchestrator context. The current wording says this but Claude still loads extracts into its own context. Needs stronger guardrails -- e.g., "Do NOT call `rlm extract` and read the output yourself. Instead, construct the extract command and embed its output directly in the Task subagent prompt."

- [x] **Add exact CLI usage examples to the skill prompt.** Claude guessed wrong flags (`--chunk` instead of `--chunk-id`, `--session` on extract). Add a quick-reference block in SKILL.md showing the exact syntax for each command, especially extract variants: `--lines START:END`, `--chunk-id ID --manifest PATH`, `--grep PATTERN`.

- [x] **Add file-group chunk dispatch pattern.** When using `files_directory`/`files_language`/`files_balanced`, the chunks contain file lists rather than line ranges. The skill prompt needs an explicit pattern for this: iterate the file list in each chunk, extract each file's content, and include all of them in a single subagent prompt per chunk group.



\