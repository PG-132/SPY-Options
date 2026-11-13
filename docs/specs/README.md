# Specs

What each part of the screener does, one behavior per ID. Specs describe current intended behavior. They don't certify that the code matches; the tests and the owner do.

## Areas

| Area | File | Purpose |
| --- | --- | --- |
| COLLECT | [collect.md](collect.md) | Chain snapshots from Webull: what is asked for, what is stored |
| VOL | [vol.md](vol.md) | Pricing math, the forward, IVs and bands, the clocks and the exchange calendar, the variance-swap rate |
| SURF | [surface.md](surface.md) | Readable and tradeable gates, the smile fit, residuals, edges, forward cost |
| TERM | [term.md](term.md) | Forward variance between expiries, constant maturity, no-arbitrage, the drop rule |
| CTX | [context.md](context.md) | Each window against the rest of the chain and its neighbours; the level against VIX |
| LEDG | [ledger.md](ledger.md) | Cross-snapshot record: history views, repricing, settlement, the band rule |
| PRICE | [prices.md](prices.md) | Daily closes and their cache; implied against realized by month |
| APP | [app.md](app.md) | The command line and the daily pipeline |
| CHOOSE | [choose.md](choose.md) | The structure chooser from the README. Not built |
| SCEN | [scenario.md](scenario.md) | Value, Greeks and P&L of a position under hypothetical spot, IV, dates and paths. Built 2026-11-09 |

## Status legend

| Status | Meaning |
| --- | --- |
| Intended | Confirmed as how it should work. Evidence is the owner's own words: a docs entry, a commit message, or "user, YYYY-MM-DD" |
| Observed | Seen in code or tests; not yet confirmed as intended |
| Proposed | Suggested; not built and not approved |
| Gap | Known to be missing or broken compared with intent |
| Removed | Retired, with the date. The ID is kept |

Where the owner wrote down the reason for a behavior (in docs/measurements.md, docs/integrity.md, docs/concepts.md, or a commit message), it is marked **Intended** with that as evidence. That reading is itself assumption A-012 in [../assumptions.md](../assumptions.md).

## IDs

`AREA-NNN`, for example `VOL-004`. Numbers are assigned in order within an area and never reused. A retired behavior stays in its table as **Removed** with the date.

An area file can split when it passes about 300 lines or starts covering unrelated capabilities.
