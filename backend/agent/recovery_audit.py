"""backend/agent/recovery_audit.py — recoverability + cert-expiry + credential probes.

Four GROUND probes reconciled against physics only:

  1. **mount_health** — bind-mount source paths (from custom_volumes) must exist
     and be non-empty.  DRIFT if missing or empty.  VERIFIED if all bind-mounts
     are present.  VERIFIED (no bind-mounts) if the manifest declares none.

  2a. **backup_configured** — soft advisory.  For an app that opts into backup
     (``backup_supported``), surface "no backup configured" (INDETERMINATE) when
     no backup directory resolves.  DISTINCT from "declared but absent" below:
     this is "you never set one up", not "the one you set up is gone".

  2b. **backup_freshness** — once a backup directory resolves (explicit
     ``backup_dir`` or ``<config_root>/backups/<key>``), it must exist and
     contain at least one artifact whose mtime is within 24h.  INDETERMINATE if
     the directory is absent (config absent ≠ failure).  DRIFT if empty or stale.

  3. **cert_expiry** — if the app manifest exposes a ``tls_cert_path`` field,
     the cert must not expire within 30 days.  DRIFT < 30 days (warn), DRIFT
     < 7 days (crit).  INDETERMINATE if the cert file is unreadable.
     Supports both PEM files and Traefik ACME JSON (auto-detected by extension).
     The ``{config_root}`` template in cert paths is resolved at reconcile time.

  4. **credential_validity** — if the app manifest declares ``auto_secrets``,
     each referenced env-var key must be present and non-empty in the platform
     ``.env`` file.  DRIFT if any declared secret is absent or empty.
     INDETERMINATE if the ``.env`` file cannot be read.

GROUND-only: no docs, no runbooks.  INDETERMINATE whenever a ground source is
unreachable; never a silent VERIFIED.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any

from backend.agent.backup import app_backup_dir
from backend.agent.spine import Finding, Verdict
from backend.core.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Probe 1: mount health
# ---------------------------------------------------------------------------


def _probe_mount_health(app: Any) -> Finding | None:
    """GROUND: bind-mount source paths exist and are non-empty."""
    app_key: str = getattr(app, "key", str(app))
    finding_id = f"recovery.mount_health.{app_key}"
    physics = f"bind-mount source paths for app {app_key}"

    custom_volumes = getattr(app, "custom_volumes", None) or []
    if not custom_volumes:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.VERIFIED,
            summary="no bind-mounts declared — nothing to probe",
        )

    missing: list[str] = []
    empty: list[str] = []

    for vol in custom_volumes:
        host_path = getattr(vol, "host_path", None) or ""
        # Named volumes have no leading slash; bind-mounts do.
        if not host_path or not host_path.startswith("/"):
            continue
        p = Path(host_path)
        if not p.exists():
            missing.append(host_path)
            continue
        # Check non-empty: at least one item inside (or inode count > 0)
        try:
            if not os.listdir(host_path):
                empty.append(host_path)
        except PermissionError:
            # Can't list → treat as accessible but unverifiable
            pass

    if missing:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary="bind-mount source path(s) missing",
            detail=f"missing={missing}",
        )
    if empty:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary="bind-mount source path(s) are empty",
            detail=f"empty={empty}",
        )
    return Finding(
        id=finding_id,
        physics=physics,
        verdict=Verdict.VERIFIED,
        summary="all bind-mount source paths present and non-empty",
    )


# ---------------------------------------------------------------------------
# Probe 2a: backup configured (soft advisory — DISTINCT from freshness)
# ---------------------------------------------------------------------------


def _probe_backup_configured(app: Any, config_root: str | None = None) -> Finding | None:
    """Soft advisory: an app that opts into backup has a resolvable backup dir.

    This is DISTINCT from :func:`_probe_backup_freshness`:

      * freshness answers "is the EXISTING backup recent?" and only fires once a
        ``backup_dir`` resolves to a real directory;
      * THIS probe answers "is backup CONFIGURED at all?" for an app that
        declared ``backup_supported`` — a soft INDETERMINATE advisory when the
        backup directory cannot be resolved (no config_root) so the operator
        sees "no backup configured" rather than silence.

    Returns None when the app does not opt into backup (``backup_supported``
    falsy) — no advisory for apps with no durable state to protect.
    """
    if not getattr(app, "backup_supported", False):
        return None  # app does not opt into backup — nothing to advise

    app_key: str = getattr(app, "key", str(app))
    finding_id = f"recovery.backup_configured.{app_key}"
    physics = f"backup configuration for app {app_key}"

    backup_dir = app_backup_dir(app, config_root)
    if not backup_dir:
        # Opted into backup but no directory resolves — soft advisory, not a
        # DRIFT: nothing is broken, the operator simply has not configured a
        # backup location yet.
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.INDETERMINATE,
            summary="no backup configured — app supports backup but none is set up",
            detail=f"app={app_key} backup_supported=true backup_dir=unresolved",
        )

    return Finding(
        id=finding_id,
        physics=physics,
        verdict=Verdict.VERIFIED,
        summary="backup directory configured",
        detail=f"path={backup_dir}",
    )


# ---------------------------------------------------------------------------
# Probe 2b: backup freshness
# ---------------------------------------------------------------------------

_BACKUP_WARN_H = 24  # hours — DRIFT (warn)
_BACKUP_CRIT_H = 72  # hours — DRIFT (crit)


def _probe_backup_freshness(app: Any, config_root: str | None = None) -> Finding | None:
    """GROUND: latest backup artifact not stale.

    The backup directory is resolved via :func:`app_backup_dir` — an explicit
    ``backup_dir`` on the manifest, else ``<config_root>/backups/<key>`` for an
    app that opts into backup.  Returns None when no directory can be resolved
    (the "no backup configured" case is owned by ``_probe_backup_configured``).
    """
    app_key: str = getattr(app, "key", str(app))
    finding_id = f"recovery.backup_freshness.{app_key}"
    physics = f"backup directory artifact mtime for app {app_key}"

    backup_dir = app_backup_dir(app, config_root)
    if not backup_dir:
        return None  # no backup dir resolvable — freshness has nothing to probe

    bdir = Path(backup_dir)
    if not bdir.exists():
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.INDETERMINATE,
            summary="backup_dir declared but directory absent",
            detail=f"path={backup_dir}",
        )

    try:
        artifacts = list(bdir.iterdir())
    except PermissionError as exc:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.INDETERMINATE,
            summary="backup_dir unreadable",
            detail=f"PermissionError: {exc}",
        )

    if not artifacts:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary="backup_dir is empty — no artifacts found",
            detail=f"path={backup_dir}",
        )

    # Find the most-recently modified artifact
    latest_mtime = max(a.stat().st_mtime for a in artifacts)
    age_h = (datetime.datetime.now().timestamp() - latest_mtime) / 3600

    if age_h > _BACKUP_CRIT_H:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary=f"latest backup is {age_h:.0f}h old — critical",
            detail=f"path={backup_dir} age_hours={age_h:.1f} threshold_crit={_BACKUP_CRIT_H}",
        )
    if age_h > _BACKUP_WARN_H:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary=f"latest backup is {age_h:.0f}h old — warn",
            detail=f"path={backup_dir} age_hours={age_h:.1f} threshold_warn={_BACKUP_WARN_H}",
        )
    return Finding(
        id=finding_id,
        physics=physics,
        verdict=Verdict.VERIFIED,
        summary=f"latest backup is {age_h:.0f}h old — within threshold",
        detail=f"path={backup_dir} age_hours={age_h:.1f}",
    )


# ---------------------------------------------------------------------------
# Probe 3: cert expiry
# ---------------------------------------------------------------------------

_CERT_WARN_DAYS = 30  # DRIFT (warn)
_CERT_CRIT_DAYS = 7  # DRIFT (crit)


def _cert_not_after_pem(cert_path: str) -> datetime.datetime | None:
    """Parse PEM cert expiry via ssl stdlib or openssl subprocess.

    Returns the expiry datetime (UTC-naive) or None if unreadable.
    """
    # Try ssl stdlib first (no subprocess, preferred)
    try:
        import ssl

        cert = ssl._ssl._test_decode_cert(cert_path)  # type: ignore[attr-defined]
        not_after_str = cert.get("notAfter", "")
        if not_after_str:
            # Format: "Jan  1 00:00:00 2030 GMT"
            return datetime.datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
    except Exception:  # noqa: S110  # nosec B110  best-effort ssl parse; fall through to openssl subprocess
        pass

    # Fallback: openssl subprocess
    try:
        import subprocess

        r = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate", "-in", cert_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            # Output: "notAfter=Jan  1 00:00:00 2030 GMT"
            line = r.stdout.strip()
            if "=" in line:
                date_str = line.split("=", 1)[1].strip()
                return datetime.datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
    except Exception:  # noqa: S110  # nosec B110  best-effort subprocess fallback; return None if unavailable
        pass

    return None


def _der_not_after(der_bytes: bytes) -> datetime.datetime | None:
    """Parse notAfter from a DER-encoded certificate via openssl subprocess.

    Returns the expiry datetime (UTC-naive) or None if unreadable.
    """
    try:
        import subprocess

        r = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate", "-inform", "DER"],
            input=der_bytes,
            capture_output=True,
            timeout=5,
        )
        if r.returncode != 0:
            return None
        line = r.stdout.decode().strip()
        if "=" not in line:
            return None
        date_str = line.split("=", 1)[1].strip()
        return datetime.datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
    except Exception:  # nosec B110  # best-effort subprocess; caller handles None
        return None


def _decode_b64_cert(cert_b64: str) -> bytes | None:
    """Decode a base64 cert string to DER bytes, or None if malformed."""
    import base64

    try:
        return base64.b64decode(cert_b64)
    except Exception:  # nosec B110  # best-effort decode; None signals failure to caller
        return None


def _acme_cert_entries(data: dict[str, Any]) -> list[bytes]:
    """Extract all DER-decoded certificate bytes from a Traefik ACME JSON dict."""
    result: list[bytes] = []
    for resolver_data in data.values():
        if not isinstance(resolver_data, dict):
            continue
        for cert_entry in resolver_data.get("Certificates") or []:
            if not isinstance(cert_entry, dict):
                continue
            cert_b64 = cert_entry.get("certificate") or cert_entry.get("Certificate") or ""
            if not cert_b64:
                continue
            der = _decode_b64_cert(cert_b64)
            if der is not None:
                result.append(der)
    return result


def _cert_not_after_acme_json(acme_path: str) -> datetime.datetime | None:
    """Parse the earliest cert expiry from a Traefik ACME JSON store.

    Traefik stores ACME certs as:
      {<resolver>: {"Certificates": [{certificate: "<base64-DER>", ...}]}}

    Returns the earliest (soonest to expire) notAfter datetime found across all
    certs in all resolvers, or None if the file is unreadable or contains no certs.
    """
    import json

    try:
        data = json.loads(Path(acme_path).read_text(encoding="utf-8"))
    except Exception:  # nosec B110  # best-effort; caller handles None
        return None

    if not isinstance(data, dict):
        return None

    earliest: datetime.datetime | None = None
    for der_bytes in _acme_cert_entries(data):
        dt = _der_not_after(der_bytes)
        if dt is not None and (earliest is None or dt < earliest):
            earliest = dt
    return earliest


def _cert_not_after(cert_path: str) -> datetime.datetime | None:
    """Parse cert expiry from a PEM file or a Traefik ACME JSON store.

    Auto-detects format: files ending in ``.json`` are treated as Traefik
    ACME JSON; all others are tried as PEM first (ssl stdlib) then via openssl.

    Returns the expiry datetime (UTC-naive) or None if unreadable.
    """
    if cert_path.lower().endswith(".json"):
        return _cert_not_after_acme_json(cert_path)
    return _cert_not_after_pem(cert_path)


def _probe_cert_expiry(app: Any, config_root: str = "") -> Finding | None:
    """GROUND: TLS certificate not expiring within thresholds.

    Supports PEM files and Traefik ACME JSON stores (auto-detected by extension).
    The ``{config_root}`` template in cert paths is resolved using ``config_root``
    when provided; unresolved templates yield INDETERMINATE.

    Returns None when the manifest has no ``tls_cert_path`` field (omit).
    """
    app_key: str = getattr(app, "key", str(app))
    finding_id = f"recovery.cert_expiry.{app_key}"
    physics = f"TLS certificate expiry for app {app_key}"

    cert_path = getattr(app, "tls_cert_path", None) or ""
    if not cert_path:
        return None  # no cert configured — omit finding

    # Resolve {config_root} template if present
    if "{config_root}" in cert_path:
        if not config_root:
            return Finding(
                id=finding_id,
                physics=physics,
                verdict=Verdict.INDETERMINATE,
                summary="tls_cert_path uses {config_root} template but config_root not provided",
                detail=f"raw_path={cert_path}",
            )
        cert_path = cert_path.replace("{config_root}", config_root)

    if not Path(cert_path).exists():
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.INDETERMINATE,
            summary="tls_cert_path declared but file absent",
            detail="cert_path not present on disk",
        )

    not_after = _cert_not_after(cert_path)
    if not_after is None:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.INDETERMINATE,
            summary="cert expiry unreadable",
            detail="ssl and openssl both failed to parse the cert",
        )

    now_utc = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    days_left = (not_after - now_utc).days

    if days_left < _CERT_CRIT_DAYS:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary=f"certificate expires in {days_left} days — critical",
            detail=f"days_remaining={days_left} threshold_crit={_CERT_CRIT_DAYS}",
        )
    if days_left < _CERT_WARN_DAYS:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary=f"certificate expires in {days_left} days — warn",
            detail=f"days_remaining={days_left} threshold_warn={_CERT_WARN_DAYS}",
        )
    return Finding(
        id=finding_id,
        physics=physics,
        verdict=Verdict.VERIFIED,
        summary=f"certificate valid for {days_left} more days",
        detail=f"days_remaining={days_left}",
    )


# ---------------------------------------------------------------------------
# Probe 4: credential validity
# ---------------------------------------------------------------------------

# Minimum entropy bytes for a generated secret (token_hex(N) → 2*N hex chars)
_SECRET_MIN_LEN = 16  # 8 bytes of entropy minimum; anything shorter is suspicious


def _read_env_file(env_path: str) -> dict[str, str] | None:
    """Read a .env file into a key→value dict.

    Returns None if the file is unreadable (yields INDETERMINATE).
    """
    try:
        lines = Path(env_path).read_text(encoding="utf-8").splitlines()
    except Exception:  # best-effort; caller handles None
        return None

    result: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            result[k.strip()] = v.strip()
    return result


def _extract_secret_keys(auto_secrets: Any) -> list[str]:
    """Normalise auto_secrets entries (``{key:, length:}`` dicts or bare strings) to key names."""
    secret_keys: list[str] = []
    for entry in auto_secrets:
        if isinstance(entry, dict):
            k = entry.get("key", "")
        elif isinstance(entry, str):
            k = entry
        else:
            k = ""
        if k:
            secret_keys.append(k)
    return secret_keys


def _resolve_credential_env_path(env_path: str) -> str:
    """Resolve the .env path, falling back to ``backend.core.config`` when unset."""
    if env_path:
        return env_path
    try:
        from backend.core.config import config as _cfg

        return str(_cfg.env_file)
    except Exception:  # config import may fail in test environments
        return ""


def _classify_secrets(
    secret_keys: list[str], env_vars: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Split declared secret keys into (missing, empty, below-min-length) buckets."""
    missing: list[str] = []
    empty: list[str] = []
    short: list[str] = []
    for key_name in secret_keys:
        val = env_vars.get(key_name)
        if val is None:
            missing.append(key_name)
        elif val == "":
            empty.append(key_name)
        elif len(val) < _SECRET_MIN_LEN:
            short.append(f"{key_name}(len={len(val)})")
    return missing, empty, short


def _probe_credential_validity(app: Any, env_path: str = "") -> Finding | None:
    """GROUND: declared auto_secrets are present and well-formed in the .env file.

    Checks that every key listed in the manifest's ``auto_secrets`` field:
      - exists in the platform ``.env`` file
      - is non-empty
      - meets a minimum length threshold (prevents stub/placeholder values)

    Returns None when the manifest declares no ``auto_secrets`` (omit).
    Returns INDETERMINATE when the ``.env`` file cannot be read.
    Returns DRIFT when any secret is absent, empty, or below the length threshold.
    Returns VERIFIED when all declared secrets are present and well-formed.
    """
    app_key: str = getattr(app, "key", str(app))
    finding_id = f"recovery.credential_validity.{app_key}"
    physics = f"auto_secrets env-var presence + length for app {app_key}"

    secret_keys = _extract_secret_keys(getattr(app, "auto_secrets", None) or [])
    if not secret_keys:
        return None  # no secrets declared — omit finding

    resolved_env_path = _resolve_credential_env_path(env_path)
    if not resolved_env_path or not Path(resolved_env_path).exists():
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.INDETERMINATE,
            summary="credential probe: .env file absent or path unknown",
            detail=f"env_path={resolved_env_path!r}",
        )

    env_vars = _read_env_file(resolved_env_path)
    if env_vars is None:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.INDETERMINATE,
            summary="credential probe: .env file unreadable",
            detail=f"env_path={resolved_env_path!r}",
        )

    missing, empty, short = _classify_secrets(secret_keys, env_vars)

    if missing:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary=f"declared secret(s) absent from .env: {', '.join(missing)}",
            detail=f"missing={missing} env_path={resolved_env_path!r}",
        )
    if empty:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary=f"declared secret(s) present but empty in .env: {', '.join(empty)}",
            detail=f"empty={empty} env_path={resolved_env_path!r}",
        )
    if short:
        return Finding(
            id=finding_id,
            physics=physics,
            verdict=Verdict.DRIFT,
            summary=f"declared secret(s) below minimum length ({_SECRET_MIN_LEN} chars): {', '.join(short)}",
            detail=f"short={short} min_len={_SECRET_MIN_LEN} env_path={resolved_env_path!r}",
        )

    return Finding(
        id=finding_id,
        physics=physics,
        verdict=Verdict.VERIFIED,
        summary=f"all {len(secret_keys)} declared secret(s) present and well-formed",
        detail=f"checked={secret_keys}",
    )


# ---------------------------------------------------------------------------
# Public reconciler
# ---------------------------------------------------------------------------


def reconcile_recovery(  # noqa: C901 — flat dispatch of 5 independent guarded GROUND probes (mount/backup-configured/backup-freshness/cert/credential); each carries its own INDETERMINATE fallback, splitting scatters the per-probe guard
    apps: list[Any],
    config_root: str | None = None,
    *,
    env_path: str = "",
) -> list[Finding]:
    """GROUND recoverability reconciler.

    Probes per app: mount_health + backup_configured (soft advisory) +
    backup_freshness + cert_expiry + credential_validity.  ``config_root`` (the
    platform config root) lets the backup probes resolve
    ``<config_root>/backups/<key>`` for apps that opt into backup via
    ``backup_supported``; when None, only manifests carrying an explicit
    ``backup_dir`` resolve.

    Accepts the list of installed app manifest objects.  Each probe is
    independently guarded so one failure yields its own INDETERMINATE without
    suppressing the others.  Returns all non-None findings.

    ``config_root`` is used to resolve ``{config_root}`` templates in
    ``tls_cert_path`` fields.  When empty, the reconciler tries to read it from
    the platform DB record; pass it explicitly in tests to avoid DB access.

    ``env_path`` is the path to the platform ``.env`` file for the credential
    probe.  When empty, the probe resolves it via ``backend.core.config``.
    """
    # Resolve config_root from DB when not provided explicitly. Coerce None→"" so the
    # cert probe (which takes a str) never receives None from the unified signature.
    resolved_config_root: str = config_root or ""
    if not resolved_config_root:
        try:
            from backend.core.state import StateDB

            with StateDB() as _db:
                _p = _db.get_platform()
                resolved_config_root = getattr(_p, "config_root", "") or ""
        except Exception as exc:
            log.debug("could not read config_root from DB for cert path resolution: %s", exc)

    findings: list[Finding] = []

    for app in apps:
        app_key = getattr(app, "key", "unknown")

        # Probe 2a: backup configured (soft advisory; omit if not opted in)
        try:
            f = _probe_backup_configured(app, config_root)
            if f is not None:
                findings.append(f)
        except Exception as exc:
            log.warning("backup_configured probe failed for %s: %s", app_key, exc)
            findings.append(
                Finding(
                    id=f"recovery.backup_configured.{app_key}",
                    physics=f"backup configuration for app {app_key}",
                    verdict=Verdict.INDETERMINATE,
                    summary="backup_configured probe raised unexpectedly",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

        # Probe 1: mount health
        try:
            f = _probe_mount_health(app)
            if f is not None:
                findings.append(f)
        except Exception as exc:
            log.warning("mount_health probe failed for %s: %s", app_key, exc)
            findings.append(
                Finding(
                    id=f"recovery.mount_health.{app_key}",
                    physics=f"bind-mount source paths for app {app_key}",
                    verdict=Verdict.INDETERMINATE,
                    summary="mount_health probe raised unexpectedly",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

        # Probe 2b: backup freshness (omit if no backup_dir resolvable)
        try:
            f = _probe_backup_freshness(app, config_root)
            if f is not None:
                findings.append(f)
        except Exception as exc:
            log.warning("backup_freshness probe failed for %s: %s", app_key, exc)
            findings.append(
                Finding(
                    id=f"recovery.backup_freshness.{app_key}",
                    physics=f"backup directory artifact mtime for app {app_key}",
                    verdict=Verdict.INDETERMINATE,
                    summary="backup_freshness probe raised unexpectedly",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

        # Probe 3: cert expiry (omit if no tls_cert_path)
        try:
            f = _probe_cert_expiry(app, config_root=resolved_config_root)
            if f is not None:
                findings.append(f)
        except Exception as exc:
            log.warning("cert_expiry probe failed for %s: %s", app_key, exc)
            findings.append(
                Finding(
                    id=f"recovery.cert_expiry.{app_key}",
                    physics=f"TLS certificate expiry for app {app_key}",
                    verdict=Verdict.INDETERMINATE,
                    summary="cert_expiry probe raised unexpectedly",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

        # Probe 4: credential validity (omit if no auto_secrets)
        try:
            f = _probe_credential_validity(app, env_path=env_path)
            if f is not None:
                findings.append(f)
        except Exception as exc:
            log.warning("credential_validity probe failed for %s: %s", app_key, exc)
            findings.append(
                Finding(
                    id=f"recovery.credential_validity.{app_key}",
                    physics=f"auto_secrets env-var presence + length for app {app_key}",
                    verdict=Verdict.INDETERMINATE,
                    summary="credential_validity probe raised unexpectedly",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

    return findings


__all__ = ["reconcile_recovery"]
