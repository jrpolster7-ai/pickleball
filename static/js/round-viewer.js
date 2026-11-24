// Round viewer (CLAUDE.md section 10): click a tab or an arrow, press ← →, or swipe.
// Without this script the tabs and arrows still work as plain links.
(function () {
  "use strict";

  function setup(root) {
    var tabs = Array.prototype.slice.call(root.querySelectorAll("[data-tab]"));
    var panels = Array.prototype.slice.call(root.querySelectorAll("[data-panel]"));
    var prev = root.querySelector("[data-prev]");
    var next = root.querySelector("[data-next]");
    if (!tabs.length) return;

    var on = ["border-court", "bg-court", "text-white"];
    var off = ["border-line", "bg-white", "text-court", "hover:border-court"];
    var current = Number((tabs.find(function (t) { return t.getAttribute("aria-selected") === "true"; }) || tabs[0]).dataset.tab);

    function show(index, focusTab) {
      index = Math.max(1, Math.min(tabs.length, index));
      current = index;
      tabs.forEach(function (tab) {
        var active = Number(tab.dataset.tab) === index;
        tab.setAttribute("aria-selected", active ? "true" : "false");
        tab.tabIndex = active ? 0 : -1;
        on.forEach(function (c) { tab.classList.toggle(c, active); });
        off.forEach(function (c) { tab.classList.toggle(c, !active); });
        if (active) {
          tab.scrollIntoView({ block: "nearest", inline: "center" });
          if (focusTab) tab.focus();
        }
      });
      panels.forEach(function (panel) { panel.hidden = Number(panel.dataset.panel) !== index; });
      prev.setAttribute("aria-disabled", index === 1 ? "true" : "false");
      next.setAttribute("aria-disabled", index === tabs.length ? "true" : "false");
      var url = new URL(window.location.href);
      url.searchParams.set("round", index);
      history.replaceState(null, "", url);
    }

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function (e) { e.preventDefault(); show(Number(tab.dataset.tab)); });
    });
    prev.addEventListener("click", function (e) { e.preventDefault(); show(current - 1); });
    next.addEventListener("click", function (e) { e.preventDefault(); show(current + 1); });

    // Left and right arrow keys, unless someone is typing in a box.
    document.addEventListener("keydown", function (e) {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      var tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); show(current - 1, root.contains(document.activeElement)); }
      if (e.key === "ArrowRight") { e.preventDefault(); show(current + 1, root.contains(document.activeElement)); }
    });

    // Swiping sideways on a touch screen. An extra, never the only way.
    var startX = null, startY = null;
    panels.forEach(function (panel) {
      panel.addEventListener("touchstart", function (e) {
        startX = e.touches[0].clientX; startY = e.touches[0].clientY;
      }, { passive: true });
      panel.addEventListener("touchend", function (e) {
        if (startX === null) return;
        var dx = e.changedTouches[0].clientX - startX;
        var dy = e.changedTouches[0].clientY - startY;
        startX = null;
        if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) show(current + (dx < 0 ? 1 : -1));
      }, { passive: true });
    });

    show(current);
  }

  document.querySelectorAll("[data-round-viewer]").forEach(setup);
})();
