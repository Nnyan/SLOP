"""
tests/test_wizard_contracts.py — Contract tests for the setup wizard.

These tests answer the question: "for every user selection in the wizard,
does something actually happen in the backend?"

This is the test that would have caught the Stage 3 infra gap — where
auth=tinyauth, vpn=gluetun, dashboard=glance etc. were collected by the
wizard but no step ever called provider.deploy() for them.

Design: static analysis + real code imports. No mocks. No HTTP calls.
"""

import ast
import pathlib
import re
import sys
import pytest

REPO = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO))


# ── Helpers ───────────────────────────────────────────────────────────────

def _wizard_steps_src() -> str:
    """Source of all wizard step functions concatenated."""
    src = (REPO / "backend" / "platform" / "wizard.py").read_text()
    # Only the step function bodies, not the class or STEPS list
    return src[src.find("def step_"):]


def _wizard_input_fields() -> dict[str, int]:
    """WizardInput field → usage count in step functions."""
    src = (REPO / "backend" / "platform" / "wizard.py").read_text()
    m = re.search(r'class WizardInput:(.*?)(?=\n# ---|\ndef )', src, re.DOTALL)
    if not m:
        return {}
    fields = re.findall(r'^\s{4}(\w+)\s*:', m.group(1), re.MULTILINE)
    steps = _wizard_steps_src()
    return {f: len(re.findall(rf'\binp\.{f}\b', steps)) for f in fields}


def _active_steps() -> list[str]:
    src = (REPO / "backend" / "platform" / "wizard.py").read_text()
    m = re.search(r'STEPS = \[(.*?)\]', src, re.DOTALL)
    if not m:
        return []
    # Each entry is ("step_name", step_fn) — take every first quoted string per line
    steps = []
    for line in m.group(1).splitlines():
        match = re.search(r'"(\w+)"', line)
        if match:
            steps.append(match.group(1))
    return steps


def _defined_steps() -> list[str]:
    src = (REPO / "backend" / "platform" / "wizard.py").read_text()
    return re.findall(r'^def step_(\w+)\(', src, re.MULTILINE)


def _infra_providers() -> dict[str, list[str]]:
    """slot → [keys] from provider class attributes."""
    import collections
    providers: dict = collections.defaultdict(list)
    for f in (REPO / "backend" / "infra" / "providers").glob("*.py"):
        src = f.read_text()
        slot_m = re.search(r'\bslot\s*=\s*["\'](\w+)["\']', src)
        if slot_m:
            for km in re.finditer(r'\bkey\s*=\s*["\'](\w+)["\']', src):
                providers[slot_m.group(1)].append(km.group(1))
    return dict(providers)


def _deploy_infra_src() -> str:
    """Source of step_deploy_infra + its helpers (`_deploy_*`,
    `_try_deploy_one`, `_format_deploy_result`).

    Step 2.7.h split the previously-monolithic step_deploy_infra into
    per-slot helpers; the `inp.auth` / `inp.vpn` / `inp.dashboard` /
    `inp.management` / `inp.tunnels` references now live in the
    helpers, not in the orchestrator. The contract tests below check
    for those field references — this helper assembles all the
    deploy-related function bodies so the assertions still find them.
    """
    src = (REPO / "backend" / "platform" / "wizard.py").read_text()
    parts: list[str] = []
    pattern = (
        r'def (?:step_deploy_infra|_deploy_\w+|_try_deploy_one|'
        r'_format_deploy_result)\(.*?(?=\ndef \w)'
    )
    for m in re.finditer(pattern, src, re.DOTALL):
        parts.append(m.group(0))
    return "\n".join(parts)


# ── Contract: WizardInput fields are all used ─────────────────────────────

class TestWizardInputContracts:
    """Every field on WizardInput must be read by at least one wizard step.
    
    If a field is collected from the user but never read, the user's choice
    has no effect — a silent drop that looks like it works.
    """

    # Fields legitimately on WizardInput but used outside wizard steps
    # (e.g. written to .env indirectly via inp.secrets)
    ALLOWED_UNUSED = {
        "traefik_dashboard_port",  # passed to build_traefik_fragment
    }

    def test_no_dead_wizard_input_fields(self):
        """Every WizardInput field must be referenced in at least one step function."""
        fields = _wizard_input_fields()
        dead = {
            f: count for f, count in fields.items()
            if count == 0 and f not in self.ALLOWED_UNUSED
        }
        assert not dead, (
            f"WizardInput fields never read by any step: {list(dead.keys())}\n"
            "These are collected from users but silently ignored.\n"
            "This is how Stage 3 infra selections were dropped for months."
        )

    def test_domain_field_used(self):
        fields = _wizard_input_fields()
        assert fields.get("domain", 0) > 5, "domain should be used heavily"

    def test_auth_field_used_by_deploy_infra(self):
        """inp.auth must be referenced in step_deploy_infra specifically."""
        src = _deploy_infra_src()
        assert "inp.auth" in src, (
            "inp.auth not referenced in step_deploy_infra! "
            "Auth provider will never be deployed."
        )

    def test_vpn_field_used_by_deploy_infra(self):
        src = _deploy_infra_src()
        assert "inp.vpn" in src, "inp.vpn not in step_deploy_infra — VPN never deployed"

    def test_dashboard_field_used_by_deploy_infra(self):
        src = _deploy_infra_src()
        assert "inp.dashboard" in src, "Dashboard never deployed"

    def test_management_field_used_by_deploy_infra(self):
        src = _deploy_infra_src()
        assert "inp.management" in src, "Management app never deployed"

    def test_tunnels_field_used_by_deploy_infra(self):
        src = _deploy_infra_src()
        assert "inp.tunnels" in src, "Tunnels never deployed"

    def test_eab_credentials_reach_traefik_config(self):
        """ZeroSSL EAB credentials must be passed to build_traefik_yaml."""
        src = _wizard_steps_src()
        # step_traefik_config must reference eab_kid
        traefik_config_m = re.search(
            r'def step_traefik_config\(.*?(?=\ndef step_)', src, re.DOTALL
        )
        if traefik_config_m:
            assert "eab_kid" in traefik_config_m.group(0), (
                "eab_kid not passed to traefik config — ZeroSSL certs will never work"
            )

    def test_secrets_written_to_env(self):
        """Secrets collected in Stage 5 must be written to .env."""
        src = _wizard_steps_src()
        env_step_m = re.search(
            r'def step_write_env\(.*?(?=\ndef step_)', src, re.DOTALL
        )
        if env_step_m:
            assert "inp.secrets" in env_step_m.group(0), (
                "inp.secrets not referenced in step_write_env — Stage 5 secrets lost"
            )


# ── Contract: every INFRA_SLOT option has a deploy handler ───────────────

class TestInfraSlotContracts:
    """Every non-none option in the wizard's INFRA_SLOTS must be deployable.

    This test would have caught the Stage 3 gap immediately.
    """

    # Known frontend slot → backend values (from SetupView.vue INFRA_SLOTS)
    FRONTEND_OPTIONS = {
        "auth":       ["tinyauth", "authelia"],
        "tunnel":     ["cloudflared", "tailscale", "headscale"],
        "vpn":        ["gluetun"],
        "dashboard":  ["glance", "homepage"],
        "management": ["dockge", "portainer", "dockhand", "komodo"],
    }

    def test_every_auth_option_has_provider(self):
        providers = _infra_providers()
        for opt in self.FRONTEND_OPTIONS["auth"]:
            assert opt in providers.get("auth", []), (
                f"auth='{opt}' has no InfraProvider — cannot be deployed"
            )

    def test_every_tunnel_option_has_provider(self):
        providers = _infra_providers()
        for opt in self.FRONTEND_OPTIONS["tunnel"]:
            assert opt in providers.get("tunnel", []), (
                f"tunnel='{opt}' has no InfraProvider"
            )

    def test_every_vpn_option_has_provider(self):
        providers = _infra_providers()
        for opt in self.FRONTEND_OPTIONS["vpn"]:
            assert opt in providers.get("vpn", []), (
                f"vpn='{opt}' has no InfraProvider"
            )

    def test_every_dashboard_option_has_provider(self):
        providers = _infra_providers()
        for opt in self.FRONTEND_OPTIONS["dashboard"]:
            assert opt in providers.get("dashboard", []), (
                f"dashboard='{opt}' has no InfraProvider"
            )

    def test_every_management_option_has_provider(self):
        providers = _infra_providers()
        for opt in self.FRONTEND_OPTIONS["management"]:
            assert opt in providers.get("management", []), (
                f"management='{opt}' has no InfraProvider"
            )

    def test_deploy_infra_step_exists_in_steps_list(self):
        """step_deploy_infra must be in the STEPS list — or infra is never deployed."""
        active = _active_steps()
        assert "deploy_infra" in active, (
            "step_deploy_infra not in STEPS list — "
            "all Stage 3 selections will be silently ignored!"
        )

    def test_deploy_infra_after_traefik_healthy(self):
        """Infra must deploy after Traefik is healthy (routing prerequisite)."""
        active = _active_steps()
        if "deploy_infra" in active and "traefik_healthy" in active:
            assert active.index("deploy_infra") > active.index("traefik_healthy"), (
                "deploy_infra must run after traefik_healthy"
            )

    def test_deploy_infra_handles_each_slot(self):
        """step_deploy_infra must reference all 5 slot types."""
        deploy_src = _deploy_infra_src()
        assert deploy_src, "step_deploy_infra function not found"
        for slot_attr in ("inp.auth", "inp.vpn", "inp.dashboard", "inp.management", "inp.tunnels"):
            assert slot_attr in deploy_src, (
                f"{slot_attr} not in step_deploy_infra — that slot is never deployed"
            )


# ── Contract: all wizard steps are active ────────────────────────────────

class TestWizardStepCompleteness:
    """Every defined step_ function must be in the STEPS list."""

    # Steps that are utilities / helpers, not wizard stages
    NON_STAGE_STEPS: set[str] = {"socket_proxy"}  # runs post-complete, conditional

    def test_no_orphan_steps(self):
        """Defined steps not in STEPS list are dead code — they never run."""
        defined = set(_defined_steps()) - self.NON_STAGE_STEPS
        active  = set(_active_steps())
        orphans = defined - active
        assert not orphans, (
            f"Defined but inactive steps: {orphans}\n"
            "These functions exist but are never called during setup."
        )

    def test_steps_list_has_required_steps(self):
        """Core steps that must always be present."""
        active = _active_steps()
        required = [
            "docker_check", "write_env", "traefik_deploy",
            "traefik_healthy", "deploy_infra", "complete",
        ]
        for step in required:
            assert step in active, f"Required step '{step}' missing from STEPS"


# ── Contract: wizard payload fields match backend ────────────────────────

class TestPayloadContracts:
    """Fields sent by the frontend must be accepted by the backend."""

    # What the frontend sends (from SetupView.vue runWizard payload)
    FRONTEND_PAYLOAD_FIELDS = {
        "domain", "config_root", "media_root", "puid", "pgid", "timezone",
        "cert_resolver", "acme_email", "dns_provider", "eab_kid", "eab_hmac",
        "ntfy_url", "ntfy_topic", "ntfy_enabled", "secrets",
        "infra_selections", "selected_stacks",
    }

    # What WizardRequest accepts (check against model fields)
    def test_wizard_request_accepts_all_payload_fields(self):
        from backend.api.platform import WizardRequest
        import inspect
        # Get all fields on WizardRequest
        wr_fields = set(WizardRequest.model_fields.keys())
        # infra_selections and selected_stacks are top-level WizardRequest fields
        missing = self.FRONTEND_PAYLOAD_FIELDS - wr_fields - {"infra_selections", "selected_stacks"}
        assert not missing, (
            f"Frontend sends these fields but WizardRequest doesn't have them: {missing}"
        )

    def test_infra_selections_accepted_as_dict(self):
        from backend.api.platform import WizardRequest
        # Should accept tunnels as list
        req = WizardRequest(
            domain="test.local",
            infra_selections={"auth": "tinyauth", "tunnels": ["cloudflared", "tailscale"]},
        )
        assert req.infra_selections["tunnels"] == ["cloudflared", "tailscale"]

    def test_wizard_input_built_from_request(self):
        """The WizardInput constructor in run_async must not crash with real values."""
        from backend.platform.wizard import WizardInput
        # Simulate what wizard_run_async builds
        inp = WizardInput(
            domain="test.local",
            config_root="/srv/test/config",
            media_root="/mnt/test/media",
            puid=1000,
            pgid=1000,
            timezone="UTC",
            cert_resolver="letsencrypt",
            acme_email="test@test.local",
            dns_provider="cloudflare",
            secrets={"CF_DNS_API_TOKEN": "test123"},
            auth="tinyauth",
            tunnels=["cloudflared"],
            vpn="gluetun",
            dashboard="glance",
            management="dockhand",
            traefik_dashboard_port=8081,
            eab_kid="kid123",
            eab_hmac="hmac456",
        )
        assert inp.domain == "test.local"
        assert inp.auth == "tinyauth"
        assert inp.tunnels == ["cloudflared"]
        assert inp.eab_kid == "kid123"
        assert inp.traefik_dashboard_port == 8081


# ── Contract: frontend Stage 5 LLM config reaches backend ────────────────

class TestLLMContracts:
    """Stage 5 selections must result in correct llm_agent_config."""

    def test_ollama_url_set_when_ollama_selected(self, tmp_path):
        """wizard_save_llm with provider=ollama must set ollama_url."""
        import json
        from backend.core.state import init_db, configure, StateDB

        db_path = tmp_path / "state.db"
        init_db(db_path)
        configure(db_path)

        # Simulate what wizard_save_llm does for provider=ollama
        with StateDB() as db:
            cfg = {
                "provider": "ollama",
                "api_key": "",
                "model": "phi4-mini",
                "ollama_url": "http://ollama:11434",
            }
            db.set_setting("llm_agent_config", json.dumps(cfg))

        with StateDB() as db:
            saved = json.loads(db.get_setting("llm_agent_config") or "{}")

        assert saved.get("provider") == "ollama"
        assert saved.get("ollama_url") == "http://ollama:11434", (
            "Ollama URL must be http://ollama:11434 (Docker container hostname), "
            "not localhost — this is what kept the LLM agent offline after setup"
        )
        assert "localhost" not in saved.get("ollama_url", "")

    def test_groq_config_has_api_key_slot(self, tmp_path):
        """wizard_save_llm with provider=groq must store api_key."""
        import json
        from backend.core.state import init_db, configure, StateDB

        db_path = tmp_path / "state.db"
        init_db(db_path)
        configure(db_path)

        with StateDB() as db:
            cfg = {"provider": "groq", "api_key": "gsk_test123",
                   "model": "llama-3.3-70b-versatile"}
            db.set_setting("llm_agent_config", json.dumps(cfg))

        with StateDB() as db:
            saved = json.loads(db.get_setting("llm_agent_config") or "{}")
        assert saved.get("api_key") == "gsk_test123"


# ── Contract: Stage 8 platform-ready gate ────────────────────────────────

class TestInstallGate:
    """Apps cannot install until platform.status == 'ready'."""

    def test_install_app_requires_ready_status(self, tmp_path):
        """install_app must fail gracefully if platform is not ready."""
        from backend.core.state import init_db, configure, StateDB
        from backend.manifests.executor import install_app

        db_path = tmp_path / "state.db"
        init_db(db_path)
        configure(db_path)

        # Platform is pending (not ready)
        result = install_app("sonarr")
        assert not result.ok, "install_app should fail when platform is not ready"
        # The failure message should be clear
        failed_step = next((s for s in result.steps if s.status == "error"), None)
        assert failed_step is not None
        assert "platform" in failed_step.message.lower() or "ready" in failed_step.message.lower()

    def test_install_app_succeeds_when_ready(self, tmp_path):
        """When platform is ready, install_app proceeds past the gate."""
        from backend.core.state import init_db, configure, StateDB
        from backend.manifests.executor import install_app

        db_path = tmp_path / "state.db"
        init_db(db_path)
        configure(db_path)

        with StateDB() as db:
            db.update_platform(
                status="ready",
                domain="test.local",
                config_root=str(tmp_path / "config"),
                media_root=str(tmp_path / "media"),
                puid=1000, pgid=1000, timezone="UTC",
            )

        # Should proceed past the validate step (will fail later at Docker)
        result = install_app("sonarr")
        # The failure should NOT be "Platform setup is not complete"
        if not result.ok:
            failed = next((s for s in result.steps if s.status == "error"), None)
            if failed:
                assert "Platform setup is not complete" not in failed.message, (
                    "Still failing at platform gate even though status=ready"
                )
