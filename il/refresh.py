"""Refresh live data from public sources and resolve due calls.

    python3 -m il.refresh            # fetch everything, resolve, write data/live/*.json and append resolutions
    python3 -m il.refresh --offline  # resolve against the data already on disk (no network)

Every source is fetched independently. A failed fetch keeps the last good data, marks it stale with the
error and the date it started failing, and never blocks the others. Resolutions are appended to the ledger
only when the rule in the call decides it from data actually retrieved.
"""
import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import data, ledger

UA = "idea-locator-prophet-fund/1.0 (+https://github.com/theguysaccount/idea-locator-prophet-fund)"
FR_API = "https://www.federalregister.gov/api/v1/documents.json"
CT_API = "https://clinicaltrials.gov/api/v2/studies"
FR_FIELDS = ["title", "type", "abstract", "action", "agencies", "publication_date", "effective_on", "comments_close_on",
             "document_number", "html_url", "regulation_id_numbers", "docket_ids", "significant"]
STALE_ALERT_DAYS = 28


def now_ts():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def http_get(url, tries=3, timeout=40):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as exc:  # network, HTTP and decode errors are all retried, then reported
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("GET %s failed: %s" % (url, last))


def num_str(v):
    s = repr(float(v))
    if s.endswith(".0"):
        s = s[:-2]
    return s


# ---------------------------------------------------------------- series

def fred_url(series):
    return "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + urllib.parse.quote(series)


def parse_fred(text):
    rows = list(csv.reader(io.StringIO(text)))
    pts = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in (".", ""):
            try:
                pts.append([r[0], num_str(r[1])])
            except ValueError:
                pass
    if not pts:
        raise ValueError("no observations in FRED CSV")
    return pts


def owid_url(slug):
    return "https://ourworldindata.org/grapher/%s.csv?v=1&csvType=full&useColumnShortNames=true" % urllib.parse.quote(slug)


def parse_owid(text, column, entity):
    reader = csv.DictReader(io.StringIO(text))
    pts = []
    for r in reader:
        if r.get("entity") == entity and r.get(column) not in (None, ""):
            pts.append([r["year"], num_str(r[column])])
    if not pts:
        raise ValueError("no %s rows for %s in OWID CSV" % (column, entity))
    return pts


def worldbank_url(country, indicator):
    return "https://api.worldbank.org/v2/country/%s/indicator/%s?format=json&per_page=200" % (country, indicator)


def parse_worldbank(text):
    doc = json.loads(text)
    if not isinstance(doc, list) or len(doc) < 2 or not doc[1]:
        raise ValueError("unexpected World Bank response")
    pts = [[r["date"], num_str(r["value"])] for r in doc[1] if r.get("value") is not None]
    if not pts:
        raise ValueError("no values in World Bank response")
    return sorted(pts)


def fetch_series(src):
    kind = src["kind"]
    if kind == "fred":
        url = fred_url(src["series"])
        return url, parse_fred(http_get(url))
    if kind == "owid":
        url = owid_url(src["slug"])
        return url, parse_owid(http_get(url), src["column"], src.get("entity", "World"))
    if kind == "worldbank":
        url = worldbank_url(src["country"], src["indicator"])
        return url, parse_worldbank(http_get(url))
    raise ValueError("not a fetchable source: %s" % kind)


def mark_stale(rec, err, today):
    rec = dict(rec or {})
    rec["status"] = "stale"
    rec["error"] = str(err)[:300]
    rec.setdefault("failing_since", today)
    return rec


def refresh_metrics(cats, old, today, extra_sources=()):
    out = {}
    sources = {}
    for c in cats:
        m = c.get("metric")
        if m and m["source"]["kind"] != "manual":
            sources[data.series_key(m["source"])] = m["source"]
    for src in extra_sources:
        sources[data.series_key(src)] = src
    for key, src in sorted(sources.items()):
        try:
            url, pts = fetch_series(src)
            out[key] = {"status": "ok", "fetched": now_ts(), "url": url, "points": pts}
            print("  ok   %s (%d points, last %s)" % (key, len(pts), pts[-1][0]))
        except Exception as exc:
            out[key] = mark_stale(old.get(key), exc, today)
            print("  FAIL %s: %s" % (key, exc))
        time.sleep(0.3)
    return out


# ---------------------------------------------------------------- Federal Register

def fr_query_url(q, since=None, extra=None, per_page=20):
    params = [("order", "newest"), ("per_page", str(per_page))]
    for f in FR_FIELDS:
        params.append(("fields[]", f))
    if q.get("term"):
        params.append(("conditions[term]", q["term"]))
    for a in q.get("agencies", []):
        params.append(("conditions[agencies][]", a))
    for t in q.get("types", ["RULE", "PRORULE"]):
        params.append(("conditions[type][]", t))
    if q.get("rin"):
        params.append(("conditions[regulation_id_number]", q["rin"]))
    if since:
        params.append(("conditions[publication_date][gte]", since))
    for k, v in (extra or []):
        params.append((k, v))
    return FR_API + "?" + urllib.parse.urlencode(params)


def slim_doc(d):
    return {
        "document_number": d["document_number"], "title": d["title"], "type": d["type"],
        "action": d.get("action"), "agencies": [a.get("name") for a in d.get("agencies", []) if a.get("name")],
        "publication_date": d["publication_date"], "effective_on": d.get("effective_on"),
        "comments_close_on": d.get("comments_close_on"), "html_url": d["html_url"],
        "rins": d.get("regulation_id_numbers") or [], "dockets": d.get("docket_ids") or [],
        "significant": d.get("significant"),
    }


def refresh_calendar(cats, old, today):
    since = (date.fromisoformat(today) - timedelta(days=540)).isoformat()
    docs = {}
    errors = []
    for c in cats:
        for q in c.get("fr", []):
            try:
                url = fr_query_url(q, since=since)
                res = json.loads(http_get(url)).get("results", [])
                for d in res:
                    s = slim_doc(d)
                    cur = docs.setdefault(s["document_number"], s)
                    cur.setdefault("categories", [])
                    if c["slug"] not in cur["categories"]:
                        cur["categories"].append(c["slug"])
            except Exception as exc:
                errors.append("%s: %s" % (c["slug"], exc))
            time.sleep(0.35)
    if errors and not docs:
        print("  FAIL calendar: %s" % "; ".join(errors[:3]))
        return mark_stale(old, "; ".join(errors[:3]), today)
    items = sorted(docs.values(), key=lambda d: d["publication_date"], reverse=True)
    by_cat = {}
    for d in items:
        for s in d["categories"]:
            by_cat.setdefault(s, []).append(d)

    def rank(d):
        upcoming = (d.get("comments_close_on") or "") >= today or (d.get("effective_on") or "") >= today
        return (0 if upcoming else 1, "" if upcoming else d["publication_date"])

    for s in by_cat:
        up = sorted([d for d in by_cat[s] if rank(d)[0] == 0],
                    key=lambda d: min(x for x in (d.get("comments_close_on"), d.get("effective_on")) if x and x >= today))
        rest = [d for d in by_cat[s] if rank(d)[0] == 1]
        by_cat[s] = up + rest
    print("  ok   calendar (%d documents%s)" % (len(items), ", %d query errors" % len(errors) if errors else ""))
    return {"status": "ok" if not errors else "partial", "fetched": now_ts(), "errors": errors[:10],
            "items": items, "by_category": by_cat}


# ---------------------------------------------------------------- ClinicalTrials.gov

def ct_url(sponsor):
    params = [("query.spons", sponsor), ("pageSize", "50"), ("format", "json")]
    return CT_API + "?" + urllib.parse.urlencode(params)


def parse_ct(text):
    out = []
    for s in json.loads(text).get("studies", []):
        p = s.get("protocolSection", {})
        ident = p.get("identificationModule", {})
        status = p.get("statusModule", {})
        sponsor = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "")
        design = p.get("designModule", {})
        out.append({
            "nct": ident.get("nctId"), "title": ident.get("briefTitle", ""), "official_title": ident.get("officialTitle", ""),
            "status": status.get("overallStatus", ""), "sponsor": sponsor,
            "first_posted": (status.get("studyFirstPostDateStruct") or {}).get("date", ""),
            "start": (status.get("startDateStruct") or {}).get("date", ""),
            "type": design.get("studyType", ""), "phases": design.get("phases", []),
        })
    return out


def refresh_trials(cats, old, today):
    by_cat, errors = {}, []
    for c in cats:
        t = c.get("trials")
        if not t:
            continue
        found = []
        for sp in t.get("sponsors", []):
            try:
                rows = parse_ct(http_get(ct_url(sp)))
                found += [r for r in rows if sp.lower() in r["sponsor"].lower()]
            except Exception as exc:
                errors.append("%s: %s" % (sp, exc))
            time.sleep(0.35)
        found.sort(key=lambda r: r.get("first_posted", ""), reverse=True)
        by_cat[c["slug"]] = found
    if errors and not any(by_cat.values()):
        print("  FAIL trials: %s" % "; ".join(errors[:3]))
        return mark_stale(old, "; ".join(errors[:3]), today)
    print("  ok   trials (%d studies)" % sum(len(v) for v in by_cat.values()))
    return {"status": "ok" if not errors else "partial", "fetched": now_ts(), "errors": errors[:10], "by_category": by_cat}


# ---------------------------------------------------------------- resolvers

def _fred_value(pts, spec):
    """Value for one side of a FRED comparison, or None if the data is not published yet."""
    if "value" in spec:
        return float(spec["value"]), "fixed %s" % spec["value"]
    lookup = {d: float(v) for d, v in pts}
    if "date" in spec:
        if spec["date"] not in lookup:
            return None, None
        return lookup[spec["date"]], "%s = %s" % (spec["date"], lookup[spec["date"]])
    a, b = spec["avg"]
    window = [(d, v) for d, v in lookup.items() if a <= d <= b]
    months = (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7]) + 1
    if len(window) < months:
        return None, None
    val = sum(v for _, v in window) / len(window)
    return val, "average %s..%s = %.3f" % (a, b, val)


def resolve_fred(call, metrics, fetcher=None):
    r = call["resolver"]
    key = "fred:" + r["series"]
    rec = metrics.get(key)
    pts = rec.get("points") if rec else None
    if not pts:
        return None
    left, ltxt = _fred_value(pts, r["left"])
    right, rtxt = _fred_value(pts, r["right"])
    if left is None or right is None:
        return None
    scale = float(r.get("right_scale", "1"))
    right_s = right * scale
    ok = {"gt": left > right_s, "ge": left >= right_s, "lt": left < right_s, "le": left <= right_s}[r["op"]]
    txt = "FRED %s: %s; %s%s; rule %s." % (r["series"], ltxt, rtxt, (" × %s = %.3f" % (r["right_scale"], right_s)) if scale != 1 else "", r["op"])
    return {"outcome": "yes" if ok else "no", "method": "auto:fred",
            "evidence": [{"text": txt, "url": "https://fred.stlouisfed.org/series/" + r["series"]}]}


def resolve_federal_register(call, today, getter=http_get):
    r = call["resolver"]
    q = {"term": r.get("term"), "agencies": [r["agency"]] if r.get("agency") else [], "types": [r.get("type", "RULE")],
         "rin": r.get("rin")}
    url = fr_query_url(q, since=r.get("since"), per_page=50)
    res = json.loads(getter(url)).get("results", [])
    hits = []
    for d in res:
        if d["publication_date"] > call["resolves_on"]:
            continue
        if r.get("since") and d["publication_date"] < r["since"]:
            continue
        title = d.get("title", "").lower()
        if all(t.lower() in title for t in r.get("title_contains", [])):
            hits.append(d)
    if hits:
        d = sorted(hits, key=lambda d: d["publication_date"])[0]
        return {"outcome": "yes", "method": "auto:federal_register",
                "evidence": [{"text": "%s (%s, FR doc %s, published %s)" % (d["title"], d["type"], d["document_number"],
                                                                            d["publication_date"]), "url": d["html_url"]}]}
    if today > call["resolves_on"]:
        return {"outcome": "no", "method": "auto:federal_register",
                "evidence": [{"text": "No matching Federal Register document published by %s." % call["resolves_on"],
                              "url": url.replace("/documents.json", "/documents")}]}
    return None


def resolve_clinicaltrials(call, today, getter=http_get):
    r = call["resolver"]
    rows = parse_ct(getter(ct_url(r["sponsor"])))
    hits = []
    for s in rows:
        if r["sponsor"].lower() not in s["sponsor"].lower():
            continue
        if s.get("type") and s["type"] != "INTERVENTIONAL":
            continue
        fp = s.get("first_posted") or ""
        if not (r["first_posted_after"] <= fp <= call["resolves_on"]):
            continue
        text = (s["title"] + " " + s.get("official_title", "")).lower()
        if r["title_contains"].lower() in text:
            hits.append(s)
    if hits:
        s = sorted(hits, key=lambda s: s["first_posted"])[0]
        return {"outcome": "yes", "method": "auto:clinicaltrials",
                "evidence": [{"text": "%s: %s (first posted %s)" % (s["nct"], s["title"], s["first_posted"]),
                              "url": "https://clinicaltrials.gov/study/" + s["nct"]}]}
    if today > call["resolves_on"]:
        return {"outcome": "no", "method": "auto:clinicaltrials",
                "evidence": [{"text": "No matching study first posted by %s." % call["resolves_on"], "url": ct_url(r["sponsor"])}]}
    return None


def run_resolvers(entries, metrics, today, getter=http_get, write_path=None):
    view = ledger.View(entries)
    log = []
    for cid, e in sorted(view.calls.items()):
        if cid in view.resolutions:
            continue
        call = e["body"]
        kind = call["resolver"]["kind"]
        try:
            if kind == "fred":
                res = resolve_fred(call, metrics)
            elif kind == "federal_register":
                res = resolve_federal_register(call, today, getter)
            elif kind == "clinicaltrials":
                res = resolve_clinicaltrials(call, today, getter)
            else:
                res = None
                if call["resolves_on"] <= today:
                    log.append({"call": cid, "status": "due-manual"})
                continue
        except Exception as exc:
            log.append({"call": cid, "status": "error", "error": str(exc)[:200]})
            continue
        if res is None:
            log.append({"call": cid, "status": "open" if call["resolves_on"] > today else "due-waiting-for-data"})
            continue
        body = {"call": cid, "outcome": res["outcome"], "resolved_on": today, "method": res["method"],
                "evidence": res["evidence"]}
        if write_path:
            ledger.append(write_path, entries, "resolution", body)
        else:
            entries.append(ledger.make_entry(entries, "resolution", body))
        log.append({"call": cid, "status": "resolved", "outcome": res["outcome"]})
        print("  RESOLVED %s -> %s" % (cid, res["outcome"]))
    return log


def stale_sources(live, today, days=STALE_ALERT_DAYS):
    """Sources that have been failing for longer than `days` (the workflow fails on these, after deploying)."""
    out = []
    t = date.fromisoformat(today)

    def old(rec):
        fs = (rec or {}).get("failing_since")
        return rec and rec.get("status") == "stale" and fs and (t - date.fromisoformat(fs)).days > days

    for k, rec in live.get("metrics", {}).items():
        if old(rec):
            out.append(k)
    for name in ("calendar", "trials"):
        if old(live.get(name)):
            out.append(name)
    return out


def main(argv):
    offline = "--offline" in argv
    today = date.today().isoformat()
    cats = data.load_categories()
    live = data.load_live()
    entries = ledger.load(data.LEDGER)
    problems = ledger.verify(entries)
    if problems:
        print("ledger is broken, refusing to touch it:\n  " + "\n  ".join(problems))
        return 1
    if not offline:
        print("metrics:")
        extra = []
        for e in ledger.View(entries).calls.values():
            r = e["body"]["resolver"]
            if r["kind"] == "fred":
                extra.append({"kind": "fred", "series": r["series"]})
        live["metrics"] = refresh_metrics(cats, live["metrics"], today, extra)
        print("calendar:")
        live["calendar"] = refresh_calendar(cats, live["calendar"], today)
        print("trials:")
        live["trials"] = refresh_trials(cats, live["trials"], today)
        data.write_json(data.LIVE + "/metrics.json", live["metrics"])
        data.write_json(data.LIVE + "/calendar.json", live["calendar"])
        data.write_json(data.LIVE + "/trials.json", live["trials"])
    print("resolvers:")
    getter = http_get
    if offline:
        def getter(url):
            raise RuntimeError("offline")
    log = run_resolvers(entries, live["metrics"], today, getter=getter, write_path=data.LEDGER)
    stale = stale_sources(live, today)
    runs = {"last_run": now_ts(), "offline": offline, "resolvers": log, "stale_over_%d_days" % STALE_ALERT_DAYS: stale}
    data.write_json(data.LIVE + "/runs.json", runs)
    for row in log:
        print("  %s %s" % (row["call"], row["status"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
