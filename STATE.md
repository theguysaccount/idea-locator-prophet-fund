# STATE: 2026-10-25

**Before this repo:** 17 saved Claude artifact pages (31 Jul to 6 Aug 2026), reports only. None of the Python they cite (`filter/plain.py`, `engine.py`, `freeze.py`, `PREREGISTRATION.md`) exists in the folders, so nothing could be re-run. The prophet.fund thesis page is AES-encrypted and unreadable.

**Worth reusing (and reused):** the rule (capital burned × constraint lift, with abstention), the 20 verified category pairs and 19 "not timing" myths, the five calls frozen on 2026-08-01, the 28-row slip corpus, the enabler taxonomy, and the backtest numbers with their caveats.

**Broken in the research and fixed here:**
- Slip corpus errors: the EMV fuel-pump date (moved twice, to April 2021); TSMC Arizona, which held; Intel Ohio, which is a target, not an actual date; and the EUDR small-operator start date.
- Several graveyards were cohort-level ("the 2010s microgrid cohort"). These no longer earn a Ripe verdict; they show as Blocked on a check.
- The private 2026-08-01 hash chain was never published, so it cannot be verified. The public chain starts on 2026-10-25 and records the first-stated dates.

**Works now:**
- 58 categories: 20 live, 19 history, 19 myths.
- 159 cited sources, every one resolving.
- 13 dated calls on the ledger: 8 resolve automatically from the Federal Register, FRED or ClinicalTrials.gov, and 5 by scheduled review.
- Live metrics from FRED, the World Bank and OWID; a Federal Register calendar of 76 documents; trial tracking.
- The re-look screen; 44 Python and 3 Node tests; weekly refresh, deploy and self-test workflows with keep-alive.

**Known gaps:**
- (Closed 2026-11-10.) No call was due to resolve before January 2027, so there was no score. See the update below.
- Five graveyards are unenumerated, and capital is disclosed for only some companies.
- Analytics are off until a GoatCounter key is set.
- There is no custom domain, and Google Search Console is not set up.

## Update: 2026-11-10

- **First resolution.** C14 (CMS publishes the CY 2027 Physician Fee Schedule final rule referencing G0552 by 2027-01-31, said at 92%) resolved **YES** early. The final rule was published on 2026-11-09 (FR doc 2026-22743), and the resolver found it.
  - The ledger now reports a mean Brier score: 0.006 over one call.
  - `/calls/` lists resolved calls with their evidence. Category pages, cards, embeds and share cards show the outcome.
- **Why the 2026-11-09 refresh failed.** A test asserted the launch-day sentence "No call has resolved yet", so the run stopped before committing and the site stopped refreshing (the last deploy stayed live).
  - The tests now build temporary chains with and without resolutions, and assert on whatever the real ledger holds.
  - The relook tests derive their expectations from the data instead of fixed figures.
- **Slow sources.** The same run logged a World Bank read timeout, which was already marked stale without failing the run.
  - Requests now use growing waits, a per-attempt time cap, no retries on client errors, and a run-wide time budget.
  - A test runs a full refresh with the World Bank timing out on every attempt. It checks that the run succeeds, the World Bank keeps its last good values, and every other source refreshes.
- **Tests:** 56 Python and 4 Node, up from 44 Python and 3 Node at launch.
