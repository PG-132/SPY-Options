"""
vrp.py - implied against realized, one claim per month. Step 5b.

  python app.py vrp          the table
  python app.py vrp update   recompute from the cached prices

Ported from vrp_log.py in the straddle folder. The premise is unchanged: on
the first session of a month the options imply some volatility for the month
ahead, a month later we know what happened, and one row holds both.

Implied is forward-looking, so the only honest realized number is measured
over the SAME forward window. Not the trailing month, which is what most
write-ups use because it is available immediately.

WHY MONTHLY
-----------
A claim every session gives ~250 rows a year that each share 20/21 of their
data with the one before. They cannot be averaged without double counting,
and day-to-day wobble on SPY is mostly noise. Month anchors are naturally
non-overlapping: every row is an independent observation and only one claim
is open at a time. Nothing is lost - the raw closes are cached, so any other
anchoring can be re-derived.

This is also the binding constraint on ever testing anything predictive here.
Thirty-six years of prices is about 430 independent monthly observations, not
9,000 daily ones.

TWO IMPLIED SOURCES, AND THEY ARE NOW THE SAME QUANTITY
-------------------------------------------------------
^VIX reaches back to 1990 and is the only implied series with real history.
It is SPX, and a variance swap integral across out-of-the-money strikes
rather than an at-the-money quote.

The original file said our own SPY series would "sit alongside it, never
pooled with it", and at the time that was right: an at-the-money quote is a
different quantity, running about 0.80 of VIX. Since `vol.variance_swap` we
compute the same kind of number, and on 2026-10-15 ours read 16.46% against
VIX's 16.46%. So the two can finally be compared, and `iv_source` records
which produced each row.

What has not changed is depth. Ours starts at 2026-10-15 and needs a snapshot
on the first session of a month to anchor one, so the monthly log will run on
^VIX for a long time yet.

Realized: zero-mean sqrt(mean(r^2)) on close-to-close log returns, annualized
by sqrt(252). The straddle workbook's own convention, kept so the two agree.
"""

import csv
import datetime as dt
import math
import pathlib
import sys

from screener import prices

CONFIG = {
    "horizon_months": 1,
    "sessions_per_year": 252,
    # Our own rate is read at VIX's maturity so the two line up. The chain
    # tops out near 29 days, so a little extension is allowed; past this the
    # snapshot is not asked to reach.
    "target_days": 30,
    "max_extrapolation_days": 5,
    # Chains collected under a narrow band cannot carry a variance swap rate
    # at all. See docs/measurements.md.
    "converged_moves": 12,
    # An anchor has to be near the start of its month. SPY's history begins
    # 1993-01-29, which made that date "January's first session": its window
    # ran to 28 February and shared 18 of its 19 sessions with February's.
    # A real anchor lands on the 1st to 3rd.
    "max_anchor_day": 7,
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
IV_DIR = ROOT / "data" / "iv"
OUT_DIR = ROOT / "data" / "vrp"
LOG_COLS = ["anchor", "window_end", "months", "iv", "iv_source", "realized",
            "rv_to_date", "sessions", "sessions_expected", "status"]
OURS_COLS = ["snapshot", "date", "spy_vs_30d", "extrapolated_days", "band", "vix",
             "ours_minus_vix"]
DAILY_COLS = ["anchor", "session", "date", "close", "ret", "abs_ret", "bar", "beat",
              "rv_ann", "rv_minus_iv", "beat_rate", "iv", "status"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def add_months(d, n):
    """Calendar months, clamping the day. 31 Jan plus one month is 28 Feb."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    day = min(d.day, [31, 29 if (y % 4 == 0 and (y % 100 or y % 400 == 0)) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day)


def realized(closes, start, end):
    """Annualized realized vol over the sessions in (start, end].

    The session count is whatever the calendar held. Holidays make it vary and
    pretending otherwise would misstate the vol."""
    window = [(d, c) for d, c in closes if start < d <= end]
    prior = [(d, c) for d, c in closes if d <= start]
    if len(window) < 2 or not prior:
        return None, len(window)
    series = [prior[-1]] + window
    rets = [math.log(b / a) for (_, a), (_, b) in zip(series, series[1:])]
    ann = math.sqrt(CONFIG["sessions_per_year"])
    return math.sqrt(sum(r * r for r in rets) / len(rets)) * ann, len(rets)


def month_anchors(closes):
    """The first session of each month present in the data."""
    seen, out = set(), []
    for d, _ in closes:
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def business_days(start, end):
    """Weekdays in (start, end]. Holidays are not removed: this is only the
    expected count, shown beside the actual one so a short month is visible."""
    n, d = 0, start + dt.timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


def build(spy_closes, vix_closes, months=None):
    """One row per month, anchored on its first session."""
    months = months or CONFIG["horizon_months"]
    vix = dict(vix_closes)
    last = spy_closes[-1][0]
    rows = []
    for anchor in month_anchors(spy_closes):
        level = vix.get(anchor)
        if level is None:
            continue                       # no implied reading that day
        if anchor.day > CONFIG["max_anchor_day"]:
            continue                       # a partial month at the start of the data
        end = add_months(anchor, months)
        closed = end <= last
        rv, n = realized(spy_closes, anchor, min(end, last))
        rows.append({
            "anchor": anchor, "window_end": end, "months": months,
            "iv": level / 100.0, "iv_source": "^VIX",
            "realized": rv if closed else None,
            "rv_to_date": rv, "sessions": n,
            "sessions_expected": business_days(anchor, end),
            "status": "closed" if closed else "open",
        })
    return rows


# ---------------------------------------------------------------------------
# Day by day inside each window
# ---------------------------------------------------------------------------

def daily_path(spy_closes, log):
    """One row per session, carrying the bar its window was anchored at.

    This is the straddle workbook's vol block generalised from one position to
    the market - its Daily Log columns D, E, F, G, M and N: return, absolute
    return, the daily bar, whether the day beat it, expanding realized vol,
    and realized minus implied.

    The BAR is the window's implied vol divided by sqrt(252): the one-day move
    implied at the anchor, held fixed across the window exactly as the sheet
    holds entry IV fixed. Realized expands from the anchor, so it is the same
    number the monthly row will end on, watched while it forms.

    A fair market does NOT beat a one-standard-deviation bar half the time.
    For a normal it is 31.7%, and the median session comes in at 0.67 bars.
    The straddle tool's note said 50%, which is wrong and would have made
    every window look quiet.
    """
    by_date = dict(spy_closes)
    dates = [d for d, _ in spy_closes]
    out = []
    for row in log:
        anchor, end, iv = row["anchor"], row["window_end"], row["iv"]
        bar = iv / math.sqrt(CONFIG["sessions_per_year"])
        prior = [d for d in dates if d <= anchor]
        if not prior:
            continue
        prev = by_date[prior[-1]]
        logs, beats = [], 0
        for d in dates:
            if not (anchor < d <= end):
                continue
            close = by_date[d]
            simple = close / prev - 1
            logs.append(math.log(close / prev))
            rv = math.sqrt(sum(x * x for x in logs) / len(logs)) *                 math.sqrt(CONFIG["sessions_per_year"])
            hit = abs(simple) > bar
            beats += hit
            out.append({
                "anchor": anchor, "session": len(logs), "date": d,
                "close": round(close, 4), "ret": round(simple, 6),
                "abs_ret": round(abs(simple), 6), "bar": round(bar, 6),
                "beat": hit, "rv_ann": round(rv, 6),
                "rv_minus_iv": round(rv - iv, 6),
                "beat_rate": round(beats / len(logs), 4),
                "iv": round(iv, 6), "status": row["status"],
            })
            prev = close
    return out


# ---------------------------------------------------------------------------
# Our own implied series, from the snapshots
# ---------------------------------------------------------------------------

def converged(band):
    try:
        return int(str(band).split("/")[0]) >= CONFIG["converged_moves"]
    except (ValueError, AttributeError, IndexError):
        return False


def our_rate(snapshot):
    """Our variance swap rate at VIX's maturity, from one snapshot.

    Interpolated in TOTAL variance against calendar days, because that is what
    adds across time. Expiries whose integral has not converged are left out,
    and a chain collected under a narrow band is refused outright: its rate is
    understated by 0.5 to 1.1 vol points and would read as a real move."""
    path = IV_DIR / snapshot / "expiries.csv"
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows or not converged(rows[0].get("collected_band")):
        return None
    pts = sorted((_f(r["days_to_expiry"]), _f(r["vs_rate"])) for r in rows
                 if _f(r.get("vs_rate")) and
                 (_f(r.get("vs_edge_cost")) or 0.0) <= 0.0005)
    if len(pts) < 2:
        return None

    target = CONFIG["target_days"]
    lo = max((p for p in pts if p[0] <= target), default=None)
    hi = min((p for p in pts if p[0] >= target), default=None)
    if lo and hi and lo != hi:
        wlo, whi = lo[1] ** 2 * lo[0], hi[1] ** 2 * hi[0]
        w = wlo + (whi - wlo) * (target - lo[0]) / (hi[0] - lo[0])
        short = 0.0
    elif lo:
        short = target - lo[0]
        if short > CONFIG["max_extrapolation_days"]:
            return None
        w = lo[1] ** 2 * target          # hold variance per day flat past the end
    else:
        return None
    return {"rate": math.sqrt(w / target), "extrapolated_days": round(short, 2),
            "band": rows[0].get("collected_band", "")}


def our_series(vix_closes):
    """One row per snapshot that can carry a rate, beside VIX the same day."""
    vix = dict(vix_closes)
    out = []
    for folder in sorted(p for p in IV_DIR.glob("*") if p.is_dir()):
        got = our_rate(folder.name)
        if not got:
            continue
        try:
            when = dt.date.fromisoformat(folder.name[:10])
        except ValueError:
            continue
        level = vix.get(when)
        out.append({
            "snapshot": folder.name, "date": when,
            "spy_vs_30d": got["rate"], "extrapolated_days": got["extrapolated_days"],
            "band": got["band"], "vix": (level / 100.0) if level else None,
            "ours_minus_vix": (got["rate"] - level / 100.0) if level else None,
        })
    return out


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

def analyse(refresh=False):
    spy = prices.closes(prices.history("SPY", refresh))
    vix = prices.closes(prices.history("^VIX", refresh))
    log = build(spy, vix)
    daily = daily_path(spy, log)
    ours = our_series(vix)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "vrp_monthly.csv", log, LOG_COLS)
    write_csv(OUT_DIR / "daily.csv", daily, DAILY_COLS)
    write_csv(OUT_DIR / "our_implied.csv", ours, OURS_COLS)
    return log, daily, ours


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: (r[c].isoformat() if isinstance(r.get(c), dt.date)
                            else r.get(c)) for c in cols})


def report(log, daily, ours, show=15):
    closed = [r for r in log if r["status"] == "closed" and r["realized"] is not None]
    print(f"IMPLIED vs REALIZED - SPY, one claim per month, "
          f"{CONFIG['horizon_months']}-month horizon")
    print("source ^VIX (30d constant maturity) - realized annualized x sqrt(252)")
    print()
    print(f"  {'month':<10}{'window':>26}{'implied':>10}{'realized':>10}"
          f"{'premium':>10}{'sess':>9}")
    for r in log[-show:]:
        win = f"{r['anchor']} to {r['window_end']}"
        if r["status"] == "closed" and r["realized"] is not None:
            prem = (r["iv"] - r["realized"]) * 100
            print(f"  {r['anchor'].strftime('%Y-%m'):<10}{win:>26}{r['iv']*100:>9.2f}%"
                  f"{r['realized']*100:>9.2f}%{prem:>+9.2f} {r['sessions']:>8.0f}")
        else:
            rv = f"{r['rv_to_date']*100:.2f}%" if r["rv_to_date"] else "-"
            print(f"  {r['anchor'].strftime('%Y-%m'):<10}{win:>26}{r['iv']*100:>9.2f}%"
                  f"{rv:>10}{'in progress':>10}"
                  f"{r['sessions']:>6.0f}/{r['sessions_expected']:.0f}")

    if closed:
        n = len(closed)
        prem = [r["iv"] - r["realized"] for r in closed]
        beat = sum(1 for p in prem if p < 0)
        print()
        print(f"  {n} completed months, each an independent observation")
        print(f"    implied mean {sum(r['iv'] for r in closed)/n*100:.2f}%   "
              f"realized mean {sum(r['realized'] for r in closed)/n*100:.2f}%   "
              f"premium {sum(prem)/n*100:+.2f} pts")
        print(f"    realized exceeded implied in {beat} of {n} months "
              f"({beat/n*100:.0f}%)")
        live = [r for r in log if r["status"] == "open"]
        if live:
            cur = live[-1]["iv"]
            pct = sum(1 for r in closed if r["iv"] < cur) / n * 100
            print(f"    the open claim at {cur*100:.2f}% sits at the "
                  f"{pct:.0f}th percentile of those months")

    # Consecutive windows can share a session or two, because a calendar
    # month from one month's first session can reach past the next month's.
    # Each window's own path stays whole - it has to end on the realized
    # figure its monthly row reports - so the overlap is removed here
    # instead, by counting each session once.
    closed_days, seen = [], set()
    for r in daily:
        if r["status"] == "closed" and r["date"] not in seen:
            seen.add(r["date"])
            closed_days.append(r)
    if closed_days:
        beats = sum(1 for r in closed_days if r["beat"])
        n = len(closed_days)
        print()
        print(f"  DAY BY DAY - {n:,} sessions inside those windows")
        print(f"    beat the implied one-day bar {beats:,} times ({beats/n*100:.1f}%)")
        print("    a fair market clears a one-standard-deviation bar 31.7% of the time,")
        print("    so under that is the premium showing up session by session")
        worst = max(closed_days, key=lambda r: r["abs_ret"])
        print(f"    biggest session: {worst['date']} at {worst['ret']*100:+.2f}%, "
              f"{worst['abs_ret']/worst['bar']:.1f} bars")

    print()
    if ours:
        print("  OUR OWN variance swap rate at the same maturity, per snapshot")
        print(f"    {'snapshot':<18}{'ours':>8}{'^VIX':>8}{'gap':>8}{'band':>7}{'extrap':>8}")
        for r in ours:
            v = f"{r['vix']*100:7.2f}%" if r["vix"] else "       -"
            g = f"{r['ours_minus_vix']*100:+7.2f}" if r["ours_minus_vix"] is not None else "      -"
            print(f"    {r['snapshot']:<18}{r['spy_vs_30d']*100:7.2f}%{v}{g}"
                  f"{r['band']:>7}{r['extrapolated_days']:>7.1f}d")
        print("    (ours is SPY and intraday; VIX is SPX at the close, so these")
        print("     are close cousins rather than the same reading)")
    else:
        print("  no snapshot can carry a variance swap rate yet: needs a chain")
        print(f"  collected at {CONFIG['converged_moves']} moves or wider, reaching "
              f"{CONFIG['target_days']} days")


def cmd_vrp(what=None):
    log, daily, ours = analyse(refresh=str(what or "").lower() == "refresh")
    report(log, daily, ours)
    try:
        shown = OUT_DIR.relative_to(ROOT)
    except ValueError:
        shown = OUT_DIR
    print()
    print(f"  saved {shown}/")


if __name__ == "__main__":
    cmd_vrp(sys.argv[1] if len(sys.argv) > 1 else None)
