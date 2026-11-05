# PRICE: daily closes and implied against realized

## Purpose

Keep a cache of daily closes for SPY and the CBOE index series, and log implied against realized volatility one non-overlapping month at a time. Code: `screener/prices.py`, `screener/vrp.py`. Tests: `tests/test_prices.py`, `tests/test_vrp.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| PRICE-001 | Daily OHLC for SPY, ^VIX, ^VIX9D, ^VIX3M and ^IRX from Yahoo, cached under `data/prices/`; `prices.py` is the only file that imports `yfinance` | Intended | | `prices.py` docstring |
| PRICE-002 | Freshness is judged against the last session whose close should exist, not a fixed age | Intended | Tuesday after a long weekend still wants Monday's close | `test_tuesday_after_a_long_weekend_still_wants_mondays_close`, `test_a_weekend_walks_back_to_friday` |
| PRICE-003 | A bar for a session that hasn't closed is never written to the cache; close time is 13:00 on 1pm closes, 16:00 otherwise; the ET offset comes from zoneinfo | Intended | An EST afternoon is not a finished session | `test_a_partial_bar_is_never_written_to_the_cache`, `test_an_est_afternoon_is_not_a_finished_session`, `test_a_1pm_close_settles_at_1pm`; measurements.md 2026-11-01 |
| PRICE-004 | The cache guard and the variance clock read one calendar table | Intended | | `test_the_guard_and_the_variance_clock_read_one_table` |
| PRICE-005 | A dead API falls back to the cache; no cache and no download is an error; corrupt rows are skipped | Intended | | `test_a_dead_api_falls_back_to_the_cache_rather_than_losing_a_run`, `test_no_cache_and_no_download_is_an_error_not_an_empty_list`, `test_a_corrupt_row_is_skipped_rather_than_crashing` |
| PRICE-006 | `refresh` re-downloads everything | Observed | | `app.py`, `prices.cmd_prices` |
| PRICE-007 | One implied/realized claim per month, anchored on the month's first session (no later than the 7th); realized is measured over the same forward window | Intended | | `vrp.py` docstring; CONFIG `max_anchor_day` |
| PRICE-008 | Realized = zero-mean sqrt(mean(r^2)) on close-to-close log returns x sqrt(252) | Intended | | `vrp.py` docstring |
| PRICE-009 | Implied comes from ^VIX, and from our own variance-swap rate at 30 days (extrapolated at most 5 days) when a snapshot exists; `iv_source` records which | Intended | | `vrp.py` docstring; CONFIG `target_days`, `max_extrapolation_days` |
| PRICE-010 | Our own rate is refused from a chain collected under fewer than 12 moves below | Intended | | `vrp.converged()`; measurements.md 2026-10-15 |

## Interfaces

- `python app.py prices [refresh]`, `python app.py vrp [refresh]`.

## Gaps

- `vrp.py`'s comment says the chain tops out near 29 days; since `max_dte` went to 37 it reaches further. See A-007.
