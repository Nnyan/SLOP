# ADR 0015 — First-Run Readiness Contract

- **Date:** 2026-05-15
- **Status:** Accepted
- **Deciders:** operator, Claude Opus 4.7 (v5 Tier 3.1 design session)

## Context

Tier 2 of the v5.0 installer arc closed at commit b95016b with the install pipeline producing a `mediastack` system user, a populated `/opt/mediastack`, a populated `/var/lib/mediastack`, a running `mediastack.service` systemd unit, and a state file at `phase: "installed"`. None of those facts answer the question "can an operator open a browser to the wizard right now." A systemd unit that is `active (running)` can be a backend that has crashed and is restarting, or a process that has bound a port without yet serving requests, or a process serving requests against an empty SPA build with no UI to drive. The Tier 2 close exit code was 0; the operator's browser experience was unverified.

Tier 3's job is to close that gap. Step 3.1 (this ADR) defines the contract: what propositions an external observer must be able to verify before the install is considered ready for first browser visit. Step 3.2 (V5_INSTALLER_PLAN.md) implements the mechanical smoke test against the contract. Step 3.3 runs the smoke test against three target distros. The contract is the load-bearing piece — Sonnet's Step 3.2 implementation work is mechanical against a tight contract and judgment-laden against a loose one.

The contract is observable. Every predicate it specifies must be checkable by an HTTP client and a `systemctl` invocation; nothing requires a headless browser, a screenshot diff, or operator inspection. The wizard's behavior under user interaction is not v5.0's scope (per V5_INSTALLER_PLAN.md Tier 3 framing); v5.0's scope is "the bytes the wizard depends on are being served correctly." Observability is the line between "this contract" and "the wizard's own quality bar."

The contract composes with three pieces of existing v5 contract surface: ADR 0013 §1 (path layout — the install dir, data dir, and systemd unit name are inputs), ADR 0013 §2 as amended in the companion commit (state-file lifecycle — the smoke test writes `smoke_test_passed: true` and is the only writer of that field's `true` value), and ADR 0013 §4 (refusal logic — the new state combination `phase: "installed"` + `smoke_test_passed: false` needs explicit handling). §5 and §7 of this ADR formalize those compositions; the rest of 0013 is unchanged.

## Scope

In scope: the readiness predicates, their timing budgets, their response-shape signatures, their failure-mode messages, the smoke test's write to the state file, the refusal-logic composition for `installed` + `smoke_test_passed: false`, and the `POST_INSTALL.txt` post-install handoff artifact (contents, location, lifecycle).

Out of scope and tracked elsewhere:

- *What the wizard does when the operator interacts with it.* This ADR stops at "the SPA is served correctly and the QuickStart router is mounted and responsive." Beyond that is the wizard's own UX, which predates v5 and has its own quality bar.
- *Headless browser-driven end-to-end testing.* Per V5_INSTALLER_PLAN.md Step 3.3.a, the manual "verify wizard loads in a browser" check is a sanity probe by the human operator running the install on a VM; it is not part of the mechanical smoke test or the audit-gate-mode check. Automating it is v5.1+ work under its own ADR.
- *Re-running the smoke test on demand (`mediastack smoke` subcommand).* The smoke test as defined here runs once, at install time, as the final step of `install.sh`. A standalone smoke-rerun subcommand for operators who want to re-verify after a host restart or after debugging is a v5.1 candidate; see "Alternatives considered." The two-field state model in ADR 0013 §2 makes adding it mechanical when it's wanted.
- *Health-monitoring beyond first-run.* The mediastack backend has its own health subsystem (`backend/health/`), Prometheus instrumentation (`/metrics`), and K8s-style probes (`/healthz`, `/readyz`, `/startupz`). Those probes are *inputs* to this contract — the smoke test reads them — but their own evolution is the backend's concern, not the installer's. If the backend changes a probe's response shape, this ADR's §3 needs an amendment; that's a known coupling point.
- *Selecting the specific QuickStart endpoint URL for §1 predicate P5.* The QuickStart router exists at `/api/v1/quickstart/...` (dual-mounted at `/api/quickstart/...` for legacy compatibility) per `backend/api/main.py`. The exact non-mutating GET endpoint within the router that the smoke test probes is Step 3.2's first design call: it must be safe to call before the wizard is touched, must not require auth state, and must return a documented JSON shape. Naming it here would couple this contract to a specific router internal; the contract names the property ("a non-mutating QuickStart GET returns 200 with `Content-Type: application/json`") and Step 3.2 picks the URL.

## Decision

## §1 — Readiness predicates

Five predicates, evaluated in order. Each is independently observable; later predicates depend on earlier ones being true but are not implied by them. The order is the order Step 3.2 implements; earlier failures short-circuit later checks because they make later checks meaningless (a port that isn't bound can't serve `/healthz`).

| # | Predicate | Owner | Source of truth |
|---|---|---|---|
| P1 | systemd unit `mediastack.service` reports `active (running)` | systemd | `systemctl is-active mediastack.service` exits 0 |
| P2 | The configured HTTP port is bound on `127.0.0.1` by a process owned by the `mediastack` user | kernel | `ss -ltnp` (or equivalent) shows the port and PID; PID matches `systemctl show -p MainPID` for the unit |
| P3 | `GET /healthz` returns HTTP 200 with the documented liveness shape | `backend/api/probes.py` | response status + JSON validates against the shape contract in §3 |
| P4 | `GET /startupz` returns HTTP 200 with `startup_complete: true`, AND `GET /readyz` returns HTTP 200 with `status: "ok"` and `checks.db_ping: "ok"` | `backend/api/probes.py` | both responses status + JSON validate; the conjunction is one predicate because the two probes answer two halves of "startup truly finished and the backend can serve real requests" and either alone is insufficient |
| P5 | `GET /` returns HTTP 200 with an HTML body matching the SPA signature defined in §3, AND a non-mutating QuickStart `GET /api/v1/quickstart/<endpoint>` returns HTTP 200 with `Content-Type: application/json` | backend SPA-fallback + QuickStart router | response status + body shape; specific QuickStart endpoint chosen at Step 3.2 implementation time per Scope note above |

P1 is the cheapest check and the most common failure mode (a unit that crash-looped past systemd's restart budget reports `failed` or `activating`). P2 catches the narrow case where the unit is `active` because the process started but hasn't yet bound the socket — a 1-3 second race window. P3 catches the process being up without the FastAPI app having installed routes (rare but real if `lifespan` raised during startup). P4 catches the DB-not-reachable case, which is the F16 failure mode (data dir not writable → lifespan's `init_db` raises → `readyz` reports `db_ping` failure even though the process is otherwise up). P5 catches the frontend-not-built case (`/` returns 503 with the documented "Frontend not built" detail) and the QuickStart-router-not-mounted case (any HTTP error on a route that should be 200).

The five predicates together answer five distinct operational questions: "Is the process supervised?" (P1), "Has the socket actually come up?" (P2), "Is the FastAPI app installed?" (P3), "Did startup complete and is the database reachable?" (P4), "Is the operator-visible surface — frontend bytes and QuickStart API — being served?" (P5). A passing smoke test means yes to all five.

## §2 — Timing budget

The smoke test runs once, after `service_install` and before the state file's third write. Its total wall-clock budget is **30 seconds** from first probe to final result. Within the budget, predicates are evaluated as follows:

| Predicate | Initial delay | Per-attempt timeout | Retry policy |
|---|---|---|---|
| P1 | 2s (allow systemd's start sequence to settle) | 1s | Retry every 500ms up to 10s total wait for `active (running)` |
| P2 | 0 (only runs after P1 passes) | 1s | Retry every 500ms up to 5s total wait for the port to appear bound |
| P3 | 0 (only runs after P2 passes) | 3s per request | Retry with backoff (500ms, 1s, 2s, 4s) up to 10s total wait |
| P4 | 0 (only runs after P3 passes) | 3s per request, per probe | Retry with backoff (500ms, 1s, 2s, 4s) up to 10s total wait. Both `/startupz` and `/readyz` must pass within their joint budget |
| P5 | 0 (only runs after P4 passes) | 3s per request, per endpoint | One attempt per endpoint (no retry — if /readyz passed, P5's endpoints should serve immediately; a P5 failure is structural, not timing-driven) |

Total observed budget is well under 30s in the success case (P1's 2s settle + ~100ms each for P2-P5 successful probes ≈ 3s). The 30s ceiling exists to give a failed install a deterministic time-to-failure rather than an indefinite hang. The retry-with-backoff on P3 and P4 specifically tolerates the lifespan's `_reconcile_on_startup` 8-second sleep (which is not on the critical path for readiness, but a slow lifespan startup on a low-resource VM can still tax P3/P4 timings).

The Step 2.8 retest used a flat 10-second sleep before `systemctl is-active`. The retry-with-backoff design supersedes that pattern: it converges faster on healthy hosts (no 10s wait when the service was up in 2s) and gives clearer diagnostics on unhealthy hosts (the failure message names which predicate timed out, not "10 seconds elapsed").

Timing budgets are not configurable in v5.0. If a target distro proves unable to start the service within 30s on the dev VM specs (4GB RAM, 2 vCPU baseline per Step 3.3 provisioning), that's a Tier 3 finding, not a budget-tunability question — the right answer is to diagnose the slowness or document the spec, not to relax the contract.

## §3 — Response-shape signatures

Each predicate has a positive-match contract for its observed response. The contracts are designed to be specific enough to distinguish "right thing" from "wrong thing being served," and loose enough to survive non-cosmetic backend evolution.

### P1 — systemd

`systemctl is-active mediastack.service` exits with status 0 and writes `active` to stdout. No other status string ("activating", "failed", "inactive") matches.

### P2 — port binding

The port from `<install_dir>/.installer-state.json` field `port` is in `LISTEN` state, owned by a PID matching `systemctl show -p MainPID --value mediastack.service`. The PID match is load-bearing: it distinguishes mediastack from a colliding service that happened to bind the same port (extremely rare on a fresh install but cheap to verify and a good audit-gate invariant).

### P3 — `/healthz`

```
HTTP/1.1 200 OK
Content-Type: application/json
```

Body must be valid JSON with at least: `status` field equal to the string `"ok"`, and a `ts` field whose value is a number (Unix timestamp). Additional fields are permitted and ignored. Per `backend/api/probes.py`, the response is `{"status": "ok", "ts": <unix-timestamp>}` and the smoke test validates that shape.

### P4 — `/startupz` and `/readyz`

`/startupz` must return HTTP 200 with JSON containing `status: "ok"` and `startup_complete: true`. A `status: "starting"` body (HTTP 503) is treated as "retry"; the predicate fails only if the retry budget exhausts without seeing `startup_complete: true`.

`/readyz` must return HTTP 200 with JSON containing `status: "ok"` and a `checks` object containing `db_ping: "ok"`. A `status: "not_ready"` body (HTTP 503) or a `checks.db_ping` value other than `"ok"` is treated as "retry"; the predicate fails only if the retry budget exhausts without seeing the success shape. The `checks.state_configured` field is read but not asserted on (a freshly-installed mediastack has not yet been configured by the operator; the wizard does that work).

### P5 — SPA + QuickStart

For `GET /`:

```
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
```

Body must contain *all three* of:

1. A Vue mount-point element: an HTML element with `id="app"` (matched by regex `id=["']app["']` to tolerate single/double quotes). This signals the Vue SPA's expected mount target is present.
2. A built-asset reference: at least one `<script>` or `<link>` tag referencing a path matching `/assets/index-` (the Vite/dist hashing convention from the existing build). This distinguishes a real built `index.html` from a placeholder, a 503-with-HTML, or a different SPA.
3. A title containing `mediastack` (case-insensitive). This distinguishes mediastack's `index.html` from someone else's index.html accidentally served by the same port (e.g. if a misconfigured nginx fronted the install).

A 503 response from `/` is recognized as a distinct failure class. FastAPI renders an `HTTPException` by writing its `detail` field into a JSON body of the form `{"detail": "..."}`; the smoke test parses that JSON and matches the `detail` field's value containing the substring `Frontend not built` (the documented failure mode in `backend/api/main.py`'s SPA fallback). This match triggers a more specific diagnostic message than a generic P5 failure.

For the QuickStart GET endpoint (URL to be chosen at Step 3.2 implementation time per §1 footnote):

```
HTTP/1.1 200 OK
Content-Type: application/json
```

No body-shape assertion beyond valid JSON. The smoke test does not assert the QuickStart endpoint's *contents* because that couples this contract to the QuickStart router's internal evolution; it asserts only that the endpoint is mounted, responds, and serves JSON. A wrong-content QuickStart response is the QuickStart's own test suite's job to catch.

### Signature fragility notes

The three-part `/` body match is deliberately multi-part: any one of them could be defeated by a UI redesign (the mount point could move to a different ID, the dist path could change with a new build tool, the title could be updated). All three are unlikely to change in a single non-coordinated commit; if they do, the smoke test failure is a strong signal that something cross-cutting changed and the signature needs an amendment. This is the right failure mode — a brittle signature that breaks on minor changes is noise; a robust signature that breaks on cross-cutting changes is signal.

The K8s probe shapes (P3, P4) are external API surface published by `backend/api/probes.py`. Backend changes to those probe responses must update this ADR's §3 in the same commit; the amendment cost is small and the coupling is honest.

## §4 — Failure-mode taxonomy

Each predicate has a positive-match definition (§3) and one or more negative-match definitions. When a predicate fails, the smoke test reports the predicate, the specific failure shape, and an operator-facing diagnostic command. No predicate failure mutates the state file beyond the smoke-test write described in §5; the state file's behavior is a function of the overall smoke-test result, not of which predicate failed.

| Predicate | Failure shape | Operator message | Diagnostic command |
|---|---|---|---|
| P1 | `systemctl is-active` returns `failed` | "The mediastack service failed to start. Recent backend logs may show why." | `journalctl -u mediastack.service -n 50 --no-pager` |
| P1 | `systemctl is-active` returns `activating` or `inactive` after retry budget | "The mediastack service did not reach `active` state within 10 seconds. The unit may be slow to start or stuck in a startup hook." | `systemctl status mediastack.service` |
| P2 | Port not bound after retry budget, but P1 passed | "The mediastack service is active but did not bind to port `<port>` within 5 seconds. The process may be initializing or another service may have the port." | `ss -ltnp` and `systemctl status mediastack.service` |
| P2 | Port bound by wrong PID | "Port `<port>` is bound, but not by the mediastack process. Another service may be using the port." | `ss -ltnp` and `lsof -i :<port>` |
| P3 | `/healthz` returns non-200, or returns 200 with wrong shape | "The mediastack backend is running but `/healthz` did not respond as expected. The FastAPI app may have failed to install routes." | `journalctl -u mediastack.service -n 50 --no-pager` |
| P4 | `/startupz` did not reach `startup_complete: true` within retry budget | "The mediastack backend's startup did not complete within 10 seconds. The lifespan handler may be slow or stuck (commonly: database initialization, scheduler startup)." | `journalctl -u mediastack.service -n 100 --no-pager` |
| P4 | `/readyz` returned `checks.db_ping` not equal to `"ok"` | "The mediastack backend cannot reach its database at `<data_dir>/state.db`. The data directory may have wrong ownership or permissions." | `ls -la <data_dir>/` and `journalctl -u mediastack.service -n 50 --no-pager` |
| P5 | `/` returned 503 with a JSON `detail` containing "Frontend not built" | "The frontend was not built during install. The install pipeline's frontend build step may have failed silently." | `ls <install_dir>/frontend/dist/` (expected: does not exist or empty) |
| P5 | `/` returned 200 but body did not match SPA signature | "The frontend is serving but does not match the expected mediastack SPA signature. This may indicate a misconfigured reverse proxy fronting the port, or a corrupted build." | `curl -s http://127.0.0.1:<port>/ | head -50` |
| P5 | QuickStart endpoint returned non-200 or non-JSON | "The QuickStart API endpoint did not respond as expected. The QuickStart router may not be mounted." | `curl -s -i http://127.0.0.1:<port>/api/v1/quickstart/<endpoint>` |

Every failure message names the failed predicate (P1-P5), what was expected, what was observed, and a specific command the operator can run for more context. No message says "smoke test failed" generically; the diagnostic surface is the failure message itself.

The F16-class failure (data dir not writable) falls under P4's `db_ping` failure case. The pre-Class-A-audit pattern of "service active, install reports success, browser shows nothing" is structurally caught by P4 in this contract — the smoke test will not pass until `db_ping` returns `"ok"`.

## §5 — State-file composition

Per ADR 0013 §2 as amended, the install pipeline writes the state file twice (pre-install with `phase: "installing", smoke_test_passed: false`, then post-pipeline with `phase: "installed", smoke_test_passed: false`). The smoke test, on overall success, performs a **third** write that mutates only `smoke_test_passed` to `true`. The write is atomic via the same temp-file-and-rename pattern ADR 0013 §2 specifies for the install writes. The smoke test does not introduce any new fields, does not bump the schema version, and does not write `completed_at` (which already reflects pipeline completion, not smoke success — that's the correct semantic per the amended §2).

On smoke-test **failure**, no state-file write happens. The state file remains in its post-pipeline state: `phase: "installed"`, `smoke_test_passed: false`. This is intentional. The state file's role is to record "what the installer attempted and what it confirmed"; `phase: "installed"` records "pipeline ran without exception"; `smoke_test_passed: true` records "smoke ran and confirmed readiness." A failed smoke leaves the second field accurately at `false`, which §7 of this ADR teaches the refusal logic to detect.

No separate `SMOKE_FAIL.txt` artifact is written. The state file's `smoke_test_passed: false` combined with the *absence* of `POST_INSTALL.txt` (§6) is the durable record that an install completed its pipeline but failed its smoke test. Adding a third artifact for the same fact would invite divergence (the three could say different things if any single write failed); the two existing artifacts already encode the failure unambiguously.

## §6 — Post-install operator handoff

On smoke-test success, the installer writes `<install_dir>/POST_INSTALL.txt` and then writes its contents to stdout, both before exiting 0. The two outputs share a single source: stdout is `cat <install_dir>/POST_INSTALL.txt` plus a minimal "Install complete" framing line above it. There is no risk of divergence because there is one source.

### Location and ownership

`<install_dir>/POST_INSTALL.txt`. With default install dir, `/opt/mediastack/POST_INSTALL.txt`. Owner `mediastack:mediastack`, mode `0644` (world-readable; unlike the state file, this is operator-facing documentation and benefits from being readable by any host user inspecting the install).

### Lifecycle

| Event | Effect on POST_INSTALL.txt |
|---|---|
| Successful install (smoke passed) | File written. |
| Smoke test failure | File **not** written. Its absence is part of the failure contract per §5. |
| Successful `--force` reinstall | File rewritten with new timestamp, version, and any changed paths. |
| `uninstall` subcommand | File removed along with the rest of `<install_dir>`. |
| `purge` subcommand | File removed along with `<install_dir>`. |
| Manual deletion by operator | The file is regenerable from `<install_dir>/.installer-state.json` and the installer; a future `mediastack status` subcommand (v5.1+ candidate) could rebuild it. v5.0 does not auto-regenerate. |

The lifecycle gives a useful invariant: **if `POST_INSTALL.txt` exists, the install completed successfully and its smoke test passed.** Operators, audit-gate runners, and future tooling can rely on this invariant without consulting the state file. Conversely, presence of `.installer-state.json` without `POST_INSTALL.txt` is the file-system signature of an install whose pipeline completed but whose smoke did not pass — diagnosable at a glance.

### Contents

Plain text, UTF-8, LF line endings. Designed to be greppable, copy-pasteable from a terminal, and stable in shape so that future automation can parse it if it wants to (though parsing the state file is the better path).

Template (substitution placeholders in `<>`; the installer fills them at write time):

```
Mediastack v<version> install complete
========================================

Open your browser to:

    http://<hostname>:<port>/

The setup wizard will guide you through first-run configuration.

Service unit:    mediastack.service
Install dir:     <install_dir>
Data dir:        <data_dir>
Install user:    mediastack
Installed at:    <completed_at>

Useful commands:

    Check status:      sudo systemctl status mediastack.service
    View logs:         sudo journalctl -u mediastack.service -f
    Stop the service:  sudo systemctl stop mediastack.service
    Uninstall:         sudo <install_dir>/installer/main.py uninstall

For documentation, see:  https://github.com/Nnyan/SLOP
```

`<hostname>` is resolved at install time as: the first non-loopback IPv4 address reported by `hostname -I` if available, falling back to `hostname --fqdn`, falling back to the literal `localhost`. The choice is deliberate — a curl|bash operator is most often installing on a host they ssh'd into, where the LAN address is what they want; `localhost` is the right fallback for the dev-VM case where the operator is at the console. Documenting the resolution order in the file itself was considered and rejected as noise; the resolution is internal and the operator just wants the URL.

### Stdout banner

After writing the file, the installer emits to stdout:

```
==================================================
Install complete. See <install_dir>/POST_INSTALL.txt
==================================================

<contents of POST_INSTALL.txt>
```

The banner serves the immediate-attention case (operator's eyes are on the terminal as install finishes); the file serves the durable case (operator scrolled away, host rebooted, etc.). The duplication is by design — the channels have different lifespans and different access patterns, and a single source eliminates the divergence risk.

## §7 — Refusal-logic composition with ADR 0013 §4

ADR 0013 §4 defines a five-state machine for existing-install detection (S1 clean, S2 installed, S3 in_progress, S4 corrupted_state, S5 partial). The two-field state model (this ADR plus the 0013 §2 amendment) introduces a sub-distinction within S2:

- **S2a — installed and ready.** `phase: "installed"`, `smoke_test_passed: true`, `POST_INSTALL.txt` present. This is the case 0013 §4's existing S2 message describes ("mediastack X.Y.Z is already installed at `<install_dir>` (installed YYYY-MM-DD). Re-run with `--force` to reinstall...").
- **S2b — installed but smoke failed.** `phase: "installed"`, `smoke_test_passed: false`, `POST_INSTALL.txt` absent. This is new. A re-running operator on a host in this state should see a message that names the problem (smoke failed during install) and offers two paths: re-run the smoke test only, or reinstall via `--force`.

The S2b operator message:

> "mediastack X.Y.Z was installed at `<install_dir>` (installed YYYY-MM-DD), but its smoke test did not pass. The install pipeline completed but runtime readiness was not confirmed. Re-run with `--force` to fully reinstall (this preserves `<data_dir>`), or check `journalctl -u mediastack.service` for the original failure. A standalone smoke-rerun subcommand is planned for v5.1."

`--force` behavior is identical in S2a and S2b: remove install dir + systemd unit, preserve data dir, fresh install. The two-field model gives the operator-facing message more diagnostic specificity without requiring the refusal logic to gain new behavior.

The detection function `detect_existing_install()` from 0013 §4 reads `smoke_test_passed` (always required per §2's amended field list) and `POST_INSTALL.txt`'s presence to distinguish S2a from S2b. Both signals are checked because either could be inaccurate in isolation: a manually-deleted `POST_INSTALL.txt` with `smoke_test_passed: true` should still be treated as S2a (the install was healthy; the operator messed with the file). A `POST_INSTALL.txt` present with `smoke_test_passed: false` should not occur (the contract makes them write-coupled) and if observed, indicates a corrupted state warranting the S4 message — though §4's existing definition of S4 (state file doesn't validate) does not catch this case. Whether to extend S4 to cover "state file validates but contradicts a file-system invariant" is a v5.1+ refinement; v5.0 detects only the obvious case (smoke_test_passed: false → S2b).

Precedence within §4 is unchanged: S2 → S3 → S4 → S5, with S2 now sub-dividing into S2a / S2b on the `smoke_test_passed` value.

## Layout invariants

Extends ADR 0013's INV-1 through INV-6.

| # | Invariant | Verification | Audit-gate finding |
|---|---|---|---|
| INV-7 | On a successful install, the smoke test's five predicates (§1 P1-P5) all return their positive-match shape (§3). | Audit-mode check: run `installer/smoke.py::smoke_test()` against the installed host; assert no exceptions and a successful return value. | V5_INSTALLER_PLAN.md Step 4.5.a finding 2 (smoke test passes on all three distros). |
| INV-8 | On a successful install, `<install_dir>/POST_INSTALL.txt` exists with mode 0644, owner `mediastack:mediastack`, and a body matching the §6 template with all placeholders substituted (no remaining `<...>` tokens). | Audit-mode check: `test -f`, stat for ownership and mode, regex `<[a-z_]+>` returns no matches in body. | Step 4.5.a finding 1 (install from clean VM works), extended with POST_INSTALL.txt presence. |
| INV-9 | `<install_dir>/.installer-state.json` field `smoke_test_passed` equals `true` exactly when `<install_dir>/POST_INSTALL.txt` exists. (Write-coupling invariant.) | Audit-mode check: read the field; check the file; assert equivalence. | Step 4.5.a finding 1, extended. |
| INV-10 | The smoke test completes within 30 seconds wall-clock on a baseline VM (4GB RAM, 2 vCPU, Step 3.3 spec). | Audit-mode check: time the smoke-test invocation; assert duration < 30s. | Step 4.5.a finding 2, with timing assertion. |
| INV-11 | After `uninstall`, `POST_INSTALL.txt` does not exist (along with the rest of `<install_dir>`); after `purge`, `POST_INSTALL.txt` does not exist (along with the rest of ADR 0017 INV-13's predicates). | Audit-mode check: `test -e` returns false. | Step 4.5.a finding 3, extended. |

INV-7 through INV-11 are verified by the v5.0.0 audit gate against the three target distros. They join 0013's INV-1 through INV-6 as the structural-equivalent of "what an auditor checks on a working v5 install."

## Consequences

- `installer/smoke.py` (V5_INSTALLER_PLAN.md Step 3.2.a) implements the five predicates from §1 with the timing budgets from §2 and the response-shape signatures from §3.
- `installer/main.py::run_install_pipeline` is extended (Step 3.2.b) to call the smoke test as the final step. On smoke success, write `smoke_test_passed: true` to the state file (§5) and write `POST_INSTALL.txt` (§6), then emit the stdout banner. On smoke failure, do not mutate the state file beyond what the pipeline already wrote, do not write `POST_INSTALL.txt`, emit the failure message and diagnostic command (§4) to stderr, exit non-zero.
- `installer/post_install.py` (new module, Step 3.2.b) renders the `POST_INSTALL.txt` template with substituted values, resolves the hostname per §6's resolution order, and writes the file with the correct mode and ownership.
- `installer/install.py::detect_existing_install()` is extended (Step 3.2.c) to distinguish S2a from S2b per §7, and to emit the S2b operator message when appropriate.
- `installer/tests/test_smoke.py` (Step 3.2.d) covers each predicate with mocked HTTP responses (for the success shape and for each documented failure shape per §4) and mocked systemctl invocations. Each predicate's timing budget is exercised at least once. Tests also cover `post_install.py` rendering (including INV-8's no-unfilled-placeholders check) and the S2a/S2b detection refinement.
- `tools/install-smoke` (the install-smoke harness from the Class-A audit) is extended to verify INV-7 through INV-11 after a real install on the dev VM. The harness's role per LESSONS_LEARNED is "real end-to-end testing at step closure"; the readiness contract benefits directly from this harness.
- ADR 0013 §2 is amended (companion commit) to specify the two-field write lifecycle and update the `smoke_test_passed` field row.
- `docs/cleanup/V5_INSTALLER_PLAN.md` Step 3.2 sub-tasks are refined to four (a smoke.py, b wire-up + post_install.py, c detection refinement, d tests). This is housekeeping, not a contract change.
- `docs/cleanup/COMPLETION_AUDIT_v5_0_0.md` (Step 4.5.a) verifies INV-7 through INV-11 on the three target distros.

## What this does NOT govern

- *Specific QuickStart endpoint URL for P5.* Step 3.2's first design call. The contract is "a non-mutating QuickStart GET returns 200 with JSON"; the URL within the router is implementation-time choice.
- *Standalone smoke-rerun subcommand (`mediastack smoke`).* v5.1+ candidate; the two-field state model makes it mechanical when wanted.
- *Health monitoring beyond first-run.* The backend's own health subsystem and metrics are separate concerns.
- *Headless-browser end-to-end testing of the wizard.* Sanity-only at v5.0 per Step 3.3.a; automation is v5.1+.
- *Refusing to write POST_INSTALL.txt when `--install-dir` is a non-default path and the operator is custom-deploying.* The file is always written at `<install_dir>/POST_INSTALL.txt` regardless of whether `<install_dir>` is the default. Custom-dir operators get the file in their custom dir, which is the right place.

## Alternatives considered

**§1: a single combined "wizard reachable" predicate that conflates P3-P5.** Rejected. Conflating the K8s probes with the SPA fallback and the QuickStart router loses the diagnostic specificity that makes §4's failure-mode taxonomy useful. The F16-class failure (data dir not writable) is distinguishable from the "frontend not built" failure only because P4 and P5 are separate predicates. One combined predicate would have a single generic failure message; five predicates have five specific ones.

**§1: drop P2 (port binding) because P3-P5 will fail if the port isn't bound anyway.** Rejected. P2 catches the narrow 1-3 second race where the process is up but hasn't bound yet, and gives a more specific message ("port not bound") than P3's would be ("HTTP probe failed — could be many things"). The cost of P2 is one `ss` invocation; the diagnostic clarity is worth it.

**§1: add a sixth predicate that exercises a wizard interaction (e.g. submitting a known-safe first-run form).** Rejected. Wizard interactions are stateful — they would mutate the install. The smoke test must be safe to re-run (a future `mediastack smoke` subcommand depends on this) and must not commit operator-meaningful changes. Read-only probes only.

**§2: budget configurable via `--smoke-timeout` flag.** Rejected for v5.0. A configurable timeout is an attractive nuisance: it makes "slow host" indistinguishable from "broken host" by letting the operator paper over the slowness. If a target distro can't pass the smoke within 30s on the baseline spec, that's a real Tier 3 finding worth diagnosing, not a budget-tunability question. v5.1+ may revisit if real operator feedback shows the budget is wrong for legitimate use cases.

**§2: poll-once with no retry.** Rejected. Lifespan startup is genuinely non-instant (8s background sleep, scheduler initialization, DB migration on first start); a poll-once design would force the smoke test to wait for the worst case before its first probe. Retry-with-backoff converges fast on healthy hosts and tolerates slow startup without flat-waiting.

**§3: a single literal-string match on `/` body (e.g. "Mediastack" appearing anywhere).** Considered and rejected. Too loose — would pass on a 503 body that mentioned mediastack by name, would pass on a misconfigured proxy returning mediastack-themed error page, etc. The three-part match (mount point + dist asset + title) is more robust without being fragile.

**§3: a header-based signature (e.g. `X-Mediastack-Phase: ready`).** Considered. The backend doesn't currently emit such a header; adding one would be a small change in `backend/api/main.py`. Rejected because (a) it's a backend change for an installer contract, which crosses concerns, and (b) headers are easy to spoof or proxy-strip, so the body-shape signature is more honest about what's being served. If the backend evolves to emit a structured-readiness header for other reasons (e.g. for K8s admission controllers in a future deployment scenario), §3 could amend to include the header check; v5.0 doesn't need it.

**§4: writing a `SMOKE_FAIL.txt` artifact next to (or in place of) `POST_INSTALL.txt`.** Rejected per §5. The state file's `smoke_test_passed: false` combined with the absence of `POST_INSTALL.txt` is the durable record. Adding a third artifact invites divergence (three files with three potentially different stories) without adding diagnostic information beyond what the existing two encode.

**§4: smoke-failure mutates `phase` to a new value (e.g. `installed_broken` or `smoke_failed`).** Rejected because it would require a schema version bump (the `phase` enum's domain changes) and because the two-field design already encodes the distinction without complicating the enum. ADR 0013 §2 explicitly resists optional-additions-without-bump for the same reason; widening the `phase` enum has the same cost without the same benefit.

**§5: smoke test writes a fourth field (e.g. `smoke_run_at: <timestamp>`).** Considered. A timestamp on the smoke pass would help diagnose "was this smoke from this install or a re-run?" once a re-run subcommand exists in v5.1+. Deferred to v5.1 with the re-run subcommand, since v5.0 has no re-run path and the field would be set exactly once at install time (equal to `completed_at`'s timestamp ± seconds), providing no information beyond what `completed_at` already carries.

**§6: single-channel handoff (POST_INSTALL.txt only, no stdout banner).** Rejected. The curl|bash operator is watching the terminal; making them `cat` a file after install adds friction. The cost of the dual-channel design is ~50ms of stdout writing; the benefit is the operator's immediate-access path is direct.

**§6: single-channel handoff (stdout only, no POST_INSTALL.txt).** Rejected. Stdout is ephemeral; an operator who scrolls past it or pipes the install to a log file loses easy access. The file is the durable artifact.

**§6: write `POST_INSTALL.txt` even on smoke failure with a "INSTALL FAILED" body.** Rejected per the "if POST_INSTALL.txt exists, install succeeded" invariant. Writing it on failure breaks the invariant and loses an operator-and-audit-gate-checkable signal. Smoke failures have their own diagnostic path (stderr message + journalctl) that doesn't conflate with the success artifact.

**§6: write the file at `/var/lib/mediastack/POST_INSTALL.txt` (data dir, persisting across `--force` reinstall).** Rejected. `POST_INSTALL.txt` describes the install, not the data. ADR 0013 §1's code/data boundary places install-describing artifacts in the code dir; `POST_INSTALL.txt` belongs with `.installer-state.json` for the same reason. Surviving `--force` is the wrong property: a `--force` reinstall produces a fresh `POST_INSTALL.txt` reflecting the new install's facts, which is more accurate than preserving the old one.

**§7: introduce a sixth refusal state S6 for "installed but smoke failed."** Considered briefly and rejected. The existing S2 state already captures "an install is here"; the smoke-failure case is a sub-distinction within S2 (S2a vs S2b) rather than a structurally new state. The `--force` behavior is identical; the only difference is the operator-facing message. Sub-dividing S2 keeps the state machine simple while improving the diagnostic surface.

**§7: refuse to allow `--force` on S2b, requiring operator to run uninstall first.** Rejected. The S2b case is genuinely "this install is broken"; making the operator type one more command to fix it is friction without safety benefit. The data dir is preserved across `--force` per 0013 §4, so there's no data-loss risk; the failure mode an over-cautious refusal would prevent isn't a real failure mode.

## Status

Accepted; implemented in V5_INSTALLER_PLAN.md Tier 3.2 (`smoke.py`, `post_install.py`, `main.py` extensions, `install.py::detect_existing_install()` refinement) and verified by V5_INSTALLER_PLAN.md Step 4.5 audit invariants INV-7 through INV-11.

Depends on the companion amendment to ADR 0013 §2 (two-field state-file lifecycle). The amendment must land before or in the same commit-sequence as this ADR.

Revisit when:

- A standalone smoke-rerun subcommand (`mediastack smoke`) is added in v5.1+. §2's budget and §3's signatures would be re-evaluated against the re-run use case (e.g. a re-run after operator-initiated DB migration should tolerate a longer P4 budget — or maybe shouldn't, since re-run smoke is post-startup and should be fast).
- The backend's K8s probe response shapes change (`backend/api/probes.py`). §3 amends to track.
- Headless-browser end-to-end testing lands in v5.1+. Predicates may consolidate or be supplemented by browser-driven checks; the SPA-shape signature in P5 may become redundant if a browser is actually loading the page.
- A target distro can't pass the smoke within the 30s budget on the baseline VM spec. The right response is diagnosis first, budget tuning second — but operator feedback may show the budget is genuinely wrong for legitimate use cases.
- The QuickStart router's URL chosen at Step 3.2 implementation time changes (e.g. router renamed, endpoint moved). §1 and §3's references to the QuickStart endpoint need updating.
- A sixth predicate is wanted (e.g. a wizard-interaction safety check). Adding predicates is mechanical against this ADR's structure; the cost is small if the predicate is genuinely read-only.
