import json
import os
import re
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from il import data, site

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
        cls.ctx = site.build(out=cls.tmp.name, today="2026-10-25", quiet=True)
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

    def test_ledger_page_shows_no_fake_score(self):
        html = self.pages["calls/index.html"]
        self.assertIn("No call has resolved yet", html)


if __name__ == "__main__":
    unittest.main()
