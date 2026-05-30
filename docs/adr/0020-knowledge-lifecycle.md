# ADR 0020 — Knowledge-Lifecycle & Reconciler-Trust Discipline

**Status:** Accepted 2026-05-30 (S-75-E)
**Decided by:** Robot wave S-75 (KNOWLEDGE-LIFECYCLE), Stream E (doctrine + ADR)
**Supersedes:** none
**See also:** `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md` (full rationale), `docs/KNOWLEDGE-LIFECYCLE-AUDIT.md` (charter), [ADR 0019 — Test-Data Isolation](0019-test-data-isolation.md), CLAUDE.md § "Knowledge-Lifecycle & reconciliation", `.claude/AUTONOMOUS-DEFAULTS.md` § "gap-discovery ritual"
**Review by:** 2027-05-30  <!-- process +12 mo from accepted date -->

## Context

The 2026-05-29 Knowledge-Lifecycle audit (`docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`)
found a single structural pattern across eight independent failure items (E1–E8,
all deploy/ops drift surfaced during the Rocinante deploy session): **SLOP is
reliable exactly where truth is derived/reconciled against physical ground truth
at use-time, and rots exactly where truth is stored-and-trusted.**

- *Reliable (derived against physics):* the line-count ratchet reads real LOC; the
  port linter reads `/proc/net/tcp`; the SLOP AI Agent reconciles live
  containers-vs-DB.
- *Rotted (stored-and-trusted):* CLAUDE.md facts (the false "no git on server" note;
  the `:8090`-vs-`:8080` port; the stale `_SLOP_MANAGED_VARS` enumeration), memory
  files, `MANAGER-HANDOFF.md`.

Two reality-reconcilers already exist — the **runtime** SLOP AI Agent
(`backend/core/agent.py`) and the **dev-time** `ms-enforce` gate suite — but **every
Rocinante failure fell in the gap *between* them**: a divergence between a documented
dev-time claim and live deploy reality that neither owner was positioned to catch.
The operator became detector-of-last-resort by default, not by design.

The audit's phase-2 critic surfaced the deeper trap: **the cure is isomorphic to the
disease unless disciplined.** A naive fix ("derive the handoff from git/BACKLOG")
reconciles *text against text* — cross-referencing, which inherits the
trust-the-text fragility it claims to cure. The `:8090`-vs-`:8080` bug was caught
only by journald (physics); no text-vs-text probe would have caught it. And a wrong
or stale probe is a *new* stored-and-trusted falsehood carrying a **higher** authority
("verified") — a false green, undetectable by definition. **Probes age too** — the
missing fourth leg of the project's "aging trilogy" (facts age, gates age, doctrine
ages, **and probes age**).

This ADR makes the audit's design decisions durable and citable: the
derive/reconcile-vs-store/trust routing, the two-owner firewall, and the
reconciler-trust discipline (GROUND-vs-XREF) that keeps the cure from becoming the
disease.

## Decision

### Decision 1 — Route facts by derive/reconcile-vs-store/trust, not by storing more

The fix is **methodology, not a bigger memory store** (vector RAG is explicitly
rejected: a slick store invites *more* trust while rotting silently — worse than
plaintext you appropriately distrust). Every load-bearing fact routes by
**volatility** × **source-of-truth**:

- **derivable-by-probe** → *derive, don't store.* Point at the live source
  (`_SLOP_MANAGED_VARS`, `installer/_defaults.py`); never enumerate the copy.
- **mutable-external** (the deploy host) → *structured state + `last_verified` +
  cadence*, reconciled by a probe that touches the live unit/socket/filesystem.
- **rationale-only** (walk-back entries, doctrine *why*) → *store + staleness-audit*,
  **tagged as rationale** so the truth-check doesn't waste effort and the calendar-age
  check isn't defeated by date-bumping. This is the ONLY class where calendar age is
  the right instrument.
- **in-flight-state** (handoff head, wave queue) → *derive, don't hand-author*
  (SHA-freshness now; narrow generated head later); keep prose hand-authored.

**`last_verified` / `verify_probe` frontmatter is applied ONLY to facts with a real
probe behind them.** A `last_verified` with no probe is negative value — false
assurance, defeated by date-bumping.

### Decision 2 — The two-owner firewall (HARD)

Knowledge ownership splits into exactly two non-overlapping owners:

- **Runtime knowledge → the SLOP AI Agent** (`backend/core/agent.py`). It **emits a
  reality view** of the *running instance* (bound port, install-dir-is-git, owning
  user, which env source actually populated each var) via its existing health-signal
  surface. **It is runtime-only: it never reads or adjudicates docs.**
- **Dev-time / process / doc knowledge → a SEPARATE new dev-time reconciler**
  (`tools/audit_doc_reality.py`, registered as `ms-enforce check_doc_reality`,
  warn-only). It **reconciles** the Agent's reality view + a host-side probe against
  documented claims and files findings into BACKLOG as `[gap-discovery]` entries. It
  **derives + reconciles; it never accumulates** — its only persistent output is
  BACKLOG entries, already under triage discipline.

**SSH/airgap resolution (Option A — operator-authenticated pull, automated logic):**
reconciling doc-vs-deploy reality requires reaching a live host, but the firewall
keeps the Agent runtime-only and the dev-tool repo-layer, and **no automated tool
holds an SSH credential.** Resolution: the wave installs a tiny read-only
`slop-reality-probe` on the host (prints the GROUND-class reality view to stdout). The
dev-side reconciler rides the **already-credentialed** SessionStart path — it runs
`ssh <host> slop-reality-probe` using the **operator's own ambient SSH agent**, at the
one moment a human session reliably exists, reconciles, and files `[gap-discovery]`
entries. No tool stores a secret; the Agent never reaches out; the dev-tool holds no
creds. **The human provides auth but not detection — the literal definition of "out
of the detector seat."** Host unreachable ⇒ `INDETERMINATE` (loud), never `OK`.

### Decision 3 — The reconciler-trust discipline (GROUND-vs-XREF)

The single discipline that prevents the cure becoming the disease: **a green light is
only trustworthy if it can go red against physics.** A probe that cannot fail against
ground truth is theater.

The **pinned vocabulary** (defined once here and in CLAUDE.md; all S-75 streams and
all future probes use it verbatim):

- **GROUND** — a probe that touches physics (a socket, the Docker socket, the
  filesystem, `git rev-parse`, process env) and therefore MAY assert `verified`.
- **XREF** — a text-vs-text comparison; may only flag `INCONSISTENT`, never assert
  `verified`.
- **INDETERMINATE** — ground truth was unreachable; emitted LOUDLY, never silently
  downgraded to `OK`.
- **UNPROBED** — no probe exists for this fact yet; counted by a ratchet that may
  shrink, never grow; never blessed as `verified`.

The **verdict tokens** every probe emits:

- `verified` — GROUND match (probe touched reality and it matched).
- `DRIFT` — GROUND mismatch (probe touched reality and it diverged).
- `INCONSISTENT` — XREF mismatch (text disagreed with text).
- `INDETERMINATE` — ground truth unreachable.

**Only `DRIFT` on a load-bearing claim files to BACKLOG.** `INCONSISTENT` /
low-confidence verdicts go to a lower-tier queue that does not count against BACKLOG
triage discipline. Findings dedup (update, never re-file).

The five operational rules:

1. **GROUND-vs-XREF tiering.** Only physics-touching probes may say `verified`.
   Text-vs-text probes may only flag `INCONSISTENT`.
2. **No silent skip, no silent pass.** A probe that can't reach ground truth emits
   `INDETERMINATE` (loud), never `OK`. A green light means "I touched reality and it
   matched" — never "I had nothing to check."
3. **Probes carry their own evidence.** Each verdict line states the ground truth it
   touched (e.g. "probed 10.0.1.51:8080 → 200"), making wrong/dead probes auditable.
4. **Probes are an aging asset (the fourth leg).** A probe that touched *nothing* this
   run is a candidate-dead probe → flagged. `UNPROBED` rows ratchet down, never up.
5. **Severity gate before BACKLOG.** Only GROUND-confirmed, load-bearing `DRIFT` files
   to BACKLOG; `XREF`/low-confidence go to the lower-tier queue. Dedup, never re-file.

### Decision 4 — Warn-only landing + promotion-to-blocking trigger

All S-75 gates land **TIER_1 warn-only** (`check_doc_reality`,
`check_handoff_freshness`, `check_fact_freshness`, and any sibling probes): they
surface findings but always return `True` and never block CI. A gate earns promotion
to **blocking** only when **both** hold:

- it has produced **clean signal across N consecutive runs** (recommended N = 5;
  no false-positive `DRIFT`/`INCONSISTENT` that turned out benign), AND
- its **`UNPROBED` ratchet is at (or near) zero** for the class it governs — i.e. the
  gate actually probes what it claims to govern, so a green is meaningful.

Promotion is a deliberate doctrine act recorded with the gate's tier change; it is the
Enforcement-Lifecycle wave's job, not done silently. (This mirrors ADR 0019's
warn-only-then-promote convention for `check_test_isolation`.)

### Exception clauses

- **Consensus error is out of scope.** Reconciliation finds *divergence*, not shared
  misconception; if doc and reality are both wrong, no probe catches it.
- **Rationale-only facts** are exempt from the truth-check (Decision 1) — they are
  legitimately stored and aged by calendar, provided they are tagged rationale.
- **Code-contract drift** (the two `CatalogEntry` defs, `_SLOP_MANAGED_VARS`) is
  already partly covered by `tests/test_rules_migration_batch1.py`; dependency/world
  drift and rationale rot are explicit follow-ups, not this wave's scope. The new
  tooling is scoped to the **host-reality class** and must not masquerade as a general
  K-L solution.

## Consequences

### Positive

- **The detector seat is owned by design, not by operator friction.** The unowned gap
  between runtime and dev-time reconcilers is closed by a named, firewalled dev-tool.
- **False greens are structurally prevented.** GROUND-vs-XREF + no-silent-pass +
  probe-aging mean a passing probe provably touched reality; a probe that touched
  nothing is flagged rather than trusted.
- **Bounded, batched, prioritized inventory.** `[gap-discovery]` findings flow into
  existing BACKLOG triage — the operator is in the *decision* path, never the
  *detection* path.
- **The cure is dogfooded.** This ADR and the audit report are committed to tracked
  branches (not the gitignored run-archive), the first application of the promotion
  discipline they prescribe.

### Negative

- **The operator remains triage-of-last-resort.** The win is bounded/batched
  inventory, not elimination of the human; a `[gap-discovery]` flood that is
  ignored-forever is the dominant residual risk (mitigated by BACKLOG triage
  discipline + severity gate).
- **Probe maintenance burden.** Probes are now a maintained, aging asset; a stale
  probe (still SSHing the old host) is a liability the aging-leg must catch.
- **Operator-ambient-SSH coupling.** Doc-vs-host reconciliation only runs when an
  operator session with a live SSH agent exists; airgapped/headless contexts emit
  `INDETERMINATE` rather than verifying.

### Neutral

- **The SLOP AI Agent's charter is unchanged** — it stays runtime-only; this ADR only
  names the firewall it already respects.
- **Vector RAG / a bigger memory store is explicitly NOT adopted** — the decision is
  methodology, not storage.
- **The aging-engine consolidation** (facts-aging + gate-aging + doctrine-aging +
  probe-aging share one shape) is a **design contract** shared with the
  Enforcement-Lifecycle wave, not a delivery coupling.

## Status

Accepted. Enforced via:

- **Process:** new probes follow GROUND-vs-XREF; reviewers cite this ADR when a probe
  asserts `verified` from a text-vs-text comparison, or silently passes when it could
  not reach ground truth.
- **Tooling:** `ms-enforce` warn-only gates `check_doc_reality`,
  `check_handoff_freshness`, `check_fact_freshness` (S-75 streams A–D). All return
  `True`; they surface findings, never fail CI.
- **Doctrine:** CLAUDE.md § "Knowledge-Lifecycle & reconciliation" defines the pinned
  vocabulary; `.claude/AUTONOMOUS-DEFAULTS.md` defines the gap-discovery ritual cadence
  and `[gap-discovery]` triage handling.
- **Review trigger:** revisit when any S-75 gate is a candidate for CI-blocking
  promotion (per Decision 4's N-runs + UNPROBED-near-zero trigger), or when a new
  knowledge class (dependency/world drift, rationale rot) is brought in scope.
