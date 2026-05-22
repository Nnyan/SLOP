"""backend/core/config.py

Centralised configuration. All env-var reads happen here.
Everything else imports from this module — never os.environ directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # ── Paths ──────────────────────────────────────────────────────────────
    data_dir:     Path   # writable runtime directory (DB, compose fragments, .env)
    catalog_dir:  Path   # read-only catalog YAML files
    static_dir:   Path   # compiled frontend assets

    # ── Network ────────────────────────────────────────────────────────────
    bind_host:    str
    bind_port:    int
    docker_socket: str

    # ── Feature flags ─────────────────────────────────────────────────────
    debug:        bool
    # ── Docker host path (for containerized Mediastack) ─────────────────────
    # When running inside Docker, compose fragments must reference HOST paths
    # so the Docker daemon can resolve volume mounts correctly.
    # Set MS_HOST_DATA_DIR to the host-side path (left side of volume mount).
    host_data_dir:   Path | None = None  # empty = use data_dir
    host_config_dir: Path | None = None  # empty = use config_root

    # ── Derived paths (computed properties) ───────────────────────────────
    @property
    def effective_data_dir(self) -> Path:
        """Path to use in compose fragment volume mounts.
        When containerized: the HOST path (from MS_HOST_DATA_DIR).
        When native: same as data_dir.
        """
        if self.host_data_dir and str(self.host_data_dir) not in (".", ""):
            return self.host_data_dir
        return self.data_dir

    @property
    def db_path(self) -> Path:
        return self.data_dir / "state.db"

    @property
    def compose_dir(self) -> Path:
        """Where per-service compose fragments are written."""
        return self.data_dir / "compose"

    @property
    def install_dir(self) -> Path:
        """Root of the Mediastack installation (repo root)."""
        return Path(__file__).parent.parent.parent

    @property
    def env_file(self) -> Path:
        """The .env file the user edits — also what the service reads.
        Stored in the install dir (not data_dir) so edits persist across
        ms-update without needing to copy files."""
        env_override = os.environ.get("MS_ENV_FILE")
        if env_override:
            return Path(env_override)
        return self.install_dir / ".env"

    @classmethod
    def from_env(cls) -> "Config":
        base = Path(__file__).parent.parent.parent  # repo root
        return cls(
            data_dir=Path(os.environ.get("MS_DATA_DIR", str(base / "data"))),
            catalog_dir=Path(os.environ.get("MS_CATALOG_DIR", str(base / "catalog"))),
            static_dir=Path(os.environ.get(
                "MS_STATIC_DIR",
                str(base / "backend" / "static"),  # Vite outDir in vite.config.ts
            )),
            bind_host=os.environ.get("MS_BIND_HOST", "0.0.0.0"),
            bind_port=int(os.environ.get("MS_BIND_PORT", "8080")),
            docker_socket=os.environ.get("MS_DOCKER_SOCKET", "unix:///var/run/docker.sock"),
            debug=os.environ.get("MS_DEBUG", "").lower() in ("1", "true", "yes"),
            host_data_dir=Path(os.environ["MS_HOST_DATA_DIR"]) if os.environ.get("MS_HOST_DATA_DIR") else None,
            host_config_dir=Path(os.environ["MS_HOST_CONFIG_DIR"]) if os.environ.get("MS_HOST_CONFIG_DIR") else None,
        )


# Module-level singleton — import and use directly
config = Config.from_env()
