---
name: rlm
description: Recursively analyze content beyond context limits using sub-LLM delegation (based on the RLM paper)
argument-hint: "query" path/to/content
user_invocable: true
---

# RLM: Recursive Language Model Analysis

You are executing the RLM (Recursive Language Model) algorithm. This technique lets you analyze content far beyond your context window by treating it as external data you inspect programmatically, never loading it directly.

**CRITICAL RULES:**
1. NEVER use the Read tool to read target files directly -- all content access goes through `uv run rlm extract`
2. NEVER load full file contents into your context -- only metadata, chunk manifests, and targeted extracts
3. All analysis of chunk content happens in Task subagents, not in your main context
4. You are the orchestrator. You see metadata and summaries. Subagents see actual content.

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

**Decision point:** If the target is a single small file (<200 lines), you may use `uv run rlm extract <path> --lines 1:200` to read it directly and answer without chunking. For anything larger, proceed to Step 2.

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

**IMPORTANT:** Each subagent prompt must include:
1. The original query
2. Context about what this chunk represents (file path, line range, role in project)
3. The actual chunk content (extracted via the prompt itself or included inline)
4. Instructions to return a structured finding

**Pattern for subagent dispatch:**

First, extract the chunk content:
```bash
cd /Users/marknutter/Kode/recursive-ai && uv run rlm extract <source_file> --lines <start>:<end>
```

Then spawn a Task subagent with the content included in the prompt. For file-group chunks, extract each file's content.

**Spawn subagents in PARALLEL** -- use multiple Task tool calls in a single message for independent chunks.

Example subagent prompt:
```
Analyze the following code for: <query>

File: <source_file> (lines <start>-<end>)
Context: <what this chunk is -- e.g., "authentication module", "API routes", etc.>

<extracted content>

Return your findings as a structured list:
- Finding: <description>
- Location: <file:line>
- Severity/Relevance: <high/medium/low>
- Details: <explanation>

If nothing relevant is found, say "No findings for this chunk."
```

**Dispatch rules:**
- Spawn up to 4-6 subagents in parallel per batch
- If there are more chunks than can fit in one batch, process in waves
- Store each subagent's results: `uv run rlm result <session_id> --key "chunk_<id>" --value "<findings>"`

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

- **Grep-first for search queries:** If the query is looking for something specific (a pattern, a vulnerability type, a keyword), use `uv run rlm extract <path> --grep "<pattern>"` before chunking to find relevant areas fast.
- **Small targets:** Files under 200 lines can be extracted and analyzed directly without subagents.
- **Targeted drill-down:** If scan metadata shows only 2-3 relevant files, chunk only those files, not the whole directory.

## Error Handling

- If a subagent returns an error, retry once with a simpler prompt
- If CLI commands fail, check the path exists and session is valid
- If no findings emerge after 2 full iterations, try a different chunking strategy
- Always degrade gracefully -- partial results are better than no results
