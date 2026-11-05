# TERM: the time axis

## Purpose

Strip the variance priced for the sessions between adjacent expiries, so one stretch of time can be set beside the next; and read vol at fixed session horizons. Code: `screener/term.py`. Tests: `tests/test_term.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| TERM-001 | Forward variance between adjacent expiries is the difference of total variances (`iv^2 * T`) over the sessions in the gap, annualized at 252 | Intended | A flat term structure prices every window the same; a single hot session shows in its own window | `test_strips_variance_not_volatility`, `test_a_flat_term_structure_prices_every_window_the_same`, `test_a_single_hot_session_shows_up_in_its_own_window` |
| TERM-002 | Strips from the variance-swap rate when the chain carries one, else from the ATM level for the whole snapshot; a window never mixes the two; `source` says which | Intended | | `test_prefers_the_variance_swap_rate_when_the_chain_carries_one`, `test_falls_back_to_the_at_the_money_level_for_the_whole_snapshot`, `test_a_window_never_mixes_the_two`; measurements.md 2026-10-16 |
| TERM-003 | A window divides by the variance clock (half days 0.5), but a one-date window is still pinned to its date via `session_priced`; affected rows are marked | Intended | | `test_a_window_divides_by_the_clock_not_by_the_date_count`, `test_one_date_is_still_one_date_when_it_closes_early` |
| TERM-004 | Expiries with the same session count make no window | Observed | | `test_expiries_with_the_same_session_count_make_no_window` |
| TERM-005 | Falling total variance is reported, never repaired, and called arbitrage only when negative by more than its error bar | Intended | | `test_falling_total_variance_is_reported_not_repaired`, `test_a_negative_inside_its_error_bar_is_not_called_arbitrage`, `test_a_negative_beyond_the_error_bar_is` |
| TERM-006 | An expiry whose `vs_edge_cost` exceeds 0.0005 is dropped from the term structure (not swapped for its ATM level) | Intended | | `test_an_under_sampled_expiry_leaves_the_term_structure`; CONFIG `max_vs_edge_cost` comment |
| TERM-007 | Every window carries `edge_margin` (the fraction of that budget its weaker foot spent) and `spans_dropped` (dropped expiries inside it); no cutoff is applied to the margin | Intended | | `test_a_window_is_only_as_resolved_as_its_weaker_foot`, `test_a_dropped_expiry_widens_a_window_rather_than_leaving_a_hole`, `test_the_cliff_is_graded_not_just_passed`; measurements.md 2026-11-02 |
| TERM-008 | Error bars propagate the fit's standard error and each expiry's `forward_iv_cost`; a one-session window is read less precisely than a five | Intended | | `test_a_one_session_window_is_read_less_precisely_than_a_five`, `test_no_error_on_the_inputs_means_no_error_on_the_answer` |
| TERM-009 | Constant maturity at 5, 10 and 15 sessions, interpolated in variance, never extrapolated past the chain | Intended | | `test_lands_on_the_flat_level_at_every_horizon`, `test_interpolates_in_variance_not_in_volatility`, `test_refuses_to_extrapolate_past_the_chain` |
| TERM-010 | A snapshot with one expiry is refused | Observed | | `test_refuses_a_snapshot_with_one_expiry` |
| TERM-011 | Writes `data/term/<snapshot>/forward.csv` and `constant.csv` | Intended | | `test_reads_both_files_and_writes_both_outputs` |

## Interfaces

- `python app.py term [snapshot]`, reading `data/iv/` and `data/surface/`.

## Gaps

- The horizons comment still reasons from a 30-day chain. See A-007.
