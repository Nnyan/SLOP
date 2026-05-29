#!/usr/bin/env python3
"""audit_archived_observations.py — Floating-work audit: archived observations.

Walks .claude/run-archive/*/observations/, decisions/, and proposed-deletions/.
For each OBSERVATION file (not decision docs) containing strong future-work
signals (TODO, future, not in scope, worth doing, should be added/implemented),
checks if a meaningful source-file reference in that file is already tracked
in docs/BACKLOG.md. If not, emits a candidate backlog line.

Decision docs are also scanned but with stricter filtering — only explicit
future-work sections (not "Alternatives considered" boilerplate).

Exit code: 0 always (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_archived_observations.py [--repo /path/to/repo]

Output:
  CANDIDATE: <archive_file>  trigger=<phrase>  source=<basename>
    sample: <line context>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Strong trigger phrases that specifically indicate deferred/future work
# (not generic document language)
FUTURE_WORK_RE = re.compile(
    r"(?:"
    r"\bTODO\b"
    r"|not in scope"
    r"|\bfuture\b.{0,40}(?:wave|work|item|consideration)"
    r"|(?:worth|should be)\s+(?:adding|implementing|tracking|investigated?|considered?)"
    r"|(?:future|deferred|planned|pending)\s+work"
    r"|candidate for (?:a )?(?:backlog|future)"
    r")",
    re.IGNORECASE,
)

# Source file extensions that represent actual work items
SOURCE_EXTS = frozenset({
    ".py", ".ts", ".vue", ".js", ".yaml", ".yml", ".toml", ".sh", ".cfg"
})

# Basenames to ignore (they appear ubiquitously in decisions as doctrine refs)
IGNORE_BASENAMES = frozenset({
    "AUTONOMOUS-DEFAULTS.md",
    "ROBOT.md",
    "CLAUDE.md",
    "BACKLOG.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "uv.lock",
})

# Subdirectories within each run-archive/<date>/ to scan
SUBDIRS = ["observations", "decisions", "proposed-deletions"]


def load_backlog(repo: Path) -> str:
    """Load docs/BACKLOG.md content, return empty string if missing."""
    backlog = repo / "docs" / "BACKLOG.md"
    if not backlog.exists():
        return ""
    return backlog.read_text(encoding="utf-8", errors="replace")


def _find_run_archive(repo: Path) -> Path | None:
    """Find the .claude/run-archive directory.

    In a worktree, the run-archive lives in the main repo's .claude/ directory.
    We use git to find the common .git directory and derive the main repo root.
    """
    run_archive = repo / ".claude" / "run-archive"
    if run_archive.exists():
        return run_archive

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


def extract_source_paths(text: str) -> list[str]:
    """Extract file paths with tracked-extension types from text."""
    path_re = re.compile(
        r"[`'\"]?([a-zA-Z0-9_./-]+(?:\.[a-z]{2,5}))[`'\"]?"
    )
    refs = []
    for m in path_re.finditer(text):
        path = m.group(1)
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        if ext in SOURCE_EXTS:
            basename = Path(path).name
            if basename not in IGNORE_BASENAMES and len(basename) > 4:
                refs.append(path)
    return refs


def is_referenced_in_backlog(backlog_text: str, basename: str) -> bool:
    """Return True if the basename is meaningfully referenced in BACKLOG.md.

    Checks all lines (not just open items) since the file might be tracked
    as part of a done item.
    """
    for line in backlog_text.splitlines():
        if basename in line:
            return True
    return False


def find_future_work_context(text: str) -> list[tuple[str, str]]:
    """Return (trigger_phrase, context_line) for lines with future-work signals.

    Skips boilerplate sections like '## Alternatives considered' and
    '## Morning review action' (these are standard decision doc sections,
    not indicators of floating work).
    """
    in_alternatives_section = False
    results = []

    for line in text.splitlines():
        stripped = line.strip()

        # Track section context to skip boilerplate
        if re.match(r"^#{1,4}\s+Alternatives?\s+considered", stripped, re.IGNORECASE):
            in_alternatives_section = True
            continue
        if re.match(r"^#{1,4}\s+", stripped) and in_alternatives_section:
            in_alternatives_section = False

        if in_alternatives_section:
            continue

        m = FUTURE_WORK_RE.search(stripped)
        if m:
            results.append((m.group(0).lower(), stripped))

    return results


def scan_archive(repo: Path) -> list[tuple[str, str, str, str]]:
    """Scan run-archive directories for untracked future-work indicators.

    Returns list of (archive_abs_path, trigger_phrase, source_basename, sample_line).
    """
    run_archive = _find_run_archive(repo)
    if run_archive is None:
        return []

    backlog_text = load_backlog(repo)
    candidates = []
    seen_keys: set[tuple[str, str]] = set()

    for date_dir in sorted(run_archive.iterdir()):
        if not date_dir.is_dir():
            continue
        for subdir_name in SUBDIRS:
            subdir = date_dir / subdir_name
            if not subdir.exists():
                continue
            for obs_file in sorted(subdir.iterdir()):
                if not obs_file.is_file():
                    continue
                try:
                    text = obs_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                future_contexts = find_future_work_context(text)
                if not future_contexts:
                    continue

                source_paths = extract_source_paths(text)
                abs_path = str(obs_file)

                for trigger_phrase, sample_line in future_contexts:
                    # Find source files mentioned that aren't in backlog
                    for src_path in source_paths:
                        basename = Path(src_path).name
                        if is_referenced_in_backlog(backlog_text, basename):
                            continue
                        key = (abs_path, basename)
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        candidates.append((abs_path, trigger_phrase, basename, sample_line))
                    break  # one trigger-phrase per file is enough

    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None,
                        help="Path to repo root (default: auto-detect from script location)")
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        repo = Path(__file__).resolve().parent.parent

    if _find_run_archive(repo) is None:
        print("OK: no .claude/run-archive/ directory found", file=sys.stderr)
        sys.exit(0)

    candidates = scan_archive(repo)

    for abs_path, trigger_phrase, basename, sample_line in candidates:
        print(f"CANDIDATE: {abs_path}  trigger={trigger_phrase!r}  source={basename!r}")
        print(f"  sample: {sample_line[:100]}")

    if candidates:
        print(
            f"\nSummary: {len(candidates)} candidate backlog item(s) from archived observations",
            file=sys.stderr,
        )
    else:
        print("OK: no untracked candidates in archived observations", file=sys.stderr)

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
