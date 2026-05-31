# S-65 — AGENT-SPINE — single-orchestrator launch prompt

Paste the block below into a **fresh Opus session**. ONE orchestrator handles all
4 streams (`.claude/ROBOT.md` § "Architecture — ONE orchestrator per batch").
Full wave spec: `.claude/waves/S-65-AGENT-SPINE.md` — the orchestrator reads it
end-to-end. **Hard sequence: S1 (the spine contract + self-audit reconciler)
builds and merges to the wave branch BEFORE S2/S3/S4; S3 runs after S2 (shared
egress seam).**

> **Pre-fire note:** this wave is product code (`backend/agent/`), adds NO doctrine
> edit and NO `ms-enforce` gate, so it does NOT trip the independent-review
> mechanical floor. BUT it is a significant new subsystem AND BACKLOG `:67`
> mandates one **owed independent adversarial review** charged at the
> **egress/sanitization trust boundary (S2) + the advisory-only remediation gate
> (S4)** — the **Manager runs that review before the sanctioned merge to main**.

================================================================
in Robot mode: you are the ORCHESTRATOR for SLOP wave S-65 (AGENT-SPINE) — ONE
orchestrator, 4 streams, fired from this single session. This is a CODE wave that
builds the reusable agent oversight spine (reconcile→interpret→remediate seams)
with the agent self-audit as the reference implementation. You merge each stream
into the wave branch `wave/S-65-agent-spine` but DO NOT merge to main and DO NOT
push (the Manager does the post-wave merge via tools/merge_wave_to_main.py, after
the owed independent review).

First read, in order:
  1. .claude/ROBOT.md (binding rules, orchestrator startup sequence, ONE-
     orchestrator-per-batch architecture, dedicated merge-worktree pattern,
     subagent preamble).
  2. .claude/AUTONOMOUS-DEFAULTS.md (decision register).
  3. .claude/waves/S-65-AGENT-SPINE.md (the full wave spec — all 4 streams, models,
     deliverables, the PINNED S1 contract, the S2→S3 egress-share, the two-owner
     firewall + fail-closed-egress + advisory-only invariants).
  4. docs/AGENT-EXPANSION-SURVEY.md §0 + §4 (the spine shape + the OVERREACH
     guardrails the streams must honor).

Startup:
  1. Confirm base: `git rev-parse origin/main` (expect b5419dd or later). Confirm
     the reused primitives exist at the CURRENT SHA (scrub.py, router/dispatch.py +
     registry.py, autofix.py/apply.py/backoff.py, reality_view.py, integrity.py) —
     the fact-check leg (do not trust the draft-time landing claim). Also grep
     integrity.py for any docs/.md read (R9 firewall leg). Branch the wave off this
     live SHA.
  2. High-tier pre-flight: run
     `python3 tools/wave_complexity.py .claude/waves/S-65-AGENT-SPINE.md` (expect
     High, score 11) then the matching rigor (validate-wave-file + fact-check
     subagent + processor-contract-pinned + cross-wave-disjointness + edited-wave
     consistency). Write `.claude/run/preflight/S-65.md` (DISPATCH-OK or BLOCKED).
     **BLOCK dispatch if any check returns FALSE.**
  3. Create `.claude/run/status/S-65.md` (Bash heredoc, not Write) with
     `**State:** RUNNING` as the first non-blank line.

Run shape (the hard sequence matters — see wave spec § "Cross-wave dependencies"):
  - PHASE 1: dispatch ONLY S1 (spine contract + GROUND self-audit reconciler +
    the run_health_cycle hook), model opus, isolation:"worktree", on
    `wave/S-65-S1-spine`. When it returns, create the wave branch
    `wave/S-65-agent-spine` and merge S1 into it using a dedicated merge worktree
    (`.claude/worktrees/merge-S-65`, detached from origin/main — this ONE time, to
    create the wave branch). S1 is the PINNED producer of the `spine.py` contract
    (Finding/Decision types + the three seam signatures + the egress-seam location)
    that S2/S3/S4 import.
  - PHASE 2: dispatch S2 and S4 CONCURRENTLY (single message, multiple Agent tool
    uses; isolation:"worktree"; S2 opus, S4 sonnet), each branched off the
    S1-merged `wave/S-65-agent-spine`. Run S3 (opus) AFTER S2 returns (S3 shares
    S2's egress seam). Inject the subagent preamble (git -C <worktree> pin).
  - Each subagent commits to its own `wave/S-65-SN-*` branch and ships its tests +
    the invariant assertions (S1 GROUND red-path; S2 zero-token-escape +
    fail-closed; S3 LLM-cannot-flip-DRIFT; S4 advisory-only-no-side-effect). No
    auto-remediation is wired.
  - Merge each returned stream into `wave/S-65-agent-spine` via merge worktrees
    **detached from `wave/S-65-agent-spine`, NOT origin/main** (origin/main would
    drop S1). S1 solely owns the `backend/health/checker.py` hook; no other shared
    files.

Per-stream models (from the wave spec): S1 opus · S2 opus · S3 opus · S4 sonnet.

Invariants every stream must hold (wave spec "Rules to follow"; HARDENED by the
pre-fire review R1–R8 — see docs/REVIEW-LOG.md):
  - Two-owner firewall: NO spine module reads docs/process — derive intent from
    physics + the manifest only. No doctrine edit, no ms-enforce gate.
  - DENY-BY-DEFAULT egress (R1/R2/R3): cloud-bound payloads are a STRUCTURED,
    allowlisted finding shape (not a free-form blob); the allowlist is the gate,
    scrub() is defense-in-depth (it leaks hostnames/emails/JWTs/raw-hex/`/data`
    paths — do NOT rely on it). Fail-closed = provable cleanliness (send only if an
    independent allowlist verifier passes; else INDETERMINATE, do not send). The
    decision sits BELOW chain selection (per-attempt provider); unknown provider ⇒
    treated as cloud. Compose with — do not remove — the existing checker.py:~405
    chokepoint. Red-path test MUST feed scrub's known misses.
  - LLM is XREF/advisory — STRUCTURAL (R8): Finding.verdict is frozen; interpret()
    returns annotations that cannot carry a verdict; a "verified" reply cannot flip
    a DRIFT. interpret() runs far less often than the ~30s cycle (cost guard).
  - Remediation advisory-only — STRUCTURAL (R6/R7): spine_remediate imports ONLY the
    taxonomy map as data; MUST NOT import apply_safe_fix/select_auto_applicable/
    executors/subprocess; a structural import-absence test enforces it.
  - No payload in logs/exceptions (R5). Never-raises at the run_health_cycle boundary.

Maintain `.claude/run/status/S-65.md` continuously; set `**State:** CLOSED` as your
final action. Do not call AskUserQuestion — apply .claude/AUTONOMOUS-DEFAULTS.md and
log each decision + the authorizing rule to `.claude/run/questions/S-65.md` (proceed,
never block). On a hard blocker, write `.claude/run/blockers/S-65.md` and halt. When
all 4 streams are merged into `wave/S-65-agent-spine`, set State CLOSED and report —
the Manager runs the owed independent review (egress + advisory-only-remediation
boundary) and does the single sanctioned merge to main.
================================================================
