"""tests/test_models_ssrf.py

SSRF test coverage for _validate_gguf_url() (S-23-SEC-B, H-10).

The guard was added in commit 5d462d7 and is called in three GGUF route
handlers (preflight + two download routes).  These tests exercise the accept
and reject cases directly on the validator function.

Scope: literal-IP checks and scheme enforcement only.
DNS rebinding / hostname resolution is out of scope (documented below).
"""
import pytest

from backend.api.models import _validate_gguf_url


# ---------------------------------------------------------------------------
# Accept cases
# ---------------------------------------------------------------------------


def test_accept_https_huggingface_url():
    """HTTPS HuggingFace URL is accepted and returned unchanged."""
    url = "https://huggingface.co/user/repo/model.gguf"
    result = _validate_gguf_url(url)
    assert result == url


def test_accept_hf_shorthand():
    """hf:// shorthand is accepted — resolution is deferred to resolve_gguf_url()."""
    url = "hf://user/repo/model.gguf"
    result = _validate_gguf_url(url)
    assert result == url


# ---------------------------------------------------------------------------
# Reject cases
# ---------------------------------------------------------------------------


def test_reject_http_url():
    """Plain http:// URL is rejected (scheme must be https)."""
    with pytest.raises(ValueError, match="https://"):
        _validate_gguf_url("http://example.com/model.gguf")


def test_reject_file_url():
    """file:// URL is rejected — prevents local filesystem read via urlopen."""
    with pytest.raises(ValueError):
        _validate_gguf_url("file:///etc/passwd")


def test_reject_private_ip_192_168():
    """HTTPS URL targeting 192.168.x.x private range is rejected (H-10)."""
    with pytest.raises(ValueError, match="private or reserved"):
        _validate_gguf_url("https://192.168.1.1/model.gguf")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known gap: 'localhost' is treated as a DNS name by ipaddress.ip_address(), "
        "so the literal-IP block does not fire and the URL passes validation. "
        "[BR: SSRF] [WAVE-DEFER: owned by S-23-BR-TESTS-B] "
        "Needs an explicit hostname blocklist (localhost, ::1, etc.) in _validate_gguf_url."
    ),
)
def test_reject_localhost():
    """https://localhost should be rejected — SSRF risk via loopback.

    CURRENT STATUS: xfail — localhost is not a bare IP literal, so the guard
    silently allows it through.  Fix tracked in TODO.md as
    [BR: SSRF] _validate_gguf_url allows hostname 'localhost' as DNS bypass.
    """
    with pytest.raises(ValueError):
        _validate_gguf_url("https://localhost/model.gguf")


def test_reject_10x_range():
    """HTTPS URL targeting 10.x.x.x private range is rejected (H-10)."""
    with pytest.raises(ValueError, match="private or reserved"):
        _validate_gguf_url("https://10.0.0.1/model.gguf")


def test_reject_empty_string():
    """Empty string is rejected — empty scheme is not https."""
    with pytest.raises(ValueError):
        _validate_gguf_url("")
