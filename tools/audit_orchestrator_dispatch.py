#!/usr/bin/env python3
"""audit_orchestrator_dispatch.py — Robot-mode dispatch audit: one-orchestrator-per-wave anti-pattern.

Scans ``.claude/run-archive/*/status/*.md`` for the ONE-ORCHESTRATOR-PER-WAVE
anti-pattern: multiple orchestrator status files written within the same hour
that reference DIFFERENT waves.  The correct doctrine is ONE orchestrator per
BATCH (which may handle many waves); one-per-wave wastes a session boundary and
loses cross-wave conflict-resolution context.

Detection heuristic:
  1. For each run-archive entry (``<archive>/<run>/status/*.md``), collect all
     status files whose name matches a wave-number pattern (``S-NN*.md`` or
     ``S-NNN*.md``).
  2. Parse the "Last updated:" or "**Last updated:**" timestamp from each file
     (ISO-8601 ``YYYY-MM-DDTHH:MM:SSZ`` or space-separated ``YYYY-MM-DD HH:MM:SS``
     or date-only ``YYYY-MM-DD``).
  3. Group status files by hour-bucket (``YYYY-MM-DD HH``), ignoring run-dir.
  4. Within each hour-bucket, check whether the wave status files are spread
     across MULTIPLE different run-dirs each covering DIFFERENT waves.
     - Same run-dir, multiple waves → ONE orchestrator per batch → CORRECT (no warn).
     - Different run-dirs, different waves → one orchestrator per wave → WARNING.

Exit code: 0 always (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_orchestrator_dispatch.py [--repo .]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# Matches wave-numbered status files: S-55.md, S-60-agent-fix.md, S-123.md, etc.
# Excludes BATCH-N-COMPLETE.md, ROUND-N-COMPLETE.md, etc.
_WAVE_FILE_RE = re.compile(r"^(S-\d+)", re.IGNORECASE)

# Timestamp patterns: extract (date, hour) from status file text.
# Handles: ISO-8601 with T separator, space-separated datetime, date-only.
# Looks for the date/time that appears right after a "Last updated:" or "Started:" label.
# The label may be wrapped in markdown bold (**...**).
_DATE_HOUR_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):")
_DATE_ONLY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class _StatusEntry(NamedTuple):
    run_dir: str   # e.g. "2026-05-29-batch4"
    wave_id: str   # e.g. "S-58"
    hour_bucket: str  # "YYYY-MM-DD HH" or "YYYY-MM-DD ??" when only date found
    filename: str  # for error messages


def _find_run_archive(repo: Path) -> Path | None:
    """Locate ``.claude/run-archive/`` in the repo (or main repo for worktrees)."""
    archive = repo / ".claude" / "run-archive"
    if archive.exists():
        return archive

    # Worktree: common gitdir is in a different place — climb to main repo.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if result.returncode == 0:
            git_common = Path(result.stdout.strip())
            if not git_common.is_absolute():
                git_common = (repo / git_common).resolve()
            main_repo = git_common.parent
            main_archive = main_repo / ".claude" / "run-archive"
            if main_archive.exists():
                return main_archive
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return None


def _parse_hour_bucket(text: str) -> str:
    """Extract 'YYYY-MM-DD HH' or 'YYYY-MM-DD ??' from status file text.

    Scans the first 10 lines of the file where the timestamp header lives.
    Uses the first date found in the header region; this avoids spurious matches
    from wave-branch SHA references or git log lines later in the file.
    """
    header_lines = text.splitlines()[:10]
    header = "\n".join(header_lines)

    m = _DATE_HOUR_RE.search(header)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = _DATE_ONLY_RE.search(header)
    if m:
        return f"{m.group(1)} ??"
    return "unknown"


def collect_status_entries(archive: Path) -> list[_StatusEntry]:
    """Walk run-archive/*/status/*.md and parse wave-numbered entries."""
    entries: list[_StatusEntry] = []

    for run_dir in sorted(archive.iterdir()):
        if not run_dir.is_dir():
            continue
        status_dir = run_dir / "status"
        if not status_dir.is_dir():
            continue

        for md_file in sorted(status_dir.glob("*.md")):
            wave_match = _WAVE_FILE_RE.match(md_file.name)
            if not wave_match:
                continue  # skip BATCH-N-COMPLETE.md, ROUND-N-COMPLETE.md, etc.

            wave_id = wave_match.group(1).upper()

            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            hour_bucket = _parse_hour_bucket(text)

            entries.append(_StatusEntry(
                run_dir=run_dir.name,
                wave_id=wave_id,
                hour_bucket=hour_bucket,
                filename=str(md_file),
            ))

    return entries


def detect_anti_pattern(entries: list[_StatusEntry]) -> list[str]:
    """Return WARNING lines for hour-buckets where DIFFERENT waves are in separate run-dirs.

    The correct pattern is ONE orchestrator per BATCH: one run-dir contains
    status files for ALL waves in the batch.  The anti-pattern is one run-dir
    per wave: each run-dir contains status files for only its own wave, and
    multiple such run-dirs appear in the same hour for DIFFERENT waves.

    Decision rule per known hour-bucket (``??`` and ``unknown`` buckets skipped):
    1. Build run_dir → {wave_id, ...} mapping within the hour.
    2. For each pair of run-dirs (A, B) active in that hour, check whether their
       wave-sets are disjoint (no shared waves) AND both have at least one unique
       wave.  Disjoint per-run-dir wave coverage suggests separate orchestrator
       sessions dispatched per wave rather than one session per batch.
    3. If ≥2 such disjoint run-dirs exist, emit a WARNING.

    This avoids false positives from:
    - One run-dir covering multiple waves (correct ONE-per-batch pattern).
    - The same wave appearing in two different run-dirs (retry batch — no anti-pattern).
    - Date-only timestamps where the hour is unknown (not enough info to judge).
    """
    # Group all entries by known hour_bucket (skip ambiguous buckets)
    by_hour: dict[str, list[_StatusEntry]] = {}
    for entry in entries:
        if entry.hour_bucket in ("unknown",) or entry.hour_bucket.endswith("??"):
            continue  # insufficient timestamp precision — skip
        by_hour.setdefault(entry.hour_bucket, []).append(entry)

    warnings: list[str] = []
    for hour_bucket, hour_entries in sorted(by_hour.items()):
        # Build run_dir → set of wave_ids
        run_waves: dict[str, set[str]] = {}
        for entry in hour_entries:
            run_waves.setdefault(entry.run_dir, set()).add(entry.wave_id)

        # Need ≥2 run-dirs to detect the anti-pattern
        if len(run_waves) < 2:
            continue

        # Find pairs of run-dirs whose wave-sets are completely disjoint.
        # Disjoint means each run-dir has waves the other doesn't share at all.
        run_dirs = sorted(run_waves)
        disjoint_pairs: list[tuple[str, str]] = []
        for i, rd_a in enumerate(run_dirs):
            for rd_b in run_dirs[i + 1:]:
                if run_waves[rd_a].isdisjoint(run_waves[rd_b]):
                    disjoint_pairs.append((rd_a, rd_b))

        if not disjoint_pairs:
            continue  # all run-dirs share at least one wave — no anti-pattern

        # Collect the run-dirs that are part of at least one disjoint pair
        offending_run_dirs: set[str] = set()
        for rd_a, rd_b in disjoint_pairs:
            offending_run_dirs.add(rd_a)
            offending_run_dirs.add(rd_b)

        # Build a compact spread summary
        wave_summary = []
        for rd in sorted(offending_run_dirs):
            waves_sorted = sorted(run_waves[rd])
            wave_summary.append(f"{rd}:{','.join(waves_sorted)}")

        all_waves = sorted({w for rd in offending_run_dirs for w in run_waves[rd]})
        offending_files = [e.filename for e in hour_entries if e.run_dir in offending_run_dirs]

        warnings.append(
            f"WARNING: one-orchestrator-per-wave anti-pattern detected — "
            f"hour={hour_bucket} "
            f"run-dirs={len(offending_run_dirs)} "
            f"waves={','.join(all_waves)} "
            f"spread=({'; '.join(wave_summary)})"
        )
        for fname in offending_files:
            warnings.append(f"  file: {fname}")

    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=None,
        help="Path to repo root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        # Script lives in tools/, repo is one level up
        repo = Path(__file__).resolve().parent.parent

    archive = _find_run_archive(repo)
    if archive is None:
        print("OK: .claude/run-archive/ not found — nothing to scan", file=sys.stderr)
        sys.exit(0)

    entries = collect_status_entries(archive)
    if not entries:
        print("OK: no wave status files found in run-archive", file=sys.stderr)
        sys.exit(0)

    warnings = detect_anti_pattern(entries)

    for line in warnings:
        print(line)

    if warnings:
        anti_count = sum(1 for w in warnings if w.startswith("WARNING:"))
        print(
            f"\nSummary: {anti_count} potential one-orchestrator-per-wave instance(s) "
            f"across {len(entries)} status file(s) — review whether these were "
            "separate orchestrator sessions for different waves (anti-pattern) or "
            "a single orchestrator writing multiple wave status files (correct).",
            file=sys.stderr,
        )
    else:
        print(
            f"OK: {len(entries)} status file(s) scanned — "
            "no one-orchestrator-per-wave anti-pattern detected",
            file=sys.stderr,
        )

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
