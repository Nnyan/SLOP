#!/usr/bin/env python3
"""tools/validate-wave-file.py — Wave-file preflight validator.

Validates a wave file (Markdown) against live repository state to catch
wave-design errors (e.g. referencing non-existent files, wrong inbound-ref
counts) before agent dispatch.

Heuristics used
---------------
**Path claims:**
  Backtick-quoted tokens (`` `path/to/file` ``) and bare tokens containing
  a ``/`` whose extension is in a known set (.py, .md, .yaml, .yml, .json,
  .sh, .toml, .txt, .rst, .sql, .js, .ts, .vue) are treated as candidate
  paths.  Paths are resolved relative to the repo root (the directory
  containing this script's parent).

  A path is "to-be-created" (expected NOT to exist) when it is EVER
  classified as new anywhere in the document.  A path is "new" if:
    1. It appears in a line containing keywords like "(new)", "create",
       "build", "new file", "add", "split into", or "implement"
       (case-insensitive), AND the path appears outside a command invocation.
    2. It appears under a section heading that itself contains "Deliverable",
       "Stream", "Create", "Build", or "Phase".

  If a path is classified as "new" in ANY part of the document (e.g. in the
  Deliverables section), it is treated as "new" everywhere — including later
  Verification sections that reference it without the "new" keyword.  This
  two-pass approach prevents false positives for newly-created files that
  appear in Verification commands after being declared in Deliverables.

  Paths inside backtick-quoted shell command invocations (where the backtick
  content contains spaces and starts with a known command like python3/pytest/
  bash/grep) are NOT extracted as path claims.  These are command arguments,
  not assertions about whether the file exists.

  Paths containing glob wildcards (``*``, ``?``, ``[``..``]``) are skipped
  entirely — they are patterns, not specific path claims.

  Paths under ``.claude/run/`` are skipped — these are run-artifact paths
  produced by agents; their existence depends on whether the wave has already
  been executed.

  All other candidate paths are "claimed-existing" and must exist on disk.
  Missing claimed-existing paths are failures.  Missing to-be-created paths
  are expected (silently skipped).

  Conservative by design: only FAIL on paths that are clearly claimed-existing
  AND are missing from disk.

**Inbound-ref claims:**
  Lines matching patterns like:
    "X is referenced N times"
    "returns N inbound refs"
    "grep ... returns N"
    "grep -r ... → N"
  are parsed for the integer count and the target string.  The validator
  re-runs ``grep -r`` on the repo and checks whether the live count matches.
  Only exact-count assertions are checked.  Approximate claims ("several",
  ">5") are skipped.

  NOTE: version-string comparisons like ">=2.10" are NOT treated as
  inbound-ref claims — only claims phrased as reference COUNTS.

Exit codes
----------
  0 — all claimed-existing paths exist and all inbound-ref counts match.
  1 — one or more failures (missing claimed-existing path OR wrong count).

Machine-readable output (--json flag)
--------------------------------------
  When invoked with ``--json``, the validator writes a single JSON object to
  stdout (after all human-readable output) with keys:

    {
      "wave": "<absolute path>",
      "ok": true | false,
      "failures": ["MISSING ...", "INBOUND-REF MISMATCH ...", ...],
      "warnings": ["Could not run grep ...", ...],
      "tier": null
    }

  The ``tier`` field is always ``null`` when emitted by this validator — it is
  a placeholder populated by the pre-flight harness (Stream E) after it calls
  ``tools/wave_complexity.py`` to score the wave.

  Exit codes are UNCHANGED — ``--json`` only adds the JSON object, it does NOT
  alter exit semantics.  The pre-flight harness (Stream E) reads this object to
  decide DISPATCH-OK vs BLOCKED.

  Tier-string contract note (PINNED by Stream B / ``tools/wave_complexity.py``):
    Tier values are exactly ``"Low"``, ``"Medium"``, ``"High"`` (capitalized).
    The harness may ``from wave_complexity import VALID_TIERS`` to branch on them.
    This validator does NOT define those strings; the contract is B's to own.

Usage
-----
  python3 tools/validate-wave-file.py .claude/waves/S-55-DEPS-AND-TOOLING.md
  python3 tools/validate-wave-file.py .claude/waves/S-73-WAVE-AUTHORING-RIGOR.md --json
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Extensions that make a bare token look like a file path reference.
_PATH_EXTENSIONS = {
    ".py", ".md", ".yaml", ".yml", ".json", ".sh",
    ".toml", ".txt", ".rst", ".sql", ".js", ".ts", ".vue",
}

# Keywords that signal a path is expected to be new / not yet existing.
_NEW_KEYWORDS = re.compile(
    r"\b(new|create|build|add|implement|write|split\s+into|extract|refactor)\b",
    re.IGNORECASE,
)

# Section headings that imply deliverables or planned work (new files expected).
_DELIVERABLE_HEADINGS = re.compile(
    r"^#{1,6}\s+(deliverable|stream\s+[a-zA-Z0-9]|create|build|phase\s+\d|target)",
    re.IGNORECASE | re.MULTILINE,
)

# Section headings or line markers that indicate paths are being DELETED or
# are purely illustrative — existence checks are skipped in these contexts.
_DELETE_SECTION_HEADINGS = re.compile(
    r"^#{1,6}\s+(authorized\s+deletions?|delete|deletions?)",
    re.IGNORECASE,
)

# Line-level keywords that signal a path is being DELETED (not claimed-existing).
# Matches patterns like "(delete)", "delete backend/foo.py", etc.
_DELETE_KEYWORDS = re.compile(
    r"\b(delete|deleted|deleting|authorized\s+deletions?)\b",
    re.IGNORECASE,
)

# Line-level keywords that signal a path is illustrative / not a real claim.
_ILLUSTRATIVE_KEYWORDS = re.compile(
    r"\b(example|illustrative|e\.g\.|e\.g,|for\s+example|such\s+as)\b",
    re.IGNORECASE,
)

# Known top-level directories in this repository.  A path fragment that does
# NOT start with one of these is almost certainly a partial path reference or a
# narrative mention — not a concrete claim about a repo-relative path.
# Also includes dot-directories that hold project config/tooling.
_KNOWN_TOP_LEVEL_DIRS = (
    "backend/",
    "catalog/",
    "cli/",
    "data/",
    "docs/",
    "frontend/",
    "installer/",
    "migrations/",
    "secrets/",
    "tests/",
    "tools/",
    ".claude/",
    ".github/",
)

# Path prefixes to skip entirely — run artifacts whose existence depends on
# whether the wave has already been executed, plus system paths (/tmp/, etc.)
# that are never repo-relative.
_SKIP_PATH_PREFIXES = (
    ".claude/run/",
    "/tmp/",
    "/var/",
    "/opt/",
    "/etc/",
    "/usr/",
    "/home/",
    "/srv/",
)

# Backtick-quoted tokens: `something`
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")

# Commands that indicate a backtick-quoted string is a shell invocation.
# When a backtick token starts with one of these and contains spaces,
# its contained paths are arguments, not existence assertions.
_COMMAND_PREFIXES = re.compile(
    r"^(python3?|pytest|pip|uv|bash|sh|cat|grep|diff|ls|cd|find|git|"
    r"ms-enforce|ms-testgen|ruff|mypy|bandit|actionlint|shellcheck|"
    r"import\s+json|print|sudo|chmod|curl|wget|tar|cp|mv|rm|mkdir)\b",
    re.IGNORECASE,
)

# Inbound-ref count claim patterns.
_INBOUND_COUNT_PATTERNS = [
    # "X is referenced N times"
    re.compile(
        r"`?([^`\n]+?)`?\s+is\s+referenced\s+(\d+)\s+times?",
        re.IGNORECASE,
    ),
    # "returns N inbound refs"
    re.compile(
        r"returns?\s+(\d+)\s+inbound\s+refs?",
        re.IGNORECASE,
    ),
    # "grep ... returns N"
    re.compile(
        r"grep.*?returns?\s+(\d+)",
        re.IGNORECASE,
    ),
    # "grep -r ... → N"
    re.compile(
        r"grep.*?→\s*(\d+)",
        re.IGNORECASE,
    ),
    # "referenced N times"
    re.compile(
        r"referenced\s+(\d+)\s+times?",
        re.IGNORECASE,
    ),
]

# Grep-subject extraction: look for a backtick-quoted string near the count.
_GREP_SUBJECT_RE = re.compile(r"`([^`\n]+)`")


def _is_path_candidate(token: str) -> bool:
    """Return True if token looks like a file path."""
    token = token.strip().strip('"').strip("'")
    if "/" not in token:
        return False
    # Skip glob patterns.
    if any(c in token for c in ("*", "?", "[")):
        return False
    suffix = Path(token).suffix
    return suffix in _PATH_EXTENSIONS


def _is_skipped_path(token: str) -> bool:
    """Return True if the path should be skipped entirely (e.g. run artifacts)."""
    return any(token.startswith(p) for p in _SKIP_PATH_PREFIXES)


def _is_command_invocation(backtick_content: str) -> bool:
    """Return True if the backtick content looks like a shell command."""
    content = backtick_content.strip()
    if " " not in content:
        return False
    # Strip common path-to-command prefixes (.venv/bin/, /usr/bin/, etc.)
    # to normalize the command name for prefix matching.
    for prefix in (".venv/bin/", ".venv\\bin\\", "/usr/bin/", "/usr/local/bin/",
                   "python3 -m ", "sudo ", "./"):
        if content.startswith(prefix):
            content = content[len(prefix):]
            break
    return bool(_COMMAND_PREFIXES.match(content))


def _has_known_top_level_prefix(token: str) -> bool:
    """Return True if token starts with a known top-level repo directory."""
    return any(token.startswith(d) for d in _KNOWN_TOP_LEVEL_DIRS)


def _classify_path(
    token: str,
    line: str,
    in_deliverable_section: bool,
    in_delete_section: bool,
) -> str:
    """Return 'new', 'existing', or 'skip'."""
    token = token.strip()
    # Skip tokens that look like URLs.
    if token.startswith("http"):
        return "skip"
    # Skip command flags.
    if token.startswith("-"):
        return "skip"
    # Skip tokens with shell/template placeholders.
    if "<" in token or ">" in token or "{" in token or "}" in token:
        return "skip"
    # Skip run-artifact paths and system paths (/tmp/, /var/, etc.).
    if _is_skipped_path(token):
        return "skip"
    # Skip path fragments that don't start with a known top-level dir.
    # These are almost always partial path mentions or narrative examples,
    # not concrete claims about repo-relative file existence.
    if not _has_known_top_level_prefix(token):
        return "skip"
    # Skip paths inside "Authorized deletions" sections or lines with
    # delete-related keywords — these paths are being removed, not asserted
    # to exist.
    if in_delete_section:
        return "skip"
    if _DELETE_KEYWORDS.search(line):
        return "skip"
    # Skip paths on lines that are explicitly illustrative/example.
    if _ILLUSTRATIVE_KEYWORDS.search(line):
        return "skip"
    # If the line has new-file keywords, classify as new.
    if _NEW_KEYWORDS.search(line):
        return "new"
    # If we are inside a deliverables/phase section, classify as new.
    if in_deliverable_section:
        return "new"
    return "existing"


def _command_ranges(line: str) -> list[tuple[int, int]]:
    """Return list of (start, end) character ranges that are inside command backticks.

    These ranges should be excluded from bare-token extraction — paths inside
    command invocations are arguments, not existence assertions.
    """
    ranges = []
    for m in _BACKTICK_RE.finditer(line):
        if _is_command_invocation(m.group(1)):
            ranges.append((m.start(), m.end()))
    return ranges


def _in_command_range(pos: int, ranges: list[tuple[int, int]]) -> bool:
    """Return True if character position is inside a command-backtick range."""
    return any(start <= pos < end for start, end in ranges)


def _extract_paths(content: str) -> list[tuple[str, str]]:
    """Return list of (path, classification) from wave file content.

    classification is 'new' or 'existing'.

    Two-pass approach:
      Pass 1 — collect every (path, classification) occurrence.
      Pass 2 — if a path was EVER classified as 'new' in any occurrence,
               treat it as 'new' everywhere.  This prevents false positives
               when a new-file deliverable is later mentioned in the
               Verification section without the "new" keyword.

    Paths inside backtick-quoted shell command invocations are excluded
    from bare-token extraction — they are arguments, not claims.
    """
    raw_results: list[tuple[str, str]] = []

    lines = content.splitlines()
    in_deliverable = False
    in_delete = False

    for line in lines:
        # Track section headings.
        if re.match(r"^#{1,6}\s+", line):
            in_deliverable = bool(_DELIVERABLE_HEADINGS.match(line))
            in_delete = bool(_DELETE_SECTION_HEADINGS.match(line))

        # Find command-invocation ranges to exclude from bare-token extraction.
        cmd_ranges = _command_ranges(line)

        # Backtick-quoted tokens: only extract standalone path tokens,
        # not tokens that are part of command invocations.
        for m in _BACKTICK_RE.finditer(line):
            raw = m.group(1).strip()
            # Skip if this backtick span is a command invocation.
            if _is_command_invocation(m.group(1)):
                continue
            if _is_path_candidate(raw):
                cls = _classify_path(raw, line, in_deliverable, in_delete)
                if cls != "skip":
                    raw_results.append((raw, cls))

        # Bare slash-containing tokens: skip those inside command ranges.
        for word_m in re.finditer(r"[^\s,;|()\[\]\"']+", line):
            word = word_m.group(0).strip().rstrip(".,:;)")
            if not word:
                continue
            # Skip if this word is inside a command-invocation backtick range.
            if _in_command_range(word_m.start(), cmd_ranges):
                continue
            if _is_path_candidate(word):
                cls = _classify_path(word, line, in_deliverable, in_delete)
                if cls != "skip":
                    raw_results.append((word, cls))

    # Pass 2: build a set of paths that are "new" in ANY occurrence.
    ever_new: set[str] = {p for p, c in raw_results if c == "new"}

    # Deduplicate: one entry per unique path, with 'new' winning over 'existing'.
    deduped: dict[str, str] = {}
    for path, cls in raw_results:
        if path not in deduped:
            deduped[path] = cls
        elif cls == "new":
            deduped[path] = "new"

    # Apply global "new" override.
    return [
        (p, "new" if p in ever_new else c)
        for p, c in deduped.items()
    ]


def _extract_inbound_ref_claims(content: str) -> list[tuple[str, int]]:
    """Return list of (grep_subject, expected_count) from inbound-ref claims.

    Only exact integer counts are extracted.  Version strings (>=X) are
    deliberately excluded.
    """
    claims: list[tuple[str, int]] = []
    seen_subjects: set[str] = set()

    for line in content.splitlines():
        # Skip lines that look like version requirements (bcrypt>=2.10 etc.)
        if re.search(r"[><=!]=?\s*\d+\.\d+", line):
            continue
        for pat in _INBOUND_COUNT_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            # Extract the count (last capture group that is a digit string).
            groups = [g for g in m.groups() if g and g.isdigit()]
            if not groups:
                continue
            count = int(groups[-1])
            # Extract the subject: prefer backtick-quoted string near the match.
            subjects = _GREP_SUBJECT_RE.findall(line)
            if subjects:
                # Use the first subject that is not a command/flag.
                subject = next(
                    (s for s in subjects if not s.startswith("-") and " " not in s.strip()),
                    subjects[0],
                )
            else:
                subject = ""
            if subject and subject not in seen_subjects:
                seen_subjects.add(subject)
                claims.append((subject, count))
            break  # only extract once per line
    return claims


def _live_grep_count(subject: str) -> int:
    """Return the number of files containing subject across the repo."""
    try:
        result = subprocess.run(
            ["grep", "-r", "--include=*.py", "--include=*.md",
             "--include=*.yaml", "--include=*.yml", "-l", subject],
            capture_output=True, text=True, cwd=str(REPO), timeout=30,
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        return len(lines)
    except Exception:
        return -1  # sentinel: could not run grep


def validate(wave_path: Path) -> tuple[list[str], list[str]]:
    """Validate the wave file.  Returns (failures, warnings)."""
    content = wave_path.read_text(encoding="utf-8")
    failures: list[str] = []
    warnings: list[str] = []

    # ── 1. Path checks ──────────────────────────────────────────────────────
    paths = _extract_paths(content)
    for path_str, cls in paths:
        full = REPO / path_str
        exists = full.exists()
        if cls == "existing" and not exists:
            failures.append(
                f"MISSING claimed-existing path: {path_str}"
            )

    # ── 2. Inbound-ref count checks ─────────────────────────────────────────
    claims = _extract_inbound_ref_claims(content)
    for subject, expected in claims:
        live = _live_grep_count(subject)
        if live < 0:
            warnings.append(f"Could not run grep for inbound-ref claim: '{subject}'")
            continue
        if live != expected:
            failures.append(
                f"INBOUND-REF MISMATCH: '{subject}' — "
                f"wave claims {expected}, grep found {live} file(s)"
            )

    return failures, warnings


def main() -> None:
    args = sys.argv[1:]
    emit_json = "--json" in args
    positional = [a for a in args if not a.startswith("--")]

    if not positional:
        print("Usage: validate-wave-file.py <wave-file.md> [--json]", file=sys.stderr)
        sys.exit(1)

    wave_path = Path(positional[0])
    if not wave_path.is_absolute():
        wave_path = Path.cwd() / wave_path
    if not wave_path.exists():
        print(f"ERROR: wave file not found: {wave_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating: {wave_path}")
    failures, warnings = validate(wave_path)

    for w in warnings:
        print(f"  WARNING: {w}")
    for f in failures:
        print(f"  FAIL: {f}")

    if not failures and not warnings:
        print("  OK: all claims check out")
    elif not failures:
        print(f"  OK (with {len(warnings)} warning(s))")

    if emit_json:
        result = {
            "wave": str(wave_path),
            "ok": len(failures) == 0,
            "failures": list(failures),
            "warnings": list(warnings),
            "tier": None,
        }
        print(json.dumps(result))

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
