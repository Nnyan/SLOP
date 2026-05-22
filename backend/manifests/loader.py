"""backend/manifests/loader.py

Loads and validates app manifests from YAML files.

A manifest is the single source of truth for everything Mediastack
knows about an app: how to deploy it, wire it, health-check it,
and remove it. This module turns raw YAML into validated AppManifest
objects that the rest of the system uses.

Usage:
    from backend.manifests.loader import load_manifest, load_all_manifests

    manifest = load_manifest("sonarr")          # loads catalog/apps/sonarr.yaml
    all_apps = load_all_manifests()             # loads all catalog/apps/*.yaml
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from backend.core.config import config
from backend.core.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Manifest validation errors
# ---------------------------------------------------------------------------


class ManifestError(Exception):
    """A manifest file has a structural or validation problem."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path.name}: {message}")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PortDef:
    internal: int
    protocol: str = "tcp"
    name: str = ""


@dataclass
class VolumeDef:
    host_path: str      # relative to config_root or absolute
    container_path: str
    readonly: bool = False


@dataclass
class WireDef:
    wire_type: str      # indexer | notification | library | ...
    peer: str           # key of the other app
    direction: str      # accepts | connects_to
    description: str = ""
    optional: bool = False


@dataclass
class PostDeployStep:
    step_type: str      # wait_healthy | api_ready | wire | custom
    timeout: int = 60
    path: str = ""      # for api_ready
    target: str = ""    # for wire
    wire_type: str = ""


@dataclass
class HealthCheckDef:
    name: str
    check_type: str     # http | tcp | process | custom
    path: str = ""
    expect_status: int = 200
    interval: int = 30
    port: int = 0       # for tcp checks: override port (defaults to app host_port)


@dataclass
class SelfHealDef:
    condition: str      # matches a health check name
    action: str         # restart | rewire | notify
    max_attempts: int = 3
    cooldown: int = 60


@dataclass
class GpuDef:
    optional: bool = True
    warn_if_absent: bool = True
    nvidia: bool = True
    amd: bool = False


@dataclass
class DependencyDef:
    postgres: bool = False
    redis: bool = False
    mariadb: bool = False
    apps: list[str] = field(default_factory=list)


@dataclass
class AppManifest:
    # ── Identity ──────────────────────────────────────────────────────────
    key: str
    display_name: str
    description: str
    category: str
    tier: int
    icon: str
    version: str
    image: str
    image_tag: str
    linuxserver: bool

    # ── Ports ─────────────────────────────────────────────────────────────
    web_port: int | None
    extra_ports: list[PortDef] = field(default_factory=list)

    # ── Storage ───────────────────────────────────────────────────────────
    config_volume: str = "/config"   # container path
    media_volume: str | None = None  # container path, None = not mounted
    custom_volumes: list[VolumeDef] = field(default_factory=list)

    # ── Environment ───────────────────────────────────────────────────────
    env: dict[str, str] = field(default_factory=dict)

    # ── Dependencies ──────────────────────────────────────────────────────
    dependencies: DependencyDef = field(default_factory=DependencyDef)

    # ── Traefik ───────────────────────────────────────────────────────────
    traefik_enabled: bool = True
    service_type: str = "management"  # management | media | internal
    traefik_subdomain: str = ""      # defaults to key if empty
    traefik_headers: dict[str, str] = field(default_factory=dict)

    # ── Wiring ────────────────────────────────────────────────────────────
    wiring: list[WireDef] = field(default_factory=list)

    # ── Post-deploy ───────────────────────────────────────────────────────
    post_deploy: list[PostDeployStep] = field(default_factory=list)

    # ── Health ────────────────────────────────────────────────────────────
    health_checks: list[HealthCheckDef] = field(default_factory=list)
    self_heal: list[SelfHealDef] = field(default_factory=list)

    # ── GPU ───────────────────────────────────────────────────────────────
    gpu: GpuDef | None = None

    # ── Companion services (app-specific, not shared) ────────────────────
    # e.g. Karakeep needs Meilisearch + Chrome — deployed and removed with the app
    companions: list[dict[str, Any]] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    # Per-app config schema — drives the config form in app detail view
    # Each entry: {key, label, type, required, placeholder, help, secret, options}
    dashboard_icon: str = ""          # override for walkxcode icon name
    start_grace_s: int = 0               # seconds after container start to skip health checks (0 = use default 120s)
    config_schema: list[dict[str, Any]] = field(default_factory=list)
    post_install: list[str] = field(default_factory=list)  # guidance shown after install
    # Default config values (pre-fills config form on first open)
    config_defaults: dict[str, Any] = field(default_factory=dict)     # must be installed first
    recommends: list[str] = field(default_factory=list)   # optional but beneficial

    # ── FUSE / privileged requirements ───────────────────────────────────────
    # For debrid/rclone containers that need SYS_ADMIN and /dev/fuse
    capabilities: list[str] = field(default_factory=list)   # e.g. ["SYS_ADMIN"]
    security_opt: list[str] = field(default_factory=list)   # e.g. ["apparmor:unconfined"]
    devices: list[str] = field(default_factory=list)        # e.g. ["/dev/fuse:/dev/fuse:rwm"]

    # ── Extra container config (cap_add, devices, etc.) ─────────────────
    extra_config: dict[str, Any] = field(default_factory=dict)

    # ── Links / tags ──────────────────────────────────────────────────────
    links: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    # ── Internal ──────────────────────────────────────────────────────────
    source_path: Path | None = None
    content_hash: str = ""          # SHA256 of source YAML

    def traefik_sub(self) -> str:
        return self.traefik_subdomain or self.key

    def to_catalog_entry(self) -> dict[str, Any]:
        """Compact dict for the UI catalog API."""
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "tier": self.tier,
            "icon": self.icon,
            "web_port": self.web_port,
            "linuxserver": self.linuxserver,
            "tags": self.tags,
            "links": self.links,
            "has_gpu": self.gpu is not None,
            "start_grace_s": self.start_grace_s or 60,
            "dependencies": {
                "postgres": self.dependencies.postgres,
                "redis": self.dependencies.redis,
                "apps": self.dependencies.apps,
            },
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


VALID_CATEGORIES = {
    "arr", "media", "downloader", "requests", "tools",
    "ai", "monitoring", "productivity", "infra",
}

VALID_STEP_TYPES = {"wait_healthy", "api_ready", "wire", "custom"}
VALID_CHECK_TYPES = {"http", "tcp", "process", "custom"}
VALID_HEAL_ACTIONS = {"restart", "rewire", "notify"}
VALID_WIRE_DIRECTIONS = {"accepts", "connects_to"}


def _require(data: dict[str, Any], key: str, path: Path) -> Any:
    val = data.get(key)
    if val is None or val == "":
        raise ManifestError(path, f"Missing required field: '{key}'")
    return val


def _parse_ports(data: dict[str, Any], path: Path) -> tuple[int | None, list[PortDef]]:
    ports_raw = data.get("ports", {})
    web_port = ports_raw.get("web")
    if web_port is not None:
        try:
            web_port = int(web_port)
        except (TypeError, ValueError):
            raise ManifestError(path, f"ports.web must be an integer, got: {web_port!r}")

    extra: list[PortDef] = []
    for p in ports_raw.get("extra", []):
        try:
            extra.append(PortDef(
                internal=int(p["internal"]),
                protocol=p.get("protocol", "tcp"),
                name=p.get("name", ""),
            ))
        except (KeyError, TypeError, ValueError) as e:
            raise ManifestError(path, f"Invalid extra port definition: {e}")

    return web_port, extra


def _parse_volumes(data: dict[str, Any], path: Path) -> tuple[str, str | None, list[VolumeDef]]:
    vol = data.get("volumes", {})
    config_vol = vol.get("config", "/config")
    media_vol = vol.get("media")

    custom: list[VolumeDef] = []
    for v in vol.get("custom", []):
        try:
            custom.append(VolumeDef(
                host_path=v["host"],
                container_path=v["container"],
                readonly=bool(v.get("readonly", False)),
            ))
        except KeyError as e:
            raise ManifestError(path, f"Custom volume missing field: {e}")

    return config_vol, media_vol, custom


def _parse_wiring(data: dict[str, Any], path: Path) -> list[WireDef]:
    wiring_raw = data.get("wiring", {})
    wires: list[WireDef] = []

    for direction in ("accepts", "connects_to"):
        peer_key = "from" if direction == "accepts" else "to"
        for entry in wiring_raw.get(direction, []):
            try:
                wires.append(WireDef(
                    wire_type=entry["type"],
                    peer=entry[peer_key],
                    direction=direction,
                    description=entry.get("description", ""),
                    optional=bool(entry.get("optional", False)),
                ))
            except KeyError as e:
                raise ManifestError(path, f"Wiring entry missing field: {e}")

    return wires


def _parse_post_deploy(data: dict[str, Any], path: Path) -> list[PostDeployStep]:
    steps = []
    for raw in data.get("post_deploy", []):
        step_type = raw.get("type", "")
        if step_type not in VALID_STEP_TYPES:
            raise ManifestError(
                path,
                f"Unknown post_deploy step type '{step_type}'. "
                f"Valid: {sorted(VALID_STEP_TYPES)}"
            )
        steps.append(PostDeployStep(
            step_type=step_type,
            timeout=int(raw.get("timeout", 60)),
            path=raw.get("path", ""),
            target=raw.get("target", ""),
            wire_type=raw.get("wire_type", ""),
        ))
    return steps


def _parse_health(data: dict[str, Any], path: Path) -> tuple[list[HealthCheckDef], list[SelfHealDef]]:
    health_raw = data.get("health", {})

    checks = []
    for raw in health_raw.get("checks", []):
        check_type = raw.get("type", "http")
        if check_type not in VALID_CHECK_TYPES:
            raise ManifestError(path, f"Unknown health check type: '{check_type}'")
        checks.append(HealthCheckDef(
            name=raw.get("name", "default"),
            check_type=check_type,
            path=raw.get("path", ""),
            expect_status=int(raw.get("expect_status", 200)),
            interval=int(raw.get("interval", 30)),
            port=int(raw.get("port", 0)),
        ))

    heals = []
    for raw in (health_raw.get("self_heal") or []):
        action = raw.get("action", "")
        if action not in VALID_HEAL_ACTIONS:
            raise ManifestError(path, f"Unknown self_heal action: '{action}'")
        heals.append(SelfHealDef(
            condition=raw.get("condition", ""),
            action=action,
            max_attempts=int(raw.get("max_attempts", 3)),
            cooldown=int(raw.get("cooldown", 60)),
        ))

    return checks, heals


def _parse_gpu(data: dict[str, Any]) -> GpuDef | None:
    gpu_raw = data.get("gpu")
    if gpu_raw is None:
        return None
    return GpuDef(
        optional=bool(gpu_raw.get("optional", True)),
        warn_if_absent=bool(gpu_raw.get("warn_if_absent", True)),
        nvidia=bool(gpu_raw.get("nvidia", True)),
        amd=bool(gpu_raw.get("amd", False)),
    )


def _parse_dependencies(data: dict[str, Any]) -> DependencyDef:
    dep = data.get("dependencies", {})
    return DependencyDef(
        postgres=bool(dep.get("postgres", False)),
        redis=bool(dep.get("redis", False)),
        mariadb=bool(dep.get("mariadb", False)),
        apps=list(dep.get("apps", [])),
    )


def _content_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def parse_manifest(path: Path) -> AppManifest:
    """Parse and validate a single manifest YAML file.

    Raises ManifestError with a plain-language message if the file is
    invalid. Never raises raw YAML or Python exceptions to callers.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ManifestError(path, f"Could not read file: {e}")

    try:
        data = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as e:
        raise ManifestError(path, f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise ManifestError(path, "Manifest must be a YAML mapping, not a list or scalar")

    # Required fields
    key = _require(data, "key", path)
    display_name = _require(data, "display_name", path)
    image = _require(data, "image", path)
    category = _require(data, "category", path)

    if not key.replace("-", "").replace("_", "").isalnum():
        raise ManifestError(path, f"key must be alphanumeric (hyphens/underscores ok), got: {key!r}")

    if category not in VALID_CATEGORIES:
        raise ManifestError(
            path,
            f"Unknown category '{category}'. Valid: {sorted(VALID_CATEGORIES)}"
        )

    tier = int(data.get("tier", 2))
    if tier not in (1, 2):
        raise ManifestError(path, f"tier must be 1 or 2, got: {tier}")

    # Structural sections
    web_port, extra_ports = _parse_ports(data, path)
    config_vol, media_vol, custom_vols = _parse_volumes(data, path)
    wiring = _parse_wiring(data, path)
    post_deploy = _parse_post_deploy(data, path)
    health_checks, self_heal = _parse_health(data, path)
    gpu = _parse_gpu(data)
    deps = _parse_dependencies(data)

    traefik_raw = data.get("traefik", {}) or {}

    env_raw = data.get("env", {}) or {}
    env = {str(k): str(v) for k, v in env_raw.items()}

    return AppManifest(
        key=key,
        display_name=display_name,
        description=data.get("description", ""),
        category=category,
        tier=tier,
        icon=data.get("icon", "📦"),
        version=str(data.get("version", "1.0")),
        image=image,
        image_tag=str(data.get("image_tag", "latest")),
        linuxserver=bool(data.get("linuxserver", True)),
        web_port=web_port,
        extra_ports=extra_ports,
        config_volume=config_vol,
        media_volume=media_vol,
        custom_volumes=custom_vols,
        env=env,
        dependencies=deps,
        traefik_enabled=bool(traefik_raw.get("enabled", True)),
        traefik_subdomain=str(traefik_raw.get("subdomain", "")),
        traefik_headers=dict(traefik_raw.get("headers", {})),
        wiring=wiring,
        post_deploy=post_deploy,
        health_checks=health_checks,
        self_heal=self_heal,
        gpu=gpu,
        companions=list(data.get("companions", []) or []),
        requires=list(data.get("requires", []) or []),
        recommends=list(data.get("recommends", []) or []),
        capabilities=list(data.get("capabilities", []) or []),
        security_opt=list(data.get("security_opt", []) or []),
        devices=list(data.get("devices", []) or []),
        extra_config=dict(data.get("extra_config", {}) or {}),
        links=dict(data.get("links", {}) or {}),
        tags=list(data.get("tags", []) or []),
        service_type=str(data.get("service_type", "management")),
        dashboard_icon=str(data.get("dashboard_icon", "") or ""),
        start_grace_s=int(data.get("start_grace_s", 0) or 0),
        config_schema=list(data.get("config_schema", []) or []),
        post_install=list(data.get("post_install", []) or []),
        config_defaults=dict(data.get("config_defaults", {}) or {}),
        source_path=path,
        content_hash=_content_hash(raw_text),
    )


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------


_cache: dict[str, AppManifest] = {}
_cache_loaded_at: float = 0.0          # epoch seconds of last load_all_manifests call
_CACHE_TTL: float = 300.0              # 5 minutes — new community manifests picked up automatically


def load_manifest(key: str, force_reload: bool = False) -> AppManifest:
    """Load a single manifest by app key.

    Checks catalog/apps/<key>.yaml. Caches result — use force_reload=True
    to pick up changes (e.g. during development or after a registry install).

    Raises ManifestError if not found or invalid.
    Raises KeyError if the key doesn't exist in the catalog.
    """
    if key in _cache and not force_reload:
        return _cache[key]

    app_path = config.catalog_dir / "apps" / f"{key}.yaml"
    if not app_path.exists():
        raise KeyError(
            f"No manifest found for '{key}'. "
            f"Looked in: {app_path}"
        )

    manifest = parse_manifest(app_path)
    if manifest.key != key:
        raise ManifestError(
            app_path,
            f"Manifest key '{manifest.key}' doesn't match filename '{key}.yaml'. "
            f"They must match."
        )

    _cache[key] = manifest
    return manifest


def load_all_manifests(force_reload: bool = False) -> dict[str, AppManifest]:
    """Load every manifest in catalog/apps/.

    Returns a dict keyed by app key. Invalid manifests are logged as
    warnings and skipped — a bad community manifest doesn't break the catalog.
    """
    global _cache_loaded_at
    import time as _time

    # Bust the cache if it's older than the TTL (default 5 min).
    # This ensures new community manifests are picked up without a restart.
    now = _time.monotonic()
    if _cache and (now - _cache_loaded_at) > _CACHE_TTL:
        log.debug("Manifest cache expired (%.0fs old) — reloading", now - _cache_loaded_at)
        _cache.clear()

    result: dict[str, AppManifest] = {}

    # Scan official catalog first, then community manifests.
    # Community manifests override official ones if keys match (allows patching).
    scan_dirs = [
        config.catalog_dir / "apps",       # official manifests (baked into image)
        config.catalog_dir / "community",  # user-pulled community manifests
    ]

    for apps_dir in scan_dirs:
        if not apps_dir.exists():
            continue
        for yaml_path in sorted(apps_dir.glob("*.yaml")):
            key = yaml_path.stem
            source = "community" if "community" in str(apps_dir) else "official"
            try:
                manifest = parse_manifest(yaml_path)
                if manifest.key != key:
                    log.warning(
                        "Skipping %s [%s] — manifest key '%s' doesn't match filename",
                        yaml_path.name, source, manifest.key,
                    )
                    continue
                if key in result and source == "community":
                    log.info("Community manifest overrides official: %s", key)
                result[key] = manifest
                _cache[key] = manifest
            except ManifestError as e:
                log.warning("Skipping invalid manifest %s [%s]: %s",
                            yaml_path.name, source, e.message)

    _cache_loaded_at = _time.monotonic()
    return result


def clear_cache() -> None:
    """Clear the manifest cache. Used in tests and on TTL expiry."""
    global _cache_loaded_at
    _cache.clear()
    _cache_loaded_at = 0.0
