#!/usr/bin/env python3
"""check_cleanup_ledger.py — PROJECT_CLEANUP.md ledger consistency checker.

For any [ ] -> [x] checkbox flip in docs/cleanup/PROJECT_CLEANUP.md, warns
if no line was added to RECORD OF COMPLETIONS in the same commit.

Usage:
  tools/check_cleanup_ledger.py --check         # staged-diff check (pre-commit, advisory)
  tools/check_cleanup_ledger.py --retroactive   # scan git history for ledger gaps
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER_FILE = "docs/cleanup/PROJECT_CLEANUP.md"
RECORD_MARKERS = ("## RECORD OF COMPLETIONS", "### RECORD OF COMPLETIONS")


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, cwd=str(REPO))


def _parse_diff(diff_text):
    """Return (flip_count, record_addition_count) from a unified diff string.

    flip_count: number of [ ] -> [x] transitions (min of removed-unchecked
                and added-checked lines, to handle paired context).
    record_addition_count: non-blank added lines after a RECORD OF COMPLETIONS
                           section marker.
    """
    removed_unchecked = 0
    added_checked = 0
    in_record = False
    record_additions = 0

    for line in diff_text.splitlines():
        # Determine document content regardless of diff prefix
        if line and line[0] in ('+', '-', ' '):
            content = line[1:]
        else:
            content = line

        # Track position: once we enter a RECORD section, stay in it
        if any(marker in content for marker in RECORD_MARKERS):
            in_record = True

        if line.startswith('-') and not line.startswith('---'):
            if '[ ]' in line:
                removed_unchecked += 1
        elif line.startswith('+') and not line.startswith('+++'):
            if re.search(r'\[x\]', line, re.IGNORECASE):
                added_checked += 1
            if in_record and content.strip():
                record_additions += 1

    flip_count = min(removed_unchecked, added_checked)
    return flip_count, record_additions


def cmd_check():
    """--check: inspect staged diff; warn (advisory) if flips lack ledger entry."""
    diff = _run(["git", "diff", "--cached", "--", LEDGER_FILE]).stdout
    if not diff:
        return

    flips, records = _parse_diff(diff)
    if flips == 0:
        return

    if records == 0:
        print("  ! Ledger advisory: " + str(flips) + " checkbox flip(s) in " + LEDGER_FILE)
        print("    No RECORD OF COMPLETIONS entry detected in this commit.")
        print("    Ledger gaps are recoverable from git history; add an entry when convenient.")
    # Always exit 0 — advisory only, not a hard block


def cmd_retroactive():
    """--retroactive: scan full git history for checkbox flips without ledger entries."""
    result = _run(["git", "log", "--format=%H", "--", LEDGER_FILE])
    commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    if not commits:
        print("Retroactive ledger audit: no commits touch " + LEDGER_FILE)
        sys.exit(0)

    gaps = []
    for commit_hash in commits:
        diff = _run(["git", "show", commit_hash, "--", LEDGER_FILE]).stdout
        flips, records = _parse_diff(diff)
        if flips > 0 and records == 0:
            summary = _run(
                ["git", "log", "-1", "--format=%as %s", commit_hash]
            ).stdout.strip()
            gaps.append((commit_hash[:12], flips, summary))

    if not gaps:
        print("Retroactive ledger audit: clean")
        print("  " + str(len(commits)) + " commit(s) touching the ledger; "
              "no unrecorded completions found")
        sys.exit(0)

    print("Retroactive ledger audit: " + str(len(gaps)) + " gap(s) in "
          + str(len(commits)) + " commit(s)")
    print()
    for short_hash, flips, summary in gaps:
        print("  " + short_hash + "  (" + str(flips) + " flip(s) without ledger entry)")
        print("    " + summary)
    print()
    print("These commits completed tasks without adding to RECORD OF COMPLETIONS.")
    print("If the ledger has since been reconstructed, these are historical gaps (closed).")
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print("Usage: tools/check_cleanup_ledger.py [--check] [--retroactive]")
        print("  --check         staged-diff advisory check (pre-commit)")
        print("  --retroactive   scan full git history for checkbox flips without ledger entries")
        sys.exit(0)

    if "--check" in args:
        cmd_check()
    elif "--retroactive" in args:
        cmd_retroactive()
    else:
        print("Unknown argument: " + args[0], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
