# Contributing to Mediastack

This document covers the conventions that aren't already enforced by `ms-enforce`. For the full architectural rule set, see ms-enforce (run `python3 ms-enforce --list`).

## Pre-merge checklist

- [ ] `ms-enforce` (or `ms-enforce --fast` for pre-commit) passes locally. *(enforcement: `ms-enforce` is the gate itself; CI also runs it)*
- [ ] New behaviour has a test (Core Rule 2.5: regression test in the same commit as the bug fix; Core Rule 4.11: snapshot test for stable outputs). *(enforcement: Rule 4.11 by `ms-enforce check_snapshots`; Rule 2.5 [manual — "same commit as the fix" is a git-history invariant that cannot be statically checked without false positives])*
- [ ] `mypy --strict` clean for any backend file you touched (Core Rule 5.20). *(enforcement: `ms-enforce check_mypy`)*
- [ ] Commit subjects follow Conventional Commits 1.0 (Core Rule 7.1) — the commit-msg hook rejects malformed subjects. *(enforcement: `tools/commit_msg_hook.py` at commit time; `tests/test_commit_format.py` catches `--no-verify` bypass on next CI run)*
- [ ] If you introduced a new architectural constraint, codify it in `ms-coverage` as a rule entry (Core Rule 4.1). *(enforcement: `ms-enforce check_rule_contract` — ADR 0012 staged check via `ms-rule-contract --audit`)*
- [ ] Any pre-existing failing test is either fixed in this commit, or marked `pytest.mark.xfail(strict=True, reason='github.com/Nnyan/SLOP/issues/N')` with a GitHub issue created. *(enforcement: `ms-enforce check_stale_xfails` rejects xfails older than 30 days without an issue link)*
- [ ] Every new architectural constraint (ADR, Core Rule, checklist item) names its automated enforcement check or is explicitly tagged [manual] with a one-line rationale — bare intentions without enforcement are not mergeable. *(enforcement: `ms-enforce check_adr_enforcement` — accepts the `> Enforcement: [manual — ...]` or `> Enforcement: [automated — ...]` annotation in the ADR file as the matching signal)*

## Snapshot tests (Core Rule 4.11)

Outputs that downstream tools or operators depend on (CLI banners, machine-readable JSON, API response shapes) are pinned by `syrupy` snapshot tests in `tests/test_snapshots.py`. The committed snapshots live at `tests/__snapshots__/test_snapshots.ambr`.

### When a snapshot test fails

1. **Read the diff.** Snapshot failures show the old vs new output. If the change is unintended, fix the source.

2. **If the change is intentional, regenerate:**

    ```bash
    pytest tests/test_snapshots.py --snapshot-update
    ```

3. **Review the snapshot diff:**

    ```bash
    git diff tests/__snapshots__/
    ```

4. **Commit the snapshot update in the SAME commit as the source change** so reviewers see both halves of the contract together. A `feat(api):` that changes a response shape WITHOUT the matching snapshot update will be caught by CI (`ms-enforce` Tier 2).

### What gets a snapshot

In scope:
- API response shapes (frontend depends on stable keys)
- CLI banners and operator output
- Machine-readable JSON from `ms-*` tools
- Cross-session continuity outputs (e.g. `ms-status --handoff`)

Out of scope:
- Per-test outputs that vary by environment (use unit-test assertions instead)
- Compose fragment / manifest YAML (already covered by schema tests)
- Vue frontend visual rendering (would need Playwright + image diff; tracked separately)

See [`docs/cleanup/STEP_2_1_SNAPSHOT_STRATEGY.md`](docs/cleanup/STEP_2_1_SNAPSHOT_STRATEGY.md) for the full target list and rationale.

## Test independence (Core Rule 4.10 — pending; see step 1.5)

The CI workflow `.github/workflows/test-randomly.yml` runs the full test suite under a random shuffle on every push/PR (`--randomly-seed=${GITHUB_RUN_ID}`). New tests must pass under arbitrary order.

If you write a test that mutates module-level state (settings, globals, config singletons), pair it with an `autouse=True` per-function fixture that resets that state — see `tests/test_llm_diagnose_refactor.py::_reset_module_state` for the established pattern.

A backlog of pre-existing order-dependent tests is tracked in [`docs/TODO_2026_05_08_test_independence_backlog.md`](docs/TODO_2026_05_08_test_independence_backlog.md). The CI gate is informational (continue-on-error) until that backlog clears.

## Commit conventions (Core Rule 7.1)

Subjects follow Conventional Commits 1.0:

```
type(scope): subject ≤ 100 chars, no trailing period
```

Where:
- `type` ∈ feat | fix | refactor | perf | test | docs | chore
- `scope` is lowercase, underscores or hyphens (e.g. `api`, `health`, `manifests`)
- The commit-msg hook (`tools/commit_msg_hook.py`) rejects malformed subjects.
- `--no-verify` bypasses the hook but `tests/test_commit_format.py` catches the bypass on the next CI run.

`ms-changelog` regenerates `CHANGELOG.md` from the trailing `git log` since the cutoff SHA. Run it on demand; do not hand-edit CHANGELOG.md.

## Architecture Decision Records (Core Rule 4.15)

Architectural decisions that constrain the codebase live in `docs/adr/` as numbered Markdown files. The format is Context / Decision / Consequences / Status — see `docs/adr/template.md`. Existing examples:

- [`0001-database-migrations.md`](docs/adr/0001-database-migrations.md) — custom numbered-file migrations vs Alembic
- [`0002-mocking-policy.md`](docs/adr/0002-mocking-policy.md) — system boundary vs project boundary mocking
- [`0003-structured-logging-correlation-ids.md`](docs/adr/0003-structured-logging-correlation-ids.md) — structlog + ProcessorFormatter
- [`0004-rate-limiting-tiers.md`](docs/adr/0004-rate-limiting-tiers.md) — slowapi tier definitions

When you make an architectural decision (library choice, threshold, exception clause, enforcement mechanism), write an ADR in the same PR as the implementation. The ADR doesn't replace strategy docs (`docs/cleanup/STEP_*_STRATEGY.md`) — strategy docs describe HOW to implement; ADRs describe WHY this approach was chosen, durably.

ADR numbers are immutable once accepted. If a decision is later superseded, the old ADR stays in the directory with its `Status:` updated to `Superseded` and a `Supersedes:` link in the new ADR.

`tests/test_adr_discipline.py` enforces the convention — sequential numbering, four required sections, valid status value.

## Working with the cleanup steps

Cleanup planning and step sequencing are tracked in the private slop-process repo. Per-step strategy docs (`docs/cleanup/STEP_<N>_<NAME>_STRATEGY.md`) author OPUS-level decisions before SONNET-level implementation. When a step has both [OPUS] and [SONNET] sub-tasks, the OPUS strategy doc lands first.

The `ms-status` tool reports current step + sub-task progress. `ms-status --handoff` emits a session-start prompt that tells the next agent (human or otherwise) what to verify before assuming the previous session's claims.

## Agent handoff conventions

Cross-session work follows [`docs/HANDOFF_PROTOCOL.md`](docs/HANDOFF_PROTOCOL.md). The defining rule: *the new session does not trust prior summaries; it verifies via `git log`, `ms-enforce`, and `ms-coverage` directly.* This protects against drift in long, multi-session work threads.
