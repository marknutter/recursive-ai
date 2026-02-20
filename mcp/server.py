#!/usr/bin/env python3
"""
RLM MCP Server

Exposes RLM memory operations as MCP tools so any MCP-compatible agent
(Claude Code, Cursor, etc.) can recall, store, and search memories natively
without requiring explicit /rlm invocations.

Usage:
    uv run python mcp/server.py

MCP config (.mcp.json):
    {
      "mcpServers": {
        "rlm": {
          "type": "stdio",
          "command": "uv",
          "args": ["run", "python", "mcp/server.py"]
        }
      }
    }
"""

import json
import sys
import subprocess
from pathlib import Path

# Project root is parent of mcp/
PROJECT_ROOT = Path(__file__).parent.parent


def run_rlm(*args) -> str:
    """Run an rlm CLI command and return stdout."""
    result = subprocess.run(
        ["uv", "run", "rlm", *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0 and result.stderr:
        return f"Error: {result.stderr.strip()}"
    return result.stdout.strip()


def handle_tool_call(name: str, arguments: dict) -> str:
    """Dispatch a tool call to the appropriate rlm command."""

    if name == "rlm_recall":
        query = arguments.get("query", "")
        tags = arguments.get("tags", "")
        max_results = arguments.get("max_results", 10)
        cmd = ["recall", query, "--deep", "--max", str(max_results)]
        if tags:
            cmd += ["--tags", tags]
        return run_rlm(*cmd)

    elif name == "rlm_remember":
        content = arguments.get("content", "")
        tags = arguments.get("tags", "")
        summary = arguments.get("summary", "")
        cmd = ["remember", content]
        if tags:
            cmd += ["--tags", tags]
        if summary:
            cmd += ["--summary", summary]
        return run_rlm(*cmd)

    elif name == "rlm_memory_list":
        tags = arguments.get("tags", "")
        limit = arguments.get("limit", 20)
        cmd = ["memory-list", "--limit", str(limit)]
        if tags:
            cmd += ["--tags", tags]
        return run_rlm(*cmd)

    elif name == "rlm_memory_extract":
        entry_id = arguments.get("entry_id", "")
        grep = arguments.get("grep", "")
        context = arguments.get("context", 3)
        cmd = ["memory-extract", entry_id]
        if grep:
            cmd += ["--grep", grep, "--context", str(context)]
        return run_rlm(*cmd)

    elif name == "rlm_remember_url":
        url = arguments.get("url", "")
        tags = arguments.get("tags", "")
        summary = arguments.get("summary", "")
        depth = arguments.get("depth", 2)
        cmd = ["remember", url, "--depth", str(depth)]
        if tags:
            cmd += ["--tags", tags]
        if summary:
            cmd += ["--summary", summary]
        return run_rlm(*cmd)

    elif name == "rlm_forget":
        entry_id = arguments.get("entry_id", "")
        return run_rlm("forget", entry_id)

    else:
        return f"Unknown tool: {name}"


# MCP tool definitions
TOOLS = [
    {
        "name": "rlm_recall",
        "description": (
            "Search RLM persistent memory for past conversations, decisions, and knowledge. "
            "Use this when the user asks about previous work, past decisions, or anything "
            "that might have been discussed in a prior session. Also use proactively when "
            "starting work on a topic — check if there's relevant prior context first. "
            "Returns matching memory entries with relevance scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — keywords or phrases to search for in memory",
                },
                "tags": {
                    "type": "string",
                    "description": "Optional comma-separated tags to filter by (e.g. 'conversation,project-name')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "rlm_remember",
        "description": (
            "Store a piece of knowledge or decision in RLM persistent memory for future recall. "
            "Use this to save important findings, architectural decisions, or context that "
            "should survive across sessions. Provide descriptive tags and a clear summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content to store in memory",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags for categorization (e.g. 'architecture,auth,decision')",
                },
                "summary": {
                    "type": "string",
                    "description": "Short description of what this memory contains (under 80 chars)",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "rlm_memory_list",
        "description": (
            "Browse the RLM memory store — list entries with their IDs, summaries, tags, and sizes. "
            "Use to get an overview of what's in memory, or to find entries by tag."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "string",
                    "description": "Optional comma-separated tags to filter by",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to show (default: 20)",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "rlm_memory_extract",
        "description": (
            "Extract the content of a specific memory entry by ID. Optionally grep for specific "
            "patterns within the entry. Use after rlm_recall returns entry IDs to get full content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "The memory entry ID (e.g. 'm_abc123def456')",
                },
                "grep": {
                    "type": "string",
                    "description": "Optional regex pattern to search within the entry",
                },
                "context": {
                    "type": "integer",
                    "description": "Lines of context around grep matches (default: 3)",
                    "default": 3,
                },
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "rlm_remember_url",
        "description": (
            "Fetch content from a URL and store it in RLM persistent memory. "
            "Supports web pages (HTML converted to text), GitHub repositories "
            "(cloned and key files ingested), raw files, and API specs. "
            "For GitHub repos, creates multiple memory entries: one overview "
            "with README and file tree, plus entries for key source files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch and remember (web page, GitHub repo, raw file, etc.)",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags for categorization",
                },
                "summary": {
                    "type": "string",
                    "description": "Short description (auto-generated if omitted)",
                },
                "depth": {
                    "type": "integer",
                    "description": "Directory scan depth for GitHub repos (default: 2)",
                    "default": 2,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "rlm_forget",
        "description": "Delete a specific memory entry by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "The memory entry ID to delete",
                },
            },
            "required": ["entry_id"],
        },
    },
]


def send(obj: dict):
    """Write a JSON-RPC message to stdout."""
    print(json.dumps(obj), flush=True)


def handle_request(request: dict) -> dict | None:
    """Handle a JSON-RPC request and return a response."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "rlm", "version": "0.1.0"},
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result_text = handle_tool_call(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            },
        }

    elif method == "notifications/initialized":
        # No response needed for notifications
        return None

    else:
        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return None


def main():
    """Run the MCP server, reading JSON-RPC from stdin and writing to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response is not None:
            send(response)


if __name__ == "__main__":
    main()
