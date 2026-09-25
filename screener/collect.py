"""
collect.py — SPY option-chain snapshots from Webull. Step 1 of the screener.

  python app.py plan     which contracts a snapshot would pull; saves nothing
  python app.py snap     take one snapshot and save it under data/chains/

This is the only file in the project that talks to Webull (chosen broker for this project,
made easy with webull's sdk). It uses market
data only, never webull.trade, so nothing here can place an order.
Credentials come from WEBULL_APP_KEY / WEBULL_APP_SECRET in the environment
and are never printed.

WHAT A SNAPSHOT CAPTURES
-------------------------------------------------
Every listed SPY expiry from 1 to 30 days out, calls and puts, at every strike
from 6 expected moves below spot to 3 above. One expected move is the
at-the-money IV of the expiry closest to 30 days, times the square root of the
time to each expiry, so the band widens and narrows as that IV moves. At 12%
IV it runs 20.6% below spot to 10.3% above at 30 days, 10.0% to 5.0% at a
week, and 3.8% to 1.9% for tomorrow.

The sides differ because the skew does. SPY puts stay bid and keep real delta
far out of the money, since people pay for crash protection; calls stop being
quoted much sooner.

Nothing is capped. Numbers that would be suspicious, like an IV outside
5-60% or a band edge still carrying 1% delta, are flagged as warnings
instead. Same-day expiries are skipped (time to expiry is counted in whole
days, so they would have none left.)

One pass per run, 20 contracts per request (Webull's cap). SPY's price is
recorded before the first batch, after every few batches and after the last,
so each option can later be solved against spot at its own quote time. At 12%
IV, solving a week-out at-the-money option against a price 30 cents stale
moves its IV by 0.36 points.

WHAT IT STORES
-------------------------------------
Raw fields only; our own IVs are solved later, in step 2. One folder per run,
data/chains/YYYY-MM-DD_HHMM/ (Eastern time):

  options.csv  one row per contract, every field Webull returned. Webull's own
               IV and Greeks are renamed vendor_* so the 2 aren't mistaken
               (their theta leaves out the interest-on-strike term).
  spot.csv     the SPY quotes taken during the pass
  run.json     when it ran, the rules used, where the band's IV came from,
               what was asked for vs. received, and any warnings
"""

import csv
import datetime as dt
import json
import math
import os
import pathlib
import re
import statistics
import sys
import time
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Capture rules.
# ---------------------------------------------------------------------------

CONFIG = {
    "underlying": "SPY",
    "min_dte": 1,              # same-day expiries have no whole day left
    "max_dte": 30,             # the 30-day limit, for now
    "anchor_dte": 30,          # the expiry whose at-the-money IV sizes every band
    # How far to record, in expected moves. The two sides differ because the
    # skew does: measured on the 29-day chain on 2026-09-24, calls stopped
    # being quoted about 3.1 moves up (850 strike, last bid >= $0.05), while
    # puts still carried 1% delta about 6 moves down and stayed bid to the
    # lowest listed strike, 35% below spot.
    "moves_below": 6,
    "moves_above": 3,
    "batch": 20,               # Webull's cap on option contracts per quote request
    "throttle_s": 0.25,        # pause between requests; the rate limit is unmeasured
    "spot_every": 5,           # record SPY's price after every N option batches
    # Warnings, not caps: values that would be suspicious get flagged in run.json. (hard coded, may change later)
    "iv_plausible": (0.05, 0.60),  # an anchor IV outside this range
    # An outer strike still carrying this much delta means the band stopped
    # while the market was still pricing real risk. Bid can't be the test:
    # SPY puts stay bid 35% out of the money, so a bid check never goes quiet.
    "edge_delta": 0.01,
    "iv_fallback": 0.20,       # used only if Webull gives no anchor IV; wide on purpose (though shouldn't happen)
    "stale_after_min": 15,     # a median quote older than this means stale quotes
}

ANCHOR_WINDOW = 5.0            # dollars either side of spot, to find the at-the-money strike
LIST_PAGE_CAP = 100            # runaway stop for the contract listing

ET = ZoneInfo("America/New_York")
ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAIN_DIR = ROOT / "data" / "chains"

# Webull's own IV and Greeks, renamed so they're never mistaken for ours.
VENDOR = {"imp_vol": "vendor_iv", "delta": "vendor_delta", "gamma": "vendor_gamma",
          "theta": "vendor_theta", "vega": "vendor_vega", "rho": "vendor_rho"}

# Column order in the saved files; any other field Webull returns follows.
OPTION_COLS = ["symbol", "expiry", "dte", "strike", "right", "bid", "ask",
               "bid_size", "ask_size", "price", "volume", "open_interest",
               "quote_time", "quote_time_et", *VENDOR.values(), "batch", "fetched_at"]
SPOT_COLS = ["after_batch", "fetched_at", "price", "bid", "ask",
             "quote_time", "quote_time_et", "yield"]


# ---------------------------------------------------------------------------
# Clock, band and small helpers
# ---------------------------------------------------------------------------

def now_et():
    return dt.datetime.now(ET)


def market_open(t):
    """Regular session, Mon-Fri 9:30-16:00 ET. Holidays aren't known here;
    on a holiday the quotes come back stale and the quote-age check says so."""
    return t.weekday() < 5 and dt.time(9, 30) <= t.time() < dt.time(16, 0)


def band_pct(dte, iv, side):
    """How far one side of an expiry's band reaches, as a fraction of spot:
    moves_below or moves_above expected moves, where one expected move =
    IV x sqrt(days/365). side is "below" or "above" spot."""
    moves = CONFIG["moves_below"] if side == "below" else CONFIG["moves_above"]
    return moves * iv * math.sqrt(dte / 365)


def ms_to_et(v):
    """Webull's quote_time is epoch milliseconds; blank if it isn't."""
    try:
        return dt.datetime.fromtimestamp(int(v) / 1000, ET).isoformat(timespec="milliseconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _positive(v):
    f = _float(v)
    return f is not None and f > 0


# ---------------------------------------------------------------------------
# Webull access (market data only)
# ---------------------------------------------------------------------------

def make_client():
    key = os.environ.get("WEBULL_APP_KEY")
    secret = os.environ.get("WEBULL_APP_SECRET")
    if not key or not secret:
        sys.exit("Missing WEBULL_APP_KEY / WEBULL_APP_SECRET in the environment.")
    if key.strip().lower() in {"your-key", "your_app_key", "<your_app_key>"}:
        sys.exit("WEBULL_APP_KEY is placeholder text, not a real credential.")
    import logging
    logging.basicConfig(level=logging.WARNING, format="  [sdk] %(message)s")
    from webull.core.client import ApiClient
    from webull.data.data_client import DataClient
    api = ApiClient(key, secret, os.environ.get("WEBULL_REGION_ID", "us"))
    api._stream_logger_set = api._file_logger_set = True   # keep the SDK's own logs off
    api.set_token_dir(os.environ.get("WEBULL_OPENAPI_TOKEN_DIR")
                      or str(pathlib.Path.home() / ".webull"))
    print("connecting to Webull (if it asks for 2FA, approve it in the Webull app)")
    return DataClient(api)


_last_call = [0.0]


def throttled(fn, *a, **kw):
    """Space requests out and retry transient failures. Auth, entitlement and
    bad-symbol errors won't fix themselves, so they fail at once."""
    for attempt in range(5):
        wait = CONFIG["throttle_s"] - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            return fn(*a, **kw)
        except Exception as e:
            msg = str(e)
            fatal = any(s in msg for s in
                        ("MARKET_DATA_NOT_SUBSCRIBED", "UNAUTHORIZED", "Invalid Symbol"))
            if fatal or attempt == 4:
                raise
            print(f"  ! {type(e).__name__}, retry {attempt + 1}/4 in {2 ** attempt}s")
            time.sleep(2 ** attempt)
        finally:
            _last_call[0] = time.monotonic()


def get_spot(client, after_batch):
    """One SPY quote, stamped with when we got it."""
    row = throttled(client.market_data.get_snapshot,
                    CONFIG["underlying"], "US_STOCK").json()[0]
    return {**row, "after_batch": after_batch,
            "fetched_at": now_et().isoformat(timespec="milliseconds"),
            "quote_time_et": ms_to_et(row.get("quote_time"))}


def is_standard(r):
    """Webull lists adjusted series (e.g. 4SPY260925C00771350) that its own
    quote endpoint then rejects, failing the whole batch. Standard SPY only."""
    return (r.get("def_type") == "STANDARD"
            and r.get("root_symbol") == CONFIG["underlying"]
            and str(r.get("symbol", ""))[:1].isalpha())


def list_contracts(client, lo, hi):
    """Every standard contract listed with a strike from lo to hi, all
    expiries. This is only which contracts exist, no prices. The server's
    expiry filter doesn't work, so expiries get filtered in build_plan.
    Pages until a page brings nothing new."""
    out, seen, cursor, pages = {}, set(), None, 0
    while pages < LIST_PAGE_CAP:
        rows = throttled(client.instrument.get_option_contracts,
                         category="US_OPTION", underlying_symbols=CONFIG["underlying"],
                         strike_price_gte=math.floor(lo), strike_price_lte=math.ceil(hi),
                         page_size=1000, last_instrument_id=cursor).json() or []
        pages += 1
        fresh = [r for r in rows if r.get("symbol") not in seen]
        if not fresh:
            break
        for r in fresh:
            seen.add(r.get("symbol"))
            if is_standard(r):
                out[r["symbol"]] = r
        cursor = rows[-1].get("instrument_id")
        if cursor is None:
            break
    return out, pages


def quote_batch(client, symbols, rejected):
    """Quotes for up to 20 contracts. One symbol the server rejects fails the
    whole request, so drop it, note it in `rejected`, and ask again."""
    syms = list(symbols)
    while syms:
        try:
            return throttled(client.option_market_data.get_option_snapshot,
                             syms, "US_OPTION").json() or []
        except Exception as e:
            m = re.search(r"Invalid Symbol:\[([^\]]+)\]", str(e))
            bad = {s.strip() for s in m.group(1).split(",")} & set(syms) if m else set()
            if not bad:
                raise
            rejected.extend(sorted(bad))
            syms = [s for s in syms if s not in bad]
    return []


def anchor_iv(client, spot, today):
    """The IV that sizes every band: Webull's IV for the at-the-money call and
    put of the recorded expiry (1-30 days) closest to anchor_dte, averaged.
    Costs one small listing and one quote request. If Webull gives no IV it
    falls back, and run.json says so. Returns a dict recording where the
    number came from."""
    near, _ = list_contracts(client, spot - ANCHOR_WINDOW, spot + ANCHOR_WINDOW)
    pairs = {}                  # (dte, expiry) -> strike -> {"CALL": symbol, "PUT": symbol}
    for r in near.values():
        dte = (dt.date.fromisoformat(r["expiration_date"]) - today).days
        if CONFIG["min_dte"] <= dte <= CONFIG["max_dte"]:
            by_strike = pairs.setdefault((dte, r["expiration_date"]), {})
            by_strike.setdefault(float(r["strike_price"]), {})[r["option_type"]] = r["symbol"]

    fallback = {"iv": CONFIG["iv_fallback"], "fallback": True}
    if not pairs:
        return {**fallback, "source": "no contracts listed near spot"}
    dte, exp = min(pairs, key=lambda k: abs(k[0] - CONFIG["anchor_dte"]))
    both = {k: s for k, s in pairs[(dte, exp)].items() if "CALL" in s and "PUT" in s}
    if not both:
        return {**fallback, "source": f"no call/put pair near spot on {exp}"}
    strike = min(both, key=lambda k: abs(k - spot))
    call, put = both[strike]["CALL"], both[strike]["PUT"]

    quotes = {q.get("symbol"): q for q in quote_batch(client, [call, put], [])}
    call_iv = _float(quotes.get(call, {}).get("imp_vol"))
    put_iv = _float(quotes.get(put, {}).get("imp_vol"))
    where = {"expiry": exp, "dte": dte, "strike": strike, "call_iv": call_iv, "put_iv": put_iv}
    found = [v for v in (call_iv, put_iv) if v and v > 0]
    if not found:
        return {**fallback, **where, "source": "Webull returned no IV for the at-the-money pair"}
    return {**where, "iv": sum(found) / len(found), "fallback": False,
            "source": "Webull's IV, at-the-money call and put"}


# ---------------------------------------------------------------------------
# What to pull
# ---------------------------------------------------------------------------

def build_plan(contracts, spot, today, iv):
    """Every expiry from min_dte to max_dte; in each, calls and puts at every
    strike inside that expiry's band. Returns (per-expiry summary, contracts)."""
    by_exp = {}
    for r in contracts.values():
        by_exp.setdefault(r["expiration_date"], []).append(r)
    expiries, chosen = [], []
    for exp in sorted(by_exp):
        dte = (dt.date.fromisoformat(exp) - today).days
        if not CONFIG["min_dte"] <= dte <= CONFIG["max_dte"]:
            continue
        below, above = band_pct(dte, iv, "below"), band_pct(dte, iv, "above")
        lo, hi = spot * (1 - below), spot * (1 + above)
        rows = sorted((r for r in by_exp[exp] if lo <= float(r["strike_price"]) <= hi),
                      key=lambda r: (float(r["strike_price"]), r["option_type"]))
        strikes = sorted({float(r["strike_price"]) for r in rows})
        expiries.append({"expiry": exp, "dte": dte,
                         "band_below": round(below, 4), "band_above": round(above, 4),
                         "strike_lo": strikes[0] if strikes else None,
                         "strike_hi": strikes[-1] if strikes else None,
                         "strikes": len(strikes), "contracts": len(rows)})
        chosen += [{"symbol": r["symbol"], "expiry": exp, "dte": dte,
                    "strike": float(r["strike_price"]),
                    "right": "C" if r["option_type"] == "CALL" else "P"}
                   for r in rows]
    return expiries, chosen


def batches(seq):
    n = CONFIG["batch"]
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def prepare(client):
    """Everything before the chain quotes: SPY, the anchor IV, the listing and
    the plan. Shared by `plan` and `snap`, and printed by both."""
    start = now_et()
    spots = [get_spot(client, after_batch=0)]
    spot = float(spots[0]["price"])
    anchor = anchor_iv(client, spot, start.date())
    iv, longest = anchor["iv"], CONFIG["max_dte"]
    contracts, pages = list_contracts(client, spot * (1 - band_pct(longest, iv, "below")),
                                      spot * (1 + band_pct(longest, iv, "above")))
    expiries, chosen = build_plan(contracts, spot, start.date(), anchor["iv"])
    p = {"start": start, "spots": spots, "spot": spot, "anchor": anchor,
         "contracts": contracts, "pages": pages, "expiries": expiries, "chosen": chosen}
    print_plan(p)
    return p


def print_plan(p):
    a, start = p["anchor"], p["start"]
    n_listed = len({r["expiration_date"] for r in p["contracts"].values()})
    print(f"{CONFIG['underlying']} {p['spot']:,.2f} at {start:%a %H:%M:%S} ET, "
          f"market {'open' if market_open(start) else 'CLOSED'}")
    moves = f"{CONFIG['moves_below']} expected moves below spot, {CONFIG['moves_above']} above"
    if a["fallback"]:
        print(f"band: {moves}, at a FALLBACK {a['iv']:.0%} IV ({a['source']})")
    else:
        print(f"band: {moves}, at {a['iv']:.2%} IV "
              f"({a['expiry']} at-the-money {a['strike']:g}, {a['dte']} days out)")
    print(f"listing: {len(p['contracts']):,} standard contracts across {n_listed} expiries "
          f"({p['pages']} page{'' if p['pages'] == 1 else 's'})\n")
    print(f"  {'expiry':<12}{'DTE':>4}{'below':>8}{'above':>8}   {'strikes':<20}"
          f"{'contracts':>9}")
    for e in p["expiries"]:
        rng = (f"{e['strike_lo']:g}-{e['strike_hi']:g} ({e['strikes']})"
               if e["strikes"] else "none")
        print(f"  {e['expiry']:<12}{e['dte']:>4}{-e['band_below']:>8.1%}{e['band_above']:>8.1%}"
              f"   {rng:<20}{e['contracts']:>9,}")
    n_req = len(batches(p["chosen"]))
    n_spot = 1 + math.ceil(n_req / CONFIG["spot_every"])
    secs = (n_req + n_spot) * (CONFIG["throttle_s"] + 0.35)
    print(f"\n  TOTAL {len(p['expiries'])} expiries, {len(p['chosen']):,} contracts -> "
          f"{n_req} quote requests + {n_spot} SPY quotes, roughly {secs / 60:.1f} min")


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------

def to_row(q, c, batch_no, fetched_at):
    """Webull's fields as returned (IV and Greeks renamed vendor_*), plus our
    own columns from the contract listing."""
    row = {VENDOR.get(k, k): v for k, v in q.items()}
    row.update(symbol=c["symbol"], expiry=c["expiry"], dte=c["dte"],
               strike=c["strike"], right=c["right"],
               quote_time_et=ms_to_et(q.get("quote_time")),
               batch=batch_no, fetched_at=fetched_at)
    return row


def take_snapshot(client):
    """One pass: SPY, the anchor IV, the listing, every planned contract's
    quote, and SPY again every few batches. Writes the run folder; returns
    (folder, run)."""
    p = prepare(client)
    if not p["chosen"]:
        sys.exit(f"\nNothing selected: no listed expiries {CONFIG['min_dte']}-"
                 f"{CONFIG['max_dte']} days out.")

    meta = {c["symbol"]: c for c in p["chosen"]}
    groups = batches([c["symbol"] for c in p["chosen"]])
    spots, rows, rejected = p["spots"], [], []
    print()
    for i, group in enumerate(groups, 1):
        quotes = quote_batch(client, group, rejected)
        fetched = now_et().isoformat(timespec="milliseconds")
        rows += [to_row(q, meta[q["symbol"]], i, fetched)
                 for q in quotes if q.get("symbol") in meta]
        if i % CONFIG["spot_every"] == 0 or i == len(groups):
            spots.append(get_spot(client, after_batch=i))
        if i % 25 == 0 or i == len(groups):
            print(f"  batch {i}/{len(groups)}, {len(rows):,} quotes so far")

    run = summarize(p, now_et(), rows, spots, rejected)
    folder = write_snapshot(p["start"], rows, spots, run)
    report(folder, run)
    return folder, run


def band_edges(rows):
    """Each expiry's outermost out-of-the-money put and call, with the delta
    and bid out there. Delta near zero means the band reached past where the
    market prices anything; delta still meaningful means it stopped short."""
    by_exp = {}
    for r in rows:
        by_exp.setdefault(r["expiry"], []).append(r)
    edges = []
    for exp, rs in sorted(by_exp.items()):
        for side, right, pick in (("put", "P", min), ("call", "C", max)):
            pool = [r for r in rs if r["right"] == right]
            if pool:
                r = pick(pool, key=lambda r: r["strike"])
                edges.append({"expiry": exp, "side": side, "strike": r["strike"],
                              "delta": abs(_float(r.get("vendor_delta")) or 0.0),
                              "bid": _float(r.get("bid")) or 0.0})
    return edges


def summarize(p, end, rows, spots, rejected):
    """What run.json records: the rules, the anchor IV, the counts, and
    anything to distrust."""
    start, a, chosen = p["start"], p["anchor"], p["chosen"]
    got = {r["symbol"] for r in rows}
    missing = sorted(c["symbol"] for c in chosen
                     if c["symbol"] not in got and c["symbol"] not in rejected)
    ages = [(end - dt.datetime.fromisoformat(r["quote_time_et"])).total_seconds() / 60
            for r in rows if r.get("quote_time_et")]
    age = round(statistics.median(ages), 2) if ages else None
    prices = [float(s["price"]) for s in spots if _positive(s.get("price"))]
    edges = band_edges(rows)
    live_edges = [e for e in edges if e["delta"] >= CONFIG["edge_delta"]]

    warnings = []
    if not market_open(start):
        warnings.append(f"market closed at {start:%a %H:%M} ET: bid/ask are stale")
    if age is not None and age > CONFIG["stale_after_min"]:
        warnings.append(f"median quote is {age:.0f} min old: quotes look stale")
    lo, hi = CONFIG["iv_plausible"]
    if a["fallback"]:
        warnings.append(f"anchor IV unreadable ({a['source']}); bands sized from the "
                        f"{a['iv']:.0%} fallback")
    elif not lo <= a["iv"] <= hi:
        warnings.append(f"anchor IV {a['iv']:.1%} is outside the plausible {lo:.0%}-{hi:.0%}; "
                        f"check it before trusting this snapshot")
    if live_edges:
        warnings.append(f"{len(live_edges)} band edges still carry {CONFIG['edge_delta']:.0%} "
                        f"delta or more: the band may be cutting off strikes that matter "
                        f"(see edges in run.json)")
    if missing:
        warnings.append(f"{len(missing)} planned contracts came back without a quote")
    if rejected:
        warnings.append(f"{len(rejected)} symbols rejected by Webull")
    if p["pages"] >= LIST_PAGE_CAP:
        warnings.append("the contract listing hit its page cap; expiries may be missing")

    return {
        "underlying": CONFIG["underlying"],
        "started_et": start.isoformat(timespec="seconds"),
        "finished_et": end.isoformat(timespec="seconds"),
        "seconds": round((end - start).total_seconds(), 1),
        "market_open_at_start": market_open(start),
        "spot_at_start": p["spot"],
        "spot_range": [min(prices), max(prices)] if prices else None,
        "spot_quotes": len(spots),
        "rules": {k: CONFIG[k] for k in ("min_dte", "max_dte", "anchor_dte", "moves_below",
                                         "moves_above", "batch", "spot_every")},
        "anchor": a,
        "listing_pages": p["pages"],
        "expiries": p["expiries"],
        "requested": len(chosen),
        "received": len(rows),
        "no_bid": sum(1 for r in rows if not _positive(r.get("bid"))),
        "median_quote_age_min": age,
        "edges": edges,
        "rejected": rejected,
        "missing": missing,
        "warnings": warnings,
    }


def write_csv(path, rows, first):
    cols = [c for c in first if any(c in r for r in rows)]
    cols += sorted({k for r in rows for k in r} - set(cols))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def write_snapshot(start, rows, spots, run):
    stamp = start.strftime("%Y-%m-%d_%H%M")
    folder, n = CHAIN_DIR / stamp, 1
    while folder.exists():                      # two runs inside one minute
        n += 1
        folder = CHAIN_DIR / f"{stamp}_{n}"
    folder.mkdir(parents=True)
    write_csv(folder / "options.csv", rows, OPTION_COLS)
    write_csv(folder / "spot.csv", spots, SPOT_COLS)
    (folder / "run.json").write_text(json.dumps(run, indent=2, default=str),
                                     encoding="utf-8")
    return folder


def _shown(path):
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def report(folder, run):
    print(f"\nsaved {_shown(folder)}{os.sep}")
    print(f"  {run['received']:,} of {run['requested']:,} contracts quoted in "
          f"{run['seconds']:.0f}s ({len(run['missing'])} missing, "
          f"{len(run['rejected'])} rejected)")
    print(f"  {run['no_bid']:,} have no bid (far out of the money); kept as-is")
    if run["spot_range"]:
        lo, hi = run["spot_range"]
        print(f"  SPY moved {hi - lo:.2f} during the pass ({lo:.2f}-{hi:.2f}), "
              f"{run['spot_quotes']} quotes recorded")
    if run["median_quote_age_min"] is not None:
        print(f"  median quote age {run['median_quote_age_min']:.1f} min")
    print("  warnings: " + ("none" if not run["warnings"] else ""))
    for w in run["warnings"]:
        print(f"    ! {w}")


# ---------------------------------------------------------------------------
# Commands (called from app.py)
# ---------------------------------------------------------------------------

def cmd_plan():
    prepare(make_client())
    print("\n  plan only: two at-the-money quotes to size the band, nothing saved. "
          "`python app.py snap` takes the snapshot.")


def cmd_snap():
    take_snapshot(make_client())
