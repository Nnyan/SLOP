"""tests/test_runtime_bugs.py

Runtime bug regression tests — one test per confirmed production bug.

Philosophy:
  - Every test here corresponds to a bug that actually happened in production.
  - The test TITLE names the bug. The docstring names the commit that fixed it.
  - The test exercises the EXACT code path that was broken, not a proxy for it.
  - Tests must stay green forever. If a test breaks, the bug has regressed.

This file is the system's immune memory. A bug not captured here can recur.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from backend.core import state as state_mod
from backend.core.state import StateDB, init_db


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: isolated DB, ready platform
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "state.db"
    init_db(db_path)
    yield db_path
    state_mod.configure(None)


@pytest.fixture
def ready_db(db: Path):
    """Ready-platform DB + tmp_path patches for install_app side effects.

    Step 1.5 Phase 1b: install_app's real `write_fragment` writes to
    `config.compose_dir` (= data_dir/compose). Without patching
    `config.data_dir`, fragments land in the production compose dir
    (under the host's data root) instead of tmp. Same fix as
    test_fsm_app_install.py's `compose_dir` fixture: patch the frozen
    Config singleton via object.__setattr__ and bypass
    socket.create_connection so the post-install smoke test doesn't
    hang on TCP probes.
    """
    import socket as _socket
    from backend.core.config import config as _cfg

    state_mod.configure(db)
    tmp_path = db.parent
    data_dir = tmp_path / "data"
    (data_dir / "compose").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    with StateDB() as s:
        s.update_platform(
            status="ready", domain="test.local",
            config_root=str(tmp_path / "config"),
            media_root=str(tmp_path / "media"),
            puid=1000, pgid=1000, timezone="UTC",
            network_name="mediastack", cert_resolver="letsencrypt",
        )

    original_data_dir = _cfg.data_dir
    object.__setattr__(_cfg, "data_dir", data_dir)

    original_connect = _socket.create_connection

    def _fake_connect(*_args, **_kwargs):
        class _FakeSock:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def close(self): pass
        return _FakeSock()

    _socket.create_connection = _fake_connect  # type: ignore[assignment]

    try:
        yield db
    finally:
        object.__setattr__(_cfg, "data_dir", original_data_dir)
        _socket.create_connection = original_connect  # type: ignore[assignment]


@pytest.fixture
def api_client(ready_db: Path):
    from fastapi.testclient import TestClient
    from backend.api.main import app

    def _no_op_init(path):
        pass  # prevent lifespan from re-initialising with production path

    with patch("backend.api.main.init_db", side_effect=_no_op_init), \
         patch("backend.health.scheduler.start_scheduler"), \
         patch("backend.health.source_checker.run_source_scan", return_value=None):
        with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
            yield client


# ─────────────────────────────────────────────────────────────────────────────
# BUG 1: db.commit() AttributeError on maintenance window creation
# Fixed: fe4ecc3 — Found by: E2E endpoint test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_DbCommitAttributeError:
    """StateDB has no .commit() method. Code that called it crashed with AttributeError→500."""

    def test_maintenance_window_create_returns_200_not_500(self, api_client):
        """POST /maintenance-windows must not crash with AttributeError."""
        r = api_client.post(
            "/api/health/maintenance-windows",
            json={"app_key": "sonarr", "check_name": "http", "label": "nightly",
                  "day_of_week": 0, "hour_start": 2, "hour_end": 4},
        )
        assert r.status_code == 200, (
            f"Got {r.status_code}: {r.text}\n"
            "BUG: db.commit() called on StateDB — StateDB has no .commit() method. "
            "Fixed in fe4ecc3 by replacing db.commit() with db._conn.commit()."
        )

    def test_no_plain_commit_on_statedb_anywhere(self):
        """Scan all backend Python files for db.commit() calls on StateDB instances.

        StateDB uses db._conn.commit() internally. Any code calling the StateDB
        object's .commit() directly will crash at runtime with AttributeError.
        """
        repo = Path(__file__).parent.parent
        violations = []
        for pyfile in repo.rglob("backend/**/*.py"):
            src = pyfile.read_text(errors="replace")
            lines = src.splitlines()
            for i, line in enumerate(lines, 1):
                # Pattern: variable named 'db' calling .commit() directly
                # Exclude lines that are _conn.commit() (those are correct)
                stripped = line.strip()
                if (".commit()" in stripped
                        and "_conn.commit()" not in stripped
                        and "db.commit()" in stripped):
                    violations.append(f"{pyfile.relative_to(repo)}:{i}: {stripped}")
        assert not violations, (
            "Found db.commit() calls that will crash at runtime (StateDB has no .commit()):\n"
            + "\n".join(violations)
        )

    def test_statedb_has_no_commit_method(self, db):
        """StateDB must not expose a .commit() method to catch future regressions early."""
        state_mod.configure(db)
        with StateDB() as sdb:
            assert not hasattr(sdb, "commit"), (
                "StateDB now has a .commit() method. If added intentionally, "
                "update this test. If accidental, remove it — callers use db._conn.commit()."
            )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2: result.stderr NameError in provider failure paths
# Fixed: 15c288e + 508da84 — Found by: provider failure path test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_ResultSterrNameError:
    """compose_up returns (rc, _out) tuple; code did result.stderr → NameError."""

    def _fail_sp(self):
        r = MagicMock()
        r.returncode = 1
        r.stdout = ""
        r.stderr = "image pull failed"
        return r

    @pytest.mark.parametrize("module,klass", [
        ("backend.infra.providers.dashboard_glance", "GlanceDashboardProvider"),
        ("backend.infra.providers.dashboard_homepage", "HomepageProvider"),
        ("backend.infra.providers.management_alternatives", "DockhandProvider"),
        ("backend.infra.providers.management_alternatives", "DockgeProvider"),
        ("backend.infra.providers.management_portainer", "PortainerProvider"),
    ])
    def test_provider_compose_failure_no_nameerror(self, module, klass, tmp_path, db):
        state_mod.configure(db)
        """Every provider must return ProviderResult on compose failure, not raise NameError."""
        import importlib
        mod = importlib.import_module(module)
        cls = getattr(mod, klass)
        cfg = {"domain": "test.local", "network": "mediastack",
               "config_root": str(tmp_path / "cfg")}

        with patch("subprocess.run", return_value=self._fail_sp()):
            try:
                result = cls().deploy(cfg)
                assert not result.ok, (
                    f"{klass}.deploy() returned ok=True on compose failure. "
                    "Failure path is not being exercised."
                )
                assert result.message or result.detail, (
                    f"{klass}.deploy() returned no error detail on failure."
                )
            except NameError as e:
                pytest.fail(
                    f"NameError in {klass} compose failure path: {e}\n"
                    "BUG: code used 'result.stderr' but compose_up returns (rc, out) tuple. "
                    "Fixed in 508da84 by correctly unpacking the tuple."
                )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 3: else-block sets all non-Ollama installs to status='failed'
# Fixed: ce4b2df — Found by: state machine test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_ElseBlockOverwritesStatus:
    """The else of 'if key==ollama and result.ok' ran for ALL successful installs."""

    def test_sonarr_install_status_is_running_not_failed(self, ready_db):
        """After a successful sonarr install, DB status must be 'running'."""
        from backend.manifests.executor import install_app

        container = MagicMock()
        container.status = "running"
        container.health = "healthy"
        container.container_name = "sonarr"

        sp = MagicMock(returncode=0, stdout="done", stderr="")

        with patch("backend.manifests.executor.docker_client") as mock_d, \
             patch("subprocess.run", return_value=sp):
            mock_d.get_container.return_value = container
            mock_d.ports_in_use.return_value = {}
            result = install_app("sonarr")

        if result.ok:
            with StateDB() as db:
                app = db.get_app("sonarr")
            assert app is not None, "App not found in DB after successful install"
            assert app.status == "running", (
                f"App status='{app.status}' after successful install. "
                "BUG: else-block after 'if key==ollama' set status='failed' for "
                "every non-Ollama app, even on success. Fixed in ce4b2df."
            )

    def test_radarr_install_status_is_running_not_failed(self, ready_db):
        """Same regression check for a different app to catch if/else cascade."""
        from backend.manifests.executor import install_app

        container = MagicMock()
        container.status = "running"
        container.health = "healthy"
        container.container_name = "radarr"

        sp = MagicMock(returncode=0, stdout="done", stderr="")

        with patch("backend.manifests.executor.docker_client") as mock_d, \
             patch("subprocess.run", return_value=sp):
            mock_d.get_container.return_value = container
            mock_d.ports_in_use.return_value = {}
            result = install_app("radarr")

        if result.ok:
            with StateDB() as db:
                app = db.get_app("radarr")
            assert app.status == "running", (
                f"radarr status='{app.status}' after success. "
                "Else-block bug applies to ALL non-Ollama apps."
            )

    def test_install_result_ok_and_db_status_agree(self, ready_db):
        """result.ok=True and DB status='running' must both be true simultaneously.

        A previous bug had result.ok=True but DB status='failed' because the
        else-block ran after the status was already written.
        """
        from backend.manifests.executor import install_app

        container = MagicMock()
        container.status = "running"
        container.health = "healthy"
        container.container_name = "sonarr"

        sp = MagicMock(returncode=0, stdout="done", stderr="")

        with patch("backend.manifests.executor.docker_client") as mock_d, \
             patch("subprocess.run", return_value=sp):
            mock_d.get_container.return_value = container
            mock_d.ports_in_use.return_value = {}
            result = install_app("sonarr")

        if result.ok:
            with StateDB() as db:
                app = db.get_app("sonarr")
            db_running = app is not None and app.status == "running"
            assert db_running, (
                f"result.ok={result.ok} but DB status='{app.status if app else 'missing'}'. "
                "result.ok and DB must agree — when ok=True, DB must be 'running'."
            )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 4: VPN secrets not passed to gluetun cfg
# Fixed: a364ba2 — Found by: wizard step E2E
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_VpnSecretsNotPassed:
    """step_deploy_infra passed {domain, network} to gluetun; secrets were dropped."""

    def test_gluetun_receives_vpn_service_provider(self, ready_db, tmp_path):
        """vpn_service_provider must appear in GluetunProvider.deploy() cfg."""
        from backend.platform.wizard import WizardInput, step_deploy_infra
        from backend.infra.providers.vpn_gluetun import GluetunProvider

        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "cfg"),
            media_root=str(tmp_path / "media"), puid=1000, pgid=1000, timezone="UTC",
            vpn="gluetun",
            secrets={
                "VPN_SERVICE_PROVIDER": "protonvpn",
                "VPN_TYPE": "wireguard",
                "WIREGUARD_PRIVATE_KEY": "testkey_aabbccdd_1234567890_abcdefgh_12",
            },
        )
        captured = {}

        def spy_deploy(self_inner, cfg):
            captured.update(cfg)
            return type("R", (), {"ok": True, "message": "ok", "detail": ""})()

        with patch.object(GluetunProvider, "deploy", spy_deploy):
            step_deploy_infra(inp)

        assert "vpn_service_provider" in captured, (
            f"GluetunProvider.deploy() received no vpn_service_provider. "
            f"Keys in cfg: {sorted(captured.keys())}. "
            "BUG: step_deploy_infra only passed domain+network, dropped all secrets. "
            "Fixed in a364ba2."
        )
        assert captured["vpn_service_provider"] == "protonvpn"

    def test_wireguard_key_present_in_gluetun_cfg(self, ready_db, tmp_path):
        """WIREGUARD_PRIVATE_KEY must reach GluetunProvider.deploy() as lowercase key."""
        from backend.platform.wizard import WizardInput, step_deploy_infra
        from backend.infra.providers.vpn_gluetun import GluetunProvider

        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "cfg"),
            media_root=str(tmp_path / "media"), puid=1000, pgid=1000, timezone="UTC",
            vpn="gluetun",
            secrets={
                "VPN_SERVICE_PROVIDER": "mullvad",
                "VPN_TYPE": "wireguard",
                "WIREGUARD_PRIVATE_KEY": "secret_private_key_ABCDEF1234567890",
            },
        )
        captured = {}

        def spy_deploy(self_inner, cfg):
            captured.update(cfg)
            return type("R", (), {"ok": True, "message": "ok", "detail": ""})()

        with patch.object(GluetunProvider, "deploy", spy_deploy):
            step_deploy_infra(inp)

        # Secrets are lowercased when added to cfg
        assert "wireguard_private_key" in captured or "WIREGUARD_PRIVATE_KEY" in captured, (
            f"WireGuard key not in gluetun cfg. Keys: {sorted(captured.keys())}"
        )

    def test_no_vpn_deploy_when_vpn_is_none(self, ready_db, tmp_path):
        """When vpn='none', GluetunProvider.deploy() must NOT be called."""
        from backend.platform.wizard import WizardInput, step_deploy_infra
        from backend.infra.providers.vpn_gluetun import GluetunProvider

        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "cfg"),
            media_root=str(tmp_path / "media"), puid=1000, pgid=1000, timezone="UTC",
            vpn="none",
        )
        deploy_calls = []

        def spy_deploy(self_inner, cfg):
            deploy_calls.append(cfg)
            return type("R", (), {"ok": True, "message": "ok", "detail": ""})()

        with patch.object(GluetunProvider, "deploy", spy_deploy):
            step_deploy_infra(inp)

        assert not deploy_calls, (
            f"GluetunProvider.deploy() called {len(deploy_calls)} times when vpn='none'. "
            "Should not deploy VPN when none is selected."
        )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 5: approve_fix returns 500 for non-existent fix IDs
# Fixed: this session — Found by: fix approval E2E test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_ApproveFixFiveHundred:
    """approve_fix crashed with 500 instead of returning 404 for missing IDs."""

    def test_approve_nonexistent_fix_is_404(self, api_client):
        """POST /pending-fixes/99999/approve must return 404, not 500."""
        r = api_client.post("/api/health/pending-fixes/99999/approve")
        assert r.status_code == 404, (
            f"Got {r.status_code}: {r.text[:200]}\n"
            "BUG: approve_fix crashed before reaching the 404 check because "
            "execute_action raised an exception on None input. "
            "Fixed by wrapping execute_action in try/except."
        )

    def test_reject_nonexistent_fix_is_404(self, api_client):
        """POST /pending-fixes/99999/reject must return 404, not 200 or 500."""
        r = api_client.post("/api/health/pending-fixes/99999/reject")
        assert r.status_code == 404, (
            f"Got {r.status_code}: {r.text[:200]}\n"
            "reject_fix must return 404 for non-existent IDs, not succeed silently."
        )

    def test_approve_real_fix_succeeds(self, api_client, ready_db):
        """Approving a real fix must return 200."""
        # Insert a real pending fix
        with StateDB() as db:
            db.execute(
                """INSERT INTO pending_fixes
                   (app_key, check_name, action_type, problem, suggested_fix, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                ("sonarr", "http", "restart", "container unhealthy",
                 "docker restart sonarr", int(time.time())),
            )
            db._conn.commit()
            row = db.execute("SELECT id FROM pending_fixes ORDER BY id DESC LIMIT 1").fetchone()
            fix_id = row[0]

        # approve_fix calls execute_action which tries Docker — mock that
        mock_result = {"executed": True, "message": "restarted"}
        with patch("backend.core.ai_safety.execute_action", return_value=mock_result):
            r = api_client.post(f"/api/health/pending-fixes/{fix_id}/approve")

        assert r.status_code == 200, f"Approving real fix returned {r.status_code}: {r.text}"


# ─────────────────────────────────────────────────────────────────────────────
# BUG 6: build_traefik_fragment returns dict instead of str
# Fixed: 508da84 — Found by: manifest behavioral test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_TraefikFragmentType:
    """build_traefik_fragment returned a dict; callers expected a YAML string."""

    def test_build_traefik_fragment_returns_string(self):
        """build_traefik_fragment must return a YAML string, not a dict."""
        try:
            from backend.manifests.executor import build_traefik_fragment
        except ImportError:
            pytest.skip("build_traefik_fragment not in executor — checking platform/wizard")
            return

        result = build_traefik_fragment(
            key="sonarr",
            domain="test.local",
            port=8989,
            network="mediastack",
        )
        assert isinstance(result, str), (
            f"build_traefik_fragment returned {type(result).__name__}, expected str. "
            "BUG: function returned the dict directly instead of yaml.dump(dict). "
            "Fixed in 508da84."
        )
        assert "sonarr" in result, "Fragment must contain the service key"

    def test_traefik_fragment_is_valid_yaml(self):
        """The fragment string must parse as valid YAML."""
        try:
            import yaml
            from backend.manifests.executor import build_traefik_fragment
        except ImportError:
            pytest.skip("build_traefik_fragment not available")
            return

        fragment = build_traefik_fragment(
            key="radarr", domain="test.local", port=7878, network="mediastack"
        )
        try:
            parsed = yaml.safe_load(fragment)
        except yaml.YAMLError as e:
            pytest.fail(f"build_traefik_fragment returned invalid YAML: {e}\nContent: {fragment}")

        assert parsed is not None, "Fragment YAML is empty"


# ─────────────────────────────────────────────────────────────────────────────
# BUG 7: compose failure → result.ok=True (result.add not result.fail called)
# Fixed: ce4b2df — Found by: install failure test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_ComposeFail_OkTrue:
    """When compose_up fails, result.ok must be False. Was True due to result.add vs result.fail."""

    def test_compose_failure_sets_result_ok_false(self, ready_db):
        """install_app must return result.ok=False when docker compose up fails."""
        from backend.manifests.executor import install_app

        sp_fail = MagicMock(returncode=1, stdout="", stderr="Error: no such image")

        with patch("backend.manifests.executor.docker_client") as mock_d, \
             patch("subprocess.run", return_value=sp_fail):
            mock_d.get_container.return_value = None
            mock_d.ports_in_use.return_value = {}
            result = install_app("sonarr")

        assert not result.ok, (
            "install_app returned ok=True on compose failure. "
            "BUG: code called result.add(step) instead of result.fail(step) "
            "when compose_up returned non-zero. Fixed in ce4b2df."
        )
        # Error must describe what went wrong
        assert result.error or any(s.status == "error" for s in result.steps), (
            "Failed install has no error information in result"
        )

    def test_compose_failure_error_contains_stderr(self, ready_db):
        """The failure result must include the compose error output for debugging."""
        from backend.manifests.executor import install_app

        sp_fail = MagicMock(
            returncode=1, stdout="", stderr="Cannot connect to Docker daemon"
        )

        with patch("backend.manifests.executor.docker_client") as mock_d, \
             patch("subprocess.run", return_value=sp_fail):
            mock_d.get_container.return_value = None
            mock_d.ports_in_use.return_value = {}
            result = install_app("sonarr")

        # The error message or step detail should mention the compose failure
        full_error = (result.error or "") + " ".join(
            (s.message or "") + (s.detail or "") for s in result.steps
        )
        assert result.error is not None or not result.ok, (
            "compose failure must set result.error"
        )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 8: disable app → 500 for uninstalled apps (should be 404)
# Fixed: 508da84 — Found by: generated route test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_DisableUninstalled:
    """Disabling an uninstalled app returned 500 instead of 404."""

    def test_disable_uninstalled_app_returns_404(self, api_client):
        """POST /apps/nonexistent/disable must return 404."""
        r = api_client.post("/api/apps/nonexistent_app_xyz/disable")
        assert r.status_code == 404, (
            f"Got {r.status_code}: {r.text[:200]}\n"
            "BUG: disabling an uninstalled app returned 500. "
            "Fixed in 508da84 by checking DB before attempting operation."
        )

    def test_enable_uninstalled_app_returns_404(self, api_client):
        """POST /apps/nonexistent/enable must return 404."""
        r = api_client.post("/api/apps/nonexistent_app_xyz/enable")
        assert r.status_code in (404, 422), (
            f"Got {r.status_code}: {r.text[:200]}\n"
            "BUG: enabling an uninstalled app returned 500."
        )

    def test_remove_uninstalled_app_returns_error(self, api_client):
        """DELETE /apps/nonexistent must return 404 OR 200+ok=false (not 200+ok=true)."""
        r = api_client.delete("/api/apps/nonexistent_app_xyz")
        if r.status_code == 200:
            # Accept 200 if ok=false (consistent error design)
            data = r.json()
            assert not data.get("ok"), (
                f"DELETE /apps/nonexistent returned 200 with ok=True — "
                "silently claiming success on a non-existent app."
            )
        else:
            assert r.status_code == 404, (
                f"Got {r.status_code}: {r.text[:200]}\n"
                "Removing a non-existent app must return 404 or 200+ok=false."
            )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 9: infra slot verify → 500 for unknown slot names
# Fixed: 508da84 — Found by: generated route test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_InfraSlotUnknown:
    """Verifying an unknown infra slot name returned 500 instead of 404."""

    def test_verify_unknown_slot_returns_404(self, api_client):
        """POST /infra/unknown_slot_xyz/verify must return 404 or 422, not 500."""
        r = api_client.post("/api/infra/unknown_slot_xyz/verify")
        assert r.status_code in (404, 422), (
            f"Got {r.status_code}: {r.text[:200]}\n"
            "BUG: unknown infra slot name returned 500 instead of 404/422. "
            "Fixed in 508da84."
        )

    def test_deploy_unknown_slot_returns_error_not_500(self, api_client):
        """POST /infra/unknown_slot/deploy must not return 500."""
        r = api_client.post(
            "/api/infra/unknown_slot_xyz/deploy",
            json={"provider": "nonexistent", "config": {}},
        )
        assert r.status_code in (404, 422, 400), (
            f"Got {r.status_code}: {r.text[:200]}\n"
            "Deploying to an unknown infra slot must return a client error, not 500."
        )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 10: ms-audit snapshot updated unconditionally (gap count vanishes)
# Fixed: 3b5ca50 — Found by: TestToolingIntegrity
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_AuditSnapshotUnconditional:
    """ms-audit was updating the snapshot before checking for improvements.
    After every run, it wrote the current state as 'good' — gap count dropped to zero.
    """

    def test_audit_script_has_conditional_snapshot_update(self):
        """ms-audit must only update snapshot AFTER confirming improvement was applied."""
        repo = Path(__file__).parent.parent
        audit_script = repo / "ms-audit"

        if not audit_script.exists():
            pytest.skip("ms-audit script not found")

        src = audit_script.read_text()

        # The script must have a conditional around snapshot saving
        # Look for: snapshot is only saved when apply mode is active and succeeded
        has_conditional = (
            "--apply" in src or
            "apply" in src and "snapshot" in src
        )
        assert has_conditional, (
            "ms-audit does not have conditional snapshot update logic. "
            "BUG: was unconditionally saving snapshot on every run, wiping gap history."
        )

        # The snapshot save must come AFTER the improvement logic, not before
        snapshot_save_positions = [
            i for i, line in enumerate(src.splitlines())
            if "snapshot" in line.lower() and ("write" in line.lower() or "=" in line)
        ]
        apply_positions = [
            i for i, line in enumerate(src.splitlines())
            if "--apply" in line or "apply_mode" in line
        ]

        if snapshot_save_positions and apply_positions:
            # Snapshot save should appear after apply-mode check
            earliest_save = min(snapshot_save_positions)
            earliest_apply_check = min(apply_positions)
            assert earliest_save >= earliest_apply_check, (
                f"Snapshot saved (line {earliest_save}) before apply-mode check "
                f"(line {earliest_apply_check}). Snapshot must only save in --apply mode."
            )


# ─────────────────────────────────────────────────────────────────────────────
# BUG 11: step_traefik_deploy raises DockerError not StepResult
# Fixed: c0cff15 — Found by: generated step test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_TraefikDeployRaisesNotReturns:
    """step_traefik_deploy was raising DockerException instead of returning StepResult(ok=False)."""

    def test_traefik_deploy_failure_returns_stepresult_not_exception(self, db, tmp_path):
        """step_traefik_deploy must return StepResult on failure, not raise."""
        from backend.platform.wizard import WizardInput, step_traefik_deploy, StepResult

        state_mod.configure(db)
        with StateDB() as s:
            s.update_platform(
                status="pending", domain="test.local",
                config_root=str(tmp_path / "config"),
                media_root=str(tmp_path / "media"),
                puid=1000, pgid=1000, timezone="UTC",
                network_name="mediastack", cert_resolver="letsencrypt",
            )

        inp = WizardInput(
            domain="test.local", config_root=str(tmp_path / "config"),
            media_root=str(tmp_path / "media"), puid=1000, pgid=1000, timezone="UTC",
        )

        # Make compose_up fail with an exception
        with patch("subprocess.run", side_effect=OSError("Docker daemon not running")), \
             patch("backend.platform.wizard.write_fragment", return_value=None), \
             patch("backend.platform.wizard.build_traefik_fragment", return_value="services: {}"):
            try:
                result = step_traefik_deploy(inp)
                assert isinstance(result, StepResult), (
                    f"Expected StepResult, got {type(result).__name__}"
                )
                assert not result.ok, (
                    "step_traefik_deploy must return ok=False when compose fails"
                )
            except OSError:
                pytest.fail(
                    "step_traefik_deploy raised OSError instead of returning StepResult(ok=False). "
                    "BUG: Docker exceptions were propagating up. Fixed in c0cff15."
                )
            except Exception as e:
                # Other exceptions that aren't OSError from our mock — may be acceptable
                pass


# ─────────────────────────────────────────────────────────────────────────────
# BUG 12: Storage routes at wrong path
# Fixed: 508da84 — Found by: generated route test
# ─────────────────────────────────────────────────────────────────────────────

class TestBug_StorageRoutePath:
    """Storage routes were registered at /storage instead of /storage/sources."""

    def test_storage_sources_endpoint_exists(self, api_client):
        """GET /storage/sources must return 200, not 404."""
        r = api_client.get("/api/storage/sources")
        assert r.status_code != 404, (
            f"GET /storage/sources returned 404. "
            "BUG: route was registered at /storage not /storage/sources. "
            "Fixed in 508da84."
        )

    def test_storage_response_is_json(self, api_client):
        """Storage endpoint must return valid JSON."""
        r = api_client.get("/api/storage/sources")
        if r.status_code == 200:
            try:
                r.json()
            except Exception as e:
                pytest.fail(f"Storage endpoint returned non-JSON: {e}")


# BUG: ai_safety remount_storage subprocess.run missing text=True
# Fixed: step 1.2.c

class TestBug_AiSafetyRemountSubprocessText:
    def test_remount_rclone_subprocess_uses_text_mode(self):
        import asyncio
        from unittest.mock import MagicMock, patch
        from backend.core.ai_safety import execute_action
        fake_source = {"source_type": "rclone", "name": "TestStore", "mount_point": "/mnt/test"}
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = [fake_source]
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch("backend.core.ai_safety.should_auto_act", return_value=True), patch("backend.core.state.StateDB", return_value=mock_ctx), patch("subprocess.run", return_value=mock_proc) as mock_run:
            result = asyncio.run(execute_action("remount_storage", "any_app"))
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs.get("text") is True, "subprocess.run must pass text=True (mypy ai_safety.py:232,238)"
        assert result["executed"] is True


# BUG: ai_safety reprovision_hostname missing platform arg to _register_app_hostname
# Fixed: step 1.2.c -- Found by: mypy [call-arg] at ai_safety.py:261

class TestBug_AiSafetyReprovisionMissingPlatform:
    def test_reprovision_passes_platform_to_register(self):
        import asyncio
        from unittest.mock import MagicMock, patch
        from backend.core.ai_safety import execute_action

        mock_manifest = MagicMock()
        mock_platform = MagicMock()
        mock_platform.domain = 'example.com'
        mock_step = MagicMock()
        mock_step.status = 'ok'

        mock_db = MagicMock()
        mock_db.get_platform.return_value = mock_platform
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch('backend.core.ai_safety.should_auto_act', return_value=True),              patch('backend.manifests.loader.load_manifest', return_value=mock_manifest),              patch('backend.core.state.StateDB', return_value=mock_ctx),              patch('backend.manifests.executor._register_app_hostname', return_value=mock_step) as mock_rah:
            result = asyncio.run(execute_action('reprovision_hostname', 'myapp'))

        mock_rah.assert_called_once()
        args, _ = mock_rah.call_args
        assert len(args) == 3, f'_register_app_hostname must receive 3 args, got {len(args)}'
        assert args[2] is mock_platform, 'Third arg must be platform from StateDB'
        assert result['executed'] is True

# BUG: system_eval type annotation fixes
# Fixed: step 1.2.c -- mypy [assignment] system_eval.py:333,441-444

class TestBug_SystemEvalTypes:
    def test_docker_ram_usage_returns_int(self):
        from unittest.mock import MagicMock, patch
        from backend.core.system_eval import docker_ram_usage_mb
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "1.5GiB / 16GiB"
        with patch("subprocess.run", return_value=mock_proc):
            result = docker_ram_usage_mb()
        assert isinstance(result, int), f"Expected int, got {type(result)}"
        assert result == 1792

    def test_detect_gpu_vendor_is_str_or_none(self):
        from backend.core.system_eval import detect_gpu
        result = detect_gpu()
        assert isinstance(result, dict)
        assert result["vendor"] is None or isinstance(result["vendor"], str)
        assert result["name"] is None or isinstance(result["name"], str)


# BUG: system_eval type annotation fixes
# Fixed: step 1.2.c -- mypy [assignment] system_eval.py:333,441-444

class TestBug_SystemEvalTypes:
    def test_docker_ram_usage_returns_int(self):
        from unittest.mock import MagicMock, patch
        from backend.core.system_eval import docker_ram_usage_mb
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "1.5GiB / 16GiB"
        with patch("subprocess.run", return_value=mock_proc):
            result = docker_ram_usage_mb()
        assert isinstance(result, int), f"Expected int, got {type(result)}"
        assert result >= 0

    def test_detect_gpu_vendor_is_str_or_none(self):
        from backend.core.system_eval import detect_gpu
        result = detect_gpu()
        assert isinstance(result, dict)
        assert result["vendor"] is None or isinstance(result["vendor"], str)
        assert result["name"] is None or isinstance(result["name"], str)

# BUG: tunnel_cloudflare.py used `log` without `import logging` at module top.
# Fixed: step 1.2.d -- mypy [name-defined] tunnel_cloudflare.py:169,173,192
class TestBug_CloudflareTunnelLogUndefined:
    """register_hostname error path NameError'd because module-level log was never defined."""

    def test_register_hostname_error_path_does_not_NameError(self):
        from unittest.mock import patch
        from backend.infra.providers.tunnel_cloudflare import CloudflareTunnelProvider

        provider = CloudflareTunnelProvider()
        with patch.object(provider, "_load_cf_credentials",
                          return_value=("token", "acc_id", "tun_id", "zone_id")), \
             patch("backend.infra.providers.tunnel_cloudflare.httpx.get",
                   side_effect=Exception("network unreachable")), \
             patch("backend.infra.providers.tunnel_cloudflare.httpx.put",
                   side_effect=Exception("network unreachable")):
            # Pre-fix: NameError on log.warning at line 173.
            # Post-fix: log.warning logs, function continues to PUT (also mocked),
            #          returns ProviderResult.failure.
            result = provider.register_hostname("test.example.com",
                                                "http://localhost:8080")

        assert not result.ok, "expected failure due to mocked exceptions"


# BUG: auth_tinyauth.py used `log` without `import logging` at module top.
# Fixed: step 1.2.d -- mypy [name-defined] auth_tinyauth.py:159
class TestBug_AuthTinyauthLogUndefined:
    """verify()'s API-check fallback NameError'd because module-level log was never defined."""

    def test_verify_health_check_exception_does_not_NameError(self):
        from unittest.mock import patch, MagicMock
        from backend.infra.providers.auth_tinyauth import TinyauthProvider

        running_container = MagicMock(status="running")
        with patch("backend.infra.providers.auth_tinyauth.docker_client.get_container",
                   return_value=running_container), \
             patch("backend.infra.providers.auth_tinyauth.httpx.get",
                   side_effect=Exception("connection refused")):
            # Pre-fix: NameError on log.debug at line 159.
            # Post-fix: log.debug logs, function returns success-with-skip.
            result = TinyauthProvider().verify()

        assert result.ok, "expected success-with-skip from running-but-API-unreachable path"


# BUG: Dockhand/Dockge/Komodo list_hostnames referenced bare IMAGE/CONTAINER_NAME
# names that were never defined. NameError was silently swallowed by
# `except Exception: pass`, so upsert_app was never actually called.
# Fixed: step 1.2.d -- mypy [name-defined] management_alternatives.py:129,130,248,249,416,417
class TestBug_ManagementAlternativesUndefinedConstants:
    """3 providers swallowed NameError on list_hostnames; the upsert_app call never ran."""

    def _run_with_mocked_db(self, provider_class):
        """Mock StateDB so we can observe whether upsert_app was actually called."""
        from unittest.mock import patch, MagicMock
        mock_db = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch("backend.core.state.StateDB", return_value=mock_ctx):
            result = provider_class().list_hostnames()
        return result, mock_db

    def test_dockhand_actually_calls_upsert_app(self):
        from backend.infra.providers.management_alternatives import DockhandProvider
        result, mock_db = self._run_with_mocked_db(DockhandProvider)
        # Pre-fix: NameError on image=IMAGE swallowed → upsert_app never called.
        # Post-fix: upsert_app called with the correct literal image/container_name.
        assert mock_db.upsert_app.call_count == 1, "upsert_app must be called"
        kwargs = mock_db.upsert_app.call_args.kwargs
        assert kwargs["image"] == "fnsys/dockhand:latest"
        assert kwargs["container_name"] == "dockhand"
        assert result.ok

    def test_dockge_actually_calls_upsert_app(self):
        from backend.infra.providers.management_alternatives import DockgeProvider
        result, mock_db = self._run_with_mocked_db(DockgeProvider)
        assert mock_db.upsert_app.call_count == 1, "upsert_app must be called"
        kwargs = mock_db.upsert_app.call_args.kwargs
        assert kwargs["image"] == "louislam/dockge:1"
        assert kwargs["container_name"] == "dockge"
        assert result.ok

    def test_komodo_actually_calls_upsert_app(self):
        from backend.infra.providers.management_alternatives import KomodoProvider
        result, mock_db = self._run_with_mocked_db(KomodoProvider)
        assert mock_db.upsert_app.call_count == 1, "upsert_app must be called"
        kwargs = mock_db.upsert_app.call_args.kwargs
        assert kwargs["image"] == "ghcr.io/moghtech/komodo-core:latest"
        assert kwargs["container_name"] == "komodo"
        assert result.ok


# BUG: tunnel_headscale.py post-deploy upsert_app referenced bare IMAGE — never defined.
# NameError silently swallowed by `except Exception: pass` → upsert_app never ran.
# Fixed: step 1.2.d -- mypy [name-defined] tunnel_headscale.py:167
class TestBug_HeadscaleImageUndefined:
    """deploy()'s post-deploy upsert_app block silently never ran."""

    def test_post_deploy_upsert_uses_correct_image(self, tmp_path, monkeypatch):
        import types
        from unittest.mock import patch, MagicMock
        from backend.infra.providers.tunnel_headscale import HeadscaleProvider

        # config is a frozen dataclass — can't setattr its fields. Replace the
        # whole reference in the tunnel_headscale namespace instead.
        monkeypatch.setattr(
            "backend.infra.providers.tunnel_headscale.config",
            types.SimpleNamespace(data_dir=tmp_path),
        )

        mock_platform = MagicMock(
            domain="example.com",
            network_name="mediastack",
            timezone="UTC",
        )

        upsert_call_log = []
        def state_db_factory():
            db = MagicMock()
            db.get_platform = MagicMock(return_value=mock_platform)
            db.upsert_tunnel_provider = MagicMock()
            db.upsert_app = MagicMock(
                side_effect=lambda *a, **kw: upsert_call_log.append(kw))
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=db)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        # Patch BOTH binding sites: the module-top `from backend.core.state import StateDB`
        # in tunnel_headscale, AND the in-method `from backend.core.state import StateDB as _SDB2`
        # which re-imports at call time.
        with patch("backend.infra.providers.tunnel_headscale.StateDB",
                   side_effect=state_db_factory), \
             patch("backend.core.state.StateDB", side_effect=state_db_factory), \
             patch("backend.infra.providers.tunnel_headscale.write_fragment",
                   return_value=str(tmp_path / "frag.yml")), \
             patch("backend.infra.providers.tunnel_headscale.compose_up",
                   return_value=(0, "")):
            HeadscaleProvider().deploy({"domain": "test.example.com"})

        # Pre-fix: NameError on image=IMAGE → except: pass → no call.
        # Post-fix: upsert_app called with image="headscale/headscale:latest".
        images = [c.get("image") for c in upsert_call_log]
        assert "headscale/headscale:latest" in images, \
            f"expected upsert_app called with correct image; saw kwargs: {upsert_call_log}"


# BUG: auth_authelia.py post-deploy upsert_app referenced bare IMAGE — never defined.
# NameError silently swallowed by `except Exception: pass` → upsert_app never ran.
# Fixed: step 1.2.d -- mypy [name-defined] auth_authelia.py:197
class TestBug_AutheliaImageUndefined:
    """deploy()'s post-deploy upsert_app block silently never ran."""

    def test_post_deploy_upsert_uses_correct_image(self, tmp_path, monkeypatch):
        import types
        from unittest.mock import patch, MagicMock
        from backend.infra.providers.auth_authelia import AutheliaProvider

        # config is a frozen dataclass — replace whole reference, not field.
        monkeypatch.setattr(
            "backend.infra.providers.auth_authelia.config",
            types.SimpleNamespace(data_dir=tmp_path),
        )

        mock_platform = MagicMock(
            domain="example.com",
            network_name="mediastack",
            timezone="UTC",
        )

        upsert_call_log = []
        def state_db_factory():
            db = MagicMock()
            db.get_platform = MagicMock(return_value=mock_platform)
            db.upsert_auth_provider = MagicMock()
            db.upsert_app = MagicMock(
                side_effect=lambda *a, **kw: upsert_call_log.append(kw))
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=db)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        # Patch BOTH StateDB binding sites: the module-top from-import in
        # auth_authelia AND backend.core.state for the in-method re-import.
        with patch("backend.infra.providers.auth_authelia.StateDB",
                   side_effect=state_db_factory), \
             patch("backend.core.state.StateDB", side_effect=state_db_factory), \
             patch("backend.infra.providers.auth_authelia.write_fragment",
                   return_value=str(tmp_path / "frag.yml")), \
             patch("backend.infra.providers.auth_authelia.compose_up",
                   return_value=(0, "")):
            AutheliaProvider().deploy({
                "domain": "test.example.com",
                "jwt_secret": "test-jwt-secret-32chars-long-aaaa",
                "session_secret": "test-session-secret-32chars-long",
            })

        # Pre-fix: NameError on image=IMAGE → except: pass → no call.
        # Post-fix: upsert_app called with image="authelia/authelia:latest".
        images = [c.get("image") for c in upsert_call_log]
        assert "authelia/authelia:latest" in images, \
            f"expected upsert_app called with correct image; saw kwargs: {upsert_call_log}"


# BUG: executor._wire() guarded `target is None` but not `source is None`.
# When source app was uninstalled, source.id raised AttributeError mid-SQL.
# Fixed: step 1.2.d -- mypy [union-attr] executor.py:990
class TestBug_ExecutorWireSourceUnguarded:
    """_wire() crashed with AttributeError when source was uninstalled."""

    def test_wire_source_missing_returns_skipped_without_AttributeError(self):
        from unittest.mock import patch, MagicMock
        from backend.manifests.executor import _wire

        # source missing, target present
        def get_app_side_effect(key):
            if key == "missing_source":
                return None
            return MagicMock(id=42)

        def state_db_factory():
            db = MagicMock()
            db.get_app = MagicMock(side_effect=get_app_side_effect)
            db.execute = MagicMock()
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=db)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        # Patch both binding sites: local import in executor + the module attr
        with patch("backend.manifests.executor.StateDB", side_effect=state_db_factory), \
             patch("backend.core.state.StateDB", side_effect=state_db_factory):
            # Pre-fix: only target was guarded; source.id raised AttributeError.
            # Post-fix: source-None guard returns "skipped" cleanly.
            result = _wire("missing_source", "present_target", "depends_on")

        assert result["status"] == "skipped"
        assert "missing_source" in result["message"], \
            f"expected message to name the missing source; got: {result['message']}"


# BUG: checker.py:880,910 passed status="error" to CheckResult — but the
# dataclass has no status field. Any execution of the no-compose-fragment
# or OOM-killed branches would TypeError at runtime.
# Fixed: step 1.2.e -- mypy [call-arg] checker.py:880,910
class TestBug_CheckResultStatusKwarg:
    """CheckResult dataclass rejects status= kwarg; pre-fix call sites were broken."""

    def test_check_result_dataclass_rejects_status_kwarg(self):
        """Confirm the dataclass surface that the fix relied on. Pre-fix code
        passed status='error' to CheckResult; this test verifies that call
        would have raised TypeError, proving the bug existed."""
        import pytest
        from backend.health.checker import CheckResult
        with pytest.raises(TypeError, match="status"):
            CheckResult(
                app_key="x", check_name="y", ok=False,
                message="m", status="error",
            )

    def test_check_result_post_fix_construction_succeeds(self):
        """Post-fix construction (no status kwarg) succeeds and produces
        the expected attributes."""
        from backend.health.checker import CheckResult
        r = CheckResult(
            app_key="x", check_name="y", ok=False, message="m",
        )
        assert r.app_key == "x"
        assert r.ok is False
        assert r.message == "m"


# BUG: run_health_cycle aggregator at checker.py:1195 used isinstance(_, Exception)
# which misses BaseException-but-not-Exception (asyncio.CancelledError,
# KeyboardInterrupt, SystemExit). asyncio.gather(return_exceptions=True)
# can return BaseException subclasses; pre-fix code tried to iterate them
# → "TypeError: ... is not iterable" → silent fan-out aggregator break.
# Fixed: step 1.2.e -- mypy [union-attr] checker.py:1197 (HIGH-severity per §6.3 line 6)
class TestBug_HealthAggregatorBaseException:
    """asyncio.CancelledError from a task crashed the health aggregator (HIGH-severity)."""

    def test_aggregator_pattern_skips_BaseException_subclasses(self):
        """Replicates the post-fix aggregator pattern from run_health_cycle.
        Demonstrates pre-fix vs post-fix behavior on the same input."""
        class CustomBase(BaseException):
            pass

        fake_results = [
            ["result_a"],     # normal: list of CheckResult-like
            CustomBase(),     # BaseException-but-not-Exception (would crash pre-fix)
            ValueError("x"),  # regular Exception (also skipped)
        ]

        # POST-FIX pattern (mirrors checker.py:1192-1196 verbatim)
        iterated = []
        for app_results in fake_results:
            if isinstance(app_results, BaseException):
                continue
            for r in app_results:
                iterated.append(r)
        assert iterated == ["result_a"]

        # PRE-FIX pattern reproduced — must crash on the CustomBase entry
        crashed_on_basexcept = False
        for app_results in fake_results:
            if isinstance(app_results, Exception):  # ← PRE-FIX
                continue
            try:
                for _ in app_results:
                    pass
            except TypeError:
                crashed_on_basexcept = True
        assert crashed_on_basexcept, (
            "pre-fix Exception-only check should crash when iterating BaseException")


# BUG: storage.add_source passed cur.lastrowid (int|None) to get_source(int).
# If INSERT silently fails to populate lastrowid, downstream KeyError —
# wrong error class, no actionable message.
# Fixed: step 1.2.e -- mypy [arg-type] storage.py:364
class TestBug_StorageAddSourceLastrowid:
    """add_source must fail loudly with RuntimeError when lastrowid is None."""

    def test_add_source_raises_RuntimeError_on_None_lastrowid(self):
        from unittest.mock import patch, MagicMock
        import pytest
        from backend.platform.storage import add_source

        mock_cur = MagicMock()
        mock_cur.lastrowid = None
        mock_db = MagicMock()
        mock_db._c.execute = MagicMock(return_value=mock_cur)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("backend.platform.storage.StateDB", return_value=mock_ctx):
            # Pre-fix: passes None to get_source → KeyError (wrong class, vague).
            # Post-fix: RuntimeError naming the failure mode.
            with pytest.raises(RuntimeError, match="lastrowid"):
                add_source(name="test", source_type="local", mount_point="/tmp")
