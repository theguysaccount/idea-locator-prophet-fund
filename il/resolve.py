"""Resolve a manual call on the ledger, with evidence. Used by the scheduled review (see OPERATIONS.md).

    python3 -m il.resolve C1-sema-thicket yes --evidence "India: ... launched 2026-03-20" --url https://... [--url ...]
    python3 -m il.resolve --due          # list calls that are due and unresolved

Rules: only calls on the ledger can be resolved, only once, and never before their resolution date unless the
outcome is already certain (pass --early with a reason). Evidence text and at least one https URL are required.
"""
import argparse
import sys
from datetime import date

from . import data, ledger


def main(argv):
    ap = argparse.ArgumentParser(prog="python3 -m il.resolve")
    ap.add_argument("call", nargs="?")
    ap.add_argument("outcome", nargs="?", choices=ledger.OUTCOMES)
    ap.add_argument("--evidence", action="append", default=[], help="one sentence of evidence (repeatable)")
    ap.add_argument("--url", action="append", default=[], help="https source for the evidence (repeatable)")
    ap.add_argument("--early", help="reason for resolving before the resolution date")
    ap.add_argument("--due", action="store_true", help="list due, unresolved calls and exit")
    args = ap.parse_args(argv)
    today = date.today().isoformat()
    entries = ledger.load(data.LEDGER)
    problems = ledger.verify(entries)
    if problems:
        print("ledger is broken:\n  " + "\n  ".join(problems))
        return 1
    view = ledger.View(entries)
    if args.due:
        due = [e["body"] for cid, e in sorted(view.calls.items())
               if cid not in view.resolutions and e["body"]["resolves_on"] <= today]
        for b in due:
            print("%s  due %s  [%s]  %s" % (b["id"], b["resolves_on"], b["resolver"]["kind"], b["statement"]))
        if not due:
            print("no calls are due")
        return 0
    if not args.call or not args.outcome:
        ap.error("give a call id and an outcome, or --due")
    if args.call not in view.calls:
        print("unknown call %s" % args.call)
        return 1
    if args.call in view.resolutions:
        print("%s is already resolved; resolutions are final" % args.call)
        return 1
    call = view.calls[args.call]["body"]
    if call["resolves_on"] > today and not args.early:
        print("%s resolves on %s; pass --early with a reason if the outcome is already certain" % (args.call, call["resolves_on"]))
        return 1
    if not args.evidence or not args.url or not all(u.startswith("https://") for u in args.url):
        print("evidence text and at least one https URL are required")
        return 1
    evidence = [{"text": t, "url": args.url[min(i, len(args.url) - 1)]} for i, t in enumerate(args.evidence)]
    body = {"call": args.call, "outcome": args.outcome, "resolved_on": today, "method": "manual", "evidence": evidence}
    if args.early:
        body["early_reason"] = args.early
    e = ledger.append(data.LEDGER, entries, "resolution", body)
    print("#%d resolved %s -> %s (%s)" % (e["seq"], args.call, args.outcome, e["hash"][:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
