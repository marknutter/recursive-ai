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

## Version History
- **0.1** — Core RLM analysis (scan/chunk/extract/dispatch loop, skill prompt)
- **0.2** — Persistent memory (SQLite FTS5, recall pipeline, grep pre-filtering, graduated dispatch, self-improving strategies, chat data ingestion)
- **0.3** — Auto-recall infrastructure (MCP server, conversation archiving hooks, zero-footprint install, export moved into package, global MCP config) ← **current**
- **1.0** — Public release (PyPI packaging, relocatable install, stable API, external testing)

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
- [x] ~~Remove hardcoded install path~~ — resolved via symlink resolution + template substitution
- [ ] PyPI packaging (`pip install rlm` / `uv pip install rlm`)
- [ ] Stable, documented CLI and MCP API
- [ ] Comprehensive documentation and getting-started guide
- [ ] Migration guides (JSON → SQLite, per-project → global)
- [ ] Performance benchmarks
- [ ] Example workflows
- [ ] Test with at least one external user

### 1.0 Release Criteria
All of the above must be complete before tagging 1.0. The key gates:
- Installable via `pip install rlm` without cloning the repo
- No hardcoded paths — install works on any machine
- Documented, stable CLI and MCP API
- Tested by at least one person who isn't the author

---

# Completed Work

## Phase 1: Core RLM ✅
- Scan, chunk, extract, session management
- Multiple chunking strategies (functions, files, headings, semantic, lines)
- Subagent dispatch pattern
- Skill prompt with clear modes

## Phase 2: Episodic Memory ✅
- SQLite + FTS5 backend with batch transaction optimization (21x speedup)
- Memory storage API (`/rlm remember`) and recall API (`/rlm recall`)
- Hook-based auto-archiving (PreCompact + SessionEnd hooks)
- RLM-powered recall with size detection + chunking guidance
- Self-improving retrieval via learned patterns
- Tested end-to-end: hooks archive conversations, recall retrieves them

## Skill Prompt ✅
- Enforced subagent-only content access
- Exact CLI usage examples
- File-group chunk dispatch pattern

---

# TODO: Next Phase

**Recommended implementation sequence:**
1. **Auto-Recall (MCP server)** - Changes the experience, smallest lift, biggest payoff
2. **Semantic Tagging** - Improves recall quality immediately, small scope
3. **Transcript Compression** - Improves what auto-recall retrieves
4-7. **Ongoing improvements** - Engine, SQLite, cross-platform, advanced features

---

## 1. Automatic Memory Utilization (Auto-Recall) 🎯 START HERE

### Current Status (as of 2026-02-17)

**✅ MCP AUTO-RECALL FULLY WORKING IN TERMINAL SESSIONS!**

The #1 priority from the roadmap is now complete. Testing confirmed:
- All 5 MCP tools (`rlm_recall`, `rlm_remember`, `rlm_memory_list`, `rlm_memory_extract`, `rlm_forget`) available as native operations
- Agent proactively uses these tools without needing `/rlm` skill invocation
- Excellent retrieval quality with grep pre-filtering for large memories
- SessionStart hook automatically injects recent project context

**What's implemented and working:**
- ✅ `mcp/server.py` — Full MCP stdio JSON-RPC 2.0 server exposing 5 tools
- ✅ `.mcp.json` — Project-scoped MCP config (approval persists after first use)
- ✅ `hooks/session-start-rlm.py` — SessionStart hook that queries recent project memories
- ✅ Hook symlinked and registered globally via `install.sh`
- ✅ Native MCP tool calling confirmed working in terminal sessions

**Known limitation — Omnara compatibility:**
- The SessionStart hook *runs* on Omnara but Omnara ignores the `additionalContext` field
- MCP tools work on Omnara (confirmed via direct tool calls) but not as seamlessly
- **Workaround:** Terminal sessions provide the full auto-recall experience

**To use auto-recall:**
```bash
cd /path/to/recursive-ai
# Start a Claude Code session from terminal
# MCP tools are immediately available - no /rlm needed
# Agent will proactively search memory when relevant
```

**The problem:** Users must explicitly invoke `/rlm "query"` to access past conversations. The system has the memory but the agent doesn't know to use it unless asked.

**The goal:** Make AI agents automatically consult their memory when it would be helpful, without the user having to remember to invoke `/rlm`.

**Why start here:** This changes the *experience* of the tool from a feature you remember to use into a capability that feels native. MCP server approach is the smallest lift with biggest payoff, and immediately gets you partway to cross-platform compatibility (#6).

### Recommended approach: MCP Server (priority)
- [ ] **Build MCP server exposing RLM tools**: Wrap `rlm recall`, `rlm remember`, and `rlm scan/chunk/analyze` as MCP tools.
- [ ] **Test with Claude Code**: Verify the agent calls `rlm_recall` on its own when relevant.
- [ ] **Test with Cursor**: Cursor supports MCP — test cross-platform compatibility immediately.
- [ ] **Document MCP setup**: Add installation and configuration instructions to README.

**Why MCP first:** MCP tools feel native to the agent (like `Read` or `Bash`). The agent decides when to recall rather than requiring a slash command. Works across any MCP-compatible client (Claude Code, Cursor, etc.), immediately addressing cross-platform (#6).

### Alternative approaches (secondary):
- [ ] **Session-start hook**: On every new session, automatically recall recent work on the current project and inject a brief summary into the agent's context. Blunt instrument vs. MCP's surgical approach.
- [ ] **CLAUDE.md memory injection**: Generate a per-project `~/.claude/projects/{project}/memory/RECENT.md` file that gets auto-loaded. Update it at session end with a summary of what was worked on.
- [ ] **Prompt-level instruction**: Add instructions to `CLAUDE.md` telling the agent to check memory before starting complex work ("Before implementing, check if this was discussed previously: `/rlm 'relevant query'`").
- [ ] **Investigate Claude Code's `SessionStart` hook**: Does Claude Code support running hooks at session start? If so, we could auto-inject recent context.
- [ ] **Explore other coding assistants' extension points**: What hooks/plugins do Codex, Gemini Code Assist, Cursor, Windsurf offer? Map the integration surface for each.

### Open questions:
- What's the right amount of context to auto-inject? Too much wastes tokens, too little misses important context.
- Should auto-recall be project-scoped (only memories tagged with current project) or global?
- How do we avoid the agent wasting time on memory lookups when the task is simple?

## 2. Semantic Tagging ✅ COMPLETE (2026-02-17)

**The problem:** Conversations were tagged only with generic metadata: `conversation,session,recursive-ai,2026-02-15`. This made recall less effective because searches couldn't target specific topics.

**The solution:** Implemented LLM-based semantic tag extraction that automatically generates meaningful tags at archive time. Tags like `mcp`, `hooks`, `testing`, `semantic`, `feature` make recall dramatically better.

### What was implemented:
- ✅ **`rlm/semantic_tags.py`**: Tag extraction module with multiple fallbacks
  - Primary: Claude CLI (if available)
  - Secondary: Direct API call (if ANTHROPIC_API_KEY set)
  - Fallback: Keyword extraction for common technical terms
- ✅ **Semantic hooks**: Created `pre-compact-rlm-semantic.py` and `session-end-rlm-semantic.py`
- ✅ **Auto-activation**: `install.sh` now symlinks semantic versions by default
- ✅ **Tested and working**: Fallback keyword extraction successfully generates relevant tags

### Tag extraction approach:
1. Truncates long transcripts (keeps first 60% and last 40% of 10K chars max)
2. Tries LLM-based extraction with focused prompt
3. Falls back to keyword extraction if LLM unavailable
4. Combines with base tags (conversation, session, project, date)
5. Stores enriched tags with memory entries

### Example transformation achieved:
**Before:** `conversation,session,recursive-ai,2026-02-17`
**After:** `conversation,session,recursive-ai,2026-02-17,mcp,test,server,hooks,semantic,feature,testing,tagging,recall`

## 3. Intelligent Transcript Compression

**The problem:** Raw session JSONL files are ~2.5MB. The current export script reduces this to ~107KB (24x compression) by extracting only user/assistant messages and summarizing tool calls. But 107KB is still a lot of content for a single conversation, much of which is boilerplate, repeated context, or verbose tool output that isn't useful for long-term memory.

**The goal:** Reduce stored conversation size by another 5-10x while preserving the information that matters for future recall. Like human memory: remember the decisions, insights, and key exchanges — not every keystroke.

**Why do this third:** Directly improves what auto-recall (#1) retrieves, and semantic tagging (#2) makes it easier to identify what to compress vs. preserve.

### Performance benchmarks:
- [ ] **Establish formal benchmarks**: Define metrics (context leverage ratio, recall accuracy, subagent efficiency, wall-clock time) and create reproducible test suites.
- [ ] **Compare against paper results**: The paper reports 100x context leverage. Our best is 5,600x on CPython (total codebase) and 63x on Juice Shop (relevant content). Understand where we're outperforming and where we're falling short.
- [ ] **Benchmark against competing tools**: Compare RLM analysis vs. Aider's repo map, Cursor's codebase indexing, OpenClaw's hybrid search on identical tasks.

### Chunking strategy improvements:
- [ ] **Adaptive chunk sizing**: Instead of fixed chunk sizes, dynamically size chunks based on content density and query relevance signals.
- [ ] **Cross-file dependency awareness**: When analyzing function X, automatically include its imports, callers, and type definitions in the same chunk.
- [ ] **AST-aware chunking for more languages**: Expand proper AST parsing beyond Python to JS/TS, Go, Rust (currently regex-based).

### Subagent dispatch improvements:
- [ ] **Smarter pre-filtering**: Use grep/keyword analysis before dispatching subagents to skip irrelevant chunks (already done for recall, extend to analysis).
- [ ] **Confidence-based early termination**: If first wave of subagents all agree on a finding with high confidence, skip remaining waves.
- [ ] **Result deduplication**: Detect when multiple subagents report the same finding from different chunks.

### Iteration loop improvements:
- [ ] **Drill-down heuristics**: Better automatic decisions about when to re-chunk at finer granularity vs. when to accept results.
- [ ] **Cross-reference resolution**: When a subagent says "this function calls X.authenticate()", automatically queue X for analysis.

## 5. SQLite Memory Store Improvements

**The goal:** Make the storage layer more robust, efficient, and capable as the memory store grows beyond hundreds to thousands+ entries.

**Why do this fifth:** These are incremental improvements that matter at scale. Not urgent for early adoption.

**The problem:** Raw session JSONL files are ~2.5MB. The current export script reduces this to ~107KB (24x compression) by extracting only user/assistant messages and summarizing tool calls. But 107KB is still a lot of content for a single conversation, much of which is boilerplate, repeated context, or verbose tool output that isn't useful for long-term memory.

**The goal:** Reduce stored conversation size by another 5-10x while preserving the information that matters for future recall. Like human memory: remember the decisions, insights, and key exchanges — not every keystroke.

### Current state (24x compression already):
The export script (`examples/export_session.py`) already:
- ✅ Strips tool results (verbose command output)
- ✅ Summarizes tool calls to one-liners (`[Tool: Bash] git status`)
- ✅ Deduplicates streaming assistant messages
- ✅ Keeps only user and assistant messages
- Result: ~2.5MB raw JSONL → ~107KB exported transcript

### Additional compression opportunities:
- [ ] **Strip system reminders and hook output**: The JSONL contains `system-reminder` blocks, hook success messages, linter notifications. These are noise for memory purposes.
- [ ] **Collapse repetitive exchanges**: If the user says "yes" and the assistant says "OK, doing it now" followed by 10 tool calls then a summary, compress to just the summary.
- [ ] **Extract decisions and findings**: Pull out the "we decided X because Y" moments and tag them specially.
- [ ] **Remove boilerplate assistant responses**: "Let me check...", "Great question!", "Here's what I found:" — these are conversational filler.
- [ ] **Summarize code blocks**: Instead of storing full code output, store "wrote 45-line function `authenticate()` in `auth.py`" with a reference to the commit hash.

### Tiered storage approach:
- [ ] **Tier 1: Summary** (~2-5KB) — Key decisions, findings, topics discussed, files modified. Auto-generated at session end.
- [ ] **Tier 2: Conversation** (~20-50KB) — The human-readable back-and-forth, compressed. What we store today but smarter.
- [ ] **Tier 3: Full transcript** (~100KB+) — Everything including tool calls. Kept for forensic recall but not loaded by default.
- [ ] Store all three tiers, search Tier 1 first, drill into Tier 2/3 only when needed.

### Counterpoints to aggressive compression (things to be careful about):
- Tool call sequences sometimes contain important context ("I tried X, it failed, so I did Y instead"). The failure path is often more informative than the success.
- Error messages and debugging exchanges are high-value for future recall ("how did we fix that bug last time?").
- The full transcript is already only loaded by subagents (not the main context), so storage cost matters more than retrieval cost.

## 4. RLM Analysis Engine Improvements

**The goal:** Reach and exceed the efficiency gains reported in the paper. Make RLM the best-in-class recursive analysis tool.

**Why do this fourth:** These are ongoing improvements to weave in as you encounter pain points. Not urgent compared to auto-recall, tagging, and compression.

### Schema improvements:
- [ ] **Conversation-specific metadata**: Add fields for session_id, project_path, turn_count, duration. Enable queries like "conversations from last week" or "longest sessions about project X".
- [ ] **Temporal indexing**: Index by date so temporal queries ("what was I doing last Tuesday") are fast.
- [ ] **Relationship tracking**: Link related memories (e.g., "this conversation continued from memory X" or "this decision supersedes memory Y").

### Search improvements:
- [ ] **Tag filtering in SQL**: Currently tags may be filtered in Python post-query. Move tag filtering into the SQL query itself for efficiency at scale.
- [ ] **Ranked tag search**: When searching by tag, weight exact matches higher than partial matches.
- [ ] **Configurable BM25 weights**: Allow tuning BM25 parameters (k1, b) for different content types (conversations vs. documents vs. code).

### Storage efficiency:
- [ ] **Content deduplication**: If the same conversation is archived twice (e.g., PreCompact + SessionEnd race condition edge case), detect and skip.
- [ ] **Incremental archiving**: Instead of storing the full conversation every time compaction happens, store only the delta since the last archive.
- [ ] **Compression**: Consider zlib compression for stored content. 107KB conversations would compress to ~15-20KB.
- [ ] **Retention policies**: Auto-summarize and compress old memories (>30 days) while keeping recent ones in full fidelity.

### Reliability:
- [ ] **WAL mode**: Enable SQLite WAL (Write-Ahead Logging) for better concurrent read/write performance.
- [ ] **Backup strategy**: Periodic backup of the memory database. Simple rsync or SQLite `.backup` command.
- [ ] **Integrity checks**: Periodic PRAGMA integrity_check on the database.

## 6. Cross-Platform Compatibility (Library-ification)

**The goal:** Make RLM + episodic memory a standalone library that any AI coding assistant, chatbot, or agent framework can use. Not just Claude Code.

**Why do this sixth:** The MCP server (#1) is the first step toward this. Once MCP works across multiple clients, abstracting the rest of the integration layer becomes the natural next move.

### Phase 1: Abstract the integration layer
- [ ] **Define a provider-agnostic hook interface**: Currently hooks are Claude Code-specific (`PreCompact`, `SessionEnd`). Define abstract events: `on_context_overflow`, `on_session_end`, `on_session_start`, `on_user_query`.
- [ ] **Abstract the session transcript format**: Currently parses Claude Code's JSONL format. Define a generic transcript format and write adapters for each platform.
- [ ] **Abstract the skill/prompt interface**: Currently uses SKILL.md for Claude Code skills. Define a generic "instruction set" that maps to each platform's prompt injection mechanism.

### Phase 2: Platform adapters
- [ ] **OpenAI Codex**: Research Codex's extension points, context management, and tool calling interface.
- [ ] **Gemini Code Assist**: Research Google's coding assistant hooks and integration APIs.
- [ ] **Cursor**: Research Cursor's `.cursor/` configuration, custom instructions, and MCP support.
- [ ] **Windsurf**: Research Windsurf's extension model.
- [ ] **Aider**: Research Aider's plugin system and repo map integration.
- [ ] **Generic chatbot integration**: Define a minimal API (`remember()`, `recall()`, `analyze()`) that any chatbot framework could call.

### Phase 3: Package and distribute
- [ ] **PyPI package**: `pip install rlm` or `uv pip install rlm` for the core library.
- [ ] **CLI tool**: `rlm` as a standalone command-line tool (already exists, just needs packaging).
- [ ] **MCP server**: Expose RLM as an MCP server so any MCP-compatible client gets memory for free. (Already covered in #1)
- [ ] **Documentation**: Getting started guides per platform, API reference, architecture docs.
- [ ] **Example integrations**: Working examples for each supported platform.

## 7. Advanced Memory Intelligence

**The goal:** Make the memory system smarter over time — importance scoring, consolidation, forgetting curves, better UX.

**Why do this last:** These are polish features that make a good system great. Tackle after the core experience (#1-3) and scale improvements (#4-6) are solid.

### Memory quality and intelligence:
- [ ] **Memory importance scoring**: Not all conversations are equally valuable. Score memories by information density, decision count, topic novelty. Prioritize high-value memories in search results.
- [ ] **Automatic tagging**: Use LLM to auto-generate semantic tags at archive time instead of just project name + date. "authentication", "architecture-decision", "debugging", "performance-optimization".
- [ ] **Memory consolidation**: Like sleep in humans — periodically review related memories and create consolidated "knowledge entries" that synthesize patterns across multiple conversations.
- [ ] **Forgetting curve**: Reduce the search weight of memories that have never been recalled. Frequently recalled memories get boosted. Natural Ebbinghaus-style decay.

### Developer experience:
- [ ] **Memory dashboard**: Simple web UI or TUI to browse, search, and manage the memory store.
- [ ] **Memory statistics**: `rlm stats` command showing entry count, total size, tag distribution, recall frequency, storage growth over time.
- [ ] **Export/import**: Export full memory store for backup or migration between machines.
- [ ] **Privacy controls**: Ability to mark certain memories as "do not recall" or auto-redact sensitive content (API keys, passwords) before storage.