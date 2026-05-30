"""tests/test_reality_view.py

Unit tests for the SLOP Agent RealityView (backend/core/reality_view.py).

GROUND data — observed about the running instance. These tests assert the view
is well-formed and self-consistent and that env-source provenance follows the
core/config.py loading order (override=False ⇒ real process env wins over .env).

Everything runs on tmp_path / injected fakes: no real host access, no real .env
writes, no os.environ mutation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.core import reality_view as rv

PINNED_KEYS = {
    "schema_version",
    "observed_at",
    "bound_port",
    "install_dir_is_git",
    "install_dir_owner",
    "env_sources",
}
PINNED_SOURCE_VALUES = {"environ", "dotenv", "unset"}


# ── classify_env_source (pure provenance logic) ──────────────────────────────


def test_classify_unset_when_absent_from_environ():
    assert rv.classify_env_source("FOO", {}, {"FOO": "x"}) == "unset"
    assert rv.classify_env_source("FOO", {}, {}) == "unset"


def test_classify_dotenv_when_value_matches_file():
    # In environ AND .env declares the same value ⇒ the file's value is effective.
    assert rv.classify_env_source("FOO", {"FOO": "bar"}, {"FOO": "bar"}) == "dotenv"


def test_classify_environ_when_value_differs_from_file():
    # override=False ⇒ a pre-existing process value won over the .env value.
    assert rv.classify_env_source("FOO", {"FOO": "real"}, {"FOO": "file"}) == "environ"


def test_classify_environ_when_not_in_dotenv():
    # Present in process env, file never mentioned it ⇒ environ.
    assert rv.classify_env_source("FOO", {"FOO": "real"}, {}) == "environ"


def test_observe_env_sources_maps_each_name():
    out = rv.observe_env_sources(
        ["A", "B", "C"],
        {"A": "1", "B": "2"},
        {"A": "1", "B": "9"},
    )
    assert out == {"A": "dotenv", "B": "environ", "C": "unset"}
    assert set(out.values()) <= PINNED_SOURCE_VALUES


# ── install dir observers (tmp_path / fakes) ─────────────────────────────────


def test_install_dir_is_git_true_with_dir(tmp_path):
    (tmp_path / ".git").mkdir()
    assert rv.observe_install_dir_is_git(tmp_path) is True


def test_install_dir_is_git_true_with_file(tmp_path):
    # worktrees record .git as a gitdir-pointer file
    (tmp_path / ".git").write_text("gitdir: /somewhere\n")
    assert rv.observe_install_dir_is_git(tmp_path) is True


def test_install_dir_is_git_false_when_absent(tmp_path):
    assert rv.observe_install_dir_is_git(tmp_path) is False


class _FakeStat:
    def __init__(self, uid):
        self.st_uid = uid


class _FakePwEntry:
    def __init__(self, name):
        self.pw_name = name


def test_install_dir_owner_resolves_name(tmp_path):
    owner = rv.observe_install_dir_owner(
        tmp_path,
        stat_fn=lambda p: _FakeStat(1234),
        getpwuid_fn=lambda uid: _FakePwEntry("mediastack") if uid == 1234 else None,
    )
    assert owner == "mediastack"


def test_install_dir_owner_falls_back_to_uid_on_lookup_failure(tmp_path):
    def _boom(uid):
        raise KeyError(uid)

    owner = rv.observe_install_dir_owner(
        tmp_path, stat_fn=lambda p: _FakeStat(4242), getpwuid_fn=_boom
    )
    assert owner == "4242"


def test_install_dir_owner_unknown_on_stat_failure(tmp_path):
    def _boom(p):
        raise OSError("nope")

    owner = rv.observe_install_dir_owner(tmp_path, stat_fn=_boom)
    assert owner == "unknown"


# ── full assembly (pure over injected fakes) ─────────────────────────────────


def _build(tmp_path, **over):
    kwargs = dict(
        bound_port=8080,
        install_dir=tmp_path,
        environ={"PUID": "1000", "MS_BIND_PORT": "9999"},
        dotenv_values={"PUID": "1000"},
        var_names=["PUID", "MS_BIND_PORT", "DOMAIN"],
        now=datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc),
        stat_fn=lambda p: _FakeStat(1000),
        getpwuid_fn=lambda uid: _FakePwEntry("mediastack"),
    )
    kwargs.update(over)
    return rv.build_reality_view(**kwargs)


def test_view_has_exactly_pinned_keys(tmp_path):
    view = _build(tmp_path)
    assert set(view.keys()) == PINNED_KEYS


def test_view_schema_version_and_types(tmp_path):
    view = _build(tmp_path)
    assert view["schema_version"] == 1
    assert isinstance(view["bound_port"], int)
    assert isinstance(view["install_dir_is_git"], bool)
    assert isinstance(view["install_dir_owner"], str)
    assert isinstance(view["env_sources"], dict)


def test_view_observed_at_is_iso8601(tmp_path):
    view = _build(tmp_path)
    # round-trips through fromisoformat ⇒ well-formed
    datetime.fromisoformat(view["observed_at"])


def test_view_self_consistent_env_sources(tmp_path):
    (tmp_path / ".git").mkdir()
    view = _build(tmp_path)
    assert view["bound_port"] == 8080
    assert view["install_dir_is_git"] is True
    assert view["install_dir_owner"] == "mediastack"
    # PUID matches .env ⇒ dotenv; MS_BIND_PORT only in environ ⇒ environ;
    # DOMAIN in neither ⇒ unset.
    assert view["env_sources"] == {
        "PUID": "dotenv",
        "MS_BIND_PORT": "environ",
        "DOMAIN": "unset",
    }
    assert set(view["env_sources"].values()) <= PINNED_SOURCE_VALUES


def test_view_value_vocabulary_is_pinned(tmp_path):
    view = _build(tmp_path)
    for v in view["env_sources"].values():
        assert v in PINNED_SOURCE_VALUES


def test_default_var_names_include_managed_and_operator_vars():
    names = rv.reality_var_names()
    # _SLOP_MANAGED_VARS members and deploy-relevant operator vars present.
    assert "PUID" in names
    assert "DOMAIN" in names
    assert "MS_TRUSTED_HOSTS" in names
    assert "MS_BIND_PORT" in names
    assert names == sorted(names)  # deterministic order


# ── live-assembly fallback never raises / well-formed ────────────────────────


def test_assemble_live_reality_view_is_well_formed():
    # Touches the real config singleton + os.environ READ-ONLY; asserts shape
    # only (no host-specific values), and never writes a .env.
    view = rv.assemble_live_reality_view()
    assert set(view.keys()) == PINNED_KEYS
    assert view["schema_version"] == 1
    assert isinstance(view["bound_port"], int)
    assert isinstance(view["env_sources"], dict)
    assert set(view["env_sources"].values()) <= PINNED_SOURCE_VALUES


def test_get_reality_view_reexport_matches_schema():
    from backend.core.agent import get_reality_view

    view = get_reality_view()
    assert set(view.keys()) == PINNED_KEYS
