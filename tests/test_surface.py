"""
Tests for screener/surface.py, offline.

The important one builds points from a known smile, fits them, and checks the
curve comes back. The rest pin the gates and the two edge readings, and the
diagnostic that caught the wrong curve shape in the first place.

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
from screener import surface  # noqa: E402

FORWARD = 766.34


def truth(k):
    """A smile with the shape real ones have: steep put wing, flat call side."""
    return 0.13 - 0.55 * k + 0.9 * math.sqrt(k * k + 0.02 ** 2) - 0.02


def point(strike, iv, band=0.0006, **kw):
    p = {"symbol": f"X{strike:g}", "expiry": "2026-10-23", "right": "P" if strike < FORWARD else "C",
         "dte": 29.0, "sessions": 21.0, "strike": float(strike), "delta": -0.3,
         "iv": iv, "iv_bid": iv - band / 2, "iv_ask": iv + band / 2, "iv_band": band,
         "vega": 0.5, "forward": FORWARD, "spread_pct": 0.02, "open_interest": 500.0,
         "volume": 50.0, "quote_age_min": 0.1,
         "forward_error": 0.0, "iv_fwd_hi": None, "iv_fwd_lo": None}
    p.update(kw)
    p["moneyness"] = math.log(p["strike"] / FORWARD)
    p["readable"], why = surface.readable(p)
    p["tradeable"], why_trade = (surface.tradeable(p) if p["readable"] else (False, why))
    p["why_not"] = why or why_trade
    return p


def smile_points(n=60, lo=620.0, hi=840.0):
    return [point(k, truth(math.log(k / FORWARD)))
            for k in (lo + (hi - lo) * i / (n - 1) for i in range(n))]


class TestGates(unittest.TestCase):
    def test_readable_needs_a_narrow_band_and_real_vega(self):
        self.assertTrue(surface.readable(point(700, 0.22))[0])
        wide = surface.readable(point(700, 0.22, band=0.02))
        self.assertFalse(wide[0])
        self.assertIn("band", wide[1])
        thin = surface.readable(point(700, 0.22, vega=0.01))
        self.assertFalse(thin[0])
        self.assertIn("vega", thin[1])

    def test_tradeable_checks_spread_interest_volume_and_age(self):
        self.assertTrue(surface.tradeable(point(700, 0.22))[0])
        for field, value, word in (("spread_pct", 0.40, "spread"),
                                   ("open_interest", 2.0, "open interest"),
                                   ("volume", 0.0, "no trades"),
                                   ("quote_age_min", 30.0, "min old")):
            ok, why = surface.tradeable(point(700, 0.22, **{field: value}))
            self.assertFalse(ok, field)
            self.assertIn(word, why)

    def test_missing_open_interest_is_unknown_not_zero(self):
        """Webull leaves it blank on newly listed expiries. Treating that as
        nobody-there would delete whole expiries that trade fine."""
        ok, _ = surface.tradeable(point(700, 0.22, open_interest=None))
        self.assertTrue(ok)

    def test_missing_volume_is_zero_not_unknown(self):
        """The opposite reading to open interest, and measured: Webull never
        sends volume 0, it sends blank, and deal_amount is empty on every one
        of those. Reading it as unknown made the gate unable to reject
        anything."""
        ok, why = surface.tradeable(point(700, 0.22, volume=None))
        self.assertFalse(ok)
        self.assertIn("no trades", why)


class TestFit(unittest.TestCase):
    def test_recovers_a_known_smile(self):
        pts = smile_points()
        curve, used, dropped = surface.fit_expiry(pts)
        self.assertEqual((len(used), dropped), (len(pts), 0))
        worst = max(abs(curve(p["moneyness"]) - truth(p["moneyness"])) for p in pts)
        self.assertLess(worst, 2e-4, "should land inside a fiftieth of a vol point")

    def test_a_wide_quote_cannot_drag_the_curve(self):
        """Weighting is 1/band^2: a penny-wide wing gets a vote proportional to
        how well it can be read."""
        clean = smile_points()
        curve_before, _, _ = surface.fit_expiry(clean)
        liar = point(700.0, truth(math.log(700 / FORWARD)) + 0.05, band=0.004)
        curve_after, _, _ = surface.fit_expiry(clean + [liar])
        moved = max(abs(curve_after(p["moneyness"]) - curve_before(p["moneyness"]))
                    for p in clean)
        self.assertLess(moved, 0.002)

    def test_refuses_to_fit_too_few_points(self):
        curve, used, _ = surface.fit_expiry(smile_points(n=4))
        self.assertIsNone(curve)

    def test_skips_unreadable_points_but_still_scores_them(self):
        pts = smile_points() + [point(650.0, 0.40, band=0.02)]   # unreadable
        curve, used, dropped = surface.fit_expiry(pts)
        self.assertEqual(dropped, 1)
        surface.score(pts, curve)
        self.assertTrue(all("fitted_iv" in p for p in pts))


class TestReadings(unittest.TestCase):
    def setUp(self):
        self.pts = smile_points()
        self.curve, _, _ = surface.fit_expiry(self.pts)

    def test_edges_are_measured_at_the_prices_you_would_trade(self):
        rich = point(720.0, truth(math.log(720 / FORWARD)) + 0.01, band=0.001)
        surface.score([rich], self.curve)
        self.assertGreater(rich["edge_at_bid"], 0)      # sellable above the curve
        self.assertLess(rich["edge_at_ask"], 0)
        cheap = point(720.0, truth(math.log(720 / FORWARD)) - 0.01, band=0.001)
        surface.score([cheap], self.curve)
        self.assertGreater(cheap["edge_at_ask"], 0)     # buyable below it
        self.assertLess(cheap["edge_at_bid"], 0)

    def test_a_deviation_inside_the_spread_is_not_an_edge(self):
        """Half a band off the curve, with a band wide enough to swallow it."""
        p = point(720.0, truth(math.log(720 / FORWARD)) + 0.0003, band=0.002)
        surface.score([p], self.curve)
        self.assertGreater(p["residual"], 0)
        self.assertLess(p["edge_at_bid"], 0)

    def test_sign_changes_counts_flips_along_the_smile(self):
        made_up = [{"residual": r} for r in (1, 1, 1, -1, -1, 1, -1)]
        self.assertEqual(surface.sign_changes(made_up), 3)


class TestEndToEnd(unittest.TestCase):
    def test_writes_points_and_fits(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = pathlib.Path(tmp.name) / "2026-09-24_1142"
        folder.mkdir(parents=True)
        rows = []
        for p in smile_points():
            rows.append({k: p[k] for k in ("symbol", "expiry", "dte", "sessions", "strike",
                                           "right", "delta", "iv", "iv_bid", "iv_ask",
                                           "iv_band", "vega", "forward", "spread_pct",
                                           "open_interest", "volume", "quote_age_min")})
        with open(folder / "contracts.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        surface.OUT_DIR = pathlib.Path(tmp.name) / "out"
        self.addCleanup(setattr, surface, "OUT_DIR", surface.ROOT / "data" / "surface")

        with contextlib.redirect_stdout(io.StringIO()):
            fits, points, dest = surface.analyse(folder)
        self.assertEqual(len(fits), 1)
        self.assertEqual(len(points), len(rows))
        self.assertLess(fits[0]["rms_vol_pts"], 0.02)
        with open(dest / "points.csv", newline="", encoding="utf-8") as f:
            saved = list(csv.DictReader(f))
        self.assertEqual(list(saved[0]), surface.POINT_COLS)
        with open(dest / "fits.csv", newline="", encoding="utf-8") as f:
            self.assertEqual(list(csv.DictReader(f))[0].keys(),
                             dict.fromkeys(surface.FIT_COLS).keys())


if __name__ == "__main__":
    unittest.main()


FORWARD_HI = FORWARD + 0.12          # a 12-cent error bar, the Sep-24 29-day figure


class TestForwardCost(unittest.TestCase):
    """What a wrong forward is worth in a residual. See docs/integrity.md.

    A forward error moves every IV in the expiry together and drags the
    log-moneyness axis with it, so the fitted curve follows and most of it
    cancels. That is why it is measured against a refit rather than taken as
    each point's raw IV sensitivity, which overstates it about threefold.
    """

    def shifted_points(self, odd_one=None, by=0.0):
        """The same strikes read at FORWARD_HI. Unless perturbed, each one
        lands exactly on the smile in the shifted coordinates, which is what
        a pure common-mode shift looks like."""
        pts = []
        for i, p in enumerate(smile_points()):
            iv_hi = truth(math.log(p["strike"] / FORWARD_HI))
            if odd_one is not None and i == odd_one:
                iv_hi += by
            p["iv_fwd_hi"] = iv_hi
            p["forward_error"] = 0.12
            pts.append(p)
        return pts

    def fit_shifted(self, pts):
        alt = [dict(q, moneyness=math.log(q["strike"] / FORWARD_HI), iv=q["iv_fwd_hi"])
               for q in pts]
        curve, _, _ = surface.fit_expiry(alt)
        return [(curve, "iv_fwd_hi", FORWARD_HI)]

    def test_a_pure_common_mode_shift_costs_almost_nothing(self):
        """The whole point: if the forward moves and the curve moves with it,
        no point's deviation from the curve changes."""
        pts = self.shifted_points()
        curve, _, _ = surface.fit_expiry(pts)
        surface.score(pts, curve)
        surface.forward_cost(pts, curve, self.fit_shifted(pts))
        self.assertLess(max(p["forward_cost"] for p in pts), 5e-4,
                        "a coherent shift should cancel out of the residual")

    def test_a_point_that_moves_against_the_curve_pays_for_it(self):
        """One strike reading differently at the shifted forward than its
        neighbours do: that part cannot cancel, so it shows up as cost."""
        pts = self.shifted_points(odd_one=20, by=0.01)
        curve, _, _ = surface.fit_expiry(pts)
        surface.score(pts, curve)
        surface.forward_cost(pts, curve, self.fit_shifted(pts))
        # a hair under the 0.01 injected: one outlier pulls the shifted curve
        # slightly toward itself, so part of its own move is absorbed
        self.assertGreater(pts[20]["forward_cost"], 0.008)
        self.assertLess(pts[20]["forward_cost"], 0.010)
        rest = [q["forward_cost"] for i, q in enumerate(pts) if i != 20]
        self.assertLess(max(rest), 0.002, "its neighbours should be untouched")

    def test_an_unsolvable_shifted_reading_is_skipped_not_counted_as_zero(self):
        pts = smile_points()
        curve, _, _ = surface.fit_expiry(pts)
        surface.score(pts, curve)
        surface.forward_cost(pts, curve, [(curve, "iv_fwd_hi", FORWARD_HI)])
        self.assertEqual(max(p["forward_cost"] for p in pts), 0.0)

    def test_no_forward_error_means_no_cost(self):
        pts = smile_points()
        curve, _, _ = surface.fit_expiry(pts)
        surface.score(pts, curve)
        surface.forward_cost(pts, curve, [])
        self.assertTrue(all(p["forward_cost"] == 0.0 for p in pts))


class TestSurvivesTheForward(unittest.TestCase):
    def test_an_edge_smaller_than_the_forward_cost_does_not_count(self):
        """54 of the Sep-24 chain's 88 spread-clearing edges died here."""
        p = {"edge_at_bid": 0.0003, "forward_cost": 0.0010}
        self.assertFalse(surface.survives_the_forward(p, "edge_at_bid"))
        p = {"edge_at_bid": 0.0030, "forward_cost": 0.0010}
        self.assertTrue(surface.survives_the_forward(p, "edge_at_bid"))

    def test_a_point_with_no_cost_recorded_is_judged_on_its_spread_alone(self):
        self.assertTrue(surface.survives_the_forward({"edge_at_ask": 0.0005}, "edge_at_ask"))
