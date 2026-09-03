"""An observation marked unfit to prescribe from must not size the bar.

``affects_prescription`` was written by three paths and read by none, so
``state_service._extract_e1rm_observations``'s promise - "a below-watermark set is
history only - not even a prescription basis" - was not enforced anywhere. The e1RM
basis query filtered on ``validity_status`` alone and took the latest observation,
whatever the flag said.

The invariant these tests pin is stronger than "False rows are filtered", because that
phrasing can be satisfied by the one query that happens to be patched. It is stated
against the ATHLETE-VISIBLE OUTCOME instead:

    Given two otherwise identical observations, toggling only affects_prescription
    True -> False must leave the next prescription exactly as it was before that
    observation existed.

and paired with the positive control, so a filter that rejects everything cannot pass.
``test_dose_denominator_agrees_with_prescribed_load`` extends it across the ADR-0056
pairing: both e1RM readers must reach the same number, which is what stops a future
reader from bypassing the predicate and quietly reintroducing the divergence.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.benchmark_definition import BenchmarkDefinition
from app.models.benchmark_observation import BenchmarkObservation
from app.models.exercise import Exercise
from app.models.user import User
from app.schemas.benchmarks import BenchmarkObservationCreate
from app.schemas.prescription import ExercisePrescription, WorkoutPrescription
from app.services import benchmark_service
from app.services.prescription_service import _enrich_exercises_with_load
from app.services.state_service import prelog_e1rm_denominators

pytestmark = pytest.mark.asyncio

_CODE = "pl_e1rm_squat"
_RULES = {"floor": 40.0, "cap": 250.0}
_BLOCK = {"week_number": 1, "duration_weeks": 4}
#: Every observation is stamped relative to this, so "newer" is unambiguous.
_T0 = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)


async def _setup(db, email: str) -> User:
    """An athlete with a squat in the catalog and a squat e1RM benchmark defined."""
    user = User(email=email, hashed_password="hashed", is_active=True)
    db.add(user)
    db.add(Exercise(
        name="Back Squat", modality="Strength", movement_pattern="squat",
        load_type="barbell", is_benchmark=True, e1rm_benchmark_code=_CODE,
    ))
    db.add(BenchmarkDefinition(
        code=_CODE, name="Squat e1RM", domain="powerlifting",
        metric_type="load", unit="kg", better_direction="higher",
        observation_weight=1.0, standardization_rules=_RULES,
    ))
    await db.commit()
    await db.refresh(user)
    return user


async def _observe(db, user_id: int, raw: float, *, days: int, affects: bool) -> None:
    """Record an e1RM observation through the service, as every real writer does."""
    await benchmark_service.create_observation(
        db, user_id,
        BenchmarkObservationCreate(
            benchmark_code=_CODE, raw_value=raw, source="benchmark_test",
            observed_at=_T0 + timedelta(days=days), affects_prescription=affects,
        ),
    )


async def _observe_without_stating_the_flag(db, user_id: int, raw: float, *, days: int) -> None:
    """Write an observation the way the corpus-ingest scripts used to: flag omitted.

    Deliberately bypasses ``create_observation`` (which defaults the flag to True) to
    produce a genuine SQL NULL - the "nobody ever said" case.
    """
    def_id = (await db.execute(
        select(BenchmarkDefinition.id).where(BenchmarkDefinition.code == _CODE)
    )).scalar_one()
    db.add(BenchmarkObservation(
        user_id=user_id, benchmark_definition_id=def_id, raw_value=raw,
        source="synthetic:strength_standards", observed_at=_T0 + timedelta(days=days),
    ))
    await db.commit()


def _squat_rx() -> WorkoutPrescription:
    return WorkoutPrescription(
        type="strength", focus="squat", rationale="x", duration_min=60,
        exercises=[ExercisePrescription(
            name="Back Squat", sets=3, reps="5", load_note="Autoregulate by RPE"
        )],
    )


async def _prescribe(db, user_id: int) -> ExercisePrescription:
    """The squat as it would actually be prescribed to this athlete right now."""
    rx = _squat_rx()
    await _enrich_exercises_with_load(db, user_id, rx, _BLOCK)
    return rx.exercises[0]


async def test_rejected_observation_leaves_the_prescription_exactly_as_it_was(async_db):
    user = await _setup(async_db, "basis-reject@test.com")
    await _observe(async_db, user.id, 140.0, days=0, affects=True)
    before = await _prescribe(async_db, user.id)

    # A newer, heavier observation the athlete explicitly marked unfit to prescribe from.
    await _observe(async_db, user.id, 180.0, days=1, affects=False)
    after = await _prescribe(async_db, user.id)

    assert before.e1rm_basis_kg == 140.0, "precondition: the accepted observation is the basis"
    assert after.e1rm_basis_kg == before.e1rm_basis_kg, (
        "a rejected observation must not become the prescription basis"
    )
    assert after.prescribed_load_kg == before.prescribed_load_kg, (
        "and must not move the prescribed load"
    )
    assert after.percent_e1rm == before.percent_e1rm


async def test_the_same_observation_accepted_does_move_the_prescription(async_db):
    """Positive control: a filter that rejects everything must not pass the test above."""
    user = await _setup(async_db, "basis-accept@test.com")
    await _observe(async_db, user.id, 140.0, days=0, affects=True)
    before = await _prescribe(async_db, user.id)

    await _observe(async_db, user.id, 180.0, days=1, affects=True)
    after = await _prescribe(async_db, user.id)

    assert after.e1rm_basis_kg == 180.0
    assert after.prescribed_load_kg is not None and before.prescribed_load_kg is not None
    assert after.prescribed_load_kg > before.prescribed_load_kg


async def test_an_observation_that_never_stated_the_flag_is_not_a_basis(async_db):
    """NULL is "nobody said", and absence of a statement is not permission."""
    user = await _setup(async_db, "basis-null@test.com")
    await _observe(async_db, user.id, 140.0, days=0, affects=True)
    before = await _prescribe(async_db, user.id)

    await _observe_without_stating_the_flag(async_db, user.id, 180.0, days=1)
    after = await _prescribe(async_db, user.id)

    assert after.e1rm_basis_kg == before.e1rm_basis_kg == 140.0
    assert after.prescribed_load_kg == before.prescribed_load_kg


async def test_dose_denominator_agrees_with_prescribed_load(async_db):
    """ADR-0056 across the seam: both e1RM readers must resolve the same number.

    ``prelog_e1rm_denominators`` sizes dose intensity (I = load / e1RM_pre) and
    ``_current_e1rm_values`` sizes the prescribed load. If only one honoured the flag,
    an athlete would be prescribed against 140 and scored against 180.
    """
    user = await _setup(async_db, "basis-pairing@test.com")
    await _observe(async_db, user.id, 140.0, days=0, affects=True)
    await _observe(async_db, user.id, 180.0, days=1, affects=False)

    prescribed = await _prescribe(async_db, user.id)
    denominators = await prelog_e1rm_denominators(async_db, user.id, {_CODE})

    assert denominators[_CODE]["value"] == 140.0
    assert prescribed.e1rm_basis_kg == denominators[_CODE]["value"], (
        "dose intensity and prescribed load must resolve the same e1RM"
    )
