"""Weekly self-test of the live site and of every cited source.

    python3 scripts/health.py live  [base_url]   # the deployed site answers and matches the repo
    python3 scripts/health.py links              # every source URL in data/ still resolves
    python3 scripts/health.py stale              # a data source has been failing for over four weeks

Each mode prints a report (also appended to $GITHUB_STEP_SUMMARY when set) and exits 1 on failure.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from il import data, ledger, refresh  # noqa: E402

UA = "idea-locator-prophet-fund/1.0 (+https://github.com/theguysaccount/idea-locator-prophet-fund)"
BROWSER_UA = "Mozilla/5.0 (compatible; idea-locator-linkcheck/1.0; +https://github.com/theguysaccount/idea-locator-prophet-fund)"
DEFAULT_BASE = "https://theguysaccount.github.io/idea-locator-prophet-fund"
# Hosts that refuse automated clients without a contact email or behind bot walls. They are checked by
# people when edited, not weekly, so a block here is not counted as a broken link.
SKIP_HOSTS = ("www.sec.gov", "sec.gov", "www.bloomberg.com", "www.reuters.com")


def report(lines):
    text = "\n".join(lines)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n\n")


def get(url, ua=UA, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def check_live(base):
    base = base.rstrip("/")
    out, failed = ["## Live site", ""], False
    cats = data.load_categories()
    pages = ["/", "/calls/", "/relook/", "/calendar/", "/graveyard/", "/slips/", "/method/", "/about/",
             "/category/%s/" % cats[0]["slug"], "/category/%s/" % cats[-1]["slug"], "/sitemap.xml", "/data/board.json",
             "/data/relook.json", "/ledger/chain.jsonl"]
    for p in pages:
        try:
            status, body = get(base + p + "?selftest=%d" % int(time.time()))
            ok = status == 200 and len(body) > 200
        except Exception as exc:
            status, ok = str(exc), False
        failed |= not ok
        out.append("- %s %s %s" % ("ok  " if ok else "FAIL", p, status))
    # The live ledger must be the repo's ledger, or a prefix of it while a deploy is pending.
    try:
        _, body = get(base + "/ledger/chain.jsonl?selftest=%d" % int(time.time()))
        live = [json.loads(l) for l in body.decode("utf-8").splitlines() if l.strip()]
        repo = ledger.load(data.LEDGER)
        if ledger.verify(live):
            failed = True
            out.append("- FAIL live ledger does not verify")
        elif not ledger.is_prefix(live, repo):
            failed = True
            out.append("- FAIL live ledger is not a prefix of the repository ledger")
        else:
            out.append("- ok   ledger: %d live entries, %d in the repository" % (len(live), len(repo)))
    except Exception as exc:
        failed = True
        out.append("- FAIL ledger check: %s" % exc)
    runs = data.read_json(os.path.join(data.LIVE, "runs.json"), {})
    last = runs.get("last_run")
    if last:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
        stale = age > 9
        failed |= stale
        out.append("- %s last data refresh %s (%d days ago)" % ("FAIL" if stale else "ok  ", last, age))
    report(out)
    return 1 if failed else 0


def source_urls():
    urls = {}
    for c in data.load_categories():
        for group in ("graveyard", "winners", "evidence"):
            for item in c.get(group, []):
                if item.get("source"):
                    urls.setdefault(item["source"], c["slug"])
        m = c.get("metric")
        if m:
            for p in m["source"].get("points", []):
                if p.get("source"):
                    urls.setdefault(p["source"], c["slug"])
            if m.get("source_page"):
                urls.setdefault(m["source_page"], c["slug"])
    for r in data.load_slips()["rows"]:
        if r.get("source"):
            urls.setdefault(r["source"], "slips")
    return urls


def check_one(url):
    host = url.split("/")[2]
    if host in SKIP_HOSTS:
        return url, "skipped", True
    last = None
    for attempt in range(2):
        try:
            status, _ = get(url, ua=BROWSER_UA, timeout=25)
            return url, status, 200 <= status < 400
        except urllib.error.HTTPError as exc:
            last = exc.code
            if exc.code in (401, 403, 429):  # bot walls are not dead links
                return url, exc.code, True
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(2)
    return url, last, False


def check_links():
    urls = source_urls()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check_one, sorted(urls)))
    broken = [(u, s) for u, s, ok in results if not ok]
    out = ["## Source links", "", "%d URLs checked, %d broken" % (len(results), len(broken))]
    for u, s in broken:
        out.append("- %s (%s) on %s" % (u, s, urls[u]))
    report(out)
    # A handful of dead links is a content task, not an outage; a large share means something systemic.
    return 1 if len(broken) > max(3, 0.15 * len(results)) else 0


def check_stale():
    live = data.load_live()
    stale = refresh.stale_sources(live, date.today().isoformat())
    report(["## Data sources", "", "stale for over %d days: %s" % (refresh.STALE_ALERT_DAYS, ", ".join(stale) or "none")])
    return 1 if stale else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    if mode == "live":
        sys.exit(check_live(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("IL_BASE_URL", DEFAULT_BASE)))
    if mode == "links":
        sys.exit(check_links())
    if mode == "stale":
        sys.exit(check_stale())
    sys.exit("unknown mode %s" % mode)
