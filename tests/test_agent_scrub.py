"""tests/test_agent_scrub.py — Unit tests for backend.agent.scrub.

Covers:
- Golden redaction for each category (path, container, IPv4, IPv6, username, secret)
- Idempotency: scrub(scrub(x)) == scrub(x) on a mixed-identifier blob
- profile='local' passthrough
- Empty string and None safety
- is_external() against known cloud / local providers
"""
import pytest

from backend.agent.scrub import is_external, scrub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scrub(text: str) -> str:
    return scrub(text, profile="cloud")


# ---------------------------------------------------------------------------
# Individual category tests
# ---------------------------------------------------------------------------

class TestPathRedaction:
    def test_opt_path(self):
        assert _scrub("/opt/mediastack/backend/core/agent.py") == "<PATH>"

    def test_var_lib_path(self):
        assert _scrub("data dir: /var/lib/mediastack/db.sqlite") == "data dir: <PATH>"

    def test_srv_path(self):
        assert _scrub("config at /srv/mediastack/config/app.conf") == "config at <PATH>"

    def test_home_path(self):
        assert _scrub("file /home/stack/.env loaded") == "file <PATH> loaded"

    def test_path_in_sentence(self):
        result = _scrub("Error reading /opt/mediastack/backend/logs/app.log: permission denied")
        assert "<PATH>" in result
        assert "/opt/mediastack" not in result

    def test_multiple_paths(self):
        text = "src=/opt/mediastack/x dst=/var/lib/mediastack/y"
        result = _scrub(text)
        assert "/opt/mediastack" not in result
        assert "/var/lib/mediastack" not in result
        assert result.count("<PATH>") == 2


class TestContainerNameRedaction:
    def test_basic_container(self):
        assert _scrub("mediastack-ollama-1") == "<APP>"

    def test_container_in_sentence(self):
        result = _scrub("container mediastack-plex-2 is unhealthy")
        assert "<APP>" in result
        assert "mediastack-plex-2" not in result

    def test_complex_container_name(self):
        result = _scrub("mediastack-open-webui-1 started")
        assert "<APP>" in result

    def test_non_container_not_redacted(self):
        # A plain word with no trailing digit group should not match
        result = _scrub("normal-service-name running")
        assert result == "normal-service-name running"


class TestIPv4Redaction:
    def test_plain_ipv4(self):
        assert _scrub("192.168.1.100") == "<IP>"

    def test_ipv4_with_port(self):
        assert _scrub("10.0.0.1:8080") == "<IP>"

    def test_ipv4_in_url(self):
        result = _scrub("connecting to http://192.168.1.50:11434/api/tags")
        assert "192.168.1.50" not in result
        assert "<IP>" in result

    def test_localhost_not_redacted(self):
        # 127.0.0.1 is a valid IPv4 and SHOULD be redacted (it's an IP literal)
        result = _scrub("http://127.0.0.1:8080/")
        assert "127.0.0.1" not in result

    def test_multiple_ips(self):
        text = "primary: 10.0.0.1, replica: 10.0.0.2"
        result = _scrub(text)
        assert "10.0.0.1" not in result
        assert "10.0.0.2" not in result
        assert result.count("<IP>") == 2


class TestIPv6Redaction:
    def test_full_ipv6(self):
        result = _scrub("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert "<IP>" in result
        assert "2001:0db8" not in result

    def test_compressed_ipv6(self):
        result = _scrub("addr ::1 loopback")
        assert "::1" not in result
        assert "<IP>" in result

    def test_ipv6_in_sentence(self):
        result = _scrub("IPv6 address fe80::1 assigned")
        assert "fe80::1" not in result


class TestUsernameRedaction:
    def test_bare_mediastack(self):
        assert _scrub("mediastack") == "<USER>"

    def test_bare_stack(self):
        assert _scrub("stack") == "<USER>"

    def test_username_in_sentence(self):
        result = _scrub("running as user mediastack on host")
        assert "mediastack" not in result
        assert "<USER>" in result

    def test_stack_in_sentence(self):
        result = _scrub("user stack has uid 1000")
        assert " stack " not in result


class TestSecretRedaction:
    def test_bearer_token(self):
        result = _scrub("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc123")
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "<SECRET>" in result

    def test_openai_style_key(self):
        result = _scrub("api_key=sk-abcdefghijklmnopqrstuvwxyz123456")
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result
        assert "<SECRET>" in result

    def test_bearer_lowercase(self):
        result = _scrub("bearer eyJhbGciOiJSUzI1NiJ9_longtoken_here_that_is_long")
        assert "<SECRET>" in result

    def test_api_key_colon(self):
        result = _scrub("api_key: supersecretlongapikey1234567890abcdef")
        assert "supersecretlongapikey" not in result

    def test_short_value_not_redacted(self):
        # Tokens under 20 chars should not be redacted as secrets
        result = _scrub("token=short")
        # "short" is only 5 chars — under the threshold
        assert "short" in result


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    MIXED_BLOB = (
        "Error in /opt/mediastack/backend/core/agent.py: "
        "container mediastack-ollama-1 unreachable at 192.168.1.50:11434. "
        "User mediastack running bearer sk-abcdefghijklmnopqrstuvwxyz123456. "
        "IPv6: 2001:db8::1"
    )

    def test_idempotent_on_mixed_blob(self):
        once = scrub(self.MIXED_BLOB)
        twice = scrub(once)
        assert once == twice, f"Not idempotent!\nOnce:  {once!r}\nTwice: {twice!r}"

    def test_idempotent_plain_text(self):
        text = "no identifiers here at all"
        assert scrub(text) == scrub(scrub(text))

    def test_idempotent_placeholder_not_re_matched(self):
        # Placeholders themselves must survive a second pass unchanged
        for placeholder in ("<PATH>", "<APP>", "<IP>", "<USER>", "<SECRET>"):
            assert scrub(placeholder) == placeholder


# ---------------------------------------------------------------------------
# profile='local' passthrough
# ---------------------------------------------------------------------------

class TestLocalProfile:
    def test_local_returns_unchanged(self):
        text = (
            "/opt/mediastack/backend user mediastack 192.168.1.1 "
            "mediastack-ollama-1 bearer sk-secrettoken12345678901234567890"
        )
        assert scrub(text, profile="local") == text

    def test_local_none_safety(self):
        # Even with profile=local, None should not raise; but spec says local returns
        # text unchanged — None is treated consistently
        assert scrub(None, profile="local") == ""  # None-safe regardless of profile

    def test_cloud_default(self):
        text = "/opt/mediastack/x"
        # Default profile is cloud
        assert scrub(text) != text
        assert "<PATH>" in scrub(text)


# ---------------------------------------------------------------------------
# Edge cases: empty / None safety
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self):
        assert scrub("") == ""

    def test_none_returns_empty(self):
        assert scrub(None) == ""  # type: ignore[arg-type]

    def test_whitespace_only(self):
        assert scrub("   ") == "   "

    def test_no_identifiers(self):
        text = "Everything is fine, no sensitive data here."
        assert scrub(text) == text


# ---------------------------------------------------------------------------
# is_external()
# ---------------------------------------------------------------------------

class TestIsExternal:
    @pytest.mark.parametrize("provider", [
        "groq", "cerebras", "openrouter", "mistral", "cohere",
        "google", "anthropic", "openai", "nim", "gai",
    ])
    def test_cloud_providers(self, provider: str):
        assert is_external(provider) is True

    @pytest.mark.parametrize("provider", [
        "ollama", "llamacpp", "shimmy", "localai", "",
    ])
    def test_local_providers(self, provider: str):
        assert is_external(provider) is False

    def test_case_insensitive(self):
        assert is_external("OpenAI") is True
        assert is_external("GROQ") is True

    def test_with_whitespace(self):
        assert is_external("  anthropic  ") is True

    def test_unknown_provider_is_not_external(self):
        assert is_external("my-custom-llm") is False
