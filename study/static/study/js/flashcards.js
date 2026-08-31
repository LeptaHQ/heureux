/* Shared face, keyboard, pointer-swipe, and order controls for flashcard decks. */
(function () {
  "use strict";

  var SWIPE_MIN = 55;
  var INTERACTIVE_SELECTOR =
    "a, button, input, select, textarea, [contenteditable='true']";

  function hasTextSelection() {
    var selection = window.getSelection();
    return Boolean(selection && !selection.isCollapsed);
  }

  function create(options) {
    var root = options && options.root;
    if (!root) throw new Error("A flashcard deck root is required.");

    var revealed = false;
    var reverseOrder = false;
    var swipe = null;
    var consumeClick = false;

    function card() {
      return options.getCard
        ? options.getCard()
        : root.querySelector("[data-flashcard-card]:not(.hidden)");
    }

    function allowed(action) {
      if (!card()) return false;
      return !options.isEnabled || options.isEnabled(action) !== false;
    }

    function dispatchChange(kind) {
      root.dispatchEvent(new CustomEvent("heureux:flashcard-change", {
        bubbles: true,
        detail: {
          kind: kind,
          revealed: revealed,
          reverseOrder: reverseOrder
        }
      }));
    }

    function setFace(nextRevealed, changeKind) {
      var current = card();
      if (!current) return;
      revealed = Boolean(nextRevealed);
      var front = current.querySelector("[data-flashcard-front]");
      var back = current.querySelector("[data-flashcard-back]");
      var showFront = reverseOrder ? revealed : !revealed;
      if (front) front.classList.toggle("hidden", !showFront);
      if (back) back.classList.toggle("hidden", showFront);
      current.classList.toggle("is-revealed", revealed);
      var face = showFront ? "Recto" : "Verso";
      var faceLabel = current.querySelector("[data-flashcard-face-label]");
      if (faceLabel) faceLabel.textContent = face;
      current.setAttribute(
        "aria-label",
        face + ". Appuyez pour retourner la carte."
      );
      root.querySelectorAll("[data-flashcard-flip-label]").forEach(
        function (label) {
          label.textContent = revealed ? "Masquer" : "Retourner";
        }
      );
      if (options.onFaceChange) {
        options.onFaceChange({
          card: current,
          revealed: revealed,
          reverseOrder: reverseOrder,
          visibleFace: showFront ? "front" : "back"
        });
      }
      dispatchChange(changeKind || "face");
    }

    function reset(config) {
      var current = card();
      if (current) {
        current.classList.remove(
          "flashcard-deck__card--swiping",
          "flashcard-deck__card--settle"
        );
        current.style.transform = "";
        current.style.opacity = "";
      }
      setFace(Boolean(config && config.revealed), "card");
    }

    function reveal() {
      if (!revealed && allowed("flip")) setFace(true);
    }

    function hide() {
      if (revealed && allowed("flip")) setFace(false);
    }

    function toggle() {
      if (!allowed("flip")) return false;
      setFace(!revealed);
      return true;
    }

    function syncOrderButtons() {
      root.querySelectorAll("[data-flashcard-order]").forEach(
        function (button) {
          var active =
            (button.dataset.flashcardOrder === "back") === reverseOrder;
          button.classList.toggle("is-active", active);
          button.setAttribute("aria-pressed", active ? "true" : "false");
        }
      );
    }

    function setOrder(order) {
      reverseOrder = order === "back";
      syncOrderButtons();
      reset();
    }

    function invoke(action, callback) {
      if (!callback || !allowed(action)) return false;
      callback(api);
      return true;
    }

    function settle(target) {
      if (!target) return;
      target.classList.remove("flashcard-deck__card--swiping");
      target.classList.add("flashcard-deck__card--settle");
      target.style.transform = "";
      target.style.opacity = "";
      window.setTimeout(function () {
        target.classList.remove("flashcard-deck__card--settle");
      }, 200);
    }

    function finishSwipe(event) {
      if (!swipe || event.pointerId !== swipe.id) return;
      var target = swipe.card;
      var dx = event.clientX - swipe.x;
      var axis = swipe.axis;
      swipe = null;
      settle(target);
      if (
        axis !== "x" ||
        Math.abs(dx) < SWIPE_MIN ||
        hasTextSelection()
      ) {
        return;
      }
      consumeClick = true;
      window.setTimeout(function () {
        consumeClick = false;
      }, 0);
      if (dx < 0) {
        invoke(
          "swipe-left",
          options.onSwipeLeft || options.onRight
        );
      } else {
        invoke(
          "swipe-right",
          options.onSwipeRight || options.onLeft
        );
      }
    }

    function interactiveTarget(target) {
      return target && target.closest
        ? target.closest(INTERACTIVE_SELECTOR)
        : null;
    }

    root.addEventListener("click", function (event) {
      var orderButton = event.target.closest("[data-flashcard-order]");
      if (orderButton && root.contains(orderButton)) {
        setOrder(orderButton.dataset.flashcardOrder);
        return;
      }
      var flipButton = event.target.closest("[data-flashcard-flip]");
      if (flipButton && root.contains(flipButton)) {
        toggle();
        return;
      }
      var targetCard = event.target.closest("[data-flashcard-card]");
      if (!targetCard || targetCard !== card()) return;
      if (consumeClick) {
        consumeClick = false;
        return;
      }
      if (event.target.closest("[data-flashcard-ignore-toggle]")) return;
      if (interactiveTarget(event.target) || hasTextSelection()) return;
      toggle();
    });

    root.addEventListener("pointerdown", function (event) {
      var targetCard = event.target.closest("[data-flashcard-card]");
      if (
        !event.isPrimary ||
        event.pointerType !== "touch" ||
        targetCard !== card() ||
        event.target.closest("[data-flashcard-ignore-toggle]") ||
        interactiveTarget(event.target) ||
        !allowed("swipe")
      ) {
        return;
      }
      swipe = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        card: targetCard,
        axis: null
      };
      if (event.isTrusted && targetCard.setPointerCapture) {
        targetCard.setPointerCapture(event.pointerId);
      }
    });

    root.addEventListener("pointermove", function (event) {
      if (!swipe || event.pointerId !== swipe.id || !swipe.card) return;
      var dx = event.clientX - swipe.x;
      var dy = event.clientY - swipe.y;
      if (!swipe.axis) {
        if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
        swipe.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
        if (swipe.axis === "x") {
          swipe.card.classList.add("flashcard-deck__card--swiping");
        }
      }
      if (swipe.axis !== "x" || hasTextSelection()) return;
      event.preventDefault();
      swipe.card.style.transform =
        "translateX(" + String(dx) + "px) rotate("
        + String(dx / 45) + "deg)";
      swipe.card.style.opacity = String(
        Math.max(0.5, 1 - Math.abs(dx) / 420)
      );
    });
    root.addEventListener("pointerup", finishSwipe);
    root.addEventListener("pointercancel", function () {
      if (swipe && swipe.card) settle(swipe.card);
      swipe = null;
    });

    function keydown(event) {
      var target = event.target;
      if (
        target
        && target.closest
        && target.closest("[data-flashcard-ignore-toggle]")
      ) {
        return;
      }
      var interactive = interactiveTarget(target);
      var control = target && target.closest
        ? target.closest("[data-flashcard-control]")
        : null;
      var directional = event.key.indexOf("Arrow") === 0;
      if (interactive && !(control && directional)) return;

      var handled = false;
      if (
        event.code === "Space" ||
        event.key === "Enter" ||
        event.key === "ArrowUp" ||
        event.key === "ArrowDown"
      ) {
        handled = toggle();
      } else if (event.key === "ArrowLeft") {
        handled = invoke("left", options.onLeft);
      } else if (event.key === "ArrowRight") {
        handled = invoke("right", options.onRight);
      }
      if (handled) event.preventDefault();
    }
    document.addEventListener("keydown", keydown);

    var api = {
      reset: reset,
      reveal: reveal,
      hide: hide,
      toggle: toggle,
      setRevealed: function (value) { setFace(value); },
      isRevealed: function () { return revealed; },
      setOrder: setOrder,
      isReverseOrder: function () { return reverseOrder; },
      destroy: function () {
        document.removeEventListener("keydown", keydown);
      }
    };

    syncOrderButtons();
    return api;
  }

  window.HeureuxFlashcards = {
    create: create
  };
})();
