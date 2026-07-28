"""
Regression guard for native-enum binding across every model that uses a PG enum.

The Postgres enum types were created from the enum *values* (e.g. ``"active"``),
but SQLAlchemy's default binds the member *name* (``"ACTIVE"``). That mismatch
made every block/planned-session read raise ``invalid input value for enum ...``
— which surfaced once the Twin/Planning UI started calling the prescriber and
planning endpoints. ``values_callable`` on the columns fixes it. These checks
inspect the compiled column type (no DB needed), so a future edit dropping
``values_callable`` fails here instead of at runtime.

Note that "values" does not mean "lowercase" everywhere: ``blockgoal`` labels are
Title-case (``"Strength"``, ``"CrossFit"``). The invariant is name-vs-value, not
casing, which is why the sweep below compares against member values rather than
asserting any particular case.
"""

from sqlalchemy import Enum as SAEnum

from app.models import Base
from app.models.macrocycle import Macrocycle, MacrocycleStatus
from app.models.mesocycle import (
    BlockGoal,
    BlockStatus,
    MesocycleBlock,
    PlannedSession,
    SessionStatus,
)
from app.models.objective import Objective, ObjectiveStatus
from app.models.weak_point import WeakPoint, WeakPointSource


def test_block_columns_bind_enum_values_not_names() -> None:
    assert set(MesocycleBlock.__table__.c.status.type.enums) == {b.value for b in BlockStatus}
    assert set(MesocycleBlock.__table__.c.goal.type.enums) == {g.value for g in BlockGoal}
    # Guard the specific casing that broke: values are lower/title-case, never the
    # upper-case member names.
    assert "ACTIVE" not in MesocycleBlock.__table__.c.status.type.enums
    assert "active" in MesocycleBlock.__table__.c.status.type.enums


def test_planned_session_status_binds_enum_values() -> None:
    assert set(PlannedSession.__table__.c.status.type.enums) == {s.value for s in SessionStatus}
    assert "PENDING" not in PlannedSession.__table__.c.status.type.enums
    assert "pending" in PlannedSession.__table__.c.status.type.enums


def test_macrocycle_status_binds_enum_values() -> None:
    assert set(Macrocycle.__table__.c.status.type.enums) == {m.value for m in MacrocycleStatus}
    assert "ACTIVE" not in Macrocycle.__table__.c.status.type.enums
    assert "active" in Macrocycle.__table__.c.status.type.enums


def test_objective_status_binds_enum_values() -> None:
    assert set(Objective.__table__.c.status.type.enums) == {o.value for o in ObjectiveStatus}
    assert "ACTIVE" not in Objective.__table__.c.status.type.enums
    assert "active" in Objective.__table__.c.status.type.enums


def test_weak_point_source_binds_enum_values() -> None:
    assert set(WeakPoint.__table__.c.source.type.enums) == {w.value for w in WeakPointSource}
    assert "SELF_REPORT" not in WeakPoint.__table__.c.source.type.enums
    assert "self_report" in WeakPoint.__table__.c.source.type.enums


def test_every_native_enum_column_binds_values_not_names() -> None:
    """Ratchet: any *future* enum column is covered without editing this file.

    ``app.models`` imports every model, so ``Base.metadata`` sees the whole schema.
    A new ``SAEnum`` column that forgets ``values_callable`` fails here.
    """
    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            column_type = column.type
            enum_class = getattr(column_type, "enum_class", None)
            if not isinstance(column_type, SAEnum) or enum_class is None:
                continue
            expected = {member.value for member in enum_class}
            if set(column_type.enums) != expected:
                offenders.append(
                    f"{table.name}.{column.name} binds {sorted(column_type.enums)}, "
                    f"expected member values {sorted(expected)} "
                    f"— add values_callable to this column"
                )

    assert not offenders, "Enum columns binding member names instead of values:\n" + "\n".join(
        offenders
    )


def test_enum_sweep_actually_inspects_columns() -> None:
    """Positive control: the sweep is worthless if it silently matches nothing."""
    inspected = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, SAEnum) and getattr(column.type, "enum_class", None) is not None
    ]
    assert len(inspected) >= 6, f"sweep found only {len(inspected)} enum columns: {inspected}"
