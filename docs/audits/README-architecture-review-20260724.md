# Provenance — `architecture-review-20260724.html`

```text
status: audit input / planning artifact
captured_from: temporary scratchpad
captured_on: 2026-07-24
authority: not an implemented specification
queue_coverage: items 3-10
```

Generated 2026-07-24 by `/improve-codebase-architecture-mwdev`. It was preserved here
verbatim (byte-identical copy, md5 `a1f518f043fd9e0a4b24aee98466c060`) because it lived
only in a session scratchpad under `%LOCALAPPDATA%\Temp` and is the sole specification for
the remaining production-flywheel queue items.

**This file records recommendations, not settled architecture.** Nothing in it is binding
until it has been designed, implemented, and verified through the normal path.

## How to read it

Each candidate carries a slug, a RANK group (`api-contract` / `services` / `engine`), a
`direct-fix` / `design` classification, a file:line list, a Problem/Solution pair, and a
leverage line. **Search by slug, not by number** — the queue numbers are report candidate
indices and collide misleadingly with unrelated GitHub issue/PR numbers.

Group C (`api-contract`) slugs in queue order:

1. `confidence-status-literal` — delivered, PR #193, merged 2026-07-28
2. `repo-construction-seam`
3. `prescription-content-type`
4. `dashboard-typed-mapping`
5. `weakpoints-router-seam`
6. `planning-reschedule-service`

Group D (`engine`, 3 candidates) slugs are not yet extracted from the report.

## Known accuracy limits

The report's own descriptions can be wrong in both directions, so treat its citations as a
starting point to verify rather than as a specification. Observed on candidate 1:

- It claimed the confidence enum was "hand-mirrored 2x in web". It was one file, two lines,
  and the second apparent mirror was a different concept entirely.
- It named four files but missed a **third** publisher of the same band
  (`OnboardingTwinSummary.overall_confidence`), which the independent verifier found.

Re-verify every file:line claim before designing against it.
