# Migrating from Mediastack-RAD v2 → v3

## Prerequisites

Before running the migration script, ensure:

```bash
# PyYAML is required to parse the v2 docker-compose.yml
# (already in requirements.txt — install if running outside the venv)
pip install pyyaml

# Mediastack v3 must be running
./ms status   # or: curl http://localhost:8080/api/ping
```

Without PyYAML installed, the script falls back to inspecting running Docker
containers via `docker ps`. This fallback is less reliable — it can only detect
containers that are currently running and may miss stopped services or produce
incorrect names on non-standard compose project names. Install PyYAML first.

## Overview

v2 (`/opt/msrad`, commit `30c52f1`) and v3 can run **simultaneously** on
the same server. Migration is non-destructive: v3 installs apps fresh, v2 keeps
running until you're satisfied and switch over.

## v2 stack → v3 manifest mapping

| v2 compose service | v3 key          | Notes |
|--------------------|-----------------|-------|
| traefik            | *(platform)*    | Platform wizard deploys Traefik |
| cloudflared        | *(infra slot)*  | Deploy via Infrastructure → Tunnel |
| tinyauth           | *(infra slot)*  | Deploy via Infrastructure → Auth |
| sonarr             | `sonarr`        | Direct config folder re-use |
| radarr             | `radarr`        | Direct config folder re-use |
| prowlarr           | `prowlarr`      | Direct config folder re-use |
| bazarr             | `bazarr`        | Direct config folder re-use |
| overseerr          | `overseerr`     | Config folder re-use |
| sabnzbd            | `sabnzbd`       | Config folder re-use |
| qbittorrent        | `qbittorrent`   | Config folder re-use |

## Step-by-step migration

### 1. Run the v3 platform wizard

```bash
cd /opt/mediastack  # v3 repo
./ms wizard
```

Use your existing domain and config paths. The wizard deploys a new Traefik
instance on ports 81/444 (different from v2's 80/443) by default, so both
proxy stacks can coexist temporarily.

### 2. Deploy infra slots

Open the v3 UI at http://localhost:8080, go to Infrastructure, and deploy:
- **Auth** → TinyAuth (same version as v2)
- **Tunnel** → Cloudflare Tunnel (use your existing tunnel token)

### 3. Migrate app config (optional — recommended)

v3 app containers use the same config structure as v2. You can point v3 apps
at the existing v2 config directories to avoid re-configuring from scratch:

```bash
# Example: use v2 Sonarr config in v3
curl -X POST http://localhost:8080/api/apps/sonarr/install \
  -H "Content-Type: application/json" \
  -d '{"extra_env": {}}'
```

v3's `config_root` setting determines where config folders are created.
Set it to match v2's config path during the wizard, and apps will find
their existing databases automatically.

### 4. Run the migration script (automated)

```bash
python3 tools/migrate_from_v2.py \
  --v2-path /opt/msrad \
  --api-url http://localhost:8080 \
  --dry-run
```

Remove `--dry-run` to actually install the detected apps.

### 5. Verify v3 apps are healthy

```bash
./ms health status
./ms apps list
```

### 6. Switch DNS / Cloudflare Tunnel

Once v3 apps are verified, update your Cloudflare Tunnel to point at the v3
Traefik instance instead of v2. Traffic switches instantly, no downtime.

### 7. Stop v2

```bash
cd /opt/msrad
docker compose down
```

## Running the migration script

```
usage: migrate_from_v2.py [-h] [--v2-path PATH] [--api-url URL] [--dry-run]

optional arguments:
  --v2-path PATH   Path to v2 msrad directory (default: /opt/msrad)
  --api-url URL    Mediastack v3 API URL (default: http://localhost:8080)
  --dry-run        Show what would be installed without doing it
```

## Config compatibility

| App | Config path | Compatible? |
|-----|-------------|-------------|
| Sonarr | `/config/sonarr` | ✅ Full compatibility |
| Radarr | `/config/radarr` | ✅ Full compatibility |
| Prowlarr | `/config/prowlarr` | ✅ Full compatibility |
| Bazarr | `/config/bazarr` | ✅ Full compatibility |
| Overseerr | `/config/overseerr` | ✅ Full compatibility |
| SABnzbd | `/config/sabnzbd` | ✅ Full compatibility |
| qBittorrent | `/config/qbittorrent` | ✅ Full compatibility |
