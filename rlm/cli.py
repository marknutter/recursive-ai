"""CLI entry point -- all Claude<->Python interaction goes through here.

All stdout is capped at 4000 chars with truncation notice.
"""

import argparse
import json
import sys

from rlm import scanner, chunker, extractor, state, memory, export, url_fetcher

MAX_OUTPUT = 4000


def _truncate(text: str, max_chars: int = MAX_OUTPUT) -> str:
    """Truncate output with notice if over budget."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 60] + "\n\n... [output truncated at 4000 chars -- use extract for full content]"


def _print(text: str):
    """Print with truncation."""
    print(_truncate(text))


def cmd_scan(args):
    """Scan a path and produce metadata summary."""
    metadata = scanner.scan_path(args.path, max_depth=args.depth)
    _print(scanner.format_metadata(metadata, max_chars=MAX_OUTPUT))


def cmd_chunk(args):
    """Chunk content and save manifest."""
    strategy = args.strategy
    path = args.path

    if strategy == "lines":
        manifest = chunker.chunk_by_lines(path, chunk_size=args.chunk_size, overlap=args.overlap)
    elif strategy.startswith("files"):
        group_by = strategy.replace("files_", "") if "_" in strategy else "directory"
        manifest = chunker.chunk_by_files(path, group_by=group_by)
    elif strategy == "functions":
        manifest = chunker.chunk_by_functions(path)
    elif strategy == "headings":
        manifest = chunker.chunk_by_headings(path, level=args.heading_level)
    elif strategy == "semantic":
        manifest = chunker.chunk_by_semantic(path, target_size=args.target_size)
    else:
        _print(f"Unknown strategy: {strategy}")
        sys.exit(1)

    if "error" in manifest:
        _print(f"Error: {manifest['error']}")
        sys.exit(1)

    # Save manifest if session provided
    if args.session:
        session_dir = f"/tmp/rlm-sessions/{args.session}"
        manifest_path = chunker.save_manifest(manifest, session_dir)
        state.update_iteration(
            args.session,
            iteration=0,
            action=f"chunk_{strategy}",
            summary=f"Created {manifest['chunk_count']} chunks"
        )
        manifest["manifest_path"] = manifest_path

    # Output summary (not full manifest)
    lines = []
    lines.append(f"Strategy: {manifest.get('strategy', strategy)}")
    lines.append(f"Chunks: {manifest['chunk_count']}")
    if "total_lines" in manifest:
        lines.append(f"Total lines: {manifest['total_lines']}")
    lines.append("")

    for c in manifest["chunks"]:
        cid = c["chunk_id"]
        chars = c.get("char_count", 0)
        preview = c.get("preview", "")
        name = c.get("name", c.get("heading", c.get("group_name", "")))

        info = f"  {cid}"
        if name:
            info += f" [{name}]"
        if "start_line" in c:
            info += f" L{c['start_line']}-{c['end_line']}"
        info += f" ({chars:,} chars)"
        if preview:
            info += f"  {preview[:60]}"
        lines.append(info)

    if args.session:
        lines.append(f"\nManifest saved: {manifest['manifest_path']}")

    _print("\n".join(lines))


def cmd_extract(args):
    """Extract content from a file or manifest."""
    if args.lines:
        parts = args.lines.split(":")
        if len(parts) != 2:
            _print("Error: --lines format is START:END (e.g., 1:50)")
            sys.exit(1)
        start, end = int(parts[0]), int(parts[1])
        content = extractor.extract_lines(args.path, start, end)
        _print(content)
    elif args.chunk_id and args.manifest:
        content = extractor.extract_chunk(args.manifest, args.chunk_id)
        _print(content)
    elif args.grep:
        content = extractor.extract_grep(args.path, args.grep, context=args.context)
        _print(content)
    else:
        _print("Error: Specify --lines START:END, --chunk-id ID --manifest PATH, or --grep PATTERN")
        sys.exit(1)


def cmd_recommend(args):
    """Suggest chunking strategies for a path."""
    recommendations = chunker.recommend_strategies(args.path)
    lines = [f"Recommended strategies for: {args.path}\n"]
    for r in recommendations:
        lines.append(f"  [{r['priority']}] {r['strategy']}: {r['reason']}")
    _print("\n".join(lines))


def cmd_init(args):
    """Create a new RLM session."""
    result = state.init_session(args.query, args.path)
    lines = [
        f"Session created: {result['session_id']}",
        f"Session dir: {result['session_dir']}",
        f"Query: {args.query}",
        f"Target: {args.path}",
    ]
    _print("\n".join(lines))


def cmd_status(args):
    """Show session status."""
    _print(state.format_status(args.session_id))


def cmd_result(args):
    """Manage session results."""
    if args.all:
        summary = state.format_results_summary(args.session_id)
        _print(summary)
    elif args.key and args.value:
        result = state.add_result(args.session_id, args.key, args.value)
        if "error" in result:
            _print(f"Error: {result['error']}")
        else:
            _print(f"Result stored: {args.key}")
    elif args.key:
        results = state.get_results(args.session_id)
        if isinstance(results, dict) and args.key in results:
            _print(results[args.key]["value"])
        else:
            _print(f"Result '{args.key}' not found")
    else:
        _print("Error: Specify --key K --value V to store, --key K to retrieve, or --all for summary")
        sys.exit(1)


def cmd_finalize(args):
    """Mark session as complete."""
    result = state.set_final(args.session_id, args.answer or "")
    if "error" in result:
        _print(f"Error: {result['error']}")
    else:
        _print(f"Session {args.session_id} marked as complete")


def cmd_remember(args):
    """Store a new memory entry."""
    # URL mode: delegate to remember-url logic
    if getattr(args, "url", None):
        args_url = type("Args", (), {
            "url": args.url,
            "tags": args.tags,
            "summary": args.summary,
            "depth": 2,
        })()
        cmd_remember_url(args_url)
        return

    if args.file:
        try:
            with open(args.file, "r", errors="replace") as f:
                content = f.read()
        except OSError as e:
            _print(f"Error reading file: {e}")
            sys.exit(1)
        source = "file"
        source_name = args.file
    elif args.stdin:
        content = sys.stdin.read()
        source = "stdin"
        source_name = None
    elif args.content:
        content = args.content
        source = "text"
        source_name = None
    else:
        _print("Error: Provide content as argument, --file PATH, --url URL, or --stdin")
        sys.exit(1)

    if not content.strip():
        _print("Error: Empty content")
        sys.exit(1)

    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
    result = memory.add_memory(
        content=content,
        tags=tags,
        source=source,
        source_name=source_name,
        summary=args.summary,
    )

    lines = [
        f"Memory stored: {result['id']}",
        f"Summary: {result['summary']}",
        f"Tags: {', '.join(result['tags'])}",
        f"Size: {result['char_count']:,} chars",
    ]
    _print("\n".join(lines))


def cmd_remember_url(args):
    """Fetch content from a URL and store as memory."""
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
    depth = getattr(args, "depth", 2)

    try:
        results = url_fetcher.remember_url(
            url=args.url,
            tags=tags,
            summary=args.summary if hasattr(args, "summary") and args.summary else None,
            depth=depth,
        )
    except ValueError as e:
        _print(f"Error: {e}")
        sys.exit(1)

    if len(results) == 1:
        r = results[0]
        lines = [
            f"Memory stored from URL: {r['id']}",
            f"Summary: {r['summary']}",
            f"Tags: {', '.join(r['tags'])}",
            f"Size: {r['char_count']:,} chars",
        ]
    else:
        lines = [f"Stored {len(results)} entries from URL:\n"]
        for r in results:
            lines.append(
                f"  {r['id']}  {r['summary']}  "
                f"[{', '.join(r['tags'][:4])}]  ({r['char_count']:,} chars)"
            )

    _print("\n".join(lines))


def cmd_recall(args):
    """Search memory and return matching entries.

    For large matches (>10KB), the output includes size annotations
    to guide RLM-powered recall via the /rlm skill.
    """
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
    results = memory.search_index(
        args.query, tags=tags, max_results=args.max, deep=args.deep,
        include_size=True,  # Annotate with size categories
    )

    # Check if any results need RLM chunking
    large_results = [r for r in results if r.get("size_category") in ("large", "huge")]

    output = memory.format_search_results(results)

    # Add guidance for large memories
    if large_results:
        guidance = [
            "\n" + "="*60,
            f"Note: {len(large_results)} of {len(results)} results are large (>10KB)",
            "",
            "For context-efficient retrieval of large memories:",
            "1. Use grep pre-filtering: rlm memory-extract <id> --grep \"keyword\"",
            "2. Or use RLM chunking for full analysis (via /rlm skill)",
            "",
            "Large results:"
        ]
        for r in large_results:
            size = r.get("char_count", 0)
            category = r.get("size_category", "unknown")
            guidance.append(f"  {r['id']}: {size:,} chars ({category})")
        guidance.append("="*60)
        output += "\n".join(guidance)

    _print(output)


def cmd_memory_extract(args):
    """Extract content from a memory entry."""
    if args.grep:
        content = memory.grep_memory_content(
            args.entry_id, args.grep, context=args.context,
        )
    else:
        content = memory.get_memory_content(args.entry_id, chunk_id=args.chunk_id)
    _print(content)


def cmd_memory_list(args):
    """List all memory entries."""
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
    _print(memory.format_index_summary(
        tags=tags,
        offset=args.offset,
        limit=args.limit,
    ))


def cmd_memory_tags(args):
    """List all tags with counts."""
    tag_counts = memory.list_tags()
    if not tag_counts:
        _print("No tags found. Memory store is empty.")
        return
    lines = [f"Tags ({len(tag_counts)} unique):\n"]
    for tag, count in tag_counts.items():
        lines.append(f"  {tag}: {count}")
    _print("\n".join(lines))


def cmd_forget(args):
    """Delete a memory entry."""
    result = memory.delete_memory(args.entry_id)
    if "error" in result:
        _print(f"Error: {result['error']}")
        sys.exit(1)
    _print(f"Deleted: {result['id']}")


def cmd_strategy(args):
    """Strategy management subcommands."""
    if args.strategy_action == "show":
        patterns = memory.load_learned_patterns()
        if not patterns:
            _print("No learned patterns yet. File: " + memory.PATTERNS_PATH)
        else:
            _print(patterns)
    elif args.strategy_action == "log":
        _print(memory.format_performance_summary())
    elif args.strategy_action == "perf":
        data = {}
        if args.query:
            data["query"] = args.query
        if args.search_terms:
            data["search_terms"] = [t.strip() for t in args.search_terms.split(",")]
        if args.entries_found is not None:
            data["entries_found"] = args.entries_found
        if args.entries_relevant is not None:
            data["entries_relevant"] = args.entries_relevant
        if args.subagents is not None:
            data["subagents_dispatched"] = args.subagents
        if args.notes:
            data["strategy_notes"] = args.notes
        memory.log_performance(data)
        _print("Performance logged.")
    else:
        _print("Unknown strategy action. Use: show, log, perf")


def cmd_stats(args):
    """Show memory store statistics."""
    from datetime import datetime
    from rlm import db

    memory.init_memory_store()
    stats = db.get_stats()

    def fmt_size(chars):
        if chars >= 1_000_000:
            return f"{chars / 1_000_000:.1f}M chars"
        if chars >= 1_000:
            return f"{chars / 1_000:.1f}K chars"
        return f"{chars} chars"

    def fmt_bytes(b):
        if b >= 1_000_000:
            return f"{b / 1_000_000:.1f} MB"
        if b >= 1_000:
            return f"{b / 1_000:.1f} KB"
        return f"{b} bytes"

    lines = ["RLM Memory Statistics", "=" * 40, ""]

    # Overview
    lines.append(f"Entries:        {stats['total_entries']}")
    lines.append(f"Total content:  {fmt_size(stats['total_chars'])}")
    lines.append(f"Database size:  {fmt_bytes(stats['db_file_size'])}")
    lines.append(f"Unique tags:    {stats['unique_tags']}")
    lines.append("")

    # Date range
    if stats["oldest_timestamp"]:
        oldest = datetime.fromtimestamp(stats["oldest_timestamp"]).strftime("%Y-%m-%d")
        newest = datetime.fromtimestamp(stats["newest_timestamp"]).strftime("%Y-%m-%d")
        lines.append(f"Date range:     {oldest} → {newest}")
        lines.append("")

    # Size stats
    lines.append(f"Entry sizes:    avg {fmt_size(stats['avg_chars'])}, "
                 f"min {fmt_size(stats['min_chars'])}, "
                 f"max {fmt_size(stats['max_chars'])}")
    lines.append("")

    # Size distribution
    lines.append("Size distribution:")
    for bucket, count in stats["size_distribution"].items():
        bar = "█" * min(count, 40)
        lines.append(f"  {bucket:<16} {count:>4}  {bar}")
    lines.append("")

    # By source
    if stats["by_source"]:
        lines.append("By source:")
        for source, info in sorted(stats["by_source"].items(), key=lambda x: -x[1]["count"]):
            lines.append(f"  {source:<12} {info['count']:>4} entries  ({fmt_size(info['chars'])})")
        lines.append("")

    # Top tags
    if stats["top_tags"]:
        lines.append("Top tags:")
        for tag, count in stats["top_tags"]:
            lines.append(f"  {tag:<24} {count:>4}")

    _print("\n".join(lines))


def cmd_tui(args):
    """Launch the interactive TUI dashboard."""
    from rlm.tui import RlmTuiApp
    app = RlmTuiApp()
    app.run()


def cmd_export_session(args):
    """Export a Claude Code session JSONL to readable transcript."""
    output_path = args.output if args.output else None
    text = export.export_session(args.session_file, output_path=output_path)

    if output_path:
        _print(f"Exported to {output_path} ({len(text):,} chars)")
    else:
        # Print without truncation — hooks pipe this into rlm remember
        print(text)


def main():
    parser = argparse.ArgumentParser(
        prog="rlm",
        description="RLM: Recursive Language Model toolkit for Claude Code",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan path and produce metadata")
    p_scan.add_argument("path", help="File or directory to scan")
    p_scan.add_argument("--depth", type=int, default=3, help="Max directory depth")
    p_scan.set_defaults(func=cmd_scan)

    # chunk
    p_chunk = subparsers.add_parser("chunk", help="Chunk content and save manifest")
    p_chunk.add_argument("path", help="File or directory to chunk")
    p_chunk.add_argument("--strategy", required=True,
                         choices=["lines", "files_directory", "files_language", "files_balanced",
                                  "functions", "headings", "semantic"],
                         help="Chunking strategy")
    p_chunk.add_argument("--session", help="Session ID to associate manifest with")
    p_chunk.add_argument("--chunk-size", type=int, default=500, help="Lines per chunk (lines strategy)")
    p_chunk.add_argument("--overlap", type=int, default=50, help="Overlap lines (lines strategy)")
    p_chunk.add_argument("--heading-level", type=int, default=2, help="Heading level (headings strategy)")
    p_chunk.add_argument("--target-size", type=int, default=50000, help="Target chars (semantic strategy)")
    p_chunk.set_defaults(func=cmd_chunk)

    # extract
    p_extract = subparsers.add_parser("extract", help="Extract content")
    p_extract.add_argument("path", help="File path")
    p_extract.add_argument("--lines", help="Line range START:END")
    p_extract.add_argument("--chunk-id", help="Chunk ID to extract")
    p_extract.add_argument("--manifest", help="Manifest file path")
    p_extract.add_argument("--grep", help="Regex pattern to search")
    p_extract.add_argument("--context", type=int, default=5, help="Context lines for grep")
    p_extract.set_defaults(func=cmd_extract)

    # recommend
    p_recommend = subparsers.add_parser("recommend", help="Suggest chunking strategies")
    p_recommend.add_argument("path", help="File or directory")
    p_recommend.set_defaults(func=cmd_recommend)

    # init
    p_init = subparsers.add_parser("init", help="Create new RLM session")
    p_init.add_argument("query", help="The analysis query")
    p_init.add_argument("path", help="Target path")
    p_init.set_defaults(func=cmd_init)

    # status
    p_status = subparsers.add_parser("status", help="Show session status")
    p_status.add_argument("session_id", help="Session ID")
    p_status.set_defaults(func=cmd_status)

    # result
    p_result = subparsers.add_parser("result", help="Manage session results")
    p_result.add_argument("session_id", help="Session ID")
    p_result.add_argument("--key", help="Result key")
    p_result.add_argument("--value", help="Result value to store")
    p_result.add_argument("--all", action="store_true", help="Show all results summary")
    p_result.set_defaults(func=cmd_result)

    # finalize
    p_finalize = subparsers.add_parser("finalize", help="Mark session complete")
    p_finalize.add_argument("session_id", help="Session ID")
    p_finalize.add_argument("--answer", help="Final answer text")
    p_finalize.set_defaults(func=cmd_finalize)

    # remember
    p_remember = subparsers.add_parser("remember", help="Store a memory entry")
    p_remember.add_argument("content", nargs="?", help="Text content to remember")
    p_remember.add_argument("--file", help="File to store as memory")
    p_remember.add_argument("--url", help="URL to fetch and store as memory")
    p_remember.add_argument("--stdin", action="store_true", help="Read from stdin")
    p_remember.add_argument("--tags", help="Comma-separated tags")
    p_remember.add_argument("--summary", help="Short description (auto-generated if omitted)")
    p_remember.set_defaults(func=cmd_remember)

    # remember-url
    p_remember_url = subparsers.add_parser("remember-url", help="Fetch URL content and store as memory")
    p_remember_url.add_argument("url", help="URL to fetch (web page, GitHub repo, raw file, API spec)")
    p_remember_url.add_argument("--tags", help="Comma-separated tags")
    p_remember_url.add_argument("--summary", help="Short description (auto-generated if omitted)")
    p_remember_url.add_argument("--depth", type=int, default=2, help="Directory scan depth for repos (default: 2)")
    p_remember_url.set_defaults(func=cmd_remember_url)

    # recall
    p_recall = subparsers.add_parser("recall", help="Search memory")
    p_recall.add_argument("query", help="Search query")
    p_recall.add_argument("--tags", help="Filter by comma-separated tags")
    p_recall.add_argument("--max", type=int, default=20, help="Max results")
    p_recall.add_argument("--deep", action="store_true", help="Also search content (slower)")
    p_recall.set_defaults(func=cmd_recall)

    # memory-extract
    p_mextract = subparsers.add_parser("memory-extract", help="Extract memory content")
    p_mextract.add_argument("entry_id", help="Memory entry ID")
    p_mextract.add_argument("--chunk-id", help="Specific chunk ID")
    p_mextract.add_argument("--grep", help="Search pattern within entry")
    p_mextract.add_argument("--context", type=int, default=3, help="Context lines for grep")
    p_mextract.set_defaults(func=cmd_memory_extract)

    # memory-list
    p_mlist = subparsers.add_parser("memory-list", help="List all memories")
    p_mlist.add_argument("--tags", help="Filter by comma-separated tags")
    p_mlist.add_argument("--offset", type=int, default=0, help="Skip first N entries")
    p_mlist.add_argument("--limit", type=int, default=50, help="Max entries to show")
    p_mlist.set_defaults(func=cmd_memory_list)

    # memory-tags
    p_mtags = subparsers.add_parser("memory-tags", help="List all tags")
    p_mtags.set_defaults(func=cmd_memory_tags)

    # forget
    p_forget = subparsers.add_parser("forget", help="Delete a memory entry")
    p_forget.add_argument("entry_id", help="Memory entry ID to delete")
    p_forget.set_defaults(func=cmd_forget)

    # strategy
    p_strategy = subparsers.add_parser("strategy", help="Manage recall strategies")
    p_strategy.add_argument("strategy_action", choices=["show", "log", "perf"],
                            help="show=learned patterns, log=performance history, perf=log new entry")
    p_strategy.add_argument("--query", help="Query that was run (perf)")
    p_strategy.add_argument("--search-terms", help="Comma-separated search terms used (perf)")
    p_strategy.add_argument("--entries-found", type=int, help="Total entries found (perf)")
    p_strategy.add_argument("--entries-relevant", type=int, help="Relevant entries (perf)")
    p_strategy.add_argument("--subagents", type=int, help="Subagents dispatched (perf)")
    p_strategy.add_argument("--notes", help="Strategy notes (perf)")
    p_strategy.set_defaults(func=cmd_strategy)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show memory store statistics")
    p_stats.set_defaults(func=cmd_stats)

    # tui
    p_tui = subparsers.add_parser("tui", help="Launch interactive TUI dashboard")
    p_tui.set_defaults(func=cmd_tui)

    # export-session
    p_export = subparsers.add_parser("export-session", help="Export session JSONL to transcript")
    p_export.add_argument("session_file", help="Path to Claude Code .jsonl session file")
    p_export.add_argument("--output", help="Write to file instead of stdout")
    p_export.set_defaults(func=cmd_export_session)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
