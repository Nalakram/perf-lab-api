"""Which wellness source to believe, per signal (provider-independent).

``WellnessSample`` is keyed ``(user_id, date, source)``, so several sources may report the
same day — an Oura sync and a manual check-in routinely do. Nothing consumed ``source``:
``_latest_wellness`` returned a single row ordered by ``created_at``, so whichever landed
last won and the other row's signals were dropped, and ``_baselines`` averaged every source
together so a provider switch silently shifted the athlete's own baseline.

This module owns the two judgements that fixes those, kept pure and free of any provider
name so a new integration needs no edit here.

**Objective vs subjective is the whole model.** A wearable measures HRV, resting heart rate
and sleep better than a person estimating them. But soreness, mood and stress are not
measurable by a device at all — a provider reporting them is inferring, while the athlete is
the primary instrument. So authority inverts by signal rather than being a single ranking of
providers.

**Two devices are NOT ranked against each other.** There is no evidence in this repo that
one wearable measures HRV better than another, and inventing an order would be exactly the
kind of unbacked claim the readiness path is being cleaned of. Equal-authority sources tie-
break on ingestion recency, which is the previous behaviour narrowed to where it is
defensible.

Distinct from ``app.logic.observation_authority``, which governs whether an observation may
write *capacity* (and rejects device imports outright, ADR-0058). Wellness is not capacity;
conflating the two would import a rejection rule written for a different question.
"""

from __future__ import annotations

from typing import Any

#: Signals only a human can report. A device that emits these is inferring, not measuring.
SUBJECTIVE_SIGNALS: frozenset[str] = frozenset({"soreness", "mood", "stress"})

#: Signals a wearable measures more reliably than a person estimating them.
OBJECTIVE_SIGNALS: frozenset[str] = frozenset(
    {"hrv_ms", "sleep_hours", "sleep_quality", "resting_hr"}
)

#: The athlete entering a value by hand. Every other source string is a provider/device.
MANUAL_SOURCE = "manual"

#: Authority ranks. Only the ordering matters; the values are arbitrary.
_PREFERRED = 2
_ACCEPTED = 1


def is_device_source(source: str) -> bool:
    """Anything that is not the athlete typing a value is a provider/device.

    Deliberately not a list of provider names: a new integration must not need an edit
    here, and an unrecognised provider must not silently fall to the bottom of a ranking.
    """
    return (source or "").strip().lower() != MANUAL_SOURCE


def authority_rank(signal: str, source: str) -> int:
    """How much this source's reading of this signal should be believed. Higher wins.

    Subjective signals invert the ordering rather than excluding devices: a provider-derived
    stress score is still evidence, just weaker than the athlete's own report.
    """
    device = is_device_source(source)
    if signal in SUBJECTIVE_SIGNALS:
        return _ACCEPTED if device else _PREFERRED
    return _PREFERRED if device else _ACCEPTED


def resolve_signal_source(
    signal: str, candidates: list[tuple[str, Any, Any]]
) -> tuple[str, Any] | None:
    """Pick the source to believe for one signal from same-day candidates.

    ``candidates`` is ``(source, value, ingested_at)``; entries whose value is ``None`` are
    not candidates at all, because a source that reported nothing for a signal must not
    outrank one that did simply by being more authoritative in general.

    Returns ``(source, value)``, or ``None`` when no source supplied this signal — which
    stays missing rather than becoming a number.
    """
    supplied = [(src, val, at) for src, val, at in candidates if val is not None]
    if not supplied:
        return None
    # Highest authority first, then most recently ingested. `ingested_at` may be None on a
    # legacy row; sort those last rather than raising on a None comparison.
    best = max(
        supplied,
        key=lambda c: (authority_rank(signal, c[0]), c[2] is not None, c[2] or 0),
    )
    return best[0], best[1]
