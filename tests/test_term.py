"""
Tests for screener/term.py, offline.

The one that matters is that variance is what gets stripped, not volatility.
Averaging IVs across time is the mistake this file exists to prevent, and the
numbers differ enough that a test catches it.

  python -m unittest discover tests        (from the project folder)
"""

import contextlib
import csv
import io
import math
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from screener import term  # noqa: E402

YEAR = term.CONFIG["sessions_per_year"]


def expiry(sessions, atm, days=None, atm_error=0.0, calendar=None, half_days=0):
    """One fitted expiry, in the shape load() produces. Days default to the
    session count so the two clocks agree unless a test wants them apart, and
    so does the calendar count - pass `calendar` and `half_days` to put a 1pm
    close inside the range."""
    days = sessions if days is None else days
    T = days / 365.0
    return {"expiry": f"E{sessions:g}", "sessions": float(sessions), "days": float(days),
            "sessions_calendar": float(sessions if calendar is None else calendar),
            "half_days": float(half_days),
            "T": T, "atm": atm, "level": atm, "source": "atm", "atm_error": atm_error,
            "level_error": atm_error,
            "total_var": atm * atm * T, "total_var_error": 2.0 * atm * T * atm_error}


class TestForwardVariance(unittest.TestCase):
    def test_strips_variance_not_volatility(self):
        """Ten sessions at 10%, then twenty at 20% overall. The second ten
        sessions price at 26.46%, not the 30% you get by working in vol."""
        a = expiry(10, 0.10, days=10 / 252 * 365)
        b = expiry(20, 0.20, days=20 / 252 * 365)
        w = term.forward_windows([a, b])[0]
        self.assertEqual(w["sessions"], 10)
        self.assertAlmostEqual(w["forward_vol"], math.sqrt(0.07), places=9)
        self.assertAlmostEqual(w["forward_vol"], 0.26457513, places=6)
        naive = (0.20 * 20 - 0.10 * 10) / 10
        self.assertNotAlmostEqual(w["forward_vol"], naive, places=2)

    def test_a_flat_term_structure_prices_every_window_the_same(self):
        """If every session is worth the same variance, every window reads
        back at that vol however many sessions it spans."""
        v = 0.13
        rows = [expiry(s, v, days=s / 252 * 365) for s in (2, 3, 8, 13)]
        for w in term.forward_windows(rows):
            self.assertAlmostEqual(w["forward_vol"], v, places=9)

    def test_a_single_hot_session_shows_up_in_its_own_window(self):
        """Nine quiet sessions at 10% and one at 30% in the middle. The hot
        session's window reads 30%; its neighbours stay at 10%."""
        per = [0.10] * 10
        per[4] = 0.30
        rows, w = [], 0.0
        for i, v in enumerate(per, start=1):
            w += v * v / YEAR
            T = i / 252 * 365
            lv = math.sqrt(w / T)
            rows.append({"expiry": f"E{i}", "sessions": float(i), "days": i / 252 * 365,
                         "T": T, "atm": lv, "level": lv, "source": "atm",
                         "atm_error": 0.0, "level_error": 0.0,
                         "total_var": w, "total_var_error": 0.0})
        got = [x["forward_vol"] for x in term.forward_windows(rows)]
        self.assertAlmostEqual(got[3], 0.30, places=9)      # window into session 5
        for i, g in enumerate(got):
            if i != 3:
                self.assertAlmostEqual(g, 0.10, places=9)

    def test_expiries_with_the_same_session_count_make_no_window(self):
        """Two expiries a weekend apart share a session count: nothing trades
        between them, so there is no window to price."""
        a, b = expiry(5, 0.12), expiry(5, 0.12, days=7)
        self.assertEqual(term.forward_windows([a, b]), [])


class TestEarlyCloses(unittest.TestCase):
    def test_a_window_divides_by_the_clock_not_by_the_date_count(self):
        """The 2026-11-20 to 11-27 shape: four dates, one of them a 1pm close,
        so 3.5 sessions of variance. Dividing by four reads the window
        cheap, and the difference is more than a vol point."""
        a = expiry(10, 0.15, days=14)
        b = expiry(13.5, 0.16, days=20, calendar=14, half_days=1)
        w = term.forward_windows([a, b])[0]
        self.assertAlmostEqual(w["sessions"], 3.5, places=12)
        self.assertEqual(w["sessions_calendar"], 4)
        self.assertEqual(w["half_days"], 1)

        dw = b["total_var"] - a["total_var"]
        honest = math.sqrt(dw / (3.5 / 252))
        naive = math.sqrt(dw / (4.0 / 252))
        self.assertAlmostEqual(w["forward_vol"], honest, places=12)
        self.assertGreater((honest - naive) * 100, 1.0,
                           "counting the 1pm close whole understates it by "
                           "over a point, which is what made 11-20 to 11-27 "
                           "look like a -3.26 anomaly")

    def test_one_date_is_still_one_date_when_it_closes_early(self):
        """session_priced used to key off the clock reading exactly 1. A
        window over a single 1pm close reads 0.5 and would have lost its
        date, taking it out of the pivot."""
        a = expiry(0, 0.15, days=1)
        b = expiry(0.5, 0.16, days=2, calendar=1, half_days=1)
        w = term.forward_windows([a, b])[0]
        self.assertEqual(w["session_priced"], b["expiry"])

    def test_a_chain_with_no_early_close_is_untouched(self):
        a, b = expiry(10, 0.15, days=14), expiry(14, 0.16, days=20)
        w = term.forward_windows([a, b])[0]
        self.assertEqual(w["half_days"], 0)
        self.assertEqual(w["sessions"], w["sessions_calendar"])
        self.assertEqual(w["session_priced"], "")


class TestNoArbitrage(unittest.TestCase):
    def test_falling_total_variance_is_reported_not_repaired(self):
        a = expiry(5, 0.20, days=5 / 252 * 365)
        b = expiry(10, 0.10, days=10 / 252 * 365)      # less total variance, further out
        w = term.forward_windows([a, b])[0]
        self.assertLess(w["forward_var"], 0)
        self.assertIsNone(w["forward_vol"], "no real vol exists for negative variance")
        self.assertTrue(w["negative"])

    def test_a_negative_inside_its_error_bar_is_not_called_arbitrage(self):
        """Barely negative, with error bars wide enough to swallow it. Worth
        recording, not worth claiming."""
        # total variance goes flat at atm = 0.13 * sqrt(5/6) = 0.11867, so
        # a hair under that tips it just negative
        a = expiry(5, 0.1300, days=5 / 252 * 365, atm_error=0.01)
        b = expiry(6, 0.1186, days=6 / 252 * 365, atm_error=0.01)
        w = term.forward_windows([a, b])[0]
        self.assertTrue(w["negative"])
        self.assertFalse(w["arbitrage"])

    def test_a_negative_beyond_the_error_bar_is(self):
        a = expiry(5, 0.30, days=5 / 252 * 365, atm_error=1e-6)
        b = expiry(6, 0.10, days=6 / 252 * 365, atm_error=1e-6)
        w = term.forward_windows([a, b])[0]
        self.assertTrue(w["arbitrage"])


class TestErrorBars(unittest.TestCase):
    def test_a_one_session_window_is_read_less_precisely_than_a_five(self):
        """The same error on each end, divided by a fifth of the time: a
        narrow window amplifies whatever its endpoints carry."""
        base = expiry(10, 0.13, days=10 / 252 * 365, atm_error=0.0005)
        near = expiry(11, 0.13, days=11 / 252 * 365, atm_error=0.0005)
        far = expiry(15, 0.13, days=15 / 252 * 365, atm_error=0.0005)
        one = term.forward_windows([base, near])[0]["forward_vol_error"]
        five = term.forward_windows([base, far])[0]["forward_vol_error"]
        self.assertGreater(one, five * 2)

    def test_no_error_on_the_inputs_means_no_error_on_the_answer(self):
        rows = [expiry(5, 0.13, days=5 / 252 * 365), expiry(10, 0.13, days=10 / 252 * 365)]
        self.assertAlmostEqual(term.forward_windows(rows)[0]["forward_vol_error"], 0.0)


class TestConstantMaturity(unittest.TestCase):
    def setUp(self):
        self.rows = [expiry(s, 0.13, days=s / 252 * 365) for s in (2, 7, 14, 21)]

    def test_lands_on_the_flat_level_at_every_horizon(self):
        for s in (3, 7, 10, 20):
            self.assertAlmostEqual(term.constant_maturity(self.rows, s)["vol"], 0.13, places=9)

    def test_interpolates_in_variance_not_in_volatility(self):
        """Halfway between a 10% expiry and a 20% one is not 15%."""
        lo = expiry(10, 0.10, days=10 / 252 * 365)
        hi = expiry(20, 0.20, days=20 / 252 * 365)
        mid = term.constant_maturity([lo, hi], 15)["vol"]
        w = (lo["total_var"] + hi["total_var"]) / 2
        self.assertAlmostEqual(mid, math.sqrt(w / (15 / YEAR)), places=9)
        self.assertNotAlmostEqual(mid, 0.15, places=3)

    def test_refuses_to_extrapolate_past_the_chain(self):
        self.assertIsNone(term.constant_maturity(self.rows, 30))
        self.assertIsNone(term.constant_maturity(self.rows, 1))
        self.assertIsNone(term.constant_maturity([], 10))

    def test_an_exact_hit_uses_that_expiry_rather_than_interpolating(self):
        got = term.constant_maturity(self.rows, 14)
        self.assertEqual(got["interpolated_between"], "E14")


class TestEndToEnd(unittest.TestCase):
    def test_reads_both_files_and_writes_both_outputs(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        snap = "2026-10-13_1319"
        (root / "iv" / snap).mkdir(parents=True)
        (root / "surface" / snap).mkdir(parents=True)
        exp, fit = [], []
        for s, v in ((5, 0.10), (10, 0.12), (15, 0.14)):
            days = s / 252 * 365
            exp.append({"expiry": f"E{s}", "days_to_expiry": days, "forward_iv_cost": 0.0003})
            fit.append({"expiry": f"E{s}", "sessions": s, "atm_fitted": v,
                        "rms_vol_pts": 0.02, "points_fitted": 100})
        for path, rows in (((root / "iv" / snap / "expiries.csv"), exp),
                           ((root / "surface" / snap / "fits.csv"), fit)):
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)

        for name, value in (("IV_DIR", root / "iv"), ("SURFACE_DIR", root / "surface"),
                            ("OUT_DIR", root / "term")):
            old = getattr(term, name)
            setattr(term, name, value)
            self.addCleanup(setattr, term, name, old)

        rows, windows, curve, dest, dropped = term.analyse(snap)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(windows), 2)
        self.assertTrue(all(w["forward_vol"] > 0 for w in windows))
        self.assertTrue(all(w["forward_vol_error"] > 0 for w in windows),
                        "a real snapshot always carries some error")
        with open(dest / "forward.csv", newline="", encoding="utf-8") as f:
            self.assertEqual(list(csv.DictReader(f))[0].keys(),
                             dict.fromkeys(term.FORWARD_COLS).keys())
        with open(dest / "constant.csv", newline="", encoding="utf-8") as f:
            saved = list(csv.DictReader(f))
        self.assertEqual(len(saved), len(term.CONFIG["horizons"]))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            term.report(snap, rows, windows, curve, dest, dropped)
        self.assertIn("arbitrage-free", out.getvalue())

    def test_refuses_a_snapshot_with_one_expiry(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        snap = "x"
        (root / "iv" / snap).mkdir(parents=True)
        (root / "surface" / snap).mkdir(parents=True)
        with open(root / "iv" / snap / "expiries.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["expiry", "days_to_expiry", "forward_iv_cost"])
            w.writeheader()
            w.writerow({"expiry": "E5", "days_to_expiry": 7.2, "forward_iv_cost": 0.0003})
        with open(root / "surface" / snap / "fits.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["expiry", "sessions", "atm_fitted",
                                              "rms_vol_pts", "points_fitted"])
            w.writeheader()
            w.writerow({"expiry": "E5", "sessions": 5, "atm_fitted": 0.12,
                        "rms_vol_pts": 0.02, "points_fitted": 100})
        for name, value in (("IV_DIR", root / "iv"), ("SURFACE_DIR", root / "surface"),
                            ("OUT_DIR", root / "term")):
            old = getattr(term, name)
            setattr(term, name, value)
            self.addCleanup(setattr, term, name, old)
        with self.assertRaises(SystemExit):
            term.analyse(snap)


if __name__ == "__main__":
    unittest.main()


class TestWhichLevelIsStripped(unittest.TestCase):
    """The variance swap rate is additive across time where the at-the-money
    level only approximately is, so it is preferred. But the two cannot be
    mixed inside one snapshot: a window differencing a variance swap total
    against an ATM total measures nothing."""

    def build(self, rows):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        snap = "s"
        (root / "iv" / snap).mkdir(parents=True)
        (root / "surface" / snap).mkdir(parents=True)
        exp, fit = [], []
        for name, sessions, atm, vs, edge in rows:
            exp.append({"expiry": name, "days_to_expiry": sessions / 252 * 365,
                        "forward_iv_cost": 0.0003, "vs_rate": vs, "vs_error": 0.0005,
                        "vs_strikes": 120, "vs_edge_cost": edge})
            fit.append({"expiry": name, "sessions": sessions, "atm_fitted": atm,
                        "rms_vol_pts": 0.02, "points_fitted": 100})
        for path, data in (((root / "iv" / snap / "expiries.csv"), exp),
                           ((root / "surface" / snap / "fits.csv"), fit)):
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
        for attr, value in (("IV_DIR", root / "iv"), ("SURFACE_DIR", root / "surface"),
                            ("OUT_DIR", root / "term")):
            old = getattr(term, attr)
            setattr(term, attr, value)
            self.addCleanup(setattr, term, attr, old)
        return snap

    def test_prefers_the_variance_swap_rate_when_the_chain_carries_one(self):
        snap = self.build([("A", 5, 0.10, 0.12, 0.0001),
                           ("B", 10, 0.11, 0.13, 0.0001)])
        rows, dropped = term.load(snap)
        self.assertEqual([r["source"] for r in rows], ["vs", "vs"])
        self.assertAlmostEqual(rows[0]["level"], 0.12)
        self.assertEqual(dropped, [])

    def test_an_under_sampled_expiry_leaves_the_term_structure(self):
        """2026-10-29 carried 30 strikes, read below its neighbour, and
        produced a negative window then a 26% one. Dropping it bridges the
        gap instead."""
        snap = self.build([("A", 5, 0.10, 0.12, 0.0001),
                           ("B", 6, 0.11, 0.115, 0.0040),   # under-sampled
                           ("C", 8, 0.12, 0.14, 0.0001)])
        rows, dropped = term.load(snap)
        self.assertEqual([r["expiry"] for r in rows], ["A", "C"])
        self.assertEqual([d[0] for d in dropped], ["B"])
        windows = term.forward_windows(rows)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["sessions"], 3, "the window should bridge B")
        self.assertIsNotNone(windows[0]["forward_vol"])

    def test_falls_back_to_the_at_the_money_level_for_the_whole_snapshot(self):
        """One source per snapshot. With too few usable integrals nothing is
        stripped from a variance swap rate at all, not even where one exists."""
        snap = self.build([("A", 5, 0.10, 0.12, 0.0001),
                           ("B", 10, 0.11, None, None),
                           ("C", 15, 0.12, None, None)])
        rows, dropped = term.load(snap)
        self.assertEqual([r["source"] for r in rows], ["atm", "atm", "atm"])
        self.assertAlmostEqual(rows[0]["level"], 0.10)
        self.assertEqual(dropped, [], "nothing is dropped when ATM is the source")

    def test_a_window_never_mixes_the_two(self):
        snap = self.build([("A", 5, 0.10, 0.12, 0.0001),
                           ("B", 10, 0.11, 0.13, 0.0001)])
        rows, _ = term.load(snap)
        self.assertEqual(term.forward_windows(rows)[0]["source"], "vs")
