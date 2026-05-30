# S-75 KNOWLEDGE-LIFECYCLE — Robot orchestrator launch prompt

Hand this to a fresh **Opus orchestrator** (bypassPermissions / Robot mode) to run
batch-10. **Precondition: S-74-DEPLOY-HARDENING must already be merged to `main`**
(this wave has a hard cross-batch dependency on it — see the wave file's Cross-wave
deps). One orchestrator, one wave, all streams parallel.

============================================================================
Prompt for the S-75 Robot orchestrator to execute the Knowledge-Lifecycle wave starts here:
============================================================================

You are the **Opus orchestrator** for Robot batch-10, executing ONE wave:
`.claude/waves/S-75-KNOWLEDGE-LIFECYCLE.md`. Read it in full — it is your complete
spec. Read `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md` for the rationale behind every
constraint. Follow `.claude/ROBOT.md` and `.claude/AUTONOMOUS-DEFAULTS.md` doctrine.

**Before you dispatch — verify the precondition and pre-flight:**
1. Confirm S-74-DEPLOY-HARDENING is on `main`: `git -C <repo> log --oneline main | grep -i S-74`. If it is NOT merged, STOP and report — do not dispatch.
2. Confirm you are on a fresh wave branch off the current `main`.
3. Run `python3 tools/preflight_wave.py .claude/waves/S-75-KNOWLEDGE-LIFECYCLE.md`. It must print **DISPATCH-OK**. If BLOCKED, stop and surface the failing check. Then dispatch the one fact-check subagent the High tier requires (verify the wave's repo-claims against live tree state) before clearing dispatch.

**Dispatch (MAX parallelism):** spin up **5 `general-purpose` subagents, each in its
own git worktree**, and launch all 5 concurrently — there is no land-order dependency
between streams; they share only the four PINNED contracts (fixed text in the wave
file). Give each subagent its stream's Deliverables section verbatim plus the wave's
Rules and the PINNED contracts. Per-stream models (from the wave's Model column):
- **Stream A — opus** — runtime reality-emit (`backend/core/agent.py` + the PINNED RealityView schema). Runtime-only; it must NOT read docs.
- **Stream B — opus** — dev-time reconciler keystone (`slop-reality-probe`, `tools/audit_doc_reality.py` = `ms-enforce check_doc_reality`, session-start SSH). Owns the PINNED `[gap-discovery]` + verdict vocabulary.
- **Stream C — sonnet** — `tools/check_handoff_freshness.py` + run-archive promotion in `tools/merge_wave_to_main.py`.
- **Stream D — sonnet** — `tools/audit_fact_freshness.py` + `verify_probe` frontmatter + inline `<!-- verify: -->` annotations in `CLAUDE.md` "Project facts" ONLY.
- **Stream E — opus** — `docs/adr/0020-knowledge-lifecycle.md` + the reconciler-trust doctrine section in `CLAUDE.md` + the gap-discovery ritual in `.claude/AUTONOMOUS-DEFAULTS.md`. Owns the PINNED reconciler-trust vocabulary + the `CLAUDE.md` ownership split.

**Enforce the HARD rules while reviewing each merge:**
- **Two-owner firewall:** reject any A diff that reads docs; reject any B diff that embeds SLOP-runtime control logic.
- **GROUND-vs-XREF + no-silent-pass:** every new probe must emit `INDETERMINATE` (loud) when ground truth is unreachable — never `OK`; only physics-touching probes may say `verified`. Each verdict line must name the ground truth it touched.
- **All new gates warn-only (TIER_1)** with a documented promotion trigger.
- Additive only; `agent.py` stays under the 500-line cap; no test writes outside `tmp_path`.

**Merge order for the one shared file:** `CLAUDE.md` is touched by E (new doctrine
section) and D (inline annotations on different lines). Merge **E before D**; resolve
with the PINNED ownership split as authority. All other files are disjoint.

**Merge each stream** to the wave branch with `tools/merge_wave_to_main.py` (requires
status=COMPLETE, ms-enforce green, conflict-abort). After all 5 land, apply the
**one-line cross-repo addition** to `/home/stack/v5/docs/tools/check_push_status.sh`
(a new read-only `check_doc_reality` layer) directly — v5 is a separate repo, not
worktree-able.

**Acceptance before you call it done:** `ms-enforce` exits 0; the file-size ratchet
holds; every new gate exits 0 warn-only on the clean tree AND demonstrably goes red
on its seeded fixture (prove each green light can go red); all new unit tests pass.

**Do NOT push and do NOT merge to `main`.** Stop and hand back to the Manager with: a
per-stream summary, the `ms-enforce` result, the proof-of-red for each new gate, and
any PINNED-contract renegotiations that occurred.

============================================================================
Prompt ends here.
============================================================================
