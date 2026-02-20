"""URL content fetching for RLM memory ingestion.

Fetches content from URLs (web pages, GitHub repos, raw files, API specs)
and prepares it for storage in the RLM memory system.

Uses only Python stdlib (urllib, html.parser) to keep dependencies minimal.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# Limits
MAX_CONTENT_BYTES = 512_000  # 500KB per page
MAX_REPO_FILES = 50  # Max files to ingest from a repo
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "RLM/0.1 (Recursive Language Model memory ingestion)"


class _HTMLTextExtractor(HTMLParser):
    """Extract readable text from HTML, stripping tags and boilerplate."""

    # Tags whose content we skip entirely
    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0
        self._in_pre = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "pre":
            self._in_pre = True
        # Block-level tags get line breaks
        if tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
                    "li", "tr", "blockquote", "section", "article"):
            self._pieces.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "pre":
            self._in_pre = False
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                    "blockquote", "section", "article"):
            self._pieces.append("\n")

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_pre:
            self._pieces.append(data)
        else:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        # Collapse whitespace runs (but preserve intentional newlines)
        lines = raw.splitlines()
        cleaned = []
        for line in lines:
            stripped = " ".join(line.split())
            cleaned.append(stripped)

        # Collapse multiple blank lines
        result = []
        prev_blank = False
        for line in cleaned:
            if not line:
                if not prev_blank:
                    result.append("")
                prev_blank = True
            else:
                result.append(line)
                prev_blank = False

        return "\n".join(result).strip()


def html_to_text(html: str) -> str:
    """Convert HTML to readable plain text."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


# --- URL detection ---


def is_url(text: str) -> bool:
    """Check if a string looks like a URL (has http:// or https:// protocol)."""
    return text.strip().startswith(("http://", "https://"))


# --- URL type detection ---

class URLType:
    GITHUB_REPO = "github_repo"
    GITHUB_FILE = "github_file"
    RAW_FILE = "raw_file"
    HTML_PAGE = "html_page"


def detect_url_type(url: str) -> str:
    """Classify a URL by type to determine the fetch strategy."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.rstrip("/")

    # GitHub repository (not a specific file)
    if host in ("github.com", "www.github.com"):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 2:
            # github.com/user/repo
            return URLType.GITHUB_REPO
        if len(parts) >= 4 and parts[2] in ("blob", "tree"):
            # github.com/user/repo/blob/branch/path
            return URLType.GITHUB_FILE

    # Raw file URLs
    if host == "raw.githubusercontent.com":
        return URLType.RAW_FILE

    # Files with known extensions
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".txt", ".json", ".yaml", ".yml", ".xml", ".csv",
               ".py", ".js", ".ts", ".go", ".rs", ".rb", ".java", ".sh"):
        return URLType.RAW_FILE

    return URLType.HTML_PAGE


def _github_file_to_raw_url(url: str) -> str:
    """Convert a GitHub blob URL to a raw.githubusercontent.com URL."""
    parsed = urlparse(url)
    path = parsed.path
    # /user/repo/blob/branch/path -> /user/repo/branch/path
    path = re.sub(r"/blob/", "/", path, count=1)
    return f"https://raw.githubusercontent.com{path}"


# --- Fetching ---

def fetch_url(url: str) -> tuple[str, str]:
    """Fetch content from a URL.

    Returns (content_text, content_type) where content_type is 'text' or 'html'.
    Raises ValueError on fetch errors.
    """
    url_type = detect_url_type(url)

    if url_type == URLType.GITHUB_FILE:
        url = _github_file_to_raw_url(url)
        url_type = URLType.RAW_FILE

    req = Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            content_type_header = resp.headers.get("Content-Type", "")
            raw = resp.read(MAX_CONTENT_BYTES)

            # Detect encoding
            charset = "utf-8"
            if "charset=" in content_type_header:
                charset = content_type_header.split("charset=")[-1].split(";")[0].strip()

            text = raw.decode(charset, errors="replace")

            if "html" in content_type_header.lower() or url_type == URLType.HTML_PAGE:
                return html_to_text(text), "html"
            else:
                return text, "text"

    except HTTPError as e:
        raise ValueError(f"HTTP error fetching {url}: {e.code} {e.reason}") from e
    except URLError as e:
        raise ValueError(f"URL error fetching {url}: {e.reason}") from e
    except Exception as e:
        raise ValueError(f"Error fetching {url}: {e}") from e


def fetch_github_repo(url: str, depth: int = 2) -> list[dict]:
    """Clone a GitHub repo and extract key files for memory ingestion.

    Returns a list of dicts, each with:
        - content: str (the file/overview content)
        - source_name: str (the file path or "repo overview")
        - summary: str (auto-generated summary)
        - extra_tags: list[str] (additional tags for this entry)

    Uses shallow clone (--depth 1) and cleans up temp dir afterward.
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) < 2:
        raise ValueError(f"Invalid GitHub repo URL: {url}")

    owner, repo_name = path_parts[0], path_parts[1]
    # Strip .git suffix if present
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    clone_url = f"https://github.com/{owner}/{repo_name}.git"

    tmpdir = tempfile.mkdtemp(prefix="rlm-repo-")

    try:
        # Shallow clone
        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, tmpdir],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise ValueError(
                f"Failed to clone {clone_url}: {result.stderr.strip()}"
            )

        entries = []

        # 1. Build repo overview (file tree + README)
        overview_parts = [f"# {owner}/{repo_name}\n"]

        # File tree
        tree_lines = _build_file_tree(tmpdir, max_depth=depth)
        overview_parts.append("## File Structure\n```")
        overview_parts.append("\n".join(tree_lines))
        overview_parts.append("```\n")

        # README
        readme_content = _find_and_read_readme(tmpdir)
        if readme_content:
            overview_parts.append("## README\n")
            overview_parts.append(readme_content)

        entries.append({
            "content": "\n".join(overview_parts),
            "source_name": f"github:{owner}/{repo_name}",
            "summary": f"{owner}/{repo_name} repository overview",
            "extra_tags": [f"repo:{repo_name}", "github", "overview"],
        })

        # 2. Collect key files (config, docs, main entry points)
        key_files = _find_key_files(tmpdir, max_files=MAX_REPO_FILES)
        for rel_path, content in key_files:
            entries.append({
                "content": content,
                "source_name": f"github:{owner}/{repo_name}/{rel_path}",
                "summary": f"{repo_name}/{rel_path}",
                "extra_tags": [f"repo:{repo_name}", "github", "source-file"],
            })

        return entries

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _build_file_tree(root: str, max_depth: int = 2) -> list[str]:
    """Build an indented file tree, excluding .git and common noise."""
    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".tox", ".eggs",
                 "dist", "build", ".mypy_cache", ".pytest_cache", "venv",
                 ".venv", "env", ".env"}
    SKIP_FILES = {".DS_Store", "Thumbs.db"}

    lines = []

    def _walk(path: str, prefix: str, current_depth: int):
        if current_depth > max_depth:
            return

        try:
            entries = sorted(os.listdir(path))
        except OSError:
            return

        dirs = []
        files = []
        for name in entries:
            full = os.path.join(path, name)
            if os.path.isdir(full):
                if name not in SKIP_DIRS:
                    dirs.append(name)
            else:
                if name not in SKIP_FILES:
                    files.append(name)

        for name in files:
            lines.append(f"{prefix}{name}")

        for name in dirs:
            lines.append(f"{prefix}{name}/")
            _walk(os.path.join(path, name), prefix + "  ", current_depth + 1)

    _walk(root, "", 0)
    return lines


def _find_and_read_readme(repo_dir: str) -> str | None:
    """Find and read the README file in a repo."""
    candidates = ["README.md", "README.rst", "README.txt", "README",
                   "readme.md", "Readme.md"]
    for name in candidates:
        path = os.path.join(repo_dir, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", errors="replace") as f:
                    content = f.read(MAX_CONTENT_BYTES)
                return content
            except OSError:
                continue
    return None


def _find_key_files(
    repo_dir: str,
    max_files: int = 50,
) -> list[tuple[str, str]]:
    """Find key files in a repo worth ingesting.

    Returns list of (relative_path, content) tuples.
    Prioritizes: config files, entry points, docs.
    """
    # Priority filenames (always include if present)
    PRIORITY_NAMES = {
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "Makefile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        ".env.example", "setup.py", "setup.cfg",
        "CONTRIBUTING.md", "CHANGELOG.md", "LICENSE",
    }

    # File extensions worth ingesting (source code, docs, config)
    GOOD_EXTENSIONS = {
        ".py", ".js", ".ts", ".go", ".rs", ".rb", ".java", ".kt",
        ".md", ".rst", ".txt",
        ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".sh", ".bash",
    }

    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".tox", ".eggs",
                 "dist", "build", ".mypy_cache", ".pytest_cache", "venv",
                 ".venv", "env", ".env", "vendor", "third_party"}

    MAX_FILE_SIZE = 100_000  # 100KB per file

    collected: list[tuple[str, str, int]] = []  # (rel_path, content, priority)

    for dirpath, dirnames, filenames in os.walk(repo_dir):
        # Skip uninteresting directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = os.path.relpath(dirpath, repo_dir)
        if rel_dir == ".":
            rel_dir = ""

        for fname in filenames:
            rel_path = os.path.join(rel_dir, fname) if rel_dir else fname
            full_path = os.path.join(dirpath, fname)

            # Check file size
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            if size > MAX_FILE_SIZE or size == 0:
                continue

            ext = os.path.splitext(fname)[1].lower()
            priority = 2  # default: low

            if fname in PRIORITY_NAMES:
                priority = 0  # highest
            elif fname.lower().startswith("readme"):
                continue  # already handled in overview
            elif ext in GOOD_EXTENSIONS:
                priority = 1  # medium

                # Boost entry points
                if fname in ("main.py", "index.js", "index.ts", "main.go",
                              "main.rs", "lib.rs", "app.py", "app.js",
                              "server.py", "server.js", "cli.py"):
                    priority = 0
            else:
                continue  # skip unknown file types

            try:
                with open(full_path, "r", errors="replace") as f:
                    content = f.read(MAX_FILE_SIZE)
            except OSError:
                continue

            collected.append((rel_path, content, priority))

    # Sort by priority, then path
    collected.sort(key=lambda x: (x[2], x[0]))

    # Return up to max_files
    return [(path, content) for path, content, _ in collected[:max_files]]


def remember_url(
    url: str,
    tags: list[str] | None = None,
    summary: str | None = None,
    depth: int = 2,
) -> list[dict]:
    """Fetch URL content and store in RLM memory.

    Returns list of result dicts from memory.add_memory() calls.
    """
    from rlm import memory

    url_type = detect_url_type(url)
    user_tags = tags or []

    if url_type == URLType.GITHUB_REPO:
        repo_entries = fetch_github_repo(url, depth=depth)
        results = []
        for entry in repo_entries:
            all_tags = user_tags + entry["extra_tags"] + ["url-source"]
            result = memory.add_memory(
                content=entry["content"],
                tags=all_tags,
                source="url",
                source_name=entry["source_name"],
                summary=entry.get("summary") if not summary else summary,
            )
            results.append(result)
        return results
    else:
        content, content_type = fetch_url(url)
        if not content.strip():
            raise ValueError(f"No content retrieved from {url}")

        parsed = urlparse(url)
        domain = parsed.hostname or "unknown"
        all_tags = user_tags + ["url-source", domain]

        if summary is None:
            # Use first line of content as summary hint
            summary = None  # let memory.add_memory auto-generate

        result = memory.add_memory(
            content=content,
            tags=all_tags,
            source="url",
            source_name=url,
            summary=summary,
        )
        return [result]
