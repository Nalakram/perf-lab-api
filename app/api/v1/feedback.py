"""Session feedback — first-party adherence/satisfaction labels.

``POST /v1/feedback``  record an athlete-reported outcome for a planned session.
``GET  /v1/feedback``  the caller's recent outcomes, newest first.

These endpoints write and read labels only; neither mutates a plan. Feedback never
writes ``PlannedSession.status`` — that stays the canonical source of whether a
session happened (ADR-0070). What the labels *do* now reach is the prescriber's
adherence bias, via a single block-scoped aggregate
(``planning_service.block_adherence_signals``), so a reported modification can make
the next session lighter. That is a bounded policy response to declared friction,
not a claim that the modification caused anything.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.session_feedback import SessionFeedbackIn, SessionFeedbackOut
from app.services import session_feedback_service

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("", response_model=SessionFeedbackOut, status_code=201)
async def create_feedback(
    payload: SessionFeedbackIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionFeedbackOut:
    """Persist one athlete-reported ``SessionFeedback`` row, user-scoped."""
    feedback = await session_feedback_service.create_feedback(db, current_user.id, payload)
    return SessionFeedbackOut.model_validate(feedback)


@router.get("", response_model=list[SessionFeedbackOut])
async def list_feedback(
    limit: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SessionFeedbackOut]:
    """The caller's recent session feedback, newest first."""
    rows = await session_feedback_service.list_feedback(db, current_user.id, limit=limit)
    return [SessionFeedbackOut.model_validate(r) for r in rows]
