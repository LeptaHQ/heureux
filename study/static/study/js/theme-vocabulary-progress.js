(function () {
  "use strict";

  function countLabel(count, noun) {
    return String(count) + " " + noun + (count === 1 ? "" : "s") + " affiché"
      + (noun === "fiche" ? "e" : "") + (count === 1 ? "" : "s");
  }

  function setPressed(buttons, activeValue, attribute) {
    buttons.forEach(function (button) {
      var active = button.getAttribute(attribute) === activeValue;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function setupDirectory(directory) {
    var items = Array.from(
      directory.querySelectorAll("[data-theme-vocabulary-directory-item]")
    );
    var buttons = Array.from(
      directory.querySelectorAll("[data-theme-vocabulary-directory-filter]")
    );
    var result = directory.querySelector(
      "[data-theme-vocabulary-directory-result]"
    );
    var empty = directory.querySelector(
      "[data-theme-vocabulary-directory-empty]"
    );
    var reset = directory.querySelector(
      "[data-theme-vocabulary-directory-reset]"
    );
    var grid = directory.querySelector(
      ".theme-vocabulary-directory .memory-library__grid, "
      + ".memory-library__grid"
    );
    if (!items.length || !buttons.length) return;

    function applyFilter(value) {
      var visible = 0;
      items.forEach(function (item) {
        var matches =
          value === "all" || item.dataset.themeVocabularyStatus === value;
        item.classList.toggle("theme-vocabulary-filtered-out", !matches);
        if (matches) visible += 1;
      });
      setPressed(
        buttons,
        value,
        "data-theme-vocabulary-directory-filter"
      );
      if (result) result.textContent = countLabel(visible, "thème");
      if (empty) empty.classList.toggle("hidden", visible !== 0);
      if (grid) grid.classList.toggle("theme-vocabulary-filtered-out", visible === 0);
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        applyFilter(button.dataset.themeVocabularyDirectoryFilter);
      });
    });
    if (reset) {
      reset.addEventListener("click", function () {
        applyFilter("all");
        buttons[0].focus();
      });
    }
    applyFilter("all");
  }

  document.querySelectorAll("[data-theme-vocabulary-directory]").forEach(
    setupDirectory
  );

  var root = document.querySelector("[data-theme-vocabulary-progress]");
  if (!root) return;

  var errorMessage = root.querySelector(
    "[data-theme-vocabulary-progress-error]"
  );
  var learnedCount = document.querySelector(
    "[data-theme-vocabulary-learned-count]"
  );
  var filterButtons = Array.from(
    root.querySelectorAll("[data-theme-vocabulary-status-filter]")
  );
  var filterResult = root.querySelector(
    "[data-theme-vocabulary-filter-result]"
  );
  var filterEmpty = root.querySelector(
    "[data-theme-vocabulary-filter-empty]"
  );
  var filterReset = root.querySelector(
    "[data-theme-vocabulary-filter-reset]"
  );
  var phrases = Array.from(
    root.querySelectorAll("[data-theme-vocabulary-phrase]")
  );
  var groups = Array.from(
    root.querySelectorAll("[data-theme-vocabulary-group]")
  );
  var deck = root.querySelector("[data-theme-vocabulary-deck]");
  var previous = root.querySelector("[data-theme-vocabulary-previous]");
  var next = root.querySelector("[data-theme-vocabulary-next]");
  var deckProgress = root.querySelector(
    "[data-theme-vocabulary-deck-progress]"
  );
  var deckProgressBar = root.querySelector(
    "[data-theme-vocabulary-deck-progress-bar]"
  );
  var activeFilter = "all";
  var filteredPhrases = phrases.slice();
  var phraseIndex = 0;
  var interaction = null;
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

  function matchesFilter(phrase) {
    return (
      activeFilter === "all"
      || phrase.dataset.themeVocabularyStatus === activeFilter
    );
  }

  function cardsMode() {
    return (
      document.documentElement.getAttribute("data-collection-view-mode")
      !== "table"
    );
  }

  function currentPhrase() {
    return filteredPhrases[phraseIndex] || null;
  }

  function updateDeckProgress() {
    var total = filteredPhrases.length;
    var position = total ? phraseIndex + 1 : 0;
    if (deckProgress) {
      deckProgress.textContent = String(position) + " / " + String(total);
    }
    if (deckProgressBar) {
      deckProgressBar.style.width = total
        ? String((position / total) * 100) + "%"
        : "0%";
    }
  }

  function syncCardAccessibility(activePhrase) {
    var enabled = cardsMode();
    phrases.forEach(function (phrase) {
      if (enabled && phrase === activePhrase) {
        phrase.tabIndex = 0;
        phrase.setAttribute(
          "aria-keyshortcuts",
          "ArrowLeft ArrowRight ArrowUp ArrowDown Space Enter"
        );
      } else {
        phrase.removeAttribute("tabindex");
        phrase.removeAttribute("aria-keyshortcuts");
        phrase.removeAttribute("aria-label");
      }
    });
  }

  function renderDeck() {
    var activePhrase = currentPhrase();
    phrases.forEach(function (phrase) {
      phrase.classList.toggle(
        "theme-vocabulary-card--inactive",
        phrase !== activePhrase
      );
    });
    if (deck) {
      deck.classList.toggle(
        "theme-vocabulary-deck--empty",
        filteredPhrases.length === 0
      );
    }
    if (previous) previous.disabled = phraseIndex <= 0;
    if (next) {
      next.disabled =
        !filteredPhrases.length || phraseIndex >= filteredPhrases.length - 1;
    }
    updateDeckProgress();
    if (window.HeureuxReadAloud) window.HeureuxReadAloud.stop();
    if (cardsMode()) {
      if (interaction && activePhrase) interaction.reset();
    } else {
      phrases.forEach(function (phrase) {
        var front = phrase.querySelector("[data-flashcard-front]");
        var back = phrase.querySelector("[data-flashcard-back]");
        if (front) front.classList.remove("hidden");
        if (back) back.classList.remove("hidden");
        phrase.classList.remove("is-revealed");
      });
      if (window.HeureuxReadAloud) {
        window.HeureuxReadAloud.refresh(root);
      }
    }
    syncCardAccessibility(activePhrase);
  }

  function refreshDeck(resetPosition) {
    var previousPhrase = currentPhrase();
    var previousIndex = phraseIndex;
    filteredPhrases = phrases.filter(matchesFilter);
    if (resetPosition) {
      phraseIndex = 0;
    } else if (previousPhrase && filteredPhrases.includes(previousPhrase)) {
      phraseIndex = filteredPhrases.indexOf(previousPhrase);
    } else {
      phraseIndex = Math.min(previousIndex, filteredPhrases.length - 1);
      phraseIndex = Math.max(phraseIndex, 0);
    }
    renderDeck();
  }

  function updateFilterCounts() {
    var counts = {
      all: phrases.length,
      learning: 0,
      learned: 0
    };
    phrases.forEach(function (phrase) {
      counts[phrase.dataset.themeVocabularyStatus] += 1;
    });
    Object.keys(counts).forEach(function (status) {
      var count = root.querySelector(
        '[data-theme-vocabulary-filter-count="' + status + '"]'
      );
      if (count) count.textContent = String(counts[status]);
    });
  }

  function updateGroups() {
    groups.forEach(function (group) {
      var groupPhrases = Array.from(
        group.querySelectorAll("[data-theme-vocabulary-phrase]")
      );
      var visible = groupPhrases.filter(matchesFilter).length;
      var count = group.querySelector("[data-theme-vocabulary-group-count]");
      group.classList.toggle(
        "theme-vocabulary-filtered-out",
        visible === 0
      );
      if (count) {
        var total = Number(count.dataset.total || groupPhrases.length);
        count.textContent =
          activeFilter === "all"
            ? String(total) + " fiches"
            : String(visible) + " / " + String(total) + " fiches";
      }
    });
  }

  function applyFilter(value, resetPosition) {
    activeFilter = ["all", "learning", "learned"].includes(value)
      ? value
      : "all";
    phrases.forEach(function (phrase) {
      phrase.classList.toggle(
        "theme-vocabulary-filtered-out",
        !matchesFilter(phrase)
      );
    });
    setPressed(
      filterButtons,
      activeFilter,
      "data-theme-vocabulary-status-filter"
    );
    updateFilterCounts();
    updateGroups();
    refreshDeck(resetPosition);
    var visible = filteredPhrases.length;
    if (filterResult) {
      filterResult.textContent = countLabel(visible, "fiche");
    }
    if (filterEmpty) filterEmpty.classList.toggle("hidden", visible !== 0);
  }

  function goPrevious() {
    if (phraseIndex <= 0) return;
    phraseIndex -= 1;
    renderDeck();
  }

  function goNext() {
    if (phraseIndex >= filteredPhrases.length - 1) return;
    phraseIndex += 1;
    renderDeck();
  }

  if (deck && window.HeureuxFlashcards) {
    interaction = window.HeureuxFlashcards.create({
      root: deck,
      getCard: currentPhrase,
      isEnabled: function (action) {
        if (!cardsMode() || !filteredPhrases.length) return false;
        if (action === "left" || action === "swipe-right") {
          return phraseIndex > 0;
        }
        if (action === "right" || action === "swipe-left") {
          return phraseIndex < filteredPhrases.length - 1;
        }
        return true;
      },
      onLeft: goPrevious,
      onRight: goNext,
      onSwipeLeft: goNext,
      onSwipeRight: goPrevious,
      onFaceChange: function () {
        if (window.HeureuxReadAloud) window.HeureuxReadAloud.stop();
      }
    });
  }
  if (previous) previous.addEventListener("click", goPrevious);
  if (next) next.addEventListener("click", goNext);

  filterButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      applyFilter(button.dataset.themeVocabularyStatusFilter, true);
    });
  });
  if (filterReset) {
    filterReset.addEventListener("click", function () {
      applyFilter("all", true);
      filterButtons[0].focus();
    });
  }

  function updatePhrase(form, completed) {
    var phrase = form.closest("[data-theme-vocabulary-phrase]");
    if (!phrase) return;
    var input = form.querySelector(
      "[data-theme-vocabulary-completed-input]"
    );
    var button = form.querySelector("button");
    var statusCopy = phrase.querySelector(
      "[data-theme-vocabulary-status-copy]"
    );
    phrase.classList.toggle("is-learned", completed);
    phrase.dataset.themeVocabularyStatus = completed
      ? "learned"
      : "learning";
    if (input) input.value = completed ? "0" : "1";
    if (statusCopy) {
      statusCopy.textContent = completed ? "Apprise" : "À apprendre";
    }
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
    var phrase = form.closest("[data-theme-vocabulary-phrase]");
    var focusWillMove = phrase && !(
      activeFilter === "all"
      || activeFilter === (
        body.get("completed") === "1" ? "learned" : "learning"
      )
    );

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
        applyFilter(activeFilter, false);
        if (focusWillMove) {
          window.requestAnimationFrame(function () {
            var activePhrase = currentPhrase();
            if (cardsMode() && activePhrase) activePhrase.focus();
            else {
              var activeButton = filterButtons.find(function (candidate) {
                return candidate.getAttribute("aria-pressed") === "true";
              });
              if (activeButton) activeButton.focus();
            }
          });
        }
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

  new MutationObserver(function (mutations) {
    if (mutations.some(function (mutation) {
      return mutation.attributeName === "data-collection-view-mode";
    })) {
      renderDeck();
    }
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-collection-view-mode"]
  });

  applyFilter("all", true);
})();
