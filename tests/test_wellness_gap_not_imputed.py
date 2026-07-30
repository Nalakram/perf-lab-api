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
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


# ── Contract: optional-and-nullable is NOT the same as defaulted ─────────────
#
# These are different failure modes, and a test that only checks "the field is
# optional" passes on the DEFECTIVE shape: `sleep_quality: float = Field(5.0, ...)`
# is also optional in the request. What distinguishes them is what absence MEANS —
# `None` versus a fabricated number — and whether the published contract advertises
# a default. The last assertion is the one that would have caught the original bug
# from the outside, without reading a line of Python.

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WELLNESS_FIELDS = ("sleep_quality", "life_stress_inverse")


def _workout_log_schema(source: dict) -> dict:
    return source["components"]["schemas"]["WorkoutLog"]


def _live_openapi() -> dict:
    from app.main import app

    return app.openapi()


def _committed_openapi() -> dict:
    return json.loads((_REPO_ROOT / "openapi.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", _WELLNESS_FIELDS)
def test_absence_yields_none_not_a_number(field: str):
    """Optional-and-nullable: omitting it produces ``None``, never a float."""
    value = getattr(_log(), field)
    assert value is None
    assert not isinstance(value, float)


@pytest.mark.parametrize("field", _WELLNESS_FIELDS)
def test_explicit_null_is_accepted_and_yields_none(field: str):
    log = WorkoutLog.model_validate({
        "timestamp": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        "modality": "Strength",
        "duration_minutes": 60.0,
        "session_rpe": 7.0,
        field: None,
    })
    assert getattr(log, field) is None


@pytest.mark.parametrize("field", _WELLNESS_FIELDS)
def test_supplied_value_still_enforces_the_range(field: str):
    assert getattr(_log(**{field: 1.0}), field) == 1.0
    assert getattr(_log(**{field: 10.0}), field) == 10.0
    with pytest.raises(ValidationError):
        _log(**{field: 10.5})
    with pytest.raises(ValidationError):
        _log(**{field: 0.5})


@pytest.mark.parametrize("field", _WELLNESS_FIELDS)
def test_zero_is_rejected_not_silently_treated_as_unknown(field: str):
    """``0`` is out of domain. It must raise, not become a stand-in for missing."""
    with pytest.raises(ValidationError):
        _log(**{field: 0.0})
    assert getattr(_log(), field) is None  # the only spelling of unknown


@pytest.mark.parametrize("source_name,loader", [("live app", _live_openapi), ("committed openapi.json", _committed_openapi)])
@pytest.mark.parametrize("field", _WELLNESS_FIELDS)
def test_published_contract_carries_no_default_for_wellness(field: str, source_name: str, loader):
    """THE OUTSIDE-IN CATCH: the contract must not advertise a default.

    Checked against BOTH the live app schema and the committed ``openapi.json``. The
    live check catches a Python-side regression the instant it happens; the committed
    check catches a stale artefact being shipped to the frontend. A regression that
    restored ``Field(5.0, ...)`` fails the live arm even if nobody regenerated the file.
    """
    schema = _workout_log_schema(loader())
    prop = schema["properties"][field]
    assert "default" not in prop, (
        f"{source_name}: WorkoutLog.{field} advertises a default ({prop.get('default')!r}). "
        "A defaulted field is not the same as an optional-and-nullable one — absence must "
        "mean unknown, not a fabricated value (ADR-0049)."
    )
    assert field not in schema.get("required", []), f"{source_name}: {field} must stay optional"
    # Optional-and-NULLABLE: the union must actually admit null.
    assert {"type": "null"} in prop["anyOf"], (
        f"{source_name}: WorkoutLog.{field} must admit null, not merely be omittable"
    )
    numeric = [b for b in prop["anyOf"] if b.get("type") == "number"]
    assert numeric and numeric[0]["minimum"] == 1.0 and numeric[0]["maximum"] == 10.0, (
        f"{source_name}: the 1-10 bounds must survive on the non-null branch"
    )


# ── End to end: the gap survives every layer, request → disk → engine ────────

@pytest.mark.asyncio
async def test_no_checkin_stays_unknown_from_request_to_disk_to_engine(http_client, async_db):
    """THE WHOLE CHAIN, IN ONE TEST, for the no-check-in case (#199).

    The original defect survived precisely because every layer looked locally
    reasonable. So this asserts each link explicitly, and reads the row BACK FROM THE
    DATABASE rather than inferring persistence from the request or the model:

        request OMITS both keys
          -> the validated Pydantic model holds None (not 5.0, not 0)
          -> the persisted row holds SQL NULL
          -> the engine emits the identity contribution + missing provenance

    Both field names are asserted by name. ``life_stress_inverse`` is the one a
    half-done fix leaves broken, because the frontend calls it ``mood``.
    """
    email = "chain-nocheckin@example.com"
    reg = await http_client.post("/auth/register", json={"email": email, "password": "testpass99"})
    assert reg.status_code == 201, reg.text
    tok = await http_client.post(
        "/auth/token",
        data={"username": email, "password": "testpass99"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = tok.json()["access_token"]

    # LINK 1 — the request body genuinely omits both keys (this is what the frontend
    # now sends when the athlete has not checked in; see workoutLogBody.ts).
    body = {
        "timestamp": datetime.now(UTC).isoformat(),
        "modality": "Strength",
        "duration_minutes": 60.0,
        "session_rpe": 7.0,
    }
    assert "sleep_quality" not in body
    assert "life_stress_inverse" not in body

    # LINK 2 — the validated Pydantic model holds None, not a substituted number.
    parsed = WorkoutLog.model_validate(body)
    assert parsed.sleep_quality is None
    assert parsed.life_stress_inverse is None
    assert parsed.sleep_quality != 5.0 and parsed.life_stress_inverse != 5.0
    assert parsed.sleep_quality != 0.0 and parsed.life_stress_inverse != 0.0

    resp = await http_client.post(
        "/v1/log-workout", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text

    # LINK 3 — the PERSISTED row is SQL NULL. Read back from the database.
    row = (await async_db.execute(text(
        "SELECT sleep_quality, life_stress_inverse, dose_snapshot FROM workout_logs "
        "ORDER BY id DESC LIMIT 1"
    ))).one()
    assert row[0] is None, f"sleep_quality persisted as {row[0]!r}, expected SQL NULL"
    assert row[1] is None, f"life_stress_inverse persisted as {row[1]!r}, expected SQL NULL"

    # LINK 4 — the engine emitted the identity contribution and missing provenance.
    hf = row[2]["human_factor_gain"]
    assert hf["value"] == 1.0, "missing wellness must be the multiplicative identity"
    assert hf["source"] == "neutral_missing"
    assert hf["confidence"] == 0.0
    by_name = {i["name"]: i for i in hf["inputs"]}
    for field in _WELLNESS_FIELDS:
        assert by_name[field]["value"] is None
        assert by_name[field]["source"] == "neutral_missing"
        assert by_name[field]["confidence"] == 0.0
        assert by_name[field]["penalty"] == 1.0, "identity: no penalty for an unknown input"

    # LINK 4b — identity on the RECOVERY side too, not only the dose.
    p = default_parameters()
    for axis in sorted(FatigueState.KEYS):
        assert recovery_clearance_multiplier(axis, None, None, p) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_completed_checkin_persists_the_exact_values_both_fields(http_client, async_db):
    """The other side of the matrix: a real check-in is stored verbatim, by field name."""
    email = "chain-checkin@example.com"
    await http_client.post("/auth/register", json={"email": email, "password": "testpass99"})
    tok = await http_client.post(
        "/auth/token",
        data={"username": email, "password": "testpass99"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = tok.json()["access_token"]

    # Deliberately different values, at opposite ends, so a transposed mapping fails.
    body = {
        "timestamp": datetime.now(UTC).isoformat(),
        "modality": "Strength",
        "duration_minutes": 60.0,
        "session_rpe": 7.0,
        "sleep_quality": 10.0,
        "life_stress_inverse": 1.0,
    }
    resp = await http_client.post(
        "/v1/log-workout", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text

    row = (await async_db.execute(text(
        "SELECT sleep_quality, life_stress_inverse, dose_snapshot FROM workout_logs "
        "ORDER BY id DESC LIMIT 1"
    ))).one()
    assert row[0] == 10.0, "sleep_quality must persist verbatim"
    assert row[1] == 1.0, "life_stress_inverse must persist verbatim (frontend `mood`)"

    hf = row[2]["human_factor_gain"]
    assert hf["source"] == "reported"
    assert hf["confidence"] == 1.0
    by_name = {i["name"]: i for i in hf["inputs"]}
    assert by_name["sleep_quality"]["value"] == 10.0
    assert by_name["life_stress_inverse"]["value"] == 1.0
    # Measured behaviour preserved bit for bit: the worst-case life-stress report still
    # penalises exactly as the pre-change equation says.
    assert by_name["life_stress_inverse"]["penalty"] == pytest.approx(_expected_penalty(1.0))
    assert by_name["sleep_quality"]["penalty"] == pytest.approx(_expected_penalty(10.0))


def test_confidence_never_scales_the_dose():
    """PROHIBITION (user ruling): confidence must not be smuggled back into the mean.

    ``ΔS_applied != c_aggregate × ΔS_base``. An athlete who supplies less data must not
    receive less training. Proven by construction: the six-axis dose for a log with NO
    wellness (confidence 0.0) is identical to one whose reported wellness earns no
    penalty (confidence 1.0). If confidence were ever multiplied into the dose, the
    zero-confidence vector would shrink and these would diverge.
    """
    unknown = calculate_stress_dose(_log())
    reported_no_penalty = calculate_stress_dose(_log(sleep_quality=10.0, life_stress_inverse=10.0))
    assert unknown.human_factor_gain is not None
    assert reported_no_penalty.human_factor_gain is not None
    assert unknown.human_factor_gain.confidence == 0.0
    assert reported_no_penalty.human_factor_gain.confidence == 1.0
    for axis in _SIX_AXES:
        assert getattr(unknown.dose_six, axis) == pytest.approx(
            getattr(reported_no_penalty.dose_six, axis)
        ), "confidence must scale nothing"
    for legacy in ("d_met_systemic", "d_nm_peripheral", "d_nm_central",
                   "d_struct_damage", "d_struct_signal"):
        assert getattr(unknown, legacy) == pytest.approx(getattr(reported_no_penalty, legacy))
    # Adaptation too: it is divided by the gain, never by the confidence.
    for key in ("c_met_aerobic", "c_nm_force"):
        if hasattr(unknown.adaptation_contribution, key):
            assert getattr(unknown.adaptation_contribution, key) == pytest.approx(
                getattr(reported_no_penalty.adaptation_contribution, key)
            )
