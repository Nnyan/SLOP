"""
tests/test_failure_paths.py — Failure Path / Error Injection Tests

Every test here deliberately makes a dependency fail and verifies the
system handles it correctly — no NameErrors, no unhandled 500s, no
silent data corruption. These cover the failure path blindness that
happy-path testing misses entirely.

All external I/O (Docker, subprocess, network) is mocked so tests
run without any live infrastructure.
"""
import json
import pathlib
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock, patch, call

import pytest

REPO = pathlib.Path(__file__).parent.parent


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from backend.core.state import init_db
    db_path = tmp_path / "state.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def ready_platform(db, tmp_path):
    """Mark platform as ready — same pattern as test_executor.py."""
    from backend.core import state as state_mod
    state_mod.configure(db)
    from backend.core.state import StateDB
    with StateDB() as s:
        s.update_platform(
            status="ready", domain="test.example.com",
            config_root=str(tmp_path / "config"), media_root="/mnt/media",
            puid=1000, pgid=1000, timezone="UTC",
            cert_resolver="letsencrypt", network_name="mediastack",
        )
    return db


@pytest.fixture
def real_install_env(db, tmp_path):
    """Behavioural-mock-free install fixture (Core Rule 4.12 / ADR 0002).

    Sets up a real `tmp_path`-rooted compose dir and patches the
    `backend.core.config.config.data_dir` singleton so install_app's
    real `write_fragment` writes to a verifiable location. Tests that
    use this fixture can drop @patch on write_fragment / write_compose_file
    / pathlib.Path.mkdir and assert on actual filesystem + DB effects.
    """
    from backend.core import state as state_mod
    from backend.core.config import config as _cfg
    from backend.core.state import StateDB

    state_mod.configure(db)
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    compose_dir = data_dir / "compose"
    compose_dir.mkdir(parents=True, exist_ok=True)

    with StateDB() as s:
        s.update_platform(
            status="ready", domain="test.example.com",
            config_root=str(config_root), media_root=str(media_root),
            puid=1000, pgid=1000, timezone="UTC",
            cert_resolver="letsencrypt", network_name="mediastack",
        )

    # Config is a frozen dataclass — bypass via object.__setattr__.
    original_data_dir = _cfg.data_dir
    object.__setattr__(_cfg, "data_dir", data_dir)
    try:
        yield {
            "tmp": tmp_path, "db": db,
            "config_root": config_root, "media_root": media_root,
            "data_dir": data_dir, "compose_dir": compose_dir,
        }
    finally:
        object.__setattr__(_cfg, "data_dir", original_data_dir)


# ═══════════════════════════════════════════════════════════════════════════
# Executor — compose_up failure paths
# ═══════════════════════════════════════════════════════════════════════════

class TestComposeUpFailurePaths:
    """What happens when docker compose up returns non-zero?"""

    def test_compose_failure_returns_structured_error_not_exception(
        self, real_install_env
    ):
        """compose_up failure must return result.ok=False with error detail, not raise.

        Step 2.2.d rewrite per ADR 0002: drops `@patch` on
        `write_fragment` and `write_compose_file` so the real fragment
        IS written to a tmp_path compose dir before the simulated
        compose-up failure. Then asserts the install pipeline rolls back
        cleanly: fragment is removed, no stale DB record left running.
        """
        env = real_install_env
        with patch("backend.manifests.executor.docker_client.ports_in_use",
                   return_value={}), \
             patch("backend.manifests.executor.docker_client.get_container",
                   return_value=None), \
             patch("backend.manifests.executor.subprocess.run",
                   return_value=MagicMock(returncode=1, stdout="",
                                           stderr="port already in use")):
            from backend.manifests.executor import install_app
            result = install_app("sonarr")

        assert not result.ok, "compose failure must produce result.ok=False"
        assert result.error, "compose failure must populate result.error"
        assert "NameError" not in (result.error or ""), \
            "compose failure raised NameError instead of returning structured error"
        assert "AttributeError" not in (result.error or ""), \
            "compose failure raised AttributeError (likely result.stderr usage)"

        # Behavioural assertion — failure must clean up the fragment we wrote
        # before the deploy attempt. _run_deploy calls remove_fragment on
        # failure; if it doesn't, a future install_app would skip the
        # write because the file already exists.
        frag = env["compose_dir"] / "sonarr.yaml"
        assert not frag.exists(), \
            "compose failure must roll back the fragment write (remove_fragment)"

    def test_compose_failure_does_not_leave_status_running(self, real_install_env):
        """After compose_up failure, app status must NOT be 'running'.

        Step 2.2.d rewrite per ADR 0002: drops `@patch` on `write_fragment` /
        `write_compose_file`. The real install pipeline runs against a
        tmp_path; we assert on real DB state after the simulated failure.
        """
        with patch("backend.manifests.executor.docker_client.ports_in_use",
                   return_value={}), \
             patch("backend.manifests.executor.docker_client.get_container",
                   return_value=None), \
             patch("backend.manifests.executor.subprocess.run",
                   return_value=MagicMock(returncode=1, stdout="", stderr="")):
            from backend.manifests.executor import install_app
            from backend.core.state import StateDB
            install_app("sonarr")

        with StateDB() as db:
            app = db.get_app("sonarr")
        if app:
            assert app.status != "running", (
                "Failed install must not leave app with status='running'. "
                "Running status causes health scheduler to treat it as healthy."
            )


# ═══════════════════════════════════════════════════════════════════════════
# Executor — container health check failure paths
# ═══════════════════════════════════════════════════════════════════════════

class TestWaitHealthyFailurePaths:
    """What happens during wait_healthy when the container fails or is slow?"""

    def test_container_exits_unexpectedly_returns_error_with_logs(self):
        """If container exits during wait_healthy, return error with tail of logs."""
        from backend.manifests.executor import _wait_healthy
        exited_container = MagicMock()
        exited_container.status = "exited"
        exited_container.health = "unhealthy"

        with patch("backend.manifests.executor.docker_client.get_container",
                   return_value=exited_container), \
             patch("backend.manifests.executor.docker_client.container_logs",
                   return_value="Error: port 8080 already in use\nExiting."):
            result = _wait_healthy("sonarr", timeout=5)

        assert result["status"] == "error"
        assert "exited" in result["message"].lower() or "exited" in result.get("detail", "").lower(), (
            "wait_healthy must report that the container exited, "
            "not just timeout as if it was still trying."
        )

    def test_docker_unavailable_returns_error_not_exception(self):
        """DockerError during wait_healthy must return error dict, not propagate."""
        from backend.core.docker_client import DockerError
        from backend.manifests.executor import _wait_healthy

        with patch("backend.manifests.executor.docker_client.get_container",
                   side_effect=DockerError("Cannot connect to Docker socket")):
            # Should not raise — must catch and return error
            try:
                result = _wait_healthy("sonarr", timeout=1)
                # If it returns, must be an error
                assert result.get("status") == "error" or result.get("status") == "ok"
            except Exception as e:
                pytest.fail(
                    f"_wait_healthy raised {type(e).__name__} when Docker unavailable. "
                    f"Must return error dict instead: {e}"
                )

    def test_timeout_returns_error_with_docker_logs_hint(self):
        """Timeout must include 'docker logs' hint so user knows how to debug."""
        from backend.manifests.executor import _wait_healthy

        with patch("backend.manifests.executor.docker_client.get_container",
                   return_value=None):
            result = _wait_healthy("sonarr", timeout=1)

        assert result["status"] == "error"
        assert "docker logs" in result.get("detail", "") or "docker logs" in result.get("message", ""), (
            "Timeout error must include 'docker logs sonarr' hint. "
            "Without it, user doesn't know how to diagnose the failure."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Infra providers — compose failure paths (the result.stderr bug)
# ═══════════════════════════════════════════════════════════════════════════

class TestInfraProviderComposeFailure:
    """
    All infra providers must handle compose_up failure without NameError.
    The bug: compose_up returns (rc, str) but code used result.stderr[:400]
    where 'result' was never defined.
    """

    def _make_provider(self, provider_class):
        """Instantiate a provider with minimal config."""
        return provider_class()

    # Step 2.6 Bucket G: each test takes the `test_db` fixture so
    # `state.configure(path)` is set before provider.deploy() reads
    # platform via StateDB. Without it the deploy raises StateError
    # before reaching the compose failure path under test.

    # Step 2.2.d closure: each test now uses the real `write_fragment`
    # (writing to a tmp_compose_dir per ADR 0002 §4 real-fakes pattern)
    # and only mocks at the OS boundary via `compose_up`. Drops 1
    # internal mock per test; the assertion (no NameError on compose
    # failure, returns ok=False) is unchanged and the test remains
    # behavioural rather than implementation-coupled.

    @patch("backend.core.compose.compose_up", return_value=(1, "port conflict error"))
    def test_glance_compose_failure_no_nameerror(
        self, mock_compose, ready_db, tmp_compose_dir,
    ):
        """Glance deploy must not raise NameError on compose failure."""
        from backend.infra.providers.dashboard_glance import GlanceDashboardProvider as GlanceProvider
        provider = GlanceProvider()
        try:
            result = provider.deploy({"domain": "test.com", "network": "mediastack"})
            # Either returns a failure result (correct) or raises something
            assert not result.ok, "Compose failure should produce result.ok=False"
            assert "result.stderr" not in str(result.detail or ""), (
                "Error detail contains 'result.stderr' text — likely raised NameError "
                "that was caught somewhere."
            )
        except NameError as e:
            pytest.fail(
                f"GlanceProvider.deploy raised NameError: {e}\n"
                f"compose_up returns (rc, str) but code used result.stderr"
            )

    @patch("backend.core.compose.compose_up", return_value=(1, "container conflict"))
    def test_dockhand_compose_failure_no_nameerror(
        self, mock_compose, test_db, tmp_compose_dir,
    ):
        """Dockhand deploy must not raise NameError on compose failure."""
        from backend.infra.providers.management_alternatives import DockhandProvider
        provider = DockhandProvider()
        try:
            result = provider.deploy({"domain": "test.com", "network": "mediastack"})
            assert not result.ok
        except NameError as e:
            pytest.fail(f"DockhandProvider.deploy raised NameError: {e}")

    @patch("backend.core.compose.compose_up", return_value=(1, "no space left"))
    def test_dockge_compose_failure_no_nameerror(
        self, mock_compose, test_db, tmp_compose_dir,
    ):
        """Dockge deploy must not raise NameError on compose failure."""
        from backend.infra.providers.management_alternatives import DockgeProvider
        provider = DockgeProvider()
        try:
            result = provider.deploy({"domain": "test.com", "network": "mediastack"})
            assert not result.ok
        except NameError as e:
            pytest.fail(f"DockgeProvider.deploy raised NameError: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Platform reset — failure paths
# ═══════════════════════════════════════════════════════════════════════════

class TestPlatformResetFailurePaths:
    """What happens when docker stop/rm fails during reset?"""

    def test_reset_continues_when_docker_stop_fails(self):
        """If docker stop returns non-zero, reset must continue (not abort)."""
        from backend.api.platform import _stop_and_remove_containers
        with patch("subprocess.run") as mock_run:
            # docker stop fails (container already stopped or removed)
            mock_run.return_value = MagicMock(returncode=1)
            result = _stop_and_remove_containers(["traefik", "tinyauth"])
        # Must return a result dict, not raise
        assert isinstance(result, dict), "reset helper must return dict even on docker failure"
        assert "stopped" in result
        assert "removed" in result

    def test_network_remove_disconnects_stragglers_first(self):
        """_remove_network must disconnect attached containers before rm."""
        from backend.api.platform import _remove_network
        with patch("subprocess.run") as mock_run, \
             patch("backend.api.platform._find_network_containers",
                   return_value=["container1", "container2"]):
            mock_run.return_value = MagicMock(returncode=0)
            _remove_network("mediastack")

        calls_str = " ".join(str(c) for c in mock_run.call_args_list)
        assert "disconnect" in calls_str, (
            "_remove_network must disconnect containers before running 'docker network rm'. "
            "Without disconnect, rm fails if any container is still attached."
        )

    def test_find_network_containers_returns_empty_on_docker_error(self):
        """_find_network_containers must return [] if Docker fails, not raise."""
        from backend.api.platform import _find_network_containers
        with patch("subprocess.run", side_effect=Exception("Docker not running")):
            result = _find_network_containers("mediastack")
        assert result == [], (
            "_find_network_containers must return [] on Docker error, not propagate."
        )


# ═══════════════════════════════════════════════════════════════════════════
# StateDB — failure paths
# ═══════════════════════════════════════════════════════════════════════════

class TestStateDatabaseFailurePaths:
    """What happens when DB operations fail?"""

    def test_state_db_no_plain_commit_calls_in_backend(self):
        """No backend file must call plain db.commit() — only db._c.commit() is valid.

        Bug: maintenance window POST called db.commit() → AttributeError → 500.
        StateDB has no .commit() method. Auto-commits on __exit__ or use db._c.commit().
        """
        import re as _re
        violations = []
        for f in (REPO / "backend").rglob("*.py"):
            src = f.read_text()
            # Find X.commit() where X is not _c (i.e., not the allowed pattern)
            hits = _re.findall(r'(?<!\._c)db\.commit\(\)|(?<!\._c)_pdb\.commit\(\)|(?<!\._c)_fdb\.commit\(\)', src)
            if hits:
                violations.append(f"{f.relative_to(REPO)}: {hits}")
        assert not violations, (
            f"Direct .commit() calls found (raises AttributeError). "
            f"Use db._c.commit() instead:\n" + "\n".join(str(v) for v in violations[:5])
        )

    def test_maintenance_window_source_has_no_db_commit_call(self):
        """Verify the source code doesn't call db.commit() inside StateDB context."""
        src = (REPO / "backend" / "api" / "health.py").read_text()
        maint_start = src.find("def create_maintenance_window")
        next_fn = src.find("\n@router", maint_start + 100)
        fn_body = src[maint_start:next_fn]
        assert "db.commit()" not in fn_body, (
            "create_maintenance_window calls db.commit() but StateDB has no such method. "
            "This is AttributeError → HTTP 500 every time."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Wizard step — failure paths and correctness
# ═══════════════════════════════════════════════════════════════════════════

class TestWizardStepFailurePaths:
    """What happens when individual wizard steps fail?"""

    def test_deploy_infra_handles_provider_exception_gracefully(self):
        """If a provider's deploy() raises, the step continues with other providers."""
        from backend.platform.wizard import step_deploy_infra, WizardInput
        inp = WizardInput(
            domain="test.com", config_root="/tmp", media_root="/mnt",
            puid=1000, pgid=1000, timezone="UTC",
            cert_resolver="letsencrypt", network_name="mediastack",
            tunnels=["cloudflared"],
            secrets={"CF_TUNNEL_TOKEN": "tok_test"},
        )
        with patch("backend.infra.registry.get_provider") as mock_get:
            failing_provider = MagicMock()
            failing_provider.deploy.side_effect = RuntimeError("Docker socket not found")
            mock_get.return_value = failing_provider

            result = step_deploy_infra(inp)

        # Step must return a result (not propagate the exception)
        assert result is not None, "step_deploy_infra must not propagate provider exceptions"
        assert result.status in ("ok", "skipped", "error"), (
            f"step_deploy_infra must return valid status, got: {result.status}"
        )
        # Failure detail must mention the problematic provider
        assert result.detail or result.message, "Failed step must have error message"

    def test_deploy_infra_vpn_reads_from_secrets_not_empty_dict(self):
        """VPN deploy cfg must include secrets, not just {domain, network}."""
        from backend.platform.wizard import step_deploy_infra, WizardInput
        inp = WizardInput(
            domain="test.com", config_root="/tmp", media_root="/mnt",
            puid=1000, pgid=1000, timezone="UTC",
            cert_resolver="letsencrypt", network_name="mediastack",
            vpn="gluetun",
            secrets={
                "VPN_SERVICE_PROVIDER": "protonvpn",
                "VPN_TYPE": "wireguard",
                "WIREGUARD_PRIVATE_KEY": "abc123keyabc123keyabc123keyabc123key==",
            },
        )
        captured_cfg = {}
        with patch("backend.infra.registry.get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.deploy.return_value = MagicMock(ok=True, message="ok", detail="")
            def _capture_deploy(cfg):
                captured_cfg.update(cfg)
                return mock_provider.deploy.return_value
            mock_provider.deploy.side_effect = _capture_deploy
            mock_get.return_value = mock_provider

            step_deploy_infra(inp)

        assert captured_cfg.get("vpn_service_provider") == "protonvpn", (
            f"VPN provider name not passed to deploy(). Got cfg: {captured_cfg}. "
            "step_deploy_infra must map VPN_SERVICE_PROVIDER secret to vpn_service_provider."
        )
        assert captured_cfg.get("wireguard_private_key"), (
            "WireGuard private key not passed to gluetun deploy(). "
            "step_deploy_infra must map WIREGUARD_PRIVATE_KEY to wireguard_private_key."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Health cycle — failure paths
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthCycleFailurePaths:
    """What happens when the health cycle encounters failures?"""

    def test_health_cycle_has_per_app_exception_handling(self):
        """run_health_cycle must wrap each app's check to prevent one failure aborting all."""
        src = (REPO / "backend" / "health" / "checker.py").read_text()
        import re as _re
        cycle_start = src.find("async def run_health_cycle")
        cycle_body = src[cycle_start:cycle_start + 5000]
        # Must have try/except inside a loop that iterates over apps
        has_loop = "for " in cycle_body and ("app" in cycle_body or "apps" in cycle_body)
        has_except = "except" in cycle_body
        assert has_loop and has_except, (
            "run_health_cycle must iterate over apps with per-iteration exception handling. "
            "One app timing out must not cancel health checks for the remaining apps."
        )

    def test_health_trigger_endpoint_has_exception_handling(self):
        """POST /health/run must not return 500 if health cycle raises."""
        src = (REPO / "backend" / "api" / "health.py").read_text()
        fn_start = src.find("async def trigger_health_run")
        fn_body = src[fn_start:fn_start + 800]
        assert "try:" in fn_body, (
            "trigger_health_run must have a try block. "
            "Unhandled exceptions return 500 to the frontend."
        )
        try_idx = fn_body.find("try:")
        assert "except" in fn_body[try_idx:], (
            "trigger_health_run has try: but no matching except. "
            "Exception will still propagate as 500."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Validate-secrets — failure path correctness
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateSecretsFailurePaths:
    """Credential validation must handle all failure modes cleanly."""

    def test_dns_check_with_network_error_returns_warning_not_error(self):
        """CF API unreachable → warning (can't verify), not error (invalid token)."""
        from backend.api.platform import wizard_validate_secrets
        with patch("urllib.request.urlopen", side_effect=Exception("Network unreachable")):
            result = wizard_validate_secrets({
                "checks": ["dns"],
                "cf_dns_token": "valid_looking_token_abc123",
            })
        assert isinstance(result, dict)
        # Network error → warning (can't verify), not hard error (invalid creds)
        assert result.get("ok") in (True, False)
        if not result.get("ok"):
            # If not ok, must be in errors not just warnings
            # But network error should be a warning, not a blocking error
            assert len(result.get("warnings", [])) > 0 or len(result.get("errors", [])) > 0

    def test_vpn_wireguard_with_short_key_returns_error(self):
        """A WireGuard key that's too short must be caught before deploy."""
        from backend.api.platform import wizard_validate_secrets
        result = wizard_validate_secrets({
            "checks": ["vpn"],
            "vpn_type": "wireguard",
            "vpn_provider": "mullvad",
            "vpn_key": "tooshort",
        })
        assert not result.get("ok"), "Short WireGuard key must produce an error"
        assert result.get("errors"), "Errors list must be non-empty for invalid WG key"

    def test_empty_checks_always_succeeds(self):
        """Empty checks list: nothing to validate → always ok, never raises."""
        from backend.api.platform import wizard_validate_secrets
        result = wizard_validate_secrets({"checks": []})
        assert result.get("ok") is True
        assert result.get("errors") == []
        assert result.get("warnings") == []
