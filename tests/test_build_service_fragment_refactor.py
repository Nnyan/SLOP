"""Regression tests for the build_service_fragment refactor (step 2.7.e).

`build_service_fragment` previously had cyclomatic complexity 17. The
refactor extracts 4 phase helpers (`_frag_env`, `_frag_volumes`,
`_frag_ports`, `_frag_healthcheck`) and assembles optional keys via
a (key, value) loop. The orchestrator drops to ≤ 4.

These tests exercise the helpers directly + a couple of orchestrator
behaviours that the helper-level tests don't reach (the
list-snapshot semantics for cap_add / security_opt / devices, the
no-op assembly when env/volumes/ports come back empty).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.compose import (  # noqa: E402
    _FRAGMENT_LIST_KEYS,
    _SYSTEM_PORTS,
    _frag_env,
    _frag_healthcheck,
    _frag_ports,
    _frag_volumes,
    build_service_fragment,
)


# ── _frag_env ──────────────────────────────────────────────────────


def test_env_linuxserver_default_keys() -> None:
    env = _frag_env(True, 1000, 1000, "UTC", None, None)
    assert env == {"PUID": "1000", "PGID": "1000", "TZ": "UTC"}


def test_env_non_linuxserver_omits_puid_pgid_tz() -> None:
    env = _frag_env(False, 1000, 1000, "UTC", None, None)
    assert env == {}


def test_env_static_env_layered_after_linuxserver() -> None:
    env = _frag_env(True, 1000, 1000, "UTC",
                    static_env={"FOO": "bar"}, env_overrides=None)
    assert env["FOO"] == "bar"
    assert env["PUID"] == "1000"


def test_env_overrides_win_over_static() -> None:
    """env_overrides should overwrite static_env on key collisions."""
    env = _frag_env(True, 1000, 1000, "UTC",
                    static_env={"FOO": "static"},
                    env_overrides={"FOO": "override"})
    assert env["FOO"] == "override"


# ── _frag_volumes ──────────────────────────────────────────────────


def test_volumes_default_includes_config_only() -> None:
    assert _frag_volumes("/srv/cfg", None, None) == ["/srv/cfg:/config"]


def test_volumes_includes_data_when_media_root() -> None:
    out = _frag_volumes("/srv/cfg", "/srv/media", None)
    assert "/srv/media:/data" in out


def test_volumes_appends_extra_volumes() -> None:
    out = _frag_volumes("/srv/cfg", None, [
        {"host": "/srv/x", "container": "/x"},
        {"host": "/srv/y", "container": "/y"},
    ])
    assert "/srv/x:/x" in out and "/srv/y:/y" in out


# ── _frag_ports ────────────────────────────────────────────────────


def test_ports_returns_empty_when_either_port_unset() -> None:
    assert _frag_ports(None, 8080) == []
    assert _frag_ports(8080, None) == []


def test_ports_returns_empty_for_system_ports() -> None:
    """80/443/8080/8081 → host port not bound; reachable via Traefik only."""
    for sp in _SYSTEM_PORTS:
        assert _frag_ports(sp, 9999) == [], \
            f"system port {sp} must not bind a host port"


def test_ports_binds_host_to_container_normally() -> None:
    assert _frag_ports(8989, 8989) == ["8989:8989"]
    assert _frag_ports(7878, 7879) == ["7879:7878"]


# ── _frag_healthcheck ──────────────────────────────────────────────


def test_healthcheck_none_when_no_web_port() -> None:
    assert _frag_healthcheck(None, 30) is None


def test_healthcheck_none_when_no_grace() -> None:
    assert _frag_healthcheck(8989, 0) is None


def test_healthcheck_includes_start_period_and_test() -> None:
    hc = _frag_healthcheck(8989, 60)
    assert hc is not None
    assert hc["start_period"] == "60s"
    assert any("8989" in s for s in hc["test"])


# ── build_service_fragment orchestrator ────────────────────────────


def _common(**over):
    base = dict(
        manifest_key="sonarr", display_name="Sonarr",
        image="lscr.io/linuxserver/sonarr", image_tag="latest",
        web_port=8989, host_port=8989,
        config_path="/srv/cfg/sonarr", media_root="/srv/media",
        domain="example.com",
    )
    base.update(over)
    return base


def test_orchestrator_omits_optional_when_falsy() -> None:
    """capabilities=None → 'cap_add' must NOT be in fragment.
    The (key, value) loop should skip empty/None values silently."""
    frag = build_service_fragment(**_common(linuxserver=False, media_root=None))
    assert "cap_add" not in frag
    assert "security_opt" not in frag
    assert "devices" not in frag
    assert "shm_size" not in frag


def test_orchestrator_copies_cap_add_for_snapshot_semantics() -> None:
    """The fragment should hold a *new* list, not the caller's reference."""
    caller_caps = ["NET_ADMIN"]
    frag = build_service_fragment(**_common(capabilities=caller_caps))
    assert frag["cap_add"] == ["NET_ADMIN"]
    assert frag["cap_add"] is not caller_caps, \
        "cap_add must be a copy — _FRAGMENT_LIST_KEYS list-cast preserves snapshot"


def test_orchestrator_emits_image_and_container_name_always() -> None:
    """The required-key block must always be present, regardless of options."""
    frag = build_service_fragment(**_common())
    assert frag["image"] == "lscr.io/linuxserver/sonarr:latest"
    assert frag["container_name"] == "sonarr"
    assert frag["restart"] == "unless-stopped"


def test_fragment_list_keys_match_keys_with_list_typed_inputs() -> None:
    """Drift guard: the list-cast keys must match the orchestrator's
    list[str]-typed inputs (cap_add / security_opt / devices)."""
    assert _FRAGMENT_LIST_KEYS == frozenset({"cap_add", "security_opt", "devices"})
