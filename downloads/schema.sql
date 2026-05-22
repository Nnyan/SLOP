-- Mediastack v4 — SQLite State Schema
-- GENERATED FILE — do not edit directly.
-- To update: add a migration in migrations/ and run tools/regenerate-schema-sql.py
--
-- This file is kept as a human-readable reference for the current DB schema.
-- The authoritative source of schema changes is the numbered files in migrations/.
-- See docs/cleanup/01_migrations_design.md for the rationale.

CREATE TABLE app_dependencies (
    id              INTEGER PRIMARY KEY,
    app_id          INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL CHECK (dependency_type IN ('postgres', 'redis', 'mariadb', 'app')),
    dependency_key  TEXT NOT NULL,  -- 'postgres', 'redis', or app.key
    db_name         TEXT,           -- for postgres: the database name created for this app
    db_user         TEXT,           -- for postgres: the user created for this app
    UNIQUE (app_id, dependency_type, dependency_key)
);

CREATE TABLE app_instances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_key    TEXT NOT NULL UNIQUE,       -- e.g. sonarr_debrid
    manifest_key    TEXT NOT NULL,              -- e.g. sonarr (base manifest)
    label           TEXT NOT NULL,              -- e.g. "Sonarr (Debrid)"
    role            TEXT NOT NULL DEFAULT 'default'
                        CHECK (role IN ('default', 'debrid', 'download', 'secondary')),
    app_id          INTEGER REFERENCES apps(id) ON DELETE CASCADE,
    created_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE "apps" (
    id              INTEGER PRIMARY KEY,
    key             TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    tier            INTEGER NOT NULL DEFAULT 2,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'installing'
                        CHECK (status IN (
                            'installing', 'running', 'stopped',
                            'unhealthy', 'updating', 'removing', 'error', 'disabled',
                            'failed'
                        )),
    image           TEXT NOT NULL,
    image_tag       TEXT NOT NULL DEFAULT 'latest',
    container_name  TEXT NOT NULL,
    web_port        INTEGER,
    host_port       INTEGER,
    config_path     TEXT,
    manifest_source TEXT,
    manifest_hash   TEXT,
    extra_config    TEXT,
    installed_at    INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    last_healthy_at INTEGER
);

CREATE TABLE cloud_llm_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    sanitized       INTEGER NOT NULL DEFAULT 1,  -- 1=sanitized before send
    purpose         TEXT NOT NULL DEFAULT '',     -- e.g. 'health_escalation'
    app_key         TEXT NOT NULL DEFAULT '',
    created_at      INTEGER NOT NULL
);

CREATE TABLE external_resources (
    id              INTEGER PRIMARY KEY,
    app_id          INTEGER REFERENCES apps(id) ON DELETE SET NULL,
    resource_type   TEXT NOT NULL CHECK (resource_type IN (
                        'cf_tunnel_hostname', 'cf_dns_record', 'traefik_route'
                    )),
    resource_id     TEXT,               -- CF hostname ID or DNS record ID
    hostname        TEXT,               -- e.g. sonarr.nyrdalyrt.com
    target          TEXT,               -- e.g. HTTPS:10.0.1.60:443
    config          TEXT,               -- JSON: full resource config snapshot
    provisioned_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    removed_at      INTEGER             -- NULL = still active
);

CREATE TABLE fix_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key     TEXT NOT NULL,
    error_type  TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    suggested_fix TEXT NOT NULL,
    outcome     TEXT NOT NULL DEFAULT 'pending',  -- pending | success | failure
    thumbs      INTEGER DEFAULT NULL,             -- 1=up, -1=down, NULL=no feedback
    created_at  INTEGER NOT NULL
);

CREATE TABLE health_check_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_key  TEXT NOT NULL,
    check_name   TEXT NOT NULL,
    status       TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    checked_at   INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE health_checks (
    id              INTEGER PRIMARY KEY,
    subject_type    TEXT NOT NULL,          -- app | infra | platform
    subject_key     TEXT NOT NULL,
    check_name      TEXT NOT NULL,          -- e.g. api_reachable | disk_space | wiring
    status          TEXT NOT NULL CHECK (status IN ('ok', 'warning', 'error', 'unknown')),
    summary         TEXT NOT NULL,          -- one-line plain-language result
    detail          TEXT,                   -- extended info for expansion
    auto_fix        TEXT,                   -- name of available auto-fix, NULL if none
    checked_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (subject_type, subject_key, check_name)
);

CREATE TABLE infra_migrations (
    id              INTEGER PRIMARY KEY,
    slot            TEXT NOT NULL,
    from_provider   TEXT NOT NULL,
    to_provider     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'started'
                        CHECK (status IN ('started', 'completed', 'failed', 'rolled_back')),
    steps_total     INTEGER NOT NULL DEFAULT 0,
    steps_completed INTEGER NOT NULL DEFAULT 0,
    current_step    TEXT,                   -- description of step in progress
    rollback_data   TEXT,                   -- JSON: data needed to reverse the migration
    started_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    completed_at    INTEGER
);

CREATE TABLE infra_slots (
    id              INTEGER PRIMARY KEY,
    slot            TEXT NOT NULL UNIQUE
                        CHECK (slot IN ('auth', 'tunnel', 'vpn', 'management', 'dashboard')),
    provider        TEXT,           -- e.g. tinyauth, cloudflared, gluetun
    status          TEXT NOT NULL DEFAULT 'empty'
                        CHECK (status IN ('empty', 'deploying', 'active', 'migrating', 'error', 'removed')),
    config          TEXT,           -- JSON: provider-specific config (no secrets)
    deployed_at     INTEGER,
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE infra_tunnel_providers (
    id          INTEGER PRIMARY KEY,
    provider    TEXT NOT NULL UNIQUE,   -- cloudflared | tailscale | headscale
    status      TEXT NOT NULL DEFAULT 'empty'
                    CHECK (status IN ('empty', 'deploying', 'active', 'error', 'removed')),
    config      TEXT,                   -- JSON config (no secrets)
    deployed_at INTEGER,
    updated_at  INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE llm_model_registry (
    id              INTEGER PRIMARY KEY,
    filename        TEXT NOT NULL UNIQUE,   -- e.g. phi-4-mini-instruct-Q4_K_M.gguf
    display_name    TEXT,                   -- optional friendly name
    enabled         INTEGER NOT NULL DEFAULT 0,
    -- Capabilities: JSON array of task tags
    -- Built-in tags: reasoning, json, code, fast, general, classification
    capabilities    TEXT NOT NULL DEFAULT '[]',
    -- Per-task priority scores: JSON {task_type: 0.0-1.0}
    task_scores     TEXT NOT NULL DEFAULT '{}',
    -- Overall priority for tie-breaking (1=highest)
    priority        INTEGER NOT NULL DEFAULT 5,
    -- Context window in tokens (for routing large payloads)
    context_window  INTEGER NOT NULL DEFAULT 4096,
    -- Ollama model name (how it's registered in Ollama, may differ from filename)
    ollama_name     TEXT,
    -- Notes set by user
    notes           TEXT,
    registered_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE llm_routing_log (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL DEFAULT (unixepoch()),
    app_key     TEXT NOT NULL,
    task_type   TEXT NOT NULL,          -- reasoning | json | fast | etc.
    model       TEXT NOT NULL,          -- model name used
    success     INTEGER NOT NULL,       -- 1=ok, 0=failed
    duration_ms INTEGER,               -- inference time
    error_type  TEXT,                  -- connection|timeout|parse|null
    summary     TEXT                   -- first 120 chars of LLM output
);

CREATE TABLE maintenance_windows (
    id          INTEGER PRIMARY KEY,
    app_key     TEXT NOT NULL,
    check_name  TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT 'Scheduled task',
    -- Recurrence: day_of_week 0=Mon…6=Sun, NULL=daily
    day_of_week INTEGER,
    -- Time window (UTC hour, inclusive)
    hour_start  INTEGER NOT NULL,
    hour_end    INTEGER NOT NULL DEFAULT -1,  -- -1 = hour_start+2
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE managed_services (
    id              INTEGER PRIMARY KEY,
    service_type    TEXT NOT NULL UNIQUE CHECK (service_type IN ('postgres', 'redis', 'mariadb')),
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'error')),
    container_name  TEXT NOT NULL,
    image           TEXT NOT NULL,
    host_port       INTEGER,
    data_path       TEXT,           -- host bind-mount path
    deployed_at     INTEGER,
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE manifest_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    icon            TEXT DEFAULT '📦',
    source_url      TEXT NOT NULL,       -- raw URL to the YAML manifest file
    author          TEXT DEFAULT 'community',
    verified        INTEGER DEFAULT 0,   -- 1 = reviewed by maintainers
    installed       INTEGER DEFAULT 0,   -- 1 = pulled into local custom catalog
    registry_url    TEXT,               -- which registry this came from
    fetched_at      INTEGER,
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE operation_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    op_key      TEXT NOT NULL,              -- app key being operated on
    step_name   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok','warning','error','running','skipped')),
    message     TEXT NOT NULL DEFAULT '',
    detail      TEXT DEFAULT '',
    created_at  INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE operations (
    id              INTEGER PRIMARY KEY,
    operation       TEXT NOT NULL,          -- install | remove | update | wire | swap | heal
    subject_type    TEXT NOT NULL,          -- app | infra | platform | managed_service
    subject_key     TEXT NOT NULL,          -- app.key or slot name
    status          TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed', 'rolled_back')),
    triggered_by    TEXT NOT NULL DEFAULT 'user'
                        CHECK (triggered_by IN ('user', 'cli', 'health', 'scheduler')),
    detail          TEXT,                   -- JSON: operation-specific context
    error           TEXT,                   -- plain-language error if failed
    started_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    completed_at    INTEGER
);

CREATE TABLE pending_fixes (
    id          INTEGER PRIMARY KEY,
    app_key     TEXT    NOT NULL,
    check_name  TEXT    NOT NULL,
    action_type TEXT    NOT NULL,
    problem     TEXT    NOT NULL,
    suggested_fix TEXT  NOT NULL,
    confidence  REAL    NOT NULL DEFAULT 0.5,
    status      TEXT    NOT NULL DEFAULT 'pending',
    model       TEXT,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    resolved_at INTEGER,
    UNIQUE(app_key, check_name, action_type)
);

CREATE TABLE platform (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'ready', 'error')),
    domain          TEXT,           -- e.g. nyrdalyrt.com
    wildcard_domain TEXT,           -- e.g. *.nyrdalyrt.com
    network_name    TEXT NOT NULL DEFAULT 'mediastack',
    config_root     TEXT NOT NULL DEFAULT '/srv/mediastack/config',
    media_root      TEXT NOT NULL DEFAULT '/mnt/media',
    puid            INTEGER NOT NULL DEFAULT 1000,
    pgid            INTEGER NOT NULL DEFAULT 1000,
    timezone        TEXT NOT NULL DEFAULT 'America/Los_Angeles',
    traefik_version TEXT,           -- deployed Traefik image tag
    cert_resolver   TEXT NOT NULL DEFAULT 'letsencrypt',
    installed_at    INTEGER,        -- Unix timestamp, NULL until ready
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE quickstart_phases (
    phase       TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'pending',
                -- pending | skipped | complete
    completed_at INTEGER
);

CREATE TABLE request_routing (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    media_type      TEXT NOT NULL UNIQUE
                        CHECK (media_type IN (
                            'movies', 'tv', 'music', 'books',
                            'comics', 'audiobooks', 'adult'
                        )),
    debrid_instance  TEXT,           -- instance_key of the debrid arr (e.g. radarr_debrid)
    download_instance TEXT,          -- instance_key of the download arr (e.g. radarr)
    seerr_debrid_id  INTEGER,        -- Seerr internal ID for debrid instance
    seerr_download_id INTEGER,       -- Seerr internal ID for download instance
    default_path    TEXT NOT NULL DEFAULT 'download'
                        CHECK (default_path IN ('debrid', 'download', 'ask')),
    notes           TEXT,
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE secrets (
    id              INTEGER PRIMARY KEY,
    key             TEXT NOT NULL UNIQUE,   -- env var name e.g. CF_DNS_API_TOKEN
    description     TEXT,
    service         TEXT,                   -- which app/infra slot uses this
    is_set          INTEGER NOT NULL DEFAULT 0 CHECK (is_set IN (0, 1)),
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE storage_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,       -- human label: "Main NAS", "Backblaze B2"
    source_type     TEXT NOT NULL
                        CHECK (source_type IN ('nfs', 'smb', 'rclone', 'local')),
    remote_host     TEXT,                       -- IP/hostname for nfs/smb
    remote_path     TEXT,                       -- export path or share name
    mount_point     TEXT NOT NULL UNIQUE,       -- local path: /mnt/nas01
    credentials_key TEXT,                       -- key in secrets table (smb/sftp)
    options         TEXT,                       -- JSON: mount options / rclone backend config
    is_primary      INTEGER NOT NULL DEFAULT 0, -- 1 = used as media_root fallback
    status          TEXT NOT NULL DEFAULT 'inactive'
                        CHECK (status IN ('active', 'inactive', 'error', 'mounting')),
    error_message   TEXT,
    created_at      INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at      INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE wiring (
    id              INTEGER PRIMARY KEY,
    source_app_id   INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    target_app_id   INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    wire_type       TEXT NOT NULL,      -- e.g. indexer | notification | library
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'active', 'failed', 'stale')),
    config          TEXT,               -- JSON: wire-specific data
    wired_at        INTEGER,
    checked_at      INTEGER,
    UNIQUE (source_app_id, target_app_id, wire_type)
);

CREATE INDEX idx_cloud_usage_created ON cloud_llm_usage (created_at);

CREATE INDEX idx_cloud_usage_provider ON cloud_llm_usage (provider);

CREATE INDEX idx_fix_history_app ON fix_history (app_key);

CREATE INDEX idx_fix_history_error ON fix_history (error_type, outcome);

CREATE INDEX idx_hch_key ON health_check_history (subject_key, check_name, checked_at);

CREATE INDEX idx_hch_status ON health_check_history (status, checked_at);

CREATE INDEX idx_op_steps_key ON operation_steps(op_key, created_at);

CREATE INDEX idx_operations_started  ON operations(started_at DESC);

CREATE INDEX idx_operations_subject ON operations(subject_type, subject_key);

