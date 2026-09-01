/* One-at-a-time deck for the in-page comprehension vocabulary catalog.

   The same markup powers the adaptive table view, so the deck only takes over
   while the collection renders cards: it hides every entry but the active one,
   drives the shared progress toolbar and controls, and hands flip, keyboard and
   swipe handling to the shared flashcard engine. */
(function () {
  "use strict";

  var INACTIVE_CLASS = "comprehension-vocabulary-phrase--inactive";

  function setup(deck) {
    var cards = Array.from(
      deck.querySelectorAll("[data-comprehension-vocabulary-phrase]")
    );
    if (!cards.length) return;

    var progress = deck.querySelector("[data-flashcard-progress]");
    var progressBar = deck.querySelector("[data-flashcard-progress-bar]");
    var previous = deck.querySelector("[data-flashcard-previous]");
    var next = deck.querySelector("[data-flashcard-next]");
    var index = 0;
    var interaction = null;

    function cardsMode() {
      return (
        document.documentElement.getAttribute("data-collection-view-mode")
        !== "table"
      );
    }

    function currentCard() {
      return cards[index] || null;
    }

    function updateProgress() {
      var total = cards.length;
      var position = index + 1;
      if (progress) {
        progress.textContent = String(position) + " / " + String(total);
      }
      if (progressBar) {
        progressBar.style.width = String((position / total) * 100) + "%";
      }
    }

    function syncAccessibility(activeCard) {
      var enabled = cardsMode();
      cards.forEach(function (card) {
        if (enabled && card === activeCard) {
          card.tabIndex = 0;
          card.setAttribute(
            "aria-keyshortcuts",
            "ArrowLeft ArrowRight ArrowUp ArrowDown Space Enter"
          );
        } else {
          card.removeAttribute("tabindex");
          card.removeAttribute("aria-keyshortcuts");
          card.removeAttribute("aria-label");
        }
      });
    }

    function render() {
      var activeCard = currentCard();
      cards.forEach(function (card) {
        card.classList.toggle(INACTIVE_CLASS, card !== activeCard);
      });
      if (previous) previous.disabled = index <= 0;
      if (next) next.disabled = index >= cards.length - 1;
      updateProgress();
      if (window.HeureuxReadAloud) window.HeureuxReadAloud.stop();
      if (cardsMode()) {
        if (interaction && activeCard) interaction.reset();
      } else {
        cards.forEach(function (card) {
          var front = card.querySelector("[data-flashcard-front]");
          var back = card.querySelector("[data-flashcard-back]");
          if (front) front.classList.remove("hidden");
          if (back) back.classList.remove("hidden");
          card.classList.remove("is-revealed");
        });
        if (window.HeureuxReadAloud) window.HeureuxReadAloud.refresh(deck);
      }
      syncAccessibility(activeCard);
    }

    function goPrevious() {
      if (index <= 0) return;
      index -= 1;
      render();
    }

    function goNext() {
      if (index >= cards.length - 1) return;
      index += 1;
      render();
    }

    if (window.HeureuxFlashcards) {
      interaction = window.HeureuxFlashcards.create({
        root: deck,
        getCard: currentCard,
        isEnabled: function (action) {
          if (!cardsMode()) return false;
          if (action === "left" || action === "swipe-right") {
            return index > 0;
          }
          if (action === "right" || action === "swipe-left") {
            return index < cards.length - 1;
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

    new MutationObserver(function (mutations) {
      if (mutations.some(function (mutation) {
        return mutation.attributeName === "data-collection-view-mode";
      })) {
        render();
      }
    }).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-collection-view-mode"]
    });

    render();
  }

  document
    .querySelectorAll("[data-comprehension-vocabulary-deck]")
    .forEach(setup);
})();
