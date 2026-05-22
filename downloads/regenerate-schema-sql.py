#!/usr/bin/env python3
"""tools/regenerate-schema-sql.py

Apply all migrations to a fresh in-memory SQLite database, dump the
resulting schema, and overwrite backend/core/schema.sql.

Usage:
    python3 tools/regenerate-schema-sql.py [--check]

Options:
    --check     Print a diff and exit non-zero if schema.sql is out of date.
                (Used by CI / ms-enforce. Does not overwrite schema.sql.)
    --help      Show this message.

Developer workflow:
    1. Write a new migration in migrations/NNN_*.{sql,py}.
    2. Run this script to regenerate schema.sql.
    3. Commit migration + updated schema.sql in the same commit.
    4. CI re-runs --check and fails if they don't match.

See: docs/cleanup/01_migrations_design.md §4 (Model B) for the rationale.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO / "migrations"
SCHEMA_SQL = REPO / "backend" / "core" / "schema.sql"

_MIGRATION_NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.(sql|py)$")

_SCHEMA_HEADER = """\
-- Mediastack v4 — SQLite State Schema
-- GENERATED FILE — do not edit directly.
-- To update: add a migration in migrations/ and run tools/regenerate-schema-sql.py
--
-- This file is kept as a human-readable reference for the current DB schema.
-- The authoritative source of schema changes is the numbered files in migrations/.
-- See docs/cleanup/01_migrations_design.md for the rationale.
"""


def _scan_migrations(d: Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for p in d.iterdir():
        if p.is_dir():
            continue
        m = _MIGRATION_NAME_RE.match(p.name)
        if not m:
            continue
        out.append((int(m.group(1)), p))
    out.sort()
    return out


def _apply_sql(conn: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)


def _apply_py(conn: sqlite3.Connection, path: Path) -> None:
    spec = importlib.util.spec_from_file_location("_mig_regen", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.upgrade(conn)
    conn.commit()


def build_schema_from_migrations() -> str:
    """Apply all migrations to :memory: and return the schema SQL text."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    for _version, path in _scan_migrations(MIGRATIONS_DIR):
        if path.suffix == ".sql":
            _apply_sql(conn, path)
        else:
            _apply_py(conn, path)

    # Dump schema: all non-internal tables/indexes/triggers, sorted
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'schema_migrations%' "
        "ORDER BY type DESC, name"   # tables before indexes
    ).fetchall()

    parts: list[str] = [_SCHEMA_HEADER]
    for row in rows:
        parts.append(row["sql"].rstrip() + ";")
        parts.append("")

    conn.close()
    return "\n".join(parts) + "\n"


def _normalize(text: str) -> str:
    """Normalize whitespace for comparison (collapse runs of blank lines,
    strip trailing whitespace from each line)."""
    lines = [line.rstrip() for line in text.splitlines()]
    # Collapse 2+ blank lines to one
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                out.append(line)
        else:
            blank_run = 0
            out.append(line)
    return "\n".join(out).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if schema.sql is out of date (CI mode)",
    )
    args = parser.parse_args()

    generated = build_schema_from_migrations()

    if args.check:
        if not SCHEMA_SQL.exists():
            print(f"FAIL: {SCHEMA_SQL} does not exist.", file=sys.stderr)
            print("Run: python3 tools/regenerate-schema-sql.py", file=sys.stderr)
            return 1
        on_disk = SCHEMA_SQL.read_text(encoding="utf-8")
        if _normalize(generated) != _normalize(on_disk):
            print(
                "FAIL: backend/core/schema.sql is out of sync with migrations/.",
                file=sys.stderr,
            )
            print(
                "A migration was added without regenerating schema.sql.",
                file=sys.stderr,
            )
            print(
                "Fix: python3 tools/regenerate-schema-sql.py && git add backend/core/schema.sql",
                file=sys.stderr,
            )
            # Show a truncated diff for quick diagnosis
            import difflib
            diff = list(difflib.unified_diff(
                _normalize(on_disk).splitlines(keepends=True),
                _normalize(generated).splitlines(keepends=True),
                fromfile="schema.sql (on disk)",
                tofile="schema.sql (generated)",
                n=3,
            ))
            sys.stderr.writelines(diff[:60])
            if len(diff) > 60:
                print(f"... ({len(diff) - 60} more lines)", file=sys.stderr)
            return 1
        print("OK: schema.sql is in sync with migrations/.")
        return 0

    # Overwrite mode
    SCHEMA_SQL.write_text(generated, encoding="utf-8")
    print(f"Wrote {SCHEMA_SQL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
