"""tests/test_agent_scrub_integration.py — Integration tests for scrub() wiring
in backend.health.checker._dispatch_llm_call.

Verifies (ADR-0018 / S-61 Stream C):
  - Cloud provider path: outbound prompt is scrubbed (no raw paths / IPs).
  - Local provider path: outbound prompt is the raw prompt unchanged.

Mocking strategy mirrors test_llm_diagnose_refactor.py:
  - Fresh module-scoped StateDB via init_db().
  - httpx.AsyncClient.post patched with AsyncMock to capture the outbound payload
    without any real network calls.
  - Provider config driven by setting up provider / cloud_providers args directly
    (matches _dispatch_llm_call's signature — no need to go through StateDB for
    these unit-level integration tests).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.state import StateDB, init_db  # noqa: E402
from backend.health.checker import _dispatch_llm_call  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="module")
def _fresh_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Schema-migrated DB for the whole module."""
    db_path = tmp_path_factory.mktemp("scrub_integration") / "state.db"
    init_db(db_path)
    return db_path


@pytest.fixture(autouse=True)
def _clean_llm_config() -> None:
    """Reset llm_agent_config between tests."""
    try:
        with StateDB() as db:
            db.set_setting("llm_agent_config", "")
    except Exception:
        pass
    yield
    try:
        with StateDB() as db:
            db.set_setting("llm_agent_config", "")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENSITIVE_PROMPT = (
    "Error in /opt/mediastack/backend/core/agent.py: "
    "container mediastack-ollama-1 unreachable at 192.168.1.50:11434. "
    "Running as user mediastack."
)

_FAKE_CLOUD_BODY = json.dumps({
    "choices": [{"message": {"content": json.dumps({
        "action": "manual", "confidence": 0.8,
        "problem": "x", "cause": "y", "suggested_fix": "z",
    })}}]
})


def _mock_response(body: str) -> MagicMock:
    """Fake httpx Response that raise_for_status() is a no-op on."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json.loads(body)
    return resp


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _run_dispatch(prompt: str, provider: str, cloud_providers: set[str],
                  fake_response: str, allow_raw: bool = False,
                  ollama_url: str = "http://ignored:11434") -> list[dict]:
    """Helper: patch httpx.AsyncClient.post, call _dispatch_llm_call, return captured payloads."""
    captured: list[dict] = []

    mock_post = AsyncMock(side_effect=lambda url, **kwargs: (
        captured.append(kwargs.get("json", {})) or _mock_response(fake_response)
    ))

    import httpx

    async def _inner():
        with patch.object(httpx.AsyncClient, "post", mock_post):
            client = httpx.AsyncClient()
            return await _dispatch_llm_call(
                client, prompt, ollama_url,
                provider, "fake-api-key", "test-model",
                cloud_providers, allow_raw=allow_raw,
            )

    _run(_inner())
    return captured


# ---------------------------------------------------------------------------
# Cloud provider: scrub() must run before the HTTP call
# ---------------------------------------------------------------------------

class TestCloudProviderScrubbed:
    """Configure a CLOUD provider (groq) and assert the outbound payload
    contains no raw paths, IPs, or internal usernames."""

    @pytest.fixture(autouse=True)
    def _providers(self):
        from backend.core.cloud_llm import PROVIDERS
        self.cloud_providers = set(PROVIDERS.keys())

    def test_path_not_in_outbound_payload(self) -> None:
        """Raw /opt/mediastack path must be absent from the outbound request."""
        captured = _run_dispatch(
            _SENSITIVE_PROMPT, "groq", self.cloud_providers, _FAKE_CLOUD_BODY,
        )
        assert captured, "No HTTP call was made"
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert "/opt/mediastack" not in content, (
            f"Raw path leaked to cloud provider! content={content!r}"
        )

    def test_ip_not_in_outbound_payload(self) -> None:
        """Raw IP address must be absent from the outbound request."""
        captured = _run_dispatch(
            _SENSITIVE_PROMPT, "groq", self.cloud_providers, _FAKE_CLOUD_BODY,
        )
        assert captured
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert "192.168.1.50" not in content, (
            f"Raw IP leaked to cloud provider! content={content!r}"
        )

    def test_scrub_placeholders_present_in_outbound_payload(self) -> None:
        """Scrub placeholders must appear, confirming scrub() ran."""
        captured = _run_dispatch(
            _SENSITIVE_PROMPT, "groq", self.cloud_providers, _FAKE_CLOUD_BODY,
        )
        assert captured
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert any(ph in content for ph in ("<PATH>", "<IP>", "<APP>", "<USER>")), (
            f"No scrub placeholders found in cloud payload: content={content!r}"
        )

    def test_allow_raw_bypasses_scrub(self) -> None:
        """allow_raw=True must send the raw prompt without scrubbing."""
        captured = _run_dispatch(
            _SENSITIVE_PROMPT, "groq", self.cloud_providers, _FAKE_CLOUD_BODY,
            allow_raw=True,
        )
        assert captured
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert "/opt/mediastack" in content, (
            f"allow_raw=True should preserve raw path; content={content!r}"
        )
        assert "192.168.1.50" in content, (
            f"allow_raw=True should preserve raw IP; content={content!r}"
        )


# ---------------------------------------------------------------------------
# Local provider: scrub() must NOT run (passthrough)
# ---------------------------------------------------------------------------

class TestLocalProviderPassthrough:
    """Configure a LOCAL provider (llamacpp) and assert the outbound payload
    is the raw prompt unchanged — scrub() must not alter local calls."""

    @pytest.fixture(autouse=True)
    def _providers(self):
        from backend.core.cloud_llm import PROVIDERS
        self.cloud_providers = set(PROVIDERS.keys())

    def test_raw_path_preserved_for_local_provider(self) -> None:
        """Local provider must receive the raw prompt with paths intact."""
        captured = _run_dispatch(
            _SENSITIVE_PROMPT, "llamacpp", self.cloud_providers, _FAKE_CLOUD_BODY,
            ollama_url="http://localhost:8080",
        )
        assert captured, "No HTTP call was made"
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert "/opt/mediastack" in content, (
            f"Local provider should receive raw prompt; content={content!r}"
        )
        assert "192.168.1.50" in content, (
            f"Local provider should receive raw IP; content={content!r}"
        )

    def test_no_scrub_placeholders_for_local_provider(self) -> None:
        """No scrub placeholders must appear in a local provider's payload."""
        captured = _run_dispatch(
            _SENSITIVE_PROMPT, "llamacpp", self.cloud_providers, _FAKE_CLOUD_BODY,
            ollama_url="http://localhost:8080",
        )
        assert captured
        content = captured[0].get("messages", [{}])[0].get("content", "")
        for ph in ("<PATH>", "<APP>", "<IP>", "<USER>"):
            assert ph not in content, (
                f"Scrub placeholder {ph!r} found in local provider payload — "
                f"scrub() must not run for local providers; content={content!r}"
            )

    def test_ollama_provider_passthrough(self) -> None:
        """ollama (default local) must also receive raw prompt unchanged."""
        ollama_response = json.dumps({"response": "ok"})
        captured = _run_dispatch(
            _SENSITIVE_PROMPT, "ollama", self.cloud_providers, ollama_response,
            ollama_url="http://ollama:11434",
        )
        assert captured, "No HTTP call was made"
        # Ollama uses 'prompt' key not 'messages'
        content = captured[0].get("prompt", "")
        assert "/opt/mediastack" in content, (
            f"ollama provider should receive raw prompt; content={content!r}"
        )
        assert "192.168.1.50" in content, (
            f"ollama provider should receive raw IP; content={content!r}"
        )
