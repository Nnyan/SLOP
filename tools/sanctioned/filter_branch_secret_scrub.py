"""
tools/sanctioned/filter_branch_secret_scrub.py — Sanctioned secret-scrub via git filter-branch.

Wraps the secret-scrub filter-branch flow used in the Tailscale-key incident
(2026-05-28). Takes a file path or glob pattern to scrub, runs git filter-branch
to rewrite all commits that contained that file (or matched that pattern),
and audits the operation via write_entry.

DOES NOT PUSH. Use tools/sanctioned/force_push_tag.py (for tags) or
tools/sanctioned/robot_settings.py push-then-restore (for branches, where
authorized) to push rewritten refs after this operation.

SECURITY CONTRACT:
  - Operates only inside the current git repo root.
  - Refuses to run if the working tree is not clean (safety check).
  - Captures pre-scrub HEAD SHA (pre_sha) and post-scrub HEAD SHA (post_sha)
    in the audit log entry.
  - try/finally restores deny-list even if the filter-branch itself fails.
  - Writes to docs/SANCTIONED-OPS-LOG.md (or --log-path for tests).

The filter-branch command used:
    git filter-branch --force --index-filter \\
        'git rm --cached --ignore-unmatch <path-pattern>' \\
        --prune-empty --tag-name-filter cat -- --all

Usage (CLI):
  python3 tools/sanctioned/filter_branch_secret_scrub.py \\
      --path path/to/secret/file \\
      --reason "Scrub leaked Tailscale private key added in commit abc1234" \\
      [--dry-run]

Dry-run (no rewrite, audit entry written with result=DRY-RUN):
  python3 tools/sanctioned/filter_branch_secret_scrub.py \\
      --path path/to/secret --reason "..." --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# ── import pinned symbols from foundation modules ─────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.sanctioned._lift_restore import SETTINGS_LOCAL, lifted
from tools.sanctioned._audit import SANCTIONED_OPS_LOG, write_entry

# ── constants ─────────────────────────────────────────────────────────────────

TOOL_NAME = "filter_branch_secret_scrub"

# filter-branch itself does not push, so we only need to lift the filter-branch
# operation; no push deny needs lifting here.
_FILTER_BRANCH_DENY_PATTERNS: list[str] = []  # no deny for filter-branch itself


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_head_sha() -> str:
    """Return current HEAD SHA (full 40-char)."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _get_repo_root() -> Path:
    """Return the absolute path to the git repo root."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    )
    return Path(result.stdout.strip())


def _check_working_tree_clean() -> bool:
    """Return True if working tree is clean (no uncommitted changes)."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip() == ""


def _run_filter_branch(path_pattern: str, repo_root: Path) -> subprocess.CompletedProcess:
    """Run git filter-branch to scrub path_pattern from all history."""
    env = os.environ.copy()
    # Suppress the "are you sure" warning that filter-branch emits
    env["FILTER_BRANCH_SQUELCH_WARNING"] = "1"
    return subprocess.run(
        [
            "git", "filter-branch",
            "--force",
            "--index-filter",
            "git rm --cached --ignore-unmatch " + path_pattern,
            "--prune-empty",
            "--tag-name-filter", "cat",
            "--",
            "--all",
        ],
        check=True,
        cwd=str(repo_root),
        env=env,
    )


# ── main logic ────────────────────────────────────────────────────────────────

def run(
    path_pattern: str,
    reason: str,
    dry_run: bool = False,
    require_clean: bool = True,
    settings_path: Path = SETTINGS_LOCAL,
    log_path: Path = SANCTIONED_OPS_LOG,
) -> int:
    """Execute the sanctioned filter-branch secret-scrub flow.

    Parameters
    ----------
    path_pattern: File path or glob pattern to scrub from all history.
    reason:       Mandatory free-form justification text (written to audit log).
    dry_run:      If True, skip the actual rewrite; audit with result=DRY-RUN.
    require_clean: If True (default), refuse to run with uncommitted changes.
    settings_path: Override for tests.
    log_path:     Override for tests.

    Returns exit code: 0=success, non-zero=failure.
    """
    # ── Validate we are inside a git repo ─────────────────────────────────────
    try:
        repo_root = _get_repo_root()
    except subprocess.CalledProcessError:
        sys.stderr.write("ERROR: not inside a git repository.\n")
        return 1

    # ── Working-tree cleanliness check ────────────────────────────────────────
    if require_clean:
        try:
            is_clean = _check_working_tree_clean()
        except subprocess.CalledProcessError as exc:
            sys.stderr.write("ERROR: could not check working tree status: " + str(exc) + "\n")
            return 1
        if not is_clean:
            sys.stderr.write(
                "ERROR: working tree has uncommitted changes.\n"
                "       Commit or stash before running filter-branch.\n"
            )
            return 1

    # ── Capture pre-scrub SHA ─────────────────────────────────────────────────
    try:
        pre_sha = _get_head_sha()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write("ERROR: failed to get HEAD SHA: " + str(exc) + "\n")
        return 1

    # ── Dry-run path ──────────────────────────────────────────────────────────
    if dry_run:
        write_entry(
            tool=TOOL_NAME,
            op="filter-branch scrub: " + path_pattern,
            pre_sha=pre_sha,
            post_sha=None,
            result="DRY-RUN",
            notes=reason,
            log_path=log_path,
        )
        print("DRY-RUN: would scrub " + path_pattern + " from all history via filter-branch")
        print("         Repo root: " + str(repo_root))
        return 0

    # ── Live path: lift deny (none needed for filter-branch itself), run, audit, restore ──
    exit_code = 0
    scrub_result = "FAILED: not attempted"
    post_sha: str | None = None

    # Even though filter-branch itself has no deny, we use the lifted() context
    # manager (with empty pattern list) to keep the try/finally discipline
    # uniform across all sanctioned tools. This ensures restore() always runs.
    try:
        with lifted(_FILTER_BRANCH_DENY_PATTERNS, settings_path=settings_path):
            try:
                _run_filter_branch(path_pattern, repo_root)
                post_sha = _get_head_sha()
                scrub_result = "OK"
                print("filter-branch scrub complete: " + path_pattern)
                print("  pre-SHA:  " + pre_sha)
                print("  post-SHA: " + post_sha)
            except subprocess.CalledProcessError as exc:
                scrub_result = "FAILED: " + str(exc)
                exit_code = 1
                sys.stderr.write("ERROR: filter-branch failed: " + str(exc) + "\n")
    except Exception as exc:  # noqa: BLE001
        scrub_result = "FAILED: lift/restore error: " + str(exc)
        exit_code = 1
        sys.stderr.write("ERROR: lift/restore error: " + str(exc) + "\n")

    # Audit AFTER restore (always runs regardless of exit_code)
    write_entry(
        tool=TOOL_NAME,
        op="filter-branch scrub: " + path_pattern,
        pre_sha=pre_sha,
        post_sha=post_sha,
        result=scrub_result,
        notes=reason,
        log_path=log_path,
    )

    return exit_code


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Sanctioned secret-scrub via git filter-branch. Rewrites history "
            "to remove a file or glob pattern from ALL commits. Does NOT push "
            "(use force_push_tag.py or robot_settings.py push-then-restore "
            "for that step)."
        ),
    )
    p.add_argument("--path", required=True,
                   help="File path or glob pattern to scrub from all history.")
    p.add_argument("--reason", required=True,
                   help="Mandatory free-form justification (written to audit log).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be done; skip the actual rewrite.")
    p.add_argument("--allow-dirty", action="store_true",
                   help="Skip the working-tree cleanliness check (dangerous).")
    p.add_argument("--log-path", default=None,
                   help="Override audit log path (for tests).")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Explicit --log-path wins; env-var redirect (S-71-B) applies when neither
    # --log-path nor SLOP_AUDIT_LOG_PATH is set (falling back to SANCTIONED_OPS_LOG).
    if args.log_path:
        log_path: Path = Path(args.log_path)
    elif "SLOP_AUDIT_LOG_PATH" in os.environ:
        log_path = Path(os.environ["SLOP_AUDIT_LOG_PATH"])
    else:
        log_path = SANCTIONED_OPS_LOG

    return run(
        path_pattern=args.path,
        reason=args.reason,
        dry_run=args.dry_run,
        require_clean=not args.allow_dirty,
        log_path=log_path,
    )


if __name__ == "__main__":
    sys.exit(main())
