# S-74-DEPLOY-HARDENING — Fix the genuinely-broken `ms-update` / `deploy.sh` path

## Goal
Make the in-place update path (`ms-update` + `deploy.sh --update`) actually work
on a standard install, instead of silently doing nothing. On 2026-05-29 a live
update of the Rocinante test server (`/opt/mediastack`, service user `mediastack`,
HTTPS git clone) required ~10 manual recovery steps because `sudo ms-update`
swallowed its own failure and several baked-in assumptions were wrong. Every item
below is a confirmed, reproduced bug — not speculation (forensics in
`docs/BACKLOG.md` §"From Rocinante deploy session" + memory `project-rocinante-deploy`).

End state:
- `ms-update` and `deploy.sh` run all file-touching git/pip/npm as the **service
  user** (root only for `systemctl`), surface fetch failures instead of eating them,
  recover a history-rewrite-diverged clone via `fetch` + `reset --hard origin/main`,
  and build the frontend with a writable `HOME`.
- Ownership, build-HOME, and the service port have ONE canonical name/convention
  shared across both scripts (pinned below).
- The `.env`-vs-systemd config mechanism for `os.environ`-read operator settings
  (`MS_TRUSTED_HOSTS`, `DOMAIN`) is decided and implemented as ONE coherent model.
- Install/update docs match the real model, plus a "recover a stale/diverged clone"
  runbook.

## Context
- **`sudo ms-update` silently no-ops.** It runs git as root on a service-user-owned
  repo → git's "dubious ownership" guard fails; its unguarded
  `git -C "$REPO" fetch origin main --quiet 2>/dev/null` (ms-update line 64) eats
  stderr, and `set -euo pipefail` (line 11) then exits with no output → blank
  prompt, no update. The existing `reset --hard origin/main` fallback (lines 72–77)
  is never reached because the fetch dies first.
- **Ownership churn.** The service runs as `mediastack`; doing git/login ops as
  `stack` or root keeps colliding (root-owned `.git/FETCH_HEAD`; a blanket
  `chown stack` made `.env` (mode 600) unreadable → crash-loop
  `PermissionError: '.env'`). ms-update line 96 already self-detects the owner via
  `stat -c %U`, but only uses it for an end-of-run chown — the top-of-script git
  still runs as the invoking (root) user. `deploy.sh` chowns to `$REAL_USER`
  (the invoking login user, line 33), not the service user.
- **History-rewrite divergence.** Clones from before the 2026-05-28 tailscale-key
  history rewrite are diverged from `origin/main`; `git pull` cannot fast-forward —
  only `fetch` + `reset --hard origin/main` works. `deploy.sh --update` uses a bare
  `git pull origin main` (line 76) with no reset fallback at all.
- **Frontend build needs a writable HOME.** `mediastack` is a system user with
  `HOME=/nonexistent`; `npm ci` / `npm run build` fail (`EACCES mkdir '/nonexistent'`).
  Neither `deploy.sh` (lines 78, 87, 149) nor the update path sets `HOME`. And
  `backend/static/` is a gitignored build artifact — a `reset --hard` deletes the
  old built copy, so the build MUST run on every update, not be skipped.
- **Port-var mismatch.** `deploy.sh` bakes the systemd `--port` from `MS_PORT`
  (default 8080, line 34) and writes `MS_PORT=` into `.env` (line 175); `ms-update`
  reads `MEDIASTACK_PORT` from `.env` for its health-check port (lines 194, 256). A
  `.env` carrying only `MS_PORT` makes ms-update silently fall back to 8080.
- **`.env` vs systemd `Environment=` for operator settings.** `MS_TRUSTED_HOSTS`
  and `DOMAIN` are read via `os.environ` (`backend/api/main.py` line 272 uses
  `_os_th.environ.get("MS_TRUSTED_HOSTS", "")`), NOT via the Starlette `Config`
  path in `backend/core/config.py`. Whether editing `.env` works for these depends
  entirely on whether the running unit carries `EnvironmentFile=`: `deploy.sh`'s
  generated unit DOES (line 268), but the Rocinante unit's observed behaviour says
  it did not take effect — an ambiguity Stream C must resolve on the real box and
  collapse into ONE documented model. This is the wave's load-bearing judgment call.
- **Verification reality:** these are shell/install scripts that cannot be exercised
  in CI against a real server (the same gap the parked "install.sh test wave" covers).
  Verification is `shellcheck` + logic review + guarded dry-run + targeted Python
  unit tests — pinned in Verification below.
- **Processor-pattern contract applies** (`.claude/AUTONOMOUS-DEFAULTS.md`
  §"Processor-pattern contract"): A and B share three symbols and consume one
  decision from C. All four are PINNED verbatim in Deliverables so no stream drifts
  the interface.

## Rules to follow
- **Apply-script constraints** (CLAUDE.md §"Apply scripts / SSH"): any new Python
  helper is plain Python — no f-strings, no `{}` dict literals in apply-script code;
  no multi-line bash in SSH double-quoted args; no multi-line `python3 -c`.
- **Bash safety.** Both scripts keep `set -euo pipefail`. The fix is NOT to relax
  error handling globally — it is to stop *suppressing* the specific fetch errors
  (drop `2>/dev/null` or capture+surface) and to guard the genuinely-optional steps
  explicitly. Every git/pip/npm that touches files runs as the service user.
- **Backward compatibility.** A `.env` written by an older `deploy.sh` (carrying
  `MEDIASTACK_PORT` or only `MS_PORT`) must still resolve a correct port — read the
  canonical name first, fall back to the legacy name with a one-line deprecation
  note. Do not break existing installs.
- **Idempotence.** `ms-update` and `deploy.sh --update` must be safe to run
  repeatedly and must converge a diverged clone, not error out on it.
- **Pin before drift.** No stream invents a shape for a shared symbol. The four
  pins in Deliverables are binding; if a stream finds a pin wrong or impossible it
  HALTS and writes a blocker (the wave file is wrong) rather than guessing a new
  shape at runtime (`.claude/AUTONOMOUS-DEFAULTS.md` §"Processor-pattern contract").
- **Single source of truth for ownership.** Exactly one helper owns service-user
  detection + ownership normalization; both scripts call it. No second copy drifts.

## Authorized deletions
None. This wave is additive + in-place edits to two existing scripts (`ms-update`,
`deploy.sh`), one new shared shell helper, one new docs file, and new tests. No
files are removed. (The `2>/dev/null` and bare `git pull` lines are *edited away*,
not file deletions.)

## Parallelization

**Models (per-wave default):** coordinator = **opus** (the wave touches two
load-bearing install scripts with no CI safety net and a cross-stream config
decision; merges need synthesis), subagents = **sonnet** unless the per-stream
`Model` column below overrides.

Four streams. A authors the shared helper + the env-decision-consuming half of
`ms-update`; C produces the env-mechanism decision. B and D consume pinned
contracts, so all four dispatch in parallel — consumers build against the pin
rather than waiting for the producer to merge.

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A — `ms-update` rewrite + shared helper | **opus** | parallel | `general-purpose` in worktree | Author the shared `tools/deploy_lib.sh` helper (service-user detection + build-HOME + ownership normalize); rewrite `ms-update` to run as the service user, guard+surface the fetch, reach the reset fallback, build with a writable HOME |
| B — `deploy.sh` alignment | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Source the same helper; chown to the service user (not the login user); canonicalize the port var; set build-HOME; add a `--update` fetch+reset fallback |
| C — config-mechanism decision | **opus** | parallel | `general-purpose` in worktree | Resolve `.env`-vs-systemd-`Environment=` for `MS_TRUSTED_HOSTS`/`DOMAIN`, implement ONE model, produce the operator-env contract A/B consume |
| D — docs + recovery runbook | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Update `docs/INSTALL.md` to the real ownership/update model; write a new `docs/DEPLOY.md` "recover a stale/diverged clone" runbook reflecting C's decision |

**Per-stream Model justification (one line each — required by the rubric in `.claude/ROBOT.md` §"Per-stream Model column"):**
- **A = opus** — ambiguous root-cause (a `set -euo pipefail` script that fails
  *silently* by eating stderr) plus load-bearing shell that has no CI to catch a
  plausible-but-wrong rewrite; the helper it authors is the contract B consumes.
  (Rubric: ambiguous root-cause + load-bearing + plausible-but-wrong-passes-no-tests.)
- **C = opus** — the `.env`-vs-systemd model is an irreducible judgment with
  contradictory evidence (the unit carries `EnvironmentFile=` yet the operator
  setting didn't take effect); a wrong call silently breaks operator config and the
  coordinator can't catch a plausible-but-wrong decision. (Rubric: ambiguous
  root-cause / cross-stream decision the coordinator can't catch.)
- **B = sonnet (inherit)** — bounded implementation against A's three pinned shell
  contracts and C's pinned env contract; the coordinator (opus) reviews the merge.
  (Rubric: bounded implementation to a clear spec — the default.)
- **D = sonnet (inherit)** — bounded technical writing that transcribes the resolved
  facts + the verified recovery steps into docs; no irreducible judgment it makes
  alone. (Rubric: bounded implementation to a clear spec.)

## Complexity & Pre-flight
**Tier: High.** Signals: 4 streams; four PINNED shared-symbol contracts spanning
A↔B and C→A/B; two Opus streams; touches doctrine path `.claude/ROBOT.md` (Robot
mode) and security-adjacent ownership/`.env`-permission logic. Any one of {shared
symbols, sensitive paths, Opus stream} pushes toward High; all three present ⇒
High (floor guarantee in `tools/wave_complexity.py`).

**Rigor applied (per `.claude/ROBOT.md` §"Complexity-gated pre-flight"):** High =
`tools/validate-wave-file.py` (mechanical path/ref gate) + one fact-check subagent
(any claim proven FALSE against the live repo BLOCKS dispatch) + processor-contract-
pinned check (every shared symbol pinned in Deliverables) + cross-wave disjointness
+ edited-wave consistency. `tools/preflight_wave.py` writes the verdict to
`.claude/run/preflight/S-74-DEPLOY-HARDENING.md`; dispatch proceeds only on
DISPATCH-OK.

## Deliverables per stream

### Stream A — `ms-update` rewrite + shared `tools/deploy_lib.sh` helper
1. **Shared helper `tools/deploy_lib.sh` (new file; PINNED interface — A produces,
   B sources verbatim).** A POSIX-bash library, `source`-able from both scripts,
   exposing exactly these three contracts. No stream may redefine them inline:
   - **`detect_service_user <install_dir>`** — echoes the canonical service user,
     resolved in this PINNED order: `stat -c %U <install_dir>` → else
     `systemctl show mediastack -p User --value` → else literal `mediastack`. Callers
     assign `SVC_USER="$(detect_service_user "$INSTALL_DIR")"` and run every
     file-touching git/pip/npm via `sudo -u "$SVC_USER" …`; root is used ONLY for
     `systemctl`.
   - **`build_home`** — echoes the canonical writable build HOME for the service
     user: `"${MS_BUILD_HOME:-/tmp}"`. Every `npm` invocation runs as
     `sudo -u "$SVC_USER" env HOME="$(build_home)" npm …`.
   - **`normalize_ownership <install_dir> <svc_user>`** — chowns the tree to
     `<svc_user>:<svc_user>` and re-asserts `.env` mode 600. This is the SINGLE
     ownership normalizer; it also resolves the currently-dangling
     `tools/normalize-ownership.sh` reference at ms-update line 97 (point that call
     site at this helper, or create `tools/normalize-ownership.sh` as a thin shim
     that sources it — A's choice, but the dangling reference must resolve).
2. **Rewrite `ms-update`'s git sync:**
   - Run the fetch/pull/reset as the service user: `sudo -u "$SVC_USER" git -C "$REPO" …`.
   - STOP swallowing fetch errors: drop the `2>/dev/null` on the fetch (line 64) —
     capture stderr and surface it on failure. The script must report "fetch failed:
     <reason>" rather than dying silently under `set -e`.
   - Ensure the `fetch` + `reset --hard origin/main` recovery path is actually
     reachable on a diverged (history-rewritten) clone — it must not be gated behind
     a fetch that already died.
   - **Post-update SHA-verify (fail loud) — rider from the S-75 K-L audit:** after the
     fetch + pull/reset, assert local `HEAD` == `git rev-parse origin/main`; on
     mismatch, exit non-zero with a loud message (NOT a soft warn). A green "updated"
     must be able to go red against physics — this is the GROUND-class check that
     feeds S-75's `check_handoff_freshness`.
3. **Build with a writable HOME:** any `npm ci` / `npm run build` ms-update triggers
   runs as `sudo -u "$SVC_USER" env HOME="$(build_home)" npm …`. Because
   `backend/static/` is gitignored, the frontend build runs on every update where
   frontend files changed (do not skip it on a `reset --hard`).
4. **Canonical port var (consumes PINNED contract from B's deliverable 2):**
   ms-update reads the canonical `MS_PORT` first, falling back to legacy
   `MEDIASTACK_PORT` with a one-line deprecation note (lines 194, 256).
5. **Consumes C's PINNED operator-env contract:** ms-update's messaging about where
   `MS_TRUSTED_HOSTS`/`DOMAIN` live matches C's decided model (no claim that editing
   `.env` works if C decides it does not).

### Stream B — `deploy.sh` alignment
1. **Source the shared helper:** `source "$INSTALL_DIR/tools/deploy_lib.sh"` and use
   `detect_service_user` / `build_home` / `normalize_ownership` — do NOT reimplement
   them. `SERVICE_USER` becomes `$(detect_service_user "$INSTALL_DIR")` (the service
   user), NOT `$REAL_USER` (the invoking login user, current line 33). The install-dir
   chown (lines 130, 233) targets the service user.
2. **Canonical port var (PINNED — B owns the name; A + D consume it):** the canonical
   service-port env var name is **`MS_PORT`** (default `8080`). `deploy.sh` already
   bakes the unit `--port` from `MS_PORT` and writes `MS_PORT=` into `.env` — keep
   that as the source of truth. ms-update (A) is the side that changes to read
   `MS_PORT`. Docs (D) use `MS_PORT` everywhere. Legacy `MEDIASTACK_PORT` is read
   only as a deprecated fallback.
3. **Build-HOME in every build path:** the `--update`, `--frontend-only`, and full
   build paths run `npm` as `sudo -u "$SVC_USER" env HOME="$(build_home)" npm …`.
4. **`--update` fetch+reset fallback:** replace the bare `git pull origin main`
   (line 76) with `sudo -u "$SVC_USER" git -C "$INSTALL_DIR" fetch origin main`
   followed by a fast-forward attempt and a `reset --hard origin/main` fallback when
   the clone is diverged — mirroring A's ms-update recovery logic (the two must agree).
5. **Consumes C's PINNED operator-env contract:** if C decides operator env lives in
   the systemd unit, `deploy.sh`'s generated unit + any wizard path set it the way C
   specifies; if C decides `.env` is authoritative, `deploy.sh` ensures the mechanism
   (e.g. `EnvironmentFile=` / `load_dotenv`) is wired.

### Stream C — config-mechanism decision (`.env` vs systemd `Environment=`)
1. **Resolve the real mechanism on the box / from the code:** confirm how
   `MS_TRUSTED_HOSTS` and `DOMAIN` (read via `os.environ` in `backend/api/main.py`)
   actually reach the process — reconcile the contradiction that `deploy.sh`'s unit
   carries `EnvironmentFile=` yet the Rocinante operator setting did not take effect.
2. **Decide ONE model and PIN it (PINNED — C produces, A + B + D consume):** either
   - **(a) `.env` is authoritative** — call `load_dotenv()` (or keep/repair the
     systemd `EnvironmentFile=`) at startup so editing `.env` works as the docs imply,
     OR
   - **(b) systemd `Environment=` is authoritative** — document that operator-facing
     env (trusted hosts, domain) lives in the unit, and give `deploy.sh` / the wizard
     a clean, idempotent way to set it.

   The decision is recorded as a short rationale (in `docs/DEPLOY.md` via D, or a
   one-paragraph ADR-style note) AND as the **operator-env contract** A/B/D consume:
   "operator env `MS_TRUSTED_HOSTS` / `DOMAIN` is set via `<mechanism>`; the
   canonical edit point is `<file/command>`."
3. **Implement the chosen model** in `backend/api/main.py` and/or `backend/core/config.py`
   (a) or in `deploy.sh`'s unit-generation (b) — minimally and backward-compatibly.
4. **Targeted Python unit test** asserting the chosen model resolves
   `MS_TRUSTED_HOSTS` as documented (e.g. monkeypatch `os.environ` / a tmp `.env`,
   never touch a real install).

### Stream D — docs + recovery runbook
1. **New file `docs/DEPLOY.md`** — the canonical ownership + update model: install
   dir owned by the service user; ALL file ops via `sudo -u <svc_user>`; root only
   for `systemctl`. Includes the **"recover a stale/diverged clone" runbook** (the
   verified manual sequence: chown to service user → fetch → `reset --hard
   origin/main` → pip → `env HOME=… npm ci && npm run build` → restart) so a diverged
   pre-rewrite clone is recoverable by hand if `ms-update` ever fails again.
2. **Update `docs/INSTALL.md`** to the real model: HTTPS git clone at the install dir
   updated via `ms-update` / `deploy.sh --update`; canonical `MS_PORT`; the
   operator-env edit point per C's PINNED contract. (CLAUDE.md's stale "no git on
   server" fact was already corrected in `90bf54f`; D aligns INSTALL.md to match.)
3. **Cross-reference** the runbook from `docs/BACKLOG.md`'s "From Rocinante deploy
   session" entries when they flip to done at merge (coordinator/post-wave audit).

## Verification
1. **Verification caveat (PINNED — these scripts cannot run in CI against a real
   server).** Acceptance for the shell changes is the four-part gate, NOT a green CI
   run that exercises a live update:
   - `shellcheck ms-update deploy.sh tools/deploy_lib.sh` is clean (no new warnings).
   - **Logic review** by the coordinator: every git/pip/npm runs as `$SVC_USER`;
     `systemctl` is the only root op; no `2>/dev/null` remains on the fetch; the
     `reset --hard origin/main` path is reachable on a diverged clone.
   - **Guarded dry-run:** `bash ms-update --help` and `bash deploy.sh --help` exit 0
     and touch nothing; sourcing `tools/deploy_lib.sh` and calling
     `detect_service_user` / `build_home` in a scratch dir returns the expected
     values without mutating the repo.
   - **Targeted Python unit tests** where Python is involved (C's config test + the
     cross-script consistency test below) pass under `tmp_path`.
2. `python3 -m pytest tests/test_deploy_hardening.py -v` — a new test asserting:
   `ms-update` and `deploy.sh` reference the SAME canonical port var (`MS_PORT`);
   neither contains a `git fetch` with `2>/dev/null` on the update path; both invoke
   the shared helper rather than an inline duplicate. (Static/grep-style assertions
   over the script text — no live server.)
3. **Shared-symbol contracts hold:** `tools/deploy_lib.sh` defines exactly
   `detect_service_user`, `build_home`, `normalize_ownership`; both `ms-update` and
   `deploy.sh` source it and contain no second copy of the detection logic.
4. **Port-var contract holds:** the canonical name `MS_PORT` appears in both scripts'
   read paths; `MEDIASTACK_PORT` appears only as a clearly-marked deprecated fallback.
5. **Operator-env contract holds:** A's messaging, B's unit generation, and D's docs
   all describe C's single decided mechanism — no contradictory claim about whether
   editing `.env` works for `MS_TRUSTED_HOSTS` / `DOMAIN`.
6. `python3 ms-enforce` exits 0 — no new warnings from the doctrine/docs edits.
7. `python3 tools/wave_complexity.py .claude/waves/S-74-DEPLOY-HARDENING.md` exits 0
   and prints `High` as its final line; `python3 tools/validate-wave-file.py
   .claude/waves/S-74-DEPLOY-HARDENING.md` passes; `python3 tools/preflight_wave.py
   .claude/waves/S-74-DEPLOY-HARDENING.md` ends DISPATCH-OK.
8. `docs/DEPLOY.md` exists with the ownership model + the diverged-clone recovery
   runbook; `docs/INSTALL.md` reflects the real git-clone update model and `MS_PORT`.

## Out of scope
- **A full install.sh / DinD / snapshot-VM integration-test harness.** The
  verification caveat is the honest gap here; building real end-to-end deploy testing
  is the parked "install.sh test wave" (memory `project-future-installer-test-wave`),
  NOT this wave. This wave hardens the scripts and tests what is statically testable.
- **Rewriting the systemd unit layout or the data-dir migration logic.** Only the
  port var, ownership, build-HOME, fetch/reset, and operator-env mechanism change.
- **The wizard UI for setting operator env.** C may give `deploy.sh` a clean hook,
  but a frontend wizard surface for trusted-hosts/domain is a separate effort.
- **Touching the agent / catalog / health subsystems.** Strictly the deploy path.
- **Retro-fitting other servers.** The fixes are general; no server-specific config
  is committed (Rocinante specifics stay in memory `project-rocinante-deploy`).

## Cross-wave dependencies (EXPLICIT)
- Depends ONLY on current `origin/main` (post-batch-8 as of 2026-05-29). The
  orchestrator re-confirms `git rev-parse origin/main` at startup and rebases the
  wave branch if main has advanced.
- **No upstream code dependency on an unmerged wave.** S-74 is batch-9; batch-8
  (Test-Data-Hygiene) is already merged to main. S-74 touches deploy scripts +
  `backend/api/main.py` / `backend/core/config.py` (C's minimal config change) +
  docs — file-disjoint with the not-yet-drafted Enforcement-Lifecycle wave (which
  touches `tools/audit_*.py` + doctrine, not deploy scripts).
- **Intra-wave shared touch-points** (all pinned above; resolved keep-both per
  `.claude/AUTONOMOUS-DEFAULTS.md` §"Intra-wave merge conflict"):
  - `tools/deploy_lib.sh` — A produces the three functions; B sources them (no edit).
  - Canonical port var `MS_PORT` — B owns the name; A's read path + D's docs consume it.
  - Build-HOME convention `${MS_BUILD_HOME:-/tmp}` — A defines it in the helper; B uses it.
  - Operator-env mechanism — C decides; A (messaging), B (unit/`.env` wiring), D
    (docs) all consume the one decision. C is the only stream that resolves it.
  - `docs/DEPLOY.md` is created solely by D; `docs/INSTALL.md` edited solely by D.
  - `backend/api/main.py` / `backend/core/config.py` touched solely by C (option a).

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine. Four streams (A–D), all parallel from
start — every shared symbol is pinned, so B/D build against A's helper and C's
decision rather than waiting for a merge. Coordinator merges all streams to
`wave/S-74-deploy-hardening` in a dedicated `.claude/worktrees/merge-S-74` worktree
(detached HEAD), never main. The knowingly-shared files are `ms-update` (A) and
`deploy.sh` (B) — disjoint primary ownership, but both `source tools/deploy_lib.sh`
(A's file), so merge A first, then B rebases onto it; resolve any additive overlap
keep-both at the whole-block level (NEVER `merge=union`) and log a `S-74-MERGE-N.md`
decision. C's `backend/` edit and D's docs are file-disjoint. Because there is no CI
that runs these scripts live, the coordinator's logic review (Verification §1) is a
hard merge gate, not advisory. Post-wave merge to main goes through
`python3 tools/merge_wave_to_main.py wave/S-74-deploy-hardening`; on merge, flip the
six `[→ S-74]` entries in `docs/BACKLOG.md` to done.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-74-DEPLOY-HARDENING.md as orchestrator.`
