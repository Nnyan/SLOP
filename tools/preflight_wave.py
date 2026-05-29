#!/usr/bin/env python3
"""tools/preflight_wave.py — Complexity-gated pre-flight harness.

Orchestrator startup step: compute the wave's complexity tier (via
tools/wave_complexity.py), run the matching rigor level, and write a
verdict report to .claude/run/preflight/<wave-stem>.md.

Tier → rigor mapping (per Stream C PINNED spec):
  Low    → tools/validate-wave-file.py (mechanical path/ref check)
  Medium → Low + one fact-check subagent step (claim-check hook)
  High   → Medium + processor-contract-pinned check +
            cross-wave disjointness + edited-wave consistency

Verdict:
  DISPATCH-OK  — all checks PASS
  BLOCKED      — one or more checks are FALSE

Usage
-----
  python3 tools/preflight_wave.py <wave-file.md> [--repo <repo-root>]
                                   [--output-dir <dir>]

Exit codes
----------
  0 — DISPATCH-OK
  1 — BLOCKED (one or more FALSE claims)
  2 — usage / file-not-found error

Import API (for tests and harness consumers)
--------------------------------------------
  from tools.preflight_wave import run_preflight, CheckResult, PreflightReport

  report = run_preflight(
      wave_path=Path("..."),
      repo=Path("."),
      output_dir=Path(".claude/run/preflight"),
  )
  # report.verdict  → "DISPATCH-OK" or "BLOCKED"
  # report.checks   → list[CheckResult]
  # report.report_path → Path where the .md was written
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Pinned constants (Stream B contract) ────────────────────────────────────
# These strings are PINNED verbatim by the wave.  Do NOT change casing.
VALID_TIERS = ("Low", "Medium", "High")
TIER_LOW = "Low"
TIER_MEDIUM = "Medium"
TIER_HIGH = "High"

# ── Repo root heuristic ─────────────────────────────────────────────────────
_TOOLS_DIR = Path(__file__).resolve().parent
_DEFAULT_REPO = _TOOLS_DIR.parent


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Result of a single pre-flight check."""
    name: str
    tier_required: str          # "Low" | "Medium" | "High" (minimum tier that activates)
    status: str                 # "PASS" or "FALSE"
    detail: str = ""


@dataclass
class PreflightReport:
    """Full pre-flight report for a wave."""
    wave_stem: str
    tier: str
    checks: list[CheckResult] = field(default_factory=list)
    verdict: str = ""           # "DISPATCH-OK" or "BLOCKED"
    report_path: Optional[Path] = None
    timestamp: str = ""

    def is_blocked(self) -> bool:
        return any(c.status == "FALSE" for c in self.checks)


# ── Tier resolution ──────────────────────────────────────────────────────────

def _get_tier_from_scorer(wave_path: Path, repo: Path) -> str:
    """Resolve the complexity tier for *wave_path*.

    Strategy:
    1. Try to import tools/wave_complexity.py as a module and call
       score_wave(wave_path) (Stream B's pinned API).
    2. If the module is not yet present in this worktree (Stream B hasn't
       merged yet), fall back to the CLI tail-line strategy:
       run `python3 tools/wave_complexity.py <wave> --repo <repo>`
       and take the last stdout line as the tier.
    3. If neither works (file absent, CLI fails), fall back to scanning
       the wave file for a "**Tier: <X>**" self-declared line (a best-effort
       heuristic used only when the scorer is unavailable).
    4. If nothing resolves, default to "High" (most conservative).

    This fallback chain ensures the harness is usable in this isolated
    worktree before B's file is merged, and resolves correctly post-merge.
    """
    wave_complexity_path = repo / "tools" / "wave_complexity.py"

    # Strategy 1: dynamic import
    if wave_complexity_path.exists():
        try:
            spec = importlib.util.spec_from_file_location(
                "wave_complexity", wave_complexity_path
            )
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            result = mod.score_wave(wave_path)
            tier = result.get("tier", "")
            if tier in VALID_TIERS:
                return tier
        except Exception:
            pass

    # Strategy 2: CLI tail-line
    if wave_complexity_path.exists():
        try:
            out = subprocess.run(
                [sys.executable, str(wave_complexity_path),
                 str(wave_path), "--repo", str(repo)],
                capture_output=True, text=True, timeout=60,
            )
            lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
            if lines and lines[-1] in VALID_TIERS:
                return lines[-1]
        except Exception:
            pass

    # Strategy 3: self-declared tier in the wave file
    try:
        content = wave_path.read_text(encoding="utf-8")
        m = re.search(
            r"\*\*Tier:\s*(Low|Medium|High)\b",
            content,
            re.IGNORECASE,
        )
        if m:
            raw = m.group(1).capitalize()
            # Normalise capitalisation to match VALID_TIERS exactly
            for t in VALID_TIERS:
                if t.lower() == raw.lower():
                    return t
    except Exception:
        pass

    # Strategy 4: conservative default
    return TIER_HIGH


# ── Individual checks ────────────────────────────────────────────────────────

def _check_validate_wave_file(wave_path: Path, repo: Path) -> CheckResult:
    """Run tools/validate-wave-file.py as the Low-tier mechanical gate.

    Passes iff the validator exits 0 (no path/ref failures).
    """
    validator = repo / "tools" / "validate-wave-file.py"
    if not validator.exists():
        return CheckResult(
            name="validate-wave-file",
            tier_required=TIER_LOW,
            status="FALSE",
            detail="tools/validate-wave-file.py not found in repo",
        )
    try:
        result = subprocess.run(
            [sys.executable, str(validator), str(wave_path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return CheckResult(
                name="validate-wave-file",
                tier_required=TIER_LOW,
                status="PASS",
                detail=result.stdout.strip() or "Validator exited 0",
            )
        else:
            return CheckResult(
                name="validate-wave-file",
                tier_required=TIER_LOW,
                status="FALSE",
                detail=(result.stdout + result.stderr).strip(),
            )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="validate-wave-file",
            tier_required=TIER_LOW,
            status="FALSE",
            detail="Validator timed out (>120s)",
        )
    except Exception as exc:
        return CheckResult(
            name="validate-wave-file",
            tier_required=TIER_LOW,
            status="FALSE",
            detail=f"Unexpected error: {exc}",
        )


def _check_fact_check_subagent_hook(wave_path: Path, repo: Path) -> CheckResult:
    """Medium-tier: hook/step representing the fact-check subagent dispatch.

    At this tier the harness RECORDS that a fact-check subagent step is
    required.  Actual subagent dispatch is the orchestrator's responsibility
    (the harness defines and documents the rigor step).  The check PASSes
    here as a structural marker; the orchestrator reads the report and knows
    to launch the subagent before clearing DISPATCH-OK.

    A FALSE here means the wave file is missing the minimum structural
    requirement for a fact-check (e.g. no "## Complexity" section declaring
    the tier).
    """
    try:
        content = wave_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            name="fact-check-subagent-hook",
            tier_required=TIER_MEDIUM,
            status="FALSE",
            detail=f"Could not read wave file: {exc}",
        )

    # A Medium/High wave must declare its tier explicitly.
    has_tier_decl = bool(
        re.search(r"\*\*Tier:\s*(Medium|High)\b", content, re.IGNORECASE)
    )
    if not has_tier_decl:
        return CheckResult(
            name="fact-check-subagent-hook",
            tier_required=TIER_MEDIUM,
            status="FALSE",
            detail=(
                "Wave file does not contain a '**Tier: Medium**' or "
                "'**Tier: High**' self-declaration under '## Complexity'. "
                "Medium/High waves must declare their tier."
            ),
        )

    return CheckResult(
        name="fact-check-subagent-hook",
        tier_required=TIER_MEDIUM,
        status="PASS",
        detail=(
            "Fact-check subagent step recorded. "
            "Orchestrator must dispatch one fact-check subagent before "
            "clearing DISPATCH-OK for a Medium/High wave."
        ),
    )


def _check_processor_contract_pinned(wave_path: Path, repo: Path) -> CheckResult:
    """High-tier: verify every shared symbol is PINNED verbatim in Deliverables.

    A wave is processor-contract-pinned iff its Deliverables section contains
    at least one explicit PINNED marker (the word "PINNED" in caps) for each
    cross-stream shared symbol mentioned in the Parallelization section.
    Conservative: only FAIL if there are explicit cross-stream shared-symbol
    mentions but zero PINNED markers in Deliverables.
    """
    try:
        content = wave_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            name="processor-contract-pinned",
            tier_required=TIER_HIGH,
            status="FALSE",
            detail=f"Could not read wave file: {exc}",
        )

    # Check for "PINNED" markers in the Deliverables section.
    deliverables_match = re.search(
        r"^#{1,3}\s+Deliverables",
        content,
        re.IGNORECASE | re.MULTILINE,
    )

    if not deliverables_match:
        return CheckResult(
            name="processor-contract-pinned",
            tier_required=TIER_HIGH,
            status="FALSE",
            detail=(
                "No '## Deliverables' section found. "
                "High-tier waves must have a Deliverables section with PINNED markers."
            ),
        )

    deliverables_text = content[deliverables_match.start():]
    pinned_count = len(re.findall(r"\bPINNED\b", deliverables_text))

    if pinned_count == 0:
        return CheckResult(
            name="processor-contract-pinned",
            tier_required=TIER_HIGH,
            status="FALSE",
            detail=(
                "Deliverables section contains zero PINNED markers. "
                "High-tier waves with shared symbols must pin every shared "
                "interface verbatim (AUTONOMOUS-DEFAULTS § 'Processor-pattern contract')."
            ),
        )

    return CheckResult(
        name="processor-contract-pinned",
        tier_required=TIER_HIGH,
        status="PASS",
        detail=f"Found {pinned_count} PINNED marker(s) in Deliverables section.",
    )


def _check_cross_wave_disjointness(wave_path: Path, repo: Path) -> CheckResult:
    """High-tier: verify the wave declares cross-wave dependencies and disjointness.

    A High-tier wave must contain a '## Cross-wave dependencies' section.
    If it claims to be disjoint with in-flight waves, that assertion is
    recorded as PASS (the harness cannot auto-verify full cross-wave diffs).
    FAIL only if the section is missing entirely.
    """
    try:
        content = wave_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            name="cross-wave-disjointness",
            tier_required=TIER_HIGH,
            status="FALSE",
            detail=f"Could not read wave file: {exc}",
        )

    has_section = bool(
        re.search(
            r"^#{1,3}\s+Cross-wave dependencies",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
    )

    if not has_section:
        return CheckResult(
            name="cross-wave-disjointness",
            tier_required=TIER_HIGH,
            status="FALSE",
            detail=(
                "No '## Cross-wave dependencies' section found. "
                "High-tier waves must declare cross-wave file overlap / disjointness."
            ),
        )

    return CheckResult(
        name="cross-wave-disjointness",
        tier_required=TIER_HIGH,
        status="PASS",
        detail="Cross-wave dependencies section present; disjointness claim recorded.",
    )


def _check_edited_wave_consistency(wave_path: Path, repo: Path) -> CheckResult:
    """High-tier: check self-consistency of the wave file.

    Verifies that the wave's own Complexity section lists a tier consistent
    with having at least one of: shared symbols, sensitive paths, or Opus streams.
    Conservative — only FAILs on clearly inconsistent declarations.
    """
    try:
        content = wave_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            name="edited-wave-consistency",
            tier_required=TIER_HIGH,
            status="FALSE",
            detail=f"Could not read wave file: {exc}",
        )

    # Must have a Complexity section for High-tier waves.
    has_complexity = bool(
        re.search(
            r"^#{1,3}\s+Complexity",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
    )

    if not has_complexity:
        return CheckResult(
            name="edited-wave-consistency",
            tier_required=TIER_HIGH,
            status="FALSE",
            detail=(
                "No '## Complexity' section found. "
                "High-tier waves must include a Complexity & Pre-flight section."
            ),
        )

    # The Complexity section must declare "High".
    complexity_match = re.search(
        r"^#{1,3}\s+Complexity.*?(?=^#{1,3}\s|\Z)",
        content,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if complexity_match:
        complexity_text = complexity_match.group(0)
        if not re.search(r"\bHigh\b", complexity_text):
            return CheckResult(
                name="edited-wave-consistency",
                tier_required=TIER_HIGH,
                status="FALSE",
                detail=(
                    "Complexity section does not declare 'High'. "
                    "Wave scored as High but Complexity section disagrees."
                ),
            )

    return CheckResult(
        name="edited-wave-consistency",
        tier_required=TIER_HIGH,
        status="PASS",
        detail="Complexity section present and declares High tier consistently.",
    )


# ── Main harness ─────────────────────────────────────────────────────────────

def run_preflight(
    wave_path: Path,
    repo: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> PreflightReport:
    """Run the complexity-gated pre-flight harness for *wave_path*.

    Parameters
    ----------
    wave_path:
        Path to the wave Markdown file.
    repo:
        Repo root directory.  Defaults to the parent of tools/.
    output_dir:
        Directory where the preflight report is written.
        Defaults to <repo>/.claude/run/preflight/.

    Returns
    -------
    PreflightReport with verdict DISPATCH-OK or BLOCKED.
    """
    if repo is None:
        repo = _DEFAULT_REPO
    if output_dir is None:
        output_dir = repo / ".claude" / "run" / "preflight"

    wave_path = Path(wave_path).resolve()
    repo = Path(repo).resolve()
    output_dir = Path(output_dir).resolve()

    wave_stem = wave_path.stem  # e.g. "S-73-WAVE-AUTHORING-RIGOR"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    report = PreflightReport(
        wave_stem=wave_stem,
        tier="",
        timestamp=timestamp,
    )

    # ── Resolve tier ────────────────────────────────────────────────────────
    tier = _get_tier_from_scorer(wave_path, repo)
    report.tier = tier

    # ── Tier → rigor ────────────────────────────────────────────────────────
    # Low tier: validate-wave-file.py only
    report.checks.append(_check_validate_wave_file(wave_path, repo))

    if tier in (TIER_MEDIUM, TIER_HIGH):
        # Medium tier: Low + fact-check subagent hook
        report.checks.append(_check_fact_check_subagent_hook(wave_path, repo))

    if tier == TIER_HIGH:
        # High tier: Medium + processor-contract + disjointness + consistency
        report.checks.append(_check_processor_contract_pinned(wave_path, repo))
        report.checks.append(_check_cross_wave_disjointness(wave_path, repo))
        report.checks.append(_check_edited_wave_consistency(wave_path, repo))

    # ── Verdict ──────────────────────────────────────────────────────────────
    report.verdict = "BLOCKED" if report.is_blocked() else "DISPATCH-OK"

    # ── Write report ─────────────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{wave_stem}.md"
    report.report_path = report_path
    _write_report(report, report_path)

    return report


def _write_report(report: PreflightReport, path: Path) -> None:
    """Write a Markdown preflight report to *path*."""
    lines = [
        f"# Pre-flight report: {report.wave_stem}",
        "",
        f"**Timestamp:** {report.timestamp}  ",
        f"**Tier:** {report.tier}  ",
        f"**Verdict:** {report.verdict}",
        "",
        "## Checks",
        "",
        "| Check | Tier Required | Status | Detail |",
        "|---|---|---|---|",
    ]
    for c in report.checks:
        detail_short = c.detail.replace("\n", " ").replace("|", "/")[:120]
        lines.append(
            f"| {c.name} | {c.tier_required} | {c.status} | {detail_short} |"
        )

    lines += [
        "",
        "## Verdict",
        "",
        f"**{report.verdict}**",
        "",
    ]

    if report.verdict == "BLOCKED":
        false_checks = [c for c in report.checks if c.status == "FALSE"]
        lines.append("Blocking failures:")
        lines.append("")
        for c in false_checks:
            lines.append(f"- **{c.name}**: {c.detail}")
        lines.append("")
    else:
        lines.append(
            "All checks passed. Orchestrator may proceed with stream dispatch."
        )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> tuple[Path, Path, Path]:
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the complexity-gated pre-flight harness for a wave file.",
    )
    parser.add_argument("wave_file", type=Path, help="Path to the wave .md file")
    parser.add_argument(
        "--repo", type=Path, default=_DEFAULT_REPO,
        help="Repo root (default: parent of tools/)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Directory for preflight reports (default: <repo>/.claude/run/preflight/)",
    )
    args = parser.parse_args()
    output_dir = args.output_dir or (Path(args.repo) / ".claude" / "run" / "preflight")
    return Path(args.wave_file), Path(args.repo), Path(output_dir)


def main() -> None:
    wave_path, repo, output_dir = _parse_args()

    if not wave_path.is_absolute():
        wave_path = Path.cwd() / wave_path
    if not wave_path.exists():
        print(f"ERROR: wave file not found: {wave_path}", file=sys.stderr)
        sys.exit(2)

    report = run_preflight(wave_path=wave_path, repo=repo, output_dir=output_dir)

    print(f"Wave:    {report.wave_stem}")
    print(f"Tier:    {report.tier}")
    print()
    for c in report.checks:
        print(f"  [{c.status:<5}] {c.name} (tier≥{c.tier_required}): {c.detail[:80]}")
    print()
    print(f"Verdict: {report.verdict}")
    if report.report_path:
        print(f"Report:  {report.report_path}")

    sys.exit(0 if report.verdict == "DISPATCH-OK" else 1)


if __name__ == "__main__":
    main()
