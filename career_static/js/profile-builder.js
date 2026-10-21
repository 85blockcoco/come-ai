"use strict";

/**
 * Approbation champ par champ du profil candidat structuré (SK-10).
 *
 * Ce fichier est autonome : il ne dépend d'aucun autre script et ne modifie
 * jamais un fait sans une action explicite de la personne.  Chaque proposition
 * affiche sa source (page, offsets, citation) et propose cinq décisions :
 * approuver, corriger, rejeter, mettre de côté, rouvrir.
 *
 * Rien n'est envoyé à un fournisseur : tout est local.
 */

const CANDIDATE_PROFILE_ENDPOINT = "/api/career/candidate-profile";

const candidateProfileState = {
  profile: null,
  loading: false,
};

const candidateProfileElements = {
  panel: document.querySelector("#candidate-profile-panel"),
  status: document.querySelector("#candidate-profile-status"),
  summary: document.querySelector("#candidate-profile-summary"),
  usable: document.querySelector("#candidate-profile-usable"),
  facts: document.querySelector("#candidate-profile-facts"),
  empty: document.querySelector("#candidate-profile-empty"),
  documentForm: document.querySelector("#candidate-profile-document-form"),
  textForm: document.querySelector("#candidate-profile-text-form"),
  textValue: document.querySelector("#candidate-profile-text-value"),
  replaceToggle: document.querySelector("#candidate-profile-replace"),
  deleteButton: document.querySelector("#candidate-profile-delete"),
  exportLink: document.querySelector("#candidate-profile-export"),
};

function candidateProfileElement(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function candidateProfileApi(url, options = {}) {
  const formData = options.body instanceof FormData;
  const response = await fetch(url, {
    headers: options.body && !formData ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  let body = {};
  if (contentType.includes("application/json")) {
    try { body = await response.json(); } catch (_) { body = {}; }
  }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "L’action Career n’a pas abouti.";
    const suffix = body.error_id ? ` (référence ${body.error_id})` : "";
    throw new Error(detail + suffix);
  }
  return body;
}

function setCandidateProfileStatus(value = "", error = false) {
  const node = candidateProfileElements.status;
  if (!node) return;
  node.textContent = String(value || "");
  node.classList.toggle("error", Boolean(error));
  node.setAttribute("role", error ? "alert" : "status");
}

function candidateProfileDecisionLabels() {
  return {
    approved: "Approuver",
    modified: "Corriger",
    rejected: "Rejeter",
    suspended: "Mettre de côté",
    proposed: "Rouvrir",
  };
}

function candidateProfileKindLabels() {
  return {
    identity: "Identité",
    contact: "Coordonnées",
    skill: "Compétence",
    experience: "Expérience",
    education: "Formation",
    language: "Langue",
    certification: "Certification",
    project: "Projet",
  };
}

function renderCandidateProfileSummary(profile) {
  const summary = candidateProfileElements.summary;
  const usable = candidateProfileElements.usable;
  if (!summary || !usable) return;
  const counts = profile.counts || {};
  summary.replaceChildren();
  const totals = [
    ["À vérifier", counts.proposed || 0],
    ["Approuvés", counts.approved || 0],
    ["Corrigés", counts.modified || 0],
    ["Rejetés", counts.rejected || 0],
    ["Mis de côté", counts.suspended || 0],
  ];
  totals.forEach(([label, value]) => {
    const item = candidateProfileElement("span", "", "candidate-profile-counter");
    item.append(candidateProfileElement("strong", String(value)), candidateProfileElement("span", label));
    summary.append(item);
  });

  usable.replaceChildren();
  const groups = profile.usable || {};
  const entries = Object.entries(groups).filter(([, values]) => Array.isArray(values) && values.length);
  if (!entries.length) {
    usable.append(candidateProfileElement(
      "p",
      "Aucun fait approuvé pour l’instant : rien ne peut justifier une candidature.",
      "empty-state compact-empty",
    ));
    return;
  }
  usable.append(candidateProfileElement(
    "p",
    "Seuls ces faits approuvés ou corrigés peuvent justifier une candidature.",
    "panel-help",
  ));
  const kindLabels = candidateProfileKindLabels();
  entries.forEach(([kind, values]) => {
    const block = candidateProfileElement("div", "", "candidate-profile-usable-group");
    block.append(candidateProfileElement("h4", kindLabels[kind] || kind));
    const list = candidateProfileElement("ul");
    values.forEach((value) => list.append(candidateProfileElement("li", value)));
    block.append(list);
    usable.append(block);
  });
}

function renderCandidateProfileFact(fact) {
  const kindLabels = candidateProfileKindLabels();
  const decisionLabels = candidateProfileDecisionLabels();
  const card = candidateProfileElement("article", "", "candidate-fact");
  card.dataset.status = fact.status;
  card.dataset.factId = fact.id;

  const head = candidateProfileElement("div", "", "candidate-fact-head");
  head.append(candidateProfileElement("span", kindLabels[fact.kind] || fact.kind, "candidate-fact-kind"));
  const status = candidateProfileElement("span", fact.status_label || fact.status, "candidate-fact-status");
  status.dataset.status = fact.status;
  head.append(status);
  if (fact.is_ocr) {
    head.append(candidateProfileElement("span", "OCR", "candidate-fact-tag"));
  }
  card.append(head);

  card.append(candidateProfileElement("p", fact.label || fact.value, "candidate-fact-label"));
  if (fact.value && fact.value !== fact.label) {
    card.append(candidateProfileElement("p", fact.value, "candidate-fact-value"));
  }

  const provenance = fact.provenance;
  if (provenance) {
    const details = candidateProfileElement("details", "", "candidate-fact-evidence");
    const page = provenance.page ? `page ${provenance.page}` : "page inconnue";
    details.append(candidateProfileElement("summary", `Source (${page})`));
    details.append(candidateProfileElement("blockquote", provenance.quote || "—"));
    const offsets = candidateProfileElement(
      "p",
      `Caractères ${provenance.start_offset}–${provenance.end_offset}`,
      "candidate-fact-offsets",
    );
    details.append(offsets);
    if (provenance.source_name) {
      details.append(candidateProfileElement("p", provenance.source_name, "candidate-fact-offsets"));
    }
    card.append(details);
  }

  const actions = candidateProfileElement("div", "", "candidate-fact-actions");
  const input = document.createElement("input");
  input.type = "text";
  input.value = fact.value || "";
  input.maxLength = 4000;
  input.setAttribute("aria-label", `Corriger la valeur de ${fact.label || fact.value}`);
  input.className = "candidate-fact-input";
  actions.append(input);

  const allowed = fact.status === "proposed"
    ? ["approved", "modified", "rejected", "suspended"]
    : fact.status === "rejected" || fact.status === "suspended"
      ? ["proposed", "modified", "rejected"]
      : ["approved", "modified", "rejected", "suspended"];

  allowed.forEach((decision) => {
    const button = candidateProfileElement("button", decisionLabels[decision] || decision, "quiet-button");
    button.type = "button";
    button.dataset.decision = decision;
    button.addEventListener("click", () => decideCandidateProfileFact(fact.id, decision, input.value));
    actions.append(button);
  });

  const remove = candidateProfileElement("button", "Supprimer", "quiet-button danger-text");
  remove.type = "button";
  remove.dataset.action = "delete";
  remove.addEventListener("click", () => deleteCandidateProfileFact(fact.id));
  actions.append(remove);

  card.append(actions);
  return card;
}

function renderCandidateProfile(profile) {
  candidateProfileState.profile = profile;
  const list = candidateProfileElements.facts;
  const empty = candidateProfileElements.empty;
  if (!list) return;
  list.replaceChildren();
  const facts = Array.isArray(profile.facts) ? profile.facts : [];
  facts.forEach((fact) => list.append(renderCandidateProfileFact(fact)));
  if (empty) empty.hidden = facts.length > 0;
  renderCandidateProfileSummary(profile);
  const problems = Array.isArray(profile.problems) ? profile.problems : [];
  if (problems.length) {
    setCandidateProfileStatus(problems.join(" "), true);
  } else {
    setCandidateProfileStatus("");
  }
  const hasProfile = facts.length > 0;
  if (candidateProfileElements.deleteButton) candidateProfileElements.deleteButton.hidden = !hasProfile;
  if (candidateProfileElements.exportLink) candidateProfileElements.exportLink.hidden = !hasProfile;
}

async function loadCandidateProfile() {
  if (candidateProfileState.loading) return;
  candidateProfileState.loading = true;
  try {
    const profile = await candidateProfileApi(CANDIDATE_PROFILE_ENDPOINT);
    renderCandidateProfile(profile);
  } catch (error) {
    setCandidateProfileStatus(error.message, true);
  } finally {
    candidateProfileState.loading = false;
  }
}

async function decideCandidateProfileFact(factId, decision, value) {
  try {
    setCandidateProfileStatus("Décision enregistrée…");
    const profile = await candidateProfileApi(
      `${CANDIDATE_PROFILE_ENDPOINT}/facts/${encodeURIComponent(factId)}/decision`,
      { method: "POST", body: JSON.stringify({ decision, value: decision === "modified" ? value : "" }) },
    );
    renderCandidateProfile(profile);
    setCandidateProfileStatus("Décision enregistrée.");
  } catch (error) {
    setCandidateProfileStatus(error.message, true);
  }
}

async function deleteCandidateProfileFact(factId) {
  try {
    const profile = await candidateProfileApi(
      `${CANDIDATE_PROFILE_ENDPOINT}/facts/${encodeURIComponent(factId)}`,
      { method: "DELETE" },
    );
    renderCandidateProfile(profile);
    setCandidateProfileStatus("Fait supprimé.");
  } catch (error) {
    setCandidateProfileStatus(error.message, true);
  }
}

async function deleteCandidateProfile() {
  try {
    const profile = await candidateProfileApi(CANDIDATE_PROFILE_ENDPOINT, { method: "DELETE" });
    renderCandidateProfile(profile);
    setCandidateProfileStatus("Profil candidat supprimé.");
  } catch (error) {
    setCandidateProfileStatus(error.message, true);
  }
}

function bindCandidateProfileEvents() {
  const documentForm = candidateProfileElements.documentForm;
  if (documentForm) {
    documentForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(documentForm);
      const replace = candidateProfileElements.replaceToggle?.checked ? "true" : "false";
      formData.set("replace", replace);
      try {
        setCandidateProfileStatus("Lecture locale du document…");
        const profile = await candidateProfileApi(
          `${CANDIDATE_PROFILE_ENDPOINT}/proposals/document`,
          { method: "POST", body: formData },
        );
        renderCandidateProfile(profile);
        setCandidateProfileStatus("Propositions lues localement. Rien n’est approuvé : vérifie chaque champ.");
        documentForm.reset();
      } catch (error) {
        setCandidateProfileStatus(error.message, true);
      }
    });
  }

  const textForm = candidateProfileElements.textForm;
  if (textForm) {
    textForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = candidateProfileElements.textValue?.value || "";
      if (!text.trim()) {
        setCandidateProfileStatus("Colle d’abord le texte du profil.", true);
        return;
      }
      try {
        setCandidateProfileStatus("Lecture locale du texte…");
        const profile = await candidateProfileApi(`${CANDIDATE_PROFILE_ENDPOINT}/proposals`, {
          method: "POST",
          body: JSON.stringify({
            text,
            filename: "texte-profil",
            replace: Boolean(candidateProfileElements.replaceToggle?.checked),
          }),
        });
        renderCandidateProfile(profile);
        setCandidateProfileStatus("Propositions lues localement. Rien n’est approuvé : vérifie chaque champ.");
        if (candidateProfileElements.textValue) candidateProfileElements.textValue.value = "";
      } catch (error) {
        setCandidateProfileStatus(error.message, true);
      }
    });
  }

  if (candidateProfileElements.deleteButton) {
    candidateProfileElements.deleteButton.addEventListener("click", deleteCandidateProfile);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  if (!candidateProfileElements.panel) return;
  bindCandidateProfileEvents();
  loadCandidateProfile();
});

window.careerProfileBuilder = {
  reload: loadCandidateProfile,
};
