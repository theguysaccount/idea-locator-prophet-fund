import json
import unittest

from il import ledger, refresh

FRED_CSV = "observation_date,X\n2026-01-01,100\n2026-02-01,101\n2026-03-01,.\n2026-09-01,110\n"


class ParserTests(unittest.TestCase):
    def test_fred_skips_missing_values(self):
        pts = refresh.parse_fred(FRED_CSV)
        self.assertEqual(pts, [["2026-01-01", "100"], ["2026-02-01", "101"], ["2026-09-01", "110"]])

    def test_owid_filters_entity(self):
        text = "entity,code,year,cost\nWorld,OWID_WRL,2020,5.5\nChina,CHN,2020,1\nWorld,OWID_WRL,2021,4\n"
        self.assertEqual(refresh.parse_owid(text, "cost", "World"), [["2020", "5.5"], ["2021", "4"]])

    def test_worldbank(self):
        doc = [{"page": 1}, [{"date": "2024", "value": 38.8}, {"date": "2025", "value": None}, {"date": "2023", "value": 38}]]
        self.assertEqual(refresh.parse_worldbank(json.dumps(doc)), [["2023", "38"], ["2024", "38.8"]])

    def test_bad_responses_raise(self):
        with self.assertRaises(ValueError):
            refresh.parse_fred("observation_date,X\n")
        with self.assertRaises(ValueError):
            refresh.parse_worldbank(json.dumps([{"message": "error"}]))


def fred_call(**over):
    c = {"id": "T1", "resolves_on": "2026-10-31", "p_pct": 50,
         "resolver": {"kind": "fred", "series": "X", "op": "gt", "left": {"date": "2026-09-01"}, "right": {"date": "2026-01-01"}}}
    c["resolver"].update(over)
    return c


class ResolverTests(unittest.TestCase):
    metrics = {"fred:X": {"points": refresh.parse_fred(FRED_CSV)}}

    def test_fred_yes(self):
        self.assertEqual(refresh.resolve_fred(fred_call(), self.metrics)["outcome"], "yes")

    def test_fred_no(self):
        self.assertEqual(refresh.resolve_fred(fred_call(op="lt"), self.metrics)["outcome"], "no")

    def test_fred_waits_for_data(self):
        self.assertIsNone(refresh.resolve_fred(fred_call(left={"date": "2027-09-01"}), self.metrics))

    def test_fred_average_needs_every_month(self):
        call = fred_call(left={"avg": ["2026-01-01", "2026-03-01"]}, right={"value": "50"})
        self.assertIsNone(refresh.resolve_fred(call, self.metrics))  # March is missing
        call = fred_call(left={"avg": ["2026-01-01", "2026-02-01"]}, right={"value": "100"}, op="ge")
        self.assertEqual(refresh.resolve_fred(call, self.metrics)["outcome"], "yes")

    def test_fred_scale(self):
        call = fred_call(right={"date": "2026-01-01"}, right_scale="1.2")
        self.assertEqual(refresh.resolve_fred(call, self.metrics)["outcome"], "no")  # 110 < 120

    def fr_getter(self, results):
        return lambda url: json.dumps({"results": results})

    def test_federal_register_hit_resolves_yes_early(self):
        call = {"id": "T2", "resolves_on": "2027-06-30", "resolver": {"kind": "federal_register", "rin": "2120-AL82",
                                                                       "type": "RULE", "since": "2026-10-25"}}
        doc = {"title": "Normalizing BVLOS", "type": "Rule", "document_number": "2027-1", "publication_date": "2027-03-01",
               "html_url": "https://www.federalregister.gov/d/2027-1"}
        res = refresh.resolve_federal_register(call, "2027-03-02", getter=self.fr_getter([doc]))
        self.assertEqual(res["outcome"], "yes")
        self.assertIn("2027-1", res["evidence"][0]["text"])

    def test_federal_register_waits_then_resolves_no(self):
        call = {"id": "T2", "resolves_on": "2027-06-30", "resolver": {"kind": "federal_register", "rin": "2120-AL82",
                                                                       "type": "RULE", "since": "2026-10-25"}}
        self.assertIsNone(refresh.resolve_federal_register(call, "2027-01-01", getter=self.fr_getter([])))
        self.assertEqual(refresh.resolve_federal_register(call, "2027-07-01", getter=self.fr_getter([]))["outcome"], "no")

    def test_federal_register_title_filter_and_window(self):
        call = {"id": "T3", "resolves_on": "2027-01-31", "resolver": {"kind": "federal_register", "term": "G0552", "type": "RULE",
                                                                       "since": "2026-10-25", "title_contains": ["CY 2027", "Physician Fee Schedule"]}}
        wrong_year = {"title": "CY 2026 Payment Policies Under the Physician Fee Schedule", "type": "Rule", "document_number": "a",
                      "publication_date": "2026-11-05", "html_url": "https://x"}
        late = {"title": "CY 2027 Payment Policies Under the Physician Fee Schedule", "type": "Rule", "document_number": "b",
                "publication_date": "2027-02-15", "html_url": "https://x"}
        self.assertIsNone(refresh.resolve_federal_register(call, "2026-12-01", getter=self.fr_getter([wrong_year, late])))
        good = dict(late, publication_date="2026-11-04", document_number="c")
        self.assertEqual(refresh.resolve_federal_register(call, "2026-12-01", getter=self.fr_getter([good]))["outcome"], "yes")

    def test_clinicaltrials(self):
        call = {"id": "T4", "resolves_on": "2027-12-31", "resolver": {"kind": "clinicaltrials", "sponsor": "Synchron",
                                                                       "title_contains": "pivotal", "first_posted_after": "2026-10-25"}}

        def getter(studies):
            return lambda url: json.dumps({"studies": studies})

        def study(title, posted, sponsor="Synchron, Inc.", kind="INTERVENTIONAL"):
            return {"protocolSection": {"identificationModule": {"nctId": "NCT1", "briefTitle": title},
                                        "statusModule": {"overallStatus": "RECRUITING", "studyFirstPostDateStruct": {"date": posted}},
                                        "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
                                        "designModule": {"studyType": kind}}}

        old = study("A pivotal study", "2025-01-01")
        self.assertIsNone(refresh.resolve_clinicaltrials(call, "2027-01-01", getter=getter([old])))
        new = study("COMMAND Pivotal Trial", "2027-03-01")
        self.assertEqual(refresh.resolve_clinicaltrials(call, "2027-04-01", getter=getter([new]))["outcome"], "yes")
        self.assertEqual(refresh.resolve_clinicaltrials(call, "2028-01-02", getter=getter([old]))["outcome"], "no")

    def test_run_resolvers_appends_a_verifiable_resolution(self):
        entries = []
        entries.append(ledger.make_entry(entries, "genesis", {"statement": "g"}))
        entries.append(ledger.make_entry(entries, "call", fred_call()))
        log = refresh.run_resolvers(entries, self.metrics, "2026-11-01", getter=lambda u: "{}")
        self.assertEqual(log[0]["status"], "resolved")
        self.assertEqual(entries[-1]["type"], "resolution")
        self.assertEqual(ledger.verify(entries), [])
        # A second run must not resolve the same call twice.
        refresh.run_resolvers(entries, self.metrics, "2026-11-02", getter=lambda u: "{}")
        self.assertEqual(sum(1 for e in entries if e["type"] == "resolution"), 1)

    def test_stale_sources_after_four_weeks(self):
        live = {"metrics": {"fred:X": {"status": "stale", "failing_since": "2026-09-01"},
                            "fred:Y": {"status": "stale", "failing_since": "2026-10-20"}},
                "calendar": {"status": "ok"}, "trials": {}}
        self.assertEqual(refresh.stale_sources(live, "2026-10-25"), ["fred:X"])

    def test_failed_fetch_keeps_last_good_values(self):
        rec = refresh.mark_stale({"status": "ok", "points": [["2026-01-01", "1"]]}, "boom", "2026-10-25")
        self.assertEqual(rec["points"], [["2026-01-01", "1"]])
        self.assertEqual(rec["status"], "stale")
        again = refresh.mark_stale(rec, "boom", "2026-11-01")
        self.assertEqual(again["failing_since"], "2026-10-25")


if __name__ == "__main__":
    unittest.main()
