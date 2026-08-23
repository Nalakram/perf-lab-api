"""Let low confidence make a prescription more cautious (ADR-0029 envelope, tri-state).

The project's rule is that uncertainty must affect behaviour: a low-confidence estimate
should produce a more conservative prescription. Until now uncertainty was only ever
*reported* — the twin could say "I am not sure about your max strength" and then prescribe
exactly as if it were sure.

The lever is the RPE cap, not the load. ``prescription_service`` derives percentage, kg and
the load note from ``rpe_cap`` through ``percent_1rm_for_prescription`` and
``suggested_load_kg``, so lowering the cap makes every derived figure follow consistently.
Scaling the resolved kg afterwards would leave the percentage and the note describing a
session that was not prescribed.

**Tri-state, defaulting to off.** ``app/engine/feature_flags.py`` is explicit that a flag
read by no production code is a fictional gate, and that five such booleans were deleted for
that reason. This one has a real OFF branch and a real ON branch a test can tell apart:

- ``off``    — byte-identical to the previous behaviour. The cap is untouched.
- ``shadow`` — compute what the adjustment *would* be and report it, still prescribe the
               unadjusted cap. Lets the effect be observed on real athletes before it acts.
- ``on``     — apply it.

Deliberately conservative in one direction only: this can lower an RPE cap, never raise one.
High confidence justifying *greater* precision is a separate decision with a very different
risk profile, and nothing here does it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.logic.confidence_presentation import (
    STATUS_INSUFFICIENT,
    STATUS_PROVISIONAL,
    ConfidenceStatus,
)

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"
VALID_MODES = frozenset({MODE_OFF, MODE_SHADOW, MODE_ON})

#: How far to pull the RPE cap down, by the certainty of the weakest capacity axis.
#: An "insufficient" axis is an unrefined prior — the twin does not really know what this
#: athlete can do, so a full RPE point of headroom is cheap insurance. "provisional" is
#: weakly constrained rather than unknown, so it gets half.
RPE_REDUCTION: dict[str, float] = {
    STATUS_INSUFFICIENT: 1.0,
    STATUS_PROVISIONAL: 0.5,
}

#: Never drive the cap below a genuinely productive working intensity. Below roughly RPE 6
#: a strength session stops driving adaptation, and an over-cautious plan that trains
#: nothing is its own failure — being unsure is not a reason to stop training.
MIN_RPE_CAP = 6.0


@dataclass(frozen=True)
class ConservatismDecision:
    """What the conservatism rule concluded, and whether it was allowed to act."""

    mode: str
    basis_status: ConfidenceStatus | None
    baseline_rpe_cap: float
    effective_rpe_cap: float
    applied: bool
    reason: str

    @property
    def adjustment(self) -> float:
        """Signed change to the cap. Zero when nothing was applied."""
        return round(self.effective_rpe_cap - self.baseline_rpe_cap, 3)


def decide(
    *,
    baseline_rpe_cap: float,
    weakest_status: ConfidenceStatus | None,
    mode: str,
) -> ConservatismDecision:
    """Resolve the cap this session should actually use.

    ``weakest_status`` is the least certain capacity axis for this athlete — the one that
    should most limit trust. ``None`` means no state, and no state is not a licence to be
    aggressive: it is simply no signal to act on, and the caller has no basis for a
    reduction either way.
    """
    if mode not in VALID_MODES:
        # An unrecognised mode must not silently behave like "on". Fail closed.
        return ConservatismDecision(
            mode=mode,
            basis_status=weakest_status,
            baseline_rpe_cap=baseline_rpe_cap,
            effective_rpe_cap=baseline_rpe_cap,
            applied=False,
            reason=f"unrecognised mode {mode!r}; treated as off",
        )

    reduction = RPE_REDUCTION.get(weakest_status or "", 0.0)
    if mode == MODE_OFF:
        return ConservatismDecision(
            mode=mode,
            basis_status=weakest_status,
            baseline_rpe_cap=baseline_rpe_cap,
            effective_rpe_cap=baseline_rpe_cap,
            applied=False,
            reason="uncertainty conservatism is off",
        )

    if reduction <= 0.0:
        return ConservatismDecision(
            mode=mode,
            basis_status=weakest_status,
            baseline_rpe_cap=baseline_rpe_cap,
            effective_rpe_cap=baseline_rpe_cap,
            applied=False,
            reason=(
                "no reduction warranted"
                if weakest_status
                else "no capacity confidence available to act on"
            ),
        )

    proposed = max(MIN_RPE_CAP, round(baseline_rpe_cap - reduction, 2))
    if proposed >= baseline_rpe_cap:
        return ConservatismDecision(
            mode=mode,
            basis_status=weakest_status,
            baseline_rpe_cap=baseline_rpe_cap,
            effective_rpe_cap=baseline_rpe_cap,
            applied=False,
            reason=f"cap already at or below the {MIN_RPE_CAP:g} floor",
        )

    if mode == MODE_SHADOW:
        return ConservatismDecision(
            mode=mode,
            basis_status=weakest_status,
            baseline_rpe_cap=baseline_rpe_cap,
            # Shadow reports the proposal but prescribes the baseline.
            effective_rpe_cap=baseline_rpe_cap,
            applied=False,
            reason=f"shadow: would cap at RPE {proposed:g} for {weakest_status} confidence",
        )

    return ConservatismDecision(
        mode=mode,
        basis_status=weakest_status,
        baseline_rpe_cap=baseline_rpe_cap,
        effective_rpe_cap=proposed,
        applied=True,
        reason=f"capped at RPE {proposed:g}: weakest capacity axis is {weakest_status}",
    )
