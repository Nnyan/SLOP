# S-65 — AGENT-SPINE — the reusable reconcile→interpret→remediate spine (reference implementation = agent self-audit)

## Goal
Build the **reusable oversight spine** every future agent-expansion stratum plugs into,
and prove it on the agent reconciling **itself**. The spine has one shape
(`docs/AGENT-EXPANSION-SURVEY.md` §0):

> **GROUND probe that can go red against physics → optional advisory interpretation
> (LLM = XREF/advisory, never authoritative) → bounded, human-gated remediation.**

This wave ships the **four reusable seams** (reconciler contract, fail-closed sanitizer
boundary, ms-router advisory-review call, advisory-only remediation gate) wired to a
**GROUND self-audit reconciler**. **Scope decision (operator-locked 2026-05-30):
remediation is the GATE INTERFACE ONLY — present and returns `advisory-only`; NO
auto-remediation is wired in this wave.** Later probe-pack waves add real probes + gated
remediation by reusing these seams. The expansion is then mostly *wiring existing
primitives into the spine*.

## Context
The SLOP AI Agent (`backend/core/agent.py`, runtime executive manager) has a solid
**liveness-of-known-containers** layer (container-vs-DB reconciliation, RealityView
env-provenance, LLM connectivity, per-app checks, opt-in safe-autofix) but **~0% of the
"recoverable" half** of its mandate and of the host substrate (survey §1–§2). Before
adding probe packs, the **seams must exist and be reusable** — otherwise every later
stratum re-invents the egress boundary, the review call, and the gate.

**Reuse — VERIFIED LANDED on main `b9501ae` at draft time (survey §0 instruction):**
- **Sanitizer** = `backend/agent/scrub.py` `scrub(text, *, profile="cloud")` (142 L,
  S-61) → `<IP>`/`<PATH>`/`<APP>`/`<USER>`/`<SECRET>`; `profile="local"` passes through;
  pure/idempotent/None-safe.
- **LLM transport** = `backend/agent/router/dispatch.py` `route_and_dispatch(...)` (S-62/63)
  + `router/registry.py` `available_providers` — on-host/local-first chain, cloud opt-in,
  never raises (degrades to legacy single-provider).
- **Remediation primitives** = `backend/agent/autofix.py` `select_auto_applicable` +
  `apply.py` `SAFE_FIX_TYPES` + `backoff.py` (S-60/64) — the gate skeleton (NOT wired to
  act this wave).
- **GROUND self-view** = `backend/core/reality_view.py` `assemble_live_reality_view()` +
  `backend/core/agent.py` `get_reality_view()` — touches physics, never raises.
- **Cycle insertion seam** = `backend/health/checker.py:1469` `run_health_cycle()` already
  calls `check_agent_connectivity()`; the self-audit reconciler hooks the same cycle.

**Two-owner firewall (HARD, CLAUDE.md "Knowledge-Lifecycle"):** the spine is
**runtime-only** — it observes the live process / OS / Docker / DB and the manifest the
agent already reads; it **never reads docs/process/runbooks** to decide anything (survey
§4 "reading docs to pick a fix = firewall breach"). The dev-time reconciler
(`tools/audit_doc_reality.py`) stays the separate owner of doc knowledge. This wave adds
NO doctrine edit and NO `ms-enforce` gate — it is product code under `backend/agent/`.

## Rules to follow
- **Additive.** New modules under `backend/agent/`; reuse the landed primitives by import,
  do NOT fork or reimplement them. The ONLY edit to an existing file is the minimal hook in
  `backend/health/checker.py` `run_health_cycle()` to invoke the self-audit reconciler each
  cycle (additive try/except block, mirroring the existing `check_agent_connectivity` block;
  never-raises contract).
- **Pinned vocabulary (CLAUDE.md "Knowledge-Lifecycle", verbatim):** GROUND / XREF /
  INDETERMINATE / UNPROBED; verdicts `verified` / `DRIFT` / `INCONSISTENT` / `INDETERMINATE`.
  The reconciler emits GROUND verdicts; the LLM review is **XREF — may only flag
  `INCONSISTENT`, never assert `verified`** and never decides remediation.
- **Fail-closed egress (the load-bearing safety property).** Any payload leaving the host
  to a cloud provider passes the sanitizer FIRST; if the sanitizer cannot run / verify, the
  call is **NOT made** (fail closed, not fail open). On-host/local providers
  (`profile="local"`) need no scrub but still route through the same seam.
- **LLM is advisory, never authoritative** (survey §4): the GROUND verdict + deterministic
  rule decide; the LLM only *explains*. Never "ask the model whether to apply."
- **Remediation is advisory-only this wave:** the gate returns a structured `advisory-only`
  decision (the action it WOULD propose + why it is not acting). No `SAFE_FIX` is invoked.
- **File-size ratchet applies** (`backend/agent/**`, `backend/core/**` = 500 hard cap).
  Keep each new module under cap; split if needed.
- **Never-raises at the cycle boundary:** a spine failure degrades to a recorded
  INDETERMINATE health signal — it must never break `run_health_cycle()`.

## Authorized deletions
None. No history rewrites. Streams may delete only dead scaffolding they themselves create.

## Parallelization

**Models (per-wave default):** orchestrator = **opus**, subagents = per-stream below.

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| **S1** spine contract + GROUND self-audit reconciler (PINNED producer) | **opus** | **sequential — FIRST, merge to wave branch before others** | `backend/agent/spine.py` (the `Finding`/verdict contract + `reconcile→interpret→remediate` protocol) + `backend/agent/self_audit.py` (the GROUND self-reconciler) + the `run_health_cycle` hook + tests |
| **S2** fail-closed sanitizer boundary + LIVE red-path test | **opus** | parallel (after S1) | the egress seam wrapping `scrub()`; fail-closed-on-sanitizer-failure; the runtime red-path test asserting no `<IP>`/`<PATH>`-class token escapes the actual payload (survey §4 scrub-as-live-probe) |
| **S3** ms-router advisory-review call (interpret seam) | **opus** | sequential after S2 (shares the egress seam) | `backend/agent/spine_review.py` — pass GROUND findings through the S2 boundary + `route_and_dispatch`, return XREF/`INCONSISTENT`-only advisory; on-host default, cloud opt-in |
| **S4** advisory-only remediation gate (remediate seam) | **sonnet** | parallel (after S1) | `backend/agent/spine_remediate.py` — the gate interface reusing the `SAFE_FIX_TYPES`/backoff shape; returns a structured `advisory-only` decision; wires NO action |

**Per-stream Model justification (rubric, ROBOT.md § "Per-stream Model column"):**
- **S1 = opus** — load-bearing contract design every other stream + every future stratum
  consumes; the reconciler must derive intent from physics only (firewall) — highest
  plausible-but-wrong risk.
- **S2 = opus** — the egress/sanitization trust boundary; fail-closed correctness is subtle
  and security-bearing (this is one of the two surfaces the owed independent review targets).
- **S3 = opus** — must keep the LLM strictly XREF/advisory (never authoritative) across the
  router's fallback paths; the "advisory, not authority" invariant is easy to violate.
- **S4 = sonnet** — bounded gate skeleton against the settled `SAFE_FIX_TYPES`/backoff
  interface; returns advisory-only (no action wiring) — well-specified, lower risk.

## Complexity & Pre-flight
**Tier: High** (new cross-cutting subsystem, 4 streams, a hard S1-first sequence + an
S2→S3 egress-share, a security-bearing egress boundary, runtime-cycle hook). Run High-tier
pre-flight (validate-wave-file + fact-check subagent + processor-contract-pinned +
cross-wave-disjointness + edited-wave consistency). Confirm with
`python3 tools/wave_complexity.py .claude/waves/S-65-AGENT-SPINE.md`. Write the verdict to
`.claude/run/preflight/S-65.md`. **BLOCK dispatch on any FALSE.**

## Deliverables per stream

### Stream S1 — Spine contract + GROUND self-audit reconciler (PINNED producer)
1. **`backend/agent/spine.py` — the reusable contract** (consumed by S2/S3/S4 + every
   future stratum): a `Finding` structure (`id`, `physics` one-liner, `verdict` ∈
   `verified`/`DRIFT`/`INCONSISTENT`/`INDETERMINATE`, `summary`, `detail`); the three
   protocol seam signatures —
   `reconcile() -> list[Finding]` (GROUND), `interpret(findings) -> list[Finding]`
   (XREF/advisory, default no-op pass-through), `remediate(findings) -> list[Decision]`
   (returns `advisory-only` Decisions). **PINNED**: this contract is the open API; S2/S3/S4
   import it and do NOT edit `spine.py`'s logic.
2. **`backend/agent/self_audit.py` — the GROUND self-reconciler** (reference impl of
   `reconcile()`): reconcile the agent against physics ONLY — its DB record (tier-0,
   category=agent) vs runtime; `get_reality_view()` (bound_port / install_dir_is_git /
   owner) vs the agent's expectation; enforcement-coverage integrity
   (`backend/agent/integrity.py`) — each emitting a GROUND `Finding`. NO doc reads
   (firewall). INDETERMINATE (loud) when a ground source is unreachable; never a silent OK.
3. **Hook** `run_health_cycle()` (`backend/health/checker.py`, additive try/except mirroring
   the `check_agent_connectivity` block) to call the self-audit `reconcile()` each cycle and
   persist findings to `health_checks` (a new `subject_type="agent_self_audit"` or reuse the
   process_integrity dimension — stream's call, documented). Never-raises.
4. **Tests** (`tests/test_agent_spine.py`, `tests/test_agent_self_audit.py`): the contract
   shape; a GROUND red-path (inject a DB-vs-reality mismatch → assert `DRIFT`); an
   unreachable-source case → assert `INDETERMINATE` (not OK).

### Stream S2 — Fail-closed sanitizer boundary + LIVE red-path test (egress trust boundary)
1. **The egress seam** (in `spine.py` per S1's PINNED contract, or a `spine_egress.py` S1
   exposes — coordinate via the contract): a single function every outbound-to-cloud payload
   passes through. Cloud route → `scrub(payload, profile="cloud")` FIRST; **fail closed** —
   if scrub raises or a post-scrub verification finds a residual `<IP>`/`<PATH>`/`<SECRET>`-
   class literal, the call is NOT made (return a recorded INDETERMINATE, do not send).
   On-host route (`profile="local"`) → no scrub needed but SAME seam.
2. **LIVE red-path test** (`tests/test_spine_egress_redpath.py`, the survey §4 "scrub-as-a-
   live-probe"): feed a payload containing a real IP + abs path + bearer token through the
   actual egress seam and assert the emitted payload has ZERO un-redacted tokens; AND a
   fail-closed test (monkeypatch `scrub` to raise → assert NO outbound call is made).
3. Align the cloud-vs-local decision to the **routing set** the dispatcher uses, not a
   stale copy (BACKLOG `:130` lesson: egress must scrub if `provider in cloud_providers`).

### Stream S3 — ms-router advisory-review call (interpret seam) — sequential after S2
1. **`backend/agent/spine_review.py`** implementing `interpret(findings)`: serialize the
   GROUND findings to a prompt, send through the **S2 egress boundary** then
   `route_and_dispatch(... max_tier=...)` (on-host/local-first; cloud only if the user
   opted in), parse the reply as **advisory XREF** — it may annotate a finding or flag
   `INCONSISTENT`, it may NEVER upgrade a `DRIFT`→`verified` or decide remediation.
2. **Opt-in + default-most-private** (locked decision): review runs only if the user enabled
   LLM review; default to the most-private available tier (deterministic critic → on-host
   LLM → cloud). No key / disabled → skip cleanly (findings pass through un-annotated).
3. **Tests** (`tests/test_spine_review.py`): the LLM reply can only annotate / flag
   `INCONSISTENT` (assert a malicious "verified" reply cannot flip a `DRIFT`); the egress
   boundary is on the call path (assert scrub ran before dispatch for a cloud provider);
   opt-out path skips cleanly.

### Stream S4 — Advisory-only remediation gate (remediate seam) — parallel after S1
1. **`backend/agent/spine_remediate.py`** implementing `remediate(findings) -> [Decision]`:
   for each `DRIFT` finding, consult the deterministic mapping (reuse `apply.SAFE_FIX_TYPES`
   / `autofix.select_auto_applicable` SHAPE) to compute *what action it WOULD propose*, then
   return a structured **`advisory-only` Decision** (`finding_id`, `would_propose`,
   `why_not_acting="advisory-only spine; no auto-remediation wired in S-65"`). **Wires NO
   action** — invokes no `apply`, no `autofix`.
2. The gate is the seam future waves flip to gated-acting; document the single extension
   point (where a future wave would add the human-gate + backoff + verify, reusing S-60/64).
3. **Tests** (`tests/test_spine_remediate.py`): every `DRIFT` yields exactly one
   `advisory-only` Decision; assert NO `apply`/`autofix` side-effect is invoked (the
   advisory-only invariant — the second surface the owed independent review targets).

## Verification
- Full backend suite passes; new tests pass; `ms-enforce` exits 0 on each stream branch and
  on the merged wave branch.
- S1: the self-audit reconciler emits GROUND `Finding`s on a real cycle; the DB-vs-reality
  red-path asserts `DRIFT`; an unreachable source asserts `INDETERMINATE`.
- S2: the LIVE red-path test proves zero token escape AND fail-closed-on-scrub-failure (no
  outbound call).
- S3: the LLM reply cannot flip a `DRIFT`→`verified`; egress scrub is on the cloud call path.
- S4: every `DRIFT` → exactly one `advisory-only` Decision; NO remediation side-effect.
- Two-owner firewall intact: no spine module reads docs/process; no doctrine edit; no
  `ms-enforce` gate added.
- File-size ratchet green (no new `backend/agent/**` file over 500).

## Out of scope
- **Any real probe pack** (host-substrate, recoverability, etc.) — those are the FOLLOW-ON
  agent-expansion waves (BACKLOG `[→ future — agent-expansion roadmap]`), each reusing this
  spine. S-65 ships only the seams + the self-audit reference reconciler.
- **Any auto-remediation / gated acting** — the remediation seam is advisory-only this wave.
- **The global autofix circuit-breaker** (survey §4) — rides WITH S-64's autofix lineage in a
  later wave, not here.
- Doctrine edits / new `ms-enforce` gates (this is runtime product code).
- Frontend surfacing of self-audit findings (a later UI pass).

## Cross-wave dependencies (EXPLICIT)
- **Depends on landed primitives (main `b9501ae`):** `scrub.py` (S-61), `router/dispatch.py`
  + `registry.py` (S-62/63), `autofix.py`/`apply.py`/`backoff.py` (S-60/64),
  `reality_view.py`, `integrity.py`. Confirm each at base before dispatch (the orchestrator's
  fact-check leg).
- **Intra-wave:**
  - **S1 is the PINNED producer** — its `spine.py` contract (the `Finding`/`Decision` types +
    the three seam signatures + the egress-seam location) is consumed by S2/S3/S4. S1 lands on
    the wave branch FIRST; the others branch off the S1-merged wave branch and IMPORT the
    contract (never edit `spine.py`).
  - **S3 depends on S2** (shares the egress boundary) — run S3 after S2.
  - **S2 ∥ S4** (after S1) — disjoint files (`spine_egress`/test vs `spine_remediate`/test).
  - **Only shared file = `backend/health/checker.py`** — S1 ONLY edits it (the cycle hook).
    No other stream touches it. No `ms-enforce`/baseline shared-additive files in this wave.

## Robot mode (autonomous execution)
ONE Opus orchestrator (`.claude/ROBOT.md` § "Architecture — ONE orchestrator per batch").
1. Startup: read ROBOT.md + AUTONOMOUS-DEFAULTS + this file; confirm base
   `git rev-parse origin/main` (expect `b9501ae` or later); High-tier pre-flight →
   `.claude/run/preflight/S-65.md` (BLOCK on FALSE). Create `.claude/run/status/S-65.md`
   (Bash heredoc) with `**State:** RUNNING` as the first non-blank line.
2. **Phase 1 — dispatch ONLY S1** (`isolation:"worktree"`, opus) on `wave/S-65-S1-spine`.
   When it returns, create the wave branch `wave/S-65-agent-spine` and merge S1 into it via a
   dedicated merge worktree detached from origin/main (ONE time, to create the wave branch).
3. **Phase 2 — dispatch S2 and S4 CONCURRENTLY** (single message, multiple Agent tool uses,
   `isolation:"worktree"`, models per table), each branched off the S1-merged wave branch.
   Run **S3 AFTER S2** (shared egress seam). Inject the subagent preamble (`git -C <worktree>`).
4. Each subagent commits to its own `wave/S-65-SN-*` branch + ships its tests. Merge each
   returned stream into `wave/S-65-agent-spine` via merge worktrees **detached from
   `wave/S-65-agent-spine`** (NOT origin/main — that would drop S1). No keep-both shared files
   beyond S1's sole ownership of `checker.py`.
5. Maintain `.claude/run/status/S-65.md` continuously; set `**State:** CLOSED` as the final
   action. Non-blocking decisions → `.claude/run/questions/S-65.md` (proceed, never block; no
   AskUserQuestion). Hard blocker → `.claude/run/blockers/S-65.md` and halt.
6. **OWED before the Manager merges to main** (BACKLOG `:67`): one independent adversarial
   review charged at **the egress/sanitization trust boundary (S2) + the advisory-only
   remediation gate (S4)** — the Manager runs it before the sanctioned merge. The orchestrator
   does NOT merge to main and does NOT push.
