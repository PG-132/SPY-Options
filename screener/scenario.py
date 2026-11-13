"""
scenario.py - what a position would be worth, and what it would be exposed
to, if SPY, its IVs or the date were different. Built on steps 2 to 4.

  python app.py scenario pos.csv                    a grid on the newest snapshot
  python app.py scenario pos.csv 2026-11-05_1633    the same on a particular one
  python app.py scenario pos.csv --shift -2         the grid with every IV 2 points lower
  python app.py scenario pos.csv --sessions 1,5     the grid with the closes 1 and 5
                                                    sessions out added to its dates
  python app.py scenario pos.csv --path path.csv    P&L along a path, hedges and all

Everything before this measures a chain. This file asks a different question
of one: if spot were here, the IVs shifted this much and the date that, what
would these legs be worth and what would they be exposed to? It never asks
how likely any of that is. Every number it prints is a model output under the
rules below - a what-if, never a forecast, and never a sort key (README;
docs/specs/choose.md CHOOSE-002). The structure chooser and the UI that come
next call this rather than pricing anything themselves, so there is one set
of rules to argue with.

WHERE A POSITION STARTS
-----------------------
One snapshot, and only what the pipeline already measured on it. The spot is
the one the collector saw when it started, read through
`ledger.snapshot_spot` so the ledger and this start from the same price. The
forwards, the times and the IVs are vol.py's, on vol.py's own clock
(`vol.years_to_expiry`, the one function both call). So at the snapshot's own
spot and time every leg prices back to Black-Scholes at vol.py's IV for its
strike, its Greeks are the ones in contracts.csv, and a position where nothing
moves reads exactly zero. That is the first thing the tests check, because a
scenario engine that cannot give back the chain it was built on cannot be
trusted with anything it was not.

vol.py solves one IV per strike, from the out-of-the-money side. Under the
forward read from parity that IV prices both sides of the strike, so an
in-the-money leg uses it too: its Greeks match through parity, same gamma and
vega, delta one apart. A strike vol.py could not read takes the fitted curve's
value at its moneyness, inside the fitted range only, and is flagged `fit_iv`;
having no band of its own it carries the fit's RMS as one. Outside the fitted
range, or on an expiry with no fit, it is refused with the reason. A guess
there would be a number the chain never quoted. So is a strike the chain does
not list at all: the curve would happily price 733 on an expiry that lists 730
and 735, for a contract nobody can trade. (Both readings are A-017.)

THE RULES
---------
Every forward moves with spot and keeps today's carry rate:

    F' = F x (S'/S) x (S/F)^(1 - T'/T)

which is F x S'/S at the snapshot's own time and S' at expiry. Holding the
carry in dollars instead would put the forward's whole premium over spot
(about three dollars five weeks out) into the leg's last day as a jump
between the forward and the spot its intrinsic is read at.

Each strike keeps its IV as spot moves (sticky strike). Until 2026-11-12 the
smile slid along the fitted curve instead, each strike carrying its residual
to its new moneyness. On ALL FIVE large moves the snapshots then held, the
strike near the old spot moved the opposite way to what the slide predicted
- up on the drops, down on the rallies - and the slide showed a short
straddle making money on a 1% drop (docs/measurements.md 2026-11-11). So the
curve is read only at the start, for a strike vol.py could not read
(`fit_iv`). (Decided, owner 2026-11-11, replacing the 2026-11-06 slide.)

A point is three inputs, kept apart (owner, 2026-11-12): the date, the spot,
and each strike's IV on that date. The date is time passing: it sets time to
expiry and the forward's carry, and nothing else. The IV on the date is its
own input, built in steps: today's IV for the strike, carried to the date
along today's term structure (below), plus the response to the spot move,
plus any shift. "Fixed as spot moves" is not frozen in time.

The IV response. How much IV moves with spot is not known, only that a drop
raises it by more than a rally lowers it, so every grid point is priced
three times, under responses named for the IV change and never for the
outcome:

    none       no change
    moderate   +1.0 per 1% of SPY on a drop, -1.0 on a rally   } at 30 days
    large      +2.0 per 1% on a drop,        -1.5 on a rally   } to expiry

scaled to each leg by sqrt(30 / its days to expiry at the point), so one
response per expiry, the same for every strike on it. These are umbrella
figures the owner chose above what was measured, not a fit
(docs/measurements.md 2026-11-11; the rally figures widened 2026-11-12).
Which case hurts depends on the position - a bigger IV fall on a rally helps
a short straddle, a bigger rise on a drop hurts it - so the report names the
lowest and highest case at each point (`extremes`). The rates apply to the
whole move from the snapshot's spot, however many sessions it took (owner,
2026-11-12); VIX history says that is about right out to a week and
generous after. The scaling is provisional: it held within 12-25% across
7-36 days on four of the five moves and missed both ways under a week, so a
leg outside one to five weeks is flagged `tenor`, not capped. Not in the
band: IV moving against the usual way, or with no spot move at all;
--shift asks about those.

The date. Each expiry rolls along today's term structure, on the session
clock. Its remaining total variance is its total today less what the market
prices for the sessions that have passed: term.py's totals interpolated in
sessions by `term.constant_maturity`, with the origin added the way context.py
adds its front window, at minus the part of today's session still to run.
The whole smile is scaled by the new level over today's level, keeping its
shape:

    ratio = sqrt(remaining / T') / level

Because the clock is sessions, a weekend or a holiday costs no variance: a
leg's total variance on Sunday is what it was on Friday's close, though T'
is two days shorter and the IV quoted on it two days higher. Plain
Black-Scholes at constant IV would decay a weekend as three days. (Decided,
owner 2026-11-06.) Two cases have nothing to roll from and keep a constant
IV instead: a negative remainder, which is a calendar arbitrage in the term
structure (`negative_var`), and an expiry term.py left out - dropped by its
drop rule (A-015), or never fitted (`no_term`).

A scenario date is valued at that date's close (`prices.session_close`, 13:00
on a 1pm close). The snapshot's own date is the snapshot itself, so the first
column of every grid is "spot moves now" and its middle row reads zero. A leg
on its expiry is worth its intrinsic at that point's spot with zero Greeks,
flagged `expired`. It is settled in cash in this model, once: exercise into
shares is not followed, and after its expiry the leg keeps what it settled
at. On a path that is SPY at the step dated on the expiry, and a path that
skips that date is refused. A grid row holds one spot at every date, so a
leg that expired earlier in the row settled at that same spot. That is the
reading of every grid column after a front expiry: SPY moved there and
stayed, so a calendar's later columns assume the front leg settled at the
row's spot.

The IV shift, in vol points, is added to every leg after the time roll,
with the response. A selloff steepens skew; no rule here models that (the
response is one shift per expiry), so a change in skew is the user's to
enter this way, leg by leg if need be, never something assumed.

Hedges. SPY shares carry one share of delta each. E-nano S&P 500 futures
(NES) pay $0.50 per index point, and one SPY dollar is about ten index
points, so one contract carries about five shares of delta, not one:

    shares per contract = 0.50 x NES fill price / SPY spot

with both prices read from the trade rather than assuming the ratio is ten.
The fill carries the future's own premium over the index, and that premium is
part of how far the future moves when spot does. A broker shows a future's
delta as 1.0 per contract, in the future's own units. (Confirmed by the
owner, 2026-11-09.) A hedge leg has delta and nothing else.

A future has one price at a time, so every NES contract is marked to one
NES price: the latest fill's ratio to SPY, times SPY. P&L is $0.50 x
contracts x (that mark - the contract's entry), and delta is $0.50 x the net
contracts x the ratio. Converting each fill at its own ratio instead gives
every contract its own price: a contract bought at 7000 and sold at 7014,
both with SPY at 700, would leave 0.01 shares of delta behind and none of
the $7 it made. Between fills the ratio is held, not modelled.

Without trades along it, P&L at a point depends only on the point. A path
with hedge trades depends on how it got there: each trade's P&L runs from
the spot it was made at, or for NES from its fill.

ENTRY AND P&L
-------------
P&L is model value at the point minus model value at the start, so a scenario
where nothing moves reads zero. Entry is at mid (decided, owner 2026-11-06);
the far side - asks paid, bids received - is shown beside it, and so is each
leg's model start value minus its own mid. That gap is not folded into P&L.
On an out-of-the-money leg it is rounding, since its IV was solved from that
mid. On an in-the-money leg it is how far its own mid sits from parity with
the out-of-the-money side, which is exactly the bias vol.py's forward exists
to avoid; showing it separately keeps it from posing as P&L.

ERROR BARS
----------
Every leg is repriced at its strike's `iv_bid` and `iv_ask`, carried through
the same rules. Legs on one expiry and strike read one IV, so they are
taken together, at that strike's low IV and at its high one: +10 and -10 of
one call carry no range, and neither does a synthetic. The position's range
then adds up each strike's extremes. That assumes every strike errs the
worst way at once, which is the conservative read, the same one
vol.variance_swap takes with quote spreads. Between strikes that offset, a
spread or a calendar, the truth is narrower (A-017). At the start the range
is not zero: it says the position cannot be marked any closer than its
quotes. Hedges carry no range.

The smile rules are not arbitrage-aware, so at a point the strikes a
position holds can be priced into an arbitrage: a vertical above its width
or a butterfly below zero. That is flagged `arb`, with the largest breach in
the report, and never repaired (`bounds`).

FLAGS
-----
Short codes on every row, joined with ';'. `FLAGS` below says what each one
means; the report prints the ones that occurred.

WHAT IT DOES NOT KNOW
---------------------
- `pricing.bs` is European and SPY options are American. Scenarios push legs
  deep in the money, which is exactly where early exercise is worth most
  (docs/integrity.md item 2). Past 0.9 |delta| a leg is flagged `deep`; 0.9
  is a placeholder, not a measurement, until that item is.
- Expiries that close at 1pm are still priced to 16:00 (A-003, the deferred
  half). Only their last day or two are affected.
- The smile's shape is in question under stress. On the 2026-11-05 chain (VIX
  28) the fit ran long same-sign residuals from 11-12 out, though its RMS
  stayed inside the quote band (integrity.md item 4). A leg sliding along the
  curve inherits that misfit.
- The time roll is only as fine as the term structure. Where the drop rule
  removed expiries, the sessions between the survivors are interpolated.
- Theta is Black-Scholes theta, dollars per calendar day at the point's IV.
  The engine's own step from one date to the next runs on the session clock,
  so over a weekend the grid's P&L moves by less than three days of theta.

WHAT IT WRITES
--------------
data/scenario/<snapshot>/<position>/legs.csv   each leg at the start: IV and
                                               its source, entry at mid and
                                               far side, model minus mid
data/scenario/<snapshot>/<position>/grid.csv   one row per leg per point
                                               per IV response, and a
                                               `total` row for each
data/scenario/<snapshot>/<position>/path.csv   one row per path step, with
                                               --path instead of the grid

Every row of all three carries `inputs`, a fingerprint of the legs (fills
included) and the snapshot files they were priced from (`fingerprint`), and
every grid and path row also carries `report`, which adds that run's shift,
sessions and response rates, or its steps, so two reports that price
differently never share an id. The files
are hashed either side of the one place they are read, and a run whose data
changed in between (another `iv` or `surface` on the same snapshot) is
refused, so the fingerprint is of the data priced, not of whatever is on
disk by the time the run saves. A folder
holds one position on one set of inputs: a grid and a path priced from the
same ones stay side by side, whatever the shift or the steps, and a run
leaves out the other file when it was priced from anything else. The new set
is built in data/scenario/.work/ and swapped in whole (`publish`), so a save
that fails, a file held open by a spreadsheet included, leaves the last good
set exactly as it was: never the new legs beside an old grid. The work area
is out of every position's way: a position file named `pos.old.csv` keeps
its own results however often `pos.csv` runs (`work_area`). One run at a
time saves a given position on a given snapshot: a second that starts while
the first is saving is refused, since the two would share a work folder
(`held`).

Position CSV: kind,expiry,strike,right,qty,price. `kind` is option, shares or
nes; qty is signed (contracts, shares or futures); `price` is the fill for
hedge legs; on an option it is recorded as the fill, not used, since entry
is at mid (rule 4). A wholly blank row is skipped and a row
whose kind starts with # is a comment; any other row with no kind is refused,
since dropping it would quietly turn a spread into an outright. Every number
in either file is read strictly: blank means not given, and anything that is
not a finite number is refused, never read as zero. Option and NES quantities
are whole contracts; shares may be fractional. `--shift` is the grid's;
a path carries its own on each step, so the two together are refused. Path CSV:
date,spot,iv_shift,kind,qty,price,
the last three blank on a row with no trade. Nothing upstream is touched, and
this is not part of `daily`: it runs when asked.
"""

import contextlib
import csv
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import shutil
import statistics
import sys

if os.name == "nt":                       # the OS file lock behind `held`
    import msvcrt
else:
    import fcntl

from screener import context, ledger, prices, pricing, surface, term, vol

CONFIG = {
    # E-nano S&P 500 futures (NES) pay $0.50 per S&P 500 index point.
    # Sourced: NinjaTrader's E-nano contract specs, accessed 2026-11-06; CME
    # lists NES from 2026-08-24. A contract term, not a measurement. One NES
    # is converted to SPY shares at this times its fill over SPY spot, about
    # 5 (owner confirmed 2026-11-09; see the docstring, "Hedges").
    "nes_dollars_per_point": 0.50,
    # SPY options deliver 100 shares per contract.
    "contract_shares": 100,
    # Legs past this |delta| are flagged: European math on an American option
    # is least safe deep in the money (integrity.md item 2). A placeholder,
    # not a measurement, until that item's binomial check bounds the gap.
    "deep_delta": 0.9,
    # The default grid: this many expected moves of the position's front
    # expiry either side of spot, in steps of `grid_step`. A display choice
    # from the change record, not a measurement: it decides which points get
    # printed, never what any of them is worth.
    "grid_moves": 3.0,
    "grid_step": 0.5,
    # The lowest IV a shift may push a leg to: the IV solver's own floor in
    # pricing.implied_vol. Below it there is no volatility to price.
    "iv_floor": 1e-4,
    # A spread between held strikes priced outside its no-arbitrage bounds by
    # more than this, in $ a share, is flagged `arb` (see `bounds`). Half a
    # cent, under the one-cent quote tick: a display threshold, not a
    # measurement. It decides what is flagged, never what anything is worth.
    "arb_tolerance": 0.005,
    # The IV response to a spot move, in vol points per 1% of SPY move for a
    # leg `response_days` from expiry, as (on a drop, on a rally), scaled to
    # a leg with `days` left by sqrt(response_days / days). Umbrella figures
    # the owner chose above what was measured, not a fit: on the two drops
    # held the strike near spot rose +0.47 and +0.66 per 1% at about 30 days,
    # on the two rallies it fell -0.60 and -1.18 (docs/measurements.md
    # 2026-11-11; the rally figures widened 2026-11-12 to sit above both).
    "response": {"moderate": (1.0, -1.0), "large": (2.0, -1.5)},
    "response_days": 30.0,
    # The days to expiry over which sqrt(30/days) is being checked, one to
    # five weeks (owner, 2026-11-11). On four of five measured moves it held
    # within 12-25% across 7-36 days and missed both ways under 7, so a leg
    # outside this range is flagged `tenor` rather than capped.
    "response_checked_days": (7.0, 35.0),
}

# The IV responses every grid point is priced under, named for the IV change
# and never for the outcome: which one hurts depends on the position.
CASES = ("none", "moderate", "large")

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAIN_DIR = ROOT / "data" / "chains"
IV_DIR = ROOT / "data" / "iv"
SURFACE_DIR = ROOT / "data" / "surface"
OUT_DIR = ROOT / "data" / "scenario"
# Saves are staged in OUT_DIR/.work/<snapshot>/<position>/, out of the way of
# every position's results (see `work_area`).
WORK = ".work"

LEG_COLS = ["inputs", "leg", "kind", "expiry", "strike", "right", "qty", "price",
            "iv_source", "iv", "iv_bid", "iv_ask", "bid", "ask",
            "entry_mid", "entry_far", "model_start", "model_minus_mid",
            "shares_per_contract", "flags"]
GRID_COLS = ["snapshot", "position", "inputs", "report", "date", "sessions_passed", "spot", "moves",
             "move_pct", "iv_shift", "response", "iv_response", "leg", "days_left", "iv",
             "value", "value_low", "value_high",
             "pnl", "pnl_low", "pnl_high", "delta", "gamma", "theta", "vega",
             "flags"]
PATH_COLS = ["snapshot", "position", "inputs", "report", "step", "date", "sessions_passed", "spot",
             "iv_shift", "trade", "value", "pnl_position", "pnl_hedges", "pnl",
             "pnl_low", "pnl_high", "delta", "gamma", "theta", "vega", "flags"]

FLAGS = {
    "deep": "past 0.9 |delta|: a European price on an American option "
            "(integrity.md item 2; 0.9 is a placeholder)",
    "tenor": "days to expiry outside the one to five weeks the IV response's "
             "sqrt(30/days) scaling is being checked over: applied, not capped",
    "fit_iv": "the strike had no IV of its own: read off the fitted curve, "
              "with the fit's RMS as its band",
    "no_term": "the expiry is not in the term structure (dropped, or not "
               "fitted): constant IV as the date moves",
    "negative_var": "remaining variance came out negative, a calendar "
                    "arbitrage: constant IV as the date moves",
    "iv_floor": "the IV shift pushed the leg to the floor of 0.01 vol points",
    "expired": "on or past expiry: settled in cash at intrinsic on its expiry date "
               "(on a grid row, the row's spot), zero Greeks",
    "no_quote": "no bid and ask of its own in the snapshot: entry cost unknown",
    "arb": "the strikes the position holds on one expiry are priced into an "
           "arbitrage here: a vertical between two of them below zero or above "
           "its discounted width, or a butterfly across three below zero. "
           "Flagged, not repaired: the smile rules are not arbitrage-aware",
}

GREEKS = ("delta", "gamma", "theta", "vega")


class Refused(ValueError):
    """A position, path or point the engine will not price, with every
    reason. Refusing is the honest answer where the alternative is a number
    the chain never quoted."""

    def __init__(self, reasons):
        self.reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        super().__init__("; ".join(self.reasons))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _positive(v):
    """A price the engine can use: a finite number above zero."""
    return v is not None and math.isfinite(v) and v > 0


def _whole(v):
    """Option and NES quantities trade in whole contracts."""
    return v is not None and math.isfinite(v) and float(v).is_integer()


def _numbers(raw, keys, where, problems):
    """The numeric cells of one row of a position or path file, strictly:
    blank is None (not given), a finite number is used, and anything else is
    a problem, never a zero. Returns the values and the cells that failed.

    `_f` alone turns a typo into None, and `or 0.0` then turned it into zero:
    an IV shift of "typo" ran as no shift, and "nan" as NaN all the way to
    the P&L."""
    values, bad = {}, set()
    for key in keys:
        text = str(raw.get(key) or "").strip()
        v = _f(text) if text else None
        if text and (v is None or not math.isfinite(v)):
            problems.append(f"{where}: {key} {text!r} is not a number")
            bad.add(key)
            v = None
        values[key] = v
    return values, bad


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _key(strike):
    return round(float(strike), 4)


# ---------------------------------------------------------------------------
# One snapshot, as the pipeline left it
# ---------------------------------------------------------------------------

def load(snapshot):
    """Everything the rules need from one snapshot, read rather than re-derived.

    Raw quotes and the start time come from the chain itself through vol.load,
    so the clock starts where vol.py's did. Forwards and IVs come from
    data/iv, the fits and their ranges from data/surface, and the term
    structure from term.load, which reads both. Nothing here is solved
    again."""
    options, spots, started = vol.load(CHAIN_DIR / snapshot)
    spot = ledger.snapshot_spot(snapshot)
    if not _positive(spot):
        # Missing, or not a usable price ("NaN" parses as a float, and would
        # make every number downstream NaN): the median of what spot.csv
        # recorded instead, counting only real prices.
        seen = [_f(s.get("price")) for s in spots if _positive(_f(s.get("price")))]
        spot = statistics.median(seen) if seen else None
    if not _positive(spot):
        raise Refused(f"{snapshot}: no usable spot recorded, in run.json or spot.csv")

    expiries = {}
    for r in read_rows(IV_DIR / snapshot / "expiries.csv"):
        exp = dt.date.fromisoformat(r["expiry"])
        T = vol.years_to_expiry(exp, started)
        expiries[r["expiry"]] = {
            "date": exp, "forward": _f(r["forward"]), "T": T,
            "disc": math.exp(-vol.CONFIG["rate"] * T),
            "atm_iv": _f(r.get("atm_iv")), "fit": None, "range": None, "rms": None,
        }
    for r in read_rows(SURFACE_DIR / snapshot / "fits.csv"):
        e = expiries.get(r["expiry"])
        if e is None:
            continue
        e["fit"] = (_f(r["m"]), _f(r["s"]), [_f(r[f"c{i}"]) for i in range(5)])
        e["rms"] = (_f(r.get("rms_vol_pts")) or 0.0) / 100.0
    # The fitted range is where the curve was fitted, and so the only place
    # it may be read: the min and max moneyness of each expiry's readable
    # points.
    for r in read_rows(SURFACE_DIR / snapshot / "points.csv"):
        e = expiries.get(r["expiry"])
        k = _f(r.get("moneyness"))
        if e is None or k is None or r.get("readable") != "True":
            continue
        lo, hi = e["range"] or (k, k)
        e["range"] = (min(lo, k), max(hi, k))
    for e in expiries.values():
        if e["fit"] and e["range"] is None:
            e["fit"] = None                  # a curve with no range has nowhere to be read

    contracts = {}
    for r in read_rows(IV_DIR / snapshot / "contracts.csv"):
        row = {k: _f(r.get(k)) for k in ("strike", "iv", "iv_bid", "iv_ask", "delta",
                                          "gamma", "theta", "vega")}
        row["right"] = r["right"]
        contracts[(r["expiry"], _key(r["strike"]))] = row

    # Every leg's own bid and ask, unfiltered: a far wing bid at zero is
    # still the price a seller there would get. `listed` is every contract
    # the chain holds at all, quoted or not.
    quotes, listed = {}, set()
    for o in options:
        if _f(o.get("strike")) is None:
            continue
        key = (o["expiry"], _key(o["strike"]), o["right"].upper()[:1])
        listed.add(key)
        bid, ask = _f(o.get("bid")), _f(o.get("ask"))
        if bid is not None and ask is not None:
            quotes[key] = (bid, ask)

    rows, dropped = term.load(snapshot)
    remaining = context.session_remaining(snapshot)
    # The session clock with the snapshot at zero: context.with_spot puts the
    # origin at minus the part of today still to run, so shifting by that
    # much makes "sessions passed since the snapshot" the coordinate.
    clock = [dict(r, sessions=r["sessions"] + remaining)
             for r in context.with_spot(rows, remaining)]
    return {
        "snapshot": snapshot, "started": started, "date": started.date(),
        "spot": spot, "expiries": expiries, "contracts": contracts,
        "quotes": quotes, "listed": listed, "term": {r["expiry"]: r for r in rows},
        "dropped": [d[0] for d in dropped], "remaining": remaining, "clock": clock,
    }


def curve(fit, k):
    """surface.py's fitted smile at log-moneyness k. The basis is surface's
    own, so the curve here is the curve there."""
    m, s, coef = fit
    return sum(c * b for c, b in zip(coef, surface.smile_basis(k, m, s)))


# ---------------------------------------------------------------------------
# Legs
# ---------------------------------------------------------------------------

def build_legs(ctx, rows):
    """Every leg of a position, resolved against the snapshot. All the
    problems are collected before refusing, so one run says everything that
    is wrong with the file rather than the first thing."""
    legs, problems = [], []
    for i, raw in enumerate(rows, 1):
        kind = (raw.get("kind") or "").strip().lower()
        if kind.startswith("#") or not any((v or "").strip() for v in raw.values()
                                            if isinstance(v, str)):
            continue                              # a comment, or a wholly blank row
        if not kind:
            # Anything else without a kind is a leg nobody named: skipping it
            # would turn a straddle into a call without a word.
            problems.append(f"row {i}: kind is blank but the row is not; it must "
                            f"be option, shares or nes (or start with # to leave "
                            f"it out)")
            continue
        nums, bad = _numbers(raw, ("strike", "qty", "price"), f"row {i}", problems)
        if bad:
            continue
        try:
            if kind == "option":
                legs.append(option_leg(ctx, raw))
            elif kind in ("shares", "nes"):
                legs.append(hedge_leg(kind, nums["qty"], nums["price"], ctx["spot"]))
            else:
                raise Refused(f"kind {kind!r} is not option, shares or nes")
        except Refused as e:
            problems += [f"row {i}: {r}" for r in e.reasons]
    if problems:
        raise Refused(problems)
    if not legs:
        raise Refused("the position has no legs")
    share_nes_mark(legs, ctx["spot"])
    return legs


def option_leg(ctx, raw):
    """One option leg at the start: its IV and band, where they came from,
    its value on vol.py's terms, and its own quotes."""
    expiry = (raw.get("expiry") or "").strip()
    K, qty = _f(raw.get("strike")), _f(raw.get("qty"))
    # The fill, if the row logs one. Entry is still at mid (rule 4), so it
    # does not move a number, but it is part of which trade this is: it shows
    # in legs.csv and in the position's fingerprint.
    fill = _f(raw.get("price"))
    right = (raw.get("right") or "").strip().upper()[:1]
    if not qty:
        raise Refused(f"{expiry} {raw.get('strike')}: qty missing or zero")
    if fill is not None and fill <= 0:
        raise Refused(f"{expiry} {raw.get('strike')}: a fill of {fill:g} is not a price")
    if not _whole(qty):
        raise Refused(f"{expiry} {raw.get('strike')}: {qty:g} contracts; options "
                      f"trade in whole contracts")
    if K is None or K <= 0 or right not in ("C", "P"):
        raise Refused(f"{expiry}: needs a strike and a right of C or P")
    e = ctx["expiries"].get(expiry)
    if e is None:
        raise Refused(f"{K:g}{right} {expiry}: vol.py read no such expiry in "
                      f"{ctx['snapshot']}")
    if (expiry, _key(K), right) not in ctx["listed"]:
        # Not a strike vol.py failed to read: a contract the chain does not
        # hold. The curve could put a number on it, for something nobody can
        # trade (the 12-04 expiry lists 730 and 735, not 733).
        raise Refused(f"{K:g}{right} {expiry}: not in this snapshot's chain, "
                      f"so there is nothing to price")
    F, T = e["forward"], e["T"]
    k0 = math.log(K / F)
    flags = set()
    c = ctx["contracts"].get((expiry, _key(K)))
    if c and c["iv"] is not None:
        ivs, source = (c["iv_bid"], c["iv"], c["iv_ask"]), "vol"
    elif e["fit"] and e["range"][0] <= k0 <= e["range"][1]:
        iv = curve(e["fit"], k0)
        ivs, source = (iv - e["rms"], iv, iv + e["rms"]), "fit"
        flags.add("fit_iv")
    else:
        why = ("no smile was fitted to this expiry" if not e["fit"] else
               f"its moneyness {k0:+.4f} sits outside the fitted range "
               f"{e['range'][0]:+.4f} to {e['range'][1]:+.4f}")
        raise Refused(f"{K:g}{right} {expiry}: vol.py read no IV at this strike, "
                      f"and {why}")

    mult = qty * CONFIG["contract_shares"]
    start = pricing.bs(right, F, K, T, ivs[1], e["disc"])
    bid, ask = ctx["quotes"].get((expiry, _key(K), right), (None, None))
    if bid is None or ask is None:
        flags.add("no_quote")
        entry_mid = entry_far = None
    else:
        entry_mid = mult * (bid + ask) / 2
        entry_far = mult * (ask if qty > 0 else bid)
    return {
        "kind": "option", "label": f"{qty:+g} {expiry} {K:g}{right}",
        "expiry": expiry, "date": e["date"], "strike": K, "right": right,
        "qty": qty, "price": fill, "ivs": ivs, "source": source,
        "k0": k0, "flags": flags, "bid": bid, "ask": ask,
        "entry_mid": entry_mid, "entry_far": entry_far,
        "start_value": mult * start["price"], "per": None,
    }


def hedge_leg(kind, qty, price, spot):
    """SPY shares or NES futures, entered at `spot`. Delta only.

    `spot` is the SPY price at the trade: the snapshot's for a leg in the
    position file, the step's own for a trade along a path. An NES leg needs
    its fill, since the conversion reads it; a share leg's fill is optional
    and, if given, shows as its entry beside the P&L rather than in it, the
    way an option's mid does.

    An NES leg carries its fill as `entry_mark`, the NES price its P&L runs
    from, and its fill over SPY as `ratio`. That ratio is only its own until
    a later fill replaces it: every NES contract is marked to one NES price
    (see `share_nes_mark` and `run_path`)."""
    if not qty:
        raise Refused(f"{kind}: qty missing or zero")
    if kind == "nes" and not _whole(qty):
        # Shares may be fractional (brokers sell them); a future may not.
        raise Refused(f"nes: {qty:g} contracts; futures trade in whole contracts")
    nes = {}
    if kind == "nes":
        if not price or price <= 0:
            raise Refused("an NES leg needs its fill price: the conversion to "
                          "SPY shares is read from it")
        per = CONFIG["nes_dollars_per_point"] * price / spot
        label = f"{qty:+g} NES @ {price:g}"
        start_value = entry = None
        nes = {"ratio": price / spot, "entry_mark": price}
    else:
        per = 1.0
        label = f"{qty:+g} SPY"
        start_value = qty * spot
        entry = qty * (price if price else spot)
    return {
        "kind": kind, "label": label, "qty": qty, "price": price, "spot": spot,
        "per": per, "flags": set(), "source": None, "ivs": None,
        "expiry": None, "strike": None, "right": None, "bid": None, "ask": None,
        "entry_mid": entry, "entry_far": entry,
        "start_value": start_value if start_value is not None else 0.0, **nes,
    }


def share_nes_mark(legs, spot):
    """Mark every NES leg of a position to one NES price.

    A future has one price at a time. Converting each fill at its own ratio
    to SPY gives each contract its own price instead: buy one at 7000 and
    sell it at 7014, both with SPY at 700, and the two read 5.00 and 5.01
    shares, leaving 0.01 shares of delta in a flat position and none of the
    $7 the round trip made. So the ratio is the latest fill's, the last NES
    row of the file, and every leg's P&L runs from the mark at the snapshot.
    What a leg's own fill made or lost before that shows beside the P&L, as
    its `model_minus_mid`, the way an option's mid does."""
    nes = [l for l in legs if l["kind"] == "nes"]
    if not nes:
        return
    ratio = nes[-1]["price"] / spot
    for l in nes:
        l["ratio"] = ratio
        l["entry_mark"] = ratio * spot
        l["per"] = CONFIG["nes_dollars_per_point"] * ratio


# ---------------------------------------------------------------------------
# Points
# ---------------------------------------------------------------------------

def point(ctx, date, spot, shift=0.0, case="none"):
    """A scenario point: a date, a spot, a parallel IV shift in vol points,
    and which IV response to the spot move to price under (`CASES`).

    The snapshot's own date means the snapshot itself; any later date means
    that date's close. `passed` is the variance clock from the snapshot,
    which is what the time roll is read on. `nes_ratio` is the NES price over
    SPY at this point; a path sets it from its latest NES fill, and left as
    None the legs' own shared ratio is used. `settled` maps an expiry date
    already passed to SPY's price on it, which is what a leg expiring then
    settled at; a path fills it, and an expiry missing from it settles at
    this point's own spot, which is right on a grid row and nowhere else."""
    if date < ctx["date"]:
        raise Refused(f"{date} is before the snapshot ({ctx['date']})")
    # The files are checked as they are read, but this is also the door the
    # chooser and the UI come through, where NaN would price to NaN and an
    # infinite spot fail deep inside the model.
    if not _positive(spot):
        raise Refused(f"{date}: spot must be a finite positive price, not {spot}")
    shift = 0.0 if shift is None else shift
    if not math.isfinite(shift):
        raise Refused(f"{date}: the IV shift {shift} is not a number")
    if case not in CASES:
        raise Refused(f"{date}: no IV response called {case!r}; the cases are "
                      f"{', '.join(CASES)}")
    start = date == ctx["date"]
    when = (ctx["started"] if start else
            dt.datetime.combine(date, prices.session_close(date), tzinfo=vol.ET))
    passed = 0.0 if start else vol.sessions_between(ctx["date"], date) + ctx["remaining"]
    return {"date": date, "spot": spot, "shift": shift, "case": case, "start": start,
            "when": when, "passed": passed, "nes_ratio": None, "settled": {}}


def response(moved, days, case):
    """The IV response, in vol points, to SPY moving by the ratio `moved`
    (scenario spot over the snapshot's) for a leg `days` from expiry.

    rate x the move in percent x sqrt(30 / days), with the rate for a drop
    or a rally from CONFIG["response"]. The move is the whole move from the
    snapshot's spot, however many sessions it took to get there: the
    horizon does not enter, only the days the leg has left (owner,
    2026-11-12). Zero under `none` and at an unchanged spot."""
    if case == "none" or moved == 1.0:
        return 0.0
    down, up = CONFIG["response"][case]
    rate = down if moved < 1.0 else up
    return rate * 100.0 * abs(moved - 1.0) * math.sqrt(CONFIG["response_days"] / days)


def remaining_variance(ctx, expiry, passed):
    """An expiry's total variance still to come after `passed` sessions: its
    total today minus the total the term structure prices out to there. None
    when the expiry is not in the term structure."""
    row = ctx["term"].get(expiry)
    if row is None:
        return None
    if passed <= 0:
        gone = 0.0
    else:
        cm = term.constant_maturity(ctx["clock"], passed)
        if cm is None:
            return None
        gone = cm["total_var"]
    return row["total_var"] - gone


def roll(ctx, expiry, T1, passed):
    """(ratio, flag): how much the expiry's smile scales by at a later date.
    The new level is what the remaining variance is worth over the time left;
    the ratio is that over today's level."""
    rem = remaining_variance(ctx, expiry, passed)
    if rem is None:
        return 1.0, "no_term"
    if rem <= 0:
        return 1.0, "negative_var"
    return math.sqrt(rem / T1) / ctx["term"][expiry]["level"], None


def price_leg(ctx, leg, pt):
    """One leg at one point: value at the leg's IV and at each end of its
    band, and Greeks, all for the whole leg (quantity and multiplier in)."""
    S0, S1 = ctx["spot"], pt["spot"]
    if leg["kind"] != "option":
        if leg["kind"] == "shares":
            value, delta = leg["qty"] * S1, leg["qty"]
        else:
            # One NES price at this point, the same for every contract:
            # P&L from each contract's own entry, delta from the net.
            ratio = pt.get("nes_ratio") or leg["ratio"]
            dollars = CONFIG["nes_dollars_per_point"] * leg["qty"]
            value = dollars * (ratio * S1 - leg["entry_mark"])
            delta = dollars * ratio
        out = {"iv": None, "iv_response": None, "days_left": None,
               "value": value, "value_low": value, "value_high": value,
               "values": [value] * 3,
               "delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "flags": set()}
        return out

    mult = leg["qty"] * CONFIG["contract_shares"]
    flags = set(leg["flags"])
    if pt["date"] >= leg["date"]:
        # Settled in cash at SPY's price on its expiry date, once. Past that
        # date the value is what it settled at, not intrinsic at today's
        # spot: an expired 600 call settled at 605 is $500, whatever SPY
        # does next. A path supplies that spot; with none (a grid row, where
        # spot is the same at every date) it is the point's own.
        K = leg["strike"]
        at = S1
        if pt["date"] > leg["date"]:
            at = pt["settled"].get(leg["date"], S1)
        intrinsic = max(0.0, at - K) if leg["right"] == "C" else max(0.0, K - at)
        flags.add("expired")
        v = mult * intrinsic
        return {"iv": None, "iv_response": None, "days_left": 0.0,
                "value": v, "value_low": v, "value_high": v, "values": [v] * 3,
                "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "flags": flags}

    e = ctx["expiries"][leg["expiry"]]
    F0, T0 = e["forward"], e["T"]
    T1 = T0 if pt["start"] else vol.years_to_expiry(leg["date"], pt["when"])
    F1 = F0 * (S1 / S0) * (S0 / F0) ** (1.0 - T1 / T0)
    disc1 = math.exp(-vol.CONFIG["rate"] * T1)

    # The strike keeps its IV as spot moves; the date carries it along the
    # term structure; the response to the spot move and any shift go on top.
    ratio = 1.0
    if not pt["start"]:
        ratio, why = roll(ctx, leg["expiry"], T1, pt["passed"])
        if why:
            flags.add(why)
    days = T1 * 365.0
    resp = response(S1 / S0, days, pt.get("case", "none"))
    lo, hi = CONFIG["response_checked_days"]
    if resp and not lo <= days <= hi:
        flags.add("tenor")

    ivs = []
    for iv in leg["ivs"]:
        v = iv * ratio + (resp + pt["shift"]) / 100.0
        if v < CONFIG["iv_floor"]:
            v = CONFIG["iv_floor"]
            flags.add("iv_floor")
        ivs.append(v)
    priced = [pricing.bs(leg["right"], F1, leg["strike"], T1, v, disc1) for v in ivs]
    values = [mult * p["price"] for p in priced]
    mid = priced[1]
    if abs(mid["delta"]) > CONFIG["deep_delta"]:
        flags.add("deep")
    # The call at this strike, per share, for `bounds`: a put's through
    # parity, which holds exactly here since both rights share F1 and the IV.
    call = mid["price"] + (disc1 * (F1 - leg["strike"]) if leg["right"] == "P" else 0.0)
    out = {"iv": ivs[1], "iv_response": resp, "days_left": days, "forward": F1,
           "value": values[1], "value_low": min(values),
           "value_high": max(values), "values": values, "call": call, "disc": disc1,
           "flags": flags}
    for g in GREEKS:
        out[g] = mult * mid[g]
    return out


def price_point(ctx, legs, pt):
    """Every leg at one point, and the position: values, P&L against the
    start, Greeks, the flags any leg raised, and `arb`, the worst spread
    between its strikes priced outside its bounds (None if none).

    The position's range adds each strike's extremes, not each leg's. Legs
    on one expiry and strike read one IV - vol.py solves one per strike, for
    both rights - so they err together: +10 and -10 of one call are worth
    nothing at any IV, where adding each leg's own extremes read -$10 to +$10
    on the Nov-20 750C of 2026-11-10_1540. Between strikes the extremes are
    still added, as though each strike errs the worst way at once (A-017)."""
    rows = []
    for leg in legs:
        r = price_leg(ctx, leg, pt)
        for k in ("", "_low", "_high"):
            r["pnl" + k] = r["value" + k] - leg["start_value"]
        rows.append(r)
    total = {k: sum(r[k] for r in rows) for k in ("value", "pnl") + GREEKS}
    draws = {}
    for i, (leg, r) in enumerate(zip(legs, rows)):
        key = (leg["expiry"], leg["strike"]) if leg["kind"] == "option" else i
        acc = draws.setdefault(key, {"values": [0.0, 0.0, 0.0], "start": 0.0})
        acc["values"] = [a + v for a, v in zip(acc["values"], r["values"])]
        acc["start"] += leg["start_value"]
    total["value_low"] = sum(min(d["values"]) for d in draws.values())
    total["value_high"] = sum(max(d["values"]) for d in draws.values())
    total["pnl_low"] = sum(min(d["values"]) - d["start"] for d in draws.values())
    total["pnl_high"] = sum(max(d["values"]) - d["start"] for d in draws.values())
    worst, hit = bounds(legs, rows)
    for leg, r in zip(legs, rows):
        if leg["kind"] == "option" and (leg["expiry"], leg["strike"]) in hit:
            r["flags"].add("arb")
    total["flags"] = set().union(*(r["flags"] for r in rows))
    total["arb"] = worst
    return rows, total


def bounds(legs, rows):
    """(worst, hit): whether the prices this point gives the strikes a
    position holds, expiry by expiry, admit an arbitrage.

    A call vertical is worth between nothing and its width discounted, and a
    call butterfly is worth something; on a smile that is not arbitrage-free
    neither holds. The quotes themselves can break them by a little, and
    while the smile slid along surface.py's fit (until 2026-11-12) a
    scenario priced a $5 vertical above $500 and a butterfly below zero. A
    read-only scan of every 5-wide call vertical and butterfly on the 16
    snapshots held on 2026-11-11, at whole expected moves out to three on
    each snapshot's own date: with the slide, 1.8% of verticals and 4.6% of
    butterflies broke their bounds after a move, worst $513.32 and -$56.51;
    with each strike's IV held, 7 of 146,880 verticals and 2.3% of
    butterflies, all but 2 inside their own quote bands; at the start 2 of
    24,480 and 4.3%, by at most 2 cents a share. A response that differs
    between expiries can still break a calendar's bound, which is not
    checked here. So the strikes are checked, each neighbouring pair and
    triple, and flagged `arb` beyond `arb_tolerance`, never repaired: a
    repair would be another rule for the smile. Expired legs are intrinsic,
    which cannot break these. `worst` is the largest breach, in $ a share
    (a butterfly's scaled to its narrower wing), with where it was."""
    held = {}
    for leg, r in zip(legs, rows):
        if leg["kind"] == "option" and "call" in r:
            held.setdefault(leg["expiry"], {})[leg["strike"]] = (r["call"], r["disc"])
    worst, hit, tol = None, set(), CONFIG["arb_tolerance"]
    for expiry, at in held.items():
        ks = sorted(at)
        c = [at[k][0] for k in ks]
        disc = at[ks[0]][1]
        found = []
        for i in range(len(ks) - 1):
            width, spread = ks[i + 1] - ks[i], c[i] - c[i + 1]
            found.append((max(-spread, spread - disc * width), "vertical", ks[i:i + 2]))
        for i in range(len(ks) - 2):
            w1, w2 = ks[i + 1] - ks[i], ks[i + 2] - ks[i + 1]
            s1, s2 = (c[i] - c[i + 1]) / w1, (c[i + 1] - c[i + 2]) / w2
            found.append(((s2 - s1) * min(w1, w2), "butterfly", ks[i:i + 3]))
        for size, spread, strikes in found:
            if size <= tol:
                continue
            hit |= {(expiry, k) for k in strikes}
            if worst is None or size > worst["size"]:
                worst = {"size": size, "spread": spread, "expiry": expiry,
                         "strikes": strikes}
    return worst, hit


# ---------------------------------------------------------------------------
# The grid and the path
# ---------------------------------------------------------------------------

def previous_session(d):
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5 or d in vol.HOLIDAYS:
        d -= dt.timedelta(days=1)
    return d


def sessions_after(d, n):
    """The date `n` trading sessions after `d`: weekends and NYSE closures
    skipped, a 1pm close counted as a day you can be at."""
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d not in vol.HOLIDAYS:
            n -= 1
    return d


def parse_sessions(text):
    """`--sessions 1,5`: whole numbers of sessions after the snapshot, each
    one a grid date. Refused unless every one is a positive whole number."""
    if text is None or text == "" or text == ():
        return ()
    items = text if isinstance(text, (list, tuple)) else str(text).split(",")
    out, bad = [], []
    for item in items:
        n = _f(str(item).strip())
        if n is None or not math.isfinite(n) or n <= 0 or not _whole(n):
            bad.append(str(item).strip())
        else:
            out.append(int(n))
    if bad:
        raise Refused(f"--sessions takes positive whole numbers of sessions after "
                      f"the snapshot, comma-separated; not {', '.join(map(repr, bad))}")
    return tuple(sorted(set(out)))


def grid_dates(ctx, legs, sessions=()):
    """The snapshot itself, each expiry in the position, the session before
    the last one, where a calendar's back leg is all that is left, and the
    close `n` sessions after the snapshot for each n in `sessions`: the
    horizon asked for, separate from any leg's days to expiry."""
    exps = sorted({l["date"] for l in legs if l["kind"] == "option"})
    dates = {ctx["date"]} | set(exps)
    if exps:
        d = previous_session(exps[-1])
        if d > ctx["date"]:
            dates.add(d)
    dates |= {sessions_after(ctx["date"], n) for n in parse_sessions(sessions)}
    return sorted(dates)


def grid_spots(ctx, legs):
    """Spot at whole and half expected moves of the position's front expiry,
    in log terms like vol.py's `moves_from_forward`. Returns the list of
    (moves, spot), the expiry used and one move."""
    opts = [l for l in legs if l["kind"] == "option"]
    if opts:
        front = min(opts, key=lambda l: l["date"])["expiry"]
    elif ctx["expiries"]:
        front = min(ctx["expiries"], key=lambda x: ctx["expiries"][x]["date"])
    else:
        raise Refused(f"{ctx['snapshot']}: no expiry to size the grid from")
    e = ctx["expiries"][front]
    iv = e["atm_iv"] or (curve(e["fit"], 0.0) if e["fit"] else None)
    if not iv:
        raise Refused(f"{front}: no at-the-money IV to size the grid from")
    move = iv * math.sqrt(e["T"])
    n = int(round(CONFIG["grid_moves"] / CONFIG["grid_step"]))
    return ([(i * CONFIG["grid_step"], ctx["spot"] * math.exp(i * CONFIG["grid_step"] * move))
             for i in range(-n, n + 1)], front, move)


def grid_slope(ctx, legs, shift=0.0, case="none"):
    """The grid's own sensitivity to spot at the snapshot, in shares per $1,
    just below spot and just above: (below, above).

    Under `none` both are the delta, Black-Scholes at a fixed IV, which is
    what contracts.csv holds and what Webull's API delta matched on the same
    snapshot. Under a response each strike's IV also moves with spot, by the
    response's own slope, so the grid's slope adds vega times that, per leg:

        below:  delta - vega x (rate on a drop)  x 100 / S x sqrt(30 / days)
        above:  delta + vega x (rate on a rally) x 100 / S x sqrt(30 / days)

    The two sides differ because the rates do: a drop raises IV by more than
    a rally lowers it. Until 2026-11-12 the smile slid instead, and the slope
    on the Nov-13 750 straddle of `2026-11-09_1421` read +32.99 shares
    against +15.90 of delta. Inside the what-if the slope is the hedge that
    cancels first-order P&L; which of them hedges SPY better at a given
    rebalancing interval is untested (integrity.md item 5)."""
    S = ctx["spot"]
    rows, total = price_point(ctx, legs, point(ctx, ctx["date"], S, shift))
    if case == "none":
        return total["delta"], total["delta"]
    down, up = CONFIG["response"][case]
    below = above = total["delta"]
    for r in rows:
        if r.get("days_left"):
            k = math.sqrt(CONFIG["response_days"] / r["days_left"]) * 100.0 / S
            below -= r["vega"] * down * k
            above += r["vega"] * up * k
    return below, above


def grid(ctx, legs, shift=0.0, position="", sessions=()):
    """Every leg and the position at every (date, spot) of the default grid,
    under each IV response, at one IV shift. Returns the rows and the totals
    keyed by (date, moves, case)."""
    spots, _, _ = grid_spots(ctx, legs)
    rows, totals = [], {}
    for date in grid_dates(ctx, legs, sessions):
        for moves, spot in spots:
            for case in CASES:
                pt = point(ctx, date, spot, shift, case)
                leg_rows, total = price_point(ctx, legs, pt)
                base = {"snapshot": ctx["snapshot"], "position": position, "date": date,
                        "sessions_passed": pt["passed"], "spot": spot, "moves": moves,
                        "move_pct": 100.0 * (spot / ctx["spot"] - 1.0),
                        "iv_shift": shift, "response": case}
                for leg, r in zip(legs, leg_rows):
                    rows.append({**base, **r, "leg": leg["label"]})
                rows.append({**base, **total, "leg": "total", "iv": None})
                totals[(date, moves, case)] = total
    return rows, totals


def read_path(path):
    """A path file, checked: dates in order, a spot on every step, and a
    hedge trade only where kind, qty and price make one."""
    steps, problems = [], []
    for i, raw in enumerate(read_rows(path), 1):
        try:
            date = dt.date.fromisoformat((raw.get("date") or "").strip())
        except ValueError:
            problems.append(f"step {i}: date {raw.get('date')!r} is not YYYY-MM-DD")
            continue
        nums, bad = _numbers(raw, ("spot", "iv_shift", "qty", "price"), f"step {i}",
                             problems)
        spot, qty, price = nums["spot"], nums["qty"], nums["price"]
        kind = (raw.get("kind") or "").strip().lower()
        if "spot" not in bad and (spot is None or spot <= 0):
            problems.append(f"step {i}: spot must be a positive price")
        if kind and kind not in ("shares", "nes"):
            problems.append(f"step {i}: a trade along a path is shares or nes, not {kind!r}")
        if kind and not qty:
            problems.append(f"step {i}: a {kind} trade needs a qty")
        if kind == "nes" and qty and not _whole(qty):
            problems.append(f"step {i}: {qty:g} NES contracts; futures trade in "
                            f"whole contracts")
        if not kind and (qty or price):
            problems.append(f"step {i}: a qty or price with no kind; a trade "
                            f"is shares or nes")
        if kind == "nes" and not price:
            problems.append(f"step {i}: an NES trade needs its fill price")
        if steps and date < steps[-1]["date"]:
            problems.append(f"step {i}: {date} comes before the step above it")
        steps.append({"step": i, "date": date, "spot": spot,
                      "shift": nums["iv_shift"] or 0.0,
                      "kind": kind, "qty": qty, "price": price})
    if problems:
        raise Refused(problems)
    if not steps:
        raise Refused("the path has no steps")
    return steps


def run_path(ctx, legs, steps, position=""):
    """P&L along a path. The position is valued at each step as at any point;
    each hedge trade joins at its own step's spot and runs from there.

    NES is marked to one price per step: the latest NES fill's ratio to SPY,
    times the step's spot, so at a step with an NES trade the mark is that
    fill. Every NES contract, in the position file or traded along the way,
    is valued at that mark, which is what lets a round trip come back flat
    with the difference of its fills as P&L. Between fills the ratio is held:
    the future's premium over SPY is not modelled, only read off the fills.

    An option leg settles once, at the spot of the last step dated on its
    expiry, and keeps that value: a path is the one place where SPY after an
    expiry differs from SPY on it. So a path that steps past an expiry
    without landing on it is refused - SPY's price at the settlement is the
    one number it would otherwise have to make up."""
    expiries = sorted({l["date"] for l in legs if l["kind"] == "option"})
    dates = {s["date"] for s in steps}
    missed = [e for e in expiries if e not in dates and steps[-1]["date"] > e]
    if missed:
        raise Refused([f"the path steps past the {e} expiry with no step dated "
                       f"on it; add one, since legs expiring then settle at "
                       f"SPY's price that day" for e in missed])
    trades, rows, settled = [], [], {}
    ratio = next((l["ratio"] for l in legs if l["kind"] == "nes"), None)
    for s in steps:
        if s["kind"] == "nes":
            ratio = s["price"] / s["spot"]
        pt = point(ctx, s["date"], s["spot"], s["shift"])
        pt["nes_ratio"] = ratio
        pt["settled"] = dict(settled)
        if s["date"] in expiries:
            settled[s["date"]] = s["spot"]        # the last step on the day wins
        _, total = price_point(ctx, legs, pt)
        label = ""
        if s["kind"]:
            t = hedge_leg(s["kind"], s["qty"], s["price"], s["spot"])
            trades.append(t)
            label = t["label"]
        hedged = [price_leg(ctx, t, pt) for t in trades]
        pnl_hedges = sum(h["value"] - t["start_value"] for h, t in zip(hedged, trades))
        row = {"snapshot": ctx["snapshot"], "position": position, "step": s["step"],
               "date": s["date"], "sessions_passed": pt["passed"], "spot": s["spot"],
               "iv_shift": s["shift"], "trade": label, "value": total["value"],
               "pnl_position": total["pnl"], "pnl_hedges": pnl_hedges,
               "pnl": total["pnl"] + pnl_hedges,
               "pnl_low": total["pnl_low"] + pnl_hedges,
               "pnl_high": total["pnl_high"] + pnl_hedges,
               "flags": total["flags"], "arb": total["arb"]}
        for g in GREEKS:
            row[g] = total[g] + sum(h[g] for h in hedged)
        rows.append(row)
    return rows


def leg_rows(legs):
    out = []
    for l in legs:
        ivs = l["ivs"] or (None, None, None)
        if l["kind"] == "nes":
            # The shared mark at the start against this leg's own fill: what
            # the contract made or lost before the snapshot, kept out of P&L.
            gap = CONFIG["nes_dollars_per_point"] * l["qty"] * (l["entry_mark"] - l["price"])
        elif l["entry_mid"] is not None:
            gap = l["start_value"] - l["entry_mid"]
        else:
            gap = None
        out.append({
            "leg": l["label"], "kind": l["kind"], "expiry": l["expiry"],
            "strike": l["strike"], "right": l["right"], "qty": l["qty"],
            "price": l["price"], "iv_source": l["source"], "iv": ivs[1],
            "iv_bid": ivs[0], "iv_ask": ivs[2], "bid": l["bid"], "ask": l["ask"],
            "entry_mid": l["entry_mid"], "entry_far": l["entry_far"],
            "model_start": l["start_value"] if l["kind"] != "nes" else 0.0,
            "model_minus_mid": gap,
            "shares_per_contract": l["per"], "flags": l["flags"],
        })
    return out


def _cell(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (set, frozenset)):
        return ";".join(sorted(v))
    return v


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _cell(r.get(c)) for c in cols})


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _money(v, width=10):
    return f"{v:>+{width},.0f}" if v is not None else f"{'-':>{width}}"


def _header(ctx, legs, position):
    print(f"{ctx['snapshot']}: {position}, {len(legs)} leg{'s' * (len(legs) != 1)}. "
          f"A what-if under the rules in scenario.py, not a forecast.")
    print(f"  start: SPY {ctx['spot']:.2f} at {ctx['started']:%Y-%m-%d %H:%M} ET")
    print()
    print(f"  {'leg':<28}{'IV':>8}{'source':>8}{'entry mid':>12}{'far side':>11}"
          f"{'model - mid':>13}")
    for r in leg_rows(legs):
        iv = f"{r['iv'] * 100:.2f}%" if r["iv"] is not None else "-"
        print(f"  {r['leg']:<28}{iv:>8}{r['iv_source'] or '-':>8}"
              f"{_money(r['entry_mid'], 12)}{_money(r['entry_far'], 11)}"
              f"{_money(r['model_minus_mid'], 13)}")
    known = [r for r in leg_rows(legs) if r["entry_mid"] is not None]
    mid = sum(r["entry_mid"] for r in known)
    far = sum(r["entry_far"] for r in known)
    print(f"  {'position':<44}{_money(mid, 12)}{_money(far, 11)}")
    print("    entry is at mid; P&L runs from the model's start value, so the "
          "model - mid gap is beside it, not in it")
    nes = [l for l in legs if l["kind"] == "nes"]
    if nes:
        print(f"    NES: {nes[-1]['per']:.3f} SPY shares of delta per contract "
              f"(0.50 x latest fill {nes[-1]['price']:g} / SPY spot); every NES "
              f"contract is marked to that one price")


def _flags(rows, unit):
    """Each flag that occurred, what it means, and where: per leg on a grid,
    per step on a path, with how many of the points it was raised at."""
    seen, points = {}, set()
    for r in rows:
        at = (r.get("date"), r.get("moves"), r.get("step"))
        points.add(at)
        for f in r.get("flags") or ():
            seen.setdefault(f, {}).setdefault(r.get("leg") or "", set()).add(at)
    if not seen:
        return
    print()
    for f in sorted(seen):
        print(f"    ! {f}: {FLAGS[f]}")
        where = [f"{leg} ({len(at)} of {len(points)} {unit})" if leg else
                 f"{len(at)} of {len(points)} {unit}"
                 for leg, at in sorted(seen[f].items())]
        print(f"        {'; '.join(where)}")


def _arb(found):
    """The largest spread priced outside its bounds, from (where, arb) pairs."""
    found = [(where, a) for where, a in found if a]
    if not found:
        return
    where, a = max(found, key=lambda x: x[1]["size"])
    strikes = "/".join(f"{k:g}" for k in a["strikes"])
    print(f"        largest: the {a['expiry']} {strikes} {a['spread']} off its bound by "
          f"${a['size']:.3f} a share (${100 * a['size']:,.2f} a contract), at {where}")


def _saved(dest):
    try:
        shown = dest.relative_to(ROOT)
    except ValueError:
        shown = dest
    print(f"\n  saved {shown}/")


def extremes(by_case, tol=0.5):
    """(lowest, highest): which IV response gives a point's position the
    lowest P&L and which the highest, from {case: total}. None for both when
    the cases agree within `tol` dollars, as they do where spot has not
    moved. Named per point, never assumed: a bigger IV rise hurts a short
    straddle on a drop, and a bigger IV fall helps it on a rally."""
    pnl = {c: by_case[c]["pnl"] for c in CASES if c in by_case}
    lo, hi = min(pnl, key=pnl.get), max(pnl, key=pnl.get)
    if pnl[hi] - pnl[lo] < tol:
        return None, None
    return lo, hi


def _rates():
    parts = []
    for case in CASES[1:]:
        down, up = CONFIG["response"][case]
        parts.append(f"{case} {down:+.1f} on a drop, {up:+.1f} on a rally")
    return "; ".join(parts)


def report_grid(ctx, legs, position, rows, totals, shift, dest, sessions=()):
    _header(ctx, legs, position)
    spots, front, move = grid_spots(ctx, legs)
    dates = grid_dates(ctx, legs, sessions)
    lo_days, hi_days = CONFIG["response_checked_days"]
    print()
    print(f"  P&L in $ at an IV shift of {shift:+.2f} vol points: model value at each "
          f"point minus at the start,")
    print("  under three IV responses to the spot move. Each strike keeps its IV as "
          "spot moves; the date")
    print("  carries it along today's term structure; the response and any shift go "
          "on top.")
    print(f"  Response, vol points per 1% of SPY move at {CONFIG['response_days']:.0f} "
          f"days to expiry, x sqrt({CONFIG['response_days']:.0f}/days left):")
    print(f"    {_rates()}.")
    print("  Umbrella figures set above what five moves measured (docs/measurements.md "
          "2026-11-11), not a fit;")
    print("  the same however many sessions the move took. Not in the band: IV moving "
          "against the usual way,")
    print("  or moving with no spot move at all (ask with --shift).")
    print(f"  Spot in expected moves of {front} ({move * 100:.2f}% each); dates at their "
          f"close, `now` is the snapshot.")
    options = [l for l in legs if l["kind"] == "option"]
    for d in dates:
        at = [r for r in rows if r["date"] == d and r["moves"] == 0.0
              and r["response"] == "none" and r["leg"] != "total"]
        passed = at[0]["sessions_passed"] if at else 0.0
        print()
        print(f"  {'now' if d == ctx['date'] else d.isoformat() + ' close'}: "
              f"{passed:.2f} sessions after the snapshot")
        seen = set()
        for leg, r in zip(legs, at):
            if leg["kind"] != "option" or (leg["expiry"], leg["strike"]) in seen:
                continue
            seen.add((leg["expiry"], leg["strike"]))
            if r["iv"] is None:
                print(f"    {leg['expiry']} {leg['strike']:g}: expired")
            else:
                print(f"    {leg['expiry']} {leg['strike']:g}: {r['days_left']:.1f} days to "
                      f"expiry, IV {r['iv'] * 100:.2f}% with no response")
        if not options:
            print("    no option legs")
        print(f"    {'moves':>6}{'move':>8}{'spot':>9}" +
              "".join(f"{c:>11}" for c in CASES) + "   lowest / highest")
        for moves, spot in spots:
            by = {c: totals[(d, moves, c)] for c in CASES}
            lo, hi = extremes(by)
            tail = f"   {lo} / {hi}" if lo else ""
            print(f"    {moves:>+6.1f}{100 * (spot / ctx['spot'] - 1):>+7.2f}%{spot:>9.2f}" +
                  "".join(_money(by[c]["pnl"], 11) for c in CASES) + tail)
    start = totals[(ctx["date"], 0.0, "none")]
    print()
    print(f"  Greeks now, at fixed IV: delta {start['delta']:+.1f} shares, gamma "
          f"{start['gamma']:+.2f} shares per $1, theta {start['theta']:+,.2f} $/day, "
          f"vega {start['vega']:+,.2f} $/vol point")
    slopes = []
    for case in CASES[1:]:
        below, above = grid_slope(ctx, legs, shift, case)
        slopes.append(f"{case} {below:+.1f} below, {above:+.1f} above")
    print(f"  grid slope at spot, shares per $1: none {start['delta']:+.1f} either side "
          f"(the delta); {'; '.join(slopes)}.")
    print("  Each response adds vega x its own slope. Which of them hedges SPY better "
          "is untested.")
    # At the start P&L is zero unless a shift was asked for, and then it is
    # that shock. The range around it is the IV bands either way; saying the
    # bands alone made it credited a -5 point shock to quote uncertainty.
    width = start["pnl_high"] - start["pnl_low"]
    if shift:
        print(f"  at the start the {shift:+.2f} point shift alone moves the value by "
              f"{start['pnl']:+,.0f} (the shock asked for); the IV bands put it between")
        print(f"  {start['pnl_low']:+,.0f} and {start['pnl_high']:+,.0f}, ${width:,.0f} wide "
              f"around that;")
    else:
        print(f"  at the start the IV bands alone put the position's value between "
              f"{start['pnl_low']:+,.0f} and {start['pnl_high']:+,.0f} of its model value;")
    print("  every point's range, under every response, is in grid.csv (pnl_low, pnl_high)")
    _flags([r for r in rows if r["leg"] != "total"], "points")
    _arb((f"{d} {'now' if d == ctx['date'] else 'close'}, {m:+.1f} moves, {c}", t.get("arb"))
         for (d, m, c), t in totals.items())
    _saved(dest)


def report_path(ctx, legs, position, rows, dest):
    _header(ctx, legs, position)
    print()
    print("  P&L in $ along the path: the position from its start, each hedge "
          "trade from its own spot.")
    print()
    print(f"  {'step':>4}  {'date':<11}{'spot':>9}{'shift':>7}  {'trade':<20}"
          f"{'position':>10}{'hedges':>10}{'P&L':>10}{'range':>20}{'delta':>9}")
    for r in rows:
        rng = f"{r['pnl_low']:+,.0f} to {r['pnl_high']:+,.0f}"
        print(f"  {r['step']:>4}  {r['date'].isoformat():<11}{r['spot']:>9.2f}"
              f"{r['iv_shift']:>+7.2f}  {r['trade']:<20}{_money(r['pnl_position'])}"
              f"{_money(r['pnl_hedges'])}{_money(r['pnl'])}{rng:>20}{r['delta']:>+9.1f}")
    _flags(rows, "steps")
    _arb((f"step {r['step']} ({r['date']})", r.get("arb")) for r in rows)
    _saved(dest)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def latest():
    """The newest snapshot the pipeline has carried through the fit: the
    engine needs the raw chain, vol.py's IVs and surface.py's curves."""
    ready = sorted(p.name for p in SURFACE_DIR.glob("*")
                   if (p / "fits.csv").exists()
                   and (IV_DIR / p.name / "contracts.csv").exists()
                   and (CHAIN_DIR / p.name / "options.csv").exists())
    if not ready:
        sys.exit(f"Nothing fitted in {SURFACE_DIR}. Run `python app.py surface` first.")
    return ready[-1]


def run(position, snapshot, path=None, shift=0.0, sessions=()):
    """Price a position file on one snapshot and write the output. Returns
    what the report needs; raises Refused rather than printing a guess.

    `shift` and `sessions` are the grid's. A path carries its own shift on
    every step, so a shift given with a path is refused rather than dropped
    or stacked on top: one shock with two sources is one too many to read
    back. A path's dates are its own too, so `sessions` with a path is
    refused for the same reason."""
    shift = 0.0 if shift is None else shift
    if not math.isfinite(shift):
        raise Refused(f"the IV shift {shift} is not a number")
    if path and shift:
        raise Refused("--shift sets the grid's IV shift; a path carries its own "
                      "in each step's iv_shift column, so put the shift there")
    sessions = parse_sessions(sessions)
    if path and sessions:
        raise Refused("--sessions adds dates to the grid; a path has its own dates "
                      "in its date column, so put them there")
    if snapshot == WORK:
        raise Refused(f"{WORK} is where saves are staged, not a snapshot")
    position = pathlib.Path(position)
    dest = OUT_DIR / snapshot / position.stem
    with held(dest):
        return _run(position, snapshot, path, shift, dest, sessions)


def _run(position, snapshot, path, shift, dest, sessions=()):
    """`run` inside its lock (`held`): everything from tidying what an
    interrupted run left to swapping the new set in."""
    recover(dest)
    # The snapshot's files are hashed either side of the one place they are
    # read, so the fingerprint is of the data this run priced. Hashed after
    # pricing instead, a re-run of `iv` in the meantime stamped a grid priced
    # on the old IVs with the new data's fingerprint.
    data = snapshot_hash(snapshot)
    ctx = load(snapshot)
    if snapshot_hash(snapshot).digest() != data.digest():
        raise Refused(f"{snapshot}: its data changed while it was being read (was "
                      f"`iv`, `surface` or `daily` running on it?). Run this again")
    legs = build_legs(ctx, read_rows(position))
    totals = None
    if path:
        steps = read_path(pathlib.Path(path))
        rows = run_path(ctx, legs, steps, position.stem)
        name, other, cols = "path.csv", "grid.csv", PATH_COLS
        params = ["path", [[str(s["date"]), s["spot"], s["shift"], s["kind"], s["qty"],
                            s["price"]] for s in steps]]
    else:
        rows, totals = grid(ctx, legs, shift, position.stem, sessions)
        name, other, cols = "grid.csv", "path.csv", GRID_COLS
        # The response rates are the engine's, not the position's, but they
        # change every number off spot, so they are part of which report
        # this is: a grid priced under other rates gets another id.
        params = ["grid", shift, CONFIG["grid_moves"], CONFIG["grid_step"],
                  {c: list(r) for c, r in sorted(CONFIG["response"].items())},
                  CONFIG["response_days"], list(sessions)]
    stamp = fingerprint(data, legs)
    report = hashlib.sha256((stamp + json.dumps(params)).encode()).hexdigest()[:12]
    legs_out = leg_rows(legs)
    for r in legs_out:
        r["inputs"] = stamp
    for r in rows:
        r["inputs"], r["report"] = stamp, report
    # The folder holds one position on one set of inputs. A grid and a path
    # priced from the same ones stay side by side, whatever the shift or the
    # steps; one priced from anything else is left out of the new set, not
    # left to be read as this position's.
    keep = [other] if (dest / other).exists() and saved_inputs(dest / other) == stamp else []
    removed = [other] if (dest / other).exists() and not keep else []
    publish(dest, {"legs.csv": (legs_out, LEG_COLS), name: (rows, cols)}, keep)
    return {"ctx": ctx, "legs": legs, "rows": rows, "totals": totals, "dest": dest,
            "inputs": stamp, "report": report, "removed": removed, "sessions": sessions}


def publish(dest, files, keep=()):
    """Replace the results folder `dest` with a complete new set, all at once.

    `files` maps a name to (rows, columns); `keep` names files already in
    `dest` that belong with them (the other output, on the same inputs).
    Writing into the live folder one file at a time could fail between two
    files - a CSV open in a spreadsheet is enough on Windows - and leave the
    new legs beside the old grid. So the set is built in the work area's
    `new`, then swapped in: `dest` to the work area's `old`, the new set to
    `dest`, and `old` deleted. Windows refuses to move a folder while a file
    in it is open, so a locked result stops the swap before anything has
    moved, and the last good set stays as it was. A failure anywhere is a
    Refused with that said, never a half-written folder."""
    staging, old = work_area(dest)
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            for name, (rows, cols) in files.items():
                write_csv(staging / name, rows, cols)
            for name in keep:
                shutil.copy2(dest / name, staging / name)
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            shutil.rmtree(staging, ignore_errors=True)
            raise Refused(f"could not write the results ({e}); the last good set in "
                          f"{dest} is untouched")
        if dest.exists():
            try:
                dest.rename(old)
            except OSError:
                shutil.rmtree(staging, ignore_errors=True)
                raise Refused(f"could not replace {dest}: a file in it is open elsewhere "
                              f"(a spreadsheet?). Close it and rerun; the last good set "
                              f"is untouched")
        try:
            staging.rename(dest)
        except OSError as e:
            if old.exists():
                old.rename(dest)
            shutil.rmtree(staging, ignore_errors=True)
            raise Refused(f"could not put the new results in place ({e}); the last good "
                          f"set in {dest} is back")
        shutil.rmtree(old, ignore_errors=True)
    finally:
        _tidy(staging.parent)


def work_area(dest):
    """(new, old): where a save of `dest` builds its new set and parks the
    last good one, under data/scenario/.work/<snapshot>/<position>/.

    Not beside `dest`. They used to be `<position>.writing` and
    `<position>.old` in the snapshot's folder, which is also where a position
    file named `pos.old.csv` saves its results, so running `pos.csv` deleted
    them as its own leftovers. Results are always one folder down from a
    snapshot, so no position name reaches `.work`, and `run` refuses a
    snapshot named `.work`. Derived from `dest` rather than from OUT_DIR, so
    it is always beside the results it guards."""
    work = dest.parent.parent / WORK / dest.parent.name / dest.name
    return work / "new", work / "old"


def _tidy(work):
    """Remove a position's work folder, and the snapshot's and `.work`
    itself, if each is empty. A folder still holding something stays."""
    for d in (work, work.parent, work.parent.parent):
        try:
            d.rmdir()
        except OSError:
            return


@contextlib.contextmanager
def held(dest):
    """One run at a time per results folder, from `recover` to `publish`.

    Every run of one position on one snapshot stages in the same work
    folder, and `recover` and `publish` clear what they find there, so two
    runs at once could delete or overwrite each other's unfinished set: one
    published the short-put legs of one run beside the long-call grid of the
    other, and the second failed. So a run first takes an operating-system
    lock on `lock` in that work folder, and a run that cannot get it is
    refused, not made to wait. The lock belongs to the open file, and the
    system drops it when its holder ends, however it ends: a run that
    crashed leaves at most an unlocked file, which the next run takes over
    and removes. Other positions, and the same one on other snapshots, have
    their own folders and run freely."""
    lock = work_area(dest)[0].parent / "lock"
    out = dest.parent.parent                  # data/scenario: a refused run leaves it as found
    had_out = out.exists()
    busy = Refused(f"another run is saving {dest.parent.name}/{dest.name} right now; "
                   f"let it finish, then run this again")
    fd = None
    for _ in range(3):
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock, os.O_RDWR | os.O_CREAT)
        except FileNotFoundError:
            continue                  # a finishing run tidied the folder away just then
        try:
            _os_lock(fd)
        except OSError:
            os.close(fd)
            raise busy from None
        if _same_file(fd, lock):
            break
        # Locked a file that a finishing run removed after we opened it:
        # whoever creates the next one would hold a lock of its own.
        _os_unlock(fd)
        os.close(fd)
        fd = None
    if fd is None:
        raise busy
    try:
        yield
    finally:
        _os_unlock(fd)
        os.close(fd)
        try:
            lock.unlink()
        except OSError:
            pass                      # another run has it open: it is theirs now
        _tidy(lock.parent)
        if not had_out:
            try:
                out.rmdir()           # only if nothing was saved in it
            except OSError:
                pass


def _os_lock(fd):
    """Lock the file without waiting; OSError if another holder has it."""
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _os_unlock(fd):
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass                          # closing the file drops it anyway


def _same_file(fd, path):
    """Whether the open file is still the one at `path`."""
    try:
        a, b = os.fstat(fd), os.stat(path)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def recover(dest):
    """Tidy what a run stopped partway through left in the work area: a
    staged set that never went in is deleted, and a last good set moved
    aside comes back if nothing took its place. Run before anything else, so
    even a run that is then refused leaves the folder whole. It looks only in
    `dest`'s own work folder, never at a neighbour of `dest`."""
    staging, old = work_area(dest)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    if old.exists():
        if dest.exists():
            shutil.rmtree(old, ignore_errors=True)     # swapped in; only the cleanup failed
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            old.rename(dest)                            # stopped mid-swap: the good set returns
    _tidy(staging.parent)


def snapshot_hash(snapshot):
    """Every snapshot file the engine reads, hashed in a fixed order; a
    hashlib object that `fingerprint` adds the legs to. `run` takes it
    either side of `load`, the one place those files are read."""
    h = hashlib.sha256(snapshot.encode())
    for folder, name in ((CHAIN_DIR, "options.csv"), (CHAIN_DIR, "spot.csv"),
                         (CHAIN_DIR, "run.json"), (IV_DIR, "contracts.csv"),
                         (IV_DIR, "expiries.csv"), (SURFACE_DIR, "fits.csv"),
                         (SURFACE_DIR, "points.csv")):
        path = folder / snapshot / name
        h.update(name.encode())
        h.update(path.read_bytes() if path.exists() else b"missing")
    return h


def fingerprint(data, legs):
    """What a saved result was priced from, as 12 hex characters: the legs
    as the engine read them, added to `data`, the `snapshot_hash` taken
    when the snapshot's files were read.

    The legs, not the file's bytes: a comment, a blank row or `600` written
    `600.0` is the same position, and changing a leg is not. Their order
    stays in, since the last NES row sets the shared NES mark. The snapshot
    files are in because re-running `iv` or `surface` changes what the same
    legs are worth, and they are the bytes the run read, not a second read
    after pricing (`run` refuses if the two hashes either side of the read
    differ). Every fill is in, an option's included: two trades at
    different prices are two positions, even where the engine's numbers agree.
    The grid's shift and a path's steps are not: those belong to the run, and
    each run gets its own `report` id over them (see `run`), so a grid and a
    path of one position share `inputs` and differ in `report`. The engine's
    own code is not in it either, so a result saved before a change to the
    engine is not caught by this. Neither is a file rewritten with the same
    bytes while it was being read: the hashes either side agree, though the
    read may have caught it half-written."""
    h = data.copy()
    for l in legs:
        h.update(json.dumps([l["kind"], l["expiry"], l["strike"], l["right"],
                             l["qty"], l["price"]]).encode())
    return h.hexdigest()[:12]


def saved_inputs(path):
    """The fingerprint a saved CSV was priced from; None if it carries none,
    as files from before the column existed do."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            row = next(csv.DictReader(f), None)
    except OSError:
        return None
    return (row or {}).get("inputs") or None


def cmd_scenario(position, which=None, path=None, shift=0.0, sessions=None):
    if not pathlib.Path(position).exists():
        sys.exit(f"No position file at {position}")
    if path and not pathlib.Path(path).exists():
        sys.exit(f"No path file at {path}")
    snapshot = which or latest()
    for folder, need in ((CHAIN_DIR, "options.csv"), (IV_DIR, "contracts.csv"),
                         (SURFACE_DIR, "fits.csv")):
        if not (folder / snapshot / need).exists():
            sys.exit(f"No {need} for {snapshot} in {folder}. Run the pipeline "
                     f"through `surface` on it first.")
    try:
        out = run(position, snapshot, path, shift, sessions)
    except Refused as e:
        sys.exit("Refused, nothing written:\n  " + "\n  ".join(e.reasons))
    name = pathlib.Path(position).stem
    if path:
        report_path(out["ctx"], out["legs"], name, out["rows"], out["dest"])
    else:
        report_grid(out["ctx"], out["legs"], name, out["rows"], out["totals"],
                    shift or 0.0, out["dest"], out["sessions"])
    print(f"  inputs {out['inputs']}: this position (its legs and fills) on this "
          f"snapshot's data; report {out['report']}: this run of it")
    for gone in out["removed"]:
        print(f"    ! removed {gone}: it was priced from other inputs (an earlier "
              f"version of this position, or of the snapshot's data)")
