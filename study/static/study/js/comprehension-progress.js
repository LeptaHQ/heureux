(function () {
  "use strict";

  var forms = document.querySelectorAll(
    "[data-comprehension-completion-form]"
  );
  if (!forms.length) return;

  var toast = document.querySelector(
    "[data-comprehension-progress-toast]"
  );
  var progressStatusClasses = [
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

  function matchingForms(testId) {
    return document.querySelectorAll(
      '[data-comprehension-completion-form][data-comprehension-test-id="' +
        testId +
        '"]'
    );
  }

  function setPending(testId, pending) {
    matchingForms(testId).forEach(function (form) {
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
    if (element.classList.contains("ce-status")) {
      element.classList.remove(
        "ce-status--progress",
        "ce-status--done"
      );
      if (status === "active") {
        element.classList.add("ce-status--progress");
      } else if (status === "done") {
        element.classList.add("ce-status--done");
      }
    } else {
      element.classList.remove.apply(
        element.classList,
        progressStatusClasses
      );
      element.classList.add("progress-status--" + status);
    }
    element.textContent = label;
  }

  function updatePage(data) {
    var testId = String(data.test_id);
    var completed = data.completed;
    matchingForms(testId).forEach(function (form) {
      var input = form.querySelector(
        "[data-comprehension-completed-input]"
      );
      var button = form.querySelector("button");
      form.classList.toggle("is-complete", completed);
      if (input) input.value = completed ? "0" : "1";
      if (!button) return;
      var testLabel = button.dataset.comprehensionLabel || "ce test";
      button.setAttribute("aria-checked", completed ? "true" : "false");
      button.setAttribute(
        "aria-label",
        (completed
          ? "Marquer ce test comme non terminé : "
          : "Marquer ce test comme terminé : ") + testLabel
      );
      button.title = completed
        ? "Test terminé"
        : "Marquer comme terminé";
    });

    document.querySelectorAll(
      '[data-comprehension-progress-status="' + testId + '"]'
    ).forEach(function (status) {
      setStatus(status, data.test.status, data.test.label);
    });
    document.querySelectorAll(
      '[data-comprehension-progress-control="' + testId + '"]'
    ).forEach(function (control) {
      control.classList.toggle("is-complete", completed);
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest(
      "[data-comprehension-completion-form]"
    );
    if (!form) return;
    event.preventDefault();
    if (form.dataset.pending === "true") return;

    var testId = form.dataset.comprehensionTestId;
    var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
    clearError();
    setPending(testId, true);

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
        if (form.dataset.comprehensionCompletionRefresh === "true") {
          window.location.reload();
        }
      })
      .catch(function (error) {
        showError(
          error.message || "Impossible d’enregistrer cette progression."
        );
      })
      .finally(function () {
        setPending(testId, false);
      });
  });
})();
