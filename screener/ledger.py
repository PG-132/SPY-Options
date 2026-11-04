"""
ledger.py - every window ever priced, and what became of it. Step 7.

  python app.py ledger          rebuild, settle what has closed, report
  python app.py ledger 10       the same, showing the last 10 snapshots

context.py measures one chain against itself. This file keeps the record
across chains, which is the only place two questions can be answered:

  did this window reprice, and when
  when a window priced rich, did it deliver

Neither is visible in a single snapshot. The first needs two chains; the
second needs the window to have closed.

EVERY WINDOW, NOT THE INTERESTING ONES
--------------------------------------
Every window of every snapshot goes in, unconditionally. Logging only the
ones that looked notable on the day would build a record with a selection
effect in it: you could measure what the flagged windows did, but never
whether flagging them helped, because there would be no control group.
Filtering belongs in the view, where a wrong threshold costs a re-query
rather than a year of data.

REBUILT, NOT APPENDED
---------------------
Each run reads context's saved output for every snapshot and writes the
whole file. Appending would need dedupe logic and would freeze old rows
against whatever the code did at the time; rebuilding means a correction in
vol.py or context.py reaches the entire history on the next run. At twelve
rows a snapshot this costs nothing - twenty years of daily snapshots is 60k
rows - and the snapshots stay the only source of truth.

WHAT SETTLES, AND AGAINST WHAT
------------------------------
A window spans (start, end] in sessions, so its realized volatility is
measured over exactly those closes: open on the left, closed on the right,
the same convention vrp.py uses. The row settles once `end` is in the price
history.

One difference from vrp.realized, which refuses a window holding a single
return. Most windows here ARE one session, and a single return is a
legitimate estimate of that session's volatility - just an extremely noisy
one, which is the same |return| against the implied bar that the daily path
already reports. Refusing it would throw away the front of every chain, so
it is allowed and the session count travels with the number.

WHAT A SETTLED ROW DOES NOT PROVE
---------------------------------
One session realizing above its implied bar says nothing: a one-standard-
deviation bar is cleared about a third of the time by a market behaving
exactly as priced. These rows are only worth anything in aggregate, and the
aggregate needs event days separated from ordinary ones before it means
much - a meeting priced three points above its neighbours is normal, and a
quiet Tuesday priced the same way is not. `start_date` and `end_date` are
carried on every row so an event calendar can be joined on later without
rebuilding anything.
"""

import bisect
import collections
import csv
import json
import datetime as dt
import math
import pathlib
import sys

from screener import prices, vol, vrp

CONFIG = {
    "sessions_per_year": 252,
    # How far back the "and what was it a week ago" column looks, in calendar
    # days. A week rather than a snapshot count: snapshots are taken by hand
    # and skipping two days should widen the comparison, not silently change
    # what it means.
    "compare_days": 7,
    # A window has to have moved by more than this to be worth printing in
    # the movers table. Below it the row is still in the file - this only
    # decides what the report shows.
    "mover_points": 0.0050,
    # How much of the grid the report prints. The file holds all of it.
    "pivot_rows": 8,
    "pivot_cols": 9,
    "gaps_shown": 6,
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAIN_DIR = ROOT / "data" / "chains"
CONTEXT_DIR = ROOT / "data" / "context"
OUT_DIR = ROOT / "data" / "ledger"

COLS = ["snapshot", "asof", "kind", "spot", "band",
        "from_expiry", "to_expiry", "start_date", "end_date",
        "start_price", "sessions_ahead", "edge_margin",
        "spans_dropped", "put_skew_to", "call_skew_to",
        "sessions", "days", "forward_vol", "forward_vol_error",
        "vs_rest", "vs_rest_error", "rest_differs",
        "vs_neighbours", "vs_neighbours_error", "neighbours_differ",
        "chain_vol", "status", "realized", "realized_sessions",
        "realized_minus_priced"]
MOVER_EXTRA = ["was", "moved", "chain_moved", "moved_vs_chain", "repriced",
               "roll_down", "net_of_roll"]

SPOT = "spot"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _d(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Building the record
# ---------------------------------------------------------------------------

def snapshots(limit=None):
    """Snapshots that context.py has already written output for, oldest first."""
    out = sorted(p.name for p in CONTEXT_DIR.glob("*")
                 if (p / "windows.csv").exists())
    return out[-limit:] if limit else out


def read_snapshot(name):
    """One snapshot's windows, with the chain summary folded onto each row."""
    folder = CONTEXT_DIR / name
    with open(folder / "windows.csv", newline="", encoding="utf-8") as f:
        windows = list(csv.DictReader(f))
    chain = {}
    path = folder / "chain.csv"
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            chain = rows[0] if rows else {}
    return windows, chain


def snapshot_spot(name):
    """The spot the collector itself saw when it started.

    Only the first window needs it, and only because that window begins
    partway through a session. Missing run.json means the raw chain was
    cleared; the row then settles from the previous close as before, which
    is the old behaviour rather than a failure."""
    path = CHAIN_DIR / name / "run.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return _f(json.load(f).get("spot_at_start"))
    except (OSError, json.JSONDecodeError):
        return None


def converged(band):
    """Whether a chain this wide can carry a variance swap rate at all.

    `vrp` has refused narrow-band chains since before any of this existed,
    on the measurement that they understate the rate by 0.5 to 1.1 vol
    points. The rule is read from there rather than copied, because the one
    thing that must not happen is this module quietly keeping a different
    threshold - and because a cut-off chosen now, on the handful of
    snapshots held here, would be a cut-off chosen to make an answer come
    out."""
    try:
        return int(str(band).split("/")[0]) >= vrp.CONFIG["converged_moves"]
    except (ValueError, AttributeError, IndexError):
        return False


def snapshot_band(name, chain=None):
    """How wide a chain this window was priced off, as "below/above" in
    expected moves.

    A variance swap rate is only as complete as the strike range behind it,
    and the band is the single biggest thing moving the edge margin: over the
    snapshots held here it medians 0.376 at 12/6 against 0.622 at 6/3,
    because a tighter band cuts the integral off while it is still climbing.
    Rates collected under different bands are different quantities, so a
    study that pools them is pooling chains that were never comparable - and
    this one column is the only thing that lets a later analysis notice.

    Widening is not retroactive. A wide chain can be truncated down to match
    a narrow one by re-integrating over fewer strikes, but a narrow one can
    never be widened: those strikes were never collected.

    run.json is the source; the chain summary is the fallback for snapshots
    whose raw chain has since been cleared."""
    path = CHAIN_DIR / name / "run.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                r = json.load(f).get("rules") or {}
            if r.get("moves_below") is not None:
                return f"{r['moves_below']}/{r['moves_above']}"
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    return (chain or {}).get("band") or ""


def build(names=None):
    """One row per window per snapshot, oldest first.

    `start_date` is where the window begins on the calendar. For every window
    but the first that is the near expiry; for the first it is the snapshot's
    own date, because the window runs from the moment of the snapshot."""
    names = list(names if names is not None else snapshots())
    # The last snapshot of a date is that day's anchor and belongs to the
    # daily series; anything earlier was taken to bracket something. Three
    # snapshots on a meeting day should not give that day three times the
    # weight of every other, and the distinction has to be recorded at write
    # time because the folder names alone stop saying it once more arrive.
    anchor_of = {}
    for name in names:
        anchor_of[name[:10]] = name

    out = []
    for name in names:
        windows, chain = read_snapshot(name)
        asof = _d(chain.get("asof") or chain.get("date") or name[:10])
        spot = snapshot_spot(name)
        band = snapshot_band(name, chain)
        kind = "anchor" if anchor_of.get(name[:10]) == name else "bracket"
        ahead = 0.0                   # the windows tile, so this is cumulative
        for w in windows:
            end = _d(w["to_expiry"])
            if end is None:
                continue                  # a window with no readable far end
            start = asof if w["from_expiry"] == SPOT else _d(w["from_expiry"])
            if start is None:
                continue
            sessions = _f(w["sessions"]) or 0.0
            out.append({
                "snapshot": name, "asof": asof, "kind": kind, "spot": spot,
                "band": band,
                "from_expiry": w["from_expiry"], "to_expiry": w["to_expiry"],
                "start_date": start, "end_date": end,
                # How far ahead the window begins. This is the ageing axis:
                # a period reprices as it approaches, and without knowing the
                # distance there is no way to tell that drift from news.
                "sessions_ahead": round(ahead, 4),
                # Not derivable later: the chain that priced this window is
                # gone by the time it settles, so how well it converged has
                # to ride along with it. Carried raw, with no cutoff applied,
                # so a threshold can be chosen when there is a sample to
                # choose it on rather than baked in now.
                "edge_margin": _f(w.get("edge_margin")),
                "spans_dropped": int(_f(w.get("spans_dropped")) or 0),
                "put_skew_to": _f(w.get("put_skew_to")),
                "call_skew_to": _f(w.get("call_skew_to")),
                "sessions": sessions, "days": _f(w["days"]),
                "forward_vol": _f(w["forward_vol"]),
                "forward_vol_error": _f(w["forward_vol_error"]),
                "vs_rest": _f(w["vs_rest"]),
                "vs_rest_error": _f(w["vs_rest_error"]),
                "rest_differs": w.get("rest_differs") == "True",
                "vs_neighbours": _f(w["vs_neighbours"]),
                "vs_neighbours_error": _f(w["vs_neighbours_error"]),
                "neighbours_differ": w.get("neighbours_differ") == "True",
                "chain_vol": _f(chain.get("chain_vol")),
                "start_price": spot if w["from_expiry"] == SPOT else None,
                "status": "open", "realized": None,
                "realized_sessions": None, "realized_minus_priced": None,
            })
            ahead += sessions
    return out


def missing_sessions(rows, through=None):
    """Trading days inside the covered range that no snapshot saw.

    The record cannot distinguish a quiet day from a day nobody looked, and
    only one of those can be recovered. A gap is also the one failure that
    stays silent: an alarm not heard, a machine asleep, a token expired, and
    nothing in the output complains until someone wonders in December why
    November looks thin. Counted against the holiday table, so a closed
    market is not reported as a miss."""
    if not rows:
        return [], 0
    have = {r["asof"] for r in rows}
    start = min(have)
    end = through or max(max(have), dt.date.today())
    want = [d for d in trading_days(start - dt.timedelta(days=1), end)
            if d.weekday() < 5 and d not in vol.HOLIDAYS]
    return [d for d in want if d not in have], len(want)


def trading_days(start, end):
    """The sessions in (start, end]. Shares vol.py's holiday table rather
    than keeping a second copy that can drift out of step with it."""
    out, d = [], start + dt.timedelta(days=1)
    while d <= end:
        if d.weekday() < 5 and d not in vol.HOLIDAYS:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def pivot(rows, value="vs_neighbours", kind="anchor"):
    """Snapshots down the side, the dates being priced across the top.

    Read a row and you get one day's view of the future, which is what
    `context` prints. Read a COLUMN and you get how one date was repriced as
    it approached, which no single snapshot can show.

    The cell is vs_neighbours, not vs_rest. vs_rest spans about 7.7 points
    from the front of a chain to the back, so a window drifting toward the
    front walks that whole range with nothing repricing at all - it would
    measure position, not news. vs_neighbours removes the local slope
    wherever the window sits, so it stays comparable as the window ages. The
    cost is that the first and last window of each chain have no reading.

    A window covering several sessions fills every date it spans, which is
    honest: that is the rate priced for a block containing that date, and
    the grid gets finer toward the diagonal exactly where the market lists
    more expiries."""
    grid = collections.defaultdict(dict)
    for r in rows:
        if kind and r.get("kind") != kind:
            continue
        v = r.get(value)
        if v is None:
            continue
        for d in trading_days(r["start_date"], r["end_date"]):
            grid[r["snapshot"]][d] = v
    return grid


# ---------------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------------

def realized_over(closes, start, end, dates=None, start_price=None, span=None):
    """Annualized realized volatility over a window ending at `end`'s close.

    `closes` must be sorted by date, which is what prices.py returns.

    Two shapes, decided by whether `start_price` is given.

    Without it the window is (start, end] - it begins at `start`'s close, and
    that close is the base the first return is measured from. This is every
    window between two expiries.

    With it the window begins at a MOMENT inside `start`'s session, at that
    price, so `start`'s own close is the first thing measured rather than the
    base. This is the first window of a snapshot taken before the close: it
    prices the rest of that afternoon, and settling it from the previous
    close would drop exactly the part the snapshot could see. On 2026-09-24
    that afternoon was worth 0.46% of spot. `spot_at_start` in run.json is
    what the collector itself observed, so no intraday price feed is needed.

    `span` is the window's length in SESSIONS and becomes the denominator in
    place of the number of returns. The two agree for a close-to-close
    window; they differ for that first one, where two returns can span 1.04
    sessions and dividing by two would understate the result by a third.

    vrp.realized refuses a window holding one return, which is right for a
    monthly claim and wrong here: most windows are a single session, and one
    return is a real if very noisy reading of that session. Zero-mean, as
    everywhere else in this project - the sample mean over a handful of
    returns is noise, and subtracting it would remove real movement.

    Found by bisection rather than by filtering. Both sides of this grow:
    the windows with every snapshot and the closes with every session, so a
    scan of the whole history per row is quadratic in the thing we intend to
    keep doing daily for years. Measured at 23 seconds for twenty years of
    snapshots against today's history, against nothing at all for a bisect.
    `dates` lets the caller hoist the index out of the loop."""
    if dates is None:
        dates = [d for d, _ in closes]
    stop = bisect.bisect_right(dates, end)         # first close after `end`
    if start_price is not None:
        first = bisect.bisect_left(dates, start)   # `start`'s own close counts
        if stop <= first:
            return None, 0
        prices_in = [start_price] + [c for _, c in closes[first:stop]]
    else:
        first = bisect.bisect_right(dates, start)  # `start`'s close is the base
        if first == 0 or stop <= first:
            return None, 0
        prices_in = [c for _, c in closes[first - 1:stop]]
    rets = [math.log(b / a) for a, b in zip(prices_in, prices_in[1:])]
    if not rets:
        return None, 0
    ann = math.sqrt(CONFIG["sessions_per_year"])
    over = span if span and span > 0 else len(rets)
    return math.sqrt(sum(r * r for r in rets) / over) * ann, len(rets)


def settle(rows, closes):
    """Fill in what each closed window actually delivered.

    A window settles once the price history reaches its end date. Until then
    the row stays open and carries no verdict - not a zero, which would read
    as a quiet window rather than an unfinished one."""
    if not closes:
        return rows
    dates = [d for d, _ in closes]        # hoisted: one index, not one per row
    last = dates[-1]
    for r in rows:
        if r["end_date"] > last:
            continue
        at = r.get("start_price")
        rv, n = realized_over(closes, r["start_date"], r["end_date"], dates,
                              start_price=at,
                              span=r["sessions"] if at else None)
        if rv is None:
            continue
        r["status"] = "settled"
        r["realized"] = rv
        r["realized_sessions"] = n
        if r["forward_vol"]:
            r["realized_minus_priced"] = rv - r["forward_vol"]
    return rows


# ---------------------------------------------------------------------------
# What moved
# ---------------------------------------------------------------------------

def slot_at(curve, ahead, span, exclude=None, max_gap=1.5):
    """The window on `curve` sitting `ahead` sessions out with a span near
    `span`, or None if nothing comparable sits there.

    A slot is a position AND a length. A one-session window five sessions out
    is not the same slot as a five-session window five sessions out, so
    matching on distance alone would read the term structure's own shape as a
    change. The span tolerance is relative because a half-session error means
    something very different on a 1-session window than on a 20-session one.

    `exclude` is the (from, to) pair of the window being controlled, and it
    has to be excluded or the answer is circular. One session apart a window
    slides about one slot, which is inside max_gap, so the nearest comparable
    window to where it landed is usually itself - and a window compared with
    itself reports a roll-down of exactly zero, which reads as "this slide
    cost nothing" when the truth is that the old chain never priced that slot
    at this span and the question has no answer here."""
    tol = max(0.6, 0.25 * span)
    near = [r for r in curve
            if r.get("forward_vol") and r.get("sessions")
            and abs(r["sessions"] - span) <= tol
            and (r["from_expiry"], r["to_expiry"]) != exclude]
    if not near:
        return None
    best = min(near, key=lambda r: abs(r["sessions_ahead"] - ahead))
    return best if abs(best["sessions_ahead"] - ahead) <= max_gap else None


def movers(rows, newest=None, back_days=None):
    """The newest snapshot's windows against the same windows a week ago.

    Matched on the pair of expiries, which is what makes a window the same
    window: its session count shrinks as the chain ages but its endpoints do
    not move. The chain's own level is carried alongside, because a window
    rising with the whole chain is a different event from one rising against
    it - and so is the change in vs_neighbours.

    The expiry pair and the slot are not two ways of asking one question.
    The pair says WHICH period is being priced and is the only thing that can
    reprice; the slot says how far ahead it sat, which is what the pricing
    drifts along as the period approaches. So the pair carries the signal and
    the slot is its control, and the two are read together."""
    if not rows:
        return [], None, None
    back_days = CONFIG["compare_days"] if back_days is None else back_days
    newest = newest or max(r["snapshot"] for r in rows)
    now = [r for r in rows if r["snapshot"] == newest]
    if not now:
        return [], newest, None
    asof = now[0]["asof"]

    # The snapshot nearest to `back_days` ago, out of those that are at least
    # a day old. Nothing within a day of the newest: comparing two snapshots
    # from the same session measures the afternoon, not the week.
    #
    # And nothing collected under a different band. A wider chain carries
    # more of the smile, so its rate sits higher for reasons that have
    # nothing to do with the market - across a band change every window
    # would read as having moved, in the same direction, by about the width
    # of the difference. That is the one artefact this table cannot survive,
    # since its whole output is differences.
    band_now = next((r.get("band") for r in now if r.get("band")), None)
    older = sorted({r["snapshot"]: r["asof"] for r in rows
                    if r["asof"] < asof
                    and (not band_now or r.get("band") == band_now)}.items(),
                   key=lambda kv: abs((asof - kv[1]).days - back_days))
    if not older:
        return [], newest, None
    then_name = older[0][0]
    then_rows = [r for r in rows if r["snapshot"] == then_name]
    then = {(r["from_expiry"], r["to_expiry"]): r for r in then_rows}

    out = []
    for r in now:
        was = then.get((r["from_expiry"], r["to_expiry"]))
        if not was or not was["forward_vol"] or not r["forward_vol"]:
            continue
        row = dict(r)
        row["was"] = was["forward_vol"]
        row["moved"] = r["forward_vol"] - was["forward_vol"]
        row["chain_moved"] = ((r["chain_vol"] - was["chain_vol"])
                              if (r["chain_vol"] and was["chain_vol"]) else None)
        # What the window did beyond what the whole chain did. A general
        # repricing lifts both and leaves this near zero.
        row["moved_vs_chain"] = (row["moved"] - row["chain_moved"]
                                 if row["chain_moved"] is not None else None)
        # `moved` is mostly roll-down. A window keeps its expiries but loses
        # sessions ahead, so it slides along a term structure that need not
        # have moved at all. On the 10-20 to 10-28 pair both movers fell 4.18
        # and 4.17 points while the slot each one arrived in was priced within
        # 0.02 points of a week earlier: the whole decline was position.
        # Neither `moved` nor `moved_vs_chain` defends against that - the
        # chain's level is one number shared by every row here, so removing it
        # shifts the column and ranks nothing differently. The change in
        # vs_neighbours strips the local slope at both readings, so it is what
        # repriced. None for a chain's first and last window.
        row["repriced"] = (r["vs_neighbours"] - was["vs_neighbours"]
                           if (r["vs_neighbours"] is not None
                               and was["vs_neighbours"] is not None) else None)
        # Roll-down, measured rather than inferred. The window has slid from
        # was["sessions_ahead"] to r["sessions_ahead"], and what that slide is
        # worth is the older curve's own slope between those two slots - read
        # entirely from the older snapshot, so none of today's news leaks into
        # the control. `repriced` estimates the same quantity from local slope
        # inside one chain; this reads it across two, and where both exist they
        # are independent checks on each other.
        into = slot_at(then_rows, r["sessions_ahead"], r["sessions"],
                       exclude=(r["from_expiry"], r["to_expiry"]))
        row["roll_down"] = (into["forward_vol"] - was["forward_vol"]
                            if into else None)
        row["net_of_roll"] = (row["moved"] - row["roll_down"]
                              if row["roll_down"] is not None else None)
        out.append(row)
    # Ranked on what is left once roll-down is removed, preferring the measured
    # control to the inferred one, and falling back to the raw move only for
    # windows where neither can be computed - for those the question cannot be
    # answered here at all, so they sort last rather than looking quiet.
    def rank(r):
        for k in ("net_of_roll", "repriced"):
            if r[k] is not None:
                return (0, -abs(r[k]))
        return (1, -abs(r["moved"]))
    out.sort(key=rank)
    return out, newest, then_name


def pooled(rows):
    """Realized against priced over a set of windows, pooled in VARIANCE.

    Not the mean of their volatility differences. Most windows here hold one
    session, and one |return| annualized averages sqrt(2/pi) = 0.798 of the
    true sigma even when the pricing is exactly right - so averaging those
    readings reports a 2.5 point premium on a 12.6% chain that is entirely
    estimator artifact. Measured on the first 41 settled rows: the mean said
    -2.72 points where the artifact alone accounts for -2.54.

    Squared returns against priced variance carries no such bias, and it is
    the construction vrp.py already uses over a month."""
    rows = [r for r in rows if r["forward_vol"] and r["realized"] is not None
            and r["realized_sessions"]]
    if not rows:
        return None
    rn = sum(r["realized_sessions"] for r in rows)
    pn = sum(r["sessions"] for r in rows)
    rv = sum(r["realized"] ** 2 * r["realized_sessions"] for r in rows) / rn
    pv = sum(r["forward_vol"] ** 2 * r["sessions"] for r in rows) / pn
    if pv <= 0:
        return None
    return {"n": len(rows), "realized": math.sqrt(rv), "priced": math.sqrt(pv),
            "ratio": math.sqrt(rv / pv)}


def settled_summary(rows):
    """The closed windows, split by whether they were priced above or below
    their own chain. Not evidence yet - see the module docstring.

    Narrow-band rows are left out, not offered as an option, because
    leaving the choice to whoever reads this would just be a free
    parameter: the band that gives the nicer ratio.

    A tight band understates the integrated variance LEVEL by 0.5 to 1.1
    vol points, and that survives differencing. The band is sqrt(T)-scaled,
    so it cuts off about the same fraction of the distribution at every
    tenor and the understatement is roughly constant in vol points; a
    window differencing two such totals inherits it at close to full size.
    The realized leg is read from SPY closes and cannot be affected either
    way, so pooling these rows compares a low priced leg against an
    untouched realized one.

    What does NOT follow is any direction for the pooled ratio: the
    realized leg moves with the market, and that is what drove the gap
    between pooling and not."""
    done = [r for r in rows
            if r["status"] == "settled" and converged(r.get("band"))]
    skipped = sum(1 for r in rows if r["status"] == "settled"
                  and not converged(r.get("band")))
    everything = pooled(done)
    if not everything:
        return {"skipped": skipped} if skipped else None
    return {"all": everything,
            "rich": pooled([r for r in done if r["vs_rest"] and r["vs_rest"] > 0]),
            "cheap": pooled([r for r in done if r["vs_rest"] and r["vs_rest"] <= 0]),
            "skipped": skipped,
            "windows": len({(r["from_expiry"], r["to_expiry"]) for r in done})}


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

def spy_closes(refresh=False):
    """A seam: the tests replace this rather than the network."""
    return prices.closes(prices.history("SPY", refresh))


def analyse(limit=None, refresh=False):
    names = snapshots(limit)
    if not names:
        raise SystemExit("no context output yet: run `python app.py context` first")
    rows = settle(build(names), spy_closes(refresh))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "windows.csv", rows, COLS)
    write_pivot(OUT_DIR / "pivot.csv", pivot(rows))
    return rows, names


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(r[c], 8) if isinstance(r.get(c), float)
                            else r.get(c)) for c in cols})


def write_pivot(path, grid):
    """One row per snapshot, one column per date priced. Sparse: a cell is
    blank where that snapshot could not see that date, or where the window
    covering it was at the end of its chain and has no local reading."""
    dates = sorted({d for row in grid.values() for d in row})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["snapshot"] + [d.isoformat() for d in dates])
        for snap in sorted(grid):
            row = grid[snap]
            w.writerow([snap] + [("%.6f" % row[d]) if d in row else ""
                                 for d in dates])


def report(rows, names):
    open_n = sum(1 for r in rows if r["status"] == "open")
    print(f"{len(rows)} windows across {len(names)} snapshots, "
          f"{names[0]} to {names[-1]}")
    print(f"  {len(rows) - open_n} settled, {open_n} still open")

    gaps, expected = missing_sessions(rows)
    if gaps:
        recent = ", ".join(d.isoformat() for d in gaps[-CONFIG["gaps_shown"]:])
        more = f" (showing the last {CONFIG['gaps_shown']})" if \
            len(gaps) > CONFIG["gaps_shown"] else ""
        print(f"  ! {len(gaps)} of {expected} sessions in range were never "
              f"snapped{more}")
        print(f"    {recent}")
        print("    a missing session is not recoverable; nothing here "
              "interpolates one")

    moved, newest, then = movers(rows)
    print()
    if then is None:
        print("  only one snapshot so far: nothing to compare against yet")
    else:
        gap = (rows[-1]["asof"] - next(r["asof"] for r in rows
                                       if r["snapshot"] == then)).days
        chain_moved = next((m["chain_moved"] for m in moved
                            if m["chain_moved"] is not None), None)
        level = (f"; chain level {chain_moved * 100:+.2f}p"
                 if chain_moved is not None else "")
        print(f"  what repriced since {then} ({gap} days){level}")
        print(f"    {'window':20}{'now':>8}{'was':>8}{'moved':>8}"
              f"{'rolled':>8}{'net':>9}")

        def edge(m):
            """What is left after roll-down, by whichever control exists."""
            for k in ("net_of_roll", "repriced"):
                if m[k] is not None:
                    return m[k]
            return m["moved"]

        shown = [m for m in moved if abs(edge(m)) >= CONFIG["mover_points"]]
        for m in shown:
            label = (f"spot to {m['to_expiry'][5:]}" if m["from_expiry"] == SPOT
                     else f"{m['from_expiry'][5:]} to {m['to_expiry'][5:]}")
            rd = (f"{m['roll_down'] * 100:+7.2f}p"
                  if m["roll_down"] is not None else "      --")
            nt = (f"{m['net_of_roll'] * 100:+8.2f}p"
                  if m["net_of_roll"] is not None else "        --")
            print(f"    {label:20}{m['forward_vol'] * 100:7.2f}%"
                  f"{m['was'] * 100:7.2f}%{m['moved'] * 100:+7.2f}p"
                  f"{rd:>8}{nt:>9}")
        if not shown:
            print(f"    nothing repriced more than "
                  f"{CONFIG['mover_points'] * 100:.1f} points")
        else:
            print("    moved is the raw change and is mostly roll-down: the "
                  "window slides along")
            print("    the term structure as it loses sessions ahead. rolled "
                  "is what that slide")
            print("    was worth, read off the older curve at the slot the "
                  "window moved into,")
            print("    so net is what actually repriced. -- means no "
                  "comparable slot existed.")

        # Two independent estimates of the same quantity: the slot read across
        # snapshots, and vs_neighbours read inside each one. Where they
        # disagree, one of the two chains is locally misshapen.
        both = [m for m in moved if m["net_of_roll"] is not None
                and m["repriced"] is not None]
        if both:
            gaps = [abs(m["net_of_roll"] - m["repriced"]) for m in both]
            print(f"    slot and vs_neighbours agree to "
                  f"{sum(gaps) / len(gaps) * 100:.2f}p on average over "
                  f"{len(both)} of {len(moved)} windows")
        rolled = sum(1 for m in moved if m["roll_down"] is not None)
        print(f"    {len(moved)} windows matched on expiries, {rolled} of them "
              f"to a slot; the file holds all")

    grid = pivot(rows)
    if grid:
        snaps = sorted(grid)[-CONFIG["pivot_rows"]:]
        seen = sorted({d for n in snaps for d in grid[n]})
        newest = max(r["asof"] for r in rows)
        ahead = [d for d in seen if d >= newest][:CONFIG["pivot_cols"]]
        if ahead and len(snaps) > 1:
            print()
            print("  how each date has been priced against its neighbours, "
                  "in vol points")
            print("    " + " " * 16
                  + "".join(f"{d.isoformat()[5:]:>7}" for d in ahead))
            for n in snaps:
                cells = "".join(
                    (f"{grid[n][d] * 100:>7.1f}" if d in grid[n] else "      .")
                    for d in ahead)
                print(f"    {n:<16}{cells}")
            print("    a dot is a date that snapshot could not see, or a window")
            print("    at the end of its chain with no local reading")

    s = settled_summary(rows)
    print()
    if not s:
        print("  nothing has settled yet")
    elif not s.get("all"):
        print(f"  nothing usable has settled yet: {s['skipped']} closed "
              f"window-readings came off chains too narrow to carry a rate")
    else:
        print(f"  settled: {s['all']['n']} window-readings over "
              f"{s['windows']} distinct windows, pooled in variance")
        print(f"    {'':24}{'priced':>9}{'realized':>10}{'ratio':>8}")
        for label, key in (("all of them", "all"),
                           ("priced above their chain", "rich"),
                           ("priced below it", "cheap")):
            p = s[key]
            if not p:
                continue
            print(f"    {label:24}{p['priced'] * 100:8.2f}%"
                  f"{p['realized'] * 100:9.2f}%{p['ratio']:8.3f}"
                  f"   (n={p['n']})")
        print("    SPY realizes 0.806 of implied over the full history, so a")
        print("    ratio near that is the usual premium rather than a finding")
        print("    overlapping snapshots price the same window repeatedly, and")
        print("    only front windows have closed so far - they are the cheap")
        print("    ones, so the split above is not yet a fair comparison")
        if s.get("skipped"):
            print(f"    {s['skipped']} more closed readings are left out: "
                  f"collected under a band too")
            print(f"      narrow to carry a rate. The band is sqrt(T)-scaled, "
                  f"so the shortfall is")
            print(f"      near constant in vol points and a window inherits "
                  f"most of it.")

    try:
        shown = OUT_DIR.relative_to(ROOT)
    except ValueError:
        shown = OUT_DIR
    print()
    print(f"  saved {shown}/windows.csv")


def cmd_ledger(limit=None, refresh=False):
    try:
        n = int(limit) if limit else None
    except (TypeError, ValueError):
        n = None
    rows, names = analyse(n, refresh)
    report(rows, names)


if __name__ == "__main__":
    cmd_ledger(sys.argv[1] if len(sys.argv) > 1 else None)
