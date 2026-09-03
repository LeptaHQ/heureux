(() => {
  const input = document.querySelector("[data-writing-word-input]");
  const status = document.querySelector("[data-writing-word-status]");
  if (!input || !status) return;

  const minimum = Number(input.dataset.wordMin || 0);
  const maximum = Number(input.dataset.wordMax || 0);
  const countWords = (value) => {
    const matches = value
      .trim()
      .match(/[\p{L}\p{N}]+(?:[’'-][\p{L}\p{N}]+)*/gu);
    return matches ? matches.length : 0;
  };
  const update = () => {
    const count = countWords(input.value);
    let guidance = "dans la limite";
    if (count < minimum) guidance = `${minimum - count} mot${minimum - count > 1 ? "s" : ""} à ajouter`;
    if (count > maximum) guidance = `${count - maximum} mot${count - maximum > 1 ? "s" : ""} à retirer`;
    status.textContent = `${count} mot${count > 1 ? "s" : ""} · ${guidance} · objectif ${minimum}–${maximum}`;
    status.classList.toggle("auth-error", count > 0 && (count < minimum || count > maximum));
  };

  input.addEventListener("input", update);
  update();
})();
