# CHOOSE: picking a structure

## Purpose

The README's second goal: the owner states the exposure they want across hypothetical future spot outcomes, and the selector finds the option structure whose exposures come closest, ranked by fit, never by expected profit. Not built: every row below is intent, not code. Work is tracked in [../changes/2026-11-04-choosing.md](../changes/2026-11-04-choosing.md).

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| CHOOSE-001 | Takes a target exposure across hypothetical spot outcomes, plus limits (DTE window, max loss, budget, liquidity), and returns candidate structures | Gap (intended, user 2026-11-05; not built) | | change record; README.md "Choosing" |
| CHOOSE-002 | Fit is the distance between a candidate's exposures and the target across those outcomes; the closest ranks first, execution cost (bid-ask across all legs as a share of premium) a close second. Never ranked by expected profit; rich or cheap only against today's surface | Intended | | user, 2026-11-05; owner's plan doc 2026-09-18; README.md |
| CHOOSE-003 | Uses the `tradeable` flag from SURF-002 to keep untradeable strikes out | Proposed | | `surface.py` docstring: "the trade flag rides along for whatever ranks candidates later" |
| CHOOSE-004 | An exact match isn't required: the closest candidates are returned with how far each misses the target | Intended | | user, 2026-11-05 |
| CHOOSE-005 | Views are built in order: long premium, short premium, calendars and diagonals, direction (verticals) | Intended | | user, 2026-11-05 |
| CHOOSE-006 | Undefined-risk structures stay candidates; their max loss reads unlimited, so a max-loss limit removes them | Intended | | user, 2026-11-05; owner's plan doc |
| CHOOSE-007 | Shows exposures only: no hedge suggestions and no alert on a drifting delta; the owner decides when to hedge | Intended | | user, 2026-11-05 |

## Gaps

- How the target is written, how distance is measured, what sets the size, the strike search and the fill price are undecided. They are the open questions in the change record, to settle before acceptance criteria for view 1.
