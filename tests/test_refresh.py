import contextlib
import copy
import io
import json
import os
import shutil
import socket
import tempfile
import unittest
import urllib.error
from unittest import mock

from il import data, ledger, refresh

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



class FakeResponse:
    def __init__(self, body):
        self.buf = io.BytesIO(body.encode("utf-8"))

    def read(self, n=-1):
        return self.buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RetryTests(unittest.TestCase):
    URL = "https://api.worldbank.org/v2/country/USA/indicator/IT.NET.BBND.P2?format=json"

    def get(self, outcomes, **kw):
        """Run http_get against a scripted sequence of urlopen outcomes; returns (result or exception, attempts, waits)."""
        attempts, waits = [], []

        def urlopen(req, timeout):
            attempts.append(timeout)
            out = outcomes[len(attempts) - 1]
            if isinstance(out, Exception):
                raise out
            return FakeResponse(out)

        with mock.patch.object(refresh.urllib.request, "urlopen", urlopen), contextlib.redirect_stdout(io.StringIO()):
            try:
                result = refresh.http_get(self.URL, sleep=waits.append, **kw)
            except RuntimeError as exc:
                result = exc
        return result, attempts, waits

    def test_a_timeout_is_retried_with_growing_waits_then_reported(self):
        err = socket.timeout("The read operation timed out")
        result, attempts, waits = self.get([err, err, err])
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(len(attempts), refresh.ATTEMPTS)
        self.assertEqual(len(waits), refresh.ATTEMPTS - 1)
        self.assertTrue(2 <= waits[0] < 3 and 4 <= waits[1] < 5, waits)
        for n in range(1, refresh.ATTEMPTS + 1):
            self.assertIn("attempt %d" % n, str(result))

    def test_a_slow_source_that_answers_on_retry_is_used(self):
        result, attempts, _ = self.get([socket.timeout("timed out"), '[{"page": 1}, []]'])
        self.assertEqual(result, '[{"page": 1}, []]')
        self.assertEqual(len(attempts), 2)

    def test_client_errors_are_not_retried_but_server_errors_are(self):
        not_found = urllib.error.HTTPError(self.URL, 404, "Not Found", {}, None)
        _, attempts, _ = self.get([not_found])
        self.assertEqual(len(attempts), 1)
        busy = urllib.error.HTTPError(self.URL, 503, "Busy", {}, None)
        result, attempts, _ = self.get([busy, "ok"])
        self.assertEqual((result, len(attempts)), ("ok", 2))

    def test_a_spent_budget_starts_no_attempt(self):
        result, attempts, _ = self.get([], budget=refresh.Budget(0))
        self.assertEqual(attempts, [])
        self.assertIn("time budget", str(result))

    def test_attempts_never_outlast_the_budget(self):
        clock = [0.0]
        budget = refresh.Budget(12, clock=lambda: clock[0])
        clock[0] = 4.0  # 8 s left: the attempt's socket timeout shrinks to fit
        _, attempts, waits = self.get([socket.timeout("t"), socket.timeout("t"), socket.timeout("t")], budget=budget)
        self.assertTrue(all(t <= 8 for t in attempts), attempts)
        self.assertTrue(all(w <= 8 for w in waits), waits)

    def test_a_trickling_body_is_cut_off_at_the_wall_clock_cap(self):
        with self.assertRaises(TimeoutError):
            refresh._read_capped(FakeResponse("x" * 10), deadline=0)


class SlowSourceRunTests(unittest.TestCase):
    """A full refresh where one source times out on every attempt: the run still succeeds, the slow source keeps its
    last good data marked stale, and every other source refreshes. Runs on temporary copies of data/live and the
    ledger with a scripted network, so it never touches the repository's files or the internet."""

    TODAY = "2026-11-09"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live_dir = os.path.join(self.tmp.name, "live")
        shutil.copytree(data.LIVE, self.live_dir)
        self.chain = os.path.join(self.tmp.name, "chain.jsonl")
        shutil.copy(data.LEDGER, self.chain)
        self.old_live = data.load_live()
        cats = data.load_categories()
        self.owid_columns = sorted({c["metric"]["source"]["column"] for c in cats
                                    if c.get("metric") and c["metric"]["source"]["kind"] == "owid"})
        self.slow = sorted({data.series_key(c["metric"]["source"]) for c in cats
                            if c.get("metric") and c["metric"]["source"]["kind"] == "worldbank"})
        self.assertTrue(self.slow, "the board has a World Bank series to make slow")
        self.requests = []

    def tearDown(self):
        self.tmp.cleanup()

    def network(self, url):
        self.requests.append(url)
        if "api.worldbank.org" in url:
            raise RuntimeError("GET %s failed: attempt 1 (30s): The read operation timed out" % url)
        if "fredgraph.csv" in url:
            return "observation_date,X\n2026-08-01,100\n2026-09-01,101\n"
        if "ourworldindata.org" in url:
            header = "entity,code,year," + ",".join(self.owid_columns)
            return header + "\nWorld,OWID_WRL,2025," + ",".join("1" for _ in self.owid_columns) + "\n"
        if "federalregister.gov" in url:
            return json.dumps({"results": []})
        if "clinicaltrials.gov" in url:
            return json.dumps({"studies": []})
        raise AssertionError("unexpected URL " + url)

    def run_refresh(self):
        with mock.patch.object(data, "LIVE", self.live_dir), mock.patch.object(data, "LEDGER", self.chain), \
                mock.patch.object(data, "load_live", lambda: copy.deepcopy(self.old_live)), \
                mock.patch.object(refresh.time, "sleep", lambda s: None), contextlib.redirect_stdout(io.StringIO()) as out:
            rc = refresh.main([], today=self.TODAY, getter=self.network)
        return rc, out.getvalue()

    def test_one_slow_source_does_not_fail_the_refresh(self):
        before = {f: open(os.path.join(data.LIVE, f), encoding="utf-8").read() for f in os.listdir(data.LIVE)}
        rc, log = self.run_refresh()
        self.assertEqual(rc, 0, log)
        metrics = data.read_json(os.path.join(self.live_dir, "metrics.json"))
        for key in self.slow:
            rec, old = metrics[key], self.old_live["metrics"].get(key, {})
            self.assertEqual(rec["status"], "stale")
            self.assertIn("timed out", rec["error"])
            self.assertEqual(rec.get("points"), old.get("points"), "last good values are kept")
            self.assertEqual(rec["failing_since"], old.get("failing_since") or self.TODAY)
            self.assertIn("FAIL %s" % key, log)
        others = [k for k in metrics if k not in self.slow]
        self.assertTrue(others)
        for key in others:
            self.assertEqual(metrics[key]["status"], "ok", key)
        runs = data.read_json(os.path.join(self.live_dir, "runs.json"))
        self.assertEqual(runs["stale_now"], self.slow)
        self.assertEqual(runs["stale_over_%d_days" % refresh.STALE_ALERT_DAYS], [])
        self.assertEqual(data.read_json(os.path.join(self.live_dir, "calendar.json"))["status"], "ok")
        self.assertEqual(ledger.verify(ledger.load(self.chain)), [])
        after = {f: open(os.path.join(data.LIVE, f), encoding="utf-8").read() for f in os.listdir(data.LIVE)}
        self.assertEqual(before, after, "the repository's data/live must not be touched by the test")


if __name__ == "__main__":
    unittest.main()
