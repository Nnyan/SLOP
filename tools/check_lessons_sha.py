#!/usr/bin/env python3
"""check_lessons_sha.py — Detect unresolved commit-SHA placeholders in LESSONS_LEARNED.md.

Catches the Rule 1 failure mode: a LESSONS entry written with 'Commit: TBD' but the real
SHA never filled in after the commit lands.

Usage:
    python3 tools/check_lessons_sha.py
    python3 tools/check_lessons_sha.py --path /path/to/LESSONS_LEARNED.md
    python3 tools/check_lessons_sha.py --quiet     # exit code only, no per-match output
    python3 tools/check_lessons_sha.py --self-test # run smoke test and exit

Hook integration (DO NOT install automatically — user decides):
    Add to .git/hooks/pre-push (chmod +x):
        python3 tools/check_lessons_sha.py || exit 1

Exit 0 if no unresolved placeholders found; exit 1 if any found.
"""

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

DEFAULT_PATH = "/home/stack/v5/docs/LESSONS_LEARNED.md"

# Patterns that signal an unresolved commit placeholder
PLACEHOLDER_RE = re.compile(r"\b(TBD|tbd|\?\?\?|TODO|pending|<SHA>)\b")

# Anchor: placeholder only fires when one of these appears within ±3 lines
ANCHOR_RE = re.compile(r"(?i)\b(commit|sha|fix-in)\b")


def scan(path, quiet=False):
    """Scan *path* for unresolved placeholders; return list of (lineno, placeholder, heading)."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    findings = []
    in_code_block = False
    heading = ""

    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        if in_code_block:
            continue
        if line.startswith("#"):
            heading = line.strip()
        m = PLACEHOLDER_RE.search(line)
        if not m:
            continue
        lo, hi = max(0, i - 3), min(len(lines), i + 4)
        if not ANCHOR_RE.search("\n".join(lines[lo:hi])):
            continue
        findings.append((i + 1, m.group(0), heading))
        if not quiet:
            print(
                str(path) + ":" + str(i + 1) + ": unresolved commit placeholder '"
                + m.group(0) + "' in entry near \"" + heading + "\""
            )
    return findings


def _self_test():
    """Smoke test — one TBD placeholder should be found, not zero or two."""
    sample = (
        "# Test\n"
        "## Fix\n"
        "Commit: TBD\n"
        "Lesson: about something\n"
        "## Another\n"
        "Commit: abc123\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(sample)
        tmp = f.name
    try:
        found = scan(tmp, quiet=True)
        if len(found) == 1:
            print("self-test passed (1 placeholder found as expected)")
            sys.exit(0)
        else:
            print("self-test FAILED: expected 1, got " + str(len(found)))
            for ln, ph, h in found:
                print("  line " + str(ln) + ": '" + ph + "' near \"" + h + "\"")
            sys.exit(1)
    finally:
        os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser(
        description="Check LESSONS_LEARNED.md for unresolved commit-SHA placeholders."
    )
    ap.add_argument("--path", default=DEFAULT_PATH, help="Path to LESSONS_LEARNED.md")
    ap.add_argument("--quiet", action="store_true", help="Suppress per-match output; exit code only")
    ap.add_argument("--self-test", action="store_true", dest="self_test", help="Run smoke test and exit")
    args = ap.parse_args()

    if args.self_test:
        _self_test()

    findings = scan(args.path, quiet=args.quiet)
    if findings and not args.quiet:
        print(str(len(findings)) + " unresolved placeholder(s) found.")
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
