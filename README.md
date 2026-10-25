# Idea Locator: the ripeness board

**Live:** https://theguysaccount.github.io/idea-locator-prophet-fund/ · **Ledger:** [calls, verdicts and resolutions](https://theguysaccount.github.io/idea-locator-prophet-fund/calls/) · **Data (CC BY 4.0):** [board.json](https://theguysaccount.github.io/idea-locator-prophet-fund/data/board.json), [graveyard.csv](https://theguysaccount.github.io/idea-locator-prophet-fund/data/graveyard.csv), [slips.csv](https://theguysaccount.github.io/idea-locator-prophet-fund/data/slips.csv) · **Screens:** [docs/screens](docs/screens/)

A public, dated, hash-chained record of calls on whether failed startup categories are viable again. Each category names:
- the constraint that killed it (a cost, a law, a capability, an install base);
- the metric that has moved since, refreshed from public data;
- the funded companies that died proving demand, each with a source;
- a dated call with a probability, a resolver and a falsifier, frozen on an append-only SHA-256 chain before it resolves.

The rule behind it: a category is worth re-attempting when funded companies already burned real money proving the demand **and** the specific constraint that killed them has since crossed a threshold. Webvan and Instacart are the canonical pair. The [method page](https://theguysaccount.github.io/idea-locator-prophet-fund/method/) has the backtests and every test that failed.

Also on the site:
- a **re-look screen** that maps a fund's passed deals to categories, privately in the browser;
- a **regulatory unlock calendar** from the Federal Register;
- a **slip corpus** of how often dated commitments actually happen on time;
- a **graveyard** dataset.

## How it runs (no human in the loop)

| Job | Workflow | When | Fails safe because |
|---|---|---|---|
| Refresh metrics (FRED, World Bank, OWID), the Federal Register calendar and ClinicalTrials.gov; resolve calls whose rule can now be decided; commit; redeploy | `refresh.yml` | Mondays 06:17 UTC | each source fails independently and keeps its last good data; tests run before any commit |
| Test, guard the ledger, build, render share images, deploy to Pages, ping IndexNow | `deploy.yml` | on content or code changes, after a refresh, or by hand | tests, the build or the ledger guard failing stops the job; Pages keeps the last good deploy |
| Live health check, source link check, tests on main, keep-alive | `selftest.yml` | Thursdays 05:41 UTC | read-only checks; keep-alive re-enables schedules and pushes a heartbeat after 40 quiet days |
| Tests on every push and pull request (Python 3.9 and 3.12) | `ci.yml` | every push | n/a |

Details, alerts and the keys a human can turn later: [OPERATIONS.md](OPERATIONS.md).

## Layout

```
il/              Python 3.9+, standard library only
  data.py        load and validate data/ (the build refuses invalid data)
  ledger.py      append-only hash chain: canonical JSON, verify, prefix check
  register.py    write new calls and verdict changes onto the ledger
  refresh.py     fetch public data, build the calendar, run automatic resolvers
  resolve.py     resolve a manual call with evidence (used by the scheduled review)
  site.py        static site generator (pages, embeds, share-card HTML, sitemap, data exports)
  charts.py      server-rendered SVG charts
data/
  categories/    one JSON file per category: verdict, constraint, metric, graveyard, evidence, sources
  calls.json     calls to register (once registered, the ledger is the source of truth)
  slips.json     the slip corpus
  backlog.json   candidate categories for the scheduled review to verify
  live/          fetched data (metrics, calendar, trials, run log), committed by refresh.yml
ledger/chain.jsonl   the ledger
site/            CSS, browser scripts (share, ledger verifier, re-look), static page bodies, IndexNow key
scripts/         share images (og.py), ledger guard, IndexNow, health and link checks, screenshots
tests/           unittest suites + Node tests for the browser scripts
```

## Run, test, deploy

```bash
python3 -m il.refresh          # fetch public data and resolve due calls (no keys needed)
python3 -m il.site             # build into dist/
python3 scripts/og.py          # optional: render share images with local Chrome
python3 -m http.server 4731 --directory dist
```

```bash
python3 -m unittest discover -s tests -t .
node --test tests/js.test.mjs  # after a build; checks the browser verifier and re-look matcher
```

Deploys happen on push to `main` (`deploy.yml`). To deploy by hand: `gh workflow run deploy.yml`.

### Changing content
- **Edit a category:** change `data/categories/<slug>.json`, then run `python3 -m il.register`. A verdict change is appended to the ledger with today's date. Then run the tests.
- **Add a call:** append it to `data/calls.json` and run `python3 -m il.register`. Registered calls can never change; to revise a view, add a new call.
- **Resolve a manual call:** `python3 -m il.resolve <id> yes|no|void --evidence "..." --url https://...`.

The deploy job refuses to publish a ledger that does not extend the one already live (`scripts/guard_ledger.py`).

## Settings (repository variables; all optional)

`IL_BASE_URL`, `IL_CUSTOM_DOMAIN`, `IL_GOATCOUNTER` (cookieless analytics), `IL_RELOOK_REPORT_URL` (the money slot). See [.env.example](.env.example) and [OPERATIONS.md](OPERATIONS.md).

## Licence

Code MIT; content and data CC BY 4.0. See [LICENSE](LICENSE). Research, not investment advice.
