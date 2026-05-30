# S-74-DEPLOY-HARDENING — orchestrator launch prompt (batch-9)

Paste the block below into a **fresh Opus session**. Base SHA is current `origin/main`
at write time; the orchestrator re-confirms at startup. Fire this FIRST (batch-9);
S-75 (batch-10) only fires after this has landed on main.

================================================================
in Robot mode: you are the orchestrator for the SLOP batch-9 run —
ONE wave, 4 independent streams to fire concurrently.

main is at origin/main commit 55fa798. Re-confirm with
`git rev-parse origin/main` at startup and rebase the wave branch if
main has advanced.

Wave to handle:
  .claude/waves/S-74-DEPLOY-HARDENING.md

Follow the standard orchestrator startup sequence in .claude/ROBOT.md:
  1. Confirm the base SHA above.
  2. Run `python3 tools/preflight_wave.py .claude/waves/S-74-DEPLOY-HARDENING.md`.
     It scores High — expect a fact-check subagent dispatch and a
     DISPATCH-OK verdict before you dispatch streams. BLOCK on any FALSE claim.
  3. Dispatch all 4 streams (A, B, C, D) concurrently as `general-purpose`
     subagents in git worktrees, using the per-stream Model column
     (A opus, B sonnet, C opus, D sonnet; coordinator opus).
  4. Inject the subagent preamble (.claude/ROBOT.md) verbatim at the top
     of every stream prompt — including the "pin git to your worktree
     with git -C <worktree>" rule.
  5. Honor the PINNED contracts: the `tools/deploy_lib.sh` interface
     (detect_service_user / build_home / normalize_ownership), the
     canonical port-var name (B's deliverable), and C's operator-env
     contract (the .env-vs-systemd decision that A/B/D consume).
  6. Merge each stream into wave/S-74-deploy-hardening in a dedicated
     .claude/worktrees/merge-S-74 worktree (detached HEAD), never main.
     Resolve any additive conflict on shared doc files keep-both
     (NEVER merge=union) and log an S-74-MERGE-N.md decision.
  7. Maintain .claude/run/status/S-74.md continuously; do NOT push, do
     NOT merge to main — the operator reviews + merges after.

Verification note: ms-update/deploy.sh are shell/install scripts with no
CI against a real server — verify via shellcheck + logic review + guarded
dry-run + the targeted unit tests the wave defines (state this limit).

Do not call AskUserQuestion. Apply .claude/AUTONOMOUS-DEFAULTS.md for any
decision and log it. On hard blocker, write
.claude/run/blockers/S-74-<stream>.md and halt only that stream.
================================================================
