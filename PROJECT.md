# Project TODOs

## Skill Prompt Improvements

- [ ] **Enforce subagent-only content access.** Tighten SKILL.md to make it explicit that extracted content must go *into subagent prompts*, never into the main orchestrator context. The current wording says this but Claude still loads extracts into its own context. Needs stronger guardrails -- e.g., "Do NOT call `rlm extract` and read the output yourself. Instead, construct the extract command and embed its output directly in the Task subagent prompt."

- [ ] **Add exact CLI usage examples to the skill prompt.** Claude guessed wrong flags (`--chunk` instead of `--chunk-id`, `--session` on extract). Add a quick-reference block in SKILL.md showing the exact syntax for each command, especially extract variants: `--lines START:END`, `--chunk-id ID --manifest PATH`, `--grep PATTERN`.

- [ ] **Add file-group chunk dispatch pattern.** When using `files_directory`/`files_language`/`files_balanced`, the chunks contain file lists rather than line ranges. The skill prompt needs an explicit pattern for this: iterate the file list in each chunk, extract each file's content, and include all of them in a single subagent prompt per chunk group.
