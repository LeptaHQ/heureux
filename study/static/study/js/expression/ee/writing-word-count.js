(() => {
  const inputs = [...document.querySelectorAll("[data-writing-word-input]")];
  const totalStatus = document.querySelector("[data-writing-word-total-status]");
  if (!inputs.length && !totalStatus) return;

  const countWords = (value) => {
    const matches = value
      .trim()
      .match(/[\p{L}\p{N}]+(?:[’'-][\p{L}\p{N}]+)*/gu);
    return matches ? matches.length : 0;
  };
  const updateStatus = (input, status) => {
    const minimum = Number(input.dataset.wordMin || 0);
    const maximum = Number(input.dataset.wordMax || 0);
    const count = countWords(input.value);
    let guidance = "dans la limite";
    if (count < minimum) guidance = `${minimum - count} mot${minimum - count > 1 ? "s" : ""} à ajouter`;
    if (count > maximum) guidance = `${count - maximum} mot${count - maximum > 1 ? "s" : ""} à retirer`;
    status.textContent = `${count} mot${count > 1 ? "s" : ""} · ${guidance} · objectif ${minimum}–${maximum}`;
    status.classList.toggle("auth-error", count > 0 && (count < minimum || count > maximum));
  };
  const update = () => {
    inputs.forEach((input) => {
      const status = input
        .closest(".response-edit-field")
        ?.querySelector("[data-writing-word-status]");
      if (status) updateStatus(input, status);
    });
    if (totalStatus) {
      const totalInputs = document.querySelectorAll(
        "[data-writing-word-total-input]"
      );
      updateStatus(
        {
          value: [...totalInputs].map((input) => input.value).join(" "),
          dataset: totalStatus.dataset,
        },
        totalStatus,
      );
    }
  };

  document
    .querySelectorAll(
      "[data-writing-word-input], [data-writing-word-total-input]"
    )
    .forEach((input) => input.addEventListener("input", update));
  update();
})();
