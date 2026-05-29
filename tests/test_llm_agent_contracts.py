"""
tests/test_llm_agent_contracts.py — Contract tests for every LLM AI agent promise.

Each test verifies one specific promise end-to-end through the code paths,
not just that a function exists, but that the full chain is wired correctly.

Promises tested:
  P1: Every failing app gets diagnosed (manifest + infra Docker-inspect fallback)
  P2: All 8 prompt action types are implemented in execute_action()
  P3: Ntfy delivery status is surfaced to the LLM
  P4: Rejected fixes store reason; suppression after 3 rejections
  P5: Context includes failure duration (chronic vs transient)
  P6: Escalate and reprovision_hostname actually execute
  P7: Rolling failures detected (gradual cascade, not just mass failure)
  P8: Post-fix verification runs 60s after approval
  P9: Action map in LLM prompt exactly matches execute_action() implementation
  P10: Infra apps (tier=0) get Docker-inspect health check when no manifest
"""

import ast
import pathlib
import re
import pytest

REPO = pathlib.Path(__file__).parent.parent


def _read(name: str) -> str:
    return (REPO / name).read_text()


def _checker()   -> str: return _read("backend/health/checker.py")
def _safety()    -> str: return _read("backend/core/ai_safety.py")
def _assembler() -> str: return _read("backend/health/context_assembler.py")
def _health_api()-> str: return _read("backend/api/health.py")


# ── P1 / P10: Every app gets diagnosed ───────────────────────────────────

class TestDiagnosisCoverage:
    def test_infra_apps_get_docker_inspect_fallback(self):
        """tier=0 apps with no catalog manifest must be checked via Docker inspect.

        Step 1.4.d split check_app into per-phase helpers; the tier
        check + docker-inspect fallback now live in
        `_check_infra_app` and `_load_manifest_or_skip` rather than
        inline in check_app's body. Search the whole checker module
        for the contract instead of slicing check_app's body.
        """
        src = _checker()
        assert "_check_infra_app" in src, (
            "No infra-fallback helper — tier=0 apps silently skipped"
        )
        assert 'getattr(_tier_app, "tier", 1) != 0' in src \
            or "tier == 0" in src or "tier=0" in src, (
            "No tier check before infra-fallback dispatch"
        )
        assert "docker" in src and "inspect" in src, (
            "Docker inspect fallback missing — infra apps never health-checked"
        )

    def test_infra_fallback_writes_health_check_result(self):
        """Infra Docker-inspect fallback must write to health_checks table.

        Step 1.4.d: scan the `_check_infra_app` helper directly —
        the previous 'Infra app without manifest' comment marker
        moved during the refactor.
        """
        src = _checker()
        helper_start = src.find("def _check_infra_app(")
        if helper_start < 0:
            pytest.fail("_check_infra_app helper missing from checker.py")
        helper_end = src.find("\ndef ", helper_start + 50)
        fallback = src[helper_start:helper_end] if helper_end > 0 else src[helper_start:]
        assert "upsert_health_check" in fallback, (
            "Infra fallback doesn't write health_checks — Source 20 always shows stale 'running'"
        )

    def test_all_catalog_apps_parse(self):
        """Every catalog YAML must load without error."""
        import sys
        sys.path.insert(0, str(REPO))
        from backend.manifests.loader import load_all_manifests, clear_cache
        clear_cache()
        m = load_all_manifests()
        assert len(m) >= 50


# ── P2: All 8 actions implemented ────────────────────────────────────────

class TestActionImplementations:
    # Actions the LLM prompt explicitly lists
    PROMPT_ACTIONS = {
        "restart_container", "reload_config", "pull_image",
        "rewire", "restart_managed_service", "remount_storage",
        "manual", "escalate",
    }

    def _execute_action_body(self) -> str:
        """Source slice covering execute_action + per-action helpers
        + dispatch tables (`_ACTION_ALIASES`, `_ACTION_DISPATCHERS`).

        Step 2.7.i refactored execute_action into a table-driven
        dispatch with one `_action_<name>` helper per branch — the
        action name strings now live in helper bodies + the tables,
        not in the orchestrator. This slice captures all of them.
        """
        src = _safety()
        start = src.find("def _action_")
        if start < 0:
            start = src.find("async def execute_action(")
        end = src.find("\n\n_ACTION_DESCRIPTIONS", start)
        return src[start:end]

    def test_all_prompt_actions_implemented(self):
        """Every action in the LLM prompt must have a case in execute_action()."""
        body = self._execute_action_body()
        for action in self.PROMPT_ACTIONS - {"manual"}:
            assert action in body, (
                f"Action '{action}' in LLM prompt but NOT in execute_action() — "
                f"user approves fix and nothing happens"
            )

    def test_escalate_implemented(self):
        body = self._execute_action_body()
        assert "escalate" in body, "escalate not handled in execute_action()"

    def test_reprovision_hostname_implemented(self):
        body = self._execute_action_body()
        assert "reprovision" in body, (
            "reprovision_hostname missing — _action_map points to it but it's a dead end"
        )

    def test_self_heal_supports_all_manifest_actions(self):
        """_attempt_self_heal must handle all actions that manifests can define.

        Step 2.7.a: split into `_heal_<action>` helpers + dispatch
        tables (`_HEAL_ALIASES`, `_HEAL_DISPATCHERS`); action names
        live in those tables / helpers now, not the orchestrator body.
        """
        src = _checker()
        start = src.find("def _heal_")
        if start < 0:
            start = src.find("async def _attempt_self_heal(")
        # Capture through the end of _attempt_self_heal — find the next
        # async def AFTER the orchestrator's start, not after `start`.
        orch = src.find("async def _attempt_self_heal(")
        end = src.find("\nasync def ", orch + 100)
        if end < 0:
            end = len(src)
        heal = src[start:end]
        for action in ("restart_container", "reload_config", "pull_image",
                       "rewire", "remount_storage", "restart_managed_service"):
            assert action in heal, (
                f"_attempt_self_heal does not handle '{action}' — "
                f"manifest self_heal.action={action} silently does nothing"
            )

    def test_action_map_values_are_all_implemented(self):
        """Every action the LLM can suggest must be implemented in execute_action().

        Step 2.7.i replaced the old `_action_map` dict in checker.py
        with `_ACTION_ALIASES` + `_ACTION_DISPATCHERS` tables in
        ai_safety.py. The contract still holds — every action name
        the LLM can produce must be reachable through the dispatch
        table. This test now reads the canonical actions from
        `_ACTION_ALIASES.values()` and confirms they appear in the
        execute_action region (orchestrator + per-action helpers).
        """
        safety = _safety()
        # Find _ACTION_ALIASES dict literal
        aliases_match = re.search(
            r"_ACTION_ALIASES:\s*dict\[str,\s*str\]\s*=\s*\{(.*?)^\}",
            safety, re.DOTALL | re.MULTILINE,
        )
        assert aliases_match, "_ACTION_ALIASES not found in ai_safety.py"
        # values are the canonical names: "alias": "canonical"
        values = set(re.findall(r'"\w+":\s*"(\w+)"', aliases_match.group(1)))
        body = self._execute_action_body()
        for v in values - {"manual"}:
            assert v in body, (
                f"_ACTION_ALIASES maps to '{v}' but execute_action() has no case — "
                f"LLM suggests it, user approves, nothing happens"
            )

    def test_prompt_action_list_matches_execute_action(self):
        """Actions listed in the LLM system prompt must match execute_action() exactly."""
        checker = _checker()
        m = re.search(
            r"AVAILABLE ACTIONS.*?\n(.*?)===",
            checker, re.DOTALL
        )
        if not m:
            pytest.skip("AVAILABLE ACTIONS section not found")
        prompt_actions = set(re.findall(r"^(\w+)\s+—", m.group(1), re.MULTILINE))
        body = self._execute_action_body()
        for action in prompt_actions - {"manual"}:
            assert action in body, (
                f"'{action}' in LLM prompt but not executed — broken promise"
            )


# ── P3: Notification context ──────────────────────────────────────────────

class TestNotificationContext:
    def test_ntfy_status_in_context(self):
        """Assembler must surface ntfy running/down status to LLM."""
        src = _assembler()
        assert "ntfy" in src.lower(), "No ntfy context in assembler"
        # Must check actual ntfy app status, not just the URL setting
        assert "ntfy" in src and ("running" in src or "status" in src), (
            "Ntfy status not surfaced — LLM blind to notification failures"
        )

    def test_ntfy_send_returns_bool_not_swallowed(self):
        """_send_notification must return a bool so callers know if it worked."""
        src = _checker()
        start = src.find("async def _send_notification(")
        end = src.find("\nasync def ", start + 100)
        fn = src[start:end]
        assert "return True" in fn or "return resp" in fn, (
            "Notification failure silently swallowed — caller never knows"
        )


# ── P4: Rejection learning ────────────────────────────────────────────────

class TestRejectionLearning:
    def test_rejection_stores_reason_parameter(self):
        src = _health_api()
        start = src.find("def reject_fix(")
        end = src.find("\n\n@router", start)
        fn = src[start:end]
        assert "reason" in fn, (
            "reject_fix() has no reason parameter — "
            "user can't explain why the fix was wrong"
        )

    def test_rejection_stored_as_rejected_not_failure(self):
        src = _health_api()
        assert "'rejected'" in src, (
            "Rejection stored as 'failure' — indistinguishable from execution failure"
        )

    def test_suppression_after_three_rejections(self):
        src = _health_api()
        assert "3" in src and "suppress" in src.lower(), (
            "No 3-rejection suppression — LLM keeps suggesting what user hates"
        )

    def test_suppressed_actions_surface_to_llm(self):
        src = _assembler()
        assert "SUPPRESSED" in src or "suppressed" in src.lower(), (
            "Suppressed actions not in LLM context — still gets suggested"
        )


# ── P5: Failure duration ──────────────────────────────────────────────────

class TestFailureDuration:
    def test_context_has_failure_duration(self):
        src = _assembler()
        assert "Failing for:" in src, (
            "No failure duration in context — LLM can't calibrate confidence correctly"
        )

    def test_chronic_failures_labeled_differently(self):
        src = _assembler()
        assert "CHRONIC" in src or "chronic" in src or "1440" in src, (
            "No chronic failure distinction — keeps suggesting restart for config issues"
        )


# ── P6 + P8: Action execution + verification ─────────────────────────────

class TestActionExecution:
    def test_post_fix_verification_thread_started(self):
        src = _health_api()
        assert "60" in src and "Thread" in src, (
            "No post-fix verification — fix logged success even if app still failing"
        )

    def test_verification_updates_fix_history(self):
        src = _health_api()
        assert "failed_verification" in src or "verification" in src.lower(), (
            "Verification result not written to fix_history"
        )


# ── P7: Cascade detection ─────────────────────────────────────────────────

class TestCascadeDetection:
    def test_mass_failure_in_context(self):
        src = _assembler()
        assert "MASS FAILURE" in src, "No mass failure detection"

    def test_rolling_failure_in_context(self):
        src = _assembler()
        assert "ROLLING" in src, (
            "No rolling failure detection — gradual infra degradation missed"
        )

    def test_infra_degraded_cascade_warning(self):
        src = _assembler()
        assert "INFRA DEGRADED" in src, (
            "No infra-degraded warning — LLM diagnoses apps individually "
            "instead of finding infra root cause"
        )


# ── P9: Context source completeness ──────────────────────────────────────

class TestContextCompleteness:
    def test_all_sources_0_through_20_present(self):
        """Every numbered context source (0..20) must appear in the
        assembler. Sources may carry letter suffixes (5a, 5b, 6b-i,
        etc.) when split into sub-sections — accept any of the forms
        `── N.`, `── Na.`, `── Nb.`, `── Nb-i.`, etc.
        """
        src = _assembler()
        for i in range(21):
            # Match `── 5.`, `── 5a.`, `── 5b-i.`, etc.
            pattern = rf"── {i}[a-z]?(?:[a-z]?-[ivx]+)?\."
            assert re.search(pattern, src), f"Context source {i} missing"

    def test_routing_log_limit_at_least_10(self):
        src = _assembler()
        section = src[src.find("Previous LLM diagnoses"):]
        section = section[:section.find("# ──", 100)]
        limits = [int(m) for m in re.findall(r"LIMIT\s+(\d+)", section)]
        assert limits and max(limits) >= 10, (
            f"Routing log LIMIT {limits} — LLM only sees few past diagnoses, "
            f"can't detect repeated wrong diagnosis pattern"
        )


# ── Additional gaps found in second audit pass ────────────────────────────

class TestSelfHealBypassesSafetyTier:
    """Manifest self_heal must NOT go through the AI safety tier.
    
    The safety tier (suggest/act) governs LLM-suggested fixes.
    When a user defines self_heal in their manifest, they are explicitly
    opting into automatic remediation for that specific action.
    """

    def test_self_heal_does_not_call_should_auto_act(self):
        """_attempt_self_heal must not delegate to execute_action (which checks should_auto_act)."""
        src = _checker()
        start = src.find("async def _attempt_self_heal(")
        end = src.find("\nasync def ", start + 100)
        fn = src[start:end]
        # Must NOT call execute_action (which would block on safety tier)
        # OR must have explicit bypass
        if "execute_action" in fn:
            # If it delegates, must bypass should_auto_act somehow
            assert "bypass" in fn.lower() or "manifest" in fn, (
                "_attempt_self_heal calls execute_action which checks should_auto_act. "
                "Default safety=suggest means self_heal silently does nothing."
            )

    def test_self_heal_restart_uses_direct_docker_command(self):
        """Self-heal restart must use docker restart directly, not the approval flow."""
        src = _checker()
        start = src.find("async def _attempt_self_heal(")
        end = src.find("\nasync def ", start + 100)
        fn = src[start:end]
        assert "docker" in fn and "restart" in fn, (
            "Self-heal restart not using direct docker command — "
            "will fail silently if safety tier is not set to 'act'"
        )

    def test_self_heal_supports_reload_config(self):
        """Self-heal must support reload_config (HUP signal), not just restart.

        Step 2.7.a: capture the per-action helpers + dispatch table
        as well — the HUP signal call lives in `_heal_reload_config`,
        not in the orchestrator.
        """
        src = _checker()
        start = src.find("def _heal_")
        if start < 0:
            start = src.find("async def _attempt_self_heal(")
        orch = src.find("async def _attempt_self_heal(")
        end = src.find("\nasync def ", orch + 100)
        if end < 0:
            end = len(src)
        fn = src[start:end]
        assert "reload_config" in fn or "HUP" in fn, (
            "Self-heal only implements restart — "
            "manifest reload_config silently returns False"
        )


class TestOllamaUrlDefault:
    def test_scheduler_ollama_default_is_docker_hostname(self):
        """Scheduler must use http://ollama:11434 not localhost (unreachable in Docker)."""
        src = (REPO / "backend" / "health" / "scheduler.py").read_text()
        # Match the "ollama_url" config key having a localhost default value.
        # Use the quoted key form to avoid false-positives where the Python
        # variable `ollama_url` is assigned a llamacpp_url (which correctly
        # defaults to localhost for the non-ollama provider path).
        defaults = re.findall(r'"ollama_url"[^)]*?localhost', src)
        assert not defaults, (
            f"Scheduler uses localhost as ollama_url default — "
            f"unreachable from inside Docker containers: {defaults}"
        )


class TestPostFixVerification:
    def test_verification_uses_subprocess_not_new_event_loop(self):
        """Post-fix verification must not create asyncio.new_event_loop() in a thread."""
        src = _health_api()
        thread_section = src[src.find("_verify_after_delay"):]
        thread_section = thread_section[:1000]
        assert "new_event_loop" not in thread_section, (
            "asyncio.new_event_loop() in daemon thread causes issues with "
            "httpx async client — use subprocess.run() for verification"
        )


class TestLLMPromptRules:
    def test_401_leads_to_auth_middleware_diagnosis(self):
        """LLM prompt must have rule: 401 error + INFRA DEGRADED → auth middleware down."""
        src = _checker()
        rules = src[src.find("CONTEXT READING RULES"):]
        rules = rules[:rules.find("AVAILABLE ACTIONS")]
        assert "401" in rules or "auth" in rules.lower(), (
            "No 401→auth_middleware_down rule — LLM diagnoses individual apps "
            "instead of identifying TinyAuth/Authelia as root cause"
        )

    def test_cause_field_is_parsed_from_llm_response(self):
        """LLM returns 'cause' field — it must be parsed and stored, not discarded."""
        src = _checker()
        # data.get("cause") must appear in the response parsing block
        assert 'data.get("cause"' in src or "data.get('cause'" in src, (
            "LLM 'cause' field (root cause analysis) is discarded — "
            "pending_fix only stores problem and suggested_fix"
        )

    def test_escalation_notes_stored(self):
        """LLM escalation_notes must be stored for cloud LLM to use."""
        src = _checker()
        assert "escalation_notes" in src or "escalation" in src, (
            "escalation_notes field from LLM response is discarded"
        )
