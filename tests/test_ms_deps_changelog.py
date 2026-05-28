"""
tests/test_ms_deps_changelog.py — unit tests for tools/ms_deps/changelog.py

All tests are offline: urllib.request.urlopen (via the module's _fetch_url
wrapper) is mocked to avoid any real network requests.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Make sure the tools package is importable when pytest is run from the repo root.
import importlib
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.ms_deps.changelog import (
    _excerpt,
    _extract_github_owner_repo,
    _fetch_url,
    _pypi_metadata,
    _resolve_url,
    fetch_changelog,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pypi_meta(
    project_urls: dict | None = None,
    home_page: str = "",
    source_url: str = "",
) -> dict:
    """Build a minimal PyPI metadata dict."""
    urls = project_urls or {}
    if source_url:
        urls.setdefault("Source", source_url)
    return {
        "info": {
            "project_urls": urls,
            "home_page": home_page,
        }
    }


def _mock_response(body: str, status: int = 200):
    """Return a context-manager mock that mimics urllib's HTTP response."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body.encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# _fetch_url
# ---------------------------------------------------------------------------

class TestFetchUrl(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_200_returns_body(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response("hello world")
        result = _fetch_url("https://example.com/")
        self.assertEqual(result, "hello world")

    @patch("urllib.request.urlopen")
    def test_404_returns_none(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response("not found", status=404)
        result = _fetch_url("https://example.com/")
        self.assertIsNone(result)

    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout"))
    def test_url_error_returns_none(self, mock_urlopen):
        result = _fetch_url("https://example.com/")
        self.assertIsNone(result)

    @patch("urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_os_error_returns_none(self, mock_urlopen):
        result = _fetch_url("https://example.com/")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _extract_github_owner_repo
# ---------------------------------------------------------------------------

class TestExtractGithubOwnerRepo(unittest.TestCase):

    def test_standard_url(self):
        self.assertEqual(
            _extract_github_owner_repo("https://github.com/encode/starlette"),
            ("encode", "starlette"),
        )

    def test_url_with_trailing_path(self):
        self.assertEqual(
            _extract_github_owner_repo("https://github.com/encode/starlette/issues"),
            ("encode", "starlette"),
        )

    def test_strips_git_suffix(self):
        self.assertEqual(
            _extract_github_owner_repo("https://github.com/encode/starlette.git"),
            ("encode", "starlette"),
        )

    def test_non_github_returns_none(self):
        self.assertIsNone(_extract_github_owner_repo("https://gitlab.com/owner/repo"))

    def test_empty_returns_none(self):
        self.assertIsNone(_extract_github_owner_repo(""))

    def test_none_input(self):
        self.assertIsNone(_extract_github_owner_repo(None))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scenario 1: project_urls.Changelog URL is used directly
# ---------------------------------------------------------------------------

class TestChangelogUrlFromProjectUrls(unittest.TestCase):

    def _pypi_with_changelog(self):
        return _make_pypi_meta(
            project_urls={"Changelog": "https://example.com/CHANGELOG"}
        )

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_changelog_url_preferred(self, mock_meta, mock_fetch):
        """When project_urls.Changelog is set and resolves, that URL is used."""
        mock_meta.return_value = self._pypi_with_changelog()
        mock_fetch.return_value = "## v1.2.0\n- Fixed a bug\n"

        output = fetch_changelog("mypkg", "1.1.0", "1.2.0")

        # The first _fetch_url call should be for the Changelog URL.
        first_call_url = mock_fetch.call_args_list[0][0][0]
        self.assertEqual(first_call_url, "https://example.com/CHANGELOG")
        self.assertIn("Release notes: https://example.com/CHANGELOG", output)
        self.assertIn("Fixed a bug", output)

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_release_notes_key_fallback(self, mock_meta, mock_fetch):
        """When no Changelog key, Release notes key is tried."""
        meta = _make_pypi_meta(
            project_urls={"Release notes": "https://example.com/releases"}
        )
        mock_meta.return_value = meta
        mock_fetch.return_value = "v1.2.0 released"

        output = fetch_changelog("mypkg", "1.1.0", "1.2.0")
        self.assertIn("Release notes: https://example.com/releases", output)


# ---------------------------------------------------------------------------
# Scenario 2: No Changelog key, but GitHub home_page → GitHub releases URL
# ---------------------------------------------------------------------------

class TestGithubReleasesUrl(unittest.TestCase):

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_github_releases_tag_constructed(self, mock_meta, mock_fetch):
        """When there's no Changelog URL but home_page is GitHub, the releases
        tag URL for v<new-version> is tried."""
        meta = _make_pypi_meta(home_page="https://github.com/encode/starlette")
        mock_meta.return_value = meta

        # No Changelog/Release notes/Releases URL → None, None, None
        # Then the GitHub releases/tag URL → body
        def side_effect(url: str):
            if "releases/tag/v1.2.0" in url:
                return "<html>Release page</html>"
            return None

        mock_fetch.side_effect = side_effect

        output = fetch_changelog("starlette", "1.1.0", "1.2.0")
        self.assertIn(
            "https://github.com/encode/starlette/releases/tag/v1.2.0", output
        )
        self.assertIn("Release notes:", output)

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_github_releases_tag_without_v_prefix(self, mock_meta, mock_fetch):
        """Falls back to tag without 'v' prefix when v-prefixed tag is missing."""
        meta = _make_pypi_meta(home_page="https://github.com/encode/starlette")
        mock_meta.return_value = meta

        def side_effect(url: str):
            if "releases/tag/1.2.0" in url and "releases/tag/v1.2.0" not in url:
                return "<html>Release page no v</html>"
            return None

        mock_fetch.side_effect = side_effect
        output = fetch_changelog("starlette", "1.1.0", "1.2.0")
        self.assertIn(
            "https://github.com/encode/starlette/releases/tag/1.2.0", output
        )


# ---------------------------------------------------------------------------
# Scenario 3: All resolution attempts return 404 → "No changelog found"
# ---------------------------------------------------------------------------

class TestNoChangelogFound(unittest.TestCase):

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_all_404_yields_no_changelog(self, mock_meta, mock_fetch):
        """When every URL attempt fails, output says 'No changelog found.'"""
        meta = _make_pypi_meta(
            project_urls={"Changelog": "https://example.com/missing"},
            home_page="https://github.com/encode/starlette",
        )
        mock_meta.return_value = meta
        mock_fetch.return_value = None  # All requests 404/fail.

        output = fetch_changelog("starlette", "1.1.0", "1.2.0")
        self.assertIn("No changelog found.", output)
        self.assertIn("starlette 1.1.0 → 1.2.0", output)

    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_pypi_unavailable_yields_no_changelog(self, mock_meta):
        """When PyPI itself is unreachable, output says 'No changelog found.'"""
        mock_meta.return_value = None

        output = fetch_changelog("mypkg", "0.1.0", "0.2.0")
        self.assertIn("No changelog found.", output)

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_no_project_urls_no_homepage(self, mock_meta, mock_fetch):
        """No project_urls, no home_page → no changelog."""
        meta = _make_pypi_meta()  # empty project_urls, empty home_page
        mock_meta.return_value = meta
        mock_fetch.return_value = None

        output = fetch_changelog("bare-pkg", "1.0.0", "1.0.1")
        self.assertIn("No changelog found.", output)


# ---------------------------------------------------------------------------
# Scenario 4: Network error (URLError) → "No changelog found" (no crash)
# ---------------------------------------------------------------------------

class TestNetworkError(unittest.TestCase):

    @patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("network unreachable"),
    )
    def test_urlerror_does_not_crash(self, mock_urlopen):
        """urllib.error.URLError from _fetch_url is handled; no exception propagates."""
        # _pypi_metadata calls _fetch_url which calls urlopen — will raise URLError.
        output = fetch_changelog("starlette", "1.1.0", "1.2.0")
        self.assertIn("No changelog found.", output)

    @patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url="https://pypi.org/pypi/starlette/json",
            code=500,
            msg="Internal Server Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,  # type: ignore[arg-type]
        ),
    )
    def test_httperror_does_not_crash(self, mock_urlopen):
        """urllib.error.HTTPError is handled gracefully."""
        output = fetch_changelog("starlette", "1.1.0", "1.2.0")
        self.assertIn("No changelog found.", output)


# ---------------------------------------------------------------------------
# Scenario 5: Excerpt truncation at ~200 lines
# ---------------------------------------------------------------------------

class TestExcerptTruncation(unittest.TestCase):

    def test_short_body_not_truncated(self):
        body = "\n".join(f"line {i}" for i in range(50))
        result = _excerpt(body, max_lines=200)
        self.assertEqual(result, body)
        self.assertNotIn("truncated", result)

    def test_long_body_truncated(self):
        body = "\n".join(f"line {i}" for i in range(500))
        result = _excerpt(body, max_lines=200)
        lines = result.splitlines()
        # Last line should be the truncation notice.
        self.assertIn("truncated at 200 lines", lines[-1])
        # Exactly 201 output lines: 200 content + 1 truncation note.
        self.assertEqual(len(lines), 201)

    def test_exactly_200_lines_not_truncated(self):
        body = "\n".join(f"line {i}" for i in range(200))
        result = _excerpt(body, max_lines=200)
        self.assertNotIn("truncated", result)

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_long_changelog_file_is_truncated_in_output(self, mock_meta, mock_fetch):
        """When a raw CHANGELOG.md is returned, the excerpt in the output is capped."""
        meta = _make_pypi_meta(home_page="https://github.com/encode/starlette")
        mock_meta.return_value = meta

        long_body = "\n".join(f"## Version {i}.0.0" for i in range(500))

        def side_effect(url: str):
            if "raw.githubusercontent.com" in url and "CHANGELOG" in url:
                return long_body
            return None

        mock_fetch.side_effect = side_effect

        output = fetch_changelog("starlette", "1.1.0", "1.2.0")
        self.assertIn("truncated at 200 lines", output)
        # Ensure we do not include all 500 lines.
        self.assertNotIn("## Version 499.0.0", output)


# ---------------------------------------------------------------------------
# CLI entry point smoke test
# ---------------------------------------------------------------------------

class TestMainCli(unittest.TestCase):

    @patch("tools.ms_deps.changelog._fetch_url")
    @patch("tools.ms_deps.changelog._pypi_metadata")
    def test_main_returns_zero(self, mock_meta, mock_fetch):
        mock_meta.return_value = _make_pypi_meta(
            project_urls={"Changelog": "https://example.com/CHANGELOG"}
        )
        mock_fetch.return_value = "## v1.0.0\n- stuff\n"

        captured = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(captured):
            rc = main(["--package", "mypkg", "--from", "0.9.0", "--to", "1.0.0"])

        self.assertEqual(rc, 0)
        self.assertIn("mypkg 0.9.0 → 1.0.0", captured.getvalue())

    @patch("tools.ms_deps.changelog._fetch_url", return_value=None)
    @patch("tools.ms_deps.changelog._pypi_metadata", return_value=None)
    def test_main_no_changelog_exits_zero(self, mock_meta, mock_fetch):
        """Even with no changelog found, exit code is 0 (best-effort tool)."""
        captured = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(captured):
            rc = main(["--package", "ghost", "--from", "1.0.0", "--to", "2.0.0"])

        self.assertEqual(rc, 0)
        self.assertIn("No changelog found.", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
