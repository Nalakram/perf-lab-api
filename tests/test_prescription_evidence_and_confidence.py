"""A prescription must carry the evidence behind its claims and its own certainty.

Two of the eight explanations the twin is supposed to deliver were absent from the
response contract: *what evidence supports this* and *how confident is it*.
``state_drivers`` collapsed each threshold test to a phrase and threw away the number that
fired it, and no field anywhere carried a variance, interval, or confidence band — grepping
``confidence|variance|uncertain|interval`` over app/schemas/prescription.py returned nothing.

Both were cheap because the data was already in hand: ``finalize_prescription`` receives the
whole state vector, and ``_derive_state_drivers`` already read the exact numeric behind each
label before discarding it.
"""

from datetime import UTC, datetime

from app.domain.vectors import CapacityConfidence
from app.logic.confidence_presentation import POLICY_VERSION
from app.logic.prescription_finalize import (
    NO_DRIVERS_LABEL,
    UNCERTAINTY_NOT_MODELLED,
    _derive_confidence,
    _derive_measurement_recommendations,
    _derive_state_drivers,
    _derive_state_evidence,
)
from app.schemas.state import UnifiedStateVector


def _state(**over: object) -> UnifiedStateVector:
    base: dict[str, object] = {
        "timestamp": datetime.now(UTC),
        "c_met_aerobic": 500.0,
        "c_nm_force": 50.0,
        "c_struct": 50.0,
        "b_met_anaerobic": 50.0,
    }
    base.update(over)
    return UnifiedStateVector(**base)  # type: ignore[arg-type]


# ── evidence carries the number, not just the phrase ──────────────────────────


def test_evidence_carries_the_value_and_threshold_that_fired_it() -> None:
    ev = _derive_state_evidence(_state(f_nm_central=70.0))

    assert len(ev) == 1
    e = ev[0]
    assert e.axis == "f_nm_central"
    assert e.label == "elevated CNS / central fatigue"
    assert e.value == 70.0
    assert e.threshold == 55.0
    assert e.direction == "above"


def test_drivers_and_evidence_can_never_disagree() -> None:
    """Both are emitted from one rule table, so the phrase always matches the number.

    They were previously eight independent ``if`` statements producing only strings; a
    threshold edited in one place and not the other could not be detected.
    """
    state = _state(f_nm_central=70.0, f_met_systemic=80.0, c_met_aerobic=20.0)

    drivers = _derive_state_drivers(state)
    evidence = _derive_state_evidence(state)

    assert drivers == [e.label for e in evidence]
    for e in evidence:
        if e.direction == "above":
            assert e.value > e.threshold
        else:
            assert e.value < e.threshold


def test_no_driver_fires_means_empty_evidence_not_an_invented_observation() -> None:
    """The "all normal" sentinel is a driver-only phrase; evidence stays empty.

    Emitting a synthetic evidence row for "nothing fired" would be exactly the
    missing-becomes-a-number failure this codebase is trying to stop.
    """
    state = _state()

    assert _derive_state_drivers(state) == [NO_DRIVERS_LABEL]
    assert _derive_state_evidence(state) == []


def test_a_two_sided_rule_does_not_fire_on_an_unpopulated_axis() -> None:
    """c_met_aerobic == 0.0 means "no aerobic signal yet", not "no aerobic capacity"."""
    assert _derive_state_evidence(_state(c_met_aerobic=0.0)) == []
    assert _derive_state_evidence(_state(c_met_aerobic=20.0))[0].axis == "c_met_aerobic"


# ── certainty, including the certainty that is missing ────────────────────────


def test_capacity_backed_driver_carries_its_confidence_band() -> None:
    """The rule reads the legacy scalar mirror; the variance lives under the decomposed name.

    ``c_met_aerobic`` vs ``capacity_confidence.aerobic`` — matching on the axis name alone
    would silently report "no uncertainty modelled" for the one driver that has some, and
    nothing else in the payload would look wrong. This pins the declared mapping.
    """
    ev = _derive_state_evidence(_state(c_met_aerobic=20.0))

    assert len(ev) == 1
    assert ev[0].confidence_status is not None


def test_unmodelled_axes_report_null_certainty_not_high_certainty() -> None:
    """Fatigue and tissue carry no variance anywhere in the engine.

    Reporting None (documented as UNKNOWN) rather than omitting the field keeps a reader
    from taking silence for confidence.
    """
    ev = _derive_state_evidence(_state(f_nm_central=70.0, tissue_t={"lumbar": 60.0}))

    assert {e.axis for e in ev} == {"f_nm_central", "tissue_t.lumbar"}
    assert all(e.confidence_status is None for e in ev)


def test_confidence_names_the_state_families_it_cannot_model() -> None:
    c = _derive_confidence(_state())

    assert set(c.uncertainty_not_modelled) == set(UNCERTAINTY_NOT_MODELLED)
    assert "fatigue_f" in c.uncertainty_not_modelled
    assert "tissue_t" in c.uncertainty_not_modelled


def test_confidence_covers_every_capacity_axis() -> None:
    c = _derive_confidence(_state())

    assert set(c.capacity_axes) == set(CapacityConfidence.KEYS)


def test_confidence_reuses_the_shared_policy_version() -> None:
    """The band thresholds must not be re-declared here.

    confidence_presentation.py owns them precisely so consumers cannot drift; if this
    stops matching, some caller has started deciding certainty on its own.
    """
    assert _derive_confidence(_state()).policy_version == POLICY_VERSION


def test_weakest_axis_is_the_least_certain_one() -> None:
    """The weakest axis is what should most limit trust in the prescription."""
    conf = CapacityConfidence()
    # Established (low variance) everywhere except one deliberately starved axis.
    for axis in CapacityConfidence.KEYS:
        setattr(conf, axis, 0.05)
    conf.max_strength = 1.4  # above PROVISIONAL_MAX_VARIANCE -> insufficient

    c = _derive_confidence(_state(capacity_confidence=conf))

    assert c.weakest_capacity_axis == "max_strength"
    assert c.weakest_capacity_status == "insufficient"
    assert c.capacity_axes["aerobic"] == "established"


# ── measurement recommendations ───────────────────────────────────────────────


def _conf(**over: float) -> CapacityConfidence:
    """All axes established except the ones named."""
    c = CapacityConfidence()
    for axis in CapacityConfidence.KEYS:
        setattr(c, axis, 0.05)
    for axis, var in over.items():
        setattr(c, axis, var)
    return c


def test_established_axes_are_never_suggested_for_measurement() -> None:
    """Nothing is gained by re-measuring an axis the twin already knows."""
    recs = _derive_measurement_recommendations(_state(capacity_confidence=_conf()), "powerlifting")

    assert recs == []


def test_goal_relevant_uncertainty_outranks_more_severe_irrelevant_uncertainty() -> None:
    """This is the whole point of ranking: relevance beats raw severity.

    mobility is *more* uncertain than hypertrophy, but powerlifting does not train it, so
    the axis the athlete actually loads is the one worth measuring first.
    """
    state = _state(
        capacity_confidence=_conf(max_strength=1.4, hypertrophy=0.9, mobility=1.4)
    )

    recs = _derive_measurement_recommendations(state, "powerlifting")
    axes = [r.axis for r in recs]

    assert axes[0] == "max_strength"
    assert axes.index("hypertrophy") < axes.index("mobility")
    assert [r.material_to_goal for r in recs][:2] == [True, True]


def test_every_recommendation_explains_why() -> None:
    state = _state(capacity_confidence=_conf(max_strength=1.4, hypertrophy=0.9))

    for r in _derive_measurement_recommendations(state, "powerlifting"):
        assert r.reason, f"{r.axis} recommended with no reason"
        assert r.current_status != "established"


def test_an_unrecognised_goal_still_recommends_by_severity() -> None:
    """No goal domain means no relevance signal — rank on certainty alone, never crash."""
    state = _state(capacity_confidence=_conf(max_strength=1.4, hypertrophy=0.9))

    recs = _derive_measurement_recommendations(state, "not-a-real-goal")

    assert [r.axis for r in recs] == ["max_strength", "hypertrophy"]
    assert all(r.material_to_goal is False for r in recs)
