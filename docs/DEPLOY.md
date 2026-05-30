# SLOP Deploy Model — Ownership, Updates, and Recovery

This document describes the canonical ownership model for the SLOP install directory,
how updates work, and how to manually recover a stale or history-diverged clone.

## Ownership model

The SLOP install directory (`/opt/mediastack`) is an **HTTPS git clone** owned by the
**service user `mediastack`**.

| Principal | Permitted operations |
|---|---|
| Service user (`mediastack`) | All file-touching ops: `git`, `pip`, `npm`, reading `.env` |
| `root` | **Only** `systemctl` calls (start / stop / restart / enable / daemon-reload) |

Running git, pip, or npm as root on a `mediastack`-owned tree triggers git's "dubious
ownership" guard and silently breaks the update. Always run file ops via
`sudo -u "$SVC_USER" ...`.

### Shared helper: `tools/deploy_lib.sh`

Both `ms-update` and `deploy.sh` source `tools/deploy_lib.sh`, which exposes three
canonical functions. Never re-implement these inline:

- **`detect_service_user <install_dir>`** — Echoes the canonical service user.
  Resolution order: `stat -c %U <install_dir>` → `systemctl show mediastack -p User --value`
  → fallback literal `mediastack`. Callers run every file-touching op via
  `sudo -u "$(detect_service_user "$INSTALL_DIR")" ...`.

- **`build_home`** — Echoes `${MS_BUILD_HOME:-/tmp}`. The service user (`mediastack`)
  has `HOME=/nonexistent`; npm fails without a writable HOME. Every `npm` invocation
  runs as `sudo -u "$SVC_USER" env HOME="$(build_home)" npm ...`.

- **`normalize_ownership <install_dir> <svc_user>`** — `chown -R <svc_user>:<svc_user>`
  on the tree and re-asserts `.env` mode 600. This is the single ownership normalizer;
  both scripts call it at the end of each update to undo any root-owned files left by
  `systemctl` or a pre-fix `sudo ms-update`.

## Updating an installed instance

Use either:

```bash
sudo ms-update
```

or the deploy script:

```bash
sudo -u mediastack /opt/mediastack/deploy.sh --update
```

Both tools:
1. Detect the service user via `detect_service_user`.
2. Run `sudo -u "$SVC_USER" git -C "$INSTALL_DIR" fetch origin main` (errors are
   surfaced, not swallowed).
3. Attempt a fast-forward; if the clone is diverged, fall back automatically to
   `sudo -u "$SVC_USER" git -C "$INSTALL_DIR" reset --hard origin/main`.
4. Assert `HEAD == origin/main` after the sync; exit non-zero with a loud message if
   they do not match (a green "updated" must be able to go red against physics).
5. Install updated Python packages: `sudo -u "$SVC_USER" "$VENV/bin/pip" install -q -r requirements.txt`.
6. Build the frontend with a writable HOME (because `backend/static/` is gitignored
   and deleted by `reset --hard`, the build always runs when frontend files changed):
   `sudo -u "$SVC_USER" env HOME="$(build_home)" npm --prefix frontend ci && npm --prefix frontend run build`.
7. Call `normalize_ownership` to fix any root-owned artifacts.
8. `systemctl restart mediastack` (root-only op, no `sudo -u`).

### Service port

The canonical service-port environment variable is **`MS_PORT`** (default `8080`).
`deploy.sh` bakes this into the generated systemd unit (`--port ${MS_PORT:-8080}`) and
writes `MS_PORT=<value>` into `.env`. `ms-update` reads `MS_PORT` from `.env` for its
health-check port, falling back to the legacy name `MEDIASTACK_PORT` (deprecated; a
one-line warning is printed when the fallback fires).

### Operator environment (`MS_TRUSTED_HOSTS`, `DOMAIN`)

<!-- OPERATOR-ENV: reconcile with Stream C final decision @ merge -->
Operator env `MS_TRUSTED_HOSTS` / `DOMAIN` is authoritative in the install-dir `.env`
(`/opt/mediastack/.env`); the canonical edit point is: edit `.env` then
`systemctl restart mediastack`.

`deploy.sh`'s generated unit carries `EnvironmentFile=/opt/mediastack/.env`, which
causes systemd to inject every `KEY=VALUE` from `.env` into the process environment
before FastAPI starts. Because `MS_TRUSTED_HOSTS` and `DOMAIN` are read via
`os.environ` in `backend/api/main.py`, a value set in `.env` takes effect on the next
service restart — no code change required.

```bash
# Example: allow a LAN hostname as a trusted host
echo 'MS_TRUSTED_HOSTS=myserver.local,10.0.1.51' >> /opt/mediastack/.env
systemctl restart mediastack
```

## Recover a stale or history-diverged clone (manual runbook)

Use this runbook when `ms-update` or `deploy.sh --update` cannot recover automatically —
for example, after a history-rewrite on `origin/main` (e.g. the 2026-05-28 tailscale-key
purge) leaves the local clone in a diverged state that `git pull` cannot fast-forward.

Copy and run these steps as root on the target host:

```bash
# Step 1 — Fix ownership so git can operate as the service user
chown -R mediastack:mediastack /opt/mediastack

# Step 2 — Fetch from origin (runs as the service user; errors are visible)
sudo -u mediastack git -C /opt/mediastack fetch origin main

# Step 3 — Hard-reset to the remote HEAD (safe: SLOP has no local commits)
sudo -u mediastack git -C /opt/mediastack reset --hard origin/main

# Step 4 — Install / sync Python packages
sudo -u mediastack /opt/mediastack/.venv/bin/pip install -q -r /opt/mediastack/requirements.txt

# Step 5 — Rebuild the frontend (backend/static/ is gitignored; reset wiped it)
sudo -u mediastack env HOME=/tmp npm --prefix /opt/mediastack/frontend ci --silent
sudo -u mediastack env HOME=/tmp npm --prefix /opt/mediastack/frontend run build

# Step 6 — Restart the service
systemctl restart mediastack
```

After Step 6, verify the service is healthy:

```bash
systemctl status mediastack.service
curl -s http://localhost:${MS_PORT:-8080}/api/v1/health/summary | python3 -m json.tool
```

### Why `HOME=/tmp`?

The service user `mediastack` is a system account with `HOME=/nonexistent`. npm writes
to `$HOME/.npm`; without a writable HOME, it exits with `EACCES mkdir '/nonexistent'`.
`HOME=/tmp` (or any writable directory) resolves this. The `build_home` helper in
`tools/deploy_lib.sh` codifies this convention; set `MS_BUILD_HOME` to override.

### Why `reset --hard` instead of `git pull`?

A history-rewrite on `origin/main` (e.g. to remove a leaked secret) changes commit
SHAs. The local clone's commit graph diverges from the remote's. `git pull` refuses to
fast-forward and errors out. `fetch` + `reset --hard origin/main` is the correct
recovery: it discards local history in favor of the authoritative remote. This is safe
because the install dir is an HTTPS clone — there are no local commits to lose.

## Paths reference

| Path | Purpose |
|---|---|
| `/opt/mediastack/` | Code + venv (install dir); HTTPS git clone; owned by `mediastack` |
| `/var/lib/mediastack/` | Runtime data, DB, compose fragments (`MS_DATA_DIR`) |
| `/opt/mediastack/.env` | Secrets + operator config (mode 600; read via `EnvironmentFile=`) |
| `/opt/mediastack/backend/static/` | Built frontend assets (gitignored; rebuilt on each update) |
| `/opt/mediastack/tools/deploy_lib.sh` | Shared shell helper sourced by `ms-update` and `deploy.sh` |

## See also

- `INSTALL.md` — first-time installation instructions
- `docs/INSTALL.md` — update model and `MS_PORT` reference
- `ms-update` — the primary update tool (install via `sudo ln -sf /opt/mediastack/ms-update /usr/local/bin/ms-update`)
- `deploy.sh` — full deploy / `--update` / `--frontend-only` modes
- `tools/deploy_lib.sh` — shared service-user detection, build-HOME, and ownership normalization
