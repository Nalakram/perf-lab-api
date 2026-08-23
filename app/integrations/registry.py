"""Provider slug → adapter, so the sync service never names a concrete provider.

``app/integrations/base.py`` promises that "the sync service never imports a concrete
provider". That was not true: ``wearable_service`` imported ``OuraAdapter`` directly and
resolved it through ``if provider == "oura": ... else raise``, so adding Garmin meant editing
the shared service — the exact coupling the adapter Protocol exists to prevent.

This module is the one place that knows concrete adapters. ``wearable_service`` imports only
``adapter_for``; ``tests/test_wearable_provider_seam.py`` enforces that with an AST guard, so
the promise in ``base.py`` is checked rather than merely written down.

Registration is explicit rather than by scanning the package: an import-time side effect that
depends on module discovery order is how a provider silently goes missing in one entrypoint
and not another.
"""

from __future__ import annotations

from collections.abc import Callable

from app.integrations.base import WearableAdapter
from app.integrations.oura import OuraAdapter


class UnknownWearableProvider(LookupError):
    """Raised for a provider slug no adapter is registered for.

    A distinct type rather than ``ValueError`` so a route can map it to 404/400 without
    catching every other value error in the call.
    """

    def __init__(self, provider: str, known: tuple[str, ...]) -> None:
        self.provider = provider
        self.known = known
        super().__init__(
            f"Unsupported wearable provider {provider!r}. Registered: {', '.join(known) or 'none'}"
        )


#: Slug → zero-argument factory. Factories, not instances: an adapter reads settings at
#: construction, so a module-level instance would freeze configuration at import time and
#: make it untestable by monkeypatching settings.
_FACTORIES: dict[str, Callable[[], WearableAdapter]] = {}


def register(provider: str, factory: Callable[[], WearableAdapter]) -> None:
    """Register a provider's adapter factory. Re-registering the same slug replaces it.

    Replacement is deliberate — a test swapping in a fake for one provider should not have
    to know whether the real one was registered first.
    """
    _FACTORIES[provider] = factory


def supported_providers() -> tuple[str, ...]:
    """Every registered slug, sorted, for error messages and capability responses."""
    return tuple(sorted(_FACTORIES))


def is_supported(provider: str) -> bool:
    return provider in _FACTORIES


def adapter_for(provider: str) -> WearableAdapter:
    """The adapter for ``provider``.

    Raises :class:`UnknownWearableProvider` rather than returning a default. Falling back to
    a default provider would silently attribute one vendor's data to another, and
    ``WellnessSample.source`` is now load-bearing for baselines and per-signal authority.
    """
    factory = _FACTORIES.get(provider)
    if factory is None:
        raise UnknownWearableProvider(provider, supported_providers())
    adapter = factory()
    if adapter.provider != provider:
        # A registry keyed on one slug handing back an adapter that stamps another would
        # write wellness rows under the wrong source, which now changes readiness.
        raise RuntimeError(
            f"adapter registered under {provider!r} reports provider {adapter.provider!r}"
        )
    return adapter


register(OuraAdapter.provider, OuraAdapter)
