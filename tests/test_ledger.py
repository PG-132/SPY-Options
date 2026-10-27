"""
Tests for screener/ledger.py, offline.

The claim this file guards is that the record says what happened and not
what the arithmetic wishes had happened. Two things in here were wrong
before they were tested: pooling settled windows by averaging their
volatilities, which reports a premium that is not there, and matching
windows across snapshots by anything other than their endpoints.

  python -m unittest discover tests        (from the project folder)
"""

import contextlib
import csv
import datetime as dt
import io
import math
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from screener import ledger  # noqa: E402

YEAR = 252.0

WCOLS = ["from_expiry", "to_expiry", "session_priced", "sessions", "days",
         "source", "forward_vol", "forward_vol_error", "rest_vol", "vs_rest",
         "vs_rest_error", "rest_differs", "neighbour_vol", "vs_neighbours",
         "vs_neighbours_error", "neighbours_differ"]
CCOLS = ["snapshot", "date", "sessions", "days", "chain_vol",
         "chain_vol_calendar", "windows"]


def window(frm, to, vol, sessions=1, vs_rest=0.0, vs_neigh=""):
    return {"from_expiry": frm, "to_expiry": to, "sessions": sessions,
            "days": sessions, "forward_vol": vol, "forward_vol_error": 0.003,
            "vs_rest": vs_rest, "vs_rest_error": 0.002,
            "rest_differs": abs(vs_rest) > 0.002, "vs_neighbours": vs_neigh,
            "vs_neighbours_error": "", "neighbours_differ": False,
            "session_priced": to if sessions == 1 else "", "source": "vs",
            "rest_vol": "", "neighbour_vol": ""}


def closes(start, n, step=0.0, px=100.0):
    """n sessions of closes, each `step` in log terms above the last."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append((d, px))
            px *= math.exp(step)
        d += dt.timedelta(days=1)
    return out


class Base(unittest.TestCase):
    def build(self, snaps):
        """snaps: {name: (chain_vol, [window dicts])}"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        for name, (chain_vol, windows) in snaps.items():
            folder = root / "context" / name
            folder.mkdir(parents=True)
            with open(folder / "windows.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=WCOLS, extrasaction="ignore")
                w.writeheader()
                w.writerows(windows)
            with open(folder / "chain.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=CCOLS, extrasaction="ignore")
                w.writeheader()
                w.writerow({"snapshot": name, "date": name[:10],
                            "chain_vol": chain_vol})
        for attr, value in (("CONTEXT_DIR", root / "context"),
                            ("OUT_DIR", root / "ledger")):
            old = getattr(ledger, attr)
            setattr(ledger, attr, value)
            self.addCleanup(setattr, ledger, attr, old)
        return root

    def prices(self, rows):
        old = ledger.spy_closes
        ledger.spy_closes = lambda refresh=False: rows
        self.addCleanup(setattr, ledger, "spy_closes", old)


ONE = {"2026-10-20_1543": (0.168, [
    window(ledger.SPOT, "2026-10-21", 0.1225, vs_rest=-0.0475),
    window("2026-10-21", "2026-10-22", 0.1277, vs_rest=-0.0420),
    window("2026-10-22", "2026-10-27", 0.1936, sessions=3, vs_rest=0.0267),
])}


class TestBuilding(Base):
    def test_the_first_window_starts_at_the_snapshot_not_at_the_word_spot(self):
        """It runs from the moment of the snapshot, so its realized window
        has to begin on the snapshot's own date or it would be measured over
        the wrong sessions."""
        self.build(ONE)
        rows = ledger.build()
        self.assertEqual(rows[0]["from_expiry"], ledger.SPOT)
        self.assertEqual(rows[0]["start_date"], dt.date(2026, 10, 20))
        self.assertEqual(rows[0]["end_date"], dt.date(2026, 10, 21))

    def test_a_later_window_starts_at_its_near_expiry(self):
        self.build(ONE)
        r = ledger.build()[1]
        self.assertEqual(r["start_date"], dt.date(2026, 10, 21))
        self.assertEqual(r["end_date"], dt.date(2026, 10, 22))

    def test_every_window_is_kept_not_just_the_flagged_ones(self):
        """A record of only the interesting windows has no control group in
        it, so it can never show whether flagging them helped."""
        self.build(ONE)
        self.assertEqual(len(ledger.build()), 3)

    def test_rebuilding_does_not_duplicate(self):
        self.build(ONE)
        self.prices(closes(dt.date(2026, 10, 1), 20, 0.004))
        a, _ = ledger.analyse()
        b, _ = ledger.analyse()
        self.assertEqual(len(a), len(b))


class TestRealizedOverAWindow(unittest.TestCase):
    def test_open_on_the_left_and_closed_on_the_right(self):
        c = closes(dt.date(2026, 1, 5), 10, 0.01)
        rv, n = ledger.realized_over(c, c[2][0], c[6][0])
        self.assertEqual(n, 4, "sessions 3,4,5,6 - four returns, not five")
        self.assertAlmostEqual(rv, 0.01 * math.sqrt(YEAR), places=10)

    def test_a_single_session_is_allowed_here(self):
        """vrp.realized refuses one return, which is right for a monthly
        claim. Most windows here are one session and refusing them would
        throw away the front of every chain."""
        c = closes(dt.date(2026, 1, 5), 10, 0.01)
        rv, n = ledger.realized_over(c, c[0][0], c[1][0])
        self.assertEqual(n, 1)
        self.assertAlmostEqual(rv, 0.01 * math.sqrt(YEAR), places=10)

    def test_nothing_before_the_start_means_no_reading(self):
        c = closes(dt.date(2026, 1, 5), 10, 0.01)
        rv, _ = ledger.realized_over(c, dt.date(2020, 1, 1), c[-1][0])
        self.assertIsNone(rv)


class TestSettlingFromTheSnapshotsOwnSpot(unittest.TestCase):
    """The first window of a snapshot begins partway through a session, so
    it prices the rest of that afternoon. Settling it from the previous
    close drops exactly the part the snapshot could see - 0.46% of spot on
    2026-09-24. run.json records what the collector observed, so the base is
    available without any intraday price feed."""

    def setUp(self):
        self.c = closes(dt.date(2026, 1, 5), 6, 0.01)   # +1% a session

    def test_the_snapshots_own_session_close_is_measured_not_used_as_base(self):
        """Two returns, not one: spot to that evening's close, then on to the
        expiry. Without start_price the first of those is invisible."""
        start, end = self.c[0][0], self.c[1][0]
        base = self.c[0][1] * math.exp(-0.005)          # spot 0.5% under the close
        _, n_plain = ledger.realized_over(self.c, start, end)
        _, n_spot = ledger.realized_over(self.c, start, end, start_price=base)
        self.assertEqual(n_plain, 1)
        self.assertEqual(n_spot, 2)

    def test_the_span_divides_not_the_number_of_returns(self):
        """Two returns over 1.04 sessions. Dividing by two would understate
        it by a third - the afternoon is a fraction of a session, not one."""
        start, end = self.c[0][0], self.c[1][0]
        base = self.c[0][1] * math.exp(-0.005)
        rv, n = ledger.realized_over(self.c, start, end, start_price=base,
                                     span=1.04)
        want = math.sqrt((0.005 ** 2 + 0.01 ** 2) / 1.04) * math.sqrt(YEAR)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(rv, want, places=10)

    def test_without_a_spot_the_old_behaviour_is_unchanged(self):
        start, end = self.c[1][0], self.c[4][0]
        rv, n = ledger.realized_over(self.c, start, end)
        self.assertEqual(n, 3)
        self.assertAlmostEqual(rv, 0.01 * math.sqrt(YEAR), places=10)

    def test_a_missing_run_json_leaves_the_row_settling_as_before(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = ledger.CHAIN_DIR
        ledger.CHAIN_DIR = pathlib.Path(tmp.name)
        self.addCleanup(setattr, ledger, "CHAIN_DIR", old)
        self.assertIsNone(ledger.snapshot_spot("2026-10-20_1543"))


class TestSettling(Base):
    def test_a_window_past_the_data_stays_open_and_carries_no_verdict(self):
        self.build(ONE)
        rows = ledger.settle(ledger.build(),
                             closes(dt.date(2026, 10, 1), 15, 0.004))
        openrows = [r for r in rows if r["status"] == "open"]
        self.assertTrue(openrows)
        for r in openrows:
            self.assertIsNone(r["realized"], "an open window has no verdict")
            self.assertIsNone(r["realized_minus_priced"])

    def test_a_closed_window_gets_both_numbers(self):
        self.build(ONE)
        rows = ledger.settle(ledger.build(),
                             closes(dt.date(2026, 10, 1), 30, 0.004))
        done = [r for r in rows if r["status"] == "settled"]
        self.assertTrue(done)
        for r in done:
            self.assertIsNotNone(r["realized"])
            self.assertAlmostEqual(r["realized_minus_priced"],
                                   r["realized"] - r["forward_vol"])


class TestPooling(unittest.TestCase):
    """The bug this class exists for: averaging the volatility readings of
    one-session windows understates realized by sqrt(2/pi) = 0.798 even when
    the pricing is exactly right, because a single |return| is a biased
    estimate of sigma. Pooling squared returns has no such bias."""

    def rows(self, triples):
        return [{"forward_vol": p, "sessions": n, "realized": r,
                 "realized_sessions": n, "status": "settled", "vs_rest": 0.0}
                for p, r, n in triples]

    def test_pooling_is_in_variance_not_in_volatility(self):
        """Two sessions priced at 10%: one realizes 20%, one realizes
        nothing. The variance delivered is twice what was priced, so the
        ratio is sqrt(2). Averaging the two volatilities would say 1.0 and
        report a market that landed exactly on its price."""
        got = ledger.pooled(self.rows([(0.10, 0.20, 1), (0.10, 0.0, 1)]))
        self.assertAlmostEqual(got["ratio"], math.sqrt(2.0), places=10)
        self.assertNotAlmostEqual(got["ratio"], 1.0, places=2)

    def test_a_long_window_counts_for_more_than_a_short_one(self):
        """A five-session window carries five sessions of variance. Counting
        it once would let a single quiet day outvote a quiet week."""
        short = ledger.pooled(self.rows([(0.10, 0.20, 1), (0.10, 0.10, 5)]))
        long = ledger.pooled(self.rows([(0.10, 0.20, 5), (0.10, 0.10, 1)]))
        self.assertLess(short["ratio"], long["ratio"])

    def test_pricing_that_was_exactly_right_gives_one(self):
        got = ledger.pooled(self.rows([(0.12, 0.12, 1), (0.12, 0.12, 4)]))
        self.assertAlmostEqual(got["ratio"], 1.0, places=12)

    def test_nothing_settled_is_none_rather_than_zero(self):
        self.assertIsNone(ledger.pooled([]))


class TestMovers(Base):
    def snaps(self):
        return {
            "2026-10-13_1543": (0.150, [
                window("2026-11-13", "2026-11-20", 0.1700, sessions=5),
                window("2026-10-14", "2026-10-15", 0.1000)]),
            "2026-10-20_1543": (0.168, [
                window("2026-11-13", "2026-11-20", 0.1851, sessions=5),
                window("2026-10-21", "2026-10-22", 0.1277)]),
        }

    def test_a_window_is_matched_on_its_endpoints(self):
        """Its session count shrinks as the chain ages but its endpoints do
        not move, so they are what makes it the same window."""
        self.build(self.snaps())
        moved, newest, then = ledger.movers(ledger.build())
        self.assertEqual(newest, "2026-10-20_1543")
        self.assertEqual(then, "2026-10-13_1543")
        self.assertEqual(len(moved), 1, "only one window appears in both")
        self.assertEqual(moved[0]["to_expiry"], "2026-11-20")
        self.assertAlmostEqual(moved[0]["moved"], 0.1851 - 0.1700, places=10)

    def test_the_chains_own_move_is_reported_beside_it(self):
        """A window rising with the whole chain is a different event from
        one rising against it, and the raw move cannot tell them apart."""
        self.build(self.snaps())
        m = ledger.movers(ledger.build())[0][0]
        self.assertAlmostEqual(m["chain_moved"], 0.168 - 0.150, places=10)
        self.assertAlmostEqual(m["moved_vs_chain"],
                               (0.1851 - 0.1700) - (0.168 - 0.150), places=10)

    def test_one_snapshot_has_nothing_to_compare_with(self):
        self.build(ONE)
        moved, _, then = ledger.movers(ledger.build())
        self.assertEqual(moved, [])
        self.assertIsNone(then)


class TestThePivot(Base):
    def snaps(self):
        return {
            "2026-10-20_1100": (0.16, [
                window(ledger.SPOT, "2026-10-21", 0.12, vs_neigh=0.001),
                window("2026-10-21", "2026-10-23", 0.15, sessions=2, vs_neigh=0.002),
                window("2026-10-23", "2026-10-26", 0.19, vs_neigh=0.003)]),
            "2026-10-20_1543": (0.17, [
                window(ledger.SPOT, "2026-10-21", 0.13, vs_neigh=0.004),
                window("2026-10-21", "2026-10-23", 0.16, sessions=2, vs_neigh=0.005),
                window("2026-10-23", "2026-10-26", 0.20, vs_neigh=0.006)]),
        }

    def test_the_last_snapshot_of_a_day_is_the_anchor(self):
        """Three snapshots on a meeting day must not give that day three
        times the weight of every other in the series."""
        self.build(self.snaps())
        kinds = {r["snapshot"]: r["kind"] for r in ledger.build()}
        self.assertEqual(kinds["2026-10-20_1543"], "anchor")
        self.assertEqual(kinds["2026-10-20_1100"], "bracket")

    def test_brackets_are_left_out_of_the_grid(self):
        self.build(self.snaps())
        self.assertEqual(sorted(ledger.pivot(ledger.build())),
                         ["2026-10-20_1543"])

    def test_a_window_fills_every_date_it_spans(self):
        """A two-session block prices both its days at the same rate. That
        is what the market charged for a block containing either of them."""
        self.build(self.snaps())
        row = ledger.pivot(ledger.build(), value="forward_vol")["2026-10-20_1543"]
        self.assertAlmostEqual(row[dt.date(2026, 10, 22)], 0.16)
        self.assertAlmostEqual(row[dt.date(2026, 10, 23)], 0.16)
        self.assertAlmostEqual(row[dt.date(2026, 10, 21)], 0.13)

    def test_sessions_ahead_accumulates_across_the_chain(self):
        """The ageing axis. Without it there is no way to separate a window
        repricing from a window simply getting closer."""
        self.build(self.snaps())
        rows = [r for r in ledger.build() if r["snapshot"] == "2026-10-20_1543"]
        self.assertEqual([r["sessions_ahead"] for r in rows], [0.0, 1.0, 3.0])

    def test_a_holiday_is_not_a_date_the_grid_prices(self):
        self.assertNotIn(dt.date(2026, 11, 26),
                         ledger.trading_days(dt.date(2026, 11, 25),
                                             dt.date(2026, 11, 30)))


class TestMissingSessions(unittest.TestCase):
    """A gap is the one failure that stays quiet. The record cannot tell a
    day nobody looked at from a day nothing happened, and only one of those
    can be recovered."""

    def rows(self, dates):
        return [{"asof": d} for d in dates]

    def test_names_the_sessions_nobody_snapped(self):
        got, want = ledger.missing_sessions(
            self.rows([dt.date(2026, 10, 19), dt.date(2026, 10, 23)]),
            through=dt.date(2026, 10, 23))
        self.assertEqual(got, [dt.date(2026, 10, 20), dt.date(2026, 10, 21),
                               dt.date(2026, 10, 22)])
        self.assertEqual(want, 5)

    def test_a_closed_market_is_not_a_missed_session(self):
        """Thanksgiving 2026 is in the holiday table and must not be
        reported as something you failed to do."""
        got, _ = ledger.missing_sessions(
            self.rows([dt.date(2026, 11, 25), dt.date(2026, 11, 27)]),
            through=dt.date(2026, 11, 27))
        self.assertNotIn(dt.date(2026, 11, 26), got)
        self.assertEqual(got, [])

    def test_a_weekend_is_not_a_gap_either(self):
        got, _ = ledger.missing_sessions(
            self.rows([dt.date(2026, 10, 23), dt.date(2026, 10, 26)]),
            through=dt.date(2026, 10, 26))
        self.assertEqual(got, [])

    def test_an_unbroken_run_reports_nothing(self):
        days = [dt.date(2026, 10, 19) + dt.timedelta(days=i) for i in range(5)]
        got, want = ledger.missing_sessions(self.rows(days), through=days[-1])
        self.assertEqual(got, [])
        self.assertEqual(want, 5)

    def test_the_range_runs_to_today_so_todays_miss_is_reported(self):
        """The point is to notice a gap while it still means something,
        and the most useful one to hear about is the one just made."""
        old = dt.date.today() - dt.timedelta(days=30)
        while old.weekday() >= 5:
            old -= dt.timedelta(days=1)
        got, _ = ledger.missing_sessions(self.rows([old]))
        self.assertTrue(got, "a month of silence should be reported")
        self.assertGreater(max(got), old)


class TestEndToEnd(Base):
    def test_writes_the_file_and_reports(self):
        self.build(ONE)
        self.prices(closes(dt.date(2026, 10, 1), 30, 0.004))
        rows, names = ledger.analyse()
        path = ledger.OUT_DIR / "windows.csv"
        self.assertTrue(path.exists())
        with open(path, newline="", encoding="utf-8") as f:
            saved = list(csv.DictReader(f))
        self.assertEqual(len(saved), len(rows))
        self.assertIn("start_date", saved[0])
        self.assertIn("end_date", saved[0])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ledger.report(rows, names)
        self.assertIn("pooled in variance", out.getvalue())

    def test_no_context_output_is_an_error_not_an_empty_file(self):
        self.build({})
        with self.assertRaises(SystemExit):
            ledger.analyse()


if __name__ == "__main__":
    unittest.main()
