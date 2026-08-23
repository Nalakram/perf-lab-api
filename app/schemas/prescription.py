"""Workout prescription + structured explainability (backward compatible)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# Same source of truth the Twin's history view uses. Importing the policy rather than
# restating its bands is deliberate: confidence_presentation.py owns the thresholds so
# consumers cannot drift from them (schemas/state.py imports it for the same reason).
from app.logic.confidence_presentation import ConfidenceStatus


class ValidationSummary(BaseModel):
    """Result of validate_session checks."""

    passed: bool
    failed_checks: list[str] = Field(default_factory=list)
    hard_violations: list[str] = Field(default_factory=list)


class StateEvidence(BaseModel):
    """The measurement behind one state driver, not just the phrase it produced.

    ``state_drivers`` collapses a threshold test to a string ("elevated CNS / central
    fatigue"), discarding the number that fired it — so a client can read *what* the
    system concluded but never *what it saw*. Each entry here is the same test with its
    evidence intact, emitted from the same rule table, so the label and the number cannot
    disagree.
    """

    axis: str = Field(description="State field the test read, e.g. 'f_nm_central'.")
    label: str = Field(description="The human-readable driver this produced.")
    value: float = Field(description="The observed value on that axis.")
    threshold: float = Field(description="The threshold it was compared against.")
    direction: Literal["above", "below"] = Field(
        description="Whether firing means the value sat above or below the threshold."
    )
    confidence_status: ConfidenceStatus | None = Field(
        default=None,
        description=(
            "Certainty band for this axis, when the axis has a variance model. NULL means "
            "the engine models no uncertainty for it at all (fatigue, tissue and skill "
            "carry no variance) — that is UNKNOWN certainty, not high certainty."
        ),
    )


class PrescriptionConfidence(BaseModel):
    """How certain the twin is about the state this prescription was built on.

    Derived from the live per-axis ``capacity_confidence`` variance via the shared
    ``confidence_presentation_policy``. Reported, not yet acted on: nothing in the
    prescriber currently widens or narrows a recommendation based on these bands.
    """

    policy_version: str = Field(description="Confidence-presentation policy that produced the bands.")
    capacity_axes: dict[str, ConfidenceStatus] = Field(
        default_factory=dict,
        description="Per-capacity-axis certainty band derived from live variance.",
    )
    weakest_capacity_axis: str | None = Field(
        default=None,
        description="The least certain capacity axis — the one that should most constrain trust.",
    )
    weakest_capacity_status: ConfidenceStatus | None = None
    uncertainty_not_modelled: list[str] = Field(
        default_factory=list,
        description=(
            "State families the engine keeps NO uncertainty for. Their contribution to this "
            "prescription has unknown certainty; the absence is reported rather than being "
            "allowed to read as confidence."
        ),
    )


class MeasurementRecommendation(BaseModel):
    """What to measure next to make the twin less unsure about THIS goal.

    The goal's rule is that a missing optional measurement should reduce certainty rather
    than make the app unusable — so the honest response to low confidence is to say what
    would raise it. Ranked so an axis the athlete's own goal actually trains outranks an
    equally-uncertain axis they never touch.
    """

    axis: str = Field(description="Capacity axis whose uncertainty a measurement would reduce.")
    current_status: ConfidenceStatus = Field(description="The axis's certainty band right now.")
    material_to_goal: bool = Field(
        description="Whether this axis is one the athlete's current goal domain actually trains."
    )
    reason: str = Field(description="Why this axis is worth measuring.")


class PlanRevisionTrigger(BaseModel):
    """A concrete state change that would make this session the wrong call.

    Every driver is a threshold test, so each one already implies its own falsification
    condition: the crossing that would start it applying, or stop it. Surfacing those turns
    "here is your session" into "here is your session, and here is what would change it" -
    without any new modelling, because the thresholds are the same ones the prescriber used.
    """

    axis: str = Field(description="State field this trigger watches.")
    label: str = Field(description="The driver that would start or stop applying.")
    currently_active: bool = Field(
        description="True if this driver is firing now, so the trigger describes it switching OFF."
    )
    condition: str = Field(description="The crossing that would revise the plan.")
    current_value: float = Field(description="Where the axis sits today.")
    threshold: float = Field(description="The value it would have to cross.")


class ConservatismSummary(BaseModel):
    """Whether the twin's own uncertainty made this session more cautious.

    Reports the decision either way, including when it declined to act, so "the plan was not
    softened" is visibly a choice rather than an absence. ``applied`` is the only field that
    says the prescription actually changed - in ``shadow`` mode the reduction is described
    but ``effective_rpe_cap`` still equals the baseline.
    """

    mode: str = Field(description="off | shadow | on - the tri-state flag's value for this session.")
    applied: bool = Field(description="True only if the prescribed cap actually moved.")
    basis_status: ConfidenceStatus | None = Field(
        default=None,
        description="Certainty of the weakest capacity axis, which is what the rule acts on.",
    )
    baseline_rpe_cap: float = Field(description="The RPE cap the ADR-0029 envelope produced.")
    effective_rpe_cap: float = Field(description="The cap actually used to resolve load.")
    reason: str = Field(description="Why the rule did or did not act.")


class ExpectedOutcome(BaseModel):
    """What the twin predicts this session will do to one state axis.

    A point prediction from the engine's own forward model - the same path MPC rolls out
    with - not a separate estimate invented for display. ``interval`` is deliberately
    absent rather than fabricated: the forward model is deterministic and the fatigue and
    tissue families carry no variance anywhere in the engine, so there is no honest spread
    to report. See ``PrescriptionConfidence.uncertainty_not_modelled``.
    """

    axis: str = Field(description="State axis the prediction is about, e.g. 'fatigue_f.cns'.")
    current: float = Field(description="Where the axis sits before the session.")
    predicted: float = Field(description="Where the forward model puts it immediately after.")
    delta: float = Field(description="predicted - current. Positive means the session adds load.")


class PrescriptionExplanation(BaseModel):
    """Why this session — state drivers, constraints, sources."""

    state_drivers: list[str] = Field(default_factory=list)
    # `default_factory=lambda: []` rather than `list`, matching `exercises` below: with a
    # custom model as the element type, bare `list` infers list[Unknown] and trips the
    # strict-pyright gate on the runtime request path.
    state_evidence: list[StateEvidence] = Field(
        default_factory=lambda: [],
        description=(
            "The numbers behind ``state_drivers``, one entry per driver that fired. Empty "
            "when no driver fired, or when there is no athlete state yet."
        ),
    )
    confidence: "PrescriptionConfidence | None" = Field(
        default=None,
        description="Certainty of the twin state this session was built on. NULL when no state exists.",
    )
    plan_revision_triggers: list[PlanRevisionTrigger] = Field(
        default_factory=lambda: [],
        description=(
            "What would change this plan: the drivers currently applying that would switch "
            "off, and the nearest ones that would switch on. Derived from the same "
            "thresholds the prescriber used, so they cannot disagree."
        ),
    )
    expected_outcomes: list[ExpectedOutcome] = Field(
        default_factory=lambda: [],
        description=(
            "What this session is predicted to do, largest movement first, from the engine's "
            "forward model. Point predictions with no interval - the model is deterministic "
            "and these axes carry no variance. Empty when no state exists to predict from."
        ),
    )
    expected_outcome_horizon: str | None = Field(
        default=None,
        description="What the prediction is *of*, so it cannot be read as a longer-range claim.",
    )
    conservatism: "ConservatismSummary | None" = Field(
        default=None,
        description=(
            "Whether low confidence made this session more cautious. NULL when load was "
            "never resolved for this prescription (no lift with a current e1RM)."
        ),
    )
    measurement_recommendations: list[MeasurementRecommendation] = Field(
        default_factory=lambda: [],
        description=(
            "What to measure to sharpen this plan, worst-first with goal-relevant axes "
            "prioritised. Empty when every capacity axis is already established."
        ),
    )
    goal_alignment: str = ""
    constraints_applied: list[str] = Field(default_factory=list)
    source_alignment: list[str] = Field(
        default_factory=list,
        description="Human-readable: templates + primitives + models",
    )
    template_id: str | None = None
    prescription_branch: str | None = Field(
        default=None,
        description="Internal prescriber branch id (safety, readiness, goal path)",
    )
    validation: ValidationSummary | None = None
    warnings: list[str] = Field(
        default_factory=list,
        description="Soft constraint / template warnings (non-blocking)",
    )
    score: float | None = Field(
        default=None,
        description="Template-aligned fit score vs twin state (0–1)",
    )
    structured_template_name: str | None = Field(
        default=None,
        description="Display name for structured coaching template (v2)",
    )


class ExercisePrescription(BaseModel):
    """A single prescribed exercise within a session."""
    name: str
    sets: int | None = None
    reps: str | None = None
    load_note: str | None = None
    weak_point_tags: list[str] = Field(default_factory=list)

    # ADR-0045: strength prescriptions speak in load. When the athlete has a current
    # e1RM for this lift, the service resolves %e1RM → a suggested working kg against
    # the ADR-0029 intensity envelope, plus an RPE cap. Absent an e1RM these stay null
    # and the lift degrades to RPE-only autoregulation (the ``load_note`` fallback).
    prescribed_load_kg: float | None = Field(
        default=None, description="Suggested working load in kg (pre-fills the log)."
    )
    percent_e1rm: float | None = Field(
        default=None, description="Fraction of estimated 1RM the suggested load targets (0–1)."
    )
    rpe_cap: float | None = Field(
        default=None, description="Upper RPE bound for the working sets (ADR-0029 envelope)."
    )
    e1rm_basis_kg: float | None = Field(
        default=None, description="The current e1RM the suggestion was resolved against."
    )


class WorkoutPrescription(BaseModel):
    """
    Next-session recommendation. Legacy fields required; `why` optional for old clients.
    """

    type: str
    focus: str
    rationale: str
    duration_min: int
    model_version: str = Field(default="v0.3", description="Prescription engine version")
    exercises: list[ExercisePrescription] = Field(default_factory=lambda: [])
    why: PrescriptionExplanation | None = None

    def to_prescribed_content(self) -> dict[str, Any]:
        """Serialize for persistence into ``PlannedSession.prescribed_content``.

        The single source of truth for that JSON shape — the prescribe-and-persist
        seam (service + planning route) writes it, and state_service reads it back
        by string key (ADR-0031). Keeping it here means a new field flows to all
        three sites from one place.
        """
        return self.model_dump()
