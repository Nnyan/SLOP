"""backend/health/scheduler.py

Background health check scheduler.

Runs `run_health_cycle()` on a configurable interval (default 30s).
Started automatically by the FastAPI lifespan when the platform is ready.
Stops cleanly on app shutdown via asyncio task cancellation.

Design constraints:
  - Never blocks the API — runs as an asyncio background task
  - Platform must be ready before checks start (wait loop on startup)
  - Each cycle runs all app checks concurrently via asyncio.gather
  - A single failing check never kills the scheduler
  - Interval and agent config are read from settings at each cycle
    so changes take effect without restart
"""
from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger

import asyncio
import json
import time

log = get_logger(__name__)

# Tracks the running scheduler task so the lifespan can cancel it
_scheduler_task: asyncio.Task[None] | None = None

DEFAULT_INTERVAL = 60      # seconds between full check cycles
PLATFORM_READY_POLL = 5    # seconds between platform-ready checks on startup
MAX_STARTUP_WAIT = 300     # give up waiting for platform after 5 minutes


async def _wait_for_platform() -> bool:
    """Wait until the platform is configured and ready.

    Returns True when ready, False if the timeout is exceeded.
    """
    deadline = time.monotonic() + MAX_STARTUP_WAIT
    while time.monotonic() < deadline:
        try:
            from backend.core.state import StateDB
            with StateDB() as db:
                platform = db.get_platform()
            if platform.status == "ready":
                return True
        except Exception:
            pass
        await asyncio.sleep(PLATFORM_READY_POLL)
    return False


async def _load_cycle_config() -> dict[str, Any]:
    """Load agent and scheduler config from settings DB."""
    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            interval_raw = db.get_setting("health_check_interval_secs")
            agent_raw = db.get_setting("llm_agent_config")
            ntfy_topic = db.get_setting("ntfy_topic") or "mediastack"
            ntfy_url   = db.get_setting("ntfy_url")   or "http://ntfy:80"
        interval = int(interval_raw) if interval_raw else DEFAULT_INTERVAL
        agent_cfg = json.loads(agent_raw) if agent_raw else {}
        _provider = agent_cfg.get("provider", "ollama")
        if _provider == "llamacpp":
            _llm_url = agent_cfg.get("llamacpp_url", "http://localhost:8081")
        else:
            _llm_url = agent_cfg.get("ollama_url", "http://ollama:11434")
        return {
            "interval": max(30, interval),
            "ollama_url": _llm_url,
            "ntfy_url": ntfy_url,
            "ntfy_topic": ntfy_topic,
        }
    except Exception:
        return {
            "interval": DEFAULT_INTERVAL,
            "ollama_url": "",   # provider config unreadable — surface error rather than silently use wrong backend
            "ntfy_url": "http://ntfy:80",
            "ntfy_topic": "mediastack",
        }


def _set_setting_silently(key: str, value: str) -> None:
    """db.set_setting wrapped in try/except — never raises."""
    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            db.set_setting(key, value)
    except Exception:
        pass


async def _execute_cycle(cfg: dict[str, Any]) -> None:
    """Run one full health cycle and persist its summary."""
    from backend.health.checker import run_health_cycle
    cycle_start = time.monotonic()
    run = await run_health_cycle(
        ollama_url=cfg["ollama_url"],
        ntfy_url=cfg["ntfy_url"],
        ntfy_topic=cfg["ntfy_topic"],
    )
    elapsed = time.monotonic() - cycle_start
    if run.apps_degraded > 0:
        log.warning(
            "Health cycle: %d/%d healthy, %d degraded (%.1fs)",
            run.apps_healthy, run.apps_checked, run.apps_degraded, elapsed,
        )
    else:
        log.debug(
            "Health cycle: %d/%d healthy (%.1fs)",
            run.apps_healthy, run.apps_checked, elapsed,
        )
    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            db.set_setting("health_last_cycle_at", str(int(time.time())))
            db.set_setting(
                "health_last_cycle_summary",
                json.dumps({
                    "apps_checked":  run.apps_checked,
                    "apps_healthy":  run.apps_healthy,
                    "apps_degraded": run.apps_degraded,
                    "llm_agent":     run.llm_agent_state,
                    "elapsed_ms":    int(elapsed * 1000),
                }),
            )
    except Exception:
        pass


def _check_docker_daemon_health() -> None:
    """Probe `docker ps` latency; persist a daemon-slow indicator when slow."""
    import subprocess as _sp, time as _t
    _docker_start = _t.monotonic()
    try:
        _sp.run(["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, timeout=5)
    except Exception as _de:
        log.error("Docker daemon unreachable: %s — skipping health checks", _de)
        return
    _docker_ms = int((_t.monotonic() - _docker_start) * 1000)
    if _docker_ms > 3000:
        log.warning("Docker daemon slow: %dms — all health checks unreliable",
                    _docker_ms)
        _set_setting_silently("docker_daemon_slow_ms", str(_docker_ms))
    else:
        _set_setting_silently("docker_daemon_slow_ms", "0")


def _check_and_restart_traefik() -> None:
    """If Traefik is not running, attempt one compose-up restart."""
    try:
        from backend.core import docker_client as _dc
        _traefik = _dc.get_container("traefik")
        if not _traefik or _traefik.status == "running":
            return
        log.warning("Traefik container is not running (status: %s) — attempting restart",
                    _traefik.status)
        import subprocess as _ts
        from backend.core.config import config as _tc
        _frag = _tc.compose_dir / "traefik.yaml"
        if not _frag.exists():
            return
        _r = _ts.run(
            ["docker", "compose", "-f", str(_frag), "up", "-d", "--quiet-pull"],
            capture_output=True, timeout=30,
        )
        if _r.returncode == 0:
            log.info("Traefik restarted successfully by health scheduler")
        else:
            log.error("Traefik restart failed: %s", _r.stderr.decode()[:200])
    except Exception as _te:
        log.debug("Traefik health check failed: %s", _te)


def _check_managed_services_health() -> None:
    """Run check_managed_services and warn on each unhealthy service."""
    try:
        from backend.health.managed_services import check_managed_services
        _ms_results = check_managed_services()
        for _svc, _res in _ms_results.items():
            if not _res["healthy"]:
                log.warning(
                    "Managed service '%s' unhealthy: %s", _svc, _res["message"]
                )
    except Exception as _mse:
        log.debug("Managed service check failed: %s", _mse)


def _check_disk_space() -> None:
    """Log a warning when the data dir is over 80% full (error over 95%)."""
    try:
        import shutil as _shu
        from backend.core.config import config as _cfg
        _du = _shu.disk_usage(str(_cfg.data_dir))
        _pct = int(_du.used / _du.total * 100)
        if _pct > 95:
            log.error("Data dir disk CRITICAL: %d%% used", _pct)
        elif _pct > 80:
            log.warning("Data dir disk: %d%% used — low disk space", _pct)
    except Exception:
        pass


def _maybe_start_source_scan() -> None:
    """Schedule a weekly source-availability scan in the background if overdue."""
    try:
        from backend.health.source_checker import due_for_scan, run_source_scan
        if due_for_scan():
            log.info("Source availability scan is due — starting in background.")
            asyncio.create_task(run_source_scan(), name="source-scan")
    except Exception as _e:
        log.debug("Source scan check failed: %s", _e)


async def _scheduler_loop() -> None:
    """Main scheduler loop. Runs until cancelled.

    Each iteration: load config → (skip if previous still running) → run one
    cycle → run ambient post-cycle checks (docker daemon / Traefik / managed
    services / disk / source scan) → sleep. CancelledError propagates out
    from the sleep or from the in-flight cycle so the FastAPI lifespan can
    cancel cleanly. Other exceptions are logged and the loop continues.
    """
    log.info("Health scheduler: waiting for platform to be ready…")
    if not await _wait_for_platform():
        log.warning(
            "Health scheduler: platform not ready after %ds — "
            "checks will not run until Mediastack is restarted.",
            MAX_STARTUP_WAIT,
        )
        return

    log.info("Health scheduler started — platform is ready.")

    cycle_running = False  # non-overlapping guard
    while True:
        cfg = await _load_cycle_config()

        if cycle_running:
            log.debug("Skipping health cycle — previous cycle still running.")
            await asyncio.sleep(cfg["interval"])  # CancelledError propagates
            continue

        cycle_running = True
        try:
            await _execute_cycle(cfg)
        except asyncio.CancelledError:
            cycle_running = False
            raise
        except Exception as e:
            log.error("Health scheduler cycle error: %s", e, exc_info=True)
            # Continue running — a single bad cycle never kills the scheduler
        finally:
            cycle_running = False

        # Ambient post-cycle checks — each handles its own exceptions
        _check_docker_daemon_health()
        _check_and_restart_traefik()
        _check_managed_services_health()
        _check_disk_space()
        _maybe_start_source_scan()

        try:
            await asyncio.sleep(cfg["interval"])
        except asyncio.CancelledError:
            log.info("Health scheduler stopping.")
            raise




async def _maybe_run_weekly_summary() -> None:
    """Run a weekly LLM health summary if 7+ days have passed since last one."""
    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            last_summary_str = db.get_setting("last_weekly_summary_ts") or "0"
            last_summary = int(last_summary_str)

        import time
        now = int(time.time())
        seven_days = 7 * 24 * 3600
        if now - last_summary < seven_days:
            return  # Not yet time

        log.info("Running weekly health summary…")

        from backend.core.state import StateDB as SDB
        import time as _t
        cutoff = now - seven_days

        with SDB() as db:
            rows = db.execute(
                """SELECT subject_key, check_name, status, summary, checked_at
                   FROM health_check_history
                   WHERE checked_at >= ? AND status IN ('error', 'warning')
                   ORDER BY checked_at DESC LIMIT 100""",
                (cutoff,)
            ).fetchall()

        if not rows:
            log.info("No health issues this week — skipping LLM summary.")
            with SDB() as db:
                db.set_setting("last_weekly_summary_ts", str(now))
            return

        # Build summary prompt
        issues_text = "\n".join(
            f"- {r['subject_key']}: {r['check_name']} ({r['status']}) — {r['summary']}"
            for r in rows[:30]
        )
        prompt = (
            f"You are a homelab health assistant. Summarize the following health issues "
            f"from the past 7 days in plain language. Identify patterns, recurring issues, "
            f"and the most important action to take. Be concise — 3-5 sentences max.\n\n"
            f"Issues:\n{issues_text}"
        )

        # Try local LLM
        summary_text = ""
        try:
            from backend.health.checker import _llm_state
            if _llm_state.get("status") == "ready":
                import httpx, asyncio
                with SDB() as db:
                    _wcfg_raw = db.get_setting("llm_agent_config")
                _wcfg = json.loads(_wcfg_raw) if _wcfg_raw else {}
                _wprovider = _wcfg.get("provider", "ollama")
                if _wprovider == "llamacpp":
                    ollama_url = _wcfg.get("llamacpp_url", "http://localhost:8081")
                else:
                    ollama_url = _wcfg.get("ollama_url", "http://ollama:11434")
                model = _wcfg.get("ollama_model") or "phi4-mini"
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        f"{ollama_url}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False}
                    )
                    resp.raise_for_status()
                    summary_text = resp.json().get("response", "")
        except Exception as e:
            log.debug("Weekly summary LLM call failed: %s", e)

        if summary_text:
            with SDB() as db:
                db.set_setting("last_weekly_summary", summary_text[:2000])
                db.set_setting("last_weekly_summary_ts", str(now))
            log.info("Weekly health summary generated (%d chars).", len(summary_text))
        else:
            with SDB() as db:
                db.set_setting("last_weekly_summary_ts", str(now))

    except Exception as e:
        log.debug("Weekly summary failed: %s", e)
def start_scheduler() -> None:
    """Start the health scheduler as an asyncio background task.

    Called from FastAPI lifespan. Safe to call multiple times — only
    one scheduler runs at a time.
    """
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        log.debug("Health scheduler already running.")
        return
    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="health-scheduler")
    log.info("Health scheduler task created.")


def stop_scheduler() -> None:
    """Cancel the scheduler gracefully. Called from FastAPI lifespan shutdown."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        log.info("Health scheduler cancelled.")
    _scheduler_task = None


def scheduler_status() -> dict[str, Any]:
    """Return current scheduler state (for the health API)."""
    if _scheduler_task is None:
        return {"running": False, "state": "not_started"}
    if _scheduler_task.done():
        exc = _scheduler_task.exception() if not _scheduler_task.cancelled() else None
        return {
            "running": False,
            "state": "stopped",
            "error": str(exc) if exc else None,
        }
    return {
        "running": True,
        "state": _scheduler_task.get_name(),
        "error": None,
    }
