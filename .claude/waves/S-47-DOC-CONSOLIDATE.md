# S-47-DOC-CONSOLIDATE — Reconcile duplicate docs and orphan compose file

## Goal
Eliminate "which file wins?" ambiguity from the three current duplicate-docs in
the repo: `INSTALL.md` vs `docs/INSTALL.md`, `MIGRATION.md` vs `docs/MIGRATION.md`,
and the orphaned `docker-compose.option-b.yml`. Each domain concept ends with one
canonical file and (where useful) a one-line pointer from the other location.

## Context
- `INSTALL.md` (root, 198 lines) and `docs/INSTALL.md` (5 lines) differ. Root is
  substantive; `docs/` looks like a stub.
- `MIGRATION.md` (root, 94 lines) and `docs/MIGRATION.md` (128 lines) **both
  substantive and forked**. Needs careful diff review, not a unilateral pick.
- `docker-compose.option-b.yml` lives alongside `docker-compose.yml`. The "option-b"
  naming is a tell that this was an alternative kept "just in case." The live
  compose is v4 ("Docker-only deployment"); option-b is v3 ("manager stack").
- These were flagged in the SLOP audit on 2026-05-27 alongside the dep-policy
  and track-gate work. This wave is the doc-only slice.

## Rules to follow
- Do NOT touch `.gitignore` (S-46 owns that file this round to avoid merge conflict).
- Do NOT touch `backend/static` or `data/tailscale/*` (those are S-48 Stream C).
- The canonical location for each concern is whatever results in fewer references
  needing to update. Check inbound references via `grep -rn "INSTALL.md\|docs/INSTALL"`
  etc. before deciding.
- If a doc has forked content (MIGRATION), MERGE the unique content — do not
  silently drop sentences. Reviewer must be able to see "here's what each side
  said, here's the merged result" in the diff.
- For `docker-compose.option-b.yml`: research first. If it's actually used by
  any documented install path, keep with a clear deprecation notice + rename. If
  not, delete with a one-line note in the deletion commit citing why.

## Parallelization

**Models:** coordinator = **sonnet**, subagents = **sonnet**. Rationale: pure
file-shuffling and diff-merging; no architectural judgment calls in the streams.
Sonnet end-to-end. Pass `model: "sonnet"` in each `Agent` call.

**You are the coordinator agent.** Dispatch the three streams below as concurrent
`Agent` subagent calls in a single message with `isolation: "worktree"`. Streams
touch disjoint files. After all finish, merge the worktrees back to main and
report.

| Stream | Subagent type | Scope |
|---|---|---|
| A — INSTALL dedup | `general-purpose` in worktree | `INSTALL.md`, `docs/INSTALL.md`, any inbound references |
| B — MIGRATION merge | `general-purpose` in worktree | `MIGRATION.md`, `docs/MIGRATION.md`, any inbound references |
| C — docker-compose.option-b decision | `general-purpose` in worktree | `docker-compose.option-b.yml`, any README/INSTALL reference to it |

## Deliverables

### Stream A — INSTALL dedup
1. `diff INSTALL.md docs/INSTALL.md` to see the actual delta.
2. `grep -rn "INSTALL.md" .` (excluding `.venv`, `node_modules`, `.claude/worktrees`) — count inbound references to each.
3. Pick the canonical home. Bias: the location with more inbound references stays.
4. Replace the loser with a one-line pointer: `> See [{canonical}](path) for install instructions.`
   (or delete the loser if no inbound references exist).
5. Update README.md if it references the loser.

### Stream B — MIGRATION merge
1. `diff MIGRATION.md docs/MIGRATION.md` — produce a side-by-side analysis comment in the PR/commit message naming what's unique to each.
2. Decide canonical home (likely `docs/MIGRATION.md` since it's the longer/newer; verify by inbound reference count).
3. **Merge unique content** from the loser into the canonical. Do not silently drop sentences. If two sentences disagree, surface that in the commit message and pick the one that matches current code.
4. Replace the loser with a one-line pointer or delete (per inbound-reference check).
5. Update inbound references in README.md, INSTALL.md, ADRs, etc.

### Stream C — docker-compose.option-b decision
1. `grep -rn "option-b\|option_b" .` — is it referenced anywhere (README, INSTALL, scripts, CI)?
2. Compare to `docker-compose.yml` — is option-b a strict subset, a different deployment style, or vestigial?
3. **Decide one of three:**
   - **Vestigial (no inbound refs, no documented path):** delete. Cite reasoning in commit.
   - **Documented alternative (refs exist):** rename to `legacy/docker-compose-v3.yml` and add a one-line `DEPRECATED` header pointing to `docker-compose.yml`.
   - **Currently active (used somewhere live):** keep but add a one-line header explaining when to choose it vs the main compose.
4. Update any inbound references to match the decision.

## Verification

After all three streams merge:
1. No two markdown files share the same H1 title (except by deliberate pointer pattern).
2. `grep -rn "INSTALL.md\|MIGRATION.md\|option-b" . --include="*.md" --include="*.yml" --include="*.yaml" --include="*.py" --include="*.sh"` returns no broken references.
3. `python3 ms-enforce` exits 0 (markdown lints if any).
4. Root README's "Documentation" / "Getting Started" sections, if they exist, still link to existing files.

## Out of scope
- `.gitignore` changes (S-46 Stream C owns this round)
- `backend/static` cleanup (S-48 Stream C)
- `data/tailscale/*` cleanup (S-48 Stream C)
- ADR `review-by:` field (S-50 Stream A)
- `docs/MAP.md` index (S-50 Stream B)
- Track-status invariant gate (S-48)
