# LAUNCH: machine-driven

The board launches and grows without anyone posting or sending anything. This file covers what is live, how a deploy happens, how people find the board, and the optional domain step.

## 1. What's live

- **Site:** https://theguysaccount.github.io/idea-locator-prophet-fund/ (GitHub Pages, deployed by `deploy.yml`)
- **Ledger:** https://theguysaccount.github.io/idea-locator-prophet-fund/ledger/chain.jsonl (verify in the browser on `/calls/`)
- **Data:** `/data/board.json`, `/data/graveyard.csv`, `/data/slips.csv`, `/data/relook.json` (CC BY 4.0)

## 2. How a deploy happens

1. A push to `main` that touches `il/`, `data/`, `ledger/`, `site/` or `scripts/` runs `deploy.yml`. So does `refresh.yml` (by dispatch) after new data, and `gh workflow run deploy.yml` by hand.
2. `deploy.yml` runs the tests, then the ledger guard (the new chain must extend the live one), then builds `dist/` and runs the browser-script tests.
3. It renders the share images with the runner's Chrome, uploads the artifact and deploys to Pages.
4. Finally it submits every URL to IndexNow.

Any failure stops before deploying, and Pages keeps serving the last good build.

## 3. How people find it (machine channels only)

| Channel | What is in place |
|---|---|
| Search | One page per category, titled for the question people search (e.g. "Why Webvan failed, and when online grocery became viable", "Is vertical farming viable again?"), each with a sourced answer in the first paragraph |
| Structured data | `WebSite` and `Dataset` on home; `Article` and `BreadcrumbList` on category pages; `Dataset` with `DataDownload` on the ledger, graveyard and slip pages |
| Sitemap and robots | `sitemap.xml` (66 URLs) and `robots.txt`. The account-level `theguysaccount.github.io/robots.txt` does not exist, which means "allow all"; the sitemap is announced through IndexNow and internal links instead (see OPERATIONS.md for the fix) |
| IndexNow | The key file is published at the site root, and every deploy submits all URLs. That covers Bing, Yandex, Seznam and Naver; Bing powers several AI answer engines |
| Share loop | Every call page has a 1200×630 share card, native share, X, LinkedIn, email and copy-link buttons, a citation and an embed code (`/embed/<slug>/`) that updates when the call resolves |
| AI answer engines | A plain-language answer first, dated evidence with sources, JSON downloads and a stable ledger. These are the properties answer engines quote |
| GitHub | Public repo with a description, topics and open data, discoverable through GitHub search and topic pages |

Search terms each page is built to answer:
- `why did <company> fail`
- `was <company> too early`
- `is <category> viable again`
- `<category> startups failed why`
- `regulatory deadlines slip how often`
- `startup graveyard dataset`
- `drone delivery FAA part 108 final rule`
- `supersonic overland ban repeal`
- `Medicare digital therapeutics billing codes G0552`

## 4. The first 14 days (automatic)

| Day | What the automation does | What to look at (optional) |
|---|---|---|
| 0 | Deploy, share images, IndexNow submission of all 66 URLs | Actions tab green; Bing `site:theguysaccount.github.io/idea-locator-prophet-fund` |
| 1 (Mon) | `refresh.yml`: metrics, Federal Register calendar, trials; resolvers run; commit and redeploy if anything changed | New "Refresh data" commit |
| 4 (Thu) | `selftest.yml`: live health, ledger match, source links, keep-alive | Run summary |
| 8, 15 | Weekly refreshes; the calendar picks up new FAA, CMS, NRC, FMCSA and FERC documents | `/calendar/` |
| any | Visitors open correction issues (label `correction`) | Issues tab |

Signals of use that need no analytics account:
- GitHub stars and forks;
- correction issues;
- Bing indexing;
- referrers, once `IL_GOATCOUNTER` is set.

## 5. Production domain (needs Jack; nothing is blocked without it)

Candidates, owned names first:
1. **ripeness.prophetventures.org.** `prophetventures.org` is owned (Namecheap, created 2026-04-01) and is the Prophet line's venture brand. One record, no purchase.
2. **ripenessboard.com.** Unregistered per WHOIS on 2026-10-25, about $10/yr. Needs Jack's OK to spend.
3. **ripeagain.com.** Unregistered per WHOIS on 2026-10-25. Backup.

(`prophet.fund` is not owned and `idealocator.com` is registered to someone else.)

Steps for option 1:
1. At Namecheap (prophetventures.org, Advanced DNS), add `CNAME  ripeness  theguysaccount.github.io.`
2. In the repo, set these variables: `IL_CUSTOM_DOMAIN=ripeness.prophetventures.org` and `IL_BASE_URL=https://ripeness.prophetventures.org`.
3. Run `gh workflow run deploy.yml`. The build writes `dist/CNAME`, canonical URLs and the sitemap with the new origin.
4. Repo Settings, then Pages: confirm the custom domain and tick "Enforce HTTPS" once the certificate is issued (usually under an hour).
5. Then 301 the other Prophet redirect domains (prophait.com, makeprophet.com, maxprophets.com, prophetnode.com, propheticventures.org, metaprophet.org) to the new origin at the registrar.

For an apex domain (options 2 and 3):
- A records `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
- AAAA records `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153`
- `CNAME www theguysaccount.github.io.`

Then do steps 2-4.
