# Coverage-Completeness & Handoff-Integrity Audit — launch prompt

Paste the block below into a **fresh Opus session**. **GATE: fire ONLY after S-74
(batch-9) AND S-75 (batch-10) have both landed on `main`.** This is a READ-ONLY audit
that commits a report to a branch for Manager review — it does NOT merge to main and
does NOT need a pinned base SHA (it reconfirms `origin/main` at startup). Full charter:
`docs/COVERAGE-HANDOFF-AUDIT.md` — read it first.

================================================================
in Robot mode: you are the Auditor-Manager for the SLOP combined
Coverage-Completeness + Handoff-Integrity audit. This is a READ-ONLY
discovery/design session that PRODUCES batch-11 — it is NOT a code wave.
You do NOT merge or push anything to main.

First read the charter in full: docs/COVERAGE-HANDOFF-AUDIT.md
Also read: docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md (the precedent +
the GROUND-vs-XREF keystone you will reuse).

Startup:
  1. Confirm S-74 AND S-75 are both on main (grep docs/MERGE-LOG.md;
     `git log --oneline` for the S-75 merge). If S-75 is NOT landed, STOP —
     this audit is gated on it. Re-confirm `git rev-parse origin/main`.
  2. Create the output branch `docs/audit-coverage-handoff` for your
     deliverables. (You commit there; you never touch main.)

Run shape (per the charter §3-§4):
  - Dispatch parallel READ-ONLY investigator subagents concurrently
    (general-purpose; NO worktrees — they return findings, not edits),
    split across the two tracks:
      Track A (coverage, SNAPSHOT): enumerate every KNOWN tiered/enumerable
        invariant (seed list in charter §3-A — discover more), then
        coverage-check each tier → Covered / Warn-only / Doctrine-only /
        UNCOVERED / N/A, then a max-blast-radius fix per gap. Track A ALSO
        carries two named enumeration/hunt targets (charter §3-A):
          (i) Operator-owned blast-radius — enumerate every operator-owned /
              manual step; each must be reclassified (automated/session-owned)
              OR carry a red-when-stale signal (enforce "No phantom owners").
          (ii) Single-entity-hardcoded tools/gates — hunt every tool/gate
              hardcoded to one member of a known plural set (check_backlog_stale
              + the push-tool lineage are seeds); enforce the "Reuse-and-blast-
              radius checkpoint"; honor recorded scope-reasons (a justified
              hardcode like lift_push_restore.py's SETTINGS_PATH is NOT a finding).
      Track B (handoff, LONGITUDINAL): review the HISTORY of handoffs
        (MANAGER-HANDOFF.md git history, the memory corpus's evolution, the
        .claude/waves/ launch-prompt archive, MERGE-LOG, .claude/run-archive/,
        past orchestrator prompts) for what varied + what correlated with
        seamless vs lossy outcomes. Cover all handoff types. Hit the concrete
        target list in charter §3-B.
  - Then a SHARED phase-2 blind-spot critic over the MERGED findings of BOTH
    tracks (charter §3 "blind-spot pass"). Derive independently FIRST, then
    attack.
  - KEYSTONE: a tier / handoff step is "covered" ONLY if its gate can go RED
    against physics. Doctrine-only / warn-only / an unenforced checklist =
    YELLOW, not green. Do not rubber-stamp.

Deliverables (on docs/audit-coverage-handoff — charter §6):
  1. Create (write new) docs/COVERAGE-HANDOFF-AUDIT-REPORT.md — both tracks' findings, the
     blind-spot critic's pass, and ONE prioritized blast-radius target list
     for batch-11. Bake in the orchestrator status-protocol additions
     (charter §5) as a Track-B deliverable.
  2. A co-batching analysis for batch-11 (this audit's targets + the
     check_backlog_stale registry expansion + the deferred Enforcement-
     Lifecycle core S-70+S-72) — max stream parallelism, file-disjointness
     permitting.
  3. Commit to the branch. DO NOT merge, DO NOT push. The Manager reviews +
     drafts batch-11.

Maintain .claude/run/status/COVERAGE-HANDOFF-AUDIT.md continuously, with a
top-of-file `**State:** RUNNING` marker; set `**State:** CLOSED` as your final
action before ending (you are dogfooding the very protocol you are specifying).

Do not call AskUserQuestion. Apply .claude/AUTONOMOUS-DEFAULTS.md for any
decision and log it to .claude/run/questions/COVERAGE-HANDOFF-AUDIT.md (the
non-blocking channel — proceed, never block). On a hard blocker, write
.claude/run/blockers/COVERAGE-HANDOFF-AUDIT.md and halt.
================================================================
