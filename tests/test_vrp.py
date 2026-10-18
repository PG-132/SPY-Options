"""
Tests for screener/vrp.py, offline.

The claim this file makes is that implied and realized are measured over the
SAME forward window. Most of these pin that: the window boundaries, the month
arithmetic, and what counts as a closed claim.

  python -m unittest discover tests        (from the project folder)
"""

import csv
import datetime as dt
import math
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from screener import vrp  # noqa: E402

ANN = math.sqrt(252)


def series(start, n, step=0.0):
    """n sessions of closes, each `step` in log terms above the last."""
    out, d, px = [], start, 100.0
    while len(out) < n:
        if d.weekday() < 5:
            out.append((d, px))
            px *= math.exp(step)
        d += dt.timedelta(days=1)
    return out


class TestRealized(unittest.TestCase):
    def test_a_constant_log_move_gives_back_its_own_volatility(self):
        """Every session moves by the same log return, so the zero-mean
        root-mean-square is that return, annualized."""
        step = 0.01
        closes = series(dt.date(2026, 1, 5), 30, step)
        rv, n = vrp.realized(closes, closes[0][0], closes[-1][0])
        self.assertEqual(n, 29)
        self.assertAlmostEqual(rv, step * ANN, places=10)

    def test_a_flat_market_realizes_nothing(self):
        closes = series(dt.date(2026, 1, 5), 20)
        rv, _ = vrp.realized(closes, closes[0][0], closes[-1][0])
        self.assertAlmostEqual(rv, 0.0, places=12)

    def test_the_window_is_open_on_the_left_and_closed_on_the_right(self):
        """The anchor's own session belongs to the previous claim. Its close
        is the base the first return is measured from, not a return itself."""
        closes = series(dt.date(2026, 1, 5), 10, 0.01)
        rv, n = vrp.realized(closes, closes[2][0], closes[6][0])
        self.assertEqual(n, 4, "sessions 3,4,5,6 - four returns, not five")
        self.assertAlmostEqual(rv, 0.01 * ANN, places=10)

    def test_nothing_before_the_anchor_means_no_reading(self):
        closes = series(dt.date(2026, 1, 5), 10, 0.01)
        rv, _ = vrp.realized(closes, dt.date(2025, 1, 1), closes[-1][0])
        self.assertIsNone(rv, "no prior close to measure the first return from")

    def test_one_session_is_not_enough(self):
        closes = series(dt.date(2026, 1, 5), 10, 0.01)
        rv, n = vrp.realized(closes, closes[0][0], closes[1][0])
        self.assertIsNone(rv)


class TestMonthArithmetic(unittest.TestCase):
    def test_adds_a_calendar_month(self):
        self.assertEqual(vrp.add_months(dt.date(2026, 1, 15), 1), dt.date(2026, 2, 15))
        self.assertEqual(vrp.add_months(dt.date(2026, 12, 3), 1), dt.date(2027, 1, 3))

    def test_clamps_a_day_the_next_month_does_not_have(self):
        self.assertEqual(vrp.add_months(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 28))
        self.assertEqual(vrp.add_months(dt.date(2024, 1, 31), 1), dt.date(2024, 2, 29))
        self.assertEqual(vrp.add_months(dt.date(2026, 3, 31), 1), dt.date(2026, 4, 30))

    def test_anchors_are_the_first_session_of_each_month(self):
        closes = series(dt.date(2026, 1, 1), 70)
        got = vrp.month_anchors(closes)
        self.assertEqual(got[0], dt.date(2026, 1, 1))
        self.assertTrue(all(a.day <= 3 for a in got), got)
        self.assertEqual(len({(a.year, a.month) for a in got}), len(got),
                         "one anchor per month, no repeats")


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.spy = series(dt.date(2026, 1, 1), 120, 0.005)
        self.vix = [(d, 20.0) for d, _ in self.spy]

    def test_a_window_past_the_data_is_open_not_closed(self):
        rows = vrp.build(self.spy, self.vix)
        self.assertTrue(any(r["status"] == "open" for r in rows))
        for r in rows:
            if r["status"] == "open":
                self.assertIsNone(r["realized"], "an open claim has no verdict")
                self.assertIsNotNone(r["rv_to_date"], "but it does have a reading")

    def test_a_closed_window_carries_both_numbers(self):
        closed = [r for r in vrp.build(self.spy, self.vix) if r["status"] == "closed"]
        self.assertTrue(closed)
        for r in closed:
            self.assertIsNotNone(r["realized"])
            self.assertAlmostEqual(r["iv"], 0.20)
            self.assertEqual(r["iv_source"], "^VIX")

    def test_a_month_with_no_implied_reading_is_skipped(self):
        thin = [(d, v) for d, v in self.vix if d.month != 2]
        rows = vrp.build(self.spy, thin)
        self.assertNotIn(2, [r["anchor"].month for r in rows])

    def test_the_expected_session_count_sits_beside_the_actual(self):
        """A short month is visible rather than silently misstated."""
        for r in vrp.build(self.spy, self.vix):
            self.assertGreater(r["sessions_expected"], 0)


class TestOurOwnRate(unittest.TestCase):
    def build(self, rows, band="12/6", snap="2026-10-15_1233"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        (root / snap).mkdir(parents=True)
        with open(root / snap / "expiries.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["expiry", "days_to_expiry", "vs_rate",
                                              "vs_edge_cost", "collected_band"])
            w.writeheader()
            for days, rate in rows:
                w.writerow({"expiry": f"E{days}", "days_to_expiry": days,
                            "vs_rate": rate, "vs_edge_cost": 0.0001,
                            "collected_band": band})
        old = vrp.IV_DIR
        vrp.IV_DIR = root
        self.addCleanup(setattr, vrp, "IV_DIR", old)
        return snap

    def test_interpolates_in_total_variance_not_in_volatility(self):
        snap = self.build([(20.0, 0.10), (40.0, 0.20)])
        got = vrp.our_rate(snap)
        w = 0.10 ** 2 * 20 + (0.20 ** 2 * 40 - 0.10 ** 2 * 20) * (30 - 20) / 20
        self.assertAlmostEqual(got["rate"], math.sqrt(w / 30), places=12)
        self.assertNotAlmostEqual(got["rate"], 0.15, places=3)

    def test_a_short_chain_may_be_extended_a_little(self):
        snap = self.build([(20.0, 0.13), (29.0, 0.13)])
        got = vrp.our_rate(snap)
        self.assertAlmostEqual(got["rate"], 0.13, places=10)
        self.assertAlmostEqual(got["extrapolated_days"], 1.0)

    def test_but_not_a_lot(self):
        snap = self.build([(10.0, 0.13), (20.0, 0.13)])
        self.assertIsNone(vrp.our_rate(snap), "10 days short is too far to reach")

    def test_a_narrow_band_is_refused_outright(self):
        """Its rate is understated by 0.5 to 1.1 vol points, which would read
        as a real move rather than a collection artifact."""
        snap = self.build([(20.0, 0.13), (40.0, 0.13)], band="6/3")
        self.assertIsNone(vrp.our_rate(snap))

    def test_an_unrecorded_band_is_refused_too(self):
        snap = self.build([(20.0, 0.13), (40.0, 0.13)], band="")
        self.assertIsNone(vrp.our_rate(snap))

    def test_the_series_puts_vix_beside_it_on_the_same_day(self):
        snap = self.build([(20.0, 0.10), (40.0, 0.20)])
        rows = vrp.our_series([(dt.date(2026, 10, 15), 16.0)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], dt.date(2026, 10, 15))
        self.assertAlmostEqual(rows[0]["vix"], 0.16)
        self.assertAlmostEqual(rows[0]["ours_minus_vix"],
                               rows[0]["spy_vs_30d"] - 0.16)

    def test_no_vix_that_day_leaves_the_gap_blank_rather_than_zero(self):
        snap = self.build([(20.0, 0.10), (40.0, 0.20)])
        rows = vrp.our_series([(dt.date(2020, 1, 2), 16.0)])
        self.assertIsNone(rows[0]["vix"])
        self.assertIsNone(rows[0]["ours_minus_vix"])


if __name__ == "__main__":
    unittest.main()


class TestDailyPath(unittest.TestCase):
    """The straddle workbook's vol block, generalised to the market: return,
    the implied one-day bar, whether the session cleared it, and realized
    expanding toward the figure the monthly row will report."""

    def setUp(self):
        self.spy = series(dt.date(2026, 1, 1), 120, 0.005)
        self.vix = [(d, 20.0) for d, _ in self.spy]
        self.log = vrp.build(self.spy, self.vix)
        self.daily = vrp.daily_path(self.spy, self.log)

    def test_the_bar_is_one_standard_deviation_held_fixed(self):
        """IV / sqrt(252), set at the anchor and not moved, exactly as the
        sheet holds entry IV fixed across a trade."""
        first = [r for r in self.daily if r["anchor"] == self.log[0]["anchor"]]
        self.assertTrue(first)
        want = self.log[0]["iv"] / ANN
        self.assertEqual(len({r["bar"] for r in first}), 1, "the bar must not drift")
        self.assertAlmostEqual(first[0]["bar"], want, places=6)

    def test_a_session_beats_when_the_move_exceeds_the_bar(self):
        for r in self.daily:
            self.assertEqual(r["beat"], r["abs_ret"] > r["bar"], r["date"])

    def test_a_quiet_market_never_beats_a_twenty_percent_bar(self):
        """0.5% a session against a 20% implied bar of 1.26%."""
        self.assertFalse(any(r["beat"] for r in self.daily))

    def test_realized_expands_and_lands_on_what_the_monthly_row_reports(self):
        """The daily path has to end where the monthly claim is settled, or
        the two views disagree about the same window."""
        closed = [r for r in self.log if r["status"] == "closed"]
        self.assertTrue(closed)
        for row in closed:
            path = [r for r in self.daily if r["anchor"] == row["anchor"]]
            self.assertAlmostEqual(path[-1]["rv_ann"], row["realized"], places=5,
                                   msg=str(row["anchor"]))
            self.assertEqual([r["session"] for r in path],
                             list(range(1, len(path) + 1)))

    def test_the_beat_rate_is_running_not_final(self):
        hot = [(d, c) for d, c in self.spy]
        vix = [(d, 1.0) for d, _ in hot]          # a 1% bar nothing can miss
        log = vrp.build(hot, vix)
        daily = vrp.daily_path(hot, log)
        path = [r for r in daily if r["anchor"] == log[0]["anchor"]]
        self.assertTrue(all(r["beat"] for r in path))
        for i, r in enumerate(path, start=1):
            self.assertAlmostEqual(r["beat_rate"], 1.0)
            self.assertEqual(r["session"], i)

    def test_a_partial_month_at_the_start_of_the_data_is_not_an_anchor(self):
        """SPY's history opens 1993-01-29, which would otherwise anchor a
        January window running to 28 February and sharing 18 of its 19
        sessions with February's."""
        late = series(dt.date(2026, 1, 28), 90, 0.005)
        vix = [(d, 20.0) for d, _ in late]
        anchors = [r["anchor"] for r in vrp.build(late, vix)]
        self.assertTrue(all(a.day <= vrp.CONFIG["max_anchor_day"] for a in anchors),
                        anchors)
        self.assertNotIn(dt.date(2026, 1, 28), anchors)
