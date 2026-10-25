"""Render the 1200x630 share images: dist/_og/<name>.html -> dist/og/<name>.png, using headless Chrome.

    python3 scripts/og.py [dist]

If Chrome is missing or a screenshot fails, the committed default image is used for that page, so a share
card never 404s. The HTML cards are removed afterwards so they are not published.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, "site", "og-default.png")
CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "", shutil.which("google-chrome-stable") or "",
    shutil.which("chromium-browser") or "", shutil.which("chromium") or "",
]


def chrome():
    for c in CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def shoot(binary, html, png):
    # Each Chrome gets its own profile: parallel instances sharing one profile fail on Linux runners.
    profile = tempfile.mkdtemp(prefix="il-og-")
    cmd = [binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
           "--force-device-scale-factor=1", "--user-data-dir=" + profile, "--window-size=1200,630",
           "--virtual-time-budget=2000", "--screenshot=" + png, "file://" + html]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90, check=False)
    except subprocess.TimeoutExpired:
        pass
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return os.path.exists(png) and os.path.getsize(png) > 1000


def main(dist):
    dist = os.path.abspath(dist)  # Chrome needs absolute file:// URLs and output paths
    src = os.path.join(dist, "_og")
    out = os.path.join(dist, "og")
    os.makedirs(out, exist_ok=True)
    names = sorted(n[:-5] for n in os.listdir(src) if n.endswith(".html")) if os.path.isdir(src) else []
    binary = chrome()
    ok = 0
    if binary:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: shoot(binary, os.path.join(src, n + ".html"), os.path.join(out, n + ".png")), names))
        ok = sum(results)
    for n in names:
        png = os.path.join(out, n + ".png")
        if not (os.path.exists(png) and os.path.getsize(png) > 1000):
            shutil.copy(DEFAULT, png)
    if not os.path.exists(os.path.join(out, "default.png")):
        shutil.copy(DEFAULT, os.path.join(out, "default.png"))
    shutil.rmtree(src, ignore_errors=True)
    print("share images: %d rendered, %d defaulted (chrome: %s)" % (ok, len(names) - ok, binary or "not found"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist")))
