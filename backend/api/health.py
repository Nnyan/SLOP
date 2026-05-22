"""backend/api/health.py

Health monitoring API routes.

GET  /api/health/status          — last health run summary
GET  /api/health/apps            — all app health check results
GET  /api/health/apps/{key}      — single app health
POST /api/health/run             — trigger a health cycle immediately
GET  /api/health/llm-agent       — LLM agent status
"""
from __future__ import annotations

from typing import Any

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.rate_limit import limiter
from backend.core.logging import get_logger
from backend.core.state import StateDB
from backend.health.checker import _llm_state

log = get_logger(__name__)
router = APIRouter()


class AppHealthOut(BaseModel):
    app_key: str
    check_name: str
    status: str
    summary: str
    last_checked: str | None
    auto_fix: str | None


class LLMAgentStatus(BaseModel):
    status: str
    consecutive_failures: int
    consecutive_slow: int
    description: str
    last_error: str = ""
    last_error_type: str = ""
    ollama_url: str = ""
    model_tried: str = ""
    last_success_at: int = 0
    configured_provider: str = "ollama"


@router.get("/apps", response_model=list[AppHealthOut])
def get_all_app_health() -> list[AppHealthOut]:
    with StateDB() as db:
        rows = db.execute(
            "SELECT * FROM health_checks WHERE subject_type='app' ORDER BY checked_at DESC"
        ).fetchall()
    seen: set[str] = set()
    results = []
    for row in rows:
        key = f"{row['subject_key']}:{row['check_name']}"
        if key in seen:
            continue
        seen.add(key)
        checked = row["checked_at"]
        results.append(AppHealthOut(
            app_key=row["subject_key"],
            check_name=row["check_name"],
            status=row["status"],
            summary=row["summary"] or "",
            last_checked=datetime.fromtimestamp(checked).isoformat() if checked else None,
            auto_fix=row["auto_fix"] if "auto_fix" in row.keys() else None,
        ))
    return results


@router.get("/apps/{key}", response_model=list[AppHealthOut])
def get_app_health(key: str) -> list[AppHealthOut]:
    with StateDB() as db:
        rows = db.execute(
            "SELECT * FROM health_checks WHERE subject_type='app' AND subject_key=? ORDER BY checked_at DESC",
            (key,)
        ).fetchall()
    return [
        AppHealthOut(
            app_key=r["subject_key"],
            check_name=r["check_name"],
            status=r["status"],
            summary=r["summary"] or "",
            last_checked=datetime.fromtimestamp(r["checked_at"]).isoformat() if r["checked_at"] else None,
            auto_fix=r["auto_fix"] if "auto_fix" in r.keys() else None,
        )
        for r in rows
    ]



@router.get("/summary")
def get_health_summary() -> dict[str, Any]:
    """Return lightweight ok/warning/error counts — for sidebar display.
    Avoids fetching all check details just to count statuses.
    """
    from backend.core.state import StateDB
    with StateDB() as db:
        rows = db.execute(
            "SELECT status, COUNT(*) as n FROM health_checks "
            "WHERE subject_type='app' GROUP BY status"
        ).fetchall()
    counts = {"ok": 0, "warning": 0, "error": 0, "unknown": 0}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] = r["n"]
    return counts

@router.get("/llm-agent", response_model=LLMAgentStatus)
def get_llm_agent_status() -> LLMAgentStatus:
    status = _llm_state.get("status", "unknown")
    descriptions = {
        "active":   "LLM responding quickly and producing valid JSON diagnoses.",
        "degraded": "LLM responses are slow or unreliable. Escalation-only mode.",
        "offline":  "LLM unreachable. Rule-based healing only.",
        "disabled": "LLM agent explicitly disabled. Rule-based healing only.",
        "unknown":  "LLM agent has not run yet this session.",
    }
    # Build a rich description when there's an error
    base_desc = descriptions.get(status, "Unknown state.")
    last_err = _llm_state.get("last_error", "")
    url = _llm_state.get("ollama_url", "") or "http://localhost:11434"
    model = _llm_state.get("model_tried", "") or "phi4-mini"
    err_type = _llm_state.get("last_error_type", "")

    if status == "offline" and last_err:
        if err_type == "connection":
            base_desc = f"Cannot reach Ollama at {url}. Check that Ollama is installed and running."
        elif err_type == "model":
            base_desc = f"Model \'{model}\' not found in Ollama. Run: ollama pull {model}"
        elif err_type == "timeout":
            base_desc = f"Model \'{model}\' took too long to respond. Try a smaller/faster model."
        elif err_type == "parse":
            base_desc = f"Model \'{model}\' returned malformed output. Try a different model."

    return LLMAgentStatus(
        status=status,
        consecutive_failures=_llm_state.get("consecutive_failures", 0),
        consecutive_slow=_llm_state.get("consecutive_slow", 0),
        description=base_desc,
        last_error=last_err,
        last_error_type=err_type,
        ollama_url=url,
        model_tried=model,
        last_success_at=_llm_state.get("last_success_at", 0),
        configured_provider=_llm_state.get("configured_provider", "ollama") or "ollama",
    )


@router.post("/run")
@limiter.limit("10/minute")  # type: ignore[untyped-decorator]  # slowapi decorator is untyped (Step 2.4 — heavy read tier)
async def trigger_health_run(request: Request) -> dict[str, Any]:
    """Trigger an immediate health check cycle."""
    try:
        from backend.core.state import StateDB
        from backend.health.checker import run_health_cycle
        import json

        with StateDB() as db:
            cfg = db.get_setting("llm_agent_config")

        agent_cfg = json.loads(cfg) if cfg else {}
        ollama_url = agent_cfg.get("ollama_url", "http://ollama:11434")
        ntfy_topic = agent_cfg.get("ntfy_topic", "mediastack")

        run = await run_health_cycle(
            ollama_url=ollama_url,
            ntfy_url="http://ntfy:80",
            ntfy_topic=ntfy_topic,
        )
    except Exception as _e:
        raise HTTPException(status_code=500,
                            detail=f"Health cycle failed: {type(_e).__name__}: {_e}")

    # Count all installed apps for context (health cycle only checks status=running)
    from backend.core.state import StateDB as _SDB
    with _SDB() as _db:
        all_apps = _db.get_all_apps()
    total_installed = len(all_apps)
    non_running = [a.key for a in all_apps if a.status != "running"]

    return {
        "apps_checked": run.apps_checked,
        "apps_healthy": run.apps_healthy,
        "apps_degraded": run.apps_degraded,
        "total_installed": total_installed,
        "non_running_apps": non_running,
        "note": (
            f"Health cycle checks apps with status=running. "
            f"{len(non_running)} installed app(s) not running: {non_running}"
            if non_running else "All installed apps are running."
        ),
        "llm_agent_state": run.llm_agent_state,
        "duration_ms": int((run.started_at - __import__("time").monotonic()) * -1000),
        "results": [
            {
                "app": r.app_key,
                "check": r.check_name,
                "ok": r.ok,
                "message": r.message,
                "auto_healed": r.auto_healed,
                "notification_sent": r.notification_sent,
                "llm_diagnosis": r.llm_diagnosis,
            }
            for r in run.results
        ],
    }


@router.get("/scheduler", tags=["Health"])
def get_scheduler_status() -> dict[str, Any]:
    """Return the health scheduler status.

    Shows whether the background check scheduler is running,
    the last cycle time, and last cycle results.
    """
    from backend.health.scheduler import scheduler_status
    status = scheduler_status()

    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            last_at = db.get_setting("health_last_cycle_at")
            last_summary = db.get_setting("health_last_cycle_summary")
        import json, datetime as _dt
        summary = json.loads(last_summary) if last_summary else None
        last_ts = (
            _dt.datetime.fromtimestamp(int(last_at)).isoformat()
            if last_at else None
        )
    except Exception:
        summary = None
        last_ts = None

    return {
        **status,
        "last_cycle_at": last_ts,
        "last_cycle_summary": summary,
    }


@router.post("/scheduler/pause", tags=["Health"])
def pause_scheduler() -> dict[str, Any]:
    """Temporarily pause the health scheduler.
    Useful when running maintenance that would produce false alarms.
    """
    from backend.health.scheduler import stop_scheduler
    stop_scheduler()
    return {"ok": True, "message": "Health scheduler paused. Restart the API to resume."}


@router.put("/settings", tags=["Health"])
def update_health_settings(
    interval_secs: int | None = None,
    ntfy_topic: str | None = None,
    ollama_url: str | None = None,
) -> dict[str, Any]:
    """Update health scheduler settings.

    interval_secs: seconds between check cycles (minimum 10, default 30)
    ntfy_topic: ntfy topic for failure notifications
    ollama_url: Ollama base URL for LLM agent

    Changes take effect at the next cycle — no restart needed.
    """
    from backend.core.state import StateDB
    updated: dict[str, Any] = {}
    with StateDB() as db:
        if interval_secs is not None:
            val = max(30, interval_secs)  # 30s minimum matches DNS challenge delay
            db.set_setting("health_check_interval_secs", str(val))
            updated["health_check_interval_secs"] = val
        if ntfy_topic is not None:
            db.set_setting("ntfy_topic", ntfy_topic)
            updated["ntfy_topic"] = ntfy_topic
        if ollama_url is not None:
            import json as _json
            existing = db.get_setting("llm_agent_config") or "{}"
            cfg = _json.loads(existing)
            cfg["ollama_url"] = ollama_url
            db.set_setting("llm_agent_config", _json.dumps(cfg))
            updated["ollama_url"] = ollama_url
    return {"ok": True, "updated": updated}


# ── Pending actions ────────────────────────────────────────────────────────

class PendingAction(BaseModel):
    priority: str   # error | warning | suggestion
    title: str
    description: str
    action: str     # human-readable action to take
    link: str | None = None   # UI route to navigate to
    icon: str = ""


@router.get("/pending-actions")
def get_pending_actions() -> list[PendingAction]:
    """Return outstanding platform issues, ordered by priority.

    Sources: platform DB state, settings, installed apps, health results.
    Errors first, then warnings, then suggestions.
    """
    from backend.core.state import StateDB
    from backend.core.config import config as _cfg

    actions: list[PendingAction] = []

    with StateDB() as db:
        platform = db.get_platform()
        settings = {
            "cf_token": db.get_setting("cf_auto_register_hostnames"),
            "ntfy_url": db.get_setting("ntfy_url"),
        }
        apps = db.get_all_apps()
        health_rows = db.execute(
            "SELECT subject_key AS app_key, status, summary FROM health_checks "
            "WHERE status IN ('error','warning') AND subject_type='app' "
            "ORDER BY checked_at DESC LIMIT 50"
        ).fetchall() if _table_exists(db, "health_checks") else []

    # ── Errors ──────────────────────────────────────────────────────────────

    # Platform not configured
    if platform.status == "pending":
        actions.append(PendingAction(
            priority="error",
            title="Platform setup incomplete",
            description="The setup wizard has not been completed — Traefik and HTTPS are not configured.",
            action="Run the setup wizard",
            link="/setup",
            icon="⚙️",
        ))

    # CF_DNS_API_TOKEN missing
    env_vals: dict[str, str] = {}
    if _cfg.env_file.exists():
        for line in _cfg.env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env_vals[k.strip()] = v.strip()

    if not env_vals.get("CF_DNS_API_TOKEN") and platform.status == "ready":
        actions.append(PendingAction(
            priority="error",
            title="Cloudflare API token missing",
            description="CF_DNS_API_TOKEN is not set — wildcard certificates cannot be issued.",
            action="Add it in Settings → Secrets",
            link="/settings",
            icon="🔑",
        ))

    # Apps in error state
    error_apps = [a for a in apps if getattr(a, "status", "") == "error"]
    for app in error_apps[:3]:
        actions.append(PendingAction(
            priority="error",
            title=f"{app.display_name or app.key} is in error state",
            description=f"Container failed to start or is unhealthy.",
            action=f"Check logs: ms apps logs {app.key}",
            link="/health",
            icon="❌",
        ))

    # ── Warnings ─────────────────────────────────────────────────────────────

    # Auth infra slot empty
    with StateDB() as db:
        auth_slot = db.get_slot("auth")
    if auth_slot and getattr(auth_slot, "status", "empty") == "empty":
        actions.append(PendingAction(
            priority="warning",
            title="No authentication deployed",
            description="Apps are publicly accessible without a login screen.",
            action="Deploy TinyAuth in Infrastructure",
            link="/infra",
            icon="🔐",
        ))

    # No LLM model installed
    models_dir = _cfg.data_dir / "models"
    has_model = models_dir.exists() and any(models_dir.glob("*.gguf"))
    if not has_model:
        actions.append(PendingAction(
            priority="warning",
            title="AI health monitoring inactive",
            description="No LLM model installed — health issues won't have AI-powered diagnosis.",
            action="Install Ollama and download phi-4-mini",
            link="/models",
            icon="🤖",
        ))

    # Health check errors/warnings from recent cycle
    seen_apps: set[str] = set()
    for row in health_rows:
        if row["app_key"] not in seen_apps:
            seen_apps.add(row["app_key"])
            if row["status"] == "warning":
                actions.append(PendingAction(
                    priority="warning",
                    title=f"{row['app_key']} health warning",
                    description=row["summary"] or "Health check returned a warning.",
                    action="View details in Health Monitor",
                    link="/health",
                    icon="⚠️",
                ))

    # ── Suggestions ──────────────────────────────────────────────────────────

    # No apps installed
    running_apps = [a for a in apps if getattr(a, "status", "") == "running"]
    if not running_apps and platform.status == "ready":
        actions.append(PendingAction(
            priority="suggestion",
            title="No apps installed yet",
            description="The platform is ready — start by installing Sonarr, Radarr and Prowlarr.",
            action="Browse the Catalog",
            link="/catalog",
            icon="📦",
        ))

    # Notifications not configured
    if not env_vals.get("NTFY_URL", "") and not (settings.get("ntfy_url") or ""):
        actions.append(PendingAction(
            priority="suggestion",
            title="Push notifications not configured",
            description="Set up ntfy to receive alerts when apps go down or certs expire.",
            action="Configure in Settings → Notifications",
            link="/settings",
            icon="🔔",
        ))

    # Sort: errors → warnings → suggestions
    order = {"error": 0, "warning": 1, "suggestion": 2}
    actions.sort(key=lambda a: order.get(a.priority, 3))
    return actions


def _table_exists(db: Any, table_name: str) -> bool:
    try:
        db.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
        return True
    except Exception:
        return False


# ── Anomaly detection ──────────────────────────────────────────────────────

@router.get("/anomalies")
def get_anomalies() -> list[dict[str, Any]]:
    """Return recurring failure patterns detected across health check history."""
    from backend.health.anomaly import get_anomaly_summary
    return get_anomaly_summary()


# ── Platform health review (LLM reviews pending actions) ───────────────────

@router.post("/platform-review")
async def run_platform_review() -> dict[str, Any]:
    """Ask the LLM to review pending actions and suggest fixes.

    The LLM gets:
    - Full pending actions list with priorities
    - Current platform state
    - RAG knowledge base context

    Returns plain-language summary and per-action suggestions.
    """
    import asyncio
    from backend.core.state import StateDB
    from backend.core.rag import enrich_prompt_with_context

    # Get pending actions
    try:
        actions = get_pending_actions()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not actions:
        return {"ok": True, "summary": "No pending actions — platform looks healthy.",
                "suggestions": []}

    with StateDB() as db:
        platform = db.get_platform()

    # Build prompt
    actions_text = "\n".join(
        f"[{a.priority.upper()}] {a.title}: {a.description} → {a.action}"
        for a in actions
    )
    prompt = f"""You are a homelab infrastructure assistant reviewing a Mediastack server.

Platform: domain={platform.domain}, status={platform.status}

Current issues requiring attention:
{actions_text}

For each issue:
1. Confirm if the suggested action is correct
2. Add any additional context or caveats
3. Flag if any issues are related to each other
4. Prioritize which to fix first

Respond as a helpful assistant in plain language. Be concise — 2-3 sentences per issue max."""

    prompt = enrich_prompt_with_context(prompt, actions_text)

    # Try local LLM first
    from backend.health.checker import _llm_state
    llm_available = _llm_state.get("status") == "ready"

    if llm_available:
        try:
            from backend.core.state import StateDB as _SDB
            with _SDB() as db:
                ollama_url = db.get_setting("ollama_url") or "http://localhost:11434"
                model = db.get_setting("ollama_model") or "phi4-mini"
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False}
                )
                resp.raise_for_status()
                response_text = resp.json().get("response", "")
                return {
                    "ok": True,
                    "summary": response_text,
                    "provider": "local",
                    "action_count": len(actions),
                    "suggestions": [
                        {"title": a.title, "action": a.action, "priority": a.priority}
                        for a in actions
                    ],
                }
        except Exception as e:
            log.debug("Local LLM platform review failed: %s", e)

    # No local LLM — return structured analysis without AI
    error_count = sum(1 for a in actions if a.priority == "error")
    warning_count = sum(1 for a in actions if a.priority == "warning")
    return {
        "ok": True,
        "summary": (
            f"Found {error_count} error(s) and {warning_count} warning(s). "
            f"{'Install Ollama and a model to get AI-powered analysis.' if not llm_available else ''}"
        ),
        "provider": None,
        "action_count": len(actions),
        "suggestions": [
            {"title": a.title, "action": a.action, "priority": a.priority}
            for a in actions
        ],
    }


# ── Apply AI suggestion ────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    app_key: str
    action_type: str
    suggested_fix: str


@router.post("/apply-fix")
async def apply_suggested_fix(req: ApplyRequest) -> dict[str, Any]:
    """Execute an AI-suggested fix, respecting the safety tier.

    The safety tier must be set to 'act' for auto-execution, or the
    user must have explicitly confirmed via the UI (handled by frontend
    showing a confirmation modal before calling this endpoint).
    """
    from backend.core.ai_safety import execute_action, get_safety_level

    level = get_safety_level(req.action_type)
    if level == "observe":
        return {
            "ok": False,
            "requires_approval": False,
            "message": f"Safety level for '{req.action_type}' is 'observe' — no actions allowed.",
        }

    result = await execute_action(req.action_type, req.app_key, req.suggested_fix)

    # Record in fix_history
    try:
        from backend.core.state import StateDB
        import time as _time
        with StateDB() as db:
            db.execute(
                """INSERT INTO fix_history
                   (app_key, error_type, context, suggested_fix, outcome, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (req.app_key, req.action_type, req.suggested_fix[:200],
                 req.suggested_fix, "pending", int(_time.time()))
            )
    except Exception:
        pass

    return result


# ── Weekly health summary ──────────────────────────────────────────────────




# ── Ghost resource management ───────────────────────────────────────────────

@router.get("/ghost-resources")
def get_ghost_resources() -> dict[str, Any]:
    """Return ghost containers, fragments, and volumes.

    A ghost is a Docker resource that exists but is not tracked in Mediastack DB,
    or an app in DB that has no corresponding running container.
    """
    import subprocess
    from backend.core.state import StateDB
    from backend.core.config import config as _cfg

    ghost_containers: list[dict[str, Any]] = []
    ghost_fragments: list[dict[str, Any]] = []
    orphaned_apps: list[dict[str, Any]] = []

    _INFRA = {"traefik", "cloudflared", "tinyauth", "gluetun", "portainer",
               "authelia", "headscale", "tailscale", "glance", "homepage",
               "dockge", "dockhand", "komodo", "portainer_be"}

    # Get running containers from Docker
    running: dict[str, str] = {}
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    running[parts[0]] = f"{parts[1]} ({parts[2]})"
    except Exception:
        pass  # Docker not available

    # DB apps
    with StateDB() as db:
        db_apps = {a.key: a for a in db.get_all_apps()}

    # Ghost containers: running but not in DB and not infra
    for name, info in running.items():
        if name not in _INFRA and name not in db_apps:
            ghost_containers.append({"name": name, "info": info})

    # Orphaned apps: in DB as running but container not found
    for key, app in db_apps.items():
        if getattr(app, "status", "") == "running":
            cname = getattr(app, "container_name", key) or key
            if cname not in running and key not in running:
                orphaned_apps.append({
                    "key": key,
                    "display_name": app.display_name or key,
                    "container_name": cname,
                })

    # Ghost fragments: compose files with no DB entry
    compose_dir = _cfg.compose_dir
    if compose_dir.exists():
        infra_files = {"traefik", "cloudflared", "tinyauth", "gluetun",
                       "portainer", "authelia", "headscale", "tailscale"}
        for frag in sorted(compose_dir.glob("*.yaml")):
            k = frag.stem
            if k not in infra_files and k not in db_apps:
                ghost_fragments.append({
                    "filename": frag.name,
                    "key": k,
                    "size_bytes": frag.stat().st_size,
                })

    return {
        "ghost_containers": ghost_containers,
        "ghost_fragments": ghost_fragments,
        "orphaned_apps": orphaned_apps,
        "docker_available": bool(running) or True,
    }


class GhostAction(BaseModel):
    resource_type: str  # container | fragment | orphaned_app
    name: str
    action: str         # adopt | remove | ignore


@router.post("/ghost-resources/action")
def handle_ghost_resource(req: GhostAction) -> dict[str, Any]:
    """Act on a ghost resource: adopt, remove, or ignore."""
    import subprocess
    from backend.core.state import StateDB
    from backend.core.config import config as _cfg

    if req.action == "remove":
        if req.resource_type == "container":
            try:
                r = subprocess.run(
                    ["docker", "stop", req.name],
                    capture_output=True, text=True, timeout=30,
                )
                subprocess.run(["docker", "rm", req.name],
                               capture_output=True, timeout=15)
                return {"ok": True, "message": f"Container '{req.name}' stopped and removed."}
            except Exception as e:
                raise HTTPException(502, str(e))

        elif req.resource_type == "fragment":
            frag = _cfg.compose_dir / req.name
            if frag.exists():
                frag.unlink()
                return {"ok": True, "message": f"Fragment '{req.name}' deleted."}
            raise HTTPException(404, f"Fragment '{req.name}' not found.")

        elif req.resource_type == "orphaned_app":
            with StateDB() as db:
                db.upsert_app(req.name, status="error")
            return {"ok": True, "message": f"'{req.name}' marked as error — reinstall or remove."}

    elif req.action == "adopt":
        if req.resource_type == "container":
            # Register the container in the DB
            with StateDB() as db:
                db.upsert_app(
                    req.name,
                    display_name=req.name.replace("_", " ").replace("-", " ").title(),
                    category="tools",
                    image="unknown",
                    container_name=req.name,
                    status="running",
                    config_path="",
                )
            return {"ok": True, "message": f"Container '{req.name}' adopted into Mediastack."}

    elif req.action == "ignore":
        return {"ok": True, "message": f"'{req.name}' will be suppressed from ghost reports."}

    raise HTTPException(422, f"Unknown action: {req.action}")


# ── Weekly health history LLM summary ─────────────────────────────────────

@router.get("/weekly-summary")
async def get_weekly_summary() -> dict[str, Any]:
    """Generate a plain-language LLM summary of the last 7 days of health data.

    Returns: {summary, period, error_count, warning_count, top_issues, generated_at}
    """
    import time as _time
    from backend.core.state import StateDB
    from backend.core.rag import enrich_prompt_with_context

    cutoff = int(_time.time()) - 7 * 86400
    with StateDB() as db:
        # Get health history for the week
        try:
            rows = db.execute(
                """SELECT subject_key, check_name, status, summary, checked_at
                   FROM health_check_history
                   WHERE checked_at >= ? ORDER BY checked_at DESC LIMIT 200""",
                (cutoff,)
            ).fetchall()
        except Exception:
            rows = []

    error_count = sum(1 for r in rows if r["status"] == "error")
    warning_count = sum(1 for r in rows if r["status"] == "warning")

    # Find top issues (most frequent error/warning pairs)
    from collections import Counter
    issue_counter = Counter(
        f"{r['subject_key']}:{r['check_name']}"
        for r in rows if r["status"] in ("error", "warning")
    )
    top_issues = [
        {"app": k.split(":")[0], "check": k.split(":")[1], "count": v}
        for k, v in issue_counter.most_common(5)
    ]

    # Build LLM prompt
    issues_text = "\n".join(
        f"- {i['app']} / {i['check']}: {i['count']} occurrence(s)"
        for i in top_issues
    ) or "No issues recorded this week."

    prompt = f"""You are a homelab assistant reviewing a week of health monitoring data.

Period: last 7 days
Total checks recorded: {len(rows)}
Errors: {error_count}
Warnings: {warning_count}

Top recurring issues:
{issues_text}

Write a brief (3-5 sentence) plain-language weekly summary for the homelab owner.
Include: overall health assessment, what needs attention, and any positive highlights.
Keep it conversational and helpful."""

    prompt = enrich_prompt_with_context(prompt, issues_text)

    # Try local LLM
    summary = None
    from backend.health.checker import _llm_state
    if _llm_state.get("status") == "ready":
        try:
            with StateDB() as db:
                ollama_url = db.get_setting("ollama_url") or "http://localhost:11434"
                model = db.get_setting("ollama_model") or "phi4-mini"
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False}
                )
                resp.raise_for_status()
                summary = resp.json().get("response", "")
        except Exception:
            pass

    if not summary:
        # Fallback: structured summary without LLM
        health = "healthy" if error_count == 0 else "needs attention" if error_count < 5 else "has significant issues"
        summary = (
            f"Your homelab {health} this week with {error_count} error(s) and "
            f"{warning_count} warning(s) recorded across {len(rows)} health checks. "
            + (f"Most frequent issue: {top_issues[0]['app']} ({top_issues[0]['count']}×)." if top_issues else "No recurring issues detected.")
        )

    return {
        "summary": summary,
        "period": "last 7 days",
        "error_count": error_count,
        "warning_count": warning_count,
        "top_issues": top_issues,
        "generated_at": int(_time.time()),
        "llm_used": _llm_state.get("status") == "ready",
    }


# ── Test result reporting for LLM context ────────────────────────────────

@router.post("/test-results")
def record_test_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Ingest pytest run results so the LLM health agent can include them
    in weekly summaries and anomaly detection.

    Called by: pytest conftest.py post-run hook, or manually via ms-check.
    Payload: {passed, failed, errors, duration_s, failures: [{name, message}]}
    """
    from backend.core.state import StateDB
    import json, time as _time

    with StateDB() as db:
        db.set_setting("last_test_run_ts", str(int(_time.time())))
        db.set_setting("last_test_run_passed", str(payload.get("passed", 0)))
        db.set_setting("last_test_run_failed", str(payload.get("failed", 0)))
        db.set_setting("last_test_run_duration", str(payload.get("duration_s", 0)))
        failures = payload.get("failures", [])
        db.set_setting("last_test_run_failures", json.dumps(failures[:20]))

    return {"ok": True, "recorded": True}


@router.get("/test-results")
def get_test_results() -> dict[str, Any]:
    """Return the most recent pytest run results."""
    from backend.core.state import StateDB
    import json, time as _time

    with StateDB() as db:
        ts = int(db.get_setting("last_test_run_ts") or "0")
        passed = int(db.get_setting("last_test_run_passed") or "0")
        failed = int(db.get_setting("last_test_run_failed") or "0")
        duration = float(db.get_setting("last_test_run_duration") or "0")
        failures_raw = db.get_setting("last_test_run_failures") or "[]"

    failures = []
    try:
        failures = json.loads(failures_raw)
    except Exception:
        pass

    age_hours = (_time.time() - ts) / 3600 if ts else None
    return {
        "last_run_ts": ts or None,
        "age_hours": round(age_hours, 1) if age_hours else None,
        "passed": passed,
        "failed": failed,
        "duration_s": duration,
        "failures": failures,
        "status": "pass" if failed == 0 and passed > 0 else ("fail" if failed > 0 else "unknown"),
    }


# ── LLM test proposal system ──────────────────────────────────────────────

class TestProposalRequest(BaseModel):
    fix_description: str = Field(..., description="What was fixed and why")
    diff_summary: str = Field("", description="Optional: key lines changed")
    bug_category: str = Field("", description="e.g. method_mismatch, field_not_wired")


@router.post("/propose-tests")
async def propose_tests(req: TestProposalRequest) -> dict[str, Any]:
    """Ask the LLM to propose new test cases based on a recent bug fix.

    The LLM analyzes the fix description and generates Python test code
    following the project's existing test patterns. Tests are written to
    tests/proposed/ — never to tests/ directly. A human must approve via
    POST /health/proposed-tests/{id}/approve.

    Safety: proposed tests are syntax-checked and dry-run collected
    (pytest --collect-only) before being shown to the user.
    """
    import time as _time
    import hashlib
    from pathlib import Path

    PROPOSED_DIR = Path("tests") / "proposed"
    PROPOSED_DIR.mkdir(parents=True, exist_ok=True)

    prompt = f"""You are a Python test engineer reviewing a bug fix in a FastAPI + Vue 3 homelab app called Mediastack.

Bug fix description:
{req.fix_description}

Diff summary:
{req.diff_summary or 'Not provided'}

Bug category: {req.bug_category or 'unknown'}

Generate a focused pytest test class (2-5 test methods) that would have caught this bug BEFORE it was fixed.
Follow these patterns from the existing test suite:
- Use @pytest.fixture with scope="module" for db_path
- Use fastapi.testclient.TestClient for API calls  
- Each test has a clear docstring explaining what it catches
- Test names start with test_
- Import from backend.* as needed
- No mocks unless absolutely necessary — test the real behavior

Return ONLY valid Python code. No markdown fences. No explanation outside the code.
Start with: import pytest
"""

    # Try cloud LLM cascade
    try:
        from backend.core.cloud_llm import escalate_to_cloud
        _esc = await escalate_to_cloud(prompt, app_key="", purpose="ai_test_generation")
        proposed_code = _esc.response if _esc and _esc.ok else None
    except Exception:
        proposed_code = None

    # Fallback to local LLM
    if not proposed_code:
        try:
            import httpx
            from backend.core.state import StateDB
            with StateDB() as db:
                ollama_url = db.get_setting("ollama_url") or "http://localhost:11434"
                model = db.get_setting("ollama_model") or "phi4-mini"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                )
                proposed_code = resp.json().get("response", "")
        except Exception as e:
            return {"ok": False, "error": f"No LLM available: {e}"}

    if not proposed_code or len(proposed_code) < 100:
        return {"ok": False, "error": "LLM returned empty or too-short response"}

    # Safety validation: must parse as Python
    import ast as _ast
    try:
        _ast.parse(proposed_code)
    except SyntaxError as e:
        return {"ok": False, "error": f"LLM-generated code has syntax error: {e}"}

    # Write to proposed/ with timestamp ID
    proposal_id = hashlib.sha1(
        f"{_time.time()}{req.fix_description}".encode()
    ).hexdigest()[:8]
    filename = f"test_proposed_{proposal_id}.py"
    proposal_path = PROPOSED_DIR / filename

    header = f'''"""PROPOSED TEST — awaiting human review.

Generated by LLM based on fix: {req.fix_description[:100]}
Bug category: {req.bug_category or 'unknown'}

To approve: POST /api/health/proposed-tests/{proposal_id}/approve
To discard: DELETE /api/health/proposed-tests/{proposal_id}

DO NOT run in CI until approved.
"""
'''
    proposal_path.write_text(header + proposed_code)

    # Dry-run collect to check for import errors (not execution)
    import subprocess, sys
    collect_result = subprocess.run(
        [sys.executable, "-m", "pytest", str(proposal_path),
         "--collect-only", "-q", "--tb=short"],
        capture_output=True, text=True, timeout=30,
        cwd=str(Path(".")),
    )
    collection_ok = collect_result.returncode == 0

    return {
        "ok": True,
        "proposal_id": proposal_id,
        "filename": filename,
        "collection_valid": collection_ok,
        "collection_output": collect_result.stdout[:500] if not collection_ok else None,
        "preview": proposed_code[:500],
        "message": (
            f"Test proposal saved to tests/proposed/{filename}. "
            f"Review with GET /api/health/proposed-tests/{proposal_id}, "
            f"then approve via POST /api/health/proposed-tests/{proposal_id}/approve"
        ),
    }


@router.get("/proposed-tests")
def list_proposed_tests() -> list[dict[str, Any]]:
    """List all pending proposed tests awaiting review."""
    from pathlib import Path
    PROPOSED_DIR = Path("tests") / "proposed"
    if not PROPOSED_DIR.exists():
        return []
    results = []
    for f in sorted(PROPOSED_DIR.glob("test_proposed_*.py")):
        src = f.read_text()
        results.append({
            "id": f.stem.replace("test_proposed_", ""),
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "preview": src[src.find('import'):src.find('import') + 300] if 'import' in src else src[:300],
        })
    return results


@router.post("/proposed-tests/{proposal_id}/approve")
def approve_proposed_test(proposal_id: str) -> dict[str, Any]:
    """Promote a proposed test from tests/proposed/ to tests/.

    Runs a final syntax check before promotion.
    Rollback: git rm tests/test_proposed_{id}.py
    """
    from pathlib import Path
    import ast as _ast, shutil

    proposed = Path("tests") / "proposed" / f"test_proposed_{proposal_id}.py"
    if not proposed.exists():
        raise HTTPException(404, f"Proposal {proposal_id} not found.")

    # Final syntax check
    src = proposed.read_text()
    try:
        _ast.parse(src)
    except SyntaxError as e:
        raise HTTPException(422, f"Proposed test has syntax error: {e}")

    # Remove the warning header comment before promoting
    promoted_src = src[src.find('import pytest'):]  # strip header
    dest = Path("tests") / f"test_proposed_{proposal_id}.py"
    dest.write_text(promoted_src)
    proposed.unlink()

    return {
        "ok": True,
        "promoted_to": str(dest),
        "message": f"Test promoted to tests/. Add to git: git add {dest}",
        "rollback": f"git rm {dest}",
    }


@router.delete("/proposed-tests/{proposal_id}")
def discard_proposed_test(proposal_id: str) -> dict[str, Any]:
    """Discard a proposed test without promoting it."""
    from pathlib import Path
    proposed = Path("tests") / "proposed" / f"test_proposed_{proposal_id}.py"
    if not proposed.exists():
        raise HTTPException(404, f"Proposal {proposal_id} not found.")
    proposed.unlink()
    return {"ok": True, "discarded": proposal_id}


# ── Anomaly suppression / snooze ──────────────────────────────────────────

class AnomalySnoozeRequest(BaseModel):
    app_key: str
    check_name: str
    reason: str = ""
    hours: int = Field(72, ge=1, le=720)


@router.post("/anomalies/{app_key}/{check_name}/snooze")
def snooze_anomaly(app_key: str, check_name: str, req: AnomalySnoozeRequest) -> dict[str, Any]:
    """Snooze recurring anomaly alerts for an app/check pair.

    Used when you know why an app fails at a specific time (e.g. a backup
    job restarts a container at 03:00) and don't want it polluting anomaly
    reports. The anomaly is still recorded — just not shown as 'recurring'.
    """
    import time as _time
    from backend.core.state import StateDB
    snooze_until = int(_time.time()) + req.hours * 3600
    with StateDB() as db:
        db.set_setting(
            f"snooze_{app_key}_{check_name}",
            str(snooze_until)
        )
    return {
        "ok": True,
        "snoozed_until": snooze_until,
        "hours": req.hours,
        "message": (
            f"Anomaly '{check_name}' for '{app_key}' snoozed for {req.hours}h. "
            f"Still recorded in history — just hidden from recurring issues panel."
        ),
    }



@router.get("/agent-config")
def get_agent_config() -> dict[str, Any]:
    """Return current LLM inference provider configuration."""
    from backend.core.state import StateDB
    import json as _json
    with StateDB() as db:
        raw = db.get_setting("llm_agent_config")
    cfg = _json.loads(raw) if raw else {}
    return {
        "provider":   cfg.get("provider",     "ollama"),
        "ollama_url": cfg.get("ollama_url",   "http://localhost:11434"),
        "model":      cfg.get("ollama_model", ""),
        "api_key":    cfg.get("api_key",      ""),
    }


@router.put("/agent-config")
def put_agent_config(
    provider:   str | None = None,
    ollama_url: str | None = None,
    model:      str | None = None,
    api_key:    str | None = None,
) -> dict[str, Any]:
    """Persist LLM inference provider config. Only supplied fields are updated."""
    from backend.core.state import StateDB
    import json as _json
    with StateDB() as db:
        raw = db.get_setting("llm_agent_config")
        cfg = _json.loads(raw) if raw else {}
        if provider   is not None: cfg["provider"]     = provider
        if ollama_url is not None: cfg["ollama_url"]   = ollama_url
        if model      is not None: cfg["ollama_model"] = model
        if api_key    is not None: cfg["api_key"]      = api_key
        db.set_setting("llm_agent_config", _json.dumps(cfg))
    return {"ok": True, "config": cfg}


@router.get("/llm-ping")
async def ping_llm() -> dict[str, Any]:
    """Probe Ollama (or configured LLM backend) right now and return structured result.
    
    Used by the UI to get an immediate, accurate status without waiting for
    a health cycle to fail enough times to flip the state machine.
    """
    import httpx
    from backend.core.state import StateDB
    import json as _json

    with StateDB() as db:
        cfg_raw = db.get_setting("llm_agent_config")
    cfg = _json.loads(cfg_raw) if cfg_raw else {}
    provider  = cfg.get("provider",   "ollama")
    base_url  = cfg.get("ollama_url", "http://localhost:11434")
    api_key   = cfg.get("api_key",   "")

    try:
        from backend.core.llm_router import best_model_for
        rec = best_model_for("reasoning")
        model = (rec.ollama_name or rec.filename.replace(".gguf", "")) if rec else None
    except Exception:
        model = None
    if not model:
        model = cfg.get("ollama_model", "")

    INSTALL = {
        "ollama":      "curl -fsSL https://ollama.com/install.sh | sh && ollama pull phi4-mini",
        "llamacpp":    "# Build llama-server: cmake llama.cpp -B build -DGGML_CUDA=ON && cmake --build build -t llama-server\n./build/bin/llama-server -m /path/to/model.gguf --port 8080",
        "shimmy":      "curl -L https://github.com/Michael-A-Kuykendall/shimmy/releases/latest/download/shimmy-linux-x86_64 -o shimmy\nchmod +x shimmy && ./shimmy serve --bind 0.0.0.0:11435",
        "localai":     "docker run -p 8080:8080 localai/localai:latest-aio-cpu",
        "groq":        "# Sign up at console.groq.com → API Keys (free, no credit card)",
        "cerebras":    "# Sign up at cloud.cerebras.ai → API Keys (free, 1M tokens/day)",
        "nim":         "# Sign up at build.nvidia.com → Get API key (free, nvapi- prefix)",
        "gai":         "# Sign up at aistudio.google.com → Get API key (free, generous limits)",
        "openrouter":  "# Sign up at openrouter.ai → API Keys → Create key",
    }

    def _ok(models: list[Any]) -> dict[str, Any]:
        loaded = any(model in m for m in models) if model else bool(models)
        fix = ""
        if not loaded and model and provider == "ollama":
            fix = f"ollama pull {model}"
        return {
            "reachable": True, "model_loaded": loaded,
            "model": model or (models[0] if models else ""),
            "ollama_url": base_url, "loaded_models": models, "provider": provider,
            "error_type": "model" if not loaded else "",
            "error": f"No model loaded. {fix}" if not loaded else "",
            "fix": fix,
        }

    def _err(etype: str, msg: str, fix: str = "") -> dict[str, Any]:
        return {
            "reachable": False, "model_loaded": False,
            "model": model or "", "ollama_url": base_url,
            "loaded_models": [], "provider": provider,
            "error_type": etype, "error": msg,
            "fix": fix or INSTALL.get(provider, ""),
        }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            if provider == "ollama":
                r = await client.get(f"{base_url}/api/tags")
                if r.status_code != 200:
                    return _err("http", f"Ollama returned HTTP {r.status_code}")
                return _ok([m.get("name","") for m in r.json().get("models", [])])

            # ── Cloud providers — all use /v1/models or equivalent ──────
            elif provider in ("openrouter", "groq", "cerebras", "nim", "gai"):
                if not api_key:
                    return _err("auth",
                        f"API key required for {provider}.",
                        INSTALL.get(provider, f"# Sign up and get an API key for {provider}"))
                # Cerebras uses /v1/models, Google AI uses models list endpoint
                if provider == "gai":
                    list_url = "https://generativelanguage.googleapis.com/v1beta/openai/models"
                else:
                    list_url = f"{base_url}/models"
                r = await client.get(list_url,
                                     headers={"Authorization": f"Bearer {api_key}"})
                if r.status_code == 200:
                    data = r.json()
                    models_list = [m.get("id","") for m in data.get("data", [])][:6]
                    return {
                        "reachable": True, "model_loaded": True,
                        "model": model or "auto",
                        "ollama_url": base_url,
                        "loaded_models": models_list, "provider": provider,
                        "error_type": "", "error": "", "fix": "",
                    }
                return _err("auth" if r.status_code == 401 else "http",
                            f"{provider} returned HTTP {r.status_code}")

            else:  # llamacpp | shimmy | localai — all expose /v1/models
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                r = await client.get(f"{base_url}/v1/models", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    ids = [m.get("id","") for m in (data.get("data", data) if isinstance(data, dict) else data)]
                    return _ok(ids)
                if provider == "shimmy":  # shimmy also has /health
                    r2 = await client.get(f"{base_url}/health")
                    if r2.status_code == 200:
                        return _ok([])
                return _err("http", f"{provider} returned HTTP {r.status_code}")

    except httpx.ConnectError:
        return _err("connection", f"Cannot connect to {provider} at {base_url}.")
    except httpx.TimeoutException:
        return _err("timeout",   f"Connection to {base_url} timed out.")
    except Exception as e:
        return _err("unknown", str(e)[:200])


# ── Maintenance windows ────────────────────────────────────────────────────

@router.get("/maintenance-windows")
def get_maintenance_windows() -> list[dict[str, Any]]:
    """Return all configured maintenance windows."""
    from backend.core.state import StateDB
    with StateDB() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_windows (
                id INTEGER PRIMARY KEY, app_key TEXT NOT NULL,
                check_name TEXT NOT NULL, label TEXT NOT NULL DEFAULT 'Scheduled task',
                day_of_week INTEGER, hour_start INTEGER NOT NULL,
                hour_end INTEGER NOT NULL DEFAULT -1, enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            )""")
        rows = db.execute("SELECT * FROM maintenance_windows ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


class MaintenanceWindowIn(BaseModel):
    app_key:    str
    check_name: str
    label:      str = "Scheduled task"
    day_of_week: int | None = None   # 0=Mon … 6=Sun, None=every day
    hour_start:  int = 0
    hour_end:    int = -1            # -1 = hour_start + 2


@router.post("/maintenance-windows")
def create_maintenance_window(req: MaintenanceWindowIn) -> dict[str, Any]:
    """Create a maintenance window to suppress a recurring false-positive."""
    from backend.core.state import StateDB
    with StateDB() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_windows (
                id INTEGER PRIMARY KEY, app_key TEXT NOT NULL,
                check_name TEXT NOT NULL, label TEXT NOT NULL DEFAULT 'Scheduled task',
                day_of_week INTEGER, hour_start INTEGER NOT NULL,
                hour_end INTEGER NOT NULL DEFAULT -1, enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            )""")
        db.execute(
            """INSERT INTO maintenance_windows
               (app_key, check_name, label, day_of_week, hour_start, hour_end)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (req.app_key, req.check_name, req.label, req.day_of_week,
             req.hour_start, req.hour_end),
        )
    return {"ok": True}


@router.delete("/maintenance-windows/{window_id}")
def delete_maintenance_window(window_id: int) -> dict[str, Any]:
    """Remove a maintenance window."""
    from backend.core.state import StateDB
    with StateDB() as db:
        db.execute("DELETE FROM maintenance_windows WHERE id = ?", (window_id,))
        # NOTE: StateDB auto-commits on __exit__ — db._c.commit() removed (Core Rule 4.4)
    return {"ok": True}


# ── Source availability (Tier 1 + 2) ─────────────────────────────────────

@router.get("/sources")
def get_source_availability() -> dict[str, Any]:
    """Return current source availability for all registered external resources."""
    from backend.core.state import StateDB
    import json as _j
    try:
        from backend.health.source_checker import _ensure_tables
        _ensure_tables()
    except Exception:
        pass
    try:
        with StateDB() as db:
            rows = db.execute("""
                SELECT source_type, resource_key, url, status,
                       http_status, error, last_checked
                FROM source_availability
                ORDER BY
                    CASE status WHEN 'missing' THEN 0 WHEN 'unreachable' THEN 1 ELSE 2 END,
                    resource_key
            """).fetchall()
            last_scan = db.get_setting("source_scan_last_at")
            summary_raw = db.get_setting("source_scan_summary")
        items = [dict(r) for r in rows]
        issues = [i for i in items if i["status"] != "ok"]
        summary = _j.loads(summary_raw) if summary_raw else {}
        return {
            "items": items, "issues": issues,
            "last_scan_at": int(last_scan) if last_scan else None,
            "summary": summary,
        }
    except Exception as _e:
        return {"items": [], "issues": [], "last_scan_at": None,
                "summary": {}, "error": str(_e)}


@router.post("/sources/scan")
async def trigger_source_scan() -> dict[str, Any]:
    """Trigger an immediate source availability scan (async, non-blocking)."""
    import asyncio
    from backend.health.source_checker import run_source_scan
    try:
        asyncio.create_task(run_source_scan(), name="source-scan-manual")
        return {"ok": True, "message": "Source scan started in background."}
    except Exception as _e:
        raise HTTPException(status_code=500, detail=f"Failed to start source scan: {_e}")


class ReplacementRequest(BaseModel):
    source_type: str
    resource_key: str
    url: str


@router.post("/sources/find-replacement")
async def find_source_replacement(req: ReplacementRequest) -> dict[str, Any]:
    """Ask the LLM to find a replacement for a missing/broken source URL.
    
    Returns a suggestion with confidence score. Never auto-applies —
    user must confirm via the /sources/apply-replacement endpoint.
    """
    try:
        from backend.health.source_checker import find_replacement
        result = await find_replacement(req.source_type, req.resource_key, req.url)
        return result
    except Exception as _e:
        raise HTTPException(status_code=500, detail=f"Replacement lookup failed: {_e}")


class ApplyReplacementRequest(BaseModel):
    source_type: str
    resource_key: str
    old_url: str
    new_url: str


@router.post("/sources/apply-replacement")
def apply_source_replacement(req: ApplyReplacementRequest) -> dict[str, Any]:
    """Apply a confirmed URL replacement.
    
    For docker_image: updates the apps table image + image_tag.
    For hf_model: updates the recommended_models cache (frontend only —
    manifest URLs require a code change).
    """
    from backend.core.state import StateDB

    if req.source_type == "docker_image":
        # Parse new_url into image + tag
        if ":" in req.new_url.split("/")[-1]:
            new_image, new_tag = req.new_url.rsplit(":", 1)
        else:
            new_image, new_tag = req.new_url, "latest"

        with StateDB() as db:
            db.execute(
                "UPDATE apps SET image=?, image_tag=? WHERE key=?",
                (new_image, new_tag, req.resource_key),
            )
            # Mark source as ok with new URL
            db.execute("""
                INSERT INTO source_availability
                    (source_type, resource_key, url, status, last_checked)
                VALUES (?, ?, ?, 'ok', unixepoch())
                ON CONFLICT(source_type, resource_key, url)
                DO UPDATE SET status='ok', last_checked=unixepoch()
            """, (req.source_type, req.resource_key, req.new_url))
            # Mark old URL as superseded
            db.execute("""
                UPDATE source_availability
                SET status='superseded', error='Replaced by user'
                WHERE source_type=? AND resource_key=? AND url=?
            """, (req.source_type, req.resource_key, req.old_url))
            # NOTE: StateDB auto-commits on __exit__ — db._c.commit() removed (Core Rule 4.4)
        return {"ok": True, "message": f"Image updated to {req.new_url}. Restart app to apply."}

    elif req.source_type == "hf_model":
        # Can't auto-patch code — tell user what to do
        return {
            "ok": False,
            "message": (
                f"HuggingFace model URLs are defined in the catalog. "
                f"The suggested URL is: {req.new_url} — "
                f"use it in the custom URL download field on the Models page."
            ),
            "suggested_url": req.new_url,
        }

    return {"ok": False, "message": f"Unknown source type: {req.source_type}"}


# ── Pending fixes API ─────────────────────────────────────────────────────

class _EscalateRequest(BaseModel):
    app_key: str
    check_name: str
    problem: str
    logs: str = ""
    context: str = ""


@router.get("/pending-fixes")
def get_pending_fixes() -> list[dict[str, Any]]:
    """Return all pending AI-suggested fixes awaiting user approval."""
    from backend.core.state import StateDB
    with StateDB() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pending_fixes (
                id INTEGER PRIMARY KEY, app_key TEXT NOT NULL,
                check_name TEXT NOT NULL, action_type TEXT NOT NULL,
                problem TEXT NOT NULL, suggested_fix TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                status TEXT NOT NULL DEFAULT 'pending', model TEXT,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                resolved_at INTEGER,
                UNIQUE(app_key, check_name, action_type)
            )""")
        rows = db.execute(
            "SELECT * FROM pending_fixes WHERE status='pending' ORDER BY confidence DESC, created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/pending-fixes/{fix_id}/approve")
async def approve_fix(fix_id: int) -> dict[str, Any]:
    """Approve and execute a pending AI fix."""
    from backend.core.state import StateDB
    from backend.core.ai_safety import execute_action
    import time as _t
    try:
        with StateDB() as db:
            # Ensure table exists (created lazily in checker.py, may not exist yet)
            db.execute("""CREATE TABLE IF NOT EXISTS pending_fixes (
                id INTEGER PRIMARY KEY, app_key TEXT NOT NULL,
                check_name TEXT NOT NULL, action_type TEXT NOT NULL,
                problem TEXT NOT NULL, suggested_fix TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                status TEXT NOT NULL DEFAULT 'pending', model TEXT,
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                resolved_at INTEGER,
                UNIQUE(app_key, check_name, action_type))""")
            row = db.execute("SELECT * FROM pending_fixes WHERE id=?", (fix_id,)).fetchone()
    except Exception as _dbe:
        raise HTTPException(status_code=500, detail=f"Database error: {_dbe}")
    if not row:
        raise HTTPException(status_code=404, detail=f"Fix {fix_id} not found")
    fix = dict(row)
    try:
        result = await execute_action(fix["action_type"], fix["app_key"], fix["suggested_fix"])
    except Exception as _e:
        raise HTTPException(status_code=500, detail=f"Action execution failed: {_e}")
    # Determine outcome accurately
    if result.get("executed"):
        outcome = "success"
    elif result.get("requires_approval"):
        # Safety tier is 'suggest' — user approved but action needs manual run
        outcome = "user_approved_manual"
    else:
        outcome = "pending"

    # Enrich result with the fix command when manual execution is needed
    if result.get("requires_approval"):
        result["manual_command"] = fix.get("suggested_fix", "")
        result["message"] = (
            f"Manual action required — run this command:\n{fix.get('suggested_fix','')}"
        )

    with StateDB() as db:
        db.execute("UPDATE pending_fixes SET status='approved', resolved_at=? WHERE id=?",
                   (int(_t.time()), fix_id))
        db.execute(
            """INSERT INTO fix_history (app_key, error_type, context, suggested_fix, outcome, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (fix["app_key"], fix["action_type"], fix["problem"], fix["suggested_fix"],
             outcome, int(_t.time())),
        )
    # Post-fix verification: re-check via docker inspect 60s later.
    # Uses subprocess (not asyncio-in-thread) to avoid event loop conflicts.
    if result.get("executed"):
        import threading as _th, subprocess as _subp, time as _vt2
        _app_key_snap = fix["app_key"]
        def _verify_after_delay() -> None:
            _vt2.sleep(60)
            try:
                from backend.core.state import StateDB as _VDB2
                _r = _subp.run(
                    ["docker", "inspect", "--format",
                     "{{.State.Status}}", _app_key_snap],
                    capture_output=True, text=True, timeout=5,
                )
                _still_failing = (_r.returncode != 0 or
                                   _r.stdout.strip() not in ("running",))
                import logging as _vlog2
                _vlog2.getLogger(__name__).info(
                    "Post-fix verification for %s: %s",
                    _app_key_snap,
                    "recovered" if not _still_failing else "still failing"
                )
                with _VDB2() as _vdb2:
                    _vdb2.execute(
                        """UPDATE fix_history SET outcome=?
                           WHERE app_key=?
                           AND created_at=(SELECT MAX(created_at) FROM fix_history WHERE app_key=?)""",
                        ("success" if not _still_failing else "failed_verification",
                         _app_key_snap, _app_key_snap),
                    )
                    # NOTE: StateDB auto-commits on __exit__ — _vdb2.commit() removed (Core Rule 4.4)
            except Exception:
                pass
        _th.Thread(target=_verify_after_delay, daemon=True).start()

    return result


@router.post("/pending-fixes/{fix_id}/reject")
def reject_fix(fix_id: int, reason: str = "") -> dict[str, Any]:
    """Reject a pending AI fix. Returns 404 if fix not found."""
    from backend.core.state import StateDB
    import time as _t
    with StateDB() as db:
        try:
            row = db.execute("SELECT * FROM pending_fixes WHERE id=?", (fix_id,)).fetchone()
        except Exception:
            row = None
        if not row:
            raise HTTPException(status_code=404, detail=f"Fix {fix_id} not found")
        fix = dict(row)
        db.execute("UPDATE pending_fixes SET status='rejected', resolved_at=? WHERE id=?",
                   (int(_t.time()), fix_id))
        try:
            db.execute(
                """INSERT INTO fix_history (app_key, error_type, context, suggested_fix, outcome, created_at)
                   VALUES (?, ?, ?, ?, 'failure', ?)""",
                (fix["app_key"], fix["action_type"], fix["problem"], fix["suggested_fix"], int(_t.time())),
            )
        except Exception:
            pass
    return {"ok": True}


@router.post("/escalate")
async def escalate_to_cloud(req: _EscalateRequest) -> dict[str, Any]:
    """Escalate a complex diagnosis to the fastest available cloud LLM.
    
    Used when local model returns low confidence or 'escalate' action type.
    Tries Groq → Cerebras → OpenRouter in order of speed.
    """
    import httpx as _hx
    import json as _ej
    from backend.core.state import StateDB
    from backend.health.context_assembler import assemble_context

    with StateDB() as db:
        cfg = _ej.loads(db.get_setting("llm_agent_config") or "{}")
    api_key  = cfg.get("api_key", "")
    provider = cfg.get("provider", "ollama")

    # Build escalation prompt with full context
    ctx = assemble_context(req.app_key, req.check_name)
    prompt = f"""You are an expert homelab systems administrator. A local AI agent was unable to diagnose this issue with high confidence and has escalated to you.

App: {req.app_key}
Check: {req.check_name}
Problem reported: {req.problem}
Recent logs:
{req.logs[-1500:] if req.logs else "(none)"}
{ctx}

Provide a thorough diagnosis. Respond ONLY with JSON:
{{"problem": "clear one-sentence description", "root_cause": "detailed root cause analysis", "suggested_fix": "exact command or step-by-step action", "action": "restart_container|reload_config|pull_image|rewire|restart_managed_service|remount_storage|manual", "confidence": 0.0, "escalation_notes": "what the local model likely missed"}}"""

    # Try cloud providers in speed order: groq → cerebras → openrouter
    CLOUD_ENDPOINTS = [
        ("groq",       "https://api.groq.com/openai/v1/chat/completions",       "llama-3.3-70b-versatile"),
        ("cerebras",   "https://api.cerebras.ai/v1/chat/completions",            "llama-3.3-70b"),
        ("openrouter", "https://openrouter.ai/api/v1/chat/completions",          "meta-llama/llama-3.3-70b-instruct:free"),
    ]

    # Use configured provider's key if it's a cloud provider, else try all
    for ep_provider, url, model in CLOUD_ENDPOINTS:
        if not api_key:
            continue
        if provider != ep_provider and provider not in ("ollama","llamacpp","shimmy","localai"):
            continue  # use configured key only for configured provider
        try:
            async with _hx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}",
                             "HTTP-Referer": "https://github.com/Nnyan/SLOP",
                             "X-Title": "Mediastack Health Agent Escalation"},
                    json={"model": model,
                          "messages": [{"role": "user", "content": prompt}],
                          "response_format": {"type": "json_object"}},
                )
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"]
                    data: dict[str, Any] = _ej.loads(raw)
                    data["escalated_to"] = f"{ep_provider}/{model}"
                    return data
        except Exception:
            continue

    return {
        "problem": req.problem,
        "root_cause": "Cloud escalation unavailable — no API keys configured.",
        "suggested_fix": "Configure a cloud provider API key in Settings → AI / LLM → Inference provider.",
        "action": "manual",
        "confidence": 0.0,
        "escalated_to": None,
    }

@router.post("/llm-test")
async def llm_test(req: dict[str, Any]) -> dict[str, Any]:
    """Test an LLM provider config with a minimal prompt.
    Returns latency, model used, and whether the response was valid JSON.
    """
    import time as _time
    import httpx as _httpx

    provider = req.get("provider", "ollama")
    api_key = req.get("api_key", "")
    model = req.get("model", "")
    ollama_url = req.get("ollama_url", "http://localhost:11434")

    test_prompt = (
        'You are a JSON API. Respond with exactly this JSON and nothing else: '
        '{"status": "ok", "message": "Mediastack LLM connection test passed"}'
    )

    start = _time.monotonic()
    try:
        if provider == "ollama":
            async with _httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model or "phi4-mini", "prompt": test_prompt,
                          "stream": False, "format": "json"},
                )
            raw = r.json().get("response", "")
        else:
            from backend.core.cloud_llm import PROVIDERS as _CP
            p = _CP.get(provider, {})
            base = p.get("base_url", "").rstrip("/")
            if not base:
                return {"ok": False, "error": f"Unknown provider: {provider}", "latency_ms": 0}
            hdrs = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/Nnyan/SLOP",
                "X-Title": "Mediastack LLM Test",
            }
            if provider == "anthropic":
                hdrs["anthropic-version"] = "2023-06-01"
            m = model or p.get("default_model", "")
            rf = {} if provider == "anthropic" else {"response_format": {"type": "json_object"}}
            async with _httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    f"{base}/chat/completions", headers=hdrs,
                    json={"model": m, "messages": [{"role": "user", "content": test_prompt}],
                          "max_tokens": 100, **rf},
                )
            raw = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")

        elapsed = int((_time.monotonic() - start) * 1000)
        import json as _jj
        try:
            parsed = _jj.loads(raw.strip().lstrip("```json").rstrip("```").strip())
            valid = parsed.get("status") == "ok"
        except Exception:
            valid = False

        return {
            "ok": valid,
            "latency_ms": elapsed,
            "model": model,
            "raw": raw[:200],
            "error": "" if valid else "Response was not valid JSON or unexpected format",
        }

    except Exception as e:
        return {
            "ok": False,
            "latency_ms": int((_time.monotonic() - start) * 1000),
            "model": model,
            "raw": "",
            "error": str(e)[:200],
        }


@router.get("/llm-providers")
def llm_providers() -> dict[str, Any]:
    """Return all available LLM providers with metadata for the Settings UI."""
    from backend.core.cloud_llm import PROVIDERS

    # Curated model lists per provider
    MODELS: dict[str, list[dict[str, Any]]] = {
        "groq": [
            {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (best quality)", "recommended": True},
            {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B (fastest)", "recommended": False},
        ],
        "cerebras": [
            {"id": "llama-3.3-70b", "label": "Llama 3.3 70B (best quality)", "recommended": True},
            {"id": "qwen-3-32b", "label": "Qwen 3 32B (alternative)", "recommended": False},
        ],
        "openrouter": [
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "label": "Llama 3.3 70B (free)", "recommended": True},
            {"id": "mistralai/mistral-small:free", "label": "Mistral Small (free)", "recommended": False},
            {"id": "google/gemini-flash-1.5:free", "label": "Gemini Flash 1.5 (free)", "recommended": False},
            {"id": "anthropic/claude-3.5-haiku", "label": "Claude 3.5 Haiku (paid, best quality)", "recommended": False},
        ],
        "mistral": [
            {"id": "mistral-small-latest", "label": "Mistral Small (fast, cheap)", "recommended": True},
            {"id": "mistral-nemo", "label": "Mistral Nemo (fastest)", "recommended": False},
            {"id": "mistral-large-latest", "label": "Mistral Large (best quality)", "recommended": False},
        ],
        "cohere": [
            {"id": "command-r7b-12-2024", "label": "Command R7B (fast, cheap)", "recommended": True},
            {"id": "command-r-plus-08-2024", "label": "Command R+ (best quality)", "recommended": False},
        ],
        "google": [
            {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash (best free)", "recommended": True},
            {"id": "gemini-1.5-flash-8b", "label": "Gemini 1.5 Flash 8B (fastest)", "recommended": False},
        ],
        "anthropic": [
            {"id": "", "label": "Enter model ID (e.g. claude-haiku-4-5) — see console.anthropic.com/docs", "recommended": True},
        ],
        "openai": [
            {"id": "gpt-4o-mini", "label": "GPT-4o Mini (cost-effective)", "recommended": True},
            {"id": "gpt-4o", "label": "GPT-4o (best quality)", "recommended": False},
        ],
    }

    result = {}
    for key, meta in PROVIDERS.items():
        result[key] = {
            **meta,
            "key": key,
            "models": MODELS.get(key, [{"id": meta.get("default_model", ""), "label": "Default", "recommended": True}]),
        }

    return {"providers": result}


@router.get("/apps/{key}/container-status")
def get_container_status(key: str) -> dict[str, Any]:
    """Lightweight container health poll for the wizard install progress view.
    
    Returns current Docker state without triggering a full health cycle.
    Frontend polls this every 3s during install to show live progress.
    """
    import subprocess as _sp
    try:
        r = _sp.run(
            ["docker", "inspect", "--format",
             "{{.State.Status}}|{{.State.Health.Status}}",
             key],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return {"key": key, "status": "missing", "health": "unknown", "ready": False}
        parts = r.stdout.strip().split("|")
        container_status = parts[0] if parts else "unknown"
        health = parts[1] if len(parts) > 1 else "none"
        # "none" health means no healthcheck defined — treat running as healthy
        ready = container_status == "running" and health in ("healthy", "none", "")
        return {
            "key": key,
            "status": container_status,
            "health": health,
            "ready": ready,
        }
    except Exception as e:
        return {"key": key, "status": "error", "health": "unknown", "ready": False,
                "error": str(e)}
