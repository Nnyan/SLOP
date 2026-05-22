#!/usr/bin/env python3
"""tools/commit_msg_hook.py — Conventional Commits 1.0 enforcement.

Installed as .git/hooks/commit-msg via symlink (1.3.c will wire it):
    ln -sf "$(realpath tools/commit_msg_hook.py)" .git/hooks/commit-msg

Receives the commit message file path as argv[1], reads the first
non-comment line, validates against the project's CC 1.0 rules.
Exits 0 to accept; exits 1 with a helpful error message to reject.

Strategy ref: STEP_1_3_COMMIT_DISCIPLINE_STRATEGY.md §3; step 1.3.b.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Subject-line regex. Periods are permitted *within* the subject (e.g. version
# numbers, sub-task IDs like "1.3.a", abbreviations); the trailing-period
# rejection is a separate Python check below — this avoids false positives
# while still enforcing CC 1.0 §6 (no period at end of subject).
PATTERN = re.compile(
    r"^(feat|fix|refactor|perf|test|docs|chore)"
    r"(\([a-z0-9_/\-]+\))?"
    r"!?: "
    r"[^\n]{1,100}$"
)

# Auto-accept these git-internal prefixes (per strategy §3.3)
BYPASS_PREFIXES = ("Merge ", 'Revert "', "fixup! ", "squash! ")


def first_non_comment_line(text: str) -> str:
    """Return the first line that is not a git-comment line (does not start with '#')."""
    for line in text.splitlines():
        if not line.startswith("#"):
            return line
    return ""


def validate(subject: str) -> bool:
    """Return True if the subject is acceptable, False otherwise.

    Two-step: regex match + trailing-period rejection. Splitting the period
    check out of the regex lets subjects contain periods (e.g. '1.3.a',
    'mypy --strict', 'PROJECT_CLEANUP.md') which the spec intends to allow.
    """
    if subject.startswith(BYPASS_PREFIXES):
        return True
    if not PATTERN.match(subject):
        return False
    if subject.endswith("."):
        return False
    return True


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: commit_msg_hook.py <commit-msg-path>\n")
        return 1
    path = Path(sys.argv[1])
    if not path.exists():
        sys.stderr.write(f"commit-msg file not found: {path}\n")
        return 1
    subject = first_non_comment_line(path.read_text()).rstrip()
    if validate(subject):
        return 0
    sys.stderr.write(
        "✗ commit-msg: subject does not match Conventional Commits 1.0\n"
        f"  got:      {subject}\n"
        "  expected: type(scope)?: subject\n"
        "            type ∈ {feat, fix, refactor, perf, test, docs, chore}\n"
        "            subject ≤ 100 chars, no trailing period\n"
        "  see:      docs/cleanup/STEP_1_3_COMMIT_DISCIPLINE_STRATEGY.md\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
