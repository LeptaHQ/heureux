(() => {
  const timer = document.querySelector("[data-writing-timer]");
  const form = document.querySelector("[data-writing-form]");
  if (!timer || !form) return;

  const output = timer.querySelector("strong");
  const initialRemaining = Number(timer.dataset.remaining || 0) * 1000;
  const startedAt = window.performance.now();
  let input = form.querySelector("[data-writing-word-input]");

  const render = () => {
    const remaining = Math.ceil((initialRemaining - (window.performance.now() - startedAt)) / 1000);
    const elapsed = Math.abs(remaining);
    const minutes = Math.floor(elapsed / 60);
    const seconds = elapsed % 60;
    output.textContent = `${remaining < 0 ? "-" : ""}${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    timer.classList.toggle("is-warning", remaining < 180);
  };

  render();
  window.setInterval(render, 1000);

  if (input) {
    form.querySelectorAll("[data-writing-word-input]").forEach((field) => {
      field.addEventListener("focus", () => { input = field; });
    });
    form.querySelectorAll("[data-writing-character]").forEach((button) => {
      button.addEventListener("click", () => {
        const start = input.selectionStart ?? input.value.length;
        const end = input.selectionEnd ?? start;
        input.focus();
        input.setRangeText(button.dataset.writingCharacter || "", start, end, "end");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
  }
})();
