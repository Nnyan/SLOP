"""Regression tests for the _install_inner refactor (step 1.4.d, refactor 4/5).

`_install_inner` previously had cyclomatic complexity 26 — above Core Rule
8.1's threshold of 15. The refactor extracts ~10 phase helpers
(`_validate_install`, `_install_dependencies`, `_ensure_config_dir`,
`_compute_host_port`, `_check_port_conflict`, `_build_compose_service`,
`_write_compose_files`, `_run_deploy`, `_run_post_deploy_steps`,
`_register_install`) plus a module-scope `_SYSTEM_PORTS` constant.

These tests exercise the pure / lightly-mocked helpers; full end-to-end
install coverage remains in test_executor.py / test_fsm_app_install.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.state import init_db  # noqa: E402
from backend.manifests.executor import (  # noqa: E402
    ExecutionResult,
    _SYSTEM_PORTS,
    _check_port_conflict,
    _compute_host_port,
    _ensure_config_dir,
    _validate_install,
)


@pytest.fixture(autouse=True, scope="module")
def _fresh_state_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("install_inner_refactor") / "state.db"
    init_db(db_path)
    return db_path


def _result() -> ExecutionResult:
    return ExecutionResult(ok=True, app_key="test", operation="install")


def _platform(status: str = "ready",
              config_root: str = "/tmp/cfg") -> SimpleNamespace:
    return SimpleNamespace(status=status, config_root=config_root)


def _manifest(key: str = "testapp", display_name: str = "TestApp",
              web_port: int = 9999) -> SimpleNamespace:
    return SimpleNamespace(
        key=key, display_name=display_name, web_port=web_port,
    )


# ── _SYSTEM_PORTS / _compute_host_port ─────────────────────────────


def test_system_ports_includes_traefik_and_mediastack() -> None:
    """Traefik (80/443) and Mediastack (8080/8081) ports must be reserved."""
    assert 80 in _SYSTEM_PORTS
    assert 443 in _SYSTEM_PORTS
    assert 8080 in _SYSTEM_PORTS
    assert 8081 in _SYSTEM_PORTS


def test_compute_host_port_returns_none_for_system_port() -> None:
    """Apps whose web_port collides with a reserved port get host_port=None
    so the compose fragment doesn't try to bind it on the host."""
    assert _compute_host_port(_manifest(web_port=8080), None) is None
    assert _compute_host_port(_manifest(web_port=80), None) is None


def test_compute_host_port_uses_override_when_present() -> None:
    """host_port_override (from API param) wins over manifest.web_port."""
    assert _compute_host_port(_manifest(web_port=9999), 12345) == 12345


def test_compute_host_port_returns_normal_port_for_regular_app() -> None:
    assert _compute_host_port(_manifest(web_port=9999), None) == 9999


def test_compute_host_port_override_into_system_port() -> None:
    """Override into a system port should still trigger the None policy."""
    assert _compute_host_port(_manifest(web_port=9999), 8080) is None


# ── _validate_install ──────────────────────────────────────────────


def test_validate_install_fails_when_platform_not_ready() -> None:
    result = _result()
    out = _validate_install(_platform(status="pending"), _manifest(),
                            "testapp", existing=None, result=result)
    assert out is False
    assert result.ok is False
    assert "Platform setup is not complete" in (result.error or "")


def test_validate_install_returns_true_for_clean_install() -> None:
    """No existing app, platform ready → continue."""
    result = _result()
    out = _validate_install(_platform(), _manifest(), "testapp",
                            existing=None, result=result)
    assert out is True
    assert result.ok is True


def test_validate_install_early_success_when_already_healthy() -> None:
    """An already-running healthy container is a success early-return:
    result.ok=True but the function returns False to abort the rest."""
    existing = SimpleNamespace(status="running", container_name="testapp")
    fake_container = SimpleNamespace(
        status="running", health="healthy", id="abc",
    )
    result = _result()
    with patch("backend.manifests.executor.docker_client.get_container",
               return_value=fake_container):
        out = _validate_install(_platform(), _manifest(),
                                "testapp", existing=existing, result=result)
    assert out is False  # caller stops
    assert result.ok is True  # but it's a success, not a failure


def test_validate_install_allows_retry_on_unhealthy() -> None:
    """status=running but container actually unhealthy → allow retry."""
    existing = SimpleNamespace(status="running", container_name="testapp")
    fake_container = SimpleNamespace(
        status="restarting", health="unhealthy", id="abc",
    )
    result = _result()
    with patch("backend.manifests.executor.docker_client.get_container",
               return_value=fake_container):
        out = _validate_install(_platform(), _manifest(),
                                "testapp", existing=existing, result=result)
    assert out is True
    assert result.ok is True


def test_validate_install_continues_when_container_missing() -> None:
    """status=running but docker can't find the container → allow retry."""
    existing = SimpleNamespace(status="running", container_name="testapp")
    result = _result()
    with patch("backend.manifests.executor.docker_client.get_container",
               side_effect=RuntimeError("no such container")):
        out = _validate_install(_platform(), _manifest(),
                                "testapp", existing=existing, result=result)
    assert out is True


# ── _ensure_config_dir ─────────────────────────────────────────────


def test_ensure_config_dir_creates_directory_and_flags_new(tmp_path: Path) -> None:
    platform = SimpleNamespace(config_root=str(tmp_path))
    result = _result()
    out = _ensure_config_dir(platform, "myapp", result)
    assert out is not None
    config_path, created_now = out
    assert config_path == tmp_path / "myapp"
    assert config_path.exists()
    assert created_now is True


def test_ensure_config_dir_reports_existing_as_not_new(tmp_path: Path) -> None:
    """A pre-existing config dir should set created_now=False so the deploy
    step doesn't delete the user's data on a failed install."""
    (tmp_path / "myapp").mkdir()
    platform = SimpleNamespace(config_root=str(tmp_path))
    result = _result()
    out = _ensure_config_dir(platform, "myapp", result)
    assert out is not None
    _, created_now = out
    assert created_now is False


def test_ensure_config_dir_returns_none_on_oserror(tmp_path: Path) -> None:
    """Permission denied (or similar) → result.fail and helper returns None."""
    platform = SimpleNamespace(config_root=str(tmp_path))
    result = _result()
    with patch("pathlib.Path.mkdir",
               side_effect=PermissionError("denied")):
        out = _ensure_config_dir(platform, "myapp", result)
    assert out is None
    assert result.ok is False


# ── _check_port_conflict ───────────────────────────────────────────


def test_check_port_conflict_passes_when_no_host_port() -> None:
    """Apps without a host_port (system-port collision) skip the check."""
    result = _result()
    assert _check_port_conflict("anykey", None, result) is True
    assert result.ok is True


def test_check_port_conflict_fails_when_running_container_holds_port() -> None:
    result = _result()
    with patch("backend.manifests.executor.docker_client.ports_in_use",
               return_value={9999: "other_app"}):
        ok = _check_port_conflict("myapp", 9999, result)
    assert ok is False
    assert result.ok is False
    assert "in use" in (result.error or "")


def test_check_port_conflict_passes_when_same_app_holds_port() -> None:
    """Re-running install on the same app shouldn't trip the conflict check."""
    result = _result()
    with patch("backend.manifests.executor.docker_client.ports_in_use",
               return_value={9999: "myapp"}):
        ok = _check_port_conflict("myapp", 9999, result)
    assert ok is True
    assert result.ok is True


def test_check_port_conflict_passes_when_no_one_holds_port() -> None:
    result = _result()
    with patch("backend.manifests.executor.docker_client.ports_in_use",
               return_value={}):
        ok = _check_port_conflict("myapp", 9999, result)
    assert ok is True


# ── _install_inner orchestrator — early-fail smoke test ────────────


def test_install_inner_fails_early_on_platform_not_ready() -> None:
    """When the platform isn't ready, _install_inner stops at the first
    helper (`_validate_install`) without touching docker, deps, or DB."""
    from backend.manifests.executor import _install_inner

    fake_platform = SimpleNamespace(status="pending", config_root="/tmp")
    result = _result()
    full_manifest = SimpleNamespace(
        key="x", display_name="X", web_port=9999,
        dependencies=SimpleNamespace(postgres=False, redis=False, apps=[]),
        companions=[], post_deploy=[], custom_volumes=[], env={},
        tier=2, category="other", image="x", image_tag="latest",
        media_volume=False, linuxserver=False, content_hash="h",
        extra_config=None,
    )

    class FakeDB:
        def __enter__(self) -> "FakeDB":
            return self
        def __exit__(self, *a: object) -> None:
            pass
        def get_platform(self) -> SimpleNamespace:
            return fake_platform
        def get_app(self, key: str) -> None:
            return None

    with patch("backend.manifests.executor.StateDB", return_value=FakeDB()):
        _install_inner(full_manifest, result, extra_env=None,
                       host_port_override=None)

    assert result.ok is False
    assert "Platform setup is not complete" in (result.error or "")
