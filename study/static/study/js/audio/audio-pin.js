/* Use the shared audio PIN dialog for actions that require authorization. */
(function () {
  "use strict";
  var dialog = document.querySelector("[data-audio-pin-dialog]");
  var pending = false;

  function cancelled() {
    var error = new Error("Préparation annulée.");
    error.name = "AbortError";
    return error;
  }

  function requestPin(message, signal, prompt) {
    if (signal && signal.aborted) return Promise.reject(cancelled());
    if (!dialog || typeof dialog.showModal !== "function") {
      return Promise.reject(new Error("Le formulaire PIN est indisponible. Rechargez la page."));
    }
    if (pending) return Promise.reject(new Error("Une saisie de code PIN est déjà en cours."));
    pending = true;
    return new Promise(function (resolve, reject) {
      var form = dialog.querySelector("[data-audio-pin-form]");
      var input = dialog.querySelector("[data-audio-pin-input]");
      var status = dialog.querySelector("[data-audio-pin-error]");
      var cancelButtons = dialog.querySelectorAll("[data-audio-pin-cancel]");
      var previousFocus = document.activeElement;
      var title = dialog.querySelector("h2");
      var description = dialog.querySelector("[data-audio-pin-description]");
      var submitButton = form.querySelector("[type=submit]");
      var originalTitle = title.textContent, originalDescription = description.textContent;
      var originalAction = submitButton.getAttribute("aria-label");
      function setAction(label) {
        submitButton.title = label;
        submitButton.setAttribute("aria-label", label);
      }
      if (prompt) {
        title.textContent = prompt.title;
        description.textContent = prompt.description;
        setAction(prompt.action);
      }
      var settled = false;
      input.value = "";
      input.setAttribute("aria-invalid", message ? "true" : "false");
      status.textContent = message || "";

      function finish(value) {
        if (settled) return;
        settled = true;
        input.value = "";
        form.removeEventListener("submit", submit);
        dialog.removeEventListener("cancel", close);
        dialog.removeEventListener("close", close);
        cancelButtons.forEach(function (button) { button.removeEventListener("click", close); });
        if (signal) signal.removeEventListener("abort", close);
        pending = false;
        if (dialog.open) dialog.close();
        if (prompt) {
          title.textContent = originalTitle;
          description.textContent = originalDescription;
          setAction(originalAction);
        }
        if (previousFocus && previousFocus.isConnected) previousFocus.focus({preventScroll: true});
        // AudioContext.resume must run in the PIN submit gesture, before any fetch.
        if (value !== null && prompt && prompt.onConfirm) {
          try { resolve(Promise.resolve(prompt.onConfirm()).then(function () { return value; })); }
          catch (error) { reject(error); }
        } else resolve(value);
      }
      function close() { finish(null); }
      function submit(event) {
        event.preventDefault();
        if (form.reportValidity()) finish(input.value);
      }
      form.addEventListener("submit", submit);
      dialog.addEventListener("cancel", close);
      dialog.addEventListener("close", close);
      cancelButtons.forEach(function (button) { button.addEventListener("click", close); });
      if (signal) signal.addEventListener("abort", close, {once: true});
      dialog.showModal();
      input.focus();
    });
  }

  window.HeureuxAudioRequest = function (url, options, prompt) {
    if (new URL(url, location.href).origin !== location.origin) {
      return Promise.reject(new Error("La demande audio doit rester sur ce site."));
    }
    var original = JSON.parse(options.body);
    function askThenSend(message) {
      if (prompt && prompt.onPrompt && !(options.signal && options.signal.aborted)) prompt.onPrompt();
      return requestPin(message, options.signal, prompt).then(function (value) {
        if (value === null || (options.signal && options.signal.aborted)) throw cancelled();
        return send(value);
      });
    }
    function send(pin) {
      var payload = Object.assign({}, original);
      if (pin !== undefined) payload.pin = pin;
      var request = Object.assign({}, options, {
        body: JSON.stringify(payload), redirect: "error"
      });
      return fetch(url, request).then(function (response) {
        if (response.status !== 403) return response;
        return response.clone().json().then(function (data) {
          if (data.error !== "pin_required" && data.error !== "pin_invalid") return response;
          return askThenSend(data.error === "pin_invalid" ? data.message : "");
        });
      });
    }
    return prompt && prompt.confirmBeforeSend ? askThenSend("") : send();
  };
})();
