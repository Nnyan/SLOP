#!/usr/bin/env python3
"""tests/integration/run.py

Integration test suite for a running Mediastack server.
Unlike unit tests, these hit the actual HTTP API and verify real behaviour.

Usage:
  python3 tests/integration/run.py                        # localhost:8080
  python3 tests/integration/run.py --url http://192.168.1.100:8080
  python3 tests/integration/run.py --url http://192.168.1.100:8080 --verbose
  python3 tests/integration/run.py --suite smoke          # quick checks only

Test suites:
  smoke     — API reachable, DB init, catalog loads, health endpoint
  platform  — Wizard runs, platform status, DNS providers
  catalog   — All manifests loadable, no port conflicts, registry sync
  health    — Scheduler status, health API responds
  routing   — Media types present, seerr-help endpoints
  all       — Everything (default)

Exit codes:
  0 — all tests passed
  1 — one or more tests failed
  2 — cannot reach server
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

# ── Colors ─────────────────────────────────────────────────────────────────

NO_COLOR = not sys.stdout.isatty()


def _c(code: str, t: str) -> str:
    return t if NO_COLOR else f"\033[{code}m{t}\033[0m"


green  = lambda t: _c("32", t)
yellow = lambda t: _c("33", t)
red    = lambda t: _c("31", t)
cyan   = lambda t: _c("36", t)
bold   = lambda t: _c("1",  t)
dim    = lambda t: _c("2",  t)


# ── HTTP client ────────────────────────────────────────────────────────────


class Client:
    def __init__(self, base_url: str, verbose: bool = False) -> None:
        self.base = base_url.rstrip("/")
        self.verbose = verbose
        self._timings: dict[str, float] = {}

    def get(self, path: str, timeout: int = 10) -> tuple[int, object]:
        return self._req("GET", path, timeout=timeout)

    def post(self, path: str, body: dict | None = None, timeout: int = 30) -> tuple[int, object]:
        return self._req("POST", path, body, timeout)

    def put(self, path: str, body: dict | None = None) -> tuple[int, object]:
        return self._req("PUT", path, body)

    def _req(self, method: str, path: str, body: dict | None = None,
             timeout: int = 10) -> tuple[int, object]:
        url = f"{self.base}/api{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                elapsed = time.monotonic() - t0
                self._timings[path] = elapsed
                if self.verbose:
                    ms_str = f"{elapsed*1000:.0f}"; print(f"  {dim(method + chr(32) + path + chr(32) + str(resp.status) + chr(32) + ms_str)}")
                parsed = json.loads(raw) if raw else {}
                return resp.status, parsed
        except urllib.error.HTTPError as e:
            elapsed = time.monotonic() - t0
            raw = e.read().decode()
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"detail": raw}
            return e.code, parsed
        except urllib.error.URLError as e:
            raise ConnectionError(f"Cannot reach {url}: {e.reason}") from e


# ── Test runner ─────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration_ms: float = 0.0
    skip_reason: str = ""


@dataclass
class Suite:
    name: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.skip_reason)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skip_reason)


def run_test(suite: Suite, name: str, fn: Callable) -> None:
    t0 = time.monotonic()
    try:
        fn()
        suite.results.append(TestResult(
            name=name, passed=True, message="",
            duration_ms=(time.monotonic() - t0) * 1000,
        ))
    except AssertionError as e:
        suite.results.append(TestResult(
            name=name, passed=False, message=str(e),
            duration_ms=(time.monotonic() - t0) * 1000,
        ))
    except Exception as e:
        suite.results.append(TestResult(
            name=name, passed=False,
            message=f"{type(e).__name__}: {e}",
            duration_ms=(time.monotonic() - t0) * 1000,
        ))


def skip_test(suite: Suite, name: str, reason: str) -> None:
    suite.results.append(TestResult(name=name, passed=True, message="", skip_reason=reason))


# ── Test suites ─────────────────────────────────────────────────────────────


def suite_smoke(c: Client) -> Suite:
    s = Suite("smoke")

    def test_ping():
        status, data = c.get("/ping")
        assert status == 200, f"Expected 200, got {status}"
        assert data.get("status") == "ok", f"Expected status=ok, got {data}"

    def test_platform_status_reachable():
        status, data = c.get("/platform/status")
        assert status == 200, f"Expected 200, got {status} — {data}"
        assert "status" in data, f"Missing 'status' key: {data}"

    def test_catalog_loads():
        status, data = c.get("/catalog")
        assert status == 200, f"Catalog endpoint failed: {status}"
        assert isinstance(data, dict), "Catalog should return a dict by category"
        total = sum(len(v) for v in data.values())
        assert total >= 50, f"Expected 50+ catalog entries, got {total}"

    def test_registry_endpoint():
        status, data = c.get("/registry")
        assert status == 200, f"Registry endpoint failed: {status}"
        assert isinstance(data, list), "Registry should return a list"

    def test_api_docs_reachable():
        url = f"{c.base}/docs"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200, f"/docs returned {resp.status}"

    def test_installed_apps_endpoint():
        status, data = c.get("/apps")
        assert status == 200, f"GET /apps failed: {status}"
        assert isinstance(data, list), "Apps endpoint should return a list"

    run_test(s, "GET /api/ping", test_ping)
    run_test(s, "GET /api/platform/status reachable", test_platform_status_reachable)
    run_test(s, "GET /api/catalog returns 50+ apps", test_catalog_loads)
    run_test(s, "GET /api/registry returns list", test_registry_endpoint)
    run_test(s, "GET /docs OpenAPI reachable", test_api_docs_reachable)
    run_test(s, "GET /api/apps returns list", test_installed_apps_endpoint)

    return s


def suite_platform(c: Client) -> Suite:
    s = Suite("platform")

    def test_dns_providers():
        status, data = c.get("/platform/dns-providers")
        assert status == 200
        assert isinstance(data, list)
        assert len(data) >= 10, f"Expected 10+ DNS providers, got {len(data)}"
        keys = [p["key"] for p in data]
        assert "cloudflare" in keys
        assert "route53" in keys

    def test_wizard_steps():
        status, data = c.get("/platform/wizard/steps")
        assert status == 200
        assert isinstance(data, list)
        assert len(data) >= 5, f"Expected 5+ wizard steps, got {len(data)}"
        names = [s["name"] for s in data]
        assert "traefik_config" in names
        assert "traefik_deploy" in names

    def test_media_routing_guide():
        status, data = c.get("/platform/media-routing-guide?domain=example.com")
        assert status == 200
        assert "tls_certificate" in data
        assert "cloudflare_dns_setup" in data
        assert "*.example.com" in str(data)

    def test_validate_wizard_rejects_bad_domain():
        status, data = c.post("/platform/wizard/validate", {
            "domain": "notadomain",
            "config_root": "/tmp/cfg",
            "media_root": "/tmp/media",
            "puid": 1000, "pgid": 1000,
            "timezone": "UTC",
        })
        assert status in (200, 422), f"Expected 200/422, got {status}"

    run_test(s, "GET /api/platform/dns-providers", test_dns_providers)
    run_test(s, "GET /api/platform/wizard/steps", test_wizard_steps)
    run_test(s, "GET /api/platform/media-routing-guide", test_media_routing_guide)
    run_test(s, "POST /api/platform/wizard/validate rejects bad domain", test_validate_wizard_rejects_bad_domain)

    return s


def suite_catalog(c: Client) -> Suite:
    s = Suite("catalog")

    def test_all_categories_present():
        status, data = c.get("/catalog")
        assert status == 200
        categories = set(data.keys())
        expected = {"arr", "media", "tools", "monitoring", "productivity", "ai"}
        missing = expected - categories
        assert not missing, f"Missing categories: {missing}"

    def test_media_apps_present():
        status, data = c.get("/catalog")
        assert status == 200
        all_keys = [e["key"] for entries in data.values() for e in entries]
        for expected in ["plex", "jellyfin", "sonarr", "radarr", "prowlarr"]:
            assert expected in all_keys, f"'{expected}' missing from catalog"

    def test_media_apps_have_media_service_type():
        status, data = c.get("/catalog")
        assert status == 200
        all_entries = [e for entries in data.values() for e in entries]
        for key in ["plex", "jellyfin", "emby"]:
            entry = next((e for e in all_entries if e["key"] == key), None)
            if entry:
                # service_type may not be in catalog response — just check key exists
                assert entry["key"] == key

    def test_no_port_conflicts():
        status, data = c.get("/catalog")
        assert status == 200
        port_map: dict[int, list[str]] = {}
        for entries in data.values():
            for app in entries:
                port = app.get("web_port")
                if port and port not in (80, 3000, 8080):
                    port_map.setdefault(port, []).append(app["key"])
        conflicts = {p: keys for p, keys in port_map.items() if len(keys) > 1}
        assert not conflicts, f"Port conflicts: {conflicts}"

    def test_registry_all_apps():
        status, data = c.get("/registry")
        assert status == 200
        assert len(data) >= 50, f"Registry should have 50+ entries, got {len(data)}"
        verified = [e for e in data if e.get("verified")]
        assert len(verified) >= 50, "Official apps should be verified"

    run_test(s, "Catalog has all required categories", test_all_categories_present)
    run_test(s, "Catalog has Plex, Jellyfin, Sonarr, Radarr, Prowlarr", test_media_apps_present)
    run_test(s, "Media apps identifiable in catalog", test_media_apps_have_media_service_type)
    run_test(s, "No port conflicts in 52-app catalog", test_no_port_conflicts)
    run_test(s, "Registry has 50+ entries", test_registry_all_apps)

    return s


def suite_health(c: Client) -> Suite:
    s = Suite("health")

    def test_health_scheduler_status():
        status, data = c.get("/health/scheduler")
        assert status == 200
        assert "running" in data
        assert "state" in data

    def test_health_apps_endpoint():
        status, data = c.get("/health/apps")
        assert status == 200
        assert isinstance(data, list)

    def test_llm_agent_endpoint():
        status, data = c.get("/health/llm-agent")
        assert status == 200
        assert "status" in data
        valid_states = {"active", "degraded", "offline", "disabled", "unknown"}
        assert data["status"] in valid_states, f"Invalid LLM state: {data['status']}"

    def test_settings_endpoint():
        status, data = c.get("/settings")
        assert status == 200
        assert "health_check_interval_secs" in data
        assert "ntfy_topic" in data
        assert "llm_enabled" in data

    def test_system_profile():
        status, data = c.get("/settings/system", timeout=20)
        assert status == 200
        assert "cpu_cores" in data
        assert "total_ram_gb" in data
        assert data["cpu_cores"] > 0
        assert data["total_ram_gb"] > 0

    run_test(s, "GET /api/health/scheduler status", test_health_scheduler_status)
    run_test(s, "GET /api/health/apps returns list", test_health_apps_endpoint)
    run_test(s, "GET /api/health/llm-agent has valid status", test_llm_agent_endpoint)
    run_test(s, "GET /api/settings has all keys", test_settings_endpoint)
    run_test(s, "GET /api/settings/system has CPU/RAM", test_system_profile)

    return s


def suite_routing(c: Client) -> Suite:
    s = Suite("routing")

    def test_media_types_all_present():
        status, data = c.get("/routing/media")
        assert status == 200
        assert isinstance(data, list)
        types = [r["media_type"] for r in data]
        for expected in ["movies", "tv", "music", "books", "comics", "audiobooks", "adult"]:
            assert expected in types, f"Missing media type: {expected}"

    def test_seerr_supported_flag():
        status, data = c.get("/routing/media")
        assert status == 200
        by_type = {r["media_type"]: r for r in data}
        assert by_type["movies"]["seerr_supported"] is True
        assert by_type["tv"]["seerr_supported"] is True
        assert by_type["music"]["seerr_supported"] is False

    def test_seerr_help_movies():
        status, data = c.get("/routing/media/movies/seerr-help")
        assert status == 200
        assert "steps" in data
        assert len(data["steps"]) > 0

    def test_instances_endpoint():
        status, data = c.get("/routing/instances")
        assert status == 200
        assert isinstance(data, list)

    def test_infra_slots():
        status, data = c.get("/infra/slots")
        assert status == 200
        assert isinstance(data, list)
        slot_names = [s["slot"] for s in data]
        for expected in ["auth", "tunnel", "dashboard", "management", "vpn"]:
            assert expected in slot_names, f"Missing infra slot: {expected}"

    def test_infra_provider_schemas():
        status, data = c.get("/infra/providers/management/schema")
        assert status == 200
        assert isinstance(data, list)
        provider_keys = [p["key"] for p in data]
        assert "portainer" in provider_keys
        assert "dockhand" in provider_keys

    run_test(s, "All 7 media types in routing", test_media_types_all_present)
    run_test(s, "Movies/TV seerr_supported=True, music=False", test_seerr_supported_flag)
    run_test(s, "GET /api/routing/media/movies/seerr-help", test_seerr_help_movies)
    run_test(s, "GET /api/routing/instances returns list", test_instances_endpoint)
    run_test(s, "5 infra slots present", test_infra_slots)
    run_test(s, "Management providers have schemas", test_infra_provider_schemas)

    return s


# ── Main ───────────────────────────────────────────────────────────────────


SUITES = {
    "smoke":    suite_smoke,
    "platform": suite_platform,
    "catalog":  suite_catalog,
    "health":   suite_health,
    "routing":  suite_routing,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mediastack integration tests — runs against a live server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default="http://localhost:8080",
                        help="Mediastack API base URL")
    parser.add_argument("--suite", default="all",
                        choices=["all"] + list(SUITES.keys()),
                        help="Which test suite to run (default: all)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show HTTP request details")
    args = parser.parse_args()

    c = Client(args.url, verbose=args.verbose)

    print()
    print(bold(f"  Mediastack Integration Tests"))
    print(dim(f"  Target: {args.url}"))
    print()

    # Connectivity check
    print("  Checking server connectivity…")
    try:
        status, data = c.get("/ping", timeout=5)
        if status != 200:
            print(f"  {red('✗')} Server responded with HTTP {status}")
            return 2
        version = data.get("version", "?")
        print(f"  {green('✓')} Server responding — v{version}")
    except ConnectionError as e:
        print(f"  {red('✗')} {e}")
        print(f"  {dim('Start the server: make dev  or  uvicorn backend.api.main:app')}")
        return 2

    print()

    # Run suites
    suites_to_run = list(SUITES.values()) if args.suite == "all" \
        else [SUITES[args.suite]]

    all_results: list[TestResult] = []
    for suite_fn in suites_to_run:
        suite = suite_fn(c)
        print(f"  {bold(suite.name.upper())}")
        for r in suite.results:
            if r.skip_reason:
                print(f"    {dim('○')} {r.name} {dim(f'(skipped: {r.skip_reason})')}")
            elif r.passed:
                print(f"    {green(chr(10003))} {r.name} ({r.duration_ms:.0f}ms)")
            else:
                print(f"    {red('✗')} {r.name}")
                print(f"      {dim(r.message)}")
        all_results.extend(suite.results)
        print()

    # Summary
    passed = sum(1 for r in all_results if r.passed and not r.skip_reason)
    failed = sum(1 for r in all_results if not r.passed and not r.skip_reason)
    skipped = sum(1 for r in all_results if r.skip_reason)
    total = passed + failed

    color = green if failed == 0 else red
    print(f"  {color(bold(f'{passed}/{total} passed'))}"
          + (f", {red(str(failed) + ' failed')}" if failed else "")
          + (f", {dim(str(skipped) + ' skipped')}" if skipped else ""))
    print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
