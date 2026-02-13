# RLM: Recursive Language Model Analysis (Codex Edition)

You are executing the RLM (Recursive Language Model) algorithm using OpenAI Codex. This technique lets you analyze content far beyond your context window by treating it as external data you inspect programmatically, never loading it directly.

## Prerequisites

Set the following environment variables before running:

```bash
export RLM_PROVIDER=openai
export OPENAI_API_KEY=<your-key>
# Optional: override the default model
# export RLM_MODEL=gpt-4o-mini
```

## Critical Rules

1. NEVER read target files directly -- all content access goes through `uv run rlm`
2. The `rlm analyze` command sends chunks to the OpenAI API for analysis. Use it instead of reading extracted content yourself.
3. The ONLY `rlm` outputs you should read are: `scan` (metadata), `chunk` (manifest), `recommend` (strategies), `init`/`status`/`result --all` (session info). Everything else goes through `analyze`.
4. You are the orchestrator. You see metadata and summaries. The API-dispatched sub-LLM sees actual content.

## CLI Quick Reference

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

# Analyze -- dispatches chunk to OpenAI API for analysis (PREFERRED METHOD)
uv run rlm analyze <session_id> --file <filepath> --lines <START>:<END>
uv run rlm analyze <session_id> --chunk-id <ID> --manifest <manifest_path>

# Extract -- targeted content retrieval (only if you need raw content for custom analysis)
uv run rlm extract <filepath> --lines <START>:<END>
uv run rlm extract <filepath> --chunk-id <ID> --manifest <manifest_path>
uv run rlm extract <filepath> --grep "<pattern>" --context 5

# Session management
uv run rlm init "<query>" "<path>"
uv run rlm status <session_id>
uv run rlm result <session_id> --key <key> --value "<value>"
uv run rlm result <session_id> --all
uv run rlm finalize <session_id> --answer "<text>"

# Check provider configuration
uv run rlm providers
```

## Step 0: Parse Arguments and Initialize

The user wants to run RLM analysis. Parse their request to extract:
- **query**: The analysis question
- **target_path**: The file or directory to analyze

Initialize the session:

```bash
uv run rlm init "<query>" "<target_path>"
```

Save the session_id from the output. You'll use it throughout.

## Step 1: Scan -- Get Metadata Only

```bash
uv run rlm scan "<target_path>"
```

Read the metadata output carefully. Note:
- Total size (files, lines, bytes)
- Language breakdown
- Directory structure
- File listing with structure outlines

**Decision point:** If the target is a single small file (<200 lines), you may analyze it in one shot. For anything larger, proceed to Step 2.

## Step 2: Choose Chunking Strategy

First check recommendations:
```bash
uv run rlm recommend "<target_path>"
```

**Strategy selection heuristics:**
- **Directory of source code** -> `files_directory` or `files_language` for broad analysis, then drill into specific files with `functions`
- **Single large source file** -> `functions` if it has structure, `semantic` otherwise
- **Markdown/docs** -> `headings`
- **Large file, no structure** -> `lines` or `semantic`
- **Need balanced workload** -> `files_balanced`

Then chunk:
```bash
uv run rlm chunk "<target_path>" --strategy <chosen_strategy> --session <session_id>
```

## Step 3: Dispatch Analysis

For each chunk, use `rlm analyze` to send it to the OpenAI API for analysis. The analyze command extracts the content, sends it to the configured model, and stores the result automatically.

### For line-range chunks (functions, lines, semantic, headings):

```bash
uv run rlm analyze <session_id> --file <source_file> --lines <start_line>:<end_line>
```

### For manifest-based chunks:

```bash
uv run rlm analyze <session_id> --chunk-id <chunk_id> --manifest <manifest_path>
```

### For file-group chunks (files_directory, files_language, files_balanced):

These chunks contain multiple files. Run analyze for each file in the group:

```bash
uv run rlm analyze <session_id> --file <file_1> --lines 1:<total_lines_1>
uv run rlm analyze <session_id> --file <file_2> --lines 1:<total_lines_2>
```

**Dispatch rules:**
- Run analyses sequentially (each is an API call)
- Review findings between batches to guide further analysis

## Step 4: Evaluate Results

After each batch of analyses completes, evaluate:

```bash
uv run rlm result <session_id> --all
```

**Decision heuristics:**

1. **Sufficient coverage?** Have all chunks been analyzed? If not, dispatch remaining.
2. **Need finer granularity?** If analyses found interesting areas but need more detail:
   - Re-chunk specific files with `functions` or smaller `lines` chunk size
   - Dispatch new analyses on the finer chunks
3. **Need broader context?** If findings reference other files not yet analyzed:
   - Scan and chunk the referenced files
   - Dispatch analyses on the new chunks
4. **Enough to answer?** If results address the query comprehensively, proceed to Step 5.
5. **Iteration limit:** Track iterations. After 12 iterations, start synthesizing with what you have. Hard stop at 15.

**For each decision, log it:**
```bash
uv run rlm result <session_id> --key "iteration_<N>_decision" --value "<what you decided and why>"
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
uv run rlm finalize <session_id>
```

Present the final answer directly to the user.

## Quick-Path Optimizations

- **Grep-first for search queries:** If the query is looking for something specific, use `uv run rlm extract <path> --grep "<pattern>"` to find relevant areas first, then analyze those specific regions.
- **Small targets:** Files under 200 lines can be dispatched to a single analyze call.
- **Targeted drill-down:** If scan metadata shows only 2-3 relevant files, chunk and analyze only those files.

## Error Handling

- If an analyze call returns an error, check OPENAI_API_KEY is set and valid
- If CLI commands fail, check the path exists and session is valid
- If no findings emerge after 2 full iterations, try a different chunking strategy
- Always degrade gracefully -- partial results are better than no results
