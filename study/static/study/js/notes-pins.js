(function () {
  "use strict";

  var list = document.querySelector("[data-annotation-list]");
  var dialog = document.getElementById("pinned-note-dialog");
  if (!list || !dialog || typeof dialog.showModal !== "function") return;
  var content = dialog.querySelector("[data-pinned-note-content]");
  var actions = dialog.querySelector("[data-pinned-note-actions]");
  var status = dialog.querySelector("[data-pinned-note-status]");
  var toast = document.querySelector("[data-annotation-toast]");
  var sourceCard = null;
  var actionSources = [];
  var lastAction = null;

  function syncActions() {
    actionSources.forEach(function (source, index) {
      var button = actions.children[index];
      ["class", "aria-pressed", "aria-label", "title", "disabled", "hidden"].forEach(function (name) {
        if (source.hasAttribute(name)) button.setAttribute(name, source.getAttribute(name));
        else button.removeAttribute(name);
      });
      if (button.innerHTML !== source.innerHTML) button.innerHTML = source.innerHTML;
    });
    var focused = document.activeElement;
    if (lastAction !== null && !actions.children[lastAction].disabled &&
        (!dialog.contains(focused) || focused === dialog)) {
      actions.children[lastAction].focus({ preventScroll: true });
    }
  }

  function enhance(records) {
    list.querySelectorAll("[data-pinned-note-open]").forEach(function (button) {
      if (button.hidden) button.hidden = false;
    });
    if (!dialog.open) return;
    if (!sourceCard.isConnected) {
      dialog.close();
      return;
    }
    syncActions();
    if (toast && records.some(function (record) { return toast.contains(record.target); })) {
      status.textContent = toast.classList.contains("hidden") ? "" : toast.textContent;
      status.hidden = !status.textContent;
    }
  }
  list.classList.add("notes-pin-ready");
  enhance();
  var observer = new MutationObserver(enhance);
  var observed = {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ["class", "aria-pressed", "aria-label", "title", "disabled", "hidden"],
  };
  observer.observe(list, observed);
  if (toast) observer.observe(toast, observed);

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
    sourceCard = card;
    actionSources = Array.from(card.querySelectorAll(".annotation-action"));
    actions.replaceChildren.apply(actions, actionSources.map(function (source, index) {
      var button = source.cloneNode(true);
      Array.from(button.attributes).forEach(function (attribute) {
        if (attribute.name.startsWith("data-") || attribute.name === "id") {
          button.removeAttribute(attribute.name);
        }
      });
      button.type = "button";
      button.dataset.pinnedNoteAction = String(index);
      return button;
    }));
    dialog._returnFocus = card.querySelector("[data-pinned-note-open]");
    dialog.showModal();
  });
  actions.addEventListener("click", function (event) {
    var button = event.target.closest("[data-pinned-note-action]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    var source = actionSources[Number(button.dataset.pinnedNoteAction)];
    if (!source || !source.isConnected || source.disabled) return;
    lastAction = Number(button.dataset.pinnedNoteAction);
    if (source.matches("[data-annotation-edit]") ||
        source.closest(".annotation-card__pin, [data-annotation-action='delete']")) {
      dialog.close();
    }
    source.click();
  });
  dialog.addEventListener("close", function () {
    content.replaceChildren();
    actions.replaceChildren();
    status.textContent = "";
    status.hidden = true;
    sourceCard = null;
    actionSources = [];
    lastAction = null;
  });
})();
