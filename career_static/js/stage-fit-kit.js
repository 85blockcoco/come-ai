/* Stage Fit Kit UI (SPEC-024) — local, no auto-send. */
(function () {
  "use strict";
  const root = document.querySelector("[data-stage-fit-kit]");
  if (!root) return;
  const status = root.querySelector(".stage-fit-status");
  const launch = root.querySelector(".stage-fit-launch");
  const kitIdInput = root.querySelector(".stage-fit-kit-id");
  const exportLink = root.querySelector(".stage-fit-export");

  async function launchKit() {
    const offerId = root.getAttribute("data-offer-id");
    if (!offerId) return;
    if (status) status.textContent = "Génération du kit…";
    try {
      const response = await fetch(`/stagefit/kit/${encodeURIComponent(offerId)}`, { method: "POST" });
      const data = await response.json();
      if (kitIdInput) kitIdInput.value = data.kit_id || "";
      if (exportLink && data.kit_id) exportLink.href = `/stagefit/kit/${data.kit_id}/export`;
      if (status) status.textContent = "Kit prêt (envoi manuel uniquement).";
    } catch (err) {
      if (status) status.textContent = "Échec : " + (err && err.message ? err.message : err);
    }
  }

  if (launch) launch.addEventListener("click", launchKit);
})();
