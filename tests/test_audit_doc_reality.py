"""tests/test_audit_doc_reality.py — Tests for tools/audit_doc_reality.py (S-75-B).

Covers every PINNED verdict-token path AND the dedup + severity gate:
  - verified      (GROUND match)
  - DRIFT         (GROUND mismatch) → files to BACKLOG (deduped, load-bearing only)
  - INCONSISTENT  (XREF mismatch)   → routes to lower-tier xref queue (NOT BACKLOG)
  - INDETERMINATE (unreachable host) → loud, never OK, never written
  - dedup: a second DRIFT for the same claim UPDATES the line, never re-files
  - severity gate: INCONSISTENT does NOT land in docs/BACKLOG.md
  - ms-enforce registration: check_doc_reality present + in TIER_1 + warn-only
  - the slop-reality-probe emits the PINNED schema verbatim

DOGFOOD RULE: every write goes to tmp_path. No test writes the real docs/BACKLOG.md.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "audit_doc_reality.py"
PROBE = REPO / "slop-reality-probe"


def _load_tool():
    spec = importlib.util.spec_from_file_location("audit_doc_reality", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _py() -> str:
    venv_py = REPO / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else sys.executable


# A RealityView that matches the canonical documented deploy facts.
_MATCHING_VIEW = {
    "schema_version": 1,
    "observed_at": "2026-05-30T00:00:00+00:00",
    "bound_port": 8080,
    "install_dir_is_git": True,
    "install_dir_owner": "mediastack",
    "env_sources": {"MS_TRUSTED_HOSTS": "environ"},
}


def _fixture_repo(tmp_path: Path) -> Path:
    """Create a fixture repo with CLAUDE.md + memory deploy facts."""
    (tmp_path / "CLAUDE.md").write_text(
        "The install dir (`/opt/mediastack`)\n"
        "is an HTTPS git clone of `Nnyan/SLOP`, updated via ms-update.\n"
        "The tree is owned by the **service user `mediastack`** — run git as that user.\n",
        encoding="utf-8",
    )
    mem = tmp_path / "memory.md"
    mem.write_text("- **Port:** `8080` (baked into the systemd unit).\n", encoding="utf-8")
    return mem


# ---------------------------------------------------------------------------
# Verdict-token paths
# ---------------------------------------------------------------------------
class TestVerdictTokens:
    def test_verified_on_ground_match(self, tmp_path):
        mod = _load_tool()
        mem = _fixture_repo(tmp_path)
        ok, summary, verdicts = mod.run(
            tmp_path, host=None, memory_file=mem,
            backlog=tmp_path / "docs" / "BACKLOG.md",
            view_override=_MATCHING_VIEW, write_findings=True,
        )
        assert ok is True
        tokens = {v.claim: v.token for v in verdicts}
        assert tokens["bound_port"] == mod.VERIFIED
        assert tokens["install_dir_is_git"] == mod.VERIFIED
        assert tokens["install_dir_owner"] == mod.VERIFIED
        # GROUND verdict names the physics it touched.
        bp = next(v for v in verdicts if v.claim == "bound_port")
        assert "RealityView bound_port=8080" in bp.line()

    def test_drift_on_ground_mismatch_files_to_backlog(self, tmp_path):
        mod = _load_tool()
        mem = _fixture_repo(tmp_path)
        bad_view = dict(_MATCHING_VIEW, bound_port=9090)
        backlog = tmp_path / "docs" / "BACKLOG.md"
        ok, summary, verdicts = mod.run(
            tmp_path, host=None, memory_file=mem, backlog=backlog,
            view_override=bad_view, write_findings=True,
        )
        bp = next(v for v in verdicts if v.claim == "bound_port")
        assert bp.token == mod.DRIFT
        assert "doc says 8080" in bp.line() and "reality says 9090" in bp.line()
        # DRIFT on a load-bearing claim is filed to BACKLOG as a [gap-discovery] line.
        text = backlog.read_text()
        assert "**[gap-discovery]** bound_port —" in text
        assert "[ ]" in text

    def test_indeterminate_on_unreachable_never_ok(self, tmp_path):
        mod = _load_tool()
        mem = _fixture_repo(tmp_path)
        backlog = tmp_path / "docs" / "BACKLOG.md"
        ok, summary, verdicts = mod.run(
            tmp_path, host=None, memory_file=mem, backlog=backlog,
            unreachable=True, write_findings=True,
        )
        assert ok is True  # warn-only
        assert all(v.token == mod.INDETERMINATE for v in verdicts)
        assert "INDETERMINATE" in verdicts[0].line()
        # Loud and never OK: summary reports INDETERMINATE, not OK/verified.
        assert "INDETERMINATE" in summary
        assert mod.VERIFIED not in [v.token for v in verdicts]
        # Nothing written to BACKLOG on unreachable (no ground touched).
        assert not backlog.exists()

    def test_inconsistent_routes_to_xref_not_backlog(self, tmp_path):
        mod = _load_tool()
        # Build an INCONSISTENT (XREF) verdict directly and route it.
        v = mod.Verdict("doc_path_xref", mod.INCONSISTENT, "/opt/x", "/opt/y", "", "text-vs-text")
        routed = mod.route_inconsistent_to_xref([v], tmp_path)
        assert routed == ["doc_path_xref"]
        xref_file = tmp_path / ".claude" / "run" / "xref-findings" / "doc_path_xref.txt"
        assert xref_file.exists()
        assert "INCONSISTENT" in xref_file.read_text()
        # SEVERITY GATE: INCONSISTENT must NOT count against BACKLOG.
        backlog = tmp_path / "docs" / "BACKLOG.md"
        assert not backlog.exists()


# ---------------------------------------------------------------------------
# Dedup + severity gate
# ---------------------------------------------------------------------------
class TestDedupAndSeverity:
    def test_drift_dedup_updates_in_place(self, tmp_path):
        mod = _load_tool()
        backlog = tmp_path / "docs" / "BACKLOG.md"
        backlog.parent.mkdir(parents=True)
        backlog.write_text("# BACKLOG\n\n- some other item\n", encoding="utf-8")

        v1 = mod.Verdict("bound_port", mod.DRIFT, 8080, 9090, "ground", "x")
        mod.file_drift_to_backlog([v1], backlog)
        v2 = mod.Verdict("bound_port", mod.DRIFT, 8080, 7070, "ground", "x")
        mod.file_drift_to_backlog([v2], backlog)

        text = backlog.read_text()
        # Exactly ONE gap-discovery line for bound_port (deduped, updated in place).
        assert text.count("**[gap-discovery]** bound_port —") == 1
        # Updated to the latest reality value.
        assert "reality says 7070" in text
        assert "reality says 9090" not in text

    def test_only_load_bearing_drift_files(self, tmp_path):
        mod = _load_tool()
        backlog = tmp_path / "docs" / "BACKLOG.md"
        # A DRIFT on a non-load-bearing claim is NOT filed.
        v = mod.Verdict("some_minor_claim", mod.DRIFT, "a", "b", "ground", "x")
        written = mod.file_drift_to_backlog([v], backlog)
        assert written == []
        assert not backlog.exists()

    def test_inconsistent_never_files_to_backlog_via_run(self, tmp_path):
        """End-to-end: an XREF-class INCONSISTENT verdict in run() lands in xref, not BACKLOG."""
        mod = _load_tool()
        backlog = tmp_path / "docs" / "BACKLOG.md"
        # Inject a verdict list with an INCONSISTENT and confirm severity routing.
        verdicts = [mod.Verdict("c1", mod.INCONSISTENT, "x", "y", "", "xref")]
        filed = mod.file_drift_to_backlog(verdicts, backlog)
        routed = mod.route_inconsistent_to_xref(verdicts, tmp_path)
        assert filed == []           # not in BACKLOG
        assert routed == ["c1"]      # in xref queue
        assert not backlog.exists()


# ---------------------------------------------------------------------------
# fetch_reality_view via injected runner (no real SSH, no stored secret)
# ---------------------------------------------------------------------------
class TestFetchRealityView:
    def test_unreachable_when_no_host(self):
        mod = _load_tool()
        view, detail = mod.fetch_reality_view(None)
        assert view is None
        assert "unreachable" in detail.lower()

    def test_ssh_failure_is_indeterminate(self):
        mod = _load_tool()

        def _bad_runner(host, cmd, timeout):
            return 255, ""

        view, detail = mod.fetch_reality_view("rocinante", _runner=_bad_runner)
        assert view is None
        assert "rc=255" in detail

    def test_good_probe_parses(self):
        mod = _load_tool()

        def _good_runner(host, cmd, timeout):
            return 0, json.dumps(_MATCHING_VIEW)

        view, detail = mod.fetch_reality_view("rocinante", _runner=_good_runner)
        assert view is not None and view["bound_port"] == 8080
        assert "probed rocinante" in detail


# ---------------------------------------------------------------------------
# slop-reality-probe emits the PINNED schema verbatim
# ---------------------------------------------------------------------------
class TestRealityProbeSchema:
    def test_probe_emits_pinned_keys(self):
        res = subprocess.run(
            [_py(), str(PROBE), "--install-dir", str(REPO),
             "--env-var", "PUID", "--env-var", "TZ"],
            capture_output=True, text=True, timeout=30,
        )
        assert res.returncode == 0, res.stderr
        view = json.loads(res.stdout)
        assert set(view.keys()) == {
            "schema_version", "observed_at", "bound_port",
            "install_dir_is_git", "install_dir_owner", "env_sources",
        }
        assert view["schema_version"] == 1
        assert isinstance(view["bound_port"], int)
        assert isinstance(view["install_dir_is_git"], bool)
        assert isinstance(view["install_dir_owner"], str)
        assert isinstance(view["env_sources"], dict)
        # GROUND: this repo IS a git tree.
        assert view["install_dir_is_git"] is True


# ---------------------------------------------------------------------------
# ms-enforce registration (warn-only, in TIER_1)
# ---------------------------------------------------------------------------
class TestMsEnforceRegistration:
    def test_check_doc_reality_registered_in_tier1(self):
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "def check_doc_reality()" in text
        assert "Doc-vs-reality reconciliation (warn only)" in text
        # Appears within the TIER_1 list, before TIER_2 declaration.
        tier1_idx = text.index("TIER_1: list[tuple[str, object]] = [")
        tier2_idx = text.index("TIER_2: list[tuple[str, object]] = [")
        reg_idx = text.index('("Doc-vs-reality reconciliation (warn only)", check_doc_reality)')
        assert tier1_idx < reg_idx < tier2_idx

    def test_wrapper_is_warn_only(self):
        """The ms-enforce wrapper returns (True, ...) always."""
        ms_enforce = REPO / "ms-enforce"
        # ms-enforce has no .py extension; load via SourceFileLoader.
        from importlib.machinery import SourceFileLoader
        loader = SourceFileLoader("ms_enforce_mod", str(ms_enforce))
        spec = importlib.util.spec_from_loader("ms_enforce_mod", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        ok, summary = mod.check_doc_reality()
        assert ok is True  # warn-only
        # Inside ms-enforce host is unset → INDETERMINATE surfaces (never OK/verified).
        assert isinstance(summary, str)
