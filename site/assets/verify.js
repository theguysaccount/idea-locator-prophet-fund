// Recompute every ledger hash in the browser. Must match il/ledger.py byte for byte:
// canonical JSON = sorted keys, no whitespace, non-ASCII (and DEL) escaped as \uXXXX.
(function () {
  "use strict";

  function canon(v) {
    if (v === null || typeof v !== "object") return JSON.stringify(v);
    if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
    return "{" + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ":" + canon(v[k]); }).join(",") + "}";
  }
  function ascii(s) {
    return s.replace(/[\u007f-\uffff]/g, function (c) { return "\\u" + ("0000" + c.charCodeAt(0).toString(16)).slice(-4); });
  }
  function hex(buf) {
    return Array.prototype.map.call(new Uint8Array(buf), function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }
  async function sha256(text) {
    var bytes = new TextEncoder().encode(text);
    return hex(await crypto.subtle.digest("SHA-256", bytes));
  }
  function payload(e) {
    return ascii(canon({ seq: e.seq, type: e.type, ts: e.ts, body: e.body, prev: e.prev }));
  }
  if (typeof window !== "undefined") window.ilLedger = { canon: canon, ascii: ascii, payload: payload };

  var btn = typeof document !== "undefined" && document.getElementById("verify-btn");
  var out = typeof document !== "undefined" && document.getElementById("verify-out");
  if (!btn || !out) return;

  btn.addEventListener("click", async function () {
    out.className = "verify-out";
    if (!window.crypto || !crypto.subtle) {
      out.textContent = "This browser cannot compute SHA-256 here (it needs HTTPS).";
      return;
    }
    out.textContent = "Fetching and checking…";
    try {
      var res = await fetch(btn.getAttribute("data-chain"), { cache: "no-store" });
      var lines = (await res.text()).split("\n").filter(function (l) { return l.trim(); });
      var prev = "0".repeat(64);
      for (var i = 0; i < lines.length; i++) {
        var e = JSON.parse(lines[i]);
        if (e.seq !== i) throw new Error("entry " + i + ": sequence number is " + e.seq);
        if (e.prev !== prev) throw new Error("entry " + i + ": does not point at the hash of entry " + (i - 1));
        var h = await sha256(payload(e));
        if (h !== e.hash) throw new Error("entry " + i + ": hash mismatch, the entry was edited");
        prev = h;
      }
      out.className = "verify-out ok";
      out.textContent = "✓ All " + lines.length + " entries verify. Head " + prev.slice(0, 16) + "…";
      if (window.ilTrack) window.ilTrack("ledger_verify", "ok");
    } catch (err) {
      out.className = "verify-out bad";
      out.textContent = "✗ " + err.message;
      if (window.ilTrack) window.ilTrack("ledger_verify", "fail");
    }
  });
})();
