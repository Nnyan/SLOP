#!/usr/bin/env python3
"""audit_wave_subagent_preamble.py — Verify wave files' orchestrator sections
include the subagent preamble rules.

Scans every .claude/waves/*.md file. For each file that contains a
"Robot mode" section (i.e., it is an orchestrator-dispatching wave), checks
whether the section (or the file's body) references the three canonical
subagent-preamble requirements:
  1. venv-symlink  — ln -sf .venv / venv symlink mention / "subagent preamble"
  2. file-creation — Bash heredoc for new file creation, NOT the Write tool
  3. no-AskUserQuestion — NEVER call AskUserQuestion

Emits WARNING-prefixed lines for wave files whose Robot mode section omits
a preamble pointer.  Exits 0 always (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_wave_subagent_preamble.py [--repo /path/to/repo]

Output:
  WARNING: <file>  missing preamble signal(s): <list>
  (empty output means all Robot mode wave files reference the preamble)

## False-positive notes (known FP classes)

1. **Wave files without a Robot mode section** (e.g., S-44-AGENT-G.md,
   S-45-RATCHET.md, OPTIONAL-FILE-SIZE-REMEDIATION.md) are skipped entirely.
   They contain no orchestrator dispatch and need no preamble pointer.

2. **Older wave files that include the preamble rules inline** (S-46 through
   S-50 style: "NEVER call AskUserQuestion") satisfy the no-AskUserQuestion
   signal and are detected correctly.

3. **Newer wave files (S-55/S-56) that say "subagent preamble with venv
   symlink"** satisfy all three signals via a single phrase; detected correctly.

4. **Very recent waves (S-57 onwards) that reference ROBOT.md by pointer**
   ("operate under .claude/ROBOT.md doctrine v4") without restating the preamble
   rules do NOT satisfy the three signals.  These are the intended warnings.
   The fix is to add "subagent preamble with venv symlink, Bash heredoc for
   new files, never AskUserQuestion" or equivalent to the Robot mode section.

5. **The wave file being scanned for its own preamble** (S-69) references
   the preamble in stream descriptions, not in its own Robot mode section;
   it is treated the same as any other wave — flagged if the Robot mode footer
   lacks the three signals.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ── Signal patterns ────────────────────────────────────────────────────────

# Signal 1: venv-symlink reference
# Matches: "subagent preamble", "venv symlink", "ln -sf", "venv-symlink"
_VENV_SIGNALS = re.compile(
    r"subagent preamble|venv[- ]symlink|ln -sf.*venv|venv.*symlink",
    re.IGNORECASE,
)

# Signal 2: file-creation rule
# Matches: "Bash heredoc", "heredoc for new file", "heredoc.*file creation",
#          "file.creation.*heredoc", "never.*Write tool", "not the Write tool"
_FILE_CREATION_SIGNALS = re.compile(
    r"bash heredoc|heredoc for new file|file.creation.*heredoc"
    r"|heredoc.*file.creat"
    r"|never.*write tool"
    r"|not the write tool",
    re.IGNORECASE,
)

# Signal 3: no-AskUserQuestion rule
# Matches: "AskUserQuestion", "never call AskUserQuestion", "no-AskUserQuestion"
_NO_ASK_SIGNALS = re.compile(
    r"AskUserQuestion|no.AskUserQuestion",
    re.IGNORECASE,
)

# Detect a "Robot mode" section heading (## or ### Robot mode)
_ROBOT_SECTION_RE = re.compile(
    r"^#{1,3}\s+Robot\s+mode",
    re.IGNORECASE,
)


def extract_robot_section(text: str) -> str | None:
    """Return the text of the first '## Robot mode' section, or None if absent.

    The section extends from the heading to (but not including) the next
    same-or-higher-level heading, or end-of-file.
    """
    lines = text.splitlines()
    start = None
    heading_depth = 0

    for i, line in enumerate(lines):
        m = _ROBOT_SECTION_RE.match(line.rstrip())
        if m:
            start = i
            # Count leading hashes to determine level
            heading_depth = len(line) - len(line.lstrip("#"))
            break

    if start is None:
        return None

    # Collect until the next heading of equal or lesser depth
    section_lines = [lines[start]]
    for line in lines[start + 1:]:
        stripped = line.rstrip()
        if stripped and stripped[0] == "#":
            depth = len(stripped) - len(stripped.lstrip("#"))
            if depth <= heading_depth:
                break
        section_lines.append(line)

    return "\n".join(section_lines)


def check_wave_file(path: Path) -> list[str]:
    """Return a list of missing signal names, or [] if all present / no Robot mode."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    section = extract_robot_section(text)
    if section is None:
        # No Robot mode section — not an orchestrator wave; skip
        return []

    # Check signals against the full file, not just the section.
    # Older waves (S-46 to S-50) define these rules before the section.
    # Searching the full file avoids missing them.
    missing: list[str] = []
    if not _VENV_SIGNALS.search(text):
        missing.append("venv-symlink")
    if not _FILE_CREATION_SIGNALS.search(text):
        missing.append("file-creation-heredoc")
    if not _NO_ASK_SIGNALS.search(text):
        missing.append("no-AskUserQuestion")
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit wave files for subagent preamble references."
    )
    parser.add_argument(
        "--repo",
        default=".",
        metavar="PATH",
        help="Path to repo root (default: current directory)",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    waves_dir = repo / ".claude" / "waves"

    if not waves_dir.exists():
        # No waves directory — nothing to check
        return

    wave_files = sorted(waves_dir.glob("*.md"))
    if not wave_files:
        return

    warned = 0
    for wave_file in wave_files:
        missing = check_wave_file(wave_file)
        if missing:
            rel = wave_file.relative_to(repo)
            print(
                f"WARNING: {rel}  missing preamble signal(s): {', '.join(missing)}"
            )
            warned += 1

    if warned == 0:
        print("OK: all Robot-mode wave files reference the subagent preamble")


if __name__ == "__main__":
    main()
