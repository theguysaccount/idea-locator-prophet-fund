import unittest

from il import data, ledger


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cats = data.load_categories()
        cls.calls = data.load_calls()

    def test_data_validates(self):
        self.assertEqual(data.validate(self.cats, self.calls), [])

    def test_ripe_needs_a_named_sourced_graveyard(self):
        for c in self.cats:
            if c["verdict"] == "ripe":
                sourced = [g for g in c["graveyard"] if g.get("source")]
                self.assertGreaterEqual(len(sourced), 2, c["slug"])

    def test_every_live_category_has_a_reason_and_a_way_to_resolve(self):
        view = ledger.View(ledger.load(data.LEDGER))
        for c in self.cats:
            if c["kind"] != "live":
                continue
            has_signal = bool(c.get("metric") or c.get("fr") or c.get("trials") or view.calls_for(c["slug"]))
            if c["verdict"] in ("pending", "check"):
                self.assertTrue(has_signal or c.get("graveyard_note"), "%s has nothing to watch" % c["slug"])

    def test_myths_name_their_disqualifying_test(self):
        for c in self.cats:
            if c["kind"] == "myth":
                self.assertIn(c["myth_test"], data.MYTH_TESTS)

    def test_no_placeholder_text(self):
        bad = ("TODO", "TBD", "lorem", "XXX", "FIXME")
        for c in self.cats:
            blob = repr(c)
            for word in bad:
                self.assertNotIn(word, blob, c["slug"])

    def test_calls_are_falsifiable(self):
        for call in self.calls:
            self.assertTrue(call["falsifier"].strip())
            if call["resolver"]["kind"] == "manual":
                self.assertTrue(call["resolver"].get("how"), call["id"])

    def test_slip_rows_are_consistent(self):
        rows = data.load_slips()["rows"]
        self.assertGreaterEqual(len(rows), 20)
        for r in rows:
            self.assertIn(r["outcome"], ("held", "late", "early", "killed", "pending"))
            if r["outcome"] == "held":
                self.assertEqual(r["slip_months"], 0, r["commitment"])
            if r["outcome"] == "late":
                self.assertGreater(r["slip_months"], 0, r["commitment"])
            if r["outcome"] == "early":
                self.assertLess(r["slip_months"], 0, r["commitment"])
            self.assertTrue(r["source"].startswith("https://"), r["commitment"])


if __name__ == "__main__":
    unittest.main()
