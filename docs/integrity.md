# Data integrity: what could be wrong, and how we would know

Nothing here forecasts, but almost everything is derived, and a derivation can
be wrong in ways that look like data. Three have been caught this way so far:
whole-day time counting put the 1-DTE expiry 1.3 vol points off, a cubic smile
fit reported 460 tradeable edges that did not exist, and a wing slope measured
across the belly blamed SVI's failure on our strike window when the window was
fine.

This is the running list. Add to it when a new assumption gets built on, and
strike items off when they are checked rather than when they feel fine.



### 1. The holiday table is hand-typed, and half-days are missing 

`vol.HOLIDAYS` was typed from memory, not imported. Worse, early closes are
not modelled at all: the Friday after Thanksgiving and Christmas Eve trade a
half session and right now are counted as whole.

session counts, which drive every per-session IV and so every
comparison between expiries. Dormant until late November, then real.

*How we would know:* a day the whole chain prices as cheap per session, with
no event to explain it, sitting next to a known holiday.

### 2. European math on American options 

`pricing.bs` is European. SPY options are American. Reading only the
out-of-the-money side avoids the worst of it, since early exercise is a
deep-in-the-money phenomenon, but the exposure is not zero.

*How we would know:* bound it. Price a few of our actual strikes under a
binomial tree and compare. If the gap is inside the IV band, stop worrying.

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
