# data/ (not in git)

Everything here is regenerable, so none of it is committed.

    chains/YYYY-MM-DD_HHMM/   one chain snapshot per run: options.csv, spot.csv, run.json
                              written by `python app.py snap`
    iv/                       derived IVs per snapshot (step 2)
    prices/                   SPY history and the CBOE index series, pulled from Yahoo

A snapshot is about 650 KB, so daily collection runs roughly 150 MB a year.
