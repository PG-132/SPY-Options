"""
Tests for screener/vol.py, offline.

The main test builds a synthetic chain from a known smile, writes it out in
the shape `snap` writes, and checks that vol.py reads back what went in: the
forward, every strike's IV, and the reference points. If the pipeline ever
loses a convention along the way, the recovered numbers stop matching.

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
from screener import pricing, vol  # noqa: E402

SNAP_AT = "2026-09-24T11:42:00.000-04:00"
FORWARD = 766.34
RATE = 0.04


def smile(K, F):
    """A plain downward-sloping smile: 13% at the money, puts richer."""
    return 0.13 - 0.5 * math.log(K / F)


def write_snapshot(folder, expiries, strikes, forward=FORWARD, quote_at=SNAP_AT):
    """A chain priced from `smile`, in the shape collect.py saves."""
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for expiry in expiries:
        exp = dt.date.fromisoformat(expiry)
        close = dt.datetime.combine(exp, dt.time(16, 0), tzinfo=vol.ET)
        T = (close - dt.datetime.fromisoformat(quote_at)).total_seconds() / (365 * 86400)
        disc = math.exp(-RATE * T)
        for K in strikes:
            iv = smile(K, forward)
            for right in ("C", "P"):
                px = pricing.bs(right, forward, K, T, iv, disc)["price"]
                rows.append({
                    "symbol": f"SPY{exp:%y%m%d}{right}{int(K * 1000):08d}",
                    "expiry": expiry, "dte": (exp - dt.date(2026, 9, 24)).days,
                    "strike": K, "right": right,
                    "bid": round(px - 0.005, 6), "ask": round(px + 0.005, 6),
                    "vendor_iv": round(iv, 4),
                    "quote_time_et": quote_at, "fetched_at": quote_at,
                })
    with open(folder / "options.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(folder / "spot.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["after_batch", "price", "quote_time_et",
                                          "fetched_at"])
        w.writeheader()
        for i, px in enumerate((763.70, 763.75, 763.90)):
            w.writerow({"after_batch": i * 5, "price": px,
                        "quote_time_et": quote_at, "fetched_at": quote_at})
    return folder


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        vol.IV_DIR = self.dir / "iv"

    def tearDown(self):
        vol.IV_DIR = vol.ROOT / "data" / "iv"

    def analyse(self, expiries=("2026-10-23",), strikes=None):
        strikes = strikes or [float(k) for k in range(660, 871, 5)]
        folder = write_snapshot(self.dir / "chains" / "2026-09-24_1142", expiries, strikes)
        with contextlib.redirect_stdout(io.StringIO()):
            return vol.analyse(folder)


class TestClocks(Base):
    def test_sessions_skip_weekends_and_holidays(self):
        # Sep 24 to Oct 23, 2026: 21 trading days, no holidays in between
        self.assertEqual(vol.sessions_between(dt.date(2026, 9, 24), dt.date(2026, 10, 23)), 21)
        # Thursday to the following Monday is one session, not four days
        self.assertEqual(vol.sessions_between(dt.date(2026, 9, 24), dt.date(2026, 9, 28)), 2)
        # Labor Day 2026 falls on Sep 7 and does not count
        self.assertEqual(vol.sessions_between(dt.date(2026, 9, 3), dt.date(2026, 9, 10)), 4)

    def test_time_to_expiry_counts_hours_not_whole_days(self):
        """An 11:42 snapshot is 1.18 days from tomorrow's 16:00 expiry. Calling
        it 1.0 put the Sep-25 IV 1.3 points high against Webull's."""
        expiries, _, _, _ = self.analyse(expiries=("2026-09-25",))
        self.assertAlmostEqual(expiries[0]["days_to_expiry"], 1.179, places=2)
        self.assertEqual(expiries[0]["dte"], 1)

    def test_per_session_iv_lifts_an_expiry_that_spans_a_weekend(self):
        """Monday expiries look cheap in calendar time: four days of decay for
        two sessions of movement."""
        expiries, _, _, _ = self.analyse(expiries=("2026-09-28",))
        e = expiries[0]
        self.assertEqual((e["dte"], e["sessions"]), (4, 2))
        self.assertGreater(e["atm_iv_per_session"], e["atm_iv"])


class TestReadsBackWhatWentIn(Base):
    def test_recovers_the_forward(self):
        expiries, _, _, _ = self.analyse()
        self.assertAlmostEqual(expiries[0]["forward"], FORWARD, places=2)

    def test_recovers_every_strike_iv(self):
        _, contracts, _, _ = self.analyse()
        self.assertGreater(len(contracts), 30)
        worst = max(abs(c["iv"] - smile(c["strike"], FORWARD)) for c in contracts)
        self.assertLess(worst, 5e-4)

    def test_reads_the_out_of_the_money_side_only(self):
        _, contracts, _, _ = self.analyse()
        for c in contracts:
            self.assertEqual(c["right"], "P" if c["strike"] < FORWARD else "C")

    def test_at_the_money_and_delta_points_land_on_the_smile(self):
        expiries, contracts, _, _ = self.analyse()
        e = expiries[0]
        self.assertAlmostEqual(e["atm_iv"], smile(FORWARD, FORWARD), places=3)
        # a downward-sloping smile: puts above the money-money, calls below
        self.assertGreater(e["iv_25d_put"], e["atm_iv"])
        self.assertGreater(e["iv_10d_put"], e["iv_25d_put"])
        self.assertLess(e["iv_25d_call"], e["atm_iv"])
        self.assertGreater(e["put_skew_25d"], 0)
        self.assertLess(e["call_skew_25d"], 0)
        # and each delta point sits between the strikes that bracket it
        near = [c["iv"] for c in contracts
                if c["right"] == "P" and 0.20 <= abs(c["delta"]) <= 0.30]
        self.assertTrue(min(near) <= e["iv_25d_put"] <= max(near))

    def test_our_greeks_come_from_our_iv(self):
        _, contracts, _, _ = self.analyse()
        for c in contracts:
            F, T = c["forward"], c["dte"] / 365
            self.assertLess(abs(c["delta"]), 1.0)
            self.assertGreater(c["vega"], 0)
            self.assertLess(c["theta"], 0)

    def test_the_iv_band_brackets_the_mid(self):
        _, contracts, _, _ = self.analyse()
        for c in contracts:
            self.assertLess(c["iv_bid"], c["iv"])
            self.assertLess(c["iv"], c["iv_ask"])
            # each is rounded to 6 places on its own, so allow the last digit
            self.assertAlmostEqual(c["iv_band"], c["iv_ask"] - c["iv_bid"], places=5)

    def test_writes_both_files_with_their_columns(self):
        expiries, contracts, _, dest = self.analyse()
        with open(dest / "expiries.csv", newline="", encoding="utf-8") as f:
            saved = list(csv.DictReader(f))
        self.assertEqual(len(saved), len(expiries))
        self.assertEqual(list(saved[0]), vol.EXPIRY_COLS)
        with open(dest / "contracts.csv", newline="", encoding="utf-8") as f:
            self.assertEqual(list(csv.DictReader(f))[0].keys(), dict.fromkeys(
                vol.CONTRACT_COLS).keys())


class TestQuoteHandling(Base):
    def test_drops_quotes_with_no_market(self):
        rows = [{"strike": "700", "right": "P", "bid": "0", "ask": "0.01"},
                {"strike": "701", "right": "P", "bid": "0.40", "ask": "0.30"},
                {"strike": "702", "right": "P", "bid": "0.40", "ask": "0.42"}]
        kept = vol.quotes_by_strike(rows)
        self.assertEqual(list(kept), [702.0])      # no bid, and a crossed quote

    def test_skips_an_expiry_it_cannot_read(self):
        expiries, contracts, warnings, _ = self.analyse(strikes=[760.0, 770.0])
        self.assertEqual(expiries, [])
        self.assertTrue(any("skipped" in w for w in warnings))

    def test_matches_each_quote_to_the_nearest_spot(self):
        spots = [{"price": "763.70", "quote_time_et": "2026-09-24T11:42:00-04:00",
                  "fetched_at": "2026-09-24T11:42:00-04:00"},
                 {"price": "763.90", "quote_time_et": "2026-09-24T11:43:40-04:00",
                  "fetched_at": "2026-09-24T11:43:40-04:00"}]
        self.assertEqual(vol.spot_at("2026-09-24T11:43:35-04:00", spots), 763.90)
        self.assertEqual(vol.spot_at("2026-09-24T11:42:10-04:00", spots), 763.70)


if __name__ == "__main__":
    unittest.main()
