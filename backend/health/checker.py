"""backend/health/checker.py

Health check runner — Step 7 core.

Runs manifest-defined health checks against installed apps.
On failure: attempts self-heal, invokes LLM agent if available,
sends ntfy notification, and disables app if performance thresholds exceeded.

Design:
  - Health checks run on a schedule (configurable, default 30s)
  - Each check is independent — one failing app doesn't block others
  - The LLM agent enriches failures but is never in the critical path
  - disable_app() is only called for ENHANCEMENT criticality apps
    or when PERF_THRESHOLDS are exceeded for other apps
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.core.logging import get_logger
from backend.core.state import StateDB
from backend.manifests.executor import (
    PERF_THRESHOLDS,
    Criticality,
    disable_app,
    get_criticality,
)
from backend.manifests.loader import load_manifest

log = get_logger(__name__)

# LLM agent degradation state — module-level so it persists across checks
_llm_state: dict[str, Any] = {
    "status": "unknown",          # active | degraded | offline | disabled
    "consecutive_failures": 0,
    "consecutive_slow": 0,
    "last_checked": 0,
    "last_error": "",             # human-readable last error
    "last_error_type": "",        # connection | timeout | parse | auth | dns | unknown
    "ollama_url": "http://ollama:11434",  # Docker container hostname
    "model_tried": "",            # which model was requested
    "last_success_at": 0,        # unix timestamp of last successful call
    "configured_provider": "",    # provider name from llm_agent_config
    "configured_model": "",       # model name from llm_agent_config
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    app_key: str
    check_name: str
    ok: bool
    message: str
    response_time_ms: float = 0.0
    detail: str = ""
    llm_diagnosis: str | None = None
    action_type: str | None = None   # restart_container | reload_config | pull_image | rewire | restart_managed_service | remount_storage | manual | escalate
    auto_healed: bool = False
    notification_sent: bool = False


@dataclass
class HealthRun:
    started_at: float
    results: list[CheckResult] = field(default_factory=list)
    apps_checked: int = 0
    apps_healthy: int = 0
    apps_degraded: int = 0
    apps_disabled: int = 0
    llm_agent_state: str = "unknown"


# ---------------------------------------------------------------------------
# HTTP health check
# ---------------------------------------------------------------------------


async def _check_http(
    app_key: str,
    check_name: str,
    base_url: str,
    path: str,
    expect_status: int = 200,
    timeout: float = 10.0,
) -> CheckResult:
    url = f"{base_url.rstrip('/')}{path}"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
        elapsed_ms = (time.monotonic() - start) * 1000
        ok = resp.status_code == expect_status
        return CheckResult(
            app_key=app_key,
            check_name=check_name,
            ok=ok,
            message=(
                f"HTTP {resp.status_code}" if ok
                else f"Expected {expect_status}, got {resp.status_code}"
            ),
            response_time_ms=elapsed_ms,
        )
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            app_key=app_key, check_name=check_name, ok=False,
            message=f"Request timed out after {timeout}s",
            response_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            app_key=app_key, check_name=check_name, ok=False,
            message=f"Connection failed: {type(e).__name__}",
            response_time_ms=elapsed_ms,
            detail=str(e)[:200],
        )


# ---------------------------------------------------------------------------
# LLM agent integration
# ---------------------------------------------------------------------------


def _log_routing(app_key: str, task_type: str, model: str,
                 success: bool, duration_ms: int | None,
                 error_type: str | None, summary: str | None) -> None:
    """Write one routing decision to llm_routing_log. Never raises."""
    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS llm_routing_log (
                    id INTEGER PRIMARY KEY,
                    ts INTEGER NOT NULL DEFAULT (unixepoch()),
                    app_key TEXT NOT NULL, task_type TEXT NOT NULL,
                    model TEXT NOT NULL, success INTEGER NOT NULL,
                    duration_ms INTEGER, error_type TEXT, summary TEXT
                )"""
            )
            db.execute(
                """INSERT INTO llm_routing_log
                   (app_key, task_type, model, success, duration_ms, error_type, summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (app_key, task_type, model, int(success),
                 duration_ms, error_type, summary),
            )
            # Prune entries older than 30 days
            db.execute(
                "DELETE FROM llm_routing_log WHERE ts < (unixepoch() - 2592000)"
            )
    except Exception as exc:
        log.debug("routing log write failed: %s", exc)



async def _check_tcp(app_key: str, check_name: str, port: int) -> CheckResult:
    """TCP reachability check — verifies port accepts connections on localhost.

    Distinguishes:
      - Port not bound at all (wrong config, app crashed before binding)
      - Port bound but refusing connection (race condition / startup)
      - Connected successfully
    """
    import socket as _sock, subprocess as _sp
    if not port:
        return CheckResult(app_key=app_key, check_name=check_name,
                           ok=False, message="TCP check: no port configured.")
    start = time.monotonic()
    try:
        with _sock.create_connection(("localhost", port), timeout=5):
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult(app_key=app_key, check_name=check_name,
                               ok=True, message=f"TCP port {port} open",
                               response_time_ms=elapsed)
    except (ConnectionRefusedError, OSError, TimeoutError) as e:
        # Item 5: distinguish "port not bound" from "connection refused"
        # ss -tlnp shows listening ports — if absent, the process hasn't bound
        try:
            ss = _sp.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=3)
            port_bound = f":{port} " in ss.stdout or f":{port}\t" in ss.stdout
        except Exception:
            port_bound = None  # can't tell
        if port_bound is False:
            msg = (
                f"Port {port} is not bound — process may have crashed before startup "
                f"or is configured with the wrong port. Check: docker logs {app_key}"
            )
        else:
            msg = f"TCP port {port} unreachable: {e}"
        return CheckResult(app_key=app_key, check_name=check_name,
                           ok=False, message=msg)


def _check_process(app_key: str, check_name: str, container_name: str) -> CheckResult:
    """Check that the container process is running via docker inspect."""
    import subprocess as _sp, json as _j
    try:
        r = _sp.run(
            ["docker", "inspect", "--format", "{{json .State.Running}}", container_name],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip() == "true":
            return CheckResult(app_key=app_key, check_name=check_name,
                               ok=True, message=f"Container {container_name} is running")
        return CheckResult(app_key=app_key, check_name=check_name,
                           ok=False, message=f"Container {container_name} is not running")
    except Exception as e:
        return CheckResult(app_key=app_key, check_name=check_name,
                           ok=False, message=f"Could not inspect container: {e}")



# Map raw LLM action strings to internal action_type symbols (module-scope so
# `_extract_diagnosis` and tests can reuse it).
_LLM_ACTION_MAP: dict[str, str] = {
    "restart":           "restart_container",
    "restart_container": "restart_container",
    "reload":            "reload_config",
    "config_change":     "reload_config",
    "pull":              "pull_image",
    "update_image":      "pull_image",
    "rewire":            "rewire",
    "restart_service":   "restart_managed_service",
    "remount":           "remount_storage",
    "reprovision":       "reprovision_hostname",
    "manual":            "manual",
    "escalate":          "escalate",
}


def _check_ram_for_llm(model: str) -> bool:
    """Pre-flight RAM check — return False when the model can't fit safely."""
    from backend.core.system_eval import quick_ram_check, LLM_MODEL_RAM_MB
    model_ram = LLM_MODEL_RAM_MB.get(model, 3000)
    ok, warn = quick_ram_check(model_ram)
    if not ok:
        log.debug("Skipping LLM diagnosis — %s", warn)
    return ok


def _build_diagnosis_prompt(app_key: str, check_result: CheckResult, logs: str) -> str:
    """Assemble the full LLM prompt: failure summary + DB context + RAG enrichment."""
    try:
        from backend.health.context_assembler import assemble_context as _ctx
        _diagnostic_ctx = _ctx(app_key, check_result.check_name)
    except Exception:
        _diagnostic_ctx = ""

    prompt = f"""You are a homelab health agent diagnosing a failing service. Respond with JSON ONLY — no prose, no markdown.

=== FAILURE SUMMARY ===
App: {app_key}
Check: {check_result.check_name}
Error: {check_result.message}
Response time: {check_result.response_time_ms:.0f}ms

=== RECENT DOCKER LOGS ===
{logs[-2000:]}

{_diagnostic_ctx}

=== CONTEXT READING RULES ===
- If "MASS FAILURE EVENT" appears: set action=escalate, confidence=0.9, explain infra root cause
- If "TRAEFIK IS STOPPED" or "TRAEFIK CONTAINER MISSING" appears: set action=manual, explain Traefik is the cause
- If "MANAGED SERVICES DOWN: postgres" or "redis" appears: set action=restart_managed_service
- If "CRITICAL: No compose fragment" appears: set action=manual, suggested_fix="Reinstall from Catalog"
- If "OOM killed: YES" appears: set action=restart_container, confidence=0.95
- If "Already pending user approval" appears: acknowledge it, do NOT suggest the same action again
- If "INSTALL FAILED" appears: app never ran, likely config/image issue — set action=pull_image or manual
- If "DOCKER DAEMON SLOW" appears: note this may be a false positive, set confidence ≤0.5
- If error contains "401" or "403" and "INFRA DEGRADED" appears in context: the auth middleware (tinyauth/authelia) is down. Set action=manual, cause="auth middleware down", confidence=0.95. Do NOT diagnose the individual app — fix the infra first.
- If error contains "502" or "504" and Traefik-related: set action=manual, cause="Traefik routing failed", check Traefik container status
- Avoid suggesting actions listed under "Previous fix attempts" that show [✓] (already worked)
- Avoid suggesting actions listed under "Previous fix attempts" that show [✗] (already failed)

=== AVAILABLE ACTIONS (pick the most specific one) ===
restart_container      — container crashed or is stuck, needs restart
reload_config          — config file changed, service needs reload (not full restart)
pull_image             — image outdated or corrupted, pull fresh copy
rewire                 — API key/URL to another app is wrong or stale
restart_managed_service — postgres or redis is down
remount_storage        — NFS/rclone mount is stale or disconnected
manual                 — requires human action (reinstall, fix config, check hardware)
escalate               — local model uncertain, needs cloud LLM review

=== CONFIDENCE CALIBRATION ===
≥0.90 — single clear cause with direct evidence in logs or context
0.70–0.89 — likely cause, some supporting evidence
0.50–0.69 — plausible but multiple possible causes
<0.50 — insufficient evidence, recommend escalate

Respond with exactly this JSON and nothing else:
{{"problem": "one sentence describing what is failing", "cause": "one sentence root cause from logs/context", "suggested_fix": "specific command or step — not a generic suggestion", "action": "one of the 8 action types above", "confidence": 0.0}}"""

    try:
        from backend.core.rag import enrich_prompt_with_context as _rag_enrich
        error_context = f"{app_key} {check_result.check_name} {check_result.message} {logs[-500:]}"
        prompt = _rag_enrich(prompt, error_context)
    except Exception:
        pass  # RAG is optional — proceed without it
    return prompt


def _load_provider_config() -> tuple[str, str, str, set[str]]:
    """Return (provider, api_key, model_cfg, cloud_provider_set) from llm_agent_config."""
    try:
        import json as _jcfg
        with StateDB() as _db:
            _cfg = _jcfg.loads(_db.get_setting("llm_agent_config") or "{}")
        _provider = _cfg.get("provider", "ollama")
        _api_key = _cfg.get("api_key", "")
        _model_cfg = _cfg.get("model", "")
        _llm_state["configured_provider"] = _provider
        _llm_state["configured_model"] = _model_cfg
        from backend.core.cloud_llm import PROVIDERS as _PROV_MAP
        return _provider, _api_key, _model_cfg, set(_PROV_MAP.keys())
    except Exception:
        return "ollama", "", "", set()


async def _call_ollama(client: httpx.AsyncClient, prompt: str,
                       ollama_url: str, model: str) -> str:
    """Hit ollama /api/generate; return the raw response string."""
    resp = await client.post(
        f"{ollama_url}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
    )
    resp.raise_for_status()
    return resp.json().get("response", "") or ""


async def _call_cloud_provider(client: httpx.AsyncClient, prompt: str,
                               provider: str, api_key: str, model: str) -> str:
    """Hit an OpenAI-style cloud /v1/chat/completions; return the assistant content."""
    from backend.core.cloud_llm import PROVIDERS as _CP
    _p_cfg = _CP.get(provider, {})
    _base = _p_cfg.get("base_url", "").rstrip("/")
    if not _base:
        raise ValueError(f"Unknown provider '{provider}'")
    _endpoint = f"{_base}/chat/completions"
    hdrs = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/Nnyan/mediastack",
        "X-Title": "Mediastack Health Agent",
    }
    cloud_model = model or _p_cfg.get("default_model", "")
    _rf: dict[str, Any] = {}
    if provider not in ("anthropic",):
        _rf = {"response_format": {"type": "json_object"}}
    if provider == "anthropic":
        hdrs["anthropic-version"] = "2023-06-01"
    resp = await client.post(
        _endpoint, headers=hdrs,
        json={"model": cloud_model,
              "messages": [{"role": "user", "content": prompt}],
              **_rf},
    )
    resp.raise_for_status()
    return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") or ""


async def _call_openai_compatible(client: httpx.AsyncClient, prompt: str,
                                  ollama_url: str, api_key: str, model: str) -> str:
    """Hit an OpenAI-shaped local server (llamacpp / shimmy / localai)."""
    hdrs = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await client.post(
        f"{ollama_url}/v1/chat/completions",
        headers=hdrs,
        json={"model": model,
              "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}},
    )
    resp.raise_for_status()
    return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") or ""


async def _dispatch_llm_call(client: httpx.AsyncClient, prompt: str,
                             ollama_url: str, provider: str, api_key: str,
                             model: str, cloud_providers: set[str]) -> str:
    """Dispatch the LLM call to ollama / cloud / openai-compatible by provider."""
    if provider == "ollama":
        return await _call_ollama(client, prompt, ollama_url, model)
    if provider in cloud_providers:
        return await _call_cloud_provider(client, prompt, provider, api_key, model)
    return await _call_openai_compatible(client, prompt, ollama_url, api_key, model)


async def _maybe_rag_expand(raw: str, prompt: str, app_key: str,
                            ollama_url: str, model: str, logs: str) -> str:
    """If the model's confidence is low and we have logs, re-run with extra KB chunks.

    Always uses ollama for the expansion (preserves original behaviour). Returns
    the expanded raw string when the re-run succeeded, otherwise the original raw.
    """
    try:
        parsed = __import__('json').loads(raw)
        confidence = float(parsed.get("confidence", 1.0))
        if confidence >= 0.5 or not logs:
            return raw
        from backend.core.rag import query_knowledge_base as _qkb
        extra_chunks = _qkb(
            f"{app_key} {parsed.get('problem', '')} {logs[-200:]}", n=2
        )
        if not extra_chunks:
            return raw
        log.debug(
            "RAG expansion triggered for %s (confidence=%.2f) — re-running with %d extra chunks",
            app_key, confidence, len(extra_chunks)
        )
        expanded_context = "\n\n".join(extra_chunks)
        expanded_prompt = (
            f"Additional knowledge base context:\n{expanded_context}\n\n{prompt}"
        )
        async with httpx.AsyncClient(timeout=50) as client2:
            resp2 = await client2.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "prompt": expanded_prompt,
                      "stream": False, "format": "json"},
            )
        if resp2.status_code == 200:
            raw2 = resp2.json().get("response", "")
            if isinstance(raw2, str) and raw2:
                return raw2
    except Exception:
        pass
    return raw


def _track_llm_success(elapsed: float, ollama_url: str, model: str) -> None:
    """Record a successful LLM call in _llm_state (slow / active / degraded)."""
    if elapsed > PERF_THRESHOLDS["llm_inference_seconds"]:
        _llm_state["consecutive_slow"] += 1
    else:
        _llm_state["consecutive_slow"] = 0
        _llm_state["status"] = "active"
    if _llm_state["consecutive_slow"] >= 3:
        _llm_state["status"] = "degraded"
        log.warning("LLM agent degraded — slow inference (%ds)", int(elapsed))
    _llm_state["consecutive_failures"] = 0
    _llm_state["last_error"] = ""
    _llm_state["last_error_type"] = ""
    _llm_state["last_success_at"] = int(time.monotonic())
    _llm_state["model_tried"] = model
    _llm_state["ollama_url"] = ollama_url


def _classify_llm_error(e: Exception, ollama_url: str, model: str) -> None:
    """Update _llm_state with the error classification + offline-state transition."""
    _llm_state["consecutive_failures"] = _llm_state.get("consecutive_failures", 0) + 1
    err_str = str(e)
    if "Connection refused" in err_str or "Connect call failed" in err_str or "ConnectionRefusedError" in err_str:
        _llm_state["last_error_type"] = "connection"
        _llm_state["last_error"] = f"Cannot reach {ollama_url} — Ollama may not be running."
    elif "timed out" in err_str.lower() or "TimeoutError" in err_str:
        _llm_state["last_error_type"] = "timeout"
        _llm_state["last_error"] = f"Request to {ollama_url} timed out — model may be too slow or overloaded."
    elif "404" in err_str or "model" in err_str.lower() and "not found" in err_str.lower():
        _llm_state["last_error_type"] = "model"
        _llm_state["last_error"] = f"Model \'{model}\' not found in Ollama — run: ollama pull {model}"
    elif "JSONDecodeError" in err_str or "json" in err_str.lower():
        _llm_state["last_error_type"] = "parse"
        _llm_state["last_error"] = f"Model \'{model}\' returned invalid JSON — try a different model."
    else:
        _llm_state["last_error_type"] = "unknown"
        _llm_state["last_error"] = f"{type(e).__name__}: {err_str[:120]}"
    _llm_state["ollama_url"] = ollama_url
    _llm_state["model_tried"] = model
    if _llm_state["last_error_type"] in ("dns", "auth"):
        _llm_state["status"] = "offline"
        log.warning("LLM agent offline (immediate): %s — %s",
                    _llm_state["last_error_type"], _llm_state["last_error"])
    elif _llm_state["consecutive_failures"] >= PERF_THRESHOLDS["llm_parse_fail_streak"]:
        _llm_state["status"] = "offline"
        log.warning("LLM agent offline after %d consecutive failures: %s",
                    _llm_state["consecutive_failures"], _llm_state["last_error"])


def _extract_diagnosis(data: dict[str, Any]) -> tuple[str, str, str, float]:
    """Map LLM JSON to (action_type, problem, suggested, confidence)."""
    raw_action = data.get("action", "manual").lower()
    action_type = _LLM_ACTION_MAP.get(raw_action, raw_action)
    confidence = float(data.get("confidence", 0.5))
    problem = data.get("problem", "")
    cause = data.get("cause", "")
    if cause and cause.lower() not in problem.lower():
        problem = f"{problem} (Root cause: {cause})" if problem else cause
    suggested = data.get("suggested_fix", "")
    escalation = data.get("escalation_notes", "")
    if escalation:
        suggested = (
            f"{suggested} [Escalation context: {escalation[:200]}]"
            if suggested else escalation
        )
    return action_type, problem, suggested, confidence


def _persist_pending_fix(app_key: str, check_name: str, action_type: str,
                         problem: str, suggested: str, confidence: float,
                         model: str) -> None:
    """Upsert the LLM's diagnosis into the pending_fixes approval queue."""
    try:
        with StateDB() as _pdb:
            _pdb.execute("""
                CREATE TABLE IF NOT EXISTS pending_fixes (
                    id           INTEGER PRIMARY KEY,
                    app_key      TEXT NOT NULL,
                    check_name   TEXT NOT NULL,
                    action_type  TEXT NOT NULL,
                    problem      TEXT NOT NULL,
                    suggested_fix TEXT NOT NULL,
                    confidence   REAL NOT NULL DEFAULT 0.5,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    model        TEXT,
                    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
                    resolved_at  INTEGER,
                    UNIQUE(app_key, check_name, action_type)
                )""")
            _pdb.execute("""
                INSERT INTO pending_fixes
                    (app_key, check_name, action_type, problem, suggested_fix,
                     confidence, status, model)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(app_key, check_name, action_type)
                DO UPDATE SET
                    problem=excluded.problem,
                    suggested_fix=excluded.suggested_fix,
                    confidence=excluded.confidence,
                    status='pending',
                    model=excluded.model,
                    created_at=unixepoch(),
                    resolved_at=NULL
            """, (app_key, check_name, action_type,
                  problem, suggested, confidence, model))
    except Exception as _pe:
        log.debug("pending_fixes write failed: %s", _pe)


async def _llm_diagnose(
    app_key: str,
    check_result: CheckResult,
    logs: str,
    ollama_url: str = "http://ollama:11434",  # Docker container hostname (correct default)
    model: str = "phi4-mini",
) -> str | None:
    """Query the LLM agent for a diagnosis. Never raises — returns None on any failure.

    Orchestrates: pre-flight RAM check → prompt build (with DB context + RAG)
    → provider config → HTTP dispatch → optional RAG-expansion re-run →
    response parsing → pending_fixes upsert → human-readable diagnosis string.
    """
    if not _check_ram_for_llm(model):
        return None

    prompt = _build_diagnosis_prompt(app_key, check_result, logs)
    provider, api_key, _model_cfg, cloud_providers = _load_provider_config()

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=50) as client:
            raw = await _dispatch_llm_call(
                client, prompt, ollama_url, provider, api_key, model, cloud_providers,
            )
            raw = await _maybe_rag_expand(
                raw, prompt, app_key, ollama_url, model, logs,
            )
        elapsed = time.monotonic() - start
        _track_llm_success(elapsed, ollama_url, model)

        import json
        clean = raw.strip().lstrip("```json").rstrip("```").strip()
        data = json.loads(clean)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        _log_routing(app_key, "reasoning", model, True, elapsed_ms, None,
                     data.get("problem", "")[:120])

        action_type, problem, suggested, confidence = _extract_diagnosis(data)
        _persist_pending_fix(app_key, check_result.check_name, action_type,
                             problem, suggested, confidence, model)
        return (
            f"[{action_type.upper().replace('_',' ')} | confidence={confidence:.0%}] "
            f"{problem} — {suggested}"
        )
    except Exception as e:
        _classify_llm_error(e, ollama_url, model)
        _log_routing(app_key, "reasoning", model, False, None,
                     _llm_state["last_error_type"], _llm_state["last_error"][:120])
        log.debug("LLM diagnosis skipped: %s", e)
        return None


# ---------------------------------------------------------------------------
# ntfy notification
# ---------------------------------------------------------------------------


async def _send_notification(
    title: str,
    message: str,
    priority: str = "default",
    ntfy_url: str = "http://ntfy:80",
    topic: str = "mediastack",
) -> bool:
    """Send an ntfy push notification. Returns True if sent."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{ntfy_url}/{topic}",
                content=message.encode(),
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": "warning" if priority != "urgent" else "rotating_light",
                },
            )
        return resp.status_code in (200, 201)
    except Exception as e:
        log.debug("ntfy notification failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Self-heal
# ---------------------------------------------------------------------------


# Manifest action aliases — module-scope so tests can introspect.
_HEAL_ALIASES: dict[str, str] = {
    "restart":                 "restart_container",
    "restart_container":       "restart_container",
    "reload":                  "reload_config",
    "reload_config":           "reload_config",
    "pull":                    "pull_image",
    "pull_image":              "pull_image",
    "rewire":                  "rewire",
    "remount":                 "remount_storage",
    "remount_storage":         "remount_storage",
    "restart_managed_service": "restart_managed_service",
}


def _heal_restart_container(app_key: str) -> bool:
    import subprocess as _sub
    r = _sub.run(["docker", "restart", "-t", "10", app_key],
                 capture_output=True, timeout=30)
    if r.returncode == 0:
        log.info("Self-healed '%s' via manifest restart", app_key)
        return True
    log.warning("Self-heal restart failed for %s: %s",
                app_key, r.stderr.decode()[:100])
    return False


def _heal_reload_config(app_key: str) -> bool:
    import subprocess as _sub
    r = _sub.run(["docker", "kill", "--signal=HUP", app_key],
                 capture_output=True, timeout=10)
    if r.returncode == 0:
        log.info("Self-healed '%s' via manifest reload_config", app_key)
        return True
    return False


def _heal_pull_image(app_key: str) -> bool:
    import subprocess as _sub
    with StateDB() as _db:
        _app = _db.get_app(app_key)
    if not (_app and _app.image):
        return False
    r = _sub.run(
        ["docker", "pull", f"{_app.image}:{_app.image_tag or 'latest'}"],
        capture_output=True, timeout=120,
    )
    if r.returncode == 0:
        log.info("Self-healed '%s' via manifest pull_image", app_key)
        return True
    return False


def _heal_rewire(app_key: str) -> bool:
    with StateDB() as _db:
        _stale = _db.execute(
            """SELECT w.id FROM wiring w
               JOIN apps a1 ON a1.id = w.source_app_id
               WHERE a1.key = ? AND w.status IN ('stale','failed')""",
            (app_key,),
        ).fetchall()
        for row in _stale:
            _db.execute("UPDATE wiring SET status='pending' WHERE id=?", (row["id"],))
    log.info("Self-healed '%s' via manifest rewire (%d entries)", app_key, len(_stale))
    return len(_stale) > 0


def _heal_remount_storage(app_key: str) -> bool:
    import subprocess as _sub
    with StateDB() as _db:
        _stores = _db.execute(
            "SELECT name, source_type FROM storage_sources WHERE status='error'"
        ).fetchall()
    for s in _stores:
        cname = f"rclone-{s['name'].lower().replace(' ', '-')}"
        _sub.run(["docker", "restart", cname], capture_output=True, timeout=15)
    log.info("Self-healed '%s' via manifest remount_storage", app_key)
    return bool(_stores)


def _heal_restart_managed_service(app_key: str) -> bool:
    import subprocess as _sub
    with StateDB() as _db:
        _dep = _db.execute(
            """SELECT ms.container_name FROM app_dependencies d
               JOIN apps a ON a.id = d.app_id
               JOIN managed_services ms ON ms.service_type = d.dependency_type
               WHERE a.key = ? AND ms.status = 'error' LIMIT 1""",
            (app_key,),
        ).fetchone()
    if not _dep:
        return False
    r = _sub.run(["docker", "restart", _dep["container_name"]],
                 capture_output=True, timeout=30)
    if r.returncode == 0:
        log.info("Self-healed '%s' via manifest restart_managed_service", app_key)
        return True
    return False


# Action dispatch table — module-scope so tests can introspect.
_HEAL_DISPATCHERS: dict[str, "Callable[[str], bool]"] = {
    "restart_container":       _heal_restart_container,
    "reload_config":           _heal_reload_config,
    "pull_image":              _heal_pull_image,
    "rewire":                  _heal_rewire,
    "remount_storage":         _heal_remount_storage,
    "restart_managed_service": _heal_restart_managed_service,
}


async def _attempt_self_heal(
    app_key: str,
    action: str,
    check_result: CheckResult,
) -> bool:
    """Attempt the self-heal action defined in the manifest.

    IMPORTANT: Manifest self_heal bypasses the AI safety tier. When a user
    defines self_heal in their manifest, they are explicitly opting into
    automatic remediation for that specific action. The safety tier (suggest/act)
    applies only to LLM-suggested fixes sent to pending_fixes for approval.

    Returns True if the action was successfully executed.

    Step 2.7.a: action dispatch is now table-driven via `_HEAL_ALIASES`
    (manifest-string → canonical-action) + `_HEAL_DISPATCHERS`
    (canonical-action → handler). Drops cyclomatic complexity from 16 to ≤ 4.
    """
    action_type = _HEAL_ALIASES.get(action, action)
    handler = _HEAL_DISPATCHERS.get(action_type)
    if handler is None:
        return False
    try:
        return handler(app_key)
    except Exception as e:
        log.warning("Self-heal failed for %s/%s: %s", app_key, action_type, e)
        return False


# ---------------------------------------------------------------------------
# Main check runner
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Container startup grace period
# ---------------------------------------------------------------------------

_DOCKER_DEFAULT_GRACE_S = 120  # seconds after container start to skip health checks

def _container_started_at(container_name: str) -> float | None:
    """Return Unix timestamp when container last started, or None if unavailable."""
    import subprocess
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.StartedAt}}", container_name],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        # Docker returns ISO 8601: "2026-05-01T02:59:14.123456789Z"
        from datetime import datetime, timezone
        raw = r.stdout.strip().replace("Z", "+00:00")
        # Handle nanoseconds — Python datetime only handles 6 decimal places
        import re
        raw = re.sub(r'(\.\d{6})\d+', r'\1', raw)
        dt = datetime.fromisoformat(raw)
        return dt.timestamp()
    except Exception:
        return None


def _in_startup_grace(container_name: str, grace_s: int) -> tuple[bool, float]:
    """Return (is_in_grace, seconds_since_start).

    Returns (True, age) if the container started less than grace_s seconds ago.
    Returns (False, age) otherwise. Returns (False, -1) if we can't determine.
    """
    started_at = _container_started_at(container_name)
    if started_at is None:
        return False, -1.0
    age = time.time() - started_at
    return age < grace_s, age



def _container_runtime_state(container_name: str) -> dict[str, Any]:
    """Fetch runtime diagnostic data from docker inspect.

    Returns dict with: restart_count, exit_code, oom_killed, finished_at.
    Never raises — returns empty dict on any failure.
    """
    import subprocess, json as _json
    try:
        r = subprocess.run(
            ["docker", "inspect",
             "--format", "{{json .State}}",
             container_name],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {}
        state = _json.loads(r.stdout.strip())
        return {
            "restart_count": state.get("RestartCount", 0),
            "exit_code":     state.get("ExitCode", 0),
            "oom_killed":    state.get("OOMKilled", False),
            "finished_at":   state.get("FinishedAt", ""),
        }
    except Exception:
        return {}


def _config_disk_pct(config_path: str | None) -> int | None:
    """Return used % of the filesystem holding config_path, or None."""
    if not config_path:
        return None
    import shutil
    try:
        u = shutil.disk_usage(config_path)
        return int(u.used / u.total * 100)
    except Exception:
        return None


async def _container_net_reachability(
    container_name: str,
    wired_targets: list[tuple[str, int]],  # [(hostname, port), ...]
) -> dict[str, bool]:
    """Quick TCP reachability test from inside the container to its wired deps.
    Uses `docker exec <ctr> nc -z -w2 <host> <port>`.
    Only runs if wired_targets is non-empty. Never raises.
    """
    import asyncio
    results: dict[str, bool] = {}
    if not wired_targets:
        return results

    async def _probe(host: str, port: int) -> tuple[str, bool]:
        key = f"{host}:{port}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container_name,
                "nc", "-z", "-w2", host, str(port),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5)
            return key, proc.returncode == 0
        except Exception:
            return key, False

    tasks = [_probe(h, p) for h, p in wired_targets[:4]]  # max 4 probes
    for coro in asyncio.as_completed(tasks):
        key, ok = await coro
        results[key] = ok
    return results


# ── check_app helpers — split for complexity discipline (Core Rule 8.1) ─────


def _check_infra_app(app_key: str) -> None:
    """Tier-0 (infra) app fallback — docker-inspect health check.

    Writes results directly to DB; returns nothing. Used when the app
    record exists in the DB but has no catalog manifest (e.g. tunnel
    providers, auth proxy).
    """
    import subprocess as _sp, time as _itime
    try:
        _r = _sp.run(
            ["docker", "inspect", "--format",
             "{{.State.Status}}|{{.State.Health.Status}}|{{.State.StartedAt}}",
             app_key],
            capture_output=True, text=True, timeout=5,
        )
        if _r.returncode == 0:
            _parts = _r.stdout.strip().split("|")
            _cstate  = _parts[0] if _parts else "unknown"
            _hstate  = _parts[1] if len(_parts) > 1 else ""
            _ok = _cstate == "running" and _hstate not in ("unhealthy",)
            _status = "ok" if _ok else "error"
            _msg = (f"Container {_cstate}"
                    + (f" (health: {_hstate})" if _hstate and _hstate != "none" else ""))
            with StateDB() as _idb:
                _idb.upsert_health_check(
                    "app", app_key, "container_state",
                    status=_status, summary=_msg,
                )
                if _ok:
                    _idb.upsert_app(app_key, status="running",
                                    last_healthy_at=int(_itime.time()))
                else:
                    _idb.upsert_app(app_key, status="failed")
        else:
            with StateDB() as _idb:
                _idb.upsert_health_check(
                    "app", app_key, "container_state",
                    status="error", summary="Container not found — may not be deployed",
                )
                _idb.upsert_app(app_key, status="failed")
    except Exception as _ie:
        log.debug("Infra app health check failed for %s: %s", app_key, _ie)


def _load_manifest_or_skip(app_key: str) -> Any | None:
    """Load the catalog manifest, falling back to infra-app docker-inspect.

    Returns the manifest object on success. Returns None when:
      - app is unmanaged (no manifest, not in apps table) → caller returns []
      - app is infra (tier=0) → infra check has been performed; caller returns []
    """
    try:
        return load_manifest(app_key)
    except Exception:
        with StateDB() as _tdb:
            _tier_app = _tdb.get_app(app_key)
        if not _tier_app or getattr(_tier_app, "tier", 1) != 0:
            return None  # truly unmanaged
        _check_infra_app(app_key)
        return None


def _precheck_fragment(app_key: str, app: Any, manifest: Any) -> list[CheckResult] | None:
    """Pre-check 1: compose fragment must exist on disk.

    Returns a list of error CheckResults (one per defined health check)
    when the fragment is missing — the LLM can't help here. Returns None
    when the fragment is fine and the caller should continue.
    """
    try:
        from backend.core.config import config as _cfg
        _frag_path = _cfg.compose_dir / f"{app_key}.yaml"
        if not _frag_path.exists() and app and app.status not in ("failed", "disabled", "removing"):
            log.warning("App '%s' has no compose fragment — misconfigured", app_key)
            return [CheckResult(
                app_key=app_key,
                check_name=check_def.name,
                ok=False,
                message=(
                    f"No compose fragment for '{app_key}' — app cannot start. "
                    f"Remove from DB or reinstall."
                ),
            ) for check_def in manifest.health_checks]
    except Exception:
        pass
    return None


def _precheck_oom(app_key: str, manifest: Any, runtime_state: dict[str, Any],
                  in_grace: bool) -> list[CheckResult] | None:
    """Pre-check 2: OOM kill detection.

    Returns a single oom_killed CheckResult when the container was OOM-killed
    (and not in grace). Returns None to signal the caller should continue.
    """
    if runtime_state.get("oom_killed") and not in_grace:
        log.warning("App '%s' was OOM killed", app_key)
        _oom_result = CheckResult(
            app_key=app_key,
            check_name="oom_killed",
            ok=False,
            message=(
                f"{manifest.display_name} was killed due to out-of-memory (OOM). "
                f"Restart count: {runtime_state.get('restart_count', '?')}. "
                f"Increase Docker memory limit or reduce concurrent apps."
            ),
        )
        _oom_result.action_type = "restart_container"
        _oom_result.llm_diagnosis = (
            f"[OOM KILL | confidence=95%] Container killed by kernel OOM killer. "
            f"Suggested fix: Add mem_limit to compose fragment or reduce app memory usage."
        )
        return [_oom_result]
    return None


def _grace_results(app_key: str, manifest: Any, container_age: float,
                   grace_s: int) -> list[CheckResult]:
    """Return 'starting' CheckResults for every defined health check.

    Used when the container is inside the configured startup grace period —
    real health checks would always fail during boot.
    """
    log.debug(
        "%s is in startup grace period (started %.0fs ago, grace=%ds) — skipping checks",
        app_key, container_age, grace_s,
    )
    return [
        CheckResult(
            app_key=app_key,
            check_name=check_def.name,
            ok=True,
            message=f"Starting — {container_age:.0f}s into {grace_s}s grace period",
        )
        for check_def in manifest.health_checks
    ]


async def _run_one_check(app_key: str, check_def: Any, base_url: str,
                         host_port: int | None, container_name: str) -> CheckResult:
    """Dispatch a single check_def to its check_type (http/tcp/process/custom)."""
    if check_def.check_type == "http" and base_url:
        return await _check_http(
            app_key=app_key,
            check_name=check_def.name,
            base_url=base_url,
            path=check_def.path or "/",
            expect_status=check_def.expect_status,
        )
    if check_def.check_type == "tcp":
        tcp_port = check_def.port or host_port or 0
        return await _check_tcp(app_key, check_def.name, tcp_port)
    if check_def.check_type == "process":
        return _check_process(app_key, check_def.name, container_name)
    return CheckResult(
        app_key=app_key, check_name=check_def.name,
        ok=True, message=f"Check type '{check_def.check_type}' not implemented."
    )


def _resolve_pending_fixes(app_key: str, check_name: str) -> None:
    """Mark pending_fixes for this (app,check) as resolved on a passing check.

    Also updates fix_history outcome=success for any pending fixes for the app.
    """
    try:
        import time as _ft
        with StateDB() as _fdb:
            _pending = _fdb.execute(
                """SELECT id FROM pending_fixes
                   WHERE app_key=? AND check_name=? AND status='pending'""",
                (app_key, check_name),
            ).fetchall()
            for _pf in _pending:
                _fdb.execute(
                    "UPDATE pending_fixes SET status='resolved', resolved_at=? WHERE id=?",
                    (int(_ft.time()), _pf["id"]),
                )
            _fdb.execute(
                """UPDATE fix_history SET outcome='success'
                   WHERE app_key=? AND outcome='pending'""",
                (app_key,),
            )
    except Exception:
        pass


def _record_healthy(app_key: str, check_name: str, result: CheckResult) -> None:
    """Persist a passing health-check outcome."""
    with StateDB() as db:
        db.upsert_health_check(
            "app", app_key, check_name,
            status="ok", summary=f"OK ({result.response_time_ms:.0f}ms)",
        )


async def _try_self_heal(app_key: str, manifest: Any, check_def: Any,
                         result: CheckResult) -> Any | None:
    """Walk manifest.self_heal entries looking for a match for this check.

    On match: invoke the heal action and update result.auto_healed; returns the
    matched entry. With no match but a non-empty list, returns the LAST entry
    (preserves the original loop-variable semantics for the auto_fix recording
    in `_record_unhealthy`). Returns None when self_heal is empty.
    """
    last = None
    for heal in manifest.self_heal:
        last = heal
        if heal.condition == check_def.name or heal.condition in (result.message or ""):
            healed = await _attempt_self_heal(app_key, heal.action, result)
            result.auto_healed = healed
            return heal
    return last


def _mass_failure_diagnosis(app_key: str, result: CheckResult) -> bool:
    """If ≥4 apps are currently failing, mark this result as escalation.

    Returns True when the short-circuit fired — caller should skip per-app
    LLM diagnosis, notification, and DB recording (preserves the original
    `continue` semantics so mass-failure results are not double-recorded).
    """
    try:
        with StateDB() as _mdb:
            _mass = _mdb.execute(
                """SELECT COUNT(DISTINCT subject_key) as n FROM health_checks
                   WHERE status IN ('error','warning')
                   AND checked_at >= ?""",
                (int(time.time()) - 300,),
            ).fetchone()
        if _mass and _mass["n"] >= 4 and app_key not in ("postgres", "redis", "traefik"):
            result.llm_diagnosis = (
                f"[INFRASTRUCTURE EVENT | confidence=90%] "
                f"{_mass['n']} apps failing simultaneously — likely shared root cause. "
                f"Check: managed services (postgres/redis), storage mounts, "
                f"Docker daemon health, and Traefik status before diagnosing {app_key} individually."
            )
            result.action_type = "escalate"
            return True
    except Exception:
        pass
    return False


def _filter_error_logs(app_key: str) -> str:
    """Pull recent docker logs and keep only error/warn lines (signal over noise).

    Falls back to the raw 2KB tail when no error keywords match. Returns
    a placeholder string when logs are unreachable.
    """
    try:
        from backend.core import docker_client
        raw_logs = docker_client.container_logs(app_key, tail=200)
        error_lines = [l for l in raw_logs.splitlines()
                       if any(k in l.lower() for k in
                              ("error", "warn", "exception", "fatal",
                               "panic", "killed", "oom"))]
        if error_lines:
            return "\n".join(error_lines[-20:])
        return raw_logs[-2000:]
    except Exception:
        return "(logs unavailable)"


async def _collect_net_checks(app_key: str, container_name: str) -> dict[str, bool]:
    """Probe TCP reachability from inside the container to its wired deps."""
    _net_targets: list[tuple[str, int]] = []
    try:
        with StateDB() as _ndb:
            _wires = _ndb.execute(
                """SELECT a2.container_name, a2.web_port
                   FROM wiring w
                   JOIN apps a1 ON a1.id = w.source_app_id
                   JOIN apps a2 ON a2.id = w.target_app_id
                   WHERE a1.key = ? AND w.status = 'active'""",
                (app_key,),
            ).fetchall()
        _net_targets = [(w["container_name"] or "", w["web_port"] or 0)
                        for w in _wires if w["web_port"]]
    except Exception:
        pass
    return await _container_net_reachability(container_name, _net_targets)


async def _diagnose_with_llm(app_key: str, container_name: str,
                             runtime_state: dict[str, Any], result: CheckResult,
                             ollama_url: str) -> bool:
    """Mass-failure short-circuit + filtered-logs + net-checks + LLM call.

    Returns True iff the mass-failure short-circuit fired (caller skips
    notification + recording — preserves original `continue` semantics).
    """
    if _mass_failure_diagnosis(app_key, result):
        return True
    logs = _filter_error_logs(app_key)
    runtime_state["network_checks"] = await _collect_net_checks(app_key, container_name)

    from backend.core.llm_router import best_model_for as _best_model
    _model_rec = _best_model("reasoning")
    _model_name = (
        _model_rec.ollama_name or _model_rec.filename.replace(".gguf", "")
        if _model_rec else "phi4-mini"
    )
    result.llm_diagnosis = await _llm_diagnose(
        app_key, result, logs,
        ollama_url=ollama_url,
        model=_model_name,
    )
    import json as _rj
    result.detail = _rj.dumps({
        "restart_count":   runtime_state.get("restart_count"),
        "exit_code":       runtime_state.get("exit_code"),
        "oom_killed":      runtime_state.get("oom_killed"),
        "config_disk_pct": runtime_state.get("config_disk_pct"),
        "network_checks":  runtime_state.get("network_checks", {}),
    })
    return False


async def _notify_failure(app_key: str, manifest: Any, result: CheckResult,
                          ntfy_url: str, ntfy_topic: str) -> None:
    """Send the 'unhealthy' or 'auto-fixed' ntfy notification for a failing check."""
    title = f"{'🔧 Auto-fixed' if result.auto_healed else '⚠️ Unhealthy'}: {manifest.display_name}"
    msg_parts = [f"Check: {result.check_name}", f"Error: {result.message}"]
    if result.llm_diagnosis:
        msg_parts.append(f"Diagnosis: {result.llm_diagnosis}")
    if result.auto_healed:
        msg_parts.append("Container restarted automatically.")
    sent = await _send_notification(
        title=title,
        message="\n".join(msg_parts),
        priority="high" if not result.auto_healed else "default",
        ntfy_url=ntfy_url,
        topic=ntfy_topic,
    )
    result.notification_sent = sent


def _record_unhealthy(app_key: str, manifest: Any, check_def: Any,
                      result: CheckResult, heal_entry: Any | None) -> None:
    """Persist a failing/auto-fixed health-check outcome and history row."""
    _hc_status = "warning" if not result.auto_healed else "ok"
    with StateDB() as db:
        db.upsert_health_check(
            "app", app_key, check_def.name,
            status=_hc_status,
            summary=result.message,
            auto_fix=heal_entry.action if (manifest.self_heal and heal_entry) else None,
        )
        if _hc_status in ("error", "warning"):
            try:
                import time as _t
                db.execute(
                    "INSERT INTO health_check_history "
                    "(subject_type,subject_key,check_name,status,summary,checked_at) "
                    "VALUES ('app',?,?,?,?,?)",
                    (app_key, check_def.name, _hc_status,
                     result.message[:500], int(_t.time()))
                )
            except Exception:
                pass


async def _maybe_perf_warn(app_key: str, manifest: Any, result: CheckResult,
                           ntfy_url: str, ntfy_topic: str) -> None:
    """Send a performance-disable nudge for slow ENHANCEMENT-tier apps."""
    criticality = get_criticality(app_key)
    slow = result.response_time_ms > PERF_THRESHOLDS["api_response_seconds"] * 1000
    if (
        slow
        and criticality == Criticality.ENHANCEMENT
        and not result.auto_healed
    ):
        log.warning(
            "%s response %.0fms exceeds threshold — offering disable",
            app_key, result.response_time_ms
        )
        await _send_notification(
            title=f"⏱️ Performance: {manifest.display_name} is slow",
            message=(
                f"{manifest.display_name} responded in {result.response_time_ms:.0f}ms "
                f"(threshold: {PERF_THRESHOLDS['api_response_seconds']*1000:.0f}ms). "
                f"Consider disabling it to free resources."
            ),
            priority="default",
            ntfy_url=ntfy_url, topic=ntfy_topic,
        )


async def check_app(app_key: str, ollama_url: str, ntfy_url: str, ntfy_topic: str) -> list[CheckResult]:
    """Run all health checks for a single app — orchestrator over the helpers above.

    Step 4.1 wire-up: thin timing wrapper around the real implementation
    in `_check_app_inner`. Outcome label is `ok` when every CheckResult
    is ok (or no checks ran), otherwise `error`.
    """
    from backend.core.metrics import health_check_duration_seconds
    _t0 = time.monotonic()
    results: list[CheckResult] = []
    try:
        results = await _check_app_inner(
            app_key, ollama_url, ntfy_url, ntfy_topic,
        )
        return results
    finally:
        outcome = "ok" if all(r.ok for r in results) else "error"
        health_check_duration_seconds.labels(
            app_key=app_key, outcome=outcome,
        ).observe(time.monotonic() - _t0)


async def _check_app_inner(
    app_key: str, ollama_url: str, ntfy_url: str, ntfy_topic: str,
) -> list[CheckResult]:
    """Real check_app body — wrapped by check_app() above for timing."""
    results: list[CheckResult] = []

    manifest = _load_manifest_or_skip(app_key)
    if manifest is None:
        return results

    with StateDB() as db:
        app = db.get_app(app_key)
    if not app or app.status in ("disabled", "removing", "installing"):
        return results

    _host_port = getattr(app, "host_port", None) or getattr(manifest, "web_port", None)
    base_url = f"http://localhost:{_host_port}" if _host_port else ""

    frag_results = _precheck_fragment(app_key, app, manifest)
    if frag_results is not None:
        return frag_results

    container_name = (app.container_name or app_key) if app else app_key
    grace_s = int(getattr(manifest, "start_grace_s", 0) or _DOCKER_DEFAULT_GRACE_S)
    in_grace, container_age = _in_startup_grace(container_name, grace_s)

    runtime_state = _container_runtime_state(container_name)
    runtime_state["config_disk_pct"] = _config_disk_pct(
        getattr(app, "config_path", None) if app else None
    )

    oom_results = _precheck_oom(app_key, manifest, runtime_state, in_grace)
    if oom_results is not None:
        return oom_results

    if in_grace and container_age >= 0:
        return _grace_results(app_key, manifest, container_age, grace_s)

    for check_def in manifest.health_checks:
        result = await _run_one_check(
            app_key, check_def, base_url, _host_port, container_name
        )

        if result.ok:
            _resolve_pending_fixes(app_key, check_def.name)
            _record_healthy(app_key, check_def.name, result)
            results.append(result)
            continue

        # Failure path
        heal_entry = await _try_self_heal(app_key, manifest, check_def, result)

        if _llm_state.get("status") not in ("disabled",):
            mass_failure = await _diagnose_with_llm(
                app_key, container_name, runtime_state, result, ollama_url
            )
            if mass_failure:
                continue  # original semantics: skip notification + recording + append

        await _notify_failure(app_key, manifest, result, ntfy_url, ntfy_topic)
        _record_unhealthy(app_key, manifest, check_def, result, heal_entry)
        await _maybe_perf_warn(app_key, manifest, result, ntfy_url, ntfy_topic)
        results.append(result)

    return results


async def run_health_cycle(
    ollama_url: str = "http://ollama:11434",  # Docker container hostname (correct default)
    ntfy_url: str = "http://ntfy:80",
    ntfy_topic: str = "mediastack",
) -> HealthRun:
    """Run one full health check cycle across all installed apps."""
    run = HealthRun(started_at=time.monotonic())
    run.llm_agent_state = _llm_state.get("status", "unknown")

    # Skip LLM phase if no model is configured or Ollama is not running
    _llm_available = _llm_state.get("status") == "ready"
    if not _llm_available:
        log.debug(
            "LLM health agent inactive (status: %s) — "
            "install Ollama and download a model to enable AI health monitoring.",
            _llm_state.get("status", "unknown"),
        )

    with StateDB() as db:
        apps = db.get_all_apps(status="running")

    run.apps_checked = len(apps)

    # Wrap each check_app in a timeout so a single hung app (e.g. DNS resolution
    # stuck, LLM endpoint blocked) can't stall the entire health cycle.
    # 30s per app is generous — http checks have their own 10s timeout internally.
    async def _check_with_timeout(app_key: str) -> list[CheckResult]:
        try:
            return await asyncio.wait_for(
                check_app(app_key, ollama_url=ollama_url, ntfy_url=ntfy_url, ntfy_topic=ntfy_topic),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            log.warning("Health check for '%s' timed out after 30s — skipping.", app_key)
            return []

    tasks = [_check_with_timeout(app.key) for app in apps]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    for app_results in all_results:
        if isinstance(app_results, BaseException):
            continue
        for r in app_results:
            run.results.append(r)
            if r.ok or r.auto_healed:
                run.apps_healthy += 1
            else:
                run.apps_degraded += 1

    return run
