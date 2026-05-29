#!/usr/bin/env python3
"""audit_status_file_freshness.py — Detect stale status-file updates during Robot runs.

For each status file in a run dir (`.claude/run/status/*.md` or a supplied
`--run-dir`), checks that the "Last updated" timestamp either:

  (a) Advanced past the "Started" timestamp when streams were merged — i.e.,
      the file was actually updated during the run, not left frozen at the
      initial "Started" value despite showing MERGED streams; OR
  (b) Is not stale relative to now when the run is still active (configurable
      via `--max-stale-min`, default 60).

Prints WARNING-prefixed lines for each staleness finding.
Exits 0 always (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_status_file_freshness.py [--repo .] [--run-dir PATH]
                                               [--max-stale-min N]

Arguments:
  --repo          Path to repo root (default: auto-detect from script location)
  --run-dir       Override the run directory to scan (default: <repo>/.claude/run)
  --max-stale-min Minutes before a "Last updated" timestamp in an active run is
                  considered stale (default: 60)

Output:
  WARNING: <file> -- Last updated == Started but N merged stream(s) recorded
  WARNING: <file> -- Last updated is M minutes old (active run, threshold N min)
  (empty output or clean summary on stderr for a clean run / no active run)

Known false-positive classes:
  FP1 -- Single-stream waves where the orchestrator writes the status file only
         once (at the start and end simultaneously).  Counter: the check only
         fires when Started == Last updated AND there is >=1 merged stream,
         which is still informative even for single-stream waves.
  FP2 -- Archived run dirs where the operator manually edited the status file
         to correct timestamps (timestamps may legitimately look stale post-edit).
         Counter: --run-dir targeting a live .claude/run/ only; archive scans
         skip the wall-clock staleness check.
  FP3 -- Runs completed in under 1 minute (Started == Last updated by coincidence
         rather than neglect). Counter: only warn if >=1 merged stream is present;
         this is always informative regardless of run duration.
  FP4 -- Status files that use date-only format (YYYY-MM-DD) instead of ISO-8601
         with time component. Counter: date-only timestamps skip the wall-clock
         check (ambiguous); the Started == Last updated check still applies.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

# ---- Regex patterns ------------------------------------------------------

# Match: **Last updated:** 2026-05-29T05:41:11Z
# or:    **Last updated:** 2026-05-29
_TS_PATTERN = re.compile(
    r"\*\*Last updated:\*\*\s+(\S+)"
)

# Match: **Started:** 2026-05-29T05:41:11Z  or  **Started:** 2026-05-29 (robot start)
_STARTED_PATTERN = re.compile(
    r"\*\*Started:\*\*\s+(\S+)"
)

# Match stream-merge events:
#   "-- MERGED (commit_sha"  or  "-> MERGED (commit_sha"  or  "DISPATCHED -> MERGED"
# Covers patterns like:
#   - A (verify.py)  -- MERGED (04796ce; 9 tests)
#   - A (verify.py)  -> MERGED (commit abc1234)
#   - A (scrub.py)   -- DISPATCHED -> MERGED (0efd4d1; 55 tests)
_MERGED_STREAM_RE = re.compile(
    r"(?:--|\xe2\x80\x94|->|→)\s*MERGED\b",
    re.IGNORECASE,
)

# Also match Unicode dash variants that appear in markdown status files:
# U+2014 EM DASH (—) and U+2192 ARROW (→)
_MERGED_STREAM_RE2 = re.compile(
    r"(?:—|→|--|-\s*>)\s*MERGED\b",
    re.IGNORECASE,
)

# Accepted ISO-8601 variants
_ISO_FULL = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})Z?$")
_DATE_ONLY = re.compile(r"^(\d{4}-\d{2}-\d{2})$")


def _parse_timestamp(ts_str: str) -> tuple:
    """Parse a timestamp string.  Returns (datetime or None, is_date_only).

    Handles:
      2026-05-29T05:41:11Z   -> (datetime(2026,5,29,5,41,11), False)
      2026-05-29T05:41:11    -> (datetime(2026,5,29,5,41,11), False)
      2026-05-29             -> (datetime(2026,5,29,0,0,0),   True)
    """
    ts_str = ts_str.strip().rstrip("Z")
    m = _ISO_FULL.match(ts_str)
    if m:
        try:
            dt = datetime.datetime(
                int(ts_str[:4]), int(ts_str[5:7]), int(ts_str[8:10]),
                int(ts_str[11:13]), int(ts_str[14:16]), int(ts_str[17:19]),
            )
            return dt, False
        except (ValueError, IndexError):
            return None, False

    m = _DATE_ONLY.match(ts_str)
    if m:
        try:
            dt = datetime.datetime(
                int(ts_str[:4]), int(ts_str[5:7]), int(ts_str[8:10]),
            )
            return dt, True
        except ValueError:
            return None, True

    return None, False


def _count_merged_streams(content: str) -> int:
    """Return the number of stream-merge event lines in the file."""
    count = len(_MERGED_STREAM_RE.findall(content))
    count += len(_MERGED_STREAM_RE2.findall(content))
    # Deduplicate: a line may match both patterns; count unique lines instead
    lines_with_merge = [
        ln for ln in content.splitlines()
        if _MERGED_STREAM_RE.search(ln) or _MERGED_STREAM_RE2.search(ln)
    ]
    return len(lines_with_merge)


def _is_active_run_dir(run_dir: Path) -> bool:
    """Heuristic: if run_dir is .claude/run (not run-archive), treat as active."""
    parts = run_dir.resolve().parts
    for i, p in enumerate(parts):
        if p == ".claude":
            next_parts = parts[i + 1:]
            if not next_parts:
                continue
            if next_parts[0] == "run":
                # Check it's not a run-archive subdirectory
                if len(next_parts) < 2 or "archive" not in next_parts[0].lower():
                    return True
    return False


def audit_run_dir(
    run_dir: Path,
    max_stale_min: int,
    is_active: bool,
) -> list:
    """Audit all *.md status files in run_dir/status/ (or run_dir itself).

    Returns a list of WARNING-prefixed finding strings.
    """
    warnings = []

    # Accept: run_dir/status/*.md  OR  run_dir/*.md  OR  run_dir as direct file
    if run_dir.is_file():
        status_files = [run_dir]
    else:
        status_subdir = run_dir / "status"
        if status_subdir.is_dir():
            status_files = sorted(status_subdir.glob("*.md"))
        else:
            status_files = sorted(run_dir.glob("*.md"))

    if not status_files:
        return warnings  # nothing to check

    # Build naive UTC datetime without using deprecated utcnow()
    _utc_now = datetime.datetime.now(datetime.timezone.utc)
    now = datetime.datetime(
        _utc_now.year, _utc_now.month, _utc_now.day,
        _utc_now.hour, _utc_now.minute, _utc_now.second,
    )

    for sf in status_files:
        try:
            content = sf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Extract timestamps
        m_updated = _TS_PATTERN.search(content)
        m_started = _STARTED_PATTERN.search(content)

        if not m_updated:
            # No "Last updated" field -- cannot assess freshness
            continue

        last_updated_str = m_updated.group(1)
        last_updated, lu_date_only = _parse_timestamp(last_updated_str)

        if last_updated is None:
            continue  # unparseable timestamp

        started_str = m_started.group(1) if m_started else None
        started = None
        started_date_only = False
        if started_str:
            started, started_date_only = _parse_timestamp(started_str)

        merged_count = _count_merged_streams(content)

        # Check 1: Started == Last updated but merges were recorded
        # This fires when a status file was never updated after the initial write
        # even though stream merges occurred (all merges recorded in one final bulk
        # write at the same timestamp as the start).
        if (
            merged_count >= 1
            and started is not None
            and last_updated is not None
            and not lu_date_only
            and not started_date_only
            and started == last_updated
        ):
            warnings.append(
                "WARNING: {} -- Last updated ({}) == Started but "
                "{} merged stream(s) recorded; "
                "status file may not have been updated during the run".format(
                    sf.name, last_updated_str, merged_count
                )
            )

        # Check 2: Active-run wall-clock staleness
        # Only applies when scanning a live .claude/run/ directory and
        # the timestamp is a full ISO-8601 (not date-only, which is ambiguous).
        if is_active and not lu_date_only and last_updated is not None:
            age_min = (now - last_updated).total_seconds() / 60.0
            if age_min > max_stale_min:
                warnings.append(
                    "WARNING: {} -- Last updated is {:.0f} min ago "
                    "(threshold: {} min); "
                    "active run status file may be stale".format(
                        sf.name, age_min, max_stale_min
                    )
                )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo", default=None,
        help="Path to repo root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--run-dir", default=None, dest="run_dir",
        help="Override run directory to scan "
             "(default: <repo>/.claude/run; use 'none' to skip)",
    )
    parser.add_argument(
        "--max-stale-min", type=int, default=60, dest="max_stale_min",
        help="Minutes before a Last-updated timestamp in an active run is "
             "considered stale (default: 60)",
    )
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        repo = Path(__file__).resolve().parent.parent

    if args.run_dir and args.run_dir.lower() == "none":
        print("OK: no run dir to scan (--run-dir none)", file=sys.stderr)
        sys.exit(0)

    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
    else:
        run_dir = repo / ".claude" / "run"

    if not run_dir.exists():
        print("OK: no active run directory found -- clean pass", file=sys.stderr)
        sys.exit(0)

    # Determine whether this is an active run vs. an archived run
    is_active = _is_active_run_dir(run_dir)

    warnings = audit_run_dir(run_dir, args.max_stale_min, is_active)

    for w in warnings:
        print(w)

    if warnings:
        print(
            "\nSummary: {} status-file freshness warning(s)".format(len(warnings)),
            file=sys.stderr,
        )
    else:
        status_subdir = run_dir / "status"
        scan_dir = status_subdir if status_subdir.is_dir() else run_dir
        if scan_dir.is_dir():
            count = len(list(scan_dir.glob("*.md")))
        elif run_dir.is_file():
            count = 1
        else:
            count = 0
        print(
            "OK: {} status file(s) checked -- all fresh".format(count),
            file=sys.stderr,
        )

    sys.exit(0)  # always exit 0 -- warn-only


if __name__ == "__main__":
    main()
