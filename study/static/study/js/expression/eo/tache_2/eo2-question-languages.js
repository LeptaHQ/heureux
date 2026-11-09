/* Saved question translations; canonical French annotation text stays in place. */
(function () {
  "use strict";
  var storageKey = "heureux.eo2.questionLanguage";
  var initialized = new WeakSet();
  var instances = new Set();
  var preferred = "fr";
  try {
    if (localStorage.getItem(storageKey) === "en") preferred = "en";
  } catch (error) {
    console.warn("La préférence de langue EO2 est indisponible dans ce navigateur.");
  }

  function setup(root) {
    if (initialized.has(root)) return;
    var controls = root.querySelector("[data-eo2-language-controls]");
    if (!controls) return;
    var status = controls.querySelector("[data-eo2-language-status]");
    var buttons = Array.from(controls.querySelectorAll("[data-eo2-language-option]"));
    var ready = root.dataset.eo2LanguageReady === "true";
    var base = ready ? preferred : "fr";
    var rows = Array.from(root.querySelectorAll("[data-tache-two-question]")).map(function (row) {
      return {
        row: row, button: row.querySelector("[data-eo2-question-toggle]"),
        french: row.querySelector("[data-eo2-french]"),
        english: row.querySelector("[data-eo2-english]"), language: "fr"
      };
    });
    if (!rows.length || rows.length !== Number(root.dataset.eo2LanguageTotal) ||
        rows.some(function (row) { return !row.button || !row.french; })) return;
    initialized.add(root);

    function show(item, language) {
      var english = language === "en" && Boolean(item.english);
      var selection = window.getSelection();
      if (selection && !selection.isCollapsed && selection.rangeCount &&
          selection.getRangeAt(0).intersectsNode(item.row)) {
        selection.removeAllRanges();
        document.dispatchEvent(new Event("selectionchange"));
      }
      item.language = english ? "en" : "fr";
      item.french.hidden = english;
      if (item.english) item.english.hidden = !english;
      item.button.disabled = !item.english;
      item.button.setAttribute("aria-pressed", english ? "true" : "false");
      var number = item.button.textContent.trim();
      var label = item.english
        ? "Afficher la question " + number + (english ? " en français" : " en anglais")
        : "Traduction anglaise non préparée pour la question " + number;
      item.button.setAttribute("aria-label", label);
      item.button.title = label;
    }

    function sync() {
      var englishCount = rows.filter(function (row) { return row.language === "en"; }).length;
      buttons.forEach(function (button) {
        button.setAttribute("aria-pressed", button.dataset.eo2LanguageOption === base ? "true" : "false");
      });
      var text;
      if (root.dataset.eo2LanguageError === "true") {
        text = "Traductions indisponibles : le catalogue enregistré est invalide ou inaccessible.";
      } else if (!ready) {
        text = "Traduction globale indisponible : certaines questions ont été modifiées ou n’ont pas encore de traduction enregistrée.";
      } else if (englishCount !== (base === "en" ? rows.length : 0)) {
        text = "Personnalisé : " + englishCount + " en anglais, " + (rows.length - englishCount) + " en français.";
      } else {
        text = "";
      }
      if (status.textContent !== text) status.textContent = text;
      status.hidden = !text;
      if (window.HeureuxReadAloud) window.HeureuxReadAloud.refresh(document);
    }

    function choose(language) {
      base = language === "en" && ready ? "en" : "fr";
      rows.forEach(function (row) { show(row, base); });
      sync();
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        preferred = button.dataset.eo2LanguageOption;
        try { localStorage.setItem(storageKey, preferred); }
        catch (error) { console.warn("La préférence de langue EO2 n’a pas pu être enregistrée."); }
        instances.forEach(function (instance) {
          if (instance.root.isConnected) instance.choose(preferred);
          else instances.delete(instance);
        });
      });
      button.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") event.stopPropagation();
      });
    });
    rows.forEach(function (row) {
      row.button.addEventListener("click", function (event) {
        event.stopPropagation();
        show(row, row.language === "fr" ? "en" : "fr");
        sync();
      });
      row.button.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") event.stopPropagation();
      });
    });
    instances.add({root: root, choose: choose});
    controls.hidden = false;
    choose(base);
  }

  function refresh() {
    instances.forEach(function (instance) {
      if (!instance.root.isConnected) instances.delete(instance);
    });
    document.querySelectorAll("[data-eo2-language]").forEach(setup);
  }
  refresh();
  new MutationObserver(refresh).observe(document.getElementById("main"), {childList: true, subtree: true});
  document.addEventListener("heureux:flashcard-change", refresh);
  window.addEventListener("storage", function (event) {
    if (event.key !== storageKey) return;
    preferred = event.newValue === "en" ? "en" : "fr";
    instances.forEach(function (instance) {
      if (instance.root.isConnected) instance.choose(preferred);
      else instances.delete(instance);
    });
  });
})();
