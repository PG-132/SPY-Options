"""
context.py - where this chain's pricing sits. Step 6 of the screener.

  python app.py context                  the newest snapshot
  python app.py context 2026-10-20_1543  a particular one

term.py strips the variance between expiries and stops there: it says what
each window is worth, not whether that is a lot. This file asks the second
question, and asks it of every window without being pointed at one. Choosing
which windows to look at is where a view leaks into a measurement, so there
is nothing to choose here - the whole chain comes back decomposed.

TWO COMPARISONS, BOTH OF THEM FACTS
-----------------------------------
vs rest    the window against the complement: the chain's total variance less
           this window's, over the sessions that are left. The level
           question - is this stretch expensive against everything else on
           offer.

vs neigh   the window against the two beside it. A term structure that slopes
           makes every front window read cheap against the rest and every
           back one rich, which is the shape of a calm market rather than
           news. The local comparison is what finds a window jutting above
           the ones either side - an earnings date, a meeting - and it fits
           nothing to get there.

           Not their mean: the straight line between them, read at this
           window's own midpoint in session space. Windows are not equally
           spaced - SPY lists daily out two weeks and weekly after that - and
           against unequal spacing a plain mean leaves part of the slope in
           the answer, which is the thing the comparison exists to remove.
           The two are the same number when the spacing happens to be even.

Neither is modelled. The first is arithmetic on the chain, the second
arithmetic on three adjacent windows. Fitting a curve to the term structure
and reporting deviations from it would be the obvious third option and it is
left out on purpose: the shape chosen would decide which windows look
unusual.

A window at either end has one neighbour, so its local number is left blank
rather than quietly reported as a first difference where the others are
second differences.

THE DECOMPOSITION TILES
-----------------------
term.forward_windows covers the gaps BETWEEN expiries, which leaves out the
stretch from the snapshot to the first expiry. That stretch is priced - it is
the front expiry's own total variance - and dropping it would make every
complement miss a piece. A synthetic zero row is prepended so the windows run
from spot to the last expiry with no gaps: their sessions add to the chain's
and their variances to its total. Zero elapsed time carries zero variance
exactly, so that row is arithmetic rather than an assumption.

ERROR BARS
----------
A window and the rest of the chain share endpoints, and share them with
opposite signs: an error in the total variance at the window's far edge
raises the window and lowers the rest by the same stroke. Their difference is
therefore less certain than either side, and propagating the two as though
they were independent would understate it.

So every comparison is differentiated through to the per-expiry totals, and
the coefficients are summed per expiry before squaring. That is also what
makes the last window come out right, where the rest's far end and the
window's own far end are the same number and have to cancel rather than be
counted twice.

One known understatement remains. The per-expiry totals are treated as
independent of each other, and they are not: each carries that expiry's
forward_iv_cost, which comes from the same forward and moves them together.
A common-mode error largely cancels in any difference, so the bars here are
wider than the truth, which is the safe direction - it calls fewer windows
different than it could.

WHAT IS NOT HERE
----------------
No percentile for a window. The index series resolve three points on the
curve - 9, 30 and 93 days - while our chain carries six or seven separate
windows inside the first nine days alone. Ranking a window against VIX9D
means collapsing our own resolution to buy a number at a coarser one, and
30-90 days sits past what the collector reaches at all. The 30-day level is
ranked against VIX, which is like for like. The windows are ranked against
nothing yet. What they will be ranked against is our own history of them,
which is why every window of every snapshot gets logged.
"""

import collections
import csv
import datetime as dt
import json
import math
import pathlib
import sys

from screener import prices, term, vrp

CONFIG = {
    "sessions_per_year": 252,
    # The index whose history the 30-day level is ranked against. VIX is a
    # variance swap rate at 30 days and so is ours, which is the only reason
    # the comparison means anything.
    "benchmark": "^VIX",
    # Regular US equity hours in minutes past midnight ET. Half-days close
    # at 13:00 and are not modelled yet; on one the fraction below is
    # overstated, which is a known and dated gap.
    "open_minute": 9 * 60 + 30,
    "close_minute": 16 * 60,
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAIN_DIR = ROOT / "data" / "chains"
SURFACE_DIR = ROOT / "data" / "surface"
OUT_DIR = ROOT / "data" / "context"

WINDOW_COLS = ["from_expiry", "to_expiry", "session_priced", "sessions", "days",
               "source", "forward_vol", "forward_vol_error",
               "put_skew_to", "call_skew_to",
               "rest_vol", "vs_rest", "vs_rest_error", "rest_differs",
               "neighbour_vol", "vs_neighbours", "vs_neighbours_error",
               "neighbours_differ"]
CHAIN_COLS = ["snapshot", "date", "session_remaining", "sessions", "days",
              "chain_vol",
              "chain_vol_calendar", "windows",
              "rate_30d", "extrapolated_days", "band", "vix", "ours_minus_vix",
              "percentile", "percentile_n", "history_from", "history_to"]

SPOT = "spot"


# ---------------------------------------------------------------------------
# The decomposition
# ---------------------------------------------------------------------------

def session_remaining(snapshot):
    """How much of the snapshot's own trading session was still to run, as a
    fraction, from the timestamp the collector wrote.

    Falls back to the folder name, which carries the time to the minute, and
    to zero if neither can be read - zero being the assumption that costs
    least, since it is what a snapshot taken at the close would have."""
    stamp = None
    path = CHAIN_DIR / snapshot / "run.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                stamp = dt.datetime.fromisoformat(json.load(f)["started_et"])
        except (ValueError, KeyError, OSError, json.JSONDecodeError):
            stamp = None
    if stamp is None:
        try:
            stamp = dt.datetime.strptime(snapshot[:15], "%Y-%m-%d_%H%M")
        except ValueError:
            return 0.0
    minutes = stamp.hour * 60 + stamp.minute + stamp.second / 60.0
    span = CONFIG["close_minute"] - CONFIG["open_minute"]
    return min(1.0, max(0.0, (CONFIG["close_minute"] - minutes) / span))


def with_spot(rows, remaining=0.0):
    """`rows` from term.load, with a synthetic row in front of them for the
    moment the snapshot was taken.

    Its variance is zero and so is the uncertainty about that: no time has
    passed, exactly. Its SESSION COUNT is not zero, though, and that is the
    subtle part. vol.sessions_between counts from the day after the snapshot,
    which puts the session clock's origin at that day's close - so a snapshot
    taken before the close sits at a NEGATIVE session count, and the window
    from it to the first expiry is longer than one session by however much of
    today is left.

    Uncorrected, the front window prices the rest of today plus all of
    tomorrow and is divided by a single session: it reads 11% high at 14:30
    and 2% high at 15:45. A routine that snaps at different times on
    different days therefore puts a sawtooth of about a point into the front
    of every chain, and the ledger reports it as a repricing. Every other
    window differences two expiries that both contain the same partial day,
    so it cancels there and only the first one needs this.

    `source` is copied from the first real expiry so the stub window does not
    read as mixing two of them."""
    if not rows:
        return []
    first = rows[0]
    spot = {"expiry": SPOT, "sessions": -float(remaining), "days": 0.0, "T": 0.0,
            "atm": first["atm"], "level": first["level"],
            "put_skew": first.get("put_skew"),
            "call_skew": first.get("call_skew"),
            "source": first["source"], "level_error": 0.0,
            "total_var": 0.0, "total_var_error": 0.0}
    return [spot] + list(rows)


def decompose(rows, remaining=0.0):
    """Windows tiling the snapshot to the last expiry, and the rows behind.

    The forward arithmetic is term's, called once on the extended rows rather
    than reimplemented for the leading stub."""
    full = with_spot(rows, remaining)
    return term.forward_windows(full), full


# ---------------------------------------------------------------------------
# Comparing a window with the rest
# ---------------------------------------------------------------------------

def _gradient(sessions, vol):
    """d(forward vol) / d(the variance accumulated over the window).

    vol = sqrt(w / y), so d(vol)/dw = 1 / (2 * vol * y)."""
    y = sessions / CONFIG["sessions_per_year"]
    if not y or not vol:
        return None
    return 1.0 / (2.0 * vol * y)


def _window_terms(w):
    """A window's vol differentiated against the per-expiry totals it is made
    of: minus at the near end, plus at the far one."""
    g = _gradient(w["sessions"], w["forward_vol"])
    if g is None:
        return None
    terms = collections.Counter()
    terms[w["from_expiry"]] -= g
    terms[w["to_expiry"]] += g
    return terms


def _rest_terms(w, last, rest_sessions, rest_vol):
    """The same for the complement, whose variance is w_last - w_to + w_from.

    Accumulated rather than written as a literal, because for the LAST window
    `last` and the window's own far end are the same expiry and the two
    coefficients have to cancel. A dict literal cannot hold a key twice: it
    keeps whichever was written last and the cancellation never happens, which
    leaves the final window carrying an uncertainty that is not there."""
    g = _gradient(rest_sessions, rest_vol)
    if g is None:
        return None
    terms = collections.Counter()
    terms[last] += g
    terms[w["to_expiry"]] -= g
    terms[w["from_expiry"]] += g
    return terms


def _error(parts, errors):
    """Standard deviation of a linear combination of the per-expiry totals.

    `parts` is a sequence of (weight, {expiry: coefficient}) pairs. Summing
    the coefficients per expiry before squaring is the whole point: shared
    endpoints have to be allowed to cancel or reinforce, and squaring each
    appearance on its own would forbid both."""
    total = collections.Counter()
    for weight, terms in parts:
        if terms is None:
            return None
        for expiry, coef in terms.items():
            total[expiry] += weight * coef
    return math.sqrt(sum((c * errors.get(e, 0.0)) ** 2 for e, c in total.items()))


def richness(windows, full):
    """Each window against the rest of the chain and against its neighbours.

    Both differences are in volatility points on the session clock, the same
    units term.py reports, and each carries the error on the difference
    rather than the error on either side."""
    if not windows:
        return []
    errors = {r["expiry"]: r["total_var_error"] for r in full}
    at = {r["expiry"]: r["sessions"] for r in full}
    last = full[-1]
    # The span, not the last expiry's own count: the snapshot sits at a
    # negative session when taken before the close, and the windows have to
    # tile what they actually cover or every complement is short.
    total_sessions = last["sessions"] - full[0]["sessions"]
    total_var = last["total_var"]

    def midpoint(w):
        """Where the window sits on the session axis. A forward vol belongs
        to the whole window, not to either edge, so the middle is the only
        defensible place to put it when spacing it against its neighbours."""
        return (at[w["from_expiry"]] + at[w["to_expiry"]]) / 2.0

    out = []
    for i, w in enumerate(windows):
        row = dict(w)
        row.update({"rest_vol": None, "vs_rest": None, "vs_rest_error": None,
                    "rest_differs": False, "neighbour_vol": None,
                    "vs_neighbours": None, "vs_neighbours_error": None,
                    "neighbours_differ": False})

        rest_sessions = total_sessions - w["sessions"]
        rest_var_total = total_var - (w["total_var_to"] - w["total_var_from"])
        if w["forward_vol"] and rest_sessions > 0:
            years = rest_sessions / CONFIG["sessions_per_year"]
            rest = rest_var_total / years
            if rest > 0:
                rest_vol = math.sqrt(rest)
                diff = w["forward_vol"] - rest_vol
                err = _error([(1.0, _window_terms(w)),
                              (-1.0, _rest_terms(w, last["expiry"],
                                                 rest_sessions, rest_vol))],
                             errors)
                row.update({"rest_vol": rest_vol, "vs_rest": diff,
                            "vs_rest_error": err,
                            "rest_differs": bool(err is not None
                                                 and abs(diff) > err)})

        # Only an interior window has a neighbour on each side. One-sided
        # would be a first difference where the rest are second differences,
        # so the ends are left blank.
        if 0 < i < len(windows) - 1:
            before, after = windows[i - 1], windows[i + 1]
            if w["forward_vol"] and before["forward_vol"] and after["forward_vol"]:
                span = midpoint(after) - midpoint(before)
                frac = (midpoint(w) - midpoint(before)) / span if span else 0.5
                line = (before["forward_vol"] * (1.0 - frac)
                        + after["forward_vol"] * frac)
                diff = w["forward_vol"] - line
                err = _error([(1.0, _window_terms(w)),
                              (-(1.0 - frac), _window_terms(before)),
                              (-frac, _window_terms(after))], errors)
                row.update({"neighbour_vol": line, "vs_neighbours": diff,
                            "vs_neighbours_error": err,
                            "neighbours_differ": bool(err is not None
                                                      and abs(diff) > err)})
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# The level, against the only history that matches it
# ---------------------------------------------------------------------------

def vix_history(refresh=False):
    """A seam: the tests replace this rather than the network."""
    return prices.closes(prices.history(CONFIG["benchmark"], refresh))


def percentile(rate, closes):
    """Where `rate` sits in a history of index closes, as a fraction.

    Ties take the midpoint, which matters because index closes carry two
    decimals and exact repeats are common."""
    if rate is None or not closes:
        return None
    levels = [c / 100.0 for _, c in closes if c]
    if not levels:
        return None
    below = sum(1 for v in levels if v < rate)
    equal = sum(1 for v in levels if v == rate)
    return {"pct": (below + 0.5 * equal) / len(levels), "n": len(levels),
            "first": closes[0][0], "last": closes[-1][0]}


def chain_level(windows, full):
    """The whole chain as one number, on both clocks.

    The same total variance annualizes two ways and the choice is a
    convention, not a measurement. The session figure is the aggregate of the
    windows below it and shares their clock. The calendar figure is the one
    that can sit beside VIX, which annualizes on calendar time. On a 23
    session, 31 day chain they differ by 0.6 vol points - small, but large
    enough to read as a real gap against the index if only one were shown
    and its clock went unnamed."""
    last = full[-1]
    span = last["sessions"] - full[0]["sessions"]
    years = span / CONFIG["sessions_per_year"]
    if years <= 0 or last["total_var"] <= 0:
        return None
    return {"sessions": span, "days": last["days"],
            "vol": math.sqrt(last["total_var"] / years),
            "vol_calendar": (math.sqrt(last["total_var"] / last["T"])
                             if last["T"] > 0 else None),
            "windows": len(windows)}


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

def analyse(snapshot, refresh=False):
    rows, dropped = term.load(snapshot)
    if len(rows) < 2:
        raise SystemExit(f"{snapshot}: need at least two fitted expiries, "
                         f"found {len(rows)}")
    remaining = session_remaining(snapshot)
    windows, full = decompose(rows, remaining)
    scored = richness(windows, full)
    chain = chain_level(windows, full)

    closes = vix_history(refresh)
    rate = vrp.our_rate(snapshot)
    try:
        when = dt.date.fromisoformat(snapshot[:10])
    except ValueError:
        when = None
    today = dict(closes).get(when)
    rank = percentile(rate["rate"], closes) if rate else None

    summary = {
        "snapshot": snapshot, "date": when,
        "session_remaining": round(remaining, 4),
        "sessions": chain["sessions"] if chain else None,
        "days": chain["days"] if chain else None,
        "chain_vol": chain["vol"] if chain else None,
        "chain_vol_calendar": chain["vol_calendar"] if chain else None,
        "windows": len(scored),
        "rate_30d": rate["rate"] if rate else None,
        "extrapolated_days": rate["extrapolated_days"] if rate else None,
        "band": rate["band"] if rate else None,
        "vix": (today / 100.0) if today else None,
        "ours_minus_vix": (rate["rate"] - today / 100.0)
                          if (rate and today) else None,
        "percentile": rank["pct"] if rank else None,
        "percentile_n": rank["n"] if rank else None,
        "history_from": rank["first"] if rank else None,
        "history_to": rank["last"] if rank else None,
    }

    dest = OUT_DIR / snapshot
    dest.mkdir(parents=True, exist_ok=True)
    term.write_csv(dest / "windows.csv", scored, WINDOW_COLS)
    term.write_csv(dest / "chain.csv", [summary], CHAIN_COLS)
    return scored, summary, dest, dropped


def report(scored, summary, dest, dropped=()):
    print(f"{summary['snapshot']}: {len(scored)} windows tiling "
          f"{summary['sessions']:.0f} sessions to {summary['days']:.0f} days")
    print()

    if summary["chain_vol"]:
        print(f"  the whole chain      {summary['chain_vol'] * 100:8.2f}%"
              f"   {summary['sessions']:.0f} sessions, the aggregate of the "
              f"windows below")
    if summary["chain_vol_calendar"]:
        print(f"  the same, calendar   {summary['chain_vol_calendar'] * 100:8.2f}%"
              f"   {summary['days']:.0f} days: the same variance, VIX's clock")
    if summary["rate_30d"]:
        extra = (f" ({summary['extrapolated_days']:.0f} days past the chain)"
                 if summary["extrapolated_days"] else "")
        print(f"  our 30-day rate      {summary['rate_30d'] * 100:8.2f}%"
              f"   interpolated to VIX's maturity{extra}")
        if summary["vix"]:
            print(f"  VIX the same day     {summary['vix'] * 100:8.2f}%"
                  f"   we read {summary['ours_minus_vix'] * 100:+.2f} points "
                  f"against it")
        if summary["percentile"] is not None:
            print(f"  against VIX's own history: {summary['percentile'] * 100:.0f}th "
                  f"percentile of {summary['percentile_n']:,} sessions, "
                  f"{summary['history_from']} to {summary['history_to']}")
    else:
        print("  no 30-day rate from this chain, so no percentile: the band is "
              "too narrow or the chain too short to reach 30 days")
    for exp, strikes, edge in dropped:
        print(f"    ! {exp} left out of the term structure: {strikes:.0f} strikes, "
              f"its integral still moving {edge * 100:.3f} vol points at the edge")

    print()
    print(f"  {'window':22}{'sess':>5}{'fwd vol':>10}{'+/-':>8}"
          f"{'vs rest':>10}{'vs neigh':>11}")
    for w in scored:
        label = (f"spot to {w['to_expiry'][5:]}" if w["from_expiry"] == SPOT
                 else f"{w['from_expiry'][5:]} to {w['to_expiry'][5:]}")
        vol = f"{w['forward_vol'] * 100:8.2f}%" if w["forward_vol"] else "negative"
        err = f"{w['forward_vol_error'] * 100:6.2f}p" if w["forward_vol_error"] else "     -"
        rest = (f"{w['vs_rest'] * 100:+7.2f}p{'*' if w['rest_differs'] else ' '}"
                if w["vs_rest"] is not None else "        -")
        near = (f"{w['vs_neighbours'] * 100:+8.2f}p"
                f"{'*' if w['neighbours_differ'] else ' '}"
                if w["vs_neighbours"] is not None else "         -")
        print(f"  {label:22}{w['sessions']:>5.0f}{vol:>10}{err:>8}{rest:>10}{near:>11}")

    print()
    print("  * the difference is bigger than the error on the difference")
    print("    vs rest   this window against the whole rest of the chain")
    print("    vs neigh  against the line between the two windows either side,")
    print("              read at this one's midpoint, so an uneven gap does not")
    print("              leave slope in the answer; blank at the ends")

    try:
        shown = dest.relative_to(ROOT)
    except ValueError:
        shown = dest
    print()
    print(f"  saved {shown}/")


def latest():
    folders = sorted(p for p in SURFACE_DIR.glob("*") if p.is_dir())
    if not folders:
        raise SystemExit("no fitted surfaces yet: run `python app.py surface` first")
    return folders[-1].name


def cmd_context(which=None, refresh=False):
    snapshot = which or latest()
    if not (SURFACE_DIR / snapshot).is_dir():
        raise SystemExit(f"no fitted surface at data/surface/{snapshot}")
    scored, summary, dest, dropped = analyse(snapshot, refresh)
    report(scored, summary, dest, dropped)


if __name__ == "__main__":
    cmd_context(sys.argv[1] if len(sys.argv) > 1 else None)
