"""tests/test_agent_classifier.py

Unit tests for:
  backend/agent/taxonomy.py  — ErrorClass enum + DETECTION_PATTERNS
  backend/agent/classifier.py — classify_offline() + compute_signature_hash()
  backend/agent/listener.py  — integration: uses classifier, writes real class

Coverage:
  TestClassifyOffline:
    - One test per detectable class (9 tests)
    - Fallback to UNKNOWN (1 test)

  TestComputeSignatureHash:
    - Determinism (same inputs → same hash)
    - Sensitivity to app_key
    - Normalisation strips paths and numbers

  TestListenerUsesClassifier:
    - Error step with IMAGE_PULL_FAIL signal writes IMAGE_PULL_FAIL
    - Error step with unrecognised text writes UNKNOWN

StateDB fixture: same as test_agent_listener.py.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core.state as _state_mod
from backend.core.state import StateDB, init_db
from backend.agent.taxonomy import ErrorClass
from backend.agent.classifier import classify_offline, compute_signature_hash
from backend.agent.listener import install_failure_listener


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated database for each test — same pattern as test_agent_listener."""
    p = tmp_path / "state.db"
    init_db(p)
    _state_mod.configure(p)
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_pending_fixes(db_path: Path) -> list[dict]:
    """Return all rows from pending_fixes as plain dicts."""
    with StateDB() as db:
        rows = db.execute("SELECT * FROM pending_fixes").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# classify_offline tests
# ---------------------------------------------------------------------------


class TestClassifyOffline:

    def test_image_pull_fail_manifest_unknown(self) -> None:
        text = "Error response from daemon: manifest unknown"
        assert classify_offline(text) == ErrorClass.IMAGE_PULL_FAIL

    def test_image_pull_fail_pull_access_denied(self) -> None:
        text = "pull access denied for private-repo/app, repository does not exist"
        assert classify_offline(text) == ErrorClass.IMAGE_PULL_FAIL

    def test_port_conflict(self) -> None:
        text = "Error starting userland proxy: listen tcp4 0.0.0.0:8080: bind: address already in use"
        assert classify_offline(text) == ErrorClass.PORT_CONFLICT

    def test_eperm_volume(self) -> None:
        # 'permission denied' without matching a higher-priority class
        text = "mkdir /config: permission denied"
        assert classify_offline(text) == ErrorClass.EPERM_VOLUME

    def test_missing_env_var_is_required(self) -> None:
        text = "POSTGRES_PASSWORD is required but not set"
        assert classify_offline(text) == ErrorClass.MISSING_ENV_VAR

    def test_missing_env_var_not_set(self) -> None:
        text = "API_KEY not set — aborting startup"
        assert classify_offline(text) == ErrorClass.MISSING_ENV_VAR

    def test_unresolved_placeholder(self) -> None:
        text = "env value contains unresolved placeholder: {puid}"
        assert classify_offline(text) == ErrorClass.UNRESOLVED_PLACEHOLDER

    def test_healthcheck_timeout(self) -> None:
        text = "container is unhealthy after 5 retries"
        assert classify_offline(text) == ErrorClass.HEALTHCHECK_TIMEOUT

    def test_crash_loop_restarting(self) -> None:
        text = "Restarting (1) 3 seconds ago"
        assert classify_offline(text) == ErrorClass.CRASH_LOOP

    def test_resource_exhaustion_oomkilled(self) -> None:
        # OOMKilled must be caught by RESOURCE_EXHAUSTION (priority 4)
        # before CRASH_LOOP (priority 9)
        text = "container exit: OOMKilled=true exit_code=137"
        assert classify_offline(text) == ErrorClass.RESOURCE_EXHAUSTION

    def test_resource_exhaustion_enospc(self) -> None:
        text = "write /var/lib/docker/overlay2: ENOSPC"
        assert classify_offline(text) == ErrorClass.RESOURCE_EXHAUSTION

    def test_dependency_down_connection_refused(self) -> None:
        text = "dial tcp 172.17.0.2:5432: connect: Connection refused"
        assert classify_offline(text) == ErrorClass.DEPENDENCY_DOWN

    def test_dependency_down_no_such_host(self) -> None:
        text = "Get http://postgres:5432/health: dial tcp: lookup postgres on 127.0.0.11:53: no such host"
        assert classify_offline(text) == ErrorClass.DEPENDENCY_DOWN

    def test_unknown_fallback_for_unrecognised_text(self) -> None:
        text = "Something completely different with no known signal whatsoever"
        assert classify_offline(text) == ErrorClass.UNKNOWN

    def test_empty_string_returns_unknown(self) -> None:
        assert classify_offline("") == ErrorClass.UNKNOWN

    def test_case_insensitive_matching(self) -> None:
        # 'MANIFEST UNKNOWN' uppercased should still match IMAGE_PULL_FAIL
        text = "MANIFEST UNKNOWN"
        assert classify_offline(text) == ErrorClass.IMAGE_PULL_FAIL


# ---------------------------------------------------------------------------
# compute_signature_hash tests
# ---------------------------------------------------------------------------


class TestComputeSignatureHash:

    def test_same_inputs_same_hash(self) -> None:
        h1 = compute_signature_hash(ErrorClass.PORT_CONFLICT, "bind: address already in use", "sonarr")
        h2 = compute_signature_hash(ErrorClass.PORT_CONFLICT, "bind: address already in use", "sonarr")
        assert h1 == h2

    def test_different_app_keys_differ(self) -> None:
        h1 = compute_signature_hash(ErrorClass.PORT_CONFLICT, "bind: address already in use", "sonarr")
        h2 = compute_signature_hash(ErrorClass.PORT_CONFLICT, "bind: address already in use", "radarr")
        assert h1 != h2

    def test_different_classes_differ(self) -> None:
        h1 = compute_signature_hash(ErrorClass.PORT_CONFLICT, "some error", "sonarr")
        h2 = compute_signature_hash(ErrorClass.UNKNOWN, "some error", "sonarr")
        assert h1 != h2

    def test_normalization_strips_paths_and_numbers(self) -> None:
        """Two errors identical except for a container ID / path produce the same hash."""
        base = "permission denied on /var/lib/docker/overlay2/abc123def456"
        variant = "permission denied on /var/data/containers/overlay2/deadbeef12345678"
        h1 = compute_signature_hash(ErrorClass.EPERM_VOLUME, base, "sonarr")
        h2 = compute_signature_hash(ErrorClass.EPERM_VOLUME, variant, "sonarr")
        assert h1 == h2

    def test_normalization_strips_timestamps(self) -> None:
        e1 = "crash at 2024-01-15T12:34:56Z exit code 1"
        e2 = "crash at 2025-06-30T23:59:59Z exit code 1"
        h1 = compute_signature_hash(ErrorClass.CRASH_LOOP, e1, "sonarr")
        h2 = compute_signature_hash(ErrorClass.CRASH_LOOP, e2, "sonarr")
        assert h1 == h2

    def test_hash_is_40_char_hex(self) -> None:
        h = compute_signature_hash(ErrorClass.UNKNOWN, "some error", "app")
        assert len(h) == 40
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Listener integration tests (listener now calls classifier)
# ---------------------------------------------------------------------------


class TestListenerUsesClassifier:

    def test_error_step_writes_classified_row(self, db_path: Path) -> None:
        """Error step with IMAGE_PULL_FAIL signal writes IMAGE_PULL_FAIL class."""
        step = {
            "name": "pull",
            "status": "error",
            "message": "Image pull failed",
            "detail": "manifest unknown for linuxserver/sonarr:latest",
        }
        asyncio.run(install_failure_listener("sonarr", step))
        rows = _get_pending_fixes(db_path)
        assert len(rows) == 1, f"Expected 1 row, got {rows}"
        assert rows[0]["diagnosis_class"] == "IMAGE_PULL_FAIL"
        assert rows[0]["app_key"] == "sonarr"

    def test_error_step_writes_unknown_for_unrecognised(self, db_path: Path) -> None:
        """Error step with unrecognised text writes UNKNOWN class."""
        step = {
            "name": "deploy",
            "status": "error",
            "message": "Something weird happened",
            "detail": "completely novel error with no known pattern at all",
        }
        asyncio.run(install_failure_listener("radarr", step))
        rows = _get_pending_fixes(db_path)
        assert len(rows) == 1, f"Expected 1 row, got {rows}"
        assert rows[0]["diagnosis_class"] == "UNKNOWN"

    def test_error_step_writes_port_conflict_class(self, db_path: Path) -> None:
        """Port-conflict error detail → PORT_CONFLICT class persisted."""
        step = {
            "name": "deploy",
            "status": "error",
            "message": "Deploy failed",
            "detail": "Error: bind: address already in use port 8080",
        }
        asyncio.run(install_failure_listener("bazarr", step))
        rows = _get_pending_fixes(db_path)
        assert len(rows) == 1
        assert rows[0]["diagnosis_class"] == "PORT_CONFLICT"

    def test_non_error_step_writes_nothing(self, db_path: Path) -> None:
        """Non-error steps do not write pending_fixes rows."""
        step = {"name": "pull", "status": "ok", "message": "pulled", "detail": ""}
        asyncio.run(install_failure_listener("sonarr", step))
        rows = _get_pending_fixes(db_path)
        assert rows == []


# ---------------------------------------------------------------------------
# Phase C: classify_with_llm tests
# ---------------------------------------------------------------------------


def _seed_fix_history(db_path: Path, sig_hash: str, fix: str) -> None:
    """Pre-seed fix_history with a success row for the given signature_hash."""
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO fix_history "
        "(app_key, error_type, context, suggested_fix, outcome, created_at, "
        " diagnosis_class, signature_hash) "
        "VALUES (?, ?, ?, ?, 'success', unixepoch(), ?, ?)",
        ("sonarr", "IMAGE_PULL_FAIL", "", fix, "IMAGE_PULL_FAIL", sig_hash),
    )
    conn.commit()
    conn.close()


class TestClassifyWithLlm:

    def test_pattern_library_hit_skips_llm(self, db_path: Path, monkeypatch) -> None:
        """If fix_history has a matching signature_hash, LLM is never called."""
        from backend.agent.classifier import classify_with_llm, compute_signature_hash
        from backend.agent.taxonomy import ErrorClass

        error_text = "manifest unknown for linuxserver/sonarr:latest"
        app_key = "sonarr"

        # Pre-seed fix_history with a cached success row
        sig_hash = compute_signature_hash(ErrorClass.IMAGE_PULL_FAIL, error_text, app_key)
        cached_fix = "Pull the image manually: docker pull linuxserver/sonarr:latest"
        _seed_fix_history(db_path, sig_hash, cached_fix)

        # Track whether the LLM helper is called
        llm_called = []

        async def _fake_llm(prompt: str):  # type: ignore[override]
            llm_called.append(prompt)
            return "should not be called"

        monkeypatch.setattr(
            "backend.agent.classifier._query_llm_for_diagnosis", _fake_llm
        )

        error_class, suggested_fix, confidence = asyncio.run(
            classify_with_llm(error_text, app_key, str(db_path))
        )

        assert confidence == 0.95, f"Expected 0.95, got {confidence}"
        assert suggested_fix == cached_fix
        assert error_class == ErrorClass.IMAGE_PULL_FAIL
        assert llm_called == [], "LLM must NOT be called on pattern-library hit"

    def test_llm_unreachable_returns_offline_class(
        self, db_path: Path, monkeypatch
    ) -> None:
        """If LLM returns None, offline class is returned with confidence=0.4."""
        from backend.agent.classifier import classify_with_llm
        from backend.agent.taxonomy import ErrorClass

        monkeypatch.setattr(
            "backend.agent.classifier._query_llm_for_diagnosis",
            lambda *a, **kw: _coro(None),
        )

        error_text = "manifest unknown for linuxserver/sonarr:latest"
        error_class, suggested_fix, confidence = asyncio.run(
            classify_with_llm(error_text, "sonarr", str(db_path))
        )

        assert confidence == 0.4, f"Expected 0.4 (LLM unreachable), got {confidence}"
        assert suggested_fix == ""
        assert error_class == ErrorClass.IMAGE_PULL_FAIL

    def test_llm_response_gives_suggested_fix(
        self, db_path: Path, monkeypatch
    ) -> None:
        """If LLM returns text, suggested_fix is extracted and confidence=0.8."""
        from backend.agent.classifier import classify_with_llm
        from backend.agent.taxonomy import ErrorClass

        llm_reply = "Try pulling the image manually first."
        monkeypatch.setattr(
            "backend.agent.classifier._query_llm_for_diagnosis",
            lambda *a, **kw: _coro(llm_reply),
        )

        error_text = "manifest unknown for linuxserver/sonarr:latest"
        error_class, suggested_fix, confidence = asyncio.run(
            classify_with_llm(error_text, "sonarr", str(db_path))
        )

        assert confidence == 0.8, f"Expected 0.8 (LLM responded, non-UNKNOWN), got {confidence}"
        assert suggested_fix != ""
        assert "manually" in suggested_fix.lower() or suggested_fix[:5] == llm_reply[:5]
        assert error_class == ErrorClass.IMAGE_PULL_FAIL

    def test_listener_writes_suggested_fix(
        self, db_path: Path, monkeypatch
    ) -> None:
        """Listener uses classify_with_llm and persists suggested_fix + confidence."""
        from backend.agent.taxonomy import ErrorClass

        monkeypatch.setattr(
            "backend.agent.listener.classify_with_llm",
            lambda *a, **kw: _coro(
                (ErrorClass.IMAGE_PULL_FAIL, "Try X", 0.8)
            ),
        )

        step = {
            "name": "pull",
            "status": "error",
            "message": "Image pull failed",
            "detail": "manifest unknown for linuxserver/sonarr:latest",
        }
        asyncio.run(install_failure_listener("sonarr", step))
        rows = _get_pending_fixes(db_path)

        assert len(rows) == 1, f"Expected 1 row, got {rows}"
        assert rows[0]["suggested_fix"] == "Try X"
        assert abs(rows[0]["confidence"] - 0.8) < 0.001
        assert rows[0]["diagnosis_class"] == "IMAGE_PULL_FAIL"


# ---------------------------------------------------------------------------
# Helpers for async monkeypatching in sync test contexts
# ---------------------------------------------------------------------------


async def _coro(value):
    """Return *value* as a coroutine — for use in monkeypatch lambdas."""
    return value
