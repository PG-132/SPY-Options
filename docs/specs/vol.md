# VOL: pricing, IVs, clocks

## Purpose

Turn a raw snapshot into our own implied volatilities with error bars: the forward from parity, one IV per strike, an IV band, our Greeks, reference points, and the variance-swap rate. Also owns the exchange calendar and the session clocks. Code: `screener/pricing.py`, `screener/vol.py`. Tests: `tests/test_pricing.py`, `tests/test_vol.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| VOL-001 | Black-Scholes is priced off the forward, European, per share | Intended | Reproduces the straddle tool's frozen reference cases to float noise | `test_reproduces_straddle_tool_exactly`; `pricing.py` docstring |
| VOL-002 | The IV solver refuses prices at or below the no-arbitrage floor or beyond any volatility | Observed | Raises `SolveError` | `test_refuses_a_price_at_the_no_arbitrage_floor`, `test_refuses_a_price_no_volatility_can_reach` |
| VOL-003 | Forward from put-call parity: pairs with call/put spread asymmetry over 0.05 are rejected; up to 6 tightest survivors averaged 1/width^2; if none pass, weight on asymmetry instead | Intended | See tests | `test_rejects_a_pair_whose_legs_are_quoted_unevenly`, `test_weights_on_asymmetry_when_no_pair_is_even_enough`, `test_uses_no_more_pairs_than_asked_for`; measurements.md 2026-10-10 |
| VOL-004 | `forward_error` is reported, never below what one pair can be read to; a warning when the pairs don't bracket the forward | Intended | Column present; warning text in run output | `test_reports_the_disagreement_as_its_own_number`, `test_the_error_bar_never_falls_below_what_one_pair_can_be_read_to`, `test_says_so_when_the_pairs_do_not_bracket_the_forward` |
| VOL-005 | One IV per strike from the out-of-the-money side: puts below the forward, calls above | Intended | No in-the-money leg is solved | `test_reads_the_out_of_the_money_side_only`; `vol.py` docstring |
| VOL-006 | Each strike gets an IV band solved at bid and ask; quotes with bid under 0.005 have no IV | Intended | `iv_bid <= iv <= iv_ask` | `test_the_iv_band_brackets_the_mid`, `test_drops_quotes_with_no_market` |
| VOL-007 | Each quote is solved against the SPY spot recorded nearest its own quote time | Intended | | `test_matches_each_quote_to_the_nearest_spot`; integrity.md "Handled" |
| VOL-008 | Time to expiry is actual seconds from the snapshot to 16:00 ET on the expiry date, over 365 days | Intended (the hours rule); Observed on 1pm-close expiries, where the clock still ends at 16:00 (A-003, deferred by the owner 2026-11-05) | `test_time_to_expiry_counts_hours_not_whole_days` passes | measurements.md 2026-09-24; A-003; Gaps below |
| VOL-009 | Rate is a flat 4%, written into every row | Intended | | CONFIG `rate`; integrity.md "Handled" (checked 2026-10-18 against ^IRX) |
| VOL-010 | Variance clock: sessions from the day after the snapshot through expiry, skipping weekends and `HOLIDAYS`; a `HALF_DAYS` date counts 0.5 | Intended | `sessions_between` returns a float; the two clocks agree where nothing closes early | `test_sessions_skip_weekends_and_holidays`, `test_a_1pm_close_is_about_half_a_session_on_the_variance_clock`, `test_the_two_clocks_agree_wherever_nothing_closes_early`; measurements.md 2026-10-30 |
| VOL-011 | The 0.5 weight measured on Thanksgiving Fridays is applied to every 1pm close, including Christmas Eve | Observed | | `vol.py` comment above `HALF_DAYS`; A-006 |
| VOL-012 | Calendar clock counts whole dates (a half day is one date); ledger gap detection counts a half day as a day you can snapshot | Intended | | `test_a_half_day_is_still_a_day_you_can_snapshot`; `vol.py` docstrings |
| VOL-013 | `HOLIDAYS` and `HALF_DAYS` match NYSE's published calendar through 2027; an expiry past the last date warns rather than counting silently | Intended | Tables equal the NYSE list | Sourced: NYSE Group release of 2025-12-23, checked 2026-11-04 (see status.md) |
| VOL-014 | Our own Greeks at our own IV; reference points at the forward and at 25 and 10 delta each side | Intended | | `test_our_greeks_come_from_our_iv`, `test_at_the_money_and_delta_points_land_on_the_smile` |
| VOL-015 | Variance-swap rate per expiry over out-of-the-money strikes, with `vs_edge_cost` (what the outermost strike pair was worth) and the collection band carried on every expiry | Intended | A flat smile returns its own vol; skew lifts it above ATM; cutting the band understates it | `test_a_flat_smile_gives_back_its_own_volatility`, `test_skew_lifts_it_above_the_at_the_money_level`, `test_cutting_the_band_understates_it` |
| VOL-016 | `forward_iv_cost`: cents of forward error turned into vol points; unknown, not zero, when a shifted solve fails | Intended | | `test_turns_cents_of_forward_into_vol_points`, `test_an_unsolvable_shift_is_reported_as_unknown_not_zero` |
| VOL-017 | An expiry with no strike quoted on both sides is skipped with a warning | Observed | | `test_skips_an_expiry_it_cannot_read` |
| VOL-018 | Writes `data/iv/<snapshot>/contracts.csv` and `expiries.csv`; never touches the snapshot | Intended | | `test_writes_both_files_with_their_columns` |

## Interfaces

- `python app.py iv [snapshot]`, default the newest.
- Columns: `CONTRACT_COLS` and the expiry columns in `vol.py`.

## Constraints

- European math on American options: early exercise is avoided by reading out-of-the-money only, but not bounded. Open as docs/integrity.md item 2.

## Gaps

- On an expiry that closes at 1pm (2026-11-27, 2026-12-24), VOL-008 still ends the clock at 16:00, so T runs three hours long. Prices fix total variance (σ²T), not σ, so every IV in that expiry comes out low by √(T_true / T_used) while its total variance stays right. The bias therefore stays inside that expiry's annualized readings: `atm_iv`, `vs_rate`, the delta points and skews, each strike's IV, and vega and theta (delta and gamma depend only on σ√T). Nothing built from total variance sees it, because `term.py` rebuilds total variance as level² × T with the same T and divides windows by the session clock: forward windows, constant maturity, context, ledger settlement, and the 30-day rate in `vrp.py`, which interpolates in total variance. Size, from the formula at 13-15% IV (arithmetic, not measured on a chain): about 0.04 vol points three weeks out; 0.4-0.5 points from the 2026-11-25 15:45 snapshot on the 11-27 expiry; 0.8-1.0 points from the 2026-12-23 snapshot on the 12-24 expiry. The fixed-expiry view in `history.py` will show those expiries' ATM sagging in their last day or two: that is the clock, not the market. The owner deferred a fix as a separate, lower-priority decision on 2026-11-05. See A-003.
