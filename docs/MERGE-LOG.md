# Wave Merge Log

Audit trail for every wave-branch merge to `main`. Each entry records what was
merged, when, by whom (operator vs sanctioned tool), and the resulting state.

**Why this log exists:** the `git checkout main` / `git switch main` deny rules
in `.claude/settings.local.json` protect against runaway agents merging
unverified work to main during a wave. But post-wave merges are legitimate.
They are recorded here regardless of whether they were done via operator
handoff or the sanctioned tool.

**Sanctioned merge tool** (shipped S-59 Stream D): `tools/merge_wave_to_main.py`
(note: underscores in the filename). Invoke as:

```
python3 tools/merge_wave_to_main.py wave/S-NN-topic [wave/S-MM-topic ...]
```

The tool runs pre-flight checks, does internal lift-restore of the checkout-main
deny rules (try/finally), merges `--no-ff`, aborts on any conflict, and appends
an audit entry here automatically. The Method field will read
`tools/merge_wave_to_main.py` for tool-driven merges vs `operator-manual` for
manual merges.

**Entry format:**

```markdown
## YYYY-MM-DD — <one-line summary>

- **Method:** operator-manual | tools/merge_wave_to_main.py
- **Operator/Caller:** <user name | agent session id>
- **Pre-merge main HEAD:** <SHA>
- **Branches merged (in order):**
  1. `<branch>` → merge commit `<SHA>`
  2. `<branch>` → merge commit `<SHA>`
  ...
- **Post-merge main HEAD:** <SHA>
- **Pushed to origin:** yes/no (origin SHA after push)
- **Pre-flight checks run:** ms-enforce (PASS/FAIL/skipped), test suite (count), wave status verification
- **Notes:** anything unusual — conflicts resolved, regressions caught, manual interventions
```

**Convention:** newest entries at the TOP. Prune entries older than 12 months
to `docs/MERGE-LOG-archive/<year>.md`; the git history is the long-term record.

**Review:** the operator-assist Claude session reviews entries on each batch
landing — flags anything anomalous (unexpected branches, missing pre-flight
checks, unverified merges).

---

## 2026-05-30 — wave/S-75-knowledge-lifecycle

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack
- **Pre-merge main HEAD:** `4d09f1c2e82aeeb734c27f69227e6277e6efc32f`
- **Branches merged (in order):**
  1. `wave/S-75-knowledge-lifecycle` → merge commit `9983ceba0c9174c9b0c46d9d90b7eab4e703f5e5`
- **Post-merge main HEAD:** `9983ceba0c9174c9b0c46d9d90b7eab4e703f5e5`
- **Pushed to origin:** yes — pushed in the batch-10 sweep (merge commit `9983ceb` on origin/main)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:wave/S-75-knowledge-lifecycle: OK
  - status:wave/S-75-knowledge-lifecycle: COMPLETE (**Manager-reconstructed** — see Notes)
  - diff:wave/S-75-knowledge-lifecycle: OK (18 diff-stat lines)
  - ms-enforce:wave/S-75-knowledge-lifecycle: EXIT 0 (All Core Rules satisfied)
- **Notes:** Manager review/merge of batch-10 (S-75-KNOWLEDGE-LIFECYCLE). All 5 streams merged on
  the wave branch (A→E→B→C→D; E-before-D for the CLAUDE.md ownership split), 3 keep-both whole-block
  merge decisions (no union-interleave; S-69 lesson honored). The orchestrator wrote a complete,
  high-quality closing status **under the full-wave filename `S-75-KNOWLEDGE-LIFECYCLE.md` instead of
  the conventional short `S-75.md`** — so the Manager's initial `S-75.md` lookup found nothing
  (handoff gap: the status filename is not pinned in the convention → evidence for the
  handoff-integrity audit's status-protocol standardization). The Manager re-verified acceptance
  independently before merging and it matched the orchestrator's report exactly: ms-enforce EXIT 0;
  the 3 new TIER_1 warn-only gates (`check_doc_reality`/`check_handoff_freshness`/
  `check_fact_freshness`) registered + green, with doc-reality emitting `3 INDETERMINATE` (loud, not
  OK) when no `--host` ground truth is present; file-size ratchet holds (`agent.py` 257/500); 66 new
  unit tests pass; orchestrator-supplied proof-of-red confirmed per gate. **NEW:** the merge tool now runs Stream C's
  promotion-reconciliation check, which emitted **42 warn-only "un-promoted finding" warnings** for
  historical run-archive decisions/observations never reconciled into BACKLOG/MERGE-LOG/WALK-BACK-LOG/
  MAP (warn-only; did not block) — logged to BACKLOG. The missing-status-protocol gap is evidence for
  the handoff-integrity audit. v5 SessionStart-hook one-liner is uncommitted (operator-owned). Final
  main HEAD `9983ceb`.


## 2026-05-30 — wave/S-74-deploy-hardening

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack
- **Pre-merge main HEAD:** `a3cbce4cb783de8c91ac253b83de4a7b80068464`
- **Branches merged (in order):**
  1. `wave/S-74-deploy-hardening` → merge commit `f1857691fee366dfbd23b03ab0f34e5b034d83a6`
- **Post-merge main HEAD:** `f1857691fee366dfbd23b03ab0f34e5b034d83a6`
- **Pushed to origin:** yes — `origin/main` at `f1857691fee366dfbd23b03ab0f34e5b034d83a6` (via `/tmp/lift-push-restore.py all`)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:wave/S-74-deploy-hardening: OK
  - status:wave/S-74-deploy-hardening: COMPLETE
  - diff:wave/S-74-deploy-hardening: OK (13 diff-stat lines)
  - ms-enforce:wave/S-74-deploy-hardening: EXIT 0 (All Core Rules satisfied)
  - post-merge tests: `tests/test_deploy_hardening.py` + `tests/test_operator_env_dotenv.py` = 22 passed (16+6)
- **Notes:** Manager review/merge of batch-9. Wave built off `e3a0eef`; main had advanced 2 doc
  commits to `a3cbce4` (handoff refresh + gitignore) — those touch only `.gitignore` +
  `MANAGER-HANDOFF.md`, zero overlap with the wave's files, so merge-tree was conflict-free.
  Confirmed (not re-derived) the PINNED contracts on the wave tree before merge: `deploy_lib.sh`
  defines exactly `detect_service_user`/`build_home`/`normalize_ownership` (both scripts source it,
  no inline dup); no `2>/dev/null` on fetch; no bare `git pull origin main`; `MS_PORT` canonical in
  both scripts; `backend/core/config.py` loads `.env` with `override=False` (real env / systemd
  `Environment=` wins). Final main HEAD `f1857691fee366dfbd23b03ab0f34e5b034d83a6`.


## 2026-05-30 — docs/wave-draft-knowledge-lifecycle

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack
- **Pre-merge main HEAD:** `3ec8b5246cc6d77572e7d57d4ea24e5f90d0e82c`
- **Branches merged (in order):**
  1. `docs/wave-draft-knowledge-lifecycle` → merge commit `fe3d32e12f327409385094931dea252e1ccce926`
- **Post-merge main HEAD:** `fe3d32e12f327409385094931dea252e1ccce926`
- **Pushed to origin:** yes — `fe3d32e` (pushed via lift-push-restore by Manager session post-merge)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:docs/wave-draft-knowledge-lifecycle: OK
  - status:docs/wave-draft-knowledge-lifecycle: no status file (skipped — draft branch)
  - diff:docs/wave-draft-knowledge-lifecycle: OK (6 diff-stat lines)
  - ms-enforce:docs/wave-draft-knowledge-lifecycle: PASS (branch-isolated)
- **Notes:** batch-10 wave-file draft. `S-75-KNOWLEDGE-LIFECYCLE.md` + `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md` + launch prompt, produced by a fresh Opus Auditor-Manager (5-lens read-only fan-out: reality-drift/transition-seam/temporal-decay/unmeasured-dimension/detection-ownership + phase-2 blind-spot critic). Dogfooded green (wave_complexity=High score 36, validate-wave-file OK, preflight=DISPATCH-OK). Manager review confirmed: two-owner firewall holds (SLOP AI Agent emits a runtime-only RealityView; a SEPARATE dev-time reconciler `check_doc_reality` owns docs); the keystone GROUND-vs-XREF discipline pinned (only physics-touching probes may say "verified"; unreachable⇒INDETERMINATE; probes-age = 4th aging leg); host probe rides operator ambient SSH (no stored secret); all new gates warn-only. HARD-sequences after S-74 (batch-9→batch-10); launch prompt gates on S-74 being on main. Draft branch deleted post-merge.


## 2026-05-30 — docs/wave-draft-deploy-hardening

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack
- **Pre-merge main HEAD:** `6ab2f5c23a43595c01db04a02875631679eb3dd7`
- **Branches merged (in order):**
  1. `docs/wave-draft-deploy-hardening` → merge commit `b19958d1d09fe171f1c43a44a7d4850f9e6fd6d2`
- **Post-merge main HEAD:** `b19958d1d09fe171f1c43a44a7d4850f9e6fd6d2` (+ rider amend `6a1a315`, log `3ec8b52`; both pushed in `fe3d32e`)
- **Pushed to origin:** yes — in `fe3d32e` (Manager session, post-merge)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:docs/wave-draft-deploy-hardening: OK
  - status:docs/wave-draft-deploy-hardening: no status file (skipped — draft branch)
  - diff:docs/wave-draft-deploy-hardening: OK (3 diff-stat lines)
  - ms-enforce:docs/wave-draft-deploy-hardening: PASS (branch-isolated)
- **Notes:** batch-9 wave-file draft. `S-74-DEPLOY-HARDENING.md` (4 streams: A opus ms-update rewrite + shared `deploy_lib.sh` / B sonnet deploy.sh align / C opus config-mechanism decision / D sonnet docs+runbook) authored by a fresh session from the Rocinante forensics. Manager review: covers audit riders 2 (surface fetch errors) + 3 (`.env`-vs-systemd config decision, Stream C); **added rider 1 (post-update SHA-verify, fail-loud) to Stream A** (`6a1a315`) — still dogfoods High + validate OK. Draft branch deleted post-merge.


## 2026-05-29 — wave/S-71-test-data-hygiene

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack
- **Pre-merge main HEAD:** `55aded1d935b9c60aac9473f9d67c1fb43a34ae5`
- **Branches merged (in order):**
  1. `wave/S-71-test-data-hygiene` → merge commit `96fd6a2b611d4dfbed0134d71f334945cbb290df`
- **Post-merge main HEAD:** `96fd6a2b611d4dfbed0134d71f334945cbb290df`
- **Pushed to origin:** yes — `96fd6a2` (pushed via lift-push-restore by Manager session post-merge, 2026-05-29)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:wave/S-71-test-data-hygiene: OK
  - status:wave/S-71-test-data-hygiene: COMPLETE
  - diff:wave/S-71-test-data-hygiene: OK (13 diff-stat lines)
  - ms-enforce:wave/S-71-test-data-hygiene: PASS (branch-isolated; separator line is the known cosmetic logging wart)
- **Notes:** batch-8. S-71-TEST-DATA-HYGIENE — 4 streams (A sonnet ADR-0019 / B sonnet SLOP_AUDIT_LOG_PATH redirect / C opus check_test_isolation gate / D sonnet narrow autouse + sweep + test rename), all file-disjoint → zero conflicts, no decisions, no blockers. Manager review confirmed: merge-tree dry-run conflict-free; the 3 pinned contracts all hold in merged code (policy-doc path `docs/adr/0019-test-data-isolation.md` ↔ gate name `check_test_isolation` bidirectional; `SLOP_AUDIT_LOG_PATH` redirect only fires on default-path+env, production unchanged); `check_test_isolation` registered warn-only (ms-enforce:1704), exit 0; `_isolate_config_data_dir` narrowed autouse→opt-in; `test_preflight_harness.py`→`test_preflight_wave.py`. Full suite: 9 failures, all pre-existing on main (zero unique to wave). Stream worktrees already pruned by orchestrator; wave branch deleted post-merge.


## 2026-05-29 — docs/wave-draft-batch8 (S-71-TEST-DATA-HYGIENE wave draft)

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack (operator-assist / Manager session)
- **Pre-merge main HEAD:** `38b4d25b29b2b1ccb181edb772289402357cdcd7`
- **Branches merged (in order):**
  1. `docs/wave-draft-batch8` → merge commit `a0d70397bb69fae2cca6609d120cd232f5b8325f`
- **Post-merge main HEAD:** `a0d70397bb69fae2cca6609d120cd232f5b8325f`
- **Pushed to origin:** yes — `a0d7039` (pushed via lift-push-restore by Manager session post-merge, 2026-05-29)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:docs/wave-draft-batch8: OK
  - status:docs/wave-draft-batch8: no status file (skipped — draft branch)
  - diff:docs/wave-draft-batch8: OK (5 diff-stat lines)
  - ms-enforce:docs/wave-draft-batch8: PASS (branch-isolated; separator line is the known cosmetic logging wart)
- **Notes:** batch-8 wave file `.claude/waves/S-71-TEST-DATA-HYGIENE.md` — the FIRST wave authored on batch-7's `_TEMPLATE.md` + per-stream Model column. Drafted + dogfooded by the Manager session at the operator's direction (not a separate fresh drafting session this time): `wave_complexity.py`=High (score 26), `validate-wave-file.py`=OK, `preflight_wave.py`=DISPATCH-OK. Now on main, ready for the batch-8 orchestrator to execute. Draft branch deleted post-merge.


## 2026-05-29 — wave/S-73-wave-authoring-rigor

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack
- **Pre-merge main HEAD:** `02769fe57c30b62947c3e4a4ef6e6322ff4fb057`
- **Branches merged (in order):**
  1. `wave/S-73-wave-authoring-rigor` → merge commit `ff27adb4d19f792859e940edafcf746940268dc6`
- **Post-merge main HEAD:** `ff27adb4d19f792859e940edafcf746940268dc6`
- **Pushed to origin:** yes — `ff27adb` (pushed via lift-push-restore by Manager session post-merge, 2026-05-29)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:wave/S-73-wave-authoring-rigor: OK
  - status:wave/S-73-wave-authoring-rigor: COMPLETE
  - diff:wave/S-73-wave-authoring-rigor: OK (11 diff-stat lines)
  - ms-enforce:wave/S-73-wave-authoring-rigor: PASS (branch-isolated; pre-flight [5/5] reported OK — the captured separator line is the known cosmetic logging wart)
- **Notes:** batch-7. S-73-WAVE-AUTHORING-RIGOR — 5 streams (A opus / B opus / C sonnet / D haiku / E sonnet), all merged into the wave branch by the orchestrator. Manager review confirmed: merge-tree dry-run conflict-free vs current main (wave change-set disjoint from the in-run external docs push `02769fe`); MERGE-1 keep-both ROBOT.md subsections in correct order, no `merge=union`, no leftover markers; MERGE-2 doctrine references `preflight_wave.py` (no stale `preflight_harness.py`); MERGE-3 fixture verified. Stray untracked `_TEMPLATE.md` + old `.bak` removed pre-merge; 5 stream worktrees + wave/stream branches pruned post-merge. Open cosmetic follow-up: test file `tests/test_preflight_harness.py` still tests `tools/preflight_wave.py` (rename in batch-8 sweep).


## 2026-05-29 — docs/wave-draft-s73

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack
- **Pre-merge main HEAD:** `cb58f70ccc073fe829dc28b3c9249aa3fe597803`
- **Branches merged (in order):**
  1. `docs/wave-draft-s73` → merge commit `86cd5a19ffc44087a13d3d3427364edff68efd51`
- **Post-merge main HEAD:** `86cd5a19ffc44087a13d3d3427364edff68efd51`
- **Pushed to origin:** no (push is operator-only)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists:docs/wave-draft-s73: OK
  - status:docs/wave-draft-s73: no status file (skipped)
  - diff:docs/wave-draft-s73: OK (2 diff-stat lines)
  - ms-enforce:docs/wave-draft-s73: ────────────────────────────────────────────────────────────
- **Notes:** S-73-WAVE-AUTHORING-RIGOR wave draft (per `docs/POST-BATCH6-WAVE-MAP.md` Wave 1; drafted by a fresh session, reviewed by Manager). **First merge on the FIXED tool** — this entry is auto-generated *and* correctly flush-left (dedent bug fixed `cea63cb`), and pre-flight [5/5] actually RAN ms-enforce branch-isolated on the draft branch instead of skipping (from-main bug fixed). (Minor cosmetic: the ms-enforce pre-flight summary captured a separator line as its first-line summary — harmless.) Branch deleted post-merge.


## 2026-05-29 — batch-6: S-66 + S-67 + S-68 + S-69 (via integration branch)

- **Method:** tools/merge_wave_to_main.py (merged a pre-integrated `integration/batch6` branch — see merge strategy below)
- **Operator/Caller:** stack (operator-assist / Manager session)
- **Pre-merge main HEAD:** `c57d0ab`
- **Merge strategy:** the four wave branches had **known additive conflicts** (ms-enforce TIER_1 list across S-67/S-68/S-69; ROBOT.md/MAP.md across S-68/S-69). Since the sanctioned tool aborts on conflict by design, all four were merged + conflict-resolved off-`main` in a dedicated **merge worktree** (`.claude/worktrees/merge-batch6`, branch `integration/batch6`) — the S-69 merge-worktree doctrine pattern — then the verified integration branch was merged to `main` in one clean `--no-ff` (no conflicts; `main` was an ancestor).
- **Branches folded in (in integration order):**
  1. `wave/S-66-post-s58-unmask-cleanup` (`d0494fd`) → clean
  2. `wave/S-67-doc-and-tooling-hygiene` (`09ac124`) → clean
  3. `wave/S-68-sanctioned-channel-toolkit` (`df7df64`) → ms-enforce + MAP.md additive conflicts, resolved keep-both
  4. `wave/S-69-doctrine-mechanical-enforcement` (`88f877c`) → ms-enforce additive conflict; **reconstructed deterministically via difflib** (NOT marker-strip — functions were split by shared boilerplate, the union-interleave trap). All 9 gates + 9 TIER_1 registrations present exactly once.
- **Integration → main merge commit:** `ebaf67c`
- **Post-merge main HEAD:** `ebaf67c` (audit-log + follow-up commits land on top)
- **Pushed to origin:** YES (push follows this audit-log commit)
- **Pre-flight / verification:**
  - Per-wave: orchestrator verified each in its worktree (S-66 67→17 residual; S-67 links 113→9; S-68 124 pass; S-69 130 pass).
  - Integration: ms-enforce executed all 9 new gates without crash; full suite 11 failed / 2900 passed — the 11 are a strict subset of the known-17 residuals (Docker/env, git-history, gitignored-artifact, pre-existing); zero new failures.
  - **On main (real tree): ms-enforce → All Core Rules satisfied; live settings.local.json stayed clean (no pollution).**
- **Operator merge-time fix:** committed `77fb678` on the integration branch — access-request allow/deny adapters now honor `target_paths["settings_local"]` (a `[deny] Bash(rm -rf *)` processor-test fixture was writing the real settings file via the default path, tripping S-68's new real-settings guard tests; this was the `/doctor` rm-rf-star gremlin's root cause). Analogous to the S-59 A↔B adapter fix at batch-5.
- **Notes:** Stray untracked files (`docs/SANCTIONED-OPS-LOG.md`, `tools/audit_orchestrator_prompt_format.py`) the orchestrator had moved to `.claude/run/stray-maintree-files/` are now canonical on main via the merge; the moved copies are deleted in cleanup. MERGE-LOG dedent-indentation bug (S-68-C follow-up) hit again on the tool's auto-entry — hand-corrected here.


## 2026-05-29 — docs/wave-drafts-s68-s69-doctrine (FIRST sanctioned-tool merge)

- **Method:** tools/merge_wave_to_main.py
- **Operator/Caller:** stack (operator-assist / Manager session)
- **Pre-merge main HEAD:** `37d96d4fe3fe2efc68ba51744c7a2237705772b9`
- **Branches merged (in order):**
  1. `docs/wave-drafts-s68-s69-doctrine` → merge commit `ab716cd79cdecb9bbea33641c64f81608b9b39b6`
- **Post-merge main HEAD:** `ab716cd79cdecb9bbea33641c64f81608b9b39b6`
- **Pushed to origin:** YES (push step follows this audit-log commit)
- **Pre-flight checks run:**
  - working-tree: CLEAN
  - branch-exists: OK
  - status: no status file (skipped — drafts branch, not a `wave/S-NN` branch)
  - diff: OK (5 diff-stat lines)
  - ms-enforce: skipped (tool was invoked from `main`, not the branch — see note)
- **Contents merged:** S-68 + S-69 wave drafts, processor-pattern A↔B contract doctrine (AUTONOMOUS-DEFAULTS), batch-5 retro BACKLOG close-outs. Plus a redundant duplicate MANAGER-HANDOFF.md commit (`13cf95a`, byte-identical to main's `37d96d4` — merged cleanly, no conflict).
- **Notes:** First real use of the sanctioned merge channel (shipped S-59 Stream D). Worked end-to-end: pre-flight → lift `checkout main`/`switch main` denies → `--no-ff` merge → restore denies (verified back in place) → audit entry. Two follow-ups logged to BACKLOG for the S-68 refactor: (1) `_append_audit_entry`'s `textwrap.dedent` mangles indentation when multi-line fields are interpolated (this entry was hand-corrected); (2) the from-`main` invocation path skips ms-enforce — the tool should run it branch-isolated (e.g. via a temp worktree) so the check isn't silently skipped.


## 2026-05-29 — batch-5: S-59 + S-63 + S-64 + doctrine recovery + adapter fix

- **Method:** operator-manual via /tmp/batch5-recovery-and-merge.py + /tmp/batch5-continue.py (S-59 Stream D shipped `tools/merge_wave_to_main.py` THIS batch; will be the sanctioned channel for future batches)
- **Operator/Caller:** Nnyan (orchestrator + operator-assist session collaboration)
- **Pre-batch main HEAD:** `4af5f0d` (doctrine + waves: BACKLOG triage + S-66/S-67 drafts + re-annotation)
- **Pre-merge sequence:**
  1. Rewound `wave/S-63-router-wiring-and-cost` from `995a4c7` → `e48516b` (drop misplaced operator-assist doctrine commit per S-63-operator-commit-collision.md)
  2. Cherry-picked `995a4c7` (the doctrine commit: walk-back log + sensitive-path dead-end + ms-enforce gate + CLAUDE.md) onto main → commit `73a8fe0`
  3. Added missing TIER_1 registration for `check_walkback_log` (the Edit that didn't apply previously) — separate commit
- **Branches merged (in order):**
  1. `wave/S-59-access-requests-processor` (no-ff) → merge commit `fa90d02` (with one additive ms-enforce conflict resolved keep-both: check_walkback_log + check_access_requests_stale)
  2. (mid-step) S-59 A↔B adapter fix per S-59-AB-interface-gap.md decision record (run-archive; untracked) exact snippet
  3. `wave/S-63-router-wiring-and-cost` (no-ff, clean tip `e48516b`) → merge commit `a726ace`
  4. `wave/S-64-agent-safe-autofix` (no-ff) → merge commit `adb3cd8`
- **Post-merge main HEAD:** (audit-log commit on top after this entry) — push step follows
- **Pre-flight checks:**
  - Orchestrator per-wave verification (S-59: 73 tests; S-63: 111 router tests; S-64: 15 tests; all wave-internal ms-enforce green)
  - Track-status gate observation cleared by this merge (S-66/S-67 wave files now part of main)
- **Notes:**
  - **S-63 operator-commit collision recovery:** misplaced doctrine commit (`995a4c7`) rewound from wave/S-63 and cherry-picked to main directly. Clean wave/S-63 tip restored. Per orchestrator's decision file recommendation (option a).
  - **S-59 A↔B adapter:** Stream A and Stream B were dispatched in parallel against an under-specified contract. Wave file under-specified the wiring symbol. Adapter committed mid-merge per the decision file's exact snippet. **Follow-up:** amend S-59 wave file to pin the A↔B contract (BACKLOG candidate).
  - **Orchestrator retro candidate:** dedicated merge worktrees + detached HEAD to prevent cross-session collisions. Two collisions this batch (S-63 doctrine + S-64-A stray). Worth folding into ROBOT.md / AUTONOMOUS-DEFAULTS in a follow-up doctrine sweep.

## 2026-05-29 — batch-4 follow-ups: BACKLOG + S-63/S-64 drafts + origin/main doctrine

- **Method:** operator-manual via operator-assist session lift-restore (tools/merge_wave_to_main.py pending S-59 Stream D)
- **Operator/Caller:** Nnyan (LLM Review session drafted on `docs/backlog-batch4-followups`; operator-assist session executed merge via /tmp/batch4-followups-merge.py)
- **Pre-merge main HEAD:** `084d9d8`
- **Branches merged (in order):**
  1. `docs/backlog-batch4-followups` (no-ff) → merge commit `93e7254`
- **Post-merge main HEAD:** `93e7254` (this audit-log commit will sit on top after the next step)
- **Pushed to origin:** YES (push step follows audit-log commit; origin HEAD will be the audit-log commit SHA)
- **Pre-flight checks run:**
  - Dry-merge via `git merge-tree` before execution: clean (no conflicts)
  - ms-enforce post-merge: ✓ All Core Rules satisfied
- **Notes:**
  - LLM Review session folded original 3-wave scope into 2 (S-63 = router wiring + cost/success persistence; S-64 = safe-tier auto-fix). Fold rationale: log_decision() contract is shared and persistence is meaningless until wiring produces decisions. Confirmed sound by operator-assist review of both wave files.
  - Both waves are file-disjoint and parallel-safe (S-63 touches router/*, checker.py, classifier.py, migration 009; S-64 touches autofix.py, scheduler.py, no migration). Either may merge to main first when batch-5 lands.
  - Doctrine commit on the branch (`26f5278`) adds the AUTONOMOUS-DEFAULTS entry about computing batch base from `git rev-parse origin/main` rather than local HEAD — captures the SHA-mismatch lesson from batch-4's prompt that mis-stated the base.
  - Branch cleanup follows in step 8.
  - This merge sets up batch-5: S-59 (4 streams) + S-63 (3 sequential streams) + S-64 (2 sequential streams) under ONE orchestrator. 9 total streams, dispatched in 3 phased rounds.

## 2026-05-29 — Batch: S-58 + agent-review waves (S-60/S-61/S-62) + wave-spec commits

- **Method:** operator-manual (this batch predates the sanctioned merge tool — S-59 Stream D will ship it)
- **Operator/Caller:** Nnyan (running merges from terminal; assisted by this Claude session)
- **Pre-batch main HEAD:** `ed7e130` (access-requests: log + apply .claude/waves and .claude/run write allows)
- **Audit log introduction commit:** `b5f986d` (audit: introduce docs/MERGE-LOG.md) — pre-merge HEAD for the wave merges below
- **Branches merged (in order):**
  1. `chore/waves-s60-62` (no-ff) → merge commit `3b9232e` — wave spec commits from agent-review session
  2. `wave/S-60-agent-fix-safety` (no-ff) → merge commit `47631cf`
  3. `wave/S-61-agent-anonymization` (no-ff) → merge commit `c6546e3`
  4. `wave/S-62-ms-router` (no-ff) → merge commit `7bf7fbc`
  5. `wave/S-58-testclient-sweep` (no-ff) → merge commit `d13daf5` (417 TestClient failures fixed)
- **Post-merge main HEAD:** `d13daf5`
- **Pushed to origin:** YES — `origin/main` at `d13daf5` confirmed via `git push origin main` (188 objects, 74.60 KiB)
- **Pre-flight checks run:**
  - Wave verification per orchestrators (S-58: full suite 450→43; S-60/61/62: orchestrator review verdict ✅)
  - ms-enforce post-merge: ✓ All Core Rules satisfied (39s wall clock) — TIER_2 is green; S-57's 12 fixes plus S-58's 417 TestClient fixes brought the suite into compliance
  - Full pytest re-run skipped (orchestrators already verified; operator chose to trust the audit trail rather than re-run a 2400-test suite)
- **Notes:**
  - First entry under the new merge-log convention (created same day, 2026-05-29).
  - Operator-manual method used because `tools/merge_wave_to_main.py` didn't exist yet at this batch (shipped in S-59 Stream D).
  - `--ff-only` failed on first attempt (main had the docs/MERGE-LOG.md commit ahead of the wave branches' base); switched all merges to `--no-ff`. Wave-branch merges proceeded clean — no conflicts, the orchestrators' "additive ms-enforce + disjoint files" claim held.
  - Stream C snapshot-regression lesson from S-58 will be captured for AUTONOMOUS-DEFAULTS doctrine update in the next commit (same batch).
