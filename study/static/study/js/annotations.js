/* Private notes and persistent highlights for selected study text. */
(function () {
  "use strict";

  var main = document.getElementById("main");
  var action = document.querySelector("[data-selection-translate]");
  var noteButton = document.querySelector("[data-note-selection]");
  var highlightButton = document.querySelector("[data-highlight-selection]");
  var highlightLabel = highlightButton
    ? highlightButton.querySelector(".selection-translate__label")
    : null;
  var notePanel = document.querySelector("[data-note-panel]");
  var sourceUrl = document.body.dataset.annotationSourceUrl;
  var createUrl = document.body.dataset.annotationCreateUrl;
  if (
    !main ||
    !action ||
    !noteButton ||
    !highlightButton ||
    !highlightLabel ||
    !notePanel ||
    !sourceUrl ||
    !createUrl
  ) {
    return;
  }

  var noteSource = notePanel.querySelector("[data-note-source]");
  var noteBody = notePanel.querySelector("[data-note-body]");
  var notePaste = notePanel.querySelector("[data-note-paste]");
  var noteStatus = notePanel.querySelector("[data-note-status]");
  var noteSaveClose = notePanel.querySelector("[data-note-save-close]");
  var notePasteClose = notePanel.querySelector("[data-note-paste-close]");
  var noteCloseButtons = notePanel.querySelectorAll(
    "[data-note-close], [data-note-cancel]"
  );
  if (
    !noteSource ||
    !noteBody ||
    !noteStatus ||
    !noteSaveClose ||
    !notePasteClose
  ) {
    return;
  }
  var toast = document.querySelector("[data-annotation-toast]");
  var sourcePath = window.location.pathname + window.location.search;
  var currentSelection = null;
  var noteSelection = null;
  var highlights = [];
  var toastTimer = null;
  var mutationTimer = null;
  var annotationReadButtons = Array.from(
    document.querySelectorAll("[data-annotation-read]")
  );
  var frenchSpeech = window.HeureuxFrenchSpeech;
  var activeReadId = "";
  var annotationReadNumber = 0;
  var annotationReadChunks = [];
  var annotationReadIndex = 0;

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function selectionElement(range) {
    var node = range.commonAncestorContainer;
    return node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
  }

  function rootForNode(node) {
    var element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    return element ? element.closest("[data-annotation-root]") : null;
  }

  function captureSelection() {
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      return null;
    }
    var range = selection.getRangeAt(0);
    var element = selectionElement(range);
    var startRoot = rootForNode(range.startContainer);
    var endRoot = rootForNode(range.endContainer);
    if (startRoot !== endRoot) return null;
    var root = startRoot || main;
    if (
      !element ||
      !main.contains(element) ||
      element.closest(
        "button, input, textarea, select, [contenteditable='true'], " +
        "[data-translation-panel], [data-note-panel]"
      )
    ) {
      return null;
    }
    var quote = range.cloneContents().textContent || "";
    if (!quote.trim()) return null;

    var before = range.cloneRange();
    before.selectNodeContents(root);
    before.setEnd(range.startContainer, range.startOffset);
    var start = (before.cloneContents().textContent || "").length;
    var end = start + quote.length;
    var pageText = root.textContent || "";
    var coverage = highlightCoverage(root, start, end);
    var highlightStart = Math.min(start, coverage.start);
    var highlightEnd = Math.max(end, coverage.end);
    return {
      quote: quote,
      start: start,
      end: end,
      prefix: pageText.slice(Math.max(0, start - 160), start),
      suffix: pageText.slice(end, end + 160),
      fullyHighlighted: coverage.fullyHighlighted,
      highlightIds: coverage.ids,
      highlightRevisions: coverage.revisions,
      highlight: {
        quote: pageText.slice(highlightStart, highlightEnd),
        start: highlightStart,
        end: highlightEnd,
        prefix: pageText.slice(Math.max(0, highlightStart - 160), highlightStart),
        suffix: pageText.slice(highlightEnd, highlightEnd + 160)
      },
      sourceKey: root.dataset.annotationSourceKey || ""
    };
  }

  function updateHighlightButton(details) {
    var shouldRemove = Boolean(details && details.fullyHighlighted);
    highlightLabel.textContent = shouldRemove ? "Unhighlight" : "Highlight";
    highlightButton.setAttribute(
      "aria-label",
      shouldRemove ? "Unhighlight selected text" : "Highlight selected text"
    );
  }

  function rememberSelection() {
    var details = captureSelection();
    if (details) {
      currentSelection = details;
      updateHighlightButton(details);
    }
  }

  function showToast(message) {
    if (!toast) return;
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.remove("hidden");
    toastTimer = window.setTimeout(function () {
      toast.classList.add("hidden");
    }, 2200);
  }

  function readJson(response) {
    if (response.redirected) {
      return Promise.reject(
        new Error("Votre session a expiré. Reconnectez-vous.")
      );
    }
    var contentType = response.headers.get("Content-Type") || "";
    if (contentType.indexOf("application/json") === -1) {
      return Promise.reject(
        new Error("La réponse du serveur est inattendue.")
      );
    }
    return response.json().catch(function () {
      throw new Error("La réponse du serveur est invalide.");
    }).then(function (data) {
      if (!response.ok) {
        var error = new Error(data.error || "L'enregistrement a échoué.");
        error.status = response.status;
        throw error;
      }
      return data;
    });
  }

  function announceWritingSujetProgress(data) {
    if (!data || !data.writing_sujet_progress) return;
    document.dispatchEvent(new CustomEvent("heureux:writing-sujet-progress", {
      detail: data.writing_sujet_progress
    }));
  }

  function annotationBody(kind, details, body) {
    var selected = kind === "highlight" ? details.highlight : details;
    var values = new URLSearchParams();
    values.set("kind", kind);
    values.set("quote", selected.quote);
    values.set("start_offset", selected.start);
    values.set("end_offset", selected.end);
    values.set("prefix", selected.prefix);
    values.set("suffix", selected.suffix);
    values.set("source_path", sourcePath);
    values.set("source_key", details.sourceKey || "");
    values.set("source_title", document.title);
    values.set("body", body || "");
    if (kind === "highlight") {
      values.set("overlap_ids", details.highlightIds.join(","));
      values.set(
        "overlap_revisions",
        JSON.stringify(details.highlightRevisions)
      );
    }
    var taskId = document.body.dataset.annotationTaskId;
    if (taskId) values.set("task_id", taskId);
    return values;
  }

  function createAnnotation(kind, details, body) {
    return fetch(createUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "fetch",
        "Content-Type": "application/x-www-form-urlencoded"
      },
      body: annotationBody(kind, details, body).toString()
    }).then(readJson);
  }

  function resetNoteFormState() {
    noteSaveClose.disabled = false;
    notePasteClose.disabled = false;
    noteBody.readOnly = false;
    if (notePaste) notePaste.disabled = false;
  }

  function closeNotePanel() {
    notePanel.classList.add("hidden");
    noteStatus.textContent = "";
    resetNoteFormState();
    noteSelection = null;
  }

  function openNotePanel() {
    rememberSelection();
    if (!currentSelection) return;
    noteSelection = currentSelection;
    noteSource.textContent = noteSelection.quote;
    noteBody.value = "";
    noteStatus.textContent = "";
    resetNoteFormState();
    notePanel.classList.remove("hidden");
    notePanel.focus({ preventScroll: true });
    window.setTimeout(function () {
      noteBody.focus({ preventScroll: true });
    }, 0);
  }

  function insertIntoNote(text) {
    var start = noteBody.selectionStart;
    var end = noteBody.selectionEnd;
    var retainedLength = noteBody.value.length - (end - start);
    var available = Math.max(noteBody.maxLength - retainedLength, 0);
    var insertion = text.slice(0, available);
    if (!insertion) return 0;
    noteBody.value =
      noteBody.value.slice(0, start)
      + insertion
      + noteBody.value.slice(end);
    var cursor = start + insertion.length;
    noteBody.setSelectionRange(cursor, cursor);
    noteBody.dispatchEvent(new Event("input", { bubbles: true }));
    return insertion.length;
  }

  // Resolves to true only when clipboard text actually landed in the note,
  // so « Coller et fermer » never saves an unchanged note by surprise.
  function readClipboardIntoNote() {
    if (!navigator.clipboard || !navigator.clipboard.readText) {
      noteStatus.textContent =
        "Collage automatique indisponible. Utilisez ⌘V ou Ctrl+V.";
      return Promise.resolve(false);
    }
    noteStatus.textContent = "Lecture du presse-papiers…";
    return navigator.clipboard.readText()
      .then(function (text) {
        if (!text) {
          noteStatus.textContent = "Le presse-papiers est vide.";
          return false;
        }
        var inserted = insertIntoNote(text);
        if (!inserted) {
          noteStatus.textContent = "La note a atteint sa longueur maximale.";
          return false;
        }
        noteStatus.textContent = inserted < text.length
          ? "Texte collé jusqu'à la limite de la note."
          : "Texte collé.";
        return true;
      })
      .catch(function () {
        noteStatus.textContent =
          "Impossible d'accéder au presse-papiers. Utilisez ⌘V ou Ctrl+V.";
        return false;
      });
  }

  function pasteNote() {
    if (!notePaste || notePaste.disabled) return;
    notePaste.disabled = true;
    readClipboardIntoNote().then(function () {
      notePaste.disabled = false;
      noteBody.focus({ preventScroll: true });
    });
  }

  function pasteAndCloseNote() {
    if (!noteSelection || notePasteClose.disabled) return;
    notePasteClose.disabled = true;
    noteSaveClose.disabled = true;
    if (notePaste) notePaste.disabled = true;
    readClipboardIntoNote().then(function (pasted) {
      resetNoteFormState();
      if (!pasted) {
        noteBody.focus({ preventScroll: true });
        return;
      }
      saveNote();
    });
  }

  function saveNote() {
    if (!noteSelection || noteSaveClose.disabled) return;
    noteSaveClose.disabled = true;
    notePasteClose.disabled = true;
    noteBody.readOnly = true;
    if (notePaste) notePaste.disabled = true;
    noteStatus.textContent = "Enregistrement…";
    createAnnotation("note", noteSelection, noteBody.value)
      .then(function () {
        closeNotePanel();
        showToast("Note enregistrée.");
      })
      .catch(function (error) {
        resetNoteFormState();
        noteStatus.textContent = error.message;
      });
  }

  function normalizedContext(value) {
    return (value || "").replace(/\s+/g, " ").trim();
  }

  function commonPrefixLength(left, right) {
    var limit = Math.min(left.length, right.length);
    var index = 0;
    while (index < limit && left[index] === right[index]) index += 1;
    return index;
  }

  function commonSuffixLength(left, right) {
    var limit = Math.min(left.length, right.length);
    var count = 0;
    while (
      count < limit &&
      left[left.length - count - 1] === right[right.length - count - 1]
    ) {
      count += 1;
    }
    return count;
  }

  function normalizedTextMap(value) {
    var normalized = "";
    var starts = [];
    var ends = [];
    var whitespaceStart = -1;
    for (var index = 0; index < value.length; index += 1) {
      if (/\s/.test(value[index])) {
        if (normalized && whitespaceStart === -1) {
          whitespaceStart = index;
        }
        continue;
      }
      if (whitespaceStart !== -1) {
        normalized += " ";
        starts.push(whitespaceStart);
        ends.push(index);
        whitespaceStart = -1;
      }
      normalized += value[index];
      starts.push(index);
      ends.push(index + 1);
    }
    return {
      text: normalized,
      starts: starts,
      ends: ends
    };
  }

  function bestOffsets(item, root) {
    var text = root.textContent || "";
    var savedPrefix = normalizedContext(item.prefix);
    var savedSuffix = normalizedContext(item.suffix);
    var candidates = [];
    var candidateKeys = {};
    function addCandidate(start, end) {
      var key = start + ":" + end;
      if (candidateKeys[key]) return;
      candidateKeys[key] = true;
      candidates.push({ start: start, end: end });
    }

    var exactIndex = text.indexOf(item.quote);
    while (exactIndex !== -1) {
      addCandidate(exactIndex, exactIndex + item.quote.length);
      exactIndex = text.indexOf(item.quote, exactIndex + 1);
    }

    var normalizedQuote = normalizedContext(item.quote);
    if (normalizedQuote) {
      var mappedText = normalizedTextMap(text);
      var normalizedIndex = mappedText.text.indexOf(normalizedQuote);
      while (normalizedIndex !== -1) {
        var normalizedEnd = normalizedIndex + normalizedQuote.length;
        addCandidate(
          mappedText.starts[normalizedIndex],
          mappedText.ends[normalizedEnd - 1]
        );
        normalizedIndex = mappedText.text.indexOf(
          normalizedQuote,
          normalizedIndex + 1
        );
      }
    }

    var best = null;
    candidates.forEach(function (candidate) {
      var index = candidate.start;
      var end = candidate.end;
      var score = -Math.min(
        Math.abs(index - item.start_offset) / 10000,
        1
      );
      var currentPrefix = normalizedContext(
        text.slice(Math.max(0, index - 400), index)
      );
      var prefixMatch = commonSuffixLength(
        currentPrefix,
        savedPrefix
      );
      if (savedPrefix && currentPrefix.endsWith(savedPrefix)) {
        score += 200 + savedPrefix.length;
      } else if (prefixMatch >= 4) {
        score += prefixMatch;
      }
      var currentSuffix = normalizedContext(
        text.slice(end, end + 400)
      );
      var suffixMatch = commonPrefixLength(
        currentSuffix,
        savedSuffix
      );
      if (savedSuffix && currentSuffix.startsWith(savedSuffix)) {
        score += 200 + savedSuffix.length;
      } else if (suffixMatch >= 4) {
        score += suffixMatch;
      }
      if (!best || score > best.score) {
        best = { start: index, end: end, score: score };
      }
    });
    return best;
  }

  function highlightCoverage(root, start, end) {
    var intervals = [];
    highlights.forEach(function (item) {
      if (highlightRoot(item) !== root) return;
      var offsets = bestOffsets(item, root);
      if (!offsets || offsets.end <= start || offsets.start >= end) return;
      intervals.push({
        id: item.id,
        revision: item.revision,
        start: Math.max(start, offsets.start),
        end: Math.min(end, offsets.end),
        originalStart: offsets.start,
        originalEnd: offsets.end
      });
    });
    intervals.sort(function (left, right) {
      return left.start - right.start || right.end - left.end;
    });

    var coveredUntil = start;
    var hasGap = false;
    var ids = [];
    var revisions = {};
    intervals.forEach(function (interval) {
      if (interval.start > coveredUntil) hasGap = true;
      coveredUntil = Math.max(coveredUntil, interval.end);
      if (ids.indexOf(interval.id) === -1) {
        ids.push(interval.id);
        revisions[String(interval.id)] = interval.revision;
      }
    });
    return {
      ids: ids,
      revisions: revisions,
      fullyHighlighted: intervals.length > 0 && !hasGap && coveredUntil >= end,
      start: intervals.reduce(function (minimum, interval) {
        return Math.min(minimum, interval.originalStart);
      }, start),
      end: intervals.reduce(function (maximum, interval) {
        return Math.max(maximum, interval.originalEnd);
      }, end)
    };
  }

  function textSegments(root, start, end, includeNestedRoots) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var segments = [];
    var offset = 0;
    var node;
    while ((node = walker.nextNode())) {
      var nodeStart = offset;
      var nodeEnd = offset + node.data.length;
      if (nodeEnd > start && nodeStart < end) {
        var parent = node.parentElement;
        var segmentStart = Math.max(0, start - nodeStart);
        var segmentEnd = Math.min(node.data.length, end - nodeStart);
        if (
          parent &&
          node.data.slice(segmentStart, segmentEnd).trim() &&
          !(
            root === main &&
            !includeNestedRoots &&
            parent.closest("[data-annotation-root]")
          ) &&
          !parent.closest(
            "script, style, button, textarea, select, option, " +
            "[data-user-highlight]"
          )
        ) {
          segments.push({
            node: node,
            start: segmentStart,
            end: segmentEnd
          });
        }
      }
      offset = nodeEnd;
      if (offset >= end) break;
    }
    return segments;
  }

  function wrapSegment(segment, highlightId) {
    var node = segment.node;
    if (!node.parentNode || segment.start >= segment.end) return;
    if (segment.end < node.data.length) node.splitText(segment.end);
    var selected = segment.start > 0 ? node.splitText(segment.start) : node;
    var mark = document.createElement("mark");
    mark.className = "user-highlight";
    mark.dataset.userHighlight = highlightId;
    mark.dataset.highlightId = highlightId;
    selected.parentNode.insertBefore(mark, selected);
    mark.appendChild(selected);
  }

  function highlightRoot(item) {
    if (!item.source_key) {
      var legacyMark = main.querySelector(
        '[data-highlight-id="' + String(item.id).replace(/"/g, "") + '"]'
      );
      return legacyMark
        ? legacyMark.closest("[data-annotation-root]") || main
        : main;
    }
    var roots = main.querySelectorAll(
      "[data-annotation-root][data-annotation-source-key]"
    );
    for (var index = 0; index < roots.length; index += 1) {
      if (roots[index].dataset.annotationSourceKey === item.source_key) {
        return roots[index];
      }
    }
    return null;
  }

  function applyHighlight(item) {
    var root = highlightRoot(item);
    if (!root) return false;
    if (
      root.querySelector(
        '[data-highlight-id="' + String(item.id).replace(/"/g, "") + '"]'
      )
    ) {
      return true;
    }
    var offsets = bestOffsets(item, root);
    if (!offsets) return false;
    var segments = textSegments(
      root,
      offsets.start,
      offsets.end,
      !item.source_key
    );
    if (!segments.length) return false;
    segments.reverse().forEach(function (segment) {
      wrapSegment(segment, item.id);
    });
    return true;
  }

  function applySavedHighlights() {
    highlights.forEach(applyHighlight);
  }

  function removeHighlightMarks(ids) {
    var selectedIds = ids.map(String);
    Array.from(main.querySelectorAll("[data-highlight-id]")).forEach(
      function (mark) {
        if (selectedIds.indexOf(mark.dataset.highlightId) === -1) return;
        var parent = mark.parentNode;
        if (!parent) return;
        while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
        parent.removeChild(mark);
        parent.normalize();
      }
    );
  }

  function replaceSavedHighlights(items) {
    removeHighlightMarks(
      Array.from(main.querySelectorAll("[data-highlight-id]")).map(function (mark) {
        return mark.dataset.highlightId;
      })
    );
    highlights = items;
    applySavedHighlights();
    rememberSelection();
  }

  function fetchHighlights() {
    var url = new URL(sourceUrl, window.location.origin);
    url.searchParams.set("source_path", sourcePath);
    fetch(url.toString(), {
      headers: { "X-Requested-With": "fetch" }
    })
      .then(readJson)
      .then(function (data) {
        replaceSavedHighlights(data.highlights || []);
      })
      .catch(function () {});
  }

  function deleteHighlight(item) {
    if (!item.delete_url) {
      return Promise.reject(new Error("Ce surlignage ne peut pas être supprimé."));
    }
    return fetch(item.delete_url, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "fetch"
      }
    }).then(readJson).then(function (data) {
      announceWritingSujetProgress(data);
      return data;
    });
  }

  function removeHighlights(details) {
    var selectedIds = details.highlightIds.map(String);
    var selectedHighlights = highlights.filter(function (item) {
      return selectedIds.indexOf(String(item.id)) !== -1;
    });
    if (!selectedHighlights.length) return;

    highlightButton.disabled = true;
    Promise.all(selectedHighlights.map(deleteHighlight))
      .then(function () {
        highlights = highlights.filter(function (item) {
          return selectedIds.indexOf(String(item.id)) === -1;
        });
        removeHighlightMarks(selectedIds);
        details.fullyHighlighted = false;
        details.highlightIds = [];
        details.highlightRevisions = [];
        currentSelection = details;
        updateHighlightButton(details);
        showToast("Surlignage supprimé.");
        highlightButton.disabled = false;
      })
      .catch(function (error) {
        showToast(error.message);
        highlightButton.disabled = false;
        fetchHighlights();
      });
  }

  function toggleHighlight() {
    rememberSelection();
    var details = currentSelection;
    if (!details) return;
    if (details.fullyHighlighted) {
      removeHighlights(details);
      return;
    }
    highlightButton.disabled = true;
    createAnnotation("highlight", details, "")
      .then(function (data) {
        announceWritingSujetProgress(data);
        var selected = details.highlight;
        var item = {
          id: data.id,
          quote: selected.quote,
          start_offset: selected.start,
          end_offset: selected.end,
          prefix: selected.prefix,
          suffix: selected.suffix,
          source_key: details.sourceKey || "",
          revision: data.revision,
          delete_url: data.delete_url
        };
        var removedIds = (data.removed_ids || []).map(String);
        var replacedIds = removedIds.concat(String(item.id));
        removeHighlightMarks(replacedIds);
        highlights = highlights.filter(function (saved) {
          return (
            saved.id !== item.id &&
            removedIds.indexOf(String(saved.id)) === -1
          );
        });
        highlights.push(item);
        applyHighlight(item);
        details.fullyHighlighted = true;
        details.highlightIds = [item.id];
        details.highlightRevisions = [item.revision];
        currentSelection = details;
        updateHighlightButton(details);
        showToast("Passage surligné.");
        highlightButton.disabled = false;
      })
      .catch(function (error) {
        showToast(error.message);
        highlightButton.disabled = false;
        if (error.status === 409) fetchHighlights();
      });
  }

  function setAnnotationReadState(id, active) {
    annotationReadButtons.forEach(function (button) {
      if (button.dataset.annotationRead !== id) return;
      var label = active
        ? "Arrêter la lecture"
        : button.dataset.annotationReadLabel;
      button.classList.toggle("is-reading", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.setAttribute("aria-label", label);
      button.setAttribute("title", active ? "Arrêter" : "Lire");
      var hiddenLabel = button.querySelector(".sr-only");
      if (hiddenLabel) hiddenLabel.textContent = label;
    });
  }

  function stopAnnotationReading(cancelSpeech) {
    var previousId = activeReadId;
    var wasReading = Boolean(previousId);
    activeReadId = "";
    annotationReadNumber += 1;
    annotationReadChunks = [];
    annotationReadIndex = 0;
    if (
      wasReading &&
      cancelSpeech !== false &&
      frenchSpeech &&
      frenchSpeech.supported
    ) {
      frenchSpeech.synthesis.cancel();
      frenchSpeech.synthesis.resume();
    }
    if (previousId) setAnnotationReadState(previousId, false);
  }

  function finishAnnotationReading() {
    var previousId = activeReadId;
    activeReadId = "";
    annotationReadChunks = [];
    annotationReadIndex = 0;
    if (previousId) setAnnotationReadState(previousId, false);
  }

  function speakNextAnnotationChunk(readNumber) {
    if (!activeReadId || readNumber !== annotationReadNumber) return;
    if (annotationReadIndex >= annotationReadChunks.length) {
      finishAnnotationReading();
      return;
    }
    var utterance = new frenchSpeech.Utterance(
      annotationReadChunks[annotationReadIndex]
    );
    var voice = frenchSpeech.preferredVoice();
    utterance.lang = "fr-FR";
    utterance.rate = 0.92;
    utterance.pitch = 1;
    if (voice) utterance.voice = voice;
    utterance.onend = function () {
      if (!activeReadId || readNumber !== annotationReadNumber) return;
      annotationReadIndex += 1;
      speakNextAnnotationChunk(readNumber);
    };
    utterance.onerror = function () {
      if (readNumber === annotationReadNumber) stopAnnotationReading();
    };
    frenchSpeech.synthesis.speak(utterance);
  }

  function toggleAnnotationReading(button) {
    var id = button.dataset.annotationRead;
    if (activeReadId === id) {
      stopAnnotationReading();
      return;
    }
    var item = button.closest("[data-annotation-item]");
    var readable = item ? item.querySelector("[data-annotation-readable]") : null;
    var chunks = readable
      ? frenchSpeech.chunks(readable.textContent || "")
      : [];
    if (!chunks.length) {
      showToast("Aucun texte à lire.");
      return;
    }

    stopAnnotationReading();
    frenchSpeech.refreshVoices();
    activeReadId = id;
    annotationReadChunks = chunks;
    annotationReadIndex = 0;
    annotationReadNumber += 1;
    var readNumber = annotationReadNumber;
    setAnnotationReadState(id, true);
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {
      detail: { source: "annotation-item" }
    }));
    frenchSpeech.synthesis.resume();
    speakNextAnnotationChunk(readNumber);
  }

  function setupAnnotationReading() {
    if (!annotationReadButtons.length) return;
    if (!frenchSpeech || !frenchSpeech.supported) {
      annotationReadButtons.forEach(function (button) {
        button.hidden = true;
      });
      return;
    }
    annotationReadButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        toggleAnnotationReading(button);
      });
    });
    document.addEventListener("heureux:speech-start", function (event) {
      if (
        activeReadId &&
        (!event.detail || event.detail.source !== "annotation-item")
      ) {
        stopAnnotationReading(false);
      }
    });
  }

  function setupStudyDeck() {
    var deck = document.querySelector("[data-annotation-study]");
    if (!deck) return;
    var cards = Array.from(deck.querySelectorAll("[data-study-card]"));
    var progress = deck.querySelector("[data-study-progress]");
    var progressBar = deck.querySelector("[data-study-progress-bar]");
    var previous = deck.querySelector("[data-study-previous]");
    var reveal = deck.querySelector("[data-study-reveal]");
    var keep = deck.querySelector("[data-study-keep]");
    var learned = deck.querySelector("[data-study-learned]");
    var restart = deck.querySelector("[data-study-restart]");
    var done = deck.querySelector("[data-study-done]");
    var controls = deck.querySelector(".annotation-study__controls");
    var summary = deck.querySelector("[data-study-summary]");
    var clearButton = deck.querySelector("[data-study-clear]");
    var clearLabel = deck.querySelector("[data-study-clear-label]");
    var knownCountEl = deck.querySelector("[data-study-known-count]");
    var orderButtons = Array.from(
      deck.querySelectorAll("[data-study-order]")
    );
    var index = 0;
    var revealed = false;
    var reverseOrder = false;
    // Decisions are held locally until the end of the run so nothing leaves
    // the « À étudier » pack mid-session; only « Je le connais » cards are
    // removed, and only when the learner confirms with the end button.
    var decisions = {};

    function cardId(card) {
      return card.getAttribute("data-study-id");
    }

    function setFlagState(button, pressed) {
      var label = pressed
        ? button.dataset.studyFlagOn
        : button.dataset.studyFlagOff;
      button.setAttribute("aria-pressed", pressed ? "true" : "false");
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      var text = button.querySelector("[data-study-flag-label]");
      if (text) text.textContent = label;
    }

    function toggleFlag(button) {
      if (button.disabled) return;
      var field = button.dataset.studyFlag;
      var next = button.getAttribute("aria-pressed") !== "true";
      var formData = new FormData();
      formData.set(field, next ? "1" : "0");
      button.disabled = true;
      fetch(button.dataset.studyFlagUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken(),
          "X-Requested-With": "fetch"
        },
        body: formData,
        credentials: "same-origin"
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("Impossible de mettre à jour cet élément.");
          }
          return response.json();
        })
        .then(function (payload) {
          var pressed = Boolean(payload[field]);
          setFlagState(button, pressed);
          showToast(
            pressed
              ? button.dataset.studyFlagToastOn
              : button.dataset.studyFlagToastOff
          );
        })
        .catch(function (error) {
          showToast(error.message);
        })
        .finally(function () {
          button.disabled = false;
        });
    }

    Array.from(deck.querySelectorAll("[data-study-flag]")).forEach(
      function (button) {
        button.addEventListener("click", function (event) {
          event.stopPropagation();
          toggleFlag(button);
        });
      }
    );

    function pluralize(count) {
      return count > 1 ? "s" : "";
    }

    function showCardFace(card, showAnswerFace) {
      var showFront = reverseOrder ? showAnswerFace : !showAnswerFace;
      card
        .querySelector("[data-study-front]")
        .classList.toggle("hidden", !showFront);
      card
        .querySelector("[data-study-back]")
        .classList.toggle("hidden", showFront);
      card.classList.toggle("is-revealed", showAnswerFace);
      var face = showFront ? "Recto" : "Verso";
      var faceLabel = card.querySelector("[data-study-face-label]");
      if (faceLabel) faceLabel.textContent = face;
      card.setAttribute(
        "aria-label",
        face + ". Appuyez pour retourner la carte."
      );
    }

    function resetCurrentCard() {
      var card = cards[index];
      if (!card) return;
      showCardFace(card, false);
      revealed = false;
      reveal.classList.remove("hidden");
      keep.classList.add("hidden");
      learned.classList.add("hidden");
    }

    function render() {
      cards.forEach(function (card, cardIndex) {
        card.classList.toggle("hidden", cardIndex !== index);
      });
      var card = cards[index];
      if (!card) return;
      resetCurrentCard();
      previous.disabled = index === 0;
      controls.classList.remove("hidden");
      done.classList.add("hidden");
      progress.textContent = String(index + 1) + " / " + String(cards.length);
      if (progressBar) {
        progressBar.style.width =
          String(((index + 1) / cards.length) * 100) + "%";
      }
    }

    function showAnswer() {
      if (revealed) return;
      var card = cards[index];
      showCardFace(card, true);
      revealed = true;
      reveal.classList.add("hidden");
      keep.classList.remove("hidden");
      learned.classList.remove("hidden");
    }

    function hideAnswer() {
      if (!revealed) return;
      var card = cards[index];
      if (!card) return;
      resetCurrentCard();
    }

    function toggleAnswer() {
      if (revealed) hideAnswer();
      else showAnswer();
    }

    function knownCards() {
      return cards.filter(function (card) {
        return decisions[cardId(card)] === "known";
      });
    }

    function showDone() {
      cards.forEach(function (card) {
        card.classList.add("hidden");
      });
      controls.classList.add("hidden");
      done.classList.remove("hidden");
      progress.textContent =
        String(cards.length) + " / " + String(cards.length);
      if (progressBar) progressBar.style.width = "100%";
      var known = knownCards().length;
      if (knownCountEl) knownCountEl.textContent = String(known);
      if (clearLabel) {
        clearLabel.textContent =
          "Retirer " +
          String(known) +
          " élément" +
          pluralize(known) +
          " connu" +
          pluralize(known);
      }
      if (clearButton) {
        clearButton.disabled = false;
        clearButton.classList.toggle("hidden", known === 0);
      }
      if (summary) {
        summary.textContent =
          known > 0
            ? "Vous avez marqué " +
              String(known) +
              " élément" +
              pluralize(known) +
              " comme connu" +
              pluralize(known) +
              "."
            : "Aucun élément marqué « Je le connais » — votre sélection reste inchangée.";
      }
    }

    function goNext() {
      if (index < cards.length - 1) {
        index += 1;
        render();
        return;
      }
      showDone();
    }

    function advance() {
      if (!revealed) return;
      goNext();
    }

    previous.addEventListener("click", function () {
      if (index > 0) {
        index -= 1;
        render();
      }
    });
    orderButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        reverseOrder = button.dataset.studyOrder === "back";
        orderButtons.forEach(function (option) {
          var active = option === button;
          option.classList.toggle("is-active", active);
          option.setAttribute("aria-pressed", active ? "true" : "false");
        });
        resetCurrentCard();
      });
    });
    reveal.addEventListener("click", showAnswer);
    cards.forEach(function (card) {
      card.addEventListener("click", function (event) {
        if (
          event.target.closest(
            "a, button, input, select, textarea, [contenteditable='true']"
          )
        ) {
          return;
        }
        var selection = window.getSelection();
        if (selection && !selection.isCollapsed) return;
        toggleAnswer();
      });
    });
    keep.addEventListener("click", function () {
      var card = cards[index];
      if (card) decisions[cardId(card)] = "keep";
      advance();
    });
    learned.addEventListener("click", function () {
      var card = cards[index];
      if (card) decisions[cardId(card)] = "known";
      advance();
    });
    if (clearButton) {
      clearButton.addEventListener("click", function () {
        var toRemove = knownCards();
        if (!toRemove.length) return;
        clearButton.disabled = true;
        if (clearLabel) clearLabel.textContent = "Retrait…";
        Promise.all(
          toRemove.map(function (card) {
            var formData = new FormData();
            formData.set("study_later", "0");
            return fetch(card.dataset.studyToggleUrl, {
              method: "POST",
              headers: {
                "X-CSRFToken": csrfToken(),
                "X-Requested-With": "fetch"
              },
              body: formData,
              credentials: "same-origin"
            }).then(function (response) {
              if (!response.ok) {
                throw new Error("Impossible de mettre à jour la sélection.");
              }
            });
          })
        )
          .then(function () {
            var removedCount = toRemove.length;
            toRemove.forEach(function (card) {
              var id = cardId(card);
              delete decisions[id];
              cards = cards.filter(function (other) {
                return other !== card;
              });
              if (card.parentNode) card.parentNode.removeChild(card);
            });
            clearButton.classList.add("hidden");
            showToast(
              String(removedCount) +
                " élément" +
                pluralize(removedCount) +
                " retiré" +
                pluralize(removedCount) +
                " de « À étudier »."
            );
            if (summary) {
              summary.textContent =
                cards.length > 0
                  ? "Retiré de « À étudier ». Il reste " +
                    String(cards.length) +
                    " élément" +
                    pluralize(cards.length) +
                    " dans votre sélection."
                  : "Votre sélection « À étudier » est maintenant vide.";
            }
            if (restart) restart.disabled = cards.length === 0;
          })
          .catch(function (error) {
            clearButton.disabled = false;
            showDone();
            showToast(error.message);
          });
      });
    }
    restart.addEventListener("click", function () {
      if (!cards.length) return;
      index = 0;
      render();
    });
    document.addEventListener("keydown", function (event) {
      var target = event.target;
      var interactive = target.closest(
        "input, textarea, select, button, a"
      );
      var deckControl = target.closest(
        "[data-study-previous], [data-study-reveal], "
        + "[data-study-keep], [data-study-learned], [data-study-order]"
      );
      var directional = event.key.indexOf("Arrow") === 0;
      if (
        (interactive && !(deckControl && directional)) ||
        done.classList.contains("hidden") === false
      ) {
        return;
      }
      if (event.key === " ") {
        event.preventDefault();
        toggleAnswer();
      } else if (
        event.key === "ArrowUp"
        || event.key === "ArrowDown"
      ) {
        event.preventDefault();
        toggleAnswer();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goNext();
      } else if (event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        index -= 1;
        render();
      }
    });
    render();
  }

  action.querySelectorAll("button").forEach(function (button) {
    button.addEventListener("pointerdown", function () {
      rememberSelection();
    });
  });
  document.addEventListener("selectionchange", function () {
    window.setTimeout(rememberSelection, 0);
  });
  document.addEventListener("pointerup", rememberSelection);
  noteButton.addEventListener("click", openNotePanel);
  if (notePaste) notePaste.addEventListener("click", pasteNote);
  highlightButton.addEventListener("click", toggleHighlight);
  noteSaveClose.addEventListener("click", function () {
    saveNote();
  });
  notePasteClose.addEventListener("click", pasteAndCloseNote);
  noteCloseButtons.forEach(function (button) {
    button.addEventListener("click", closeNotePanel);
  });
  document.addEventListener("pointerdown", function (event) {
    if (
      !notePanel.classList.contains("hidden") &&
      !notePanel.contains(event.target) &&
      !action.contains(event.target)
    ) {
      closeNotePanel();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !notePanel.classList.contains("hidden")) {
      closeNotePanel();
    }
  });

  var observer = new MutationObserver(function () {
    window.clearTimeout(mutationTimer);
    mutationTimer = window.setTimeout(applySavedHighlights, 80);
  });
  observer.observe(main, { childList: true, subtree: true });
  window.addEventListener("pagehide", function () {
    observer.disconnect();
    stopAnnotationReading();
  });
  setupAnnotationReading();
  setupStudyDeck();
  fetchHighlights();
})();
