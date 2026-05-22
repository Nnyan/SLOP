"""backend/platform/wizard.py

Platform wizard — the one-time setup that must complete before any apps
can be installed.

Steps run in order. Each step is independently validatable and executable.
If a step fails, the wizard stops and reports the plain-language error.
The wizard is idempotent — re-running it after a partial failure is safe.

Steps:
  1. preflight       — Docker reachable, ports 80/443 free
  2. network         — create the shared Docker network
  3. config_dirs     — create Traefik config directories and acme.json
  4. traefik_config  — write traefik.yml static config
  5. traefik_deploy  — write fragment, docker compose up traefik
  6. traefik_healthy — wait for Traefik to report healthy
  7. complete        — mark platform status = ready in state DB
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.core import docker_client
from backend.core.compose import (
    STACK_NETWORK,
    build_traefik_fragment,
    build_traefik_yaml,
    write_fragment,
)
from backend.core.config import config
from backend.core.logging import get_logger
from backend.core.system_eval import evaluate_system
from backend.core.state import StateDB, init_db

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    step: str
    status: str         # ok | error | skipped
    message: str        # plain-language one-liner
    detail: str = ""    # expanded info (shown on expand in UI)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class WizardResult:
    steps: list[StepResult] = field(default_factory=list)
    platform_ready: bool = False

    @property
    def ok(self) -> bool:
        return all(s.ok or s.status == "skipped" for s in self.steps)

    def last_error(self) -> StepResult | None:
        for s in reversed(self.steps):
            if s.status == "error":
                return s
        return None


# ---------------------------------------------------------------------------
# Wizard input
# ---------------------------------------------------------------------------


@dataclass
class WizardInput:
    domain: str
    config_root: str
    media_root: str
    puid: int
    pgid: int
    timezone: str
    cert_resolver: str = "letsencrypt"
    network_name: str = STACK_NETWORK
    # TLS / ACME settings
    acme_email: str = ""             # defaults to admin@domain
    dns_provider: str = "cloudflare" # traefik/lego DNS provider key
    include_zerossl: bool = True     # add ZeroSSL as fallback CA
    eab_kid: str = ""            # ZeroSSL External Account Binding Key ID
    eab_hmac: str = ""           # ZeroSSL External Account Binding HMAC Key
    # Access mode settings (for media server routing)
    ntfy_url: str = "http://ntfy:80"
    ntfy_topic: str = "mediastack"
    ntfy_enabled: bool = False
    # Tunnel selections (multi-select list)
    tunnels: list[str] | None = None  # ["cloudflared", "tailscale"]
    # Infra slot selections (stored for context; deployment happens via wizard_install_stacks)
    auth: str = "none"              # auth provider: tinyauth | authelia | none
    vpn: str = "none"               # vpn provider: gluetun | none
    dashboard: str = "none"         # dashboard: glance | homepage | none
    management: str = "none"        # container mgmt: dockhand | dockge | none
    traefik_dashboard_port: int = 8081
    # Secrets collected by Stage 5 — written verbatim to .env
    secrets: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Individual steps
# ---------------------------------------------------------------------------




def step_system_eval(inp: WizardInput) -> StepResult:
    """Evaluate host resources and determine LLM model recommendation."""
    try:
        profile = evaluate_system(
            config_root=inp.config_root,
            media_root=inp.media_root,
        )
        ram_gb = round(profile.total_ram_mb / 1024, 1)
        free_gb = round(profile.free_ram_mb / 1024, 1)
        headroom_gb = round(profile.headroom_ram_mb / 1024, 1)

        detail_lines = [
            f"CPU: {profile.cpu_cores} cores — {profile.cpu_model}",
            f"RAM: {ram_gb}GB total, {free_gb}GB available",
        ]
        for disk in profile.disks:
            detail_lines.append(
                f"Disk {disk.path}: {disk.free_gb}GB free of {disk.total_gb}GB ({disk.percent_used}% used)"
            )

        if profile.recommended_model:
            detail_lines.append(f"LLM recommendation: {profile.recommended_model} "
                                f"({headroom_gb}GB headroom)")
        elif profile.llm_warning:
            detail_lines.append(f"LLM: {profile.llm_warning}")

        # Store profile in settings for later use
        import json, time as _time
        with StateDB() as db:
            db.set_setting("system_profile", json.dumps({
                "cpu_cores": profile.cpu_cores,
                "total_ram_mb": profile.total_ram_mb,
                "free_ram_mb": profile.free_ram_mb,
                "headroom_ram_mb": profile.headroom_ram_mb,
                "recommended_llm_model": profile.recommended_model,
                "llm_warning": profile.llm_warning,
                "measured_at": int(_time.time()),
            }))

        return StepResult(
            step="system_eval",
            status="ok",
            message=(
                f"System: {profile.cpu_cores} cores, {ram_gb}GB RAM. "
                + (f"Recommended LLM: {profile.recommended_model}."
                   if profile.recommended_model
                   else "RAM too limited for LLM agent.")
            ),
            detail="\n".join(detail_lines),
        )
    except Exception as e:
        # Non-fatal — continue wizard even if eval fails
        return StepResult(
            step="system_eval",
            status="skipped",
            message="System evaluation skipped — could not read hardware info.",
            detail=str(e),
        )

def step_preflight(inp: WizardInput) -> StepResult:
    """Check Docker is reachable and ports 80/443 are free."""
    # Docker reachable?
    try:
        docker_client.daemon_info()
    except docker_client.DockerError as e:
        return StepResult(
            step="preflight",
            status="error",
            message="Docker is not reachable.",
            detail=str(e),
        )

    # Ports 80 and 443 — allow if already owned by Traefik (wizard re-run)
    in_use = docker_client.ports_in_use()
    conflicts = []
    for port in (80, 443):
        if port in in_use:
            owner = in_use[port]
            if owner.lower() != "traefik":
                conflicts.append(f"port {port} is already used by '{owner}'")

    if conflicts:
        return StepResult(
            step="preflight",
            status="error",
            message=f"Port conflict — {', '.join(conflicts)}.",
            detail=(
                "Traefik needs ports 80 and 443. Stop the conflicting containers "
                "before running the platform wizard."
            ),
        )

    traefik_already = any(in_use.get(p, "").lower() == "traefik" for p in (80, 443))
    return StepResult(
        step="preflight",
        status="ok",
        message=(
            "Docker reachable. Traefik already running on 80/443 — will reconfigure."
            if traefik_already
            else "Docker reachable, ports 80 and 443 are free."
        ),
    )


def step_network(inp: WizardInput) -> StepResult:
    """Create the shared Docker network."""
    try:
        existing = docker_client.get_network(inp.network_name)
        if existing:
            return StepResult(
                step="network",
                status="skipped",
                message=f"Network '{inp.network_name}' already exists — skipping.",
            )
        docker_client.create_network(inp.network_name)
        return StepResult(
            step="network",
            status="ok",
            message=f"Created Docker network '{inp.network_name}'.",
        )
    except docker_client.DockerError as e:
        return StepResult(
            step="network",
            status="error",
            message=f"Could not create network '{inp.network_name}'.",
            detail=str(e),
        )


def step_config_dirs(inp: WizardInput) -> StepResult:
    """Create Traefik config directories and initialise acme.json."""
    traefik_dir = Path(inp.config_root) / "traefik"
    dynamic_dir = traefik_dir / "dynamic"
    acme_path = traefik_dir / "acme.json"

    try:
        dynamic_dir.mkdir(parents=True, exist_ok=True)

        if not acme_path.exists():
            acme_path.touch()
            acme_path.chmod(0o600)
        # ZeroSSL fallback resolver also needs a 600-mode storage file
        acme_zerossl = traefik_dir / "acme-zerossl.json"
        if not acme_zerossl.exists():
            acme_zerossl.touch()
            acme_zerossl.chmod(0o600)
        # Buypass CA resolver storage file
        acme_buypass = traefik_dir / "acme-buypass.json"
        if not acme_buypass.exists():
            acme_buypass.touch()
            acme_buypass.chmod(0o600)
        else:
            # Fix permissions if wrong — common cause of cert failures
            current_mode = oct(acme_path.stat().st_mode)[-3:]
            if current_mode != "600":
                acme_path.chmod(0o600)

        return StepResult(
            step="config_dirs",
            status="ok",
            message=f"Traefik config directories ready at {traefik_dir}.",
        )
    except OSError as e:
        return StepResult(
            step="config_dirs",
            status="error",
            message=f"Could not create Traefik config directory at {traefik_dir}.",
            detail=(
                f"Error: {e}. "
                f"Make sure the user running Mediastack has write access to {inp.config_root}."
            ),
        )


def step_traefik_config(inp: WizardInput) -> StepResult:
    """Write the traefik.yml static configuration file.

    Configures DNS-01 challenge for wildcard certificate (*.domain.com).
    Both Let's Encrypt and ZeroSSL resolvers are written — ZeroSSL is
    a ready fallback if LE rate limits are hit during initial setup.

    Supported dns_provider values:
      cloudflare (default), route53, namecheap, porkbun, digitalocean,
      gandi, hetzner, linode, ovh, godaddy, duckdns, google, azure, and 80+
      more. Full list: https://doc.traefik.io/traefik/https/acme/#providers
    """
    traefik_yml_path = Path(inp.config_root) / "traefik" / "traefik.yml"
    try:
        content = build_traefik_yaml(
            domain=inp.domain,
            cert_resolver=inp.cert_resolver,
            acme_email=inp.acme_email,
            dns_provider=inp.dns_provider,
            include_zerossl=inp.include_zerossl,
            eab_kid=inp.eab_kid or "",
            eab_hmac=inp.eab_hmac or "",
        )
        traefik_yml_path.write_text(content)
        return StepResult(
            step="traefik_config",
            status="ok",
            message=(
                f"Traefik configured with DNS-01 wildcard cert. "
                f"Provider: {inp.dns_provider}. "
                f"All apps will share *.{inp.domain} automatically."
            ),
            detail=str(traefik_yml_path),
        )
    except OSError as e:
        return StepResult(
            step="traefik_config",
            status="error",
            message=f"Could not write Traefik config to {traefik_yml_path}.",
            detail=str(e),
        )


def step_traefik_deploy(inp: WizardInput) -> StepResult:
    # Wizard steps must NEVER raise — all failures must be returned as StepResult(ok=False)
    """Write the Traefik compose fragment and start the container."""
    # Pre-check: verify required DNS provider credentials exist in .env
    from backend.core.compose import _PROVIDER_ENV_VARS
    from backend.core.config import config as _cfg

    required_vars = _PROVIDER_ENV_VARS.get(inp.dns_provider, [])
    if required_vars and _cfg.env_file.exists():
        env_vals: dict[str, str] = {}
        for line in _cfg.env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_vals[k.strip()] = v.strip()
        missing = [v for v in required_vars if not env_vals.get(v)]
        if missing:
            return StepResult(
                step="traefik_deploy",
                status="error",
                message=(
                    f"Missing credentials for {inp.dns_provider} DNS provider: "
                    + ", ".join(missing)
                ),
                detail=(
                    f"Add these to your .env file before running the wizard:\n"
                    + "\n".join(f"  {v}=your_value_here" for v in missing)
                    + "\n\nYou can set them in Settings → Secrets."
                ),
            )

    # Check if Traefik is already running (gracefully handle Docker unavailable)
    try:
        existing = docker_client.get_container("traefik")
        if existing and existing.status == "running":
            return StepResult(
                step="traefik_deploy",
                status="skipped",
                message="Traefik is already running — skipping deploy.",
            )
    except Exception:
        existing = None  # Docker unavailable — proceed to deploy attempt

    # Build and write the fragment
    fragment = build_traefik_fragment(
        domain=inp.domain,
        network_name=inp.network_name,
        cert_resolver=inp.cert_resolver,
        config_root=inp.config_root,
        dns_provider=inp.dns_provider,
    )

    try:
        frag_path = write_fragment("traefik", fragment)
    except OSError as e:
        return StepResult(
            step="traefik_deploy",
            status="error",
            message="Could not write Traefik compose fragment.",
            detail=str(e),
        )

    # Run docker compose up
    compose_file = config.compose_dir / "traefik.yaml"
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d", "--pull", "always"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return StepResult(
                step="traefik_deploy",
                status="error",
                message="Traefik failed to start.",
                detail=_clean_docker_output(result.stderr or result.stdout),
            )
        return StepResult(
            step="traefik_deploy",
            status="ok",
            message="Traefik started.",
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            step="traefik_deploy",
            status="error",
            message="Traefik deploy timed out after 120 seconds.",
            detail="The container may still be starting. Check 'docker logs traefik'.",
        )
    except FileNotFoundError:
        return StepResult(
            step="traefik_deploy",
            status="error",
            message="'docker compose' command not found.",
            detail="Make sure Docker Compose v2 is installed.",
        )
    except OSError as e:
        # Docker daemon not running, socket unreachable, or transient
        # OS errors. Wizard contract: never raise — surface as a
        # structured StepResult so the wizard can recover gracefully.
        return StepResult(
            step="traefik_deploy",
            status="error",
            message="Docker daemon is not reachable.",
            detail=f"{e}\n\nStart Docker (e.g. `sudo systemctl start docker`) and retry.",
        )


def step_traefik_healthy(inp: WizardInput, timeout: int = 60) -> StepResult:
    """Wait for Traefik to report healthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        c = docker_client.get_container("traefik")
        if c:
            if c.health in ("healthy", "none") and c.status == "running":
                return StepResult(
                    step="traefik_healthy",
                    status="ok",
                    message="Traefik is up and running.",
                )
            if c.status in ("exited", "dead"):
                try:
                    logs = docker_client.container_logs("traefik", tail=20)
                except Exception:
                    logs = "(could not retrieve logs)"
                return StepResult(
                    step="traefik_healthy",
                    status="error",
                    message="Traefik exited unexpectedly after starting.",
                    detail=f"Check the logs:\n{logs}",
                )
        time.sleep(2)

    return StepResult(
        step="traefik_healthy",
        status="error",
        message=f"Traefik did not become healthy within {timeout} seconds.",
        detail=(
            "The container may still be pulling the image or initialising. "
            "Run 'docker logs traefik' to investigate."
        ),
    )


def step_complete(inp: WizardInput) -> StepResult:
    """Mark the platform as ready in the state database."""
    try:
        with StateDB() as db:
            db.update_platform(
                status="ready",
                domain=inp.domain,
                wildcard_domain=f"*.{inp.domain}",
                network_name=inp.network_name,
                config_root=inp.config_root,
                media_root=inp.media_root,
                puid=inp.puid,
                pgid=inp.pgid,
                timezone=inp.timezone,
                cert_resolver=inp.cert_resolver,
                installed_at=int(time.time()),
                traefik_version="v3.3",
            )
        return StepResult(
            step="complete",
            status="ok",
            message="Platform setup complete. You can now install apps.",
        )
    except Exception as e:
        return StepResult(
            step="complete",
            status="error",
            message="Platform configuration could not be saved to the database.",
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# Wizard runner


def step_docker_check(inp: "WizardInput") -> "StepResult":
    """Stage 1 prerequisite: verify Docker daemon is reachable and version is adequate."""
    try:
        import subprocess
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return StepResult("docker_check", "error",
                "Docker daemon is not running or not accessible.",
                "Fix: sudo systemctl start docker   or   sudo service docker start")
        version = r.stdout.strip()
        major = int(version.split(".")[0]) if version else 0
        if major < 24:
            return StepResult("docker_check", "error",
                f"Docker {version} is too old — requires 24.0+.",
                "Fix: https://docs.docker.com/engine/install/")
        return StepResult("docker_check", "ok",
            f"Docker {version} — compatible", "")
    except FileNotFoundError:
        return StepResult("docker_check", "error",
            "Docker is not installed.",
            "Install Docker: https://docs.docker.com/engine/install/")
    except Exception as e:
        return StepResult("docker_check", "error", "Docker check failed.", str(e))


def step_dns_validation(inp: "WizardInput") -> "StepResult":
    """Stage 7: verify domain resolves to this server after Traefik deploys.

    Skipped when using Cloudflare Tunnel or Tailscale — these handle routing
    without an A record pointing at the server's public IP.
    """
    import socket
    import subprocess

    if not inp.domain:
        return StepResult("dns_validation", "skipped", "No domain configured — skipping DNS check.")

    # Tunnels route traffic without DNS A records — skip validation
    tunnel_active = getattr(inp, "cf_tunnel_token", "") or getattr(inp, "tunnels", [])
    if tunnel_active:
        return StepResult(
            "dns_validation", "skipped",
            "DNS validation skipped — tunnel handles routing without A records.",
            "Cloudflare Tunnel / Tailscale route requests to your server directly. "
            "No public DNS A record is required.",
        )

    try:
        r = subprocess.run(["curl", "-sf", "--max-time", "5", "https://api.ipify.org"],
                          capture_output=True, text=True, timeout=8)
        server_ip = r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        server_ip = None

    try:
        domain_ip = socket.gethostbyname(inp.domain)
    except socket.gaierror:
        # Domain doesn't resolve at all — warn but don't abort.
        # Traefik is already deployed; user can fix DNS and certs will issue later.
        return StepResult(
            "dns_validation", "skipped",
            f"DNS not yet configured for {inp.domain} — certificates will issue once DNS is updated.",
            f"Create an A record pointing {inp.domain} to this server's IP. "
            f"Traefik will automatically obtain a certificate once DNS propagates.",
        )

    if server_ip and domain_ip != server_ip:
        # Points to wrong IP — warn but don't abort.
        return StepResult(
            "dns_validation", "skipped",
            f"DNS points to {domain_ip} (expected {server_ip}) — certificates may not issue yet.",
            f"Update the A record for {inp.domain} to {server_ip}. "
            f"Traefik will retry certificate issuance automatically.",
        )

    # Check if acme.json already has a cert for this domain (idempotent re-run)
    try:
        import json as _j
        acme_path = Path(inp.config_root) / "traefik" / "acme.json"
        if acme_path.exists():
            acme = _j.loads(acme_path.read_text())
            cert_count = 0
            for resolver_data in acme.values():
                certs = resolver_data.get("Certificates") or []
                cert_count += sum(1 for c in certs
                                  if inp.domain in (c.get("domain", {}).get("main", "")
                                                    + " ".join(c.get("domain", {}).get("sans", []))))
            if cert_count > 0:
                return StepResult("dns_validation", "ok",
                    f"DNS OK and TLS certificate already issued — {inp.domain} → {domain_ip}", "")
    except Exception:
        pass
    return StepResult("dns_validation", "ok",
        f"DNS OK — {inp.domain} → {domain_ip}. "
        f"Traefik will obtain TLS certificate automatically (takes ~30s).", "")


def step_write_env(inp: "WizardInput") -> "StepResult":
    """Stage 7: write/update .env with wizard-collected values."""
    import os
    try:
        candidates = [config.data_dir.parent / ".env", Path("/srv/mediastack/.env")]
        env_path = next((p for p in candidates if p.parent.exists()), candidates[0])

        existing: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()

        updates = {
            "DOMAIN": inp.domain,
            "CONFIG_ROOT": inp.config_root,
            "MEDIA_ROOT": inp.media_root,
            "PUID": str(inp.puid),
            "PGID": str(inp.pgid),
            "TZ": inp.timezone,
            "ACME_EMAIL": inp.acme_email or f"admin@{inp.domain}",
            "CERT_RESOLVER": inp.cert_resolver,
            "DNS_PROVIDER": inp.dns_provider,
        }
        if inp.ntfy_enabled:
            updates["NTFY_URL"] = inp.ntfy_url
            updates["NTFY_TOPIC"] = inp.ntfy_topic

        # Write secrets collected in Stage 5 (API tokens, generated passwords, etc.)
        if inp.secrets:
            for k, v in inp.secrets.items():
                if k and v:  # skip empty values
                    updates[k] = v

        # ── TinyAuth: hash username:password → TINYAUTH_AUTH_USERS ────────
        # The wizard collects plaintext TINYAUTH_USERNAME + TINYAUTH_PASSWORD.
        # We convert them to bcrypt format that TinyAuth expects before writing .env.
        _username = updates.pop("TINYAUTH_USERNAME", None) or (inp.secrets or {}).get("TINYAUTH_USERNAME", "")
        _password = updates.pop("TINYAUTH_PASSWORD", None) or (inp.secrets or {}).get("TINYAUTH_PASSWORD", "")
        if _username and _password:
            try:
                import bcrypt as _bcrypt
                _hashed = _bcrypt.hashpw(_password.encode(), _bcrypt.gensalt(rounds=10))
                updates["TINYAUTH_AUTH_USERS"] = f"{_username}:{_hashed.decode()}"
            except ImportError:
                # bcrypt not installed — store a placeholder; user must set manually
                updates["TINYAUTH_AUTH_USERS"] = f"{_username}:REPLACE_WITH_BCRYPT_HASH"
                log.warning("bcrypt not installed — TINYAUTH_AUTH_USERS needs manual update")
            except Exception as _e:
                log.warning("Could not hash TinyAuth password: %s", _e)

        existing.update(updates)
        content = "\n".join(f"{k}={v}" for k, v in sorted(existing.items())) + "\n"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(content)
        os.chmod(env_path, 0o600)

        return StepResult("write_env", "ok",
            f".env written ({len(updates)} values, permissions 600)", str(env_path))
    except Exception as e:
        return StepResult("write_env", "error", "Could not write .env file.", str(e))


def step_persist_settings(inp: "WizardInput") -> "StepResult":
    """Persist notification and system settings to DB after platform is ready."""
    try:
        with StateDB() as db:
            db.set_setting("ntfy_url", inp.ntfy_url)
            db.set_setting("ntfy_topic", inp.ntfy_topic)
            db.set_setting("ntfy_enabled", "true" if inp.ntfy_enabled else "false")
            db.set_setting("puid", str(inp.puid))
            db.set_setting("pgid", str(inp.pgid))
            db.set_setting("timezone", inp.timezone)
            db.set_setting("traefik_dashboard_port", str(inp.traefik_dashboard_port or 8081))
        return StepResult("persist_settings", "ok", "Settings saved to database.", "")
    except Exception as e:
        return StepResult("persist_settings", "error", "Could not save settings.", str(e))




def _try_deploy_one(
    slot: str, key: str, cfg: dict[str, Any],
    deployed: list[str], failed: list[str],
) -> None:
    """Deploy one infra provider. On success appends to `deployed`,
    on any error appends to `failed`. The 'none' / empty-string keys
    are no-ops so callers can pass through unselected slots."""
    if not key or key == "none":
        return
    from backend.infra.registry import get_provider as _get
    try:
        provider = _get(slot, key)
        result = provider.deploy(cfg)
        if result.ok:
            deployed.append(key)
            log.info("Wizard: deployed infra %s/%s", slot, key)
        else:
            failed.append(f"{key}: {result.detail or result.message}")
            log.warning("Wizard: infra %s/%s deploy failed: %s",
                        slot, key, result.detail or result.message)
    except Exception as e:
        failed.append(f"{key}: {e}")
        log.warning("Wizard: infra %s/%s exception: %s", slot, key, e)


def _deploy_tunnels(inp: "WizardInput", domain: str, network: str,
                    deployed: list[str], failed: list[str]) -> None:
    """Deploy tunnel providers (cloudflared, tailscale, headscale) —
    must be up before auth routing so Traefik can route through them."""
    for tunnel in (inp.tunnels or []):
        cfg: dict[str, Any] = {"domain": domain, "network": network}
        if tunnel == "cloudflared":
            cfg["token"] = (
                inp.secrets.get("CF_TUNNEL_TOKEN", "") if inp.secrets else ""
            )
        elif tunnel in ("tailscale", "headscale"):
            cfg["auth_key"] = (
                inp.secrets.get("TAILSCALE_AUTH_KEY", "")
                or inp.secrets.get("HEADSCALE_AUTH_KEY", "")
            ) if inp.secrets else ""
        _try_deploy_one("tunnel", tunnel, cfg, deployed, failed)


def _deploy_auth(inp: "WizardInput", domain: str, network: str,
                 deployed: list[str], failed: list[str]) -> None:
    """Deploy the auth provider (tinyauth, authelia) — after tunnels."""
    if not inp.auth or inp.auth == "none":
        return
    cfg: dict[str, Any] = {
        "domain": domain,
        "network": network,
        "users": "",  # filled from TINYAUTH_AUTH_USERS in .env when relevant
    }
    if inp.auth == "tinyauth" and inp.secrets:
        cfg["users"] = inp.secrets.get("TINYAUTH_AUTH_USERS", "")
    _try_deploy_one("auth", inp.auth, cfg, deployed, failed)


def _deploy_vpn(inp: "WizardInput", domain: str, network: str,
                deployed: list[str], failed: list[str]) -> None:
    """Deploy the VPN provider (gluetun) — must be up before download clients."""
    if not inp.vpn or inp.vpn == "none":
        return
    cfg: dict[str, Any] = {"domain": domain, "network": network}
    if inp.vpn == "gluetun" and inp.secrets:
        # Map wizard secret keys → gluetun provider field keys
        cfg["vpn_service_provider"]  = inp.secrets.get("VPN_SERVICE_PROVIDER", "").strip()
        cfg["vpn_type"]              = inp.secrets.get("VPN_TYPE", "openvpn").strip().lower()
        cfg["openvpn_user"]          = inp.secrets.get("OPENVPN_USER", "")
        cfg["openvpn_password"]      = inp.secrets.get("OPENVPN_PASSWORD", "")
        cfg["wireguard_private_key"] = inp.secrets.get("WIREGUARD_PRIVATE_KEY", "")
        cfg["server_countries"]      = inp.secrets.get("SERVER_COUNTRIES", "")
    _try_deploy_one("vpn", inp.vpn, cfg, deployed, failed)


def _deploy_dashboard(inp: "WizardInput", domain: str, network: str,
                      deployed: list[str], failed: list[str]) -> None:
    """Deploy the dashboard provider (glance, homepage)."""
    if not inp.dashboard or inp.dashboard == "none":
        return
    _try_deploy_one(
        "dashboard", inp.dashboard,
        {"domain": domain, "network": network},
        deployed, failed,
    )


def _deploy_management(inp: "WizardInput", domain: str, network: str,
                       deployed: list[str], failed: list[str]) -> None:
    """Deploy the container-management provider (dockge, portainer, dockhand, komodo)."""
    if not inp.management or inp.management == "none":
        return
    cfg: dict[str, Any] = {"domain": domain, "network": network}
    if inp.management == "komodo" and inp.secrets:
        cfg["jwt_secret"] = inp.secrets.get("KOMODO_JWT_SECRET", "")
        cfg["passkey"]    = inp.secrets.get("KOMODO_PASSKEY", "")
    _try_deploy_one("management", inp.management, cfg, deployed, failed)


def _format_deploy_result(deployed: list[str], skipped: list[str],
                          failed: list[str]) -> StepResult:
    """Render the deploy_infra step's StepResult from the three buckets.

    - All three empty → 'skipped' (no providers selected)
    - Only failures   → 'error'
    - Otherwise       → 'ok' (success or partial-success; failures listed)
    """
    parts = []
    if deployed:
        parts.append(f"Deployed: {', '.join(deployed)}")
    if skipped:
        parts.append(f"Skipped: {', '.join(skipped)}")
    if failed:
        parts.append(f"Failed: {', '.join(failed)}")
    if not deployed and not failed:
        return StepResult(
            "deploy_infra", "skipped",
            "No infrastructure providers selected.", "",
        )
    if failed and not deployed:
        return StepResult(
            "deploy_infra", "error",
            "Infrastructure deployment failed.",
            "\n".join(failed),
        )
    return StepResult(
        "deploy_infra", "ok",
        " · ".join(parts),
        "\n".join(failed) if failed else "",
    )


def step_deploy_infra(inp: WizardInput) -> StepResult:
    """Deploy selected infra providers: auth, tunnels, VPN, dashboard, management.

    Calls each provider's .deploy() method in the correct order:
      tunnels first (cloudflared/tailscale) so Traefik can route through them,
      then auth (tinyauth/authelia), then VPN (gluetun), then dashboard, then management.
    Each deploy failure is logged as a warning — the step returns 'skipped' with
    details so users see what happened without stopping the whole wizard.

    Step 2.7.h: extracts the per-slot deploys (`_deploy_tunnels`,
    `_deploy_auth`, `_deploy_vpn`, `_deploy_dashboard`,
    `_deploy_management`), the inner `_deploy` closure (now the
    module-level `_try_deploy_one`), and the result-formatting
    (`_format_deploy_result`) into helpers — drops complexity from
    20 to ≤ 4.

    Step 2.6 followup: the original orchestrator had a
    `with StateDB() as db: platform = db.get_platform()` block whose
    result was unused. 2.7.h preserved it for behaviour parity, but
    that turns step_deploy_infra into a hard dependency on
    state.configure() being called first — the wizard normally
    establishes that, but several test_failure_paths tests call
    step_deploy_infra directly without configuring state. Drop the
    dead query.
    """
    domain = inp.domain or ""
    config_root = inp.config_root or ""  # noqa: F841
    network = inp.network_name or "mediastack"

    deployed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    _deploy_tunnels(inp, domain, network, deployed, failed)
    _deploy_auth(inp, domain, network, deployed, failed)
    _deploy_vpn(inp, domain, network, deployed, failed)
    _deploy_dashboard(inp, domain, network, deployed, failed)
    _deploy_management(inp, domain, network, deployed, failed)

    return _format_deploy_result(deployed, skipped, failed)

def step_verify_running(inp: "WizardInput") -> "StepResult":
    """Post-deploy verification: confirm Traefik and infra apps are running."""
    from backend.core import docker_client as _dc
    issues = []
    verified = []

    # Traefik — always required
    t = _dc.get_container("traefik")
    if t and t.status == "running":
        verified.append("traefik")
    else:
        issues.append("Traefik container not running — check: docker logs traefik")

    # Infra slots selected by user
    infra_containers = {
        "tinyauth": "tinyauth",
        "authelia": "authelia",
        "cloudflared": "cloudflared",
        "tailscale": "tailscale",
        "headscale": "headscale",
        "gluetun": "gluetun",
        "glance": "glance",
        "homepage": "homepage",
        "dockge": "dockge",
        "portainer": "portainer",
    }
    # Check all selected infra: tunnels, auth, vpn, dashboard, management
    all_selected = list(getattr(inp, "tunnels", []) or [])
    for attr in ("auth", "vpn", "dashboard", "management"):
        val = getattr(inp, attr, "none")
        if val and val != "none":
            all_selected.append(val)
    for slot_val in all_selected:
        cname = infra_containers.get(slot_val)
        if cname:
            c = _dc.get_container(cname)
            if c and c.status == "running":
                verified.append(cname)
            else:
                issues.append(f"{cname} not running — may still be starting")

    if issues:
        return StepResult(
            "verify_running", "skipped",
            f"Core verified ({', '.join(verified)}). Some items need attention.",
            "\n".join(issues),
        )
    if verified:
        return StepResult(
            "verify_running", "ok",
            f"All deployed services running: {', '.join(verified)}",
        )
    return StepResult("verify_running", "skipped", "No services to verify.", "")

# ---------------------------------------------------------------------------


STEPS = [
    ("docker_check",     step_docker_check),
    ("system_eval",      step_system_eval),
    ("preflight",        step_preflight),
    ("write_env",        step_write_env),
    ("network",          step_network),
    ("config_dirs",      step_config_dirs),
    ("traefik_config",   step_traefik_config),
    ("traefik_deploy",   step_traefik_deploy),
    ("traefik_healthy",  step_traefik_healthy),
    ("deploy_infra",     step_deploy_infra),
    ("dns_validation",   step_dns_validation),
    ("persist_settings", step_persist_settings),
    ("verify_running",   step_verify_running),
    ("complete",         step_complete),
]


def run_wizard(inp: WizardInput,
                step_callback: Callable[[StepResult], None] | None = None) -> WizardResult:
    """Run all platform wizard steps in order.

    Stops at the first error and returns the results accumulated so far.
    Steps marked 'skipped' (idempotent re-runs) don't stop execution.
    If step_callback is provided, it is called with each StepResult as it completes.
    """
    result = WizardResult()

    op_id: int | None = None
    try:
        with StateDB() as db:
            op_id = db.log_operation(
                "install", "platform", "platform",
                detail={"domain": inp.domain},
            )
    except Exception:
        pass

    for step_name, step_fn in STEPS:
        log.info("Platform wizard: running step '%s'", step_name)
        try:
            step_result = step_fn(inp)
        except Exception as e:
            step_result = StepResult(
                step=step_name,
                status="error",
                message=f"Unexpected error in step '{step_name}'.",
                detail=str(e),
            )

        result.steps.append(step_result)
        if step_callback is not None:
            try:
                step_callback(step_result)
            except Exception:
                pass
        log.info(
            "Platform wizard: step '%s' → %s: %s",
            step_name, step_result.status, step_result.message,
        )

        if step_result.status == "error":
            break

    result.platform_ready = result.ok

    # Record operation result
    if op_id is not None:
        try:
            with StateDB() as db:
                err = result.last_error()
                db.complete_operation(
                    op_id,
                    status="completed" if result.ok else "failed",
                    error=err.message if err else None,
                )
        except Exception:
            pass

    return result


def validate_wizard(inp: WizardInput) -> list[dict[str, str]]:
    """Validate wizard input before running.

    Returns a list of {field, message} dicts for any problems found.
    An empty list means the input is valid.
    """
    issues = []

    if not inp.domain or "." not in inp.domain:
        issues.append({
            "field": "domain",
            "message": "Domain must be a valid hostname like 'nyrdalyrt.com'.",
        })

    if not inp.config_root or not inp.config_root.startswith("/"):
        issues.append({
            "field": "config_root",
            "message": "Config root must be an absolute path starting with '/'.",
        })

    if not inp.media_root or not inp.media_root.startswith("/"):
        issues.append({
            "field": "media_root",
            "message": "Media root must be an absolute path starting with '/'.",
        })

    if inp.puid < 0 or inp.pgid < 0:
        issues.append({
            "field": "puid",
            "message": "PUID and PGID must be non-negative integers.",
        })

    return issues


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _clean_docker_output(raw: str) -> str:
    """Summarise Docker output — strip progress bars, keep error lines."""
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip pull progress lines
        if any(stripped.startswith(p) for p in (
            "Pulling", "Waiting", "Downloading", "Extracting",
            "Pull complete", "Already exists", "Digest:", "Status:",
        )):
            continue
        lines.append(stripped)
    return "\n".join(lines) if lines else raw[:500]


def step_socket_proxy(inp: "WizardInput") -> "StepResult":
    """Deploy the Docker socket proxy for secure Traefik API access.

    Optional step — improves security by restricting Docker API access.
    Traefik is configured to use the proxy instead of the raw socket.
    """
    from backend.core.compose import build_socket_proxy_fragment, compose_up, write_fragment
    from backend.core.config import config as _cfg

    try:
        fragment = build_socket_proxy_fragment()
        frag_path = write_fragment("docker-socket-proxy", fragment)
        rc, _out = compose_up(frag_path, timeout=30)
        if rc != 0:
            # Non-fatal — Traefik still works with raw socket
            return StepResult(
                step="socket_proxy",
                status="warning",
                message="Docker socket proxy could not start — Traefik will use raw socket.",
                detail=_out[:300],
            )
    except Exception as e:
        return StepResult(
            step="socket_proxy",
            status="warning",
            message="Docker socket proxy deployment failed — using raw socket.",
            detail=str(e),
        )

    return StepResult(
        step="socket_proxy",
        status="ok",
        message="Docker socket proxy deployed. Traefik API access is now restricted to read-only.",
    )
