#!/usr/bin/env python3
"""tools/check_blast_radius.py — Validate Blast-radius: blocks in SLOP bug-fix commits.

Enforces Rule 4 (Decision D2) from S1-OUTPUT-rule-design.md.  Every commit whose
subject starts with 'fix(' or 'fix:' must contain a properly-structured Blast-radius
block in the commit body.

Expected block format (in commit message body):

    Blast-radius class: <noun phrase describing the class of bug>

    Swept: <N> nodes — <X> fixed, <Y> clean, <Z> deferred, <W> not-checked
    Fixed inline: <file>:<fn()> [× count]   (or "none")
    Deferred to TODO: [BR: <class>] — <concern> [Xm]   (or "none")
    Full audit: LESSONS_LEARNED.md "<entry title>" (this commit)

Checks performed:
  BR001  Block exists in bug-fix commit
  BR002  Blast-radius class: is a noun phrase (no .py/.vue/.ts, no :NNN line refs)
  BR003  Swept: line uses count format (not a comma list of files)
  BR004  Swept: N >= 4 (one node per layer: code, config/schema, docs, tests)
  BR005  Breakdown fixed+clean+deferred+not-checked sums to N
  BR006  Full audit: LESSONS_LEARNED.md "..." line present
  BR007  Deferred to TODO: line contains [BR: ...] tag when deferred >= 1
  BR008  LESSONS_LEARNED.md entry with the quoted title exists
  BR009  That LESSONS entry has a **Swept nodes** table (warning, not error)

Usage:
    python3 tools/check_blast_radius.py                   # check HEAD
    python3 tools/check_blast_radius.py --sha abc1234     # check specific commit
    echo "$MSG" | python3 tools/check_blast_radius.py --stdin
    python3 tools/check_blast_radius.py --self-test       # run embedded test suite
    python3 tools/check_blast_radius.py --quiet           # exit code only

Exit: 0 if valid or not a bug-fix commit; 1 if any ERROR finding.

To integrate as a commit-msg hook (LOCAL ONLY — do not add to repo .githooks):
    cp tools/check_blast_radius.py .git/hooks/commit-msg-helper
    # In .git/hooks/commit-msg:
    #!/bin/bash
    python3 .git/hooks/commit-msg-helper --stdin < "$1" || exit 1

To bypass (rare — e.g. hotfix/rollback per Rule 15):
    git commit --no-verify
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_LESSONS_CANDIDATES = [
    REPO / "docs" / "LESSONS_LEARNED.md",
    Path("/home/stack/v5/docs/LESSONS_LEARNED.md"),
]
_TODO_CANDIDATES = [
    REPO / "docs" / "TODO.md",
    Path("/home/stack/v5/docs/TODO.md"),
]

# ── Regex patterns ─────────────────────────────────────────────────────────────
BUG_FIX_SUBJECT_RE = re.compile(r"^fix[\(:]", re.IGNORECASE)
BUG_FIX_BODY_RE    = re.compile(r"^(?:Bug|bug):", re.MULTILINE)
CLASS_LINE_RE      = re.compile(r"^Blast-radius class:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
SWEPT_SUMMARY_RE   = re.compile(
    r"^Swept:\s*(\d+)\s+nodes?\s*[—\-]\s*"
    r"(\d+)\s+fixed[,\s]+(\d+)\s+clean[,\s]+(\d+)\s+deferred[,\s]+(\d+)\s+not-?checked",
    re.MULTILINE | re.IGNORECASE,
)
FULL_AUDIT_RE      = re.compile(
    r'^Full audit:\s+LESSONS_LEARNED\.md\s+"([^"]+)"',
    re.MULTILINE | re.IGNORECASE,
)
DEFERRED_LINE_RE   = re.compile(r"^Deferred to TODO:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
BR_TAG_RE          = re.compile(r"\[BR:[^\]]+\]", re.IGNORECASE)
BAD_CLASS_RE       = re.compile(r'\.(py|vue|ts|js|sh|md|yaml|yml|json)\b|:\d+')


# ── Helpers ────────────────────────────────────────────────────────────────────
def _find_file(candidates: list[Path]) -> Path | None:
    for p in candidates:
        if p.exists():
            return p
    return None


def _git_show(sha: str) -> str | None:
    r = subprocess.run(
        ["git", "show", "--no-patch", "--format=%B", sha],
        capture_output=True, text=True, cwd=str(REPO),
    )
    return r.stdout.strip() if r.returncode == 0 else None


def _is_bug_fix(msg: str) -> bool:
    subject = msg.splitlines()[0] if msg else ""
    return bool(BUG_FIX_SUBJECT_RE.match(subject) or BUG_FIX_BODY_RE.search(msg))


# ── Validator ──────────────────────────────────────────────────────────────────
def validate(msg: str, label: str = "HEAD",
             lessons_path: Path | None = None,
             todo_path: Path | None = None) -> tuple[list[str], bool]:
    """Parse and validate a commit message.

    Returns (output_lines, had_error).  Caller decides whether to print.
    lessons_path / todo_path override the default candidate search (for testing).
    """
    out: list[str] = []
    had_error = False

    def emit(level: str, code: str, text: str) -> None:
        nonlocal had_error
        out.append(f"{label}: {level}: [{code}] {text}")
        if level == "ERROR":
            had_error = True

    # BR001 — block must exist
    class_match = CLASS_LINE_RE.search(msg)
    if not class_match:
        emit("ERROR", "BR001", "missing 'Blast-radius class:' line in bug-fix commit")
        return out, had_error

    class_name = class_match.group(1).strip().rstrip(".")

    # BR002 — class must be a noun phrase
    if BAD_CLASS_RE.search(class_name):
        emit("ERROR", "BR002",
             "Blast-radius class: looks like a file path or line ref, not a noun phrase: "
             + repr(class_name))

    # BR003/BR004/BR005 — Swept summary line
    swept_match = SWEPT_SUMMARY_RE.search(msg)
    deferred_count = 0
    if not swept_match:
        emit("ERROR", "BR003",
             "Swept: line missing or malformed — expected "
             "'Swept: N nodes — X fixed, Y clean, Z deferred, W not-checked' "
             "(got a comma list? add count breakdown, N >= 4)")
    else:
        total_n  = int(swept_match.group(1))
        fixed    = int(swept_match.group(2))
        clean    = int(swept_match.group(3))
        deferred = int(swept_match.group(4))
        not_chk  = int(swept_match.group(5))
        deferred_count = deferred

        if total_n < 4:
            emit("ERROR", "BR004",
                 "Swept node count is %d; minimum is 4 (one per layer: code, config/schema, docs, tests)"
                 % total_n)
        breakdown = fixed + clean + deferred + not_chk
        if breakdown != total_n:
            emit("ERROR", "BR005",
                 "Swept breakdown %d+%d+%d+%d=%d does not match header N=%d"
                 % (fixed, clean, deferred, not_chk, breakdown, total_n))

    # BR007 — Deferred to TODO: line must have [BR: ...] when deferred >= 1
    deferred_match = DEFERRED_LINE_RE.search(msg)
    if deferred_count >= 1:
        if not deferred_match or deferred_match.group(1).strip().lower() == "none":
            emit("ERROR", "BR007",
                 "Swept reports %d deferred but 'Deferred to TODO:' is absent or 'none'"
                 % deferred_count)
        elif not BR_TAG_RE.search(deferred_match.group(1)):
            emit("ERROR", "BR007",
                 "Deferred to TODO: line must contain a [BR: <class>] tag; got: "
                 + repr(deferred_match.group(1)[:80]))

    # BR006/BR008/BR009 — Full audit cross-reference
    audit_match = FULL_AUDIT_RE.search(msg)
    if not audit_match:
        emit("ERROR", "BR006",
             "missing 'Full audit: LESSONS_LEARNED.md \"<title>\" (this commit)' line")
    else:
        entry_title = audit_match.group(1).strip()
        lp = lessons_path or _find_file(_LESSONS_CANDIDATES)
        if lp:
            text = lp.read_text(encoding="utf-8", errors="replace")
            if entry_title not in text:
                emit("ERROR", "BR008",
                     "LESSONS_LEARNED.md has no entry titled %r (required by Full audit:)"
                     % entry_title)
            else:
                # Check for **Swept nodes** table within 4000 chars of title
                pos = text.find(entry_title)
                chunk = text[pos: pos + 4000]
                if "**Swept nodes**" not in chunk:
                    emit("WARNING", "BR009",
                         "LESSONS entry %r exists but has no '**Swept nodes**' table (D2 requires it)"
                         % entry_title)

    return out, had_error


# ── Self-test ──────────────────────────────────────────────────────────────────
_VALID_BLOCK = """\
fix(health): correct URL dispatch for llamacpp provider

Body text here.

Blast-radius class: config dispatch path ignores provider when selecting URL key

Swept: 4 nodes — 1 fixed, 2 clean, 0 deferred, 1 not-checked
Fixed inline: backend/api/health.py:trigger_health_run()
Deferred to TODO: none
Full audit: LESSONS_LEARNED.md "Valid self-test entry" (this commit)
"""

_FEATURE_NO_BLOCK = "feat(dashboard): add SLOP agent widget\n\nJust a feature, no blast-radius block needed.\n"
_FIX_NO_BLOCK     = "fix(api): correct null handling in catalog load\n\nBody text.\n"
_NO_VERDICTS      = """\
fix(health): some fix

Blast-radius class: config dispatch something

Swept: backend/api/health.py, backend/core/agent.py
Fixed inline: none
Deferred to TODO: none
Full audit: LESSONS_LEARNED.md "no verdicts entry" (this commit)
"""
_DEFERRED_NO_TODO = """\
fix(llm): align llamacpp URL

Blast-radius class: llamacpp port mismatch across backend and frontend

Swept: 5 nodes — 1 fixed, 2 clean, 1 deferred, 1 not-checked
Fixed inline: backend/api/platform.py:wizard_save_llm()
Deferred to TODO: [BR: llamacpp port mismatch across backend and frontend] — add test [10m]
Full audit: LESSONS_LEARNED.md "deferred no todo entry" (this commit)
"""


def run_self_test(quiet: bool = False) -> bool:
    ok = True
    cases = []

    with tempfile.TemporaryDirectory() as td:
        lp = Path(td) / "LESSONS_LEARNED.md"
        tp = Path(td) / "TODO.md"

        lp.write_text(
            "## Session 18 — 2026-05-24\n\n"
            "### Valid self-test entry (commit `abc1234`)\n\n"
            "**Pattern / Bug / Symptom**: test\n"
            "**Root cause / Why this happens**: test\n"
            "**Fix / Approach taken**: test\n"
            "**Blast radius**: minimal\n"
            "**Lesson**: keep testing\n\n"
            "**Swept nodes**:\n"
            "| Node | Layer | Verdict |\n"
            "|------|-------|---------|\n"
            "| backend/api/health.py | code | fixed |\n",
            encoding="utf-8",
        )
        tp.write_text("- [ ] [BR: config dispatch path] — some deferred item\n", encoding="utf-8")

        cases = [
            # (description, msg, expect_error, lessons_path, todo_path)
            ("1. Valid block",                 _VALID_BLOCK,        False, lp, tp),
            ("2. feat: no block (not needed)", _FEATURE_NO_BLOCK,   False, lp, tp),
            ("3. fix: missing block",          _FIX_NO_BLOCK,       True,  lp, tp),
            ("4. fix: Swept is comma list",    _NO_VERDICTS,        True,  lp, tp),
            ("5. fix: deferred, no TODO match",_DEFERRED_NO_TODO,   True,  lp, tp),
        ]

        for desc, msg, expect_err, lpath, tpath in cases:
            is_fix = _is_bug_fix(msg)
            if not is_fix:
                lines, err = [], False
            else:
                lines, err = validate(msg, label="SELF-TEST", lessons_path=lpath, todo_path=tpath)
            passed = (err == expect_err)
            ok = ok and passed
            status = "PASS" if passed else "FAIL"
            if not quiet:
                print("  [%s] %s" % (status, desc))
                if not passed:
                    for ln in lines:
                        print("         %s" % ln)

    return ok


# ── CLI ────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Validate Blast-radius: blocks in SLOP commits.")
    ap.add_argument("--sha",       help="Commit SHA to check (default: HEAD)")
    ap.add_argument("--stdin",     action="store_true", help="Read commit message from stdin")
    ap.add_argument("--quiet",     action="store_true", help="Suppress output; use exit code only")
    ap.add_argument("--self-test", action="store_true", dest="self_test",
                    help="Run embedded test suite and exit")
    args = ap.parse_args()

    if args.self_test:
        if not args.quiet:
            print("check_blast_radius.py — self-test")
        ok = run_self_test(quiet=args.quiet)
        if not args.quiet:
            print("Self-test: %s" % ("PASS" if ok else "FAIL"))
        return 0 if ok else 1

    if args.stdin:
        msg = sys.stdin.read()
        label = "STDIN"
    else:
        sha = args.sha or "HEAD"
        msg = _git_show(sha)
        if msg is None:
            if not args.quiet:
                print("%s: ERROR: could not retrieve commit message" % sha, file=sys.stderr)
            return 1
        label = sha[:7] if len(sha) > 7 else sha

    if not _is_bug_fix(msg):
        if not args.quiet:
            print("%s: OK (not a bug-fix commit — Blast-radius block not required)" % label)
        return 0

    lines, had_error = validate(msg, label=label)
    if not args.quiet:
        if lines:
            for ln in lines:
                print(ln)
        else:
            print("%s: OK (Blast-radius block is valid)" % label)

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
