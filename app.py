#!/usr/bin/env python3
"""
app.py - the one entry point for the SPY screener.

  python app.py          same as `plan` (read-only, saves nothing)
  python app.py plan     which contracts a snapshot would pull
  python app.py daily    snap, then every step that reads it, in order
  python app.py snap     take one chain snapshot, saved under data/chains/
  python app.py iv       solve our own IVs from the newest snapshot
  python app.py surface  fit the smile per expiry and score every point
  python app.py term     strip variance between expiries: the time axis
  python app.py context  which windows are priced differently from the rest
  python app.py history  the same surface seen from every snapshot so far
  python app.py ledger   every window ever priced, and what became of it
  python app.py prices   daily closes for SPY and the CBOE series, cached
  python app.py vrp      implied against realized, one claim per month

More commands arrive as the modules land (surface, screen, etc). The files in
folder screener/ are imported from here, not run on their own.
"""

import argparse
import sys

from screener import collect, context, history, ledger, prices, surface, term, vol, vrp


def cmd_daily():
    """Snap, then every step that reads it, in order.

    Five commands at 15:45 is five chances to forget one, and a missing
    step is not loud - it just leaves the newest snapshot out of the
    record until someone notices. Each step defaults to the newest
    snapshot, so they chain with no arguments. A failure anywhere stops
    the run rather than letting later steps report on older data."""
    steps = (("snap", collect.cmd_snap), ("iv", vol.cmd_iv),
             ("surface", surface.cmd_surface), ("term", term.cmd_term),
             ("context", context.cmd_context), ("ledger", ledger.cmd_ledger))
    for i, (name, run) in enumerate(steps, 1):
        print()
        print(f"{'=' * 72}")
        print(f"[{i}/{len(steps)}] {name}")
        print(f"{'=' * 72}")
        run()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="which contracts a snapshot would pull; saves nothing")
    sub.add_parser("daily", help="snap and run the whole pipeline on it")
    sub.add_parser("snap", help="take one chain snapshot and save it")
    iv = sub.add_parser("iv", help="solve our own IVs from a snapshot")
    iv.add_argument("snapshot", nargs="?",
                    help="folder name under data/chains/; default the newest")
    sf = sub.add_parser("surface", help="fit the smile and score every point")
    sf.add_argument("snapshot", nargs="?",
                    help="folder name under data/iv/; default the newest")
    tm = sub.add_parser("term", help="forward variance between expiries")
    tm.add_argument("snapshot", nargs="?",
                    help="folder name under data/surface/; default the newest")
    cx = sub.add_parser("context", help="which windows are priced differently")
    cx.add_argument("snapshot", nargs="?",
                    help="folder name under data/surface/; default the newest")
    hi = sub.add_parser("history", help="compare every snapshot taken so far")
    hi.add_argument("limit", nargs="?",
                    help="only the most recent N snapshots; default all")
    lg = sub.add_parser("ledger", help="every window ever priced, and how it settled")
    lg.add_argument("limit", nargs="?", help="only the most recent N snapshots")
    pr = sub.add_parser("prices", help="daily closes for SPY and the CBOE series")
    pr.add_argument("refresh", nargs="?", help="pass `refresh` to re-download")
    vr = sub.add_parser("vrp", help="implied against realized, monthly")
    vr.add_argument("refresh", nargs="?", help="pass `refresh` to re-download")

    # VS Code's Run button starts the file with no arguments. Default to the
    # read-only command; anything that writes has to be asked for.
    argv = sys.argv[1:] or ["plan"]
    if not sys.argv[1:]:
        print("(no command given, running `plan`, which is read-only)\n")
    a = ap.parse_args(argv)

    if a.cmd == "daily":
        cmd_daily()
    elif a.cmd == "plan":
        collect.cmd_plan()
    elif a.cmd == "snap":
        collect.cmd_snap()
    elif a.cmd == "iv":
        vol.cmd_iv(a.snapshot)
    elif a.cmd == "surface":
        surface.cmd_surface(a.snapshot)
    elif a.cmd == "term":
        term.cmd_term(a.snapshot)
    elif a.cmd == "context":
        context.cmd_context(a.snapshot)
    elif a.cmd == "history":
        history.cmd_history(a.limit)
    elif a.cmd == "ledger":
        ledger.cmd_ledger(a.limit)
    elif a.cmd == "prices":
        prices.cmd_prices(a.refresh)
    elif a.cmd == "vrp":
        vrp.cmd_vrp(a.refresh)


if __name__ == "__main__":
    main()
