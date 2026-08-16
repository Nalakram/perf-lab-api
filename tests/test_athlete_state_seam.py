"""Architecture guard: AthleteState is queried only behind the repository seam (AUD-C15).

The state-history route once inlined ``select(AthleteState)`` + ``unified_from_athlete_row``
— the exact query-plus-domain-conversion leak the repository boundary exists to prevent
(CONTEXT.md). After migrating those reads behind ``AthleteContextRepository`` +
``state_service`` loaders, this guard keeps the aggregate from leaking back: no production
route (``app/api``) or service (``app/services``) module may call ``select(AthleteState)``
directly.

Deliberately narrow: it gates *this one aggregate*, not all ORM queries, and only in
routes/services. The repository implementation is the sanctioned home; one-off maintenance
scripts (``app/scripts``) and migrations are out of scope, as is a column-only
``select(AthleteState.user_id, ...)`` projection (not the whole-entity load this guards).

Second guard, same boundary one level up: a route may neither *import* nor *construct*
``AthleteContextRepository``. Keeping the query out of the route is not enough if the route
still reaches for the repository directly — that hands the HTTP layer a persistence handle and
lets ORM rows back into a handler body. Routes call a ``state_service`` loader; the service
layer owns repository construction.

**What this second guard proves, and what it does not.** It proves that no module under
``app/api`` names ``AthleteContextRepository`` — it flags construction by bare or attribute
reference, and it flags the import under any alias (matched on the imported name, never on
``asname``), so an aliased construction is caught at its import even though ``Repo(db)`` alone
is invisible to an AST name match. The two matchers below are complete only together.

It does NOT prove that no route ever touches a repository. A known, deliberately unguarded
bypass: construct the repository in an unscanned module (for example a ``Depends`` provider in
``app/core``) and inject the handle into the handler without an ``AthleteContextRepository``
annotation. The route then calls ``.list_recent_workouts(...)`` on an injected object with no
occurrence of the name anywhere in ``app/api``, and this guard stays green. Closing that
requires resolving injected dependency types across modules — a different guard and a wider
contract than the slice that introduced this one. Treat this guard as covering the direct,
in-file reach for the repository (the regression it exists to prevent), not as a proof of
repository-freedom in the route layer.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
# Production route + service modules — where a raw AthleteState load would be a seam leak.
SCANNED_ROOTS = [APP / "api", APP / "services"]
# The one sanctioned home for the query.
ALLOWED = {APP / "repositories" / "athlete_context_repository.py"}
# Route modules only: the service layer is the sanctioned home for repository construction,
# so this second guard scans app/api and nothing below it.
ROUTE_ROOT = APP / "api"
REPO_CLASS = "AthleteContextRepository"
REPO_MODULE = "app.repositories.athlete_context_repository"


def _athlete_state_select_lines(path: Path) -> list[int]:
    """Line numbers of ``select(AthleteState)`` calls (whole-entity load) in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "select"
            and any(isinstance(a, ast.Name) and a.id == "AthleteState" for a in node.args)
        ):
            hits.append(node.lineno)
    return hits


def _repo_construction_lines(path: Path) -> list[int]:
    """Line numbers of ``AthleteContextRepository(...)`` construction calls in ``path``.

    Matches the bare name (``AthleteContextRepository(db)``) and the attribute form
    (``module.AthleteContextRepository(db)``).

    It does NOT match a construction through an aliased import (``... import
    AthleteContextRepository as Repo`` then ``Repo(db)``) — at the AST level ``Repo(db)`` carries
    no reference to the real name. That hole is closed by ``_repo_import_lines`` instead, which
    flags the import the alias depends on; the two matchers are only complete together, which is
    why both tests below exist.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else None
        )
        if name == REPO_CLASS:
            hits.append(node.lineno)
    return hits


def _repo_import_lines(path: Path) -> list[int]:
    """Line numbers where ``path`` imports ``AthleteContextRepository``, under any alias.

    Two forms are flagged:

    * ``from ... import AthleteContextRepository`` — matched on the *imported* name
      (``alias.name``), never on ``alias.asname``, so ``as Repo`` is flagged identically.
    * ``import app.repositories.athlete_context_repository`` — importing the defining module,
      which makes the attribute form reachable.

    Matching the import rather than the use is what makes the alias bypass unreachable: a route
    cannot construct the repository under any local name without first importing the real name
    here. A bare unused import is flagged too — REQ-1 is "neither imports nor constructs", and an
    unused import is a re-entry point waiting for a caller.

    Not covered: a name obtained without a static import — ``importlib.import_module``,
    ``getattr`` on a module object, or a repository handle constructed elsewhere and injected
    (see the module docstring's stated limitation).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(a.name == REPO_CLASS for a in node.names):
                hits.append(node.lineno)
        elif isinstance(node, ast.Import):
            if any(a.name == REPO_MODULE for a in node.names):
                hits.append(node.lineno)
    return hits


def test_scanned_roots_exist() -> None:
    """Guard the guard: a path typo would make the scan vacuously green."""
    for root in SCANNED_ROOTS:
        assert root.is_dir(), f"scanned root missing: {root}"
    assert ROUTE_ROOT.is_dir(), f"route root missing: {ROUTE_ROOT}"


def test_guard_detects_a_repository_construction() -> None:
    """Guard the guard: prove the AST matcher fires on the pattern it is meant to catch.

    Without this, a matcher that silently stopped matching would read as a clean codebase.
    """
    probe = Path(__file__).parent / "_seam_probe_not_a_module.py"
    probe.write_text(
        "from app.repositories.athlete_context_repository import AthleteContextRepository\n"
        "def f(db):\n"
        "    return AthleteContextRepository(db)\n",
        encoding="utf-8",
    )
    try:
        assert _repo_construction_lines(probe) == [3]
    finally:
        probe.unlink()


def test_routes_do_not_construct_the_athlete_context_repository() -> None:
    """No ``app/api`` module may construct ``AthleteContextRepository``.

    ``GET /v1/workouts`` once did (``AthleteContextRepository(db).list_recent_workouts(...)``
    inline in the handler) while the module docstring claimed both history reads went through
    a service loader. Routes delegate to ``state_service``; the loader owns the repository.
    """
    offenders: dict[str, list[int]] = {}
    for path in ROUTE_ROOT.rglob("*.py"):
        lines = _repo_construction_lines(path)
        if lines:
            offenders[str(path.relative_to(APP))] = lines
    assert not offenders, (
        f"{REPO_CLASS} is constructed inside route modules: {offenders}. Routes must delegate "
        "to a state_service loader (e.g. load_recent_workouts / load_recent_state_snapshots); "
        "repository construction belongs in the service layer (CONTEXT.md)."
    )


def test_import_guard_detects_an_aliased_and_a_bare_import() -> None:
    """Guard the guard: the import scan must fire on an alias and on an unused bare import.

    The alias case is the load-bearing one — it is what makes the construction matcher's blind
    spot (``Repo(db)`` is just ``ast.Name(id="Repo")``) unreachable in practice. The bare case
    is REQ-1's "neither imports nor constructs" taken literally.
    """
    aliased = Path(__file__).parent / "_seam_probe_aliased_import.py"
    aliased.write_text(
        "from app.repositories.athlete_context_repository import "
        "AthleteContextRepository as Repo\n"
        "async def list_workouts(db, user_id, limit):\n"
        "    return await Repo(db).list_recent_workouts(user_id, limit)\n",
        encoding="utf-8",
    )
    bare = Path(__file__).parent / "_seam_probe_bare_import.py"
    bare.write_text(
        "from app.repositories.athlete_context_repository import AthleteContextRepository\n"
        "async def list_workouts(db, user_id, limit):\n"
        "    return []\n",
        encoding="utf-8",
    )
    module = Path(__file__).parent / "_seam_probe_module_import.py"
    module.write_text(
        "import app.repositories.athlete_context_repository as m\n"
        "def f(db):\n"
        "    return m.AthleteContextRepository(db)\n",
        encoding="utf-8",
    )
    try:
        # The alias defeats the construction matcher — and is caught by the import scan.
        assert _repo_construction_lines(aliased) == []
        assert _repo_import_lines(aliased) == [1]
        # A bare unused import constructs nothing, and is still a REQ-1 violation.
        assert _repo_construction_lines(bare) == []
        assert _repo_import_lines(bare) == [1]
        # Importing the defining module is flagged too (the attribute form's entry point).
        assert _repo_import_lines(module) == [1]
    finally:
        aliased.unlink()
        bare.unlink()
        module.unlink()


def test_routes_do_not_import_the_athlete_context_repository() -> None:
    """No ``app/api`` module may import ``AthleteContextRepository``, under any alias.

    REQ-1 is "neither imports nor constructs". Flagging the import is also what closes the
    aliased-construction bypass: a route cannot build the repository under a local name without
    importing the real name first. See the module docstring for the bypass this does not cover.
    """
    offenders: dict[str, list[int]] = {}
    for path in ROUTE_ROOT.rglob("*.py"):
        lines = _repo_import_lines(path)
        if lines:
            offenders[str(path.relative_to(APP))] = lines
    assert not offenders, (
        f"{REPO_CLASS} is imported by route modules: {offenders}. A route needs no reference to "
        "the repository at all — it calls a state_service loader, which owns both the "
        "construction and the row->schema projection (CONTEXT.md)."
    )


def test_no_direct_athlete_state_select_in_routes_or_services() -> None:
    offenders: dict[str, list[int]] = {}
    for root in SCANNED_ROOTS:
        for path in root.rglob("*.py"):
            if path in ALLOWED:
                continue
            lines = _athlete_state_select_lines(path)
            if lines:
                offenders[str(path.relative_to(APP))] = lines
    assert not offenders, (
        "AthleteState is loaded directly outside the repository seam: "
        f"{offenders}. Route/service code must go through AthleteContextRepository / the "
        "state_service loaders (CONTEXT.md), not inline select(AthleteState)."
    )
