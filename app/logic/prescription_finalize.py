"""Attach provenance, validation, explainability, and structured-template scoring."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.vectors import CapacityConfidence
from app.logic.coaching_template_registry import get_structured_template_for_goal
from app.logic.confidence_presentation import (
    POLICY_VERSION,
    ConfidenceStatus,
    confidence_status,
)
from app.logic.constraint_engine import (
    SessionValidator,
    build_constraint_context,
    encode_session_candidate,
    simple_session_scorer,
)
from app.logic.goal_seed_emphasis import GOAL_AXIS_FLOOR, domain_for_goal
from app.logic.registries import (
    get_fallback_template,
    get_template_for_goal,
    primitive_names,
)
from app.schemas.prescription import (
    MeasurementRecommendation,
    PlanRevisionTrigger,
    PrescriptionConfidence,
    PrescriptionExplanation,
    StateEvidence,
    ValidationSummary,
    WorkoutPrescription,
)
from app.schemas.state import UnifiedStateVector
from app.schemas.training_goals import TrainingGoal

NO_DRIVERS_LABEL = "state within normal twin bands for prescription"
MAX_DRIVERS = 8


@dataclass(frozen=True)
class _DriverRule:
    """One threshold test, with everything needed to explain itself.

    The label and the evidence come from the same row, so the phrase a client reads and
    the number behind it cannot drift apart — which is what happened while the drivers
    were built by eight independent ``if`` statements that discarded their own inputs.
    """

    axis: str
    read: Callable[[UnifiedStateVector], float]
    threshold: float
    direction: Literal["above", "below"]
    label: str
    #: Firing predicate. Separate from ``threshold`` because one rule is two-sided:
    #: a low aerobic signal only counts when the axis is actually populated.
    fires: Callable[[float], bool]
    #: When an axis reads as "no signal yet" rather than a real low value. Such an axis has
    #: no meaningful crossing to report - the honest ask there is a measurement, not a
    #: threshold watch, and measurement_recommendations already covers it.
    unpopulated: Callable[[float], bool] | None = None
    #: Which ``capacity_confidence`` axis carries this rule's uncertainty, when one does.
    #: Declared rather than inferred from ``axis``: the rule reads the legacy scalar
    #: mirror (``c_met_aerobic``) while the variance lives under the decomposed name
    #: (``aerobic``), so name-matching would silently report "no uncertainty modelled"
    #: for the one driver that actually has some.
    confidence_axis: str | None = None


def _above(threshold: float) -> Callable[[float], bool]:
    return lambda v: v > threshold


_DRIVER_RULES: tuple[_DriverRule, ...] = (
    _DriverRule("f_nm_central", lambda s: s.f_nm_central, 55.0, "above",
                "elevated CNS / central fatigue", _above(55.0)),
    _DriverRule("f_nm_peripheral", lambda s: s.f_nm_peripheral, 55.0, "above",
                "elevated peripheral / muscular fatigue", _above(55.0)),
    _DriverRule("f_met_systemic", lambda s: s.f_met_systemic, 60.0, "above",
                "elevated systemic metabolic fatigue", _above(60.0)),
    _DriverRule("tissue_t.lumbar", lambda s: s.tissue_t.lumbar, 50.0, "above",
                "lumbar tissue stress", _above(50.0)),
    _DriverRule("tissue_t.wrist", lambda s: s.tissue_t.wrist, 50.0, "above",
                "wrist tissue stress", _above(50.0)),
    _DriverRule("tissue_t.knee", lambda s: s.tissue_t.knee, 55.0, "above",
                "knee tissue stress", _above(55.0)),
    _DriverRule("fatigue_f.tendon", lambda s: s.fatigue_f.tendon, 45.0, "above",
                "tendon fatigue", _above(45.0)),
    # Two-sided on purpose: 0.0 means "no aerobic signal yet", not "no aerobic capacity".
    _DriverRule("c_met_aerobic", lambda s: s.c_met_aerobic, 30.0, "below",
                "low aerobic capacity signal", lambda v: 0.0 < v < 30.0,
                unpopulated=lambda v: v <= 0.0,
                confidence_axis="aerobic"),
)

#: Capacity axes carry a live variance; these families do not, so their contribution to a
#: prescription has unknown certainty. Reported explicitly rather than left to look certain.
UNCERTAINTY_NOT_MODELLED = ["fatigue_f", "tissue_t", "skill_state"]


def _derive_state_evidence(state: UnifiedStateVector) -> list[StateEvidence]:
    """Every driver that fired, carrying the value and threshold that fired it."""
    bands = _capacity_bands(state)
    out: list[StateEvidence] = []
    for rule in _DRIVER_RULES:
        value = float(rule.read(state))
        if not rule.fires(value):
            continue
        out.append(
            StateEvidence(
                axis=rule.axis,
                label=rule.label,
                value=round(value, 4),
                threshold=rule.threshold,
                direction=rule.direction,
                # Only capacity axes have a variance model; everything else stays None,
                # which the schema documents as unknown certainty, not high certainty.
                confidence_status=(
                    bands.get(rule.confidence_axis) if rule.confidence_axis else None
                ),
            )
        )
    return out[:MAX_DRIVERS]


def _derive_state_drivers(state: UnifiedStateVector) -> list[str]:
    """Human-readable drivers for explainability.

    Derived from the evidence list so the two can never disagree. The
    "nothing fired" sentinel is a driver-only concept: an empty evidence list already
    says the same thing without inventing an observation.
    """
    labels = [e.label for e in _derive_state_evidence(state)]
    return labels or [NO_DRIVERS_LABEL]


def _capacity_bands(state: UnifiedStateVector) -> dict[str, ConfidenceStatus]:
    """Per-capacity-axis certainty from live variance, via the shared policy."""
    return {
        axis: confidence_status(getattr(state.capacity_confidence, axis))
        for axis in CapacityConfidence.KEYS
    }


#: Weakest-first ordering for picking the axis that should most limit trust.
_STATUS_RANK: dict[str, int] = {
    "insufficient": 0,
    "provisional": 1,
    "established": 2,
}


def _derive_confidence(state: UnifiedStateVector) -> PrescriptionConfidence:
    """Summarize how certain the twin is about the capacity it just prescribed against."""
    bands = _capacity_bands(state)
    weakest_axis: str | None = None
    weakest_status: ConfidenceStatus | None = None
    if bands:
        weakest_axis = min(
            bands, key=lambda a: (_STATUS_RANK.get(bands[a], 0), a)
        )
        weakest_status = bands[weakest_axis]
    return PrescriptionConfidence(
        policy_version=POLICY_VERSION,
        capacity_axes=bands,
        weakest_capacity_axis=weakest_axis,
        weakest_capacity_status=weakest_status,
        uncertainty_not_modelled=list(UNCERTAINTY_NOT_MODELLED),
    )


#: How many measurement suggestions are worth surfacing on one session.
MAX_MEASUREMENT_RECOMMENDATIONS = 4

#: Why each band is worth acting on, phrased for the athlete rather than the estimator.
_MEASUREMENT_REASON: dict[str, str] = {
    "insufficient": (
        "no observation has constrained this axis yet - its value is an unrefined prior, "
        "so anything this session infers from it is a guess"
    ),
    "provisional": (
        "only weakly constrained - one benchmark would materially sharpen it"
    ),
}


def _derive_measurement_recommendations(
    state: UnifiedStateVector, goal: TrainingGoal
) -> list[MeasurementRecommendation]:
    """Name the axes whose uncertainty most limits this plan, worst and most-relevant first.

    Uses the goal's own trained axes (``GOAL_AXIS_FLOOR``) to rank: an uncertain axis the
    athlete's domain actually trains outranks an equally uncertain one they never touch.
    An established axis is never suggested - there is nothing to gain by re-measuring it.
    """
    bands = _capacity_bands(state)
    domain = domain_for_goal(str(goal))
    goal_axes: set[str] = set(GOAL_AXIS_FLOOR.get(domain, {})) if domain else set()

    out = [
        MeasurementRecommendation(
            axis=axis,
            current_status=status,
            material_to_goal=axis in goal_axes,
            reason=_MEASUREMENT_REASON.get(status, ""),
        )
        for axis, status in bands.items()
        if status != "established"
    ]
    # Goal-relevant first, then least-certain first, then stable by name.
    out.sort(key=lambda r: (not r.material_to_goal, _STATUS_RANK.get(r.current_status, 0), r.axis))
    return out[:MAX_MEASUREMENT_RECOMMENDATIONS]


#: Active triggers are always shown; this caps how many *approaching* ones ride along.
MAX_INACTIVE_TRIGGERS = 3


def _trigger_condition(rule: "_DriverRule", fires_now: bool) -> str:
    """Phrase the crossing that would flip this driver."""
    if rule.direction == "above":
        return (
            f"{rule.axis} falls back to {rule.threshold:g} or below"
            if fires_now
            else f"{rule.axis} rises above {rule.threshold:g}"
        )
    return (
        f"{rule.axis} recovers to {rule.threshold:g} or above"
        if fires_now
        else f"{rule.axis} falls below {rule.threshold:g}"
    )


def _derive_plan_revision_triggers(state: UnifiedStateVector) -> list[PlanRevisionTrigger]:
    """What would change this plan - every active driver, plus the nearest approaching ones.

    Uses the prescriber's own thresholds, so a trigger can never contradict the reasoning
    that produced the session. Axes that are merely unpopulated are skipped: "measure this"
    is a recommendation, not a threshold to watch.
    """
    active: list[PlanRevisionTrigger] = []
    approaching: list[tuple[float, PlanRevisionTrigger]] = []

    for rule in _DRIVER_RULES:
        value = float(rule.read(state))
        if rule.unpopulated is not None and rule.unpopulated(value):
            continue
        fires_now = rule.fires(value)
        trigger = PlanRevisionTrigger(
            axis=rule.axis,
            label=rule.label,
            currently_active=fires_now,
            condition=_trigger_condition(rule, fires_now),
            current_value=round(value, 4),
            threshold=rule.threshold,
        )
        if fires_now:
            active.append(trigger)
        else:
            # Relative distance, so axes on different scales rank comparably.
            distance = abs(value - rule.threshold) / max(abs(rule.threshold), 1.0)
            approaching.append((distance, trigger))

    approaching.sort(key=lambda pair: (pair[0], pair[1].axis))
    return active + [t for _, t in approaching[:MAX_INACTIVE_TRIGGERS]]


def finalize_prescription(
    rx: WorkoutPrescription,
    state: UnifiedStateVector | None,
    goal: TrainingGoal,
    branch_id: str,
    recent_sessions: list[dict[str, Any]] | None = None,
) -> WorkoutPrescription:
    """
    Enrich prescription with `why`. If state is None (no athlete row), minimal explanation only.
    Hard constraint violations replace with a safe recovery session.
    Universal safety rules always run via SessionValidator; template-specific rules follow.
    """
    if state is None:
        out = rx.model_copy(deep=True)
        out.why = PrescriptionExplanation(
            state_drivers=["No AthleteState history — baseline not established"],
            goal_alignment=str(goal),
            constraints_applied=[],
            source_alignment=["Assessment required before twin-linked validation"],
            prescription_branch=branch_id,
            validation=ValidationSummary(passed=True, failed_checks=[], hard_violations=[]),
            warnings=[],
            score=None,
            structured_template_name=None,
        )
        return out

    program_template = get_template_for_goal(goal) or get_fallback_template()

    structured = get_structured_template_for_goal(goal)
    candidate = encode_session_candidate(rx, goal, branch_id)
    ctx = build_constraint_context(state, recent_sessions, goal)
    srep = SessionValidator(structured).validate(candidate, ctx)
    soft_warnings = srep.soft_warnings
    hard_violations = list(dict.fromkeys(srep.hard_failed))
    skipped_codes = srep.skipped_codes
    score_val: float | None = None
    if not hard_violations:
        score_val = simple_session_scorer(candidate, structured, state)

    out_rx = rx.model_copy(deep=True)
    rationale_suffix = ""

    if hard_violations:
        out_rx = WorkoutPrescription(
            type="Recovery",
            focus="Easy movement + mobility (constraint override)",
            rationale=(
                f"Hard domain constraints triggered: {', '.join(hard_violations[:6])}. "
                "Defaulting to a low-risk session until state improves."
            ),
            duration_min=min(rx.duration_min, 35) if rx.duration_min else 30,
        )
        vsummary = ValidationSummary(
            passed=False,
            failed_checks=soft_warnings,
            hard_violations=hard_violations,
        )
        rationale_suffix = f" [branch: {branch_id} → overridden]"
        score_val = None
    else:
        if soft_warnings:
            rationale_suffix = " " + "; ".join(soft_warnings[:4])
        vsummary = ValidationSummary(
            passed=True,
            failed_checks=soft_warnings,
            hard_violations=[],
        )

    prim_labels = primitive_names(program_template.provenance_primitive_ids)
    sources = [structured.source_name, program_template.source_name] + prim_labels
    if skipped_codes:
        sources.append(f"skipped_unregistered_rules:{len(skipped_codes)}")

    applied = list(
        dict.fromkeys(
            soft_warnings + program_template.constraint_rule_ids[:6] + hard_violations[:4]
        )
    )

    warnings_out = list(dict.fromkeys(soft_warnings))[:12]

    tid = structured.template_id
    st_name = structured.name

    evidence = _derive_state_evidence(state)
    out_rx.why = PrescriptionExplanation(
        state_drivers=[e.label for e in evidence] or [NO_DRIVERS_LABEL],
        state_evidence=evidence,
        confidence=_derive_confidence(state),
        measurement_recommendations=_derive_measurement_recommendations(state, goal),
        plan_revision_triggers=_derive_plan_revision_triggers(state),
        goal_alignment=str(goal),
        constraints_applied=applied,
        source_alignment=sources[:14],
        template_id=tid,
        prescription_branch=branch_id,
        validation=vsummary,
        warnings=warnings_out,
        score=score_val,
        structured_template_name=st_name,
    )

    if rationale_suffix and not hard_violations:
        out_rx.rationale = (out_rx.rationale + rationale_suffix).strip()

    return out_rx
