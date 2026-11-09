# SCEN: what a position does under hypothetical outcomes

## Purpose

Value, Greeks and P&L of a position under hypothetical spot levels, IV shifts, dates and paths, built on the snapshot's own IVs, smile fit and term structure. What-if only, never a forecast or a sort key. The UI and the structure chooser call it. Not built: Intended rows are the owner's decisions, not code. Detail and acceptance criteria are in [../changes/2026-11-06-scenario-engine.md](../changes/2026-11-06-scenario-engine.md).

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| SCEN-001 | A position is option legs (expiry, strike, right, signed contracts) and hedge legs (SPY shares or NES futures) from one snapshot, newest by default | Proposed | | change record "Inputs and output" |
| SCEN-002 | Each option leg uses vol.py's IV for its strike (the out-of-the-money side, valid for both rights under the parity forward), else the fitted curve inside its range, else it is refused | Proposed | AC-1, AC-2 | change record |
| SCEN-003 | At a scenario spot every forward moves with spot, carry unchanged | Proposed | AC-3 | change record |
| SCEN-004 | When spot moves, the smile slides along the fitted curve, each leg keeping its start residual; never extrapolated past the fitted range | Intended | AC-3 | user, 2026-11-06 |
| SCEN-005 | When the date moves, each expiry rolls along today's term structure in sessions, so weekends and holidays cost no variance; values at that date's close; expired legs worth intrinsic | Intended | AC-4, AC-5 | user, 2026-11-06 |
| SCEN-006 | A parallel IV shift in vol points is applied after the smile and time rules | Proposed | AC-6 | change record |
| SCEN-007 | P&L is model value at the point minus model value at the start; entry at mid, with the far side shown beside it | Intended (entry at mid) | AC-1, AC-10 | user, 2026-11-06 |
| SCEN-008 | Every value carries a range from each leg's IV band | Proposed | AC-9 | Conventions: numbers carry error bars |
| SCEN-009 | Hedge legs carry only delta: one per SPY share; per NES contract `0.50 × NES price / SPY spot`, about 5 shares | Proposed (owner to confirm the NES conversion) | AC-7, AC-13 | NES $0.50 per index point, Sourced 2026-11-06 |
| SCEN-010 | Paths: unhedged P&L depends only on the endpoint; trades along a path add their own P&L from their own spot | Proposed | AC-8 | change record |
| SCEN-011 | Flags in the output: legs past 0.9 absolute delta (European math), legs held at the fitted range's edge, expiries without a fit, negative remaining variance, expiries dropped from the term structure | Proposed | AC-3, AC-4 | integrity.md items 2 and 4; A-015 |

## Gaps

- Not built.
