# APP: the command line

## Purpose

One entry point for every step, and one command for the daily routine. Code: `app.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| APP-001 | With no arguments, `app.py` runs `plan`, which is read-only, and says so | Intended | No files written by a bare run | `app.py` comment ("anything that writes has to be asked for") |
| APP-002 | `daily` runs snap, iv, surface, term, context, ledger in that order, each on the newest snapshot, then `response`, history's fixed-strike view over every day's last snapshot | Intended | | `cmd_daily()`; `response` added 2026-11-12 ([../changes/2026-11-11-iv-response.md](../changes/2026-11-11-iv-response.md), LEDG-026) |
| APP-003 | A failure in any `daily` step stops the run rather than letting later steps report on older data | Intended | | `cmd_daily()` docstring |
| APP-004 | `history` (beyond its `response` view), `prices` and `vrp` are not part of `daily` | Observed | | `cmd_daily()` |
| APP-005 | Snapshot-reading steps take an optional snapshot folder name and default to the newest | Intended | | argparse definitions in `app.py` |
| APP-006 | `scenario` runs on demand with a position file, and is not part of `daily` | Intended | | [../changes/2026-11-06-scenario-engine.md](../changes/2026-11-06-scenario-engine.md) "Inputs and output", accepted 2026-11-06; `test_writes_legs_and_grid_with_their_columns_through_app_py` |

## Interfaces

Commands: `plan`, `daily`, `snap`, `iv`, `surface`, `term`, `context`, `history`, `ledger`, `prices`, `vrp`, `scenario`. See [../../README.md](../../README.md) "Running it".
