# Status

As of 2026-11-04

## Current state

The measuring pipeline is built and in daily use: snap, iv, surface, term, context and ledger run as `python app.py daily` at about 15:45 ET, with history, prices and vrp alongside. The latest work (2026-11-01 to 11-04) made the ledger record the strike band each window was priced under, graded how resolved each window's chain was (`edge_margin`, `spans_dropped`), measured roll-down off the older curve, and refused to cache unfinished price bars. The structure chooser the README describes is not built. Two paper trades are closed (Sep-25 long straddle, Oct-30 short straddle). This knowledge base was added on 2026-11-04; its open questions are in [assumptions.md](assumptions.md).

## Completed

- Pipeline modules and 256 offline tests: `python -m unittest discover tests` passed on 2026-11-04 (Python 3.13.7).
- Knowledge base set up on 2026-11-04: `AGENTS.md`, `CLAUDE.md`, this file, [assumptions.md](assumptions.md), [context.md](context.md), [architecture.md](architecture.md), [specs/](specs/README.md), [changes/](changes/2026-11-04-choosing.md).
- Exchange calendar checked on 2026-11-04: `vol.HOLIDAYS` and `vol.HALF_DAYS` match NYSE's list for 2026 and 2027 exactly. **Sourced:** [NYSE Group Announces 2026, 2027 and 2028 Holiday and Early Closings Calendar](https://ir.theice.com/press/news-details/2025/NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar/default.aspx), released 2025-12-23, accessed 2026-11-04. Early closes are 1:00pm ET, 1:15pm for eligible options.

## Verification limits

- `snap`, `plan`, `daily`, `prices` and `vrp` were not run: the Webull SDK and `yfinance` aren't installed on the setup machine, and `data/` isn't in the repository.
- The specs were written from module docstrings, CONFIG blocks, test names and selected function bodies. Coverage per file is in [architecture.md](architecture.md) "Inspection coverage".
- The window figures in the 2026-11-02 measurements.md entry are arithmetic on a published 4-row level table, not a measurement on windows.

## Behaviors to confirm

All of them are in [assumptions.md](assumptions.md), most consequential first: A-003 (1pm-close expiries priced to 16:00), A-004 (the chooser), A-012 (how intent was read). The corrections an agent made are A-010, A-011, A-013 and A-014.

## Open questions

- Everything in [assumptions.md](assumptions.md).
- Open risks the owner already tracks: [integrity.md](integrity.md) items 2 (European math on American options), 3 (Webull is not an independent check) and 4 (the fit is untested outside a calm market).

## Next actions

Not permission to act; do these when asked.

1. Owner works through [assumptions.md](assumptions.md), starting with A-003: the 2026-11-27 expiry is already in the chain.
2. Owner decides whether the chooser ([changes/2026-11-04-choosing.md](changes/2026-11-04-choosing.md)) or the delta-hedged trade is the next build.
3. Re-run the band-shortfall check on a month of dailies under one band, as the 2026-11-02 measurements.md entry plans.
4. Measure the 6/3 shortfall on windows directly: take a raw 12/6 chain, truncate it to 6/3, re-integrate and compare windows. Replaces arithmetic on a level table (A-001).
5. Before 2027 ends, extend `vol.HOLIDAYS` and `vol.HALF_DAYS` from NYSE's calendar (2028 is already published).
6. When VIX is materially higher, capture a chain and re-run the residual sign-flip test (integrity.md item 4).

## History

- 2026-11-04: A-001 resolved: yes, the explanation was wrong. `ledger.py` and the 2026-11-02 measurements.md entry now say the shortfall shrinks with tenor (0.88, 0.71, 0.25 vol points on the three windows) and name the mechanism: the band is sqrt(T)-scaled, the listed strike range is not. The 6/3 exclusion itself is unchanged. Band history corrected in `collect.py` and context.md (6/3 through 10-13, one 20/10 snapshot on 10-15, 12/6 from 10-20), the stale `(1-30 days)` in `collect.anchor_iv` fixed, and the owner's git workflow added to AGENTS.md.
- 2026-11-04: knowledge base and spec-driven workflow added on branch `sdd` after merging `main` at `3506ff6`. Stale text corrected in the `collect.py`, `surface.py`, `vrp.py` and `app.py` docstrings, a `prices.py` comment, concepts.md, integrity.md item 1 and data/README.md (A-010, A-011, A-013, A-014). No logic changed. Proposed to `main` as a pull request from `sdd`.
- 2026-11-04: `3506ff6` (owner): the band shortfall is stated as surviving differencing; questioned in A-001.
- 2026-11-03: `1716f0e`, `a99a4c3` (owner): ledger records the band per window; firm/marginal label replaced by the raw margin.
- 2026-11-02: `932dd3b` (owner): `edge_margin` grades how resolved each window's chain was.
- 2026-11-01: `a4e9847`, `d37a07a` (owner): roll-down measured off the older curve; unfinished bars refused at the cache.
- Earlier work is in `git log` and the dated entries of [measurements.md](measurements.md).
