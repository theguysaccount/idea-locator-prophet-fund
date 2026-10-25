# OPERATIONS

Everything that runs, how each job fails safely, what to watch, and the keys a human can turn later. Nothing here needs a person for the site to stay live, current and discoverable.

## Automated jobs

### `refresh.yml`: weekly data refresh and call resolution (Mondays 06:17 UTC, or by hand)
1. `python -m il.refresh` fetches each source independently, with three retries:
   - FRED series (electricity price, truckload PPI, fed funds rate);
   - the World Bank (US broadband);
   - Our World in Data (genome cost, EV sales);
   - Federal Register documents matched to categories;
   - ClinicalTrials.gov studies for tracked sponsors.
2. Automatic resolvers run on every unresolved call:
   - Federal Register: a final rule under a RIN, or a full-text term plus title.
   - FRED: a dated observation or a monthly average versus a threshold, using first published values.
   - ClinicalTrials.gov: sponsor, title term and first-posted window.

   A resolution is appended to the ledger only when the rule is decided by data actually retrieved. "Yes" can come early; "no" only after the date.
3. The tests run, including ledger integrity and the check that the ledger matches `data/`.
4. `data/live/` and `ledger/chain.jsonl` are committed and `deploy.yml` is dispatched.
5. `scripts/health.py stale` fails the run if any source has failed for more than 28 days. This happens after the deploy, so the site stays up and GitHub emails the repo owner.

**Fails safe:**
- A failed source keeps its last good data, marked `stale` with the error and the date it started failing. The page then says "the last fetch failed; showing the last good values".
- A failing test stops the run before the commit.
- A broken ledger stops `il.refresh` before it writes anything.

### `deploy.yml`: build and publish (on content or code pushes to `main`, after a refresh, or by hand)
1. Tests, then the ledger guard (`scripts/guard_ledger.py`): the new chain must verify and contain every live entry unchanged. A 404 is allowed only before the first deploy.
2. The build (`python -m il.site`) refuses invalid data, then the browser-script tests run.
3. Share images (`scripts/og.py`) are rendered with the runner's Chrome; any image that fails falls back to the default card.
4. Pages deploy, then IndexNow submission of every URL (non-blocking).

**Fails safe:** any failure before the deploy step leaves the previous Pages deployment live.

### `selftest.yml`: weekly self-test (Thursdays 05:41 UTC, or by hand)
- **Tests on `main`.**
- **Live health:**
  - 14 key URLs return 200;
  - the live ledger verifies and is a prefix of the repo ledger;
  - the last data refresh is under 9 days old.
- **Source links:** every cited URL still resolves. Bot walls (401/403/429) and sec.gov (which refuses automated clients without an email) are not counted. The job fails if more than 15% (minimum 3) are broken; fewer is listed in the run summary as content work.
- **Keep-alive** (runs even if the checks fail): see `keepalive.yml` below.

### `keepalive.yml`: called by every scheduled workflow (`refresh.yml` and `selftest.yml`), or by hand
- Re-enables every workflow in `.github/workflows/` through the API.
- If the last commit is 40 or more days old, pushes a heartbeat commit (`.github/heartbeat`). GitHub disables schedules in public repos after 60 days without activity.

Weekly refreshes normally commit `data/live/runs.json`, so the heartbeat rarely fires.

### `ci.yml`: tests on every push and pull request
Python 3.9 and 3.12, the build, and the Node tests of the browser scripts.

## What to watch

| Signal | Where | Healthy |
|---|---|---|
| Workflow runs | Actions tab; failure emails go to the repo owner | Refresh and self-test green weekly |
| Data freshness | `data/live/runs.json` (`last_run`, resolver log, stale sources) and "last fetched" on each chart | Under 9 days old; no source stale over 28 days |
| Resolutions | `/calls/` and new `resolution` entries in `ledger/chain.jsonl` | Automatic calls resolve on schedule; due manual calls are listed by `python -m il.resolve --due` |
| Score | `/calls/` (Brier score once calls resolve) | First automatic call due 2027-01-31 (C14) |
| Corrections | Issues labelled `correction` | Reviewed by the scheduled routine |
| Reach | Bing indexing; GoatCounter once the key is set (`relook_match`, `share`, `ledger_verify`) | Growing |

Calendar of resolutions:
- 2027-01-31: C14 (Medicare codes), automatic
- 2027-04-30: C16 (truckload index), automatic, as soon as March 2027 data is published
- 2027-06-30: C12 (FAA BVLOS rule), automatic
- 2027-10-31: C15 (electricity price), automatic
- 2027-12-31: C1, C3, C4, C19 manual; C13 and C18 automatic
- 2028-01-31: C2 manual; C17 automatic
- 2028-08-01: C5 manual

## Scheduled Claude routine (needs a human to set up once; then runs itself)

Actions has no model API key, so judgement work goes to a scheduled Claude Code routine. Create it from Claude Code's schedule feature (or `/schedule`) on the first of each month, in a checkout of this repo, with this prompt:

> In ~/code/idea-locator-prophet-fund (git pull first):
> 1. Run `python3 -m il.resolve --due`. For each due manual call, research the outcome from primary sources and resolve it with `python3 -m il.resolve <id> yes|no|void --evidence "..." --url https://...`. Use `void` only if the resolver cannot be applied, and say why.
> 2. Refresh hand-collected values: the Pew smartphone series, launch prices and any evidence older than 12 months on live categories. Edit `data/categories/*.json` with sources.
> 3. Take two to four items from `data/backlog.json`. Verify each one's graveyard (named companies, dates, sources) and dates. Add them as categories only if they pass `data.validate`; otherwise record why in the commit message and remove or annotate them.
> 4. Review open issues labelled `correction`. Apply the ones with sources and close them with a comment linking the commit. Never edit a registered call.
> 5. If a verdict should change, edit the category's `verdict` and `verdict_reason`, then run `python3 -m il.register` (the change is dated on the ledger).
> 6. Run `python3 -m unittest discover -s tests -t .` and `python3 -m il.site`, commit, and push. Do not post anywhere.

Without the routine, the automatic parts keep running: 8 of 13 calls resolve themselves, and metrics and the calendar stay current. The 5 manual calls would show "Due, awaiting resolution" after their dates.

## Keys Jack can turn later

| Key | Why | Exact steps |
|---|---|---|
| **Custom domain** | Shorter URL, its own root `robots.txt` (so crawlers see the sitemap) and trust | See LAUNCH.md §5: one CNAME at Namecheap for `ripeness.prophetventures.org`, then set repo variables `IL_CUSTOM_DOMAIN` and `IL_BASE_URL`, run `gh workflow run deploy.yml` and enforce HTTPS in Settings, then Pages |
| **Money: paid fund re-look reports** | First revenue event. GitHub Pages is non-commercial, so the paid flow must live elsewhere | Host a request page or checkout off Pages (for example Stripe Payment Links on a Cloudflare Pages site, or a form on the custom domain's host); Stripe stays in test mode until Jack approves live keys. Set repo variable `IL_RELOOK_REPORT_URL` to that page and redeploy: a "Request a private re-look report" box appears on `/relook/`. Jack's decision: price and NDA terms for handling decks |
| **Analytics** | Measure activation (`relook_match`) and shares | Create a GoatCounter site (free for non-commercial use), set repo variable `IL_GOATCOUNTER=https://<code>.goatcounter.com/count` and redeploy. It is cookieless and honours DNT and GPC |
| **Google Search Console** | Google does not use IndexNow; submitting the sitemap speeds indexing | Needs a Google account and DNS TXT verification on the custom domain, then submit `<domain>/sitemap.xml` |
| **Root robots.txt without a domain** | Crawlers only read `theguysaccount.github.io/robots.txt`, which 404s (allow-all, but the Sitemap line is never seen) | Create repo `theguysaccount/theguysaccount.github.io` with a `robots.txt` listing each project's sitemap. Shared by every project on the account, so it is a decision for whoever owns the account |
| **Design-partner fund** | Private, dated passed-deck graveyards are the asset the research says compounds | Requires outreach and an NDA, both human |
| **Scheduled Claude routine** | Manual resolutions, backlog growth, corrections | Set up once, as above |

## Failure playbook

- **Refresh failed:** open the run. A source error is usually upstream (FRED or World Bank maintenance); the site keeps the last data. If a source moved, fix its URL or parser in `il/refresh.py` and run `gh workflow run refresh.yml`.
- **Deploy refused by the ledger guard:** someone rewrote public history. Restore `ledger/chain.jsonl` from the last deployed commit; add changes as new entries only.
- **Self-test link failures:** replace dead sources in `data/` with archived or primary copies (the run summary lists each URL and page).
- **Schedules disabled anyway:** run any workflow by hand from the Actions tab, or push any commit; the keep-alive resumes.
