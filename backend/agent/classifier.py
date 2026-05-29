"""backend/agent/classifier.py

Error classifier for the LLM agent pipeline (Phase B/C).

Public API:

  classify_offline(error_text) → ErrorClass
      Iterates DETECTION_PATTERNS in priority order.  Returns the first
      class whose any pattern matches the error text (case-insensitive).
      Falls back to ErrorClass.UNKNOWN if nothing matches.

  compute_signature_hash(error_class, error_text, app_key) → str (SHA1 hex)
      Normalises error_text (strip digits, UUIDs, hex container IDs,
      filesystem paths, ISO-8601 timestamps) then hashes the triple
      ``"<class>:<normalised>:<app_key>"``.  Stable lookup key for the
      pattern-library cache in fix_history.

  classify_with_llm(error_text, app_key, db_path) → Coroutine[tuple[ErrorClass, str, float]]
      Three-step fallback: pattern-library hit → offline classifier → LLM call.
      Gracefully degrades to (offline_class, "", 0.4) when LLM is unreachable.
      Added in Phase C.

Usage:
    from backend.agent.classifier import classify_offline, compute_signature_hash
    from backend.agent.classifier import classify_with_llm
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


# ---------------------------------------------------------------------------
# Phase C: LLM-enriched classifier
# ---------------------------------------------------------------------------


async def _query_llm_for_diagnosis(prompt: str) -> str | None:
    """Call the configured LLM backend with *prompt*. Returns raw text or None.

    Uses the same provider abstraction (ollama / cloud / openai-compatible) as
    the existing health checker.  All exceptions are swallowed — returns None
    if the LLM is unreachable, misconfigured, or times out.

    Deferred imports prevent circular-import issues with ``backend.core.state``
    and ``backend.health.checker``.
    """
    try:
        import json as _json
        import httpx
        from backend.core.state import StateDB
        from backend.health.checker import _load_provider_config
        from backend.agent.router.dispatch import route_and_dispatch

        provider, api_key, model, cloud_providers = _load_provider_config()

        with StateDB() as _db:
            cfg_raw = _db.get_setting("llm_agent_config")
        cfg = _json.loads(cfg_raw) if cfg_raw else {}
        if provider == "llamacpp":
            base_url = cfg.get("llamacpp_url", "http://localhost:8081")
        else:
            base_url = cfg.get("ollama_url", "http://localhost:11434")
        if not model:
            model = cfg.get("ollama_model", "phi4-mini")

        async with httpx.AsyncClient(timeout=30) as client:
            # route_and_dispatch routes every per-provider call through
            # _dispatch_llm_call (scrub preserved) and degrades to the legacy
            # single-provider path on empty chain / router error. Returns ''
            # on all-failed; preserve today's None-on-failure semantics.
            raw = await route_and_dispatch(
                client, prompt, cfg,
                ollama_url=base_url, model=model, api_key=api_key,
                cloud_providers=cloud_providers,
            )
            return raw if raw else None
    except Exception:
        return None


async def classify_with_llm(
    error_text: str,
    app_key: str,
    db_path: str,
) -> tuple[ErrorClass, str, float]:
    """Classify *error_text* using a three-step fallback strategy.

    Returns ``(error_class, suggested_fix, confidence)`` where:
    - ``confidence=0.95``  — pattern-library exact-hash hit (LLM skipped)
    - ``confidence=0.8``   — LLM responded and regex class was not UNKNOWN
    - ``confidence=0.5``   — LLM responded but class is UNKNOWN
    - ``confidence=0.4``   — LLM unreachable; offline result kept, no suggestion

    Three-step fallback:
    1. **Pattern-library hit** — query ``fix_history`` for a prior successful
       fix with the same ``signature_hash``.  If found, return cached fix with
       ``confidence=0.95`` (no LLM call made).
    2. **Offline class + LLM enrichment** — run ``classify_offline`` to get
       the error class, then call the LLM for a human-readable suggested fix.
    3. **Graceful degrade** — if the LLM is unreachable at any point, return
       ``(offline_class, "", 0.4)``.

    Args:
        error_text: Raw error string from a failing install step.
        app_key:    Catalog key of the failing app (e.g. ``"sonarr"``).
        db_path:    Path to the SQLite state database file.  Used for the
                    pattern-library ``fix_history`` lookup.

    Returns:
        ``(ErrorClass, suggested_fix_str, confidence_float)`` — never raises.
    """
    import sqlite3

    # Compute offline class and stable hash — pure, always succeeds.
    error_class = classify_offline(error_text)
    sig_hash = compute_signature_hash(error_class, error_text, app_key)

    # Step 1 — pattern-library lookup (exact hash hit on prior successful fix).
    if db_path:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT suggested_fix FROM fix_history "
                "WHERE signature_hash=? AND outcome='success' "
                "ORDER BY created_at DESC LIMIT 1",
                (sig_hash,),
            ).fetchone()
            conn.close()
            if row:
                return (error_class, row["suggested_fix"], 0.95)
        except Exception:
            pass  # DB missing or column not yet added — fall through to LLM

    # Step 2 — build context and call LLM.
    # Deferred import: assemble_context may reference backend.core.state internally.
    from backend.health.context_assembler import assemble_context

    context_block = assemble_context(
        app_key,
        "install_monitor",
        runtime={"error_class": error_class.value, "error_text": error_text[:500]},
    )
    prompt = (
        "You are a Docker install troubleshooter. "
        "Diagnose the following installation failure and suggest a fix.\n\n"
        + context_block
        + "\n\nError class: "
        + error_class.value
        + "\nError: "
        + error_text[:500]
        + "\n\nReply with one short paragraph (plain text, ≤200 chars) describing the fix."
    )

    raw = await _query_llm_for_diagnosis(prompt)

    if raw is None:
        # Step 3 — graceful degrade: LLM unreachable.
        return (error_class, "", 0.4)

    # Parse: first non-empty paragraph, truncate to 200 chars.
    first_para = next(
        (p.strip() for p in raw.split("\n\n") if p.strip()),
        raw.strip(),
    )
    suggested_fix = first_para[:200]
    confidence = 0.8 if error_class != ErrorClass.UNKNOWN else 0.5
    return (error_class, suggested_fix, confidence)
