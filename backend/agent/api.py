"""backend/agent/api.py

Agent REST endpoints — Phase D.

GET  /api/v1/agent/diagnoses       — pending LLM-generated diagnoses
POST /api/v1/agent/fixes/{id}/apply — stub; returns 501 (Phase E)

This router is registered in backend/api/main.py via _mount().
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.core.logging import get_logger
from backend.core.state import StateDB

log = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DiagnosisOut(BaseModel):
    id: int
    app_key: str
    problem: str
    diagnosis_class: str
    suggested_fix: str
    confidence: float
    status: str
    created_at: int


class DiagnosesResponse(BaseModel):
    diagnoses: list[DiagnosisOut]


# ---------------------------------------------------------------------------
# GET /diagnoses
# ---------------------------------------------------------------------------


@router.get("/diagnoses", response_model=DiagnosesResponse)
def get_diagnoses() -> DiagnosesResponse:
    """Return all pending diagnoses that have a non-empty suggested_fix.

    Ordered by created_at DESC, limited to 50 rows.  Only rows with
    status='pending' and suggested_fix != '' are included — empty
    suggested_fix means the LLM was unreachable and there is nothing
    actionable to show the user.
    """
    with StateDB() as db:
        rows = db.execute(
            """
            SELECT id, app_key, problem, diagnosis_class,
                   suggested_fix, confidence, status, created_at
            FROM   pending_fixes
            WHERE  status = 'pending'
              AND  suggested_fix != ''
            ORDER  BY created_at DESC
            LIMIT  50
            """,
        ).fetchall()

    diagnoses = [
        DiagnosisOut(
            id=row["id"],
            app_key=row["app_key"],
            problem=row["problem"],
            diagnosis_class=row["diagnosis_class"],
            suggested_fix=row["suggested_fix"],
            confidence=row["confidence"],
            status=row["status"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return DiagnosesResponse(diagnoses=diagnoses)


# ---------------------------------------------------------------------------
# POST /fixes/{id}/apply — Phase E stub
# ---------------------------------------------------------------------------


@router.post("/fixes/{fix_id}/apply", status_code=501)
def apply_fix(fix_id: int) -> Any:
    """Stub endpoint — auto-apply is not yet implemented (Phase E).

    Returns HTTP 501 with a human-readable detail string.  The frontend
    renders this as an amber banner so users know the feature is coming.
    """
    return JSONResponse(
        status_code=501,
        content={"detail": "Auto-apply not yet implemented (Phase E)"},
    )
