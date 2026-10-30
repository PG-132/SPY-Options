"""
term.py - the time axis: what the market prices for the days BETWEEN expiries.
Step 4 of the screener.

  python app.py term                  the newest snapshot
  python app.py term 2026-10-13_1319  a particular one

surface.py fits one smile per expiry and nothing links them. An expiry's ATM
IV is an average over every session left in its window, so a month holding a
quiet fortnight and a loud week reads as one middling number. On the
2026-10-13 chain the 24-day ATM was 12.22% while the sessions inside it were
priced from 8.84% to 13.85%.

Variance adds across time; volatility does not. Total variance to an expiry is

    w = iv^2 * T

and the variance belonging to the days between two expiries is the difference
of their totals. Divide that by the sessions in the gap and you have what the
market pays for one of those sessions, which is the number that can be set
beside the session next to it.

TWO READINGS
------------
forward.csv   one row per adjacent pair: the vol priced for that gap alone.
              Where that gap is a single session, `session_priced` names the
              trading day it belongs to, so the market's opinion of one
              specific date can be followed across snapshots. SPY lists daily
              expiries about two weeks out; past that the gaps span several
              sessions and cannot be pinned to a date.
constant.csv  vol out to a FIXED number of sessions, interpolated, so one day
              compares with the next without an expiry ageing underneath it

Which one is the right unit depends on the structure. A straddle held to
expiry is a bet on the TOTAL variance of its window, so the aggregate is what
matters and the stripped view is noise. A calendar spread trades one segment
against another, so the shared time cancels and only the forward number is
the trade.

Sessions rather than calendar days for both. A gap across a weekend holds
three calendar days and one session, and only the session clock prices it in
line with its neighbours.

ERROR BARS
----------
A forward variance is a difference of two totals divided by a small session
count, which amplifies whatever error each total carries. Both sources are
propagated: the fit's standard error on the at-the-money level, and that
expiry's forward_iv_cost, which does not shrink by averaging. A one-session
window divides by 1/252, so a hundredth of a vol point on each end becomes
real uncertainty on the answer. Reported, not hidden.

NO-ARBITRAGE
------------
Total variance cannot fall as maturity grows; that prices a window of negative
variance, which is a calendar arbitrage. Checked on every pair, reported, never
silently repaired. Whether a negative one is real depends on its error bar, so
the check asks whether it is negative by MORE than that bar.
"""

import collections
import csv
import math
import pathlib
import sys

CONFIG = {
    # Horizons for the constant-maturity readings, in sessions. Kept inside
    # what the collector reaches: it anchors at 30 DTE, so the longest expiry
    # lands near 18 sessions and a 21-session horizon would be outside the
    # chain most days. These stay fixed - changing them breaks the day-to-day
    # comparison they exist for.
    "horizons": (5, 10, 15),
    "sessions_per_year": 252,
    # Which level to strip variance from. The variance swap rate is additive
    # across time where implied variance at one strike only approximately is,
    # and it carries the whole smile rather than one point on it. Falls back
    # to the at-the-money level per expiry when the chain cannot support the
    # integral, and `source` on every row says which was used.
    "prefer": "variance_swap",
    # A variance swap rate off a sparse strike grid is under-sampled, and the
    # damage lands on the term structure rather than on the number itself:
    # 2026-10-29 carried 30 strikes against 128-235 either side, read 0.7
    # points BELOW its neighbour, and produced a negative window followed by
    # a 26% one. `vs_edge_cost` catches it - 0.089 vol points there against
    # 0.013-0.036 everywhere else. Such an expiry is dropped from the term
    # structure entirely rather than falling back to the at-the-money level,
    # because a window stripping a variance swap total against an ATM total
    # is not measuring anything.
    "max_vs_edge_cost": 0.0005,
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
IV_DIR = ROOT / "data" / "iv"
SURFACE_DIR = ROOT / "data" / "surface"
OUT_DIR = ROOT / "data" / "term"

FORWARD_COLS = ["from_expiry", "to_expiry", "session_priced", "sessions",
                "sessions_calendar", "half_days", "days",
                "source", "total_var_from", "total_var_to", "forward_var",
                "forward_vol", "forward_vol_error", "atm_to", "level_to",
                "put_skew_to", "call_skew_to", "arbitrage"]
CONSTANT_COLS = ["sessions", "vol", "interpolated_between", "total_var"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load(snapshot):
    """One row per expiry, joining what vol.py measured to what surface.py fitted.

    The at-the-money level comes from the FIT rather than from expiries.csv.
    Both are honest, but the fitted one is a curve through every readable
    strike while the other interpolates between the two nearest quotes, so it
    carries far less of any single quote's noise.
    """
    expiries = {r["expiry"]: r for r in read_rows(IV_DIR / snapshot / "expiries.csv")}
    fits = read_rows(SURFACE_DIR / snapshot / "fits.csv")

    # One source for the whole snapshot, so every window differences like
    # against like. Variance swap rates are used only if enough expiries can
    # carry one.
    usable = [e for e in expiries.values()
              if _f(e.get("vs_rate")) and (_f(e.get("vs_edge_cost")) or 0.0)
              <= CONFIG["max_vs_edge_cost"]]
    use_vs = CONFIG["prefer"] == "variance_swap" and len(usable) >= 2
    out, dropped = [], []
    for fit in fits:
        e = expiries.get(fit["expiry"])
        if e is None:
            continue
        atm = _f(fit["atm_fitted"])
        sessions, T = _f(fit["sessions"]), _f(e["days_to_expiry"]) / 365.0
        if not atm or not sessions or not T:
            continue
        # The fit's own standard error on its level, and the forward's cost,
        # which is systematic and does not average away.
        n = max(1.0, _f(fit["points_fitted"]) or 1.0)
        fit_se = (_f(fit["rms_vol_pts"]) or 0.0) / 100.0 / math.sqrt(n)
        fwd_cost = _f(e["forward_iv_cost"]) or 0.0
        atm_error = math.hypot(fit_se, fwd_cost)

        vs, vs_error = _f(e.get("vs_rate")), _f(e.get("vs_edge_cost"))
        edge = _f(e.get("vs_edge_cost")) or 0.0
        if use_vs:
            if not vs or edge > CONFIG["max_vs_edge_cost"]:
                dropped.append((fit["expiry"], _f(e.get("vs_strikes")), edge))
                continue
            level, level_error, source = vs, (_f(e.get("vs_error")) or 0.0), "vs"
        else:
            level, level_error, source = atm, atm_error, "atm"

        out.append({
            "expiry": fit["expiry"],
            "sessions": sessions,
            # `sessions` is the variance clock and counts a 1pm close as about
            # half. These two come from expiries.csv and say how many whole
            # trading days the range holds and how many close early.
            "sessions_calendar": _f(e.get("sessions_calendar")) or sessions,
            "half_days": _f(e.get("half_days")) or 0.0,
            "days": _f(e["days_to_expiry"]),
            "T": T,
            "atm": atm,
            "level": level,
            # Carried, not used. The variance swap rate integrates the whole
            # smile into one number, so it is skew-inclusive and skew-blind:
            # two chains with the same rate can be shaped very differently.
            # A window whose vol falls while its skew steepens is a
            # different event from one where both fall.
            "put_skew": _f(e.get("put_skew_25d")),
            "call_skew": _f(e.get("call_skew_25d")),
            "source": source,
            "level_error": level_error,
            "total_var": level * level * T,
            # w = level^2 * T, so dw = 2 * level * T * d(level)
            "total_var_error": 2.0 * level * T * level_error,
        })
    out.sort(key=lambda r: r["sessions"])
    return out, dropped


def forward_windows(rows):
    """The gap between each adjacent pair of expiries, priced on its own."""
    out = []
    for a, b in zip(rows, rows[1:]):
        ds = b["sessions"] - a["sessions"]
        if ds <= 0:
            continue                      # same session count: nothing between them
        # Whole trading days in the window, and how many of them close at 1pm.
        # `ds` is the variance clock and is what the window divides by; `dc`
        # counts dates and is what pins a one-session window to one of them.
        # Absent on rows built before half days were modelled, and on any
        # snapshot stored then: without a 1pm close the two counts agree, so
        # falling back to the clock is exact rather than merely safe.
        dc = round(b.get("sessions_calendar", b["sessions"])
                   - a.get("sessions_calendar", a["sessions"]))
        dh = round(b.get("half_days", 0.0) - a.get("half_days", 0.0))
        dw = b["total_var"] - a["total_var"]
        years = ds / CONFIG["sessions_per_year"]
        var = dw / years
        err_w = math.hypot(a["total_var_error"], b["total_var_error"])
        err_var = err_w / years
        vol = math.sqrt(var) if var > 0 else None
        # d(vol) = d(var) / (2 * vol); undefined where vol is, so left blank
        vol_err = (err_var / (2.0 * vol)) if vol else None
        out.append({
            "from_expiry": a["expiry"], "to_expiry": b["expiry"],
            "sessions": ds, "days": round(b["days"] - a["days"], 3),
            "sessions_calendar": dc, "half_days": dh,
            "total_var_from": a["total_var"], "total_var_to": b["total_var"],
            "forward_var": var, "forward_vol": vol, "forward_vol_error": vol_err,
            "atm_to": b["atm"], "level_to": b["level"],
            "put_skew_to": b.get("put_skew"), "call_skew_to": b.get("call_skew"),
            "source": b["source"] if a["source"] == b["source"] else "mixed",
            # A window holding exactly one trading day prices exactly that
            # day, and it is the later expiry's own date: sessions are counted
            # through the expiry, so the single day in (a, b] is b. Wider
            # windows cannot be pinned to a date and are left blank. Keyed on
            # the calendar count, not the clock - a window over one 1pm close
            # still prices one date though its clock reads about 0.5.
            "session_priced": b["expiry"] if dc == 1 else "",
            # Negative variance is an arbitrage only if it is negative by more
            # than the error on the difference.
            "arbitrage": var < 0 and abs(dw) > err_w,
            "negative": var < 0,
        })
    return out


def constant_maturity(rows, sessions):
    """Volatility out to a fixed number of SESSIONS, by interpolating total
    variance. Interpolating IV instead would be wrong: variance is what adds
    across time, so a straight line between two IVs is a line through the
    wrong quantity."""
    if not rows or sessions <= 0:
        return None
    lo = hi = None
    for r in rows:
        if r["sessions"] <= sessions:
            lo = r
        if r["sessions"] >= sessions and hi is None:
            hi = r
    if lo is None or hi is None:
        return None                       # outside the chain; no extrapolating
    if lo["sessions"] == hi["sessions"]:
        w, between = lo["total_var"], lo["expiry"]
    else:
        span = hi["sessions"] - lo["sessions"]
        frac = (sessions - lo["sessions"]) / span
        w = lo["total_var"] + (hi["total_var"] - lo["total_var"]) * frac
        between = f"{lo['expiry']} to {hi['expiry']}"
    years = sessions / CONFIG["sessions_per_year"]
    return {"sessions": sessions, "vol": math.sqrt(w / years),
            "interpolated_between": between, "total_var": w}


def analyse(snapshot):
    rows, dropped = load(snapshot)
    if len(rows) < 2:
        raise SystemExit(f"{snapshot}: need at least two fitted expiries, found {len(rows)}")
    windows = forward_windows(rows)
    curve = [constant_maturity(rows, s) or {"sessions": s, "vol": None,
             "interpolated_between": "outside the chain", "total_var": None}
             for s in CONFIG["horizons"]]
    dest = OUT_DIR / snapshot
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(dest / "forward.csv", windows, FORWARD_COLS)
    write_csv(dest / "constant.csv", curve, CONSTANT_COLS)
    return rows, windows, curve, dest, dropped


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(r[c], 8) if isinstance(r.get(c), float) else r.get(c))
                        for c in cols})


def report(snapshot, rows, windows, curve, dest, dropped=()):
    print(f"{snapshot}: {len(rows)} expiries, {len(windows)} windows between them")
    print()
    used = collections.Counter(r["source"] for r in rows)
    print(f"  stripping from: " + ", ".join(f"{v} on {k}" for k, v in used.most_common()))
    for exp, strikes, edge in dropped:
        print(f"    ! {exp} left out: {strikes:.0f} strikes, its integral still moving "
              f"{edge * 100:.3f} vol points at the edge")
    print()
    print(f"  {'window':24}{'sess':>5}{'fwd vol':>10}{'+/-':>8}{'level to there':>16}")
    for w in windows:
        vol = f"{w['forward_vol'] * 100:8.2f}%" if w["forward_vol"] else "negative"
        err = f"{w['forward_vol_error'] * 100:6.2f}p" if w["forward_vol_error"] else "     -"
        label = f"{w['from_expiry'][5:]} to {w['to_expiry'][5:]}"
        # The count of dates, not the clock: printing the clock rounded is how
        # a 3.5-session window comes to call itself 4.
        sess = f"{w.get('sessions_calendar', w['sessions']):.0f}" + ("*" if w.get("half_days") else "")
        print(f"  {label:24}{sess:>5}{vol:>10}{err:>8}"
              f"{w['level_to'] * 100:15.2f}%")
    early = [w for w in windows if w.get("half_days")]
    for w in early:
        n = w["half_days"]
        held = "a 1pm close" if n == 1 else f"{n:.0f} 1pm closes"
        print(f"    * {w['from_expiry'][5:]} to {w['to_expiry'][5:]} holds {held}; "
              f"its variance clock reads {w['sessions']:.2f} sessions, "
              f"not {w['sessions_calendar']:.0f}")

    print()
    print("  constant maturity, interpolated on the session clock")
    for c in curve:
        shown = f"{c['vol'] * 100:8.2f}%" if c["vol"] else "        -"
        print(f"    {c['sessions']:>3.0f} sessions{shown}    ({c['interpolated_between']})")

    flagged = [w for w in windows if w["negative"]]
    if flagged:
        print()
        for w in flagged:
            real = "beyond its error bar" if w["arbitrage"] else "inside its error bar"
            print(f"    ! {w['from_expiry']} to {w['to_expiry']}: negative variance, {real}")
    else:
        print()
        print("  no window prices negative variance: the term structure is arbitrage-free")

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


def cmd_term(which=None):
    snapshot = which or latest()
    if not (SURFACE_DIR / snapshot).is_dir():
        raise SystemExit(f"no fitted surface at data/surface/{snapshot}")
    rows, windows, curve, dest, dropped = analyse(snapshot)
    report(snapshot, rows, windows, curve, dest, dropped)


if __name__ == "__main__":
    cmd_term(sys.argv[1] if len(sys.argv) > 1 else None)
