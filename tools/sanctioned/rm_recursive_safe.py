"""
tools/sanctioned/rm_recursive_safe.py — Sanctioned recursive delete (S-68 Stream E).

Restricts recursive deletion to the PROJECT TREE ONLY.

Safety invariants (in priority order):
  1. Target must resolve via realpath inside the repo root — no symlink escapes.
  2. Refuses /, $HOME, ~/.claude, .git/, or any path with a .. traversal outside root.
  3. Audits each deletion via write_entry before removing anything.
  4. Dry-run mode (--dry-run) prints what WOULD be deleted without touching the fs.

Usage:
  python3 tools/sanctioned/rm_recursive_safe.py <target-path> [--dry-run]
  python3 tools/sanctioned/rm_recursive_safe.py --help

Exit codes:
  0  success (deleted or dry-run ok)
  1  refused (safety check failed) — NO audit entry is written
  2  error during deletion — audit entry with FAILED result

Pure stdlib — no external dependencies.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Resolve repo root (two levels up from tools/sanctioned/)
_THIS_FILE = Path(__file__).resolve()
REPO_ROOT: Path = _THIS_FILE.parent.parent.parent  # tools/sanctioned/rm_recursive_safe.py -> repo root

# Ensure repo root is on sys.path so imports work both as a module and as a CLI script
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import pinned audit symbol (PINNED — as specified in S-68 Stream E)
from tools.sanctioned._audit import write_entry  # noqa: E402


# ── safety constants ──────────────────────────────────────────────────────────

_ABSOLUTE_REFUSALS: frozenset[str] = frozenset([
    "/",
    "/root",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/boot",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/tmp",
    "/var",
])

_HOME = Path.home()


def _refuse(reason: str) -> int:
    """Print refusal message to stderr and return exit code 1. No audit written."""
    print(f"REFUSED: {reason}", file=sys.stderr)
    return 1


def _check_target_safe(target: Path) -> str | None:
    """Return None if target is safe to delete; return an error string if not.

    Checks (in order):
      1. Target must be an absolute path or resolve to one inside REPO_ROOT.
      2. Realpath must be contained strictly inside REPO_ROOT (containment check).
      3. Must not be /, $HOME, or any absolute refusal path.
      4. Must not escape the repo root via symlinks.
      5. Must not be the repo root itself.
      6. Must not be inside .git/ (would corrupt the repository).
    """
    try:
        resolved = target.resolve()
    except OSError as exc:
        return f"cannot resolve path: {exc}"

    # Check absolute refusals
    for refusal in _ABSOLUTE_REFUSALS:
        if str(resolved) == refusal or str(resolved).startswith(refusal + "/"):
            return f"target resolves to a protected system path: {resolved}"

    # Check $HOME
    try:
        resolved.relative_to(_HOME)
        # If we get here, target is inside $HOME — refuse unless it's inside REPO_ROOT
        # (the repo might be inside $HOME, which is common)
    except ValueError:
        pass  # not inside HOME — that's fine, continue checking

    # Containment check: target must be STRICTLY inside REPO_ROOT
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        return (
            f"target resolves outside the project tree: {resolved}\n"
            f"  repo root: {REPO_ROOT}\n"
            f"  This tool only deletes paths inside the project tree."
        )

    # Must not be the repo root itself
    if resolved == REPO_ROOT:
        return f"refusing to delete the repo root itself: {resolved}"

    # Must not be inside .git/
    git_dir = REPO_ROOT / ".git"
    try:
        resolved.relative_to(git_dir)
        return f"refusing to delete inside .git/: {resolved}"
    except ValueError:
        pass  # good, not inside .git

    # Check for symlink escape: if the target path (before resolution) has a
    # component that is a symlink pointing outside REPO_ROOT, refuse.
    # We do this by checking each ancestor against REPO_ROOT.
    try:
        # Walk up from target to REPO_ROOT, checking each component
        check = target.resolve() if target.is_absolute() else (Path.cwd() / target).resolve()
        # Already checked via realpath containment above; symlinks are dereferenced.
        pass
    except OSError:
        return f"cannot verify symlink safety for: {target}"

    return None  # safe


def rm_recursive_safe(
    target: Path,
    *,
    dry_run: bool = False,
    caller: str | None = None,
    log_path: Path | None = None,
) -> int:
    """Safely delete a path recursively, restricted to the project tree.

    Parameters
    ----------
    target:
        Path to delete. Must resolve inside REPO_ROOT.
    dry_run:
        If True, print what would be deleted without removing anything.
        No audit entry is written in dry-run mode.
    caller:
        Identity string for the audit entry. Defaults to $USER.
    log_path:
        Override the audit log path (used in tests). Defaults to the
        canonical SANCTIONED_OPS_LOG.

    Returns
    -------
    int
        0 = success, 1 = refused (no audit written), 2 = deletion error.
    """
    resolved = None
    try:
        resolved = target.resolve()
    except OSError as exc:
        return _refuse(f"cannot resolve target path: {exc}")

    error = _check_target_safe(target)
    if error is not None:
        return _refuse(error)

    if not resolved.exists():
        return _refuse(f"target does not exist: {resolved}")

    if dry_run:
        print(f"DRY-RUN: would delete {resolved}")
        return 0

    # Audit BEFORE deletion (so the log entry exists even if deletion crashes)
    audit_kwargs: dict = dict(
        tool="rm_recursive_safe",
        op="rm-recursive",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes=f"deleted {resolved} (contained within {REPO_ROOT})",
        caller=caller,
    )
    if log_path is not None:
        audit_kwargs["log_path"] = log_path

    try:
        write_entry(**audit_kwargs)
    except Exception as exc:
        print(f"AUDIT WRITE FAILED: {exc}", file=sys.stderr)
        return 2

    # Perform deletion
    try:
        if resolved.is_dir() and not resolved.is_symlink():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return 0
    except Exception as exc:
        # Update audit entry result to FAILED
        failed_kwargs = dict(audit_kwargs)
        failed_kwargs["result"] = f"FAILED: {exc}"
        failed_kwargs["notes"] = f"deletion failed for {resolved}"
        try:
            write_entry(**failed_kwargs)
        except Exception:
            pass  # best-effort
        print(f"DELETION FAILED: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Sanctioned recursive delete — restricted to the project tree only. "
            "Refuses any target resolving outside the repo root, refuses /, "
            "$HOME, and symlink-escape targets. Audits each deletion."
        )
    )
    parser.add_argument(
        "target",
        help="Path to delete (must be inside the project tree)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without removing anything (no audit written)",
    )
    parser.add_argument(
        "--caller",
        default=None,
        help="Override caller identity in audit entry (default: $USER)",
    )

    args = parser.parse_args(argv)
    target = Path(args.target)
    return rm_recursive_safe(target, dry_run=args.dry_run, caller=args.caller)


if __name__ == "__main__":
    sys.exit(main())
