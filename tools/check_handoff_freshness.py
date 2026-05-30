#!/usr/bin/env python3
"""
tools/check_handoff_freshness.py — Handoff SHA freshness checker (S-75 Stream C).

Verifies that the SHA declared in docs/MANAGER-HANDOFF.md for origin/main
matches the live value of ``git rev-parse origin/main``.

This is GROUND-class: it touches git physics (git rev-parse), so verdicts
may say "verified" or "DRIFT". Unreachable origin or absent/unparseable
SHA line → INDETERMINATE (loud, never silent OK).

Verdict vocabulary (PINNED — Stream E contract):
  verified      — GROUND match (declared SHA is a prefix of live SHA)
  DRIFT         — GROUND mismatch (declared SHA does NOT match live SHA)
  INDETERMINATE — unreachable ground truth or unparseable handoff

ms-enforce registration: see check_handoff_freshness() thin wrapper at the
bottom of this module + TIER_1 append block in ms-enforce.

Promotion-to-blocking trigger (TIER_1 gate graduation):
  Promote to blocking when two consecutive batches show DRIFT without a
  corresponding handoff update commit in the batch sweep. Current tier:
  warn-only (TIER_1), always returns True from the ms-enforce wrapper.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Canonical handoff file path (relative to repo root)
HANDOFF_FILE = Path("docs") / "MANAGER-HANDOFF.md"

# Regex to extract the 7-char short SHA from the bold bullet line.
# Matches: - **origin/main at `<SHA>`** — ...
# Declared SHA is 7-char short; live SHA is full 40-char.
# We compare by prefix (declared prefix of live full SHA).
_SHA_LINE_RE = re.compile(
    r"^\s*-\s+\*\*origin/main\s+at\s+`([0-9a-f]{4,40})`\*\*",
    re.IGNORECASE,
)


def _parse_declared_sha(handoff_path: Path) -> str | None:
    """Return the declared SHA string from MANAGER-HANDOFF.md, or None if absent/unparseable."""
    try:
        text = handoff_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = _SHA_LINE_RE.match(line)
        if m:
            return m.group(1)
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

    Verdict format:
      verified  — handoff says <declared>; git rev-parse origin/main → <live> [GROUND: git rev-parse]
      DRIFT     — WARNING: handoff says <declared>; git rev-parse origin/main → <live> [GROUND: git rev-parse]
      INDETERMINATE — WARNING: <reason> [GROUND: git rev-parse UNREACHABLE / HANDOFF UNPARSEABLE]

    Always returns True (TIER_1 warn-only). The ms-enforce gate never blocks.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    handoff_path = repo_root / HANDOFF_FILE

    # Step 1: parse declared SHA
    declared = _parse_declared_sha(handoff_path)
    if declared is None:
        if not handoff_path.exists():
            reason = f"handoff file not found: {handoff_path}"
        else:
            reason = (
                f"could not parse origin/main SHA from {handoff_path} "
                "(expected bold bullet: - **origin/main at `<SHA>`**)"
            )
        verdict = (
            f"WARNING: INDETERMINATE — {reason} "
            "[GROUND: git rev-parse UNREACHABLE / HANDOFF UNPARSEABLE]"
        )
        print(verdict)
        return True, verdict

    # Step 2: get live SHA from origin/main
    live = _get_live_sha(repo_root)
    if live is None:
        verdict = (
            f"WARNING: INDETERMINATE — origin/main is unreachable "
            f"(declared in handoff: {declared!r}); cannot verify. "
            "[GROUND: git rev-parse UNREACHABLE]"
        )
        print(verdict)
        return True, verdict

    live_short = live[:7]

    # Step 3: compare — declared is a short prefix; live is full 40-char
    # Match if declared is a prefix of live (case-insensitive)
    if live.startswith(declared.lower()):
        verdict = (
            f"verified — handoff says {declared!r}; "
            f"git rev-parse origin/main → {live_short!r} "
            "[GROUND: git rev-parse]"
        )
        return True, verdict
    else:
        verdict = (
            f"WARNING: DRIFT — handoff says {declared!r}; "
            f"git rev-parse origin/main → {live_short!r} (full: {live}). "
            "Update docs/MANAGER-HANDOFF.md to reflect the current origin/main SHA. "
            "[GROUND: git rev-parse]"
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
