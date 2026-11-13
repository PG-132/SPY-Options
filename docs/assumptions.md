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

### A-003 · VOL-008 · High · The pricing clock on expiries that close at 1pm

**Assumed:** ending time to expiry at 16:00 on a 1pm-close expiry is an oversight, not a choice.

**Why:** `vol.one_expiry()` always ends time to expiry at 16:00 ET. NYSE's calendar has 1pm closes on 2026-11-27 and 2026-12-24 (1:15pm for eligible options), and SPY lists daily expiries on both dates. The extra three hours make that expiry's IVs read low: about 0.5 vol points on 11-27 and 1 point on 12-24 in their last day. Nothing built from total variance sees it (windows, constant maturity, context, ledger, vrp), so the error stays in that one expiry's annualized numbers. Mechanism and sizes are in [specs/vol.md](specs/vol.md) under "Gaps". `prices.session_close()` already knows the 13:00 close; `vol.py` doesn't use it.

**Owner, 2026-11-05:** a separate, lower-priority decision. The other half of this entry, `context.py` measuring the snapshot's own session against 16:00 on a half day, was fixed the same day (CTX-003).

**Question:** end the pricing clock at 13:00 on `HALF_DAYS` expiries, or keep 16:00 as a documented convention? The agent's suggestion if it changes: 13:00 rather than 13:15, since variance builds only while SPY itself trades.

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

### A-015 · TERM-006 · Medium · The drop rule's threshold is absolute

**Assumed:** `term.CONFIG["max_vs_edge_cost"]` = 0.0005 (0.05 vol points of edge cost) is meant as a fixed cap at every vol level.

**Why:** it was set on calm chains (measurements.md 2026-11-02). On `2026-11-05_1633`, at VIX 28, edge costs ran 0.0005 to 0.005, and the rule dropped every expiry from 11-06 to 11-12 and from 11-16 to 11-19. That left three windows: spot to 11-13, 11-13 to 11-20, and 11-20 to 11-30. It also cut 12-04 and 12-11, so that day has no 30-day rate and no VIX comparison; 11-30 was 5.02 days short, just over `vrp.CONFIG["max_extrapolation_days"]`. Some drops are real: run.json shows 11-17 to 11-19 listed only down to 680-690, with 13-17% delta still at the edge. Others are marginal, such as 11-09 at 0.00057. A fixed cap gets stricter as vol rises: 0.05 points is 0.33% of a 15% rate but 0.17% of a 30% one.

**Question:** keep the cap absolute, or scale it with the expiry's own rate?

## Interpretations the agent made

### A-012 · All specs · Medium · Your written reasons count as intent

**Assumed:** a behavior whose reason you wrote down (measurements.md, integrity.md, concepts.md, a docstring's rationale, or a commit message) is marked **Intended**; behavior seen only in code or tests is **Observed**.

**Why:** the knowledge base was built from the repo alone, and those docs read as decisions.

**Question:** OK, or should everything start as Observed until you confirm it?

### A-017 · SCEN-002, SCEN-008, SCEN-012 · Low · Three smaller readings in the scenario engine

**Assumed:** (1) a strike the chain does not list is refused, not read off the fitted curve; (2) a listed strike vol.py could not read, which does take the curve inside its range, carries the fit's RMS as its IV band; (3) the position's range adds each strike's low and each strike's high, as though every strike errs the worst way at once. (Narrowed 2026-11-11, the owner's go-ahead on a Codex finding: legs on one expiry and strike read one IV, so they are now taken together first; +10 and -10 of one call had read -$10 to +$10. Between strikes the question below stands.)

**Why:** the record says a strike that "was not readable" takes the curve, and reads that as one vol.py failed to solve. On `2026-11-05_1633` a straddle at 733 on 12-04, which lists 730 and 735, came back priced off the curve with no quote: a number for a contract nobody can trade. A curve-read leg has no quotes of its own to give it a band, and the fit's RMS is the curve's own measured miss. Adding extremes is the conservative read, the one `vol.variance_swap` takes with quote spreads; between legs that offset, a spread or a calendar, the truth is narrower.

**Owner, 2026-11-13:** "leave it like that for now": all three stay as built, deferred rather than confirmed.

**Question:** keep all three, or change any of them?

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
