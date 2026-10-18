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
from screener import prices  # noqa: E402


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

    def at(self, y, m, d, hour_et):
        return prices.last_expected_session(
            dt.datetime(y, m, d, hour_et + 4, tzinfo=dt.timezone.utc))

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
