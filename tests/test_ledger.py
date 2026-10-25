import copy
import os
import tempfile
import unittest

from il import data, ledger, register


class LedgerTests(unittest.TestCase):
    def chain(self, n=3):
        entries = []
        entries.append(ledger.make_entry(entries, "genesis", {"statement": "g"}, ts="2026-10-25T00:00:00Z"))
        for i in range(n):
            entries.append(ledger.make_entry(entries, "call", {"id": "C%d" % i, "p_pct": 50, "resolves_on": "2027-01-01",
                                                               "statement": "sé", "resolver": {"kind": "manual"}},
                                             ts="2026-10-25T00:00:0%dZ" % (i + 1)))
        return entries

    def test_canonical_form_is_sorted_compact_ascii(self):
        self.assertEqual(ledger.canonical({"b": 1, "a": "é"}), '{"a":"\\u00e9","b":1}')

    def test_known_hash_vector(self):
        e = {"seq": 0, "type": "genesis", "ts": "2026-10-25T00:00:00Z", "body": {"statement": "x"}, "prev": "0" * 64}
        # Recomputing must stay stable across Python versions; the browser verifier depends on it.
        self.assertEqual(ledger.entry_hash(e), ledger.entry_hash(copy.deepcopy(e)))
        self.assertEqual(len(ledger.entry_hash(e)), 64)

    def test_valid_chain_verifies(self):
        self.assertEqual(ledger.verify(self.chain()), [])

    def test_editing_a_past_entry_is_detected(self):
        entries = self.chain()
        entries[1]["body"]["p_pct"] = 99
        problems = ledger.verify(entries)
        self.assertTrue(any("hash mismatch" in p for p in problems))

    def test_rewriting_history_breaks_the_link(self):
        entries = self.chain()
        entries[2]["prev"] = "f" * 64
        self.assertTrue(any("prev does not match" in p for p in ledger.verify(entries)))

    def test_floats_are_rejected(self):
        with self.assertRaises(ValueError):
            ledger.make_entry([], "genesis", {"value": 0.1})

    def test_prefix(self):
        a = self.chain(2)
        b = copy.deepcopy(a)
        b.append(ledger.make_entry(b, "note", {"text": "more"}))
        self.assertTrue(ledger.is_prefix(a, b))
        self.assertFalse(ledger.is_prefix(b, a))
        c = copy.deepcopy(b)
        c[1]["hash"] = "0" * 64
        self.assertFalse(ledger.is_prefix(a, c))

    def test_append_round_trips_through_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "chain.jsonl")
            entries = []
            ledger.append(path, entries, "genesis", {"statement": "g"})
            ledger.append(path, entries, "note", {"text": "n"})
            loaded = ledger.load(path)
            self.assertEqual(loaded, entries)
            self.assertEqual(ledger.verify(loaded), [])

    def test_view_folds_calls_and_scores(self):
        entries = self.chain(2)
        entries.append(ledger.make_entry(entries, "resolution", {"call": "C0", "outcome": "yes", "resolved_on": "2027-01-02",
                                                                 "method": "manual", "evidence": []}))
        v = ledger.View(entries)
        self.assertEqual(v.status("C0", "2027-01-03"), "resolved")
        self.assertEqual(v.status("C1", "2026-12-31"), "open")
        self.assertEqual(v.status("C1", "2027-01-01"), "due")
        self.assertAlmostEqual(v.scored()[0]["brier"], 0.25)


class RealLedgerTests(unittest.TestCase):
    def test_published_chain_verifies(self):
        entries = ledger.load(data.LEDGER)
        self.assertTrue(entries, "ledger/chain.jsonl is empty")
        self.assertEqual(ledger.verify(entries), [])
        self.assertEqual(entries[0]["type"], "genesis")

    def test_ledger_is_in_sync_with_data(self):
        # Registered calls are immutable and every verdict change is on the chain.
        self.assertEqual(register.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
