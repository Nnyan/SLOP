# S-75 KNOWLEDGE-LIFECYCLE — make load-bearing knowledge reconcile against physics, and own gap-discovery

## Goal
Stop cross-session knowledge from rotting silently. Build the **two-owner**
reality-reconciliation layer the audit prescribes: the SLOP AI Agent emits a
runtime reality view (its own running state), and a **separate new dev-time tool**
reconciles documented claims against that reality + a host probe, filing
`[gap-discovery]` findings into BACKLOG. Add the freshness mechanisms that can
**fail loudly against physics** (handoff SHA-freshness, run-archive promotion,
fact `verify_probe`), and pin the **reconciler-trust discipline** (GROUND-vs-XREF,
no-silent-pass, probe-aging) so the cure cannot become the next rot source.

Full rationale + taxonomy + fact-store routing: `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`.

## Context
The 2026-05-29 Rocinante session surfaced a class of failures no prior gap-audit
ever caught: a false `CLAUDE.md` deploy fact, a `:8090`-vs-`:8080` belief drift, a
silently-broken `ms-update`, an undocumented ownership model, `.env`-vs-systemd
`Environment=` confusion, a stale `MANAGER-HANDOFF.md`, and tools stranded across a
repo move. The audit's diagnosis: SLOP is reliable where truth is **derived/
reconciled against physical ground truth** (the line ratchet reads real LOC; the
port linter reads `/proc/net/tcp`; the Agent reconciles containers-vs-DB) and rots
where truth is **stored-and-trusted**. Two owned detectors already exist — the
runtime Agent (`backend/core/agent.py`) and dev-time `ms-enforce` + the SessionStart
hook `/home/stack/v5/docs/tools/check_push_status.sh` — but **nothing reconciles a
documented claim against live deploy reality**; the operator was detector-of-last-
resort by default. This wave closes that gap proactively, owned, and recurring.

## Rules to follow
- **Additive only.** No rewrites of `backend/core/agent.py`, `./ms-enforce`, or
  `tools/merge_wave_to_main.py` — extend them. Respect the file-size ratchet
  (`backend/core/**` hard cap 500; `agent.py` is ~243 lines today).
- **Two-owner firewall (HARD).** The SLOP AI Agent stays **runtime-only** — it emits
  reality about the *running instance* and NEVER reads or adjudicates docs. All
  dev-time/process/doc knowledge is owned by the new dev-time tool. Respect memory
  `project-agent-expansion-scope` (extend the Python pipeline; no framework bolt-ons,
  no self-training).
- **GROUND-vs-XREF discipline (HARD).** Only physics-touching probes may assert
  "verified"; text-vs-text probes may only flag inconsistency. No silent skip / no
  silent pass — unreachable ground truth ⇒ `INDETERMINATE` (loud), never `OK`.
- **No stored secret.** The host probe rides the operator's ambient SSH at session
  start (Option A); no tool stores an SSH credential.
- **All new gates land warn-only** (TIER_1), matching the `check_walkback_log` /
  `check_doc_decay` precedent; each carries a documented promotion-to-blocking trigger.
- Dogfood: this wave's own findings live on a **tracked branch**, never the gitignored
  `.claude/run-archive/`.

## Authorized deletions
None. Every change is additive (new files) or an in-place extension of an existing
file. No file or section may be removed.

## Parallelization

**Models (per-wave default):** coordinator = **opus**, subagents = **sonnet** (per-stream overrides in the table).

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A | **opus** | parallel | `general-purpose` in worktree | Runtime reality-emit: extend `backend/core/agent.py` to publish a **RealityView** of the running instance via the existing health surface |
| B | **opus** | parallel | `general-purpose` in worktree | Dev-time reconciler keystone: host-side `slop-reality-probe`, `tools/audit_doc_reality.py` (= `ms-enforce check_doc_reality`), session-start SSH wiring |
| C | sonnet | parallel | `general-purpose` in worktree | Boundary freshness: `tools/check_handoff_freshness.py` (SHA) + run-archive **promotion-reconciliation** in `tools/merge_wave_to_main.py` |
| D | sonnet | parallel | `general-purpose` in worktree | Fact-store freshness convention: `tools/audit_fact_freshness.py` + `last_verified`/`verify_probe` frontmatter + inline `<!-- verify: -->` annotations |
| E | **opus** | parallel | `general-purpose` in worktree | Doctrine + ADR: `docs/adr/0020-knowledge-lifecycle.md`, the reconciler-trust discipline into `CLAUDE.md` + `.claude/AUTONOMOUS-DEFAULTS.md` |

**Per-stream Model justification (required by ROBOT.md § "Per-stream Model column"):**
- A = **opus** — load-bearing runtime change on the executive-manager pipeline; defining the RealityView contract is cross-stream design B depends on; a plausible-but-wrong emit (mislabels which env source loaded a var) passes tests yet poisons the reconciler downstream.
- B = **opus** — irreducible judgment: the SSH/firewall topology, the GROUND-vs-XREF tiering, and the no-silent-pass discipline are exactly the "plausible-but-wrong survives tests" class; a reconciler that blesses a text-vs-text check as "verified" is the disease wearing the cure's clothes.
- C = sonnet — bounded implementation to a clear spec (assert a SHA equals `git rev-parse origin/main`; enumerate run/ findings and warn on un-promoted).
- D = sonnet — bounded: parse frontmatter, run a declared probe, ratchet the `UNPROBED` count; the discipline it enforces is pinned by E.
- E = **opus** — doctrine is load-bearing and shared across sensitive files (`CLAUDE.md`, `AUTONOMOUS-DEFAULTS.md`); getting the GROUND-vs-XREF rule and probe-aging fourth leg precisely right is what keeps every other stream honest.

## Complexity & Pre-flight
**Tier: High.** Scored High by `tools/wave_complexity.py`: 5 parallel streams, 3
**PINNED** cross-stream contracts, sensitive doctrine paths
(`.claude/AUTONOMOUS-DEFAULTS.md`, `CLAUDE.md`), and 3 Opus streams — the floor
guarantee (shared symbols + sensitive paths + Opus stream all present → High)
applies. High-tier pre-flight runs: `validate-wave-file.py` (mechanical) + a
fact-check subagent + processor-contract-pinned + cross-wave disjointness +
edited-wave consistency. Pre-flight must read **DISPATCH-OK** before dispatch.

## Deliverables per stream

### Stream A — Runtime reality-emit (the runtime owner)
1. Extend `backend/core/agent.py` to assemble a **RealityView** of the *running
   instance* and expose it on the existing agent-health surface (no new framework).
   Fields it observes about itself: bound listen port, whether the install dir is a
   git checkout, the owning user of the install dir, and — per env var — which source
   actually populated it (`os.environ` vs `.env`/Starlette `Config`, contrasting
   `backend/platform/storage.py`). Runtime-only; it never reads docs.
2. **PINNED — `RealityView` schema (Stream A owns; Stream B consumes verbatim).**
   A JSON object: `{"schema_version": 1, "observed_at": <iso8601>, "bound_port": int,
   "install_dir_is_git": bool, "install_dir_owner": str, "env_sources":
   {<VAR>: "environ"|"dotenv"|"unset"}}`. Stream B must read these keys verbatim; any
   change is a pinned-contract renegotiation, not a unilateral edit.
3. Unit tests for the emit (assert the view is well-formed and self-consistent),
   using `tmp_path`/fakes — no real host, no real `.env` writes.

### Stream B — Dev-time reconciler keystone (the dev-time owner)
1. **New** host-side `slop-reality-probe` (read-only; ships in the SLOP repo so it
   reaches the deploy host): prints the **PINNED RealityView** JSON to stdout. All
   GROUND-class (reads the live socket / `git -C` / filesystem / process env).
2. **New** `tools/audit_doc_reality.py`, registered as `ms-enforce check_doc_reality`
   (warn-only TIER_1). It reconciles documented claims (the `CLAUDE.md` deploy facts,
   memory deploy facts) against the RealityView. Runs `ssh <host> slop-reality-probe`
   over the **operator's ambient SSH at session start** (Option A — no stored secret);
   host unreachable ⇒ `INDETERMINATE`, never `OK`.
3. **PINNED — `[gap-discovery]` finding contract + verdict vocabulary (Stream B owns;
   C and D consume).** A finding filed to `docs/BACKLOG.md` is a single line
   `[ ] **[gap-discovery]** <claim> — doc says X, reality says Y (probe: <cmd>)`,
   deduped by `<claim>` (update, never re-file). Verdict tokens are exactly
   `verified` (GROUND match), `DRIFT` (GROUND mismatch), `INCONSISTENT` (XREF
   mismatch), `INDETERMINATE` (unreachable). Only `DRIFT` on a load-bearing claim
   files to BACKLOG; `INCONSISTENT` goes to a lower-tier queue not counted against
   BACKLOG triage.
4. One-line wiring note (cross-repo touchpoint, see Cross-wave deps): the SessionStart
   hook `/home/stack/v5/docs/tools/check_push_status.sh` calls `check_doc_reality` as
   a new read-only layer; the orchestrator applies that one-line addition directly
   (v5 is not worktree-able).
5. Tests: reconcile a fixture doc against a fixture RealityView; assert each verdict
   token path and the dedup/severity gate.

### Stream C — Boundary freshness (handoff SHA + run-archive promotion)
1. **New** `tools/check_handoff_freshness.py` (= `ms-enforce check_handoff_freshness`,
   warn-only): assert the SHA `docs/MANAGER-HANDOFF.md` declares for `origin/main`
   equals live `git rev-parse origin/main`; mismatch ⇒ loud warn (GROUND-class).
2. Extend `tools/merge_wave_to_main.py` with **promotion-reconciliation**: at merge,
   enumerate the wave's `.claude/run/<batch>/` observation/decision findings and warn
   on any with zero reference in a tracked doc (BACKLOG / MERGE-LOG / WALK-BACK-LOG /
   MAP) — closing the gitignored `.claude/run-archive/` one-way drain before pruning.
3. Tests for both, fixture-based.

### Stream D — Fact-store freshness convention
1. **New** `tools/audit_fact_freshness.py` (= `ms-enforce check_fact_freshness`,
   warn-only): for memory facts and `CLAUDE.md` facts carrying a `verify_probe`,
   **run the probe and compare** (GROUND); facts with no probe are reported
   `UNPROBED` and counted by a **ratchet** that may shrink, never grow. This replaces
   age-only checking (the audit's "deepest gap": a fact false on day 1, or date-bumped
   to reset the clock, passes `tools/audit_memory_staleness.py`).
2. Add `last_verified` + optional `verify_probe` to the memory-frontmatter convention,
   and inline `<!-- verify: <cmd> -->` annotations on the GROUND-checkable facts in
   the `CLAUDE.md` "Project facts" block ONLY (the verify-annotation half — see PINNED
   CLAUDE.md ownership split).
3. Tests: a probed fact that drifts fails; an `UNPROBED` fact is counted, not blessed.

### Stream E — Doctrine + ADR (the discipline that keeps the cure safe)
1. **New** `docs/adr/0020-knowledge-lifecycle.md` (from `docs/adr/template.md`): the
   derive/reconcile-vs-store/trust decision, the two-owner firewall, GROUND-vs-XREF.
2. Add a **"Knowledge-Lifecycle & reconciliation"** doctrine section to `CLAUDE.md`
   (the prose section — see PINNED ownership split) capturing: a green light must be
   able to go red against physics; no silent pass; probes age (the fourth leg).
3. Add the **gap-discovery ritual cadence** (session-relative, not a silent cron) to
   `.claude/AUTONOMOUS-DEFAULTS.md`, and the `[gap-discovery]` triage handling.
4. **PINNED — reconciler-trust vocabulary (Stream E owns; A/B/C/D consume):** the
   terms `GROUND`, `XREF`, `INDETERMINATE`, `UNPROBED`, and "a green light must be
   able to go red" are defined once in doctrine; all streams use them verbatim.
5. **PINNED — `CLAUDE.md` ownership split:** Stream **E** owns the new doctrine
   *section*; Stream **D** owns ONLY adding inline `<!-- verify: -->` comments to the
   existing "Project facts" block. The two never edit the same lines (the S-59 A↔B
   doctrine-ownership lesson).

## Verification
- `python3 tools/wave_complexity.py .claude/waves/S-75-KNOWLEDGE-LIFECYCLE.md` → **High**.
- `python3 tools/validate-wave-file.py .claude/waves/S-75-KNOWLEDGE-LIFECYCLE.md` → exit 0.
- `python3 tools/preflight_wave.py .claude/waves/S-75-KNOWLEDGE-LIFECYCLE.md` → **DISPATCH-OK**.
- All new gates exit 0 warn-only on a clean tree; each surfaces a real drift on a
  seeded fixture (every green light demonstrably can go red).
- `ms-enforce` exits 0; the file-size ratchet holds (`agent.py` stays < 500).
- Each new probe's verdict line names the ground truth it touched (auditability).
- New unit tests pass; no test writes outside `tmp_path` or to real repo files.
- The two-owner firewall holds: `backend/core/agent.py` contains no doc-reading code;
  `tools/audit_doc_reality.py` contains no SLOP-runtime control logic.

## Out of scope
- **Deploy-path fixes themselves** (`ms-update`/`deploy.sh` run-as-service-user,
  guarded fetch, post-update SHA-verify, error-channel surfacing, `.env`-vs-systemd
  config-source *decision*) — **ceded to S-74-DEPLOY-HARDENING**; this wave consumes a
  sane update path, it does not fix it. (See Cross-wave deps.)
- **Aging-engine consolidation** (unifying facts-aging with gate-aging/doctrine-aging
  onto one timestamp engine) — a shared design contract with **Enforcement-Lifecycle
  (S-70+S-72)**, deferred to that wave; here we build standalone freshness checks.
- **Code-contract drift** (the two `CatalogEntry` defs, `_SLOP_MANAGED_VARS`) — already
  partly covered by `tests/test_rules_migration_batch1.py`; not re-solved here.
- **Full derived `MANAGER-HANDOFF.md` generation** — only the GROUND SHA-freshness
  assertion now; full rendering depends on a stable BACKLOG token grammar (XREF, fragile).
- Dependency/world drift and rationale rot — noted follow-ups, not this wave.

## Cross-wave dependencies (EXPLICIT)
- **Hard sequence after S-74-DEPLOY-HARDENING (batch-9 → this is batch-10).** The
  host-reality probe (Stream B) assumes a sane, SHA-verifying update path, and both
  waves edit the **`CLAUDE.md` deploy section**; they are NOT file-disjoint there.
  S-74 must merge to main first. This is the rare cross-batch hard dependency the
  one-orchestrator-per-batch doctrine names — it is *between* batches (normal
  sequencing), not multiple orchestrators within a batch.
- **Riders handed to S-74 (co-batched into it, not duplicated here):** post-update
  SHA-verification + stop-swallowing-stderr (error-channel integrity, audit T8) +
  the `.env`-vs-systemd config-source decision (T7) — all deploy-fix-shaped and S-74
  already edits those exact lines.
- **Shared design contract with Enforcement-Lifecycle (S-70+S-72, batch-11+):**
  facts-aging is the same shape as gate-aging/doctrine-aging. Both touch `./ms-enforce`
  and doctrine docs — but Enforcement-Lifecycle is deferred until the warn-only gates
  accumulate run-history signal, so there is **no concurrency conflict**; the only
  interaction is the forward-compatible aging-engine interface, noted for that wave to
  absorb. Do NOT couple delivery.
- **Intra-wave shared touchpoints (PINNED, must hold):** (1) the **RealityView schema**
  (A produces → B consumes); (2) the **`[gap-discovery]` finding + verdict vocabulary**
  (B owns → C/D consume); (3) the **reconciler-trust vocabulary** (E owns → all
  consume); (4) the **`CLAUDE.md` ownership split** (E = doctrine section; D = inline
  verify-annotations; disjoint lines).
- **Cross-repo touchpoint:** the one-line call into
  `/home/stack/v5/docs/tools/check_push_status.sh` is applied by the orchestrator
  directly (v5 is a separate repo, not worktree-able) after Stream B merges.

## Robot mode (autonomous execution)
**ONE Opus orchestrator** for this single-wave batch (per the one-orchestrator-per-
batch doctrine). It runs `tools/preflight_wave.py` (must read DISPATCH-OK), then
dispatches **all 5 streams concurrently** as `general-purpose` subagents in separate
git worktrees (max parallelism — no stream has a hard dependency on another *landing*;
they share only the PINNED contracts above, which are fixed text). Streams are
file-disjoint except the two PINNED `CLAUDE.md` editors (E = new section, D = inline
annotations on different lines) — the orchestrator merges E before D and resolves the
single file at merge with the pinned ownership split as the authority. Merge each
stream **into the wave branch in a dedicated detached-HEAD merge worktree** (the S-74
pattern — `.claude/worktrees/merge-S-75`, never on `main`), gating each merge on
status=COMPLETE + ms-enforce-green + conflict-abort and logging an `S-75-MERGE-N.md`
decision for any non-trivial resolution. `tools/merge_wave_to_main.py` is the
**Manager's** wave→main channel only — the orchestrator does NOT use it for stream→wave
merges. After all merge, the orchestrator applies the one-line v5 hook addition. Do not
push; the Manager reviews + merges the wave branch to main with the sanctioned tool, and
only after **S-74 has landed on main**.
