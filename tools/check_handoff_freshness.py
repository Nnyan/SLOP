#!/usr/bin/env python3
"""
tools/check_handoff_freshness.py — Handoff SHA freshness checker
(S-75 Stream C; LR-1 grounded rewrite 2026-05-30).

Verifies that the origin/main SHA recorded in the committed ``.handoff-sha``
artifact — the origin/main SHA that the current ``docs/MANAGER-HANDOFF.md`` was
last refreshed against — matches the live value of ``git rev-parse origin/main``.

GROUND-class: it touches git physics (``git rev-parse``), so verdicts may say
"verified" or "DRIFT".

LR-1 fix (GROUND-gate brownout closure — Coverage+Handoff audit, finding F7/P1):
The prior version parsed a human-maintained prose bullet
(``- **origin/main at `<SHA>`**``) out of MANAGER-HANDOFF.md. A doc-hygiene
rewrite (commit ``95dc0e0``) deleted that bullet, so the gate emitted
INDETERMINATE *permanently* — a GROUND gate silently browned out to "not red"
with no actionable signal. The freshness SHA is now read from a committed
machine artifact (``.handoff-sha``), and **ABSENCE of that artifact is DRIFT**
(a defect to fix), NOT INDETERMINATE. Only a genuinely unreachable origin
(``git rev-parse`` cannot resolve origin/main) is INDETERMINATE.

Verdict vocabulary (PINNED — Stream E contract):
  verified      — GROUND match (.handoff-sha == origin/main)
  DRIFT         — GROUND mismatch, OR .handoff-sha missing/malformed
  INDETERMINATE — origin/main genuinely unreachable (git rev-parse failed)

Steady-state note (exact-match semantics, intentional): right after a batch
lands on main, ``.handoff-sha`` legitimately trails origin/main by the merge
commit, so the gate reads **DRIFT — refresh the handoff**. That is the designed
nudge for the next session (and is loud + red-eligible, i.e. NOT a brownout),
not a defect. A self-referential "store this commit's own SHA" is impossible,
so a one-commit lag after each landing is inherent.

``.handoff-sha`` ownership: written/updated at each handoff refresh. Until
batch-11 P1 wires ``merge_wave_to_main.py`` to stamp it automatically, the
Manager updates it when refreshing MANAGER-HANDOFF.md. Skipping that step is
GROUND-visible — the gate goes DRIFT (red-eligible) — satisfying the doctrine
"a manual step is covered only if skipping it can go red."

ms-enforce registration: see check_handoff_freshness() thin wrapper at the
bottom of this module + TIER_1 append block in ms-enforce.

Promotion-to-blocking trigger (TIER_1 gate graduation): promote to blocking
when two consecutive batches show DRIFT without a corresponding handoff /
.handoff-sha update in the batch sweep. Current tier: warn-only (TIER_1),
always returns True from the ms-enforce wrapper.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Canonical committed artifact: the origin/main SHA the current handoff was
# refreshed against. Repo-root-relative.
HANDOFF_SHA_FILE = Path(".handoff-sha")

# Retained for DRIFT remediation hints only (no longer parsed for the SHA).
HANDOFF_FILE = Path("docs") / "MANAGER-HANDOFF.md"

# A bare git short/long SHA (4–40 hex). The artifact's first whitespace-token.
_SHA_RE = re.compile(r"^[0-9a-f]{4,40}$", re.IGNORECASE)


def _read_declared_sha(repo_root: Path) -> str | None:
    """Return the SHA recorded in .handoff-sha, or None if absent/malformed.

    The artifact's first whitespace-delimited token is the SHA, so a trailing
    ``# comment`` is tolerated.
    """
    path = repo_root / HANDOFF_SHA_FILE
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    token = raw.split()[0] if raw else ""
    if _SHA_RE.match(token):
        return token
    return None


def _get_live_sha(repo_root: Path) -> str | None:
    """Return the full SHA of origin/main, or None if origin is unreachable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(repo_root),
            timeout=15,
        )
        if result.returncode != 0:
            return None
        sha = result.stdout.strip()
        if not sha or not re.match(r"^[0-9a-f]{40}$", sha):
            return None
        return sha
    except (subprocess.TimeoutExpired, OSError):
        return None


def check(repo_root: Path | None = None) -> tuple[bool, str]:
    """Check handoff SHA freshness. Returns (True, verdict_message) always (warn-only).

    Verdict logic (LR-1 grounded):
      1. origin/main unreachable          → INDETERMINATE (the only genuine one)
      2. .handoff-sha absent/malformed    → DRIFT (defect — artifact must exist)
      3. .handoff-sha == origin/main      → verified
      4. .handoff-sha != origin/main      → DRIFT (refresh the handoff)

    Always returns True (TIER_1 warn-only). The ms-enforce gate never blocks.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    # Step 1: live origin/main SHA — the GROUND anchor. Unreachable ground is
    # the ONLY genuine INDETERMINATE.
    live = _get_live_sha(repo_root)
    if live is None:
        verdict = (
            "WARNING: INDETERMINATE — origin/main is unreachable "
            "(git rev-parse origin/main failed); cannot verify handoff freshness. "
            "[GROUND: git rev-parse UNREACHABLE]"
        )
        print(verdict)
        return True, verdict

    live_short = live[:7]

    # Step 2: declared SHA from the committed .handoff-sha artifact.
    # ABSENCE → DRIFT (NOT INDETERMINATE) — this is the LR-1 brownout closure:
    # a missing machine artifact is a defect that must go red, never "not red".
    declared = _read_declared_sha(repo_root)
    if declared is None:
        verdict = (
            f"WARNING: DRIFT — {HANDOFF_SHA_FILE} is missing or malformed; "
            f"handoff freshness cannot be grounded against origin/main ({live_short}). "
            f"Create {HANDOFF_SHA_FILE} containing the origin/main SHA that "
            f"{HANDOFF_FILE} was last refreshed against. "
            "[GROUND: .handoff-sha ABSENT/MALFORMED]"
        )
        print(verdict)
        return True, verdict

    # Step 3: compare (declared may be short; live is full 40-char).
    if live.startswith(declared.lower()):
        verdict = (
            f"verified — {HANDOFF_SHA_FILE} says {declared!r}; "
            f"git rev-parse origin/main → {live_short!r} [GROUND: git rev-parse]"
        )
        return True, verdict

    verdict = (
        f"WARNING: DRIFT — {HANDOFF_SHA_FILE} says {declared!r}; "
        f"git rev-parse origin/main → {live_short!r} (full: {live}). "
        f"Handoff trails current origin/main — refresh {HANDOFF_FILE} and update "
        f"{HANDOFF_SHA_FILE} to the current SHA. [GROUND: git rev-parse]"
    )
    print(verdict)
    return True, verdict


def main() -> None:
    """CLI entry point for standalone use."""
    import sys
    _, msg = check()
    print(msg)
    # Always exit 0 — warn-only
    sys.exit(0)


if __name__ == "__main__":
    main()
