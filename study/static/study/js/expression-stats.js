(() => {
  "use strict";

  document.querySelectorAll("[data-expression-stats]").forEach((panel) => {
    const content = panel.querySelector("[data-expression-stats-content]");
    const status = panel.querySelector("[data-expression-stats-status]");
    const message = panel.querySelector("[data-expression-stats-message]");
    const retry = panel.querySelector("[data-expression-stats-retry]");
    const placeholders = Array.from(panel.querySelectorAll("[data-expression-stats-placeholder]"))
      .map((node) => [node, node.textContent]);
    let loading = false;

    async function loadStats() {
      if (loading) return;
      loading = true;
      retry.hidden = true;
      panel.setAttribute("aria-busy", "true");
      message.textContent = "Chargement du contenu et de la progression… Les parcours restent accessibles.";
      placeholders.forEach(([node, text]) => { node.textContent = text; });
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 30000);
      try {
        const response = await fetch(panel.dataset.expressionStats, {
          signal: controller.signal,
          credentials: "same-origin",
          cache: "no-store",
          headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
        });
        if (!response.ok) throw new Error("Statistics unavailable");
        const data = await response.json();
        const metrics = panel.querySelector("[data-expression-stats-metrics]");
        if (typeof data.html !== "string" || (metrics && typeof data.metrics !== "string")) {
          throw new Error("Invalid statistics");
        }
        const focusedLink = content.contains(document.activeElement)
          ? document.activeElement.closest("a")
          : null;
        const href = focusedLink?.getAttribute("href");
        content.innerHTML = data.html;
        if (metrics) metrics.innerHTML = data.metrics;
        if (href) {
          Array.from(content.querySelectorAll("a")).find((link) => link.getAttribute("href") === href)?.focus();
        }
        status.hidden = true;
      } catch {
        message.textContent = "La progression n’a pas pu être chargée. Les parcours restent accessibles.";
        placeholders.forEach(([node]) => { node.textContent = "Statistiques indisponibles"; });
        retry.hidden = false;
      } finally {
        window.clearTimeout(timeout);
        loading = false;
        panel.setAttribute("aria-busy", "false");
      }
    }

    retry.addEventListener("click", loadStats);
    loadStats();
  });
})();
