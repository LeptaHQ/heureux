(function () {
  "use strict";

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

  function submitForm(form, fallback) {
    var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
    return fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "X-CSRFToken": csrf ? csrf.value : "",
        "X-Requested-With": "fetch"
      }
    }).then(function (response) {
      return response.json().catch(function () {
        throw new Error("La réponse du serveur est inattendue.");
      }).then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || fallback);
        }
        return data;
      });
    });
  }

  function initCompletionForms() {
    var completionError = "Impossible d’enregistrer cette progression.";

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
      clearError();
      setPending(testId, true);

      submitForm(form, completionError)
        .then(function (data) {
          updatePage(data);
          if (form.dataset.comprehensionCompletionRefresh === "true") {
            window.location.reload();
          }
        })
        .catch(function (error) {
          showError(error.message || completionError);
        })
        .finally(function () {
          setPending(testId, false);
        });
    });
  }

  function initQuestionStudyForms() {
    var studyError = "Impossible d’enregistrer cette question à étudier.";
    var addLabel = "Ajouter à étudier";
    var removeLabel = "Retirer de l’étude";

    function matchingForms(questionId) {
      return document.querySelectorAll(
        '[data-question-study-form][data-question-study-question="' +
          questionId +
          '"]'
      );
    }

    function setPending(questionId, pending) {
      matchingForms(questionId).forEach(function (form) {
        var button = form.querySelector("[data-question-study-button]");
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

    function setCount(selector, value) {
      if (typeof value !== "number") return;
      document.querySelectorAll(selector).forEach(function (element) {
        element.textContent = String(value);
      });
    }

    function updatePage(data) {
      var questionId = String(data.question_id);
      var marked = Boolean(data.is_to_study);
      var label = marked ? removeLabel : addLabel;

      matchingForms(questionId).forEach(function (form) {
        var input = form.querySelector("[data-question-study-input]");
        var button = form.querySelector("[data-question-study-button]");
        form.classList.toggle("is-marked", marked);
        if (input) input.value = marked ? "0" : "1";
        if (!button) return;
        var number =
          button.dataset.questionStudyNumber || data.question_number;
        var fullLabel = label + " : question " + number;
        button.setAttribute("aria-pressed", marked ? "true" : "false");
        button.setAttribute("aria-label", fullLabel);
        button.title = label;
        var text = button.querySelector("[data-question-study-text]");
        if (text) text.textContent = label;
        var srLabel = button.querySelector("[data-question-study-label]");
        if (srLabel) srLabel.textContent = fullLabel;
      });

      document.querySelectorAll(
        '[data-question-study-row="' + questionId + '"]'
      ).forEach(function (row) {
        row.classList.toggle("is-to-study", marked);
      });
      document.querySelectorAll(
        '[data-question-study-map="' + questionId + '"]'
      ).forEach(function (item) {
        item.classList.toggle("is-to-study", marked);
        var baseLabel = item.dataset.questionStudyBaseLabel;
        if (baseLabel) {
          item.setAttribute(
            "aria-label",
            baseLabel + (marked ? ", à étudier" : "")
          );
        }
      });

      setCount(
        '[data-question-study-mode-count="' + data.mode + '"]',
        data.mode_marked_count
      );
      setCount(
        '[data-question-study-test-count="' + data.test_slug + '"]',
        data.test_marked_count
      );
    }

    document.addEventListener("submit", function (event) {
      var form = event.target.closest("[data-question-study-form]");
      if (!form) return;
      event.preventDefault();
      if (form.dataset.pending === "true") return;

      var questionId = form.dataset.questionStudyQuestion;
      clearError();
      setPending(questionId, true);

      submitForm(form, studyError)
        .then(function (data) {
          updatePage(data);
          if (
            !data.is_to_study
            && form.dataset.questionStudyRefresh === "true"
          ) {
            window.location.reload();
          }
        })
        .catch(function (error) {
          showError(error.message || studyError);
        })
        .finally(function () {
          setPending(questionId, false);
        });
    });
  }

  initCompletionForms();
  initQuestionStudyForms();
})();
