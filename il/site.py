"""Build the static site into dist/ from data/, data/live/ and the ledger.

    python3 -m il.site            # build into dist/
    IL_OUT=/tmp/x python3 -m il.site

Environment (all optional):
    IL_BASE_URL            canonical origin + path (default: the GitHub Pages URL)
    IL_REPO                owner/name for correction links (default theguysaccount/idea-locator-prophet-fund)
    IL_GOATCOUNTER         https://<code>.goatcounter.com/count  (cookieless analytics; off when empty)
    IL_RELOOK_REPORT_URL   link for private fund re-look reports (the money slot; off when empty)
    IL_TODAY               YYYY-MM-DD override, for tests
    IL_OUT                 output directory (default dist/)
"""
import json
import os
import shutil
import sys
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import quote

from . import charts, data, ledger

ROOT = data.ROOT
SITE_NAME = "Idea Locator"
TAGLINE = "Dated calls on whether dead startup categories are ripe again"
DEFAULT_BASE = "https://theguysaccount.github.io/idea-locator-prophet-fund"
DEFAULT_REPO = "theguysaccount/idea-locator-prophet-fund"


def esc(s):
    return escape(str(s), quote=True)


def money_m(m):
    if m is None:
        return "undisclosed"
    if m >= 1000:
        return "$%.1fB" % (m / 1000.0)
    return "$%sM" % ("{:,.0f}".format(m) if m >= 10 else ("%.1f" % m).rstrip("0").rstrip("."))


def clip(text, n):
    """Shorten text to at most n characters at a word boundary, with an ellipsis."""
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "\u2026"


def short(h, n=10):
    return h[:n]


class Ctx:
    """Per-build configuration and derived data shared by all pages."""

    def __init__(self, out=None, today=None):
        self.base = os.environ.get("IL_BASE_URL", DEFAULT_BASE).rstrip("/")
        self.repo = os.environ.get("IL_REPO", DEFAULT_REPO)
        self.goat = os.environ.get("IL_GOATCOUNTER", "").strip()
        self.report_url = os.environ.get("IL_RELOOK_REPORT_URL", "").strip()
        self.today = today or os.environ.get("IL_TODAY") or date.today().isoformat()
        self.out = out or os.environ.get("IL_OUT") or os.path.join(ROOT, "dist")
        self.built = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.urls = []  # (path, lastmod) for the sitemap


class Page:
    def __init__(self, ctx, path):
        self.ctx = ctx
        self.path = path  # "" for home, "category/x/" for others, "404.html" for files
        depth = 0 if path in ("", "404.html") else path.rstrip("/").count("/") + 1
        if path.endswith(".html"):
            depth = path.count("/")
        self.prefix = "../" * depth

    def u(self, target=""):
        return self.prefix + target

    @property
    def canonical(self):
        return self.ctx.base + "/" + self.path


# ---------------------------------------------------------------- derived data

def derive(ctx, cats, entries, live, slips):
    view = ledger.View(entries)
    by_slug = {c["slug"]: c for c in cats}
    for c in cats:
        c["_calls"] = sorted(view.calls_for(c["slug"]), key=lambda e: e["seq"])
        v = view.verdicts.get(c["slug"])
        c["_verdict_entry"] = v
        c["_verdict"] = v["body"]["verdict"] if v else c["verdict"]
        c["_verdict_since"] = v["ts"][:10] if v else None
        hist = view.verdict_history.get(c["slug"], [])
        c["_first_seen"] = hist[0]["ts"][:10] if hist else ctx.today
        c["_capital"] = sum(g["raised_usd_m"] for g in c["graveyard"] if g.get("raised_usd_m"))
        c["_metric"] = None
        m = c.get("metric")
        if m:
            pts, prov = data.metric_points(m, live)
            info = {"points": pts, "prov": prov}
            if pts:
                pts_sorted = sorted(pts, key=lambda p: charts.year_frac(p[0]))
                then = None
                if m.get("then"):
                    tf = charts.year_frac(m["then"])
                    cands = [p for p in pts_sorted if charts.year_frac(p[0]) <= tf + 0.001]
                    then = cands[-1] if cands else pts_sorted[0]
                else:
                    then = pts_sorted[0]
                now = pts_sorted[-1]
                info["then"], info["now"] = then, now
                if then[1] and now[1]:
                    ratio = now[1] / then[1]
                    better = ratio if m["direction"] == "up" else (1 / ratio if ratio else None)
                    info["better_x"] = better
                info["stale"] = prov.get("status") == "stale"
            c["_metric"] = info
        cal = live.get("calendar", {}).get("by_category", {}).get(c["slug"], [])
        c["_fr"] = cal
        c["_trials"] = live.get("trials", {}).get("by_category", {}).get(c["slug"], [])
    return view, by_slug


def call_status(view, cid, today):
    s = view.status(cid, today)
    if s == "resolved":
        r = view.resolutions[cid]["body"]
        return "resolved", r["outcome"]
    return s, None


def resolver_text(res):
    k = res["kind"]
    if k == "federal_register":
        bits = []
        if res.get("rin"):
            bits.append("RIN %s" % res["rin"])
        if res.get("term"):
            bits.append("full text contains “%s”" % res["term"])
        if res.get("agency"):
            bits.append("agency %s" % res["agency"])
        if res.get("title_contains"):
            bits.append("title contains %s" % " and ".join("“%s”" % t for t in res["title_contains"]))
        return "Automatic: Federal Register API, document type %s, %s, published %s or later." % (
            res.get("type", "RULE"), ", ".join(bits), res.get("since", "any date"))
    if k == "fred":
        def side(s):
            if "value" in s:
                return s["value"]
            if "date" in s:
                return "the %s observation" % s["date"][:7]
            return "the average of %s to %s" % (s["avg"][0][:7], s["avg"][1][:7])
        ops = {"gt": "is above", "ge": "is at or above", "lt": "is below", "le": "is at or below"}
        txt = "Automatic: FRED series %s, %s %s %s" % (res["series"], side(res["left"]), ops[res["op"]], side(res["right"]))
        if res.get("right_scale"):
            txt += " × %s" % res["right_scale"]
        return txt + ", using the first published values."
    if k == "clinicaltrials":
        return ("Automatic: ClinicalTrials.gov API, an interventional study sponsored by %s, first posted on or after %s, "
                "with “%s” in its title." % (res["sponsor"], res["first_posted_after"], res["title_contains"]))
    return "Manual: %s Resolved by a scheduled review that appends the outcome and its evidence to the ledger." % res.get(
        "how", "")


# ---------------------------------------------------------------- layout

NAV = [("", "Board"), ("calls/", "Ledger"), ("relook/", "Re-look"), ("calendar/", "Calendar"),
       ("graveyard/", "Graveyard"), ("slips/", "Slips"), ("method/", "Method")]


def layout(pg, title, description, body, og_image=None, jsonld=None, noindex=False, body_class=""):
    ctx = pg.ctx
    full_title = title if title.endswith(SITE_NAME) else "%s | %s" % (title, SITE_NAME)
    og = og_image or "og/default.png"
    lds = jsonld if isinstance(jsonld, list) else ([jsonld] if jsonld else [])
    head = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % esc(full_title),
        '<meta name="description" content="%s">' % esc(description),
        '<link rel="canonical" href="%s">' % esc(pg.canonical),
        '<meta property="og:type" content="%s">' % ("article" if pg.path.startswith("category/") else "website"),
        '<meta property="og:site_name" content="%s">' % SITE_NAME,
        '<meta property="og:title" content="%s">' % esc(title),
        '<meta property="og:description" content="%s">' % esc(description),
        '<meta property="og:url" content="%s">' % esc(pg.canonical),
        '<meta property="og:image" content="%s/%s">' % (esc(ctx.base), esc(og)),
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="theme-color" content="#0f172a">',
        '<link rel="icon" href="%s" type="image/svg+xml">' % pg.u("assets/favicon.svg"),
        '<link rel="stylesheet" href="%s">' % pg.u("assets/style.css?v=" + ctx.asset_v),
        '<link rel="alternate" type="application/json" title="Board data" href="%s">' % pg.u("data/board.json"),
    ]
    if noindex:
        head.append('<meta name="robots" content="noindex">')
    if ctx.goat:
        head.append('<meta name="il-goatcounter" content="%s">' % esc(ctx.goat))
    for ld in lds:
        head.append('<script type="application/ld+json">%s</script>'
                    % json.dumps(ld, ensure_ascii=False).replace("</", "<\\/"))
    head.append("</head>")
    nav = "".join('<a href="%s"%s>%s</a>' % (pg.u(p), ' aria-current="page"' if p == pg.path else "", esc(n))
                  for p, n in NAV)
    header = ('<header class="site"><div class="wrap"><a class="brand" href="%s"><span class="dot"></span>%s</a>'
              '<nav aria-label="Main">%s</nav></div></header>' % (pg.u(""), SITE_NAME, nav))
    footer = (
        '<footer class="site"><div class="wrap">'
        '<p><strong>%s</strong> keeps a public, dated, hash-chained record of calls on when failed startup categories '
        'become viable again. Built and refreshed by automation from public sources. '
        '<a href="%s">About and method</a> · <a href="%s">Data downloads</a> · '
        '<a href="https://github.com/%s">Source on GitHub</a> · '
        '<a href="https://github.com/%s/issues/new?labels=correction&title=Correction">Report an error</a></p>'
        '<p class="fine">Research, not investment advice: nothing here recommends buying, selling or funding anything. '
        'Content CC BY 4.0, code MIT. Rebuilt %s · ledger head <code>%s</code>.</p>'
        "</div></footer>" % (SITE_NAME, pg.u("about/"), pg.u("about/#data"), esc(ctx.repo), esc(ctx.repo),
                             esc(ctx.today), esc(short(ctx.head, 12))))
    scripts = '<script src="%s" defer></script>' % pg.u("assets/app.js?v=" + ctx.asset_v)
    return "".join(head) + '<body class="%s">%s<main id="main" class="wrap">%s</main>%s%s</body></html>' % (
        esc(body_class), header, body, footer, scripts)


def badge(v):
    label = data.VERDICTS[v][0]
    return '<span class="badge v-%s">%s</span>' % (esc(v), esc(label))


def conf_tag(c):
    names = {"H": "high confidence: primary or legal source", "M": "medium confidence: widely reported",
             "L": "low confidence: single or secondary source"}
    return '<abbr class="conf conf-%s" title="%s">%s</abbr>' % (c, names.get(c, ""), c)


def src_link(item, text="source"):
    if item.get("source"):
        return '<a href="%s" rel="nofollow noopener" target="_blank">%s</a>' % (esc(item["source"]), esc(text))
    if item.get("unlinked"):
        return '<span class="unlinked" title="%s">unlinked</span>' % esc(item["unlinked"])
    return ""


def years(g):
    f, d = g.get("founded"), g.get("died")
    if f and d:
        return "%s–%s" % (f, d)
    if d:
        return "died %s" % d
    return str(f or "")


# ---------------------------------------------------------------- category

def metric_block(pg, c):
    m, info = c.get("metric"), c.get("_metric")
    if not m or not info:
        return ""
    pts, prov = info["points"], info["prov"]
    caption_src = ""
    if prov["kind"] == "manual":
        firsts = [p for p in m["source"]["points"] if p.get("source")]
        caption_src = "Hand-collected from %s; refreshed by review, not automatically." % (
            ", ".join(sorted({'<a href="%s" rel="nofollow noopener" target="_blank">%s</a>'
                              % (esc(p["source"]), esc(p.get("source_name", "source"))) for p in firsts})) or "the sources listed")
    else:
        names = {"fred": "FRED (Federal Reserve Bank of St. Louis)", "owid": "Our World in Data",
                 "worldbank": "World Bank Open Data"}
        when = prov.get("fetched")
        caption_src = 'Live series from <a href="%s" rel="nofollow noopener" target="_blank">%s</a>%s, refreshed by the weekly job%s.' % (
            esc(m.get("source_page") or prov.get("url") or "#"), names[prov["kind"]],
            (" (%s)" % esc(m["source_note"])) if m.get("source_note") else "",
            (", last fetched %s" % esc(when[:10])) if when else "")
        if prov["status"] == "not-fetched":
            caption_src += " Not fetched yet in this build."
        if prov["status"] == "stale":
            caption_src += ' <strong class="warn">The last fetch failed; showing the last good values.</strong>'
    svg = charts.line_chart(pts, m["label"], unit=m["unit"], log=m.get("log", False), marks=m.get("marks", []),
                            threshold=m.get("threshold"))
    summary = ""
    if info.get("then") and info.get("now"):
        t, n = info["then"], info["now"]
        bx = info.get("better_x")
        moved = ""
        if bx:
            if bx >= 1.25:
                moved = "%s better for the category" % ("%.1f×" % bx if bx < 100 else "{:,.0f}×".format(bx))
            elif bx <= 0.8:
                moved = "%.1f× worse for the category" % (1 / bx)
            else:
                moved = "barely moved"
        summary = ('<p class="metric-sum"><span>%s</span> <b>%s</b> → <span>%s</span> <b>%s</b>%s</p>'
                   % (esc(charts.fmt_date(t[0])), esc(charts.fmt_value(t[1], m["unit"])), esc(charts.fmt_date(n[0])),
                      esc(charts.fmt_value(n[1], m["unit"])), (' <em>(%s)</em>' % moved) if moved else ""))
    rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(charts.fmt_date(d)), esc(charts.fmt_value(v, m["unit"])))
                   for d, v in sorted(pts, key=lambda p: charts.year_frac(p[0]), reverse=True)[:60])
    table = ('<details class="data"><summary>Data table</summary><table><thead><tr><th>Date</th><th>%s</th></tr></thead>'
             "<tbody>%s</tbody></table></details>" % (esc(m["label"]), rows)) if rows else ""
    note = ('<p class="fine">%s</p>' % esc(m["note"])) if m.get("note") else ""
    return ('<section class="panel" id="metric"><h2>The metric that moved</h2><p class="lede">%s</p>%s%s'
            '<p class="fine">%s</p>%s%s</section>' % (esc(m["label"]), summary, ('<div class="scroll chart-wrap">%s</div>' % svg) if svg else '<p class="fine">Not enough data points to chart yet.</p>',
                                                    caption_src, note, table))


def graveyard_block(c):
    g = c["graveyard"]
    if not g:
        msg = c.get("graveyard_note") or ("No named graveyard yet. The board will not call a category ripe until funded "
                                          "companies that died on this constraint are named and sourced.")
        return '<section class="panel" id="graveyard"><h2>Graveyard</h2><p class="callout">%s</p></section>' % esc(msg)
    rows = []
    for x in g:
        raised = money_m(x.get("raised_usd_m")) if x.get("raised_usd_m") is not None else "—"
        rows.append("<tr><td><strong>%s</strong>%s</td><td>%s</td><td>%s%s</td><td>%s</td><td>%s %s</td></tr>" % (
            esc(x["name"]), ('<br><span class="fine">%s</span>' % esc(x["note"])) if x.get("note") else "",
            esc(years(x)), esc(raised), ('<br><span class="fine">%s</span>' % esc(x["raised_note"])) if x.get("raised_note") else "",
            esc(x["how"]), src_link(x), conf_tag(x["conf"])))
    total = c["_capital"]
    head = ("Companies that died proving people wanted this. Capital shown where it was disclosed%s."
            % (", %s in total" % money_m(total) if total else ""))
    note = ('<p class="fine">%s</p>' % esc(c["graveyard_note"])) if c.get("graveyard_note") else ""
    return ('<section class="panel" id="graveyard"><h2>Graveyard</h2><p class="lede">%s</p><div class="scroll"><table class="grave">'
            "<thead><tr><th>Company</th><th>Years</th><th>Capital</th><th>How it died</th><th>Source</th></tr></thead>"
            "<tbody>%s</tbody></table></div>%s</section>" % (head, "".join(rows), note))


def calls_block(pg, c, view):
    if not c["_calls"]:
        return ""
    items = []
    for e in c["_calls"]:
        b = e["body"]
        st, outcome = call_status(view, b["id"], pg.ctx.today)
        if st == "resolved":
            status = '<span class="st st-%s">Resolved: %s</span>' % (esc(outcome), esc(outcome.upper()))
        elif st == "due":
            status = '<span class="st st-due">Due, awaiting resolution</span>'
        else:
            status = '<span class="st st-open">Open</span>'
        items.append(
            '<article class="call" id="%s"><header><span class="pp">%d%%</span><div><h3>%s</h3><p class="fine">%s · '
            "resolves %s · registered %s%s</p></div></header>"
            "<dl><dt>Resolver</dt><dd>%s</dd><dt>Falsified if</dt><dd>%s</dd><dt>Why this probability</dt><dd>%s</dd></dl>"
            '<p class="hash">ledger #%d · <code title="%s">%s…</code> · <a href="%s">verify</a></p></article>'
            % (esc(b["id"]), b["p_pct"], esc(b["statement"]), status, esc(b["resolves_on"]), esc(e["ts"][:10]),
               (" · first stated %s" % esc(b["first_stated"])) if b.get("first_stated") else "",
               esc(resolver_text(b["resolver"])), esc(b["falsifier"]), esc(b["rationale"]),
               e["seq"], esc(e["hash"]), esc(short(e["hash"], 16)), pg.u("calls/#e%d" % e["seq"])))
    return ('<section class="panel" id="calls"><h2>Dated calls</h2><p class="lede">Each call is written to an append-only, '
            "hash-chained ledger before it resolves, with the probability, the date and the rule that decides it.</p>%s</section>"
            % "".join(items))


def fr_block(c):
    docs = c.get("_fr") or []
    if not docs:
        return ""
    rows = []
    for d in docs[:8]:
        when = []
        if d.get("effective_on"):
            when.append("effective %s" % d["effective_on"])
        if d.get("comments_close_on"):
            when.append("comments close %s" % d["comments_close_on"])
        rows.append('<li><a href="%s" rel="nofollow noopener" target="_blank">%s</a><br><span class="fine">%s · %s · '
                    "published %s%s</span></li>" % (esc(d["html_url"]), esc(d["title"]), esc(d["type"]),
                                                    esc(", ".join(d.get("agencies", []))), esc(d["publication_date"]),
                                                    (" · " + esc(", ".join(when))) if when else ""))
    return ('<section class="panel" id="regulation"><h2>Regulatory activity</h2><p class="lede">Federal Register documents '
            "matched to this category, refreshed weekly. The dates are what an E5 (legal permission) crossing hangs on.</p>"
            '<ul class="docs">%s</ul></section>' % "".join(rows))


def trials_block(c):
    ts = c.get("_trials") or []
    if not ts:
        return ""
    rows = "".join('<li><a href="https://clinicaltrials.gov/study/%s" rel="nofollow noopener" target="_blank">%s</a> — %s'
                   '<br><span class="fine">%s · %s · first posted %s</span></li>'
                   % (esc(t["nct"]), esc(t["nct"]), esc(t["title"]), esc(t["sponsor"]), esc(t["status"]),
                      esc(t.get("first_posted", "")))
                   for t in ts[:10])
    return ('<section class="panel" id="trials"><h2>Trials to watch</h2><p class="lede">Studies on ClinicalTrials.gov from '
            'the companies in this category, refreshed weekly.</p><ul class="docs">%s</ul></section>' % rows)


def share_block(pg, c):
    url = pg.canonical
    text = "%s — %s" % (c["title"], data.VERDICTS[c["_verdict"]][0])
    embed = '<iframe src="%s/embed/%s/" width="100%%" height="190" style="border:0;max-width:560px" title="%s" loading="lazy"></iframe>' % (
        pg.ctx.base, c["slug"], c["name"])
    cite = '%s. "%s." %s, %s. %s' % (SITE_NAME, c["title"], SITE_NAME, pg.ctx.today[:4], url)
    return (
        '<section class="panel share" id="share"><h2>Share, embed or cite</h2>'
        '<div class="share-row" data-share-url="%s" data-share-text="%s" data-slug="%s">'
        '<button type="button" class="btn" data-share="native">Share</button>'
        '<a class="btn ghost" data-share="x" href="https://twitter.com/intent/tweet?text=%s&url=%s" target="_blank" rel="noopener">Post on X</a>'
        '<a class="btn ghost" data-share="linkedin" href="https://www.linkedin.com/sharing/share-offsite/?url=%s" target="_blank" rel="noopener">LinkedIn</a>'
        '<a class="btn ghost" data-share="email" href="mailto:?subject=%s&body=%s">Email</a>'
        '<button type="button" class="btn ghost" data-copy="%s">Copy link</button></div>'
        '<label class="fine" for="embed-%s">Embed this call (updates when the call resolves)</label>'
        '<textarea id="embed-%s" class="code" readonly rows="2">%s</textarea>'
        '<label class="fine" for="cite-%s">Cite</label><textarea id="cite-%s" class="code" readonly rows="2">%s</textarea>'
        '<p class="fine">Spotted an error? <a href="https://github.com/%s/issues/new?labels=correction&title=%s&body=%s">Open a public correction</a>.</p>'
        "</section>"
        % (esc(url), esc(text), esc(c["slug"]), quote(text), quote(url), quote(url), quote(c["title"]),
           quote(text + "\n" + url), esc(url), esc(c["slug"]), esc(c["slug"]), esc(embed), esc(c["slug"]),
           esc(c["slug"]), esc(cite), esc(pg.ctx.repo), quote("Correction: " + c["name"]),
           quote("Page: %s\n\nWhat is wrong, and a source for the fix:\n" % url)))


def facts_block(c):
    con = c["constraint"]
    classes = " + ".join("%s %s" % (p, data.ENABLERS[p]) for p in c["enabler"].split("+"))
    cells = ['<div><dt>Killing constraint</dt><dd><strong>%s</strong><br><span class="fine">%s</span></dd></div>'
             % (esc(con["name"]), esc(classes))]
    cr = c.get("crossing")
    if cr:
        cells.append('<div><dt>Crossing</dt><dd><strong>%s</strong><br><span class="fine">%s</span></dd></div>'
                     % (esc(cr["date"]), esc(cr["text"])))
    if c["_capital"]:
        cells.append('<div><dt>Capital burned proving demand</dt><dd><strong>%s</strong><br><span class="fine">%d named '
                     "compan%s</span></dd></div>" % (money_m(c["_capital"]), len(c["graveyard"]),
                                                    "y" if len(c["graveyard"]) == 1 else "ies"))
    if c.get("winners"):
        w = c["winners"][0]
        cells.append('<div><dt>%s</dt><dd><strong>%s</strong><br><span class="fine">founded %s</span></dd></div>'
                     % ("Who won" if c["kind"] == "history" else "Who is in now", esc(w["name"]), esc(w.get("founded", "—"))))
    if c["kind"] == "myth":
        cells.append('<div><dt>Why it is not timing</dt><dd><strong>%s</strong></dd></div>' % esc(data.MYTH_TESTS[c["myth_test"]]))
    return '<dl class="facts">%s</dl><p class="fine con-detail">%s</p>' % ("".join(cells), esc(con.get("detail", "")))


def evidence_block(c):
    ev = c.get("evidence") or []
    if not ev:
        return ""
    items = "".join('<li><time>%s</time> %s %s %s</li>' % (esc(e["date"]), esc(e["text"]), src_link(e), conf_tag(e["conf"]))
                    for e in sorted(ev, key=lambda e: e["date"]))
    return '<section class="panel" id="evidence"><h2>What changed, dated</h2><ul class="evidence">%s</ul></section>' % items


def winners_block(c):
    ws = c.get("winners") or []
    if not ws:
        return ""
    head = "Who won once the constraint crossed" if c["kind"] == "history" else (
        "Who succeeded at the same time" if c["kind"] == "myth" else "Who is in the category now")
    items = "".join("<li><strong>%s</strong>%s — %s %s</li>" % (
        esc(w["name"]), (" (founded %s)" % esc(w["founded"])) if w.get("founded") else "", esc(w.get("note", "")), src_link(w))
        for w in ws)
    return '<section class="panel" id="winners"><h2>%s</h2><ul class="evidence">%s</ul></section>' % (head, items)


def category_page(ctx, c, by_slug, view):
    pg = Page(ctx, "category/%s/" % c["slug"])
    v = c["_verdict"]
    since = ""
    if c["_verdict_entry"]:
        e = c["_verdict_entry"]
        since = ' <span class="fine">since %s · <a href="%s">ledger #%d</a></span>' % (
            esc(c["_verdict_since"]), pg.u("calls/#e%d" % e["seq"]), e["seq"])
    related = ""
    if c.get("related"):
        related = '<section class="panel"><h2>Related</h2><ul class="cards mini">%s</ul></section>' % "".join(
            card(pg, by_slug[r], mini=True) for r in c["related"])
    body = (
        '<nav class="crumbs" aria-label="Breadcrumb"><a href="%s">Board</a> › %s</nav>'
        '<article class="cat"><header class="cat-head"><p class="kicker">%s</p><h1>%s</h1>'
        '<p class="verdict-line">%s%s</p><p class="reason">%s</p></header>'
        '<section class="answer"><h2 class="sr">Short answer</h2><p>%s</p></section>%s%s%s%s%s%s%s%s%s%s</article>'
        % (pg.u(""), esc(c["name"]), esc({"history": "Case file: a category that formed", "myth": "Myth check",
                                            "live": "Live call"}[c["kind"]]),
           esc(c["question"]), badge(v), since, esc(c["verdict_reason"]), esc(c["answer"]), facts_block(c),
           metric_block(pg, c), graveyard_block(c), winners_block(c), evidence_block(c), calls_block(pg, c, view),
           fr_block(c), trials_block(c), share_block(pg, c), related))
    ld = {
        "@context": "https://schema.org", "@type": "Article", "headline": c["title"], "description": c["answer"],
        "datePublished": c["_first_seen"], "dateModified": c["updated"], "url": pg.canonical,
        "mainEntityOfPage": pg.canonical, "author": {"@type": "Organization", "name": SITE_NAME, "url": ctx.base + "/"},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": ctx.base + "/"},
        "image": "%s/og/%s.png" % (ctx.base, c["slug"]), "about": c["name"],
        "isAccessibleForFree": True, "license": "https://creativecommons.org/licenses/by/4.0/",
    }
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Board", "item": ctx.base + "/"},
        {"@type": "ListItem", "position": 2, "name": c["name"], "item": pg.canonical}]}
    return pg, layout(pg, c["title"], c["answer"][:300], body, og_image="og/%s.png" % c["slug"], jsonld=[ld, crumbs],
                      body_class="v-%s" % v)


def embed_page(ctx, c):
    pg = Page(ctx, "embed/%s/" % c["slug"])
    target = "%s/category/%s/" % (ctx.base, c["slug"])
    callbit = ""
    if c["_calls"]:
        b = c["_calls"][0]["body"]
        callbit = '<p class="ecall"><b>%d%%</b> %s <span>resolves %s</span></p>' % (b["p_pct"], esc(b["statement"]), esc(b["resolves_on"]))
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex"><title>%s</title><link rel="canonical" href="%s">'
            '<link rel="stylesheet" href="%s"></head><body class="embed"><a class="ecard" href="%s" target="_blank" rel="noopener">'
            '<span class="ebrand">%s ripeness board</span><span class="ename">%s</span>%s<span class="ereason">%s</span>%s</a></body></html>'
            % (esc(c["name"]), esc(target), pg.u("assets/style.css?v=" + ctx.asset_v), esc(target), SITE_NAME,
               esc(c["name"]), badge(c["_verdict"]), esc(c["verdict_reason"]), callbit))
    return pg, html


def og_card(ctx, c):
    """HTML for the 1200x630 share image, screenshotted by scripts/og.py."""
    v = c["_verdict"]
    callbit = ""
    if c["_calls"]:
        b = c["_calls"][0]["body"]
        callbit = '<div class="ogcall"><b>%d%%</b><span>%s<br><i>resolves %s</i></span></div>' % (
            b["p_pct"], esc(clip(b["statement"], 150)), esc(b["resolves_on"]))
    metric = ""
    info = c.get("_metric")
    if info and info.get("then") and info.get("now"):
        m = c["metric"]
        metric = '<div class="ogmetric">%s<br><b>%s → %s</b></div>' % (
            esc(m["label"]), esc(charts.fmt_value(info["then"][1], m["unit"])), esc(charts.fmt_value(info["now"][1], m["unit"])))
    return ('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="../assets/style.css"></head>'
            '<body class="og v-%s"><div class="ogwrap"><div class="ogtop"><span class="dot"></span>%s · ripeness board</div>'
            '<h1>%s</h1><div class="ogv">%s</div><p>%s</p>%s%s</div></body></html>'
            % (esc(v), SITE_NAME, esc(c["question"]), badge(v), esc(c["verdict_reason"]), metric, callbit))


# ---------------------------------------------------------------- board

def card(pg, c, mini=False):
    v = c["_verdict"]
    bits = []
    info = c.get("_metric")
    if info and info.get("then") and info.get("now") and not mini:
        m = c["metric"]
        bits.append('<span class="cm">%s: %s → %s</span>' % (esc(m.get("short", m["label"])),
                                                                  esc(charts.fmt_value(info["then"][1], m["unit"])),
                                                                  esc(charts.fmt_value(info["now"][1], m["unit"]))))
    if c["_capital"] and not mini:
        bits.append('<span class="cg">graveyard %s</span>' % money_m(c["_capital"]))
    if c["_calls"] and not mini:
        b = c["_calls"][0]["body"]
        bits.append('<span class="cc">call: %d%% by %s</span>' % (b["p_pct"], esc(b["resolves_on"])))
    meta = ('<p class="meta">%s</p>' % " · ".join(bits)) if bits else ""
    return ('<li class="card v-%s"><a href="%s"><span class="cn">%s</span>%s<span class="cq">%s</span>'
            '<span class="ck">Killed by: %s</span>%s</a></li>'
            % (esc(v), pg.u("category/%s/" % c["slug"]), esc(c["name"]), badge(v),
               esc(c["verdict_reason"]), esc(c["constraint"]["name"]), meta))


def home_page(ctx, cats, view):
    pg = Page(ctx, "")
    live = [c for c in cats if c["kind"] == "live"]
    groups = []
    blurbs = {
        "ripe": "The constraint crossed and funded companies died proving demand. The clock is running.",
        "pending": "A dated public event decides these. The board watches the source and resolves automatically where it can.",
        "check": "One named check decides each of these. Unknown is not the same as no.",
        "nogo": "Popular ideas whose blocker has not moved, or got worse. Waiting does not help yet.",
        "unknown": "The named blocker never moved, or it crossed and the category died anyway. The board abstains.",
    }
    for v in data.LIVE_VERDICTS:
        cs = [c for c in live if c["_verdict"] == v]
        if cs:
            groups.append('<section class="group" id="%s"><h2>%s <span class="count">%d</span></h2><p class="lede">%s</p>'
                          '<ul class="cards">%s</ul></section>' % (v, esc(data.VERDICTS[v][0]), len(cs), esc(blurbs[v]),
                                                                  "".join(card(pg, c) for c in sorted(cs, key=lambda c: -c["_capital"]))))
    hist = [c for c in cats if c["kind"] == "history"]
    myths = [c for c in cats if c["kind"] == "myth"]
    open_calls = [e for cid, e in view.calls.items() if cid not in view.resolutions]
    resolved = len(view.resolutions)
    next_due = sorted(open_calls, key=lambda e: e["body"]["resolves_on"])
    nd = next_due[0]["body"] if next_due else None
    total_dead = sum(c["_capital"] for c in cats)
    stats = ('<ul class="stats"><li><b>%d</b> live categories</li><li><b>%d</b> dated calls, %d resolved</li>'
             '<li><b>%s</b> of disclosed capital in the graveyard</li><li>next call due <b>%s</b></li></ul>'
             % (len(live), len(view.calls), resolved, money_m(total_dead), esc(nd["resolves_on"]) if nd else "—"))
    body = (
        '<section class="hero"><h1>Which dead startup categories are worth trying again?</h1>'
        '<p class="sub">Each call names what killed the category, the metric that has moved since, the funded companies that died '
        "proving demand, and a dated prediction that resolves in public. Every call is hash-chained, so none can be quietly edited "
        "after the fact.</p>%s"
        '<p class="cta"><a class="btn" href="#ripe">See the board</a> <a class="btn ghost" href="%s">Re-look your passed deals '
        '(private, in your browser)</a></p></section>'
        '<section class="rule panel"><h2>The rule</h2><p>A category is worth re-attempting when two things are true: funded companies '
        "already burned real money proving the demand, and the specific constraint that killed them has since crossed a threshold "
        '(cost, law, capability or install base). Webvan and Instacart are the canonical pair. <a href="%s">How the rule was tested, '
        "and where it failed</a>.</p></section>%s"
        '<section class="group" id="formed"><h2>Formed: the rule on history <span class="count">%d</span></h2><p class="lede">'
        "Categories that died early, then formed once their binding constraint crossed. These are the backtest, not predictions.</p>"
        '<ul class="cards">%s</ul></section>'
        '<section class="group" id="myths"><h2>Not timing failures <span class="count">%d</span></h2><p class="lede">Famous '
        "“too early” stories that fail the test. If a competitor succeeded at the same time, the enabler existed.</p>"
        '<ul class="cards">%s</ul></section>'
        % (stats, pg.u("relook/"), pg.u("method/"), "".join(groups), len(hist),
           "".join(card(pg, c) for c in sorted(hist, key=lambda c: -c["_capital"])), len(myths),
           "".join(card(pg, c) for c in sorted(myths, key=lambda c: -c["_capital"]))))
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": ctx.base + "/",
           "description": TAGLINE},
          {"@context": "https://schema.org", "@type": "Dataset", "name": "Idea Locator ripeness board",
           "description": "Failed startup categories with the constraint that killed them, the metric that moved since, a sourced "
                          "graveyard of funded companies, and dated, hash-chained calls on whether each is viable again.",
           "url": ctx.base + "/", "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
           "creator": {"@type": "Organization", "name": SITE_NAME}, "dateModified": ctx.today,
           "distribution": [
               {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": ctx.base + "/data/board.json"},
               {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": ctx.base + "/data/graveyard.csv"},
               {"@type": "DataDownload", "encodingFormat": "application/jsonl", "contentUrl": ctx.base + "/ledger/chain.jsonl"}]}]
    return pg, layout(pg, "Ripeness board: which dead startup categories are viable again",
                      "Dated, hash-chained calls on whether failed startup categories are ripe again: the constraint that "
                      "killed each one, the metric that moved since, and a sourced graveyard of funded companies.",
                      body, jsonld=ld, body_class="home")


# ---------------------------------------------------------------- ledger

def entry_summary(e, by_slug):
    b = e["body"]
    t = e["type"]
    if t == "genesis":
        return esc(b.get("statement", "Genesis"))
    if t == "call":
        return "Call <b>%s</b> (%d%%, resolves %s): %s" % (esc(b["id"]), b["p_pct"], esc(b["resolves_on"]), esc(b["statement"]))
    if t == "verdict":
        name = by_slug.get(b["category"], {}).get("name", b["category"])
        prev = (" (was %s)" % esc(data.VERDICTS.get(b["from"], (b["from"],))[0])) if b.get("from") else ""
        return 'Verdict: <a href="../category/%s/">%s</a> is <b>%s</b>%s. %s' % (
            esc(b["category"]), esc(name), esc(data.VERDICTS[b["verdict"]][0]), prev, esc(b.get("reason", "")))
    if t == "resolution":
        return "Resolution: <b>%s</b> resolved <b>%s</b> on %s (%s)." % (esc(b["call"]), esc(b["outcome"].upper()),
                                                                      esc(b["resolved_on"]), esc(b["method"]))
    return esc(b.get("text", ""))


def calls_page(ctx, entries, view, by_slug):
    pg = Page(ctx, "calls/")
    rows = "".join('<tr id="e%d"><td>%d</td><td><time>%s</time></td><td>%s</td><td>%s</td><td><code title="%s">%s…</code></td></tr>'
                   % (e["seq"], e["seq"], esc(e["ts"][:10]), esc(e["type"]), entry_summary(e, by_slug), esc(e["hash"]),
                      esc(short(e["hash"], 12))) for e in reversed(entries))
    scored = view.scored()
    if scored:
        brier = sum(r["brier"] for r in scored) / len(scored)
        score = "<p><b>%d</b> calls resolved yes/no. Mean Brier score <b>%.3f</b> (0 is perfect; always saying 50%% scores 0.250).</p>" % (len(scored), brier)
    else:
        first_due = min((e["body"]["resolves_on"] for e in view.calls.values()), default="—")
        score = ("<p>No call has resolved yet, so there is no score to report, and reporting one would be the lie. The first call "
                 "is due <b>%s</b>. Until then, what exists is tamper-evidence.</p>" % esc(first_due))
    body = (
        '<h1>The ledger</h1><p class="sub">Every call, verdict and resolution, in order. Each entry carries the SHA-256 hash of '
        "the entry before it, so changing any past entry breaks every hash after it. The deploy job refuses to publish a ledger "
        "that does not extend the one already live.</p>"
        '<section class="panel"><h2>Verify it yourself</h2><p>Your browser can recompute every hash from the raw file. Nothing is '
        'sent anywhere.</p><p><button type="button" class="btn" id="verify-btn" data-chain="%s">Verify the chain</button> '
        '<a class="btn ghost" href="%s" download>Download chain.jsonl</a></p><p id="verify-out" class="verify-out" aria-live="polite"></p>'
        '<p class="fine">Head <code>%s</code> · %d entries. Canonical form: JSON with sorted keys, no whitespace, '
        'ASCII-escaped; <code>hash = sha256(canonical({seq, type, ts, body, prev}))</code>.</p></section>'
        '<section class="panel"><h2>Score</h2>%s</section>'
        '<section class="panel"><h2>Entries</h2><div class="scroll"><table class="ledger"><thead><tr><th>#</th><th>Date</th>'
        "<th>Type</th><th>Entry</th><th>Hash</th></tr></thead><tbody>%s</tbody></table></div></section>"
        '<script src="%s" defer></script>'
        % (pg.u("ledger/chain.jsonl"), pg.u("ledger/chain.jsonl"), esc(view.head), len(entries), score, rows,
           pg.u("assets/verify.js?v=" + ctx.asset_v)))
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": "Idea Locator call ledger",
          "description": "Append-only, hash-chained ledger of dated calls on startup category timing, with resolutions.",
          "url": pg.canonical, "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
          "creator": {"@type": "Organization", "name": SITE_NAME},
          "distribution": [{"@type": "DataDownload", "encodingFormat": "application/jsonl",
                            "contentUrl": ctx.base + "/ledger/chain.jsonl"}]}
    return pg, layout(pg, "The ledger: hash-chained startup timing calls",
                      "Every dated call on when a failed startup category becomes viable, with its probability, resolver "
                      "and outcome, in an append-only SHA-256 hash chain you can verify in your browser.", body, jsonld=ld)


# ---------------------------------------------------------------- other pages

def relook_page(ctx):
    pg = Page(ctx, "relook/")
    slot = ""
    if ctx.report_url:
        slot = ('<section class="panel money"><h2>Want this run on your full pass archive?</h2><p>A private re-look report reads '
                'your passed decks, not one-line descriptions. <a class="btn" href="%s" rel="noopener">Request a private re-look '
                "report</a></p></section>" % esc(ctx.report_url))
    body = (
        '<h1>Re-look your passed deals</h1><p class="sub">Paste the deals you passed on, one per line: company, the year you '
        "passed, and a short description. The screen matches each one to a category on the board and tells you whether the "
        "constraint that killed that category has crossed since you passed. <strong>It runs entirely in your browser. Nothing you "
        "type is uploaded or stored.</strong></p>"
        '<section class="panel"><label for="deals"><b>Your passed deals</b> <span class="fine">(one per line: company, year, '
        'description; or load a CSV with those three columns)</span></label>'
        '<textarea id="deals" rows="8" spellcheck="false" placeholder="Acme Grocer, 2009, online grocery delivery from our own warehouses"></textarea>'
        '<p class="row"><button type="button" class="btn" id="run">Run the re-look</button> '
        '<button type="button" class="btn ghost" id="sample">Load an example</button> '
        '<label class="btn ghost file">Load CSV<input type="file" id="csv" accept=".csv,text/csv" hidden></label></p>'
        '<p class="fine">Matching uses the category keywords published in <a href="%s">relook.json</a>. When nothing matches, or the '
        "matched category's blocker never moved, the answer is “I don't know”, not a guess.</p></section>"
        '<section class="panel" id="results" hidden><h2>Re-look list</h2><p id="summary" class="lede" aria-live="polite"></p>'
        '<div class="scroll"><table class="relook"><thead><tr><th>Deal</th><th>Matched category</th><th>Verdict</th>'
        "<th>Since you passed</th></tr></thead><tbody id=\"rows\"></tbody></table></div>"
        '<p><button type="button" class="btn ghost" id="export">Download results as CSV</button></p></section>%s'
        '<section class="panel"><h2>Why passed deals</h2><p>A fund’s passed decks are a private, dated graveyard: '
        "companies that pitched, were turned down, and never entered a database. The question this answers is narrow and "
        "checkable: which of your passes were right ideas at the wrong time, and has the binding constraint crossed since? "
        "It makes no prediction about any company.</p></section>"
        '<script src="%s" defer></script>' % (pg.u("data/relook.json"), slot, pg.u("assets/relook.js?v=" + ctx.asset_v)))
    return pg, layout(pg, "Re-look screen: which of your passed deals are ripe now",
                      "Paste the startups you passed on and see which ones were right ideas at the wrong time: the constraint "
                      "that killed each category, and whether it has crossed since. Runs privately in your browser.", body)


def calendar_page(ctx, cats, live):
    pg = Page(ctx, "calendar/")
    cal = live.get("calendar") or {}
    items = cal.get("items", [])
    by_slug = {c["slug"]: c for c in cats}
    upcoming, recent = [], []
    for d in items:
        key_date = d.get("comments_close_on") or d.get("effective_on")
        if key_date and key_date >= ctx.today:
            upcoming.append((key_date, d))
        else:
            recent.append((d["publication_date"], d))
    upcoming.sort(key=lambda x: x[0])
    recent.sort(key=lambda x: x[0], reverse=True)

    def row(when, d, label):
        cats_html = ", ".join('<a href="%s">%s</a>' % (pg.u("category/%s/" % s), esc(by_slug[s]["name"]))
                              for s in d.get("categories", []) if s in by_slug)
        return ('<tr><td><time>%s</time><br><span class="fine">%s</span></td><td><a href="%s" rel="nofollow noopener" '
                'target="_blank">%s</a><br><span class="fine">%s · %s</span></td><td>%s</td></tr>'
                % (esc(when), esc(label(d)), esc(d["html_url"]), esc(d["title"]), esc(d["type"]),
                   esc(", ".join(d.get("agencies", []))), cats_html))

    def up_label(d):
        if d.get("comments_close_on") and d["comments_close_on"] >= ctx.today:
            return "comments close"
        return "takes effect"

    up_rows = "".join(row(w, d, up_label) for w, d in upcoming) or '<tr><td colspan="3">Nothing upcoming in the tracked set.</td></tr>'
    re_rows = "".join(row(w, d, lambda d: "published") for w, d in recent[:40]) or '<tr><td colspan="3">No documents fetched yet.</td></tr>'
    fetched = cal.get("fetched")
    status = ("Fetched %s from the Federal Register API." % esc(fetched[:10])) if fetched else "Not fetched yet in this build."
    if cal.get("status") == "stale":
        status += ' <strong class="warn">The last refresh failed; showing the last good list.</strong>'
    body = (
        '<h1>Regulatory unlock calendar</h1><p class="sub">Legal permission (enabler class E5) is the one constraint with no cost '
        "curve to extrapolate, and the only one whose crossing dates are scheduled in public. This calendar maps Federal Register "
        "rules, proposed rules and notices onto the categories on the board.</p><p class=\"fine\">%s Rules take effect on paper; "
        'the <a href="%s">slip corpus</a> measures how often those dates move.</p>'
        '<section class="panel"><h2>Upcoming dates</h2><div class="scroll"><table class="cal"><thead><tr><th>Date</th><th>Document</th>'
        "<th>Categories</th></tr></thead><tbody>%s</tbody></table></div></section>"
        '<section class="panel"><h2>Recently published</h2><div class="scroll"><table class="cal"><thead><tr><th>Date</th><th>Document</th>'
        "<th>Categories</th></tr></thead><tbody>%s</tbody></table></div></section>" % (status, pg.u("slips/"), up_rows, re_rows))
    return pg, layout(pg, "Regulatory unlock calendar for startup categories",
                      "Upcoming effective dates and comment deadlines from the Federal Register, mapped to startup categories "
                      "whose viability hangs on a legal permission. Refreshed weekly.", body)


def slip_stats(rows):
    out = {}
    for r in rows:
        s = out.setdefault(r["class"], {"n": 0, "held": 0, "late": 0, "early": 0, "killed": 0, "pending": 0, "slips": []})
        s["n"] += 1
        st = r["outcome"]
        s[st] = s.get(st, 0) + 1
        if st in ("late", "early") and r.get("slip_months") is not None:
            s["slips"].append(abs(r["slip_months"]))
    for s in out.values():
        moved = s["late"] + s["early"] + s["killed"]
        decided = moved + s["held"]
        s["p_move"] = (moved / float(decided)) if decided else None
        sl = sorted(s["slips"])
        s["median"] = sl[len(sl) // 2] if sl else None
        s["max"] = sl[-1] if sl else None
    return out


def slips_page(ctx, slips):
    pg = Page(ctx, "slips/")
    rows = slips["rows"]
    stats = slip_stats(rows)
    names = slips.get("classes", {})
    srows = "".join("<tr><td><b>%s</b> %s</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%s</td><td>%s</td></tr>" % (
        esc(k), esc(names.get(k, "")), s["n"], s["held"], s["late"], s["early"], s["killed"], s["pending"],
        ("%d%%" % round(100 * s["p_move"])) if s["p_move"] is not None else "—",
        ("%d mo" % s["median"]) if s["median"] is not None else "—") for k, s in sorted(stats.items()))
    labels = {"held": "held", "late": "late", "early": "early", "killed": "killed", "pending": "pending"}
    drows = "".join(
        '<tr><td>%s</td><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s %s</td></tr>' % (
            esc(r["class"]), esc(r["commitment"]), ('<br><span class="fine">%s</span>' % esc(r["note"])) if r.get("note") else "",
            esc(r["announced"]), esc(r["actual"]), esc(labels[r["outcome"]]),
            ("%+d mo" % r["slip_months"]) if r.get("slip_months") is not None else "—", esc(r.get("moves", "")),
            src_link(r), conf_tag(r["conf"])) for r in rows)
    body = (
        '<h1>The slip corpus</h1><p class="sub">How often do dated commitments (patent expiries, statutory sunsets, regulatory '
        "deadlines, plant start-ups) actually happen on the date announced? A category timed to a date inherits that date's "
        "reliability. Superseded dates vanish from the record the moment they are superseded; this table keeps them.</p>"
        '<section class="panel"><h2>Base rates by class</h2><div class="scroll"><table><thead><tr><th>Class</th><th>n</th><th>Held</th>'
        "<th>Late</th><th>Early</th><th>Killed</th><th>Pending</th><th>P(move)</th><th>Median slip</th></tr></thead><tbody>%s</tbody>"
        '</table></div><p class="fine">P(move) counts decided rows only (held, late, early, killed). The corpus is selection-biased '
        "toward dates that moved, because routine dates that hold are rarely written about, so every P(move) is an upper bound on "
        "the population rate. It is closer to the right conditioning for founders, who only care about dates big enough to build "
        'a company against. <a href="%s">Download CSV</a>.</p></section>'
        '<section class="panel"><h2>Every commitment</h2><div class="scroll"><table class="slips"><thead><tr><th>Class</th>'
        "<th>Commitment</th><th>Announced</th><th>Actual / current</th><th>Outcome</th><th>Slip</th><th>Moves</th><th>Source</th>"
        "</tr></thead><tbody>%s</tbody></table></div><p class=\"fine\">%s</p></section>"
        % (srows, pg.u("data/slips.csv"), drows, esc(slips.get("note", ""))))
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": "Slip corpus: announced versus actual dates",
          "description": "Dated commitments (patent expiries, statutory sunsets, regulatory deadlines, plant start-ups) with the "
                         "announced date, the date actually in force, slip in months and number of moves.",
          "url": pg.canonical, "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
          "creator": {"@type": "Organization", "name": SITE_NAME},
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": ctx.base + "/data/slips.csv"}]}
    return pg, layout(pg, "Slip corpus: how often regulatory deadlines move",
                      "Announced versus actual dates for patent expiries, statutory sunsets, regulatory deadlines and plant "
                      "start-ups, with base rates by class. How much to trust a date a startup category is timed to.", body, jsonld=ld)


def graveyard_rows(cats):
    rows = []
    for c in cats:
        for g in c["graveyard"]:
            rows.append({"company": g["name"], "category": c["name"], "slug": c["slug"], "verdict": c["_verdict"],
                         "founded": g.get("founded", ""), "died": g.get("died", ""), "raised_usd_m": g.get("raised_usd_m"),
                         "how": g["how"], "constraint": c["constraint"]["name"], "source": g.get("source", ""),
                         "conf": g["conf"]})
    rows.sort(key=lambda r: -(r["raised_usd_m"] or 0))
    return rows


def graveyard_page(ctx, cats):
    pg = Page(ctx, "graveyard/")
    rows = graveyard_rows(cats)
    total = sum(r["raised_usd_m"] or 0 for r in rows)
    trs = "".join('<tr><td><strong>%s</strong></td><td><a href="%s">%s</a> %s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        esc(r["company"]), pg.u("category/%s/" % r["slug"]), esc(r["category"]), badge(r["verdict"]),
        esc("%s–%s" % (r["founded"], r["died"]) if r["founded"] else r["died"]),
        esc(money_m(r["raised_usd_m"]) if r["raised_usd_m"] is not None else "—"), esc(r["how"]),
        src_link(r) + " " + conf_tag(r["conf"])) for r in rows)
    body = (
        '<h1>The startup graveyard</h1><p class="sub">%d companies that died in categories on the board, %s of disclosed capital, '
        "each with the constraint that killed its category and a source. Sorted by capital raised.</p>"
        '<p class="fine">A big graveyard is evidence of demand: investors do not put hundreds of millions into something nobody '
        "wants. It is only half of the rule; the other half is whether the killer has moved. "
        '<a href="%s">Download CSV</a>.</p><div class="scroll"><table class="grave"><thead><tr><th>Company</th><th>Category</th>'
        "<th>Years</th><th>Capital</th><th>How it died</th><th>Source</th></tr></thead><tbody>%s</tbody></table></div>"
        % (len(rows), money_m(total), pg.u("data/graveyard.csv"), trs))
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": "Startup graveyard with the constraint that killed each category",
          "description": "Failed startups with founding and death years, capital raised where disclosed, how each died, and the "
                         "binding constraint of its category.", "url": pg.canonical,
          "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
          "creator": {"@type": "Organization", "name": SITE_NAME},
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": ctx.base + "/data/graveyard.csv"}]}
    return pg, layout(pg, "Startup graveyard: failed companies and what killed them",
                      "Failed startups with capital raised, how each died, and the constraint that killed its category, "
                      "with sources. A dataset of demand proven the expensive way.", body, jsonld=ld)


def read_page(name):
    with open(os.path.join(ROOT, "site", "pages", name), encoding="utf-8") as fh:
        return fh.read()


def static_page(ctx, path, name, title, description):
    pg = Page(ctx, path)
    html = read_page(name).replace("{{base}}", ctx.base).replace("{{repo}}", ctx.repo).replace("{{u}}", pg.u(""))
    return pg, layout(pg, title, description, html)


def not_found(ctx):
    pg = Page(ctx, "404.html")
    pg.prefix = ctx.base + "/"  # 404 is served at any depth, so links must be absolute
    body = ('<h1>Not on the board</h1><p class="sub">That page does not exist. <a href="%s/">Go to the ripeness board</a> or '
            '<a href="%s/graveyard/">search the graveyard</a>.</p>' % (esc(ctx.base), esc(ctx.base)))
    return pg, layout(pg, "Page not found", "This page is not on the Idea Locator ripeness board.", body, noindex=True)


# ---------------------------------------------------------------- exports

def relook_json(ctx, cats):
    out = []
    for c in cats:
        m, info = c.get("metric"), c.get("_metric")
        series = None
        if m and info and info.get("points"):
            pts = sorted(info["points"], key=lambda p: charts.year_frac(p[0]))
            yearly = {}
            for d, v in pts:
                yearly[int(str(d)[:4])] = v
            series = {"label": m["label"], "unit": m["unit"], "direction": m["direction"],
                      "points": [[y, yearly[y]] for y in sorted(yearly)]}
        out.append({"slug": c["slug"], "name": c["name"], "verdict": c["_verdict"],
                    "verdict_label": data.VERDICTS[c["_verdict"]][0], "constraint": c["constraint"]["name"],
                    "crossing": (c.get("crossing") or {}).get("date"), "keywords": c["keywords"],
                    "url": "../category/%s/" % c["slug"], "series": series})
    return {"generated": ctx.today, "categories": out}


def board_json(ctx, cats, view):
    out = []
    for c in cats:
        out.append({
            "slug": c["slug"], "name": c["name"], "kind": c["kind"], "url": "%s/category/%s/" % (ctx.base, c["slug"]),
            "question": c["question"], "answer": c["answer"], "verdict": c["_verdict"], "verdict_reason": c["verdict_reason"],
            "verdict_since": c["_verdict_since"], "enabler": c["enabler"], "constraint": c["constraint"],
            "crossing": c.get("crossing"), "graveyard": c["graveyard"], "winners": c.get("winners", []),
            "evidence": c.get("evidence", []), "calls": [e["body"]["id"] for e in c["_calls"]],
            "metric": ({"label": c["metric"]["label"], "unit": c["metric"]["unit"],
                        "now": c["_metric"].get("now"), "then": c["_metric"].get("then")}
                       if c.get("_metric") and c["_metric"].get("now") else None),
            "updated": c["updated"]})
    return {"name": "Idea Locator ripeness board", "generated": ctx.built, "ledger_head": view.head,
            "license": "CC BY 4.0", "categories": out}


def write(ctx, path, text):
    full = os.path.join(ctx.out, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def emit(ctx, pg, html, lastmod=None, sitemap=True):
    target = pg.path + "index.html" if (pg.path == "" or pg.path.endswith("/")) else pg.path
    write(ctx, target, html)
    if sitemap:
        ctx.urls.append((pg.canonical, lastmod or ctx.today))


def asset_version():
    import hashlib
    h = hashlib.sha256()
    folder = os.path.join(ROOT, "site", "assets")
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), "rb") as fh:
            h.update(name.encode() + fh.read())
    return h.hexdigest()[:10]


def build(out=None, today=None, quiet=False):
    ctx = Ctx(out=out, today=today)
    cats = data.load_categories()
    calls = data.load_calls()
    problems = data.validate(cats, calls)
    entries = ledger.load(data.LEDGER)
    problems += ["ledger: " + p for p in ledger.verify(entries)]
    if problems:
        raise SystemExit("Refusing to build:\n  " + "\n  ".join(problems))
    live = data.load_live()
    slips = data.load_slips()
    ctx.asset_v = asset_version()
    view, by_slug = derive(ctx, cats, entries, live, slips)
    ctx.head = view.head
    if os.path.exists(ctx.out):
        shutil.rmtree(ctx.out)
    os.makedirs(ctx.out)
    shutil.copytree(os.path.join(ROOT, "site", "assets"), os.path.join(ctx.out, "assets"))

    emit(ctx, *home_page(ctx, cats, view))
    for c in cats:
        pg, html = category_page(ctx, c, by_slug, view)
        emit(ctx, pg, html, lastmod=max(c["updated"], c["_verdict_since"] or c["updated"]))
        epg, ehtml = embed_page(ctx, c)
        emit(ctx, epg, ehtml, sitemap=False)
        write(ctx, "_og/%s.html" % c["slug"], og_card(ctx, c))
    emit(ctx, *calls_page(ctx, entries, view, by_slug))
    emit(ctx, *relook_page(ctx))
    emit(ctx, *calendar_page(ctx, cats, live))
    emit(ctx, *slips_page(ctx, slips))
    emit(ctx, *graveyard_page(ctx, cats))
    emit(ctx, *static_page(ctx, "method/", "method.html", "Method: how the ripeness rule was tested",
                           "The two-variable rule behind the board (capital burned proving demand, times how far the killing "
                           "constraint has moved), its backtest on 110 categories, and every test that failed."))
    emit(ctx, *static_page(ctx, "about/", "about.html", "About Idea Locator",
                           "What the Idea Locator ripeness board is, who runs it, how it stays honest, and how to download or "
                           "correct the data."))
    pg404, html404 = not_found(ctx)
    emit(ctx, pg404, html404, sitemap=False)
    default_og = ('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="../assets/style.css"></head>'
                  '<body class="og"><div class="ogwrap"><div class="ogtop"><span class="dot"></span>%s</div>'
                  "<h1>Which dead startup categories are worth trying again?</h1>"
                  "<p>Dated, hash-chained calls: what killed each category, the metric that moved since, and the graveyard "
                  "that proved demand.</p></div></body></html>" % SITE_NAME)
    write(ctx, "_og/default.html", default_og)

    # data exports
    write(ctx, "data/board.json", json.dumps(board_json(ctx, cats, view), ensure_ascii=False, indent=1))
    write(ctx, "data/relook.json", json.dumps(relook_json(ctx, cats), ensure_ascii=False))
    write(ctx, "data/graveyard.csv", data.to_csv(graveyard_rows(cats), ["company", "category", "verdict", "founded", "died",
                                                                         "raised_usd_m", "how", "constraint", "source", "conf"]))
    write(ctx, "data/slips.csv", data.to_csv(slips["rows"], ["class", "commitment", "announced", "actual", "outcome",
                                                             "slip_months", "moves", "conf", "source", "note"]))
    os.makedirs(os.path.join(ctx.out, "ledger"), exist_ok=True)
    shutil.copy(data.LEDGER, os.path.join(ctx.out, "ledger", "chain.jsonl"))
    write(ctx, "ledger/HEAD", view.head + "\n")

    # discovery
    key_path = os.path.join(ROOT, "site", "indexnow-key.txt")
    if os.path.exists(key_path):
        key = open(key_path).read().strip()
        write(ctx, "%s.txt" % key, key)
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in ctx.urls:
        sm.append("<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (escape(loc), lastmod[:10]))
    sm.append("</urlset>")
    write(ctx, "sitemap.xml", "\n".join(sm) + "\n")
    write(ctx, "robots.txt", "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % ctx.base)
    write(ctx, "urls.txt", "\n".join(u for u, _ in ctx.urls) + "\n")
    write(ctx, ".nojekyll", "")
    if not quiet:
        print("built %d pages (%d categories, %d ledger entries) into %s" % (len(ctx.urls), len(cats), len(entries), ctx.out))
    return ctx


if __name__ == "__main__":
    build(out=sys.argv[1] if len(sys.argv) > 1 else None)
