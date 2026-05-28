#!/usr/bin/env python3
"""check_track_status.py — invariant gate for untracked files.

Every file on disk must be in exactly one of three states:
  1. tracked (git knows about it)
  2. gitignored (.gitignore covers it)
  3. allowlisted (.track-allowlist covers it with a documented reason)

Any file in a fourth state ("silently untracked") causes exit 1.

Usage:
    python3 tools/check_track_status.py
    python3 tools/check_track_status.py --repo /path/to/repo
"""

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

ALLOWLIST_FILE = ".track-allowlist"
REASON_MARKER = "# reason:"


def parse_allowlist(repo_root: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse .track-allowlist and return (entries, errors).

    Each valid entry is a (glob, reason) tuple.
    Each malformed entry (missing reason comment) is added to errors.
    """
    allowlist_path = repo_root / ALLOWLIST_FILE
    if not allowlist_path.exists():
        return [], []

    entries: list[tuple[str, str]] = []
    errors: list[str] = []

    for lineno, raw_line in enumerate(allowlist_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        # Skip blank lines and pure comment lines
        if not line or line.startswith("#"):
            continue

        # A valid entry must contain "# reason:" somewhere after the glob
        if REASON_MARKER not in line:
            errors.append(
                f"{ALLOWLIST_FILE}:{lineno}: entry missing '# reason:' comment: {line!r}"
            )
            continue

        # Split into glob and reason parts
        glob_part, _, reason_part = line.partition(REASON_MARKER)
        glob_part = glob_part.strip()
        reason_text = reason_part.strip()

        if not glob_part:
            errors.append(
                f"{ALLOWLIST_FILE}:{lineno}: empty glob before '# reason:': {line!r}"
            )
            continue

        if not reason_text:
            errors.append(
                f"{ALLOWLIST_FILE}:{lineno}: empty reason after '# reason:': {line!r}"
            )
            continue

        entries.append((glob_part, reason_text))

    return entries, errors


def is_allowlisted(path_str: str, entries: list[tuple[str, str]]) -> bool:
    """Return True if path_str matches any allowlist glob."""
    for glob, _ in entries:
        # Try fnmatch for simple patterns and pathlib for path-relative matching
        if fnmatch.fnmatch(path_str, glob):
            return True
        # Also try matching just the filename component against non-path globs
        filename = Path(path_str).name
        if "/" not in glob and fnmatch.fnmatch(filename, glob):
            return True
    return False


def get_untracked_paths(repo_root: Path) -> list[str]:
    """Run git ls-files --others --exclude-standard and return results."""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: git ls-files failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)

    paths = [p for p in result.stdout.splitlines() if p.strip()]
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()

    # Parse allowlist — errors here are fatal (malformed allowlist = broken gate)
    entries, errors = parse_allowlist(repo_root)
    if errors:
        for err in errors:
            print(f"ALLOWLIST ERROR: {err}", file=sys.stderr)
        print(
            f"\n{len(errors)} allowlist error(s). Fix {ALLOWLIST_FILE} before re-running.",
            file=sys.stderr,
        )
        return 1

    # Collect untracked (not gitignored) paths
    untracked = get_untracked_paths(repo_root)

    # Check each untracked path against the allowlist
    violations: list[str] = []
    for path_str in untracked:
        if not is_allowlisted(path_str, entries):
            violations.append(path_str)

    if violations:
        for v in violations:
            print(
                f"UNTRACKED: {v}\n"
                f"  -> Add to .gitignore, .track-allowlist (with reason), or `git add` it."
            )
        print(
            f"\n{len(violations)} untracked file(s) not covered by .gitignore or .track-allowlist.",
            file=sys.stderr,
        )
        return 1

    print("OK: all untracked paths are covered by .gitignore or .track-allowlist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
