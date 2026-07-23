/* Heureux — front-end behaviour: theme, nav, and the review session. */
(function () {
  "use strict";

  /* ---------- Theme toggle ---------- */
  var root = document.documentElement;
  function setTheme(name) {
    root.setAttribute("data-theme", name);
    try { localStorage.setItem("theme", name); } catch (e) {}
  }
  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var current = root.getAttribute("data-theme") === "dark" ? "dark" : "light";
      setTheme(current === "dark" ? "light" : "dark");
    });
  });

  /* ---------- Collection view toggle ---------- */
  (function () {
    var toggles = Array.from(
      document.querySelectorAll("[data-collection-view-toggle]")
    );
    var collections = document.querySelectorAll("[data-collection-view]");
    if (!toggles.length || !collections.length) return;

    function scrollActiveAnnotationAnchor() {
      var anchorId = window.location.hash.slice(1);
      if (!anchorId) return;
      try { anchorId = decodeURIComponent(anchorId); } catch (e) {}

      document.querySelectorAll(".is-annotation-anchor").forEach(
        function (element) {
          element.classList.remove("is-annotation-anchor");
        }
      );
      var target = document.getElementById(anchorId);
      if (target && target.offsetParent === null) {
        target = Array.from(
          document.querySelectorAll("[data-annotation-anchor]")
        ).find(function (candidate) {
          return candidate.dataset.annotationAnchor === anchorId;
        });
      }
      if (!target || target.offsetParent === null) return;

      target.classList.add("is-annotation-anchor");
      window.requestAnimationFrame(function () {
        target.scrollIntoView({ block: "center" });
      });
    }

    function setCollectionView(mode, persist) {
      if (mode !== "cards" && mode !== "table") mode = "cards";
      root.setAttribute("data-collection-view-mode", mode);
      toggles.forEach(function (toggle) {
        toggle.querySelectorAll("[data-collection-view-option]").forEach(
          function (button) {
            button.setAttribute(
              "aria-pressed",
              button.dataset.collectionViewOption === mode ? "true" : "false"
            );
          }
        );
      });
      if (persist) {
        try { localStorage.setItem("collectionViewMode", mode); } catch (e) {}
      }
      scrollActiveAnnotationAnchor();
    }

    var initial =
      root.getAttribute("data-collection-view-mode") === "table"
        ? "table"
        : "cards";
    setCollectionView(initial, false);

    toggles.forEach(function (toggle) {
      toggle.addEventListener("click", function (event) {
        var button = event.target.closest("[data-collection-view-option]");
        if (!button || !toggle.contains(button)) return;
        setCollectionView(button.dataset.collectionViewOption, true);
      });
    });
    window.addEventListener("hashchange", scrollActiveAnnotationAnchor);
  })();

  /* ---------- Active Notes scope ---------- */
  (function () {
    var scopeNav = document.querySelector(".notes-scope-nav");
    if (!scopeNav) return;
    var activeScope = scopeNav.querySelector(".is-active");
    if (!activeScope) return;

    window.requestAnimationFrame(function () {
      var navBox = scopeNav.getBoundingClientRect();
      var activeBox = activeScope.getBoundingClientRect();
      if (activeBox.left >= navBox.left && activeBox.right <= navBox.right) return;

      var target = scopeNav.scrollLeft + activeBox.left - navBox.left -
        (navBox.width - activeBox.width) / 2;
      scopeNav.scrollTo({ left: Math.max(0, target), behavior: "auto" });
    });
  })();

  /* ---------- Tâche 2 month sections ---------- */
  (function () {
    var toggles = Array.from(
      document.querySelectorAll("[data-tache-two-month-toggle]")
    );
    if (!toggles.length) return;

    function setMonthExpanded(monthKey, expanded, persist) {
      toggles.forEach(function (toggle) {
        if (toggle.dataset.tacheTwoMonthKey !== monthKey) return;

        var target = document.getElementById(
          toggle.getAttribute("aria-controls")
        );
        if (!target) return;

        toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
        toggle.setAttribute(
          "aria-label",
          (expanded ? "Réduire " : "Afficher ") +
            toggle.dataset.tacheTwoMonthName
        );
        var label = toggle.querySelector(
          "[data-tache-two-month-toggle-label]"
        );
        if (label) label.textContent = expanded ? "Réduire" : "Afficher";

        if (target.tagName === "TBODY") {
          target.querySelectorAll("[data-tache-two-month-row]").forEach(
            function (row) {
              row.hidden = !expanded;
            }
          );
        } else {
          target.hidden = !expanded;
        }
        target.classList.toggle("is-collapsed", !expanded);
      });

      if (persist) {
        try {
          localStorage.setItem(
            "tacheTwoMonth:" + monthKey,
            expanded ? "expanded" : "collapsed"
          );
        } catch (e) {}
      }
    }

    Array.from(
      new Set(
        toggles.map(function (toggle) {
          return toggle.dataset.tacheTwoMonthKey;
        })
      )
    ).forEach(function (monthKey) {
      var expanded = false;
      try {
        expanded =
          localStorage.getItem("tacheTwoMonth:" + monthKey) === "expanded";
      } catch (e) {}
      setMonthExpanded(monthKey, expanded, false);
    });

    toggles.forEach(function (toggle) {
      toggle.addEventListener("click", function () {
        setMonthExpanded(
          toggle.dataset.tacheTwoMonthKey,
          toggle.getAttribute("aria-expanded") !== "true",
          true
        );
      });
    });
  })();

  /* ---------- Form dialogs ---------- */
  (function () {
    var dialogs = Array.from(document.querySelectorAll(".form-dialog"));
    if (!dialogs.length) return;

    function openDialog(dialog, trigger) {
      if (!dialog || dialog.open) return;
      dialog._returnFocus = trigger || document.activeElement;
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
      window.requestAnimationFrame(function () {
        var firstField = dialog.querySelector("input:not([type='hidden']), textarea");
        if (firstField) firstField.focus();
      });
    }

    function closeDialog(dialog) {
      if (!dialog || !dialog.open) return;
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
    }

    document.querySelectorAll("[data-dialog-open]").forEach(function (trigger) {
      trigger.addEventListener("click", function () {
        openDialog(
          document.getElementById(trigger.dataset.dialogOpen),
          trigger
        );
      });
    });

    dialogs.forEach(function (dialog) {
      dialog.querySelectorAll("[data-dialog-close]").forEach(function (button) {
        button.addEventListener("click", function () {
          closeDialog(dialog);
        });
      });
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) closeDialog(dialog);
      });
      dialog.addEventListener("close", function () {
        if (
          dialog._returnFocus &&
          dialog._returnFocus.isConnected
        ) {
          dialog._returnFocus.focus();
        }
      });
    });

    var editDialog = document.getElementById("note-edit-dialog");
    var editForm = editDialog
      ? editDialog.querySelector("[data-annotation-edit-form]")
      : null;
    var editError = editDialog
      ? editDialog.querySelector("[data-annotation-edit-error]")
      : null;
    function setEditError(message) {
      if (!editError) return;
      editError.textContent = message || "";
      editError.hidden = !message;
    }
    document.querySelectorAll("[data-annotation-edit]").forEach(
      function (button) {
        button.addEventListener("click", function () {
          if (!editDialog || !editForm) return;
          var annotationId = button.dataset.annotationEdit;
          var source = Array.from(
            document.querySelectorAll("[data-annotation-edit-source]")
          ).find(function (candidate) {
            return candidate.dataset.annotationEditSource === annotationId;
          });
          if (!source) return;
          editForm.action = button.dataset.annotationUpdateUrl;
          editForm.querySelector("[data-annotation-edit-title]").value =
            source.dataset.annotationEditTitle || "";
          editForm.querySelector("[data-annotation-edit-body]").value =
            source.dataset.annotationEditBody || "";
          setEditError("");
          openDialog(editDialog, button);
        });
      }
    );
    if (editForm && window.fetch) {
      editForm.addEventListener("submit", function (event) {
        event.preventDefault();
        var submitButton =
          event.submitter || editForm.querySelector("[type='submit']");
        submitButton.disabled = true;
        setEditError("");
        fetch(editForm.action, {
          method: "POST",
          body: new FormData(editForm),
          credentials: "same-origin",
          headers: {
            "Accept": "application/json",
            "X-Requested-With": "fetch"
          }
        })
          .then(function (response) {
            return response.json().then(
              function (payload) {
                return { response: response, payload: payload };
              },
              function () {
                throw new Error(
                  "Impossible de lire la réponse d’enregistrement."
                );
              }
            );
          })
          .then(function (result) {
            if (!result.response.ok) {
              throw new Error(
                result.payload.error ||
                "Impossible d’enregistrer cette note."
              );
            }
            if (!result.payload.redirect_url) {
              throw new Error("La réponse d’enregistrement est incomplète.");
            }
            var target = new URL(
              result.payload.redirect_url,
              window.location.origin
            );
            if (
              target.pathname === window.location.pathname &&
              target.search === window.location.search
            ) {
              window.location.hash = target.hash;
              window.location.reload();
            } else {
              window.location.assign(target.href);
            }
          })
          .catch(function (error) {
            submitButton.disabled = false;
            setEditError(error.message);
          });
      });
    }

    dialogs.forEach(function (dialog) {
      if (dialog.hasAttribute("data-dialog-open-on-load")) {
        openDialog(dialog);
      }
    });
  })();

  /* ---------- Mobile nav ---------- */
  var toggle = document.querySelector("[data-nav-toggle]");
  var links = document.querySelector("[data-nav-links]");
  var utilityMenu = document.querySelector("[data-nav-more]");
  var mobileNavQuery = window.matchMedia("(max-width: 760px)");

  function setNavOpen(open, returnFocus) {
    if (!toggle || !links) return;
    links.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Fermer le menu" : "Ouvrir le menu");
    root.classList.toggle("nav-open", open && mobileNavQuery.matches);
    if (!open && utilityMenu) utilityMenu.removeAttribute("open");
    if (!open && returnFocus) toggle.focus();
  }

  if (toggle && links) {
    toggle.addEventListener("click", function () {
      setNavOpen(!links.classList.contains("is-open"), false);
    });
    links.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        setNavOpen(false, false);
      });
    });
  }

  if (utilityMenu) {
    utilityMenu.addEventListener("toggle", function () {
      if (utilityMenu.open && mobileNavQuery.matches) {
        window.setTimeout(function () {
          utilityMenu.scrollIntoView({ block: "nearest" });
        }, 0);
      }
    });
  }

  document.addEventListener("click", function (event) {
    if (utilityMenu && !utilityMenu.contains(event.target)) {
      utilityMenu.removeAttribute("open");
    }
    if (
      toggle &&
      links &&
      links.classList.contains("is-open") &&
      !links.contains(event.target) &&
      !toggle.contains(event.target)
    ) {
      setNavOpen(false, false);
    } else if (
      links &&
      links.classList.contains("is-open") &&
      event.target === links
    ) {
      setNavOpen(false, false);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (links && links.classList.contains("is-open")) {
      setNavOpen(false, true);
    } else if (utilityMenu && utilityMenu.open) {
      utilityMenu.removeAttribute("open");
      utilityMenu.querySelector("summary").focus();
    }
  });

  function closeNavAboveMobile() {
    if (!mobileNavQuery.matches) setNavOpen(false, false);
  }

  if (mobileNavQuery.addEventListener) {
    mobileNavQuery.addEventListener("change", closeNavAboveMobile);
  } else {
    mobileNavQuery.addListener(closeNavAboveMobile);
  }

  /* ---------- Subject vocabulary search ---------- */
  (function () {
    var input = document.querySelector("[data-subject-vocabulary-search]");
    var directory = document.querySelector("[data-subject-vocabulary-directory]");
    if (!input || !directory) return;

    var groups = Array.from(directory.querySelectorAll("[data-subject-theme]"));
    var rows = Array.from(directory.querySelectorAll("[data-subject-vocabulary-row]"));
    var status = document.querySelector("[data-subject-vocabulary-status]");
    var empty = document.querySelector("[data-subject-vocabulary-empty]");
    var searching = false;

    function normalized(value) {
      return value
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .trim();
    }

    function updateDirectory() {
      var query = normalized(input.value);
      if (query && !searching) {
        groups.forEach(function (group) {
          group.dataset.wasOpen = group.open ? "true" : "false";
        });
      }

      var visibleCount = 0;
      groups.forEach(function (group) {
        var groupRows = Array.from(
          group.querySelectorAll("[data-subject-vocabulary-row]")
        );
        var groupCount = 0;
        groupRows.forEach(function (row) {
          var matches = !query || normalized(row.textContent).includes(query);
          row.hidden = !matches;
          if (matches) {
            groupCount += 1;
            visibleCount += 1;
          }
        });
        group.hidden = groupCount === 0;
        if (query && groupCount) group.open = true;
      });

      if (!query && searching) {
        groups.forEach(function (group) {
          group.hidden = false;
          group.open = group.dataset.wasOpen === "true";
          delete group.dataset.wasOpen;
        });
      }
      searching = Boolean(query);

      if (status) {
        if (query) {
          var plural = visibleCount === 1 ? "" : "s";
          status.textContent =
            visibleCount + " sujet" + plural + " trouvé" + plural;
        } else {
          status.textContent = rows.length + " sujets";
        }
      }
      if (empty) empty.hidden = visibleCount !== 0;
    }

    input.addEventListener("input", updateDirectory);
  })();

  /* ---------- Confirmation dialog ---------- */
  var openConfirm = function (opts) {
    opts = opts || {};
    return Promise.resolve(
      window.confirm(opts.message || "Confirmer cette action ?")
    );
  };
  (function () {
    var dialog = document.querySelector("[data-confirm-dialog]");
    var canUseDialog = dialog && typeof dialog.showModal === "function";
    var messageEl = dialog && dialog.querySelector("[data-confirm-message]");
    var acceptBtn = dialog && dialog.querySelector("[data-confirm-accept]");

    if (canUseDialog) {
      openConfirm = function (opts) {
        opts = opts || {};
        return new Promise(function (resolve) {
          if (messageEl) {
            messageEl.textContent =
              opts.message || "Confirmer cette action ?";
          }
          if (acceptBtn) {
            acceptBtn.textContent = opts.label || "Confirmer";
            acceptBtn.classList.toggle("btn--danger", opts.tone !== "safe");
          }
          var settled = false;
          function cleanup() {
            if (acceptBtn) acceptBtn.removeEventListener("click", onAccept);
            dialog.removeEventListener("close", onClose);
          }
          function onAccept() {
            if (settled) return;
            settled = true;
            cleanup();
            if (dialog.open) dialog.close();
            resolve(true);
          }
          function onClose() {
            if (settled) return;
            settled = true;
            cleanup();
            resolve(false);
          }
          if (acceptBtn) acceptBtn.addEventListener("click", onAccept);
          dialog.addEventListener("close", onClose);
          dialog._returnFocus = document.activeElement;
          dialog.showModal();
          window.requestAnimationFrame(function () {
            if (acceptBtn) acceptBtn.focus();
          });
        });
      };
    }

    Array.from(document.querySelectorAll("form[data-confirm]")).forEach(
      function (form) {
        if (form.closest("[data-annotation-list]")) return;
        form.addEventListener("submit", function (event) {
          if (form.dataset.confirmed === "1") {
            form.removeAttribute("data-confirmed");
            return;
          }
          event.preventDefault();
          openConfirm({
            message: form.dataset.confirm,
            label: form.dataset.confirmLabel,
            tone: form.dataset.confirmTone,
          }).then(function (ok) {
            if (!ok) return;
            form.dataset.confirmed = "1";
            if (typeof form.requestSubmit === "function") {
              form.requestSubmit();
            } else {
              form.submit();
            }
          });
        });
      }
    );
  })();

  document.querySelectorAll("[data-auto-submit]").forEach(function (control) {
    control.addEventListener("change", function () {
      var form = control.form;
      if (!form) return;
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });
  });

  /* ---------- Custom select (accessible listbox) ---------- */
  (function () {
    var selects = Array.from(
      document.querySelectorAll("select[data-custom-select]")
    );
    if (!selects.length) return;
    var uid = 0;

    selects.forEach(function (select) {
      if (select.dataset.customSelectReady === "1") return;
      select.dataset.customSelectReady = "1";
      uid += 1;
      var base = "custom-select-" + uid;
      var options = Array.from(select.options);

      var wrapper = document.createElement("div");
      wrapper.className = "custom-select";

      var button = document.createElement("button");
      button.type = "button";
      button.className = "custom-select__button";
      button.setAttribute("aria-haspopup", "listbox");
      button.setAttribute("aria-expanded", "false");
      button.id = base + "-button";
      if (select.getAttribute("aria-label")) {
        button.setAttribute("aria-label", select.getAttribute("aria-label"));
      } else if (select.labels && select.labels[0]) {
        button.setAttribute("aria-labelledby", base + "-button");
      }
      var valueEl = document.createElement("span");
      valueEl.className = "custom-select__value";
      var chevron = document.createElement("span");
      chevron.className = "custom-select__chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.innerHTML =
        '<svg viewBox="0 0 24 24"><path d="m7 10 5 5 5-5"></path></svg>';
      button.appendChild(valueEl);
      button.appendChild(chevron);

      var list = document.createElement("ul");
      list.className = "custom-select__list";
      list.setAttribute("role", "listbox");
      list.id = base + "-list";
      list.tabIndex = -1;
      list.hidden = true;
      button.setAttribute("aria-controls", list.id);

      var optionEls = options.map(function (option, optionIndex) {
        var item = document.createElement("li");
        item.className = "custom-select__option";
        item.setAttribute("role", "option");
        item.id = base + "-option-" + optionIndex;
        item.dataset.value = option.value;
        item.textContent = option.textContent;
        item.setAttribute(
          "aria-selected",
          option.selected ? "true" : "false"
        );
        list.appendChild(item);
        return item;
      });

      select.classList.add("custom-select__native");
      select.setAttribute("tabindex", "-1");
      select.setAttribute("aria-hidden", "true");
      select.parentNode.insertBefore(wrapper, select);
      wrapper.appendChild(select);
      wrapper.appendChild(button);
      wrapper.appendChild(list);

      var activeIndex = Math.max(0, select.selectedIndex);

      function syncButton() {
        var selected = options[select.selectedIndex] || options[0];
        valueEl.textContent = selected ? selected.textContent : "";
      }

      function setActive(nextIndex) {
        activeIndex = Math.max(0, Math.min(nextIndex, optionEls.length - 1));
        optionEls.forEach(function (item, itemIndex) {
          item.classList.toggle(
            "is-active",
            itemIndex === activeIndex
          );
        });
        var current = optionEls[activeIndex];
        if (current) {
          list.setAttribute("aria-activedescendant", current.id);
          current.scrollIntoView({ block: "nearest" });
        }
      }

      function openList() {
        if (!list.hidden) return;
        list.hidden = false;
        wrapper.classList.add("is-open");
        button.setAttribute("aria-expanded", "true");
        setActive(select.selectedIndex);
        list.focus();
      }

      function closeList(focusButton) {
        if (list.hidden) return;
        list.hidden = true;
        wrapper.classList.remove("is-open");
        button.setAttribute("aria-expanded", "false");
        if (focusButton) button.focus();
      }

      function choose(optionIndex) {
        var option = options[optionIndex];
        if (!option) return;
        var changed = select.selectedIndex !== optionIndex;
        select.selectedIndex = optionIndex;
        optionEls.forEach(function (item, itemIndex) {
          item.setAttribute(
            "aria-selected",
            itemIndex === optionIndex ? "true" : "false"
          );
        });
        syncButton();
        closeList(true);
        if (changed) {
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }

      button.addEventListener("click", function () {
        if (list.hidden) {
          openList();
        } else {
          closeList(true);
        }
      });

      button.addEventListener("keydown", function (event) {
        if (
          event.key === "ArrowDown" ||
          event.key === "ArrowUp" ||
          event.key === "Enter" ||
          event.key === " "
        ) {
          event.preventDefault();
          openList();
        }
      });

      list.addEventListener("keydown", function (event) {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setActive(activeIndex + 1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          setActive(activeIndex - 1);
        } else if (event.key === "Home") {
          event.preventDefault();
          setActive(0);
        } else if (event.key === "End") {
          event.preventDefault();
          setActive(optionEls.length - 1);
        } else if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose(activeIndex);
        } else if (event.key === "Escape") {
          event.preventDefault();
          closeList(true);
        } else if (event.key === "Tab") {
          closeList(false);
        }
      });

      optionEls.forEach(function (item, optionIndex) {
        item.addEventListener("click", function () {
          choose(optionIndex);
        });
        item.addEventListener("mousemove", function () {
          setActive(optionIndex);
        });
      });

      document.addEventListener("click", function (event) {
        if (!wrapper.contains(event.target)) closeList(false);
      });

      syncButton();
    });
  })();

  /* ---------- In-place note & highlight actions ---------- */
  (function () {
    var list = document.querySelector("[data-annotation-list]");
    if (!list) return;

    var status = list.dataset.status || ""; // "", "todo", "done", "study"
    var panelKind =
      list.dataset.activeTab === "highlights" ? "highlights" : "notes";
    var toast = document.querySelector("[data-annotation-toast]");
    var toastTimer = null;

    var STUDY_LABEL = { on: "Retirer de l’étude", off: "Ajouter à étudier" };
    var DONE_LABEL = {
      on: "Marquer comme à faire",
      off: "Marquer comme terminé",
    };

    function flashToast(message) {
      if (!toast) return;
      window.clearTimeout(toastTimer);
      toast.textContent = message;
      toast.classList.remove("hidden");
      toastTimer = window.setTimeout(function () {
        toast.classList.add("hidden");
      }, 2200);
    }

    function itemNodes(id) {
      return Array.from(
        list.querySelectorAll('[data-annotation-item="' + id + '"]')
      );
    }

    function readNumber(el) {
      var value = parseInt((el.textContent || "").replace(/[^0-9]/g, ""), 10);
      return isNaN(value) ? 0 : value;
    }

    function adjustCount(el, delta) {
      if (!el) return;
      el.textContent = Math.max(0, readNumber(el) + delta);
    }

    function heroEl(name) {
      return document.querySelector('[data-hero-count="' + name + '"]');
    }
    function tabCount(name) {
      return document.querySelector('[data-tab-count="' + name + '"]');
    }
    function scopeCount(key) {
      return document.querySelector('[data-scope-count="' + key + '"]');
    }

    function bumpHero(name, delta) {
      var el = heroEl(name);
      if (!el) return;
      var next = Math.max(0, readNumber(el) + delta);
      el.textContent = next;
      if (name === "notes" || name === "highlights") {
        var span = el.parentNode;
        if (!span) return;
        while (el.nextSibling) span.removeChild(el.nextSibling);
        var word = name === "notes" ? "note" : "surlignage";
        span.appendChild(
          document.createTextNode(" " + word + (next === 1 ? "" : "s"))
        );
      }
    }

    function postForm(form) {
      return fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch" },
        body: new FormData(form),
        credentials: "same-origin",
      }).then(function (response) {
        if (!response.ok) throw new Error("bad status");
        return response.json();
      });
    }

    function setButtonBusy(form, busy) {
      var button = form.querySelector("button");
      if (button) button.disabled = busy;
    }

    function nativeSubmit(form) {
      form.dataset.fallback = "1";
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    }

    function recountSection(section, isRow) {
      if (!section) return;
      var items = isRow
        ? section.querySelectorAll("tr.annotation-table__row")
        : section.querySelectorAll(".annotation-card");
      if (!items.length) {
        section.remove();
        return;
      }
      var countEl = section.querySelector(".notes-date-section__count");
      if (countEl) countEl.textContent = items.length;
    }

    function refreshEmptyState() {
      if (list.querySelector("[data-annotation-item]")) return;
      var panel = list.querySelector(".notes-tab-panel");
      var section = panel && panel.querySelector(".annotations-section");
      var cardsView = list.querySelector(
        "[data-collection-view-panel='cards']"
      );
      var tableView = list.querySelector(
        "[data-collection-view-panel='table']"
      );
      if (cardsView) cardsView.remove();
      if (tableView) tableView.remove();
      var toolbar = list.querySelector(".collection-view-toolbar");
      if (toolbar) toolbar.remove();
      if (section && !section.querySelector(".empty, .notes-empty-hint")) {
        var empty = document.createElement("div");
        if (panelKind === "notes") {
          empty.className = "empty annotation-empty";
          var paragraph = document.createElement("p");
          paragraph.textContent =
            "Aucune note ici. Écrivez-en une ou sélectionnez du texte " +
            "ailleurs dans l'application.";
          empty.appendChild(paragraph);
        } else {
          empty.className = "notes-empty-hint";
          empty.textContent =
            "Sélectionnez un passage, puis choisissez l'icône de surlignage.";
        }
        section.appendChild(empty);
      }
    }

    function detachItem(id) {
      itemNodes(id).forEach(function (node) {
        var isRow = node.tagName === "TR";
        var section = isRow
          ? node.closest("tbody")
          : node.closest(".notes-date-section");
        node.remove();
        recountSection(section, isRow);
      });
      refreshEmptyState();
    }

    function removeFromView(id) {
      detachItem(id);
      bumpHero(panelKind, -1);
      adjustCount(tabCount(panelKind), -1);
    }

    function badgeText(type, annKind) {
      if (type === "study") return "À étudier";
      return annKind === "highlight" ? "Terminé" : "Terminée";
    }

    function syncRowEmpty(statusCell) {
      var hasBadge = statusCell.querySelector(
        ".annotation-card__study, .annotation-card__done"
      );
      var empty = statusCell.querySelector(".annotation-table__status-empty");
      if (hasBadge && empty) {
        empty.remove();
      } else if (!hasBadge && !empty) {
        var span = document.createElement("span");
        span.className = "annotation-table__status-empty";
        span.setAttribute("aria-label", "Non marqué");
        span.textContent = "—";
        statusCell.appendChild(span);
      }
    }

    function setBadge(node, type, on, annKind) {
      var isRow = node.tagName === "TR";
      var container = isRow
        ? node.querySelector(".annotation-table__status")
        : node.querySelector(".annotation-card__head");
      if (!container) return;
      var cls =
        type === "study" ? "annotation-card__study" : "annotation-card__done";
      var existing = container.querySelector("." + cls);
      if (on && !existing) {
        var span = document.createElement("span");
        span.className = cls;
        span.textContent = badgeText(type, annKind);
        if (isRow) {
          container.appendChild(span);
        } else {
          var before =
            type === "study"
              ? container.querySelector(".annotation-card__done") ||
                container.querySelector("time")
              : container.querySelector("time");
          container.insertBefore(span, before || null);
        }
      } else if (!on && existing) {
        existing.remove();
      }
      if (isRow) syncRowEmpty(container);
    }

    function updateToggleForm(node, action, active, labels) {
      var form = node.querySelector(
        'form[data-annotation-action="' + action + '"]'
      );
      if (!form) return;
      var field = action === "study" ? "study_later" : "completed";
      var input = form.querySelector('input[name="' + field + '"]');
      if (input) input.value = active ? "0" : "1";
      var button = form.querySelector("button");
      if (button) {
        var label = active ? labels.on : labels.off;
        button.setAttribute("aria-pressed", active ? "true" : "false");
        button.setAttribute("aria-label", label);
        button.setAttribute("title", label);
        var sr = button.querySelector(".sr-only");
        if (sr) sr.textContent = label;
      }
    }

    function handleStudy(id, studyLater) {
      bumpHero("study", studyLater ? 1 : -1);
      if (
        (status === "study" && !studyLater) ||
        (status === "todo" && studyLater)
      ) {
        removeFromView(id);
        return;
      }
      itemNodes(id).forEach(function (node) {
        updateToggleForm(node, "study", studyLater, STUDY_LABEL);
        setBadge(node, "study", studyLater, node.dataset.annotationKind);
      });
    }

    function handleComplete(id, completed) {
      if (
        (status === "todo" && completed) ||
        (status === "done" && !completed)
      ) {
        removeFromView(id);
        return;
      }
      itemNodes(id).forEach(function (node) {
        updateToggleForm(node, "complete", completed, DONE_LABEL);
        setBadge(node, "done", completed, node.dataset.annotationKind);
      });
    }

    function handleDelete(id, data) {
      detachItem(id);
      bumpHero(panelKind, -1);
      adjustCount(tabCount(panelKind), -1);
      if (data && data.scope) adjustCount(scopeCount(data.scope), -1);
      if (data && data.was_study) bumpHero("study", -1);
      flashToast(
        panelKind === "highlights" ? "Surlignage supprimé." : "Note supprimée."
      );
    }

    function runToggle(form, action) {
      var id = form.dataset.annotationId;
      setButtonBusy(form, true);
      postForm(form)
        .then(function (data) {
          if (action === "study") {
            handleStudy(id, !!data.study_later);
          } else {
            handleComplete(id, !!data.completed);
          }
          setButtonBusy(form, false);
        })
        .catch(function () {
          nativeSubmit(form);
        });
    }

    function runDelete(form) {
      setButtonBusy(form, true);
      postForm(form)
        .then(function (data) {
          handleDelete(form.dataset.annotationId, data);
        })
        .catch(function () {
          nativeSubmit(form);
        });
    }

    list.addEventListener("submit", function (event) {
      var form = event.target.closest("form[data-annotation-action]");
      if (!form || !list.contains(form)) return;
      if (form.dataset.fallback === "1") return; // let the browser submit
      event.preventDefault();
      if (form.dataset.annotationAction === "delete") {
        openConfirm({
          message: form.dataset.confirm,
          label: form.dataset.confirmLabel,
          tone: form.dataset.confirmTone,
        }).then(function (ok) {
          if (ok) runDelete(form);
        });
      } else {
        runToggle(form, form.dataset.annotationAction);
      }
    });
  })();

  /* ---------- Service worker (PWA) ---------- */
  if ("serviceWorker" in navigator) {
    var updateBanner = document.querySelector("[data-pwa-update-banner]");
    var updateButton = document.querySelector("[data-pwa-update]");
    var waitingRegistration = null;
    var reloadingForUpdate = false;
    var reloadOnControllerChange = false;

    function showWorkerUpdate(registration) {
      if (!navigator.serviceWorker.controller || !registration.waiting) return;
      waitingRegistration = registration;
      if (updateBanner) updateBanner.classList.remove("hidden");
    }

    if (updateButton) {
      updateButton.addEventListener("click", function () {
        if (!waitingRegistration || !waitingRegistration.waiting) return;
        updateButton.disabled = true;
        reloadOnControllerChange = true;
        waitingRegistration.waiting.postMessage({ type: "SKIP_WAITING" });
      });
    }
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (!reloadOnControllerChange || reloadingForUpdate) return;
      reloadingForUpdate = true;
      window.location.reload();
    });
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" })
        .then(function (registration) {
          showWorkerUpdate(registration);
          registration.addEventListener("updatefound", function () {
            var worker = registration.installing;
            if (!worker) return;
            worker.addEventListener("statechange", function () {
              if (worker.state === "installed") {
                showWorkerUpdate(registration);
              }
            });
          });
          registration.update().catch(function () {});
        })
        .catch(function () {});
    });
  }

  /* ---------- Install prompt (PWA) ---------- */
  (function () {
    var installBtn = document.querySelector("[data-install-app]");
    if (!installBtn) return;
    function isStandalone() {
      return window.matchMedia("(display-mode: standalone)").matches ||
        navigator.standalone === true;
    }
    function isIOS() {
      return /iphone|ipad|ipod/i.test(navigator.userAgent) ||
        (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    }
    if (isStandalone()) { return; } // already installed — nothing to offer

    var deferred = null;
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault();
      deferred = e;
      installBtn.hidden = false;
    });
    window.addEventListener("appinstalled", function () {
      deferred = null;
      installBtn.hidden = true;
    });
    installBtn.addEventListener("click", function () {
      if (deferred) {
        deferred.prompt();
        deferred.userChoice.then(function () {
          deferred = null;
          installBtn.hidden = true;
        });
      } else if (isIOS()) {
        alert("Pour installer Heureux : appuyez sur le bouton Partager, puis « Sur l'écran d'accueil ».");
      }
    });
    // iOS Safari never fires beforeinstallprompt — surface manual instructions.
    if (isIOS()) { installBtn.hidden = false; }
  })();

  /* ---------- Shared French speech ---------- */
  var frenchSpeech = (function () {
    var synthesis = window.speechSynthesis;
    var Utterance = window.SpeechSynthesisUtterance;
    var frenchVoices = [];
    var feminineVoiceNames = [
      "amelie",
      "audrey",
      "aurelie",
      "caroline",
      "celine",
      "charlotte",
      "chloe",
      "claire",
      "denise",
      "elise",
      "eloise",
      "francoise",
      "hortense",
      "julie",
      "lea",
      "manon",
      "marie",
      "sandrine",
      "sylvie",
      "valerie",
      "virginie",
      "vivienne"
    ];
    var qualityVoiceNames = [
      "premium",
      "enhanced",
      "neural",
      "natural",
      "wavenet"
    ];

    function normalizedVoiceName(voice) {
      return ((voice && voice.name) || "")
        .concat(" ", (voice && voice.voiceURI) || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase();
    }

    function isFeminineVoice(voice) {
      var name = normalizedVoiceName(voice);
      return feminineVoiceNames.some(function (candidate) {
        return name.indexOf(candidate) !== -1;
      });
    }

    function refreshVoices() {
      if (!synthesis) {
        frenchVoices = [];
        return;
      }
      frenchVoices = synthesis.getVoices().filter(function (voice) {
        return /^fr(?:[-_]|$)/i.test(voice.lang || "");
      });
    }

    function voiceScore(voice) {
      var language = (voice.lang || "").replace("_", "-").toLowerCase();
      var name = normalizedVoiceName(voice);
      var value = language === "fr-fr" ? 100 : 50;
      if (isFeminineVoice(voice)) value += 1000;
      else if (name.indexOf("google") !== -1) value += 500;
      qualityVoiceNames.forEach(function (quality, index) {
        if (name.indexOf(quality) !== -1) {
          value += 450 - (index * 40);
        }
      });
      if (voice.localService) value += 10;
      if (voice.default) value += 1;
      return value;
    }

    function preferredVoice() {
      return frenchVoices.slice().sort(function (first, second) {
        return voiceScore(second) - voiceScore(first);
      })[0] || null;
    }

    function splitLongSegment(segment) {
      var chunks = [];
      var remainder = segment.trim();
      while (remainder.length > 220) {
        var splitAt = remainder.lastIndexOf(", ", 220);
        if (splitAt < 120) splitAt = remainder.lastIndexOf("; ", 220);
        if (splitAt < 120) splitAt = remainder.lastIndexOf(" ", 220);
        if (splitAt < 1) splitAt = 220;
        chunks.push(remainder.slice(0, splitAt + 1).trim());
        remainder = remainder.slice(splitAt + 1).trim();
      }
      if (remainder) chunks.push(remainder);
      return chunks;
    }

    function chunks(text) {
      var normalized = text
        .replace(/\u00a0/g, " ")
        .replace(/^\s*--\s*/, "")
        .replace(/\s+--\s+/g, ". ")
        .replace(/\s+/g, " ")
        .trim();
      if (!normalized) return [];

      var sentences;
      if (typeof Intl !== "undefined" && Intl.Segmenter) {
        var segmenter = new Intl.Segmenter("fr", { granularity: "sentence" });
        sentences = Array.from(segmenter.segment(normalized)).map(
          function (part) { return part.segment.trim(); }
        );
      } else {
        sentences = normalized.match(/[^.!?…]+(?:[.!?…]+|$)/g) || [normalized];
      }

      return sentences.reduce(function (parts, sentence) {
        return parts.concat(splitLongSegment(sentence));
      }, []).filter(Boolean);
    }

    var supported = Boolean(synthesis && Utterance);
    if (supported) {
      refreshVoices();
      if (synthesis.addEventListener) {
        synthesis.addEventListener("voiceschanged", refreshVoices);
      } else {
        synthesis.onvoiceschanged = refreshVoices;
      }
    }

    return {
      synthesis: synthesis,
      Utterance: Utterance,
      supported: supported,
      refreshVoices: refreshVoices,
      preferredVoice: preferredVoice,
      isFeminineVoice: isFeminineVoice,
      chunks: chunks
    };
  })();
  window.HeureuxFrenchSpeech = frenchSpeech;

  /* ---------- CO French audio ---------- */
  (function () {
    var readers = Array.from(
      document.querySelectorAll("[data-co-audio-reader]")
    );
    if (!readers.length) return;

    var synthesis = frenchSpeech.synthesis;
    var Utterance = frenchSpeech.Utterance;
    var active = null;
    var playbackId = 0;

    function setStatus(reader, message) {
      var status = reader.querySelector("[data-co-audio-status]");
      if (status) status.textContent = message;
    }

    function setButtonLabel(button, label) {
      var node = button.querySelector("[data-co-audio-button-label]");
      if (node) node.textContent = label;
    }

    var PLAY_ICON = '<path d="M9 7.5 L17 12 L9 16.5 Z"></path>';
    var PAUSE_ICON =
      '<rect x="8.6" y="7" width="2.6" height="10" rx="1"></rect>' +
      '<rect x="12.8" y="7" width="2.6" height="10" rx="1"></rect>';

    function setButtonIcon(button, kind) {
      var svg = button.querySelector("svg");
      if (svg) svg.innerHTML = kind === "pause" ? PAUSE_ICON : PLAY_ICON;
    }

    function resetReader(reader, message) {
      reader.classList.remove("is-playing", "is-paused");
      reader.querySelectorAll("[data-co-audio-play]").forEach(function (button) {
        setButtonLabel(button, button.dataset.coAudioName === "question"
          ? "Question"
          : "Dialogue");
        setButtonIcon(button, "play");
        button.classList.remove("is-active");
        button.setAttribute("aria-pressed", "false");
        button.setAttribute(
          "aria-label",
          "Écouter " + (button.dataset.coAudioName === "question"
            ? "la question"
            : "le dialogue") + " en français"
        );
      });
      var stop = reader.querySelector("[data-co-audio-stop]");
      if (stop) stop.disabled = true;
      setStatus(reader, message || readyVoiceStatus());
    }

    function cancelPlayback(message) {
      var previous = active;
      active = null;
      playbackId += 1;
      if (
        previous ||
        synthesis.speaking ||
        synthesis.pending ||
        synthesis.paused
      ) {
        synthesis.cancel();
        synthesis.resume();
      }
      if (previous) resetReader(previous.reader, message);
    }

    function refreshVoiceStatus() {
      frenchSpeech.refreshVoices();
      readers.forEach(function (reader) {
        if (!active || active.reader !== reader) {
          setStatus(reader, readyVoiceStatus());
        }
      });
    }

    function readyVoiceStatus() {
      var voice = frenchSpeech.preferredVoice();
      if (!voice) return "Prêt à écouter · voix française";
      return (frenchSpeech.isFeminineVoice(voice)
        ? "Voix féminine · "
        : "Voix française · ") + voice.name;
    }

    function finishPlayback(message) {
      if (!active) return;
      var reader = active.reader;
      active = null;
      resetReader(reader, message || "Lecture terminée · cliquez pour réécouter");
    }

    function speakNext(id) {
      if (!active || active.id !== id || active.state !== "playing") return;
      if (active.index >= active.chunks.length) {
        finishPlayback();
        return;
      }

      var utterance = new Utterance(active.chunks[active.index]);
      var utteranceId = active.utteranceId + 1;
      active.utteranceId = utteranceId;
      var voice = frenchSpeech.preferredVoice();
      utterance.lang = "fr-FR";
      utterance.rate = active.rate;
      utterance.pitch = 1;
      if (voice) utterance.voice = voice;

      utterance.onend = function () {
        if (
          !active ||
          active.id !== id ||
          active.utteranceId !== utteranceId ||
          active.state !== "playing"
        ) return;
        active.index += 1;
        speakNext(id);
      };
      utterance.onerror = function () {
        if (
          !active ||
          active.id !== id ||
          active.utteranceId !== utteranceId ||
          active.state !== "playing"
        ) return;
        finishPlayback("Lecture indisponible. Vérifiez la voix de l’appareil.");
      };
      active.utterance = utterance;
      synthesis.speak(utterance);
    }

    function startPlayback(reader, button) {
      var target = button.dataset.coAudioTarget;
      var textNode = reader.querySelector(
        '[data-co-audio-text="' + target + '"]'
      );
      var chunks = frenchSpeech.chunks(textNode ? textNode.textContent : "");
      if (!chunks.length) {
        setStatus(reader, "Aucun texte français à lire.");
        return;
      }

      document.dispatchEvent(new CustomEvent("heureux:speech-start", {
        detail: { source: "comprehension-audio" }
      }));
      cancelPlayback();
      frenchSpeech.refreshVoices();
      var rateControl = reader.querySelector("[data-co-audio-rate]");
      var rate = rateControl ? parseFloat(rateControl.value) : 1;
      var id = playbackId + 1;
      playbackId = id;
      active = {
        id: id,
        reader: reader,
        button: button,
        chunks: chunks,
        index: 0,
        rate: rate,
        state: "playing",
        utteranceId: 0
      };

      reader.classList.add("is-playing");
      button.classList.add("is-active");
      button.setAttribute("aria-pressed", "true");
      button.setAttribute(
        "aria-label",
        "Mettre en pause " + (target === "question"
          ? "la question"
          : "le dialogue")
      );
      setButtonLabel(button, "Pause");
      setButtonIcon(button, "pause");
      var stop = reader.querySelector("[data-co-audio-stop]");
      if (stop) stop.disabled = false;
      setStatus(
        reader,
        "Lecture de " + (target === "question" ? "la question" : "du dialogue")
          + " en français…"
      );
      synthesis.resume();
      speakNext(id);
    }

    function pausePlayback() {
      if (!active || active.state !== "playing") return;
      active.state = "paused";
      active.utteranceId += 1;
      synthesis.cancel();
      synthesis.resume();
      active.reader.classList.remove("is-playing");
      active.reader.classList.add("is-paused");
      setButtonLabel(active.button, "Reprendre");
      setButtonIcon(active.button, "play");
      active.button.setAttribute("aria-label", "Reprendre la lecture");
      setStatus(active.reader, "Lecture en pause.");
    }

    function resumePlayback() {
      if (!active || active.state !== "paused") return;
      active.state = "playing";
      active.reader.classList.remove("is-paused");
      active.reader.classList.add("is-playing");
      setButtonLabel(active.button, "Pause");
      setButtonIcon(active.button, "pause");
      active.button.setAttribute("aria-label", "Mettre la lecture en pause");
      setStatus(active.reader, "Lecture reprise en français…");
      synthesis.resume();
      speakNext(active.id);
    }

    if (!synthesis || !Utterance) {
      readers.forEach(function (reader) {
        reader.classList.add("is-unavailable");
        setStatus(reader, "Audio français indisponible dans ce navigateur.");
      });
      return;
    }

    refreshVoiceStatus();
    if (synthesis.addEventListener) {
      synthesis.addEventListener("voiceschanged", refreshVoiceStatus);
    } else {
      synthesis.onvoiceschanged = refreshVoiceStatus;
    }
    document.addEventListener("heureux:speech-start", function (event) {
      if (
        active &&
        (!event.detail || event.detail.source !== "comprehension-audio")
      ) {
        cancelPlayback("Lecture remplacée par une autre lecture.");
      }
    });

    readers.forEach(function (reader) {
      reader.querySelectorAll("[data-co-audio-play]").forEach(function (button) {
        button.disabled = false;
        button.addEventListener("click", function () {
          if (active && active.reader === reader && active.button === button) {
            if (active.state === "paused") resumePlayback();
            else pausePlayback();
            return;
          }
          startPlayback(reader, button);
        });
      });

      var stop = reader.querySelector("[data-co-audio-stop]");
      if (stop) {
        stop.addEventListener("click", function () {
          if (active && active.reader === reader) {
            cancelPlayback("Lecture arrêtée.");
          }
        });
      }

      var rate = reader.querySelector("[data-co-audio-rate]");
      if (rate) {
        rate.disabled = false;
        rate.addEventListener("change", function () {
          if (active && active.reader === reader) {
            cancelPlayback("Vitesse réglée sur " + rate.options[rate.selectedIndex].text + ".");
          } else {
            setStatus(
              reader,
              "Vitesse réglée sur " + rate.options[rate.selectedIndex].text + "."
            );
          }
        });
      }
      resetReader(reader);
    });

    window.addEventListener("pagehide", function () {
      if (active) cancelPlayback();
    });
  })();

  /* ---------- Review session ---------- */
  var app = document.getElementById("review-app");
  if (!app) return;

  var nextUrl = app.dataset.nextUrl;
  var previousUrl = app.dataset.previousUrl;
  var answerUrl = app.dataset.answerUrl;
  var csrf = app.dataset.csrf;
  var scope = {};
  try { scope = JSON.parse(app.dataset.scope || "{}"); } catch (e) {}

  var frontEl = document.getElementById("card-front");
  var backEl = document.getElementById("card-back");
  var revealBtn = document.getElementById("reveal");
  var gradesEl = document.getElementById("grades");
  var kbdHint = document.getElementById("kbd-hint");
  var cardZone = document.getElementById("card-zone");
  var doneZone = document.getElementById("done-zone");
  var progressEl = document.getElementById("progress");
  var summaryEl = document.getElementById("session-summary");
  var previousButton = document.getElementById("previous-card");
  var currentButton = document.getElementById("current-card");
  var currentButtonLabel = document.getElementById("current-card-label");
  var previousLabel = document.getElementById("previous-card-label");
  var counters = {
    new: document.getElementById("c-new"),
    learn: document.getElementById("c-learn"),
    review: document.getElementById("c-review"),
    revisit: document.getElementById("c-revisit")
  };

  var currentId = null;
  var presentationToken = "";
  var revealed = false;
  var startTime = 0;
  var reviewed = 0;
  var revisited = 0;
  var sumElapsed = 0;
  var busy = false;
  var currentData = null;
  var currentView = null;
  var viewingPrevious = false;

  function params(extra) {
    var p = new URLSearchParams();
    Object.keys(scope).forEach(function (k) { p.append(k, scope[k]); });
    if (extra) Object.keys(extra).forEach(function (k) { p.append(k, extra[k]); });
    return p;
  }

  function updateCounters(c) {
    if (!c) return;
    if (counters.new) counters.new.textContent = c.new_available;
    if (counters.learn) counters.learn.textContent = c.learning_due;
    if (counters.review) counters.review.textContent = c.review_due;
    if (counters.revisit) counters.revisit.textContent = c.revisit_total;
    var remaining = c.total_due;
    var total = reviewed + remaining;
    var pct = total > 0 ? Math.round((reviewed / total) * 100) : 100;
    if (progressEl) progressEl.style.width = pct + "%";
  }

  function fmtTime(ms) {
    var s = Math.round(ms / 1000);
    if (s < 60) return s + " s";
    var m = Math.round(s / 60);
    return m + " min";
  }

  function setAnnotationRoots(sourceKey) {
    frontEl.dataset.annotationRoot = "";
    backEl.dataset.annotationRoot = "";
    frontEl.dataset.annotationSourceKey = sourceKey + ":front";
    backEl.dataset.annotationSourceKey = sourceKey + ":back";
  }

  function readJson(r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (r.status === 401 && data.login_url) {
        window.location.assign(data.login_url);
      }
      if (!r.ok) {
        var error = new Error(data.error || "Erreur de révision.");
        error.status = r.status;
        error.data = data;
        throw error;
      }
      return data;
    });
  }

  function showDone(data) {
    var c = data.counts;
    cardZone.classList.add("hidden");
    doneZone.classList.remove("hidden");
    currentId = null;
    presentationToken = "";
    currentData = null;
    viewingPrevious = false;
    if (previousButton) previousButton.disabled = !data.can_previous;
    if (previousButton) previousButton.classList.remove("hidden");
    if (currentButton) currentButton.classList.add("hidden");
    if (previousLabel) previousLabel.classList.add("hidden");
    if (summaryEl) {
      if (reviewed === 0) {
        summaryEl.textContent = "Aucune carte révisée dans cette session.";
      } else {
        var correct = reviewed - revisited;
        var pct = Math.round((100 * correct) / reviewed);
        summaryEl.innerHTML =
          "<strong>" + reviewed + "</strong> carte" + (reviewed > 1 ? "s" : "") +
          " · <strong>" + pct + "&nbsp;%</strong> correct" +
          (revisited ? " · <strong>" + revisited + "</strong> à revoir" : "") +
          " · " + fmtTime(sumElapsed);
      }
    }
    updateCounters(c);
    if (progressEl) progressEl.style.width = "100%";
  }

  function renderCard(data) {
    currentData = data;
    currentId = data.card_id;
    presentationToken = data.presentation_token;
    revealed = false;
    frontEl.innerHTML = data.front_html;
    backEl.innerHTML = data.back_html;
    setAnnotationRoots(data.annotation_source_key);
    backEl.classList.add("hidden");
    revealBtn.classList.remove("hidden");
    gradesEl.classList.add("hidden");
    updateCounters(data.counts);
    kbdHint.innerHTML = "Appuyez sur <kbd>Espace</kbd> pour révéler la réponse";
    if (previousButton) previousButton.disabled = !data.can_previous;
    if (previousButton) previousButton.classList.remove("hidden");
    if (currentButton) currentButton.classList.add("hidden");
    if (previousLabel) previousLabel.classList.add("hidden");
    viewingPrevious = false;
    startTime = Date.now();
  }

  function handleState(data) {
    if (data.done) { showDone(data); return; }
    cardZone.classList.remove("hidden");
    doneZone.classList.add("hidden");
    renderCard(data);
  }

  function reveal() {
    if (revealed || viewingPrevious) return;
    revealed = true;
    backEl.classList.remove("hidden");
    revealBtn.classList.add("hidden");
    gradesEl.classList.remove("hidden");
    kbdHint.innerHTML =
      "<kbd>1</kbd> Revoir &nbsp; <kbd>2</kbd> Correct";
  }

  function gradeError(error) {
    busy = false;
    kbdHint.textContent = error.message + " Rechargez la page.";
  }

  function fetchCurrentState() {
    return fetch(nextUrl + "?" + params().toString(), {
      headers: { "X-Requested-With": "fetch" }
    }).then(readJson);
  }

  function recoverGradeConflict(
    action,
    cardId,
    attemptedToken,
    elapsed,
    error,
    canRetry
  ) {
    var conflict = error.data || {};
    var replacementToken = conflict.presentation_token || "";
    if (
      canRetry &&
      conflict.current_card_id === cardId &&
      replacementToken &&
      replacementToken !== attemptedToken
    ) {
      presentationToken = replacementToken;
      submitGrade(action, cardId, replacementToken, elapsed, false);
      return;
    }

    fetchCurrentState()
      .then(function (data) {
        if (
          canRetry &&
          !data.done &&
          data.card_id === cardId &&
          data.presentation_token &&
          data.presentation_token !== attemptedToken
        ) {
          presentationToken = data.presentation_token;
          submitGrade(
            action,
            cardId,
            data.presentation_token,
            elapsed,
            false
          );
          return;
        }
        busy = false;
        handleState(data);
      })
      .catch(gradeError);
  }

  function submitGrade(action, cardId, token, elapsed, canRetry) {
    var body = params({
      card_id: cardId,
      action: action,
      elapsed_ms: elapsed,
      presentation_token: token
    });
    fetch(answerUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrf,
        "X-Requested-With": "fetch",
        "Content-Type": "application/x-www-form-urlencoded"
      },
      body: body.toString()
    })
      .then(readJson)
      .then(function (data) {
        reviewed += 1;
        if (action === "revisit") revisited += 1;
        sumElapsed += elapsed;
        busy = false;
        handleState(data);
      })
      .catch(function (error) {
        if (error.status === 409) {
          recoverGradeConflict(
            action,
            cardId,
            token,
            elapsed,
            error,
            canRetry
          );
          return;
        }
        gradeError(error);
      });
  }

  function grade(action) {
    if (!revealed || viewingPrevious || busy || currentId === null) return;
    busy = true;
    submitGrade(
      action,
      currentId,
      presentationToken,
      Date.now() - startTime,
      true
    );
  }

  function loadNext() {
    fetchCurrentState()
      .then(handleState)
      .catch(function (error) {
        kbdHint.textContent = error.message;
      });
  }

  function viewPrevious() {
    var fromDone = !doneZone.classList.contains("hidden");
    if (
      busy ||
      viewingPrevious ||
      !previousUrl ||
      (!currentData && !fromDone) ||
      previousButton.disabled
    ) {
      return;
    }
    busy = true;
    fetch(previousUrl + "?" + params().toString(), {
      headers: { "X-Requested-With": "fetch" }
    })
      .then(readJson)
      .then(function (data) {
        currentView = {
          done: fromDone,
          revealed: revealed,
          startTime: startTime,
          pausedAt: Date.now()
        };
        viewingPrevious = true;
        if (fromDone) {
          doneZone.classList.add("hidden");
          cardZone.classList.remove("hidden");
        }
        frontEl.innerHTML = data.front_html;
        backEl.innerHTML = data.back_html;
        setAnnotationRoots(data.annotation_source_key);
        backEl.classList.remove("hidden");
        revealBtn.classList.add("hidden");
        gradesEl.classList.add("hidden");
        previousButton.classList.add("hidden");
        currentButton.classList.remove("hidden");
        currentButtonLabel.textContent = fromDone
          ? "Retour au résumé"
          : "Retour à la carte actuelle";
        previousLabel.classList.remove("hidden");
        kbdHint.textContent = "Consultation uniquement · votre carte actuelle est conservée.";
        busy = false;
      })
      .catch(function (error) {
        busy = false;
        kbdHint.textContent = error.message;
      });
  }

  function returnToCurrent() {
    if (!viewingPrevious || !currentView) return;
    if (currentView.done) {
      cardZone.classList.add("hidden");
      doneZone.classList.remove("hidden");
      previousButton.classList.remove("hidden");
      currentButton.classList.add("hidden");
      currentButtonLabel.textContent = "Retour à la carte actuelle";
      previousLabel.classList.add("hidden");
      viewingPrevious = false;
      currentView = null;
      return;
    }
    if (!currentData) return;
    frontEl.innerHTML = currentData.front_html;
    backEl.innerHTML = currentData.back_html;
    setAnnotationRoots(currentData.annotation_source_key);
    revealed = currentView.revealed;
    startTime = currentView.startTime + (Date.now() - currentView.pausedAt);
    backEl.classList.toggle("hidden", !revealed);
    revealBtn.classList.toggle("hidden", revealed);
    gradesEl.classList.toggle("hidden", !revealed);
    previousButton.classList.remove("hidden");
    currentButton.classList.add("hidden");
    previousLabel.classList.add("hidden");
    kbdHint.innerHTML = revealed
      ? "<kbd>1</kbd> Revoir &nbsp; <kbd>2</kbd> Correct"
      : "Appuyez sur <kbd>Espace</kbd> pour révéler la réponse";
    viewingPrevious = false;
    currentView = null;
  }

  revealBtn.addEventListener("click", reveal);
  gradesEl.querySelectorAll(".grade").forEach(function (btn) {
    btn.addEventListener("click", function () {
      grade(btn.dataset.action);
    });
  });
  if (previousButton) previousButton.addEventListener("click", viewPrevious);
  if (currentButton) currentButton.addEventListener("click", returnToCurrent);

  document.addEventListener("keydown", function (e) {
    if (
      e.target &&
      e.target.closest &&
      e.target.closest(
        "input, textarea, select, button, a, [contenteditable='true'], [data-translation-panel], [data-note-panel]"
      )
    ) {
      return;
    }
    if (viewingPrevious) {
      return;
    }
    if (!revealed && (e.code === "Space" || e.code === "Enter")) {
      e.preventDefault();
      reveal();
    } else if (revealed && (e.key === "1" || e.key.toLowerCase() === "r")) {
      e.preventDefault();
      grade("revisit");
    } else if (revealed && (e.key === "2" || e.key.toLowerCase() === "c")) {
      e.preventDefault();
      grade("correct");
    }
  });

  loadNext();
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    busy = false;
    loadNext();
  });
})();
