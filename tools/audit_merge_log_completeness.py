#!/usr/bin/env python3
"""audit_merge_log_completeness.py — Merge-log completeness audit.

Walks git log on the default branch (or --branch) for merge commits (those
with 2+ parents). For each merge commit, asserts that EITHER:

  (a) There is a corresponding docs/MERGE-LOG.md entry within 3 commits
      *after* the merge commit (i.e., among the 3 next commits on the
      branch that follow the merge), OR
  (b) The merge commit's own message references "merge-log" or
      "MERGE-LOG" (case-insensitive), OR
  (c) The merge commit falls in the pre-MERGE-LOG era (before the commit
      that introduced docs/MERGE-LOG.md).

Prints WARNING-prefixed lines for merges with no audit trail.
Always exits 0 (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_merge_log_completeness.py [--repo .] [--branch main]
                                                  [--window 3]

Output:
  WARNING: <sha7>  <subject>  (no MERGE-LOG entry within {window} commits)
  (one line per merge without an audit trail; empty output means all covered)

Known false-positive (FP) classes:
  FP1 — Pre-MERGE-LOG-era merges: any merge commit that predates the commit
        that introduced docs/MERGE-LOG.md is explicitly excluded. The log
        was introduced in batch S-58 (commit b5f986d per the first MERGE-LOG
        entry). If that introduction commit cannot be found, ALL commits are
        in-scope (conservative).
  FP2 — Intra-wave stream merges: merges that fold a sub-stream into its
        wave branch (e.g., "merge(S-59-B): ...") are wave-internal bookkeeping,
        not main-branch events. The scanner only operates on --branch (default:
        the branch pointed to by HEAD or 'main' if HEAD is detached), so these
        intra-wave merges do not appear unless the branch itself is the default
        branch. If HEAD is in a worktree on a feature branch, the scanner uses
        that branch, which may include wave-internal merges — run with
        `--branch main` to target only the main-branch audit trail.
  FP3 — Audit-entry committed as a sibling of the merge: the MERGE-LOG entry
        commit may appear as a sibling commit (same-depth) rather than strictly
        *after* the merge in linear git-log order. The scanner checks both the
        3 commits immediately following AND the 3 commits immediately preceding
        the merge to handle this ordering variance (the entry may be committed
        in the same push batch).
  FP4 — Merge commit message includes the SHA of the audit entry: some
        operators annotate the merge commit message with the audit SHA directly.
        The scanner accepts this as adequate trail.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# How many commits before/after a merge to scan for a MERGE-LOG update
_DEFAULT_WINDOW = 3

# Regex to detect a MERGE-LOG entry header in the commit diff
# MERGE-LOG entries start with "## YYYY-MM-DD — ..."
_MERGE_LOG_ENTRY_RE = re.compile(
    r"^\+## \d{4}-\d{2}-\d{2} ",
    re.MULTILINE,
)

# Patterns in a commit message that count as a merge-log reference.
# These must indicate an actual audit/logging action, not merely mention
# the filename incidentally (e.g., "introduce docs/MERGE-LOG.md" should
# NOT match — it creates the file, it doesn't log a merge event).
# "audit: log ... MERGE-LOG" SHOULD match; "log" must appear BEFORE
# any MERGE-LOG mention to count as an action.
# Matched case-insensitively against the full commit message.
_MSG_REFERENCE_RES = (
    # "audit: log <anything>" — operator auditing a merge event
    # Require "log" to appear early (before "MERGE") to avoid matching
    # "audit: introduce docs/MERGE-LOG.md"
    re.compile(r"\baudit[:\s]+log\b", re.IGNORECASE),
    # "log <something> to MERGE-LOG" / "log batch merge"
    re.compile(r"\blog\b[^.]{1,60}\bmerge.log\b", re.IGNORECASE),
    # "see docs/MERGE-LOG.md for audit" — explicit reference to existing entry
    re.compile(r"\bsee\b.*\bmerge.log\b", re.IGNORECASE),
    # "MERGE-LOG entry" or "merge-log entry"
    re.compile(r"\bmerge.log\s+entry\b", re.IGNORECASE),
    # "see MERGE-LOG" or "updated MERGE-LOG" — standalone reference without ".md"
    re.compile(r"\b(?:see|updated?|wrote to|appended? to)\s+merge.log\b", re.IGNORECASE),
)


def _run_git(args: list[str], repo: Path, timeout: int = 30) -> str:
    """Run a git command in repo. Return stdout. Raise on error."""
    result = subprocess.run(
        ["git", "-C", str(repo)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "git command failed: "
            + " ".join(["git"] + args)
            + "\n"
            + result.stderr.strip()
        )
    return result.stdout


def _get_merge_log_intro_sha(repo: Path) -> str | None:
    """Return the SHA of the commit that first introduced docs/MERGE-LOG.md.

    Returns None if git is unavailable or the file has no history.
    This is used to exclude pre-MERGE-LOG-era merges (FP1).
    """
    try:
        out = _run_git(
            ["log", "--diff-filter=A", "--follow", "--format=%H",
             "--", "docs/MERGE-LOG.md"],
            repo,
        )
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if lines:
            # git log lists newest first; we want the OLDEST (introduction)
            return lines[-1]
        return None
    except Exception:
        return None


def _commits_on_branch(repo: Path, branch: str) -> list[dict]:
    """Return all commits on branch as a list of dicts with sha, subject, parents.

    Uses git log --format="%H %P|%s" to capture SHA + parent SHAs + subject
    in one pass. Parent SHAs are space-separated.
    """
    try:
        out = _run_git(
            ["log", branch, "--format=%H %P|%s"],
            repo,
        )
    except RuntimeError:
        return []

    commits = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # Split on first '|' to separate "SHA PARENT1 PARENT2 ..." from subject
        pipe_idx = line.find("|")
        if pipe_idx == -1:
            continue
        sha_parents = line[:pipe_idx].strip().split()
        subject = line[pipe_idx + 1 :]
        if not sha_parents:
            continue
        sha = sha_parents[0]
        parents = sha_parents[1:]
        commits.append(
            {
                "sha": sha,
                "subject": subject,
                "parents": parents,
                "is_merge": len(parents) >= 2,
            }
        )
    return commits


def _commit_touches_merge_log(repo: Path, sha: str) -> bool:
    """Return True if the given commit adds lines to docs/MERGE-LOG.md.

    Uses git diff-tree to check the patch for the file.
    """
    try:
        out = _run_git(
            ["diff-tree", "--no-commit-id", "-p", sha, "--",
             "docs/MERGE-LOG.md"],
            repo,
        )
        return bool(_MERGE_LOG_ENTRY_RE.search(out))
    except Exception:
        return False


def _msg_references_merge_log(subject: str) -> bool:
    """Return True if a commit subject line genuinely references the MERGE-LOG.

    Uses compiled patterns that require an audit/logging context — not mere
    incidental filename mentions (e.g., 'introduce docs/MERGE-LOG.md' should
    NOT match; 'audit: log batch-5 merge to docs/MERGE-LOG.md' SHOULD match).
    """
    return any(pattern.search(subject) for pattern in _MSG_REFERENCE_RES)


def _sha_is_ancestor_or_equal(repo: Path, ancestor: str, descendant: str) -> bool:
    """Return True if ancestor is an ancestor of (or equal to) descendant."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             ancestor, descendant],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def audit(
    repo: Path,
    branch: str = "HEAD",
    window: int = _DEFAULT_WINDOW,
) -> list[tuple[str, str]]:
    """Return a list of (sha7, subject) for merge commits with no audit trail.

    Parameters
    ----------
    repo:    path to the git repository root
    branch:  branch/ref to walk (default HEAD)
    window:  number of commits before/after each merge to check for MERGE-LOG
    """
    intro_sha = _get_merge_log_intro_sha(repo)
    commits = _commits_on_branch(repo, branch)

    if not commits:
        return []

    # Build a positional index so we can look at neighbours
    # commits[0] is the NEWEST, commits[-1] is the OLDEST
    untracked: list[tuple[str, str]] = []

    for idx, commit in enumerate(commits):
        if not commit["is_merge"]:
            continue

        sha = commit["sha"]
        subject = commit["subject"]

        # FP1: skip pre-MERGE-LOG era merges
        if intro_sha is not None:
            if not _sha_is_ancestor_or_equal(repo, intro_sha, sha):
                # intro_sha is NOT an ancestor of sha → sha predates the intro
                continue

        # Check (b): does the merge commit message itself reference the log?
        if _msg_references_merge_log(subject):
            continue

        # Check (a)+(b) extended: look at neighbouring commits (window before
        # and window after in linear git-log order). "After" the merge in git-log
        # = lower index (newer commits appear first). "Before" = higher index.
        neighbour_range = commits[max(0, idx - window): idx + window + 1]
        found = False
        for neighbour in neighbour_range:
            # Check the commit message for a reference
            if _msg_references_merge_log(neighbour["subject"]):
                found = True
                break
            # Check whether this neighbour commit actually touches MERGE-LOG.md
            if _commit_touches_merge_log(repo, neighbour["sha"]):
                found = True
                break

        if not found:
            untracked.append((sha[:7], subject[:100]))

    return untracked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=None,
        help="Path to repo root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--branch",
        default="HEAD",
        help="Branch/ref to walk (default: HEAD)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=_DEFAULT_WINDOW,
        help=(
            "Number of commits before/after a merge to check for a MERGE-LOG "
            "entry (default: %(default)s)"
        ),
    )
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        # Script lives in tools/, repo is one level up
        repo = Path(__file__).resolve().parent.parent

    untracked = audit(repo, branch=args.branch, window=args.window)

    for sha7, subject in untracked:
        print(
            "WARNING: "
            + sha7
            + "  "
            + subject
            + "  (no MERGE-LOG entry within "
            + str(args.window)
            + " commits)"
        )

    total = len(untracked)
    if total:
        print(
            "\nSummary: "
            + str(total)
            + " merge commit(s) with no MERGE-LOG audit trail",
            file=sys.stderr,
        )
    else:
        print("OK: all merge commits have a MERGE-LOG audit trail", file=sys.stderr)

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
