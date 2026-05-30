# Knowledge-Lifecycle & Gap-Discovery Audit — Charter

**For:** a fresh **Opus Auditor-Manager** session (+ its read-only lens subagents).
**Status:** approved 2026-05-29. This is a discovery/design phase that **produces** the
implementation batch — it is NOT itself a code wave.
**Output goes on branch `docs/wave-draft-knowledge-lifecycle`. Do NOT merge to main**
— the Manager reviews + merges.

## 1. The problem
Despite rules, ms-enforce gates, ADRs, BACKLOG triage, walk-back logs, and a
structured-plaintext memory system, cross-session continuity keeps failing: facts
rot, work is dropped, things go stale/untracked, and big transitions strand
artifacts. Critically, **our prior gap-audits never surfaced these classes — they
only surface via friction** (a live failure), with the operator as the manual
detector-of-last-resort. The goal: make gap-discovery **proactive, owned, and
recurring**, so neither the operator nor any single session has to be the detector.

## 2. Evidence (derive your taxonomy from THESE, not from theory)
This session (2026-05-29), updating the Rocinante test server + reviewing process:
- **Stranded artifacts across a repo move:** the `MS*` tools were left on the
  `mediastack` (dev) repo after the move to public `SLOP`; this dev env was unaware
  of them for a while.
- **A false stored fact:** CLAUDE.md said "No git on target server — scp + sudo cp";
  the target is actually an HTTPS git clone. Found only by hitting it live.
- **Doc-vs-reality drift, unreconciled:** operator believed SLOP ran on `:8090`;
  code/docs say `:8080`; the only authority was the box's journald. No store
  reconciled belief vs reality.
- **An undiscovered product bug:** `sudo ms-update` silently did nothing (root git on
  a service-user-owned repo → dubious-ownership → `set -e` death w/ suppressed
  stderr). Unknown until it bit.
- **An undocumented ownership model** → a bad `chown` crash-looped the service.
- **`.env` vs systemd `Environment=`:** operator-facing env silently didn't load;
  undocumented.
- **The handoff was stale at session start** ("batch-7 in-flight" when it had finished).
- Historical siblings: the `.60 → .51` server move and the `mediastack → SLOP` repo
  move both dropped things.

Forensics: `docs/BACKLOG.md` §"From Rocinante deploy session", memory
`project-rocinante-deploy`, this session's `docs/MERGE-LOG.md` entries.

## 3. The charge (BOTH levels required)
**A. Object-level — Knowledge-Lifecycle (K-L).** Design how load-bearing knowledge
stays true over time. Independently derive a failure-mode taxonomy from the evidence,
then a methodology routing each kind of knowledge by **volatility × source-of-truth**
(e.g. derive-don't-store / structured-state-with-freshness / rationale+staleness-audit
/ derived-not-authored handoff). Name the concrete mechanisms (session-boundary
reconciliation, staleness gates, a derived handoff, a transition/migration
reconciliation checklist, etc.).

**B. Meta-level — the recurring Gap-Discovery Ritual.** Design the repeatable process
that catches blind-spots PROACTIVELY — multi-lens, seam-crossing
(repo↔server↔other-repo↔running-state), reality-reconciling — so discovery is
periodic + batched, not friction-driven. **Explicitly audit WHY prior gap-analyses
(incl. the Tier-1–7 meta-analysis in `docs/MANAGER-HANDOFF.md` "Open meta-patterns",
and the Appendix below) missed these classes**, and design the ritual to defeat that
failure mode. This is the part that gets the operator out of the detector seat.

## 4. Fixed constraints (decided — design WITHIN these)
- **Audit topology:** ONE Opus Auditor-Manager dispatches **parallel READ-ONLY lens
  subagents** (no worktrees — findings, not file mutations). Minimum lenses:
  **reality-drift**, **transition/seam**, **temporal-decay**, **unmeasured-dimension**
  ("what axis are we structurally not measuring?"). Add lenses if warranted. Then a
  **phase-2 blind-spot critic** reviews the MERGED findings ("what did all lenses
  collectively miss?"). The Manager synthesizes. (One manager + many auditors — NOT
  multiple independent top-level sessions; synthesis needs one mind seeing all lenses.)
- **Independence:** each lens derives from the evidence **independently FIRST**. The
  Appendix (a prior single-session analysis) is to be **attacked for blind spots, not
  adopted** — read it only after your own derivation, and score it for what it missed.
- **Two-owner architecture (firewalled by layer):**
  - **SLOP runtime-knowledge** reconciliation → owned by the **SLOP AI Agent**
    (`backend/core/agent.py`), as an EXTENSION of its existing reality-reconciliation
    (ghost-container detection) to config/version/artifact drift. Respect memory
    `project-agent-expansion-scope` (extend the Python pipeline; reject framework
    bolt-ons / self-training). **Keep the SLOP AI Agent focused ONLY on SLOP runtime.**
  - **Dev-time K-L + the gap-discovery ritual** → owned by a **SEPARATE new dev-time
    tool** (repo/session layer), NOT the SLOP AI Agent. Define the minimal interface
    (e.g. the dev-time tool writes findings into a tracked queue / BACKLOG; it does
    not live inside the runtime Agent).
- **Implementation shape:** the batch this audit produces MUST use **Robot mode with
  maximum stream parallelism to minimize the number of sequential waves.** **Analyze
  co-batching** with queued waves — **S-74-DEPLOY-HARDENING** and the deferred
  **Enforcement-Lifecycle (S-70+S-72; "aging" — a sibling theme: gates age, doctrine
  ages, and K-L = facts age, the third aging leg, so synergy is likely)** — and
  recommend what can run concurrently (file-disjointness permitting) vs what must
  sequence. New tasks/streams should be analyzed for what can ride along with existing
  waves. You decide **spike-vs-wave-vs-multi-batch** and **justify** it.

## 5. Deliverables (on `docs/wave-draft-knowledge-lifecycle`)
1. **Audit report** — independently-derived failure taxonomy; the blind-spot analysis
   (why prior audits missed these); the fact-store inventory + per-fact routing.
2. **Implementation plan as wave file(s)** in `.claude/waves/`, authored on
   `.claude/waves/_TEMPLATE.md` with the per-stream **Model column** + justifications,
   **dogfooded green**: `python3 tools/wave_complexity.py`,
   `python3 tools/validate-wave-file.py`, `python3 tools/preflight_wave.py`
   (→ DISPATCH-OK). Encode the two-owner design + the ritual + the co-batching call.
3. **The orchestrator launch prompt** for a fresh Robot orchestrator to run the batch.
4. Commit; **do not merge, do not push.**

## 6. Where to look
Stores to audit: `CLAUDE.md`, the memory dir + `MEMORY.md`, `.claude/ROBOT.md`,
`.claude/AUTONOMOUS-DEFAULTS.md`, `docs/BACKLOG.md`, `docs/MERGE-LOG.md`,
`docs/MANAGER-HANDOFF.md`, `.claude/run-archive/`, `docs/MAP.md`, `docs/adr/`,
`docs/WALK-BACK-LOG.md`, the slop-process docs repo (`/home/stack/v5`), git history.
Mechanisms to study/extend: the **SLOP AI Agent + ghost-detection** (the reconciliation
model), the **SessionStart 3-repo-sync hook**
(`/home/stack/v5/docs/tools/check_push_status.sh` — an EXISTING boundary-reconciliation
mechanism worth extending), S-70/S-72 (sibling aging work), the batch-7 wave-authoring
tooling (for dogfooding).

## Appendix — a prior single-session analysis (ATTACK THIS; derive your own first)
Produced by the Manager session that wrote this charter. It is a single perspective
with a single blind spot. **Do not adopt it. Derive independently, then use this only
to find what BOTH it and your lenses missed.**

- **Reframe:** not a storage shortage — a storage *surplus* with no *lifecycle*. The
  failures are decay, fragmentation/no-single-source-of-truth, retrieval-blindness,
  transition-discontinuity, and ground-truth-drift — none fixed by "more memory."
- **Claims vs reality:** memory tools (vector RAG, Mem0, Zep, Letta, memU, Chroma,
  LlamaIndex, SimpleMem) index *claims*; our worst failures are *reality drift*. The
  codebase is reliable exactly where truth is **derived/reconciled** (ratchet reads
  real line counts; port linter reads `/proc/net/tcp`; ghost-detection reconciles
  containers vs DB) and rots exactly where truth is **stored & trusted**. The dev
  process lacks the reconciliation SLOP-the-product already has.
- **Route by volatility × source-of-truth:** derivable → probe, don't store;
  mutable-external → structured state + `last-verified` + cadence; rationale → ADR +
  staleness audit; in-flight/handoff → **derive from git/BACKLOG/run-state, don't
  hand-author** (the static HANDOFF is itself an anti-pattern — stale the instant work
  resumes).
- **Aging trilogy:** gates age (S-70), doctrine ages (S-72), facts age (this) — same
  shape. The philosophy "tool-enforced doctrine" (rules → gates) applied to *facts*:
  every load-bearing fact is derived, or carries a check that fails when it drifts.
- **Tooling take:** if a store is needed at all, temporal/self-editing memory
  (Zep's fact-invalidation, Letta) fits the *decay* failure; vanilla vector RAG is the
  *least* aligned (retrieval, not lifecycle) and fights this project's plaintext
  auditability. Risk: a slick store invites *more* trust while rotting silently —
  worse than plaintext you appropriately distrust. Prefer methodology over a DB.
- **Existing leverage:** the SessionStart 3-repo-sync hook is already the right
  "derive truth at the boundary" mechanism — it just reconciles git, not knowledge.
  Extend it rather than bolt on a new store.
- **Known limit (state it honestly):** no audit eliminates friction-surfaced gaps; it
  shrinks them. The win is converting an infinite friction-trickle into a periodic,
  bounded, prioritized inventory the system owns.
