# Review Log

Audit trail of independent reviews of significant changes — see CLAUDE.md § "Independent review for significant changes". One entry per significant change: the reviewer, the charge, key findings, and the author's per-finding **reconciliation** (accept/reject + why). The reconciliation line — not "reviewed: yes" — is the point: it records that the author checked the reviewer's findings against physics and what they did about each. Each entry should cite a durable, committed review record. Newest at top.

---

## 2026-05-30 — Batch-11 S5: status protocol + missing-status gate + §3.6 prompt-doctrine + .handoff-sha auto-stamp

- **Change:** doctrine edits to `.claude/ROBOT.md` (§3.5 status-protocol template + a NEW §3.6 prompt-&-menu doctrine) and `.claude/AUTONOMOUS-DEFAULTS.md` (Known additive-registration files), plus `.claude/waves/_TEMPLATE.md`; a merge-time RED-ON-MISSING-STATUS gate + an inexact-name glob fallback + a `.handoff-sha` auto-stamp in `tools/merge_wave_to_main.py`; the test helper in `tests/test_check_handoff_freshness.py` migrated to the `.handoff-sha` contract. Editing two doctrine files (ROBOT.md + AUTONOMOUS-DEFAULTS.md) trips the **independent-review mechanical floor**. Additions/strengthenings only → NO WALK-BACK-LOG entry.
- **Reviewer:** self-administered **four-question rationale** (the floor tier for a doctrine edit/addition — the cheap 80%; this is not a new gate or an irreversible-git op). The findings are reconciled against physics below (the gate is GROUND-tested, not asserted).
- **Four-question rationale:**
  1. **What need?** The orchestrator↔Manager *emitter* side was unspecified: status files had no machine-readable State marker, the canonical filename was unpinned (a misnamed file was silently missed → `_find_status_file`→None was a silent pass), and the manual handoff-refresh step (`.handoff-sha`) had no owner. The prompt-formatting rule lived only in a memory file, not doctrine.
  2. **Why this mechanism?** A `**State:**` first-line marker + a PINNED short filename give the Manager a single `grep` poll target; a merge-time GROUND gate (filesystem) refuses on missing/non-terminal status (a manual step is "covered" only if skipping it can go red — the K-L keystone); the merge tool stamping `.handoff-sha` makes the refresh OWNED by the tool, not a phantom-owner manual step. §3.6 is honestly stamped ADVISORY (formatting is taste — no physics red-signal; do not market it as enforced).
  3. **Failure mode of the new mechanism?** The status gate is GROUND on *presence + first-line State* only — it cannot detect a status file that *lies* (says COMPLETE while work is unfinished). That residual is XREF/UNPROBED and rides Manager batch-landing review. The §3.6 doctrine has no enforcement at all (advisory). The `.handoff-sha` auto-stamp carries an inherent 1-commit self-reference lag (see below).
  4. **Red-signal?** The status gate: `[red-signal: GROUND]` on presence/first-line-State (`tests/test_merge_status_gate.py` feeds missing/RUNNING/BLOCKED/no-marker → asserts refuse). The `.handoff-sha` contract: `tests/test_check_handoff_freshness.py` (absence→DRIFT, match→verified). §3.6: `[red-signal: NONE — ADVISORY]` (honest; formatting has no physics anchor).
- **Key findings → reconciliation:**
  - The §3.6 edit is a Communication/taste rule with no possible GROUND probe. **Reconciled:** stamped ADVISORY in the section header itself; NOT registered as a gate; explicitly "do not market it as enforced."
  - The status gate could become theater if it only string-matched "COMPLETE" anywhere in the file (the old `_status_is_complete` did exactly that). **Reconciled:** the new gate grounds on the FIRST-non-blank-line State marker + filesystem existence (DRIFT on absence, refusing the prior silent-skip); proven red via the red-path test.
  - `.handoff-sha` 1-commit lag: a file cannot store its own commit's SHA. **Reconciled (documented, not hidden):** the stamp writes the *local post-merge main SHA* (the value origin/main becomes on push), so the post-push steady state is `verified` with no second manual stamp; in the merge→push window the gate reads DRIFT, which is the correct loud push/refresh nudge (red-eligible, not a brownout). The lag is documented in `_stamp_handoff_sha`'s docstring, in the stamped artifact's own comment, and in `check_handoff_freshness`'s module docstring — I left the gate's DRIFT-on-absence behavior unchanged (it is correct).
- **Record:** lands in the same commit as the changes above on `wave/B11-S5-status` (cite the commit SHA from the orchestrator's merge; this entry's GROUND legs are the two committed test files).
## 2026-05-30 — Batch-11 S7: `check_independent_review` gate + walk-back GROUND leg

- **Change:** built the PENDING `check_independent_review` gate (`tools/independent_review.py` + ms-enforce wrapper + TIER_1 registration), added a GROUND leg to `check_walkback_log` (numstat-add to `docs/WALK-BACK-LOG.md`, not just a message token), and exposed the PINNED `artifact_exists` helper for S11. This commit ADDS a `def check_` to ms-enforce → it trips the gate's own mechanical floor (correctly), so it carries this entry.
- **Reviewer:** new-enforcement-mechanism tier → author-administered **four-question rationale** (the cheap floor reviewer; a fresh adversarial subagent is not spawnable inside a Robot worktree stream — the residual substance risk rides the Manager batch-landing review + the standing audits, depth-1). Durable committed record: this REVIEW-LOG entry (no `/tmp` pointer).
- **Four-question rationale (additions extend the walk-back four):**
  - **What need?** The Reuse/blast-radius + independent-review doctrine had a `[red-signal: PENDING]` — an unenforced checklist (yellow, not green). A significant change could land claiming "reviewed" with no committed artifact behind the claim (the exact `/tmp`-transcript rot the doctrine names).
  - **Why this mechanism?** A GROUND artifact-existence leg: when the floor fires, the commit must cite a REVIEW-LOG record AND HEAD must have made a non-empty addition to the committed log (git numstat — physics). Token-without-entry → DRIFT. Reuses the `check_walkback_log` numstat-floor shape (sibling family).
  - **Failure mode?** Substance is UNPROBED — the leg proves an entry *landed*, not that the review was *good*; a low-quality entry passes the leg. Mitigation: honest `[red-signal: PARTIAL]`; substance rides the Manager batch-landing review. The GROUND-on-fabrication leg is the half that can go red against physics today.
  - **Red-signal?** `[red-signal: PARTIAL]` — GROUND on missing-artifact (red against git numstat); UNPROBED on substance. HARD STOP: warn-only, no auto-promotion to blocking until a deliberate recorded escalation.
- **Acyclicity (the sharpest correctness point), enforced IN CODE:** the floor-path set statically excludes `docs/REVIEW-LOG.md` (`_FLOOR_EXCLUDED_PATHS`) and the gate's own `def check_independent_review` (`_SELF_CHECK_NAME`, skipped in `_adds_check_def`) — a review (whose only output is a REVIEW-LOG entry) can NEVER trigger a review. Proven by `test_acyclicity_review_log_only_does_not_trip` + `test_acyclicity_adding_own_check_def_does_not_trip`. Changing the exclusion trips WALK-BACK-LOG.
- **Reconciliation vs physics:** ran the tool on live HEAD → DRIFT (this commit's pre-state cited no REVIEW-LOG entry); after adding this entry the same commit reads `verified` [GROUND: numstat]. 12 red-path tests pass (DRIFT on non-existent record; verified on committed record; both acyclicity legs; walk-back token-without-entry → DRIFT).
- **Record:** lands in the same commit as the gate, the helper, and the tests.

## 2026-05-30 — Batch-11 (Enforcement-Lifecycle) wave DESIGN — pre-fire review

- **Change:** the batch-11 wave design (`.claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md` + `BATCH-11-LAUNCH-PROMPT.md`) — High-complexity wave = a "significant change" requiring one independent review before firing.
- **Reviewer:** fresh Opus adversarial subagent (derive-design-independently-from-the-audit-report-and-doctrine, THEN attack the drafts; verified load-bearing claims against live repo state). **Verdict: NEEDS-CHANGES** (3 blockers). Durable record: this entry (the subagent transcript was ephemeral; findings captured below per the committed-record rule).
- **Key findings → reconciliation (all 11 ACCEPTED; applied to the wave file):**
  - **R1 (BLOCKER)** undeclared 3-way `CLAUDE.md` collision (S5 F10 + S9 CatalogEntry/SoT + §3.6 prompt-doctrine). **Accepted** — verified S9's targets live at `CLAUDE.md:288,303-304`. Added `CLAUDE.md` + `ROBOT.md` to the shared-additive list with **region-pinned ownership** (S9 vs S11 vs S5) + keep-both.
  - **R2 (BLOCKER)** §3.6 prompt-doctrine edit referenced but owned by no stream (phantom-owner). **Accepted** — assigned to S5 as an explicit deliverable.
  - **R3 (BLOCKER)** F10 gate can't go RED — no on-disk "Manager-handoff prompt" artifact exists, so it's XREF/false-positive theater. **Accepted (sharpest finding)** — S11 now must FIRST canonicalize a Manager-handoff-prompt artifact (pinned filename + a back-reference token in the working prompt) as a PRECONDITION; only then can the gate ground existence + the back-reference. (Ironically reinforces F10's own thesis: the artifact must be a real thing.)
  - **R4** S1's probe registry is built-from-scratch + enumeration under-specified. **Accepted** — S1 must enumerate the §4g brownout-prone probes + ship a schema doc.
  - **R5** merge-worktree base ambiguity (ROBOT.md hardcodes `--detach origin/main`; Phase-2 must detach from `wave/batch-11` or silently drop S1). **Accepted** — pinned in wave + launch prompt.
  - **R6** `.handoff-sha` auto-stamp owner unpinned. **Accepted** — pinned to S5 (it's a `merge_wave_to_main.py` edit = S5's file).
  - **R7** S2 mediastack queue file unresolved (registry-rot hole). **Accepted** — S2 must resolve it or land the row INDETERMINATE+BACKLOG, not a silent TODO.
  - **R8** S5 overloaded → split F10 into its own stream. **Accepted** — F10 split into **S11** (10→11 streams); cleaner region ownership.
  - **R9** S4's hook-config probe needs S1's registry to be an OPEN SEAM. **Accepted** — S1 contract now mandates the open-seam append mechanism (S2/S4 use it).
  - **R10** `audit_single_entity_hardcode.py` (BACKLOG:58) had no owning stream (dropped). **Accepted** — assigned explicitly to S6.
  - **R11** launch prompt inherited R1/R5 gaps. **Accepted** — folded the keep-both + detach-from-batch-branch one-liners into the launch prompt.
- **Outcome:** all blockers + should-fixes folded in; design is now FIRE-READY. Depth-1 (no review-of-the-review; residual synthesis risk rides batch-11's own pre-flight + Manager batch-landing review).

## 2026-05-30 — LR-1 grounded fix: `check_handoff_freshness` brownout closure

- **Change:** rewrote `tools/check_handoff_freshness.py` to read a committed `.handoff-sha` artifact (absence → DRIFT) instead of parsing a deletable prose bullet from `docs/MANAGER-HANDOFF.md`; added the `.handoff-sha` artifact. Closes the LIVE-RED brownout — the gate had been permanently INDETERMINATE since commit `95dc0e0` deleted the parseable bullet, so a GROUND gate silently returned "not red."
- **Reviewer:** the independent Coverage+Handoff audit session (fresh Opus Auditor-Manager + 7 read-only investigators + a blind-spot critic). It derived this fix's DESIGN independently as finding **F7 / target P1** and reconciled it live against physics (ran the gate → confirmed permanent INDETERMINATE). **Durable committed record:** `docs/COVERAGE-HANDOFF-AUDIT-REPORT.md` (§0.1 LR-1, §3.1 F7, §5 P1) — landed on the same branch.
- **Key findings → reconciliation:**
  - F7/P1 "derive the declared SHA from a committed machine artifact, not human prose; harden absence → DRIFT not INDETERMINATE." **Accepted + implemented:** gate reads `.handoff-sha`; missing/malformed → DRIFT; only genuinely-unreachable origin → INDETERMINATE. **Verified both legs live** (verified when present+matching; DRIFT when absent).
  - The investigator's first instinct ("just re-add the parseable bullet"), which the critic flagged as "isomorphic to the disease." **Rejected** — it recreates a deletable human token; used the grounded artifact instead.
  - Self-reference limit: a file cannot hold its own commit's SHA, so the gate legitimately reads DRIFT (refresh-needed) for one commit after a batch lands. **Accepted as designed** (loud + red-eligible = not a brownout); the auto-stamp (merge tool writes `.handoff-sha`) is batch-11 P1.
- **Tier note:** warn-only gate (zero blocking blast radius); the independent audit IS the durable derivation, so the gate-change review tier is satisfied by a committed reviewer record + author reconciliation (depth-1). No `/tmp` pointer — the cited record is committed.
- **Record:** lands in the same commit as `.handoff-sha`, the gate rewrite, and this entry.

## 2026-05-30 — Independent-review discipline (this doctrine, dogfooded)

- **Change:** the "Independent review for significant changes" doctrine itself (CLAUDE.md) + `docs/REVIEW-LOG.md` + the batch-11 `check_independent_review` gate.
- **Reviewer:** fresh Opus adversarial subagent (derive-own-design-then-attack), charged to hunt for a loop or a freeze.
- **Key findings → reconciliation:**
  - G1 (highest) the gate checks token-presence, not review-occurrence → theater that the promotion machinery could bless into a blocking string-check. **Accepted + refined:** cite a **committed** artifact (not a `/tmp` transcript — the rot we just killed) + an artifact-existence GROUND leg; `[red-signal: PARTIAL]`; hard stop on auto-promotion. (Also checked the reviewer's "auto-promote on timer" claim against doctrine: promotion is a *deliberate* act, not silent — but a false-green would mislead the promoter, so the hard-stop stands.)
  - G2 acyclicity asserted not enforced. **Accepted:** statically exclude REVIEW-LOG + the gate's own def from the trigger, in code.
  - G3 narrow-below-floor recorded reason = stored-and-trusted rot in the dangerous direction. **Accepted — better asymmetry:** no narrow-below-floor; floor is code, flex lives above it; tighten the floor only via reviewed doctrine change.
  - G4 proceed-and-owe has no forcing function. **Accepted:** owed reviews are BACKLOG entries under `check_backlog_stale` (age-red).
  - G5 free widening is cost-deferred to throughput. **Accepted:** reviewer weight by tier (four-question → subagent → separate session).
  - G6 subagent independence partly fictional (author writes the charge). **Accepted:** irreversible tier gets a fixed-charge separate session.
  - G7 floor gameable for non-path triggers. **Accepted:** two honest tiers (mechanical floor vs declared advisory).
  - Bonus: doctrine *removals* have the four-question walk-back; *additions* had none → extend four-question to additions (the floor tier).
- **Record:** key findings captured in this entry (the live subagent transcript was ephemeral `/tmp` — exactly why the doctrine now requires a *committed* artifact going forward). Landed in the same commit as this file.

## 2026-05-30 — Reuse-and-blast-radius checkpoint

- **Change:** the "Reuse-and-blast-radius checkpoint" doctrine (CLAUDE.md) + the batch-11 `audit_single_entity_hardcode.py` scanner + the audit-charter fold-in.
- **Reviewer:** fresh Opus adversarial subagent (derive-then-attack).
- **Key findings → reconciliation:**
  - GAP-1 no red-signal → the checkpoint is an unenforced checklist (yellow, not green). **Accepted:** added the GROUND scanner (batch-11) + honest `[red-signal: PENDING]` stamp.
  - GAP-2 "before authoring ANY tool" too heavy → dead opt-in gate. **Accepted:** scoped the mandatory part to known plural sets / sibling families.
  - GAP-3 collision with focused-wave scope. **Accepted:** "parameterize the seam, not the coverage" + BACKLOG the uncovered members.
  - GAP-4 "insert an error" hand-waving. **Accepted:** a regression test feeding known-bad input asserting DRIFT/non-zero (the `check_handoff_freshness` pattern).
  - GAP-6 self-exemplifying (the frontend grep rule). **Accepted:** generalized CLAUDE.md:156 as the `.vue` instance in the same stroke.
  - GAP-7 the recorded reuse note is itself stored-and-trusted rot. **Accepted:** marked it XREF-class (rationale, not assurance).
  - Reviewer's "day-one true-positive" (`lift_push_restore.py`'s `SETTINGS_PATH` hardcode): **reconciled against code → it is a JUSTIFIED hardcode** (the deny lifted is the running SLOP session's, always SLOP). Not a bug; it is the scanner's false-positive-suppression test case (the recorded-reason exemption).
- **Record:** landed in commit `e0b310d` (doctrine: Reuse-and-blast-radius checkpoint…). Live subagent transcript was ephemeral.
