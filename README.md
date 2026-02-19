# RLM: Recursive Language Model for Claude Code

> **Paper:** [Scaling LLM Inference with Optimized Sample Compute Allocation](https://arxiv.org/html/2512.24601v2)

RLM enables AI agents to analyze content far beyond their context windows while maintaining perfect memory across sessions. It adapts the recursive analysis technique from the research paper for [Claude Code](https://docs.anthropic.com/en/docs/claude-code), using Bash as the REPL and Task subagents as the sub-LLM calls. A Python toolkit handles scanning, chunking, and extraction while Claude orchestrates the recursive analysis — never loading raw content into its own context, only metadata and subagent findings.

## What It Does

### 1. Automatic Session Archiving (Passive)

Three hooks fire automatically during every Claude Code session:

- **SessionStart** — When a session opens, searches memory for recent conversations about the current project and injects a brief summary as context. This gives the agent immediate continuity without you having to ask "what was I working on."
- **PreCompact** — When Claude Code is about to compact your conversation (context window filling up), this captures and archives the full session before it's lost. Creates two entries: a ~1KB summary + a ~30-60KB compressed transcript, linked by a shared session ID tag.
- **SessionEnd** — Same archival as PreCompact, but fires when you close a session. Skips if PreCompact already archived within the last 60 seconds.

**Content deduplication:** If the same session file gets archived again and hasn't changed, it's skipped. If it's grown (more conversation happened), old entries are replaced with fresh ones.

**What gets stored:** Semantic tags are auto-extracted (e.g., `architecture-decision`, `bug-fix`, `mcp`), project name, date, and a compressed transcript with skill prompts stripped out.

### 2. MCP Server (Passive — Available as Native Tools)

Five tools are available in every Claude Code terminal session as native MCP operations:

| Tool | What it does |
|------|-------------|
| `rlm_recall` | Search memory by query + optional tag filter |
| `rlm_remember` | Store new memories |
| `rlm_memory_list` | Browse entries by tag |
| `rlm_memory_extract` | Extract full content with optional grep |
| `rlm_forget` | Delete entries |

These let any Claude session access your memory store without invoking the `/rlm` skill.

### 3. `/rlm` Skill (Active — You Invoke It)

Three modes, routed by argument:

**`/rlm "query"` — Recall mode**
Searches your memories using deep keyword search + subagent evaluation:
1. Load learned retrieval patterns from past sessions
2. Deep search (scans content, not just tags/summaries)
3. Grep pre-filtering to eliminate false positives
4. Graduated subagent dispatch (top 4-5 first, expand if gaps)
5. Synthesize answer from relevant findings
6. Log performance and update learned patterns

**`/rlm "query" path/to/code` — Analysis mode**
Analyze any codebase or file beyond context window limits:
1. Scan target for metadata (size, structure, languages)
2. Choose chunking strategy (functions, files, headings, semantic, lines)
3. Dispatch parallel subagents — each extracts and analyzes its own chunk
4. Iterate: drill deeper or broaden based on findings
5. Synthesize final answer

**`/rlm remember "content"` — Store mode**
Manually save knowledge with auto-generated tags and summary.

### 4. TUI Dashboard (`rlm tui`)

Interactive terminal UI with 5 tabs:

| Tab | What it does |
|-----|-------------|
| **Browse** | DataTable of all entries + tag sidebar for filtering |
| **Search** | FTS5 full-text search with BM25 ranking |
| **Detail** | View entry content with in-entry grep |
| **Stats** | Entry counts, size distribution, source breakdown, top tags |
| **Tags** | Full tag list with counts, click to filter Browse |

Keyboard: `1-5` switch tabs, `d` delete entry, `r` refresh, `q` quit.

### 5. CLI Commands

All available via `rlm <command>`:

**Memory management:**
- `remember`, `recall`, `memory-extract`, `memory-list`, `memory-tags`, `forget`
- `strategy show/log/perf` — view and manage learned retrieval patterns
- `stats` — store-wide statistics
- `tui` — launch dashboard

**Analysis engine:**
- `scan`, `chunk`, `extract`, `recommend` — RLM analysis primitives
- `init`, `status`, `result`, `finalize` — session management

**Utility:**
- `export-session` — convert Claude Code .jsonl to compressed transcript

### What You Should Expect

**Automatically happening in the background:**
- Every session gets archived before compaction or on close
- Every new session gets recent project context injected
- Duplicate archives are skipped

**When you actively use it:**
- `/rlm "what was I working on yesterday"` — recalls from archived sessions
- `/rlm "security review" src/` — analyzes a codebase without loading it all into context
- `/rlm remember "always use uv for Python"` — stores knowledge for future sessions
- `rlm tui` — visual browsing and management
- MCP tools available for any Claude session to read/write memory

---

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI)
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

No API keys needed — everything runs on your existing Claude Code subscription. No external Python dependencies beyond [textual](https://textual.textualize.io/) for the TUI.

## Installation

```bash
git clone <repo-url>
cd recursive-ai
bash install.sh
```

The installer sets up four things — all in your home directory, nothing in your project:

1. **Skill prompt** — Symlinks `SKILL.md` into `~/.claude/skills/rlm/` so Claude Code recognizes the `/rlm` command
2. **Python package** — Runs `uv sync` to install the `rlm` CLI
3. **Hooks** — Symlinks PreCompact, SessionEnd, and SessionStart hooks into `~/.claude/hooks/` for automatic conversation archiving
4. **MCP server** — Registers a user-scoped MCP server in `~/.claude.json` so `rlm_recall`, `rlm_remember`, etc. are available as native tools in every project

No files are added to any project directory. Everything lives under `~/.claude/`, `~/.rlm/`, and the cloned repo.

To make `rlm` available globally without `uv run`:

```bash
uv tool install -e .
```

## Usage

In any Claude Code session:

```
# Analysis — query + path
/rlm "find security vulnerabilities" ./src/
/rlm "summarize the architecture" ~/projects/my-app/
/rlm find all API endpoints and their auth requirements ./backend/

# Recall — query alone (searches persistent memory)
/rlm what did we decide about authentication
/rlm what was I working on last session

# Store — remember + content
/rlm remember "The deploy process requires running migrations first" --tags "deploy,ops" --summary "Deploy prerequisites"
```

Quotes around the query are optional — Claude parses the intent from context.

### Memory CLI

```bash
# Search memory
rlm recall "query" [--tags tag1,tag2] [--max 20]

# Store a memory
rlm remember "content" --tags "tag1,tag2" --summary "description"
rlm remember --file /path/to/file --tags "tag1,tag2" --summary "description"

# Browse memory
rlm memory-list [--tags tag1,tag2] [--offset 0] [--limit 50]
rlm memory-tags

# Grep within a specific entry
rlm memory-extract <entry_id> --grep "pattern" --context 3

# Extract full entry content
rlm memory-extract <entry_id>

# View/manage retrieval strategies
rlm strategy show
rlm strategy log

# Delete a memory
rlm forget <entry_id>

# Export a session transcript
rlm export-session /path/to/session.jsonl

# Store statistics
rlm stats

# Interactive dashboard
rlm tui
```

### Analysis CLI

```bash
# Scan a path — get metadata summary
rlm scan ./src/
rlm scan ./src/auth.py
rlm scan . --depth 5

# Get chunking strategy recommendations
rlm recommend ./src/

# Chunk content (produces manifest, not content)
rlm chunk ./src/auth.py --strategy functions
rlm chunk ./src/ --strategy files_directory
rlm chunk ./src/auth.py --strategy lines --chunk-size 300 --overlap 30
rlm chunk ./docs/guide.md --strategy headings --heading-level 2
rlm chunk ./src/big_file.py --strategy semantic --target-size 30000

# Extract actual content
rlm extract ./src/auth.py --lines 1:50
rlm extract ./src/auth.py --grep "password|secret|token"
rlm extract ./src/auth.py --chunk-id abc123 --manifest /tmp/rlm-sessions/xyz/manifest.json

# Session management
rlm init "find bugs" ./src/
rlm status <session_id>
rlm result <session_id> --key finding_1 --value "SQL injection in query.py:42"
rlm result <session_id> --all
rlm finalize <session_id> --answer "Found 3 critical issues..."
```

### Manual Memory Population

To populate memory with existing chat data:

```bash
rlm remember --file ./notes/architecture-decisions.md --tags "architecture,decisions" --summary "ADR log"

# Ingest CSV archives or Firebase exports from chat platforms
uv run python scripts/ingest_chat_data.py --source csv --path /path/to/archive.csv
uv run python scripts/ingest_chat_data.py --source firebase --path /path/to/firebase-export.json
```

---

## How It Works

### The RLM Analysis Loop

```
/rlm "find security issues" ./src/
                 |
     [1. Scan] Python produces metadata — file tree, sizes,
               languages, structure outlines. No content loaded.
                 |
     [2. Plan] Claude sees metadata, picks a chunking strategy
               (by functions, files, headings, etc.)
                 |
     [3. Chunk] Python decomposes content into a manifest of
                chunk IDs with line ranges and previews.
                 |
     [4. Dispatch] Claude extracts chunk content and spawns
                   parallel Task subagents to analyze each piece.
                 |
     [5. Evaluate] Are results sufficient? Need finer detail?
                   Loop back to re-chunk, or proceed to synthesis.
                 |
     [6. Synthesize] Combine all subagent findings into a
                     structured answer for the user.
```

The key insight: **Claude is the orchestrator, not the reader.** It sees metadata and makes decisions. Subagents see actual content and return findings. This keeps the main context window clean for reasoning while subagents do the heavy lifting across arbitrarily large codebases.

### How Recall Differs from RAG

| Aspect | Standard RAG | RLM Recall |
|--------|-------------|------------|
| **Semantic understanding** | At index time (via embeddings) | At query time (via LLM evaluation) |
| **Search method** | Vector similarity or hybrid scoring | Two-tier: keyword pre-filter → LLM evaluation |
| **Retrieval quality** | Limited by embedding model quality | Scales with LLM capability |
| **Dependencies** | Embedding API + vector DB | Pure SQLite FTS5 + LLM |
| **Complexity** | High (embedding pipeline, vector storage) | Minimal (keyword index only) |
| **Cost model** | Embedding API calls per document at index time | LLM tokens per query at retrieval time |

Standard RAG embeds everything upfront and searches by vector similarity. RLM uses **cheap keyword search to find candidates**, then applies **expensive LLM intelligence only where it matters** — evaluating the actual relevance of each candidate entry.

### Self-Improving Retrieval

The recall pipeline includes a feedback loop:

1. **Learned patterns** — Before each recall, load `~/.rlm/strategies/learned_patterns.md` — heuristics discovered in previous sessions
2. **Grep pre-filtering** — Before dispatching subagents, grep within each candidate to confirm keyword presence. Eliminates false positives
3. **Graduated dispatch** — Start with top entries, evaluate, expand only if synthesis is incomplete
4. **Performance logging** — After each session, log metrics to `~/.rlm/strategies/performance.jsonl`
5. **Pattern learning** — If the agent discovers a reusable retrieval heuristic, it writes it to `learned_patterns.md` for future sessions

The "model" being trained is the skill prompt's heuristics, the "training signal" is the agent's self-assessment, and the "weights" are the patterns file. No fine-tuning, no embedding models — just prompt-level online learning.

### Data Flow

Nothing large ever enters Claude's context:

1. **Metadata in** — `rlm scan` produces a ~2-4KB summary. Claude reads this to understand what it's dealing with.
2. **Chunk manifest in** — `rlm chunk` produces chunk IDs with line ranges and previews. Claude uses this to plan dispatch.
3. **Extracted content to subagents** — `rlm extract` retrieves actual content into Task subagent prompts, not into the main context.
4. **Findings in** — Subagent results (short text) flow back. Claude accumulates and decides whether to iterate or synthesize.
5. **Bounded output always** — Every CLI command caps stdout at 4000 characters, enforcing the metadata-only principle.

---

## Architecture

### Modules

```
rlm/
  scanner.py    Metadata production. File trees, sizes, line counts,
                language detection, structure outlines.

  chunker.py    Content decomposition. Seven strategies producing
                chunk manifests (metadata only, never raw content):
                lines, files_directory, files_language, files_balanced,
                functions, headings, semantic.

  extractor.py  Targeted content retrieval. Line ranges, chunk IDs,
                or grep matches with surrounding context.

  state.py      Session persistence at /tmp/rlm-sessions/{session_id}/.

  memory.py     Persistent long-term memory. Storage, search,
                grep-within-entry, bounded formatting.

  db.py         SQLite FTS5 backend. Schema management, CRUD,
                full-text search with BM25 ranking and Porter stemming.

  archive.py    Two-tier session archiving with content deduplication.
                Shared logic for PreCompact and SessionEnd hooks.

  summarize.py  Session summary generation from compressed transcripts.

  semantic_tags.py  LLM-based tag extraction with keyword fallback.

  export.py     Session transcript exporter. Reads Claude Code .jsonl
                files, strips tool results, deduplicates streaming
                artifacts (~24x compression).

  tui.py        Interactive terminal dashboard (textual). Browse,
                search, detail view, stats, tag management.

  cli.py        CLI entry point. All output capped at 4000 chars.

skill/
  SKILL.md      The unified skill prompt. Routes by argument to
                analysis, recall, or store mode.

hooks/
  pre-compact-rlm-semantic.py   Archive before compaction
  session-end-rlm-semantic.py   Archive on session close
  (SessionStart hook at ~/.claude/hooks/rlm-sessionstart.py)

mcp/
  server.py     MCP server exposing 5 memory tools as native operations
```

### Key Paths

| Path | Purpose |
|------|---------|
| `~/.rlm/memory/memory.db` | SQLite FTS5 database (all entries + full-text index) |
| `~/.rlm/strategies/learned_patterns.md` | Self-improving retrieval heuristics |
| `~/.rlm/strategies/performance.jsonl` | Performance log from recall sessions |
| `~/.claude/skills/rlm/SKILL.md` | Skill prompt (symlink) |
| `~/.claude/hooks/rlm-*.py` | Hook scripts (symlinks) |
| `/tmp/rlm-sessions/` | Ephemeral analysis session state |

## Chunking Strategies

| Strategy | Best For | How It Splits |
|----------|----------|---------------|
| `functions` | Source code with clear structure | Function and class boundaries (ast for Python, regex for others) |
| `files_directory` | Small-medium projects | Groups files by parent directory |
| `files_language` | Multi-language projects | Groups files by programming language |
| `files_balanced` | Large projects | Balanced groups by total character count |
| `headings` | Markdown and documentation | Heading boundaries (configurable level) |
| `semantic` | Prose, config, unstructured text | Blank-line boundaries, adaptively sized |
| `lines` | Fallback for anything | Fixed-size line ranges with overlap |

## Language Support

Structure extraction (function/class detection) works for:

| Language | Method | Detects |
|----------|--------|---------|
| Python | `ast` module | Functions, classes, async functions |
| JavaScript/TypeScript | Regex | Functions, arrow functions, classes, methods |
| Go | Regex | Functions, methods, structs, interfaces |
| Rust | Regex | Functions, structs, enums, traits, impls |
| Ruby | Regex | Classes, modules, methods |
| Java/Kotlin/C#/Scala | Regex | Classes, interfaces, enums, methods |
| Others | Generic regex | `def`/`func`/`function`/`class` patterns |

Language detection covers 40+ file extensions.

## How It Compares to Normal Claude Code

| | Normal Claude Code | With RLM |
|---|---|---|
| **Context usage** | Reads files directly into context | Only metadata and findings enter context |
| **Scale limit** | ~200K tokens of context | Arbitrarily large (tested on 100K+ line codebases) |
| **Analysis depth** | Sees everything at once but may miss details | Systematic chunk-by-chunk analysis with iteration |
| **Speed** | Fast for small targets | Slower setup, but parallelized analysis |
| **Best for** | Files that fit in context | Large codebases, exhaustive analysis, security audits |

## Design Decisions

**Zero external dependencies (except TUI).** The core uses only Python's standard library. The TUI adds [textual](https://textual.textualize.io/) as the sole external dependency. Memory search uses SQLite FTS5 with BM25 ranking and Porter stemming — all built into Python's `sqlite3` module.

**Subagents, not direct reads.** The orchestrating Claude never reads target files with the Read tool. All content flows through `rlm extract` into Task subagents.

**Haiku subagents.** Chunk analysis subagents use the `haiku` model for speed and cost efficiency. The root orchestration runs on whatever model you're using in Claude Code.

**File-based state.** Each CLI invocation is a separate Python process, so session state persists to `/tmp/rlm-sessions/`. This survives across the many Bash tool invocations in a single conversation.

**All output is bounded.** Every CLI command caps stdout at 4000 characters. Even if someone points RLM at a million-line codebase, the orchestrator's context only ever contains bounded summaries.

**Deterministic chunk IDs.** Chunk IDs are MD5 hashes of `source:start_line:end_line`, so the same content always produces the same chunk ID.

## Test Results

### RLM (Recursive Analysis)

- [Test 1: Self-Referential Test](test_results/rlm/01-self-referential-test.md) — RLM analyzing its own codebase. 22x context leverage.
- [Test 2: Security Audit (Juice Shop)](test_results/rlm/02-security-audit-test.md) — 83 vulnerabilities found in OWASP Juice Shop (95K lines). 81% recall, 63x context leverage.
- [Test 3: Scale Test (CPython stdlib)](test_results/rlm/03-scale-test.md) — 100+ architectural patterns cataloged across CPython's 1.18M-line standard library. 5,600x leverage ratio.
- [Test 4: Eval Safety Audit (CPython stdlib)](test_results/rlm/04-eval-safety-test.md) — 455 eval() calls classified across CPython's stdlib. Found critical RCE in logging/config.py.

### Recall (Persistent Memory)

- [Test 1: "san diego"](test_results/recall/01-san-diego-recall.md) — Found 5 scattered mentions across 15 years of chat history from 336 entries.
- [Test 2: "synopit"](test_results/recall/02-synopit-recall.md) — Reconstructed full startup timeline from 4 weekly archives.
- [Test 3: "what did User A say about Futurama"](test_results/recall/03-goober-futurama-recall.md) — Truthful negative: identified the actual fans with attributed quotes.
- [Test 4: "what did everyone think about the Iraq war"](test_results/recall/04-iraq-war-opinions-recall.md) — Political profiles of 8 people reconstructed from 3 years of debate. Best demonstration of iterative retrieval vs. single-pass RAG.

## Troubleshooting

**`/rlm` command not found:** Run `bash install.sh` again. Make sure `~/.claude/skills/rlm/SKILL.md` exists.

**`rlm` CLI not found:** Run `uv tool install -e .` from the repo, or prefix with `uv run`.

**Session not found:** Sessions live in `/tmp/` and may be cleared on reboot. This is by design — sessions are ephemeral.

**Truncated output:** Intentional. Use `rlm extract` with specific line ranges or chunk IDs.

## License

MIT
