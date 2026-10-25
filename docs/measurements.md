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

That produced a prediction, which was tested on 2026-10-13 and came back
split. See below.

Note that on the two longest expiries the forward's error already exceeds the
median quote band, at 1.21x and 1.17x. The forward is the largest error there,
not the spreads, and `vol.py` warns when that happens.

## What a wrong forward costs a residual (2026-10-11)

The forward now carries an error bar, so the question is what that error is
worth to the thing surface.py actually reports: a point's deviation from the
fitted curve. The answer is much less than its effect on the IV level, because
a forward error is not noise on one strike. It moves every IV in the expiry
together AND drags the log-moneyness axis with it, so the fitted curve follows
and most of the error cancels.

Measured by shifting each expiry's forward by its own error bar, re-solving
every IV and refitting:

| Expiry | Forward error | Median move in IV | Median move in residual | Cancelled |
| --- | --- | --- | --- | --- |
| 2026-09-29 | 1.5c | 0.008 | 0.002 | 75% |
| 2026-10-07 | 6.0c | 0.023 | 0.005 | 78% |
| 2026-10-09 | 8.0c | 0.029 | 0.010 | 66% |
| 2026-10-16 | 8.7c | 0.027 | 0.008 | 70% |
| 2026-10-23 | 11.6c | 0.034 | 0.010 | 71% |

So widening each point's band by its raw IV sensitivity would be about three
times too harsh, and would have deleted every edge in the snapshot.

What survives still matters, because it is the same size as the deviations
being hunted. Shifting every forward by its error bar flips 139 of 1,246
points' clears-its-spread verdict, concentrated on the long expiries: 35 of
132 on 2026-10-16, 32 of 135 on 2026-10-23, 23 of 120 on 2026-10-09. The
largest edge anywhere in the snapshot is 0.08 vol points, so a 0.010 shift is
an eighth of the biggest thing we ever find.

And it is nowhere near uniform within an expiry. On the 29-day the per-point
residual sensitivity runs from 0.000 to 0.093 vol points, a hundredfold
spread, so a single number per expiry would be too harsh for most points and
too lenient for the few that matter.

That rules out both shortcuts, so it is measured per point instead:
`vol.py` solves each mid at the forward plus and minus its error bar,
`surface.py` refits the smile on each of those readings against its own
shifted axis, and `forward_cost` is how far that point's residual moved. An
edge counts only when it clears its spread and outlasts this.

On the Sep-24 chain the effect is large: 88 points cleared their spread, and
34 of those also clear the forward. The 54 that die include a +0.03 edge on
the 2026-10-06 801 call against a 0.07 forward cost.

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
## What happens when spreads widen (2026-10-11)

Every constant in this repo was set on one chain, 2026-09-24, with ATM IV at
13% and most of the book quoted a penny wide. So: keep every mid, multiply
every spread, and see what gives.

| Spreads | Readable points | Cut by band | Median band | Edges found |
| --- | --- | --- | --- | --- |
| 1x | 992 | 45 | 0.069 | 34 |
| 2x | 959 | 242 | 0.132 | 12 |
| 3x | 945 | 302 | 0.200 | 0 |
| 5x | 748 | 499 | 0.301 | 0 |
| 8x | 389 | 858 | 0.400 | 0 |

**At 3x the screener finds nothing.** Not few, none, and 3x is a modest
stress. It is not the gates giving way: readable points only fall from 992 to
945. It is structural. `edge_at_bid` is the IV at the BID minus the curve, so
widening a quote pushes the bid IV down and the ask IV up directly, and a
deviation has to beat the half-spread. At 3x not one deviation in 1,247
contracts does.

Zero is the correct answer, which is the uncomfortable part. The edge test
asks whether a mispricing is bigger than the cost of taking it, and in a wide
market it genuinely is not. The deviations here are 0.02 to 0.08 vol points
and they are only visible when crossing is cheap, which is only true when
nothing is happening.

(The `cut:vega` column is not shown because it is an artifact of ordering:
`readable()` tests band before vega, so a point failing both is counted
against band. The vega gate does not loosen as spreads widen.)

**The fitted shape is not the fragile part.** A whole-number move in vol is a
smaller stretch than the basis already handles across strikes:

| Expiry | Lowest IV | ATM | Highest IV | Range |
| --- | --- | --- | --- | --- |
| 2026-09-28 | 9.50% | 10.38% | 29.10% | 3.06x |
| 2026-10-09 | 10.73% | 12.58% | 35.78% | 3.33x |
| 2026-10-23 | 11.00% | 13.05% | 39.17% | 3.56x |

One curve on the 29-day expiry spans 11.00% to 39.17% at an RMS of 0.023 vol
points. What this does NOT test is whether the shape changes character under
stress - in a selloff the at-the-money level rises and the put skew tends to
flatten against it, which is a different curve rather than a scaled one. A
quiet Thursday cannot answer that. Only a captured stressed chain can.

**What it did surface.** The asymmetry gate is a cliff. At 3x spreads the
2026-10-05 pairs sit at 0.030, 0.060, 0.060, 0.060 and 0.090, so a gate at
0.05 keeps one of five comparable readings. When nothing passes the gate the
bias is the dominant error, so `vol.forward()` now weights 1/(asymmetry^2)
over all the pairs instead of taking the single evenest. That keeps six pairs
where it used to keep one, while still giving the best pair 92% of the vote on
2026-10-08, where the runner-up really is five times worse.

## What a second snapshot found (2026-10-12)

First chain since 2026-09-24. Columbus Day, so equities trade but the bond
market is shut and the session is thin. SPY 777.51 against 763.66, and vol
lower across the board: ATM runs 9.09% to 12.06% where Sep-24 ran 10.38% to
13.95%.

The pipeline reproduces. RMS 0.019 to 0.030 vol points against Sep-24's 0.013
to 0.034, sign flips healthy, agreement with Webull 0.00 to 0.13 and under
0.04 on nine of twelve expiries. The forward held up better than on Sep-24:
error 1.0 to 10.0 cents against 1.5 to 11.6, and no expiry where the forward
outgrew the median quote band, where Sep-24 had two at 1.2x.

**The point of a thin day was to exercise the two liquidity gates that had
never rejected anything. Neither fired, for two different reasons.**

`min_volume` could not fire at all. Webull never sends a volume of zero: it
sends the field blank. Across both chains there are 259 blanks in the solved
contracts and not one contract reporting zero. `tradeable()` read blank as
unknown, the same as it reads open interest, so the gate was unable to reject
anything ever.

Blank means untraded, and the raw chain says so unambiguously. On 2026-10-12,
`deal_amount` is populated on 1,554 of 1,554 contracts that report a volume
and on 0 of the 632 that do not. Those blanks have median open interest 1
against 454, median spread $2.62 against $0.01, and median |delta| 0.969 -
deep in the money, barely held, nobody trading them.

Reading blank as zero takes tradeable from 979 to 909 on 2026-09-24 and from
749 to 721 on 2026-10-12. It removes three edges from each snapshot, and one
of them was the single largest edge on the Sep-24 chain: the 2026-10-09 811
call, +0.08 vol points, on a contract that did not trade that day.

Open interest keeps the opposite reading. Its blanks are newly listed
expiries, and it does report a genuine zero when it means one - 26 of them on
2026-10-12.

`max_quote_age_min` has still never fired, but harmlessly. Sep-24 had no quote
older than 5 minutes; 2026-10-12 had 10, and all 10 had already failed the
readable gate on band width or vega. Stale quotes are wide quotes, so the band
catches them first. The age gate is cheap insurance, not a protection that has
yet done anything.

## The time axis, and a prediction half-confirmed (2026-10-13)

An expiry's ATM IV averages over every session left in its window, which on
this chain hides a great deal. The 24-day ATM reads 12.22%; the sessions
inside it are priced from 8.84% to 13.87%.

Stripping variance between adjacent expiries, on the session clock:

| Window | Sessions | Forward vol | Error |
| --- | --- | --- | --- |
| 10-14 to 10-15 | 1 | 9.22% | 0.06 |
| 10-16 to 10-19 | 1 | 9.52% | 0.23 |
| 10-19 to 10-20 | 1 | 8.76% | 0.26 |
| 10-23 to 10-26 | 1 | 11.03% | 0.35 |
| 10-27 to 10-30 | 3 | 13.87% | 0.18 |
| 10-30 to 11-06 | 5 | 13.41% | 0.24 |

Three regimes in one month: tomorrow priced on its own, about ten quiet
sessions near 10%, then a step up to roughly 13.5% from 10-28. The error bars
run 0.04 to 0.85 vol points across all three snapshots, so a one-session
window is readable, which was not obvious beforehand - a difference of two
totals divided by 1/252 amplifies whatever the endpoints carry.

The 10-16 to 10-19 window spans three calendar days and one session, and
prices at 9.52%, in line with its neighbours. On a calendar clock it would
read as a dead window. First time the two-clock machinery has been
load-bearing on live data.

Constant maturity, interpolated in total variance against sessions:

| Snapshot | 5 sessions | 10 sessions | 15 sessions |
| --- | --- | --- | --- |
| 2026-09-24 | 12.15% | 12.19% | 12.58% |
| 2026-10-12 | 9.10% | 9.47% | 10.89% |
| 2026-10-13 | 9.79% | 10.04% | 11.39% |

Vol fell about three points over the three weeks and recovered half a point
overnight. These are comparable day to day in a way per-expiry ATM is not,
because no expiry ages underneath them.

No window in any of the three snapshots prices negative variance: 34 windows,
zero calendar arbitrage.

**The densification prediction split.** The grid half was confirmed, sharply:
2026-10-26 went from 26 strikes on a pure $5 grid to 101 strikes at mostly $1
spacing in a single overnight, and 2026-10-27 entered the band the same day as
the new sparse one, 25 strikes with every gap exactly 5.00.

The error half was wrong, and backwards. 2026-10-26's forward error ROSE as it
densified, 2.0c on one pair to 4.2c on five. That is not a regression. One
pair cannot disagree with itself, so its error bar is the noise floor from its
own spread, and five pairs reveal a disagreement the single reading had no way
to show. The floor is a lower bound that can understate the real uncertainty.

How much it understates is not established. There are only three single-pair
expiries across all three snapshots - 2026-10-08, 2026-10-26 and 2026-10-27,
all of them the ~26-strike $5-grid case - with errors of 7.0c, 2.0c and 2.5c
against a 3.5c median for multi-pair expiries. That is far too few to call a
pattern. Re-check as more sparse expiries pass through.

## Following one trading session across snapshots (2026-10-13)

A one-session window between consecutive expiries prices exactly one trading
day, so each snapshot gives a reading for each near-term date and those can be
compared. Monday against Tuesday:

| The session | Seen 10-12 | Seen 10-13 | Change |
| --- | --- | --- | --- |
| 2026-10-15 | 8.73% | 9.22% | +0.48 |
| 2026-10-16 | 9.33% | 9.97% | +0.64 |
| 2026-10-19 | 9.42% | 9.52% | +0.10 |
| 2026-10-20 | 8.71% | 8.76% | +0.05 |
| 2026-10-21 | 9.49% | 10.16% | +0.66 |
| 2026-10-22 | 9.22% | 9.87% | +0.65 |
| 2026-10-23 | 10.06% | 10.20% | +0.14 |
| 2026-10-26 | 11.43% | 11.03% | -0.40 |

The repricing is not uniform. Four sessions were marked up about two thirds of
a point, three barely moved, and 2026-10-26 was marked down. Error bars on
these run 0.06 to 0.35 vol points, so the larger moves are outside them and
the small ones are not.

Nothing in an ATM column or a constant-maturity reading would show this: both
average over the window and a day that moves while its neighbours do not
disappears into the average.

Coverage ends where daily expiries do, roughly two weeks out on SPY. Past
that the windows span three and five sessions and cannot be pinned to a date.

## Widening the collection band (2026-10-15)

The band was 6 expected moves below spot and 3 above. Those numbers were
sized for relative value, where a strike whose IV cannot be read is not worth
collecting. A variance swap integral asks the opposite question: it weights
each strike by 1/K^2 and uses the PRICE, never the IV, so a two-cent put with
hopeless vega contributes exactly two cents and the deep puts carry the most
weight of anything in the chain. The old band cut off precisely those.

Measured on one wide snapshot, 3,812 contracts at 20 moves below and 10
above, by computing the integral twice from the same quotes:

| Expiry | DTE | VS rate at 6/3 | VS rate, full chain | Missed |
| --- | --- | --- | --- | --- |
| 2026-10-16 | 1 | 15.92% | 16.97% | +1.06 |
| 2026-10-23 | 8 | 13.46% | 14.36% | +0.89 |
| 2026-10-30 | 15 | 14.93% | 15.73% | +0.80 |
| 2026-11-13 | 29 | 15.94% | 16.46% | +0.52 |

The wide band was not the binding constraint: at 20 moves the formula reached
for strike 184 on the 29-day and the exchange only lists down to 500, so the
right-hand column is the whole chain.

Opening the put side in steps shows where it converges. Seven of thirteen
expiries gain nothing at all between 12 moves and 20, and the 29-day stops
moving at 10. So the band is now 12 below and 6 above: 3,372 contracts and
169 requests against 2,570 and 129, about two minutes a snapshot.

**What is left at the short end is truncation, not noise.** The 1-day expiry
was still gaining +0.18 vol points at 20 moves with no sign of stopping,
because real strikes remained outside even that band.

It is worth recording that this was first blamed on the tick floor, wrongly.
Propagating each quote's own half-spread through the integral gives an error
of 0.03 vol points at 1 DTE, or 0.25 with every quote assumed to err the same
way - the 2/T factor amplifies the value and its error equally, so it cancels
out of the relative error. The original claim compared a contribution against
sigma^2 * T when the integral already returns sigma^2, an error of a factor
of T.

**Density matters more than maturity.** 2026-10-29 reads a VS-minus-ATM
spread of +1.40 against about +2.5 on either side of it. It is the 30-strike
expiry; a coarse grid under-samples the integral, the same way it weakened
the forward. Any VS rate wants a strike-count quality number beside it.

## Wiring the integral into the time axis (2026-10-16)

`vol.variance_swap()` computes the fair variance strike per expiry and
`term.py` now strips forward variance from it rather than from the
at-the-money level. On the 2026-10-15 chain:

| Expiry | DTE | ATM | VS rate | error | strikes | edge cost | VS - ATM |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-16 | 1 | 14.67% | 17.10% | 0.25 | 110 | 0.036 | +2.42 |
| 2026-10-23 | 8 | 11.90% | 14.37% | 0.14 | 155 | 0.013 | +2.47 |
| 2026-10-29 | 14 | 12.53% | 14.01% | 0.03 | 30 | 0.089 | +1.47 |
| 2026-10-30 | 15 | 12.84% | 15.74% | 0.09 | 235 | 0.014 | +2.90 |
| 2026-11-13 | 29 | 13.23% | 16.46% | 0.05 | 158 | 0.020 | +3.23 |

A flat smile returns its own volatility to three decimal places, which is the
exact answer for a lognormal and is what pins the implementation.

**The sparse expiry broke the term structure before it broke the number.**
2026-10-29 carries 30 strikes against 128-235 either side. Its at-the-money
level is perfectly monotone against its neighbours - 12.19%, 12.53%, 12.84% -
but its variance swap rate DIPS, 14.73% then 14.01% then 15.74%, because a
coarse grid under-samples the integral. Stripped, that produced a negative
window into it and a 25.99% window out of it.

The fix is to drop such an expiry from the term structure rather than fall
back to its at-the-money level, because a window differencing a variance swap
total against an ATM total measures nothing. With 2026-10-29 removed the two
windows become one 2-session window at 17.64%, sitting between the 19.67% and
17.10% either side. `vs_edge_cost` is the test: 0.089 vol points there against
0.013 to 0.036 everywhere else.

**What the edge cost does not catch is a narrow band.** The three chains taken
at 6/3 have perfectly healthy edge costs and are still understated by 0.5 to
1.1 vol points, because many small missing contributions add up while each
outermost strike still looks unimportant. There is no internal check for this,
so `collected_band` travels with every expiry from run.json and `app.py
history` warns when a comparison crosses the convergence point.

That warning fires on the measured line rather than on any difference: 12
moves is where the integral stopped moving, so 12/6 and 20/10 compare fine
with each other and neither compares with 6/3. A warning that fired on every
band change would fire forever and be ignored.

## Porting the implied-against-realized log, and a check on the integral (2026-10-18)

`vrp_log.py` from the straddle folder is now `screener/prices.py` and
`screener/vrp.py`. The monthly anchoring and the realized convention came
across unchanged; the pandas and numpy were dropped so only `prices.py`
carries a third-party import, the way `collect.py` is the only file that
talks to Webull.

Running it against the full cache rather than the 2021 start the old log
used:

| | |
| --- | --- |
| Completed months | 405 |
| Implied mean | 19.54% |
| Realized mean | 15.75% |
| Premium | +3.78 points |
| Months realized beat implied | 64 of 405, 16% |

**The integral agrees with VIX.** The first chain collected wide enough to
carry a variance swap rate was 2026-10-15. At 29 days it reads 16.46%; ^VIX
closed at 16.46% the same day.

| 2026-11-13, 29 days out | Value | Ratio to ^VIX |
| --- | --- | --- |
| Our ATM IV | 13.23% | 0.804 |
| Our variance swap rate | 16.46% | 1.000 |

The 0.804 matches the ATM-to-VIX ratio measured earlier at 0.793. Two
caveats: agreement to two decimals is luck, since our snapshot is 12:33
intraday against a 16:00 close, SPY against SPX, 29 days against 30; and it
is one observation. Half a point would have counted as success. But the gap
closing from 21% to inside a rounding error on the first try is the strongest
evidence so far that the integral computes what it claims.

**The rate assumption checks out.** ^IRX is cached back to 1960. On our four
snapshot dates the 13-week bill read 4.050% to 4.088% against the 4.000% in
`vol.CONFIG`, so we are 5 to 9 basis points low, worth about half a cent on a
30-day forward against a forward error bar of 1 to 11 cents. Integrity item 1
is closed.

## The daily bar (2026-10-18)

`vrp.daily_path` writes one row per session under each monthly claim, to
`data/vrp/daily.csv`: return, absolute return, the bar, beat, expanding
realized, realized minus implied, running beat rate. 8,554 rows over 404
windows.

| | |
| --- | --- |
| Distinct sessions | 8,365 |
| Beat the implied one-day bar | 1,679, or 20.1% |
| A fair market would clear it | 31.7% |
| Predicted from the monthly premium | 21.5% |
| Biggest session | 2008-10-13, +14.52%, 5.8 bars |

The straddle tool's note that a fairly priced window beats the bar about 50%
of sessions is wrong. The bar is one standard deviation, cleared 31.7% of the
time by a normal, and the median session comes in at 0.67 bars.

That 20.1% against a predicted 21.5% is worth noting: the prediction comes
from the monthly figures alone - realized runs 0.806 of implied, so the true
move is 0.806 bars and a normal clears 1/0.806 standard deviations 21.5% of
the time. Two independent routes to the same number.

**Window overlap.** A calendar month from one month's first session can reach
past the next month's, so 189 of 8,365 sessions belong to two windows, 2.3%.
Each window's path is left whole because it must end on the realized figure
its monthly row reports; aggregate counts dedupe instead.

The worst case was not a rounding issue. SPY's history opens 1993-01-29, so
that date became January's first session and anchored a window running to 28
February which shared 18 of its 19 sessions with February's. Anchors are now
required to fall in the first week of their month, which drops it: 405
completed months became 404 and nothing else moved.

## Decomposing the chain into windows (2026-10-21)

`term.py` prices each gap between expiries and stops. `context.py` asks the
second question of every one of them, without being told which to look at:
is this window expensive, and expensive against what.

**Two baselines, and only one of them finds much.** On the 2026-10-20_1543
chain, 12 windows tiling 23 sessions:

| comparison | flagged beyond the error on the difference |
|---|---|
| against the whole rest of the chain | 8 of 12 |
| against the line between its neighbours | 4 of 12 |

The first count is mostly the term structure restating itself. The chain runs
from 12.25% at the front to 18.51% at the back, so every early window reads
cheap against the rest and every late one rich: eight findings carrying one
fact about the shape. The local comparison removes a straight line by
construction, and what survives it is this:

```
10-23 to 10-26   14.89%   +1.18p against its neighbours
10-26 to 10-27   14.05%   -3.07p
10-27 to 10-28   19.36%   +3.59p
11-06 to 11-13   17.02%   -0.68p
```

One session, 28 October, is priced at 19.36% inside a chain averaging 16.82%,
standing 3.59 points above the straight line between the sessions either side
of it. Nothing in this repo carries an event calendar, so what is being priced
there is not identified here - only that it is being paid for, and that no
part of the term structure's shape accounts for it.

**The line, not the mean.** Windows are not equally spaced: SPY lists daily
expiries about two weeks out and weekly after that. Against uneven spacing the
mean of the two neighbours still carries part of the slope, while the straight
line between them read at the window's own midpoint removes it exactly. On
this chain the two agree to 0.000 points everywhere the expiries are daily and
part company once they are not, by at most 0.067 points.

Small here, and not small in general. For windows of 2, 1 and 5 sessions
carrying 12%, 15% and 21%, the midpoints fall at 1, 2.5 and 5.5 sessions: the
line gives 15% and the mean gives 16.5%, so averaging would report a 1.5 point
anomaly where there is only slope.

**Two clocks on the same variance.** The first run of this printed the chain's
aggregate beside VIX and showed a gap that did not exist. `term.py` builds
total variance on calendar days and divides windows by sessions - deliberate,
and right, because the session clock is what makes adjacent windows
comparable - but it leaves the aggregate annualized on sessions while every
index number is annualized on calendar time. The same total variance, 23
sessions inside 31 days:

```
session clock     16.82%
calendar clock    17.42%
our 30-day rate   17.37%   interpolated to VIX's maturity
VIX the same day  17.31%
```

0.60 points of pure convention, which is most of the distance a real
dislocation would have to travel to be worth noticing. Both are now printed
with their clock named, and the descent from 17.42 to 17.31 reads as three
small explicable steps rather than one unexplained one.

**What the band tier would have cost.** The original plan ranked each window
against a historical distribution stripped from VIX9D, VIX and VIX3M. It was
dropped before it was built. Three index series resolve three points on the
curve, while this chain carries seven separate windows inside the first nine
days alone, so a percentile at that resolution would have meant collapsing
seven measurements into one to rank it - and 30 to 90 days sits past what the
collector reaches at all. The 30-day level is ranked against VIX, which is
like for like. The windows are ranked against nothing yet; what they will be
ranked against is our own history of them.

## What averaging volatility readings does to a premium (2026-10-23)

The ledger's first settled summary reported realized running 2.72 vol points
below priced across 41 closed windows. It read as a clean confirmation of the
premium measured everywhere else here. Almost all of it was the average.

38 of those 41 windows hold a single session, and one absolute return
annualized is a biased estimate of that session's sigma - by Jensen, the
square root of an average is below the average of the square roots. For a
normal it comes to sqrt(2/pi) = 0.7979 of the truth. Against a mean priced
level of 12.59%, pricing that was exactly right would still have produced

    12.59% x 0.7979 - 12.59% = -2.54 points

against the -2.72 measured. The signal was -0.18 points and the estimator was
the rest.

Pooled in variance instead - squared returns summed against summed priced
variance, which is what vrp.py already does over a month - the same 41 rows
give a realized-to-priced ratio of 0.829, against the 0.806 SPY has run over
its whole history. The usual premium, and no finding.

The bias is a function of how many returns the window holds, and it dies
quickly:

| sessions | a realized reading averages |
|---|---|
| 1 | 0.7979 of the true sigma |
| 2 | 0.8862 |
| 5 | 0.9515 |
| 21 | 0.9882 |
| 252 | 0.9990 |

Which is why vrp.py never tripped over this and the ledger did on its first
run. A monthly claim carries 1.2% of the bias; a one-session window carries
20% of it, and the ledger is mostly one-session windows.

The rule this leaves: anything averaging volatilities across short windows
has to be pooled in variance instead, and a premium measured off short
windows is not comparable to one measured off long ones without this
correction.

## The snapshot's own session (2026-10-25)

`vol.sessions_between` counts trading days from the day AFTER the snapshot,
which puts the session clock's origin at that day's close. A snapshot taken
before the close therefore sits at a NEGATIVE session count, and the window
running from it to the first expiry is longer than one session by whatever
is left of today.

Nothing corrected for that. The front window priced the rest of today plus
all of the next session and was divided by a single session:

| snapped at | sessions left | front window reads |
|---|---|---|
| 09:45 | 0.96 | 40.1% high |
| 12:30 | 0.54 | 24.0% high |
| 14:30 | 0.23 | 10.9% high |
| 15:45 | 0.04 | 1.9% high |

Only the first window is affected. Every other one differences two expiries
that both contain the same partial day, so it cancels there.

The size of the problem is not the bias itself but its variability. A routine
snapping at 15:45 most days and 14:30 on two of them puts a 1.06 point
sawtooth into the front of the chain on a 12% window, twice a week, and the
ledger reports it as a repricing.

**The fix.** `context.with_spot` gives the synthetic spot row a session count
of minus the fraction of the session still to run, read from `started_et` in
the snapshot's own run.json. The front window then spans `1 + fraction`
sessions and the arithmetic is right at any snapshot time. Nothing else moves.

**Measured, not just derived.** The two snapshots twelve minutes apart on
2026-10-20 give the same chain at two clock times:

```
                   left   uncorrected   corrected
2026-10-20_1531   0.072      12.44%       12.01%
2026-10-20_1543   0.042      12.25%       11.99%
```

0.194 points of disagreement before, 0.020 after - and twelve minutes of
genuine market movement sits inside that residual.

Applied to the six snapshots on disk, which were taken anywhere from 11:42 to
15:43, the pooled realized-to-priced ratio over 41 settled windows moved from
0.829 to 0.845. The ledger rebuilds from context's output rather than
appending, so one change corrected the whole history on the next run.

Half-days remain uncorrected: a 13:00 close makes the fraction above
overstated, and that is a separate dated gap.

## Resolution is not repricing (2026-10-25)

The pivot view puts snapshots down the side and the dates they price across
the top, so a column is one date's history. On its first run it separated
two things that look identical in a single chain.

The 28 October FOMC window, read down:

| snapshot | window covering 28 Oct | vol | vs neighbours |
|---|---|---|---|
| 2026-10-12_1449 | 10-26 to 10-30, 4 sessions | 15.65% | +1.51p |
| 2026-10-13_1319 | 10-26 to 10-30, 4 sessions | 15.27% | +0.60p |
| 2026-10-15_1233 | 10-27 to 10-28, 1 session | 19.67% | +4.16p |
| 2026-10-20_1543 | 10-27 to 10-28, 1 session | 19.36% | +3.59p |

The jump from +0.60 to +4.16 between the 13th and the 15th is not the market
changing its mind. On the 12th and 13th the meeting sat inside a four-session
block: three quiet days near 14% averaged with one near 19.7% gives the
15.65% shown, and the event is diluted below anything the local comparison
could flag. By the 15th SPY had listed a 27 October expiry, the block split,
and the day stood on its own.

So the event was priced at full size the moment a daily expiry existed to
carry it, and decayed mildly from there - 4.16 to 3.59 over five sessions.
Nothing built gradually.

**Why the cell is vs_neighbours and not vs_rest.** vs_rest spans 7.68 points
from the front of the 2026-10-20 chain to its back, which is the term
structure and nothing else. A window drifting toward the front walks that
entire range with nothing repricing, so as a time series it would measure
position. vs_neighbours removes the local slope wherever the window sits.
The cost is that the first and last window of each chain have no reading.

**What the grid still cannot separate.** A period genuinely reprices as it
approaches, because uncertainty about it resolves - the chain walks from
trailing realized toward the long-run average, and a fixed window walks back
down that. That drift is not news and there is no baseline for it yet.
`sessions_ahead` is now recorded on every row so the drift can be estimated
once there is a year of series; until then ageing and news are confounded in
any column read.
