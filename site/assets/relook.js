// Re-look screen. Everything runs in this page: the deals you paste never leave your browser.
(function () {
  "use strict";
  var board = null, lastRows = [];
  var SAMPLE = [
    "Webvan, 1999, online grocery delivery from our own automated warehouses",
    "Kozmo, 2000, one-hour delivery of convenience items in cities",
    "Recovery app, 2021, prescription digital therapeutics app for substance use disorder",
    "Gene coach, 2018, genome-based wellness coaching subscription",
    "Mach jet, 2019, supersonic business jet for transatlantic routes",
    "Leafy, 2020, indoor vertical farming of salad greens",
    "Pawshop, 2009, online pet supplies with free shipping",
    "Haul Co, 2022, digital freight brokerage marketplace for truckload",
    "Quick basket, 2021, 15-minute grocery delivery from dark stores",
    "Blockly, 2015, accounting software for dentists"
  ].join("\n");

  function load() {
    if (board) return Promise.resolve(board);
    return fetch("../data/relook.json").then(function (r) { return r.json(); }).then(function (d) { board = d; return d; });
  }

  function parseCSVLine(line) {
    var out = [], cur = "", q = false;
    for (var i = 0; i < line.length; i++) {
      var c = line[i];
      if (q) {
        if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
        else if (c === '"') q = false;
        else cur += c;
      } else if (c === '"') q = true;
      else if (c === ",") { out.push(cur); cur = ""; }
      else cur += c;
    }
    out.push(cur);
    return out.map(function (s) { return s.trim(); });
  }

  function parseDeals(text) {
    var deals = [];
    text.split(/\r?\n/).forEach(function (line) {
      if (!line.trim()) return;
      var f = parseCSVLine(line);
      if (/^(company|name)$/i.test(f[0]) && /year/i.test(f[1] || "")) return; // header row
      var year = parseInt(f[1], 10);
      var desc = f.slice(2).join(", ");
      if (isNaN(year)) { desc = f.slice(1).join(", "); year = null; }
      deals.push({ company: f[0], year: year, desc: desc || f[0] });
    });
    return deals.slice(0, 500);
  }

  function norm(s) { return " " + String(s).toLowerCase().replace(/[^a-z0-9]+/g, " ") + " "; }

  function match(deal) {
    var text = norm(deal.desc + " " + deal.company);
    var best = null, bestScore = 0;
    board.categories.forEach(function (c) {
      var score = 0;
      c.keywords.forEach(function (k) {
        var kk = norm(k);
        if (text.indexOf(kk) !== -1) score += kk.trim().split(" ").length * 2 - 1;
      });
      if (score > bestScore) { bestScore = score; best = c; }
    });
    return bestScore > 0 ? { cat: best, score: bestScore } : null;
  }

  function fmt(v) {
    var a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toPrecision(3) + "M";
    if (a >= 1000) return Math.round(v).toLocaleString();
    if (a >= 1) return (Math.round(v * 100) / 100).toString();
    return (Math.round(v * 1000) / 1000).toString();
  }

  function since(deal, c) {
    if (c.verdict === "not-timing") return "Not a timing failure: the enabler already existed, so waiting does not change the answer.";
    if (c.verdict === "unknown") return "I don't know: the board abstains on this category (the named blocker crossed, or never moved, without deciding it).";
    var bits = [];
    if (c.series && c.series.points.length && deal.year) {
      var pts = c.series.points, then = null;
      for (var i = 0; i < pts.length; i++) if (pts[i][0] <= deal.year) then = pts[i];
      var now = pts[pts.length - 1];
      if (!then) then = pts[0];
      if (then && now && then[0] !== now[0]) {
        var ratio = now[1] / then[1];
        var better = c.series.direction === "up" ? ratio : 1 / ratio;
        var moved = better >= 1.25 ? (better >= 100 ? Math.round(better).toLocaleString() : better.toFixed(1)) + "× better" :
          better <= 0.8 ? (1 / better).toFixed(1) + "× worse" : "barely moved";
        bits.push(c.series.label.replace(/ \(.*\)$/, "") + ": " + fmt(then[1]) + " (" + then[0] + ") → " + fmt(now[1]) + " (" + now[0] + "), " + moved + ".");
      }
    }
    var cy = c.crossing ? parseInt(c.crossing, 10) : NaN;
    if (!isNaN(cy) && deal.year) {
      bits.push(cy > deal.year ? "The constraint crossed in " + cy + ", after you passed." : "The constraint had crossed by " + cy + ", before you passed.");
    } else if (c.crossing === "pending") {
      bits.push("The trigger is still pending.");
    }
    if (!bits.length) bits.push("No public series for this constraint yet; see the category page.");
    return bits.join(" ");
  }

  if (typeof window !== "undefined") {
    window.ilRelook = { parseDeals: parseDeals, setBoard: function (b) { board = b; }, match: match, since: since };
  }
  var $ = function (id) { return typeof document !== "undefined" ? document.getElementById(id) : null; };
  var input = $("deals"), runBtn = $("run"), sampleBtn = $("sample"), csvInput = $("csv"), exportBtn = $("export");
  if (!input || !runBtn) return;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  function run() {
    var deals = parseDeals(input.value);
    if (!deals.length) { input.focus(); return; }
    load().then(function () {
      var tbody = $("rows"), html = [], matched = 0, ripe = 0;
      lastRows = [];
      deals.forEach(function (d) {
        var m = match(d);
        var row = { company: d.company, year: d.year || "", description: d.desc, category: "", verdict: "", since: "" };
        if (m) {
          matched++;
          if (m.cat.verdict === "ripe" || m.cat.verdict === "formed") ripe++;
          row.category = m.cat.name; row.verdict = m.cat.verdict_label; row.since = since(d, m.cat);
          html.push("<tr><td><b>" + esc(d.company) + "</b>" + (d.year ? " (" + d.year + ")" : "") + "<br><span class=\"fine\">" + esc(d.desc) +
            "</span></td><td><a href=\"" + esc(m.cat.url) + "\">" + esc(m.cat.name) + "</a><br><span class=\"fine\">killed by: " + esc(m.cat.constraint) +
            "</span></td><td><span class=\"badge v-" + esc(m.cat.verdict) + "\">" + esc(m.cat.verdict_label) + "</span></td><td>" + esc(row.since) + "</td></tr>");
        } else {
          row.verdict = "I don't know"; row.since = "No category on the board matches this description.";
          html.push("<tr><td><b>" + esc(d.company) + "</b>" + (d.year ? " (" + d.year + ")" : "") + "<br><span class=\"fine\">" + esc(d.desc) +
            "</span></td><td>—</td><td><span class=\"badge v-unknown\">I don't know</span></td><td>No category on the board matches this description, so the screen does not guess.</td></tr>");
        }
        lastRows.push(row);
      });
      tbody.innerHTML = html.join("");
      $("summary").textContent = deals.length + " deal" + (deals.length === 1 ? "" : "s") + " screened: " + matched + " matched a category, " +
        ripe + " in a category that is ripe or has already formed, " + (deals.length - matched) + " with no match (I don't know).";
      $("results").hidden = false;
      $("results").scrollIntoView({ behavior: "smooth", block: "start" });
      if (window.ilTrack) {
        window.ilTrack("relook_run", deals.length + " deals");
        if (matched) window.ilTrack("relook_match", matched + " matched");
      }
    }).catch(function () {
      $("summary").textContent = "Could not load the board data. Check your connection and try again.";
      $("results").hidden = false;
    });
  }

  function exportCSV() {
    if (!lastRows.length) return;
    var cols = ["company", "year", "description", "category", "verdict", "since"];
    var q = function (v) { v = String(v == null ? "" : v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var csv = cols.join(",") + "\n" + lastRows.map(function (r) { return cols.map(function (c) { return q(r[c]); }).join(","); }).join("\n") + "\n";
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "relook.csv";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    if (window.ilTrack) window.ilTrack("relook_export", lastRows.length + " rows");
  }

  runBtn.addEventListener("click", run);
  sampleBtn.addEventListener("click", function () { input.value = SAMPLE; run(); });
  exportBtn.addEventListener("click", exportCSV);
  csvInput.addEventListener("change", function () {
    var f = csvInput.files && csvInput.files[0];
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function () { input.value = String(reader.result); run(); };
    reader.readAsText(f);
  });
})();
