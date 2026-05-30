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
  python3 tools/audit_backlog_stale.py --check-rings   # cross-repo (repo,file,syntax) coverage

Output:
  WARNING: docs/BACKLOG.md:<line>  bare [ ] entry is <N> days old: <text>
  (one line per stale bare-[ ] entry; empty output means all are triaged or recent)

  In --check-rings mode, per-ring verdicts using the pinned GROUND/XREF/
  INDETERMINATE vocabulary (see CLAUDE.md "Knowledge-Lifecycle & reconciliation").

Cross-repo (repo, file, syntax) triage-queue REGISTRY (BATCH-11 S2, P2)
----------------------------------------------------------------------
SLOP's BACKLOG-triage doctrine is not SLOP-only: each of the 3 repo rings keeps
its own triage queue. The hardcoded SLOP-only path (`<repo>/docs/BACKLOG.md`)
was the single-entity-hardcode the Reuse-and-blast-radius checkpoint exists to
catch. This file now PARAMETERIZES THE INTERFACE over the ring set via the
`RING_REGISTRY` below (the gate iterates a registry; it does not hardcode a
second path). To add/move a ring, edit `RING_REGISTRY` — nothing else.

Ring-coverage semantics (stated verbatim so S3 and the audit can rely on them):
  * present-ring-with-NO-registry-row  -> DRIFT  (the SEAM itself is the gap;
    a triage queue exists on disk for a known ring but the registry omits it).
  * registered-but-absent / unreachable -> INDETERMINATE (loud, never silent;
    the per-ring reachability is also a probe in tools/probe_registry.json, so
    S1's aging engine ages a sustained INDETERMINATE to DRIFT).
These are GROUND verdicts: each ring's row is reconciled against a filesystem
stat of its queue file every run — never stored-and-trusted.

S3 contract (DO NOT BREAK): the SLOP-ring scan signature is unchanged —
`load_backlog(repo)` + `_parse_entries(text)` + `main()`'s `--repo`/`--today`
flags behave exactly as before. The ring registry and `--check-rings` mode are
ADDITIVE; S3 adds park-rule parser legs to the same per-entry path.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

# Threshold in days before a bare [ ] entry is considered stale.
STALE_DAYS = 14

# ---------------------------------------------------------------------------
# Cross-repo (repo, file, syntax) triage-queue REGISTRY  (BATCH-11 S2, P2)
# ---------------------------------------------------------------------------
# PARAMETERIZE-THE-INTERFACE: the gate iterates this registry over the 3 repo
# rings instead of hardcoding `<repo>/docs/BACKLOG.md`. Each row is a
# (repo, file, syntax) triple plus a `present_expected` honesty flag.
#
# Fields:
#   ring             stable ring id (matches the probe-registry id suffix)
#   repo             absolute path to the repo root
#   queue_file       repo-relative path to the triage queue file
#   syntax           the triage-token syntax this queue uses (informational +
#                    consumed by S3's per-ring parser-leg selection)
#   present_expected True  = a queue file SHOULD exist for this ring on disk;
#                            its absence is a real INDETERMINATE worth surfacing.
#                    False = no canonical single queue resolved at write-time
#                            (e.g. mediastack fragments work across many
#                            docs/TODO_*.md topic files); the row is honestly
#                            INDETERMINATE and carries a BACKLOG follow-up so it
#                            is NOT a silent TODO-hole.
#   note             rationale / resolution provenance.
#
# A "present ring" (queue file exists on disk) that has NO row here is the SEAM
# gap -> DRIFT. We cannot enumerate that statically (it is the very thing we are
# missing a row for), so the coverage assertion + its red-path test live in
# tests/test_backlog_ring_registry.py: they feed a known on-disk-ring-with-no-row
# and assert DRIFT.
RING_REGISTRY: list[dict] = [
    {
        "ring": "slop",
        "repo": "/home/stack/code/slop",
        "queue_file": "docs/BACKLOG.md",
        "syntax": "slop-bracket",  # `[ ]` / `[park]` / `[→ S-NN]` / `[x]` / `[—]`
        "present_expected": True,
        "note": "SLOP canonical triage queue (the original hardcoded path).",
    },
    {
        "ring": "slop_process",
        "repo": "/home/stack/v5",
        "queue_file": "docs/TODO.md",
        "syntax": "slop-bracket",  # same `[ ]`/`[x]` bracket syntax (verified 2026-05-30)
        "present_expected": True,
        "note": "slop-process: resolved to docs/TODO.md (84KB persistent task list, "
                "same [ ]/[x] bracket syntax as SLOP). Verified on disk 2026-05-30.",
    },
    {
        "ring": "mediastack",
        "repo": "/home/stack/code/mediastack",
        "queue_file": "docs/TODO.md",  # placeholder canonical path — does NOT exist
        "syntax": "slop-bracket",
        "present_expected": False,
        "note": "mediastack: NO single canonical triage queue resolved at write-time "
                "(2026-05-30). Work is fragmented across many docs/TODO_*.md topic "
                "files; there is no docs/TODO.md or docs/BACKLOG.md aggregate. Row "
                "lands INDETERMINATE (NOT a silent TODO-hole) + BACKLOG follow-up "
                "(docs/BACKLOG.md) to pick/create a canonical queue. When one is "
                "chosen, set queue_file + present_expected:True here.",
    },
]

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
    """Load <repo>/docs/BACKLOG.md, return empty string if missing.

    S3-CONTRACT: signature unchanged — the SLOP ring still resolves
    docs/BACKLOG.md under `repo`. Generalized loading for non-SLOP rings goes
    through `load_queue(repo, queue_file)` (additive); this stays the SLOP path.
    """
    return load_queue(repo, "docs/BACKLOG.md")


def load_queue(repo: Path, queue_file: str) -> str:
    """Load <repo>/<queue_file>, return empty string if missing.

    The (repo, file, syntax)-registry generalization of load_backlog: any ring's
    queue file is read the same way. Empty string == file absent/unreadable
    (the caller maps that to INDETERMINATE for a registered ring).
    """
    path = repo / queue_file
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Cross-repo ring-coverage reconciliation (GROUND — filesystem stat per ring)
# ---------------------------------------------------------------------------

def resolve_rings(registry: list[dict] | None = None) -> list[dict]:
    """Reconcile every registered ring against the filesystem (GROUND).

    For each row, stat its (repo, queue_file) and emit a verdict using the
    pinned vocabulary:
      * file present                       -> 'verified'      (GROUND match)
      * absent + present_expected True      -> 'INDETERMINATE' (loud; ages via S1)
      * absent + present_expected False     -> 'INDETERMINATE' (honest TODO-hole,
                                               carries a BACKLOG follow-up)
    Returns a list of result dicts (one per ring) with keys:
      ring, repo, queue_file, syntax, present, verdict, detail.

    NOTE: the present-ring-with-NO-row -> DRIFT verdict is NOT decidable here
    (a missing row cannot list itself). That seam-gap verdict is produced by
    `coverage_drift(on_disk_rings)` and exercised by the red-path test.
    """
    reg = RING_REGISTRY if registry is None else registry
    results: list[dict] = []
    for row in reg:
        repo = Path(row["repo"])
        queue_file = row["queue_file"]
        present = (repo / queue_file).exists()
        if present:
            verdict = "verified"
            detail = "GROUND: queue file present"
        else:
            verdict = "INDETERMINATE"
            if row.get("present_expected", True):
                detail = (
                    "INDETERMINATE: registered ring queue file absent/unreachable "
                    "(ages via tools/probe_registry.json -> S1 aging engine)"
                )
            else:
                detail = (
                    "INDETERMINATE: no canonical queue resolved at write-time "
                    "(BACKLOG follow-up tracks picking one); NOT a silent TODO-hole"
                )
        results.append({
            "ring": row["ring"],
            "repo": str(repo),
            "queue_file": queue_file,
            "syntax": row["syntax"],
            "present": present,
            "verdict": verdict,
            "detail": detail,
        })
    return results


def coverage_drift(on_disk_rings: list[tuple[str, str, str]],
                   registry: list[dict] | None = None) -> list[dict]:
    """SEAM-gap check: a ring whose queue file is present ON DISK but has NO
    registry row is a DRIFT (the registry is the gap).

    `on_disk_rings` is a list of (ring_id, repo, queue_file) the caller has
    independently established to exist (e.g. by scanning the known repo roots).
    Returns a DRIFT result dict per uncovered on-disk ring. Empty == covered.

    This is the leg the red-path test feeds a known-bad input to: a present
    ring not in RING_REGISTRY -> DRIFT (proves the gate can go red).
    """
    reg = RING_REGISTRY if registry is None else registry
    known = {row["ring"] for row in reg}
    drifts: list[dict] = []
    for ring_id, repo, queue_file in on_disk_rings:
        if ring_id not in known:
            drifts.append({
                "ring": ring_id,
                "repo": repo,
                "queue_file": queue_file,
                "verdict": "DRIFT",
                "detail": (
                    "DRIFT: triage queue present on disk for a known ring but the "
                    "(repo,file,syntax) registry has NO row — the SEAM is the gap"
                ),
            })
    return drifts


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


def _run_check_rings() -> None:
    """Print per-ring (repo,file,syntax) coverage verdicts. Warn-only, exit 0."""
    results = resolve_rings()
    indeterminate = 0
    for r in results:
        if r["verdict"] == "verified":
            print(f"verified: ring {r['ring']} [{r['syntax']}] -> "
                  f"{r['repo']}/{r['queue_file']}  ({r['detail']})")
        else:  # INDETERMINATE
            indeterminate += 1
            print(f"INDETERMINATE: ring {r['ring']} [{r['syntax']}] -> "
                  f"{r['repo']}/{r['queue_file']}  ({r['detail']})", file=sys.stderr)
    print(
        f"\nSummary: {len(results)} ring(s) in RING_REGISTRY; "
        f"{indeterminate} INDETERMINATE (registered-but-absent/unreachable). "
        f"present-ring-with-no-row -> DRIFT (see coverage_drift + red-path test).",
        file=sys.stderr,
    )
    sys.exit(0)  # warn-only — TIER_1, no auto-promote


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
    parser.add_argument(
        "--check-rings", action="store_true",
        help="Cross-repo mode: reconcile every (repo,file,syntax) ring in "
             "RING_REGISTRY against the filesystem (GROUND) and print per-ring "
             "verdicts (verified / INDETERMINATE). Warn-only; exit 0.",
    )
    args = parser.parse_args()

    if args.check_rings:
        _run_check_rings()
        return

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
