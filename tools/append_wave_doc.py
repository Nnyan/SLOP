#!/usr/bin/env python3
"""tools/append_wave_doc.py — Safe append helper for shared wave docs.

Appends a single line to one of the three append-only shared wave documents.
Refuses any other target path, making the append-only intent explicit and
hard to misuse with Edit/Write by accident.

Usage:
    python3 tools/append_wave_doc.py --file docs/TASK_TIMING_LOG.md --line "2026-05-25,S-23-A,..."
    python3 tools/append_wave_doc.py --file docs/TODO.md --line "- [ ] [10m] New finding"
    python3 tools/append_wave_doc.py --file docs/LESSONS_LEARNED.md --line "..."

    # With explicit repo root (optional; default: auto-detect from script location)
    python3 tools/append_wave_doc.py --repo /home/stack/v5 --file docs/TODO.md --line "..."

Exit: 0 on success; 1 on error.

Why this exists:
    Wave-work sessions must never use Edit or Write on shared docs files because
    concurrent sessions may have written to the same file in the meantime, making
    Edit's uniqueness check fail or Write's overwrite clobber a peer's row.
    This script uses open(path, 'a') — an OS-level append — which is safe for
    single-line appends from independent processes (each append is atomic on
    Linux for writes shorter than PIPE_BUF).

Allowed targets (relative to repo root):
    docs/TASK_TIMING_LOG.md
    docs/TODO.md
    docs/LESSONS_LEARNED.md

No third-party imports — stdlib only.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ALLOWED_TARGETS = [
    "docs/TASK_TIMING_LOG.md",
    "docs/TODO.md",
    "docs/LESSONS_LEARNED.md",
]


def find_repo_root():
    """Walk up from this script's location to find the repo root (contains docs/)."""
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "docs").is_dir():
        return candidate
    # Fallback: try well-known paths
    for known in [
        Path("/home/stack/v5"),
        Path("/home/stack/code/slop"),
    ]:
        if (known / "docs").is_dir():
            return known
    return candidate  # best guess


def resolve_target(file_arg, repo_root):
    """Return resolved absolute Path for *file_arg*, or raise ValueError if not allowed."""
    # Normalise: strip leading ./ and repo_root prefix if user passed absolute path
    normalised = file_arg
    try:
        normalised = str(Path(file_arg).relative_to(repo_root))
    except ValueError:
        pass  # file_arg is already relative (or a bare basename)

    # Normalise slashes
    normalised = normalised.replace(os.sep, "/").lstrip("./")

    if normalised not in ALLOWED_TARGETS:
        raise ValueError(
            "Refused: '%s' is not in the allowed-targets list.\n"
            "Allowed targets (relative to repo root):\n  %s"
            % (file_arg, "\n  ".join(ALLOWED_TARGETS))
        )

    return repo_root / normalised


def append_line(target_path, line):
    """Append *line* + newline to *target_path* using open(path, 'a')."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(target_path), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Safely append one line to a shared wave doc (append-only guard)."
    )
    parser.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="Relative path of the target file (e.g. docs/TODO.md)",
    )
    parser.add_argument(
        "--line",
        required=True,
        metavar="TEXT",
        help="The line of text to append (no trailing newline needed)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        metavar="DIR",
        help="Repo root directory (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve() if args.repo else find_repo_root()

    try:
        target_path = resolve_target(args.file, repo_root)
    except ValueError as exc:
        print("Error: " + str(exc), file=sys.stderr)
        sys.exit(1)

    if not target_path.exists():
        print(
            "Error: target file does not exist: %s" % target_path,
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        append_line(target_path, args.line)
    except OSError as exc:
        print("Error writing to %s: %s" % (target_path, exc), file=sys.stderr)
        sys.exit(1)

    print("Appended 1 line to %s" % target_path)
    sys.exit(0)


if __name__ == "__main__":
    main()
