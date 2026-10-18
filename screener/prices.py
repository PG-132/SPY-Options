"""
prices.py - daily closes for SPY and the CBOE index series. Step 5 of the
screener, and the only module that talks to Yahoo.

  python app.py prices           fetch what is missing, print what is cached
  python app.py prices refresh   re-download everything

Ported from vrp_log.py in the straddle folder, where it fed the implied
against realized log. Kept as its own module for the same reason collect.py
is the only file that imports webull: a dependency on somebody else's API
lives behind one door.

WHY YAHOO AND NOT WEBULL
------------------------
Webull gives us the option chain, which is what the rest of this reads. It
does not give decades of daily closes, and realized volatility needs them:
SPY goes back to 1993 here and ^VIX to 1990, against four option snapshots.
The realized side of the comparison arrives deep on the first run; the
implied side accumulates a day at a time.

FRESHNESS
---------
The cache is compared against the last session whose close SHOULD exist, not
against a fixed age. A "four days is fresh" rule breaks on exactly the day it
matters: Friday to Tuesday over a long weekend is four days, so it served
stale data on the first session back. Holidays are not enumerated - guessing
one costs a download that returns the same data.
"""

import csv
import datetime as dt
import pathlib
import sys

SERIES = {
    "SPY": "spy_ohlc.csv",       # the underlying, for realized volatility
    "^VIX": "vix.csv",           # 30-day constant maturity, the deep implied series
    "^VIX9D": "vix9d.csv",       # 9-day: the front of the term structure
    "^VIX3M": "vix3m.csv",       # 3-month: the back of it
    "^IRX": "irx.csv",           # 13-week bill, for integrity item 1
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "prices"
COLS = ["date", "open", "high", "low", "close"]


def last_expected_session(now_utc=None):
    """The most recent session whose close should exist by now, in ET.

    `now_utc` is a seam for the tests; left out it reads the clock."""
    et = (now_utc or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(hours=4)
    d = et.date()
    if et.weekday() >= 5 or et.hour < 16:      # weekend, or before today's close
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def read_cache(path):
    if not path.exists():
        return []
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.append({"date": dt.date.fromisoformat(r["date"][:10]),
                            **{c: (float(r[c]) if r.get(c) else None)
                               for c in ("open", "high", "low", "close")}})
            except (ValueError, KeyError):
                continue
    out.sort(key=lambda r: r["date"])
    return out


def write_cache(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "date": r["date"].isoformat()})


def download(symbol):
    """The one place yfinance is imported. Returns [] rather than raising, so
    a dead API falls back to the cache instead of losing a run."""
    try:
        import yfinance as yf
    except ImportError:
        print(f"  yfinance is not installed; cannot fetch {symbol}", file=sys.stderr)
        return []
    raw = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=False)
    if raw.empty:
        return []
    out = []
    for stamp, row in raw.iterrows():
        out.append({"date": stamp.date(),
                    **{c: (float(row[c.capitalize()])
                           if c.capitalize() in raw.columns else None)
                       for c in ("open", "high", "low", "close")}})
    out.sort(key=lambda r: r["date"])
    return out


def history(symbol, refresh=False):
    """Daily bars for one symbol, oldest first, cached under data/prices/."""
    path = OUT_DIR / SERIES.get(symbol, f"{symbol.strip('^').lower()}.csv")
    cached = read_cache(path)
    if cached and not refresh and cached[-1]["date"] >= last_expected_session():
        return cached
    fetched = download(symbol)
    if not fetched:
        if cached:
            print(f"  {symbol}: download returned nothing, using the cache "
                  f"through {cached[-1]['date']}", file=sys.stderr)
            return cached
        raise SystemExit(f"no data for {symbol} and no cache to fall back on")
    write_cache(path, fetched)
    return fetched


def closes(rows):
    """[(date, close)] for the rows that have one, oldest first."""
    return [(r["date"], r["close"]) for r in rows if r["close"]]


def cmd_prices(what=None):
    refresh = str(what or "").lower() == "refresh"
    print(f"last session whose close should exist: {last_expected_session()}")
    print()
    for symbol in SERIES:
        rows = history(symbol, refresh)
        fresh = "current" if rows[-1]["date"] >= last_expected_session() else "BEHIND"
        print(f"  {symbol:<8} {len(rows):>6} sessions  "
              f"{rows[0]['date']} to {rows[-1]['date']}  {fresh}")
    try:
        shown = OUT_DIR.relative_to(ROOT)
    except ValueError:
        shown = OUT_DIR
    print()
    print(f"  cached in {shown}/")


if __name__ == "__main__":
    cmd_prices(sys.argv[1] if len(sys.argv) > 1 else None)
