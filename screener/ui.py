"""
ui.py - the page: everything it shows, built here as plain data from the
screener's own code and files. ui_app.py draws it; nothing there computes.

  python app.py ui                     the page, on the newest snapshot
  python app.py ui 2026-11-05_1633     opened on a particular one
  python app.py ui --port 8051         on another port (8050 by default)
  python app.py ui --no-browser        without opening the browser

The page is local: it serves on 127.0.0.1 only, reads what the pipeline
saved, and writes nothing. Stop it with Ctrl+C in the terminal it runs in.

WHY THE SPLIT
-------------
Every number on the page has to be one the screener already stands behind:
vol.py's IVs, surface.py's fit, term.py's strip, the scenario engine's
what-ifs. The way to keep it so is to keep the drawing away from the numbers.
This file reads and arranges; ui_app.py turns what this returns into Dash
and Plotly figures and does no arithmetic on any of it. So every figure can
be tested here, offline, without Dash installed, against the files it came
from - and if the drawing ever moves to another library, only ui_app.py
changes. (docs/changes/2026-11-13-ui.md, sections 1 and 3.)

THE CHAIN VIEW: THE IV SURFACE
------------------------------
Strike across, expiry deep, IV up. Three things are drawn, and they are
different kinds of thing:

- Points: every IV vol.py solved (contracts.csv, the out-of-the-money side),
  each with its band, `iv_bid` to `iv_ask`. These are the measurements.
  Points surface.py left out of its fit (`readable` False in points.csv)
  are kept, marked, with surface.py's reason.
- Smiles: each expiry's fitted curve, through surface.py's own saved
  `fitted_iv`, only between the strikes it was fitted on.
- The surface: the same fits on one strike grid shared by every expiry.
  Any 3D library draws a surface over a grid, and the chain is not one -
  each expiry reads its own strikes - so the fit supplies the grid. It is
  evaluated through `scenario.curve` (surface.smile_basis underneath) at
  ln(K/F), the expiry's forward from the engine's own load, which is the
  same reading the engine makes for a strike vol.py could not solve. Inside
  each expiry's fitted range only: the standing rule that the curve is never
  evaluated past the strikes it was fitted on (docs/integrity.md), and the
  same range test the engine uses, so the surface covers exactly what the
  engine would read off the curve. Between two expiries the renderer draws
  the face; that part is not measured, and the page says so.

Expiries sit at their sessions from the snapshot on the engine's clock -
`scenario.point(...)["passed"]` at each expiry's date, which counts what was
left of the snapshot's own session and a 1pm close as half - so session s
on this axis is session s on the strip and on the sweep, when those come.

STEPPING THROUGH SNAPSHOTS
--------------------------
Each snapshot is read through `scenario.load`, with its points.csv and
run.json, between two `scenario.snapshot_hash`es: if the files changed in
between (an `iv` or `surface` re-run on it), the read is refused rather
than drawn from a mix. What was read is kept, keyed by that hash, so
stepping back is free and a re-derived snapshot is read again.

The axes stay fixed across the snapshots held, so a change in level shows as
a change instead of being rescaled away. They are sized from what the fits
cover and the IVs they used, not from the quotes the fit left out: across
the 22 snapshots held on 2026-11-19, the 12,000 IVs left out had a 90th
percentile of 65% and reached 130%, against 35% and 69% for the 24,952
used, and would flatten everything else.

The collector's warnings for the snapshot (run.json) sit beside the surface.
Nothing in the pipeline repeats them, and an after-the-close chain like
2026-11-05_1633 is not the same kind of reading as a 15:45 one.

THE CHAIN VIEW: THE VARIANCE STRIP
----------------------------------
term.py's time axis, as the owner reads it: the integral, and the strip it
is made of (docs/changes/2026-11-13-ui.md, 4.6).

- The integral: total variance from the snapshot to each expiry, term.py's
  `total_var` (stripped from the variance swap rate) with its error, from
  zero at the snapshot - context.py's own origin, `with_spot`, which counts
  what was left of the snapshot's session. Beside it each expiry's ATM
  total, `atm_total_var`; the gap between the two is the variance the
  wings add. Between expiries the total is read at every whole session
  through `term.constant_maturity`, the same interpolation the engine's
  time roll uses, so the page never draws a number between two expiries
  that term.py would not give.
- The strip: each window between adjacent expiries from
  `context.decompose`, the front window from the snapshot included, with
  its forward vol and error, its forward variance, its date when it holds
  one session, and term.py's marks: negative, an arbitrage beyond its
  error bar, a window widened by expiries the drop rule left out (A-015),
  and how much of the drop budget its weaker foot spent.

Positions are the engine's session clock, the one `scenario.load` builds
(`ctx["clock"]`), so session s here is session s on the surface. Expiries
the term structure left out are placed by `scenario.point`, as on the
surface, and listed with term.py's reason.

THE HIGHLIGHTS
--------------
Hovering a session on the strip, or an expiry on the surface, picks one
place in both windows (docs/changes/2026-11-13-ui.md, AC-27). Hover only
lands on points a chart carries, so every place it can land is prepared
here as a focus: each whole session, each expiry in the term structure,
each other expiry on the surface. A focus says where it is, the integral
there and how that total was read, and which window holds it. The charts
carry its key; the page looks it up and reads nothing off a chart.

Two readings matter more than they look:

- How a total was read. At an expiry it is that expiry's own, stripped.
  Between two expiries it is term.py's straight line, and its error is only
  what those two ends carry in (the most it can be, whatever their
  correlation). Inside a window standing in for dropped expiries, how the
  variance splits across its sessions is simply unknown, and the page has
  to say so rather than let a tidy interpolated number pass for a daily one
  (the owner, 2026-11-20).
- Which window holds an expiry's own session: the one ending there, as the
  ledger settles windows over (start, end]. The integral at s already holds
  it in full; the next window has added nothing yet.

And the source: term.py strips every expiry from its variance swap rate, or,
when fewer than two can carry one, from its ATM level, for the whole
snapshot. The two are different quantities. On 11-19 the 12-11 to 12-18
window read 30.90% from the variance swap and 21.88% from ATM levels; on
11-20, an ATM fallback, it read 24.35%. So a step between the two looked
like a fall of 6.5 points when like for like it rose. The strip names its
source for that reason.
"""

import json
import logging
import math
import socket
import sys
import threading
import traceback
import webbrowser

from screener import context, scenario, term

_cache = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def snapshots():
    """The snapshots the page can show, oldest first: those carried through
    the fit (`scenario.ready`)."""
    return scenario.ready()


def run_warnings(name):
    """(warnings, note): the collector's warnings for one snapshot, verbatim
    from its run.json, and a note when there are none to show, saying why."""
    path = scenario.CHAIN_DIR / name / "run.json"
    if not path.exists():
        return [], "no run.json for this snapshot, so no collector warnings to show"
    try:
        found = json.loads(path.read_text(encoding="utf-8")).get("warnings")
    except (OSError, ValueError, AttributeError) as e:
        return [], f"run.json could not be read ({e})"
    if not found:
        return [], "none"
    return [str(w) for w in found], None


def load_snapshot(name):
    """One snapshot as the engine reads it, with its points.csv and run.json,
    read between two hashes of its files and kept by that hash."""
    before = scenario.snapshot_hash(name).digest()
    with _lock:
        hit = _cache.get(name)
    if hit is not None and hit["digest"] == before:
        return hit
    ctx = scenario.load(name)
    points = scenario.read_rows(scenario.SURFACE_DIR / name / "points.csv")
    # term.load again for the drop rule's reasons, which the engine keeps only
    # by name: the same files, inside the same two hashes.
    rows, dropped = term.load(name)
    warnings, note = run_warnings(name)
    if scenario.snapshot_hash(name).digest() != before:
        raise scenario.Refused(f"{name}: its data changed while it was being read "
                               f"(was `iv`, `surface` or `daily` running on it?). "
                               f"Step to it again")
    snap = {"name": name, "digest": before, "ctx": ctx, "points": points,
            "term_rows": rows, "term_dropped": dropped,
            "warnings": warnings, "warnings_note": note}
    with _lock:
        _cache[name] = snap
    return snap


# ---------------------------------------------------------------------------
# The chain view: the IV surface
# ---------------------------------------------------------------------------

def _inside(e, K):
    """Whether strike K sits inside the expiry's fitted range: the engine's
    own test (scenario.option_leg), ln(K/F) between the outermost readable
    moneyness the fit was made on."""
    if not e["fit"] or not e["range"]:
        return False
    k = math.log(K / e["forward"])
    return e["range"][0] <= k <= e["range"][1]


def _read(name):
    """(snapshot, None), or (None, the refusal to show in its place)."""
    try:
        return load_snapshot(name), None
    except scenario.Refused as e:
        return None, {"snapshot": name, "refused": e.reasons}
    except Exception as e:                      # shown on the page, traceback here
        traceback.print_exc()
        return None, {"snapshot": name,
                      "refused": [f"could not be read: {type(e).__name__}: {e}"]}


def chain_surface(name):
    """Everything the 3D view draws for one snapshot, as plain data.

    Returns {"snapshot", "started", "spot", "expiries", "points", "smiles",
    "grid", "warnings", "warnings_note"}, or {"snapshot", "refused"} with the
    reasons when the snapshot cannot be read."""
    snap, refused = _read(name)
    if refused:
        return refused
    ctx = snap["ctx"]
    by_expiry = {}
    for r in snap["points"]:
        if scenario._f(r.get("strike")) is not None:
            by_expiry.setdefault(r["expiry"], {})[scenario._key(r["strike"])] = r

    order = sorted(ctx["expiries"], key=lambda x: ctx["expiries"][x]["date"])
    expiries, at = [], {}
    for x in order:
        e = ctx["expiries"][x]
        at[x] = scenario.point(ctx, e["date"], ctx["spot"])["passed"]
        expiries.append({"expiry": x, "sessions": at[x], "fitted": bool(e["fit"]),
                         "forward": e["forward"]})

    points = []
    for (x, K), c in sorted(ctx["contracts"].items()):
        if c["iv"] is None or x not in at:
            continue
        saved = by_expiry.get(x, {}).get(K)
        readable = bool(saved) and saved.get("readable") == "True"
        why = ("" if readable else
               (saved.get("why_not") or "left out of the fit") if saved else
               "not in surface.py's points.csv")
        points.append({"expiry": x, "strike": K, "right": c["right"], "sessions": at[x],
                       "iv": c["iv"], "iv_bid": c["iv_bid"], "iv_ask": c["iv_ask"],
                       "delta": c["delta"],
                       "fitted_iv": scenario._f(saved.get("fitted_iv")) if saved else None,
                       "residual": scenario._f(saved.get("residual")) if saved else None,
                       "readable": readable, "why_not": why})

    smiles = []
    for x in order:
        e = ctx["expiries"][x]
        line = [(K, scenario._f(r.get("fitted_iv")))
                for K, r in sorted(by_expiry.get(x, {}).items())
                if _inside(e, K) and scenario._f(r.get("fitted_iv")) is not None]
        if line:
            smiles.append({"expiry": x, "sessions": at[x],
                           "strikes": [k for k, _ in line], "iv": [v for _, v in line]})

    fitted = [x for x in order if ctx["expiries"][x]["fit"] and ctx["expiries"][x]["range"]]
    every = sorted({K for (_, K) in ctx["contracts"]})
    table = {x: [scenario.curve(ctx["expiries"][x]["fit"], math.log(K / ctx["expiries"][x]["forward"]))
                 if _inside(ctx["expiries"][x], K) else None for K in every]
             for x in fitted}
    keep = [i for i in range(len(every)) if any(table[x][i] is not None for x in fitted)]
    grid = {"strikes": [every[i] for i in keep], "expiries": fitted,
            "sessions": [at[x] for x in fitted],
            "iv": [[table[x][i] for i in keep] for x in fitted]}

    counts = {"expiries": len(expiries), "fitted": len(fitted), "points": len(points),
              "used": sum(1 for p in points if p["readable"])}
    return {"snapshot": name, "started": ctx["started"].strftime("%Y-%m-%d %H:%M"),
            "spot": ctx["spot"], "expiries": expiries, "points": points,
            "smiles": smiles, "grid": grid, "counts": counts,
            "warnings": snap["warnings"], "warnings_note": snap["warnings_note"]}


# ---------------------------------------------------------------------------
# The chain view: the variance strip
# ---------------------------------------------------------------------------

def chain_strip(name):
    """Everything the integral and the strip draw for one snapshot, as plain
    data: {"snapshot", "expiries", "integral", "windows", "dropped"}, or
    {"snapshot", "refused"}.

    `expiries` are term.py's rows on the engine's clock, the snapshot's own
    origin first; `integral` is the total at every whole session between
    them; `windows` are context.py's, each placed from its `start` to its
    `end` session; `dropped` are the expiries the drop rule left out, with
    term.py's reason and their place on the clock."""
    snap, refused = _read(name)
    if refused:
        return refused
    ctx = snap["ctx"]
    at = {r["expiry"]: r["sessions"] for r in ctx["clock"]}

    expiries = []
    for r in ctx["clock"]:
        origin = r["expiry"] == context.SPOT
        expiries.append({
            "expiry": r["expiry"], "origin": origin, "sessions": r["sessions"],
            "days": r.get("days"), "total_var": r["total_var"],
            "total_var_error": r["total_var_error"], "level": r["level"],
            "atm": None if origin else r["atm"],
            "atm_total_var": r.get("atm_total_var"),
            "atm_total_var_error": r.get("atm_total_var_error"),
            "source": r["source"]})

    last = max(at.values(), default=0.0)
    integral = []
    for s in range(1, int(last) + 1):
        cm = term.constant_maturity(ctx["clock"], s)
        if cm:
            integral.append({"sessions": float(s), "total_var": cm["total_var"],
                             "total_var_error": cm["total_var_error"],
                             "between": cm["interpolated_between"]})

    found, _ = context.decompose(snap["term_rows"], ctx["remaining"], snap["term_dropped"])
    keep = ("from_expiry", "to_expiry", "session_priced", "sessions", "sessions_calendar",
            "half_days", "days", "source", "forward_var", "forward_vol",
            "forward_vol_error", "negative", "arbitrage", "edge_margin", "spans_dropped",
            "atm_to", "level_to", "put_skew_to", "call_skew_to")
    windows = [dict({k: w.get(k) for k in keep},
                    start=at[w["from_expiry"]], end=at[w["to_expiry"]])
               for w in found if w["from_expiry"] in at and w["to_expiry"] in at]

    dropped = []
    for x, strikes, edge in snap["term_dropped"]:
        e = ctx["expiries"].get(x)
        if e is not None:
            dropped.append({"expiry": x, "strikes": strikes, "edge": edge,
                            "sessions": scenario.point(ctx, e["date"], ctx["spot"])["passed"]})
    # The expiries left out that each window stands in for, by name: the
    # ones strictly inside it on the clock. term.py counts the same ones by
    # date (`spans_dropped`); the tests hold the two to each other.
    for w in windows:
        w["left_out"] = [d["expiry"] for d in dropped if w["start"] < d["sessions"] < w["end"]]

    # term.py takes one source for the whole snapshot: the variance swap rate
    # where at least two expiries can carry one, else every expiry's ATM
    # level. The page has to say which, since the two are different
    # quantities and a step from one to the other is not a repricing.
    sources = {r["source"] for r in ctx["clock"] if r["expiry"] != context.SPOT}
    source = sources.pop() if len(sources) == 1 else ("mixed" if sources else None)

    foci, by_expiry = _foci(ctx, at, integral, windows, dropped, snap["term_dropped"])
    return {"snapshot": name, "source": source, "expiries": expiries, "integral": integral,
            "windows": windows, "dropped": dropped, "foci": foci, "focus_by_expiry": by_expiry}


def _window_at(windows, s):
    """The window holding session s: start < s <= end, as the ledger settles
    a window over (start, end]. So on an expiry's own session it is the
    window ending there - the integral at s already holds it in full, and
    the next has added nothing yet."""
    return next((i for i, w in enumerate(windows) if w["start"] < s <= w["end"]), None)


def _foci(ctx, at, integral, windows, dropped, term_dropped):
    """Everything a highlight shows, prepared for each place it can land.

    Hover snaps to the points a chart carries and never reads between them
    (docs/changes/2026-11-13-ui.md, section 9), so a highlight can only be at
    a point the view supplies: every whole session, every expiry in the term
    structure, and every other expiry on the surface. Each gets a focus,
    keyed by its place in the list; the charts carry that key on each point,
    and the page looks a highlight up rather than reading a position off the
    chart. Each holds:

      sessions     where it sits on the engine's clock
      kind         "session", "expiry", or "outside" (on the surface, not in
                   the term structure)
      total_var    the integral there, with total_var_error; None outside
      at_expiry    True when that total is an expiry's own stripped one;
                   False when term.py read it on its straight line between
                   two expiries - its error then comes from those two only
                   and says nothing about how variance is spread between
                   them (AC-33)
      between      term.py's own words for where it read the total
      window       the index of the window holding it, or None past the
                   last expiry the term structure kept
      reason       for an expiry outside the term structure: why

    Also returned: each expiry's key, for the surface's points and smiles."""
    foci, by_expiry = [], {}
    stops = set(at.values())

    def add(**f):
        f["key"] = len(foci)
        foci.append(f)
        return f["key"]

    for p in integral:
        # A snapshot taken after the close puts every expiry on a whole
        # session, and there the total is that expiry's own: stripped, not
        # read off a line, whatever the window before it stands in for.
        p["at_expiry"] = p["sessions"] in stops
        p["window"] = _window_at(windows, p["sessions"])
        p["widened"] = (not p["at_expiry"] and p["window"] is not None
                        and bool(windows[p["window"]]["spans_dropped"]))
        p["key"] = add(kind="session", sessions=p["sessions"], expiry=None,
                       total_var=p["total_var"], total_var_error=p["total_var_error"],
                       at_expiry=p["at_expiry"], between=p["between"],
                       window=p["window"], reason=None)
    for r in ctx["clock"]:
        if r["expiry"] == context.SPOT:
            continue
        w = next((i for i, w in enumerate(windows) if w["to_expiry"] == r["expiry"]), None)
        by_expiry[r["expiry"]] = add(
            kind="expiry", sessions=r["sessions"], expiry=r["expiry"],
            total_var=r["total_var"], total_var_error=r["total_var_error"], at_expiry=True,
            between=r["expiry"], window=w, reason=None)

    why = {d["expiry"]: d for d in dropped}
    for x in sorted(ctx["expiries"], key=lambda x: ctx["expiries"][x]["date"]):
        if x in by_expiry:
            continue
        s = scenario.point(ctx, ctx["expiries"][x]["date"], ctx["spot"])["passed"]
        d = why.get(x)
        reason = (f"left out of the term structure (A-015): {d['strikes']:.0f} strikes, its "
                  f"integral still moving {100 * d['edge']:.3f} vol points at the edge"
                  if d else "not in the term structure: surface.py has no fit for it")
        w = next((i for i, w in enumerate(windows) if w["start"] < s < w["end"]), None)
        by_expiry[x] = add(kind="outside", sessions=s, expiry=x, total_var=None,
                           total_var_error=None, at_expiry=False, between=None,
                           window=w, reason=reason)
    return foci, by_expiry


def axis_ranges(names):
    """Axes that stay put while stepping: strike and IV over what every
    snapshot's fit covers and the points it used, sessions from 0 to the
    furthest expiry, and the strip's total variance and forward vol from 0
    to the top of the highest error bar. None if no snapshot could be read."""
    strikes, ivs, sessions, totals, vols = [], [], [0.0], [0.0], [0.0]
    for name in names:
        v = chain_surface(name)
        if v.get("refused"):
            continue
        strikes += v["grid"]["strikes"]
        ivs += [z for row in v["grid"]["iv"] for z in row if z is not None]
        for p in v["points"]:
            if p["readable"]:
                strikes.append(p["strike"])
                ivs += [z for z in (p["iv_bid"], p["iv_ask"]) if z is not None]
        sessions += [x["sessions"] for x in v["expiries"]]
        # The strip's two value axes reach the top of every error bar, so no
        # bar is cut off at any snapshot. Display ranges only: no figure.
        s = chain_strip(name)
        for x in s["expiries"]:
            for value, err in (("total_var", "total_var_error"),
                               ("atm_total_var", "atm_total_var_error")):
                if x.get(value) is not None:
                    totals.append(x[value] + (x.get(err) or 0.0))
        for w in s["windows"]:
            if w["forward_vol"] is not None:
                vols.append(w["forward_vol"] + (w["forward_vol_error"] or 0.0))
    if not strikes or not ivs:
        return None
    return {"strike": [min(strikes), max(strikes)], "sessions": [0.0, max(sessions)],
            "iv": [min(ivs), max(ivs)], "total_var": [0.0, max(totals)],
            "forward_vol": [0.0, max(vols)]}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def cmd_ui(which=None, port=8050, browser=True):
    try:
        from screener import ui_app
    except ImportError as e:
        sys.exit(f"The page needs Dash and Plotly ({e}). Install them with:\n"
                 f"  python -m pip install -r requirements.txt")
    names = snapshots()
    if which and which not in names:
        sys.exit(f"{which} is not a snapshot carried through `surface`; "
                 f"those are in data/surface/ with their fits.csv")
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(f"Port {port} is in use (is the page already running?). "
                     f"Try: python app.py ui --port {port + 1}")
    app = ui_app.create_app(which)
    # One line per request in the terminal is noise; errors still print.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    url = f"http://127.0.0.1:{port}/"
    print(f"SPY screener page: {url}")
    print("  serving on this machine only; stop it with Ctrl+C")
    if browser:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
