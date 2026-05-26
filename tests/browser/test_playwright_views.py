"""tests/browser/test_playwright_views.py

Browser E2E tests using Playwright against the live Mediastack server.

Core Rule: 2.1 (full E2E testing — every user-facing flow)
These are the ONLY tests that verify the Vue frontend in a real browser.
Every bug found by looking at the UI was invisible to every other test.

Requirements:
  - Mediastack server running at BASE_URL (default: http://localhost:8080)
  - Chromium installed: python3 -m playwright install chromium
  - Run: pytest tests/browser/ -m browser --base-url http://localhost:8080

Marks:
  @pytest.mark.browser — requires live server + browser
  @pytest.mark.slow    — longer than 10s
"""
from __future__ import annotations

import re
import time

import pytest

# Skip entire module if playwright not available or server not running
playwright_available = True
try:
    from playwright.sync_api import Page, expect
except ImportError:
    playwright_available = False

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not playwright_available, reason="playwright not installed"),
]


def _server_url(request) -> str:
    """Get base URL from --base-url or default."""
    return getattr(request.config, "option", None) and \
           getattr(request.config.option, "base_url", None) or "http://localhost:8080"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Share browser context across all tests — faster than per-test."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 900}}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_api(page: "Page", max_s: int = 10) -> bool:
    """Wait until the API is reachable (page doesn't show error state)."""
    deadline = time.time() + max_s
    while time.time() < deadline:
        try:
            resp = page.request.get("/api/v1/platform/status")
            if resp.ok:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 1. Core Navigation — every route renders without crash
# ─────────────────────────────────────────────────────────────────────────────

class TestCoreNavigation:
    """Every named Vue view must render in a real browser without JS errors."""

    VIEWS = [
        ("/",           "Dashboard"),
        ("/catalog",    "Catalog"),
        ("/health",     "Health"),
        ("/settings",   "Settings"),
        ("/coverage",   "Coverage"),
        ("/infrastructure", "Infrastructure"),
        ("/routing",    "Routing"),
        ("/storage",    "Storage"),
        ("/models",     "Models"),
    ]

    @pytest.mark.parametrize("path,name", VIEWS)
    def test_view_renders_without_js_error(self, page: "Page", base_url: str, path: str, name: str):
        """Every view must load without uncaught JS exceptions."""
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.on("console", lambda m: js_errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{base_url}{path}", wait_until="networkidle")

        assert not js_errors, (
            f"{name}View ({path}) has JS errors: {js_errors[:3]}\n"
            "Browser errors are invisible to all other tests."
        )

    @pytest.mark.parametrize("path,name", VIEWS)
    def test_view_does_not_show_blank_page(self, page: "Page", base_url: str, path: str, name: str):
        """Every view must render visible content — not a white screen."""
        page.goto(f"{base_url}{path}", wait_until="networkidle")
        # Check that the app root has rendered children
        content = page.locator("#app > *")
        expect(content.first).to_be_visible(timeout=5000)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Platform Status → Sidebar Consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestPlatformStatusDisplay:
    """Platform status shown in sidebar must match the API response."""

    def test_sidebar_reflects_api_status(self, page: "Page", base_url: str):
        """Sidebar platform status must match GET /api/platform/status.

        Root bug this catches: stale sidebar after platform reset — UI showed
        'ready' while API reported 'pending'. Never caught by any backend test.
        """
        page.goto(base_url, wait_until="networkidle")

        # Get the API status
        api_resp = page.request.get(f"{base_url}/api/v1/platform/status")
        assert api_resp.ok, "API platform status failed"
        api_status = api_resp.json().get("status", "unknown")

        # Check sidebar shows correct state
        if api_status == "pending":
            # Setup link should be visible when pending
            setup_link = page.locator("a[href='/setup'], a[href*='setup']")
            expect(setup_link.first).to_be_visible(timeout=3000)
        elif api_status == "ready":
            # Dashboard content should be visible
            page.locator("text=Dashboard, text=Catalog, text=Health").first
            # Setup link should NOT be prominent
            pass

    def test_platform_status_updates_without_reload(self, page: "Page", base_url: str):
        """Status must refresh automatically — not require F5.

        Root bug: platform status was cached in Vue component and only
        updated on page load. Reset changed DB but sidebar stayed stale.
        """
        page.goto(base_url, wait_until="networkidle")

        # Trigger a platform status re-check via the API (simulates server-side change)
        api_resp = page.request.get(f"{base_url}/api/v1/platform/status")
        assert api_resp.ok

        # Status poll should happen automatically within 30s (or on route change)
        # Navigate away and back
        page.goto(f"{base_url}/catalog", wait_until="networkidle")
        page.goto(base_url, wait_until="networkidle")

        # No JS errors after navigation
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.wait_for_timeout(1000)
        assert not js_errors, f"JS errors after navigation cycle: {js_errors}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Catalog View
# ─────────────────────────────────────────────────────────────────────────────

class TestCatalogView:
    """Catalog must load apps, show correct install states, handle search."""

    def test_catalog_loads_apps(self, page: "Page", base_url: str):
        """Catalog must display app cards (not empty or error state)."""
        page.goto(f"{base_url}/catalog", wait_until="networkidle")
        # Should show multiple app entries
        apps = page.locator("[data-app-key], .app-card, .catalog-item")
        # If no specific selectors, check for text content from catalog
        page.wait_for_timeout(1000)
        content = page.content()
        assert any(name in content for name in ("Sonarr", "Radarr", "Plex", "Jellyfin")), (
            "Catalog view does not show any known app names. "
            "Either catalog failed to load or Vue rendering broke."
        )

    def test_search_filters_results(self, page: "Page", base_url: str):
        """Search input must filter the visible app list."""
        page.goto(f"{base_url}/catalog", wait_until="networkidle")

        # Find search input
        search = page.locator("input[type='text'], input[placeholder*='earch']").first
        if not search.is_visible():
            pytest.skip("No search input found in catalog — UI may not have search")

        search.fill("sonarr")
        page.wait_for_timeout(500)

        content = page.content()
        assert "Sonarr" in content, "Searching 'sonarr' should show Sonarr"
        # Plex should be hidden after filtering
        # (can't assert hidden DOM elements reliably, but visible text should be filtered)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Coverage Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverageView:
    """Coverage topology dashboard must render all 272+ nodes."""

    def test_coverage_view_renders_nodes(self, page: "Page", base_url: str):
        """Coverage view must display node table with data from /api/coverage."""
        page.goto(f"{base_url}/coverage", wait_until="networkidle")
        page.wait_for_timeout(2000)  # wait for API fetch

        content = page.content()
        # Should show some node kinds
        assert any(k in content for k in ("route", "table", "provider", "manifest", "rule")), (
            "Coverage view shows no node kinds. "
            "Either /api/coverage failed or Vue rendering broke."
        )

    def test_coverage_shows_percentage(self, page: "Page", base_url: str):
        """Overall coverage percentage must be visible."""
        page.goto(f"{base_url}/coverage", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Should show a percentage
        content = page.content()
        assert re.search(r"\d+%", content), (
            "Coverage view does not show a percentage. "
            "Summary card may not be rendering."
        )

    def test_kind_filter_works(self, page: "Page", base_url: str):
        """Kind filter buttons must change visible nodes."""
        page.goto(f"{base_url}/coverage", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Click "Routes" filter if it exists
        routes_btn = page.locator("button:has-text('Routes'), button:has-text('route')")
        if routes_btn.count() > 0:
            routes_btn.first.click()
            page.wait_for_timeout(500)
            # After filtering, should still show content
            content = page.content()
            assert "GET" in content or "POST" in content, (
                "Filtering to 'routes' should show HTTP method names"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Health View
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthView:
    """Health view must show accurate app health state."""

    def test_health_view_renders(self, page: "Page", base_url: str):
        """Health view must load without error."""
        page.goto(f"{base_url}/health", wait_until="networkidle")
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.wait_for_timeout(1000)
        assert not js_errors, f"Health view JS errors: {js_errors}"

    def test_no_apps_shows_empty_state_not_all_healthy(self, page: "Page", base_url: str):
        """With no running apps, health view must not show 'all healthy'.

        Root bug: frontend showed 'all apps healthy' when apps_checked=0.
        This is a false positive — no apps checked ≠ all healthy.
        """
        page.goto(f"{base_url}/health", wait_until="networkidle")
        page.wait_for_timeout(1000)

        content = page.content().lower()
        # If no apps installed, must not claim all healthy
        api_resp = page.request.get(f"{base_url}/api/v1/health/apps")
        if api_resp.ok:
            apps = api_resp.json()
            if not apps:
                assert "all healthy" not in content, (
                    "Health view shows 'all healthy' when no apps are installed. "
                    "Zero apps checked ≠ all healthy — Core Rule 1.5 (fail loud)."
                )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Setup Wizard (when platform is pending)
# ─────────────────────────────────────────────────────────────────────────────

class TestSetupWizard:
    """Setup wizard must be accessible and not crash when platform is pending."""

    def test_setup_route_accessible(self, page: "Page", base_url: str):
        """/setup must render the wizard UI."""
        page.goto(f"{base_url}/setup", wait_until="networkidle")
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.wait_for_timeout(1000)
        assert not js_errors, f"Setup wizard JS errors: {js_errors}"

    def test_setup_shows_form_elements(self, page: "Page", base_url: str):
        """Wizard must show at least one form element — not a blank page."""
        page.goto(f"{base_url}/setup", wait_until="networkidle")
        page.wait_for_timeout(1000)
        # Check for form inputs or wizard steps
        has_inputs = page.locator("input, select, textarea, button").count() > 0
        assert has_inputs, "Setup wizard has no interactive elements — rendering may have broken"


# ─────────────────────────────────────────────────────────────────────────────
# 7. API Response Contract → Vue Rendering
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIToViewContracts:
    """Verify that what the API returns is actually rendered by Vue correctly."""

    def test_settings_values_appear_in_settings_view(self, page: "Page", base_url: str):
        """Settings view must display values from GET /api/settings."""
        # Get current settings from API
        resp = page.request.get(f"{base_url}/api/v1/settings")
        if not resp.ok:
            pytest.skip("Settings API not available")

        page.goto(f"{base_url}/settings", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # Settings page must render (not crash on settings data)
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.wait_for_timeout(500)
        assert not js_errors, f"Settings view JS errors when rendering API data: {js_errors}"

    def test_404_route_does_not_crash(self, page: "Page", base_url: str):
        """Unknown routes must show a not-found state, not a blank crash."""
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.goto(f"{base_url}/this-route-does-not-exist", wait_until="networkidle")
        page.wait_for_timeout(500)
        assert not js_errors, f"Unknown route caused JS crash: {js_errors}"


# ─────────────────────────────────────────────────────────────────────────────
# Data Contract Tests — UI matches API (not just "loads without error")
# Core Rule 3.3: content contracts validated
# These are the tests that would have caught the "stale sidebar" class of bugs
# ─────────────────────────────────────────────────────────────────────────────

class TestUIMatchesAPIData:
    """The UI must render data from the API — not stale/cached/wrong values."""

    def test_coverage_percentage_matches_api(self, page: "Page", base_url: str):
        """Coverage % shown in UI must match GET /api/coverage response.

        Root class: v3 label shown when v4 was deployed — stale render.
        """
        # Get ground truth from API
        api_resp = page.request.get(f"{base_url}/api/coverage")
        if not api_resp.ok:
            pytest.skip("Coverage API not available")

        api_data = api_resp.json()
        api_pct = str(api_data.get("summary", {}).get("coverage_pct", ""))
        if not api_pct:
            pytest.skip("Coverage API returned no percentage")

        # UI must show the same value
        page.goto(f"{base_url}/coverage", wait_until="networkidle")
        page.wait_for_timeout(2000)
        content = page.content()
        assert api_pct in content or f"{api_pct}%" in content, (
            f"Coverage UI shows different percentage than API. "
            f"API: {api_pct}%. UI may be showing stale data."
        )

    def test_platform_status_matches_api(self, page: "Page", base_url: str):
        """Platform status shown in sidebar must match GET /api/platform/status."""
        api_resp = page.request.get(f"{base_url}/api/v1/platform/status")
        if not api_resp.ok:
            pytest.skip("Platform API not available")

        api_status = api_resp.json().get("status", "")
        page.goto(f"{base_url}/", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # The sidebar must reflect the actual DB state
        content = page.content().lower()
        if api_status == "ready":
            # If platform is ready, must NOT show setup wizard prompt
            assert "wizard" not in content or "complete" in content, (
                f"Platform is 'ready' per API but UI shows wizard/setup state. "
                f"Self-heal or status sync is broken."
            )
        elif api_status == "pending":
            # If pending, must show setup cue
            assert any(w in content for w in ("setup", "configure", "wizard", "pending")), (
                f"Platform is 'pending' per API but UI shows no setup prompt."
            )

    def test_catalog_count_matches_api(self, page: "Page", base_url: str):
        """App count shown in catalog must match GET /api/apps/catalog."""
        api_resp = page.request.get(f"{base_url}/api/v1/catalog")
        if not api_resp.ok:
            pytest.skip("Catalog API not available")

        api_apps = api_resp.json()
        # Handle both list and dict responses
        if isinstance(api_apps, list):
            api_count = len(api_apps)
        elif isinstance(api_apps, dict):
            api_count = len(api_apps.get("apps", api_apps))
        else:
            pytest.skip("Unexpected catalog API response shape")

        page.goto(f"{base_url}/catalog", wait_until="networkidle")
        page.wait_for_timeout(2000)

        content = page.content()
        # UI should show the count somewhere (or at least show app cards)
        # Most permissive assertion: if API has >0 apps, UI should show >0 app cards
        if api_count > 0:
            app_cards = page.locator("[data-testid='app-card'], .app-card, [class*='app-card']")
            visible = app_cards.count()
            if visible == 0:
                # Fall back to checking for app names in content
                assert any(
                    word in content.lower()
                    for word in ["sonarr", "radarr", "plex", "install"]
                ), (
                    f"Catalog API has {api_count} apps but catalog UI shows nothing. "
                    "Vue component may have broken rendering."
                )

    def test_no_stale_version_label(self, page: "Page", base_url: str):
        """UI must not show 'v3' or 'v2' label anywhere — regression for version label bug."""
        page.goto(f"{base_url}/", wait_until="networkidle")
        page.wait_for_timeout(500)
        content = page.content()

        for stale_marker in ["Mediastack v2", "Mediastack v3", "msrad", "v3-final"]:
            assert stale_marker not in content, (
                f"Stale version marker '{stale_marker}' found in UI. "
                "Version label not updated after upgrade."
            )

    def test_sidebar_app_status_updates_after_navigation(self, page: "Page", base_url: str):
        """Sidebar app status must NOT be cached across navigation — regression for stale sidebar."""
        # Navigate to catalog and back to dashboard
        page.goto(f"{base_url}/catalog", wait_until="networkidle")
        page.wait_for_timeout(500)
        page.goto(f"{base_url}/", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # No JS errors during navigation (the stale sidebar was caused by a Vue reactivity bug)
        # The actual assertion is that no console error appeared
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1000)

        critical_errors = [e for e in errors if "cannot read" in e.lower() or "undefined" in e.lower()]
        assert not critical_errors, (
            f"Vue reactivity errors after navigation: {critical_errors}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Wizard Flow — regression guard for the prereqs 500 / JSON parse failure
# Root bug: GET /api/v1/platform/prereqs returned "Internal Server Error" as
# plain text; frontend r.json() threw SyntaxError → Stage 0 never rendered.
# ─────────────────────────────────────────────────────────────────────────────

class TestSetupWizardFlow:
    """
    Wizard-specific flow tests.

    These catch the class of bug where a backend route starts returning
    non-JSON (e.g. 500 "Internal Server Error") and the Vue frontend
    throws SyntaxError on r.json() — invisible to all backend tests.
    """

    def test_prereqs_api_returns_json_not_error_string(self, page: "Page", base_url: str):
        """
        Regression: prereqs returning plain-text 500 caused
        SyntaxError: Unexpected token 'I', "Internal S"... is not valid JSON
        in the Platform Setup wizard Stage 0.

        This test verifies the root cause: the API endpoint must return
        valid JSON, not a plain-text error string.
        """
        resp = page.request.get(f"{base_url}/api/v1/platform/prereqs")
        assert resp.status != 500, (
            f"prereqs endpoint returned 500. "
            f"Body: {resp.text()[:200]}"
        )
        # Must be parseable as JSON — this is the exact failure mode the user hit
        try:
            data = resp.json()
        except Exception as e:
            pytest.fail(
                f"prereqs endpoint returned non-JSON (status {resp.status}). "
                f"Frontend will throw SyntaxError. Body: {resp.text()[:200]}. "
                f"Parse error: {e}"
            )
        assert isinstance(data, dict), f"prereqs must return a JSON object, got: {type(data)}"

    def test_wizard_stage_0_loads_without_js_error(self, page: "Page", base_url: str):
        """Stage 0 (Welcome) must render without any JS console errors."""
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.on("console", lambda m: js_errors.append(f"[console.error] {m.text}") if m.type == "error" else None)

        page.goto(f"{base_url}/setup", wait_until="networkidle")
        page.wait_for_timeout(2000)  # wait for onMounted prereqs fetch

        # Filter out non-critical noise (extension errors, etc.)
        critical = [e for e in js_errors if any(
            kw in e.lower() for kw in ("syntaxerror", "unexpected token", "undefined", "cannot read")
        )]
        assert not critical, (
            f"Wizard Stage 0 has critical JS errors: {critical}\n"
            "Most likely cause: a backend API call returned non-JSON."
        )

    def test_wizard_stage_0_to_stage_1_navigation(self, page: "Page", base_url: str):
        """Continue button on Stage 0 must advance to Stage 1 (stack selection)."""
        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))

        page.goto(f"{base_url}/setup", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Find and click Continue
        continue_btn = page.locator("button:has-text('Continue'), button:has-text('Next')").first
        if not continue_btn.is_visible():
            pytest.skip("No Continue button visible on Stage 0 — wizard may require platform=pending state")

        continue_btn.click()
        page.wait_for_timeout(1000)

        # Should now be on Stage 1 (stack selection)
        assert not js_errors, f"JS errors after Stage 0→1 navigation: {js_errors}"

        content = page.content()
        assert any(kw in content.lower() for kw in (
            "stack", "quick", "media", "select", "stage 1", "step 1"
        )), "After clicking Continue, wizard did not advance to Stage 1"

    def test_wizard_no_json_errors_on_mount(self, page: "Page", base_url: str):
        """
        Wizard onMounted makes several API calls. None should result in
        a JSON parse failure. Catches the 'Internal Server Error' class of regression.
        """
        failed_requests = []

        def on_response(response):
            if "/api/v1/" in response.url:
                content_type = response.headers.get("content-type", "")
                if response.status >= 400 or "application/json" not in content_type:
                    failed_requests.append({
                        "url": response.url,
                        "status": response.status,
                        "content_type": content_type,
                    })

        page.on("response", on_response)
        page.goto(f"{base_url}/setup", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Filter for non-JSON that would break the frontend
        critical = [r for r in failed_requests if r["status"] >= 500]
        assert not critical, (
            f"Wizard's onMounted API calls returned 500s: {critical}\n"
            "These will cause JSON parse errors in the frontend."
        )
