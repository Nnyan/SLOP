#!/usr/bin/env python3
"""tools/wave_complexity.py — Wave-file complexity scorer.

Scores a wave file (Markdown) into one of three complexity tiers from
mechanical signals read out of the wave text plus light repo lookups. The
tier drives how much pre-flight rigor the orchestrator applies before
dispatch (see ROBOT.md "### Complexity-gated pre-flight").

This is a *scorer*, not a gate: it ALWAYS exits 0 and never blocks. Blocking
is the pre-flight harness's job. Pure stdlib, standalone-runnable, own tests —
matching the tools/audit_*.py and tools/validate-wave-file.py family.

Tier-string contract (PINNED — this module produces it; consumers import the
constants verbatim, never re-defining the strings):

    TIER_LOW    = "Low"
    TIER_MEDIUM = "Medium"
    TIER_HIGH   = "High"
    VALID_TIERS = ("Low", "Medium", "High")

Python API (PINNED):

    score_wave(wave_path) -> dict
        wave_path : str | pathlib.Path
        returns   : {"tier": <one of VALID_TIERS>, "score": int,
                     "signals": dict, "reasons": list[str]}
        Never raises on a well-formed wave file. Raises FileNotFoundError on
        an unreadable/missing file (callers handle).

CLI (PINNED):

    python3 tools/wave_complexity.py <wave-file> [--repo .]
        Prints a human-readable summary, then emits the bare tier string
        ("Low"/"Medium"/"High") as the FINAL stdout line so shell consumers
        can `tail -1`. Exit 0 ALWAYS.

Signals (mechanical):
    stream_count          — rows in the Parallelization stream table.
    files_touched         — distinct candidate file paths claimed/created.
    shared_symbols        — count of "PINNED" markers (shared-symbol pins).
    is_refactor           — wave text signals rewrite/refactor vs additive-only.
    sensitive_paths       — touches doctrine/security paths (.claude/settings*,
                            ROBOT.md, AUTONOMOUS-DEFAULTS, backend security /
                            migrations).
    cross_wave_overlap    — references to OTHER wave files (potential overlap).
    repo_claims           — count of path + inbound-ref assertions about the repo.
    opus_streams          — count of streams whose Model cell carries the token
                            "opus" (per Stream A's pinned Model-column format;
                            blank/inherit cells take the **Models:** default).

Score -> tier calibration (deterministic, documented so a reviewer can see why
a wave scored its tier). Each signal contributes weighted points:

    +2  per shared-symbol PINNED contract       (shared_symbols)
    +3  if any sensitive doctrine/security path  (sensitive_paths > 0)
    +2  per Opus stream                          (opus_streams)
    +2  if the wave is a refactor (not additive)  (is_refactor)
    +1  per stream beyond the first              (max(0, stream_count - 1))
    +1  if cross-wave file overlap referenced     (cross_wave_overlap > 0)
    +1  if repo_claims >= 4                        (claim-heavy wave)
    +1  if files_touched >= 6                      (broad blast radius)

    Thresholds:
        score <= 2          -> Low
        3 <= score <= 6     -> Medium
        score >= 7          -> High

    Floor guarantees (a tier can be raised by a single strong signal even if
    the additive score is borderline — these encode "any one of {shared
    symbols, sensitive paths, Opus stream} pushes toward High"):
        - sensitive_paths AND shared_symbols AND opus_streams all present
          -> High (the dogfood case: this very wave).
        - a single additive stream with no shared symbols, no sensitive
          paths, no Opus stream, not a refactor -> Low regardless of score.

This wave file (.claude/waves/S-73-WAVE-AUTHORING-RIGOR.md) MUST score High:
5 streams, 3 PINNED contracts, sensitive doctrine paths, 2 Opus streams.
A unit test pins that calibration.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── Tier-string contract (PINNED) ───────────────────────────────────────────
TIER_LOW = "Low"
TIER_MEDIUM = "Medium"
TIER_HIGH = "High"
VALID_TIERS = (TIER_LOW, TIER_MEDIUM, TIER_HIGH)

# Calibration thresholds (documented in the module docstring).
_MEDIUM_FLOOR = 3
_HIGH_FLOOR = 7

# Path-extension set mirrors validate-wave-file.py's candidate-path heuristic.
_PATH_EXTS = (
    ".py", ".md", ".yaml", ".yml", ".json", ".sh", ".toml",
    ".txt", ".rst", ".sql", ".js", ".ts", ".vue",
)

# Sensitive doctrine / security path fragments (case-insensitive substring).
_SENSITIVE_FRAGMENTS = (
    ".claude/settings",
    "robot.md",
    "autonomous-defaults",
    "backend/core/security",
    "backend/security",
    "backend/migrations",
    "/migrations/",
    "migration",
)

_REFACTOR_TOKENS = (
    "refactor",
    "rewrite",
    "rewrites",
    "consolidate",
    "restructure",
)

_CREATE_TOKENS = (
    "create",
    "build",
    "new file",
    "add ",
    "implement",
    "files created",
    "files modified",
)


def _read(wave_path: Path) -> str:
    """Read the wave file. Raises FileNotFoundError if missing/unreadable."""
    return wave_path.read_text(encoding="utf-8")


def _stream_table_rows(content: str) -> list[str]:
    """Return the data rows of the Parallelization stream table.

    A stream-table row is a Markdown table row whose header row contains a
    `Stream` column. We locate the table under the `## Parallelization`
    heading (falling back to any table with a `Stream` header) and return
    its body rows (excluding the header and the `---` separator).
    """
    lines = content.splitlines()
    rows: list[str] = []
    in_table = False
    header_seen = False
    for line in lines:
        stripped = line.strip()
        is_table_line = stripped.startswith("|") and stripped.endswith("|")
        if not in_table:
            # Detect the header row of a table that has a Stream column.
            if is_table_line and re.search(r"\bStream\b", stripped):
                cells = [c.strip().lower() for c in stripped.strip("|").split("|")]
                if "stream" in cells:
                    in_table = True
                    header_seen = False
            continue
        # Inside a table.
        if not is_table_line:
            break  # table ended
        if not header_seen:
            # This is the separator row (---|---).
            header_seen = True
            continue
        rows.append(stripped)
    return rows


def _split_cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip("|").split("|")]


def _count_opus_streams(content: str) -> int:
    """Count streams whose Model cell carries the token 'opus'.

    Per Stream A's PINNED Model-column format, the Model column sits
    immediately after `Stream`. A cell containing the case-insensitive token
    `opus` is an Opus stream. Blank / `_(blank → ...)_` cells inherit the
    `**Models:**` default line and are NOT counted here.
    """
    rows = _stream_table_rows(content)
    if not rows:
        return 0
    # The header told us a Stream column exists; the Model column (if present)
    # is the cell index 1 (immediately after Stream). We re-derive the index
    # from the original header to be robust.
    model_idx = _model_column_index(content)
    count = 0
    for row in rows:
        cells = _split_cells(row)
        if model_idx is not None and model_idx < len(cells):
            cell = cells[model_idx]
        else:
            # No dedicated Model column: scan the whole row (still honors the
            # "token opus" rule, but a blank/inherit row won't match).
            cell = row
        # Inherit markers must NOT count even if they name a model.
        if "→" in cell or "blank" in cell.lower() or "inherit" in cell.lower():
            continue
        if re.search(r"\bopus\b", cell, re.IGNORECASE):
            count += 1
    return count


def _model_column_index(content: str) -> int | None:
    """Return the column index of the `Model` header cell, or None."""
    for line in content.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip().lower() for c in stripped.strip("|").split("|")]
        if "stream" in cells and "model" in cells:
            return cells.index("model")
    return None


def _extract_candidate_paths(content: str) -> set[str]:
    """Extract candidate file paths (backtick tokens + bare path-like tokens)."""
    paths: set[str] = set()
    # Backtick-quoted tokens.
    for m in re.findall(r"`([^`]+)`", content):
        token = m.strip()
        if " " in token:
            continue  # command invocation, not a path
        if "/" in token and token.endswith(_PATH_EXTS):
            paths.add(token)
        elif token.endswith(_PATH_EXTS):
            paths.add(token)
    # Bare tokens containing a slash with a known extension.
    for m in re.findall(r"[\w./\-]+", content):
        if "/" in m and m.endswith(_PATH_EXTS) and "*" not in m:
            paths.add(m)
    return paths


def _count_shared_symbols(content: str) -> int:
    """Count PINNED markers (shared-symbol contracts)."""
    return len(re.findall(r"PINNED", content))


def _detect_refactor(content: str) -> bool:
    """True if the wave signals a refactor/rewrite rather than additive-only."""
    low = content.lower()
    # An explicit "additive only" rule overrides refactor tokens that merely
    # appear in prohibitions ("no rewrites").
    additive_only = bool(re.search(r"additive[\s\-]*only", low))
    if additive_only:
        return False
    return any(tok in low for tok in _REFACTOR_TOKENS)


def _count_sensitive_paths(content: str) -> int:
    """Count distinct sensitive doctrine/security path fragments referenced."""
    low = content.lower()
    hits = 0
    for frag in _SENSITIVE_FRAGMENTS:
        if frag in low:
            hits += 1
    return hits


def _count_cross_wave_overlap(content: str, wave_path: Path) -> int:
    """Count references to OTHER wave files (.claude/waves/<other>.md)."""
    this_name = wave_path.name
    refs = re.findall(r"\.claude/waves/([A-Za-z0-9_\-]+\.md)", content)
    others = {r for r in refs if r != this_name and not r.startswith("_")}
    return len(others)


def _count_repo_claims(content: str) -> int:
    """Count path + inbound-ref assertions about the repo.

    A repo-claim is an assertion the pre-flight could fact-check: an
    inbound-ref count ("referenced N times", "grep ... N"), an
    "exists"/"already exists" assertion, or a line-number citation
    ("line NN", "lines NN-MM").
    """
    claims = 0
    claims += len(re.findall(r"referenced\s+\d+\s+times", content, re.IGNORECASE))
    claims += len(re.findall(r"\b\d+\s+inbound\s+ref", content, re.IGNORECASE))
    claims += len(re.findall(r"already exists", content, re.IGNORECASE))
    claims += len(re.findall(r"\bline\s+\d+", content, re.IGNORECASE))
    claims += len(re.findall(r"\blines\s+\d+", content, re.IGNORECASE))
    return claims


def _count_files_touched(content: str) -> int:
    return len(_extract_candidate_paths(content))


def _collect_signals(content: str, wave_path: Path) -> dict:
    rows = _stream_table_rows(content)
    return {
        "stream_count": len(rows),
        "files_touched": _count_files_touched(content),
        "shared_symbols": _count_shared_symbols(content),
        "is_refactor": _detect_refactor(content),
        "sensitive_paths": _count_sensitive_paths(content),
        "cross_wave_overlap": _count_cross_wave_overlap(content, wave_path),
        "repo_claims": _count_repo_claims(content),
        "opus_streams": _count_opus_streams(content),
    }


def _score_signals(sig: dict) -> tuple[int, list[str]]:
    """Apply the documented weighting. Returns (score, reasons)."""
    score = 0
    reasons: list[str] = []

    if sig["shared_symbols"]:
        pts = 2 * sig["shared_symbols"]
        score += pts
        reasons.append(
            f"+{pts}: {sig['shared_symbols']} PINNED shared-symbol marker(s)"
        )
    if sig["sensitive_paths"]:
        score += 3
        reasons.append(
            f"+3: touches {sig['sensitive_paths']} sensitive doctrine/security path(s)"
        )
    if sig["opus_streams"]:
        pts = 2 * sig["opus_streams"]
        score += pts
        reasons.append(f"+{pts}: {sig['opus_streams']} Opus stream(s)")
    if sig["is_refactor"]:
        score += 2
        reasons.append("+2: refactor/rewrite (not additive-only)")
    extra_streams = max(0, sig["stream_count"] - 1)
    if extra_streams:
        score += extra_streams
        reasons.append(f"+{extra_streams}: {sig['stream_count']} parallel streams")
    if sig["cross_wave_overlap"]:
        score += 1
        reasons.append(
            f"+1: references {sig['cross_wave_overlap']} other wave file(s)"
        )
    if sig["repo_claims"] >= 4:
        score += 1
        reasons.append(f"+1: claim-heavy ({sig['repo_claims']} repo claims)")
    if sig["files_touched"] >= 6:
        score += 1
        reasons.append(f"+1: broad blast radius ({sig['files_touched']} files)")

    return score, reasons


def _tier_for(score: int, sig: dict) -> tuple[str, list[str]]:
    """Map score + floor-guarantees to a tier. Returns (tier, extra_reasons)."""
    extra: list[str] = []

    # Floor guarantee: all three strong High signals present -> High.
    if sig["sensitive_paths"] and sig["shared_symbols"] and sig["opus_streams"]:
        extra.append(
            "FLOOR->High: shared symbols + sensitive paths + Opus stream all present"
        )
        return TIER_HIGH, extra

    # Floor guarantee: a single purely-additive stream with no strong signals -> Low.
    if (
        sig["stream_count"] <= 1
        and not sig["shared_symbols"]
        and not sig["sensitive_paths"]
        and not sig["opus_streams"]
        and not sig["is_refactor"]
    ):
        extra.append("FLOOR->Low: single additive stream, no strong signals")
        return TIER_LOW, extra

    if score >= _HIGH_FLOOR:
        return TIER_HIGH, extra
    if score >= _MEDIUM_FLOOR:
        return TIER_MEDIUM, extra
    return TIER_LOW, extra


def score_wave(wave_path) -> dict:
    """Score a wave file -> {tier, score, signals, reasons} (PINNED API).

    `wave_path` accepts str or pathlib.Path. Never raises on a well-formed
    wave file; raises FileNotFoundError on a missing/unreadable file.
    """
    path = Path(wave_path)
    content = _read(path)  # FileNotFoundError propagates for missing files.

    signals = _collect_signals(content, path)
    score, reasons = _score_signals(signals)
    tier, extra = _tier_for(score, signals)
    reasons.extend(extra)

    assert tier in VALID_TIERS  # contract self-check
    return {
        "tier": tier,
        "score": score,
        "signals": signals,
        "reasons": reasons,
    }


def _format_summary(wave_path: Path, result: dict) -> str:
    lines = [f"Wave: {wave_path}"]
    lines.append("Signals:")
    for k, v in result["signals"].items():
        lines.append(f"  {k}: {v}")
    lines.append(f"Score: {result['score']}")
    lines.append("Reasons:")
    for r in result["reasons"]:
        lines.append(f"  {r}")
    lines.append(f"Tier: {result['tier']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a wave file into a complexity tier (Low/Medium/High).",
    )
    parser.add_argument("wave_file", help="Path to the wave Markdown file.")
    parser.add_argument(
        "--repo", default=".",
        help="Repo root (reserved for light repo lookups; default '.').",
    )
    args = parser.parse_args(argv)

    wave_path = Path(args.wave_file)
    if not wave_path.is_absolute():
        wave_path = Path.cwd() / wave_path

    try:
        result = score_wave(wave_path)
    except FileNotFoundError:
        print(f"ERROR: wave file not found: {wave_path}", file=sys.stderr)
        # Scoring is informational; even on missing file we keep exit 0 per the
        # PINNED CLI contract ("Exit 0 ALWAYS"). Emit nothing as the tier line
        # would be misleading; print a sentinel so tail -1 is unambiguous.
        print("ERROR")
        return 0

    print(_format_summary(wave_path, result))
    # FINAL stdout line: the bare tier string (shell consumers tail -1).
    print(result["tier"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
