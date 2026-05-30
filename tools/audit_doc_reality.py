#!/usr/bin/env python3
"""audit_doc_reality.py — doc-vs-reality reconciler (S-75 Stream B, warn-only).

Reconciles DOCUMENTED claims (the CLAUDE.md deploy facts + memory deploy facts)
against a PINNED RealityView produced by `slop-reality-probe` running ON the
deploy host. This is the DEV-TIME reconciler keystone: it READS docs and READS
a RealityView; it NEVER touches the running-app control path.

────────────────────────────────────────────────────────────────────────────
CROSS-REPO WIRING NOTE (orchestrator applies this; this tool does NOT edit v5):
  The SessionStart hook  /home/stack/v5/docs/tools/check_push_status.sh  should
  call this reconciler as a new READ-ONLY layer. The exact one-line invocation
  the orchestrator must add is:

      python3 /home/stack/code/slop/tools/audit_doc_reality.py --repo /home/stack/code/slop --host rocinante || true

  (`|| true` keeps the warn-only reconciler from ever failing the SessionStart
  hook — it is TIER_1 visibility, never blocking. The host arg is the operator's
  ambient-SSH alias; no secret is stored or read.)
────────────────────────────────────────────────────────────────────────────

PINNED RealityView schema (Stream A owns; consumed VERBATIM — keys read exactly):
  schema_version:int  observed_at:str  bound_port:int
  install_dir_is_git:bool  install_dir_owner:str  env_sources:{VAR: src}

PINNED verdict vocabulary (this Stream owns; C and D consume):
  verified      — GROUND match (probe touched physics, doc agrees)
  DRIFT         — GROUND mismatch (probe touched physics, doc disagrees)
  INCONSISTENT  — XREF mismatch (text-vs-text only; may NEVER bless)
  INDETERMINATE — unreachable ground truth (LOUD; NEVER OK)

PINNED reconciler-trust discipline (Stream E owns; consumed here):
  GROUND = probe touches physics → may assert "verified".
  XREF   = text-vs-text → may only flag INCONSISTENT, never bless.
  INDETERMINATE = unreachable ground truth (loud, never OK).
  "A green light must be able to go red against physics."
Every GROUND verdict line NAMES the ground truth it touched.

SEVERITY / QUEUE routing:
  - Only DRIFT on a load-bearing claim files to docs/BACKLOG.md as a
    `[gap-discovery]` line (deduped by <claim>, updated in place never re-filed).
  - INCONSISTENT (XREF) routes to a LOWER-TIER queue (.claude/run/xref-findings/)
    that does NOT count against BACKLOG triage.
  - INDETERMINATE is reported loudly but never written to BACKLOG (no ground
    truth was touched, so there is nothing to assert against the doc).

PROMOTION-TO-BLOCKING TRIGGER (documented per warn-only contract):
  Promote check_doc_reality from TIER_1 warn-only to a blocking gate only once
  (a) the host probe runs reliably in CI/SessionStart for >=30 days with zero
  INDETERMINATE-due-to-tooling, AND (b) a deploy-fact DRIFT has been caught and
  fixed at least once via this gate (proving it can go red against physics).
  Until both hold, it returns (True, summary) always.

Exit code: 0 ALWAYS (warn-only).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

GAP_TAG = "[gap-discovery]"

# Verdict tokens — PINNED vocabulary.
VERIFIED = "verified"
DRIFT = "DRIFT"
INCONSISTENT = "INCONSISTENT"
INDETERMINATE = "INDETERMINATE"

# Lower-tier XREF queue (does NOT count against BACKLOG triage).
XREF_QUEUE_DIR = Path(".claude") / "run" / "xref-findings"


# ─────────────────────────────────────────────────────────────────────────
# Claim extraction from docs (the documented deploy facts).
# ─────────────────────────────────────────────────────────────────────────
def extract_doc_claims(repo: Path) -> dict[str, object]:
    """Parse the documented deploy facts into a normalized claim dict.

    Reads CLAUDE.md (project facts). Returns the subset of deploy facts this
    reconciler knows how to ground-check. Missing facts simply aren't claimed
    (no fabricated claim).
    """
    claims: dict[str, object] = {}
    claude_md = repo / "CLAUDE.md"
    if not claude_md.exists():
        return claims
    text = claude_md.read_text(encoding="utf-8", errors="replace")

    # install dir is an HTTPS git clone → install_dir_is_git == True
    if re.search(r"/opt/mediastack`?\s*\)?\s*is an?\s+HTTPS git clone", text) or \
       re.search(r"HTTPS git clone of `Nnyan/SLOP`", text):
        claims["install_dir_is_git"] = True

    # tree owned by service user `mediastack` → install_dir_owner == mediastack
    m = re.search(r"owned by the \*\*service user `([A-Za-z0-9_]+)`", text)
    if m:
        claims["install_dir_owner"] = m.group(1)

    return claims


def extract_memory_claims(memory_file: Path) -> dict[str, object]:
    """Parse deploy facts from the memory file (e.g. Rocinante deploy note).

    Reads the bound-port claim. Memory is XREF-class doc text; claims here are
    reconciled the same way (DRIFT if ground disagrees, since the probe is the
    ground oracle). Returns {} if the file is absent.
    """
    claims: dict[str, object] = {}
    if not memory_file.exists():
        return claims
    text = memory_file.read_text(encoding="utf-8", errors="replace")
    # **Port:** `8080` ...
    m = re.search(r"\*\*Port:\*\*\s*`?(\d+)`?", text)
    if m:
        claims["bound_port"] = int(m.group(1))
    return claims


# ─────────────────────────────────────────────────────────────────────────
# RealityView acquisition (GROUND) — runs slop-reality-probe over ambient SSH.
# ─────────────────────────────────────────────────────────────────────────
def fetch_reality_view(
    host: str | None,
    probe_cmd: str = "slop-reality-probe",
    timeout: int = 30,
    _runner=None,
) -> tuple[dict | None, str]:
    """Run `ssh <host> slop-reality-probe` (Option A: operator ambient SSH).

    Returns (reality_view_or_None, detail). On any failure (no host, ssh error,
    bad JSON) returns (None, reason) — the caller emits INDETERMINATE, never OK.
    NEVER reads or stores an SSH key/credential; the host arg comes from config.

    `_runner` is an injectable subprocess runner for tests (no real SSH).
    """
    if not host:
        return None, "no --host provided (ground truth unreachable)"

    runner = _runner or _ssh_run
    try:
        rc, out = runner(host, probe_cmd, timeout)
    except Exception as exc:  # noqa: BLE001 — any ssh/transport error ⇒ INDETERMINATE
        return None, f"ssh transport error: {exc}"
    if rc != 0:
        return None, f"ssh {host} {probe_cmd} exited rc={rc}"
    try:
        view = json.loads(out)
    except json.JSONDecodeError as exc:
        return None, f"probe emitted non-JSON: {exc}"
    if not isinstance(view, dict) or view.get("schema_version") != 1:
        return None, "probe JSON missing schema_version==1 (contract mismatch)"
    return view, f"probed {host} via `ssh {host} {probe_cmd}`"


def _ssh_run(host: str, probe_cmd: str, timeout: int) -> tuple[int, str]:
    """Real ambient-SSH runner. No key handling — relies on operator's SSH agent."""
    res = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, probe_cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return res.returncode, res.stdout


# ─────────────────────────────────────────────────────────────────────────
# Reconciliation — produce verdicts.
# ─────────────────────────────────────────────────────────────────────────
class Verdict:
    """One reconciliation result line."""

    __slots__ = ("claim", "token", "doc_value", "reality_value", "ground", "detail")

    def __init__(self, claim, token, doc_value, reality_value, ground, detail):
        self.claim = claim
        self.token = token
        self.doc_value = doc_value
        self.reality_value = reality_value
        self.ground = ground  # str naming the physics touched, or "" for XREF
        self.detail = detail

    def line(self) -> str:
        if self.token == INDETERMINATE:
            return f"{INDETERMINATE}: {self.claim} — ground truth unreachable ({self.detail})"
        if self.ground:
            base = (
                f"{self.token}: {self.claim} — doc says {self.doc_value!r}, "
                f"reality says {self.reality_value!r} ({self.ground})"
            )
        else:
            base = (
                f"{self.token}: {self.claim} — doc says {self.doc_value!r} "
                f"(XREF text-vs-text, no physics touched)"
            )
        return base


# Which claims are GROUND-checkable against the RealityView, and how to name
# the physics touched. Each maps claim-key → (reality-key, ground-namer).
def _ground_name(reality_key: str, view: dict) -> str:
    if reality_key == "bound_port":
        return f"probed live listen socket → RealityView bound_port={view.get('bound_port')}"
    if reality_key == "install_dir_is_git":
        return f"probed `git -C <install_dir>` → RealityView install_dir_is_git={view.get('install_dir_is_git')}"
    if reality_key == "install_dir_owner":
        return f"probed install-dir inode owner → RealityView install_dir_owner={view.get('install_dir_owner')!r}"
    return f"probed RealityView {reality_key}={view.get(reality_key)!r}"


# Claims that, when DRIFT, are load-bearing and file to BACKLOG.
_LOAD_BEARING = frozenset({"bound_port", "install_dir_is_git", "install_dir_owner"})


def reconcile(
    doc_claims: dict[str, object],
    view: dict | None,
    unreachable_detail: str,
) -> list[Verdict]:
    """Reconcile doc claims against the RealityView.

    If `view` is None (host unreachable / bad probe), every GROUND-checkable
    claim becomes INDETERMINATE (loud, never OK).
    """
    verdicts: list[Verdict] = []
    for claim_key, doc_val in sorted(doc_claims.items(), key=lambda kv: kv[0]):
        if view is None:
            verdicts.append(Verdict(
                claim_key, INDETERMINATE, doc_val, None, "", unreachable_detail,
            ))
            continue
        reality_val = view.get(claim_key)
        ground = _ground_name(claim_key, view)
        if reality_val == doc_val:
            verdicts.append(Verdict(claim_key, VERIFIED, doc_val, reality_val, ground, "match"))
        else:
            verdicts.append(Verdict(claim_key, DRIFT, doc_val, reality_val, ground, "mismatch"))
    return verdicts


# ─────────────────────────────────────────────────────────────────────────
# Severity routing: DRIFT → BACKLOG (deduped); INCONSISTENT → xref queue.
# ─────────────────────────────────────────────────────────────────────────
def _gap_line(v: Verdict) -> str:
    probe_hint = "ssh <host> slop-reality-probe"
    return (
        f"- [ ] **{GAP_TAG}** {v.claim} — doc says {v.doc_value!r}, "
        f"reality says {v.reality_value!r} (probe: {probe_hint})"
    )


def file_drift_to_backlog(verdicts: list[Verdict], backlog: Path) -> list[str]:
    """File load-bearing DRIFT verdicts to BACKLOG as [gap-discovery] lines.

    Deduped by <claim>: an existing [gap-discovery] line for the same claim is
    UPDATED in place, never re-filed. Returns the list of claims written.
    Only DRIFT on a load-bearing claim is filed.
    """
    targets = [v for v in verdicts if v.token == DRIFT and v.claim in _LOAD_BEARING]
    if not targets:
        return []

    text = backlog.read_text(encoding="utf-8", errors="replace") if backlog.exists() else ""
    lines = text.splitlines()
    written: list[str] = []

    for v in targets:
        new_line = _gap_line(v)
        # Dedup by claim: match an existing gap-discovery line mentioning this claim.
        claim_marker = f"**{GAP_TAG}** {v.claim} —"
        replaced = False
        for i, ln in enumerate(lines):
            if claim_marker in ln:
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        written.append(v.claim)

    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def route_inconsistent_to_xref(verdicts: list[Verdict], repo: Path) -> list[str]:
    """Route INCONSISTENT (XREF) verdicts to the lower-tier queue.

    Writes to .claude/run/xref-findings/<claim>.txt — a queue that does NOT
    count against BACKLOG triage (it is outside docs/BACKLOG.md entirely).
    Returns the claims routed.
    """
    targets = [v for v in verdicts if v.token == INCONSISTENT]
    if not targets:
        return []
    qdir = repo / XREF_QUEUE_DIR
    qdir.mkdir(parents=True, exist_ok=True)
    routed: list[str] = []
    for v in targets:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", v.claim)
        (qdir / f"{safe}.txt").write_text(v.line() + "\n", encoding="utf-8")
        routed.append(v.claim)
    return routed


# ─────────────────────────────────────────────────────────────────────────
# Orchestration entry point.
# ─────────────────────────────────────────────────────────────────────────
def run(
    repo: Path,
    host: str | None,
    memory_file: Path | None = None,
    backlog: Path | None = None,
    view_override: dict | None = None,
    unreachable: bool = False,
    _runner=None,
    write_findings: bool = True,
) -> tuple[bool, str, list[Verdict]]:
    """Full reconciliation. Returns (ok_always_True, summary, verdicts).

    `view_override` / `unreachable` let tests inject a RealityView (or force the
    unreachable path) without real SSH. Always returns ok=True (warn-only).
    """
    doc_claims = extract_doc_claims(repo)
    mem = memory_file if memory_file is not None else (
        Path.home() / ".claude" / "projects" / "-home-stack-code-slop"
        / "memory" / "project_rocinante_deploy.md"
    )
    doc_claims.update(extract_memory_claims(mem))

    if view_override is not None:
        view, detail = view_override, "injected RealityView (test/fixture)"
    elif unreachable:
        view, detail = None, "forced-unreachable (test/fixture)"
    else:
        view, detail = fetch_reality_view(host, _runner=_runner)

    verdicts = reconcile(doc_claims, view, detail)

    backlog_path = backlog if backlog is not None else (repo / "docs" / "BACKLOG.md")
    filed: list[str] = []
    routed: list[str] = []
    if write_findings:
        filed = file_drift_to_backlog(verdicts, backlog_path)
        routed = route_inconsistent_to_xref(verdicts, repo)

    counts = {VERIFIED: 0, DRIFT: 0, INCONSISTENT: 0, INDETERMINATE: 0}
    for v in verdicts:
        counts[v.token] = counts.get(v.token, 0) + 1

    summary = (
        f"doc-vs-reality: {counts[VERIFIED]} verified, {counts[DRIFT]} DRIFT, "
        f"{counts[INCONSISTENT]} INCONSISTENT, {counts[INDETERMINATE]} INDETERMINATE"
        f" | {detail}"
    )
    if filed:
        summary += f" | filed DRIFT→BACKLOG: {', '.join(filed)}"
    if routed:
        summary += f" | routed INCONSISTENT→xref-queue: {', '.join(routed)}"
    return True, summary, verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="Repo root (default: tool's parent)")
    parser.add_argument(
        "--host", default=None,
        help="Deploy host (operator ambient SSH alias). Unreachable/absent ⇒ INDETERMINATE.",
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="Reconcile and print only; do not file/route findings.",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent

    ok, summary, verdicts = run(
        repo, args.host, write_findings=not args.no_write,
    )
    for v in verdicts:
        # GROUND verdicts (verified/DRIFT) print to stdout; INDETERMINATE loud to stderr.
        stream = sys.stderr if v.token == INDETERMINATE else sys.stdout
        print(v.line(), file=stream)
    print(summary, file=sys.stderr)
    return 0  # warn-only: always 0


if __name__ == "__main__":
    raise SystemExit(main())
