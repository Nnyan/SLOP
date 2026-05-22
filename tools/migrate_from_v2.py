#!/usr/bin/env python3
"""tools/migrate_from_v2.py — Non-destructive migration from Mediastack-RAD v2 to v3.

Reads the v2 docker-compose.yml, detects running apps, maps them to v3 manifest
keys, and installs them via the v3 API.  v2 keeps running throughout.

Usage:
  python3 tools/migrate_from_v2.py --dry-run
  python3 tools/migrate_from_v2.py --v2-path /opt/msrad --api-url http://localhost:8080
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ── v2 → v3 manifest mapping ───────────────────────────────────────────────

V2_TO_V3: dict[str, str | None] = {
    # Platform-level — handled by wizard, not catalog install
    "traefik":      None,   # platform wizard
    "cloudflared":  None,   # infra slot: tunnel → cloudflared
    "tinyauth":     None,   # infra slot: auth → tinyauth

    # Direct manifest installs
    "sonarr":       "sonarr",
    "radarr":       "radarr",
    "prowlarr":     "prowlarr",
    "bazarr":       "bazarr",
    "overseerr":    "overseerr",
    "sabnzbd":      "sabnzbd",
    "qbittorrent":  "qbittorrent",
    "plex":         "plex",
    "jellyfin":     "jellyfin",
    "emby":         "emby",
    "lidarr":       "lidarr",
    "readarr":      "readarr",
    "mylar3":       "mylar3",
    "whisparr":     "whisparr",
    "tdarr":        "tdarr",
    "fileflows":    "fileflows",
    "dozzle":       "dozzle",
    "portainer":    "portainer",
    "netdata":      "netdata",
    "scrutiny":     "scrutiny",
    "homepage":     None,   # infra slot: dashboard → homepage
    "glance":       None,   # infra slot: dashboard → glance
    "gluetun":      None,   # infra slot: vpn → gluetun
}

# ── Colours ────────────────────────────────────────────────────────────────

NO_COLOR = not sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return text if NO_COLOR else f"\033[{code}m{text}\033[0m"


green  = lambda t: _c("32", t)
yellow = lambda t: _c("33", t)
red    = lambda t: _c("31", t)
cyan   = lambda t: _c("36", t)
bold   = lambda t: _c("1",  t)
dim    = lambda t: _c("2",  t)


def info(msg: str)    -> None: print(f"  {cyan('→')} {msg}")
def ok(msg: str)      -> None: print(f"  {green('✓')} {msg}")
def warn(msg: str)    -> None: print(f"  {yellow('!')} {msg}")
def err(msg: str)     -> None: print(f"  {red('✗')} {msg}", file=sys.stderr)
def skip(msg: str)    -> None: print(f"  {dim('○')} {msg}")
def section(msg: str) -> None: print(f"\n{bold(msg)}")


# ── v2 detection ───────────────────────────────────────────────────────────


def read_v2_compose(v2_path: Path) -> dict[str, Any]:
    """Parse the v2 docker-compose.yml and return the services dict."""
    import yaml  # type: ignore[import-untyped]

    for candidate in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
        compose_file = v2_path / candidate
        if compose_file.exists():
            with open(compose_file) as f:
                data = yaml.safe_load(f)
            return data.get("services", {})

    return {}


def detect_v2_services_from_docker(v2_path: Path) -> list[str]:
    """Fallback: inspect running Docker containers for v2 service names."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        # docker compose containers are typically named <project>_<service>_1
        # or <project>-<service>-1
        project = v2_path.name  # e.g. "msrad"
        names = result.stdout.strip().split("\n")
        services = []
        for name in names:
            for sep in ("_", "-"):
                if name.startswith(project + sep):
                    svc = name[len(project) + 1:].rsplit(sep + "1", 1)[0]
                    services.append(svc)
                    break
        return services
    except Exception:
        return []


def get_v2_apps(v2_path: Path) -> dict[str, dict]:
    """Return detected v2 services with their compose config."""
    services: dict[str, Any] = {}

    # Try reading compose file
    try:
        services = read_v2_compose(v2_path)
    except ImportError:
        warn("PyYAML not available — falling back to docker ps inspection.")
    except Exception as e:
        warn(f"Could not read compose file: {e}. Falling back to docker ps.")

    if not services:
        running = detect_v2_services_from_docker(v2_path)
        services = {name: {} for name in running}

    return services


# ── v3 API client ──────────────────────────────────────────────────────────


def api_request(api_url: str, method: str, path: str,
                body: dict | None = None) -> dict:
    url = f"{api_url.rstrip('/')}/api{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            detail = json.loads(raw).get("detail", raw)
        except Exception:
            detail = raw
        raise RuntimeError(f"API error {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach v3 API at {api_url}. "
            f"Is Mediastack v3 running? ({e.reason})"
        ) from e


def get_installed_v3_keys(api_url: str) -> set[str]:
    try:
        apps = api_request(api_url, "GET", "/apps")
        return {a["key"] for a in apps}
    except Exception:
        return set()


def get_available_v3_keys(api_url: str) -> set[str]:
    try:
        catalog = api_request(api_url, "GET", "/catalog")
        keys: set[str] = set()
        for entries in catalog.values():
            for e in entries:
                keys.add(e["key"])
        return keys
    except Exception:
        return set()


# ── Main migration logic ───────────────────────────────────────────────────


def migrate(v2_path: Path, api_url: str, dry_run: bool) -> int:
    print()
    print(bold("  Mediastack v2 → v3 Migration"))
    print(dim(f"  v2 path: {v2_path}  |  v3 API: {api_url}"))
    if dry_run:
        print(f"  {yellow('DRY RUN')} — nothing will be installed")
    print()

    # ── Check v2 path
    if not v2_path.exists():
        err(f"v2 path does not exist: {v2_path}")
        return 1

    # ── Detect v2 apps
    section("Detecting v2 services…")
    v2_services = get_v2_apps(v2_path)
    if not v2_services:
        warn("No v2 services detected. Check --v2-path points to your v2 compose directory.")
        return 1

    for svc in sorted(v2_services):
        info(f"Found: {svc}")

    # ── Check v3 API
    section("Checking v3 API…")
    try:
        status = api_request(api_url, "GET", "/platform/status")
        v3_status = status.get("status", "unknown")
        info(f"v3 platform status: {v3_status}")
        if v3_status != "ready":
            warn("v3 platform not ready. Run the wizard first: ./ms wizard")
    except RuntimeError as e:
        err(str(e))
        return 1

    already_installed = get_installed_v3_keys(api_url)
    available = get_available_v3_keys(api_url)

    # ── Build migration plan
    section("Migration plan…")
    to_install: list[tuple[str, str]] = []       # (v2_name, v3_key)
    skipped_platform: list[str] = []             # platform-level, handled by wizard
    skipped_unknown: list[str] = []              # not in v2→v3 map
    skipped_existing: list[tuple[str, str]] = [] # already in v3

    for svc_name in sorted(v2_services):
        v3_key = V2_TO_V3.get(svc_name, "UNKNOWN")

        if v3_key is None:
            skipped_platform.append(svc_name)
        elif v3_key == "UNKNOWN":
            skipped_unknown.append(svc_name)
        elif v3_key in already_installed:
            skipped_existing.append((svc_name, v3_key))
        elif v3_key not in available:
            warn(f"  {svc_name} → {v3_key} (not in catalog — skip)")
        else:
            to_install.append((svc_name, v3_key))

    for svc_name in skipped_platform:
        skip(f"{svc_name} → handled by platform wizard/infra slots")
    for svc_name in skipped_unknown:
        skip(f"{svc_name} → no v3 equivalent found")
    for v2_name, v3_key in skipped_existing:
        skip(f"{v2_name} → {v3_key} (already installed in v3)")
    for v2_name, v3_key in to_install:
        info(f"{v2_name} → {bold(v3_key)}")

    if not to_install:
        print()
        ok("Nothing to migrate — all detected apps are already in v3.")
        return 0

    print(f"\n  {bold(str(len(to_install)))} apps to install: "
          + ", ".join(v3_key for _, v3_key in to_install))

    if dry_run:
        print()
        print(f"  {yellow('DRY RUN complete.')} Re-run without --dry-run to install.")
        return 0

    # ── Install
    section("Installing apps in v3…")
    errors: list[tuple[str, str]] = []
    import time

    for v2_name, v3_key in to_install:
        print(f"\n  Installing {bold(v3_key)} (from v2: {v2_name})…")
        try:
            result = api_request(api_url, "POST", f"/apps/{v3_key}/install", {})
            if result.get("installing"):
                # Poll for progress
                while True:
                    time.sleep(1)
                    progress = api_request(api_url, "GET", f"/apps/{v3_key}/install/progress")
                    for step in progress.get("steps", []):
                        st = step.get("status", "")
                        msg = step.get("message", "")
                        dot = green("✓") if st == "ok" else (yellow("!") if st == "warning" else red("✗"))
                        print(f"    {dot} {msg}")

                    if progress.get("done"):
                        if progress.get("ok"):
                            ok(f"{v3_key} installed.")
                        else:
                            err_msg = progress.get("error", "failed")
                            err(f"{v3_key}: {err_msg}")
                            errors.append((v3_key, err_msg))
                        break
        except RuntimeError as e:
            err(f"{v3_key}: {e}")
            errors.append((v3_key, str(e)))

    # ── Summary
    section("Migration summary")
    installed_count = len(to_install) - len(errors)
    if installed_count:
        ok(f"{installed_count} apps installed successfully.")
    if errors:
        for key, msg in errors:
            err(f"{key}: {msg}")
        print()
        warn("Some apps failed to install. Check the errors above.")
        warn("v2 is still running — no changes were made to your v2 stack.")
        return 1

    print()
    print("  Next steps:")
    print(f"    1. Verify v3 apps: {cyan('./ms apps list')}")
    print(f"    2. Check health: {cyan('./ms health status')}")
    print(f"    3. Switch Cloudflare Tunnel to v3 Traefik")
    print(f"    4. Stop v2: {cyan('cd /opt/msrad && docker compose down')}")
    print()
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Non-destructive migration from Mediastack-RAD v2 to v3.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # Preview what would be migrated
              python3 tools/migrate_from_v2.py --dry-run

              # Actually install detected v2 apps in v3
              python3 tools/migrate_from_v2.py --v2-path /opt/msrad

              # v3 running on a different port
              python3 tools/migrate_from_v2.py --api-url http://localhost:8090 --dry-run
        """),
    )
    parser.add_argument(
        "--v2-path",
        default="/opt/msrad",
        metavar="PATH",
        help="Path to the v2 msrad compose directory (default: /opt/msrad)",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("MEDIASTACK_URL", "http://localhost:8080"),
        metavar="URL",
        help="Mediastack v3 API URL (default: $MEDIASTACK_URL or http://localhost:8080)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be installed without actually installing",
    )
    args = parser.parse_args()

    return migrate(Path(args.v2_path), args.api_url, args.dry_run)


import textwrap

if __name__ == "__main__":
    sys.exit(main())
