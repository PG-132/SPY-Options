# CHOOSE: picking a structure

## Purpose

The README's second goal: given a view and risk limits, find the option structure that fits best, ranked by fit, never by expected profit. Not built. Work is tracked in [../changes/2026-11-04-choosing.md](../changes/2026-11-04-choosing.md).

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| CHOOSE-001 | Takes a view and risk limits and returns candidate structures | Gap | | README.md "Choosing"; no code |
| CHOOSE-002 | Candidates are ranked by fit to the view and limits, not by expected profit; rich or cheap only against today's surface | Intended | | README.md |
| CHOOSE-003 | Uses the `tradeable` flag from SURF-002 to keep untradeable strikes out | Proposed | | `surface.py` docstring: "the trade flag rides along for whatever ranks candidates later" |

## Gaps

- What a "view" and "risk limits" are, which structures are in scope, and what "fit" means are all undefined. See A-004.
