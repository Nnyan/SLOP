"""backend/agent/types.py

Shared agent type definitions.

Separated here to avoid circular imports between autofix, apply, and spine modules.
"""

from __future__ import annotations

import enum


class OperationalLevel(enum.Enum):
    """Controls how much autonomy the auto-apply pipeline exercises.

    ADVISORY:    The pipeline only reports what it *would* do — no mutations.
    SUPERVISED:  Mutations require the confirmation gate (dry_run=True by default).
                 The caller must explicitly pass dry_run=False to execute.
    AUTONOMOUS:  Gate bypassed; actions execute immediately. Only valid when
                 explicitly configured via settings (agent_operational_level=autonomous).
    """

    ADVISORY = "advisory"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"

    @classmethod
    def from_setting(cls, raw: str | None) -> OperationalLevel:
        """Parse an operational level from a settings string (case-insensitive).

        Defaults to SUPERVISED when the setting is absent or unrecognised — the
        safest non-advisory mode that still allows opt-in execution.
        """
        if raw and raw.strip().lower() in {m.value for m in cls}:
            return cls(raw.strip().lower())
        return cls.SUPERVISED


__all__ = ["OperationalLevel"]
