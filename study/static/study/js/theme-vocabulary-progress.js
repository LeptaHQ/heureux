(function () {
  "use strict";

  var root = document.querySelector("[data-theme-vocabulary-progress]");
  if (!root) return;

  var errorMessage = root.querySelector(
    "[data-theme-vocabulary-progress-error]"
  );
  var learnedCount = document.querySelector(
    "[data-theme-vocabulary-learned-count]"
  );
  var mutationQueue = Promise.resolve();

  function showError(message) {
    if (!errorMessage) return;
    errorMessage.textContent = message;
    errorMessage.classList.remove("hidden");
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

  function updatePhrase(form, completed) {
    var phrase = form.closest("[data-theme-vocabulary-phrase]");
    var input = form.querySelector(
      "[data-theme-vocabulary-completed-input]"
    );
    var button = form.querySelector("button");
    if (phrase) phrase.classList.toggle("is-learned", completed);
    if (input) input.value = completed ? "0" : "1";
    if (!button) return;

    var phraseText = button.dataset.phraseText || "cette fiche";
    button.setAttribute("aria-checked", completed ? "true" : "false");
    button.setAttribute(
      "aria-label",
      completed
        ? "Marquer comme non apprise : " + phraseText
        : "Marquer comme apprise : " + phraseText
    );
    button.title = completed ? "Fiche apprise" : "Marquer comme apprise";
  }

  root.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-theme-vocabulary-progress-form]");
    if (!form) return;
    event.preventDefault();

    var button = form.querySelector("button");
    if (!button || form.dataset.pending === "true") return;
    form.dataset.pending = "true";
    button.disabled = true;
    var body = new FormData(form);
    var csrf = form.querySelector(
      "input[name='csrfmiddlewaretoken']"
    ).value;

    mutationQueue = mutationQueue.then(function () {
      clearError();
      return fetch(form.action, {
        method: "POST",
        body: body,
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": csrf,
          "X-Requested-With": "fetch"
        }
      });
    })
      .then(readJson)
      .then(function (data) {
        updatePhrase(form, data.completed);
        if (learnedCount) learnedCount.textContent = String(data.learned);
      })
      .catch(function (error) {
        showError(
          error.message || "Impossible d’enregistrer cette progression."
        );
      })
      .finally(function () {
        delete form.dataset.pending;
        button.disabled = false;
      });
  });
})();
