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

**SVI** fails for a subtler reason, and it is our window's fault rather than
the model's. SVI requires both wings to rise in total variance. Read straight
off this chain, the left wing slopes -0.0429 per unit k and the right slopes
-0.0007, still falling, which implies rho = -1.035, outside SVI's legal range
of +/-1. The fit pinned rho at the boundary and threw b to 98. The call side
turns up further out than 3 expected moves, where our band stops.

**What works** is SVI's idea applied to IV instead of total variance, with
quadratic and cubic terms for the belly: iv = c0 + c1*d + c2*sqrt(d^2+s^2) +
c3*d^2 + c4*d^3 around d = k - m. Only m and s are searched; the five
coefficients are exact least squares, weighted 1/band^2.

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
