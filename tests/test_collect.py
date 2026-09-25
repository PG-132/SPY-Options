"""
Tests for screener/collect.py. No network, no credentials: a fake client
stands in for Webull, so these run any time, weekends included.

  python -m unittest discover tests        (from the project folder)
  or press Run on this file in VS Code
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
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from screener import collect  # noqa: E402

SPOT = 762.60
IV = 0.12
TODAY = collect.now_et().date()


def occ(exp, right, strike):
    """An OCC-style symbol, e.g. SPY260925C00764000."""
    return f"SPY{exp.strftime('%y%m%d')}{right}{int(round(strike * 1000)):08d}"


def parse_occ(sym):
    return (dt.datetime.strptime(sym[3:9], "%y%m%d").date(), sym[9], int(sym[10:]) / 1000)


def listing(expiries, strikes):
    """Contract rows shaped like Webull's get_option_contracts."""
    rows, iid = [], 1000
    for exp in expiries:
        for k in strikes:
            for typ in ("CALL", "PUT"):
                iid += 1
                rows.append({"symbol": occ(exp, typ[0], k), "instrument_id": iid,
                             "expiration_date": exp.isoformat(), "strike_price": str(k),
                             "option_type": typ, "def_type": "STANDARD",
                             "root_symbol": "SPY"})
    return rows


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class FakeClient:
    """Just enough of Webull's DataClient: SPY quotes, a paged contract listing
    that honors the strike range, and option quotes. Every quote carries the
    same IV; bids go to zero beyond 3 expected moves, like a real chain's
    wings, unless bids_everywhere. One symbol can be set to be rejected."""

    def __init__(self, contracts, page_size=7, bad_symbol=None, iv="0.131",
                 bids_everywhere=False):
        self.contracts, self.page_size, self.bad = contracts, page_size, bad_symbol
        self.iv, self.bids_everywhere = iv, bids_everywhere
        self.market_data = self.instrument = self.option_market_data = self

    def get_snapshot(self, symbol, category):
        return FakeResponse([{"symbol": "SPY", "price": str(SPOT),
                              "quote_time": int(collect.now_et().timestamp() * 1000),
                              "yield": "0.00973"}])

    def get_option_contracts(self, page_size, last_instrument_id,
                             strike_price_gte=None, strike_price_lte=None, **kw):
        pool = [r for r in self.contracts
                if (strike_price_gte is None or float(r["strike_price"]) >= strike_price_gte)
                and (strike_price_lte is None or float(r["strike_price"]) <= strike_price_lte)]
        ids = [r["instrument_id"] for r in pool]
        start = 0 if last_instrument_id is None else ids.index(last_instrument_id) + 1
        return FakeResponse(pool[start:start + self.page_size])

    def get_option_snapshot(self, symbols, category):
        if self.bad in symbols:
            raise RuntimeError(f"417 INVALID_SYMBOL Invalid Symbol:[{self.bad}]")
        now_ms = int(collect.now_et().timestamp() * 1000)
        out = []
        for s in symbols:
            exp, right, k = parse_occ(s)
            move = 0.131 * math.sqrt(max((exp - TODAY).days, 1) / 365)
            moves = (k / SPOT - 1) / move                  # strikes out, in expected moves
            call_delta = 0.5 * math.erfc(moves / math.sqrt(2))   # dies off like a real wing
            quoted = self.bids_everywhere or abs(moves) <= 3
            out.append({"symbol": s, "bid": "1.10" if quoted else "0",
                        "ask": "1.15" if quoted else "0.01", "price": "1.12",
                        "volume": "10", "open_interest": "250", "quote_time": now_ms,
                        "imp_vol": self.iv, "gamma": "0.02", "theta": "-0.19",
                        "delta": f"{call_delta if right == 'C' else call_delta - 1:.4f}",
                        "vega": "0.51", "rho": "0.07"})
        return FakeResponse(out)


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = dict(collect.CONFIG)
        collect.CONFIG["throttle_s"] = 0          # no sleeping in tests

    def tearDown(self):
        collect.CONFIG.clear()
        collect.CONFIG.update(self.saved)
        collect.CHAIN_DIR = collect.ROOT / "data" / "chains"


class TestRules(Base):
    def test_band_is_expected_moves_and_follows_the_iv(self):
        below = collect.band_pct(30, IV, "below")
        above = collect.band_pct(30, IV, "above")
        self.assertAlmostEqual(below, 6 * IV * math.sqrt(30 / 365))
        self.assertAlmostEqual(above, 3 * IV * math.sqrt(30 / 365))
        self.assertAlmostEqual(below, 0.2064, places=4)   # 20.6% down, 10.3% up at 12% IV
        self.assertAlmostEqual(above, 0.1032, places=4)
        # a quarter of the time -> half the band; double the IV -> double the band
        self.assertAlmostEqual(collect.band_pct(7, IV, "below")
                               / collect.band_pct(28, IV, "below"), 0.5)
        self.assertAlmostEqual(collect.band_pct(30, 2 * IV, "above"), 2 * above)

    def test_the_put_side_reaches_further_than_the_call_side(self):
        # SPY puts stay bid far out of the money; calls stop being quoted sooner
        self.assertGreater(collect.band_pct(30, IV, "below"),
                           collect.band_pct(30, IV, "above"))

    def test_market_hours(self):
        fri = dt.datetime(2026, 9, 18, tzinfo=collect.ET)
        self.assertTrue(collect.market_open(fri.replace(hour=14, minute=30)))
        self.assertTrue(collect.market_open(fri.replace(hour=9, minute=30)))
        self.assertFalse(collect.market_open(fri.replace(hour=16, minute=0)))
        self.assertFalse(collect.market_open(fri.replace(hour=9, minute=29)))
        self.assertFalse(collect.market_open(dt.datetime(2026, 9, 19, 12, tzinfo=collect.ET)))

    def test_only_standard_spy_series(self):
        good = {"symbol": "SPY260925C00764000", "def_type": "STANDARD", "root_symbol": "SPY"}
        self.assertTrue(collect.is_standard(good))
        self.assertFalse(collect.is_standard({**good, "symbol": "4SPY260925C00771350"}))
        self.assertFalse(collect.is_standard({**good, "def_type": "ADJUSTED"}))
        self.assertFalse(collect.is_standard({**good, "root_symbol": "SPYX"}))

    def test_batches_respect_the_20_contract_cap(self):
        self.assertEqual([len(b) for b in collect.batches(list(range(45)))], [20, 20, 5])

    def test_quote_time_converts_to_eastern(self):
        t = dt.datetime(2026, 9, 18, 15, 55, tzinfo=collect.ET)
        self.assertTrue(collect.ms_to_et(int(t.timestamp() * 1000)).startswith(
            "2026-09-18T15:55:00.000-04:00"))
        self.assertEqual(collect.ms_to_et(None), "")
        self.assertEqual(collect.ms_to_et("not a time"), "")


class TestPlan(Base):
    def setUp(self):
        super().setUp()
        days = (0, 1, 7, 30, 31, 90)
        self.exps = {d: TODAY + dt.timedelta(days=d) for d in days}
        strikes = [float(k) for k in range(600, 921)]
        self.contracts = {r["symbol"]: r for r in listing(self.exps.values(), strikes)}

    def test_expiries_1_to_30_days_only(self):
        expiries, _ = collect.build_plan(self.contracts, SPOT, TODAY, IV)
        self.assertEqual([e["dte"] for e in expiries], [1, 7, 30])

    def test_every_strike_inside_its_band_with_both_rights(self):
        _, chosen = collect.build_plan(self.contracts, SPOT, TODAY, IV)
        by_exp = {}
        for c in chosen:
            moneyness = c["strike"] / SPOT - 1
            side = "below" if moneyness < 0 else "above"
            self.assertLessEqual(abs(moneyness), collect.band_pct(c["dte"], IV, side) + 1e-12)
            by_exp.setdefault(c["dte"], {}).setdefault(c["strike"], set()).add(c["right"])
        for dte, strikes in by_exp.items():
            self.assertTrue(all(r == {"C", "P"} for r in strikes.values()), dte)
            # nothing inside the band left out: the listing has every $1 strike
            lo = SPOT * (1 - collect.band_pct(dte, IV, "below"))
            hi = SPOT * (1 + collect.band_pct(dte, IV, "above"))
            want = {float(k) for k in range(600, 921) if lo <= k <= hi}
            self.assertEqual(set(strikes), want, dte)

    def test_higher_iv_records_a_wider_band(self):
        calm, _ = collect.build_plan(self.contracts, SPOT, TODAY, IV)
        wild, _ = collect.build_plan(self.contracts, SPOT, TODAY, 2 * IV)
        for c, w in zip(calm, wild):
            self.assertGreater(w["strikes"], c["strikes"], c["expiry"])


class TestAnchor(Base):
    def setUp(self):
        super().setUp()
        self.exps = [TODAY + dt.timedelta(days=d) for d in (7, 28, 31, 35)]
        self.rows = listing(self.exps, [float(k) for k in range(740, 790)])

    def test_uses_the_recorded_expiry_closest_to_30_days_and_the_strike_nearest_spot(self):
        # 31 days is nearer to 30 than 28, but it isn't recorded, so 28 anchors
        a = quiet(collect.anchor_iv, FakeClient(self.rows), SPOT, TODAY)
        self.assertFalse(a["fallback"])
        self.assertEqual((a["dte"], a["strike"]), (28, 763.0))
        self.assertAlmostEqual(a["iv"], 0.131)

    def test_falls_back_loudly_when_webull_gives_no_iv(self):
        a = quiet(collect.anchor_iv, FakeClient(self.rows, iv=""), SPOT, TODAY)
        self.assertTrue(a["fallback"])
        self.assertEqual(a["iv"], collect.CONFIG["iv_fallback"])
        self.assertIn("no IV", a["source"])


class TestWebullHandling(Base):
    def test_listing_pages_until_nothing_new_and_drops_adjusted_series(self):
        rows = listing([TODAY + dt.timedelta(days=7)], [760.0, 761.0, 762.0, 763.0])
        rows.append({**rows[0], "symbol": "4SPY260925C00771350", "instrument_id": 1,
                     "def_type": "ADJUSTED"})
        got, pages = quiet(collect.list_contracts, FakeClient(rows, page_size=3), 700, 800)
        self.assertEqual(len(got), 8)                       # 4 strikes x call/put
        self.assertNotIn("4SPY260925C00771350", got)
        self.assertEqual(pages, 4)                          # 3 pages of rows + 1 empty

    def test_rejected_symbol_is_dropped_and_the_rest_still_quoted(self):
        rows = listing([TODAY + dt.timedelta(days=7)], [760.0, 761.0])
        syms = [r["symbol"] for r in rows]
        rejected = []
        quotes = collect.quote_batch(FakeClient(rows, bad_symbol=syms[1]), syms, rejected)
        self.assertEqual(rejected, [syms[1]])
        self.assertEqual({q["symbol"] for q in quotes}, set(syms) - {syms[1]})

    def test_rows_keep_raw_fields_and_rename_webull_greeks(self):
        c = {"symbol": "SPY260925C00764000", "expiry": "2026-09-25", "dte": 7,
             "strike": 764.0, "right": "C"}
        q = {"symbol": c["symbol"], "bid": "3.10", "ask": "3.20", "imp_vol": "0.13",
             "delta": "0.51", "quote_time": 1790000000000, "something_new": "kept"}
        row = collect.to_row(q, c, batch_no=3, fetched_at="t")
        self.assertEqual(row["vendor_iv"], "0.13")
        self.assertEqual(row["vendor_delta"], "0.51")
        self.assertNotIn("imp_vol", row)
        self.assertNotIn("delta", row)
        self.assertEqual((row["bid"], row["ask"], row["something_new"]), ("3.10", "3.20", "kept"))
        self.assertEqual((row["strike"], row["right"], row["batch"]), (764.0, "C", 3))
        self.assertTrue(row["quote_time_et"])


class TestSnapshotEndToEnd(Base):
    def setUp(self):
        super().setUp()
        self.exps = [TODAY + dt.timedelta(days=d) for d in (1, 7, 30, 45)]
        self.rows = listing(self.exps, [float(k) for k in range(600, 921)])

    def snap(self, client):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        collect.CHAIN_DIR = pathlib.Path(tmp.name)
        return quiet(collect.take_snapshot, client)

    def test_one_pass_writes_a_complete_run_folder(self):
        bad = next(r["symbol"] for r in self.rows
                   if r["expiration_date"] == self.exps[1].isoformat()
                   and abs(float(r["strike_price"]) - SPOT) < 1)
        folder, run = self.snap(FakeClient(self.rows, page_size=250, bad_symbol=bad))

        self.assertEqual(run["anchor"]["dte"], 30)
        self.assertAlmostEqual(run["anchor"]["iv"], 0.131)
        _, chosen = collect.build_plan({r["symbol"]: r for r in self.rows}, SPOT, TODAY, 0.131)
        self.assertEqual(run["requested"], len(chosen))
        self.assertEqual(run["received"], len(chosen) - 1)
        self.assertEqual(run["rejected"], [bad])
        self.assertEqual(run["missing"], [])
        self.assertEqual([e["dte"] for e in run["expiries"]], [1, 7, 30])
        # 4 expected moves out, the edges carry almost no delta: no edge warning
        self.assertTrue(all(e["delta"] < collect.CONFIG["edge_delta"] for e in run["edges"]))
        self.assertFalse([w for w in run["warnings"] if "band edges" in w])

        with open(folder / "options.csv", newline="", encoding="utf-8") as f:
            opts = list(csv.DictReader(f))
        self.assertEqual(len(opts), run["received"])
        self.assertEqual(list(opts[0])[:7],
                         ["symbol", "expiry", "dte", "strike", "right", "bid", "ask"])
        self.assertIn("vendor_iv", opts[0])
        self.assertNotIn("imp_vol", opts[0])

        with open(folder / "spot.csv", newline="", encoding="utf-8") as f:
            spots = list(csv.DictReader(f))
        n_batches = math.ceil(len(chosen) / 20)
        self.assertEqual(len(spots), 1 + math.ceil(n_batches / collect.CONFIG["spot_every"]))
        self.assertEqual(spots[0]["after_batch"], "0")
        self.assertEqual(spots[-1]["after_batch"], str(n_batches))

        saved = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["received"], run["received"])
        self.assertEqual(saved["anchor"]["expiry"], self.exps[2].isoformat())

    def test_edges_that_still_carry_delta_are_flagged(self):
        collect.CONFIG["moves_below"] = 2         # too narrow: 2 moves out is ~2.3% delta
        collect.CONFIG["moves_above"] = 2
        _, run = self.snap(FakeClient(self.rows, page_size=250))
        flagged = [e for e in run["edges"] if e["delta"] >= collect.CONFIG["edge_delta"]]
        self.assertEqual(len(flagged), 2 * len(run["expiries"]))    # a put and a call each
        self.assertTrue([w for w in run["warnings"] if "band edges" in w])

    def test_implausible_anchor_iv_is_flagged(self):
        _, run = self.snap(FakeClient(self.rows, page_size=250, iv="0.75"))
        self.assertTrue([w for w in run["warnings"] if "outside the plausible" in w])

    def test_missing_anchor_iv_falls_back_and_says_so(self):
        _, run = self.snap(FakeClient(self.rows, page_size=250, iv=""))
        self.assertTrue(run["anchor"]["fallback"])
        self.assertTrue([w for w in run["warnings"] if "fallback" in w])


if __name__ == "__main__":
    unittest.main()
