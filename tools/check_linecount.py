#!/usr/bin/env python3
"""check_linecount — File-size ratchet (wave S-45-RATCHET).

Walks the repo, classifies every source file into a tiered category, and:

  * default mode    — fails (exit 1) if a non-baselined file exceeds its
                       category hard cap, or a baselined file has grown beyond
                       its recorded baseline. Tests over 1000 lines print a
                       WARNING but do NOT fail.
  * --snapshot      — writes `.linecount-baseline.json` listing every file
                       currently above its category hard cap (the frozen
                       ceiling for existing oversize files).
  * --update-shrunk — for any baselined file whose current size is *lower*
                       than its baseline, rewrite the baseline entry to the
                       new (smaller) value. Manual ratchet-tightening step.

Pure-Python stdlib only — no new dependencies. Determinism guarantees:
file lists are sorted by path, JSON is written with sorted keys and
indent=2, and `--snapshot` produces byte-identical output for a given tree.

Specified by `.claude/waves/S-45-RATCHET.md`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import sys
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Configuration — tiered caps + patterns
# ---------------------------------------------------------------------------
# The order of CATEGORIES is load-bearing. Categories are evaluated in this
# order; the first pattern that matches wins. So narrow patterns (e.g. Vue
# views, API routers) MUST appear before broader ones (frontend other,
# production code).

# Each entry: (category_key, hard_cap, list_of_glob_patterns)
# Patterns are POSIX-style globs matched against the repo-relative POSIX path
# using fnmatch.fnmatchcase (so `**/` is matched explicitly via `*` segments).
CATEGORIES: list[tuple[str, int, list[str]]] = [
    # Vue views — capped at 600 (existing CLAUDE.md rule)
    ("vue_views", 600, [
        "frontend/src/views/*.vue",
        "frontend/src/views/**/*.vue",
    ]),
    # API routers — looser cap (800) because routers aggregate many endpoints
    ("api_routers", 800, [
        "backend/api/*.py",
        "backend/api/**/*.py",
    ]),
    # Production code — strict cap (500)
    ("production_code", 500, [
        "backend/core/*.py", "backend/core/**/*.py",
        "backend/health/*.py", "backend/health/**/*.py",
        "backend/manifests/*.py", "backend/manifests/**/*.py",
        "backend/platform/*.py", "backend/platform/**/*.py",
        "backend/infra/*.py", "backend/infra/**/*.py",
        "backend/agent/*.py", "backend/agent/**/*.py",
    ]),
    # Frontend other — anything under frontend/src that didn't match views
    ("frontend_other", 500, [
        "frontend/src/*.vue", "frontend/src/**/*.vue",
        "frontend/src/*.ts", "frontend/src/**/*.ts",
    ]),
    # Tests — informational only (does NOT fail CI). Must be evaluated BEFORE
    # `cli_installer` so that `installer/tests/**` matches `tests` instead of
    # being swallowed by the broader `installer/**` pattern.
    ("tests", 1000, [
        "tests/*.py", "tests/**/*.py",
        "installer/tests/*.py", "installer/tests/**/*.py",
    ]),
    # CLI / installer scripts
    ("cli_installer", 800, [
        "cli/*.py", "cli/**/*.py",
        "installer/*.py", "installer/**/*.py",
    ]),
]

# Convenience: dict form for JSON output / lookup.
CAPS: dict[str, int] = {key: cap for key, cap, _patterns in CATEGORIES}

# Extensions included by the walker.
INCLUDED_EXTENSIONS = frozenset({".py", ".vue", ".ts"})

# Directory names that terminate descent (matched against any path component).
EXCLUDED_DIR_NAMES = frozenset({
    "node_modules", ".venv", "venv", "dist", ".git",
    "__pycache__", "build", ".next",
})

# Glob patterns that exclude individual files (matched against repo-relative
# POSIX path). Mirrors the directory list for belt-and-suspenders coverage if
# someone passes a custom root.
EXCLUDE_GLOBS = (
    "**/node_modules/**", "**/.venv/**", "**/venv/**", "**/dist/**",
    "**/.git/**", "**/__pycache__/**", "**/build/**", "**/.next/**",
)

BASELINE_FILENAME = ".linecount-baseline.json"


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------

def classify(rel_posix_path: str) -> str | None:
    """Return the category key for `rel_posix_path`, or None if uncategorized.

    Categories are evaluated in CATEGORIES order; first match wins.
    """
    for key, _cap, patterns in CATEGORIES:
        for pattern in patterns:
            if fnmatch.fnmatchcase(rel_posix_path, pattern):
                return key
    return None


def _path_excluded(rel_posix_path: str) -> bool:
    for pattern in EXCLUDE_GLOBS:
        if fnmatch.fnmatchcase(rel_posix_path, pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# File walking
# ---------------------------------------------------------------------------

def iter_source_files(root: Path) -> Iterable[tuple[str, Path]]:
    """Yield (rel_posix_path, absolute_path) for every source file under root.

    Skips excluded directories and respects INCLUDED_EXTENSIONS. Output is
    deterministically sorted by rel_posix_path.
    """
    root = root.resolve()
    collected: list[tuple[str, Path]] = []

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except (PermissionError, FileNotFoundError):
            return
        for entry in entries:
            if entry.is_symlink():
                # Skip symlinks to avoid loops / surprise content.
                continue
            if entry.is_dir():
                if entry.name in EXCLUDED_DIR_NAMES:
                    continue
                _walk(entry)
                continue
            if not entry.is_file():
                continue
            if entry.suffix not in INCLUDED_EXTENSIONS:
                continue
            try:
                rel = entry.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if _path_excluded(rel):
                continue
            collected.append((rel, entry))

    _walk(root)
    collected.sort(key=lambda item: item[0])
    yield from collected


def count_lines(path: Path) -> int:
    """Spec: len(file.read_text(errors='ignore').splitlines())."""
    return len(path.read_text(errors="ignore").splitlines())


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------

def baseline_path(root: Path) -> Path:
    return root / BASELINE_FILENAME


def load_baseline(root: Path) -> dict:
    """Return baseline JSON, or an empty skeleton if it doesn't exist."""
    bp = baseline_path(root)
    if not bp.exists():
        return {"generated_at": "", "caps": dict(CAPS), "files": []}
    return json.loads(bp.read_text())


def dump_baseline(root: Path, data: dict) -> str:
    """Serialize `data` to deterministic JSON and write to .linecount-baseline.json.

    Returns the serialized string for tests / debugging.
    """
    # Files sorted by path for determinism. Each entry's keys sorted too.
    files = sorted(data.get("files", []), key=lambda f: f["path"])
    payload = {
        "generated_at": data.get("generated_at", ""),
        "caps": data.get("caps", dict(CAPS)),
        "files": files,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    baseline_path(root).write_text(text)
    return text


def build_snapshot(root: Path, now: _dt.datetime | None = None) -> dict:
    """Walk `root` and produce a baseline dict listing files over their cap.

    For deterministic re-snapshot output: if a baseline already exists and
    its `files` list is byte-equivalent to the freshly computed one, we
    preserve the prior `generated_at` timestamp. This means re-running
    `--snapshot` on an unchanged tree produces a byte-identical file.
    """
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    over: list[dict] = []
    for rel, abs_path in iter_source_files(root):
        category = classify(rel)
        if category is None:
            continue
        cap = CAPS[category]
        lines = count_lines(abs_path)
        if lines > cap:
            over.append({"path": rel, "lines": lines, "category": category})
    over.sort(key=lambda f: f["path"])

    generated_at = now.isoformat()
    bp = baseline_path(root)
    if bp.exists():
        try:
            prior = json.loads(bp.read_text())
        except json.JSONDecodeError:
            prior = None
        if prior and prior.get("files") == over and prior.get("caps") == dict(CAPS):
            # Tree state matches existing baseline — preserve timestamp for
            # byte-identical re-snapshot determinism.
            generated_at = prior.get("generated_at") or generated_at

    return {
        "generated_at": generated_at,
        "caps": dict(CAPS),
        "files": over,
    }


# ---------------------------------------------------------------------------
# Check / update modes
# ---------------------------------------------------------------------------

def _baseline_map(baseline: dict) -> dict[str, int]:
    """Convert baseline['files'] into {path: baseline_lines}."""
    return {entry["path"]: entry["lines"] for entry in baseline.get("files", [])}


def run_check(root: Path, *, out=sys.stdout) -> int:
    """Default mode. Return 0 on pass, 1 on fail.

    Failure rules:
      1. A file NOT in the baseline whose line count exceeds its category cap
         (except `tests` — those only produce a WARNING).
      2. A baselined file whose current line count exceeds its baselined value.
    """
    baseline = load_baseline(root)
    baselined = _baseline_map(baseline)

    violations: list[str] = []
    warnings: list[str] = []

    for rel, abs_path in iter_source_files(root):
        category = classify(rel)
        if category is None:
            continue
        cap = CAPS[category]
        lines = count_lines(abs_path)

        if rel in baselined:
            # Baselined file — must not grow beyond its recorded baseline.
            base_lines = baselined[rel]
            if lines > base_lines:
                violations.append(
                    f"{rel}:{lines} / {base_lines} ({category})"
                )
            continue

        # Not baselined — must stay under the category hard cap.
        if lines > cap:
            if category == "tests":
                warnings.append(
                    f"WARNING: {rel}:{lines} > {cap} ({category}) "
                    f"— informational, not failing"
                )
            else:
                violations.append(f"{rel}:{lines} / {cap} ({category})")

    for w in warnings:
        print(w, file=out)

    if violations:
        print("File-size ratchet: violations", file=out)
        for v in violations:
            print(v, file=out)
        return 1

    return 0


def run_snapshot(root: Path) -> int:
    """Generate `.linecount-baseline.json` from the current tree state."""
    data = build_snapshot(root)
    dump_baseline(root, data)
    return 0


def run_update_shrunk(root: Path, *, out=sys.stdout) -> int:
    """Rewrite baseline entries for files that have shrunk below their baseline.

    Files that have *grown* are left untouched (and will fail the next check).
    Files that have shrunk *below* their category cap are removed from the
    baseline entirely. Files no longer present are removed.
    """
    baseline = load_baseline(root)
    baselined = _baseline_map(baseline)
    # Build current line-count lookup for every file currently in the tree.
    current: dict[str, tuple[int, str]] = {}
    for rel, abs_path in iter_source_files(root):
        category = classify(rel)
        if category is None:
            continue
        current[rel] = (count_lines(abs_path), category)

    new_files: list[dict] = []
    for entry in baseline.get("files", []):
        path = entry["path"]
        if path not in current:
            # File deleted / moved — drop from baseline.
            print(f"removed (no longer present): {path}", file=out)
            continue
        lines_now, category = current[path]
        cap = CAPS.get(category, entry.get("lines", 0))
        if lines_now <= cap:
            # File has shrunk under its category cap — drop from baseline.
            print(
                f"shrunk under cap: {path} {entry['lines']} -> {lines_now} "
                f"(cap {cap}) — removed from baseline",
                file=out,
            )
            continue
        if lines_now < entry["lines"]:
            print(
                f"shrunk: {path} {entry['lines']} -> {lines_now} ({category})",
                file=out,
            )
            new_files.append({"path": path, "lines": lines_now, "category": category})
        else:
            # Same or grew — keep baseline value untouched. (Growth fails check.)
            new_files.append(dict(entry))

    baseline["files"] = new_files
    baseline["generated_at"] = (
        _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    )
    dump_baseline(root, baseline)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--snapshot", action="store_true",
        help="Generate .linecount-baseline.json from current tree.",
    )
    mode.add_argument(
        "--update-shrunk", action="store_true",
        help="Lower baseline entries for files that have shrunk.",
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Repo root (defaults to script's parent directory).",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve() if args.root else Path(__file__).resolve().parent.parent

    if args.snapshot:
        return run_snapshot(root)
    if args.update_shrunk:
        return run_update_shrunk(root)
    return run_check(root)


if __name__ == "__main__":
    sys.exit(main())
