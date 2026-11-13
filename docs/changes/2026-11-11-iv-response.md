# IV response band

State: verified (built 2026-11-12; uncommitted until the owner pushes). Accepted by the owner 2026-11-12: "Yes, your picks", closing the last two questions
Created: 2026-11-11
Specs: SCEN-004 (replaced), SCEN-006, SCEN-011, SCEN-013, new SCEN-015 and SCEN-016 ([../specs/scenario.md](../specs/scenario.md)); new LEDG-026 ([../specs/ledger.md](../specs/ledger.md))
Builds on: [2026-11-06-scenario-engine.md](2026-11-06-scenario-engine.md)

## Problem

The engine answers "what is this position worth if SPY moves x%" with one number, and that number rests on a rule the owner's own chains contradict. Rule 1 of the engine record slides each strike's IV along the fitted smile as spot moves. Across the five large moves the snapshots hold, every strike near the old spot moved the opposite way to what the slide predicted: down days raised its IV, up days lowered it ([measurements.md](../measurements.md), 2026-11-11 entry). On a short Nov-20 750 straddle the slide shows +$20 on a 1% drop; holding the strike's IV fixed shows -$97, and the IV rise seen on real down days makes it worse.

Nobody knows exactly how much IV moves with spot, only that big drops raise it more than rallies lower it. So the honest output is a band: a few P&Ls per spot move, one per IV response, sized generously from what has been seen and narrowed as tail events come. (**Decided**, owner 2026-11-11: "at each of those moves there's for instance 3 possible p&l's based on iv shift"; "umbrella figures first, then narrow it down as we do experience those tail events".)

Why not call it the "IV band": that name already means each strike's quote band, `iv_bid` to `iv_ask`, which every value's range is built from (SCEN-008). This is the **IV response**: the change in a strike's IV that comes with a spot move. The band is the set of three responses.

## Intended behavior

### 1. As spot moves, each strike keeps its IV

The baseline holds each strike's IV fixed as spot moves (sticky strike); the smile no longer slides. This replaces rule 1 of the engine record. The time roll (rule 2), the parallel shift (rule 3), entry at mid, the quote-band error bars, hedges and Greeks are unchanged. (**Decided**, owner 2026-11-11, agreeing to the proposal that put it as decision 1; it reverses the owner's 2026-11-06 choice of the slide.)

**Time passing and the IV on a date are separate inputs.** (**Decided**, owner 2026-11-12: "keep the distinction that time passing and iv changing with time are separate inputs".) A point has three inputs:
- **The date.** Time passing: it sets each leg's time to expiry (and the forward's carry), and nothing else.
- **The spot.**
- **Each strike's IV on that date.** Its own input, reached in steps:
  1. Start from today's IV for the strike.
  2. Carry it to the date along today's term structure (rule 2, the time roll).
  3. Add the response to the spot move (section 2).
  4. Add any `--shift`.

  Later, typing an IV replaces all four steps and leaves the date alone (section 8).

Steps 1 and 2 are the default IV, "no change in the market's view". For a later date that is the forward IV today's chain prices for what is left of the option's life. As a quoted number it can still move. The Nov-20 750 on `2026-11-10_1540`, with SPY unchanged, reads 16.20% now, 16.42% at the Nov 13 close and 19.79% at the Nov 17 close (engine output). Part of that rise is the weekend leaving the window, since variance is counted per session (the owner's 2026-11-06 choice: weekends cost nothing). The rest is today's term structure pricing the last sessions above the week's average.

Holding the quoted 16.20% instead would decay the weekend as two full days. On this straddle that reads +$725 by the Nov 17 close against the engine's +$531 (engine outputs). So "fixed as spot moves" does not mean frozen in time. Each date block in the report shows every leg's IV beside its days to expiry, so the two inputs can be read apart. (**Proposed**, agent, for the display.) (Added 2026-11-12, after the owner asked how a fixed IV compares values over time.)

What follows from it:
- A leg reads the fitted curve only at the start, and only when vol.py had no IV for its strike (`fit_iv`). The `edge` and `no_fit` flags no longer arise from a spot move and are retired.
- Most `arb` breaches go with the slide. The 2026-11-11 scan with IVs held at the start date: 7 of 146,880 five-wide verticals broke a bound, against 2,658 with the slide; butterflies 2.3%, all but 2 inside their own quote bands (measurements.md 2026-11-11). The `arb` check stays.
- integrity.md item 4 (the fit's shape under stress) matters less to the engine, since a moving leg no longer travels along the fitted curve.

### 2. Three IV responses at every point

At every scenario point each live option leg is priced three times:

| Case | Response, vol points | Down move (SPY lower) | Up move (SPY higher) |
| --- | --- | --- | --- |
| `none` | no change | 0 | 0 |
| `moderate` | rate x m x sqrt(30 / days) | +1.0 per 1% | -1.0 per 1% |
| `large` | rate x m x sqrt(30 / days) | +2.0 per 1% | -1.5 per 1% |

- `m` is the size of the move from the snapshot's spot in percent, `100 x |S'/S - 1|`.
- `days` is the leg's calendar days to expiry at the point: `vol.years_to_expiry` x 365, the measure the event readings used.
- One response per expiry, the same for every strike on it: a parallel shift per expiry. A change in skew is not modelled; on Nov 5 the strike 5% above the old spot rose +4.3 at 29 days against +2.9 at the old spot.
- The response is added after the time roll, together with any `--shift`: `IV = start IV x roll ratio + (response + shift) / 100`, floored as now (`iv_floor`).

The rates are umbrella figures, chosen above what was measured rather than equal to it. They stay until typed IVs (section 8) and more tail events take over. (**Decided**, owner 2026-11-11: "i agree with your change record ... those are generous coefficients above the two observed downside rates"; up moves widened 2026-11-12: "-1 and -1.5 ... umbrella figures that sit above measured rallies".)
- **Down moves.** The two measured 30-day rates were +0.47 (Oct 29-30, -1.81%) and +0.66 (Nov 4-5, -4.43%) per 1%. `moderate` is about 1.5 to 2 times those, `large` 3 to 4 times.
- **Up moves.** The two measured rates were -0.60 (Nov 6-9, +2.08%) and -1.18 (Nov 3-4, +1.48%, the day after the election). `large` at -1.5 sits above both; `moderate` at -1 sits above the first and near the second. The first draft, -0.5 and -1, put `large` between them.

What the band looks like, as an illustration from the engine on one position (engine output under these rates, not a finding): a short Nov-20 750 straddle on `2026-11-10_1540`, 10 days to expiry (factor sqrt(30/10) = 1.73), spot moving now.

| Move | `none` | `moderate` | `large` | Slide (today's engine) |
| --- | --- | --- | --- | --- |
| -3% | -883 | -1,198 (+5.2) | -1,576 (+10.4) | -738 |
| -1% | -97 | -258 (+1.7) | -420 (+3.5) | +20 |
| +1% | -123 | +36 (-1.7) | +114 (-2.6) | -245 |
| +3% | -937 | -722 (-5.2) | -675 (-7.8) | -1,176 |

### 3. Cases are named for the IV change, not for the outcome

Which case hurts depends on the position. In the table above, `large` is the worst case for the short straddle on a drop, but the best on a rally, where a bigger IV fall helps it; there `none` is the worst. For a long straddle every row turns over. (**Decided**, owner 2026-11-11: "'bad' changes with the position. even in your example the larger iv decline during a rally improves p&l".) So no case is labelled good or bad. At each point the report names which case is lowest and which highest for this position.

### 4. The expiry scaling is provisional

sqrt(30 / days) is a reasonable shape, not yet a rule: it agreed across a few expiries on a few moves, which doesn't establish it in general. It is to be checked on each new move over one to five weeks to expiry. (**Decided**, owner 2026-11-11: "treat the expiry scaling as provisional ... we should see how it unfolds over a one to 5 week range".)

What it rests on (measurements.md, 2026-11-11). Under the rule, a change times sqrt(days / 30) is the same at every expiry.
- **7 to 36 days:** that product stayed within 12-25% across expiries on four of the five moves. On the fifth, Nov 6-9 (Friday to Monday), it ranged 1.86 times: the change was -1.3 to -1.6 at every expiry from 7 to 32 days, flat rather than falling with tenor. (Found 2026-11-12: that was mostly the weekend in the engine's own time roll; net of it, Nov 6-9 fits. See Notes.)
- **Under 7 days:** the rule missed both ways. On Nov 3-4 the 1- and 2-day expiries moved about 35% less than the 30-day expiry implies through it. On Nov 4-5 the 1-day expiry moved about 47% more. On Nov 6-9, the 1- to 4-day expiries' IV rose or held on an up move.

So (**Proposed**, agent):
- A leg whose days to expiry at a point fall outside 7 to 35, where the response is not zero, is flagged `tenor`: "outside the one-to-five-week range the expiry scaling is being checked over".
- The scaling is not capped there. A cap would assume a direction, and under a week the misses went both ways.

### 5. The horizon is its own input

Two inputs, not one:
- **Horizon:** the sessions from the snapshot to the scenario date, which is how long the move took.
- **Tenor:** each leg's days to expiry on that date.

The event readings and the VIX table are one-session moves. A "3% over five days" scenario therefore needs its own stated assumption about the response, not the one-session figure carried over silently. (**Decided**, owner 2026-11-11: "keep the scenario horizon explicit ... days remaining until expiry and days taken to reach the scenario are 2 different inputs"; "we should still take those vix values loosely".)

The assumption (**Decided**, owner 2026-11-12, the agent's pick): the rates apply to the whole move from the snapshot's spot, the same however many sessions it took. The `now` column, where spot moves with no time passing, reads them as one session's reaction, the nearest thing measured.

What supports it, loosely (VIX daily closes 1993-2026, overlapping windows, SPY moves of 1.5% or more; measurements.md 2026-11-11):
- **Down moves:** the median VIX change per 1% is +1.16 over one session, +1.04 over five and +0.87 over twenty-one. The 90th percentile stays near +2.1 per 1% at every horizon.
- **Up moves:** the response fades faster: -0.94 per 1% over one session, -0.79 over five, -0.51 over twenty-one.
- **Reading:** holding the rates constant is about right out to a week and increasingly generous after that, more so on up moves. For a short-vol position on a slow rally, "generous" means flattering.

What it leaves out, said in the report:
- **IV against the usual way.** IV can move the other way to the band. VIX did so on 3-6% of one-session moves of 1.5% or more, 8-11% over five sessions and 12-22% over twenty-one. The band's other edge is `none`, at zero, and no fourth case is added (**Decided**, owner 2026-11-12, the agent's pick).
- **IV moving on its own.** Without any spot move the response is zero. `--shift` is how to ask for that.

The input (**Proposed**, agent): `--sessions 1,5` adds grid dates at the close 1 and 5 sessions after the snapshot, beside the default dates (now, each expiry, the session before the last). Each date's block in the report states its sessions passed and every leg's days to expiry there.

### 6. Output

All **Proposed**, agent:
- **`grid.csv`:** one row per leg per point per case. Two new columns, after `iv_shift` (and, added in the build, `move_pct` beside `moves` and `days_left` before `iv`, so the move in the rates' unit and the leg's own clock are in the file too):
  - `response`: `none`, `moderate` or `large`;
  - `iv_response`: that leg's response in vol points, blank on hedges and total rows.

  Every case carries its value, P&L, quote-band range (`low <= mid <= high`) and Greeks. The Greeks are kept under all three because every one of them moves with IV, and how the Greeks change with spot and time is what the owner wants from the engine.
- **The report:**
  - One block per date. Rows are spot moves, with the percent beside the expected moves. Columns are `none`, `moderate` and `large` P&L, then which case is lowest and which highest.
  - Above the blocks, once: the rates, where they came from, and the horizon assumption.
  - Greeks now, at fixed IV, as before. The grid-slope line (SCEN-013) becomes each case's slope just below and just above spot. Under `none` that is the fixed-IV delta on both sides. The other two cases add vega x d(response)/dS, which differs by side since the rates do.
- **`report` id:** includes the rates and the `--sessions` list, so a change to either makes a new id. The `inputs` fingerprint is unchanged.
- **Paths:** priced at `none` plus each step's own `iv_shift`, with no response added. A path is the owner's own story for IV, and adding a response on top would count it twice. Rule 1's change still applies to them.

### 7. A repeatable check on each new move

`history` gains a fourth view, a fixed strike across a move (**Proposed**, agent). For each pair of consecutive snapshots carried through `iv`, it writes one row per expiry to `data/history/response.csv`:
- the sessions between the two snapshots, and SPY's move;
- the strike nearest the old spot, and its days to expiry at the second snapshot;
- its IV change, and that change times sqrt(days / 30).

`daily` did not run `history` (the record first said it did), so `daily` gains a last step, `response`, that writes this view alone (`history.cmd_response`, three lines of report); the full `history` writes it too. Every new move is measured without anyone remembering to. It is what this record's scratch scripts did by hand for the five events. When the owner narrows the rates, or keeps or drops the scaling, the readings go into measurements.md and the constants change as the Conventions say.

### 8. Later: typing the IV

The owner wants to be able to say "IV will be 25% on Friday" and have the position priced at Friday's spot and remaining time at that IV. (**Decided** as the direction, owner 2026-11-12: "later in development i should be able to manually input my own iv to simplify things".) It is not part of this build. It is its own change, after this one.

A typed IV replaces the whole IV input of section 1, leaving the date as it is. The umbrella rates stay as the default for points where no IV is typed.

Open for that change:
- On a position with several strikes, what one typed number sets: every strike on the expiry, with the smile's shape kept around it, or one IV per leg.
- Whether the grid, the path steps (which already take an `iv_shift`), or both accept it.
- Whether the report shows the default IV beside the typed one, so the typed number also reads as a change against today's view.

## Scope

In: the spot rule (sticky strike), the three cases on the grid, the `--sessions` input, the report, the `tenor` flag, the `report` id, the history view.

Out:
- Responses that vary by strike (skew changes).
- A response on paths.
- A fourth case against the usual direction (owner 2026-11-12: stated as a limit instead).
- Typing an IV directly (section 8): the next change.
- Fitting the rates to data: that is the narrowing the owner wants to do over time, one event at a time.
- Any forecast. The cases say what P&L would be under each response, not how likely each is.

## Acceptance criteria

- **AC-1** With spot moved and the date unchanged, a leg's IV under `none` is its start IV plus `--shift`, whatever the smile. At the start P&L is 0 and Greeks equal contracts.csv's, as before (engine AC-1, AC-2).
- **AC-2** A leg's response is rate x m x sqrt(30 / days) vol points, positive on a down move, negative on an up move, zero at unchanged spot, and the same for every strike on one expiry. For a leg 10 days from expiry:
  - SPY -2%: `moderate` +3.46, `large` +6.93;
  - SPY +2%: `moderate` -3.46, `large` -5.20.
- **AC-3** The response is added after the time roll and with `--shift`. A response or shift below the floor is floored and flagged `iv_floor`.
- **AC-4** The same move and days to expiry give the same response at 0 and at 5 sessions. That pins the horizon assumption, so changing it has to be deliberate.
  - `--sessions 1,5` adds the closes 1 and 5 sessions after the snapshot.
  - A value that is not a positive whole number is refused.
  - A date already in the grid appears once.
- **AC-5** Every grid point carries all three cases. Each case has its value, P&L, its range from the quote band (`low <= mid <= high`) and its Greeks. `grid.csv` carries `response` and `iv_response` (and `move_pct`, `days_left`).
- **AC-6** The report names, per point, the lowest and highest case:
  - SPY +2%: a short straddle's lowest is `none`, a long straddle's is `large`;
  - SPY -2%: a short straddle's lowest is `large`.
- **AC-7** A leg with under 7 or over 35 days to expiry at a point where its response is not zero is flagged `tenor`, and its response is not capped.
- **AC-8** The report states, once:
  - the rates and their source;
  - that they are the same at every horizon;
  - that IV against the usual way, and IV moving with no spot move, are outside the band.

  Each date block states its sessions passed, every leg's days to expiry, and every leg's IV there under `none`, so time passing and the IV on that date read as separate inputs.
- **AC-9** The `report` id changes when the rates or `--sessions` change; `inputs` does not.
- **AC-10** A path is priced at `none` plus its steps' `iv_shift`, with no response.
- **AC-11** `history` writes `response.csv`, one row per consecutive pair of snapshots per expiry, with the columns in section 7. It is tested offline on two synthetic snapshots with a known move and known IVs.
- **AC-12** Tests are offline, in temporary directories, and never read the real `data/`. The tests that pin the slide (SCEN-004's three, SCEN-013's on a skewed smile) are rewritten for the new rule and named in the build notes, not dropped silently.

## Affected areas

- `screener/scenario.py`:
  - `price_leg` loses the slide and gains the response;
  - `price_point`, `grid`, `grid_slope` and the report work per case;
  - `CONFIG` gains the rates, the 30-day anchor and the 7-35 day range, each with its measurements.md entry (Conventions);
  - `FLAGS` loses `edge` and `no_fit` and gains `tenor`;
  - `GRID_COLS` gains `response` and `iv_response`;
  - the docstring's THE RULES section is rewritten.
- `screener/history.py`: the response view and its `*_COLS`. `app.py`: `--sessions`, the `response` step in `daily`, and the docstring.
- Tests: `tests/test_scenario.py`, `tests/test_history.py`.
- Docs:
  - concepts.md "What-if: the scenario engine" gains the response, its cases and the new columns;
  - specs/scenario.md and specs/ledger.md;
  - integrity.md items 4, 5 and 6;
  - context.md, where the slide moves to Rejected approaches;
  - AGENTS.md Commands, the README's "Running it" list, status.md.

## Verification plan

- **Offline tests:** on the existing synthetic chain, one per criterion, named as sentences. Then break each new rule in turn in a copy of the code:
  - the response's sign flipped;
  - the scaling dropped;
  - the response scaled with the horizon;
  - the response added before the roll;
  - the cases' order swapped.

  Each must fail a test.
- **Manual run:** the short Nov-20 750 straddle on `2026-11-10_1540`, through `app.py`. Its rows must reproduce the illustration above to the dollar. Record the run in the Commands table.
- **History view:** on the snapshots held, `history` must reproduce the five events' readings in measurements.md 2026-11-11.

## Tasks

Start here in a new session: read AGENTS.md and docs/status.md, then this record and the 2026-11-11 measurements.md entry. Ask the owner any Open question still open. Leave the work uncommitted (AGENTS.md, Git).

- [x] Owner answers the Open questions: all three, 2026-11-12
- [x] Rule 1 to sticky strike, retiring `edge` and `no_fit` for moves; rewrite the slide tests (AC-1, AC-12)
- [x] The response per case, its CONFIG rates and range, and the `tenor` flag (AC-2, AC-3, AC-5, AC-7)
- [x] `--sessions` and the horizon rule (AC-4)
- [x] Report blocks, lowest and highest case, the stated assumptions, slope per case (AC-6, AC-8)
- [x] `report` id; paths at `none` (AC-9, AC-10)
- [x] The history view (AC-11)
- [x] Manual run on `2026-11-10_1540`; docs; fold the behaviors into the specs as Intended (AC-12)

Stopped: nothing half-done. Everything is uncommitted for the owner to commit at push time.

## Verification evidence

All on 2026-11-12, Python 3.14.3, owner's machine. `python -m unittest discover tests`: 385 passed (366 before). `tests/test_scenario.py` 103 to 119, `tests/test_history.py` 13 to 16.

**Tests rewritten, not dropped (AC-12).** The slide's three spot tests became `test_a_spot_move_leaves_each_strikes_iv_where_it_was`, `test_a_strike_far_past_the_fitted_range_keeps_its_iv_with_no_edge_flag` and `test_an_expiry_without_a_fit_moves_like_any_other`. The first also checks that the slide would have moved each IV by more than 0.1 vol point. Its two slope tests became `test_with_no_response_the_grid_slope_is_the_fixed_iv_delta_on_both_sides` (now on a skewed smile) and `test_each_response_adds_vega_times_its_own_slope_on_each_side`. Three tests changed shape only: `report_for` reads the `none` total, the shift test's docstring drops the slide, and `history.analyse` returns the new view, which three history tests now unpack.

**Do the tests catch a broken rule?** Each of 16 rules was broken in turn in a copy of the code, and every one failed at least one test:
- the slide restored;
- the response's sign flipped;
- the scaling dropped;
- the response scaled with the horizon;
- the response added before the roll;
- the cases' rates swapped;
- short tenors capped instead of flagged;
- the `tenor` flag dropped;
- the report id leaving out the rates;
- a path priced under a response;
- the lowest case fixed as `large`;
- sessions counted as calendar days;
- the slope leaving out the response;
- history taking days from the first snapshot;
- history taking the strike nearest the new spot;
- history reading every snapshot instead of each day's last.

| AC | Tests | On real data |
| --- | --- | --- |
| AC-1 | `TestSpotKeepsEachStrikesIV` (4) | |
| AC-2 | `test_the_response_is_rate_times_move_times_root_30_over_days`, `test_a_leg_carries_its_response_on_top_of_its_own_iv`, `test_no_spot_move_and_no_response_mean_no_change`, `test_every_strike_on_one_expiry_gets_one_response_scaled_by_its_days` | The illustration in section 2, reproduced to the dollar (below) |
| AC-3 | `test_the_response_goes_on_after_the_roll_together_with_the_shift` | |
| AC-4 | `test_the_same_move_gets_the_same_rate_whatever_the_horizon`, `test_sessions_add_the_closes_that_many_sessions_out`, `test_sessions_that_are_not_positive_whole_numbers_are_refused`, `test_sessions_given_with_a_path_are_refused` | `--sessions 5` added the Nov 17 close |
| AC-5 | `test_every_grid_point_carries_all_three_cases`, `test_writes_legs_and_grid_with_their_columns_through_app_py` | |
| AC-6 | `test_the_lowest_case_depends_on_the_position` | Short straddle: `large / none` on every drop row; `none / large` on the rallies to +2 moves, `none / moderate` beyond, where both responses floor IV and tie |
| AC-7 | `test_a_leg_outside_one_to_five_weeks_is_flagged_tenor_not_capped` | `tenor` on 24 of 52 points, the dates with 3 and 1 days left |
| AC-8 | `test_the_report_states_the_rates_the_horizon_rule_and_what_the_band_leaves_out` | |
| AC-9 | `test_the_report_id_follows_the_rates_and_sessions_and_inputs_does_not` | |
| AC-10 | `test_a_path_is_priced_with_no_response` | |
| AC-11 | `TestFixedStrike` (3) | Read-only over the 16 days held: the five events of measurements.md 2026-11-11 reproduced within a few hundredths (the view's spot is vol.py's median quote spot, not run.json's), and a sixth, Nov 10-11, read for the first time |
| AC-12 | the above, offline, in temporary folders | |

**Manual run.** `python app.py scenario <scratch>/ivresp_check.csv 2026-11-10_1540 --sessions 5`, a short Nov-20 750 straddle, through `app.py`. The position file was kept outside the repo and its output folder deleted after.
- Grid dates: now, the Nov 17 close (5.05 sessions, 3.0 days left, IV 19.79% with no response), the Nov 19 close and the Nov 20 expiry.
- At ±1% and ±3% now, priced through `point` and `price_point`, every case matched section 2's table to the dollar.
- Slopes: the delta -1.8 shares under `none`; `moderate` +21.0 either side; `large` +43.9 below spot and +32.5 above.
- No `.work` folder was left behind.

## Open

Questions for the owner, by number:

1. ~~**Up-move rates.**~~ Resolved 2026-11-12: widened to -1 and -1.5, so they sit above the measured rallies (section 2).
2. ~~**IV against the usual way.**~~ Resolved 2026-11-12: no fourth case; the report states it as a limit, and `--shift` asks about it (section 5).
3. ~~**The horizon assumption.**~~ Resolved 2026-11-12: the same rates however many sessions the move took (section 5).

## Notes and decisions

- 2026-11-11: the owner proposed umbrella IV shifts, about three P&Ls per spot move, sized from the recent big moves and narrowed over time, over measuring the response first. Five big-move pairs of snapshots, and 33 years of VIX closes, were read to size them (measurements.md 2026-11-11). The proposal put four decisions; the owner agreed with caveats, which are folded in above:
  - the figures are generous, above the two measured downside rates;
  - which case is bad depends on the position;
  - the expiry scaling is provisional;
  - the horizon is a separate input;
  - VIX is read loosely.

  The agent read the agreement as a yes to decision 1 (sticky strike as the baseline). Two halves had no answer, and are Proposed above: decision 3's (flag or cap the scaling for the shortest expiries) and decision 4's (Greeks under all three cases). Writing the caveats in, the agent found the up-move figures are not above what was measured (question 1).
- 2026-11-12, after the build: the owner left the rally floor as it is, flagged `iv_floor`, since the figures are discretionary and will be adjusted through use. The owner also noted that the measured fixed-strike changes include the engine's own time roll. Priced out read-only, the roll is small at two to five weeks except across the Nov 6-9 weekend (+1.3 at 7-11 days). Net of it, that move follows sqrt(30/days), and the up-move rates at 30 days read -1.01 and -0.75 per 1%, still inside the band. No figure changed (measurements.md 2026-11-11, "Net of the engine's own time roll").
- 2026-11-12: built and verified (evidence above).
  - **Corrected in the build.** `daily` never ran `history`, so section 7's "runs inside `daily`" needed a new `response` step. `grid.csv` also gained `move_pct` and `days_left`.
  - **Found in the manual run: large rallies take IV to the floor.** The response is linear in the move, and the grid runs to ±3 expected moves (±8% on that straddle). The rates were sized on moves of +2.1% and -4.4%. At +5.5% with 10 days left, `large` is -1.5 x 5.5 x 1.73 = -14 vol points against a 16% IV, leaving under 2%. Further out, and with 3 days left, it reaches the floor: 10 of 52 points were flagged `iv_floor`. Not repaired: a cap would be a new rule, and it is the owner's to choose (integrity.md item 6).
  - **A sixth move, read by the new view.** Nov 10-11, +1.47%. The fixed-strike change grew with tenor instead of shrinking: -0.2 at 7 days, -0.58 at 30 days, and +1.2 at 1 day. That is the second of six moves the scaling did not fit. Still inside the band, with `none` on one edge (measurements.md 2026-11-11, addendum).
- 2026-11-12: the owner took the agent's picks on questions 2 and 3 ("Yes, your picks"); state moved to accepted and the build started.
- 2026-11-12: the owner answered question 1 and asked three more things. Each is folded in above:
  - The up-move rates are widened to -1 and -1.5.
  - The `held` case is renamed `none`, so it cannot read as an IV frozen in time.
  - Time passing and the IV on a date stay separate inputs (section 1).
  - Typing an IV directly comes later, as its own change (section 8).

  The owner offered typing the IV in place of widening the rates. The agent kept both. Widening is a constant that keeps the band generous on both sides now, and the owner placed typed IVs "later in development".
- 2026-11-11: checking the expiry scaling on all five moves, not just the two the proposal cited, found the Nov 6-9 move flat across tenors (section 4). That supports the owner's caution, and it is why `tenor` is a flag and not a cap.
