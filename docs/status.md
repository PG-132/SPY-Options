# Status

As of 2026-11-06

## Current state

The measuring pipeline is built and in daily use: snap, iv, surface, term, context and ledger run as `python app.py daily` at about 15:45 ET, with history, prices and vrp alongside. The latest work (2026-11-01 to 11-04) made the ledger record the strike band each window was priced under, graded how resolved each window's chain was (`edge_margin`, `spans_dropped`), measured roll-down off the older curve, and refused to cache unfinished price bars. The structure chooser the README describes is not built; the scenario engine it will build on is proposed ([changes/2026-11-06-scenario-engine.md](changes/2026-11-06-scenario-engine.md)). Two paper trades are closed (Sep-25 long straddle, Oct-30 short straddle). This knowledge base was added on 2026-11-04; its open questions are in [assumptions.md](assumptions.md).

## Completed

- Pipeline modules and 256 offline tests: `python -m unittest discover tests` passed on 2026-11-04 (Python 3.13.7).
- 1pm-close snapshots handled on 2026-11-05: `context.session_remaining` measures to 13:00 at the half-day weight, and `collect.market_open` ends at 13:00 on those days (CTX-003, COLLECT-011). 263 tests passed (Python 3.14.3); the six new half-day tests fail against the previous code.
- Knowledge base set up on 2026-11-04: `AGENTS.md`, `CLAUDE.md`, this file, [assumptions.md](assumptions.md), [context.md](context.md), [architecture.md](architecture.md), [specs/](specs/README.md), [changes/](changes/2026-11-04-choosing.md).
- Exchange calendar checked on 2026-11-04: `vol.HOLIDAYS` and `vol.HALF_DAYS` match NYSE's list for 2026 and 2027 exactly. **Sourced:** [NYSE Group Announces 2026, 2027 and 2028 Holiday and Early Closings Calendar](https://ir.theice.com/press/news-details/2025/NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar/default.aspx), released 2025-12-23, accessed 2026-11-04. Early closes are 1:00pm ET, 1:15pm for eligible options.

## Verification limits

- `snap`, `plan`, `daily`, `prices` and `vrp` were not run: the Webull SDK and `yfinance` aren't installed on the setup machine, and `data/` isn't in the repository.
- The specs were written from module docstrings, CONFIG blocks, test names and selected function bodies. Coverage per file is in [architecture.md](architecture.md) "Inspection coverage".
- The window figures in the 2026-11-02 measurements.md entry are arithmetic on a published 4-row level table, not a measurement on windows.
- The 1pm-close handling (2026-11-05) is tested offline only. Its first live check is the 2026-11-27 12:45 snapshot: its `session_remaining` in `data/context/` should read about 0.036, and `snap` should give no market-closed warning.

## Behaviors to confirm

All of them are in [assumptions.md](assumptions.md). Most consequential first: A-012 (how intent was read), and A-003 (1pm-close expiries priced to 16:00; narrowed on 2026-11-05 and deferred by the owner). The corrections an agent made are A-010, A-011, A-013 and A-014.

## Open questions

- Everything in [assumptions.md](assumptions.md).
- Open risks the owner already tracks: [integrity.md](integrity.md) items 2 (European math on American options), 3 (Webull is not an independent check) and 4 (the fit is untested outside a calm market).

## Next actions

Not permission to act; do these when asked. In order: the owner works down this list one session per item.

1. Build the scenario engine ([changes/2026-11-06-scenario-engine.md](changes/2026-11-06-scenario-engine.md), accepted; the task checklist is the handoff). One owner answer is pending and touches only AC-13: NES converts at about 5 SPY shares per contract, not 1.
2. Owner runs `python app.py daily` at 12:45 ET, not 15:45, on 2026-11-27 and 2026-12-24 (13:00 closes; see [context.md](context.md) Constraints).
3. Repeat the residual sign-flip test on an intraday chain while VIX stays high. The first reading, on the 2026-11-05 closing chain, showed long same-sign runs from 11-12 out ([integrity.md](integrity.md) item 4).
4. Re-run the band-shortfall check on a month of dailies under one band, as the 2026-11-02 measurements.md entry plans. 12/6 has been the band since 2026-10-20, so a month exists from about 11-20.
5. UI: its own change record once the engine is built, calling the engine for every number. First decision: Python's built-in web server with one page, or Streamlit or Dash, which would add a dependency (A-008).
6. Chooser, view 1 (long premium): settle the open questions the engine leaves in [changes/2026-11-04-choosing.md](changes/2026-11-04-choosing.md), then write its acceptance criteria. The delta-hedged paper trade needs no build: hedges are logged by hand ([trades/README.md](../trades/README.md)).
7. Bound the European-vs-American gap with a binomial tree on real strikes ([integrity.md](integrity.md) item 2). The engine's 0.9-delta flag is a placeholder until then.
8. Measure the 6/3 shortfall on windows directly: take a raw 12/6 chain, truncate it to 6/3, re-integrate and compare windows. Replaces arithmetic on a level table (A-001).
9. Owner works through [assumptions.md](assumptions.md): A-015 and A-012 first (Medium), then A-010, A-011, A-013 and A-014 (one "keep all" closes four), then A-008, A-005, A-002, A-006, A-007, A-009. A-003's pricing-clock half stays deferred by the owner; it affects only a 1pm-close expiry's last day or two.
10. Before 2027 ends, extend `vol.HOLIDAYS` and `vol.HALF_DAYS` from NYSE's calendar (2028 is already published).

## History

- 2026-11-06: scenario engine accepted ([changes/2026-11-06-scenario-engine.md](changes/2026-11-06-scenario-engine.md), [specs/scenario.md](specs/scenario.md), SCEN-001 to 011). The owner chose it before the UI, built on the surface fit and the term structure: the smile slides along the fitted curve, expiries roll along today's term structure in sessions, entry at mid. Hedges use E-nano S&P 500 futures (NES); the owner expected 1 contract to equal 1 SPY share of delta, but at $0.50 per index point it is about 5, so the engine converts from the fill price (awaiting the owner's confirmation; trades/README.md says to log the fill). The chooser now builds on the engine. Next actions reordered into the queue the owner works down one item at a time; A-003's deferred half moved from that queue's second place to the assumptions item.
- 2026-11-05: first chain under stress, `2026-11-05_1633` (SPY −4.41% close to close, VIX 16.61 to 28.18), snapped at 16:33 after the close from the 16:13-16:15 options-close quotes; run.json carries the market-closed and stale-quote warnings. The sign-flip test read for the first time (integrity.md item 4: long same-sign runs from 11-12 out, RMS still inside the quote band). The drop rule left three windows and no 30-day rate (A-015). Replaces next action 7, which waited for this chain.
- 2026-11-05: A-004 resolved: the chooser stays a goal. The owner states the exposure wanted across hypothetical spot outcomes; fit is the distance to it, and the closest match is returned with its miss shown. Views come in order: long premium, short premium, calendars and diagonals, direction. Undefined-risk structures stay as candidates. Hedges are SPY shares or futures logged by hand in the trade CSV, not options for now, and the chooser gives no hedge signals. CHOOSE-001 to 007 and the change record rewritten; the ranking rules from the owner's September plan doc added to context.md, which had none of the chat-era chooser decisions. Replaces next action 3 (chooser or delta-hedged trade: both, the trade by hand).
- 2026-11-05: A-003 partly resolved, split in two. The snapshot half is resolved: the owner chose to snap at 12:45 ET on 1pm-close days rather than skip them, and `context.session_remaining` now measures to 13:00 at the half-day weight (measured to 16:00 it read half a session left at 12:45). `collect.market_open` ends at 13:00 on those days so a 15:45 run warns. CTX-003 moved from Gap to Intended; CTX-002 and COLLECT-011 updated. The pricing-clock half stays open as A-003, deferred by the owner. Found while sizing it: the bias stays in that expiry's annualized IVs and never reaches the windows, because `term.py` rebuilds total variance with the same T (specs/vol.md "Gaps"). This replaces A-003's earlier framing, which made it the most consequential open item.

- 2026-11-04: A-001 resolved: yes, the explanation was wrong. `ledger.py` and the 2026-11-02 measurements.md entry now say the shortfall shrinks with tenor (0.88, 0.71, 0.25 vol points on the three windows) and name the mechanism: the band is sqrt(T)-scaled, the listed strike range is not. The 6/3 exclusion itself is unchanged. Band history corrected in `collect.py` and context.md (6/3 through 10-13, one 20/10 snapshot on 10-15, 12/6 from 10-20), the stale `(1-30 days)` in `collect.anchor_iv` fixed, and the owner's git workflow added to AGENTS.md.
- 2026-11-04: knowledge base and spec-driven workflow added on branch `sdd` after merging `main` at `3506ff6`. Stale text corrected in the `collect.py`, `surface.py`, `vrp.py` and `app.py` docstrings, a `prices.py` comment, concepts.md, integrity.md item 1 and data/README.md (A-010, A-011, A-013, A-014). No logic changed. Proposed to `main` as a pull request from `sdd`.
- 2026-11-04: `3506ff6` (owner): the band shortfall is stated as surviving differencing; questioned in A-001.
- 2026-11-03: `1716f0e`, `a99a4c3` (owner): ledger records the band per window; firm/marginal label replaced by the raw margin.
- 2026-11-02: `932dd3b` (owner): `edge_margin` grades how resolved each window's chain was.
- 2026-11-01: `a4e9847`, `d37a07a` (owner): roll-down measured off the older curve; unfinished bars refused at the cache.
- Earlier work is in `git log` and the dated entries of [measurements.md](measurements.md).
