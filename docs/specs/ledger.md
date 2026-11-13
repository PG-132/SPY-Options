# LEDG: the record across snapshots

## Purpose

Read the surface across many snapshots: three history views, and a ledger of every window ever priced, whether it repriced, and what it delivered once it closed. Code: `screener/history.py`, `screener/ledger.py`. Tests: `tests/test_history.py`, `tests/test_ledger.py`.

## Behaviors

### History views

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| LEDG-001 | Three views, none the default: fixed expiry (what a position experiences), constant maturity (is vol higher than yesterday), per session (the market's view of one date over time) | Intended | Writes `constant_maturity.csv`, `fixed_expiry.csv`, `per_session.csv` | `test_writes_three_files_and_reports_three_views`; `history.py` docstring |
| LEDG-002 | A missing expiry reads as missing, not zero; a snapshot with no term output contributes nothing | Observed | | `test_a_snapshot_missing_an_expiry_reads_as_missing_not_zero`, `test_a_snapshot_with_no_term_output_contributes_nothing_and_does_not_crash` |
| LEDG-003 | A band change across snapshots is called out in the history report; two wide bands are not flagged against each other | Intended | | `test_a_band_change_across_snapshots_is_called_out`, `test_two_wide_bands_are_not_flagged_against_each_other` |
| LEDG-004 | `history` refuses a single snapshot | Observed | | `test_refuses_a_single_snapshot` |

### The ledger

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| LEDG-010 | Every window of every snapshot goes in, not just flagged ones | Intended | | `test_every_window_is_kept_not_just_the_flagged_ones`; `ledger.py` docstring |
| LEDG-011 | The ledger is rebuilt from every snapshot's context output each run, never appended | Intended | Rebuilding twice gives no duplicates | `test_rebuilding_does_not_duplicate` |
| LEDG-012 | The last snapshot of a date is that day's `anchor`; earlier ones are `bracket` and stay out of the pivot grid | Intended | | `test_the_last_snapshot_of_a_day_is_the_anchor`, `test_brackets_are_left_out_of_the_grid` |
| LEDG-013 | Every row records the band it was priced under, from run.json, else the chain summary, else blank (never a guess) | Intended | | `test_every_row_carries_the_band_it_was_priced_under`, `test_falls_back_to_the_chain_summary_when_the_raw_chain_is_gone`, `test_an_unknown_band_is_blank_rather_than_a_guess`; commit `1716f0e` |
| LEDG-014 | A band counts as converged when its below-spot number is at least 12 (`vrp.CONFIG["converged_moves"]`); the above-spot number isn't checked | Observed | | `ledger.converged()`; A-009 |
| LEDG-015 | Settled summary pools only converged-band rows; 6/3 rows are counted as skipped | Intended | | `test_a_narrow_band_row_is_left_out_of_the_settled_pool`, `test_a_wide_band_row_still_pools`; commit `1716f0e` |
| LEDG-016 | The skipped message gives the reason "collected under a band too narrow", including for rows whose band is unknown | Observed | | `ledger.report()`; A-002 |
| LEDG-017 | The mover table compares the newest snapshot with the one nearest 7 days earlier, at least a day old, under the same band; if the newest band is unknown the band filter is off | Intended (band filter); Observed (unknown-band case) | A band change is not a move | `test_a_band_change_is_not_a_move`, `test_the_same_band_a_week_apart_compares_normally`; A-002 |
| LEDG-018 | Movers rank on what repriced, not on what moved: roll-down is read off the older curve at a comparable span and subtracted; a window is never its own control | Intended | Pure roll-down nets to zero | `test_the_table_ranks_on_what_repriced_not_on_what_moved`, `test_pure_roll_down_nets_to_zero`, `test_the_control_is_read_only_from_the_older_curve`, `test_a_window_is_never_its_own_control`; measurements.md 2026-11-01 |
| LEDG-019 | The mover report prints windows that moved more than 0.5 vol points; the file keeps all | Observed | | CONFIG `mover_points` |
| LEDG-020 | A window spans (start, end] in sessions and settles once `end` is in the price history; realized is measured over exactly those closes; one-session windows are allowed | Intended | | `test_open_on_the_left_and_closed_on_the_right`, `test_a_single_session_is_allowed_here`, `test_a_window_past_the_data_stays_open_and_carries_no_verdict`, `test_a_closed_window_gets_both_numbers` |
| LEDG-021 | The front window settles from the snapshot's own spot; the span divides, not the number of returns | Intended | | `test_the_snapshots_own_session_close_is_measured_not_used_as_base`, `test_the_span_divides_not_the_number_of_returns`; measurements.md 2026-10-25 |
| LEDG-022 | Pooling is in variance, weighted by sessions | Intended | | `test_pooling_is_in_variance_not_in_volatility`, `test_a_long_window_counts_for_more_than_a_short_one` |
| LEDG-023 | The pivot fills every date a window spans; holidays aren't dates | Intended | | `test_a_window_fills_every_date_it_spans`, `test_a_holiday_is_not_a_date_the_grid_prices` |
| LEDG-024 | Missed sessions (trading days with no snapshot) are named, through today; closed days and weekends aren't gaps | Intended | | `test_names_the_sessions_nobody_snapped`, `test_a_closed_market_is_not_a_missed_session`, `test_the_range_runs_to_today_so_todays_miss_is_reported`; commit `8c288df` |
| LEDG-025 | No context output is an error, not an empty file | Observed | | `test_no_context_output_is_an_error_not_an_empty_file` |
| LEDG-026 | A fourth history view, a fixed strike across a move: from each day's last snapshot to the next, per expiry, the sessions between, SPY's move (from the median spot vol.py matched quotes to), the strike nearest the old spot within 0.6%, its days to expiry at the second snapshot, its IV change, that change times sqrt(days/30) and that per 1% of move, written to `response.csv` by `history` and by `daily`'s `response` step, so the IV response band's rates and expiry scaling are checked on every new move. The change is the total at the strike, the engine's own time roll included (large across a weekend; measurements.md 2026-11-11) | Intended | AC-11 of [../changes/2026-11-11-iv-response.md](../changes/2026-11-11-iv-response.md) | owner accepted the record 2026-11-12; `TestFixedStrike` (3 tests); on the real snapshots it reproduces the five events of measurements.md 2026-11-11 within a few hundredths; integrity.md item 6 |

## Interfaces

- `python app.py history [N]`, `python app.py ledger [N]`.
- Output: `data/history/*.csv` (`response.csv` columns: `RESPONSE_COLS` in `history.py`), `data/ledger/windows.csv`, `data/ledger/pivot.csv`. Columns: `COLS` in `ledger.py`.

## Constraints

- Settled rows are only worth anything in aggregate; event days need separating before the aggregate means much (`ledger.py` docstring).

## Gaps

- `history.py` keeps its own copy of the threshold 12 (`CONVERGED_MOVES`) instead of reading `vrp.CONFIG`. See A-009.
