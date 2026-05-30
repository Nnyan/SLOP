#!/usr/bin/env python3
"""tools/audit_sanctioned_ground.py — BATCH-11 S6 (P6): Sanctioned-channel GROUND leg.

The existing `check_sanctioned_channels_complete` gate is XREF-only: it compares the
deny-string in settings.local.json against the deny-string in the SANCTIONED-CHANNELS.md
table. Per report §4c that means **a deny pointing at a deleted/broken tool passes, and the
lift->restore cycle is never probed**.

This tool adds the GROUND leg. For every sanctioned registry-row tool named in
docs/SANCTIONED-CHANNELS.md (the GROUND source — we read the actual doc, not a hardcoded
list), it asserts via AST that the file:
  (a) EXISTS on disk;
  (b) IMPORTS or references a lift/restore helper (`lifted`, `lift`, `restore`); AND
  (c) actually CALLS lift + restore (or the `lifted` context manager) AND audits.

AST presence is necessary but NOT sufficient (report §4c: "presence != correct ordering").
The REAL proof is the per-tool RED-PATH TEST in tests/test_sanctioned_ground.py
(simulate a crash mid-push, assert the deny is RESTORED — the try/finally invariant). This
tool surfaces a tool that lifts-without-a-finally-guarded-restore as a structural DRIFT so
the gate can go red against physics, not just against a doc table.

Vocabulary (CLAUDE.md "Knowledge-Lifecycle"):
  GROUND        — touches physics (the filesystem + the AST of the real source).
  DRIFT         — a registry-row tool is missing, or does not import+call lift/restore/audit,
                  or lifts without a try/finally-guarded restore.
  INDETERMINATE — the registry doc or a tool source could not be parsed (unreachable ground).
  verified      — every registry-row tool exists and is correctly wired.

Exit code: 0 always when run standalone with --report (warn-only surface); the ms-enforce
wrapper (check_sanctioned_ground) is TIER_1 warn-only.

Usage:
  python3 tools/audit_sanctioned_ground.py            # human report
  python3 tools/audit_sanctioned_ground.py --repo .   # explicit repo root
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# Lift/restore/audit symbols a correctly-wired sanctioned tool references.
_LIFT_NAMES = frozenset({"lift", "lifted", "lift_denies"})
_RESTORE_NAMES = frozenset({"restore", "lifted", "restore_denies"})
_AUDIT_NAMES = frozenset({"write_entry"})
# Tools whose audit lives in a sibling log (MERGE-LOG / surgical routine) rather than
# _audit.write_entry; recorded scope-reason so the audit leg is INDETERMINATE not DRIFT.
_AUDIT_EXEMPT = {
    "merge_wave_to_main.py": "audits to docs/MERGE-LOG.md via its own writer (not _audit.write_entry)",
    "lift_push_restore.py": "UNAUDITED routine push by design (docstring lines 9-19)",
}


def _registry_tool_paths(channels_md: str, repo: Path) -> list[tuple[str, Path]]:
    """GROUND-parse the Registry table of SANCTIONED-CHANNELS.md.

    Returns (label, path) for every distinct `tools/...py` referenced in the
    second column of a Registry-table row. We read the live doc rather than a
    hardcoded list so the gate tracks the registry (open to new rows).
    """
    out: dict[str, Path] = {}
    in_registry = False
    for line in channels_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Registry"):
            in_registry = True
            continue
        if in_registry and stripped.startswith("## "):
            break  # left the Registry section
        if not (in_registry and stripped.startswith("|")):
            continue
        # second cell holds the tool path, possibly backtick-wrapped, possibly with
        # a parenthetical subcommand note: `tools/sanctioned/robot_settings.py (push...)`
        cells = [c.strip() for c in stripped.split("|")]
        # leading empty cell from the split on the first |
        cells = [c for c in cells if c != ""]
        if len(cells) < 2:
            continue
        tool_cell = cells[1]
        m = re.search(r"`?(tools/[\w./-]+\.py)`?", tool_cell)
        if not m:
            continue
        rel = m.group(1)
        out[rel] = repo / rel
    return sorted(out.items())


def _ast_wiring(src: str) -> dict[str, bool]:
    """Return which wiring legs are present by AST inspection of *src*.

    Legs: imports_lift_restore, calls_lift, calls_restore, calls_audit,
          restore_is_guaranteed.

    `restore_is_guaranteed` is the load-bearing leg (report §4c — presence !=
    correct ordering). It is True iff the source either:
      (a) uses the `lifted(...)` context manager (which restores in its OWN
          try/finally), OR
      (b) calls a bare restore inside a `try: ... finally:` body.
    A tool that lifts and calls restore only on the happy path (no finally) can
    leak the deny on a crash -> restore_is_guaranteed stays False -> DRIFT.
    """
    legs = {
        "imports_lift_restore": False,
        "calls_lift": False,
        "calls_restore": False,
        "calls_audit": False,
        "restore_is_guaranteed": False,
    }
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return legs  # caller treats all-False as parse failure -> INDETERMINATE

    def _callee_name(call: ast.Call) -> str | None:
        fn = call.func
        if isinstance(fn, ast.Name):
            return fn.id
        if isinstance(fn, ast.Attribute):
            return fn.attr
        return None

    def _names_in(nodes) -> set[str]:
        names: set[str] = set()
        for n in nodes:
            for sub in ast.walk(n):
                if isinstance(sub, ast.Call):
                    nm = _callee_name(sub)
                    if nm:
                        names.add(nm)
        return names

    for node in ast.walk(tree):
        # imports of lift/restore helpers (static `from ... import lifted`)
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _LIFT_NAMES | _RESTORE_NAMES | _AUDIT_NAMES:
                    legs["imports_lift_restore"] = True
        # dynamic import: importlib.spec_from_file_location("..._lift_restore", ...)
        # (merge_wave_to_main.py loads the helper this way) — count the string ref.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "_lift_restore" in node.value or "_audit" in node.value:
                legs["imports_lift_restore"] = True
        # direct calls (name or attribute)
        if isinstance(node, ast.Call):
            name = _callee_name(node)
            if name in _LIFT_NAMES:
                legs["calls_lift"] = True
            if name in _RESTORE_NAMES:
                legs["calls_restore"] = True
            if name in _AUDIT_NAMES:
                legs["calls_audit"] = True
        # `with lifted(...)`: the context manager restores in its own finally.
        if isinstance(node, ast.withitem):
            ctx = node.context_expr
            if isinstance(ctx, ast.Call) and _callee_name(ctx) == "lifted":
                legs["calls_lift"] = True
                legs["calls_restore"] = True
                legs["restore_is_guaranteed"] = True
        # bare restore inside a finally body counts as guaranteed.
        if isinstance(node, ast.Try) and node.finalbody:
            if _names_in(node.finalbody) & _RESTORE_NAMES:
                legs["restore_is_guaranteed"] = True
    return legs


def audit(repo: Path) -> tuple[str, list[str]]:
    """Run the GROUND audit. Returns (verdict_token, lines)."""
    channels = repo / "docs" / "SANCTIONED-CHANNELS.md"
    if not channels.exists():
        return "INDETERMINATE", ["INDETERMINATE: docs/SANCTIONED-CHANNELS.md not found (unreachable ground)"]
    try:
        md = channels.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return "INDETERMINATE", [f"INDETERMINATE: could not read SANCTIONED-CHANNELS.md: {exc}"]

    tools = _registry_tool_paths(md, repo)
    if not tools:
        return "INDETERMINATE", ["INDETERMINATE: no Registry-row tools parsed from SANCTIONED-CHANNELS.md"]

    lines: list[str] = []
    drift = False
    indeterminate = False

    for rel, path in tools:
        base = path.name
        if not path.exists():
            lines.append(f"DRIFT: registry-row tool {rel} does not exist on disk")
            drift = True
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"INDETERMINATE: could not read {rel}: {exc}")
            indeterminate = True
            continue
        legs = _ast_wiring(src)
        if not any(legs.values()):
            lines.append(f"INDETERMINATE: could not parse {rel} (AST)")
            indeterminate = True
            continue

        problems: list[str] = []
        if not legs["imports_lift_restore"]:
            problems.append("no lift/restore/audit import")
        if not legs["calls_lift"]:
            problems.append("never calls lift/lifted")
        if not legs["calls_restore"]:
            problems.append("never calls restore/lifted")
        if not legs["restore_is_guaranteed"]:
            # the load-bearing leg: a lift whose restore is not finally-guarded can
            # leak the deny on a crash (report §4c: presence != correct ordering). DRIFT.
            problems.append("restore not finally-guarded (deny may leak on crash mid-push)")
        if not legs["calls_audit"]:
            exempt = _AUDIT_EXEMPT.get(base)
            if exempt:
                lines.append(f"NOTE: {rel} audit-leg exempt (scope-reason: {exempt})")
            else:
                problems.append("never calls write_entry (no audit)")

        if problems:
            drift = True
            lines.append(f"DRIFT: {rel} — " + "; ".join(problems))
        else:
            lines.append(f"verified: {rel} — exists + imports + lift/restore + try/finally guarded")

    if drift:
        return "DRIFT", lines
    if indeterminate:
        return "INDETERMINATE", lines
    return "verified", lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=".", help="repo root (default: cwd)")
    args = p.parse_args(argv)
    repo = Path(args.repo).resolve()

    verdict, lines = audit(repo)
    for ln in lines:
        print(ln)
    print(f"VERDICT: {verdict}")
    # warn-only surface: standalone exit 0 unless ground was unreachable AND nothing parsed
    return 0


if __name__ == "__main__":
    sys.exit(main())
