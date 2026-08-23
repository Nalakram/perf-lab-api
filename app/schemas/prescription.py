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
