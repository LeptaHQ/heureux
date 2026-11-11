(function () {
  "use strict";

  var selector = "[data-subject-bookmark-form]";
  var toast = document.querySelector("[data-subject-progress-toast]");
  if (!toast || !document.querySelector(selector)) return;

  function matchingForms(key) {
    return document.querySelectorAll(
      selector + '[data-subject-bookmark-key="' + key + '"]'
    );
  }

  function setPending(key, pending) {
    matchingForms(key).forEach(function (form) {
      var button = form.querySelector("button");
      form.dataset.pending = pending ? "true" : "false";
      button.disabled = pending;
      if (pending) {
        button.setAttribute("aria-busy", "true");
      } else {
        button.removeAttribute("aria-busy");
      }
    });
  }

  function showError(message) {
    toast.textContent = message;
    toast.classList.toggle("hidden", !message);
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest(selector);
    if (!form) return;
    event.preventDefault();
    if (form.dataset.pending === "true") return;

    var key = form.dataset.subjectBookmarkKey;
    var focused = document.activeElement;
    var restoreFocus = form.contains(focused);
    var body = new FormData(form);
    var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
    showError("");
    setPending(key, true);

    fetch(form.action, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "X-CSRFToken": csrf.value,
        "X-Requested-With": "fetch"
      }
    }).then(function (response) {
      return response.json().catch(function () {
        throw new Error("La réponse du serveur est inattendue.");
      }).then(function (data) {
        if (!response.ok) {
          throw new Error(
            data && data.error || "Impossible d’enregistrer ce favori."
          );
        }
        if (!data || data.key !== key || typeof data.bookmarked !== "boolean") {
          throw new Error("La réponse du serveur est inattendue.");
        }
        return data;
      });
    }).then(function (data) {
      matchingForms(key).forEach(function (matching) {
        var button = matching.querySelector("button");
        matching.classList.toggle("is-bookmarked", data.bookmarked);
        matching.querySelector("input[name='bookmarked']").value =
          data.bookmarked ? "0" : "1";
        button.setAttribute("aria-pressed", data.bookmarked ? "true" : "false");
        button.title = data.bookmarked ? "Retirer des favoris" : "Ajouter aux favoris";
      });
    }).catch(function (error) {
      showError(error.message || "Impossible d’enregistrer ce favori.");
    }).finally(function () {
      setPending(key, false);
      if (restoreFocus && focused.isConnected &&
          document.activeElement === document.body) {
        focused.focus({ preventScroll: true });
      }
    });
  });
})();
