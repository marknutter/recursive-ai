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
git clone <repo-url> && cd recursive-ai
bash install.sh
```

This does two things:
1. Symlinks the skill prompt into `~/.claude/skills/rlm/SKILL.md` so Claude Code recognizes the `/rlm` command
2. Runs `uv sync` to install the `rlm` Python package

## Usage

In any Claude Code session:

```
/rlm "find security vulnerabilities" ./src/
/rlm "summarize the architecture" ~/projects/my-app/
/rlm "find all API endpoints and their auth requirements" ./backend/
/rlm "what are the performance bottlenecks?" ./lib/
```

The argument format is `"<query>" <path>`. The query goes in quotes, followed by a file or directory path.

Claude will then autonomously:
1. Scan the target for metadata
2. Choose an appropriate chunking strategy
3. Decompose the content and dispatch subagents
4. Iterate if needed (up to 15 iterations)
5. Synthesize and present findings

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

  cli.py        CLI entry point. All Claude<->Python interaction goes
                through subcommands. All output is capped at 4000 characters
                with truncation notices, enforcing the bounded-output
                principle from the paper.

skill/
  SKILL.md      The skill prompt that encodes the full RLM algorithm.
                Loaded into Claude Code when the user invokes /rlm. Contains
                the 5-step orchestration loop, decision heuristics, subagent
                dispatch patterns, and iteration limits.
```

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

**Zero external dependencies.** The entire project uses only Python's standard library (`os`, `pathlib`, `json`, `re`, `ast`, `argparse`, `hashlib`, `uuid`, `textwrap`, `time`). This means `uv sync` is near-instant with no version conflicts.

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

- [Test 1: Self-Referential Test](test_results/01-self-referential-test.md) -- RLM analyzing its own codebase. Compares before/after skill prompt fix, achieving 22x context leverage.
- [Test 3: Security Audit (Juice Shop)](test_results/03-security-audit-test.md) -- 83 vulnerabilities found in OWASP Juice Shop (95K lines). 81% recall on known categories, 63x context leverage.

## Troubleshooting

**`/rlm` command not found:** Run `bash install.sh` again to re-symlink the skill. Make sure `~/.claude/skills/rlm/SKILL.md` exists.

**`uv run rlm` fails:** Make sure you're in the `recursive-ai` directory, or that the package is installed (`uv sync`).

**Session not found:** Sessions live in `/tmp/` and may be cleared on reboot. This is by design -- sessions are ephemeral per-conversation artifacts.

**Truncated output:** This is intentional. Use `rlm extract` with specific line ranges or chunk IDs to get full content for the parts you need.

## License

MIT
