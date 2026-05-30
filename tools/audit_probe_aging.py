#!/usr/bin/env python3
"""audit_probe_aging.py — GROUND-gate brownout detector / probe-aging engine (BATCH-11 P0).

The cross-cutting reconciler that closes the **"GROUND-gate brownout" class**
(report 4g): *a probe that degrades to INDETERMINATE / unparseable /
missing-input / no-date keeps returning the same color as a match.* No single
gate treats **sustained INDETERMINATE** as a defect — so this engine does.

For every REGISTERED probe (``tools/probe_registry.json`` — an OPEN SEAM other
streams append to; see ``docs/PROBE-REGISTRY.md``) it runs the probe's ``cmd``
and records per run whether the probe **reached ground** (emitted a
``verified``/``DRIFT`` token, i.e. it touched physics and matched or mismatched)
or **browned out** (``INDETERMINATE`` / unparseable / missing-input / no-date /
a configured-host rc127 / a WRONG-target value). A probe with **no ground-touch
in N consecutive runs** (default N=5) ages to **DRIFT** — the gate goes red, not
green, when its ground goes unreachable.

Vocabulary (PINNED by CLAUDE.md "Knowledge-Lifecycle & reconciliation" — used
verbatim):
  GROUND        — probe touches physics; result may say ``verified`` or ``DRIFT``.
  XREF          — text-vs-text; may only flag ``INCONSISTENT``.
  INDETERMINATE — ground truth was unreachable; emitted LOUDLY, never downgraded.
  UNPROBED      — no probe exists for this fact yet; ratchet may shrink not grow.

Verdict tokens this engine emits per probe:
  GROUND-TOUCH  — the probe reached ground this run (verified or DRIFT seen).
  BROWNOUT      — the probe did NOT reach ground this run (one of the modes above).
  DRIFT         — a probe has browned out for >= N consecutive runs (the aging red).

Brownout sub-classes recorded for diagnosis (all are "did not touch ground"):
  indeterminate     — output carried an INDETERMINATE/unreachable/skip token.
  unparseable       — output carried NO ground token and NO brownout token.
  configured-rc127  — host_configured probe exited 127 (should be installed -> DRIFT-eligible).
  no-host           — non-host_configured probe could not reach a host (quiet — don't cry wolf).
  wrong-target      — probe emitted a value, but for the WRONG physical target (LR-2 class).

Ratchet (shrink-only, sibling to ``.factprobe-baseline.json``): the per-probe
brownout-streak state lives in ``.probe-health-baseline.json``. Missing baseline
= "establish, don't alarm" (first run writes it). The number of currently-aged
(DRIFT) probes is ratcheted shrink-only — it may decrease freely, but a growing
aged count emits a WARNING. The baseline state is itself stored; per the K-L
rule it is reconciled against the live run every invocation, never trusted blind.

Exit code: always 0 (warn-only TIER_1 gate).

Usage
-----
  python3 tools/audit_probe_aging.py [options]

  --repo DIR        Repo root (default: parent of this script's dir).
  --registry PATH   Probe registry JSON (default: <repo>/tools/probe_registry.json).
  --baseline PATH   Health baseline JSON (default: <repo>/.probe-health-baseline.json).
  --runs-to-red N   Consecutive brownout runs before DRIFT (default: 5).
  --record          Persist the updated streak state to the baseline (the normal
                    per-run mode). Without it, the run is read-only (no write).
  --update-shrunk   Shrink the aged-count ratchet to the current (lower) count.
  --dry-run         Never write the baseline (overrides --record).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_RUNS_TO_RED = 5
REGISTRY_FILENAME = "tools/probe_registry.json"
BASELINE_FILENAME = ".probe-health-baseline.json"


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

def load_registry(registry_path: Path) -> list[dict[str, Any]]:
    """Load the OPEN-SEAM probe registry. Returns the list of probe rows.

    A missing/unparseable registry returns [] (the engine then has nothing to
    age — honest, not a crash).
    """
    if not registry_path.exists():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    probes = data.get("probes", [])
    return [p for p in probes if isinstance(p, dict) and p.get("id")]


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------

def _run_cmd(cmd: str, repo: Path, timeout: int = 30) -> tuple[int, str]:
    """Run *cmd* in a shell rooted at *repo*. Returns (returncode, combined output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(repo),
        )
        return result.returncode, (result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return 1, f"ERROR: {exc}"


def _wrong_target_hit(probe: dict[str, Any], output: str) -> bool:
    """True if a probe emitted a value but for the WRONG physical target (LR-2 class).

    Reads the probe's ``wrong_target`` spec: a JSON field name and a list of
    known-wrong values. If the probe's JSON output carries that field with a
    wrong value, this is a WRONG-PHYSICS brownout, NOT a ground touch.
    """
    spec = probe.get("wrong_target")
    if not isinstance(spec, dict):
        return False
    field = spec.get("json_field")
    wrong_values = spec.get("wrong_values", [])
    if not field:
        return False
    try:
        # The probe's output may have trailing log lines; find the JSON object.
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                obj = json.loads(line)
                if field in obj and obj[field] in wrong_values:
                    return True
    except (json.JSONDecodeError, ValueError):
        return False
    return False


def classify_run(probe: dict[str, Any], rc: int, output: str) -> tuple[bool, str]:
    """Classify one probe run as a ground touch or a brownout.

    Returns (ground_touched, subclass).
      ground_touched True  -> subclass == "ground"
      ground_touched False -> subclass in {indeterminate, unparseable,
                              configured-rc127, no-host, wrong-target}
    """
    ground_tokens = [t for t in probe.get("ground_tokens", [])]
    brownout_tokens = [t for t in probe.get("brownout_tokens", [])]
    host_configured = bool(probe.get("host_configured", False))

    # WRONG-target is a brownout even though a value was emitted (LR-2 class).
    if _wrong_target_hit(probe, output):
        return False, "wrong-target"

    # rc127 = "command not found" (the LR-2 install-miss signature).
    if rc == 127:
        # Configured host that should have the probe installed -> DRIFT-eligible.
        # No host configured -> quiet (do not cry wolf in a headless context).
        return (False, "configured-rc127") if host_configured else (False, "no-host")

    # Did the probe emit a ground token (verified / DRIFT / a bound value)?
    if any(tok in output for tok in ground_tokens):
        return True, "ground"

    # Explicit brownout token (INDETERMINATE / unreachable / skip / dateless ...).
    if any(tok in output for tok in brownout_tokens):
        return False, "indeterminate"

    # No ground token AND no brownout token = unparseable -> brownout (not a pass).
    return False, "unparseable"


# ---------------------------------------------------------------------------
# Baseline (shrink-only ratchet on the aged count; per-probe streak state)
# ---------------------------------------------------------------------------

def load_baseline(baseline_path: Path) -> dict[str, Any]:
    if not baseline_path.exists():
        return {"generated_at": "", "aged_count": None, "probes": {}}
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"generated_at": "", "aged_count": None, "probes": {}}
    data.setdefault("probes", {})
    data.setdefault("aged_count", None)
    return data


def dump_baseline(baseline_path: Path, data: dict[str, Any]) -> None:
    data["generated_at"] = (
        _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    )
    baseline_path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run(
    repo: Path,
    registry_path: Path,
    baseline_path: Path,
    *,
    runs_to_red: int = DEFAULT_RUNS_TO_RED,
    record: bool = False,
    update_shrunk: bool = False,
    dry_run: bool = False,
) -> tuple[bool, str, list[str]]:
    """Run every registered probe, age the brownout streaks, return (ok, summary, lines).

    Always returns ok=True (warn-only TIER_1). ``lines`` is the per-probe report.
    """
    probes = load_registry(registry_path)
    baseline = load_baseline(baseline_path)
    prior_streaks: dict[str, Any] = baseline.get("probes", {})

    establishing = baseline.get("aged_count") is None

    lines: list[str] = []
    new_streaks: dict[str, Any] = {}
    aged_drift: list[str] = []
    ground_count = 0
    brownout_count = 0

    for probe in probes:
        pid = probe["id"]
        rc, output = _run_cmd(probe["cmd"], repo)
        touched, subclass = classify_run(probe, rc, output)

        prior = prior_streaks.get(pid, {})
        prior_streak = int(prior.get("brownout_streak", 0))

        if touched:
            ground_count += 1
            streak = 0
            verdict = "GROUND-TOUCH"
            lines.append(f"GROUND-TOUCH:  {pid}  (touched physics this run)")
        else:
            brownout_count += 1
            streak = prior_streak + 1
            verdict = "BROWNOUT"
            lines.append(
                f"BROWNOUT:      {pid}  ({subclass}; streak {streak}/{runs_to_red})"
            )

        new_streaks[pid] = {
            "brownout_streak": streak,
            "last_subclass": subclass,
            "last_touched_ground": touched,
        }

        # Aging red: N consecutive brownout runs -> DRIFT.
        if streak >= runs_to_red:
            aged_drift.append(pid)
            lines.append(
                f"DRIFT:         {pid}  (no ground-touch in {streak} consecutive runs "
                f">= N={runs_to_red} — brownout aged red [{subclass}])"
            )
        # A configured-host rc127 is DRIFT immediately (it should be installed).
        elif not touched and new_streaks[pid]["last_subclass"] == "configured-rc127":
            aged_drift.append(pid)
            lines.append(
                f"DRIFT:         {pid}  (configured host returned rc127 — probe should "
                f"be installed; LR-2 class)"
            )
        # A WRONG-target value is DRIFT immediately (the probe is lying about physics).
        elif not touched and new_streaks[pid]["last_subclass"] == "wrong-target":
            aged_drift.append(pid)
            lines.append(
                f"DRIFT:         {pid}  (emitted a value for the WRONG target — "
                f"WRONG-PHYSICS defect; not a pass)"
            )

    aged_count = len(aged_drift)

    # Ratchet (shrink-only on aged_count).
    ratchet_warnings: list[str] = []
    stored_aged = baseline.get("aged_count")
    if stored_aged is not None and aged_count > stored_aged:
        ratchet_warnings.append(
            f"WARNING: aged-probe count {aged_count} exceeds baseline {stored_aged} "
            f"(more probes browned out red — fix the probe or its ground source)"
        )

    # Persist (record mode), honoring dry-run and shrink-only semantics.
    if not dry_run and (record or establishing):
        new_baseline: dict[str, Any] = {"probes": new_streaks}
        if establishing:
            # First run: establish, don't alarm — store the current aged count.
            new_baseline["aged_count"] = aged_count
        elif update_shrunk and aged_count < stored_aged:
            new_baseline["aged_count"] = aged_count
        else:
            # Keep the stored ratchet ceiling unless explicitly shrunk; still
            # refresh the per-probe streaks so aging accrues run-over-run.
            new_baseline["aged_count"] = stored_aged
        dump_baseline(baseline_path, new_baseline)

    for ln in ratchet_warnings:
        lines.append(ln)

    parts = [
        f"{ground_count} GROUND-TOUCH",
        f"{brownout_count} BROWNOUT",
        f"{aged_count} aged DRIFT",
    ]
    if establishing:
        parts.append("(baseline established — establish-not-alarm)")
    if ratchet_warnings:
        parts.append(f"{len(ratchet_warnings)} RATCHET-WARNING")
    summary = "probe-aging: " + ", ".join(parts)
    if aged_drift and not establishing:
        summary += " — DRIFT: " + ", ".join(sorted(aged_drift))
    return True, summary, lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, type=Path)
    parser.add_argument("--registry", default=None, type=Path)
    parser.add_argument("--baseline", default=None, type=Path)
    parser.add_argument("--runs-to-red", type=int, default=DEFAULT_RUNS_TO_RED,
                        dest="runs_to_red")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--update-shrunk", action="store_true", dest="update_shrunk")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    args = parser.parse_args(argv)

    repo = args.repo.resolve() if args.repo else Path(__file__).resolve().parent.parent
    registry = args.registry.resolve() if args.registry else (repo / REGISTRY_FILENAME)
    baseline = args.baseline.resolve() if args.baseline else (repo / BASELINE_FILENAME)

    _ok, summary, lines = run(
        repo, registry, baseline,
        runs_to_red=args.runs_to_red,
        record=args.record,
        update_shrunk=args.update_shrunk,
        dry_run=args.dry_run,
    )
    for ln in lines:
        print(ln)
    print(f"\n{summary}", file=sys.stderr)
    sys.exit(0)  # always 0 — warn-only TIER_1


if __name__ == "__main__":
    main()
