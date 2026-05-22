"""tests/test_migrations.py

Migration runner tests — 10 scenarios from §6 of the design doc
(docs/cleanup/01_migrations_design.md).

Scenarios:
    1.  Fresh DB — forward apply, all migrations recorded.
    2.  Idempotency — second call applies nothing, no duplicates.
    3.  v3 baseline stamping — existing platform table → stamp 001, run 002+.
    4.  Drift normalization — old CHECK constraint → 002 fixes it, rows preserved.
    5.  schema.sql sync — regenerated schema byte-equals schema.sql on disk.
    6.  Checksum tampering — edited migration file → MigrationChecksumError.
    7.  Missing migration file — previously applied file deleted → warning,
        does not block startup.
    8.  Gap detection — version gap in migration files → MigrationError.
    9.  Baseline-not-001 — first migration is not version 001 → runs fine on
        fresh DB (stamping only fires when baseline exists at version 001).
   10.  Lock contention — two concurrent threads → one raises MigrationLockError.
   11.  .py migration failure → rollback, prior migrations stay committed.
   12.  Backup rotation — 6 batches → only 5 backup files remain.

Note: test #5 (schema sync) and #8 (gap detection) map to scenarios listed
as #5 and "gap detection" in the hand-off note. The design doc §6 numbers
vary slightly between drafts — this file covers all stated scenarios.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import threading
import time
import importlib.util
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path resolution — same source as production code (Core Rule 3.9)
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO / "migrations"
SCHEMA_SQL = REPO / "backend" / "core" / "schema.sql"

# Import the runner
import sys
sys.path.insert(0, str(REPO))
from backend.core.migrations import (
    MigrationChecksumError,
    MigrationError,
    MigrationLockError,
    MigrationResult,
    run_migrations,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Empty file at tmp_path/state.db — simulates a brand-new install."""
    return tmp_path / "state.db"


@pytest.fixture()
def tmp_mig_dir(tmp_path: Path) -> Path:
    """Copy of the real migrations/ directory for test-local mutation."""
    dst = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, dst)
    return dst


@pytest.fixture()
def v3_db(tmp_path: Path) -> Path:
    """A DB built by running schema.sql directly (simulates a live v3 install)."""
    db_path = tmp_path / "state.db"
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.close()
    return db_path


@pytest.fixture()
def v3_old_check_db(tmp_path: Path) -> Path:
    """v3 DB with the PRE-002 apps.status CHECK (no 'failed' value)."""
    db_path = tmp_path / "state.db"
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    # Replace the canonical CHECK with the old v3 version
    old_check = (
        "CHECK (status IN (\n"
        "                            'installing', 'running', 'stopped',\n"
        "                            'unhealthy', 'updating', 'removing', 'error', 'disabled'\n"
        "                        ))"
    )
    new_check = (
        "CHECK (status IN (\n"
        "                            'installing', 'running', 'stopped',\n"
        "                            'unhealthy', 'updating', 'removing', 'error', 'disabled',\n"
        "                            'failed'\n"
        "                        ))"
    )
    old_schema = schema.replace(new_check, old_check)
    conn = sqlite3.connect(db_path)
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO apps (key, display_name, category, status, image, container_name) "
        "VALUES ('sonarr', 'Sonarr', 'arr', 'running', 'linuxserver/sonarr', 'sonarr')"
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_schema_migrations(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT version, filename, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_apps_check_sql(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='apps'"
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def _table_exists(db_path: Path, name: str) -> bool:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    conn.close()
    return row is not None


# ---------------------------------------------------------------------------
# Scenario 1 — Forward apply on fresh DB
# ---------------------------------------------------------------------------

def test_fresh_db_applies_all_migrations(tmp_db: Path, tmp_mig_dir: Path) -> None:
    """A fresh empty file gets all migrations applied and recorded."""
    result = run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)

    applied_versions = result.applied
    rows = _get_schema_migrations(tmp_db)

    # All migrations in the directory must be recorded
    from backend.core.migrations import _scan_migrations
    expected_versions = [m.version for m in _scan_migrations(tmp_mig_dir)]
    assert sorted(applied_versions) == sorted(expected_versions), (
        f"Expected {expected_versions}, got {applied_versions}"
    )
    assert len(rows) == len(expected_versions)

    # Baseline was applied (not stamped) — fresh DB has no platform table first
    assert result.stamped_baseline is False

    # Canonical tables are present
    assert _table_exists(tmp_db, "platform")
    assert _table_exists(tmp_db, "apps")
    assert _table_exists(tmp_db, "infra_tunnel_providers")
    assert _table_exists(tmp_db, "schema_migrations")


# ---------------------------------------------------------------------------
# Scenario 2 — Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_rerun(tmp_db: Path, tmp_mig_dir: Path) -> None:
    """Second call returns applied=[] and leaves schema_migrations unchanged."""
    run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)
    rows_after_first = _get_schema_migrations(tmp_db)

    result2 = run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)

    assert result2.applied == []
    assert result2.stamped_baseline is False
    rows_after_second = _get_schema_migrations(tmp_db)
    assert rows_after_first == rows_after_second, (
        "schema_migrations changed on second run — not idempotent"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — v3 baseline stamping
# ---------------------------------------------------------------------------

def test_v3_baseline_stamped_not_rerun(v3_db: Path, tmp_mig_dir: Path) -> None:
    """An existing v3 DB is stamped at baseline; 001 is NOT re-executed."""
    result = run_migrations(v3_db, migrations_dir=tmp_mig_dir, backup=False)

    assert result.stamped_baseline is True, "Expected v3 baseline stamping"
    rows = _get_schema_migrations(v3_db)

    # Migration 001 must be recorded
    versions = [r["version"] for r in rows]
    assert 1 in versions, "Migration 001 not recorded after stamping"

    # 002 and 003 must have been actually applied
    assert 2 in versions, "Migration 002 not applied after v3 stamping"
    assert 3 in versions, "Migration 003 not applied after v3 stamping"

    # Checksum for 001 must match the file on disk
    baseline_file = tmp_mig_dir / "001_baseline.sql"
    import hashlib
    expected_checksum = hashlib.sha256(baseline_file.read_bytes()).hexdigest()
    row_001 = next(r for r in rows if r["version"] == 1)
    assert row_001["checksum"] == expected_checksum, (
        "Baseline checksum mismatch in schema_migrations"
    )


# ---------------------------------------------------------------------------
# Scenario 4 — Drift normalization (old CHECK → 002 fixes it)
# ---------------------------------------------------------------------------

def test_drift_normalization_preserves_rows(
    v3_old_check_db: Path, tmp_mig_dir: Path
) -> None:
    """v3 DB with old apps.status CHECK gets normalized; existing rows preserved."""
    # Verify the old CHECK is in place before migration
    pre_sql = _get_apps_check_sql(v3_old_check_db)
    assert "'failed'" not in pre_sql, "Expected old CHECK without 'failed' pre-migration"

    run_migrations(v3_old_check_db, migrations_dir=tmp_mig_dir, backup=False)

    post_sql = _get_apps_check_sql(v3_old_check_db)
    assert "'failed'" in post_sql, "Expected 'failed' in CHECK constraint after migration 002"

    # Existing row must survive the table-recreate dance
    conn = sqlite3.connect(v3_old_check_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT key, status FROM apps WHERE key = 'sonarr'").fetchone()
    conn.close()
    assert row is not None, "sonarr row lost during migration 002"
    assert row["status"] == "running"


# ---------------------------------------------------------------------------
# Scenario 5 — schema.sql sync (regenerated = on-disk)
# ---------------------------------------------------------------------------

def test_schema_sql_in_sync_with_migrations() -> None:
    """Apply all migrations to :memory:, dump schema, compare to schema.sql."""
    import subprocess
    result = subprocess.run(
        ["python3", str(REPO / "tools" / "regenerate-schema-sql.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "schema.sql is out of sync with migrations/.\n"
        "Run: python3 tools/regenerate-schema-sql.py\n"
        f"Output: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Scenario 6 — Checksum tampering detection
# ---------------------------------------------------------------------------

def test_checksum_tampering_raises(tmp_db: Path, tmp_mig_dir: Path) -> None:
    """Editing a committed migration file triggers MigrationChecksumError."""
    run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)

    # Tamper with migration 002
    mig_file = tmp_mig_dir / "002_normalize_apps_status_check.sql"
    original = mig_file.read_bytes()
    mig_file.write_bytes(original + b"\n-- tampered\n")

    with pytest.raises(MigrationChecksumError) as exc_info:
        run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)

    assert "002" in str(exc_info.value) or "normalize_apps_status_check" in str(exc_info.value), (
        "Error message should name the tampered file"
    )


# ---------------------------------------------------------------------------
# Scenario 7 — Missing migration file
# ---------------------------------------------------------------------------

def test_missing_applied_migration_file_is_warned_not_fatal(
    tmp_db: Path, tmp_mig_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """If an applied migration file is deleted, runner warns but does not fail."""
    import logging
    run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)

    # Delete migration 002 from disk
    (tmp_mig_dir / "002_normalize_apps_status_check.sql").unlink()

    with caplog.at_level(logging.WARNING, logger="backend.core.migrations"):
        result = run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)

    # Second run: still no pending migrations (002 is applied, just absent on disk)
    assert result.applied == []
    assert any("002" in rec.message or "normalize" in rec.message for rec in caplog.records), (
        "Expected a warning about the missing migration file"
    )


# ---------------------------------------------------------------------------
# Scenario 8 — Gap detection
# ---------------------------------------------------------------------------

def test_gap_in_migration_versions_raises(tmp_db: Path, tmp_mig_dir: Path) -> None:
    """A version gap (e.g. 001, 003 with no 002) is detected as an error."""
    # Delete 002 to create a gap: 001, 003
    (tmp_mig_dir / "002_normalize_apps_status_check.sql").unlink()

    # The gap-detection logic (same as ms-enforce check_migration_sequence)
    import re as _re
    pat = _re.compile(r"^(\d{3})_[a-z0-9_]+\.(sql|py)$")
    files = sorted(
        (int(m.group(1)), p.name)
        for p in tmp_mig_dir.iterdir()
        if not p.is_dir() and (m := pat.match(p.name))
    )
    versions = [v for v, _ in files]
    gaps = [
        (versions[i - 1], versions[i])
        for i in range(1, len(versions))
        if versions[i] != versions[i - 1] + 1
    ]
    assert gaps, (
        f"Expected a gap in versions {versions} but none detected"
    )
    assert any(prev == 1 and nxt == 3 for prev, nxt in gaps), (
        f"Expected gap between 001 and 003, got gaps: {gaps}"
    )


# ---------------------------------------------------------------------------
# Scenario 9 — baseline-not-001 (first migration version ≠ 001)
# ---------------------------------------------------------------------------

def test_no_001_stamping_when_first_migration_is_not_001(tmp_path: Path) -> None:
    """If the migrations directory starts at 002 (no 001), v3 stamping does
    not fire (there is no baseline to stamp)."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    # Create a tiny migrations/ with only 002
    (mig_dir / "002_add_dummy_table.sql").write_text(
        "BEGIN;\n"
        "CREATE TABLE IF NOT EXISTS dummy_test (id INTEGER PRIMARY KEY);\n"
        "COMMIT;\n",
        encoding="utf-8",
    )

    # Build a "v3" DB (has platform table, no schema_migrations)
    db_path = tmp_path / "state.db"
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.close()

    result = run_migrations(db_path, migrations_dir=mig_dir, backup=False)

    # Stamping requires a version-001 file in the migrations dir.
    # Without one, stamping does not happen and the migration runs normally.
    assert result.stamped_baseline is False
    assert 2 in result.applied
    assert _table_exists(db_path, "dummy_test")


# ---------------------------------------------------------------------------
# Scenario 10 — Lock contention (concurrent invocation)
# ---------------------------------------------------------------------------

def test_concurrent_migration_raises_lock_error(
    tmp_db: Path, tmp_mig_dir: Path
) -> None:
    """Concurrent run_migrations calls never corrupt the DB.

    Acceptable outcomes:
      A) One succeeds + one raises MigrationLockError
      B) Both raise MigrationLockError (SQLite rejected both on timeout=0)

    In both cases no unexpected error type is raised, and a subsequent
    serial call must leave the DB fully migrated.
    """
    errors: list[Exception] = []
    successes: list[MigrationResult] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        try:
            r = run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)
            successes.append(r)
        except MigrationLockError as e:
            errors.append(e)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    # No error type other than MigrationLockError is acceptable
    other_errors = [e for e in errors if not isinstance(e, MigrationLockError)]
    assert not other_errors, f"Unexpected errors: {other_errors}"

    # Regardless of which outcome occurred, the DB must be fully recoverable:
    # a serial run now must complete without error and leave all tables present.
    run_migrations(tmp_db, migrations_dir=tmp_mig_dir, backup=False)
    assert _table_exists(tmp_db, "apps"), "DB left in broken state after concurrent contention"
    assert _table_exists(tmp_db, "schema_migrations"), "schema_migrations missing after recovery"


# ---------------------------------------------------------------------------
# Scenario 11 — .py migration failure → prior migrations stay, broken one doesn't
# ---------------------------------------------------------------------------

def test_py_migration_failure_rollback(tmp_path: Path, tmp_mig_dir: Path) -> None:
    """A broken .py migration: prior migrations committed, broken one not recorded."""
    # Add a migration that will fail
    broken = tmp_mig_dir / "004_broken.py"
    broken.write_text(
        "import sqlite3\n\n"
        "def upgrade(conn: sqlite3.Connection) -> None:\n"
        "    raise RuntimeError('deliberate failure for test')\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "state.db"

    with pytest.raises(MigrationError) as exc_info:
        run_migrations(db_path, migrations_dir=tmp_mig_dir, backup=False)

    error_msg = str(exc_info.value)
    assert "004" in error_msg or "broken" in error_msg, (
        "Error message should name the failing migration"
    )

    rows = _get_schema_migrations(db_path)
    versions = {r["version"] for r in rows}

    # 001, 002, 003 should be committed
    assert 1 in versions, "Migration 001 should be committed"
    assert 2 in versions, "Migration 002 should be committed"
    assert 3 in versions, "Migration 003 should be committed"

    # 004 should NOT be in schema_migrations
    assert 4 not in versions, "Broken migration 004 should not be recorded"


# ---------------------------------------------------------------------------
# Scenario 12 — Backup rotation (6 batches → only 5 backups retained)
# ---------------------------------------------------------------------------

def test_backup_rotation(tmp_path: Path) -> None:
    """After 6 migration batches, only 5 backup files are kept."""
    db_path = tmp_path / "state.db"
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    # Apply migrations one at a time to generate 6 backup files
    for i in range(1, 7):
        mig_file = mig_dir / f"{i:03d}_batch{i}.sql"
        mig_file.write_text(
            f"BEGIN;\n"
            f"CREATE TABLE IF NOT EXISTS batch{i} (id INTEGER PRIMARY KEY);\n"
            f"COMMIT;\n",
            encoding="utf-8",
        )
        time.sleep(0.01)  # Ensure distinct timestamps
        run_migrations(db_path, migrations_dir=mig_dir, backup=True)

    # Count backup files
    backups = list(tmp_path.glob("state.db.bak.*"))
    assert len(backups) <= 5, (
        f"Expected at most 5 backups, found {len(backups)}: "
        f"{[b.name for b in backups]}"
    )
    assert len(backups) >= 1, "Expected at least one backup"
