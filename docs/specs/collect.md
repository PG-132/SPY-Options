# COLLECT: chain snapshots

## Purpose

Take one snapshot of the SPY option chain from Webull and store it raw, so every derived number can be rebuilt from it. Code: `screener/collect.py`. Tests: `tests/test_collect.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| COLLECT-001 | Uses Webull market data only and cannot place orders | Intended | No import of `webull.trade` anywhere; only `collect.py` imports `webull` | `collect.py` docstring; README.md |
| COLLECT-002 | Plans every standard SPY expiry from `min_dte` 1 to `max_dte` 37 days | Intended | Expiries outside 1-37 DTE aren't planned; adjusted (non-standard) series are dropped | `test_only_expiries_inside_the_dte_window_are_planned`, `test_only_standard_spy_series`; commit `67fe417` |
| COLLECT-003 | Same-day (0 DTE) expiries are skipped | Observed | No expiry with DTE 0 in a snapshot | CONFIG `min_dte`; A-005 |
| COLLECT-004 | Band is 12 expected moves below spot and 6 above; one move = the 30-day anchor's ATM IV x sqrt(dte/365) | Intended | Band edges match the formula; put side reaches further than the call side; higher IV widens the band | `test_band_is_expected_moves_and_follows_the_iv`, `test_the_band_arithmetic_against_hand_numbers`, `test_the_put_side_reaches_further_than_the_call_side`; measurements.md 2026-10-15 |
| COLLECT-005 | Anchor IV comes from the expiry closest to 30 days, at the strike nearest spot; falls back to 0.20 with a warning if Webull gives none | Intended | Fallback is recorded in run.json warnings | `test_uses_the_recorded_expiry_closest_to_30_days_and_the_strike_nearest_spot`, `test_missing_anchor_iv_falls_back_and_says_so` |
| COLLECT-006 | Quotes go out in batches of at most 20 contracts with a 0.25 s pause | Observed | No request exceeds 20 symbols | `test_batches_respect_the_20_contract_cap` |
| COLLECT-007 | SPY spot is recorded before the first batch, every 5 batches, and after the last, so each option can be solved against the spot nearest its own quote time | Intended | spot.csv has those rows | `collect.py` docstring; `test_one_pass_writes_a_complete_run_folder` |
| COLLECT-008 | Stores raw fields only; Webull's IV and Greeks are renamed `vendor_*` | Intended | options.csv carries `vendor_iv` etc., never `iv` | `test_rows_keep_raw_fields_and_rename_webull_greeks` |
| COLLECT-009 | Writes `data/chains/YYYY-MM-DD_HHMM/` (Eastern time) with options.csv, spot.csv, run.json; run.json records the rules used (including `moves_below`/`moves_above`), asked vs received, and warnings | Intended | All three files exist after `snap` | `test_one_pass_writes_a_complete_run_folder` |
| COLLECT-010 | Suspicious values are warnings, not caps: anchor IV outside 5-60%, band edge still carrying 1% delta, median quote older than 15 min | Intended | Each case adds a warning and the snapshot is still written | `test_edges_that_still_carry_delta_are_flagged`, `test_implausible_anchor_iv_is_flagged` |
| COLLECT-011 | `snap` warns outside regular hours (Mon-Fri 9:30-16:00 ET); it doesn't know holidays | Observed | Warning printed after 16:00 | `test_market_hours`; README.md |
| COLLECT-012 | `plan` shows what a snapshot would pull and saves nothing | Intended | No files written | `app.py` docstring |

## Interfaces

- `python app.py plan`, `python app.py snap`.
- Environment: `WEBULL_APP_KEY`, `WEBULL_APP_SECRET`, optional `WEBULL_REGION_ID`, `WEBULL_OPENAPI_TOKEN_DIR`.
- Output columns: `OPTION_COLS` and `SPOT_COLS` in `collect.py`.

## Constraints

- Needs Webull's OPRA subscription. A pass takes about two minutes at 12/6 (measurements.md 2026-10-15).
- The rate limit is unmeasured.

## Gaps

- The band is a request, not a result: on short expiries the listed strikes can stop inside it (11-05 stopped at 700 against a request down to 605). Handled downstream by TERM-006, not here.
