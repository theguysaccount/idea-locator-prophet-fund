// Share, copy and privacy-respecting event counting. No cookies, no third-party scripts unless
// the site owner sets a GoatCounter endpoint (meta il-goatcounter); Do Not Track and GPC switch it off.
(function () {
  "use strict";
  var queue = (window.__ilEvents = window.__ilEvents || []);
  var meta = document.querySelector('meta[name="il-goatcounter"]');
  var endpoint = meta && meta.content;
  var optedOut = navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl === true;

  function count(path, title, isEvent) {
    if (!endpoint || optedOut) return;
    try {
      var q = "?p=" + encodeURIComponent(path) + "&t=" + encodeURIComponent(title || "") +
        (isEvent ? "&e=true" : "") + "&r=" + encodeURIComponent(document.referrer || "") + "&rnd=" + Math.random();
      var img = new Image();
      img.src = endpoint + q;
    } catch (e) { /* counting must never break the page */ }
  }

  window.ilTrack = function (name, detail) {
    queue.push({ name: name, detail: detail || null, at: new Date().toISOString() });
    count(name, detail ? String(detail) : name, true);
  };

  count(location.pathname, document.title, false);

  function copy(text, btn) {
    var done = function () {
      if (!btn) return;
      var old = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = old; }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); });
    } else { fallback(text); done(); }
  }
  function fallback(text) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "absolute"; ta.style.left = "-9999px";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
  }

  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-share],[data-copy]") : null;
    if (!el) return;
    var row = el.closest(".share-row");
    var slug = row ? row.getAttribute("data-slug") : "";
    if (el.hasAttribute("data-copy")) {
      copy(el.getAttribute("data-copy"), el);
      window.ilTrack("share", "copy:" + slug);
      return;
    }
    var kind = el.getAttribute("data-share");
    if (kind === "native") {
      var url = row.getAttribute("data-share-url"), text = row.getAttribute("data-share-text");
      if (navigator.share) {
        navigator.share({ title: text, text: text, url: url }).catch(function () {});
      } else {
        copy(url, el);
      }
    }
    window.ilTrack("share", kind + ":" + slug);
  });

  document.addEventListener("focusin", function (ev) {
    if (ev.target.matches && ev.target.matches("textarea.code[readonly]")) {
      ev.target.select();
      window.ilTrack("embed_or_cite_focus", ev.target.id);
    }
  });
})();
