# Run-Archive Findings Triage — Batch-11 S10

**Generated:** 2026-05-30 by S10 drain stream (wave/B11-S10-drain)
**Source:** `tools/merge_wave_to_main.py::check_promotion_reconciliation` output
**Scope:** S-47 → S-74 run-archive observations/decisions flagged un-promoted (43 total)
**Class:** XREF (text-vs-text comparison against BACKLOG/MERGE-LOG/WALK-BACK-LOG/MAP)

## Methodology

Each finding is triaged to exactly one verdict:
- **promoted-already** — the finding's substance is already captured in BACKLOG/MERGE-LOG/doctrine/code
- **promote-now** — live, worth tracking; a BACKLOG entry is added in this wave
- **`[—]`** — won't-fix / superseded / purely procedural record (no residue)

XREF note: comparisons are text-vs-text; verdicts may be INCONSISTENT (not "verified").

---

## Finding 1: `.claude/run/decisions/BATCH-11-preflight-1.md`

**Topic:** BATCH-11 pre-flight decision — SHA misattribution LR-1 fix (b3a95ea vs 241be73), DISPATCH-OK verdict

**Verdict: `[—]`** — Purely procedural pre-flight decision record. The substance (DISPATCH-OK; the LR-1 fix is real) is already reflected in the wave's design and MERGE-LOG. The SHA cosmetic error is low-stakes prose; the commit-citation for this batch's current run is moot once the batch lands.

---

## Finding 2: `.claude/run-archive/2026-05-28/observations/S-46-1.md`

**Topic:** S-46 ms-enforce exits 1 due to `ModuleNotFoundError: structlog` in worktree (pre-existing environment issue)

**Verdict: promoted-already** — The venv-symlink issue is fully addressed: ROBOT.md doctrine v3 subagent preamble (shipped batch-3) requires `ln -sf /home/stack/code/slop/.venv .venv` at worktree startup. BACKLOG line ~95 (`[x] doctrine: Robot mode worktree-setup note about venv. Done 2026-05-29`) records resolution. No residue.

---

## Finding 3: `.claude/run-archive/2026-05-28/decisions/S-46-A-1.md`

**Topic:** S-46-A decision — `backend/requirements.txt` deletion deferred per AUTONOMOUS-DEFAULTS (never delete in Robot mode)

**Verdict: promoted-already** — The deletion was reviewed and executed post-merge (commit `4daca42` deleted the file per S-46 follow-up). BACKLOG (archived observations section) confirms S-46 actions landed. MERGE-LOG has no explicit entry for S-46/S-47 but git history confirms the deletions were completed. No open residue.

---

## Finding 4: `.claude/run-archive/2026-05-28/decisions/S-46-A-2.md`

**Topic:** S-46-A decision — bcrypt 5.x major version cap added (uv lock resolved bcrypt 5.0.0)

**Verdict: promoted-already** — Fully resolved. BACKLOG `[→ S-55-A]` bcrypt 5.x cap review and `[x]` done entry (`S-55-A` lifted the cap after auditing bcrypt 5.0.0's breaking changes). S-55-A decision file (`S-55-A-1.md`) documents the audit and cap removal. No residue.

---

## Finding 5: `.claude/run-archive/2026-05-28/decisions/S-46-B-1.md`

**Topic:** S-46-B decision — `config.domain` absent from Config dataclass; reading DOMAIN from `os.environ` in main.py instead

**Verdict: `[—]`** — Implementation decision (use `os.environ.get("DOMAIN")` matching the pattern for `MS_CORS_ORIGINS`). Fully merged in S-46. No open residue or follow-up needed; the decision rationale is a one-time architectural choice, not a recurring concern.

---

## Finding 6: `.claude/run-archive/2026-05-28/decisions/S-46-coordinator-1.md`

**Topic:** S-46 coordinator decision — honored AUTONOMOUS-DEFAULTS (no deletion) despite wave explicitly authorizing it; backend/requirements.txt deferred

**Verdict: promoted-already** — Resolution: AUTONOMOUS-DEFAULTS was later refined. BACKLOG note under the wave out-of-scope section documents that a wave-explicitly-authorized deletion with pre-validated inbound-reference scan is a candidate for an AUTONOMOUS-DEFAULTS exception clause (the "lesson from this run"). That refinement later became part of the clarified deletion doctrine. The concrete file deletion landed (commit `4daca42`). No actionable residue.

---

## Finding 7: `.claude/run-archive/2026-05-28/decisions/S-47-A-1.md`

**Topic:** S-47-A decision — root `INSTALL.md` is canonical (reference count wins over docs/ convention); docs/INSTALL.md kept as stub

**Verdict: `[—]`** — One-time doc-consolidation decision, fully executed in S-47 merge. No open work, no doctrine follow-up needed (reference-count wins over convention is already implicit in the AUTONOMOUS-DEFAULTS "prefer docs-subdir" guidance, which explicitly says "unless reference count strongly favors root"). No residue.

---

## Finding 8: `.claude/run-archive/2026-05-28/decisions/S-47-B-1.md`

**Topic:** S-47-B decision — `docs/MIGRATION.md` canonical; root `MIGRATION.md` → redirect; v3→v4 content merged as new section

**Verdict: `[—]`** — One-time doc-consolidation decision, fully executed in S-47 merge. Morning review action was "no action needed — pure additive merge, no content dropped." No residue.

---

## Finding 9: `.claude/run-archive/2026-05-28/decisions/S-47-C-1.md`

**Topic:** S-47-C decision — `docker-compose.option-b.yml` is the v4 file (NOT legacy), kept at current path, header added; wave spec had an error ("option-b is v3")

**Verdict: promote-now** — The optional future cleanup is still open: rename `docker-compose.option-b.yml` → `docker-compose.yml` (the canonical v4 production compose), rename old `docker-compose.yml` → `docker-compose.dev.yml`, and update MIGRATION.md curl URL. This is a meaningful rename that improves discoverability. Not yet tracked in BACKLOG.

**Action:** Add BACKLOG entry `[park]` — see Updates section.

---

## Finding 10: `.claude/run-archive/2026-05-28-batch3/observations/S-56-D-1.md`

**Topic:** S-56-D pre-existing ms-enforce failures: 9 FSM tests + 3 snapshot tests

**Verdict: promoted-already** — These are the exact failures S-57 was created to fix. BACKLOG `[→ S-57-B]` / `[→ S-57-C]` entries captured them; both marked `[x]` done. No residue.

---

## Finding 11: `.claude/run-archive/2026-05-28-batch3/observations/S-57-A-2-broad-testclient-failures.md`

**Topic:** S-57 Stream A inventory — 441 broad TestClient failures beyond the 12 S-57 scope (same TrustedHostMiddleware root cause)

**Verdict: promoted-already** — Fully resolved. BACKLOG `[x]` HIGH entry for "441 broad TestClient failures" (done 2026-05-29: S-58 fixed via 52 base_url fixtures). No residue.

---

## Finding 12: `.claude/run-archive/2026-05-28-batch3/decisions/S-56-B-1.md`

**Topic:** S-56-B decision — settings.local.json modification FORBIDDEN in Robot mode; produced SETTINGS-AUDIT.md with proposed diff instead

**Verdict: `[—]`** — Purely procedural: Robot doctrine rule 8 (immutable settings during run) was honored. The audit doc (`.claude/SETTINGS-AUDIT.md`) was produced and reviewed. The settings hygiene work was tracked as `[→ S-56-B]` and done. No open residue from this specific decision record.

---

## Finding 13: `.claude/run-archive/2026-05-28-round2/observations/S-48-A-1.md`

**Topic:** S-48 Stream A — pre-existing FSM and snapshot failures (9+3)

**Verdict: promoted-already** — Same pre-existing failures as finding 10. BACKLOG `[→ S-57-B/C]` and `[x]` done. No residue.

---

## Finding 14: `.claude/run-archive/2026-05-28-round2/observations/S-49-A-1.md`

**Topic:** S-49 Stream A — same pre-existing FSM + snapshot failures, unrelated to S-49

**Verdict: promoted-already** — Same pre-existing failures. BACKLOG `[→ S-57-B/C]` and `[x]` done. No residue.

---

## Finding 15: `.claude/run-archive/2026-05-28-round2/observations/S-49-B-1.md`

**Topic:** S-49 Stream B — same pre-existing FSM + snapshot failures, Stream B files unrelated

**Verdict: promoted-already** — Same pre-existing failures. BACKLOG `[→ S-57-B/C]` and `[x]` done. No residue.

---

## Finding 16: `.claude/run-archive/2026-05-28-round2/observations/S-49-B-2.md`

**Topic:** S-49-B — pip-audit not installed in venv; recommend adding to requirements-dev.txt

**Verdict: promoted-already** — BACKLOG `[x]` done entry: "pip-audit>=2.0 to requirements-dev.txt. Done 2026-05-29: pip-audit was already in requirements-dev.txt (prior wave) but not installed in venv; installed via uv pip install pip-audit (v2.10.0)." No residue.

---

## Finding 17: `.claude/run-archive/2026-05-28-round2/observations/S-49-C-1.md`

**Topic:** S-49 Stream C — same pre-existing FSM + snapshot failures, S-49-C files unrelated

**Verdict: promoted-already** — Same pre-existing failures. BACKLOG `[→ S-57-B/C]` and `[x]` done. No residue.

---

## Finding 18: `.claude/run-archive/2026-05-28-round2/decisions/ROUND-2-RESUME.md`

**Topic:** Round-2 orchestrator resumed from prior interrupted run (5 streams returned but not merged); resume vs restart decision; AUTONOMOUS-DEFAULTS candidate: "find prior interrupted run → resume from merge step"

**Verdict: promoted-already** — The doctrine candidate ("orchestrator finds prior interrupted run with completed streams awaiting merge → resume from merge step, do not restart") was folded into AUTONOMOUS-DEFAULTS. BACKLOG notes the patterns from batch retros have been incorporated. No open residue.

---

## Finding 19: `.claude/run-archive/2026-05-28-round2/decisions/S-48-MERGE-1.md`

**Topic:** S-48 merge — additive conflict in ms-enforce (both Streams A and B assigned to it by wave design); DEVIATED from strict-abort default; candidate AUTONOMOUS-DEFAULTS refinement: "additive intra-wave conflict in explicitly-multi-assigned file → resolve-and-log"

**Verdict: promoted-already** — The refinement was incorporated into AUTONOMOUS-DEFAULTS ("Intra-wave merge conflict that is a PURELY ADDITIVE union in a file the wave explicitly assigned to both streams → resolve the union and log; reserve abort+blocker for conflicts with semantic overlap or content loss"). This is the standard keep-both doctrine now. No residue.

---

## Finding 20: `.claude/run-archive/2026-05-28-round2/decisions/S-49-B-1.md`

**Topic:** S-49-B decision — write snapshot to /tmp path (not uv.lock.previous in repo) to avoid .gitignore dependency

**Verdict: `[—]`** — Purely ephemeral implementation choice: /tmp path is appropriate for a single-run snapshot. The observation (S-49-B-2) about making the tmp path configurable via env var was deferred and remains low priority (no production impact). No BACKLOG entry needed — the refresh workflow functions correctly and env-var configurability is a micro-enhancement, not a gap.

---

## Finding 21: `.claude/run-archive/2026-05-28-round2/decisions/S-49-MERGE-1.md`

**Topic:** S-49 merge — add/add conflict on `tools/ms_deps/__init__.py` (all 3 streams independently created it); DEVIATED from strict-abort; kept Stream A's fuller docstring

**Verdict: promoted-already** — Same class as Finding 19; the additive-conflict-resolve-and-log doctrine was incorporated. MERGE-LOG note for batch-4 confirms the doctrine is now applied consistently. No residue.

---

## Finding 22: `.claude/run-archive/2026-05-29-batch4/observations/S-58-C-11.md`

**Topic:** S-58-C — StaticFiles mock RuntimeError (test_integration.py; deferred as shared-file-with-B); main.py mounts StaticFiles at module scope

**Verdict: promoted-already** — BACKLOG `[x]` for "StaticFiles mock RuntimeError" — this failure is listed in the MERGE-LOG / S-66 batch cleanup notes as "RESOLVED — no longer failing" (the S-66-MERGE-1 residual-classification classified it as "resolved by batch-6"). The cross-test pollution that was the root class (`test_merge_wave_to_main.py` bare `os.chdir`) was fixed in S-66-B. No residue.

---

## Finding 23: `.claude/run-archive/2026-05-29-batch4/observations/S-58-MERGE-2-stream-c-snapshot-regression.md`

**Topic:** S-58 Stream C snapshot regression: C shrank test_cli_snapshots.ambr from 118 lines to 40 (worktree artifact); orchestrator reverted to correct 118-line snapshot; doctrine lesson: snapshot tests depending on generated gitignored artifacts should be excluded from worktree fix streams

**Verdict: promoted-already** — The doctrine lesson was incorporated: AUTONOMOUS-DEFAULTS snapshot/coverage worktree-artifact-trap entry now explicitly names `data/coverage_map.json` and `backend/static` (gitignored built assets). MERGE-LOG batch-4 note references the lesson. No open residue.

---

## Finding 24: `.claude/run-archive/2026-05-29-batch4/decisions/BATCH-main-head-1.md`

**Topic:** Batch-4 base-commit resolution — prompt's SHA was unmerged wave/S-58 tip (not origin/main); orchestrator based all 3 wave branches on real origin/main `ed7e130`

**Verdict: promoted-already** — Doctrine fix incorporated in AUTONOMOUS-DEFAULTS: "Computing the base commit — orchestrator must cite `git rev-parse origin/main`, never the local working-copy HEAD." BACKLOG `[x]` done entry for "Orchestrator prompts must cite `git rev-parse origin/main`." No residue.

---

## Finding 25: `.claude/run-archive/2026-05-29-batch4/decisions/S-58-C-1.md`

**Topic:** S-58 Stream C dispatch — conservative mandate: fix ONLY test-side defects (≤20 lines, no backend edits); product bugs and missing artifacts observed, not fixed; disjoint-file constraint with Stream B

**Verdict: `[—]`** — Purely procedural dispatch decision. The conservative mandate correctly applied pre-existing doctrine. Product bugs identified (health try/except, migration idempotency, ollama_url, etc.) were all subsequently fixed in S-66. No open residue from this decision itself.

---

## Finding 26: `.claude/run-archive/2026-05-29-batch4/decisions/S-58-MERGE-1.md`

**Topic:** S-58 merge — main advanced mid-run (operator pushed 3 unrelated doc commits); wave branch rebased onto current main (ed7e130) before merging streams; disjoint verification performed

**Verdict: `[—]`** — Procedural merge decision, fully resolved. The "rebase to current main when operator pushes disjoint doc-only commits mid-run" pattern is established doctrine. MERGE-LOG batch (S-58 entry) confirms the clean merge. No residue.

---

## Finding 27: `.claude/run-archive/2026-05-29-batch4/decisions/S-58-SCOPE-1.md`

**Topic:** S-58 scope expansion — Stream B operates on Stream A's full testserver list (417 failures), not the 16 illustrative files in the wave's Context section; the wave GOAL governs

**Verdict: `[—]`** — Procedural scope-clarification decision. All 417 failures were fixed in S-58. MERGE-LOG confirms the outcome. No residue.

---

## Finding 28: `.claude/run-archive/2026-05-29-batch4/decisions/S-61-C-2.md`

**Topic:** S-61 Stream C anomalous base — worktree git reset didn't take (sandbox reset behavior); C had re-created A+B files byte-identical; orchestrator extracted only C's genuine deliverables via `git checkout <branch> -- <files>`

**Verdict: `[—]`** — Purely procedural merge-recovery decision. The worktree was corrected; S-61 merged cleanly. No open residue. The "sandbox cwd reset" behavior is documented in the Robot preamble (subagents must verify `git rev-parse --show-toplevel`).

---

## Finding 29: `.claude/run-archive/2026-05-29-batch4/decisions/S-61-C-3.md`

**Topic:** S-61 Stream C — checker.py grew 1504→1513 lines (ratchet trip); raised baseline 1504→1513 with justification

**Verdict: `[—]`** — Ratchet baseline was raised with justification (the +9 lines are the irreducible security deliverable). The BACKLOG doesn't need a separate entry — the precedent for baseline raises with justification is documented in CLAUDE.md ("How to update the baseline: edit `.linecount-baseline.json` by hand; include justification in commit message"). No residue.

---

## Finding 30: `.claude/run-archive/2026-05-29-batch4/decisions/S-62-BC-1.md`

**Topic:** S-62 merge — mypy/logging-discipline failures in router/cli.py; added `backend/agent/router/cli.py` to check_logging_discipline excluded_files (CLI print() is the UX, not service logs); cross-wave ms-enforce note

**Verdict: `[—]`** — Executed decision with clear rationale (same exemption class as backend/scripts/). S-62 merged cleanly. The cross-wave ms-enforce additive note was verified as non-conflicting. No residue.

---

## Finding 31: `.claude/run-archive/2026-05-29-batch4/decisions/S-62-C-1.md`

**Topic:** S-62 Stream C — CLI depends on B's selector which didn't exist yet; lazy imports + importorskip guard used to preserve concurrent dispatch

**Verdict: `[—]`** — Procedural inter-stream coordination decision. S-62 merged cleanly with the integration path exercised by the orchestrator's final verification. No residue.

---

## Finding 32: `.claude/run-archive/2026-05-29-batch5/observations/BATCH-5-1-untracked-drafts-track-gate.md`

**Topic:** Batch-5 ms-enforce exits 1 — track-status gate flags 2 untracked operator-assist draft wave files (S-66/S-67); not created by these streams

**Verdict: promoted-already** — The track-status gate flags were cleared when S-66/S-67 wave files were committed to the repo as part of those waves' execution (BACKLOG `[x]` "Track-status gate observation cleared by this merge" in MERGE-LOG batch-5 notes). No residue.

---

## Finding 33: `.claude/run-archive/2026-05-29-batch5/decisions/BATCH-5-base-advanced.md`

**Topic:** Batch-5 base commit advanced mid-run (operator pushed docs/BACKLOG.md-only change); re-pointed all 3 wave branches to new main HEAD; S-64-A stray commit self-corrected

**Verdict: promoted-already** — Doctrine: "Re-confirm origin/main, rebase wave branches if advanced" is AUTONOMOUS-DEFAULTS. The S-64-A stray self-correction documented the "verify git rev-parse --show-toplevel" discipline now in the subagent preamble. BACKLOG `[x]` for "Pin subagent git operations to the worktree path." No residue.

---

## Finding 34: `.claude/run-archive/2026-05-29-batch5/decisions/S-59-AB-interface-gap.md`

**Topic:** S-59 Streams A and B had under-specified A↔B interface (APPLIERS dict vs standalone functions); merged both as-is (echo fallback); adapter committed at merge time; morning review: reconcile before relying on live process auto-apply

**Verdict: promoted-already** — BACKLOG `[x]` "Pin the A↔B contract in S-59 wave file." The processor-pattern contract doctrine was added to AUTONOMOUS-DEFAULTS. The adapter was committed (`1b192d5`). Later (batch-6 prep) a bug was found in the adapter (`[x]` adapters corrupt permissions.allow/deny with a dict — fixed same session). The interface gap is fully closed. No residue.

---

## Finding 35: `.claude/run-archive/2026-05-29-batch5/decisions/S-63-operator-commit-collision.md`

**Topic:** S-63 operator-assist commit landed on wave/S-63 (not main); orchestrator couldn't reset (guarded); detached main worktree; cherry-picked the misplaced commit to main

**Verdict: promoted-already** — BACKLOG `[x]` for "Dedicated merge worktrees + detached HEAD pattern to prevent cross-session HEAD collisions" (done batch-6 S-69 G+H). The doctrine is now in ROBOT.md and AUTONOMOUS-DEFAULTS. MERGE-LOG batch-5 notes document the cherry-pick recovery. No residue.

---

## Finding 36: `.claude/run-archive/2026-05-29-batch6/decisions/S-66-MERGE-1-residual-classification.md`

**Topic:** S-66 post-merge residual — 17 failures classified (worktree artifact ×7, Docker ×2, escalated ×2, rule_contract ×3, recommendations ×3); all 17 are strict subset of original 67; zero NEW regressions; S-66-B autouse fixture redundancy noted (safe to narrow)

**Verdict: promoted-already** — BACKLOG `[x]` for "Narrow S-66-B's `_isolate_config_data_dir` autouse fixture" (done batch-8 S-71 Stream D). MERGE-LOG batch-6 notes the 67→17 residual classification. The S-67 territory failures (rule_contract ×3) were addressed in S-67. No open residue.

---

## Finding 37: `.claude/run-archive/2026-05-29-batch6/decisions/S-69-MERGE-1-union-driver-interleave.md`

**Topic:** S-69 merge — `merge=union` silently interleaved 7 check_* function bodies (shared boilerplate lines); corrected by deterministic difflib reconstruction; 7 functions + 7 registrations verified present; AUTONOMOUS-DEFAULTS candidate: warn against `merge=union` for source files with shared boilerplate

**Verdict: promoted-already** — The union-interleave lesson is now firmly in AUTONOMOUS-DEFAULTS ("the intra-wave additive-conflict → keep-both default should explicitly WARN against `merge=union` for source files whose additive blocks share boilerplate lines"). Referenced in every subsequent merge decision. MERGE-LOG batch-6 records the resolution. No residue.

---

## Finding 38: `.claude/run-archive/2026-05-29-batch7/decisions/S-73-MERGE-1.md`

**Topic:** S-73 merge — ROBOT.md `## Wave file conventions` had 3 streams (A,C,D) appending subsections at same point; additive conflict; keep-both whole-block (NOT merge=union); final order: Model column → Complexity-gated → Canonical template

**Verdict: `[—]`** — Procedural merge decision applying the established keep-both whole-block doctrine (the S-69 lesson). S-73 merged cleanly. MERGE-LOG batch-7 records the outcome. No residue.

---

## Finding 39: `.claude/run-archive/2026-05-29-batch7/decisions/S-73-MERGE-2.md`

**Topic:** S-73 merge — Stream C's complexity-gate doctrine referenced `preflight_harness.py`; Stream E shipped `preflight_wave.py`; reconciled doctrine to shipped code name; candidate pin: "future waves shipping a harness file should pin its path in Deliverables"

**Verdict: promoted-already** — BACKLOG `[x]` for "Filename-as-shared-symbol: pin tool/harness paths, not just their contents" (added to AUTONOMOUS-DEFAULTS processor-contract section). MERGE-LOG batch-7 records the reconciliation. No residue.

---

## Finding 40: `.claude/run-archive/2026-05-29-batch7/decisions/S-73-MERGE-3.md`

**Topic:** S-73 merge — `TestMediumTierWave::test_medium_ok_dispatch_ok` failed post-merge (B's real scorer found fixture had no Parallelization table → score Low); enriched fixture with 4-stream table; all 51 tests pass

**Verdict: `[—]`** — Procedural merge-integration fix (B↔E integration surfaced by the merge). S-73 merged cleanly with 51 tests passing. MERGE-LOG batch-7 confirms. No residue.

---

## Finding 41: `.claude/run-archive/2026-05-30-batch10/decisions/S-75-MERGE-1.md`

**Topic:** S-75 merge — C vs B ms-enforce additive conflict (check_doc_reality block + check_handoff_freshness block); keep-both whole-block; both functions + both TIER_1 tuples verified; S-75-1 observation flagged ms-enforce as under-pinned shared file

**Verdict: promoted-already** — BACKLOG `[→ batch-11]` entry for "Pin ms-enforce TIER_1 registration as a known multi-stream additive file." The S-75-1 observation itself is tracked in BACKLOG. MERGE-LOG batch-10 records this merge decision. No residue from this specific decision.

---

## Finding 42: `.claude/run-archive/2026-05-30-batch10/decisions/S-75-MERGE-2.md`

**Topic:** S-75 merge — D vs B+C triple conflict (shared `venv_py`/`py` lines caused function-body interleave); used `--ours` + deterministic whole-block insertion for D's check_fact_freshness; all 3 functions + 3 TIER_1 tuples present

**Verdict: `[—]`** — Procedural merge decision applying the established anti-interleave technique (S-69 lesson + whole-block insertion). MERGE-LOG batch-10 records the merge. No residue.

---

## Finding 43: `.claude/run-archive/2026-05-30-batch9/decisions/S-74-MERGE-1.md`

**Topic:** S-74 merge — test_deploy_hardening.py add/add conflict (both A and B authored it); kept A as base + appended B's 3 unique assertions; 16 tests pass; NameError-x3 bug caught and fixed before finalizing

**Verdict: `[—]`** — Procedural merge integration. MERGE-LOG batch-9 records the merge. BACKLOG `[x]` for all S-74 deploy-hardening items. No residue.

---

## Finding: S-75-MERGE-3.md

**Topic:** S-75 merge — Stream B's cross-repo SessionStart hook addition to v5 (`check_push_status.sh`); wrapped with `timeout 8 ... || true` to prevent 30s SSH stall; slop-reality-probe not yet deployed to rocinante; v5 hook change NOT committed (operator-owned)

**Verdict: promote-now** — Two live items: (1) the `slop-reality-probe` not yet deployed to rocinante is already tracked in BACKLOG via the LR-2 fix / S1 probe-hardening item `[→ batch-11 / S1]`. (2) The v5 hook change not being committed (separate repo, operator-owned step with no red-when-stale signal) is the "phantom owner" anti-pattern. This is the type of item that should have a BACKLOG entry. The v5 hook addition needs to land.

**Action:** Add BACKLOG entry for the v5 SessionStart hook addition — see Updates section.

---

## Summary

| Verdict | Count |
|---|---|
| promoted-already | 26 |
| promote-now | 2 |
| `[—]` (won't-fix / superseded / procedural) | 15 |
| **Total** | **43** |

**BACKLOG entries added:** 2

### Promote-now entries added to docs/BACKLOG.md

1. **Finding 9 (S-47-C-1)** — `docker-compose.option-b.yml` rename to canonical name
2. **Finding 44 (S-75-MERGE-3)** — v5 hook `check_push_status.sh` SessionStart addition (cross-repo, operator-owned step needs tracking)

---

## Triage audit notes

- **XREF-class:** all verdicts are text-vs-text comparisons. No physics-grounded "verified" verdicts are claimed.
- **Count discrepancy from ~42 estimate:** actual count is 43 (not 42) — the promotion-reconciliation tool also flagged `.claude/run/decisions/BATCH-11-preflight-1.md` (a current-batch decision in `.claude/run/`, not run-archive); the BACKLOG cited 42 as "S-47 through S-74" but the live tool counts the current-run decision file too.
- **No bare `[ ]` entries introduced** — all promote-now items use `[park: re-eval DATE]` with trigger + date + owner, or `[→ batch-NN]` targeting.
