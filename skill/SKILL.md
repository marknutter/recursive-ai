---
name: rlm
description: Recursively analyze content beyond context limits using sub-LLM delegation (based on the RLM paper)
argument-hint: "query" path/to/content
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

## Step 0: Parse Arguments and Initialize

The user invoked `/rlm <args>`. Parse the arguments to extract:
- **query**: The analysis question (in quotes)
- **target_path**: The file or directory to analyze

```
<user_args>
{{ARGS}}
</user_args>
```

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

## Error Handling

- If a subagent returns an error, retry once with a simpler prompt
- If CLI commands fail, check the path exists and session is valid
- If no findings emerge after 2 full iterations, try a different chunking strategy
- Always degrade gracefully -- partial results are better than no results
