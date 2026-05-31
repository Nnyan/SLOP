# BATCH-12 — Process-Hardening — close the two batch-11 orchestration-incident follow-ups

## Goal
Land the two `[→ next agent/process wave]` follow-ups batch-11 filed (BACKLOG
`:64`, `:65`), each as a GROUND-grounded fix that can go red against physics:

1. **Sanctioned-channel integrity (S1):** make the routine push tool crash-safe
   (`try/finally` restore) AND bring it under the GROUND auditor by registering it
   in the sanctioned-channels registry — so a leaked deny is caught, not silent.
2. **Checkout-borrow defect (S2):** turn "an orchestrator must not borrow the
   shared main checkout / every concurrent dispatch is `isolation:"worktree"`" from
   a recovered-from incident into **doctrine + a GROUND red-signal probe** that goes
   red when the canonical checkout is sitting on a `wave/*` branch.

## Context
The batch-11 Phase-2 dispatch **omitted `isolation:"worktree"`**, so 9 streams
collided in the shared canonical checkout `/home/stack/code/slop`. The orchestrator
recovered all work forensically (patch-id verified) and `main` was never
contaminated — but at the cost of a full recovery pass, and only because a human
noticed. Two defects were filed:

- **`tools/sanctioned/lift_push_restore.py`** (verified against source 2026-05-30):
  `main()` calls `restore()` only on the happy path / `rc != 0` — a true **exception**
  in `push()`/`_save()` between `lift()` and `restore()` skips restore entirely and
  leaks the `Bash(git push*)` deny (leaves the session push-unlocked). It is also
  **absent from the `docs/SANCTIONED-CHANNELS.md` Registry table**, so the batch-11
  GROUND gate `tools/audit_sanctioned_ground.py` (`check_sanctioned_ground`) never
  audits it. **Composition bonus:** that gate already checks `restore_is_guaranteed`
  (finally-guarded) per registry-row tool — so adding the registry row makes the gate
  itself flag the missing `finally`, and it goes green only once BOTH halves land
  (dogfoods the batch-11 machinery).

- **The checkout-borrow rule has no enforcement.** A prior memory + the batch-11
  handoff claimed the red-signal "already shipped" via a probe file under a
  `.claude/hooks/` directory — **VERIFIED FALSE 2026-05-30**: no such directory or
  file exists in the tree or in any git history (a phantom pointer). The probe must
  be built fresh by this wave (S2 builds it under `tools/`, not `.claude/hooks/`).
  You cannot *statically* prevent an `isolation`-less dispatch (it is a runtime
  tool-call), but you CAN GROUND-detect its footprint: the canonical checkout on a
  `wave/*` branch outside a merge worktree.

This is a single-wave batch (one orchestrator, two streams) — it dogfoods its own S2
rule by running both streams `isolation:"worktree"`.

## Rules to follow
- **Additive, not rewrite.** S1 wraps an existing function body in `try/finally`
  (minimal diff, behaviour-preserving on the happy path) + appends a registry row +
  appends a probe row. S2 appends a new `check_` + TIER_1 block to `ms-enforce`,
  appends a probe row, and appends a doctrine subsection to `.claude/ROBOT.md` — never
  reformat a neighbouring block.
- **Every new gate lands TIER_1 warn-only** and ships a **red-path test** (feed a
  known-bad input, assert DRIFT / non-zero — proves it can go red). No gate
  auto-promotes to blocking in this batch.
- **Honor the pinned probe-registry contract** (`docs/PROBE-REGISTRY.md`): a probe row
  is APPENDED to `tools/probe_registry.json` `"probes"` (keep-both-whole-block); you do
  NOT edit `tools/audit_probe_aging.py` logic. Name the physics, or it is not GROUND.
- **S2 trips the independent-review mechanical floor** (it edits `.claude/ROBOT.md` AND
  adds a `def check_`): it MUST carry the **four-question rationale** (what need, why this
  mechanism, its failure mode, its red-signal) + a `docs/REVIEW-LOG.md` entry grounded on
  a committed record. The doctrine edit is a **strengthening → NO WALK-BACK-LOG entry**.
  The new-gate adversarial review (fresh-Opus subagent tier) is **owed at batch-landing**
  (the Manager runs it before the sanctioned merge); the stream notes it as owed.
- File-size ratchet applies (`tools/` is capped post-batch-11 S8 — do not rely on a gap).

## Authorized deletions
None of substance. No history rewrites. Streams may delete only dead scaffolding they
themselves create.

## Parallelization

**Models (per-wave default):** orchestrator = **opus**, subagents = per-stream below.

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| **S1** sanctioned-channel integrity | **sonnet** | parallel | `general-purpose` in worktree | `lift_push_restore.py` try/finally + `SANCTIONED-CHANNELS.md` registry row + registry probe + red-path test |
| **S2** checkout-borrow doctrine + GROUND probe | **opus** | parallel | `general-purpose` in worktree | new `tools/audit_canonical_checkout.py` + `check_canonical_checkout` (ms-enforce TIER_1) + probe row + `.claude/ROBOT.md` doctrine + four-question rationale + REVIEW-LOG entry + red-path test |

**Per-stream Model justification (rubric, ROBOT.md § "Per-stream Model column"):**
- **S1 = sonnet** — bounded, well-specified implementation against settled interfaces
  (wrap a known body in try/finally; append one documented registry row; append one
  probe row). The acceptance is mechanical (the existing GROUND gate verifies it).
- **S2 = opus** — irreducible judgment: it must define a NEW GROUND probe whose
  red-condition is precisely scoped (DRIFT only on `wave/*` in the canonical checkout,
  NOT on legitimate `docs/*` draft branches or `agent-*`/`merge-*` worktrees), edit
  load-bearing doctrine, and prove the gate goes red — plausible-but-wrong risk is high.

## Complexity & Pre-flight
**Tier: High** (`tools/wave_complexity.py` score 9 — driven by 2 sensitive
doctrine/security paths (`.claude/ROBOT.md` + a sanctioned-channel tool), 1 Opus
stream, a refactor (the try/finally rewrite), 2 parallel streams). Despite only 2
streams, the doctrine+sanctioned-path surface scores High. Run High-tier pre-flight
(validate-wave-file + fact-check subagent + processor-contract-pinned +
cross-wave-disjointness + edited-wave consistency). Write the verdict to
`.claude/run/preflight/BATCH-12.md`. **BLOCK dispatch on any FALSE.**

## Deliverables per stream

### Stream S1 — Sanctioned-channel integrity (BACKLOG :65)
1. **`tools/sanctioned/lift_push_restore.py` — `try/finally` restore.** Refactor `main()`
   so that once `lift()` has run, `restore(branch)` is **guaranteed** in a `finally`
   block regardless of how `push()` exits (normal return, non-zero rc, OR raised
   exception). Preserve current behaviour on the happy path; the only change is that an
   exception between lift and restore can no longer leak the deny. Keep the surgical
   single-pair lift/restore (do NOT switch to the profile-wholesale `_lift_restore`).
2. **`docs/SANCTIONED-CHANNELS.md` — Registry row.** Add a row to the "Registry: deny →
   sanctioned tool" table mapping `Bash(git push*)` (routine path) →
   `tools/sanctioned/lift_push_restore.py`, Notes = "routine UNAUDITED push; restore is
   try/finally-guarded; UNAUDITED by design (no SANCTIONED-OPS-LOG receipt)". This brings
   it under `check_sanctioned_ground`. NOTE the existing `_AUDIT_EXEMPT` entry in
   `audit_sanctioned_ground.py` already records `lift_push_restore.py` as UNAUDITED — so
   the audit-leg is correctly exempt; only the try/finally leg must now pass.
3. **Probe-registry row** (open-seam append to `tools/probe_registry.json`): register the
   `check_sanctioned_ground` verdict as an aged probe (id e.g. `sanctioned_ground`,
   physics = "AST of each registry-row sanctioned tool's source", `host_configured:false`)
   so the GROUND leg can't silently disarm. Follow `docs/PROBE-REGISTRY.md` schema.
4. **Red-path test** (`tests/test_sanctioned_ground.py` exists — extend it, or a sibling):
   simulate a crash mid-`push()` (monkeypatch `push` to raise) and assert the deny is
   RESTORED (the try/finally invariant); AND a fixture proving `audit_sanctioned_ground`
   now reports the tool `verified` (was previously not covered at all).
5. **Verify** `python3 tools/audit_sanctioned_ground.py --repo .` reports
   `lift_push_restore.py` as `verified` (exists + try/finally guarded + audit-exempt),
   and `ms-enforce` exits 0 on the stream branch.

### Stream S2 — Checkout-borrow doctrine + GROUND probe (BACKLOG :64)
1. **`tools/audit_canonical_checkout.py`** — a GROUND probe. **Physics:** the branch
   checked out in the canonical worktree `/home/stack/code/slop`
   (`git -C <repo> rev-parse --abbrev-ref HEAD` + `git -C <repo> rev-parse --git-common-dir`
   to confirm it is the canonical checkout, not a linked worktree). **Verdicts:**
   - `DRIFT` — the canonical checkout's HEAD is a `wave/*` branch (the borrow footprint:
     a stream/wave branch is checked out where only `main` (or a `docs/*` draft) belongs).
   - `verified` — HEAD is `main` or a `docs/*`/non-`wave/*` branch (legitimate).
   - `INDETERMINATE` — git unavailable / path missing (emit loudly, never downgrade to OK).
   **Scope the red-condition precisely:** DRIFT ONLY on `wave/*` in the canonical checkout.
   Do NOT flag `agent-*`/`merge-*` linked worktrees (separate paths — a correct wave keeps
   the canonical checkout on `main` even mid-run) or `docs/*` draft branches (legitimate
   drafting practice). This precision is the stream's load-bearing correctness.
2. **`check_canonical_checkout`** registered in `ms-enforce` (TIER_1 warn-only, APPEND its
   own block — do not reformat neighbours). Maps the probe's DRIFT → a warn-only finding.
3. **Probe-registry row** (open-seam append to `tools/probe_registry.json`): id e.g.
   `canonical_checkout_on_main`, physics = "git HEAD branch of the canonical checkout",
   `cmd` = `python3 tools/audit_canonical_checkout.py --report`, ground_tokens
   `["verified","DRIFT"]`, brownout_tokens `["INDETERMINATE"]`, `host_configured:false`.
4. **`.claude/ROBOT.md` doctrine subsection** (APPEND under "The binding rules" or the
   "Architecture" region — pick the disjoint anchor, do not edit the §3.3/§3.5/§3.6 regions
   batch-11 pinned): state that (a) **every concurrent `agent()`/Agent dispatch MUST pass
   `isolation:"worktree"`**; (b) **an orchestrator MUST NOT borrow the canonical checkout
   `/home/stack/code/slop` for stream work** — the canonical checkout stays on `main` (the
   orchestrator operates from its own named worktree if it needs a working tree); (c) a
   shared-checkout dispatch is an **orchestration defect**, GROUND-detected by
   `check_canonical_checkout`. Cite the batch-11 incident as the source.
5. **Four-question rationale** (in the commit body AND the REVIEW-LOG entry): what need
   (prevent shared-checkout collisions + commit-leakage), why this mechanism (runtime
   dispatch can't be statically blocked → GROUND-detect the footprint + doctrine), its
   failure mode (the rule is prose until the probe ages enough runs; a borrow that is
   created-and-reverted within one run between probe runs is missed), its red-signal
   (`check_canonical_checkout` DRIFT + the aged probe). It is a **strengthening → NO
   WALK-BACK-LOG**.
6. **`docs/REVIEW-LOG.md` entry** grounded on a committed record (this stream's commit +
   the four-question rationale). Note the **owed** new-gate adversarial review (fresh-Opus
   subagent) to be run by the Manager at batch-landing before the sanctioned merge.
7. **Red-path test** (`tests/test_audit_canonical_checkout.py`): a fixture git repo whose
   canonical checkout is on a `wave/*` branch asserts DRIFT; on `main` asserts `verified`;
   a `docs/*` branch asserts `verified` (the false-positive-suppression case); git-missing
   asserts INDETERMINATE.

## Verification
- `ms-enforce` exits 0 on each stream branch AND on the merged `wave/batch-12`.
- S1: `audit_sanctioned_ground.py` reports `lift_push_restore.py` `verified`; the crash-mid-push
  red-path test passes (deny restored).
- S2: `check_canonical_checkout` DRIFTs on the `wave/*`-checkout fixture and verifies on the
  `main` + `docs/*` fixtures; the probe row is registered and aged by `audit_probe_aging.py`.
- Both new probe rows appear in `tools/probe_registry.json` and the aging engine reads them.
- S2 has a `docs/REVIEW-LOG.md` entry + four-question rationale; NO WALK-BACK-LOG (additions).
- No stream auto-promotes a gate to blocking.

## Out of scope
- Promoting any gate to blocking (later deliberate act).
- A static lint that rewrites/forbids `isolation`-less Agent calls (not statically
  detectable; the GROUND footprint probe is the buildable red-signal).
- The agent self-audit/spine wave (next, separate draft) and the agent-expansion roadmap.
- Any Rocinante host work.

## Cross-wave dependencies (EXPLICIT)
- **Depends on batch-11 (landed on main `2877d58`):** S1 consumes `audit_sanctioned_ground.py`
  + the `_AUDIT_EXEMPT` entry; both streams consume S1-batch-11's probe registry + schema
  (`tools/probe_registry.json`, `docs/PROBE-REGISTRY.md`, `tools/audit_probe_aging.py`).
  Confirm these exist at base before dispatch.
- **Intra-wave:** S1 and S2 are **disjoint** — different tools, different tests, different docs
  (S1: `lift_push_restore.py`, `SANCTIONED-CHANNELS.md`; S2: new `audit_canonical_checkout.py`,
  `.claude/ROBOT.md`). The ONLY shared files are append-only:
  - `tools/probe_registry.json` — BOTH append a probe row → **keep-both-whole-block**.
  - `ms-enforce` TIER_1 registration — S2 only (S1 reuses the existing `check_sanctioned_ground`).
  No sequencing required; run S1 ∥ S2.

## Robot mode (autonomous execution)
ONE Opus orchestrator (`.claude/ROBOT.md` § "Architecture — ONE orchestrator per batch").
1. Startup: read ROBOT.md + AUTONOMOUS-DEFAULTS + this file; confirm base
   `git rev-parse origin/main` (expect `2877d58` or later); Medium-tier pre-flight →
   `.claude/run/preflight/BATCH-12.md` (BLOCK on FALSE). Create
   `.claude/run/status/BATCH-12.md` (Bash heredoc) with `**State:** RUNNING` as the first line.
2. Dispatch **S1 and S2 CONCURRENTLY** (single message, multiple Agent tool uses;
   **`isolation:"worktree"`** on BOTH — this wave dogfoods its own S2 rule; model per the
   table). Inject the subagent preamble (`git -C <worktree>` pin).
3. Each subagent commits to its own `wave/B12-SN-*` branch + ships its red-path test.
4. Create the batch branch `wave/batch-12` and merge both streams into it via a **dedicated
   merge worktree detached from `origin/main`** (`.claude/worktrees/merge-batch-12`);
   keep-both-whole-block on `tools/probe_registry.json`. The post-wave merge to main is the
   **Manager's** job via `tools/merge_wave_to_main.py` (NOT the orchestrator). Do NOT push.
5. Maintain `.claude/run/status/BATCH-12.md` continuously; set `**State:** CLOSED` as the final
   action. Non-blocking decisions → `.claude/run/questions/BATCH-12.md` (proceed, never block;
   no AskUserQuestion). Hard blocker → `.claude/run/blockers/BATCH-12.md` and halt.
