#!/usr/bin/env python3
"""
robot-retro.py — Robot run retrospective report generator.

Usage:
    python3 tools/robot-retro.py <run-dir>
    python3 tools/robot-retro.py .claude/run/
    python3 tools/robot-retro.py .claude/run-archive/2026-05-28-round2/

Scans a Robot run directory (current .claude/run/ or archived
.claude/run-archive/<date>/) and aggregates:
  status/, decisions/, blockers/, observations/, proposed-deletions/

into ONE structured markdown report printed to STDOUT.

All stdlib — no external dependencies.
"""

import argparse
import os
import sys
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_file(path: Path) -> str:
    """Read a file, returning empty string on any error."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _list_files(directory: Path) -> list:
    """Return sorted list of files in a directory (non-recursive).
    Returns empty list if the directory does not exist.
    """
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir() if p.is_file()
    )


def _frontmatter_field(text: str, field: str) -> str:
    """Extract a single YAML-like frontmatter field value (no full YAML parser)."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(field + ":"):
            return stripped[len(field) + 1:].strip()
    return ""


def _classify_decision(text: str) -> str:
    """Return 'needs-judgment' or 'informational' based on file content.

    Needs-judgment = the decision had no matching autonomous default, deviated
    from an existing default, or requires explicit human confirmation.
    """
    lower = text.lower()
    # Strong positive signals for needs-judgment (content markers, not headings)
    judgment_markers = [
        "requires human judgment",
        "do not merge wave branch until decided",
        "deviated",
        "not covered by autonomous-defaults",
        "not covered by defaults",
        "not covered by autonomous",
        "morning review must",
        "rollback if",
        "candidate new autonomous-defaults",
        "candidate new entry",
    ]
    for marker in judgment_markers:
        if marker in lower:
            return "needs-judgment"
    # Also flag "default-applied: none" frontmatter as needs-judgment
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("default-applied:"):
            value = stripped[len("default-applied:"):].strip().lower()
            if value.startswith("none"):
                return "needs-judgment"
            break
    return "informational"


def _extract_first_heading(text: str) -> str:
    """Return the first markdown heading text found, or empty string."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _short_summary(text: str, max_chars: int = 200) -> str:
    """Extract a short summary from file content (first non-empty non-heading line)."""
    lines = text.splitlines()
    skip_frontmatter = False
    in_frontmatter = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---" and not in_frontmatter and not skip_frontmatter:
            in_frontmatter = True
            continue
        if stripped == "---" and in_frontmatter:
            in_frontmatter = False
            skip_frontmatter = True
            continue
        if in_frontmatter:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        return stripped[:max_chars] + ("…" if len(stripped) > max_chars else "")
    return "(empty)"


# ── section scanners ─────────────────────────────────────────────────────────

def scan_status(status_dir: Path) -> dict:
    """Scan status/ directory."""
    files = _list_files(status_dir)
    entries = []
    for f in files:
        text = _read_file(f)
        heading = _extract_first_heading(text)
        # Look for completion state
        is_complete = any(
            kw in text.upper()
            for kw in ["COMPLETE", "DONE", "FINISHED"]
        )
        is_blocked = "BLOCKED" in text.upper()
        state = "complete" if is_complete else ("blocked" if is_blocked else "in-progress")
        entries.append({
            "file": f.name,
            "heading": heading or f.stem,
            "state": state,
            "lines": len(text.splitlines()),
        })
    return {"files": entries, "count": len(files)}


def scan_decisions(decisions_dir: Path) -> dict:
    """Scan decisions/ directory, classifying each as informational or needs-judgment."""
    files = _list_files(decisions_dir)
    informational = []
    needs_judgment = []
    for f in files:
        text = _read_file(f)
        kind = _classify_decision(text)
        dtype = _frontmatter_field(text, "type") or kind
        wave = _frontmatter_field(text, "wave")
        stream = _frontmatter_field(text, "stream")
        default_applied = _frontmatter_field(text, "default-applied")
        heading = _extract_first_heading(text) or f.stem
        entry = {
            "file": f.name,
            "heading": heading,
            "wave": wave,
            "stream": stream,
            "default_applied": default_applied,
            "kind": kind,
            "dtype": dtype,
        }
        if kind == "needs-judgment":
            needs_judgment.append(entry)
        else:
            informational.append(entry)
    return {
        "informational": informational,
        "needs_judgment": needs_judgment,
        "count": len(files),
    }


def scan_blockers(blockers_dir: Path) -> dict:
    """Scan blockers/ directory."""
    files = _list_files(blockers_dir)
    entries = []
    for f in files:
        text = _read_file(f)
        wave = _frontmatter_field(text, "wave")
        stream = _frontmatter_field(text, "stream")
        heading = _extract_first_heading(text) or f.stem
        summary = _short_summary(text)
        entries.append({
            "file": f.name,
            "heading": heading,
            "wave": wave,
            "stream": stream,
            "summary": summary,
        })
    return {"files": entries, "count": len(files)}


def scan_observations(observations_dir: Path) -> dict:
    """Scan observations/ directory."""
    files = _list_files(observations_dir)
    entries = []
    for f in files:
        text = _read_file(f)
        wave = _frontmatter_field(text, "wave")
        stream = _frontmatter_field(text, "stream")
        heading = _extract_first_heading(text) or f.stem
        summary = _short_summary(text)
        entries.append({
            "file": f.name,
            "heading": heading,
            "wave": wave,
            "stream": stream,
            "summary": summary,
        })
    return {"files": entries, "count": len(files)}


def scan_proposed_deletions(pd_dir: Path) -> dict:
    """Scan proposed-deletions/ directory."""
    files = _list_files(pd_dir)
    entries = []
    for f in files:
        text = _read_file(f)
        # Extract non-comment, non-empty lines as candidate paths
        paths = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                paths.append(stripped)
        entries.append({
            "file": f.name,
            "line_count": len(text.splitlines()),
            "candidate_paths": paths[:10],  # cap at 10 for readability
        })
    return {"files": entries, "count": len(files)}


# ── report renderer ───────────────────────────────────────────────────────────

def render_report(run_dir: Path, data: dict) -> str:
    """Render the aggregated data into a markdown report string."""
    dir_name = run_dir.name
    lines = []

    # ── Header ──
    lines.append(f"# Robot Run Retrospective — {dir_name}")
    lines.append("")
    lines.append(f"**Run directory:** `{run_dir}`")
    lines.append("")

    # ── Summary counts ──
    status_data = data["status"]
    decisions_data = data["decisions"]
    blockers_data = data["blockers"]
    observations_data = data["observations"]
    pd_data = data["proposed_deletions"]

    lines.append("## Summary")
    lines.append("")
    lines.append("| Section | Count |")
    lines.append("|---|---|")
    lines.append(f"| Status files | {status_data['count']} |")
    lines.append(f"| Decisions — informational | {len(decisions_data['informational'])} |")
    lines.append(f"| Decisions — needs-judgment | {len(decisions_data['needs_judgment'])} |")
    lines.append(f"| Blockers | {blockers_data['count']} |")
    lines.append(f"| Observations | {observations_data['count']} |")
    lines.append(f"| Proposed deletions | {pd_data['count']} |")
    lines.append("")

    # ── Status ──
    lines.append("## Per-Stream Status")
    lines.append("")
    if not status_data["files"]:
        lines.append("_No status files found._")
    else:
        lines.append("| File | Wave/Topic | State |")
        lines.append("|---|---|---|")
        for entry in status_data["files"]:
            state_badge = {
                "complete": "COMPLETE",
                "blocked": "BLOCKED",
                "in-progress": "IN-PROGRESS",
            }.get(entry["state"], entry["state"].upper())
            lines.append(
                f"| `{entry['file']}` | {entry['heading']} | {state_badge} |"
            )
    lines.append("")

    # ── Decisions ──
    lines.append("## Decisions")
    lines.append("")

    # Informational
    lines.append("### Informational (applied default, no morning action needed)")
    lines.append("")
    if not decisions_data["informational"]:
        lines.append("_None._")
    else:
        for entry in decisions_data["informational"]:
            lines.append(f"- **`{entry['file']}`**")
            if entry["heading"] and entry["heading"] != entry["file"]:
                lines.append(f"  - Topic: {entry['heading']}")
            if entry["wave"]:
                lines.append(f"  - Wave: `{entry['wave']}`  Stream: `{entry['stream']}`")
            if entry["default_applied"] and entry["default_applied"] != "none":
                lines.append(f"  - Default applied: {entry['default_applied']}")
    lines.append("")

    # Needs-judgment
    lines.append("### Needs-Judgment (morning review required)")
    lines.append("")
    if not decisions_data["needs_judgment"]:
        lines.append("_None — all decisions covered by autonomous defaults._")
    else:
        for entry in decisions_data["needs_judgment"]:
            lines.append(f"- **`{entry['file']}`**")
            if entry["heading"] and entry["heading"] != entry["file"]:
                lines.append(f"  - Topic: {entry['heading']}")
            if entry["wave"]:
                lines.append(f"  - Wave: `{entry['wave']}`  Stream: `{entry['stream']}`")
            if entry["default_applied"]:
                lines.append(f"  - Default applied: {entry['default_applied']}")
    lines.append("")

    # ── Blockers ──
    lines.append("## Blockers")
    lines.append("")
    if not blockers_data["files"]:
        lines.append("_No blockers — all streams completed._")
    else:
        lines.append(
            f"> **{blockers_data['count']} blocker(s) require morning action.**"
        )
        lines.append("")
        for entry in blockers_data["files"]:
            lines.append(f"### `{entry['file']}`")
            if entry["wave"]:
                lines.append(f"- Wave: `{entry['wave']}`  Stream: `{entry['stream']}`")
            lines.append(f"- Summary: {entry['summary']}")
            lines.append("")

    # ── Observations ──
    lines.append("## Observations")
    lines.append("")
    if not observations_data["files"]:
        lines.append("_No observations recorded._")
    else:
        for entry in observations_data["files"]:
            lines.append(f"### `{entry['file']}`")
            if entry["wave"]:
                lines.append(f"- Wave: `{entry['wave']}`  Stream: `{entry['stream']}`")
            if entry["heading"]:
                lines.append(f"- **{entry['heading']}**")
            lines.append(f"- {entry['summary']}")
            lines.append("")

    # ── Proposed Deletions ──
    lines.append("## Proposed Deletions")
    lines.append("")
    if not pd_data["files"]:
        lines.append("_No proposed deletions._")
    else:
        lines.append(
            "> Each proposed deletion requires explicit morning-review approval."
        )
        lines.append("")
        for entry in pd_data["files"]:
            lines.append(f"### `{entry['file']}`")
            if entry["candidate_paths"]:
                lines.append("Candidate paths/commands:")
                lines.append("```")
                for path in entry["candidate_paths"]:
                    lines.append(path)
                lines.append("```")
            lines.append("")

    # ── AUTONOMOUS-DEFAULTS candidates ──
    lines.append("## Candidate AUTONOMOUS-DEFAULTS Updates")
    lines.append("")
    lines.append(
        "The following decisions were marked as _not covered by defaults_ "
        "and should be reviewed for addition to `AUTONOMOUS-DEFAULTS.md`:"
    )
    lines.append("")
    candidates = [
        e for e in decisions_data["needs_judgment"]
        if "not covered" in (e.get("default_applied") or "").lower()
        or e.get("default_applied") in (None, "", "none")
    ]
    if candidates:
        for entry in candidates:
            lines.append(f"- `{entry['file']}`: {entry['heading']}")
    else:
        lines.append("_None — all decisions either applied a default or were informational._")
    lines.append("")

    # ── Footer ──
    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `tools/robot-retro.py`. "
        "Commit doctrine updates under: `robot: lessons from <date> run`._"
    )
    lines.append("")

    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def build_report(run_dir_str: str) -> str:
    """Build and return the full retro report for a given run directory."""
    run_dir = Path(run_dir_str).resolve()

    if not run_dir.exists():
        print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    if not run_dir.is_dir():
        print(f"ERROR: not a directory: {run_dir}", file=sys.stderr)
        sys.exit(1)

    data = {
        "status": scan_status(run_dir / "status"),
        "decisions": scan_decisions(run_dir / "decisions"),
        "blockers": scan_blockers(run_dir / "blockers"),
        "observations": scan_observations(run_dir / "observations"),
        "proposed_deletions": scan_proposed_deletions(run_dir / "proposed-deletions"),
    }

    return render_report(run_dir, data)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a structured markdown retrospective from a Robot run directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "run_dir",
        help="Path to a Robot run directory (.claude/run/ or .claude/run-archive/<date>/)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write report to this file in addition to STDOUT (optional)",
        default=None,
    )
    args = parser.parse_args()

    report = build_report(args.run_dir)
    print(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\n[report also written to: {out_path}]", file=sys.stderr)


if __name__ == "__main__":
    main()
