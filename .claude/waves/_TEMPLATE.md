# WAVE NAME — Short summary

## Goal
<!-- What outcome does this wave achieve? Why does it matter? -->

## Context
<!-- Background: what's the status quo, what's blocking, why now? Refer to earlier waves or prior work if relevant. -->

## Rules to follow
<!-- Explicit constraints the streams must obey (additive vs rewrite, file sizes, tooling patterns, backward compat, etc.) -->

## Authorized deletions
<!-- What files/code/sections may be removed? None, some, or all? Be explicit. -->

## Parallelization

**Models (per-wave default):** coordinator = **opus**, subagents = **sonnet** (or specify per-stream overrides below).

<!-- List all streams. Keep parallel unless there is a hard sequential dependency (rare; state it explicitly). -->

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A | <!-- **opus** / **sonnet** / **haiku** / blank (inherit) --> | parallel/sequential | `general-purpose` in worktree | <!-- What this stream builds --> |
| B | | parallel/sequential | `general-purpose` in worktree | <!-- What this stream builds --> |
| C | | parallel/sequential | `general-purpose` in worktree | <!-- What this stream builds --> |

**Per-stream Model justification (one line each — required by the rubric in ROBOT.md § "Per-stream Model column"):**
- <!-- A = <model> — why (irreducible judgment / bounded implementation / mechanical / load-bearing / plausible-but-wrong risk) -->
- <!-- B = <model> — why -->
- <!-- C = <model> — why -->

## Complexity & Pre-flight
<!-- What tier (Low/Medium/High) does this wave score to (per tools/wave_complexity.py), and what rigor will pre-flight apply? -->

## Deliverables per stream

### Stream A — <!-- Name and one-line role -->
<!-- Numbered list of concrete deliverables (new files, edits to existing files, tests, doctrine subsections in ROBOT.md, pinned contracts to producers/consumers, etc.). Include PINNED markers for shared symbols other streams consume. -->

### Stream B — <!-- Name and one-line role -->
<!-- Numbered list of concrete deliverables. -->

### Stream C — <!-- Name and one-line role -->
<!-- Numbered list of concrete deliverables. -->

## Verification
<!-- Explicit acceptance criteria: tests must pass, tool outputs verified, contracts held, doctrine reviewed, ms-enforce exits 0, etc. -->

## Out of scope
<!-- What is explicitly NOT part of this wave, even if related? Why is it deferred? -->

## Cross-wave dependencies (EXPLICIT)
<!-- Does this wave depend on code/artifacts from prior waves? Are there intra-wave shared touchpoints (pinned contracts, merged files, doctrine ownership)? Be exact. -->

## Robot mode (autonomous execution)
<!-- Orchestrator setup: how many worktrees, how are the streams ordered, which files are shared, how are conflicts resolved, what tool runs the merge to main, etc. Refer to ROBOT.md doctrine. -->
