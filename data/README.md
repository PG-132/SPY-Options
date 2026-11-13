# data/ (not in git)

Everything here is regenerable, so none of it is committed.

    chains/YYYY-MM-DD_HHMM/   one chain snapshot per run: options.csv, spot.csv, run.json
                              written by `python app.py snap`
    iv/                       derived IVs per snapshot (step 2): contracts.csv, expiries.csv
    surface/                  fitted smiles and scored points per snapshot (step 3)
    term/                     forward variance and constant maturity (step 4)
    history/                  the cross-snapshot comparisons (step 4b), and
                              response.csv: each strike near spot across each
                              day's move, also written by `daily`
    prices/                   daily closes from Yahoo: SPY, VIX, VIX9D, VIX3M, IRX (step 5)
    vrp/                      implied against realized, monthly (step 5b)
    context/                  each window against the rest and its neighbours (step 6)
    ledger/                   windows.csv and pivot.csv across every snapshot (step 7)
    scenario/<snap>/<pos>/    legs.csv and grid.csv (or path.csv) for one position file,
                              written by `python app.py scenario`; what-ifs, not forecasts.
                              Every row carries `inputs`; a folder never mixes two
                              positions, or two versions of the snapshot data
    scenario/.work/           a scenario save in progress, with the lock that keeps a
                              second run of the same position out; gone when it
                              finishes, and tidied by the next run if one was interrupted

A snapshot is about 650 KB, so daily collection runs roughly 150 MB a year.
