# Scenario engine

State: accepted
Created: 2026-11-06 · Updated: 2026-11-09
Specs: SCEN-001 to SCEN-011 ([../specs/scenario.md](../specs/scenario.md))

## Problem

Nothing in the screener can say what a position is worth, or what it is exposed to, if SPY, IV or the date were different. The owner wants to pick strikes across expiries (or name target Greeks), and see P&L and Greeks for hypothetical spot levels, IV shifts and dates, and along a hypothetical path. The structure chooser needs the same calculation: its fit is the distance between a candidate's exposures and a target across spot outcomes ([2026-11-04-choosing.md](2026-11-04-choosing.md)). So does the delta-hedged paper trade, whose hedges make P&L depend on the path.

The engine is that calculation, built once, on the existing surface and term work. The UI and the chooser come after it and call it. (**Decided**, user 2026-11-06: engine first, using the existing surface work.)

## Intended behavior

A position is a list of legs from one snapshot. An option leg is expiry, strike, right and signed quantity in contracts. A hedge leg is a signed quantity of SPY shares or of E-nano S&P 500 futures (NES). A **scenario point** is a date, a spot price and a parallel IV shift in vol points. For each point the engine returns each leg's value and Greeks, the position totals, and P&L against the start. A **path** is a dated sequence of points with optional hedge trades at each one, and returns P&L along it.

What-if only. Every number is a model output under the stated rules, labeled as such, and never a forecast or a sort key (README; CHOOSE-002).

### Where each input comes from

- **The start spot `S`.** `spot_at_start` in the snapshot's `run.json`, read through `ledger.snapshot_spot` rather than reparsed, so the engine and the ledger start from the same price. If it is missing, the median of `spot.csv`'s prices. Options only see the ratio `S'/S`, so a few cents of drift across the 90-second pass doesn't matter; share and NES legs see `S' - S`.
- **Spot, forward, rate, time.** From the snapshot. Each expiry's forward comes from `data/iv/<snap>/expiries.csv`, and the rate from `vol.CONFIG["rate"]`. Time to expiry is computed the way `vol.one_expiry` computes it, and through the same function (see Tasks), so any change to that clock (A-003) lands in one place. At a scenario spot `S'` each forward moves with spot: `F' = F × S' / S`. Carry is unchanged.
- **A leg's IV.** `contracts.csv` holds one IV per strike, read from the out-of-the-money side. Under the forward from parity, that is the IV for both the call and the put at that strike, so an in-the-money leg uses it too. If the strike was not readable, the leg takes the fitted curve's value at its moneyness, inside the fitted range only (below). Outside that range the leg is refused with a reason.
- **A leg's quotes.** Its own bid and ask, from the raw `data/chains/<snap>/options.csv`. `contracts.csv` holds only the out-of-the-money side.
- **The smile.** `data/surface/<snap>/fits.csv`: `iv(k) = Σ c_i × smile_basis(k, m, s)[i]` over `c0..c4`, with `k = ln(K/F)` against that expiry's own forward. Use `surface.smile_basis`; don't copy it. The fitted range for an expiry is the min and max `moneyness` of its readable rows in `points.csv`. `surface.py` says the curve is only ever evaluated between the strikes it was fitted on, and the engine keeps that rule.
- **The term structure.** `term.load` and its total variances, with the origin (0 sessions, 0 variance) added as context.py's front window does.

### The rules that make it a model

1. **When spot moves, the smile slides along the fitted curve.** Each leg's IV follows the fitted curve to its new moneyness `ln(K/F')`, plus the leg's own residual (its IV minus the curve at the start), so a leg starts exactly where vol.py read it. A leg whose new moneyness leaves the fitted range is held at the range-edge value and flagged; the cubic is never extrapolated. An expiry with no fit falls back to sticky strike, and is flagged. (**Decided**, user 2026-11-06: "how else would you have the comparison")
2. **When the date moves, each expiry rolls along today's term structure.** An expiry's remaining total variance is its total today minus the variance the market prices for the sessions that have passed (`term.py`'s total variance interpolated in sessions, as `term.constant_maturity` does). Its smile is scaled by the ratio of the new level to today's level, keeping its shape. Because the clock is sessions, a weekend or holiday costs no variance. (**Decided**, user 2026-11-06. Plain Black-Scholes would decay a weekend as three calendar days; the owner's simulated account shows no change over weekends and holidays.)
   - A negative remainder is a calendar arbitrage; it is flagged and that expiry falls back to constant IV. So does a leg whose expiry `term.load` dropped (the drop rule; on the 2026-11-05 stress chain it left three windows, see A-015): with no total of its own in the term structure, it has nothing to roll from.
   - A scenario date is valued at that date's close (`prices.session_close`), and a leg on or past its expiry is worth intrinsic at that point's spot, with zero Greeks.
3. **IV shift.** A parallel shift in vol points, added to every leg after rules 1 and 2. Any skew change in a selloff is the owner's to enter this way; neither rule models it. (**Proposed**)
4. **P&L and entry.** P&L is model value at the point minus model value at the start, so a scenario where nothing moves reads zero. Entry is at mid. The far-side cost (asks paid, bids received) is shown beside it, and the gap between a leg's model start value and its own mid is shown per leg, not folded into P&L. (**Decided**, user 2026-11-06: entry at mid.)
5. **Error bars.** Each value carries a range from the leg's IV band. The leg is repriced at `iv_bid` and `iv_ask`, carried through the same rules. (**Proposed**, following the Conventions: numbers carry error bars.)
6. **Hedges.** Without trades along it, P&L at a point depends only on that point, not on how SPY got there. With hedge trades it depends on the path: each trade's P&L runs from its own spot.
   - SPY shares: delta 1 per share.
   - NES futures: entered as contracts, with their fill price; the engine converts. NES pays $0.50 per S&P 500 index point (**Sourced**: [NinjaTrader, E-nano contract specs](https://ninjatrader.com/futures/futures-contracts/e-nano/), accessed 2026-11-06; CME lists NES from 2026-08-24). A $1 move in SPY is about a 10-point move in the S&P 500, so one NES carries about 5 SPY shares of delta, not 1 (arithmetic, not measured). The engine converts at `0.50 × NES price / SPY spot` shares per contract, both from the trade, so the ratio is read rather than assumed. (**Proposed**: the owner asked for 1-to-1; a broker shows a future's delta as 1.0 per contract, which is not one SPY share. Owner to confirm.)
7. **Greeks.** Per position, from `pricing.bs` at the scenario IV and time, times 100 per contract. Units are as `pricing.py` gives them: delta in shares, gamma in shares per $1, theta in $ per calendar day, vega in $ per vol point. A hedge leg has only delta. (**Proposed**)

### Known limits, stated in the output

- `pricing.bs` is European. Scenarios push legs deep in the money, where early exercise matters most (integrity.md item 2). Legs past a delta of 0.9 in absolute value are flagged until item 2 is measured. 0.9 is a placeholder, not a measurement. (**Proposed**)
- 1pm-close expiries still end at 16:00 while A-003's pricing-clock half stays deferred. Only those expiries' last day or two are affected.
- The smile shape is in question under stress. On the 2026-11-05 chain (VIX 28) the fit ran long same-sign residuals from 11-12 out, though its RMS stayed inside the quote band (integrity.md item 4, one chain). The sliding smile inherits that misfit as a leg moves along the curve.
- The time roll is only as fine as the term structure. When the drop rule removes expiries (A-015), the sessions between survivors are interpolated across the gap.

## Scope

In: one snapshot at a time (newest by default, or a named one, like every other command); option legs and SPY or NES hedge legs; a spot × date grid at a chosen IV shift; paths read from a file; a terminal command; CSV output.

Out: a UI (its own change record next, calling this engine); the chooser's search and ranking; option hedges; quotes for futures (the owner supplies NES fill prices); American pricing; any forecast of spot or IV.

### Inputs and output (Proposed)

- `python app.py scenario <position.csv> [snapshot]` prints, for a default grid, P&L and Greeks across spot (±3 expected moves of the front expiry, in 0.5-move steps) and dates (today, each expiry in the position, and the last expiry minus one session), at zero IV shift.
- `python app.py scenario <position.csv> --path <path.csv>` prints P&L along the path.
- Position CSV: `kind,expiry,strike,right,qty,price`, where `kind` is `option`, `shares` or `nes`; `price` is the fill for hedge legs and blank for options. Path CSV: `date,spot,iv_shift,kind,qty,price`, with the last three blank on rows without a trade.
- Output goes to `data/scenario/<snapshot>/<position name>/grid.csv` (and `path.csv`), with a `*_COLS` list.
- Not part of `cmd_daily()`: it runs on demand.

## Acceptance criteria

- **AC-1** At the snapshot's own spot and time, with zero shift, the position's P&L is 0 and each leg's model value equals Black-Scholes at vol.py's IV for that strike.
- **AC-2** At the start, each option leg's Greeks equal `contracts.csv`'s Greeks for that strike (the same right), times quantity and 100. The in-the-money side matches through parity: same gamma and vega, delta differing by 1.
- **AC-3** Sliding smile: with spot moved by `x`, a leg's IV equals the fitted curve at `ln(K/F')` plus its start residual. A leg pushed outside the fitted range holds the edge value and is flagged. An expiry without a fit uses sticky strike and is flagged.
- **AC-4** Time roll: at a date `s` sessions ahead, an expiry's remaining total variance equals its total today minus the interpolated total at `s`. A date across a weekend with no session in it leaves remaining variance unchanged. A negative remainder, or an expiry dropped from the term structure, is flagged and falls back to constant IV.
- **AC-5** A leg on or past its expiry is worth intrinsic at the point's spot, with zero Greeks.
- **AC-6** A shift of +0.01 vol points changes position value by vega × 0.01, to first order (relative error under 1%).
- **AC-7** A share leg adds `qty × (S' - S)` to P&L and `qty` to delta, and nothing else.
- **AC-8** Two paths ending at the same point give the same P&L when they hold no trades. With trades they differ, by exactly the trades' P&L.
- **AC-9** Every value and P&L carries a low and high from the IV band, and low ≤ mid ≤ high.
- **AC-10** Entry at mid and at the far side are both reported. For a long leg the far-side cost is never below the mid cost.
- **AC-11** Time is tested at an EDT and an EST snapshot, and across a 1pm close (Conventions).
- **AC-12** `python app.py scenario` works through `app.py`, with its docstring, the README's "Running it" list and the Commands table in AGENTS.md updated. Tests are offline, in temporary directories, and never read the real `data/`.
- **AC-13** An NES leg of `n` contracts filled at `P` with SPY at `S` carries `n × 0.50 × P / S` shares of delta, and its P&L at `S'` is that delta times `(S' - S)`. With the S&P 500 at ten times SPY, one contract reads 5 shares.

## Affected areas

- New: `screener/scenario.py` with `cmd_scenario()` and a long docstring in the house style, and `tests/test_scenario.py`.
- Changed: `vol.py` exposes the time-to-expiry calculation as one function that `one_expiry` and the engine both call (no behavior change). `app.py` gains the command.
- Read only: `data/chains/`, `data/iv/`, `data/surface/`, `data/term/`, via `surface.smile_basis`, `term.load` and `term.constant_maturity`.
- Docs: the NES multiplier and any other new `CONFIG` constant get a comment beside it; concepts.md explains any output column that needs it; `data/README.md` and the Data table in architecture.md gain `data/scenario/`; the SCEN rows move to Intended as each is verified.

Checked against the code on 2026-11-09, so the build can rely on them: `points.csv` `moneyness` is `ln(K/F)` (`surface.py`), and `residual` is our IV minus the fit; `fits.csv` carries `forward`, `m`, `s`, `c0`-`c4`; `expiries.csv` carries `forward`; `term.load(snapshot)` returns rows with `sessions`, `T` and `total_var`, and `term.constant_maturity(rows, sessions)` returns None outside the chain, which is why the origin must be added; `prices.session_close(d)` gives the close time; `ledger.snapshot_spot(name)` reads `run.json`.

## Verification plan

Offline unit tests on a synthetic chain written to a temporary directory: a flat 12% smile for the arithmetic cases, and a fitted curve with known coefficients for rule 1. Each acceptance criterion maps to at least one test, named as a sentence. Then manual runs on two real snapshots, checking that AC-1 and AC-2 hold on real data: a calm intraday chain, and `2026-11-05_1633`, the stress chain, where expiries were dropped from the term structure and the fit is in question. Record the results in the Commands table.

## Tasks

Start here in a new session: read AGENTS.md and docs/status.md, then this record top to bottom. Ask the owner the one open item (NES) first if it is still unticked; everything else is settled. Leave the work uncommitted (AGENTS.md, Git). Tick each task as it lands and note here where you stopped.

- [x] Owner answers the four rule questions (2026-11-06): sliding smile, roll along the term structure, entry at mid; futures as NES contracts, conversion to confirm
- [ ] Owner confirms the NES conversion (rule 6, AC-13)
- [ ] Move time to expiry into one `vol.py` function used by `one_expiry`; existing tests still pass (AC-11)
- [ ] Load a snapshot: legs, quotes, forwards, IVs, fits and fitted ranges, term totals (AC-1, AC-2)
- [ ] Price a point: forward shift, sliding smile, term roll, IV shift, expiry and intrinsic (AC-3, AC-4, AC-5, AC-6)
- [ ] Hedge legs (shares and NES) and paths (AC-7, AC-8, AC-13)
- [ ] Error bars from the IV band; entry at mid and far side (AC-9, AC-10)
- [ ] `cmd_scenario`, CSV output, `app.py`, README, AGENTS.md Commands (AC-12)
- [ ] Manual runs on a calm snapshot and on `2026-11-05_1633`; record evidence here; fold the behaviors into specs/scenario.md as Intended

## Verification evidence

None yet.

## Notes and decisions

- 2026-11-06: record created. The owner chose the engine before the UI and asked that it build on the existing surface work.
- 2026-11-06: rules answered: the smile slides along the fitted curve, expiries roll along the term structure, entry at mid. Hedges use NES; the owner expected 1-to-1, but $0.50 per S&P 500 point is about 5 SPY shares per contract, so the engine converts from the fill price. State moved to `accepted`; the conversion waits on the owner's confirmation and touches only AC-13.
