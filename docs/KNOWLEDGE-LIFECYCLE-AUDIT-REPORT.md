# Knowledge-Lifecycle & Gap-Discovery — Audit Report

**Produced by:** the Opus Auditor-Manager session + 5 read-only lens auditors + 1
phase-2 blind-spot critic, 2026-05-29.
**Charter:** `docs/KNOWLEDGE-LIFECYCLE-AUDIT.md`.
**Status:** discovery/design output. Drives wave `.claude/waves/S-75-KNOWLEDGE-LIFECYCLE.md`.
**Branch:** `docs/wave-draft-knowledge-lifecycle` (not merged).

This report is **independently derived first** from the evidence; the charter
Appendix (a prior single-session analysis) was attacked, not adopted — its
scorecard is in §4. Method: 5 lenses (reality-drift, transition-seam,
temporal-decay, unmeasured-dimension, detection-ownership) each derived a taxonomy
from the 8 evidence items *without reading the Appendix*; a phase-2 critic then
audited the **merged** findings for what all lenses collectively missed. The
Manager (this session) synthesized — reconciling each load-bearing claim below
against live repo/server state rather than trusting the subagents (dogfooding the
very discipline the report prescribes).

---

## 0. The one-sentence finding

SLOP is reliable exactly where truth is **derived/reconciled against physical
ground truth at use-time** (the line-count ratchet reads real LOC; the port linter
reads `/proc/net/tcp`; the SLOP AI Agent reconciles containers-vs-DB) and rots
exactly where truth is **stored-and-trusted** (CLAUDE.md facts, memory files,
`MANAGER-HANDOFF.md`) — so the fix is **methodology (derive + reconcile + a
freshness signal that can fail loudly), not a bigger memory store** — and the
single discipline that makes the fix safe is: **a green light is only trustworthy
if it can go red against physics.**

---

## 1. Failure-mode taxonomy (independently derived from the evidence)

Eight failure classes, each anchored to evidence items (E1–E8 from the charter §2)
and to a concrete locus in the tree. The classes cluster into three families.

### Family I — Stored-and-trusted rot (truth diverged; no reconciler)
- **T1 Stored-mirror-of-code.** A prose fact duplicates a value that actually lives
  in code/config; nothing re-derives the copy, so it lags every change.
  *Anchor:* `CLAUDE.md` "known env vars" list (6 names) vs the live
  `_SLOP_MANAGED_VARS` frozenset (`backend/api/apps.py:42`, ~19 entries). *E6.*
- **T2 Cross-boundary belief.** A fact about something outside the repo's diffable
  surface (the running server, the systemd unit, journald). Git/CI cannot falsify
  it; only hitting it live reveals drift. *Anchor:* the false "no git on server /
  scp+sudo cp" CLAUDE.md fact; `:8090`-vs-`:8080`; `project_rocinante_deploy.md`.
  *E2, E3, E4, E5, E6.*
- **T3 Age-flagged-but-not-truth-checked (the deepest gap).** The only mechanisms
  aimed at fact-rot (`audit_memory_staleness.py`, `ms-docs/stale.py`) measure
  **calendar age**, not **truth**. A fact false on day 1 sails through; a verifiable
  fact can be **date-bumped to reset the clock** without re-verification. *E2, E3.*

### Family II — Boundary/transition loss (artifact stranded at a seam)
- **T4 Stranded-on-the-far-side.** An artifact stays in the source location after a
  boundary crossing; the destination never learns it exists. *Anchor:* MS* tools
  left on the `mediastack` repo after the move to public SLOP; server-recovery
  tooling (`reinstall_slop_host.sh`, `normalize-ownership.sh`) stranded in
  `/home/stack/v5`, unable to reach the host it manages. *E1, E8.*
- **T5 Hand-carry-or-lose.** Crossing a seam requires a human to manually copy state.
  *Anchor:* `.claude/run-archive/` is **gitignored** (`.gitignore:87`) — a one-way
  drain; multiple BACKLOG items were hand-carried out of it; `MANAGER-HANDOFF.md` is
  hand-authored, so it was stale at session start ("batch-7 in-flight" after it
  finished). *E7.*
- **T6 Silent-no-op at the boundary.** The crossing *mechanism* fails quietly, so
  "didn't update" is indistinguishable from "up to date." *Anchor:* `sudo ms-update`
  — root git on a service-user-owned repo → dubious-ownership → `set -euo pipefail`
  death with stderr eaten → clean exit-0. *E4.*

### Family III — Unobserved axes (no instrument points here at all)
- **T7 Effective-config provenance.** Nothing knows *which* config source is
  authoritative at runtime (`.env` via Starlette `Config` vs systemd
  `Environment=`); a value set in the inert source is silently never read. *E6.*
- **T8 Undocumented-precondition / error-channel integrity.** A destination has an
  implicit invariant (ownership, env precedence) the crossing agent can't see until
  it's violated (a bad `chown` crash-looped the service); and nothing verifies that a
  failing op actually *surfaces* its failure. *E5, E4.*

### Volatility × source-of-truth (the routing axes)
Every fact routes by **volatility** (static / slow / volatile) × **source-of-truth**
(derivable-by-probe / mutable-external / rationale-only / in-flight-state). The
per-fact routing table is §5.

---

## 2. The structural diagnosis — two owned detectors, one unowned gap

SLOP already runs **two** owned reality-reconcilers:

1. **Runtime detector** — the SLOP AI Agent (`backend/core/agent.py`) + the health
   scheduler. Reconciles the *running instance's* containers/health vs DB
   (ghost-detection). **Runtime-only, by charter.**
2. **Dev-time detector** — `ms-enforce` (~50 `check_*` gates, root script `./ms-enforce`)
   firing only on push/PR (`.github/workflows/enforce.yml` — push/PR triggers, **no
   cron**), plus the SessionStart boundary hook
   `/home/stack/v5/docs/tools/check_push_status.sh` (reconciles git push/pull state
   across 3 repos).

**Every Rocinante failure fell in the gap *between* them:** a divergence between a
*documented/dev-time claim* and *live deploy reality*. The runtime Agent never reads
docs; `ms-enforce` reconciles repo-internal consistency but never reaches the deploy
host. So **no owned process was ever positioned to catch the drift — the operator
became detector-of-last-resort by default, not by design.** That is the meta-failure
the gap-discovery ritual must close.

---

## 3. Blind-spot analysis — why prior gap-audits never surfaced these classes

The charter's central question. Three structural reasons, each independent of effort
or competence:

1. **You can only audit along an axis you already instrument.** Every existing check
   measures one of three axes — *size* (line ratchet), *process-artifact presence*
   (BACKLOG/walk-back/merge gates), or *runtime running-vs-expected* (the Agent). A
   single auditor reasoning from the existing toolset re-derives those axes and finds
   them healthy. **Stored-fact veracity, dev↔host congruence, tool inventory,
   effective-config provenance, and error-channel integrity are off-instrument**, so
   they are invisible until live friction crosses the seam the static tools never
   cross.
2. **The apparatus runs in one place and measures proxies.** All gates run inside the
   dev tree and check proxies (a date is recent, a link resolves, an exit code is 0).
   A false fact with a valid path and a fresh date is *maximally* invisible — no gate
   dereferences the proxy against an external authority. Friction (the Rocinante
   session) was the only "probe" that executed against the real host, dereferenced
   stored facts against reality, and exercised the error channel for real.
3. **The apparatus is self-trusting.** It believes the exit codes of what it shells
   out to, so a *lying subordinate channel* (`ms-update`'s eaten stderr) is in its
   own blind spot by construction.

**What the phase-2 critic found that all five lenses *also* missed** (the deeper
layer, which the methodology must internalize):

- **The reflexivity trap.** This audit's own output (taxonomy, routing table,
  findings) is itself stored-and-trusted knowledge draining into the gitignored
  run-archive — the exact failure it diagnoses. *The cure must be dogfooded on
  itself or it is theater.*
- **"Reconcile" ≠ "ground."** The project's *reliable* mechanisms touch **physics**
  (`/proc`, the Docker socket, the filesystem) that cannot lie about itself. Many
  tempting fixes ("derive the handoff from git/BACKLOG") reconcile **text against
  text** — that is *cross-referencing*, and it inherits the trust-the-text fragility
  it claims to cure. The `:8090`-vs-`:8080` bug was caught only by journald
  (physics); no text-vs-text probe would have caught it.
- **The cure is isomorphic to the disease unless disciplined.** A wrong probe is a
  new stored-and-trusted falsehood carrying a *higher* authority ("verified"). New
  probes accumulate; a stale-but-passing probe (still SSHing `.60` after the move to
  `.51`) is a **false green** — undetectable by definition. *Probes age too — the
  missing fourth leg of the "aging trilogy."*
- **The operator does not leave the detector seat — they move one hop to triage.**
  Every mechanism routes to BACKLOG → cleanup wave → human triage. The honest win is
  *bounded, batched, prioritized* inventory, not elimination. The dominant risk is a
  `[gap-discovery]` **flood → ignore-forever**, the exact loophole `check_backlog_stale`
  was built to fight.

**The single discipline that defeats the failure mode:** a green light is only
trustworthy if it can go **red against physics**. Build only probes that can fail
loudly against ground truth; everything else is the disease wearing the cure's
clothes. This becomes pinned doctrine (the **GROUND-vs-XREF** rule, §6).

---

## 4. Appendix scorecard (charter lines 110–143)

**Nailed:** the reframe (a storage *surplus* with no *lifecycle*, not a shortage);
the derive/reconcile-vs-store/trust dichotomy; the explicit rejection of vector RAG
("a slick store invites *more* trust while rotting silently — worse than plaintext
you appropriately distrust"); the honest known-limit (audits shrink friction-gaps,
never eliminate them). These are preserved.

**Missed (the lenses caught):** the *unowned gap between* the two existing detector
machines; the two-owner firewall and its transport problem; run-archive as a one-way
gitignored drain; promotion-at-merge.

**Missed by BOTH Appendix and lenses (the critic caught):** the reflexivity trap;
the GROUND-vs-XREF distinction (the Appendix says "derive from git/BACKLOG" without
noticing that is text-not-physics — the very confusion that makes its handoff
proposal fragile); the SSH-airgap-has-no-transport problem; and probe-aging as the
missing fourth leg of its own aging trilogy.

---

## 5. Fact-store inventory + per-fact routing

For each load-bearing store, the routing verdict. **`GROUND`** = a probe touches
physics and may assert "verified." **`XREF`** = text-vs-text; may only flag
inconsistency, never bless. **`UNPROBED`** = no probe exists yet (counted by a
ratchet; may shrink, never grow).

| Store / fact | Volatility × source | Class | Route — how it should be held | Probe tier |
|---|---|---|---|---|
| `CLAUDE.md` "known env vars" list | slow × derivable | T1 | **derive-don't-store**: point to `_SLOP_MANAGED_VARS` (test-enforced); never enumerate | GROUND |
| `CLAUDE.md` path-layout tables (`/opt`,`/var/lib`,`/srv`) | static × derivable | T1 | single-source from `installer/_defaults.py`; describe wizard-set `config_root` as mechanism, never a literal | GROUND |
| Rocinante deploy facts (port, service user, ownership, `.env`-vs-`Environment=`) | slow × mutable-external | T2,T7 | **structured-state + last-verified + cadence**: a host-side reality probe reconciles each claim against the live unit/socket/filesystem | GROUND |
| `CLAUDE.md` deploy = "git pull/reset" | slow × mutable-external | T2 | host probe asserts the clone is post-rewrite and not diverged; surface the `reset --hard` qualifier at point-of-use | GROUND |
| `MANAGER-HANDOFF.md` current-state head (HEAD SHA, in-flight batch, /tmp inventory) | volatile × in-flight | T5 | **derived-not-authored**: SHA-freshness assertion now (`git rev-parse origin/main`); narrow generated head later. Keep prose hand-authored | GROUND (SHA) / XREF (queue) |
| `MANAGER-HANDOFF.md` wave queue / priorities | slow × in-flight | T5 | derived from BACKLOG tokens — but **XREF**, parse-strict-fail-loud, labeled authored | XREF |
| memory `*.md` facts naming files/flags | slow × derivable | T1,T3 | reference-existence check: every named in-repo path must resolve; add `last_verified` ONLY where a probe exists | GROUND |
| memory facts about external server | slow × mutable-external | T2,T3 | `verify_probe` re-run on cadence; absent probe ⇒ visibly `UNPROBED`, never a bare date | GROUND/UNPROBED |
| `.claude/run-archive/` findings | volatile × in-flight | T5 | **promotion-reconciliation at merge**: enumerate run/ findings, warn on un-promoted before the archive is pruned | GROUND |
| Doctrine rationale (walk-back entries, "one-orchestrator-per-batch") | static × rationale-only | (n/a) | **rationale + staleness-audit**: legitimately stored; the ONLY class where calendar-age is the right tool — must be *tagged* rationale so the truth-check doesn't waste effort and the age-check isn't defeated by date-bumping | XREF |
| Infra exclusion sets (`_INFRA` duplicated 4×) | slow × derivable | T1 | derive-don't-store: one constant, ideally from manifest `category` | GROUND |
| `ms-update` / `deploy.sh` behavior | slow × mutable-external | T6,T8 | **ceded to S-74**: post-update SHA-verify + stop swallowing stderr (error-channel integrity) | GROUND |

**Routing principle:** *derivable → probe don't store; mutable-external → structured
state + last-verified + cadence; rationale → store + staleness-audit (tagged);
in-flight → derive, don't hand-author.* Apply `last_verified`/`verify_probe`
frontmatter **only** to facts with a real probe — a `last_verified` with no probe
behind it is negative value (false assurance, defeated by date-bumping).

---

## 6. The design (two-owner, firewalled) + the reconciler-trust discipline

### Owner split (the charter firewall, made buildable)
- **SLOP runtime-knowledge → the SLOP AI Agent** (`backend/core/agent.py`), as an
  extension of its existing reality-reconciliation to config/version/artifact drift
  of the *running instance*. It **emits a reality view** (bound port, install-dir-is-
  git, owning user, which env source actually populated each var) via its existing
  health-signal surface. **It stays runtime-only — it never reads or adjudicates
  docs.**
- **Dev-time K-L + the gap-discovery ritual → a SEPARATE new dev-time tool**
  (`tools/audit_doc_reality.py`, registered as `ms-enforce check_doc_reality`,
  warn-only). It **reconciles** the runtime reality view + a host-side probe against
  the documented claims, and files findings into BACKLOG as `[gap-discovery]`
  entries. It **derives + reconciles; it never accumulates** — its only persistent
  output is BACKLOG entries, already under triage discipline.

### The SSH/airgap resolution (the keystone the lenses left unbuildable)
Reconciling doc-vs-deploy-reality requires reaching a live host, but the firewall
says the Agent is runtime-only and the dev-tool is repo-layer — an airgap with **no
transport**, and **no automated tool holds an SSH credential today**. Resolution
(**Option A — operator-authenticated pull, automated logic**):

> The wave installs a tiny read-only `slop-reality-probe` on the host (prints the
> reality view to stdout — all GROUND-class). The dev-side reconciler rides the
> **already-credentialed** SessionStart path: it runs `ssh <host> slop-reality-probe`
> using the **operator's own ambient SSH agent**, at the one moment a human session
> reliably exists (session start), reconciles, and files `[gap-discovery]` entries.
> No tool stores a secret. The Agent doesn't reach out (firewall intact). The
> dev-tool holds no creds (firewall intact). **The human provides auth but not
> detection — the literal definition of "out of the detector seat."** Host
> unreachable ⇒ the probe emits `INDETERMINATE` (loud), never `OK`.

### Reconciler-trust discipline (pinned doctrine — prevents the cure becoming the disease)
1. **GROUND-vs-XREF tiering.** Only physics-touching probes may say "verified."
   Text-vs-text probes may only flag inconsistency.
2. **No silent skip, no silent pass.** A probe that can't reach ground truth emits
   `INDETERMINATE` (loud), never `OK`. A green light means "I touched reality and it
   matched" — never "I had nothing to check."
3. **Probes carry their own evidence.** Each verdict line states the ground truth it
   touched ("probed 10.0.1.51:8080 → 200"), making wrong/dead probes auditable.
4. **Probes are an aging asset (the fourth leg).** A probe that touched *nothing* this
   run is a candidate-dead probe → flagged. `UNPROBED` rows ratchet down, never up.
5. **Severity gate before BACKLOG.** Only `GROUND`-confirmed, load-bearing divergences
   file to BACKLOG triage; `XREF`/low-confidence go to a lower-tier queue that does
   not count against BACKLOG discipline. Findings dedup (update, never re-file).

### The recurring gap-discovery ritual
**Agent writes reality → dev-time tool reconciles reality-vs-doc → BACKLOG
`[gap-discovery]` → drained by a cleanup wave.** Cadence is **session-relative**
(piggybacked on the SessionStart hook), not a silent wall-clock cron. Multi-lens,
seam-crossing (dev↔host, doc↔reality, command↔effect), reality-reconciling. The
operator is in the *decision* (triage) path only — never the *detection* path.

---

## 7. Honest scope (what this does NOT solve)

- The operator remains **triage-of-last-resort**; the win is bounded/batched
  inventory, not elimination of the human.
- **Consensus error** (doc *and* reality both wrong) is invisible to reconciliation —
  it finds divergence, not shared misconception.
- The evidence is **monocultural** (all 8 items are deploy/ops drift). Code-contract
  drift (the two `CatalogEntry` defs, `_SLOP_MANAGED_VARS`) is *already* partly
  covered by `test_rules_migration_batch1.py`; dependency/world drift and rationale
  rot are **out of scope** for this wave and noted as follow-ups. The new tooling is
  scoped to the **host-reality class** and must not masquerade as a general K-L
  solution.
- The aging-engine consolidation (facts-aging + gate-aging + doctrine-aging share one
  shape) is a **design contract shared with Enforcement-Lifecycle**, not a delivery
  coupling — see the co-batching call in the wave file.

---

## 8. Deliverables produced by this audit

1. This report.
2. `.claude/waves/S-75-KNOWLEDGE-LIFECYCLE.md` — the implementation wave (two-owner
   design, 5 firewalled streams, per-stream Model column, dogfooded green; co-batching
   call vs S-74 and Enforcement-Lifecycle inside it).
3. `.claude/waves/S-75-LAUNCH-PROMPT.md` — the Robot orchestrator launch prompt.

> **Reflexivity note (dogfooding rule #1):** this report and the wave file are
> committed to a **tracked branch**, not left in the gitignored run-archive — the
> first application of the promotion discipline the report prescribes.
