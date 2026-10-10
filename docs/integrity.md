# Data integrity: what could be wrong, and how we would know

Nothing here forecasts, but almost everything is derived, and a derivation can
be wrong in ways that look like data. Three have been caught this way so far:
whole-day time counting put the 1-DTE expiry 1.3 vol points off, a cubic smile
fit reported 460 tradeable edges that did not exist, and a wing slope measured
across the belly blamed SVI's failure on our strike window when the window was
fine.

This is the running list. Add to it when a new assumption gets built on, and
strike items off when they are checked rather than when they feel fine.



### 1. The forward's error bar is not carried into each point

Fixed as far as the forward itself goes (see Handled), but only half the job.
`expiries.csv` now records `forward_error` and `forward_iv_cost`, and on
2026-10-16 and 2026-10-23 that cost is 1.2x the median quote band: the forward
is the largest error in those expiries, not the spreads. Yet each contract's
`iv_band` still reflects only its own bid and ask, so every point on those two
expiries carries an error bar that is too small, and `surface.py` weights by
1/band^2 and reads edges against it.

*Fix:* widen each point's band by its expiry's `forward_iv_cost`, or carry the
two separately so the fit can weight on quote noise while the edge test is
judged against both. Decide which before trusting an edge on a long expiry.

### 2. The rate is 4% flat and unverified 

`vol.CONFIG["rate"]`. It has never been checked against an actual short rate.
A 1% error moves a 30-day forward by about six cents, which is inside the
forward's own measured error bar on the long expiries, so this matters less
than it looks. It is still an untested input.
(as of market close on october 2, 2026 tbill yields ~4-4.5%)


*Fix:* read `^IRX` at snapshot time and record it alongside the quotes, so
history re-derives under whatever rate actually applied that day.

### 3. The holiday table is hand-typed, and half-days are missing 

`vol.HOLIDAYS` was typed from memory, not imported. Worse, early closes are
not modelled at all: the Friday after Thanksgiving and Christmas Eve trade a
half session and right now are counted as whole.

session counts, which drive every per-session IV and so every
comparison between expiries. Dormant until late November, then real.

*How we would know:* a day the whole chain prices as cheap per session, with
no event to explain it, sitting next to a known holiday.

### 4. European math on American options 

`pricing.bs` is European. SPY options are American. Reading only the
out-of-the-money side avoids the worst of it, since early exercise is a
deep-in-the-money phenomenon, but the exposure is not zero.

*How we would know:* bound it. Price a few of our actual strikes under a
binomial tree and compare. If the gap is inside the IV band, stop worrying.

### 5. Webull is not an independent check 

Our IVs agreeing with theirs to 0.11 points is reassuring but not proof: a
shared convention error would agree with itself. The genuinely independent
checks are put-call parity, the frozen reference cases, and the fit's RMS
against the measured bands.

## Handled, and why

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
