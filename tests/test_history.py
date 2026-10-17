"""
Tests for screener/history.py, offline.

This file compares snapshots rather than computing anything, so the tests are
about alignment: the same expiry lining up across days, a date that only one
snapshot saw being left out, and a missing cell reading as missing rather
than as zero.

  python -m unittest discover tests        (from the project folder)
"""

import contextlib
import csv
import io
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from screener import history  # noqa: E402


def write(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


class Base(unittest.TestCase):
    def build(self, snaps):
        """snaps: {name: {"expiries": [...], "constant": [...], "sessions": [...]}}"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        for name, s in snaps.items():
            write(root / "iv" / name / "expiries.csv", s.get("expiries", []),
                  ["expiry", "dte", "sessions", "atm_iv", "put_skew_25d",
                   "collected_band"])
            write(root / "term" / name / "constant.csv", s.get("constant", []),
                  ["sessions", "vol"])
            write(root / "term" / name / "forward.csv", s.get("sessions", []),
                  ["from_expiry", "to_expiry", "session_priced", "sessions",
                   "forward_vol", "forward_vol_error"])
        for attr, value in (("IV_DIR", root / "iv"), ("TERM_DIR", root / "term"),
                            ("OUT_DIR", root / "history")):
            old = getattr(history, attr)
            setattr(history, attr, value)
            self.addCleanup(setattr, history, attr, old)
        return root


def expiry(e, dte, sessions, atm, skew=0.02, band="12/6"):
    return {"expiry": e, "dte": dte, "sessions": sessions, "atm_iv": atm,
            "put_skew_25d": skew, "collected_band": band}


def session(date, vol):
    return {"from_expiry": "x", "to_expiry": date, "session_priced": date,
            "sessions": 1, "forward_vol": vol, "forward_vol_error": 0.0005}


TWO = {
    "2026-10-12_1449": {
        "expiries": [expiry("2026-10-16", 4, 4, 0.1082), expiry("2026-10-23", 11, 9, 0.1005)],
        "constant": [{"sessions": 5, "vol": 0.0910}, {"sessions": 10, "vol": 0.0947}],
        "sessions": [session("2026-10-16", 0.0933), session("2026-10-20", 0.0871)],
    },
    "2026-10-13_1319": {
        "expiries": [expiry("2026-10-16", 3, 3, 0.1206), expiry("2026-10-27", 14, 10, 0.1018)],
        "constant": [{"sessions": 5, "vol": 0.0979}, {"sessions": 10, "vol": 0.1004}],
        "sessions": [session("2026-10-16", 0.0997), session("2026-10-26", 0.1103)],
    },
}


class TestViews(Base):
    def setUp(self):
        self.build(TWO)
        self.snaps = history.snapshots()
        self.data = history.load(self.snaps)

    def test_snapshots_come_back_oldest_first(self):
        self.assertEqual(self.snaps, ["2026-10-12_1449", "2026-10-13_1319"])

    def test_constant_maturity_lines_horizons_up_across_days(self):
        rows = history.constant_maturity(self.data, self.snaps)
        self.assertEqual([r["sessions"] for r in rows], [5, 10])
        self.assertAlmostEqual(rows[0]["2026-10-12_1449"], 0.0910)
        self.assertAlmostEqual(rows[0]["2026-10-13_1319"], 0.0979)

    def test_fixed_expiry_keeps_only_what_appears_more_than_once(self):
        """2026-10-23 is in the first snapshot and 2026-10-27 only in the
        second; neither can be compared, so neither is a row."""
        rows = history.fixed_expiry(self.data, self.snaps)
        self.assertEqual([r["expiry"] for r in rows], ["2026-10-16"])
        cell = rows[0]["2026-10-13_1319"]
        self.assertEqual((cell["sessions"], cell["dte"]), (3, 3))
        self.assertAlmostEqual(cell["atm"], 0.1206)

    def test_fixed_expiry_carries_the_sessions_left_so_ageing_is_visible(self):
        """The whole hazard of this view is reading a falling IV as news when
        it is the clock. The session count has to travel with the number."""
        row = history.fixed_expiry(self.data, self.snaps)[0]
        before, after = row["2026-10-12_1449"], row["2026-10-13_1319"]
        self.assertEqual((before["sessions"], after["sessions"]), (4, 3))

    def test_per_session_keeps_only_dates_priced_twice(self):
        rows = history.per_session(self.data, self.snaps)
        self.assertEqual([r["session"] for r in rows], ["2026-10-16"])
        self.assertAlmostEqual(rows[0]["2026-10-12_1449"]["vol"], 0.0933)
        self.assertAlmostEqual(rows[0]["2026-10-13_1319"]["vol"], 0.0997)

    def test_a_window_wider_than_one_session_is_not_pinned_to_a_date(self):
        """Only a one-session window names a date. A three-session gap has a
        blank session_priced and must not appear here."""
        wide = dict(TWO)
        self.build({**TWO, "2026-10-14_1300": {
            "expiries": [expiry("2026-10-16", 2, 2, 0.13)],
            "constant": [{"sessions": 5, "vol": 0.10}],
            "sessions": [{"from_expiry": "a", "to_expiry": "2026-10-30",
                          "session_priced": "", "sessions": 3,
                          "forward_vol": 0.1387, "forward_vol_error": 0.0018}],
        }})
        snaps = history.snapshots()
        rows = history.per_session(history.load(snaps), snaps)
        self.assertNotIn("2026-10-30", [r["session"] for r in rows])


class TestMissingData(Base):
    def test_a_snapshot_missing_an_expiry_reads_as_missing_not_zero(self):
        self.build(TWO)
        snaps = history.snapshots()
        rows = history.fixed_expiry(history.load(snaps), snaps, min_seen=1)
        only_first = next(r for r in rows if r["expiry"] == "2026-10-23")
        self.assertIsNone(only_first["2026-10-13_1319"])
        self.assertIsNotNone(only_first["2026-10-12_1449"])

    def test_a_snapshot_with_no_term_output_contributes_nothing_and_does_not_crash(self):
        root = self.build(TWO)
        (root / "term" / "2026-10-14_1300").mkdir(parents=True)
        snaps = history.snapshots()
        self.assertIn("2026-10-14_1300", snaps)
        data = history.load(snaps)
        self.assertEqual(data["2026-10-14_1300"]["constant"], {})
        rows = history.constant_maturity(data, snaps)
        self.assertIsNone(rows[0]["2026-10-14_1300"])


class TestEndToEnd(Base):
    def test_writes_three_files_and_reports_three_views(self):
        self.build(TWO)
        snaps, fixed, constant, sessions, bands = history.analyse()
        self.assertEqual(len(snaps), 2)
        for name in ("constant_maturity.csv", "fixed_expiry.csv", "per_session.csv"):
            path = history.OUT_DIR / name
            self.assertTrue(path.exists(), name)
            with open(path, newline="", encoding="utf-8") as f:
                saved = list(csv.DictReader(f))
            self.assertTrue(all(s in saved[0] for s in snaps),
                            f"{name} should carry one column per snapshot")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            history.report(snaps, fixed, constant, sessions, bands)
        text = out.getvalue()
        for heading in ("CONSTANT MATURITY", "FIXED EXPIRY", "PER SESSION"):
            self.assertIn(heading, text)

    def test_refuses_a_single_snapshot(self):
        self.build({"2026-10-12_1449": TWO["2026-10-12_1449"]})
        with self.assertRaises(SystemExit):
            history.analyse()

    def test_limit_keeps_the_most_recent(self):
        self.build(TWO)
        self.assertEqual(history.snapshots(1), ["2026-10-13_1319"])


if __name__ == "__main__":
    unittest.main()


class TestBandChange(Base):
    def test_a_band_change_across_snapshots_is_called_out(self):
        """A variance swap rate is only as wide as the chain behind it, so a
        row spanning 6/3 and 12/6 compares different quantities."""
        self.build({
            "2026-10-12_1449": {**TWO["2026-10-12_1449"],
                                "expiries": [expiry("2026-10-16", 4, 4, 0.108, band="6/3")]},
            "2026-10-15_1233": {**TWO["2026-10-13_1319"],
                                "expiries": [expiry("2026-10-16", 1, 1, 0.147, band="12/6")]},
        })
        snaps, fixed, constant, sessions, bands = history.analyse()
        self.assertEqual(set(bands.values()), {"6/3", "12/6"})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            history.report(snaps, fixed, constant, sessions, bands)
        self.assertIn("too narrow to carry a variance", out.getvalue())

    def test_two_wide_bands_are_not_flagged_against_each_other(self):
        """12/6 and 20/10 both clear the measured convergence point, so a
        history spanning them is comparing like with like."""
        self.build({
            "2026-10-15_1233": {**TWO["2026-10-12_1449"],
                                "expiries": [expiry("2026-10-16", 4, 4, 0.108, band="20/10")]},
            "2026-10-16_1300": {**TWO["2026-10-13_1319"],
                                "expiries": [expiry("2026-10-16", 1, 1, 0.147, band="12/6")]},
        })
        snaps, fixed, constant, sessions, bands = history.analyse()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            history.report(snaps, fixed, constant, sessions, bands)
        self.assertNotIn("too narrow", out.getvalue())
