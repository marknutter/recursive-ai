# Scale Test: CPython Standard Library

RLM pointed at CPython's `Lib/` directory (~1.18 million lines, 2,043 files, 45MB) with the query "what are the main architectural patterns used". This is the stress test for bounded-output and iteration limits.

## Test Configuration

- **Target:** `/tmp/cpython/Lib` (shallow clone of python/cpython)
- **Total size:** 1,179,217 lines across 2,043 files (45.1 MB)
- **Focused areas:** asyncio (14,922 lines), importlib (6,573 lines), http (5,621 lines), logging (5,089 lines), unittest (7,145 lines), concurrency modules (threading, multiprocessing, concurrent.futures, queue, selectors), I/O & serialization modules (_pyio, codecs, json, pickle, csv, configparser), flagship top-level modules (abc, contextlib, functools, dataclasses, typing, pathlib, collections)
- **Strategy:** `files_directory` for initial survey (201 chunks), then `files_balanced` on targeted packages
- **Subagents dispatched:** 6 (asyncio, importlib, flagship modules, http/logging/unittest, concurrency, I/O & serialization)
- **Model:** haiku for all subagents
- **Iterations:** 1 (single pass with strategic targeting)

## Context Window Efficiency

| Metric | Value |
|---|---|
| Total codebase size | 45.1 MB |
| Content analyzed by subagents | ~500 KB (across 6 domains, ~80 files extracted) |
| Orchestrator context consumed | ~8 KB (scan metadata + chunk manifests + result summaries) |
| **Leverage ratio** | **~62x** on analyzed content, **~5,600x** on total codebase |

The orchestrator consumed ~8KB of context to direct analysis that touched ~500KB of actual source code out of a 45MB codebase. No source code was loaded into the orchestrator's context.

Note: we analyzed ~1% of the total codebase, strategically selecting the most architecturally significant packages. Full coverage would require multiple iterations with broader chunking -- the recursive loop that this test was meant to exercise but didn't fully trigger.

## Bounded Output Verification

The primary goal of this test was to verify the bounded-output principle holds at scale:

| Check | Result |
|---|---|
| `rlm scan` on 2,043-file, 45MB directory | Truncated at 4000 chars with notice. Listed 33 of 2,043 files before cutoff. |
| `rlm chunk` producing 201 directory chunks | Truncated at 4000 chars. Showed first ~50 chunks before cutoff. |
| `rlm recommend` | Worked normally (short output). |
| Session state persistence | All 6 results stored and retrieved correctly. |
| Subagent dispatch | All 6 completed without context overflow. |

**The bounded-output principle held.** Even on a 45MB codebase, no CLI command produced unbounded output. The orchestrator's context stayed clean throughout.

## Patterns Found: 100+

### By Domain

| Domain | Patterns Found | Key Highlights |
|---|---|---|
| **asyncio** (14,922 lines) | 16 | Protocol/Transport separation, Future state machine (PENDING->CANCELLED->FINISHED), Task 3-state scheduler, backpressure flow control, 5-layer architecture, event loop policy as Strategy |
| **importlib** (6,573 lines) | 14 | Chain of Responsibility (finder sequence), Spec value object, 3-tier bootstrap fallback, cycle detection via DFS, multi-level cache invalidation, namespace package accumulation |
| **Flagship modules** (abc, contextlib, functools, dataclasses, typing, pathlib, collections) | 18+ | ABCMeta metaclass, @dataclass code generation, @contextmanager generator protocol, cached_property descriptor, ContextDecorator dual protocol, C/Python hybrid architecture |
| **http/logging/unittest** | 26 | HTTP state machine, logging filter pipeline (Chain of Responsibility), handler registry with weak refs, test lifecycle Template Method, mock spec validation framework |
| **Concurrency** (threading, multiprocessing, concurrent.futures, queue, selectors) | 15 | Mirrored Thread/Process APIs, Future state machine, Executor Template Method, Selector/Reactor, Condition Variable as fundamental building block, timeout everywhere |
| **I/O & Serialization** (io, codecs, json, pickle, csv, configparser) | 15 | 3-tier I/O ABC hierarchy (Raw->Buffered->Text), codec registry, stateful incremental processing, interpolation strategy, protocol versioning |

### Most Recurring Patterns Across the Stdlib

| Pattern | Occurrences | Where |
|---|---|---|
| **Abstract Base Class (ABC)** | Everywhere | asyncio, importlib, io, collections, typing |
| **Template Method** | 6+ packages | asyncio event loop, importlib loader, http handler, logging handler, unittest test case, executor |
| **Strategy** | 5+ packages | Event loop policy, loader types, codec handlers, error handler, interpolation |
| **Chain of Responsibility** | 3 packages | importlib finders, logging filters, http handler chain |
| **Observer/Callback** | 4 packages | asyncio Handle system, logging handlers, unittest result, Future callbacks |
| **State Machine** | 3 packages | asyncio Future/Task, http connection, concurrent.futures Future |
| **Factory** | 4 packages | create_task, spec_from_loader, LogRecord, TestResult |
| **Context Manager (RAII)** | Everywhere | locks, files, test fixtures, context decorators |
| **Mixin/Composition** | 5+ packages | asyncio _FlowControlMixin, ThreadingHTTPServer, ContextDecorator, _LoopBoundMixin |
| **Weak References** | 3 packages | logging registry, threading, importlib |

### Top Architectural Principles

1. **Protocol/Transport Separation** -- asyncio's most important insight: separate what (application logic) from how (I/O mechanics)
2. **Layered ABC Hierarchies** -- io module's 3-tier hierarchy, asyncio's event/transport/protocol layers, importlib's finder/loader/spec
3. **C/Python Hybrid** -- critical paths in C with Python fallbacks (functools, collections, io, json, pickle)
4. **Mirrored APIs** -- Thread and Process share identical interfaces; sync and async context managers share base classes
5. **State Machines with Explicit Transitions** -- Future, Task, HTTP connection all use documented state enums
6. **Composition over Deep Inheritance** -- mixins, decorators, and protocol delegation preferred over deep class hierarchies
7. **Timeout Everything** -- all blocking operations across threading, multiprocessing, and asyncio support timeouts
8. **Graceful Degradation** -- logging never crashes the application, importlib falls back through bootstrap tiers

## Process Observations

**What worked well:**
- Initial `rlm scan` at depth 2 gave enough structural overview to identify key packages
- Strategic targeting (6 packages out of 158 directories) kept the analysis focused
- `files_balanced` created good chunk sizes for the flat route-style packages
- All 6 subagents completed successfully with rich findings
- Bounded output prevented any context overflow despite 45MB target

**What the test revealed about RLM at scale:**
- **201 directory chunks** from the initial `files_directory` -- too many to dispatch individually. Manual triage was needed to select which packages to analyze.
- **Recursive iteration wasn't triggered** -- a single targeted pass was sufficient for the architectural patterns query. A more open-ended query ("find all bugs") would require multiple iterations.
- **Coverage was shallow** -- ~1% of the codebase analyzed. Full analysis would require multiple waves of chunking and dispatch, which is exactly what the iteration loop is designed for.
- **Subagent wall time varied widely** -- asyncio analysis took ~48s, but http/logging/unittest and concurrency took 5-6 minutes each (the haiku subagents wrote extensive analysis documents to /tmp/).

## Comparison to Paper Claims

| Metric | Value | Notes |
|---|---|---|
| **Codebase size** | 45.1 MB / 1.18M lines | Largest target tested |
| **Orchestrator context** | ~8 KB | Stayed bounded despite enormous target |
| **Leverage (analyzed)** | ~62x | 500KB analyzed / 8KB orchestrator |
| **Leverage (total)** | ~5,600x | 45MB total / 8KB orchestrator |
| **Bounded output** | Held | All CLI commands truncated correctly |
| **Iteration loop** | Not fully exercised | Single pass was sufficient for this query |
| **Patterns found** | 100+ | Comprehensive architectural catalog |
| **Wall time** | ~8 minutes | Including clone, scans, 6 parallel subagents |
