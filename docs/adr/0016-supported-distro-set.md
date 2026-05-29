# ADR 0016 — Supported Distro Set for v5.0

**Status:** Accepted — 2026-05-16
**See also:** `installer/SUPPORTED_DISTROS.md`, `installer/readiness_manifest.yaml`
**Review by:** 2028-05-16

> Enforcement: [manual — `install.sh`'s distro guard rejects out-of-set versions at install time, and `installer/SUPPORTED_DISTROS.md` + `installer/readiness_manifest.yaml` are the policy artifacts. The supported set is reviewed at every release close per §6.3, not via static repo check.]

## Status

**Status:** Accepted — 2026-05-16

This ADR codifies the supported-distro policy for mediastack v5.0. It supersedes
the implicit distro set inherited from `V5_INSTALLER_PLAN.md` Direction Decision
D4 ("Supported distros for v5.0: Debian 12+ and Ubuntu 22.04+ only"), which was
carried forward from v4.x without an explicit policy review.

## Context

### 2.1 The inherited assumption

`V5_INSTALLER_PLAN.md` D4 named the supported set as "Debian 12+ and Ubuntu
22.04+." That decision was authored 2026-05-12 during the v5.0 design session and
was inherited from v4.x baseline parity. No structured review checked whether the
underlying environment assumptions still held against v5.0's increased
dependencies. The set was operationalized in `install.sh` (distro guard,
deadsnakes PPA branch for Ubuntu 22.04), in the Step 3.3 design (three-row
matrix: Ubuntu 24.04, Debian 12, Ubuntu 22.04), in audit-gate Step 4.5 success
criteria (three-distro install verification), and in `installer/SUPPORTED_DISTROS.md`.

### 2.2 What Step 3.3 surfaced

Step 3.3 matrix execution produced two distinct production-blocking findings on
the Ubuntu 22.04 row that did not appear on the Ubuntu 24.04 or Debian 12 rows:

**Finding 1: SQLite version floor.** Ubuntu 22.04 ships SQLite 3.37.2 (per the
`jammy-security` repository). The mediastack backend uses the `unixepoch()`
function at 40+ sites across 9 backend files. `unixepoch()` was added in SQLite
3.38.0; on 3.37 the service fails at lifespan startup with
`sqlite3.OperationalError: no such function: unixepoch`. Mitigation requires
either backporting `unixepoch` via a SQL polyfill (significant change to query
templates across the backend), shipping a private SQLite build (substantial
install-time surface and ongoing maintenance), or dropping Ubuntu 22.04.

**Finding 2: deadsnakes + update-alternatives breaks APT.** The Ubuntu 22.04
install path uses the deadsnakes PPA to source Python 3.11. The pre-fix
`install.sh` called `update-alternatives --install /usr/bin/python3 python3
/usr/bin/python3.11`, pointing the system Python at the deadsnakes build. This
broke Ubuntu's APT `Post-Invoke-Success` hook (`cnf-update-db`), which imports
`apt_pkg` — a compiled extension built only for python3.10 on Ubuntu 22.04. Any
subsequent `apt-get` call (including the Docker convenience script invoked by
`installer/docker.py`) failed with `ModuleNotFoundError: No module named
'apt_pkg'`. The immediate fix landed at commit `2e59460` (remove the
`update-alternatives` call; pass the explicit `/usr/bin/python3.11` path to the
installer instead). The fix works, but the underlying tension — needing a newer
Python than the base distro provides — is not a defect we should keep paying for
across the v5.x line.

### 2.3 Why the assumption survived

The Ubuntu 22.04 entry was carried from v4.x, where SQLite version requirements
were lower (no `unixepoch` use) and the deadsnakes PPA was a routine workaround
not yet known to interact with the `apt_pkg` hook. v5.0's increased dependencies
(newer SQLite features, Docker 24.0+ minimum from `installer/DEPENDENCIES.md`,
Node 20.19+ for Vite 8) outgrew the 22.04 environment. No structural check
re-evaluated the support matrix against current dependency requirements at any
tier close. The assumption survived from project memory; no re-check happened
until Step 3.3 forced one.

The rule of thumb here: **every decision depending on assumptions about reality MUST be
verified against current evidence before work commits**. The Ubuntu 22.04 entry
depended on assumptions about SQLite version availability and Python install
paths; neither was verified against current upstream state at the start of v5.0.

### 2.4 Audit scope context

The Class-A audit (CLASS_A_AUDIT_2026_05_15.md; moved to slop-process private repo) was scoped to
subprocess/runtime constraint failure modes (F1–F11) — the pattern class that
produced the Step 2.8 five-finding cluster. Distro version selection was not in
that audit's scope and could not have been surfaced by it. The LESSONS_LEARNED
entry of 2026-05-16 ("Class-A audit missed temporal-mock pattern despite
holistic scope") names the broader pattern: *"Holistic scope does not mean total
coverage. An audit format defines a category of bugs it can see; bugs in other
categories are invisible to it by construction."* Distro version policy is one
such category. It needs its own structural artifact with a defined lifecycle,
reviewed at every release boundary. This ADR is that artifact.

## Decision

v5.0.0 ships supporting the following three distros:

| Distro | Codename | Released | Standard support ends |
|---|---|---|---|
| Ubuntu 24.04 LTS | Noble Numbat | April 2024 | April 2029 (April 2034 w/ Pro) |
| Debian 13 | trixie | August 2025 | ~August 2028 (+ ELTS) |
| Debian 12 | bookworm | June 2023 | ~June 2026 (+ Debian LTS) |

Three distros total. Two distro families. Two releases per family for Debian;
one for Ubuntu at v5.0.0 ship.

**Ubuntu 26.04 LTS (Resolute Raccoon, released April 23, 2026) does NOT enter
the supported set at v5.0.0 ship.** It enters at its first point release
(26.04.1, scheduled August 6, 2026), at which time Canonical's
`do-release-upgrade` path from Ubuntu 24.04 LTS to 26.04 becomes officially
supported. The 26.04 row is added to the supported set via a v5.0.1 release
(or whichever release follows 26.04.1) that updates `install.sh`'s distro guard
and adds the corresponding row to `installer/readiness_manifest.yaml`'s
`distro_evidence` section.

Ubuntu 22.04 LTS (Jammy Jellyfish) is removed from the supported set. The
`install.sh` distro guard rejects 22.04 with a remediation message pointing to
this ADR.

The underlying policy:

> **v5.0 supports the latest LTS and the prior LTS per distro family (R-1 per
> family). A new Ubuntu LTS enters the supported set at its .1 point release; a
> new Debian release enters at its release date. When a release enters, R-2
> leaves.**

Architecture: x86_64 only through v5.x. ARM64 deferred to a future fully-Docker
rebuild.

## 4. Rationale

### 4.1 Why "latest LTS + R-1" per family

**Why not "latest LTS only" (one row per family):** Too narrow. Operators
upgrading from a prior LTS need a runway. Most homelab installs run on the
prior LTS because the current LTS at .0 has rough edges that .1 typically
smooths. A latest-only policy excludes the most likely deployment target.

**Why not "latest + every prior LTS in standard support" (three or more rows
per family for Ubuntu):** Too broad. Matrix size grows linearly with included
releases; per-row test cost is real (VM provisioning, evidence capture, audit
gate, ongoing breakage triage). The marginal benefit of the third-oldest LTS is
small: operators on that release are a thin set, and the workaround surface
required to keep older Python or SQLite environments working dominates the
value.

**Why "latest LTS + R-1":** Bounded matrix (at most two rows per family, four
rows total when the policy is at peak), one LTS cycle of upgrade runway
(roughly two years for Ubuntu, two to three years for Debian), and alignment
with the standard support windows that Canonical and Debian themselves operate.

### 4.2 Why per-family symmetry with asymmetric entry triggers

Each family gets the same rule shape (latest + R-1). This prevents bias: Ubuntu
and Debian are treated identically. Any inconvenience the policy creates falls
evenly across both.

Entry triggers are asymmetric because each family's "ready for production"
signal differs:

- **Canonical explicitly stages LTS adoption.** The .0 release is "ready for
  new installations"; the .1 release is "ready to upgrade into" — this is when
  `do-release-upgrade` from the prior LTS opens. Three weeks post-26.04.0
  release, the upgrade path is not yet officially supported by Canonical
  itself.
- **Debian has no equivalent staging concept.** Release means released. The
  release announcement, the security infrastructure activation, and the
  upgrade path readiness happen on the same day.

Imposing a uniform "wait N days post-release" rule would either over-wait on
Debian (where the signal is the release itself) or under-wait on Ubuntu (where
the release is still settling). Following each family's own readiness signal
respects each family's own model — and avoids importing churn that the upstream
project itself has not yet de-risked. The same principle applies: don't assume both families' release events mean the same thing; check
each against its own evidence.

### 4.3 Why not Fedora, RHEL, Arch, or other non-apt-based distros at v5.0

Supporting non-apt families requires substantially different installer code:

- dnf/yum for Fedora and RHEL; pacman for Arch; zypper for openSUSE.
- Different package names: `python3-venv` is the apt-family name only.
- Different default SELinux contexts on RHEL-family.
- Different systemd vendor patches.
- Different default user database (sssd in some RHEL configurations).

The Tier 2 installer's `installer/deps_debian.py` module is the sole OS-deps
surface in v5.0. Expanding to Fedora requires a parallel <!-- TEMPLATE: installer/deps_fedora.py --> (v5.1+ planned; does not exist yet)
with its own boundary tests, its own dependency-version contract, and its own
VM matrix row in Step 3.3 / audit Step 4.5. This is v5.1+ scope (per
`V5_INSTALLER_PLAN.md` D4 and `NON-GOALS`), or post-v5.0 fully-Docker rebuild
scope (where OS-deps become irrelevant because the install runs entirely in
containers).

The Class-A audit (`CLASS_A_AUDIT_2026_05_15.md`) is not the source of this
deferral. The audit operated within the inherited D4 scope of Debian + Ubuntu
only; it did not author the family-scope decision itself. The deferral is a
project-level scope decision documented in `V5_INSTALLER_PLAN.md` NON-GOALS and
DEFERRED TO v5.1, not an audit-derived recommendation.

Re-engagement triggers for non-apt family support:

- Explicit operator demand with help (a Fedora-using contributor authoring
  `deps_fedora.py` plus boundary tests plus a VM target), or
- The post-v5.0 fully-Docker rebuild making OS-deps irrelevant, at which point
  the supported "distro" set becomes "any host that runs the supported
  container runtime version."

### 4.4 Why x86_64 only through v5.x

ARM64 is deferred to the post-v5.0 fully-Docker rebuild. The current install
pipeline runs Python and Node natively on the host; ARM64 support would require
dual-arch wheels for every Python dependency, ARM64-native Node builds via
NodeSource, and ARM64 verification VMs in the audit gate. The container pivot
is the cleaner answer for ARM64 (most container images already publish
multi-arch manifests); v5.x stays x86_64.

### 4.5 Why ship without Ubuntu 26.04 at v5.0.0

This is the Shape B answer to a real trade-off. The alternatives were:

- **Shape A** ("latest LTS + R-1, the day the LTS releases"): ship v5.0.0
  supporting 26.04 immediately. Risk: shipping commits us to debugging an
  environment three weeks past release. Ubuntu 26.04 introduces substantial
  churn — Linux kernel 7.0, systemd 259 with cgroup v2 mandatory (cgroup v1
  removed), APT 3.x, Python 3.13 (which removes the `crypt` stdlib module),
  Docker 29 with containerd as default image store for fresh installs, and
  Rust-based core utilities. Any subset of these can interact with the
  installer or backend in ways not yet de-risked.
- **Shape B** (selected): "latest LTS enters at .1 point release." v5.0.0
  ships supporting Ubuntu 24.04 + Debian 13 + Debian 12. Ubuntu 26.04 enters
  at 26.04.1 (August 6, 2026) via a v5.0.1 release.
- **Shape C** ("latest LTS + R-1, regardless of release-time symmetry between
  families"): treats Ubuntu 26.04 (24 days old at v5.0.0 ship) and Debian 13
  (9 months old) identically. Hides the asymmetry rather than naming it.

Shape B follows Canonical's own readiness signal (the .1 release is when
`do-release-upgrade` opens), keeps v5.0.0 scope bounded, and preserves
operator-side optionality: anyone running 26.04 today can run mediastack v5.0.1
once 26.04.1 ships, by upgrading via Canonical's supported path.

## Consequences

### 5.1 install.sh changes (Sonnet implements)

Concrete edits to `install.sh` on the `feature/step-3-3-vm-matrix` branch as
fetched 2026-05-16 (line numbers approximate; Sonnet should match content):

- **Distro guard (current lines ~73–95):** Ubuntu guard accepts only
  `_vmaj -eq 24 && _vmin -ge 4` (no `-gt 22 && -lt 26` range; no 26+ branch).
  Debian guard accepts versions 12 and 13 explicitly (`_maj -ge 12 && _maj -le 13`).
  All other versions rejected.
- **Deadsnakes branch (current lines ~139–158):** removed entirely. The
  `_MS_PYTHON3` override variable collapses back to the default `python3`
  because both supported Ubuntu 24.04 and both supported Debian releases ship
  a Python ≥3.11 in their main archive (Ubuntu 24.04: Python 3.12; Debian 12:
  Python 3.11; Debian 13: Python 3.13). The `add-apt-repository
  ppa:deadsnakes/ppa` call and the `python3.11`/`python3.11-venv` apt installs
  are both removed.
- **`_pyvenv_ok=0` branch's Ubuntu 22.04 path (~lines around the `_vmaj -lt 24`
  case):** removed alongside the deadsnakes branch.
- **Error messages on distro-rejection paths:** updated to list the new
  supported set ("Ubuntu 24.04 LTS (Noble Numbat); Debian 12 (Bookworm);
  Debian 13 (Trixie)") and to point to this ADR (`docs/adr/0016-supported-distro-set.md`)
  for rationale, in addition to `installer/SUPPORTED_DISTROS.md`.
- **`installer/SUPPORTED_DISTROS.md`:** rewrite as a thin operator-facing
  summary that cross-references ADR 0016 as the authoritative source. Keep the
  file because install.sh's error message points to it; do not retire it.

### 5.2 V5_INSTALLER_PLAN.md changes

Specific edits to V5_INSTALLER_PLAN.md (moved to slop-process private repo):

- **Direction Decision D4:** supersede current text ("Supported distros for
  v5.0: Debian 12+ and Ubuntu 22.04+ only. Fedora, RHEL, Arch, openSUSE
  deferred to v5.1.") with a pointer to ADR 0016 as the authoritative policy.
  Retain D4's number to preserve cross-references; replace its content with a
  one-line "see ADR 0016" plus a brief note that 22.04 has been removed.
- **STATUS section:** "Current Step: Step 3.3 [OPUS] — VM matrix testing"
  remains. Update the next-action narrative to reflect Shape B (three-row
  matrix at v5.0.0; 26.04 row added at v5.0.1).
- **Step 3.3 header:** update title from "Step 3.3 — VM testing (Debian 12 +
  Ubuntu 22.04 + Ubuntu 24.04)" to "Step 3.3 — VM testing (Ubuntu 24.04 +
  Debian 12 + Debian 13)."
- **Step 3.3.0:** retain (durable VM SSH access is unchanged); update the
  example distro list ("Ubuntu 24.04, Debian 12, and Ubuntu 22.04") to
  ("Ubuntu 24.04, Debian 12, Debian 13").
- **Step 3.3.a / 3.3.b / 3.3.c:** update three-distro list to Ubuntu 24.04,
  Debian 12, Debian 13.
- **Step 4.5.a finding 1:** update "Fresh Debian 12, Ubuntu 22.04, Ubuntu
  24.04 VMs" to "Fresh Ubuntu 24.04, Debian 13, Debian 12 VMs."
- **Step 4.5.a finding 2:** same three-distro update.
- **Step 4.5.a:** add new audit-gate criterion: "ADR 0016 lands" (analogous to
  the existing "ADRs land (0013 layout contract, 0014 uninstall semantics)"
  line).
- **NON-GOALS:** the line "Multi-distro support beyond Debian/Ubuntu. Fedora,
  RHEL, Arch, openSUSE: v5.1 scope per D4." — update D4 citation to ADR 0016.
- **DEFERRED TO v5.1:** "Fedora, RHEL, Arch, openSUSE support. Per D4." —
  update D4 citation to ADR 0016.
- **DEFERRED TO v5.1:** add "Ubuntu 26.04 LTS support. Enters supported set at
  26.04.1 (August 6, 2026) per ADR 0016 §6."

### 5.3 STEP_3_3_DESIGN.md changes

Per the design refresh specification accompanying this ADR (see
STEP_3_3_DESIGN.md refresh spec; moved to slop-process private repo): the design's distro matrix
decision section is replaced wholesale, Section 1 failure-class predictions
gain forward-looking entries for Debian 13 and a deferred-to-v5.0.1 entry for
Ubuntu 26.04 (with the five Class D sub-predictions named), and Section 7
Sonnet implementation contract revises the commit sequence to reflect Shape B.

### 5.4 readiness_manifest.yaml changes

Per the manifest update artifact accompanying this ADR:

- `distro_evidence`: add `debian_13` entry (new); retain `ubuntu_24_04` and
  `debian_12` entries unchanged; move `ubuntu_22_04` entry to a new
  `archived_distros` section with a pointer to this ADR.
- `predicted_classes`: update `monitored_distros` lists per the new three-row
  set; add a "deferred-to-v5.0.1" comment block naming the five Ubuntu 26.04
  Class D sub-predictions for forward-looking visibility.
- The `ubuntu_26_04` entry is NOT added at v5.0.0; it lands in the v5.0.1
  release commit sequence post-26.04.1 (August 6, 2026).

### 5.5 Test matrix scope

- v5.0.0 ship: three rows (Ubuntu 24.04, Debian 13, Debian 12).
- Existing evidence at `/tmp/evidence/ubuntu_24_04/` and
  `/tmp/evidence/debian_12/` is reusable subject to revalidation
  against the current manifest schema (Corrections A and B already landed at
  `b050623`; existing evidence was captured against the older schema and may
  need one-time re-capture or accommodation — see the Step 3.3 design refresh
  Section 4 caution).
- Debian 13 evidence is net-new; provision the VM per Step 3.3.0 pattern and
  run the matrix per Step 3.3.a.
- Existing evidence at `/tmp/evidence/ubuntu_22_04/` becomes
  archival reference, preserved in place for future reference but not part of
  the v5.0 matrix.

### 5.6 Documentation

- `installer/DEPENDENCIES.md`: update the per-distro section to reflect the
  three supported distros plus the deferred Ubuntu 26.04 entry point.
- `INSTALL.md` (planned Step 4.4.a deliverable): names the supported set per
  this ADR.
- README install instructions: no enumeration today; if Step 4.4.b adds
  distro-naming to the README, name the supported set per this ADR.

### 5.7 Related lessons

A new LESSONS_LEARNED entry (drafted at
`/mnt/user-data/outputs/lessons_learned_step_3_3_pivot.md`, to be landed in
Sonnet's commit sequence per the Step 3.3 design refresh) records:

- The inherited-assumption-survival pattern (the project-level meta-lesson:
  inherited support targets get carried across version boundaries without
  re-verification; ADR 0016 is the structural correction).
- The unixepoch / Ubuntu 22.04 SQLite finding.
- The deadsnakes + update-alternatives + apt_pkg finding (fix at `2e59460`).
- The deferred-reading-blind-spot pattern (Section 6 lesson for the design;
  surfaces in the manifest's `systemd_python_path` regex correction).
- A brief meta-entry on **principle-citation-drift**: inherited attributions
  to authoritative artifacts (audit sections, prior decisions) can be treated
  as verified when carried across sessions, even when inaccurate. The
  triggering instance: a prior Opus session attributed a "Fedora/RHEL/Arch
  deferral to v5.1+" claim to Class-A audit §12.5; verification showed §12.5
  is about discipline restructure sequencing and contains no such deferral.
  The deferral exists as a project-level scope decision (V5_INSTALLER_PLAN.md
  D4 + NON-GOALS), not as an audit recommendation. Future ADRs cite the
  artifact's actual content, not inherited summaries.

## 6. Lifecycle

The supported set is a living artifact. Updates are triggered by upstream
release events, not by ad-hoc decisions.

### 6.1 Entry triggers

**A new Ubuntu LTS enters the supported set at its .1 point release.**

Reasoning: Canonical's `do-release-upgrade` path from the prior LTS opens at
.1. The .0 release is "release for new installations"; the .1 release is
"ready to upgrade into." Tracking .1 follows Canonical's own readiness model
— operators upgrading from R-1 onto the new LTS can do so via the supported
path. Operators on R-1 who want to skip to the new LTS at .0 are not the
install target; they should wait until .1, by which point mediastack has had
several weeks to bake the new environment into its install matrix.

Operationally: when an Ubuntu LTS .1 ships, the next mediastack release
includes the install.sh distro-guard update, the manifest's new
`ubuntu_XX_XX` entry under `distro_evidence`, and an ADR 0016 revision
recording the entry and the corresponding R-2 exit.

**A new Debian release enters the supported set at its release date.**

Reasoning: Debian's release process bakes the "ready for upgrade" signal into
the release itself. Debian does not have an LTS-style .1 staging concept;
release means released. The release announcement, the security infrastructure
activation, and the upgrade path readiness all happen on the same day.
Release-date is the operational readiness signal that Debian itself emits.

Operationally: same as Ubuntu, but the trigger is the release date, not a
later point release.

### 6.2 Exit triggers

**When a new release enters the supported set, R-2 (the now-second-prior
release) leaves.** Concretely:

- Ubuntu 28.04 ships → 28.04.1 releases approximately four months later → 24.04
  drops from the supported set at that point. The supported Ubuntu set becomes
  {28.04, 26.04}.
- Debian 14 ships → Debian 12 drops from the supported set at Debian 14 release
  date. The supported Debian set becomes {14, 13}.

The exit happens in the same release commit sequence as the entry: ADR 0016
revision, install.sh distro-guard update, manifest archival of the leaving
row, V5_INSTALLER_PLAN.md (or its successor) reference updates. The leaving
row's evidence directory is archived in place rather than deleted, mirroring
the Ubuntu 22.04 archival pattern.

**Out-of-cycle exit.** If a release falls out of upstream standard support
before its successor's R-2 trigger fires (e.g., a security incident causing
early end-of-life), the next mediastack release tags the gap as fix-now and
processes the exit ahead of schedule.

### 6.3 Audit cadence

This ADR is reviewed at every release close. The review checks:

- Accuracy: the policy is still consistent with current Canonical/Debian
  release schedules.
- Drift: no supported distro has fallen below R-1 without the corresponding
  ADR revision.
- Trigger: no entry trigger has fired without the corresponding ADR revision
  and downstream artifact updates.
- Consolidation: this ADR is a candidate for migration into the SQLite-backed knowledge store post-v5.0.

The first scheduled review of ADR 0016 itself happens at v5.0.1 close, when
the Ubuntu 26.04 row is added to the supported set.

### 6.4 On-policy-change review

If the underlying policy is amended — for example, changing from "R-1" to
"R-2," or from per-family to per-release, or adding a non-apt family — the
ADR revision documents the change with a dated entry. Revisions amend rather
than supersede; the lifecycle of this policy is itself an audit artifact.

The trigger for considering a policy amendment is a real operational signal:

- Two consecutive R-2 exits causing operator complaints → consider extending
  to "R-2 per family."
- A non-apt family operator contributes a complete `deps_<family>.py` module
  with boundary tests and a VM target → consider expanding the family scope.
- The fully-Docker rebuild ships → the policy retires (the supported "distro"
  set becomes "any host running a supported container runtime version").

## 7. References


### 7.2 Mediastack artifacts

- `docs/adr/0013-installer-layout-contract.md` — Installer layout contract
  (pipe-mode, state file, install user). ADR 0016 is consistent with ADR 0013;
  the distro decision does not interact with the layout contract.
- `docs/adr/0015-first-run-readiness-contract.md` — First-run readiness
  contract. ADR 0016's smoke-test scope (the five predicates) is invariant
  across the supported distros.
- `docs/adr/0014-frontend-build-release-policy.md` — Frontend build policy (Proposed).
  ADR 0016 does not depend on ADR 0014's resolution; both can land
  independently.
- V5_INSTALLER_PLAN.md (moved to slop-process private repo) — Direction Decision D4 superseded;
  Step 3.3, Step 4.5, NON-GOALS, DEFERRED TO v5.1 updated per §5.2 above.
- CLASS_A_AUDIT_2026_05_15.md (moved to slop-process private repo) — the audit whose Step 2.8
  findings preceded this work. Note: ADR 0016 cites the audit only for the
  category-scope context (§2.4), not as the source of the family-scope
  decision (which is V5_INSTALLER_PLAN.md NON-GOALS).
- LESSONS_LEARNED.md (moved to slop-process private repo) — entries from the 2026-05-16 Step 3.3
  pivot, drafted at `/mnt/user-data/outputs/lessons_learned_step_3_3_pivot.md`,
  forthcoming. Includes the inherited-assumption-survival pattern,
  deferred-reading-blind-spot pattern, and principle-citation-drift meta-entry
  per §5.7.
- `installer/readiness_manifest.yaml` — `distro_evidence` and
  `predicted_classes` sections refreshed per the manifest update artifact.
- `installer/SUPPORTED_DISTROS.md` — rewritten as a thin operator-facing
  summary cross-referencing this ADR.
- `installer/DEPENDENCIES.md` — per-distro section updated per §5.6.
- `install.sh` — distro guard, deadsnakes branch, error messages updated per
  §5.1.
- capture-step33-evidence.py (moved to slop-process private repo) — `DISTRO_MAP` updated for the new
  matrix per §5.5 (remove `ubuntu_22_04`; add `debian_13`).

### 7.3 Upstream artifacts

- Canonical Ubuntu 26.04 LTS release schedule (releases.ubuntu.com / Ubuntu
  release documentation): 26.04.0 released April 23, 2026; 26.04.1 scheduled
  August 6, 2026.
- Canonical Ubuntu 24.04 LTS standard support: April 2029; ESM through April
  2034 with Ubuntu Pro.
- Debian 13 release (debian.org): released August 9, 2025; standard support
  approximately three years plus LTS.
- Debian 12 release (debian.org): released June 2023; standard support through
  approximately June 2026 plus Debian LTS.
- SQLite release notes (sqlite.org/releaselog): 3.38.0 release notes document
  the introduction of `unixepoch()`; Ubuntu 22.04 jammy-security ships 3.37.2,
  jammy-updates ships 3.37.2-2ubuntu0.5; Debian 12 bookworm ships 3.40.1;
  Debian 13 trixie ships 3.46.1; Ubuntu 24.04 noble ships 3.45.1.
- Python `crypt` module removal: Python 3.13 removed the `crypt` standard
  library module. Ubuntu 26.04 defaults to Python 3.13; the removal is a Class
  D risk for the 26.04 entry at v5.0.1 (see the design refresh's forward-looking
  predictions).

---

*ADR 0016 supersedes the implicit "Debian 12+ and Ubuntu 22.04+" set
inherited from `V5_INSTALLER_PLAN.md` D4. This ADR is the authoritative source
for the supported-distro policy for v5.0.x. Revisions amend; references to D4
are redirected here.*
