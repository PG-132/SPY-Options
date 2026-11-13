# Data integrity: what could be wrong, and how we would know

Nothing here forecasts, but almost everything is derived, and a derivation can
be wrong in ways that look like data. Three have been caught this way so far:
whole-day time counting put the 1-DTE expiry 1.3 vol points off, a cubic smile
fit reported 460 tradeable edges that did not exist, and a wing slope measured
across the belly blamed SVI's failure on our strike window when the window was
fine.

This is the running list. Add to it when a new assumption gets built on, and
strike items off when they are checked rather than when they feel fine.



### 1. ~~The holiday table is hand-typed, and half-days are missing~~

Handled; see "Handled, and why" below. The number is kept so references to
items 2-4 stay valid.

### 2. European math on American options 

`pricing.bs` is European. SPY options are American. Reading only the
out-of-the-money side avoids the worst of it, since early exercise is a
deep-in-the-money phenomenon, but the exposure is not zero.

*How we would know:* bound it. Price a few of our actual strikes under a
binomial tree and compare. If the gap is inside the IV band, stop worrying.

The scenario engine (2026-11-09) makes this matter more: its what-ifs push
legs deep in the money, so it flags any leg past 0.9 delta, a placeholder
until this is bounded. It also shows the in-the-money side directly. Priced
at the strike's out-of-the-money IV, an in-the-money leg sits below its own
mid by a median of 11 cents a share, and by $2-4 deep in the money, on the
2026-11-04 chain. That gap mixes wide quotes with any early-exercise premium,
and nothing yet separates the two.

### 3. Webull is not an independent check 

Our IVs agreeing with theirs to 0.11 points is reassuring but not proof: a
shared convention error would agree with itself. The genuinely independent
checks are put-call parity, the frozen reference cases, and the fit's RMS
against the measured bands.

### 4. The fitted shape is untested outside a calm market

Every constant here was set on one chain, 2026-09-24, with ATM IV at 13%.
Widening its spreads shows the machinery degrades honestly, but that cannot
test the shape, because widening leaves every mid untouched. The basis already
fits 11.00% to 39.17% within one expiry, so dynamic range is not the worry. A
selloff is: the at-the-money level rises and the put skew tends to flatten
against it, which is a different curve rather than a scaled one.

*How we would know:* capture a chain with VIX materially higher and re-run the
residual sign-flip test. Flips near half the point count mean the basis still
fits; long same-sign runs mean it does not, the way the cubic was caught.

*First reading, 2026-11-05 (Observed, one chain).* `2026-11-05_1633`, taken
after the close from the 16:13-16:15 options-close quotes, on a 4.41% SPY drop
with VIX closing at 28.18 (16.61 the day before). Sign changes per fitted point
held at 0.32-0.52 out to 11-11, then fell to 0.05-0.16 from 11-12 to 12-11:
long same-sign runs, which by the test above mean the basis does not fit
those expiries. The exceptions are the three thinly listed expiries 11-17 to
11-19 (0.37-0.53), whose strikes stop at 680-690. On 11-04, at VIX 16.6, the
expiries out to 11-16 flipped 0.43-0.71. The RMS stayed inside the quote band
(0.09-0.12 vol points against median bands of 0.27-0.31 from 11-20 out), so
the misfit is systematic but small against the quotes. Not settled: one chain,
closing quotes rather than intraday ones, and the 11-04 chain already flipped
only 0.10-0.29 from 11-20 out. Repeat on an intraday chain while VIX stays
high.

### 5. Which delta hedges SPY: fixed-IV, or the scenario grid's slope

The scenario engine prints Black-Scholes delta at a fixed IV, and beside it
the slope of its own grid, which also moves each leg's IV along the fitted
smile as spot moves. On `2026-11-09_1421`'s Nov-13 750 straddle they read
+15.90 and +32.99 shares. Each is right about its own question. Inside the
what-if, the slope is the hedge that cancels first-order P&L. Against SPY,
the better hedge is whichever matches how SPY's IVs really move with spot,
at the interval the hedge is rebalanced, and that is not known. Hull and
White (2017, "Optimal delta hedging for options") found S&P 500 fixed-strike
IVs tending to fall as the index rose, the opposite of the sliding smile's
assumption. That is a reason to test the slope, not evidence about this
position, period or rebalancing interval. The fixed-IV delta did match
Webull's API delta on the same snapshot (straddle 15.49 shares against 15.90,
median gap 0.0011 across 1,824 out-of-the-money contracts); that is the API
field, not necessarily the app's display.

*How we would know:* first from the snapshots already held: between
consecutive chains, regress each fixed strike's IV change on SPY's change,
and set the result beside the sliding smile's prediction (`-slope/S`, +0.275
vol points per $1 on that straddle) and sticky strike's zero. Then the hedge
itself, at the owner's rebalancing interval: hedge with each delta on paper
trades or going forward, and compare the variance of the hedged P&L. Both
need many observations before they say anything.

*First reading, 2026-11-11 (Observed, five moves).* On the five largest moves
between consecutive snapshots (Oct 29-30 to Nov 6-9, -4.43% to +2.08%), the
strike nearest the old spot moved the opposite way to the slide's prediction
every time: +2.9 at 29 days where the slide said -2.5 on the Nov 5 drop, -1.7
at 30 days where it said +1.4 on the Nov 4 rally (measurements.md
2026-11-11). Five moves, three of them around an election, are not a
regression, but they are consistent with Hull and White's sign and not with
the slide's. Since 2026-11-12 the engine holds each strike's IV fixed and
shows a band of IV responses on top of it
([changes/2026-11-11-iv-response.md](changes/2026-11-11-iv-response.md)). The
grid's slope under `none` is the fixed-IV delta, and under the other two
cases the delta plus vega times the response's own slope, different below
and above spot. The hedge comparison above still stands, now between
those.

### 6. The IV response band is sized from five moves

The band's rates (+1 and +2 vol points per 1% of SPY on down moves,
-1 and -1.5 on up moves since 2026-11-12, at 30 days) are the owner's
umbrella choice, not a fit. Three things under them are thin. The rates rest on two down moves and
two up moves at a fixed strike, plus VIX history read loosely. The
sqrt(30/days) scaling across expiries held on four of those moves between 7
and 36 days, not on the fifth, and missed both ways under 7 days. And taking
the same rates however many sessions a move took is an assumption: VIX says
it is near right out to a week and generous after. None of it covers IV
moving against the usual way, which VIX did on 3-6% of one-session moves of
1.5% or more and up to 22% over a month.

Two more since it was built (2026-11-12):
- **The scaling.** A sixth move, Nov 10-11 (+1.47%), read by the new
  `history` view, did not follow it: the change grew with tenor instead of
  shrinking. The owner then pointed out that every reading is the total
  change at a fixed strike, which includes the engine's own time roll.
  Priced out, the roll is within 0.2 of zero at two to five weeks on every
  move but Nov 6-9. That one spans a weekend, and the roll alone would have
  raised IV about 1.3 points at 7-11 days. Net of it, Nov 6-9 follows the
  scaling within about 20%, so one move of six misses, not two
  (measurements.md 2026-11-11, "Net of the engine's own time roll").
  `history`'s view still reports the total change.
- **Large rallies.** The response is linear in the move, and the grid runs
  to three expected moves, past the +2.1% and -4.4% the rates were sized on.
  On `2026-11-10_1540`'s Nov-20 750 straddle, `large` at +5.5% with 10 days
  left is -14 vol points against a 16% IV, leaving under 2%; further out, and
  with 3 days left, it reaches the floor: 10 of 52 points flagged
  `iv_floor`. That is a number the measurements never reached. The owner
  left it as it is (2026-11-12): the figures are discretionary, and the
  flag marks those points while the engine's use shows what to change.

*How we would know:* read every new pair of snapshots the same way (the
`response` step of `daily` now does it, into `data/history/response.csv`),
and set
each move's fixed-strike change, by expiry from one to five weeks, beside the
band. A move outside the band on the side that hurts a position is the
event that resizes it. Record each reading in measurements.md.

## Handled, and why

- **The holiday table, and half-days.** Was item 1: `vol.HOLIDAYS` typed from
  memory and early closes counted as whole sessions. Half-days have been
  modelled since 2026-10-30 (`vol.HALF_DAYS`, weight 0.5, measured on 33
  day-after-Thanksgiving sessions; see docs/measurements.md). On 2026-11-04
  both tables were checked against NYSE Group's published 2026-2028 calendar
  (release of 2025-12-23) and match it exactly for 2026 and 2027. What is
  left: the tables end at 2027 and must be extended by hand, the 0.5 weight
  is applied to Christmas Eve unmeasured, and pricing time still ends at
  16:00 on a 1pm-close expiry (A-003 and A-006 in docs/assumptions.md).
- **Spot and option quotes are not simultaneous.** A pass takes about 90
  seconds and SPY drifts through it. Each contract is matched to the SPY price
  nearest its own quote time, and whatever mismatch remains lands in the
  parity forward rather than tilting each strike. This is what the Sep-25
  straddle log got wrong, where it showed up as calls and puts disagreeing by
  up to 4 vol points.
- **Time to expiry.** Counted in actual hours to the 16:00 close, not whole
  days. See docs/measurements.md.
- **Junk quotes shaping the surface.** Only readable points are fitted, and
  weights are 1/band^2, so a penny-wide wing cannot drag a curve that a tight
  at-the-money quote defines.
- **The fit's shape.** Residual sign flips are recorded per expiry. A good fit
  scatters; long same-sign runs mean the shape is wrong, which is how both
  rejected fits were caught.
- **The forward resting on one strike pair.** It used to come from the single
  strike where call and put mids were closest. Checking every pair in the
  0.35-0.65 delta band showed they disagree by up to 31 cents on the 29-day
  expiry, and the disagreement is a slope in strike, not scatter: one sign flip
  in 21. It tracks the pair's width asymmetry at +0.93, so the cause is the mid
  of a wide in-the-money quote not being its fair value. Timing was ruled out -
  those pairs were quoted inside two seconds and SPY moved three cents.
  Averaging cannot cure a bias, so `vol.forward()` gates pairs on asymmetry
  within 0.05 and only then averages the tightest survivors, weighted
  1/width^2 against the noise that is left. Regressing the bias out was tried
  and rejected: the fitted slope ranged 0.11 to 1.93 across one chain's
  expiries. See docs/measurements.md.
- **The forward's error reaching each point.** Its error bar is now carried
  into every edge reading, as `forward_cost` per point. It is measured against
  a refit at the shifted forward rather than assumed, because a forward error
  moves the whole expiry together and the curve follows: about 70% cancels out
  of a residual, so each point's raw IV sensitivity overstates it threefold.
  An edge now has to clear its spread AND outlast this. On the Sep-24 chain
  that took 88 spread-clearing edges down to 34.

- **The rate being 4% flat.** Checked 2026-10-18 against ^IRX, now cached
  back to 1960. On our four snapshot dates the 13-week bill read 4.050% to
  4.088%, so the assumption is 5 to 9 basis points low. At roughly six cents
  of forward per 1% of rate that is about half a cent, well inside the
  forward's own error bar of 1 to 11 cents. The item's prescribed fix was to
  record the rate at snapshot time; caching the whole series is better, since
  any past snapshot can be re-derived by date without a column on every row.

## Standing rules

- The fitted curve is only ever evaluated between the strikes it was fitted
  on. It is a reference shape, not a model for pricing what we did not see.
- Raw snapshots are never modified. Every derived number must be reproducible
  from them, so a fixed assumption re-derives the whole history.
- A wing slope is measured past the turn in total variance, never across a
  whole side. Averaging the falling belly with the rising wing gives the wrong
  sign.
- A number without an error bar is not a result. Points carry their IV band;
  anything built on top of them needs the equivalent.
- Before averaging several readings of the same quantity, check whether they
  scatter or slope. A slope means a bias, and averaging a bias just picks a
  point on it. This is what the per-pair forwards turned out to be doing.
- An error that moves a whole expiry at once is not the same size in a level
  as it is in a deviation from the fitted curve. Measure which one a reading
  depends on before widening its band.
