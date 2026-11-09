(function () {
  "use strict";

  var list = document.querySelector("[data-annotation-list]");
  var dialog = document.getElementById("pinned-note-dialog");
  if (!list || !dialog || typeof dialog.showModal !== "function") return;
  var content = dialog.querySelector("[data-pinned-note-content]");

  function enhance() {
    list.querySelectorAll("[data-pinned-note-open]").forEach(function (button) {
      button.hidden = false;
    });
  }
  list.classList.add("notes-pin-ready");
  enhance();
  new MutationObserver(enhance).observe(list, { childList: true, subtree: true });

  list.addEventListener("click", function (event) {
    var card = event.target.closest(".annotation-card--pinned");
    if (!card || dialog.open) return;
    var trigger = event.target.closest("[data-pinned-note-open]");
    if (!trigger && event.target.closest("a, button, input, textarea, select, form")) return;
    if (!trigger && window.getSelection().toString().trim()) return;

    var body = card.querySelector(".annotation-card__content").cloneNode(true);
    body.querySelectorAll("[data-recall-cell], [data-recall-content]").forEach(function (node) {
      node.removeAttribute("data-recall-cell");
      node.removeAttribute("data-recall-content");
      node.removeAttribute("data-recall-entry");
      node.classList.remove("recall-content");
    });
    content.replaceChildren(body);
    var context = card.querySelector(".annotation-card__context");
    if (context) content.appendChild(context.cloneNode(true));
    dialog._returnFocus = card.querySelector("[data-pinned-note-open]");
    dialog.showModal();
  });
  dialog.addEventListener("close", function () {
    content.replaceChildren();
  });
})();
