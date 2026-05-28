"""Tests for ms-rule-contract (ADR 0012 Rule-Addition Contract).

Step 2.3.d: covers rule-addition with all companions present (passes),
            and rule-addition with each individual companion missing (fails
            with a specific diagnostic message).
"""
from __future__ import annotations

import json
import runpy
import subprocess
import types
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_TOOL = REPO / "ms-rule-contract"

TODAY = date.today().isoformat()


def _load_tool():
    """Load ms-rule-contract as a module. runpy.run_path sets __file__ correctly."""
    g = runpy.run_path(str(_TOOL))
    return types.SimpleNamespace(**g)


@pytest.fixture()
def tool():
    return _load_tool()


# ── Synthetic content helpers ──────────────────────────────────────────────

RULE_ID = "5.99"  # synthetic ID; won't collide with any real rule
RULE_LABEL = "Synthetic Test Rule"
TEST_FN = "test_synthetic_rule_behavior"
TEST_FILE = "tests/test_rule_contract.py"


def _make_cr(include_heading=True, title=RULE_LABEL, include_section8=True, s8_date=TODAY):
    """Build a minimal CORE_RULES.md with optional rule heading and Section 8 row."""
    heading = f"### {RULE_ID} {title}\n\nSome description.\n\n" if include_heading else ""
    s8_row = (f"| {s8_date} | v9.99 — added Rule {RULE_ID} test placeholder |\n"
              if include_section8 else "")
    return (
        f"{heading}"
        "## Section 8 — Version History\n\n"
        "| Date | Change |\n"
        "|---|---|\n"
        f"{s8_row}"
    )


def _make_cov(include_entry=True, label=RULE_LABEL, include_test_fn=True):
    """Build minimal ms-coverage RULES list content."""
    if not include_entry:
        return "RULES: list[dict] = [\n]\n"
    test_fields = (
        f'        "test_fn": "{TEST_FN}",\n'
        f'        "test_file": "{TEST_FILE}",\n'
    ) if include_test_fn else ""
    return (
        "RULES: list[dict] = [\n"
        "    {\n"
        f'        "id": "{RULE_ID}",\n'
        f'        "label": "{label}",\n'
        '        "risk": "high",\n'
        '        "file": "ms-rule-contract",\n'
        f"{test_fields}"
        "    },\n"
        "]\n"
    )


def _make_map(include_node=True, rule_count=1):
    """Build minimal coverage_map.json content."""
    nodes = []
    if include_node:
        nodes.append({
            "id": f"rule:{RULE_ID}",
            "kind": "rule",
            "label": RULE_LABEL,
            "covered": True,
            "risk": "high",
        })
    return json.dumps({"nodes": nodes, "summary": {}})


def _make_snap(count=1, include_label=True):
    """Build minimal snapshot content with the rule count and label."""
    label_line = f"  ✓ [high] {RULE_LABEL}\n" if include_label else ""
    return (
        "# serializer version: 1\n"
        "# name: test_ms_enforce_list_rules\n"
        "  '''\n"
        "\n"
        f"    Active Core Rules ({count} total)\n"
        "\n"
        f"{label_line}"
        "  '''\n"
    )


# ── All companions present ─────────────────────────────────────────────────

class TestAllCompanionsPresent:
    def test_passes_with_all_companions(self, tool, monkeypatch):
        """run_companion_checks returns 0 errors when all C1-C5 are satisfied."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, warnings = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(),
            _make_cov(),
            _make_map(),
            _make_snap(),
        )
        assert errors == [], f"expected no errors, got: {errors}"

    def test_c5_warns_when_test_fn_missing(self, tool, monkeypatch):
        """C5 produces a warning (not an error) when test_fn is absent."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: False)

        errors, warnings = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(),
            _make_cov(),
            _make_map(),
            _make_snap(),
        )
        assert errors == []
        assert any("C5" in w for w in warnings)
        assert any(TEST_FN in w for w in warnings)


# ── C1: heading / RULES entry agreement ───────────────────────────────────

class TestC1HeadingEntryAgreement:
    def test_missing_core_rules_heading_fails(self, tool, monkeypatch):
        """C1 blocks when CORE_RULES.md has no ### N.NN heading for the new rule."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(include_heading=False),
            _make_cov(),
            _make_map(),
            _make_snap(),
        )
        assert any("C1" in e and "heading" in e for e in errors), errors

    def test_missing_rules_list_entry_fails(self, tool, monkeypatch):
        """C1 blocks when ms-coverage has no RULES entry for the new rule."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(),
            _make_cov(include_entry=False),
            _make_map(include_node=False),
            _make_snap(count=0, include_label=False),
        )
        assert any("C1" in e and "RULES entry" in e for e in errors), errors

    def test_title_mismatch_fails(self, tool, monkeypatch):
        """C1 blocks when heading title and RULES entry label differ."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(title="Original Title"),
            _make_cov(label="Different Label"),
            _make_map(),
            _make_snap(),
        )
        assert any("C1" in e and "mismatch" in e for e in errors), errors


# ── C2: Section 8 version history row ─────────────────────────────────────

class TestC2Section8Row:
    def test_missing_section8_row_fails(self, tool, monkeypatch):
        """C2 blocks when Section 8 has no row for today's date + rule id."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(include_section8=False),
            _make_cov(),
            _make_map(),
            _make_snap(),
        )
        assert any("C2" in e for e in errors), errors

    def test_wrong_date_section8_row_fails(self, tool, monkeypatch):
        """C2 blocks when Section 8 row exists but uses a stale date."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(s8_date="2020-01-01"),
            _make_cov(),
            _make_map(),
            _make_snap(),
        )
        assert any("C2" in e for e in errors), errors


# ── C3: coverage_map.json node present ────────────────────────────────────

class TestC3CoverageMapNode:
    def test_missing_coverage_map_node_fails(self, tool, monkeypatch):
        """C3 blocks when coverage_map.json has no node for the new rule."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(),
            _make_cov(),
            _make_map(include_node=False),
            _make_snap(),
        )
        assert any("C3" in e for e in errors), errors


# ── C4: snapshot count agreement ──────────────────────────────────────────

class TestC4SnapshotCount:
    def test_snapshot_count_mismatch_fails(self, tool, monkeypatch):
        """C4 blocks when snapshot count does not match coverage_map rule count."""
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(),
            _make_cov(),
            _make_map(rule_count=1),
            _make_snap(count=99),          # count disagrees with map (1 node)
        )
        assert any("C4" in e for e in errors), errors

    def test_snapshot_label_missing_fails(self, tool, monkeypatch):
        """C4 blocks when count is correct but the new rule's label is absent from snapshot.

        This is the realistic regression: rule added to coverage_map but snapshot not
        regenerated. Count alone doesn't catch it — label check is required.
        """
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(),
            _make_cov(),
            _make_map(rule_count=1),
            _make_snap(count=1, include_label=False),  # count matches but label absent
        )
        assert any("C4" in e and "test_cli_snapshots" in e for e in errors), errors


# ── CLI smoke test ─────────────────────────────────────────────────────────

class TestCliSmoke:
    def test_check_with_no_staged_changes_exits_0(self):
        """ms-rule-contract --check exits 0 when nothing is staged."""
        r = subprocess.run(
            ["python3", str(_TOOL), "--check"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "contract satisfied" in r.stdout

    def test_audit_with_no_numeric_rules_exits_0(self):
        """ms-rule-contract --audit exits 0 when no N.NN rules exist yet."""
        r = subprocess.run(
            ["python3", str(_TOOL), "--audit"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "clean" in r.stdout


# ── Audit invariant count and scope ───────────────────────────────────────

class TestAuditInvariantScope:
    def test_audit_success_message_says_5_invariants(self):
        """Audit clean output confirms 5 invariants, not 6 (INV-1 removed as redundant)."""
        r = subprocess.run(
            ["python3", str(_TOOL), "--audit"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "5 invariant" in r.stdout, (
            f"expected '5 invariant' in audit output; got:\n{r.stdout}"
        )

    def test_heading_without_entry_caught_by_check_c1(self, tool, monkeypatch):
        """C1 in --check still enforces heading→entry (INV-1 removed from audit by design).

        ADR 0012 Scope Note: INV-1 collapses to INV-2 under N.NN scoping, so it was
        removed from audit mode. This test guards against regression where someone
        assumes audit covers the heading→entry direction.
        """
        monkeypatch.setattr(tool, "TODAY", TODAY)
        monkeypatch.setattr(tool, "test_fn_exists", lambda fn, tf: True)

        errors, _ = tool.run_companion_checks(
            {RULE_ID},
            _make_cr(),                           # heading present
            _make_cov(include_entry=False),        # RULES entry absent
            _make_map(include_node=False),
            _make_snap(count=0, include_label=False),
        )
        assert any("C1" in e and "RULES entry" in e for e in errors), (
            f"C1 must catch heading-without-entry in --check mode, got: {errors}"
        )


# ── F5 regression: diff-aware heading detection ───────────────────────────

class TestAddedHeadingIdsDiffAware:
    """Regression for audit Finding F5: added_heading_ids must not fire on edits.

    An ID is 'new' iff it appears in + lines but NOT in - lines.  Three cases:
      1. Title-only edit: same ID in both + and - → not a new rule.
      2. Genuinely new rule: ID in + only → real addition, must be returned.
      3. Renumbering: old ID in -, new ID in + (different IDs) → new ID is a
         real addition (requires companion changes); old ID is an out-of-scope
         deletion.
    """

    def test_title_edit_not_detected_as_new_addition(self, tool):
        """Editing a rule's title text: paired +/- for the same ID → empty result."""
        diff = "-### 5.20 Old Title Text\n+### 5.20 New Title Text\n"
        assert tool.added_heading_ids(diff) == {}

    def test_genuinely_new_rule_detected(self, tool):
        """New rule ID in + with no matching - → returned as real addition."""
        diff = "+### 5.99 Brand New Synthetic Rule\n"
        result = tool.added_heading_ids(diff)
        assert "5.99" in result

    def test_renumbering_returns_new_id_not_old(self, tool):
        """Renumbering (5.20→5.21): new ID is a real addition; old ID must not appear."""
        diff = "-### 5.20 Some Rule Title\n+### 5.21 Some Rule Title\n"
        result = tool.added_heading_ids(diff)
        assert "5.21" in result, f"renumbered new ID must be detected; got {result}"
        assert "5.20" not in result, f"old ID must not be treated as addition; got {result}"


# ── meta-no-hollow-constraints: every accepted ADR has enforcement ────────────

import re as _re


def test_every_accepted_adr_has_enforcement() -> None:
    """Every accepted ADR must have its number referenced in ms-enforce or ms-coverage."""
    adr_dir = REPO / "docs" / "adr"
    enforce_text = (REPO / "ms-enforce").read_text()
    coverage_text = (REPO / "ms-coverage").read_text()
    combined = enforce_text + coverage_text

    unmatched = []
    for path in sorted(adr_dir.glob("*.md")):
        m = _re.match(r"^(\d{4})-", path.name)
        if not m:
            continue
        content = path.read_text()
        if "Status: Accepted" not in content and "**Status:** Accepted" not in content:
            continue
        num = m.group(1)
        if num not in combined:
            unmatched.append(f"ADR {num} ({path.name})")

    assert not unmatched, (
        f"{len(unmatched)} accepted ADR(s) have no enforcement reference in ms-enforce or ms-coverage:\n"
        + "\n".join(f"  - {x}" for x in unmatched)
    )
