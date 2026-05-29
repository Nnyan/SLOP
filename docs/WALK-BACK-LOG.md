# Walk-Back Log

When a doctrine rule is walked back (removed or softened), this log captures
the meta-thinking that prevents leaving orphaned needs unaddressed.

## Why this file exists

Every rule encodes a NEED. When the rule is walked back, the need doesn't
disappear — it becomes orphaned. Orphaned needs re-surface later as
individual point-issues, hit one at a time. Walk-backs without closing the
loop on the underlying need are "fixing the symptom of the symptom."

This log forces the meta-thinking BEFORE the walk-back lands. Every entry
answers four questions:

1. **What was the rule preventing?** (The underlying need.)
2. **Why are we walking it back?** (What specific case made it wrong.)
3. **What's the new mechanism for the underlying need?** (Doctrine, tool,
   process, or explicit accept-the-debt.)
4. **What's the failure mode of the new mechanism?** (When does it stop
   working; what re-triggers consideration.)

## Entry format

```markdown
## YYYY-MM-DD — <rule short name>

- **Rule walked back:** <name and brief description>
- **Where it lived:** <ROBOT.md / AUTONOMOUS-DEFAULTS.md / CLAUDE.md / settings.local.json / etc.>
- **What it was preventing:** <the underlying need; what would happen without the rule>
- **Why walked back:** <the specific case or pattern that made the rule wrong>
- **New mechanism for the underlying need:** <what now handles the need; concrete>
- **Failure mode of new mechanism:** <when does it stop working; what re-triggers consideration>
- **Linked walk-back commits:** <SHA or PR link>
- **Linked replacement-mechanism commits:** <SHA or PR link>
```

## Enforcement

`ms-enforce check_walkback_log` (TIER_1, warn-only initially) flags any
commit modifying `.claude/ROBOT.md`, `.claude/AUTONOMOUS-DEFAULTS.md`, or
`CLAUDE.md` that REMOVES ≥3 lines without referencing a WALK-BACK-LOG entry
in the commit message body. The warn-only severity will graduate to TIER_2
(fail) after the aging-policy mechanism (planned S-70) ships.

The check is intentionally lenient on additions and small tweaks — only
substantive rule removals require an entry.

## Connection to other doctrine

- `ROBOT.md § "BACKLOG triage discipline"` — addresses the orphaned-need
  pattern at the BACKLOG level (every item must be `[→ S-NN]` | `[park]` |
  `[x]` | `[—]`, never bare `[ ]`).
- `AUTONOMOUS-DEFAULTS § "Cleanup waves..."` — names the dedicated-cleanup-wave
  pattern as the structural answer to the inverse of the fix-all-failures rule.
- `docs/BACKLOG.md` — open items must have explicit fold-in targets, not
  rot in `[ ]` limbo.

The walk-back log is the meta-meta layer above these: when a NEW rule gets
walked back, the log captures the reasoning so future readers can verify the
orphaned need was actually addressed.

---

## 2026-05-29 — "fix-all-failures" rule (retroactive entry)

- **Rule walked back:** "Fix every pre-existing test or tool failure encountered in a session — pytest, ms-enforce, linters, type checkers. Do not skip, defer, or label them 'pre-existing and unrelated.'"
- **Where it lived:** Originally proposed as a repo-local memory entry (feedback_fix_all_failures.md; path never loaded because Claude Code auto-memory reads from `~/.claude/projects/`, not in-repo paths). Then promoted to `CLAUDE.md` (commit `37ea3d2`, 2026-05-27). Reverted (commit `d56c1d9`, 2026-05-27).
- **What it was preventing:** Tests, type errors, and lint failures accumulating on `main` over time. The intent was: every session ends with a clean repo, no debt. Without the rule, accumulated breakage becomes invisible until it blocks something specific (which is what happened with the 12 TIER_2 failures S-57 had to fix, and the 441 TestClient failures S-58 had to fix).
- **Why walked back:** The rule expanded EVERY wave's scope to "the wave's deliverables + fix all pre-existing failures encountered." Focused waves became unbounded. Operator pushback: "while doing X, also fix all of Y and Z" balloons effort and obscures whether the focused work itself is sound.
- **New mechanism for the underlying need:** **Dedicated cleanup waves.** S-57 was the prototype (12 TIER_2 failures fixed in a wave whose ONLY scope was those fixes). S-58 extended the pattern (417 TestClient failures). S-66 and S-67 (drafted 2026-05-29) continue it. The doctrine is now enshrined in `ROBOT.md § "BACKLOG triage discipline"`: "Cleanup waves are how pre-existing failures get fixed. The no-fix-all rule applies to FOCUSED waves doing other work. It does NOT mean we never fix pre-existing failures."
- **Failure mode of new mechanism:** Stops working if (a) cleanup waves stop being drafted when BACKLOG accumulates ≥10 items in a category, OR (b) the BACKLOG triage discipline lapses and items rot in bare `[ ]` for >14 days. The `check_backlog_coverage` ms-enforce check (warn-only) is the early-warning gate.
- **Linked walk-back commits:** `37ea3d2` (add) → `d56c1d9` (revert)
- **Linked replacement-mechanism commits:** `4af5f0d` (BACKLOG triage discipline + S-66/S-67 drafted + re-annotation pass)
