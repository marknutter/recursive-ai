"""High-level chunk analysis using LLM providers.

Extracts content from chunks and dispatches to the configured
provider for analysis. Results are stored in the session state.
"""

from rlm import extractor, state
from rlm.providers import get_provider


def analyze_chunk(
    session_id: str,
    query: str,
    content: str,
    chunk_id: str,
    context: str = "",
    provider_name: str | None = None,
) -> dict:
    """Analyze a chunk of content and store the result.

    Args:
        session_id: The RLM session ID.
        query: The analysis query.
        content: The extracted content to analyze.
        chunk_id: Chunk identifier for result storage.
        context: Optional context about the chunk.
        provider_name: Override the provider (default: env var or "claude").

    Returns:
        Dict with 'status', 'chunk_id', 'findings', and 'provider'.
    """
    provider = get_provider(provider_name)

    findings = provider.analyze(content, query, context)

    if session_id:
        state.add_result(session_id, f"chunk_{chunk_id}", findings)

    return {
        "status": "ok",
        "chunk_id": chunk_id,
        "provider": provider.name,
        "model": provider.get_model(),
        "findings": findings,
    }


def analyze_file_range(
    session_id: str,
    query: str,
    filepath: str,
    start_line: int,
    end_line: int,
    chunk_id: str = "",
    provider_name: str | None = None,
) -> dict:
    """Extract a line range and analyze it.

    Convenience wrapper that extracts then analyzes.
    """
    content = extractor.extract_lines(filepath, start_line, end_line)
    if content.startswith("Error:"):
        return {"status": "error", "error": content}

    if not chunk_id:
        chunk_id = f"{filepath}:{start_line}-{end_line}"

    context = f"File: {filepath}, lines {start_line}-{end_line}"

    return analyze_chunk(
        session_id=session_id,
        query=query,
        content=content,
        chunk_id=chunk_id,
        context=context,
        provider_name=provider_name,
    )


def analyze_manifest_chunk(
    session_id: str,
    query: str,
    manifest_path: str,
    chunk_id: str,
    provider_name: str | None = None,
) -> dict:
    """Extract a chunk from a manifest and analyze it.

    Convenience wrapper for manifest-based extraction.
    """
    content = extractor.extract_chunk(manifest_path, chunk_id)
    if content.startswith("Error:"):
        return {"status": "error", "error": content}

    context = f"Chunk ID: {chunk_id}"

    return analyze_chunk(
        session_id=session_id,
        query=query,
        content=content,
        chunk_id=chunk_id,
        context=context,
        provider_name=provider_name,
    )
