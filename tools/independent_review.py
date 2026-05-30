#!/usr/bin/env python3
"""Independent-review enforcement helpers (BATCH-11 Stream S7, P7).

Two concerns live here, sharing one artifact-existence GROUND helper:

  1. ``check_independent_review`` — the PENDING gate from CLAUDE.md
     § "Independent review for significant changes". When a commit trips the
     **mechanical floor** (touches doctrine files / adds a sanctioned tool /
     adds a ``def check_`` to ms-enforce / invokes an irreversible-git tool), it
     must cite a ``docs/REVIEW-LOG.md`` record AND that record must actually
     EXIST as a committed artifact (cited-record-missing → DRIFT). This is the
     **artifact-existence GROUND leg**: we touch the filesystem / git numstat to
     prove the REVIEW-LOG entry really landed, never trusting the message token
     alone.

  2. The **artifact-existence helper** (``artifact_exists`` /
     ``cited_record_exists``) — PINNED: Stream S11's
     ``check_manager_handoff_artifacts`` imports ``artifact_exists`` to ground
     its own back-reference token on a committed file.

Reconciler-trust vocabulary (CLAUDE.md, verbatim):
  GROUND        — touches physics (git numstat / the filesystem); may say
                  ``verified`` or ``DRIFT``.
  DRIFT         — GROUND mismatch on a load-bearing claim (cited record absent).
  INCONSISTENT  — XREF mismatch (text-vs-text); never asserts verified.
  INDETERMINATE — ground truth unreachable (git unavailable); emitted LOUDLY.
  UNPROBED      — no probe exists for this fact yet (here: review *substance*).

ACYCLICITY IN CODE (hard, CLAUDE.md requirement): the floor-path set
**statically excludes** ``docs/REVIEW-LOG.md`` and this gate's own
``def check_independent_review`` token in ms-enforce — so a review (whose only
output is a REVIEW-LOG entry) can NEVER trigger a review. Changing that
exclusion requires a WALK-BACK-LOG entry (acyclicity in code, not prose).

[red-signal: PARTIAL] — GROUND on *fabrication / missing-artifact* (a floor
commit that cites no committed REVIEW-LOG addition is DRIFT); UNPROBED on
*substance* (whether the review was good rides the standing audits + Manager
batch-landing review). HARD STOP: this gate is TIER_1 warn-only and never
auto-promotes to blocking until/unless a deliberate recorded act does so.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# ── Mechanical-floor path set ──────────────────────────────────────────────
# Doctrine files (touch → floor fires).
_DOCTRINE_FILES = (
    "CLAUDE.md",
    ".claude/ROBOT.md",
    ".claude/AUTONOMOUS-DEFAULTS.md",
)
# A new file UNDER this dir trips the floor.
_SANCTIONED_DIR = "tools/sanctioned/"
# The enforcer file: ADDING a ``def check_`` to it trips the floor.
_ENFORCER_FILE = "ms-enforce"

# ── ACYCLICITY: paths statically EXCLUDED from the floor ───────────────────
# A review's only output is a REVIEW-LOG entry; a commit touching ONLY these
# must never trip the floor (else review → triggers review → loop). The gate's
# own ``def check_independent_review`` token in ms-enforce is excluded below in
# ``_adds_check_def`` (a check_-def whose name is the gate itself is ignored).
_FLOOR_EXCLUDED_PATHS = frozenset(
    {
        "docs/REVIEW-LOG.md",
    }
)
# The gate's own check name — adding THIS def must not trip the floor.
_SELF_CHECK_NAME = "check_independent_review"

_REVIEW_LOG_REL = "docs/REVIEW-LOG.md"

# Commit-message tokens that count as "cites a REVIEW-LOG record".
_CITE_TOKENS = ("review-log", "review_log", "reviewlog")


# ── git plumbing (GROUND) ──────────────────────────────────────────────────
def _git(args: list[str], repo: Path, timeout: int = 5) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout + r.stderr
    except Exception as exc:  # noqa: BLE001 — surfaced as INDETERMINATE upstream
        return 1, str(exc)


def _head_message(repo: Path) -> tuple[bool, str]:
    rc, out = _git(["log", "-1", "--format=%B"], repo)
    return (rc == 0), out


def _head_numstat(repo: Path) -> tuple[bool, list[tuple[int, int, str]]]:
    """Return (ok, [(added, deleted, path), ...]) for HEAD. added/deleted=-1 for binary."""
    rc, out = _git(["log", "-1", "--numstat", "--format="], repo)
    if rc != 0:
        return False, []
    rows: list[tuple[int, int, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a_s, d_s, path = parts
        a = -1 if a_s == "-" else (int(a_s) if a_s.isdigit() else 0)
        d = -1 if d_s == "-" else (int(d_s) if d_s.isdigit() else 0)
        rows.append((a, d, path))
    return True, rows


def _head_status(repo: Path) -> tuple[bool, dict[str, str]]:
    """Return (ok, {path: status_letter}) for HEAD (A/M/D/...)."""
    rc, out = _git(["log", "-1", "--name-status", "--format="], repo)
    if rc != 0:
        return False, {}
    status: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status[parts[-1]] = parts[0][:1]
    return True, status


# ── PINNED artifact-existence helper (consumed by S11) ─────────────────────
def artifact_exists(path: str | Path, repo: Path | None = None) -> bool:
    """GROUND: does an artifact actually exist on disk as a committed file?

    PINNED for Stream S11's ``check_manager_handoff_artifacts`` — the general
    "the thing the message/back-reference points at must really be there"
    primitive. Touches the filesystem (physics), never a ``/tmp`` transcript.

    Args:
        path: artifact path; absolute, or relative to ``repo`` when given.
        repo: optional repo root to resolve a relative ``path`` against.

    Returns:
        True iff the resolved path exists and is a regular file.
    """
    p = Path(path)
    if not p.is_absolute() and repo is not None:
        p = Path(repo) / p
    return p.is_file()


def cited_record_exists(commit_message: str, repo: Path, log_path: str = _REVIEW_LOG_REL) -> bool:
    """GROUND: a floor commit's cited REVIEW-LOG record actually landed.

    "Cited" = the commit message references the review log (token match) AND the
    cited record file exists AND HEAD added non-empty content to it (a real
    entry, not merely a string token). This is the artifact-existence GROUND
    leg: a message that *claims* a review but added nothing to a committed
    REVIEW-LOG is fabrication → caller emits DRIFT.

    Args:
        commit_message: the HEAD commit message body.
        repo: repo root.
        log_path: the cited record path (default ``docs/REVIEW-LOG.md``).

    Returns:
        True iff cited + file exists + HEAD made a non-empty addition to it.
    """
    msg = commit_message.lower()
    if not any(tok in msg for tok in _CITE_TOKENS):
        return False
    if not artifact_exists(log_path, repo):
        return False
    ok, rows = _head_numstat(repo)
    if not ok:
        return False
    for added, _deleted, path in rows:
        if path == log_path and added > 0:
            return True
    return False


# ── floor detection (acyclicity enforced HERE, in code) ────────────────────
def _adds_check_def(repo: Path) -> bool:
    """True iff HEAD adds a NEW ``def check_<name>`` to the enforcer file,
    EXCLUDING the gate's own ``def check_independent_review`` (acyclicity)."""
    rc, out = _git(["log", "-1", "-p", "--format=", "--", _ENFORCER_FILE], repo)
    if rc != 0:
        return False
    for line in out.splitlines():
        # Added lines start with a single '+' (not '+++').
        if not line.startswith("+") or line.startswith("+++"):
            continue
        stripped = line[1:].lstrip()
        if stripped.startswith("def check_"):
            name = stripped[len("def "):].split("(")[0].strip()
            if name == _SELF_CHECK_NAME:
                continue  # acyclicity: adding the gate itself is not a floor trip
            return True
    return False


def floor_triggers(repo: Path) -> tuple[bool, list[str]]:
    """Does HEAD trip the independent-review mechanical floor?

    Returns (tripped, reasons). Floor paths are evaluated with the acyclicity
    exclusion (``docs/REVIEW-LOG.md`` and the gate's own def are never floor
    triggers). Irreversible-git invocation is NOT detectable from numstat alone
    (it leaves no path) so it relies on author honesty + the message; we treat a
    commit ADDING a file under ``tools/sanctioned/`` as the closest static
    proxy and otherwise leave the irreversible-git tier to the declared layer.
    """
    reasons: list[str] = []
    ok_ns, rows = _head_numstat(repo)
    ok_st, status = _head_status(repo)
    if not ok_ns or not ok_st:
        return False, reasons  # caller maps to INDETERMINATE

    for _added, _deleted, path in rows:
        if path in _FLOOR_EXCLUDED_PATHS:
            continue  # ACYCLICITY: REVIEW-LOG touch never trips the floor
        if path in _DOCTRINE_FILES:
            reasons.append(f"doctrine file modified: {path}")
        elif path.startswith(_SANCTIONED_DIR) and status.get(path) == "A":
            reasons.append(f"new sanctioned tool added: {path}")

    if _adds_check_def(repo):
        reasons.append(f"new def check_ added to {_ENFORCER_FILE}")

    return (len(reasons) > 0), reasons


# ── verdict (consumed by ms-enforce check_independent_review) ──────────────
def evaluate(repo: Path) -> tuple[str, str]:
    """Return (verdict, detail) for HEAD.

    Verdicts: ``verified`` (floor tripped + cited record exists),
    ``DRIFT`` (floor tripped + NO committed REVIEW-LOG entry — fabrication),
    ``INDETERMINATE`` (git unreachable), or ``OK`` (floor not tripped — nothing
    to check; honest "I had nothing to check", not a green "verified").
    """
    ok_msg, msg = _head_message(repo)
    if not ok_msg:
        return "INDETERMINATE", "git log unavailable"

    tripped, reasons = floor_triggers(repo)
    if not tripped:
        # Distinguish unreachable-git from genuinely-not-tripped.
        ok_ns, _ = _head_numstat(repo)
        if not ok_ns:
            return "INDETERMINATE", "git numstat unavailable"
        return "OK", "HEAD does not trip the independent-review mechanical floor"

    reason_str = "; ".join(reasons)
    if cited_record_exists(msg, repo):
        return (
            "verified",
            f"floor tripped ({reason_str}) and cites a committed "
            f"{_REVIEW_LOG_REL} entry [GROUND: numstat addition]",
        )
    return (
        "DRIFT",
        f"floor tripped ({reason_str}) but HEAD cites NO committed "
        f"{_REVIEW_LOG_REL} entry — add a REVIEW-LOG entry "
        f"(reviewer + charge + per-finding reconciliation) and reference it in "
        f"the commit message. [red-signal: PARTIAL — GROUND on missing-artifact; "
        f"review substance is UNPROBED]",
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Independent-review artifact-existence gate (P7).")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    verdict, detail = evaluate(repo)
    print(f"{verdict}: {detail}")
    # Warn-only: always exit 0. HARD STOP — never auto-promote to blocking.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
