/* English glosses never replace canonical French annotation or audio text. */
(function () {
  "use strict";
  var storageKey = "heureux.eo3.responseLanguage";
  var initialized = new WeakSet();
  var instances = new Set();
  var preferred = "fr";
  try { if (localStorage.getItem(storageKey) === "en") preferred = "en"; }
  catch (error) { console.warn("La préférence de langue EO3 est indisponible."); }

  function setup(root) {
    if (initialized.has(root)) return;
    var controls = root.querySelector("[data-eo3-language-controls]");
    if (!controls) return;
    var status = controls.querySelector("[data-eo3-language-status]");
    var options = Array.from(controls.querySelectorAll("[data-eo3-language-option]"));
    var ready = root.dataset.eo3LanguageReady === "true";
    var base = ready ? preferred : "fr";
    var rows = Array.from(root.querySelectorAll("[data-eo3-french]")).filter(function (node) {
      return node.textContent.trim();
    }).map(function (node) {
      var key = node.dataset.eo3French;
      return {
        key: key, french: node,
        english: root.querySelector('[data-eo3-english="' + key + '"]'),
        language: "fr"
      };
    });
    initialized.add(root);
    if (!rows.length || rows.length !== Number(root.dataset.eo3LanguageTotal)) {
      controls.hidden = false;
      options.forEach(function (button) {
        if (button.dataset.eo3LanguageOption === "en") button.disabled = true;
      });
      status.textContent = "Traductions indisponibles : la structure de la réponse est invalide.";
      status.hidden = false;
      console.error("La structure des blocs de langue EO3 est invalide.");
      return;
    }
    var sectionButtons = Array.from(root.querySelectorAll("[data-eo3-section-toggle]"));
    var argumentButtons = Array.from(root.querySelectorAll("[data-eo3-argument-toggle]"));

    function show(row, language) {
      var english = language === "en" && Boolean(row.english);
      var selection = window.getSelection();
      if (selection && !selection.isCollapsed && selection.rangeCount) {
        var range = selection.getRangeAt(0);
        if (range.intersectsNode(row.french) || (row.english && range.intersectsNode(row.english))) {
          selection.removeAllRanges();
          document.dispatchEvent(new Event("selectionchange"));
        }
      }
      row.language = english ? "en" : "fr";
      row.french.hidden = english;
      if (row.english) row.english.hidden = !english;
    }

    function argumentRows(button) {
      var prefix = "argument-" + button.dataset.eo3ArgumentToggle + "-";
      return rows.filter(function (row) { return row.key.indexOf(prefix) === 0; });
    }

    function sync() {
      var englishCount = rows.filter(function (row) { return row.language === "en"; }).length;
      options.forEach(function (button) {
        button.setAttribute("aria-pressed", button.dataset.eo3LanguageOption === base ? "true" : "false");
      });
      sectionButtons.forEach(function (button) {
        var row = rows.find(function (item) { return item.key === button.dataset.eo3SectionToggle; });
        var english = row && row.language === "en";
        button.disabled = !row || !row.english;
        button.setAttribute("aria-pressed", english ? "true" : "false");
        var label = button.disabled ? "Traduction non préparée : " : "Afficher ";
        label += button.textContent.trim() + (button.disabled ? "" : (english ? " en français" : " en anglais"));
        button.setAttribute("aria-label", label);
        button.title = label;
      });
      argumentButtons.forEach(function (button) {
        var members = argumentRows(button);
        var count = members.filter(function (row) { return row.language === "en"; }).length;
        button.disabled = !members.length || members.some(function (row) { return !row.english; });
        button.setAttribute("aria-pressed", count && count === members.length ? "true" : (count ? "mixed" : "false"));
        var number = button.textContent.trim().replace(/\.$/, "");
        var label = button.disabled ? "Traduction non préparée pour l'argument " : "Afficher l'argument ";
        label += number + (button.disabled ? "" : (count === members.length ? " en français" : " en anglais"));
        button.setAttribute("aria-label", label);
        button.title = label;
      });
      var text = "";
      if (root.dataset.eo3LanguageError === "true") {
        text = "Traductions indisponibles : le catalogue enregistré est invalide ou inaccessible.";
      } else if (!ready) {
        text = "Traduction globale indisponible : certaines parties ont été modifiées ou n'ont pas encore de traduction enregistrée.";
      } else if (englishCount !== (base === "en" ? rows.length : 0)) {
        text = "Personnalisé : " + englishCount + " blocs en anglais, " + (rows.length - englishCount) + " en français.";
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

    function keepCard(event) {
      if (event.key === "Enter" || event.key === " ") event.stopPropagation();
    }
    options.forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        preferred = button.dataset.eo3LanguageOption;
        try { localStorage.setItem(storageKey, preferred); }
        catch (error) { console.warn("La préférence de langue EO3 n'a pas pu être enregistrée."); }
        instances.forEach(function (instance) {
          if (instance.root.isConnected) instance.choose(preferred);
          else instances.delete(instance);
        });
      });
      button.addEventListener("keydown", keepCard);
    });
    sectionButtons.forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        var row = rows.find(function (item) { return item.key === button.dataset.eo3SectionToggle; });
        if (row && row.english) show(row, row.language === "en" ? "fr" : "en");
        sync();
      });
      button.addEventListener("keydown", keepCard);
    });
    argumentButtons.forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        var members = argumentRows(button);
        var language = members.every(function (row) { return row.language === "en"; }) ? "fr" : "en";
        members.forEach(function (row) { show(row, language); });
        sync();
      });
      button.addEventListener("keydown", keepCard);
    });
    instances.add({root: root, choose: choose});
    controls.hidden = false;
    choose(base);
  }

  function refresh() {
    instances.forEach(function (instance) {
      if (!instance.root.isConnected) instances.delete(instance);
    });
    document.querySelectorAll("[data-eo3-language]").forEach(setup);
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
