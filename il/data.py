"""Load and validate the board's source data (data/*.json) and live data (data/live/*.json)."""
import csv
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
LIVE = os.path.join(DATA, "live")
LEDGER = os.path.join(ROOT, "ledger", "chain.jsonl")

KINDS = ("history", "live", "myth")
VERDICTS = {
    # key: (label, short explanation)
    "ripe": ("Ripe", "The constraint that killed the category has crossed, and a named graveyard proves demand."),
    "pending": ("Trigger pending", "A dated, public event will decide it. The board watches the source."),
    "check": ("Blocked on a check", "The call turns on one named check that has not been run yet."),
    "nogo": ("No-go", "The blocker has not moved, or moved the wrong way."),
    "unknown": ("I don't know", "The named blocker never moved, or crossed and the category still died: the board abstains."),
    "formed": ("Formed", "History: the constraint crossed and the category formed."),
    "not-timing": ("Not a timing failure", "A famous 'too early' story that fails the test: the enabler already existed."),
}
LIVE_VERDICTS = ("ripe", "pending", "check", "nogo", "unknown")
VERDICT_ORDER = ("ripe", "pending", "check", "nogo", "unknown", "formed", "not-timing")
ENABLERS = {
    "E1": "Cost curve",
    "E2": "Bandwidth / connectivity",
    "E3": "Device install base",
    "E4": "Labour structure",
    "E5": "Legal permission / regulation",
    "E6": "Behavioural norm",
    "E7": "Algorithmic step",
    "E8": "Capital availability",
    "E9": "Protocol invention",
}
MYTH_TESTS = {
    "competitor": "A competitor succeeded at the same time with the same enablers",
    "unit-economics": "It lost money on every sale; no later enabler fixes that",
    "wrong-product": "The product was wrong at any date",
    "fraud": "Fraud, not timing",
    "inversion": "Cost-curve inversion: it bet a rival technology stays expensive",
    "coordination": "Coordination failure: it needed a whole industry to standardise",
    "capture": "Enabler-owner capture: a partner owned the missing piece and took the market",
}
CONF = ("H", "M", "L")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
URL_RE = re.compile(r"^https://[^\s]+$")


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def load_categories(data_dir=DATA):
    cats = []
    folder = os.path.join(data_dir, "categories")
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json"):
            c = read_json(os.path.join(folder, name))
            c["_file"] = name
            cats.append(c)
    return cats


def load_calls(data_dir=DATA):
    return read_json(os.path.join(data_dir, "calls.json"), [])


def load_slips(data_dir=DATA):
    return read_json(os.path.join(data_dir, "slips.json"), {"rows": []})


def load_live(data_dir=DATA):
    live = os.path.join(data_dir, "live")
    return {
        "metrics": read_json(os.path.join(live, "metrics.json"), {}),
        "calendar": read_json(os.path.join(live, "calendar.json"), {}),
        "trials": read_json(os.path.join(live, "trials.json"), {}),
        "runs": read_json(os.path.join(live, "runs.json"), {}),
    }


def series_key(src):
    """Stable key for a metric source, used as the key in data/live/metrics.json."""
    kind = src["kind"]
    if kind == "fred":
        return "fred:" + src["series"]
    if kind == "owid":
        return "owid:%s:%s:%s" % (src["slug"], src["column"], src.get("entity", "World"))
    if kind == "worldbank":
        return "worldbank:%s:%s" % (src["country"], src["indicator"])
    return None


def metric_points(metric, live):
    """Return ([(date, float)], provenance dict) for a category metric, live data first."""
    src = metric["source"]
    if src["kind"] == "manual":
        pts = [(p["date"], float(p["value"])) for p in src["points"]]
        return pts, {"kind": "manual", "fetched": None, "status": "manual"}
    key = series_key(src)
    rec = live.get("metrics", {}).get(key)
    if not rec or not rec.get("points"):
        return [], {"kind": src["kind"], "fetched": None, "status": "not-fetched", "key": key}
    pts = [(d, float(v)) for d, v in rec["points"]]
    if src.get("from"):
        pts = [p for p in pts if p[0] >= src["from"]]
    return pts, {"kind": src["kind"], "fetched": rec.get("fetched"), "status": rec.get("status", "ok"),
                 "url": rec.get("url"), "key": key}


def _err(errors, cat, msg):
    errors.append("%s: %s" % (cat.get("slug", cat.get("_file")), msg))


def _check_source(errors, cat, where, item, need=True):
    src = item.get("source")
    if src is None:
        if need and not item.get("unlinked"):
            _err(errors, cat, "%s has no source URL (set 'unlinked' with a reason if none exists)" % where)
        return
    if not URL_RE.match(src):
        _err(errors, cat, "%s source is not an https URL: %r" % (where, src))


def validate(cats, calls=None):
    """Return a list of human-readable problems. The build refuses to run if any exist."""
    errors = []
    slugs = set()
    for c in cats:
        for key in ("slug", "name", "kind", "question", "title", "answer", "verdict", "verdict_reason",
                    "enabler", "constraint", "graveyard", "keywords", "updated"):
            if key not in c:
                _err(errors, c, "missing %s" % key)
        if errors and errors[-1].endswith("missing slug"):
            continue
        s = c.get("slug", "")
        if not SLUG_RE.match(s):
            _err(errors, c, "bad slug")
        if s in slugs:
            _err(errors, c, "duplicate slug")
        slugs.add(s)
        if c.get("_file") and c["_file"] != s + ".json":
            _err(errors, c, "file name must be <slug>.json")
        kind, verdict = c.get("kind"), c.get("verdict")
        if kind not in KINDS:
            _err(errors, c, "kind must be one of %s" % (KINDS,))
        if verdict not in VERDICTS:
            _err(errors, c, "unknown verdict %r" % verdict)
        if kind == "history" and verdict != "formed":
            _err(errors, c, "history categories must have verdict 'formed'")
        if kind == "myth" and verdict != "not-timing":
            _err(errors, c, "myth categories must have verdict 'not-timing'")
        if kind == "live" and verdict not in LIVE_VERDICTS:
            _err(errors, c, "live categories need a live verdict")
        if kind == "myth" and c.get("myth_test") not in MYTH_TESTS:
            _err(errors, c, "myth categories need myth_test in %s" % (sorted(MYTH_TESTS),))
        for part in str(c.get("enabler", "")).split("+"):
            if part not in ENABLERS:
                _err(errors, c, "unknown enabler class %r" % part)
        if len(c.get("title", "")) > 70:
            _err(errors, c, "title over 70 characters")
        if not 50 <= len(c.get("answer", "")) <= 520:
            _err(errors, c, "answer should be 50-520 characters (it is the meta description source)")
        if not DATE_RE.match(str(c.get("updated", ""))):
            _err(errors, c, "updated must be YYYY-MM-DD")
        grave = c.get("graveyard", [])
        if verdict in ("ripe", "formed") and not grave:
            _err(errors, c, "a %s verdict needs a named graveyard" % verdict)
        for i, g in enumerate(grave):
            for key in ("name", "how", "conf"):
                if key not in g:
                    _err(errors, c, "graveyard[%d] missing %s" % (i, key))
            if g.get("conf") not in CONF:
                _err(errors, c, "graveyard[%d] conf must be H/M/L" % i)
            raised = g.get("raised_usd_m")
            if raised is not None and not isinstance(raised, (int, float)):
                _err(errors, c, "graveyard[%d] raised_usd_m must be a number or null" % i)
            _check_source(errors, c, "graveyard[%d]" % i, g)
        for i, w in enumerate(c.get("winners", [])):
            _check_source(errors, c, "winners[%d]" % i, w)
        for i, e in enumerate(c.get("evidence", [])):
            if not DATE_RE.match(str(e.get("date", ""))):
                _err(errors, c, "evidence[%d] date must be YYYY[-MM[-DD]]" % i)
            if e.get("conf") not in CONF:
                _err(errors, c, "evidence[%d] conf must be H/M/L" % i)
            _check_source(errors, c, "evidence[%d]" % i, e)
        m = c.get("metric")
        if m:
            src = m.get("source", {})
            if src.get("kind") not in ("manual", "fred", "owid", "worldbank"):
                _err(errors, c, "metric source kind must be manual/fred/owid/worldbank")
            if src.get("kind") == "manual":
                if not src.get("points"):
                    _err(errors, c, "manual metric needs points")
                for i, p in enumerate(src.get("points", [])):
                    if not DATE_RE.match(str(p.get("date", ""))):
                        _err(errors, c, "metric point %d date" % i)
                    try:
                        float(p.get("value"))
                    except (TypeError, ValueError):
                        _err(errors, c, "metric point %d value must be numeric (as a string)" % i)
                    _check_source(errors, c, "metric point %d" % i, p)
            if m.get("direction") not in ("up", "down"):
                _err(errors, c, "metric direction must be up or down")
            for key in ("label", "unit"):
                if not m.get(key):
                    _err(errors, c, "metric missing %s" % key)
        if not c.get("keywords"):
            _err(errors, c, "keywords are needed for the re-look screen")
        for r in c.get("related", []):
            if r not in {x.get("slug") for x in cats}:
                _err(errors, c, "related slug %r does not exist" % r)
    if calls is not None:
        ids = set()
        for call in calls:
            cid = call.get("id", "?")
            if cid in ids:
                errors.append("calls.json: duplicate id %s" % cid)
            ids.add(cid)
            cat = call.get("category")
            if cat and cat not in slugs:
                errors.append("calls.json: %s references unknown category %s" % (cid, cat))
            if not isinstance(call.get("p_pct"), int) or not 1 <= call["p_pct"] <= 99:
                errors.append("calls.json: %s p_pct must be an integer 1-99" % cid)
            if not DATE_RE.match(str(call.get("resolves_on", ""))) or len(call.get("resolves_on", "")) != 10:
                errors.append("calls.json: %s resolves_on must be YYYY-MM-DD" % cid)
            kind = call.get("resolver", {}).get("kind")
            if kind not in ("manual", "federal_register", "fred", "clinicaltrials"):
                errors.append("calls.json: %s resolver kind %r" % (cid, kind))
            for key in ("statement", "falsifier", "rationale"):
                if not call.get(key):
                    errors.append("calls.json: %s missing %s" % (cid, key))
    return errors


def to_csv(rows, fields):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
