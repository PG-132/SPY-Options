# Context

## Origin

Set up on 2026-11-04 in the Claude desktop app (Code tab), working in a local clone of this repository on the `sdd` branch, after merging `main` at `3506ff6`. The knowledge base was built from the repository alone: code, tests, docs, trade logs and git history. The owner's earlier Claude conversations were not available and were not used, so anything decided only in chat is missing until the owner adds it.

## Goals

From [README.md](../README.md), labeled **Decided** (the owner wrote it):

- **Measure.** Capture the SPY option chain, solve our own IVs from the quotes, and reduce them to comparable numbers: at-the-money level per expiry, skew by delta, term structure per trading session. Distance is counted in expected moves and delta, time in sessions. Long-run context comes from published CBOE series; our own record accumulates from now on.
- **Choose.** Given a view and risk limits, find the option structure that fits best. Not built yet; see [changes/2026-11-04-choosing.md](changes/2026-11-04-choosing.md) and A-004 in [assumptions.md](assumptions.md).
- **Learn from paper trades.** Each trade in [trades/](../trades/README.md) is run to watch how the Greeks behave over a full cycle, not as a performance record.

## Scope

- In: SPY options, market data only, offline analysis, paper trades logged by hand.
- Out: forecasting, ranking structures by expected profit, placing orders, other underlyings. Priced at their own IVs, every structure is a fair bet; "rich" and "cheap" always mean against the rest of today's surface, never against a prediction. (**Decided**, README.md and docs/concepts.md)

## Constraints

- Data comes from Webull (option chain, needs the OPRA subscription) and Yahoo via `yfinance` (daily closes). Webull gives no long price history, so realized volatility comes from Yahoo. (**Observed**, `screener/prices.py`)
- Snapshots must be taken during market hours; after 16:00 ET bid/ask go stale. The daily routine runs at about 15:45 ET. (**Decided**, README.md, `app.py`)
- Own data starts 2026-09-24. Every constant was set on a calm market (ATM IV near 13%); behavior in a selloff is untested. (**Observed**, docs/integrity.md item 4)

## Preferences

From the owner's docs and code, labeled **Observed** until confirmed:

- Every number needs an error bar; a reading without one is not a result.
- Constants are measured, never chosen, and every measurement gets a dated entry in [measurements.md](measurements.md).
- Report problems, never silently repair them: arbitrage, stale bars and thin expiries are flagged, not patched.
- Long explanatory docstrings that give the reasoning, written as prose.
- Docs kept apart by job: measurements (a date and a number), integrity (a failure mode and a check), concepts (mechanisms that stay true when numbers change).

## Decisions

All **Decided** by the owner, as recorded in commits and docs. Detail lives in the linked entry.

| Date | Decision | Why | Where |
| --- | --- | --- | --- |
| 2026-09-24 | Count time to expiry in actual hours to the close, not whole days | Whole days put the 1-day expiry 1.3 vol points off | measurements.md "Whole days lie about short-dated options" |
| 2026-09-24 | Read IVs from the out-of-the-money side only | Tighter quotes; avoids American early-exercise premium | `screener/vol.py` docstring |
| 2026-10-07 | Smile shape: hyperbola + quadratic + cubic in IV, weighted 1/band^2 | Cubic and SVI both failed the sign-flip test | measurements.md "Two smile shapes that failed" |
| 2026-10-10 | Forward from parity: gate pairs on width asymmetry, average the tightest survivors 1/width^2 | Per-pair forwards slope with asymmetry, a bias averaging can't cure | measurements.md "Where the forward comes from" |
| 2026-10-15 | Collection band widened from 6/3 to 12 moves below, 6 above | 6/3 understated the variance-swap rate by 0.5 to 1.1 points | measurements.md "Widening the collection band"; commit `d10473b` |
| 2026-10-16 | Strip the term structure from the variance-swap rate rather than the ATM level | Same quantity as VIX; ATM runs about 0.80 of it | measurements.md "Wiring the integral into the time axis" |
| 2026-10-20 | `max_dte` raised from 30 to 37 | The chain must bracket 30 days, as VIX's 23-37 day window does | `screener/collect.py` CONFIG; commit `67fe417` |
| 2026-10-30 | A 1pm close counts 0.5 session on the variance clock | Measured on 33 day-after-Thanksgiving sessions | measurements.md "What a 1pm close is worth" |
| 2026-11-01 | Never cache a bar for a session that hasn't closed; ET offset from zoneinfo | A partial bar understated range variance 7.3x; the EST switch would have broken the guard | measurements.md "What a partial bar costs" |
| 2026-11-03 | Every ledger window records the band it was priced under; 6/3 rows stay out of pooled settlement stats and the mover table never compares across a band change | Rates from different bands are different quantities | commit `1716f0e`; [specs/ledger.md](specs/ledger.md) |

## Rejected approaches

Each is written up in full in the linked entry; this is the index.

| Approach | Why rejected | Date | Where | Reconsider if |
| --- | --- | --- | --- | --- |
| Cubic smile in ln(K/F) | Can't make straight wings; reported 460 tradeable edges that didn't exist | 2026-09-24 | measurements.md "Two smile shapes that failed" | never, as a smile shape |
| SVI fit | Fitting failure from a five-parameter search; the chain does admit SVI | 2026-09-24, re-measured 2026-10-07 | same entry | a robust SVI fitter is wanted for arbitrage-free extrapolation |
| Put-call parity by regression | Returned a -25% implied rate: American puts bend the line | 2026-09 | measurements.md "Known trap: put-call parity by regression" | never |
| Forward from the single closest strike pair | Pairs disagree by up to 31 cents as a slope, not scatter | 2026-10-10 | measurements.md "Where the forward comes from" | never |
| Regressing the forward bias out | Fitted slope ranged 0.11 to 1.93 across one chain | 2026-10-10 | docs/integrity.md "Handled" | the bias turns out stable across chains |
| Widening each point's band by its own IV sensitivity to the forward | Too strict in the wings, too lenient at the edges | 2026-10-11 | concepts.md "Residual, edge, and the forward's cost" | never |
| Whole-day time to expiry | 1.3 vol points off at 1 day | 2026-09-24 | measurements.md | never |
| Half-day weight by clock time (0.538) or rounded to 0 | Clock time is right for the wrong reason; 0 is the worse error and divides by zero | 2026-10-30 | measurements.md "What a 1pm close is worth" | Christmas Eve or July 3 data shows a different weight |
| Firm/marginal label on ledger windows | The split was void once narrow-band rows were refused; the raw margin is printed instead | 2026-11-03 | commit `a99a4c3`; measurements.md 2026-11-02 entry | a month of dailies under one band |
| Freshness by fixed age ("four days is fresh") | Breaks on the first session after a long weekend | before 2026-11-01 | `screener/prices.py` docstring | never |

## Proposals and assumptions

Open guesses about intent live in [assumptions.md](assumptions.md), not here.

## Requirements

See [specs/README.md](specs/README.md).
