(function () {
  "use strict";

  function normalize(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase("fr");
  }

  function setPressed(buttons, activeButton) {
    buttons.forEach(function (button) {
      var active = button === activeButton;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function preserveAuthentication(response) {
    if (response.redirected) {
      window.location.assign(response.url);
      throw new Error("Redirection vers la connexion…");
    }
    return response;
  }

  function readJson(response) {
    return response.json().catch(function () {
      throw new Error("La réponse du serveur est inattendue.");
    }).then(function (data) {
      if (!response.ok) {
        throw new Error(
          data.error || "Impossible d’enregistrer la progression."
        );
      }
      return data;
    });
  }

  function setupCatalog(root) {
    var search = root.querySelector("[data-learning-search]");
    var lessonCards = Array.from(
      root.querySelectorAll("[data-learning-lesson]")
    );
    var modules = Array.from(
      root.querySelectorAll("[data-learning-module]")
    );
    var moduleDetails = Array.from(
      root.querySelectorAll("[data-learning-module-details]")
    );
    var viewButtons = Array.from(
      root.querySelectorAll("[data-collection-view-option]")
    );
    var moduleButtons = Array.from(
      root.querySelectorAll("[data-learning-module-filter]")
    );
    var statusButtons = Array.from(
      root.querySelectorAll("[data-learning-status-filter]")
    );
    var result = root.querySelector("[data-learning-result]");
    var empty = root.querySelector("[data-learning-empty]");
    var reset = root.querySelector("[data-learning-reset]");
    var progressError = root.querySelector("[data-learning-progress-error]");
    var completedTotal = root.querySelector(
      "[data-learning-completed-total]"
    );
    var progressForms = Array.from(
      root.querySelectorAll("[data-learning-card-progress]")
    );
    if (!search || !lessonCards.length) return;

    var query = "";
    var moduleFilter = "all";
    var statusFilter = "all";

    function tableMode() {
      return (
        document.documentElement.getAttribute("data-collection-view-mode")
        === "table"
      );
    }

    function syncModuleDisclosure(resetTable) {
      moduleDetails.forEach(function (module) {
        if (!tableMode()) {
          module.open = true;
        } else if (resetTable) {
          module.open = false;
        }
      });
    }

    function revealHashTarget() {
      if (!tableMode() || !window.location.hash) return;
      var targetId = window.location.hash.slice(1);
      try {
        targetId = decodeURIComponent(targetId);
      } catch (error) {}
      var target = document.getElementById(targetId);
      if (!target || !target.matches("[data-learning-lesson]")) return;
      var module = target.closest("[data-learning-module]");
      if (!module) return;
      module.open = true;
      window.requestAnimationFrame(function () {
        target.scrollIntoView({ block: "center" });
      });
    }

    function showProgressError(message) {
      if (!progressError) return;
      progressError.textContent = message;
      progressError.classList.remove("hidden");
    }

    function clearProgressError() {
      if (!progressError) return;
      progressError.textContent = "";
      progressError.classList.add("hidden");
    }

    function matchesStatus(card) {
      if (statusFilter === "all") return true;
      if (statusFilter === "done") {
        return card.dataset.learningStatus === "done";
      }
      return card.dataset.learningStatus !== "done";
    }

    function applyFilters(updateUrl) {
      var visible = 0;
      lessonCards.forEach(function (card) {
        var searchable = normalize(card.dataset.learningSearchText);
        var matches =
          (!query || searchable.indexOf(query) !== -1)
          && (moduleFilter === "all"
            || card.dataset.learningModuleName === moduleFilter)
          && matchesStatus(card);
        card.hidden = !matches;
        if (matches) visible += 1;
      });
      modules.forEach(function (module) {
        var hasVisibleLesson = Array.from(
          module.querySelectorAll("[data-learning-lesson]")
        ).some(function (card) {
          return !card.hidden;
        });
        module.hidden = !hasVisibleLesson;
        if (
          hasVisibleLesson
          && (query || moduleFilter !== "all" || statusFilter !== "all")
        ) {
          module.open = true;
        }
      });
      if (result) {
        result.textContent =
          String(visible) + " leçon" + (visible === 1 ? "" : "s") + " affichée"
          + (visible === 1 ? "" : "s");
      }
      if (empty) empty.classList.toggle("hidden", visible !== 0);

      if (updateUrl && window.history && window.history.replaceState) {
        var url = new URL(window.location.href);
        query ? url.searchParams.set("q", search.value.trim()) : url.searchParams.delete("q");
        moduleFilter === "all"
          ? url.searchParams.delete("parcours")
          : url.searchParams.set("parcours", moduleFilter);
        statusFilter === "all"
          ? url.searchParams.delete("statut")
          : url.searchParams.set("statut", statusFilter);
        window.history.replaceState({}, "", url);
      }
    }

    function renderCardProgress(card, form, data) {
      var completed = data.completed;
      var input = form.querySelector("[data-learning-card-completed-input]");
      var button = form.querySelector("[data-learning-card-check]");
      var status = card.querySelector("[data-learning-card-status]");
      card.classList.toggle("is-completed", completed);
      form.classList.toggle("is-complete", completed);
      card.dataset.learningStatus = completed ? "done" : "active";
      if (input) input.value = completed ? "0" : "1";
      if (button) {
        var lessonLink = card.querySelector(
          ".learn-lesson-card__body > strong > a"
        );
        var lessonTitle = lessonLink ? lessonLink.textContent.trim() : "";
        button.setAttribute("aria-checked", completed ? "true" : "false");
        button.setAttribute(
          "aria-label",
          (completed ? "Marquer comme non acquise : " : "Marquer comme acquise : ")
          + lessonTitle
        );
        button.setAttribute(
          "title",
          completed ? "Leçon acquise" : "Marquer comme acquise"
        );
      }
      if (status) {
        status.textContent = completed ? "Terminée" : "En cours";
        status.classList.remove(
          "progress-status--new",
          "progress-status--active",
          "progress-status--done"
        );
        status.classList.add(
          completed ? "progress-status--done" : "progress-status--active"
        );
      }
      if (completedTotal) {
        completedTotal.textContent = String(data.completed_count);
      }
      var module = card.closest("[data-learning-module]");
      if (module) {
        var moduleCompleted = module.querySelector(
          "[data-learning-module-completed]"
        );
        var moduleCards = Array.from(
          module.querySelectorAll("[data-learning-lesson]")
        );
        var completeCount = moduleCards.filter(function (lessonCard) {
          return lessonCard.classList.contains("is-completed");
        }).length;
        if (moduleCompleted) {
          moduleCompleted.textContent = String(completeCount);
        }
        module.style.setProperty(
          "--learn-progress",
          String(Math.round(100 * completeCount / moduleCards.length)) + "%"
        );
      }
      applyFilters(false);
    }

    function selectModule(value) {
      var active = moduleButtons.find(function (button) {
        return button.dataset.learningModuleFilter === value;
      }) || moduleButtons[0];
      moduleFilter = active.dataset.learningModuleFilter;
      setPressed(moduleButtons, active);
    }

    function selectStatus(value) {
      var active = statusButtons.find(function (button) {
        return button.dataset.learningStatusFilter === value;
      }) || statusButtons[0];
      statusFilter = active.dataset.learningStatusFilter;
      setPressed(statusButtons, active);
    }

    moduleButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        selectModule(button.dataset.learningModuleFilter);
        applyFilters(true);
      });
    });
    statusButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        selectStatus(button.dataset.learningStatusFilter);
        applyFilters(true);
      });
    });
    viewButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        window.requestAnimationFrame(function () {
          syncModuleDisclosure(true);
          applyFilters(false);
        });
      });
    });
    progressForms.forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        if (form.dataset.pending === "true") return;
        var card = form.closest("[data-learning-lesson]");
        var button = form.querySelector("[data-learning-card-check]");
        var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
        form.dataset.pending = "true";
        if (button) button.disabled = true;
        clearProgressError();
        fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          credentials: "same-origin",
          headers: {
            "Accept": "application/json",
            "X-CSRFToken": csrf ? csrf.value : "",
            "X-Requested-With": "fetch"
          }
        })
          .then(preserveAuthentication)
          .then(readJson)
          .then(function (data) {
            renderCardProgress(card, form, data);
          })
          .catch(function (error) {
            showProgressError(error.message);
          })
          .finally(function () {
            delete form.dataset.pending;
            if (button) button.disabled = false;
          });
      });
    });
    search.addEventListener("input", function () {
      query = normalize(search.value.trim());
      applyFilters(true);
    });
    if (reset) {
      reset.addEventListener("click", function () {
        search.value = "";
        query = "";
        selectModule("all");
        selectStatus("all");
        syncModuleDisclosure(true);
        applyFilters(true);
        search.focus();
      });
    }

    var params = new URLSearchParams(window.location.search);
    search.value = params.get("q") || "";
    query = normalize(search.value.trim());
    selectModule(params.get("parcours") || "all");
    selectStatus(params.get("statut") || "all");
    syncModuleDisclosure(true);
    applyFilters(false);
    revealHashTarget();
    window.addEventListener("hashchange", revealHashTarget);
  }

  function setupLesson(root) {
    var startForm = root.querySelector("[data-learning-start-form]");
    var form = root.querySelector("[data-learning-progress-form]");
    if (!form) return;
    var input = form.querySelector("[data-learning-completed-input]");
    var button = form.querySelector("[data-learning-completion-button]");
    var label = form.querySelector("[data-learning-completion-label]");
    var lessonStatus = root.querySelector("[data-learning-lesson-status]");
    var count = root.querySelector("[data-learning-completed-count]");
    var bar = root.querySelector("[data-learning-progress-bar]");
    var fill = root.querySelector("[data-learning-progress-fill]");
    var title = root.querySelector("[data-learning-completion-title]");
    var copy = root.querySelector("[data-learning-completion-copy]");
    var status = root.querySelector("[data-learning-progress-status]");
    var pending = false;

    if (startForm) {
      var startCsrf = startForm.querySelector(
        "input[name='csrfmiddlewaretoken']"
      );
      fetch(startForm.action, {
        method: "POST",
        body: new FormData(startForm),
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": startCsrf ? startCsrf.value : "",
          "X-Requested-With": "fetch"
        }
      })
        .then(preserveAuthentication)
        .then(readJson)
        .catch(function (error) {
          if (status) status.textContent = error.message;
        });
    }

    function render(data) {
      var completed = data.completed;
      root.classList.toggle("is-completed", completed);
      input.value = completed ? "0" : "1";
      button.setAttribute("aria-pressed", completed ? "true" : "false");
      button.classList.toggle("btn--primary", !completed);
      label.textContent = completed
        ? "Marquer à revoir"
        : "Marquer comme acquise";
      if (lessonStatus) {
        lessonStatus.textContent = completed ? "Terminée" : "En cours";
        lessonStatus.classList.toggle("progress-status--done", completed);
        lessonStatus.classList.toggle("progress-status--active", !completed);
      }
      if (count) count.textContent = String(data.completed_count);
      if (bar) {
        bar.setAttribute("aria-valuenow", String(data.percent));
        bar.setAttribute(
          "aria-label",
          String(data.percent) + " % des leçons terminées"
        );
      }
      if (fill) fill.style.width = String(data.percent) + "%";
      if (title) {
        title.textContent = completed
          ? "Leçon acquise"
          : "Prêt à valider cette leçon ?";
      }
      if (copy) {
        copy.textContent = completed
          ? "Tu peux la rouvrir à tout moment pour consolider un point."
          : "Valide-la lorsque tu peux expliquer les idées essentielles sans relire.";
      }
      if (status) {
        status.textContent = completed
          ? "Progression enregistrée."
          : "La leçon a été replacée dans ton parcours.";
      }
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (pending) return;
      pending = true;
      button.disabled = true;
      if (status) status.textContent = "";
      var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "X-CSRFToken": csrf ? csrf.value : "",
          "X-Requested-With": "fetch"
        }
      })
        .then(preserveAuthentication)
        .then(readJson)
        .then(render)
        .catch(function (error) {
          if (status) status.textContent = error.message;
        })
        .finally(function () {
          pending = false;
          button.disabled = false;
        });
    });
  }

  document.querySelectorAll("[data-learning-catalog]").forEach(setupCatalog);
  document.querySelectorAll("[data-learning-lesson-page]").forEach(setupLesson);
})();
