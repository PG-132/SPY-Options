# spy-screener

A SPY options screener that 
    -Measures
        Captures options chain, solves its own IVs from the quotes, reduces them to numbers that can be
        compared such as at the money level for each expiry, skew by delta, and term structure per trading
        session. Distance out of the money is counted in expected moves and delta rather than %'s and time 
        is counted in sessions rather than calendar days. Long run context comes from published CBOE series
        while personal data is recorded and logged from present onwards. 

    -Choosing
        Given a view and risk limits, finds the structure that fits best given risk parameters.

    This is not a forecaster. Priced at their own IVs, every structure is a fair bet and only differ in shape 
    of risk and not in edge. Nothing here ranks candidates by expected profit, they rank by fit. 
    rich or cheap always means against the rest of today's surface rather than against a prediction. 


## Running it

Everything runs through `app.py`, from this folder:

    python app.py plan     which contracts a snapshot would pull (read-only)
    python app.py snap     take one chain snapshot, saved under data/chains/

With no command (VS Code's Run button), `app.py` runs `plan`.

It needs `WEBULL_APP_KEY` and `WEBULL_APP_SECRET` in the environment, plus
Webull's OPRA subscription. Take snapshots during market hours: after 16:00 ET
bid/ask go stale, and `snap` warns you.

## Layout

    app.py                the one entry point
    screener/collect.py   chain snapshots; the only file that talks to Webull
                          (market data only, so it can't place orders)
    tests/                offline tests with a fake Webull:
                          python -m unittest discover tests
    data/chains/          one folder per snapshot, created on the first `snap`

