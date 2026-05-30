# Review Log

Audit trail of independent reviews of significant changes — see CLAUDE.md § "Independent review for significant changes". One entry per significant change: the reviewer, the charge, key findings, and the author's per-finding **reconciliation** (accept/reject + why). The reconciliation line — not "reviewed: yes" — is the point: it records that the author checked the reviewer's findings against physics and what they did about each. Each entry should cite a durable, committed review record. Newest at top.

---

## 2026-05-30 — Batch-11 S11 (F10): two-session Manager-handoff-artifact contract + gate

- **Change:** doctrine addition to `CLAUDE.md` (new § "Two-session Manager handoff — BOTH artifacts, with a back-reference") + `.claude/ROBOT.md` (new § "Two-session Manager→Manager handoff artifacts (§3.3)") + a new `def check_manager_handoff_artifacts` in `ms-enforce` (TIER_1 warn-only) + red-path tests (`tests/test_check_manager_handoff_artifacts.py`). Trips the **mechanical floor** (doctrine-file edits + a new `def check_`).
- **Reviewer / tier:** doctrine addition → the **self-administered four-question rationale** (the 80% tier; cheap). This is a strengthening/addition, not a removal → NO WALK-BACK-LOG entry. Durable committed record: this entry + the stream commit (SHA recorded in the merge-log / stream branch `wave/B11-S11-handoff`).
- **Four-question rationale (additions-extended walk-back four questions):**
  - **What need:** a Manager→Manager handoff is the **stored-and-trusted, rot-prone** knowledge class (Knowledge-Lifecycle keystone). The audit (report §3.1) catalogs prose-only handoff failures (F1 volatile-state, F5 phantom `/tmp` pointers) — state with no durable, named, GROUND-able record behind it. The need: make the handoff a real on-disk artifact a probe can touch, not prose a session trusts.
  - **Why this mechanism:** canonicalize TWO artifacts — A (the Manager-handoff prompt, pinned filename `.claude/waves/<BATCH>-MANAGER-HANDOFF-PROMPT.md`) and B (any working `*-LAUNCH-PROMPT.md`) — with B carrying a committed **back-reference token** `<!-- manager-handoff-prompt: <path> -->`. The token is the **discriminator**: it lets a filesystem-GROUND gate distinguish a *legitimately combined* handoff (B ships alongside a real A → verified) from a *dangling* one (B's token resolves to no file → DRIFT) WITHOUT false-positiving on a deliberately-combined handoff. This is the R3 reviewer finding (the wave-design review) made concrete: without a defined artifact + token the gate would be XREF/false-positive theater.
  - **Its failure mode:** (1) a Manager could ship A under a non-canonical filename → the newest-by-mtime scan wouldn't recognize it (mitigated: the canonical name is doctrine-pinned in two places; an off-name file simply falls into the launch-prompt path and surfaces as INCONSISTENT/DRIFT, never a silent pass). (2) The gate grounds *existence + the back-reference*, NOT the *content quality* of the handoff (a present-but-useless A passes) — substance rides the Manager batch-landing review, honestly UNPROBED. (3) mtime is the "newest" proxy; a touch could reorder — acceptable for a warn-only signal.
  - **Its red-signal:** `check_manager_handoff_artifacts` (TIER_1 **warn-only**), GROUND on `.claude/waves/`: newest handoff is a working `*-LAUNCH-PROMPT.md` whose back-reference token resolves to no existing Manager-handoff-prompt file → **DRIFT**; a launch prompt with no token at all → **INCONSISTENT** (XREF-class, not a silent OK); empty/absent dir → **INDETERMINATE** (ground unreachable, never downgraded to OK). Proven red-eligible by `tests/test_check_manager_handoff_artifacts.py::test_dangling_backreference_drifts` (DRIFT) and `::test_paired_a_and_b_verified` (verified). Does NOT auto-promote to blocking.
- **Reuse note (Reuse-and-blast-radius checkpoint):** the artifact-existence check SHOULD reuse S7's pinned `artifact-existence helper`, but S7 merges later and its helper is NOT on the `wave/batch-11` base at S11 author-time. Implemented as a direct filesystem check (`_mh_artifact_exists`) with an in-code merge-time refactor note to fold into S7's helper once it lands. Flagged here so the orchestrator/Manager schedules the refactor.
- **Record:** lands in the same stream commit as the doctrine edits, the gate, and the tests.

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
