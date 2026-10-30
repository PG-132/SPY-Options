# trades

One folder per trade, named by expiry and structure. Each holds the daily log
as a CSV, which GitHub renders as a table and git can diff line by line, along
with the workbook it came from and any notes.

| Trade | Entered | Closed | Result |
| --- | --- | --- | --- |
| [SPY 764 straddle, Sep 25](2026-09-25-spy-764-straddle/) | 2026-08-24, $4,706 debit at 12.80% IV | expired 2026-09-25, SPY 771.35 | −$3,236 before fees |
| [SPY 775 straddle, Oct 30](2026-10-30-spy-775-straddle/) | 2026-10-05, $2,005 credit at 12.47% IV | closed 2026-10-30 before the bell, SPY 755.72 | +$444 at exit, +$77 if held |

These are paper trades, kept to watch how the Greeks behave over a full cycle,
not a performance record.
