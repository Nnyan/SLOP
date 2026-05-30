"""tests/test_audit_single_entity_hardcode.py — BATCH-11 S6 (R10).

Proves the single-entity-hardcode scanner (the GROUND red-signal for CLAUDE.md's
Reuse-and-blast-radius checkpoint):

  1. RED-PATH: a tool with an unjustified SLOP-only hardcode + no --repo param -> DRIFT.
  2. SUPPRESSION (day-one false-positive): lift_push_restore.py's SETTINGS_PATH is a
     JUSTIFIED hardcode (recorded scope-reason) and MUST NOT be flagged.
  3. inline `# scope-reason:` marker suppresses.
  4. a file that exposes --repo is not flagged (interface parameterized over the set).
  5. unparseable file -> INDETERMINATE (no silent pass).
  6. the scanner does not itself hardcode SLOP-only (dogfood) — the hunt literal is
     supplied/derived, and the real repo scans clean by default.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.audit_single_entity_hardcode import audit, scan_file

SLOP_LITERAL = "/home/stack/code/slop"


def _scan_one(tmp_path: Path, name: str, body: str) -> tuple[str, list[str]]:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return audit(tmp_path, slop_root=SLOP_LITERAL, scan_file_path=f)


# ── 1. RED-PATH ───────────────────────────────────────────────────────────────

class TestRedPath:
    def test_unjustified_slop_hardcode_no_repo_param_drifts(self, tmp_path):
        body = (
            "from pathlib import Path\n"
            "BACKLOG = Path('/home/stack/code/slop/docs/BACKLOG.md')\n"
            "def main():\n"
            "    return str(BACKLOG)\n"
        )
        verdict, lines = _scan_one(tmp_path, "bad_tool.py", body)
        assert verdict == "DRIFT", "\n".join(lines)
        assert any("bad_tool.py" in ln and "DRIFT" in ln for ln in lines)


# ── 2. SUPPRESSION: SETTINGS_PATH (day-one) ────────────────────────────────────

class TestSettingsPathSuppressed:
    def test_real_lift_push_restore_settings_path_suppressed(self, tmp_path):
        """The REAL lift_push_restore.py SETTINGS_PATH must NOT be flagged."""
        real = REPO / "tools" / "sanctioned" / "lift_push_restore.py"
        verdict, lines = audit(REPO, slop_root=SLOP_LITERAL, scan_file_path=real)
        # It contains the SLOP literal but must be suppressed -> not DRIFT.
        assert verdict != "DRIFT", "\n".join(lines)
        assert any("SETTINGS_PATH" in ln and "suppressed" in ln for ln in lines), (
            "SETTINGS_PATH was not suppressed via the recorded scope-reason:\n"
            + "\n".join(lines)
        )

    def test_recorded_reason_is_load_bearing(self, tmp_path):
        """A file NOT in the allowlist, with a SLOP literal in a bare const + no
        --repo param, DRIFTs — proving the allowlist (not luck) is what suppresses
        the real SETTINGS_PATH."""
        body = (
            "from pathlib import Path\n"
            "SETTINGS_PATH = Path('/home/stack/code/slop/.claude/x.json')\n"
        )
        # named differently so it's not in the allowlist AND has no --repo token
        verdict, lines = _scan_one(tmp_path, "other_tool.py", body)
        assert verdict == "DRIFT", "\n".join(lines)


# ── 3. inline marker ───────────────────────────────────────────────────────────

class TestInlineMarker:
    def test_inline_scope_reason_suppresses(self, tmp_path):
        body = (
            "from pathlib import Path\n"
            "P = Path('/home/stack/code/slop/x')  # scope-reason: SLOP-only by nature\n"
        )
        verdict, lines = _scan_one(tmp_path, "marked.py", body)
        assert verdict != "DRIFT", "\n".join(lines)
        assert any("inline scope-reason" in ln for ln in lines)


# ── 4. parameterized file ───────────────────────────────────────────────────────

class TestParameterized:
    def test_file_with_repo_param_not_flagged(self, tmp_path):
        body = (
            "import argparse\n"
            "from pathlib import Path\n"
            "DEFAULT = Path('/home/stack/code/slop')\n"
            "def main():\n"
            "    p = argparse.ArgumentParser()\n"
            "    p.add_argument('--repo', default=str(DEFAULT))\n"
        )
        verdict, lines = _scan_one(tmp_path, "param_tool.py", body)
        assert verdict != "DRIFT", "\n".join(lines)


# ── 5. INDETERMINATE ────────────────────────────────────────────────────────────

class TestIndeterminate:
    def test_unparseable_file_is_indeterminate(self, tmp_path):
        body = "def broken(:\n   pass\n"  # syntax error
        verdict, lines = _scan_one(tmp_path, "broken.py", body)
        assert verdict == "INDETERMINATE", "\n".join(lines)


# ── 6. dogfood ──────────────────────────────────────────────────────────────────

class TestDogfood:
    def test_scanner_does_not_flag_itself(self, tmp_path):
        """The scanner skips its own file (its docstring names SLOP paths legitimately)
        — even when hunting the canonical SLOP literal, it must NOT DRIFT on itself."""
        scanner = REPO / "tools" / "audit_single_entity_hardcode.py"
        verdict, lines = audit(REPO, slop_root=SLOP_LITERAL, scan_file_path=scanner)
        assert verdict != "DRIFT", "\n".join(lines)

    def test_real_repo_default_scans_clean(self):
        """Default derived literal (the worktree root) -> the real tools/ scans clean."""
        verdict, _ = audit(REPO)
        assert verdict == "verified"
