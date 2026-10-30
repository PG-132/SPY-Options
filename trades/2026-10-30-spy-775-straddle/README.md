# SPY 775 short straddle, expiring 2026-10-30

Second SIMULATED trade, and the mirror of the Sep-25 long: sell the same structure
and watch the same Greeks from the other side. Closed on the morning of expiry
rather than held through, so the last row is a settlement that was never collected.

*NO DELTA HEDGING, NO LEG ADJUSTMENT* - kept deliberately clean, which is the
thing the next experiment is meant to change.

## The trade

| | |
| --- | --- |
| Entered | 2026-10-05, SPY at 772.25 |
| Structure | 1 call + 1 put sold, strike 775, expiring 2026-10-30 |
| Credit | 20.05 per straddle, $2,005.00 total, $0.20 fees |
| IV sold | 12.47% at the money (call 12.49%, put 12.46%) |
| Break-evens | 754.95 and 795.05, so ±2.6% over 25 days |
| Daily bar | 0.786%, the move that eats one day of theta |
| Exit rule | written at entry: close if P&L reaches -$2,000 |

The thesis line was left blank at entry. The stated purpose was structural - watch
short gamma, short vega and positive theta evolve over a full cycle - not directional.

## Outcome

SPY spent the month inside the break-evens and the position accumulated almost
exactly what the premium implied. Through 10-29 the mark had decayed 20.05 to 9.50,
a paper gain of **+$1,055**, and 14 of the 19 logged sessions came in under the bar.

Then the last session. SPY opened at 761.38, fell to 750.36 intraday (-2.47%) and
closed at 755.72 (-1.77%). The mark went 9.50 to 19.28 in one day: **-$978, which
is 93% of everything the previous eighteen sessions had earned.**

| | |
| --- | --- |
| Realized over the hold | 11.70% |
| Implied sold | 12.47% |
| Ratio | 0.938 |
| Premium kept, settlement | 3.8% |
| Premium kept, theory (1 - rv/iv) | 6.2% |

The gap between 3.8% and 6.2% is the cost of not hedging. `1 - rv/iv` is the
expectation under continuous delta hedging; unhedged, the outcome is decided by the
terminal distance from the strike rather than by the path, and here the path ended
18.28 points below it on the single worst day of the hold.

**Settlement.** SPY closed at 755.72, so the call expired worthless and the put
finished 19.28 in the money: $1,928 against $2,005 received, **+$77 before fees**.
The put mid observed at the end of the day was 18.24, which implies a spot of
756.76 - a 16:15 print, the same drift the Sep-25 trade saw between the 16:00 close
and the broker's fill.

**The position was not actually held to that.** It was closed at market on the
morning of 10-30 with SPY near 760, at a mark of roughly 15.6, for about **+$444**.
Closing early was worth about $367 more than seeing it through - the only time in
either experiment that the early exit beat the settlement.

## Data notes

Three logged closes were midday prices rather than closes; the authoritative close
is in `spy_close` and what was originally written down is kept in `spy_logged`.
The 10-15 row is off by 1.30 points because the 12:33 chain snapshot price was
recorded as that day's close - the marks and Greeks on that row belong to 773.09,
not to the 771.79 the session actually closed at. 10-21 was missed entirely; its
close is backfilled from `data/prices/spy_ohlc.csv` and carries no mark.

On 10-29 the two legs were 0.12 and 9.38, so the averaged `atm_iv` on that row is
not a meaningful number and should not be read as one.
