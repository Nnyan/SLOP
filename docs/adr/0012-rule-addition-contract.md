# ADR 0012 — Rule-Addition Contract

- **Date:** 2026-05-10
- **Status:** Accepted
- **Deciders:** operator, Claude Code (v4.2 execution)

## Context

During the v4.1.0 cleanup arc, 5 drift incidents involved Core Rules added to `docs/CORE_RULES.md` without corresponding updates to one or more dependent locations (`ms-coverage` RULES list, version history table in Section 8, `data/coverage_map.json`, CLI snapshot). These were caught only at release-time audit (Findings 1–5 in `docs/cleanup/COMPLETION_AUDIT.md`).

A Core Rule addition is a multi-document state change. The dependent locations must all land in the same commit, or the system is in a partially-described state that `ms-enforce --list` will misreport.

This ADR follows the architectural pattern already used by the Refactoring Contract (Rule 2.10) and the Structural Anti-Pattern Checker (Rule 5.24): scan staged changes, identify structural triggers, require dependent companion changes, block at commit if missing. Rules are stored as data; additions to the contract are append-only.

## Scope

This ADR governs **rule additions only**. The following are explicitly out of scope and tracked as future work:

- **Rule deletion.** A separate Rule-Deletion Contract (to be assigned a future ADR when scheduled for implementation) will enforce the symmetric invariant: removing a heading from `CORE_RULES.md` requires removing the matching RULES entry, regenerating `coverage_map.json`, updating the snapshot, and recording the deletion in version history.
- **Rule renumbering.** Modelled as deletion + addition; will be handled once the deletion contract lands. In the interim, renumbering is detected as a *collision* at addition time (see "Collision detection" below) but its bookkeeping is not enforced end-to-end.
- **Rule splits and merges.** Modelled as combinations of deletion + addition; deferred with renumbering.
- **Prose-only edits to existing rules.** These do not change canonical ids and do not trigger this contract. Rule 5.8 (version history discipline) governs them independently.

This scoping is deliberate: addition is the highest-frequency operation and the source of all 5 observed drift incidents. Subsequent contracts will compose with this one rather than replace it.

## Decision

### Trigger

A Core Rule addition is detected when the **staged diff** contains either of:

1. A new heading line in `docs/CORE_RULES.md` matching `^### \d+\.\d+ ` at the start of an added line, **or**
2. A new RULES entry in `ms-coverage` (an added object containing an `"id":` field matching `\d+\.\d+`)

Either signal independently triggers the full contract check. Both directions are validated — neither alone is sufficient as the only trigger source — so doc-only additions (heading without registry entry) and registry-only additions (entry without heading) are both caught.

### Verification semantics

Trigger detection is **diff-based** (parses added lines from the staged diff).

Companion verification operates on the **staged tree state** of the affected files — i.e., the file contents as they would exist post-commit, not the raw diff hunks. This distinction matters because companions like `coverage_map.json` must be checked for *consistency with the new RULES list*, not merely for "the file was touched."

### Required companions

All of the following must hold in the staged tree for the contract to pass. Each row names the check, its enforcement level, and the rationale for that level.

| # | Companion | Check semantics | Enforcement | Rationale |
|---|---|---|---|---|
| C1 | `CORE_RULES.md` heading and `ms-coverage` RULES entry agree | For each newly-added rule id, the id appears as both a `### N.NN` heading in `CORE_RULES.md` and an `"id": "N.NN"` entry in the RULES list. The short title on the heading line and the `title` field of the RULES entry must agree byte-for-byte after trimming. | Hard block | Registry and doc are the same statement in two forms; one without the other is a partial rule. Title agreement prevents the silent-drift case where heading and registry refer to different prose. |
| C2 | Version history row added to Section 8 of `CORE_RULES.md` | The staged Section 8 table contains a new row whose rule-id cell matches the added id and whose date is today. | Hard block | Rule 5.8 requires version history on every change. Required for traceability across the v4.x arc. |
| C3 | `data/coverage_map.json` is consistent with the staged RULES list | Regenerate `coverage_map.json` in memory from the staged RULES list and byte-compare to the staged `coverage_map.json`. They must be identical. | Hard block | `coverage_map.json` is the input to `ms-enforce --list`. A stale or hand-edited map silently misreports the rule count. Pure presence-in-diff is too weak: an unrelated edit to the file would satisfy it. |
| C4 | `tests/__snapshots__/test_cli_snapshots.ambr` reflects the new state | The snapshot's rule-count value and rule-label list match what `ms-enforce --list` would emit given the staged `coverage_map.json`. | Hard block | Rule 4.11 (Snapshot Discipline). CI will fail on the next test run if this diverges; better to catch at commit. Same presence-vs-consistency reasoning as C3. |
| C5 | `test_fn` named in the RULES entry exists in `test_file` | The function name in the entry's `test_fn` field is defined (any signature) in the file named by `test_file`, resolved relative to repo root. | Warn only | Stubs are acceptable at addition time; the test is often generated by `ms-testgen` in a follow-up step. Hard-blocking on test existence would break the plan-then-implement pattern this project uses. The warning surfaces the gap so it isn't forgotten. |

### Collision detection (side effect)

The contract additionally detects rule-id collisions as a side effect of C1: if the staged `CORE_RULES.md` contains two `### N.NN` headings with the same id, or the staged RULES list has two entries with the same `"id"`, the check hard-blocks with a collision diagnostic. This is not a separately-configured check; it falls out of the uniqueness requirement implicit in C1. Observed during v4.2 plan authoring when proposed 5.19/5.20/5.21 collided with existing rules.

### Audit mode

`ms-rule-contract --audit` scans the full repo state (no staging) and verifies five invariants:

1. Every RULES entry in `ms-coverage` has a matching heading in `CORE_RULES.md` (orphan check).
2. `coverage_map.json` has a node for every numeric RULES entry.
3. The snapshot rule count matches the coverage_map rule count.
4. Every `test_fn` named in the RULES list is defined in its `test_file`.
5. Every numeric rule has a version history row in Section 8 of `CORE_RULES.md`.

**Scope Note:** INV-1 as originally specified (every `### N.NN` heading has a matching RULES entry) collapses to INV-2's check under the N.NN scoping decided in this ADR. Without a registry distinguishing "headings under this contract" from legacy headings, the only way to identify in-scope headings is "headings that have a numeric RULES entry" — which is exactly INV-2. INV-1 has been removed from audit mode as redundant; the heading→entry direction is still enforced at commit time by C1 in `--check` mode.

Audit mode verifies the 5 invariants for all rules added under the N.NN convention (numeric IDs). Legacy slug-ID entries predate this contract; their drift was corrected in the v4.1.0 audit closure (commit ac1a64b) and is not re-checked here. Audit mode is forward-looking enforcement, not a retroactive scan of legacy state. It is intentionally stricter than the commit-time check on C5 (here it's an audit failure, not a warning) because at audit time the plan-then-implement window has closed. Used as a release-gate check to verify the repo is bookkeeping-clean for all N.NN-format rules before a version tag.

## Consequences

- A new tool `ms-rule-contract` is added to the `ms-*` toolchain (Step 2.2).
- Pre-commit hook runs `ms-rule-contract --check` before Semgrep (so a failed contract short-circuits the slower lint pass).
- CI (`enforce.yml`) runs `ms-rule-contract --audit` on every push to `main` **and on every pull request**. Push-to-main alone is insufficient because drift can enter via merge of a PR whose branch never saw the audit.
- Core Rule 5.25 (Rule-Addition Contract Discipline) is added documenting the full checklist, with this ADR linked as the source of design intent.

## What this does NOT enforce

- **Semantic correctness of the rule.** The contract is structural — presence and consistency of the required companion changes, not the quality of the prose or the wisdom of the rule itself.
- **Cross-rule coherence.** If a new rule contradicts an existing one, the contract is silent. That is a human-review concern.
- **Test quality.** C5 verifies the test function exists, not that it meaningfully tests the rule.
- **Deletion, renumbering, splits, merges, prose-only edits.** Out of scope per the Scope section above.

## Alternatives considered

- **Trigger on `ms-coverage` RULES only (not the `CORE_RULES.md` heading).** Rejected: `CORE_RULES.md` is the authoritative narrative source. A doc-only addition (heading without registry entry) would go undetected, and that is one of the observed drift modes.
- **Trigger on `CORE_RULES.md` heading only.** Rejected for the symmetric reason: registry-only additions (an entry sneaks into `ms-coverage` without a heading) would go undetected.
- **Warn instead of block for C3/C4.** Rejected. A stale `coverage_map.json` causes `ms-enforce --list` to silently misreport; snapshot drift causes CI failure on the next test run. Both are concrete, diagnosable, and cheap to fix at commit time; warning lets them slip to CI or release audit, which is where the v4.1.0 incidents came from.
- **Presence-in-diff for C3/C4 (the original draft of this ADR).** Rejected. "File appears in staged diff" is satisfied by an unrelated edit to the same file. Consistency checks (regenerate-and-compare) are mechanically only slightly more expensive and close the gap.
- **Single contract covering addition + deletion + renumbering.** Rejected for v4.2. Addition is the high-frequency case and accounts for all observed incidents. Bundling the rarer operations would delay this contract and complicate its spec. Deletion will get its own ADR when scheduled for implementation.

## Status

Accepted; not yet enforced (ms-rule-contract not yet wired to pre-commit / CI as of
the ADR acceptance date). Enforcement wired in Step 2.3 of the v4.2 Hardening Plan.

Enforced by:
- `ms-rule-contract --check` in the pre-commit hook (blocks commit if companions missing)
- `ms-rule-contract --audit` in `.github/workflows/enforce.yml` (CI gate on push + PR)
- `ms-enforce` Tier 1: `check_rule_contract()` (fast sanity check)

Revisit when:
- Rule deletion becomes frequent enough to warrant authoring a Rule-Deletion Contract (to be assigned a future ADR at that time).
- Rule renumbering is needed across the codebase (triggers both deletion and addition contracts).
