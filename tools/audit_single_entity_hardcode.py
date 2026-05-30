#!/usr/bin/env python3
"""tools/audit_single_entity_hardcode.py — BATCH-11 S6 (R10 / BACKLOG:58).

The GROUND red-signal for CLAUDE.md's **Reuse-and-blast-radius checkpoint**. That rule
says: when a tool's operand is a member of a KNOWN plural set (the 3 repo rings, the
sanctioned-channel hierarchy, ...), you must PARAMETERIZE THE INTERFACE over the set
(a `--repo`/registry param), not hardcode one member. Hardcoding a single entity when
the set is plural is a defect UNLESS the scope-reason is recorded.

This scanner makes that rule red-eligible against physics: it greps `tools/` +
`tools/sanctioned/` for a SLOP-only hardcoded literal (an absolute path under the SLOP
repo root) in a tool that exposes NO `--repo`/registry parameter — i.e. the plural-set
members are foreclosed by construction. It emits the pinned vocabulary:

  verified      — no foreclosing hardcode found (every SLOP-only literal is either in a
                  tool that ALSO exposes --repo/registry, or carries a recorded
                  scope-reason).
  DRIFT         — a SLOP-only literal in a tool with no --repo param and no scope-reason.
  INDETERMINATE — a scanned file could not be parsed/read (unreachable ground).

It HONORS RECORDED SCOPE-REASONS (suppresses justified hardcodes). A hardcode is
suppressed when EITHER:
  (a) the line carries an inline `# scope-reason: ...` marker, OR
  (b) the assignment's TARGET NAME is in the per-file recorded allowlist
      (_RECORDED_SCOPE_REASONS) with a documented reason — e.g.
      lift_push_restore.py's SETTINGS_PATH is SLOP-session-specific by nature
      (the deny it lifts governs THIS session; report §2.3 cleared it).

DOGFOOD: this scanner must not itself hardcode SLOP-only. It derives the SLOP repo root
from `--repo` (default: the repo containing this file, via git rev-parse) — the literal
it hunts for is supplied, never baked in.

Usage:
  python3 tools/audit_single_entity_hardcode.py            # scan this repo
  python3 tools/audit_single_entity_hardcode.py --repo /path/to/repo
  python3 tools/audit_single_entity_hardcode.py --scan-file <file>  # one file (tests)
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

# Directories scanned (the sibling families named in the Reuse checkpoint).
_SCAN_DIRS = ("tools",)  # includes tools/sanctioned recursively

# Parameter names that prove the interface is parameterized over the set.
_REPO_PARAM_TOKENS = ("--repo", "--host", "--branch", "registry", "REGISTRY")

# Inline marker that records a scope-reason on the offending line/statement.
_SCOPE_REASON_MARKER = "scope-reason:"

# Recorded allowlist: {filename: {target_name: reason}} — the day-one suppressions.
# Each entry is a deliberate, reviewed scope-reason (report §2.3 "Cleared").
_RECORDED_SCOPE_REASONS: dict[str, dict[str, str]] = {
    "lift_push_restore.py": {
        "SETTINGS_PATH": (
            "the settings file IS SLOP-session-specific by nature — the deny it lifts "
            "governs THIS session, not the target repo; report §2.3 cleared it "
            "(docstring lines 27-30). The push TARGET is already --repo-parameterized."
        ),
    },
}


def _slop_root(repo_arg: str | None) -> Path:
    """Derive the SLOP repo root (the literal we hunt for) — never hardcoded.

    Order: explicit --repo, else `git rev-parse --show-toplevel` from this file's dir.
    """
    if repo_arg:
        return Path(repo_arg).resolve()
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=here, capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return here.parent  # tools/ -> repo root


def _iter_target_names(node: ast.AST) -> list[str]:
    """Return the assignment target names for an Assign/AnnAssign node."""
    names: list[str] = []
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.append(t.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.append(node.target.id)
    return names


def scan_file(path: Path, slop_root: str, lines: list[str]) -> tuple[bool, bool, list[str]]:
    """Scan one file. Returns (found_drift, found_indeterminate, finding_lines).

    `slop_root` is the SLOP-only literal prefix; `lines` is the raw source split for
    inline-marker checks.
    """
    findings: list[str] = []
    src = "".join(lines)
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return False, True, [f"INDETERMINATE: could not parse {path.name} (AST): {exc}"]

    # Does the FILE expose a --repo/registry parameter anywhere? (interface-level check)
    file_parameterized = any(tok in src for tok in _REPO_PARAM_TOKENS)

    rel_name = path.name
    recorded = _RECORDED_SCOPE_REASONS.get(rel_name, {})

    drift = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        literal = node.value
        if slop_root not in literal:
            continue
        lineno = getattr(node, "lineno", 0)
        raw_line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""

        # Suppression (a): inline scope-reason marker on the line.
        if _SCOPE_REASON_MARKER in raw_line:
            findings.append(f"suppressed (inline scope-reason): {rel_name}:{lineno}")
            continue

        # Suppression (b): the enclosing assignment's target is in the recorded allowlist.
        suppressed = False
        for anc in ast.walk(tree):
            if isinstance(anc, (ast.Assign, ast.AnnAssign)):
                if getattr(anc, "lineno", -1) == lineno:
                    for tname in _iter_target_names(anc):
                        if tname in recorded:
                            findings.append(
                                f"suppressed (recorded scope-reason {rel_name}::{tname}): "
                                f"{recorded[tname][:60]}..."
                            )
                            suppressed = True
        if suppressed:
            continue

        # Suppression (c): the file is interface-parameterized over the set.
        if file_parameterized:
            findings.append(
                f"OK (file exposes --repo/registry): {rel_name}:{lineno} contains a "
                f"SLOP-only literal but the interface is parameterized over the set"
            )
            continue

        # Otherwise: a foreclosing single-entity hardcode -> DRIFT.
        drift = True
        findings.append(
            f"DRIFT: {rel_name}:{lineno} hardcodes a SLOP-only literal "
            f"({literal!r}) and exposes NO --repo/registry param — the plural-set "
            f"members are foreclosed (CLAUDE.md Reuse-and-blast-radius checkpoint). "
            f"Parameterize the interface or record a scope-reason."
        )
    return drift, False, findings


def audit(repo: Path, slop_root: str | None = None, scan_file_path: Path | None = None) -> tuple[str, list[str]]:
    """Run the scanner. Returns (verdict, lines)."""
    literal = str(slop_root) if slop_root else str(_slop_root(str(repo)))

    if scan_file_path is not None:
        targets = [scan_file_path]
    else:
        targets = []
        for d in _SCAN_DIRS:
            base = repo / d
            if base.exists():
                targets.extend(sorted(base.rglob("*.py")))

    if not targets:
        return "INDETERMINATE", ["INDETERMINATE: no tool files found to scan (unreachable ground)"]

    all_lines: list[str] = []
    any_drift = False
    any_indeterminate = False
    for path in targets:
        # never scan ourselves for the hunt-literal (the docstring names paths legitimately)
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            file_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except Exception as exc:  # noqa: BLE001
            any_indeterminate = True
            all_lines.append(f"INDETERMINATE: could not read {path}: {exc}")
            continue
        drift, indet, findings = scan_file(path, literal, file_lines)
        any_drift = any_drift or drift
        any_indeterminate = any_indeterminate or indet
        # Only surface DRIFT + suppressions + INDETERMINATE (skip the noisy OK lines
        # unless there is nothing else, to keep the report focused).
        all_lines.extend(f for f in findings if not f.startswith("OK ("))

    if any_drift:
        return "DRIFT", all_lines or ["DRIFT (see findings)"]
    if any_indeterminate:
        return "INDETERMINATE", all_lines or ["INDETERMINATE"]
    return "verified", all_lines or [f"verified: no foreclosing SLOP-only hardcode under {_SCAN_DIRS}"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=".", help="repo root to scan (default: cwd)")
    p.add_argument("--slop-root", default=None,
                   help="the SLOP-only literal prefix to hunt for (default: derived "
                        "from --repo / git rev-parse — never hardcoded)")
    p.add_argument("--scan-file", default=None, help="scan a single file (tests)")
    args = p.parse_args(argv)

    repo = Path(args.repo).resolve()
    scan_file_path = Path(args.scan_file).resolve() if args.scan_file else None
    verdict, lines = audit(repo, slop_root=args.slop_root, scan_file_path=scan_file_path)
    for ln in lines:
        print(ln)
    print(f"VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
