# spy-screener

A personal SPY options volatility screener and paper-trading notebook. It snapshots the chain from Webull, solves its own IVs, fits the smile, strips the term structure, and keeps a ledger of every window it priced against what SPY actually did. It measures; it does not forecast.

## Read first

1. This file.
2. [docs/status.md](docs/status.md): current state, open questions, next actions.
3. [docs/assumptions.md](docs/assumptions.md): open questions for the owner. Check it for any entry touching your task.
4. [docs/context.md](docs/context.md): goals, scope, decisions, rejected approaches.
5. Then only what the task needs: [docs/specs/](docs/specs/README.md) for the affected areas, and [docs/architecture.md](docs/architecture.md).

Search `docs/` for the task's key terms before answering or editing, so related decisions and constraints aren't missed. Don't read every file by default. `docs/measurements.md` is long (1,300+ lines): search it by heading or keyword instead of reading it whole.

### Where things live

| Question | File |
| --- | --- |
| Why is a constant this number? | [docs/measurements.md](docs/measurements.md), dated entries |
| What could still be wrong? | [docs/integrity.md](docs/integrity.md) |
| What does this output column or mechanism mean? | [docs/concepts.md](docs/concepts.md) |
| What does the code do, by area, with IDs? | [docs/specs/](docs/specs/README.md) |
| How did the paper trades go? | [trades/README.md](trades/README.md) |

## Boundaries

- In scope: the screener in `screener/`, its entry point `app.py`, its tests, its docs, and the paper-trade logs in `trades/`.
- Out of scope: placing orders (the code uses Webull market data only, never `webull.trade`), forecasting, and ranking anything by expected profit.
- The user's current request comes first. Next actions listed in docs/status.md are not permission to act; do them when asked.
- Never write secrets into this folder. Webull keys live in the environment (`WEBULL_APP_KEY`, `WEBULL_APP_SECRET`) and its token in `~/.webull`. Record where a secret lives, not its value.

## Labels

Facts in `docs/` carry one label: **Decided** (the user approved it), **Proposed**, **Assumption**, **Observed** (seen, not confirmed as intended), **Sourced** (with source and date), or **Open**. Never relabel something as Decided without the user saying so.

## Keeping this project current

You maintain these files as part of normal work. No special tool or skill is needed.

- **Save as you go.** When you learn something that matters, write it into the document that owns it: findings, decisions and why they were made, corrected facts, user preferences, open questions, and rejected approaches with the reason.
- **One home per fact.** Update the owning document and link to it elsewhere. Don't copy it.
- **When understanding changes,** update the current text and add a dated line to the History in docs/status.md saying what changed, why, and what it replaces. Fix any other document that now disagrees.
- **Keep it a knowledge base, not a log.** Leave out asides, repeated answers, and speculation presented as fact. If the user asks you not to save something, don't.
- **When you finish substantive work,** tell the user which files you updated and what remains uncertain. If you couldn't write the files, say so and show the change you would have made.

## Answering assumptions

[docs/assumptions.md](docs/assumptions.md) holds every guess an agent made about what the code is meant to do. The user answers them by ID, for example "A-003: yes, intended" or "A-005: no, it should do X".

1. **Before working in an area,** check assumptions.md for an open entry that touches it. If one does and the answer would change your work, ask it first. Otherwise mention it and carry on.
2. **When the user answers an entry:**
   - Confirmed: set the linked spec behaviors to **Intended** with evidence "user, YYYY-MM-DD".
   - Rejected or changed: set them to **Gap**, and if code must change, open a change record in `docs/changes/` (or a one-line fix for something small) and follow the change workflow below.
   - A correction an agent made that the user vetoes: revert that text and record the user's version.
   - Then fix any doc that now disagrees, delete the entry from assumptions.md, and add a dated line to the History in docs/status.md: `A-NNN resolved: <answer>, <what changed>`.
3. **When you have to guess something new,** add an entry with the next unused ID. IDs are never reused.

## Commands

| Purpose | Command | Source | Last verified |
| --- | --- | --- | --- |
| Test (offline, fake Webull) | `python -m unittest discover tests` | README.md | 2026-11-04: 256 tests passed, Python 3.13.7 |
| Daily run (snap + pipeline) | `python app.py daily` | app.py | not run (needs Webull SDK, keys, market hours) |
| Plan a snapshot, read-only | `python app.py plan` | app.py | not run (needs Webull SDK and keys) |
| One step on the newest snapshot | `python app.py iv\|surface\|term\|context\|history\|ledger` | app.py | not run (needs data/ from a snapshot) |
| Price history | `python app.py prices [refresh]` | app.py | not run (needs `yfinance`) |
| Implied vs realized | `python app.py vrp [refresh]` | app.py | not run (needs `yfinance`) |

No lint, format, or typecheck configuration exists. There is no dependency manifest; see A-008 in docs/assumptions.md.

Update this table whenever a command changes or you run one with a new result.

## Conventions

- Standard library only in the analysis code; `numpy` is not imported. Third-party APIs sit behind one door each: Webull only in `screener/collect.py`, Yahoo only in `screener/prices.py`.
- Every module is reached through `app.py`; each has a `cmd_<name>()` and a long docstring that explains its reasoning. Keep that style (see any file in `screener/`).
- Tests: `tests/test_<module>.py`, `unittest`, offline, with test names written as sentences that state the behavior (`test_a_band_change_is_not_a_move`). Fixtures write to `tempfile.TemporaryDirectory()` and must never read the real `data/` (see `tests/test_ledger.py`).
- Raw snapshots in `data/chains/` are never modified. Every derived number must be reproducible from them. `data/` is not committed.
- Numbers carry error bars. Constants come from measurements, not choice. The standing rules at the end of [docs/integrity.md](docs/integrity.md) are hard rules.
- Git: the owner pushes. Commit only when he says he is about to, one commit per change, never several chained together, and show him the message first since he usually rewrites it. Messages are lowercase, no prefix, one plain line saying what changed and why (`git log`), with a body only when the change is substantial. No `Co-authored-by` trailer unless he asks.
- When you change a `CONFIG` constant, add a dated entry to docs/measurements.md saying what measurement produced the new value, and update the comment beside the constant.
- When you add an `app.py` command, also update the `app.py` docstring, the README's "Running it" list, and `cmd_daily()` if it reads the newest snapshot.
- When you add or rename an output column, update the module's `*_COLS` list, its tests, and docs/concepts.md if the column needs explaining.
- When you touch time logic, test it in both EDT and EST (the 2026-11-01 entry in docs/measurements.md shows why).
- `vol.HOLIDAYS` and `vol.HALF_DAYS` are the one exchange calendar, shared by `vol.py` and `prices.py`. They run to the end of 2027; extend both from NYSE's published calendar before then.
- When an integrity item is checked, move it to "Handled, and why" in docs/integrity.md with the date and evidence.
- When a paper trade closes, add its row to trades/README.md.

Follow the existing architecture and these conventions over general best practices.

## Change workflow

Specs in `docs/specs/` describe intended behavior. Each behavior is **Intended**, **Observed** (seen in code, not confirmed), **Proposed**, or **Gap**.

1. **Investigate.** Read the affected specs, docs/architecture.md, the code, and its tests. Identify the behavior change and the contracts it touches before you edit.
2. **Outline.** For a small fix, write a short outline in your reply covering intended behavior, acceptance criteria, and how you'll check it. For a significant feature, redesign, migration, or contract change, create `docs/changes/YYYY-MM-DD-<slug>.md` (state `proposed`) with numbered acceptance criteria (`AC-1`, ...) and a task checklist where each task names its criteria. For user-interface changes, cover the loading, empty, error, and success states that apply.
3. **Resolve consequential gaps.** Ask when ambiguity affects correctness, scope, or who decides. An explicit user request authorizes the change; routine choices don't need separate approval. Before coding a significant change, check the record against the specs and the Conventions for conflicts or missing steps.
4. **Implement.** Take the simplest approach that meets the criteria. Add no speculative abstractions, no unneeded dependencies, and no unrelated cleanup. If the change alters an **Observed** behavior, tell the user. If the plan turns out wrong, update the record first instead of quietly redesigning.
5. **Verify.** Tie each acceptance criterion to a test or other observable check. Use the Commands table. Run focused checks for small changes and broader checks for shared contracts, dependencies, auth, schemas, migrations, deployment, or public APIs. Add regression tests that protect meaningful behavior, unless the Conventions set a lighter testing preference. Review the diff in a separate pass before calling the work done. Never weaken a criterion to fit the code, and never hide a failed check.
6. **Record.** Update the change record (state, ticked tasks, verification evidence). When it's verified, fold the behavior into `docs/specs/` as Intended and link the record. Then update docs/status.md and any Commands, Conventions, or architecture details that changed.

**Across sessions:** the change record's task checklist is the handoff. Tick tasks as you finish them, and note where you stopped and what is half-done.
