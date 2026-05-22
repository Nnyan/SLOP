# Mediastack v5.0.0 Release Notes

**Release date:** 2026-05-22
**Audit subject HEAD:** 9f34e4d

v5.0.0 is the first release of mediastack's one-command installer. A single
`curl | sudo bash` command turns a fresh Linux host into a running mediastack
deployment in under five minutes. This release establishes the install /
uninstall / purge / clean lifecycle as a contract, captured across four
Architecture Decision Records (ADRs 0013, 0015, 0016, 0017) and verified
against a three-distro VM matrix.

---

## What's new in v5.0.0

### One-command installation

A single command on any supported distro performs the full install:

    curl -fsSL https://raw.githubusercontent.com/Nnyan/SLOP/main/install.sh \
      | sudo bash -s -- --install-docker=yes

The installer fetches the canonical mediastack source, installs OS
dependencies, creates the `mediastack` system user, deploys to
`/opt/mediastack`, installs and starts the `mediastack.service` systemd unit,
runs a smoke test against the running service, and writes
`/opt/mediastack/POST_INSTALL.txt` with the URL, login info, and operator
commands. The pipe-mode `--install-docker=yes|no` flag is required (no TTY
prompts in pipe mode); the installer fails fast with a clear message
otherwise.

For development or repeatable installs from a checkout:

    git clone https://github.com/Nnyan/SLOP.git
    cd mediastack
    sudo ./install.sh --install-docker=yes

### Supported distros (x86_64)

- Ubuntu 24.04 LTS (Noble)
- Debian 13 (Trixie)
- Debian 12 (Bookworm)

The audit gate verified all five lifecycle invariants (install, smoke,
uninstall, purge, idempotent re-run, `--force` data preservation) against
each distro. Ubuntu 22.04 was archived during development per ADR 0016 and
is not supported. ARM64 is deferred to a future fully-Docker release;
v5.0/v5.1 are x86_64 only.

### Lifecycle subcommands

After install, the `mediastack` CLI is available at
`/opt/mediastack/bin/mediastack`:

- **`mediastack uninstall`** — removes the install dir, systemd unit,
  service, user, and group. Preserves `/var/lib/mediastack` data dir. Per
  ADR 0017 §B.
- **`mediastack purge`** — like uninstall, plus removes the data dir and all
  containers/volumes labeled `mediastack.managed=true`. Per ADR 0017 §B.
- **`mediastack clean`** — resets all mediastack-managed apps (containers
  and volumes) while leaving mediastack itself running. Requires the
  service active. Per ADR 0017 §C.

All subcommands accept `--yes` for non-interactive use. Behavior is
contracted in ADR 0017 and verified at audit time via
`verify_removed(mode='uninstall'|'purge')`.

### Idempotency and `--force`

Re-running `install.sh` against an already-installed host is a no-op (exit
0). Use `--force` to reinstall while preserving the data dir
(`/var/lib/mediastack`). Per ADR 0013 §1 INV-5/INV-6, verified by audit
findings F-04 and F-05.

### Two-label container scheme

Mediastack-managed containers and volumes are labeled with
`mediastack.managed=true` and `mediastack.app-key=<key>`. The
`mediastack.*` namespace is reserved — see "Label namespace reservation"
in `docs/INSTALL.md`. Per ADR 0017 §D.

---

## System requirements

- **OS:** Ubuntu 24.04 LTS / Debian 13 / Debian 12 (x86_64)
- **Kernel:** 5.15+ (modern systemd, cgroups v2)
- **Disk:** ≥10 GB free on `/`
- **Memory:** 2 GB minimum, 4 GB recommended
- **Network:** outbound HTTPS to GitHub, package mirrors, NodeSource (for
  npm)
- **Docker:** ≥24.0 with compose plugin. The installer can install Docker
  via the official Docker get.docker.com script when invoked with
  `--install-docker=yes`.
- **Privileges:** root (via `sudo`) — the installer creates a system user,
  installs system packages, writes to `/opt/`, manages systemd.

The installer's `prereq_check` validates these at the start of every run
and refuses with a clear message if anything is missing.

---

## Operator usage

After install, point a browser at the URL printed in
`/opt/mediastack/POST_INSTALL.txt` (typically
`http://<host-ip>:8080/`).

Day-2 operations:

- **Check status:** `systemctl status mediastack.service`
- **Restart service:** `sudo systemctl restart mediastack.service`
- **View logs:** `journalctl -u mediastack.service -f`
- **Uninstall:** `sudo /opt/mediastack/bin/mediastack uninstall --yes`
- **Purge (full removal):** `sudo /opt/mediastack/bin/mediastack purge --yes`

See `docs/INSTALL.md` for advanced operations, label namespace details, and
troubleshooting.

---

## Audit summary

v5.0.0 ships with a completed audit gate (V5_INSTALLER_PLAN.md Step 4.5)
verifying 13 findings across three categories:

- **Block A (8 findings, F-06–F-13):** automated checks against committed
  source — ms-enforce, structural audit, pytest, GLOSSARY vocabulary
  sweep, ADRs landed and Accepted, Core Rule 5.26 enforced, ADR 0014
  disposition (Accepted), ms-enforce baseline regression closure.
- **Block B (5 findings, F-01–F-05):** real-VM verification on Ubuntu
  24.04, Debian 13, Debian 12 — install (curl|bash + git-clone), smoke
  test, uninstall+purge (INV-12+INV-13), idempotent re-run (INV-5),
  `--force` data preservation (INV-6). All PASS across all three distros.
- **Block C (5 synthetic exercises, 6.1–6.5):** Phase 6 divergence drills
  — state-file corruption non-forceable, pipe-mode missing flag, user
  attribute mismatch refusal, label-spoofed container removal, `clean`
  refuses when service inactive. All five exercises fire correctly on
  target drift.

The audit caught and fixed five code bugs in installer/main.py,
installer/uninstall.py, installer/user.py, and installer/fetch.py — all
related to either pre-flight ordering or system-call tolerance for
already-absent targets. Each fix is documented in
`docs/cleanup/COMPLETION_AUDIT_v5_0_0.md` and
`docs/cleanup/LESSONS_LEARNED.md`.

---

## Known limitations and post-v5.0 work

The following are documented and deferred to future releases:

- **Other distros (Fedora, RHEL, Arch, openSUSE):** v5.1+ scope.
- **ARM64 support:** deferred to a future fully-Docker release.
- **v4.x → v5.0 migration tooling:** not provided; v5.0 is a fresh-install
  release (Direction Decision D7).
- **Pre-release tag semver ordering:** the operator install path correctly
  filters pre-release tags, but the underlying `_parse_v5_semver` does
  not implement full semver pre-release ordering. Proper fix deferred per
  `docs/TODO_2026_05_21_post_v5_0_0_proper_semver_pre_release.md`.
- **Pre-flight ordering for Docker checks:** Docker daemon and consent=no
  edge cases fire after first writes. Deferred per
  `docs/TODO_2026_05_22_post_v5_0_0_docker_preflight_ordering.md`. Does
  not affect normal install path.
- **F-07 structural-antipattern allowlist:** test infrastructure issue
  (root-owned basetemp cascade) deferred per
  `docs/TODO_2026_05_10_root_owned_test_files.md` (v4.3 backlog).
- **F-08 known flakes:** documented in `docs/KNOWN_FLAKES.md`. The 104-test
  PermissionError cascade and 3 `test_readiness_manifest.py` failures are
  pre-existing infrastructure issues, not regressions.
- **Rootless Docker, `--dry-run`, `mediastack uninstall-replay`, standalone
  `mediastack smoke`:** alternatives considered and deferred per ADRs
  0013/0015/0017.

---

## Upgrading from v4.x

There is no automated upgrade path from v4.x to v5.0. Per Direction
Decision D7, v5.0 is a fresh-install release. Operators with a v4.x
deployment should:

1. Back up data: `/var/lib/mediastack` (or equivalent v4 data location).
2. Uninstall v4: per v4.x documentation.
3. Install v5.0: `curl -fsSL .../install.sh | sudo bash -s -- --install-docker=yes`
4. Restore data: place backed-up data in `/var/lib/mediastack` and restart
   the service.

Configuration formats may differ between v4 and v5; review your data dir
contents before restoring.

---

## Acknowledgments

v5.0.0 is the product of an extended development arc covering four tiers
of work: foundation (Tier 1), core machinery (Tier 2), distro matrix and
service contract (Tier 3), and the audit-gated release process (Tier 4).
Architecture decisions are captured in ADRs 0013, 0015, 0016, and 0017.
The audit gate is captured in `docs/cleanup/COMPLETION_AUDIT_v5_0_0.md`
and the evidence archive at `docs/cleanup/audit_v5_0_0_evidence/`.

---

## Links

- **Repository:** https://github.com/Nnyan/SLOP
- **Installation:** `docs/INSTALL.md`
- **Architecture:** `docs/adr/`
- **Audit document:** `docs/cleanup/COMPLETION_AUDIT_v5_0_0.md`
- **Glossary:** `docs/GLOSSARY.md`

---

*Tagged as v5.0.0 on 2026-05-22 by the Tier 4 §4.6 tag ceremony.*
