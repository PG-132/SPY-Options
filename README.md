# spy-screener

A SPY options screener that:

**Measures.** Captures options chain, solves its own IVs from the quotes, reduces
them to numbers that can be compared such as at the money level for each expiry,
skew by delta, and term structure per trading session. Distance out of the money
is counted in expected moves and delta rather than %'s and time is counted in
sessions rather than calendar days. Long run context comes from published CBOE
series while personal data is recorded and logged from present onwards.

**Choosing.** Given a view and risk limits, finds the structure that fits best
given risk parameters.

This is not a forecaster. Priced at their own IVs, every structure is a fair bet
and only differ in shape of risk and not in edge. Nothing here ranks candidates
by expected profit, they rank by fit. Rich or cheap always means against the rest
of today's surface rather than against a prediction.

## Running it

Everything runs through `app.py`, from this folder:

    python app.py plan     which contracts a snapshot would pull (read-only)
    python app.py daily    snap, then every step that reads it, in order
    python app.py snap     take one chain snapshot, saved under data/chains/
    python app.py iv       solve our own IVs for the newest snapshot
    python app.py surface  fit a smile per expiry and score every point off it
    python app.py term     strip variance between expiries: the time axis
    python app.py context  which windows are priced differently from the rest
    python app.py history  the same surface seen from every snapshot so far
    python app.py ledger   every window ever priced, and what became of it
    python app.py prices   daily closes for SPY and the CBOE series, cached
    python app.py vrp      implied against realized, one claim per month

    python app.py scenario pos.csv [snapshot] [--shift N] [--sessions 1,5]
    python app.py scenario pos.csv [snapshot] --path path.csv
                           what a position does if spot, IV or the date
                           were different, under three IV responses to
                           the spot move: a what-if, never a forecast

With no command (VS Code's Run button), `app.py` runs `plan`.

`scenario` reads a position file, one leg per row:

    kind,expiry,strike,right,qty,price
    option,2026-12-04,735,C,1,
    option,2026-12-04,735,P,1,
    nes,,,,-1,7420

`kind` is `option`, `shares` or `nes`; `qty` is signed; `price` is the fill
for hedge legs; on an option it may log your fill, which is recorded but not
used, since entry is at mid. Option and NES quantities are whole
contracts; shares may be fractional. Start a row's kind with `#` to leave it
out; a row with anything in it but no kind is refused, not skipped. It prints P&L across spot (in expected
moves, with the percent beside them) and dates, and writes
`data/scenario/<snapshot>/<position>/`. Each strike keeps its IV as spot
moves; at every point the P&L comes three times, under no IV response, a
moderate one and a large one (vol points per 1% of SPY move at 30 days:
+1 and +2 on a drop, -1 and -1.5 on a rally, scaled by sqrt(30 / days
left)), and the report names which case is lowest and highest there.
`--sessions 1,5` adds the closes 1 and 5 sessions out to the dates. With
`--path`, a file of `date,spot,iv_shift,kind,qty,price` steps (the last three
only on a step with a hedge trade), it prints P&L along that path instead.
A path that passes an expiry needs a step dated on it: that is the price the
expiring legs settle at, and it refuses to guess one. `--shift` and `--sessions` are for the
grid; a path's shocks go in its `iv_shift` column and its dates in its own,
so either with `--path` is refused. A path is priced with no IV response. A number that doesn't parse, in either file, is refused rather than
read as zero. Every saved row carries `inputs`, a fingerprint of the legs and
the snapshot data: a grid and a path from the same inputs stay side by side,
and a run removes one priced from anything else. Each run also gets a `report`
id of its own. A save is all or nothing: if it fails, say because a result
is open in a spreadsheet, the last good set stays as it was.
The rules it prices by are in `screener/scenario.py`.

It needs `WEBULL_APP_KEY` and `WEBULL_APP_SECRET` in the environment, plus
Webull's OPRA subscription. Take snapshots during market hours: after the close
bid/ask go stale, and `snap` warns you. The close is 16:00 ET, but 13:00 on the
early closes (the day after Thanksgiving, Christmas Eve), so on those days snap
at 12:45.

## Layout

    app.py                the one entry point
    screener/collect.py   chain snapshots; the only file that talks to Webull
                          (market data only, so it can't place orders)
    screener/pricing.py   Black-Scholes in forward terms, and the IV solver
    screener/vol.py       our own IVs per snapshot: forward, bands, our Greeks
    screener/surface.py   the gates, the smile fit, and what sits off it
    screener/term.py      forward variance between expiries, constant maturity
    screener/context.py   every window against the rest of the chain and
                          against its neighbours; the level against VIX
    screener/history.py   the three ways of comparing one snapshot to another
    screener/ledger.py    the record across snapshots: what repriced, what
                          settled, and what it delivered
    screener/prices.py    daily closes from Yahoo; the only file that talks to it
    screener/vrp.py       implied against realized, monthly and non-overlapping
    screener/scenario.py  a position under hypothetical spot, IV, dates and
                          paths, on the snapshot's own smile and term structure
    tests/                offline tests with a fake Webull:
                          python -m unittest discover tests
    docs/concepts.md      the mechanisms, and what each output column means
    docs/measurements.md  what produced every constant in the code
    docs/integrity.md     what could still be wrong, and how we would know
    docs/status.md        where the project stands, next actions, history
    docs/assumptions.md   open questions about intent, answered by ID
    docs/context.md       goals, scope, decisions, rejected approaches
    docs/architecture.md  the pipeline, the data folders, inspection coverage
    docs/specs/           what each area does, one behavior per ID
    docs/changes/         one record per feature, with a task checklist
    trades/               paper trades, one folder each
    data/                 snapshots and everything derived from them; not in git

## Working with an agent

Open this folder in Claude Code or Codex. Codex loads `AGENTS.md`; Claude Code
loads `CLAUDE.md`, which imports it. For any other tool, start by reading
`AGENTS.md`. A new session needs nothing from an old one: the state of the
work lives in `docs/status.md`, and the open questions in `docs/assumptions.md`.

