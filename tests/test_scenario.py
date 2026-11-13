"""
Tests for screener/scenario.py, offline.

Every test builds a synthetic snapshot in a temporary folder - raw quotes,
vol.py's IVs, surface.py's fit and its range, and the term levels - with a
smile whose coefficients are known, so each rule can be checked against
arithmetic done here rather than against the engine itself. The real data/
folder is never read: every module the engine reads through points at the
temporary one for the length of a test.

The first claim is the one everything else stands on: at the snapshot's own
spot and time the engine gives back the chain it was built on. Then each
rule, then the plumbing. Acceptance criteria are the AC-n in
docs/changes/2026-11-06-scenario-engine.md.

  python -m unittest discover tests        (from the project folder)
"""

import contextlib
import csv
import datetime as dt
import io
import json
import math
import pathlib
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app  # noqa: E402
from screener import context, ledger, pricing, scenario, term, vol  # noqa: E402

RATE = vol.CONFIG["rate"]
SPOT = 600.0
STRIKES = [float(k) for k in range(540, 661, 5)]
BAND = 0.002                                  # half of each strike's IV band
HALF_SPREAD = 0.02                            # half of each quote's spread, $

FLAT = (0.0, 0.1, [0.12, 0.0, 0.0, 0.0, 0.0])            # 12% everywhere
SKEW = (0.0, 0.05, [0.13, -0.4, 0.3, 0.5, 0.0])          # puts richer, a real shape

EST = "2026-11-05T15:45:00-05:00"             # a Thursday after the clocks went back
EDT = "2026-10-29T15:45:00-04:00"             # the Thursday before
PRE_HALF = "2026-11-20T15:45:00-05:00"        # the Friday before Thanksgiving week

POS_COLS = ["kind", "expiry", "strike", "right", "qty", "price"]


def curve(fit, k):
    return scenario.curve(fit, k)


def expiry(name, fit=FLAT, level=0.12, edge=0.0, k_range=None, forward=None):
    return {"expiry": name, "fit": fit, "level": level, "edge": edge,
            "k_range": k_range, "forward": forward}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0]) if rows else ["expiry"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def make_snapshot(root, name, started, expiries, spot=SPOT, residuals=None,
                  missing=()):
    """A snapshot as the pipeline leaves it, for a smile we choose.

    Each expiry's strike IVs are its fitted curve plus any residual given
    for that strike; `missing` strikes get quotes but no IV, as when vol.py
    cannot read one. An expiry with fit None gets IVs (flat 12%) but no fit
    row, as when surface.py cannot fit it. Levels are the term structure's
    variance swap rates; `edge` over term.py's threshold drops an expiry
    from it."""
    residuals = residuals or {}
    when = dt.datetime.fromisoformat(started)
    asof = when.date()
    options, contracts, exps, fits, points = [], [], [], [], []
    for e in expiries:
        exp = dt.date.fromisoformat(e["expiry"])
        T = vol.years_to_expiry(exp, when)
        disc = math.exp(-RATE * T)
        F = e["forward"] or spot * math.exp(RATE * T)
        sessions = vol.sessions_between(asof, exp)
        fit = e["fit"]

        def iv_at(K):
            base = curve(fit, math.log(K / F)) if fit else 0.12
            return base + residuals.get((e["expiry"], K), 0.0)

        for K in STRIKES:
            iv = iv_at(K)
            for right in ("C", "P"):
                px = pricing.bs(right, F, K, T, iv, disc)["price"]
                options.append({
                    "symbol": f"SPY{exp:%y%m%d}{right}{int(K * 1000):08d}",
                    "expiry": e["expiry"], "strike": K, "right": right,
                    "bid": round(max(px - HALF_SPREAD, 0.0), 4),
                    "ask": round(px + HALF_SPREAD, 4),
                    "quote_time_et": started, "fetched_at": started,
                })
            if K in missing:
                continue
            right = "P" if K < F else "C"
            g = pricing.bs(right, F, K, T, iv, disc)
            contracts.append({"expiry": e["expiry"], "strike": K, "right": right,
                              "iv": iv, "iv_bid": iv - BAND, "iv_ask": iv + BAND,
                              "delta": g["delta"], "gamma": g["gamma"],
                              "theta": g["theta"], "vega": g["vega"], "forward": F})
            k = math.log(K / F)
            lo, hi = e["k_range"] or (-1.0, 1.0)
            points.append({"expiry": e["expiry"], "strike": K, "moneyness": k,
                           "readable": str(lo <= k <= hi)})
        exps.append({"expiry": e["expiry"], "forward": F, "days_to_expiry": T * 365,
                     "sessions": sessions,
                     "sessions_calendar": vol.calendar_sessions_between(asof, exp),
                     "half_days": vol.half_days_between(asof, exp),
                     "atm_iv": iv_at(F) if F in STRIKES else (curve(fit, 0.0) if fit else 0.12),
                     "vs_rate": e["level"], "vs_edge_cost": e["edge"], "vs_error": 0.0,
                     "forward_iv_cost": 0.0, "vs_strikes": len(STRIKES),
                     "strikes_read": len(STRIKES)})
        if fit:
            m, s, coef = fit
            fits.append({"expiry": e["expiry"], "sessions": sessions, "forward": F,
                         "points_fitted": 30, "rms_vol_pts": 0.05,
                         "atm_fitted": curve(fit, 0.0), "m": m, "s": s,
                         **{f"c{i}": c for i, c in enumerate(coef)}})

    chain = root / "chains" / name
    write_csv(chain / "options.csv", options)
    write_csv(chain / "spot.csv", [{"price": spot, "quote_time_et": started,
                                    "fetched_at": started}])
    with open(chain / "run.json", "w", encoding="utf-8") as f:
        json.dump({"started_et": started, "spot_at_start": spot}, f)
    write_csv(root / "iv" / name / "contracts.csv", contracts)
    write_csv(root / "iv" / name / "expiries.csv", exps)
    write_csv(root / "surface" / name / "fits.csv", fits)
    write_csv(root / "surface" / name / "points.csv", points)
    return name


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        # Every module the engine reads through, pointed at the fixture. The
        # engine reuses term.load, context.session_remaining and
        # ledger.snapshot_spot rather than copying them, so each of their
        # folders has to move too or the real data/ leaks in.
        for mod, attr, sub in ((scenario, "CHAIN_DIR", "chains"),
                               (scenario, "IV_DIR", "iv"),
                               (scenario, "SURFACE_DIR", "surface"),
                               (scenario, "OUT_DIR", "scenario"),
                               (term, "IV_DIR", "iv"),
                               (term, "SURFACE_DIR", "surface"),
                               (context, "CHAIN_DIR", "chains"),
                               (ledger, "CHAIN_DIR", "chains")):
            old = getattr(mod, attr)
            setattr(mod, attr, self.root / sub)
            self.addCleanup(setattr, mod, attr, old)

    def snapshot(self, expiries=None, started=EST, name=None, **kw):
        expiries = expiries or [expiry("2026-11-06"), expiry("2026-11-09"),
                                expiry("2026-11-13"), expiry("2026-11-20")]
        name = name or dt.datetime.fromisoformat(started).strftime("%Y-%m-%d_%H%M")
        make_snapshot(self.root, name, started, expiries, **kw)
        return scenario.load(name)

    def legs(self, ctx, *rows):
        return scenario.build_legs(ctx, [dict(zip(POS_COLS, map(str, r))) for r in rows])

    def at(self, ctx, legs, date, spot=SPOT, shift=0.0, case="none"):
        return scenario.price_point(ctx, legs, scenario.point(ctx, date, spot, shift, case))


D = dt.date


class TestTheStartGivesBackTheChain(Base):
    """AC-1 and AC-2: before any rule, the engine must reproduce what vol.py
    measured, or nothing it says about other points can be believed."""

    def test_at_the_start_nothing_moves_and_the_pnl_is_zero(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW),
                                      expiry("2026-11-20", fit=SKEW)])
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 1, ""),
                         ("option", "2026-11-20", 580, "P", -2, ""),
                         ("option", "2026-11-20", 620, "P", 1, ""))
        rows, total = self.at(ctx, legs, ctx["date"])
        self.assertEqual(total["pnl"], 0.0)
        for r in rows:
            self.assertEqual(r["pnl"], 0.0)

    def test_each_leg_starts_at_black_scholes_on_vol_pys_own_iv(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)],
                            residuals={("2026-11-20", 580.0): 0.004})
        e = ctx["expiries"]["2026-11-20"]
        when = dt.datetime.fromisoformat(EST)
        T = vol.years_to_expiry(D(2026, 11, 20), when)
        self.assertEqual(e["T"], T)
        for K, right in ((580.0, "P"), (580.0, "C"), (630.0, "C"), (630.0, "P")):
            leg = self.legs(ctx, ("option", "2026-11-20", K, right, 3, ""))[0]
            iv = ctx["contracts"][("2026-11-20", K)]["iv"]
            want = 300 * pricing.bs(right, e["forward"], K, T, iv, math.exp(-RATE * T))["price"]
            self.assertAlmostEqual(leg["start_value"], want, places=9)
            rows, _ = self.at(ctx, [leg], ctx["date"])
            self.assertAlmostEqual(rows[0]["value"], want, places=9)
            self.assertAlmostEqual(rows[0]["iv"], iv, places=12)

    def test_start_greeks_are_the_contracts_greeks_times_quantity_and_100(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        for K in (570.0, 600.0, 640.0):
            c = ctx["contracts"][("2026-11-20", K)]
            legs = self.legs(ctx, ("option", "2026-11-20", K, c["right"], -3, ""))
            rows, _ = self.at(ctx, legs, ctx["date"])
            for g in scenario.GREEKS:
                self.assertAlmostEqual(rows[0][g], -300 * c[g], places=8, msg=f"{K} {g}")

    def test_an_in_the_money_leg_matches_through_parity(self):
        """One IV prices both sides of a strike under the parity forward, so
        the in-the-money leg has the same gamma and vega and a delta one
        share apart."""
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        for K, otm, itm in ((570.0, "P", "C"), (640.0, "C", "P")):
            out = self.at(ctx, self.legs(ctx, ("option", "2026-11-20", K, otm, 1, ""),
                                         ("option", "2026-11-20", K, itm, 1, "")),
                          ctx["date"])[0]
            a, b = out
            self.assertAlmostEqual(a["gamma"], b["gamma"], places=10)
            self.assertAlmostEqual(a["vega"], b["vega"], places=10)
            calls = a if otm == "C" else b
            puts = b if otm == "C" else a
            self.assertAlmostEqual(calls["delta"] - puts["delta"], 100.0, places=8)


class TestSpotKeepsEachStrikesIV(Base):
    """AC-1 of the IV response record: as spot moves each strike keeps its IV,
    whatever the smile, and the fitted curve is read only at the start. These
    replace the slide's three tests (2026-11-12), which pinned each leg
    sliding along the curve with its residual, holding the edge value past
    the fitted range (`edge`), and sticky strike only where there was no fit
    (`no_fit`). On five large moves the strike near the old spot went the
    opposite way to the slide's prediction (measurements.md 2026-11-11)."""

    def test_forwards_move_with_spot_at_the_start(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        rows, _ = self.at(ctx, legs, ctx["date"], spot=SPOT * 1.03)
        F = ctx["expiries"]["2026-11-20"]["forward"]
        self.assertAlmostEqual(rows[0]["forward"], F * 1.03, places=9)

    def test_a_spot_move_leaves_each_strikes_iv_where_it_was(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)],
                            residuals={("2026-11-20", 580.0): 0.01,
                                       ("2026-11-20", 620.0): -0.006})
        F = ctx["expiries"]["2026-11-20"]["forward"]
        for spot in (SPOT * 0.97, SPOT * 1.02):
            for K, resid in ((580.0, 0.01), (620.0, -0.006), (600.0, 0.0)):
                right = "P" if K < F else "C"
                legs = self.legs(ctx, ("option", "2026-11-20", K, right, 1, ""))
                rows, _ = self.at(ctx, legs, ctx["date"], spot=spot)
                start = ctx["contracts"][("2026-11-20", K)]["iv"]
                self.assertAlmostEqual(rows[0]["iv"], start, places=12)
                slid = curve(SKEW, math.log(K / (F * spot / SPOT))) + resid
                self.assertGreater(abs(slid - start), 1e-3)   # the slide would have moved it

    def test_a_strike_far_past_the_fitted_range_keeps_its_iv_with_no_edge_flag(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW, k_range=(-0.06, 0.06))],
                            residuals={("2026-11-20", 600.0): 0.003})
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        rows, total = self.at(ctx, legs, ctx["date"], spot=SPOT * 0.88)
        self.assertAlmostEqual(rows[0]["iv"], ctx["contracts"][("2026-11-20", 600.0)]["iv"],
                               places=12)
        self.assertNotIn("edge", total["flags"])
        self.assertNotIn("edge", scenario.FLAGS)

    def test_an_expiry_without_a_fit_moves_like_any_other(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-13"),
                                      expiry("2026-11-20", fit=None)])
        legs = self.legs(ctx, ("option", "2026-11-20", 590, "P", 1, ""))
        iv0 = ctx["contracts"][("2026-11-20", 590.0)]["iv"]
        rows, total = self.at(ctx, legs, ctx["date"], spot=SPOT * 0.95)
        self.assertAlmostEqual(rows[0]["iv"], iv0, places=12)
        self.assertNotIn("no_fit", total["flags"])
        self.assertNotIn("no_fit", scenario.FLAGS)


class TestTheDateRollsAlongTheTermStructure(Base):
    """AC-4: an expiry's remaining variance is its total less what the term
    structure prices out to the date, on the session clock."""

    LEVELS = {"2026-11-06": 0.10, "2026-11-09": 0.12, "2026-11-13": 0.14,
              "2026-11-20": 0.15}

    def stepped(self):
        return self.snapshot(expiries=[expiry(e, level=v) for e, v in self.LEVELS.items()])

    def total(self, ctx, e):
        return self.LEVELS[e] ** 2 * ctx["expiries"][e]["T"]

    def test_remaining_variance_is_todays_total_less_the_interpolated_total(self):
        ctx = self.stepped()
        rem = ctx["remaining"]
        self.assertAlmostEqual(rem, 15 / 390, places=12)       # 15:45 of a 9:30-16:00 day
        # Tuesday 11-10 is three sessions on, between the Monday and Friday
        # expiries at two and six: a quarter of the way.
        passed = scenario.point(ctx, D(2026, 11, 10), SPOT)["passed"]
        self.assertAlmostEqual(passed, 3 + rem, places=12)
        w9, w13 = self.total(ctx, "2026-11-09"), self.total(ctx, "2026-11-13")
        want = w13 - (w9 + 0.25 * (w13 - w9))
        self.assertAlmostEqual(scenario.remaining_variance(ctx, "2026-11-13", passed),
                               want, places=15)

    def test_before_the_first_expiry_it_interpolates_from_the_snapshot_itself(self):
        """The origin sits at the snapshot, with zero variance, the way
        context.py starts its front window."""
        ctx = self.stepped()
        w6 = self.total(ctx, "2026-11-06")
        rem = ctx["remaining"]
        half = (1 + rem) / 2
        self.assertAlmostEqual(scenario.remaining_variance(ctx, "2026-11-06", half),
                               w6 / 2, places=15)

    def test_a_weekend_with_no_session_leaves_remaining_variance_unchanged(self):
        ctx = self.snapshot(expiries=[expiry(e) for e in self.LEVELS])
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 1, ""))
        friday, saturday, sunday, monday = (D(2026, 11, d) for d in (6, 7, 8, 9))
        rems, totals = [], []
        for d in (friday, saturday, sunday, monday):
            pt = scenario.point(ctx, d, SPOT)
            rems.append(scenario.remaining_variance(ctx, "2026-11-13", pt["passed"]))
            T1 = vol.years_to_expiry(D(2026, 11, 13), pt["when"])
            rows, _ = scenario.price_point(ctx, legs, pt)
            totals.append(rows[0]["iv"] ** 2 * T1)
        self.assertAlmostEqual(rems[0], rems[1], places=15)
        self.assertAlmostEqual(rems[0], rems[2], places=15)
        # what the leg carries is the same total, though its IV reads higher
        self.assertAlmostEqual(totals[0], totals[2], places=14)
        self.assertLess(rems[3], rems[2])                    # Monday is a session

    def test_the_smile_is_scaled_by_the_new_level_over_todays(self):
        ctx = self.stepped()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        pt = scenario.point(ctx, D(2026, 11, 12), SPOT)
        T1 = vol.years_to_expiry(D(2026, 11, 20), pt["when"])
        rem = scenario.remaining_variance(ctx, "2026-11-20", pt["passed"])
        rows, total = scenario.price_point(ctx, legs, pt)
        self.assertAlmostEqual(rows[0]["iv"], 0.12 * math.sqrt(rem / T1) / 0.15, places=12)
        self.assertEqual(total["flags"], set())

    def test_a_negative_remainder_is_flagged_and_keeps_a_constant_iv(self):
        """A later expiry holding less total variance than an earlier one is
        a calendar arbitrage: there is no remainder to roll."""
        ctx = self.snapshot(expiries=[expiry("2026-11-09", level=0.30),
                                      expiry("2026-11-13", level=0.12)])
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 1, ""))
        pt = scenario.point(ctx, D(2026, 11, 10), SPOT)
        self.assertLess(scenario.remaining_variance(ctx, "2026-11-13", pt["passed"]), 0)
        rows, total = scenario.price_point(ctx, legs, pt)
        self.assertIn("negative_var", total["flags"])
        self.assertAlmostEqual(rows[0]["iv"], 0.12, places=12)

    def test_an_expiry_dropped_from_the_term_structure_is_flagged_and_keeps_a_constant_iv(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-06"), expiry("2026-11-09"),
                                      expiry("2026-11-13", edge=0.001),
                                      expiry("2026-11-20")])
        self.assertIn("2026-11-13", ctx["dropped"])
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 1, ""))
        rows, total = self.at(ctx, legs, D(2026, 11, 10))
        self.assertIn("no_term", total["flags"])
        self.assertAlmostEqual(rows[0]["iv"], 0.12, places=12)

    def test_the_forward_keeps_its_carry_rate_and_meets_spot_at_expiry(self):
        ctx = self.stepped()
        e = ctx["expiries"]["2026-11-20"]
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        pt = scenario.point(ctx, D(2026, 11, 19), 610.0)
        T1 = vol.years_to_expiry(D(2026, 11, 20), pt["when"])
        rows, _ = scenario.price_point(ctx, legs, pt)
        self.assertAlmostEqual(rows[0]["forward"],
                               610.0 * (e["forward"] / SPOT) ** (T1 / e["T"]), places=9)
        self.assertLess(rows[0]["forward"] - 610.0, (e["forward"] - SPOT) / 5)


class TestExpiry(Base):
    """AC-5."""

    def test_a_leg_on_its_expiry_is_worth_intrinsic_at_spot_with_zero_greeks(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 2, ""),
                         ("option", "2026-11-13", 620, "P", -1, ""))
        rows, total = self.at(ctx, legs, D(2026, 11, 13), spot=612.0)
        self.assertAlmostEqual(rows[0]["value"], 200 * 12.0, places=9)
        self.assertAlmostEqual(rows[1]["value"], -100 * 8.0, places=9)
        for r in rows:
            self.assertEqual(r["value_low"], r["value_high"])
            for g in scenario.GREEKS:
                self.assertEqual(r[g], 0.0)
        self.assertIn("expired", total["flags"])

    def test_on_a_grid_row_a_leg_past_its_expiry_settled_at_the_rows_spot(self):
        """A grid row holds one spot at every date, so a leg that expired
        earlier in the row settled at that spot. A point with no path behind
        it can mean nothing else."""
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-06", 590, "P", 1, ""))
        rows, _ = self.at(ctx, legs, D(2026, 11, 16), spot=585.0)
        self.assertAlmostEqual(rows[0]["value"], 500.0, places=9)


class TestIVShift(Base):
    """AC-6."""

    def test_a_hundredth_of_a_vol_point_moves_value_by_vega_to_first_order(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("option", "2026-11-20", 600, "P", 1, ""),
                         ("option", "2026-11-20", 570, "P", -2, ""))
        for date in (ctx["date"], D(2026, 11, 12)):
            _, flat = self.at(ctx, legs, date, spot=595.0)
            _, up = self.at(ctx, legs, date, spot=595.0, shift=0.01)
            moved = up["value"] - flat["value"]
            self.assertLess(abs(moved - flat["vega"] * 0.01), 0.01 * abs(flat["vega"] * 0.01))

    def test_the_shift_is_added_after_both_rules(self):
        """Added after the roll, so it is never scaled: two vol points is two
        vol points at any date. Checked where the roll's ratio is well away
        from 1, or the order could not show."""
        levels = TestTheDateRollsAlongTheTermStructure.LEVELS
        ctx = self.snapshot(expiries=[expiry(e, fit=SKEW, level=v) for e, v in levels.items()])
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        pt = scenario.point(ctx, D(2026, 11, 12), 590.0)
        ratio, _ = scenario.roll(ctx, "2026-11-20",
                                 vol.years_to_expiry(D(2026, 11, 20), pt["when"]), pt["passed"])
        self.assertGreater(abs(ratio - 1.0), 0.05)
        plain, _ = self.at(ctx, legs, D(2026, 11, 12), spot=590.0)
        shifted, _ = self.at(ctx, legs, D(2026, 11, 12), spot=590.0, shift=2.0)
        self.assertAlmostEqual(shifted[0]["iv"] - plain[0]["iv"], 0.02, places=12)

    def test_a_shift_below_zero_vol_is_floored_and_flagged(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        rows, total = self.at(ctx, legs, ctx["date"], shift=-20.0)
        self.assertEqual(rows[0]["iv"], scenario.CONFIG["iv_floor"])
        self.assertIn("iv_floor", total["flags"])


class TestHedges(Base):
    """AC-7 and AC-13: hedges carry delta and nothing else."""

    def test_a_share_leg_adds_qty_times_the_spot_move_and_its_qty_in_delta(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("shares", "", "", "", 30, ""))
        for date, spot in ((ctx["date"], 612.5), (D(2026, 11, 13), 590.0)):
            rows, total = self.at(ctx, legs, date, spot=spot)
            self.assertAlmostEqual(total["pnl"], 30 * (spot - SPOT), places=9)
            self.assertEqual(total["delta"], 30.0)
            for g in ("gamma", "theta", "vega"):
                self.assertEqual(total[g], 0.0)
            self.assertEqual(total["pnl_low"], total["pnl_high"])

    def test_one_nes_contract_reads_about_five_shares_with_the_index_at_ten_times_spy(self):
        ctx = self.snapshot()
        leg = self.legs(ctx, ("nes", "", "", "", 1, 6000))[0]
        self.assertAlmostEqual(leg["per"], 5.0, places=12)
        self.assertNotAlmostEqual(leg["per"], 1.0)

    def test_an_nes_leg_carries_its_converted_delta_and_its_pnl_is_that_times_the_move(self):
        ctx = self.snapshot()
        n, P = -3, 6030.0
        legs = self.legs(ctx, ("nes", "", "", "", n, P))
        shares = n * 0.50 * P / SPOT
        rows, total = self.at(ctx, legs, D(2026, 11, 10), spot=588.0)
        self.assertAlmostEqual(total["delta"], shares, places=12)
        self.assertAlmostEqual(total["pnl"], shares * (588.0 - SPOT), places=9)

    def test_nes_legs_in_one_position_share_one_mark(self):
        """A round trip logged in the position file is flat from the start:
        no delta and no P&L anywhere on the grid. The $7 it made before the
        snapshot shows beside the P&L, not in it."""
        ctx = self.snapshot()
        legs = self.legs(ctx, ("nes", "", "", "", 1, 7000.0), ("nes", "", "", "", -1, 7014.0))
        for date, spot in ((ctx["date"], SPOT), (D(2026, 11, 13), 640.0), (D(2026, 11, 13), 560.0)):
            _, total = self.at(ctx, legs, date, spot=spot)
            self.assertAlmostEqual(total["delta"], 0.0, places=12)
            self.assertAlmostEqual(total["pnl"], 0.0, places=9)
        gaps = [r["model_minus_mid"] for r in scenario.leg_rows(legs)]
        self.assertAlmostEqual(sum(gaps), 7.0, places=9)

    def test_an_nes_leg_without_its_fill_is_refused(self):
        ctx = self.snapshot()
        with self.assertRaises(scenario.Refused):
            self.legs(ctx, ("nes", "", "", "", 1, ""))

    def test_a_share_fill_shows_beside_the_pnl_not_in_it(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("shares", "", "", "", 10, 601.5))
        row = scenario.leg_rows(legs)[0]
        self.assertAlmostEqual(row["entry_mid"], 6015.0, places=9)
        self.assertAlmostEqual(row["model_minus_mid"], -15.0, places=9)
        _, total = self.at(ctx, legs, ctx["date"])
        self.assertEqual(total["pnl"], 0.0)


class TestPaths(Base):
    """AC-8: without trades only the endpoint matters; trades add their own
    P&L, each from the spot it was made at."""

    def path(self, ctx, legs, steps):
        rows = [{"date": d.isoformat(), "spot": s, "iv_shift": "", "kind": k,
                 "qty": q, "price": p} for d, s, k, q, p in steps]
        path = self.root / f"path{len(list(self.root.glob('path*')))}.csv"
        write_csv(path, rows)
        return scenario.run_path(ctx, legs, scenario.read_path(path))

    def test_two_unhedged_paths_to_the_same_point_give_the_same_pnl(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("option", "2026-11-13", 590, "P", -1, ""))
        up = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                   (D(2026, 11, 9), 630.0, "", "", ""),
                                   (D(2026, 11, 12), 605.0, "", "", "")])
        down = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                     (D(2026, 11, 9), 570.0, "", "", ""),
                                     (D(2026, 11, 12), 605.0, "", "", "")])
        self.assertAlmostEqual(up[-1]["pnl"], down[-1]["pnl"], places=9)

    def test_hedge_trades_change_a_path_by_exactly_their_own_pnl(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        plain = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                      (D(2026, 11, 9), 630.0, "", "", ""),
                                      (D(2026, 11, 12), 605.0, "", "", "")])
        hedged = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                       (D(2026, 11, 9), 630.0, "shares", -40, ""),
                                       (D(2026, 11, 10), 640.0, "nes", 2, 6450.0),
                                       (D(2026, 11, 12), 605.0, "", "", "")])
        trades = -40 * (605.0 - 630.0) + 2 * 0.50 * 6450.0 / 640.0 * (605.0 - 640.0)
        self.assertAlmostEqual(hedged[-1]["pnl"] - plain[-1]["pnl"], trades, places=9)
        self.assertAlmostEqual(hedged[-1]["pnl_hedges"], trades, places=9)
        self.assertAlmostEqual(hedged[-1]["delta"] - plain[-1]["delta"],
                               -40 + 2 * 0.50 * 6450.0 / 640.0, places=9)

    def hedge_only(self, ctx, legs, steps):
        """The hedges' own P&L and delta along a path: the same path with and
        without its trades, differenced, so the option leg drops out."""
        plain = self.path(ctx, legs, [(d, s, "", "", "") for d, s, *_ in steps])
        hedged = self.path(ctx, legs, steps)
        return [(h["pnl_hedges"], h["delta"] - p["delta"]) for h, p in zip(hedged, plain)]

    def test_closing_an_nes_contract_leaves_no_delta_and_keeps_the_difference_of_its_fills(self):
        """AC-14. Bought at 7000 and sold at 7014, both with SPY at 700: flat,
        $7 made, and still $7 wherever SPY goes afterwards. Converting each
        fill at its own ratio read 5.00 and 5.01 shares, left 0.01 shares of
        delta in a flat position and reported none of the $7."""
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        out = self.hedge_only(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                          (D(2026, 11, 9), 700.0, "nes", 1, 7000.0),
                                          (D(2026, 11, 10), 700.0, "nes", -1, 7014.0),
                                          (D(2026, 11, 12), 720.0, "", "", ""),
                                          (D(2026, 11, 13), 650.0, "", "", "")])
        self.assertAlmostEqual(out[1][1], 5.0, places=12)              # long one, 5 shares
        for pnl, delta in out[2:]:
            self.assertAlmostEqual(pnl, 7.0, places=9)
            self.assertAlmostEqual(delta, 0.0, places=12)

    def test_resizing_an_nes_hedge_marks_every_contract_to_one_price(self):
        """Buy three, sell one at a different basis: what the one made is kept,
        the two left run from their own fill, and delta is two contracts at
        the latest ratio."""
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        out = self.hedge_only(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                          (D(2026, 11, 9), 700.0, "nes", 3, 7000.0),
                                          (D(2026, 11, 10), 710.0, "nes", -1, 7105.0),
                                          (D(2026, 11, 12), 690.0, "", "", "")])
        ratio = 7105.0 / 710.0
        mark = ratio * 690.0
        realized, held = 0.50 * (7105.0 - 7000.0), 0.50 * 2 * (mark - 7000.0)
        self.assertAlmostEqual(out[2][0], 0.50 * 3 * (7105.0 - 7000.0), places=9)
        self.assertAlmostEqual(out[3][0], realized + held, places=9)
        self.assertAlmostEqual(out[3][1], 0.50 * 2 * ratio, places=12)

    def test_a_path_can_close_an_nes_leg_from_the_position_file(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("nes", "", "", "", 2, 6000.0))
        rows = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                     (D(2026, 11, 9), SPOT, "nes", -2, 6030.0),
                                     (D(2026, 11, 12), 640.0, "", "", "")])
        plain = self.path(ctx, self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, "")),
                          [(ctx["date"], SPOT, "", "", ""), (D(2026, 11, 9), SPOT, "", "", ""),
                           (D(2026, 11, 12), 640.0, "", "", "")])
        for r, p in zip(rows[1:], plain[1:]):
            self.assertAlmostEqual(r["pnl"] - p["pnl"], 0.50 * 2 * (6030.0 - 6000.0), places=9)
            self.assertAlmostEqual(r["delta"] - p["delta"], 0.0, places=12)

    def test_resizing_a_share_hedge_keeps_what_was_realized(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        out = self.hedge_only(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                          (D(2026, 11, 9), 720.0, "shares", 40, ""),
                                          (D(2026, 11, 10), 725.0, "shares", -20, ""),
                                          (D(2026, 11, 12), 730.0, "", "", "")])
        self.assertAlmostEqual(out[2][0], 40 * 5.0, places=9)
        self.assertAlmostEqual(out[3][0], 20 * 5.0 + 20 * 10.0, places=9)
        self.assertAlmostEqual(out[3][1], 20.0, places=12)

    def test_an_expired_leg_keeps_what_it_settled_at_whatever_spy_does_next(self):
        """AC-15. A 600 call settled with SPY at 605 is $500 and stays $500:
        re-reading intrinsic at each later step marked it at $1,500 with SPY
        at 615 and at nothing at 590, all at zero delta."""
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 1, ""))
        rows = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                     (D(2026, 11, 13), 605.0, "", "", ""),
                                     (D(2026, 11, 16), 615.0, "", "", ""),
                                     (D(2026, 11, 17), 590.0, "", "", "")])
        for r in rows[1:]:
            self.assertAlmostEqual(r["value"], 500.0, places=9)
            self.assertEqual(r["delta"], 0.0)

    def test_a_calendar_after_its_front_expiry_moves_only_with_its_back_leg(self):
        ctx = self.snapshot()
        cal = self.legs(ctx, ("option", "2026-11-13", 600, "C", -1, ""),
                        ("option", "2026-11-20", 600, "C", 1, ""))
        back = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        rows = self.path(ctx, cal, [(ctx["date"], SPOT, "", "", ""),
                                    (D(2026, 11, 13), 605.0, "", "", ""),
                                    (D(2026, 11, 16), 615.0, "", "", "")])
        front_pnl = -500.0 - cal[0]["start_value"]          # short, settled at 605
        _, b = self.at(ctx, back, D(2026, 11, 16), spot=615.0)
        self.assertAlmostEqual(rows[-1]["pnl"], b["pnl"] + front_pnl, places=9)
        self.assertAlmostEqual(rows[-1]["delta"], b["delta"], places=9)

    def test_the_last_step_on_the_expiry_date_settles_it(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 1, ""))
        rows = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                     (D(2026, 11, 13), 605.0, "", "", ""),
                                     (D(2026, 11, 13), 608.0, "shares", -50, ""),
                                     (D(2026, 11, 16), 615.0, "", "", "")])
        self.assertAlmostEqual(rows[1]["value"], 500.0, places=9)
        self.assertAlmostEqual(rows[-1]["value"], 800.0, places=9)

    def test_a_path_that_steps_over_an_expiry_without_landing_on_it_is_refused(self):
        """SPY's price on the expiry date is what the leg settles at, and a path
        that skips the date leaves the engine nothing to read it from."""
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", 1, ""))
        with self.assertRaises(scenario.Refused) as caught:
            self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                  (D(2026, 11, 12), 605.0, "", "", ""),
                                  (D(2026, 11, 16), 615.0, "", "", "")])
        self.assertIn("2026-11-13", str(caught.exception))
        # A path that ends before the expiry, or lands on it, is fine.
        self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""), (D(2026, 11, 12), 605.0, "", "", "")])

    def test_a_trade_has_no_pnl_at_its_own_step(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        rows = self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                     (D(2026, 11, 9), 630.0, "shares", -40, "")])
        self.assertEqual(rows[-1]["pnl_hedges"], 0.0)

    def test_a_quantity_with_no_kind_is_refused_not_ignored(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        with self.assertRaises(scenario.Refused):
            self.path(ctx, legs, [(ctx["date"], SPOT, "", "", ""),
                                  (D(2026, 11, 9), 630.0, "", -40, "")])

    def test_a_number_that_does_not_parse_is_refused_not_read_as_zero(self):
        """An iv_shift of "typo" ran as no shift and "nan" as NaN P&L, and a
        typo'd qty on a step with no trade was dropped. Blank still means not
        given, and each bad cell is named once."""
        ctx = self.snapshot()
        start = {"date": "2026-11-05", "spot": "600", "iv_shift": "", "kind": "",
                 "qty": "", "price": ""}
        for key, text in (("iv_shift", "typo"), ("iv_shift", "nan"), ("iv_shift", "inf"),
                          ("qty", "1o"), ("spot", "6oo")):
            path = self.root / f"bad_{key}_{text}.csv"
            write_csv(path, [start, dict(start, date="2026-11-10", **{key: text})])
            with self.assertRaises(scenario.Refused) as caught:
                scenario.read_path(path)
            self.assertEqual(caught.exception.reasons,
                             [f"step 2: {key} {text!r} is not a number"])
        path = self.root / "blank.csv"
        write_csv(path, [start])
        self.assertEqual(scenario.read_path(path)[0]["shift"], 0.0)

    def test_a_path_that_goes_back_in_time_is_refused(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        with self.assertRaises(scenario.Refused):
            self.path(ctx, legs, [(D(2026, 11, 10), SPOT, "", "", ""),
                                  (D(2026, 11, 9), SPOT, "", "", "")])


class TestErrorBarsAndEntry(Base):
    """AC-9 and AC-10."""

    def test_every_value_and_pnl_carries_a_range_around_it(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW),
                                      expiry("2026-11-20", fit=SKEW)])
        legs = self.legs(ctx, ("option", "2026-11-13", 600, "C", -2, ""),
                         ("option", "2026-11-20", 600, "C", 2, ""),
                         ("option", "2026-11-20", 575, "P", 1, ""),
                         ("shares", "", "", "", -50, ""))
        rows, _ = scenario.grid(ctx, legs)
        for r in rows:
            self.assertLessEqual(r["value_low"], r["value"] + 1e-9)
            self.assertLessEqual(r["value"], r["value_high"] + 1e-9)
            self.assertLessEqual(r["pnl_low"], r["pnl"] + 1e-9)
            self.assertLessEqual(r["pnl"], r["pnl_high"] + 1e-9)
        start = [r for r in rows if r["leg"] == "total" and r["date"] == ctx["date"]
                 and r["moves"] == 0.0][0]
        self.assertLess(start["pnl_low"], 0.0)       # no position is marked closer than its quotes
        self.assertGreater(start["pnl_high"], 0.0)

    def test_offsetting_contracts_on_one_strike_carry_no_range(self):
        """Codex's case: +10 and -10 of one call read one IV, so they cannot err
        apart, yet adding each leg's extremes gave them a range (-$10 to +$10
        on the Nov-20 750C of 2026-11-10_1540). A synthetic, long a call and
        short the put at one strike, is the same: its value does not depend on
        IV at all."""
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        for rows in ((("option", "2026-11-20", 600, "C", 10, ""),
                      ("option", "2026-11-20", 600, "C", -10, "")),
                     (("option", "2026-11-20", 600, "C", 1, ""),
                      ("option", "2026-11-20", 600, "P", -1, ""))):
            legs = self.legs(ctx, *rows)
            for date, spot in ((ctx["date"], SPOT), (D(2026, 11, 10), 585.0)):
                _, total = self.at(ctx, legs, date, spot)
                self.assertAlmostEqual(total["value_low"], total["value"], places=9)
                self.assertAlmostEqual(total["value_high"], total["value"], places=9)
                self.assertAlmostEqual(total["pnl_low"], total["pnl"], places=9)
                self.assertAlmostEqual(total["pnl_high"], total["pnl"], places=9)

    def test_legs_on_different_strikes_still_add_their_extremes(self):
        """Only one strike's legs share an IV. Between strikes the range still
        adds each one's worst case (A-017), so a vertical's range is the sum."""
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("option", "2026-11-20", 605, "C", -1, ""))
        rows, total = self.at(ctx, legs, ctx["date"])
        self.assertAlmostEqual(total["value_low"], sum(r["value_low"] for r in rows), places=9)
        self.assertAlmostEqual(total["value_high"], sum(r["value_high"] for r in rows), places=9)
        self.assertLess(total["value_low"], total["value"])

    def test_a_leg_with_no_iv_of_its_own_reads_the_curve_with_the_fit_rms_as_its_band(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)], missing=(605.0,))
        leg = self.legs(ctx, ("option", "2026-11-20", 605, "C", 1, ""))[0]
        F = ctx["expiries"]["2026-11-20"]["forward"]
        self.assertEqual(leg["source"], "fit")
        self.assertIn("fit_iv", leg["flags"])
        lo, mid, hi = leg["ivs"]
        self.assertAlmostEqual(mid, curve(SKEW, math.log(605 / F)), places=12)
        self.assertAlmostEqual(hi - mid, 0.0005, places=12)
        self.assertAlmostEqual(mid - lo, 0.0005, places=12)

    def test_a_strike_the_chain_does_not_list_is_refused_not_read_off_the_curve(self):
        """The curve's fallback is for a strike vol.py could not read. A strike
        that was never listed is not one: it has no quote to enter at and
        nobody to trade it with."""
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        with self.assertRaises(scenario.Refused) as caught:
            self.legs(ctx, ("option", "2026-11-20", 603, "C", 1, ""))
        self.assertIn("not in this snapshot's chain", str(caught.exception))

    def test_a_strike_with_no_iv_outside_the_fitted_range_is_refused(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW, k_range=(-0.05, 0.05))],
                            missing=(650.0,))
        with self.assertRaises(scenario.Refused) as caught:
            self.legs(ctx, ("option", "2026-11-20", 650, "C", 1, ""))
        self.assertIn("outside the fitted range", str(caught.exception))

    def test_entry_is_reported_at_mid_and_at_the_far_side(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 2, ""),
                         ("option", "2026-11-20", 590, "P", -3, ""))
        quotes = ctx["quotes"]
        for leg, row in zip(legs, scenario.leg_rows(legs)):
            bid, ask = quotes[("2026-11-20", leg["strike"], leg["right"])]
            q = leg["qty"] * 100
            self.assertAlmostEqual(row["entry_mid"], q * (bid + ask) / 2, places=9)
            self.assertAlmostEqual(row["entry_far"], q * (ask if q > 0 else bid), places=9)
            self.assertAlmostEqual(row["model_minus_mid"],
                                   leg["start_value"] - row["entry_mid"], places=9)

    def test_a_long_leg_never_costs_less_at_the_far_side(self):
        ctx = self.snapshot()
        rows = scenario.leg_rows(self.legs(
            ctx, *[("option", "2026-11-20", K, r, q, "")
                   for K in (560, 600, 640) for r in ("C", "P") for q in (1, -1)]))
        for r in rows:
            self.assertGreaterEqual(r["entry_far"], r["entry_mid"])

    def test_a_leg_past_09_delta_is_flagged(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 545, "C", 1, ""))
        _, total = self.at(ctx, legs, ctx["date"])
        self.assertIn("deep", total["flags"])
        _, total = self.at(ctx, self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, "")),
                            ctx["date"])
        self.assertNotIn("deep", total["flags"])


class TestIVResponse(Base):
    """AC-2 to AC-7 and AC-10 of docs/changes/2026-11-11-iv-response.md: three
    IV responses to the spot move, named for the IV change, scaled by the
    days each leg has left and by nothing else."""

    EXP = "2026-11-20"

    def test_the_response_is_rate_times_move_times_root_30_over_days(self):
        """The record's worked case: a leg 10 days out, SPY 2% either way."""
        r = scenario.response
        self.assertAlmostEqual(r(0.98, 10.0, "moderate"), 2 * math.sqrt(3), places=12)
        self.assertAlmostEqual(r(0.98, 10.0, "large"), 4 * math.sqrt(3), places=12)
        self.assertAlmostEqual(r(1.02, 10.0, "moderate"), -2 * math.sqrt(3), places=12)
        self.assertAlmostEqual(r(1.02, 10.0, "large"), -3 * math.sqrt(3), places=12)
        self.assertAlmostEqual(r(0.98, 10.0, "moderate"), 3.46, places=2)
        self.assertAlmostEqual(r(1.02, 10.0, "large"), -5.20, places=2)

    def test_a_leg_carries_its_response_on_top_of_its_own_iv(self):
        ctx = self.snapshot(expiries=[expiry(self.EXP, fit=SKEW)])
        legs = self.legs(ctx, ("option", self.EXP, 600, "C", 1, ""))
        iv0 = ctx["contracts"][(self.EXP, 600.0)]["iv"]
        days = ctx["expiries"][self.EXP]["T"] * 365
        for spot, case, rate in ((SPOT * 0.98, "moderate", 1.0), (SPOT * 0.98, "large", 2.0),
                                 (SPOT * 1.02, "moderate", -1.0), (SPOT * 1.02, "large", -1.5)):
            rows, _ = self.at(ctx, legs, ctx["date"], spot=spot, case=case)
            want = rate * 2.0 * math.sqrt(30 / days)
            self.assertAlmostEqual(rows[0]["iv_response"], want, places=9)
            self.assertAlmostEqual(rows[0]["iv"], iv0 + want / 100, places=12)

    def test_no_spot_move_and_no_response_mean_no_change(self):
        ctx = self.snapshot(expiries=[expiry(self.EXP, fit=SKEW)])
        legs = self.legs(ctx, ("option", self.EXP, 600, "C", 1, ""))
        for case in scenario.CASES:
            rows, total = self.at(ctx, legs, ctx["date"], case=case)
            self.assertEqual(rows[0]["iv_response"], 0.0)
            self.assertEqual(total["pnl"], 0.0)
        rows, _ = self.at(ctx, legs, ctx["date"], spot=SPOT * 0.9, case="none")
        self.assertEqual(rows[0]["iv_response"], 0.0)

    def test_every_strike_on_one_expiry_gets_one_response_scaled_by_its_days(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW), expiry(self.EXP, fit=SKEW)])
        legs = self.legs(ctx, ("option", self.EXP, 580, "P", 1, ""),
                         ("option", self.EXP, 620, "C", -1, ""),
                         ("option", "2026-11-13", 600, "C", 1, ""))
        rows, _ = self.at(ctx, legs, ctx["date"], spot=SPOT * 0.97, case="large")
        self.assertEqual(rows[0]["iv_response"], rows[1]["iv_response"])
        d20 = ctx["expiries"][self.EXP]["T"] * 365
        d13 = ctx["expiries"]["2026-11-13"]["T"] * 365
        self.assertAlmostEqual(rows[2]["iv_response"] / rows[0]["iv_response"],
                               math.sqrt(d20 / d13), places=12)

    def test_the_response_goes_on_after_the_roll_together_with_the_shift(self):
        """IV = today's IV x the roll's ratio + (response + shift) / 100,
        where the ratio is well away from 1 so the order shows."""
        levels = TestTheDateRollsAlongTheTermStructure.LEVELS
        ctx = self.snapshot(expiries=[expiry(e, fit=SKEW, level=v) for e, v in levels.items()])
        legs = self.legs(ctx, ("option", self.EXP, 600, "C", 1, ""))
        pt = scenario.point(ctx, D(2026, 11, 12), 590.0, 2.0, "large")
        T1 = vol.years_to_expiry(D(2026, 11, 20), pt["when"])
        ratio, _ = scenario.roll(ctx, self.EXP, T1, pt["passed"])
        self.assertGreater(abs(ratio - 1.0), 0.05)
        resp = scenario.response(590.0 / SPOT, T1 * 365, "large")
        rows, _ = scenario.price_point(ctx, legs, pt)
        iv0 = ctx["contracts"][(self.EXP, 600.0)]["iv"]
        self.assertAlmostEqual(rows[0]["iv"], iv0 * ratio + (resp + 2.0) / 100, places=12)
        rows, total = self.at(ctx, legs, ctx["date"], spot=SPOT * 1.05, shift=-12.0,
                              case="large")
        self.assertEqual(rows[0]["iv"], scenario.CONFIG["iv_floor"])
        self.assertIn("iv_floor", total["flags"])

    def test_the_same_move_gets_the_same_rate_whatever_the_horizon(self):
        """The rates apply to the whole move from the snapshot, however many
        sessions it took (owner, 2026-11-12): the horizon reaches the
        response only through the days the leg has left."""
        ctx = self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW), expiry(self.EXP, fit=SKEW)])
        legs = self.legs(ctx, ("option", self.EXP, 600, "C", 1, ""))
        per, days = [], []
        for date in (ctx["date"], scenario.sessions_after(ctx["date"], 5)):
            rows, _ = self.at(ctx, legs, date, spot=SPOT * 0.97, case="moderate")
            days.append(rows[0]["days_left"])
            per.append(rows[0]["iv_response"] / math.sqrt(30 / rows[0]["days_left"]))
        self.assertGreater(days[0] - days[1], 5)              # the leg aged a week
        self.assertAlmostEqual(per[0], per[1], places=9)
        self.assertAlmostEqual(per[0], 3.0, places=9)

    def test_a_leg_outside_one_to_five_weeks_is_flagged_tenor_not_capped(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-06"), expiry(self.EXP),
                                      expiry("2026-12-18")])
        legs = self.legs(ctx, ("option", "2026-11-06", 600, "C", 1, ""),
                         ("option", self.EXP, 600, "C", 1, ""),
                         ("option", "2026-12-18", 600, "C", 1, ""))
        rows, _ = self.at(ctx, legs, ctx["date"], spot=SPOT * 0.98, case="moderate")
        self.assertEqual(["tenor" in r["flags"] for r in rows], [True, False, True])
        days = ctx["expiries"]["2026-11-06"]["T"] * 365
        self.assertLess(days, 7)
        self.assertAlmostEqual(rows[0]["iv_response"], 2 * math.sqrt(30 / days), places=9)
        rows, total = self.at(ctx, legs, ctx["date"], case="moderate")
        self.assertNotIn("tenor", total["flags"])        # no move, no response, no flag

    def test_an_unknown_case_is_refused(self):
        ctx = self.snapshot()
        with self.assertRaises(scenario.Refused):
            scenario.point(ctx, ctx["date"], SPOT, 0.0, "bad")

    def straddle(self, ctx, qty):
        return self.legs(ctx, ("option", self.EXP, 600, "C", qty, ""),
                         ("option", self.EXP, 600, "P", qty, ""))

    def test_the_lowest_case_depends_on_the_position(self):
        """A bigger IV fall on a rally helps a short straddle and hurts a long
        one, so no case is the bad one. Where spot has not moved the cases
        agree and none is named."""
        ctx = self.snapshot(expiries=[expiry(self.EXP, fit=SKEW)])
        for qty, spot, want in ((-1, SPOT * 1.02, ("none", "large")),
                                (1, SPOT * 1.02, ("large", "none")),
                                (-1, SPOT * 0.98, ("large", "none")),
                                (1, SPOT * 0.98, ("none", "large")),
                                (-1, SPOT, (None, None))):
            legs = self.straddle(ctx, qty)
            by = {c: self.at(ctx, legs, ctx["date"], spot=spot, case=c)[1]
                  for c in scenario.CASES}
            self.assertEqual(scenario.extremes(by), want, (qty, spot))

    def test_every_grid_point_carries_all_three_cases(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW), expiry(self.EXP, fit=SKEW)])
        legs = self.legs(ctx, ("option", self.EXP, 600, "C", -1, ""),
                         ("option", "2026-11-13", 590, "P", 2, ""),
                         ("shares", "", "", "", 10, ""))
        rows, totals = scenario.grid(ctx, legs, sessions=(2,))
        seen = {}
        for r in rows:
            seen.setdefault((r["date"], r["moves"], r["leg"]), set()).add(r["response"])
            self.assertLessEqual(r["pnl_low"], r["pnl"] + 1e-9)
            self.assertLessEqual(r["pnl"], r["pnl_high"] + 1e-9)
            for g in scenario.GREEKS:
                self.assertIsNotNone(r[g])
        self.assertEqual(set(map(frozenset, seen.values())), {frozenset(scenario.CASES)})
        self.assertIn(scenario.sessions_after(ctx["date"], 2), {d for d, _, _ in seen})
        self.assertEqual(len(totals), len(seen) / 4 * 3)
        moved = [r for r in rows if r["leg"] == "+2 2026-11-13 590P" and r["moves"] == -1.0
                 and r["date"] == ctx["date"]]
        self.assertEqual(len({r["iv"] for r in moved}), 3)  # three IVs, three values


class TestHorizon(Base):
    """AC-4: the horizon is its own input. `--sessions` adds the closes that
    many sessions after the snapshot, apart from any leg's days to expiry."""

    def test_sessions_add_the_closes_that_many_sessions_out(self):
        ctx = self.snapshot()                                 # Thursday 2026-11-05
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("option", "2026-11-06", 600, "P", 1, ""))
        dates = scenario.grid_dates(ctx, legs, (1, 5))
        self.assertEqual(dates, [ctx["date"], D(2026, 11, 6), D(2026, 11, 12),
                                 D(2026, 11, 19), D(2026, 11, 20)])  # Nov 6 once
        self.assertEqual(scenario.sessions_after(D(2026, 11, 25), 1), D(2026, 11, 27))

    def test_sessions_that_are_not_positive_whole_numbers_are_refused(self):
        for bad in ("0", "-1", "1.5", "x", "nan", "1,,2"):
            with self.assertRaises(scenario.Refused, msg=bad):
                scenario.parse_sessions(bad)
        self.assertEqual(scenario.parse_sessions("5,1,1"), (1, 5))
        self.assertEqual(scenario.parse_sessions(None), ())

    def test_a_path_is_priced_with_no_response(self):
        """AC-10: a path is the owner's own story for IV, in its iv_shift
        column; a response on top would count it twice."""
        ctx = self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW),
                                      expiry("2026-11-20", fit=SKEW)])
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", -1, ""),
                         ("option", "2026-11-20", 600, "P", -1, ""))
        steps = [{"step": 1, "date": ctx["date"], "spot": SPOT, "shift": 0.0,
                  "kind": "", "qty": None, "price": None},
                 {"step": 2, "date": D(2026, 11, 10), "spot": SPOT * 0.97, "shift": 1.0,
                  "kind": "", "qty": None, "price": None}]
        rows = scenario.run_path(ctx, legs, steps)
        _, none = self.at(ctx, legs, D(2026, 11, 10), spot=SPOT * 0.97, shift=1.0)
        _, moderate = self.at(ctx, legs, D(2026, 11, 10), spot=SPOT * 0.97, shift=1.0,
                              case="moderate")
        self.assertAlmostEqual(rows[1]["pnl"], none["pnl"], places=9)
        self.assertGreater(abs(rows[1]["pnl"] - moderate["pnl"]), 1.0)


class TestSpreadBounds(Base):
    """Codex's case: a butterfly marked below zero and a $5 vertical above $500,
    with no flag. The smile rules are not arbitrage-aware, so prices that break
    a spread's bounds are flagged `arb`, with the largest breach, and left as
    they are. A residual of our choosing at one strike makes the breach."""

    EXP = "2026-11-20"

    def calls(self, ctx, legs, rows):
        """Per-share call values at each leg's strike, by hand: a put through
        parity at the start's forward and discount."""
        e = ctx["expiries"][self.EXP]
        out = {}
        for leg, r in zip(legs, rows):
            per = r["value"] / (leg["qty"] * 100)
            if leg["right"] == "P":
                per += e["disc"] * (e["forward"] - leg["strike"])
            out[leg["strike"]] = per
        return out, e["disc"]

    def test_a_butterfly_priced_below_zero_is_flagged_with_its_size(self):
        ctx = self.snapshot(expiries=[expiry(self.EXP)],
                            residuals={(self.EXP, 600.0): 0.05})
        legs = self.legs(ctx, ("option", self.EXP, 595, "C", 1, ""),
                         ("option", self.EXP, 600, "C", -2, ""),
                         ("option", self.EXP, 605, "C", 1, ""))
        rows, total = self.at(ctx, legs, ctx["date"])
        c, _ = self.calls(ctx, legs, rows)
        fly = c[595.0] - 2 * c[600.0] + c[605.0]
        self.assertLess(fly, -scenario.CONFIG["arb_tolerance"])
        self.assertIn("arb", total["flags"])
        self.assertTrue(all("arb" in r["flags"] for r in rows))
        self.assertEqual(total["arb"]["spread"], "butterfly")
        self.assertEqual(total["arb"]["strikes"], [595.0, 600.0, 605.0])
        self.assertAlmostEqual(total["arb"]["size"], -fly, places=9)

    def test_a_vertical_above_its_width_is_flagged_through_puts_too(self):
        """Held as puts, the same strikes are checked through parity: the put
        at 600 priced above the put at 605 is the call vertical over $5."""
        ctx = self.snapshot(expiries=[expiry(self.EXP)],
                            residuals={(self.EXP, 600.0): 0.10})
        for right in ("C", "P"):
            legs = self.legs(ctx, ("option", self.EXP, 600, right, 1, ""),
                             ("option", self.EXP, 605, right, -1, ""))
            rows, total = self.at(ctx, legs, ctx["date"])
            c, disc = self.calls(ctx, legs, rows)
            over = (c[600.0] - c[605.0]) - 5 * disc
            self.assertGreater(over, scenario.CONFIG["arb_tolerance"])
            self.assertEqual(total["arb"]["spread"], "vertical")
            self.assertAlmostEqual(total["arb"]["size"], over, places=9)
            self.assertIn("arb", total["flags"])

    def test_spreads_inside_their_bounds_raise_nothing(self):
        ctx = self.snapshot(expiries=[expiry(self.EXP, fit=SKEW)])
        legs = self.legs(ctx, ("option", self.EXP, 595, "C", 1, ""),
                         ("option", self.EXP, 600, "C", -2, ""),
                         ("option", self.EXP, 605, "P", 1, ""))
        for date, spot in ((ctx["date"], SPOT), (D(2026, 11, 10), 590.0)):
            rows, total = self.at(ctx, legs, date, spot)
            self.assertNotIn("arb", total["flags"])
            self.assertIsNone(total["arb"])

    def test_a_breach_is_flagged_only_on_the_strikes_in_it(self):
        ctx = self.snapshot(expiries=[expiry(self.EXP), expiry("2026-11-13")],
                            residuals={(self.EXP, 600.0): 0.10})
        legs = self.legs(ctx, ("option", self.EXP, 600, "C", 1, ""),
                         ("option", self.EXP, 605, "C", -1, ""),
                         ("option", "2026-11-13", 600, "C", 1, ""),
                         ("shares", "", "", "", 10, ""))
        rows, _ = self.at(ctx, legs, ctx["date"])
        self.assertEqual(["arb" in r["flags"] for r in rows], [True, True, False, False])


class TestClock(Base):
    """AC-11: time is right across a change of clocks and across a 1pm
    close, and the engine stands on vol.py's clock to the second."""

    def test_vol_years_to_expiry_counts_the_hour_the_clocks_gave_back(self):
        when = dt.datetime.fromisoformat(EDT)
        seconds = 8 * 86400 + 15 * 60 + 3600     # 15:45 EDT to 16:00 EST, eight days on
        self.assertAlmostEqual(vol.years_to_expiry(D(2026, 11, 6), when),
                               seconds / (365 * 86400), places=15)

    def test_a_time_in_new_york_counts_the_changed_hour_too(self):
        """Codex's case. The test above starts from a fixed -04:00, as a
        snapshot's own time does. scenario.point builds later dates in
        America/New_York, the same zone object as the expiry's close, and
        Python then subtracts clock readings: the Oct-30 close to the Nov-6
        close read 168 hours, though 169 passed. A spring change is an hour
        short the other way."""
        for start, end, hours in ((D(2026, 10, 30), D(2026, 11, 6), 169),
                                  (D(2027, 3, 12), D(2027, 3, 19), 167),
                                  (D(2026, 11, 6), D(2026, 11, 13), 168)):
            when = dt.datetime.combine(start, dt.time(16, 0), tzinfo=vol.ET)
            self.assertAlmostEqual(vol.years_to_expiry(end, when) * 365 * 24, hours, places=9)

    def test_a_scenario_date_before_the_change_prices_on_the_hours_that_pass(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-06"), expiry("2026-11-13")],
                            started=EDT)
        pt = scenario.point(ctx, D(2026, 10, 30), SPOT)
        self.assertAlmostEqual(vol.years_to_expiry(D(2026, 11, 6), pt["when"]) * 365 * 24,
                               169, places=9)
        legs = self.legs(ctx, ("option", "2026-11-06", 600, "C", 1, ""))
        rows, _ = scenario.price_point(ctx, legs, pt)
        F1 = rows[0]["forward"]
        T1 = 169 / (365 * 24)
        expected = 100 * pricing.bs("C", F1, 600.0, T1, rows[0]["iv"],
                                    math.exp(-RATE * T1))["price"]
        self.assertAlmostEqual(rows[0]["value"], expected, places=9)

    def test_an_edt_snapshot_prices_back_its_chain_across_the_change(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-06", fit=SKEW),
                                      expiry("2026-11-13", fit=SKEW)], started=EDT)
        self.check_start(ctx, "2026-11-06")

    def test_an_est_snapshot_prices_back_its_chain(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW),
                                      expiry("2026-11-20", fit=SKEW)], started=EST)
        self.check_start(ctx, "2026-11-13")

    def check_start(self, ctx, exp):
        e = ctx["expiries"][exp]
        self.assertEqual(e["T"], vol.years_to_expiry(e["date"], ctx["started"]))
        c = ctx["contracts"][(exp, 590.0)]
        legs = self.legs(ctx, ("option", exp, 590, c["right"], 1, ""))
        rows, total = self.at(ctx, legs, ctx["date"])
        self.assertEqual(total["pnl"], 0.0)
        self.assertAlmostEqual(rows[0]["delta"], 100 * c["delta"], places=10)
        self.assertAlmostEqual(rows[0]["vega"], 100 * c["vega"], places=10)

    def test_a_date_across_the_change_is_valued_at_its_own_close(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-06"), expiry("2026-11-13")],
                            started=EDT)
        pt = scenario.point(ctx, D(2026, 11, 2), SPOT)
        self.assertEqual(pt["when"].utcoffset(), dt.timedelta(hours=-5))
        self.assertEqual((pt["when"].hour, pt["when"].minute), (16, 0))

    def test_a_1pm_close_is_valued_at_13_00_and_counts_half_a_session(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-23"), expiry("2026-11-25"),
                                      expiry("2026-11-30"), expiry("2026-12-04")],
                            started=PRE_HALF)
        pt = scenario.point(ctx, D(2026, 11, 27), SPOT)
        self.assertEqual((pt["when"].hour, pt["when"].minute), (13, 0))
        # Mon, Tue, Wed whole; Thanksgiving shut; Friday half
        self.assertAlmostEqual(pt["passed"], 3.5 + ctx["remaining"], places=12)
        thursday = scenario.point(ctx, D(2026, 11, 26), SPOT)
        self.assertAlmostEqual(thursday["passed"], 3.0 + ctx["remaining"], places=12)
        legs = self.legs(ctx, ("option", "2026-11-30", 600, "C", 1, ""))
        rems = [scenario.remaining_variance(ctx, "2026-11-30", p["passed"])
                for p in (thursday, pt)]
        w23 = 0.12 ** 2 * ctx["expiries"]["2026-11-23"]["T"]
        self.assertLess(rems[1], rems[0])                      # the half day costs something
        self.assertGreater(rems[1], rems[0] - w23)             # but less than a whole one
        rows, _ = scenario.price_point(ctx, legs, pt)
        self.assertGreater(rows[0]["value"], 0.0)


class TestGrid(Base):
    def test_the_grid_runs_three_expected_moves_either_side_in_half_moves(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("option", "2026-11-13", 600, "P", 1, ""))
        spots, front, move = scenario.grid_spots(ctx, legs)
        self.assertEqual(front, "2026-11-13")
        e = ctx["expiries"]["2026-11-13"]
        self.assertAlmostEqual(move, 0.12 * math.sqrt(e["T"]), places=12)
        self.assertEqual([m for m, _ in spots], [x / 2 for x in range(-6, 7)])
        for m, s in spots:
            self.assertAlmostEqual(s, SPOT * math.exp(m * move), places=9)

    def straddle(self, ctx, K=600):
        return self.legs(ctx, ("option", "2026-11-20", K, "C", 1, ""),
                         ("option", "2026-11-20", K, "P", 1, ""))

    def test_with_no_response_the_grid_slope_is_the_fixed_iv_delta_on_both_sides(self):
        """Each strike keeps its IV as spot moves, so under `none` the grid's
        slope is the delta, even on a skewed smile. Under the slide it was
        delta plus vega x the slide: +32.99 against +15.90 shares on
        Codex's Nov-13 750 straddle of 2026-11-09_1421."""
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        legs = self.straddle(ctx)
        _, now = self.at(ctx, legs, ctx["date"])
        self.assertEqual(scenario.grid_slope(ctx, legs), (now["delta"], now["delta"]))
        h = 0.01
        _, up = self.at(ctx, legs, ctx["date"], spot=SPOT + h)
        _, dn = self.at(ctx, legs, ctx["date"], spot=SPOT - h)
        self.assertAlmostEqual((up["value"] - dn["value"]) / (2 * h), now["delta"], places=4)

    def test_each_response_adds_vega_times_its_own_slope_on_each_side(self):
        """below = delta - vega x drop rate x 100/S x sqrt(30/days); above =
        delta + vega x rally rate x the same. A bump a tenth of a cent each
        way gives the same numbers, and the large case, whose rates differ
        by side, has a kink at spot."""
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        legs = self.straddle(ctx)
        rows, now = self.at(ctx, legs, ctx["date"])
        days = rows[0]["days_left"]
        k = math.sqrt(30 / days) * 100 / SPOT
        h = 0.001
        for case in ("moderate", "large"):
            down, up = scenario.CONFIG["response"][case]
            below, above = scenario.grid_slope(ctx, legs, case=case)
            self.assertAlmostEqual(below, now["delta"] - now["vega"] * down * k, places=9)
            self.assertAlmostEqual(above, now["delta"] + now["vega"] * up * k, places=9)
            v0 = now["value"]
            _, lo = scenario.price_point(ctx, legs, scenario.point(ctx, ctx["date"], SPOT - h,
                                                                   case=case))
            _, hi = scenario.price_point(ctx, legs, scenario.point(ctx, ctx["date"], SPOT + h,
                                                                   case=case))
            self.assertAlmostEqual((v0 - lo["value"]) / h, below, delta=0.05)
            self.assertAlmostEqual((hi["value"] - v0) / h, above, delta=0.05)
        below, above = scenario.grid_slope(ctx, legs, case="large")
        self.assertGreater(abs(below - now["delta"]), abs(above - now["delta"]))

    def test_the_report_shows_the_grid_slope_beside_the_delta(self):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        legs = self.straddle(ctx)
        rows, totals = scenario.grid(ctx, legs)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scenario.report_grid(ctx, legs, "pos", rows, totals, 0.0, self.root)
        self.assertIn("at fixed IV", out.getvalue())
        self.assertIn("grid slope at spot", out.getvalue())
        self.assertIn("(the delta)", out.getvalue())
        self.assertIn("untested", out.getvalue())

    def report_for(self, shift):
        ctx = self.snapshot(expiries=[expiry("2026-11-20", fit=SKEW)])
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""))
        rows, totals = scenario.grid(ctx, legs, shift)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scenario.report_grid(ctx, legs, "pos", rows, totals, shift, self.root)
        return out.getvalue(), totals[(ctx["date"], 0.0, "none")]

    def test_a_shifted_grid_says_the_shock_is_the_shock_and_the_band_is_the_band(self):
        """With --shift -5 a call read -154 at the start, -156 to -153, and the
        report put all of it down to the IV bands. The -154 is the shock asked
        for; the bands are the $3 around it."""
        text, start = self.report_for(-5.0)
        self.assertLess(start["pnl"], -1.0)                    # the shock moved it
        self.assertNotIn("IV bands alone", text)
        self.assertIn(f"-5.00 point shift alone moves the value by {start['pnl']:+,.0f}", text)
        width = start["pnl_high"] - start["pnl_low"]
        self.assertLess(width, abs(start["pnl"]))              # the band is the small part
        self.assertIn(f"${width:,.0f} wide", text)

    def test_an_unshifted_grid_puts_its_start_range_down_to_the_bands_alone(self):
        text, start = self.report_for(0.0)
        self.assertEqual(start["pnl"], 0.0)
        self.assertIn("IV bands alone", text)
        self.assertNotIn("shift alone", text)

    def test_the_grid_dates_are_now_each_expiry_and_the_session_before_the_last(self):
        ctx = self.snapshot()
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("option", "2026-11-09", 600, "P", 1, ""))
        self.assertEqual(scenario.grid_dates(ctx, legs),
                         [ctx["date"], D(2026, 11, 9), D(2026, 11, 19), D(2026, 11, 20)])

    def test_a_date_before_the_snapshot_is_refused(self):
        ctx = self.snapshot()
        with self.assertRaises(scenario.Refused):
            scenario.point(ctx, D(2026, 11, 4), SPOT)

    def test_a_filled_row_with_a_blank_kind_is_refused_not_dropped(self):
        """Skipping it priced a straddle as a lone call. Only a wholly blank
        row, or one commented out with #, may be left out."""
        ctx = self.snapshot()
        with self.assertRaises(scenario.Refused) as caught:
            self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                      ("", "2026-11-20", 600, "P", 1, ""))
        self.assertIn("row 2", str(caught.exception))
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", 1, ""),
                         ("", "", "", "", "", ""),
                         ("# option", "2026-11-20", 600, "P", 1, ""))
        self.assertEqual([l["label"] for l in legs], ["+1 2026-11-20 600C"])

    def test_an_expiry_the_snapshot_never_read_is_refused(self):
        ctx = self.snapshot()
        with self.assertRaises(scenario.Refused) as caught:
            self.legs(ctx, ("option", "2026-11-27", 600, "C", 1, ""),
                      ("option", "2026-11-20", 600, "X", 1, ""))
        self.assertEqual(len(caught.exception.reasons), 2)   # every problem, not the first


class AppBase(Base):
    """Runs `python app.py scenario` in-process against the fixture."""

    def position(self, rows, name="pos"):
        path = self.root / f"{name}.csv"
        write_csv(path, [dict(zip(POS_COLS, r)) for r in rows])
        return path

    def run_app(self, *args):
        old = sys.argv
        sys.argv = ["app.py", "scenario", *map(str, args)]
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                app.main()
        finally:
            sys.argv = old
        return out.getvalue()

    def header(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            return next(csv.reader(f))


class TestCommand(AppBase):
    """AC-12: through app.py, with its columns, and nothing left behind by a
    refusal."""

    def test_writes_legs_and_grid_with_their_columns_through_app_py(self):
        self.snapshot()
        pos = self.position([("option", "2026-11-20", 600, "C", 1, ""),
                             ("nes", "", "", "", -1, 6000)])
        out = self.run_app(pos, "2026-11-05_1545")
        dest = self.root / "scenario" / "2026-11-05_1545" / "pos"
        self.assertEqual(self.header(dest / "legs.csv"), scenario.LEG_COLS)
        self.assertEqual(self.header(dest / "grid.csv"), scenario.GRID_COLS)
        self.assertIn("not a forecast", out)
        self.assertIn("5.000 SPY shares", out)

    def test_a_path_writes_path_csv_with_its_columns(self):
        self.snapshot()
        pos = self.position([("option", "2026-11-20", 600, "C", 1, "")])
        path = self.root / "walk.csv"
        write_csv(path, [{"date": "2026-11-05", "spot": SPOT, "iv_shift": "",
                          "kind": "", "qty": "", "price": ""},
                         {"date": "2026-11-10", "spot": 590, "iv_shift": 1,
                          "kind": "shares", "qty": 20, "price": ""}])
        self.run_app(pos, "2026-11-05_1545", "--path", path)
        dest = self.root / "scenario" / "2026-11-05_1545" / "pos"
        self.assertEqual(self.header(dest / "path.csv"), scenario.PATH_COLS)

    def test_the_report_names_the_largest_spread_breach(self):
        self.snapshot(expiries=[expiry("2026-11-13"), expiry("2026-11-20")],
                      residuals={("2026-11-20", 600.0): 0.05})
        pos = self.position([("option", "2026-11-20", 595, "C", 1, ""),
                             ("option", "2026-11-20", 600, "C", -2, ""),
                             ("option", "2026-11-20", 605, "C", 1, "")])
        out = self.run_app(pos, "2026-11-05_1545")
        self.assertIn("! arb:", out)
        self.assertIn("largest: the 2026-11-20 595/600/605 butterfly off its bound by", out)
        grid = self.root / "scenario" / "2026-11-05_1545" / "pos" / "grid.csv"
        with open(grid, newline="", encoding="utf-8") as f:
            self.assertTrue(any("arb" in r["flags"] for r in csv.DictReader(f)))

    def test_the_report_states_the_rates_the_horizon_rule_and_what_the_band_leaves_out(self):
        """AC-8: once, the rates and their source, that they hold at every
        horizon, and what is outside the band; then per date its sessions
        and every leg's days to expiry and IV, kept apart."""
        self.snapshot(expiries=[expiry("2026-11-13", fit=SKEW), expiry("2026-11-20", fit=SKEW)])
        pos = self.position([("option", "2026-11-20", 600, "C", -1, ""),
                             ("option", "2026-11-20", 600, "P", -1, "")])
        out = self.run_app(pos, "2026-11-05_1545", "--sessions", "3")
        for text in ("moderate +1.0 on a drop, -1.0 on a rally",
                     "large +2.0 on a drop, -1.5 on a rally", "measurements.md",
                     "however many sessions the move took", "against the usual way",
                     "--shift", "lowest / highest", "2026-11-10 close: 3.",
                     "days to expiry, IV"):
            self.assertIn(text, out)
        self.assertGreaterEqual(out.count("2026-11-20 600: "), 4)   # every date block

    def test_sessions_given_with_a_path_are_refused(self):
        self.snapshot()
        pos = self.position([("option", "2026-11-20", 600, "C", 1, "")])
        path = self.root / "walk.csv"
        write_csv(path, [{"date": "2026-11-05", "spot": SPOT, "iv_shift": "",
                          "kind": "", "qty": "", "price": ""}])
        with self.assertRaises(SystemExit) as caught:
            self.run_app(pos, "2026-11-05_1545", "--path", path, "--sessions", "2")
        self.assertIn("date column", str(caught.exception.code))
        with self.assertRaises(SystemExit) as caught:
            self.run_app(pos, "2026-11-05_1545", "--sessions", "1.5")
        self.assertIn("whole numbers", str(caught.exception.code))
        self.assertFalse((self.root / "scenario").exists())

    def test_the_newest_fitted_snapshot_is_the_default(self):
        self.snapshot(started=EDT)
        self.snapshot(started=EST)
        self.assertEqual(scenario.latest(), "2026-11-05_1545")

    def test_a_spot_or_shift_that_is_not_finite_is_refused_at_every_door(self):
        """The files are checked as read, but point() is also how the chooser
        and the UI will call in: there NaN priced to NaN and an infinite spot
        crashed inside the model. A NaN in run.json falls back to spot.csv."""
        ctx = self.snapshot()
        for spot in (float("nan"), float("inf"), 0.0, -600.0, None):
            with self.assertRaises(scenario.Refused):
                scenario.point(ctx, D(2026, 11, 10), spot)
        for shift in (float("nan"), float("inf")):
            with self.assertRaises(scenario.Refused):
                scenario.point(ctx, D(2026, 11, 10), SPOT, shift)
        run = self.root / "chains" / ctx["snapshot"] / "run.json"
        info = json.loads(run.read_text(encoding="utf-8"))
        run.write_text(json.dumps(dict(info, spot_at_start="NaN")), encoding="utf-8")
        self.assertEqual(scenario.load(ctx["snapshot"])["spot"], SPOT)    # spot.csv's
        write_csv(self.root / "chains" / ctx["snapshot"] / "spot.csv",
                  [{"price": "nan", "quote_time_et": EST, "fetched_at": EST}])
        with self.assertRaises(scenario.Refused):
            scenario.load(ctx["snapshot"])

    def test_option_and_nes_quantities_are_whole_contracts(self):
        """0.5 NES priced as 2.5 shares of delta and 0.5 of an option as half a
        contract: arithmetic on a position nobody can hold. Shares may be
        fractional; brokers sell them."""
        ctx = self.snapshot()
        for row in (("nes", "", "", "", 0.5, 6000), ("option", "2026-11-20", 600, "C", 0.5, "")):
            with self.assertRaises(scenario.Refused) as caught:
                self.legs(ctx, row)
            self.assertIn("whole contracts", str(caught.exception))
        legs = self.legs(ctx, ("option", "2026-11-20", 600, "C", "2.0", ""),
                         ("nes", "", "", "", -3, 6000), ("shares", "", "", "", 2.5, ""))
        self.assertEqual(len(legs), 3)
        path = self.root / "half.csv"
        write_csv(path, [{"date": "2026-11-05", "spot": SPOT, "iv_shift": "",
                          "kind": "nes", "qty": "0.5", "price": "6000"}])
        with self.assertRaises(scenario.Refused) as caught:
            scenario.read_path(path)
        self.assertIn("whole contracts", str(caught.exception))

    def test_a_number_in_the_position_file_that_does_not_parse_is_refused(self):
        """A share fill of "60o.5" fell back to spot, and a qty of "nan" priced
        a leg at NaN."""
        ctx = self.snapshot()
        for row in (("shares", "", "", "", 10, "60o.5"),
                    ("option", "2026-11-20", "6OO", "C", 1, ""),
                    ("option", "2026-11-20", 600, "C", "nan", "")):
            with self.assertRaises(scenario.Refused) as caught:
                self.legs(ctx, row)
            self.assertIn("is not a number", str(caught.exception))

    def test_a_grid_shift_given_with_a_path_is_refused_not_dropped(self):
        """--shift is the grid's; a path's steps carry their own. Given both,
        the command used to drop the -5 without a word."""
        self.snapshot()
        pos = self.position([("option", "2026-11-20", 600, "C", 1, "")])
        path = self.root / "walk.csv"
        write_csv(path, [{"date": "2026-11-05", "spot": SPOT, "iv_shift": "",
                          "kind": "", "qty": "", "price": ""}])
        with self.assertRaises(SystemExit) as caught:
            self.run_app(pos, "2026-11-05_1545", "--path", path, "--shift", -5)
        self.assertIn("iv_shift", str(caught.exception.code))
        self.assertFalse((self.root / "scenario").exists())
        with self.assertRaises(SystemExit) as caught:
            self.run_app(pos, "2026-11-05_1545", "--shift", "nan")
        self.assertIn("not a number", str(caught.exception.code))

    def test_a_refused_position_writes_nothing(self):
        self.snapshot()
        pos = self.position([("option", "2026-11-20", 600, "C", 1, ""),
                             ("nes", "", "", "", 1, "")])
        with self.assertRaises(SystemExit) as caught, \
                contextlib.redirect_stdout(io.StringIO()):
            self.run_app(pos, "2026-11-05_1545")
        self.assertIn("fill price", str(caught.exception.code))
        self.assertFalse((self.root / "scenario").exists())

    def test_the_fixture_never_reaches_the_real_data_folder(self):
        for mod, attr in ((scenario, "CHAIN_DIR"), (scenario, "IV_DIR"),
                          (scenario, "SURFACE_DIR"), (scenario, "OUT_DIR"),
                          (term, "IV_DIR"), (term, "SURFACE_DIR"),
                          (context, "CHAIN_DIR"), (ledger, "CHAIN_DIR")):
            self.assertTrue(str(getattr(mod, attr)).startswith(str(self.root)), attr)


class TestSavedResults(AppBase):
    """Every saved row says what it was priced from (`inputs`), and a folder
    never holds results from two positions, or from two versions of the
    snapshot's data. A grid and a path of the same position on the same data
    stay side by side, whatever the shift or the steps."""

    SNAP = "2026-11-05_1545"
    CALL = [("option", "2026-11-20", 600, "C", 1, "")]
    PUTS = [("option", "2026-11-20", 600, "P", -3, "")]

    def setUp(self):
        super().setUp()
        self.snapshot()
        self.dest = self.root / "scenario" / self.SNAP / "pos"

    def walk(self, name="walk", spot=610.0):
        path = self.root / f"{name}.csv"
        write_csv(path, [{"date": "2026-11-05", "spot": SPOT, "iv_shift": "", "kind": "",
                          "qty": "", "price": ""},
                         {"date": "2026-11-10", "spot": spot, "iv_shift": "", "kind": "",
                          "qty": "", "price": ""}])
        return path

    def files(self):
        return sorted(p.name for p in self.dest.iterdir())

    def read(self, name):
        with open(self.dest / name, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def stamps(self):
        return {name: {r["inputs"] for r in self.read(name)} for name in self.files()}

    def test_a_grid_from_a_changed_position_removes_the_old_path(self):
        """Codex's case: a path for a long call, the file rewritten as three
        short puts, then a grid. The call's path.csv used to stay behind."""
        self.run_app(self.position(self.CALL), self.SNAP, "--path", self.walk())
        out = self.run_app(self.position(self.PUTS), self.SNAP)
        self.assertEqual(self.files(), ["grid.csv", "legs.csv"])
        self.assertIn("removed path.csv", out)
        self.assertEqual([r["leg"] for r in self.read("legs.csv")], ["-3 2026-11-20 600P"])

    def test_a_path_from_a_changed_position_removes_the_old_grid(self):
        self.run_app(self.position(self.CALL), self.SNAP)
        out = self.run_app(self.position(self.PUTS), self.SNAP, "--path", self.walk())
        self.assertEqual(self.files(), ["legs.csv", "path.csv"])
        self.assertIn("removed grid.csv", out)

    def test_a_path_and_a_grid_from_identical_inputs_both_survive_in_either_order(self):
        pos = self.position(self.CALL)
        for first, second in ((("--path", self.walk()), ()), ((), ("--path", self.walk()))):
            self.run_app(pos, self.SNAP, *first)
            out = self.run_app(pos, self.SNAP, *second)
            self.assertEqual(self.files(), ["grid.csv", "legs.csv", "path.csv"])
            self.assertNotIn("removed", out)
            stamps = set().union(*self.stamps().values())
            self.assertEqual(len(stamps), 1)
            self.assertRegex(stamps.pop(), r"^[0-9a-f]{12}$")

    def test_rerunning_the_grid_at_another_iv_shift_keeps_the_path(self):
        pos = self.position(self.CALL)
        self.run_app(pos, self.SNAP, "--path", self.walk())
        self.run_app(pos, self.SNAP)
        self.run_app(pos, self.SNAP, "--shift", -3)
        self.assertEqual(self.files(), ["grid.csv", "legs.csv", "path.csv"])
        self.assertEqual({r["iv_shift"] for r in self.read("grid.csv")}, {"-3.0"})

    def test_a_new_path_file_keeps_the_grid(self):
        pos = self.position(self.CALL)
        self.run_app(pos, self.SNAP)
        self.run_app(pos, self.SNAP, "--path", self.walk("first", 610.0))
        self.run_app(pos, self.SNAP, "--path", self.walk("second", 620.0))
        self.assertEqual(self.files(), ["grid.csv", "legs.csv", "path.csv"])
        self.assertEqual(self.read("path.csv")[-1]["spot"], "620.0")

    def test_re_derived_snapshot_data_removes_the_old_result(self):
        """Same position, but `iv` was re-run in between: the old grid priced
        legs that are now worth something else."""
        pos = self.position(self.CALL)
        self.run_app(pos, self.SNAP)
        contracts = self.root / "iv" / self.SNAP / "contracts.csv"
        with open(contracts, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows[0]["iv"] = str(float(rows[0]["iv"]) + 0.001)
        write_csv(contracts, rows)
        out = self.run_app(pos, self.SNAP, "--path", self.walk())
        self.assertEqual(self.files(), ["legs.csv", "path.csv"])
        self.assertIn("removed grid.csv", out)

    def test_a_comment_a_blank_row_or_600_written_600_0_is_the_same_position(self):
        self.run_app(self.position(self.CALL), self.SNAP, "--path", self.walk())
        same = self.position([("option", "2026-11-20", "600.0", "C", "1", ""),
                              ("", "", "", "", "", ""),
                              ("# option", "2026-11-20", 600, "P", 1, "")])
        self.run_app(same, self.SNAP)
        self.assertEqual(self.files(), ["grid.csv", "legs.csv", "path.csv"])

    def test_a_refused_run_removes_nothing(self):
        pos = self.position(self.CALL)
        self.run_app(pos, self.SNAP)
        before = self.stamps()
        bad = self.position([("option", "2026-11-20", 600, "C", 1, ""),
                             ("nes", "", "", "", 1, "")])
        with self.assertRaises(SystemExit):
            self.run_app(bad, self.SNAP, "--path", self.walk())
        self.assertEqual(self.stamps(), before)

    def leftovers(self):
        """Anything beside the results folder, and the work area if a save
        left it behind."""
        found = [p.name for p in self.dest.parent.iterdir() if p.name != "pos"]
        if (self.root / "scenario" / scenario.WORK).exists():
            found.append(scenario.WORK)
        return sorted(found)

    def bump_ivs(self, by):
        """`iv` re-run on the snapshot, giving every strike another IV."""
        contracts = self.root / "iv" / self.SNAP / "contracts.csv"
        with open(contracts, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            r["iv"] = str(float(r["iv"]) + by)
        write_csv(contracts, rows)

    def labels(self, name="legs.csv"):
        return sorted({r["leg"] for r in self.read(name)} - {"total"})

    def test_a_result_open_elsewhere_stops_the_save_and_keeps_the_last_good_set(self):
        """A CSV open in a spreadsheet locks it on Windows. Writing file by file
        put the new legs beside the old grid and died with a traceback; now
        the folder cannot be swapped while a file in it is open, so nothing
        moves and the command says why."""
        self.run_app(self.position(self.CALL), self.SNAP)
        before = self.stamps()
        held = open(self.dest / "grid.csv", encoding="utf-8")
        try:
            with self.assertRaises(SystemExit) as caught:
                self.run_app(self.position(self.PUTS), self.SNAP)
        finally:
            held.close()
        self.assertIn("open elsewhere", str(caught.exception.code))
        self.assertEqual(self.stamps(), before)
        self.assertEqual(self.labels(), ["+1 2026-11-20 600C"])
        self.assertEqual(self.leftovers(), [])

    def test_a_save_that_fails_partway_keeps_the_last_good_set(self):
        self.run_app(self.position(self.CALL), self.SNAP)
        before = self.stamps()
        real, calls = scenario.write_csv, []

        def second_write_fails(path, rows, cols):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
            real(path, rows, cols)
        scenario.write_csv = second_write_fails
        self.addCleanup(setattr, scenario, "write_csv", real)
        with self.assertRaises(SystemExit) as caught:
            self.run_app(self.position(self.PUTS), self.SNAP)
        self.assertIn("last good set", str(caught.exception.code))
        self.assertEqual(self.stamps(), before)
        self.assertEqual(self.leftovers(), [])

    def test_a_run_stopped_mid_swap_gets_its_last_good_set_back(self):
        """Killed after moving the good set aside and before the new one went
        in: the next run, even a refused one, puts the good set back."""
        self.run_app(self.position(self.CALL), self.SNAP)
        before = self.stamps()
        half, old = scenario.work_area(self.dest)
        old.parent.mkdir(parents=True)
        self.dest.rename(old)
        half.mkdir()
        (half / "legs.csv").write_text("half a file", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_app(self.position([("nes", "", "", "", 1, "")]), self.SNAP)
        self.assertEqual(self.stamps(), before)
        self.assertEqual(self.leftovers(), [])

    def test_a_swap_that_finished_but_left_its_old_folder_is_tidied(self):
        self.run_app(self.position(self.CALL), self.SNAP)
        stale = scenario.work_area(self.dest)[1]
        stale.mkdir(parents=True)
        (stale / "grid.csv").write_text("an older set", encoding="utf-8")
        self.run_app(self.position(self.CALL), self.SNAP, "--path", self.walk())
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.files(), ["grid.csv", "legs.csv", "path.csv"])

    def test_a_position_named_like_a_save_leftover_keeps_its_own_results(self):
        """Codex's case: pos.old.csv saves its results in `pos.old`, which is
        where pos.csv's save used to park its last good set, so running
        pos.csv deleted them as its own leftover, or, before pos.csv had any
        results, took them over as an interrupted save. Even a refused run
        did. pos.writing.csv likewise. Saves now stage in the work area."""
        for name in ("pos.old", "pos.writing"):
            self.run_app(self.position(self.PUTS, name), self.SNAP)

        def neighbours():
            return {name: sorted((p.name, p.read_bytes())
                                 for p in self.dest.with_name(name).iterdir())
                    for name in ("pos.old", "pos.writing")
                    if self.dest.with_name(name).exists()}
        before = neighbours()
        self.assertEqual(sorted(before), ["pos.old", "pos.writing"])
        pos = self.position(self.CALL)
        self.run_app(pos, self.SNAP)                       # pos.csv's first run
        self.assertEqual(neighbours(), before)
        self.run_app(pos, self.SNAP, "--path", self.walk())
        self.assertEqual(neighbours(), before)
        with self.assertRaises(SystemExit):
            self.run_app(self.position([("nes", "", "", "", 1, "")]), self.SNAP)
        self.assertEqual(neighbours(), before)
        self.assertEqual(self.labels(), ["+1 2026-11-20 600C"])
        self.assertEqual(self.leftovers(), ["pos.old", "pos.writing"])

    def test_a_snapshot_named_like_the_work_area_is_refused(self):
        """The one name that could reach the work area: a snapshot folder
        called `.work`, which the collector never makes."""
        with self.assertRaises(scenario.Refused):
            scenario.run(self.position(self.CALL), scenario.WORK)

    def test_a_result_keeps_the_fingerprint_of_the_data_it_was_priced_from(self):
        """Codex's case: `iv` re-run after a grid was priced and before it was
        hashed. The grid took the new data's fingerprint and stayed beside a
        path priced on the new data ($632.64 and $874.73 at the start, one
        `inputs`). Now it keeps the data it read, and the path removes it."""
        pos = self.position(self.CALL)
        self.run_app(pos, self.SNAP)
        read_from = {r["inputs"] for r in self.read("grid.csv")}
        real = scenario.grid

        def priced_then_iv_rerun(*a, **k):
            out = real(*a, **k)
            self.bump_ivs(0.05)
            return out
        scenario.grid = priced_then_iv_rerun
        self.addCleanup(setattr, scenario, "grid", real)
        self.run_app(pos, self.SNAP)
        scenario.grid = real
        self.assertEqual({r["inputs"] for r in self.read("grid.csv")}, read_from)
        out = self.run_app(pos, self.SNAP, "--path", self.walk())
        self.assertIn("removed grid.csv", out)
        self.assertEqual(self.files(), ["legs.csv", "path.csv"])
        self.assertNotEqual({r["inputs"] for r in self.read("path.csv")}, read_from)

    def test_data_that_changes_while_it_is_read_is_refused_and_nothing_moves(self):
        """load() reads some files twice, directly and through term.load and
        context, and the fingerprint read them a third time after pricing.
        Data that changes in between is refused, and the last good set
        stays."""
        pos = self.position(self.CALL)
        self.run_app(pos, self.SNAP)
        before = self.stamps()
        real = term.load

        def iv_rerun_midway(snapshot):
            self.bump_ivs(0.05)
            return real(snapshot)
        term.load = iv_rerun_midway
        self.addCleanup(setattr, term, "load", real)
        with self.assertRaises(SystemExit) as caught:
            self.run_app(pos, self.SNAP, "--path", self.walk())
        self.assertIn("changed while it was being read", str(caught.exception.code))
        self.assertEqual(self.stamps(), before)
        self.assertEqual(self.files(), ["grid.csv", "legs.csv"])
        self.assertEqual(self.leftovers(), [])

    def test_a_run_that_overlaps_another_is_refused_and_the_first_saves_whole(self):
        """Codex's case: two runs of one position name on one snapshot at once
        shared a work folder. The first wrote its legs, the second cleared the
        folder and wrote its own legs there, then the first wrote its grid
        and published: the short puts' legs beside the long call's grid. Now
        the second is refused before it touches anything."""
        call, puts = self.root / "a" / "pos.csv", self.root / "b" / "pos.csv"
        for path, rows in ((call, self.CALL), (puts, self.PUTS)):
            write_csv(path, [dict(zip(POS_COLS, r)) for r in rows])
        first_mid_save, second_done = threading.Event(), threading.Event()
        real, outcome = scenario.write_csv, {}

        def paced(path, rows, cols):
            if threading.current_thread().name == "first" and path.name == "grid.csv":
                first_mid_save.set()
                second_done.wait(5)
            real(path, rows, cols)
        scenario.write_csv = paced
        self.addCleanup(setattr, scenario, "write_csv", real)

        def go(name, pos):
            try:
                scenario.run(pos, self.SNAP)
                outcome[name] = "saved"
            except scenario.Refused as e:
                outcome[name] = str(e)
            finally:
                if name == "second":
                    second_done.set()
        first = threading.Thread(target=go, args=("first", call), name="first")
        second = threading.Thread(target=go, args=("second", puts), name="second")
        first.start()
        self.assertTrue(first_mid_save.wait(5))
        second.start()
        second.join(10)
        first.join(10)
        self.assertEqual(outcome["first"], "saved")
        self.assertIn("another run is saving", outcome["second"])
        self.assertEqual(self.labels("legs.csv"), ["+1 2026-11-20 600C"])
        self.assertEqual(self.labels("grid.csv"), ["+1 2026-11-20 600C"])
        self.assertEqual(len(set().union(*self.stamps().values())), 1)
        self.assertEqual(self.leftovers(), [])

    def test_a_run_while_the_lock_is_held_is_refused_and_moves_nothing(self):
        self.run_app(self.position(self.CALL), self.SNAP)
        before = self.stamps()
        with scenario.held(self.dest):
            with self.assertRaises(SystemExit) as caught:
                self.run_app(self.position(self.PUTS), self.SNAP)
            self.assertIn("another run is saving", str(caught.exception.code))
            self.assertEqual(self.stamps(), before)
            # Another position, or this one on another snapshot, is not held up.
            self.run_app(self.position(self.PUTS, "other"), self.SNAP)
        self.assertEqual(self.stamps(), before)
        self.assertEqual(self.leftovers(), ["other"])

    def test_a_lock_left_by_a_run_that_died_does_not_block_the_next(self):
        """The system drops a lock when its holder ends; the file can stay."""
        lock = scenario.work_area(self.dest)[0].parent / "lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("", encoding="utf-8")
        self.run_app(self.position(self.CALL), self.SNAP)
        self.assertEqual(self.files(), ["grid.csv", "legs.csv"])
        self.assertEqual(self.leftovers(), [])

    def test_failed_saves_never_mix_two_positions(self):
        """The owner's ask: whatever fails, a folder holds one position. A and
        all its scenarios, or B and its own, never parts of each."""
        call = self.position(self.CALL)
        self.run_app(call, self.SNAP)
        self.run_app(call, self.SNAP, "--path", self.walk())
        held = open(self.dest / "path.csv", encoding="utf-8")
        try:
            with self.assertRaises(SystemExit):
                self.run_app(self.position(self.PUTS), self.SNAP)
        finally:
            held.close()
        self.assertEqual(len(set().union(*self.stamps().values())), 1)
        self.assertEqual(self.labels(), ["+1 2026-11-20 600C"])
        self.assertEqual(self.files(), ["grid.csv", "legs.csv", "path.csv"])
        self.run_app(self.position(self.PUTS), self.SNAP)
        self.assertEqual(len(set().union(*self.stamps().values())), 1)
        self.assertEqual(self.labels(), ["-3 2026-11-20 600P"])
        self.assertEqual(self.files(), ["grid.csv", "legs.csv"])

    def test_each_run_gets_its_own_report_id_and_shares_the_position_id(self):
        """A grid at another shift, or another path, prices differently, so it
        is a different report of the same position: `inputs` groups, `report`
        tells them apart. The same run twice is the same report."""
        pos = self.position(self.CALL)

        def ids(name):
            rows = self.read(name)
            return {r["inputs"] for r in rows}.pop(), {r["report"] for r in rows}.pop()
        self.run_app(pos, self.SNAP)
        flat = ids("grid.csv")
        self.run_app(pos, self.SNAP)
        self.assertEqual(ids("grid.csv"), flat)
        self.run_app(pos, self.SNAP, "--shift", -3)
        shocked = ids("grid.csv")
        self.run_app(pos, self.SNAP, "--path", self.walk("one", 610.0))
        one = ids("path.csv")
        self.run_app(pos, self.SNAP, "--path", self.walk("two", 620.0))
        two = ids("path.csv")
        self.assertEqual({flat[0], shocked[0], one[0], two[0]}, {flat[0]})
        self.assertEqual(len({flat[1], shocked[1], one[1], two[1]}), 4)

    def test_the_report_id_follows_the_rates_and_sessions_and_inputs_does_not(self):
        """AC-9: the response rates are the engine's, but they change every
        number off spot, so a grid under other rates is another report of
        the same position; so is one with other dates."""
        pos = self.position(self.CALL)

        def ids():
            rows = self.read("grid.csv")
            return {r["inputs"] for r in rows}.pop(), {r["report"] for r in rows}.pop()
        self.run_app(pos, self.SNAP)
        first = ids()
        self.run_app(pos, self.SNAP, "--sessions", "2")
        dated = ids()
        old = dict(scenario.CONFIG["response"])
        scenario.CONFIG["response"]["large"] = (3.0, -2.0)
        self.addCleanup(scenario.CONFIG.__setitem__, "response", old)
        self.run_app(pos, self.SNAP)
        rated = ids()
        self.assertEqual({first[0], dated[0], rated[0]}, {first[0]})
        self.assertEqual(len({first[1], dated[1], rated[1]}), 3)

    def test_an_option_fill_is_part_of_which_position_it_is(self):
        """Filled at 4.10 or 5.80 was the same fingerprint, the fill not even
        read. Entry stays at mid (rule 4), so the numbers agree, but they are
        two trades and one's results do not belong to the other."""
        at_410 = self.position([("option", "2026-11-20", 600, "C", 1, "4.10")])
        self.run_app(at_410, self.SNAP, "--path", self.walk())
        first = {r["inputs"] for r in self.read("legs.csv")}
        pnl = [r["pnl"] for r in self.read("path.csv")]
        self.assertEqual([r["price"] for r in self.read("legs.csv")], ["4.1"])
        out = self.run_app(self.position([("option", "2026-11-20", 600, "C", 1, "5.80")]),
                           self.SNAP)
        self.assertNotEqual({r["inputs"] for r in self.read("legs.csv")}, first)
        self.assertIn("removed path.csv", out)
        self.run_app(self.position([("option", "2026-11-20", 600, "C", 1, "5.80")]),
                     self.SNAP, "--path", self.walk())
        self.assertEqual([r["pnl"] for r in self.read("path.csv")], pnl)   # mid, either way
        with self.assertRaises(SystemExit):
            self.run_app(self.position([("option", "2026-11-20", 600, "C", 1, "-1")]),
                         self.SNAP)

    def test_a_result_saved_before_the_fingerprint_existed_is_removed(self):
        """Files from earlier builds carry no `inputs`, so nothing says they
        belong with what is written now."""
        self.dest.mkdir(parents=True)
        write_csv(self.dest / "grid.csv", [{"snapshot": self.SNAP, "leg": "total", "pnl": "0"}])
        out = self.run_app(self.position(self.CALL), self.SNAP, "--path", self.walk())
        self.assertEqual(self.files(), ["legs.csv", "path.csv"])
        self.assertIn("removed grid.csv", out)


if __name__ == "__main__":
    unittest.main()
