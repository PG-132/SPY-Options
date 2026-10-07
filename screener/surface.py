"""
surface.py - fit a smooth shape through the measured IVs, then measure what
sits off it. Step 3 of the screener.

  python app.py surface                  the newest snapshot
  python app.py surface 2026-09-24_1142  a particular one

vol.py measures and judges nothing. This file is where the opinions live: what
counts as readable, what counts as tradeable, what shape the smile should be,
and how big a deviation has to be before it means anything.

TWO KINDS OF GATE
-----------------
Readable asks whether a point can be measured: an IV band narrower than the
deviations we care about, and enough vega that a vol point is worth something.
Tradeable asks whether you could act on it: a spread that does not eat the
premium, evidence somebody is there, and a quote that is not a ghost.

They are kept apart on purpose. A strike nobody holds still tells us where the
market prices that point, so it shapes the curve even when we would never
trade it. Only readable points are fitted; the trade flag rides along for
whatever ranks candidates later.

THE FIT
-------
Per expiry, a cubic in ln(K/F) by weighted least squares, weighted 1/band^2 so
a penny-wide wing cannot drag the curve a tight at-the-money quote defines.
The axis is log-moneyness against that expiry's own forward: model-free given
the forward, unmoved by IV or by time passing, and it shifts only when the
forward does. Delta would be circular here, since the x-coordinate would move
whenever the fitted y moved.

WHAT COMES OUT
--------------
For every point, the fitted IV and three readings:

  residual      our IV minus the fitted curve
  edge_at_bid   the IV at the BID minus the fitted curve. Positive means you
                could sell this strike above the curve, after crossing.
  edge_at_ask   the fitted curve minus the IV at the ASK. Positive means you
                could buy it below the curve.

Residual alone flatters the wings, where half a cent of quote is a vol point.
The edge readings ask the only question that pays: is the deviation bigger
than the spread you would cross to take it? In SPY the answer is almost always
no, and that is worth seeing plainly.

data/surface/<snapshot>/points.csv and fits.csv; nothing upstream is touched.
"""

import csv
import math
import pathlib
import sys

CONFIG = {
    # Readable: can this point be measured?
    "max_iv_band": 0.005,       # half a vol point of spread, in IV terms
    "min_vega": 0.05,           # $5 per contract per vol point
    # Tradeable: could you act on it?
    "max_spread_pct": 0.25,     # crossing costs a quarter of the premium
    "min_open_interest": 10,    # blank means Webull did not report it, not zero
    "min_volume": 1,            # it traded at least once today
    "max_quote_age_min": 5,
    # The fit
    "min_points": 8,            # fewer than this and five terms is just noise
    "band_floor": 0.0005,       # no quote counts as better than 0.05 vol points
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
IV_DIR = ROOT / "data" / "iv"
OUT_DIR = ROOT / "data" / "surface"

POINT_COLS = ["symbol", "expiry", "dte", "sessions", "strike", "right", "moneyness",
              "delta", "iv", "iv_bid", "iv_ask", "iv_band", "fitted_iv", "residual",
              "edge_at_bid", "edge_at_ask", "readable", "tradeable", "why_not",
              "spread_pct", "open_interest", "volume", "vega", "forward"]
FIT_COLS = ["expiry", "dte", "sessions", "forward", "points_fitted", "points_dropped",
            "rms_vol_pts", "median_band", "worst_residual", "sign_changes", "atm_fitted",
            "slope_at_atm", "curvature", "m", "s", "c0", "c1", "c2", "c3", "c4"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def readable(p):
    """Can this point be measured? Returns (ok, reason)."""
    if p["iv_band"] > CONFIG["max_iv_band"]:
        return False, f"band {p['iv_band']*100:.2f} pts"
    if p["vega"] < CONFIG["min_vega"]:
        return False, f"vega ${p['vega']*100:.2f}"
    return True, ""


def tradeable(p):
    """Could you act on it? Missing open interest counts as unknown rather
    than zero: Webull leaves the field blank on newly listed expiries, and
    treating that as nobody-there would delete whole expiries that trade."""
    if p["spread_pct"] > CONFIG["max_spread_pct"]:
        return False, f"spread {p['spread_pct']*100:.0f}% of premium"
    oi = p["open_interest"]
    if oi is not None and oi < CONFIG["min_open_interest"]:
        return False, f"open interest {oi:.0f}"
    vol = p["volume"]
    if vol is not None and vol < CONFIG["min_volume"]:
        return False, "no trades today"
    age = p["quote_age_min"]
    if age is not None and age > CONFIG["max_quote_age_min"]:
        return False, f"quote {age:.0f} min old"
    return True, ""


# ---------------------------------------------------------------------------
# The smile's shape: SVI, fitted by Nelder-Mead
# ---------------------------------------------------------------------------

def smile_basis(k, m, s):
    """The shape a smile has: straight wings joined by a rounded belly.

        iv(k) = c0 + c1*d + c2*sqrt(d^2 + s^2) + c3*d^2 + c4*d^3,   d = k - m

    The square root is the hyperbola: far from m it goes linear, so each wing
    becomes a straight line, while near m it rounds off. The quadratic and
    cubic bend the belly, which a bare hyperbola cannot do well enough.

    This is SVI's idea applied to IV rather than total variance. Real SVI was
    tried first and pinned rho at +1.00 with b = 98, which was blamed on our
    strike window. Wrongly: the call wing turns up in total variance at 1.24
    expected moves and our band reaches 2.67, and fitting past the turn gives
    rho = -0.67, legal. The five-way search failed, not the data. Here only m
    and s are searched and the coefficients fall out of weighted least squares,
    which is why this one fits. See docs/measurements.md.

    Nothing here is arbitrage-aware, so the curve is only ever evaluated
    between the strikes it was fitted on. It is a reference shape, not a model
    for pricing something we did not observe.
    """
    d = k - m
    return [1.0, d, math.sqrt(d * d + s * s), d * d, d * d * d]


def nelder_mead(cost, start, step, iterations=3000):
    """Plain Nelder-Mead. SVI's parameters cannot be solved in one shot the way
    a polynomial's can, so they get searched for: a simplex of n+1 points
    crawls downhill by reflecting its worst corner through the others."""
    n = len(start)
    simplex = [list(start)]
    for i in range(n):
        p = list(start)
        p[i] += step[i]
        simplex.append(p)
    scores = [cost(p) for p in simplex]

    for _ in range(iterations):
        order = sorted(range(n + 1), key=lambda i: scores[i])
        simplex = [simplex[i] for i in order]
        scores = [scores[i] for i in order]
        if abs(scores[-1] - scores[0]) < 1e-14:
            break
        centroid = [sum(p[i] for p in simplex[:-1]) / n for i in range(n)]
        worst = simplex[-1]

        refl = [c + (c - w) for c, w in zip(centroid, worst)]
        fr = cost(refl)
        if fr < scores[0]:
            exp = [c + 2 * (c - w) for c, w in zip(centroid, worst)]
            fe = cost(exp)
            simplex[-1], scores[-1] = (exp, fe) if fe < fr else (refl, fr)
        elif fr < scores[-2]:
            simplex[-1], scores[-1] = refl, fr
        else:
            con = [c + 0.5 * (w - c) for c, w in zip(centroid, worst)]
            fc = cost(con)
            if fc < scores[-1]:
                simplex[-1], scores[-1] = con, fc
            else:
                for i in range(1, n + 1):
                    simplex[i] = [(s + b) / 2 for s, b in zip(simplex[i], simplex[0])]
                    scores[i] = cost(simplex[i])
    best = min(range(n + 1), key=lambda i: scores[i])
    return simplex[best], scores[best]


def solve_wls(rows, targets, weights):
    """Weighted least squares, by normal equations and Gaussian elimination.
    Small enough that a dependency would cost more than it saves."""
    n = len(rows[0])
    a = [[sum(w * r[i] * r[j] for r, w in zip(rows, weights)) for j in range(n)]
         + [sum(w * r[i] * t for r, t, w in zip(rows, targets, weights))] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-18:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r != col:
                f = a[r][col] / a[col][col]
                a[r] = [v - f * c for v, c in zip(a[r], a[col])]
    return [a[i][n] / a[i][i] for i in range(n)]


def fit_expiry(points):
    """Fit the readable points of one expiry. Returns (curve, used, dropped).

    Only the bottom's position m and its roundness s are searched; given those,
    the five coefficients are exact least squares. Weights are 1/band^2, so a
    tight at-the-money quote counts for far more than a penny-wide wing."""
    used = [p for p in points if p["readable"]]
    if len(used) < CONFIG["min_points"]:
        return None, used, len(points) - len(used)

    ks = [p["moneyness"] for p in used]
    ivs = [p["iv"] for p in used]
    weights = [1.0 / max(p["iv_band"], CONFIG["band_floor"]) ** 2 for p in used]

    def solve(m, s):
        rows = [smile_basis(k, m, max(s, 1e-4)) for k in ks]
        coef = solve_wls(rows, ivs, weights)
        if coef is None:
            return None, 1e12
        cost = sum(w * (sum(c * r for c, r in zip(coef, row)) - iv) ** 2
                   for row, iv, w in zip(rows, ivs, weights))
        return coef, cost

    best, best_cost = None, float("inf")
    for m0 in (-0.04, 0.0, 0.04):
        for s0 in (0.02, 0.06, 0.15):
            v, c = nelder_mead(lambda v: solve(v[0], v[1])[1], [m0, s0], [0.02, 0.02],
                               iterations=400)
            if c < best_cost:
                best, best_cost = v, c
    m, s = best[0], max(best[1], 1e-4)
    coef, _ = solve(m, s)
    if coef is None:
        return None, used, len(points) - len(used)

    def curve(k):
        return sum(c * r for c, r in zip(coef, smile_basis(k, m, s)))

    curve.params = {"m": round(m, 6), "s": round(s, 6),
                    **{f"c{i}": round(c, 6) for i, c in enumerate(coef)}}
    return curve, used, len(points) - len(used)


# ---------------------------------------------------------------------------
# Reading, scoring, writing
# ---------------------------------------------------------------------------

def load_points(folder):
    """One row per contract from vol.py, with the gates applied."""
    out = []
    with open(folder / "contracts.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p = {k: r[k] for k in ("symbol", "expiry", "right")}
            for k in ("dte", "sessions", "strike", "delta", "iv", "iv_bid", "iv_ask",
                      "iv_band", "vega", "forward", "spread_pct", "open_interest",
                      "volume", "quote_age_min"):
                p[k] = _f(r[k])
            p["moneyness"] = math.log(p["strike"] / p["forward"])
            p["readable"], why = readable(p)
            p["tradeable"], why_trade = (tradeable(p) if p["readable"] else (False, why))
            p["why_not"] = why or why_trade
            out.append(p)
    return out


def score(points, curve):
    """Everything each point gets from the fitted curve."""
    for p in points:
        fit = curve(p["moneyness"])
        p["fitted_iv"] = round(fit, 6)
        p["residual"] = round(p["iv"] - fit, 6)
        p["edge_at_bid"] = round(p["iv_bid"] - fit, 6)      # sell above the curve?
        p["edge_at_ask"] = round(fit - p["iv_ask"], 6)      # buy below it?


def analyse(folder):
    """Fit every expiry in a snapshot, score every point, write both files."""
    points = load_points(folder)
    by_expiry, fits, scored = {}, [], []
    for p in points:
        by_expiry.setdefault(p["expiry"], []).append(p)

    for expiry in sorted(by_expiry):
        group = by_expiry[expiry]
        curve, used, dropped = fit_expiry(group)
        if curve is None:
            continue
        score(group, curve)
        scored += group
        used.sort(key=lambda p: p["moneyness"])
        resid = [abs(p["residual"]) for p in used]
        atm = curve(0.0)                                    # the forward is ln = 0
        h = 0.01
        fits.append({
            "expiry": expiry, "dte": group[0]["dte"], "sessions": group[0]["sessions"],
            "forward": group[0]["forward"], "points_fitted": len(used),
            "points_dropped": dropped,
            "rms_vol_pts": round((sum(r * r for r in resid) / len(resid)) ** 0.5 * 100, 4),
            "worst_residual": round(max(resid) * 100, 4),
            "atm_fitted": round(atm, 6),
            "slope_at_atm": round((curve(h) - curve(-h)) / (2 * h), 4),
            "curvature": round((curve(h) - 2 * atm + curve(-h)) / (h * h), 2),
            "median_band": round(sorted(p["iv_band"] for p in used)[len(used) // 2] * 100, 4),
            # A good fit leaves residuals scattered, so their signs flip about
            # half the time. Long same-sign runs mean the shape is wrong, which
            # is how the cubic that came before this was caught.
            "sign_changes": sign_changes(used),
            **curve.params,
        })

    dest = OUT_DIR / folder.name
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(dest / "points.csv", scored, POINT_COLS)
    write_csv(dest / "fits.csv", fits, FIT_COLS)
    return fits, scored, dest


def sign_changes(used):
    """How often the residuals flip sign along the smile. Scatter gives about
    half the point count; a handful means the curve is the wrong shape."""
    signs = [p["residual"] > 0 for p in used]
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def report(folder, fits, points, dest):
    print(f"{folder.name}: fitted {len(fits)} expiries, scored {len(points):,} points\n")
    print(f"  {'expiry':<12}{'DTE':>4}{'fitted':>8}{'ATM fit':>9}{'RMS':>7}{'band':>7}"
          f"{'worst':>7}{'flips':>7}{'slope':>8}")
    for f in fits:
        print(f"  {f['expiry']:<12}{f['dte']:>4}{f['points_fitted']:>8}"
              f"{f['atm_fitted']*100:>8.2f}%{f['rms_vol_pts']:>7.3f}{f['median_band']:>7.3f}"
              f"{f['worst_residual']:>7.3f}{f['sign_changes']:>7}{f['slope_at_atm']:>8.2f}")

    sellable = [p for p in points if p["tradeable"] and p["edge_at_bid"] > 0]
    buyable = [p for p in points if p["tradeable"] and p["edge_at_ask"] > 0]
    print(f"\n  tradeable points that clear their own spread: "
          f"{len(sellable)} to sell, {len(buyable)} to buy, "
          f"of {sum(1 for p in points if p['tradeable']):,} tradeable")
    for label, group, key in (("sell above the curve", sellable, "edge_at_bid"),
                              ("buy below the curve", buyable, "edge_at_ask")):
        for p in sorted(group, key=lambda p: -p[key])[:5]:
            print(f"    {label:<22}{p['expiry']}  {p['strike']:>6g}{p['right']}  "
                  f"{p[key]*100:+.2f} pts  (band {p['iv_band']*100:.2f})")
    try:
        shown = dest.relative_to(ROOT)
    except ValueError:
        shown = dest
    print(f"\n  saved {shown}/")


def latest():
    runs = sorted(p for p in IV_DIR.glob("*") if (p / "contracts.csv").exists())
    if not runs:
        sys.exit(f"Nothing in {IV_DIR}. Run `python app.py iv` first.")
    return runs[-1]


def cmd_surface(which=None):
    folder = (IV_DIR / which) if which else latest()
    if not (folder / "contracts.csv").exists():
        sys.exit(f"No solved IVs at {folder}. Run `python app.py iv` first.")
    report(folder, *analyse(folder))
