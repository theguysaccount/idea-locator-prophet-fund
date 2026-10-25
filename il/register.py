"""Write pending calls and verdict changes onto the ledger.

    python3 -m il.register           # append what is missing, print what was added
    python3 -m il.register --check   # exit 1 if data/ and the ledger disagree (used by tests and CI)

A call in data/calls.json is registered once; after that the ledger is the source of truth and editing
calls.json cannot change it (tests fail if the two disagree). A verdict in a category file that differs from
the latest verdict on the ledger is appended as a new, dated verdict entry.
"""
import sys

from . import data, ledger

GENESIS = {
    "statement": ("Idea Locator ripeness ledger. Calls, verdicts and resolutions are appended in order and never edited. "
                  "Each entry carries the hash of the one before it."),
    "registered": "2026-10-25",
    "prior": ("Calls C1-C5 were first frozen on 2026-08-01 in a private research chain (head 5b7eb13507f6...) that was never "
              "published. This public chain starts fresh; those calls keep their first-stated date, but only the public "
              "registration date counts for scoring."),
}


def pending(entries, calls, cats):
    view = ledger.View(entries)
    todo = []
    if not entries:
        todo.append(("genesis", GENESIS))
    for call in calls:
        on_chain = view.calls.get(call["id"])
        if on_chain is None:
            todo.append(("call", call))
    for c in cats:
        current = view.verdicts.get(c["slug"])
        if current is None or current["body"]["verdict"] != c["verdict"]:
            body = {"category": c["slug"], "verdict": c["verdict"], "reason": c["verdict_reason"]}
            if current is not None:
                body["from"] = current["body"]["verdict"]
            todo.append(("verdict", body))
    return todo


def mismatched_calls(entries, calls):
    view = ledger.View(entries)
    bad = []
    for call in calls:
        e = view.calls.get(call["id"])
        if e is not None and ledger.canonical(e["body"]) != ledger.canonical(call):
            bad.append(call["id"])
    return bad


def main(argv):
    check = "--check" in argv
    entries = ledger.load(data.LEDGER)
    problems = ledger.verify(entries)
    if problems:
        print("ledger is broken:\n  " + "\n  ".join(problems))
        return 1
    calls, cats = data.load_calls(), data.load_categories()
    errors = data.validate(cats, calls)
    if errors:
        print("data problems:\n  " + "\n  ".join(errors))
        return 1
    bad = mismatched_calls(entries, calls)
    if bad:
        print("calls.json differs from the ledger for %s. Registered calls cannot change; add a new call instead." % ", ".join(bad))
        return 1
    todo = pending(entries, calls, cats)
    if check:
        if todo:
            print("ledger is behind data/: %d entries to register (run python3 -m il.register)" % len(todo))
            for t, b in todo:
                print("  %s %s" % (t, b.get("id") or b.get("category") or ""))
            return 1
        print("ledger in sync with data/ (%d entries, head %s)" % (len(entries), entries[-1]["hash"][:12] if entries else "-"))
        return 0
    for etype, body in todo:
        e = ledger.append(data.LEDGER, entries, etype, body)
        print("#%d %s %s %s" % (e["seq"], etype, body.get("id") or body.get("category") or "", e["hash"][:12]))
    if not todo:
        print("nothing to register")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
