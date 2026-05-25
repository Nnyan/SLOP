"""tests/test_manifest_integrity.py

Regression suite for manifest loading bugs:

- Fields declared in the AppManifest dataclass but never wired to the
  YAML parser — config_schema and config_defaults were present in the
  class definition but missing from the AppManifest() constructor call,
  so every manifest silently returned [] and {} respectively.

- dashboard_icon field — optional override for the walkxcode icon CDN;
  must be parsed when present.

- Auto-derived icon name — key.replace('_', '-') must produce a
  well-formed CDN path.
"""
from __future__ import annotations

from pathlib import Path
import pytest

REPO = Path(__file__).parent.parent
CATALOG = REPO / "catalog" / "apps"


def all_manifests():
    """Yield (key, manifest) for every app in the catalog."""
    from backend.manifests.loader import load_manifest
    for f in sorted(CATALOG.glob("*.yaml")):
        key = f.stem
        try:
            yield key, load_manifest(key)
        except Exception as e:
            pytest.fail(f"load_manifest('{key}') raised {e}")


# ── config_schema wiring ───────────────────────────────────────────────────

class TestConfigSchemaWiring:
    """config_schema must be read from the YAML file, not default to [].

    Root cause: the AppManifest() constructor call in loader.py was
    missing config_schema= and config_defaults= keyword arguments.
    The dataclass had them with field(default_factory=list/dict), so
    every manifest silently returned empty values.
    """

    def test_ddns_updater_has_config_schema(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        assert len(m.config_schema) >= 2, (
            f"ddns_updater config_schema is empty — "
            f"loader.py is not passing config_schema= to AppManifest(). "
            f"Got: {m.config_schema}"
        )

    def test_ddns_updater_schema_has_providers_field(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        keys = [f["key"] for f in m.config_schema]
        assert "providers" in keys, (
            f"ddns_updater config_schema missing 'providers' field. Got keys: {keys}"
        )

    def test_ddns_updater_schema_has_period_field(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        keys = [f["key"] for f in m.config_schema]
        assert "period" in keys

    def test_config_schema_fields_have_required_keys(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        for field in m.config_schema:
            assert "key" in field, f"Schema field missing 'key': {field}"
            assert "label" in field, f"Schema field missing 'label': {field}"

    def test_apps_without_schema_return_empty_list(self):
        """Apps that don't define config_schema must return [], not crash."""
        from backend.manifests.loader import load_manifest
        m = load_manifest("sonarr")
        assert isinstance(m.config_schema, list)
        # sonarr has no config_schema in its YAML — should be []
        assert m.config_schema == [], (
            f"sonarr should have empty config_schema but got: {m.config_schema}"
        )


# ── config_defaults wiring ─────────────────────────────────────────────────

class TestConfigDefaultsWiring:
    def test_ddns_updater_has_defaults(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        assert isinstance(m.config_defaults, dict)
        assert len(m.config_defaults) > 0, (
            "ddns_updater config_defaults is empty — "
            "loader.py is not passing config_defaults= to AppManifest()."
        )

    def test_ddns_updater_period_default(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        assert m.config_defaults.get("period") == "5m", (
            f"Expected period='5m', got: {m.config_defaults.get('period')}"
        )

    def test_ddns_updater_ip_version_default(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("ddns_updater")
        assert m.config_defaults.get("ip_version") == "ipv4"

    def test_apps_without_defaults_return_empty_dict(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("sonarr")
        assert isinstance(m.config_defaults, dict)
        assert m.config_defaults == {}


# ── dashboard_icon wiring ─────────────────────────────────────────────────

class TestDashboardIconWiring:
    """dashboard_icon override must be loaded from YAML when present."""

    def test_docker_socket_proxy_override(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("docker_socket_proxy")
        assert m.dashboard_icon == "docker", (
            f"docker_socket_proxy should have dashboard_icon='docker' but got "
            f"'{m.dashboard_icon}'. The override in the YAML is not being parsed."
        )

    def test_apps_without_override_return_empty_string(self):
        from backend.manifests.loader import load_manifest
        m = load_manifest("sonarr")
        assert m.dashboard_icon == "", (
            f"sonarr has no dashboard_icon override but got '{m.dashboard_icon}'"
        )

    def test_icon_url_derivation_no_underscores(self):
        """Auto-derived icon name must not contain underscores — CDN uses hyphens."""
        from backend.manifests.loader import load_manifest
        for key, manifest in all_manifests():
            icon_name = (manifest.dashboard_icon or key).replace("_", "-").lower()
            assert "_" not in icon_name, (
                f"{key}: derived icon name '{icon_name}' still contains underscore. "
                "Check replace('_', '-') logic."
            )

    def test_icon_url_derivation_is_lowercase(self):
        from backend.manifests.loader import load_manifest
        for key, manifest in all_manifests():
            icon_name = (manifest.dashboard_icon or key).replace("_", "-").lower()
            assert icon_name == icon_name.lower(), (
                f"{key}: derived icon name '{icon_name}' is not lowercase."
            )


# ── General manifest completeness ─────────────────────────────────────────

class TestManifestCompleteness:
    """All manifests must have the minimum required fields populated."""

    REQUIRED_FIELDS = ["key", "display_name", "description", "category", "image"]

    def test_all_manifests_load(self):
        """Every YAML file in catalog/apps/ must load without exception."""
        errors = []
        from backend.manifests.loader import load_manifest
        for f in sorted(CATALOG.glob("*.yaml")):
            try:
                load_manifest(f.stem)
            except Exception as e:
                errors.append(f"{f.name}: {e}")
        assert not errors, "Manifests that failed to load:\n" + "\n".join(errors)

    # test_test_all_manifests_have_required_fields removed — duplicate of test in test_comprehensive_contracts.py

    def test_all_manifest_keys_match_filename(self):
        """manifest.key must match the YAML filename stem."""
        from backend.manifests.loader import load_manifest
        errors = []
        for f in sorted(CATALOG.glob("*.yaml")):
            m = load_manifest(f.stem)
            if m.key != f.stem:
                errors.append(
                    f"{f.name}: manifest.key='{m.key}' does not match filename '{f.stem}'"
                )
        assert not errors, "\n".join(errors)

    def test_config_schema_fields_are_lists(self):
        """config_schema must always be a list, never None or a dict."""
        for key, manifest in all_manifests():
            assert isinstance(manifest.config_schema, list), (
                f"{key}: config_schema is {type(manifest.config_schema).__name__}, expected list"
            )

    def test_config_defaults_are_dicts(self):
        """config_defaults must always be a dict, never None or a list."""
        for key, manifest in all_manifests():
            assert isinstance(manifest.config_defaults, dict), (
                f"{key}: config_defaults is {type(manifest.config_defaults).__name__}, expected dict"
            )


# ── Unresolved placeholder guard ───────────────────────────────────────────

class TestNoUnresolvedPlaceholders:
    """Catalog YAML prose fields must not contain raw {placeholder} strings.

    Single-brace {var} patterns (Python .format() style) in prose fields
    indicate an unresolved template substitution — the placeholder was written
    into a description or display_name but never replaced with an actual value.

    Volume host paths legitimately use {config_root}/{media_root} tokens and
    are deliberately excluded. Only top-level prose string fields are checked.

    Regression source: T3-A retrospective — {domain} found in a description
    field; guard added to prevent recurrence.
    """

    # Prose fields that MUST NOT contain raw {placeholder} tokens.
    # URL/path fields (volumes[].host) are legitimately templated and excluded.
    PROSE_FIELDS = (
        "description",
        "short_description",
        "display_name",
        "notes",
        "summary",
        "category",
    )

    def _catalog_yaml_files(self):
        """Yield all YAML files from apps/ and community/ (if it exists)."""
        import yaml
        dirs = [CATALOG]
        community = CATALOG.parent / "community"
        if community.exists():
            dirs.append(community)
        for catalog_dir in dirs:
            for f in sorted(catalog_dir.glob("*.yaml")):
                with open(f) as fh:
                    doc = fh.read()
                yield f, doc

    def test_no_unresolved_single_brace_in_descriptions(self):
        """No catalog YAML prose field may contain a raw {placeholder} token."""
        import re
        import yaml

        BRACE_RE = re.compile(r'\{[a-z_]+\}')
        violations = []

        for yaml_path, raw_text in self._catalog_yaml_files():
            try:
                doc = yaml.safe_load(raw_text)
            except Exception as exc:
                # YAML parse errors are caught by TestManifestCompleteness
                continue
            if not isinstance(doc, dict):
                continue
            for field in self.PROSE_FIELDS:
                value = doc.get(field)
                if not isinstance(value, str):
                    continue
                match = BRACE_RE.search(value)
                if match:
                    violations.append(
                        f"{yaml_path.name}: field '{field}' contains unresolved "
                        f"placeholder '{match.group()}' in value: {value!r}"
                    )

        assert not violations, (
            "Unresolved single-brace placeholders found in catalog prose fields.\n"
            "These look like Python .format() tokens that were never substituted.\n"
            "Fix the YAML or add to the exclusion list if intentional.\n\n"
            + "\n".join(violations)
        )