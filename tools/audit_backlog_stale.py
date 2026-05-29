#!/usr/bin/env python3
"""audit_backlog_stale.py — BACKLOG staleness audit: bare `[ ]` entries older than 14 days.

Parses docs/BACKLOG.md and flags any entry whose status token is bare `[ ]`
(not scheduled, parked, done, or won't-fix) AND whose provenance date is
older than 14 days from the reference date.

Status tokens that are NOT flagged:
  `[→ S-NN]`     — scheduled into a wave
  `[→ S-NN-X]`   — scheduled with stream suffix
  `[park]`        — explicitly parked with re-eval trigger
  `[parked]`      — alternate spelling of park
  `[x]`           — done
  `[—]`           — won't fix / superseded

Only bare `[ ]` (possibly with trailing spaces before the closing `]`) is flagged.

Provenance date detection:
  - Primary: a `Date added: YYYY-MM-DD` fragment anywhere on the same bullet line
    or within a 4-line window below it (for multi-line bullets).
  - Fallback: if no date is found for an entry, it is NOT flagged (conservative;
    false-negative is preferable to false-positive nagging).

Known false-positive classes (documented — do NOT change without updating this docstring):
  1. Entries in the "Done (recent)" or "Won't fix / superseded" sections that use
     `[x]` or `[—]` tokens are correctly excluded. If a `[ ]` somehow appears in
     those sections (copy-paste error), it will be flagged — intentional.
  2. Entries in the "Status legend" header section (`## Status legend`) use `[ ]`
     as an illustrative example. This scanner skips lines that appear before the
     first `---` rule separator in the file, which normally places the legend above
     the actual backlog entries. If the file is restructured to put `[ ]` legend
     lines after the first `---`, they may be incorrectly flagged.
  3. Multi-line bullet points: the scanner looks within a 4-line window below the
     bullet's `- ` line for a `Date added:` field. If the date is further than 4
     lines below, the entry will not be flagged (safe false-negative, not a nag).

Exit code: 0 always (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_backlog_stale.py [--repo /path/to/repo] [--today YYYY-MM-DD]
  python3 tools/audit_backlog_stale.py --repo . --today 2026-06-15

Output:
  WARNING: docs/BACKLOG.md:<line>  bare [ ] entry is <N> days old: <text>
  (one line per stale bare-[ ] entry; empty output means all are triaged or recent)
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

# Threshold in days before a bare [ ] entry is considered stale.
STALE_DAYS = 14

# Regex to detect bare [ ] status token at the start of a bullet line.
# Matches: `- \`[ ]\`` or `- [ ]` at the start of a trimmed line.
# Does NOT match: `[→`, `[x]`, `[—]`, `[park`, `[parked`.
_BARE_OPEN_RE = re.compile(
    r"^-\s+(?:`\[\s*\]`|\[\s*\])"
)

# Tokens that mean "not bare open"
_TRIAGED_TOKENS = re.compile(
    r"(?:"
    r"`\[→"          # [→ S-NN] scheduled
    r"|`\[x\]`"      # [x] done
    r"|`\[—\]`"      # [—] won't fix
    r"|\[→"          # bare [→ (without backticks)
    r"|\[x\]"        # bare [x]
    r"|\[—\]"        # bare [—]
    r"|`\[park"      # [park] / [parked]
    r"|\[park"       # bare [park] / [parked]
    r")"
)

# Regex to extract a date from "Date added: YYYY-MM-DD"
_DATE_ADDED_RE = re.compile(r"Date added:\s*(\d{4}-\d{2}-\d{2})")


def load_backlog(repo: Path) -> str:
    """Load docs/BACKLOG.md, return empty string if missing."""
    backlog = repo / "docs" / "BACKLOG.md"
    if not backlog.exists():
        return ""
    return backlog.read_text(encoding="utf-8", errors="replace")


def _parse_entries(text: str) -> list[tuple[int, str, datetime.date | None]]:
    """Parse BACKLOG.md and return list of (lineno, line_text, date_or_None)
    for each bare `[ ]` entry found after the first horizontal rule separator.

    Returns only entries where the line starts with `- \\`[ ]\\`` or `- [ ]`
    and does NOT have a triaged token.
    """
    lines = text.splitlines()
    entries: list[tuple[int, str, datetime.date | None]] = []

    # Skip everything before the first `---` separator (header / legend section).
    past_first_sep = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not past_first_sep:
            if stripped == "---":
                past_first_sep = True
            continue

        # Must look like a bare-open bullet.
        if not _BARE_OPEN_RE.match(stripped):
            continue

        # Confirm there's no triaged token on this line.
        if _TRIAGED_TOKENS.search(stripped):
            continue

        # This is a genuine bare [ ] entry.
        # Look for "Date added: YYYY-MM-DD" on this line or within 4 lines below.
        date_found: datetime.date | None = None
        window = lines[i : i + 5]  # inclusive of current line
        for wline in window:
            m = _DATE_ADDED_RE.search(wline)
            if m:
                try:
                    date_found = datetime.date.fromisoformat(m.group(1))
                except ValueError:
                    pass
                break

        entries.append((i + 1, line, date_found))  # 1-based lineno

    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=None,
        help="Path to repo root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--today", default=None,
        help="Reference date as YYYY-MM-DD (default: system date). "
             "Used to make staleness checks deterministic in tests.",
    )
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        # Script lives in tools/, repo is one level up.
        repo = Path(__file__).resolve().parent.parent

    if args.today:
        try:
            today = datetime.date.fromisoformat(args.today)
        except ValueError:
            print(f"ERROR: --today must be YYYY-MM-DD, got: {args.today!r}", file=sys.stderr)
            sys.exit(0)
    else:
        today = datetime.date.today()

    text = load_backlog(repo)
    if not text:
        print(
            "WARNING: docs/BACKLOG.md not found — cannot check for stale entries",
            file=sys.stderr,
        )
        sys.exit(0)

    entries = _parse_entries(text)

    stale: list[tuple[int, str, int]] = []
    no_date: list[tuple[int, str]] = []

    for lineno, line_text, date_found in entries:
        if date_found is None:
            no_date.append((lineno, line_text))
            continue
        age = (today - date_found).days
        if age > STALE_DAYS:
            stale.append((lineno, line_text, age))

    for lineno, line_text, age in stale:
        print(
            f"WARNING: docs/BACKLOG.md:{lineno}  "
            f"bare [ ] entry is {age} days old: {line_text.strip()[:120]}"
        )

    # Summary to stderr.
    if stale:
        print(
            f"\nSummary: {len(stale)} stale bare [ ] entry/entries "
            f"(>{STALE_DAYS} days without triage)",
            file=sys.stderr,
        )
        if no_date:
            print(
                f"  Note: {len(no_date)} bare [ ] entry/entries have no 'Date added:' "
                "provenance — not flagged (conservative).",
                file=sys.stderr,
            )
    else:
        total_bare = len(entries)
        if total_bare:
            print(
                f"OK: {total_bare} bare [ ] entry/entries found; "
                f"none older than {STALE_DAYS} days",
                file=sys.stderr,
            )
        else:
            print("OK: no bare [ ] entries in docs/BACKLOG.md", file=sys.stderr)
        if no_date:
            print(
                f"  Note: {len(no_date)} bare [ ] entry/entries have no 'Date added:' "
                "provenance — not flagged (conservative).",
                file=sys.stderr,
            )

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
