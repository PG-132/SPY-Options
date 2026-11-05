# Assumptions to confirm

Every place an agent had to guess what the code or docs are meant to say. Answer by ID, in any session, with Claude or Codex: "A-003: yes, intended", "A-005: no, it should do X", "A-010: revert it". The agent then updates the specs and docs, deletes the entry, and logs the answer in [status.md](status.md) (the loop is in [../AGENTS.md](../AGENTS.md) under "Answering assumptions").

You don't have to answer these before working. An agent only stops to ask one when your request touches its area.

**Weight:** High = numbers in the output may be wrong. Medium = a rule or explanation may be wrong. Low = wording or housekeeping.

Opened 2026-11-04, during knowledge-base setup. IDs are never reused.

## Questions about the code

### A-002 · LEDG-016, LEDG-017 · Low · Unknown-band rows

**Assumed:** two edge cases are unintended, but rare enough to leave alone for now.

**Why:** (1) a settled row whose band is blank is counted in the skipped total, and the report says it was "collected under a band too narrow"; the real reason is that its band is unknown. (2) If the newest snapshot's band is blank, the mover table's band filter turns off and it can compare across a band change, which is the one artefact its comment says it can't survive. Both need a snapshot with neither run.json nor a chain summary.

**Question:** fix both (count unknown separately; refuse to compare when the newest band is unknown), or leave them?

### A-003 · VOL-008, CTX-003 · High · Expiries that close at 1pm

**Assumed:** pricing time ending at 16:00 on a 1pm-close expiry is an oversight, not a choice.

**Why:** `vol.one_expiry()` always ends time to expiry at 16:00 ET. NYSE's calendar has 1pm closes on 2026-11-27 and 2026-12-24 (1:15pm for eligible options), and SPY lists daily expiries on both dates. 11-27 is already inside the 37-day chain; 12-24 enters it around 11-17. The extra three hours make T too long and IV too low. An agent's rough estimate: about 0.04 vol points three weeks out, about half a point when snapped on 11-25 for the 11-27 expiry. `prices.session_close()` already knows the 13:00 close; `vol.py` doesn't use it. Separately, `context.py` measures the snapshot's own session against 16:00 on a half day; its own comment calls that "not modelled yet".

**Question:** should the pricing clock end at 13:00 on `HALF_DAYS` expiries (or 13:15, if SPY options trade the extra 15 minutes), and should `context.py`'s session fraction use the same close?

### A-004 · CHOOSE-001 · Medium · The structure chooser

**Assumed:** "Choosing" in the README is a planned goal that hasn't been built, not something removed. It's held in [changes/2026-11-04-choosing.md](changes/2026-11-04-choosing.md) as `proposed`.

**Why:** the README describes it; no module, command or test implements it; `surface.py` says the tradeable flag "rides along for whatever ranks candidates later".

**Question:** is it still a goal? If so: what form does a view take (range, direction, vol stance over dates?), which risk limits, which structures are in scope, and what does "fit" mean? Or is the next experiment the delta-hedged trade the Oct-30 notes mention?

### A-005 · COLLECT-003 · Low · Same-day expiries

**Assumed:** skipping 0 DTE expiries is still intended.

**Why:** `collect.py` says they're skipped because "time to expiry is counted in whole days, so they would have none left". Time has been counted in hours since 2026-09-24, so that reason no longer holds; `vol.one_expiry()` also drops `dte <= 0`. The text was left unchanged.

**Question:** keep skipping 0 DTE (and say why), or collect them?

### A-006 · VOL-011 · Low · The half-day weight on Christmas Eve

**Assumed:** applying the Thanksgiving-Friday weight of 0.5 to Christmas Eve is a deliberate, stated assumption.

**Why:** `vol.py` says only that half-day type is measurable from closes alone. 2026-12-24 is the next one.

**Question:** keep 0.5 for every 1pm close?

### A-007 · TERM-009, PRICE-009 · Low · Comments that still assume a 30-day chain

**Assumed:** two comments are stale since `max_dte` went from 30 to 37 (2026-10-20), but the constants they justify are still wanted.

**Why:** `term.py` says the longest expiry "lands near 18 sessions" so a 21-session horizon would be outside the chain; at 37 days the longest is about 25 sessions. `vrp.py` says the chain "tops out near 29 days". Neither was edited.

**Question:** keep horizons at (5, 10, 15) and correct the comments, or add a 20-session horizon now that the chain reaches it?

### A-008 · Architecture · Low · No dependency file

**Assumed:** dependencies are installed by hand and that's fine for now.

**Why:** the code needs the Webull OpenAPI SDK (imported as `webull.core` and `webull.data`) and `yfinance`, and nothing in the repo says which packages or versions. Neither was installed on the setup machine.

**Question:** want a `requirements.txt`? If so, which pip package name and version of the Webull SDK do you use?

### A-009 · LEDG-014, PRICE-010 · Low · How "converged" is decided

**Assumed:** checking only the below-spot number (`int(band.split("/")[0]) >= 12`) is enough, because only 6/3 and 12/6 have ever been used.

**Why:** a 12/3 chain would pass. Also, `ledger.converged()` reads the threshold from `vrp.CONFIG` on purpose ("the one thing that must not happen is this module quietly keeping a different threshold"), but `history.py` keeps its own `CONVERGED_MOVES = 12`.

**Question:** is the below side the only one that matters, and should `history.py` read `vrp.CONFIG` too?

## Interpretations the agent made

### A-012 · All specs · Medium · Your written reasons count as intent

**Assumed:** a behavior whose reason you wrote down (measurements.md, integrity.md, concepts.md, a docstring's rationale, or a commit message) is marked **Intended**; behavior seen only in code or tests is **Observed**.

**Why:** the knowledge base was built from the repo alone, and those docs read as decisions.

**Question:** OK, or should everything start as Observed until you confirm it?

## Text the agent corrected (veto any of these)

Where git history showed the code had been changed on purpose, the stale text was updated to match. No logic was changed; the tests still pass.

### A-010 · COLLECT-002, COLLECT-004 · Collection band and DTE wording

**Changed:** the `collect.py` docstring said "1 to 30 days" and "6 expected moves below spot to 3 above", with 6/3 percentages. It now says 1 to 37 days and 12/6, with the percentages recomputed from `band_pct`. `concepts.md` "Two clocks" said "6 expected moves below spot, 3 above"; it now says 12/6, widened on 2026-10-15.

**Evidence:** commits `d10473b` (12/6) and `67fe417` (max DTE 37); the CONFIG comments.

**Question:** keep the corrections?

### A-011 · VOL-013 · integrity.md item 1 moved to Handled

**Changed:** item 1 ("half-days are missing") is struck through and its number kept so items 2-4 keep their numbers. A "Handled" bullet records that half-days have been modelled since 2026-10-30, and that both calendar tables match NYSE's published calendar exactly for 2026-2027 (checked 2026-11-04).

**Question:** keep it?

### A-013 · SURF-005 · The smile shape in `surface.py`

**Changed:** the module docstring said "a cubic in ln(K/F)"; the code fits hyperbola + quadratic + cubic in IV (`smile_basis`), and measurements.md records the cubic as rejected. The docstring now describes the shape the code uses.

**Question:** keep it?

### A-014 · APP, PRICE · Small text fixes

**Changed:**
- `app.py` docstring: "More commands arrive as the modules land (surface, screen, etc)" now points to the chooser change record instead (surface already exists).
- `vrp.py` docstring: `python app.py vrp update` became `refresh`, the argument the code actually checks.
- `data/README.md`: `prices/` was listed twice and `context/` and `ledger/` were missing.
- `prices.py`: the `^IRX` comment pointed to "integrity item 1", now the flat-rate check.

**Question:** keep them?
