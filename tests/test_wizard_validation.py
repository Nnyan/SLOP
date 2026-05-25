"""tests/test_wizard_validation.py — Regression guards for WizardRequest validators
and step_write_env / _write_env_file newline-stripping.

Added in S-23-SEC-TESTS (Wave 2B) to cover security fixes from:
  - S-23-SEC-A  (d0eb43c): eab_kid/eab_hmac charset, acme_email, ntfy_url, cert_resolver, C-4 newline-strip
  - S-23-BR-SEC (af68c8b): domain newline-inject, network_name allowlist, lan_subnet CIDR
"""
from __future__ import annotations

import os
import pytest
from pydantic import ValidationError

from backend.api.platform import WizardRequest

# ---------------------------------------------------------------------------
# Minimal valid base kwargs — only `domain` is required; everything else has
# a safe default that passes all validators.
# ---------------------------------------------------------------------------
BASE: dict = dict(domain="example.com")


# ---------------------------------------------------------------------------
# Helper: build a WizardRequest with one field overridden
# ---------------------------------------------------------------------------
def _make(**overrides):
    return WizardRequest(**{**BASE, **overrides})


# ===========================================================================
# WizardRequest.domain
# ===========================================================================

class TestDomainValidator:
    """domain_must_have_dot — strip+lower first, then reject newlines and dotless values."""

    def test_valid_simple(self):
        req = _make(domain="example.com")
        assert req.domain == "example.com"

    def test_valid_subdomain(self):
        req = _make(domain="sub.example.co.uk")
        assert "." in req.domain

    def test_strips_whitespace_and_lowercases(self):
        req = _make(domain="  EXAMPLE.COM  ")
        assert req.domain == "example.com"

    def test_rejects_no_dot(self):
        with pytest.raises(ValidationError):
            _make(domain="localhost")

    def test_rejects_embedded_newline(self):
        with pytest.raises(ValidationError):
            _make(domain="evil.com\nINJECT=1")

    def test_rejects_embedded_carriage_return(self):
        with pytest.raises(ValidationError):
            _make(domain="evil.com\rINJECT=1")


# ===========================================================================
# WizardRequest.eab_kid / eab_hmac (shared validator no_injection_chars)
# ===========================================================================

class TestEabKid:
    """eab_kid — base64url chars only (A-Za-z0-9 - _ =); empty string is OK."""

    def test_valid_base64url(self):
        _make(eab_kid="ABCdef-_123==")

    def test_empty_allowed(self):
        _make(eab_kid="")

    @pytest.mark.parametrize("bad", [
        "abc\ndef",    # newline
        "abc:def",     # colon (YAML injection)
        "abc def",     # space
        "abc+def",     # plus (not base64url)
        "abc/def",     # slash (not base64url)
        "abc\x00def",  # null byte
    ])
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            _make(eab_kid=bad)


class TestEabHmac:
    """eab_hmac shares the same validator as eab_kid."""

    def test_valid(self):
        _make(eab_hmac="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_==")

    def test_empty_allowed(self):
        _make(eab_hmac="")

    @pytest.mark.parametrize("bad", [
        "abc\ndef",
        "abc:def",
        "abc def",
    ])
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            _make(eab_hmac=bad)


# ===========================================================================
# WizardRequest.acme_email
# ===========================================================================

class TestAcmeEmail:
    """valid_email — basic email regex; empty string is accepted (defaults to admin@domain)."""

    def test_valid(self):
        _make(acme_email="user@example.com")

    def test_empty_allowed(self):
        _make(acme_email="")

    def test_strips_whitespace(self):
        req = _make(acme_email="  user@example.com  ")
        assert req.acme_email == "user@example.com"

    @pytest.mark.parametrize("bad", [
        "notanemail",           # no @
        "noatsign.example.com", # no @
        "user@nodot",           # no dot after @
        "user @example.com",    # space in local part
    ])
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            _make(acme_email=bad)


# ===========================================================================
# WizardRequest.ntfy_url
# ===========================================================================

class TestNtfyUrl:
    """valid_url — must start with http:// or https://; empty is OK (default set)."""

    def test_valid_http(self):
        _make(ntfy_url="http://ntfy.example.com")

    def test_valid_https(self):
        _make(ntfy_url="https://ntfy.example.com/topic")

    def test_default_passes(self):
        _make(ntfy_url="http://ntfy:80")

    def test_empty_allowed(self):
        # empty string passes (field has a default; validator only rejects non-empty bad values)
        _make(ntfy_url="")

    @pytest.mark.parametrize("bad", [
        "ftp://ntfy.example.com",   # wrong scheme
        "//ntfy.example.com",       # scheme-relative
        "ntfy.example.com",         # no scheme
        "http://ntfy.com\nINJECT=1",  # newline inject
        "http://ntfy.com\rINJECT=1",  # carriage-return inject
        "http://ntfy.com evil",     # space
    ])
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            _make(ntfy_url=bad)


# ===========================================================================
# WizardRequest.cert_resolver
# ===========================================================================

class TestCertResolver:
    """validate_cert_resolver — allowlist: letsencrypt, zerossl, buypass, staging."""

    @pytest.mark.parametrize("valid", ["letsencrypt", "zerossl", "buypass", "staging"])
    def test_valid_values(self, valid):
        _make(cert_resolver=valid)

    def test_empty_allowed(self):
        # empty string is skipped by the validator (not in _valid but v is falsy)
        _make(cert_resolver="")

    @pytest.mark.parametrize("bad", [
        "digicert",
        "lets-encrypt",
        "LETSENCRYPT",
        "letsencrypt\n",
        "letsencrypt staging",  # space-separated — not a valid single value
    ])
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            _make(cert_resolver=bad)


# ===========================================================================
# WizardRequest.network_name
# ===========================================================================

class TestNetworkName:
    """network_name_safe — alphanumeric + hyphen + underscore only; non-empty."""

    @pytest.mark.parametrize("valid", [
        "mediastack",
        "media-stack",
        "media_stack",
        "MyNetwork123",
        "a",
    ])
    def test_valid(self, valid):
        _make(network_name=valid)

    def test_strips_surrounding_whitespace(self):
        req = _make(network_name="  mediastack  ")
        assert req.network_name == "mediastack"

    @pytest.mark.parametrize("bad", [
        "",                 # empty after strip
        "my network",       # space
        "my.network",       # dot
        "net\nwork",        # newline
        "net:work",         # colon
        "net/work",         # slash
    ])
    def test_invalid(self, bad):
        with pytest.raises(ValidationError):
            _make(network_name=bad)


# ===========================================================================
# _validate_lan_subnet  (backend/infra/providers/auth_tinyauth.py)
# ===========================================================================

class TestValidateLanSubnet:
    """_validate_lan_subnet — valid CIDR or empty string; raises ValueError for garbage."""

    def setup_method(self):
        from backend.infra.providers.auth_tinyauth import _validate_lan_subnet
        self._fn = _validate_lan_subnet

    def test_empty_string_accepted(self):
        assert self._fn("") == ""

    def test_whitespace_only_accepted(self):
        assert self._fn("   ") == ""

    @pytest.mark.parametrize("cidr", [
        "192.168.1.0/24",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.100.1/32",
        "192.168.1.5/24",   # host bits set — strict=False should accept
    ])
    def test_valid_cidr(self, cidr):
        result = self._fn(cidr)
        assert result == cidr

    @pytest.mark.parametrize("bad", [
        "not-a-cidr",
        # bare IP without prefix — ip_network(strict=False) treats it as /32, so it IS valid;
        # only clearly-invalid inputs raise
        "192.168.1.0/33",     # prefix length too large (> 32 for IPv4)
        "999.999.999.999/24", # invalid IP octets
        "192.168.1.0/24\nINJECT=1",  # newline inject — extra chars break parsing
    ])
    def test_invalid_raises(self, bad):
        with pytest.raises(ValueError):
            self._fn(bad)


# ===========================================================================
# step_write_env — C-4 newline-stripping (backend/platform/wizard.py)
# ===========================================================================

class TestStepWriteEnvNewlineStrip:
    """A value containing \\n must NOT inject an extra KEY=VALUE line in .env."""

    def test_newline_in_domain_is_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MS_ENV_FILE", str(tmp_path / ".env"))
        from backend.platform.wizard import step_write_env, WizardInput
        inp = WizardInput(
            domain="evil.com\nINJECT=injected",
            config_root="/tmp/cfg",
            media_root="/tmp/media",
            puid=1000,
            pgid=1000,
            timezone="UTC",
        )
        step_write_env(inp)
        # The newline is stripped, so INJECT must NOT appear as its own key=value line.
        env_text = (tmp_path / ".env").read_text() if (tmp_path / ".env").exists() else ""
        lines = env_text.splitlines()
        assert not any(line.startswith("INJECT=") for line in lines), (
            "Newline in domain value must not inject a standalone INJECT= line in .env"
        )

    def test_newline_in_secret_value_is_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MS_ENV_FILE", str(tmp_path / ".env"))
        from backend.platform.wizard import step_write_env, WizardInput
        inp = WizardInput(
            domain="example.com",
            config_root="/tmp/cfg",
            media_root="/tmp/media",
            puid=1000,
            pgid=1000,
            timezone="UTC",
            secrets={"CF_DNS_API_TOKEN": "tok\nINJECT=bad"},
        )
        step_write_env(inp)
        env_text = (tmp_path / ".env").read_text() if (tmp_path / ".env").exists() else ""
        lines = env_text.splitlines()
        assert not any(line.startswith("INJECT=") for line in lines), (
            "Newline in secret value must not inject a standalone INJECT= line in .env"
        )

    def test_carriage_return_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MS_ENV_FILE", str(tmp_path / ".env"))
        from backend.platform.wizard import step_write_env, WizardInput
        inp = WizardInput(
            domain="example.com",
            config_root="/tmp/cfg",
            media_root="/tmp/media",
            puid=1000,
            pgid=1000,
            timezone="UTC",
            secrets={"MY_KEY": "value\rwith\rcr"},
        )
        step_write_env(inp)
        env_text = (tmp_path / ".env").read_text() if (tmp_path / ".env").exists() else ""
        assert "\r" not in env_text, "Carriage returns must be stripped from .env values"


# ===========================================================================
# _write_env_file — C-4 newline-stripping (backend/api/settings.py)
# ===========================================================================

class TestWriteEnvFileNewlineStrip:
    """_write_env_file must strip \\n/\\r from updated values (env-injection guard)."""

    def test_newline_in_value_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MS_ENV_FILE", str(tmp_path / ".env"))
        (tmp_path / ".env").write_text("EXISTING=original\n")
        from backend.api.settings import _write_env_file
        _write_env_file({"EXISTING": "new\nINJECT=evil"})
        content = (tmp_path / ".env").read_text()
        # The newline is stripped; INJECT must not appear as its own key line
        lines = content.splitlines()
        assert not any(line.startswith("INJECT=") for line in lines), (
            "_write_env_file must strip newlines to prevent .env injection"
        )

    def test_carriage_return_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MS_ENV_FILE", str(tmp_path / ".env"))
        (tmp_path / ".env").write_text("KEY=original\n")
        from backend.api.settings import _write_env_file
        _write_env_file({"KEY": "val\rwith\rcr"})
        content = (tmp_path / ".env").read_text()
        assert "\r" not in content

    def test_new_key_newline_stripped(self, tmp_path, monkeypatch):
        """Keys not already in .env are appended — newlines must still be stripped."""
        monkeypatch.setenv("MS_ENV_FILE", str(tmp_path / ".env"))
        (tmp_path / ".env").write_text("")
        from backend.api.settings import _write_env_file
        _write_env_file({"NEW_KEY": "value\nINJECT=evil"})
        content = (tmp_path / ".env").read_text()
        lines = content.splitlines()
        assert not any(line.startswith("INJECT=") for line in lines), (
            "_write_env_file must not allow newline-injected keys when appending new entries"
        )
