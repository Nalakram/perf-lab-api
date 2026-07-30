"""Missing wellness on a workout log is a gap, never an imputed midpoint (ADR-0049).

Before this suite, ``WorkoutLog.sleep_quality`` and ``.life_stress_inverse`` defaulted to
the scale midpoint ``5.0``, so "the athlete reported 5/10" and "no check-in exists" were
the same value from the schema down through the dose engine, the persisted row, and the
calibration frame. ADR-0049's guardrail — "never feed a client-side, carried-forward, or
silently-imputed value into readiness ... Missing lowers confidence; it is never filled to
look measured" — is what these tests hold the line on, using the ADR-0039 ``neutral_missing``
labelling precedent (a neutral that is *labelled* and carries zero confidence).

Covered:
- schema: absence parses as ``None``; a supplied value still validates and is still bounded
- persistence: a log submitted without wellness lands as SQL ``NULL``, not ``5.0``
- dose engine: unknown ⇒ exactly the no-penalty gain 1.0, labelled, zero confidence
- dose engine: a worst-case *reported* value still penalises; output bounded, non-negative
- dose engine: the reported path is bit-for-bit the pre-change equation (no regression)
- clearance: unknown ⇒ exactly the identity multiplier, and differs from a reported 5.0
- ``0`` and ``None`` are distinguishable at every consumer
"""
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.domain.vectors import FatigueState
from app.engine.parameters import default_parameters
from app.logic.dose_engine_v0 import calculate_stress_dose
from app.logic.state_update_v0 import recovery_clearance_multiplier
from app.ml.dose_calibration.build_training_frame import build_log
from app.models.user import User
from app.schemas.workouts import WorkoutLog
from app.services.state_service import initialize_athlete_state, process_new_workout

_SIX_AXES = ("volume", "intensity", "density", "impact", "skill", "metabolic")


def _log(**kwargs) -> WorkoutLog:
    """A workout log that, by default, carries NO wellness check-in."""
    defaults = {
        "timestamp": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        "modality": "Strength",
        "duration_minutes": 60.0,
        "session_rpe": 7.0,
    }
    defaults.update(kwargs)
    return WorkoutLog(**defaults)


def _expected_penalty(value: float) -> float:
    """The pre-change human-factor penalty equation, restated independently."""
    p = default_parameters()
    return 1.0 + max(0.0, (p.dose_human_factor_reference - value) * p.dose_human_factor_slope)


# ── Schema: absence survives parsing as None ─────────────────────────────────

def test_omitting_wellness_yields_none_not_the_midpoint():
    log = _log()
    assert log.sleep_quality is None, "absent sleep must stay unknown, not become 5.0"
    assert log.life_stress_inverse is None, "absent stress must stay unknown, not become 5.0"


def test_explicit_null_is_accepted_and_stays_none():
    log = WorkoutLog.model_validate({
        "timestamp": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        "modality": "Strength",
        "duration_minutes": 60.0,
        "session_rpe": 7.0,
        "sleep_quality": None,
        "life_stress_inverse": None,
    })
    assert log.sleep_quality is None
    assert log.life_stress_inverse is None


def test_supplied_wellness_still_validates_and_round_trips():
    log = _log(sleep_quality=3.0, life_stress_inverse=9.0)
    assert log.sleep_quality == 3.0
    assert log.life_stress_inverse == 9.0


@pytest.mark.parametrize("field", ["sleep_quality", "life_stress_inverse"])
@pytest.mark.parametrize("bad", [0.0, 0.999, -1.0, 10.001, 11.0])
def test_supplied_wellness_still_enforces_the_1_to_10_bounds(field: str, bad: float):
    with pytest.raises(ValidationError):
        _log(**{field: bad})


@pytest.mark.parametrize("field", ["sleep_quality", "life_stress_inverse"])
@pytest.mark.parametrize("edge", [1.0, 10.0])
def test_scale_endpoints_are_in_domain(field: str, edge: float):
    assert getattr(_log(**{field: edge}), field) == edge


# ── Dose engine: unknown ⇒ no penalty, labelled ──────────────────────────────

def test_unknown_wellness_applies_exactly_no_penalty():
    hf = calculate_stress_dose(_log()).human_factor_gain
    assert hf is not None
    assert hf.value == 1.0, "an unknown input must contribute the identity multiplier"


def test_unknown_wellness_is_labelled_with_zero_confidence():
    hf = calculate_stress_dose(_log()).human_factor_gain
    assert hf is not None
    assert hf.source == "neutral_missing"
    assert hf.confidence == 0.0
    assert {i.name for i in hf.inputs} == {"sleep_quality", "life_stress_inverse"}
    for item in hf.inputs:
        assert item.value is None
        assert item.source == "neutral_missing"
        assert item.confidence == 0.0
        assert item.penalty == 1.0


def test_unknown_is_not_silently_read_as_the_average_athlete():
    """A real 1.0/10 report must be distinguishable from "no check-in" in the dose."""
    unknown = calculate_stress_dose(_log())
    reported_bad = calculate_stress_dose(_log(sleep_quality=1.0, life_stress_inverse=1.0))
    assert unknown.human_factor_gain is not None
    assert reported_bad.human_factor_gain is not None
    assert reported_bad.human_factor_gain.value > unknown.human_factor_gain.value
    assert reported_bad.human_factor_gain.source == "reported"
    assert reported_bad.human_factor_gain.confidence == 1.0


def test_partial_wellness_keeps_the_reported_half_and_labels_the_gap():
    hf = calculate_stress_dose(_log(sleep_quality=2.0)).human_factor_gain
    assert hf is not None
    assert hf.source == "partial_neutral_missing"
    assert hf.confidence == 0.5
    by_name = {i.name: i for i in hf.inputs}
    assert by_name["life_stress_inverse"].penalty == 1.0
    assert by_name["sleep_quality"].penalty == pytest.approx(_expected_penalty(2.0))
    assert hf.value == pytest.approx(_expected_penalty(2.0))


def test_worst_case_reported_wellness_still_penalises():
    hf = calculate_stress_dose(_log(sleep_quality=1.0, life_stress_inverse=1.0)).human_factor_gain
    assert hf is not None
    assert hf.value == pytest.approx(_expected_penalty(1.0) ** 2)
    assert hf.value > 1.0


# ── Dose engine: boundedness, non-negativity, monotonicity ───────────────────

@pytest.mark.parametrize("sq,lsi", [
    (None, None), (1.0, 1.0), (10.0, 10.0), (1.0, None), (None, 10.0), (5.0, 7.0),
])
def test_gain_is_bounded_and_dose_stays_non_negative(sq: float | None, lsi: float | None):
    p = default_parameters()
    ceiling = _expected_penalty(1.0) ** 2
    dose = calculate_stress_dose(_log(sleep_quality=sq, life_stress_inverse=lsi))
    hf = dose.human_factor_gain
    assert hf is not None
    assert 1.0 <= hf.value <= ceiling, "gain must stay in [1, (1+(ref-1)*slope)^2]"
    assert p.dose_human_factor_slope >= 0.0
    for axis in _SIX_AXES:
        assert getattr(dose.dose_six, axis) >= 0.0
    for legacy in ("d_met_systemic", "d_nm_peripheral", "d_nm_central",
                   "d_struct_damage", "d_struct_signal"):
        assert getattr(dose, legacy) >= 0.0


def test_gain_is_monotone_non_increasing_in_each_reported_input():
    values = [1.0, 3.0, 5.0, 7.0, 10.0]
    gains = []
    for v in values:
        hf = calculate_stress_dose(_log(sleep_quality=v, life_stress_inverse=7.0)).human_factor_gain
        assert hf is not None
        gains.append(hf.value)
    assert gains == sorted(gains, reverse=True), "a worse report must never lower the penalty"


def test_gain_is_never_zero_so_the_adaptation_reciprocal_is_safe():
    """``adapt.scaled(1/gain)`` is only well-defined because the gain cannot reach 0."""
    for sq in (None, 1.0, 10.0):
        hf = calculate_stress_dose(_log(sleep_quality=sq)).human_factor_gain
        assert hf is not None
        assert hf.value >= 1.0


# ── Dose engine: the populated path must not have regressed ──────────────────

@pytest.mark.parametrize("sq,lsi", [(7.0, 7.0), (3.0, 8.0), (2.0, 2.0), (10.0, 1.0)])
def test_reported_path_still_implements_the_pre_change_equation(sq: float, lsi: float):
    """A known-good value produces exactly what it produced before this change.

    The gain equation for a *reported* input is untouched: ``1 + max(0, (ref - x)*slope)``.
    Restated here independently of the engine so a change to the engine's formula fails.
    """
    hf = calculate_stress_dose(_log(sleep_quality=sq, life_stress_inverse=lsi)).human_factor_gain
    assert hf is not None
    assert hf.value == pytest.approx(_expected_penalty(sq) * _expected_penalty(lsi))


def test_reported_gain_scales_the_six_axis_dose_by_exactly_the_gain():
    """The gain's only effect on the vector is the documented uniform scaling."""
    neutral = calculate_stress_dose(_log(sleep_quality=10.0, life_stress_inverse=10.0))
    penalised = calculate_stress_dose(_log(sleep_quality=2.0, life_stress_inverse=2.0))
    hf = penalised.human_factor_gain
    assert hf is not None
    assert hf.value > 1.0
    for axis in _SIX_AXES:
        base = getattr(neutral.dose_six, axis)
        if base > 0.0:
            assert getattr(penalised.dose_six, axis) == pytest.approx(base * hf.value)


def test_unknown_wellness_dose_equals_a_maximally_recovered_report_in_value_only():
    """Unknown dosing matches "no penalty due", but stays distinguishable by its label."""
    unknown = calculate_stress_dose(_log())
    great = calculate_stress_dose(_log(sleep_quality=10.0, life_stress_inverse=10.0))
    for axis in _SIX_AXES:
        assert getattr(unknown.dose_six, axis) == pytest.approx(getattr(great.dose_six, axis))
    assert unknown.human_factor_gain is not None
    assert great.human_factor_gain is not None
    assert unknown.human_factor_gain.source != great.human_factor_gain.source
    assert unknown.human_factor_gain.confidence < great.human_factor_gain.confidence


def test_unknown_dose_does_not_carry_forward_a_previous_session() -> None:
    """ADR-0049 forbids carry-forward: a prior poor check-in must not colour the next one."""
    calculate_stress_dose(_log(sleep_quality=1.0, life_stress_inverse=1.0))
    after = calculate_stress_dose(_log())
    assert after.human_factor_gain is not None
    assert after.human_factor_gain.value == 1.0


# ── Clearance multiplier: one convention, and 0 != None ──────────────────────

@pytest.mark.parametrize("axis", sorted(FatigueState.KEYS))
def test_unknown_wellness_is_the_identity_clearance_multiplier(axis: str):
    p = default_parameters()
    assert recovery_clearance_multiplier(axis, None, None, p) == pytest.approx(1.0)


@pytest.mark.parametrize("axis", sorted(FatigueState.KEYS))
def test_unknown_differs_from_the_old_imputed_5_point_0(axis: str):
    """The reconciliation: an imputed 5.0 actively SLOWED clearance; unknown must not.

    This is the defect the schema default caused downstream — ``recovery_clearance_
    multiplier`` z-scores against a 7.0 centre, so the fabricated 5.0 arrived as z = -1
    and quietly punished every athlete who simply did not check in.
    """
    p = default_parameters()
    unknown = recovery_clearance_multiplier(axis, None, None, p)
    imputed = recovery_clearance_multiplier(axis, 5.0, 5.0, p)
    assert imputed < unknown, "a reported 5/10 must remain a real, distinct signal"


@pytest.mark.parametrize("axis", sorted(FatigueState.KEYS))
def test_a_reported_value_still_moves_clearance_in_both_directions(axis: str):
    p = default_parameters()
    neutral = recovery_clearance_multiplier(axis, None, None, p)
    poor = recovery_clearance_multiplier(axis, 2.0, 2.0, p)
    good = recovery_clearance_multiplier(axis, 10.0, 10.0, p)
    assert poor < neutral < good
    assert p.recovery_clearance_min <= poor
    assert good <= p.recovery_clearance_max
    assert poor > 0.0, "a non-positive multiplier would freeze or reverse fatigue decay"


def test_one_unknown_input_does_not_erase_the_other_measured_one():
    p = default_parameters()
    axis = sorted(FatigueState.KEYS)[0]
    both_unknown = recovery_clearance_multiplier(axis, None, None, p)
    sleep_only = recovery_clearance_multiplier(axis, 10.0, None, p)
    assert sleep_only > both_unknown


# ── 0 is not None, at every consumer ─────────────────────────────────────────

def test_zero_and_none_differ_at_the_schema():
    assert _log().sleep_quality is None
    with pytest.raises(ValidationError):
        _log(sleep_quality=0.0)


@pytest.mark.parametrize("axis", sorted(FatigueState.KEYS))
def test_zero_and_none_differ_at_the_clearance_multiplier(axis: str):
    p = default_parameters()
    assert recovery_clearance_multiplier(axis, 0.0, 0.0, p) != pytest.approx(
        recovery_clearance_multiplier(axis, None, None, p)
    )


def test_zero_and_none_differ_in_the_calibration_frame():
    """``or 5.0`` mapped BOTH a missing report and a ``0`` onto the midpoint."""
    base = {
        "date": pd.Timestamp("2026-01-01"),
        "modality": "Strength",
        "duration_minutes": 60.0,
        "session_rpe": 7.0,
        "sets_eff": 4.0,
    }
    missing = build_log(pd.Series({**base, "sleep_quality": np.nan,
                                   "life_stress_inverse": np.nan}))
    assert missing.sleep_quality is None
    assert missing.life_stress_inverse is None

    # 0 is out of the 1-10 domain: it is now rejected as corrupt rather than laundered
    # into a plausible-looking 5.0.
    with pytest.raises(ValidationError):
        build_log(pd.Series({**base, "sleep_quality": 0.0, "life_stress_inverse": 0.0}))


def test_calibration_frame_preserves_a_real_report():
    log = build_log(pd.Series({
        "date": pd.Timestamp("2026-01-01"),
        "modality": "Strength",
        "duration_minutes": 60.0,
        "session_rpe": 7.0,
        "sets_eff": 4.0,
        "sleep_quality": 3.0,
        "life_stress_inverse": 8.0,
    }))
    assert log.sleep_quality == 3.0
    assert log.life_stress_inverse == 8.0


# ── Persistence: a gap lands as SQL NULL ─────────────────────────────────────

async def _create_user(db, email: str = "wellness-gap@example.com") -> User:
    user = User(email=email, hashed_password="hashed", is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _logged_wellness_row(db, user_id: int, log: WorkoutLog):
    """The raw (sleep_quality, life_stress_inverse) tuple straight out of SQL."""
    await process_new_workout(db, user_id=user_id, log=log)
    result = await db.execute(text(
        "SELECT sleep_quality, life_stress_inverse FROM workout_logs "
        "WHERE user_id = :uid ORDER BY id DESC LIMIT 1"
    ), {"uid": user_id})
    return result.one()


@pytest.mark.asyncio
async def test_workout_without_wellness_persists_sql_null(async_db):
    user = await _create_user(async_db, "gap-null@example.com")
    baseline = await initialize_athlete_state(async_db, user.id)
    row = await _logged_wellness_row(
        async_db, user.id, _log(timestamp=baseline.timestamp + timedelta(hours=24))
    )
    assert row[0] is None, f"sleep_quality persisted as {row[0]!r}, expected SQL NULL"
    assert row[1] is None, f"life_stress_inverse persisted as {row[1]!r}, expected SQL NULL"
    assert row[0] != 5.0
    assert row[1] != 5.0


@pytest.mark.asyncio
async def test_workout_with_wellness_persists_the_reported_value(async_db):
    user = await _create_user(async_db, "gap-reported@example.com")
    baseline = await initialize_athlete_state(async_db, user.id)
    row = await _logged_wellness_row(
        async_db,
        user.id,
        _log(
            timestamp=baseline.timestamp + timedelta(hours=24),
            sleep_quality=5.0,
            life_stress_inverse=8.0,
        ),
    )
    assert row[0] == 5.0, "a genuine 5/10 report must persist as 5.0, not NULL"
    assert row[1] == 8.0


@pytest.mark.asyncio
async def test_persisted_dose_snapshot_labels_the_wellness_gap(async_db):
    """The stored dose is auditable: the gap is recorded, not hidden."""
    user = await _create_user(async_db, "gap-snapshot@example.com")
    baseline = await initialize_athlete_state(async_db, user.id)
    await process_new_workout(
        async_db, user_id=user.id,
        log=_log(timestamp=baseline.timestamp + timedelta(hours=24)),
    )
    result = await async_db.execute(text(
        "SELECT dose_snapshot FROM workout_logs WHERE user_id = :uid "
        "ORDER BY id DESC LIMIT 1"
    ), {"uid": user.id})
    snapshot = result.scalar_one()
    assert snapshot["human_factor_gain"]["source"] == "neutral_missing"
    assert snapshot["human_factor_gain"]["confidence"] == 0.0
    assert snapshot["human_factor_gain"]["value"] == 1.0
