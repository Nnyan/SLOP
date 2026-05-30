#!/usr/bin/env python3
"""check_session_winddown.py -- ADVISORY session wind-down aggregator (BATCH-11 S4, P4).

ADVISORY, NOT ENFORCEMENT. This script is wired to the harness `Stop` hook
(`.claude/settings.json`). Read the §4f honesty caveat before trusting it:

    A non-zero Stop exit RE-PROMPTS / surfaces feedback to the session. It does
    NOT retroactively force a push, a handoff refresh, or a memory-write the
    session never did, and it may be ignored during teardown. The hook config
    is itself text in `.claude/settings.json` with no intrinsic guarantee it is
    registered and firing -- that is why S4 ALSO registers a probe-registry row
    (`session_winddown_hook_present`) so a silently-disarmed hook ages red via
    the brownout detector (else it becomes the next F7). Treat this aggregator's
    green as "I surfaced what I could reach", never as "the boundary held".

It AGGREGATES (does not replace) the existing warn-only gates:
  - handoff-freshness        (tools/check_handoff_freshness.py)   [GROUND: git]
  - status-file COMPLETE     (tools/audit_status_file_freshness.py)
  - MERGE-LOG completeness   (tools/audit_merge_log_completeness.py)
  - backlog-stale            (tools/audit_backlog_stale.py)
  - push-status              (v5 docs/tools/check_push_status.sh, if reachable)
  - memory-index orphan      NEW GROUND leg, below

Vocabulary (verbatim, CLAUDE.md "Knowledge-Lifecycle & reconciliation"):
  GROUND        -- touched physics (filesystem / git); may assert verified/DRIFT.
  XREF          -- text-vs-text; may only flag INCONSISTENT.
  INDETERMINATE -- ground truth unreachable; emitted LOUDLY, never silent OK.
  UNPROBED      -- no probe exists yet.

Exit code is ADVISORY: 0 = nothing to surface; 1 = at least one leg has
something for the session to look at (re-prompt). Either way the session may
proceed -- the harness does not force the owed write.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUSH_STATUS_SH = Path("/home/stack/v5/docs/tools/check_push_status.sh")
MEMORY_DIR = Path(
    "/home/stack/.claude/projects/-home-stack-code-slop/memory"
)

# Tokens that, when present in a sub-gate's output, mean "surface this".
_ATTENTION_TOKENS = ("DRIFT", "INCONSISTENT", "INDETERMINATE", "WARNING")


def _run(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 30):
    """Run a sub-gate; return (rc, combined_output). rc==127 => not found."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, "INDETERMINATE: command not found -- " + " ".join(cmd)
    except subprocess.TimeoutExpired:
        return 124, "INDETERMINATE: timed out -- " + " ".join(cmd)


def _classify_output(out: str) -> str:
    """Return the worst attention token found in output, or 'OK'."""
    upper = out.upper()
    for tok in _ATTENTION_TOKENS:
        if tok in upper:
            return tok
    return "OK"


def _leg_subgate(name: str, script_rel: str) -> tuple[str, str]:
    """Run a python sub-gate by relative path; classify its output."""
    script = REPO_ROOT / script_rel
    if not script.exists():
        return ("INDETERMINATE", f"[{name}] INDETERMINATE: {script_rel} missing")
    rc, out = _run([sys.executable, str(script)])
    if rc == 127:
        return ("INDETERMINATE", f"[{name}] INDETERMINATE: not runnable")
    verdict = _classify_output(out)
    first = next((ln for ln in out.splitlines() if ln.strip()), "(no output)")
    return (verdict, f"[{name}] {verdict}: {first.strip()[:200]}")


def _leg_push_status() -> tuple[str, str]:
    """Run the cross-repo push-status script if reachable; else INDETERMINATE."""
    if not PUSH_STATUS_SH.exists():
        return (
            "INDETERMINATE",
            "[push-status] INDETERMINATE: check_push_status.sh unreachable "
            f"({PUSH_STATUS_SH}) -- cross-repo tool not on this box",
        )
    rc, out = _run(["bash", str(PUSH_STATUS_SH)], timeout=60)
    # The script prints a clean line when all repos are up to date.
    if "All repos clean and up to date" in out:
        return ("verified", "[push-status] verified: all repos clean + up to date")
    if "unpushed" in out.lower() or "behind" in out.lower() or "uncommitted" in out.lower():
        first = next(
            (ln for ln in out.splitlines() if ln.strip() and "✓" not in ln),
            "(see full output)",
        )
        return ("DRIFT", f"[push-status] DRIFT: {first.strip()[:200]}")
    return ("INDETERMINATE", "[push-status] INDETERMINATE: unparseable push-status output")


def _leg_memory_index() -> tuple[str, str]:
    """NEW GROUND leg: every memory *.md (except MEMORY.md) is referenced in MEMORY.md.

    GROUND -- reads the real filesystem. If the memory dir / MEMORY.md is
    unreachable from this worktree, emit INDETERMINATE (NOT OK).
    """
    if not MEMORY_DIR.is_dir():
        return (
            "INDETERMINATE",
            f"[memory-index] INDETERMINATE: memory dir unreachable ({MEMORY_DIR})",
        )
    index = MEMORY_DIR / "MEMORY.md"
    if not index.is_file():
        return (
            "INDETERMINATE",
            f"[memory-index] INDETERMINATE: MEMORY.md not found in {MEMORY_DIR}",
        )
    try:
        index_text = index.read_text(encoding="utf-8", errors="replace")
        md_files = sorted(
            p.name for p in MEMORY_DIR.glob("*.md") if p.name != "MEMORY.md"
        )
    except OSError as exc:  # pragma: no cover - defensive
        return ("INDETERMINATE", f"[memory-index] INDETERMINATE: read error: {exc}")

    orphans = [name for name in md_files if name not in index_text]
    if orphans:
        return (
            "DRIFT",
            "[memory-index] DRIFT: "
            f"{len(orphans)} memory file(s) with NO MEMORY.md line: "
            + ", ".join(orphans),
        )
    return (
        "verified",
        f"[memory-index] verified: all {len(md_files)} memory file(s) indexed in MEMORY.md",
    )


def main() -> int:
    print("=== Session wind-down (ADVISORY -- re-prompt only, does NOT force a write) ===")
    legs: list[tuple[str, str]] = []
    legs.append(_leg_subgate("handoff-freshness", "tools/check_handoff_freshness.py"))
    legs.append(_leg_subgate("status-COMPLETE", "tools/audit_status_file_freshness.py"))
    legs.append(_leg_subgate("MERGE-LOG", "tools/audit_merge_log_completeness.py"))
    legs.append(_leg_subgate("backlog-stale", "tools/audit_backlog_stale.py"))
    legs.append(_leg_push_status())
    legs.append(_leg_memory_index())

    attention = False
    for verdict, line in legs:
        print(line)
        if verdict in ("DRIFT", "INCONSISTENT", "WARNING", "INDETERMINATE"):
            attention = True

    print("---")
    if attention:
        print(
            "ADVISORY: one or more wind-down legs want attention "
            "(re-prompt). This does NOT block ending the session and does NOT "
            "force the owed push/write -- the session owner must act."
        )
        return 1
    print("ADVISORY: all wind-down legs clean. (Still advisory -- not a hard boundary.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
