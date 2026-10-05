# Data integrity: what could be wrong, and how we would know

Nothing here forecasts, but almost everything is derived, and a derivation can
be wrong in ways that look like data. Two have already been caught this way:
whole-day time counting put the 1-DTE expiry 1.3 vol points off, and a cubic
smile fit reported 460 tradeable edges that did not exist.

This is the running list. Add to it when a new assumption gets built on, and
strike items off when they are checked rather than when they feel fine.



### 1. The forward rests on one strike pair

`vol.forward()` picks the single strike where call and put mids are closest and
takes the forward from that pair. One stale or crossed quote at that strike
moves the forward for the whole expiry, and every IV solved against it.

so compare the forward implied by each near-the-money pair
(say 0.35 to 0.65 delta). They should agree within a cent or two. A spread
wider than that means one pair is dragging the result.

*Fix when we get to it:* works for now in the building stages but take the forward 
from a weighted fit across those pairs rather than one, and record the disagreement 
as a quality number per expiry.

### 2. The rate is 4% flat and unverified 

`vol.CONFIG["rate"]`. It has never been checked against an actual short rate.
A 1% error moves a 30-day forward by about six cents, so this matters less
than the item above, but it is an untested input.
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

## Standing rules

- The fitted curve is only ever evaluated between the strikes it was fitted
  on. It is a reference shape, not a model for pricing what we did not see.
- Raw snapshots are never modified. Every derived number must be reproducible
  from them, so a fixed assumption re-derives the whole history.
- A number without an error bar is not a result. Points carry their IV band;
  anything built on top of them needs the equivalent.
