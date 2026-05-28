# S-50-MENTAL-MODEL-FOUNDATIONS — Doc decay, docs/MAP, rules-to-tests audit

## Goal
Lay three foundations for keeping the project's mental model healthy as it
grows: a TTL on ADRs/operational docs, a single top-level documentation map,
and a *list* (not implementation) of CLAUDE.md rules that can be migrated from
prose to mechanical enforcement. Subsequent waves consume the list.

## Context
- The 2026-05-27 audit identified four principles: single source of truth,
  provenance on generated files, decisions decay (encode the half-life), rules
  graduate to tests. ADRs go to 0017; CLAUDE.md is ~140 lines and growing. The
  cost of "what's already decided?" is rising and there's no decay mechanism.
- ADRs are dated and immutable (good), but operational docs (MIGRATION.md,
  installer/DEPENDENCIES.md, etc.) have no "last-verified" field. They rot
  silently. The two MIGRATION.md files diverging (now resolved by S-47) was
  evidence.
- Fully independent of S-46/S-47/S-48/S-49. Can fire any time.

## Rules to follow
- Do not migrate any CLAUDE.md rule to a test in *this* wave — Stream C
  produces a candidate list with effort estimates. The actual migrations are
  separate future waves (one per testable rule, or batched in a follow-up).
- ADR `review-by:` must default sensibly per category. Architectural ADRs
  (e.g., 0006 SQLite vs Postgres) default to 24 months. Process ADRs default to
  12 months. Operational ADRs default to 6 months. The Stream A script picks
  the default per ADR but lets the author override.
- `docs/MAP.md` is the index of all docs. ≤ 100 lines. Bullet points only;
  one line per doc. If a doc deserves more, it gets its own file.

## Parallelization

**Models:** coordinator = **sonnet**, subagents = **sonnet**. Rationale: Streams
A and B are mechanical (template edit, doc index). Stream C (rules-to-tests
audit) is judgment-heavy per row but each row is small and well-scoped — Sonnet
handles that well. No deep cross-stream coordination needed. Pass `model: "sonnet"`
in each `Agent` call.

**You are the coordinator agent.** All three streams are fully parallel —
dispatch concurrently as `Agent` subagents in worktrees in one message. After
all three finish, merge and report.

| Stream | Subagent type | Scope |
|---|---|---|
| A — ADR review-by + stale-check tool | `general-purpose` in worktree | `docs/adr/template.md`, all existing ADRs (add `review-by:` field), `tools/ms-docs/stale.py`, `ms-enforce` registration |
| B — docs/MAP.md | `general-purpose` in worktree | `docs/MAP.md` (new), README.md (link to it) |
| C — rules-to-tests audit | `general-purpose` in worktree | `docs/RULES-TO-TESTS-AUDIT.md` (new, candidate list only — no migrations) |

## Deliverables

### Stream A — ADR `review-by:` field + stale check

#### A1. Update `docs/adr/template.md`
Add a `Review by:` line in the frontmatter / header, with a one-line comment
explaining the default per ADR category.

#### A2. Add `review-by:` to all 17 existing ADRs (0001–0017)
Default-fill per category, then a human can adjust:
- Architectural (0001 migrations, 0006 sqlite-vs-postgres, 0008 vue-3, 0009 infra-slot, 0011 single-tenant, 0013 installer-layout, 0016 supported-distros): **default 24 months from ADR date**.
- Process (0007 ms-test-vs-pytest, 0010 no-plugin-system, 0012 rule-addition-contract, 0014 frontend-build-release, 0015 first-run-readiness, 0017 uninstall-semantics): **default 12 months**.
- Operational (0002 mocking-policy, 0003 structured-logging, 0004 rate-limiting-tiers, 0005 api-versioning): **default 6 months**.

#### A3. `tools/ms-docs/stale.py`
- Parse each ADR's `review-by:` field.
- Report ADRs whose `review-by:` date is in the past.
- Exit 0 with WARNING list (not failure). Print "ADR 0007 was due for review on 2026-04-12 (45 days overdue)."

#### A4. `ms-enforce` integration
Register `check_doc_decay` as a warn-only TIER_1 check (same pattern as the
orphan detector from S-48).

### Stream B — `docs/MAP.md`

Single file, ≤ 100 lines. Structure:
```markdown
# SLOP Documentation Map

Single index for every documentation file in this repo. New docs land here or
they don't ship.

## Onboarding (read first)
- README.md — project pitch, install one-liner, basic operation
- CONTRIBUTING.md — local setup, branch & PR norms
- docs/INSTALL.md — full install walkthrough
- CLAUDE.md — agent/contributor conventions

## Architecture & decisions
- docs/adr/ — Architecture Decision Records (one file each, numbered)
- docs/GLOSSARY.md — domain vocabulary

## Operations
- docs/MIGRATION.md — version-to-version upgrade notes
- docs/observability.md — metrics, logs, dashboards
- docs/RELEASE_NOTES_v5_0_0.md — current release notes
- installer/DEPENDENCIES.md — dep policy + transitive notes
- installer/SUPPORTED_DISTROS.md — supported install targets

## Wave / project state
- .claude/waves/ — active wave prompts
- CHANGELOG.md — release-tagged change history

## Catalog
- catalog/MANIFEST_SPEC.md — app manifest format
```

Each line is `path — one-sentence purpose`. Update README.md to link to the map.

### Stream C — Rules-to-tests audit

Read every rule in CLAUDE.md (including grandfathered facts and project facts).
For each, fill a row in `docs/RULES-TO-TESTS-AUDIT.md`:

| Rule (CLAUDE.md section) | Testable? | Proposed test | Estimated effort |
|---|---|---|---|
| "Any field added to `to_catalog_entry()` must also be added to the Pydantic model" | YES | `tests/test_catalog_round_trip.py` — load every manifest, assert dataclass → Pydantic → JSON → Pydantic round trip preserves all fields | S (1 session) |
| "Apply scripts: no f-strings, no `{}` dict literals" | YES | ruff rule or grep check via `tools/ms-enforce check_apply_scripts` | S |
| "No multi-line bash in SSH double-quoted args" | PARTIAL | grep heuristic; false positives likely | M |
| "Vue view files: NO business logic" | PARTIAL | already partly enforced by file-size ratchet; could add Vue-AST check for setup-script size | M |
| "Backend tests run against a local venv; no external server required for unit tests" | NO | Documentation-of-fact, not a rule | — |
| ... |

Verdicts:
- **YES** — fully mechanizable; future wave can land the test cheaply.
- **PARTIAL** — partial check possible; documentation still useful.
- **NO** — documentation-of-fact or contextual judgment.

Total at the bottom: "N YES / M PARTIAL / K NO out of (N+M+K) total rules. Y
estimated sessions to migrate all YES rules."

Do NOT migrate any rules in this wave — the audit is the deliverable.

## Verification

After all three streams merge:
1. Every ADR (0001–0017) has a `review-by:` field.
2. `python3 tools/ms-docs/stale.py` exits 0, may print WARNINGs for any
   already-overdue ADRs.
3. `docs/MAP.md` exists and is ≤ 100 lines.
4. README.md links to `docs/MAP.md`.
5. `docs/RULES-TO-TESTS-AUDIT.md` exists, lists every CLAUDE.md rule, and
   ends with a tally line.
6. `python3 ms-enforce` exits 0 (warnings allowed, failures not).

## Out of scope
- Migrating any CLAUDE.md rule to a test in this wave (Stream C delivers a list, future waves consume it)
- Provenance-header check for generated files (defer to a follow-up after seeing how docs/MAP and the audit settle)
- Splitting CLAUDE.md into root + `docs/project-facts/` (defer; smaller principle, can land after the audit reveals what's left in CLAUDE.md after rule migration)
