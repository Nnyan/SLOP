"""tests/conftest.py

Shared pytest configuration:
- Reports test results to the health API after each run (feeds the LLM)
- Provides shared fixtures used across multiple test files
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """After every test run, POST results to the health API if it's running.

    This feeds the LLM health agent so it can include test status in
    weekly summaries, flag regressions, and suggest new test coverage.
    """
    stats = terminalreporter.stats
    passed = len(stats.get("passed", []))
    failed = len(stats.get("failed", []))
    errors = len(stats.get("error", []))
    try:
        _t = terminalreporter._session_start
        duration = time.monotonic() - float(_t) if isinstance(_t, (int, float)) else 0.0
    except Exception:
        duration = 0.0

    failures = []
    for item in stats.get("failed", []) + stats.get("error", []):
        failures.append({
            "name": item.nodeid,
            "message": str(item.longreprtext)[:500] if hasattr(item, "longreprtext") else str(item)[:200],
        })

    payload = {
        "passed": passed,
        "failed": failed + errors,
        "duration_s": round(duration, 1),
        "failures": failures[:20],
    }

    # Write to local file as well (works even when API is down).
    # Derive path from config.data_dir — same source ms-test.py + production
    # use (Core Rule 3.9). Hardcoded REPO/"data" diverges on non-default
    # MS_DATA_DIR deployments. Closes 1.1.5.k.
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from backend.core.config import config as _cfg
        results_file = _cfg.data_dir / "last_test_run.json"
    except Exception:
        # Fallback for environments without backend on path
        results_file = Path(__file__).parent.parent / "data" / "last_test_run.json"
    try:
        results_file.parent.mkdir(parents=True, exist_ok=True)
        results_file.write_text(json.dumps({**payload, "ts": int(time.time())}))
    except Exception:
        pass

    # POST to API if it's up
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:8080/api/health/test-results",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # API not running — results saved to file instead


# ──────────────────────────────────────────────────────────────────────────────
# Shared runtime fixtures — used by E2E, failure-path, and state-machine tests
# ──────────────────────────────────────────────────────────────────────────────
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.core import state as _state_mod
from backend.core.state import StateDB, init_db


# ──────────────────────────────────────────────────────────────────────────────
# CWD isolation — autouse, function-scoped (S-66 Stream B, Cluster 2b)
# ──────────────────────────────────────────────────────────────────────────────
# tests/test_merge_wave_to_main.py has 4 bare os.chdir() calls with no
# restore, leaving cwd set to a tmp git repo. Downstream tests using
# Path("relative/path") then fail silently.  This autouse fixture saves
# and restores cwd around EVERY test, eliminating that pollution without
# editing test_merge_wave_to_main.py (which S-68 owns).
import os as _os


@pytest.fixture(autouse=True)
def _restore_cwd():
    """Save and restore os.getcwd() around every test (S-66 cwd isolation)."""
    _saved = _os.getcwd()
    yield
    _os.chdir(_saved)


# ──────────────────────────────────────────────────────────────────────────────
# config.data_dir isolation — autouse, function-scoped (S-66 Stream B, Cluster 1)
# ──────────────────────────────────────────────────────────────────────────────
# Infra providers (GlanceDashboardProvider, HomepageProvider) call
# cfg_dir.mkdir() using platform.config_root or config.data_dir.
# In CI / sandbox, platform.config_root is NULL and config.data_dir
# resolves to /srv/mediastack or /var/lib/mediastack — paths that don't
# exist and aren't writable. Redirecting data_dir → tmp_path makes
# providers write to an isolated temp directory, fixing the PermissionError
# without touching product code.  compose_dir is a property derived from
# data_dir, so it is automatically redirected as well.
@pytest.fixture(autouse=True)
def _isolate_config_data_dir(tmp_path: Path):
    """Redirect config.data_dir (and derived compose_dir) to tmp_path (S-66)."""
    from backend.core import config as _cfg_mod
    _cfg = _cfg_mod.config
    _orig = _cfg.data_dir
    _new = tmp_path / "ms_data"
    _new.mkdir(parents=True, exist_ok=True)
    object.__setattr__(_cfg, "data_dir", _new)
    yield
    object.__setattr__(_cfg, "data_dir", _orig)


# ──────────────────────────────────────────────────────────────────────────────
# Event-loop isolation — autouse, function-scoped (S-66 Stream B, Cluster 2a)
# ──────────────────────────────────────────────────────────────────────────────
# asyncio.run() in test_llm_diagnose_refactor.py closes + clears the
# current event loop.  Downstream tests in test_llm_models.py call
# asyncio.get_event_loop().run_until_complete() which raises RuntimeError
# when no loop is set.  Creating a fresh loop before each test ensures
# get_event_loop() always succeeds for sync callers.
# pytest-asyncio (strict mode) manages its own loop per async test and
# always calls asyncio.set_event_loop(), so this fixture does not
# interfere with async tests.
@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """Ensure a usable asyncio event loop exists before every test (S-66)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    yield


# ──────────────────────────────────────────────────────────────────────────────
# Community catalog pollution scrubber (step 2.6 Bucket D)
# ──────────────────────────────────────────────────────────────────────────────
# `catalog/community/` is gitignored and used in production for
# user-installed custom manifests (via /api/apps/install-from-github
# and /api/apps/install-custom). A few tests hit those endpoints with
# malicious-key payloads (`../../etc/passwd`, `my_app...danger`) to
# exercise the sanitiser — the sanitised manifests get written to the
# real community dir and are then loaded by every subsequent
# `load_all_manifests()` call, tripping integrity contracts.
#
# Scrub known test-pollution patterns at session start AND end. We do
# NOT touch arbitrary files — only filenames matching test patterns —
# so a real user-installed manifest in `catalog/community/` survives.
_TEST_MANIFEST_PATTERNS = (
    "myapp", "______etc_passwd", "my_app____danger__",
)


def _scrub_community_test_pollution() -> None:
    community = Path(__file__).parent.parent / "catalog" / "community"
    if not community.exists():
        return
    for f in community.iterdir():
        if not f.is_file():
            continue
        for pat in _TEST_MANIFEST_PATTERNS:
            if f.stem == pat or f.stem.startswith(pat + "."):
                f.unlink()
                break


@pytest.fixture(autouse=True)
def _community_catalog_scrub():
    """Scrub known security-test pollution from catalog/community/
    before AND after every test. Function-scoped (was session-scoped):
    `test_non_catalog_installs.py::test_key_sanitization_*` writes
    sanitised manifests mid-session, which would otherwise leak into
    every integrity contract test that runs later."""
    _scrub_community_test_pollution()
    yield
    _scrub_community_test_pollution()


# ──────────────────────────────────────────────────────────────────────────────
# Compose-dir redirect (step 2.2.d) — opt-in fixture
# ──────────────────────────────────────────────────────────────────────────────
# Tests that exercise provider.deploy() or install_app() write a real
# compose fragment to `config.compose_dir`. Without redirection, those
# writes land in /srv/mediastack/data/compose (production!) — and on
# some hosts that's not writeable by the test user, raising
# PermissionError. Per ADR 0002 §3-4, the fix is a real-fake
# tmp_path-backed compose dir, not a mock on `write_fragment`.
@pytest.fixture
def tmp_compose_dir(tmp_path: Path):
    """Redirect `config.compose_dir` (and `config.data_dir`) to a tmp
    path for the duration of the test. The real `write_fragment` and
    related compose helpers run unmodified — they just write to the
    tmp dir instead of /srv/mediastack/data/. Yields the compose dir
    path so the test can assert on what was written."""
    from backend.core import config as _cfg_mod
    from unittest.mock import MagicMock
    compose = tmp_path / "compose"
    compose.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    original_config = _cfg_mod.config
    mock_cfg = MagicMock()
    mock_cfg.compose_dir = compose
    mock_cfg.data_dir = data
    mock_cfg.config_root = tmp_path / "config"
    _cfg_mod.config = mock_cfg
    try:
        yield compose
    finally:
        _cfg_mod.config = original_config


# ──────────────────────────────────────────────────────────────────────────────
# Fast smoke test (step 2.6.a) — autouse, opt-out via `real_smoke_test` marker
# ──────────────────────────────────────────────────────────────────────────────
# `_run_smoke_test` polls TCP `localhost:<host_port>` until success or
# `manifest.start_grace_s` (default 30s) elapses. In test environments
# there's no real container listening, so the loop hangs the full
# `start_grace_s` per test — turning ~200ms test runs into 30s timeouts.
#
# This autouse fixture replaces `_run_smoke_test` with a fast-pass StepLog
# so the install pipeline returns immediately. Tests that exercise the
# real smoke-test loop (e.g. test_health_scheduler.TestSmokeTests) opt
# out by carrying the `real_smoke_test` marker.
@pytest.fixture(autouse=True)
def _fast_smoke_test(request, monkeypatch):
    """Patch _run_smoke_test → fast-pass StepLog. Opt out via
    `@pytest.mark.real_smoke_test`."""
    if request.node.get_closest_marker("real_smoke_test"):
        yield
        return
    from backend.manifests.executor import StepLog

    def _fast(_key, _manifest):
        return StepLog(
            name="smoke_test", status="ok",
            message="Smoke test passed (mocked by conftest fixture).",
        )

    monkeypatch.setattr("backend.manifests.executor._run_smoke_test", _fast)
    yield


@pytest.fixture
def test_db(tmp_path: Path):
    """Real SQLite DB with full schema. Isolated per test."""
    db_path = tmp_path / "state.db"
    init_db(db_path)
    _state_mod.configure(db_path)
    yield db_path
    _state_mod.configure(None)


@pytest.fixture
def ready_db(test_db: Path):
    """test_db with platform marked ready and realistic config."""
    with StateDB() as db:
        db.update_platform(
            status="ready",
            domain="test.local",
            config_root=str(test_db.parent / "config"),
            media_root=str(test_db.parent / "media"),
            puid=1000, pgid=1000, timezone="UTC",
            network_name="mediastack", cert_resolver="letsencrypt",
        )
    return test_db


@pytest.fixture
def test_compose_dir(tmp_path: Path):
    """Temp compose directory registered with config."""
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    return compose_dir


@pytest.fixture
def mock_docker_healthy():
    """Docker client that reports all containers as running+healthy."""
    container = MagicMock()
    container.status = "running"
    container.health = "healthy"
    container.container_name = "test_app"
    with patch("backend.manifests.executor.docker_client") as mock:
        mock.get_container.return_value = container
        mock.ports_in_use.return_value = {}
        yield mock


@pytest.fixture
def mock_docker_unhealthy():
    """Docker client that reports containers as running but unhealthy."""
    container = MagicMock()
    container.status = "running"
    container.health = "unhealthy"
    container.container_name = "test_app"
    with patch("backend.manifests.executor.docker_client") as mock:
        mock.get_container.return_value = container
        mock.ports_in_use.return_value = {}
        yield mock


@pytest.fixture
def mock_docker_missing():
    """Docker client that reports containers as absent."""
    with patch("backend.manifests.executor.docker_client") as mock:
        mock.get_container.return_value = None
        mock.ports_in_use.return_value = {}
        yield mock


@pytest.fixture
def mock_compose_success():
    """subprocess.run returns success for docker compose calls."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = "done"
    result.stderr = ""
    with patch("subprocess.run", return_value=result):
        yield result


@pytest.fixture
def mock_compose_failure():
    """subprocess.run returns failure for docker compose calls."""
    result = MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = "Error: image not found"
    with patch("subprocess.run", return_value=result):
        yield result


@pytest.fixture
def wizard_input(tmp_path: Path):
    """Minimal valid WizardInput for testing steps."""
    from backend.platform.wizard import WizardInput
    return WizardInput(
        domain="test.local",
        config_root=str(tmp_path / "config"),
        media_root=str(tmp_path / "media"),
        puid=1000, pgid=1000, timezone="UTC",
    )


# ─────────────────────────────────────────────────────────────────────────────
# FakeDockerClient — controllable Docker substitute for FSM tests
#
# Mirrors the exact interface of backend.core.docker_client so patches are
# drop-in. Tests drive FSM transitions by calling container.set_health().
# No real Docker socket needed — deterministic and instant.
# ─────────────────────────────────────────────────────────────────────────────

import time as _time
from dataclasses import dataclass as _dc, field as _field
from unittest.mock import patch as _patch


@_dc
class FakeContainer:
    """A simulated Docker container whose health can be controlled by tests."""
    container_name: str
    status: str = "running"       # running | exited | paused | restarting | dead
    health: str = "healthy"       # healthy | unhealthy | starting | none
    image: str = "fake/image:latest"
    started_at: float = _field(default_factory=_time.time)
    oom_killed: bool = False
    restart_count: int = 0
    exit_code: int = 0

    def set_health(self, health: str) -> None:
        """Drive an FSM health transition. Tests call this to change state."""
        self.health = health
        if health in ("unhealthy", "missing"):
            self.status = "exited" if health == "missing" else "running"

    def set_oom(self) -> None:
        """Simulate OOM kill."""
        self.oom_killed = True
        self.status = "exited"
        self.health = "none"
        self.exit_code = 137

    def container_info(self):
        """Return a ContainerInfo matching the real docker_client return type."""
        from backend.core.docker_client import ContainerInfo
        return ContainerInfo(
            id=f"fake{self.container_name[:8]:0<8}",
            name=self.container_name,
            image=self.image,
            status=self.status,
            state=self.status,
            health=self.health,
            created=int(self.started_at),
        )

    def runtime_state(self) -> dict:
        """Match _container_runtime_state() output shape."""
        return {
            "restart_count": self.restart_count,
            "exit_code": self.exit_code,
            "oom_killed": self.oom_killed,
            "finished_at": "",
        }


class FakeDockerClient:
    """
    Drop-in replacement for backend.core.docker_client module.

    Implements the full interface used by executor.py, checker.py, and
    health/scheduler.py. Tests add containers and drive health transitions:

        fake = FakeDockerClient()
        c = fake.add_container("sonarr", health="healthy")
        c.set_health("unhealthy")   # drive FSM transition in next health cycle
    """

    def __init__(self):
        self._containers: dict[str, FakeContainer] = {}
        self._ports: dict[int, str] = {}

    def add_container(
        self,
        name: str,
        health: str = "healthy",
        status: str = "running",
        started_at: float | None = None,
    ) -> FakeContainer:
        """Create a simulated container. Returns a handle for state control."""
        c = FakeContainer(
            container_name=name,
            health=health,
            status=status,
            started_at=started_at or _time.time(),
        )
        self._containers[name] = c
        return c

    def remove_container(self, name: str) -> None:
        self._containers.pop(name, None)

    # ── docker_client module interface ────────────────────────────────────────

    def get_container(self, name: str):
        c = self._containers.get(name)
        return c.container_info() if c else None

    def list_containers(self, include_stopped: bool = False):
        return [
            c.container_info()
            for c in self._containers.values()
            if include_stopped or c.status == "running"
        ]

    def ports_in_use(self) -> dict[int, str]:
        return dict(self._ports)

    def container_logs(self, name: str, tail: int = 100) -> str:
        if name not in self._containers:
            from backend.core.docker_client import DockerError
            raise DockerError(f"Container '{name}' not found.")
        return f"[fake logs for {name}]\n"

    def network_exists(self, name: str) -> bool:
        return True  # assume network always exists in tests

    def _runtime_state(self, name: str) -> dict:
        """Used by checker.py _container_runtime_state() shim."""
        c = self._containers.get(name)
        return c.runtime_state() if c else {}

    def _started_at(self, name: str) -> float | None:
        """Used by checker.py _container_started_at() shim."""
        c = self._containers.get(name)
        return c.started_at if c else None


@pytest.fixture
def fake_docker():
    """
    FakeDockerClient wired into all call sites.

    Patches:
      - backend.manifests.executor.docker_client
      - backend.health.checker._container_runtime_state (subprocess call)
      - backend.health.checker._in_startup_grace (subprocess call)
      - backend.health.checker._container_started_at (subprocess call)

    Usage:
        def test_something(fake_docker, test_db):
            c = fake_docker.add_container("sonarr", health="healthy")
            # run code...
            c.set_health("unhealthy")
            # run code again...
    """
    client = FakeDockerClient()

    def _fake_runtime_state(container_name: str) -> dict:
        return client._runtime_state(container_name)

    def _fake_started_at(container_name: str):
        return client._started_at(container_name)

    def _fake_in_grace(container_name: str, grace_s: int):
        started = client._started_at(container_name)
        if started is None:
            return False, -1.0
        age = _time.time() - started
        return age < grace_s, age

    with _patch("backend.manifests.executor.docker_client", client), \
         _patch("backend.health.checker._container_runtime_state",
                side_effect=_fake_runtime_state), \
         _patch("backend.health.checker._container_started_at",
                side_effect=_fake_started_at), \
         _patch("backend.health.checker._in_startup_grace",
                side_effect=_fake_in_grace):
        yield client


@pytest.fixture
def fake_docker_with_db(fake_docker, test_db):
    """Convenience: FakeDockerClient + isolated DB in one fixture."""
    return fake_docker, test_db


# ─────────────────────────────────────────────────────────────────────────────
# HypothesisReporter — writes property test failures to data/ for LLM ingestion
#
# When a Hypothesis test fails, the falsifying example is written to
# data/hypothesis_failures.json. _assemble_improve_context() picks this up
# automatically on the next ms-audit --improve call.
# ─────────────────────────────────────────────────────────────────────────────

import json as _json
import time as _time
from pathlib import Path as _Path


def pytest_runtest_logreport(report):
    """Hook: capture Hypothesis failure details on test failure."""
    if not report.failed:
        return

    # Only capture Hypothesis property test failures
    if not (report.longrepr and "Falsifying example" in str(report.longrepr)):
        return

    data_dir = _Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    failures_file = data_dir / "hypothesis_failures.json"

    try:
        existing = _json.loads(failures_file.read_text()) if failures_file.exists() else {}
    except Exception:
        existing = {}

    findings = existing.get("findings", [])
    longrepr_str = str(report.longrepr)

    # Extract the falsifying example
    example = ""
    for line in longrepr_str.splitlines():
        if "Falsifying example" in line:
            example = line.strip()
            break

    # Extract assertion message
    message = ""
    for line in longrepr_str.splitlines():
        if "AssertionError" in line:
            message = line.strip().replace("AssertionError: ", "")[:150]
            break

    findings.append({
        "test": report.nodeid,
        "input": example[:200],
        "message": message,
        "timestamp": int(_time.time()),
    })

    # Keep only the 20 most recent
    findings = findings[-20:]

    failures_file.write_text(_json.dumps({
        "tool": "hypothesis",
        "generated_at": int(_time.time()),
        "findings": findings,
    }, indent=2))
