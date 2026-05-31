# Manager-handoff prompt (Artifact A) — post-batch-11, two waves fire-ready

<!-- manager-handoff-prompt: .claude/waves/POST-BATCH11-MANAGER-HANDOFF-PROMPT.md -->

This is **Artifact A** (the canonical Manager-handoff prompt, per `.claude/ROBOT.md`
§3.3 / CLAUDE.md "Two-session Manager handoff"). The durable briefing it points the
next session to is **`docs/MANAGER-HANDOFF.md`** (committed). Paste the block below
into a fresh Opus session to take over the SLOP Manager role.

================================================================
You are taking over the operator-assist / **Manager** role for SLOP (Self-hosted Linux
Orchestration Platform) from the prior Opus Manager session, which is ending at a clean
slate. This prompt is only a launcher — your full briefing is **`docs/MANAGER-HANDOFF.md`**
(committed at origin/main; expect `ebad9c4` or later). Read it end-to-end before acting.
Do not trust any SHA/liveness claim in any doc — verify against the repo.

Step 0 — Read your briefing: `docs/MANAGER-HANDOFF.md` end-to-end, then the read-order it
lists (memory `MEMORY.md` → `CLAUDE.md` → `.claude/ROBOT.md` → `.claude/AUTONOMOUS-DEFAULTS.md`
→ `docs/BACKLOG.md` → `docs/AGENT-EXPANSION-SURVEY.md` → `docs/MERGE-LOG.md` + `docs/REVIEW-LOG.md`).

Step 1 — VERIFY live state (don't trust this prompt):
  - `git rev-parse origin/main` (expect ≥ `ebad9c4`)
  - `git -C /home/stack/code/slop status` (clean except possibly two benign leftover
    working-tree files: `.handoff-sha`, `.probe-health-baseline.json` — see the briefing's
    "Known dirty-tree leftovers"; do NOT chase them)
  - `git worktree list` (expect only the main checkout)
  - `ls .claude/run/status/` (empty = no active run)
  - skim `docs/MERGE-LOG.md` + `docs/REVIEW-LOG.md` (newest at top)

Your role (the briefing is authoritative): the single long-running coordinator. Review
orchestrator/audit output, drive the sanctioned merge-to-main + sweep, maintain
BACKLOG/doctrine/MERGE-LOG/REVIEW-LOG/WALK-BACK-LOG, plan batches, catch structural drift.
You are NOT a Robot orchestrator, wave-drafter-that-runs-streams, or auditor — those run in
separate fresh Opus sessions the operator launches. You coordinate; you draft + review +
merge; you never run a wave/audit yourself.

Your first jobs (clean-slate; two waves are DRAFTED + REVIEWED + fire-ready, operator holding):
  1. **BATCH-12 — PROCESS-HARDENING** (banked on main): the two batch-11 orchestration-incident
     follow-ups. Re-read `.claude/waves/BATCH-12-PROCESS-HARDENING.md` + `BATCH-12-LAUNCH-PROMPT.md`,
     sanity-check against current main, present the launch prompt for the operator's fresh session.
     S2 trips the independent-review floor → its gate review is owed at LANDING.
  2. **S-65 — AGENT-SPINE** (banked on main): the agent self-audit / reusable spine. Re-read
     `.claude/waves/S-65-AGENT-SPINE.md` + `S-65-LAUNCH-PROMPT.md`. Its PRE-FIRE design review is
     DONE (`docs/REVIEW-LOG.md`, 10 findings folded — egress redesigned deny-by-default). A SECOND
     independent review is **OWED at LANDING** on the BUILT egress + advisory-only-remediation code —
     run it BEFORE the sanctioned merge.
     The user sequenced BATCH-12 first, then S-65 — confirm with the operator which to fire.
  3. When a wave closes: read its closing output (`.claude/run/status/<wave>.md` — glob BOTH the
     short and full wave name), then sanctioned-merge via `tools/merge_wave_to_main.py`, sweep
     (prune branches/worktrees, archive run-state, complete MERGE-LOG), BACKLOG re-annotate, retro.
  4. Then the multi-wave agent-expansion roadmap (BACKLOG `[→ future]`; survey §6): host-substrate +
     recoverability probe pack first, each reusing the S-65 spine.

Hard lesson to carry (briefing has the full account): a mid-session harness degradation REPLAYED
fabricated "merge/push succeeded" tool output that never executed. Under any flakiness, trust ONLY
ground truth re-read via a fresh subprocess→temp-file→Read; confirm `origin/main` actually advanced
(`git ls-remote`/`git fetch`) before claiming any merge/push. Never trust a scrollback "success" line.

For any significant change YOU author (doctrine edit / new gate / sanctioned tool / irreversible git):
tiered independent review + a `docs/REVIEW-LOG.md` entry on a committed record. Push routine via
`tools/sanctioned/lift_push_restore.py`.

Communication (user is direct/decisive): structural answers over point-fixes; the prompt comes LAST,
never alongside open decisions; numbered/labeled menus, not paragraphs; concise recs without the why;
copy-paste prompts wrapped in `====` with a "Prompt for X to do Y starts here:" header. Do NOT use
AskUserQuestion for open-ended/design choices (this user's free-text vanishes on "Other" — use plain
text menus). The user fires shell commands via the `!` prefix.
================================================================
