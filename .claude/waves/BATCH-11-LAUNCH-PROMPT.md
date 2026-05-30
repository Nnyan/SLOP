# BATCH-11 — Enforcement-Lifecycle — single-orchestrator launch prompt

Paste the block below into a **fresh Opus session**. ONE orchestrator handles
all 11 streams (`.claude/ROBOT.md` § "Architecture — ONE orchestrator per
batch"). Full wave spec: `.claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md` —
the orchestrator reads it end-to-end. **Hard sequence: S1 (the aging/brownout
engine + probe registry) builds and merges to the batch branch BEFORE the other
streams integrate.**

> **Pre-fire gate: DONE.** The batch-11 wave design got its independent review
> (fresh Opus adversarial reviewer, 2026-05-30; `docs/REVIEW-LOG.md`) — verdict
> NEEDS-CHANGES, all R1–R11 reconciled + folded into the wave file. Safe to fire.

================================================================
in Robot mode: you are the ORCHESTRATOR for SLOP batch-11 (Enforcement-Lifecycle)
— ONE orchestrator, 11 streams, fired from this single session. This is a CODE
batch that builds gates + doctrine; you merge each stream into the batch branch
`wave/batch-11` but DO NOT merge to main and DO NOT push (the Manager does the
post-wave merge via tools/merge_wave_to_main.py).

First read, in order:
  1. .claude/ROBOT.md (binding rules, orchestrator startup sequence, ONE-
     orchestrator-per-batch architecture, dedicated merge-worktree pattern).
  2. .claude/AUTONOMOUS-DEFAULTS.md (decision register).
  3. .claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md (the full wave spec — all
     11 streams, models, deliverables, the reviewer-hardened cross-stream
     contracts and shared-file region pins).
  4. docs/COVERAGE-HANDOFF-AUDIT-REPORT.md §5 (P0–P9 rationale + each fix's own
     failure-mode + red-signal) — the source of record for every stream.

Startup:
  1. Confirm base: `git rev-parse origin/main` — batch-11 builds on the landed
     audit report + the LR-1 fix. Branch the batch off this live SHA.
  2. High-tier pre-flight: run
     `python3 tools/wave_complexity.py .claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md`
     then the matching rigor (validate-wave-file + fact-check subagent +
     processor-contract-pinned + cross-wave disjointness + edited-wave
     consistency). Write `.claude/run/preflight/BATCH-11.md` (DISPATCH-OK or
     BLOCKED). **BLOCK dispatch if any check returns FALSE.**
  3. Create `.claude/run/status/BATCH-11.md` (Bash heredoc, not Write) with
     `**State:** RUNNING` as the first line.

Run shape (the hard sequence matters — see wave spec § "Cross-wave dependencies"):
  - PHASE 1: dispatch ONLY S1 (aging engine / brownout detector + the OPEN-SEAM
    probe registry = P0 + the S-70/S-72 core), model opus, on `wave/B11-S1-aging`.
    When it returns, create the batch branch `wave/batch-11` and merge S1 into it
    using a dedicated merge worktree (`.claude/worktrees/merge-batch-11`, detached
    from origin/main — this ONE time, to create the batch branch). S1 is the
    PINNED producer of the registry schema + the open-seam append mechanism +
    the "INDETERMINATE is red-eligible after N runs" rule the others consume.
  - PHASE 2: dispatch S2, S4, S5, S6, S7, S8, S9, S10, S11 CONCURRENTLY (single
    message, multiple Agent tool uses; isolation:worktree; model per the wave
    spec table), each branched off the S1-merged `wave/batch-11`. Run S3 AFTER
    S2 (they share audit_backlog_stale.py). Inject the subagent preamble.
  - Each subagent commits to its own `wave/B11-SN-*` branch and ships its
    deliverables + a RED-PATH TEST (feed a known-bad input, assert DRIFT /
    non-zero — every new gate must prove it can go red). No gate auto-promotes.
  - Merge each returned stream into `wave/batch-11` via merge worktrees
    **detached from `wave/batch-11`, NOT origin/main** (origin/main would drop
    S1). KEEP-BOTH-WHOLE-BLOCK on the shared additive files: `ms-enforce` TIER_1
    (S5/S6/S7/S11), `CLAUDE.md` (S9 owns CatalogEntry/data-dir regions; S11 owns
    the two-session region), `.claude/ROBOT.md` (S5 owns §3.5/§3.6; S11 owns
    §3.3), `tools/merge_wave_to_main.py` (S5). These regions are disjoint by
    design — keep both halves whole.

Per-stream models (from the wave spec): S1 opus · S2 opus · S3 sonnet · S4 opus
· S5 opus · S6 opus · S7 opus · S8 sonnet · S9 sonnet · S10 sonnet · S11 opus.

Doctrine-floor note: S5, S11 (and the §3.6 prompt-doctrine edit, owned by S5)
touch CLAUDE.md / .claude/ROBOT.md / AUTONOMOUS-DEFAULTS.md or add a `def check_`
→ each trips the independent-review mechanical floor and must carry the
four-question rationale + a docs/REVIEW-LOG.md entry (grounded on a committed
record). Additions are strengthenings → NO WALK-BACK-LOG entry needed.

Maintain `.claude/run/status/BATCH-11.md` continuously; set `**State:** CLOSED`
as your final action. Do not call AskUserQuestion — apply
.claude/AUTONOMOUS-DEFAULTS.md and log each decision + the authorizing rule to
`.claude/run/questions/BATCH-11.md` (proceed, never block). On a hard blocker,
write `.claude/run/blockers/BATCH-11.md` and halt. When all streams are merged
into `wave/batch-11`, set State CLOSED and report — the Manager reviews and does
the single sanctioned merge to main.
================================================================
