# Context

## Origin

Set up on 2026-11-04 in the Claude desktop app (Code tab), working in a local clone of this repository on the `sdd` branch, after merging `main` at `3506ff6`. The knowledge base was built from the repository alone: code, tests, docs, trade logs and git history. The owner's earlier Claude conversations were not available and were not used, so anything decided only in chat is missing until the owner adds it.

## Goals

From [README.md](../README.md), labeled **Decided** (the owner wrote it):

- **Measure.** Capture the SPY option chain, solve our own IVs from the quotes, and reduce them to comparable numbers: at-the-money level per expiry, skew by delta, term structure per trading session. Distance is counted in expected moves and delta, time in sessions. Long-run context comes from published CBOE series; our own record accumulates from now on.
- **Choose.** Given the exposure the owner wants across hypothetical spot outcomes, find the option structure that comes closest. Not built yet; defined by the owner on 2026-11-05 (A-004). See [changes/2026-11-04-choosing.md](changes/2026-11-04-choosing.md) and [specs/choose.md](specs/choose.md).
- **Learn from paper trades.** Each trade in [trades/](../trades/README.md) is run to watch how the Greeks behave over a full cycle, not as a performance record.

## Scope

- In: SPY options, market data only, offline analysis, paper trades logged by hand.
- Out: forecasting, ranking structures by expected profit, placing orders, other underlyings. Priced at their own IVs, every structure is a fair bet; "rich" and "cheap" always mean against the rest of today's surface, never against a prediction. (**Decided**, README.md and docs/concepts.md)

## Constraints

- Data comes from Webull (option chain, needs the OPRA subscription) and Yahoo via `yfinance` (daily closes). Webull gives no long price history, so realized volatility comes from Yahoo. (**Observed**, `screener/prices.py`)
- Snapshots must be taken during market hours; after the close bid/ask go stale. The daily routine runs at about 15:45 ET. (**Decided**, README.md, `app.py`)
- On the 1pm-close days in `vol.HALF_DAYS` (2026-11-27, 2026-12-24, 2027-11-26) the routine runs at 12:45 ET instead. The owner remembers this; `snap` warns if a run lands after 13:00. (**Decided**, user 2026-11-05)
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
| 2026-09-18 | The chooser ranks by fit first and execution cost (bid-ask across all legs as a share of premium) a close second; expected P&L and theta per unit of gamma appear only as context, never as a sort key | Priced at their own IVs every structure is a fair bet, and theta/gamma reduces to ½σ²S², which is IV again | the owner's plan doc "SPY Options Screener Plan" (Claude Docs, 2026-09-17); [specs/choose.md](specs/choose.md) CHOOSE-002 |
| 2026-09-24 | Count time to expiry in actual hours to the close, not whole days | Whole days put the 1-day expiry 1.3 vol points off | measurements.md "Whole days lie about short-dated options" |
| 2026-09-24 | Read IVs from the out-of-the-money side only | Tighter quotes; avoids American early-exercise premium | `screener/vol.py` docstring |
| 2026-10-07 | Smile shape: hyperbola + quadratic + cubic in IV, weighted 1/band^2 | Cubic and SVI both failed the sign-flip test | measurements.md "Two smile shapes that failed" |
| 2026-10-10 | Forward from parity: gate pairs on width asymmetry, average the tightest survivors 1/width^2 | Per-pair forwards slope with asymmetry, a bias averaging can't cure | measurements.md "Where the forward comes from" |
| 2026-10-15 | Collection band widened from 6/3 to 12 moves below, 6 above; one 20/10 snapshot on 10-15, 12/6 from 10-20 | 6/3 understated the variance-swap LEVEL by 0.5 to 1.1 points, most of it at the short end | measurements.md "Widening the collection band"; commit `d10473b` |
| 2026-10-16 | Strip the term structure from the variance-swap rate rather than the ATM level | Same quantity as VIX; ATM runs about 0.80 of it | measurements.md "Wiring the integral into the time axis" |
| 2026-10-20 | `max_dte` raised from 30 to 37 | The chain must bracket 30 days, as VIX's 23-37 day window does | `screener/collect.py` CONFIG; commit `67fe417` |
| 2026-10-30 | A 1pm close counts 0.5 session on the variance clock | Measured on 33 day-after-Thanksgiving sessions | measurements.md "What a 1pm close is worth" |
| 2026-11-01 | Never cache a bar for a session that hasn't closed; ET offset from zoneinfo | A partial bar understated range variance 7.3x; the EST switch would have broken the guard | measurements.md "What a partial bar costs" |
| 2026-11-03 | Every ledger window records the band it was priced under; 6/3 rows stay out of pooled settlement stats and the mover table never compares across a band change | Rates from different bands are different quantities | commit `1716f0e`; [specs/ledger.md](specs/ledger.md) |
| 2026-11-05 | On 1pm-close days, snap at 12:45 ET; the snapshot's leftover session runs to 13:00 and counts at the half-day weight | At 15:45 the quotes are 2¾ hours stale. Measured to 16:00, a 12:45 snapshot would read half a session left and its front window about 17% low | [specs/context.md](specs/context.md) CTX-003 |
| 2026-11-05 | Defer the pricing clock on 1pm-close expiries as a separate, lower-priority decision; it stays at 16:00 until then | The bias stays in that expiry's annualized IVs and never reaches the windows | A-003 in [assumptions.md](assumptions.md); [specs/vol.md](specs/vol.md) "Gaps" |
| 2026-11-05 | The chooser takes the exposure the owner wants across hypothetical spot outcomes; fit is the distance to it, and the closest match is returned with its miss shown | "I want the most accurate exposure for what I'm betting"; the chain can't always reproduce the target exactly | [changes/2026-11-04-choosing.md](changes/2026-11-04-choosing.md); CHOOSE-001, 002, 004 |
| 2026-11-05 | Chooser views in order: long premium, short premium, calendars and diagonals, direction. Undefined-risk structures stay as candidates | Calendars need both long and short legs; direction is the easiest to track; the owner won't trade undefined risk | CHOOSE-005, CHOOSE-006 |
| 2026-11-06 | Scenario engine before the UI, built on the surface fit and term structure: the smile slides along the fitted curve as spot moves, each expiry rolls along today's term structure in sessions, entry at mid | "How else would you have the comparison"; the owner's simulated account shows no change over weekends and holidays | [changes/2026-11-06-scenario-engine.md](changes/2026-11-06-scenario-engine.md); SCEN-004, 005, 007 |
| 2026-11-11 | Scenario engine: each strike keeps its IV as spot moves (replacing the 2026-11-06 slide), and every point shows three P&Ls under umbrella IV responses (none, moderate, large), generous on purpose and narrowed as tail events come; cases are named for the IV change since which one hurts depends on the position; the sqrt(30/days) expiry scaling is provisional; the horizon and the days to expiry are separate inputs; VIX history is read loosely | On all five large moves held, the strike's IV went opposite to the slide; nobody knows the response exactly, only that drops raise IV more than rallies lower it | [changes/2026-11-11-iv-response.md](changes/2026-11-11-iv-response.md) (proposed, not built); measurements.md 2026-11-11 |
| 2026-11-13 | Scenario engine: on a later date the forward keeps today's carry rate and rolls toward spot every calendar day, so weekends cost carry though they cost no variance (A-016); A-017's three readings stay as built for now | "they do indeed still cost carry so we'll use that"; "lets leave it like that for now" | [specs/scenario.md](specs/scenario.md) SCEN-003; [assumptions.md](assumptions.md) A-017 |
| 2026-11-12 | The IV response stays as built: large rallies that take IV to its floor stay flagged, not capped; the rates are discretionary and are adjusted through the engine's use, not refitted to every reading | "the figures are discretionary and that's alright"; the measured changes include the engine's own time roll, which the owner did not want to keep folding into the responses | [changes/2026-11-11-iv-response.md](changes/2026-11-11-iv-response.md) Notes |
| 2026-11-12 | IV response band: up-move rates widened to -1 and -1.5 per 1% so they sit above both measured rallies; the no-change case is named `none`; time passing and the IV on a date stay separate inputs; typing an IV directly ("IV will be 25% on Friday") comes later as its own change, with the umbrella rates as the default until then | "umbrella figures that sit above measured rallies"; "keep the distinction that time passing and iv changing with time are separate inputs"; "later in development i should be able to manually input my own iv" | [changes/2026-11-11-iv-response.md](changes/2026-11-11-iv-response.md) sections 1, 2 and 8 |
| 2026-11-09 | An NES future counts as `0.50 × fill / SPY spot` SPY shares of delta per contract, about 5, not 1 | NES pays $0.50 per S&P 500 point and SPY is about a tenth of the index; owner: "Yes, about 5" | [specs/scenario.md](specs/scenario.md) SCEN-009 |
| 2026-11-05 | Paper trades are delta-hedged with SPY shares or futures, logged by hand in a column of the trade's daily CSV; the owner decides when to hedge and the chooser gives no hedge signals | Logging by hand works for now; automating it would need `webull.trade` | [trades/README.md](../trades/README.md); CHOOSE-007 |

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
| Skipping the snapshot on 1pm-close days | Loses the day's data point when a 12:45 snap and a small fix keep it | 2026-11-05 | [specs/context.md](specs/context.md) CTX-003 | the 12:45 snap proves hard to keep |
| Hedging with options (the plan doc's hedge finder) | Adds a layer of complication and changes the trade's structure; shares or futures do the job | 2026-11-05 | [changes/2026-11-04-choosing.md](changes/2026-11-04-choosing.md) "Scope" | the owner gets to option hedges |
| Hedge-timing signals from the chooser (e.g. delta climbing inside ±1 expected move) | The owner decides when to hedge and can read the exposures directly | 2026-11-05 | CHOOSE-007 | the owner asks for them |
| The smile sliding along the fitted curve as spot moves (scenario rule 1, sticky moneyness) | On all five large moves held, each strike near the old spot moved opposite to its prediction; it showed a short straddle making money on a 1% drop | 2026-11-11 (out of the code 2026-11-12) | measurements.md 2026-11-11; [changes/2026-11-11-iv-response.md](changes/2026-11-11-iv-response.md) | fixed-strike readings on new moves start following the slide |
| Freshness by fixed age ("four days is fresh") | Breaks on the first session after a long weekend | before 2026-11-01 | `screener/prices.py` docstring | never |

## Proposals and assumptions

Open guesses about intent live in [assumptions.md](assumptions.md), not here.

## Requirements

See [specs/README.md](specs/README.md).
