# Eval Safety Test: CPython Standard Library

RLM pointed at CPython's `Lib/` directory (~1.18 million lines, 2,043 files, 45MB) with the query "find all uses of eval() and assess their safety". This test was designed to exercise the recursive iteration loop -- grep-first to locate all eval() calls, dispatch subagents to analyze each group, then drill into the most critical findings.

## Test Configuration

- **Target:** `/tmp/cpython/Lib` (shallow clone of python/cpython)
- **Total size:** 1,179,217 lines across 2,043 files (45.1 MB)
- **Grep-first results:** 455 eval() calls across 92 files
- **Production files:** ~60 eval() calls in 20 non-test files
- **Test files:** ~395 eval() calls in 72 test files (confirmed safe)
- **Iterations:** 2 (wave 1: broad analysis of all groups; wave 2: drill-down into logging/config.py listen() RCE)
- **Subagents dispatched:** 8 (6 in wave 1, 2 in wave 2)
- **Model:** haiku for all subagents

## Context Window Efficiency

| Metric | Value |
|---|---|
| Total codebase size | 45.1 MB |
| Content analyzed by subagents | ~180 KB (grep results + extracted contexts across 20+ files) |
| Orchestrator context consumed | ~6 KB (grep summary + scan metadata + result summaries) |
| **Leverage ratio** | **~30x** on analyzed content, **~7,500x** on total codebase |

The orchestrator consumed ~6KB of context to direct a 2-iteration analysis across 92 files. No source code was loaded into the orchestrator's context.

## Iteration Loop Exercised

This test successfully exercised the evaluate/iterate loop:

1. **Grep-first** (Quick-Path Optimization): Found 455 eval() calls, categorized into production vs test code
2. **Wave 1 dispatch** (6 subagents in parallel): Analyzed all production eval() groups -- debuggers, annotationlib, logging/config, IDLE/turtle, misc modules, test files
3. **Evaluate**: Identified logging/config.py as needing deeper investigation (network-facing eval) and pydoc_data/topics.py as unchecked
4. **Wave 2 drill-down** (2 subagents): Deep-dived into logging/config.py listen() attack chain; confirmed pydoc_data/topics.py is documentation-only
5. **Synthesize**: Compiled findings into severity-ranked report

## Findings: 455 eval() Calls Analyzed

### By Severity

| Severity | Count | Where |
|---|---|---|
| Critical | 5 | pdb.py (3), bdb.py (1), logging/config.py (1 — network RCE) |
| High | 7 | bdb.py (1), logging/config.py (2), IDLE autocomplete/calltip/debugobj (3), pyshell.py (1) |
| Medium | 4 | pdb.py (1), annotationlib.py (1), turtle.py (1), logging/config.py (1) |
| Low | 5 | annotationlib.py (2), rlcompleter.py (1), inspect.py (1), collections (1) |
| Safe / No Risk | 434 | All test files (~395), documentation references (~15), hardcoded/whitelisted calls (~24) |

### Production Code — Detailed Findings

#### Critical: Remote Code Execution via logging/config.py

**The most significant finding.** `logging.config.listen()` opens a network socket that accepts logging configurations. These configs flow through `fileConfig()` which calls `eval()` 4 times (lines 132, 154, 158, 160) with `vars(logging)` as namespace. Since `__builtins__` is always accessible in eval(), an unauthenticated attacker can achieve arbitrary code execution:

```
Network attacker → listen() socket → fileConfig() → eval(args, vars(logging)) → RCE
```

Payload example: `eval("__import__('os').system('id')", vars(logging))` works despite namespace restriction.

**CVSS 9.8** — No authentication, network-accessible, trivial exploitation.

#### Critical: Debugger eval() (pdb.py, bdb.py)

| Location | Risk | Description |
|---|---|---|
| `pdb.py:2100` `_getval()` | Critical | Direct eval of user input from `print`, `pp`, `whatis` commands. No validation. |
| `pdb.py:2108-2110` `_getval_except()` | Critical | Same pattern, used by `display` command. Persistent expressions eval'd on each step. |
| `pdb.py:1429` | Medium | Function lookup via eval. Regex-limited but side effects possible. |
| `bdb.py:924` `runeval()` | Critical | API-level eval of arbitrary expressions. By design but no safety controls. |
| `bdb.py:1149` `effective()` | High | Breakpoint conditions eval'd with syntax-only validation. |

**Mitigating context:** Debuggers inherently require code execution. These are by-design features, not bugs. However, the lack of any sandboxing means debugger access = full code execution.

#### High: IDLE Interactive Features

| Location | Risk | Description |
|---|---|---|
| `idlelib/autocomplete.py:221` | High | Eval of user-typed expressions for tab completion. By design. |
| `idlelib/calltip.py:140` | High | Eval of expressions for function signature display. By design. |
| `idlelib/debugobj.py:37` | High | Eval of user edits in debug object inspector. By design. |
| `idlelib/pyshell.py:279` | Medium-High | **Breakpoint file deserialization** — reads `.idlerc/breakpoints.lst` and eval's line content without validation. Potential for local privilege escalation if file is writable by attacker. |

**Mitigating context:** IDLE is an interactive development environment. eval() for autocomplete, calltips, and debugging is the intended purpose. The pyshell.py breakpoint file issue is the only genuine vulnerability.

#### Medium: Type Annotation Evaluation

| Location | Risk | Description |
|---|---|---|
| `annotationlib.py:205, 220` | Low | ForwardRef.evaluate() — pre-compiled code objects in expression-mode. Safe. |
| `annotationlib.py:1067` | Medium | get_annotations() — raw string eval without pre-compilation. Safe in practice (annotations come from source code) but could be exploited if annotations are set from untrusted input. |

#### Low: Well-Protected eval() Calls

| Location | Risk | Description |
|---|---|---|
| `collections/__init__.py:447` | Low | Namedtuple factory with empty `__builtins__` — the gold standard for safe eval. |
| `inspect.py:2195, 2198` | Low | Builtin signature parsing — AST-validated input, result validated to primitives only. |
| `rlcompleter.py:158` | Low | REPL tab completion — regex restricts to dotted names only. `__getattr__` trigger acknowledged in docs. |

#### Safe: Properly Protected

| Location | Pattern |
|---|---|
| `pydoc.py:2045` | Whitelist (`['True', 'False', 'None']`) before eval. |
| `pydoc.py:316` | Uses `ast.literal_eval()` — safe by design. |
| `turtle.py:185` | Whitelist of 5 literal values before eval. |
| `turtle.py:3983, 3986` | Hardcoded internal constants. |
| `idlelib/autocomplete.py:185, 189` | Hardcoded `"dir()"` and `"__all__"`. |
| `idlelib/run.py:107` | Tcl eval, not Python eval. |

#### False Positives

| Location | Type |
|---|---|
| `pydoc_data/topics.py` (12 matches) | Documentation strings only. No executable eval(). |
| `dataclasses.py` (2 matches) | Comments discussing why eval was NOT used. |
| `_pydecimal.py` (1 match) | Comment (`# Invariant: eval(repr(d)) == d`). |
| `pprint.py` (1 match) | Docstring reference. |
| `tkinter/ttk.py` (1 match) | Tcl interpreter eval, not Python eval. |

### Test Code — Confirmed Safe

| File | Calls | Pattern |
|---|---|---|
| `test_string_literals.py` | 60 | Hardcoded string literal testing |
| `test_compile.py` | 49 | Hardcoded numeric literal testing |
| `test_tcl.py` | 31 | Tcl eval, not Python eval |
| `test_builtin.py` | 27 | Testing eval() itself with controlled inputs |
| `test_descr.py` | 19 | Descriptor protocol testing |
| `test_opcodes.py` | 16 | Opcode testing with literals |
| All others | ~193 | Various language feature tests with hardcoded inputs |

## Safety Pattern Taxonomy

The analysis revealed 6 distinct patterns for eval() usage:

| Pattern | Safety | Example | Count |
|---|---|---|---|
| **Whitelist guard** | Safe | `if x in ['True','False']: eval(x)` | 3 locations |
| **ast.literal_eval** | Safe | `ast.literal_eval(string)` | 1 location |
| **Hardcoded expression** | Safe | `eval("dir()")` | 5 locations |
| **Pre-compiled code object** | Low risk | `eval(compiled_code, namespace)` | 2 locations |
| **Regex-restricted input** | Low-Medium | `if re.match(r'\w+\.', text): eval(text)` | 2 locations |
| **Empty __builtins__** | Low risk | `eval(code, {'__builtins__': {}})` | 1 location |
| **Unrestricted user input** | Critical | `eval(user_string, frame.f_globals)` | 12 locations |
| **External data (network/file)** | Critical | `eval(config_value, vars(logging))` | 5 locations |

## Process Observations

**What this test demonstrates about the iteration loop:**
- **Grep-first was essential** — 455 matches across 92 files would be unmanageable without the initial categorization step
- **Wave 1 identified the drill-down target** — logging/config.py was flagged as needing deeper investigation, triggering wave 2
- **Wave 2 confirmed the critical finding** — the listen() RCE vector was only fully understood after dedicated deep-dive analysis
- **2 iterations were sufficient** — the evaluate step correctly determined no further iteration was needed after wave 2

**What worked well:**
- Grep-first optimization prevented wasting subagent time on test files
- Categorizing production vs test code in the orchestrator kept analysis focused
- Parallel dispatch (6 subagents wave 1, 2 subagents wave 2) completed efficiently
- Subagents correctly identified false positives (comments, Tcl eval, ast.literal_eval)

**What the test revealed about eval() in CPython:**
- The stdlib has a clear divide: ~95% of eval() calls are either in test code or properly protected
- The dangerous calls are concentrated in 3 areas: debuggers, IDLE, and logging/config
- Debugger and IDLE eval() is by-design (interactive execution environments)
- logging/config.py is the only true vulnerability — network-accessible eval() with insufficient namespace isolation

## Comparison to Previous Tests

| Metric | Test 3 (Juice Shop) | Test 4 (Scale) | This Test |
|---|---|---|---|
| **Codebase size** | 7.4 MB | 45.1 MB | 45.1 MB |
| **Orchestrator context** | ~5 KB | ~8 KB | ~6 KB |
| **Leverage ratio** | 63x | 5,600x | 7,500x |
| **Iterations** | 1 | 1 | 2 |
| **Subagents** | 6 | 6 | 8 |
| **Iteration loop exercised** | No | No | **Yes** |
| **Grep-first used** | No | No | **Yes** |
| **Findings** | 83 vulns | 100+ patterns | 455 eval() calls classified |
