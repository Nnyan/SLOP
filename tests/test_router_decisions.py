"""Tests for backend.agent.router.decisions.log_decision persistence.

Covers:
- Row is written to router_decisions with outcome set
- Row is written without outcome (None-safe)
- Function never raises even when the DB is broken/missing
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from backend.agent.router.types import RouteDecision, Tier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(tier: Tier = Tier.SIMPLE, chain: list[str] | None = None) -> RouteDecision:
    return RouteDecision(
        tier=tier,
        chain=chain if chain is not None else ["ollama"],
        reason="test decision",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def statedb(tmp_path):
    """A fully-migrated StateDB pointed at a temp path."""
    from backend.core.state import init_db, StateDB
    db_path = tmp_path / "state.db"
    init_db(db_path)
    return StateDB


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLogDecisionPersistence:
    def test_row_written_with_outcome(self, statedb):
        """INSERT a row with all optional fields set; read it back."""
        from backend.agent.router.decisions import log_decision

        decision = _make_decision(tier=Tier.STANDARD, chain=["ollama", "openai"])
        log_decision(
            decision,
            chosen_provider="ollama",
            outcome="success",
            cost_usd=0.001,
            latency_ms=120,
        )

        with statedb() as db:
            row = db.execute(
                "SELECT * FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None
        assert row["tier"] == "STANDARD"
        assert json.loads(row["chain"]) == ["ollama", "openai"]
        assert row["chosen_provider"] == "ollama"
        assert row["outcome"] == "success"
        assert row["cost_usd"] == pytest.approx(0.001)
        assert row["latency_ms"] == 120

    def test_row_written_without_outcome(self, statedb):
        """INSERT a row with all optional fields None (dry-run / unresolved path)."""
        from backend.agent.router.decisions import log_decision

        decision = _make_decision(tier=Tier.SIMPLE, chain=["local"])
        log_decision(decision)  # no kwargs — single-arg caller

        with statedb() as db:
            row = db.execute(
                "SELECT * FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None
        assert row["tier"] == "SIMPLE"
        assert row["chosen_provider"] is None
        assert row["outcome"] is None
        assert row["cost_usd"] is None
        assert row["latency_ms"] is None

    def test_none_outcome_is_safe(self, statedb):
        """Explicit None for outcome must not raise or corrupt other fields."""
        from backend.agent.router.decisions import log_decision

        decision = _make_decision(tier=Tier.COMPLEX, chain=["openai"])
        log_decision(decision, chosen_provider="openai", outcome=None, cost_usd=0.05)

        with statedb() as db:
            row = db.execute(
                "SELECT * FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None
        assert row["outcome"] is None
        assert row["cost_usd"] == pytest.approx(0.05)

    def test_created_at_is_set(self, statedb):
        """created_at should be a positive Unix timestamp."""
        from backend.agent.router.decisions import log_decision

        log_decision(_make_decision())

        with statedb() as db:
            row = db.execute(
                "SELECT created_at FROM router_decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row is not None
        assert row["created_at"] > 0


class TestLogDecisionNeverRaises:
    def test_does_not_raise_when_db_missing(self, tmp_path, monkeypatch):
        """Point StateDB at a non-existent directory; log_decision must not raise."""
        import backend.core.state as state_mod

        # Save old path and point at a path that can't be opened
        old_path = state_mod._DB_PATH
        state_mod._DB_PATH = tmp_path / "nonexistent_dir" / "state.db"

        from backend.agent.router.decisions import log_decision

        # Must not raise
        log_decision(
            _make_decision(),
            outcome="success",
            chosen_provider="ollama",
        )

        # Restore
        state_mod._DB_PATH = old_path

    def test_does_not_raise_when_table_missing(self, tmp_path, monkeypatch):
        """Point StateDB at an empty SQLite DB (no router_decisions table)."""
        import backend.core.state as state_mod

        bare_db = tmp_path / "bare.db"
        # Create a SQLite file with NO tables
        conn = sqlite3.connect(bare_db)
        conn.close()

        old_path = state_mod._DB_PATH
        state_mod._DB_PATH = bare_db

        from backend.agent.router.decisions import log_decision

        # Must not raise even though the table doesn't exist
        log_decision(_make_decision(), outcome="all_failed")

        # Restore
        state_mod._DB_PATH = old_path

    def test_does_not_raise_when_db_path_none(self, monkeypatch):
        """Simulate StateDB not configured (_DB_PATH=None); must not raise."""
        import backend.core.state as state_mod

        old_path = state_mod._DB_PATH
        state_mod._DB_PATH = None

        from backend.agent.router.decisions import log_decision

        log_decision(_make_decision())

        state_mod._DB_PATH = old_path
