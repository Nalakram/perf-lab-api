"""Engine feature flags.

A flag lives here only when it actually selects behavior at a production call site — an OFF
branch and an ON branch that a test can tell apart. Experimental work that runs shadow-only
and has no live branch yet is NOT a flag: a boolean read by no production code is a fictional
promotion gate — it implies a live path exists when it does not. Such work's maturity belongs
in an ADR and the roadmap, not in runtime config.

`test_feature_flags_are_wired.py` enforces this: every constant here must have at least one
production reader, or CI fails.

History: five ENABLE_* booleans once sat here as "promotion gates" for shadow subsystems
(MPC prescription, personalized recovery, tissue-risk penalty, decrement hard-block, workout-
informed confidence). None was ever wired — each gated nothing — so they were removed (AUD-C9,
2026-07-16). The shadow computations and their telemetry are untouched and keep running;
promoting any of them to live is a separately-approved feature mission that must build a real
OFF/ON path with a validation harness before a control flag returns. See docs/adr/0042
(MPC) and docs/adr/0043 (personalized recovery).
"""

# INT-02 (ADR-0066): candidate-aware prescription basis. Tri-state — the flag governs the
# ENTIRE basis selection, not an incidental min():
#   "off"    → legacy: latest valid raw e1RM is the basis (the prescription half of the
#              max_strength defect stays OPEN in this state).
#   "shadow" → compute + record legacy vs candidate-aware, still select legacy.
#   "on"     → basis is canonical current capacity capped by an active decline-candidate
#              ceiling; the chronologically-latest raw observation is no longer direct
#              durable prescription authority.
DECLINE_CANDIDATE_PRESCRIPTION_BASIS: str = "off"

# ADR-0029 envelope: let low confidence make a session more cautious. Tri-state — the flag
# governs whether the twin's own uncertainty is allowed to change what it prescribes, not an
# incidental clamp:
#   "off"    → the RPE cap is untouched. Byte-identical to the pre-flag behaviour.
#   "shadow" → compute and report the reduction the twin would apply, still prescribe the
#              unadjusted cap. Lets the effect be watched on real athletes before it acts.
#   "on"     → a low-confidence weakest capacity axis lowers the working RPE cap, and
#              percentage / kg / load-note all follow from it.
# Read by app/services/prescription_service.py (_enrich_exercises_with_load).
UNCERTAINTY_CONSERVATISM: str = "off"
