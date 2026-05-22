"""tests/browser/conftest.py

Playwright browser test configuration.
Auto-skips all browser tests when server is unreachable.
"""
import pytest
import subprocess


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: requires live Mediastack server + Chromium")


def pytest_collection_modifyitems(config, items):
    """Auto-skip browser tests when server is unreachable."""
    import urllib.request

    base_url = getattr(getattr(config, "option", None), "base_url", None) or "http://localhost:8080"

    try:
        urllib.request.urlopen(f"{base_url}/api/platform/status", timeout=3)
        server_up = True
    except Exception:
        server_up = False

    try:
        from playwright.sync_api import sync_playwright
        playwright_ok = True
    except ImportError:
        playwright_ok = False

    for item in items:
        if "browser" in item.keywords:
            if not server_up:
                item.add_marker(pytest.mark.skip(
                    reason=f"Server not reachable at {base_url} — start Mediastack first"
                ))
            elif not playwright_ok:
                item.add_marker(pytest.mark.skip(
                    reason="playwright not installed — run: pip install playwright && playwright install chromium"
                ))
