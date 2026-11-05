# Architecture

## Stack

| Item | Version | Source |
| --- | --- | --- |
| Python | 3.13.7 on the machine used for setup; no minimum is declared | `python --version`, 2026-11-04 |
| Standard library only for analysis | uses `zoneinfo`, so Python 3.9+ | imports in `screener/*.py` |
| Webull OpenAPI Python SDK | not pinned; imported as `webull.core.client` and `webull.data.data_client` | `screener/collect.py` `make_client()` |
| `yfinance` | not pinned | `screener/prices.py` |

There is no `requirements.txt` or `pyproject.toml` (A-008 in [assumptions.md](assumptions.md)). Neither third-party package was installed on the setup machine, so only the offline tests were run.

## Module map

| File | Responsibility |
| --- | --- |
| `app.py` | The one entry point: argparse commands, and `daily`, which chains the pipeline |
| `screener/collect.py` | Chain snapshots. The only file that talks to Webull, market data only |
| `screener/pricing.py` | Black-Scholes in forward terms, the IV solver, Greeks. Math with no opinions |
| `screener/vol.py` | Our IVs per snapshot: forward from parity, IV band per strike, Greeks, variance-swap rate, the exchange calendar (`HOLIDAYS`, `HALF_DAYS`) and the session clocks |
| `screener/surface.py` | Readable and tradeable gates, the smile fit, residuals and edges, forward cost |
| `screener/term.py` | Forward variance between expiries, constant-maturity vol, no-arbitrage check, the drop rule for under-resolved expiries |
| `screener/context.py` | Every window against the rest of the chain and against its neighbours; the level against VIX |
| `screener/history.py` | Three cross-snapshot views: fixed expiry, constant maturity, per session |
| `screener/ledger.py` | Every window of every snapshot, rebuilt each run; repricing (movers), settlement against realized, pivot, missed sessions |
| `screener/prices.py` | Daily closes for SPY, ^VIX, ^VIX9D, ^VIX3M, ^IRX from Yahoo; the cache and its freshness guard. The only file that talks to Yahoo |
| `screener/vrp.py` | Implied against realized, one non-overlapping claim per month |
| `tests/` | Offline unit tests, one file per module, with a fake Webull client |
| `trades/` | Hand-kept paper-trade logs (CSV plus the source workbook) and notes |

## Entry points

- `python app.py <command>`; with no command it runs `plan`, which is read-only (so VS Code's Run button can't write anything).
- `python -m unittest discover tests`.
- Modules are imported from `app.py`, not run on their own (each still has a `__main__` guard).

## Key flows

**Daily pipeline** (`python app.py daily`, about 15:45 ET). Each step reads the newest output of the one before; a failure stops the run.

```text
snap ──> iv ──> surface ──> term ──> context ──> ledger
 │        │        │          │         │           │
 │        │        │          │         │           └─ data/ledger/  (rebuilt from every snapshot's context output)
 │        │        │          │         └─ data/context/
 │        │        │          └─ data/term/      forward.csv, constant.csv
 │        │        └─ data/surface/<snap>/       points.csv, fits.csv
 │        └─ data/iv/<snap>/                     contracts.csv, expiries.csv
 └─ data/chains/YYYY-MM-DD_HHMM/                 options.csv, spot.csv, run.json  (raw, never modified)
```

`history`, `prices` and `vrp` are run on their own. `context`, `ledger` and `vrp` call `prices` for SPY closes and VIX.

**Settlement.** A ledger window spans (start, end] in sessions. Once `end` is in the cached SPY closes, its realized volatility is measured over exactly those closes and set beside the forward vol it was priced at.

## External services

| Service | Used for | Where | Notes |
| --- | --- | --- | --- |
| Webull OpenAPI | Option chain quotes, SPY spot | `collect.py` | Needs the OPRA subscription. 20 contracts per request; rate limit unmeasured (`throttle_s` 0.25) |
| Yahoo Finance via `yfinance` | Daily OHLC history | `prices.py` | Returns `[]` on failure and falls back to the cache |

## Data

Everything under `data/` is regenerable and git-ignored, except `data/README.md`. A snapshot is about 650 KB, so roughly 150 MB a year.

| Folder | Written by | Holds |
| --- | --- | --- |
| `data/chains/YYYY-MM-DD_HHMM/` | `snap` | `options.csv` (every field Webull returned, vendor IV and Greeks renamed `vendor_*`), `spot.csv`, `run.json` (rules used, band, asked vs received, warnings) |
| `data/iv/<snapshot>/` | `iv` | `contracts.csv`, `expiries.csv` |
| `data/surface/<snapshot>/` | `surface` | `points.csv`, `fits.csv` |
| `data/term/<snapshot>/` | `term` | `forward.csv`, `constant.csv` |
| `data/context/<snapshot>/` | `context` | windows against rest and neighbours |
| `data/history/` | `history` | `constant_maturity.csv`, `fixed_expiry.csv`, `per_session.csv` |
| `data/ledger/` | `ledger` | `windows.csv` and `pivot.csv`, rebuilt each run |
| `data/prices/` | `prices` | daily closes per symbol |
| `data/vrp/` | `vrp` | the monthly implied/realized log |

Column lists are the `*_COLS` constants at the top of each module.

## Deployment

None. It runs by hand on the owner's machine. There is no CI configuration in the repository.

## Configuration and secrets

- Tunable rules are the `CONFIG` dict at the top of each module. Each value has a comment and, usually, a measurements.md entry.
- `WEBULL_APP_KEY` and `WEBULL_APP_SECRET`: environment variables, never printed.
- Webull's token directory: `~/.webull`, or `WEBULL_OPENAPI_TOKEN_DIR` if set. Region: `WEBULL_REGION_ID`, default `us`. Both read in `collect.make_client()`.
- `.gitignore` excludes `conf/`, `token.txt`, `.env`, `*.pem`.

## Inspection coverage

| Area | Depth | Date | Notes |
| --- | --- | --- | --- |
| `app.py` | read in full | 2026-11-04 | |
| `screener/collect.py` | docstring, CONFIG, function list | 2026-11-04 | Webull calls not traced |
| `screener/pricing.py` | docstring, function list | 2026-11-04 | covered by frozen reference tests |
| `screener/vol.py` | docstring, CONFIG, calendar, clocks, `one_expiry` start, `collected_band` | 2026-11-04 | `forward()` and `variance_swap()` bodies not traced |
| `screener/surface.py` | docstring, CONFIG, gates | 2026-11-04 | fit internals sampled |
| `screener/term.py` | docstring, CONFIG keys, half-day handling | 2026-11-04 | drop rule body not traced |
| `screener/context.py` | docstring, CONFIG keys | 2026-11-04 | |
| `screener/history.py` | docstring | 2026-11-04 | |
| `screener/ledger.py` | docstring; band, convergence, movers filter, settled summary read in full | 2026-11-04 | roll-down and pivot bodies not traced |
| `screener/prices.py`, `screener/vrp.py` | docstrings, CONFIG keys, `cmd_vrp` | 2026-11-04 | |
| `tests/` | every test name read; suite run | 2026-11-04 | 256 passed |
| `docs/` | integrity and concepts read; measurements read by section | 2026-11-04 | |
| `trades/` | READMEs read | 2026-11-04 | CSVs and workbooks not opened |
