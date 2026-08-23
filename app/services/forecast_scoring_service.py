"""Score the twin's own forecasts against what actually happened (program 2, slice 1).

The loop the project wants runs athlete state -> prescription -> completed training ->
evidence -> updated state -> better prescription. It was open at the *predicting* end, not
the learning end: grepping ``predicted_vs|prediction_error|realized|forecast`` across
``app/services/`` and ``app/logic/`` returned a single unrelated docstring word. Nothing
recorded what the twin expected, so nothing could measure how wrong it was.

Prescriptions now record ``why.expected_outcomes``, and ``_persist_prescription`` writes
that into ``PlannedSession.prescribed_content``. This module is the other half: for sessions
the athlete actually completed, compare what the forward model predicted against what the
state really did, and report the error.

Three disciplines this deliberately keeps:

1. **It decodes state strictly.** ``unified_from_athlete_row_strict`` never reconstructs
   from legacy scalars — a damaged row fails closed rather than presenting a lossy
   reconstruction as though it were observed. Scoring a forecast against a guess would be
   worse than not scoring it.
2. **It refuses ambiguous attribution.** If anything else the athlete did lands between the
   two state snapshots bracketing a session, the realized delta is not attributable to that
   session, and it is skipped with a reason rather than quietly counted.
3. **It authorizes nothing.** This is a measuring instrument. No caller changes behaviour
   from its output, and a bias figure here is not a licence to adjust the model — that is a
   separate, evidenced decision.

Read-only: it issues SELECTs and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.state_loading import unified_from_athlete_row_strict
from app.models.athlete_state import AthleteState
from app.models.mesocycle import PlannedSession, SessionStatus
from app.schemas.state import UnifiedStateVector

#: Why a completed, forecast-carrying session could not be scored. Counted, never hidden:
#: a scorer that silently drops what it cannot handle reports a flattering error rate.
SKIP_NO_BRACKET = "no state snapshots bracket the completion"
SKIP_UNDECODABLE = "a bracketing state row could not be decoded strictly"
SKIP_AMBIGUOUS = "another session completed inside the same window"
SKIP_NO_AXES = "the forecast named no axis this scorer can read"


@dataclass
class AxisError:
    """Accumulated forecast error on one state axis."""

    axis: str
    n: int = 0
    sum_error: float = 0.0
    sum_abs_error: float = 0.0
    # `lambda: []` rather than `list`: with a parameterised element type, bare `list`
    # infers list[Unknown] and trips the strict-pyright gate.
    samples: list[dict[str, float]] = field(default_factory=lambda: [])

    def add(self, predicted_delta: float, realized_delta: float) -> None:
        err = realized_delta - predicted_delta
        self.n += 1
        self.sum_error += err
        self.sum_abs_error += abs(err)
        self.samples.append(
            {
                "predicted_delta": round(predicted_delta, 3),
                "realized_delta": round(realized_delta, 3),
                "error": round(err, 3),
            }
        )

    def summary(self) -> dict[str, Any]:
        if not self.n:
            return {"axis": self.axis, "n": 0, "bias": None, "mean_abs_error": None}
        return {
            "axis": self.axis,
            "n": self.n,
            # Signed mean: positive means reality exceeded the forecast, i.e. the session
            # cost the athlete more than the twin expected. Direction matters more than
            # magnitude here — a biased model is wrong in a fixable way.
            "bias": round(self.sum_error / self.n, 4),
            "mean_abs_error": round(self.sum_abs_error / self.n, 4),
        }


def _fatigue_value(state: UnifiedStateVector, axis: str) -> float | None:
    """Read a forecast axis such as ``fatigue_f.cns`` off a decoded state vector."""
    family, _, key = axis.partition(".")
    if family != "fatigue_f" or not key:
        return None
    value = getattr(state.fatigue_f, key, None)
    return float(value) if value is not None else None


def _forecast_of(session: PlannedSession) -> list[dict[str, Any]]:
    """Pull the recorded forecast out of the prescription JSON.

    Every level is isinstance-checked rather than trusted: this is arbitrary JSONB written
    by an older version of the app, so a shape assumption here would fail on exactly the
    historical rows the scorer exists to read.
    """
    content: dict[str, Any] = session.prescribed_content or {}
    why_raw: object = content.get("why")
    if not isinstance(why_raw, dict):
        return []
    why = cast(dict[str, Any], why_raw)
    outcomes_raw: object = why.get("expected_outcomes")
    if not isinstance(outcomes_raw, list):
        return []
    outcomes = cast(list[object], outcomes_raw)
    found: list[dict[str, Any]] = []
    for entry in outcomes:
        if isinstance(entry, dict):
            typed = cast(dict[str, Any], entry)
            if typed.get("axis"):
                found.append(typed)
    return found


async def score_forecasts(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Compare recorded forecasts against realized state for completed sessions.

    Scoped to one athlete with ``user_id``; fleet-wide otherwise. Returns per-axis bias and
    mean absolute error, plus an explicit account of every session that could not be scored.
    """
    stmt = (
        select(PlannedSession)
        .where(PlannedSession.status == SessionStatus.COMPLETED)
        .where(PlannedSession.completed_at.is_not(None))
        .where(PlannedSession.prescribed_content.is_not(None))
        .order_by(PlannedSession.completed_at.desc())
        .limit(limit)
    )
    if user_id is not None:
        stmt = stmt.where(PlannedSession.user_id == user_id)
    sessions = list((await db.execute(stmt)).scalars().all())

    axes: dict[str, AxisError] = {}
    skipped: dict[str, int] = {}
    scored = 0

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for session in sessions:
        forecast = _forecast_of(session)
        if not forecast:
            continue  # no prediction was recorded; nothing to score, and not a failure

        before_row = (
            await db.execute(
                select(AthleteState)
                .where(AthleteState.user_id == session.user_id)
                .where(AthleteState.timestamp <= session.completed_at)
                .order_by(AthleteState.timestamp.desc())
                .limit(1)
            )
        ).scalars().first()
        after_row = (
            await db.execute(
                select(AthleteState)
                .where(AthleteState.user_id == session.user_id)
                .where(AthleteState.timestamp > session.completed_at)
                .order_by(AthleteState.timestamp.asc())
                .limit(1)
            )
        ).scalars().first()
        if before_row is None or after_row is None:
            _skip(SKIP_NO_BRACKET)
            continue

        # Anything else the athlete completed inside the window makes the realized delta
        # un-attributable to THIS session. Refuse rather than count it.
        others = (
            await db.execute(
                select(PlannedSession.id)
                .where(PlannedSession.user_id == session.user_id)
                .where(PlannedSession.id != session.id)
                .where(PlannedSession.status == SessionStatus.COMPLETED)
                .where(PlannedSession.completed_at > before_row.timestamp)
                .where(PlannedSession.completed_at <= after_row.timestamp)
            )
        ).scalars().all()
        if others:
            _skip(SKIP_AMBIGUOUS)
            continue

        try:
            before = unified_from_athlete_row_strict(before_row)
            after = unified_from_athlete_row_strict(after_row)
        except Exception:
            # Strict decoding refused. That is the correct outcome for a damaged row, and
            # the session is reported as unscoreable rather than scored against a guess.
            _skip(SKIP_UNDECODABLE)
            continue

        matched = 0
        for outcome in forecast:
            axis = str(outcome["axis"])
            b, a = _fatigue_value(before, axis), _fatigue_value(after, axis)
            if b is None or a is None:
                continue
            predicted_delta = float(outcome.get("delta", 0.0))
            axes.setdefault(axis, AxisError(axis=axis)).add(predicted_delta, a - b)
            matched += 1

        if matched:
            scored += 1
        else:
            _skip(SKIP_NO_AXES)

    return {
        "scope": "fleet" if user_id is None else f"user:{user_id}",
        "sessions_examined": len(sessions),
        "sessions_scored": scored,
        "skipped": skipped,
        "axes": [axes[a].summary() for a in sorted(axes)],
        # Same contract as the EKF calibration gate: evidence, never authority.
        "authorizes": "nothing - this is a measuring instrument, not a promotion gate",
    }


def format_report(result: dict[str, Any]) -> str:
    """Plain-text forecast-error report for a CLI."""
    lines = [
        f"Forecast error vs realized state - scope: {result['scope']}",
        f"  sessions examined: {result['sessions_examined']}   scored: {result['sessions_scored']}",
    ]
    skipped: dict[str, int] = result.get("skipped") or {}
    if skipped:
        for reason, n in sorted(skipped.items()):
            lines.append(f"  skipped {n}: {reason}")
    else:
        lines.append("  skipped: none")

    axes: list[dict[str, Any]] = result.get("axes") or []
    if not axes:
        lines.append("  no axis had a scoreable forecast yet")
    else:
        lines.append("")
        lines.append(f"  {'axis':<24}{'n':>5}{'bias':>10}{'mean|err|':>12}")
        for a in axes:
            bias = "n/a" if a["bias"] is None else f"{a['bias']:+.3f}"
            mae = "n/a" if a["mean_abs_error"] is None else f"{a['mean_abs_error']:.3f}"
            lines.append(f"  {a['axis']:<24}{a['n']:>5}{bias:>10}{mae:>12}")
        lines.append("")
        lines.append("  bias > 0 means the session cost more than the twin predicted")
    lines.append(f"  authorizes: {result['authorizes']}")
    return "\n".join(lines)
