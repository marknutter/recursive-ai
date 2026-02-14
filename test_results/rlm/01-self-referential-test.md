# Self-Referential Architecture Summary Test

RLM pointed at its own codebase (~77KB, 13 files, 2,200 lines) with the query "summarize the architecture and explain how each module works". Two runs: before and after fixing the skill prompt.

## Context Window Efficiency

| | Test 1 (old prompt) | Test 2 (fixed prompt) |
|---|---|---|
| Raw source in orchestrator context | ~20KB | **0 bytes** |
| Metadata in orchestrator context | ~1.5KB | ~1.5KB |
| Subagent result summaries in context | ~2KB | ~2KB |
| **Total orchestrator context used** | **~23.5KB** | **~3.5KB** |
| **Content actually analyzed** | ~77KB | ~77KB |
| **Leverage ratio** | ~3x | **~22x** |

## What Broke in Test 1

- Claude tried wrong CLI flags (`--chunk` instead of `--chunk-id`, `--session` on extract)
- Loaded all 5 module extracts into its own context (~20KB of source code)
- Skipped the evaluate/iterate loop
- Bypassed chunk manifest entirely, extracted by filename + line ranges

## What Improved in Test 2

- Zero raw source entered the orchestrator's context
- Subagents extracted their own content via Bash
- Correct CLI flags used throughout (CLI quick-reference in prompt helped)
- File-group chunks dispatched correctly (3 subagents for 3 meaningful directory groups)

## Why 22x and Not 100x

The codebase is small. Overhead (scan metadata, chunk manifest, subagent findings) has a fixed floor of ~2-3KB. On larger targets the ratio improves because:

- Scan metadata truncates at ~4KB regardless of project size
- Chunk manifests grow modestly (~2KB for 50 chunks)
- Subagent findings are bounded per-chunk
- Orchestrator context stays roughly constant

Expected leverage: ~70-80x at 770KB, ~100x at 7.7MB.

## Recursive Loop

Neither test exercised iteration -- both completed in a single pass (scan -> chunk -> dispatch -> synthesize). Expected: the loop would engage on larger targets where first-pass findings reveal areas needing finer-grained re-chunking.

## Skill Prompt Fixes That Made the Difference

1. **Subagent-only extraction** -- "NEVER call `rlm extract` in a Bash tool and read the output yourself"
2. **CLI quick-reference** -- exact flag syntax prevented guessing wrong flags
3. **Pattern A/B dispatch** -- explicit patterns for line-range vs file-group chunks
