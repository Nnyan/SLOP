#!/usr/bin/env python3
"""check_referenced_files — Orphan-file detector (wave S-48-TRACK-GATE Stream B).

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
import subprocess
import sys
import time
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
# Main check
# ---------------------------------------------------------------------------

def run_check(
    repo: Path,
    grep_extensions: list[str] | None = None,
    *,
    out=sys.stdout,
) -> int:
    """Run the orphan-file check. Always returns 0 (warning-only).

    Prints WARNING lines to *out* for each detected orphan.
    """
    if grep_extensions is None:
        grep_extensions = DEFAULT_GREP_EXTENSIONS

    allowlist_patterns = load_allowlist(repo)
    tracked = git_tracked_files(repo)
    corpus = build_search_corpus(repo, tracked, grep_extensions)

    cutoff = time.time() - GRACE_DAYS * 86400
    warnings: list[str] = []

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
