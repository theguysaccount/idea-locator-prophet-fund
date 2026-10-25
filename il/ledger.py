"""Append-only, hash-chained ledger of dated calls, verdicts and resolutions.

Each line of ledger/chain.jsonl is one entry:
    {"seq": n, "type": ..., "ts": ..., "body": {...}, "prev": <hash of entry n-1>, "hash": <sha256>}

hash = sha256(canonical({"seq","type","ts","body","prev"})). Canonical JSON is
sorted keys, no whitespace, ASCII-escaped, so the browser (site/assets/verify.js)
recomputes byte-identical hashes. Bodies never hold floats: numbers that are not
integers are stored as strings, because float formatting differs between languages.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

GENESIS_PREV = "0" * 64
TYPES = ("genesis", "call", "verdict", "resolution", "note")
OUTCOMES = ("yes", "no", "void")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def entry_hash(entry):
    core = {k: entry[k] for k in ("seq", "type", "ts", "body", "prev")}
    return hashlib.sha256(canonical(core).encode("ascii")).hexdigest()


def _check_no_floats(value, where):
    if isinstance(value, float):
        raise ValueError("float in ledger body at %s: store %r as a string" % (where, value))
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not k.isascii():
                raise ValueError("non-ASCII or non-string key at %s" % where)
            _check_no_floats(v, where + "." + k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_no_floats(v, "%s[%d]" % (where, i))


def now_ts():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except ValueError as exc:
                    raise ValueError("ledger line %d is not JSON: %s" % (n, exc))
    return entries


def verify(entries):
    """Return a list of problems; empty means the chain is intact."""
    problems = []
    prev = GENESIS_PREV
    for i, e in enumerate(entries):
        tag = "entry %d" % i
        missing = [k for k in ("seq", "type", "ts", "body", "prev", "hash") if k not in e]
        if missing:
            problems.append("%s: missing %s" % (tag, ", ".join(missing)))
            continue
        if e["seq"] != i:
            problems.append("%s: seq is %r" % (tag, e["seq"]))
        if e["type"] not in TYPES:
            problems.append("%s: unknown type %r" % (tag, e["type"]))
        if i == 0 and e["type"] != "genesis":
            problems.append("entry 0 must be genesis")
        if e["prev"] != prev:
            problems.append("%s: prev does not match the hash of entry %d" % (tag, i - 1))
        try:
            _check_no_floats(e["body"], tag)
        except ValueError as exc:
            problems.append(str(exc))
        if entry_hash(e) != e["hash"]:
            problems.append("%s: hash mismatch (entry edited after it was written)" % tag)
        prev = e["hash"]
    return problems


def is_prefix(old, new):
    """True when `new` extends `old` without changing any existing entry."""
    if len(new) < len(old):
        return False
    return all(a.get("hash") == b.get("hash") for a, b in zip(old, new))


def make_entry(entries, etype, body, ts=None):
    if etype not in TYPES:
        raise ValueError("unknown entry type %r" % etype)
    _check_no_floats(body, "body")
    prev = entries[-1]["hash"] if entries else GENESIS_PREV
    e = {"seq": len(entries), "type": etype, "ts": ts or now_ts(), "body": body, "prev": prev}
    e["hash"] = entry_hash(e)
    return e


def append(path, entries, etype, body, ts=None):
    """Append one entry to the in-memory chain and to the file. Returns the entry."""
    e = make_entry(entries, etype, body, ts)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(canonical(e) + "\n")
    entries.append(e)
    return e


def write_all(path, entries):
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(canonical(e) + "\n")


class View:
    """Calls, current verdicts and resolutions folded out of the chain."""

    def __init__(self, entries):
        self.entries = entries
        self.calls = {}          # call id -> entry
        self.resolutions = {}    # call id -> entry
        self.verdicts = {}       # category slug -> latest verdict entry
        self.verdict_history = {}
        for e in entries:
            b = e["body"]
            if e["type"] == "call":
                self.calls[b["id"]] = e
            elif e["type"] == "resolution":
                self.resolutions[b["call"]] = e
            elif e["type"] == "verdict":
                self.verdicts[b["category"]] = e
                self.verdict_history.setdefault(b["category"], []).append(e)

    @property
    def head(self):
        return self.entries[-1]["hash"] if self.entries else GENESIS_PREV

    def calls_for(self, slug):
        return [e for e in self.calls.values() if e["body"].get("category") == slug]

    def status(self, call_id, today):
        if call_id in self.resolutions:
            return "resolved"
        due = self.calls[call_id]["body"]["resolves_on"]
        return "due" if due <= today else "open"

    def scored(self):
        """Resolved yes/no calls with their Brier score."""
        rows = []
        for cid, r in self.resolutions.items():
            outcome = r["body"]["outcome"]
            if outcome == "void" or cid not in self.calls:
                continue
            p = self.calls[cid]["body"]["p_pct"] / 100.0
            o = 1.0 if outcome == "yes" else 0.0
            rows.append({"call": cid, "p": p, "outcome": outcome, "brier": (p - o) ** 2})
        return rows
