# Architecture

## Stack

| Item | Version | Source |
| --- | --- | --- |
| Python | 3.13.7 on the machine used for setup, 3.14.3 on the owner's machine; no minimum is declared | `python --version`, 2026-11-04 |
| Standard library only for analysis | uses `zoneinfo`, so Python 3.9+ | imports in `screener/*.py` |
| Webull OpenAPI Python SDK | 2.0.19, pip package `webull-openapi-python-sdk`; imported as `webull.core.client` and `webull.data.data_client` | `screener/collect.py` `make_client()`; `requirements.txt` |
| `yfinance` | 1.2.0 | `screener/prices.py`; `requirements.txt` |
| Dash | 4.5.1, for the UI only; brings Flask, Werkzeug and pydantic with it | `screener/ui_app.py`; `requirements.txt`; installed 2026-11-19 |
| Plotly | 7.1.0 (plotly.js 4.1.1 in the browser), for the UI only | `screener/ui_app.py`; `requirements.txt`; installed 2026-11-19 |

`requirements.txt` pins the four packages above (owner, 2026-11-19, closing A-008). Install with `python -m pip install -r requirements.txt`. It pins only those four, so pip resolves the packages they bring in: on the owner's machine on 2026-11-19 that added 20 and moved `typing_extensions` from 4.15.0 to 4.16.0. Neither the Webull SDK nor `yfinance` was installed on the setup machine, so only the offline tests were run there.

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
| `screener/history.py` | Four cross-snapshot views: fixed expiry, constant maturity, per session, and a fixed strike across each day's move (the check on the scenario engine's IV response) |
| `screener/ledger.py` | Every window of every snapshot, rebuilt each run; repricing (movers), settlement against realized, pivot, missed sessions |
| `screener/prices.py` | Daily closes for SPY, ^VIX, ^VIX9D, ^VIX3M, ^IRX from Yahoo; the cache and its freshness guard. The only file that talks to Yahoo |
| `screener/vrp.py` | Implied against realized, one non-overlapping claim per month |
| `screener/scenario.py` | A position's value, Greeks and P&L under hypothetical spot, IV shifts, dates and paths, on the snapshot's own IVs and term structure, each strike keeping its IV as spot moves, under three IV responses to the move. What-if only; the UI and the chooser call it |
| `screener/ui.py` | The page's view: everything it shows, as plain data from the engine and the pipeline's files; standard library only. Holds `cmd_ui` |
| `screener/ui_app.py` | The page's drawing: Dash layout, callbacks and Plotly figures, built only from `ui.py`'s output. The one file that imports Dash or Plotly, imported only by `ui` |
| `tests/` | Offline unit tests, one file per module, with a fake Webull client |
| `trades/` | Hand-kept paper-trade logs (CSV plus the source workbook) and notes |

## Entry points

- `python app.py <command>`; with no command it runs `plan`, which is read-only (so VS Code's Run button can't write anything).
- `python -m unittest discover tests`.
- Modules are imported from `app.py`, not run on their own (each still has a `__main__` guard).

## Key flows

**Daily pipeline** (`python app.py daily`, about 15:45 ET; 12:45 on 1pm-close days). Each step reads the newest output of the one before; a failure stops the run.

```text
snap ──> iv ──> surface ──> term ──> context ──> ledger ──> response
 │        │        │          │         │           │
 │        │        │          │         │           └─ data/ledger/  (rebuilt from every snapshot's context output)
 │        │        │          │         └─ data/context/
 │        │        │          └─ data/term/      forward.csv, constant.csv
 │        │        └─ data/surface/<snap>/       points.csv, fits.csv
 │        └─ data/iv/<snap>/                     contracts.csv, expiries.csv
 └─ data/chains/YYYY-MM-DD_HHMM/                 options.csv, spot.csv, run.json  (raw, never modified)
```

`response` is history's fixed-strike view alone (`history.cmd_response`), reading every day's last snapshot in `data/iv/` and writing `data/history/response.csv`. The full `history`, `prices` and `vrp` are run on their own. `context`, `ledger` and `vrp` call `prices` for SPY closes and VIX.

**Scenarios** (`python app.py scenario <position.csv>`, on demand, not in `daily`). Reads one snapshot's raw quotes (`data/chains/`), vol.py's IVs and forwards (`data/iv/`), the fit and its range (`data/surface/`, read only for a strike vol.py could not read), and the term structure through `term.load`, starting on vol.py's clock (`vol.years_to_expiry`). Writes `data/scenario/<snap>/<position>/`.

**The page** (`python app.py ui`, on demand). Serves on 127.0.0.1 (port 8050 by default) until Ctrl+C. Reads each snapshot through `scenario.load`, with its `points.csv`, `run.json` and `term.load` (for the drop rule's reasons), between two `scenario.snapshot_hash`es, and keeps what it read by that hash. The strip comes from `term.load`, `term.constant_maturity` and `context.decompose`. Each view is a window moved by `screener/assets/windows.js`, which Dash serves with the page. Writes nothing yet. See [specs/ui.md](specs/ui.md).

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
| `data/history/` | `history`; `response.csv` also by `daily` | `constant_maturity.csv`, `fixed_expiry.csv`, `per_session.csv`, `response.csv` |
| `data/ledger/` | `ledger` | `windows.csv` and `pivot.csv`, rebuilt each run |
| `data/prices/` | `prices` | daily closes per symbol |
| `data/vrp/` | `vrp` | the monthly implied/realized log |
| `data/scenario/<snapshot>/<position>/` | `scenario` | `legs.csv`, and `grid.csv` or `path.csv`; every row stamped with `inputs`, and a folder never mixes two; saves are staged in `data/scenario/.work/` |

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
| `screener/collect.py` | docstring, CONFIG, function list; `market_open` and the `summarize` warnings read in full on 2026-11-05 | 2026-11-04 | Webull calls not traced |
| `screener/pricing.py` | docstring, function list | 2026-11-04 | covered by frozen reference tests |
| `screener/vol.py` | docstring, CONFIG, calendar, clocks, `collected_band`; `one_expiry` and the `variance_swap` integral read in full on 2026-11-05 | 2026-11-04 | `forward()` body not traced |
| `screener/surface.py` | docstring, CONFIG, gates | 2026-11-04 | fit internals sampled |
| `screener/term.py` | docstring, CONFIG keys, half-day handling; how `load` builds total variance and how windows divide it, read 2026-11-05 | 2026-11-04 | drop rule body not traced |
| `screener/context.py` | docstring, CONFIG keys; `session_remaining` and `with_spot` read in full on 2026-11-05 | 2026-11-04 | |
| `screener/history.py` | docstring | 2026-11-04 | |
| `screener/ledger.py` | docstring; band, convergence, movers filter, settled summary read in full | 2026-11-04 | roll-down and pivot bodies not traced |
| `screener/prices.py`, `screener/vrp.py` | docstrings, CONFIG keys, `cmd_vrp` | 2026-11-04 | |
| `screener/scenario.py` | written in full | 2026-11-09 | |
| `tests/` | every test name read; suite run | 2026-11-04 | 256 passed; 350 on 2026-11-10 |
| `docs/` | integrity and concepts read; measurements read by section | 2026-11-04 | |
| `trades/` | READMEs read | 2026-11-04 | CSVs and workbooks not opened |
