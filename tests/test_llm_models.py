"""tests/test_llm_models.py

Unit tests for GET /api/v1/platform/cloud-models (S-33-LLM-MODELS).

Covers:
  - Unknown provider → 400
  - api_key too short → 400
  - Happy path (mocked HTTP) → model list returned, error null
  - Provider HTTP error → {"models": [], "error": "Provider returned HTTP ..."}
  - Timeout → {"models": [], "error": "...timed out..."}
  - Groq uses Bearer auth header
  - Anthropic uses x-api-key header, not Bearer
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Integration-level tests via TestClient (sync, no asyncio plugin needed)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Synchronous TestClient backed by the real FastAPI app."""
    import os
    td = tmp_path_factory.mktemp("slop-llm-models-state")
    os.environ.setdefault("SLOP_DATA_DIR", str(td))
    os.environ.setdefault("SLOP_TEST_MODE", "1")

    from fastapi.testclient import TestClient
    from backend.api.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_unknown_provider_returns_400(client):
    """Unrecognised provider name must return 400."""
    r = client.get("/api/v1/platform/cloud-models", params={"provider": "fakeprovider", "api_key": "a" * 20})
    assert r.status_code == 400


def test_api_key_too_short_returns_400(client):
    """api_key shorter than 10 chars must return 400."""
    r = client.get("/api/v1/platform/cloud-models", params={"provider": "openai", "api_key": "short"})
    assert r.status_code == 400


def test_missing_api_key_returns_400(client):
    """Omitting api_key entirely (empty string default) must return 400."""
    r = client.get("/api/v1/platform/cloud-models", params={"provider": "groq"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Unit-level tests on the async handler directly (no asyncio plugin needed)
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_happy_path_openai_returns_model_list():
    """Mocked OpenAI /v1/models → sorted model list returned, error is None."""
    from backend.api.platform import get_cloud_models

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "gpt-4o", "object": "model"},
            {"id": "gpt-4o-mini", "object": "model"},
            {"id": "gpt-3.5-turbo", "object": "model"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = _run(get_cloud_models(provider="openai", api_key="sk-" + "a" * 20))

    assert result["error"] is None
    assert "gpt-4o" in result["models"]
    assert "gpt-4o-mini" in result["models"]
    assert result["models"] == sorted(result["models"]), "models must be sorted"


def test_provider_http_error_returns_safe_dict():
    """Provider returning non-200 status → safe error dict, no exception raised."""
    from backend.api.platform import get_cloud_models

    mock_response = MagicMock()
    mock_response.status_code = 401

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = _run(get_cloud_models(provider="anthropic", api_key="sk-ant-" + "x" * 20))

    assert result["models"] == []
    assert result["error"] is not None
    assert "401" in result["error"]


def test_timeout_returns_safe_dict():
    """httpx.TimeoutException must be caught and returned as a safe error dict."""
    import httpx
    from backend.api.platform import get_cloud_models

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = _run(get_cloud_models(provider="groq", api_key="gsk_" + "y" * 20))

    assert result["models"] == []
    assert result["error"] is not None


def test_groq_bearer_auth_header_used():
    """Groq uses Bearer auth — Authorization header must be set."""
    from backend.api.platform import get_cloud_models

    captured: dict = {}

    async def fake_get(url, headers=None, **kwargs):
        captured.update(headers or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"id": "llama-3.3-70b-versatile"}]}
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = fake_get

    key = "gsk_testkey_" + "z" * 20
    with patch("httpx.AsyncClient", return_value=mock_client):
        _run(get_cloud_models(provider="groq", api_key=key))

    assert "Authorization" in captured
    assert captured["Authorization"] == f"Bearer {key}"


def test_anthropic_x_api_key_header_used():
    """Anthropic uses x-api-key, not Bearer — Authorization must NOT be present."""
    from backend.api.platform import get_cloud_models

    captured: dict = {}

    async def fake_get(url, headers=None, **kwargs):
        captured.update(headers or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"id": "claude-3-5-sonnet-20241022"}]}
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = fake_get

    key = "sk-ant-" + "a" * 30
    with patch("httpx.AsyncClient", return_value=mock_client):
        _run(get_cloud_models(provider="anthropic", api_key=key))

    assert "x-api-key" in captured
    assert captured["x-api-key"] == key
    assert "Authorization" not in captured
