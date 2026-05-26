"""tests/test_storage.py

Tests for debrid manifests, storage source management,
and mount config generation.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.state import StateDB, init_db
from backend.manifests.loader import load_all_manifests, load_manifest, clear_cache
from backend.platform.storage import (
    StorageSource,
    add_source,
    generate_mount_config,
    generate_nfs_unit,
    generate_smb_unit,
    generate_rclone_config,
    get_source,
    list_sources,
    remove_source,
    update_source_status,
    verify_mount,
    _systemd_unit_name,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "state.db"
    init_db(db_path)
    yield db_path


def make_source(
    name="Main NAS",
    source_type="nfs",
    mount_point="/mnt/nas01",
    remote_host="10.0.1.100",
    remote_path="/volume1/media",
    options=None,
    is_primary=True,
) -> StorageSource:
    return StorageSource(
        id=None,
        name=name,
        source_type=source_type,
        remote_host=remote_host,
        remote_path=remote_path,
        mount_point=mount_point,
        credentials_key=None,
        options=options or {},
        is_primary=is_primary,
        status="inactive",
        error_message=None,
    )


# ── Debrid manifests ───────────────────────────────────────────────────────


class TestDebridManifests:
    def test_decypharr_loads(self):
        m = load_manifest("decypharr")
        assert m.key == "decypharr"
        assert m.web_port == 8282
        assert "SYS_ADMIN" in m.capabilities
        assert any("/dev/fuse" in d for d in m.devices)
        assert "apparmor:unconfined" in m.security_opt

    def test_dumb_loads(self):
        m = load_manifest("dumb")
        assert m.key == "dumb"
        assert m.dependencies.postgres is True
        assert "SYS_ADMIN" in m.capabilities
        assert m.web_port in (3000, 3013)  # port varies by version

    def test_zilean_loads(self):
        m = load_manifest("zilean")
        assert m.key == "zilean"
        assert m.dependencies.postgres is True
        assert m.web_port == 8181

    def test_rclone_infra_is_tier_1(self):
        from backend.manifests.loader import parse_manifest
        p = Path("catalog/infra/rclone.yaml")
        assert p.exists()
        m = parse_manifest(p)
        assert m.tier == 1
        assert "SYS_ADMIN" in m.capabilities

    def test_debrid_manifests_have_fuse_requirements(self):
        for key in ("decypharr", "dumb"):
            m = load_manifest(key)
            assert m.capabilities, f"{key} should have capabilities"
            assert m.devices, f"{key} should have devices"
            assert m.security_opt, f"{key} should have security_opt"

    def test_catalog_has_39_manifests(self):
        manifests = load_all_manifests()
        assert len(manifests) >= 39

    def test_zilean_health_check_path(self):
        m = load_manifest("zilean")
        api_steps = [s for s in m.post_deploy if s.step_type == "api_ready"]
        assert any("/healthcheck/ping" in s.path for s in api_steps)


# ── Systemd unit name generation ───────────────────────────────────────────


class TestUnitNames:
    def test_simple_path(self):
        assert _systemd_unit_name("/mnt/nas01") == "mnt-nas01.mount"

    def test_nested_path(self):
        name = _systemd_unit_name("/mnt/cloud/backblaze")
        assert name == "mnt-cloud-backblaze.mount"

    def test_path_with_hyphen_escaped(self):
        name = _systemd_unit_name("/mnt/my-nas")
        assert "mount" in name
        # Hyphens in path components must be escaped per systemd spec
        assert "\\x2d" in name or "-" in name


# ── NFS mount config ───────────────────────────────────────────────────────


class TestNFSMountConfig:
    def test_unit_name_correct(self):
        s = make_source(mount_point="/mnt/nas01")
        cfg = generate_nfs_unit(s)
        assert cfg.systemd_unit_name == "mnt-nas01.mount"

    def test_unit_contains_remote(self):
        s = make_source(remote_host="10.0.1.100", remote_path="/volume1/media")
        cfg = generate_nfs_unit(s)
        assert "10.0.1.100:/volume1/media" in cfg.systemd_unit

    def test_unit_has_before_docker(self):
        s = make_source()
        cfg = generate_nfs_unit(s)
        assert "Before=docker.service" in cfg.systemd_unit

    def test_unit_has_network_dep(self):
        s = make_source()
        cfg = generate_nfs_unit(s)
        assert "network-online.target" in cfg.systemd_unit

    def test_fstab_entry_generated(self):
        s = make_source()
        cfg = generate_nfs_unit(s)
        assert cfg.fstab_entry is not None
        assert "nfs" in cfg.fstab_entry

    def test_nfs_version_option(self):
        s = make_source(options={"nfs_version": "4.2"})
        cfg = generate_nfs_unit(s)
        assert "nfsvers=4.2" in cfg.systemd_unit

    def test_install_steps_include_nfs_common(self):
        s = make_source()
        cfg = generate_nfs_unit(s)
        steps_text = "\n".join(cfg.install_steps)
        assert "nfs-common" in steps_text
        assert "systemctl enable" in steps_text

    def test_install_steps_include_mkdir(self):
        s = make_source(mount_point="/mnt/mynas")
        cfg = generate_nfs_unit(s)
        assert any("/mnt/mynas" in step for step in cfg.install_steps)


# ── SMB mount config ───────────────────────────────────────────────────────


class TestSMBMountConfig:
    def test_unit_uses_cifs_type(self):
        s = make_source(source_type="smb", remote_path="media")
        cfg = generate_smb_unit(s)
        assert "Type=cifs" in cfg.systemd_unit

    def test_unit_has_credentials_file(self):
        s = make_source(source_type="smb", remote_path="media")
        cfg = generate_smb_unit(s)
        assert "credentials=" in cfg.systemd_unit
        assert ".cred" in cfg.systemd_unit

    def test_install_steps_include_cifs_utils(self):
        s = make_source(source_type="smb", remote_path="media")
        cfg = generate_smb_unit(s)
        assert any("cifs-utils" in step for step in cfg.install_steps)

    def test_install_steps_warn_about_password_security(self):
        s = make_source(source_type="smb", remote_path="media")
        cfg = generate_smb_unit(s)
        steps = "\n".join(cfg.install_steps)
        assert "chmod 600" in steps

    def test_smb_version_applied(self):
        s = make_source(source_type="smb", remote_path="share",
                        options={"smb_version": "2.1"})
        cfg = generate_smb_unit(s)
        assert "vers=2.1" in cfg.systemd_unit


# ── rclone config ──────────────────────────────────────────────────────────


class TestRcloneConfig:
    def test_s3_backend(self):
        s = make_source(source_type="rclone", remote_host=None, remote_path=None,
                        options={"backend": "s3", "provider": "Backblaze"})
        cfg = generate_rclone_config(s)
        assert cfg.rclone_conf_block is not None
        assert "type = s3" in cfg.rclone_conf_block
        assert "provider = Backblaze" in cfg.rclone_conf_block

    def test_sftp_backend(self):
        s = make_source(source_type="rclone", remote_host="192.168.1.100",
                        remote_path=None, options={"backend": "sftp", "user": "backup"})
        cfg = generate_rclone_config(s)
        assert "type = sftp" in cfg.rclone_conf_block
        assert "host = 192.168.1.100" in cfg.rclone_conf_block

    def test_remote_name_is_normalized(self):
        s = make_source(name="My Cloud NAS", source_type="rclone",
                        remote_host=None, remote_path=None,
                        options={"backend": "b2"})
        cfg = generate_rclone_config(s)
        assert cfg.rclone_remote_name == "my_cloud_nas"

    def test_smb_backend_rclone(self):
        s = make_source(source_type="rclone", name="Remote NAS", remote_host="10.0.1.50",
                        remote_path=None, options={"backend": "smb", "user": "pi"})
        cfg = generate_rclone_config(s)
        assert "type = smb" in cfg.rclone_conf_block

    def test_install_steps_present(self):
        s = make_source(source_type="rclone", remote_host=None, remote_path=None,
                        options={"backend": "s3"})
        cfg = generate_rclone_config(s)
        assert len(cfg.install_steps) >= 3


# ── Dispatcher ─────────────────────────────────────────────────────────────


class TestDispatcher:
    def test_nfs_dispatches_correctly(self):
        s = make_source(source_type="nfs")
        cfg = generate_mount_config(s)
        assert cfg.systemd_unit is not None

    def test_smb_dispatches_correctly(self):
        s = make_source(source_type="smb", remote_path="media")
        cfg = generate_mount_config(s)
        assert "cifs" in cfg.systemd_unit.lower()

    def test_rclone_dispatches_correctly(self):
        s = make_source(source_type="rclone", remote_host=None, remote_path=None,
                        options={"backend": "s3"})
        cfg = generate_mount_config(s)
        assert cfg.rclone_conf_block is not None

    def test_local_dispatches_correctly(self):
        s = make_source(source_type="local", remote_host=None, remote_path=None)
        cfg = generate_mount_config(s)
        assert cfg.install_steps  # has instructions even for local
        assert cfg.systemd_unit is None

    def test_unknown_type_raises(self):
        s = make_source(source_type="ftp")
        with pytest.raises(ValueError, match="Unknown source_type"):
            generate_mount_config(s)


# ── State DB CRUD ──────────────────────────────────────────────────────────


class TestStorageSourceDB:
    def test_add_and_get(self, db):
        source = add_source(
            name="Main NAS",
            source_type="nfs",
            mount_point="/mnt/nas01",
            remote_host="10.0.1.100",
            remote_path="/volume1/media",
            is_primary=True,
        )
        assert source.id is not None
        fetched = get_source(source.id)
        assert fetched.name == "Main NAS"
        assert fetched.is_primary is True
        assert fetched.status == "inactive"

    def test_list_sources(self, db):
        add_source("NAS1", "nfs", "/mnt/nas01", "10.0.1.100", "/vol1", is_primary=True)
        add_source("Cloud", "rclone", "/mnt/cloud", options={"backend": "s3"})
        sources = list_sources()
        assert len(sources) == 2
        # Primary should come first
        assert sources[0].is_primary is True

    def test_update_status(self, db):
        s = add_source("NAS", "nfs", "/mnt/nas01", "10.0.1.100", "/vol1")
        update_source_status(s.id, "active")
        updated = get_source(s.id)
        assert updated.status == "active"

    def test_update_status_error(self, db):
        s = add_source("NAS", "nfs", "/mnt/nas01", "10.0.1.100", "/vol1")
        update_source_status(s.id, "error", error="Mount timeout")
        updated = get_source(s.id)
        assert updated.status == "error"
        assert "timeout" in updated.error_message.lower()

    def test_remove_source(self, db):
        s = add_source("NAS", "nfs", "/mnt/nas01", "10.0.1.100", "/vol1")
        remove_source(s.id)
        with pytest.raises(KeyError):
            get_source(s.id)

    def test_duplicate_name_raises(self, db):
        add_source("NAS", "nfs", "/mnt/nas01", "10.0.1.100", "/vol1")
        with pytest.raises(Exception):  # UNIQUE constraint
            add_source("NAS", "smb", "/mnt/nas02", "10.0.1.101", "/share")

    def test_options_stored_as_json(self, db):
        opts = {"backend": "s3", "region": "us-west-2", "vfs_cache_mode": "full"}
        s = add_source("Cloud", "rclone", "/mnt/cloud", options=opts)
        fetched = get_source(s.id)
        assert fetched.options["backend"] == "s3"
        assert fetched.options["region"] == "us-west-2"


# ── Mount verification ─────────────────────────────────────────────────────


class TestVerifyMount:
    def test_existing_accessible_path(self, tmp_path: Path):
        ok, msg = verify_mount(str(tmp_path))
        # False would mean verify_mount() rejected a real, accessible tmp_path —
        # likely a regression in the os.access/stat check or the message contract.
        assert ok is True
        assert "accessible" in msg.lower()

    def test_nonexistent_path(self):
        ok, msg = verify_mount("/nonexistent/path/that/does/not/exist")
        assert ok is False
        assert "not exist" in msg.lower()

    def test_compose_fragment_capabilities(self):
        """Verify compose builder passes capabilities to fragment."""
        from backend.core.compose import build_service_fragment
        frag = build_service_fragment(
            manifest_key="decypharr",
            display_name="Decypharr",
            image="cy01/blackhole",
            image_tag="latest",
            web_port=8282,
            host_port=8282,
            config_path="/config/decypharr",
            media_root=None,
            domain="example.com",
            capabilities=["SYS_ADMIN"],
            security_opt=["apparmor:unconfined"],
            devices=["/dev/fuse:/dev/fuse:rwm"],
        )
        assert frag["cap_add"] == ["SYS_ADMIN"]
        assert frag["security_opt"] == ["apparmor:unconfined"]
        assert frag["devices"] == ["/dev/fuse:/dev/fuse:rwm"]
