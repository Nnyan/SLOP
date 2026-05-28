"""
tools/ms_deps/changelog.py — best-effort changelog/release-notes fetcher.

Usage:
    python3 -m tools.ms_deps.changelog --package <name> --from <old> --to <new>

Fetches PyPI metadata to locate a changelog or release-notes URL, then
prints a markdown fragment with an excerpt (up to ~200 lines).  All network
errors are treated as "no changelog found" — this tool never crashes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Optional

# Per-request timeout in seconds.
_TIMEOUT = 5

# Maximum excerpt lines when fetching a changelog file.
_MAX_EXCERPT_LINES = 200

# PyPI JSON endpoint.
_PYPI_URL = "https://pypi.org/pypi/{package}/json"

# GitHub raw changelog paths to try (branch tried: main, then master).
_GITHUB_CHANGELOG_PATHS = [
    "CHANGELOG.md",
    "CHANGELOG.rst",
    "CHANGES.md",
    "CHANGES.rst",
    "HISTORY.md",
    "HISTORY.rst",
]
_GITHUB_BRANCHES = ["main", "master"]

# Order in which to try project_urls keys for a direct changelog link.
_URL_KEYS = ["Changelog", "Release notes", "Releases"]


def _fetch_url(url: str) -> Optional[str]:
    """
    Fetch *url* with a short timeout.  Returns the decoded body on HTTP 200,
    None for any non-200 response, and None (without raising) for any network
    or URL error.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ms-deps-changelog/1.0 (+https://github.com/Nnyan/SLOP)"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return None
    except Exception:  # noqa: BLE001 — never crash
        return None


def _pypi_metadata(package: str) -> Optional[dict]:
    """Return the parsed PyPI JSON for *package*, or None on failure."""
    url = _PYPI_URL.format(package=package)
    body = _fetch_url(url)
    if body is None:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _extract_github_owner_repo(url: str) -> Optional[tuple[str, str]]:
    """
    Extract (owner, repo) from a GitHub URL such as
    ``https://github.com/owner/repo`` or ``https://github.com/owner/repo/...``.
    Returns None if the URL is not GitHub.
    """
    if not url:
        return None
    m = re.match(r"https?://github\.com/([^/]+)/([^/?\s#]+)", url)
    if m:
        owner = m.group(1)
        repo = m.group(2)
        # Strip trailing .git if present.
        repo = re.sub(r"\.git$", "", repo)
        return owner, repo
    return None


def _resolve_url(package: str, new_version: str, metadata: dict) -> Optional[tuple[str, str]]:
    """
    Try to find a working URL for changelog/release notes.

    Returns a (url, body) pair where body is the fetched text (may be the
    full file or a redirect landing page), or None if nothing resolves.

    Resolution order:
    1. project_urls.Changelog / Release notes / Releases  (direct link)
    2. GitHub releases tag page for new_version
    3. Raw CHANGELOG.md / CHANGES.md on GitHub (main then master)
    """
    info = metadata.get("info", {})
    project_urls: dict = info.get("project_urls") or {}
    home_page: str = info.get("home_page") or ""
    source_url: str = project_urls.get("Source") or project_urls.get("source") or ""

    # 1. Direct project_urls keys.
    for key in _URL_KEYS:
        url = project_urls.get(key)
        if url:
            body = _fetch_url(url)
            if body is not None:
                return url, body

    # Determine GitHub owner/repo from home_page or Source URL.
    github_ref = _extract_github_owner_repo(home_page) or _extract_github_owner_repo(source_url)

    if github_ref:
        owner, repo = github_ref

        # 2. GitHub releases tag page.
        tag_url = f"https://github.com/{owner}/{repo}/releases/tag/v{new_version}"
        body = _fetch_url(tag_url)
        if body is not None:
            return tag_url, body

        # Also try without the leading "v".
        tag_url_nv = f"https://github.com/{owner}/{repo}/releases/tag/{new_version}"
        body = _fetch_url(tag_url_nv)
        if body is not None:
            return tag_url_nv, body

        # 3. Raw CHANGELOG.md / CHANGES.md on GitHub.
        for branch in _GITHUB_BRANCHES:
            for path in _GITHUB_CHANGELOG_PATHS:
                raw_url = (
                    f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
                )
                body = _fetch_url(raw_url)
                if body is not None:
                    return raw_url, body

    return None


def _excerpt(body: str, max_lines: int = _MAX_EXCERPT_LINES) -> str:
    """Return up to *max_lines* lines from *body*, with a truncation note."""
    lines = body.splitlines()
    if len(lines) <= max_lines:
        return body
    kept = lines[:max_lines]
    kept.append(f"... (truncated at {max_lines} lines)")
    return "\n".join(kept)


def fetch_changelog(package: str, old_version: str, new_version: str) -> str:
    """
    Return a markdown fragment describing where to find the changelog for
    *package* moving from *old_version* to *new_version*.

    Never raises.  Network failures produce "No changelog found."
    """
    header = f"### {package} {old_version} → {new_version}"

    meta = _pypi_metadata(package)
    if meta is None:
        return f"{header}\nNo changelog found.\n"

    result = _resolve_url(package, new_version, meta)
    if result is None:
        return f"{header}\nNo changelog found.\n"

    url, body = result
    excerpt_text = _excerpt(body)
    return f"{header}\nRelease notes: {url}\n\n{excerpt_text}\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.ms_deps.changelog",
        description="Fetch changelog / release-notes for a Python package version bump.",
    )
    parser.add_argument("--package", required=True, help="PyPI package name")
    parser.add_argument("--from", dest="from_version", required=True, metavar="OLD")
    parser.add_argument("--to", dest="to_version", required=True, metavar="NEW")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    output = fetch_changelog(args.package, args.from_version, args.to_version)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
