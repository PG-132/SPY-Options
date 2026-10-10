# Measurements behind the code's numbers

Every constant in `screener/collect.py` came from one of these. Each entry says
what produced it, so it can be re-checked rather than trusted.

## Webull API, verified 2026-09-02/03

- `get_option_snapshot` accepts at most **20 contract symbols** per request.
- Its date filters do not work: asking for one expiry returned another, so
  expiries are filtered in our code.
- The contract listing includes adjusted series (e.g. `4SPY260925C00771350`)
  that the quote endpoint then rejects with `INVALID_SYMBOL`, failing the whole
  batch. Only `def_type == STANDARD` survives.
- Webull's theta omits the interest-on-strike term, so their single-leg theta
  disagrees with ours by 15-30%. Their IV runs 0.2-0.35 vol points below ours.
  (That IV gap was measured against the old spot-and-whole-days method. Pricing
  from the parity forward with actual time to expiry closes it to 0.11 points
  or less on every expiry; see below.)
  Hence every vendor number is stored under a `vendor_` prefix, never as truth.
- After 16:00 ET bid/ask go stale while `close` stays the official print.

## Where the market stops quoting, measured 2026-09-24

SPY ~765, 29-day expiry (2026-10-23), at-the-money IV 12.7-13.2%. One expected
move = IV x sqrt(days/365) = about $28.

- **Calls** stop being quoted about **3.1 expected moves** up: 850 was the last
  strike bid >= $0.05, at 14.0% IV.
- **Puts** never stop. The lowest listed strike, 500, is 35% below spot (9.6
  expected moves) and was still bid $0.07. Crash protection always has a buyer,
  so a bid threshold never goes quiet on that side.
- The **1% delta** boundary sits near **6 expected moves** down.

That asymmetry is why the band is 6 moves below spot and 3 above, and why the
edge warning tests delta rather than bid.

## Why 1% delta is the boundary

IV error is price error divided by vega, and vega collapses in the wings. IV
solved at the bid versus at the ask on the same 29-day chain:

| Strike | Delta | Bid x Ask | IV span | Vega/contract |
|---|---|---|---|---|
| 740 put | 22 | 4.45 x 4.48 | 0.0 pts | $63 |
| 700 put | 7.0 | 1.45 x 1.47 | 0.1 | $28 |
| 660 put | 2.9 | 0.69 x 0.70 | 0.1 | $14 |
| 600 put | 1.1 | 0.30 x 0.31 | 0.2 | $6.0 |
| 550 put | 0.5 | 0.16 x 0.17 | 0.3 | $3.1 |
| 500 put | 0.2 | 0.08 x 0.09 | 0.6 | $1.6 |
| 845 call | 0.7 | 0.05 x 0.06 | 0.3 | $3.6 |
| 870 call | 0.3 | 0.01 x 0.02 | 0.9 | $1.1 |

Past roughly 1 delta, the bid-ask alone moves the solved IV by more than the
differences we would be trying to measure.

## Calendar time lies about the term structure

From the 2026-09-24 snapshot, at-the-money IV as quoted (annualized over
calendar days) versus per trading session:

| Expiry | Cal days | Sessions | As quoted | Per session |
|---|---|---|---|---|
| Sep 25 | 1 | 1 | 13.83% | 11.49% |
| Sep 28 | 4 | 2 | **10.33%** | 12.14% |
| Oct 2 | 8 | 6 | 12.70% | 12.18% |
| Oct 5 | 11 | 7 | **11.88%** | 12.37% |
| Oct 23 | 29 | 21 | 13.15% | 12.84% |

Both apparent bargains are Mondays: a weekend adds calendar days with no
trading. Rank expiries in session time, never as quoted.

## VIX is not the at-the-money, and the gap is the skew

VIX is a variance-swap rate over out-of-the-money strikes weighted 1/K^2, so
it sits above the at-the-money by an amount that grows with the skew. From the
2026-09-24 snapshot:

- at-the-money (29d): **12.92%**
- a VIX-style variance swap rebuilt from our own recorded strikes: **15.44%**
- real VIX at the same minute (11:42 ET): **16.29%**

Ours sits 0.85 under CBOE's because our band truncates at ~1 delta (CBOE runs
the tail to two zero bids), SPY is not SPX, and 29 is not 30 days.

**Timing dominates the ratio.** At the same minute the ratio is 0.793; against
that day's VIX close it is 0.834; the 2026-08-24 straddle entry gives 0.808 on
closes. Never compare a snapshot IV against a VIX close. Use roughly 0.8 x VIX
as a working rule until the snapshot series replaces it.

## Free history, no option chains required

Verified 2026-09-24 via yfinance: `^VIX` 1990-> (1-minute bars intraday),
`^SKEW` 1990-> (daily only), `^VIX9D` 2011->, `^VIX3M` 2006->, `^VVIX` 2007->.
So level, term slope and tail all have published daily history. Strike-level
history does not exist for us; our own record starts with the first snapshot.

On 2026-09-24: VIX 15.48 was the 35th percentile since 1990 (27th over 5
years); SKEW 146.15 was the 94th (69th over 5 years).

Matching history on shape rather than level is possible but weak: of days with
VIX 14.5-16.5 and SKEW above 141, realized vol over the next 21 sessions came
in under VIX 91% of the time, against 84% for all days. That sample is 228
overlapping days, about 11 independent months, and SKEW above 141 only occurs
from 2014 on. Treat it as description, not prediction.

## Known trap: put-call parity by regression

Regressing call minus put against strike to recover both the discount factor
and the forward returned an implied rate of **-25%** on the 29-day chain. The
forward was fine (766.24 against 766.18 from theory), but American puts carry
an early-exercise premium that bends the line on the in-the-money side. Fix the
rate from a T-bill and back the forward out of the at-the-money pair instead.

## Whole days lie about short-dated options (2026-09-24)

Time to expiry counted in whole days, against actual hours to the 16:00 close,
on the snapshot taken at 11:42 ET. At-the-money IV each way, with Webull's for
comparison:

| Expiry | Whole days | Actual | ATM whole | ATM actual | Webull |
| --- | --- | --- | --- | --- | --- |
| Sep 25 | 1 | 1.18 | 15.17% | 13.97% | 13.86% |
| Oct 2 | 8 | 8.18 | 12.82% | 12.68% | 12.70% |
| Oct 23 | 29 | 29.18 | 13.13% | 13.09% | 13.15% |

Rounding a day away costs 1.3 vol points at one day to expiry and 0.04 at
twenty-nine, because IV scales with the inverse root of time. `vol.py` counts
actual time; `dte` survives only as a label.

With that fixed, and the forward taken from parity, our IVs land within 0.11
points of Webull's on every expiry, and within 0.05 on nine of thirteen. Two
independent implementations agreeing that closely is the strongest check we
have that neither is quietly wrong.

## Where the forward comes from (2026-10-10, on the 2026-09-24 chain)

Put-call parity gives a forward at every strike quoted on both sides. They
should all agree. Across the 0.35-0.65 delta band they do not, and the
disagreement grows with maturity:

| Expiry | DTE | Pairs | Spread, all pairs | Spread, 6 tightest | Forward's error, vol pts |
| --- | --- | --- | --- | --- | --- |
| 2026-09-29 | 5 | 7 | 1.3c | 1.3c | 0.017 |
| 2026-10-07 | 13 | 14 | 11.9c | 4.2c | 0.037 |
| 2026-10-08 | 14 | 3 | 9.6c | 30.9c | 0.261 |
| 2026-10-09 | 15 | 15 | 18.7c | 8.0c | 0.063 |
| 2026-10-16 | 22 | 19 | 24.9c | 8.7c | 0.058 |
| 2026-10-23 | 29 | 22 | 30.8c | 12.0c | 0.066 |

That 31 cents is not quote noise. Three things identify it:

- **It is a slope, not scatter.** Across the 29-day band F(K) falls
  monotonically with strike, one sign flip about the mean in 21 steps, slope
  -0.0147 per dollar. The same signature that failed the cubic smile.
- **It tracks width asymmetry.** Correlation between a pair's deviation and
  its call spread minus put spread is +0.93 on the four longest expiries, at
  roughly 0.9 of a cent per cent of asymmetry. The mid of a wide
  in-the-money quote is not its fair value, and how deep a leg sits runs
  monotonically with strike, which is why the error arrives tilted.
- **Timing is not the cause.** All 22 pairs were quoted between 11:43:43 and
  11:43:45, and SPY moved three cents across them. Subtracting each pair's own
  spot makes the spread slightly worse, 33.8c against 30.8c.

Averaging cures noise and does nothing for a bias. What cures a bias is
reading it where it vanishes, which is where the two legs are quoted the same
width. So `vol.forward()` gates on asymmetry first - `|C width - P width|`
within 0.05 - and only then averages the tightest survivors, weighted
1/width^2 against the noise that is left. Selection handles the bias, weighting
handles the noise.

Two measurements decided that shape rather than the obvious alternatives:

- **Weighting on asymmetry instead of gating on it** barely differs, because
  once the gate is applied the survivors all sit within 0.04 of even on twelve
  of thirteen expiries. The two weightings disagree by at most 1.5 cents.
- **Regressing the bias out** - fit F against signed asymmetry across all
  pairs, take the intercept at zero - was tried and rejected. The fitted slope
  came out 0.11, 0.16, 0.17, 0.20, 0.22, 0.24, 0.32, 0.41, 0.50, 0.90, 1.45,
  1.93 across the thirteen expiries. A 17x range in one quoting behaviour on
  one afternoon is not a model. The short expiries are the unstable ones: their
  quotes are all 0.01-0.03 wide, so the slope is fitted over a tiny x-range and
  then extrapolated to zero, dragging their forwards 5-6 cents.

Against the old single-pair rule the forward moves by under two cents on every
expiry, so that rule was not wrong, just unprotected: it picked one of 22
disagreeing readings by a criterion unrelated to reliability, and reported no
uncertainty.

`forward_error` is the wider of what the used pairs disagree by and half the
tightest pair's combined spread, in forward terms. The second term matters
because one pair cannot disagree with itself and that is not certainty.
`forward_iv_cost` converts the error to vol points at the strike nearest the
money: ten cents of forward is about 0.06 vol points at 29 days.

| Expiry | DTE | Eligible pairs | Used | Forward error | Vol pts | vs median band |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-29 | 5 | 24 | 6 | 1.5c | 0.020 | 0.16x |
| 2026-10-07 | 13 | 7 | 6 | 6.0c | 0.052 | 0.60x |
| 2026-10-08 | 14 | 1 | 1 | 7.0c | 0.059 | 0.69x |
| 2026-10-09 | 15 | 7 | 6 | 8.0c | 0.063 | 0.94x |
| 2026-10-16 | 22 | 7 | 6 | 8.7c | 0.058 | 1.21x |
| 2026-10-23 | 29 | 9 | 6 | 11.6c | 0.066 | 1.17x |

**2026-10-08 is the instructive case.** Exactly one pair passes the gate,
because the expiry is quoted on a $5 strike grid - 26 strikes, every gap
exactly 5.00 - where 2026-10-07 has a $1 grid with 105. Checked against the
raw chain: this is what the exchange listed, not something the collector
dropped. $5 of strike is far enough that the next pair out is already five
times more asymmetric, so there is nowhere near the money to read a second
clean forward from. Ranking by width instead of gating gave that expiry a
30.9-cent error bar and pulled its forward two cents off the clean reading;
the gate returns the clean reading and an error bar of 7.0 cents from that
pair's own quote noise.

The prediction that follows: $1 strikes get listed as a weekly approaches, so
this expiry's grid should densify and its forward error should fall day over
day. Worth checking against the next snapshots, as a test of whether the
quality number means what it claims.

Note that on the two longest expiries the forward's error already exceeds the
median quote band, at 1.21x and 1.17x. The forward is the largest error there,
not the spreads, and `vol.py` warns when that happens.

## Two smile shapes that failed, and the test that caught them (2026-09-24)

Residuals from a good fit scatter, so their signs flip about half the time
along the smile. Long same-sign runs mean the shape is wrong. On the 29-day
expiry, 133 points:

| Shape | RMS, vol points | Worst residual | Sign flips |
| --- | --- | --- | --- |
| cubic in ln(K/F) | 0.407 | 2.04 | 5 |
| SVI | 0.081 | 0.28 | 7 |
| hyperbola + quadratic + cubic, in IV | 0.023 | 0.10 | 26 |

**The cubic** cannot be a smile. A real one has straight wings and a rounded
belly; a polynomial that matches the belly undershoots both wings, which is
exactly what the residuals showed: +2.04 at the 595 put, -0.30 through the
shoulders, +1.21 at the 835 call. It reported 460 of 978 tradeable points as
sellable above the curve, all of it artifact.

**SVI** fails, though not for the reason first recorded here. That note said
the right wing never turns up in total variance, implying rho = -1.035 and
forcing the fit to the boundary. It came from regressing the whole call side at
once, which averages the falling belly with the rising wing: 63 points from
k = 0 out slope -0.0036, and a negative right slope is illegal.

Re-measured 2026-10-07, the wing does turn, at k = 0.0455, or 1.24 expected
moves, inside a band that reaches 2.67. Past the turn the right wing slopes
+0.0087 against the left wing's -0.0437, giving rho = -0.67 and b = 0.026,
comfortably legal. The chain admits an SVI fit; rho = +1.00 with b = 98 was a
fitting failure, most likely Nelder-Mead on all five parameters from one start.
That code is gone, so the cause is not settled - only that the window was never
the problem.

**What works** is SVI's idea applied to IV instead of total variance, with
quadratic and cubic terms for the belly: iv = c0 + c1*d + c2*sqrt(d^2+s^2) +
c3*d^2 + c4*d^3 around d = k - m. Only m and s are searched; the five
coefficients are exact least squares, weighted 1/band^2.

That linearity is also why it fits where SVI did not: no five-way search to
get lost in.

The stopping rule is the measurement floor, not the RMS alone: median IV bands
on these expiries run 0.048-0.097 vol points, and the fit's RMS is 0.013-0.034,
so it already sits inside the noise of the quotes it is fitting. More
flexibility past that is fitting the spread.

Sign flips land at 12-40 of about 130 rather than the ~65 pure scatter would
give. That residue looks inherent: market makers quote from their own smooth
model, so neighbouring quotes are correlated by construction.

**What the working fit finds:** 40 of 978 tradeable points clear their own
spread to sell and 52 to buy, the largest edge being 0.08 vol points on a
contract whose own band is 0.20. In SPY, nothing is loose. The surface earns
its keep as a reference and a data check, not as a source of free money.
