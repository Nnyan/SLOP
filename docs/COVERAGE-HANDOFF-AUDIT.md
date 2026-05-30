# Coverage-Completeness & Handoff-Integrity Audit — Charter

**For:** a fresh **Opus Auditor-Manager** session (Robot mode) + its read-only
investigator subagents.
**Status:** scheduled 2026-05-30. This is a discovery/design phase that **produces**
the implementation batch (batch-11) — it is NOT itself a code wave.
**Gate:** fire ONLY after **S-74-DEPLOY-HARDENING (batch-9) AND S-75-KNOWLEDGE-LIFECYCLE
(batch-10) have both landed on `main`.** The audit's output DEFINES batch-11's scope, so
running it before S-75 freezes would churn.
**Output goes on branch `docs/audit-coverage-handoff` (committed, NOT merged/pushed)** —
the Manager reviews + merges, then drafts batch-11 from the blast-radius list.

This is a **combined two-track** audit run as ONE session — a handoff gap IS a coverage
gap, so the two tracks share a blind-spot critic + synthesis and emit ONE report + ONE
prioritized blast-radius target list. Running them together avoids disconnected piles and
shared-checkout contention (never double-orchestrate the SLOP checkout).

## 1. The problem (both tracks)

Despite rules, ms-enforce gates, ADRs, BACKLOG triage, walk-back logs, and a
structured-plaintext memory system, two recurring failure shapes persist that prior
gap-audits did not surface proactively:

- **Track A — coverage gaps.** We have many KNOWN, enumerable, *tiered* invariants (the 3
  repo rings, the file-size ratchet categories, the ms-enforce gate set, the sanctioned-
  channel hierarchy, the BACKLOG triage states, the park-rule triad, the aging legs, …).
  For each, the question "is **every** tier actually covered by a reconciler / gate / test
  / owner?" has never been answered systematically. The motivating miss: repo state had a
  KNOWN layer (Ring-0, uncommitted working-tree WIP) with **no reconciler** — it surfaced
  only via friction (84KB of slop-process WIP sat uncommitted ~2 days, unwatched).

- **Track B — handoff gaps.** Handoffs (session→session, Manager→Manager, orchestrator
  launch/return, end-session wind-down) have been **inconsistent** — some complete and
  well-instructed, some lossy. Two reproducible defects already named: handoffs that
  **assert volatile state** (a prior handoff said an orchestrator was "still running"; it
  had closed by read-time), and incoming sessions that **fail to read the prior session's
  closing output** (the actual handoff payload). The end-of-session doc/memory update is
  "vibes," not an enforced checklist.

The shared root: knowledge is **stored-and-trusted** rather than **derived/reconciled
against physics**. Both tracks ask the same meta-question from two angles — *is the
structure complete, and can each piece go RED when it drifts?*

## 2. Evidence (derive findings from THESE, not from theory)

**Track A seed evidence:**
- The Ring-0 miss (above) — a known state layer with no reconciler; the sibling
  working-tree hook fix landed (slop-process `e5c0da5`) but the committed-docs side
  (`check_backlog_stale` only triaging SLOP `docs/BACKLOG.md`) is still uncovered.
- `check_backlog_stale` catches only bare `[ ]` — it does NOT flag overdue / dateless /
  already-fired parks, though the strengthened park rule requires trigger + date + owner.

**Track B seed evidence:**
- The "still running" volatile-state assertion (memory `feedback-handoff-no-volatile-state`).
- Inconsistent next-session instruction quality across the `MANAGER-HANDOFF.md` history.
- The `check_test_isolation` / cross-session HEAD-leak incidents (drafting sessions leaving
  a branch checked out on the shared checkout) — a handoff-hygiene coverage gap.

Forensics: `docs/MANAGER-HANDOFF.md` git history, the memory corpus's evolution, the
`.claude/waves/` launch-prompt archive, `docs/MERGE-LOG.md`, `.claude/run-archive/`, past
orchestrator prompts, `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`.

## 3. The charge

### Track A — Coverage-Completeness (meta-pattern #9; snapshot method)

1. **ENUMERATE "things we KNOW"** — sweep doctrine + code + docs for every tiered/
   enumerable invariant. Seed list (NOT exhaustive — the audit discovers more): the 3 repo
   rings; file-size ratchet categories; BACKLOG triage states `[→]`/`[park]`/`[x]`/`[—]`;
   the park-rule triad (trigger/date/owner); the 4 aging legs (incl. probes-age); the
   ms-enforce gate set (warn-only vs enforcing) ↔ doctrine rules; the sanctioned-channel
   hierarchy (is every dangerous op routed?); the K-L 8-class taxonomy; the 3 data dirs;
   the dual `CatalogEntry` defs; `_SLOP_MANAGED_VARS`; Quick Stacks SoT; catalog env-var
   syntax; the wave-file schema; cross-session HEAD safety.
2. **COVERAGE-CHECK each tier** → classify: **Covered** (gated + enforced) / **Warn-only**
   / **Doctrine-only** (no automation) / **UNCOVERED** (Ring-0 class) / **N/A**.
3. **MAX-BLAST-RADIUS fix per gap** — not a point-patch: define the full set of sites + the
   generalizing mechanism + the new mechanism's own failure mode. (The `check_backlog_stale`
   → `(repo, file, syntax)` registry is the template.)

Track A additionally carries two NAMED enumeration/hunt targets (each governed by the keystone —
a target is "covered" only if its gate can go RED against physics):

- **(i) Operator-owned blast-radius.** Enumerate EVERY operator-owned / manual step; each must be
  reclassified (automated / session-owned) OR carry a red-when-stale signal — enforce the
  CLAUDE.md "No phantom owners; no silently-trusted manual step" doctrine. A manual step with no
  red-when-stale signal is a coverage gap of the same class as an unreconciled state tier.
- **(ii) Single-entity-hardcoded tools/gates.** Hunt EVERY tool/gate hardcoded to one member of a
  known plural set (the `check_backlog_stale` SLOP-only path and the push-tool lineage are seed
  instances) — enforce the CLAUDE.md "Reuse-and-blast-radius checkpoint". Honor recorded
  scope-reasons: a justified hardcode (e.g. `lift_push_restore.py`'s `SETTINGS_PATH`) is NOT a
  finding.

### Track B — Handoff-Integrity (meta-pattern #10; LONGITUDINAL method)

Review the **HISTORY** of handoffs (not a snapshot) to find what varied and what correlated
with seamless vs lossy outcomes. Cover ALL handoff types: session→session, Manager→Manager,
orchestrator launch/return, end-session wind-down. Concrete targets:
- **End-of-session update completeness** — is there a doc/memory checklist, enforced or vibes?
- **Next-session instruction quality** — extract WHY the good handoffs worked.
- **Prompt doctrine** — formalize + extend memory `feedback-prompt-and-menu-formatting` into
  doctrine: formatting rules, WHEN to surface a prompt, single-sentence vs full prompts.
- **Automate-vs-ask** — catalog things sessions ask the user to do that could be a hook/tool
  (ties to v5 session-end-hook work). Automation can't be fumbled at handoff.
- **End-session process** — define + automate the wind-down.
- **Orchestrator↔Manager status protocol** (already partly specced — see §5; the audit
  systematizes it into the standard template, not a one-off).

### Both — the keystone and the blind-spot pass

- **KEYSTONE rubric (reused from the K-L audit):** a tier / handoff step is "**covered**"
  ONLY if its gate can go **RED against physics** (GROUND-vs-XREF). Doctrine-only / warn-only
  / a checklist nobody is forced to run = **YELLOW, not green.** This prevents the audit from
  rubber-stamping.
- **BLIND-SPOT CRITIC (adversarial, phase 2):** after both tracks' findings merge — what
  structures did Track A miss? what tiers did it wave through as "covered" that are only
  warn-only/doctrine-only? what handoff failure mode did Track B not name? The Appendix-attack
  discipline from the K-L audit applies: derive independently FIRST, then attack.

## 4. Fixed constraints (decided — design WITHIN these)

- **Audit topology:** ONE Opus Auditor-Manager dispatches **parallel READ-ONLY investigator
  subagents** (no worktrees — findings, not file mutations), split across the two tracks
  (Track A enumerate/coverage-check lenses; Track B longitudinal-history lenses). Then a
  **shared phase-2 blind-spot critic** reviews the MERGED findings from both tracks. The
  Auditor-Manager synthesizes ONE report. (One manager + many auditors — NOT multiple
  independent top-level sessions; synthesis needs one mind across both tracks.)
- **Max parallelism** (memory `feedback-wave-max-parallel`): dispatch the investigator
  subagents concurrently; sequential is the exception.
- **READ-ONLY:** the audit produces a report + a blast-radius target list. It commits to its
  branch and does NOT merge. Fixes come in batch-11, drafted by the Manager from the report.
- **Output feeds ONE batch:** batch-11 (Enforcement-Lifecycle) absorbs BOTH blast-radius
  streams — this audit's targets AND the `check_backlog_stale` registry expansion (memory
  `project-backlog-stale-gate-blast-radius`, already a `[→ batch-11]` BACKLOG entry).

## 5. Orchestrator↔Manager status protocol (bake into the deliverable)

The two-session model: the Manager GENERATES the orchestrator prompt and never runs waves; a
fresh session RUNS it. The orchestrator already writes `.claude/run/status/<wave>.md`
(continuous) + `.claude/run/blockers/<wave>-<stream>.md` (hard stops) — S-74 proved the
Manager can read the closing output + detect blockers WITHOUT being told fired/closed. The
audit's remediation wave must add these THREE to the **standard** orchestrator template in
`.claude/ROBOT.md` (not a single prompt):

1. A fixed top-of-file marker `**State:** RUNNING→COMPLETE|BLOCKED|NEEDS-INPUT|CLOSED` that
   the Manager polls.
2. A non-blocking `.claude/run/questions/<wave>.md` clarification channel — the orchestrator
   does NOT block (it proceeds via `.claude/AUTONOMOUS-DEFAULTS.md`) but logs the question +
   the default it took, for Manager review. (Resolves the zero-prompt-Robot-mode tension.)
3. "Write the terminal `**State:** CLOSED` as your final action before ending."

Manager-side: a poll loop (`/loop` or a scheduled wakeup) over status State + `blockers/` +
`questions/`. The Manager cannot force-kill another interactive session — the orchestrator
SELF-terminates on a terminal State; the Manager detects the marker. This is the
automate-vs-ask category made concrete.

## 6. Deliverables (on `docs/audit-coverage-handoff`)

1. **`docs/COVERAGE-HANDOFF-AUDIT-REPORT.md`** — Track A: the full tiered-invariant inventory
   with each tier's coverage classification + the max-blast-radius fix per gap. Track B: the
   longitudinal handoff-failure taxonomy + WHY good handoffs worked + the proposed Handoff
   Protocol (per-type checklist) + prompt/automation doctrine + end-session checklist/hook
   spec + the status-protocol template above. The blind-spot critic's findings. ONE
   prioritized **blast-radius target list → batch-11.**
2. **Co-batching analysis** for batch-11 — what the audit's targets, the `check_backlog_stale`
   registry, and the deferred Enforcement-Lifecycle core (S-70+S-72) can share vs must
   sequence (file-disjointness permitting). Max stream parallelism.
3. Commit to the branch; **do not merge, do not push.** The Manager reviews + drafts batch-11.

## 7. Where to look

Stores/histories to audit: `CLAUDE.md`, the memory dir + `MEMORY.md`, `.claude/ROBOT.md`,
`.claude/AUTONOMOUS-DEFAULTS.md`, `docs/BACKLOG.md`, `docs/MERGE-LOG.md`,
`docs/MANAGER-HANDOFF.md` (+ its full git history — Track B's primary source),
`.claude/run-archive/`, the `.claude/waves/` launch-prompt archive, `docs/MAP.md`,
`docs/adr/`, `docs/WALK-BACK-LOG.md`, `tools/ms-enforce` + the gate set, the file-size
ratchet (`tools/check_linecount.py` + `.linecount-baseline.json`), `tools/sanctioned/`, the
slop-process docs repo (`/home/stack/v5`), git history.
Mechanisms to study/extend: the SLOP AI Agent reality-reconciliation (the GROUND model), the
SessionStart 3-repo-sync hook (`/home/stack/v5/docs/tools/check_push_status.sh`, now with
Ring-0 detection), the S-75 gap-discovery ritual (once landed), the batch-7 wave-authoring
tooling (for dogfooding the batch-11 wave files this audit's findings will inform).

## 8. Known limit (state it honestly)

No audit eliminates friction-surfaced gaps; it shrinks them and converts an infinite
friction-trickle into a periodic, bounded, prioritized inventory the system owns. The
coverage registry and the Handoff Protocol are themselves things that can rot — so the report
must name each new mechanism's failure mode and route its own staleness into the S-75 ritual.
