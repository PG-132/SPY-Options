"""
Tests for screener/pricing.py.

The first test is the one that matters: the forward-based math must reproduce
straddle_tool.py, the pricer that ran the Sep-25 straddle and was checked
against Hull and finite differences. Its outputs are frozen in
straddle_tool_reference.json so this repo does not depend on that folder.

  python -m unittest discover tests        (from the project folder)
"""

import json
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from screener import pricing  # noqa: E402

REFERENCE = json.loads(
    (pathlib.Path(__file__).with_name("straddle_tool_reference.json")).read_text(
        encoding="utf-8"))


class TestAgainstTheOldPricer(unittest.TestCase):
    def test_reproduces_straddle_tool_exactly(self):
        worst, cases = 0.0, REFERENCE["cases"]
        self.assertGreater(len(cases), 300)
        for c in cases:
            F, disc = pricing.from_spot(c["S"], c["T"], c["r"])
            got = pricing.bs(c["right"], F, c["K"], c["T"], c["sigma"], disc)
            for greek, want in c["expect"].items():
                worst = max(worst, abs(got[greek] - want))
                self.assertAlmostEqual(got[greek], want, places=9,
                                       msg=f"{greek} for {c}")
        self.assertLess(worst, 1e-9, "should agree to float noise, not approximately")


class TestTextbook(unittest.TestCase):
    """Hull's worked example: S=42, K=40, r=10%, sigma=20%, six months.
    Call 4.76, put 0.81.
    
    computes properly.
    """

    def setUp(self):
        self.F, self.disc = pricing.from_spot(42.0, 0.5, 0.10)

    def test_call_and_put(self):
        call = pricing.bs("C", self.F, 40.0, 0.5, 0.20, self.disc)["price"]
        put = pricing.bs("P", self.F, 40.0, 0.5, 0.20, self.disc)["price"]
        self.assertAlmostEqual(call, 4.76, places=2)
        self.assertAlmostEqual(put, 0.81, places=2)


class TestParity(unittest.TestCase):
    def test_call_minus_put_is_the_discounted_distance_to_the_forward(self):
        for T in (1 / 365, 30 / 365, 1.0):
            for K in (700.0, 763.0, 830.0):
                F, disc = pricing.from_spot(763.66, T, 0.04)
                c = pricing.bs("C", F, K, T, 0.13, disc)["price"]
                p = pricing.bs("P", F, K, T, 0.13, disc)["price"]
                self.assertAlmostEqual(c - p, disc * (F - K), places=10)

    def test_forward_recovered_from_a_call_and_a_put(self):
        F, disc = pricing.from_spot(763.66, 29 / 365, 0.04)
        for K in (700.0, 763.0, 830.0):
            c = pricing.bs("C", F, K, 29 / 365, 0.13, disc)["price"]
            p = pricing.bs("P", F, K, 29 / 365, 0.13, disc)["price"]
            self.assertAlmostEqual(pricing.forward_from_parity(c, p, K, disc), F,
                                   places=9)

    def test_one_forward_means_one_iv_per_strike(self):
        """The whole reason for pricing off the forward: a call and a put at
        the same strike, priced from the same forward, solve to the same IV."""
        F, disc = pricing.from_spot(763.66, 29 / 365, 0.04)
        for K in (700.0, 763.0, 830.0):
            c = pricing.bs("C", F, K, 29 / 365, 0.137, disc)["price"]
            p = pricing.bs("P", F, K, 29 / 365, 0.137, disc)["price"]
            civ = pricing.implied_vol("C", c, F, K, 29 / 365, disc)
            piv = pricing.implied_vol("P", p, F, K, 29 / 365, disc)
            self.assertAlmostEqual(civ, piv, places=8)
            self.assertAlmostEqual(civ, 0.137, places=8)


class TestSolver(unittest.TestCase):
    def test_round_trips_across_the_surface(self):
        F, disc = pricing.from_spot(763.66, 29 / 365, 0.04)
        worst, checked = 0.0, 0
        for right in ("C", "P"):
            for K in (600.0, 700.0, 764.0, 800.0, 845.0):
                for sigma in (0.05, 0.128, 0.40, 1.20):
                    T = 29 / 365
                    px = pricing.bs(right, F, K, T, sigma, disc)["price"]
                    if px - pricing.floor_price(right, F, K, T, disc) < 1e-6:
                        continue     # deep in the money: no time value left to read
                    worst = max(worst, abs(pricing.implied_vol(right, px, F, K, T, disc)
                                           - sigma))
                    checked += 1
        self.assertGreater(checked, 30)
        self.assertLess(worst, 1e-8)

    def test_refuses_a_price_at_the_no_arbitrage_floor(self):
        F, disc = pricing.from_spot(763.66, 1 / 365, 0.04)
        floor = pricing.floor_price("C", F, 700.0, 1 / 365, disc)
        with self.assertRaises(pricing.SolveError):
            pricing.implied_vol("C", floor, F, 700.0, 1 / 365, disc)
        with self.assertRaises(pricing.SolveError):     # an expiring worthless put
            pricing.implied_vol("P", 0.0, F, 700.0, 1 / 365, disc)

        # deep in the money at a low vol: the price IS intrinsic, so there is
        # nothing left for a vol to explain
        F, disc = pricing.from_spot(763.66, 29 / 365, 0.04)
        px = pricing.bs("C", F, 600.0, 29 / 365, 0.05, disc)["price"]
        with self.assertRaises(pricing.SolveError):
            pricing.implied_vol("C", px, F, 600.0, 29 / 365, disc)

    def test_refuses_a_price_no_volatility_can_reach(self):
        F, disc = pricing.from_spot(763.66, 29 / 365, 0.04)
        with self.assertRaises(pricing.SolveError):
            pricing.implied_vol("C", 900.0, F, 764.0, 29 / 365, disc)

    def test_iv_band_widens_as_vega_collapses(self):
        """The Sep-24 measurement: a penny of spread is a tenth of a point near
        the money and most of a point in the wings."""
        F, disc = pricing.from_spot(763.66, 29 / 365, 0.04)
        near = pricing.iv_band("P", 1.45, 1.47, F, 700.0, 29 / 365, disc)
        wing = pricing.iv_band("C", 0.01, 0.02, F, 870.0, 29 / 365, disc)
        self.assertLess(near[1] - near[0], 0.002)         # under 0.2 vol points
        self.assertGreater(wing[1] - wing[0], 0.005)      # over half a point
        self.assertLess(near[1] - near[0], wing[1] - wing[0])


class TestGreeks(unittest.TestCase):
    """Greeks against bumped prices. Loose tolerances on purpose: finite
    differences are the approximation here, not the formulas."""

    def setUp(self):
        self.T, self.K, self.sigma = 29 / 365, 764.0, 0.13
        self.spot, self.rate = 763.66, 0.04

    def priced(self, right, spot=None, T=None, sigma=None):
        F, disc = pricing.from_spot(spot or self.spot, T or self.T, self.rate)
        return pricing.bs(right, F, self.K, T or self.T, sigma or self.sigma, disc)

    def test_delta_and_gamma_match_a_spot_bump(self):
        h = 0.01
        for right in ("C", "P"):
            up = self.priced(right, spot=self.spot + h)["price"]
            dn = self.priced(right, spot=self.spot - h)["price"]
            mid = self.priced(right)
            self.assertAlmostEqual((up - dn) / (2 * h), mid["delta"], places=6)
            self.assertAlmostEqual((up - 2 * mid["price"] + dn) / (h * h),
                                   mid["gamma"], places=5)

    def test_vega_matches_a_vol_bump(self):
        h = 1e-4
        for right in ("C", "P"):
            up = self.priced(right, sigma=self.sigma + h)["price"]
            dn = self.priced(right, sigma=self.sigma - h)["price"]
            self.assertAlmostEqual((up - dn) / (2 * h) / 100, self.priced(right)["vega"],
                                   places=6)

    def test_theta_matches_a_day_passing(self):
        """Theta is the instantaneous rate, so a whole day of decay lands near
        it rather than on it: about a sixth of a cent apart here."""
        for right in ("C", "P"):
            today = self.priced(right)["price"]
            tomorrow = self.priced(right, T=self.T - 1 / 365)["price"]
            self.assertAlmostEqual(tomorrow - today, self.priced(right)["theta"],
                                   places=2)

    def test_at_expiry_only_intrinsic_is_left(self):
        F, disc = pricing.from_spot(771.35, 0.0, 0.04)
        call = pricing.bs("C", F, 764.0, 0.0, 0.13, disc)
        put = pricing.bs("P", F, 764.0, 0.0, 0.13, disc)
        self.assertAlmostEqual(call["price"], 7.35, places=10)   # the Sep-25 settlement
        self.assertEqual(put["price"], 0.0)
        self.assertEqual((call["gamma"], call["theta"], call["vega"]), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
