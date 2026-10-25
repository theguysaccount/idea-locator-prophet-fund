"""Refuse to deploy a ledger that does not extend the one already live.

    python3 scripts/guard_ledger.py https://<site>/ledger/chain.jsonl ledger/chain.jsonl

Exit 0: the new chain verifies and starts with every live entry, unchanged (or nothing is live yet: 404).
Exit 1: the live chain could not be read for another reason, or history would be rewritten.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from il import ledger  # noqa: E402

UA = "idea-locator-prophet-fund/1.0 (+https://github.com/theguysaccount/idea-locator-prophet-fund)"


def fetch(url):
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + "nocache=1", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read().decode("utf-8")


def main(live_url, local_path):
    new = ledger.load(local_path)
    problems = ledger.verify(new)
    if problems:
        print("local ledger does not verify:\n  " + "\n  ".join(problems))
        return 1
    try:
        text = fetch(live_url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print("no live ledger yet (404); first deploy allowed with %d entries" % len(new))
            return 0
        print("could not read the live ledger (HTTP %s); refusing to deploy" % exc.code)
        return 1
    except Exception as exc:
        print("could not read the live ledger (%s); refusing to deploy" % exc)
        return 1
    old = [json.loads(line) for line in text.splitlines() if line.strip()]
    if ledger.verify(old):
        print("the live ledger does not verify; refusing to deploy on top of it")
        return 1
    if not ledger.is_prefix(old, new):
        print("REFUSED: the new ledger changes or drops entries that are already public (%d live, %d new)" % (len(old), len(new)))
        return 1
    print("ok: %d live entries preserved, %d new" % (len(old), len(new) - len(old)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
