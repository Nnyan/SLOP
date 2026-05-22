"""tests/test_commit_format.py — Step 1.3 enforcement test for Core Rule 7.1.

Validates that every commit since the hook-cutoff SHA matches Conventional
Commits 1.0 with the project's type/scope/subject constraints. Pre-cutoff
commits are skipped (grandfathered per strategy §2.7).

Strategy ref: STEP_1_3_COMMIT_DISCIPLINE_STRATEGY.md §6; step 1.3.f.
"""
from __future__ import annotations

import re
import subprocess

import pytest

# The cutoff is the commit that landed the commit-msg hook (step 1.3.c).
# Inclusive: cutoff SHA itself is the first post-policy commit and must conform.
CUTOFF_SHA = "45bb063"

PATTERN = re.compile(
    r"^(feat|fix|refactor|perf|test|docs|chore)"
    r"(\([a-z0-9_/\-]+\))?"
    r"!?: "
    r"[^\n]{1,100}$"
)
BYPASS_PREFIXES = ("Merge ", 'Revert "', "fixup! ", "squash! ")


def _subject_ok(subject: str) -> bool:
    """Pattern match plus trailing-period check (per strategy §3.2 split).

    Mirrors the validation contract of tools/commit_msg_hook.py.validate().
    """
    if subject.startswith(BYPASS_PREFIXES):
        return True
    return bool(PATTERN.match(subject)) and not subject.endswith(".")


def test_commit_subjects_post_cutoff_match_convention():
    """Every commit since CUTOFF_SHA (inclusive) must follow CC 1.0 with project rules.

    The range `{cutoff}~1..HEAD` includes the cutoff commit itself, which
    landed the hook and is the first post-policy commit. Any commit that
    bypassed the hook (e.g. via --no-verify or rebase) is caught here.
    """
    result = subprocess.run(
        ["git", "log", "--pretty=format:%H %s", f"{CUTOFF_SHA}~1..HEAD"],
        capture_output=True, text=True, check=True,
    )
    bad = []
    for line in result.stdout.splitlines():
        sha, _, subject = line.partition(" ")
        if not _subject_ok(subject):
            bad.append(f"  {sha[:8]} {subject}")
    assert not bad, (
        "Non-conforming commit subjects found in post-cutoff range:\n"
        + "\n".join(bad)
    )


@pytest.mark.parametrize("subject", [
    "feat(api): add /v2/health endpoint",
    "fix(executor): guard source=None in _wire",
    "docs(cleanup): mark 1.3.a done",
    "refactor: split run_health_cycle into stages",
    "feat!: drop legacy /v1 endpoints",
    "fix(api/health)!: tighten rate limits",
    'Revert "old non-CC subject"',
    "Merge branch 'feature/x' into main",
])
def test_pattern_accepts_valid_subjects(subject):
    assert _subject_ok(subject), f"valid subject rejected: {subject}"


@pytest.mark.parametrize("subject,reason", [
    ("feature: bad type", "feature is not in the type list"),
    ("fix: subject ending in period.", "trailing period"),
    ("FIX(api): uppercase type", "type must be lowercase"),
    ("fix(API): uppercase scope", "scope must be lowercase"),
    ("fix:", "missing subject"),
    ("fix: " + "x" * 101, "subject > 100 chars"),
    ("commit message with no type prefix", "missing type"),
])
def test_pattern_rejects_invalid_subjects(subject, reason):
    assert not _subject_ok(subject), f"invalid subject accepted ({reason}): {subject}"
