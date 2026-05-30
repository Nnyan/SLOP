# BATCH-11 — Enforcement-Lifecycle — close the "GROUND-gate brownout" class

> **Pre-fire independent review applied 2026-05-30** (fresh Opus adversarial reviewer;
> see `docs/REVIEW-LOG.md`). Verdict was NEEDS-CHANGES (R1–R3 blockers); all findings
> reconciled + folded in below. Stream count 10→**11** (F10 split into its own stream S11).

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
  main ahead of this batch** (`241be73`; the gate now reads a committed
  `.handoff-sha`, absence→DRIFT). Batch-11 only needs the *auto-stamp* half
  (merge tool writes `.handoff-sha`) → S5.
- **LR-2** (`slop-reality-probe` never installed on host) — probe installed
  out-of-band 2026-05-30; the install-dir facts now ground. A SECOND probe
  defect surfaced during that fix: called bare, the probe's port auto-detect
  returns `:22` (SSH) not SLOP's `:8080` — a GROUND probe touching the WRONG
  physics (BACKLOG; folded into S1 probe-hardening).

**Hard architectural fact (§6):** P0 (the aging engine) ⊃ the deferred
Enforcement-Lifecycle core (S-70 + S-72) — same stream, built once. Every other
stream relies on "INDETERMINATE is red-eligible" to be non-theatrical, so
**P0/S1 lands on the batch branch FIRST**.

## Rules to follow
- **Additive, not rewrite.** New gates append their own `check_` + TIER_1
  registration block in `ms-enforce`; never reformat neighbouring blocks.
- **Every new gate lands TIER_1 warn-only** and ships with a **red-path test**
  (feed a known-bad input, assert DRIFT / non-zero — proves it can go red).
  No gate auto-promotes to blocking here.
- **Honor recorded scope-reasons** (the single-entity-hardcode scanner must
  SUPPRESS justified hardcodes, e.g. `lift_push_restore.py` `SETTINGS_PATH` —
  its day-one false-positive-suppression test).
- **Shared additive files (keep-both-whole-block / region-pinned — see
  Cross-wave dependencies):** `ms-enforce` TIER_1 registration (S5, S6, S7,
  S11), `CLAUDE.md` (S9, S11), `.claude/ROBOT.md` (S5, S11),
  `tools/audit_backlog_stale.py` (S2→S3), `tools/merge_wave_to_main.py` (S5).
- **Doctrine edits trip the independent-review mechanical floor** (S5, S11 +
  the §3.6 prompt-doctrine edit touch CLAUDE.md / `.claude/ROBOT.md` /
  `AUTONOMOUS-DEFAULTS.md` or add a `def check_`): each carries the
  four-question rationale + a `docs/REVIEW-LOG.md` entry grounded on a committed
  record. Additions are strengthenings → NO WALK-BACK-LOG entry.
- File-size ratchet applies (`tools/` is currently UNCAPPED — S8 fixes the
  aperture; do not rely on the gap).

## Authorized deletions
None of substance. No history rewrites. Streams may delete only dead scaffolding
they themselves create. Existing gate logic is additive-only except: S8 widens
`check_linecount.py` aperture (additive catch-all); S5 adds a glob-fallback to
`_find_status_file` in `merge_wave_to_main.py` (additive, warn-on-inexact).

## Parallelization

**Models (per-wave default):** orchestrator = **opus**, subagents = per-stream below.

| Stream | Model | Order | Scope |
|---|---|---|---|
| **S1** aging engine / brownout detector + probe registry (P0 + S-70/S-72 core) | **opus** | **sequential — FIRST, merge to batch branch before others** | the cross-cutting probe-aging reconciler; an **open-seam** probe registry; `.probe-health-baseline.json` |
| **S2** cross-repo triage-queue registry (P2) | **opus** | parallel (author before S3) | `(repo,file,syntax)` registry generalizing `check_backlog_stale` over the 3 rings |
| **S3** park-rule triad enforcement (P3) | **sonnet** | sequential after S2 (shared file) | parseable backstop-date / trigger / owner legs in `audit_backlog_stale.py` |
| **S4** session-boundary hooks + wind-down (P4) | **opus** | parallel (after S1) | `.claude/settings.json` hooks + `check_session_winddown`; registers its hook-config as an S1 probe |
| **S5** status protocol + missing-status gate + prompt-doctrine + handoff-sha auto-stamp (P5 + adjacents) | **opus** | parallel (after S1) | ROBOT.md/_TEMPLATE status template, merge-time status gate, §3.6 prompt-doctrine, `.handoff-sha` auto-stamp, additive-files pin |
| **S6** sanctioned-channel GROUND leg + single-entity-hardcode scanner (P6 + BACKLOG:58) | **opus** | parallel | per-tool red-path "deny restored after push" test + `audit_single_entity_hardcode.py` |
| **S7** walkback + independent-review artifact legs (P7) | **opus** | parallel | `check_walkback_log` GROUND leg + PENDING `check_independent_review` + artifact-existence helper |
| **S8** ratchet aperture + provenance + pre-commit hook (P8 + adjacents) | **sonnet** | parallel | catch-all ratchet category, `.sh`/`.yaml` aperture, `check_provenance`, local ratchet pre-commit hook |
| **S9** point coverage gaps (P9) | **sonnet** | parallel | `_DEFAULT_STACKS` ref test, catalog port-uniqueness, CatalogEntry doc-fix + union field-sync, 3 data-dir SoT |
| **S10** run-archive un-promoted-findings drain (cleanup) | **sonnet** | parallel | triage the 42 un-promoted findings: promoted-already / promote-now / `[—]` |
| **S11** F10 — two-session / Manager-handoff-artifact contract + doctrine + gate | **opus** | parallel (after S1) | canonicalize the Manager-handoff-prompt artifact, then doctrine + `check_manager_handoff_artifacts` |

**Per-stream Model justification (rubric, ROBOT.md § "Per-stream Model column"):**
- S1 = opus — load-bearing cross-cutting design (the engine + registry every other stream depends on); highest plausible-but-wrong risk.
- S2 = opus — interface generalization over a plural set; reshapes a file's I/O signature.
- S3 = sonnet — bounded parser-leg additions against S2's settled signature.
- S4 = opus — new harness-integration surface (`settings.json` hooks) + the §4f "hook isn't the boundary it's sold as" subtlety.
- S5 = opus — status-template across multiple files + a new merge-time gate + merge-tool edit; irreducible judgment, de-bottlenecked by moving F10 to S11.
- S6 = opus — security-adjacent (rails watching the rail-bypass tools) + the hardcode scanner's recorded-reason exemption; red-path correctness is subtle.
- S7 = opus — acyclicity + artifact-existence reasoning; must not self-trigger.
- S8 = sonnet — mechanical aperture widening + header gate against clear specs.
- S9 = sonnet — bounded, well-specified point tests/fixes.
- S10 = sonnet — mechanical triage against durable docs (XREF).
- S11 = opus — the F10 artifact-contract + doctrine + gate is irreducible-judgment (must define a NEW on-disk contract the gate can ground-truth, then prove it goes red).

## Complexity & Pre-flight
**Tier: High** (11 streams, cross-stream contracts, doctrine edits, a hard P0
sequence, shared doctrine files). Run High-tier pre-flight (validate-wave-file +
fact-check subagent + processor-contract-pinned + cross-wave disjointness +
edited-wave consistency). **BLOCK dispatch on any FALSE.** Verdict →
`.claude/run/preflight/BATCH-11.md`.

## Deliverables per stream
> Full rationale + each item's own failure-mode + red-signal: report §5 (P0–P9).
> Each stream commits to its own `wave/B11-SN-*` branch.

### Stream S1 — Aging engine / brownout detector + probe registry (P0 + S-70/S-72 core) — PINNED producer
1. `tools/audit_probe_aging.py` + `.probe-health-baseline.json` (shrink-only ratchet, sibling to `.factprobe-baseline.json`): for every registered probe, record per run whether it reached ground (`verified`/`DRIFT`) or browned out (`INDETERMINATE`/unparseable/missing-input/no-date); flag any probe with **no ground-touch in N runs** → DRIFT.
2. **PINNED CONTRACT (consumed by all):** (a) the probe-registry schema; (b) the rule "INDETERMINATE is red-eligible after N runs"; (c) **the registry is an OPEN SEAM** — other streams append a row for their own probe via a documented append mechanism, WITHOUT editing S1's logic (R9: S4's hook-config probe + S2's per-ring probes register this way). Distinguish *configured-host rc127* (DRIFT — should be installed, e.g. LR-2) from *no-host-configured* (quiet).
3. **Initial registry MUST enumerate** the known brownout-prone probes named in report §4g: `check_handoff_freshness` (F7), `audit_doc_reality` (S-75 / LR-2), `audit_status_file_freshness:200`, `audit_backlog_stale` dateless (`:21`) — plus a written **schema doc** the Phase-2 streams read before registering (R4).
4. **Probe-touches-WRONG-physics hardening (BACKLOG, from LR-2 fix):** `slop-reality-probe` bare-call returns `bound_port:22` (SSH) not SLOP's `:8080` — the port auto-detect grabs the lowest LISTEN socket. Fix the probe to derive the SLOP service port (from config/service), and treat "probe emitted a value but it's the wrong target" as a registry-trackable defect class, not a pass.
5. Register `audit_probe_aging.py` in `ms-enforce` (non-hook trigger — must not depend on S4). Red-path test: a probe stuck INDETERMINATE for N runs asserts DRIFT.

### Stream S2 — Cross-repo `(repo, file, syntax)` triage-queue registry (P2)
1. Replace `audit_backlog_stale.py`'s hardcoded `repo/"docs"/"BACKLOG.md"` + `ms-enforce:1486 --repo str(REPO)` with a registry: SLOP `docs/BACKLOG.md`; slop-process `/home/stack/v5` `docs/TODO.md`; mediastack `/home/stack/code/mediastack` — **resolve its actual queue file before shipping** (R7); if none found, land the row as INDETERMINATE with a BACKLOG follow-up, NOT a silent TODO-hole.
2. **Semantics (state explicitly):** present-ring-with-no-row → DRIFT (the seam); registered-but-absent/unreachable ring → INDETERMINATE (caught by S1). Register each ring's reachability as an S1-registry probe (open-seam append).
3. Coverage assertion: every on-disk ring has a registry row. Red-path test.

### Stream S3 — Park-rule triad enforcement (P3) — sequence after S2
1. Each `[park]` requires a parseable `re-eval YYYY-MM-DD` (DRIFT if missing/past), a non-vague trigger (INCONSISTENT, lower-tier vagueness denylist), an owner token.
2. Each `[→ batch-NN]` DRIFTs if that batch already landed (cross-check MERGE-LOG).
3. **Close the dateless-skip escape hatch** (`audit_backlog_stale.py:178-180`). Red-path tests per leg. Also covers BACKLOG `:164` deferred-trigger monitor.

### Stream S4 — Session-boundary hooks + wind-down (P4) — after S1
1. Committed `.claude/settings.json` with a `SessionStart` hook (existing `check_push_status.sh`) + a `Stop` hook → new `tools/check_session_winddown.py` aggregating handoff-freshness / status-COMPLETE / MERGE-LOG / backlog-stale / push-status **+ a memory-index orphan GROUND leg** (every memory `*.md` has a `MEMORY.md` line).
2. **Honor §4f honestly:** a non-zero Stop exit re-prompts, it does NOT force a missed push/write — stamp advisory. **Register the hook-config as an S1-registry probe** ("is the Stop hook present + firing?") via the open-seam append (R9) so it can't silently disarm (else it's the next F7).

### Stream S5 — Status protocol + missing-status gate + prompt-doctrine + handoff-sha auto-stamp (P5 + adjacents)
1. Pin the **SHORT** status filename `.claude/run/status/<S-NN>.md`; add `**State:**` marker + questions channel + terminal-CLOSED to the standard `.claude/ROBOT.md` orchestrator template, `_TEMPLATE.md`, and the launch-prompt template.
2. `_find_status_file` gains a `glob(f"{wave_key}*.md")` fallback that **WARNs on inexact match** (fixes F4).
3. Merge-time **red-on-missing-status gate**: status file exists at canonical short path (filesystem GROUND → else DRIFT, not skip) AND first line is a terminal State (BLOCKED/NEEDS-INPUT blocks the merge gate).
4. **§3.6 prompt-doctrine edit (R2 — was unowned):** formalize memory `feedback-prompt-and-menu-formatting` into a `.claude/ROBOT.md` §3.6 section (report §3.6). Honestly advisory (no physics red-signal — formatting is taste).
5. **`.handoff-sha` auto-stamp (R6 — pinned here, it's a `merge_wave_to_main.py` edit = S5's file):** the sanctioned merge tool writes `.handoff-sha = origin/main` post-merge so the manual handoff-refresh step is owned. Address the inherent 1-commit self-reference lag (make the gate tolerant or document it).
6. Pin `ms-enforce` TIER_1 + lint baselines as known additive-registration files in `AUTONOMOUS-DEFAULTS.md`/`_TEMPLATE.md` (BACKLOG `:166`).
7. This stream edits doctrine files → four-question rationale + REVIEW-LOG entry.

### Stream S6 — Sanctioned-channel GROUND leg + single-entity-hardcode scanner (P6 + BACKLOG:58)
1. For each sanctioned registry-row tool: assert file exists + imports + calls lift/restore/audit (AST). **Red-path test per tool: feed a crash mid-push, assert the deny is restored** (§4c).
2. **`tools/audit_single_entity_hardcode.py` (R10 — was dropped):** GROUND red-signal for the Reuse-and-blast-radius checkpoint — greps `tools/` + `tools/sanctioned/` for a SLOP-only literal in a tool exposing no `--repo`/registry param; verified/DRIFT/INDETERMINATE. **MUST honor recorded scope-reasons** (suppress `lift_push_restore.py` `SETTINGS_PATH` — day-one false-positive-suppression test). Red-path test.

### Stream S7 — Walk-back-log + independent-review artifact legs (P7) — PINNED producer (artifact-existence helper)
1. `check_walkback_log`: add the GROUND leg that a doctrine-removal commit actually added a dated WALK-BACK-LOG entry (numstat add non-empty), not just a message token.
2. Build the PENDING `check_independent_review` (mechanical-floor path set; statically EXCLUDE `docs/REVIEW-LOG.md` + the gate's own def — acyclicity in code) with the **artifact-existence GROUND leg** (cited record missing → DRIFT). **HARD STOP: no auto-promotion to blocking until the GROUND leg lands.**
3. **PINNED:** expose the artifact-existence helper for S11's F10 gate to reuse. Ground REVIEW-LOG entries on a committed record, never `/tmp`.

### Stream S8 — Ratchet aperture + provenance + pre-commit hook (P8 + adjacents)
1. Add a catch-all `uncategorized`/shrink-only `UNCATEGORIZED` category so `classify()` never returns None for an included extension (fixes uncapped `tools/`, `backend/scripts/`, root `*.py`, `migrations/`); widen `INCLUDED_EXTENSIONS` to flag oversize `.sh`/`.yaml` (baseline current violators, real cap).
2. `check_provenance` (BACKLOG `:53`): require "AUTO-GENERATED by …" headers on lockfiles/baselines/coverage maps. Warn-only + red-path test.
3. Local pre-commit hook for the file-size ratchet (BACKLOG `:56`).

### Stream S9 — Point coverage gaps (P9, lower-tier queue — NOT fix-all)
`_DEFAULT_STACKS` referential test; catalog-wide host-port uniqueness (intended-collision allowlist); correct the false CatalogEntry doc claim (`CLAUDE.md:303-304`) + union-over-all-manifests in field-sync test 1; reconcile the 3 data-dir path values + add a `/srv/mediastack/config` SoT constant (near `CLAUDE.md:288`); surface that invariant tests ride `test.yml` not `ms-enforce`. **Owns the `CLAUDE.md` CatalogEntry + data-dir regions** (R1 region-pin).

### Stream S10 — Run-archive un-promoted-findings drain (cleanup)
Triage the 42 findings (S-47→S-74) flagged by the S-75 promotion-reconciliation check: each → promoted-already / promote-now / `[—]`. Dedicated-cleanup-wave discipline.

### Stream S11 — F10: two-session / Manager-handoff-artifact contract + doctrine + gate (split out per R8)
1. **PRECONDITION (R3 — the gate cannot go red without this):** canonicalize a **Manager-handoff-prompt artifact** — a pinned on-disk filename (e.g. `.claude/waves/<BATCH>-MANAGER-HANDOFF-PROMPT.md`) AND a required **back-reference token** the working `*-LAUNCH-PROMPT.md` must carry pointing at its Manager-handoff prompt. Without a defined artifact, the gate is XREF / false-positive theater.
2. **Doctrine:** add to CLAUDE.md + `.claude/ROBOT.md` §3.3 Manager→Manager row — a Manager handoff MUST emit BOTH artifact A (the Manager-handoff prompt, canonical filename) and artifact B (any working launch prompt), B back-referencing A; emitting B in place of A is malformed by construction. **Owns the `CLAUDE.md` two-session region + the `ROBOT.md` §3.3 region** (R1 region-pin, disjoint from S5's §3.5/§3.6 and S9's regions).
3. **Gate `check_manager_handoff_artifacts`** (reuse S7's artifact-existence helper — PINNED dep): GROUND on the filesystem — newest handoff is a working `*-LAUNCH-PROMPT.md` whose required back-reference token resolves to NO existing Manager-handoff-prompt file → DRIFT. Red-path test: a working prompt with a dangling/absent back-reference → DRIFT; a legitimately paired A+B → verified. The back-reference token is the discriminator that prevents false-positives on a deliberately-combined handoff.

## Verification
- `ms-enforce` exits 0 on each stream branch and on the merged batch branch.
- Every new gate ships a passing red-path test (proves it can go red).
- S1's brownout detector is registered in `ms-enforce` (non-hook trigger) and flags a deliberately-INDETERMINATE probe; the registry enumerates the §4g probes and is an open seam (S2/S4 append successfully).
- S11: `check_manager_handoff_artifacts` DRIFTs on a working-prompt-with-dangling-back-reference fixture and verifies on a paired A+B fixture.
- Doctrine-editing streams (S5, S11) each have a REVIEW-LOG entry; no WALK-BACK-LOG (additions).
- No stream auto-promotes a gate to blocking.

## Out of scope
- Promoting any gate to blocking (later deliberate act).
- LR-1's gate logic (already fixed on main); only the merge-tool auto-stamp is in scope (S5).
- Consensus error (doc + reality both wrong) — acknowledged unfixable by reconciliation (report §7).
- A full Rocinante host redeploy (host is behind origin/main; operator-owned, tracked separately).

## Cross-wave dependencies (EXPLICIT — reviewer-hardened)
- **S1 lands FIRST on the batch branch.** S2, S4, S5, S6, S7, S11 rely on "INDETERMINATE is red-eligible"; shipping them before S1 manufactures future F7s.
- **S1's registry is an OPEN SEAM** (R9): S2 (per-ring reachability), S4 (hook-config) append rows via S1's documented append mechanism — NOT by editing S1's logic. S1 must ship that seam + schema doc before Phase 2 integrates.
- **Shared additive files (keep-both-whole-block; region-pinned where noted):**
  - `ms-enforce` TIER_1 registration — S5, S6, S7, S11 (each appends its own block).
  - **`CLAUDE.md` (R1 — was undeclared):** S9 owns the CatalogEntry/data-dir regions; S11 owns the two-session region. Disjoint regions, keep-both.
  - **`.claude/ROBOT.md` (R1):** S5 owns §3.5 status-template + §3.6 prompt-doctrine; S11 owns the §3.3 Manager→Manager row. Disjoint, keep-both.
  - `tools/audit_backlog_stale.py` — **S2 → S3 sequenced** (S2 reshapes the I/O signature, S3 adds parser legs).
  - `tools/merge_wave_to_main.py` — S5 only (status gate + `.handoff-sha` auto-stamp).
- **S11 (F10 gate) consumes S7's artifact-existence helper** (PINNED) — implementable independently via filesystem checks if S7 lags, but the PRECONDITION artifact (S11 #1) must exist first.
- **Merge-worktree base (R5):** the batch branch `wave/batch-11` is created at S1-merge time. ALL Phase-2 stream merges use a merge worktree detached from **`wave/batch-11`** (NOT `origin/main` — ROBOT.md's canonical example hardcodes origin/main, which would silently drop S1).

## Robot mode (autonomous execution)
ONE Opus orchestrator (`.claude/ROBOT.md` § "Architecture — ONE orchestrator per batch").
1. Startup sequence (read ROBOT.md + AUTONOMOUS-DEFAULTS + this file; High-tier pre-flight → `.claude/run/preflight/BATCH-11.md`; BLOCK on FALSE).
2. **Phase 1 — build S1 alone** in its worktree; merge `wave/B11-S1-aging` to a NEW batch branch `wave/batch-11` (dedicated merge worktree detached from origin/main, ONE TIME to create the batch branch).
3. **Phase 2 — dispatch S2,S4,S5,S6,S7,S8,S9,S10,S11 concurrently** (Agent tool, isolation:worktree, model per the table), each branched off the S1-merged `wave/batch-11`. Run **S3 after S2**. Inject the subagent preamble.
4. Maintain `.claude/run/status/BATCH-11.md` (`**State:** RUNNING`…`CLOSED`). Non-blocking decisions → `.claude/run/questions/BATCH-11.md` (proceed, never block; no AskUserQuestion). Hard blocker → `.claude/run/blockers/BATCH-11.md`.
5. Merge each stream into `wave/batch-11` via merge worktrees **detached from `wave/batch-11`** (R5); keep-both on the shared additive files above. The post-wave merge to main is the **Manager's** job via `merge_wave_to_main.py` (NOT the orchestrator). Do NOT push.
