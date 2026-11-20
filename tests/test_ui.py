"""
Tests for screener/ui.py and screener/ui_app.py, offline.

The page draws only what the screener already stands behind, so the claim
under test is always the same: each figure on it is the number in the file
or the engine call it came from, and nothing else. The snapshots are the
engine's synthetic ones (tests/test_scenario.py: a smile with known
coefficients, in a temporary folder), with points.csv given the columns
surface.py writes and the fixture leaves out. The real data/ is never read.

The view is tested without Dash. The tests that draw or serve the page skip,
with the reason, where Dash or Plotly is not installed.

Acceptance criteria are the AC-n in docs/changes/2026-11-13-ui.md.

  python -m unittest discover tests        (from the project folder)
"""

import csv
import datetime as dt
import importlib.util
import json
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from screener import context, scenario, term, ui  # noqa: E402
from test_scenario import EDT, EST, SKEW, Base, expiry  # noqa: E402

HAVE_DASH = all(importlib.util.find_spec(m) for m in ("dash", "plotly"))
if HAVE_DASH:
    from screener import ui_app  # noqa: E402


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def complete_points(root, name, reason="band 3.37 pts"):
    """Give the fixture's points.csv the columns surface.py writes and the
    fixture leaves out: `fitted_iv` (the expiry's curve at the point's
    moneyness), `residual` (vol.py's IV less that) and `why_not`.

    `fitted_iv` is rounded to 6 places, as the real files are, so a smile
    drawn from the curve instead of from the saved column reads differently
    and a test can tell which one the view used."""
    fits = {r["expiry"]: (float(r["m"]), float(r["s"]), [float(r[f"c{i}"]) for i in range(5)])
            for r in read_csv(root / "surface" / name / "fits.csv")}
    ivs = {(r["expiry"], float(r["strike"])): float(r["iv"])
           for r in read_csv(root / "iv" / name / "contracts.csv")}
    rows = read_csv(root / "surface" / name / "points.csv")
    for r in rows:
        fit = fits.get(r["expiry"])
        fitted = scenario.curve(fit, float(r["moneyness"])) if fit else None
        iv = ivs.get((r["expiry"], float(r["strike"])))
        r["fitted_iv"] = "" if fitted is None else round(fitted, 6)
        r["residual"] = "" if fitted is None or iv is None else iv - fitted
        r["why_not"] = "" if r["readable"] == "True" else reason
    write_rows(root / "surface" / name / "points.csv", rows)


class UIBase(Base):
    def setUp(self):
        super().setUp()
        ui._cache.clear()
        self.addCleanup(ui._cache.clear)

    def chain(self, expiries=None, started=EST, **kw):
        """A snapshot as the pipeline leaves it, and its name."""
        ctx = self.snapshot(expiries, started=started, **kw)
        complete_points(self.root, ctx["snapshot"])
        return ctx["snapshot"]

    def readable_range(self, name, exp):
        """The fitted range as surface.py's points define it, worked out here
        rather than through ui or the engine: the outermost readable
        moneyness."""
        ks = [float(r["moneyness"]) for r in read_csv(self.root / "surface" / name / "points.csv")
              if r["expiry"] == exp and r["readable"] == "True"]
        return min(ks), max(ks)


NARROW = [expiry("2026-11-06"), expiry("2026-11-13", fit=SKEW, k_range=(-0.03, 0.02)),
          expiry("2026-11-20", fit=SKEW, k_range=(-0.06, 0.04))]


class TestTheSurfaceIsTheChainsOwnNumbers(UIBase):
    """AC-25: points, smiles and the surface, each from the file or the call
    it came from."""

    def test_every_iv_vol_py_read_is_a_point_with_its_band(self):
        name = self.chain()
        view = ui.chain_surface(name)
        rows = read_csv(self.root / "iv" / name / "contracts.csv")
        self.assertEqual(len(view["points"]), len(rows))
        got = {(p["expiry"], p["strike"]): p for p in view["points"]}
        for r in rows:
            p = got[(r["expiry"], float(r["strike"]))]
            self.assertEqual(p["iv"], float(r["iv"]))
            self.assertEqual((p["iv_bid"], p["iv_ask"]), (float(r["iv_bid"]), float(r["iv_ask"])))
            self.assertEqual(p["right"], r["right"])

    def test_each_expiry_sits_at_its_sessions_on_the_engines_clock(self):
        """At 15:45 a quarter hour of the 6.5-hour session is left, so the
        next day's expiry is one session and 15/390 away."""
        name = self.chain()
        ctx = scenario.load(name)
        view = ui.chain_surface(name)
        for x in view["expiries"]:
            date = ctx["expiries"][x["expiry"]]["date"]
            self.assertEqual(x["sessions"], scenario.point(ctx, date, ctx["spot"])["passed"])
        first = view["expiries"][0]
        self.assertEqual(first["expiry"], "2026-11-06")
        self.assertAlmostEqual(first["sessions"], 1 + 15 / 390, places=9)
        self.assertTrue(all(p["sessions"] == next(x["sessions"] for x in view["expiries"]
                                                  if x["expiry"] == p["expiry"])
                            for p in view["points"]))

    def test_the_fit_is_drawn_only_inside_each_expirys_fitted_range(self):
        """The standing rule: the curve is never evaluated past the strikes
        it was fitted on. Inside, the surface is the curve at ln(K/F)."""
        name = self.chain(NARROW)
        ctx = scenario.load(name)
        grid = ui.chain_surface(name)["grid"]
        self.assertEqual(grid["expiries"], ["2026-11-06", "2026-11-13", "2026-11-20"])
        seen_outside = seen_inside = 0
        for x, row in zip(grid["expiries"], grid["iv"]):
            lo, hi = self.readable_range(name, x)
            e = ctx["expiries"][x]
            for K, z in zip(grid["strikes"], row):
                k = math.log(K / e["forward"])
                if lo <= k <= hi:
                    self.assertAlmostEqual(z, scenario.curve(e["fit"], k), places=12)
                    seen_inside += 1
                else:
                    self.assertIsNone(z, f"{x} {K} is outside its fitted range")
                    seen_outside += 1
        self.assertGreater(seen_outside, 0)
        self.assertGreater(seen_inside, 0)
        for i, K in enumerate(grid["strikes"]):
            self.assertTrue(any(row[i] is not None for row in grid["iv"]),
                            f"strike {K} is inside no expiry's fitted range")

    def test_a_smile_runs_through_surface_pys_saved_fitted_iv_only_inside_its_range(self):
        name = self.chain(NARROW)
        saved = {(r["expiry"], float(r["strike"])): float(r["fitted_iv"])
                 for r in read_csv(self.root / "surface" / name / "points.csv") if r["fitted_iv"]}
        ctx = scenario.load(name)
        smiles = {s["expiry"]: s for s in ui.chain_surface(name)["smiles"]}
        s = smiles["2026-11-13"]
        lo, hi = self.readable_range(name, "2026-11-13")
        F = ctx["expiries"]["2026-11-13"]["forward"]
        for K, z in zip(s["strikes"], s["iv"]):
            self.assertTrue(lo <= math.log(K / F) <= hi)
            self.assertEqual(z, saved[("2026-11-13", K)])
        inside = [K for (x, K) in saved if x == "2026-11-13" and lo <= math.log(K / F) <= hi]
        self.assertEqual(s["strikes"], sorted(inside))

    def test_a_point_the_fit_left_out_is_kept_with_surface_pys_reason(self):
        name = self.chain(NARROW)
        out = [p for p in ui.chain_surface(name)["points"] if p["expiry"] == "2026-11-13"
               and not p["readable"]]
        self.assertTrue(out)
        self.assertTrue(all(p["why_not"] == "band 3.37 pts" for p in out))

    def test_an_expiry_with_no_fit_keeps_its_points_but_has_no_smile_or_surface_row(self):
        name = self.chain([expiry("2026-11-06"), expiry("2026-11-13", fit=None),
                           expiry("2026-11-20")])
        view = ui.chain_surface(name)
        self.assertNotIn("2026-11-13", view["grid"]["expiries"])
        self.assertNotIn("2026-11-13", [s["expiry"] for s in view["smiles"]])
        self.assertTrue(any(p["expiry"] == "2026-11-13" for p in view["points"]))
        self.assertFalse(next(x for x in view["expiries"] if x["expiry"] == "2026-11-13")["fitted"])


class TestTheStripIsTermPysOwnNumbers(UIBase):
    """AC-26: the integral and the strip, each figure term.py's or
    context.py's, on the engine's clock."""

    def expect(self, name):
        ctx = scenario.load(name)
        rows, dropped = term.load(name)
        return ctx, rows, dropped

    def test_the_integral_starts_at_zero_at_the_snapshot_and_is_term_pys_totals(self):
        """Variance swap rates set apart from the fit's flat 12% ATM, so the
        integral's two lines cannot pass for each other."""
        name = self.chain([expiry("2026-11-06", level=0.14), expiry("2026-11-09", level=0.14),
                           expiry("2026-11-13", level=0.15), expiry("2026-11-20", level=0.16)])
        ctx, rows, _ = self.expect(name)
        self.assertTrue(all(r["atm_total_var"] != r["total_var"] for r in rows))
        s = ui.chain_strip(name)
        origin = s["expiries"][0]
        self.assertTrue(origin["origin"])
        self.assertEqual((origin["sessions"], origin["total_var"]), (0.0, 0.0))
        got = {x["expiry"]: x for x in s["expiries"] if not x["origin"]}
        self.assertEqual(sorted(got), sorted(r["expiry"] for r in rows))
        for r in rows:
            x = got[r["expiry"]]
            for k in ("total_var", "total_var_error", "atm_total_var", "atm_total_var_error"):
                self.assertEqual(x[k], r[k], k)

    def test_between_expiries_the_total_is_term_pys_own_interpolation_at_every_session(self):
        name = self.chain()
        ctx, _, _ = self.expect(name)
        s = ui.chain_strip(name)
        last = max(x["sessions"] for x in s["expiries"])
        self.assertEqual([p["sessions"] for p in s["integral"]],
                         [float(n) for n in range(1, int(last) + 1)])
        for p in s["integral"]:
            self.assertEqual(p["total_var"],
                             term.constant_maturity(ctx["clock"], p["sessions"])["total_var"])

    def test_the_windows_are_context_pys_with_the_front_one_from_the_snapshot(self):
        name = self.chain()
        ctx, rows, dropped = self.expect(name)
        found, _ = context.decompose(rows, ctx["remaining"], dropped)
        windows = ui.chain_strip(name)["windows"]
        self.assertEqual(len(windows), len(found))
        for w, f in zip(windows, found):
            for k in ("from_expiry", "to_expiry", "sessions", "forward_vol",
                      "forward_vol_error", "forward_var"):
                self.assertEqual(w[k], f[k], k)
        self.assertEqual((windows[0]["from_expiry"], windows[0]["start"]), (context.SPOT, 0.0))
        for a, b in zip(windows, windows[1:]):
            self.assertEqual(a["end"], b["start"], "the strip has a gap or an overlap")
        self.assertAlmostEqual(windows[0]["end"], 1 + 15 / 390, places=9)

    def test_a_window_holding_one_session_carries_its_date(self):
        windows = ui.chain_strip(self.chain())["windows"]
        monday = next(w for w in windows if w["to_expiry"] == "2026-11-09")
        self.assertEqual(monday["session_priced"], "2026-11-09")
        week = next(w for w in windows if w["to_expiry"] == "2026-11-20")
        self.assertEqual(week["session_priced"], "")

    def test_a_negative_window_and_an_arbitrage_are_marked(self):
        name = self.chain([expiry("2026-11-06"), expiry("2026-11-13", level=0.20),
                           expiry("2026-11-20", level=0.10)])
        bad = next(w for w in ui.chain_strip(name)["windows"] if w["to_expiry"] == "2026-11-20")
        self.assertTrue(bad["negative"])
        self.assertTrue(bad["arbitrage"])
        self.assertIsNone(bad["forward_vol"])

    def test_an_expiry_the_drop_rule_left_out_is_listed_and_widens_its_window(self):
        name = self.chain([expiry("2026-11-06"), expiry("2026-11-09", edge=0.001),
                           expiry("2026-11-13"), expiry("2026-11-20")])
        s = ui.chain_strip(name)
        self.assertEqual([d["expiry"] for d in s["dropped"]], ["2026-11-09"])
        self.assertEqual(s["dropped"][0]["edge"], 0.001)
        wide = next(w for w in s["windows"] if w["to_expiry"] == "2026-11-13")
        self.assertEqual((wide["from_expiry"], wide["spans_dropped"]), ("2026-11-06", 1))
        surface = {x["expiry"]: x["sessions"] for x in ui.chain_surface(name)["expiries"]}
        self.assertEqual(s["dropped"][0]["sessions"], surface["2026-11-09"])

    def test_the_strip_and_the_surface_place_every_expiry_at_the_same_session(self):
        name = self.chain()
        surface = {x["expiry"]: x["sessions"] for x in ui.chain_surface(name)["expiries"]}
        for x in ui.chain_strip(name)["expiries"]:
            if not x["origin"]:
                self.assertEqual(x["sessions"], surface[x["expiry"]], x["expiry"])

    def test_the_strips_fixed_axes_reach_the_top_of_every_error_bar(self):
        """The fixture's variance swap rates carry no error, which would let
        an axis that stops at the values pass; so these are given one."""
        a = self.chain(started=EDT)
        b = self.chain([expiry("2026-11-06", level=0.25), expiry("2026-11-13"),
                        expiry("2026-11-20")], started=EST)
        for name in (a, b):
            path = self.root / "iv" / name / "expiries.csv"
            rows = read_csv(path)
            for r in rows:
                r["vs_error"] = 0.004
            write_rows(path, rows)
        ui._cache.clear()
        self.assertTrue(all(x["total_var_error"] > 0 for x in ui.chain_strip(b)["expiries"]
                            if not x["origin"]))
        ranges = ui.axis_ranges([a, b])
        for name in (a, b):
            s = ui.chain_strip(name)
            for x in s["expiries"]:
                self.assertLessEqual(x["total_var"] + x["total_var_error"], ranges["total_var"][1])
            for w in s["windows"]:
                if w["forward_vol"] is not None:
                    self.assertLessEqual(w["forward_vol"] + w["forward_vol_error"],
                                         ranges["forward_vol"][1])


LEFT_OUT = [expiry("2026-11-06"), expiry("2026-11-09", edge=0.001), expiry("2026-11-13"),
            expiry("2026-11-20", edge=0.001)]
FALLBACK = [expiry("2026-11-06", edge=0.001), expiry("2026-11-09", edge=0.001),
            expiry("2026-11-13"), expiry("2026-11-20", edge=0.001)]


class TestTheHighlightIsTheViewsOwnReading(UIBase):
    """AC-27 and AC-31 to AC-33: every highlight is prepared in the view, from
    term.py's and context.py's numbers, for each place a hover can land. In
    the default chain, snapped at 15:45, the expiries sit 1.04 (11-06), 2.04
    (11-09), 6.04 (11-13) and 11.04 (11-20) sessions out."""

    def focus(self, strip, sessions=None, expiry=None):
        if expiry:
            return strip["foci"][strip["focus_by_expiry"][expiry]]
        return next(f for f in strip["foci"] if f["kind"] == "session" and f["sessions"] == sessions)

    def ends(self, strip, f):
        w = strip["windows"][f["window"]]
        return w["from_expiry"], w["to_expiry"]

    def with_quote_errors(self, name):
        """The fixture's variance swap rates carry no error; give them one,
        so an error that is not carried through cannot pass as zero."""
        path = self.root / "iv" / name / "expiries.csv"
        rows = read_csv(path)
        for r in rows:
            r["vs_error"] = 0.004
        write_rows(path, rows)
        ui._cache.clear()
        return name

    def test_a_session_inside_a_window_names_that_window_and_the_expiries_at_its_ends(self):
        s = ui.chain_strip(self.chain())
        self.assertEqual(self.ends(s, self.focus(s, 4.0)), ("2026-11-09", "2026-11-13"))

    def test_on_an_expirys_own_session_the_window_is_the_one_ending_there(self):
        """(start, end], as the ledger settles: at 11-13 the integral holds the
        window to 11-13 in full, and the one from 11-13 has added nothing."""
        s = ui.chain_strip(self.chain())
        f = self.focus(s, expiry="2026-11-13")
        self.assertEqual(self.ends(s, f), ("2026-11-09", "2026-11-13"))
        self.assertEqual(f["sessions"], s["windows"][f["window"]]["end"])

    def test_a_session_in_the_front_window_names_the_snapshot_and_the_first_expiry(self):
        s = ui.chain_strip(self.chain())
        f = self.focus(s, 1.0)
        self.assertEqual(self.ends(s, f), (context.SPOT, "2026-11-06"))
        self.assertEqual(s["windows"][f["window"]]["start"], 0.0)

    def test_between_expiries_the_integral_is_term_pys_straight_line_with_the_two_ends_error(self):
        name = self.with_quote_errors(self.chain())
        ctx = scenario.load(name)
        s = ui.chain_strip(name)
        between = [f for f in s["foci"] if f["kind"] == "session"]
        self.assertTrue(between)
        for f in between:
            cm = term.constant_maturity(ctx["clock"], f["sessions"])
            self.assertEqual((f["total_var"], f["total_var_error"]),
                             (cm["total_var"], cm["total_var_error"]))
            self.assertFalse(f["at_expiry"])
            self.assertGreater(f["total_var_error"], 0.0)

    def test_at_an_expiry_the_integral_is_its_stripped_total_with_its_own_error(self):
        name = self.with_quote_errors(self.chain())
        s = ui.chain_strip(name)
        for x in s["expiries"]:
            if x["origin"]:
                continue
            f = self.focus(s, expiry=x["expiry"])
            self.assertEqual((f["kind"], f["at_expiry"]), ("expiry", True))
            self.assertEqual((f["total_var"], f["total_var_error"]),
                             (x["total_var"], x["total_var_error"]))

    def test_an_expiry_left_out_has_no_integral_reading_and_names_the_window_standing_in_for_it(self):
        s = ui.chain_strip(self.chain(LEFT_OUT))
        f = self.focus(s, expiry="2026-11-09")
        self.assertEqual(f["kind"], "outside")
        self.assertIsNone(f["total_var"])
        self.assertIsNone(f["total_var_error"])
        self.assertIn("A-015", f["reason"])
        self.assertEqual(self.ends(s, f), ("2026-11-06", "2026-11-13"))
        self.assertEqual(s["windows"][f["window"]]["left_out"], ["2026-11-09"])
        # The sessions that window holds are drawn as a split nobody knows.
        self.assertEqual([p["sessions"] for p in s["integral"] if p["widened"]],
                         [2.0, 3.0, 4.0, 5.0, 6.0])

    def test_past_the_last_kept_expiry_no_window_is_named(self):
        s = ui.chain_strip(self.chain(LEFT_OUT))
        f = self.focus(s, expiry="2026-11-20")
        self.assertEqual(f["kind"], "outside")
        self.assertIsNone(f["window"])
        self.assertEqual(max(p["sessions"] for p in s["integral"]), 6.0,
                         "the integral stops at the last expiry it kept")

    def test_an_expiry_dropped_before_the_first_kept_one_widens_the_window_from_the_snapshot(self):
        """AC-31 on the page. On 2026-11-19_1539 the 11-20 expiry was dropped
        and 11-23 kept first, and the window from the snapshot read as sound."""
        s = ui.chain_strip(self.chain([expiry("2026-11-06", edge=0.001), expiry("2026-11-09"),
                                       expiry("2026-11-13"), expiry("2026-11-20")]))
        front = s["windows"][0]
        self.assertEqual((front["from_expiry"], front["to_expiry"]), (context.SPOT, "2026-11-09"))
        self.assertEqual((front["spans_dropped"], front["left_out"]), (1, ["2026-11-06"]))
        self.assertEqual(self.focus(s, expiry="2026-11-06")["window"], 0)
        self.assertTrue(next(p for p in s["integral"] if p["sessions"] == 1.0)["widened"])

    def test_after_the_close_a_session_on_an_expiry_reads_that_expirys_own_total(self):
        """At 16:33 nothing of the session is left, so every expiry sits on a
        whole session, as on 2026-11-05_1633 and 2026-11-20_1629. There the
        total is the expiry's stripped one, not a point on a line, and is not
        marked unknown even when the window before it is widened."""
        name = self.chain(LEFT_OUT, started="2026-11-05T16:33:00-05:00")
        s = ui.chain_strip(name)
        on = next(x for x in s["expiries"] if x["expiry"] == "2026-11-13")
        self.assertEqual(on["sessions"], 6.0)
        p = next(p for p in s["integral"] if p["sessions"] == 6.0)
        self.assertTrue(p["at_expiry"])
        self.assertFalse(p["widened"])
        f = s["foci"][p["key"]]
        self.assertTrue(f["at_expiry"])
        self.assertEqual((f["total_var"], f["total_var_error"]),
                         (on["total_var"], on["total_var_error"]))
        self.assertTrue(next(p for p in s["integral"] if p["sessions"] == 5.0)["widened"])

    def test_every_window_names_exactly_the_expiries_term_py_counts_as_left_out_inside_it(self):
        for chain in (LEFT_OUT, FALLBACK, None,
                      [expiry("2026-11-06", edge=0.001), expiry("2026-11-09", edge=0.001),
                       expiry("2026-11-13"), expiry("2026-11-20")]):
            s = ui.chain_strip(self.chain(chain))
            for w in s["windows"]:
                self.assertEqual(len(w["left_out"]), w["spans_dropped"],
                                 (w["from_expiry"], w["to_expiry"]))
            ui._cache.clear()

    def test_every_whole_session_and_every_expiry_on_the_surface_has_a_highlight(self):
        name = self.chain([expiry("2026-11-06"), expiry("2026-11-09"),
                           expiry("2026-11-13", fit=None), expiry("2026-11-20")])
        s, v = ui.chain_strip(name), ui.chain_surface(name)
        self.assertEqual(sorted(s["focus_by_expiry"]), sorted(x["expiry"] for x in v["expiries"]))
        self.assertEqual([f["key"] for f in s["foci"]], list(range(len(s["foci"]))))
        for p in s["integral"]:
            self.assertEqual(s["foci"][p["key"]]["sessions"], p["sessions"])
        unfitted = self.focus(s, expiry="2026-11-13")
        self.assertEqual(unfitted["kind"], "outside")
        self.assertIn("no fit", unfitted["reason"])

    def test_the_strip_says_where_its_totals_come_from(self):
        """AC-32: term.py's one source per snapshot, the variance swap rate
        where two expiries can carry one, else every expiry's ATM level."""
        self.assertEqual(ui.chain_strip(self.chain())["source"], "vs")
        self.assertEqual(ui.chain_strip(self.chain(FALLBACK, started=EDT))["source"], "atm")


class TestSnapshots(UIBase):
    """AC-24's stepping half, AC-12's warnings, and the refusals."""

    def test_the_collector_warnings_are_shown_word_for_word(self):
        name = self.chain()
        path = self.root / "chains" / name / "run.json"
        run = json.loads(path.read_text(encoding="utf-8"))
        run["warnings"] = ["market closed at Thu 16:33 ET: bid/ask are stale",
                           "median quote is 21 min old: quotes look stale"]
        path.write_text(json.dumps(run), encoding="utf-8")
        view = ui.chain_surface(name)
        self.assertEqual(view["warnings"], run["warnings"])
        self.assertIsNone(view["warnings_note"])

    def test_no_warnings_and_no_run_json_are_each_said_in_words(self):
        name = self.chain()
        self.assertEqual(ui.chain_surface(name)["warnings_note"], "none")
        (self.root / "chains" / name / "run.json").unlink()
        warnings, note = ui.run_warnings(name)
        self.assertEqual(warnings, [])
        self.assertIn("no run.json", note)

    def test_a_snapshot_the_engine_refuses_shows_its_reasons_instead_of_a_surface(self):
        name = self.chain()
        (self.root / "chains" / name / "run.json").write_text(
            json.dumps({"started_et": EST, "spot_at_start": "NaN"}), encoding="utf-8")
        write_rows(self.root / "chains" / name / "spot.csv",
                   [{"price": "nan", "quote_time_et": EST, "fetched_at": EST}])
        view = ui.chain_surface(name)
        self.assertNotIn("points", view)
        self.assertTrue(any("no usable spot" in r for r in view["refused"]))

    def test_data_that_changes_while_it_is_read_is_refused_not_drawn(self):
        name = self.chain()
        real = scenario.load

        def load_then_rewrite(snapshot):
            ctx = real(snapshot)
            with open(self.root / "iv" / snapshot / "contracts.csv", "a", encoding="utf-8") as f:
                f.write("\n")
            return ctx

        scenario.load = load_then_rewrite
        self.addCleanup(setattr, scenario, "load", real)
        view = ui.chain_surface(name)
        self.assertTrue(any("changed while it was being read" in r for r in view["refused"]))

    def test_a_snapshot_rewritten_since_it_was_read_is_read_again(self):
        name = self.chain()
        before = {(p["expiry"], p["strike"]): p["iv"] for p in ui.chain_surface(name)["points"]}
        path = self.root / "iv" / name / "contracts.csv"
        rows = read_csv(path)
        rows[0]["iv"] = float(rows[0]["iv"]) + 0.01
        write_rows(path, rows)
        after = {(p["expiry"], p["strike"]): p["iv"] for p in ui.chain_surface(name)["points"]}
        key = (rows[0]["expiry"], float(rows[0]["strike"]))
        self.assertAlmostEqual(after[key], before[key] + 0.01, places=12)

    def test_each_snapshot_in_the_list_is_drawn_from_its_own_files(self):
        """Stepping: two snapshots at different spots give two surfaces, each
        its own file's numbers."""
        a = self.chain(started=EDT, spot=600.0)
        b = self.chain(started=EST, spot=620.0)
        self.assertEqual(ui.snapshots(), [a, b])
        for name in (a, b):
            view = ui.chain_surface(name)
            rows = read_csv(self.root / "iv" / name / "contracts.csv")
            self.assertEqual(sorted(p["iv"] for p in view["points"]),
                             sorted(float(r["iv"]) for r in rows))
        self.assertNotEqual(ui.chain_surface(a)["spot"], ui.chain_surface(b)["spot"])

    def test_fixed_axes_cover_every_snapshots_fit_and_used_ivs_but_not_a_far_wing_left_out(self):
        a = self.chain(NARROW, started=EDT, spot=600.0)
        b = self.chain(NARROW, started=EST, spot=620.0,
                       residuals={("2026-11-13", 540.0): 0.6})     # a wild wing quote
        ranges = ui.axis_ranges([a, b])
        for name in (a, b):
            view = ui.chain_surface(name)
            for z in (z for row in view["grid"]["iv"] for z in row if z is not None):
                self.assertTrue(ranges["iv"][0] <= z <= ranges["iv"][1])
            for p in view["points"]:
                if p["readable"]:
                    self.assertTrue(ranges["strike"][0] <= p["strike"] <= ranges["strike"][1])
                    self.assertTrue(ranges["iv"][0] <= p["iv_bid"] and p["iv_ask"] <= ranges["iv"][1])
            self.assertLessEqual(max(x["sessions"] for x in view["expiries"]), ranges["sessions"][1])
        wild = next(p for p in ui.chain_surface(b)["points"]
                    if (p["expiry"], p["strike"]) == ("2026-11-13", 540.0))
        self.assertFalse(wild["readable"])
        self.assertGreater(wild["iv"], ranges["iv"][1])

    def test_the_page_reads_through_the_engines_folders_only(self):
        """The fixture moves the engine's folders; the view has none of its
        own, so it cannot reach the real data/ around them."""
        self.assertFalse([n for n in vars(ui) if n.endswith("_DIR")])
        for attr in ("CHAIN_DIR", "IV_DIR", "SURFACE_DIR"):
            self.assertTrue(str(getattr(scenario, attr)).startswith(str(self.root)), attr)


class TestWithoutDash(unittest.TestCase):
    """AC-22: Dash and Plotly are the page's alone. Every other command runs
    on a machine without them, and `ui` says how to install them."""

    def test_app_py_loads_and_the_page_says_how_to_install_dash_when_it_is_missing(self):
        # The child stops at cmd_ui's import check, before any snapshot is
        # listed or read, so it never reaches data/.
        code = ("import sys\n"
                "for m in ('dash', 'plotly'):\n"
                "    sys.modules[m] = None\n"          # import of either now fails
                "sys.modules.pop('screener.ui_app', None)\n"
                "import app\n"
                "from screener import ui\n"
                "try:\n"
                "    ui.cmd_ui(browser=False)\n"
                "except SystemExit as e:\n"
                "    print('EXIT', e)\n")
        import subprocess
        root = pathlib.Path(__file__).resolve().parents[1]
        out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True,
                             text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("EXIT The page needs Dash and Plotly", out.stdout)
        self.assertIn("pip install -r requirements.txt", out.stdout)


@unittest.skipUnless(HAVE_DASH, "Dash and Plotly are not installed")
class TestTheDrawing(UIBase):
    """The figure carries the view's numbers and nothing else, and the page
    is served by its own Dash app."""

    def trace(self, fig, name):
        return next(t for t in fig["data"] if t["name"] == name)

    def test_the_figure_draws_exactly_the_views_numbers(self):
        name = self.chain(NARROW)
        view = ui.chain_surface(name)
        fig = ui_app.surface_figure(view, ui.axis_ranges([name]), contours=True)
        s = self.trace(fig, ui_app.NAMES["surface"])
        self.assertEqual([list(r) for r in s["z"]], view["grid"]["iv"])
        self.assertEqual(list(s["x"]), view["grid"]["strikes"])
        self.assertEqual(list(s["y"]), view["grid"]["sessions"])
        # One hover label per cell, naming the row's expiry; none where the
        # fit is not drawn.
        self.assertEqual(len(s["text"]), len(view["grid"]["expiries"]))
        for x, row, labels in zip(view["grid"]["expiries"], view["grid"]["iv"], s["text"]):
            self.assertEqual(len(labels), len(row))
            for z, label in zip(row, labels):
                self.assertEqual(label.startswith(f"{x} (fit)"), z is not None)
        used = [p for p in view["points"] if p["readable"]]
        pts = self.trace(fig, ui_app.NAMES["points"])
        self.assertEqual(list(pts["z"]), [p["iv"] for p in used])
        band = self.trace(fig, ui_app.NAMES["bands"])
        self.assertEqual(list(band["z"]), [z for p in used for z in (p["iv_bid"], p["iv_ask"], None)])
        out = self.trace(fig, ui_app.NAMES["left_out"])
        self.assertEqual(len(out["z"]), sum(1 for p in view["points"] if not p["readable"]))
        self.assertTrue(fig["layout"]["uirevision"])

    def test_a_step_to_another_snapshot_keeps_the_camera_the_user_left(self):
        """The camera Plotly reports after the user turns the surface goes
        into the next snapshot's figure; with no turn yet, the first view."""
        a = self.chain(started=EDT)
        b = self.chain(started=EST)
        turned = {"eye": {"x": -1.4, "y": -1.4, "z": 1.1}, "up": {"x": 0, "y": 0, "z": 1},
                  "center": {"x": 0, "y": 0, "z": 0}}
        camera = ui_app.camera_from({"scene.camera": turned})
        fig, _, _, title, _ = ui_app.page_for(a, ["fixed"], ui.axis_ranges([a, b]), camera)
        self.assertEqual(title, f"Snapshot {a}")
        self.assertEqual(fig["layout"]["scene"]["camera"]["eye"], turned["eye"])
        fig, _, _, _, _ = ui_app.page_for(b, ["fixed"], ui.axis_ranges([a, b]),
                                       ui_app.camera_from({"xaxis.range": [0, 1]}))
        self.assertEqual(fig["layout"]["scene"]["camera"]["eye"], ui_app.CAMERA["eye"])

    def test_the_strip_draws_exactly_the_views_numbers(self):
        name = self.chain([expiry("2026-11-06"), expiry("2026-11-09", edge=0.001),
                           expiry("2026-11-13", level=0.20), expiry("2026-11-20", level=0.10)])
        strip = ui.chain_strip(name)
        fig = ui_app.strip_figure(strip, ui.axis_ranges([name]))
        total = self.trace(fig, ui_app.STRIP_NAMES["total"])
        self.assertEqual(list(total["y"]), [x["total_var"] for x in strip["expiries"]])
        self.assertEqual(list(total["error_y"]["array"]),
                         [x["total_var_error"] for x in strip["expiries"]])
        atm = self.trace(fig, ui_app.STRIP_NAMES["atm"])
        self.assertEqual(list(atm["y"]), [x["atm_total_var"] for x in strip["expiries"]
                                          if x["atm_total_var"] is not None])
        dots = self.trace(fig, ui_app.STRIP_NAMES["sessions"])
        self.assertEqual(list(dots["y"]), [p["total_var"] for p in strip["integral"]])
        priced = [w for w in strip["windows"] if w["forward_vol"] is not None]
        mids = self.trace(fig, ui_app.STRIP_NAMES["mids"])
        self.assertEqual(list(mids["y"]), [w["forward_vol"] for w in priced])
        self.assertEqual(list(mids["error_y"]["array"]), [w["forward_vol_error"] for w in priced])
        # A window widened by expiries left out is drawn dashed, and only
        # dashed: the solid steps are exactly the sound windows.
        def steps(windows):
            return [v for w in windows for v in (w["forward_vol"], w["forward_vol"], None)]
        solid = self.trace(fig, ui_app.STRIP_NAMES["steps"])
        wide = self.trace(fig, ui_app.STRIP_NAMES["widened"])
        self.assertEqual(list(solid["y"]), steps([w for w in priced if not w["spans_dropped"]]))
        self.assertEqual(list(wide["y"]), steps([w for w in priced if w["spans_dropped"]]))
        self.assertTrue(any(w["spans_dropped"] for w in priced))
        bad = self.trace(fig, ui_app.STRIP_NAMES["negative"])
        self.assertEqual(len(bad["x"]), sum(1 for w in strip["windows"] if w["negative"]))
        self.assertEqual(list(bad["marker"]["color"]), [ui_app.CRITICAL])
        left = self.trace(fig, ui_app.STRIP_NAMES["dropped"])
        self.assertEqual(list(left["x"]), [d["sessions"] for d in strip["dropped"]])
        # The dots carry term.py's error, and a dot inside a widened window
        # is hollow: the split there is unknown.
        self.assertEqual(list(dots["error_y"]["array"]),
                         [p["total_var_error"] for p in strip["integral"]])
        self.assertEqual(list(dots["marker"]["symbol"]),
                         ["circle-open" if p["widened"] else "circle" for p in strip["integral"]])
        self.assertIn("circle-open", dots["marker"]["symbol"])

    def test_the_highlight_draws_exactly_the_focus_the_view_gave(self):
        """AC-27's drawing, as data: where each shape sits and which smiles
        the surface thickens are the view's, and nothing is read between."""
        name = self.chain()
        view, strip = ui.chain_surface(name), ui.chain_strip(name)
        ranges = ui.axis_ranges([name])
        data = ui_app.focus_data(view, strip, ranges)
        self.assertEqual(json.loads(json.dumps(data)), data, "the page keeps it as JSON")
        smiles = {s["expiry"]: s for s in view["smiles"]}

        f = next(f for f in strip["foci"] if f["kind"] == "session" and f["sessions"] == 4.0)
        w = strip["windows"][f["window"]]
        h = ui_app.highlight(data, f["key"])
        span = next(s for s in h["shapes"] if s["type"] == "rect" and s["yref"] == "paper")
        self.assertEqual((span["x0"], span["x1"]), (0.0, 4.0))
        self.assertEqual(span["label"]["text"], "time included in the total")
        box = next(s for s in h["shapes"] if s["type"] == "rect" and s["xref"] == "x2")
        self.assertEqual((box["x0"], box["x1"]), (w["start"], w["end"]))
        line = next(s for s in h["shapes"] if s["type"] == "line")
        self.assertEqual((line["x0"], line["x1"]), (4.0, 4.0))
        ring = next(s for s in h["shapes"] if s["type"] == "circle")
        self.assertEqual((ring["xanchor"], ring["yanchor"]), (4.0, f["total_var"]))
        a, b = smiles["2026-11-09"], smiles["2026-11-13"]
        self.assertEqual(h["surface"]["x"], a["strikes"] + [None] + b["strikes"] + [None])
        self.assertEqual(h["surface"]["y"], [a["sessions"]] * len(a["strikes"]) + [None]
                         + [b["sessions"]] * len(b["strikes"]) + [None])
        self.assertEqual(h["surface"]["z"], a["iv"] + [None] + b["iv"] + [None])

        # The window from the snapshot: its near end is the SPY line, exactly
        # where the figure drew it.
        fig = ui_app.surface_figure(view, ranges, keys=strip["focus_by_expiry"])
        spot = self.trace(fig, ui_app.NAMES["spot"])
        front = next(f for f in strip["foci"] if f["kind"] == "session" and f["sessions"] == 1.0)
        h = ui_app.highlight(data, front["key"])
        self.assertEqual(h["surface"]["x"][:3], list(spot["x"]) + [None])
        self.assertEqual(h["surface"]["z"][:3], list(spot["z"]) + [None])
        self.assertEqual(h["surface"]["x"][3:], smiles["2026-11-06"]["strikes"] + [None])

    def test_a_click_holds_the_highlight_until_clicked_again_or_let_go(self):
        nf = ui_app.next_focus
        self.assertEqual(nf("hover", 3, None), (3, None))
        self.assertEqual(nf("click", 3, None), (3, 3))
        self.assertEqual(nf("hover", 5, 3), (3, 3), "held: a hover moves nothing")
        self.assertEqual(nf("click", 5, 3), (5, 5), "a click elsewhere holds there instead")
        self.assertEqual(nf("click", 3, 3), (3, None), "a second click lets go")
        self.assertEqual(nf("letgo", None, 3), (3, None))
        name = self.chain()
        data = ui_app.focus_data(ui.chain_surface(name), ui.chain_strip(name), None)
        self.assertIn("Held", ui_app.highlight(data, 3, held=True)["readout"][0])
        self.assertNotIn("Held", ui_app.highlight(data, 3, held=False)["readout"][0])

    def test_a_click_on_the_surface_holds_its_expiry_until_let_go(self):
        """The page's own response to the events Dash sends, as Dash sends
        them: a surface cell arrives with only x, y, z and its trace's number
        (seen in the browser). A real 3D click is the owner's to make; the
        browser pane's synthetic clicks never reach plotly.js's 3D scene."""
        name = self.chain()
        _, _, _, _, data = ui_app.page_for(name, [], None)
        keys = ui.chain_strip(name)["focus_by_expiry"]
        y = next(f["sessions"] for f in data["foci"] if f["expiry"] == "2026-11-13")
        cell = {"points": [{"x": 600.0, "y": y, "z": 0.12, "curveNumber": data["surface_curve"]}]}

        strip, surface, readout, held, style = ui_app.respond("surface.clickData", cell, data, None)
        self.assertEqual(held, keys["2026-11-13"])
        self.assertEqual(style, ui_app.LETGO_SHOWN)
        shapes = strip.to_plotly_json()["operations"][0]["params"]["value"]
        self.assertEqual(next(s for s in shapes if s["type"] == "line")["x0"], y)

        other = {"points": [{"customdata": keys["2026-11-06"]}]}
        self.assertEqual(ui_app.respond("strip.hoverData", other, data, held),
                         (ui_app.dash.no_update,) * 5, "held: a hover moves nothing")
        *_, released, style = ui_app.respond("letgo.n_clicks", 1, data, held)
        self.assertIsNone(released)
        self.assertEqual(style, ui_app.LETGO_HIDDEN)
        *_, moved, _ = ui_app.respond("strip.hoverData", other, data, released)
        self.assertIsNone(moved)
        self.assertEqual(ui_app.respond("strip.hoverData", {"points": [{}]}, data, None),
                         (ui_app.dash.no_update,) * 5, "a point with no highlight changes nothing")

    def test_every_hover_target_carries_its_highlights_key(self):
        name = self.chain(LEFT_OUT)
        view, strip = ui.chain_surface(name), ui.chain_strip(name)
        keys = strip["focus_by_expiry"]
        fig = ui_app.surface_figure(view, None, keys=keys)
        self.assertEqual(fig["data"][0]["name"], ui_app.NAMES["highlight"])
        self.assertEqual(list(fig["data"][0]["x"]), [], "nothing is highlighted until hovered")
        smiles = self.trace(fig, ui_app.NAMES["smiles"])
        self.assertEqual(list(smiles["customdata"]),
                         [c for s in view["smiles"] for c in [keys[s["expiry"]]] * len(s["strikes"])
                          + [None]])
        pts = self.trace(fig, ui_app.NAMES["points"])
        self.assertEqual(list(pts["customdata"]),
                         [keys[p["expiry"]] for p in view["points"] if p["readable"]])
        # A surface cell's hover reaches Dash with no customdata, only x, y,
        # z and its trace's number; its row is found by its place on the
        # expiry axis, on the trace the page says is the surface.
        page, _, _, _, data = ui_app.page_for(name, [], None)
        curve = data["surface_curve"]
        self.assertEqual(page["data"][curve]["type"], "surface")
        for x, y in zip(view["grid"]["expiries"], view["grid"]["sessions"]):
            cell = {"points": [{"x": 600.0, "y": y, "z": 0.12, "curveNumber": curve}]}
            self.assertEqual(ui_app.key_from(cell, data["foci"], curve), keys[x], x)
        self.assertIsNone(ui_app.key_from({"points": [{"y": 0.5, "curveNumber": curve}]},
                                          data["foci"], curve), "between rows is no expiry")
        spot = next(i for i, t in enumerate(page["data"]) if t["name"] == ui_app.NAMES["spot"])
        far = page["data"][spot]["y"][1]
        self.assertIsNone(ui_app.key_from({"points": [{"y": far, "curveNumber": spot}]},
                                          data["foci"], curve), "the SPY line is no expiry")

        sfig = ui_app.strip_figure(strip)
        dots = self.trace(sfig, ui_app.STRIP_NAMES["sessions"])
        self.assertEqual(list(dots["customdata"]), [p["key"] for p in strip["integral"]])
        total = self.trace(sfig, ui_app.STRIP_NAMES["total"])
        self.assertEqual(list(total["customdata"]),
                         [None if x["origin"] else keys[x["expiry"]] for x in strip["expiries"]])
        left = self.trace(sfig, ui_app.STRIP_NAMES["dropped"])
        self.assertEqual(list(left["customdata"]), [keys[d["expiry"]] for d in strip["dropped"]])
        aim = self.trace(sfig, ui_app.STRIP_NAMES["targets"])
        self.assertEqual(list(aim["customdata"]),
                         [f["key"] for f in strip["foci"] if f["window"] is not None])
        self.assertEqual(aim["hoverinfo"], "none")
        for event, key in (({"points": [{"customdata": 7}]}, 7),
                           ({"points": [{"customdata": [7]}]}, 7),
                           ({"points": [{}]}, None), (None, None)):
            self.assertEqual(ui_app.key_from(event), key)

    def test_on_an_atm_fallback_the_strip_says_so_and_draws_the_total_once(self):
        """AC-32. On 2026-11-20_1629 only one expiry could carry a variance
        swap rate, so term.py used ATM levels for all twelve; the page still
        called the line a variance swap and its absent gap the wings'."""
        atm = self.chain(FALLBACK, started=EDT)
        vs = self.chain(started=EST)
        ranges = ui.axis_ranges([atm, vs])
        _, sfig, side, title, data = ui_app.page_for(atm, ["fixed"], ranges)
        names = [t["name"] for t in sfig["data"]]
        self.assertIn(ui_app.STRIP_NAMES["total_atm"], names)
        self.assertNotIn(ui_app.STRIP_NAMES["total"], names)
        self.assertNotIn(ui_app.STRIP_NAMES["atm"], names)
        self.assertIn(ui_app.ATM_TITLE, title)
        said = str(side)
        self.assertIn(ui_app.INTEGRAL_ATM, said)
        self.assertNotIn(ui_app.INTEGRAL_VS, said)
        f = data["foci"][ui.chain_strip(atm)["focus_by_expiry"]["2026-11-13"]]
        self.assertIn("ATM level", ui_app.highlight(data, f["key"])["readout"][1])

        _, sfig, side, title, _ = ui_app.page_for(vs, ["fixed"], ranges)
        names = [t["name"] for t in sfig["data"]]
        self.assertIn(ui_app.STRIP_NAMES["total"], names)
        self.assertIn(ui_app.STRIP_NAMES["atm"], names)
        self.assertEqual(title, f"Snapshot {vs}")
        self.assertIn(ui_app.INTEGRAL_VS, str(side))

    def test_the_readout_says_how_each_total_was_read(self):
        """The owner's caution on AC-33: an interpolated point must not read
        like a measured one, least of all inside a window standing in for
        expiries left out, where which day holds the variance is unknown."""
        name = self.chain(LEFT_OUT)
        strip = ui.chain_strip(name)
        data = ui_app.focus_data(ui.chain_surface(name), strip, None)
        keys = strip["focus_by_expiry"]

        def said(key):
            return " ".join(ui_app.highlight(data, key)["readout"])

        def session(s):
            return next(f["key"] for f in strip["foci"]
                        if f["kind"] == "session" and f["sessions"] == s)

        self.assertIn("stripped from its variance swap rate", said(keys["2026-11-13"]))
        inside = said(session(4.0))
        self.assertIn("straight line", inside)
        self.assertIn("not how variance spreads between them", inside)
        self.assertIn("2026-11-09", inside)
        self.assertIn("is unknown", inside)
        self.assertIn("never stripped", said(keys["2026-11-09"]))
        self.assertIn("no window covers it", said(keys["2026-11-20"]))
        self.assertIn("the snapshot (the rest of its session included)", said(session(1.0)))
        self.assertNotIn("is unknown", said(session(1.0)))

    def test_every_view_sits_in_a_window_and_the_windows_script_is_served(self):
        """AC-30: the layout carries the three windows, with the graphs that
        follow their size, and the page serves the script that moves them."""
        self.chain()
        client = ui_app.create_app().server.test_client()
        layout = client.get("/_dash-layout").get_data(as_text=True)
        for win in ("win-surface", "win-strip", "win-info"):
            self.assertIn(f'"id": "{win}"', layout.replace('":"', '": "'))
        self.assertIn('"responsive"', layout)
        script = client.get("/assets/windows.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("win-bar", script.get_data(as_text=True))
        page = client.get("/").get_data(as_text=True)
        self.assertIn("resize: both", page)

    def test_the_page_is_served_by_its_own_app_with_every_snapshot_listed(self):
        a = self.chain(started=EDT)
        b = self.chain(started=EST)
        client = ui_app.create_app().server.test_client()
        self.assertEqual(client.get("/").status_code, 200)
        layout = client.get("/_dash-layout").get_data(as_text=True)
        self.assertIn(a, layout)
        self.assertIn(b, layout)

    def test_with_no_snapshot_the_page_says_which_commands_to_run(self):
        layout = ui_app.create_app().server.test_client().get("/_dash-layout").get_data(as_text=True)
        self.assertIn("python app.py daily", layout)

    def test_the_command_refuses_a_snapshot_not_carried_through_the_fit(self):
        self.chain()
        with self.assertRaises(SystemExit):
            ui.cmd_ui("2026-01-01_1200", browser=False)


if __name__ == "__main__":
    unittest.main()
