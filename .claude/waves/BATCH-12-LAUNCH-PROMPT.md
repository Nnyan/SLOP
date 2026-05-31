# BATCH-12 — Process-Hardening — single-orchestrator launch prompt

Paste the block below into a **fresh Opus session**. ONE orchestrator handles
both streams (`.claude/ROBOT.md` § "Architecture — ONE orchestrator per batch").
Full wave spec: `.claude/waves/BATCH-12-PROCESS-HARDENING.md` — the orchestrator
reads it end-to-end. **No hard sequence: S1 ∥ S2 (disjoint files; only
`tools/probe_registry.json` is shared, append-only).**

> **Pre-fire note:** this is a High-tier wave (`wave_complexity.py` score 9 —
> sensitive doctrine/security paths + an Opus stream + a refactor). S2 edits
> `.claude/ROBOT.md` + adds a `def check_` → it trips the independent-review
> mechanical floor and ships a four-question rationale + a `docs/REVIEW-LOG.md`
> entry; the **new-gate adversarial review is OWED at batch-landing** (the Manager
> runs it before the sanctioned merge). Additions are strengthenings → NO
> WALK-BACK-LOG entry.

================================================================
in Robot mode: you are the ORCHESTRATOR for SLOP batch-12 (Process-Hardening) —
ONE orchestrator, 2 streams, fired from this single session. This is a CODE batch
that hardens the sanctioned-push channel and adds the checkout-borrow GROUND
red-signal + doctrine. You merge each stream into the batch branch
`wave/batch-12` but DO NOT merge to main and DO NOT push (the Manager does the
post-wave merge via tools/merge_wave_to_main.py).

First read, in order:
  1. .claude/ROBOT.md (binding rules, orchestrator startup sequence, ONE-
     orchestrator-per-batch architecture, dedicated merge-worktree pattern,
     subagent preamble).
  2. .claude/AUTONOMOUS-DEFAULTS.md (decision register).
  3. .claude/waves/BATCH-12-PROCESS-HARDENING.md (the full wave spec — both
     streams, models, deliverables, the precise probe red-condition scoping,
     the shared append-only probe registry).
  4. docs/PROBE-REGISTRY.md (the open-seam append contract + row schema — both
     streams append a probe row).

Startup:
  1. Confirm base: `git rev-parse origin/main` (expect 2877d58 or later — this
     batch builds on landed batch-11: audit_sanctioned_ground.py, the probe
     registry, audit_probe_aging.py). Branch the batch off this live SHA.
  2. High-tier pre-flight: run
     `python3 tools/wave_complexity.py .claude/waves/BATCH-12-PROCESS-HARDENING.md`
     (expect High, score 9) then the matching rigor (validate-wave-file +
     fact-check subagent + processor-contract-pinned + cross-wave-disjointness +
     edited-wave consistency). Write `.claude/run/preflight/BATCH-12.md`
     (DISPATCH-OK or BLOCKED). **BLOCK dispatch if any check returns FALSE.**
  3. Create `.claude/run/status/BATCH-12.md` (Bash heredoc, not Write) with
     `**State:** RUNNING` as the first non-blank line.

Run shape (no hard sequence):
  - Dispatch S1 and S2 CONCURRENTLY (single message, multiple Agent tool uses;
    **isolation:"worktree" on BOTH** — this wave dogfoods its own S2 rule;
    S1 model sonnet, S2 model opus). Inject the subagent preamble (git -C
    <worktree> pin).
  - Each subagent commits to its own branch (S1 → wave/B12-S1-sanctioned,
    S2 → wave/B12-S2-checkout) and ships its deliverables + a RED-PATH TEST
    (feed a known-bad input, assert DRIFT / non-zero — every new gate must prove
    it can go red). No gate auto-promotes.
  - Create the batch branch wave/batch-12 and merge both streams into it via a
    dedicated merge worktree (.claude/worktrees/merge-batch-12, detached from
    origin/main). KEEP-BOTH-WHOLE-BLOCK on the only shared file:
    tools/probe_registry.json (both append a probe row). S2's ms-enforce TIER_1
    block and .claude/ROBOT.md doctrine subsection are S2-only.

Per-stream models (from the wave spec): S1 sonnet · S2 opus.

Doctrine-floor note: S2 edits .claude/ROBOT.md AND adds a `def check_` → it must
carry the four-question rationale (what need, why this mechanism, its failure
mode, its red-signal) + a docs/REVIEW-LOG.md entry grounded on a committed
record. The new-gate adversarial review is OWED at batch-landing (Manager runs
it). Additions are strengthenings → NO WALK-BACK-LOG entry.

Maintain `.claude/run/status/BATCH-12.md` continuously; set `**State:** CLOSED`
as your final action. Do not call AskUserQuestion — apply
.claude/AUTONOMOUS-DEFAULTS.md and log each decision + the authorizing rule to
`.claude/run/questions/BATCH-12.md` (proceed, never block). On a hard blocker,
write `.claude/run/blockers/BATCH-12.md` and halt. When both streams are merged
into `wave/batch-12`, set State CLOSED and report — the Manager reviews, runs the
owed S2 adversarial review, and does the single sanctioned merge to main.
================================================================
