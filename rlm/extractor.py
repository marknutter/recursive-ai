"""Content retrieval -- when Claude needs actual text for a chunk.

Provides targeted extraction of file content by line ranges,
chunk IDs from manifests, or grep patterns with context.
"""

import json
import re
from pathlib import Path


def extract_lines(filepath: str, start: int, end: int) -> str:
    """Extract raw content for a line range (1-indexed, inclusive).

    Returns the content with line numbers prefixed.
    """
    path = Path(filepath)
    if not path.is_file():
        return f"Error: File not found: {filepath}"

    lines = []
    try:
        with open(filepath, "r", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if i > end:
                    break
                if i >= start:
                    lines.append(f"{i:>6}| {line.rstrip()}")
    except OSError as e:
        return f"Error reading file: {e}"

    if not lines:
        return f"Error: No content found for lines {start}-{end} in {filepath}"

    return "\n".join(lines)


def extract_chunk(manifest_path: str, chunk_id: str) -> str:
    """Extract content for a specific chunk from a manifest.

    The manifest is a JSON file containing chunk metadata
    including source file, start_line, and end_line.
    """
    manifest = _load_manifest(manifest_path)
    if isinstance(manifest, str):
        return manifest  # Error message

    chunk = _find_chunk(manifest, chunk_id)
    if isinstance(chunk, str):
        return chunk  # Error message

    source = chunk.get("source_file", chunk.get("path", ""))
    start = chunk["start_line"]
    end = chunk["end_line"]

    return extract_lines(source, start, end)


def extract_multiple(manifest_path: str, chunk_ids: list[str]) -> dict[str, str]:
    """Extract content for multiple chunks from a manifest.

    Returns dict of chunk_id -> content.
    """
    manifest = _load_manifest(manifest_path)
    if isinstance(manifest, str):
        return {"error": manifest}

    results = {}
    for cid in chunk_ids:
        chunk = _find_chunk(manifest, cid)
        if isinstance(chunk, str):
            results[cid] = chunk
        else:
            source = chunk.get("source_file", chunk.get("path", ""))
            start = chunk["start_line"]
            end = chunk["end_line"]
            results[cid] = extract_lines(source, start, end)

    return results


def extract_grep(filepath: str, pattern: str, context: int = 5) -> str:
    """Extract lines matching a regex pattern with surrounding context.

    Returns matching regions with line numbers.
    """
    path = Path(filepath)
    if not path.is_file():
        return f"Error: File not found: {filepath}"

    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    try:
        with open(filepath, "r", errors="replace") as f:
            all_lines = f.readlines()
    except OSError as e:
        return f"Error reading file: {e}"

    matches = []
    for i, line in enumerate(all_lines):
        if compiled.search(line):
            matches.append(i)

    if not matches:
        return f"No matches found for pattern '{pattern}' in {filepath}"

    # Build output with context, merging overlapping regions
    regions = _merge_regions(matches, context, len(all_lines))
    output_lines = []

    for region_start, region_end in regions:
        if output_lines:
            output_lines.append("---")  # Region separator
        for i in range(region_start, min(region_end + 1, len(all_lines))):
            marker = ">>" if i in matches else "  "
            output_lines.append(f"{marker} {i + 1:>6}| {all_lines[i].rstrip()}")

    return "\n".join(output_lines)


def _load_manifest(manifest_path: str) -> list[dict] | str:
    """Load a chunk manifest from JSON file."""
    path = Path(manifest_path)
    if not path.is_file():
        return f"Error: Manifest not found: {manifest_path}"

    try:
        with open(manifest_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return f"Error loading manifest: {e}"

    chunks = data.get("chunks", data) if isinstance(data, dict) else data
    if not isinstance(chunks, list):
        return "Error: Manifest does not contain a chunk list"

    return chunks


def _find_chunk(manifest: list[dict], chunk_id: str) -> dict | str:
    """Find a chunk by ID in a manifest."""
    for chunk in manifest:
        if chunk.get("chunk_id") == chunk_id:
            return chunk
    return f"Error: Chunk '{chunk_id}' not found in manifest"


def _merge_regions(
    match_indices: list[int], context: int, total_lines: int
) -> list[tuple[int, int]]:
    """Merge overlapping context regions around matches."""
    if not match_indices:
        return []

    regions = []
    start = max(0, match_indices[0] - context)
    end = min(total_lines - 1, match_indices[0] + context)

    for idx in match_indices[1:]:
        new_start = max(0, idx - context)
        new_end = min(total_lines - 1, idx + context)

        if new_start <= end + 1:
            # Overlapping or adjacent, merge
            end = new_end
        else:
            regions.append((start, end))
            start = new_start
            end = new_end

    regions.append((start, end))
    return regions
