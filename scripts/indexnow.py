"""Submit URLs to IndexNow (Bing, Yandex, Seznam, Naver and others share submissions).

    python3 scripts/indexnow.py dist/urls.txt [base_url]

The key file is published at <base>/<key>.txt by the build. Failures are reported but never fail a deploy.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASE = "https://theguysaccount.github.io/idea-locator-prophet-fund"


def main(url_file, base):
    base = base.rstrip("/")
    with open(os.path.join(ROOT, "site", "indexnow-key.txt")) as fh:
        key = fh.read().strip()
    with open(url_file) as fh:
        urls = [u.strip() for u in fh if u.strip().startswith(base + "/")]
    if not urls:
        print("no URLs to submit")
        return 0
    host = urllib.parse.urlparse(base).netloc
    body = {"host": host, "key": key, "keyLocation": "%s/%s.txt" % (base, key), "urlList": urls[:10000]}
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "User-Agent": "idea-locator-prophet-fund/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print("IndexNow: HTTP %s for %d URLs" % (resp.status, len(body["urlList"])))
    except urllib.error.HTTPError as exc:
        print("IndexNow: HTTP %s (%s)" % (exc.code, exc.read()[:200]))
    except Exception as exc:
        print("IndexNow: failed (%s)" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.environ.get("IL_BASE_URL", DEFAULT_BASE)))
