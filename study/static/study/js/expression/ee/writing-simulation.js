(() => {
  const timer = document.querySelector("[data-writing-timer]");
  const form = document.querySelector("[data-writing-form]");
  const submit = document.querySelector("[data-writing-submit]");
  if (!timer || !form || !submit) return;

  const output = timer.querySelector("strong");
  const initialRemaining = Number(timer.dataset.remaining || 0) * 1000;
  const startedAt = window.performance.now();
  const input = form.querySelector("[data-writing-word-input]");
  let submitted = false;

  const render = () => {
    const remaining = Math.max(
      0,
      Math.ceil((initialRemaining - (window.performance.now() - startedAt)) / 1000),
    );
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    output.textContent = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    timer.classList.toggle("is-warning", remaining > 0 && remaining < 180);
    if (remaining > 0 || submitted) return;
    submitted = true;
    output.textContent = "00:00";
    submit.click();
  };

  render();
  window.setInterval(render, 1000);

  if (input) {
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
