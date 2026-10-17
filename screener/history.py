"""
history.py - the same surface seen from several days. Step 4b of the screener.

  python app.py history        every snapshot that has been through `term`
  python app.py history 8      only the most recent 8

Everything before this reads one snapshot. Three questions need more than one,
and they are different questions that get confused with each other constantly:

  FIXED EXPIRY      follow one contract as it ages. What a position actually
                    experiences. Confounded on purpose: when an expiry's IV
                    falls you cannot tell from this view alone whether the
                    market calmed down or the expiry simply got older. Skew
                    especially shrinks with maturity as a structural matter
                    rather than as news.

  CONSTANT MATURITY hold the horizon, let the expiry roll. Is vol higher than
                    yesterday, all else equal? This is the view that separates
                    the two things the first one mixes, and it is what VIX
                    does.

  PER SESSION       hold the calendar DATE, watch the market change its mind
                    about it. Is the market getting more worried about next
                    Thursday? Only available where expiries are consecutive
                    daily ones, so roughly two weeks out on SPY.

Which one is right depends on what is being asked, and none of them is the
default. A straddle held to expiry lives in the first. A question about
whether today was a risk-off day lives in the second. An economic calendar
lives in the third.

Nothing here is a forecast. These are three ways of reading what the market
already priced, on days we happened to record.
"""

import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
IV_DIR = ROOT / "data" / "iv"
TERM_DIR = ROOT / "data" / "term"
OUT_DIR = ROOT / "data" / "history"

# Below this many expected moves on the put side a chain is too narrow to
# carry a variance swap rate: measured on 2026-10-15, the integral stops
# moving at about 12 moves and seven of thirteen expiries gained nothing at
# all between 12 and 20. So 12/6 and 20/10 compare fine with each other and
# neither compares with 6/3. A warning that fires on every band difference
# would fire forever and be ignored.
CONVERGED_MOVES = 12


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_rows(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def snapshots(limit=None):
    """Every snapshot that has been all the way through `term`, oldest first."""
    found = sorted(p.name for p in TERM_DIR.glob("*") if p.is_dir())
    return found[-limit:] if limit else found


def load(snaps):
    out = {}
    for s in snaps:
        out[s] = {
            "expiries": {r["expiry"]: r for r in read_rows(IV_DIR / s / "expiries.csv")},
            "band": next((r.get("collected_band", "")
                          for r in read_rows(IV_DIR / s / "expiries.csv")), ""),
            "constant": {int(_f(r["sessions"])): r
                         for r in read_rows(TERM_DIR / s / "constant.csv")},
            "sessions": {r["session_priced"]: r
                         for r in read_rows(TERM_DIR / s / "forward.csv")
                         if r.get("session_priced")},
        }
    return out


def fixed_expiry(data, snaps, min_seen=2):
    """One row per expiry, one column per snapshot: how the market's view of
    that specific contract moved while it aged."""
    seen = {}
    for s in snaps:
        for e in data[s]["expiries"]:
            seen.setdefault(e, []).append(s)
    rows = []
    for e in sorted(seen):
        if len(seen[e]) < min_seen:
            continue
        row = {"expiry": e}
        for s in snaps:
            r = data[s]["expiries"].get(e)
            row[s] = None if r is None else {
                "dte": _f(r["dte"]), "sessions": _f(r["sessions"]),
                "atm": _f(r["atm_iv"]), "skew": _f(r["put_skew_25d"]),
            }
        rows.append(row)
    return rows


def constant_maturity(data, snaps):
    """One row per horizon. These are the only numbers here that mean the same
    thing on every line, because nothing ages underneath them."""
    horizons = sorted({h for s in snaps for h in data[s]["constant"]})
    return [{"sessions": h,
             **{s: _f((data[s]["constant"].get(h) or {}).get("vol")) for s in snaps}}
            for h in horizons]


def per_session(data, snaps, min_seen=2):
    """One row per future trading day, one column per snapshot: what the
    market paid for that single session, each time we looked."""
    seen = {}
    for s in snaps:
        for d in data[s]["sessions"]:
            seen.setdefault(d, []).append(s)
    rows = []
    for d in sorted(seen):
        if len(seen[d]) < min_seen:
            continue
        row = {"session": d}
        for s in snaps:
            r = data[s]["sessions"].get(d)
            row[s] = None if r is None else {
                "vol": _f(r["forward_vol"]), "error": _f(r["forward_vol_error"]),
            }
        rows.append(row)
    return rows


def _pct(v, width=9):
    return f"{v * 100:{width - 1}.2f}%" if v is not None else " " * (width - 1) + "-"


def converged(band):
    """Is this band wide enough that its variance swap rates compare with any
    other wide one? Unrecorded counts as not, since it predates the column."""
    try:
        return int(str(band).split("/")[0]) >= CONVERGED_MOVES
    except (ValueError, AttributeError, IndexError):
        return False


def report(snaps, fixed, constant, sessions, bands=None):
    short = [s[5:10] for s in snaps]
    print(f"{len(snaps)} snapshots: {', '.join(snaps)}")
    narrow = [s for s in snaps if not converged((bands or {}).get(s))]
    if bands and narrow and len(narrow) < len(snaps):
        print()
        print(f"  ! {len(narrow)} of {len(snaps)} chains here are too narrow to carry "
              f"a variance swap rate:")
        for s in snaps:
            mark = "narrow" if s in narrow else "ok"
            print(f"      {s}  {bands.get(s) or 'unrecorded':>7}  {mark}")
        print(f"    Under {CONVERGED_MOVES} moves the rate is understated by 0.5 to 1.1 vol")
        print("    points. Rows crossing that line compare different quantities.")

    print()
    print("  CONSTANT MATURITY - the horizon is pinned, so these compare directly")
    print(f"    {'sessions':>9}" + "".join(f"{h:>10}" for h in short))
    for row in constant:
        print(f"    {row['sessions']:>9.0f}" + "".join(_pct(row[s], 10) for s in snaps))

    print()
    print("  FIXED EXPIRY - at-the-money IV, with sessions left in brackets.")
    print("  Falling IV here may be the market calming down OR the expiry ageing.")
    print(f"    {'expiry':12}" + "".join(f"{h:>16}" for h in short))
    for row in fixed:
        cells = []
        for s in snaps:
            c = row[s]
            cells.append("               -" if c is None
                         else f"{c['atm'] * 100:10.2f}% ({c['sessions']:>2.0f})")
        print(f"    {row['expiry']:12}" + "".join(cells))

    print()
    if sessions:
        print("  PER SESSION - what one specific trading day cost, each time we looked")
        print(f"    {'session':12}" + "".join(f"{h:>10}" for h in short))
        for row in sessions:
            cells = []
            for s in snaps:
                c = row[s]
                cells.append("         -" if c is None else _pct(c["vol"], 10))
            print(f"    {row['session']:12}" + "".join(cells))
    else:
        print("  PER SESSION - nothing yet: needs one trading day priced in two snapshots")


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def analyse(limit=None):
    snaps = snapshots(limit)
    if len(snaps) < 2:
        raise SystemExit(f"history needs at least two snapshots through `term`, "
                         f"found {len(snaps)}")
    data = load(snaps)
    fixed = fixed_expiry(data, snaps)
    constant = constant_maturity(data, snaps)
    sessions = per_session(data, snaps)
    bands = {s: data[s]["band"] for s in snaps}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "constant_maturity.csv", constant, ["sessions"] + snaps)
    write_csv(OUT_DIR / "fixed_expiry.csv",
              [{"expiry": r["expiry"],
                **{s: (r[s]["atm"] if r[s] else None) for s in snaps}} for r in fixed],
              ["expiry"] + snaps)
    write_csv(OUT_DIR / "per_session.csv",
              [{"session": r["session"],
                **{s: (r[s]["vol"] if r[s] else None) for s in snaps}} for r in sessions],
              ["session"] + snaps)
    return snaps, fixed, constant, sessions, bands


def cmd_history(limit=None):
    snaps, fixed, constant, sessions, bands = analyse(int(limit) if limit else None)
    report(snaps, fixed, constant, sessions, bands)
    try:
        shown = OUT_DIR.relative_to(ROOT)
    except ValueError:
        shown = OUT_DIR
    print()
    print(f"  saved {shown}/")


if __name__ == "__main__":
    cmd_history(sys.argv[1] if len(sys.argv) > 1 else None)
