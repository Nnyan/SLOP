# BATCH-11 — Enforcement-Lifecycle — close the "GROUND-gate brownout" class

## Goal
Make SLOP's doctrine/process gates **red-eligible against physics** instead of
warn-only-by-default. Batch-11 builds the cross-cutting **probe-aging /
brownout detector** (so a gate that loses its ground goes red, not green),
then lands the prioritized blast-radius fixes the Coverage+Handoff audit
produced. Source of record: `docs/COVERAGE-HANDOFF-AUDIT-REPORT.md` §5 (P0–P9)
+ §6 (co-batching) + this batch's F10 addition.

## Context
The audit's one-sentence finding: SLOP has a large gate library that is
**warn-only end-to-end** for the doctrine/process surface, and its few real
GROUND gates share one silent failure mode — the **"GROUND-gate brownout":**
*a probe that degrades to INDETERMINATE / unparseable / missing-input keeps
returning the same color as a match.* Two instances were LIVE-RED on main:
- **LR-1** (`check_handoff_freshness` defeated by a prose rewrite) — **FIXED on
  main ahead of this batch** (commit lands with the audit report; the gate now
  reads a committed `.handoff-sha`, absence→DRIFT). Batch-11 P1 only needs the
  *auto-stamp* half (merge tool writes `.handoff-sha`).
- **LR-2** (`slop-reality-probe` never installed on host → S-75 reconciler
  touches zero physics, exits 0) — operator installs the probe out-of-band;
  P1 moves the install onto the automated deploy path so it can't regress.

**Hard architectural fact (§6):** P0 (the aging engine) ⊃ the deferred
Enforcement-Lifecycle core (S-70 + S-72) — they are the **same stream**, built
once. Every other stream relies on "INDETERMINATE is red-eligible" to be
non-theatrical, so **P0/S1 lands on the batch branch FIRST**.

## Rules to follow
- **Additive, not rewrite.** New gates append their own `check_` + TIER_1
  registration block in `ms-enforce`; never reformat neighbouring blocks.
  `ms-enforce` TIER_1 registration is a KNOWN multi-stream additive touchpoint
  (S5, S7 both touch it) → keep-both-whole-block protocol, parallel-safe.
- **Every new gate lands TIER_1 warn-only** and ships with a **red-path test**
  (feed a known-bad input, assert DRIFT / non-zero — proves it can go red).
  No gate auto-promotes to blocking here (promotion is a later deliberate act).
- **Honor recorded scope-reasons** (the single-entity-hardcode hunt must
  SUPPRESS justified hardcodes, e.g. `lift_push_restore.py` SETTINGS_PATH — its
  day-one false-positive-suppression test).
- **Doctrine edits trip the independent-review mechanical floor** (S4/S5/S7 +
  the prompt-doctrine edit touch CLAUDE.md / `.claude/ROBOT.md` /
  `AUTONOMOUS-DEFAULTS.md` or add a `def check_`): each carries the
  four-question rationale + a `docs/REVIEW-LOG.md` entry grounded on a
  committed record. Additions are strengthenings → NO WALK-BACK-LOG entry;
  only softening an existing rule trips that.
- File-size ratchet applies (note: `tools/` is currently UNCAPPED — S8 fixes
  the aperture; do not rely on the gap).

## Authorized deletions
None of substance. Streams may delete dead scaffolding they themselves create.
Do NOT delete or rewrite existing gates' logic except: S8 widens
`check_linecount.py` CATEGORIES/aperture (additive catch-all), S5 adds a
glob-fallback to `_find_status_file` in `merge_wave_to_main.py` (additive,
warn-on-inexact). No history rewrites.

## Parallelization

**Models (per-wave default):** orchestrator = **opus**, subagents = per-stream below.

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| **S1** aging engine / brownout detector (= P0 + S-70/S-72 core) | **opus** | **sequential — FIRST, merge to batch branch before others integrate** | `general-purpose` in worktree | the cross-cutting probe-aging reconciler + `.probe-health-baseline.json` |
| **S2** cross-repo triage-queue registry (P2) | **opus** | parallel (author before S3) | `general-purpose` in worktree | `(repo,file,syntax)` registry generalizing `check_backlog_stale` over the 3 rings |
| **S3** park-rule triad enforcement (P3) | **sonnet** | sequential after S2 (shared file) | `general-purpose` in worktree | parseable backstop-date / trigger / owner legs in `audit_backlog_stale.py` |
| **S4** session-boundary hooks + wind-down (P4) | **opus** | parallel (after S1) | `general-purpose` in worktree | `.claude/settings.json` hooks + `check_session_winddown` |
| **S5** status protocol + red-on-missing-status gate + **F10** (P5 + F10) | **opus** | parallel (after S1) | `general-purpose` in worktree | orchestrator status template, missing-status gate, **two-artifact handoff doctrine + red-signal** |
| **S6** sanctioned-channel GROUND leg (P6) | **opus** | parallel | `general-purpose` in worktree | per-tool file/AST presence + red-path "deny restored after push" test |
| **S7** walkback + independent-review artifact legs (P7) | **opus** | parallel | `general-purpose` in worktree | `check_walkback_log` GROUND leg + the PENDING `check_independent_review` + artifact-existence helper |
| **S8** ratchet aperture + provenance + pre-commit hook (P8 + adjacents) | **sonnet** | parallel | `general-purpose` in worktree | catch-all ratchet category, `.sh`/`.yaml` aperture, `check_provenance`, local ratchet pre-commit hook |
| **S9** point coverage gaps (P9) | **sonnet** | parallel | `general-purpose` in worktree | `_DEFAULT_STACKS` ref test, catalog port-uniqueness, CatalogEntry doc-fix + union field-sync, 3 data-dir SoT |
| **S10** run-archive un-promoted-findings drain (cleanup) | **sonnet** | parallel | `general-purpose` in worktree | triage the 42 un-promoted findings: promoted-already / promote-now / `[—]` |

**Per-stream Model justification (rubric, ROBOT.md § "Per-stream Model column"):**
- S1 = opus — load-bearing cross-cutting design (the engine every other stream depends on); plausible-but-wrong risk is highest.
- S2 = opus — interface generalization (registry over a plural set) with blast-radius reasoning; reshapes a file's I/O signature.
- S3 = sonnet — bounded parser-leg additions against S2's settled signature.
- S4 = opus — new harness-integration surface (`settings.json` hooks) with the §4f "hook is not the boundary it's sold as" subtlety to honor.
- S5 = opus — doctrine (F10) + a new GROUND gate + status-template changes; irreducible judgment on the two-artifact contract.
- S6 = opus — security-adjacent (the rails that watch the rail-bypass tools); red-path correctness is subtle.
- S7 = opus — acyclicity + artifact-existence reasoning; reuses `check_walkback_log` shape, must not self-trigger.
- S8 = sonnet — mostly mechanical aperture widening + header gate against clear specs.
- S9 = sonnet — bounded, well-specified point tests/fixes.
- S10 = sonnet — mechanical triage against durable docs (XREF).

## Complexity & Pre-flight
**Tier: High** (10 streams, cross-stream contracts, doctrine edits, a hard P0
sequence). Run High-tier pre-flight: validate-wave-file + fact-check subagent +
processor-contract-pinned check + cross-wave disjointness + edited-wave
consistency. **BLOCK dispatch on any FALSE.** Write verdict to
`.claude/run/preflight/BATCH-11.md`.

## Deliverables per stream
> Full rationale + each item's own failure-mode + red-signal: report §5 (P0–P9).
> Each stream commits to its own `wave/B11-SN-*` branch.

### Stream S1 — Aging engine / brownout detector (P0 + S-70/S-72 core) — PINNED producer
1. `tools/audit_probe_aging.py` + `.probe-health-baseline.json` (shrink-only ratchet, sibling to `.factprobe-baseline.json`): for every registered probe, record per run whether it reached ground (`verified`/`DRIFT`) or browned out (`INDETERMINATE`/unparseable/missing-input/no-date); flag any probe with **no ground-touch in N runs** → DRIFT.
2. **PINNED CONTRACT (consumed by all):** the probe-registry schema + the "INDETERMINATE is red-eligible after N runs" rule. Distinguish *configured-host rc127* (DRIFT — should be installed, e.g. LR-2) from *no-host-configured* (quiet) so headless contexts don't cry wolf.
3. Register in `ms-enforce` so it runs on every push (non-hook trigger — must not depend on S4's hooks).
4. Red-path test: a probe stuck INDETERMINATE for N runs asserts DRIFT.

### Stream S2 — Cross-repo `(repo, file, syntax)` triage-queue registry (P2)
1. Replace `audit_backlog_stale.py`'s hardcoded `repo/"docs"/"BACKLOG.md"` + `ms-enforce:1486 --repo str(REPO)` with a registry: SLOP `docs/BACKLOG.md`, slop-process `/home/stack/v5` `docs/TODO.md`, mediastack (audit for its queue).
2. **Coverage seam:** every on-disk ring has a registry row → else DRIFT; a registered repo unreachable → INDETERMINATE (caught by S1).
3. Red-path test + the registry-completeness assertion.

### Stream S3 — Park-rule triad enforcement (P3) — sequence after S2
1. Each `[park]` requires a parseable `re-eval YYYY-MM-DD` (DRIFT if missing/past), a non-vague trigger (INCONSISTENT, lower-tier vagueness denylist), an owner token.
2. Each `[→ batch-NN]` DRIFTs if that batch already landed (cross-check MERGE-LOG).
3. **Close the dateless-skip escape hatch** (`audit_backlog_stale.py:178-180`). Red-path tests for each leg.

### Stream S4 — Session-boundary hooks + wind-down (P4) — after S1
1. Committed `.claude/settings.json` with a `SessionStart` hook (existing `check_push_status.sh`) + a `Stop` hook → new `tools/check_session_winddown.py` aggregating handoff-freshness / status-COMPLETE / MERGE-LOG / backlog-stale / push-status **+ a memory-index orphan GROUND leg** (every memory `*.md` has a `MEMORY.md` line).
2. **Honor §4f honestly:** a non-zero Stop exit re-prompts, it does NOT force a missed push/write — stamp advisory. **Register the hook-config itself as an S1 probe** ("is the Stop hook present + firing?") so it can't silently disarm (it would otherwise be the next F7).
3. Build AFTER S1 (so it's covered by the brownout detector).

### Stream S5 — Status protocol + red-on-missing-status gate + **F10** (P5 + F10)
1. Pin the **SHORT** status filename `.claude/run/status/<S-NN>.md` (must match `_extract_wave_key`); add `**State:**` marker + questions channel + terminal-CLOSED to the standard `.claude/ROBOT.md` orchestrator template, `_TEMPLATE.md`, and the launch-prompt template.
2. `_find_status_file` gains a `glob(f"{wave_key}*.md")` fallback that **WARNs on inexact match** (visible, not silently absorbed — fixes F4).
3. Merge-time **red-on-missing-status gate**: status file exists at canonical short path (filesystem GROUND → else DRIFT, not skip) AND first line is a terminal State (BLOCKED/NEEDS-INPUT blocks the merge gate).
4. Pin `ms-enforce` TIER_1 + lint baselines as **known additive-registration files** (keep-both-whole-block) in `AUTONOMOUS-DEFAULTS.md`/`_TEMPLATE.md` (BACKLOG `:163`).
5. **F10 — the two-session / Manager-handoff-artifact gap (NEW; folded in by Manager review of the audit — the audit's Track B missed it):**
   - **Doctrine** (CLAUDE.md + ROBOT.md §3.3 Manager→Manager row): a Manager handoff MUST emit **two distinct artifacts** — (A) the **Manager-handoff prompt** (launches the next *Manager* session) and (B) any **working/orchestrator launch prompt(s)** (launches a *work* session). **B back-references A.** Emitting B in place of A — collapsing the two-session model — is malformed by construction. *Why it broke before: the rule lived only as prose in MANAGER-HANDOFF.md (the rot tier), with no gate that could go red.*
   - **Red-signal** `check_manager_handoff_artifacts` (reuse S7's artifact-existence GROUND shape — PINNED dep, but implementable independently via filesystem checks): when the newest handoff artifact is a `.claude/waves/*-LAUNCH-PROMPT.md` (working prompt) with **no corresponding/updated Manager-handoff prompt artifact**, emit **DRIFT**. Filesystem existence + reference-graph = physics. Red-path test: a working prompt with no Manager-handoff prompt → DRIFT.
6. This stream edits doctrine files → four-question rationale + REVIEW-LOG entry.

### Stream S6 — Sanctioned-channel GROUND leg (P6)
1. For each registry-row tool: assert file exists + imports + calls lift/restore/audit (AST).
2. **Red-path test per tool: feed a crash mid-push, assert the deny is restored** (the rails that watch the rail-bypass tools — §4c). AST presence ≠ ordering; the red-path test is the real proof.

### Stream S7 — Walk-back-log + independent-review artifact legs (P7) — PINNED producer (artifact-existence helper)
1. `check_walkback_log`: add the GROUND leg that a doctrine-removal commit actually added a dated WALK-BACK-LOG entry (numstat add non-empty), not just a message token.
2. Build the PENDING `check_independent_review` (mechanical-floor path set; statically EXCLUDE `docs/REVIEW-LOG.md` + the gate's own def — acyclicity in code) with the **artifact-existence GROUND leg** (cited record missing → DRIFT). **HARD STOP: must NOT auto-promote to blocking until the GROUND leg lands.**
3. **PINNED:** expose the artifact-existence helper for S5's F10 gate to reuse. Ground REVIEW-LOG entries on a committed record, never `/tmp`.

### Stream S8 — Ratchet aperture + provenance + pre-commit hook (P8 + adjacents)
1. Add a catch-all `uncategorized`/shrink-only `UNCATEGORIZED` category so `classify()` never returns None for an included extension (fixes uncapped `tools/`, `backend/scripts/`, root `*.py`, `migrations/`); widen `INCLUDED_EXTENSIONS` to flag oversize `.sh`/`.yaml` (baseline current violators, real cap — not a theater catch-all).
2. `check_provenance` (BACKLOG `:53`): require "AUTO-GENERATED by …" headers on lockfiles/baselines/coverage maps. Warn-only + red-path test.
3. Local pre-commit hook for the file-size ratchet (BACKLOG `:56`).

### Stream S9 — Point coverage gaps (P9, lower-tier queue — NOT fix-all)
`_DEFAULT_STACKS` referential test; catalog-wide host-port uniqueness (intended-collision allowlist); correct the false CatalogEntry doc claim + union-over-all-manifests in field-sync test 1; reconcile the 3 data-dir path values + add a `/srv/mediastack/config` SoT constant; surface that invariant tests ride `test.yml` not `ms-enforce`.

### Stream S10 — Run-archive un-promoted-findings drain (cleanup)
Triage the 42 findings (S-47→S-74) flagged by the S-75 promotion-reconciliation check: each → promoted-already / promote-now (to BACKLOG/MERGE-LOG/MAP) / `[—]` not-worth. Dedicated-cleanup-wave discipline (not one-at-a-time, not all-failures).

## Verification
- `ms-enforce` exits 0 on each stream branch and on the merged batch branch.
- Every new gate ships a passing red-path test (proves it can go red).
- S1's brownout detector is registered in `ms-enforce` (non-hook trigger) and flags a deliberately-INDETERMINATE probe.
- F10: `check_manager_handoff_artifacts` DRIFTs on a working-prompt-without-Manager-prompt fixture.
- Doctrine-editing streams (S4/S5/S7) each have a REVIEW-LOG entry; no WALK-BACK-LOG needed (additions).
- No stream auto-promotes a gate to blocking.

## Out of scope
- Promoting any gate to blocking (later deliberate Enforcement-Lifecycle act).
- LR-1's gate logic (already fixed on main); only the merge-tool auto-stamp of `.handoff-sha` is in scope (P1, fold into S1 or S5 — see deps).
- Consensus error (doc + reality both wrong) — acknowledged unfixable by reconciliation (report §7).

## Cross-wave dependencies (EXPLICIT)
- **S1 lands FIRST on the batch branch.** S4, S5, S6, S7 rely on "INDETERMINATE is red-eligible" — shipping them before S1 manufactures future F7s.
- **S2 → S3** share `audit_backlog_stale.py`: author S2 (reshapes I/O signature) first, S3 against its result (parser legs). May be folded into one stream.
- **S5 ↔ S7** both append to `ms-enforce` TIER_1 registration — distinct non-overlapping blocks, parallel-safe under keep-both-whole-block.
- **S5 (F10 gate) consumes S7's artifact-existence helper** (PINNED) — but is implementable independently via filesystem checks if S7 lags.
- **`.handoff-sha` auto-stamp (P1):** `merge_wave_to_main.py` writes `.handoff-sha = origin/main` post-merge — assign to S1 (probe-adjacent) or S5 (handoff-protocol); Manager pins at wave-authoring.

## Robot mode (autonomous execution)
ONE Opus orchestrator (per `.claude/ROBOT.md` § "Architecture — ONE orchestrator
per batch"). Dispatch shape:
1. Startup sequence (read ROBOT.md + AUTONOMOUS-DEFAULTS + this file; High-tier
   pre-flight → `.claude/run/preflight/BATCH-11.md`; BLOCK on FALSE).
2. **Phase 1 — build S1 alone**, in its worktree; merge `wave/B11-S1-aging` to
   the batch branch `wave/batch-11` (dedicated merge worktree, ROBOT.md pattern).
3. **Phase 2 — dispatch S2,S4,S5,S6,S7,S8,S9,S10 concurrently** (Agent tool,
   isolation:worktree, model per the table), each onto its own
   `wave/B11-SN-*` branch off the S1-merged batch branch. Run **S3 after S2**.
4. Maintain `.claude/run/status/BATCH-11.md` (`**State:** RUNNING`…`CLOSED`).
   Non-blocking decisions → `.claude/run/questions/BATCH-11.md` (proceed, never
   block; no AskUserQuestion). Hard blocker → `.claude/run/blockers/BATCH-11.md`.
5. Merge each stream into `wave/batch-11` via dedicated merge worktrees; the
   post-wave merge to main is the **Manager's** job via `merge_wave_to_main.py`
   (NOT the orchestrator). Do NOT push.
