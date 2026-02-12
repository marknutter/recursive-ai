"""Content decomposition strategies.

Chunks content into metadata-only manifests (never full content).
Each chunk is described by {chunk_id, source_file, start_line, end_line,
char_count, preview} -- the preview is a short excerpt for orientation.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from rlm.scanner import detect_language, extract_structure, _count_lines, SKIP_DIRS, SKIP_EXTENSIONS


def chunk_by_lines(
    path: str, chunk_size: int = 500, overlap: int = 50
) -> dict:
    """Chunk a file into fixed-size line ranges with overlap.

    Returns a manifest dict with chunk metadata only.
    """
    filepath = Path(path).resolve()
    if not filepath.is_file():
        return {"error": f"Not a file: {path}"}

    total_lines = _count_lines(str(filepath))
    if total_lines == 0:
        return {"source_file": str(filepath), "strategy": "lines", "chunks": []}

    chunks = []
    start = 1
    while start <= total_lines:
        end = min(start + chunk_size - 1, total_lines)
        chunk_id = _make_chunk_id(str(filepath), start, end)
        preview = _get_preview(str(filepath), start)
        char_count = _estimate_chars(str(filepath), start, end)

        chunks.append({
            "chunk_id": chunk_id,
            "source_file": str(filepath),
            "start_line": start,
            "end_line": end,
            "char_count": char_count,
            "preview": preview,
        })

        if end >= total_lines:
            break
        start = end - overlap + 1

    return {
        "source_file": str(filepath),
        "strategy": "lines",
        "total_lines": total_lines,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def chunk_by_files(
    dirpath: str, group_by: str = "directory"
) -> dict:
    """Chunk a directory into file-group chunks.

    group_by: "directory" | "language" | "balanced"
    Returns manifest with each chunk being a group of files.
    """
    root = Path(dirpath).resolve()
    if not root.is_dir():
        return {"error": f"Not a directory: {dirpath}"}

    files = _collect_files(root)

    if group_by == "directory":
        groups = _group_by_directory(root, files)
    elif group_by == "language":
        groups = _group_by_language(files)
    elif group_by == "balanced":
        groups = _group_balanced(files, target_size=50000)
    else:
        return {"error": f"Unknown group_by: {group_by}"}

    chunks = []
    for group_name, group_files in groups.items():
        total_lines = sum(f["lines"] for f in group_files)
        total_chars = sum(f["size"] for f in group_files)
        file_paths = [f["path"] for f in group_files]
        chunk_id = _make_chunk_id(group_name, 0, total_lines)

        chunks.append({
            "chunk_id": chunk_id,
            "group_name": group_name,
            "files": file_paths,
            "file_count": len(file_paths),
            "total_lines": total_lines,
            "char_count": total_chars,
            "preview": f"{len(file_paths)} files: {', '.join(Path(p).name for p in file_paths[:5])}{'...' if len(file_paths) > 5 else ''}",
        })

    return {
        "source_dir": str(root),
        "strategy": f"files_{group_by}",
        "total_files": len(files),
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def chunk_by_functions(filepath: str) -> dict:
    """Chunk a file by function/class boundaries.

    Uses ast for Python, regex for other languages.
    Falls back to chunk_by_lines if no structure found.
    """
    path = Path(filepath).resolve()
    if not path.is_file():
        return {"error": f"Not a file: {filepath}"}

    structure = extract_structure(str(path))
    total_lines = _count_lines(str(path))

    if not structure:
        # No functions/classes found, fall back to semantic chunking
        return chunk_by_semantic(filepath)

    chunks = []
    # Add gaps between structures as their own chunks
    prev_end = 0
    for item in structure:
        # Gap before this item
        if item["start_line"] > prev_end + 1:
            gap_start = prev_end + 1
            gap_end = item["start_line"] - 1
            if gap_end - gap_start > 2:  # Skip tiny gaps
                chunk_id = _make_chunk_id(str(path), gap_start, gap_end)
                chunks.append({
                    "chunk_id": chunk_id,
                    "source_file": str(path),
                    "start_line": gap_start,
                    "end_line": gap_end,
                    "char_count": _estimate_chars(str(path), gap_start, gap_end),
                    "type": "gap",
                    "name": f"gap_{gap_start}_{gap_end}",
                    "preview": _get_preview(str(path), gap_start),
                })

        # The structure item itself
        chunk_id = _make_chunk_id(str(path), item["start_line"], item["end_line"])
        chunks.append({
            "chunk_id": chunk_id,
            "source_file": str(path),
            "start_line": item["start_line"],
            "end_line": item["end_line"],
            "char_count": _estimate_chars(str(path), item["start_line"], item["end_line"]),
            "type": item["type"],
            "name": item["name"],
            "preview": _get_preview(str(path), item["start_line"]),
        })
        prev_end = item["end_line"]

    # Trailing gap
    if prev_end < total_lines:
        gap_start = prev_end + 1
        if total_lines - gap_start > 2:
            chunk_id = _make_chunk_id(str(path), gap_start, total_lines)
            chunks.append({
                "chunk_id": chunk_id,
                "source_file": str(path),
                "start_line": gap_start,
                "end_line": total_lines,
                "char_count": _estimate_chars(str(path), gap_start, total_lines),
                "type": "gap",
                "name": f"gap_{gap_start}_{total_lines}",
                "preview": _get_preview(str(path), gap_start),
            })

    return {
        "source_file": str(path),
        "strategy": "functions",
        "total_lines": total_lines,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def chunk_by_headings(filepath: str, level: int = 2) -> dict:
    """Chunk a markdown file by heading boundaries.

    Splits at headings of the specified level or higher.
    """
    path = Path(filepath).resolve()
    if not path.is_file():
        return {"error": f"Not a file: {filepath}"}

    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": f"Cannot read file: {e}"}

    if not lines:
        return {"source_file": str(path), "strategy": "headings", "chunks": []}

    # Find heading positions
    heading_pattern = re.compile(r"^(#{1," + str(level) + r"})\s+(.+)")
    heading_positions = []

    for i, line in enumerate(lines, 1):
        m = heading_pattern.match(line)
        if m:
            heading_positions.append((i, m.group(2).strip()))

    if not heading_positions:
        # No headings found, treat entire file as one chunk
        return chunk_by_semantic(filepath)

    chunks = []
    total_lines = len(lines)

    for idx, (start, title) in enumerate(heading_positions):
        if idx + 1 < len(heading_positions):
            end = heading_positions[idx + 1][0] - 1
        else:
            end = total_lines

        chunk_id = _make_chunk_id(str(path), start, end)
        chunks.append({
            "chunk_id": chunk_id,
            "source_file": str(path),
            "start_line": start,
            "end_line": end,
            "char_count": _estimate_chars(str(path), start, end),
            "heading": title,
            "preview": _get_preview(str(path), start),
        })

    # Content before first heading
    if heading_positions[0][0] > 1:
        preamble_end = heading_positions[0][0] - 1
        chunk_id = _make_chunk_id(str(path), 1, preamble_end)
        chunks.insert(0, {
            "chunk_id": chunk_id,
            "source_file": str(path),
            "start_line": 1,
            "end_line": preamble_end,
            "char_count": _estimate_chars(str(path), 1, preamble_end),
            "heading": "(preamble)",
            "preview": _get_preview(str(path), 1),
        })

    return {
        "source_file": str(path),
        "strategy": "headings",
        "total_lines": total_lines,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def chunk_by_semantic(filepath: str, target_size: int = 50000) -> dict:
    """Chunk a file by blank-line boundaries, adaptively sized.

    Tries to create chunks of roughly target_size characters,
    splitting at blank-line boundaries for natural breaks.
    """
    path = Path(filepath).resolve()
    if not path.is_file():
        return {"error": f"Not a file: {filepath}"}

    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": f"Cannot read file: {e}"}

    if not lines:
        return {"source_file": str(path), "strategy": "semantic", "chunks": []}

    total_lines = len(lines)

    # Find blank-line boundaries
    boundaries = [0]  # Start
    for i, line in enumerate(lines):
        if line.strip() == "" and i > 0:
            boundaries.append(i)
    boundaries.append(total_lines)

    # Merge boundaries into chunks of target_size
    chunks = []
    chunk_start_idx = 0
    current_chars = 0

    for i in range(1, len(boundaries)):
        segment_chars = sum(len(lines[j]) for j in range(boundaries[i - 1], min(boundaries[i], total_lines)))
        current_chars += segment_chars

        if current_chars >= target_size or i == len(boundaries) - 1:
            start_line = boundaries[chunk_start_idx] + 1
            end_line = boundaries[i]
            if end_line < start_line:
                continue

            chunk_id = _make_chunk_id(str(path), start_line, end_line)
            chunks.append({
                "chunk_id": chunk_id,
                "source_file": str(path),
                "start_line": start_line,
                "end_line": end_line,
                "char_count": current_chars,
                "preview": _get_preview(str(path), start_line),
            })

            chunk_start_idx = i
            current_chars = 0

    return {
        "source_file": str(path),
        "strategy": "semantic",
        "total_lines": total_lines,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def recommend_strategies(path: str) -> list[dict]:
    """Recommend chunking strategies based on content type and size.

    Returns ranked list of {strategy, reason, priority}.
    """
    target = Path(path).resolve()

    if target.is_file():
        return _recommend_for_file(target)
    elif target.is_dir():
        return _recommend_for_directory(target)
    else:
        return [{"strategy": "lines", "reason": "Path not found, defaulting to line-based", "priority": 1}]


def _recommend_for_file(filepath: Path) -> list[dict]:
    """Recommend strategies for a single file."""
    lang = detect_language(str(filepath))
    lines = _count_lines(str(filepath))
    recommendations = []

    if lang == "markdown":
        recommendations.append({
            "strategy": "headings",
            "reason": "Markdown file -- heading boundaries are natural splits",
            "priority": 1,
        })
    elif lang in ("python", "javascript", "typescript", "go", "rust", "java", "kotlin", "ruby"):
        structure = extract_structure(str(filepath))
        if structure:
            recommendations.append({
                "strategy": "functions",
                "reason": f"Found {len(structure)} functions/classes -- structural boundaries are ideal",
                "priority": 1,
            })

    if lines > 200:
        recommendations.append({
            "strategy": "semantic",
            "reason": "Blank-line boundaries for natural paragraph/block splits",
            "priority": 2 if recommendations else 1,
        })

    recommendations.append({
        "strategy": "lines",
        "reason": f"Fixed-size chunks ({lines} lines total)",
        "priority": 3 if recommendations else 1,
    })

    return sorted(recommendations, key=lambda x: x["priority"])


def _recommend_for_directory(dirpath: Path) -> list[dict]:
    """Recommend strategies for a directory."""
    files = _collect_files(dirpath)
    total_lines = sum(f["lines"] for f in files)
    languages = set(f["language"] for f in files)

    recommendations = []

    # Always recommend file-based chunking for directories
    if len(files) <= 50:
        recommendations.append({
            "strategy": "files_directory",
            "reason": f"Small project ({len(files)} files) -- group by directory",
            "priority": 1,
        })
    elif len(languages) > 3:
        recommendations.append({
            "strategy": "files_language",
            "reason": f"Multi-language project ({len(languages)} languages) -- group by language",
            "priority": 1,
        })
    else:
        recommendations.append({
            "strategy": "files_balanced",
            "reason": f"Large project ({len(files)} files, {total_lines:,} lines) -- balanced groups",
            "priority": 1,
        })

    recommendations.append({
        "strategy": "files_directory",
        "reason": "Group files by directory for structural analysis",
        "priority": 2,
    })

    return sorted(recommendations, key=lambda x: x["priority"])


# --- Helper functions ---

def _make_chunk_id(source: str, start: int, end: int) -> str:
    """Create a deterministic chunk ID."""
    raw = f"{source}:{start}:{end}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _get_preview(filepath: str, start_line: int, max_len: int = 120) -> str:
    """Get a short preview from the start of a chunk."""
    try:
        with open(filepath, "r", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if i >= start_line:
                    stripped = line.strip()
                    if stripped:
                        if len(stripped) > max_len:
                            return stripped[:max_len] + "..."
                        return stripped
                    # Skip blank lines for preview
                    if i > start_line + 5:
                        break
    except OSError:
        pass
    return "(empty)"


def _estimate_chars(filepath: str, start: int, end: int) -> int:
    """Estimate character count for a line range."""
    count = 0
    try:
        with open(filepath, "r", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if i > end:
                    break
                if i >= start:
                    count += len(line)
    except OSError:
        pass
    return count


def _collect_files(root: Path) -> list[dict]:
    """Collect all eligible files in a directory."""
    files = []

    for dirpath_str, dirnames, filenames in os.walk(root):
        # Filter out skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]

        for fname in filenames:
            fpath = Path(dirpath_str) / fname
            if fpath.suffix.lower() in SKIP_EXTENSIONS:
                continue
            try:
                stat = fpath.stat()
            except OSError:
                continue
            if stat.st_size > 5_000_000:
                continue

            files.append({
                "path": str(fpath),
                "relative": str(fpath.relative_to(root)),
                "size": stat.st_size,
                "lines": _count_lines(str(fpath)),
                "language": detect_language(str(fpath)),
            })

    return files


def _group_by_directory(root: Path, files: list[dict]) -> dict[str, list[dict]]:
    """Group files by their parent directory."""
    groups: dict[str, list[dict]] = {}
    for f in files:
        rel = Path(f["relative"])
        parent = str(rel.parent) if rel.parent != Path(".") else "(root)"
        groups.setdefault(parent, []).append(f)
    return groups


def _group_by_language(files: list[dict]) -> dict[str, list[dict]]:
    """Group files by language."""
    groups: dict[str, list[dict]] = {}
    for f in files:
        groups.setdefault(f["language"], []).append(f)
    return groups


def _group_balanced(files: list[dict], target_size: int = 50000) -> dict[str, list[dict]]:
    """Group files into balanced chunks by total character count."""
    sorted_files = sorted(files, key=lambda f: -f["size"])
    groups: dict[str, list[dict]] = {}
    group_sizes: dict[str, int] = {}
    group_idx = 0

    for f in sorted_files:
        # Find existing group with room, or create new one
        placed = False
        for gname, gsize in group_sizes.items():
            if gsize + f["size"] <= target_size:
                groups[gname].append(f)
                group_sizes[gname] += f["size"]
                placed = True
                break

        if not placed:
            gname = f"group_{group_idx}"
            groups[gname] = [f]
            group_sizes[gname] = f["size"]
            group_idx += 1

    return groups


def save_manifest(manifest: dict, session_dir: str) -> str:
    """Save a chunk manifest to the session directory.

    Returns the path to the saved manifest file.
    """
    manifest_path = os.path.join(session_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest_path
