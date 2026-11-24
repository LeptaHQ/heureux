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
      select: (provider) => choices.forEach((choice) =>
        choice.setAttribute("aria-pressed", String(choice.value === provider))),
    };
  };
})();
