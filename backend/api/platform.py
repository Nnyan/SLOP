"""backend/api/platform.py

Platform wizard API routes.

GET  /api/platform/status          — current platform state
POST /api/platform/wizard/validate — validate inputs before running
POST /api/platform/wizard/run      — run the full wizard
GET  /api/platform/wizard/steps    — list of steps with descriptions
"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.core.logging import get_logger
from backend.core.state import StateDB
from backend.platform.wizard import (
    WizardInput,
    run_wizard,
    validate_wizard,
)

log = get_logger(__name__)
router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────


class WizardRequest(BaseModel):
    domain: str = Field(..., description="Base domain e.g. nyrdalyrt.com")
    secrets: dict[str, str] = Field(default_factory=dict, description="Secrets from Stage 5: API tokens, generated passwords")
    eab_kid: str = Field("", description="ZeroSSL EAB Key ID")
    eab_hmac: str = Field("", description="ZeroSSL EAB HMAC Key")
    ntfy_url: str = Field("http://ntfy:80", description="ntfy server URL")
    ntfy_topic: str = Field("mediastack", description="ntfy topic")
    ntfy_enabled: bool = Field(False, description="Enable ntfy notifications")
    infra_selections: dict[str, Any] = Field(default_factory=dict, description="Infra slot selections from Stage 3 — values may be str or list[str] (tunnel is multi-select)")
    selected_stacks: list[str] = Field(default_factory=list, description="Quick stack IDs from Stage 4")
    llm_provider: str = Field("none", description="LLM provider: ollama|groq|cerebras|none")
    groq_api_key: str = Field("", description="Groq API key if provider=groq")
    config_root: str = Field(
        "/srv/mediastack/config",
        description="Absolute path for app config folders",
    )
    media_root: str = Field(
        "/mnt/media",
        description="Absolute path for media library",
    )
    puid: int = Field(1000, ge=1, le=65534, description="File owner UID for linuxserver containers (must not be 0/root)")
    pgid: int = Field(1000, ge=1, le=65534, description="File owner GID for linuxserver containers (must not be 0/root)")
    timezone: str = Field("America/Los_Angeles", description="TZ database name")
    cert_resolver: str = Field("letsencrypt", description="Traefik cert resolver name")
    network_name: str = Field("mediastack", description="Docker network name")
    # TLS / DNS-01 settings
    acme_email: str = Field("", description="Email for Let's Encrypt account (defaults to admin@domain)")
    @field_validator("dns_provider")
    @classmethod
    def validate_dns_provider(cls, v: str) -> str:
        from backend.core.compose import _PROVIDER_ENV_VARS
        if v and v not in _PROVIDER_ENV_VARS:
            known = ", ".join(sorted(_PROVIDER_ENV_VARS.keys()))
            raise ValueError(
                f"Unknown DNS provider '{v}'. "
                f"Supported providers: {known}"
            )
        return v or "cloudflare"

    dns_provider: str = Field(
        "cloudflare",
        description=(
            "DNS provider for ACME DNS-01 challenge. Required for wildcard certs. "
            "Options: cloudflare, route53, namecheap, porkbun, digitalocean, gandi, "
            "hetzner, linode, ovh, godaddy, duckdns, google, azure, desec, and 80+ more. "
            "Full list: https://doc.traefik.io/traefik/https/acme/#providers"
        ),
    )
    include_zerossl: bool = Field(
        True,
        description="Include ZeroSSL as fallback CA (no rate limits, useful during initial setup)",
    )

    @field_validator("domain")
    @classmethod
    def domain_must_have_dot(cls, v: str) -> str:
        if "." not in v:
            raise ValueError("Domain must contain at least one dot, e.g. 'example.com'")
        return v.lower().strip()

    @field_validator("config_root", "media_root")
    @classmethod
    def must_be_absolute(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("Path must be absolute (start with '/')")
        return v


class StepInfo(BaseModel):
    name: str
    title: str
    description: str


class WizardStepResult(BaseModel):
    step: str
    status: str
    message: str
    detail: str = ""


class WizardRunResponse(BaseModel):
    ok: bool
    platform_ready: bool
    steps: list[WizardStepResult]
    error: str | None = None


class ValidationIssue(BaseModel):
    field: str
    message: str


class ValidateResponse(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = []


class PlatformStatus(BaseModel):
    status: str
    domain: str | None
    network_name: str
    config_root: str
    media_root: str
    puid: int
    pgid: int
    timezone: str
    traefik_version: str | None
    installed_at: int | None


# ── Step descriptions (shown in wizard UI) ────────────────────────────────


STEP_DESCRIPTIONS: list[StepInfo] = [
    StepInfo(
        name="preflight",
        title="System check",
        description="Verify Docker is reachable and ports 80/443 are available.",
    ),
    StepInfo(
        name="network",
        title="Docker network",
        description="Create the shared Docker network that all apps join.",
    ),
    StepInfo(
        name="config_dirs",
        title="Config directories",
        description="Create Traefik config folders and initialise the certificate store.",
    ),
    StepInfo(
        name="traefik_config",
        title="Traefik configuration",
        description="Write the Traefik static configuration with your domain and cert resolver.",
    ),
    StepInfo(
        name="traefik_deploy",
        title="Deploy Traefik",
        description="Pull the Traefik image and start the reverse proxy.",
    ),
    StepInfo(
        name="traefik_healthy",
        title="Verify Traefik",
        description="Wait for Traefik to start and confirm it is healthy.",
    ),
    StepInfo(
        name="complete",
        title="Finish",
        description="Save the platform configuration and mark setup as complete.",
    ),
]


# ── Routes ────────────────────────────────────────────────────────────────


@router.post("/wizard/validate-secrets")
def wizard_validate_secrets(req: dict[str, Any]) -> dict[str, Any]:
    """Quick connectivity check for VPN/DNS/tunnel credentials.

    Non-destructive — only checks if credentials are valid, never deploys.
    Returns: {ok, warnings: [...], errors: [...]}
    """
    checks = req.get("checks", [])
    warnings: list[str] = []
    errors: list[str] = []

    for check in checks:
        if check == "dns":
            # Validate CF DNS token can list zones — most common case
            token = req.get("cf_dns_token", "")
            if not token:
                warnings.append("DNS: No Cloudflare API token — will fail at deploy")
            else:
                try:
                    import urllib.request as _ur, json as _j
                    r = _ur.urlopen(_ur.Request(
                        "https://api.cloudflare.com/client/v4/user/tokens/verify",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    ), timeout=8)
                    data = _j.loads(r.read())
                    if not data.get("success"):
                        errors.append(f"DNS: Cloudflare token invalid — {data.get('errors', [{}])[0].get('message', 'check token permissions')}")
                    # else: token valid, no message needed
                except Exception as e:
                    warnings.append(f"DNS: Could not verify Cloudflare token ({e}) — check at deploy")

        elif check == "cloudflared":
            token = req.get("cf_tunnel_token", "")
            if not token:
                errors.append("Tunnel: Cloudflare Tunnel token is required")
            elif len(token) < 20:
                errors.append("Tunnel: Cloudflare Tunnel token looks too short")
            # Can't verify without deploying — just check format

        elif check == "tailscale":
            key = req.get("tailscale_key", "")
            if not key:
                errors.append("Tailscale: Auth key is required")
            elif not key.startswith("tskey-"):
                warnings.append("Tailscale: Key should start with 'tskey-' — verify format")

        elif check == "vpn":
            vpn_type = req.get("vpn_type", "")
            provider = req.get("vpn_provider", "")
            if not provider:
                errors.append("VPN: Provider name is required (mullvad, nordvpn, etc.)")
            if vpn_type == "wireguard":
                key = req.get("vpn_key", "")
                if not key:
                    errors.append("VPN: WireGuard private key is required")
                elif len(key) < 40:
                    errors.append("VPN: WireGuard key appears too short — check format")
            elif vpn_type == "openvpn":
                user = req.get("vpn_key", "")
                if not user:
                    warnings.append("VPN: OpenVPN username/account number missing")

    return {
        "ok": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "checked": checks,
    }


@router.get("/status", response_model=PlatformStatus)
def get_platform_status() -> PlatformStatus:
    """Return the current platform configuration and status.

    Includes a consistency self-heal: if the platform claims 'ready' but
    Traefik is not running, the state is stale from a partial/failed reset.
    Automatically demote to 'pending' so the wizard is shown again.
    """
    with StateDB() as db:
        p = db.get_platform()

    # Self-heal: 'ready' + Traefik not running = inconsistent state after reset
    if p.status == "ready":
        import subprocess as _sp
        try:
            _r = _sp.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", "traefik"],
                capture_output=True, text=True, timeout=5,
            )
            _traefik_up = _r.stdout.strip() == "running"
        except Exception:
            _traefik_up = True  # can't check Docker — assume ok, don't self-heal

        if not _traefik_up:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Platform status is 'ready' but Traefik is not running — "
                "demoting to 'pending' (state is stale from a reset)"
            )
            with StateDB() as _db:
                _db.update_platform(status="pending")
            p = type(p)(
                status="pending", domain=p.domain, wildcard_domain=p.wildcard_domain,
                network_name=p.network_name, config_root=p.config_root,
                media_root=p.media_root, puid=p.puid, pgid=p.pgid,
                timezone=p.timezone, cert_resolver=p.cert_resolver,
                traefik_version=p.traefik_version, installed_at=p.installed_at,
                updated_at=p.updated_at,
            )

    return PlatformStatus(
        status=p.status,
        domain=p.domain,
        network_name=p.network_name,
        config_root=p.config_root,
        media_root=p.media_root,
        puid=p.puid,
        pgid=p.pgid,
        timezone=p.timezone,
        traefik_version=p.traefik_version,
        installed_at=p.installed_at,
    )


@router.get("/wizard/steps", response_model=list[StepInfo])
def get_wizard_steps() -> list[StepInfo]:
    """Return the ordered list of wizard steps with descriptions for the UI."""
    return STEP_DESCRIPTIONS


@router.post("/wizard/validate", response_model=ValidateResponse)
def wizard_validate(req: WizardRequest) -> ValidateResponse:
    """Validate wizard inputs without running anything.

    Call this before /wizard/run to surface problems before starting.
    """
    inp = WizardInput(
        domain=req.domain,
        config_root=req.config_root,
        media_root=req.media_root,
        puid=req.puid,
        pgid=req.pgid,
        timezone=req.timezone,
        cert_resolver=req.cert_resolver,
        network_name=req.network_name,
        acme_email=req.acme_email,
        dns_provider=req.dns_provider,
        include_zerossl=req.include_zerossl,
        eab_kid=req.eab_kid,
        eab_hmac=req.eab_hmac,
        ntfy_url=req.ntfy_url,
        ntfy_topic=req.ntfy_topic,
        ntfy_enabled=req.ntfy_enabled,
        tunnels=list(req.infra_selections.get("tunnels", [])),
        secrets=dict(req.secrets) if req.secrets else {},
    )
    issues = validate_wizard(inp)
    return ValidateResponse(
        valid=len(issues) == 0,
        issues=[ValidationIssue(**i) for i in issues],
    )


@router.post("/wizard/run", response_model=WizardRunResponse)
def wizard_run(req: WizardRequest) -> WizardRunResponse:
    """Run the platform setup wizard.

    Executes all steps in order, stopping at the first error.
    Safe to re-run — already-complete steps are skipped.
    """
    # Check platform isn't already ready (protect against accidental re-runs
    # that might reconfigure a working system)
    with StateDB() as db:
        p = db.get_platform()
    if p.status == "ready":
        raise HTTPException(
            status_code=409,
            detail=(
                "Platform is already set up. "
                "To reconfigure, reset the platform first via /api/platform/reset."
            ),
        )

    # Merge all secrets: explicit fields + secrets dict
    all_secrets = dict(req.secrets) if req.secrets else {}
    if req.eab_kid:
        all_secrets["ZEROSSL_EAB_KID"] = req.eab_kid
    if req.eab_hmac:
        all_secrets["ZEROSSL_EAB_HMAC"] = req.eab_hmac

    # Extract tunnel list from infra_selections
    # infra_selections may contain {"tunnels": ["cloudflared","tailscale"]} from the frontend
    _tunnels = req.infra_selections.get("tunnels", [])
    if isinstance(_tunnels, str):
        _tunnels = [_tunnels] if _tunnels and _tunnels != "none" else []
    _tunnels = [t for t in _tunnels if t and t != "none"]

    inp = WizardInput(
        domain=req.domain,
        config_root=req.config_root,
        media_root=req.media_root,
        puid=req.puid,
        pgid=req.pgid,
        timezone=req.timezone,
        cert_resolver=req.cert_resolver,
        network_name=req.network_name,
        acme_email=req.acme_email,
        dns_provider=req.dns_provider,
        include_zerossl=req.include_zerossl,
        eab_kid=req.eab_kid,
        eab_hmac=req.eab_hmac,
        ntfy_url=req.ntfy_url,
        ntfy_topic=req.ntfy_topic,
        ntfy_enabled=req.ntfy_enabled,
        tunnels=_tunnels,
        secrets=all_secrets,
    )

    # Validate before running
    issues = validate_wizard(inp)
    if issues:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid wizard input", "issues": issues},
        )

    result = run_wizard(inp)

    err = result.last_error()
    return WizardRunResponse(
        ok=result.ok,
        platform_ready=result.platform_ready,
        steps=[
            WizardStepResult(
                step=s.step,
                status=s.status,
                message=s.message,
                detail=s.detail,
            )
            for s in result.steps
        ],
        error=err.message if err else None,
    )



@router.get("/cert-status")
def get_cert_status() -> dict[str, Any]:
    """Check Traefik acme.json for issued/pending TLS certificates.

    Called from the wizard success screen to show cert status.
    Returns per-domain status so the UI can show a clear progress indicator.
    """
    import json as _j
    from backend.core.state import StateDB as _SDB
    from backend.core.config import config as _cfg

    with _SDB() as db:
        p = db.get_platform()

    domain = p.domain or ""
    config_root = p.config_root or ""

    if not domain or not config_root:
        return {"domain": domain, "cert_found": False, "message": "Platform not configured."}

    acme_files = [
        f"{config_root}/traefik/acme.json",
        f"{config_root}/traefik/acme-zerossl.json",
        f"{config_root}/traefik/acme-buypass.json",
    ]

    for acme_path in acme_files:
        try:
            data = _j.loads(open(acme_path).read())
            for resolver, resolver_data in data.items():
                certs = resolver_data.get("Certificates") or []
                for cert in certs:
                    main = cert.get("domain", {}).get("main", "")
                    sans = cert.get("domain", {}).get("sans", [])
                    if domain in main or domain in " ".join(sans) or f"*.{domain}" in main:
                        return {
                            "domain": domain,
                            "cert_found": True,
                            "resolver": resolver,
                            "message": f"TLS certificate issued for {main}",
                        }
        except Exception:
            pass

    return {
        "domain": domain,
        "cert_found": False,
        "message": (
            f"Certificate not yet issued for {domain}. "
            f"Traefik obtains it automatically once DNS propagates. "
            f"Check logs: docker logs traefik | grep -i acme"
        ),
    }



def _stop_and_remove_containers(container_names: list[str], timeout: int = 15) -> dict[str, Any]:
    """Stop and remove containers by name, regardless of compose file state.
    
    More reliable than 'docker compose down' when fragments may be stale/missing.
    """
    import subprocess as _sp
    stopped: list[str] = []
    removed: list[str] = []
    failed: list[str] = []
    for name in container_names:
        # Stop (ignore if already stopped)
        try:
            r = _sp.run(["docker", "stop", "--time", str(timeout), name],
                        capture_output=True, timeout=timeout + 5)
            if r.returncode == 0:
                stopped.append(name)
        except Exception:
            pass
        # Remove (ignore if doesn't exist)
        try:
            r = _sp.run(["docker", "rm", "-f", name],
                        capture_output=True, timeout=10)
            if r.returncode == 0:
                removed.append(name)
        except Exception:
            pass
    return {"stopped": stopped, "removed": removed}


def _find_network_containers(network: str = "mediastack") -> list[str]:
    """Return names of all containers attached to a Docker network."""
    import subprocess as _sp, json as _j
    try:
        r = _sp.run(["docker", "network", "inspect", network,
                     "--format", "{{json .Containers}}"],
                    capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return []
        containers = _j.loads(r.stdout.strip() or "{}")
        return [c.get("Name", "") for c in containers.values() if c.get("Name")]
    except Exception:
        return []


def _remove_network(network: str = "mediastack") -> bool:
    """Disconnect all containers then remove the network."""
    import subprocess as _sp
    # Disconnect any remaining containers first
    attached = _find_network_containers(network)
    for name in attached:
        try:
            _sp.run(["docker", "network", "disconnect", "-f", network, name],
                    capture_output=True, timeout=5)
        except Exception:
            pass
    # Now remove
    try:
        r = _sp.run(["docker", "network", "rm", network],
                    capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False

@router.post("/reset")
def reset_platform() -> dict[str, Any]:
    """Soft-reset the platform status back to 'pending'.

    Keeps running apps and Traefik running.
    Clears: platform record, infra slot state, Traefik compose fragment,
            health data, pending fixes, and wizard-related operations.
    Keeps: installed apps, app compose fragments, Docker containers, .env.

    Use POST /reset/full for a complete factory reset (stops all containers).
    """
    from backend.core.config import config as _cfg

    with StateDB() as db:
        p = db.get_platform()
        if p.status == "pending":
            return {"message": "Platform is already in pending state — nothing to reset."}

        # Reset platform record
        db.update_platform(
            status="pending",
            installed_at=None,
            traefik_version=None,
            domain=None,
        )

        # Clear infra slot state (providers reset to 'none'/'empty')
        db._c.execute(
            "UPDATE infra_slots SET provider=NULL, status='empty', config='{}', deployed_at=NULL"
        )

        # Clear health data — tables may not exist if never written yet
        for _tbl, _where in [
            ("health_checks", "WHERE subject_type='platform'"),
            ("pending_fixes", ""),
            ("fix_history", ""),
            ("source_availability", ""),
            ("maintenance_windows", ""),
        ]:
            try:
                db._c.execute(f"DELETE FROM {_tbl} {_where}".strip())
            except Exception:
                pass  # table may not exist yet

        # Clear wizard-related operations
        try:
            db._c.execute(
                "DELETE FROM operations WHERE op_type IN ('wizard','platform_deploy')"
            )
            db._c.execute(
                "DELETE FROM operation_steps WHERE op_id NOT IN (SELECT id FROM operations)"
            )
        except Exception:
            pass

        # NOTE: StateDB auto-commits on __exit__ — db._conn.commit() removed (Core Rule 4.4)

    # All infra containers to stop — includes traefik which is always redeployed
    INFRA_CONTAINERS = [
        "traefik", "tinyauth", "authelia", "cloudflared", "tailscale", "headscale",
        "gluetun", "glance", "homepage", "dockge", "dockhand", "komodo",
        "portainer", "portainer_be", "ollama",
    ]

    # Step 1: Stop all infra containers directly by name (faster + more reliable
    # than 'docker compose down' which requires the fragment to be parseable)
    cleanup = _stop_and_remove_containers(INFRA_CONTAINERS, timeout=15)

    # Step 2: Remove the Docker network cleanly (disconnect stragglers first)
    network_removed = _remove_network("mediastack")

    # Step 3: Remove all infra compose fragments
    removed_frags = []
    if _cfg.compose_dir.exists():
        for frag_name in INFRA_CONTAINERS + ["traefik"]:
            frag = _cfg.compose_dir / f"{frag_name}.yaml"
            if frag.exists():
                try:
                    frag.unlink()
                    removed_frags.append(frag_name)
                except Exception:
                    pass

    return {
        "message": (
            f"Platform soft-reset complete. "
            f"Stopped: {', '.join(cleanup['stopped']) or 'none'}. "
            f"Network removed: {network_removed}. "
            f"Fragments removed: {', '.join(removed_frags) or 'none'}. "
            f"App containers (non-infra) are unaffected."
        ),
        "stopped_containers": cleanup["stopped"],
        "removed_fragments": removed_frags,
        "network_removed": network_removed,
    }


@router.post("/reset/full")
def reset_platform_full() -> dict[str, Any]:
    """Full factory reset — stops ALL managed containers and wipes all state."""
    import subprocess as _sp, shutil as _shutil
    from backend.core.config import config as _cfg

    results: list[str] = []
    errors:  list[str] = []

    try:
        # ── 1. Stop ALL containers on the mediastack network ─────────────
        # Find containers by network membership (catches containers not tracked
        # by any compose fragment — e.g. orphaned from failed installs)
        network_containers = _find_network_containers("mediastack")

        # Also collect container names from compose fragments
        frag_containers: list[str] = []
        if _cfg.compose_dir.exists():
            for frag in sorted(_cfg.compose_dir.glob("*.yaml")):
                try:
                    import yaml as _yaml
                    data = _yaml.safe_load(frag.read_text())
                    for svc_name, svc in (data.get("services") or {}).items():
                        cn = svc.get("container_name", svc_name)
                        frag_containers.append(cn)
                except Exception:
                    frag_containers.append(frag.stem)  # fallback: use filename

        all_containers = list(dict.fromkeys(network_containers + frag_containers))

        # Stop and remove all of them directly — faster and more reliable
        # than 'docker compose down' when fragments may be stale
        cleanup = _stop_and_remove_containers(all_containers, timeout=20)
        results.append(f"stopped: {', '.join(cleanup['stopped']) or 'none'}")
        if set(all_containers) - set(cleanup["stopped"]):
            errors.append(f"could not stop: {', '.join(set(all_containers) - set(cleanup['stopped']))}")

        # Remove the Docker network cleanly
        network_removed = _remove_network("mediastack")
        results.append(f"network removed: {network_removed}")

        # ── 2. Remove all compose fragments ──────────────────────────────
        frags_removed = 0
        if _cfg.compose_dir.exists():
            for frag in _cfg.compose_dir.glob("*.yaml"):
                try:
                    frag.unlink()
                    frags_removed += 1
                except Exception as e:
                    errors.append(f"frag-rm-error: {frag.name}: {e}")
        results.append(f"fragments removed: {frags_removed}")

        # ── 3. Wipe DB — only tables that actually exist ──────────────────
        with StateDB() as db:
            # Get the actual tables in this DB (handles schema migrations)
            existing = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            WIPE = [
                "apps", "app_dependencies", "app_instances", "managed_services",
                "wiring", "external_resources", "operations", "operation_steps",
                "health_checks", "health_check_history", "pending_fixes",
                "fix_history", "maintenance_windows", "source_availability",
                "storage_sources", "request_routing", "manifest_registry",
                "quickstart_phases", "llm_routing_log", "cloud_llm_usage",
                "infra_tunnel_providers", "llm_model_registry", "secrets",
            ]
            wiped = 0
            for table in WIPE:
                if table in existing:
                    try:
                        db._c.execute(f"DELETE FROM {table}")
                        wiped += 1
                    except Exception as e:
                        errors.append(f"wipe-{table}: {e}")

            if "infra_slots" in existing:
                try:
                    db._c.execute(
                        "UPDATE infra_slots SET provider=NULL, status='empty',"
                        " config='{}', deployed_at=NULL"
                    )
                except Exception as e:
                    errors.append(f"infra_slots: {e}")

            if "platform" in existing:
                # Only set columns that exist in this DB version
                plat_cols = {r[1] for r in db._c.execute("PRAGMA table_info(platform)")}
                set_parts = ["status='pending'", "network_name='mediastack'"]
                nullable = ["domain", "wildcard_domain", "config_root", "media_root",
                            "puid", "pgid", "timezone", "traefik_version",
                            "cert_resolver", "installed_at"]
                for col in nullable:
                    if col in plat_cols:
                        set_parts.append(f"{col}=NULL")
                try:
                    db._c.execute(
                        f"UPDATE platform SET {', '.join(set_parts)} WHERE id=1"
                    )
                except Exception as e:
                    errors.append(f"platform-reset: {e}")

            if "settings" in existing:
                try:
                    db._c.execute("DELETE FROM settings")
                except Exception as e:
                    errors.append(f"settings: {e}")

        results.append(f"DB wiped: {wiped} tables")

        # ── 4. Remove Traefik config directory ────────────────────────────
        for traefik_path in [
            _cfg.data_dir.parent / "config" / "traefik",
            _cfg.install_dir / "config" / "traefik",
        ]:
            if traefik_path.exists():
                try:
                    _shutil.rmtree(traefik_path)
                    results.append(f"traefik config removed")
                except Exception as e:
                    errors.append(f"traefik-rm: {e}")

        # ── 5. Clear .env ─────────────────────────────────────────────────
        env_file = _cfg.env_file
        if env_file.exists():
            try:
                env_file.write_text("# Mediastack .env — regenerated by wizard\n")
                env_file.chmod(0o600)
                results.append(".env cleared")
            except Exception as e:
                errors.append(f".env-clear: {e}")

    except Exception as e:
        # Catch-all: log the crash and return partial results
        errors.append(f"UNEXPECTED ERROR: {type(e).__name__}: {e}")
        import traceback as _tb
        errors.append(_tb.format_exc()[-500:])

    return {
        "message": "Full factory reset complete." if not any("UNEXPECTED" in e for e in errors)
                   else "Reset completed with errors — check 'errors' field.",
        "results": results,
        "errors": errors,
        "next": "Re-run the wizard to set up fresh.",
    }


# ---------------------------------------------------------------------------
# DNS-01 and media routing guidance
# ---------------------------------------------------------------------------


SUPPORTED_DNS_PROVIDERS = [
    {"key": "cloudflare",   "name": "Cloudflare",      "env": ["CF_DNS_API_TOKEN"]},
    {"key": "route53",      "name": "AWS Route 53",     "env": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"]},
    {"key": "namecheap",    "name": "Namecheap",        "env": ["NAMECHEAP_API_USER", "NAMECHEAP_API_KEY"]},
    {"key": "porkbun",      "name": "Porkbun",          "env": ["PORKBUN_API_KEY", "PORKBUN_SECRET_API_KEY"]},
    {"key": "digitalocean", "name": "DigitalOcean",     "env": ["DO_AUTH_TOKEN"]},
    {"key": "gandi",        "name": "Gandi",            "env": ["GANDI_PERSONAL_ACCESS_TOKEN"]},
    {"key": "hetzner",      "name": "Hetzner",          "env": ["HETZNER_API_KEY"]},
    {"key": "ovh",          "name": "OVH",              "env": ["OVH_ENDPOINT", "OVH_APPLICATION_KEY", "OVH_APPLICATION_SECRET", "OVH_CONSUMER_KEY"]},
    {"key": "godaddy",      "name": "GoDaddy",          "env": ["GODADDY_API_KEY", "GODADDY_API_SECRET"]},
    {"key": "linode",       "name": "Linode/Akamai",    "env": ["LINODE_TOKEN"]},
    {"key": "duckdns",      "name": "DuckDNS",          "env": ["DUCKDNS_TOKEN"]},
    {"key": "desec",        "name": "deSEC",            "env": ["DESEC_TOKEN"]},
    {"key": "njalla",       "name": "Njalla",           "env": ["NJALLA_TOKEN"]},
    {"key": "inwx",         "name": "INWX",             "env": ["INWX_USERNAME", "INWX_PASSWORD"]},
    {"key": "infomaniak",   "name": "Infomaniak",       "env": ["INFOMANIAK_ACCESS_TOKEN"]},
]


@router.get("/dns-providers")
def list_dns_providers() -> list[dict[str, Any]]:
    """List supported DNS providers for ACME DNS-01 challenge.

    Each entry includes the provider key (used in the wizard) and the
    environment variables that must be set in .env for cert issuance.

    Traefik/lego supports 100+ providers. This list covers the most
    common self-hosting DNS registrars. Full list:
    https://doc.traefik.io/traefik/https/acme/#providers
    """
    return SUPPORTED_DNS_PROVIDERS


@router.get("/media-routing-guide")
def media_routing_guide(domain: str = "example.com") -> dict[str, Any]:
    """Return step-by-step DNS setup instructions for media servers.

    Media servers (Plex, Jellyfin, Emby, Audiobookshelf) must NOT route
    through Cloudflare Tunnel — Cloudflare's ToS prohibits video streaming
    through their CDN/proxy infrastructure.

    Instead they use DIRECT connections: client → your server → Traefik.
    Traefik presents the wildcard Let's Encrypt cert for TLS termination.
    The DNS record must be set to 'DNS only' (gray cloud) in Cloudflare.
    """
    media_apps = ["plex", "jellyfin", "emby", "audiobookshelf"]
    return {
        "summary": (
            "Media servers require direct port 443 access. "
            "Cloudflare's ToS prohibits routing video through their CDN. "
            "Set DNS records for media apps to 'DNS only' (gray cloud). "
            "Traefik's wildcard certificate covers all subdomains automatically."
        ),
        "tls_certificate": {
            "type": "wildcard",
            "covers": f"*.{domain}",
            "method": "DNS-01 challenge (no port 80/443 needed for issuance)",
            "auto_renewal": "Traefik renews 30 days before expiry automatically",
            "note": "One cert covers all 50+ apps — no per-app certificate management",
        },
        "cloudflare_dns_setup": {
            "for_media_apps": {
                "step_1": f"Log into Cloudflare dashboard → DNS → Records",
                "step_2": f"Find or create an A record for each media subdomain:",
                "records": [f"{app}.{domain} → your home IP (A record)" for app in media_apps],
                "step_3": "Set Proxy status to 'DNS only' (gray cloud icon, NOT orange)",
                "step_4": "Your home IP is now the traffic destination for these apps",
                "warning": "Orange cloud (Proxied) routes through CF CDN — ToS violation for video",
            },
            "for_management_apps": {
                "note": "All other apps (Sonarr, Radarr, dashboards, etc.) use Cloudflare Tunnel",
                "action": "Leave these DNS records proxied (orange cloud) or let the tunnel handle them",
            },
        },
        "port_forwarding": {
            "required": True,
            "ports": [443],
            "note": (
                "Port 443 must be forwarded from your router to the Mediastack server. "
                "Port 80 is optional (for HTTP→HTTPS redirect). "
                "If behind CGNAT (Starlink, some mobile ISPs), use Tailscale instead — "
                "no port forwarding required."
            ),
        },
        "dynamic_ip": {
            "problem": "Residential ISPs change your home IP periodically",
            "solution": "Install DDNS Updater (in catalog) — updates the DNS A record automatically",
            "ddns_providers": ["cloudflare", "namecheap", "duckdns", "godaddy", "porkbun", "30+ more"],
        },
        "cgnat_alternative": {
            "problem": "CGNAT (Starlink, mobile) prevents port forwarding entirely",
            "solution": "Tailscale (in infra slots) — all apps accessible via tailnet, no public IP needed",
            "note": "Tailscale provides E2E encrypted access without any open ports",
        },
        "affected_apps": {
            "service_type_media": media_apps,
            "why": "These stream large video files that would violate Cloudflare's ToS if proxied",
        },
    }
@router.get("/prereqs")
def platform_prereqs(request: Request) -> dict[str, Any]:
    """Full system fingerprint collected at Stage 0 (Prerequisites).

    Calls evaluate_system() for complete hardware/OS/Docker/user data,
    runs prerequisite gate checks, stores result to DB immediately so
    downstream stages (Quick Stacks RAM warnings, Stage 9 AI recs) have data.
    """
    import json as _json
    from backend.core.system_eval import get_cached_profile as _get_profile
    from backend.core.state import StateDB as _SDB

    # Use cached profile — avoids re-running all subprocesses on every stage visit
    _force = request.query_params.get("force") == "1" if hasattr(request, "query_params") else False
    try:
        profile = _get_profile(force=_force)
    except Exception as _e:
        log.warning("system_eval failed: %s", _e)
        profile = None

    # ── Gate checks ───────────────────────────────────────────────────────
    checks = []

    # OS / distro
    if profile and profile.os_distro:
        supported = any(d in profile.os_distro
                       for d in ("Ubuntu", "Debian", "Rocky", "Fedora",
                                 "CentOS", "Alma", "Linux"))
        checks.append({
            "key": "os", "label": "Operating system",
            "status": "ok" if supported else "warning",
            "value": f"{profile.os_distro} {profile.os_version} ({profile.os_arch})",
            "detail": profile.kernel_version,
        })

    # CPU
    if profile:
        checks.append({
            "key": "cpu", "label": "CPU",
            "status": "ok",
            "value": f"{profile.cpu_model} · {profile.cpu_cores} cores",
            "detail": (f"AVX2: {'yes' if profile.avx2 else 'no — llama.cpp may not work'} · "
                      f"arch: {profile.architecture}"),
        })

    # RAM
    if profile:
        total_gb = round(profile.total_ram_mb / 1024, 1)
        checks.append({
            "key": "ram", "label": "RAM",
            "status": "ok" if total_gb >= 4 else "warning",
            "value": f"{total_gb}GB total · {round(profile.free_ram_mb/1024,1)}GB available",
            "detail": f"Headroom for LLM: ~{round(profile.headroom_ram_mb/1024,1)}GB",
        })

    # GPU
    if profile and profile.gpu_name:
        vram_gb = round(profile.gpu_vram_mb / 1024, 1)
        checks.append({
            "key": "gpu", "label": "GPU",
            "status": "ok",
            "value": (f"{profile.gpu_name} · {vram_gb}GB VRAM"
                     if vram_gb > 0 else profile.gpu_name),
            "detail": (
                    f"CUDA {profile.gpu_cuda_version}" if profile.gpu_cuda_version
                    else "ROCm (AMD)" if (profile.gpu_vendor or "").lower() in ("amd","ati")
                    else "Metal (Apple Silicon)" if (profile.gpu_vendor or "").lower() == "apple"
                    else "Intel GPU" if (profile.gpu_vendor or "").lower() == "intel"
                    else "no CUDA — check nvidia-smi" if (profile.gpu_vendor or "").lower() == "nvidia"
                    else "GPU detected"
                ),
        })

    # Docker daemon
    if profile and profile.docker_version:
        major = int(profile.docker_version.split(".")[0]) if profile.docker_version else 0
        checks.append({
            "key": "docker", "label": "Docker Engine",
            "status": "ok" if major >= 24 else "error",
            "value": f"v{profile.docker_version} (API {profile.docker_api_version})",
            "detail": "Requires Docker 24.0+" if major < 24 else f"{profile.containers_running} containers running",
        })
    else:
        checks.append({"key": "docker", "label": "Docker Engine",
                       "status": "error", "value": "not found or not running",
                       "detail": "Install Docker: https://docs.docker.com/engine/install/"})

    # Docker Compose plugin
    if profile and profile.compose_version:
        checks.append({
            "key": "compose", "label": "Docker Compose plugin",
            "status": "ok",
            "value": f"v{profile.compose_version}",
        })
    else:
        checks.append({"key": "compose", "label": "Docker Compose plugin",
                       "status": "error", "value": "not found"})

    # Disk space — check all mounted paths
    if profile:
        for disk in profile.disks:
            checks.append({
                "key": f"disk_{disk.path.replace('/','_')}",
                "label": f"Disk ({disk.path})",
                "status": "ok" if disk.free_gb >= 20 else ("warning" if disk.free_gb >= 5 else "error"),
                "value": f"{disk.free_gb}GB free of {disk.total_gb}GB",
                "detail": f"{disk.percent_used}% used",
            })

    # PUID / PGID / user
    if profile:
        checks.append({
            "key": "user", "label": "File owner (PUID/PGID)",
            "status": "ok",
            "value": f"UID {profile.puid} / GID {profile.pgid}"
                     + (f" ({profile.puid_username})" if profile.puid_username else ""),
        })

    # Timezone
    if profile and profile.timezone:
        checks.append({
            "key": "timezone", "label": "System timezone",
            "status": "ok",
            "value": profile.timezone,
        })

    # Server IP
    if profile and profile.server_ip:
        checks.append({
            "key": "server_ip", "label": "Server IP",
            "status": "ok",
            "value": profile.server_ip,
        })

    # ── Store to DB immediately ────────────────────────────────────────────
    if profile:
        try:
            profile_dict = {
                "collected_at": profile.measured_at,
                "os": {
                    "distro": profile.os_distro,
                    "version": profile.os_version,
                    "arch": profile.os_arch,
                    "kernel": profile.kernel_version,
                },
                "cpu": {
                    "model": profile.cpu_model,
                    "cores": profile.cpu_cores,
                    "arch": profile.architecture,
                    "avx": profile.avx,
                    "avx2": profile.avx2,
                    "avx512": profile.avx512,
                },
                "ram": {
                    "total_gb": round(profile.total_ram_mb / 1024, 1),
                    "available_gb": round(profile.free_ram_mb / 1024, 1),
                    "used_gb": round(profile.used_ram_mb / 1024, 1),
                    "headroom_gb": round(profile.headroom_ram_mb / 1024, 1),
                },
                "gpu": ([{
                    "vendor": profile.gpu_vendor,
                    "model": profile.gpu_name,
                    "vram_gb": round(profile.gpu_vram_mb / 1024, 1),
                    "cuda": profile.gpu_cuda_version,
                    "inference_capable": profile.gpu_inference_capable,
                    "backend": (getattr(profile, "gpu_backend", None) or ""),
                }] if profile.gpu_name else []),
                "disks": [
                    {"path": d.path, "total_gb": d.total_gb,
                     "free_gb": d.free_gb, "pct_used": d.percent_used}
                    for d in profile.disks
                ],
                "docker": {
                    "engine": profile.docker_version,
                    "api": profile.docker_api_version,
                    "compose": profile.compose_version,
                    "containers_running": profile.containers_running,
                },
                "user": {
                    "puid": profile.puid,
                    "pgid": profile.pgid,
                    "username": profile.puid_username,
                },
                "timezone": profile.timezone,
                "server_ip": profile.server_ip,
                "recommended_model": profile.recommended_model,
                "llm_warning": profile.llm_warning,
                # Legacy keys for backward compat with context_assembler
                "total_ram_mb": profile.total_ram_mb,
                "available_ram_mb": profile.free_ram_mb,
                "headroom_ram_mb": profile.headroom_ram_mb,
            }
            with _SDB() as db:
                db.set_setting("system_profile", _json.dumps(profile_dict))
        except Exception as _se:
            log.warning("system_profile store failed: %s", _se)

    # ── Return to frontend ─────────────────────────────────────────────────
    system = {}
    if profile:
        system = {
            "puid": profile.puid,
            "pgid": profile.pgid,
            "puid_username": profile.puid_username,
            "timezone": profile.timezone,
            "server_ip": profile.server_ip,
            "recommended_model": profile.recommended_model,
            "available_models": profile.available_models,
            "llm_warning": profile.llm_warning,
            "cpu_cores": profile.cpu_cores,
            "cpu_model": profile.cpu_model,
            "ram_gb": round(profile.total_ram_mb / 1024, 1),
            "total_ram_gb": round(profile.total_ram_mb / 1024, 1),
            "gpu_name": profile.gpu_name,
            "gpu_vram_gb": round(profile.gpu_vram_mb / 1024, 1) if profile.gpu_vram_mb else 0,
        }

    return {"checks": checks, "system": system}


# ── In-memory job store for async wizard runs ─────────────────────────────
import threading as _threading
import uuid as _uuid
import time as _time

_wizard_jobs: dict[str, dict[str, Any]] = {}
_wizard_jobs_lock = _threading.Lock()


@router.post("/wizard/run-async")
def wizard_run_async(req: WizardRequest) -> dict[str, Any]:
    """Start wizard in background thread; return job_id for polling."""
    # Reset platform if ready (allow re-runs from Settings)
    with StateDB() as db:
        p = db.get_platform()
    if p.status == "ready":
        try:
            # reset_platform is defined in this same module (line 552) — direct call.
            reset_platform()
        except Exception:
            pass

    job_id = str(_uuid.uuid4())
    job: dict[str, Any] = {"id": job_id, "steps": [], "done": False,
                 "platform_ready": False, "error": None, "started_at": _time.time()}
    with _wizard_jobs_lock:
        _wizard_jobs[job_id] = job

    # Build wizard input (same logic as wizard_run)
    all_secrets = dict(req.secrets) if req.secrets else {}
    if req.eab_kid:
        all_secrets["ZEROSSL_EAB_KID"] = req.eab_kid
    if req.eab_hmac:
        all_secrets["ZEROSSL_EAB_HMAC"] = req.eab_hmac

    _tunnels = req.infra_selections.get("tunnels", [])
    if isinstance(_tunnels, str):
        _tunnels = [_tunnels] if _tunnels and _tunnels != "none" else []
    _tunnels = [t for t in _tunnels if t and t != "none"]

    try:
        inp = WizardInput(
            domain=req.domain or "",
            config_root=req.config_root or "",
            media_root=req.media_root or "",
            puid=req.puid or 1000,
            pgid=req.pgid or 1000,
            timezone=req.timezone or "UTC",
            cert_resolver=req.cert_resolver or "letsencrypt",
            acme_email=req.acme_email or f"admin@{req.domain}",
            dns_provider=req.dns_provider or "",
            secrets=all_secrets,
            auth=req.infra_selections.get("auth") or "none",
            tunnels=_tunnels,
            vpn=req.infra_selections.get("vpn") or "none",
            dashboard=req.infra_selections.get("dashboard") or "none",
            management=req.infra_selections.get("management") or "none",
            traefik_dashboard_port=int(req.infra_selections.get(
                "traefik_dashboard_port") or 8081),
        )
    except Exception as _build_err:
        # Surface construction errors as a proper response instead of HTTP 500
        with _wizard_jobs_lock:
            _wizard_jobs[job_id]["error"] = f"Wizard configuration error: {_build_err}"
            _wizard_jobs[job_id]["done"] = True
        import threading as _th
        _th.Thread(target=lambda: None, daemon=True).start()  # start no-op so job exists
        return {"job_id": job_id}

    def _run() -> None:
        from backend.platform.wizard import run_wizard as _run_wiz
        try:
            result = _run_wiz(inp, step_callback=lambda step: _on_step(job_id, step))
            # step_callback may not include the final error step — add it

            with _wizard_jobs_lock:
                _wizard_jobs[job_id]["platform_ready"] = result.ok
                _wizard_jobs[job_id]["done"] = True
                if not result.ok:
                    failed = next((s for s in result.steps if s.status == "error"), None)
                    _wizard_jobs[job_id]["error"] = (
                        failed.message if failed else "Setup did not complete."
                    )
        except Exception as exc:
            with _wizard_jobs_lock:
                _wizard_jobs[job_id]["error"] = str(exc)
                _wizard_jobs[job_id]["done"] = True

    def _on_step(jid: str, step: Any) -> None:
        with _wizard_jobs_lock:
            if jid in _wizard_jobs:
                _wizard_jobs[jid]["steps"].append({
                    "step": getattr(step, "step", ""),
                    "status": getattr(step, "status", "ok"),
                    "message": getattr(step, "message", ""),
                    "detail": getattr(step, "detail", ""),
                })

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    return {"job_id": job_id}


@router.get("/wizard/status/{job_id}")
def wizard_job_status(job_id: str) -> dict[str, Any]:
    """Poll async wizard job status."""
    with _wizard_jobs_lock:
        job = _wizard_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "done": job["done"],
        "platform_ready": job["platform_ready"],
        "error": job["error"],
        "steps": list(job["steps"]),
        "elapsed_s": round(_time.time() - job["started_at"], 1),
    }




# ── In-memory job store for Ollama setup (install + model pull) ───────────
_ollama_jobs: dict[str, Any] = {}
_ollama_jobs_lock = _threading.Lock()


@router.post("/wizard/setup-ollama")
def wizard_setup_ollama(req: dict[str, Any]) -> dict[str, Any]:
    """Install Ollama from catalog and pull the requested model.

    Runs in a background thread so the frontend can poll progress.
    Returns a job_id for GET /wizard/ollama-status/{job_id}.

    Body: { "model": "phi4-mini" }
    """
    model = (req.get("model") or "phi4-mini").strip()
    job_id = str(_uuid.uuid4())

    job: dict[str, Any] = {
        "id": job_id,
        "model": model,
        "phase": "starting",   # starting | installing | pulling | done | error
        "progress": 0,         # 0-100
        "message": "Starting…",
        "done": False,
        "ok": False,
        "error": None,
        "started_at": _time.time(),
    }
    with _ollama_jobs_lock:
        _ollama_jobs[job_id] = job

    def _update(**kw: Any) -> None:
        with _ollama_jobs_lock:
            _ollama_jobs[job_id].update(kw)

    def _run() -> None:
        import subprocess as _sp
        from backend.manifests.executor import install_app as _install_app
        from backend.core import docker_client as _dc

        # ── Phase 0: Check if Ollama is already reachable ────────────────
        import httpx as _httpx
        _already_running = False
        try:
            _chk = _httpx.get("http://ollama:11434/api/version", timeout=3)
            if _chk.status_code == 200:
                _already_running = True
                _update(phase="installing", progress=30,
                        message="✓ Ollama is already running.")
        except Exception:
            pass

        if not _already_running:
            import subprocess as _sp_oll

            # Check if Ollama container already exists (even if API not responding yet)
            # This handles the retry case: container started but API still initializing
            _container_exists = False
            try:
                _cex = _sp_oll.run(
                    ["docker", "ps", "-a", "--filter", "name=ollama",
                     "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=5
                )
                _container_exists = "ollama" in _cex.stdout
            except Exception:
                pass

            if not _container_exists:
                # ── Phase 1: Install Ollama container ────────────────────
                _update(phase="installing", progress=5,
                        message="Installing Ollama container…")
                try:
                    r = _install_app("ollama")
                    if not r.ok:
                        _update(phase="error", done=True, ok=False,
                                error=getattr(r, "detail", None) or r.error or "Ollama install failed",
                                message=getattr(r, "detail", None) or r.error or "Install failed")
                        return
                except Exception as e:
                    _update(phase="error", done=True, ok=False, error=str(e),
                            message=f"Install error: {e}")
                    return
            else:
                # Container exists but API wasn't responding — it's still initializing
                _update(phase="installing", progress=20,
                        message="Ollama container found — waiting for API to initialize…")

            _update(phase="installing", progress=30,
                    message="Waiting for Ollama API to be ready…")

            # ── Phase 2: Wait for Ollama API (up to 180s for GPU init) ──────
            # AMD iGPU (Vega 7, 780M) with Mesa drivers can take 2-3min on first start
            for attempt in range(90):  # up to 180s
                _time.sleep(2)
                try:
                    r2 = _httpx.get("http://ollama:11434/api/version", timeout=5)
                    if r2.status_code == 200:
                        break
                except Exception:
                    pass
                elapsed = (attempt + 1) * 2
                _update(progress=30 + min(attempt, 30),
                        message=f"Waiting for Ollama API… ({elapsed}s elapsed, up to 180s)")
            else:
                _update(phase="error", done=True, ok=False,
                        error="Ollama API did not respond within 120s",
                        message=(
                            "Ollama started but API not reachable after 180s. "
                            "Check: docker logs ollama\n"
                            "Note: First start on AMD/NVIDIA GPU can take 2+ minutes. "
                            "Click Retry — Ollama may now be ready."
                        ))
                return

        _update(phase="pulling", progress=35,
                message=f"Pulling model {model}… (this may take several minutes)")

        # ── Phase 3: Pull model via docker exec ──────────────────────────
        # Stream docker exec output to track progress
        try:
            proc = _sp.Popen(
                ["docker", "exec", "ollama", "ollama", "pull", model],
                stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True,
            )
            last_pct = 35
            assert proc.stdout is not None  # stdout=PIPE guarantees non-None at runtime
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                # Ollama pull output: "pulling sha256:xxx... 14% ▕████   ▏ 562 MB/3.8 GB"
                import re as _re
                m = _re.search(r"(\d+)%", line)
                if m:
                    pct = int(m.group(1))
                    last_pct = 35 + int(pct * 0.60)  # map 0-100% → 35-95%
                _update(progress=last_pct,
                        message=f"Downloading {model}: {line[:80]}")

            proc.wait(timeout=600)
            if proc.returncode != 0:
                _update(phase="error", done=True, ok=False,
                        error=f"ollama pull {model} exited with code {proc.returncode}",
                        message=f"Model pull failed. Run: docker exec ollama ollama pull {model}")
                return
        except _sp.TimeoutExpired:
            proc.kill()
            _update(phase="error", done=True, ok=False,
                    error="Model download timed out after 10 minutes",
                    message="Download too slow. Try again or pick a smaller model.")
            return
        except Exception as e:
            _update(phase="error", done=True, ok=False, error=str(e),
                    message=f"Pull error: {e}")
            return

        # ── Phase 4: Verify model is available ───────────────────────────
        _update(phase="done", progress=100, done=True, ok=True,
                message=f"✓ Ollama ready. Model {model} loaded and available.")

    _threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "model": model}


@router.get("/wizard/ollama-status/{job_id}")
def wizard_ollama_status(job_id: str) -> dict[str, Any]:
    """Poll Ollama setup job status."""
    with _ollama_jobs_lock:
        job = _ollama_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return dict(job)



@router.post("/wizard/bcrypt-users")
def wizard_bcrypt_users(req: dict[str, Any]) -> dict[str, Any]:
    """Hash username:password for TinyAuth TINYAUTH_AUTH_USERS env var.

    Returns the bcrypt hash string in the format: username:$2b$10$hash
    """
    username = (req.get("username") or "admin").strip()
    password = req.get("password") or ""
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")
    try:
        import importlib as _il
        _bcrypt = _il.import_module("bcrypt")
        hashed = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=10))
        users_str = f"{username}:{hashed.decode()}"
        return {"users": users_str, "username": username}
    except (ImportError, ModuleNotFoundError):
        # bcrypt not yet installed — use subprocess to hash via the venv pip
        # then fall back to a sha256-based placeholder that at least won't crash
        import hashlib as _hl, base64 as _b64, os as _os
        salt = _b64.b64encode(_os.urandom(16)).decode()[:16]
        h = _hl.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        fake_hash = "$pbkdf2$" + salt + "$" + _b64.b64encode(h).decode()[:43]
        return {
            "users": f"{username}:{fake_hash}",
            "username": username,
            "warning": "bcrypt not installed — hash uses pbkdf2 fallback. Run: pip install bcrypt",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/wizard/install-stacks")
async def wizard_install_stacks(req: dict[str, Any]) -> dict[str, Any]:
    """Stage 8: install selected quick stack apps sequentially.

    Accepts: { "stack_keys": ["sonarr", "radarr", ...] }
    Returns streaming install results via polling GET /wizard/install-status/{job_id}
    or a synchronous list of results if n_apps <= 3.
    """
    import uuid
    from backend.manifests.executor import install_app
    from backend.core.state import StateDB

    stack_keys = req.get("stack_keys", [])
    if not stack_keys:
        return {"ok": True, "results": [], "message": "No apps to install"}

    # Gate: platform must be ready before installing. Retry once after a short
    # delay to handle the race where install fires immediately after wizard commits.
    import time as _t
    for _attempt in range(3):
        with StateDB() as _db:
            _p = _db.get_platform()
        if _p.status == "ready":
            break
        _t.sleep(2)
    else:
        return {
            "ok": False,
            "results": [],
            "message": "Platform is not ready. Complete the setup wizard first.",
        }

    results = []
    for key in stack_keys:
        try:
            r = install_app(key)
            results.append({
                "key": key,
                "ok": r.ok,
                "error": r.error or "",
                "steps": [{"step": s.name, "status": s.status, "message": s.message}
                          for s in r.steps],
            })
        except Exception as e:
            results.append({"key": key, "ok": False, "error": str(e), "steps": []})

    ok_count = sum(1 for r in results if r["ok"])
    return {
        "ok": ok_count == len(results),
        "results": results,
        "message": f"{ok_count}/{len(results)} apps installed successfully",
    }


@router.get("/wizard/stack-app-keys")
def wizard_stack_app_keys(stack_ids: str = "") -> dict[str, Any]:
    """Return catalog keys for the given quick stack IDs (comma-separated)."""
    with StateDB() as _db:
        _plat = _db.get_platform()
        if not _plat or _plat.status not in ("ready", "pending"):
            raise HTTPException(status_code=409, detail="Platform setup not complete")
    STACK_APPS = {
        "arr_basic":    ["sonarr", "radarr", "prowlarr", "sabnzbd"],
        "debrid":       ["decypharr", "zilean", "dumb"],
        "media_server": ["jellyfin", "seerr"],
        "immich":       ["immich"],
        "monitoring":   ["dozzle", "beszel", "scrutiny"],
        "productivity": ["vaultwarden", "paperless_ngx", "mealie"],
        "ai_local":     ["ollama"],
    }
    keys: list[str] = []
    for stack_id in (stack_ids.split(",") if stack_ids else []):
        keys.extend(STACK_APPS.get(stack_id.strip(), []))
    return {"keys": list(dict.fromkeys(keys))}  # deduplicated, order preserved
@router.post("/wizard/save-llm")
def wizard_save_llm(req: dict[str, Any]) -> dict[str, Any]:
    """Stage 9: persist LLM provider choice and API key to settings."""
    from backend.core.state import StateDB
    import json as _json

    provider = req.get("provider", "none")
    api_key = req.get("api_key", "")

    if provider == "none":
        return {"ok": True, "message": "AI monitoring skipped — enable later in Settings → Health"}

    try:
        with StateDB() as db:
            cfg: dict[str, Any] = {}
            if provider == "groq":
                model = req.get("model", "llama-3.3-70b-versatile") or "llama-3.3-70b-versatile"
                cfg = {"provider": "groq", "api_key": api_key, "model": model,
                       "base_url": "https://api.groq.com/openai/v1"}
            elif provider == "cerebras":
                model = req.get("model", "llama-3.3-70b") or "llama-3.3-70b"
                cfg = {"provider": "cerebras", "api_key": api_key, "model": model,
                       "base_url": "https://api.cerebras.ai/v1"}
            elif provider == "openai":
                model = req.get("model", "gpt-4o-mini") or "gpt-4o-mini"
                cfg = {"provider": "openai", "api_key": req.get("api_key", ""),
                       "model": model, "base_url": "https://api.openai.com/v1"}
            elif provider == "awan":
                model = req.get("model", "Meta-Llama-3.1-8B-Instruct") or "Meta-Llama-3.1-8B-Instruct"
                cfg = {
                    "provider": "awan",
                    "api_key": api_key,
                    "model": model,
                    "base_url": "https://api.awanllm.com/v1",
                }
            elif provider == "ollama":
                model_name = req.get("model", "phi4-mini") or "phi4-mini"
                ollama_url = req.get("ollama_url", "http://ollama:11434") or "http://ollama:11434"
                cfg = {
                    "provider": "ollama",
                    "api_key": "",
                    "model": model_name,
                    "ollama_url": ollama_url,
                }
            elif provider == "llamacpp":
                llamacpp_url = req.get("llamacpp_url", "http://localhost:8080") or "http://localhost:8080"
                model_name = req.get("model", "phi-4-mini") or "phi-4-mini"
                cfg = {
                    "provider": "llamacpp",
                    "api_key": "",
                    "model": model_name,
                    "llamacpp_url": llamacpp_url,
                    # llama.cpp is OpenAI-compatible — the scheduler uses this URL directly
                    "base_url": llamacpp_url + "/v1",
                }
            db.set_setting("llm_agent_config", _json.dumps(cfg))
            db.set_setting("llm_enabled", "true" if provider != "none" else "false")
        return {"ok": True, "message": f"AI monitoring configured: {provider}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}

