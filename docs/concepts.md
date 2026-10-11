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
