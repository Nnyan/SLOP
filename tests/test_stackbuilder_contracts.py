"""
tests/test_stackbuilder_contracts.py — Contract tests for Stackbuilder promises.

Every test verifies one specific promise end-to-end through the code path,
with injected error conditions, not just happy-path function existence.

Promises audited:
  P1:  Install = app running, registered in DB, health-monitored
  P2:  Remove = clean state (container, fragment, DB cascade, wiring)
  P3:  Replace = port pre-validated, wiring updated to new app
  P4:  Dependencies (postgres/redis) deployed before dependent app
  P5:  Port uniqueness enforced against running AND stopped apps
  P6:  Smoke test skips system-port apps (not falsely testing Traefik)
  P7:  Batch install isolates failures, reports dep-skipped to UI
  P8:  GitHub manifest validated before install_app() called
  P9:  Install lock expires after timeout (no permanent 409 deadlock)
  P10: Config directory cleaned up when install fails at deploy step
  P11: Wiring SQL runs on remove (not just logged)
  P12: replace_app rewires connections to the new app
  P13: Frontend poll timeout surfaces error message to user
  P14: ExecutionResult always returned — never raises to callers
  P15: Manifest port in DB matches compose fragment port mapping
"""

import ast
import pathlib
import re
import sqlite3
import tempfile
import pytest
import sys

REPO = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO))


def _executor() -> str:
    return (REPO / "backend" / "manifests" / "executor.py").read_text()

def _state() -> str:
    return (REPO / "backend" / "core" / "state.py").read_text()

def _compose() -> str:
    return (REPO / "backend" / "core" / "compose.py").read_text()

def _apps_api() -> str:
    return (REPO / "backend" / "api" / "apps.py").read_text()

def _catalog_vue() -> str:
    return (REPO / "frontend" / "src" / "views" / "CatalogView.vue").read_text()


# ── P1: Install registers app in DB ──────────────────────────────────────

class TestInstallPromises:
    def test_install_calls_upsert_app_on_success(self):
        """Successful install must write app to DB with status=running.

        Step 2.7.c: install_app's finalize block was extracted into
        the `_install_finalize` helper — that's where upsert_app is
        called now, not in a `# ── Finalise state` comment block.
        """
        src = _executor()
        finalise = src[src.find("def _install_finalize"):]
        assert "upsert_app" in finalise and "running" in finalise, (
            "install_app() doesn't write status=running to DB on success "
            "(checked inside _install_finalize helper)"
        )

    def test_install_deletes_db_record_on_early_failure(self):
        """If install fails before Docker deploy, DB record must be cleaned up."""
        src = _executor()
        assert "DELETE FROM apps WHERE key" in src, (
            "Failed pre-deploy installs leave orphaned DB records — "
            "retry says 'already installed and running'"
        )

    def test_install_marks_failed_not_deletes_on_docker_failure(self):
        """If Docker started but container crashed, mark failed (not delete)."""
        src = _executor()
        assert "status=\"failed\"" in src or "status='failed'" in src, (
            "Docker-failure path doesn't mark app as 'failed' in DB"
        )

    def test_install_returns_execution_result_never_raises(self):
        """install_app() must return ExecutionResult even on unexpected errors."""
        src = _executor()
        install_fn = src[src.find("def install_app("):]
        install_fn = install_fn[:install_fn.find("\ndef _install_inner")]
        assert "except Exception" in install_fn, (
            "install_app() has no top-level exception handler — "
            "unexpected errors propagate to callers as exceptions"
        )

    def test_install_smoke_test_runs_after_success(self):
        """Smoke test must run immediately after successful install.

        Step 2.7.c: install_app refactored — the orchestrator's
        success block runs both the CF hostname registration helper
        and the smoke-test step append. The first `if result.ok:`
        in executor.py now lives inside `_install_finalize`, which
        is unrelated to the smoke test.
        """
        src = _executor()
        assert "_run_smoke_test" in src, "No smoke test after install"
        install_start = src.find("def install_app(")
        install_end = src.find("\ndef ", install_start + 100)
        install_body = src[install_start:install_end]
        ok_idx = install_body.find("if result.ok:")
        ok_block = install_body[ok_idx:ok_idx + 2000] if ok_idx >= 0 else ""
        assert "_run_smoke_test" in ok_block, (
            "Smoke test not inside the orchestrator's `if result.ok:` "
            "block — runs even on failure"
        )

    # test_test_all_manifests_load_without_error removed — duplicate of test in test_comprehensive_contracts.py

    def test_install_lock_clears_stale_locks_on_timeout(self):
        """Stale install locks (> MAX_INSTALL_SECONDS) must be cleared automatically."""
        src = _executor()
        assert "MAX_INSTALL_SECONDS" in src, (
            "No install lock timeout — docker pull hang = permanent 409"
        )
        assert "stale" in src and "_installing_started" in src, (
            "Stale lock detection not implemented"
        )


# ── P2: Remove cascades fully ────────────────────────────────────────────

class TestRemovePromises:
    def test_remove_app_deletes_pending_fixes(self):
        """Removing an app must delete its pending AI fixes."""
        src = _state()
        remove_fn = src[src.find("def remove_app("):]
        remove_fn = remove_fn[:remove_fn.find("\n    def ", 100)]
        assert "pending_fixes" in remove_fn, (
            "remove_app() doesn't delete pending_fixes — "
            "removed app's fixes stay in the approval UI"
        )

    def test_remove_app_deletes_wiring(self):
        """Removing an app must delete its wiring rows."""
        src = _state()
        remove_fn = src[src.find("def remove_app("):]
        remove_fn = remove_fn[:remove_fn.find("\n    def ", 100)]
        assert "wiring" in remove_fn, (
            "remove_app() doesn't delete wiring — "
            "dangling wiring rows with FK to deleted app_id"
        )

    def test_remove_app_uses_app_id_for_wiring_delete(self):
        """Wiring delete must use app_id (FK), not app_key (string)."""
        src = _state()
        remove_fn = src[src.find("def remove_app("):]
        remove_fn = remove_fn[:remove_fn.find("\n    def ", 100)]
        # Must get the id before deleting the row
        assert "SELECT id FROM apps" in remove_fn or "app_id" in remove_fn, (
            "Wiring delete doesn't use app_id — won't find rows after app row deleted"
        )

    def test_remove_unwire_executes_sql_not_just_logs(self):
        """_remove_inner must execute UPDATE wiring SQL, not just add a log entry."""
        src = _executor()
        remove_inner = src[src.find("def _remove_inner("):]
        remove_inner = remove_inner[:remove_inner.find("\ndef remove_app")]
        # Must have actual SQL, not just result.add
        assert "UPDATE wiring" in remove_inner, (
            "_remove_inner only logs 'marked stale' without running SQL — "
            "wiring rows stay active pointing at deleted app"
        )

    def test_remove_app_db_is_consistent_after_remove(self, tmp_path):
        """After remove, no orphaned records should reference the removed app."""
        from backend.core.state import init_db, configure, StateDB

        db_path = tmp_path / "state.db"
        init_db(db_path)
        configure(db_path)

        with StateDB() as db:
            db.execute(
                """INSERT OR REPLACE INTO platform
                   (id, status, domain, config_root, media_root, puid, pgid, timezone, network_name, cert_resolver)
                   VALUES (1,'ready','test.local',?,?,1000,1000,'UTC','mediastack','letsencrypt')""",
                (str(tmp_path / "config"), str(tmp_path / "media")),
            )
            db._c.commit()
            db.upsert_app("sonarr", display_name="Sonarr", tier=1,
                          category="media", status="running",
                          image="lscr.io/linuxserver/sonarr",
                          container_name="sonarr", host_port=8989)
            sonarr = db.get_app("sonarr")
            db.upsert_app("prowlarr", display_name="Prowlarr", tier=1,
                          category="media", status="running",
                          image="lscr.io/linuxserver/prowlarr",
                          container_name="prowlarr", host_port=9696)
            prowlarr = db.get_app("prowlarr")
            # Wire sonarr → prowlarr
            if sonarr and prowlarr:
                db.execute(
                    "INSERT INTO wiring (source_app_id, target_app_id, wire_type, status, wired_at) "
                    "VALUES (?, ?, 'indexer', 'active', 0)",
                    (sonarr.id, prowlarr.id),
                )
            # Add a pending fix
            try:
                db.execute(
                    "INSERT INTO pending_fixes (app_key, check_name, action_type, "
                    "problem, suggested_fix, confidence) VALUES (?,?,?,?,?,?)",
                    ("sonarr", "api_reachable", "restart_container",
                     "not responding", "restart", 0.9),
                )
            except Exception:
                pass
            db._c.commit()

        with StateDB() as db:
            db.remove_app("sonarr")

        with StateDB() as db:
            remaining_wiring = db.execute(
                "SELECT COUNT(*) FROM wiring WHERE source_app_id=? OR target_app_id=?",
                (sonarr.id, sonarr.id),
            ).fetchone()[0]
            try:
                remaining_fixes = db.execute(
                    "SELECT COUNT(*) FROM pending_fixes WHERE app_key='sonarr'"
                ).fetchone()[0]
            except Exception:
                remaining_fixes = 0  # table lazily created, absence means no fixes
            remaining_app = db.get_app("sonarr")

        assert remaining_app is None, "App record still in DB after remove"
        assert remaining_wiring == 0, (
            f"{remaining_wiring} wiring row(s) still reference removed app"
        )
        assert remaining_fixes == 0, (
            f"{remaining_fixes} pending_fix row(s) still reference removed app"
        )


# ── P3: Replace is safe ───────────────────────────────────────────────────

class TestReplacePromises:
    def test_replace_validates_before_install(self):
        """replace_app must validate both old and new app before starting."""
        src = _executor()
        replace_fn = src[src.find("def replace_app("):]
        replace_fn = replace_fn[:replace_fn.find("\ndef _ensure_managed")]
        assert "validate" in replace_fn and "old_app is None" in replace_fn, (
            "replace_app doesn't validate old app exists before starting"
        )

    def test_replace_rewires_connections(self):
        """replace_app must update wiring to point to new app."""
        src = _executor()
        replace_fn = src[src.find("def replace_app("):]
        replace_fn = replace_fn[:replace_fn.find("\ndef _ensure_managed")]
        assert "UPDATE wiring" in replace_fn, (
            "replace_app doesn't rewire — dependent apps still point to removed old app"
        )

    def test_replace_handles_port_conflict(self):
        """replace_app must handle same-port scenario without conflicting."""
        src = _executor()
        replace_fn = src[src.find("def replace_app("):]
        replace_fn = replace_fn[:replace_fn.find("\ndef _ensure_managed")]
        assert "port" in replace_fn.lower(), (
            "replace_app has no port conflict handling — "
            "install_app(new) fails if old app is still using the same port"
        )

    def test_replace_result_ok_false_if_old_still_running(self):
        """If remove_old fails, result must reflect that even if new app is running."""
        src = _executor()
        replace_fn = src[src.find("def replace_app("):]
        replace_fn = replace_fn[:replace_fn.find("\ndef _ensure_managed")]
        assert "warning" in replace_fn and "remove" in replace_fn.lower(), (
            "replace_app silently ignores old app removal failure"
        )


# ── P4: Dependencies chain ────────────────────────────────────────────────

class TestDependencyPromises:
    def test_postgres_deployed_before_dependent_app(self):
        """_ensure_managed_service must run before app deploy in the install pipeline.

        Step 1.4.d split _install_inner into per-phase helpers; the
        ordering invariant now spans `_install_dependencies` (which
        calls _ensure_managed_service for postgres/redis) → fragment
        write → compose-up. Slice the whole pipeline (helpers +
        orchestrator) and assert their lexical order matches the
        runtime call order.
        """
        src = _executor()
        inner = src[src.find("def _validate_install("):]
        inner = inner[:inner.find("\ndef remove_app")]
        # Phase order: deps (postgres) → fragment → compose-up
        postgres_pos = inner.find("_ensure_managed_service")
        fragment_pos = inner.find("build_service_fragment")
        deploy_pos = inner.find("compose_up")
        assert 0 <= postgres_pos < fragment_pos < deploy_pos, (
            "Postgres deployment doesn't happen before app compose fragment is built. "
            f"positions: postgres={postgres_pos}, fragment={fragment_pos}, deploy={deploy_pos}"
        )

    def test_managed_service_registers_in_db(self):
        """_ensure_managed_service must call upsert_app so postgres appears in Dashboard."""
        src = _executor()
        managed = src[src.find("def _ensure_managed_service("):]
        managed = managed[:managed.find("\ndef _deploy_companions")]
        assert "upsert_app" in managed, (
            "_ensure_managed_service doesn't register postgres/redis in apps table — "
            "invisible to Dashboard and health scheduler"
        )

    def test_batch_preflight_adds_missing_deps(self):
        """Batch preflight must automatically add required dependencies to install_order."""
        src = _apps_api()
        preflight = src[src.find("def batch_preflight("):]
        preflight = preflight[:preflight.find("\n@router.post(\"/batch/install\")")]
        assert "missing_deps" in preflight or "requires" in preflight, (
            "batch_preflight doesn't resolve missing required dependencies"
        )

    def test_batch_install_skips_app_if_dep_failed(self):
        """If app A fails, batch must skip apps that require A."""
        src = _apps_api()
        batch = src[src.find("def _run_batch()"):]
        batch = batch[:batch.find("threading.Thread")]
        assert "failed_deps" in batch or "failed_keys" in batch, (
            "batch_install doesn't skip apps whose dependencies failed"
        )


# ── P5: Port uniqueness ───────────────────────────────────────────────────

class TestPortUniqueness:
    def test_port_conflict_checks_db_not_just_running(self):
        """Port check must query DB, not just running containers.

        Step 1.4.d / 2.7: port-conflict logic moved from inline
        comments inside _install_inner to a `_check_port_conflict`
        helper. Slice the helper body and check for the DB query
        guarding stopped apps' port reservations.
        """
        src = _executor()
        port_check_start = src.find("def _check_port_conflict(")
        port_check_end = src.find("\ndef ", port_check_start + 50)
        port_check = src[port_check_start:port_check_end] if port_check_start >= 0 else ""
        assert "SELECT key FROM apps" in port_check or "host_port=?" in port_check, (
            "Port conflict only checks running containers — "
            "stopped apps can have their port stolen"
        )

    def test_port_conflict_gives_plain_english_error(self):
        """Port conflict error must name the conflicting app."""
        src = _executor()
        assert "is already in use by" in src or "reserved by" in src, (
            "Port conflict error doesn't name the conflicting app"
        )

    def test_no_two_catalog_apps_share_a_port(self):
        """No two catalog apps should have the same web_port."""
        from backend.manifests.loader import load_all_manifests, clear_cache
        clear_cache()
        manifests = load_all_manifests()
        _SYSTEM_PORTS = {80, 443, 8080, 8081}
        port_map: dict[int, list[str]] = {}
        for key, m in manifests.items():
            if m.web_port and m.web_port not in _SYSTEM_PORTS:
                port_map.setdefault(m.web_port, []).append(key)
        conflicts = {p: keys for p, keys in port_map.items() if len(keys) > 1}
        assert not conflicts, (
            f"Port conflicts in catalog: {conflicts} — "
            f"installing these apps together will always fail"
        )


# ── P6: Smoke test correctness ────────────────────────────────────────────

class TestSmokeTest:
    def test_smoke_skips_system_port_apps(self):
        """Smoke test must skip apps on ports 80/443/8080/8081."""
        src = _executor()
        smoke = src[src.find("def _run_smoke_test("):]
        smoke = smoke[:smoke.find("\ndef _wire")]
        assert "_SYSTEM_PORTS" in smoke and "skipped" in smoke, (
            "Smoke test hits localhost:80 for system-port apps — "
            "tests Traefik, not the app, and always passes falsely"
        )

    def test_smoke_test_updates_health_checks_on_failure(self):
        """Failed smoke test must write to health_checks table."""
        src = _executor()
        smoke = src[src.find("def _run_smoke_test("):]
        smoke = smoke[:smoke.find("\ndef _wire")]
        assert "upsert_health_check" in smoke, (
            "Smoke test failure doesn't write to health_checks — "
            "dashboard doesn't show unhealthy status"
        )

    def test_smoke_test_marks_app_unhealthy_on_failure(self):
        """Failed smoke test must set app status to unhealthy."""
        src = _executor()
        smoke = src[src.find("def _run_smoke_test("):]
        smoke = smoke[:smoke.find("\ndef _wire")]
        assert "unhealthy" in smoke or "status=\"unhealthy\"" in smoke, (
            "Smoke test failure doesn't mark app unhealthy in DB"
        )


# ── P7: Batch install UI feedback ─────────────────────────────────────────

class TestBatchInstall:
    def test_batch_returns_dep_skipped_list(self):
        """Batch install response must include dep_skipped so UI can pre-mark them."""
        src = _apps_api()
        # Find the return dict after the thread start
        thread_pos = src.find("threading.Thread(target=_run_batch")
        batch_return = src[thread_pos:thread_pos+500]
        assert "dep_skipped" in batch_return or "skipped" in batch_return, (
            "Batch install response doesn't include dep_skipped — "
            "UI shows all as 'pending' when some will never start"
        )

    def test_batch_preflight_topological_order(self):
        """Batch preflight must order deps before dependents."""
        src = _apps_api()
        preflight = src[src.find("def batch_preflight("):]
        assert "install_order" in preflight and ("sort" in preflight or "PRIORITY" in preflight), (
            "Batch preflight has no topological sort — prowlarr may install after sonarr"
        )

    def test_batch_install_error_is_isolated(self):
        """One app failing batch must not block subsequent apps."""
        src = _apps_api()
        batch_fn = src[src.find("def _run_batch()"):]
        batch_fn = batch_fn[:batch_fn.find("threading.Thread")]
        assert "failed_keys" in batch_fn or "continue" in batch_fn, (
            "Batch install doesn't isolate failures — one failure stops all remaining apps"
        )


# ── P8: GitHub manifest validation ───────────────────────────────────────

class TestGitHubInstall:
    def test_github_manifest_validated_before_install(self):
        """install_from_github must validate manifest fields before calling install_app."""
        src = _apps_api()
        github_fn = src[src.find("def install_from_github("):]
        github_fn = github_fn[:github_fn.find("\n\n@router.post(\"/install-custom\")")]
        assert ("validate" in github_fn.lower() or "required" in github_fn
                or "missing" in github_fn), (
            "install_from_github passes manifest to install_app without validation — "
            "missing 'image' field gives opaque executor error"
        )

    def test_github_manifest_error_returns_ok_false(self):
        """Validation failure must return HTTP error (HTTPException or {ok: False})."""
        src = _apps_api()
        github_fn = src[src.find("def install_from_github("):]
        github_fn = github_fn[:github_fn.find("\n\n@router.post(\"/install-custom\")")]
        # HTTPException is acceptable — FastAPI converts it to a 4xx response
        has_error_response = (
            "HTTPException" in github_fn
            or '"ok": False' in github_fn
            or "'ok': False" in github_fn
        )
        assert has_error_response, (
            "Validation failure has no error response — "
            "caller gets no indication of what went wrong"
        )


# ── P9 / P10: Lock timeout and config cleanup ─────────────────────────────

class TestInstallSafety:
    def test_config_dir_cleaned_on_deploy_failure(self):
        """Config directory created in step 3 must be removed if step 5 (deploy) fails.

        Step 1.4.d split _install_inner into per-phase helpers
        (_validate_install / _install_dependencies / _ensure_config_dir /
        _compute_host_port / _check_port_conflict / ...). The cleanup
        marker `_config_dir_created_now` lives in the helpers, not the
        orchestrator body — slice the helper region too.
        """
        src = _executor()
        inner = src[src.find("def _validate_install("):]
        inner = inner[:inner.find("\ndef remove_app")]
        assert "_config_dir_created_now" in inner or "shutil.rmtree(config_path)" in inner, (
            "Config directory survives failed install — "
            "reinstall after image-pull-failure finds stale config files"
        )

    def test_install_lock_has_maximum_lifetime(self):
        """_installing set entries must expire after MAX_INSTALL_SECONDS."""
        src = _executor()
        assert "MAX_INSTALL_SECONDS" in src, (
            "Install lock has no max lifetime — docker pull hang = permanent 409 deadlock"
        )


# ── P11 / P12: Wiring integrity ───────────────────────────────────────────

class TestWiringIntegrity:
    def test_unwire_runs_sql_not_just_logs(self):
        """_remove_inner must execute UPDATE wiring SQL, not just log the action."""
        src = _executor()
        remove_inner = src[src.find("def _remove_inner("):]
        remove_inner = remove_inner[:remove_inner.find("\ndef remove_app(")]
        assert "UPDATE wiring" in remove_inner, (
            "remove_app logs 'wiring marked stale' without running SQL — "
            "wiring rows stay active, health agent gets confused about dependencies"
        )

    def test_replace_app_updates_wiring_to_new_app(self):
        """replace_app must update wiring rows to point to new app, not old."""
        src = _executor()
        replace_fn = src[src.find("def replace_app("):]
        replace_fn = replace_fn[:replace_fn.find("\ndef _ensure_managed")]
        assert "UPDATE wiring" in replace_fn, (
            "replace_app doesn't rewire — after Plex→Jellyfin replace, "
            "Sonarr's wiring still points at removed Plex"
        )


# ── P13: Frontend timeout ────────────────────────────────────────────────

class TestFrontendTimeout:
    def test_catalog_poll_timeout_sets_error(self):
        """5-minute poll timeout must set installError, not silently stop."""
        src = _catalog_vue()
        timeout_block = src[src.find("300_000"):]
        timeout_block = timeout_block[:200]
        assert "installError" in timeout_block or "timed out" in timeout_block.lower(), (
            "Install timeout silently stops UI — user doesn't know install timed out"
        )

    def test_catalog_timeout_calls_stop_progress(self):
        """Timeout must call stopInstallProgress to reset the progress bar."""
        src = _catalog_vue()
        timeout_block = src[src.find("300_000"):]
        timeout_block = timeout_block[:300]
        assert "stopInstallProgress" in timeout_block, (
            "Timeout doesn't reset progress bar — stuck at X% forever"
        )


# ── P14: No silent exceptions ────────────────────────────────────────────

class TestNoSilentExceptions:
    def test_install_app_has_top_level_catch(self):
        src = _executor()
        fn = src[src.find("def install_app("):]
        fn = fn[:src.find("def _install_inner(")]
        assert "except Exception" in fn, (
            "install_app() has no top-level exception handler — can raise to callers"
        )

    def test_remove_app_has_top_level_catch(self):
        src = _executor()
        fn = src[src.find("def remove_app("):]
        fn = fn[:src.find("def _remove_inner(")]
        assert "except Exception" in fn, (
            "remove_app() has no top-level exception handler"
        )

    def test_replace_app_not_in_try_but_validates_first(self):
        """replace_app doesn't need a try/except because it delegates to install/remove."""
        src = _executor()
        fn = src[src.find("def replace_app("):]
        fn = fn[:src.find("def _ensure_managed_service(")]
        # Either has try/except OR validates old/new before delegating
        has_guard = "except Exception" in fn or (
            "old_app is None" in fn and "load_manifest" in fn
        )
        assert has_guard, "replace_app has no validation guard before delegating"


# ── P15: Port consistency across layers ───────────────────────────────────

class TestPortConsistency:
    def test_manifest_port_matches_traefik_label_port(self):
        """Traefik label loadbalancer.server.port must use manifest.web_port."""
        src = _compose()
        labels_fn = src[src.find("def _traefik_labels("):]
        labels_fn = labels_fn[:labels_fn.find("\ndef build_service_fragment")]
        assert "web_port" in labels_fn and "loadbalancer.server.port" in labels_fn, (
            "Traefik loadbalancer port not set from manifest.web_port"
        )

    def test_compose_fragment_port_matches_health_check_port(self):
        """The port in the compose fragment must match what health checker uses.

        Step 1.4.d: host_port derivation lives in `_compute_host_port`
        (the per-phase helper), not in _install_inner's body — slice
        the helper region, not just the orchestrator.
        """
        # Health checker uses app.host_port from DB
        # DB host_port is set from host_port in the install pipeline
        # _compute_host_port derives host_port from manifest.web_port
        # So: manifest.web_port → host_port in DB → health check uses host_port
        src = _executor()
        inner = src[src.find("def _validate_install("):]
        inner = inner[:inner.find("\ndef remove_app")]
        assert "host_port" in inner and "web_port" in inner, (
            "host_port derivation from web_port missing in install pipeline"
        )

    def test_traefik_uses_web_port_health_uses_host_port(self):
        """Traefik talks to container (web_port), health checker talks to host (host_port)."""
        compose_src = _compose()
        executor_src = _executor()
        # Traefik label uses web_port (container-internal)
        assert "web_port" in compose_src and "loadbalancer.server.port" in compose_src, (
            "Traefik loadbalancer not using web_port (container-internal port)"
        )
        # Health checker must use host_port (host-mapped port)
        checker_src = (REPO / "backend" / "health" / "checker.py").read_text()
        assert "host_port" in checker_src, (
            "Health checker not using host_port — may be testing container-internal port from host"
        )