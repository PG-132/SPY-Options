#!/usr/bin/env python3
"""
app.py - the one entry point for the SPY screener.

  python app.py          same as `plan` (read-only, saves nothing)
  python app.py plan     which contracts a snapshot would pull
  python app.py snap     take one chain snapshot, saved under data/chains/
  python app.py iv       solve our own IVs from the newest snapshot

More commands arrive as the modules land (surface, screen, etc). The files in
folder screener/ are imported from here, not run on their own.
"""

import argparse
import sys

from screener import collect, vol


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="which contracts a snapshot would pull; saves nothing")
    sub.add_parser("snap", help="take one chain snapshot and save it")
    iv = sub.add_parser("iv", help="solve our own IVs from a snapshot")
    iv.add_argument("snapshot", nargs="?",
                    help="folder name under data/chains/; default the newest")

    # VS Code's Run button starts the file with no arguments. Default to the
    # read-only command; anything that writes has to be asked for.
    argv = sys.argv[1:] or ["plan"]
    if not sys.argv[1:]:
        print("(no command given, running `plan`, which is read-only)\n")
    a = ap.parse_args(argv)

    if a.cmd == "plan":
        collect.cmd_plan()
    elif a.cmd == "snap":
        collect.cmd_snap()
    elif a.cmd == "iv":
        vol.cmd_iv(a.snapshot)


if __name__ == "__main__":
    main()
