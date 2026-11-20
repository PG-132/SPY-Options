// The page's windows (docs/changes/2026-11-13-ui.md, AC-30): drag one by its
// title bar to move it; a click anywhere on one brings it to the front.
// Resizing is the browser's own (CSS `resize` on .win), and each chart
// follows its window through Dash's responsive graph.
//
// Layout only. Nothing here reads, computes or changes a figure: it moves
// boxes. Dash serves every file in screener/assets/ with the page, so this
// needs no wiring. Where windows are moved to is not kept from one launch
// to the next, like everything else on the page.
(function () {
  var front = 10;
  var drag = null;

  document.addEventListener("pointerdown", function (e) {
    var win = e.target.closest ? e.target.closest(".win") : null;
    if (!win) return;
    win.style.zIndex = String(++front);
    var bar = e.target.closest(".win-bar");
    if (!bar || e.button !== 0) return;
    var box = win.getBoundingClientRect();
    var area = win.offsetParent.getBoundingClientRect();
    drag = { win: win, dx: e.clientX - box.left, dy: e.clientY - box.top, area: area };
    bar.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  document.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var area = drag.win.offsetParent.getBoundingClientRect();
    drag.win.style.left = Math.max(0, e.clientX - area.left - drag.dx) + "px";
    drag.win.style.top = Math.max(0, e.clientY - area.top - drag.dy) + "px";
  });

  document.addEventListener("pointerup", function () { drag = null; });
  document.addEventListener("pointercancel", function () { drag = null; });
})();
