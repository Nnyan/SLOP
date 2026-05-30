# SLOP AI Agent — Oversight-Surface Expansion Survey

**Produced 2026-05-30** by an independent Opus divergence pass (read-only, first-principles
derivation diffed against the live codebase) + Manager synthesis. Durable input for the
**agent self-audit / spine wave** and the multi-wave agent-expansion roadmap. Companion to the
agent-expansion waves already in flight (`.claude/waves/S-60..S-64`).

## 0. The unifying shape (the spine)
Every agent capability fits one form: **GROUND probe that can go red against physics →
optional advisory interpretation (LLM = XREF/advisory, never authoritative) → bounded,
human-gated remediation.** "Expanding the agent" = adding probes across strata, all plugging
into ONE shared spine. The **self-audit wave is the reference implementation of that spine**;
design its seams (reconciler contract, sanitizer boundary, ms-router review call, advisory-only
remediation gate) as reusable, and every later stratum is cheap.

**Reuse (verify landing status at draft time):** anonymization (**S-61**) = the sanitizer;
ms-router + cost (**S-62/S-63**) = the LLM-review transport (on-host AND cloud providers);
safe-autofix + fix-safety (**S-60/S-64**) = bounded remediation. The expansion is mostly *wiring
existing primitives into the spine* — squarely inside the approved "extend the existing Python
pipeline" scope.

## 1. What's already well-covered (do not re-build)
Container-vs-DB reconciliation + RealityView env-provenance (`agent.py`/`reality_view.py`), LLM
connectivity, docker-daemon liveness, Traefik auto-restart, managed PG/Redis liveness, data-dir
disk %, per-app HTTP/TCP/process checks with OOM-precheck + startup grace, LLM diagnosis with
scrub+router, in-flight opt-in safe-autofix with backoff+verify. This is a solid
**liveness-of-known-containers** layer. The gaps are in the strata *underneath* (the host
substrate) and *around* it (the data's recoverability).

## 2. Oversight surface — by failure stratum (value×risk, 1–5)

### Stratum 0 — Host substrate (biggest hole; `system_eval.py` already has the probes, wired to install-time not the runtime cycle)
- **Filesystem-fill, ALL critical paths** (`/`, `/var/lib/docker`, `MS_DATA_DIR`, each app's `config_root`/`media_root`) — today only `data_dir` is watched; a full `/var/lib/docker` wedges *every* container. Alert + optional dangling-image prune (reversible). **5×2**
- **Inode exhaustion** (`statvfs.f_favail`) — green-by-bytes while writes fail. **4×1**
- **Memory pressure / OOM-kills** (`MemAvailable` + `/proc/pressure/memory` PSI + journal `oom-kill`) — the agent's own box can be the victim. Restart the hog (gated). **5×2**
- **Swap death-spiral** — alive in `docker ps`, unresponsive. Alert only. **4×1**
- **CPU load / thermal** (`loadavg`, `/sys/class/thermal`). Alert. **3×1**
- **The `mediastack` systemd unit itself** (`is-active`/`is-failed`/restart-count) — the agent runs *inside* this unit and cannot self-report its own crash-loop → needs an out-of-process watchdog (see §4). **5×2**
- **Clock skew** (chrony/timedatectl offset) — silently breaks TLS, TOTP (Vaultwarden), JWT, cert renewal. **4×1**

### Stratum 1 — Container substrate (quality beyond "is it up")
- **Restart-loop / flapping** (docker `RestartCount` + `StartedAt`) — "running" while restarting every 20s. **5×2**
- **Image drift / `:latest` digest moved** — notify only; **never auto-update**. **4×2**
- **Stopped-but-should-run** (generalize managed-services reconciliation to all tier-2/3 apps). Restart (gated). **4×2**
- **Orphaned/dangling resources** — `docker image prune` (reversible); **never** `volume prune`. **4×2**
- **Compose-fragment-vs-running drift** — SLOP authored the fragments, so this is a uniquely-available GROUND XREF (catches SLOP bugs + out-of-band `docker run`). **3×2**

### Stratum 2 — Data recoverability (≈0% covered today — and "recoverable" is HALF the mandate)
- **Backup existence / freshness** — *derive* which installed apps hold irreplaceable state (Vaultwarden vault, Immich photos+PG, Paperless, actual_budget, Vikunja); GROUND-probe whether a recent backup artifact exists + is fresh; **no target configured → red**. The agent **detects absence** (red-when-stale), it does **NOT** run backups. **#1 GAP. 5×1**
- **DB integrity** — `pg_isready` extended to app-owned Postgres (Immich ships its own) + SQLite `PRAGMA quick_check`. Alert only; repair is destructive. **5×1**
- **SMART prefail + parity staleness** (catalog ships `scrutiny` + `snapraid_ui`) — reallocated/pending sectors, SMART=FAILED, SnapRAID parity older than N days = unprotected. Detect only; **never** touch parity. **5×1**
- **Volume mount health** (`/proc/mounts`: expected source mounted + non-empty) — a vanished bind-mount makes the container write into the empty mountpoint on the root disk, "healthy" while it diverges data and fills `/`. Remount heal exists (gated). **5×2**

### Stratum 3 — Connectivity & exposure
- **TLS cert expiry** (parse notAfter) — calendar-triggered total inaccessibility. **5×1**
- **Reverse-proxy end-to-end routing** (404/502 at the public URL while the container is up). **4×2**
- **Unexpected port exposure** (`/proc/net/tcp` LISTEN on `0.0.0.0` post-install — run the port linter at *runtime*) — an accidentally-public Vaultwarden. Alert only; **never auto-firewall**. **5×1**
- **DDNS staleness** (resolve configured hostname vs public IP). **3×1**

### Stratum 4 — The agent's own integrity (raised stakes once S-64 autofix lands)
- **Global autofix circuit-breaker** — a GROUND fixes-per-hour counter across ALL apps. S-60's backoff is *per-app*; a correlated outage (disk full → 12 apps unhealthy → 12 simultaneous restart storms) trips no per-app cap. **Highest-risk new surface; per-app guards do NOT compose into a global guard. 5×3** → land *with* S-64.
- **LLM cost runaway** (rolling spend/token meter + hard ceiling → local-only fallback). **4×2**
- **Scrub-effectiveness as a LIVE probe** — assert no `<IP>`/`<PATH>`-class token escaped on the actual outbound payload (the runtime GROUND version of S-61's unit-tested gate). **4×2**

## 3. Top "silent killers" (box looks green in `docker ps`, then you lose something)
1. **No backup-existence/freshness probe** — recoverability is unprobed. **#1.**
2. **SMART prefail + parity staleness** — deaf to the loudest physical warning.
3. **TLS cert expiry / clock skew** — calendar-triggered total/auth outage.
4. **Vanished bind-mount writing to root disk** — corrupts data + fills host at once.
5. **`/var/lib/docker` (not `MS_DATA_DIR`) + inode fill** — watching the wrong disk/dimension.
6. **OOM / swap storm on the host** — per-container probes can't see "the floor is on fire."
7. **`mediastack` unit crash-loop** — the agent can't observe its own death.
Five of seven (1,2,3,4,6) are **read-only GROUND probes with zero remediation risk** — high value, low blast.

## 4. OVERREACH — what the agent must NOT take on (guardrails)
- **Owning a backup *engine*** — detect absence/staleness only; running/encrypting/moving data off-box is a stateful subsystem + privacy surface. NO.
- **Auto-updating images** — notify of drift; auto-pull-and-restart on `:latest` is a top footgun. NO.
- **Auto-firewalling / closing ports** — could lock the operator out. Detect + alert only.
- **Repairing DBs / `fsck` / SnapRAID fix** — destructive; turns "degraded" into "destroyed." Detect only.
- **Reading docs/process to pick a fix** — *two-owner firewall breach.* The agent derives intent from physics + the manifest it already reads, never from doctrine/runbooks.
- **Self-training fix policies from history** — `fix_history` is for backoff/audit, not learned fix-selection. Keep selection deterministic/rule-based (the router registry is the model).
- **Generic exec / MCP tool-sprawl** — every remediation is a named, bounded, gated action (`SAFE_FIX_TYPES`).
- **LLM as authority** — the GROUND probe + deterministic rule decides; the LLM only *explains*. Never "ask the model whether to apply."

## 5. Non-obvious surfaces a typical reviewer misses
1. The agent **can't observe its own death** (it IS the systemd unit) → needs a tiny *out-of-process* watchdog (`OnFailure=` hook / external pinger). Recognizing it can't live inside the agent is the insight.
2. **Inodes and `/var/lib/docker` are different disks** than the one watched — "we check disk" is true and nearly useless.
3. **Clock skew is an invisible multiplier** — one cheap probe preempts a whole class of scattered TLS/TOTP/JWT ghost bugs.
4. **Per-app backoff ≠ global circuit-breaker** — hides behind a green per-unit guard; the highest-risk gap once S-64 lands.
5. **A vanished bind-mount fails *upward*** (writes to root, stays "healthy") — the probe is "is `/proc/mounts` showing the source, non-empty?", not "is the app up?".
6. **SLOP authored the compose fragments** → fragment-vs-running drift is a GROUND XREF few platforms can do.
7. **"Recoverable" is half the mandate and gets ~0% of the surface** — the agent answers "is it up?" and never "if the disk dies in the next hour, what do I lose?"

## 6. Manager synthesis — prioritized roadmap
- **First expansion wave = a read-only host-substrate + recoverability probe pack:** backup-freshness, SMART/parity, mount-health, multi-path+inode disk, OOM/PSI, cert-expiry, clock-skew. Every one is a pure GROUND probe with **alert-only** remediation → full value, near-zero risk budget, each "goes red against physics." (This supersedes the Manager's earlier top-3 with a tighter, evidence-backed set.)
- **One mandatory GUARD, not a probe — expedite with S-64:** the **global autofix circuit-breaker**. Per-app backoff demonstrably doesn't compose into outage-wide safety; this should ride *with* the autofix wave, not after.
- **The self-audit/spine wave establishes the reusable spine** (reconcile→interpret→remediate + the fail-closed sanitizer + ms-router review) that all strata plug into. Design decisions locked 2026-05-30: GROUND floor always-on; LLM review opt-in/default-most-private; provider-registry default on-host/own-key, free-tier opt-in behind a fail-closed sanitizer with a red-path test.
- **Future schedule:** strata 1–4 remaining items land in subsequent agent-expansion waves, each reusing the spine. Sequence after the spine wave; re-eval the roadmap at each agent-batch landing.
- **Firewall check:** every surface here is runtime/physics-derived; none requires the agent to read docs/process. The rejected items (§4) are exactly those that would breach the firewall, no-self-training, or privacy.
