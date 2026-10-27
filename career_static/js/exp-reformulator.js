// Experience reformulator UI helper (SPEC-020).
// Compares variants and applies a chosen one. No network calls beyond fetch.

(function () {
  "use strict";

  function renderVariants(container, variants) {
    if (!container) return;
    container.innerHTML = "";
    variants.forEach(function (v, idx) {
      var card = document.createElement("div");
      card.className = "exp-variant";
      card.dataset.index = String(idx);
      var score = (v.ats_score || 0).toFixed(2);
      card.innerHTML =
        "<p class='exp-text'>" + (v.text_fr || "") + "</p>" +
        "<small>ATS " + score + " · jury " + (v.jury_score || 0).toFixed(2) + "</small>" +
        "<button type='button' class='exp-apply'>Appliquer</button>";
      container.appendChild(card);
    });
  }

  async function applyVariant(baseUrl, bulletId) {
    var res = await fetch(baseUrl + "/reformulate/" + encodeURIComponent(bulletId) + "/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted: true }),
    });
    return res.json();
  }

  window.ExpReformulator = { renderVariants: renderVariants, applyVariant: applyVariant };
})();
