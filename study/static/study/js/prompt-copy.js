(function () {
  "use strict";

  var buttons = Array.prototype.slice.call(
    document.querySelectorAll("[data-prompt-copy]")
  );

  if (!buttons.length) {
    return;
  }

  var payloadCache = Object.create(null);
  var resetTimers = new WeakMap();
  var toast = document.querySelector("[data-prompt-copy-toast]");
  var toastTimer = null;

  function readPayload(sourceId) {
    if (Object.prototype.hasOwnProperty.call(payloadCache, sourceId)) {
      return payloadCache[sourceId];
    }

    var source = document.getElementById(sourceId);
    if (!source) {
      throw new Error("Copy source not found: " + sourceId);
    }

    var payload = JSON.parse(source.textContent);
    payloadCache[sourceId] = payload;
    return payload;
  }

  function textForButton(button) {
    var payload = readPayload(button.dataset.promptCopySource);
    var key = button.dataset.promptCopyKey;

    if (key) {
      if (
        !payload ||
        typeof payload !== "object" ||
        !Object.prototype.hasOwnProperty.call(payload, key)
      ) {
        throw new Error("Copy key not found: " + key);
      }
      payload = payload[key];
    }

    if (typeof payload !== "string" || !payload.trim()) {
      throw new Error("Copy source is empty or invalid.");
    }

    return payload;
  }

  function legacyCopy(text) {
    return new Promise(function (resolve, reject) {
      var input = document.createElement("textarea");
      input.value = text;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      input.style.pointerEvents = "none";
      document.body.appendChild(input);
      input.select();
      input.setSelectionRange(0, input.value.length);

      var copied = false;
      try {
        copied = document.execCommand("copy");
      } catch (error) {
        document.body.removeChild(input);
        reject(error);
        return;
      }

      document.body.removeChild(input);
      if (copied) {
        resolve();
      } else {
        reject(new Error("The browser rejected the copy command."));
      }
    });
  }

  function writeClipboard(text) {
    if (
      navigator.clipboard &&
      typeof navigator.clipboard.writeText === "function"
    ) {
      try {
        return Promise.resolve(navigator.clipboard.writeText(text)).catch(
          function () {
            return legacyCopy(text);
          }
        );
      } catch (error) {
        return legacyCopy(text);
      }
    }
    return legacyCopy(text);
  }

  function showToast(message, isError) {
    if (!toast || !message) {
      return;
    }

    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.toggle("is-error", Boolean(isError));
    toast.classList.remove("hidden");
    toastTimer = window.setTimeout(function () {
      toast.classList.add("hidden");
      toast.classList.remove("is-error");
    }, 2400);
  }

  function setStatus(button, message) {
    var statusId = button.dataset.promptCopyStatus;
    if (!statusId) {
      return;
    }

    var status = document.getElementById(statusId);
    if (status) {
      status.textContent = message;
    }
  }

  function setButtonState(button, state) {
    var label = button.querySelector("[data-prompt-copy-label]");
    var defaultLabel = button.dataset.promptCopyDefaultLabel;
    var defaultAriaLabel = button.dataset.promptCopyDefaultAriaLabel;
    var defaultTitle = button.dataset.promptCopyDefaultTitle;
    var isError = state === "error";
    var isCopied = state === "copied";

    button.classList.toggle("is-copied", isCopied);
    button.classList.toggle("is-copy-error", isError);

    if (state === "default") {
      if (label) {
        label.textContent = defaultLabel;
      }
      button.setAttribute("aria-label", defaultAriaLabel);
      button.setAttribute("title", defaultTitle);
      return;
    }

    var nextLabel = isCopied
      ? button.dataset.promptCopySuccessLabel
      : button.dataset.promptCopyErrorLabel;
    if (label) {
      label.textContent = nextLabel;
    }
    button.setAttribute("aria-label", nextLabel);
    button.setAttribute("title", nextLabel);
  }

  function resetButtonLater(button) {
    resetTimers.set(
      button,
      window.setTimeout(function () {
        setButtonState(button, "default");
        setStatus(button, "");
        resetTimers.delete(button);
      }, 2400)
    );
  }

  buttons.forEach(function (button) {
    var label = button.querySelector("[data-prompt-copy-label]");
    button.dataset.promptCopyDefaultLabel = label ? label.textContent : "";
    button.dataset.promptCopyDefaultAriaLabel =
      button.getAttribute("aria-label") || "";
    button.dataset.promptCopyDefaultTitle = button.getAttribute("title") || "";

    button.addEventListener("click", function () {
      var existingTimer = resetTimers.get(button);
      if (existingTimer) {
        window.clearTimeout(existingTimer);
      }

      var text;
      try {
        text = textForButton(button);
      } catch (error) {
        setButtonState(button, "error");
        setStatus(button, button.dataset.promptCopyErrorMessage);
        showToast(button.dataset.promptCopyErrorMessage, true);
        resetButtonLater(button);
        return;
      }

      button.disabled = true;
      writeClipboard(text)
        .then(function () {
          setButtonState(button, "copied");
          setStatus(button, button.dataset.promptCopyToastMessage);
          showToast(button.dataset.promptCopyToastMessage, false);
        })
        .catch(function () {
          setButtonState(button, "error");
          setStatus(button, button.dataset.promptCopyErrorMessage);
          showToast(button.dataset.promptCopyErrorMessage, true);
        })
        .finally(function () {
          button.disabled = false;
          resetButtonLater(button);
        });
    });
  });
})();
