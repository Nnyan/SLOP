# Wave Merge Log

Audit trail for every wave-branch merge to `main`. Each entry records what was
merged, when, by whom (operator vs sanctioned tool), and the resulting state.

**Why this log exists:** the `git checkout main` / `git switch main` deny rules
in `.claude/settings.local.json` protect against runaway agents merging
unverified work to main during a wave. But post-wave merges are legitimate.
Today they happen via operator handoff; once S-59 Stream D ships, they happen
via `tools/merge-wave-to-main.py` (a sanctioned audited channel). Either way,
the merge is recorded here.

**Entry format:**

```markdown
## YYYY-MM-DD — <one-line summary>

- **Method:** operator-manual | tools/merge-wave-to-main.py
- **Operator/Caller:** <user name | agent session id>
- **Pre-merge main HEAD:** <SHA>
- **Branches merged (in order):**
  1. `<branch>` → merge commit `<SHA>`
  2. `<branch>` → merge commit `<SHA>`
  ...
- **Post-merge main HEAD:** <SHA>
- **Pushed to origin:** yes/no (origin SHA after push)
- **Pre-flight checks run:** ms-enforce (PASS/FAIL/skipped), test suite (count), wave status verification
- **Notes:** anything unusual — conflicts resolved, regressions caught, manual interventions
```

**Convention:** newest entries at the TOP. Prune entries older than 12 months
to `docs/MERGE-LOG-archive/<year>.md`; the git history is the long-term record.

**Review:** the operator-assist Claude session reviews entries on each batch
landing — flags anything anomalous (unexpected branches, missing pre-flight
checks, unverified merges).

---

## 2026-05-29 — Batch: S-58 + agent-review waves (S-60/S-61/S-62) + wave-spec commits

- **Method:** operator-manual (this batch predates the sanctioned merge tool — S-59 Stream D will ship it)
- **Operator/Caller:** Nnyan (running merges from terminal; assisted by this Claude session)
- **Pre-batch main HEAD:** `ed7e130` (access-requests: log + apply .claude/waves and .claude/run write allows)
- **Audit log introduction commit:** `b5f986d` (audit: introduce docs/MERGE-LOG.md) — pre-merge HEAD for the wave merges below
- **Branches merged (in order):**
  1. `chore/waves-s60-62` (no-ff) → merge commit `3b9232e` — wave spec commits from agent-review session
  2. `wave/S-60-agent-fix-safety` (no-ff) → merge commit `47631cf`
  3. `wave/S-61-agent-anonymization` (no-ff) → merge commit `c6546e3`
  4. `wave/S-62-ms-router` (no-ff) → merge commit `7bf7fbc`
  5. `wave/S-58-testclient-sweep` (no-ff) → merge commit `d13daf5` (417 TestClient failures fixed)
- **Post-merge main HEAD:** `d13daf5`
- **Pushed to origin:** YES — `origin/main` at `d13daf5` confirmed via `git push origin main` (188 objects, 74.60 KiB)
- **Pre-flight checks run:**
  - Wave verification per orchestrators (S-58: full suite 450→43; S-60/61/62: orchestrator review verdict ✅)
  - ms-enforce post-merge: ✓ All Core Rules satisfied (39s wall clock) — TIER_2 is green; S-57's 12 fixes plus S-58's 417 TestClient fixes brought the suite into compliance
  - Full pytest re-run skipped (orchestrators already verified; operator chose to trust the audit trail rather than re-run a 2400-test suite)
- **Notes:**
  - First entry under the new merge-log convention (created same day, 2026-05-29).
  - Operator-manual method used because `tools/merge-wave-to-main.py` doesn't exist yet (S-59 Stream D scope, in-flight).
  - `--ff-only` failed on first attempt (main had the docs/MERGE-LOG.md commit ahead of the wave branches' base); switched all merges to `--no-ff`. Wave-branch merges proceeded clean — no conflicts, the orchestrators' "additive ms-enforce + disjoint files" claim held.
  - Stream C snapshot-regression lesson from S-58 will be captured for AUTONOMOUS-DEFAULTS doctrine update in the next commit (same batch).
