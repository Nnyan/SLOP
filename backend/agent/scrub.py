"""backend/agent/scrub.py — Outbound LLM identifier redaction.

Scrubs SLOP-internal identifiers from text before it is sent to an external
(cloud) LLM provider.  All replacements are deterministic, order-stable, and
idempotent: scrub(scrub(x)) == scrub(x).

Public API
----------
scrub(text, *, profile="cloud") -> str
is_external(provider) -> bool
"""
from __future__ import annotations

import re

from backend.core.agent import _CLOUD_PROVIDERS  # noqa: WPS436 — deliberate internal import

# ---------------------------------------------------------------------------
# Placeholder tokens — chosen to be syntactically impossible as real values
# so re-matching is safe (idempotency).
# ---------------------------------------------------------------------------
_PH_SECRET = "<SECRET>"
_PH_PATH   = "<PATH>"
_PH_APP    = "<APP>"
_PH_IP     = "<IP>"
_PH_USER   = "<USER>"

# ---------------------------------------------------------------------------
# Pre-compiled patterns — applied in ORDER (most-destructive first so a
# secret embedded in a path doesn't partially survive).
#
# 1. Secrets / bearer tokens   — must go first (widest risk)
# 2. Absolute SLOP paths       — before usernames so /opt/mediastack/…
#                                doesn't leave the literal "mediastack"
# 3. Container names           — mediastack-<app>-<n>
# 4. IPv6 literals             — before IPv4 (IPv4-mapped ::ffff: forms)
# 5. IPv4 literals
# 6. Internal usernames        — narrowest; only bare words after path/IP gone
# ---------------------------------------------------------------------------

# 1. Bearer / API-key-like tokens:
#    "Bearer <token>", "Authorization: Bearer <token>", api_key="sk-…", etc.
#    Matches typical base64url / hex / sk-style tokens of 20+ chars.
_RE_SECRET = re.compile(
    r"""
    (?:
        (?:Bearer|bearer)\s+[A-Za-z0-9\-_\.~+/]{20,}(?:={0,2})  # HTTP Bearer
      | (?:api[_\-]?key|apikey|token|secret|password|Authorization)  # labelled
        \s*[=:]\s*
        ["\']?[A-Za-z0-9\-_\.~+/!@#$%^&*]{20,}["\']?
      | \bsk-[A-Za-z0-9]{20,}                                     # OpenAI-style
      | \bghp_[A-Za-z0-9]{36,}                                    # GitHub PAT
    )
    """,
    re.VERBOSE,
)

# 2. Absolute SLOP-related paths — /opt/..., /var/lib/..., /srv/..., /home/...
#    Match the full path token (up to a whitespace/quote/comma/newline).
_RE_PATH = re.compile(
    r"""
    /(?:opt|var/lib|srv|home)/\S*  # absolute path starting with known prefixes
    """,
    re.VERBOSE,
)

# 3. Docker container names: mediastack-<anything>-<digits>
_RE_APP = re.compile(r"\bmediastack-[a-zA-Z0-9_\-]+-\d+\b")

# 4. IPv6 — full form, compressed form, and IPv4-mapped (must precede IPv4)
_RE_IPV6 = re.compile(
    r"""
    (?<![:\w])          # negative lookbehind: not already part of a word/colon
    (?:
        # Full 8-group
        [0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){7}
      | # Compressed (contains ::)
        (?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}
    )
    (?![:\w])           # negative lookahead
    """,
    re.VERBOSE,
)

# 5. IPv4 — dotted-quad, optional :port
_RE_IPV4 = re.compile(
    r"""
    \b
    (?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}
    (?:25[0-5]|2[0-4]\d|[01]?\d\d?)
    (?::\d{1,5})?       # optional port
    \b
    """,
    re.VERBOSE,
)

# 6. Internal usernames — only the bare words "mediastack" or "stack"
#    Word-boundary anchored so "mediastack-foo" (already gone as APP/PATH) won't
#    create a spurious match; we still guard with \b.
_RE_USER = re.compile(r"\b(?:mediastack|stack)\b")

# Ordered list of (pattern, replacement) — idempotency relies on placeholders
# not matching any of these patterns.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (_RE_SECRET, _PH_SECRET),
    (_RE_PATH,   _PH_PATH),
    (_RE_APP,    _PH_APP),
    (_RE_IPV6,   _PH_IP),
    (_RE_IPV4,   _PH_IP),
    (_RE_USER,   _PH_USER),
]


def scrub(text: str, *, profile: str = "cloud") -> str:
    """Redact SLOP-internal identifiers from text bound for an external LLM.

    Redacts -> stable placeholders:
      absolute paths (/opt/mediastack, /var/lib/mediastack, /srv/...)  -> <PATH>
      container names (mediastack-<app>-<n>)                           -> <APP>
      IPv4 / IPv6 literals                                             -> <IP>
      internal usernames (mediastack, stack)                           -> <USER>
      bearer/API-key-like tokens                                       -> <SECRET>

    Pure, deterministic, idempotent. profile='local' returns text unchanged.
    None-safe: scrub(None) returns "".
    """
    if text is None:
        return ""
    if not text:
        return text
    if profile == "local":
        return text

    result = text
    for pattern, placeholder in _RULES:
        result = pattern.sub(placeholder, result)
    return result


def is_external(provider: str) -> bool:
    """True iff provider is in the cloud set (sourced from core.agent)."""
    return (provider or "").strip().lower() in _CLOUD_PROVIDERS
