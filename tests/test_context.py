"""
Tests for screener/context.py, offline.

Two claims run through this file. The first is that the decomposition tiles:
every complement is the chain minus one window, so a gap anywhere would
quietly shrink every other comparison. The second is that neither comparison
smuggles in a shape - a flat chain must read flat everywhere, and a chain
that slopes in a straight line must read flat against its neighbours even
when the windows are unevenly spaced.

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
from screener import context  # noqa: E402

YEAR = 252.0


def chain(windows, err=0.0):
    """term.load rows whose forward windows have exactly the vols given.

    `windows` is [(sessions, forward_vol)] running from spot. Calendar days
    are set so the two clocks coincide, which keeps the arithmetic here exact
    - the clocks parting company is pinned in its own test rather than left
    to leak into every other one."""
    rows, cum_s, cum_w = [], 0.0, 0.0
    for i, (sessions, vol) in enumerate(windows):
        cum_s += sessions
        cum_w += vol * vol * (sessions / YEAR)
        T = cum_s / YEAR
        level = math.sqrt(cum_w / T)
        rows.append({"expiry": f"E{i + 1}", "sessions": cum_s,
                     "days": cum_s * 365.0 / YEAR, "T": T,
                     "atm": level, "level": level, "source": "vs",
                     "level_error": err, "total_var": cum_w,
                     "total_var_error": 2.0 * level * T * err})
    return rows


def scored(windows, err=0.0):
    rows = chain(windows, err)
    cut, full = context.decompose(rows)
    return context.richness(cut, full)


class TestTheDecomposition(unittest.TestCase):
    def test_the_windows_tile_the_chain(self):
        """Sessions add to the chain's and variances to its total, with no
        gap between one window and the next. Every complement is computed by
        subtraction, so this is the property they all rest on."""
        rows = chain([(2, 0.12), (1, 0.15), (5, 0.21)])
        cut, full = context.decompose(rows)
        self.assertAlmostEqual(sum(w["sessions"] for w in cut),
                               full[-1]["sessions"])
        self.assertAlmostEqual(
            sum(w["total_var_to"] - w["total_var_from"] for w in cut),
            full[-1]["total_var"], places=12)
        for a, b in zip(cut, cut[1:]):
            self.assertEqual(a["to_expiry"], b["from_expiry"])

    def test_the_first_window_starts_at_spot_not_at_the_first_expiry(self):
        """term.forward_windows covers the gaps BETWEEN expiries. Without the
        stub the stretch from the snapshot to the front expiry belongs to no
        window and is missing from every complement."""
        cut, _ = context.decompose(chain([(3, 0.10), (2, 0.20)]))
        self.assertEqual(len(cut), 2)
        self.assertEqual(cut[0]["from_expiry"], context.SPOT)
        self.assertAlmostEqual(cut[0]["forward_vol"], 0.10)
        self.assertAlmostEqual(cut[0]["total_var_from"], 0.0)

    def test_no_time_carries_no_variance_and_no_doubt_about_it(self):
        """The stub is arithmetic, not an assumption, so it must not widen
        the first window's error bar."""
        rows = chain([(3, 0.10), (2, 0.20)], err=0.004)
        cut, full = context.decompose(rows)
        self.assertEqual(full[0]["total_var"], 0.0)
        self.assertEqual(full[0]["total_var_error"], 0.0)
        gradient = 1.0 / (2.0 * 0.10 * (3.0 / YEAR))
        self.assertAlmostEqual(cut[0]["forward_vol_error"],
                               gradient * rows[0]["total_var_error"], places=12)


class TestTheSnapshotsOwnSession(unittest.TestCase):
    """A snapshot taken before the close sits at a negative session count.
    vol.sessions_between starts from the day AFTER, so the clock's origin is
    that day's close, and the window from the snapshot to the first expiry
    is longer than one session by however much of today is left.

    Left alone this reads 11% high at 14:30 and 2% high at 15:45, so a
    routine that snaps at different times on different days puts a sawtooth
    of about a point into the front of every chain. Measured on the two real
    snapshots twelve minutes apart: 0.194 points of disagreement before the
    correction, 0.020 after."""

    def test_the_snapshot_sits_before_the_close_not_on_it(self):
        full = context.with_spot(chain([(1, 0.12), (1, 0.14)]), remaining=0.25)
        self.assertAlmostEqual(full[0]["sessions"], -0.25)
        self.assertEqual(full[0]["total_var"], 0.0, "no time, no variance")

    def test_the_front_window_is_longer_than_one_session(self):
        cut, _ = context.decompose(chain([(1, 0.12), (1, 0.14)]), remaining=0.25)
        self.assertAlmostEqual(cut[0]["sessions"], 1.25)
        self.assertAlmostEqual(cut[1]["sessions"], 1.0, "only the first one")

    def test_the_same_variance_over_more_sessions_reads_lower(self):
        rows = chain([(1, 0.12), (1, 0.14)])
        at_close = context.decompose(rows, 0.0)[0][0]["forward_vol"]
        midday = context.decompose(rows, 0.25)[0][0]["forward_vol"]
        self.assertAlmostEqual(midday, at_close / math.sqrt(1.25), places=12)

    def test_the_windows_still_tile_what_they_cover(self):
        """The complement arithmetic subtracts from the span, so the span has
        to be measured from the snapshot and not from the first expiry."""
        rows = chain([(2, 0.12), (1, 0.15), (5, 0.21)])
        cut, full = context.decompose(rows, remaining=0.3)
        self.assertAlmostEqual(sum(w["sessions"] for w in cut),
                               full[-1]["sessions"] - full[0]["sessions"])

    def test_a_market_priced_flat_through_the_partial_day_reads_flat(self):
        """Built by hand rather than with chain(), which assumes the first
        expiry holds exactly one session. Here every session carries the same
        variance INCLUDING the 0.4 of today still to run, so the front window
        holds 1.4 sessions of it and must come back at the same 15% as the
        whole sessions after it. Before the correction it read 18%."""
        v, rem = 0.15, 0.4
        rows = []
        for i in range(1, 4):
            elapsed = i + rem
            w = v * v * elapsed / YEAR
            rows.append({"expiry": f"E{i}", "sessions": float(i),
                         "days": elapsed * 365.0 / YEAR, "T": elapsed / YEAR,
                         "atm": v, "level": v, "source": "vs",
                         "level_error": 0.0, "total_var": w,
                         "total_var_error": 0.0})
        cut, full = context.decompose(rows, remaining=rem)
        self.assertAlmostEqual(cut[0]["sessions"], 1.4)
        for w in cut:
            self.assertAlmostEqual(w["forward_vol"], v, places=12)
        for w in context.richness(cut, full):
            self.assertAlmostEqual(w["vs_rest"], 0.0, places=10)


class TestReadingTheSnapshotTime(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        old = context.CHAIN_DIR
        context.CHAIN_DIR = self.root
        self.addCleanup(setattr, context, "CHAIN_DIR", old)

    def write(self, name, started):
        folder = self.root / name
        folder.mkdir(parents=True)
        (folder / "run.json").write_text('{"started_et": "%s"}' % started,
                                         encoding="utf-8")

    def test_reads_the_collectors_own_timestamp(self):
        self.write("2026-10-20_1543", "2026-10-20T14:30:00-04:00")
        self.assertAlmostEqual(context.session_remaining("2026-10-20_1543"),
                               90 / 390, places=6)

    def test_falls_back_to_the_folder_name(self):
        """A snapshot whose raw chain has been deleted still has its time in
        the folder name, to the minute."""
        self.assertAlmostEqual(context.session_remaining("2026-10-20_1430"),
                               90 / 390, places=6)

    def test_after_the_close_nothing_is_left(self):
        self.write("2026-10-20_1700", "2026-10-20T17:00:00-04:00")
        self.assertEqual(context.session_remaining("2026-10-20_1700"), 0.0)

    def test_before_the_open_the_whole_session_is_left(self):
        self.write("2026-10-20_0800", "2026-10-20T08:00:00-04:00")
        self.assertEqual(context.session_remaining("2026-10-20_0800"), 1.0)

    def test_an_unreadable_name_assumes_the_close(self):
        """Zero is the assumption that costs least: it is what a snapshot
        taken at the close would have had."""
        self.assertEqual(context.session_remaining("not-a-snapshot"), 0.0)


class TestAgainstTheRest(unittest.TestCase):
    def test_a_flat_chain_reads_flat_everywhere(self):
        rows = scored([(1, 0.15)] * 5)
        for w in rows:
            self.assertAlmostEqual(w["vs_rest"], 0.0, places=10)
            self.assertFalse(w["rest_differs"])

    def test_the_rest_is_the_chain_less_this_window(self):
        """One loud session inside a quiet chain. The rest has to read as the
        quiet part alone, not as the average including the loud one."""
        rows = scored([(1, 0.10), (1, 0.30), (1, 0.10), (1, 0.10)])
        loud = rows[1]
        quiet = math.sqrt((0.10 ** 2 * 3) / 3)
        self.assertAlmostEqual(loud["rest_vol"], quiet, places=10)
        self.assertAlmostEqual(loud["vs_rest"], 0.30 - quiet, places=10)

    def test_a_sloping_chain_makes_the_front_cheap_and_the_back_rich(self):
        """Not a defect, and the reason the local comparison exists beside
        this one: against the whole rest, a term structure that slopes says
        the same thing about every window in it."""
        rows = scored([(1, 0.10), (1, 0.12), (1, 0.14), (1, 0.16), (1, 0.18)])
        self.assertLess(rows[0]["vs_rest"], 0)
        self.assertLess(rows[1]["vs_rest"], 0)
        self.assertGreater(rows[-1]["vs_rest"], 0)
        self.assertGreater(rows[-2]["vs_rest"], 0)

    def test_one_window_has_no_rest_to_compare_with(self):
        rows = scored([(4, 0.15)])
        self.assertIsNone(rows[0]["vs_rest"])
        self.assertFalse(rows[0]["rest_differs"])


class TestAgainstTheNeighbours(unittest.TestCase):
    def test_a_straight_line_reads_flat_even_when_the_gaps_are_uneven(self):
        """The test a plain mean of the two neighbours fails. Midpoints at 1,
        2.5 and 5.5 sessions: the line from 12% to 21% passes through 15% at
        the middle one, while their mean is 16.5%. Averaging would report a
        1.5 point anomaly where there is only slope."""
        rows = scored([(2, 0.12), (1, 0.15), (5, 0.21)], err=0.002)
        self.assertAlmostEqual(rows[1]["vs_neighbours"], 0.0, places=10)
        self.assertAlmostEqual(rows[1]["neighbour_vol"], 0.15, places=10)
        self.assertFalse(rows[1]["neighbours_differ"])
        self.assertAlmostEqual((0.12 + 0.21) / 2 - 0.15, 0.015, places=10,
                               msg="what averaging would have claimed instead")

    def test_a_window_jutting_above_both_sides_is_found(self):
        rows = scored([(1, 0.12), (1, 0.12), (1, 0.20), (1, 0.12), (1, 0.12)])
        self.assertAlmostEqual(rows[2]["vs_neighbours"], 0.08, places=10)
        self.assertTrue(rows[2]["neighbours_differ"])

    def test_the_ends_are_blank_rather_than_measured_one_sided(self):
        """A first difference where the others are second differences would
        be a different quantity in the same column."""
        rows = scored([(1, 0.10), (1, 0.14), (1, 0.18)])
        self.assertIsNone(rows[0]["vs_neighbours"])
        self.assertIsNone(rows[-1]["vs_neighbours"])
        self.assertIsNotNone(rows[1]["vs_neighbours"])

    def test_curvature_survives_what_slope_does_not(self):
        """The comparison removes a straight line and nothing more: a chain
        bending away from one still reads."""
        rows = scored([(1, 0.10), (1, 0.16), (1, 0.18)])
        self.assertGreater(rows[1]["vs_neighbours"], 0)


class TestErrorBars(unittest.TestCase):
    def test_a_difference_is_less_certain_than_either_side_of_it(self):
        """A window and the rest of the chain share endpoints with opposite
        signs: an error at the window's far edge raises one and lowers the
        other. Treating them as independent would understate the gap."""
        rows = scored([(1, 0.10), (2, 0.14), (3, 0.18), (1, 0.12)], err=0.003)
        for w in rows:
            self.assertGreater(w["vs_rest_error"], w["forward_vol_error"],
                               w["to_expiry"])

    def test_the_last_window_does_not_count_the_chains_end_twice(self):
        """For the last window the rest's far end and its own far end are the
        same total variance and have to cancel. In a two-window chain each
        window's difference against the rest is the other's negated, so the
        two error bars must come out equal; squaring the shared endpoint
        twice would inflate one of them."""
        rows = scored([(2, 0.11), (3, 0.19)], err=0.003)
        self.assertAlmostEqual(rows[0]["vs_rest"], -rows[1]["vs_rest"], places=12)
        self.assertAlmostEqual(rows[0]["vs_rest_error"], rows[1]["vs_rest_error"],
                               places=12)

    def test_a_perfectly_measured_chain_has_no_bar_and_everything_differs(self):
        rows = scored([(1, 0.10), (1, 0.20), (1, 0.10)], err=0.0)
        self.assertAlmostEqual(rows[1]["vs_rest_error"], 0.0)
        self.assertTrue(rows[1]["rest_differs"])

    def test_a_wide_enough_bar_calls_nothing_different(self):
        """The gate is what keeps a noisy chain from reading as a dozen
        findings."""
        rows = scored([(1, 0.10), (1, 0.12), (1, 0.11), (1, 0.13)], err=0.05)
        self.assertFalse(any(w["rest_differs"] for w in rows))
        self.assertFalse(any(w["neighbours_differ"] for w in rows))


class TestTheTwoClocks(unittest.TestCase):
    def test_the_same_variance_annualizes_two_ways_and_both_are_reported(self):
        """23 sessions inside 31 calendar days. The session figure is the
        aggregate of the windows; the calendar one is what can sit beside
        VIX. Showing one without naming its clock reads as a 0.6 point gap
        against the index that is nothing but convention."""
        rows = chain([(23, 0.17)])
        rows[-1]["days"] = 31.0
        rows[-1]["T"] = 31.0 / 365.0
        cut, full = context.decompose(rows)
        level = context.chain_level(cut, full)
        self.assertAlmostEqual(level["vol"], 0.17, places=10)
        self.assertAlmostEqual(level["vol_calendar"],
                               0.17 * math.sqrt((23.0 / YEAR) / (31.0 / 365.0)),
                               places=12)
        self.assertGreater(level["vol_calendar"] - level["vol"], 0.006,
                           "0.6 vol points of pure convention")


class TestPercentile(unittest.TestCase):
    def closes(self, levels):
        import datetime as dt
        return [(dt.date(2020, 1, 1) + dt.timedelta(days=i), v)
                for i, v in enumerate(levels)]

    def test_ranks_against_the_history(self):
        got = context.percentile(0.25, self.closes([10.0, 20.0, 30.0, 40.0]))
        self.assertAlmostEqual(got["pct"], 0.5)
        self.assertEqual(got["n"], 4)

    def test_ties_take_the_midpoint(self):
        """Index closes carry two decimals, so exact repeats are common and
        counting them all as below would overstate every reading."""
        got = context.percentile(0.20, self.closes([10.0, 20.0, 20.0, 30.0]))
        self.assertAlmostEqual(got["pct"], 0.5)

    def test_the_extremes_are_zero_and_one(self):
        history = self.closes([10.0, 20.0, 30.0])
        self.assertAlmostEqual(context.percentile(0.05, history)["pct"], 0.0)
        self.assertAlmostEqual(context.percentile(0.95, history)["pct"], 1.0)

    def test_no_rate_means_no_percentile_rather_than_a_zero(self):
        self.assertIsNone(context.percentile(None, self.closes([10.0])))
        self.assertIsNone(context.percentile(0.15, []))


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        import datetime as dt
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        rows = chain([(1, 0.10), (1, 0.20), (1, 0.12)])

        def patch(obj, name, value):
            old = getattr(obj, name)
            setattr(obj, name, value)
            self.addCleanup(setattr, obj, name, old)

        patch(context, "OUT_DIR", self.root)
        patch(context.term, "load", lambda s: (rows, []))
        patch(context, "vix_history",
              lambda refresh=False: [(dt.date(2026, 10, 20), 17.31)])
        patch(context.vrp, "our_rate",
              lambda s: {"rate": 0.1737, "extrapolated_days": 0.0,
                         "band": "12/6"})

    def test_writes_both_files_and_reports_every_window(self):
        cut, summary, dest, dropped = context.analyse("2026-10-20_1543")
        self.assertEqual(len(cut), 3)
        for name, expect in (("windows.csv", 3), ("chain.csv", 1)):
            with open(dest / name, newline="", encoding="utf-8") as f:
                saved = list(csv.DictReader(f))
            self.assertEqual(len(saved), expect, name)
        self.assertAlmostEqual(summary["ours_minus_vix"], 0.1737 - 0.1731,
                               places=10)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            context.report(cut, summary, dest, dropped)
        text = out.getvalue()
        self.assertIn("vs rest", text)
        self.assertIn("vs neigh", text)
        self.assertIn("percentile", text)

    def test_a_chain_with_no_thirty_day_rate_still_decomposes(self):
        """A narrow band refuses a rate, which costs the percentile and
        nothing else. The windows are measured against each other and do not
        need an index to be readable."""
        old = context.vrp.our_rate
        context.vrp.our_rate = lambda s: None
        self.addCleanup(setattr, context.vrp, "our_rate", old)
        cut, summary, dest, _ = context.analyse("2026-10-20_1543")
        self.assertEqual(len(cut), 3)
        self.assertIsNone(summary["percentile"])
        self.assertIsNotNone(summary["chain_vol"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            context.report(cut, summary, dest)
        self.assertIn("no 30-day rate", out.getvalue())


if __name__ == "__main__":
    unittest.main()
