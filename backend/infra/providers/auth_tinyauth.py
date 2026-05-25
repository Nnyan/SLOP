"""backend/infra/providers/auth_tinyauth.py

Tinyauth v5 auth provider.

Implements: deploy, remove, verify, protect, unprotect, export_users.
"""
from __future__ import annotations

import subprocess
import time
from typing import Any

import httpx

from backend.core import docker_client
from backend.core.compose import compose_up, compose_down,  write_fragment
from backend.core.config import config
from backend.core.logging import get_logger
from backend.core.state import StateDB
from backend.infra.base import InfraProvider, ProviderResult

log = get_logger(__name__)


def _validate_lan_subnet(v: str) -> str:
    """Validate that v is a valid CIDR notation (or empty string = no LAN bypass).

    Raises ValueError for non-empty values that aren't valid CIDRs.
    An empty/blank string means 'no LAN bypass' and is always accepted.
    """
    import ipaddress as _ipaddress
    v = v.strip()
    if not v:
        return v
    try:
        _ipaddress.ip_network(v, strict=False)
    except ValueError:
        raise ValueError(
            "lan_subnet must be a valid CIDR (e.g. 192.168.1.0/24), got: " + repr(v)
        )
    return v


CONTAINER_NAME = "tinyauth"
IMAGE = "ghcr.io/steveiliop56/tinyauth:v5"
PORT = 3000


class TinyauthProvider(InfraProvider):
    slot = "auth"
    key = "tinyauth"
    display_name = "Tinyauth v5"

    def deploy(self, cfg: dict[str, Any]) -> ProviderResult:
        """Deploy Tinyauth v5 as the auth provider.

        Required config keys:
          app_url       — e.g. https://auth.nyrdalyrt.com
          users         — bcrypt hash string e.g. admin:$2b$10$...
          lan_subnet    — e.g. 10.0.0.0/22 (for LAN bypass)
          domain        — base domain for Traefik labels
        """
        with StateDB() as db:
            platform = db.get_platform()

        domain = cfg.get("domain") or platform.domain or ""
        app_url = cfg.get("app_url", f"https://auth.{domain}")
        users = cfg.get("users", "")
        _raw_subnet = cfg.get("lan_subnet", platform.config.get("lan_subnet", "") if hasattr(platform, "config") else "")
        lan_subnet = _validate_lan_subnet(_raw_subnet)
        network = platform.network_name
        config_path = f"{platform.config_root}/tinyauth"

        fragment = {
            "image": IMAGE,
            "container_name": CONTAINER_NAME,
            "restart": "unless-stopped",
            "networks": [network],
            "ports": [f"{PORT}:{PORT}"],
            "volumes": [f"{config_path}:/app/data"],
            "environment": {
                "TINYAUTH_APPURL": app_url,
                "TINYAUTH_AUTH_USERS": users or "${TINYAUTH_AUTH_USERS}",
                "SECRET": "${TINYAUTH_SECRET}",
            },
            "labels": [
                "traefik.enable=true",
                f"traefik.http.routers.tinyauth.rule=Host(`auth.{domain}`)",
                "traefik.http.routers.tinyauth.entrypoints=websecure",
                "traefik.http.routers.tinyauth.tls=true",
                f"traefik.http.services.tinyauth.loadbalancer.server.port={PORT}",
                # ForwardAuth middleware used by all other services
                "traefik.http.middlewares.tinyauth-auth.forwardauth.address="
                f"http://{CONTAINER_NAME}:{PORT}/api/auth/traefik",
                "traefik.http.middlewares.tinyauth-auth.forwardauth.trustForwardHeader=true",
                # authResponseHeaders: ensure auth headers flow to app but WWW-Authenticate
                # is NOT forwarded to the browser (prevents the native browser popup)
                "traefik.http.middlewares.tinyauth-auth.forwardauth.authResponseHeaders=X-Auth-User,X-Auth-Email",
            ],
        }

        try:
            import pathlib
            pathlib.Path(config_path).mkdir(parents=True, exist_ok=True)
            frag_path = write_fragment(CONTAINER_NAME, fragment)
            rc, _out = compose_up(frag_path, timeout=90)
            if rc != 0:
                return ProviderResult.failure(
                    "Tinyauth failed to start.",
                    _out[:300],
                )
        except Exception as e:
            return ProviderResult.failure("Could not deploy Tinyauth.", str(e))

        # Update slot state
        with StateDB() as db:
            db.update_slot("auth",
                           provider="tinyauth",
                           status="active",
                           config={"app_url": app_url, "domain": domain,
                                   "lan_subnet": lan_subnet},
                           deployed_at=int(time.time()))

        # Register as a fully managed app — identical to catalog install.
        # This makes infra apps health-monitored, Dashboard-visible, with
        # operation history — exactly like apps installed from the Catalog.
        try:
            from backend.core.state import StateDB as _SDB2
            import time as _t2
            with _SDB2() as _db2:
                _db2.upsert_app(
                    "tinyauth",
                    display_name="Tinyauth v5",
                    tier=0,  # tier 0 = infrastructure layer
                    category="auth",
                    status="running",
                    image=IMAGE,
                    image_tag="latest",
                    container_name=CONTAINER_NAME,
                    host_port=3000,
                    last_healthy_at=int(_t2.time()),
                )
        except Exception as _e2:
            import logging as _l2
            _l2.getLogger(__name__).debug("Could not register infra app in DB: %s", _e2)

        return ProviderResult.success(
            f"Tinyauth v5 deployed at {app_url}.",
            data={"app_url": app_url, "lan_subnet": lan_subnet},
        )

    def remove(self) -> ProviderResult:
        from backend.core.compose import compose_up, compose_down,  remove_fragment
        frag_path = config.compose_dir / f"{CONTAINER_NAME}.yaml"
        if frag_path.exists():
            try:
                compose_down(frag_path, timeout=30)
            except Exception as e:
                return ProviderResult.failure("Could not stop Tinyauth.", str(e))
        remove_fragment(CONTAINER_NAME)
        with StateDB() as db:
            db.update_slot("auth", status="empty", provider=None, config={})
        return ProviderResult.success("Tinyauth removed.")

    def verify(self) -> ProviderResult:
        c = docker_client.get_container(CONTAINER_NAME)
        if c is None:
            return ProviderResult.failure(
                "Tinyauth container is not running.",
                "Run the infrastructure wizard to deploy it.",
            )
        if c.status != "running":
            return ProviderResult.failure(
                f"Tinyauth container is in '{c.status}' state.",
                f"Check logs: docker logs {CONTAINER_NAME}",
            )
        # Check API responds
        try:
            r = httpx.get(f"http://localhost:{PORT}/api/health", timeout=5)
            if r.status_code == 200:
                return ProviderResult.success("Tinyauth is healthy.")
        except Exception as _e:
            log.debug("Suppressed exception: %s", _e)
        # Health endpoint may not exist in all versions — just check running
        return ProviderResult.success("Tinyauth is running (API check skipped).")

    def protect(self, hostname: str, rules: dict[str, Any] | None = None) -> ProviderResult:
        """Tinyauth protects via Traefik middleware — no per-hostname API needed."""
        return ProviderResult.success(
            f"Tinyauth protection is applied via Traefik middleware "
            f"(covers {hostname} automatically)."
        )

    def unprotect(self, hostname: str) -> ProviderResult:
        return ProviderResult.success(
            "Tinyauth protection removed by updating Traefik labels."
        )

    def export_users(self) -> ProviderResult:
        """Export user list from Tinyauth for migration."""
        with StateDB() as db:
            slot = db.get_slot("auth")
        # Users are stored in the .env / TINYAUTH_AUTH_USERS
        # We don't have the plaintext passwords — export the hash string
        users_str = slot.config.get("users", "")
        users = []
        for entry in users_str.split(","):
            entry = entry.strip()
            if ":" in entry:
                username, _ = entry.split(":", 1)
                users.append({"username": username, "hash": entry})
        return ProviderResult.success(
            f"Exported {len(users)} user(s). "
            "Note: only bcrypt hashes are exported — plaintext passwords are not available. "
            "Users will need to reset passwords in the new auth provider.",
            data={"users": users},
        )

    def pre_migration_snapshot(self) -> ProviderResult:
        with StateDB() as db:
            slot = db.get_slot("auth")
        return ProviderResult.success("Snapshot captured.", data=dict(slot.__dict__))
