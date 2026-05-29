#!/usr/bin/env python3
"""audit_todos.py — Floating-work audit: code TODO/FIXME/HACK/XXX markers.

Scans all source and config files for # TODO, # FIXME, # HACK, # XXX markers
(hash-prefixed comments only). Compares to docs/BACKLOG.md. Warns on any code
marker without a matching line referencing the marker's file:line.

For Python files, uses the tokenize module to find only true COMMENT tokens
(not markers embedded in string literals or docstrings).

Excluded: .venv/, node_modules/, .git/, .claude/ subtree (waves, worktrees,
run-archives), test fixture directories.

Exit code: 0 always (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_todos.py [--repo /path/to/repo]

Output:
  UNTRACKED: <file>:<line>  <marker>: <text>
  (one line per untracked marker; empty output means all are in BACKLOG.md)
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
from pathlib import Path

# Marker keywords (case-insensitive) that must appear as the FIRST word
# in a comment (after the leading '#').
_MARKER_WORDS = frozenset(["todo", "fixme", "hack", "xxx"])
_FIRST_WORD_RE = re.compile(r"^(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

# Directories to exclude (any path component matching these is skipped)
EXCLUDE_DIR_PARTS = frozenset({
    ".venv",
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    "worktrees",    # .claude/worktrees/ — worktree copies of the repo
})

# Top-level path prefixes to exclude (relative to repo root, using forward slash)
EXCLUDE_PATH_PREFIXES = (
    ".claude/",             # all .claude/ subtree (waves, run-archives, worktrees, etc.)
)

# Extensions to scan — source and config files only.
# Markdown (.md) files are excluded because they use TODO in prose, not as code markers.
SCAN_EXTENSIONS = frozenset({
    ".py",
    ".ts",
    ".vue",
    ".js",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
})

# Directory names indicating test fixture directories to skip
FIXTURE_DIR_PARTS = frozenset({"test_fixtures", "fixtures"})


def load_backlog(repo: Path) -> str:
    """Load docs/BACKLOG.md content, return empty string if missing."""
    backlog = repo / "docs" / "BACKLOG.md"
    if not backlog.exists():
        return ""
    return backlog.read_text(encoding="utf-8", errors="replace")


def is_excluded(path: Path, repo: Path) -> bool:
    """Return True if path should be skipped."""
    try:
        rel = path.relative_to(repo)
    except ValueError:
        return False

    rel_str = str(rel).replace("\\", "/")

    # Check top-level path prefix exclusions
    for prefix in EXCLUDE_PATH_PREFIXES:
        if rel_str.startswith(prefix) or rel_str == prefix.rstrip("/"):
            return True

    # Check individual path components
    for part in rel.parts:
        if part in EXCLUDE_DIR_PARTS:
            return True
        if part in FIXTURE_DIR_PARTS:
            return True

    return False


def _extract_marker_from_comment(comment_text: str) -> str | None:
    """Return marker kind if the comment starts with a marker keyword.

    comment_text: the text after the '#' character (stripped).
    """
    text = comment_text.lstrip()
    m = _FIRST_WORD_RE.match(text)
    if m:
        return m.group(1).upper()
    return None


def _find_markers_py(text: str, rel: str) -> list[tuple[str, int, str, str]]:
    """Find markers in a Python file using the tokenize module.

    Only COMMENT tokens are inspected — string literals and docstrings are
    completely ignored. This eliminates false positives from docstrings that
    describe or reference marker patterns.
    """
    results = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for tok_type, tok_string, start, _end, line in tokens:
            if tok_type != tokenize.COMMENT:
                continue
            # tok_string is the full comment including '#', e.g. "# TODO: fix"
            comment_text = tok_string.lstrip("#")
            marker = _extract_marker_from_comment(comment_text)
            if marker:
                lineno = start[0]
                results.append((rel, lineno, marker, line.rstrip()))
    except tokenize.TokenError:
        # File has a syntax error; fall back to line-by-line scan
        results = _find_markers_linebased(text, rel)
    return results


def _find_markers_linebased(text: str, rel: str) -> list[tuple[str, int, str, str]]:
    """Line-based fallback for non-Python files (YAML, TOML, shell, etc.).

    Looks for lines where '#' is the first non-whitespace character or where
    '#' appears as an inline comment (preceded by whitespace), and the comment
    starts immediately with a marker keyword.
    """
    results = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped:
            continue

        # Pure comment line: starts with '#'
        if stripped.startswith("#"):
            comment_text = stripped[1:]
            marker = _extract_marker_from_comment(comment_text)
            if marker:
                results.append((rel, lineno, marker, line.rstrip()))
            continue

        # Inline comment: look for ' #' preceded by whitespace
        # Only match if the '#' is not inside a quoted string
        # (heuristic: skip if unbalanced quotes before '#')
        for sep in ("  #", " #"):
            idx = line.rfind(sep)
            if idx == -1:
                continue
            before = line[:idx]
            # Skip if inside a string (odd number of unescaped quotes before hash)
            if before.count("'") % 2 != 0 or before.count('"') % 2 != 0:
                break
            comment_text = line[idx + len(sep) - 1:].lstrip("#")
            marker = _extract_marker_from_comment(comment_text)
            if marker:
                results.append((rel, lineno, marker, line.rstrip()))
            break

    return results


def find_markers(repo: Path) -> list[tuple[str, int, str, str]]:
    """Walk repo and find all TODO/FIXME/HACK/XXX code markers.

    Returns list of (rel_path, line_number, marker_kind, full_line).
    """
    results = []
    for path in sorted(repo.rglob("*")):
        if not path.is_file():
            continue
        if is_excluded(path, repo):
            continue
        if path.suffix not in SCAN_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(repo))

        if path.suffix == ".py":
            file_markers = _find_markers_py(text, rel)
        else:
            file_markers = _find_markers_linebased(text, rel)

        results.extend(file_markers)
    return results


def is_tracked_in_backlog(backlog_text: str, rel_path: str, lineno: int) -> bool:
    """Check if a file:line reference appears in BACKLOG.md.

    Matching strategies (checked in order):
    1. Exact "rel_path:lineno" substring anywhere in BACKLOG.md.
    2. "basename:lineno" substring anywhere in BACKLOG.md.
    """
    basename = Path(rel_path).name
    ref_full = f"{rel_path}:{lineno}"
    ref_base = f"{basename}:{lineno}"

    for line in backlog_text.splitlines():
        if ref_full in line:
            return True
        if ref_base in line:
            return True

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None,
                        help="Path to repo root (default: auto-detect from script location)")
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        # Script lives in tools/, repo is one level up
        repo = Path(__file__).resolve().parent.parent

    backlog_text = load_backlog(repo)
    if not backlog_text:
        print("WARNING: docs/BACKLOG.md not found — all markers will appear untracked",
              file=sys.stderr)

    markers = find_markers(repo)
    untracked = []
    for rel_path, lineno, kind, line_text in markers:
        if not is_tracked_in_backlog(backlog_text, rel_path, lineno):
            untracked.append((rel_path, lineno, kind, line_text))

    for rel_path, lineno, kind, line_text in untracked:
        print(f"UNTRACKED: {rel_path}:{lineno}  {kind}: {line_text.strip()[:120]}")

    if untracked:
        print(f"\nSummary: {len(untracked)} untracked marker(s) out of {len(markers)} total",
              file=sys.stderr)
    else:
        if markers:
            print(f"OK: all {len(markers)} marker(s) are referenced in docs/BACKLOG.md",
                  file=sys.stderr)
        else:
            print("OK: no TODO/FIXME/HACK/XXX markers found", file=sys.stderr)

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
