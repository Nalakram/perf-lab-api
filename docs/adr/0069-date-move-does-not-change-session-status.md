---
status: accepted
date: 2026-08-16
---
# Moving a planned session's date does not change its lifecycle status

`PATCH /v1/planning/sessions/{id}` auto-assigned `SessionStatus.RESCHEDULED` whenever
`scheduled_date` changed and the caller sent no explicit status
(`app/api/v1/planning.py:129-130`, pre-change). Under the current session model that write
is effectively terminal. Both live session resolvers filter on `PENDING` —
`planning_service.get_today_session` (`app/services/planning_service.py:289`) and
`state_service._match_planned_session` (`app/services/state_service.py:571`) — and the only
writes of `PENDING` anywhere in `app/` are the column default
(`app/models/mesocycle.py:197`) and bulk block creation
(`app/services/planning_service.py:234`). Nothing returns a session to `PENDING`.

So a moved session became permanently invisible to `/v1/planning/today`, never auto-linked a
logged workout, and could never reach `COMPLETED` or count toward adherence — the exact
opposite of what a user means by "move this session to a different day".

**Decision.** Under the current session model, changing `scheduled_date` does not change a
pending session's lifecycle status. `original_scheduled_date` remains provenance. The
automatic `RESCHEDULED` transition was removed because current lifecycle consumers treat it
as effectively terminal.

The scope is narrow, and the following are all part of the decision:

1. **`RESCHEDULED` remains in the enum for compatibility.** `app/models/mesocycle.py:48`,
   the `sessionstatus` DB enum (`alembic/versions/a000_init_foundational_tables.py:149`), the
   published `SessionStatus` contract, and the four-value expectation in
   `tests/test_enum_binding.py` are all unchanged. Only the *automatic* write was removed; a
   caller that explicitly `PATCH`es `status: "rescheduled"` still gets it. No migration, no
   enum change, no contract change.
2. **`original_scheduled_date` is retained, but its future use in adherence calculations is
   undecided.** The first-move-wins provenance rule (`app/api/v1/planning.py:123-126`) is
   preserved exactly. Whether a session that was moved should be scored differently from one
   executed as planned is a real product question this ADR does **not** answer; it only
   guarantees the evidence to answer it later is still being recorded.
3. **This decision governs the current mutable-session implementation only.** Today a
   `PlannedSession` row is mutated in place, which is precisely why an absorbing status is so
   damaging — there is no other row to carry the session forward.
4. **Proposed [ADR-0063](0063-session-commitment-and-issuance.md) is NOT resolved,
   implemented, superseded, or implicitly accepted by this ADR.** ADR-0063 remains
   `status: proposed`. This is a defect repair inside the implementation that exists today,
   not a step toward, or an endorsement of, the commitment/issuance model.
5. **If ADR-0063 later lands with revision/issuance semantics, this rescheduling rule must be
   reconsidered inside that architecture rather than carried forward automatically.** Under
   revision-based sessions a date move plausibly *should* produce a status or revision
   transition, because a superseded revision would no longer be the row a resolver targets.
   "Date moves never touch status" is a conclusion about the current model, not an invariant
   to inherit.

## Data census

A read-only count of `planned_sessions WHERE status = 'rescheduled'` across every local
Postgres database on 2026-08-16 returned **0 rows** — including the development database
`perflab` (0 planned sessions total) and every `perflab_test*` database. No local row was ever
stranded by this path, so no repair or backfill migration is warranted, and none was written.

**Unresolved operational follow-up:** the production count is unknown. Production is EC2 and
out of scope for this change. Any stranded production rows would need a separate human
decision about whether to return them to `PENDING`; this ADR does not authorize that.

## Consequences

- A date move now leaves a pending session pending, so it stays resolvable by
  `/v1/planning/today` and stays auto-linkable by `_match_planned_session`.
- `SessionStatus` is no longer imported by `app/api/v1/planning.py`; it had exactly one use
  there, the removed assignment.
- Regression coverage lives in `tests/test_planning_reschedule_lifecycle.py`, which pins
  route-observable behaviour: move-to-today stays discoverable and `PENDING`, an explicit
  status still wins, and `original_scheduled_date` provenance is unchanged.
- Prose in `docs/ARCHITECTURE.md:290` and `docs/COMPONENT_GUIDE.md:212` asserted the old
  auto-transition; both were reconciled in this change to state that the "+1 day" action moves
  `scheduled_date` and leaves status unchanged.
