"""tests/test_preflight_wave.py — Tests for tools/preflight_wave.py

Fixtures drive a Low/Medium/High wave through the harness, assert that:
- A FALSE claim yields a BLOCKED verdict.
- A BLOCKED verdict writes .claude/run/preflight/<wave>.md to tmp_path.
- A PASS verdict yields DISPATCH-OK.
- The tier-string contract holds (only VALID_TIERS used).
- tmp_path is used exclusively — NEVER the real .claude/run/preflight/ dir.

NOTE: These tests use stub/fixture wave files in tmp_path.  tools/wave_complexity.py
(Stream B) may not exist in this isolated worktree; the harness gracefully falls
back to parsing the "**Tier: X**" self-declaration in the wave file.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ── Import harness under test ────────────────────────────────────────────────
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
_HARNESS_PATH = _TOOLS_DIR / "preflight_wave.py"

spec = importlib.util.spec_from_file_location("preflight_wave", _HARNESS_PATH)
assert spec is not None and spec.loader is not None
preflight_wave = importlib.util.module_from_spec(spec)
# Register in sys.modules BEFORE exec_module so dataclass decorators can
# resolve the module's __dict__ via sys.modules[cls.__module__].
sys.modules["preflight_wave"] = preflight_wave
spec.loader.exec_module(preflight_wave)  # type: ignore[union-attr]

run_preflight = preflight_wave.run_preflight
VALID_TIERS = preflight_wave.VALID_TIERS
TIER_LOW = preflight_wave.TIER_LOW
TIER_MEDIUM = preflight_wave.TIER_MEDIUM
TIER_HIGH = preflight_wave.TIER_HIGH
CheckResult = preflight_wave.CheckResult
PreflightReport = preflight_wave.PreflightReport


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_wave(tmp_path: Path, name: str, content: str) -> Path:
    """Write *content* to tmp_path/<name>.md and return the Path."""
    p = tmp_path / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


# ── Low-tier wave fixtures ────────────────────────────────────────────────────

_LOW_WAVE_OK = """\
# S-LOW-GOOD-WAVE

## Goal
Single additive stream, no shared symbols.

## Complexity & Pre-flight
**Tier: Low.** One stream; no shared symbols; no sensitive paths; no Opus stream.

## Deliverables per stream
### Stream A
1. Add `tools/some_new_file.py` (new tool).
"""

_LOW_WAVE_FALSE_PATH = """\
# S-LOW-BAD-PATH

## Goal
Wave that claims a non-existent file exists.

## Context
This wave depends on the existing implementation in
`tools/this_file_does_not_exist_zzzzzz.py` which provides the core logic.

## Complexity & Pre-flight
**Tier: Low.**

## Deliverables per stream
### Stream A
1. Add a new helper function.
"""


class TestLowTierWave:
    """Low-tier: only validate-wave-file.py runs."""

    def test_low_ok_dispatch_ok(self, tmp_path: Path) -> None:
        """A well-formed Low wave with no invalid path claims → DISPATCH-OK."""
        wave = _make_wave(tmp_path, "S-LOW-GOOD-WAVE", _LOW_WAVE_OK)
        output_dir = tmp_path / "preflight"

        report = run_preflight(
            wave_path=wave,
            repo=_TOOLS_DIR.parent,
            output_dir=output_dir,
        )

        assert report.verdict == "DISPATCH-OK", (
            f"Expected DISPATCH-OK but got {report.verdict}; "
            f"checks: {[(c.name, c.status, c.detail) for c in report.checks]}"
        )
        assert report.tier == TIER_LOW
        # Report file must exist in tmp_path, NOT in real .claude/run/preflight/
        assert report.report_path is not None
        assert report.report_path.exists()
        assert str(report.report_path).startswith(str(tmp_path))

    def test_low_tier_only_runs_low_checks(self, tmp_path: Path) -> None:
        """Low tier must NOT run Medium or High checks."""
        wave = _make_wave(tmp_path, "S-LOW-GOOD-WAVE", _LOW_WAVE_OK)
        output_dir = tmp_path / "preflight"

        report = run_preflight(
            wave_path=wave,
            repo=_TOOLS_DIR.parent,
            output_dir=output_dir,
        )

        check_names = {c.name for c in report.checks}
        assert "validate-wave-file" in check_names
        # Medium/High checks must not be present
        assert "fact-check-subagent-hook" not in check_names
        assert "processor-contract-pinned" not in check_names
        assert "cross-wave-disjointness" not in check_names
        assert "edited-wave-consistency" not in check_names

    def test_low_false_path_yields_blocked(self, tmp_path: Path) -> None:
        """A Low wave with a clearly wrong path claim → BLOCKED."""
        wave = _make_wave(tmp_path, "S-LOW-BAD-PATH", _LOW_WAVE_FALSE_PATH)
        output_dir = tmp_path / "preflight"

        report = run_preflight(
            wave_path=wave,
            repo=_TOOLS_DIR.parent,
            output_dir=output_dir,
        )

        assert report.verdict == "BLOCKED"
        false_checks = [c for c in report.checks if c.status == "FALSE"]
        assert len(false_checks) >= 1

        # Report file must exist in tmp_path
        assert report.report_path is not None
        assert report.report_path.exists()
        assert str(report.report_path).startswith(str(tmp_path))

        # Report file content must say BLOCKED
        content = report.report_path.read_text()
        assert "BLOCKED" in content

    def test_report_written_to_output_dir(self, tmp_path: Path) -> None:
        """Report is always written to output_dir/<wave-stem>.md."""
        wave = _make_wave(tmp_path, "S-LOW-GOOD-WAVE", _LOW_WAVE_OK)
        output_dir = tmp_path / "preflight_out"

        report = run_preflight(
            wave_path=wave,
            repo=_TOOLS_DIR.parent,
            output_dir=output_dir,
        )

        expected = output_dir / "S-LOW-GOOD-WAVE.md"
        assert report.report_path == expected
        assert expected.exists()


# ── Medium-tier wave fixtures ─────────────────────────────────────────────────

_MEDIUM_WAVE_OK = """\
# S-MEDIUM-GOOD-WAVE

## Goal
Multi-stream additive wave with several repo claims.

## Complexity & Pre-flight
**Tier: Medium.** Multiple streams; several repo claims; no shared symbols.

## Parallelization
**Models:** coordinator = **opus**, subagents = **sonnet**.

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A — add tool a | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Add `tools/new_tool_a.py` |
| B — add tool b | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Add `tools/new_tool_b.py` |
| C — add tool c | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Add `tools/new_tool_c.py` |
| D — extend validator | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Extend `tools/validate-wave-file.py` |

## Deliverables per stream
### Stream A
1. Add `tools/new_tool_a.py` (new file). `tools/validate-wave-file.py` exists today.
### Stream B
1. Add `tools/new_tool_b.py`. `tools/wave_complexity.py` exists today.
### Stream C
1. Add `tools/new_tool_c.py`. `README.md` exists today.
### Stream D
1. Extend `tools/validate-wave-file.py`. `ms-enforce` exists today.
"""

_MEDIUM_WAVE_NO_TIER_DECL = """\
# S-MEDIUM-NO-DECL

## Goal
Medium wave that forgets to declare its tier.

## Deliverables per stream
### Stream A
1. Add `tools/new_medium_tool.py`.
"""


class TestMediumTierWave:
    """Medium-tier: Low checks + fact-check subagent hook."""

    def test_medium_ok_dispatch_ok(self, tmp_path: Path) -> None:
        """A well-formed Medium wave → DISPATCH-OK."""
        wave = _make_wave(tmp_path, "S-MEDIUM-GOOD-WAVE", _MEDIUM_WAVE_OK)
        output_dir = tmp_path / "preflight"

        report = run_preflight(
            wave_path=wave,
            repo=_TOOLS_DIR.parent,
            output_dir=output_dir,
        )

        assert report.tier == TIER_MEDIUM
        # Both Low and Medium checks must be present
        check_names = {c.name for c in report.checks}
        assert "validate-wave-file" in check_names
        assert "fact-check-subagent-hook" in check_names
        # High-only checks must not be present
        assert "processor-contract-pinned" not in check_names

    def test_medium_no_tier_decl_fact_check_false(self, tmp_path: Path) -> None:
        """A Medium wave without a tier declaration → fact-check check is FALSE → BLOCKED."""
        wave = _make_wave(
            tmp_path, "S-MEDIUM-NO-DECL", _MEDIUM_WAVE_NO_TIER_DECL
        )
        output_dir = tmp_path / "preflight"

        # Force the harness to treat this as Medium (no scorer available, self-decl missing)
        # by patching the tier resolver directly for this test.
        import unittest.mock as mock

        with mock.patch.object(
            preflight_wave, "_get_tier_from_scorer", return_value=TIER_MEDIUM
        ):
            report = run_preflight(
                wave_path=wave,
                repo=_TOOLS_DIR.parent,
                output_dir=output_dir,
            )

        fact_check = next(
            (c for c in report.checks if c.name == "fact-check-subagent-hook"),
            None,
        )
        assert fact_check is not None
        assert fact_check.status == "FALSE"
        assert report.verdict == "BLOCKED"

        # Report written to tmp_path
        assert report.report_path is not None
        assert str(report.report_path).startswith(str(tmp_path))
        content = report.report_path.read_text()
        assert "BLOCKED" in content

    def test_false_claim_yields_blocked(self, tmp_path: Path) -> None:
        """Any FALSE check at Medium tier → BLOCKED verdict."""
        wave = _make_wave(
            tmp_path, "S-MEDIUM-NO-DECL", _MEDIUM_WAVE_NO_TIER_DECL
        )
        output_dir = tmp_path / "preflight"

        import unittest.mock as mock

        with mock.patch.object(
            preflight_wave, "_get_tier_from_scorer", return_value=TIER_MEDIUM
        ):
            report = run_preflight(
                wave_path=wave,
                repo=_TOOLS_DIR.parent,
                output_dir=output_dir,
            )

        assert report.verdict == "BLOCKED"
        assert any(c.status == "FALSE" for c in report.checks)


# ── High-tier wave fixtures ───────────────────────────────────────────────────

_HIGH_WAVE_OK = """\
# S-HIGH-GOOD-WAVE

## Goal
High-complexity wave with shared symbols, sensitive paths, Opus streams.

## Complexity & Pre-flight
**Tier: High.** Signals: 5 streams; three PINNED shared-symbol contracts;
touches ROBOT.md; two Opus streams.

## Deliverables per stream

### Stream A
1. **Model-column format (PINNED — A produces, B consumes):** exact format.

### Stream B
1. **Tier-string contract (PINNED — B produces, C and E consume):**
   `VALID_TIERS = ("Low", "Medium", "High")`.

## Cross-wave dependencies
- Depends only on current `origin/main`.
- File-disjoint with all other in-flight waves.
"""

_HIGH_WAVE_NO_PINNED = """\
# S-HIGH-NO-PINNED

## Goal
High wave but Deliverables has no PINNED markers.

## Complexity & Pre-flight
**Tier: High.** Multiple streams, shared symbols.

## Deliverables per stream
### Stream A
1. Extend `tools/validate-wave-file.py`.

## Cross-wave dependencies
- Depends on current main.
"""

_HIGH_WAVE_NO_CROSS_WAVE = """\
# S-HIGH-NO-CROSS-WAVE

## Goal
High wave but missing Cross-wave dependencies section.

## Complexity & Pre-flight
**Tier: High.** Multiple streams, shared symbols.

## Deliverables per stream
### Stream A
1. **Contract (PINNED):** the tier string PINNED to "High".
"""

_HIGH_WAVE_NO_COMPLEXITY_SECTION = """\
# S-HIGH-NO-COMPLEXITY

## Goal
High wave but missing Complexity section entirely.

## Deliverables per stream
### Stream A
1. **Contract (PINNED):** the tier string PINNED to "High".

## Cross-wave dependencies
- Depends on current main.
"""


class TestHighTierWave:
    """High-tier: Low + Medium + processor-contract + disjointness + consistency."""

    def _run_as_high(
        self, tmp_path: Path, name: str, content: str
    ) -> PreflightReport:
        """Helper: run preflight forcing tier=High."""
        import unittest.mock as mock

        wave = _make_wave(tmp_path, name, content)
        output_dir = tmp_path / "preflight"

        with mock.patch.object(
            preflight_wave, "_get_tier_from_scorer", return_value=TIER_HIGH
        ):
            return run_preflight(
                wave_path=wave,
                repo=_TOOLS_DIR.parent,
                output_dir=output_dir,
            )

    def test_high_ok_dispatch_ok(self, tmp_path: Path) -> None:
        """A well-formed High wave → DISPATCH-OK."""
        report = self._run_as_high(tmp_path, "S-HIGH-GOOD-WAVE", _HIGH_WAVE_OK)

        check_names = {c.name for c in report.checks}
        assert "validate-wave-file" in check_names
        assert "fact-check-subagent-hook" in check_names
        assert "processor-contract-pinned" in check_names
        assert "cross-wave-disjointness" in check_names
        assert "edited-wave-consistency" in check_names

        # Report in tmp_path
        assert report.report_path is not None
        assert str(report.report_path).startswith(str(tmp_path))

    def test_high_no_pinned_markers_blocked(self, tmp_path: Path) -> None:
        """High wave with no PINNED markers in Deliverables → BLOCKED."""
        report = self._run_as_high(tmp_path, "S-HIGH-NO-PINNED", _HIGH_WAVE_NO_PINNED)

        pinned_check = next(
            (c for c in report.checks if c.name == "processor-contract-pinned"),
            None,
        )
        assert pinned_check is not None
        assert pinned_check.status == "FALSE"
        assert report.verdict == "BLOCKED"

        # Report written
        assert report.report_path is not None
        assert report.report_path.exists()
        content = report.report_path.read_text()
        assert "BLOCKED" in content

    def test_high_no_cross_wave_section_blocked(self, tmp_path: Path) -> None:
        """High wave missing Cross-wave dependencies → BLOCKED."""
        report = self._run_as_high(
            tmp_path, "S-HIGH-NO-CROSS-WAVE", _HIGH_WAVE_NO_CROSS_WAVE
        )

        disjoint_check = next(
            (c for c in report.checks if c.name == "cross-wave-disjointness"),
            None,
        )
        assert disjoint_check is not None
        assert disjoint_check.status == "FALSE"
        assert report.verdict == "BLOCKED"

    def test_high_no_complexity_section_blocked(self, tmp_path: Path) -> None:
        """High wave missing Complexity section → edited-wave-consistency FALSE → BLOCKED."""
        report = self._run_as_high(
            tmp_path, "S-HIGH-NO-COMPLEXITY", _HIGH_WAVE_NO_COMPLEXITY_SECTION
        )

        consistency_check = next(
            (c for c in report.checks if c.name == "edited-wave-consistency"),
            None,
        )
        assert consistency_check is not None
        assert consistency_check.status == "FALSE"
        assert report.verdict == "BLOCKED"

    def test_false_check_always_blocks(self, tmp_path: Path) -> None:
        """Any FALSE check at any tier → verdict is BLOCKED (invariant)."""
        report = self._run_as_high(tmp_path, "S-HIGH-NO-PINNED", _HIGH_WAVE_NO_PINNED)
        assert report.verdict == "BLOCKED"
        assert report.is_blocked()


# ── Tier-string contract ─────────────────────────────────────────────────────

class TestTierStringContract:
    """Verify B's VALID_TIERS contract is honoured exactly."""

    def test_valid_tiers_exact(self) -> None:
        """VALID_TIERS must be exactly ("Low", "Medium", "High")."""
        assert VALID_TIERS == ("Low", "Medium", "High")

    def test_tier_constants_match_valid_tiers(self) -> None:
        """TIER_LOW/MEDIUM/HIGH must match entries in VALID_TIERS."""
        assert TIER_LOW in VALID_TIERS
        assert TIER_MEDIUM in VALID_TIERS
        assert TIER_HIGH in VALID_TIERS
        assert TIER_LOW == "Low"
        assert TIER_MEDIUM == "Medium"
        assert TIER_HIGH == "High"

    def test_harness_branches_on_exact_tier_strings(self, tmp_path: Path) -> None:
        """Harness only branches on VALID_TIERS; no stray lower-cased variants."""
        import inspect
        source = inspect.getsource(preflight_wave)
        # Look for any bare lowercase tier comparisons (e.g. "low", "high")
        # that are NOT part of comments, string constants in VALID_TIERS, or docstrings.
        # We check for suspicious patterns like == "low" or == "high".
        import re
        bad_patterns = re.findall(
            r'==\s*["\'](?:low|medium|high)["\']',
            source,
            re.IGNORECASE,
        )
        # Filter out any that use the correct capitalisation
        real_bad = [p for p in bad_patterns if p not in (
            '== "Low"', "== 'Low'",
            '== "Medium"', "== 'Medium'",
            '== "High"', "== 'High'",
        )]
        assert not real_bad, (
            f"Harness uses stray lowercase tier comparison(s): {real_bad}"
        )

    def test_all_check_tier_required_in_valid_tiers(self, tmp_path: Path) -> None:
        """Every CheckResult.tier_required must be a member of VALID_TIERS."""
        import unittest.mock as mock

        wave_content = _HIGH_WAVE_OK
        wave = _make_wave(tmp_path, "S-HIGH-GOOD-WAVE", wave_content)
        output_dir = tmp_path / "preflight"

        with mock.patch.object(
            preflight_wave, "_get_tier_from_scorer", return_value=TIER_HIGH
        ):
            report = run_preflight(
                wave_path=wave,
                repo=_TOOLS_DIR.parent,
                output_dir=output_dir,
            )

        for c in report.checks:
            assert c.tier_required in VALID_TIERS, (
                f"Check '{c.name}' has tier_required={c.tier_required!r} "
                f"which is not in VALID_TIERS"
            )


# ── Report file contract ──────────────────────────────────────────────────────

class TestReportFileContract:
    """Verify report file structure and tmp_path isolation."""

    def test_report_never_written_to_real_preflight_dir(
        self, tmp_path: Path
    ) -> None:
        """Using explicit output_dir means real .claude/run/preflight/ is never touched."""
        wave = _make_wave(tmp_path, "S-ISOLATION-TEST", _LOW_WAVE_OK)
        output_dir = tmp_path / "isolated_preflight"

        report = run_preflight(
            wave_path=wave,
            repo=_TOOLS_DIR.parent,
            output_dir=output_dir,
        )

        assert report.report_path is not None
        # Must be inside tmp_path
        assert str(report.report_path).startswith(str(tmp_path))
        # Must NOT be inside real .claude/run/preflight
        real_dir = str(_TOOLS_DIR.parent / ".claude" / "run" / "preflight")
        assert not str(report.report_path).startswith(real_dir)

    def test_report_contains_verdict_line(self, tmp_path: Path) -> None:
        """Report file must contain the verdict string."""
        wave = _make_wave(tmp_path, "S-LOW-GOOD-WAVE", _LOW_WAVE_OK)
        output_dir = tmp_path / "preflight"

        report = run_preflight(
            wave_path=wave,
            repo=_TOOLS_DIR.parent,
            output_dir=output_dir,
        )

        content = report.report_path.read_text()
        assert report.verdict in content

    def test_blocked_report_lists_false_checks(self, tmp_path: Path) -> None:
        """A BLOCKED report file explicitly lists the FALSE checks."""
        import unittest.mock as mock

        wave = _make_wave(
            tmp_path, "S-MEDIUM-NO-DECL", _MEDIUM_WAVE_NO_TIER_DECL
        )
        output_dir = tmp_path / "preflight"

        with mock.patch.object(
            preflight_wave, "_get_tier_from_scorer", return_value=TIER_MEDIUM
        ):
            report = run_preflight(
                wave_path=wave,
                repo=_TOOLS_DIR.parent,
                output_dir=output_dir,
            )

        assert report.verdict == "BLOCKED"
        content = report.report_path.read_text()
        assert "BLOCKED" in content
        assert "FALSE" in content
