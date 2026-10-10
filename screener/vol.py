"""
vol.py - solved IVs from a chain snapshot: bid/ask. Step 2 of the screener.

  python app.py iv                  the newest snapshot in data/chains/
  python app.py iv 2026-09-24_1142  a particular one

pricing.py is the math and holds no opinions. This file makes every choice:
which spot belongs to which quote, what the forward is, which side of a strike
to read, and what counts as time. Keeping the judgment here is what lets the
math be tested against a frozen reference to float noise.

PER EXPIRY, IN ORDER:

1. The forward, from put-call parity at the strikes whose call and put are
   quoted the same width. That is the market quoting its own forward, so no
   dividend needs guessing, and any mismatch between the recorded spot and the
   option mids is absorbed there instead of tilting every strike's IV.

   (In the
   ***Sep-25 straddle log that mismatch showed up as calls and puts disagreeing
   by up to 4 vol points. See docs/measurements.md.)***

   Every strike quoted on both sides implies a forward and they do not agree:
   up to 31 cents apart at 29 days, as a bias that tracks the pair's width
   asymmetry rather than as noise. So the pairs are gated on that asymmetry,
   the survivors averaged, and what they still disagree by is reported as
   `forward_error`. Nothing downstream treats the forward as exact.

2. One IV per strike, solved from the out-of-the-money side: puts below the
   forward, calls above. Those quotes are tighter, and it sidesteps the
   early-exercise premium in deep in-the-money American puts.

3. An IV band per strike, solved at the bid and at the ask, so the spread is
   carried in vol points rather than thrown away.

4. Our own Greeks at our own IV, so a strike called "25 delta" is 25 delta by
   our lens rather than the vendor's.

5. Reference points: IV at the forward, and IV at 25 and 10 delta each side.
   Those are what make expiries comparable with each other.

TWO CLOCKS
----------
Time to expiry for pricing is calendar days over 365, which is the clock the
model uses. Sessions are counted separately, because comparing expiries in
calendar time makes any expiry with a weekend in it look cheap (on 2026-09-24
the Sep-28 expiry quoted 10.33% against 12.99% three weeks out, and per
session it was 12.14% against 12.66%. Both go in the output.)

WHAT IT WRITES
--------------
data/iv/<snapshot>/contracts.csv  one row per strike we could read
data/iv/<snapshot>/expiries.csv   one row per expiry, the reference points

The snapshot itself is never touched, so improving anything here re-derives
the whole history from raw quotes.
"""

import csv
import datetime as dt
import math
import pathlib
import statistics
import sys
from zoneinfo import ZoneInfo

from . import pricing

CONFIG = {
    # Flat, and written into every output row so a later change can re-derive
    # history. A 30-day IV moves by well under a tenth of a point across any
    # plausible rate, and the chain cannot tell us the rate itself: fitting it
    # from parity returns nonsense, because American puts bend the line.
    # Subject to change when expiries greater than 1 month join the surface.
    "rate": 0.04,
    "delta_points": (0.25, 0.10),   # the reference points either side
    "min_bid": 0.005,               # no bid, no market, no IV
    "forward_pairs": 6,             # the evenest pairs the forward is read from
    "forward_max_asymmetry": 0.05,  # call spread minus put spread, past which the mid is biased
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAIN_DIR = ROOT / "data" / "chains"
IV_DIR = ROOT / "data" / "iv"
ET = ZoneInfo("America/New_York")

# NYSE closures. Only the next couple of years matter, since for now nothing here
# looks further than 30 days out, but an expiry past the last date gets a
# warning rather than a silently wrong session count.

HOLIDAYS = [dt.date(*d) for d in (
    (2026, 1, 1), (2026, 1, 19), (2026, 2, 16), (2026, 4, 3), (2026, 5, 25),
    (2026, 6, 19), (2026, 7, 3), (2026, 9, 7), (2026, 11, 26), (2026, 12, 25),
    (2027, 1, 1), (2027, 1, 18), (2027, 2, 15), (2027, 3, 26), (2027, 5, 31),
    (2027, 6, 18), (2027, 7, 5), (2027, 9, 6), (2027, 11, 25), (2027, 12, 24),
)]

CONTRACT_COLS = ["symbol", "expiry", "dte", "sessions", "strike", "right", "bid", "ask",
                 "mid", "spread", "spread_pct", "open_interest", "volume",
                 "quote_age_min", "iv", "iv_bid", "iv_ask", "iv_band", "delta", "gamma",
                 "theta", "vega", "vendor_iv", "iv_vs_vendor", "moves_from_forward",
                 "forward", "spot_used", "quote_time_et"]
EXPIRY_COLS = ["expiry", "dte", "days_to_expiry", "sessions", "forward", "forward_error",
               "forward_iv_cost", "forward_pairs", "forward_from_spot", "forward_gap",
               "atm_strike", "atm_iv", "atm_iv_per_session", "iv_25d_put", "iv_10d_put",
               "iv_25d_call", "iv_10d_call", "put_skew_25d", "call_skew_25d",
               "strikes_read", "median_iv_band", "median_vs_vendor", "rate"]


# ---------------------------------------------------------------------------
# Reading a snapshot
# ---------------------------------------------------------------------------

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load(folder):
    # The three files of a snapshot, plus the moment it started.
    options = read_rows(folder / "options.csv")
    spots = [s for s in read_rows(folder / "spot.csv") if _f(s.get("price"))]
    started = min((o["fetched_at"] for o in options), default=None)
    return options, spots, dt.datetime.fromisoformat(started)


def spot_at(quote_time, spots):

    """The SPY price recorded closest in time to this quote. SPY drifted 31
    cents during the Sep-24 pass; a week-out option solved against a price 30
    cents stale moves by about a third of a vol point."""

    when = _time(quote_time)
    if when is None:
        return _f(spots[0]["price"])
    best = min(spots, key=lambda s: abs((_time(s["quote_time_et"]) or _time(s["fetched_at"]))
                                        - when))
    return _f(best["price"])


def _time(v):
    try:
        return dt.datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def sessions_between(start, expiry):
    """Trading days from the day after `start` through `expiry`. Weekends and
    NYSE closures removed, which is what makes expiries comparable. (full days in time gives abnormal values)"""

    d, n = start + dt.timedelta(days=1), 0
    while d <= expiry:
        if d.weekday() < 5 and d not in HOLIDAYS:
            n += 1
        d += dt.timedelta(days=1)
    return n


# ---------------------------------------------------------------------------
# One expiry
# ---------------------------------------------------------------------------

def quotes_by_strike(rows):
    #{strike: {"C": row, "P": row}}, keeping only quotes with a real bid.
    out = {}
    for r in rows:
        bid, ask = _f(r.get("bid")), _f(r.get("ask"))
        if bid is None or ask is None or bid < CONFIG["min_bid"] or ask <= bid:
            continue
        out.setdefault(_f(r["strike"]), {})[r["right"]] = r
    return out


def mid(row):
    return (_f(row["bid"]) + _f(row["ask"])) / 2


def forward(by_strike, disc, want=None):
    """The forward, read from the pairs whose two legs are quoted evenly.

    Parity gives a forward at every strike quoted on both sides, and all of
    them should agree. Measured on the 2026-09-24 chain they do not: across the
    0.35-0.65 delta band the 29-day pairs spread 31 cents. That spread is a
    BIAS, not noise, which is what decides how to handle it. Three things say
    so:

      - it arrives as a slope in strike, one sign flip about the mean in 21
        steps, the same signature that failed the cubic smile
      - it tracks the pair's width asymmetry, call spread minus put spread, at
        +0.93 correlation, while total width predicts it at only -0.29
      - timing is not the cause: those 22 pairs were quoted inside two seconds
        of each other and SPY moved three cents across them

    The mechanism is that the in-the-money leg is quoted wider, because the
    market maker carries more premium and more direction on it, so its mid sits
    predictably off fair value. How deep a leg sits runs monotonically with
    strike, so the error tilts rather than scatters. Averaging cures noise and
    does nothing for a bias; what cures a bias is reading it where it vanishes,
    which is where the two legs are quoted the same width.

    So pairs must first pass an asymmetry gate, and only then are the tightest
    of them averaged, weighted 1/width^2 against the noise that is left. On a
    $1 strike grid five to twenty-four pairs pass and the averaging is real. On
    a coarse grid it can come down to one, which is honest rather than a
    regression to the old single-pair rule: `pairs` says how many were used and
    the error bar widens to that pair's own quote noise.

    `error` is the forward's error bar, the wider of what the used pairs
    disagree by and what the tightest of them can be read to. Nothing
    downstream may treat the forward as exact.
    """
    pairs = []
    for k, sides in by_strike.items():
        if "C" not in sides or "P" not in sides:
            continue
        call, put = sides["C"], sides["P"]
        cw, pw = _f(call["ask"]) - _f(call["bid"]), _f(put["ask"]) - _f(put["bid"])
        pairs.append({
            "strike": k,
            "width": cw + pw,
            "asymmetry": cw - pw,
            "mid_gap": abs(mid(call) - mid(put)),
            "forward": pricing.forward_from_parity(mid(call), mid(put), k, disc),
        })
    if not pairs:
        return None

    eligible = [p for p in pairs if abs(p["asymmetry"]) <= CONFIG["forward_max_asymmetry"]]
    if not eligible:
        # A grid too coarse to hold an even pair. Take the evenest there is and
        # let the error bar carry the damage.
        eligible = sorted(pairs, key=lambda p: abs(p["asymmetry"]))[:1]

    # tightest first, then nearest the money: among equally tight pairs the one
    # whose call and put agree is the one sitting closest to the forward.
    eligible.sort(key=lambda p: (p["width"], p["mid_gap"]))
    used = eligible[:max(1, want or CONFIG["forward_pairs"])]
    weights = [1.0 / max(p["width"], 0.01) ** 2 for p in used]
    F = sum(w * p["forward"] for w, p in zip(weights, used)) / sum(weights)

    reads = [p["forward"] for p in used]
    strikes = sorted(p["strike"] for p in used)
    # half the tightest pair's combined spread, in forward terms: the floor
    # under what any single reading can resolve.
    noise = (min(p["width"] for p in used) / 2) / disc
    return {
        "forward": F,
        "error": max(max(reads) - min(reads), noise),
        "spread": max(reads) - min(reads),
        "pairs": len(used),
        "eligible": len(eligible),
        "strikes": strikes,
        "brackets": strikes[0] <= F <= strikes[-1],
    }


def forward_iv_cost(contracts, F, spread, T, disc):
    """What the forward's error bar is worth in vol points, read at the strike
    nearest the money. This is the floor under every IV in the expiry: no
    strike can be known better than its forward is."""
    if not contracts or not spread:
        return None
    c = min(contracts, key=lambda c: abs(c["strike"] - F))
    if c.get("iv") is None:
        return None
    try:
        shifted = pricing.implied_vol(c["right"], c["mid"], F + spread, c["strike"], T, disc)
    except pricing.SolveError:
        return None
    return abs(shifted - c["iv"])


def quote_age(row):
    """Minutes between the quote's own timestamp and when we fetched it. A
    quote that has not moved while the market has is a ghost, whatever IV it
    implies."""

    then, now = _time(row.get("quote_time_et")), _time(row.get("fetched_at"))
    return round((now - then).total_seconds() / 60, 2) if then and now else None


def read_strike(row, right, strike, F, T, disc, spot):
    """One strike, translated: IV from the mid, the band from bid and ask, and
    our own Greeks at our own IV. Returns None when no IV exists, which is
    honest rather than a gap-filled guess.

    Liquidity comes along as plain facts: open interest, volume, the spread
    and its share of premium, and the quote's age. Nothing is judged here. The
    thresholds that decide what is worth trading belong to whatever reads this
    file, so changing one costs a re-read instead of a re-solve."""

    try:
        iv = pricing.implied_vol(right, mid(row), F, strike, T, disc)
        lo, hi = pricing.iv_band(right, _f(row["bid"]), _f(row["ask"]), F, strike, T, disc)
    except pricing.SolveError:
        return None
    g = pricing.bs(right, F, strike, T, iv, disc)

    vendor = _f(row.get("vendor_iv"))
    spread = _f(row["ask"]) - _f(row["bid"])
    return {
        "symbol": row["symbol"], "expiry": row["expiry"], "strike": strike, "right": right,
        "bid": _f(row["bid"]), "ask": _f(row["ask"]), "mid": round(mid(row), 4),
        "spread": round(spread, 4), "spread_pct": round(spread / mid(row), 4),
        "open_interest": _f(row.get("open_interest")), "volume": _f(row.get("volume")),
        "quote_age_min": quote_age(row),
        "iv": round(iv, 6), "iv_bid": round(lo, 6), "iv_ask": round(hi, 6),
        "iv_band": round(hi - lo, 6),
        "delta": round(g["delta"], 6), "gamma": round(g["gamma"], 6),
        "theta": round(g["theta"], 6), "vega": round(g["vega"], 6),
        "vendor_iv": vendor, "iv_vs_vendor": round(iv - vendor, 6) if vendor else None,
        "forward": round(F, 4), "spot_used": spot, "quote_time_et": row.get("quote_time_et"),
    }


def at_delta(contracts, right, target):
    """IV where |delta| equals target, interpolated along the smile. Delta is
    the market's own measurement for distance, so the same target means the same
    thing on every expiry and in any vol regime."""

    pts = sorted(((abs(c["delta"]), c["iv"]) for c in contracts if c["right"] == right),
                 key=lambda p: p[0])
    for (d0, iv0), (d1, iv1) in zip(pts, pts[1:]):
        if d0 <= target <= d1 and d1 > d0:
            return iv0 + (iv1 - iv0) * (target - d0) / (d1 - d0)
    return None


def at_strike(contracts, K):
    """IV at a strike we may not have, interpolated between the two either
    side. Used for the at-the-money point, which sits at the forward."""

    pts = sorted(((c["strike"], c["iv"]) for c in contracts), key=lambda p: p[0])
    for (k0, iv0), (k1, iv1) in zip(pts, pts[1:]):
        if k0 <= K <= k1 and k1 > k0:
            return iv0 + (iv1 - iv0) * (K - k0) / (k1 - k0)
    return None


def one_expiry(expiry, rows, spots, started, warnings):
    """Everything for a single expiry: the forward, every strike we can read,
    and the reference points that make it comparable with other expiries."""

    exp = dt.date.fromisoformat(expiry)
    asof = started.date()
    dte = (exp - asof).days
    if dte <= 0:
        return None, []
    
    # Actual time, not whole days: these options stop trading at 16:00 ET on
    # the expiry date. Counting Sep-25 as one day from a Wed 11:42 snapshot
    # instead of 1.18 put its IV 1.3 points too high; at 29 days the same
    # rounding is worth 0.04.

    close = dt.datetime.combine(exp, dt.time(16, 0), tzinfo=ET)
    T = (close - started).total_seconds() / (365 * 86400)
    disc = math.exp(-CONFIG["rate"] * T)
    by_strike = quotes_by_strike(rows)
    fwd = forward(by_strike, disc)
    if fwd is None:
        warnings.append(f"{expiry}: no strike with both a call and a put; skipped")
        return None, []
    F = fwd["forward"]
    atm_k = min(by_strike, key=lambda k: abs(k - F))
    if fwd["pairs"] > 1 and not fwd["brackets"]:   # one pair brackets nothing by construction
        warnings.append(f"{expiry}: the forward's pairs sit on one side of it "
                        f"({fwd['strikes'][0]:.0f}-{fwd['strikes'][-1]:.0f}, F {F:.2f}); "
                        f"extrapolated, not read")

    contracts = []
    for k, sides in sorted(by_strike.items()):
        right = "P" if k < F else "C"          # the out-of-the-money side
        if right not in sides:
            continue
        spot = spot_at(sides[right].get("quote_time_et"), spots)
        c = read_strike(sides[right], right, k, F, T, disc, spot)
        if c is not None:
            contracts.append(c)
    if len(contracts) < 3:
        warnings.append(f"{expiry}: only {len(contracts)} strikes readable; skipped")
        return None, []

    sessions = sessions_between(asof, exp)
    if exp > HOLIDAYS[-1]:
        warnings.append(f"{expiry}: past the holiday table, session count may be wrong")
    atm = at_strike(contracts, F)
    # one expected move, for reporting how far out each strike sits
    one_move = atm * math.sqrt(T) if atm else None
    for c in contracts:
        c["dte"], c["sessions"] = dte, sessions
        c["moves_from_forward"] = (round(math.log(c["strike"] / F) / one_move, 3)
                                   if one_move else None)

    p25, p10 = (at_delta(contracts, "P", d) for d in CONFIG["delta_points"])
    c25, c10 = (at_delta(contracts, "C", d) for d in CONFIG["delta_points"])
    gaps = [c["iv_vs_vendor"] for c in contracts if c["iv_vs_vendor"] is not None]
    row = {
        "expiry": expiry, "dte": dte, "days_to_expiry": round(T * 365, 3),
        "sessions": sessions,
        "forward": round(F, 4),
        "forward_error": round(fwd["error"], 4),
        "forward_iv_cost": _round(forward_iv_cost(contracts, F, fwd["error"], T, disc)),
        "forward_pairs": fwd["pairs"],
        "forward_from_spot": round(contracts[len(contracts) // 2]["spot_used"] / disc, 4),
        "atm_strike": atm_k, "atm_iv": round(atm, 6) if atm else None,
        "atm_iv_per_session": (round(atm * math.sqrt(T / (sessions / 252)), 6)
                               if atm and sessions else None),
        "iv_25d_put": _round(p25), "iv_10d_put": _round(p10),
        "iv_25d_call": _round(c25), "iv_10d_call": _round(c10),
        "put_skew_25d": _round(p25 - atm if p25 and atm else None),
        "call_skew_25d": _round(c25 - atm if c25 and atm else None),
        "strikes_read": len(contracts),
        "median_iv_band": round(statistics.median(c["iv_band"] for c in contracts), 6),
        "median_vs_vendor": round(statistics.median(gaps), 6) if gaps else None,
        "rate": CONFIG["rate"],
    }
    row["forward_gap"] = round(F - row["forward_from_spot"], 4)
    # The forward is meant to be the one thing we know better than the quotes.
    # When its own error bar outgrows the median quote band it has become the
    # dominant error in the expiry, and every IV in it inherits that.
    cost = row["forward_iv_cost"]
    if cost is not None and cost > row["median_iv_band"]:
        warnings.append(f"{expiry}: the forward is worth {cost * 100:.2f} vol points of "
                        f"uncertainty against a {row['median_iv_band'] * 100:.2f} median "
                        f"band; it is the largest error here, not the quotes")
    return row, contracts


def _round(v, places=6):
    return None if v is None else round(v, places)


# ---------------------------------------------------------------------------
# A whole snapshot
# ---------------------------------------------------------------------------

def analyse(folder):
    """Read a snapshot, write contracts.csv and expiries.csv into data/iv/,
    and return (expiries, contracts, warnings, destination)."""
    
    options, spots, started = load(folder)
    by_expiry = {}
    for r in options:
        by_expiry.setdefault(r["expiry"], []).append(r)

    warnings, expiries, contracts = [], [], []
    for expiry in sorted(by_expiry):
        row, cs = one_expiry(expiry, by_expiry[expiry], spots, started, warnings)
        if row:
            expiries.append(row)
            contracts += cs

    dest = IV_DIR / folder.name
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(dest / "contracts.csv", contracts, CONTRACT_COLS)
    write_csv(dest / "expiries.csv", expiries, EXPIRY_COLS)
    return expiries, contracts, warnings, dest


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def report(folder, expiries, contracts, warnings, dest):
    print(f"{folder.name}: {len(contracts):,} strikes read across {len(expiries)} expiries\n")
    print(f"  {'expiry':<12}{'DTE':>4}{'sess':>5}{'forward':>9}{'gap':>7}{'ATM':>8}"
          f"{'per sess':>10}{'25d put':>9}{'25d call':>10}{'band':>7}{'vs WB':>7}")
    for e in expiries:
        pct = lambda v: f"{v * 100:.2f}" if v is not None else "  -  "
        print(f"  {e['expiry']:<12}{e['dte']:>4}{e['sessions']:>5}{e['forward']:>9.2f}"
              f"{e['forward_gap']:>+7.2f}{pct(e['atm_iv']):>8}{pct(e['atm_iv_per_session']):>10}"
              f"{pct(e['iv_25d_put']):>9}{pct(e['iv_25d_call']):>10}"
              f"{pct(e['median_iv_band']):>7}{pct(e['median_vs_vendor']):>7}")
    try:
        shown = dest.relative_to(ROOT)
    except ValueError:
        shown = dest
    print(f"\n  saved {shown}/")
    for w in warnings:
        print(f"    ! {w}")


def latest():
    runs = sorted(p for p in CHAIN_DIR.glob("*") if (p / "options.csv").exists())
    if not runs:
        sys.exit(f"No snapshots in {CHAIN_DIR}. Run `python app.py snap` first.")
    return runs[-1]


def cmd_iv(which=None):
    folder = (CHAIN_DIR / which) if which else latest()
    if not (folder / "options.csv").exists():
        sys.exit(f"No snapshot at {folder}")
    report(folder, *analyse(folder))
