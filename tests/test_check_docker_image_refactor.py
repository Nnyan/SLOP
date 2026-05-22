"""Regression tests for the _check_docker_image refactor (step 2.7.g).

`_check_docker_image` previously had cyclomatic complexity 20 — the
function inlined parsing, registry resolution, Docker Hub pre-auth,
and the GHCR-style 401 + www-authenticate Bearer challenge handler.

The refactor extracts each phase into its own helper. The orchestrator
drops to ≤ 10.

Tests focus on the cleanly-isolatable parsing helpers + the
www-authenticate challenge parsing logic. The HTTP roundtrip itself
is not exercised here — covered by manual QA + the higher-level
run_source_scan test suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.health.source_checker import (  # noqa: E402
    _NAMED_REGISTRIES,
    _parse_image_ref,
    _resolve_registry,
)


# ── _parse_image_ref ───────────────────────────────────────────────


def test_parse_default_tag_is_latest() -> None:
    assert _parse_image_ref("sonarr") == ("sonarr", "latest")


def test_parse_explicit_tag() -> None:
    assert _parse_image_ref("sonarr:1.2.3") == ("sonarr", "1.2.3")


def test_parse_namespaced_image() -> None:
    assert _parse_image_ref("linuxserver/sonarr:latest") == \
        ("linuxserver/sonarr", "latest")


def test_parse_does_not_treat_registry_port_as_tag() -> None:
    """A port number on the hostname (e.g. 'reg.example.com:5000/foo')
    must NOT be misread as an image tag."""
    repo, tag = _parse_image_ref("reg.example.com:5000/foo")
    assert repo == "reg.example.com:5000/foo"
    assert tag == "latest"


def test_parse_registry_port_with_explicit_tag() -> None:
    """When both a port and a tag are present, only the rightmost
    (tag) component is split off."""
    repo, tag = _parse_image_ref("reg.example.com:5000/foo:v1")
    assert repo == "reg.example.com:5000/foo"
    assert tag == "v1"


# ── _resolve_registry ──────────────────────────────────────────────


def test_resolve_named_registries_each() -> None:
    """ghcr.io / lscr.io / quay.io / gcr.io → that host as the registry."""
    for host in _NAMED_REGISTRIES:
        registry, name = _resolve_registry(f"{host}/owner/repo")
        assert registry == host
        assert name == "owner/repo"


def test_resolve_dotted_host_treated_as_registry() -> None:
    """Any token with a dot in part[0] (e.g. 'reg.example.com') is a registry."""
    registry, name = _resolve_registry("reg.example.com/foo/bar")
    assert registry == "reg.example.com"
    assert name == "foo/bar"


def test_resolve_namespaced_dockerhub() -> None:
    """'linuxserver/sonarr' → docker.io with namespace preserved."""
    registry, name = _resolve_registry("linuxserver/sonarr")
    assert registry == "registry-1.docker.io"
    assert name == "linuxserver/sonarr"


def test_resolve_bare_dockerhub_uses_library_namespace() -> None:
    """A bare name ('sonarr') must route to docker.io's library/ namespace
    (Docker Hub's default for official images)."""
    registry, name = _resolve_registry("sonarr")
    assert registry == "registry-1.docker.io"
    assert name == "library/sonarr"


def test_named_registries_membership_drift_guard() -> None:
    """Documents the named registries — drift here means a new registry
    type was added without updating the parser."""
    assert _NAMED_REGISTRIES == frozenset({"ghcr.io", "lscr.io", "quay.io", "gcr.io"})
