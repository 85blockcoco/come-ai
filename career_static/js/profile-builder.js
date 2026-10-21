"use strict";

/**
 * SK-10 — Approbation champ par champ des faits du profil candidat.
 *
 * Règles affichées dans l'interface :
 * - un fait proposé n'est jamais approuvé automatiquement, même lu par OCR ;
 * - chaque fait garde sa source (page, offsets, citation) ;
 * - un fait proposé, rejeté ou mis de côté ne peut pas justifier une
 *   correspondance ni une candidature.
 */

const candidateProfileState = {
  facts: [],
  counts: {},
  imports: [],
  pending: "",
};

const candidateProfileElements = {
  panel: document.querySelector("#candidate-profile-builder"),
  counts: document.querySelector("#candidate-facts-counts"),
  list: document.querySelector("#candidate-facts-list"),
  empty: document.querySelector("#candidate-facts-empty"),
  status: document.querySelector("#candidate-facts-status"),
  form: document.querySelector("#candidate-facts-form"),
  importSelect: document.querySelector("#candidate-facts-import"),
  text: document.querySelector("#candidate-facts-text"),
  propose: document.querySelector("#candidate-facts-propose"),
  apply: document.querySelector("#candidate-facts-apply"),
  exportButton: document.querySelector("#candidate-facts-export"),
};

function candidateElement(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function candidateApi(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  let body = {};
  if (contentType.includes("application/json")) {
    try {
      body = await response.json();
    } catch (_) {
      body = {};
    }
  }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "L’action Career n’a pas abouti.";
    throw new Error(detail);
  }
  return body;
}

function candidateStatus(text = "", error = false) {
  if (!candidateProfileElements.status) return;
  candidateProfileElements.status.textContent = String(text || "");
  candidateProfileElements.status.classList.toggle("error", error);
  candidateProfileElements.status.hidden = !text;
}

function candidateEvidenceLabel(fact) {
  const evidence = fact.evidence || {};
  const page = evidence.page ? `page ${evidence.page}` : "page inconnue";
  const confidence = evidence.page_confidence === "exact" ? "" : " (estimée)";
  const offsets = `${evidence.start_offset}–${evidence.end_offset}`;
  return `${page}${confidence} · caractères ${offsets}`;
}

function candidateDecision(fact, decision, value = "") {
  return candidateApi(`/api/career/candidate-profile/facts/${encodeURIComponent(fact.id)}`, {
    method: "PATCH",
    body: JSON.stringify({ decision, value }),
  });
}

async function candidateRefresh() {
  if (!candidateProfileElements.panel) return;
  try {
    const payload = await candidateApi("/api/career/candidate-profile/facts");
    candidateProfileState.facts = payload.facts || [];
    candidateProfileState.counts = payload.counts || {};
    renderCandidateFacts();
  } catch (error) {
    candidateStatus(error.message, true);
  }
}

async function candidateLoadImports() {
  if (!candidateProfileElements.importSelect) return;
  try {
    const payload = await candidateApi("/api/career/profile-imports");
    candidateProfileState.imports = payload.profile_imports || [];
  } catch (_) {
    candidateProfileState.imports = [];
  }
  const select = candidateProfileElements.importSelect;
  const previous = select.value;
  select.replaceChildren();
  const empty = candidateElement("option", "— Aucun document sélectionné —");
  empty.value = "";
  select.append(empty);
  candidateProfileState.imports.forEach((profileImport) => {
    const option = candidateElement("option", profileImport.original_name || "Document de profil");
    option.value = profileImport.id;
    select.append(option);
  });
  if (previous && candidateProfileState.imports.some((item) => item.id === previous)) {
    select.value = previous;
  }
}

function candidateActionButton(label, className, handler) {
  const button = candidateElement("button", label, className);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

function renderCandidateFacts() {
  const list = candidateProfileElements.list;
  if (!list) return;
  list.replaceChildren();
  const facts = candidateProfileState.facts;
  if (candidateProfileElements.empty) candidateProfileElements.empty.hidden = facts.length > 0;

  const counts = candidateProfileState.counts || {};
  if (candidateProfileElements.counts) {
    candidateProfileElements.counts.replaceChildren();
    candidateProfileElements.counts.append(
      candidateElement("span", `${counts.proposed || 0} à vérifier`, "fact-count fact-count-pending"),
      candidateElement("span", `${counts.approved || 0} approuvés`, "fact-count fact-count-approved"),
      candidateElement("span", `${counts.modified || 0} corrigés`, "fact-count fact-count-modified"),
      candidateElement("span", `${counts.suspended || 0} mis de côté`, "fact-count fact-count-suspended"),
      candidateElement("span", `${counts.rejected || 0} rejetés`, "fact-count fact-count-rejected"),
    );
  }

  facts.forEach((fact) => {
    const card = candidateElement("article", "", `candidate-fact candidate-fact-${fact.status}`);
    const head = candidateElement("div", "", "candidate-fact-head");
    head.append(candidateElement("span", fact.kind_label || fact.kind, "candidate-fact-kind"));
    head.append(candidateElement("span", fact.status_label || fact.status, "candidate-fact-status"));
    if (fact.from_ocr) {
      head.append(candidateElement("span", "OCR — validation obligatoire", "candidate-fact-ocr"));
    }
    const title = candidateElement("p", fact.value ? `${fact.label} — ${fact.value}` : fact.label, "candidate-fact-label");
    const evidence = candidateElement("p", candidateEvidenceLabel(fact), "candidate-fact-evidence");
    const quote = candidateElement("blockquote", fact.evidence?.quote || "", "candidate-fact-quote");
    card.append(head, title, evidence, quote);

    if (fact.status === "proposed") {
      const actions = candidateElement("div", "", "candidate-fact-actions");
      actions.append(
        candidateActionButton("Approuver", "primary-button", async () => {
          await candidateDecision(fact, "approve");
          await candidateRefresh();
        }),
        candidateActionButton("Corriger", "secondary-button", () => openCandidateCorrection(card, fact)),
        candidateActionButton("Rejeter", "quiet-button", async () => {
          await candidateDecision(fact, "reject");
          await candidateRefresh();
        }),
        candidateActionButton("Mettre de côté", "quiet-button", async () => {
          await candidateDecision(fact, "suspend");
          await candidateRefresh();
        }),
      );
      card.append(actions);
    } else {
      const actions = candidateElement("div", "", "candidate-fact-actions");
      if (fact.status === "approved" || fact.status === "modified") {
        actions.append(
          candidateActionButton("Mettre de côté", "quiet-button", async () => {
            await candidateDecision(fact, "suspend");
            await candidateRefresh();
          }),
        );
      }
      actions.append(
        candidateActionButton("Rouvrir", "quiet-button", async () => {
          await candidateDecision(fact, "reopen");
          await candidateRefresh();
        }),
        candidateActionButton("Supprimer", "danger-button", async () => {
          await candidateApi(`/api/career/candidate-profile/facts/${encodeURIComponent(fact.id)}`, { method: "DELETE" });
          await candidateRefresh();
        }),
      );
      card.append(actions);
    }
    list.append(card);
  });
}

function openCandidateCorrection(card, fact) {
  if (card.querySelector(".candidate-fact-correction")) return;
  const form = candidateElement("form", "", "candidate-fact-correction");
  const input = document.createElement("input");
  input.type = "text";
  input.value = fact.value || fact.label || "";
  input.maxLength = 2000;
  input.setAttribute("aria-label", "Valeur corrigée du fait");
  const submit = candidateElement("button", "Enregistrer la correction", "primary-button");
  submit.type = "submit";
  form.append(input, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) {
      candidateStatus("La correction exige une valeur.", true);
      return;
    }
    await candidateDecision(fact, "modify", value);
    await candidateRefresh();
  });
  card.append(form);
  input.focus();
}

async function candidatePropose(event) {
  event.preventDefault();
  const importId = candidateProfileElements.importSelect?.value || "";
  const text = candidateProfileElements.text?.value || "";
  if (!importId && !text.trim()) {
    candidateStatus("Choisis un document local ou colle un texte à analyser.", true);
    return;
  }
  candidateStatus("Analyse locale en cours…");
  try {
    const payload = await candidateApi("/api/career/candidate-profile/proposals", {
      method: "POST",
      body: JSON.stringify({ import_id: importId, text, filename: "texte-profil" }),
    });
    candidateStatus(
      `${payload.facts.length} fait(s) proposé(s) à vérifier${payload.source?.from_ocr ? " (OCR : validation obligatoire)" : ""}.`,
    );
    await candidateRefresh();
  } catch (error) {
    candidateStatus(error.message, true);
  }
}

async function candidateApply() {
  const usable = candidateProfileState.facts.filter((fact) => fact.usable);
  if (!usable.length) {
    candidateStatus("Aucun fait approuvé à appliquer.", true);
    return;
  }
  try {
    await candidateApi("/api/career/candidate-profile/apply", {
      method: "POST",
      body: JSON.stringify({ fact_ids: usable.map((fact) => fact.id) }),
    });
    candidateStatus("Les faits approuvés sont maintenant appliqués à ton profil.");
    await candidateRefresh();
  } catch (error) {
    candidateStatus(error.message, true);
  }
}

function candidateInit() {
  if (!candidateProfileElements.panel) return;
  candidateProfileElements.form?.addEventListener("submit", candidatePropose);
  candidateProfileElements.apply?.addEventListener("click", candidateApply);
  candidateProfileElements.exportButton?.addEventListener("click", () => {
    window.location.href = "/api/career/candidate-profile/export";
  });
}

window.careerProfileBuilder = {
  refresh: async () => {
    await candidateLoadImports();
    await candidateRefresh();
  },
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", candidateInit);
} else {
  candidateInit();
}
