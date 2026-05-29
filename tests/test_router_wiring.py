"""tests/test_router_wiring.py — Integration tests for route_and_dispatch wiring.

Covers (S-63 Stream C):
  1. Fallback: first chain provider raises → second provider is used → success.
  2. Scrub preserved: a cloud provider in the chain → outbound payload is
     scrubbed (mock httpx at transport boundary; assert identifiers are
     redacted in the actual outbound request).
  3. Empty chain → legacy single-provider path is taken (no regression).
  4. A router_decisions row IS persisted with the correct chosen_provider +
     outcome (use a temp StateDB; assert the row matches).

Mocking strategy:
  - httpx.AsyncClient.post is patched with AsyncMock so no real network calls
    are made, but the real _dispatch_llm_call path (with scrub()) is exercised.
  - route_and_dispatch is called directly — the real function is not mocked.
  - Router selection is controlled by patching
      backend.agent.router.registry.available_providers  (the canonical source)
      backend.agent.router.selector.select               (the canonical source)
    so the deferred ``from ... import`` inside dispatch.py picks up the mock.
  - StateDB is pointed at a temp file via monkeypatch so rows persist only for
    the test's lifetime.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.router.dispatch import route_and_dispatch
from backend.agent.router.types import RouteDecision, Tier
from backend.core.state import init_db, StateDB


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

# A prompt containing SLOP-internal identifiers that must be scrubbed for
# any cloud-provider outbound call.
_SENSITIVE_PROMPT = (
    "Error in /opt/mediastack/backend/core/agent.py: "
    "container mediastack-ollama-1 unreachable at 192.168.1.50:11434. "
    "Running as user mediastack."
)

_PLAIN_PROMPT = "A short, simple health question with no PII."


def _cloud_chat_response(content: str) -> dict:
    """Build an OpenAI-style /chat/completions JSON body."""
    return {
        "choices": [{"message": {"content": content}}],
    }


def _mock_response(body: dict) -> MagicMock:
    """Fake httpx.Response that raise_for_status() is a no-op on."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


def _run(coro):
    """Run an async coroutine synchronously on a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _two_entry_chain(tier: Tier = Tier.SIMPLE, providers=None) -> RouteDecision:
    """Return a RouteDecision with a two-entry cloud chain."""
    return RouteDecision(
        tier=tier,
        chain=providers or ["groq", "mistral"],
        reason="test: fixed two-provider chain",
    )


def _single_cloud_chain(provider: str = "groq", tier: Tier = Tier.SIMPLE) -> RouteDecision:
    return RouteDecision(
        tier=tier,
        chain=[provider],
        reason=f"test: single {provider} chain",
    )


def _empty_chain(tier: Tier = Tier.SIMPLE) -> RouteDecision:
    return RouteDecision(
        tier=tier,
        chain=[],
        reason="test: no providers available",
    )


# Patch targets: dispatch.py uses deferred ``from X import Y`` inside the
# function body, so the correct mock targets are the original module
# attributes — Python's import system will return the already-imported
# (mocked) object on the second ``from ... import``.
_PATCH_SELECT   = "backend.agent.router.selector.select"
_PATCH_AVAIL    = "backend.agent.router.registry.available_providers"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def statedb(tmp_path, monkeypatch):
    """Fully-migrated StateDB in a temp dir; patched into backend.core.state."""
    import backend.core.state as state_mod

    db_path = tmp_path / "state.db"
    init_db(db_path)

    old_path = state_mod._DB_PATH
    monkeypatch.setattr(state_mod, "_DB_PATH", db_path)
    yield StateDB
    monkeypatch.setattr(state_mod, "_DB_PATH", old_path)


@pytest.fixture()
def cloud_providers():
    """The real cloud provider set (from core.cloud_llm) for use in dispatch."""
    from backend.core.cloud_llm import PROVIDERS
    return set(PROVIDERS.keys())


# ---------------------------------------------------------------------------
# Scenario 1 — Fallback: first chain provider raises; second succeeds
# ---------------------------------------------------------------------------

class TestFallback:
    """First chain entry raises; route_and_dispatch falls through to second."""

    def test_first_fails_second_succeeds(self, statedb, cloud_providers):
        """If provider[0] raises, provider[1] is tried and its response returned."""
        call_count = {"n": 0}

        async def _fake_post(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("Connection refused")
            return _mock_response(_cloud_chat_response("diagnosis text"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_fake_post):
                with patch(_PATCH_SELECT, return_value=_two_entry_chain()):
                    with patch(_PATCH_AVAIL, return_value=["groq", "mistral"]):
                        client = httpx.AsyncClient()
                        result = await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )
            return result

        result = _run(_inner())

        assert result == "diagnosis text", (
            f"Expected second provider's response; got {result!r}"
        )
        assert call_count["n"] == 2, (
            f"Expected exactly 2 HTTP calls (first fails, second succeeds); got {call_count['n']}"
        )

    def test_fallback_returns_empty_on_full_chain_exhaustion(self, statedb, cloud_providers):
        """If every provider in the chain raises, route_and_dispatch returns ''."""
        import httpx

        async def _always_fail(url, **kwargs):
            raise Exception("simulated failure")

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_always_fail):
                with patch(_PATCH_SELECT, return_value=_two_entry_chain()):
                    with patch(_PATCH_AVAIL, return_value=["groq", "mistral"]):
                        client = httpx.AsyncClient()
                        result = await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "groq", "api_key": "fake-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-key-1234567890",
                            cloud_providers=cloud_providers,
                        )
            return result

        result = _run(_inner())
        assert result == "", (
            f"Expected empty string on full chain exhaustion; got {result!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 2 — Scrub preserved: cloud provider → outbound payload is scrubbed
# ---------------------------------------------------------------------------

class TestScrubPreservedOnCloudPath:
    """A cloud provider in the chain → _dispatch_llm_call applies scrub().

    The key invariant from S-61 / ADR-0018: EVERY outbound call to a cloud
    provider goes through _dispatch_llm_call, which calls scrub() before the
    HTTP request is sent.  This test routes through the REAL _dispatch_llm_call
    to confirm that the scrub choke-point is not bypassed by route_and_dispatch.
    """

    def test_path_not_in_outbound_payload(self, statedb, cloud_providers):
        """/opt/mediastack path must be absent from the cloud provider request."""
        captured: list[dict] = []

        async def _capture_post(url, **kwargs):
            captured.append(kwargs.get("json", {}))
            return _mock_response(_cloud_chat_response("scrubbed result"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_capture_post):
                with patch(_PATCH_SELECT, return_value=_single_cloud_chain("groq")):
                    with patch(_PATCH_AVAIL, return_value=["groq"]):
                        client = httpx.AsyncClient()
                        await route_and_dispatch(
                            client,
                            _SENSITIVE_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )

        _run(_inner())

        assert captured, "No HTTP call was captured"
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert "/opt/mediastack" not in content, (
            f"Raw path leaked to cloud provider via route_and_dispatch! "
            f"content={content!r}"
        )

    def test_ip_not_in_outbound_payload(self, statedb, cloud_providers):
        """Raw IP address must be absent from the cloud provider request."""
        captured: list[dict] = []

        async def _capture_post(url, **kwargs):
            captured.append(kwargs.get("json", {}))
            return _mock_response(_cloud_chat_response("result"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_capture_post):
                with patch(_PATCH_SELECT, return_value=_single_cloud_chain("groq")):
                    with patch(_PATCH_AVAIL, return_value=["groq"]):
                        client = httpx.AsyncClient()
                        await route_and_dispatch(
                            client,
                            _SENSITIVE_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )

        _run(_inner())

        assert captured
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert "192.168.1.50" not in content, (
            f"Raw IP leaked to cloud provider via route_and_dispatch! "
            f"content={content!r}"
        )

    def test_scrub_placeholders_present_in_cloud_payload(self, statedb, cloud_providers):
        """Scrub placeholders must appear in the cloud-bound payload."""
        captured: list[dict] = []

        async def _capture_post(url, **kwargs):
            captured.append(kwargs.get("json", {}))
            return _mock_response(_cloud_chat_response("ok"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_capture_post):
                with patch(_PATCH_SELECT, return_value=_single_cloud_chain("groq")):
                    with patch(_PATCH_AVAIL, return_value=["groq"]):
                        client = httpx.AsyncClient()
                        await route_and_dispatch(
                            client,
                            _SENSITIVE_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )

        _run(_inner())

        assert captured
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert any(ph in content for ph in ("<PATH>", "<IP>", "<APP>", "<USER>")), (
            f"No scrub placeholders found — scrub() may have been bypassed! "
            f"content={content!r}"
        )

    def test_container_name_not_in_outbound_payload(self, statedb, cloud_providers):
        """Docker container name must be absent from the cloud-bound payload."""
        captured: list[dict] = []

        async def _capture_post(url, **kwargs):
            captured.append(kwargs.get("json", {}))
            return _mock_response(_cloud_chat_response("ok"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_capture_post):
                with patch(_PATCH_SELECT, return_value=_single_cloud_chain("groq")):
                    with patch(_PATCH_AVAIL, return_value=["groq"]):
                        client = httpx.AsyncClient()
                        await route_and_dispatch(
                            client,
                            _SENSITIVE_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )

        _run(_inner())

        assert captured
        content = captured[0].get("messages", [{}])[0].get("content", "")
        assert "mediastack-ollama-1" not in content, (
            f"Container name leaked to cloud provider! content={content!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 3 — Empty chain → legacy single-provider path
# ---------------------------------------------------------------------------

class TestEmptyChainLegacyFallback:
    """When route_and_dispatch gets an empty chain it must call the legacy
    _dispatch_llm_call with the cfg provider — no regression."""

    def test_empty_chain_uses_legacy_path(self, statedb, cloud_providers):
        """Empty chain degrades to single-provider _dispatch_llm_call."""
        captured: list[dict] = []

        async def _capture_post(url, **kwargs):
            captured.append({"url": url, "json": kwargs.get("json", {})})
            return _mock_response({"response": "ollama response"})

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_capture_post):
                with patch(_PATCH_SELECT, return_value=_empty_chain()):
                    with patch(_PATCH_AVAIL, return_value=[]):
                        client = httpx.AsyncClient()
                        result = await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "ollama", "enabled": True},
                            ollama_url="http://ollama:11434",
                            model="test-model",
                            api_key="",
                            cloud_providers=cloud_providers,
                        )
            return result

        result = _run(_inner())

        # The legacy path (ollama) should have been called exactly once
        assert captured, "No HTTP call was made — legacy fallback did not execute"
        assert result == "ollama response", (
            f"Expected legacy ollama response; got {result!r}"
        )

    def test_empty_chain_exactly_one_http_call(self, statedb, cloud_providers):
        """Empty chain must result in exactly one HTTP call (no retry loop)."""
        call_count = {"n": 0}

        async def _count_post(url, **kwargs):
            call_count["n"] += 1
            return _mock_response({"response": "ok"})

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_count_post):
                with patch(_PATCH_SELECT, return_value=_empty_chain()):
                    with patch(_PATCH_AVAIL, return_value=[]):
                        client = httpx.AsyncClient()
                        await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "ollama", "enabled": True},
                            ollama_url="http://ollama:11434",
                            model="test-model",
                            api_key="",
                            cloud_providers=cloud_providers,
                        )

        _run(_inner())
        assert call_count["n"] == 1, (
            f"Expected exactly 1 HTTP call for legacy path; got {call_count['n']}"
        )

    def test_router_error_degrades_to_legacy(self, statedb, cloud_providers):
        """If selection itself raises, route_and_dispatch falls back to legacy."""
        captured: list[dict] = []

        async def _capture_post(url, **kwargs):
            captured.append({"url": url, "json": kwargs.get("json", {})})
            return _mock_response({"response": "legacy ok"})

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_capture_post):
                with patch(_PATCH_SELECT, side_effect=RuntimeError("router broken")):
                    with patch(_PATCH_AVAIL, return_value=["ollama"]):
                        client = httpx.AsyncClient()
                        result = await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "ollama", "enabled": True},
                            ollama_url="http://ollama:11434",
                            model="test-model",
                            api_key="",
                            cloud_providers=cloud_providers,
                        )
            return result

        result = _run(_inner())
        assert result == "legacy ok", (
            f"Expected legacy response on router error; got {result!r}"
        )
        assert len(captured) == 1, (
            f"Expected exactly 1 legacy call; got {len(captured)}"
        )


# ---------------------------------------------------------------------------
# Scenario 4 — router_decisions row persistence
# ---------------------------------------------------------------------------

class TestRouterDecisionsPersistence:
    """route_and_dispatch must persist a row to router_decisions with the
    chosen_provider and outcome after every successful or failed dispatch."""

    def test_success_row_persisted_with_chosen_provider(self, statedb, cloud_providers):
        """Successful dispatch → row with outcome='success' and chosen_provider set."""
        async def _ok_post(url, **kwargs):
            return _mock_response(_cloud_chat_response("diagnosis"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_ok_post):
                with patch(_PATCH_SELECT, return_value=_single_cloud_chain("groq")):
                    with patch(_PATCH_AVAIL, return_value=["groq"]):
                        client = httpx.AsyncClient()
                        result = await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )
            return result

        result = _run(_inner())
        assert result == "diagnosis"

        with statedb() as db:
            row = db.execute(
                "SELECT * FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None, "No router_decisions row was written"
        assert row["chosen_provider"] == "groq", (
            f"Expected chosen_provider='groq'; got {row['chosen_provider']!r}"
        )
        assert row["outcome"] == "success", (
            f"Expected outcome='success'; got {row['outcome']!r}"
        )

    def test_all_failed_row_persisted_with_outcome(self, statedb, cloud_providers):
        """Exhausted chain → row with outcome='all_failed' and chosen_provider=None."""
        async def _fail_post(url, **kwargs):
            raise Exception("connection refused")

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_fail_post):
                with patch(_PATCH_SELECT, return_value=_two_entry_chain()):
                    with patch(_PATCH_AVAIL, return_value=["groq", "mistral"]):
                        client = httpx.AsyncClient()
                        result = await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )
            return result

        result = _run(_inner())
        assert result == "", "Expected empty string on all_failed"

        with statedb() as db:
            row = db.execute(
                "SELECT * FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None, "No router_decisions row was written for all_failed"
        assert row["outcome"] == "all_failed", (
            f"Expected outcome='all_failed'; got {row['outcome']!r}"
        )
        assert row["chosen_provider"] is None, (
            f"Expected chosen_provider=None for all_failed; got {row['chosen_provider']!r}"
        )

    def test_row_has_correct_tier(self, statedb, cloud_providers):
        """The persisted row's tier must match the RouteDecision tier."""
        async def _ok_post(url, **kwargs):
            return _mock_response(_cloud_chat_response("ok"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_ok_post):
                with patch(_PATCH_SELECT, return_value=_single_cloud_chain("groq", tier=Tier.STANDARD)):
                    with patch(_PATCH_AVAIL, return_value=["groq"]):
                        client = httpx.AsyncClient()
                        await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )

        _run(_inner())

        with statedb() as db:
            row = db.execute(
                "SELECT tier FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None
        assert row["tier"] == "STANDARD", (
            f"Expected tier='STANDARD'; got {row['tier']!r}"
        )

    def test_row_latency_ms_set(self, statedb, cloud_providers):
        """latency_ms must be a non-negative integer in the persisted row."""
        async def _ok_post(url, **kwargs):
            return _mock_response(_cloud_chat_response("ok"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_ok_post):
                with patch(_PATCH_SELECT, return_value=_single_cloud_chain("groq")):
                    with patch(_PATCH_AVAIL, return_value=["groq"]):
                        client = httpx.AsyncClient()
                        await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )

        _run(_inner())

        with statedb() as db:
            row = db.execute(
                "SELECT latency_ms FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None
        assert isinstance(row["latency_ms"], int), (
            f"Expected latency_ms to be int; got {type(row['latency_ms'])}"
        )
        assert row["latency_ms"] >= 0, (
            f"Expected non-negative latency_ms; got {row['latency_ms']}"
        )

    def test_fallback_chosen_provider_is_second(self, statedb, cloud_providers):
        """When first provider fails, the second succeeds → row records the second."""
        call_count = {"n": 0}

        async def _first_fails_second_ok(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("first provider down")
            return _mock_response(_cloud_chat_response("response from mistral"))

        import httpx

        async def _inner():
            with patch.object(httpx.AsyncClient, "post", side_effect=_first_fails_second_ok):
                with patch(_PATCH_SELECT, return_value=_two_entry_chain()):
                    with patch(_PATCH_AVAIL, return_value=["groq", "mistral"]):
                        client = httpx.AsyncClient()
                        result = await route_and_dispatch(
                            client,
                            _PLAIN_PROMPT,
                            {"provider": "groq", "api_key": "fake-api-key-1234567890", "enabled": True},
                            ollama_url="http://ignored:11434",
                            model="test-model",
                            api_key="fake-api-key-1234567890",
                            cloud_providers=cloud_providers,
                        )
            return result

        result = _run(_inner())
        assert result == "response from mistral", (
            f"Expected mistral's response; got {result!r}"
        )

        with statedb() as db:
            row = db.execute(
                "SELECT chosen_provider, outcome FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None
        assert row["chosen_provider"] == "mistral", (
            f"Expected chosen_provider='mistral' (fallback winner); "
            f"got {row['chosen_provider']!r}"
        )
        assert row["outcome"] == "success"
