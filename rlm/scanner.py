"""Metadata production -- NEVER outputs full file content.

Scans paths to produce bounded-size metadata: file trees, sizes,
line counts, languages, and structure outlines. Enforces the
"symbolic handle" principle from the RLM paper.
"""

import ast
import os
import re
import textwrap
from pathlib import Path

# Extensions -> language mapping
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".php": "php",
    ".lua": "lua",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".md": "markdown",
    ".mdx": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".r": "r",
    ".R": "r",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".scala": "scala",
    ".clj": "clojure",
    ".dart": "dart",
    ".vue": "vue",
    ".svelte": "svelte",
}

# Directories to skip
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".next", ".nuxt", "target", "vendor", ".cargo",
    ".gradle", "coverage", ".nyc_output", "egg-info",
}

# Binary/unreadable extensions to skip
SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a",
    ".class", ".jar", ".war", ".ear", ".zip", ".tar", ".gz", ".bz2",
    ".xz", ".7z", ".rar", ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".ico", ".svg", ".webp", ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".woff", ".woff2", ".ttf", ".eot", ".lock",
}


def detect_language(filepath: str) -> str:
    """Detect language from file extension."""
    ext = Path(filepath).suffix.lower()
    return LANGUAGE_MAP.get(ext, "unknown")


def _count_lines(filepath: str) -> int:
    """Count lines in a file without reading entire content into memory."""
    try:
        count = 0
        with open(filepath, "r", errors="replace") as f:
            for _ in f:
                count += 1
        return count
    except (OSError, UnicodeDecodeError):
        return 0


def extract_structure(filepath: str) -> list[dict]:
    """Extract function/class names with line ranges.

    Uses ast for Python, regex patterns for other languages.
    Returns list of {name, type, start_line, end_line}.
    """
    lang = detect_language(filepath)

    if lang == "python":
        return _extract_python_structure(filepath)
    elif lang in ("javascript", "typescript"):
        return _extract_js_ts_structure(filepath)
    elif lang == "go":
        return _extract_go_structure(filepath)
    elif lang in ("java", "kotlin", "csharp", "scala"):
        return _extract_java_like_structure(filepath)
    elif lang == "rust":
        return _extract_rust_structure(filepath)
    elif lang == "ruby":
        return _extract_ruby_structure(filepath)
    else:
        return _extract_generic_structure(filepath)


def _extract_python_structure(filepath: str) -> list[dict]:
    """Use ast to extract Python structure."""
    try:
        with open(filepath, "r", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return _extract_generic_structure(filepath)

    items = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            items.append({
                "name": node.name,
                "type": "class",
                "start_line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
            })
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            items.append({
                "name": node.name,
                "type": "function",
                "start_line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
            })
    items.sort(key=lambda x: x["start_line"])
    return items


def _read_lines_safe(filepath: str) -> list[str]:
    """Read lines from a file safely."""
    try:
        with open(filepath, "r", errors="replace") as f:
            return f.readlines()
    except (OSError, UnicodeDecodeError):
        return []


def _extract_js_ts_structure(filepath: str) -> list[dict]:
    """Regex-based extraction for JS/TS."""
    lines = _read_lines_safe(filepath)
    items = []

    patterns = [
        # function declarations
        (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
        # arrow/const functions
        (r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\(|[a-zA-Z])", "function"),
        # class declarations
        (r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)", "class"),
        # method definitions
        (r"^\s+(?:async\s+)?(\w+)\s*\(", "method"),
    ]

    for i, line in enumerate(lines, 1):
        for pattern, item_type in patterns:
            m = re.match(pattern, line)
            if m:
                items.append({
                    "name": m.group(1),
                    "type": item_type,
                    "start_line": i,
                    "end_line": i,  # Approximate; no full parse
                })
                break

    return items


def _extract_go_structure(filepath: str) -> list[dict]:
    """Regex-based extraction for Go."""
    lines = _read_lines_safe(filepath)
    items = []

    for i, line in enumerate(lines, 1):
        # func (receiver) name(...) or func name(...)
        m = re.match(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", line)
        if m:
            items.append({"name": m.group(1), "type": "function", "start_line": i, "end_line": i})
            continue
        # type Name struct/interface
        m = re.match(r"^type\s+(\w+)\s+(?:struct|interface)", line)
        if m:
            items.append({"name": m.group(1), "type": "type", "start_line": i, "end_line": i})

    return items


def _extract_java_like_structure(filepath: str) -> list[dict]:
    """Regex-based extraction for Java/Kotlin/C#/Scala."""
    lines = _read_lines_safe(filepath)
    items = []

    for i, line in enumerate(lines, 1):
        # class/interface
        m = re.match(r"^\s*(?:public|private|protected|internal|abstract|final|open|data|sealed)?\s*(?:static\s+)?(?:class|interface|enum|object|record)\s+(\w+)", line)
        if m:
            items.append({"name": m.group(1), "type": "class", "start_line": i, "end_line": i})
            continue
        # method
        m = re.match(r"^\s+(?:public|private|protected|internal|override|abstract|final|open|static|suspend|fun)?\s*(?:static\s+)?(?:\w+(?:<[^>]+>)?\s+)?(\w+)\s*\(", line)
        if m and m.group(1) not in ("if", "for", "while", "switch", "catch", "return", "new"):
            items.append({"name": m.group(1), "type": "method", "start_line": i, "end_line": i})

    return items


def _extract_rust_structure(filepath: str) -> list[dict]:
    """Regex-based extraction for Rust."""
    lines = _read_lines_safe(filepath)
    items = []

    for i, line in enumerate(lines, 1):
        m = re.match(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", line)
        if m:
            items.append({"name": m.group(1), "type": "function", "start_line": i, "end_line": i})
            continue
        m = re.match(r"^\s*(?:pub\s+)?(?:struct|enum|trait|impl)\s+(\w+)", line)
        if m:
            items.append({"name": m.group(1), "type": "type", "start_line": i, "end_line": i})

    return items


def _extract_ruby_structure(filepath: str) -> list[dict]:
    """Regex-based extraction for Ruby."""
    lines = _read_lines_safe(filepath)
    items = []

    for i, line in enumerate(lines, 1):
        m = re.match(r"^\s*(?:class|module)\s+(\w+)", line)
        if m:
            items.append({"name": m.group(1), "type": "class", "start_line": i, "end_line": i})
            continue
        m = re.match(r"^\s*def\s+(\w+[?!]?)", line)
        if m:
            items.append({"name": m.group(1), "type": "method", "start_line": i, "end_line": i})

    return items


def _extract_generic_structure(filepath: str) -> list[dict]:
    """Fallback: regex for common patterns across languages."""
    lines = _read_lines_safe(filepath)
    items = []

    for i, line in enumerate(lines, 1):
        # Generic function pattern
        m = re.match(r"^\s*(?:def|func|function|fn|sub|proc)\s+(\w+)", line)
        if m:
            items.append({"name": m.group(1), "type": "function", "start_line": i, "end_line": i})
            continue
        # Generic class pattern
        m = re.match(r"^\s*(?:class|struct|enum|type|interface|trait|module)\s+(\w+)", line)
        if m:
            items.append({"name": m.group(1), "type": "type", "start_line": i, "end_line": i})

    return items


def scan_path(path: str, max_depth: int = 3) -> dict:
    """Scan a path and produce metadata summary.

    Returns dict with:
    - target: the scanned path
    - is_file: bool
    - total_files: int
    - total_lines: int
    - total_bytes: int
    - languages: {lang: {files: int, lines: int, bytes: int}}
    - tree: list of {path, size, lines, language, structure}
    - directories: list of dir paths
    """
    target = Path(path).resolve()

    if not target.exists():
        return {"error": f"Path not found: {path}"}

    if target.is_file():
        return _scan_single_file(target)

    return _scan_directory(target, max_depth)


def _scan_single_file(filepath: Path) -> dict:
    """Scan a single file."""
    stat = filepath.stat()
    lang = detect_language(str(filepath))
    lines = _count_lines(str(filepath))
    structure = extract_structure(str(filepath))

    return {
        "target": str(filepath),
        "is_file": True,
        "total_files": 1,
        "total_lines": lines,
        "total_bytes": stat.st_size,
        "languages": {lang: {"files": 1, "lines": lines, "bytes": stat.st_size}},
        "tree": [{
            "path": str(filepath),
            "size": stat.st_size,
            "lines": lines,
            "language": lang,
            "structure": structure,
        }],
        "directories": [],
    }


def _should_skip_dir(dirname: str) -> bool:
    """Check if a directory should be skipped."""
    return dirname in SKIP_DIRS or dirname.startswith(".")


def _should_skip_file(filepath: Path) -> bool:
    """Check if a file should be skipped."""
    ext = filepath.suffix.lower()
    return ext in SKIP_EXTENSIONS


def _scan_directory(dirpath: Path, max_depth: int) -> dict:
    """Scan a directory tree up to max_depth."""
    files = []
    directories = []
    languages: dict[str, dict] = {}
    total_lines = 0
    total_bytes = 0

    def _walk(current: Path, depth: int):
        nonlocal total_lines, total_bytes

        if depth > max_depth:
            return

        try:
            entries = sorted(current.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.is_dir():
                if _should_skip_dir(entry.name):
                    continue
                directories.append(str(entry.relative_to(dirpath)))
                _walk(entry, depth + 1)
            elif entry.is_file():
                if _should_skip_file(entry):
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue

                # Skip very large files (>5MB)
                if stat.st_size > 5_000_000:
                    continue

                lang = detect_language(str(entry))
                lines = _count_lines(str(entry))
                structure = extract_structure(str(entry))

                files.append({
                    "path": str(entry.relative_to(dirpath)),
                    "size": stat.st_size,
                    "lines": lines,
                    "language": lang,
                    "structure": structure,
                })

                total_lines += lines
                total_bytes += stat.st_size

                if lang not in languages:
                    languages[lang] = {"files": 0, "lines": 0, "bytes": 0}
                languages[lang]["files"] += 1
                languages[lang]["lines"] += lines
                languages[lang]["bytes"] += stat.st_size

    _walk(dirpath, 0)

    return {
        "target": str(dirpath),
        "is_file": False,
        "total_files": len(files),
        "total_lines": total_lines,
        "total_bytes": total_bytes,
        "languages": dict(sorted(languages.items(), key=lambda x: -x[1]["lines"])),
        "tree": files,
        "directories": directories,
    }


def format_metadata(metadata: dict, max_chars: int = 4000) -> str:
    """Format metadata into a bounded human-readable summary.

    Always fits within max_chars, truncating intelligently.
    """
    if "error" in metadata:
        return f"Error: {metadata['error']}"

    lines = []
    lines.append(f"Target: {metadata['target']}")
    lines.append(f"Type: {'file' if metadata['is_file'] else 'directory'}")
    lines.append(f"Files: {metadata['total_files']}")
    lines.append(f"Lines: {metadata['total_lines']:,}")
    lines.append(f"Size: {_format_bytes(metadata['total_bytes'])}")
    lines.append("")

    # Language breakdown
    if metadata["languages"]:
        lines.append("Languages:")
        for lang, stats in metadata["languages"].items():
            lines.append(f"  {lang}: {stats['files']} files, {stats['lines']:,} lines")
        lines.append("")

    # Directory listing
    if metadata["directories"]:
        lines.append(f"Directories ({len(metadata['directories'])}):")
        for d in metadata["directories"][:30]:
            lines.append(f"  {d}/")
        if len(metadata["directories"]) > 30:
            lines.append(f"  ... and {len(metadata['directories']) - 30} more")
        lines.append("")

    # File tree with structure
    if metadata["tree"]:
        lines.append(f"Files ({len(metadata['tree'])}):")
        for f in metadata["tree"]:
            struct_summary = ""
            if f["structure"]:
                names = [s["name"] for s in f["structure"][:5]]
                struct_summary = f" [{', '.join(names)}{'...' if len(f['structure']) > 5 else ''}]"
            lines.append(f"  {f['path']} ({f['lines']} lines, {f['language']}){struct_summary}")

            # Check if we're approaching the limit
            current = "\n".join(lines)
            if len(current) > max_chars - 200:
                remaining = len(metadata["tree"]) - metadata["tree"].index(f) - 1
                if remaining > 0:
                    lines.append(f"  ... and {remaining} more files")
                break

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars - 50] + "\n... [truncated to fit output limit]"
    return result


def _format_bytes(size: int) -> str:
    """Format byte size into human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
