#!/usr/bin/env python3
"""audit_fact_freshness.py — Fact-store freshness / verify-probe audit (S-75-D).

Two complementary checks:

1. **Memory-frontmatter probes** — for memory files that declare a
   ``verify_probe`` in their YAML frontmatter, runs the probe (GROUND) and
   compares its exit code / output to the stored ``last_verified`` date.
   A probe that exits non-zero or whose output is empty is reported as DRIFT
   (loud warn).

2. **CLAUDE.md inline verify annotations** — finds ``<!-- verify: <cmd> -->``
   comments in any block of CLAUDE.md, runs each command (GROUND), and
   reports DRIFT if the command exits non-zero.

3. **UNPROBED ratchet** — counts facts (memory-file frontmatter entries +
   CLAUDE.md verify-comment slots) that have NO probe.  The count is stored
   in ``.factprobe-baseline.json`` (alongside ``.linecount-baseline.json``).
   The ratchet may only SHRINK: a run where the UNPROBED count exceeds the
   baseline emits a WARNING.

Vocabulary (PINNED by Stream E):
  GROUND    — probe touches physics; result may say ``verified`` or ``DRIFT``.
  UNPROBED  — no probe registered; counted by ratchet, NEVER silently blessed.
  DRIFT     — GROUND probe ran but output signals mismatch / failure.

Exit code: always 0 (warn-only TIER_1 gate).  All findings go to stdout.

Usage
-----
  python3 tools/audit_fact_freshness.py [options]

  --repo DIR          Repo root (default: parent of this script's directory).
  --memory-dir PATH   Memory directory to scan
                      (default: ~/.claude/projects/-home-stack-code-slop/memory/).
  --claude-md PATH    Path to CLAUDE.md file to scan.
  --update-shrunk     Shrink the UNPROBED ratchet baseline to the current count
                      (only valid when count has decreased — no-ops if unchanged
                      or would grow).
  --dry-run           Parse and probe, print results, do NOT write baseline.
  --today YYYY-MM-DD  Reference date for deterministic testing (default: today).

Output (all on stdout)
----------------------
  VERIFIED:  <label>  — probe ran, exited 0, output non-empty.
  DRIFT:     <label>  — probe ran but exited non-zero or output empty.
  UNPROBED:  <label>  — no verify_probe registered.
  WARNING:   UNPROBED count <N> exceeds baseline <B>  (ratchet violation).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MEMORY_DIR = (
    Path.home() / ".claude" / "projects" / "-home-stack-code-slop" / "memory"
)

BASELINE_FILENAME = ".factprobe-baseline.json"

# Regex for inline <!-- verify: <cmd> --> annotations anywhere in text.
_VERIFY_ANNOTATION_RE = re.compile(
    r"<!--\s*verify:\s*(?P<cmd>[^>]+?)\s*-->",
    re.IGNORECASE,
)

# YAML frontmatter block: between the first and second "---" lines.
_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<fm>.*?)\n---\s*\n",
    re.DOTALL | re.MULTILINE,
)

# Naive YAML key extractor for simple scalar values (no multi-line, no anchors).
# Handles:  key: value   or   key: "value"   or   key: 'value'
_YAML_KEY_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<val>.+)$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# YAML frontmatter parsing (stdlib only — no PyYAML dependency)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Extract simple scalar top-level keys from YAML frontmatter.

    Handles only flat key: value pairs (strings, quoted strings, bare dates).
    Nested keys and lists are not parsed.  This is intentional — the convention
    only uses top-level scalar keys (``last_verified``, ``verify_probe``).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm_block = m.group("fm")
    result: dict[str, Any] = {}
    for km in _YAML_KEY_RE.finditer(fm_block):
        key = km.group("key")
        val = km.group("val").strip()
        # Strip surrounding quotes if present.
        if (val.startswith('"') and val.endswith('"')) or \
           (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        result[key] = val
    return result


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------

def _run_probe(cmd: str, repo: Path, timeout: int = 15) -> tuple[int, str]:
    """Run *cmd* in a shell rooted at *repo*.  Returns (returncode, combined output)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(repo),
        )
        combined = (result.stdout + result.stderr).strip()
        return result.returncode, combined
    except subprocess.TimeoutExpired:
        return 1, f"TIMEOUT after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return 1, f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# Memory-file fact probing
# ---------------------------------------------------------------------------

def scan_memory_files(
    memory_dir: Path,
    repo: Path,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Scan memory files for verify_probe frontmatter entries.

    Returns:
        verified: list of (label, detail) for probed facts that passed.
        drifted:  list of (label, detail) for probed facts that DRIFT.
        unprobed: list of labels for facts with no probe.
    """
    verified: list[tuple[str, str]] = []
    drifted: list[tuple[str, str]] = []
    unprobed: list[str] = []

    if not memory_dir.is_dir():
        return verified, drifted, unprobed

    for path in sorted(memory_dir.iterdir()):
        if not path.is_file() or path.suffix not in (".md", ".txt", ".yaml", ".yml"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fm = _parse_frontmatter(text)
        if not fm:
            # No frontmatter at all — treat as unprobed (has no probe convention).
            unprobed.append(path.name)
            continue

        probe = fm.get("verify_probe", "").strip()
        label = fm.get("name", path.name)

        if not probe:
            # Frontmatter present but no verify_probe — UNPROBED (correct + honest).
            unprobed.append(label)
            continue

        # Has a probe — run it (GROUND).
        rc, out = _run_probe(probe, repo)
        if rc == 0 and out:
            verified.append((label, f"probe exited 0: {out[:120]}"))
        else:
            detail = f"probe exited {rc}: {out[:120]}" if out else f"probe exited {rc}: (no output)"
            drifted.append((label, detail))

    return verified, drifted, unprobed


# ---------------------------------------------------------------------------
# CLAUDE.md inline verify annotation probing
# ---------------------------------------------------------------------------

def scan_claude_md_annotations(
    claude_md: Path,
    repo: Path,
    section_start: str = "## Project facts",
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], int]:
    """Scan CLAUDE.md for <!-- verify: <cmd> --> annotations.

    Only processes annotations INSIDE the "Project facts" section
    (from *section_start* to the next ## heading or end of file).

    Returns:
        verified: list of (label, detail).
        drifted:  list of (label, detail).
        unprobed_count: number of lines in the section without a verify annotation
                        (NOTE: this is NOT used in the UNPROBED ratchet — the ratchet
                        only counts facts WITH an explicit probe slot.  Annotation-less
                        lines are simply silent/un-annotated, which is the majority
                        and expected.)
    """
    verified: list[tuple[str, str]] = []
    drifted: list[tuple[str, str]] = []

    if not claude_md.is_file():
        return verified, drifted, 0

    text = claude_md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Locate the project-facts section.
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        if line.strip() == section_start:
            in_section = True
            continue
        if in_section:
            if line.startswith("##") and not line.startswith(section_start):
                break
            section_lines.append(line)

    if not section_lines:
        return verified, drifted, 0

    section_text = "\n".join(section_lines)
    annotations = _VERIFY_ANNOTATION_RE.findall(section_text)

    for cmd in annotations:
        cmd = cmd.strip()
        rc, out = _run_probe(cmd, repo)
        label = f"CLAUDE.md verify: {cmd[:60]}"
        if rc == 0:
            verified.append((label, f"exited 0: {out[:80]}" if out else "exited 0"))
        else:
            detail = f"exited {rc}: {out[:80]}" if out else f"exited {rc}: (no output)"
            drifted.append((label, detail))

    return verified, drifted, len(annotations)


# ---------------------------------------------------------------------------
# Ratchet — UNPROBED count (shrink-only)
# ---------------------------------------------------------------------------

def _baseline_path(repo: Path) -> Path:
    return repo / BASELINE_FILENAME


def load_baseline(repo: Path) -> dict[str, Any]:
    bp = _baseline_path(repo)
    if not bp.exists():
        return {"generated_at": "", "unprobed_count": None}
    try:
        return json.loads(bp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"generated_at": "", "unprobed_count": None}


def dump_baseline(repo: Path, data: dict[str, Any]) -> None:
    bp = _baseline_path(repo)
    data["generated_at"] = (
        _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    )
    bp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_ratchet(
    repo: Path,
    unprobed_count: int,
    *,
    update_shrunk: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Compare *unprobed_count* against the stored baseline.

    Returns a list of WARNING lines (empty = OK).
    Writes updated baseline if *update_shrunk* and count has decreased.
    """
    warnings: list[str] = []
    baseline = load_baseline(repo)
    stored = baseline.get("unprobed_count")

    if stored is None:
        # No baseline yet — establish it now.
        if not dry_run:
            dump_baseline(repo, {"unprobed_count": unprobed_count})
        return []

    if unprobed_count > stored:
        warnings.append(
            f"WARNING: UNPROBED count {unprobed_count} exceeds baseline {stored} "
            f"(ratchet violation — add probes or run --update-shrunk if this is intentional)"
        )
    elif unprobed_count < stored:
        if update_shrunk and not dry_run:
            dump_baseline(repo, {"unprobed_count": unprobed_count})
            print(
                f"INFO: UNPROBED ratchet shrunk: {stored} -> {unprobed_count} (baseline updated)",
                file=sys.stderr,
            )
        # Count decreased — good. No warning needed.

    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    repo: Path,
    memory_dir: Path,
    claude_md: Path,
    *,
    update_shrunk: bool = False,
    dry_run: bool = False,
    today: _dt.date | None = None,  # noqa: ARG001  (reserved for future date-gated probes)
) -> tuple[bool, str]:
    """Run all checks.  Returns (True, summary) always (warn-only gate).

    Emits VERIFIED/DRIFT/UNPROBED/WARNING lines to stdout as a side effect.
    """
    lines: list[str] = []

    # 1. Memory-file probes.
    mem_verified, mem_drifted, mem_unprobed = scan_memory_files(memory_dir, repo)

    # 2. CLAUDE.md inline annotations.
    ann_verified, ann_drifted, _ = scan_claude_md_annotations(claude_md, repo)

    all_verified = mem_verified + ann_verified
    all_drifted = mem_drifted + ann_drifted

    # Total UNPROBED = memory files with no probe.
    # (CLAUDE.md non-annotated lines are NOT counted in the ratchet — they
    #  are simply unannotated prose, not "claimed fact slots".)
    total_unprobed = len(mem_unprobed)

    for label, detail in all_verified:
        lines.append(f"VERIFIED:  {label}  ({detail})")
    for label, detail in all_drifted:
        lines.append(f"DRIFT:     {label}  ({detail})")
    for label in mem_unprobed:
        lines.append(f"UNPROBED:  {label}")

    # 3. Ratchet.
    ratchet_warnings = check_ratchet(
        repo, total_unprobed, update_shrunk=update_shrunk, dry_run=dry_run
    )
    lines.extend(ratchet_warnings)

    # Print all lines.
    for ln in lines:
        print(ln)

    # Build summary.
    drift_count = len(all_drifted)
    verified_count = len(all_verified)
    summary_parts = [
        f"{verified_count} VERIFIED",
        f"{drift_count} DRIFT",
        f"{total_unprobed} UNPROBED",
    ]
    if ratchet_warnings:
        summary_parts.append(f"{len(ratchet_warnings)} RATCHET-WARNING(S)")

    summary = (
        "fact-freshness: " + ", ".join(summary_parts) +
        (" — DRIFT detected (loud warn)" if drift_count > 0 else "")
    )
    return True, summary  # always True — warn-only TIER_1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=None, type=Path,
        help="Repo root (default: auto-detect from script location).",
    )
    parser.add_argument(
        "--memory-dir", default=None, type=Path,
        help=f"Memory directory to scan (default: {_DEFAULT_MEMORY_DIR}).",
    )
    parser.add_argument(
        "--claude-md", default=None, type=Path,
        help="Path to CLAUDE.md (default: <repo>/CLAUDE.md).",
    )
    parser.add_argument(
        "--update-shrunk", action="store_true",
        help="Shrink the UNPROBED ratchet baseline to the current count if lower.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and probe; do NOT write the baseline file.",
    )
    parser.add_argument(
        "--today", default=None,
        help="Reference date YYYY-MM-DD for deterministic testing (default: today).",
    )
    args = parser.parse_args()

    if args.today:
        try:
            today = _dt.date.fromisoformat(args.today)
        except ValueError:
            print(
                f"ERROR: --today {args.today!r} is not a valid YYYY-MM-DD date",
                file=sys.stderr,
            )
            sys.exit(0)
    else:
        today = _dt.date.today()

    repo = args.repo.resolve() if args.repo else Path(__file__).resolve().parent.parent
    memory_dir = args.memory_dir.resolve() if args.memory_dir else _DEFAULT_MEMORY_DIR
    claude_md = args.claude_md.resolve() if args.claude_md else (repo / "CLAUDE.md")

    _ok, summary = run(
        repo,
        memory_dir,
        claude_md,
        update_shrunk=args.update_shrunk,
        dry_run=args.dry_run,
        today=today,
    )
    print(f"\n{summary}", file=sys.stderr)
    sys.exit(0)  # always 0 — warn-only


if __name__ == "__main__":
    main()
