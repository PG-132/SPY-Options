"""
pricing.py - Black-Scholes in forward terms. Step 2 of the screener.

Everything here prices off the FORWARD rather than spot. The forward is what
the option chain itself tells us, through put-call parity, while spot needs a
dividend estimate and a rate assumption bolted on top. Feeding one forward to
both sides of a strike is what stops a call and a put at that strike from
disagreeing about implied vol, which is the flaw that showed up in the Sep-25
straddle log (see docs/measurements.md).

The inputs are:

  F      forward price of the underlying for that expiry
  K      strike
  T      time to expiry in years, counted as calendar days / 365
  sigma  volatility, annualized, as a decimal
  disc   discount factor to that expiry, e^(-rT)

Greeks come back PER SHARE, in the units the straddle tool used, so the two
can be compared directly:

  delta  shares per share          gamma  delta change per $1 of spot
  theta  $ per calendar day        vega   $ per vol POINT

Position sizing (x contracts x 100) belongs to the caller, not here.

The model is European. SPY options are American, which matters for deep
in-the-money puts; out of the money, where we solve our IVs, the difference is
negligible.
"""

import math

SQRT_2 = math.sqrt(2.0)
SQRT_2PI = math.sqrt(2.0 * math.pi)


class SolveError(RuntimeError):
    """No implied vol exists for this price: it sits at or below the
    no-arbitrage floor, which no volatility can produce."""


def norm_cdf(x):
    return 0.5 * math.erfc(-x / SQRT_2)


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / SQRT_2PI


# ---------------------------------------------------------------------------
# Getting to a forward
# ---------------------------------------------------------------------------

def from_spot(spot, T, rate):
    """(forward, discount) implied by a spot price and a rate. Dividends are
    the caller's job: subtract their present value from spot first, the way
    the straddle tool escrows them."""
    disc = math.exp(-rate * T)
    return spot / disc, disc


def forward_from_parity(call, put, strike, disc):
    """The forward the market itself is quoting. Parity says a call minus a
    put is worth the discounted distance from strike to forward:

        C - P = disc * (F - K)

    so the chain prices the forward without us guessing a dividend."""
    return strike + (call - put) / disc


def floor_price(right, F, K, T, disc):
    """The lowest price arbitrage allows. A quote at or under this has no
    implied vol: it is all intrinsic, and volatility can only add value."""
    if T <= 0:
        return max(0.0, (F - K) if right.upper()[0] == "C" else (K - F))
    return disc * max(0.0, (F - K) if right.upper()[0] == "C" else (K - F))


# ---------------------------------------------------------------------------
# Price and Greeks
# ---------------------------------------------------------------------------

def bs(right, F, K, T, sigma, disc):
    """European price and Greeks from the forward. At or past expiry the price
    is intrinsic and the Greeks are degenerate, which is honest: there is no
    curvature left to measure."""
    right = right.upper()[0]
    if T <= 0:
        intrinsic = max(0.0, F - K) if right == "C" else max(0.0, K - F)
        delta = (1.0 if F > K else 0.0) if right == "C" else (-1.0 if F < K else 0.0)
        return {"price": intrinsic, "delta": delta, "gamma": 0.0,
                "theta": 0.0, "vega": 0.0}
    if sigma <= 0:
        raise ValueError("sigma must be positive")

    spot = disc * F                      # what the forward is worth today
    rate = -math.log(disc) / T
    sqT = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqT)
    d2 = d1 - sigma * sqT
    pdf1 = norm_pdf(d1)

    if right == "C":
        price = disc * (F * norm_cdf(d1) - K * norm_cdf(d2))
        delta = norm_cdf(d1)
        theta_yr = -spot * pdf1 * sigma / (2 * sqT) - rate * K * disc * norm_cdf(d2)
    else:
        price = disc * (K * norm_cdf(-d2) - F * norm_cdf(-d1))
        delta = norm_cdf(d1) - 1.0
        theta_yr = -spot * pdf1 * sigma / (2 * sqT) + rate * K * disc * norm_cdf(-d2)

    return {
        "price": price,
        "delta": delta,                             # per share of the underlying
        "gamma": pdf1 / (spot * sigma * sqT),
        "theta": theta_yr / 365.0,                  # $ per calendar day
        "vega": spot * pdf1 * sqT / 100.0,          # $ per vol point
    }


def implied_vol(right, price, F, K, T, disc):
    """Invert the price for sigma. Newton first, bisection as backup.

    Newton stops on the size of the SIGMA step, not on how well the price
    matches. A price tolerance alone lets a tiny-vega option, far out of the
    money or nearly expired, return a sigma that is wrong by whole vol points
    while its price still agrees to a penny."""
    right = right.upper()[0]
    floor = floor_price(right, F, K, T, disc)
    if T <= 0 or price <= floor + 1e-8:
        raise SolveError(
            f"{'call' if right == 'C' else 'put'} at {price:.4f} is at or below its "
            f"no-arbitrage floor {floor:.4f}: no implied vol exists. "
            f"(Mid stale, or trading at intrinsic near expiry.)")

    sigma = 0.2
    for _ in range(100):
        m = bs(right, F, K, T, sigma, disc)
        vega = m["vega"] * 100.0                    # back to per 1.00 of vol
        if vega < 1e-12:
            break
        step = max(-0.5, min(0.5, (m["price"] - price) / vega))
        sigma = max(1e-4, sigma - step)
        if abs(step) < 1e-10:
            return sigma

    lo, hi = 1e-4, 5.0
    if bs(right, F, K, T, hi, disc)["price"] < price:
        raise SolveError(f"price {price:.4f} exceeds the model's value even at 500% vol")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if bs(right, F, K, T, mid, disc)["price"] > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-10:
            break
    return 0.5 * (lo + hi)


def iv_band(right, bid, ask, F, K, T, disc):
    """Implied vol solved at the bid and at the ask. The width is the error
    bar on that strike's IV: it says how much of what we read is the market
    and how much is the spread. In the wings, where vega collapses, a penny
    of spread can be most of a vol point."""
    return (implied_vol(right, bid, F, K, T, disc),
            implied_vol(right, ask, F, K, T, disc))
