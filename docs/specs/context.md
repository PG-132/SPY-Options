# CTX: where a chain's pricing sits

## Purpose

Compare every window of one chain against the rest of that chain and against its neighbours, without choosing which windows to look at; and rank the 30-day level against VIX history. Code: `screener/context.py`. Tests: `tests/test_context.py`.

## Behaviors

| ID | Behavior | Status | Acceptance criteria | Evidence |
| --- | --- | --- | --- | --- |
| CTX-001 | The windows tile the chain: a front window runs from the snapshot to the first expiry, so sessions and variances add to the chain's totals | Intended | | `test_the_windows_tile_the_chain`, `test_the_first_window_starts_at_spot_not_at_the_first_expiry`, `test_no_time_carries_no_variance_and_no_doubt_about_it` |
| CTX-002 | The front window includes what is left of the snapshot's own session, in sessions: the fraction of 9:30 ET to the close still ahead | Intended | Before the open the whole session is left; after the close none is; unchanged in EST | `test_the_snapshot_sits_before_the_close_not_on_it`, `test_after_the_close_nothing_is_left`, `test_before_the_open_the_whole_session_is_left`, `test_an_ordinary_winter_day_still_runs_to_four`; measurements.md 2026-10-25 |
| CTX-003 | On a 1pm-close day the session runs 9:30-13:00 (`prices.session_close`) and what is left of it counts at the half-day weight `vol.CONFIG["half_day"]`, the units of the session clock | Intended | A 12:45 snapshot on 2026-11-27 leaves 15/210 x 0.5 sessions, not 0.5; after 13:00 none; the front window to Monday spans 1.036 sessions | `TestTheSnapshotsOwnSessionOnA1pmClose` (5 tests); user, 2026-11-05 |
| CTX-004 | Snapshot time comes from the collector's timestamp, else the folder name; an unreadable name assumes the close | Observed | | `test_reads_the_collectors_own_timestamp`, `test_falls_back_to_the_folder_name`, `test_an_unreadable_name_assumes_the_close` |
| CTX-005 | `vs_rest`: the window against the chain's total variance less this window's, over the sessions left | Intended | A flat chain reads flat; a sloping chain makes the front cheap and the back rich | `test_a_flat_chain_reads_flat_everywhere`, `test_the_rest_is_the_chain_less_this_window`, `test_a_sloping_chain_makes_the_front_cheap_and_the_back_rich` |
| CTX-006 | `vs_neigh`: the window against the straight line between its two neighbours, read at its own midpoint in session space; the ends are blank | Intended | A straight line reads flat even with uneven gaps | `test_a_straight_line_reads_flat_even_when_the_gaps_are_uneven`, `test_a_window_jutting_above_both_sides_is_found`, `test_the_ends_are_blank_rather_than_measured_one_sided` |
| CTX-007 | No term-structure curve is fitted; both comparisons are arithmetic | Intended | | `context.py` docstring |
| CTX-008 | Error bars account for shared endpoints with opposite signs | Intended | | `test_a_difference_is_less_certain_than_either_side_of_it`, `test_the_last_window_does_not_count_the_chains_end_twice` |
| CTX-009 | The 30-day level is ranked as a percentile against ^VIX history; no rate means no percentile, not zero | Intended | | `test_ranks_against_the_history`, `test_no_rate_means_no_percentile_rather_than_a_zero` |
| CTX-010 | Writes `data/context/<snapshot>/`; a chain with no 30-day rate still decomposes | Observed | | `test_writes_both_files_and_reports_every_window`, `test_a_chain_with_no_thirty_day_rate_still_decomposes` |

## Interfaces

- `python app.py context [snapshot]`, reading `data/surface/` and `data/term/`, and VIX via `prices`.
