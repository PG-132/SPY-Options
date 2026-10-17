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
