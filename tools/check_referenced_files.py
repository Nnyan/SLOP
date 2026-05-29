#!/usr/bin/env python3
"""check_referenced_files — Orphan-file detector + doc-tree auditor.

Wave S-48-TRACK-GATE Stream B: orphan detection for any tracked file.
Wave S-56 Stream C: extended doc-tree checks:
  - Broken Markdown links in docs/ (links pointing to non-existent files).
  - Orphan docs/ .md files with zero inbound refs older than 30 days.
  - Tracked docs/ .md files missing from docs/MAP.md.

For every file tracked by git, searches the rest of the repo for inbound
references (by basename or path fragment). A tracked file with zero inbound
references that is also older than 30 days and not in `.orphan-allowlist` is
flagged as a WARNING.

Exit code is always 0 — this check is warning-only, never blocking.

Usage
-----
  python3 tools/check_referenced_files.py       # run against repo root
  python3 tools/check_referenced_files.py --repo /path/to/repo

Allowlist format (.orphan-allowlist at repo root)
-------------------------------------------------
Each non-blank, non-comment line must follow this format:

    <glob>    # reason: <text>

Lines missing the reason comment are an error (forces intent documentation).
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Extensions of files that will be grepped for inbound references.
# Configurable via --grep-extensions flag.
DEFAULT_GREP_EXTENSIONS: list[str] = [
    ".md",
    ".yml",
    ".yaml",
    ".py",
    ".ts",
    ".vue",
    ".json",
    ".sh",
    ".toml",
    ".cfg",
    ".ini",
]

# Grace window: only flag files older than this many days.
GRACE_DAYS: int = 30

# Allowlist filename (relative to repo root).
ALLOWLIST_FILE: str = ".orphan-allowlist"


# ---------------------------------------------------------------------------
# Allowlist parsing
# ---------------------------------------------------------------------------

def load_allowlist(repo: Path) -> list[str]:
    """Parse .orphan-allowlist; return list of glob patterns.

    Raises SystemExit with a descriptive message if any non-blank, non-comment
    line is missing the required '# reason: ...' suffix.
    """
    path = repo / ALLOWLIST_FILE
    if not path.exists():
        return []

    patterns: list[str] = []
    errors: list[str] = []

    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Each entry must have '# reason: <text>'
        if "# reason:" not in line:
            errors.append(
                f"  {ALLOWLIST_FILE}:{lineno}: missing '# reason: ...' — "
                f"entry is: {line!r}"
            )
            continue
        glob_part = line.split("#")[0].strip()
        if glob_part:
            patterns.append(glob_part)

    if errors:
        print(
            f"ERROR: {ALLOWLIST_FILE} has entries missing a reason comment:",
            file=sys.stderr,
        )
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)

    return patterns


def is_allowlisted(rel_path: str, patterns: list[str]) -> bool:
    """Return True if rel_path matches any allowlist glob."""
    for pat in patterns:
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(
            Path(rel_path).name, pat
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_tracked_files(repo: Path) -> list[str]:
    """Return list of repo-relative paths for all tracked files."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    if result.returncode != 0:
        print(f"ERROR: git ls-files failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return [line for line in result.stdout.splitlines() if line.strip()]


def git_file_birth_epoch(repo: Path, rel_path: str) -> float | None:
    """Return the epoch timestamp when the file was first added to the repo.

    Uses `git log --diff-filter=A --follow` to find the commit that introduced
    the file.  Falls back to the oldest commit touching the file (using
    `--follow --reverse`) when `--diff-filter=A` returns nothing (this happens
    on the root/initial commit in some git versions).  Returns None only if the
    history cannot be determined at all.
    """
    # Primary: find the commit that added the file via diff-filter=A.
    result = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%at", "--follow", "--", rel_path],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    if result.returncode == 0:
        lines = result.stdout.strip().splitlines()
        if lines:
            try:
                return float(lines[0].strip())
            except ValueError:
                pass

    # Fallback: take the oldest commit touching the file (reverse log).
    # This handles cases where --diff-filter=A does not match the root commit.
    result2 = subprocess.run(
        ["git", "log", "--format=%at", "--follow", "--reverse", "--", rel_path],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    if result2.returncode != 0:
        return None
    lines2 = result2.stdout.strip().splitlines()
    if not lines2:
        return None
    try:
        return float(lines2[0].strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Reference scanning
# ---------------------------------------------------------------------------

def build_search_corpus(
    repo: Path,
    tracked_files: list[str],
    grep_extensions: list[str],
) -> list[Path]:
    """Return absolute paths of files that will be grepped for references."""
    corpus: list[Path] = []
    ext_set = set(grep_extensions)
    for rel in tracked_files:
        p = repo / rel
        if p.suffix in ext_set:
            corpus.append(p)
    return corpus


def has_inbound_reference(
    rel_path: str,
    corpus: list[Path],
    subject_abs: Path,
) -> bool:
    """Return True if any corpus file mentions rel_path by basename or fragment.

    Strategy: search for both the full relative path and the basename.
    Self-references (the file itself) are excluded.
    """
    basename = Path(rel_path).name

    # We search both the full relative path and the bare basename.
    needles: list[str] = list({basename, rel_path})

    for candidate in corpus:
        if candidate == subject_abs:
            continue
        try:
            text = candidate.read_text(errors="replace")
        except OSError:
            continue
        for needle in needles:
            if needle in text:
                return True
    return False


# ---------------------------------------------------------------------------
# Doc-tree checks (wave S-56 Stream C)
# ---------------------------------------------------------------------------

# Regex for Markdown link targets: [text](target) — captures the target.
# Excludes http(s):// URLs and anchors-only (#section).
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')

# Regex for file paths in backtick spans, e.g. `docs/foo.md` or `tools/bar.py`.
# Matches any backtick-quoted token that looks like a relative file path
# (starts with a word char or '.', contains '/', ends with a file extension).
_BACKTICK_PATH_RE = re.compile(r'`([a-zA-Z0-9_.][^`]*\.[a-zA-Z0-9]{1,10})`')


def _resolve_md_link(link_target: str, source_file: Path, repo: Path) -> Path | None:
    """Resolve a Markdown link target to an absolute path, or None if not resolvable.

    Skips:
    - http/https URLs
    - mailto: links
    - Anchor-only links (#section)
    - Links with URL fragments — strips the fragment and resolves the file part.
    """
    # Strip leading/trailing whitespace.
    target = link_target.strip()

    # Skip external links and anchors-only.
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None

    # Strip URL-encoded parts and fragment (#...) from the path.
    if "#" in target:
        target = target.split("#")[0]
    if not target:
        return None

    # URL-decode (e.g. %20 → space).
    target = urllib.parse.unquote(target)

    # Resolve relative to the source file's directory.
    resolved = (source_file.parent / target).resolve()
    return resolved


def _is_likely_file_path(token: str) -> bool:
    """Return True if *token* looks like a relative filesystem path.

    Heuristic filters (all must pass):
    - Must contain '/' (exclude simple names like ``foo.py`` that are ambiguous).
    - Must NOT start with a digit (excludes version strings like ``1.2.3/...``).
    - Must NOT contain spaces (commands like ``sudo ./install.sh`` are not paths).
    - Must NOT contain '<' or '>' (template placeholders).
    - Must NOT contain '*' or '?' or '{' (glob patterns).
    - Must NOT contain ':' or '\\n' (shell commands, multi-line).
    - Must NOT start with 'https://' or 'http://' (URLs).
    - Extension (suffix of last path component) must be a known doc/code ext,
      so that tokens like ``tests/test_X.py`` with literal ``_X`` are filtered
      by other heuristics, but ``docs/foo.md`` passes.
    """
    if "/" not in token:
        return False
    if token[0].isdigit():
        return False
    if " " in token:
        return False
    if "<" in token or ">" in token:
        return False
    if "*" in token or "?" in token:
        return False
    if "{" in token or "}" in token:
        return False
    if ":" in token:
        return False
    if "\\n" in token or "\n" in token:
        return False
    if token.startswith(("https://", "http://")):
        return False
    # The last component must have a known file extension.
    last_component = token.split("/")[-1]
    if "." not in last_component:
        return False
    ext = "." + last_component.rsplit(".", 1)[-1]
    _KNOWN_EXTS = {
        ".md", ".py", ".ts", ".vue", ".json", ".yaml", ".yml",
        ".sh", ".toml", ".cfg", ".ini", ".txt", ".rst", ".html",
        ".css", ".js", ".lock", ".sql", ".env",
    }
    if ext not in _KNOWN_EXTS:
        return False
    return True


def check_doc_broken_links(
    repo: Path,
    tracked_files: list[str],
) -> list[str]:
    """Return WARNING lines for broken file references in docs/ .md files.

    Two kinds of references are checked:
    1. Standard Markdown links: ``[text](path)`` — the path must exist on disk.
    2. Backtick-quoted file paths: e.g. ``docs/foo.md`` — if the token looks
       like a relative file path (contains a ``/``), the resolved path must
       exist on disk.

    External URLs (http/https) and anchor-only links (#section) are skipped.
    """
    warnings: list[str] = []

    doc_mds = [
        rel for rel in tracked_files
        if rel.startswith("docs/") and rel.endswith(".md")
    ]

    for rel_path in doc_mds:
        source_file = repo / rel_path
        if not source_file.exists():
            continue

        try:
            text = source_file.read_text(errors="replace")
        except OSError:
            continue

        # -- Standard Markdown links -----------------------------------------
        for match in _MD_LINK_RE.finditer(text):
            link_target = match.group(2)
            resolved = _resolve_md_link(link_target, source_file, repo)
            if resolved is None:
                continue  # external / anchor — skip

            if not resolved.exists():
                # Compute a display-friendly relative path for the target.
                try:
                    display_target = str(resolved.relative_to(repo))
                except ValueError:
                    display_target = str(resolved)

                # Find line number for better diagnostics.
                line_no = text[: match.start()].count("\n") + 1
                warnings.append(
                    f"WARNING [doc-broken-link]: {rel_path}:{line_no} — "
                    f"link target does not exist: {display_target!r} "
                    f"(raw link: {link_target!r})"
                )

        # -- Backtick-quoted file paths --------------------------------------
        for match in _BACKTICK_PATH_RE.finditer(text):
            token = match.group(1).strip()
            if not _is_likely_file_path(token):
                continue

            # Resolve relative to repo root (backtick paths are repo-relative).
            resolved = (repo / token).resolve()
            if not resolved.exists():
                try:
                    display_target = str(resolved.relative_to(repo))
                except ValueError:
                    display_target = str(resolved)

                line_no = text[: match.start()].count("\n") + 1
                warnings.append(
                    f"WARNING [doc-broken-link]: {rel_path}:{line_no} — "
                    f"backtick path does not exist: {display_target!r}"
                )

    return warnings


def check_doc_orphans(
    repo: Path,
    tracked_files: list[str],
    corpus: list[Path],
    allowlist_patterns: list[str],
) -> list[str]:
    """Return WARNING lines for tracked docs/ .md files with zero inbound refs.

    A doc/ .md file is flagged when:
    - It is tracked by git.
    - It is older than GRACE_DAYS days.
    - Nothing in the corpus references it by basename or relative path.
    - It is not in the allowlist.

    This is the docs/-specific complement to the generic orphan check in
    ``run_check()``, which already covers the full repo but uses only basename/
    path matching.  This check is additive — it produces its own WARNING prefix
    so consumers can distinguish doc orphans from generic orphans.
    """
    warnings: list[str] = []
    cutoff = time.time() - GRACE_DAYS * 86400

    doc_mds = [
        rel for rel in tracked_files
        if rel.startswith("docs/") and rel.endswith(".md")
    ]

    for rel_path in doc_mds:
        abs_path = repo / rel_path
        if not abs_path.exists() or abs_path.is_dir():
            continue
        if is_allowlisted(rel_path, allowlist_patterns):
            continue

        birth = git_file_birth_epoch(repo, rel_path)
        if birth is not None and birth > cutoff:
            continue
        if birth is None:
            continue

        if not has_inbound_reference(rel_path, corpus, abs_path):
            warnings.append(
                f"WARNING [doc-orphan]: {rel_path} "
                f"(no inbound references; add to {ALLOWLIST_FILE} if intentional)"
            )

    return warnings


def check_docs_map_coverage(
    repo: Path,
    tracked_files: list[str],
    allowlist_patterns: list[str],
) -> list[str]:
    """Return WARNING lines for tracked docs/ .md files absent from docs/MAP.md.

    docs/MAP.md is the single index of all documentation files.  Any tracked
    .md under docs/ that is not mentioned by its filename or relative path in
    MAP.md is flagged.

    Allowlisted files are excluded.
    """
    map_path = repo / "docs" / "MAP.md"
    if not map_path.exists():
        return [
            "WARNING [doc-map-coverage]: docs/MAP.md does not exist — "
            "cannot audit MAP coverage"
        ]

    try:
        map_text = map_path.read_text(errors="replace")
    except OSError:
        return [
            "WARNING [doc-map-coverage]: could not read docs/MAP.md"
        ]

    warnings: list[str] = []

    doc_mds = [
        rel for rel in tracked_files
        if rel.startswith("docs/") and rel.endswith(".md")
    ]

    for rel_path in doc_mds:
        # MAP.md itself doesn't need to reference itself.
        if rel_path == "docs/MAP.md":
            continue
        if is_allowlisted(rel_path, allowlist_patterns):
            continue

        basename = Path(rel_path).name
        p = Path(rel_path)

        # A file is considered "covered" by MAP.md if any of the following
        # appear in MAP.md:
        #   1. The full relative path (e.g. ``docs/BACKLOG.md``)
        #   2. The basename (e.g. ``BACKLOG.md``)
        #   3. Any parent directory path + trailing slash (e.g. ``docs/adr/``)
        #      — this covers "docs/adr/ — Architecture Decision Records" entries.
        covered = False
        if rel_path in map_text or basename in map_text:
            covered = True
        if not covered:
            # Walk up the tree checking for explicit directory references.
            # A directory is "explicitly referenced" when it appears in MAP.md
            # as a standalone directory entry — i.e. the directory path with a
            # trailing slash is followed by whitespace or end-of-string (not
            # immediately by more path characters).
            # Example: ``docs/adr/ — Architecture Decision Records`` covers all
            # files under docs/adr/ but ``docs/`` alone is NOT a directory
            # reference (MAP.md uses ``docs/`` only as a path prefix for files).
            for parent in p.parents:
                parent_str = str(parent) + "/"
                # Require the slash-terminated parent to be followed by
                # a non-path character (space, dash, newline, end) in MAP.md.
                pattern = re.escape(parent_str) + r"(?:\s|—|-|$)"
                if re.search(pattern, map_text, re.MULTILINE):
                    covered = True
                    break

        if not covered:
            warnings.append(
                f"WARNING [doc-missing-from-MAP]: {rel_path} "
                f"is tracked but not listed in docs/MAP.md"
            )

    return warnings


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def run_check(
    repo: Path,
    grep_extensions: list[str] | None = None,
    *,
    out=sys.stdout,
) -> int:
    """Run all reference/doc checks.  Always returns 0 (warning-only).

    Checks performed:
    1. Generic orphan-file check — any tracked file with zero inbound refs
       older than GRACE_DAYS that is not allowlisted.
    2. Doc broken-link check (S-56 Stream C) — Markdown [text](path) links
       in docs/ pointing to files that do not exist on disk.
    3. Doc orphan check (S-56 Stream C) — tracked .md files in docs/ with
       zero inbound refs older than GRACE_DAYS.
    4. Doc MAP coverage check (S-56 Stream C) — tracked .md files in docs/
       that are absent from docs/MAP.md.

    Prints WARNING lines to *out* for each issue detected.
    """
    if grep_extensions is None:
        grep_extensions = DEFAULT_GREP_EXTENSIONS

    allowlist_patterns = load_allowlist(repo)
    tracked = git_tracked_files(repo)
    corpus = build_search_corpus(repo, tracked, grep_extensions)

    cutoff = time.time() - GRACE_DAYS * 86400
    warnings: list[str] = []

    # -- Check 1: generic orphan detection -----------------------------------
    for rel_path in tracked:
        abs_path = repo / rel_path

        # Skip non-existent paths (deleted but still in index edge case).
        if not abs_path.exists():
            continue

        # Skip directories (should not appear, but be safe).
        if abs_path.is_dir():
            continue

        # Check allowlist first (cheap).
        if is_allowlisted(rel_path, allowlist_patterns):
            continue

        # Apply grace window: skip files added less than GRACE_DAYS ago.
        birth = git_file_birth_epoch(repo, rel_path)
        if birth is not None and birth > cutoff:
            continue
        # If birth is unknown (None), be conservative and skip.
        if birth is None:
            continue

        # Check for inbound references.
        if not has_inbound_reference(rel_path, corpus, abs_path):
            warnings.append(
                f"WARNING: orphan file — {rel_path} "
                f"(no inbound references found; add to {ALLOWLIST_FILE} if intentional)"
            )

    # -- Check 2: broken Markdown links in docs/ (S-56 Stream C) ------------
    warnings.extend(check_doc_broken_links(repo, tracked))

    # -- Check 3: doc orphans (S-56 Stream C) --------------------------------
    # Note: doc orphans are a subset of generic orphans but use a distinct
    # WARNING prefix so consumers can distinguish them.  The generic check
    # already covers docs/ files, so this check is intentionally redundant
    # but provides the "[doc-orphan]" category tag for structured filtering.
    # To avoid double-reporting we do NOT add doc-orphan warnings for files
    # that were already flagged as generic orphans above.
    generic_orphan_paths = {
        w.split(" — ")[1].split(" ")[0]
        for w in warnings
        if w.startswith("WARNING: orphan file")
    }
    doc_orphan_warnings = check_doc_orphans(repo, tracked, corpus, allowlist_patterns)
    for w in doc_orphan_warnings:
        # Extract rel_path from the warning line (second token after prefix).
        parts = w.split(": ", 2)
        if len(parts) >= 3:
            rel = parts[2].split(" ")[0]
            if rel in generic_orphan_paths:
                continue  # already reported as generic orphan
        warnings.append(w)

    # -- Check 4: docs MAP coverage (S-56 Stream C) --------------------------
    warnings.extend(check_docs_map_coverage(repo, tracked, allowlist_patterns))

    for w in warnings:
        print(w, file=out)

    return 0  # always exit 0 — warning only


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect tracked files with zero inbound references (warning-only)."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Path to repo root (default: two levels up from this script).",
    )
    parser.add_argument(
        "--grep-extensions",
        nargs="+",
        default=None,
        metavar="EXT",
        help=(
            "File extensions to grep for references "
            f"(default: {' '.join(DEFAULT_GREP_EXTENSIONS)})"
        ),
    )
    args = parser.parse_args()

    exts = args.grep_extensions if args.grep_extensions else DEFAULT_GREP_EXTENSIONS
    sys.exit(run_check(args.repo, exts))


if __name__ == "__main__":
    main()
