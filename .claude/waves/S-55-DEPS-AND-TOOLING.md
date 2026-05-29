# S-55-DEPS-AND-TOOLING — Follow-up cleanup from Round 1/2

## Goal
Three independent follow-up items from the first two Robot rounds: the bcrypt
cap deferred by S-46, the rules-to-tests migration enabled by S-50's audit, and
the wave-file preflight tool that would have caught the S-47 inverted-labels
bug.

## Context
- S-46 Stream A added `bcrypt>=2.10,<5` (cap was a safety default per
  AUTONOMOUS-DEFAULTS major-bump rule). Need to review bcrypt 5.x changelog
  against our usage and lift the cap if safe.
- S-50 Stream C produced `docs/RULES-TO-TESTS-AUDIT.md` with ~47 candidate
  rules, ~N marked YES (mechanizable). Batch 1 picks the highest-leverage
  YES rules and migrates them.
- S-47 wave file had inverted docker-compose labels. Stream C caught it by
  inspection. A preflight tool would catch this class of bug before dispatch.
- This wave fires concurrently with S-56 and S-57 from fresh Opus orchestrators
  per the Robot pattern. Coordinator = opus, subagents = sonnet.

## Rules to follow
- Authorized deletions section required for any file deletion (per
  AUTONOMOUS-DEFAULTS). Stream B's CLAUDE.md prose removals need explicit
  listing.
- bcrypt 5.x review (Stream A) is a JUDGMENT call: if review finds breaking
  API changes, leave the cap in place and write a decision file. Don't force
  the cap removal.

## Authorized deletions

Stream B may delete (after migrating each rule to a test):
- Sections of `CLAUDE.md` corresponding to rules that have been replaced by a
  test or ms-enforce check. Each removed section MUST cite the test/check
  that replaces it in the commit message.

## Parallelization

**Models:** coordinator = **opus**, subagents = **sonnet**. Three parallel streams.

| Stream | Subagent type | Scope |
|---|---|---|
| A — bcrypt cap review | `general-purpose` in worktree | `requirements.txt`, `pyproject.toml`, `uv.lock`, bcrypt usage in `backend/platform/wizard.py` + tests |
| B — rules-to-tests batch 1 | `general-purpose` in worktree | `docs/RULES-TO-TESTS-AUDIT.md` (read only), `tests/test_*.py` (new), `ms-enforce` (new checks), `CLAUDE.md` (rule prose removals) |
| C — wave-file preflight tool | `general-purpose` in worktree | `tools/validate-wave-file.py` (new), `ms-enforce` (register check), `tests/test_validate_wave_file.py` (new) |

## Deliverables

### Stream A — bcrypt cap review
1. Read bcrypt 5.x changelog (https://github.com/pyca/bcrypt/blob/main/CHANGELOG.rst — WebFetch).
2. Grep SLOP's usage: `hashpw`, `checkpw`, `gensalt` calls.
3. If 5.x changes don't affect SLOP's usage: remove the `<5` cap, regen `uv.lock`, verify tests pass, commit.
4. If 5.x has breaking changes: leave cap, write decision file documenting the breakage + recommended workaround, commit only the doc.

### Stream B — rules-to-tests batch 1
1. Read `docs/RULES-TO-TESTS-AUDIT.md`. List rules marked YES (mechanizable).
2. Pick the **top 3-5 by leverage** (rules most likely to break silently if violated).
3. For each picked rule:
   - Implement as a pytest test OR a new ms-enforce check (whichever fits the rule's nature).
   - Remove the corresponding prose from `CLAUDE.md`.
   - Commit message format: `feat(test): migrate '<rule>' from CLAUDE.md to tests/<file>::<test>`.
4. Update `docs/RULES-TO-TESTS-AUDIT.md` to mark migrated rules with ✓.

### Stream C — wave-file preflight tool
1. Build `tools/validate-wave-file.py` (pure stdlib).
2. Behavior:
   - Argument: path to a wave file.
   - For every file path mentioned in the wave file, verify the path exists.
   - For every named tool/command, verify it exists or is on $PATH (rough heuristic).
   - For every named inbound-reference claim ("X is referenced N times"), re-run the grep and verify count.
   - Exit 1 if any claim doesn't match reality; print the mismatches.
3. Wire into `ms-enforce` as a warn-only TIER_1 check that runs against every wave file under `.claude/waves/`.
4. Tests in `tests/test_validate_wave_file.py`.

## Verification
1. Stream A: `python3 -m pytest tests/test_wizard.py -k bcrypt -v` (or whatever covers bcrypt) — pass.
2. Stream B: `python3 -m pytest tests/test_<new_test>.py -v` — pass. CLAUDE.md is shorter by the migrated rules' word count. `docs/RULES-TO-TESTS-AUDIT.md` has ✓ marks on migrated rows.
3. Stream C: `python3 tools/validate-wave-file.py .claude/waves/S-55-DEPS-AND-TOOLING.md` exits 0. Throwaway: create a wave file with a fake file path, run validator, see failure.
4. `python3 ms-enforce` exits 0.

## Out of scope
- TIER_2 test failures (9 FSM + 3 snapshot) — owned by S-57
- Doctrine + audit work (Robot retro, settings hygiene, doc audit) — owned by S-56
- Permanent Robot test battery — owned by S-56

## Robot mode (autonomous execution)

When launched with "in Robot mode" prefix, operate under `.claude/ROBOT.md`
doctrine v3 (orchestrator-as-coordinator, subagent preamble with venv symlink,
Bash heredoc for new files, never AskUserQuestion, never git push, merge to
`wave/S-55-deps-and-tooling` not main).

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-55-DEPS-AND-TOOLING.md as orchestrator.`
