# ADR NNNN — Title

**Status:** Proposed | Accepted | Superseded | Deprecated
**Decided by:** [agent or person] [date]
**Supersedes:** [link or "none"]
**See also:** [links to strategy docs, Core Rules, ms-coverage entries]
**Review by:** YYYY-MM-DD  <!-- architectural +24 mo · process +12 mo · operational +6 mo from accepted date -->

## Context

What problem are we solving? What constraints apply (technical, organisational, time-bound)? Cite specific evidence when possible — past incidents, audit findings, performance numbers. Context is the part that ages best; future readers should understand WHY without needing to ask.

If this ADR replaces an earlier one, summarise what changed and why the previous decision is no longer right.

## Decision

What we will do, in plain language. Be specific enough that a reader can implement from this section alone without re-deriving the choice. Include:

- The chosen approach (library, pattern, threshold, etc.)
- Configuration / parameters / tier definitions if applicable
- Exception clauses (when does the rule NOT apply)
- The enforcement mechanism (review, ms-enforce check, CI gate)

Avoid burying the actual decision in justification — the section header is "Decision" for a reason.

## Consequences

### Positive

- What gets better (correctness, safety, speed, clarity)?
- What new capabilities does this unlock?

### Negative

- What gets worse (perf cost, fixture surface, maintenance burden)?
- What workflows change for developers?
- What's the migration cost?

### Neutral

- What stays the same that someone might assume changes?
- What's explicitly out of scope?

## Status

How this ADR is enforced going forward:

- **Process:** new code follows the policy; reviewers cite the ADR
- **Tooling:** specific ms-enforce check or CI gate, if any
- **Coverage:** ms-coverage rule entry, if applicable
- **Review trigger:** when do we revisit (e.g. "when X happens" or "in 6 months")

If the ADR is **superseded** by a later one, link to it here and explain the trigger.

---

## Conventions

ADRs in this directory:

- Are numbered sequentially (`0001-*`, `0002-*`, ...). The number is permanent — even if an ADR is superseded, its file stays for git-blame archaeology.
- Use kebab-case slugs that match the title (e.g. `0001-database-migrations.md`).
- Are committed to git alongside the change they document. New code that needs an architectural decision lands the ADR in the same PR.
- Codify a Core Rule when applicable; enforcement is carried by ms-enforce checks (run `python3 ms-enforce --list` to see active rules).
- Reference but do not duplicate strategy docs (`docs/cleanup/STEP_*_STRATEGY.md`) — strategy is the implementation plan; ADR is the durable design decision.

See `docs/adr/0001-database-migrations.md` for an early example, and Core Rule 4.15 (Architecture Decision Records) for the project's enforcement of this convention.
