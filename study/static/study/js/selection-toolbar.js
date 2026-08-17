/* Highlight-to-English translation using the browser's local Translator API. */
(function () {
  "use strict";

  var action = document.querySelector("[data-selection-translate]");
  var selectionCopyButton = document.querySelector("[data-copy-selection]");
  var selectionCopyLabel = document.querySelector("[data-copy-selection-label]");
  var selectionCopyIcon = document.querySelector("[data-copy-selection-icon]");
  var readButton = document.querySelector("[data-read-selection]");
  var readLabel = document.querySelector("[data-read-selection-label]");
  var translateButton = document.querySelector("[data-translate-selection]");
  var noteButton = document.querySelector("[data-note-selection]");
  var highlightButton = document.querySelector("[data-highlight-selection]");
  var penCursor = document.querySelector("[data-pen-cursor]");
  var panel = document.querySelector("[data-translation-panel]");
  var notePanel = document.querySelector("[data-note-panel]");
  var main = document.getElementById("main");
  if (
    !action ||
    !selectionCopyButton ||
    !selectionCopyLabel ||
    !translateButton ||
    !panel ||
    !main
  ) {
    return;
  }

  var closeButtons = Array.from(
    panel.querySelectorAll("[data-translation-close]")
  );
  var sourceElement = panel.querySelector("[data-translation-source]");
  var statusElement = panel.querySelector("[data-translation-status-text]");
  var spinner = panel.querySelector("[data-translation-spinner]");
  var output = panel.querySelector("[data-translation-output]");
  var resultElement = panel.querySelector("[data-translation-result]");
  var copyButton = panel.querySelector("[data-translation-copy]");
  var copyLabel = panel.querySelector("[data-translation-copy-label]");
  var copyIcon = panel.querySelector("[data-translation-copy-icon]");
  var translationNoteButton = panel.querySelector("[data-translation-note]");
  var translationNoteLabel = panel.querySelector(
    "[data-translation-note-label]"
  );
  var fallbackLink = panel.querySelector("[data-translation-fallback]");
  var fallbackLabel = panel.querySelector("[data-translation-fallback-label]");
  var mobileActionQuery = window.matchMedia(
    "(max-width: 760px), (hover: none), (pointer: coarse)"
  );
  var mobilePanelQuery = window.matchMedia("(max-width: 520px)");
  var translatorOptions = {
    sourceLanguage: "fr",
    targetLanguage: "en"
  };
  var maxLocalLength = 2000;
  var selectedText = "";
  var selectedRect = null;
  var selectionTimer = null;
  var selectionCopyTimer = null;
  var requestNumber = 0;
  var translatorPromise = null;
  var translatorInstance = null;
  var frenchSpeech = window.HeureuxFrenchSpeech;
  var reading = false;
  var readingNumber = 0;
  var readingChunks = [];
  var readingIndex = 0;
  var readResetTimer = null;
  var selectionPointerId = null;
  var selectionPointerTimer = null;
  var selectedRange = null;
  var viewportFrame = null;
  var penCursorFrame = null;
  var penCursorHideTimer = null;
  var penCursorX = 0;
  var penCursorY = 0;
  var penHoveredButton = null;
  var penActionSize = null;
  var toolbarSelectionPinned = false;
  var root = document.documentElement;

  function setSpriteIcon(icon, name) {
    if (!icon) return;
    var href = icon.getAttribute("href") || "";
    icon.setAttribute(
      "href",
      href.replace(/#icon-[a-z0-9-]+$/, "#icon-" + name)
    );
    if (icon.ownerSVGElement) {
      icon.ownerSVGElement.dataset.icon = name;
    }
  }

  function normalizeSelection(text) {
    return text
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+/g, " ")
      .replace(/\n[ \t]+/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function penInputActive() {
    return root.dataset.inputMode === "pen";
  }

  function setInputMode(mode) {
    var currentMode = root.dataset.inputMode || "";
    var nextMode = mode || "";
    if (currentMode === nextMode) return;
    if (nextMode) root.dataset.inputMode = nextMode;
    else delete root.dataset.inputMode;
    penActionSize = null;
    if (!action.classList.contains("hidden")) repositionOpenUi();
  }

  function drawPenCursor() {
    penCursorFrame = null;
    if (!penCursor) return;
    penCursor.style.transform =
      "translate3d(" + penCursorX + "px, " + penCursorY + "px, 0) " +
      "translate3d(-50%, -50%, 0)";
  }

  function showPenCursor(event) {
    if (!penCursor || event.pointerType !== "pen") return;
    penCursorX = event.clientX;
    penCursorY = event.clientY;
    window.clearTimeout(penCursorHideTimer);
    var becomingVisible = !penCursor.classList.contains("is-visible");
    if (becomingVisible) {
      if (penCursorFrame) window.cancelAnimationFrame(penCursorFrame);
      drawPenCursor();
    } else if (!penCursorFrame) {
      penCursorFrame = window.requestAnimationFrame(drawPenCursor);
    }
    var overAction = event.target && action.contains(event.target);
    var deferModeChange =
      event.type === "pointerdown" &&
      !action.classList.contains("hidden");
    if (!overAction && !deferModeChange) setInputMode("pen");
    if (!root.classList.contains("pen-cursor-hidden")) {
      root.classList.add("pen-cursor-hidden");
    }
    if (becomingVisible) penCursor.classList.add("is-visible");
  }

  function hidePenCursorNow() {
    window.clearTimeout(penCursorHideTimer);
    if (penCursorFrame) {
      window.cancelAnimationFrame(penCursorFrame);
      penCursorFrame = null;
    }
    root.classList.remove("pen-cursor-hidden");
    if (penCursor) {
      penCursor.classList.remove("is-visible", "is-pressed");
    }
  }

  function schedulePenCursorHide() {
    window.clearTimeout(penCursorHideTimer);
    penCursorHideTimer = window.setTimeout(hidePenCursorNow, 450);
  }

  function rememberPointerInput(event) {
    if (event.pointerType === "pen") {
      showPenCursor(event);
    } else if (event.pointerType === "mouse" || event.pointerType === "touch") {
      hidePenCursorNow();
      if (event.target && action.contains(event.target)) return;
      setInputMode("");
    }
  }

  function setPenHoveredButton(button) {
    if (button === penHoveredButton) return;
    if (penHoveredButton) {
      penHoveredButton.classList.remove("is-pen-hovered");
    }
    penHoveredButton = button;
    if (penHoveredButton) {
      penHoveredButton.classList.add("is-pen-hovered");
    }
  }

  function selectablePointerTarget(target) {
    return Boolean(
      target &&
      target.closest &&
      main.contains(target) &&
      !target.closest(
        "button, input, textarea, select, [contenteditable='true'], " +
        "[data-selection-translate], [data-translation-panel], " +
        "[data-note-panel]"
      )
    );
  }

  function selectionDetails() {
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0 || !main) {
      return null;
    }

    var range = selection.getRangeAt(0);
    var container = range.commonAncestorContainer;
    var element = container.nodeType === Node.ELEMENT_NODE
      ? container
      : container.parentElement;
    if (
      !element ||
      !main.contains(element) ||
      action.contains(element) ||
      panel.contains(element) ||
      element.closest(
        "button, input, textarea, select, [contenteditable='true'], " +
        "[data-note-panel]"
      )
    ) {
      return null;
    }

    var text = normalizeSelection(range.cloneContents().textContent || "");
    var rect = range.getBoundingClientRect();
    if (!text || (!rect.width && !rect.height)) return null;
    return { text: text, rect: rect, range: range.cloneRange() };
  }

  function hideAction() {
    stopReading();
    setPenHoveredButton(null);
    toolbarSelectionPinned = false;
    action.classList.add("hidden");
  }

  function viewportBounds() {
    var viewport = window.visualViewport;
    var left = viewport ? viewport.offsetLeft : 0;
    var top = viewport ? viewport.offsetTop : 0;
    var width = viewport ? viewport.width : window.innerWidth;
    var height = viewport ? viewport.height : window.innerHeight;
    return {
      left: left,
      top: top,
      right: left + width,
      bottom: top + height
    };
  }

  function currentSelectionRect() {
    if (selectedRange) {
      var rect = selectedRange.getBoundingClientRect();
      if (rect.width || rect.height) {
        selectedRect = rect;
      }
    }
    return selectedRect;
  }

  function positionAction(rect) {
    action.classList.remove("hidden");
    if (mobileActionQuery.matches && !penInputActive()) {
      action.style.left = "";
      action.style.top = "";
      return;
    }

    var penMode = penInputActive();
    var actionRect = penMode && penActionSize
      ? penActionSize
      : action.getBoundingClientRect();
    if (penMode && !penActionSize) {
      penActionSize = {
        width: actionRect.width,
        height: actionRect.height
      };
      actionRect = penActionSize;
    }
    var bounds = viewportBounds();
    var inset = 8;
    var left = rect.left + (rect.width - actionRect.width) / 2;
    var maxLeft = Math.max(
      bounds.left + inset,
      bounds.right - actionRect.width - inset
    );
    left = Math.max(bounds.left + inset, Math.min(left, maxLeft));
    var gap = penMode ? 28 : 8;
    var above = rect.top - actionRect.height - gap;
    var below = rect.bottom + gap;
    var minimumTop = bounds.top + inset;
    var maximumTop = Math.max(
      minimumTop,
      bounds.bottom - actionRect.height - inset
    );
    var preferred = penMode ? below : above;
    var alternate = penMode ? above : below;
    var top = preferred >= minimumTop && preferred <= maximumTop
      ? preferred
      : alternate;
    top = Math.max(minimumTop, Math.min(top, maximumTop));
    action.style.left = Math.round(left) + "px";
    action.style.top = Math.round(top) + "px";
  }

  function applySelectionDetails(details) {
    var selectionChanged = details.text !== selectedText;
    if (selectionChanged && reading) stopReading();
    selectedText = details.text;
    selectedRect = details.rect;
    selectedRange = details.range;
    selectionCopyButton.classList.remove("is-copied");
    selectionCopyLabel.textContent = "Copy";
    if (selectionChanged) resetReadButton();
    positionAction(details.rect);
  }

  function updateSelectionAction() {
    if (
      !panel.classList.contains("hidden") ||
      (notePanel && !notePanel.classList.contains("hidden"))
    ) {
      return;
    }
    var details = selectionDetails();
    if (!details) {
      if (
        !toolbarSelectionPinned &&
        !action.classList.contains("hidden")
      ) {
        hideAction();
      }
      return;
    }
    applySelectionDetails(details);
  }

  function selectionShortcutButton(key) {
    if (key === "c") return selectionCopyButton;
    if (key === "r") return readButton;
    if (key === "t") return translateButton;
    if (key === "n") return noteButton;
    if (key === "h") return highlightButton;
    return null;
  }

  function handleSelectionShortcut(event) {
    if (
      event.defaultPrevented ||
      event.repeat ||
      event.isComposing ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey
    ) {
      return;
    }
    var button = selectionShortcutButton(event.key.toLowerCase());
    if (!button) return;
    if (
      event.target &&
      event.target.closest &&
      event.target.closest(
        "input, textarea, select, button, a, [contenteditable='true']"
      )
    ) {
      return;
    }
    if (
      !panel.classList.contains("hidden") ||
      (notePanel && !notePanel.classList.contains("hidden"))
    ) {
      return;
    }
    var details = selectionDetails();
    if (!details) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    applySelectionDetails(details);
    if (!button.hidden && !button.disabled) button.click();
  }

  function scheduleSelectionAction(delay) {
    window.clearTimeout(selectionTimer);
    selectionTimer = window.setTimeout(updateSelectionAction, delay);
  }

  function setReadButton(label, isReading) {
    if (!readButton || !readLabel) return;
    window.clearTimeout(readResetTimer);
    readLabel.textContent = label;
    readButton.classList.toggle("is-reading", isReading);
    readButton.setAttribute("aria-pressed", isReading ? "true" : "false");
    readButton.setAttribute(
      "aria-label",
      isReading
        ? "Stop reading selected text"
        : "Read selected text in French"
    );
  }

  function resetReadButton() {
    setReadButton("Read", false);
  }

  function stopReading(cancelSpeech) {
    if (!readButton) return;
    var wasReading = reading;
    reading = false;
    readingNumber += 1;
    readingChunks = [];
    readingIndex = 0;
    if (
      wasReading &&
      cancelSpeech !== false &&
      frenchSpeech &&
      frenchSpeech.supported
    ) {
      frenchSpeech.synthesis.cancel();
      frenchSpeech.synthesis.resume();
    }
    resetReadButton();
  }

  function finishReading() {
    reading = false;
    readingChunks = [];
    readingIndex = 0;
    setReadButton("Read again", false);
  }

  function showReadError() {
    reading = false;
    readingChunks = [];
    readingIndex = 0;
    setReadButton("Unavailable", false);
    readResetTimer = window.setTimeout(resetReadButton, 1800);
  }

  function speakNextChunk(number) {
    if (!reading || number !== readingNumber) return;
    if (readingIndex >= readingChunks.length) {
      finishReading();
      return;
    }

    var utterance = new frenchSpeech.Utterance(readingChunks[readingIndex]);
    var voice = frenchSpeech.preferredVoice();
    utterance.lang = "fr-FR";
    utterance.rate = 0.92;
    utterance.pitch = 1;
    if (voice) utterance.voice = voice;
    utterance.onend = function () {
      if (!reading || number !== readingNumber) return;
      readingIndex += 1;
      speakNextChunk(number);
    };
    utterance.onerror = function () {
      if (!reading || number !== readingNumber) return;
      showReadError();
    };
    frenchSpeech.synthesis.speak(utterance);
  }

  function startReading() {
    if (!selectedText || !frenchSpeech || !frenchSpeech.supported) return;
    frenchSpeech.refreshVoices();
    var chunks = frenchSpeech.chunks(selectedText);
    if (!chunks.length) return;

    document.dispatchEvent(new CustomEvent("heureux:speech-start", {
      detail: { source: "selection-toolbar" }
    }));
    frenchSpeech.synthesis.resume();
    readingNumber += 1;
    reading = true;
    readingChunks = chunks;
    readingIndex = 0;
    setReadButton("Stop", true);
    var currentReading = readingNumber;
    speakNextChunk(currentReading);
  }

  function updateReadVoiceTitle() {
    if (!readButton || !frenchSpeech || !frenchSpeech.supported) return;
    var voice = frenchSpeech.preferredVoice();
    readButton.title = voice
      ? "French voice: " + voice.name + " · Shortcut: R"
      : "Read with the best French voice available · Shortcut: R";
  }

  function googleTranslateUrl(text) {
    var url = new URL("https://translate.google.com/");
    url.searchParams.set("sl", "fr");
    url.searchParams.set("tl", "en");
    url.searchParams.set("text", text);
    url.searchParams.set("op", "translate");
    return url.toString();
  }

  function setStatus(message, loading) {
    statusElement.textContent = message;
    spinner.classList.toggle("hidden", !loading);
  }

  function positionPanel(rect) {
    panel.classList.remove("hidden");
    if (mobilePanelQuery.matches) {
      panel.style.left = "";
      panel.style.top = "";
      return;
    }

    panel.style.left = "0";
    panel.style.top = "0";
    var panelRect = panel.getBoundingClientRect();
    var bounds = viewportBounds();
    var inset = 12;
    var left = rect.left + (rect.width - panelRect.width) / 2;
    var maxLeft = Math.max(
      bounds.left + inset,
      bounds.right - panelRect.width - inset
    );
    left = Math.max(bounds.left + inset, Math.min(left, maxLeft));
    var top = rect.bottom + 10;
    var maximumTop = Math.max(
      bounds.top + inset,
      bounds.bottom - panelRect.height - inset
    );
    if (top > maximumTop) {
      top = rect.top - panelRect.height - 10;
    }
    top = Math.max(bounds.top + inset, Math.min(top, maximumTop));
    panel.style.left = Math.round(left) + "px";
    panel.style.top = Math.round(top) + "px";
  }

  function repositionPanel() {
    if (!selectedRect || panel.classList.contains("hidden")) return;
    window.requestAnimationFrame(function () {
      positionPanel(currentSelectionRect());
    });
  }

  function repositionOpenUi() {
    if (viewportFrame) return;
    viewportFrame = window.requestAnimationFrame(function () {
      viewportFrame = null;
      var rect = currentSelectionRect();
      if (!rect) return;
      if (!action.classList.contains("hidden")) positionAction(rect);
      if (!panel.classList.contains("hidden")) positionPanel(rect);
    });
  }

  function pointerNearSelection(event) {
    var selection = window.getSelection();
    var rect = currentSelectionRect();
    if (!selection || selection.isCollapsed || !rect) return false;
    var padding = event.pointerType === "pen" ? 30 : 20;
    return (
      event.clientX >= rect.left - padding &&
      event.clientX <= rect.right + padding &&
      event.clientY >= rect.top - padding &&
      event.clientY <= rect.bottom + padding
    );
  }

  function armSelectionPointerWatchdog() {
    window.clearTimeout(selectionPointerTimer);
    selectionPointerTimer = window.setTimeout(function () {
      selectionPointerId = null;
      scheduleSelectionAction(30);
    }, 2500);
  }

  function startSelectionPointer(event) {
    selectionPointerId = event.pointerId;
    armSelectionPointerWatchdog();
  }

  function releaseSelectionPointer(event, delay) {
    if (selectionPointerId !== null && event.pointerId !== selectionPointerId) {
      return false;
    }
    selectionPointerId = null;
    window.clearTimeout(selectionPointerTimer);
    scheduleSelectionAction(delay);
    return true;
  }

  function resetNoteButton() {
    if (!translationNoteButton) return;
    translationNoteButton.classList.add("hidden");
    translationNoteButton.classList.remove("is-busy");
    translationNoteButton.disabled = false;
    if (translationNoteLabel) {
      translationNoteLabel.textContent = "Add to note and highlight";
    }
  }

  function closePanel() {
    requestNumber += 1;
    panel.classList.add("hidden");
    copyButton.classList.add("hidden");
    copyLabel.textContent = "Copy";
    setSpriteIcon(copyIcon, "copy");
    resetNoteButton();
  }

  function showFallback(message) {
    setStatus(message, false);
    fallbackLabel.textContent = "Open Google Translate";
    fallbackLabel.classList.remove("sr-only");
    fallbackLink.classList.add("is-suggested");
    fallbackLink.setAttribute("title", "Open Google Translate");
    fallbackLink.setAttribute("aria-label", "Open Google Translate");
    repositionPanel();
  }

  function updateDownloadProgress(event) {
    if (panel.classList.contains("hidden")) return;
    var loaded = Number(event.loaded) || 0;
    var total = Number(event.total) || 0;
    var fraction = total > 0 ? loaded / total : loaded;
    var percent = Math.max(0, Math.min(100, Math.round(fraction * 100)));
    setStatus("Downloading the local French–English model · " + percent + "%", true);
  }

  function getTranslator() {
    if (
      !window.Translator ||
      typeof window.Translator.create !== "function"
    ) {
      return null;
    }
    if (translatorPromise) return translatorPromise;

    try {
      translatorPromise = Promise.resolve(
        window.Translator.create({
          sourceLanguage: translatorOptions.sourceLanguage,
          targetLanguage: translatorOptions.targetLanguage,
          monitor: function (monitor) {
            monitor.addEventListener("downloadprogress", updateDownloadProgress);
          }
        })
      )
        .then(function (translator) {
          translatorInstance = translator;
          return translator;
        })
        .catch(function (error) {
          translatorPromise = null;
          throw error;
        });
    } catch (error) {
      translatorPromise = null;
      return Promise.reject(error);
    }
    return translatorPromise;
  }

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function remoteTranslate(text) {
    var endpoint = panel.dataset.translationEndpoint;
    if (!endpoint) return Promise.reject(new Error("no endpoint"));
    var body = new FormData();
    body.set("text", text);
    return fetch(endpoint, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "fetch"
      },
      body: body,
      credentials: "same-origin"
    })
      .then(function (response) {
        if (!response.ok) throw new Error("translation unavailable");
        return response.json();
      })
      .then(function (payload) {
        var translation = (payload && payload.translation) || "";
        if (!translation) throw new Error("translation unavailable");
        return translation;
      });
  }

  var MOBILE_FALLBACK_MESSAGE =
    "On-device translation isn't available in this browser.";

  function translateOnServer(text, requestId, fallbackMessage) {
    setStatus("Translating…", true);
    remoteTranslate(text)
      .then(function (translation) {
        if (requestId !== requestNumber) return;
        showTranslation(translation, "Translated on the server.");
      })
      .catch(function () {
        if (requestId !== requestNumber) return;
        showFallback(fallbackMessage);
      });
  }

  function showTranslation(translation, status) {
    resultElement.textContent = translation;
    output.classList.remove("hidden");
    copyButton.classList.remove("hidden");
    if (translationNoteButton && window.HeureuxNotes) {
      translationNoteButton.classList.remove("hidden");
      translationNoteButton.disabled = false;
    }
    setStatus(status || "Translated locally on this device.", false);
    repositionPanel();
  }

  function saveTranslationNote() {
    if (!translationNoteButton || translationNoteButton.disabled) return;
    var quote = sourceElement.textContent;
    var body = resultElement.textContent;
    if (!quote || !body || !window.HeureuxNotes) return;
    translationNoteButton.disabled = true;
    translationNoteButton.classList.add("is-busy");
    if (translationNoteLabel) translationNoteLabel.textContent = "Saving…";
    window.HeureuxNotes.saveSelectionNote(quote, body, true)
      .then(function () {
        closePanel();
      })
      .catch(function (error) {
        setStatus(error.message, false);
        translationNoteButton.disabled = false;
        translationNoteButton.classList.remove("is-busy");
        if (translationNoteLabel) {
          translationNoteLabel.textContent = "Add to note and highlight";
        }
      });
  }

  function writeClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }

    var textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    var copied = document.execCommand("copy");
    textarea.remove();
    return copied
      ? Promise.resolve()
      : Promise.reject(new Error("Copy failed"));
  }

  if (readButton) {
    if (!readLabel || !frenchSpeech || !frenchSpeech.supported) {
      readButton.hidden = true;
    } else {
      resetReadButton();
      updateReadVoiceTitle();
      if (frenchSpeech.synthesis.addEventListener) {
        frenchSpeech.synthesis.addEventListener(
          "voiceschanged",
          updateReadVoiceTitle
        );
      }
      readButton.addEventListener("click", function () {
        if (reading) stopReading();
        else startReading();
      });
    }
  }
  document.addEventListener("heureux:speech-start", function (event) {
    if (
      reading &&
      (!event.detail || event.detail.source !== "selection-toolbar")
    ) {
      stopReading(false);
    }
  });

  action.addEventListener("pointerover", function (event) {
    if (event.pointerType !== "pen") return;
    var button = event.target.closest(".selection-translate__button");
    if (button && action.contains(button)) setPenHoveredButton(button);
  });
  action.addEventListener("pointerout", function (event) {
    if (event.pointerType !== "pen" || !penHoveredButton) return;
    if (event.relatedTarget && penHoveredButton.contains(event.relatedTarget)) {
      return;
    }
    setPenHoveredButton(null);
  });
  action.querySelectorAll("button").forEach(function (button) {
    button.addEventListener("pointerdown", function (event) {
      toolbarSelectionPinned = true;
      event.preventDefault();
    });
    button.addEventListener("click", function () {
      toolbarSelectionPinned = true;
    });
  });

  selectionCopyButton.addEventListener("click", function () {
    if (!selectedText) return;
    window.clearTimeout(selectionCopyTimer);
    writeClipboard(selectedText)
      .then(function () {
        selectionCopyButton.classList.add("is-copied");
        selectionCopyLabel.textContent = "Copied";
        setSpriteIcon(selectionCopyIcon, "check");
        selectionCopyTimer = window.setTimeout(function () {
          selectionCopyButton.classList.remove("is-copied");
          selectionCopyLabel.textContent = "Copy";
          setSpriteIcon(selectionCopyIcon, "copy");
        }, 1600);
      })
      .catch(function () {
        selectionCopyButton.classList.remove("is-copied");
        selectionCopyLabel.textContent = "Copy failed";
        setSpriteIcon(selectionCopyIcon, "copy");
        selectionCopyTimer = window.setTimeout(function () {
          selectionCopyLabel.textContent = "Copy";
        }, 1600);
      });
  });

  translateButton.addEventListener("click", function () {
    if (!selectedText || !selectedRect) return;
    if (reading) stopReading();
    var text = selectedText;
    var rect = selectedRect;
    var currentRequest = ++requestNumber;
    var localTranslation = text.length <= maxLocalLength
      ? getTranslator()
      : null;

    sourceElement.textContent = text;
    resultElement.textContent = "";
    output.classList.add("hidden");
    copyButton.classList.add("hidden");
    resetNoteButton();
    copyLabel.textContent = "Copy";
    setSpriteIcon(copyIcon, "copy");
    fallbackLink.href = googleTranslateUrl(text);
    fallbackLabel.textContent = "Google Translate";
    fallbackLabel.classList.add("sr-only");
    fallbackLink.classList.remove("is-suggested");
    fallbackLink.setAttribute("title", "Google Translate");
    fallbackLink.setAttribute("aria-label", "Google Translate");
    positionPanel(rect);
    panel.focus({ preventScroll: true });

    if (text.length > maxLocalLength) {
      showFallback("Select a shorter passage for local translation (maximum 2,000 characters).");
      return;
    }
    if (!localTranslation) {
      translateOnServer(text, currentRequest, MOBILE_FALLBACK_MESSAGE);
      return;
    }

    setStatus("Preparing local translation…", true);
    localTranslation
      .then(function (translator) {
        return translator.translate(text);
      })
      .then(function (translation) {
        if (currentRequest !== requestNumber) return;
        showTranslation(translation, "Translated locally on this device.");
      })
      .catch(function () {
        if (currentRequest !== requestNumber) return;
        translateOnServer(text, currentRequest, MOBILE_FALLBACK_MESSAGE);
      });
  });

  copyButton.addEventListener("click", function () {
    var text = resultElement.textContent;
    if (!text) return;

    writeClipboard(text)
      .then(function () {
        copyLabel.textContent = "Copied";
        copyButton.classList.add("is-done");
        copyButton.setAttribute("title", "Copied");
        setSpriteIcon(copyIcon, "check");
        window.setTimeout(function () {
          copyLabel.textContent = "Copy";
          copyButton.classList.remove("is-done");
          copyButton.setAttribute("title", "Copy translation");
          setSpriteIcon(copyIcon, "copy");
        }, 1600);
      })
      .catch(function () {
        setStatus("Copy failed. Select the translation and copy it manually.", false);
      });
  });

  if (translationNoteButton) {
    translationNoteButton.addEventListener("click", saveTranslationNote);
  }
  closeButtons.forEach(function (button) {
    button.addEventListener("click", closePanel);
  });
  document.addEventListener("selectionchange", function () {
    if (selectionPointerId === null) scheduleSelectionAction(80);
  });
  document.addEventListener("pointerup", function (event) {
    rememberPointerInput(event);
    if (penCursor && event.pointerType === "pen") {
      penCursor.classList.remove("is-pressed");
    }
    releaseSelectionPointer(event, event.pointerType === "pen" ? 20 : 30);
  });
  document.addEventListener("pointercancel", function (event) {
    releaseSelectionPointer(event, event.pointerType === "pen" ? 30 : 80);
    if (event.pointerType === "pen") {
      if (penCursor) penCursor.classList.remove("is-pressed");
      schedulePenCursorHide();
    }
  });
  document.addEventListener("lostpointercapture", function (event) {
    releaseSelectionPointer(event, 30);
  });
  document.addEventListener("keyup", function (event) {
    if (event.key === "Shift" || event.shiftKey) scheduleSelectionAction(30);
  });
  document.addEventListener("pointerdown", function (event) {
    rememberPointerInput(event);
    var outsideAction = !action.contains(event.target);
    var outsideTranslation = !panel.contains(event.target);
    var outsideNote = !notePanel || !notePanel.contains(event.target);
    if (outsideAction) toolbarSelectionPinned = false;
    if (
      event.isPrimary !== false &&
      selectablePointerTarget(event.target)
    ) {
      startSelectionPointer(event);
    }
    if (
      !panel.classList.contains("hidden") &&
      outsideTranslation &&
      outsideAction
    ) {
      closePanel();
    }
    if (
      !action.classList.contains("hidden") &&
      outsideAction &&
      outsideTranslation &&
      outsideNote &&
      !pointerNearSelection(event)
    ) {
      hideAction();
    }
  });
  document.addEventListener("pointerover", rememberPointerInput, {
    passive: true
  });
  document.addEventListener("pointermove", function (event) {
    if (event.pointerType === "pen") showPenCursor(event);
    if (event.pointerId === selectionPointerId) {
      armSelectionPointerWatchdog();
    }
  }, { passive: true });
  document.addEventListener("pointerout", function (event) {
    if (event.pointerType === "pen" && !event.relatedTarget) {
      schedulePenCursorHide();
    }
  }, { passive: true });
  document.addEventListener("pointerdown", function (event) {
    if (penCursor && event.pointerType === "pen") {
      showPenCursor(event);
      penCursor.classList.add("is-pressed");
    }
  }, { passive: true });
  window.addEventListener("resize", function () {
    penActionSize = null;
    repositionOpenUi();
  });
  window.addEventListener("scroll", repositionOpenUi, { passive: true });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", repositionOpenUi);
    window.visualViewport.addEventListener("scroll", repositionOpenUi, {
      passive: true
    });
  }
  window.addEventListener("blur", function () {
    selectionPointerId = null;
    window.clearTimeout(selectionPointerTimer);
    hidePenCursorNow();
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) hidePenCursorNow();
  });
  document.addEventListener("keydown", handleSelectionShortcut, true);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && reading) stopReading();
    if (event.key === "Escape" && !panel.classList.contains("hidden")) {
      closePanel();
    }
  });
  window.addEventListener("pagehide", function () {
    stopReading();
    hidePenCursorNow();
    if (translatorInstance && typeof translatorInstance.destroy === "function") {
      translatorInstance.destroy();
    }
  });
})();
