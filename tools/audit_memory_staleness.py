#!/usr/bin/env python3
"""audit_memory_staleness.py — Memory-file staleness audit.

Scans the auto-memory directory for entries that contain dated language
(explicit YYYY-MM-DD dates, or tokens like "today" / "this session") and
warns when any such entry has a date that is older than 60 days.

The goal is to surface memory entries that may reference time-sensitive
context (e.g. "the key leaked 2026-05-28", "today's retro found X",
"this session completed S-47") so an operator can decide whether to prune,
update, or keep them.

Conservative policy — only flags entries with an **explicit, parseable
YYYY-MM-DD date** that is more than 60 days before the reference date.
Entries containing informal tokens like "today" or "this session" without
a parseable date are NOT flagged (too noisy; the date-based flag is the
actionable signal).

Exit code: 0 always (warn-only; visibility, not blocking).

Known false-positive classes
-----------------------------
1. Historical records intentionally dated (incident write-ups, retro
   summaries): these ARE old by design. An operator who receives a warning
   for `project_tailscale_key_leak_2026_05_28.md` should simply note the
   entry is an archival record, not stale guidance, and re-evaluate
   periodically.
2. Date strings inside semantic version labels or commit SHAs:
   e.g. "commit 2026abc" — the regex requires the full YYYY-MM-DD
   hyphen-separated form, so these are not matched.
3. Memory files that use dates as examples / illustrations:
   the scanner checks the file-level date against the threshold; if a file
   has many dates and only some are old, the EARLIEST date in the file
   triggers the warning (conservative: flag if any part of the file may be
   stale).
4. Future-dated entries: any date AFTER the reference date is not flagged
   (e.g. a scheduled future task written into memory).

Usage
------
  python3 tools/audit_memory_staleness.py [--repo .] [--memory-dir PATH]
                                           [--today YYYY-MM-DD] [--days N]

  --repo DIR         Repo root (default: parent of script's parent dir).
  --memory-dir PATH  Path to memory dir to scan.
                     Default: ~/.claude/projects/-home-stack-code-slop/memory/
  --today YYYY-MM-DD Reference date for deterministic testing (default: today).
  --days N           Staleness threshold in days (default: 60).

Output
-------
  WARNING: <relative-path>  oldest date <DATE> is <N> days old (threshold <T>d)
  (one WARNING line per stale file; empty output means no stale entries found)
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Matches a bare YYYY-MM-DD date token anywhere in text.
# Requires word boundaries so partial matches like "20260528" are NOT matched.
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Default memory directory path (matches SLOP project layout).
_DEFAULT_MEMORY_DIR = (
    Path.home() / ".claude" / "projects" / "-home-stack-code-slop" / "memory"
)


def _find_oldest_past_date(text: str, today: date) -> date | None:
    """Return the oldest past date found in *text*, or None if no past dates."""
    oldest: date | None = None
    for m in _DATE_RE.finditer(text):
        raw = m.group(1)
        try:
            d = date.fromisoformat(raw)
        except ValueError:
            continue
        if d > today:
            # future date — skip
            continue
        if oldest is None or d < oldest:
            oldest = d
    return oldest


def scan_memory_dir(
    memory_dir: Path,
    today: date,
    threshold_days: int,
) -> list[tuple[Path, date, int]]:
    """Scan *memory_dir* and return list of (path, oldest_date, age_days) for stale files.

    A file is stale when its oldest parseable past date is more than
    *threshold_days* before *today*.
    """
    stale: list[tuple[Path, date, int]] = []
    if not memory_dir.is_dir():
        return stale

    for path in sorted(memory_dir.iterdir()):
        if not path.is_file():
            continue
        # Only scan text files (markdown primarily)
        if path.suffix not in (".md", ".txt", ".yaml", ".yml", ".json", ""):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        oldest = _find_oldest_past_date(text, today)
        if oldest is None:
            continue

        age = (today - oldest).days
        if age > threshold_days:
            stale.append((path, oldest, age))

    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=None,
        help="Path to repo root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--memory-dir", default=None,
        help=(
            "Path to memory directory to scan "
            f"(default: {_DEFAULT_MEMORY_DIR})"
        ),
    )
    parser.add_argument(
        "--today", default=None,
        help="Reference date YYYY-MM-DD for deterministic testing (default: today)",
    )
    parser.add_argument(
        "--days", type=int, default=60,
        help="Staleness threshold in days (default: 60)",
    )
    args = parser.parse_args()

    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(f"ERROR: --today value {args.today!r} is not a valid YYYY-MM-DD date",
                  file=sys.stderr)
            sys.exit(0)
    else:
        today = date.today()

    if args.memory_dir:
        memory_dir = Path(args.memory_dir).resolve()
    else:
        memory_dir = _DEFAULT_MEMORY_DIR

    stale = scan_memory_dir(memory_dir, today, args.days)

    if not stale:
        print(
            f"OK: no memory entries with dates older than {args.days} days "
            f"(scanned {memory_dir})",
            file=sys.stderr,
        )
    else:
        for path, oldest, age in stale:
            # Use a short relative-ish label: just the filename
            label = path.name
            print(
                f"WARNING: {label}  oldest date {oldest} is {age} days old "
                f"(threshold {args.days}d)"
            )
        print(
            f"\nSummary: {len(stale)} stale memory file(s) found in {memory_dir}",
            file=sys.stderr,
        )

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
