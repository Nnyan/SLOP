# ADR 0017 — Uninstall Semantics

- **Date:** 2026-05-18
- **Status:** Accepted
- **Deciders:** operator, Claude Opus 4.7 (v5 Tier 4.1 design session)

> Enforcement: [manual — verified by `installer/tests/test_uninstall.py` (unit + integration coverage of the three subcommands' semantics) and the v5.0.0 audit gate's INV-12 through INV-16 checks (`docs/cleanup/COMPLETION_AUDIT_v5_0_0.md`). Uninstall is installer-scoped and runs against a real host's filesystem, outside ms-enforce's backend-repo drift surface.]

## Context

v5.0's uninstall subcommands are the inverse of the install pipeline in goal but not in shape. ADR 0013 §1 Scope, §3 boundary 4, and INV-4 forward-reference "ADR 0014" for uninstall semantics; ADR 0015 INV-11 forward-references the same number for `POST_INSTALL.txt` lifecycle. The number 0014 was assigned to the frontend build release policy at Tier 2 close (commit a8a6d51, Proposed status), so the uninstall ADR takes the next free number, 0017. This document fills the forward-reference debt under its actual number; the paired-commit housekeeping in the Consequences section retags those forward references in ADR 0013, ADR 0015, and V5_INSTALLER_PLAN.md so future readers do not chase a wrong number.

The defining feature of uninstall — and the load-bearing sentence in this ADR — is that uninstall is **synchronous and filesystem-inspected**, where install is **temporal and externally-observed**. ADR 0015's apparatus (HTTP probes, retry-with-backoff, 30-second total budget, response-shape signatures, named diagnostic commands per failure mode) exists because install completion is a phenomenon that unfolds over time: a systemd service starts, binds a port, installs FastAPI routes, completes a startup lifespan, begins serving an SPA. Each of those events is observable only from outside the process. Uninstall has none of those properties. `systemctl stop` either succeeds or fails dispositively on its first invocation; `rm -rf <install_dir>` either removes the directory or returns a permission error; `userdel mediastack` either exits 0 or names what blocked it. Retrying `test -e /opt/mediastack` after a failed removal is meaningless — the filesystem state does not converge over time the way an HTTP probe does. The right contract for uninstall is therefore a **removal-completeness contract** that parallels ADR 0015 in *naming predicates and failure modes* but does not mirror its *temporal apparatus*. Calling that asymmetry out explicitly tells future readers — Sonnet's implementation work in Step 4.1.b, the v5.0.0 audit-gate authoring in Step 4.5, and v5.1 maintainers — why this ADR does not have a "timing budget" section. The asymmetry is the design; not a gap.

The third movement is composition. The `clean` subcommand resets all mediastack-managed apps (managed containers and their volumes) while leaving mediastack itself running. This operation is structurally distinct from `uninstall` and `purge` — it does not stop the mediastack service, does not touch the install dir, does not touch the state file. What it does need is a way to enumerate the managed containers, dispatch a removal to each app's backend representation, and report per-app status. The backend already has this capability: `backend/manifests/executor.py::remove_app(key, delete_config=None)` implements a seven-step removal sequence (validate → stop → unregister → unwire → fragment → config → state), returns a rich `ExecutionResult` with per-step status, and is the same path the in-product UI takes for app removal via `frontend/src/views/AppDetailView.vue:410`. Operator verification at Step 4.1 design start confirmed the function is well-structured, actively maintained (commit a681874 split `_remove_inner` into per-phase helpers — testable, recoverable), and reliably reports failure modes per step. `clean` therefore composes with `executor.remove_app` rather than re-implementing per-app teardown in installer code. This is the highest-leverage design decision in the ADR; the alternative (duplicate the seven-step sequence in `installer/uninstall.py`) was considered and rejected on the reliability evidence.

The contract this ADR establishes is consumed by `installer/uninstall.py` (the three subcommands' implementation in Step 4.1.b), by `installer/tests/test_uninstall.py` (the unit and integration tests in Step 4.1.c), by `backend/manifests/<compose-generator>` (the two-label application contract in §D), and by `docs/cleanup/COMPLETION_AUDIT_v5_0_0.md` (the audit gate's INV-12 through INV-16 checks in Step 4.5). It depends on `installer/state.py::read_state_file()` (Tier 1.3.c), `installer/post_install.py::_resolve_hostname()` (Tier 3.2.b — re-used by `clean`'s post-output), and the existing `backend/manifests/executor.py::remove_app()` (pre-v5 backend code). No new modules are required outside `installer/uninstall.py` itself; everything else extends or imports existing surface.

## Scope

**In scope:** the three subcommands' filesystem-and-system-effect semantics (§A common context, §B uninstall and purge, §C clean), the two-label scheme that makes container and volume enumeration possible (§D), the confirmation UX and `--yes` flag contract, the refusal logic when no state file is present or the state file is unreadable, the audit-mode verification hooks the v5.0.0 audit gate consumes (`verify_removed()`), and the layout-invariant extensions INV-12 through INV-16.

**Out of scope and tracked elsewhere:**

- The backend's per-app removal sequence in `executor.remove_app`. This ADR specifies the *call contract* between `clean` and the backend (input: app key + `delete_config=True`; output: `ExecutionResult` per app) but not the seven-step internals. Changes to `remove_app`'s internals do not amend this ADR; changes to its signature or return shape do.
- The v5.0.0 audit gate itself (V5_INSTALLER_PLAN.md Step 4.5). This ADR specifies what evidence each subcommand produces (filesystem state, docker enumeration output, per-app `ExecutionResult` lists); the audit-gate work decides what is committed where and how the evidence manifest is structured.
- A standalone `mediastack uninstall-replay` subcommand for resuming interrupted uninstalls. The reconciliation §5 IA-1 question of whether to record `phase=uninstalling` in the state file is resolved by decision (A) — no write — and the consequence (no replay-from-interruption capability) is accepted for v5.0; an `uninstall-replay` is a v5.1+ candidate under its own ADR.
- v4.x → v5.0 migration tooling (D7). Pre-v5.0 containers do not carry the two-label scheme and will not be found by `purge`'s container enumeration (U6/U7). The manual-cleanup path is documented in `INSTALL.md` (Step 4.4 doc task), not codified here.
- Non-Debian-Ubuntu distros. ADR 0016's supported set (Debian 12, Debian 13, Ubuntu 24.04) is inherited; Fedora, RHEL, Arch, openSUSE are v5.1+ work.
- Rootless Docker, scoped sudoers, alternative isolation models. ADR 0013 §5's security note on docker-group root-equivalence carries forward; an uninstall contract for a rootless-Docker future is its own ADR.
- The standalone smoke-rerun subcommand mentioned in ADR 0015 §7 (S2b message). That is independent v5.1+ work and does not interact with this ADR.
- `backend/manifests/executor.remove_app`'s reliability evolution. The current pattern is "fix and stay fixed" per operator verification; future regressions are the backend's own quality bar, not the uninstall ADR's.

## Decision

### §A — Common context (applies to all three subcommands)

The six sub-sections below specify behavior that every subcommand inherits. §B and §C add subcommand-specific structure on top of this base.

#### §A.1 — State-file read protocol

Every subcommand invokes `installer/state.py::read_state_file(<install_dir>)` as its first operation, where `<install_dir>` is resolved from the `--install-dir` CLI flag, the `MEDIASTACK_INSTALL_DIR` environment variable, or the ADR 0013 §1 default `/opt/mediastack`, in that precedence order (Core Rule 5.26 path resolution discipline). The read is strictly read-only: no subcommand writes to the state file at any point. The state file is removed only as part of the `<install_dir>` removal in §B step (6); `clean` does not interact with the state file beyond reading the `port`, `data_dir`, and `install_user` fields needed to compose its operator-facing messages and to dispatch to the backend.

This is **decision (A)** from the IA reality-check report: no `phase=uninstalling` write happens before or during uninstall. The alternative (writing `phase=uninstalling` so that an interrupted uninstall could be detected and resumed by a future `mediastack uninstall-replay` subcommand) would require expanding the `phase` enum's domain — a schema change per ADR 0013 §2 "Schema evolution" — and adding a `migrate_1_to_2()` function plus a new refusal state (S6: state file says `uninstalling`). The cost is real (one schema bump for the entire v5.0.x line) and the benefit is hypothetical (v5.0 does not have an `uninstall-replay` subcommand; the interruption window is small; `--force` already covers interruption-recovery via ADR 0013 §4's S5 partial-state handling). The trade is wrong for v5.0. The Alternatives considered section names this explicitly and points at v5.1 if the value calculus changes.

The practical consequence: if an uninstall is interrupted (operator hits Ctrl-C between steps, kernel panics, SSH connection drops), the post-interruption filesystem state may have a partial install dir removal, a stopped service, a removed systemd unit, or any combination. The next `install.sh` invocation reads what's left and routes through ADR 0013 §4's existing S5 (`partial`) handling: refuse by default with a message naming what's present, or proceed under `--force` which removes the remaining residue and starts fresh. No new refusal state is introduced.

#### §A.2 — Refusal when no state file is present

If `read_state_file(<install_dir>)` returns `None` (file does not exist), every subcommand prints to stderr:

```
No v5 mediastack install detected at <install_dir>.

If you have a v4.x install or a hand-rolled deployment, the v5 uninstaller
cannot determine what to remove. Manual cleanup is documented in
INSTALL.md (section "Removing pre-v5 installs").

If you expected a v5 install here, check the --install-dir flag.
```

…and exits with status 1. The `--force` flag does **not** override this refusal. The rationale mirrors ADR 0013 §4's S4 rationale (corrupted state is unconditionally non-forceable): silently uninstalling something the installer did not put there is a class of mistake worth refusing. The installer cannot know which paths to remove without the state file; guessing from filesystem grep is fragile (the grep accidentally matches a different mediastack-named project, or a hand-rolled v4 install) and unsafe (the operator may have customized `install_dir` to `/srv/mediastack` and a `--force` under defaults would not find it). One extra step from the operator (consult INSTALL.md, do manual `rm`) is the right cost to pay for preventing silent wrong-host removal.

#### §A.3 — Refusal when state file is corrupted or from a newer schema version

`read_state_file()` raises `StateFileCorruptedError` (the file exists but does not parse as JSON, parses but fails schema validation, or has an unknown field) or `StateFileNewerSchemaError` (the file's `schema_version` is higher than this installer supports). In either case, the subcommand surfaces the exception's message verbatim to stderr and exits 1. The `--force` flag does **not** override these refusals.

The rationale is identical to ADR 0013 §4's S4: the state file may describe a customized `install_dir` or `data_dir`, may name a user other than `mediastack`, may point at paths the installer does not otherwise know about. Silently overwriting or removing files that depend on an unreadable state file is the same class of mistake §A.2 refuses. The operator's recovery path is identical: read the error message, do manual cleanup or schema-version-upgrade the installer, then proceed.

The `StateFileNewerSchemaError` case is particularly important for forward-compatibility: a v5.0.x installer encountering a state file written by a v5.1.x installer (with `schema_version: 2`) must refuse rather than corrupt the v5.1 install. The exception's message names the version mismatch explicitly: *"This state file was written by a newer installer (schema version N; this installer supports up to M). Upgrade the installer, or restore a state file from a matching version."*

#### §A.3.5 — Refusal when state file is unreadable due to permissions

If `read_state_file()` raises `PermissionError` (file exists but the calling process cannot read it), the subcommand emits to stderr:

```
State file at <install_dir>/.installer-state.json exists but is not
readable by the current user (Permission denied).

The state file is mode 0640 owned by mediastack:mediastack. Run the
uninstaller with sudo, or as a user in the mediastack group:

    sudo mediastack <subcommand>
```

…and exits with status 1. The `--force` flag does **not** override this refusal.

This case is specifically called out (separate from §A.3's corrupted/newer-schema cases) because the operator's recovery path is different. A corrupted state file is a forensic situation requiring manual `rm`; a permission-denied state file is a routine "run as root" issue with a one-flag fix. Conflating the two messages would surface "state file unreadable" to operators whose actual problem is just that they forgot `sudo`, and would degrade the diagnostic surface for genuine corruption.

This refusal happens *before any side effect*: the read is the first operation, the exception triggers immediately, and no `systemctl stop` or `rm` has run. The fail-fast ordering mirrors ADR 0013 §3's pipe-mode flag check — operators relying on `sudo mediastack uninstall` should never find themselves with a half-stopped service because they forgot the `sudo`.

#### §A.4 — Confirmation UX (TTY-based selection)

Every destructive subcommand (`uninstall`, `purge`, `clean`) prompts for confirmation by default when stdin is a TTY, and requires `--yes` to skip the prompt when stdin is not. The mechanism mirrors ADR 0013 §3's D3 sub-resolution for `--install-docker`: interactive mode prompts; pipe mode requires the flag. The asymmetry between install (asks about Docker, defaults to nothing) and uninstall (asks about removal, defaults to nothing) is intentional — neither has a defensible default beyond "the operator must affirm."

The detection logic is `[ -t 0 ]` (POSIX: stdin is a terminal) evaluated at subcommand entry, before `read_state_file()`. The result is the *mode*. In interactive mode without `--yes`, the subcommand prints the per-subcommand confirmation text (specified in §B.6 for `uninstall`/`purge` and §C.7 for `clean`) and reads a single line from stdin. The match for "yes" is case-insensitive `y` or `yes`; any other input (including empty input) is treated as "no" and the subcommand exits 0 without side effects. In pipe mode without `--yes`, the subcommand exits 1 with:

```
This is a destructive operation. To run non-interactively, pass --yes.
To run interactively, run from a terminal.
```

In interactive mode *with* `--yes`, the prompt is skipped. In pipe mode *with* `--yes`, the prompt is skipped. The flag's semantic is uniform: "I have read the consequences; do not ask."

The fail-fast-before-side-effect ordering is part of the contract:

1. Parse arguments.
2. Detect TTY mode.
3. Resolve `<install_dir>`.
4. `read_state_file()` → may exit 1 per §A.2/§A.3/§A.3.5.
5. TTY mode check: if pipe mode and no `--yes`, exit 1.
6. Confirmation prompt (interactive, no `--yes`).
7. **First side effect** (e.g., `systemctl stop` for `uninstall`/`purge`; `docker ps` enumeration for `clean`).

Steps 1–6 are read-only/refusal-only. The implementer must not rearrange them.

#### §A.5 — `--yes` flag semantics

A single `--yes` flag bypasses the confirmation prompt for the subcommand it appears in. The flag does NOT override the refusals in §A.2 (no state file), §A.3 (corrupted state), §A.3.5 (permission denied), §A.6 (pre-existing-user mismatch), or §A.6.5 (pre-existing-group mismatch with extra members). Those refusals are about the installer's inability to safely proceed, not about operator consent; consent does not resolve them.

The flag does NOT propagate to nested operations. In `clean`, the flag bypasses the confirmation prompt for the top-level operation but does NOT become an "approve everything" flag for individual `executor.remove_app` calls — those calls are themselves non-interactive (the backend API does not have a confirmation step; the operator's `--yes` to `clean` is the consent for the whole batch).

There is no `--no` or `--assume-no` flag. The default for pipe mode without `--yes` is refusal with exit 1 (§A.4); the default for interactive mode is the prompt (with empty input → no). Neither needs a flag.

#### §A.6 — Pre-existing-user mismatch principle (mirror of ADR 0013 §5)

ADR 0013 §5's `InstallUserMismatchError` refuses to bring a pre-existing `mediastack` user under installer management if the user's attributes don't match the §5 expected attributes (UID < 1000, shell `/usr/sbin/nologin`, home `/nonexistent`). The rationale is that a pre-existing `mediastack` user with regular UID and login shell is almost certainly someone else's account that happens to collide with the project name; silently bringing it under installer management is hostile.

The same rationale applies in reverse for uninstall. If `getent passwd mediastack` returns a user whose attributes don't match §5's expected attributes — for example, a regular UID ≥ 1000, a non-`/usr/sbin/nologin` shell, or a non-`/nonexistent` home — `uninstall` and `purge` **refuse to remove the user** and report `UninstallUserMismatchError`:

```
User 'mediastack' exists but has unexpected attributes:
  UID:   <observed>     (expected: system UID < 1000)
  Shell: <observed>     (expected: /usr/sbin/nologin)
  Home:  <observed>     (expected: /nonexistent)

The installer will not remove a user it did not install. If this user
was created by the installer and modified afterwards, remove it manually:

    sudo userdel <username>

Continuing uninstall (other removal steps proceed).
```

The rest of the uninstall continues: the install dir is still removed, the systemd unit is still removed, the service is still stopped. Only U4 (the user-removal predicate, §B.2) is skipped, and U4b (the group-removal predicate, §A.6.5) is conditionally skipped pending §A.6.5's evaluation. The audit-gate verification (INV-12, INV-13) reports U4-skip as a recognized state, not a failure.

The `--force` flag does NOT override this refusal. Removing a user the installer did not create is irreversible (the operator's home directory contents, if any, are deletable but the UID is gone); the friction of one manual `userdel` is the right cost.

#### §A.6.5 — Pre-existing-group mismatch with extra members

Symmetric to §A.6: if `getent group mediastack` returns a group whose member list contains entries other than the `mediastack` user (e.g., another tool's user was added to the `mediastack` group), `uninstall` and `purge` **refuse to remove the group** and report `GroupHasUnexpectedMembersError`:

```
Group 'mediastack' exists with members not added by installer:
  <member1>, <member2>, ...

The installer will not remove a group it did not solely populate.
These additional members may belong to third-party tooling. Remove
the group manually after verifying its membership:

    sudo groupdel mediastack

Continuing uninstall (other removal steps proceed).
```

The rest of the uninstall continues. Only U4b (the group-removal predicate, §B.2) is skipped. The `--force` flag does NOT override.

The rationale is identical to §A.6's: a group with members the installer did not add is structurally indistinguishable from a group some third party uses for its own purposes. Silently removing it would orphan those members from their intended group; their tools may rely on group membership for permission checks. One manual `groupdel` after operator verification is the right cost.

The check is specifically "member list contains entries other than the `mediastack` user." A group whose only member is the just-removed `mediastack` user (or no members at all, if the user was already removed) is fine to remove and U4b proceeds normally.

#### §A.7 — Audit-mode verification hook

A pure function `installer/uninstall.py::verify_removed(install_dir, data_dir, mode)` returns a structured result indicating which U-predicates hold post-action. The `mode` argument is one of `'uninstall'`, `'purge'`, or `'clean'`. The return shape:

```python
@dataclass
class RemovalVerification:
    mode: str                       # 'uninstall' | 'purge' | 'clean'
    predicates: dict[str, bool]     # {'U1': True, 'U2': True, 'U3': True, ...}
    skipped: list[str]              # e.g. ['U4'] if §A.6 carve-out fired
    diagnostics: dict[str, str]     # per-predicate diagnostic command on False
```

The function performs no removals — it reads filesystem state, queries `systemctl`, `getent`, and `docker` via `installer._run.run_required` (Core Rule 5.27), and returns the structured result. The audit gate at Step 4.5 imports and calls this function (per IA-4: installer-importable, not a new `tools/` wrapper). Sonnet's Step 4.1.c tests cover the function in isolation: each U-predicate is exercised on synthetic post-action filesystem states, the §A.6/§A.6.5 skip behavior is exercised, and the diagnostic-command output is asserted to match the §B.3 failure-mode table.

The function is the single point of audit-mode access. No code re-implements its checks inline. Future tooling — a hypothetical `mediastack status` subcommand, a CI harness for migration testing, a `tools/check-uninstall-residue.py` if ever extracted — imports and consumes `verify_removed()` rather than duplicating the checks.

### §B — `uninstall` and `purge` shared structure

The two destructive removal subcommands share a forward sequence: stop the service, remove the systemd unit, remove the install dir, remove the user, remove the group. `purge` continues past where `uninstall` ends with three additional steps: remove the data dir, remove managed Docker containers, remove managed Docker volumes. The structure below specifies both subcommands together because the shared steps are identical; the divergence is at the suffix, not within steps.

#### §B.1 — Pipeline order

The full forward sequence, with `uninstall` ending at step 8 and `purge` continuing through step 11:

| # | Action | Subcommand | Notes |
|---|---|---|---|
| 1 | `read_state_file(<install_dir>)` | both | §A.1 |
| 2 | Confirmation (TTY) or `--yes` check (pipe) | both | §A.4 |
| 3 | `systemctl stop mediastack.service` | both | Idempotent on already-stopped units |
| 4 | `systemctl disable mediastack.service` | both | Idempotent on already-disabled units |
| 5 | `rm /etc/systemd/system/mediastack.service` then `systemctl daemon-reload` | both | The `rm` precedes `daemon-reload` so the reload picks up the unit's absence |
| 6 | `rm -rf <install_dir>` | both | Includes state file, POST_INSTALL.txt, venv, frontend dist, all installer-owned files |
| 7 | `userdel mediastack` (subject to §A.6 carve-out) | both | §A.6 may cause this step to be skipped with a recorded reason |
| 8 | `groupdel mediastack` (subject to §A.6.5 carve-out) | both | §A.6.5 may cause this step to be skipped with a recorded reason. **`uninstall` ends here.** |
| 9 | `rm -rf <data_dir>` | purge only | The data dir's removal is irreversible; the confirmation prompt's "this operation is irreversible" language refers principally to this step |
| 10 | `docker ps -a --filter label=mediastack.managed=true --format '{{.ID}}'` then `docker rm -f` each | purge only | Labels per §D; containers are removed forcibly because we want them gone regardless of whether they're running |
| 11 | `docker volume ls --filter label=mediastack.managed=true --format '{{.Name}}'` then `docker volume rm` each | purge only | Volume removal happens after container removal so no volume is in use |

The ordering is deliberate and is part of the contract; the implementer must not rearrange steps. Several constraints justify the order:

- Step 3 (stop) precedes step 5 (remove unit file). A unit removal while the service is running races with `daemon-reload` — the kernel may keep the process alive but systemd loses track of it, producing a residue process that no `systemctl` invocation can find. Stopping first ensures clean transition.
- Step 5 (remove unit file) precedes step 6 (remove install dir). The unit's `WorkingDirectory=` and `ExecStart=` reference paths under `<install_dir>`; if the install dir is removed first and `daemon-reload` somehow re-reads the unit before step 5's `rm`, systemd may attempt to restart the service against now-missing files and emit confusing log entries. Removing the unit file first eliminates the race.
- Step 6 (remove install dir) precedes step 7 (remove user). Files under `<install_dir>` are owned by `mediastack:mediastack`. `rm` running as root can remove them regardless, but having an active owner during removal keeps filesystem tooling (auditd, file integrity monitoring) attributing the removal correctly. Removing the user first would orphan the files to UID-numeric-only ownership in audit logs, which is harder to interpret retrospectively.
- Step 7 (remove user) precedes step 8 (remove group). `userdel` on a user whose primary group has no other members will leave the group behind on Debian and Ubuntu (the default `USERGROUPS_ENAB yes` in `/etc/login.defs` removes the group only if no other users are members). The explicit `groupdel` after `userdel` handles the cleanup; doing it before would fail because the user's primary group cannot be deleted while the user references it.
- Step 9 (data dir removal) precedes steps 10-11 (Docker enumeration and removal) in `purge`. The data dir contains `state.db` which the backend uses to track managed-container state; if the data dir is removed first, the backend's view of "what's managed" is gone — but the Docker daemon's view (via labels) is still intact. The label-based enumeration is the authoritative source for `purge`'s Docker cleanup; the data dir's `state.db` is incidental. Either order works in principle, but data-dir-first matches the natural "remove user-visible state, then remove system-visible state" progression.

#### §B.2 — U-predicates: the removal-completeness contract

Eight removal-completeness predicates with per-subcommand applicability. The U-predicates are to uninstall what P1–P5 are to install (ADR 0015 §1): the externally-checkable propositions that define what "this subcommand succeeded" means. Unlike P1–P5, the U-predicates have no timing component — each is a single check that returns dispositively on first call.

| # | Predicate | uninstall | purge | Verification |
|---|---|---|---|---|
| U1 | `systemctl is-active mediastack.service` returns `inactive` or `unknown` (the unit file is gone) | ✓ | ✓ | shell exit ≠ 0 and stdout ∈ {`inactive`, `unknown`} |
| U2 | `/etc/systemd/system/mediastack.service` does not exist | ✓ | ✓ | `test -e <path>` returns false |
| U3 | `<install_dir>` does not exist | ✓ | ✓ | `test -e <install_dir>` returns false |
| U4 | `getent passwd mediastack` returns nonzero (subject to §A.6 carve-out) | ✓ | ✓ | shell exit ≠ 0 |
| U4b | `getent group mediastack` returns nonzero, OR returns a group whose only member is the just-removed `mediastack` user (subject to §A.6/§A.6.5 carve-outs) | ✓ | ✓ | shell exit ≠ 0, OR `getent group` output's fourth field is empty / contains only `mediastack` |
| U5a | `<data_dir>` exists with the same inode and the same mtime as pre-uninstall (data dir preserved-untouched) | ✓ (uninstall) | ✗ | `stat -c '%i %Y' <data_dir>` matches pre-uninstall snapshot |
| U5b | `<data_dir>` does not exist | ✗ | ✓ (purge) | `test -e <data_dir>` returns false |
| U6 | `docker ps -a --filter label=mediastack.managed=true --format '{{.Names}}'` returns empty | ✗ | ✓ | docker stdout is empty |
| U7 | `docker volume ls --filter label=mediastack.managed=true --format '{{.Name}}'` returns empty | ✗ | ✓ | docker stdout is empty |

A note on U5a's verification specificity: the check is "no inode changes, no mtime changes." It deliberately does not check atime, because filesystems with `atime` enabled change atime on read access — including the audit gate's own `stat` invocation. Including atime would produce false negatives whenever the audit gate runs. Checking inode (which would change on a `mv` or a copy-then-replace) and mtime (which would change on any content modification) is sufficient to detect actual mutation of the data dir; atime is noise.

U4b's structure handles three cases: the group has been deleted (most common after successful `groupdel`), the group still exists but is empty (some `userdel` configurations leave the empty group), or the group exists with only the just-removed user as a leftover entry (a transient state on some systemd-resolved systems). All three are acceptable post-states; only "the group exists with additional members" or "the group exists with members the installer did not add" violates U4b, and §A.6.5 routes those cases to a recognized carve-out before §B's pipeline runs.

`verify_removed()` (per §A.7) evaluates each applicable U-predicate against post-action state and returns the structured result. Predicates skipped due to §A.6 or §A.6.5 are reported in the `skipped` field, not the `predicates` field — so the audit gate can distinguish "this predicate held" from "this predicate was deliberately skipped per documented carve-out."

#### §B.3 — Failure modes per U-predicate

Each U-predicate has named failure shapes with operator messages and diagnostic commands. The discipline matches ADR 0015 §4: no message says "uninstall failed" generically; the diagnostic surface is the failure message itself.

| Predicate | Failure shape | Operator message | Diagnostic command |
|---|---|---|---|
| U1 | `systemctl is-active` returns `active` or `activating` after step 3 | "The mediastack service did not stop. The unit may have a `KillMode=` configuration that prevents clean shutdown, or a child process may be unkillable." | `systemctl status mediastack.service` and `ps -ef \| grep mediastack` |
| U2 | `/etc/systemd/system/mediastack.service` still exists after step 5 | "The systemd unit file could not be removed. The path may be a read-only mount, a symlink to a different file, or held by another tool." | `ls -la /etc/systemd/system/mediastack.service` and `mount \| grep '/etc'` |
| U3 | `<install_dir>` still exists after step 6 | "The install directory could not be fully removed. A file may be in use, the filesystem may have immutable-bit-set files, or a child mount may be present." | `lsof +D <install_dir>` and `mount \| grep <install_dir>` |
| U4 | `getent passwd mediastack` still succeeds after step 7 (and §A.6 did not skip) | "The `mediastack` user could not be removed. The user may have a running process (login session, cron job, lingering systemd user services), or a system policy may be blocking `userdel`." | `loginctl user-status mediastack` and `ps -u mediastack` |
| U4b | `getent group mediastack` still succeeds after step 8 with unexpected members | "The `mediastack` group could not be removed and was not skipped by the §A.6.5 carve-out, indicating an unexpected error during `groupdel`." | `getent group mediastack` and `journalctl -t groupdel -n 50` |
| U5a | `<data_dir>` inode or mtime changed during uninstall (data dir was mutated) | "The data directory was modified during uninstall. This is unexpected — `uninstall` should not touch the data dir. Verify no other process is writing." | `lsof +D <data_dir>` and check audit logs |
| U5b | `<data_dir>` still exists after step 9 (purge only) | "The data directory could not be fully removed. A file may be in use, the filesystem may have immutable-bit-set files, or the dir may be a mount point with content provided by another tool." | `lsof +D <data_dir>` and `mount \| grep <data_dir>` |
| U6 | `docker ps -a --filter label=mediastack.managed=true` still returns container names | "Managed containers could not all be removed. Some containers may have failed `docker rm` due to volume mount issues, network conflicts, or Docker daemon errors." | `docker ps -a --filter label=mediastack.managed=true` and `journalctl -u docker -n 50` |
| U6 | `docker` daemon unreachable during enumeration | "The Docker daemon is not accessible. Without daemon access, managed containers cannot be enumerated or removed." | `systemctl status docker` and `docker info` |
| U7 | `docker volume ls --filter label=mediastack.managed=true` still returns volume names | "Managed volumes could not all be removed. Some volumes may have failed `docker volume rm` due to ongoing use by other containers (label-mismatched), or driver-specific errors." | `docker volume inspect <name>` for each remaining and `docker ps -a --filter volume=<name>` |

Every failure message names the failed predicate, what was expected, what was observed, and a specific command the operator can run for more context. The failure messages are the API contract for operator-facing diagnosis; downstream changes that alter them are amendments to this ADR.

A failure of U1, U2, or U3 stops the pipeline: if the service cannot be stopped, the install dir should not be removed (it would be mid-write); if the unit cannot be removed, the install dir's removal would leave systemd in a confused state on the next reboot. Failures of U4, U4b, U5a (during uninstall), U5b, U6, or U7 do not stop the pipeline — they are reported at the end and the overall exit code is nonzero, but the rest of the pipeline runs. The rationale: a stuck user is worth surfacing for operator action but does not block the operator from getting a clean install dir and a clean Docker state. A failed Docker enumeration during purge is worth knowing about but does not require leaving the install dir in place.

#### §B.4 — Refusal logic specifically for `uninstall` and `purge`

Beyond the §A refusals (no state file, corrupted state, permission denied), two additional refusal cases apply specifically to `uninstall` and `purge`:

**§B.4.1 — Pre-existing-user mismatch (§A.6 carve-out).** Continues the pipeline but skips U4. Reports the mismatch in stderr; exit code reflects whether other predicates also failed.

**§B.4.2 — Pre-existing-group-extra-members (§A.6.5 carve-out).** Continues the pipeline but skips U4b. Reports the mismatch in stderr; exit code reflects whether other predicates also failed.

There is no "the install is currently in use" refusal. `uninstall` and `purge` will stop the service unconditionally as step 3; an operator who runs `uninstall` while actively using the wizard accepts the disruption. The confirmation prompt (§B.6) names this consequence ("Stop and disable mediastack.service"); a separate refusal would be friction without safety benefit.

There is no "data dir contains user files; refuse to purge" refusal. `purge` is the explicit-data-removal subcommand; if the operator wanted to preserve data, `uninstall` is the correct choice. The confirmation prompt's "this operation is irreversible" language is the safety; a refusal that demanded a separate flag would be over-correction.

#### §B.5 — State-file removal

The state file at `<install_dir>/.installer-state.json` is removed as part of step (6) `rm -rf <install_dir>`. There is no separate state-file removal step. There is no atomic guarantee that the state file is removed before or after any other content of the install dir — `rm -rf` is recursive but not transactional. A partial install dir removal (e.g., interrupted by signal between steps) may leave the state file behind or remove it before other content; either case is handled by ADR 0013 §4's S5 (`partial`) refusal logic on the next `install.sh` invocation.

No backup of the state file is made before removal. The state file is regenerable from a fresh install; backing it up adds clutter without value.

#### §B.6 — Confirmation prompt text

The text is per subcommand and names what is about to be removed. For `uninstall`:

```
About to uninstall mediastack v<version>:

  - Stop and disable mediastack.service
  - Remove /etc/systemd/system/mediastack.service
  - Remove <install_dir> (code, venv, frontend, state file, POST_INSTALL.txt)
  - Remove user 'mediastack' and group 'mediastack' (if installer-installed)

The data directory <data_dir> will be PRESERVED.
To also remove data and managed containers, use 'mediastack purge' instead.

Continue? [y/N]:
```

For `purge`:

```
About to PURGE mediastack v<version> from <hostname>:

  - Stop and disable mediastack.service
  - Remove /etc/systemd/system/mediastack.service
  - Remove <install_dir> (code, venv, frontend, state file, POST_INSTALL.txt)
  - Remove user 'mediastack' and group 'mediastack' (if installer-installed)
  - Remove <data_dir> (state.db, .env, per-app configs, compose fragments)
  - Remove ALL mediastack-managed Docker containers (label: mediastack.managed=true)
  - Remove ALL mediastack-managed Docker volumes (label: mediastack.managed=true)

This operation is IRREVERSIBLE. All app data will be lost.

Continue? [y/N]:
```

The version field is read from the state file's `mediastack_version`. The hostname is resolved via `installer/post_install.py::_resolve_hostname()` (IA-6 reuse) so the operator sees which host they're purging — small but meaningful guard against accidental purges on the wrong terminal. The install_dir and data_dir are read from the state file.

The "if installer-installed" parenthetical reflects §A.6/§A.6.5: if the user or group has unexpected attributes, the prompt's claim that the user/group will be removed is hedged with the carve-out. The prompt does not enumerate the carve-out logic — that would clutter the prompt; the post-action stderr reports any skipped step.

### §C — `clean` separate structure

`clean` is structurally distinct from `uninstall` and `purge`. It does not stop the mediastack service, does not touch the install dir, does not touch the state file. What it does is iterate every managed Docker container, dispatch a per-app removal to the backend's `executor.remove_app(key, delete_config=True)`, collect the per-app `ExecutionResult`, and report a per-app status summary to the operator. The mediastack service continues running throughout; the wizard remains accessible; only the managed apps disappear.

#### §C.1 — Compose-with-backend design

`clean` invokes `backend/manifests/executor.py::remove_app(key, delete_config=True)` for each unique app key derived from the container enumeration. The function (per operator verification at design start) implements a seven-step removal sequence — validate, stop, unregister, unwire, fragment, config, state — and returns an `ExecutionResult` per call with per-step status (`ok`, `warning`, `failed`). The seven-step internals are the backend's contract; `clean` consumes `ExecutionResult` and aggregates.

The call is made over HTTP via the same internal API path the UI uses (`appsApi.remove(key, deleteConfig)` in `frontend/src/views/AppDetailView.vue:410`). The mechanism: `clean` either invokes the backend's HTTP API directly (if running on the host alongside the backend) or invokes `executor.remove_app` via Python import (if `installer/uninstall.py` runs in-process with the backend, which it does not in v5.0). For v5.0, the HTTP path is the contract; the implementation detail of whether to use `requests` or a unix-socket call is Sonnet's Step 4.1.b decision.

`delete_config=True` is hardcoded for `clean`. The rationale: `clean` is the explicit-reset subcommand; preserving per-app configs partially defeats the point. Operators who want to preserve configs while resetting containers should not use `clean` — they should use the backend's per-app removal UI with the `delete_config=False` option, which gives per-app granularity. A `--keep-configs` flag on `clean` is a v5.1+ candidate if operator feedback indicates it's wanted; v5.0 is opinionated.

#### §C.2 — Container enumeration

Container enumeration uses the two-label scheme (§D):

```
docker ps -a --filter label=mediastack.managed=true \
  --format '{{.Names}}\t{{.Label "mediastack.app-key"}}'
```

The output is tab-separated rows of container name and app-key. The app-key column may be empty for malformed containers (managed label present, app-key label absent); §C.3 handles that case.

Container enumeration runs against `docker ps -a` (all containers, not just running) so that stopped-but-not-removed containers are caught. A previous failed install or a stopped app should still be cleanable.

If `docker` is unreachable (daemon down), enumeration fails with an operator-facing error and `clean` exits 1 without side effects. No partial cleanup is attempted; either Docker is reachable and all managed containers are cleanable, or Docker is unreachable and the operator needs to fix Docker first.

#### §C.3 — App-key resolution

From the enumeration output:

1. Collect all unique non-empty `mediastack.app-key` values. This is the set of apps to clean.
2. Collect all container names that have `mediastack.managed=true` but no `mediastack.app-key`. These are "orphan" containers.
3. For each unique app-key, call `executor.remove_app(key, delete_config=True)` and collect the `ExecutionResult`.
4. For each orphan container, log a warning to stderr (operator-facing): "Container `<name>` is labeled `mediastack.managed=true` but has no `mediastack.app-key` label; cannot dispatch to backend. Inspect manually with `docker inspect <name>`." Do NOT attempt to remove the orphan container — there is no safe app-key to pass to `remove_app`, and bypassing the backend would leave state.db inconsistent.

The deduplication in step 1 matters: a single app may have multiple labeled containers (e.g., a main service container plus a sidecar). All such containers share the same `mediastack.app-key` value; `executor.remove_app` is responsible for removing all of them via its `fragment` step (the seven-step sequence includes compose-fragment removal which `docker compose down`s all of an app's containers atomically). `clean` does not need to call `remove_app` multiple times for the same app.

#### §C.4 — Pre-conditions

`clean` requires the mediastack service to be `active (running)`. The seven-step `remove_app` sequence invokes backend-side operations (hostname unregistration, state.db updates, app registry mutations) that require the backend process alive. If the service is not active, `clean` cannot proceed.

The pre-condition check runs after §A's state-file refusals and before any side effect:

```
systemctl is-active mediastack.service
```

If this returns anything other than `active`, `clean` emits to stderr:

```
The mediastack service is not running. The 'clean' subcommand requires
the service active to dispatch per-app removal through the backend.

Start the service first:

    sudo systemctl start mediastack.service

Or use 'uninstall' / 'purge' for full removal that doesn't require the
service running.
```

…and exits 1. The `clean` subcommand does not accept a `--force` flag; passing `--force` results in argparse rejection (`unrecognized arguments: --force`, exit 2). This is deliberate: there is no operator-level escape hatch for the active-service requirement, and no safe way to clean apps without the backend alive. If the service is inactive, the operator must start it first (`sudo systemctl start mediastack.service`) or use `uninstall`/`purge` for full removal that does not require the service active.

A more subtle case: the service is `active` per `systemctl` but the backend is in a degraded state (database not responding, app registry corrupted, hostname unregistration failing). The backend will report this via `ExecutionResult.failed` per call; `clean`'s aggregation (§C.5) propagates the per-app failure to the operator. No additional pre-condition check beyond `systemctl is-active` runs — the backend's own probes (`/readyz`, etc.) are the responsibility of the install-time smoke test, not of `clean`. If the operator wants to verify backend health before running `clean`, they can `curl localhost:<port>/readyz` themselves.

#### §C.5 — `ExecutionResult` aggregation

Each `remove_app(key, delete_config=True)` call returns an `ExecutionResult` with per-step status. The aggregation logic:

- **All apps return `ExecutionResult.ok` for every step** → overall success; exit code 0.
- **Some apps return `ExecutionResult.warning` (steps completed but with non-fatal issues, e.g., hostname unregistration failed but container removed)** → partial success; exit code 0; operator sees the per-app warnings.
- **Any app returns `ExecutionResult.failed` (at least one step did not complete)** → partial failure; exit code 1; operator sees which apps failed and at which step.

The exit code distinguishes "all-clean (audit gate would pass)" (0) from "some apps could not be cleaned (audit gate may not pass)" (1). Warnings do not move the exit code because the container layer was successfully cleaned even if metadata operations had issues; INV-14 verifies the container layer specifically (no managed containers remain), which is the load-bearing invariant.

#### §C.6 — Per-app fidelity post-output specification

`clean`'s stdout output reflects the aggregation from §C.5 with per-app fidelity. The format (Refinement 2 from operator response):

```
Cleaning managed apps...

  jellyfin        ok       (stopped, unwired, removed)
  sonarr          ok       (stopped, unwired, removed)
  radarr          warning  (removed; hostname unregistration failed — see logs)
  homeassistant   failed   (stop succeeded; container removal failed: <reason>)
  immich          ok       (stopped, unwired, removed)

Orphans (managed label without app-key):
  legacy-container-7   inspect with: docker inspect legacy-container-7

Summary: 3 ok, 1 warning, 1 failed, 1 orphan
```

The per-app rows stream to stdout as each `remove_app` call returns, not buffered to end. Operators on long-running cleans see progress; operators on quick cleans see the full list in one rush. The terminal-width-aware columnar format is Sonnet's implementation detail; the contract is "one row per app, status word visible, status detail visible."

The "Summary" line is mandatory; it gives the operator a one-line aggregate without re-reading the per-app list.

No row is rolled up. A `clean` with 30 apps produces 30 rows. Verbosity is accepted in v5.0; a `--brief` flag is a v5.1+ candidate if operator feedback indicates the verbosity is friction.

#### §C.7 — Confirmation prompt text

```
About to reset all managed mediastack apps on <hostname>:

  - jellyfin
  - sonarr
  - radarr
  - homeassistant
  - immich

For each app:
  - Container will be stopped and removed
  - Compose fragment will be removed
  - Per-app config under <data_dir>/config/<app>/ will be REMOVED
    (delete_config=True; --keep-configs is not available in v5.0)

Mediastack itself will continue running. The wizard remains accessible
at http://<hostname>:<port>/ after 'clean' completes.

Continue? [y/N]:
```

The app list is the result of §C.3 step 1 (unique app-keys). Orphan containers are mentioned in the prompt if any exist:

```
  Plus 1 orphan container (managed label without app-key) that cannot
  be cleaned automatically — will be reported for manual inspection.
```

The hostname is resolved via `installer/post_install.py::_resolve_hostname()` (IA-6 reuse). The port is read from the state file's `port` field.

#### §C.8 — Post-output URL

On overall success (all apps `ok`), `clean`'s final line after the Summary is:

```
Mediastack remains running at http://<hostname>:<port>/
```

…where `<hostname>` comes from the same `_resolve_hostname()` and `<port>` from the state file. The line confirms to the operator that the runtime survived the clean and the wizard is reachable.

On partial-failure aggregation states (any `failed`), the URL line is suppressed in favor of operator attention on the failures. The operator can still navigate to the wizard, but the message would distract from the per-app failure that needs action. On partial-warning states (some `warning`, no `failed`), the URL line is shown — warnings are informational, not blocking.

### §D — Cross-cutting two-label scheme

The two-label scheme makes `clean` and `purge` mechanically possible. Without labels, container and volume enumeration would require fragile filesystem grep or backend-state-database queries; with labels, `docker` is the single source of truth and enumeration is one command. The scheme is documented here because all three subcommands (uninstall does not use it; purge uses it for U6/U7; clean uses it for §C.2/§C.3) and the backend code (which applies the labels at compose-fragment write time) all depend on a consistent contract.

#### §D.1 — Label contract

Two labels, applied to every container and volume mediastack creates:

| Label | Value | Purpose |
|---|---|---|
| `mediastack.managed` | `"true"` | Filter for `docker ps`/`docker volume ls` enumeration; audit-gate INV-15 verification |
| `mediastack.app-key` | `<app-key>` (e.g., `"jellyfin"`) | Compose-with-backend lookup for `clean`; per-app fidelity in §C.6 output |

Both labels are required on every managed container and every managed volume.

`mediastack.managed=true` is the simple filter. `purge` uses it directly (`docker ps -a --filter label=mediastack.managed=true`). Audit-gate INV-13 uses it directly. Operators inspecting their host with `docker ps --filter label=mediastack.managed=true` see only mediastack-managed containers, which is operationally useful beyond just `purge`/`clean`.

`mediastack.app-key=<key>` is the dispatch key for `clean`. Without it, `clean` would have to either (a) reverse-engineer the app-key from the container name (fragile, name conventions vary), or (b) consult the backend's app registry over HTTP and reconcile against the container list (extra round-trip, possible inconsistency). The label is the single authoritative mapping from container to app-key. The label's value is the same string the backend uses internally for the app — Sonnet locates the exact module that emits this value during Step 4.1.b implementation.

A container with `mediastack.managed=true` but no `mediastack.app-key` is an orphan and is reported by `clean` (§C.3 step 2); it is removed by `purge` because the `managed` label alone is sufficient for U6.

A container with `mediastack.app-key=<key>` but no `mediastack.managed=true` should not exist — the labels are applied together — but if it does, it is invisible to both `clean` (which filters by `managed`) and `purge` (same). This is an acceptable failure mode: the container is invisible to mediastack tooling and the operator must remove it manually. The audit gate's INV-15 detects this state at audit time (every container with `app-key` should also have `managed`); the inverse check is intentionally not enforced because a stray `mediastack.app-key=junk` label on someone else's container should not cause mediastack's audit gate to fail.

#### §D.2 — Backend application contract

The labels are applied by the backend's compose-fragment generator at the time each fragment is written to `<data_dir>/data/compose/<app>.yaml`. The application is part of compose-fragment generation, not a post-hoc decoration: a container created from a compose fragment that lacks the labels is a **backend bug**, not an installer concern.

Sonnet's Step 4.1.b implementation work includes locating the exact module in `backend/manifests/` (or `backend/core/compose.py`, or wherever the compose-fragment generation lives) that emits the `labels:` block for each managed container and volume, and extending it to emit both labels. The placement is mechanical against the current code; the operator verification at design start confirmed the backend's compose-fragment generation is well-structured and has clear extension points.

The two-label scheme applies to compose-fragment writes that happen *after* Step 4.1.b lands. Compose fragments that exist on a v5.0 host from an earlier install (pre-Step-4.1.b) and have not been regenerated will not have the labels. The audit gate's INV-15 verifies labels on `docker ps -a` output (i.e., on live containers), so a re-deployed app will have the labels even if its compose fragment was old; a never-redeployed app from an old compose fragment will not. For v5.0.0 audit-gate purposes, the audit gate runs against fresh installs on clean VMs (Step 4.5.a finding 1), so the old-fragment case does not arise in the audit.

#### §D.3 — Pre-v5.0 containers

Containers created by v4.x or pre-v5.0 mediastack do NOT have the two labels. `purge` will not find them via U6/U7. This is consistent with Direction Decision D7 (no v4.x → v5.0 migration tooling): pre-v5.0 installs are out of scope.

The operator handles pre-v5.0 residue manually. `INSTALL.md` (Step 4.4 doc task) documents the manual cleanup path:

```
# Find pre-v5.0 mediastack containers by name pattern (if any)
docker ps -a --filter name=mediastack
# Inspect each to confirm it's mediastack-managed (not a coincidence)
docker inspect <container-name>
# Remove manually after verification
docker rm -f <container-name>
```

The manual path is more friction than the labeled path, which is the cost of D7. v5.1 may revisit if migration tooling becomes a priority.

#### §D.4 — Label spoofing risk

The `mediastack.*` label namespace is project-owned by convention. A third-party tool that applies `mediastack.managed=true` to its own containers would have those containers removed by `purge`, which is operator-meaningful damage if the operator did not realize the collision. The mitigation is documentation: `INSTALL.md` names the `mediastack.*` namespace as reserved and warns against external use.

No code-level mitigation is implemented. Verifying that every `mediastack.managed=true` container has a compose fragment in `<data_dir>/data/compose/` and a matching entry in `state.db` would catch label-spoofing but adds complexity for a low-probability scenario. v5.0 accepts the risk and documents the convention; v5.1 may add verification if collision is observed in the wild.

The class prediction in S.4 names this risk for audit-gate awareness.

## Layout invariants

INV-12 through INV-16 extend ADR 0013's INV-1 through INV-6 and ADR 0015's INV-7 through INV-11. They are the structural-equivalent of "what an auditor checks on a successfully-uninstalled, successfully-purged, or successfully-cleaned v5 install."

| # | Invariant | Verification | Audit-gate finding |
|---|---|---|---|
| INV-12 | After `uninstall`: U1, U2, U3, U4 (subject to §A.6), U4b (subject to §A.6.5), and U5a all hold. | `installer/uninstall.py::verify_removed(install_dir, data_dir, mode='uninstall')` returns success. | V5_INSTALLER_PLAN.md Step 4.5.a finding 3, extended (uninstall+purge leaves no mediastack files behind — uninstall half). |
| INV-13 | After `purge`: U1, U2, U3, U4 (subject to §A.6), U4b (subject to §A.6.5), U5b, U6, U7 all hold. | `verify_removed(install_dir, data_dir, mode='purge')` returns success. | Extends ADR 0013 INV-4 with the explicit two-label scheme. Replaces ADR 0013 INV-4's "label set per ADR 0014" forward reference. |
| INV-14 | After `clean`: U1 violated (`systemctl is-active` returns `active`), U2 violated, U3 violated, U4 violated, U4b violated, U5a violated (data dir still present), U6 holds (managed containers absent), U7 holds (managed volumes absent). | `verify_removed(install_dir, data_dir, mode='clean')` returns success — note the U-predicate polarity is reversed for this mode. | New, augments finding 3 (clean leaves mediastack itself untouched). |
| INV-15 | Every container labeled `mediastack.managed=true` also has a `mediastack.app-key=<value>` label with non-empty value. | `docker ps -a --filter label=mediastack.managed=true --format '{{.Label "mediastack.app-key"}}'` produces no empty lines for live containers. | New, backend-application content-level check on §D.1 contract. |
| INV-16 | `clean`'s stdout output contains one per-app status line per cleaned app (one row per unique app-key processed), in the format `<app-key>\s+(ok\|warning\|failed)\s+\(.*\)`. | Regex match on the stdout against the format pattern; row count matches the unique app-key count from §C.3. | New, UX-level invariant on §C.6 fidelity. |

INV-12 and INV-13 reference U4b alongside U4 because the group-removal case is structurally as important as the user-removal case for "no mediastack residue" — a `mediastack` group lingering on a purged host is residue.

INV-14's polarity reversal is deliberate: `clean` is the one subcommand where the success state is "mediastack itself is still here." Verifying that U6/U7 hold *and* U1/U2/U3/U4/U4b/U5a all violate is what distinguishes a successful `clean` from a partial `purge`.

INV-15 verifies a backend-application contract. The audit gate runs INV-15 against a host that has installed at least one app (a baseline app, e.g., a trivial test app, may need to be installed during the audit-gate VM run before INV-15 is meaningful; this is Step 4.5's design call). If no apps are installed, INV-15 vacuously holds.

INV-16 verifies operator-facing UX at audit time. The check is run against the stdout output of a `clean` invocation on a VM with at least one app installed. The exact regex is part of the audit-gate harness, not this ADR — the contract is "one row per app, machine-greppable" and Sonnet's Step 4.1.c tests cover the format.

All five invariants are verified by the v5.0.0 audit gate against the three-distro matrix (Debian 12, Debian 13, Ubuntu 24.04 per ADR 0016). They join ADR 0013 INV-1–INV-6 and ADR 0015 INV-7–INV-11 as the structural-equivalent of "what a working v5 install passes through during its lifecycle."

## Class predictions

Per IA-2 (matrix-as-discovery vs matrix-as-regression-detector) and the prompt's required output, the following class predictions name what kinds of bugs may surface during Steps 4.1.b/c implementation. Each prediction is a *named scenario* with expected behavior, so the audit gate can mechanically check both that the predicted scenario does not silently fail AND that the handling matches the prediction. Vague predictions ("uninstall might have permission issues") only support regression detection; named scenarios support novel-class scan.

### Class A — FileNotFoundError / permission-denied

**A.1** — `userdel mediastack` invoked while a mediastack-owned process is still running (e.g., a backgrounded `python -m something` left from manual debugging). `userdel` exits nonzero with the message "user `mediastack` is currently used by process N." Uninstall reports U4 as failed with diagnostic `loginctl user-status mediastack` and `ps -u mediastack`. The install dir is still removed (B.1 order: user removal is step 7, after install dir removal at step 6). Basis: `userdel(8)` behavior on Debian/Ubuntu shadow-utils.

**A.2** — `rm -rf <install_dir>` blocked by an open file handle held by a daemon other than mediastack (e.g., a backup tool reading the directory while uninstall runs). `rm` succeeds, leaving the file marked deleted-but-open via POSIX unlink semantics. U3's `test -e <install_dir>` returns false (the directory itself is unlinked), so U3 passes; the file is reaped when the holding process closes it. No action needed. Basis: POSIX unlink + open-file semantics.

**A.3** — State file is mode 0640 owned by `mediastack:mediastack`, but the uninstaller is invoked as a regular non-root user not in the `mediastack` group. `read_state_file()` raises `PermissionError`. §A.3.5 handles this case explicitly: emit "state file unreadable — try sudo" message and exit 1 before any side effect. Basis: file-mode design from ADR 0013 §2.

**A.4** — `systemctl stop mediastack.service` when the unit has been already-stopped (e.g., operator did `systemctl stop` manually before running `uninstall`). `systemctl` exits 0 with no-op output. B.1 step 3 succeeds; no special handling needed. Basis: `systemctl(1)` idempotency on already-stopped units.

**A.5** — `docker rm` during `purge`, but the Docker daemon is down. `docker` exits nonzero with "Cannot connect to the Docker daemon." U6 fails with the second failure shape ("Docker daemon unreachable"). Diagnostic: `systemctl status docker`. Basis: `docker(1)` exit codes and daemon-connection error patterns.

### Class B — state-machine inconsistencies

**B.1** — `uninstall` when state file is `phase=installing` (interrupted install, ADR 0013 §4 S3). `read_state_file()` succeeds (the file is well-formed), so §A.2/§A.3 do not refuse. Uninstall proceeds normally: whatever pipeline progress was made gets removed. The `phase=installing` vs `phase=installed` distinction matters for install refusal logic, not for uninstall — uninstall removes what's there. Basis: ADR 0013 §4 S3 message.

**B.2** — `uninstall` when state file is `phase=installed`, `smoke_test_passed=false` (ADR 0015 §7 S2b). `read_state_file()` succeeds; uninstall proceeds normally. The smoke-failure state doesn't change what's on disk — the pipeline completed, the install dir is fully populated. Basis: ADR 0015 §7.

**B.3** — `uninstall` when no state file but install dir exists (ADR 0013 §4 S5 partial). §A.2 refusal triggers; operator gets the "not a v5 install detected" message. **Discomfort note:** an S5 install dir from a hand-rolled deploy or an interrupted install IS something the operator might want `uninstall` to clean. But `uninstall` cannot know which paths to remove without the state file. The right answer is "manual cleanup with INSTALL.md guidance." This is the structural inverse of ADR 0013 §4's S5 reasoning (install refuses S5 without `--force`; uninstall refuses S5 unconditionally because there's nothing to forward to). Basis: ADR 0013 §4 S5 rationale, mirrored.

**B.4** — `uninstall` when state file is corrupted (S4). §A.3 refusal triggers. `--force` does not override. Basis: §A.3.

**B.5** — Concurrent `install.sh` and `mediastack uninstall` invocations on the same host. State file race: install may be writing while uninstall is reading. v5.0 does not implement file locking on the state file (out of scope: no v5.0 file-locking ADR). The window is small but the failure mode is undefined. **Unknown — verify during implementation.** If the failure is graceful (one or the other exits 1 with a clear message), accept and document. If the failure is catastrophic (the state file becomes corrupted; the install dir is left in an inconsistent state), file as a Tier 4 follow-on for a file-locking ADR.

**B.6** — `uninstall` when `POST_INSTALL.txt` was manually deleted (state file says `smoke_test_passed=true` but the file is gone, violating ADR 0015 INV-9). `read_state_file()` succeeds; uninstall proceeds normally. The S2a/S2b distinction is for install refusal (§7 of ADR 0015); uninstall removes whatever is there. Basis: ADR 0015 §7 inheritance.

**B.7** — `clean` when state file is `phase=installing` (install in progress). §C.4 refusal triggers because mediastack service is likely not `active (running)` yet. If service IS active despite `phase=installing` (an unusual state), the refusal logic is still correct because `clean` is a runtime operation and `active (running)` is the load-bearing precondition. Edge case: service active + phase=installing is structurally rare. **Unknown — verify during implementation** whether the rare case is reachable and whether `clean`'s behavior is correct.

### Class C — UX surprises

**C.1** — `--yes` propagates from a wrapper script accidentally (e.g., operator wrote `alias mediastack='mediastack --yes'` for `clean` convenience, then ran `mediastack purge` expecting confirmation). No confirmation; data dir gone before operator realizes. Mitigation: `--yes` is per-subcommand-named in the confirmation skip behavior (no global default); INSTALL.md documents the recommended invocation patterns. No code-level fix.

**C.2** — TTY detection fails in CI (CI runs `mediastack uninstall` without `--yes`, expecting interactive). §A.4's pipe-mode requirement triggers fail-fast. Operator's CI config needs `--yes`. INSTALL.md documents.

**C.3** — `clean`'s per-app summary is too verbose for hosts with many apps. A 30-app host produces 30+ rows of output (plus orphans, plus summary). v5.0 accepts verbosity; a `--brief` flag is a v5.1+ candidate if operator feedback indicates the verbosity is friction. Basis: ad-hoc — verify against real operator deployments.

**C.4** — Operator runs `uninstall` expecting `purge` semantics (data dir untouched, operator surprised). Mitigation: the confirmation prompt (§B.6) explicitly names the preserved data dir AND points at `purge` for the irreversible option. Operators who skip reading the prompt (via `--yes`) accept the consequence.

**C.5** — `clean` takes longer than expected because `executor.remove_app`'s seven-step sequence × N apps may be 30s+. Operator wonders if the process is hung. Mitigation: per-app status lines stream as each `remove_app` returns (§C.6), giving visible progress. No spinner or progress bar; the streaming rows are sufficient.

**C.6** — Mixed `ok` / `warning` / `failed` aggregation confuses operator. Per-app fidelity (§C.6) is the mitigation. Exit code (§C.5): 0 if all `ok`, 1 if any `failed`, 0 if `ok`+`warning` only — warnings are operator-info not blocking. This is a contract operators need to learn from INSTALL.md.

### Class D — distro-specific

**D.1** — `systemctl` behavior across systemd versions. Debian 12 ships systemd 252; Debian 13 ships 256; Ubuntu 24.04 ships 255. The `is-active`, `stop`, `disable`, `daemon-reload` subcommands are stable across all three; no expected divergence. Basis: systemd release notes for the relevant subcommands.

**D.2** — `userdel` behavior with active processes. Debian and Ubuntu both refuse by default (the §A.1 prediction). Both honor `--force` (which v5.0 does NOT pass — we want the refusal so the operator knows). Behavior is consistent on supported distros per ADR 0016. Basis: shadow-utils consistency.

**D.3** — Docker socket location. Rootless Docker places the socket at `$XDG_RUNTIME_DIR/docker.sock`; rootful at `/var/run/docker.sock`. v5.0 assumes rootful per ADR 0013 §5's docker-group rationale. `docker` CLI on a rootless-configured host would fail with "cannot connect" unless `DOCKER_HOST` is set — `purge`'s U6 failure would surface this. Basis: Docker rootless documentation; out of scope for v5.0 fix.

**D.4** — apt-installed packages NOT removed by `uninstall`/`purge` (Docker engine, Node.js, Python 3.11, curl, netcat-openbsd, git). The installer added them with operator consent; the uninstaller does not remove them. INSTALL.md documents this explicitly. Basis: D3 rationale (operator consented to install; operator decides removal).

**D.5** — SELinux/AppArmor on `/opt/mediastack` blocking removal. No MAC profile is applied by the installer; default profiles on Debian/Ubuntu do not block. **Unknown for non-default configurations** (e.g., operator-installed AppArmor profile on `/opt`); if encountered in the wild, file as Tier 4 follow-on documentation.

### Class S — security/safety

**S.1** — TOCTOU race on data-dir removal in `purge`. Operator creates `/var/lib/mediastack -> /` symlink between state-file read and `rm -rf`. Mitigation: `rm -rf` uses `--one-file-system` to limit damage to a single filesystem boundary; `--no-preserve-root` is explicitly NOT passed (so `rm -rf /` is rejected by `rm` itself). Sonnet's Step 4.1.b implementation should also `realpath`-resolve the data dir before unlink and refuse if the resolved path differs from the state-file-recorded path. **Unknown — verify during implementation** whether all three guards land.

**S.2** — Stale credentials in `.env` (mode 0600 in `<data_dir>`) left behind if `executor.remove_app`'s state-cleanup phase fails partway in `clean`. The `.env` file is backend-owned (ADR 0013 §1 boundary 2); `clean`'s contract is to dispatch to `remove_app`, not to clean up the backend's residue if `remove_app` fails. The operator-facing failure (§C.6 row with `failed` status) signals the residue. `purge` removes the entire `<data_dir>` including `.env`, so `purge` is the residue-free path. Basis: backend `remove_app` contract; `.env` is per-host not per-app, so this is more of a `purge` concern.

**S.3** — `purge` invoked with `--yes` on the wrong host (operator's terminal has multiple SSH sessions open; types `mediastack purge --yes` in the wrong one). Mitigation: confirmation prompt (§B.6) names the host's `<hostname>` so an operator who *did* see the prompt would notice the wrong host. With `--yes`, the prompt is skipped, so the only mitigation is operator discipline. INSTALL.md documents the recommended invocation patterns (run `purge` interactively, not via wrapper scripts).

**S.4** — Label spoofing (§D.4). A third-party tool applies `mediastack.managed=true` to its own containers; `purge` removes them. No code-level mitigation in v5.0; doc note in INSTALL.md names the `mediastack.*` namespace as reserved. Basis: §D.4 rationale.

**S.5** — `clean` always passes `delete_config=True` to `remove_app`. Per-app config under `<data_dir>/config/<app>/` is removed. Operators who wanted to preserve configs while resetting containers have no recourse — the only granular option is the backend's UI with `deleteConfig=false`. Trade-off: `clean` IS a reset; preserving configs partially defeats the point. v5.1 may add `--keep-configs`. Documented in §C.1 rationale.

**S.6** — Group `mediastack` has additional members from third-party tooling. `getent group mediastack` shows members beyond the `mediastack` user. §A.6.5 refuses `groupdel`; operator is informed; rest of uninstall continues. The other members are not removed from the group (that would require active modification of the group, not just refusal to delete). The operator decides whether to clean up the group manually. Basis: symmetry with §A.6 rationale.

## Consequences

The substantive code and document changes that follow from this ADR:

- `installer/uninstall.py` (new module) implements the three subcommand functions plus `verify_removed()` per §A.7. Entry points `_cmd_uninstall`, `_cmd_purge`, `_cmd_clean` in `installer/main.py` are extended from Tier 1.3.b stubs to dispatch into `installer/uninstall.py` (V5_INSTALLER_PLAN.md Step 4.1.b).
- `installer/uninstall.py::verify_removed(install_dir, data_dir, mode)` is the single audit-mode hook (§A.7) — installer-importable, no new `tools/` wrapper per IA-4. The function reads filesystem and Docker state via `installer._run.run_required` per Core Rule 5.27.
- `installer/tests/test_uninstall.py` covers all U-predicates (§B.2), the §A refusal logic, the §A.6/§A.6.5 carve-outs, the §C aggregation, and the §C.6 output format. Tests use the inject-kwargs pattern per Core Rule 5.27 discipline and the precedent set by `installer/tests/test_smoke.py` and `installer/tests/test_main.py`.
- `backend/manifests/<compose-generator>` is extended to apply both labels (`mediastack.managed=true` and `mediastack.app-key=<key>`) on every container and volume per §D.2. Sonnet's Step 4.1.b implementation locates the exact module; the operator's design-start verification of the backend's compose-fragment generation gives high confidence the extension point is clear.
- `tools/install-smoke` harness is extended for INV-12 through INV-16 verification on dev VMs (extends the install-smoke pattern from Step 3.2.d's INV-7 through INV-11 harness work).
- Paired-commit retag of ADR 0013's forward references: §1 Scope ("ADR 0014's subject" → "ADR 0017's subject"), §3 boundary 4 ("ADR 0014" → "ADR 0017"), INV-4 ("label set per ADR 0014" → "label set per ADR 0017 §D"). The retag commit is small and mechanical; bundling with this ADR's substantive content is acceptable.
- Paired-commit retag of ADR 0015's forward reference: INV-11 ("along with everything else INV-4 lists" → "along with the rest of ADR 0017 INV-13's predicates").
- Paired-commit edit of `V5_INSTALLER_PLAN.md`: Step 4.1.a "Write `docs/adr/0014-uninstall-semantics.md`" → "Write `docs/adr/0017-uninstall-semantics.md`."
- Paired-commit IA-5 baseline capture: `docs/cleanup/ms_enforce_baseline_2026_05_18.txt` (or whatever date is at apply time) captured by Sonnet via `ms-enforce --fast` at apply-time, before the uninstall ADR's prose commit lands. The uninstall ADR's Consequences cite this file as the content-level baseline; the v5.0.0 audit gate cites the same file.
- Core Rule 5.26 (installer hardcoded paths) is unaffected — `uninstall.py` reads `<install_dir>` and `<data_dir>` from the state file exclusively; no literal paths are added.
- `docs/agent-context/CITATIONS.md` gains three entries (per operator request, drafts at the end of this document): `COMPOSE-WITH-BACKEND`, `ADR-0017-INV-13`, `LABEL-SCHEME`. Sonnet's apply-session lands these.
- `docs/cleanup/COMPLETION_AUDIT_v5_0_0.md` (Step 4.5.a, future work) verifies INV-12 through INV-16 against the three target distros. The audit-gate findings list extends: finding 3 ("uninstall+purge leaves no mediastack files behind") gains explicit INV-12 + INV-13 + INV-14 verification, finding 11 ("ADRs land") adds ADR 0017 to the required-landed list, finding 7 (structural audit clean) extends to INV-15 (label-application content-level check).

## What this does NOT govern

- *The internals of `backend/manifests/executor.py::remove_app()`.* This ADR specifies the call contract (input/output) but not the seven-step internals. Changes to the steps' order, the `ExecutionResult` semantics per step, or the failure-recovery logic inside the function are backend concerns. If `remove_app`'s signature or return shape changes, §C composition needs amendment.
- *The exact module in `backend/manifests/` (or `backend/core/compose.py`) that applies the two labels.* Sonnet's Step 4.1.b investigation locates this; the ADR specifies the contract, not the file path.
- *The v5.0.0 audit gate's evidence-archival path and manifest format.* This ADR specifies what evidence the subcommands produce (`verify_removed()` structured output, `docker ps` listings, per-app `ExecutionResult` lists); Step 4.5's audit-gate work decides where the evidence commits and how the manifest is structured.
- *Operator-facing recovery procedures for `purge` mistakes.* `purge` is irreversible by design; there is no v5.0 "undo." Backup-and-restore is an operator concern outside the installer's scope. v5.1+ may add a snapshot subcommand if operator feedback indicates it's wanted.
- *Pre-v5.0 container cleanup automation.* Manual per §D.3.
- *Rootless Docker, scoped sudoers, alternative isolation models.* ADR 0013 §5 security note carries forward.
- *ARM64 audits.* ADR 0016 defers ARM64 explicitly; this ADR inherits the scope.
- *Migration tooling v4.2 → v5.0.* Out per D7.
- *A standalone `mediastack uninstall-replay` subcommand for interrupted uninstalls.* v5.1+ candidate; the state-file-no-write decision (A) accepts the consequence (no replay capability) for v5.0.
- *The `--keep-configs` variant of `clean`.* v5.1+ if operator feedback indicates wanted; v5.0 is opinionated (`delete_config=True` hardcoded).

## Alternatives considered

**Decision (B): pre-uninstall write `phase=uninstalling`.** Rejected. Requires expanding the `phase` enum's domain from `{installing, installed}` to `{installing, installed, uninstalling}`; per ADR 0013 §2 "Schema evolution," any change to a field's domain is a schema-version bump. The bump would force `schema_version: 2` with a `migrate_1_to_2()` function plus a new refusal state (S6: state file says `uninstalling`) in `installer/install.py::detect_existing_install()`. The cost is the schema bump for the entire v5.0.x line; the benefit is the diagnostic field for interrupted uninstalls, which v5.0 has no consumer for. Deferred to v5.1+ if an `uninstall-replay` subcommand is added — then the cost/benefit balance flips. The forward-compatibility cost is paid then, not now.

**Decision (C): new field `uninstall_started_at`.** Rejected for the same reason as (B): any field addition bumps `schema_version` per ADR 0013 §2's "strict on any change" rule. The cost is the same as (B); the benefit is even smaller (just a timestamp, no enum-state information). Strictly dominated by (B) and by the chosen (A).

**`clean` as "transient artifacts" cleaner (pipx caches, downloaded but unused models, logs older than N days).** Rejected per the framing-correction round at session start. The plan's `clean` (managed-Docker reset) is the load-bearing semantic per V5_INSTALLER_PLAN.md D10 and Step 4.1.a, the v5.0.0 audit-gate finding 3 (uninstall+purge leaves no mediastack files behind) referencing managed containers/volumes, and ADR 0013 INV-4's enumeration of "any Docker container labeled as mediastack-managed." Re-defining `clean` as a cache-cleaner would either contradict those references or require renaming the existing operation, both of which are more disruptive than accepting the plan version. A separate cache-cleaning subcommand (e.g., `prune`) for a future release is the right shape if the operation is wanted; v5.0 does not implement it.

**Single-label scheme: `mediastack.managed=true` only, no `mediastack.app-key`.** Rejected per the operator's Refinement 1 in the framing-correction round. Without the app-key label, `clean` would have to reverse-engineer the app-key from container names (fragile) or consult the backend's app registry over a separate HTTP call (extra round-trip plus possible inconsistency). The two-label scheme is the structural deliverable that makes `clean`'s compose-with-backend design mechanical. The cost is one extra label per container; the benefit is dispositive enumeration without reverse-engineering.

**Duplicate `executor.remove_app`'s seven-step sequence in `installer/uninstall.py`.** Rejected per the operator's verification at design start. The backend's `remove_app` is well-structured (commit a681874 split `_remove_inner` into per-phase helpers; the function returns rich `ExecutionResult` per step; the UI calls it via the same path). Re-implementing the sequence in installer code would create two parallel implementations to maintain, with predictable divergence over time (the backend evolves; the installer copy lags; bugs surface). Composition with the backend is the right shape; the cost is the HTTP round-trip per app and a dependency on the backend being `active (running)` (§C.4 pre-condition), both of which are accepted.

**Standalone `tools/check-uninstall-residue.py` for audit-mode verification.** Rejected per IA-4 (tools/ subprocess wrapper duplication concern). `installer/uninstall.py::verify_removed()` is installer-importable; the audit gate consumes it directly. A new `tools/` script would extend F-OF-3's duplication (the existing `tools/check-readiness.py` and `tools/capture-step33-evidence.py` already inline-re-implement Core Rule 5.27's `run_required` wrapper). Avoiding the structural debt's growth is the right choice for v5.0; the F-OF-3 structural fix (extract `tools/_run.py`) remains deferred-post-v5.0.

**`uninstall` removes apt-installed packages (Docker engine, Node.js, Python 3.11, curl, netcat-openbsd, git).** Rejected per D3 rationale. The operator consented to install these (interactively or via `--install-docker=yes`); the operator decides removal. The installer is not the right tool to remove apt packages; the operator's distribution's package manager is. INSTALL.md documents the manual `apt purge` invocation for operators who want full system rollback.

**Per-app confirmation in `clean` (prompt y/N for each app).** Rejected. The operator already typed `clean`; per-app prompts are friction without safety benefit. Per-app fidelity is in the OUTPUT (§C.6), not the prompt — the operator sees per-app status after the fact and can act on individual failures.

**`uninstall` refuses to proceed on S2b (smoke-failed install).** Rejected. Removing a broken install is the obvious case to support; refusal would be hostile. The S2b state means the pipeline completed but smoke failed; `uninstall` should help, not block.

**Add `--dry-run` flag to all subcommands.** Considered. A `--dry-run` mode that prints the actions without executing has obvious value for operator confidence. Deferred to v5.1+ because the design is more involved than it looks (e.g., `clean`'s `--dry-run` would need to enumerate containers and ask the backend "what would `remove_app` do?" without actually doing it, requiring backend-side support). v5.0 ships without `--dry-run`; the confirmation prompt (§B.6, §C.7) is the safety surface.

**Add `--keep-configs` flag to `clean`.** Considered. Operators who want to reset containers but preserve per-app configs (e.g., to migrate the config to a new app instance) have a clear use case. Deferred to v5.1+ because (a) the use case is theoretical for v5.0 (no operator feedback yet), (b) `executor.remove_app(key, delete_config=False)` already exists in the backend so adding the flag is mechanical when wanted, and (c) v5.0's opinionated `delete_config=True` matches the "clean is a reset" intent. The deferral is named in §C.1 rationale.

**Add `--brief` flag to `clean`.** Considered. A `--brief` mode that prints only the summary line (no per-app rows) would help operators with many-app hosts. Deferred to v5.1+ pending operator feedback that the verbosity is friction.


## Status

Accepted; implemented in V5_INSTALLER_PLAN.md Step 4.1.b (`installer/uninstall.py`) and Step 4.1.c (tests in `installer/tests/test_uninstall.py`). Verified by V5_INSTALLER_PLAN.md Step 4.5 audit invariants INV-12 through INV-16.

Depends on the paired-commit edits to ADR 0013 (§1 Scope, §3 boundary 4, INV-4 forward references), ADR 0015 (INV-11 forward reference), V5_INSTALLER_PLAN.md (Step 4.1.a's ADR-number citation), and the backend's compose-fragment generator (two-label application per §D.2). All paired edits land in the same commit-sequence as this ADR; the prose commit is not standalone-mergeable without the paired retags.

Depends on the IA-5 baseline capture (`docs/cleanup/ms_enforce_baseline_2026_05_18.txt` or contemporaneous date) landing before this ADR's prose commit, so the audit gate's content-level reference is stable.

Revisit when:

- v5.1's standalone smoke-rerun subcommand is added. A parallel `uninstall-replay` subcommand may be desired; the state-file no-write decision (A) is the natural reconsideration point.
- v4.x → v5.0 migration tooling ships. The pre-v5.0-container manual-cleanup path becomes formalizable, and the two-label scheme's "applies only to v5.0+ containers" caveat becomes a migration concern.
- Rootless Docker or scoped sudoers replaces docker-group membership. The §A.6 user-removal logic and the §D Docker-enumeration approach may both need amendment.
- Label-namespace collision is observed in the wild (§D.4 spoofing risk surfaces as a real incident). v5.1+ may add backend-side verification that mediastack-namespaced labels are only applied by mediastack code.
- `backend/manifests/executor.py::remove_app`'s contract changes (function signature, `ExecutionResult` shape, step set). §C composition design needs amendment.
- A `--dry-run` flag is added to all subcommands. The current confirmation-prompt safety surface becomes the dry-run output's preview surface; the design overlaps.
- A `--keep-configs` flag is added to `clean`. The `delete_config=True` hardcoding in §C.1 becomes operator-controllable; the confirmation prompt text in §C.7 needs amendment.
- Operator feedback indicates `clean`'s per-app verbosity is friction. A `--brief` flag becomes worth adding; §C.6's "no rollup" contract is loosened conditionally on the flag.

---

# Appendix — CITATIONS.md entry candidates

The three entries below are drafted for Sonnet to add to `docs/agent-context/CITATIONS.md` during the apply-session for this ADR. Each entry follows the cite-by-key shape established by the existing `D10-clean`, `D10-purge`, and `ADR-0013-INV-4` entries (per operator confirmation at the framing-correction round).

## Entry 1: `COMPOSE-WITH-BACKEND`

```
## COMPOSE-WITH-BACKEND

**Source:** `backend/manifests/executor.py::remove_app(key, delete_config=None)` at HEAD of feature/step-3-3-vm-matrix (commit a681874 split _remove_inner into per-phase helpers; subsequent commits stable).

**Verbatim seven-step sequence (operator-verified at 2026-05-18 design session):**
validate → stop → unregister → unwire → fragment → config → state

**Return shape:** ExecutionResult including per-step status (ok | warning | failed).

**UI path:** frontend/src/views/AppDetailView.vue:410 calls appsApi.remove(key, deleteConfig.value) which routes through this function.

**Why load-bearing:** ADR 0017 §C composition design depends on this contract being stable. The `clean` subcommand dispatches to remove_app per app and aggregates ExecutionResult per the per-app fidelity contract in §C.6. Future readers of clean's design verify the contract has not drifted by checking this citation against current source.

**Drift signals:** function signature changes (parameter additions or removals); ExecutionResult shape changes (step name additions, removals, or renames); step set changes (the seven-step sequence becomes six or eight). Each is a paired amendment to ADR 0017 §C.
```

## Entry 2: `ADR-0017-INV-13`

```
## ADR-0017-INV-13

**Source:** ADR 0017 §Layout invariants, INV-13.

**Verbatim:** "After `purge`: U1, U2, U3, U4 (subject to §A.6), U4b (subject to §A.6.5), U5b, U6, U7 all hold."

**Per-predicate expansion:**
- U1: `systemctl is-active mediastack.service` returns `inactive` or `unknown`
- U2: `/etc/systemd/system/mediastack.service` does not exist
- U3: `<install_dir>` does not exist
- U4: `getent passwd mediastack` returns nonzero (subject to §A.6 carve-out)
- U4b: `getent group mediastack` returns nonzero or returns single-member group (subject to §A.6/§A.6.5 carve-outs)
- U5b: `<data_dir>` does not exist
- U6: `docker ps -a --filter label=mediastack.managed=true --format '{{.Names}}'` returns empty
- U7: `docker volume ls --filter label=mediastack.managed=true --format '{{.Name}}'` returns empty

**Verification function:** `installer/uninstall.py::verify_removed(install_dir, data_dir, mode='purge')` returns success.

**Why load-bearing:** Replaces ADR 0013's stale forward-reference to "ADR 0014 INV-4." V5_INSTALLER_PLAN.md Step 4.5 audit gate (finding 3, "uninstall+purge leaves no mediastack files behind") cites this directly. Audit-gate harness uses verify_removed() per IA-4 (installer-importable, not a new tools/ wrapper).

**Drift signals:** new predicate added to U-set; carve-out conditions amended; verify_removed() return shape changes. Each is a paired amendment to ADR 0017 §B.2 and INV-13.
```

## Entry 3: `LABEL-SCHEME`

```
## LABEL-SCHEME

**Source:** ADR 0017 §D.1.

**Verbatim table:**

| Label | Value | Purpose |
|---|---|---|
| `mediastack.managed` | `"true"` | Filter for `docker ps`/`docker volume ls` enumeration; audit-gate INV-15 verification |
| `mediastack.app-key` | `<app-key>` (e.g., `"jellyfin"`) | Compose-with-backend lookup for `clean`; per-app fidelity in §C.6 output |

**Application contract (§D.2):** Both labels applied by `backend/manifests/<compose-generator>` (exact module located by Sonnet at Step 4.1.b) at compose-fragment write time. A container created without both labels is a backend bug.

**Namespace:** `mediastack.*` label keys are project-reserved. Third-party tools applying labels in this namespace risk collision with `purge`/`clean` enumeration (§D.4 — label spoofing risk).

**Why load-bearing:** Three code locations depend on this contract:
1. `installer/uninstall.py` (§C.2/§C.3 container enumeration and app-key resolution)
2. `backend/manifests/<compose-generator>` (label application at fragment write)
3. `tools/install-smoke` and v5.0.0 audit-gate harness (INV-15 verification)

Cite-by-key prevents drift across these three locations: any of the three changing its understanding of the labels surfaces as a citation mismatch rather than as silently-divergent code.

**Drift signals:** label key renamed (`mediastack.managed` → `ms.managed`); label value type changed (boolean → enum); third label added; per-volume vs per-container scope distinction added. Each is a paired amendment to ADR 0017 §D.1 and INV-15.
```

---

*End of ADR 0017 — Uninstall Semantics.*
