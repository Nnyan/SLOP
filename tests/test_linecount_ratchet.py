"""Unit tests for tools/check_linecount.py (wave S-45-RATCHET).

Every test builds a fake repo tree under `tmp_path` so the tests don't depend
on the real repo's file state. The tool is imported directly so we can
exercise the public functions (`run_check`, `run_snapshot`, `run_update_shrunk`,
`classify`) without spawning subprocesses.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader — pull in tools/check_linecount.py without polluting sys.path
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "tools" / "check_linecount.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_linecount", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_linecount"] = mod
    spec.loader.exec_module(mod)
    return mod


ratchet = _load_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(root: Path, rel: str, lines: int) -> Path:
    """Write a file with `lines` newline-terminated lines under `root`."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    # `lines` lines means `lines` "\n" terminators.
    p.write_text("x\n" * lines)
    return p


def _read_baseline(root: Path) -> dict:
    return json.loads((root / ratchet.BASELINE_FILENAME).read_text())


# ---------------------------------------------------------------------------
# Category resolution + precedence
# ---------------------------------------------------------------------------

class TestClassify:
    def test_production_code(self):
        assert ratchet.classify("backend/core/agent.py") == "production_code"
        assert ratchet.classify("backend/health/checker.py") == "production_code"
        assert ratchet.classify("backend/manifests/executor.py") == "production_code"
        assert ratchet.classify("backend/platform/wizard.py") == "production_code"
        assert ratchet.classify("backend/infra/foo.py") == "production_code"
        assert ratchet.classify("backend/agent/x.py") == "production_code"

    def test_api_routers(self):
        assert ratchet.classify("backend/api/apps.py") == "api_routers"
        assert ratchet.classify("backend/api/sub/nested.py") == "api_routers"

    def test_api_routers_precedence_over_production(self):
        # backend/api/** must NOT be swallowed by any broader backend rule.
        assert ratchet.classify("backend/api/health.py") == "api_routers"

    def test_vue_views(self):
        assert ratchet.classify("frontend/src/views/SetupView.vue") == "vue_views"
        assert ratchet.classify("frontend/src/views/sub/Other.vue") == "vue_views"

    def test_vue_views_precedence_over_frontend_other(self):
        assert ratchet.classify("frontend/src/views/X.vue") == "vue_views"

    def test_frontend_other(self):
        assert ratchet.classify("frontend/src/composables/useFoo.ts") == "frontend_other"
        assert ratchet.classify("frontend/src/components/Bar.vue") == "frontend_other"
        assert ratchet.classify("frontend/src/api/client.ts") == "frontend_other"

    def test_tests_top_level(self):
        assert ratchet.classify("tests/test_foo.py") == "tests"
        assert ratchet.classify("tests/integration/test_bar.py") == "tests"

    def test_tests_precedence_over_cli_installer(self):
        # installer/tests/** must be classified as tests, NOT cli_installer.
        assert ratchet.classify("installer/tests/test_uninstall.py") == "tests"
        assert ratchet.classify("installer/tests/sub/test_x.py") == "tests"

    def test_cli_installer(self):
        assert ratchet.classify("cli/main.py") == "cli_installer"
        assert ratchet.classify("installer/uninstall.py") == "cli_installer"

    def test_uncategorized(self):
        # Non-source extensions (e.g. .md) still return None — not in INCLUDED_EXTENSIONS.
        assert ratchet.classify("docs/readme.md") is None
        # .py files outside named categories fall through to the catch-all "uncategorized".
        # (batch-11 S8: *.py is a catch-all pattern so classify() never returns None
        # for a .py path that reaches the walker.)
        assert ratchet.classify("scripts/random.py") == "uncategorized"
        assert ratchet.classify("backend/scripts/deploy.py") == "uncategorized"

    def test_uncategorized_sh_yaml(self):
        # .sh and .yaml files are now included (batch-11 S8) and fall to uncategorized.
        assert ratchet.classify("deploy.sh") == "uncategorized"
        assert ratchet.classify("tools/cleanup-helpers.sh") == "uncategorized"
        assert ratchet.classify("installer/readiness_manifest.yaml") == "uncategorized"
        assert ratchet.classify("catalog/apps/dumb.yaml") == "uncategorized"
        assert ratchet.classify("migrations/003_sync.py") == "uncategorized"
        assert ratchet.classify("ms-test.py") == "uncategorized"


# ---------------------------------------------------------------------------
# Snapshot + Check
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_lists_only_over_cap(self, tmp_path: Path):
        # Production-code cap is 500. Build one file over, one under.
        _write(tmp_path, "backend/core/big.py", 600)
        _write(tmp_path, "backend/core/small.py", 100)
        ratchet.run_snapshot(tmp_path)
        data = _read_baseline(tmp_path)
        paths = {f["path"] for f in data["files"]}
        assert paths == {"backend/core/big.py"}
        assert data["files"][0]["lines"] == 600
        assert data["files"][0]["category"] == "production_code"

    def test_snapshot_sorted_by_path(self, tmp_path: Path):
        _write(tmp_path, "backend/core/zzz.py", 600)
        _write(tmp_path, "backend/core/aaa.py", 700)
        ratchet.run_snapshot(tmp_path)
        data = _read_baseline(tmp_path)
        assert [f["path"] for f in data["files"]] == [
            "backend/core/aaa.py", "backend/core/zzz.py",
        ]

    def test_snapshot_deterministic_byte_identical(self, tmp_path: Path):
        _write(tmp_path, "backend/core/big.py", 600)
        ratchet.run_snapshot(tmp_path)
        first = (tmp_path / ratchet.BASELINE_FILENAME).read_text()
        ratchet.run_snapshot(tmp_path)
        second = (tmp_path / ratchet.BASELINE_FILENAME).read_text()
        assert first == second

    def test_snapshot_skips_excluded_dirs(self, tmp_path: Path):
        _write(tmp_path, "node_modules/some/big.py", 600)
        _write(tmp_path, ".venv/lib/big.py", 600)
        _write(tmp_path, "__pycache__/big.py", 600)
        ratchet.run_snapshot(tmp_path)
        data = _read_baseline(tmp_path)
        assert data["files"] == []


class TestCheckMode:
    def test_clean_tree_passes(self, tmp_path: Path):
        _write(tmp_path, "backend/core/small.py", 100)
        # No baseline → check mode reads empty baseline default.
        rc = ratchet.run_check(tmp_path, out=io.StringIO())
        assert rc == 0

    def test_new_file_over_cap_fails(self, tmp_path: Path):
        # 510-line file in production_code (cap=500) — no baseline entry.
        _write(tmp_path, "backend/core/new_big.py", 510)
        buf = io.StringIO()
        rc = ratchet.run_check(tmp_path, out=buf)
        assert rc == 1
        text = buf.getvalue()
        assert "backend/core/new_big.py:510 / 500 (production_code)" in text

    def test_new_api_router_over_cap_fails(self, tmp_path: Path):
        # api_routers cap is 800.
        _write(tmp_path, "backend/api/huge.py", 850)
        rc = ratchet.run_check(tmp_path, out=io.StringIO())
        assert rc == 1

    def test_new_vue_view_over_cap_fails(self, tmp_path: Path):
        # vue_views cap is 600.
        _write(tmp_path, "frontend/src/views/Huge.vue", 700)
        buf = io.StringIO()
        rc = ratchet.run_check(tmp_path, out=buf)
        assert rc == 1
        assert "frontend/src/views/Huge.vue:700 / 600 (vue_views)" in buf.getvalue()

    def test_baselined_grew_fails(self, tmp_path: Path):
        # Seed a baseline at 700 then grow the file to 800.
        _write(tmp_path, "backend/core/legacy.py", 700)
        ratchet.run_snapshot(tmp_path)
        _write(tmp_path, "backend/core/legacy.py", 800)
        buf = io.StringIO()
        rc = ratchet.run_check(tmp_path, out=buf)
        assert rc == 1
        assert "backend/core/legacy.py:800 / 700 (production_code)" in buf.getvalue()

    def test_baselined_equal_passes(self, tmp_path: Path):
        _write(tmp_path, "backend/core/legacy.py", 700)
        ratchet.run_snapshot(tmp_path)
        rc = ratchet.run_check(tmp_path, out=io.StringIO())
        assert rc == 0

    def test_baselined_shrunk_passes_default(self, tmp_path: Path):
        # Seed baseline at 700, then shrink to 650 — should pass default check.
        _write(tmp_path, "backend/core/legacy.py", 700)
        ratchet.run_snapshot(tmp_path)
        _write(tmp_path, "backend/core/legacy.py", 650)
        rc = ratchet.run_check(tmp_path, out=io.StringIO())
        assert rc == 0
        # Baseline file unchanged in default mode.
        data = _read_baseline(tmp_path)
        legacy_entry = [f for f in data["files"] if f["path"] == "backend/core/legacy.py"][0]
        assert legacy_entry["lines"] == 700

    def test_tests_over_1000_warns_passes(self, tmp_path: Path):
        _write(tmp_path, "tests/test_huge.py", 1500)
        buf = io.StringIO()
        rc = ratchet.run_check(tmp_path, out=buf)
        assert rc == 0
        assert "WARNING" in buf.getvalue()
        assert "tests/test_huge.py:1500" in buf.getvalue()


# ---------------------------------------------------------------------------
# --update-shrunk
# ---------------------------------------------------------------------------

class TestUpdateShrunk:
    def test_shrunk_updates_baseline(self, tmp_path: Path):
        _write(tmp_path, "backend/core/legacy.py", 700)
        ratchet.run_snapshot(tmp_path)
        _write(tmp_path, "backend/core/legacy.py", 650)

        rc = ratchet.run_update_shrunk(tmp_path, out=io.StringIO())
        assert rc == 0
        data = _read_baseline(tmp_path)
        legacy = [f for f in data["files"] if f["path"] == "backend/core/legacy.py"][0]
        assert legacy["lines"] == 650

    def test_shrunk_under_cap_removed_from_baseline(self, tmp_path: Path):
        # production_code cap = 500. Shrink to 400 → drop from baseline.
        _write(tmp_path, "backend/core/legacy.py", 700)
        ratchet.run_snapshot(tmp_path)
        _write(tmp_path, "backend/core/legacy.py", 400)

        rc = ratchet.run_update_shrunk(tmp_path, out=io.StringIO())
        assert rc == 0
        data = _read_baseline(tmp_path)
        assert all(f["path"] != "backend/core/legacy.py" for f in data["files"])

    def test_grew_kept_at_baseline_value(self, tmp_path: Path):
        # update-shrunk MUST NOT raise the baseline for files that grew.
        _write(tmp_path, "backend/core/legacy.py", 700)
        ratchet.run_snapshot(tmp_path)
        _write(tmp_path, "backend/core/legacy.py", 800)

        ratchet.run_update_shrunk(tmp_path, out=io.StringIO())
        data = _read_baseline(tmp_path)
        legacy = [f for f in data["files"] if f["path"] == "backend/core/legacy.py"][0]
        # Baseline still 700 — subsequent check will then fail because file is at 800.
        assert legacy["lines"] == 700

    def test_deleted_file_removed_from_baseline(self, tmp_path: Path):
        path = _write(tmp_path, "backend/core/legacy.py", 700)
        ratchet.run_snapshot(tmp_path)
        path.unlink()

        ratchet.run_update_shrunk(tmp_path, out=io.StringIO())
        data = _read_baseline(tmp_path)
        assert all(f["path"] != "backend/core/legacy.py" for f in data["files"])


# ---------------------------------------------------------------------------
# Line counting semantics — spec is literal
# ---------------------------------------------------------------------------

def test_line_count_uses_splitlines(tmp_path: Path):
    # The spec literally says: len(file.read_text(errors='ignore').splitlines())
    p = tmp_path / "f.py"
    p.write_text("a\nb\nc")  # No trailing newline → still 3 lines per splitlines.
    assert ratchet.count_lines(p) == 3
    p.write_text("a\nb\nc\n")
    assert ratchet.count_lines(p) == 3
    p.write_text("")
    assert ratchet.count_lines(p) == 0
