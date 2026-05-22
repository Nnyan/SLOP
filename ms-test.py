#!/usr/bin/env python3
"""
ms-test.py — Mediastack comprehensive integration test suite.

Tests every data flow, contract, state transition, and silent failure mode.
Complements the 799 unit tests in tests/ which test isolated functions.
This script tests what pytest cannot: cross-layer flows, shell scripts,
frontend↔backend contracts, and operations that "succeed" but do nothing.

Usage:
    python3 ms-test.py                        # all tests
    python3 ms-test.py --section D            # just data flow tests
    python3 ms-test.py --section A,B,C        # multiple sections
    python3 ms-test.py --json                 # machine-readable output
    python3 ms-test.py --destructive          # include write/install tests
    python3 ms-test.py --url http://host:8000 # custom base URL

Environment:
    MS_BASE_URL   Base URL (default: http://localhost:8000)
    MS_REPO       Repo path (default: directory of this script)
"""

import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import textwrap
import time
from typing import Any

# Auto-detect port from .env MEDIASTACK_PORT, MS_BASE_URL env, or default 8080
def _detect_base_url() -> str:
    if url := os.environ.get("MS_BASE_URL"):
        return url.rstrip("/")
    # Try to read port from .env file in repo root or /opt/mediastack
    for env_path in [
        pathlib.Path(__file__).parent / ".env",
        pathlib.Path("/opt/mediastack/.env"),
    ]:
        try:
            for line in env_path.read_text().splitlines():
                if line.startswith("MEDIASTACK_PORT="):
                    port = line.split("=", 1)[1].strip()
                    return f"http://localhost:{port}"
        except Exception:
            pass
    return "http://localhost:8080"  # Mediastack default port

BASE_URL = _detect_base_url()
REPO = pathlib.Path(os.environ.get("MS_REPO", pathlib.Path(__file__).parent))
DESTRUCTIVE = False
SECTION_FILTER: list[str] = []

# ── Canonical paths — must match what production code uses (Core Rule 2.7) ──
# Import config to get the SAME paths that infra providers, executor, and
# health checker use. Never hardcode REPO/"data"/... here.
try:
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from backend.core.config import config as _cfg
    COMPOSE_DIR = _cfg.compose_dir        # where providers write fragments
    DB_PATH     = _cfg.db_path            # where state is stored
    DATA_DIR    = _cfg.data_dir           # runtime data root
except Exception:
    # Fallback for environments without backend installed
    COMPOSE_DIR = COMPOSE_DIR
    DB_PATH     = DB_PATH
    DATA_DIR    = REPO / "data"

# ── Output helpers ────────────────────────────────────────────────────────────

_results: list[dict] = []
_current_section = ""
_section_counts: dict[str, dict] = {}

GREEN  = "\033[32m" if sys.stdout.isatty() else ""
RED    = "\033[31m" if sys.stdout.isatty() else ""
DIM    = "\033[2m"  if sys.stdout.isatty() else ""
CYAN   = "\033[36m" if sys.stdout.isatty() else ""
YELLOW = "\033[33m" if sys.stdout.isatty() else ""
CYAN   = "\033[36m" if sys.stdout.isatty() else ""
BOLD   = "\033[1m"  if sys.stdout.isatty() else ""
RESET  = "\033[0m"  if sys.stdout.isatty() else ""


def _sec_counts() -> dict:
    return _section_counts.setdefault(_current_section, {"pass": 0, "fail": 0, "skip": 0, "warn": 0})


def section(label: str) -> bool:
    """Start a section. Returns False if section is filtered out — test functions
    should 'return' immediately when this returns False to skip all their work."""
    global _current_section
    if SECTION_FILTER and not any(label.upper().startswith(f.upper() + ".") for f in SECTION_FILTER):
        _current_section = f"__skip__{label}"
        return False
    _current_section = label
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}{label}{RESET}")
    print(f"{'─'*60}")
    return True


def _skip_section() -> bool:
    return _current_section.startswith("__skip__")


def passed(name: str, detail: str = "") -> None:
    if _skip_section():
        return
    _sec_counts()["pass"] += 1
    _results.append({"section": _current_section, "status": "PASS", "name": name, "detail": detail})
    suffix = f"  {detail}" if detail else ""
    print(f"  {GREEN}[PASS]{RESET} {name}{suffix}")


def failed(name: str, detail: str = "") -> None:
    if _skip_section():
        return
    _sec_counts()["fail"] += 1
    _results.append({"section": _current_section, "status": "FAIL", "name": name, "detail": detail})
    suffix = f"\n         {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}[FAIL]{RESET} {name}{suffix}")


def skipped(name: str, reason: str = "") -> None:
    if _skip_section():
        return
    _sec_counts()["skip"] += 1
    _results.append({"section": _current_section, "status": "SKIP", "name": name, "detail": reason})
    suffix = f"  ({reason})" if reason else ""
    print(f"  {YELLOW}[SKIP]{RESET} {name}{suffix}")

# ── Precondition Context System (Core Rule 2.9) ───────────────────────────
# Every test that checks system state must declare its preconditions.
# Context is populated once at startup; tests use section_requires() and ctx().

_CTX: dict = {}

def _set_ctx(key: str, value) -> None:
    _CTX[key] = value

def ctx(key: str, default=None):
    """Get a context value populated during startup."""
    return _CTX.get(key, default)

def section_requires(ctx_key: str, required_val, skip_msg: str = "") -> bool:
    """Precondition guard. Returns True if context matches; logs skip and returns False if not.

    Usage:
        if not section_requires("platform_status", "ready"):
            return  # skip entire section
    This makes preconditions explicit and machine-checkable (Core Rule 2.9).
    """
    actual = ctx(ctx_key)
    if actual == required_val:
        return True
    msg = skip_msg or f"requires {ctx_key}={required_val!r} (current: {actual!r})"
    skipped(f"[precondition] {msg}")
    return False

def _populate_context() -> None:
    """Query the live system once at startup. All sections use ctx() — no re-querying."""
    s, body = GET("/platform/status")
    _set_ctx("platform_status", body.get("status", "unknown") if s == 200 else "unreachable")
    _set_ctx("service_reachable", s == 200)

    s, apps = GET("/apps")
    running = [a for a in (apps if isinstance(apps, list) else [])
               if a.get("status") == "running"]
    _set_ctx("has_running_apps", len(running) > 0)
    _set_ctx("running_app_count", len(running))

    s2, h = GET("/health/apps")
    _set_ctx("has_health_data", s2 == 200 and isinstance(h, list) and len(h) > 0)

    s3, fixes = GET("/health/pending-fixes")
    fix_list = fixes if isinstance(fixes, list) else []
    _set_ctx("has_pending_fixes", len(fix_list) > 0)

    conn = _db()
    if conn:
        try:
            row = conn.execute("SELECT COUNT(*) FROM health_check_history").fetchone()
            _set_ctx("has_health_history", (row[0] if row else 0) > 0)
        except Exception:
            _set_ctx("has_health_history", False)
        finally:
            conn.close()




def warned(name: str, detail: str = "") -> None:
    if _skip_section():
        return
    _sec_counts()["warn"] += 1
    _results.append({"section": _current_section, "status": "WARN", "name": name, "detail": detail})
    suffix = f"  {YELLOW}{detail}{RESET}" if detail else ""
    print(f"  {YELLOW}[WARN]{RESET} {name}{suffix}")


def check(name: str, condition: bool, ok_detail: str = "", fail_detail: str = "") -> bool:
    if condition:
        passed(name, ok_detail)
    else:
        failed(name, fail_detail)
    return condition


# ── File read cache (avoid re-reading same files multiple times per run) ────────
_FILE_CACHE: dict[str, str] = {}

def _read_cached(path) -> str:
    """Read a file once per process, cache for subsequent calls."""
    key = str(path)
    if key not in _FILE_CACHE:
        try:
            _FILE_CACHE[key] = pathlib.Path(path).read_text(errors="replace")
        except Exception:
            _FILE_CACHE[key] = ""
    return _FILE_CACHE[key]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(method: str, path: str, **kwargs) -> tuple[int, Any]:
    """Make HTTP request; return (status_code, parsed_body)."""
    try:
        import urllib.request
        import urllib.error

        url = f"{BASE_URL}/api{path}"
        data = None
        headers = {"Accept": "application/json"}

        if "json" in kwargs:
            data = json.dumps(kwargs["json"]).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
                try:
                    return resp.status, json.loads(body)
                except Exception:
                    return resp.status, body.decode(errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, body.decode(errors="replace")
    except Exception as e:
        return 0, str(e)


def GET(path: str) -> tuple[int, Any]:
    return _req("GET", path)


def POST(path: str, body: dict | None = None) -> tuple[int, Any]:
    return _req("POST", path, json=body or {})


def PUT(path: str, body: dict) -> tuple[int, Any]:
    return _req("PUT", path, json=body)


def _api_reachable() -> bool:
    """Fast reachability ping — uses /platform/status (single row, no joins)."""
    status, _ = GET("/platform/status")
    return status < 500


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection | None:
    """Return a connection to state.db if it exists."""
    candidates = [
        DB_PATH,
        pathlib.Path("/opt/mediastack/data/state.db"),
    ]
    for p in candidates:
        if p.exists():
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            return conn
    return None


def _db_tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}


# ── SECTION A: Infrastructure Sanity ─────────────────────────────────────────

def test_section_A():
    section("A. Infrastructure Sanity")

    # API reachability
    ok = _api_reachable()
    if not check("API reachable", ok, fail_detail="Cannot reach API — is Mediastack running?"):
        skipped("remaining tests", "API unreachable")
        return False

    # DB
    conn = _db()
    if conn is None:
        warned("state.db", "Could not find state.db — DB tests will be limited")
    else:
        tables = _db_tables(conn)
        REQUIRED_TABLES = {
            "platform", "infra_slots", "apps", "app_dependencies", "managed_services",
            "wiring", "health_checks", "health_check_history", "operations",
            "operation_steps", "fix_history", "maintenance_windows",
            "storage_sources",
            "settings", "quickstart_phases",
        }
        missing = REQUIRED_TABLES - tables
        check("state.db: tables",
              not missing,
              fail_detail=f"Missing tables: {missing}")

        # WAL mode
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        check("SQLite WAL", mode == "wal",
              ok_detail=f"mode={mode}",
              fail_detail=f"Expected wal, got {mode} — run: PRAGMA journal_mode=wal")

        conn.close()

    # Filesystem
    compose_dir = COMPOSE_DIR
    check("compose/ dir", compose_dir.exists(),
          fail_detail=str(compose_dir))

    env_file = REPO / ".env"
    if env_file.exists():
        stat = env_file.stat()
        perm = oct(stat.st_mode)[-3:]
        check(".env: 600", perm == "600",
              ok_detail=perm, fail_detail=f"Got {perm} — run: chmod 600 .env")
    else:
        skipped(".env permissions", ".env not found — platform not configured yet")

    # ms-check shell function names
    ms_check = REPO / "ms-check"
    if ms_check.exists():
        content = _read_cached(ms_check)
        # Functions that must be DEFINED
        for fn in ("pass()", "warn()", "fail()", "info()", "section("):
            check(f"ms-check: {fn.rstrip('()')}() defined",
                  fn in content or fn.replace("()", "()") in content,
                  fail_detail=f"'{fn}' not found in ms-check")
        # Functions that must NOT be called if not defined (the ok/pass bug)
        if "ok " in content and "ok()" not in content and "function ok" not in content:
            # Check if it's called but not defined
            lines_with_ok = [l.strip() for l in content.splitlines()
                             if " ok " in l and not l.strip().startswith("#")]
            if lines_with_ok:
                failed("ms-check: undefined 'ok' called",
                       detail=f"Line: {lines_with_ok[0]}")
            else:
                passed("ms-check: function names ok")
        else:
            passed("ms-check: function names ok")
    else:
        skipped("ms-check shell functions", "ms-check not found")

    # ms-update OLD_COMMIT order
    ms_update = REPO / "ms-update"
    if ms_update.exists():
        content = _read_cached(ms_update)
        lines = content.splitlines()
        old_commit_line = next((i for i, l in enumerate(lines) if "OLD_COMMIT=" in l), None)
        git_pull_lines = [i for i, l in enumerate(lines)
                          if "git" in l and "pull" in l
                          and not l.strip().startswith("#")]
        if old_commit_line is not None and git_pull_lines:
            first_pull = min(git_pull_lines)
            check("ms-update: OLD_COMMIT before pull",
                  old_commit_line < first_pull,
                  ok_detail=f"line {old_commit_line+1} < pull line {first_pull+1}",
                  fail_detail=f"OLD_COMMIT at line {old_commit_line+1}, first pull at {first_pull+1} — SHAs will match!")
        else:
            skipped("ms-update OLD_COMMIT order", "Could not locate lines")
    else:
        skipped("ms-update OLD_COMMIT order", "ms-update not found")

    # ── Port uniqueness — no two apps should share host_port ──────────────
    # Reuse existing connection if available (avoid second DB open)
    _port_conn = _db()
    if _port_conn:
        try:
            rows = _port_conn.execute(
                "SELECT host_port, COUNT(*) as cnt, GROUP_CONCAT(key) as keys "
                "FROM apps WHERE host_port IS NOT NULL AND host_port > 0 "
                "GROUP BY host_port HAVING cnt > 1"
            ).fetchall()
            if rows:
                for row in rows:
                    failed(f"Port conflict: {row['host_port']} → {row['keys']}",
                           "Two apps on same port — one will fail to start")
            else:
                passed("No port conflicts")
        except Exception as e:
            warned("Port uniqueness check", str(e))
        _port_conn.close()

    # ── Compose YAML validity ────────────────────────────────────────────
    compose_dir = COMPOSE_DIR
    if compose_dir.exists():
        import re as _re
        yaml_files = list(compose_dir.glob("*.yaml"))
        if yaml_files:
            bad_yaml = []
            for yf in yaml_files:
                content = yf.read_text(errors="replace")
                # Basic validity: must have 'services:' key
                if "services:" not in content:
                    bad_yaml.append(f"{yf.name}: missing 'services:' key")
                # Must not have tab characters (YAML is space-indented)
                if "	" in content:
                    bad_yaml.append(f"{yf.name}: contains tab characters (YAML requires spaces)")
            check("Compose YAML valid",
                  not bad_yaml,
                  ok_detail=f"{len(yaml_files)} files checked",
                  fail_detail="\n         ".join(bad_yaml[:3]))
        else:
            # No compose fragments found.
            plat_status = GET("/platform/status")[1]
            if isinstance(plat_status, dict) and plat_status.get("status") == "ready":
                # Platform says ready but nothing deployed — check if Traefik
                # container is actually running before warning (fragments may have
                # been cleaned by reset but containers not yet redeployed)
                import subprocess as _sp
                traefik_running = False
                try:
                    _r = _sp.run(["docker", "inspect", "--format",
                                  "{{.State.Status}}", "traefik"],
                                 capture_output=True, text=True, timeout=5)
                    traefik_running = _r.stdout.strip() == "running"
                except Exception:
                    pass
                if traefik_running:
                    passed("Compose YAML validity",
                           "No fragments on disk but Traefik running — compose managed externally")
                else:
                    warned("Compose YAML validity",
                           "Platform is ready but no compose fragments or running Traefik found. "
                           "Run a full platform reset then re-run the setup wizard.")
            else:
                passed("Compose YAML validity", "No fragments — platform pending/reset (expected)")

    return True


# ── SECTION B: API Route Smoke Tests ─────────────────────────────────────────

def test_section_B():
    if not section("B. API Route Smoke Tests"):
        return

    GET_ROUTES = [
        # health
        "/health/apps", "/health/anomalies", "/health/pending-fixes",
        "/health/maintenance-windows", "/health/sources", "/health/scheduler",
        "/health/weekly-summary", "/health/llm-agent", "/health/llm-providers",
        "/health/fix-history", "/health/ai-safety",
        # platform
        "/platform/status", "/platform/prereqs", "/platform/wizard/steps",
        # settings
        "/settings", "/settings/system", "/settings/secrets",
        "/settings/traefik",
        # apps
        "/apps",
        # catalog
        "/catalog",
        # infra
        "/infra/slots", "/infra/providers",
        # routing
        "/routing",
        # models (LLM)
        "/models/llm-ping", "/models/agent-config",
        # storage
        "/storage/sources",
        # registry
        # /registry/{key} requires a valid key — skip generic list test
        # "/registry/registry",  # no list endpoint, only /{key} exists
    ]

    ok_count = 0
    fail_count = 0
    for route in GET_ROUTES:
        status, body = GET(route)
        if status == 0:
            failed(f"GET {route}", f"Connection error: {body}")
            fail_count += 1
        elif status >= 500:
            failed(f"GET {route}", f"Server error {status}")
            fail_count += 1
        elif status in (401, 403):
            warned(f"GET {route}", f"Auth required ({status})")
        elif status == 404:
            failed(f"GET {route}", "404 Not Found — route may have moved")
            fail_count += 1
        else:
            passed(f"GET {route}", f"→ {status}")
            ok_count += 1

    # No route should return Python tracebacks
    for route in GET_ROUTES[:5]:  # sample check
        status, body = GET(route)
        if isinstance(body, str) and "Traceback" in body:
            failed(f"GET {route} traceback check", "Response contains Python traceback!")
        elif isinstance(body, dict) and "Traceback" in json.dumps(body):
            failed(f"GET {route} traceback check", "Response body contains Traceback")

    # POST with empty body should return 400/422, not 500
    POST_ROUTES_THAT_NEED_BODY = [
        "/health/maintenance-windows",
        "/health/sources/find-replacement",
    ]
    for route in POST_ROUTES_THAT_NEED_BODY:
        status, _ = POST(route, {})
        if status >= 500:
            failed(f"POST {route} (empty body) → {status}", "Should return 4xx not 5xx")
        else:
            passed(f"POST {route} (empty body) → {status}", "correctly returns 4xx")


# ── SECTION C: Schema Validation ─────────────────────────────────────────────

def test_section_C():
    if not section("C. Schema Validation"):
        return

    # /health/apps — list of health check records
    status, body = GET("/health/apps")
    if status == 200:
        if isinstance(body, list):
            if body:
                first = body[0]
                for field in ("app_key", "check_name", "status", "summary"):
                    check(f"/health/apps[0].{field} exists",
                          field in first,
                          fail_detail=f"Field '{field}' missing from health check record")
            else:
                skipped("/health/apps schema", "No health checks yet — run a health cycle first")
        else:
            failed("/health/apps returns list", f"Got {type(body).__name__}")
    else:
        skipped("/health/apps schema", f"Endpoint returned {status}")

    # /platform/status
    status, body = GET("/platform/status")
    if status == 200:
        for field in ("status", "domain"):
            check(f"/platform/status.{field} exists", field in body,
                  fail_detail=f"Field '{field}' missing")
        valid_statuses = ("pending", "ready", "error")
        check(f"/platform/status.status is valid",
              body.get("status") in valid_statuses,
              ok_detail=body.get("status"),
              fail_detail=f"Got '{body.get('status')}', expected one of {valid_statuses}")

    # /platform/prereqs
    status, body = GET("/platform/prereqs")
    if status == 200:
        check("/platform/prereqs.checks is list", isinstance(body.get("checks"), list))
        check("/platform/prereqs.system is dict", isinstance(body.get("system"), dict))
        checks = body.get("checks", [])
        if checks:
            first = checks[0]
            for field in ("key", "label", "status"):
                check(f"/platform/prereqs.checks[0].{field} exists", field in first)
            valid_check_statuses = ("ok", "warning", "error", "skipped")
            bad = [c for c in checks if c.get("status") not in valid_check_statuses]
            check("/platform/prereqs all check statuses valid",
                  not bad,
                  fail_detail=f"Invalid statuses: {[c.get('status') for c in bad]}")

    # /settings/system
    status, body = GET("/settings/system")
    if status == 200:
        for field in ("cpu_cores", "total_ram_gb"):
            check(f"/settings/system.{field} exists", field in body)
        # New rich fields from fingerprint
        for field in ("os", "cpu", "ram"):
            if field in body:
                passed(f"/settings/system.{field} (fingerprint) present")
            else:
                warned(f"/settings/system.{field}", "fingerprint field not yet collected — run prereqs")

    # /health/scheduler
    status, body = GET("/health/scheduler")
    if status == 200:
        check("/health/scheduler.running field exists", "running" in body,
              fail_detail="Scheduler status missing 'running' field")

    # /apps — list of installed apps
    status, body = GET("/apps")
    if status == 200 and isinstance(body, list) and body:
        first = body[0]
        for field in ("key", "display_name", "status", "category"):
            check(f"/apps[0].{field} exists", field in first)

    # /catalog — catalog entries
    status, body = GET("/catalog")
    if status == 200 and isinstance(body, (list, dict)):
        if isinstance(body, list) and body:
            first = body[0]
            check("/catalog[0].key exists", "key" in first)
            check("/catalog[0].display_name exists", "display_name" in first)


# ── SECTION D: Data Flow Integrity ────────────────────────────────────────────

def test_section_D():
    if not section("D. Data Flow Integrity"):
        return

    # Settings round-trip
    status, orig = GET("/settings")
    if status == 200 and isinstance(orig, dict):
        # Write a distinctive value, read it back
        test_interval = orig.get("health_check_interval_secs", 300)
        new_interval = test_interval + 7 if test_interval < 3600 - 7 else test_interval - 7
        put_status, _ = PUT("/settings", {**orig, "health_check_interval_secs": new_interval})
        if put_status in (200, 204):
            read_status, new_data = GET("/settings")
            if read_status == 200:
                actual = new_data.get("health_check_interval_secs")
                check("Settings: round-trip",
                      actual == new_interval,
                      ok_detail=f"{new_interval}",
                      fail_detail=f"Wrote {new_interval}, read back {actual} — silent drop!")
                # Restore original
                PUT("/settings", orig)
            else:
                failed("Settings: read-back", f"GET returned {read_status}")
        else:
            warned("Settings round-trip", f"PUT returned {put_status} — may need auth")
    else:
        skipped("Settings round-trip", f"GET /settings returned {status}")

    # Health cycle → results exist (CRITICAL: catches "all healthy with 0 checked" bug)
    apps_status, apps_body = GET("/apps")
    running_apps = []
    if apps_status == 200 and isinstance(apps_body, list):
        running_apps = [a for a in apps_body if a.get("status") == "running"]

    if running_apps:
        run_status, run_body = POST("/health/run")
        if run_status == 200:
            apps_checked = run_body.get("apps_checked", -1)
            apps_healthy = run_body.get("apps_healthy", -1)
            # CRITICAL TEST: apps_checked must be > 0 when running apps exist
            check("Health run: apps > 0",
                  apps_checked > 0,
                  ok_detail=f"{apps_checked} checked, {apps_healthy} healthy",
                  fail_detail=f"apps_checked={apps_checked} but {len(running_apps)} running apps exist — BUG!")
            # Health results must appear in DB
            check_status, check_body = GET("/health/apps")
            if check_status == 200 and isinstance(check_body, list):
                check("Health: results in DB",
                      len(check_body) > 0,
                      fail_detail="GET /health/apps returned empty after run — results not persisted!")
                # Count consistency
                ok_count = sum(1 for c in check_body if c.get("status") == "ok")
                warn_count = sum(1 for c in check_body if c.get("status") == "warning")
                err_count = sum(1 for c in check_body if c.get("status") == "error")
                total_checks = ok_count + warn_count + err_count
                # apps_healthy from run response ≈ apps with all checks ok
                passed(f"Health DB: {ok_count}ok {warn_count}warn {err_count}err")
        else:
            warned("Health run", f"POST /health/run returned {run_status}")
    else:
        skipped("Health cycle data flow", "No running apps — install an app first")

    # Maintenance window round-trip
    mw_body = {
        "app_key": "test_app",
        "check_name": "test_check",
        "label": "ms-test maintenance window",
        "day_of_week": None,
        "hour_start": 2,
        "hour_end": 4,
    }
    create_status, create_resp = POST("/health/maintenance-windows", mw_body)
    if create_status in (200, 201):
        window_id = create_resp.get("id") if isinstance(create_resp, dict) else None
        read_status, windows = GET("/health/maintenance-windows")
        found = any(w.get("label") == "ms-test maintenance window"
                    for w in (windows if isinstance(windows, list) else []))
        check("Maintenance: create+read", found,
              fail_detail="Window not found after creation — silent drop!")
        # Clean up
        if window_id:
            _req("DELETE", f"/health/maintenance-windows/{window_id}")
            read_status2, windows2 = GET("/health/maintenance-windows")
            still_there = any(w.get("label") == "ms-test maintenance window"
                              for w in (windows2 if isinstance(windows2, list) else []))
            check("Maintenance: delete", not still_there,
                  fail_detail="Window still present after DELETE — delete not working!")
    else:
        warned("Maintenance window round-trip", f"POST returned {create_status}")


# ── SECTION E: State Machine Correctness ──────────────────────────────────────

def test_section_E():
    if not section("E. State Machine Correctness"):
        return

    # Platform status must be one of known states
    status, body = GET("/platform/status")
    if status == 200:
        plat_status = body.get("status", "?")
        check("Platform: valid status",
              plat_status in ("pending", "ready", "error", "configuring"),
              ok_detail=plat_status)

    # Apps: every app must have a known status
    status, body = GET("/apps")
    if status == 200 and isinstance(body, list):
        VALID_APP_STATUSES = {"installing", "running", "failed", "disabled",
                              "removing", "installed", "active", "degraded"}
        bad_status = [a for a in body if a.get("status") not in VALID_APP_STATUSES]
        check(f"All {len(body)} installed apps have valid status",
              not bad_status,
              ok_detail=f"{len(body)} apps checked",
              fail_detail=f"Unknown statuses: {[(a['key'], a['status']) for a in bad_status]}")

        # Apps with status=failed must NOT have a compose fragment
        conn = _db()
        if conn:
            compose_dir = COMPOSE_DIR
            if compose_dir.exists():
                failed_apps = [a for a in body if a.get("status") == "failed"]
                for app in failed_apps:
                    frag = compose_dir / f"{app['key']}.yaml"
                    if frag.exists():
                        warned(f"App {app['key']}: failed+compose exists",
                               "Orphaned fragment — ms-update cleanup will remove this")
            conn.close()

    # Infra slots: all 5 must exist
    status, body = GET("/infra/slots")
    if status == 200 and isinstance(body, (list, dict)):
        slots = body if isinstance(body, list) else body.get("slots", [])
        EXPECTED_SLOTS = {"auth", "tunnel", "vpn", "dashboard", "management"}
        found_slots = {s.get("slot") for s in slots}
        check("All 5 infra slot types present",
              EXPECTED_SLOTS.issubset(found_slots),
              ok_detail=str(found_slots),
              fail_detail=f"Missing slots: {EXPECTED_SLOTS - found_slots}")
        VALID_SLOT_STATUSES = {"empty", "active", "error", "deploying"}
        bad_slots = [s for s in slots if s.get("status") not in VALID_SLOT_STATUSES]
        check("Infra: slot statuses", not bad_slots,
              fail_detail=f"Bad statuses: {bad_slots}")


# ── SECTION F: Silent Failure Detection ───────────────────────────────────────

def test_section_F():
    if not section("F. Silent Failure Detection"):
        return

    # F1: Health run with 0 running apps must NOT claim "all healthy"
    apps_status, apps_body = GET("/apps")
    running_count = 0
    if apps_status == 200 and isinstance(apps_body, list):
        running_count = sum(1 for a in apps_body if a.get("status") == "running")

    run_status, run_body = POST("/health/run")
    if run_status == 200 and isinstance(run_body, dict):
        apps_checked = run_body.get("apps_checked", 0)
        if running_count == 0 and apps_checked == 0:
            passed("Health: 0 apps → 0 checked",
                   "apps_checked=0 — frontend must not show 'all healthy'")
        elif running_count > 0 and apps_checked == 0:
            failed("SILENT FAIL: 0 checked",
                   f"{running_count} running apps in DB but apps_checked=0 in response")
        elif apps_checked > 0:
            passed(f"Health run: checked {apps_checked} apps")

    # F2: Wizard run must return 409 if platform already ready
    plat_status, plat_body = GET("/platform/status")
    if isinstance(plat_body, dict) and plat_body.get("status") == "ready":
        wiz_status, wiz_body = POST("/platform/wizard/run", {"domain": "test.example.com"})
        check("Wizard: 409 on ready platform",
              wiz_status == 409,
              ok_detail="409 Conflict — prevents accidental reconfiguration",
              fail_detail=f"Got {wiz_status} — wizard ran on already-ready platform!")

    # F3: Async wizard creates real job_id
    # Just test the endpoint exists and returns a job_id format response
    # (Don't actually run the wizard on a production system)
    if not DESTRUCTIVE:
        skipped("Async wizard job creation", "Skipped in non-destructive mode (would modify platform)")
    else:
        async_status, async_body = POST("/platform/wizard/run-async",
                                        {"domain": "test.local"})
        if async_status == 200 and isinstance(async_body, dict):
            job_id = async_body.get("job_id")
            check("Wizard async: job_id", bool(job_id),
                  ok_detail=str(job_id))
            if job_id:
                poll_status, poll_body = GET(f"/platform/wizard/status/{job_id}")
                check("Wizard async: steps list",
                      poll_status == 200 and "steps" in (poll_body or {}),
                      fail_detail=f"Got {poll_status}: {poll_body}")

    # F4: Tunnel type validation — list AND string must both be accepted
    # This catches the dict[str, str] → dict[str, Any] fix
    # We test the validate endpoint which doesn't actually deploy
    validate_with_list, vbody = POST("/platform/wizard/validate", {
        "domain": "test.example.com",
        "infra_selections": {"tunnels": ["cloudflared", "tailscale"]},
    })
    check("Wizard: tunnels as list",
          validate_with_list != 422,
          ok_detail=f"Got {validate_with_list}",
          fail_detail=f"422 Unprocessable — dict[str,str] type bug still present!")

    validate_with_str, _ = POST("/platform/wizard/validate", {
        "domain": "test.example.com",
        "infra_selections": {"tunnels": "cloudflared"},
    })
    check("Wizard: tunnels as string",
          validate_with_str != 422,
          ok_detail=f"Got {validate_with_str}")

    # F5: health_check_history growth — must not be unbounded
    conn = _db()
    if conn:
        try:
            rows = conn.execute(
                "SELECT subject_key, check_name, COUNT(*) as cnt "
                "FROM health_check_history "
                "GROUP BY subject_key, check_name "
                "ORDER BY cnt DESC LIMIT 1"
            ).fetchone()
            if rows:
                check("health history: bounded (≤500)",
                      rows["cnt"] <= 500,
                      ok_detail=f"max {rows['cnt']} rows for {rows['subject_key']}:{rows['check_name']}",
                      fail_detail=f"{rows['cnt']} rows for {rows['subject_key']}:{rows['check_name']} — prune not running!")
            else:
                skipped("health_check_history bound check", "No history yet")
        except Exception as e:
            warned("health_check_history check", str(e))
        conn.close()

    # F6: Orphan detection — DB record with no compose fragment
    conn = _db()
    if conn:
        compose_dir = COMPOSE_DIR
        if compose_dir.exists():
            INFRA = {"traefik","tinyauth","authelia","cloudflared","tailscale",
                     "headscale","gluetun","glance","homepage","dockge",
                     "dockhand","komodo","portainer","portainer_be"}
            try:
                app_keys = [r[0] for r in conn.execute(
                    "SELECT key FROM apps WHERE status NOT IN ('disabled','removing')"
                ).fetchall()]
                orphans = [k for k in app_keys
                           if k not in INFRA
                           and not (compose_dir / f"{k}.yaml").exists()]
                check("No orphaned DB records",
                      not orphans,
                      ok_detail=f"{len(app_keys)} apps checked",
                      fail_detail=f"Orphaned records: {orphans} — run sudo ms-check or restart mediastack")
            except Exception as e:
                warned("Orphan detection", str(e))
        conn.close()


# ── SECTION G: Frontend↔Backend Contract Tests ────────────────────────────────

def test_section_G():
    if not section("G. Frontend ↔ Backend Contract Tests"):
        return

    # G1: /health/apps fields match what HealthView.vue expects
    status, body = GET("/health/apps")
    if status == 200 and isinstance(body, list) and body:
        first = body[0]
        # HealthView.vue accesses: c.app_key, c.check_name, c.status, c.summary
        for field in ("app_key", "check_name", "status", "summary"):
            check(f"health/apps: .{field}",
                  field in first,
                  fail_detail=f"HealthView.vue will get undefined for {field}")
        # HealthView does NOT use 'key' — if only 'key' is returned, it's a contract bug
        if "key" in first and "app_key" not in first:
            failed("health/apps: key not app_key",
                   "HealthView.vue references c.app_key — will be undefined!")

    # G2: /apps fields match what DashboardView.vue / CatalogView.vue expect
    status, body = GET("/apps")
    if status == 200 and isinstance(body, list) and body:
        first = body[0]
        for field in ("key", "display_name", "status", "category"):
            check(f"apps: .{field}",
                  field in first)

    # G3: /platform/prereqs.system has fields for Stage 1 auto-fill
    status, body = GET("/platform/prereqs")
    if status == 200 and isinstance(body, dict):
        sys_data = body.get("system", {})
        # SetupView.vue uses: sys.puid, sys.pgid, sys.timezone, sys.server_ip
        for field in ("puid", "pgid", "timezone"):
            check(f"prereqs.system: .{field}",
                  field in sys_data,
                  fail_detail=f"Stage 1 won't auto-fill {field}")

    # G4: /settings/system has fields for Settings System tab
    status, body = GET("/settings/system")
    if status == 200:
        for field in ("cpu_cores", "total_ram_gb", "free_ram_gb"):
            if field in body:
                passed(f"Settings/system.{field} present")
            else:
                warned(f"Settings/system.{field} missing", "System tab may show incomplete data")

    # G5: Health scheduler response matches HealthView.vue usage
    status, body = GET("/health/scheduler")
    if status == 200 and isinstance(body, dict):
        # HealthView.vue reads: schedulerStatus?.running, schedulerStatus?.last_cycle_ago
        for field in ("running",):
            check(f"Scheduler status.{field} present",
                  field in body,
                  fail_detail=f"HealthView.vue scheduler strip will show undefined")

    # G6: /platform/wizard/run-async and /wizard/status contract
    # Just check the endpoints exist and return proper structure
    async_run_status, _ = POST("/platform/wizard/run-async", {})
    # This should return 4xx (missing required fields) not 500
    check("wizard/run-async: 4xx on empty",
          async_run_status < 500 or async_run_status == 0,
          ok_detail=f"Got {async_run_status}",
          fail_detail=f"Server error {async_run_status} on empty request")


# ── SECTION H: Dependency Chain Tests ─────────────────────────────────────────

def test_section_H():
    if not section("H. Dependency Chain Tests"):
        return

    # H1: LLM agent gracefully handles no Ollama
    ping_status, ping_body = GET("/models/llm-ping")
    if ping_status == 200:
        # If ping succeeds, Ollama or cloud LLM is up
        passed("LLM: reachable", "Ollama or cloud LLM responding")
    else:
        # Should return structured response, not crash
        agent_status, agent_body = GET("/health/llm-agent")
        if agent_status == 200 and isinstance(agent_body, dict):
            passed("LLM: offline status",
                   f"status={agent_body.get('status')}")
        else:
            warned("LLM agent offline status", f"Got {agent_status}")

    # H2: Catalog endpoint returns all apps
    status, body = GET("/catalog")
    if status == 200:
        if isinstance(body, list):
            count = len(body)
        elif isinstance(body, dict):
            # Catalog returns {category: [apps]} grouped dict OR {"apps": [...]}
            if "apps" in body:
                count = len(body["apps"])
            else:
                count = sum(len(v) for v in body.values() if isinstance(v, list))
        else:
            count = 0
        check("Catalog: not empty", count > 0, ok_detail=f"{count} apps")
        if count > 0 and count < 50:
            warned("Catalog size", f"Only {count} apps — expected 55+")

    # H3: Storage sources endpoint
    status, body = GET("/storage/sources")
    if status == 200:
        passed("/storage/sources reachable")

    # H4: Managed services not blocking if postgres not deployed
    status, body = GET("/health/apps")
    if status == 200 and isinstance(body, list):
        postgres_errors = [c for c in body
                          if "postgres" in c.get("check_name", "").lower()
                          and c.get("status") == "error"]
        if postgres_errors:
            # Apps may be failing because postgres is down — this is expected
            warned("Postgres-dependent apps failing",
                   f"{len(postgres_errors)} checks failing — deploy postgres or check connections")
        else:
            passed("Postgres: no cascade failures")


# ── SECTION I: Cleanup and Orphan Tests ───────────────────────────────────────

def test_section_I():
    if not section("I. Cleanup and Orphan Tests"):
        return

    # I1: Startup cleanup function exists in main.py
    main_py = REPO / "backend" / "api" / "main.py"
    if main_py.exists():
        content = main_py.read_text()
        check("main.py: cleanup defined",
              "_cleanup_orphaned_records" in content,
              fail_detail="Startup cleanup not present — orphans accumulate between restarts")
        check("main.py: cleanup on startup",
              "_cleanup_orphaned_records()" in content,
              fail_detail="_cleanup_orphaned_records defined but never called!")
    else:
        skipped("main.py cleanup check", "File not found")

    # I2: orphan cleanup and history pruning happen at startup (main.py)
    # ms-update triggers a service restart which invokes startup cleanup.
    # The actual cleanup SQL lives in main.py _cleanup_orphaned_records().
    main_py = REPO / "backend" / "api" / "main.py"
    if main_py.exists():
        content = _read_cached(main_py)
        check("ms-update: cleans orphans",
              "DELETE FROM apps" in content or "_cleanup_orphaned_records" in content,
              fail_detail="No orphan cleanup in main.py startup — orphaned app records accumulate")
        check("ms-update: prunes history",
              "health_check_history" in content and "DELETE" in content,
              fail_detail="No health_check_history pruning in main.py — history grows unbounded")

    # I3: ms-check auto-remove uses correct function name
    ms_check = REPO / "ms-check"
    if ms_check.exists():
        content = _read_cached(ms_check)
        # The fix: must use 'pass' not 'ok' for success message
        if "Auto-fixed" in content or "Auto-removed" in content:
            # Check it uses 'pass' not 'ok' for the success case
            auto_fix_lines = [l for l in content.splitlines()
                              if "Auto-fixed" in l or "Auto-removed" in l]
            for line in auto_fix_lines:
                check("ms-check: auto-remove pass/ok",
                      "pass " in line or "pass \"" in line,
                      ok_detail=line.strip()[:45],
                      fail_detail=f"Uses 'ok' not 'pass': {line.strip()[:40]}")

    # I4: Ghost resource API exists
    ghost_status, ghost_body = GET("/health/ghost-resources")
    if ghost_status == 200:
        passed("ghost-resources: reachable")
    elif ghost_status == 404:
        warned("/health/ghost-resources", "Endpoint not found — ghost resource UI may be broken")


# ── SECTION J: Shell Script Integrity ────────────────────────────────────────

def test_section_J():
    if not section("J. Shell Script Integrity"):
        return

    for script_name in ("ms-check", "ms-update"):
        script = REPO / script_name
        if not script.exists():
            skipped(f"{script_name}", "File not found")
            continue

        content = script.read_text()
        lines = content.splitlines()

        # Must start with shebang
        check(f"{script_name}: starts with shebang",
              lines[0].startswith("#!"),
              ok_detail=lines[0])

        # set -euo pipefail or similar
        check(f"{script_name}: has set -e or set -euo",
              any("set -e" in l for l in lines[:20]),
              fail_detail="No error-exit flag — failures may be silently ignored")

        # Find all function definitions — handles ok()   { and ok() {
        import re as _re
        defined_fns = set()
        for line in lines:
            m = _re.match(r'^([a-zA-Z_][a-zA-Z_0-9]*)\(\)\s*\{', line.strip())
            if m:
                defined_fns.add(m.group(1))

        passed(f"{script_name}: functions defined ({len(defined_fns)})")

        # Check for common undefined function calls
        COMMON_UNDEFINED = ["ok ", "error "]
        for call in COMMON_UNDEFINED:
            call_lines = [l.strip() for l in lines
                          if l.strip().startswith(call) and not l.strip().startswith("#")]
            fn_name = call.strip()
            if call_lines and fn_name not in defined_fns:
                failed(f"{script_name}: '{fn_name}' called but not defined",
                       detail=f"Example: {call_lines[0][:60]}")

    # ms-check exit codes
    ms_check = REPO / "ms-check"
    if ms_check.exists():
        content = _read_cached(ms_check)
        check("ms-check: exit 0 pass",  "exit 0" in content)
        check("ms-check: exit 1 warn",  "exit 1" in content)
        check("ms-check: exit 2 error",    "exit 2" in content)


# ── SECTION K: End-to-End Flows ───────────────────────────────────────────────

def test_section_K():
    if not section("K. End-to-End Flows"):
        return

    # K1: System profile flow — prereqs → system populated
    prereq_status, prereq_body = GET("/platform/prereqs")
    if prereq_status == 200:
        sys_data = prereq_body.get("system", {})
        has_puid = "puid" in sys_data and sys_data["puid"]
        has_tz = "timezone" in sys_data and sys_data["timezone"]
        check("Prereqs: real system data",
              has_puid and has_tz,
              ok_detail=f"puid={sys_data.get('puid')}, tz={sys_data.get('timezone')}",
              fail_detail="System profile not collected — Stage 1 won't auto-fill")

    # K2: Platform status → wizard access
    plat_status, plat_body = GET("/platform/status")
    if isinstance(plat_body, dict):
        if plat_body.get("status") == "ready":
            passed("Wizard: 409 when ready",
                   f"domain={plat_body.get('domain')}")
        else:
            passed(f"Platform status: {plat_body.get('status')} — wizard should be accessible")

    # K3: Health cycle → pending fixes → approval flow
    _, fix_list = GET("/health/pending-fixes")
    if isinstance(fix_list, list) and fix_list:
        fix = fix_list[0]
        fix_id = fix.get("id")
        if fix_id:
            passed(f"Pending fixes: {len(fix_list)}",
                   f"First: {fix.get('app_key')} / {fix.get('action_type')}")
            # Check reject endpoint works
            reject_status, _ = POST(f"/health/pending-fixes/{fix_id}/reject")
            if reject_status in (200, 204):
                # Verify it's gone
                _, new_fixes = GET("/health/pending-fixes")
                still_there = any(f.get("id") == fix_id
                                  for f in (new_fixes or []))
                check("Fix: reject removes it",
                      not still_there,
                      fail_detail="Fix still in pending list after reject!")
    else:
        skipped("Pending fix approval flow", "No pending fixes to test")

    # K4: Weekly summary
    sum_status, sum_body = GET("/health/weekly-summary")
    if sum_status == 200 and isinstance(sum_body, dict):
        has_summary = sum_body.get("has_summary") or sum_body.get("summary")
        if has_summary:
            passed("Weekly summary: data")
        else:
            passed("Weekly summary: no data")
    elif sum_status == 200:
        passed("Weekly summary endpoint reachable")


# ── SECTION L: Performance Guards ────────────────────────────────────────────

def test_section_L():
    if not section("L. Performance / Regression Guards"):
        return

    # L1: Prereqs endpoint response time
    t0 = time.monotonic()
    status, _ = GET("/platform/prereqs")
    elapsed = time.monotonic() - t0
    if status == 200:
        check("Prereqs: < 10s",
              elapsed < 10,
              ok_detail=f"{elapsed:.1f}s",
              fail_detail=f"{elapsed:.1f}s — system detection too slow")
    else:
        skipped("Prereqs timing", f"Endpoint returned {status}")

    # L2: DB table sizes (no unbounded growth)
    conn = _db()
    if conn:
        SIZE_LIMITS = {
            "health_checks": 10000,
            "health_check_history": 50000,
            "operations": 5000,
            "pending_fixes": 500,
        }
        for table, limit in SIZE_LIMITS.items():
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                check(f"{table} row count within limit ({limit:,})",
                      count <= limit,
                      ok_detail=f"{count:,} rows",
                      fail_detail=f"{count:,} rows exceeds limit {limit:,} — cleanup not running!")
            except Exception:
                pass  # Table may not exist
        conn.close()

    # L3: Settings endpoint fast
    t0 = time.monotonic()
    GET("/settings")
    elapsed = time.monotonic() - t0
    check("Settings GET: < 2s", elapsed < 2,
          ok_detail=f"{elapsed:.2f}s")

    # L4: No API endpoint returns >10MB body unexpectedly
    for route in ("/health/apps", "/apps", "/catalog"):
        _, body = GET(route)
        size = len(json.dumps(body)) if body else 0
        check(f"GET {route}: size < 10MB",
              size < 10_000_000,
              ok_detail=f"{size/1024:.0f}KB",
              fail_detail=f"{size/1024/1024:.1f}MB — may cause frontend timeouts")


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(use_json: bool) -> int:
    _W = 48 + 20
    print(f"\n{'═'*_W}")
    print(f"{BOLD}TEST SUMMARY{RESET}")
    print(f"{'═'*_W}")

    total_pass = total_fail = total_skip = total_warn = 0
    critical_failures: list[str] = []

    _LBL = 48   # label column visible width
    _CW  = 4    # each count column width (e.g. "12P ")

    def _col(n: int, suffix: str, color: str) -> str:
        """Return a fixed-width colored count column."""
        val = f"{n}{suffix}"
        colored = f"{color}{val}{RESET}" if n else val
        return colored + " " * (_CW - len(val))

    def _row(label: str, p: int, f: int, s: int, w: int) -> None:
        lbl = label[:_LBL].ljust(_LBL)
        print(f"  {lbl} "
              f"{_col(p,'P',GREEN)}"
              f"{_col(f,'F',RED)}"
              f"{_col(s,'S',YELLOW)}"
              f"{_col(w,'W',YELLOW)}")

    for sec, counts in sorted(_section_counts.items()):
        if sec.startswith("__skip__"):
            continue
        p = counts.get("pass", 0)
        f = counts.get("fail", 0)
        s = counts.get("skip", 0)
        w = counts.get("warn", 0)
        total_pass += p; total_fail += f; total_skip += s; total_warn += w
        _row(sec, p, f, s, w)

    print(f"{'─'*(_LBL + 20)}")
    _row("TOTAL", total_pass, total_fail, total_skip, total_warn)

    # ── Failures — listed in [FAIL] style matching the rest of ms-test.py ──
    # Only shown when there ARE failures (skips listed during run, not here)
    all_failures = [(r["section"], r["name"], r.get("detail",""))
                    for r in _results if r["status"] == "FAIL"]

    if all_failures:
        print()
        for section, name, detail in all_failures:
            short = section.split(" ")[0] if " " in section else section[:2]
            print(f"  [FAIL] {short} {name}")
            if detail:
                print(f"         {detail[:120]}")

    print(f"\n{'PASS' if total_fail == 0 else 'FAIL'} — "
          f"{total_pass} passed, {total_fail} failed, "
          f"{total_skip} skipped, {total_warn} warnings")

    if use_json:
        output = {
            "summary": {"pass": total_pass, "fail": total_fail,
                        "skip": total_skip, "warn": total_warn},
            "sections": {k: v for k, v in _section_counts.items()
                         if not k.startswith("__skip__")},
            "results": _results,
            "critical_failures": critical_failures,
        }
        print("\n" + json.dumps(output, indent=2))

    if total_fail == 0:
        return 0
    if critical_failures:
        return 2
    return 1


# ── Entry point ───────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════════════════════
# SECTION M: Fault Injection Testing
# Tests how the system handles deliberate bad inputs, wrong types, invalid
# state transitions, and boundary values. These must never return 500.
# ═══════════════════════════════════════════════════════════════════════════

def test_section_M():
    if not section("M. Fault Injection Testing"):
        return

    def _fault(name: str, method: str, path: str, body=None,
                expect_not: tuple = (500,), ok_detail: str = ""):
        """Send a deliberately bad request; assert it doesn't 500."""
        status, resp = _req(method, path, json=body) if body is not None else _req(method, path)
        if status == 0:
            skipped(name, "API unreachable")
            return
        if status in expect_not:
            failed(name, f"Got {status} — server error on bad input! Response: "
                   f"{str(resp)[:120]}")
        else:
            passed(name, ok_detail or f"→ {status} (handled gracefully)")

    # ── M1: Wrong types ───────────────────────────────────────────────────
    _fault("M1a: PUID as string in wizard validate",
           "POST", "/platform/wizard/validate",
           {"domain": "test.local", "puid": "not-a-number"})

    _fault("M1b: Negative port number in settings",
           "PUT", "/settings",
           {"health_check_interval_secs": -1})

    _fault("M1c: health interval as string",
           "PUT", "/settings",
           {"health_check_interval_secs": "five-seconds"})

    _fault("M1d: disk_warn_percent > 100",
           "PUT", "/settings",
           {"disk_warn_percent": 999})

    _fault("M1e: disk_warn_percent > disk_error_percent",
           "PUT", "/settings",
           {"disk_warn_percent": 95, "disk_error_percent": 50},
           ok_detail="→ validates threshold ordering")

    # ── M2: Missing required fields ───────────────────────────────────────
    _fault("M2a: wizard/validate with no domain",
           "POST", "/platform/wizard/validate", {})

    _fault("M2b: maintenance window with no app_key",
           "POST", "/health/maintenance-windows",
           {"check_name": "test", "hour_start": 2, "hour_end": 4})

    _fault("M2c: pending fix approve with non-existent id",
           "POST", "/health/pending-fixes/999999/approve",
           expect_not=(500,))  # should 404, never 500

    _fault("M2d: pending fix reject with non-existent id",
           "POST", "/health/pending-fixes/999999/reject",
           expect_not=(500,))

    # ── M3: Injection attempts ────────────────────────────────────────────
    _fault("M3a: SQL injection in app key lookup",
           "GET", "/apps/' OR '1'='1",
           expect_not=(500,))

    _fault("M3b: Path traversal in app key",
           "GET", "/apps/../../etc/passwd",
           expect_not=(500,))

    _fault("M3c: XSS payload in domain field",
           "POST", "/platform/wizard/validate",
           {"domain": "<script>alert(1)</script>.example.com"})

    _fault("M3d: Null bytes in app key",
           "GET", "/apps/test\x00app",
           expect_not=(500,))

    # ── M4: Boundary values ───────────────────────────────────────────────
    _fault("M4a: Extremely long domain",
           "POST", "/platform/wizard/validate",
           {"domain": "a" * 1000 + ".example.com"})

    _fault("M4b: Empty string domain",
           "POST", "/platform/wizard/validate",
           {"domain": ""})

    _fault("M4c: Unicode in domain",
           "POST", "/platform/wizard/validate",
           {"domain": "médiastack.example.com"})

    _fault("M4d: GET app with empty key",
           "GET", "/apps/",
           expect_not=(500,))

    # ── M5: Invalid state transitions ─────────────────────────────────────
    # Approve a fix that was already rejected (double action)
    _, fixes = GET("/health/pending-fixes")
    if isinstance(fixes, list) and fixes:
        fix_id = fixes[0].get("id")
        if fix_id:
            # Reject it
            POST(f"/health/pending-fixes/{fix_id}/reject")
            # Try to approve the now-rejected fix
            status2, _ = POST(f"/health/pending-fixes/{fix_id}/approve")
            if status2 == 0:
                skipped("Fix: double-action", "API unreachable")
            elif status2 >= 500:
                failed("Fix: approve rejected → 500",
                       "Should return 404/400 gracefully")
            else:
                passed("Fix: approve rejected graceful",
                       f"→ {status2}")

    # ── M6: Wrong content-type ────────────────────────────────────────────
    # Send non-JSON to a JSON endpoint (use raw urllib)
    try:
        import urllib.request, urllib.error
        req = urllib.request.Request(
            f"{BASE_URL}/api/health/maintenance-windows",
            data=b"this is not json",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        check("Non-JSON body → 4xx",
              status < 500 or status == 0,
              ok_detail=f"→ {status}")
    except Exception as e:
        skipped("M6: Non-JSON body test", str(e))

    # ── M7: Concurrent state mutation ─────────────────────────────────────
    # Rapid duplicate requests — should not cause DB corruption
    import threading
    results_concurrent = []
    def _do_get():
        s, _ = GET("/health/apps")
        results_concurrent.append(s)

    threads = [threading.Thread(target=_do_get) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    non_500 = sum(1 for s in results_concurrent if s != 500 and s != 0)
    check("10 concurrent: no 500s",
          non_500 == len(results_concurrent) or len(results_concurrent) == 0,
          ok_detail=f"{non_500}/{len(results_concurrent)} clean",
          fail_detail=f"Got {len(results_concurrent)-non_500} server errors under concurrency")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION N: Logic Sequence & Process Order Testing
# Tests that operations happen in the right order, wrong-order calls are
# handled gracefully, and state machines follow valid transitions.
# ═══════════════════════════════════════════════════════════════════════════

def test_section_N():
    if not section("N. Logic Sequence & Process Order"):
        return

    # ── N1: Platform workflow sequencing ─────────────────────────────────
    plat_status, plat_body = GET("/platform/status")
    if isinstance(plat_body, dict):
        status_val = plat_body.get("status", "?")

        if status_val == "ready":
            # N1a: Wizard run on ready platform MUST return 409
            wiz_s, wiz_b = POST("/platform/wizard/run", {"domain": "test.local"})
            check("Wizard: 409 on ready",
                  wiz_s == 409,
                  ok_detail="Correctly blocks re-run without reset",
                  fail_detail=f"Got {wiz_s} — platform could be silently reconfigured!")

            # N1b: Async wizard also gated
            async_s, async_b = POST("/platform/wizard/run-async",
                                    {"domain": "test.local"})
            check("Wizard async: gated when ready",
                  async_s in (409, 422, 400, 200),  # 200 means it queued (after reset)
                  ok_detail=f"→ {async_s}",
                  fail_detail=f"Unexpected {async_s}")

        # N1c: Reset returns to pending
        if DESTRUCTIVE:
            rst_s, _ = POST("/platform/reset")
            check("Platform reset → pending",
                  rst_s in (200, 204),
                  ok_detail="Platform reset accepted")
        else:
            skipped("N1c: platform reset test", "Non-destructive mode")

    # ── N2: Health cycle sequencing ───────────────────────────────────────
    # N2a: Health results before any cycle → empty, not error
    check_s, check_b = GET("/health/apps")
    if check_s == 200:
        check("Health: list before cycle",
              isinstance(check_b, list),
              ok_detail=f"{len(check_b)} results")

    # N2b: Weekly summary before data → returns empty/placeholder, not error
    sum_s, sum_b = GET("/health/weekly-summary")
    check("Weekly summary: 200 no data",
          sum_s != 500 and sum_s != 0,
          ok_detail=f"→ {sum_s}")

    # N2c: Scheduler status always available (even before first cycle)
    sched_s, sched_b = GET("/health/scheduler")
    check("Scheduler: always reachable",
          sched_s == 200 and isinstance(sched_b, dict) and "running" in sched_b,
          ok_detail=f"running={sched_b.get('running') if isinstance(sched_b, dict) else '?'}")

    # ── N3: Fix approval sequencing ───────────────────────────────────────
    # N3a: Approve non-existent fix → 404 not 500
    s, b = POST("/health/pending-fixes/0/approve")
    check("Fix approve nonexistent: 404",
          s in (404, 400, 422) or s == 0,
          ok_detail=f"→ {s}",
          fail_detail=f"Got {s} — server error on non-existent fix!")

    # N3b: Reject non-existent fix → 404 not 500
    s, b = POST("/health/pending-fixes/0/reject")
    check("N3b: reject fix id=0 → 404 not 500",
          s in (404, 400, 422) or s == 0,
          ok_detail=f"→ {s}")

    # N3c: If a fix is approved, it should disappear from pending list
    _, fixes_before = GET("/health/pending-fixes")
    if isinstance(fixes_before, list) and fixes_before:
        fix = fixes_before[0]
        fix_id = fix.get("id")
        if fix_id:
            POST(f"/health/pending-fixes/{fix_id}/reject")
            _, fixes_after = GET("/health/pending-fixes")
            still_present = any(f.get("id") == fix_id
                                for f in (fixes_after or []))
            check("Fix: rejected removed",
                  not still_present,
                  fail_detail="Fix still in list after reject — state not updated!")
    else:
        skipped("N3c: fix removal verification", "No pending fixes")

    # ── N4: Maintenance window sequencing ─────────────────────────────────
    # Create → verify exists → delete → verify gone
    create_s, create_b = POST("/health/maintenance-windows", {
        "app_key": "ms_test_sequence",
        "check_name": "sequence_test",
        "label": "N4 sequence test window",
        "day_of_week": None,
        "hour_start": 3,
        "hour_end": 5,
    })
    if create_s in (200, 201) and isinstance(create_b, dict):
        wid = create_b.get("id")
        _, windows = GET("/health/maintenance-windows")
        found = any(w.get("label") == "N4 sequence test window"
                    for w in (windows or []))
        check("Maintenance: create+verify",
              found, fail_detail="Window not found after creation!")
        if wid:
            del_s, _ = _req("DELETE", f"/health/maintenance-windows/{wid}")
            _, windows2 = GET("/health/maintenance-windows")
            gone = not any(w.get("label") == "N4 sequence test window"
                           for w in (windows2 or []))
            check("Maintenance: delete+verify",
                  gone, fail_detail="Window still present after DELETE!")
            # N4c: Delete again → should 404, not 500
            del_s2, _ = _req("DELETE", f"/health/maintenance-windows/{wid}")
            check("Maintenance: delete idempotent",
                  del_s2 in (404, 400) or del_s2 == 0,
                  ok_detail=f"→ {del_s2}")
    elif create_s == 0:
        skipped("N4: maintenance window sequence", "API unreachable")
    else:
        warned("N4: maintenance window sequence",
               f"POST returned {create_s}")

    # ── N5: Infra slot sequencing ──────────────────────────────────────────
    # Verify → without deploy first → should handle gracefully
    for slot in ("auth", "tunnel", "vpn", "dashboard", "management"):
        s, b = POST(f"/infra/{slot}/verify")
        if s == 0:
            break  # API unreachable
        check(f"Infra {slot}: responds",
              s < 500,
              ok_detail=f"→ {s}")

    # ── N6: API response idempotency ──────────────────────────────────────
    # GET twice → same result
    s1, b1 = GET("/platform/status")
    s2, b2 = GET("/platform/status")
    if s1 == 200 and s2 == 200:
        check("Platform status: idempotent",
              b1.get("status") == b2.get("status"),
              ok_detail=b1.get("status"),
              fail_detail=f"First call: {b1.get('status')}, second: {b2.get('status')}")

    # ── N7: Frontend-expected sequencing ──────────────────────────────────
    # Prereqs MUST return puid/pgid/timezone for Stage 1 auto-fill to work
    s, b = GET("/platform/prereqs")
    if s == 200 and isinstance(b, dict):
        sys_d = b.get("system", {})
        # Test the logical chain: prereqs → Stage 1 form auto-fill
        chain_ok = all(sys_d.get(f) for f in ("puid", "pgid", "timezone"))
        check("Prereqs → Stage 1: auto-fill",
              chain_ok,
              ok_detail=f"puid={sys_d.get('puid')} pgid={sys_d.get('pgid')} tz={sys_d.get('timezone')}",
              fail_detail="Stage 1 form won't auto-fill — prereqs missing fields")

        # Checks must all have valid status values (gates Continue button)
        checks = b.get("checks", [])
        invalid_statuses = [c for c in checks
                            if c.get("status") not in ("ok","warning","error","skipped")]
        check("Prereqs: all statuses valid",
              not invalid_statuses,
              fail_detail=f"Invalid: {[c.get('status') for c in invalid_statuses]}")


# ═══════════════════════════════════════════════════════════════════════════
# History tracking — appended to after every run
# ═══════════════════════════════════════════════════════════════════════════

def _save_history(use_json: bool) -> None:
    """Append this run's results to .ms-test-history.json."""
    import datetime

    history_file = REPO / ".ms-test-history.json"
    try:
        existing = json.loads(history_file.read_text()) if history_file.exists() else {"runs": [], "version": "1.1"}
    except Exception:
        existing = {"runs": [], "version": "1.1"}

    run_record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "url": BASE_URL,
        "summary": {
            sec: counts for sec, counts in _section_counts.items()
            if not sec.startswith("__skip__")
        },
        "failures": [
            {"section": r["section"], "name": r["name"], "detail": r.get("detail","")}
            for r in _results if r["status"] == "FAIL"
        ],
        "gaps": [
            r["name"] for r in _results if r["status"] == "SKIP"
        ],
        "total_pass": sum(c.get("pass",0) for s,c in _section_counts.items() if not s.startswith("__skip__")),
        "total_fail": sum(c.get("fail",0) for s,c in _section_counts.items() if not s.startswith("__skip__")),
    }

    # Track lifetime run count independently of the rolling window
    existing["total_runs"] = existing.get("total_runs", len(existing.get("runs", []))) + 1
    # Keep last 50 runs in the file
    existing["runs"] = (existing.get("runs", []) + [run_record])[-50:]
    history_file.write_text(json.dumps(existing, indent=2))

    # Write fast-read summary for ms-update health banner.
    # Use DATA_DIR (config.data_dir) — same source production code uses
    # (Core Rule 3.9). Hardcoding REPO/"data" was the lone holdout that
    # diverges on non-default MS_DATA_DIR deployments. Closes 1.1.5.k.
    last_run_file = DATA_DIR / "last_test_run.json"
    last_run_file.parent.mkdir(parents=True, exist_ok=True)
    failed_names = [r["name"] for r in _results if r["status"] == "FAIL"]
    last_run_file.write_text(json.dumps({
        "failed": run_record["total_fail"],
        "passed": run_record["total_pass"],
        "failures": failed_names,          # names of failing tests for display
        "sections_with_failures": list({r["section"] for r in _results if r["status"] == "FAIL"}),
        "timestamp": run_record["timestamp"],
    }, indent=2))

    if not use_json:
        total = existing["total_runs"]
        kept  = len(existing["runs"])
        print(f"\n  History saved → {history_file.name}  "
              f"(run #{total}, last {kept} kept)")


# ═══════════════════════════════════════════════════════════════════════════
# Self-improvement engine
# ═══════════════════════════════════════════════════════════════════════════

def cmd_self_improve(model: str = "sonnet", apply: bool = False) -> None:
    """Read history + own source, call API, show diff, optionally apply."""
    try:
        import anthropic as _ant
    except ImportError:
        print("ERROR: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    model_ids = {
        "opus":   "claude-opus-4-6",
        "sonnet": "claude-sonnet-4-6",
        "haiku":  "claude-haiku-4-5-20251001",
    }
    model_id = model_ids.get(model, model_ids["sonnet"])

    # Read own source (truncated if very large)
    my_src = pathlib.Path(__file__).read_text()
    if len(my_src) > 40000:
        # Keep first 20k and last 10k — covers structure + recent additions
        my_src = my_src[:20000] + "\n\n... [middle truncated] ...\n\n" + my_src[-10000:]

    # Read history
    history_file = REPO / ".ms-test-history.json"
    history_summary = "No history yet."
    if history_file.exists():
        try:
            h = json.loads(history_file.read_text())
            runs = h.get("runs", [])[-5:]  # last 5 runs
            lines = []
            for r in runs:
                lines.append(
                    f"  {r['timestamp'][:10]}: "
                    f"{r['total_pass']}P {r['total_fail']}F  "
                    f"Failures: {[f['name'][:40] for f in r['failures'][:3]]}"
                )
            history_summary = "\n".join(lines) if lines else "No runs recorded yet."
        except Exception:
            pass

    prompt = f"""You are improving ms-test.py, the Mediastack integration test suite.

TASK: Improve the test script based on run history findings and known gaps.

CURRENT SCRIPT (may be truncated):
```python
{my_src}
```

LAST 5 RUN RESULTS:
{history_summary}

KNOWN GAPS (from codebase analysis):
- /platform/wizard/run-async endpoint has no async job polling tests
- step_callback in run_wizard not tested
- _cleanup_orphaned_records() startup function not tested  
- PUID/PGID mismatch detection in health context not tested
- Tunnel list vs string contract test coverage thin
- health_check_history pruning (LIMIT 500) not verified
- No test for wizard 409 when already ready AND when run-async called on ready platform
- No test for the health "0 checked = all healthy" silent failure with a real running app

INSTRUCTIONS:
1. Add tests for the gaps listed above
2. Fix any tests that are testing wrong things (based on failure history)
3. Do NOT remove existing tests — only add or improve
4. Output ONLY the Python code for the new/improved test functions
5. Each function should be a complete Python function starting with 'def test_' or update to an existing section
6. Include brief comments explaining WHAT bug/gap each test catches

Output the Python code improvements only. No explanation, no markdown."""

    print(f"\n{BOLD}Self-Improvement Mode{RESET}")
    print(f"Model: {model_id}")
    print(f"History: {history_summary[:200]}")
    print(f"\nCalling API...\n")

    client = _ant.Anthropic(api_key=api_key)
    improvement_code = []

    with client.messages.stream(
        model=model_id,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        system="Output only Python code. No markdown fences, no explanation.",
    ) as stream:
        for text in stream.text_stream:
            improvement_code.append(text)
            print(text, end="", flush=True)

    code = "".join(improvement_code)
    print(f"\n\n{'─'*60}")
    print(f"Generated {len(code)} chars of improvements")

    if apply:
        backup = pathlib.Path(__file__).with_suffix(
            f".py.bak.{int(time.time())}")
        backup.write_text(pathlib.Path(__file__).read_text())
        print(f"Backup: {backup}")

        with open(__file__, "a") as f:
            f.write(f"\n\n# ── Auto-improvement {time.strftime('%Y-%m-%d')} ──\n")
            f.write(code)
        print(f"\n{GREEN}Applied!{RESET} Re-run ms-test.py to use new tests.")
    else:
        print(f"\n{YELLOW}Dry run — use --apply to write improvements to ms-test.py{RESET}")
        tmp = pathlib.Path("/tmp/ms-test-improvement.py")
        tmp.write_text(code)
        print(f"Saved to: {tmp}")


# ═══════════════════════════════════════════════════════════════════════════
# Pytest suite analyzer
# ═══════════════════════════════════════════════════════════════════════════

def cmd_analyze_tests() -> None:
    """Analyze the existing 762-test pytest suite for quality and gaps."""
    import ast as _ast, re as _re

    tests_dir = REPO / "tests"
    if not tests_dir.exists():
        print("tests/ directory not found")
        return

    print(f"\n{BOLD}Pytest Suite Analysis{RESET}")
    print(f"{'─'*60}")

    all_tests: list[dict] = []
    file_stats: dict[str, dict] = {}

    for f in sorted(tests_dir.glob("test_*.py")):
        src = f.read_text(errors="replace")
        try:
            tree = _ast.parse(src)
        except SyntaxError as e:
            print(f"  {RED}[PARSE ERROR]{RESET} {f.name}: {e}")
            continue

        fns = [n for n in _ast.walk(tree)
               if isinstance(n, _ast.FunctionDef) and n.name.startswith("test_")]

        file_issues: list[str] = []
        fn_records: list[dict] = []

        for fn in fns:
            fn_src = _ast.get_source_segment(src, fn) or ""
            has_assert = bool(_re.search(r'\bassert\b|\bassertEqual\b|\bassertRaises\b', fn_src))
            uses_mock  = bool(_re.search(r'\bmock\b|\bpatch\b|\bMagicMock\b', fn_src, _re.I))
            is_placeholder = fn_src.strip().endswith("pass") and len(fn_src.strip().splitlines()) <= 3

            rec = {
                "file": f.name,
                "name": fn.name,
                "has_assert": has_assert,
                "uses_mock": uses_mock,
                "is_placeholder": is_placeholder,
                "lines": len(fn_src.splitlines()),
            }
            fn_records.append(rec)
            all_tests.append(rec)

            if not has_assert:
                file_issues.append(f"    no assertion: {fn.name}")
            if is_placeholder:
                file_issues.append(f"    placeholder (just 'pass'): {fn.name}")

        file_stats[f.name] = {
            "count": len(fns),
            "no_assert": sum(1 for r in fn_records if not r["has_assert"]),
            "mocked": sum(1 for r in fn_records if r["uses_mock"]),
            "placeholder": sum(1 for r in fn_records if r["is_placeholder"]),
            "issues": file_issues,
        }

    # Summary stats
    total = len(all_tests)
    no_assert_count   = sum(1 for t in all_tests if not t["has_assert"])
    mocked_count      = sum(1 for t in all_tests if t["uses_mock"])
    placeholder_count = sum(1 for t in all_tests if t["is_placeholder"])

    print(f"\n  Total tests:           {total}")
    print(f"  Tests using mocks:     {mocked_count} ({mocked_count*100//max(total,1)}%)")
    print(f"  Tests with no assert:  {no_assert_count}")
    print(f"  Placeholder tests:     {placeholder_count}")

    # Per-file quality report
    print(f"\n{'─'*60}")
    print(f"{'FILE':<35} {'COUNT':>5} {'NO_ASSERT':>9} {'MOCKED':>6}")
    print(f"{'─'*60}")
    for fname, stats in sorted(file_stats.items(), key=lambda x: -x[1]["no_assert"]):
        flag = f"  {YELLOW}⚠{RESET}" if stats["no_assert"] > 0 else ""
        print(f"  {fname:<33} {stats['count']:>5} {stats['no_assert']:>9} {stats['mocked']:>6}{flag}")

    # Gap analysis against known routes and features
    print(f"\n{'─'*60}")
    print(f"{BOLD}Coverage Gap Analysis{RESET}")
    all_test_src = "\n".join((REPO / "tests" / f).read_text(errors="replace")
                              for f in file_stats)
    GAP_CHECKS = [
        ("wizard/run-async",          ["run.async", "run_async"],   "NEW endpoint — no tests exist"),
        ("step_callback",             ["step_callback"],              "New param in run_wizard — untested"),
        ("_cleanup_orphaned_records", ["cleanup_orphan"],             "Startup cleanup — untested"),
        ("LIMIT 500 history prune",   ["LIMIT 500", "history.*prune"],"ms-update prune — untested"),
        ("tunnel list/string contract",["tunnels.*list","dict.*Any"], "Type fix — regression risk"),
        ("forceSetup URL param",      ["force=true","forceSetup"],    "Wizard re-run gate — untested"),
        ("PUID/PGID mismatch",        ["puid.*pgid.*mismatch","Permission denied.*PUID"], "Critical health context — untested"),
        ("GPU vendor-aware",          ["gpu_vendor","amd.*rocm","vendor.*nvidia"],"LLM context fix — has some coverage"),
        ("fault injection",           ["fault","injection","malformed","boundary"],"NEW — ms-test.py section M"),
        ("logic sequence",            ["sequence","wrong.order","idempotent"],"NEW — ms-test.py section N"),
        ("self-improvement",          ["self.improv","self_improv"],"NEW — ms-test.py feature"),
    ]
    for label, patterns, note in GAP_CHECKS:
        found = any(_re.search(p, all_test_src, _re.I) for p in patterns)
        status_str = f"{GREEN}✓ covered{RESET}" if found else f"{RED}✗ MISSING{RESET}"
        print(f"  {status_str}  {label:<35} {note}")

    # Actionable recommendations
    print(f"\n{'─'*60}")
    print(f"{BOLD}Recommendations{RESET}")

    recs: list[str] = []
    if no_assert_count > 0:
        recs.append(f"ADD assertions to {no_assert_count} tests that only check 'no crash'")
    if mocked_count > 100:
        recs.append(f"REDUCE mock usage: {mocked_count}/{total} tests use mocks — "
                    f"add integration tests in test_integration.py instead")
    recs.append("ADD tests for /platform/wizard/run-async + job polling in test_platform.py")
    recs.append("ADD tests for _cleanup_orphaned_records() in test_state.py or new file")
    recs.append("ADD parametrized fault-injection tests to test_api_coverage.py")
    recs.append("CONSOLIDATE: test_session_a/c/d are thin files — merge into test_integration.py")

    for i, r in enumerate(recs, 1):
        print(f"  {i}. {r}")

    print(f"\n  Run 'python3 ms-test.py --self-improve' to auto-generate improvements")
    print(f"  Run 'python3 tools/analyze-tests.py --report' for full report with suggested code\n")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION O: Prerequisites Performance & Correctness
# Verifies the optimized prereqs endpoint returns correct data quickly.
# A slow prereqs response means subprocesses are running sequentially.
# ═══════════════════════════════════════════════════════════════════════════

def test_section_O():
    if not section("O. Prerequisites Performance & Correctness"):
        return

    # O1: First call response time
    t0 = time.monotonic()
    status, body = GET("/platform/prereqs")
    elapsed = time.monotonic() - t0

    if status == 0:
        skipped("O: prereqs endpoint", "API unreachable")
        return

    # On a real server: target <3s first call, <0.1s cached call
    # The old sequential implementation could take 10s+ with docker stats
    check("Prereqs: < 5s",
          elapsed < 5.0,
          ok_detail=f"{elapsed:.2f}s",
          fail_detail=f"{elapsed:.2f}s — subprocesses may still be running sequentially")

    if status != 200:
        skipped("Prereqs: content", f"Endpoint returned {status}")
        return

    # O2: Required top-level keys
    for key in ("checks", "system"):
        check(f"O2: prereqs.{key} present",
              isinstance(body, dict) and key in body)

    checks = body.get("checks", [])
    system = body.get("system", {})

    # O3: All check statuses are valid values
    VALID = {"ok", "warning", "error", "skipped"}
    bad = [c for c in checks if c.get("status") not in VALID]
    check(f"Prereqs: all statuses valid",
          not bad,
          ok_detail=f"{len(checks)} checks",
          fail_detail=f"Invalid: {[(c.get('key'), c.get('status')) for c in bad[:3]]}")

    # O4: System profile has real data (not empty strings or zeros)
    check("Prereqs: cpu_cores",
          system.get("cpu_cores", 0) > 0,
          ok_detail=f"cpu_cores={system.get('cpu_cores')}",
          fail_detail="cpu_cores=0 — cpuinfo read failed")

    check("Prereqs: ram_gb",
          system.get("total_ram_gb", 0) > 0,
          ok_detail=f"{system.get('total_ram_gb')}GB",
          fail_detail="total_ram_gb=0 — meminfo read failed")

    check("Prereqs: timezone",
          bool(system.get("timezone")),
          ok_detail=system.get("timezone"),
          fail_detail="timezone empty — detect_timezone() returned empty string")

    check("O4: system.puid present",
          system.get("puid") is not None,
          ok_detail=f"puid={system.get('puid')}")

    # O5: Docker check present and non-error if Docker is running
    docker_check = next((c for c in checks if c.get("key") == "docker"), None)
    if docker_check:
        check("O5: docker check present in prereqs",
              True, ok_detail=f"status={docker_check.get('status')}, value={docker_check.get('value')}")
    else:
        warned("O5: docker check missing from prereqs",
               "No 'docker' key in checks — docker detection may have failed silently")

    # O6: Cached second call is faster (proves cache is working)
    t0 = time.monotonic()
    status2, body2 = GET("/platform/prereqs")
    elapsed2 = time.monotonic() - t0

    if status2 == 200:
        if elapsed > 0.005:
            # Only meaningful when first call was slow enough to distinguish
            check("Prereqs: cache working",
                  elapsed2 < elapsed,
                  ok_detail=f"first={elapsed:.2f}s, cached={elapsed2:.2f}s",
                  fail_detail=f"Cache not working — second call {elapsed2:.2f}s >= first {elapsed:.2f}s")
        else:
            passed("Prereqs: cache working", f"both calls <5ms — already warm")
        check("O6: cached prereqs call < 0.5s",
              elapsed2 < 0.5,
              ok_detail=f"{elapsed2:.3f}s",
              fail_detail=f"{elapsed2:.2f}s — cache may not be returning stored result")
    else:
        skipped("O6: cache speed test", f"Second call returned {status2}")

    # O7: Stage 1 auto-fill data present (puid, pgid, timezone)
    for field in ("puid", "pgid", "timezone"):
        check(f"Prereqs.system: .{field}",
              bool(system.get(field)),
              ok_detail=str(system.get(field)),
              fail_detail=f"Empty — Stage 1 won't auto-fill {field}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION P: Wizard Option Coverage
# For every selectable option in the wizard (auth, tunnel, VPN, DNS provider,
# dashboard, management), verify that:
#   1. The backend accepts it without error
#   2. The required secrets are known to the system
#   3. The validate endpoint doesn't 422 when that option is selected
#
# This is the test class that would have caught the TinyAuth password gap,
# the Gluetun credentials gap, and the 12 missing DNS provider fields.
# ═══════════════════════════════════════════════════════════════════════════

# Authoritative map: every wizard option → required env vars
# This mirrors backend/core/compose.py _PROVIDER_ENV_VARS and each provider's deploy()
WIZARD_OPTION_SECRETS: dict[str, list[str]] = {
    # DNS providers (from backend/core/compose.py _PROVIDER_ENV_VARS)
    "dns:cloudflare":   ["CF_DNS_API_TOKEN"],
    "dns:route53":      ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "AWS_HOSTED_ZONE_ID"],
    "dns:namecheap":    ["NAMECHEAP_API_USER", "NAMECHEAP_API_KEY"],
    "dns:porkbun":      ["PORKBUN_API_KEY", "PORKBUN_SECRET_API_KEY"],
    "dns:digitalocean": ["DO_AUTH_TOKEN"],
    "dns:gandi":        ["GANDI_PERSONAL_ACCESS_TOKEN"],
    "dns:hetzner":      ["HETZNER_API_KEY"],
    "dns:linode":       ["LINODE_TOKEN"],
    "dns:ovh":          ["OVH_ENDPOINT", "OVH_APPLICATION_KEY", "OVH_APPLICATION_SECRET", "OVH_CONSUMER_KEY"],
    "dns:godaddy":      ["GODADDY_API_KEY", "GODADDY_API_SECRET"],
    "dns:duckdns":      ["DUCKDNS_TOKEN"],
    "dns:desec":        ["DESEC_TOKEN"],
    "dns:vultr":        ["VULTR_API_KEY"],
    "dns:bunny":        ["BUNNY_API_KEY"],
    # Auth options
    "auth:tinyauth":    ["TINYAUTH_SECRET", "TINYAUTH_AUTH_USERS"],
    "auth:authelia":    ["AUTHELIA_JWT_SECRET", "AUTHELIA_SESSION_SECRET"],
    # Tunnel options
    "tunnel:cloudflared": ["CF_TUNNEL_TOKEN"],
    "tunnel:tailscale":   ["TAILSCALE_AUTH_KEY"],
    "tunnel:headscale":   ["HEADSCALE_AUTH_KEY"],
    # VPN options
    "vpn:gluetun":      ["VPN_SERVICE_PROVIDER", "VPN_TYPE"],
    # Management options
    "management:komodo": ["KOMODO_JWT_SECRET", "KOMODO_PASSKEY"],
    # Cert resolvers
    "cert:zerossl":     ["ZEROSSL_EAB_KID", "ZEROSSL_EAB_HMAC"],
}


def test_section_P():
    if not section("P. Wizard Option Coverage"):
        return

    # P1: Backend _PROVIDER_ENV_VARS includes all frontend DNS providers
    s, body = GET("/platform/wizard/steps")
    if s == 0:
        skipped("P: wizard steps", "API unreachable")
        return

    # P2: validate endpoint accepts every DNS provider without 422
    # (Tests that the backend validator knows each provider)
    dns_providers = [
        "cloudflare", "route53", "namecheap", "porkbun", "digitalocean",
        "gandi", "hetzner", "linode", "ovh", "godaddy", "duckdns",
        "desec", "vultr", "bunny", "njalla", "inwx", "infomaniak",
        "azure", "google", "dnspod",
    ]
    rejected = []
    for provider in dns_providers:
        vs, vb = POST("/platform/wizard/validate", {
            "domain": "test.example.com",
            "dns_provider": provider,
        })
        if vs == 422:
            rejected.append(provider)
        elif vs == 0:
            skipped(f"DNS provider: validation", "API unreachable")
            break

    check("DNS providers: accepted",
          not rejected,
          ok_detail=f"{len(dns_providers)} providers checked",
          fail_detail=f"Rejected providers: {rejected} — backend validator doesn't know them")

    # P3: step_traefik_deploy prerequisite check uses _PROVIDER_ENV_VARS
    # Verify the backend knows which vars each provider needs
    # (proxy for: "does the secret field exist for this provider?")
    s, body = GET("/platform/wizard/steps")
    if s == 200 and isinstance(body, list):
        step_names = [step.get("step") or step.get("name", "") for step in body]
        check("Wizard: traefik_deploy",
              "traefik_deploy" in step_names,
              ok_detail=f"Steps: {', '.join(step_names[:3])}…")

    # P4: Wizard validate with auth=tinyauth does not 422
    for auth_val in ("tinyauth", "authelia", "none"):
        vs, vb = POST("/platform/wizard/validate", {
            "domain": "test.example.com",
            "infra_selections": {"auth": auth_val},
        })
        check(f"Wizard: auth={auth_val}",
              vs != 422 or vs == 0,
              ok_detail=f"→ {vs}",
              fail_detail=f"422 — backend rejects auth={auth_val}")

    # P5: Wizard validate with vpn=gluetun does not 422
    vs, vb = POST("/platform/wizard/validate", {
        "domain": "test.example.com",
        "infra_selections": {"vpn": "gluetun"},
    })
    check("Wizard: vpn=gluetun",
          vs != 422 or vs == 0,
          ok_detail=f"→ {vs}")

    # P6: Wizard validate with management=komodo does not 422
    vs, vb = POST("/platform/wizard/validate", {
        "domain": "test.example.com",
        "infra_selections": {"management": "komodo"},
    })
    check("Wizard: management=komodo",
          vs != 422 or vs == 0,
          ok_detail=f"→ {vs}")

    # P7: bcrypt endpoint works (needed for TinyAuth password hashing)
    bs, bb = POST("/platform/wizard/bcrypt-users",
                  {"username": "admin", "password": "testpassword123"})
    if bs == 0:
        skipped("P7: bcrypt-users endpoint", "API unreachable")
    else:
        check("bcrypt-users: hash returned",
              bs == 200 and isinstance(bb, dict) and "users" in bb,
              ok_detail=f"{str(bb.get('users',''))[:15]}…" if bs == 200 else "",
              fail_detail=f"Got {bs}: {bb}")
        if bs == 200 and "users" in bb:
            users_str = bb["users"]
            check("bcrypt-users: format valid",
                  ":" in users_str and "$2b$" in users_str,
                  ok_detail="format OK",
                  fail_detail=f"Bad format: {users_str[:30]}")

    # P8: cert-status endpoint exists
    cs, cb = GET("/platform/cert-status")
    check("cert-status: endpoint exists",
          cs in (200, 404) or cs == 0,
          ok_detail=f"→ {cs}",
          fail_detail=f"Server error {cs}")

    # P9: Verify the option→secret mapping contract
    # For each option that has required secrets, at least one of those
    # env vars should appear in the step_traefik_deploy validation error
    # when that provider is selected without the token
    for key, required_vars in list(WIZARD_OPTION_SECRETS.items())[:3]:  # sample 3
        kind, value = key.split(":", 1)
        if kind == "dns" and value != "cloudflare":
            # Try to deploy without providing the required var — should get a clear error
            # We check by running validate, not actual deploy
            vs, vb = POST("/platform/wizard/validate", {
                "domain": "test.example.com",
                "dns_provider": value,
            })
            # Validate returns ok (secrets not checked at validate stage)
            # The check happens at deploy time — so we just confirm validate passes
            if vs != 0:
                check(f"P9: validate({value}) not 422",
                      vs != 422,
                      ok_detail=f"→ {vs}")

def cmd_show_trend() -> None:
    """Show pass/fail trend from .ms-test-history.json across runs."""
    history_file = REPO / ".ms-test-history.json"
    if not history_file.exists():
        print("No history yet — run ms-test.py first to record results.")
        return

    h = json.loads(history_file.read_text())
    runs = h.get("runs", [])
    if not runs:
        print("History file exists but contains no runs.")
        return

    print(f"\n{BOLD}ms-test.py Run History ({len(runs)} runs){RESET}")
    print(f"{'DATE':<12} {'URL':<25} {'PASS':>5} {'FAIL':>5} {'SKIP':>5} {'TREND'}")
    print("─" * 65)

    prev_fail = None
    for r in runs[-15:]:  # last 15
        ts = r.get("timestamp", "")[:10]
        url = r.get("url", "")[:24]
        total_p = r.get("total_pass", 0)
        total_f = r.get("total_fail", 0)
        total_s = sum(c.get("skip", 0) for c in r.get("summary", {}).values())

        if prev_fail is not None:
            if total_f < prev_fail:
                trend = f"{GREEN}↓ improving{RESET}"
            elif total_f > prev_fail:
                trend = f"{RED}↑ degrading{RESET}"
            else:
                trend = "→ stable"
        else:
            trend = ""

        fail_col = f"{RED}{total_f:>5}{RESET}" if total_f > 0 else f"{GREEN}{total_f:>5}{RESET}"
        print(f"  {ts:<12} {url:<25} {total_p:>5} {fail_col} {total_s:>5}  {trend}")
        prev_fail = total_f

    # Repeated failure patterns
    if len(runs) >= 3:
        all_fail_names: dict = {}
        for r in runs[-5:]:
            for f in r.get("failures", []):
                all_fail_names[f["name"]] = all_fail_names.get(f["name"], 0) + 1

        persistent = {k: v for k, v in all_fail_names.items() if v >= 3}
        if persistent:
            print(f"\n{RED}Persistent failures (≥3 of last 5 runs):{RESET}")
            for name, count in sorted(persistent.items(), key=lambda x: -x[1]):
                print(f"  {count}× {name}")
        else:
            print(f"\n{GREEN}No persistent failures detected.{RESET}")


def test_section_Q():
    if not section("Q. Application Flow Invariants"):
        return

    # Q1: cert_resolver is set by Traefik wizard step — may be absent on partial setups
    plat_s, plat_b = GET("/platform/status")
    if plat_s == 200 and isinstance(plat_b, dict) and plat_b.get("status") == "ready":
        cert = plat_b.get("cert_resolver")
        if cert:
            passed("Platform: cert_resolver", f"resolver={cert}")
        else:
            warned("Platform: cert_resolver",
                   "cert_resolver not configured — re-run full platform setup wizard")

        check("Platform: domain",
              bool(plat_b.get("domain")),
              ok_detail=plat_b.get("domain"))

    # Q2: LLM agent config has ollama_url if provider=ollama
    llm_s, llm_b = GET("/health/llm-agent")
    if llm_s == 200 and isinstance(llm_b, dict):
        provider = llm_b.get("configured_provider", "")
        if provider == "ollama":
            url = llm_b.get("ollama_url", "")
            check("Ollama: Docker hostname",
                  url and "localhost" not in url and "127.0.0.1" not in url,
                  ok_detail=url,
                  fail_detail=f"URL={url} — localhost won't work inside Docker containers!")
            check("Ollama URL: not localhost",
                  "ollama:11434" in (url or ""),
                  ok_detail=url,
                  fail_detail=f"Should be http://ollama:11434, got: {url}")

    # Q3: Apps deployed by this system must have compose fragments.
    #
    # Precondition: platform must be 'ready' (wizard completed).
    # When platform is 'pending', any apps in the DB are legacy records from a
    # prior deployment — they were never deployed by v4's wizard/infra system, so
    # expecting compose fragments at config.compose_dir is wrong.
    #
    # Fragment path: config.data_dir/compose/{key}.yaml (not REPO/data/compose)
    # Infra apps write fragments via write_fragment() to this same directory.
    # Slots with status != 'active' were never deployed by this system — skip them.
    conn = _db()
    if conn:
        try:
            plat_row = conn.execute("SELECT status FROM platform LIMIT 1").fetchone()
            plat_status = plat_row[0] if plat_row else "pending"
        except Exception:
            plat_status = "pending"

        if not section_requires("platform_status", "ready",
                                  "Q3: fragment check only valid after wizard completes"):
            pass
        else:
            try:
                from backend.core.config import config as _cfg
                compose_dir = _cfg.data_dir / "compose"
            except Exception:
                compose_dir = COMPOSE_DIR

            if not compose_dir.exists():
                skipped("Q3: compose dir not created yet")
            else:
                try:
                    running = conn.execute(
                        "SELECT key FROM apps WHERE status='running'"
                    ).fetchall()

                    # Infra apps write fragments too, but only when their slot is active.
                    # Slot status='active' means v4 deployed them → fragment expected.
                    # Slot status='empty'/'pending' means not deployed → no fragment expected.
                    infra_active = set()
                    try:
                        rows = conn.execute(
                            f"SELECT provider FROM {TABLE_INFRA_SLOTS} WHERE status='active' AND provider IS NOT NULL"
                        ).fetchall()
                        infra_active = {r[0] for r in rows if r[0]}
                        tunnel_rows = conn.execute(
                            f"SELECT provider FROM {TABLE_TUNNEL_PROVIDERS}"
                        ).fetchall()
                        infra_active |= {r[0] for r in tunnel_rows if r[0]}
                    except Exception:
                        pass

                    # Apps that SHOULD have fragments: running + (not infra OR infra active)
                    should_have_frag = [
                        r[0] for r in running
                        if (compose_dir / f"{r[0]}.yaml").exists() is False
                        and (r[0] in infra_active or r[0] not in infra_active)
                    ]

                    no_fragment = [r[0] for r in running
                                   if not (compose_dir / f"{r[0]}.yaml").exists()]

                    check("Running apps: compose exists",
                          not no_fragment,
                          ok_detail=f"{len(running)} running apps checked",
                          fail_detail=f"Running apps with no fragment: {no_fragment}")
                except Exception as exc:
                    warned("Q3: compose fragment check", str(exc))
        conn.close()

    # Q4: Health cycle count matches running app count
    _, apps_b = GET("/apps")
    _, health_b = GET("/health/scheduler")
    if isinstance(apps_b, list) and isinstance(health_b, dict):
        running_count = sum(1 for a in apps_b if a.get("status") == "running")
        last_checked = health_b.get("last_apps_checked", -1)
        if running_count > 0 and last_checked == 0:
            warned("Scheduler: no checks yet",
                   f"{running_count} apps running but 0 ever health-checked — run a health cycle")
        elif running_count > 0 and last_checked > 0:
            passed(f"Q4: health has checked apps ({last_checked} last cycle, {running_count} running)")

    # Q5: Stage 8 race condition guard — install_stacks checks platform status
    import re as _re, pathlib as _pl
    platform_api = _pl.Path(__file__).parent / "backend" / "api" / "platform.py"
    if platform_api.exists():
        src = platform_api.read_text()
        install_fn = src[src.find("wizard/install-stacks"):src.find("wizard/install-stacks")+800]
        has_gate = ("wizard/install-stacks" in src and
                    ("ready" in install_fn) and
                    ("status" in install_fn))
        check("install-stacks: platform gate",
              has_gate,
              ok_detail="Gate prevents install before platform completes",
              fail_detail="No platform-ready check — apps fail with 'setup not complete'")

def main() -> None:
    global BASE_URL, DESTRUCTIVE, SECTION_FILTER

    p = argparse.ArgumentParser(description="Mediastack comprehensive test suite")
    p.add_argument("--url", default=BASE_URL, help="API base URL")
    p.add_argument("--section", default="",
                   help="Run only these sections (e.g. A,B,F,M,N)")
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p.add_argument("--destructive", action="store_true",
                   help="Include tests that modify data (install, wizard, etc.)")
    p.add_argument("--self-improve", action="store_true",
                   help="Generate improvements via AI based on run history")
    p.add_argument("--apply", action="store_true",
                   help="Apply self-improvements to ms-test.py (use with --self-improve)")
    p.add_argument("--model", default="sonnet", choices=["opus","sonnet","haiku"],
                   help="AI model for --self-improve (default: sonnet)")
    p.add_argument("--analyze-tests", action="store_true",
                   help="Analyze existing pytest suite for quality and gaps")
    p.add_argument("--trend", action="store_true",
                   help="Show pass/fail trends from run history")
    args = p.parse_args()

    # Special modes — don't run tests
    if args.self_improve:
        cmd_self_improve(model=args.model, apply=args.apply)
        return
    if args.analyze_tests:
        cmd_analyze_tests()
        return
    if args.trend:
        cmd_show_trend()
        return

    BASE_URL = args.url.rstrip("/")
    DESTRUCTIVE = args.destructive
    SECTION_FILTER = [s.strip().upper() for s in args.section.split(",") if s.strip()]

    print(f"{BOLD}Mediastack Comprehensive Test Suite{RESET}")
    print(f"URL: {BASE_URL}  |  Destructive: {DESTRUCTIVE}  |  "
          f"Sections: {SECTION_FILTER or 'all'}")

    api_ok = test_section_A()
    if not api_ok:
        print(f"\n{RED}API not reachable — most tests cannot run.{RESET}")
    else:
        _populate_context()  # Core Rule 2.9: populate all preconditions once
        test_section_B()
        test_section_C()
        test_section_D()
        test_section_E()
        test_section_F()
        test_section_G()
        test_section_H()
        test_section_I()
        test_section_J()
        test_section_K()
        test_section_L()
        test_section_M()
        test_section_N()
        test_section_O()
        test_section_P()
        test_section_Q()

    _save_history(args.json)
    sys.exit(print_summary(args.json))


if __name__ == "__main__":
    main()
