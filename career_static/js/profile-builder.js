/* Côme AI Career — Profil candidat (SK-10).
 *
 * Approbation champ par champ des faits extraits d’un CV.
 *
 * Règles du module :
 *  - rien n’est approuvé automatiquement, l’interface ne fait que demander ;
 *  - chaque fait affiche sa source exacte (page, offsets, citation) ;
 *  - un fait refusé, suspendu ou encore en attente ne peut pas justifier
 *    une candidature : c’est le serveur qui applique cette règle.
 *
 * Le script est autonome : il ne dépend pas du chargement de career.js et
 * n'utilise ni HTML brut ni boîte de dialogue système.
 */

const PB_STATUS_LABELS = {
  proposed: "À valider",
  approved: "Approuvé",
  rejected: "Refusé",
  modified: "Corrigé",
  suspended: "Suspendu",
};

const PB_KIND_LABELS = {
  identity: "Identité",
  contact: "Coordonnées",
  skill: "Compétences",
  experience: "Expériences",
  education: "Formation",
  language: "Langues",
};

const PB_KIND_ORDER = ["identity", "contact", "skill", "language", "education", "experience"];

let pbProfile = null;

function pbElement(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function pbApi(url, options = {}) {
  const formData = options.body instanceof FormData;
  const response = await fetch(url, {
    headers: options.body && !formData ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  let body = {};
  if (contentType.includes("application/json")) {
    try {
      body = await response.json();
    } catch (_error) {
      body = {};
    }
  }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "L’action Career n’a pas abouti.";
    throw new Error(detail);
  }
  return body;
}

function pbMessage(value = "", isError = false) {
  const node = document.querySelector("#candidate-profile-message");
  if (!node) return;
  node.textContent = String(value || "");
  node.classList.toggle("error", Boolean(isError));
  node.hidden = !value;
}

function pbProvenanceText(fact) {
  const provenance = fact.provenance || {};
  const parts = [];
  if (provenance.page !== null && provenance.page !== undefined) {
    parts.push(`Page ${provenance.page}`);
  }
  if (provenance.extraction === "ocr") {
    parts.push("lu par OCR local");
  }
  const start = provenance.start_offset;
  const end = provenance.end_offset;
  if (Number.isInteger(start) && Number.isInteger(end)) {
    parts.push(`caractères ${start}–${end}`);
  }
  const quote = String(provenance.quote || "").trim();
  if (quote) {
    parts.push(`« ${quote.slice(0, 180)}${quote.length > 180 ? "…" : ""} »`);
  }
  return parts.join(" · ");
}

function pbStatusBadge(fact) {
  const badge = pbElement("span", PB_STATUS_LABELS[fact.status] || fact.status, "fact-status");
  badge.dataset.status = fact.status;
  return badge;
}

function pbActionButton(label, handler, className = "quiet-button") {
  const button = pbElement("button", label, className);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

function pbFactCard(fact) {
  const card = pbElement("article", "", "candidate-fact");
  card.dataset.factId = fact.id;
  card.dataset.status = fact.status;
  card.dataset.kind = fact.kind;

  const header = pbElement("header", "", "candidate-fact-header");
  const title = pbElement("div", "", "candidate-fact-title");
  title.append(pbElement("strong", fact.label || fact.kind));
  if (fact.requires_review) {
    title.append(pbElement("span", "OCR : à vérifier", "fact-review-flag"));
  }
  header.append(title, pbStatusBadge(fact));

  const value = pbElement("p", fact.value || "", "candidate-fact-value");
  const provenance = pbElement("p", pbProvenanceText(fact), "candidate-fact-provenance");
  if (fact.corrected && fact.original_value) {
    provenance.append(pbElement("br"));
    provenance.append(pbElement("span", `Valeur extraite : ${fact.original_value}`, "fact-original"));
  }

  const actions = pbElement("div", "", "candidate-fact-actions");
  if (fact.status !== "approved" && fact.status !== "modified") {
    actions.append(pbActionButton("Approuver", () => pbReviewFact(fact.id, { status: "approved" })));
  }
  if (fact.status !== "rejected") {
    actions.append(pbActionButton("Refuser", () => pbReviewFact(fact.id, { status: "rejected" })));
  }
  if (fact.status !== "suspended") {
    actions.append(pbActionButton("Suspendre", () => pbReviewFact(fact.id, { status: "suspended" })));
  }
  if (fact.status === "rejected" || fact.status === "suspended") {
    actions.append(pbActionButton("Remettre à valider", () => pbReviewFact(fact.id, { status: "proposed" })));
  }
  actions.append(pbActionButton("Corriger", () => pbOpenEditor(card, fact)));
  actions.append(pbActionButton("Supprimer", () => pbDeleteFact(fact.id), "quiet-button danger-button"));

  card.append(header, value, provenance, actions);
  return card;
}

function pbOpenEditor(card, fact) {
  const existing = card.querySelector(".candidate-fact-editor");
  if (existing) {
    existing.remove();
    return;
  }
  const editor = pbElement("div", "", "candidate-fact-editor");
  const input = document.createElement("textarea");
  input.rows = 3;
  input.maxLength = 4000;
  input.value = fact.value || "";
  input.setAttribute("aria-label", `Corriger ${fact.label || fact.kind}`);
  const actions = pbElement("div", "", "candidate-fact-actions");
  actions.append(
    pbActionButton("Enregistrer la correction", async () => {
      const value = input.value.trim();
      if (!value) {
        pbMessage("La correction ne peut pas être vide.", true);
        return;
      }
      await pbReviewFact(fact.id, { value });
    }),
    pbActionButton("Annuler", () => editor.remove()),
  );
  editor.append(input, actions);
  card.append(editor);
}

function pbRenderSummary(payload) {
  const container = document.querySelector("#candidate-profile-summary");
  if (!container) return;
  container.replaceChildren();
  const counts = payload.counts || {};
  const total = Number(payload.total || 0);
  if (!total) return;
  const line = pbElement(
    "p",
    `${total} fait${total > 1 ? "s" : ""} extrait${total > 1 ? "s" : ""} · ${counts.approved || 0} approuvé${(counts.approved || 0) > 1 ? "s" : ""} · ${counts.proposed || 0} à valider`,
    "candidate-profile-counts",
  );
  container.append(line);
  const sourceDocument = payload.document || {};
  if (sourceDocument.source_document) {
    container.append(pbElement("p", `Source : ${sourceDocument.source_document}`, "candidate-profile-source"));
  }
  (sourceDocument.warnings || []).forEach((warning) => {
    container.append(pbElement("p", warning, "candidate-profile-warning"));
  });

  const active = payload.active_profile || {};
  const activeParts = [];
  ["skills", "languages", "education", "experience"].forEach((field) => {
    const value = String(active[field] || "").trim();
    if (value) activeParts.push(value);
  });
  const activeTitle = pbElement("p", "Profil actif (uniquement les faits approuvés)", "candidate-profile-active-title");
  container.append(activeTitle);
  if (!activeParts.length) {
    container.append(
      pbElement("p", "Aucun fait approuvé : ton profil actif est vide.", "candidate-profile-active-empty"),
    );
    return;
  }
  activeParts.forEach((value) => {
    container.append(pbElement("p", value, "candidate-profile-active-value"));
  });
}

function pbRenderFacts(payload) {
  const container = document.querySelector("#candidate-profile-facts");
  const empty = document.querySelector("#candidate-profile-empty");
  if (!container) return;
  container.replaceChildren();
  const facts = Array.isArray(payload.facts) ? payload.facts : [];
  if (empty) empty.hidden = facts.length > 0;
  if (!facts.length) return;

  const groups = new Map();
  facts.forEach((fact) => {
    const kind = fact.kind || "other";
    if (!groups.has(kind)) groups.set(kind, []);
    groups.get(kind).push(fact);
  });
  const ordered = [...PB_KIND_ORDER.filter((kind) => groups.has(kind)), ...[...groups.keys()].filter((kind) => !PB_KIND_ORDER.includes(kind))];
  ordered.forEach((kind) => {
    const section = pbElement("section", "", "candidate-fact-group");
    section.append(pbElement("h4", PB_KIND_LABELS[kind] || kind, "candidate-fact-group-title"));
    groups.get(kind).forEach((fact) => section.append(pbFactCard(fact)));
    container.append(section);
  });
}

function pbRender(payload) {
  pbProfile = payload;
  pbRenderSummary(payload);
  pbRenderFacts(payload);
}

async function pbLoadProfile() {
  try {
    const payload = await pbApi("/api/career/candidate-profile");
    pbRender(payload);
  } catch (error) {
    pbMessage(error.message, true);
  }
}

async function pbReviewFact(factId, changes) {
  try {
    const payload = await pbApi(`/api/career/candidate-profile/facts/${encodeURIComponent(factId)}`, {
      method: "PATCH",
      body: JSON.stringify(changes),
    });
    pbRender(payload);
    pbMessage("Fait mis à jour.");
  } catch (error) {
    pbMessage(error.message, true);
  }
}

async function pbDeleteFact(factId) {
  try {
    const payload = await pbApi(`/api/career/candidate-profile/facts/${encodeURIComponent(factId)}`, {
      method: "DELETE",
    });
    pbRender(payload);
    pbMessage("Fait supprimé.");
  } catch (error) {
    pbMessage(error.message, true);
  }
}

async function pbBuildFromDocument() {
  const input = document.querySelector("#candidate-profile-file");
  if (!input || !input.files || !input.files.length) {
    pbMessage("Choisis d’abord un document à analyser.", true);
    return;
  }
  const form = new FormData();
  form.append("document", input.files[0]);
  form.append("source_kind", "cv");
  try {
    const payload = await pbApi("/api/career/candidate-profile/document", { method: "POST", body: form });
    pbRender(payload);
    input.value = "";
    pbMessage(`${payload.total} fait(s) proposé(s). Rien n’est approuvé : valide chaque champ.`);
  } catch (error) {
    pbMessage(error.message, true);
  }
}

async function pbBuildFromText() {
  const area = document.querySelector("#candidate-profile-text");
  if (!area || !area.value.trim()) {
    pbMessage("Colle d’abord un texte de CV.", true);
    return;
  }
  try {
    const payload = await pbApi("/api/career/candidate-profile/text", {
      method: "POST",
      body: JSON.stringify({ source_kind: "cv", text: area.value, original_name: "texte-profil" }),
    });
    pbRender(payload);
    area.value = "";
    pbMessage(`${payload.total} fait(s) proposé(s). Rien n’est approuvé : valide chaque champ.`);
  } catch (error) {
    pbMessage(error.message, true);
  }
}

async function pbDeleteProfile() {
  if (!pbProfile || !pbProfile.total) {
    pbMessage("Aucun profil candidat à supprimer.", true);
    return;
  }
  const confirmation = document.querySelector("#candidate-profile-confirm");
  if (!confirmation || confirmation.value !== "SUPPRIMER") {
    pbMessage("Écris SUPPRIMER dans le champ de confirmation pour supprimer le profil candidat.", true);
    return;
  }
  try {
    const payload = await pbApi("/api/career/candidate-profile", { method: "DELETE" });
    pbRender(payload);
    if (confirmation) confirmation.value = "";
    pbMessage("Profil candidat supprimé.");
  } catch (error) {
    pbMessage(error.message, true);
  }
}

function pbBindActions() {
  const build = document.querySelector("#candidate-profile-build");
  if (build) build.addEventListener("click", pbBuildFromDocument);
  const buildText = document.querySelector("#candidate-profile-build-text");
  if (buildText) buildText.addEventListener("click", pbBuildFromText);
  const remove = document.querySelector("#candidate-profile-delete");
  if (remove) remove.addEventListener("click", pbDeleteProfile);
  const exportButton = document.querySelector("#candidate-profile-export");
  if (exportButton) {
    exportButton.addEventListener("click", () => {
      window.location.assign("/api/career/candidate-profile/export");
    });
  }
}

function pbWatchProfileView() {
  const view = document.querySelector("#view-profile");
  if (!view || typeof MutationObserver === "undefined") return;
  const observer = new MutationObserver(() => {
    if (!view.hidden) pbLoadProfile();
  });
  observer.observe(view, { attributes: true, attributeFilter: ["hidden"] });
}

function pbInit() {
  pbBindActions();
  pbWatchProfileView();
  const view = document.querySelector("#view-profile");
  if (view && !view.hidden) pbLoadProfile();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", pbInit);
} else {
  pbInit();
}
