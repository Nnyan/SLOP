#!/usr/bin/env python3
"""audit_wave_out_of_scope.py — Floating-work audit: wave out-of-scope sections.

Walks .claude/waves/*.md, extracts each "Out of scope" section's bullets,
surfaces any bullet referencing "future" / "candidate" / "S-NN wave" (an
S-number followed by a wave keyword) that isn't referenced in docs/BACKLOG.md.

Exit code: 0 always (warn-only; visibility, not blocking).

Usage:
  python3 tools/audit_wave_out_of_scope.py [--repo /path/to/repo]

Output:
  UNTRACKED_OOS: <wave_file>  bullet: <text>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Pattern to identify wave-number references like S-49, S-52, S-NN
WAVE_REF_RE = re.compile(r"\bS-\d+\b", re.IGNORECASE)

# Keywords that signal future work
FUTURE_KEYWORDS_RE = re.compile(
    r"\b(future|candidate|next wave|planned|deferred|later|upcoming)\b",
    re.IGNORECASE,
)


def load_backlog(repo: Path) -> str:
    """Load docs/BACKLOG.md content, return empty string if missing."""
    backlog = repo / "docs" / "BACKLOG.md"
    if not backlog.exists():
        return ""
    return backlog.read_text(encoding="utf-8", errors="replace")


def extract_out_of_scope_bullets(text: str) -> list[str]:
    """Extract bullet points from 'Out of scope' sections.

    Handles both '## Out of scope' and '### Out of scope' headings.
    Collects all bullet lines (starting with - or *) until next heading.
    """
    bullets = []
    in_oos = False

    for line in text.splitlines():
        stripped = line.strip()

        # Detect out-of-scope heading
        if re.match(r"^#{1,4}\s+out\s+of\s+scope", stripped, re.IGNORECASE):
            in_oos = True
            continue

        # Stop at any other heading
        if in_oos and re.match(r"^#{1,4}\s+", stripped):
            in_oos = False
            continue

        # Collect bullets
        if in_oos and re.match(r"^[-*]\s+", stripped):
            bullets.append(stripped.lstrip("-* ").strip())

    return bullets


def bullet_has_future_signal(bullet: str) -> bool:
    """Return True if bullet references future work."""
    return bool(WAVE_REF_RE.search(bullet) or FUTURE_KEYWORDS_RE.search(bullet))


def bullet_in_backlog(backlog_text: str, bullet: str) -> bool:
    """Return True if the bullet text is substantially represented in BACKLOG.md.

    Checks using key terms (wave numbers, distinctive phrases) to avoid
    false positives from common words.
    """
    # Extract wave numbers from bullet
    wave_refs = WAVE_REF_RE.findall(bullet)

    # Extract significant words (>5 chars, not common words)
    STOP_WORDS = {
        "should", "could", "would", "their", "there", "these", "those",
        "which", "where", "after", "before", "about", "above", "below",
        "scope", "future", "candidate", "deferred", "until", "later",
    }
    words = [w.lower() for w in re.findall(r"\b[a-zA-Z]{5,}\b", bullet)
             if w.lower() not in STOP_WORDS]

    # A bullet with a specific wave reference is matched if that reference
    # appears in a [ ] or [→ line in the backlog
    backlog_lines = backlog_text.splitlines()
    relevant_lines = [
        ln for ln in backlog_lines
        if "[ ]" in ln or "[→" in ln or "[x]" in ln or "[parked]" in ln
    ]

    for wave_ref in wave_refs:
        for ln in relevant_lines:
            if wave_ref in ln:
                return True

    # Fall back to keyword matching: if ≥2 significant words from the bullet
    # appear in the same backlog line, consider it matched
    if len(words) >= 2:
        for ln in relevant_lines:
            ln_lower = ln.lower()
            matched = sum(1 for w in words if w in ln_lower)
            if matched >= 2:
                return True

    return False


def _find_waves_dir(repo: Path) -> Path | None:
    """Find the .claude/waves directory.

    In a worktree, the waves live in the main repo's .claude/ directory.
    We use git to find the common .git directory and derive the main repo root.
    """
    waves_dir = repo / ".claude" / "waves"
    if waves_dir.exists():
        return waves_dir

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if result.returncode == 0:
            git_common = Path(result.stdout.strip())
            if not git_common.is_absolute():
                git_common = (repo / git_common).resolve()
            main_repo = git_common.parent
            main_waves = main_repo / ".claude" / "waves"
            if main_waves.exists():
                return main_waves
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return None


def scan_waves(repo: Path) -> list[tuple[str, str]]:
    """Scan .claude/waves/*.md for untracked out-of-scope bullets.

    Returns list of (wave_path, bullet_text).
    """
    waves_dir = _find_waves_dir(repo)
    if waves_dir is None:
        return []

    backlog_text = load_backlog(repo)
    untracked = []

    for wave_file in sorted(waves_dir.glob("*.md")):
        try:
            text = wave_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Use relative path if possible, otherwise absolute
        try:
            rel_path = str(wave_file.relative_to(repo))
        except ValueError:
            rel_path = str(wave_file)
        bullets = extract_out_of_scope_bullets(text)

        for bullet in bullets:
            if not bullet_has_future_signal(bullet):
                continue
            if not bullet_in_backlog(backlog_text, bullet):
                untracked.append((rel_path, bullet))

    return untracked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None,
                        help="Path to repo root (default: auto-detect from script location)")
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).resolve()
    else:
        repo = Path(__file__).resolve().parent.parent

    untracked = scan_waves(repo)

    for wave_path, bullet in untracked:
        print(f"UNTRACKED_OOS: {wave_path}")
        print(f"  bullet: {bullet[:120]}")

    if untracked:
        print(f"\nSummary: {len(untracked)} untracked out-of-scope bullet(s) across wave files",
              file=sys.stderr)
    else:
        print("OK: all out-of-scope bullets with future signals are in docs/BACKLOG.md",
              file=sys.stderr)

    sys.exit(0)  # always exit 0 — warn-only


if __name__ == "__main__":
    main()
