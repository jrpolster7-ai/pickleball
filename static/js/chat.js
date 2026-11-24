// Event chat (CLAUDE.md section 11). HTMX does the polling and posting.
// This script only keeps the list scrolled to the newest message and adds Enter to send.
(function () {
  "use strict";

  var stickToBottom = true;
  var refocus = false;

  function scroller() { return document.getElementById("chat-scroll"); }

  function nearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function toBottom() {
    var el = scroller();
    if (el) el.scrollTop = el.scrollHeight;
  }

  document.addEventListener("DOMContentLoaded", toBottom);

  document.addEventListener("htmx:beforeSwap", function (evt) {
    var el = scroller();
    var sentByMe = evt.detail.elt && evt.detail.elt.matches && evt.detail.elt.matches("[data-chat-form]");
    refocus = !!sentByMe;
    stickToBottom = sentByMe || (el ? nearBottom(el) : true);
  });

  document.addEventListener("htmx:afterSettle", function () {
    if (stickToBottom) toBottom();
    if (refocus) {
      refocus = false;
      var box = document.getElementById("chat-body");
      if (box) box.focus();
    }
  });

  // Enter sends. Shift + Enter makes a new line.
  document.addEventListener("keydown", function (evt) {
    var t = evt.target;
    if (evt.key !== "Enter" || evt.shiftKey || evt.isComposing || !t || t.id !== "chat-body") return;
    evt.preventDefault();
    if (t.value.trim() && t.form) t.form.requestSubmit();
  });
})();
