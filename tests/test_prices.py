"""
Tests for screener/prices.py, offline.

Nothing here touches the network: `download` is replaced throughout. What is
pinned is the freshness rule, which is the part that was subtly wrong in an
earlier version, and the refusal to lose a cache to a dead API.

  python -m unittest discover tests        (from the project folder)
"""

import csv
import datetime as dt
import io
import contextlib
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from screener import prices, vol  # noqa: E402


def bars(start, n, close=100.0):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append({"date": d, "open": close, "high": close,
                        "low": close, "close": close})
        d += dt.timedelta(days=1)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        old = prices.OUT_DIR
        prices.OUT_DIR = self.root
        self.addCleanup(setattr, prices, "OUT_DIR", old)

    def fake_download(self, rows, record=None):
        def dl(symbol):
            if record is not None:
                record.append(symbol)
            return rows
        old = prices.download
        prices.download = dl
        self.addCleanup(setattr, prices, "download", old)


class TestFreshness(unittest.TestCase):
    """The rule this replaced was 'four days is fresh', which broke on exactly
    the day it mattered: Friday to Tuesday over a holiday is four days, so the
    first session back was served last week's closes."""

    def at(self, y, m, d, hour_et, minute=0):
        """`hour_et` really is ET. The old version of this helper added four
        hours to build a UTC stamp, the same hardcoded offset as the code it
        was testing, so every case here was written in EDT and the suite could
        not see the winter bug."""
        return prices.last_expected_session(
            dt.datetime(y, m, d, hour_et, minute, tzinfo=prices.ET)
            .astimezone(dt.timezone.utc))

    def test_before_the_close_it_is_yesterday(self):
        # Tuesday 10:00 ET: today's close does not exist yet
        self.assertEqual(self.at(2026, 10, 13, 10), dt.date(2026, 10, 12))

    def test_after_the_close_it_is_today(self):
        self.assertEqual(self.at(2026, 10, 13, 17), dt.date(2026, 10, 13))

    def test_a_weekend_walks_back_to_friday(self):
        for day, hour in ((17, 12), (18, 12), (19, 10)):   # Sat, Sun, Mon pre-close
            self.assertEqual(self.at(2026, 10, day, hour), dt.date(2026, 10, 16),
                             f"2026-10-{day} {hour}:00 ET")

    def test_tuesday_after_a_long_weekend_still_wants_mondays_close(self):
        """The case the old rule got wrong. Monday 2026-10-12 was Columbus
        Day: equities traded, so Monday's close is expected on Tuesday."""
        self.assertEqual(self.at(2026, 10, 13, 10), dt.date(2026, 10, 12))
        friday = dt.date(2026, 10, 9)
        self.assertGreater(self.at(2026, 10, 13, 10), friday,
                           "a cache ending Friday must read as stale on Tuesday")

    def test_it_is_never_a_weekend(self):
        for day in range(12, 20):
            self.assertLess(self.at(2026, 10, day, 17).weekday(), 5)


class TestTheClockAndTheGuard(unittest.TestCase):
    """The clock decides which bars may be stored, so getting it wrong does
    not just serve stale data - it writes bad data that then hides."""

    def at(self, y, m, d, hour, minute=0):
        return prices.last_expected_session(
            dt.datetime(y, m, d, hour, minute, tzinfo=prices.ET)
            .astimezone(dt.timezone.utc))

    def test_an_est_afternoon_is_not_a_finished_session(self):
        """The regression. EST began 2026-11-01; with the offset hardcoded at
        -4, Monday 15:30 ET computed 16:30 and returned Monday itself."""
        self.assertEqual(self.at(2026, 11, 2, 15, 30), dt.date(2026, 10, 30))
        self.assertEqual(self.at(2026, 11, 2, 16, 30), dt.date(2026, 11, 2))

    def test_the_daily_routine_sits_inside_the_window_that_broke(self):
        """15:45 is when the pipeline runs, in both halves of the year."""
        self.assertEqual(self.at(2026, 10, 29, 15, 45), dt.date(2026, 10, 28))
        self.assertEqual(self.at(2026, 11, 2, 15, 45), dt.date(2026, 10, 30))

    def test_a_1pm_close_settles_at_1pm(self):
        """14:00 on the day after Thanksgiving is after the bell; 14:00 on any
        other day is not. Same table the variance clock reads."""
        self.assertEqual(prices.session_close(dt.date(2026, 11, 27)),
                         prices.HALF_DAY_CLOSE)
        self.assertEqual(self.at(2026, 11, 27, 14), dt.date(2026, 11, 27))
        self.assertEqual(self.at(2026, 11, 27, 12), dt.date(2026, 11, 25))

    def test_the_guard_and_the_variance_clock_read_one_table(self):
        self.assertTrue(all(prices.session_close(d) == prices.HALF_DAY_CLOSE
                            for d in vol.HALF_DAYS))

    def test_a_holiday_has_no_close_to_expect(self):
        self.assertFalse(prices.session_closed(dt.date(2026, 11, 26)))
        self.assertEqual(self.at(2026, 11, 26, 17), dt.date(2026, 11, 25))

    def test_settled_only_cuts_the_bar_that_is_still_trading(self):
        rows = bars(dt.date(2026, 10, 26), 5)          # Mon-Fri 10-26..10-30
        now = dt.datetime(2026, 10, 30, 10, 23, tzinfo=prices.ET)
        keep, cut = prices.settled_only(rows, now.astimezone(dt.timezone.utc))
        self.assertEqual(cut, [dt.date(2026, 10, 30)])
        self.assertEqual(keep[-1]["date"], dt.date(2026, 10, 29))

    def test_settled_only_keeps_everything_after_the_bell(self):
        rows = bars(dt.date(2026, 10, 26), 5)
        now = dt.datetime(2026, 10, 30, 16, 1, tzinfo=prices.ET)
        keep, cut = prices.settled_only(rows, now.astimezone(dt.timezone.utc))
        self.assertEqual(cut, [])
        self.assertEqual(len(keep), 5)


class TestPartialBars(Base):
    def test_a_partial_bar_is_never_written_to_the_cache(self):
        """The 2026-10-30 case: a 10:23 pull returned the live print as that
        day's close. What makes it dangerous is the next line of defence -
        once stored, the freshness check sees today's date and stops
        re-downloading, so the bad bar outlives the session that made it."""
        today = prices.last_expected_session() + dt.timedelta(days=1)
        rows = bars(dt.date(2026, 1, 5), 4)
        rows.append({"date": today, "open": 761.38, "high": 761.46,
                     "low": 757.32, "close": 757.56})
        self.fake_download(rows)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            got = prices.history("SPY")
        self.assertNotIn(today, [r["date"] for r in got])
        self.assertIn("has not closed", out.getvalue())
        back = prices.read_cache(self.root / prices.SERIES["SPY"])
        self.assertNotIn(today, [r["date"] for r in back],
                         "an unsettled bar must not reach disk")

    def test_dropping_every_row_falls_back_to_the_cache(self):
        prices.write_cache(self.root / prices.SERIES["SPY"],
                           bars(dt.date(2020, 1, 6), 5))
        ahead = prices.last_expected_session() + dt.timedelta(days=1)
        self.fake_download([{"date": ahead, "open": 1, "high": 1,
                             "low": 1, "close": 1}])
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()):
                got = prices.history("SPY")
        self.assertEqual(len(got), 5, "filtering must not empty the cache")


class TestCache(Base):
    def test_round_trips_through_the_cache(self):
        rows = bars(dt.date(2026, 1, 5), 10)
        path = self.root / "x.csv"
        prices.write_cache(path, rows)
        back = prices.read_cache(path)
        self.assertEqual(len(back), 10)
        self.assertEqual(back[0]["date"], rows[0]["date"])
        self.assertAlmostEqual(back[-1]["close"], rows[-1]["close"])

    def test_a_fresh_cache_is_not_re_downloaded(self):
        rows = bars(dt.date(2026, 1, 5), 5)
        rows[-1]["date"] = prices.last_expected_session()
        prices.write_cache(self.root / prices.SERIES["SPY"], rows)
        asked = []
        self.fake_download([], record=asked)
        got = prices.history("SPY")
        self.assertEqual(asked, [], "a current cache should not hit the network")
        self.assertEqual(len(got), 5)

    def test_a_stale_cache_is_replaced(self):
        old_rows = bars(dt.date(2020, 1, 6), 5)
        prices.write_cache(self.root / prices.SERIES["SPY"], old_rows)
        fresh = bars(dt.date(2026, 1, 5), 12, close=500.0)
        asked = []
        self.fake_download(fresh, record=asked)
        got = prices.history("SPY")
        self.assertEqual(asked, ["SPY"])
        self.assertEqual(len(got), 12)
        self.assertAlmostEqual(got[0]["close"], 500.0)

    def test_a_dead_api_falls_back_to_the_cache_rather_than_losing_a_run(self):
        old_rows = bars(dt.date(2020, 1, 6), 5)
        prices.write_cache(self.root / prices.SERIES["SPY"], old_rows)
        self.fake_download([])
        with contextlib.redirect_stderr(io.StringIO()):
            got = prices.history("SPY")
        self.assertEqual(len(got), 5, "the cache is better than nothing")

    def test_no_cache_and_no_download_is_an_error_not_an_empty_list(self):
        self.fake_download([])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                prices.history("SPY")

    def test_a_corrupt_row_is_skipped_rather_than_crashing(self):
        path = self.root / "x.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=prices.COLS)
            w.writeheader()
            w.writerow({"date": "2026-01-05", "open": 1, "high": 1, "low": 1, "close": 1})
            w.writerow({"date": "not a date", "open": "", "high": "",
                        "low": "", "close": ""})
        self.assertEqual(len(prices.read_cache(path)), 1)

    def test_closes_drops_rows_with_no_close(self):
        rows = bars(dt.date(2026, 1, 5), 4)
        rows[2]["close"] = None
        self.assertEqual(len(prices.closes(rows)), 3)


if __name__ == "__main__":
    unittest.main()
