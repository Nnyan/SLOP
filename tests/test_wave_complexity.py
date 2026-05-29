"""tests/test_wave_complexity.py — tests for the wave complexity scorer.

Covers the PINNED tier-string contract, the score->tier calibration across
Low/Medium/High fixtures, the Model-column Opus detection, and the CLI's
final-line tier contract. Pure stdlib; no external deps.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "wave_complexity.py"

sys.path.insert(0, str(REPO / "tools"))
import wave_complexity as wc  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────

LOW_WAVE = """# S-XX-LOW — a trivial additive wave

## Goal
Add a small helper.

## Rules to follow
- **Additive only.** New file `backend/util/helper.py`.

## Parallelization
**Models:** subagents = **sonnet**

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A — add helper | _(blank → sonnet)_ | parallel | general-purpose | Create `backend/util/helper.py` |

## Deliverables per stream
### Stream A
1. Create `backend/util/helper.py` with one function.

## Verification
1. pytest passes.
"""

MEDIUM_WAVE = """# S-XX-MED — a multi-stream wave

## Goal
Two parallel additive streams plus some repo claims.

## Rules to follow
- **Additive only.**

## Parallelization
**Models:** subagents = **sonnet**

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A — add foo | _(blank → sonnet)_ | parallel | general-purpose | Create `backend/foo.py` |
| B — add bar | _(blank → sonnet)_ | parallel | general-purpose | Create `backend/bar.py` |
| C — add baz | _(blank → sonnet)_ | parallel | general-purpose | Create `backend/baz.py` |

## Deliverables per stream
### Stream A
- `helper_thing` is referenced 2 times today (see line 10).
- It already exists at `backend/foo.py`.
- See lines 40-50 for context.

### Stream B
- Create `backend/bar.py`.

### Stream C
- Create `backend/baz.py`.

## Verification
1. pytest passes.
"""

HIGH_WAVE = """# S-XX-HIGH — a contract-heavy doctrine wave

## Goal
Shared symbols across streams, touches doctrine, has an Opus stream.

## Rules to follow
- **Additive only.**

## Parallelization
**Models:** coordinator = **opus**, subagents = **sonnet**

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A — contract owner | **opus** | parallel | general-purpose | Edit `.claude/ROBOT.md` and own the PINNED contract |
| B — consumer | _(blank → sonnet)_ | parallel | general-purpose | Consume the PINNED `do_thing()` symbol |

## Deliverables per stream
### Stream A
1. **Contract (PINNED — A produces, B consumes):** the symbol `do_thing()`.
   Also edit `.claude/AUTONOMOUS-DEFAULTS.md`.

### Stream B
1. Consume the PINNED contract from A; touch `backend/migrations/0001.py`.

## Verification
1. pytest passes.
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ── Tier-string contract ─────────────────────────────────────────────────────

def test_valid_tiers_contract_pinned():
    assert wc.VALID_TIERS == ("Low", "Medium", "High")
    assert wc.TIER_LOW == "Low"
    assert wc.TIER_MEDIUM == "Medium"
    assert wc.TIER_HIGH == "High"


# ── score_wave API + calibration ─────────────────────────────────────────────

def test_low_wave_scores_low(tmp_path):
    p = _write(tmp_path, "S-XX-LOW.md", LOW_WAVE)
    result = wc.score_wave(p)
    assert result["tier"] in wc.VALID_TIERS
    assert result["tier"] == wc.TIER_LOW
    assert isinstance(result["score"], int)
    assert isinstance(result["signals"], dict)
    assert isinstance(result["reasons"], list)


def test_medium_wave_scores_medium(tmp_path):
    p = _write(tmp_path, "S-XX-MED.md", MEDIUM_WAVE)
    result = wc.score_wave(p)
    assert result["tier"] in wc.VALID_TIERS
    assert result["tier"] == wc.TIER_MEDIUM
    assert result["signals"]["stream_count"] == 3
    assert result["signals"]["opus_streams"] == 0
    assert result["signals"]["repo_claims"] >= 4


def test_high_wave_scores_high(tmp_path):
    p = _write(tmp_path, "S-XX-HIGH.md", HIGH_WAVE)
    result = wc.score_wave(p)
    assert result["tier"] in wc.VALID_TIERS
    assert result["tier"] == wc.TIER_HIGH
    assert result["signals"]["shared_symbols"] >= 1
    assert result["signals"]["sensitive_paths"] >= 1
    assert result["signals"]["opus_streams"] == 1


def test_accepts_str_and_path(tmp_path):
    p = _write(tmp_path, "S-XX-LOW.md", LOW_WAVE)
    assert wc.score_wave(str(p))["tier"] == wc.score_wave(p)["tier"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        wc.score_wave(tmp_path / "does-not-exist.md")


# ── Model-column Opus detection ──────────────────────────────────────────────

def test_blank_inherit_cell_not_flagged_opus(tmp_path):
    p = _write(tmp_path, "S-XX-MED.md", MEDIUM_WAVE)
    # All cells are blank/inherit -> zero Opus streams even though the
    # **Models:** default exists.
    assert wc.score_wave(p)["signals"]["opus_streams"] == 0


def test_opus_cell_flagged(tmp_path):
    p = _write(tmp_path, "S-XX-HIGH.md", HIGH_WAVE)
    assert wc.score_wave(p)["signals"]["opus_streams"] == 1


# ── Dogfood: this very wave file must score High ─────────────────────────────

def test_s73_dogfoods_to_high():
    wave = REPO / ".claude" / "waves" / "S-73-WAVE-AUTHORING-RIGOR.md"
    if not wave.exists():
        pytest.skip("S-73 wave file not present in this checkout")
    result = wc.score_wave(wave)
    assert result["tier"] == wc.TIER_HIGH
    assert result["signals"]["opus_streams"] == 2


# ── CLI contract: final stdout line is the bare tier ─────────────────────────

def _run_cli(wave_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), str(wave_path)],
        capture_output=True, text=True, cwd=str(REPO),
    )


def test_cli_final_line_is_bare_tier_low(tmp_path):
    p = _write(tmp_path, "S-XX-LOW.md", LOW_WAVE)
    cp = _run_cli(p)
    assert cp.returncode == 0
    final = cp.stdout.rstrip("\n").splitlines()[-1]
    assert final in wc.VALID_TIERS
    assert final == wc.TIER_LOW


def test_cli_final_line_is_bare_tier_high(tmp_path):
    p = _write(tmp_path, "S-XX-HIGH.md", HIGH_WAVE)
    cp = _run_cli(p)
    assert cp.returncode == 0
    final = cp.stdout.rstrip("\n").splitlines()[-1]
    assert final == wc.TIER_HIGH


def test_cli_exit_zero_on_missing_file():
    cp = subprocess.run(
        [sys.executable, str(TOOL), "/nonexistent/wave.md"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert cp.returncode == 0  # PINNED: exit 0 always


def test_cli_dogfood_s73_high():
    wave = REPO / ".claude" / "waves" / "S-73-WAVE-AUTHORING-RIGOR.md"
    if not wave.exists():
        pytest.skip("S-73 wave file not present")
    cp = _run_cli(wave)
    assert cp.returncode == 0
    assert cp.stdout.rstrip("\n").splitlines()[-1] == "High"
