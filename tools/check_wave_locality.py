#!/usr/bin/env python3
"""tools/check_wave_locality.py — File locality conflict checker for parallel wave sessions.

Parses one or more wave brief (S-NN-*.md) files, extracts each session's "You may safely
write" file set, and reports any file claimed by more than one session.

Usage:
    python3 tools/check_wave_locality.py docs/sessions/S-23-*.md
    python3 tools/check_wave_locality.py docs/sessions/S-23-A.md docs/sessions/S-23-B.md

Exit: 0 if no conflicts found; 1 if any conflicts found.

No third-party imports — stdlib only.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_SAFE_WRITE_HEADER = re.compile(r"\*\*You may safely write\*\*")
_BOLD_HEADER = re.compile(r"^\*\*")
_SEPARATOR = re.compile(r"^---")

# Matches a backtick-wrapped path token, possibly with trailing annotation
_BACKTICK_PATH = re.compile(r"`([^`]+)`")


def _looks_like_path(token):
    """Return True if *token* looks like a file or directory path."""
    # Must contain a slash or a dot with an extension to be path-like
    return "/" in token or re.search(r"\.\w+$", token) is not None


def _extract_paths_from_line(line):
    """Pull path-like tokens out of one line of markdown text."""
    paths = []
    for m in _BACKTICK_PATH.finditer(line):
        token = m.group(1).strip()
        # Strip trailing annotation like " (new file)"
        token = token.split("(")[0].strip()
        if _looks_like_path(token):
            paths.append(token)
    # Also handle bare (un-backticked) bullet list items
    stripped = line.strip().lstrip("- ").strip()
    if stripped and not stripped.startswith("`") and _looks_like_path(stripped):
        # Remove any trailing annotation
        stripped = stripped.split("(")[0].strip()
        paths.append(stripped)
    return paths


def parse_write_set(brief_path):
    """Return (session_id, list_of_paths) for the brief at *brief_path*."""
    session_id = Path(brief_path).stem  # e.g. "S-23-A"
    text = Path(brief_path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    paths = []
    in_write_block = False

    for i, line in enumerate(lines):
        if _SAFE_WRITE_HEADER.search(line):
            in_write_block = True
            # Paths may appear on this same header line (inline format)
            # e.g. "**You may safely write**: `a.py`, `b.py`"
            paths.extend(_extract_paths_from_line(line))
            continue

        if not in_write_block:
            continue

        # Stop at the next bold header or section separator
        if _BOLD_HEADER.match(line) or _SEPARATOR.match(line):
            break

        # Collect paths from continuation lines (bullet-list or comma format)
        paths.extend(_extract_paths_from_line(line))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    return session_id, unique


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def build_conflict_map(brief_files):
    """Return (session_map, conflict_map).

    session_map  : {session_id: [paths]}
    conflict_map : {path: [session_ids]}  — only paths claimed by >1 session
    """
    session_map = dict()
    ownership = defaultdict(list)  # path -> [session_ids]

    for bf in brief_files:
        session_id, paths = parse_write_set(bf)
        session_map[session_id] = paths
        for p in paths:
            ownership[p].append(session_id)

    conflict_map = dict()
    for path, owners in ownership.items():
        if len(owners) > 1:
            conflict_map[path] = owners

    return session_map, conflict_map


def check_do_not_touch_violations(brief_files, session_map):
    """Warn about files in one session's 'Do NOT touch' list that another session owns.

    Returns list of (session_id, file, owning_session_id) tuples.
    """
    _DONT_TOUCH_HEADER = re.compile(r"\*\*Do NOT touch\*\*")

    # Build a reverse map: path -> set of sessions that own it
    owners_of = defaultdict(set)
    for sid, paths in session_map.items():
        for p in paths:
            owners_of[p].add(sid)

    violations = []
    for bf in brief_files:
        session_id = Path(bf).stem
        text = Path(bf).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        in_block = False
        for line in lines:
            if _DONT_TOUCH_HEADER.search(line):
                in_block = True
                # Inline items on same line
                for token in _extract_paths_from_line(line):
                    for owner in owners_of.get(token, set()):
                        if owner != session_id:
                            violations.append((session_id, token, owner))
                continue
            if not in_block:
                continue
            if _BOLD_HEADER.match(line) or _SEPARATOR.match(line):
                break
            for token in _extract_paths_from_line(line):
                for owner in owners_of.get(token, set()):
                    if owner != session_id:
                        violations.append((session_id, token, owner))

    return violations


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report(brief_files, session_map, conflict_map, violations):
    """Print the summary report; return exit code (0 or 1)."""
    session_ids = list(session_map.keys())
    brief_count = len(session_ids)
    id_list = ", ".join(session_ids)

    print("check_wave_locality.py -- file locality check")
    print("Briefs scanned: %d (%s)" % (brief_count, id_list))
    print("")

    exit_code = 0

    if conflict_map:
        exit_code = 1
        for path, owners in sorted(conflict_map.items()):
            print("CONFLICT: %s" % path)
            print("  Claimed by: %s" % ", ".join(owners))
            print("  -> Serialize these sessions or split their file sets.")
            print("")
        print("%d conflict(s) found. Fix before dispatching parallel sessions." % len(conflict_map))
    else:
        print("No conflicts.")

    if violations:
        print("")
        print("WARNINGS -- Do-NOT-touch / ownership mismatches:")
        for checker_session, path, owner in violations:
            print("  %s prohibits %s  (but %s owns it)" % (checker_session, path, owner))

    return exit_code


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: check_wave_locality.py <brief1.md> [brief2.md ...]", file=sys.stderr)
        sys.exit(1)

    brief_files = sys.argv[1:]

    missing = [f for f in brief_files if not Path(f).exists()]
    if missing:
        for f in missing:
            print("Error: file not found: %s" % f, file=sys.stderr)
        sys.exit(1)

    session_map, conflict_map = build_conflict_map(brief_files)
    violations = check_do_not_touch_violations(brief_files, session_map)
    exit_code = report(brief_files, session_map, conflict_map, violations)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
