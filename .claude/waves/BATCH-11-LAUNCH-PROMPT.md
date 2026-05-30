# BATCH-11 — Enforcement-Lifecycle — single-orchestrator launch prompt

Paste the block below into a **fresh Opus session**. ONE orchestrator handles
all 10 streams (`.claude/ROBOT.md` § "Architecture — ONE orchestrator per
batch"). Full wave spec: `.claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md` —
the orchestrator reads it end-to-end. **Hard sequence: S1 (the aging/brownout
engine) builds and merges to the batch branch BEFORE the other streams
integrate.**

> **Pre-fire gate (Manager, BEFORE pasting this):** the batch-11 wave DESIGN is
> a "significant change" → it gets ONE independent review (REVIEW-LOG entry) per
> CLAUDE.md § "Independent review for significant changes" before firing. Do not
> launch until that review is recorded.

================================================================
in Robot mode: you are the ORCHESTRATOR for SLOP batch-11 (Enforcement-Lifecycle)
— ONE orchestrator, 10 streams, fired from this single session. This is a CODE
batch that builds gates + doctrine; you merge each stream into the batch branch
`wave/batch-11` but DO NOT merge to main and DO NOT push (the Manager does the
post-wave merge via tools/merge_wave_to_main.py).

First read, in order:
  1. .claude/ROBOT.md (binding rules, orchestrator startup sequence, ONE-
     orchestrator-per-batch architecture, dedicated merge-worktree pattern).
  2. .claude/AUTONOMOUS-DEFAULTS.md (decision register).
  3. .claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md (the full wave spec — all
     10 streams, models, deliverables, cross-stream contracts).
  4. docs/COVERAGE-HANDOFF-AUDIT-REPORT.md §5 (P0–P9 rationale + each fix's own
     failure-mode + red-signal) — the source of record for every stream.

Startup:
  1. Confirm base: `git rev-parse origin/main` — batch-11 builds on the landed
     audit report + the LR-1 fix. Branch the batch off this live SHA.
     (Re-derive it; do not trust any baked value.)
  2. High-tier pre-flight (this wave scores High): run
     `python3 tools/wave_complexity.py .claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md`
     then the matching rigor (validate-wave-file + fact-check subagent +
     processor-contract-pinned + cross-wave disjointness + edited-wave
     consistency). Write `.claude/run/preflight/BATCH-11.md` (DISPATCH-OK or
     BLOCKED). **BLOCK dispatch if any check returns FALSE.**
  3. Create `.claude/run/status/BATCH-11.md` (Bash heredoc, not Write) with
     `**State:** RUNNING` as the first line.

Run shape (the hard sequence matters — see wave spec § "Cross-wave dependencies"):
  - PHASE 1: dispatch ONLY S1 (aging engine / brownout detector = P0 + the
    S-70/S-72 core), model opus, in its own worktree on `wave/B11-S1-aging`.
    When it returns, merge it into the batch branch `wave/batch-11` using a
    dedicated merge worktree (`.claude/worktrees/merge-batch-11`, detached
    HEAD). S1 is the PINNED producer of the probe-registry schema + the
    "INDETERMINATE is red-eligible after N runs" rule that the others consume.
  - PHASE 2: dispatch S2, S4, S5, S6, S7, S8, S9, S10 CONCURRENTLY (single
    message, multiple Agent tool uses; isolation:worktree; model per the wave
    spec's Parallelization table), each branched off the S1-merged
    `wave/batch-11`. Run S3 AFTER S2 (they share audit_backlog_stale.py — S2
    reshapes the I/O signature, S3 adds parser legs). Inject the subagent
    preamble (ROBOT.md) at the top of each task prompt.
  - Each subagent commits to its own `wave/B11-SN-*` branch and ships its
    deliverables + a RED-PATH TEST (feed a known-bad input, assert DRIFT /
    non-zero — every new gate must prove it can go red). No gate auto-promotes
    to blocking.
  - Merge each returned stream into `wave/batch-11` via dedicated merge
    worktrees. ms-enforce TIER_1 registration is a known additive touchpoint
    (S5 + S7) → keep-both-whole-block on conflict.

Per-stream models (from the wave spec): S1 opus · S2 opus · S3 sonnet · S4 opus
· S5 opus · S6 opus · S7 opus · S8 sonnet · S9 sonnet · S10 sonnet.

Doctrine-floor note: S4, S5, S7 (and the prompt-doctrine edit) touch CLAUDE.md /
.claude/ROBOT.md / AUTONOMOUS-DEFAULTS.md or add a `def check_` → each trips the
independent-review mechanical floor and must carry the four-question rationale +
a docs/REVIEW-LOG.md entry (grounded on a committed record). Additions are
strengthenings → NO WALK-BACK-LOG entry needed.

Maintain `.claude/run/status/BATCH-11.md` continuously; set `**State:** CLOSED`
as your final action. Do not call AskUserQuestion — apply
.claude/AUTONOMOUS-DEFAULTS.md and log each decision + the authorizing rule to
`.claude/run/questions/BATCH-11.md` (proceed, never block). On a hard blocker,
write `.claude/run/blockers/BATCH-11.md` and halt. When all streams are merged
into `wave/batch-11`, set State CLOSED and report — the Manager reviews and does
the single sanctioned merge to main.
================================================================
