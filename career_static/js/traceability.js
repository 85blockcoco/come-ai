"use strict";

/*
 * SPEC-011 — Registre de traçabilité des exigences (interface locale).
 *
 * Ce module affiche l'état réel du registre : les exigences extraites des
 * offres, la preuve qui les couvre ou l'absence de preuve, et l'historique
 * immuable de chaque exigence.
 *
 * Règles d'honnêteté de l'interface :
 * - rien n'est affiché « couvert » sans citation ;
 * - une liaison automatique en attente de validation est signalée comme
 *   telle (« à valider »), jamais comme une couverture acquise ;
 * - les compteurs affichés viennent de l'API locale, jamais d'une estimation
 *   faite dans le navigateur ;
 * - aucune action n'envoie de candidature : le registre ne fait qu'écrire
 *   dans la base locale.
 *
 * Aucune dépendance externe, aucun appel réseau hors de l'API Career locale.
 */

const TRACEABILITY_API = "/api/career/traceability";

const traceabilityStatusLabels = {
  uncovered: "Non couverte",
  covered: "Couverte",
  partial: "Partiellement couverte",
  contradicted: "Contradite",
  waived: "Levée (dérogation)",
};

const traceabilityCriticalityLabels = {
  mandatory: "Obligatoire",
  preferred: "Appréciée",
  nice_to_have: " Bonus",
  contextual: "Contextuelle",
};

const traceabilityCategoryLabels = {
  skill: "Compétence",
  experience: "Expérience",
  education: "Formation",
  language: "Langue",
  tool: "Outil",
  certification: "Certification",
  soft_skill: "Compétence comportementale",
  other: "Autre",
};

const traceabilityReviewLabels = {
  not_required: "Lien manuel",
  pending: "À valider",
  confirmed: "Validée",
  rejected: "Rejetée",
};

const traceabilityEventLabels = {
  created: "Création",
  linked: "Preuve liée",
  unlinked: "Preuve retirée",
  status_changed: "Statut modifié",
  category_changed: "Catégorie modifiée",
  criticality_changed: "Criticité modifiée",
  waived: "Dérogation",
  reopened: "Dérogation levée",
  tags_changed: "Tags modifiés",
  deleted: "Suppression",
  link_confirmed: "Liaison validée",
  link_rejected: "Liaison rejetée",
  requirement_changed: "Exigence modifiée",
  superseded: "Exigence remplacée",
  restored: "Exigence restaurée",
};

/* Tri déterministe : criticité, puis statut, puis exigence. Aucun tri
   « par pertinence » : la pertinence n'est pas une donnée du registre. */
const traceabilityStatusRank = {
  uncovered: 0,
  partial: 1,
  contradicted: 2,
  covered: 3,
  waived: 4,
};

const traceabilityCriticalityRank = {
  mandatory: 0,
  preferred: 1,
  nice_to_have: 2,
  contextual: 3,
};

const traceabilityState = {
  requirements: [],
  selected: new Set(),
  detailId: "",
  filters: {
    status: "",
    category: "",
    criticality: "",
    review_state: "",
    offer_id: "",
    query: "",
  },
};

function traceabilityNode(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function traceabilityApi(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
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
    const detail = typeof body.detail === "string" ? body.detail : "L’action de traçabilité n’a pas abouti.";
    throw new Error(detail);
  }
  return body;
}

function traceabilityNotify(message, isError = false) {
  if (typeof window.setMessage === "function") {
    window.setMessage(message, isError);
    return;
  }
  const holder = document.querySelector("#career-message");
  if (!holder) return;
  holder.textContent = String(message || "");
  holder.classList.toggle("error", isError);
}

function traceabilityStatusTone(status) {
  if (status === "covered") return "good";
  if (status === "partial" || status === "contradicted") return "warning";
  if (status === "waived") return "muted";
  return "";
}

function traceabilityLabel(map, value) {
  return map[value] || value || "—";
}

/* La liste affichée est toujours triée de façon stable et explicable. */
function traceabilitySortKey(requirement) {
  const criticality = traceabilityCriticalityRank[requirement.criticality];
  const status = traceabilityStatusRank[requirement.status];
  const text = String(requirement.requirement_text || "");
  return [
    typeof criticality === "number" ? criticality : 9,
    typeof status === "number" ? status : 9,
    text.toLowerCase(),
    String(requirement.trace_id || ""),
  ];
}

function traceabilitySort(requirements) {
  return [...requirements].sort((left, right) => {
    const a = traceabilitySortKey(left);
    const b = traceabilitySortKey(right);
    for (let index = 0; index < a.length; index += 1) {
      if (a[index] < b[index]) return -1;
      if (a[index] > b[index]) return 1;
    }
    return 0;
  });
}

function traceabilityFilterQuery(filters) {
  const params = new URLSearchParams();
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString();
  return query ? `${TRACEABILITY_API}/requirements?${query}` : `${TRACEABILITY_API}/requirements`;
}

function traceabilityReadFilters() {
  const read = (id) => document.querySelector(id)?.value?.trim() || "";
  return {
    status: read("#traceability-filter-status"),
    category: read("#traceability-filter-category"),
    criticality: read("#traceability-filter-criticality"),
    review_state: read("#traceability-filter-review"),
    offer_id: read("#traceability-filter-offer"),
    query: read("#traceability-filter-query"),
  };
}

function traceabilityMetric(value, label) {
  const node = traceabilityNode("article", "", "metric");
  node.append(traceabilityNode("strong", String(value)), traceabilityNode("span", label));
  return node;
}

function traceabilityRenderMetrics(summary) {
  const holder = document.querySelector("#traceability-metrics");
  if (!holder) return;
  holder.replaceChildren();
  const data = summary || {};
  const mandatory = data.mandatory || {};
  const rate = Math.round(Number(data.coverage_rate || 0) * 100);
  holder.append(
    traceabilityMetric(data.total || 0, "Exigences suivies"),
    traceabilityMetric(`${rate} %`, "Exigences couvertes"),
    traceabilityMetric(`${Math.round(Number(mandatory.coverage_rate || 0) * 100)} %`, "Obligatoires couvertes"),
    traceabilityMetric(data.pending_reviews || 0, "Liaisons à valider"),
  );
}

function traceabilityRenderRow(requirement) {
  const row = traceabilityNode("article", "", "traceability-row");

  const selection = traceabilityNode("input", "", "traceability-check");
  selection.type = "checkbox";
  selection.checked = traceabilityState.selected.has(requirement.trace_id);
  selection.setAttribute("aria-label", `Sélectionner l’exigence ${requirement.requirement_text || ""}`);
  selection.addEventListener("change", () => {
    if (selection.checked) traceabilityState.selected.add(requirement.trace_id);
    else traceabilityState.selected.delete(requirement.trace_id);
    traceabilityRenderBatchBar();
  });

  const copy = traceabilityNode("div", "", "traceability-copy");
  copy.append(
    traceabilityNode("strong", requirement.requirement_text || requirement.requirement_id || "Exigence"),
  );
  const meta = traceabilityNode("div", "", "traceability-meta");
  meta.append(
    traceabilityNode("span", traceabilityLabel(traceabilityStatusLabels, requirement.status), `local-tag ${traceabilityStatusTone(requirement.status)}`),
    traceabilityNode("span", traceabilityLabel(traceabilityCriticalityLabels, requirement.criticality)),
    traceabilityNode("span", traceabilityLabel(traceabilityCategoryLabels, requirement.category)),
    traceabilityNode("span", requirement.source || "—"),
  );
  copy.append(meta);
  if (requirement.evidence_quote) {
    copy.append(traceabilityNode("p", `« ${requirement.evidence_quote} »`, "traceability-quote"));
  } else {
    copy.append(traceabilityNode("p", "Aucune preuve citée pour l’instant.", "traceability-quote muted"));
  }
  if (requirement.review_state === "pending") {
    copy.append(traceabilityNode("p", "Liaison automatique proposée : elle attend ta validation.", "traceability-quote"));
  }
  if (requirement.superseded_at) {
    copy.append(
      traceabilityNode("p", "L’offre ne demande plus cette exigence : elle est remplacée.", "traceability-quote muted"),
    );
  }

  const actions = traceabilityNode("div", "", "traceability-actions");
  const open = traceabilityNode("button", "Historique", "quiet-button");
  open.type = "button";
  open.addEventListener("click", () => traceabilityOpenDetail(requirement.trace_id));
  actions.append(open);

  row.append(selection, copy, actions);
  return row;
}

function traceabilityRenderList() {
  const holder = document.querySelector("#traceability-list");
  const empty = document.querySelector("#traceability-empty");
  const counter = document.querySelector("#traceability-count");
  if (!holder) return;
  holder.replaceChildren();
  const requirements = traceabilitySort(traceabilityState.requirements);
  requirements.forEach((requirement) => holder.append(traceabilityRenderRow(requirement)));
  if (counter) counter.textContent = `${requirements.length} exigence(s)`;
  if (empty) empty.hidden = requirements.length > 0;
  traceabilityRenderBatchBar();
}

function traceabilityRenderBatchBar() {
  const bar = document.querySelector("#traceability-batch");
  if (!bar) return;
  const count = traceabilityState.selected.size;
  bar.hidden = count === 0;
  const label = bar.querySelector("#traceability-batch-count");
  if (label) label.textContent = `${count} exigence(s) sélectionnée(s)`;
}

async function traceabilityBatch(action) {
  const traceIds = [...traceabilityState.selected];
  if (!traceIds.length) return;
  const payload = { trace_ids: traceIds, action, actor: "user" };
  if (action === "waive") {
    const justification = window.prompt("Justification de la dérogation (obligatoire) :");
    if (!justification) return;
    payload.justification = justification;
  }
  try {
    const result = await traceabilityApi(`${TRACEABILITY_API}/batch`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    traceabilityNotify(
      `${result.applied_count} exigence(s) mise(s) à jour.` +
        (result.failed_count ? ` ${result.failed_count} échec(s).` : ""),
      result.failed_count > 0,
    );
    traceabilityState.selected.clear();
    await traceabilityRefresh();
  } catch (error) {
    traceabilityNotify(error.message, true);
  }
}

function traceabilityRenderDetail(requirement) {
  const holder = document.querySelector("#traceability-detail");
  const panel = document.querySelector("#traceability-detail-panel");
  const title = document.querySelector("#traceability-detail-title");
  if (!holder || !panel) return;
  holder.replaceChildren();
  if (!requirement) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  if (title) title.textContent = requirement.requirement_text || "Exigence";

  const facts = traceabilityNode("dl", "", "traceability-facts");
  const rows = [
    ["Identifiant", requirement.requirement_id],
    ["Source", requirement.source],
    ["Catégorie", traceabilityLabel(traceabilityCategoryLabels, requirement.category)],
    ["Criticité", traceabilityLabel(traceabilityCriticalityLabels, requirement.criticality)],
    ["Statut", traceabilityLabel(traceabilityStatusLabels, requirement.status)],
    ["Preuve", requirement.evidence_id || "Aucune"],
    ["Validation", traceabilityLabel(traceabilityReviewLabels, requirement.review_state)],
    ["Repère source", requirement.locator || "—"],
  ];
  if (requirement.superseded_at) {
    rows.push(["Remplacée le", requirement.superseded_at]);
  }
  rows.forEach(([label, value]) => {
    facts.append(traceabilityNode("dt", label), traceabilityNode("dd", value || "—"));
  });
  holder.append(facts);

  if (requirement.evidence_quote) {
    holder.append(traceabilityNode("blockquote", `« ${requirement.evidence_quote} »`, "traceability-quote"));
  }

  const actions = traceabilityNode("div", "", "inline-actions");
  const action = (label, handler) => {
    const button = traceabilityNode("button", label, "quiet-button");
    button.type = "button";
    button.addEventListener("click", handler);
    return button;
  };
  if (requirement.review_state === "pending") {
    actions.append(
      action("Valider la liaison", () => traceabilityAction(`${TRACEABILITY_API}/requirements/${requirement.trace_id}/confirm`, "Liaison validée.")),
      action("Rejeter la liaison", () => traceabilityAction(`${TRACEABILITY_API}/requirements/${requirement.trace_id}/reject`, "Liaison rejetée.")),
    );
  }
  if (requirement.evidence_id) {
    actions.append(action("Retirer la preuve", () => traceabilityAction(`${TRACEABILITY_API}/requirements/${requirement.trace_id}/unlink-evidence`, "Preuve retirée.")));
  }
  if (requirement.status === "waived") {
    actions.append(action("Lever la dérogation", () => traceabilityAction(`${TRACEABILITY_API}/requirements/${requirement.trace_id}/reopen`, "Dérogation levée.")));
  } else {
    actions.append(action("Lever l’exigence (dérogation)", () => traceabilityWaive(requirement.trace_id)));
  }
  holder.append(actions);

  const timeline = traceabilityNode("ol", "", "traceability-timeline");
  (requirement.history || []).forEach((event) => {
    const item = traceabilityNode("li", "", "traceability-event");
    item.append(
      traceabilityNode("strong", traceabilityLabel(traceabilityEventLabels, event.event_type)),
      traceabilityNode("span", ` · ${event.actor} · ${event.timestamp}`),
    );
    if (event.comment) item.append(traceabilityNode("p", event.comment));
    timeline.append(item);
  });
  holder.append(traceabilityNode("h4", "Historique"), timeline);
}

async function traceabilityAction(url, successMessage) {
  try {
    await traceabilityApi(url, { method: "POST", body: JSON.stringify({ actor: "user" }) });
    traceabilityNotify(successMessage);
    await traceabilityRefresh();
  } catch (error) {
    traceabilityNotify(error.message, true);
  }
}

async function traceabilityWaive(traceId) {
  const justification = window.prompt("Justification de la dérogation (obligatoire) :");
  if (!justification) return;
  try {
    await traceabilityApi(`${TRACEABILITY_API}/requirements/${traceId}/waive`, {
      method: "POST",
      body: JSON.stringify({ justification, actor: "user" }),
    });
    traceabilityNotify("Dérogation enregistrée.");
    await traceabilityRefresh();
  } catch (error) {
    traceabilityNotify(error.message, true);
  }
}

async function traceabilityOpenDetail(traceId) {
  traceabilityState.detailId = traceId;
  try {
    const requirement = await traceabilityApi(`${TRACEABILITY_API}/requirements/${traceId}`);
    traceabilityRenderDetail(requirement);
  } catch (error) {
    traceabilityNotify(error.message, true);
  }
}

function traceabilityRenderGaps(gaps) {
  const holder = document.querySelector("#traceability-gaps");
  if (!holder) return;
  holder.replaceChildren();
  const items = Array.isArray(gaps) ? gaps : [];
  if (!items.length) {
    holder.append(
      traceabilityNode("p", "Aucune exigence obligatoire sans preuve citée.", "empty-state"),
    );
    return;
  }
  items.forEach((gap) => {
    const row = traceabilityNode("article", "", "traceability-row");
    const copy = traceabilityNode("div", "", "traceability-copy");
    copy.append(traceabilityNode("strong", gap.requirement_text || gap.requirement_id || "Exigence"));
    const meta = traceabilityNode("div", "", "traceability-meta");
    meta.append(
      traceabilityNode("span", traceabilityLabel(traceabilityStatusLabels, gap.status), `local-tag ${traceabilityStatusTone(gap.status)}`),
      traceabilityNode("span", gap.source || "—"),
    );
    copy.append(meta);
    const actions = traceabilityNode("div", "", "traceability-actions");
    const open = traceabilityNode("button", "Historique", "quiet-button");
    open.type = "button";
    open.addEventListener("click", () => traceabilityOpenDetail(gap.trace_id));
    actions.append(open);
    row.append(copy, actions);
    holder.append(row);
  });
}

async function traceabilityRefresh() {
  const holder = document.querySelector("#traceability-list");
  if (holder) holder.setAttribute("aria-busy", "true");
  try {
    const [list, coverage, gaps] = await Promise.all([
      traceabilityApi(traceabilityFilterQuery(traceabilityState.filters)),
      traceabilityApi(`${TRACEABILITY_API}/audit/coverage`),
      traceabilityApi(`${TRACEABILITY_API}/audit/gaps`),
    ]);
    traceabilityState.requirements = list.requirements || [];
    traceabilityRenderMetrics(coverage.summary);
    traceabilityRenderList();
    traceabilityRenderGaps(gaps.gaps || []);
    if (traceabilityState.detailId) {
      const current = traceabilityState.requirements.find(
        (item) => item.trace_id === traceabilityState.detailId,
      );
      traceabilityRenderDetail(current || null);
    }
  } catch (error) {
    traceabilityNotify(error.message, true);
  } finally {
    if (holder) holder.setAttribute("aria-busy", "false");
  }
}

function traceabilityInit() {
  const apply = document.querySelector("#traceability-apply");
  if (apply) {
    apply.addEventListener("click", () => {
      traceabilityState.filters = traceabilityReadFilters();
      traceabilityRefresh();
    });
  }
  document.querySelectorAll("[data-traceability-batch]").forEach((button) => {
    button.addEventListener("click", () => traceabilityBatch(button.dataset.traceabilityBatch));
  });
  const close = document.querySelector("#traceability-detail-close");
  if (close) {
    close.addEventListener("click", () => {
      traceabilityState.detailId = "";
      traceabilityRenderDetail(null);
    });
  }
}

window.CareerTraceability = {
  refresh: traceabilityRefresh,
  init: traceabilityInit,
  state: traceabilityState,
  labels: {
    status: traceabilityStatusLabels,
    criticality: traceabilityCriticalityLabels,
    category: traceabilityCategoryLabels,
    review: traceabilityReviewLabels,
    event: traceabilityEventLabels,
  },
  sort: traceabilitySort,
  filterQuery: traceabilityFilterQuery,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", traceabilityInit);
} else {
  traceabilityInit();
}
