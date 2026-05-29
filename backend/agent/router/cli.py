"""backend.agent.router.cli — Command-line status tool for the LLM router.

Usage:
    python -m backend.agent.router status

Prints:
    1. The full provider registry (names + key ProviderSpec fields).
    2. Configured / available providers from the live llm_agent_config setting.
    3. A dry-run routing decision for a sample prompt (requires Stream B
       selector + scoring to be present; skipped gracefully if absent).

Selector and scoring are imported LAZILY (inside command bodies) so that
this module is importable when only types.py and registry.py are present
(e.g. during parallel-stream development in a worktree without Stream B).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_llm_agent_config() -> dict[str, Any]:
    """Return the llm_agent_config dict from the settings DB, or {} on any error."""
    try:
        from backend.core.state import StateDB  # noqa: PLC0415

        with StateDB() as db:
            raw = db.get_setting("llm_agent_config")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _print_registry() -> None:
    """Print every entry in PROVIDER_REGISTRY."""
    from backend.agent.router.registry import PROVIDER_REGISTRY  # noqa: PLC0415

    print("=== Provider Registry ===")
    for name, spec in sorted(PROVIDER_REGISTRY.items()):
        tiers_str = ", ".join(t.name for t in sorted(spec.tiers))
        local_str = "local" if spec.local else "cloud"
        print(
            "  {name:16s}  kind={kind}  tiers=[{tiers}]  cost_per_1k={cost:.6f}  [{locality}]".format(
                name=name,
                kind=spec.kind,
                tiers=tiers_str,
                cost=spec.cost_per_1k,
                locality=local_str,
            )
        )
    print()


def _print_available(cfg: dict[str, Any]) -> list[str]:
    """Print configured / available providers and return the list."""
    from backend.agent.router.registry import available_providers  # noqa: PLC0415

    providers = available_providers(cfg)
    print("=== Configured / Available Providers ===")
    if providers:
        for p in providers:
            print("  " + p)
    else:
        print("  (none — llm_agent_config not set or disabled)")
    print()
    return providers


def _print_dry_run(cfg: dict[str, Any], providers: list[str]) -> None:  # noqa: C901
    """Print a dry-run routing decision for a sample prompt.

    Requires backend.agent.router.selector and backend.agent.router.scoring
    (Stream B).  If either is absent the dry run is skipped with a notice.
    """
    try:
        from backend.agent.router.selector import select  # noqa: PLC0415
        from backend.agent.router.scoring import complexity_score  # noqa: PLC0415
    except ImportError:
        print("=== Dry-run Decision ===")
        print("  (skipped — selector/scoring not yet available)")
        print()
        return

    from backend.agent.router.types import RouteRequest  # noqa: PLC0415
    from backend.agent.router.decisions import log_decision  # noqa: PLC0415

    sample_prompt = (
        "Summarise the key differences between transformer and RNN architectures."
    )

    print("=== Dry-run Decision ===")
    print("  sample prompt: " + sample_prompt)

    try:
        tier = complexity_score(sample_prompt)
        req = RouteRequest(prompt=sample_prompt, max_tier=tier)
        decision = select(req, providers)
        print("  tier:   " + decision.tier.name)
        print("  chain:  " + str(decision.chain))
        print("  reason: " + decision.reason)
        log_decision(decision)
    except Exception as exc:
        print("  (dry-run failed: " + str(exc) + ")")
    print()


# ---------------------------------------------------------------------------
# Sub-command: status
# ---------------------------------------------------------------------------

def cmd_status(_args: argparse.Namespace) -> None:
    """Print registry, available providers, and a dry-run decision."""
    cfg = _fetch_llm_agent_config()
    _print_registry()
    providers = _print_available(cfg)
    _print_dry_run(cfg, providers)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.agent.router",
        description="LLM router status tool",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="Print registry, available providers, dry-run decision")

    args = parser.parse_args(argv)

    if args.command == "status":
        cmd_status(args)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
