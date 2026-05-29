#!/usr/bin/env python3
"""audit_merge_worktree_pattern.py — Verify wave-branch merges used dedicated worktrees.

From archived run status/log artifacts (.claude/run-archive/*/status/*.md,
.claude/run-archive/*/decisions/*.md), this scanner checks whether orchestrator
merge operations were performed in dedicated .claude/worktrees/merge-* worktrees
with a detached HEAD, rather than directly on the shared main working tree.

Background (batch-5 retro):
  Two cross-session HEAD collisions occurred in batch-5:
  (a) A subagent committed to main by cd-ing into the main checkout.
  (b) An operator commit attached to wave/S-63 because the orchestrator had
      that branch checked out in the shared worktree during a merge.
  Both stem from using the shared main worktree's HEAD for wave-branch merges.
  The fix: every merge performed in a DEDICATED worktree (git worktree add
  .claude/worktrees/merge-<wave>) with the main worktree on a detached HEAD.

Detection strategy:
  1. Scan decision files (.claude/run-archive/*/decisions/*.md) for language
     indicating a merge was performed AND evidence of what worktree it used.
  2. Scan status files (.claude/run-archive/*/status/*.md) for merge-worktree
     references (presence of "merge-*" worktree language is a PASS signal;
     absence in files that describe merges is a WARN signal).
  3. A file is flagged if it:
       - Contains language indicating a merge commit was made (e.g. "MERGED
         (commit", "merge commit", "Merging Stream"), AND
       - Does NOT contain language indicating a dedicated merge worktree was
         used (e.g. "merge-*", "worktrees/merge", "dedicated worktree").

Known false-positive classes:
  - Pre-pattern historical runs (batch-1 through batch-4 minus the batch-5
    corrective action). The pattern was adopted mid-batch-5 after the collision.
    All runs before batch-5 and early batch-5 files will legitimately warn.
    This is expected — the warnings document the historical state.
  - Status files that record a completed merge result without describing the
    merge procedure (e.g. "Stream A — MERGED (abc1234)"). These are flagged
    as potential violations if they have no worktree evidence. Low-confidence
    candidates are annotated with "(low-confidence)" in the output.
  - The BATCH-5-COMPLETE.md itself documents the collision AND the adopted fix
    ("Did all subsequent wave merges in dedicated worktrees") — this file is
    COMPLIANT (the fix is present) and should not warn.

Exit code: 0 always (warn-only, visibility gate, never blocking).

Output:
  WARNING: <path>  [violation] <reason>
  WARNING: <path>  [low-confidence] <reason>
  (clean output → all examined files comply or no run-archive found)

Usage:
  python3 tools/audit_merge_worktree_pattern.py [--repo /path/to/repo]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Patterns that indicate a merge operation is described in the document
# ---------------------------------------------------------------------------

# Strong merge-operation indicators (high confidence that a merge happened here)
_MERGE_OP_STRONG: list[re.Pattern[str]] = [
    re.compile(r"MERGED\s+\(commit\s+[0-9a-f]{7,}", re.IGNORECASE),
    re.compile(r"merge\s+commit\s+[0-9a-f]{7,}", re.IGNORECASE),
    re.compile(r"Merging\s+Stream\s+[A-Z]", re.IGNORECASE),
    re.compile(r"git\s+merge\s+wave/", re.IGNORECASE),
    re.compile(r"merged\s+stream\s+[A-Z]\s+on\s+top\s+of", re.IGNORECASE),
    re.compile(r"stream[s]?\s+\(.*\)\s+—\s+ALL\s+MERGED", re.IGNORECASE),
]

# Weaker merge indicators (describe a merge outcome, used for low-confidence)
_MERGE_OP_WEAK: list[re.Pattern[str]] = [
    re.compile(r"—\s+MERGED\b", re.IGNORECASE),
    re.compile(r"streams.*MERGED", re.IGNORECASE),
    re.compile(r"wave\s+branch.*merged", re.IGNORECASE),
    re.compile(r"merge.*wave.*main", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Patterns that indicate the dedicated-merge-worktree pattern was FOLLOWED
# ---------------------------------------------------------------------------

_WORKTREE_COMPLIANCE: list[re.Pattern[str]] = [
    re.compile(r"worktrees/merge-", re.IGNORECASE),
    re.compile(r"merge-worktree", re.IGNORECASE),
    re.compile(r"dedicated\s+worktree", re.IGNORECASE),
    re.compile(r"git\s+worktree\s+add.*merge-", re.IGNORECASE),
    re.compile(r"merge-\*\s+worktree", re.IGNORECASE),
    re.compile(r"Did\s+all\s+subsequent\s+wave\s+merges\s+in\s+dedicated\s+worktrees", re.IGNORECASE),
    re.compile(r"\.claude/worktrees/merge-", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Patterns that indicate a VIOLATION — merge clearly done in shared checkout
# ---------------------------------------------------------------------------

_VIOLATION_INDICATORS: list[re.Pattern[str]] = [
    re.compile(r"shared\s+main\s+worktree\s+was\s+checked\s+out\s+on\s+wave/", re.IGNORECASE),
    re.compile(r"orchestrator.*shared.*worktree.*checked\s+out", re.IGNORECASE),
    re.compile(r"operator.*commit.*attached.*wave/.*because.*orchestrator.*checked\s+out", re.IGNORECASE),
    re.compile(r"HEAD\s+collision", re.IGNORECASE),
    re.compile(r"cross-session.*HEAD.*collision", re.IGNORECASE),
    re.compile(r"main\s+worktree\s+was\s+checked\s+out\s+on", re.IGNORECASE),
]

# Files to skip (not merge-operation records)
_SKIP_NAME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ROUND-\d+-COMPLETE\.md$", re.IGNORECASE),
    re.compile(r"NEXT-BATCH-COMPLETE\.md$", re.IGNORECASE),
]


def _load_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_pattern(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def _is_skip(name: str) -> bool:
    return any(p.search(name) for p in _SKIP_NAME_PATTERNS)


def scan_run_archive(repo: Path) -> list[tuple[str, str, str]]:
    """Scan run-archive for merge-worktree compliance issues.

    Returns list of (severity, path_str, reason) tuples.
    severity is "violation" or "low-confidence".
    """
    issues: list[tuple[str, str, str]] = []
    archive_root = repo / ".claude" / "run-archive"

    if not archive_root.exists():
        return issues

    # Collect all status/ and decisions/ markdown files
    candidate_files: list[Path] = []
    for run_dir in sorted(archive_root.iterdir()):
        if not run_dir.is_dir():
            continue
        for subdir in ("status", "decisions"):
            d = run_dir / subdir
            if d.is_dir():
                candidate_files.extend(sorted(d.glob("*.md")))

    for path in candidate_files:
        if _is_skip(path.name):
            continue

        text = _load_file(path)
        if not text:
            continue

        # Check for strong violation indicators first (highest confidence)
        if _has_pattern(text, _VIOLATION_INDICATORS):
            # Only flag as violation if it doesn't ALSO document the fix
            if not _has_pattern(text, _WORKTREE_COMPLIANCE):
                rel = str(path.relative_to(repo))
                issues.append((
                    "violation",
                    rel,
                    "describes HEAD collision / merge in shared worktree without "
                    "evidence of dedicated-merge-worktree fix",
                ))
            # If it documents both the problem AND the fix, it's compliant — skip
            continue

        # Check for strong merge operation + absence of worktree compliance evidence
        has_strong_merge = _has_pattern(text, _MERGE_OP_STRONG)
        has_compliance = _has_pattern(text, _WORKTREE_COMPLIANCE)

        if has_strong_merge and not has_compliance:
            rel = str(path.relative_to(repo))
            # Determine run batch for context
            batch = path.parent.parent.name
            issues.append((
                "low-confidence",
                rel,
                f"describes merge operation with no dedicated-worktree evidence "
                f"(batch: {batch}; pre-pattern runs expected — see FP note in docstring)",
            ))

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=None,
        help="Path to repo root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        repo = Path(__file__).resolve().parent.parent

    issues = scan_run_archive(repo)

    violations = [(p, r) for s, p, r in issues if s == "violation"]
    low_conf   = [(p, r) for s, p, r in issues if s == "low-confidence"]

    for path, reason in violations:
        print(f"WARNING: {path}  [violation] {reason}")

    for path, reason in low_conf:
        print(f"WARNING: {path}  [low-confidence] {reason}")

    total = len(violations) + len(low_conf)
    if total == 0:
        archive_root = repo / ".claude" / "run-archive"
        if not archive_root.exists():
            print("OK: no run-archive found — nothing to scan", file=sys.stderr)
        else:
            print("OK: no merge-worktree pattern issues found in run-archive", file=sys.stderr)
    else:
        print(
            f"\nSummary: {len(violations)} violation(s), "
            f"{len(low_conf)} low-confidence warning(s) "
            f"({total} total). Pre-pattern historical runs will appear as low-confidence.",
            file=sys.stderr,
        )

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
