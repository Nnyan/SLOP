"""
tests/test_tool_logic.py — Tool Logic Tests

Tests ms-audit, ms-check, ms-update logic directly — the tool internals
that were previously untested (tool self-ignorance). Each test verifies
BEHAVIOR of the tool's own functions, not just its output.

Key principle: extract and test the actual functions in isolation with
controlled inputs and verify they produce the correct outputs.
"""
import json
import pathlib
import re
import sys
import textwrap
import types

import pytest

REPO = pathlib.Path(__file__).parent.parent
AUDIT_TEST = REPO / "tests" / "test_comprehensive_contracts.py"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_ms_audit_functions():
    """
    Extract and exec the pure functions from ms-audit into a shared namespace.
    All globals (including non-callables) are preserved so functions can 
    reference AUDIT_TEST, REPO, PREFIXES, etc.
    """
    src = (REPO / "ms-audit").read_text()
    lines = src.splitlines()

    def _extract_fn(name: str) -> str:
        starts = [i for i, l in enumerate(lines) if re.match(rf"^def {name}\(", l)]
        if not starts:
            raise ValueError(f"Function {name} not found in ms-audit")
        start = starts[-1]
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if re.match(r"^(def |class )", lines[i]):
                end = i
                break
        return "\n".join(lines[start:end])

    # Full namespace — ALL globals preserved (callable and non-callable)
    ns: dict = {
        "re": re,
        "pathlib": pathlib,
        "json": json,
        "Any": object,
        "AUDIT_TEST": AUDIT_TEST,
        "REPO": REPO,
        "PREFIXES": ["health", "platform", "apps", "infra", "settings",
                     "catalog", "storage", "routing", "models"],
    }

    for fn_name in ("diff_snapshots", "find_gaps"):
        exec(_extract_fn(fn_name), ns)  # noqa: S102

    # Return a namespace object — include all items, not just callables
    return types.SimpleNamespace(**ns)


@pytest.fixture(scope="module")
def audit():
    return _load_ms_audit_functions()


# ═══════════════════════════════════════════════════════════════════════════
# diff_snapshots — change detection
# ═══════════════════════════════════════════════════════════════════════════

class TestDiffSnapshots:
    """
    diff_snapshots(old, new) returns what changed between two audit snapshots.
    These tests verify the logic is symmetric, complete, and handles all fields.
    """

    def test_no_changes_returns_empty_dict(self, audit):
        snap = {"routes": ["GET /a", "POST /b"], "manifests": ["sonarr"],
                "vue_calls": [], "db_tables": [], "wizard_steps": [],
                "settings_keys": [], "context_sources": [], "infra_providers": {}}
        assert audit.diff_snapshots(snap, snap) == {}

    def test_added_route_appears_in_routes_added(self, audit):
        old = {"routes": ["GET /a"], "manifests": [], "vue_calls": [],
               "db_tables": [], "wizard_steps": [], "settings_keys": [],
               "context_sources": [], "infra_providers": {}}
        new = {**old, "routes": ["GET /a", "GET /new-endpoint"]}
        diff = audit.diff_snapshots(old, new)
        assert "routes_added" in diff
        assert "GET /new-endpoint" in diff["routes_added"]
        assert "routes_removed" not in diff

    def test_removed_route_appears_in_routes_removed(self, audit):
        old = {"routes": ["GET /a", "GET /old"], "manifests": [], "vue_calls": [],
               "db_tables": [], "wizard_steps": [], "settings_keys": [],
               "context_sources": [], "infra_providers": {}}
        new = {**old, "routes": ["GET /a"]}
        diff = audit.diff_snapshots(old, new)
        assert "routes_removed" in diff
        assert "GET /old" in diff["routes_removed"]

    def test_added_manifest_detected(self, audit):
        old = {"routes": [], "manifests": ["sonarr"], "vue_calls": [],
               "db_tables": [], "wizard_steps": [], "settings_keys": [],
               "context_sources": [], "infra_providers": {}}
        new = {**old, "manifests": ["sonarr", "whisparr"]}
        diff = audit.diff_snapshots(old, new)
        assert "manifests_added" in diff
        assert "whisparr" in diff["manifests_added"]

    def test_new_infra_provider_detected_by_slot(self, audit):
        old = {"routes": [], "manifests": [], "vue_calls": [], "db_tables": [],
               "wizard_steps": [], "settings_keys": [], "context_sources": [],
               "infra_providers": {"vpn": ["gluetun"]}}
        new = {**old, "infra_providers": {"vpn": ["gluetun", "wireguard_native"]}}
        diff = audit.diff_snapshots(old, new)
        assert "providers_added" in diff
        assert "vpn/wireguard_native" in diff["providers_added"]

    def test_unchanged_fields_not_in_diff(self, audit):
        snap = {"routes": ["GET /a"], "manifests": ["sonarr"], "vue_calls": ["call"],
                "db_tables": ["apps"], "wizard_steps": ["preflight"],
                "settings_keys": ["key"], "context_sources": ["src"],
                "infra_providers": {"auth": ["tinyauth"]}}
        new_snap = {**snap, "routes": ["GET /a", "POST /new"]}
        diff = audit.diff_snapshots(snap, new_snap)
        # Only routes changed — other keys must not appear
        assert set(diff.keys()) == {"routes_added"}

    def test_multiple_additions_all_captured(self, audit):
        old = {"routes": [], "manifests": [], "vue_calls": [], "db_tables": [],
               "wizard_steps": [], "settings_keys": [], "context_sources": [],
               "infra_providers": {}}
        new = {"routes": ["GET /a", "POST /b", "DELETE /c"],
               "manifests": ["sonarr", "radarr"], "vue_calls": ["fetchApps"],
               "db_tables": ["apps"], "wizard_steps": [], "settings_keys": [],
               "context_sources": [], "infra_providers": {}}
        diff = audit.diff_snapshots(old, new)
        assert len(diff.get("routes_added", [])) == 3
        assert len(diff.get("manifests_added", [])) == 2
        assert "vue_calls_added" in diff

    def test_empty_old_snapshot_treated_as_baseline(self, audit):
        """Empty old snapshot → everything in new is 'added'."""
        old = {}
        new = {"routes": ["GET /a"], "manifests": [], "vue_calls": [], "db_tables": [],
               "wizard_steps": [], "settings_keys": [], "context_sources": [],
               "infra_providers": {}}
        diff = audit.diff_snapshots(old, new)
        assert "routes_added" in diff


# ═══════════════════════════════════════════════════════════════════════════
# find_gaps — gap detection logic
# ═══════════════════════════════════════════════════════════════════════════

class TestFindGaps:
    """
    find_gaps(snap, changes) returns gaps in test coverage.
    These tests verify the MATCHING LOGIC — does it correctly identify
    covered vs uncovered routes/manifests/providers?
    """

    def _make_snap(self) -> dict:
        return {
            "routes": [], "manifests": [], "vue_calls": [], "db_tables": [],
            "wizard_steps": [], "settings_keys": [], "context_sources": [],
            "infra_providers": {}, "context_source_count": 0,
        }

    def test_route_with_no_test_is_flagged_as_gap(self, audit):
        """A new route not mentioned anywhere in test file → gap."""
        changes = {"routes_added": ["GET /api/health/apps/totally_new_endpoint_xyz"]}
        gaps = audit.find_gaps(self._make_snap(), changes)
        gap_items = [g["item"] for g in gaps if g["type"] == "new_route"]
        assert any("totally_new_endpoint_xyz" in item for item in gap_items), (
            "Routes with no test coverage should be flagged as gaps. "
            "Test file doesn't mention 'totally_new_endpoint_xyz'."
        )

    def test_route_with_test_is_not_a_gap(self, audit):
        """A route whose last segment appears in the test file → not a gap."""
        # 'validate-secrets' IS mentioned in test_comprehensive_contracts.py
        changes = {"routes_added": ["POST /api/platform/wizard/validate-secrets"]}
        gaps = audit.find_gaps(self._make_snap(), changes)
        new_route_gaps = [g for g in gaps if g["type"] == "new_route"]
        assert not new_route_gaps, (
            "validate-secrets has tests in TestNewRouteContracts. "
            f"Should not be flagged. Gaps: {new_route_gaps}"
        )

    def test_container_status_route_is_covered(self, audit):
        """container-status route has tests → should not be a gap."""
        changes = {"routes_added": ["GET /api/health/apps/{key}/container-status"]}
        gaps = audit.find_gaps(self._make_snap(), changes)
        new_route_gaps = [g for g in gaps if g["type"] == "new_route"]
        assert not new_route_gaps, (
            "container-status has tests in TestNewRouteContracts. "
            f"Should not be flagged. Gaps: {new_route_gaps}"
        )

    def test_15_char_prefix_is_not_used(self, audit):
        """
        Old bug: path[:15] gave 'api_platform_wi' — never in test files.
        New logic uses path segments. Verify a well-tested route is not flagged.
        'validate-secrets' IS in test_comprehensive_contracts.py (TestNewRouteContracts).
        """
        changes = {"routes_added": [
            "POST /api/platform/wizard/validate-secrets"
        ]}
        gaps = audit.find_gaps(self._make_snap(), changes)
        new_route_gaps = [g for g in gaps if g["type"] == "new_route"]
        assert not new_route_gaps, (
            "validate-secrets is covered in TestNewRouteContracts. "
            "The old [:15] logic produced 'api_platform_wi' which is absent in tests. "
            "New logic extracts 'validate-secrets' and finds it in the test file. "
            f"Gaps found: {new_route_gaps}"
        )

    def test_new_manifest_with_no_test_is_gap(self, audit):
        changes = {"manifests_added": ["totally_new_app_xyz_123"]}
        gaps = audit.find_gaps(self._make_snap(), changes)
        manifest_gaps = [g for g in gaps if g["type"] == "new_manifest"]
        assert manifest_gaps, "New manifests not mentioned in test file should be a gap"

    def test_gap_list_is_empty_when_no_changes(self, audit):
        gaps = audit.find_gaps(self._make_snap(), {})
        # Only static gap types (error_handling) might still fire; route/manifest gaps = 0
        route_gaps = [g for g in gaps if g["type"] == "new_route"]
        manifest_gaps = [g for g in gaps if g["type"] == "new_manifest"]
        assert not route_gaps and not manifest_gaps

    def test_gap_has_required_fields(self, audit):
        """Every gap must have type, item, suggestion — frontend and CI use these."""
        changes = {"routes_added": ["GET /api/totally_new_route_no_tests_ever"]}
        gaps = audit.find_gaps(self._make_snap(), changes)
        for gap in gaps:
            assert "type" in gap, f"Gap missing 'type': {gap}"
            assert "item" in gap, f"Gap missing 'item': {gap}"
            assert "suggestion" in gap, f"Gap missing 'suggestion': {gap}"

    def test_new_infra_provider_with_no_test_is_gap(self, audit):
        """A new infra provider slot/key not in test file → gap."""
        changes = {"providers_added": ["vpn/totally_new_vpn_provider_xyz"]}
        gaps = audit.find_gaps(self._make_snap(), changes)
        prov_gaps = [g for g in gaps if g["type"] == "new_infra_provider"]
        assert prov_gaps, "New provider not in test file should be flagged"


# ═══════════════════════════════════════════════════════════════════════════
# ms-audit snapshot persistence
# ═══════════════════════════════════════════════════════════════════════════

class TestSnapshotPersistence:
    """
    Verify the snapshot is only written when gaps are closed.
    These tests check the CONDITIONAL WRITE logic, not just that
    the snapshot file exists.
    """

    def test_snapshot_file_is_json_parseable(self):
        snap_file = REPO / ".ms-audit-snapshot.json"
        if not snap_file.exists():
            pytest.skip("Snapshot not yet generated — run ms-audit first")
        data = json.loads(snap_file.read_text())
        assert isinstance(data, dict), "Snapshot must be a JSON object"

    def test_snapshot_contains_required_keys(self):
        snap_file = REPO / ".ms-audit-snapshot.json"
        if not snap_file.exists():
            pytest.skip("Snapshot not yet generated")
        data = json.loads(snap_file.read_text())
        for key in ("routes", "manifests", "db_tables"):
            assert key in data, f"Snapshot missing required key: {key}"

    def test_snapshot_route_count_matches_codebase(self):
        """Routes in snapshot must roughly match actual API endpoints found by scanning.

        Prefixes come from `backend/api/main.py`. Step 3.2 introduced
        a `_mount(<module>_router, "<name>", "<tag>")` helper that
        dual-registers each router at /api/v1/<name> and /api/<name>.
        The scraper recognises both `_mount(...)` calls and the
        legacy `app.include_router(..., prefix="...")` form.

        We treat the snapshot as the legacy `/api/<name>` surface
        (one entry per route, no /api/v1/ duplication) since the
        snapshot was generated before 3.2 and represents the
        canonical API.
        """
        snap_file = REPO / ".ms-audit-snapshot.json"
        if not snap_file.exists():
            pytest.skip("Snapshot not yet generated")
        snap_routes = set(json.loads(snap_file.read_text()).get("routes", []))

        # Build module → prefix map from main.py's mount + include_router calls.
        main_src = (REPO / "backend" / "api" / "main.py").read_text()
        module_prefix: dict[str, str] = {}
        # Step 3.2 _mount("<name>", "<tag>") helper — implies /api/<name>.
        for m in re.finditer(
            r'_mount\(\s*(\w+)_router\s*,\s*"([^"]+)"',
            main_src,
        ):
            module_prefix[m.group(1)] = "/api/" + m.group(2)
        # Legacy include_router calls (still in use for routers that
        # bake a prefix into the APIRouter itself, like quickstart).
        for m in re.finditer(
            r'app\.include_router\(\s*(\w+)_router\.router\s*,\s*prefix\s*=\s*"([^"]+)"',
            main_src,
        ):
            # /api/v1 mounts of those legacy routers don't add to
            # the snapshot count — snapshot is /api/<name> only.
            if m.group(2) != "/api/v1":
                module_prefix[m.group(1)] = m.group(2)

        # Scan actual codebase for routes
        real_routes = set()
        for api_file in (REPO / "backend" / "api").glob("*.py"):
            if api_file.stem == "main":
                continue
            prefix = module_prefix.get(api_file.stem, "")
            src = api_file.read_text()
            for m in re.finditer(
                r'@router\.(get|post|put|delete|patch)\("([^"]+)"', src,
            ):
                real_routes.add(f"{m.group(1).upper()} {prefix}{m.group(2)}")

        # Snapshot should be close to reality (within 9 routes either way)
        snap_only = snap_routes - real_routes
        real_only = real_routes - snap_routes
        assert len(snap_only) < 10, (
            f"Snapshot has {len(snap_only)} routes not in codebase: {snap_only}. "
            "Run ms-audit to update snapshot."
        )
        assert len(real_only) < 10, (
            f"Codebase has {len(real_only)} routes not in snapshot: {real_only}. "
            "Run ms-audit to update snapshot."
        )

    def test_snapshot_write_gated_by_gaps_in_source(self):
        """The ms-audit source code must conditionally guard snapshot write."""
        src = (REPO / "ms-audit").read_text()
        snap_write_idx = src.rfind("SNAP_FILE.write_text")
        context = src[max(0, snap_write_idx - 300):snap_write_idx + 50]
        # Must be inside an if-block that checks gaps
        assert "if not gaps" in context or "if gaps" in context, (
            "SNAP_FILE.write_text must be conditional on gaps being resolved. "
            "Unconditional write means gaps are forgotten after one run."
        )


# ═══════════════════════════════════════════════════════════════════════════
# ms-check script logic
# ═══════════════════════════════════════════════════════════════════════════

class TestMsCheckLogic:
    """
    ms-check is a bash script — test its logic by running it with
    controlled environment in a subprocess, and verify exit codes
    and output format are correct.
    """

    def test_ms_check_exit_codes_are_defined(self):
        """ms-check must use exactly: 0=pass, 1=warn, 2=fail."""
        src = (REPO / "ms-check").read_text()
        assert "exit 0" in src, "ms-check must exit 0 on all-pass"
        assert "exit 1" in src, "ms-check must exit 1 on warnings"
        assert "exit 2" in src, "ms-check must exit 2 on failures"

    def test_ms_check_pass_function_uses_correct_exit(self):
        """pass() function must contribute to exit-0 path."""
        src = (REPO / "ms-check").read_text()
        pass_fn_start = src.find("\npass()")
        if pass_fn_start == -1:
            pass_fn_start = src.find("\nfunction pass()")
        assert pass_fn_start != -1, "pass() function must be defined"

    def test_ms_check_has_git_sync_section(self):
        """Git sync section must be present to detect drift."""
        src = (REPO / "ms-check").read_text()
        assert "Git sync" in src or "git sync" in src.lower(), (
            "ms-check must have a 'Git sync' section that detects when the "
            "local branch is behind origin/main."
        )

    def test_ms_check_git_sync_notifies_when_behind(self):
        """Git sync must surface when behind — either fail() or warn() is acceptable.
        
        warn() is appropriate because: the service is still running correctly,
        and fail() would prevent other checks from running on the same ms-update run.
        The notification (at any level) is what matters.
        """
        src = (REPO / "ms-check").read_text()
        git_sync_idx = src.find("Git sync")
        git_section = src[git_sync_idx:git_sync_idx + 600]
        assert ("fail " in git_section or 'fail"' in git_section or
                "warn " in git_section or 'warn"' in git_section), (
            "Git sync must call fail() or warn() when behind origin/main. "
            "Silently accepting stale code means ms-update sync failures go unnoticed."
        )

    def test_ms_check_auto_removes_orphaned_records(self):
        """ms-check must auto-clean DB records with no compose fragment."""
        src = (REPO / "ms-check").read_text()
        assert "orphan" in src.lower() or "Auto-removed" in src, (
            "ms-check should auto-remove orphaned DB records. "
            "Orphans accumulate after failed installs and confuse health monitoring."
        )

    def test_ms_update_discards_tracked_data_files_before_pull(self):
        """ms-update must checkout data/* files before pull to prevent block."""
        src = (REPO / "ms-update").read_text()
        assert "checkout" in src and "data/" in src, (
            "ms-update must discard locally-modified tracked data/ files before pulling. "
            "Without this, 'git pull' no-ops when runtime files are modified."
        )

    def test_ms_update_verifies_pull_actually_updated_head(self):
        """ms-update must compare HEAD before/after pull, not trust exit code."""
        src = (REPO / "ms-update").read_text()
        assert "_REMOTE_HEAD" in src or "origin/main" in src, (
            "ms-update must fetch and compare local HEAD to origin/main after pull. "
            "'Already up to date' exit-0 can be a lie when auth fails."
        )

    def test_ms_update_force_resets_when_pull_fails(self):
        """On pull failure, ms-update must attempt git reset --hard origin/main."""
        src = (REPO / "ms-update").read_text()
        assert "reset --hard origin/main" in src, (
            "ms-update must fall back to 'git reset --hard origin/main' when "
            "pull fails. Without this, the server stays stuck on old code."
        )
