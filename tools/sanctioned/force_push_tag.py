"""
tools/sanctioned/force_push_tag.py — Sanctioned force-push of a single rewritten tag/ref.

Intended for use after an authorized history rewrite (e.g. secret-scrub via
filter_branch_secret_scrub.py). Lifts the Bash(git push*) deny via lifted(),
requires an explicit --reason AND a --confirm token, audits via write_entry,
and restores in finally.

SECURITY CONTRACT:
  - Refuses to force-push branch refs — only tag refs or explicitly-named
    non-branch refs (the ref must start with refs/tags/ OR be given with
    --force-ref-override for special refs like refs/notes/).
  - The --confirm token must match the last 7 chars of the pre-push HEAD SHA,
    preventing copy-paste invocations without reading the current repo state.
  - requires --reason (free-form justification, written to audit log).
  - Always audits to docs/SANCTIONED-OPS-LOG.md (or --log-path override for tests).
  - try/finally guarantees deny-list restore on success AND every error path.

Usage (CLI):
  python3 tools/sanctioned/force_push_tag.py \\
      --ref refs/tags/v1.2.3 \\
      --remote origin \\
      --reason "Scrubbed Tailscale private key from v1.2.3 tag via S-68 filter-branch" \\
      --confirm <last-7-of-HEAD-sha>

Dry-run (no push, no lift, audit entry written with result=DRY-RUN):
  python3 tools/sanctioned/force_push_tag.py --dry-run \\
      --ref refs/tags/v1.2.3 --remote origin --reason "..." --confirm <sha7>
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

TOOL_NAME = "force_push_tag"
_PUSH_DENY_PATTERNS = ["Bash(git push*)", "Bash(git push -f*)"]

# refs we will NOT force-push unconditionally — must be explicitly a tag
_BRANCH_PREFIXES = ("refs/heads/",)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_head_sha() -> str:
    """Return current HEAD SHA (full 40-char)."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _is_tag_ref(ref: str) -> bool:
    """Return True iff ref starts with refs/tags/ (the only unconditionally allowed prefix)."""
    return ref.startswith("refs/tags/")


def _is_branch_ref(ref: str) -> bool:
    """Return True iff ref looks like a branch ref (rejected unconditionally)."""
    return any(ref.startswith(pfx) for pfx in _BRANCH_PREFIXES)


def _do_force_push(ref: str, remote: str) -> None:
    """Execute git push --force <remote> <ref>."""
    subprocess.run(
        ["git", "push", "--force", remote, ref],
        check=True,
    )


# ── main logic ────────────────────────────────────────────────────────────────

def run(
    ref: str,
    remote: str,
    reason: str,
    confirm: str,
    dry_run: bool = False,
    settings_path: Path = SETTINGS_LOCAL,
    log_path: Path = SANCTIONED_OPS_LOG,
) -> int:
    """Execute the sanctioned force-push flow. Returns exit code (0=ok, non-zero=fail).

    Parameters
    ----------
    ref:        The full ref to force-push (must be a tag ref or pass _is_tag_ref).
    remote:     Git remote name (e.g. "origin").
    reason:     Mandatory free-form justification text.
    confirm:    Must match the last 7 chars of the current HEAD SHA.
    dry_run:    If True, skip the actual push (lift is also skipped); audit as DRY-RUN.
    settings_path: Override for tests.
    log_path:   Override for tests.
    """
    # ── Guard: refuse branch refs ─────────────────────────────────────────────
    if _is_branch_ref(ref):
        sys.stderr.write(
            "ERROR: force_push_tag refuses to force-push branch refs.\n"
            "       Only tag refs (refs/tags/...) are permitted.\n"
            "       Offending ref: " + ref + "\n"
        )
        return 1

    # ── Guard: must be a tag ref ──────────────────────────────────────────────
    if not _is_tag_ref(ref):
        sys.stderr.write(
            "ERROR: force_push_tag only accepts refs/tags/* refs.\n"
            "       To push other special refs, extend the tool with an "
            "--force-ref-override flag.\n"
            "       Offending ref: " + ref + "\n"
        )
        return 1

    # ── Guard: confirm token must match HEAD sha ──────────────────────────────
    try:
        head_sha = _get_head_sha()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write("ERROR: failed to get HEAD SHA: " + str(exc) + "\n")
        return 1

    if confirm != head_sha[-7:]:
        sys.stderr.write(
            "ERROR: --confirm token mismatch.\n"
            "       Expected last-7 of HEAD SHA: " + head_sha[-7:] + "\n"
            "       Got: " + confirm + "\n"
        )
        return 1

    pre_sha = head_sha

    # ── Dry-run path (no lift, no push) ───────────────────────────────────────
    if dry_run:
        write_entry(
            tool=TOOL_NAME,
            op="force-push " + ref + " -> " + remote,
            pre_sha=pre_sha,
            post_sha=None,
            result="DRY-RUN",
            notes=reason,
            log_path=log_path,
        )
        print("DRY-RUN: would force-push " + ref + " to " + remote)
        return 0

    # ── Live path: lift deny, push, audit, restore in finally ─────────────────
    exit_code = 0
    push_result = "FAILED: not attempted"
    post_sha: str | None = None

    try:
        with lifted(_PUSH_DENY_PATTERNS, settings_path=settings_path):
            try:
                _do_force_push(ref, remote)
                post_sha = _get_head_sha()
                push_result = "OK"
                print("force-pushed " + ref + " to " + remote)
            except subprocess.CalledProcessError as exc:
                push_result = "FAILED: " + str(exc)
                exit_code = 1
                sys.stderr.write("ERROR: push failed: " + str(exc) + "\n")
    except Exception as exc:  # noqa: BLE001
        push_result = "FAILED: lift/restore error: " + str(exc)
        exit_code = 1
        sys.stderr.write("ERROR: lift/restore failed: " + str(exc) + "\n")

    # Audit AFTER restore (always runs)
    write_entry(
        tool=TOOL_NAME,
        op="force-push " + ref + " -> " + remote,
        pre_sha=pre_sha,
        post_sha=post_sha,
        result=push_result,
        notes=reason,
        log_path=log_path,
    )

    return exit_code


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Sanctioned force-push of a single rewritten tag/ref after an "
            "authorized history rewrite. Lifts Bash(git push*) deny, pushes, "
            "audits, and restores in try/finally."
        ),
    )
    p.add_argument("--ref", required=True,
                   help="Full ref to force-push (must be refs/tags/*).")
    p.add_argument("--remote", default="origin",
                   help="Git remote name (default: origin).")
    p.add_argument("--reason", required=True,
                   help="Mandatory free-form justification (written to audit log).")
    p.add_argument("--confirm", required=True,
                   help="Last 7 chars of the current HEAD SHA (prevents blind copy-paste).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be done; skip the actual push.")
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
        ref=args.ref,
        remote=args.remote,
        reason=args.reason,
        confirm=args.confirm,
        dry_run=args.dry_run,
        log_path=log_path,
    )


if __name__ == "__main__":
    sys.exit(main())
