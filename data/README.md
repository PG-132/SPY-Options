# data/ (not in git)

Everything here is regenerable, so none of it is committed.

    chains/YYYY-MM-DD_HHMM/   one chain snapshot per run: options.csv, spot.csv, run.json
                              written by `python app.py snap`
    iv/                       derived IVs per snapshot (step 2): contracts.csv, expiries.csv
    surface/                  fitted smiles and scored points per snapshot (step 3)
    term/                     forward variance and constant maturity (step 4)
    history/                  the three cross-snapshot comparisons (step 4b)
    prices/                   daily closes: SPY, VIX, VIX9D, VIX3M, IRX (step 5)
    vrp/                      implied against realized, monthly (step 5b)
    prices/                   SPY history and the CBOE index series, pulled from Yahoo

A snapshot is about 650 KB, so daily collection runs roughly 150 MB a year.
