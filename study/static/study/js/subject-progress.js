(function () {
  "use strict";

  var forms = document.querySelectorAll("[data-subject-completion-form]");
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

  function matchingForms(responseId) {
    return document.querySelectorAll(
      '[data-subject-completion-form][data-subject-response-id="' +
        responseId +
        '"]'
    );
  }

  function setPending(responseId, pending) {
    matchingForms(responseId).forEach(function (form) {
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

  function setStatus(element, status, label) {
    element.classList.remove.apply(element.classList, statusClasses);
    element.classList.add("progress-status--" + status);
    element.textContent = label;
  }

  function updatePage(data) {
    var responseId = String(data.response_id);
    var completed = data.completed;
    matchingForms(responseId).forEach(function (form) {
      var input = form.querySelector("[data-subject-completed-input]");
      var button = form.querySelector("button");
      form.classList.toggle("is-complete", completed);
      if (input) input.value = completed ? "0" : "1";
      if (!button) return;
      var subjectLabel = button.dataset.subjectLabel || "ce sujet";
      button.setAttribute("aria-checked", completed ? "true" : "false");
      button.setAttribute(
        "aria-label",
        (completed
          ? "Marquer ce sujet comme non terminé : "
          : "Marquer ce sujet comme terminé : ") + subjectLabel
      );
      button.title = completed
        ? "Sujet terminé"
        : "Marquer comme terminé";
    });

    document.querySelectorAll(
      '[data-subject-progress-status="' + responseId + '"]'
    ).forEach(function (status) {
      setStatus(status, data.subject.status, data.subject.label);
    });
    document.querySelectorAll(
      '[data-subject-progress-control="' + responseId + '"]'
    ).forEach(function (control) {
      control.classList.toggle("is-complete", completed);
    });
    document.querySelectorAll(
      '[data-subject-progress-row="' + responseId + '"]'
    ).forEach(function (row) {
      ["new", "active", "done"].forEach(function (status) {
        row.classList.remove("subject-progress-row--" + status);
        row.classList.remove("tache-two-subject-card--" + status);
      });
      row.classList.add("subject-progress-row--" + data.subject.status);
      if (row.classList.contains("tache-two-subject-card")) {
        row.classList.add(
          "tache-two-subject-card--" + data.subject.status
        );
      }
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-subject-completion-form]");
    if (!form) return;
    event.preventDefault();
    if (form.dataset.pending === "true") return;

    var responseId = form.dataset.subjectResponseId;
    var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
    clearError();
    setPending(responseId, true);

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
        if (form.dataset.subjectCompletionRefresh === "true") {
          window.location.reload();
        }
      })
      .catch(function (error) {
        showError(
          error.message || "Impossible d’enregistrer cette progression."
        );
      })
      .finally(function () {
        setPending(responseId, false);
      });
  });
})();
