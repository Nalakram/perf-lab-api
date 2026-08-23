"""Fitness gate: shadow-write services delegate their commit/rollback to one seam.

Every ``app/services/*_shadow_service.py`` is a best-effort side-channel writer whose
failure must never break the request that triggered it. ``telemetry_common.best_effort_write``
owns that "commit; on failure log-and-rollback" dance in exactly one place — including the
guard against a rollback that itself raises. ``dose_routing_shadow_service`` used to reimplement
it inline with an *unguarded* rollback, awaited directly inside ``process_new_workout`` with no
surrounding try/except, so a raising rollback could break real workout ingestion (AUD-C14).

The first test below forbids a bare ``db.commit()`` / ``db.rollback()`` anywhere in a
shadow-write service: they must route through ``best_effort_write`` instead.

That ban is necessary but not sufficient, and this file used to say so out loud —
``capacity_floor_shadow_service`` "passes naturally … and calls neither". It passed by
staging its row into the *caller's* transaction, which is the opposite of isolation:
``db.add()`` only stages in memory, so the INSERT and any constraint violation it raises
execute wherever that transaction is flushed. A single oversized column value therefore
aborted the benchmark observation the row was describing. The second test closes that
hole: a shadow service that stages rows at all must delegate durability to the seam.
"""

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHADOW_SERVICES = sorted((_REPO_ROOT / "app" / "services").glob("*_shadow_service.py"))


def _direct_commit_rollback_calls(source: str) -> list[tuple[str, int]]:
    """Return (method, lineno) for every ``<something>.commit()`` / ``.rollback()`` call."""
    tree = ast.parse(source)
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"commit", "rollback"}
        ):
            hits.append((node.func.attr, node.lineno))
    return hits


def test_shadow_services_exist() -> None:
    """Guard the guard: a glob typo must not let the rule below pass vacuously."""
    assert len(_SHADOW_SERVICES) >= 5, (
        f"expected to find the shadow-write services under app/services/, found "
        f"{[p.name for p in _SHADOW_SERVICES]}"
    )


def test_shadow_services_do_not_inline_commit_or_rollback() -> None:
    offenders: dict[str, list[tuple[str, int]]] = {}
    for path in _SHADOW_SERVICES:
        hits = _direct_commit_rollback_calls(path.read_text(encoding="utf-8"))
        if hits:
            offenders[path.name] = hits

    assert not offenders, (
        "shadow-write services must delegate commit/rollback to "
        "telemetry_common.best_effort_write, not inline it:\n"
        + "\n".join(
            f"  {name}: " + ", ".join(f"{m}() at line {ln}" for m, ln in hits)
            for name, hits in offenders.items()
        )
    )


def _staged_row_lines(source: str) -> list[int]:
    """Line numbers of every ``db.add(...)`` / ``session.add_all(...)`` style call."""
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"add", "add_all"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"db", "session"}
    ]


def test_shadow_services_that_stage_rows_route_through_the_seam() -> None:
    """Staging a row without owning its transaction is not isolation, it is deferral.

    Passing the commit/rollback ban by calling neither leaves the row to flush inside the
    live request transaction, where its failure is fatal to the primary write. Any shadow
    service that stages rows must therefore reference ``best_effort_write``.
    """
    offenders: dict[str, list[int]] = {}
    for path in _SHADOW_SERVICES:
        source = path.read_text(encoding="utf-8")
        staged = _staged_row_lines(source)
        if staged and "best_effort_write" not in source:
            offenders[path.name] = staged

    assert not offenders, (
        "shadow-write services that stage rows must own their transaction via "
        "telemetry_common.best_effort_write - otherwise the row flushes inside the "
        "caller's live transaction and its failure aborts the real write:\n"
        + "\n".join(
            f"  {name}: db.add() at line(s) " + ", ".join(str(ln) for ln in lines)
            for name, lines in offenders.items()
        )
    )
