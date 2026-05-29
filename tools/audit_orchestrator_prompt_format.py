#!/usr/bin/env python3
"""audit_orchestrator_prompt_format.py — Orchestrator prompt format linter.

Scans archived orchestrator prompts (under .claude/run-archive/*/ where present)
and tracked wave-file prompt templates (.claude/waves/*.md) for required elements:

  1. Explicit `git rev-parse origin/main` base (not bare HEAD) — either in the
     Cross-wave dependencies section of a wave file, or referenced in a run-archive
     status/decisions file that documents the orchestrator startup.

  2. Per-stream model assignments — the wave file's Parallelization section must
     contain explicit model assignments (e.g., "coordinator = **opus**",
     "sonnet", "model:" per-row in the stream table).

  3. Subagent preamble reference — the wave file's Robot mode / invocation section
     must reference "subagent preamble" or the key preamble elements (venv-symlink,
     AskUserQuestion, Robot mode).

Emits WARNING-prefixed lines for missing elements.  Exit code is 0 always
(warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_orchestrator_prompt_format.py [--repo /path/to/repo]

Output:
  WARNING: <file>  missing <element>: <detail>
  (one line per finding; empty output means all checked files are compliant)

Known false-positive classes (FPs):
  FP-1: Old wave files (pre-S-55) predate the subagent preamble convention.
        These will warn on "subagent preamble" because the convention did not
        exist yet.  Suppressed: files whose basename matches S-[0-5][0-9]-* are
        treated as pre-convention and only checked for per-stream models.
  FP-2: Non-orchestrator wave files (single-stream with no dispatch) may lack
        explicit model assignments.  Suppressed: files with no Parallelization
        section are skipped for per-stream model checks.
  FP-3: Run-archive decision/status files are informational records, not prompts.
        They are only checked for git-base evidence (did the orchestrator confirm
        origin/main?); they are NOT checked for per-stream models or preamble.
  FP-4: Wave files without a Robot mode section are assumed to predate the
        doctrine or be operator-assist files; they are skipped entirely.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── Version threshold for "preamble convention exists" ──────────────────────
# Wave files for S-56 and later are expected to reference the subagent preamble.
# Older files predate the convention (FP-1).
_PREAMBLE_MIN_WAVE = 56

# Regex to extract the wave number from a filename like S-60-AGENT-FIX-SAFETY.md
_WAVE_NUM_RE = re.compile(r"[Ss]-(\d+)-", re.IGNORECASE)

# ── Element detection regexes ─────────────────────────────────────────────

# Element 1: git rev-parse origin/main
_GIT_REV_RE = re.compile(r"git\s+rev-parse\s+origin/main", re.IGNORECASE)
# A SHA-like string paired with "origin/main" counts too (e.g., "origin/main @ abc1234")
_ORIGIN_MAIN_SHA_RE = re.compile(
    r"origin/main\s*(?:commit|@|=)\s*[0-9a-f]{6,40}|"
    r"[0-9a-f]{6,40}\s*=\s*origin/main",
    re.IGNORECASE,
)

# Element 2: per-stream model assignments
_MODEL_EXPLICIT_RE = re.compile(
    r"\bopus\b|\bsonnet\b|\bhariku\b|\bmodel\s*[:=]",
    re.IGNORECASE,
)
_PARALLELIZATION_SECTION_RE = re.compile(
    r"^#{1,4}\s*parallelization",
    re.IGNORECASE | re.MULTILINE,
)
_MODELS_LINE_RE = re.compile(
    r"\bModels\s*:\s*coordinator\s*=",
    re.IGNORECASE,
)

# Element 3: subagent preamble
_PREAMBLE_DIRECT_RE = re.compile(
    r"subagent\s+preamble|preamble.*subagent",
    re.IGNORECASE,
)
_PREAMBLE_VENV_RE = re.compile(r"ln\s+-sf.*\.venv|venv.*symlink", re.IGNORECASE)
_PREAMBLE_ROBOT_RE = re.compile(r"in\s+Robot\s+mode", re.IGNORECASE)
_PREAMBLE_ASK_RE = re.compile(r"AskUserQuestion", re.IGNORECASE)
_ROBOT_MODE_SECTION_RE = re.compile(
    r"^#{1,4}\s*Robot\s+mode",
    re.IGNORECASE | re.MULTILINE,
)


def _wave_number(filename: str) -> int | None:
    """Extract numeric wave number from a wave filename like S-60-TOPIC.md."""
    m = _WAVE_NUM_RE.search(filename)
    if m:
        return int(m.group(1))
    return None


def _has_robot_section(text: str) -> bool:
    """Return True if the file has a Robot mode section."""
    return bool(_ROBOT_MODE_SECTION_RE.search(text))


def _has_parallelization_section(text: str) -> bool:
    """Return True if the file has a Parallelization section."""
    return bool(_PARALLELIZATION_SECTION_RE.search(text))


def _check_git_rev_parse(text: str) -> bool:
    """Return True if text explicitly references git rev-parse origin/main or origin/main@SHA."""
    return bool(_GIT_REV_RE.search(text) or _ORIGIN_MAIN_SHA_RE.search(text))


def _check_per_stream_models(text: str) -> bool:
    """Return True if text has per-stream model assignments."""
    return bool(_MODELS_LINE_RE.search(text) or (
        _PARALLELIZATION_SECTION_RE.search(text) and _MODEL_EXPLICIT_RE.search(text)
    ))


def _check_subagent_preamble(text: str) -> bool:
    """Return True if text references the subagent preamble or its key elements."""
    if _PREAMBLE_DIRECT_RE.search(text):
        return True
    # At least two of the three key elements counts as implicit preamble
    hits = sum([
        bool(_PREAMBLE_VENV_RE.search(text)),
        bool(_PREAMBLE_ROBOT_RE.search(text)),
        bool(_PREAMBLE_ASK_RE.search(text)),
    ])
    return hits >= 2


def audit_wave_file(path: Path) -> list[str]:
    """Lint a wave file for all three required elements.

    Returns a list of WARNING strings (empty = clean).
    """
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"WARNING: {path.name}  could not read file: {exc}"]

    # Skip files with no Robot mode section — not an orchestrator prompt
    if not _has_robot_section(text):
        return []

    rel = path.name

    # Element 1: git rev-parse origin/main base
    # Wave files should document origin/main as the base in Cross-wave deps or invocation
    if not _check_git_rev_parse(text):
        warnings.append(
            f"WARNING: {rel}  missing git-rev-parse-base: "
            "no 'git rev-parse origin/main' or 'origin/main @ <SHA>' in Cross-wave "
            "dependencies section — orchestrator needs explicit base commit, not bare HEAD"
        )

    # Element 2: per-stream model assignments (only if Parallelization section exists)
    if _has_parallelization_section(text):
        if not _check_per_stream_models(text):
            warnings.append(
                f"WARNING: {rel}  missing per-stream-models: "
                "Parallelization section found but no explicit model assignments "
                "(e.g., 'coordinator = **opus**', 'sonnet' in stream table rows)"
            )

    # Element 3: subagent preamble (only for post-convention wave files)
    wave_num = _wave_number(path.name)
    if wave_num is None or wave_num >= _PREAMBLE_MIN_WAVE:
        if not _check_subagent_preamble(text):
            warnings.append(
                f"WARNING: {rel}  missing subagent-preamble: "
                "Robot mode section found but no reference to 'subagent preamble' "
                "or its key elements (venv-symlink, AskUserQuestion, 'in Robot mode') — "
                f"convention required for wave S-{_PREAMBLE_MIN_WAVE}+"
            )

    return warnings


def audit_run_archive_file(path: Path) -> list[str]:
    """Lint a run-archive status/decisions file for git-base evidence (element 1 only).

    Run-archive files are informational records of what the orchestrator did,
    not the prompt itself.  Only check that the orchestrator documented it
    confirmed the origin/main base.

    Returns a list of WARNING strings (empty = clean).
    """
    warnings: list[str] = []

    # Only check status and decisions files that mention "orchestrator"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # Filter: only files that are orchestrator records (status or decisions docs
    # that appear to describe orchestrator startup / base-commit activity)
    if "orchestrator" not in text.lower():
        return []

    # Only warn if this looks like an orchestrator startup doc but lacks origin/main
    is_batch_doc = re.search(r"\bbatch\b.*\borchestrator\b|\borchestrator\b.*\bbatch\b",
                              text, re.IGNORECASE)
    is_base_doc = re.search(r"\bbase\s+commit\b|\borigin/main\b|\bgit\s+rev-parse\b",
                             text, re.IGNORECASE)
    has_origin_ref = _check_git_rev_parse(text)

    if is_batch_doc and not is_base_doc and not has_origin_ref:
        rel = path.name
        warnings.append(
            f"WARNING: {rel}  missing git-base-evidence: "
            "orchestrator batch record contains no reference to origin/main base commit — "
            "orchestrator should document 'git rev-parse origin/main' confirmation"
        )

    return warnings


def scan_repo(repo: Path) -> list[str]:
    """Scan the repo for orchestrator prompt format issues.

    Checks:
    - .claude/waves/*.md  (wave file prompt templates)
    - .claude/run-archive/*/status/*.md  (archived run status)
    - .claude/run-archive/*/decisions/*.md  (archived run decisions)

    Returns all WARNING lines (sorted for stability).
    """
    all_warnings: list[str] = []

    # ── Wave files ────────────────────────────────────────────────────────
    waves_dir = repo / ".claude" / "waves"
    if waves_dir.exists():
        for wave_file in sorted(waves_dir.glob("*.md")):
            all_warnings.extend(audit_wave_file(wave_file))

    # ── Run archive ───────────────────────────────────────────────────────
    archive_dir = repo / ".claude" / "run-archive"
    if archive_dir.exists():
        for subdir in sorted(archive_dir.iterdir()):
            if not subdir.is_dir():
                continue
            # Check status/ and decisions/ subdirs
            for category in ("status", "decisions"):
                cat_dir = subdir / category
                if not cat_dir.exists():
                    continue
                for md_file in sorted(cat_dir.glob("*.md")):
                    all_warnings.extend(audit_run_archive_file(md_file))

    return all_warnings


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

    warnings = scan_repo(repo)

    for line in warnings:
        print(line)

    total = len(warnings)
    if total > 0:
        print(f"\nSummary: {total} orchestrator prompt format warning(s)", file=sys.stderr)
    else:
        print("OK: all checked orchestrator prompt files pass format checks", file=sys.stderr)

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
