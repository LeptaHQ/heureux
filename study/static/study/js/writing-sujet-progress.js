(function () {
  "use strict";

  var forms = document.querySelectorAll(
    "[data-writing-sujet-completion-form]"
  );
  if (!forms.length) return;

  var toast = document.querySelector("[data-subject-progress-toast]");
  var statusClasses = [
    "progress-status--new",
    "progress-status--active",
    "progress-status--done"
  ];

  function showError(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.remove("hidden");
  }

  function clearError() {
    if (!toast) return;
    toast.textContent = "";
    toast.classList.add("hidden");
  }

  function readJson(response) {
    return response.json().catch(function () {
      throw new Error("La réponse du serveur est inattendue.");
    }).then(function (data) {
      if (!response.ok) {
        throw new Error(
          data.error || "Impossible d’enregistrer cette progression."
        );
      }
      return data;
    });
  }

  function matchingForms(sujetId) {
    return document.querySelectorAll(
      '[data-writing-sujet-completion-form][data-writing-sujet-id="' +
        sujetId +
        '"]'
    );
  }

  function setPending(sujetId, pending) {
    matchingForms(sujetId).forEach(function (form) {
      var button = form.querySelector("button");
      form.dataset.pending = pending ? "true" : "false";
      if (!button) return;
      button.disabled = pending;
      if (pending) {
        button.setAttribute("aria-busy", "true");
      } else {
        button.removeAttribute("aria-busy");
      }
    });
  }

  function updatePage(data) {
    var sujetId = String(data.sujet_id);
    var completed = data.completed;
    matchingForms(sujetId).forEach(function (form) {
      var input = form.querySelector(
        "[data-writing-sujet-completed-input]"
      );
      var button = form.querySelector("button");
      form.classList.toggle("is-complete", completed);
      if (input) input.value = completed ? "0" : "1";
      if (!button) return;
      var label = button.dataset.writingSujetLabel || "ce sujet";
      button.setAttribute("aria-checked", completed ? "true" : "false");
      button.setAttribute(
        "aria-label",
        (completed
          ? "Marquer ce sujet comme non terminé : "
          : "Marquer ce sujet comme terminé : ") + label
      );
      button.title = completed
        ? "Sujet terminé"
        : "Marquer comme terminé";
    });

    document.querySelectorAll(
      '[data-writing-sujet-progress-status="' + sujetId + '"]'
    ).forEach(function (status) {
      status.classList.remove.apply(status.classList, statusClasses);
      status.classList.add("progress-status--" + data.sujet.status);
      status.textContent = data.sujet.label;
    });
    document.querySelectorAll(
      '[data-writing-sujet-progress-control="' + sujetId + '"]'
    ).forEach(function (control) {
      control.classList.toggle("is-complete", completed);
    });
    document.querySelectorAll(
      '[data-writing-sujet-progress-row="' + sujetId + '"]'
    ).forEach(function (row) {
      ["new", "active", "done"].forEach(function (status) {
        row.classList.remove("writing-sujet-progress-row--" + status);
      });
      row.classList.add(
        "writing-sujet-progress-row--" + data.sujet.status
      );
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest(
      "[data-writing-sujet-completion-form]"
    );
    if (!form) return;
    event.preventDefault();
    if (form.dataset.pending === "true") return;

    var sujetId = form.dataset.writingSujetId;
    var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
    clearError();
    setPending(sujetId, true);

    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "X-CSRFToken": csrf.value,
        "X-Requested-With": "fetch"
      }
    })
      .then(readJson)
      .then(function (data) {
        updatePage(data);
        if (form.dataset.writingSujetCompletionRefresh === "true") {
          window.location.reload();
        }
      })
      .catch(function (error) {
        showError(
          error.message || "Impossible d’enregistrer cette progression."
        );
      })
      .finally(function () {
        setPending(sujetId, false);
      });
  });
})();
