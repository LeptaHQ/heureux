(() => {
  "use strict";
  window.HeureuxAssessmentPicker = (button, onSelect) => {
    const menu = document.getElementById(button.getAttribute("aria-controls"));
    if (!menu) return null;
    const choices = [...menu.querySelectorAll("button[value]")];
    const toggle = (open) => {
      menu.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    };
    button.addEventListener("click", () => toggle(menu.hidden));
    document.addEventListener("click", (event) => {
      if (!menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) toggle(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !menu.hidden) {
        event.preventDefault();
        toggle(false);
        button.focus();
      }
    });
    choices.forEach((choice) => choice.addEventListener("click", () => {
      toggle(false);
      button.focus();
      onSelect(choice.value, choice.textContent.trim());
    }));
    return {
      close: () => toggle(false),
      label: (provider) => choices.find((choice) => choice.value === provider)?.textContent.trim(),
      select: (provider) => choices.forEach((choice) =>
        choice.setAttribute("aria-pressed", String(choice.value === provider))),
    };
  };

  window.HeureuxAssessmentRefresh = (request) => {
    const controls = document.getElementById("lv-assessment-refresh");
    if (!controls) return null;
    const button = controls.querySelector("button");
    const disclosure = document.getElementById("lv-refresh-disclosure");
    const providers = controls.dataset.providers.split(" ");
    const version = Number(controls.dataset.graderVersion);
    const isOutdated = (report) => Boolean(report) &&
      (report.graderVersion == null || (Number.isInteger(report.graderVersion) && report.graderVersion < version));
    let provider, label;
    button.addEventListener("click", () => request(provider, label));
    return {
      isOutdated,
      select(report, selected, name) {
        provider = selected;
        label = name;
        controls.hidden = !providers.includes(provider) || !isOutdated(report);
        if (disclosure) {
          disclosure.hidden = controls.hidden;
          if (!disclosure.hidden) {
            const via = provider.startsWith("copilot-") ? " via GitHub Copilot" : "";
            disclosure.textContent = `Envoi à ${label}${via} : ${disclosure.dataset.refreshInputs}.`;
          }
        }
        return !controls.hidden;
      },
      setBusy: (busy) => { button.disabled = busy; },
    };
  };
})();
