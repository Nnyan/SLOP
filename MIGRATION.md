# Migrating from Mediastack v3 (systemd) to v4 (Docker)

## What changed in v4

Mediastack v4 ships as a Docker image. No Python, Node, or git required on
the host. Updates are a `docker compose pull && docker compose up -d`.

The systemd deployment continues to work — `ms-update` still functions.
v4 is the **recommended** path for new installs and for anyone who wants
simpler updates going forward.

---

## Migrating an existing v3 systemd install

### 1. Verify your data directory

Your data is in one of:
- `/srv/mediastack/data/` (standard)
- `/data/mediastack/` (older layout — run `sudo ms-check` to confirm)

The data directory contains `state.db` and `compose/`. **This data migrates automatically** — no export needed.

### 2. Stop the systemd service

```bash
sudo systemctl stop mediastack
sudo systemctl disable mediastack
```

### 3. Create the Docker compose file

```bash
cd /srv/mediastack
curl -fsSL https://raw.githubusercontent.com/Nnyan/SLOP/main/docker-compose.option-b.yml \
  -o docker-compose.yml
```

### 4. Verify your .env

Your existing `/srv/mediastack/.env` works as-is. Confirm it has:
```
DOMAIN=yourdomain.com
CF_DNS_API_TOKEN=...
POSTGRES_PASSWORD=...
```

### 5. Start the Docker container

```bash
docker compose up -d
docker compose logs -f mediastack   # watch startup
```

### 6. Verify

Open http://your-server-ip:8080 — your apps, health data, and settings are all intact.

### 7. Remove the systemd service files (optional)

```bash
sudo rm /etc/systemd/system/mediastack.service
sudo systemctl daemon-reload
```

---

## Volume mount contract

The compose file mounts data at the **same absolute path** inside and outside
the container. This is required because Mediastack writes compose fragments
containing host paths like `/srv/mediastack/config/sonarr:/config` — the
Docker daemon reads these from the HOST filesystem.

```yaml
volumes:
  - /srv/mediastack/data:/srv/mediastack/data    # identical paths
  - /srv/mediastack/config:/srv/mediastack/config
```

If you use a different base path, update both sides of the volume mount AND
set `MS_HOST_DATA_DIR` and `MS_HOST_CONFIG_DIR` in the environment.

---

## Updating v4

```bash
cd /srv/mediastack
docker compose pull
docker compose up -d
```

No git, no pip, no service restart needed.
