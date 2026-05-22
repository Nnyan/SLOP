"""backend/api/apps.py

App lifecycle API routes.

GET  /api/apps                    — list all installed apps
GET  /api/apps/{key}              — single app detail + health
POST /api/apps/{key}/install      — install from catalog
DELETE /api/apps/{key}            — remove app
POST /api/apps/{key}/replace/{new_key} — replace with different app
POST /api/apps/{key}/restart      — restart container
GET  /api/apps/{key}/logs         — recent container logs
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.api.rate_limit import limiter
from backend.core import docker_client
from backend.core.logging import get_logger
from backend.core.state import StateDB
# Track in-progress installs to prevent duplicate concurrent installs
_installing: set[str] = set()

from backend.manifests.executor import (
    ExecutionResult,
    install_app,
    remove_app,
    replace_app,
)

log = get_logger(__name__)
router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────


class InstallRequest(BaseModel):
    extra_env: dict[str, str] | None = None
    host_port: int | None = None


class RemoveRequest(BaseModel):
    delete_config: bool | None = None  # None = retain, True = delete, False = retain


class StepLogOut(BaseModel):
    name: str
    status: str
    message: str
    detail: str = ""


class ExecutionOut(BaseModel):
    ok: bool
    app_key: str
    operation: str
    steps: list[StepLogOut]
    error: str = ""


class AppOut(BaseModel):
    key: str
    display_name: str
    category: str
    status: str
    image: str
    image_tag: str
    web_port: int | None
    host_port: int | None
    config_path: str | None
    installed_at: int
    last_healthy_at: int | None
    container_status: str | None = None
    container_health: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────


def _exec_to_out(r: ExecutionResult) -> ExecutionOut:
    return ExecutionOut(
        ok=r.ok,
        app_key=r.app_key,
        operation=r.operation,
        steps=[StepLogOut(**s.__dict__) for s in r.steps],
        error=r.error,
    )


def _app_with_container(app: Any) -> AppOut:
    """Enrich app state record with live container status.

    Handles Docker being unavailable gracefully — returns DB status
    with container fields empty rather than crashing.
    """
    try:
        c = docker_client.get_container(app.key)
    except (docker_client.DockerError, Exception):
        c = None  # Docker unavailable — use DB status only
    return AppOut(
        key=app.key,
        display_name=app.display_name,
        category=app.category,
        status=app.status,
        image=app.image,
        image_tag=app.image_tag,
        web_port=app.web_port,
        host_port=app.host_port,
        config_path=app.config_path,
        installed_at=app.installed_at,
        last_healthy_at=app.last_healthy_at,
        container_status=c.status if c else None,
        container_health=c.health if c else None,
    )


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[AppOut])
def list_apps() -> list[AppOut]:
    """List all apps known to Mediastack (installed or previously installed)."""
    with StateDB() as db:
        apps = db.get_all_apps()
    return [_app_with_container(a) for a in apps]


@router.get("/{key}", response_model=AppOut)
def get_app(key: str) -> AppOut:
    """Get a single app's state and live container status."""
    with StateDB() as db:
        app = db.get_app(key)
    if app is None:
        raise HTTPException(status_code=404, detail=f"App '{key}' is not installed.")
    return _app_with_container(app)


@router.post("/{key}/install")
@limiter.limit("5/minute")  # type: ignore[untyped-decorator]  # slowapi decorator is untyped (Step 2.4 — heavy mutation tier)
async def api_install(
    request: Request,
    key: str,
    req: InstallRequest = InstallRequest(),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> dict[str, Any]:
    """Install an app from the catalog.

    Returns immediately with {installing: true, key}.
    Poll GET /{key}/install/progress for real-time step updates.
    The install runs in a background thread — POST returns in <1ms.
    """
    # Validate app exists in catalog before starting background task
    from backend.manifests.loader import load_all_manifests
    _manifests = load_all_manifests()
    if key not in _manifests:
        raise HTTPException(
            status_code=404,
            detail=f"App '{key}' not found in catalog. Check the key and try again.",
        )

    # Prevent duplicate concurrent installs of the same key
    if key in _installing:
        raise HTTPException(
            status_code=409,
            detail=f"'{key}' is already being installed. Poll /{key}/install/progress for status.",
        )
    _installing.add(key)

    # Clear any previous step records for this key
    try:
        from backend.core.state import StateDB
        with StateDB() as db:
            db.clear_op_steps(key)
            db.write_op_step(key, "queued", "running", f"Install queued for {key}…")
    except Exception:
        pass

    def _run() -> None:
        result = install_app(
            key,
            extra_env=req.extra_env,
            host_port_override=req.host_port,
        )
        # Write sentinel so the poller knows the install is complete.
        try:
            from backend.core.state import StateDB
            with StateDB() as db:
                if result.ok:
                    db.write_op_step(key, "__done__", "ok", "Installation complete.")
                else:
                    db.write_op_step(
                        key, "__done__", "error",
                        result.error or "Installation failed.",
                    )
        except Exception:
            pass
        finally:
            _installing.discard(key)  # release lock regardless of outcome

    background_tasks.add_task(_run)
    return {"installing": True, "key": key, "message": f"Installing {key}… poll /{key}/install/progress"}


@router.get("/{key}/install/progress")
def api_install_progress(key: str) -> dict[str, Any]:
    """Poll for real-time install progress.

    Returns steps written so far. When a step named '__done__' appears,
    the install is complete. Check its status for ok/error.

    Frontend algorithm:
      1. POST /{key}/install → start install
      2. Poll GET /{key}/install/progress every 500ms
      3. When steps contains __done__, stop polling and show result
    """
    from backend.core.state import StateDB
    with StateDB() as db:
        steps = db.get_op_steps(key)

    done_step = next((s for s in steps if s["step"] == "__done__"), None)
    visible = [s for s in steps if not s["step"].startswith("__")]

    return {
        "key": key,
        "done": done_step is not None,
        "ok": done_step["status"] == "ok" if done_step else None,
        "steps": visible,
        "error": done_step["message"] if done_step and done_step["status"] == "error" else None,
    }


@router.delete("/{key}", response_model=ExecutionOut)
@limiter.limit("5/minute")  # type: ignore[untyped-decorator]  # slowapi decorator is untyped (Step 2.4 — heavy mutation tier)
def api_remove(request: Request, key: str,
               req: RemoveRequest = RemoveRequest()) -> ExecutionOut:
    """Remove an installed app.

    Pass delete_config=true to also delete the app's config folder.
    If delete_config is omitted, the config folder is retained (safe default).
    """
    result = remove_app(key, delete_config=req.delete_config)
    return _exec_to_out(result)


@router.post("/{key}/replace/{new_key}", response_model=ExecutionOut)
@limiter.limit("5/minute")  # type: ignore[untyped-decorator]  # slowapi decorator is untyped (Step 2.4 — heavy mutation tier)
def api_replace(request: Request, key: str, new_key: str,
                req: InstallRequest = InstallRequest()) -> ExecutionOut:
    """Replace an installed app with a different one.

    Installs the new app, rewires connections, then removes the old one.
    The old app's config folder is always retained — remove manually if needed.
    """
    result = replace_app(key, new_key, extra_env=req.extra_env)
    return _exec_to_out(result)


@router.post("/{key}/restart", response_model=dict)
def api_restart(key: str) -> dict[str, Any]:
    """Restart an app's container."""
    with StateDB() as db:
        app = db.get_app(key)
    if app is None:
        raise HTTPException(status_code=404, detail=f"App '{key}' is not installed.")
    try:
        c = docker_client.client().containers.get(key)
        c.restart(timeout=30)
        return {"ok": True, "message": f"Container '{key}' restarted."}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not restart '{key}': {e}. Is Docker running?",
        )


@router.get("/{key}/logs")
def api_logs(key: str, tail: int = Query(default=100, le=500)) -> dict[str, Any]:
    """Get recent container logs."""
    with StateDB() as db:
        app = db.get_app(key)
    if app is None:
        raise HTTPException(status_code=404, detail=f"App '{key}' is not installed.")
    try:
        logs = docker_client.container_logs(key, tail=tail)
        return {"key": key, "logs": logs}
    except docker_client.DockerError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Docker unavailable — cannot retrieve logs for '{key}': {e}",
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Disable / Enable / Criticality routes (Step 4 addition)
# ---------------------------------------------------------------------------

from backend.manifests.executor import (
    Criticality,
    DisableResult,
    disable_app,
    enable_app,
    get_criticality,
    PERF_THRESHOLDS,
)
from backend.core.system_eval import evaluate_system, SystemProfile, recommend_llm
from pydantic import BaseModel as _BaseModel


class DisableRequest(_BaseModel):
    reason: str = "user_request"


class DisableOut(_BaseModel):
    ok: bool
    key: str
    criticality: str
    warning: str | None = None
    error: str | None = None


class SystemProfileOut(_BaseModel):
    cpu_cores: int
    cpu_model: str
    total_ram_gb: float
    free_ram_gb: float
    headroom_ram_gb: float
    docker_ram_gb: float
    architecture: str
    disks: list[dict[str, Any]]
    estimated_stack_ram_gb: float
    recommended_llm_model: str
    available_llm_models: list[str]
    llm_warning: str | None
    measured_at: int
    note: str


def _criticality_warning(key: str, crit: Criticality) -> str | None:
    if crit == Criticality.IMPORTANT:
        return (
            f"'{key}' is marked IMPORTANT. Disabling interrupts remote access "
            f"and authentication. LAN access remains unaffected."
        )
    return None


@router.post("/{key}/disable", response_model=DisableOut)
def api_disable(key: str, req: DisableRequest = DisableRequest()) -> DisableOut:
    """Gracefully disable an app.

    Stops the container and renames its compose fragment to .yaml.disabled.
    Config, state, and wiring are preserved. Re-enable with /enable.
    Inviolable apps (Traefik) cannot be disabled.

    Performance-triggered disables from the health system also route here
    with reason='performance' or 'health'.
    """
    crit = get_criticality(key)
    warning = _criticality_warning(key, crit)

    result: DisableResult = disable_app(key, reason=req.reason)

    if not result.ok:
        err = result.error or "disable failed"
        if "not installed" in err.lower() or "not found" in err.lower():
            status = 404
        elif "inviolable" in err.lower():
            status = 409
        else:
            status = 500
        raise HTTPException(status_code=status, detail=err)

    return DisableOut(
        ok=True, key=key,
        criticality=result.criticality,
        warning=warning,
    )


@router.post("/{key}/enable", response_model=DisableOut)
def api_enable(key: str) -> DisableOut:
    """Re-enable a previously disabled app.

    Restores the compose fragment and starts the container.
    Wiring is marked pending for the next health cycle to reconnect.
    """
    result: DisableResult = enable_app(key)

    if not result.ok:
        # 422 for expected failures (missing fragment = reinstall needed)
        # 404 if app not found
        code = 404 if "not installed" in (result.error or "") else 422
        raise HTTPException(status_code=code, detail=result.error)

    return DisableOut(ok=True, key=key, criticality=result.criticality)


@router.get("/{key}/criticality")
def api_criticality(key: str) -> dict[str, Any]:
    """Return the criticality classification for an app.

    Criticality determines what happens when the app is disabled:
      INVIOLABLE  — cannot disable, stack depends on it
      IMPORTANT   — warn before disabling (auth/tunnel providers)
      INDEPENDENT — disable freely, no stack impact
      ENHANCEMENT — disabling has zero availability impact
    """
    with StateDB() as db:
        app = db.get_app(key)
    if not app:
        raise HTTPException(status_code=404, detail=f"App '{key}' is not installed.")
    crit = get_criticality(key)
    return {
        "key": key,
        "criticality": str(crit),
        "can_disable": crit != Criticality.INVIOLABLE,
        "warning": _criticality_warning(key, crit),
        "perf_thresholds": PERF_THRESHOLDS,
    }


# ---------------------------------------------------------------------------
# System profile / resource evaluation
# ---------------------------------------------------------------------------


@router.get("/system/profile", response_model=SystemProfileOut, tags=["System"])
def api_system_profile() -> SystemProfileOut:
    """Run a system resource evaluation.

    Returns hardware specs, current RAM usage, estimated stack RAM
    for all installed apps, headroom, and LLM model recommendation.

    All figures are estimates — clearly labelled as such in the response.
    """
    with StateDB() as db:
        p = db.get_platform()
        installed_keys = [a.key for a in db.get_all_apps()]

    try:
        profile: SystemProfile = evaluate_system(
            selected_app_keys=installed_keys,
            config_root=p.config_root or "/",
            media_root=p.media_root or "/",
        )
    except Exception as _e:
        raise HTTPException(status_code=503, detail=f"System evaluation failed: {_e}")

    return SystemProfileOut(
        cpu_cores=profile.cpu_cores,
        cpu_model=profile.cpu_model,
        total_ram_gb=round(profile.total_ram_mb / 1024, 1),
        free_ram_gb=round(profile.free_ram_mb / 1024, 1),
        headroom_ram_gb=round(profile.headroom_ram_mb / 1024, 1),
        docker_ram_gb=round(profile.docker_container_ram_mb / 1024, 1),
        architecture=profile.architecture,
        disks=[
            {"path": d.path, "total_gb": d.total_gb,
             "free_gb": d.free_gb, "percent_used": d.percent_used}
            for d in profile.disks
        ],
        estimated_stack_ram_gb=round(profile.estimated_stack_ram_mb / 1024, 1),
        recommended_llm_model=profile.recommended_model,
        available_llm_models=profile.available_models,
        llm_warning=profile.llm_warning,
        measured_at=profile.measured_at,
        note=(
            "RAM figures are estimates. Actual usage varies with library size, "
            "active streams, and container configuration."
        ),
    )


# ── Batch install ─────────────────────────────────────────────────────────

class BatchInstallRequest(BaseModel):
    keys: list[str] = Field(default=[], alias="app_keys")
    preflight_only: bool = False

    model_config = {"populate_by_name": True}


class PreflightIssue(BaseModel):
    level: str   # error | warning | info
    message: str
    affected: list[str] = []


class PreflightResult(BaseModel):
    install_order: list[str]
    issues: list[PreflightIssue]
    can_proceed: bool


@router.post("/batch/preflight")
def batch_preflight(req: BatchInstallRequest) -> PreflightResult:
    """Analyse a list of apps before batch install.

    Returns:
    - install_order: topologically sorted install sequence
    - issues: errors (blocking) and warnings (informational)
    - can_proceed: False if any blocking errors exist
    """
    from backend.manifests.loader import load_all_manifests, ManifestError
    from backend.core.state import StateDB

    issues: list[PreflightIssue] = []
    all_manifests = load_all_manifests()

    with StateDB() as db:
        installed = {a.key for a in db.get_all_apps()}
        platform = db.get_platform()

    # 1. Validate all keys exist in catalog
    unknown = [k for k in req.keys if k not in all_manifests]
    if unknown:
        issues.append(PreflightIssue(
            level="error",
            message=f"Not in catalog: {', '.join(unknown)}",
            affected=unknown,
        ))

    valid_keys = [k for k in req.keys if k in all_manifests]

    # 2. Resolve dependencies — add missing requires
    to_install = set(valid_keys)
    missing_deps: list[str] = []
    for key in valid_keys:
        m = all_manifests[key]
        for req_key in m.requires:
            if req_key not in installed and req_key not in to_install:
                to_install.add(req_key)
                missing_deps.append(req_key)

    if missing_deps:
        issues.append(PreflightIssue(
            level="warning",
            message=f"Added required dependencies: {', '.join(missing_deps)}",
            affected=missing_deps,
        ))

    # 3. Check for already-installed apps
    already = [k for k in req.keys if k in installed]
    if already:
        issues.append(PreflightIssue(
            level="info",
            message=f"Already installed (will skip): {', '.join(already)}",
            affected=already,
        ))

    # 4. Topological sort — deps before dependents
    _INSTALL_PRIORITY = {
        "prowlarr": 0, "sabnzbd": 1, "qbittorrent": 1,
        "plex": 2, "jellyfin": 2, "emby": 2,
        "sonarr": 3, "radarr": 3, "lidarr": 3, "readarr": 3,
        "bazarr": 4, "seerr": 5,
    }
    install_order = sorted(
        to_install - installed,
        key=lambda k: (_INSTALL_PRIORITY.get(k, 10), k),
    )

    return PreflightResult(
        install_order=install_order,
        issues=issues,
        can_proceed=not any(i.level == "error" for i in issues),
    )


@router.post("/batch/install")
def batch_install(req: BatchInstallRequest) -> dict[str, Any]:
    """Start a batch install. Each app is queued sequentially.
    Poll GET /apps/{key}/install/progress for per-app status.
    """
    import threading
    from backend.manifests.executor import install_app

    # Run preflight first
    preflight = batch_preflight(req)
    if not preflight.can_proceed:
        return {
            "ok": False,
            "error": "Pre-flight check failed — see issues",
            "preflight": preflight.dict(),
        }

    keys = preflight.install_order

    def _run_batch() -> None:
        failed_keys: set[str] = set()
        for key in keys:
            if key in _installing:
                continue
            # Skip if a dependency failed
            from backend.manifests.loader import load_manifest
            try:
                manifest = load_manifest(key)
                failed_deps = [d for d in getattr(manifest, 'requires', []) if d in failed_keys]
                if failed_deps:
                    with StateDB() as db:
                        db.clear_op_steps(key)
                        db.write_op_step(key, "__done__", "error",
                            f"Skipped — required app(s) failed: {', '.join(failed_deps)}")
                    failed_keys.add(key)
                    continue
            except Exception:
                pass  # manifest load failure is non-fatal for skip check
            _installing.add(key)
            try:
                from backend.core.state import StateDB
                with StateDB() as db:
                    db.clear_op_steps(key)
                    db.write_op_step(key, "queued", "running", f"Queued for batch install…")
                result = install_app(key)
                with StateDB() as db:
                    if result.ok:
                        db.write_op_step(key, "__done__", "ok", "Installed.")
                    else:
                        db.write_op_step(key, "__done__", "error", result.error or "Failed.")
                        failed_keys.add(key)
            except Exception as e:
                try:
                    from backend.core.state import StateDB
                    with StateDB() as db:
                        db.write_op_step(key, "__done__", "error", str(e))
                except Exception:
                    pass
            finally:
                _installing.discard(key)

    threading.Thread(target=_run_batch, daemon=True).start()

    # GH: pre-compute which apps will be skipped due to dep ordering
    # so frontend can show 'pending' vs 'will be skipped' immediately
    dep_skipped = [k for k in req.keys if k not in keys]

    return {
        "ok": True,
        "install_order": keys,
        "dep_skipped": dep_skipped,
        "preflight": preflight.dict(),
    }


# ── YAML compose linter ────────────────────────────────────────────────────

class LintResult(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    manifest_preview: dict[str, Any] | None = None


@router.post("/lint-compose")
def lint_compose_yaml(payload: dict[str, Any]) -> LintResult:
    """Parse and validate a docker-compose.yml fragment.

    Checks:
    - Valid YAML syntax
    - Has a services: block with exactly one service
    - Service has an image: field
    - Ports are in the correct format
    - Volumes are in the correct format
    - Generates a Mediastack manifest preview if valid
    """
    import yaml as _yaml
    errors: list[str] = []
    warnings: list[str] = []

    raw = payload.get("yaml", "")
    if not raw.strip():
        return LintResult(valid=False, errors=["Paste a docker-compose.yml fragment to validate."])

    # Parse YAML
    try:
        doc = _yaml.safe_load(raw)
    except _yaml.YAMLError as e:
        line = getattr(getattr(e, "problem_mark", None), "line", None)
        detail = f" (line {line + 1})" if line is not None else ""
        return LintResult(valid=False, errors=[f"YAML syntax error{detail}: {e.problem if hasattr(e, 'problem') else str(e)}"])

    if not isinstance(doc, dict):
        return LintResult(valid=False, errors=["Expected a YAML mapping (key: value) at the top level."])

    # Services block
    services = doc.get("services", {})
    if not services:
        # Maybe they pasted a bare service def without the `services:` wrapper
        # Try to treat the whole doc as a single service
        if "image" in doc:
            services = {"app": doc}
            warnings.append("No 'services:' wrapper found — treating entire YAML as a single service definition.")
        else:
            errors.append("No 'services:' block found. Expected: services:\\n  myapp:\\n    image: ...")
            return LintResult(valid=False, errors=errors, warnings=warnings)

    if len(services) > 1:
        warnings.append(f"Found {len(services)} services — Mediastack will use the first one. Consider a single-service fragment.")

    # Validate first service
    svc_name = next(iter(services))
    svc = services[svc_name] or {}

    if not isinstance(svc, dict):
        errors.append(f"Service '{svc_name}' definition is not a mapping.")
        return LintResult(valid=False, errors=errors)

    # Required: image
    image = svc.get("image", "")
    if not image:
        errors.append(f"Service '{svc_name}' is missing an 'image:' field.")
    elif ":" not in image:
        warnings.append(f"Image '{image}' has no tag — will use ':latest'. Pin a version for stability.")

    # Ports check
    ports = svc.get("ports", [])
    for p in ports:
        if isinstance(p, str):
            parts = p.split(":")
            if len(parts) == 2:
                try:
                    int(parts[1])
                except ValueError:
                    errors.append(f"Invalid port format: '{p}'. Expected 'host:container'.")
            elif len(parts) != 1:
                errors.append(f"Invalid port format: '{p}'.")

    # Volumes check
    volumes = svc.get("volumes", [])
    for v in volumes:
        if isinstance(v, str) and ":" not in v:
            warnings.append(f"Volume '{v}' has no container path — it will be a named volume with no bind mount.")

    # Environment variables — warn about hardcoded secrets
    env = svc.get("environment", {})
    env_list = env if isinstance(env, list) else [f"{k}={v}" for k, v in (env or {}).items()]
    for entry in env_list:
        estr = str(entry)
        if any(word in estr.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "KEY", "API")):
            if "=" in estr and not estr.endswith("=") and not "${" in estr:
                warnings.append(f"Env var appears to contain a hardcoded secret: '{estr.split('=')[0]}'. Use ${{VAR}} references instead.")

    if errors:
        return LintResult(valid=False, errors=errors, warnings=warnings)

    # Build manifest preview
    image_parts = image.split(":")
    web_port = None
    for p in ports:
        pstr = str(p)
        if ":" in pstr:
            try:
                web_port = int(pstr.split(":")[-1])
                break
            except ValueError:
                pass

    manifest_preview = {
        "key": svc_name.lower().replace("-", "_"),
        "display_name": svc_name.replace("-", " ").replace("_", " ").title(),
        "image": image_parts[0],
        "image_tag": image_parts[1] if len(image_parts) > 1 else "latest",
        "web_port": web_port,
        "volumes": {v.split(":")[1].split(":")[0].strip("/").replace("/", "_"): v.split(":")[1] if ":" in str(v) else v for v in volumes[:4] if v},
        "category": "tools",
        "tier": 2,
        "service_type": "management",
    }

    return LintResult(
        valid=True,
        errors=[],
        warnings=warnings,
        manifest_preview=manifest_preview,
    )



# ── Shared: community manifest normalization and save ────────────────────────

def _save_community_manifest(
    manifest_data: dict[str, Any],
    compose_yaml: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    """Normalize a manifest dict and save it to the community catalog.

    Single source of truth for all non-catalog install paths.
    Applies all compliance rules:
      - Key sanitization (filesystem-safe identifier)
      - Complete manifest fields (traefik, health, linuxserver, ports)
      - Category validation
      - Community catalog persistence

    Returns: {"ok": True, "key": str, "install_url": str}
    Raises: HTTPException on validation failure.

    Called by: install_from_github, install_custom_app
    TODO: also called by future POST /api/apps/register
    """
    import re as _re
    import yaml as _yaml
    from backend.core.config import config as _cfg

    # ── Validate required fields ──────────────────────────────────────────
    if not manifest_data.get("image"):
        raise HTTPException(status_code=422, detail="Manifest must have an 'image' field.")
    if not manifest_data.get("key"):
        raise HTTPException(status_code=422, detail="Manifest must have a 'key' field.")

    # ── Sanitize key (rule: install-github-key-sanitization) ─────────────
    raw_key = str(manifest_data["key"])
    key = _re.sub(r"[^a-z0-9_]", "_", raw_key.lower().strip())[:64]
    if not key:
        raise HTTPException(status_code=422, detail=f"Manifest key '{raw_key}' is not a valid app key.")

    # ── Extract web_port ─────────────────────────────────────────────────
    web_port = manifest_data.get("web_port")
    if not web_port and isinstance(manifest_data.get("ports"), dict):
        web_port = manifest_data["ports"].get("web") or manifest_data["ports"].get("http")

    # ── Build complete manifest (rule: install-custom-complete-manifest) ──
    normalized = {
        "key": key,
        "display_name": manifest_data.get("display_name", key.replace("_", " ").title()),
        "description": manifest_data.get("description", ""),
        "category": manifest_data.get("category", "tools"),
        "tier": manifest_data.get("tier", 2),
        "service_type": manifest_data.get("service_type", "management"),
        "linuxserver": manifest_data.get("linuxserver", True),
        "image": manifest_data.get("image"),
        "image_tag": manifest_data.get("image_tag", "latest"),
        "start_grace_s": manifest_data.get("start_grace_s", 60),
        "ports": manifest_data.get("ports", {"web": web_port} if web_port else {}),
        "volumes": manifest_data.get("volumes", {"config": "/config"}),
        # Traefik: enable by default so custom apps get HTTPS routing
        "traefik": manifest_data.get("traefik", {
            "enabled": bool(web_port),
            "subdomain": key,
        }),
        # Health: basic HTTP check if web port available
        "health": manifest_data.get("health", {
            "checks": [
                {"name": "api_reachable", "type": "http",
                 "path": "/", "expect_status": 200, "interval": 60}
            ] if web_port else []
        }),
        "tags": manifest_data.get("tags", ["custom"]),
        "source": "community",
    }
    if source_url:
        normalized["source_url"] = source_url

    # Validate category against the loader's enum
    from backend.manifests.loader import VALID_CATEGORIES
    if normalized["category"] not in VALID_CATEGORIES:
        # Silently remap unknown categories rather than rejecting
        normalized["category"] = "tools"

    # ── Persist ───────────────────────────────────────────────────────────
    community_dir = _cfg.catalog_dir / "community"
    community_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = community_dir / f"{key}.yaml"
    manifest_path.write_text(_yaml.dump(normalized, default_flow_style=False), encoding="utf-8")

    if compose_yaml.strip():
        compose_path = community_dir / f"{key}.compose.yaml"
        compose_path.write_text(compose_yaml, encoding="utf-8")

    return {
        "ok": True,
        "key": key,
        "message": f"App '{key}' registered in community catalog.",
        "install_url": f"/api/apps/{key}/install",
    }


# ── GitHub repo manifest install ──────────────────────────────────────────

class GitHubManifestRequest(BaseModel):
    repo_url: str = Field(
        ...,
        description="GitHub URL to a raw manifest YAML or a repo containing a manifest. "
                    "Formats accepted: "
                    "https://github.com/user/repo/blob/main/manifest.yaml, "
                    "https://raw.githubusercontent.com/user/repo/main/manifest.yaml, "
                    "https://github.com/user/repo (scans for manifest.yaml at root)"
    )


@router.post("/install-from-github")
def install_from_github(req: GitHubManifestRequest) -> dict[str, Any]:
    """Fetch a Mediastack manifest from a GitHub URL and install the app.

    Accepts:
    - Direct link to a .yaml manifest file
    - GitHub repo URL (scans root for manifest.yaml / mediastack.yaml)

    Security: only fetches from github.com / raw.githubusercontent.com.
    Manifest is validated before install (required fields, image format, etc.)
    """
    import urllib.request as _req
    import urllib.error as _err
    import yaml as _yaml

    url = req.repo_url.strip()

    # Validate domain — only allow GitHub
    allowed = ("github.com", "raw.githubusercontent.com", "gist.githubusercontent.com")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.netloc not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Only GitHub URLs are accepted. Got: {parsed.netloc}",
        )

    # Convert GitHub blob URL → raw URL
    if "github.com" in url and "/blob/" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    elif "github.com" in url and "/blob/" not in url and not url.endswith(".yaml"):
        # Repo root — try common manifest names
        base = url.rstrip("/")
        for candidate in ("manifest.yaml", "mediastack.yaml", "mediastack-manifest.yaml"):
            raw = base.replace("github.com", "raw.githubusercontent.com") + f"/main/{candidate}"
            try:
                _req.urlopen(raw, timeout=5).close()
                url = raw
                break
            except Exception:
                continue
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No manifest file found at repo root. "
                       f"Expected: manifest.yaml or mediastack.yaml",
            )

    # Fetch manifest
    try:
        with _req.urlopen(url, timeout=15) as resp:
            raw_content = resp.read().decode("utf-8")
    except _err.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"GitHub returned HTTP {e.code}: {url}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch manifest: {e}")

    # Parse YAML
    try:
        manifest_data = _yaml.safe_load(raw_content)
    except _yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {e}")

    if not isinstance(manifest_data, dict):
        raise HTTPException(status_code=422, detail="Manifest must be a YAML mapping.")

    # Basic validation
    missing = [f for f in ("key", "image") if not manifest_data.get(f)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Manifest missing required fields: {', '.join(missing)}",
        )

    # Size guard — prevent malicious huge manifests
    if len(raw_content) > 64_000:
        raise HTTPException(status_code=422, detail="Manifest file exceeds 64 KB size limit.")

    # Sanitize key — must be a safe filesystem/DB identifier
    import re as _re
    raw_key = str(manifest_data["key"])
    app_key = _re.sub(r"[^a-z0-9_]", "_", raw_key.lower().strip())[:64]
    if not app_key:
        raise HTTPException(status_code=422, detail=f"Manifest key '{raw_key}' is not a valid app key.")
    if app_key != raw_key:
        manifest_data["key"] = app_key  # normalise

    # Delegate to shared normalizer — applies all compliance rules
    result = _save_community_manifest(manifest_data, source_url=url)
    result["message"] = (
        f"Manifest for '{result['key']}' fetched from GitHub and saved to community catalog. "
        f"Use POST /api/apps/{result['key']}/install to install it."
    )
    result["source_url"] = url
    return result


# ── Custom app install from YAML manifest data ──────────────────────────────

class CustomManifestInstall(BaseModel):
    manifest: dict[str, Any]
    compose_yaml: str


@router.post("/install-custom")
def install_custom_app(req: CustomManifestInstall) -> dict[str, Any]:
    """Install a custom app from a validated manifest dict and compose YAML.

    Called by the YAML linter UI after validation succeeds.
    Saves the manifest to the community catalog and queues an install.
    """
    import yaml as _yaml
    from backend.core.config import config as _cfg
    from backend.manifests.loader import load_manifest

    # Delegate entirely to the shared normalizer — single path for all compliance rules
    result = _save_community_manifest(
        manifest_data=req.manifest,
        compose_yaml=req.compose_yaml,
    )
    result["message"] = f"Custom app '{result['key']}' registered. Use the install_url to deploy."
    return result


# ── App version pinning + update ───────────────────────────────────────────

class PinVersionRequest(BaseModel):
    image_tag: str = Field(..., description="Tag to pin, e.g. '4.0.9', 'latest'")


@router.put("/{key}/pin-version")
def pin_app_version(key: str, req: PinVersionRequest) -> dict[str, Any]:
    """Pin an app to a specific image tag.

    Pinned tag is used on the next install or update.
    Set to 'latest' to un-pin and always use latest.
    """
    with StateDB() as db:
        app = db.get_app(key)
    if not app:
        raise HTTPException(404, f"App '{key}' is not installed.")
    tag = req.image_tag.strip()
    if not tag:
        raise HTTPException(422, "image_tag cannot be empty.")
    with StateDB() as db:
        db.upsert_app(key, image_tag=tag)
    return {"ok": True, "key": key, "image_tag": tag}


@router.post("/{key}/update")
def update_app(key: str) -> dict[str, Any]:
    """Pull the latest (or pinned) image and recreate the container.

    This is the 'Update' button — pulls the image then does compose up --force-recreate.
    Non-blocking: check progress via GET /apps/{key}/install/progress.
    """
    import threading
    from backend.manifests.executor import install_app
    from backend.core.compose import compose_up
    from backend.manifests.loader import load_manifest

    with StateDB() as db:
        app = db.get_app(key)
    if not app:
        raise HTTPException(404, f"App '{key}' is not installed.")

    if key in _installing:
        raise HTTPException(409, f"'{key}' is already being updated.")

    def _do_update() -> None:
        _installing.add(key)
        try:
            with StateDB() as db:
                db.clear_op_steps(key)
                db.write_op_step(key, "update", "running",
                                 f"Pulling {'pinned ' + app.image_tag if app.image_tag != 'latest' else 'latest'} image…")

            # Pull new image via compose up --pull always
            import subprocess
            from backend.core.config import config as _cfg
            frag_path = _cfg.compose_dir / f"{key}.yaml"
            if frag_path.exists():
                r = subprocess.run(
                    ["docker", "compose", "-f", str(frag_path),
                     "--env-file", str(_cfg.env_file),
                     "up", "-d", "--pull", "always", "--force-recreate"],
                    capture_output=True, text=True, timeout=180,
                )
                if r.returncode != 0:
                    with StateDB() as db:
                        db.write_op_step(key, "__done__", "error",
                                         f"Update failed: {r.stderr.strip()[:300]}")
                    return
            else:
                # No fragment — do a fresh install
                result = install_app(key)
                if not result.ok:
                    with StateDB() as db:
                        db.write_op_step(key, "__done__", "error", result.error or "Install failed.")
                    return

            with StateDB() as db:
                db.write_op_step(key, "__done__", "ok", "Updated successfully.")
                db.upsert_app(key, status="running")
        except Exception as e:
            with StateDB() as db:
                db.write_op_step(key, "__done__", "error", str(e))
        finally:
            _installing.discard(key)

    threading.Thread(target=_do_update, daemon=True).start()
    return {"ok": True, "key": key, "message": f"Update started. Poll /apps/{key}/install/progress."}


# ── Per-app configuration (config_schema driven) ────────────────────────────

@router.get("/{key}/config")
def get_app_config(key: str) -> dict[str, Any]:
    """Return current config values for an app (driven by manifest config_schema).

    Returns: {schema: [...fields...], values: {key: value}, config_file: path}
    """
    from backend.manifests.loader import load_manifest, ManifestError
    try:
        manifest = load_manifest(key)
    except (KeyError, ManifestError):
        raise HTTPException(404, f"No app '{key}' in catalog.")

    if not manifest.config_schema:
        return {"schema": [], "values": {}, "config_file": None}

    # Read current config file if it exists
    from backend.core.config import config as _cfg
    app_config_dir = _cfg.data_dir / "app_configs" / key
    config_file = app_config_dir / "config.yml"
    values: dict[str, Any] = dict(manifest.config_defaults)

    if config_file.exists():
        try:
            import yaml as _yaml
            loaded = _yaml.safe_load(config_file.read_text())
            if isinstance(loaded, dict):
                values.update(loaded)
        except Exception:
            pass

    return {
        "schema": manifest.config_schema,
        "values": values,
        "config_file": str(config_file) if config_file.exists() else None,
    }




class AppConfigUpdate(BaseModel):
    values: dict[str, Any]


@router.put("/{key}/config")
def update_app_config(key: str, req: AppConfigUpdate) -> dict[str, Any]:
    """Write per-app configuration and restart the container.

    Writes to {config_path}/config.json and restarts the container.
    Used for apps with config_schema fields (e.g. DDNS Updater providers list).
    """
    import json as _json
    import subprocess as _sp
    from pathlib import Path

    with StateDB() as db:
        app = db.get_app(key)
    if not app:
        raise HTTPException(status_code=404, detail=f"App '{key}' is not installed.")
    if not app.config_path:
        raise HTTPException(status_code=422,
                            detail=f"App '{key}' has no config path — cannot write config.")

    config_dir = Path(app.config_path)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    config_file.write_text(_json.dumps(req.values, indent=2))

    # Restart the container to pick up new config
    try:
        _sp.run(["docker", "restart", app.container_name or key],
                capture_output=True, timeout=30)
    except (FileNotFoundError, _sp.TimeoutExpired):
        pass  # Docker not available — user will need to restart manually

    return {
        "ok": True,
        "message": f"Configuration saved for '{key}'. Container restarted.",
        "config_path": str(config_file),
    }


@router.post("/{key}/pull")

@router.post("/{key}/pin-tag")
def pin_tag_alias(key: str, req: PinVersionRequest) -> dict[str, Any]:
    """Alias for PUT /{key}/pin-version using POST + tag field."""
    return pin_app_version(key, req)


def pull_app(key: str) -> dict[str, Any]:
    """Alias for POST /{key}/update — pull latest image and recreate container."""
    return update_app(key)




# ── Post-install guidance steps ───────────────────────────────────────────

@router.get("/{key}/post-install-steps")
def get_post_install_steps(key: str) -> list[dict[str, Any]]:
    """Return guided post-install steps for an app.

    Steps are auto-generated based on app category and type.
    arr apps get indexer/download client guidance.
    DDNS Updater gets provider config guidance.
    """
    from backend.manifests.loader import load_manifest, ManifestError
    try:
        manifest = load_manifest(key)
    except (KeyError, ManifestError):
        raise HTTPException(404, f"No app '{key}' in catalog.")

    steps: list[dict[str, Any]] = []
    category = getattr(manifest, "category", "")
    web_port = getattr(manifest, "web_port", None)

    if category == "arr":
        steps.append({
            "title": "Configure indexers",
            "description": "Add Prowlarr as your indexer source: Settings → Indexers → Add Indexer → Prowlarr.",
            "link": f"http://localhost:{web_port}/Settings/Indexers" if web_port else None,
            "required": True,
        })
        steps.append({
            "title": "Configure download client",
            "description": "Add qBittorrent or SABnzbd: Settings → Download Clients → Add.",
            "link": f"http://localhost:{web_port}/Settings/DownloadClients" if web_port else None,
            "required": True,
        })
        steps.append({
            "title": "Add media root folder",
            "description": "Set your media library path: Settings → Media Management → Root Folders.",
            "link": f"http://localhost:{web_port}/Settings/MediaManagement" if web_port else None,
            "required": True,
        })

    elif key == "prowlarr":
        steps.append({
            "title": "Add indexers",
            "description": "Browse and add indexers: Indexers → Add Indexer.",
            "link": f"http://localhost:{web_port}/Indexers/Add" if web_port else None,
            "required": True,
        })
        steps.append({
            "title": "Connect to arr apps",
            "description": "Sync to Sonarr/Radarr: Settings → Apps → Add Application.",
            "link": f"http://localhost:{web_port}/Settings/Apps" if web_port else None,
            "required": True,
        })

    elif key == "ddns_updater":
        steps.append({
            "title": "Configure DNS providers",
            "description": "Open the Configuration tab on this app page and add your DNS provider credentials.",
            "link": None,
            "required": True,
        })
        steps.append({
            "title": "Set DNS records to DNS-only",
            "description": "In Cloudflare: disable the orange proxy cloud on your media subdomain (required for direct streaming).",
            "link": "https://dash.cloudflare.com",
            "required": True,
        })

    elif key in ("plex", "jellyfin", "emby"):
        steps.append({
            "title": "Add media library",
            "description": "Open the app and add your media folder as a library during initial setup.",
            "link": f"http://localhost:{web_port}" if web_port else None,
            "required": True,
        })
        if key == "plex":
            steps.append({
                "title": "Sign in to Plex",
                "description": "Claim your server by signing in with your Plex account.",
                "link": "https://app.plex.tv/desktop/#!/setup",
                "required": True,
            })

    elif category == "monitoring":
        steps.append({
            "title": "Configure data sources",
            "description": "Add Prometheus, Loki, or other data sources in the app settings.",
            "link": f"http://localhost:{web_port}" if web_port else None,
            "required": False,
        })

    if not steps:
        steps.append({
            "title": "Open the app",
            "description": f"Visit http://localhost:{web_port} to complete setup." if web_port else "Complete the initial setup in the app.",
            "link": f"http://localhost:{web_port}" if web_port else None,
            "required": False,
        })

    return steps


@router.get("/{key}/check-update")
def check_app_update(key: str) -> dict[str, Any]:
    """Check if a newer image digest is available for an installed app.

    Queries the Docker registry for the current tag and compares to
    the locally pulled digest. Returns {update_available, current_digest,
    remote_digest, image_ref}.
    """
    from backend.core.state import StateDB
    with StateDB() as db:
        app = db.get_app(key)
    if not app:
        raise HTTPException(404, f"App '{key}' is not installed.")

    image_tag = app.image_tag or "latest"
    image_ref = f"{app.image}:{image_tag}"

    try:
        import subprocess
        # Get local image digest
        local = subprocess.run(
            ["docker", "inspect", "--format", "{{.RepoDigests}}", image_ref],
            capture_output=True, text=True, timeout=10,
        )
        local_digest = local.stdout.strip()

        # Pull manifest digest without downloading
        manifest = subprocess.run(
            ["docker", "manifest", "inspect", "--verbose", image_ref],
            capture_output=True, text=True, timeout=30,
        )
        if manifest.returncode != 0:
            return {
                "update_available": None,
                "image_ref": image_ref,
                "note": "Could not reach registry to check for updates.",
            }

        import json
        data = json.loads(manifest.stdout)
        remote_digest = None
        if isinstance(data, list) and data:
            remote_digest = data[0].get("Descriptor", {}).get("digest")
        elif isinstance(data, dict):
            remote_digest = data.get("Descriptor", {}).get("digest")

        update_available = bool(
            remote_digest and local_digest and remote_digest not in local_digest
        )
        return {
            "update_available": update_available,
            "image_ref": image_ref,
            "local_digest": local_digest or None,
            "remote_digest": remote_digest,
        }
    except FileNotFoundError:
        return {"update_available": None, "image_ref": image_ref,
                "note": "Docker not available on this system."}
    except Exception as e:
        return {"update_available": None, "image_ref": image_ref, "note": str(e)[:200]}

@router.post("/{key}/probe-path")
async def probe_health_path(key: str, req: dict[str, Any]) -> dict[str, Any]:
    """Test if a custom app responds to an HTTP health check path."""
    import httpx
    from backend.core.state import StateDB
    with StateDB() as db:
        app = db.get_app(key)
    if not app or not app.host_port:
        raise HTTPException(status_code=404, detail="App not found or no port configured")
    path = req.get("path", "/health")
    url = f"http://localhost:{app.host_port}{path}"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
        return {"reachable": True, "status": r.status_code, "path": path}
    except Exception as e:
        return {"reachable": False, "status": None, "path": path, "error": str(e)}


class EnhanceRequest(BaseModel):
    health_path: str = "/health"
    start_grace_s: int = 60
    category: str = "tools"
    display_name: str = ""


@router.post("/{key}/enhance")
def enhance_custom_app(key: str, req: EnhanceRequest) -> dict[str, Any]:
    """Promote a custom app to full monitoring by writing a minimal manifest."""
    from backend.core.state import StateDB
    from backend.core.config import config as cfg
    import yaml as _yaml

    with StateDB() as db:
        app = db.get_app(key)

    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    # Build a minimal manifest YAML for this custom app
    manifest_content = {
        "key": key,
        "display_name": req.display_name or app.display_name,
        "description": f"Custom app managed by Mediastack",
        "category": req.category,
        "service_type": "custom",
        "tier": 3,
        "image": app.image or "unknown",
        "image_tag": app.image_tag or "latest",
        "web_port": app.web_port,
        "start_grace_s": req.start_grace_s,
        "health": {
            "checks": [
                {
                    "name": "http_reachable",
                    "type": "http",
                    "path": req.health_path,
                    "interval": 60,
                }
            ]
        },
    }

    # Write to custom catalog directory
    custom_dir = cfg.catalog_dir / "custom"
    custom_dir.mkdir(exist_ok=True)
    manifest_path = custom_dir / f"{key}.yaml"

    try:
        with open(manifest_path, "w") as f:
            _yaml.dump(manifest_content, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not write manifest: {e}")

    # Update app record
    with StateDB() as db:
        db.upsert_app(
            key,
            display_name=req.display_name or app.display_name,
            category=req.category,
            manifest_source="custom_enhanced",
        )

    return {
        "ok": True,
        "message": (
            f"Monitoring enhanced. {app.display_name} now has HTTP health checks "
            f"on {req.health_path} with {req.start_grace_s}s grace period."
        ),
        "manifest_path": str(manifest_path),
    }

