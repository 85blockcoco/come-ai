/* Controlled automation dashboard (SPEC-016). Local-first, no automatic submission. */
(function () {
  "use strict";
  const root = document.getElementById("automation-dashboard");
  if (!root) return;

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }

  async function refresh() {
    try {
      const dashboard = await fetchJson("/automation/dashboard");
      root.innerHTML = "";
      const header = document.createElement("h2");
      header.textContent = "Automatisation contrôlée";
      root.appendChild(header);
      const stats = document.createElement("p");
      stats.textContent = "Workflows: " + (dashboard.total_workflows || 0) +
        " | actifs: " + (dashboard.active_workflows || 0) +
        " | terminés: " + (dashboard.completed_workflows || 0) +
        " | en attente humaine: " + (dashboard.waiting_human || 0);
      root.appendChild(stats);
    } catch (err) {
      root.textContent = "Erreur: " + err.message;
    }
  }

  refresh();
  setInterval(refresh, 5000);
})();
