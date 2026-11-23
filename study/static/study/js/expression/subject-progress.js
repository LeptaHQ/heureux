(function () {
  "use strict";

  var toast = document.querySelector("[data-subject-progress-toast]");
  var directory = window.HeureuxSubjectDirectory;
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

  function setupCompletion(config) {
    var prefix = "data-" + config.prefix;
    var formSelector = "[" + prefix + "-completion-form]";
    if (!document.querySelector(formSelector)) return;

    function matchingForms(id) {
      return document.querySelectorAll(
        formSelector + "[" + config.idAttribute + '="' + id + '"]'
      );
    }

    function matchingProgress(kind, id) {
      return document.querySelectorAll(
        "[" + prefix + "-progress-" + kind + '="' + id + '"]'
      );
    }

    function setPending(id, pending) {
      matchingForms(id).forEach(function (form) {
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

    function updateChecks(id, completed) {
      matchingForms(id).forEach(function (form) {
        if (form.hasAttribute(prefix + "-reset-form")) return;
        var input = form.querySelector("[" + prefix + "-completed-input]");
        var button = form.querySelector("button");
        form.classList.toggle("is-complete", completed);
        if (input) input.value = completed ? "0" : "1";
        if (!button) return;
        var label = button.getAttribute(prefix + "-label") || "ce sujet";
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
    }
    function updatePage(data, sourceRow, focus) {
      var id = String(data[config.idField]);
      var progress = data[config.progressField];
      var rows = Array.from(matchingProgress("row", id));
      // An overlapping bookmark save can already have removed this row from Favorites.
      if (!rows.length && sourceRow) rows.push(sourceRow);
      var old = rows.length ? directory.statusOf(rows[0]) : null;
      updateChecks(id, data.completed);
      matchingProgress("status", id).forEach(function (element) {
        statuses.forEach(function (status) {
          element.classList.remove("progress-status--" + status);
        });
        element.classList.add("progress-status--" + progress.status);
        element.textContent = progress.label;
      });
      matchingProgress("control", id).forEach(function (control) {
        control.classList.toggle("is-complete", data.completed);
      });
      directory.progress(rows, old, progress.status, focus);
      matchingProgress("row", id).forEach(function (row) {
        var rowClass = config.prefix + "-progress-row";
        statuses.forEach(function (status) {
          row.classList.remove(rowClass + "--" + status);
          row.classList.remove("is-status-" + status);
          if (config.extraRowClass) {
            row.classList.remove(config.extraRowClass + "--" + status);
          }
        });
        row.classList.add(rowClass + "--" + progress.status);
        row.classList.add("is-status-" + progress.status);
        if (config.extraRowClass && row.classList.contains(config.extraRowClass)) {
          row.classList.add(config.extraRowClass + "--" + progress.status);
        }
      });
    }

    if (config.eventName) {
      document.addEventListener(config.eventName, function (event) {
        if (event.detail) updatePage(event.detail);
      });
    }

    document.addEventListener("submit", function (event) {
      var form = event.target.closest(formSelector);
      if (!form) return;
      event.preventDefault();
      if (form.dataset.pending === "true") return;

      var id = form.getAttribute(config.idAttribute);
      var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
      var focus = directory.saveFocus(form);
      var row = form.closest("[" + prefix + "-progress-row]");
      var body = new FormData(form);
      var checked = Array.from(matchingForms(id)).some(function (item) {
        return item.querySelector('[aria-checked="true"]') !== null;
      });
      showError("");
      setPending(id, true);
      updateChecks(id, body.get("completed") === "1");
      fetch(form.getAttribute("action"), {
        method: "POST",
        body: body, keepalive: true,
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": csrf.value,
          "X-Requested-With": "fetch"
        }
      })
        .then(readJson)
        .then(function (data) {
          var progress = data[config.progressField];
          if (String(data[config.idField]) !== id || typeof data.completed !== "boolean" ||
              !progress || !statuses.includes(progress.status) || typeof progress.label !== "string") {
            throw new Error("La réponse du serveur est inattendue.");
          }
          updatePage(data, row, focus.current());
          if (data.highlights_reset) {
            document.dispatchEvent(new CustomEvent("heureux:highlights-hidden", {
              detail: { ids: data.hidden_highlight_ids }
            }));
          }
        })
        .catch(function (error) {
          updateChecks(id, checked);
          showError(
            error.message || "Impossible d’enregistrer cette progression."
          );
        })
        .finally(function () {
          setPending(id, false);
          focus.restore();
        });
    });
  }

  setupCompletion({
    prefix: "subject",
    idAttribute: "data-subject-response-id",
    idField: "response_id",
    progressField: "subject",
    extraRowClass: "tache-two-subject-card",
    eventName: "heureux:subject-progress"
  });
  setupCompletion({
    prefix: "writing-sujet",
    idAttribute: "data-writing-sujet-id",
    idField: "sujet_id",
    progressField: "sujet",
    eventName: "heureux:writing-sujet-progress"
  });
})();
