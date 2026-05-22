"""tests/test_dead_code_removals.py — Step 3.1.c regression tests.

Each removed-dead-code item gets a test asserting the surface stays
gone (Core Rule 2.5 pairing). If a future contributor restores any
of these, the test fails — forcing them to either justify the
restoration or pick a different name.

Tracks confirmed-dead removals from the vulture phase-2 triage
(2026-05-09):

  - `COMPOSE_VERSION` in `backend/core/compose.py` — module constant
    with no callers anywhere in the repo. Compose schema version is
    a v3.8 reference that wasn't applied to the rendered fragments.
  - `ActionType` Literal alias in `backend/core/ai_safety.py` — type
    alias never referenced as a parameter / return type annotation.
    The runtime list `ACTABLE_TYPES` is the canonical surface; the
    Literal was unused documentation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_compose_version_constant_stays_removed() -> None:
    """`COMPOSE_VERSION` was an unreferenced module constant; it was
    removed in the vulture phase-2 cleanup. If something restores it,
    the contributor should also restore a real consumer."""
    from backend.core import compose
    assert not hasattr(compose, "COMPOSE_VERSION"), (
        "COMPOSE_VERSION constant was reintroduced. If you need a "
        "compose-schema-version literal in fragments, also wire up "
        "the consumer in build_service_fragment / build_traefik_fragment."
    )


def test_action_type_literal_alias_stays_removed() -> None:
    """`ActionType` Literal alias was never used as a type annotation;
    it was removed in the vulture phase-2 cleanup. The runtime list
    `ACTABLE_TYPES` is the canonical surface — extend that for new
    actions, not the dead Literal."""
    from backend.core import ai_safety
    assert not hasattr(ai_safety, "ActionType"), (
        "ActionType Literal alias was reintroduced. If you need a "
        "type alias for action names, annotate against `ACTABLE_TYPES` "
        "or define the new alias on the call site that uses it."
    )
