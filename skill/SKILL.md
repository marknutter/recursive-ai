---
name: rlm
description: Recursive analysis, persistent memory recall, and knowledge storage
argument-hint: "query" [path] | remember "content" [--tags t1,t2]
user_invocable: true
---

# RLM: Recursive Language Model Analysis

You are executing the RLM (Recursive Language Model) algorithm. This technique lets you analyze content far beyond your context window by treating it as external data you inspect programmatically, never loading it directly.

**CRITICAL RULES:**
1. NEVER use the Read tool to read target files directly -- all content access goes through `uv run rlm`
2. NEVER call `rlm extract` in a Bash tool and read the output yourself. Extracted content must ONLY appear inside Task subagent prompts, never in your main context.
3. The ONLY `rlm` outputs you should read are: `scan` (metadata), `chunk` (manifest), `recommend` (strategies), `init`/`status`/`result --all` (session info). Everything else goes to subagents.
4. You are the orchestrator. You see metadata and summaries. Subagents see actual content. If you find yourself reading source code lines in a Bash output, you are doing it wrong.

## CLI Quick Reference

Use these EXACT syntaxes. Do not guess flags.

```bash
# Scan -- metadata only
uv run rlm scan <path>
uv run rlm scan <path> --depth 5

# Recommend chunking strategy
uv run rlm recommend <path>

# Chunk -- produces manifest, not content
uv run rlm chunk <path> --strategy <strategy> --session <session_id>
#   strategies: lines, files_directory, files_language, files_balanced, functions, headings, semantic
#   optional: --chunk-size 500 --overlap 50 (lines), --heading-level 2 (headings), --target-size 50000 (semantic)

# Extract -- targeted content retrieval (FOR SUBAGENT USE ONLY)
uv run rlm extract <filepath> --lines <START>:<END>
uv run rlm extract <filepath> --chunk-id <ID> --manifest <manifest_path>
uv run rlm extract <filepath> --grep "<pattern>" --context 5

# Session management
uv run rlm init "<query>" "<path>"
uv run rlm status <session_id>
uv run rlm result <session_id> --key <key> --value "<value>"
uv run rlm result <session_id> --all
uv run rlm finalize <session_id> --answer "<text>"
```

**All commands must be prefixed with:** `cd /Users/marknutter/Kode/recursive-ai &&`

## Step 0: Parse Arguments and Route

The user invoked `/rlm <args>`. Parse the arguments to determine the mode:

```
<user_args>
{{ARGS}}
</user_args>
```

**Mode detection:**
- `remember "content"` or `remember --file path` → **Store mode** (jump to [Memory: Store](#memory-store))
- `"query"` with NO path → **Recall mode** (jump to [Memory: Recall](#memory-recall))
- `"query" path/to/content` → **Analysis mode** (continue to Step 1 below)

### Analysis mode: Initialize

Parse the quoted query and the path from the args. Then initialize:

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm init "<query>" "<target_path>"
```

Save the session_id from the output. You'll use it throughout.

## Step 1: Scan -- Get Metadata Only

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm scan "<target_path>"
```

Read the metadata output carefully. Note:
- Total size (files, lines, bytes)
- Language breakdown
- Directory structure
- File listing with structure outlines

**Decision point:** If the target is a single small file (<200 lines), you may skip chunking and dispatch a single subagent that extracts and analyzes the whole file. For anything larger, proceed to Step 2.

## Step 2: Choose Chunking Strategy

First check recommendations:
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm recommend "<target_path>"
```

**Strategy selection heuristics:**
- **Directory of source code** -> `files_directory` or `files_language` for broad analysis, then drill into specific files with `functions`
- **Single large source file** -> `functions` if it has structure, `semantic` otherwise
- **Markdown/docs** -> `headings`
- **Large file, no structure** -> `lines` or `semantic`
- **Need balanced workload** -> `files_balanced`

Think about what the query needs. Security analysis needs function-level detail. Summarization can work with file-level grouping. Search queries need grep first.

Then chunk:
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm chunk "<target_path>" --strategy <chosen_strategy> --session <session_id>
```

## Step 3: Dispatch to Subagents

For each chunk (or batch of related chunks), spawn a Task subagent. Use `general-purpose` type with `haiku` model for speed.

**IMPORTANT: You do NOT extract content yourself.** Each subagent extracts its own content using Bash. You just tell the subagent which extract command to run. This keeps raw content out of your context entirely.

**Spawn subagents in PARALLEL** -- use multiple Task tool calls in a single message for independent chunks.

### Pattern A: Line-range chunks (functions, lines, semantic, headings)

These chunks have `source_file`, `start_line`, and `end_line`. Each subagent extracts its own content:

```
Example Task subagent prompt (general-purpose, haiku model):

Analyze code for the following query: <query>

First, extract the content by running this command:
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm extract <source_file> --lines <start_line>:<end_line>
```

This is from file: <source_file> (lines <start_line>-<end_line>)
Context: <what this chunk is -- e.g., "authentication module", function name, etc.>

After reading the extracted content, return your findings as a structured list:
- Finding: <description>
- Location: <file:line>
- Severity/Relevance: <high/medium/low>
- Details: <explanation>

If nothing relevant is found, say "No findings for this chunk."
```

### Pattern B: File-group chunks (files_directory, files_language, files_balanced)

These chunks have a `files` list instead of line ranges. Each file in the group needs to be extracted separately. Build a single subagent prompt that tells the subagent to extract all files in the group:

```
Example Task subagent prompt (general-purpose, haiku model):

Analyze code for the following query: <query>

This chunk covers the "<group_name>" group with <file_count> files.
Extract and analyze each file by running these commands:

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm extract <file_1> --lines 1:<lines_1>
```
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm extract <file_2> --lines 1:<lines_2>
```
(repeat for each file in the group)

After reading all extracted content, return your findings as a structured list:
- Finding: <description>
- Location: <file:line>
- Severity/Relevance: <high/medium/low>
- Details: <explanation>

If nothing relevant is found, say "No findings for this chunk."
```

For file-group chunks, you'll need the line counts from the scan metadata to know the end line for each file. Use the file listing from Step 1.

### After subagents return

Store each subagent's results (do NOT read the raw findings in detail -- just store them):
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm result <session_id> --key "chunk_<chunk_id>" --value "<subagent_findings>"
```

**Dispatch rules:**
- Spawn up to 4-6 subagents in parallel per batch
- If there are more chunks than can fit in one batch, process in waves

## Step 4: Evaluate Results

After each wave of subagents completes, evaluate:

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm result <session_id> --all
```

**Decision heuristics:**

1. **Sufficient coverage?** Have all chunks been analyzed? If not, dispatch remaining.

2. **Need finer granularity?** If subagents found interesting areas but need more detail:
   - Re-chunk specific files with `functions` or smaller `lines` chunk size
   - Extract specific line ranges for closer inspection
   - Dispatch new subagents on the finer chunks

3. **Need broader context?** If findings reference other files not yet analyzed:
   - Scan and chunk the referenced files
   - Dispatch subagents on the new chunks

4. **Enough to answer?** If results address the query comprehensively, proceed to Step 5.

5. **Iteration limit:** Track iterations. After 12 iterations, start synthesizing with what you have. Hard stop at 15.

**For each decision, log it:**
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm result <session_id> --key "iteration_<N>_decision" --value "<what you decided and why>"
```

## Step 5: Synthesize Final Answer

When you have enough information (or hit the iteration limit):

1. Review the accumulated results summary
2. Synthesize a comprehensive answer to the original query
3. Structure the answer with:
   - Executive summary
   - Detailed findings (grouped logically)
   - Specific locations/references (file:line)
   - Recommendations (if applicable)

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm finalize <session_id>
```

Present the final answer directly to the user.

## Quick-Path Optimizations

- **Grep-first for search queries:** If the query is looking for something specific, have a subagent run `uv run rlm extract <path> --grep "<pattern>"` before chunking to find relevant areas fast.
- **Small targets:** Files under 200 lines can be dispatched to a single subagent without chunking.
- **Targeted drill-down:** If scan metadata shows only 2-3 relevant files, chunk only those files, not the whole directory.

## Analysis: Pre/Post Memory Integration

### Pre-Analysis: Check Memory

Before starting a new analysis (after Step 0, before Step 1), check if you have prior knowledge about this target:

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm recall "<keywords from query and target path>" --deep
```

If relevant memories exist, dispatch a subagent to extract and summarize them. Use prior findings to focus on areas not previously analyzed or check if previously found issues persist.

### Post-Analysis: Store Findings

After Step 5 (synthesize), store key findings as a memory:

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm remember "<synthesized findings summary>" --tags "<target,query-type,key-topics>" --summary "<what was analyzed and key results>"
```

Always provide explicit `--tags` and `--summary`. Include target identifier, analysis type, and key topics.

---

## <a id="memory-recall"></a>Memory: Recall

Recall mode searches the persistent memory store at `~/.rlm/memory/` and uses subagent evaluation to synthesize answers from matching entries.

### Memory CLI Reference

```bash
# Search (deep scans content, not just summaries)
uv run rlm recall "query" --deep [--tags tag1,tag2] [--max 20]

# Pre-filter: grep within a memory entry (BEFORE dispatching subagent)
uv run rlm memory-extract <entry_id> --grep "pattern" [--context 3]

# Extract full content (FOR SUBAGENT USE ONLY)
uv run rlm memory-extract <entry_id> [--chunk-id <chunk_id>]

# Browse
uv run rlm memory-list [--tags tag1,tag2] [--offset 0] [--limit 50]
uv run rlm memory-tags

# Strategy and performance
uv run rlm strategy show          # Load learned retrieval patterns
uv run rlm strategy log           # Review past performance
uv run rlm strategy perf --query "..." --entries-found N --entries-relevant N --subagents N --notes "..."

# Delete a memory
uv run rlm forget <entry_id>
```

### Recall Step 0: Load Learned Patterns

Before starting, check for accumulated retrieval strategies from previous sessions:

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm strategy show
```

If patterns exist, incorporate them into your approach. These are heuristics discovered through past recall operations — they should influence your search terms, dispatch strategy, and evaluation focus.

### Recall Step 1: Search

Run a deep search. **Always use `--deep`** — it scans entry content, not just summaries/tags:

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm recall "search query" --deep
```

**Adaptive search strategy:** Consider whether the query might use different vocabulary in the stored content. If so, run multiple searches with variant terms. For example:
- "Iraq war" → also try "Iraq Bush invasion WMD"
- "authentication" → also try "auth login password"
- A person's name → also try their known nicknames

**Decision point:**
- **0 results**: Try broader/different keywords, or browse with `memory-list`/`memory-tags`
- **1-5 results**: Proceed to grep pre-filtering
- **6+ results**: Start with the top 5-8, expand only if synthesis is incomplete

### Recall Step 2: Grep Pre-Filtering

**BEFORE dispatching subagents, use grep to confirm which entries contain relevant content.** This eliminates false positives and drastically reduces wasted subagent dispatches.

For each search result, run:
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm memory-extract <entry_id> --grep "keyword" --context 3
```

**What grep tells you:**
- **"No matches"** → Skip this entry. Deep search scored it but the keyword appears in metadata, not meaningful content.
- **1-3 matches** → Small, focused hit. The grep output itself may contain enough context — consider skipping the subagent.
- **Many matches** → Rich entry. Dispatch a subagent for full evaluation.

**Optimization:** Run multiple grep calls in parallel since they're independent.

### Recall Step 3: Handle Large Memories with RLM Chunking

**When a memory is large (>10KB), use RLM chunking instead of direct extraction.**

The `recall` command annotates results with size categories:
- `small` (<2KB): Direct extraction fine
- `medium` (2-10KB): Grep pre-filtering recommended
- `large` (10-50KB): **Use RLM chunking**
- `huge` (>50KB): **Definitely use RLM chunking**

**For large/huge memories, treat them as analysis targets:**

1. Get the entry ID from search results
2. Get the full content: `uv run rlm memory-extract <entry_id>`
3. Write content to a temporary file
4. Use RLM analysis mode on that file:
   - Init session: `uv run rlm init "<query>" "<temp_file>"`
   - Scan: Shows size, structure
   - Chunk: Use `semantic` strategy for conversation transcripts
   - Extract + analyze chunks with subagents
   - Synthesize findings

**This prevents context bloat** - you never load the full 50KB conversation into context, only the relevant extracted chunks.

**Example workflow for a large conversation memory:**
```bash
# Search finds a large conversation
uv run rlm recall "Iraq war" --deep
# Output shows: m_abc123: 45,000 chars (large)

# Extract to temp file
uv run rlm memory-extract m_abc123 > /tmp/conversation.txt

# Use RLM analysis
uv run rlm init "opinions about Iraq war" /tmp/conversation.txt
# ... then scan, chunk (semantic), dispatch subagents per usual RLM workflow
```

### Recall Step 4: Dispatch Subagents for Small Memories (Graduated)

For small/medium memories that passed grep pre-filtering, dispatch subagents normally.

**Graduated dispatch — start small, expand if needed:**

1. **First wave (top 4-5 entries):** Dispatch subagents for the highest-scoring small/medium entries that had grep hits
2. **Evaluate first wave results.** If the query is well-answered, stop. If gaps remain, dispatch more.
3. **Second wave (if needed):** Process the next batch

**Subagent prompt template:**

```
Retrieve and evaluate this memory entry for relevance to the query: "<user's query>"

Pre-filter grep showed these relevant sections:
<paste grep output here>

Extract the full content for deeper context:
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm memory-extract <entry_id>
```

If the entry is large (>10K chars), focus your reading on the sections identified by grep.
If the entry has chunks, extract specific chunks:
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm memory-extract <entry_id> --chunk-id <chunk_id>
```

Return:
1. **Relevant?** yes/no
2. **Key information:** Specific facts, findings, or knowledge relevant to the query (include attributed quotes where available)
3. **Summary:** 2-3 sentence summary of what this memory contains
```

**Dispatch rules:**
- Up to 4 subagents in parallel per wave
- Use `haiku` model for speed
- Include the grep pre-filter output in the prompt so subagents know where to focus
- For entries where grep returned sufficient context (1-3 matches with clear answers), skip the subagent and use the grep output directly

### Recall Step 5: Synthesize

After subagents return (or after RLM analysis of large memories):

1. Filter out irrelevant entries
2. Combine key information from relevant entries
3. Present to the user:
   - What was found (with attributed quotes where available)
   - Where it came from (memory entry IDs)
   - Any gaps (if the query isn't fully answered)
4. If the first wave was insufficient, dispatch a second wave before giving up

### Recall Step 5: Log Performance and Learn

**After every recall session**, log what happened and assess whether you discovered a reusable pattern.

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm strategy perf \
  --query "the user's original query" \
  --search-terms "term1,term2,term3" \
  --entries-found <total from search> \
  --entries-relevant <entries confirmed relevant> \
  --subagents <total dispatched> \
  --notes "Brief note on what worked or didn't"
```

**Assess and learn:** Consider:
- Did your search terms miss relevant content? Note which vocabulary variants worked.
- Were many subagents wasted? Note what grep patterns would have filtered them out.
- Did you discover a cross-referencing pattern? (e.g., "check adjacent time periods")

If you discovered a reusable pattern, **write it to the learned patterns file** using the Edit or Write tool:

```
~/.rlm/strategies/learned_patterns.md
```

Format:
```markdown
### <Short pattern name>
**Discovered:** <date>
**Context:** <what revealed this>
**Pattern:** <the reusable heuristic, stated as an instruction>
```

### Recall Quick-Paths

- **Small result set (1-3 entries, all <5K chars):** Skip subagents. Grep + direct reading is faster.
- **Exact match:** If one result scores much higher than others, extract only that one.
- **Tag browsing:** For "what do I know about X?" queries, browse by tag first (`memory-list --tags X`).

---

## <a id="memory-store"></a>Memory: Store

Store mode saves content to persistent memory.

Parse the arguments for:
- **content**: Text to store (in quotes), OR
- **--file path**: File to store
- **--tags tag1,tag2**: Comma-separated tags (always provide)
- **--summary "..."**: Short description (always provide)

```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm remember "content" --tags "tag1,tag2" --summary "short description"
cd /Users/marknutter/Kode/recursive-ai && uv run rlm remember --file /path/to/file --tags "tag1,tag2" --summary "short description"
```

If the user provides content without explicit tags/summary, generate good ones:
- **Tags**: 3-6 lowercase keywords covering topic, source type, and key entities
- **Summary**: Under 80 chars, captures what this knowledge is about

Confirm what was stored (ID, summary, tags, size).

---

## Error Handling

- If a subagent returns an error, retry once with a simpler prompt
- If CLI commands fail, check the path exists and session is valid
- If no findings emerge after 2 full iterations, try a different chunking strategy
- If the memory store is empty, tell the user and suggest storing knowledge first
- Always degrade gracefully — partial results are better than no results
