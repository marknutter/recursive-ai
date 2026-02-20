# Issue: Add URL content ingestion to `/rlm remember`

**Title:** feat: Add ability to remember contents from a URL (GitHub repos, docs, API docs, web pages)

## Summary

Enable `/rlm remember` to accept a URL as a source, automatically fetch its content, and store it in episodic memory. This extends the memory system beyond local text/files/stdin to support ingestion from the web.

## Motivation

Currently, `/rlm remember` only supports three input modes:
- Inline text content
- Local file (`--file PATH`)
- Stdin (`--stdin`)

Users frequently want to remember content from:
- **GitHub repositories** — clone and ingest README, key source files, project structure
- **Documentation sites** — API docs, library docs, framework guides
- **API references** — OpenAPI specs, REST endpoint docs
- **Web pages** — blog posts, technical articles, Stack Overflow answers
- **Raw content URLs** — GitHub raw files, Gists, Pastebin, etc.

Without URL support, users must manually fetch content, save it to a file, then run `rlm remember --file`. This feature removes that friction.

## Proposed Design

### CLI Interface

```bash
# Remember a single web page
rlm remember-url "https://docs.example.com/api" --tags "api,docs" --summary "Example API reference"

# Remember a GitHub repo (clones to temp dir, scans, and ingests key files)
rlm remember-url "https://github.com/user/repo" --tags "repo,project" --depth 2

# Remember with explicit content type hint
rlm remember-url "https://example.com/openapi.json" --type api-spec

# Also works as a flag on the existing remember command
rlm remember --url "https://docs.example.com/guide" --tags "guide"
```

### URL Type Detection & Handling

| URL Pattern | Strategy |
|---|---|
| `github.com/<user>/<repo>` | Clone to temp dir, run `rlm scan`, ingest README + key files |
| `github.com/<user>/<repo>/blob/...` | Fetch raw file content via raw.githubusercontent.com |
| `raw.githubusercontent.com/...` | Direct HTTP fetch |
| `*.json`, `*.yaml`, `*.yml` (API specs) | Fetch and store with structured tags |
| `*.md` files | Fetch and store as-is |
| General HTML pages | Fetch, convert HTML to readable text (strip nav/ads), store |
| Docs sites (known patterns) | Fetch page content, extract main content area |

### Storage

Each URL ingestion creates one or more memory entries:
- **Single page**: One memory entry with the page content, tagged with `url-source`, domain, and user-provided tags
- **GitHub repo**: Multiple entries — one for the repo overview (README + file tree) and optionally individual entries for key files, all linked by a shared `repo:<name>` tag

### New Module: `rlm/url_fetcher.py`

Core responsibilities:
1. URL type detection (GitHub repo vs. raw file vs. HTML page vs. API spec)
2. Content fetching (HTTP GET with proper User-Agent, redirects, error handling)
3. HTML-to-text conversion (strip markup, extract main content)
4. GitHub repo handling (shallow clone, scan, selective ingestion)
5. Content size management (chunking large pages, respecting memory limits)

### MCP Integration

New MCP tool: `rlm_remember_url`
```json
{
  "name": "rlm_remember_url",
  "description": "Fetch content from a URL and store it in RLM memory",
  "inputSchema": {
    "properties": {
      "url": { "type": "string", "description": "URL to fetch and remember" },
      "tags": { "type": "string", "description": "Comma-separated tags" },
      "summary": { "type": "string", "description": "Short description" },
      "depth": { "type": "integer", "description": "For repos: directory scan depth (default: 2)" }
    },
    "required": ["url"]
  }
}
```

## Implementation Plan

1. **`rlm/url_fetcher.py`** — New module for URL detection, fetching, and content extraction
2. **`rlm/cli.py`** — Add `remember-url` subcommand and `--url` flag to `remember`
3. **`rlm/memory.py`** — Add `add_memory_from_url()` convenience method
4. **`mcp/server.py`** — Add `rlm_remember_url` tool
5. **`skill/SKILL.md`** — Document the new URL remember capability
6. **Tests** — Unit tests for URL detection, content extraction, and integration tests

## Considerations

- **Rate limiting**: Respect robots.txt and add reasonable delays for multi-page fetches
- **Content size**: Cap individual page fetches at a reasonable limit (e.g., 500KB)
- **GitHub repos**: Use shallow clone (`--depth 1`) to minimize disk usage; clean up temp dirs
- **Dependencies**: Prefer stdlib (`urllib.request`) for basic HTTP; `html.parser` for HTML stripping. Avoid adding heavy dependencies.
- **Offline fallback**: If fetch fails, provide clear error message with the URL for manual retry
- **Security**: Validate URLs, reject private/local network addresses, sanitize content

## Labels

`enhancement`, `feature`, `memory`
