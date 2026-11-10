import json
import os
import re
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from il import data, ledger, site

BASE = "https://example.test/board"


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.meta, self.title, self.ld, self.ids = [], {}, "", [], set()
        self._in_title = self._in_ld = self._in_svg = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in ("link", "script", "img", "iframe") and (a.get("href") or a.get("src")):
            self.links.append(a.get("href") or a.get("src"))
        if tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key] = a.get("content", "")
        if tag == "link" and a.get("rel") == "canonical":
            self.meta["canonical"] = a.get("href")
        if tag == "title" and not self.title and not self._in_svg:
            self._in_title = True
        if tag == "svg":
            self._in_svg = True
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "svg":
            self._in_svg = False
        if tag == "script" and self._in_ld:
            self.ld.append("".join(self._buf))
            self._in_ld = False

    def handle_data(self, d):
        if self._in_title:
            self.title += d
        if self._in_ld:
            self._buf.append(d)


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["IL_BASE_URL"] = BASE
        # Today's date, as in production: these tests must pass on whatever day the scheduled build runs.
        cls.ctx = site.build(out=cls.tmp.name, quiet=True)
        cls.out = cls.tmp.name
        cls.pages = {}
        for root, _, files in os.walk(cls.out):
            for f in files:
                if f.endswith(".html") and "_og" not in root:
                    path = os.path.join(root, f)
                    with open(path, encoding="utf-8") as fh:
                        cls.pages[os.path.relpath(path, cls.out)] = fh.read()

    @classmethod
    def tearDownClass(cls):
        del os.environ["IL_BASE_URL"]
        cls.tmp.cleanup()

    def parse(self, html):
        p = PageParser()
        p.feed(html)
        return p

    def test_every_category_has_a_page_and_an_embed(self):
        for c in data.load_categories():
            self.assertIn("category/%s/index.html" % c["slug"], self.pages)
            self.assertIn("embed/%s/index.html" % c["slug"], self.pages)

    def test_core_pages_exist(self):
        for p in ("index.html", "calls/index.html", "relook/index.html", "calendar/index.html", "slips/index.html",
                  "graveyard/index.html", "method/index.html", "about/index.html", "404.html"):
            self.assertIn(p, self.pages)
        for f in ("sitemap.xml", "robots.txt", "data/board.json", "data/relook.json", "data/graveyard.csv", "data/slips.csv",
                  "ledger/chain.jsonl", ".nojekyll"):
            self.assertTrue(os.path.exists(os.path.join(self.out, f)), f)

    def test_seo_basics_on_indexable_pages(self):
        for rel, html in self.pages.items():
            p = self.parse(html)
            if p.meta.get("robots") == "noindex":
                continue
            self.assertTrue(p.title.strip(), rel)
            self.assertLessEqual(len(p.title), 95, rel)
            self.assertTrue(40 <= len(p.meta.get("description", "")) <= 320, "%s description length" % rel)
            self.assertTrue(p.meta.get("canonical", "").startswith(BASE + "/"), rel)
            self.assertTrue(p.meta.get("og:image", "").startswith(BASE + "/og/"), rel)
            for block in p.ld:
                json.loads(block)

    def test_internal_links_resolve(self):
        missing = []
        for rel, html in self.pages.items():
            if rel == "404.html":
                continue
            page_url = "http://local/" + rel
            for href in self.parse(html).links:
                if href.startswith(("http://", "https://", "mailto:", "#", "data:")) or href.startswith("//"):
                    continue
                target = urlparse(urljoin(page_url, href)).path.lstrip("/")
                if not target or target.endswith("/"):
                    target += "index.html"
                if target.startswith("og/"):
                    continue  # share images are rendered after the build by scripts/og.py
                if not os.path.exists(os.path.join(self.out, target)):
                    missing.append("%s -> %s" % (rel, href))
        self.assertEqual(missing, [])

    def test_sitemap_lists_every_indexable_page(self):
        with open(os.path.join(self.out, "sitemap.xml")) as fh:
            sm = fh.read()
        locs = set(re.findall(r"<loc>([^<]+)</loc>", sm))
        for c in data.load_categories():
            self.assertIn("%s/category/%s/" % (BASE, c["slug"]), locs)
        self.assertNotIn("%s/embed/" % BASE, sm)

    def test_no_leaked_python_values(self):
        for rel, html in self.pages.items():
            text = re.sub(r"<script.*?</script>", "", html, flags=re.S)
            for bad in (">None<", "None ", " nan", "{'", "[object"):
                self.assertNotIn(bad, text, rel)

    def test_disclaimer_on_every_page(self):
        for rel, html in self.pages.items():
            if rel.startswith("embed/"):
                continue
            self.assertIn("not investment advice", html, rel)

    def test_relook_data_has_keywords_for_every_category(self):
        with open(os.path.join(self.out, "data/relook.json")) as fh:
            rel = json.load(fh)
        slugs = {c["slug"] for c in rel["categories"]}
        self.assertEqual(slugs, {c["slug"] for c in data.load_categories()})
        self.assertTrue(all(c["keywords"] for c in rel["categories"]))

    def test_indexnow_key_file_published(self):
        with open(os.path.join(data.ROOT, "site", "indexnow-key.txt")) as fh:
            key = fh.read().strip()
        self.assertRegex(key, r"^[0-9a-f]{32}$")
        with open(os.path.join(self.out, key + ".txt")) as fh:
            self.assertEqual(fh.read().strip(), key)

    def test_ledger_page_reports_the_real_ledger_state(self):
        # Whatever the published chain holds today: a score only once calls have resolved yes or no.
        view = ledger.View(ledger.load(data.LEDGER))
        html = self.pages["calls/index.html"]
        scored = view.scored()
        if scored:
            brier = sum(r["brier"] for r in scored) / len(scored)
            self.assertIn("Mean Brier score <b>%.3f</b>" % brier, html)
            self.assertNotIn("there is no score to report", html)
        else:
            self.assertIn("there is no score to report", html)
            self.assertNotIn("Mean Brier score", html)
        self.assertIn("<b>%d</b> dated call" % len(view.calls), self.pages["index.html"])
        self.assertIn(", %d resolved</li>" % len(view.resolutions), self.pages["index.html"])


def read(out, rel):
    with open(os.path.join(out, rel), encoding="utf-8") as fh:
        return fh.read()


class LedgerStateTests(unittest.TestCase):
    """The ledger page, category pages, board cards, embeds and share cards before any call resolves and after some
    have. Both chains are built in a temporary folder from the real one, so the published ledger's progress never
    changes what these tests expect."""

    @classmethod
    def setUpClass(cls):
        os.environ["IL_BASE_URL"] = BASE
        cls.tmp = tempfile.TemporaryDirectory()
        real = ledger.load(data.LEDGER)
        first = next((i for i, e in enumerate(real) if e["type"] == "resolution"), len(real))
        unresolved = real[:first]
        slugs = {c["slug"] for c in data.load_categories()}
        view = ledger.View(unresolved)
        cls.seq = {cid: e["seq"] for cid, e in view.calls.items()}
        cls.calls = sorted((e["body"] for e in view.calls.values()), key=lambda b: (b["resolves_on"], cls.seq[b["id"]]))
        cls.first_due = cls.calls[0]["resolves_on"]
        on_board = [b for b in cls.calls if b.get("category") in slugs]
        assert len(on_board) >= 4, "need four calls on category pages to cover yes, no, void and open"
        cls.yes, cls.no, cls.void = on_board[:3]
        cls.today = cls.yes["resolves_on"]
        cls.later = [b for b in on_board[3:] if b["resolves_on"] > cls.today]
        resolved = list(unresolved)
        for b, outcome in ((cls.yes, "yes"), (cls.no, "no"), (cls.void, "void")):
            resolved.append(ledger.make_entry(resolved, "resolution", {
                "call": b["id"], "outcome": outcome, "resolved_on": cls.today, "method": "manual",
                "evidence": [{"text": "Test evidence for %s" % b["id"], "url": "https://example.test/evidence/%s" % b["id"]}]},
                ts=cls.today + "T12:00:00Z"))
        cls.resolved_ids = {cls.yes["id"], cls.no["id"], cls.void["id"]}
        cls.before = cls.build_chain("before", unresolved)
        cls.after = cls.build_chain("after", resolved)

    @classmethod
    def build_chain(cls, name, entries):
        path = os.path.join(cls.tmp.name, name + ".jsonl")
        ledger.write_all(path, entries)
        out = os.path.join(cls.tmp.name, name)
        site.build(out=out, today=cls.today, quiet=True, ledger_path=path)
        with open(os.path.join(out, "ledger", "chain.jsonl"), encoding="utf-8") as fh:
            assert fh.read() == "".join(ledger.canonical(e) + "\n" for e in entries), "build must publish the chain it was given"
        return out

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("IL_BASE_URL", None)
        cls.tmp.cleanup()

    def category(self, out, b):
        return read(out, "category/%s/index.html" % b["category"])

    def test_before_any_resolution_there_is_no_score(self):
        html = read(self.before, "calls/index.html")
        self.assertIn("No call has resolved yet, so there is no score to report", html)
        self.assertIn("The next call fell due on <b>%s</b>" % self.first_due, html)
        self.assertNotIn("Mean Brier score", html)
        self.assertNotIn('class="resolved"', html)
        self.assertIn(", 0 resolved</li>", read(self.before, "index.html"))

    def test_before_any_resolution_calls_show_due_and_open(self):
        self.assertIn("Due, awaiting resolution", self.category(self.before, self.yes))
        for b in self.later:
            html = self.category(self.before, b)
            self.assertIn('<span class="st st-open">Open</span>', html, b["id"])
            self.assertNotIn("Resolved:", html, b["id"])

    def test_after_resolutions_the_ledger_page_scores_them(self):
        html = read(self.after, "calls/index.html")
        brier = ((self.yes["p_pct"] / 100.0 - 1) ** 2 + (self.no["p_pct"] / 100.0) ** 2) / 2
        self.assertIn("<b>2 calls</b> resolved yes or no. Mean Brier score <b>%.3f</b>" % brier, html)
        self.assertIn("1 call resolved void, which is not scored.", html)
        self.assertNotIn("there is no score to report", html)
        self.assertIn("https://example.test/evidence/%s" % self.yes["id"], html)
        nxt = min((b["resolves_on"] for b in self.calls if b["id"] not in self.resolved_ids), default=None)
        if nxt:
            self.assertIn(("The next call is due <b>%s</b>." if nxt > self.today else "The next call fell due on <b>%s</b>") % nxt,
                          html)
        self.assertIn(", 3 resolved</li>", read(self.after, "index.html"))

    def test_after_resolutions_each_category_page_shows_outcome_evidence_and_score(self):
        yes = self.category(self.after, self.yes)
        self.assertIn("Resolved: YES", yes)
        self.assertIn('href="https://example.test/evidence/%s"' % self.yes["id"], yes)
        self.assertIn("Brier score for this call: <b>%.3f</b>" % ((self.yes["p_pct"] / 100.0 - 1) ** 2), yes)
        no = self.category(self.after, self.no)
        self.assertIn("Resolved: NO", no)
        self.assertIn("Brier score for this call: <b>%.3f</b>" % ((self.no["p_pct"] / 100.0) ** 2), no)
        void = self.category(self.after, self.void)
        self.assertIn("Resolved: VOID", void)
        self.assertIn("Void calls are not scored.", void)
        for b in self.later:
            self.assertIn('<span class="st st-open">Open</span>', self.category(self.after, b), b["id"])

    def test_after_resolutions_cards_embeds_and_share_cards_follow_the_lead_call(self):
        home = read(self.after, "index.html")
        for b, label in ((self.yes, "resolved YES"), (self.no, "resolved NO"), (self.void, "voided")):
            same = [x for x in self.calls if x.get("category") == b["category"]]
            still_open = [x for x in same if x["id"] not in self.resolved_ids]
            if still_open:  # a category with an open call leads with its first-registered open call
                lead = sorted(still_open, key=lambda x: self.seq[x["id"]])[0]["resolves_on"]
                expect = ("resolves %s" if lead > self.today else "due %s, awaiting resolution") % lead
            elif len(same) == 1:
                expect = "%s %s" % (label, self.today)
            else:
                continue
            self.assertIn(expect, read(self.after, "embed/%s/index.html" % b["category"]), b["id"])
            self.assertIn(expect, read(self.after, "_og/%s.html" % b["category"]), b["id"])
            if not still_open:
                self.assertIn(expect, home, b["id"])


if __name__ == "__main__":
    unittest.main()
