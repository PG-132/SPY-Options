# SURF: gates, smile fit, edges

## Purpose

Fit one smooth smile per expiry through the readable IVs, then measure what sits off it at prices you could actually trade. Code: `screener/surface.py`. Tests: `tests/test_surface.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| SURF-001 | Readable gate: IV band at most 0.005 (half a vol point) and vega at least 0.05 ($5 per contract per vol point) | Intended | Points failing either carry a `why_not` reason | `test_readable_needs_a_narrow_band_and_real_vega` |
| SURF-002 | Tradeable gate: spread at most 25% of premium, open interest at least 10, volume at least 1, quote age at most 5 min | Intended | | `test_tradeable_checks_spread_interest_volume_and_age` |
| SURF-003 | Blank open interest means unknown (not zero); blank volume means no trades (zero), because Webull never sends a zero | Intended | | `test_missing_open_interest_is_unknown_not_zero`, `test_missing_volume_is_zero_not_unknown`; commit `52dd17d` |
| SURF-004 | Only readable points are fitted; every point is still scored | Intended | | `test_skips_unreadable_points_but_still_scores_them` |
| SURF-005 | Smile shape: `iv = c0 + c1*d + c2*sqrt(d^2+s^2) + c3*d^2 + c4*d^3`, d = ln(K/F) - m; only m and s are searched, the five coefficients by weighted least squares, weights 1/band^2 with a floor of 0.0005 | Intended | Recovers a known smile; a wide quote can't drag the curve | `test_recovers_a_known_smile`, `test_a_wide_quote_cannot_drag_the_curve`; measurements.md 2026-09-24 "Two smile shapes that failed" |
| SURF-006 | Fewer than 8 readable points: the expiry isn't fitted | Intended | | `test_refuses_to_fit_too_few_points` |
| SURF-007 | Residual sign flips are counted per expiry as the shape check | Intended | `sign_changes` in fits.csv | `test_sign_changes_counts_flips_along_the_smile`; integrity.md "Handled" |
| SURF-008 | `edge_at_bid` = IV at bid minus curve; `edge_at_ask` = curve minus IV at ask; a deviation inside the spread is not an edge | Intended | | `test_edges_are_measured_at_the_prices_you_would_trade`, `test_a_deviation_inside_the_spread_is_not_an_edge` |
| SURF-009 | `forward_cost` per point is measured by refitting at the shifted forward; an edge counts only if it clears its spread and outlasts this | Intended | | `test_a_pure_common_mode_shift_costs_almost_nothing`, `test_an_edge_smaller_than_the_forward_cost_does_not_count`; measurements.md 2026-10-11 |
| SURF-010 | The fitted curve is only evaluated between the strikes it was fitted on | Intended | | integrity.md "Standing rules" |
| SURF-011 | Writes `data/surface/<snapshot>/points.csv` and `fits.csv`; nothing upstream is touched | Intended | | `test_writes_points_and_fits` |

## Interfaces

- `python app.py surface [snapshot]`.
- Columns: `POINT_COLS`, `FIT_COLS` in `surface.py`.

## Constraints

- The fit shape was set on calm chains only (ATM near 13%). Open as docs/integrity.md item 4.
