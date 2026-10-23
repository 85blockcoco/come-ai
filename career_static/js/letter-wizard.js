// Letter wizard (SPEC-022) — minimal client helper
(function () {
  "use strict";
  window.LetterWizard = window.LetterWizard || {};
  window.LetterWizard.generate = async function (offerId, payload) {
    const res = await fetch(`/letter/generate/${encodeURIComponent(offerId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    return res.json();
  };
})();
