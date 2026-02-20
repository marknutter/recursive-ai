"""Tests for rlm.url_fetcher module."""

import os
import tempfile
import unittest

from rlm.url_fetcher import (
    URLType,
    _HTMLTextExtractor,
    _build_file_tree,
    _find_and_read_readme,
    _github_file_to_raw_url,
    detect_url_type,
    html_to_text,
    is_url,
)


class TestIsURL(unittest.TestCase):
    """Test URL auto-detection from protocol."""

    def test_https_url(self):
        assert is_url("https://example.com/page") is True

    def test_http_url(self):
        assert is_url("http://example.com/page") is True

    def test_plain_text(self):
        assert is_url("just some text to remember") is False

    def test_file_path(self):
        assert is_url("/home/user/file.txt") is False

    def test_url_with_whitespace(self):
        assert is_url("  https://example.com  ") is True

    def test_not_a_url(self):
        assert is_url("httpstuff is not a url") is False


class TestURLTypeDetection(unittest.TestCase):
    """Test URL type classification."""

    def test_github_repo(self):
        assert detect_url_type("https://github.com/user/repo") == URLType.GITHUB_REPO
        assert detect_url_type("https://github.com/user/repo/") == URLType.GITHUB_REPO
        assert detect_url_type("https://www.github.com/user/repo") == URLType.GITHUB_REPO

    def test_github_file(self):
        url = "https://github.com/user/repo/blob/main/src/app.py"
        assert detect_url_type(url) == URLType.GITHUB_FILE

        url = "https://github.com/user/repo/tree/main/src"
        assert detect_url_type(url) == URLType.GITHUB_FILE

    def test_raw_githubusercontent(self):
        url = "https://raw.githubusercontent.com/user/repo/main/README.md"
        assert detect_url_type(url) == URLType.RAW_FILE

    def test_raw_file_by_extension(self):
        assert detect_url_type("https://example.com/file.md") == URLType.RAW_FILE
        assert detect_url_type("https://example.com/data.json") == URLType.RAW_FILE
        assert detect_url_type("https://example.com/config.yaml") == URLType.RAW_FILE
        assert detect_url_type("https://example.com/script.py") == URLType.RAW_FILE
        assert detect_url_type("https://example.com/code.ts") == URLType.RAW_FILE

    def test_html_page(self):
        assert detect_url_type("https://docs.example.com/api") == URLType.HTML_PAGE
        assert detect_url_type("https://example.com/guide") == URLType.HTML_PAGE
        assert detect_url_type("https://example.com/page.html") == URLType.HTML_PAGE


class TestGitHubFileToRawURL(unittest.TestCase):
    """Test GitHub blob URL to raw URL conversion."""

    def test_basic_conversion(self):
        url = "https://github.com/user/repo/blob/main/src/app.py"
        expected = "https://raw.githubusercontent.com/user/repo/main/src/app.py"
        assert _github_file_to_raw_url(url) == expected

    def test_nested_path(self):
        url = "https://github.com/org/project/blob/v2/lib/core/engine.rs"
        expected = "https://raw.githubusercontent.com/org/project/v2/lib/core/engine.rs"
        assert _github_file_to_raw_url(url) == expected


class TestHTMLToText(unittest.TestCase):
    """Test HTML to plain text conversion."""

    def test_basic_html(self):
        html = "<p>Hello <b>world</b></p>"
        text = html_to_text(html)
        assert "Hello world" in text

    def test_strips_scripts(self):
        html = "<p>Content</p><script>alert('xss')</script><p>More</p>"
        text = html_to_text(html)
        assert "alert" not in text
        assert "Content" in text
        assert "More" in text

    def test_strips_styles(self):
        html = "<style>.foo { color: red; }</style><p>Visible text</p>"
        text = html_to_text(html)
        assert "color" not in text
        assert "Visible text" in text

    def test_strips_nav(self):
        html = "<nav><a>Home</a><a>About</a></nav><main><p>Main content</p></main>"
        text = html_to_text(html)
        assert "Home" not in text
        assert "Main content" in text

    def test_preserves_line_breaks(self):
        html = "<h1>Title</h1><p>Para 1</p><p>Para 2</p>"
        text = html_to_text(html)
        lines = [l for l in text.splitlines() if l.strip()]
        assert len(lines) >= 2

    def test_collapses_whitespace(self):
        html = "<p>  lots   of   spaces  </p>"
        text = html_to_text(html)
        assert "lots of spaces" in text

    def test_empty_html(self):
        assert html_to_text("") == ""

    def test_nested_skip_tags(self):
        html = "<footer><div><script>bad</script>Footer text</div></footer><p>Good</p>"
        text = html_to_text(html)
        assert "bad" not in text
        assert "Footer text" not in text
        assert "Good" in text


class TestBuildFileTree(unittest.TestCase):
    """Test file tree builder."""

    def test_simple_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files and dirs
            os.makedirs(os.path.join(tmpdir, "src"))
            open(os.path.join(tmpdir, "README.md"), "w").close()
            open(os.path.join(tmpdir, "src", "main.py"), "w").close()

            lines = _build_file_tree(tmpdir, max_depth=2)
            text = "\n".join(lines)
            assert "README.md" in text
            assert "src/" in text
            assert "main.py" in text

    def test_skips_git_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".git", "objects"))
            open(os.path.join(tmpdir, "file.txt"), "w").close()

            lines = _build_file_tree(tmpdir, max_depth=2)
            text = "\n".join(lines)
            assert ".git" not in text
            assert "file.txt" in text

    def test_depth_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "a", "b", "c"))
            open(os.path.join(tmpdir, "a", "b", "c", "deep.txt"), "w").close()

            lines_shallow = _build_file_tree(tmpdir, max_depth=1)
            lines_deep = _build_file_tree(tmpdir, max_depth=3)

            # Shallow shouldn't reach deep.txt
            assert "deep.txt" not in "\n".join(lines_shallow)
            # Deep should
            assert "deep.txt" in "\n".join(lines_deep)


class TestFindReadme(unittest.TestCase):
    """Test README file finder."""

    def test_finds_readme_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            readme_path = os.path.join(tmpdir, "README.md")
            with open(readme_path, "w") as f:
                f.write("# My Project\nDescription here.")

            content = _find_and_read_readme(tmpdir)
            assert content is not None
            assert "My Project" in content

    def test_finds_readme_rst(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "README.rst"), "w") as f:
                f.write("My Project\n==========\n")

            content = _find_and_read_readme(tmpdir)
            assert content is not None
            assert "My Project" in content

    def test_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert _find_and_read_readme(tmpdir) is None


if __name__ == "__main__":
    unittest.main()
