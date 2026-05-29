"""Tests for backend.agent.router.scoring and backend.agent.router.selector.

Covers:
- complexity_score returns each Tier for representative prompts
- determinism (same input -> same Tier)
- select caps the chosen tier at req.max_tier
- chain orders free/local before paid and by ascending cost
- tie-break is stable (by name)
- empty `available` -> empty chain with explanatory reason
- no-provider-for-tier degrade path (steps down to a lower tier)
"""

from __future__ import annotations

import pytest

from backend.agent.router.scoring import complexity_score
from backend.agent.router.selector import select
from backend.agent.router.registry import PROVIDER_REGISTRY
from backend.agent.router.types import RouteRequest, RouteDecision, Tier


# ---------------------------------------------------------------------------
# complexity_score — tier mapping
# ---------------------------------------------------------------------------

class TestComplexityScore:
    def test_empty_prompt_is_simple(self):
        assert complexity_score("") == Tier.SIMPLE

    def test_short_prompt_is_simple(self):
        assert complexity_score("hi there") == Tier.SIMPLE

    def test_medium_length_is_standard(self):
        # >= 600 chars, no other signal -> +1 -> STANDARD
        assert complexity_score("x" * 700) == Tier.STANDARD

    def test_large_length_is_complex(self):
        # >= 2000 chars -> +2 -> COMPLEX
        assert complexity_score("y" * 2100) == Tier.COMPLEX

    def test_code_block_short_is_standard(self):
        prompt = "fix this:\n```python\nprint(1)\n```"
        assert complexity_score(prompt) == Tier.STANDARD

    def test_stacktrace_is_complex(self):
        prompt = (
            "it crashed:\n"
            "Traceback (most recent call last):\n"
            '  File "app.py", line 12, in main\n'
            "ValueError: bad input"
        )
        assert complexity_score(prompt) == Tier.COMPLEX

    def test_python_file_frame_is_complex(self):
        prompt = 'something broke\n  File "/srv/x.py", line 5, in run'
        assert complexity_score(prompt) == Tier.COMPLEX

    def test_java_frame_is_complex(self):
        prompt = "error:\n  at com.example.Foo.bar(Foo.java:42)"
        assert complexity_score(prompt) == Tier.COMPLEX

    def test_lone_reasoning_keyword_is_complex(self):
        # reasoning keyword alone -> +2 -> COMPLEX (deliberate floor)
        assert complexity_score("why does this happen") == Tier.COMPLEX

    @pytest.mark.parametrize(
        "kw",
        ["why", "design", "architecture", "compare", "trade-off",
         "root cause", "explain", "evaluate", "justify"],
    )
    def test_each_reasoning_keyword_lifts_at_least_to_complex(self, kw):
        assert complexity_score(f"please {kw} this") >= Tier.COMPLEX

    def test_reasoning_plus_length_is_reasoning(self):
        # reasoning (+2) + large length (+2) = 4 -> REASONING
        assert complexity_score("why " + "x" * 2100) == Tier.REASONING

    def test_reasoning_plus_stacktrace_is_reasoning(self):
        prompt = (
            "explain why this fails\n"
            "Traceback (most recent call last):\n"
            '  File "a.py", line 3, in <module>'
        )
        assert complexity_score(prompt) == Tier.REASONING

    def test_reasoning_keyword_word_boundary(self):
        # "whyever" should NOT match the keyword "why"
        assert complexity_score("whyever notwithstanding") == Tier.SIMPLE

    def test_all_four_tiers_reachable(self):
        results = {
            complexity_score("hi"),
            complexity_score("x" * 700),
            complexity_score("y" * 2100),
            complexity_score("why " + "x" * 2100),
        }
        assert results == {Tier.SIMPLE, Tier.STANDARD, Tier.COMPLEX, Tier.REASONING}


# ---------------------------------------------------------------------------
# complexity_score — determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.parametrize(
        "prompt",
        [
            "hi",
            "x" * 700,
            "y" * 2100,
            "explain why\nTraceback (most recent call last):",
            "```python\nprint('hello world')\n```",
        ],
    )
    def test_same_input_same_tier(self, prompt):
        first = complexity_score(prompt)
        for _ in range(10):
            assert complexity_score(prompt) == first


# ---------------------------------------------------------------------------
# select — tier cap
# ---------------------------------------------------------------------------

class TestSelectTierCap:
    def test_caps_at_max_tier(self):
        # A REASONING-scored prompt capped at STANDARD must select STANDARD.
        prompt = "why " + "x" * 2100  # scores REASONING
        assert complexity_score(prompt) == Tier.REASONING
        req = RouteRequest(prompt=prompt, max_tier=Tier.STANDARD)
        dec = select(req, ["ollama", "groq"])
        assert dec.tier == Tier.STANDARD
        assert "capped" in dec.reason.lower()

    def test_no_cap_when_below_max(self):
        req = RouteRequest(prompt="hi", max_tier=Tier.REASONING)
        dec = select(req, ["ollama"])
        assert dec.tier == Tier.SIMPLE
        assert "capped" not in dec.reason.lower()

    def test_cap_equal_to_score_not_marked_capped(self):
        prompt = "why does it fail"  # COMPLEX
        assert complexity_score(prompt) == Tier.COMPLEX
        req = RouteRequest(prompt=prompt, max_tier=Tier.COMPLEX)
        dec = select(req, ["ollama"])
        assert dec.tier == Tier.COMPLEX
        assert "capped" not in dec.reason.lower()


# ---------------------------------------------------------------------------
# select — chain ordering
# ---------------------------------------------------------------------------

class TestChainOrdering:
    def test_free_and_local_before_paid(self):
        # STANDARD tier; ollama (local,0) + openrouter (cloud,0) are free;
        # cohere/openai/groq are paid.
        avail = ["groq", "cohere", "openai", "openrouter", "ollama"]
        req = RouteRequest(prompt="x" * 700, max_tier=Tier.STANDARD)
        dec = select(req, avail)
        # First entries must be the free/local ones.
        free = [n for n in dec.chain if PROVIDER_REGISTRY[n].local or PROVIDER_REGISTRY[n].cost_per_1k == 0.0]
        paid = [n for n in dec.chain if n not in free]
        # All free providers come before any paid provider.
        first_paid_idx = min((dec.chain.index(p) for p in paid), default=len(dec.chain))
        last_free_idx = max((dec.chain.index(f) for f in free), default=-1)
        assert last_free_idx < first_paid_idx

    def test_paid_ordered_by_ascending_cost(self):
        avail = ["groq", "cohere", "openai"]  # all paid STANDARD-capable
        req = RouteRequest(prompt="x" * 700, max_tier=Tier.STANDARD)
        dec = select(req, avail)
        costs = [PROVIDER_REGISTRY[n].cost_per_1k for n in dec.chain]
        assert costs == sorted(costs)
        # Specifically: cohere(0.00015) < openai(0.0006) < groq(0.00079)
        assert dec.chain == ["cohere", "openai", "groq"]

    def test_free_tie_break_by_name(self):
        # Two zero-cost providers: ollama (local) and openrouter (cloud, 0.0).
        # Both bucket 0, both cost 0.0 -> tie-break by name -> ollama < openrouter.
        avail = ["openrouter", "ollama"]
        req = RouteRequest(prompt="x" * 700, max_tier=Tier.STANDARD)
        dec = select(req, avail)
        assert dec.chain == ["ollama", "openrouter"]

    def test_order_independent_of_input_order(self):
        a = select(RouteRequest(prompt="x" * 700, max_tier=Tier.STANDARD),
                   ["groq", "cohere", "openai"])
        b = select(RouteRequest(prompt="x" * 700, max_tier=Tier.STANDARD),
                   ["openai", "groq", "cohere"])
        assert a.chain == b.chain

    def test_only_providers_serving_tier_included(self):
        # cohere does not serve COMPLEX; at COMPLEX it must be excluded.
        assert Tier.COMPLEX not in PROVIDER_REGISTRY["cohere"].tiers
        req = RouteRequest(prompt="why does it fail", max_tier=Tier.COMPLEX)  # COMPLEX
        dec = select(req, ["cohere", "groq"])
        assert "cohere" not in dec.chain
        assert "groq" in dec.chain

    def test_unknown_name_ignored(self):
        req = RouteRequest(prompt="hi", max_tier=Tier.SIMPLE)
        dec = select(req, ["ollama", "does_not_exist"])
        assert "does_not_exist" not in dec.chain
        assert "ollama" in dec.chain

    def test_duplicates_collapsed(self):
        req = RouteRequest(prompt="hi", max_tier=Tier.SIMPLE)
        dec = select(req, ["ollama", "ollama", "groq", "groq"])
        assert len(dec.chain) == len(set(dec.chain))


# ---------------------------------------------------------------------------
# select — empty / degrade
# ---------------------------------------------------------------------------

class TestSelectDegrade:
    def test_empty_available_empty_chain(self):
        dec = select(RouteRequest(prompt="hi"), [])
        assert dec.chain == []
        assert "no available provider" in dec.reason.lower()

    def test_no_provider_for_tier_degrades(self):
        # anthropic serves only COMPLEX/REASONING. A COMPLEX request where the
        # only provider is one that also serves a lower tier should degrade.
        # Use ollama (SIMPLE/STANDARD/COMPLEX) at a high tier we can't fully
        # serve to force a degrade: pick a REASONING request, only ollama avail.
        prompt = "why " + "x" * 2100  # REASONING
        assert complexity_score(prompt) == Tier.REASONING
        req = RouteRequest(prompt=prompt, max_tier=Tier.REASONING)
        dec = select(req, ["ollama"])  # ollama tops out at COMPLEX
        assert dec.tier == Tier.COMPLEX
        assert dec.chain == ["ollama"]
        assert "degraded" in dec.reason.lower()

    def test_degrade_returns_empty_when_nothing_serves_any_lower_tier(self):
        # anthropic only serves COMPLEX/REASONING; capped at SIMPLE there is
        # nothing at SIMPLE and we never escalate above the cap -> empty.
        req = RouteRequest(prompt="hi", max_tier=Tier.SIMPLE)
        dec = select(req, ["anthropic"])
        assert dec.tier == Tier.SIMPLE
        assert dec.chain == []
        assert "no available provider" in dec.reason.lower()

    def test_decision_is_routedecision(self):
        dec = select(RouteRequest(prompt="hi"), ["ollama"])
        assert isinstance(dec, RouteDecision)
        assert isinstance(dec.chain, list)
        assert isinstance(dec.reason, str)

    def test_select_deterministic(self):
        req = RouteRequest(prompt="x" * 700, max_tier=Tier.STANDARD)
        avail = ["groq", "cohere", "openai", "ollama", "openrouter"]
        first = select(req, avail)
        for _ in range(5):
            d = select(req, list(avail))
            assert d.tier == first.tier
            assert d.chain == first.chain
            assert d.reason == first.reason
