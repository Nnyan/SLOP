"""tools/process_access_requests.py — Access-requests queue processor.

Pure-stdlib CLI that reads docs/ACCESS-REQUESTS.md (or any queue file) and
applies pending entries in each category section.

Subcommands
-----------
list
    Show pending (``[ ]``) entries grouped by category.

process [--category install|upgrade|allow|deny] [--dry-run]
    Apply pending entries, flip status markers, write provenance notes.
    ``--dry-run`` shows proposed actions WITHOUT writing.

archive [--older-than 60d]
    Prune applied (``[x]``) entries older than N days.

Flags
-----
--allow-deny-additions
    Required to process any ``[deny]`` entries.  They are rare and
    tighten restrictions; require explicit opt-in.

Stream B applier interface
--------------------------
Stream B must provide ``tools/access_request_appliers.py`` that exposes:

    APPLIERS: dict[str, ApplierCallable]

Where ``ApplierCallable`` is:

    def apply(entry: dict, *, dry_run: bool, target_paths: dict[str, Path]) -> ApplyResult:
        ...

``entry`` is the parsed entry dict as returned by ``parse_queue_file()``:
    {
        "category":   str,            # "install" | "upgrade" | "allow" | "deny"
        "status":     str,            # "pending" | "applied" | "denied"
        "subject":    str,            # short name/package after first bold segment
        "raw_line":   str,            # the verbatim markdown bullet line
        "date":       str | None,     # date extracted from "Requested by: … (YYYY-MM-DD)"
        "source":     str | None,     # requestor string
        "line_index": int,            # 0-based index in the file's lines list
    }

``dry_run`` is True when --dry-run is passed (applier must not make changes).

``target_paths`` provides repo-root-relative resolved Paths:
    {
        "queue_file":        Path,    # docs/ACCESS-REQUESTS.md (or fixture)
        "settings_local":    Path,    # .claude/settings.local.json
        "requirements":      Path,    # requirements.txt
        "requirements_dev":  Path,    # requirements-dev.txt
    }

``ApplyResult`` must be a dict with at least:
    {
        "ok":     bool,   # True = success / dry-run preview, False = failure
        "action": str,    # human-readable one-line description of what was done
        "error":  str,    # non-empty only on failure
    }

If Stream B's module is absent, a built-in echo applier is used that logs the
entry and returns ok=True (dry_run-style preview).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

EntryDict = Dict[str, object]
ApplyResult = Dict[str, object]

# ---------------------------------------------------------------------------
# Defensive import of Stream B appliers
# ---------------------------------------------------------------------------

try:
    from tools.access_request_appliers import APPLIERS as _STREAM_B_APPLIERS  # type: ignore[import]
except ImportError:
    _STREAM_B_APPLIERS = None  # type: ignore[assignment]


def _echo_applier(entry: EntryDict, *, dry_run: bool, target_paths: dict) -> ApplyResult:
    """Built-in no-op applier used when Stream B module is absent."""
    action = (
        f"[echo] would apply {entry['category']} entry: {entry['subject']}"
        if dry_run
        else f"[echo] applied {entry['category']} entry: {entry['subject']} (no-op — Stream B absent)"
    )
    return {"ok": True, "action": action, "error": ""}


def _get_appliers() -> Dict[str, object]:
    """Return the applier map, falling back to echo for all categories."""
    categories = ["install", "upgrade", "allow", "deny"]
    if _STREAM_B_APPLIERS is not None:
        return dict(_STREAM_B_APPLIERS)
    return {cat: _echo_applier for cat in categories}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Match lines like:  - `[ ]` **[install] subject** — description
# Uses non-greedy .+? for subject so subjects containing '*' (e.g. Bash globs) match.
_STATUS_MARKER = re.compile(
    r"^(\s*-\s+)`(\[[ x—]\])`\s+\*\*\[(?P<category>install|upgrade|allow|deny)\]\s+(?P<subject>.+?)\*\*(?P<rest>.*)$",
    re.DOTALL,
)

# Detect a category section heading like "## `[install]` …"
_SECTION_HEADING = re.compile(
    r"^##\s+`\[(?P<category>install|upgrade|allow|deny)\]`",
)

# Date in "Requested by: … (YYYY-MM-DD)" or "(date)"
_DATE_PATTERN = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")

# Requested by: <source> pattern
_SOURCE_PATTERN = re.compile(r"Requested by:\s*([^.(]+)")

_STATUS_MAP = {
    "[ ]": "pending",
    "[x]": "applied",
    "[—]": "denied",
}
_STATUS_REVERSE = {v: k for k, v in _STATUS_MAP.items()}


def _classify_status(marker: str) -> str:
    return _STATUS_MAP.get(marker, "unknown")


def parse_queue_file(path: Path) -> List[EntryDict]:
    """Parse the ACCESS-REQUESTS.md queue file into a list of entry dicts.

    Each entry dict contains:
        category, status, subject, raw_line, date, source, line_index

    Entries may span multiple lines: the bullet line is the primary record,
    and indented continuation lines (starting with spaces) immediately following
    carry additional text such as "Requested by: <source> (YYYY-MM-DD)".
    Both formats are supported:
      - Single-line: all info in the bullet itself
      - Two-line: bullet + "  Requested by: ..." continuation
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: List[EntryDict] = []
    current_category: Optional[str] = None

    for idx, line in enumerate(lines):
        # Detect section heading to track current category
        heading_match = _SECTION_HEADING.match(line)
        if heading_match:
            current_category = heading_match.group("category")
            continue

        entry_match = _STATUS_MARKER.match(line)
        if entry_match and current_category:
            marker = entry_match.group(2)
            status = _classify_status(marker)
            category = entry_match.group("category")
            subject = entry_match.group("subject").strip()
            rest = entry_match.group("rest")

            # Collect text from indented continuation lines (e.g. "  Requested by: ...")
            continuation_text = rest
            next_idx = idx + 1
            while next_idx < len(lines) and lines[next_idx].startswith("  "):
                continuation_text += " " + lines[next_idx].strip()
                next_idx += 1

            # Extract date from combined text
            date_match = _DATE_PATTERN.search(continuation_text)
            date_val: Optional[str] = date_match.group(1) if date_match else None

            # Extract source / requested-by from combined text
            source_match = _SOURCE_PATTERN.search(continuation_text)
            source_val: Optional[str] = source_match.group(1).strip() if source_match else None

            entries.append(
                {
                    "category": category,
                    "status": status,
                    "subject": subject,
                    "raw_line": line,
                    "date": date_val,
                    "source": source_val,
                    "line_index": idx,
                }
            )

    return entries


def validate_entry(entry: EntryDict) -> List[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: List[str] = []
    if not entry.get("subject"):
        errors.append("missing subject")
    if not entry.get("source"):
        errors.append("missing source/requested-by")
    if not entry.get("date"):
        errors.append("missing date")
    return errors


# ---------------------------------------------------------------------------
# Queue file writer
# ---------------------------------------------------------------------------


def _flip_status_in_line(line: str, new_status: str) -> str:
    """Replace the status marker in a single line (e.g., '[ ]' → '[x]')."""
    new_marker = _STATUS_REVERSE.get(new_status, "[x]")
    # Replace first occurrence of a status marker
    return re.sub(r"`\[[ x—]\]`", f"`{new_marker}`", line, count=1)


def _append_provenance(line: str, note: str) -> str:
    """Append a provenance note to the end of the entry line."""
    # Strip trailing whitespace first
    stripped = line.rstrip()
    return stripped + f" **{note}**"


def write_queue_file(path: Path, lines: List[str]) -> None:
    """Write lines back to the queue file preserving line endings."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Subcommand: list
# ---------------------------------------------------------------------------


def cmd_list(queue_file: Path) -> int:
    """Print pending entries grouped by category."""
    entries = parse_queue_file(queue_file)
    pending = [e for e in entries if e["status"] == "pending"]

    if not pending:
        print("PENDING_COUNT=0")
        print("No pending entries found.")
        return 0

    by_category: Dict[str, List[EntryDict]] = {}
    for e in pending:
        by_category.setdefault(str(e["category"]), []).append(e)

    total = len(pending)
    print(f"PENDING_COUNT={total}")
    for cat in ["install", "upgrade", "allow", "deny"]:
        entries_in_cat = by_category.get(cat, [])
        if not entries_in_cat:
            continue
        print(f"\n[{cat}] ({len(entries_in_cat)} pending)")
        for e in entries_in_cat:
            date_str = e["date"] or "no-date"
            source_str = e["source"] or "unknown"
            print(f"  ENTRY category={e['category']} status={e['status']} subject={e['subject']!r} date={date_str} source={source_str!r}")

    return 0


# ---------------------------------------------------------------------------
# Subcommand: process
# ---------------------------------------------------------------------------


def cmd_process(
    queue_file: Path,
    category_filter: Optional[str],
    dry_run: bool,
    allow_deny: bool,
    target_paths: dict,
) -> int:
    """Process pending entries, applying them and flipping status markers."""
    entries = parse_queue_file(queue_file)
    lines = queue_file.read_text(encoding="utf-8").splitlines()
    appliers = _get_appliers()

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for entry in entries:
        cat = str(entry["category"])
        status = str(entry["status"])

        # Skip non-pending (idempotency)
        if status != "pending":
            continue

        # Category filter
        if category_filter and cat != category_filter:
            continue

        # [deny] requires explicit flag
        if cat == "deny" and not allow_deny:
            print(
                f"SKIP category=deny subject={entry['subject']!r} reason=--allow-deny-additions not set"
            )
            skipped_count += 1
            continue

        # Validate entry fields
        errors = validate_entry(entry)
        if errors:
            print(
                f"HALT category={cat} subject={entry['subject']!r} "
                f"reason=validation_failed errors={errors}"
            )
            error_count += 1
            # Halt on first failure
            break

        # Look up applier for this category
        applier = appliers.get(cat, _echo_applier)

        result: ApplyResult = applier(entry, dry_run=dry_run, target_paths=target_paths)  # type: ignore[operator]

        ok = bool(result.get("ok", False))
        action = str(result.get("action", ""))
        err = str(result.get("error", ""))

        if dry_run:
            print(
                f"DRY_RUN category={cat} status=pending subject={entry['subject']!r} "
                f"action={action!r}"
            )
            processed_count += 1
        elif ok:
            today = datetime.now().strftime("%Y-%m-%d")
            # Flip the status in the lines list
            idx = int(str(entry["line_index"]))
            old_line = lines[idx]
            new_line = _flip_status_in_line(old_line, "applied")
            new_line = _append_provenance(new_line, f"Applied {today} via process_access_requests.py")
            lines[idx] = new_line
            print(
                f"APPLIED category={cat} subject={entry['subject']!r} action={action!r}"
            )
            processed_count += 1
        else:
            print(
                f"HALT category={cat} subject={entry['subject']!r} "
                f"reason=applier_failed error={err!r}"
            )
            error_count += 1
            # Halt on first failure
            break

    if not dry_run and processed_count > 0 and error_count == 0:
        write_queue_file(queue_file, lines)

    print(
        f"SUMMARY processed={processed_count} skipped={skipped_count} "
        f"errors={error_count} dry_run={dry_run}"
    )
    return 1 if error_count > 0 else 0


# ---------------------------------------------------------------------------
# Subcommand: archive
# ---------------------------------------------------------------------------


def _parse_older_than(spec: str) -> int:
    """Parse '60d' style spec into days (integer)."""
    spec = spec.strip()
    if spec.endswith("d"):
        return int(spec[:-1])
    raise ValueError(f"Unrecognised --older-than spec: {spec!r}. Use e.g. '60d'.")


def cmd_archive(queue_file: Path, older_than_days: int) -> int:
    """Remove applied entries older than N days."""
    entries = parse_queue_file(queue_file)
    lines = queue_file.read_text(encoding="utf-8").splitlines()
    cutoff = datetime.now() - timedelta(days=older_than_days)

    removed_indices: List[int] = []
    for entry in entries:
        if entry["status"] != "applied":
            continue
        date_str = entry.get("date")
        if not date_str:
            # No date → skip (can't determine age)
            continue
        try:
            entry_date = datetime.strptime(str(date_str), "%Y-%m-%d")
        except ValueError:
            continue
        if entry_date < cutoff:
            removed_indices.append(int(str(entry["line_index"])))

    if not removed_indices:
        print(f"ARCHIVE_REMOVED=0 (no applied entries older than {older_than_days}d)")
        return 0

    # Build new lines list, skipping removed indices
    removed_set = set(removed_indices)
    new_lines = [l for i, l in enumerate(lines) if i not in removed_set]
    write_queue_file(queue_file, new_lines)
    print(f"ARCHIVE_REMOVED={len(removed_indices)}")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="process_access_requests",
        description="Access-requests queue processor for docs/ACCESS-REQUESTS.md",
    )
    parser.add_argument(
        "--queue-file",
        type=Path,
        default=None,
        help="Path to the queue markdown file (default: docs/ACCESS-REQUESTS.md relative to repo root)",
    )
    parser.add_argument(
        "--allow-deny-additions",
        action="store_true",
        default=False,
        help="Required to process [deny] category entries.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="Show pending entries grouped by category.")

    # process
    proc = sub.add_parser("process", help="Apply pending entries.")
    proc.add_argument(
        "--category",
        choices=["install", "upgrade", "allow", "deny"],
        default=None,
        help="Limit processing to a single category.",
    )
    proc.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show proposed actions without writing.",
    )

    # archive
    arch = sub.add_parser("archive", help="Prune old applied entries.")
    arch.add_argument(
        "--older-than",
        default="60d",
        help="Age threshold for pruning (e.g. '60d'). Default: 60d.",
    )

    return parser


def _resolve_queue_file(cli_path: Optional[Path]) -> Path:
    if cli_path is not None:
        return cli_path.resolve()
    # Default: repo root docs/ACCESS-REQUESTS.md
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "docs" / "ACCESS-REQUESTS.md"


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    queue_file = _resolve_queue_file(args.queue_file)
    if not queue_file.exists():
        print(f"ERROR: queue file not found: {queue_file}", file=sys.stderr)
        return 2

    target_paths = {
        "queue_file": queue_file,
        "settings_local": queue_file.parent.parent / ".claude" / "settings.local.json",
        "requirements": queue_file.parent.parent / "requirements.txt",
        "requirements_dev": queue_file.parent.parent / "requirements-dev.txt",
    }

    if args.command == "list":
        return cmd_list(queue_file)

    elif args.command == "process":
        return cmd_process(
            queue_file=queue_file,
            category_filter=args.category,
            dry_run=args.dry_run,
            allow_deny=args.allow_deny_additions,
            target_paths=target_paths,
        )

    elif args.command == "archive":
        days = _parse_older_than(args.older_than)
        return cmd_archive(queue_file, days)

    return 0


if __name__ == "__main__":
    sys.exit(main())
