# SLOP Manager Session — Handoff

You are taking over the **operator-assist / Manager** role for SLOP (Self-hosted Linux Orchestration Platform) from the prior long-running Opus Manager session. This document is your full briefing. Read it end-to-end before doing anything else.

## Your role

You are the single long-running operator-assist session — the coordinator who:
- Coordinates with the user (Nnyan) on SLOP.
- Reviews orchestrator/audit output after each Robot batch/wave.
- Drives the sanctioned merge-to-main + sweep when a wave closes.
- Maintains BACKLOG / doctrine / MERGE-LOG / REVIEW-LOG / WALK-BACK-LOG.
- Plans batches; catches structural drift (the user values structural answers over point-fixes).

You are **NOT** a Robot orchestrator, a wave-drafter that runs streams, or an auditor — those run in **separate fresh Opus sessions the operator launches**. You coordinate; you draft + review + merge; you never run a wave/audit yourself.

## Current state (2026-05-30 — batch-11 LANDED; two waves DRAFTED+REVIEWED+fire-ready; HELD for operator to fire)

> **Quiescent handoff — no active run, no in-flight subagent.** Two waves are drafted, reviewed, and banked on main, awaiting the operator's decision to fire. **VERIFY live state before acting** (do not trust the SHAs below — they are stale by read-time):
> - `git rev-parse origin/main` — expect **`d4b7074`** or later.
> - `git -C /home/stack/code/slop status` — expect clean except possibly two benign leftover working-tree files (see "Known dirty-tree leftovers").
> - `git worktree list` — expect only the main checkout.
> - `ls .claude/run/status/` — empty = no active wave.
> - Read `docs/MERGE-LOG.md` + `docs/REVIEW-LOG.md` (newest at top) for what actually landed.

### What landed this session (all on origin/main, verified pushed)
- **batch-11 ENFORCEMENT-LIFECYCLE — FULLY LANDED + swept + pushed** (merge `bf16d16`, sweep `77656d5`). 11 streams; the GROUND-gate brownout machinery (S1 aging engine + open-seam probe registry `docs/PROBE-REGISTRY.md` / `tools/probe_registry.json` / `tools/audit_probe_aging.py`), cross-repo triage registry, park-triad gate, session hooks, status protocol + `.handoff-sha` auto-stamp, sanctioned-channel GROUND leg + single-entity-hardcode scanner, walkback/independent-review artifact legs, ratchet aperture + provenance, point coverage, run-archive drain, and the F10 two-session Manager-handoff-artifact contract + `check_manager_handoff_artifacts` gate. **All gates TIER_1 warn-only.** Memory: `project-batch11-landed`.
- **`fix(winddown)` `2877d58`** — the advisory Stop hook (`tools/check_session_winddown.py`, landed by batch-11 S4) was returning **exit 1**, which the Claude Code Stop-hook contract treats as a non-blocking *error* (`"Stop hook error: Failed with non-blocking status code: No stderr output"`) every turn. An advisory hook must **exit 0**; the report on stdout IS the re-prompt. One-line fix. If you still see that error, the session is reading an OLD settings/branch — verify `git rev-parse origin/main` ≥ `2877d58`.

### Two waves DRAFTED + REVIEWED + FIRE-READY (operator holding the fire)
1. **BATCH-12 — PROCESS-HARDENING** (`b9501ae`). The two batch-11 orchestration-incident follow-ups (BACKLOG `:64`, `:65`):
   - **S1 (sonnet):** `lift_push_restore.py` `try/finally` restore + `SANCTIONED-CHANNELS.md` registry row → brings it under `check_sanctioned_ground` (whose `restore_is_guaranteed` leg then verifies the finally) + probe row + red-path test.
   - **S2 (opus):** new `tools/audit_canonical_checkout.py` + `check_canonical_checkout` (TIER_1 warn-only) GROUND-detecting the canonical checkout sitting on a `wave/*` branch, + `.claude/ROBOT.md` doctrine (mandatory `isolation:"worktree"` / no checkout-borrow) + four-question rationale + REVIEW-LOG entry + probe row + red-path test.
   - High-tier (`wave_complexity` 9); validates clean; S1 ∥ S2 (only `probe_registry.json` shared, append-only). **S2 trips the independent-review floor → owed at landing** (the design is small/disjoint; no pre-fire design review was run — your call whether to add one).
   - Files: `.claude/waves/BATCH-12-PROCESS-HARDENING.md` + `BATCH-12-LAUNCH-PROMPT.md`.
2. **S-65 — AGENT-SPINE** (`b5419dd` draft → `8a0432b`/`ebad9c4` review fold). The agent self-audit / reusable reconcile→interpret→remediate spine (BACKLOG `:67`; survey `docs/AGENT-EXPANSION-SURVEY.md`). 4 streams: S1 spine contract + GROUND self-audit reconciler (PINNED producer) · S2 deny-by-default egress boundary · S3 ms-router advisory review (XREF only) · S4 advisory-only remediation gate (no auto-fix wired). Runtime-only (two-owner firewall preserved). High-tier (`wave_complexity` 25); validates clean.
   - **Pre-fire independent review DONE** (`docs/REVIEW-LOG.md`, 2026-05-30; fresh-Opus adversarial, charged at egress + advisory-only-remediation): verdict NEEDS-CHANGES, **all 10 findings (R1–R10) accepted + folded in.** The catch (R1): egress was redesigned **deny-by-default (allowlisted structured findings)** because `scrub()` is best-effort regex that leaks ≥6 identifier classes (verified live). Advisory-only (R6) and LLM-non-authority (R8) made **structural**.
   - **STILL OWED before merge:** a SECOND independent review at **landing**, on the BUILT egress + remediation code (the pre-fire design review does NOT discharge it).
   - Files: `.claude/waves/S-65-AGENT-SPINE.md` + `S-65-LAUNCH-PROMPT.md`.

### Your first jobs (clean-slate)
0. **VERIFY state** (the step-0 gate above). Do not trust this doc's SHAs.
1. **Present BATCH-12 and/or S-65 launch prompts** for the operator to fire in fresh sessions (the operator runs orchestrators; you coordinate). The user sequenced: process follow-ups (BATCH-12) first, then S-65. Confirm which to fire.
2. **When a wave closes:** read its closing output (`.claude/run/status/<wave>.md` — glob BOTH short and full names), then sanctioned-merge via `tools/merge_wave_to_main.py`, sweep, BACKLOG re-annotate, retro. For S-65 specifically: **run the owed landing review (egress + advisory-only-remediation) BEFORE the merge.** For BATCH-12: run S2's owed gate review at landing.
3. **Then:** the multi-wave **agent-expansion roadmap** (BACKLOG `[→ future]`; survey §6): first the read-only host-substrate + recoverability probe pack (each reusing the S-65 spine), with the global autofix circuit-breaker riding WITH the S-64 lineage.

## Known dirty-tree leftovers (benign — do NOT chase)
Two files have shown as modified-but-uncommitted across sessions; both are intentional/regenerating, NOT work-in-progress:
- **`.handoff-sha`** — refreshed each handoff; committing it churns the self-reference (the file can't durably hold its own commit's SHA). S5's auto-stamp in `merge_wave_to_main.py` handles it at the next merge. This handoff DID commit a refresh; if you see it dirty again it's the post-commit lag, expected.
- **`.probe-health-baseline.json`** — regenerated every time `audit_probe_aging.py` / the winddown hook runs (registers new probes, bumps `generated_at`). A probe-run artifact, not a change you authored. Leave it unless a wave deliberately ratchets it.

## ⚠️ Hard-won lesson this session — trust ground truth, not scrollback
A mid-session **harness degradation** replayed FABRICATED tool output: a whole "merge succeeded / branches deleted / pushed" sequence was reported that **never executed** (triggered when a `head` permission-denial cancelled a queued parallel batch). The prior Manager relayed it as a completed landing — it was false; verified via fresh reads (main was still at the pre-merge SHA). **Discipline:** under any flakiness, trust ONLY ground truth re-read via a fresh `subprocess → temp-file → Read`; confirm `origin/main` actually advanced (`git ls-remote` / `git fetch`) before claiming any merge/push succeeded; never trust a tool "success" line echoed in scrollback. Memory: `project-batch11-landed` records the incident.

## Read order (after this file)
1. **Memory** — `~/.claude/projects/-home-stack-code-slop/memory/MEMORY.md` (auto-loaded). Key recent: `project-batch11-landed`, `feedback-handoff-no-volatile-state`, `feedback-prompt-and-menu-formatting`, `feedback-manager-role-handoff` (points here), `project-agent-expansion-scope`, `project-rocinante-deploy`, `feedback-askuserquestion-text-loss`.
2. **CLAUDE.md** (auto-loaded) — the keystones: Knowledge-Lifecycle (GROUND/XREF/INDETERMINATE/UNPROBED + two-owner firewall), Reuse-and-blast-radius, Independent review, No-phantom-owners, BACKLOG triage, one-orchestrator-per-batch.
3. **`.claude/ROBOT.md`** — orchestrator doctrine; §3.3 two-session handoff artifacts; §3.5 status protocol; §3.6 prompt doctrine; subagent preamble.
4. **`.claude/AUTONOMOUS-DEFAULTS.md`** — decision register.
5. **`docs/BACKLOG.md`** — every item triaged; the `[→ next agent/process wave]` (BATCH-12) + `[→ next agent wave — self-audit/spine]` (S-65) + `[→ future — agent-expansion roadmap]` entries + the scrub-hardening item (S-65 review R1).
6. **`docs/AGENT-EXPANSION-SURVEY.md`** — the spine shape (§0) + OVERREACH guardrails (§4) + roadmap (§6).
7. **`docs/MERGE-LOG.md`** + **`docs/REVIEW-LOG.md`** — audit trails (newest at top); the S-65 pre-fire review entry is the latest.
8. **`tools/merge_wave_to_main.py`** + **`tools/sanctioned/`** — the sanctioned merge + push channels (your primary handoff tools).

## Working patterns / discipline (condensed; full forms in ROBOT.md / CLAUDE.md)
- **Sanctioned channels:** merge → `tools/merge_wave_to_main.py`; routine push → `python3 tools/sanctioned/lift_push_restore.py [--repo PATH]` (UNAUDITED, no receipt-loop); audited one-off push → `robot_settings.py push-then-restore`. The `/tmp` helper is SUPERSEDED.
- **Cross-session HEAD safety:** the canonical checkout `/home/stack/code/slop` is shared. While ANY orchestrator/drafter/audit session is live, do NO main-side git ops there — wait, or isolate in `/tmp/slop-manager`. After such a session, your FIRST action is `git switch main` + verify. (BATCH-12 S2 builds the GROUND red-signal for exactly this class.)
- **Handoff hygiene:** state durable facts + the verification the next session must RUN — never another session's volatile liveness. The incoming session MUST read the waited-on session's closing output before acting (memory `feedback-handoff-no-volatile-state`).
- **Significant changes YOU author** (doctrine edit / new gate / sanctioned tool / irreversible git) → tiered independent review + a `docs/REVIEW-LOG.md` entry on a committed record.
- **Sensitive paths:** writes under `.claude/` prompt in acceptEdits (no silencing — documented `[—]`); prefer `docs/`, or Bash heredocs for new `.claude/` files. Multi-line commit messages: `git commit -F <file>`, never a `!`-prefixed heredoc.

## Communication with the user (direct, decisive)
- Structural answers over point-fixes. Concise recs without the "why".
- **The prompt comes LAST**, never alongside open decisions; menus are numbered/labeled lists, not paragraphs; copy-paste prompts wrapped in `====` with a "Prompt for X to do Y starts here:" header (memory `feedback-prompt-and-menu-formatting`). **When you hand off, surface the actual paste-block prompt in chat — do not merely write the artifact file** (this was the one miss this session).
- **Do NOT use AskUserQuestion for open-ended/design choices** — this user's free-text vanishes on "Other"; use plain numbered text menus (memory `feedback-askuserquestion-text-loss`).
- The user fires shell commands via the `!` prefix.

## This session's arc (2026-05-30, after the batch-11 landing)
Landed the winddown-hook fix → drafted+committed+pushed BATCH-12 (process follow-ups) → drafted+committed+pushed S-65 (agent spine) → ran the S-65 pre-fire adversarial review (NEEDS-CHANGES, 10 findings folded, REVIEW-LOG entry + scrub-hardening BACKLOG item) → this clean-slate Manager handoff. Nothing is fired; two waves sit fire-ready.

## Final notes
- VERIFY no other session owns the checkout before any main-side git op. Trust the audit trails (MERGE-LOG / REVIEW-LOG / BACKLOG / memory) but reconcile load-bearing facts against reality first — the whole-session lesson.
- When in doubt, ask the user one clarifying question rather than act wrong silently.

Good luck. Clean state, two fire-ready waves, a clear roadmap.

The canonical Manager-handoff prompt (artifact A) is `.claude/waves/POST-BATCH11-MANAGER-HANDOFF-PROMPT.md`.
