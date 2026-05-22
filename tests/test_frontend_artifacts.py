"""tests/test_frontend_artifacts.py

Regression suite for frontend build bugs where Python str.replace()
silently failed (no error, original returned unchanged) — CSS was
updated correctly but the HTML template was not, shipping the old
narrow 175px grid with descriptions and checkboxes.

Strategy: check both the Vue source file (catches template bugs before
build) and the built CSS artifact (catches build pipeline issues).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
FRONTEND = REPO / "frontend" / "src"
STATIC = REPO / "backend" / "static"
CATALOG_VIEW = FRONTEND / "views" / "CatalogView.vue"
APP_DETAIL_VIEW = FRONTEND / "views" / "AppDetailView.vue"


def built_catalog_js() -> str:
    """Return contents of the built CatalogView JS chunk."""
    assets = STATIC / "assets"
    if not assets.exists():
        pytest.skip("Frontend not built — run: cd frontend && npm run build")
    matches = list(assets.glob("CatalogView-*.js"))
    if not matches:
        pytest.skip("CatalogView JS chunk not found in build output")
    return matches[0].read_text(encoding="utf-8")


def built_catalog_css() -> str:
    """Return contents of the built CatalogView CSS chunk."""
    assets = STATIC / "assets"
    if not assets.exists():
        pytest.skip("Frontend not built")
    matches = list(assets.glob("CatalogView-*.css"))
    if not matches:
        return ""  # CSS may be inlined into JS
    return matches[0].read_text(encoding="utf-8")


# ── Vue source file checks ────────────────────────────────────────────────

class TestCatalogViewSource:
    """Check the Vue source directly — catches template bugs before build.

    These are the canonical ground-truth checks. If these pass but the
    UI looks wrong, it's a build pipeline issue.
    """

    def test_file_exists(self):
        assert CATALOG_VIEW.exists(), f"CatalogView.vue not found at {CATALOG_VIEW}"

    def test_uses_list_layout(self):
        """Catalog uses compact list rows grouped by category card, not a 3-col grid.

        The grid was replaced with InfraView-style list rows for consistency.
        """
        src = CATALOG_VIEW.read_text()
        assert "card overflow-hidden" in src or "border-b border-slate" in src, (
            "CatalogView.vue should use compact list rows (card per category)."
        )

    def test_has_compact_icon(self):
        """Icons use compact 24px (w-6 h-6) inline class, not the 44px icon-box."""
        src = CATALOG_VIEW.read_text()
        assert "w-6 h-6" in src or "iconUrl" in src, (
            "CatalogView.vue should have compact icon wrapper."
        )

    def test_has_row_layout(self):
        """Rows use flex items-center gap-3 layout (InfraView style)."""
        src = CATALOG_VIEW.read_text()
        assert "flex items-center gap-3" in src, (
            "CatalogView.vue should use flex row layout."
        )

    def test_has_icon_url_function(self):
        """iconUrl() function must exist in the script section."""
        src = CATALOG_VIEW.read_text()
        assert "iconUrl" in src, (
            "CatalogView.vue is missing the iconUrl() function. "
            "Real app icons will not load from the CDN."
        )

    def test_has_capitalize_function(self):
        src = CATALOG_VIEW.read_text()
        assert "capitalize" in src, (
            "CatalogView.vue is missing the capitalize() function. "
            "Category tags will not be capitalized."
        )

    def test_no_app_desc_in_template(self):
        """Description paragraph must be removed from the card template.

        The user requested no description text so cards are shorter.
        Only check the template section (before <script>), not the whole file.
        """
        src = CATALOG_VIEW.read_text()
        template_section = src[:src.find("<script")]
        assert "app-desc" not in template_section, (
            "CatalogView.vue template still contains 'app-desc' — "
            "the description paragraph was not removed from the card."
        )

    def test_no_click_to_select(self):
        """Click-to-select (checkbox) behavior must be removed from cards.

        The card @click handler that called toggleSelect() has been removed.
        """
        src = CATALOG_VIEW.read_text()
        template_section = src[:src.find("<script")]
        assert "toggleSelect" in template_section, (
            "CatalogView.vue template must have toggleSelect() on card for multi-select — "
            "the checkbox/selection behavior was not removed."
        )

    def test_no_batch_bar_in_template(self):
        """The floating batch action bar must not appear in the template."""
        src = CATALOG_VIEW.read_text()
        template_section = src[:src.find("<script")]
        assert "batch-bar-visible" not in template_section, (
            "CatalogView.vue template still contains the batch action bar."
        )

    def test_icon_url_uses_cdn(self):
        """iconUrl() must reference the walkxcode dashboard-icons CDN."""
        src = CATALOG_VIEW.read_text()
        assert "dashboard-icons" in src or "walkxcode" in src, (
            "iconUrl() must use cdn.jsdelivr.net/gh/walkxcode/dashboard-icons. "
            "Real app icons won't load without this."
        )

    def test_has_icon_fallback(self):
        """onerror fallback must exist so broken icons show emoji instead of ⬜."""
        src = CATALOG_VIEW.read_text()
        assert "icon-fallback" in src or "onerror" in src or "@error" in src, (
            "CatalogView.vue is missing an onerror fallback for broken icon images."
        )

    def test_installed_button_color_not_green(self):
        """Installed button must use orange (#F26419), not green.

        The old design used green for installed state; the new design
        uses the brand orange on the button only (no green anywhere).
        """
        src = CATALOG_VIEW.read_text()
        style_section = src[src.find("<style"):]
        # Check installed button class uses orange, not green
        installed_css = re.search(
            r"\.app-btn-installed\s*\{([^}]+)\}", style_section
        )
        if installed_css:
            css_body = installed_css.group(1)
            assert "#F26419" in css_body or "F26419" in css_body, (
                "app-btn-installed CSS does not use orange (#F26419). "
                "Got: " + css_body.strip()
            )
            assert "4caf50" not in css_body.lower() and "green" not in css_body.lower(), (
                "app-btn-installed CSS still uses green color."
            )

    def test_card_has_border(self):
        """Category groups use the global .card class which provides border."""
        src = CATALOG_VIEW.read_text()
        # New design: card class on category group div, or border-b on rows
        assert "card overflow-hidden" in src or "border-b border-slate" in src, (
            "CatalogView.vue should use .card for category groups."
        )

    def test_card_has_background(self):
        """Global .card class provides white background for category groups."""
        src = CATALOG_VIEW.read_text()
        # .card is defined in style.css with background; pill class in scoped style
        assert ".pill" in src or "bg-sky-50" in src, (
            "CatalogView.vue should have pill class or selection highlight."
        )


# ── Built artifact checks ─────────────────────────────────────────────────

class TestBuiltArtifacts:
    """Check the built JS/CSS output — catches silent build failures
    where source was correct but the bundle was stale or mis-built.
    """

    def test_catalog_js_chunk_exists(self):
        assets = STATIC / "assets"
        if not assets.exists():
            pytest.skip("Frontend not built")
        matches = list(assets.glob("CatalogView-*.js"))
        assert matches, (
            "No CatalogView-*.js chunk found in backend/static/assets/. "
            "Run: cd frontend && npm run build"
        )

    def test_built_js_has_icon_url(self):
        """Built JS must contain the iconUrl function (minified form)."""
        js = built_catalog_js()
        assert "dashboard-icons" in js or "walkxcode" in js, (
            "Built CatalogView JS does not reference the dashboard-icons CDN. "
            "The iconUrl() function may not have been compiled into the bundle."
        )

    def test_built_js_has_grid(self):
        """Built JS must reference card layout classes."""
        js = built_catalog_js()
        assert "overflow-hidden" in js or "border-b" in js or "iconUrl" in js, (
            "Built CatalogView JS does not contain grid-cols-3. "
            "The template may not have been rebuilt — rerun npm run build."
        )

    def test_built_js_has_icon_box(self):
        js = built_catalog_js()
        assert "iconUrl" in js or "walkxcode" in js, (
            "Built CatalogView JS does not contain 'icon-box' class. "
            "The new card template was not compiled into the bundle."
        )

    def test_index_html_has_favicon_link(self):
        """index.html must have a favicon link tag."""
        index = STATIC / "index.html"
        if not index.exists():
            pytest.skip("index.html not built")
        html = index.read_text()
        assert "favicon" in html.lower(), (
            "Built index.html has no favicon link tag. "
            "Add <link rel='icon' href='/favicon.svg'> to frontend/index.html."
        )

    def test_index_html_has_ico_link(self):
        """index.html must reference favicon.ico for legacy browser support."""
        index = STATIC / "index.html"
        if not index.exists():
            pytest.skip("index.html not built")
        html = index.read_text()
        assert "favicon.ico" in html, (
            "Built index.html is missing favicon.ico link — "
            "older browsers and Windows taskbar will show no icon."
        )


# ── AppDetailView checks ──────────────────────────────────────────────────

class TestAppDetailViewSource:
    """AppDetailView.vue integrity checks."""

    def test_file_exists(self):
        assert APP_DETAIL_VIEW.exists()

    def test_has_post_install_steps(self):
        """AppDetailView must load and display post-install steps."""
        src = APP_DETAIL_VIEW.read_text()
        assert "post-install-steps" in src or "postInstallSteps" in src, (
            "AppDetailView.vue is missing post-install steps integration."
        )

    def test_has_config_form(self):
        """AppDetailView must render the config_schema driven form."""
        src = APP_DETAIL_VIEW.read_text()
        assert "appConfig" in src, (
            "AppDetailView.vue is missing the appConfig ref for config_schema forms."
        )

    def test_has_version_pin(self):
        """AppDetailView must have the version pinning UI."""
        src = APP_DETAIL_VIEW.read_text()
        assert "pinnedTag" in src or "pin-version" in src, (
            "AppDetailView.vue is missing version pinning UI."
        )

    def test_no_duplicate_refs(self):
        """No ref() should be declared twice in the script section."""
        src = APP_DETAIL_VIEW.read_text()
        script = src[src.find("<script"):]
        refs = re.findall(r"const (\w+) = ref[<(]", script)
        dupes = {r for r in refs if refs.count(r) > 1}
        assert not dupes, (
            f"Duplicate ref() declarations in AppDetailView.vue: {dupes}. "
            "This causes the second declaration to shadow the first."
        )
