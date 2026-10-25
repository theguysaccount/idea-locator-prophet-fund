# DECISIONS

**D1: static site on GitHub Pages, Python standard library only.**
- Data is small, updates weekly and is identical for every visitor, so prebuilt HTML is fastest and cannot go down independently.
- The research pages were single-file HTML with no code, so there was no stack to keep.
- Node is used only in tests and screenshots.

**D2: the ledger is the source of truth for calls.**
- `data/calls.json` is a registration queue. After registration the call body on the chain is what the site shows, and tests fail if the queue and the chain disagree.
- Verdict changes are appended as dated entries.
- The deploy job refuses any ledger that does not extend the live one.

**D3: the public chain starts fresh on 2026-10-25.**
- The 2026-08-01 chain (head `5b7eb135…`) was never published and its serialisation is unknown, so continuity cannot be proven.
- C1-C5 are re-registered with `first_stated: 2026-08-01`. Only the public registration date counts for scoring. Claiming the old chain would be unverifiable.

**D4: Ripe requires a named, sourced graveyard; cohort-level corpses become a check.**
- This is stricter than the 2026-08-01 research, which admitted behind-the-meter power, protein binders and glasses apps on asserted cohorts.
- The research's own finding was that "no corpse" is the most common cause of death and that unknown is not false. Applying that evenly turns those three into Blocked on a check.
- Only prescription digital therapeutics is Ripe today: three named, dead, funded companies plus a dated code change.

**D5: abstain explicitly.**
- "I don't know" is the verdict when the named blocker never moved, or crossed and the category still died (consumer genomics, eVTOL).
- This follows the regressive-proof result that scoring such cases as zero dragged AUC from 0.719 to 0.583.

**D6: automatic resolvers only where an API can decide.**
- Federal Register (RIN or full-text plus title), FRED (date or monthly average comparisons, first published values) and ClinicalTrials.gov (sponsor, title term, first-posted window).
- Everything else is manual, with the method written into the call before it resolves.
- No model resolves a call.

**D7: capital is shown only where a stable source discloses it.**
- Totals are floors, and "capital" means raised or lost, as each source states.
- Dropped for lack of a stable source: Streamline.com and Pop.com.
- Removed as unverifiable: Convoy's $3.8B valuation and Anki's $200M raised.

**D8: weekly refresh rather than monthly.**
- The machine loop says monthly. Weekly costs nothing, keeps the Federal Register calendar fresh, and doubles as repository activity.
- Annual series (genome cost, EV sales) simply do not change most weeks.

**D9: no posting, no outreach, no accounts.**
- Distribution is search pages, structured data, sitemap, IndexNow, share cards, embeds and open data.
- The original prompt's launch-post drafts and DMs are replaced by machine channels (LAUNCH.md).

**D10: the re-look screen runs in the browser.**
- A private upload service would need a server, storage and NDAs.
- Client-side matching on published keywords gives the same first value with zero data custody. It is honest about misses ("I don't know").

**D11: brand is "Idea Locator", not prophet.fund or Persist.**
- prophet.fund is not owned, and publishing under Jack's or Persist's name needs his approval. The board is neutral and machine-run.

**D12: dropped research claims that could not be verified.**
- Dropped: humanoid success rates, agent reliability percentages, multi-speaker WER, the agentic-checkout retrenchment, and LBNL solar installed costs.
- They sit in `data/backlog.json` for the scheduled review to source or reject.
- The BloombergNEF storage price is kept, marked unlinked and "as cited", because BNEF data is not redistributable.

## Open questions settled with defaults (for Jack, none blocking)

1. **Where is the original code?** Not found. The pipeline was rebuilt from public sources; the research numbers are quoted as reported (method page).
2. **Is there a design-partner fund?** Unknown. The client-side re-look screen serves funds without one; the paid slot is `IL_RELOOK_REPORT_URL`.
3. **What does the encrypted prophet.fund thesis commit to?** Unreadable. The fund vehicle is out of scope.
4. **Founder telemetry from the Persist portfolio?** Not used. It would need consent and is not public.
5. **Domain?** Use `ripeness.prophetventures.org` (owned). Alternatives: register `ripenessboard.com` or `ripeagain.com` (both unregistered on 2026-10-25). See LAUNCH.md.
