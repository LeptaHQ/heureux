(function () {
  "use strict";

  var root = document.querySelector("[data-question-bank]");
  if (!root) return;

  var errorMessage = document.querySelector("[data-memory-progress-error]");
  var statusClasses = [
    "progress-status--new",
    "progress-status--active",
    "progress-status--done"
  ];
  var mutationQueue = Promise.resolve();

  function setStatus(element, status, label) {
    if (!element) return;
    element.classList.remove.apply(element.classList, statusClasses);
    element.classList.add("progress-status--" + status);
    element.textContent = label;
  }

  function setProgress(bar, percent, status) {
    if (!bar) return;
    var fill = bar.querySelector("span");
    if (fill) {
      fill.classList.remove(
        "memory-progress-fill--new",
        "memory-progress-fill--active",
        "memory-progress-fill--done"
      );
      fill.classList.add("memory-progress-fill--" + status);
      fill.style.width = percent + "%";
    }
    bar.setAttribute("aria-label", percent + " % terminé");
  }

  function showError(message) {
    if (!errorMessage) return;
    errorMessage.textContent = message;
    errorMessage.classList.remove("hidden");
    errorMessage.scrollIntoView({
      behavior: "smooth",
      block: "nearest"
    });
  }

  function clearError() {
    if (!errorMessage) return;
    errorMessage.textContent = "";
    errorMessage.classList.add("hidden");
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

  function updateQuestion(form, completed) {
    var row = form.closest("[data-question-bank-question]");
    var button = form.querySelector("button");
    var completedInput = form.querySelector("[data-memory-completed-input]");
    if (row) row.classList.toggle("is-complete", completed);
    if (completedInput) completedInput.value = completed ? "0" : "1";
    if (!button) return;
    var questionText = button.dataset.questionText || "cette question";
    button.setAttribute("aria-checked", completed ? "true" : "false");
    button.setAttribute(
      "aria-label",
      completed
        ? "Marquer comme non apprise : " + questionText
        : "Marquer comme apprise : " + questionText
    );
    button.title = completed
      ? "Question apprise"
      : "Marquer comme apprise";
  }

  function updateMemory(progress) {
    var summary = document.querySelector("[data-memory-progress-summary]");
    if (summary) {
      summary.classList.remove(
        "memory-learning-summary--new",
        "memory-learning-summary--active",
        "memory-learning-summary--done"
      );
      summary.classList.add(
        "memory-learning-summary--" + progress.status
      );
    }
    document.querySelectorAll("[data-memory-completed]").forEach(
      function (element) {
        element.textContent = progress.completed;
      }
    );
    setStatus(
      document.querySelector("[data-memory-status]"),
      progress.status,
      progress.label
    );
    setProgress(
      document.querySelector("[data-memory-progress-bar]"),
      progress.percent,
      progress.status
    );
  }

  function updateSection(progress) {
    var section = document.querySelector(
      '[data-memory-section="' + progress.number + '"]'
    );
    if (section) {
      var count = section.querySelector("[data-section-completed]");
      if (count) count.textContent = progress.completed;
      setStatus(
        section.querySelector("[data-section-status]"),
        progress.status,
        progress.label
      );
      setProgress(
        section.querySelector("[data-section-progress-bar]"),
        progress.percent,
        progress.status
      );
    }
    var indexEntry = document.querySelector(
      '[data-index-section="' + progress.number + '"]'
    );
    if (indexEntry) {
      var indexCount = indexEntry.querySelector("[data-index-completed]");
      if (indexCount) indexCount.textContent = progress.completed;
    }
  }

  var responseDialog = document.querySelector(
    "[data-question-response-dialog]"
  );
  var responseForm = responseDialog
    ? responseDialog.querySelector("[data-question-response-form]")
    : null;
  var responseKey = responseForm
    ? responseForm.querySelector("[data-question-response-key]")
    : null;
  var responseBody = responseForm
    ? responseForm.querySelector("[data-question-response-body]")
    : null;
  var responseQuestion = responseDialog
    ? responseDialog.querySelector("[data-question-response-question]")
    : null;
  var responseError = responseDialog
    ? responseDialog.querySelector("[data-question-response-error]")
    : null;
  var responseDelete = responseForm
    ? responseForm.querySelector("[data-question-response-delete]")
    : null;
  var responseButtons = responseForm
    ? Array.from(responseForm.querySelectorAll("[type='submit']"))
    : [];
  var responseEditButtons = Array.from(
    root.querySelectorAll("[data-question-response-edit]")
  );
  var activeResponseRow = null;
  var responseDialogSession = 0;

  function setResponseError(message) {
    if (!responseError) return;
    responseError.textContent = message || "";
    responseError.hidden = !message;
  }

  function openResponseDialog(button) {
    if (
      (responseForm && responseForm.dataset.pending === "true")
      || !responseDialog
      || !responseForm
      || !responseKey
      || !responseBody
      || !responseQuestion
    ) return;
    var row = button.closest("[data-question-bank-question]");
    if (!row) return;
    var source = row.querySelector("[data-question-response-source]");
    responseDialogSession += 1;
    activeResponseRow = row;
    responseKey.value = row.dataset.questionKey || "";
    responseBody.value = source ? source.value : "";
    responseQuestion.textContent = button.dataset.questionText || "";
    if (responseDelete) {
      responseDelete.classList.toggle(
        "hidden",
        !responseBody.value.trim()
      );
    }
    setResponseError("");
    responseDialog._returnFocus = button;
    if (typeof responseDialog.showModal === "function") {
      responseDialog.showModal();
    } else {
      responseDialog.setAttribute("open", "");
    }
    window.requestAnimationFrame(function () {
      responseBody.focus();
      responseBody.setSelectionRange(
        responseBody.value.length,
        responseBody.value.length
      );
    });
  }

  function updateResponseRow(row, data) {
    if (!row) return;
    var source = row.querySelector("[data-question-response-source]");
    var preview = row.querySelector("[data-question-response-preview]");
    var display = row.querySelector("[data-question-response-display]");
    var edit = row.querySelector("[data-question-response-edit]");
    if (source) source.value = data.body;
    if (display) display.textContent = data.body;
    if (preview) preview.classList.toggle("hidden", !data.has_response);
    row.classList.toggle("has-response", data.has_response);
    if (edit) {
      var questionText = edit.dataset.questionText || "cette question";
      edit.classList.toggle("has-response", data.has_response);
      edit.setAttribute(
        "aria-label",
        (data.has_response ? "Modifier" : "Ajouter")
          + " ma réponse : "
          + questionText
      );
      edit.title = data.has_response
        ? "Modifier ma réponse"
        : "Ajouter ma réponse";
    }
  }

  root.addEventListener("click", function (event) {
    var button = event.target.closest
      ? event.target.closest("[data-question-response-edit]")
      : null;
    if (button) openResponseDialog(button);
  });

  if (responseForm) {
    responseForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (responseForm.dataset.pending === "true") return;
      var action = event.submitter
        ? event.submitter.value
        : "save";
      if (action === "save" && !responseBody.value.trim()) {
        setResponseError("Votre réponse ne peut pas être vide.");
        responseBody.focus({ preventScroll: true });
        return;
      }
      if (
        action === "delete"
        && !window.confirm("Supprimer votre réponse à cette question ?")
      ) return;

      setResponseError("");
      responseForm.dataset.pending = "true";
      var submittedRow = activeResponseRow;
      var submittedSession = responseDialogSession;
      responseButtons.forEach(function (button) {
        button.disabled = true;
      });
      responseEditButtons.forEach(function (button) {
        button.disabled = true;
      });
      var formData = new FormData(responseForm);
      formData.set("action", action);
      fetch(responseForm.getAttribute("action"), {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": responseForm.querySelector(
            "input[name='csrfmiddlewaretoken']"
          ).value,
          "X-Requested-With": "fetch"
        }
      })
        .then(readJson)
        .then(function (data) {
        updateResponseRow(submittedRow, data);
        if (
          responseDialog.open
          && responseDialogSession === submittedSession
        ) {
          if (typeof responseDialog.close === "function") {
            responseDialog.close();
          } else {
            responseDialog.removeAttribute("open");
          }
        }
      })
      .catch(function (error) {
        var message =
          error.message || "Impossible d’enregistrer votre réponse.";
        if (
          responseDialog.open
          && responseDialogSession === submittedSession
        ) {
          setResponseError(message);
        } else {
          showError(message);
        }
        })
        .finally(function () {
          delete responseForm.dataset.pending;
          responseButtons.forEach(function (button) {
            button.disabled = false;
          });
          responseEditButtons.forEach(function (button) {
            button.disabled = false;
          });
        });
    });
  }

  root.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-memory-progress-form]");
    if (!form) return;
    event.preventDefault();

    var button = form.querySelector("button");
    if (!button || form.dataset.pending === "true") return;
    clearError();
    form.dataset.pending = "true";
    button.setAttribute("aria-busy", "true");
    button.setAttribute("aria-disabled", "true");
    var formData = new FormData(form);

    mutationQueue = mutationQueue.then(function () {
      return fetch(form.action, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": form.querySelector(
            "input[name='csrfmiddlewaretoken']"
          ).value,
          "X-Requested-With": "fetch"
        }
      })
        .then(readJson)
        .then(function (data) {
          updateQuestion(form, data.completed);
          updateMemory(data.memory);
          updateSection(data.section);
        })
        .catch(function (error) {
          showError(
            error.message || "Impossible d’enregistrer cette progression."
          );
        })
        .finally(function () {
          delete form.dataset.pending;
          button.removeAttribute("aria-busy");
          button.removeAttribute("aria-disabled");
        });
    });
  });
})();
