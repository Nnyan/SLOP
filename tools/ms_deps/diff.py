"""
tools.ms_deps.diff — Compare two uv.lock files and report version changes.

Usage:
    python3 -m tools.ms_deps.diff path/to/old/uv.lock path/to/new/uv.lock

Options:
    --include-unchanged   Include unchanged packages in the output table.
    --format=json         Output JSON list instead of a markdown table.

Exit codes:
    0  success (even if there are no changes)
    1  error (bad arguments, unreadable file, invalid TOML, missing [[package]] tables)
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------

class _Version(NamedTuple):
    major: int
    minor: int
    patch: int
    raw: str  # original string, kept for display


def _parse_version(v: str) -> _Version | None:
    """Parse a simple X.Y.Z version string.  Returns None for anything exotic."""
    parts = v.split(".")
    if len(parts) < 3:
        # Try X.Y (treat patch as 0)
        if len(parts) == 2:
            try:
                return _Version(int(parts[0]), int(parts[1]), 0, v)
            except ValueError:
                return None
        return None
    try:
        return _Version(int(parts[0]), int(parts[1]), int(parts[2]), v)
    except ValueError:
        return None


def _classify_change(old_ver: str, new_ver: str) -> str:
    """Return a human-readable change label for a version bump."""
    if old_ver == new_ver:
        return "unchanged"

    old = _parse_version(old_ver)
    new = _parse_version(new_ver)

    if old is None or new is None:
        # Exotic version strings — fall back to a plain label
        return "changed"

    if new.major != old.major:
        direction = "up" if new.major > old.major else "down"
        arrow = "↑" if direction == "up" else "↓"
        return f"major{arrow}"

    if new.minor != old.minor:
        direction = "up" if new.minor > old.minor else "down"
        arrow = "↑" if direction == "up" else "↓"
        return f"minor{arrow}"

    if new.patch != old.patch:
        direction = "up" if new.patch > old.patch else "down"
        arrow = "↑" if direction == "up" else "↓"
        return f"patch{arrow}"

    # Same numeric components but different raw strings (e.g. trailing ".0")
    return "changed"


# ---------------------------------------------------------------------------
# Lockfile parsing
# ---------------------------------------------------------------------------

def _load_packages(path: Path) -> dict[str, str]:
    """
    Parse a uv.lock file and return a mapping of {package_name: version}.

    Raises SystemExit(1) on any error so CLI callers get a clean message.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        print(f"error: {path} is not valid TOML: {exc}", file=sys.stderr)
        sys.exit(1)

    packages_raw = data.get("package")
    if packages_raw is None:
        print(
            f"error: {path} contains no [[package]] tables — is this a valid uv.lock?",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(packages_raw, list):
        print(
            f"error: {path} 'package' key is not a list — unexpected format",
            file=sys.stderr,
        )
        sys.exit(1)

    result: dict[str, str] = {}
    for entry in packages_raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        version = entry.get("version")
        if name and version:
            result[str(name)] = str(version)

    if not result:
        print(
            f"error: {path} has [[package]] tables but none have both 'name' and 'version' — "
            "cannot diff",
            file=sys.stderr,
        )
        sys.exit(1)

    return result


# ---------------------------------------------------------------------------
# Diff logic
# ---------------------------------------------------------------------------

class DiffRow(NamedTuple):
    name: str
    old: str | None   # None means added (not in old lock)
    new: str | None   # None means removed (not in new lock)
    change: str


def compute_diff(old_packages: dict[str, str], new_packages: dict[str, str]) -> list[DiffRow]:
    """Return a list of DiffRow entries for all packages in either lockfile."""
    all_names = sorted(set(old_packages) | set(new_packages))
    rows: list[DiffRow] = []
    for name in all_names:
        old_ver = old_packages.get(name)
        new_ver = new_packages.get(name)
        if old_ver is None:
            rows.append(DiffRow(name=name, old=None, new=new_ver, change="added"))
        elif new_ver is None:
            rows.append(DiffRow(name=name, old=old_ver, new=None, change="removed"))
        else:
            change = _classify_change(old_ver, new_ver)
            rows.append(DiffRow(name=name, old=old_ver, new=new_ver, change=change))
    return rows


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _format_markdown(rows: list[DiffRow], include_unchanged: bool) -> str:
    changed = [r for r in rows if r.change != "unchanged"]
    unchanged = [r for r in rows if r.change == "unchanged"]

    if not changed and not include_unchanged:
        return "(no changes)"

    lines: list[str] = [
        "| Package | Old | New | Change |",
        "|---|---|---|---|",
    ]

    def _row_line(r: DiffRow) -> str:
        old_str = r.old if r.old is not None else "—"
        new_str = r.new if r.new is not None else "—"
        return f"| {r.name} | {old_str} | {new_str} | {r.change} |"

    for r in changed:
        lines.append(_row_line(r))

    if include_unchanged and unchanged:
        # Separator row to visually group unchanged packages
        lines.append("|---|---|---|---|")
        for r in unchanged:
            lines.append(_row_line(r))

    return "\n".join(lines)


def _format_json(rows: list[DiffRow], include_unchanged: bool) -> str:
    output = []
    for r in rows:
        if not include_unchanged and r.change == "unchanged":
            continue
        output.append(
            {
                "name": r.name,
                "old": r.old,
                "new": r.new,
                "change": r.change,
            }
        )
    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.ms_deps.diff",
        description="Compare two uv.lock files and report version changes.",
    )
    parser.add_argument("old_lock", help="Path to the old/baseline uv.lock")
    parser.add_argument("new_lock", help="Path to the new/updated uv.lock")
    parser.add_argument(
        "--include-unchanged",
        action="store_true",
        default=False,
        help="Include unchanged packages in the output (default: hidden).",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        dest="output_format",
        help="Output format (default: markdown).",
    )
    args = parser.parse_args(argv)

    old_path = Path(args.old_lock)
    new_path = Path(args.new_lock)

    old_packages = _load_packages(old_path)
    new_packages = _load_packages(new_path)

    rows = compute_diff(old_packages, new_packages)

    if args.output_format == "json":
        print(_format_json(rows, args.include_unchanged))
    else:
        print(_format_markdown(rows, args.include_unchanged))

    return 0


if __name__ == "__main__":
    sys.exit(main())
