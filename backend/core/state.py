"""backend/core/state.py

Single point of access for the Mediastack state database.

Design rules:
  - All reads/writes go through StateDB — no direct sqlite3 calls elsewhere
  - StateDB is a context manager: `with StateDB() as db: db.method()`
  - Writes use explicit transactions; reads are auto-committed
  - All methods return typed dataclasses or None — no raw sqlite3.Row leakage
  - Plain-language errors are raised as StateError, never raw sqlite3 errors
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from backend.core.logging import get_logger

# ── Table name constants — single source of truth (Core Rule 3.3) ─────────
# Import these in tests rather than hardcoding table name strings.
# The Q3 bug (tunnel_providers vs infra_tunnel_providers) is prevented
# by having one canonical name imported everywhere it's used.
TABLE_PLATFORM          = "platform"
TABLE_INFRA_SLOTS       = "infra_slots"
TABLE_APPS              = "apps"
TABLE_HEALTH_CHECKS     = "health_checks"
TABLE_HEALTH_HISTORY    = "health_check_history"
TABLE_OPERATIONS        = "operations"
TABLE_PENDING_FIXES     = "pending_fixes"
TABLE_MAINTENANCE_WIN   = "maintenance_windows"
TABLE_TUNNEL_PROVIDERS  = "infra_tunnel_providers"
TABLE_SETTINGS          = "settings"
TABLE_STORAGE_SOURCES   = "storage_sources"
TABLE_MANIFEST_REGISTRY = "manifest_registry"


log = get_logger(__name__)

# Resolved at runtime by Config.from_env()
_DB_PATH: Path | None = None


# SQL verbs we recognise for the db_query_duration_seconds metric.
# Bounded set — anything outside this map collapses to OTHER for
# cardinality control (Rule 4.19 discipline).
_SQL_VERBS: frozenset[str] = frozenset({
    "SELECT", "INSERT", "UPDATE", "DELETE",
    "CREATE", "DROP", "ALTER",  # DDL family — collapsed below
})


def _sql_verb(sql: str) -> str:
    """First word of `sql`, normalised. CREATE/DROP/ALTER collapse to
    'DDL'; unknown verbs to 'OTHER'."""
    first = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else "OTHER"
    if first in {"CREATE", "DROP", "ALTER"}:
        return "DDL"
    return first if first in _SQL_VERBS else "OTHER"


# Step 4.2 — startup-complete flag. Flipped to True at the end of
# `init_db()` once migrations apply. `backend.api.probes` reads this
# for /startupz. Lives here (not in probes.py) so state.py doesn't
# need to import the API layer — keeps the dependency arrow pointing
# from `api/` -> `core/`, never the reverse.
_STARTUP_COMPLETE: bool = False


def configure(db_path: Path) -> None:
    """Set the database path before first use. Called once at startup."""
    global _DB_PATH
    _DB_PATH = db_path


class StateError(Exception):
    """Plain-language error from a state operation."""


# ---------------------------------------------------------------------------
# Platform default constants — single source of truth for schema defaults
# ---------------------------------------------------------------------------

# Default user app config directory — matches schema.sql DEFAULT for config_root.
# Referenced in CLAUDE.md "Three data directories" table and "Path layout" table.
# See: backend/core/schema.sql (platform.config_root DEFAULT).
DEFAULT_CONFIG_ROOT: str = "/srv/mediastack/config"


# ---------------------------------------------------------------------------
# Dataclasses — returned by StateDB methods, never raw sqlite3.Row
# ---------------------------------------------------------------------------


@dataclass
class Platform:
    status: str
    domain: str | None
    wildcard_domain: str | None
    network_name: str
    config_root: str
    media_root: str
    puid: int
    pgid: int
    timezone: str
    traefik_version: str | None
    cert_resolver: str
    installed_at: int | None
    updated_at: int


@dataclass
class InfraSlot:
    slot: str
    provider: str | None
    status: str
    config: dict[str, Any] = field(default_factory=dict)
    deployed_at: int | None = None
    updated_at: int = 0


@dataclass
class App:
    id: int
    key: str
    display_name: str
    tier: int
    category: str
    status: str
    image: str
    image_tag: str
    container_name: str
    web_port: int | None
    host_port: int | None
    config_path: str | None
    manifest_source: str | None
    extra_config: dict[str, Any] = field(default_factory=dict)
    installed_at: int = 0
    updated_at: int = 0
    last_healthy_at: int | None = None


@dataclass
class Operation:
    id: int
    operation: str
    subject_type: str
    subject_key: str
    status: str
    triggered_by: str
    detail: dict[str, Any] | None
    error: str | None
    started_at: int
    completed_at: int | None


@dataclass
class HealthCheck:
    subject_type: str
    subject_key: str
    check_name: str
    status: str
    summary: str
    detail: str | None
    auto_fix: str | None
    checked_at: int


# ---------------------------------------------------------------------------
# StateDB
# ---------------------------------------------------------------------------


class StateDB:
    """Context manager wrapping a SQLite connection.

    Usage:
        with StateDB() as db:
            platform = db.get_platform()

    The connection is opened on __enter__ and closed on __exit__.
    Exceptions inside the block trigger a rollback of any open transaction.
    """

    def __init__(self) -> None:
        if _DB_PATH is None:
            raise StateError(
                "Database path not configured. "
                "Call state.configure(path) at startup before using StateDB."
            )
        self._path = _DB_PATH
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "StateDB":
        self._conn = sqlite3.connect(self._path, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        if self._conn:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()   # always commit on clean exit
            self._conn.close()
        self._conn = None
        # returning None (implicit) is identical to False — exceptions propagate

    @property
    def _c(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StateError("StateDB used outside of context manager")
        return self._conn

    # ── Raw query helper ─────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute raw SQL — used by endpoints that need flexible queries.

        Always use parameterised queries (?). Never interpolate user data.

        Step 4.1 wire-up: every query records duration in the
        `mediastack_db_query_duration_seconds` histogram, labeled by
        SQL verb (`SELECT` / `INSERT` / `UPDATE` / `DELETE` / `DDL` /
        `OTHER`). Bounded cardinality per Rule 4.19. Metric import is
        lazy so test contexts that import state.py without the
        prometheus deps available don't break.
        """
        _t0 = time.monotonic()
        try:
            return self._c.execute(sql, params)
        finally:
            try:
                from backend.core.metrics import db_query_duration_seconds
                verb = _sql_verb(sql)
                db_query_duration_seconds.labels(verb=verb).observe(
                    time.monotonic() - _t0,
                )
            except Exception:
                # Metrics never break a query.
                pass

    # ── Helpers ───────────────────────────────────────────────────────────

    def _json_load(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            return cast(dict[str, Any], json.loads(value))
        except json.JSONDecodeError:
            return {}

    def _json_dump(self, value: dict[str, Any] | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    def _now(self) -> int:
        return int(time.time())

    # ── Platform ──────────────────────────────────────────────────────────

    def get_platform(self) -> Platform:
        """Return the platform singleton, creating it if needed."""
        row = self._c.execute("SELECT * FROM platform WHERE id = 1").fetchone()
        if row is None:
            self._c.execute(
                "INSERT OR IGNORE INTO platform (id, updated_at) VALUES (1, ?)",
                (self._now(),),
            )
            self._c.commit()
            row = self._c.execute("SELECT * FROM platform WHERE id = 1").fetchone()
        return Platform(
            status=row["status"],
            domain=row["domain"],
            wildcard_domain=row["wildcard_domain"],
            network_name=row["network_name"],
            config_root=row["config_root"],
            media_root=row["media_root"],
            puid=row["puid"],
            pgid=row["pgid"],
            timezone=row["timezone"],
            traefik_version=row["traefik_version"],
            cert_resolver=row["cert_resolver"],
            installed_at=row["installed_at"],
            updated_at=row["updated_at"],
        )

    def update_platform(self, **kwargs: Any) -> None:
        """Update one or more platform fields."""
        # Ensure the singleton row exists before updating
        self._c.execute(
            "INSERT OR IGNORE INTO platform (id, updated_at) VALUES (1, ?)",
            (self._now(),),
        )
        allowed = {
            "status", "domain", "wildcard_domain", "network_name",
            "config_root", "media_root", "puid", "pgid", "timezone",
            "traefik_version", "cert_resolver", "installed_at",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            self._c.commit()
            return
        updates["updated_at"] = self._now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        self._c.execute(
            f"UPDATE platform SET {cols} WHERE id = 1",
            list(updates.values()),
        )
        self._c.commit()

    # ── Infrastructure slots ──────────────────────────────────────────────

    def get_slot(self, slot: str) -> InfraSlot:
        row = self._c.execute(
            "SELECT * FROM infra_slots WHERE slot = ?", (slot,)
        ).fetchone()
        if row is None:
            raise StateError(f"Unknown infrastructure slot: '{slot}'")
        return InfraSlot(
            slot=row["slot"],
            provider=row["provider"],
            status=row["status"],
            config=self._json_load(row["config"]),
            deployed_at=row["deployed_at"],
            updated_at=row["updated_at"],
        )

    def get_all_slots(self) -> list[InfraSlot]:
        rows = self._c.execute("SELECT * FROM infra_slots ORDER BY slot").fetchall()
        return [
            InfraSlot(
                slot=r["slot"],
                provider=r["provider"],
                status=r["status"],
                config=self._json_load(r["config"]),
                deployed_at=r["deployed_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def update_slot(self, slot: str, **kwargs: Any) -> None:
        allowed = {"provider", "status", "config", "deployed_at"}
        updates = {}
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            updates[k] = self._json_dump(v) if k == "config" else v
        if not updates:
            return
        updates["updated_at"] = self._now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        self._c.execute(
            f"UPDATE infra_slots SET {cols} WHERE slot = ?",
            list(updates.values()) + [slot],
        )
        self._c.commit()


    # ── Tunnel providers (multi-provider slot) ────────────────────────────

    def get_tunnel_providers(self) -> list[dict[str, Any]]:
        """Return all tunnel provider records."""
        rows = self._c.execute(
            "SELECT * FROM infra_tunnel_providers ORDER BY deployed_at"
        ).fetchall()
        return [
            {
                "provider": r["provider"],
                "status": r["status"],
                "config": self._json_load(r["config"]),
                "deployed_at": r["deployed_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def get_tunnel_provider(self, provider: str) -> dict[str, Any] | None:
        row = self._c.execute(
            "SELECT * FROM infra_tunnel_providers WHERE provider = ?", (provider,)
        ).fetchone()
        if not row:
            return None
        return {
            "provider": row["provider"],
            "status": row["status"],
            "config": self._json_load(row["config"]),
            "deployed_at": row["deployed_at"],
        }

    def upsert_tunnel_provider(self, provider: str, **kwargs: Any) -> None:
        """Insert or update a tunnel provider record."""
        existing = self._c.execute(
            "SELECT id FROM infra_tunnel_providers WHERE provider = ?", (provider,)
        ).fetchone()
        now = self._now()
        if existing:
            allowed = {"status", "config", "deployed_at"}
            updates = {k: v for k, v in kwargs.items() if k in allowed}
            if not updates:
                return
            if "config" in updates:
                updates["config"] = self._json_dump(updates["config"])
            updates["updated_at"] = now
            cols = ", ".join(f"{k} = ?" for k in updates)
            self._c.execute(
                f"UPDATE infra_tunnel_providers SET {cols} WHERE provider = ?",
                list(updates.values()) + [provider],
            )
        else:
            config_val = self._json_dump(kwargs.get("config", {}))
            self._c.execute(
                """INSERT INTO infra_tunnel_providers
                   (provider, status, config, deployed_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    provider,
                    kwargs.get("status", "empty"),
                    config_val,
                    kwargs.get("deployed_at"),
                    now,
                ),
            )
        self._c.commit()

    def remove_tunnel_provider(self, provider: str) -> None:
        self._c.execute(
            "DELETE FROM infra_tunnel_providers WHERE provider = ?", (provider,)
        )
        self._c.commit()

    # ── Apps ──────────────────────────────────────────────────────────────

    def get_app(self, key: str) -> App | None:
        row = self._c.execute(
            "SELECT * FROM apps WHERE key = ?", (key,)
        ).fetchone()
        return self._row_to_app(row) if row else None

    def get_all_apps(
        self,
        status: str | None = None,
        include_system: bool = False,
    ) -> list[App]:
        """Return installed apps.

        By default (include_system=False) tier-0 system components such as the
        SLOP Agent are excluded so they don't appear in user-facing app lists or
        Docker status queries.  Pass include_system=True to include them.
        """
        conditions: list[str] = []
        params: list[object] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if not include_system:
            conditions.append("tier != 0")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = self._c.execute(
            "SELECT * FROM apps " + where + " ORDER BY display_name",
            params,
        ).fetchall()
        return [self._row_to_app(r) for r in rows]

    def _row_to_app(self, row: sqlite3.Row) -> App:
        return App(
            id=row["id"],
            key=row["key"],
            display_name=row["display_name"],
            tier=row["tier"],
            category=row["category"],
            status=row["status"],
            image=row["image"],
            image_tag=row["image_tag"],
            container_name=row["container_name"],
            web_port=row["web_port"],
            host_port=row["host_port"],
            config_path=row["config_path"],
            manifest_source=row["manifest_source"],
            extra_config=self._json_load(row["extra_config"]),
            installed_at=row["installed_at"],
            updated_at=row["updated_at"],
            last_healthy_at=row["last_healthy_at"],
        )

    def upsert_app(self, key: str, **kwargs: Any) -> int:
        """Insert or update an app record. Returns the app id."""
        existing = self.get_app(key)
        if existing:
            allowed = {
                "display_name", "status", "image", "image_tag", "container_name",
                "web_port", "host_port", "config_path", "manifest_source",
                "manifest_hash", "extra_config", "last_healthy_at",
            }
            updates = {}
            for k, v in kwargs.items():
                if k not in allowed:
                    continue
                updates[k] = self._json_dump(v) if k == "extra_config" else v
            if updates:
                updates["updated_at"] = self._now()
                cols = ", ".join(f"{k} = ?" for k in updates)
                self._c.execute(
                    f"UPDATE apps SET {cols} WHERE key = ?",
                    list(updates.values()) + [key],
                )
                self._c.commit()
            return existing.id
        else:
            now = self._now()
            extra = kwargs.get("extra_config")
            self._c.execute(
                """INSERT INTO apps
                   (key, display_name, tier, category, status, image, image_tag,
                    container_name, web_port, host_port, config_path,
                    manifest_source, manifest_hash, extra_config,
                    installed_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    kwargs.get("display_name", key),
                    kwargs.get("tier", 2),
                    kwargs.get("category", "tools"),
                    kwargs.get("status", "installing"),
                    kwargs.get("image", ""),
                    kwargs.get("image_tag", "latest"),
                    kwargs.get("container_name", key),
                    kwargs.get("web_port"),
                    kwargs.get("host_port"),
                    kwargs.get("config_path"),
                    kwargs.get("manifest_source", "catalog"),
                    kwargs.get("manifest_hash"),
                    self._json_dump(extra) if extra else None,
                    now, now,
                ),
            )
            self._c.commit()
            return int(self._c.execute(
                "SELECT id FROM apps WHERE key = ?", (key,)
            ).fetchone()["id"])

    def remove_app(self, key: str) -> None:
        """Remove an app and all its dependent records (full cascade).

        Cleans up: apps, health_checks, health_check_history, pending_fixes,
        wiring (by app_id), operations (by subject_key).
        """
        # Get app id for FK-based deletes before removing the row
        row = self._c.execute("SELECT id FROM apps WHERE key=?", (key,)).fetchone()
        app_id = row[0] if row else None

        self._c.execute("DELETE FROM apps WHERE key = ?", (key,))
        # Health records
        self._c.execute(
            "DELETE FROM health_checks WHERE subject_type = 'app' AND subject_key = ?",
            (key,),
        )
        self._c.execute(
            "DELETE FROM health_check_history WHERE subject_type = 'app' AND subject_key = ?",
            (key,),
        )
        # Pending AI fixes for this app
        try:
            self._c.execute("DELETE FROM pending_fixes WHERE app_key = ?", (key,))
        except Exception:
            pass  # table may not exist on older installs
        # Wiring rows (both source and target)
        if app_id:
            self._c.execute(
                "DELETE FROM wiring WHERE source_app_id = ? OR target_app_id = ?",
                (app_id, app_id),
            )
        # Operation history (keep for audit — just mark subject as removed)
        # We do NOT delete operations — they are the audit trail
        self._c.commit()

    # ── Operations log ────────────────────────────────────────────────────

    def log_operation(
        self,
        operation: str,
        subject_type: str,
        subject_key: str,
        triggered_by: str = "user",
        detail: dict[str, Any] | None = None,
    ) -> int:
        """Start an operation log entry. Returns the operation id."""
        cur = self._c.execute(
            """INSERT INTO operations
               (operation, subject_type, subject_key, status, triggered_by, detail, started_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                operation, subject_type, subject_key,
                "started", triggered_by,
                self._json_dump(detail),
                self._now(),
            ),
        )
        self._c.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def complete_operation(
        self,
        op_id: int,
        status: str = "completed",
        error: str | None = None,
    ) -> None:
        self._c.execute(
            "UPDATE operations SET status = ?, error = ?, completed_at = ? WHERE id = ?",
            (status, error, self._now(), op_id),
        )
        self._c.commit()

    def get_recent_operations(self, limit: int = 50) -> list[Operation]:
        rows = self._c.execute(
            "SELECT * FROM operations ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            Operation(
                id=r["id"],
                operation=r["operation"],
                subject_type=r["subject_type"],
                subject_key=r["subject_key"],
                status=r["status"],
                triggered_by=r["triggered_by"],
                detail=self._json_load(r["detail"]) or None,
                error=r["error"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
            )
            for r in rows
        ]

    # ── Health checks ─────────────────────────────────────────────────────

    def upsert_health_check(
        self,
        subject_type: str,
        subject_key: str,
        check_name: str,
        status: str,
        summary: str,
        detail: str | None = None,
        auto_fix: str | None = None,
    ) -> None:
        self._c.execute(
            """INSERT INTO health_checks
               (subject_type, subject_key, check_name, status, summary, detail, auto_fix, checked_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT (subject_type, subject_key, check_name)
               DO UPDATE SET
                   status = excluded.status,
                   summary = excluded.summary,
                   detail = excluded.detail,
                   auto_fix = excluded.auto_fix,
                   checked_at = excluded.checked_at""",
            (subject_type, subject_key, check_name, status, summary, detail, auto_fix, self._now()),
        )
        self._c.commit()

    def get_health_checks(
        self, subject_type: str | None = None, subject_key: str | None = None
    ) -> list[HealthCheck]:
        if subject_type and subject_key:
            rows = self._c.execute(
                "SELECT * FROM health_checks WHERE subject_type = ? AND subject_key = ?",
                (subject_type, subject_key),
            ).fetchall()
        elif subject_type:
            rows = self._c.execute(
                "SELECT * FROM health_checks WHERE subject_type = ?", (subject_type,)
            ).fetchall()
        else:
            rows = self._c.execute("SELECT * FROM health_checks").fetchall()
        return [
            HealthCheck(
                subject_type=r["subject_type"],
                subject_key=r["subject_key"],
                check_name=r["check_name"],
                status=r["status"],
                summary=r["summary"],
                detail=r["detail"],
                auto_fix=r["auto_fix"],
                checked_at=r["checked_at"],
            )
            for r in rows
        ]

    # ── Settings ──────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._c.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


    def write_op_step(
        self,
        op_key: str,
        step_name: str,
        status: str,
        message: str,
        detail: str = "",
    ) -> None:
        """Persist a single operation step for real-time progress polling."""
        self._c.execute(
            """INSERT INTO operation_steps (op_key, step_name, status, message, detail)
               VALUES (?, ?, ?, ?, ?)""",
            (op_key, step_name, status, message, detail),
        )
        self._c.commit()

    def get_op_steps(self, op_key: str) -> list[dict[str, Any]]:
        """Return all steps for an operation, oldest first."""
        rows = self._c.execute(
            """SELECT step_name, status, message, detail, created_at
               FROM operation_steps WHERE op_key=? ORDER BY id""",
            (op_key,),
        ).fetchall()
        return [
            {
                "step": r["step_name"],
                "status": r["status"],
                "message": r["message"],
                "detail": r["detail"] or "",
                "ts": r["created_at"],
            }
            for r in rows
        ]

    def clear_op_steps(self, op_key: str) -> None:
        """Remove all step records for a key (called at start of new install)."""
        self._c.execute("DELETE FROM operation_steps WHERE op_key=?", (op_key,))
        self._c.commit()

    def set_setting(self, key: str, value: str) -> None:
        self._c.execute(
            """INSERT INTO settings (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, value, self._now()),
        )
        self._c.commit()

    def get_all_settings(self) -> dict[str, str]:
        rows = self._c.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── Secrets ───────────────────────────────────────────────────────────

    def get_secrets(self) -> list[dict[str, Any]]:
        """Return secret metadata (never values)."""
        rows = self._c.execute("SELECT * FROM secrets ORDER BY service, key").fetchall()
        return [dict(r) for r in rows]

    def mark_secret_set(self, key: str, is_set: bool = True) -> None:
        self._c.execute(
            """INSERT INTO secrets (key, is_set, updated_at) VALUES (?,?,?)
               ON CONFLICT (key) DO UPDATE SET is_set = excluded.is_set, updated_at = excluded.updated_at""",
            (key, 1 if is_set else 0, self._now()),
        )
        self._c.commit()

    # ── External resources ────────────────────────────────────────────────

    def record_external_resource(
        self,
        resource_type: str,
        hostname: str,
        target: str,
        app_id: int | None = None,
        resource_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> int:
        cur = self._c.execute(
            """INSERT INTO external_resources
               (app_id, resource_type, resource_id, hostname, target, config, provisioned_at)
               VALUES (?,?,?,?,?,?,?)""",
            (app_id, resource_type, resource_id, hostname, target,
             self._json_dump(config), self._now()),
        )
        self._c.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def mark_resource_removed(self, resource_id_or_hostname: str) -> None:
        self._c.execute(
            """UPDATE external_resources SET removed_at = ?
               WHERE (resource_id = ? OR hostname = ?) AND removed_at IS NULL""",
            (self._now(), resource_id_or_hostname, resource_id_or_hostname),
        )
        self._c.commit()

    def get_active_resources(self, app_id: int | None = None) -> list[dict[str, Any]]:
        if app_id:
            rows = self._c.execute(
                "SELECT * FROM external_resources WHERE app_id = ? AND removed_at IS NULL",
                (app_id,),
            ).fetchall()
        else:
            rows = self._c.execute(
                "SELECT * FROM external_resources WHERE removed_at IS NULL"
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Module-level initializer
# ---------------------------------------------------------------------------


def init_db(db_path: Path) -> None:
    """Initialise the database and run all pending migrations.

    Safe to call on every startup — the migration runner is idempotent.
    Also calls configure(db_path) to set the global DB path.

    Schema upgrade gate: run_migrations() applies all pending numbered files
    under migrations/ in order, taking a hot-copy backup beforehand.
    Existing v3 DBs (no schema_migrations table) are auto-stamped at baseline.

    If migrations fail this function raises and lifespan startup aborts —
    FastAPI never serves a request. Core Rule 1.5 (Fail Loud, Fail Fast).
    Restore the pre-migration backup named in the error before retrying.
    See: docs/cleanup/01_migrations_design.md, docs/adr/0001-database-migrations.md
    """
    from backend.core.migrations import run_migrations  # avoid circular import at module level

    configure(db_path)
    result = run_migrations(db_path)
    log.info(
        "State database ready: %s (migrations applied: %s)",
        db_path,
        result.applied or "none",
    )
    # Step 4.2 — flip the /startupz flag now that migrations are done.
    # The flag lives here (state.py owns startup state) — `probes.py`
    # reads it via `_state_mod._STARTUP_COMPLETE` to avoid the
    # `backend.core.state -> backend.api.*` import that would create
    # a circular-dependency risk.
    global _STARTUP_COMPLETE
    _STARTUP_COMPLETE = True
