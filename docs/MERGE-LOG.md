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
- **Pre-merge main HEAD:** `ed7e130` (access-requests: log + apply .claude/waves and .claude/run write allows)
- **Branches merged (in order):**
  1. `chore/waves-s60-62` (fast-forward) — wave spec commits from agent-review session
  2. `wave/S-60-agent-fix-safety` → merge commit `<TBD — fill in after merge>`
  3. `wave/S-61-agent-anonymization` → merge commit `<TBD>`
  4. `wave/S-62-ms-router` → merge commit `<TBD>`
  5. `wave/S-58-testclient-sweep` → merge commit `<TBD>` (417 TestClient failures fixed)
- **Post-merge main HEAD:** `<TBD>`
- **Pushed to origin:** `<TBD>`
- **Pre-flight checks run:**
  - Wave verification per orchestrators (S-58: full suite 450→43; S-60/61/62: orchestrator review verdict ✅)
  - ms-enforce status: pre-existing 12 TIER_2 failures fixed by S-58; expect TIER_2 GREEN post-merge
  - Track-status warnings on 3 wave files (OPTIONAL-FILE-SIZE-REMEDIATION, S-46-PIN-RELAX, S-59-ACCESS-REQUESTS-PROCESSOR — pre-existing/known, not blocking)
- **Notes:**
  - First entry under the new merge-log convention (created same day, 2026-05-29).
  - Operator-manual method used because `tools/merge-wave-to-main.py` doesn't exist yet (S-59 Stream D scope).
  - Stream C snapshot-regression lesson from S-58 captured for AUTONOMOUS-DEFAULTS doctrine update (same batch).
