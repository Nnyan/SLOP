"""S-74 Stream C — operator-env mechanism test.

Decision (a): the install-dir ``.env`` is authoritative for the ``os.environ``-read
operator settings (``MS_TRUSTED_HOSTS`` / ``DOMAIN``). ``backend/core/config.py``
loads ``.env`` into ``os.environ`` at import (``override=False``) so editing ``.env``
takes effect even when the systemd unit's ``EnvironmentFile=`` is stale/unreloaded —
while a value already in the real process environment (systemd ``Environment=`` /
shell export) still wins.

These tests use a tmp ``.env`` under ``tmp_path`` and monkeypatch ``os.environ``;
they NEVER touch a real install.
"""
from __future__ import annotations

import os

from backend.core import config as config_module


def _write_env(tmp_path, body: str):
    p = tmp_path / ".env"
    p.write_text(body, encoding="utf-8")
    return p


def test_dotenv_populates_unset_key(tmp_path, monkeypatch):
    """A key only present in .env is loaded into os.environ (documented behaviour)."""
    env = _write_env(tmp_path, "MS_TRUSTED_HOSTS=host.example.com,foo.local\n")
    monkeypatch.delenv("MS_TRUSTED_HOSTS", raising=False)

    applied = config_module.load_dotenv(env)

    assert applied >= 1
    assert os.environ["MS_TRUSTED_HOSTS"] == "host.example.com,foo.local"


def test_real_env_wins_over_dotenv(tmp_path, monkeypatch):
    """override=False: a value already in the real environment beats .env.

    This guarantees systemd Environment= / an operator shell export still win,
    so .env is a fallback layer, never a clobber of the live process env.
    """
    env = _write_env(tmp_path, "MS_TRUSTED_HOSTS=from-dotenv.example.com\n")
    monkeypatch.setenv("MS_TRUSTED_HOSTS", "from-real-env.example.com")

    applied = config_module.load_dotenv(env)

    assert applied == 0
    assert os.environ["MS_TRUSTED_HOSTS"] == "from-real-env.example.com"


def test_override_true_clobbers(tmp_path, monkeypatch):
    """override=True is opt-in and does replace the live value (not used at startup)."""
    env = _write_env(tmp_path, "DOMAIN=dotenv.example.com\n")
    monkeypatch.setenv("DOMAIN", "real.example.com")

    config_module.load_dotenv(env, override=True)

    assert os.environ["DOMAIN"] == "dotenv.example.com"


def test_parser_handles_comments_export_and_quotes(tmp_path, monkeypatch):
    body = (
        "# a comment line\n"
        "\n"
        "export DOMAIN=\"quoted.example.com\"\n"
        "MS_TRUSTED_HOSTS='single.example.com'\n"
        "MS_PORT=9090\n"
    )
    env = _write_env(tmp_path, body)
    for k in ("DOMAIN", "MS_TRUSTED_HOSTS", "MS_PORT"):
        monkeypatch.delenv(k, raising=False)

    config_module.load_dotenv(env)

    assert os.environ["DOMAIN"] == "quoted.example.com"
    assert os.environ["MS_TRUSTED_HOSTS"] == "single.example.com"
    assert os.environ["MS_PORT"] == "9090"


def test_missing_env_file_is_noop(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    assert config_module.load_dotenv(missing) == 0


def test_ensure_env_loaded_runs_once(tmp_path, monkeypatch):
    """ensure_env_loaded is idempotent — second call is a no-op once flagged."""
    env = _write_env(tmp_path, "MS_TRUSTED_HOSTS=once.example.com\n")
    monkeypatch.setattr(config_module, "_resolve_env_file", lambda: env)
    monkeypatch.setattr(config_module, "_loaded_env_done", False, raising=False)
    monkeypatch.delenv("MS_TRUSTED_HOSTS", raising=False)

    config_module.ensure_env_loaded()
    assert os.environ["MS_TRUSTED_HOSTS"] == "once.example.com"

    # Change the live value; a second ensure_env_loaded must NOT reload/clobber.
    monkeypatch.setenv("MS_TRUSTED_HOSTS", "changed.example.com")
    config_module.ensure_env_loaded()
    assert os.environ["MS_TRUSTED_HOSTS"] == "changed.example.com"
