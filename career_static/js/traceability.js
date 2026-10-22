"use strict";

/*
 * SPEC-011 (CVBOOST-46) — Registre de traçabilité des exigences.
 *
 * Interface 100 % locale : le registre vit dans la base Career locale, les
 * exigences sont montrées avec leur provenance et leur citation de preuve,
 * et chaque action est historisée côté serveur. Rien n'est envoyé nulle
 * part : ni e-mail, ni formulaire, ni appel externe.
 *
 * Règles d'affichage reprises du contrat métier :
 * - une exigence couverte affiche toujours la citation de sa preuve ;
 * - une exigence sans preuve reste visible comme un manque (jamais masquée) ;
 * - une liaison automatique non validée est signalée comme « à valider » ;
 * - une dérogation affiche toujours sa justification.
 *
 * Ce fichier n'expose qu'un point d'entrée global (`loadTraceability`)
 * appelé par career_static/career.js au changement d'onglet.
 */

const TRACEABILITY_API = "/api/career/traceability";

const traceabilityStatusLabels = {
  uncovered: "Non couverte",
  covered: "Couverte",
  partial: "Partiellement couverte",
  contradicted: "Contradictoire",
  waived: "Dérogée",
};

const traceabilityCriticalityLabels = {
  mandatory: "Obligatoire",
  preferred: "Préférée",
  nice_to_have: "Souhaitable",
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

const traceabilityEventLabels = {
  created: "Exigence enregistrée",
  linked: "Preuve liée",
  unlinked: "Preuve déliée",
  status_changed: "Statut modifié",
  category_changed: "Catégorie modifiée",
  criticality_changed: "Criticité modifiée",
  waived: "Dérogation accordée",
  reopened: "Dérogation annulée",
  tags_updated: "Tags mis à jour",
  link_confirmed: "Liaison validée",
  link_rejected: "Liaison rejetée",
  deleted: "Exigence supprimée",
};

const traceabilityState = {
  requirements: [],
  selected: new Set(),
  activeTraceId: "",
  filters: { status: "", criticality: "", category: "", query: "" },
};

function traceabilityElement(selector) {
  return document.querySelector(selector);
}

async function traceabilityFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body ? { "Content-Type": "application/json" } : {},
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
    const detail = typeof body.detail === "string" ? body.detail : "L’action n’a pas abouti.";
    throw new Error(detail);
  }
  return body;
}

function traceabilityStatusLabel(status) {
  return traceabilityStatusLabels[status] || status || "—";
}

function traceabilityCriticalityLabel(criticality) {
  return traceabilityCriticalityLabels[criticality] || criticality || "—";
}

function traceabilityCategoryLabel(category) {
  return traceabilityCategoryLabels[category] || category || "—";
}

function traceabilityEventLabel(eventType) {
  return traceabilityEventLabels[eventType] || eventType || "Événement";
}

function traceabilityPercent(rate) {
  if (rate === null || rate === undefined) return "—";
  return `${Math.round(rate * 100)} %`;
}

/* ------------------------------------------------------------------ */
/* Rendu                                                               */
/* ------------------------------------------------------------------ */

function renderTraceabilityMetrics(summary) {
  const container = traceabilityElement("#traceability-metrics");
  if (!container) return;
  container.replaceChildren();
  const cards = [
    { value: summary.total ?? 0, label: "Exigences enregistrées" },
    { value: summary.covered ?? 0, label: "Couvertes par une preuve citée" },
    { value: (summary.uncovered ?? 0) + (summary.partial ?? 0), label: "Sans couverture complète" },
    { value: summary.waived ?? 0, label: "Dérogées (avec justification)" },
    { value: traceabilityPercent(summary.coverage_rate), label: "Couverture des exigences applicables" },
  ];
  cards.forEach((card) => {
    const box = document.createElement("div");
    box.className = "metric";
    const value = document.createElement("strong");
    value.textContent = String(card.value);
    const label = document.createElement("span");
    label.textContent = card.label;
    box.append(value, label);
    container.append(box);
  });
}

function traceabilityStatusChip(trace) {
  const chip = document.createElement("span");
  chip.className = `traceability-chip traceability-chip-${trace.status}`;
  chip.textContent = traceabilityStatusLabel(trace.status);
  if (trace.evidence_id && !trace.confirmed) {
    chip.classList.add("traceability-chip-pending");
    chip.textContent = "Liaison à valider";
  }
  return chip;
}

function renderTraceabilityList() {
  const container = traceabilityElement("#traceability-list");
  const empty = traceabilityElement("#traceability-empty");
  if (!container) return;
  container.replaceChildren();
  const traces = traceabilityState.requirements;
  if (empty) empty.hidden = traces.length > 0;

  traces.forEach((trace) => {
    const row = document.createElement("article");
    row.className = "traceability-row";
    row.dataset.traceId = trace.trace_id;

    const pick = document.createElement("input");
    pick.type = "checkbox";
    pick.className = "traceability-pick";
    pick.checked = traceabilityState.selected.has(trace.trace_id);
    pick.setAttribute("aria-label", `Sélectionner l'exigence : ${trace.requirement_text}`);
    pick.addEventListener("change", () => {
      if (pick.checked) traceabilityState.selected.add(trace.trace_id);
      else traceabilityState.selected.delete(trace.trace_id);
      renderTraceabilityBatch();
    });

    const copy = document.createElement("div");
    copy.className = "traceability-row-copy";
    const title = document.createElement("p");
    title.className = "traceability-row-text";
    title.textContent = trace.requirement_text;
    const meta = document.createElement("p");
    meta.className = "traceability-row-meta";
    const bits = [
      traceabilityCategoryLabel(trace.category),
      traceabilityCriticalityLabel(trace.criticality),
    ];
    if (trace.offer_id) bits.push(`offre ${trace.offer_id}`);
    if (trace.tags && trace.tags.length) bits.push(trace.tags.join(", "));
    meta.textContent = bits.join(" · ");
    copy.append(title, meta);

    const evidence = document.createElement("p");
    evidence.className = "traceability-row-evidence";
    if (trace.evidence_quote) {
      evidence.textContent = `« ${trace.evidence_quote} »`;
      evidence.title = trace.evidence_quote;
    } else {
      evidence.textContent = "Aucune preuve citée";
      evidence.classList.add("traceability-row-evidence-missing");
    }

    const actions = document.createElement("div");
    actions.className = "traceability-row-actions";
    actions.append(traceabilityStatusChip(trace));
    const open = document.createElement("button");
    open.type = "button";
    open.className = "quiet-button";
    open.textContent = "Ouvrir";
    open.addEventListener("click", () => openTraceabilityDetail(trace.trace_id));
    actions.append(open);

    row.append(pick, copy, evidence, actions);
    container.append(row);
  });
  renderTraceabilityBatch();
}

function renderTraceabilityBatch() {
  const bar = traceabilityElement("#traceability-batch");
  if (!bar) return;
  const count = traceabilityState.selected.size;
  bar.hidden = count === 0;
  const label = traceabilityElement("#traceability-batch-count");
  if (label) label.textContent = `${count} exigence${count > 1 ? "s" : ""} sélectionnée${count > 1 ? "s" : ""}`;
}

function traceabilityTimeline(events) {
  const list = document.createElement("ol");
  list.className = "traceability-timeline";
  events.forEach((event) => {
    const item = document.createElement("li");
    item.className = "traceability-timeline-item";
    const when = document.createElement("span");
    when.className = "traceability-timeline-date";
    when.textContent = (event.timestamp || "").replace("T", " ").slice(0, 16);
    const what = document.createElement("span");
    what.className = "traceability-timeline-label";
    what.textContent = traceabilityEventLabel(event.event_type);
    const detail = document.createElement("span");
    detail.className = "traceability-timeline-detail";
    const parts = [];
    if (event.old_value) parts.push(`avant : ${event.old_value}`);
    if (event.new_value) parts.push(`après : ${event.new_value}`);
    if (event.actor) parts.push(`acteur : ${event.actor}`);
    if (event.comment) parts.push(event.comment);
    detail.textContent = parts.join(" · ");
    item.append(when, what, detail);
    list.append(item);
  });
  return list;
}

function renderTraceabilityDetail(trace, events) {
  const panel = traceabilityElement("#traceability-detail");
  if (!panel) return;
  panel.replaceChildren();
  panel.hidden = false;

  const heading = document.createElement("div");
  heading.className = "panel-heading";
  const title = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "Exigence traçable";
  const name = document.createElement("h3");
  name.id = "traceability-detail-title";
  name.textContent = trace.requirement_text;
  title.append(eyebrow, name);
  const close = document.createElement("button");
  close.type = "button";
  close.className = "quiet-button";
  close.textContent = "Fermer";
  close.addEventListener("click", () => {
    panel.hidden = true;
    traceabilityState.activeTraceId = "";
  });
  heading.append(title, close);
  panel.append(heading);

  const facts = document.createElement("dl");
  facts.className = "traceability-facts";
  const rows = [
    ["Identifiant", trace.trace_id],
    ["Exigence", trace.requirement_id || "—"],
    ["Source", trace.source],
    ["Provenance", trace.source_field ? `${trace.source_field} · ${trace.locator || ""}`.trim() : "—"],
    ["Catégorie", traceabilityCategoryLabel(trace.category)],
    ["Criticité", traceabilityCriticalityLabel(trace.criticality)],
    ["Statut", traceabilityStatusLabel(trace.status)],
    ["Preuve", trace.evidence_id ? `${trace.evidence_id} · ${trace.evidence_field || ""}`.trim() : "—"],
    ["Citation", trace.evidence_quote || "—"],
    ["Dérogation", trace.waiver_reason || "—"],
  ];
  rows.forEach(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    definition.textContent = value;
    facts.append(term, definition);
  });
  panel.append(facts);

  const actions = document.createElement("div");
  actions.className = "traceability-actions";
  actions.append(
    traceabilityLinkForm(trace),
    traceabilityWaiveForm(trace),
    traceabilityStatusForm(trace),
  );
  panel.append(actions);

  const historyTitle = document.createElement("p");
  historyTitle.className = "eyebrow";
  historyTitle.textContent = "Historique immuable";
  panel.append(historyTitle, traceabilityTimeline(events));
}

function traceabilityLinkForm(trace) {
  const form = document.createElement("form");
  form.className = "traceability-action-form";
  const title = document.createElement("p");
  title.className = "traceability-action-title";
  title.textContent = trace.evidence_id ? "Remplacer la preuve" : "Lier une preuve";
  const idField = document.createElement("label");
  idField.textContent = "Identifiant de preuve";
  const idInput = document.createElement("input");
  idInput.type = "text";
  idInput.required = true;
  idInput.placeholder = "ex : ev_123";
  idField.append(idInput);
  const quoteField = document.createElement("label");
  quoteField.textContent = "Citation exacte de la preuve";
  const quoteInput = document.createElement("textarea");
  quoteInput.required = true;
  quoteInput.rows = 2;
  quoteInput.placeholder = "Reprends le passage exact du profil qui prouve l’exigence";
  quoteField.append(quoteInput);
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "secondary-button";
  submit.textContent = "Lier la preuve";
  form.append(title, idField, quoteField, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await traceabilityAction(() =>
      traceabilityFetch(`${TRACEABILITY_API}/requirements/${trace.trace_id}/link-evidence`, {
        method: "POST",
        body: JSON.stringify({
          evidence_id: idInput.value.trim(),
          evidence_quote: quoteInput.value.trim(),
        }),
      }),
    );
  });
  return form;
}

function traceabilityWaiveForm(trace) {
  const form = document.createElement("form");
  form.className = "traceability-action-form";
  const title = document.createElement("p");
  title.className = "traceability-action-title";
  title.textContent = "Déroger (justification obligatoire)";
  const field = document.createElement("label");
  field.textContent = "Pourquoi cette exigence ne s’applique pas ?";
  const input = document.createElement("textarea");
  input.required = true;
  input.rows = 2;
  input.placeholder = "Ex. : poste orienté recherche, expérience non exigée";
  field.append(input);
  const actions = document.createElement("div");
  actions.className = "traceability-action-buttons";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "secondary-button";
  submit.textContent = "Déroger";
  const reopen = document.createElement("button");
  reopen.type = "button";
  reopen.className = "quiet-button";
  reopen.textContent = "Annuler la dérogation";
  reopen.disabled = trace.status !== "waived";
  actions.append(submit, reopen);
  form.append(title, field, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await traceabilityAction(() =>
      traceabilityFetch(`${TRACEABILITY_API}/requirements/${trace.trace_id}/waive`, {
        method: "POST",
        body: JSON.stringify({ justification: input.value.trim() }),
      }),
    );
  });
  reopen.addEventListener("click", async () => {
    await traceabilityAction(() =>
      traceabilityFetch(`${TRACEABILITY_API}/requirements/${trace.trace_id}/reopen`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    );
  });
  return form;
}

function traceabilityStatusForm(trace) {
  const form = document.createElement("form");
  form.className = "traceability-action-form";
  const title = document.createElement("p");
  title.className = "traceability-action-title";
  title.textContent = "Actions sur la preuve et le statut";
  const select = document.createElement("select");
  ["uncovered", "covered", "partial", "contradicted", "waived"].forEach((status) => {
    const option = new Option(traceabilityStatusLabel(status), status);
    option.selected = trace.status === status;
    select.append(option);
  });
  const actions = document.createElement("div");
  actions.className = "traceability-action-buttons";
  const apply = document.createElement("button");
  apply.type = "submit";
  apply.className = "secondary-button";
  apply.textContent = "Appliquer le statut";
  const unlink = document.createElement("button");
  unlink.type = "button";
  unlink.className = "quiet-button";
  unlink.textContent = "Délier la preuve";
  unlink.disabled = !trace.evidence_id;
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "quiet-button";
  confirm.textContent = "Valider la liaison";
  confirm.disabled = !(trace.evidence_id && !trace.confirmed);
  actions.append(apply, unlink, confirm);
  form.append(title, select, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await traceabilityAction(() =>
      traceabilityFetch(`${TRACEABILITY_API}/requirements/${trace.trace_id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: select.value }),
      }),
    );
  });
  unlink.addEventListener("click", async () => {
    await traceabilityAction(() =>
      traceabilityFetch(`${TRACEABILITY_API}/requirements/${trace.trace_id}/unlink-evidence`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    );
  });
  confirm.addEventListener("click", async () => {
    await traceabilityAction(() =>
      traceabilityFetch(`${TRACEABILITY_API}/requirements/${trace.trace_id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ confirmed: true }),
      }),
    );
  });
  return form;
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */

async function traceabilityAction(call) {
  const message = traceabilityElement("#traceability-message");
  try {
    await call();
    if (message) {
      message.textContent = "Registre mis à jour.";
      message.classList.remove("error");
    }
    await loadTraceability();
  } catch (error) {
    if (message) {
      message.textContent = error.message || "L’action n’a pas abouti.";
      message.classList.add("error");
    }
  }
}

async function openTraceabilityDetail(traceId) {
  const message = traceabilityElement("#traceability-message");
  try {
    const [trace, history] = await Promise.all([
      traceabilityFetch(`${TRACEABILITY_API}/requirements/${encodeURIComponent(traceId)}`),
      traceabilityFetch(`${TRACEABILITY_API}/audit/history?trace_id=${encodeURIComponent(traceId)}`),
    ]);
    traceabilityState.activeTraceId = traceId;
    renderTraceabilityDetail(trace, history.events || []);
    if (message) message.textContent = "";
  } catch (error) {
    if (message) {
      message.textContent = error.message || "Cette exigence n’est plus disponible.";
      message.classList.add("error");
    }
  }
}

function traceabilityFilterQuery() {
  const params = new URLSearchParams();
  Object.entries(traceabilityState.filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function loadTraceability() {
  const message = traceabilityElement("#traceability-message");
  try {
    const [listing, coverage] = await Promise.all([
      traceabilityFetch(`${TRACEABILITY_API}/requirements${traceabilityFilterQuery()}`),
      traceabilityFetch(`${TRACEABILITY_API}/audit/coverage`),
    ]);
    traceabilityState.requirements = listing.requirements || [];
    const known = new Set(traceabilityState.requirements.map((trace) => trace.trace_id));
    traceabilityState.selected = new Set(
      [...traceabilityState.selected].filter((traceId) => known.has(traceId)),
    );
    renderTraceabilityMetrics(coverage.summary || {});
    renderTraceabilityList();
    if (message) {
      message.textContent = "";
      message.classList.remove("error");
    }
  } catch (error) {
    if (message) {
      message.textContent = error.message || "Le registre n’a pas pu être chargé.";
      message.classList.add("error");
    }
  }
}

function bindTraceabilityEvents() {
  const form = traceabilityElement("#traceability-filters");
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      traceabilityState.filters = {
        status: traceabilityElement("#traceability-filter-status")?.value || "",
        criticality: traceabilityElement("#traceability-filter-criticality")?.value || "",
        category: traceabilityElement("#traceability-filter-category")?.value || "",
        query: traceabilityElement("#traceability-filter-query")?.value.trim() || "",
      };
      loadTraceability();
    });
  }
  const reset = traceabilityElement("#traceability-filter-reset");
  if (reset) {
    reset.addEventListener("click", () => {
      traceabilityState.filters = { status: "", criticality: "", category: "", query: "" };
      ["#traceability-filter-status", "#traceability-filter-criticality", "#traceability-filter-category"].forEach((selector) => {
        const field = traceabilityElement(selector);
        if (field) field.value = "";
      });
      const search = traceabilityElement("#traceability-filter-query");
      if (search) search.value = "";
      loadTraceability();
    });
  }
  const selectAll = traceabilityElement("#traceability-select-all");
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      if (selectAll.checked) {
        traceabilityState.requirements.forEach((trace) => traceabilityState.selected.add(trace.trace_id));
      } else {
        traceabilityState.selected.clear();
      }
      renderTraceabilityList();
    });
  }
  const batchWaive = traceabilityElement("#traceability-batch-waive");
  if (batchWaive) {
    batchWaive.addEventListener("click", async () => {
      const field = traceabilityElement("#traceability-batch-justification");
      const justification = field ? field.value.trim() : "";
      if (!justification) {
        const message = traceabilityElement("#traceability-message");
        if (message) {
          message.textContent = "Une dérogation doit être justifiée : écris pourquoi.";
          message.classList.add("error");
        }
        field?.focus();
        return;
      }
      const traceIds = [...traceabilityState.selected];
      for (const traceId of traceIds) {
        await traceabilityAction(() =>
          traceabilityFetch(`${TRACEABILITY_API}/requirements/${traceId}/waive`, {
            method: "POST",
            body: JSON.stringify({ justification }),
          }),
        );
      }
      traceabilityState.selected.clear();
      if (field) field.value = "";
      loadTraceability();
    });
  }
  const exportJson = traceabilityElement("#traceability-export-json");
  if (exportJson) {
    exportJson.addEventListener("click", () => {
      window.open(`${TRACEABILITY_API}/export?format=json`, "_blank", "noopener");
    });
  }
  const exportCsv = traceabilityElement("#traceability-export-csv");
  if (exportCsv) {
    exportCsv.addEventListener("click", () => {
      window.open(`${TRACEABILITY_API}/export?format=csv`, "_blank", "noopener");
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindTraceabilityEvents);
} else {
  bindTraceabilityEvents();
}
