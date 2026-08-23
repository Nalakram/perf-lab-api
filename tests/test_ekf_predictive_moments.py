"""The predictive spread must be exposed, and must be the same one the update uses.

ADR-0041 names two calibration arms: NIS chi-squared and interval coverage. Only NIS was
ever computable on real data, because `ekf_shadow_log` stores nis/n_obs but not the
per-observation predictive spread — and nothing in the codebase exposed it, so a caller
wanting coverage had no honest way to get it. `evaluate_ekf_calibration_gate` reports that
arm as structurally unevaluated for exactly this reason.

`predictive_moments` is that missing primitive. These tests pin the two things that make it
trustworthy: it agrees with the update's own arithmetic, and it shares a code path with it
rather than being a second derivation that could drift.
"""

import numpy as np
import pytest

from app.engine.parameters import default_parameters
from app.logic.ekf.belief import EkfBelief
from app.logic.ekf.observation import Observation, predictive_moments, update
from app.logic.ekf.state_packing import INDEX_OF_KEY, N_STATE


def _belief() -> EkfBelief:
    from datetime import UTC, datetime

    mean = np.full(N_STATE, 0.5)
    cov = np.eye(N_STATE) * 0.2
    return EkfBelief(
        mean=mean, cov=cov, timestamp=datetime.now(UTC), model_version="test-v1"
    )


def _obs(axis: str = "max_strength", y: float = 0.7, r: float = 0.05) -> Observation:
    H = np.zeros((1, N_STATE))
    H[0, INDEX_OF_KEY[("capacity", axis)]] = 1.0
    return Observation(
        H=H,
        y=np.array([y]),
        R=np.array([[r]]),
        benchmark_code="pl_e1rm_squat",
        axis_keys=(axis,),
    )


def test_predicted_mean_is_the_filters_expectation_of_the_observation() -> None:
    belief, obs = _belief(), _obs()

    moments = predictive_moments(belief, obs)

    assert moments.mean == pytest.approx(obs.H @ belief.mean)


def test_predicted_std_includes_measurement_noise() -> None:
    """The right denominator for coverage: a realized benchmark carries noise too.

    Using the state spread alone would report systematic under-coverage that is an artefact
    of the wrong denominator, not a mis-calibrated filter.
    """
    belief, obs = _belief(), _obs(r=0.05)

    moments = predictive_moments(belief, obs)
    state_only = np.sqrt(np.diag(obs.H @ belief.cov @ obs.H.T))

    assert moments.std[0] > state_only[0]
    assert moments.std[0] == pytest.approx(np.sqrt(0.2 + 0.05))


def test_the_innovation_the_update_uses_is_this_predicted_mean() -> None:
    """Shares a code path with `update`, so a coverage figure cannot drift from the filter."""
    belief, obs = _belief(), _obs(y=0.7)
    params = default_parameters()

    moments = predictive_moments(belief, obs)
    result = update(belief, obs, params)

    assert result.innovation == pytest.approx(obs.y - moments.mean)


def test_nis_is_the_innovation_normalised_by_this_same_spread() -> None:
    """A cross-check that S here IS the S the update inverts.

    For a single-row observation, NIS reduces to (innovation / predictive_std)^2.
    """
    belief, obs = _belief(), _obs(y=0.9)
    params = default_parameters()

    moments = predictive_moments(belief, obs)
    result = update(belief, obs, params)

    expected = float((result.innovation[0] / moments.std[0]) ** 2)
    assert result.nis == pytest.approx(expected)


def test_a_more_certain_filter_predicts_a_tighter_interval() -> None:
    from datetime import UTC, datetime

    obs = _obs()
    tight = EkfBelief(
        mean=np.full(N_STATE, 0.5), cov=np.eye(N_STATE) * 0.01,
        timestamp=datetime.now(UTC), model_version="t",
    )
    loose = EkfBelief(
        mean=np.full(N_STATE, 0.5), cov=np.eye(N_STATE) * 0.9,
        timestamp=datetime.now(UTC), model_version="t",
    )

    assert predictive_moments(tight, obs).std[0] < predictive_moments(loose, obs).std[0]


def test_the_standard_deviation_is_never_nan() -> None:
    """A stabilized covariance is PSD, but floating point can leave a diagonal fractionally
    negative, and sqrt of that is nan rather than an error - which would silently poison
    every coverage figure downstream."""
    from datetime import UTC, datetime

    belief = EkfBelief(
        mean=np.full(N_STATE, 0.5),
        cov=np.eye(N_STATE) * -1e-18,  # pathological, but must not produce nan
        timestamp=datetime.now(UTC),
        model_version="t",
    )

    std = predictive_moments(belief, _obs(r=0.0)).std

    assert not np.isnan(std).any()
    assert (std >= 0.0).all()
