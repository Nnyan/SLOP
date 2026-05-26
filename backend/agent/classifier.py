"""backend/agent/classifier.py

Offline error classifier for the LLM agent pipeline (Phase B).

Provides two pure functions — no DB calls, no I/O, no side effects:

  classify_offline(error_text) → ErrorClass
      Iterates DETECTION_PATTERNS in priority order.  Returns the first
      class whose any pattern matches the error text (case-insensitive).
      Falls back to ErrorClass.UNKNOWN if nothing matches.

  compute_signature_hash(error_class, error_text, app_key) → str (SHA1 hex)
      Normalises error_text (strip digits, UUIDs, hex container IDs,
      filesystem paths, ISO-8601 timestamps) then hashes the triple
      ``"<class>:<normalised>:<app_key>"``.  Used by Phase C for the
      pattern-library lookup.  Implemented here so the hash is consistent
      across phases; Phase C adds the DB SELECT that uses it.

Usage:
    from backend.agent.classifier import classify_offline, compute_signature_hash
"""
from __future__ import annotations

import hashlib
import re

from backend.agent.taxonomy import DETECTION_PATTERNS, ErrorClass

# ---------------------------------------------------------------------------
# Internal normalisation patterns
# ---------------------------------------------------------------------------

# ISO-8601 timestamps: 2024-01-23T12:34:56[.fractional][Z or ±hh:mm]
_RE_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
)
# Filesystem paths (any token starting with /)
_RE_PATH = re.compile(r"/\S+")
# Long hex strings ≥8 chars (container IDs, SHAs, UUIDs without dashes)
_RE_HEX = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)
# UUIDs with dashes
_RE_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
# Standalone integers / decimal numbers
_RE_DIGITS = re.compile(r"\b\d+\b")

# Pre-compiled per-class patterns for classify_offline (case-insensitive)
_COMPILED: list[tuple[ErrorClass, list[re.Pattern[str]]]] = [
    (
        error_class,
        [re.compile(pat, re.IGNORECASE) for pat in patterns],
    )
    for error_class, patterns in DETECTION_PATTERNS.items()
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_offline(error_text: str) -> ErrorClass:
    """Return the best-match ErrorClass for *error_text* using regex patterns.

    Iterates DETECTION_PATTERNS in priority order (IMAGE_PULL_FAIL first,
    UNKNOWN last).  Returns the first class whose any pattern produces a
    match.  UNKNOWN is the guaranteed fallback because its pattern list is
    empty and it appears last.

    Args:
        error_text: Raw error string from a failing install step (may be
                    multi-line).

    Returns:
        The matched ErrorClass (never None).
    """
    for error_class, compiled_patterns in _COMPILED:
        for pattern in compiled_patterns:
            if pattern.search(error_text):
                return error_class
    # Explicit fallback (also reached naturally if UNKNOWN list is empty)
    return ErrorClass.UNKNOWN


def compute_signature_hash(
    error_class: ErrorClass,
    error_text: str,
    app_key: str,
) -> str:
    """Compute a stable SHA1 hex digest for a (class, error, app) triple.

    Normalisation strips the volatile parts of *error_text* so that two
    occurrences of "the same problem" on the same app produce the same
    hash even if container IDs, line numbers, or timestamps differ.

    Normalisation order (applied sequentially):
      1. ISO-8601 timestamps
      2. Filesystem paths (token starting with /)
      3. UUIDs (with dashes)
      4. Long hex strings ≥8 chars
      5. Standalone digit sequences

    After stripping, whitespace is collapsed to single spaces and the
    result is lowercased before hashing.

    Args:
        error_class: The classified ErrorClass value.
        error_text:  Raw error string (may be multi-line).
        app_key:     Catalog key of the failing app (e.g. ``"sonarr"``).

    Returns:
        40-character lowercase SHA1 hex string.
    """
    normalised = error_text
    normalised = _RE_TIMESTAMP.sub(" ", normalised)
    normalised = _RE_PATH.sub(" ", normalised)
    normalised = _RE_UUID.sub(" ", normalised)
    normalised = _RE_HEX.sub(" ", normalised)
    normalised = _RE_DIGITS.sub(" ", normalised)
    # Collapse whitespace and lowercase
    normalised = " ".join(normalised.split()).lower()

    payload = error_class.value + ":" + normalised + ":" + app_key
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
