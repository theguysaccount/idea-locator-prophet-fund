// Node tests for the browser scripts: the ledger verifier must match Python byte for byte,
// and the re-look matcher must map plain descriptions to the right categories.
// Run after a build:  python3 -m il.site && node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

function load(file) {
  const ctx = { window: {}, document: undefined, console };
  vm.createContext(ctx);
  vm.runInContext(readFileSync(path.join(root, file), "utf8"), ctx);
  return ctx.window;
}

test("browser ledger verifier reproduces every Python hash", () => {
  const { ilLedger } = load("site/assets/verify.js");
  const lines = readFileSync(path.join(root, "ledger/chain.jsonl"), "utf8").split("\n").filter((l) => l.trim());
  assert.ok(lines.length > 10);
  let prev = "0".repeat(64);
  for (const line of lines) {
    const e = JSON.parse(line);
    assert.equal(e.prev, prev);
    const h = createHash("sha256").update(ilLedger.payload(e), "utf8").digest("hex");
    assert.equal(h, e.hash, "entry " + e.seq);
    prev = h;
  }
});

test("canonical form escapes non-ASCII like Python", () => {
  const { ilLedger } = load("site/assets/verify.js");
  assert.equal(ilLedger.ascii(ilLedger.canon({ b: 1, a: "é—" })), '{"a":"\\u00e9\\u2014","b":1}');
});

test("re-look matcher maps descriptions to categories", (t) => {
  const relookPath = path.join(root, "dist/data/relook.json");
  if (!existsSync(relookPath)) {
    t.skip("build first: python3 -m il.site");
    return;
  }
  const { ilRelook } = load("site/assets/relook.js");
  ilRelook.setBoard(JSON.parse(readFileSync(relookPath, "utf8")));
  const deals = ilRelook.parseDeals([
    "company,year,description",
    "Webvan, 1999, online grocery delivery from our own warehouses",
    '"Leafy, Inc.", 2020, indoor vertical farming of salad greens',
    "Mystery, 2015, accounting software for dentists",
    "Pear-like, 2021, prescription digital therapeutics app",
  ].join("\n"));
  assert.equal(deals.length, 4);
  assert.equal(deals[1].company, "Leafy, Inc.");
  assert.equal(ilRelook.match(deals[0]).cat.slug, "online-grocery-delivery");
  assert.equal(ilRelook.match(deals[1]).cat.slug, "indoor-vertical-farming");
  assert.equal(ilRelook.match(deals[2]), null);
  assert.equal(ilRelook.match(deals[3]).cat.slug, "prescription-digital-therapeutics");
  // The wording follows the live series, so derive the expected direction from the same data.
  const farm = ilRelook.match(deals[1]).cat;
  const since = ilRelook.since(deals[1], farm);
  const pts = farm.series.points;
  const then = pts.filter((p) => p[0] <= 2020).pop() || pts[0];
  const now = pts[pts.length - 1];
  const better = farm.series.direction === "up" ? now[1] / then[1] : then[1] / now[1];
  const word = better >= 1.25 ? /\u00d7 better\./ : better <= 0.8 ? /\u00d7 worse\./ : /barely moved\./;
  assert.match(since, word);
  assert.match(since, new RegExp("\\(" + then[0] + "\\) \u2192 .+ \\(" + now[0] + "\\)"));
});

test("re-look matcher handles plurals and prefers the more specific category", (t) => {
  const relookPath = path.join(root, "dist/data/relook.json");
  if (!existsSync(relookPath)) {
    t.skip("build first: python3 -m il.site");
    return;
  }
  const { ilRelook } = load("site/assets/relook.js");
  ilRelook.setBoard(JSON.parse(readFileSync(relookPath, "utf8")));
  const [quick, kozmo] = ilRelook.parseDeals("Quick basket, 2021, 15-minute grocery delivery from dark stores\nKozmo, 2000, one-hour delivery of convenience items");
  assert.equal(ilRelook.match(quick).cat.slug, "ultrafast-grocery-delivery");
  const k = ilRelook.match(kozmo);
  assert.equal(k.cat.slug, "on-demand-local-delivery");
  // A deal older than the series falls back to its first point, whatever that point is.
  const first = k.cat.series.points[0];
  assert.ok(first[0] > 2000);
  assert.ok(ilRelook.since(kozmo, k.cat).includes("(" + first[0] + ", earliest data)"));
});
