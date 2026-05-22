# Mediastack Installation Guide

```bash
curl -fsSL https://raw.githubusercontent.com/Nnyan/SLOP/main/install.sh | sudo bash -s -- --install-docker=yes
```

## Prerequisites

- **Root access** — the installer must run as root (via `sudo` or directly as root).
- **Supported Linux distribution** — Ubuntu 24.04 LTS, Debian 12, or Debian 13 on x86_64.
  See [Supported distros](#supported-distros).
- **Internet access** — the installer clones this repository and installs system packages.
- **Python 3 and git** are installed by the installer if absent; no manual setup required.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/Nnyan/SLOP/main/install.sh | sudo bash -s -- --install-docker=yes
```

`--install-docker=yes` installs Docker via the official convenience script
([get.docker.com](https://get.docker.com)) if Docker is not already present on the host.
Use `--install-docker=no` if Docker is already installed.

This flag is **required** when running in pipe mode (`curl | bash`). The installer exits with
a non-zero status and prints an error if it is omitted in pipe mode.

On success, the installer prints a summary to stdout and writes the same content to
`/opt/mediastack/POST_INSTALL.txt`. Follow the URL in that output to reach the setup wizard.

## Advanced installation

Clone the repository to inspect `install.sh` before running it:

```bash
git clone https://github.com/Nnyan/SLOP.git
cd mediastack
sudo ./install.sh --install-docker=yes
```

Both the pipe-mode path and the git-clone path are fully supported.

### Flag reference

| Flag | Default | Description |
|---|---|---|
| `--install-docker=yes\|no` | *(required in pipe mode)* | `yes` installs Docker via get.docker.com if absent; `no` expects Docker already present on the host. |
| `--install-dir=<path>` | `/opt/mediastack` | Directory where mediastack code and state are written. Overrides the `MEDIASTACK_INSTALL_DIR` environment variable. |
| `--data-dir=<path>` | `/var/lib/mediastack` | Directory where application data is stored. Preserved across reinstalls and `uninstall`. Overrides the `MEDIASTACK_DATA_DIR` environment variable. |
| `--version-ref=<ref>` | `main` | Git branch or tag to clone. Use a release tag (e.g. `v5.0.0`) for a pinned install. |
| `--force` | *(off)* | Force reinstall even if mediastack is already installed. Preserves the data directory. |

### Examples

Install with Docker already present, using the default directories:

```bash
sudo ./install.sh --install-docker=no
```

Pin to a specific release via pipe mode:

```bash
curl -fsSL https://raw.githubusercontent.com/Nnyan/SLOP/main/install.sh \
  | sudo bash -s -- --install-docker=yes --version-ref=v5.0.0
```

Install with a custom data directory:

```bash
sudo ./install.sh --install-docker=no --data-dir=/srv/data/mediastack
```

Force reinstall after a failed or partial install (preserves the data directory):

```bash
sudo ./install.sh --install-docker=no --force
```

## Supported distros

mediastack v5.0.0 supports Ubuntu 24.04 LTS, Debian 12 (Bookworm), and Debian 13 (Trixie)
on x86_64. All required packages come from each distribution's main archive — no third-party
PPAs or non-default repositories are needed.

For the full matrix, removed versions, deferred versions, and the policy for adding new
distributions, see [`installer/SUPPORTED_DISTROS.md`](installer/SUPPORTED_DISTROS.md).

## Post-install

On a successful install the installer exits 0 and prints a summary banner to stdout. The same
content is written to `<install_dir>/POST_INSTALL.txt` (default: `/opt/mediastack/POST_INSTALL.txt`).
Open the URL in that file to reach the setup wizard.

The presence of `POST_INSTALL.txt` is the install-success invariant: it exists if and only if
the install pipeline ran to completion and the smoke test passed.

Useful commands after install:

```bash
# Check service status
sudo systemctl status mediastack.service

# Follow live logs
sudo journalctl -u mediastack.service -f

# Stop the service
sudo systemctl stop mediastack.service
```

## Uninstall

mediastack provides three subcommands. All require the state file written by the installer
(`<install_dir>/.installer-state.json`) and refuse to proceed if it is absent or unreadable.
All prompt for confirmation by default; pass `--yes` to skip the prompt (required when stdin
is not a TTY).

| Subcommand | Effect |
|---|---|
| `uninstall` | Stops the service, removes the install directory, removes the `mediastack` system user and group. **Preserves** the data directory (`/var/lib/mediastack`). |
| `purge` | Same as `uninstall`, plus removes the data directory. |
| `clean` | Removes all mediastack-managed app containers and volumes while leaving mediastack itself running. Does not touch the install directory, data directory, or state file. |

Run subcommands via the installer entry point:

```bash
sudo /opt/mediastack/installer/main.py uninstall
sudo /opt/mediastack/installer/main.py purge --yes
sudo /opt/mediastack/installer/main.py clean
```

If you have a v4.x or hand-rolled deployment without a v5 state file, the uninstaller cannot
determine what to remove. Manual cleanup is required.

For full subcommand semantics, pre-conditions, failure modes, and recovery paths, see
[`docs/adr/0017-uninstall-semantics.md`](docs/adr/0017-uninstall-semantics.md).

## Troubleshooting

### Smoke test failed during install

If the installer exits non-zero and reports that the smoke test failed, the service did not
become ready within the allotted time. Start triage with:

```bash
sudo systemctl status mediastack.service
sudo journalctl -u mediastack.service -n 100
```

Check whether port 8080 is already occupied:

```bash
ss -tlnp | grep 8080
```

After resolving the underlying issue, re-run with `--force`:

```bash
sudo ./install.sh --install-docker=no --force
```

For the named smoke-test failure shapes (predicates P1–P5) and their per-predicate diagnostic
commands, see [`docs/adr/0015-first-run-readiness-contract.md`](docs/adr/0015-first-run-readiness-contract.md) §4.

### Re-running on a host where the smoke test previously failed

If an earlier install completed the pipeline but the smoke test did not pass, the installer
reports this state on re-run (`installed`, `smoke_test_passed: false`) and refuses by default.
Re-run with `--force` to reinstall from scratch:

```bash
sudo ./install.sh --install-docker=no --force
```

`--force` preserves the data directory (`/var/lib/mediastack`) and removes the rest.

### Unsupported distribution

The installer exits immediately with an error if the host distribution is not in the supported
set. See [Supported distros](#supported-distros) and
[`installer/SUPPORTED_DISTROS.md`](installer/SUPPORTED_DISTROS.md) for the full list and the
policy for requesting additional distribution support.

### curl: Failed to connect to raw.githubusercontent.com

```
curl: (7) Failed to connect to raw.githubusercontent.com port 443 after 9 ms: Couldn't connect to server
```

The server has IPv6 configured but no working IPv6 route. curl prefers IPv6 and fails
immediately. Force IPv4 with the `-4` flag:

```bash
curl -4 -fsSL https://raw.githubusercontent.com/Nnyan/SLOP/main/install.sh | sudo bash -s -- --install-docker=yes
```

To check whether this is the cause: `curl -4 -I https://raw.githubusercontent.com` should
return HTTP 200/301 if IPv4 is working normally.
