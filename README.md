# RLM: Recursive Language Model for Claude Code

> **Paper:** [Scaling LLM Inference with Optimized Sample Compute Allocation](https://arxiv.org/html/2512.24601v2)

The RLM paper's key finding is deceptively simple: LLMs don't need to *see* content to reason about it. By giving an LLM access to a REPL, it can write code to programmatically scan, chunk, and inspect content that would never fit in its context window -- then call sub-LLMs on individual pieces and synthesize the results. The researchers showed this lets models process inputs 100x beyond their context limits with no architectural changes, no fine-tuning, and no RAG pipeline. The LLM just needs tools and the idea that it can use them recursively.

This project adapts that technique for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Claude Code already has Bash (our REPL) and Task subagents (our sub-LLM calls), so the entire RLM loop runs natively on an existing subscription with zero API keys. A Python toolkit handles scanning, chunking, and extraction while Claude orchestrates the recursive analysis -- never loading raw content into its own context, only metadata and subagent findings.

## How It Works

```
/rlm "find security issues" ./src/
                 |
     [1. Scan] Python produces metadata -- file tree, sizes,
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

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI)
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

No API keys needed -- everything runs on your existing Claude Code subscription. No external Python dependencies -- stdlib only.

## Installation

```bash
git clone <repo-url> ~/Kode/recursive-ai
cd ~/Kode/recursive-ai
bash install.sh
```

The installer sets up four things — all in your home directory, nothing in your project:

1. **Skill prompt** — Symlinks `SKILL.md` into `~/.claude/skills/rlm/` so Claude Code recognizes the `/rlm` command
2. **Python package** — Runs `uv sync` to install the `rlm` CLI
3. **Hooks** — Symlinks PreCompact, SessionEnd, and SessionStart hooks into `~/.claude/hooks/` for automatic conversation archiving
4. **MCP server** — Registers a user-scoped MCP server in `~/.claude.json` so `rlm_recall`, `rlm_remember`, etc. are available as native tools in every project

No files are added to any project directory. Everything lives under `~/.claude/`, `~/.rlm/`, and the cloned repo.

## Usage

In any Claude Code session:

```
# Analysis -- query + path
/rlm "find security vulnerabilities" ./src/
/rlm "summarize the architecture" ~/projects/my-app/
/rlm "find all API endpoints and their auth requirements" ./backend/

# Recall -- query alone (searches persistent memory)
/rlm "what did we decide about authentication"
/rlm "what was I working on last session"

# Store -- remember + content
/rlm remember "The deploy process requires running migrations first" --tags "deploy,ops" --summary "Deploy prerequisites"
```

For **analysis**, the format is `"<query>" <path>` -- query in quotes, followed by a file or directory path.
For **recall**, just a quoted query with no path.
For **storage**, the keyword `remember` followed by quoted content (with optional `--tags` and `--summary`).

Claude will then autonomously:
1. Scan the target for metadata
2. Choose an appropriate chunking strategy
3. Decompose the content and dispatch subagents
4. Iterate if needed (up to 15 iterations)
5. Synthesize and present findings

## Unified Memory

After the `memory-integrated` branch was merged into `main`, all three capabilities -- analysis, recall, and storage -- are handled by a single `/rlm` command. There are no separate `/recall` or `/remember` commands. Routing is determined by the argument pattern:

| Invocation | Mode | What It Does |
|---|---|---|
| `/rlm "query" ./path/` | **Analysis** | Recursive scan-chunk-dispatch analysis of a codebase or file |
| `/rlm "query"` | **Recall** | Searches persistent memory at `~/.rlm/memory/` and synthesizes an answer |
| `/rlm remember "content"` | **Store** | Saves content to persistent memory with tags and summary |

### How Recall Works

Recall uses the same architectural principles as codebase analysis (metadata-first, bounded output, subagent delegation) but inverts the starting condition: instead of analyzing a known target path, it must *find* what to inspect across a growing knowledge store.

**The key architectural difference from standard RAG:**

| Aspect | Standard RAG (e.g., OpenClaw) | RLM Recall |
|--------|-------------------------------|------------|
| **Semantic understanding** | At index time (via embeddings) | At query time (via LLM evaluation) |
| **Search method** | Vector similarity or hybrid (vector + keyword weighted scoring) | Two-tier: Keyword pre-filter → LLM evaluation |
| **Retrieval quality** | Limited by embedding model quality | Scales with LLM capability |
| **Dependencies** | Embedding API or local model + vector DB extension | Pure SQLite FTS5 + LLM |
| **Complexity** | High (embedding pipeline, vector storage, hybrid scoring) | Minimal (keyword index only) |
| **Cost model** | Embedding API calls per document at index time | LLM tokens per query at retrieval time |
| **Offline capability** | Yes (with local embeddings) | Yes (FTS5 works offline, LLM evaluation requires API) |

Standard RAG embeds everything upfront and searches by vector similarity. RLM uses **cheap keyword search to find candidates**, then applies **expensive LLM intelligence only where it matters** — evaluating the actual relevance of each candidate entry. This inverts the cost structure: index time is free, query time is smart.

**The retrieval pipeline:**

1. **Load learned patterns** -- Before searching, the system loads `~/.rlm/strategies/learned_patterns.md`, a file of retrieval heuristics accumulated from previous recall sessions (e.g., "use vocabulary variants for topical queries").
2. **Deep keyword search** -- Scans entry content (not just metadata) across the FTS5 index for candidate matches using BM25 ranking.
3. **Grep pre-filtering** -- Before dispatching a subagent, runs a regex grep within each candidate entry to confirm keyword presence and locate relevant sections. Entries with no matches are skipped, keeping subagent count proportional to *relevant* entries rather than *matching* entries. This eliminates false positives from index-level scoring.
4. **Graduated subagent dispatch** -- Sends the top 4-5 entries to subagents first. If the query is answered, stop. If gaps remain, dispatch more. Each subagent extracts the full entry content and evaluates it for relevance, returning attributed quotes and summaries.
5. **Synthesis** -- Combines subagent findings into a structured answer with attributed quotes and source entry IDs.
6. **Performance logging and learning** -- Logs metrics to `~/.rlm/strategies/performance.jsonl` (query, search terms, entries found/relevant, subagents dispatched, notes). If the agent discovers a reusable retrieval heuristic during the session, it writes it to `learned_patterns.md` for future sessions to load and apply.

This creates a **self-improving retrieval loop** where the "model" being trained is the skill prompt's heuristics, the "training signal" is the agent's self-assessment, and the "weights" are the patterns file. No fine-tuning, no RAG pipeline, no embedding models — just an LLM learning to search better through prompt-level online learning.

### How Storage Works

Store a piece of knowledge for later recall:

```
/rlm remember "The auth module uses JWT tokens with 24h expiry" --tags "auth,jwt,security" --summary "Auth token configuration"
/rlm remember --file ./notes/architecture-decisions.md --tags "architecture,decisions" --summary "ADR log"
```

Tags and summaries are used for search indexing. If omitted, the system generates them automatically.

### Memory Setup

Memory requires no additional setup beyond installation. The memory store is created automatically at `~/.rlm/memory/` on first use. Key paths:

| Path | Purpose |
|---|---|
| `~/.rlm/memory/memory.db` | SQLite FTS5 database (all entries + full-text index) |
| `~/.rlm/strategies/learned_patterns.md` | Self-improving retrieval heuristics |
| `~/.rlm/strategies/performance.jsonl` | Performance log from recall sessions |

#### Automatic Conversation Archiving

RLM includes Claude Code hooks that automatically archive your conversations to memory, creating a searchable knowledge base of all your work. This enables true cross-session continuity — you can pick up where you left off days or weeks later by simply asking what you were working on.

Hooks are installed automatically by `install.sh`. They work from any project directory — no per-project setup needed.

**What the hooks do:**

- **PreCompact hook** fires before every compaction (manual or automatic), exporting the full conversation transcript to `~/.rlm/memory/`
- **SessionEnd hook** fires when a session ends without compaction, ensuring zero data loss
- Conversations are tagged with `conversation`, `session`, project name, and date for easy retrieval
- Marker files prevent duplicate archiving (60-second deduplication window)
- Together, these hooks guarantee **100% conversation capture**

**Usage after installation:**

```
# Retrieve previous work
/rlm "what was I working on last session"
/rlm "what did we decide about authentication"
/rlm "openclaw voyage ai embeddings"

# The hooks archive automatically — nothing else needed
```

See [hooks/README.md](hooks/README.md) for detailed installation instructions and troubleshooting.

#### Manual Memory Population

To populate memory with existing chat data, use the ingestion scripts:

```bash
# Ingest CSV archives or Firebase exports from chat platforms
uv run python scripts/ingest_chat_data.py --source csv --path /path/to/archive.csv
uv run python scripts/ingest_chat_data.py --source firebase --path /path/to/firebase-export.json
```

### Memory CLI Commands

These commands can also be used standalone outside of `/rlm`:

```bash
# Search memory (FTS5 always searches content — --deep is accepted but no longer needed)
uv run rlm recall "query" [--tags tag1,tag2] [--max 20]

# Store a memory
uv run rlm remember "content" --tags "tag1,tag2" --summary "description"
uv run rlm remember --file /path/to/file --tags "tag1,tag2" --summary "description"

# Browse memory
uv run rlm memory-list [--tags tag1,tag2] [--offset 0] [--limit 50]
uv run rlm memory-tags

# Grep within a specific entry (pre-filter before subagent dispatch)
uv run rlm memory-extract <entry_id> --grep "pattern" --context 3

# Extract full entry content
uv run rlm memory-extract <entry_id>

# View/manage retrieval strategies
uv run rlm strategy show
uv run rlm strategy log

# Delete a memory
uv run rlm forget <entry_id>

# Export a session transcript (used by hooks, also available standalone)
uv run rlm export-session /path/to/session.jsonl [--output /path/to/output.txt]
```

## Architecture

### Modules

```
rlm/
  scanner.py    Metadata production. Scans paths to produce file trees,
                sizes, line counts, language detection, and structure
                outlines (function/class names with line ranges). Uses
                Python's ast module for Python files, regex patterns for
                JS/TS, Go, Rust, Ruby, Java, and others. Never outputs
                full file content.

  chunker.py    Content decomposition. Six strategies that produce chunk
                manifests (metadata only, never raw content):
                - lines: fixed-size line ranges with configurable overlap
                - files_directory: group files by parent directory
                - files_language: group files by programming language
                - files_balanced: balanced groups by total size
                - functions: split at function/class boundaries
                - headings: split markdown at heading boundaries
                - semantic: split at blank-line boundaries, adaptively sized
                Also includes a recommendation engine that suggests the
                best strategy based on content type and size.

  extractor.py  Targeted content retrieval. When Claude (or a subagent)
                needs actual text, it requests specific slices:
                - Line ranges (e.g., lines 142-200 of auth.py)
                - Chunk IDs from a manifest
                - Grep matches with surrounding context

  state.py      Session persistence. Each Bash invocation is a new process,
                so state lives on disk at /tmp/rlm-sessions/{session_id}/.
                Tracks the query, iteration log, accumulated subagent
                results, and final answer.

  memory.py     Persistent long-term memory. High-level API for storage,
                search, grep-within-entry, and bounded formatting. Delegates
                to db.py for all SQLite operations.

  db.py         SQLite FTS5 backend. Schema management, CRUD, full-text
                search with BM25 ranking and Porter stemming. Handles
                thread-local connections and auto-migration from JSON.

  export.py     Session transcript exporter. Reads Claude Code .jsonl session
                files and produces readable conversation text, stripping tool
                results and deduplicating streaming artifacts (~24x compression).

  cli.py        CLI entry point. All Claude<->Python interaction goes
                through subcommands. All output is capped at 4000 characters
                with truncation notices, enforcing the bounded-output
                principle from the paper.

skill/
  SKILL.md      The unified skill prompt. Loaded into Claude Code when the
                user invokes /rlm. Routes by argument pattern to one of
                three modes: analysis (query + path), recall (query alone),
                or store (remember + content). Contains the 5-step analysis
                loop, the 6-step recall flow (learned patterns, search,
                grep pre-filter, graduated dispatch, synthesize, learn),
                and the storage flow.
```

### Adaptive Retrieval

The recall mode of `/rlm` uses a self-improving retrieval loop:

1. **Learned patterns** -- Before each recall, load `~/.rlm/strategies/learned_patterns.md` -- heuristics discovered in previous sessions (e.g., "use vocabulary variants for topical queries").
2. **Grep pre-filtering** -- Before dispatching subagents, grep within each candidate entry to confirm keyword presence. Eliminates false positives from index-level matching.
3. **Graduated dispatch** -- Start with top entries, evaluate, expand only if synthesis is incomplete. Avoids the "16 subagents, 12 empty" problem.
4. **Performance logging** -- After each session, log metrics (query, search terms, entries found/relevant, subagents used) to `~/.rlm/strategies/performance.jsonl`.
5. **Pattern learning** -- If the agent discovers a reusable retrieval heuristic, it writes it to `learned_patterns.md`. Future sessions load and apply these patterns.

This creates a feedback loop where the retrieval strategy improves with use -- the "model" being trained is the skill prompt's heuristics, the "training signal" is the agent's self-assessment, and the "weights" are the patterns file.

### Data Flow

Nothing large ever enters Claude's context. The flow is:

1. **Metadata in** -- `rlm scan` produces a ~2-4KB summary of the target (file count, line counts, languages, structure names). Claude reads this to understand what it's dealing with.

2. **Chunk manifest in** -- `rlm chunk` produces a list of chunk IDs with line ranges, char counts, and short previews. Claude uses this to plan which chunks to analyze.

3. **Extracted content to subagents** -- `rlm extract` retrieves actual file content for a specific chunk. This content goes into a Task subagent prompt, not into the main context. The subagent analyzes it and returns a short structured finding.

4. **Findings in** -- Subagent results (short text) flow back to the main context. Claude accumulates these and decides whether to iterate or synthesize.

5. **Bounded output always** -- Every CLI command caps its stdout at 4000 characters. Even if someone points RLM at a million-line codebase, the orchestrator's context only ever contains bounded summaries.

### Session State

Because each `uv run rlm ...` command runs in a fresh Python process, session state is persisted to `/tmp/rlm-sessions/{session_id}/`:

```
/tmp/rlm-sessions/a1b2c3d4e5f6/
  state.json      Query, iteration log, accumulated results, status
  manifest.json   Chunk manifest from the most recent chunking operation
```

## CLI Reference

The CLI is also usable standalone for exploring codebases:

```bash
# Scan a path -- get metadata summary
uv run rlm scan ./src/
uv run rlm scan ./src/auth.py
uv run rlm scan . --depth 5

# Get chunking strategy recommendations
uv run rlm recommend ./src/

# Chunk content (produces manifest, not content)
uv run rlm chunk ./src/auth.py --strategy functions
uv run rlm chunk ./src/ --strategy files_directory
uv run rlm chunk ./src/auth.py --strategy lines --chunk-size 300 --overlap 30
uv run rlm chunk ./docs/guide.md --strategy headings --heading-level 2
uv run rlm chunk ./src/big_file.py --strategy semantic --target-size 30000

# Extract actual content
uv run rlm extract ./src/auth.py --lines 1:50
uv run rlm extract ./src/auth.py --grep "password|secret|token"
uv run rlm extract ./src/auth.py --chunk-id abc123 --manifest /tmp/rlm-sessions/xyz/manifest.json

# Session management
uv run rlm init "find bugs" ./src/
uv run rlm status <session_id>
uv run rlm result <session_id> --key finding_1 --value "SQL injection in query.py:42"
uv run rlm result <session_id> --all
uv run rlm finalize <session_id> --answer "Found 3 critical issues..."
```

## Chunking Strategies

| Strategy | Best For | How It Splits |
|---|---|---|
| `functions` | Source code with clear structure | Function and class boundaries (ast for Python, regex for others) |
| `files_directory` | Small-medium projects | Groups files by parent directory |
| `files_language` | Multi-language projects | Groups files by programming language |
| `files_balanced` | Large projects | Balanced groups by total character count |
| `headings` | Markdown and documentation | Heading boundaries (configurable level) |
| `semantic` | Prose, config, unstructured text | Blank-line boundaries, adaptively sized |
| `lines` | Fallback for anything | Fixed-size line ranges with overlap |

The `recommend` command suggests the best strategy based on what it finds:

```
$ uv run rlm recommend ./src/
Recommended strategies for: ./src/

  [1] files_directory: Small project (15 files) -- group by directory
  [2] files_directory: Group files by directory for structural analysis
```

## Language Support

Structure extraction (function/class detection) works for:

| Language | Method | Detects |
|---|---|---|
| Python | `ast` module | Functions, classes, async functions |
| JavaScript/TypeScript | Regex | Functions, arrow functions, classes, methods |
| Go | Regex | Functions, methods, structs, interfaces |
| Rust | Regex | Functions, structs, enums, traits, impls |
| Ruby | Regex | Classes, modules, methods |
| Java/Kotlin/C#/Scala | Regex | Classes, interfaces, enums, methods |
| Others | Generic regex | `def`/`func`/`function`/`class` patterns |

Language detection covers 40+ file extensions. Files with unrecognized extensions are labeled `unknown` but still scanned for line counts and sizes.

## Design Decisions

**Zero external dependencies.** The entire project uses only Python's standard library (`os`, `pathlib`, `json`, `re`, `ast`, `argparse`, `hashlib`, `uuid`, `sqlite3`, `time`). Memory search uses SQLite FTS5 with BM25 ranking and Porter stemming — all built into Python's `sqlite3` module. This means `uv sync` is near-instant with no version conflicts.

**Subagents, not direct reads.** The orchestrating Claude never reads target files with the Read tool. All content flows through `rlm extract` into Task subagents. This is the core principle from the RLM paper -- the LLM reasons about structure and delegates content inspection.

**Haiku subagents.** Chunk analysis subagents use the `haiku` model for speed and cost efficiency. The root orchestration runs on whatever model you're using in Claude Code.

**File-based state.** Each `uv run rlm` invocation is a separate Python process, so session state persists to `/tmp/rlm-sessions/`. This survives across the many Bash tool invocations in a single Claude Code conversation.

**All output is bounded.** Every CLI command caps stdout at 4000 characters. This prevents accidentally loading huge content into Claude's context and enforces the metadata-only principle. When output is truncated, a notice tells you to use `extract` for the full content.

**Deterministic chunk IDs.** Chunk IDs are MD5 hashes of `source:start_line:end_line`, so the same content always produces the same chunk ID. This makes caching and deduplication straightforward.

## How It Compares to Normal Claude Code

| | Normal Claude Code | With RLM |
|---|---|---|
| **Context usage** | Reads files directly into context | Only metadata and findings enter context |
| **Scale limit** | ~200K tokens of context | Arbitrarily large (tested on 100K+ line codebases) |
| **Analysis depth** | Sees everything at once but may miss details | Systematic chunk-by-chunk analysis with iteration |
| **Speed** | Fast for small targets | Slower setup, but parallelized analysis |
| **Best for** | Files that fit in context | Large codebases, exhaustive analysis, security audits |

## Test Results

### RLM (Recursive Analysis)

- [Test 1: Self-Referential Test](test_results/rlm/01-self-referential-test.md) -- RLM analyzing its own codebase. Compares before/after skill prompt fix, achieving 22x context leverage.
- [Test 2: Security Audit (Juice Shop)](test_results/rlm/02-security-audit-test.md) -- 83 vulnerabilities found in OWASP Juice Shop (95K lines). 81% recall on known categories, 63x context leverage.
- [Test 3: Scale Test (CPython stdlib)](test_results/rlm/03-scale-test.md) -- 100+ architectural patterns cataloged across CPython's 1.18M-line standard library (45MB). Bounded output held, 5,600x leverage ratio on total codebase.
- [Test 4: Eval Safety Audit (CPython stdlib)](test_results/rlm/04-eval-safety-test.md) -- 455 eval() calls classified across CPython's stdlib. Found critical RCE in logging/config.py listen(). First test to exercise the recursive iteration loop (grep-first, wave 1, drill-down, synthesize).

### Recall (Persistent Memory)

- [Test 1: "san diego"](test_results/recall/01-san-diego-recall.md) -- Searched 336 memory entries across 15 years of chat history. Found 5 scattered mentions across 2004-2009, 16 subagent dispatches, 3m21s.
- [Test 2: "synopit"](test_results/recall/02-synopit-recall.md) -- Reconstructed full startup timeline (concept → launch → font issues → early users) from 4 weekly archives. 1 subagent, 42s.
- [Test 3: "what did User A say about Futurama"](test_results/recall/03-goober-futurama-recall.md) -- Truthful negative: User A had 1 mention. System identified the actual Futurama fans (User B, User C, User D) with attributed quotes across 4 time periods.
- [Test 4: "what did everyone think about the Iraq war"](test_results/recall/04-iraq-war-opinions-recall.md) -- Political profiles of 8 people reconstructed from 3 years of debate (2002-2005). Captured spectrum from moral philosophy to policy critique to conspiracy theory. 6:1 anti-war ratio identified. The strongest demonstration of iterative retrieval + analysis vs. single-pass RAG.

## Troubleshooting

**`/rlm` command not found:** Run `bash install.sh` again to re-symlink the skill. Make sure `~/.claude/skills/rlm/SKILL.md` exists.

**`uv run rlm` fails:** Make sure you're in the `recursive-ai` directory, or that the package is installed (`uv sync`).

**Session not found:** Sessions live in `/tmp/` and may be cleared on reboot. This is by design -- sessions are ephemeral per-conversation artifacts.

**Truncated output:** This is intentional. Use `rlm extract` with specific line ranges or chunk IDs to get full content for the parts you need.

## License

MIT
