# APP: the command line

## Purpose

One entry point for every step, and one command for the daily routine. Code: `app.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| APP-001 | With no arguments, `app.py` runs `plan`, which is read-only, and says so | Intended | No files written by a bare run | `app.py` comment ("anything that writes has to be asked for") |
| APP-002 | `daily` runs snap, iv, surface, term, context, ledger in that order, each on the newest snapshot | Intended | | `cmd_daily()` |
| APP-003 | A failure in any `daily` step stops the run rather than letting later steps report on older data | Intended | | `cmd_daily()` docstring |
| APP-004 | `history`, `prices` and `vrp` are not part of `daily` | Observed | | `cmd_daily()` |
| APP-005 | Snapshot-reading steps take an optional snapshot folder name and default to the newest | Intended | | argparse definitions in `app.py` |

## Interfaces

Commands: `plan`, `daily`, `snap`, `iv`, `surface`, `term`, `context`, `history`, `ledger`, `prices`, `vrp`. See [../../README.md](../../README.md) "Running it".
