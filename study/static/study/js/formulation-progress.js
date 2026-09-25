(function () {
  "use strict";

  var toast = document.querySelector("[data-formulation-progress-toast]");
  var statuses = ["new", "active", "done"];

  function showError(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("hidden", !message);
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

  function setPending(form, pending) {
    var button = form.querySelector("button");
    form.dataset.pending = pending ? "true" : "false";
    if (!button) return;
    button.disabled = pending;
    if (pending) {
      button.setAttribute("aria-busy", "true");
    } else {
      button.removeAttribute("aria-busy");
    }
  }

  function updateButton(form, completed) {
    var input = form.querySelector("[data-formulation-completed-input]");
    var button = form.querySelector("[data-formulation-progress-button]");
    form.classList.toggle("is-complete", completed);
    if (input) input.value = completed ? "0" : "1";
    if (!button) return;
    if (button.getAttribute("role") === "checkbox") {
      button.setAttribute("aria-checked", completed ? "true" : "false");
    }
    button.setAttribute(
      "aria-label",
      button.getAttribute(
        completed
          ? "data-formulation-complete-aria"
          : "data-formulation-incomplete-aria"
      )
    );
    button.title = button.getAttribute(
      completed
        ? "data-formulation-complete-title"
        : "data-formulation-incomplete-title"
    );
    var text = button.getAttribute(
      completed
        ? "data-formulation-complete-text"
        : "data-formulation-incomplete-text"
    );
    if (text !== null) button.textContent = text;
  }

  function setStatus(element, status, text) {
    statuses.forEach(function (value) {
      element.classList.remove("progress-status--" + value);
    });
    element.classList.add("progress-status--" + status);
    element.textContent = text;
  }

  function updateSummary(scope, progress) {
    document.querySelectorAll(
      '[data-formulation-progress-summary="' + scope + '"]'
    ).forEach(function (element) {
      element.textContent = progress.completed + "/" + progress.total;
    });
    document.querySelectorAll(
      '[data-formulation-progress-completed="' + scope + '"]'
    ).forEach(function (element) {
      element.textContent = progress.completed;
    });
    document.querySelectorAll(
      '[data-formulation-progress-word="' + scope + '"]'
    ).forEach(function (element) {
      element.textContent = progress.completed > 1 ? "apprises" : "apprise";
    });
  }

  function updateFormulation(data) {
    var selector = (
      '[data-formulation-progress-form][data-formulation-slug="'
      + data.slug + '"]'
    );
    document.querySelectorAll(selector).forEach(function (form) {
      updateButton(form, data.completed);
    });
    document.querySelectorAll(
      '[data-formulation-row="' + data.slug + '"]'
    ).forEach(function (row) {
      statuses.forEach(function (status) {
        row.classList.remove("is-status-" + status);
      });
      row.classList.add("is-status-" + data.status);
    });
    document.querySelectorAll(
      '[data-formulation-status="' + data.slug + '"]'
    ).forEach(function (status) {
      setStatus(
        status,
        data.status,
        data.label
      );
    });

    updateSummary("overall", data.overall);
    updateSummary("essentials", data.essentials);
    updateSummary(data.category.slug, data.category);
    document.querySelectorAll(
      '[data-formulation-category="' + data.category.slug + '"]'
    ).forEach(function (group) {
      statuses.forEach(function (status) {
        group.classList.remove("is-status-" + status);
      });
      group.classList.add("is-status-" + data.category.status);
      var progress = group.querySelector(".progress-status");
      if (progress) {
        setStatus(
          progress,
          data.category.status,
          data.category.completed + "/" + data.category.total
        );
      }
    });
  }

  function updateLanguage(data) {
    var selector = (
      '[data-formulation-language-progress-form]'
      + '[data-formulation-item-id="' + data.item_id + '"]'
    );
    document.querySelectorAll(selector).forEach(function (form) {
      updateButton(form, data.completed);
    });
    document.querySelectorAll(
      '[data-formulation-language-row="' + data.item_id + '"]'
    ).forEach(function (row) {
      row.classList.toggle("is-status-done", data.completed);
    });
    document.querySelectorAll(
      "[data-formulation-language-completed]"
    ).forEach(function (element) {
      element.textContent = data.progress.completed;
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest(
      "[data-formulation-progress-form],"
      + "[data-formulation-language-progress-form]"
    );
    if (!form) return;
    event.preventDefault();
    if (form.dataset.pending === "true") return;

    var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
    showError("");
    setPending(form, true);
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
        if (form.hasAttribute("data-formulation-language-progress-form")) {
          updateLanguage(data);
        } else {
          updateFormulation(data);
        }
      })
      .catch(function (error) {
        showError(
          error.message || "Impossible d’enregistrer cette progression."
        );
      })
      .finally(function () {
        setPending(form, false);
      });
  });

  document.addEventListener("heureux:formulation-progress", function (event) {
    if (event.detail) updateFormulation(event.detail);
  });
})();
