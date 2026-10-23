# Concepts: Reference file needed to keep track of everything.

Three docs, kept apart on purpose:

- **measurements.md** has a date and a number. What produced every constant.
- **integrity.md** has a failure mode and a check. What could still be wrong.
- **concepts.md** has neither. Here lies mechanisms, the theory, which should stay 
    true when the numbers change.

Nothing here forecasts. Priced at their own IVs every structure is a fair bet,
so rich and cheap always mean against the rest of today's surface, never
against a prediction.

## The forward, and why it has an error bar

Black-Scholes needs a forward price, not a spot. Spot needs a dividend
estimate and a rate assumption bolted on; the option chain quotes its own
forward through put-call parity:

    C - P = disc * (F - K)

so any strike quoted on both sides implies a forward, with no dividend
guessed. Pricing both sides of a strike off one forward is also what stops a
call and a put at the same strike disagreeing about implied vol, which is the
flaw the Sep-25 straddle log had.

Every strike implies a forward and they should all agree. They do not. The
disagreement is a **bias, not noise**, which is the fact that decides how to
handle it:

- it arrives as a slope in strike, not as scatter
- it tracks each pair's width asymmetry, call spread minus put spread
- it survives when timing is ruled out

The mechanism is that the in-the-money leg is quoted wider, because the market
maker carries more premium and more direction on it, so its mid sits
predictably off fair value. How deep a leg sits runs monotonically with
strike, so the error tilts rather than scatters.

Averaging cures noise and does nothing for a bias. What cures a bias is
reading it where it vanishes, which is where both legs are quoted the same
width. So pairs pass an asymmetry gate first, and only then are the tightest
survivors averaged against the noise that is left. When nothing passes the
gate the bias has become the dominant error, so the weighting targets
asymmetry instead of width.

What the survivors still disagree by is `forward_error`, never zero and never
assumed away.

## The error bar on every point

An IV solved from a mid is a point estimate of something quoted as a range.
Solve at the bid and at the ask instead and the width between them is that
strike's error bar:

    iv_band = iv(ask) - iv(bid),  which is roughly spread / vega

Vega is what makes this interesting. Most of a chain is quoted a penny wide,
but vega runs from tens of dollars near the money down to cents in the wings,
so the same penny is a hundredth of a vol point in one place and most of a
point in another. A deviation is only a deviation relative to how well that
strike can be read at all.

This is why weights in the fit are 1/band^2: a penny-wide wing cannot drag a
curve that a tight at-the-money quote defines.

## Residual, edge, and the forward's cost

Three different questions, easy to confuse.

**residual** is our IV minus the fitted curve. It says where a strike sits
relative to its neighbours. It flatters the wings, where half a cent of quote
is a vol point.

**edge_at_bid** and **edge_at_ask** are the same deviation read at the prices
you would actually trade: the IV at the bid minus the curve, and the curve
minus the IV at the ask. Positive means the deviation is bigger than the
spread you would cross to take it. This is the only version that can pay.

**forward_cost** is how much of the deviation the forward's own error bar
could account for. A wrong forward is not noise on one strike. It moves every
IV in the expiry together AND slides the log-moneyness axis, so the fitted
curve follows and most of the error cancels out of a residual. How much is
left cannot be derived, because it depends on how the curve moves too, so it
is measured: refit the smile on the IVs solved at the shifted forward, against
the shifted axis, and see how far each point's residual moved.

The cancellation is not uniform, which is the whole reason the obvious
shortcut fails. In the wings nearly all of it cancels. At the money almost
none does, because the IV sensitivity is sharply peaked exactly there and that
is the one shape the basis cannot make. At the far edges the residual can move
MORE than the IV did, because the refit swings and the curve runs out from
under the point. So widening each band by its own IV sensitivity is not a
conservative bound - it is too strict in the wings and too lenient at the
edges, wrong in both directions at once.

An edge counts only when it clears its spread and outlasts its forward cost.

## Two clocks

Time to expiry for pricing is actual hours to the 16:00 close, because that is
the clock the model uses and the one the option trades on.

Sessions are counted separately, because comparing expiries in calendar time
makes any expiry with a weekend in it look cheap: four days of decay for two
days of movement, inaccurate. Per-session IV is what makes two expiries comparable.

Distance out of the money is counted in expected moves and in delta, not in
percent, for the same reason: a 2% strike is far away at one week and near at
one month.

The collected band is sized the same way - 6 expected moves below spot, 3
above - and that is what keeps strikes with no real market out of the data in
the first place. Garbage inside the band is removed by the gates instead: no
bid, then band width, vega, spread share, open interest, volume and quote age.

## The limit worth knowing

The deviations this finds are hundredths of a vol point, and an edge only
exists when it is bigger than the spread crossed to take it. Widen every
spread in a chain and the edges disappear - not because a gate fails but
because the arithmetic is honest. Crossing cost rises faster than any
deviation in the book.

So this measures relative value only where execution is cheap, and execution
is cheap only in a calm market. That is a property of relative-value screening
on a liquid index, not a bug to tune out. See measurements.md for specific measurements.

## The time axis

A smile is one expiry. Twelve smiles are not a surface until something links
them, and what links them is that an expiry contains all the time of every
expiry before it, plus the sessions in between.

**Variance adds across time; volatility does not.** Total variance to an
expiry is `iv^2 * T`, and the variance belonging to the days between two
expiries is the difference of their totals. Divide by the sessions in that gap
and you have the market's price for one of those sessions. That number can be
set beside the session next to it, which an ATM IV never could.

The failure mode this avoids: averaging IVs across time. Ten sessions at 10%
followed by ten at an overall 20% does not mean the second ten were at 30%.
Worked in variance it is 26.46%, and the gap widens as the term structure
steepens.

Two readings come out of the same arithmetic.

**Forward variance** prices one window on its own. It is what shows a dated
event: a single session carrying three times its neighbours' variance is
invisible in an ATM column and obvious here.

**Constant maturity** fixes the horizon and lets the expiry roll, so one day
compares with the next. This is what VIX does, and it exists because an
expiry's own path confounds two things. When a specific expiry's IV falls, you
cannot tell from that alone whether the market calmed down or the expiry
simply got older - skew in particular shrinks with maturity as a structural
matter, not as news. Holding sessions fixed separates them.

Both are on the session clock. A window spanning a weekend holds three
calendar days and one session, and only the session clock prices it in line
with its neighbours.

**Why the error bars matter more here.** A forward variance is a difference of
two totals divided by a small session count. A one-session window divides by
1/252, so whatever error each endpoint carries is amplified by that factor.
Both sources are propagated: the fit's standard error on the at-the-money
level, and that expiry's forward cost, which is systematic and does not shrink
by averaging.

**The no-arbitrage check comes free.** Total variance cannot fall as maturity
grows - that would price a window of negative variance, which is a calendar
arbitrage. It is checked on every adjacent pair, and because a small negative
can be noise, the check asks whether it is negative by more than its own error
bar. Reported, never silently repaired.

## Three ways to compare two days, and they answer different questions

Everything up to here reads one snapshot. Comparing snapshots is where the
confusion lives, because there are three comparisons and they are routinely
mistaken for each other.

**Fixed expiry.** Follow one contract as it ages. This is what a position
experiences, so it is the honest view for a trade you are holding. It is also
confounded on purpose: when an expiry's IV falls you cannot tell from this
view alone whether the market calmed down or the expiry simply got older.
Skew in particular shrinks with maturity as a structural matter rather than
as news - on the Sep-24 chain the 29-day expiry carried 2.55 points of
25-delta put skew, and three weeks later the same contract read 1.26 at ten
days. Almost none of that was repricing.

**Constant maturity.** Pin the horizon, let the expiry roll. Is vol higher
than yesterday, all else equal? This separates the two things the first view
mixes, and it is what VIX does. It never describes the same calendar days
twice - five sessions from today and five sessions from tomorrow are
different days - which is the price of the number meaning the same thing on
every line.

**Per session.** Pin the calendar DATE and watch the market change its mind
about it. A one-session window between consecutive expiries prices exactly one
trading day, so that day can be followed across snapshots. This is the view an
economic calendar belongs beside: it answers whether the market is getting
more or less worried about next Thursday specifically. Only available where
expiries are consecutive daily ones, so about two weeks out on SPY.

## Which number is the right one depends on the structure

Total variance and forward variance are both correct and neither is the
default. What decides is whether the position spans one window or trades two
windows against each other.

A straddle held to expiry is a bet on the TOTAL variance of its window:
implied at entry against realized over the whole thing. How the variance is
distributed inside the window barely enters the verdict, so the aggregate is
the right unit and the stripped view is noise.

A calendar spread is the opposite. It trades one time segment against
another, so the time the two legs share cancels out and what is left IS the
forward variance between them. Reading total variance on each leg would be
reading mostly the part that does not matter.

Same surface, same arithmetic, and picking the wrong unit makes a structure
look mispriced when it is not.

## The variance swap rate, and why the time axis uses it

Implied variance at one strike is not the variance of anything. It is a
Black-Scholes input chosen to reproduce a price, so differencing it across
expiries is a convention rather than a theorem, and the at-the-money level is
one point on a curve that carries far more.

The variance swap rate is the quantity that IS additive across time. It
integrates the whole out-of-the-money chain:

    sigma^2 = (2/T) sum (dK/K^2) e^{rT} Q(K)  -  (1/T)(F/K0 - 1)^2

so the smile is not discarded for the time axis, it is compressed. One number
per expiry carrying the entire curve, and that number differences cleanly
across maturities. The 1/K^2 weighting is not a choice: it falls out of the
replication theorem, which is also why the deep puts matter most and why the
collection band has to reach them.

The gap between it and the at-the-money level is what skew contributes, and
on 2026-10-15 that ran +1.9 vol points at four days to +3.2 at twenty-nine.
Both numbers are kept because that spread is a skew term structure for free,
and because they answer different questions: nobody trades a variance swap on
a retail broker, so the at-the-money level is still what you compare against
an option you are about to buy.

**Three things break it, and all three are recorded rather than patched.**

*A narrow strike band* understates it, because the missing contributions are
small individually and numerous. This is NOT caught by the convergence check
below - many tiny omissions add up while each outermost strike still looks
unimportant. The only defence is collecting wide enough, so the band travels
with every expiry as `collected_band` and comparing rates across a band
change compares different quantities.

*A sparse strike grid* under-samples it. `vs_edge_cost` catches this: it is
what the outermost strike on each side was worth, so a grid where each strike
carries a lot shows a large one. An expiry failing that check is dropped from
the term structure rather than falling back to the at-the-money level,
because a window differencing a variance swap total against an ATM total is
not measuring anything. One source per snapshot or none.

*Short maturity* was expected to break it through the tick floor and does
not. The 2/T factor amplifies the value and its error equally, so it cancels
out of the relative error: at one day the quote spreads are worth 0.03 vol
points, or 0.25 with every quote assumed to err the same way.

## Implied against realized, and why the rows are monthly

Everything before this measures what the market charges. This is the first
part that asks whether the charge was right.

The comparison only means something over the SAME forward window. Implied is
forward-looking, so pairing a month's implied with the PREVIOUS month's
realized compares two different things - which is what most write-ups do,
because trailing realized is available immediately and forward realized makes
you wait.

**One claim per month, anchored on the month's first session.** A claim every
session would give about 250 rows a year that each share 20 of their 21
sessions with the row before. They cannot be averaged without counting the
same days over and over, and day-to-day wobble on SPY is mostly noise. Month
anchors are naturally non-overlapping, so each row is an independent
observation and only one claim is ever open.

That is also the ceiling on anything predictive here. Thirty-six years of
prices is about 430 independent observations, not 9,000.

**Two implied sources, and as of 2026-10-18 they are the same quantity.**
^VIX reaches back to 1990 and is the only implied series with real depth, but
it is SPX and a variance swap integral rather than an at-the-money quote. Our
own at-the-money number was never comparable with it - it runs about 0.80 of
VIX, which is the skew VIX includes and an ATM reading does not. Now that
`vol.variance_swap` computes the same kind of number, the two can be set
side by side: on 2026-10-15 ours read 16.46% against VIX's 16.46%.

What has not changed is depth. Ours begins at 2026-10-15 and needs a snapshot
on a month's first session to anchor a row, so the monthly log runs on ^VIX
for a long time yet and `iv_source` records which produced each row.

**Realized** is zero-mean sqrt(mean(r^2)) on close-to-close log returns,
annualized by sqrt(252) - the straddle workbook's convention, kept so the two
agree. The window is open on the left and closed on the right: the anchor's
own close is the base the first return is measured from, not a return itself.

## The daily bar, and what beating it means

Under each monthly claim sits a row per session, which is the straddle
workbook's vol block generalised from one position to the market: return,
absolute return, the daily bar, whether the day cleared it, expanding
realized vol, and realized minus implied.

**The bar is the window's implied vol divided by sqrt(252)** - the one-day
move implied at the anchor, held fixed across the whole window exactly as the
sheet holds entry IV fixed for a trade. It is one standard deviation, not a
coin flip.

That distinction matters and the straddle tool got it wrong. Its note said a
fairly priced window beats the bar about half the time. It does not: for a
normal distribution a one-standard-deviation move is exceeded **31.7%** of
sessions, and the median session comes in at 0.67 bars. Reading 50% as fair
would make every window look quiet.

Measured across 404 completed months since 1993, SPY cleared its bar on
**20.1%** of sessions. That is below 31.7% by about the amount the monthly
premium predicts: realized runs 0.806 of implied, so the true move is 0.806
bars, and a normal clears 1/0.806 standard deviations 21.5% of the time. The
daily and monthly views are telling the same story from different angles,
which is the useful part - one is a verdict a month late, the other is the
same verdict forming in public.

**One wrinkle to know about.** Consecutive windows can share a session or
two, because a calendar month measured from one month's first session can
reach past the next month's. 189 of 8,365 sessions, about 2.3%, belong to two
windows. Each window's own path is left whole, since it has to end on the
realized figure its monthly row reports; the overlap is removed when sessions
are counted in aggregate. The monthly rows themselves are what the
independence claim rests on, and they are 2.3% short of perfectly disjoint
rather than exactly disjoint.

## Expensive against what

A forward window's volatility carries no scale of its own. 19.36% for one
session means nothing until it is set beside something else, and the choice
of what to set it beside decides what you are able to find.

**Against the rest of the chain.** The chain's total variance less this
window's, over the sessions that are left. This answers the level question:
of everything on offer between now and the last expiry, is this stretch the
expensive part of it.

Its hazard is that a term structure nearly always slopes, and against this
baseline a slope says the same thing about every window at once - the front
is cheap, the back is rich. Twelve rows carrying one fact. True, and close
to empty.

**Against its neighbours.** The straight line between the windows either
side, read at this window's own midpoint. A slope passes straight through a
line, so what is left over is the window that breaks the local pattern: a
single session priced above the days around it, which is how a scheduled
announcement shows up in a chain before anyone has told you it is there.

Not their mean. Windows are unevenly spaced once the daily expiries run out,
and against uneven spacing the mean of two neighbours still has slope left in
it. The line and the mean are the same number only when the gaps either side
happen to be equal.

The obvious third option - fit a curve to the term structure, report the
deviations from it - is left out on purpose. Whatever shape is chosen decides
which windows look unusual, and a smooth one will absorb exactly the bump the
exercise exists to find.

**Why the error bar belongs on the difference.** A window and the rest of the
chain are not two independent measurements. They share endpoints, and they
share them with opposite signs: an error in the total variance at the
window's far edge raises the window and lowers the rest by the same stroke.
Their difference is therefore less certain than either side of it, and
propagating the two as though they were independent would understate the bar
and call differences real that are not.

So every comparison here is differentiated through to the per-expiry totals,
and the coefficients are summed per expiry before squaring. That last part is
not a nicety. For the final window the rest's far end and the window's own
far end are the same number and have to cancel; counting each appearance
separately invents an uncertainty that is not there.

**Why no window gets a percentile.** Ranking a number needs a history of the
same number. The index series give three points on the curve - 9, 30 and 93
days - and a single chain carries six or seven windows inside the first nine
days alone. A percentile at the index's resolution would cost the resolution
the time axis was built to get.

The 30-day level is different: VIX is a 30-day variance swap rate and so is
ours, so that one is like for like and gets ranked. The windows will be
ranked eventually against our own history of them, at our own resolution,
which is why every window of every snapshot gets logged rather than only the
ones that looked interesting on the day.
