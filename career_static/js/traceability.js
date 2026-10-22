"use strict";

/**
 * SPEC-011 — Registre de traçabilité des exigences (Career Agent).
 *
 * This module renders the traceability registry: the requirements extracted
 * from the offers (SK-02), the proof that covers them (SK-10) and the
 * immutable history of every change.
 *
 * The file follows the conventions of `career_static/career.js`: the global
 * `api`, `make` and `metric` helpers are reused, and the pure functions
 * (sorting, filtering, batch selection, coverage) are written so the test
 * suite can execute them in Node against real fixtures.
 *
 * The UI never invents a proof: a requirement is only shown as covered when
 * the local registry says so, and every action goes through the local API.
 */

const TRACEABILITY_STATUS_LABELS = {
  uncovered: "Non couverte",
  covered: "Couverte",
  partial: "Partiellement couverte",
  contradicted: "Contradictoire",
  waived: "Écartée",
};

const TRACEABILITY_CATEGORY_LABELS = {
  skill: "Compétence",
  experience: "Expérience",
  education: "Formation",
  language: "Langue",
  tool: "Outil",
  certification: "Certification",
  soft_skill: "Compétence comportementale",
  other: "Autre",
};

const TRACEABILITY_CRITICALITY_LABELS = {
  mandatory: "Obligatoire",
  preferred: "Appréciée",
  nice_to_have: "Atout",
  contextual: "Contextuelle",
};

// The sorting of the "priorité" view: a mandatory requirement that is not
// covered comes first, a covered requirement comes last.
const TRACEABILITY_STATUS_PRIORITY = {
  contradicted: 0,
  uncovered: 1,
  partial: 2,
  waived: 3,
  covered: 4,
};

const TRACEABILITY_CRITICALITY_PRIORITY = {
  mandatory: 0,
  preferred: 1,
  nice_to_have: 2,
  contextual: 3,
};

const traceabilityState = {
  requirements: [],
  coverage: null,
  gaps: [],
  filters: {
    status: "",
    category: "",
    criticality: "",
    offer_id: "",
    search: "",
    sort: "priority",
  },
  selected: new Set(),
  activeTraceId: "",
};

function traceabilityStatusLabel(status) {
  return TRACEABILITY_STATUS_LABELS[status] || String(status || "");
}

function traceabilityStatusPriority(status) {
  const rank = TRACEABILITY_STATUS_PRIORITY[status];
  return typeof rank === "number" ? rank : 5;
}

function traceabilityCriticalityPriority(criticality) {
  const rank = TRACEABILITY_CRITICALITY_PRIORITY[criticality];
  return typeof rank === "number" ? rank : 4;
}

/**
 * Sort the requirements without mutating the source list.
 */
function traceabilitySortTraces(traces, sortKey) {
  const list = Array.isArray(traces) ? [...traces] : [];
  const key = String(sortKey || "priority");
  if (key === "recent") {
    list.sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || "")));
    return list;
  }
  if (key === "offer") {
    list.sort((left, right) => {
      const offer = String(left.offer_id || left.source || "").localeCompare(String(right.offer_id || right.source || ""));
      if (offer !== 0) return offer;
      return traceabilityStatusPriority(left.status) - traceabilityStatusPriority(right.status);
    });
    return list;
  }
  list.sort((left, right) => {
    const criticality = traceabilityCriticalityPriority(left.criticality) - traceabilityCriticalityPriority(right.criticality);
    if (criticality !== 0) return criticality;
    const status = traceabilityStatusPriority(left.status) - traceabilityStatusPriority(right.status);
    if (status !== 0) return status;
    return String(left.requirement_text || "").localeCompare(String(right.requirement_text || ""));
  });
  return list;
}

/**
 * Build the query string of the list endpoint from the filters of the view.
 */
function traceabilityFilterQuery(filters) {
  const params = [];
  const source = filters || {};
  ["status", "category", "criticality", "offer_id"].forEach((key) => {
    const value = String(source[key] || "").trim();
    if (value) params.push(`${key}=${encodeURIComponent(value)}`);
  });
  return params.length ? `?${params.join("&")}` : "";
}

/**
 * Client side search: the registry filters the lists, the search narrows the
 * text of the requirement, the proof and the tags.
 */
function traceabilityMatchesSearch(trace, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    trace.requirement_text,
    trace.evidence_quote,
    trace.requirement_id,
    trace.offer_id,
    trace.source,
    (trace.tags || []).join(" "),
  ].join(" ").toLowerCase();
  return haystack.includes(needle);
}

/**
 * Select the requirements a batch action applies to.  Only the requirements
 * that can legally receive the action are returned: a waiver needs a
 * justification and an unlink needs an existing proof.
 */
function traceabilityBatchTargets(traces, action) {
  const list = Array.isArray(traces) ? traces : [];
  if (action === "waive") {
    return list.filter((trace) => trace.status !== "waived");
  }
  if (action === "unlink") {
    return list.filter((trace) => Boolean(trace.evidence_id));
  }
  if (action === "reopen") {
    return list.filter((trace) => trace.status === "waived");
  }
  return [];
}

/**
 * Compute the coverage counters of a list of requirements.  Only a `covered`
 * requirement counts as covered: a partial proof is reported apart.
 */
function traceabilityCoverageBlock(traces) {
  const list = Array.isArray(traces) ? traces : [];
  const counts = { covered: 0, partial: 0, uncovered: 0, contradicted: 0, waived: 0 };
  list.forEach((trace) => {
    if (Object.prototype.hasOwnProperty.call(counts, trace.status)) counts[trace.status] += 1;
  });
  const total = list.length;
  const rate = total ? Math.round((counts.covered * 100) / total) : 0;
  return { total, ...counts, coverage_rate: rate };
}

/**
 * Return the history entries of a requirement, oldest first, with the label
 * of the event in French.
 */
function traceabilityHistoryEntries(trace) {
  const history = Array.isArray(trace && trace.history) ? trace.history : [];
  return history.map((event) => ({
    timestamp: event.timestamp,
    event_type: event.event_type,
    actor: event.actor,
    comment: event.comment || "",
    label: traceabilityEventLabel(event),
  }));
}

function traceabilityEventLabel(event) {
  const labels = {
    created: "Exigence enregistrée",
    linked: "Preuve liée",
    unlinked: "Preuve retirée",
    status_changed: "Statut modifié",
    category_changed: "Catégorie modifiée",
    criticality_changed: "Criticité modifiée",
    tags_changed: "Étiquettes modifiées",
    requirement_updated: "Exigence mise à jour",
    waived: "Exigence écartée",
    reopened: "Exigence rouverte",
    deleted: "Exigence supprimée",
    validated: "Liaison validée",
  };
  const label = labels[event && event.event_type] || String((event && event.event_type) || "");
  if (event && event.event_type === "status_changed" && event.new_value) {
    return `${label} → ${traceabilityStatusLabel(event.new_value)}`;
  }
  return label;
}

/**
 * Check the shape of an imported file before sending it to the local API.
 * The import is a merge: the traces that already exist locally are kept, and
 * the invalid ones are reported by the registry instead of being repaired.
 */
function traceabilityImportPayload(parsed) {
  const payload = parsed && typeof parsed === "object" ? parsed : {};
  const traces = Array.isArray(payload.traces) ? payload.traces : [];
  if (!traces.length) {
    throw new Error("Ce fichier ne contient aucune exigence à importer.");
  }
  return { traces, actor: "user" };
}

async function loadTraceability() {
  const query = traceabilityFilterQuery(traceabilityState.filters);
  const [listed, coverage, gaps] = await Promise.all([
    api(`/api/career/traceability/requirements${query}`),
    api("/api/career/traceability/audit/coverage"),
    api("/api/career/traceability/audit/gaps"),
  ]);
  traceabilityState.requirements = listed.requirements || [];
  traceabilityState.coverage = coverage;
  traceabilityState.gaps = gaps.gaps || [];
  renderTraceability();
}

function renderTraceability() {
  renderTraceabilityMetrics();
  renderTraceabilityRequirements();
  renderTraceabilityDetail();
}

function renderTraceabilityMetrics() {
  const target = document.querySelector("#traceability-metrics");
  if (!target) return;
  const block = traceabilityCoverageBlock(traceabilityState.requirements);
  const gaps = traceabilityState.gaps.length;
  const waived = Number((traceabilityState.coverage && traceabilityState.coverage.overall && traceabilityState.coverage.overall.waived) || 0);
  target.replaceChildren(
    metric(block.total, "exigences tracées"),
    metric(block.covered, "exigences couvertes"),
    metric(block.partial, "couvertures partielles"),
    metric(gaps, "gaps critiques"),
    metric(waived, "exigences écartées"),
    metric(`${block.coverage_rate}%`, "couverture"),
  );
}

function renderTraceabilityRequirements() {
  const target = document.querySelector("#traceability-requirements");
  const empty = document.querySelector("#traceability-empty");
  if (!target) return;
  const search = traceabilityState.filters.search;
  const filtered = traceabilityState.requirements.filter((trace) => traceabilityMatchesSearch(trace, search));
  const sorted = traceabilitySortTraces(filtered, traceabilityState.filters.sort);
  target.replaceChildren();
  empty.hidden = sorted.length > 0;
  sorted.forEach((trace) => target.append(traceabilityCard(trace)));
  renderTraceabilityBatchBar();
}

function traceabilityCard(trace) {
  const card = make("article", "", "job-card traceability-card");
  const header = make("div", "", "job-card-header");
  const title = make("h3", trace.requirement_text || "(exigence sans texte)");
  title.className = "job-company";
  header.append(title);
  const chips = make("div", "", "job-chips");
  chips.append(make("span", traceabilityStatusLabel(trace.status), "job-chip"));
  chips.append(make("span", TRACEABILITY_CRITICALITY_LABELS[trace.criticality] || trace.criticality, "job-chip"));
  chips.append(make("span", TRACEABILITY_CATEGORY_LABELS[trace.category] || trace.category, "job-chip"));
  if (trace.offer_id) chips.append(make("span", trace.offer_id, "local-tag"));
  header.append(chips);
  card.append(header);

  if (trace.evidence_quote) {
    const proof = make("p", `« ${trace.evidence_quote} »`, "panel-help");
    card.append(proof);
  } else {
    card.append(make("p", "Aucune preuve liée : cette exigence n’est pas couverte.", "panel-help"));
  }
  if (trace.waiver_reason) {
    card.append(make("p", `Justification de l’écart : ${trace.waiver_reason}`, "panel-help"));
  }
  if ((trace.tags || []).length) {
    const tags = make("div", "", "job-chips");
    trace.tags.forEach((tag) => tags.append(make("span", tag, "job-chip")));
    card.append(tags);
  }

  const actions = make("div", "", "inline-actions");
  const select = make("input");
  select.type = "checkbox";
  select.className = "traceability-select";
  select.value = trace.trace_id;
  select.setAttribute("aria-label", `Sélectionner ${trace.requirement_text || "cette exigence"}`);
  select.addEventListener("change", () => {
    if (select.checked) traceabilityState.selected.add(trace.trace_id);
    else traceabilityState.selected.delete(trace.trace_id);
    renderTraceabilityBatchBar();
  });
  actions.append(select);

  const open = make("button", "Voir l’historique", "quiet-button");
  open.type = "button";
  open.addEventListener("click", () => {
    traceabilityState.activeTraceId = trace.trace_id;
    renderTraceabilityDetail();
  });
  actions.append(open);

  if (trace.evidence_id) {
    const unlink = make("button", "Délier la preuve", "secondary-button");
    unlink.type = "button";
    unlink.addEventListener("click", () => traceabilityUnlink(trace.trace_id));
    actions.append(unlink);
  } else {
    const waive = make("button", "Écarter", "secondary-button");
    waive.type = "button";
    waive.addEventListener("click", () => traceabilityWaive(trace.trace_id));
    actions.append(waive);
  }
  card.append(actions);
  return card;
}

function renderTraceabilityBatchBar() {
  const bar = document.querySelector("#traceability-batch-bar");
  const count = document.querySelector("#traceability-batch-count");
  if (!bar) return;
  const selected = traceabilityState.requirements.filter((trace) => traceabilityState.selected.has(trace.trace_id));
  bar.hidden = selected.length === 0;
  if (count) count.textContent = `${selected.length} exigence${selected.length > 1 ? "s" : ""} sélectionnée${selected.length > 1 ? "s" : ""}`;
}

function renderTraceabilityDetail() {
  const panel = document.querySelector("#traceability-detail-panel");
  const target = document.querySelector("#traceability-detail");
  if (!panel || !target) return;
  const trace = traceabilityState.requirements.find((item) => item.trace_id === traceabilityState.activeTraceId);
  if (!trace) {
    panel.hidden = true;
    target.replaceChildren();
    return;
  }
  panel.hidden = false;
  const entries = traceabilityHistoryEntries(trace);
  const list = make("div", "", "review-list");
  entries.forEach((entry) => {
    const item = make("div", "", "detail-row");
    item.append(make("strong", entry.label));
    item.append(make("span", `${entry.timestamp} · ${entry.actor}${entry.comment ? ` · ${entry.comment}` : ""}`, "panel-help"));
    list.append(item);
  });
  target.replaceChildren(
    make("h3", trace.requirement_text || "(exigence sans texte)"),
    make("p", `Statut : ${traceabilityStatusLabel(trace.status)} · Criticité : ${TRACEABILITY_CRITICALITY_LABELS[trace.criticality] || trace.criticality}`, "panel-help"),
    trace.evidence_quote ? make("p", `Preuve : « ${trace.evidence_quote} »`, "panel-help") : make("p", "Aucune preuve liée.", "panel-help"),
    list,
  );
}

async function traceabilityWaive(traceId) {
  const justification = document.querySelector("#traceability-justification");
  const reason = justification ? justification.value.trim() : "";
  if (!reason) {
    setMessage("Écris la justification de l’écart avant de le confirmer.", true);
    return;
  }
  try {
    await api(`/api/career/traceability/requirements/${traceId}/waive`, {
      method: "POST",
      body: JSON.stringify({ justification: reason }),
    });
    setMessage("Exigence écartée : la justification est dans l’historique.");
    await loadTraceability();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function traceabilityUnlink(traceId) {
  try {
    await api(`/api/career/traceability/requirements/${traceId}/unlink-evidence`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setMessage("Preuve retirée : l’exigence n’est plus couverte.");
    await loadTraceability();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function traceabilityRunBatch(action) {
  const selected = traceabilityState.requirements.filter((trace) => traceabilityState.selected.has(trace.trace_id));
  const targets = traceabilityBatchTargets(selected, action);
  if (!targets.length) {
    setMessage("Aucune exigence sélectionnée ne peut recevoir cette action.", true);
    return;
  }
  const justification = document.querySelector("#traceability-justification");
  const reason = justification ? justification.value.trim() : "";
  if (action === "waive" && !reason) {
    setMessage("Écris la justification de l’écart avant de l’appliquer à la sélection.", true);
    return;
  }
  let done = 0;
  for (const trace of targets) {
    try {
      if (action === "waive") {
        await api(`/api/career/traceability/requirements/${trace.trace_id}/waive`, {
          method: "POST",
          body: JSON.stringify({ justification: reason }),
        });
      } else if (action === "unlink") {
        await api(`/api/career/traceability/requirements/${trace.trace_id}/unlink-evidence`, {
          method: "POST",
          body: JSON.stringify({}),
        });
      } else if (action === "reopen") {
        await api(`/api/career/traceability/requirements/${trace.trace_id}/reopen`, {
          method: "POST",
          body: JSON.stringify({}),
        });
      }
      done += 1;
    } catch (error) {
      setMessage(error.message, true);
    }
  }
  traceabilityState.selected.clear();
  setMessage(`${done} exigence${done > 1 ? "s" : ""} mise${done > 1 ? "s" : ""} à jour.`);
  await loadTraceability();
}

function initTraceabilityView() {
  const statusFilter = document.querySelector("#traceability-filter-status");
  const categoryFilter = document.querySelector("#traceability-filter-category");
  const criticalityFilter = document.querySelector("#traceability-filter-criticality");
  const offerFilter = document.querySelector("#traceability-filter-offer");
  const searchFilter = document.querySelector("#traceability-filter-search");
  const sortFilter = document.querySelector("#traceability-sort");

  if (statusFilter && !statusFilter.options.length) {
    Object.entries(TRACEABILITY_STATUS_LABELS).forEach(([value, label]) => {
      statusFilter.append(new Option(label, value));
    });
  }
  if (categoryFilter && !categoryFilter.options.length) {
    Object.entries(TRACEABILITY_CATEGORY_LABELS).forEach(([value, label]) => {
      categoryFilter.append(new Option(label, value));
    });
  }
  if (criticalityFilter && !criticalityFilter.options.length) {
    Object.entries(TRACEABILITY_CRITICALITY_LABELS).forEach(([value, label]) => {
      criticalityFilter.append(new Option(label, value));
    });
  }

  const reload = () => {
    traceabilityState.filters.status = statusFilter ? statusFilter.value : "";
    traceabilityState.filters.category = categoryFilter ? categoryFilter.value : "";
    traceabilityState.filters.criticality = criticalityFilter ? criticalityFilter.value : "";
    traceabilityState.filters.offer_id = offerFilter ? offerFilter.value.trim() : "";
    traceabilityState.filters.sort = sortFilter ? sortFilter.value : "priority";
    loadTraceability().catch((error) => setMessage(error.message, true));
  };

  [statusFilter, categoryFilter, criticalityFilter, sortFilter].forEach((element) => {
    element?.addEventListener("change", reload);
  });
  offerFilter?.addEventListener("change", reload);
  searchFilter?.addEventListener("input", () => {
    traceabilityState.filters.search = searchFilter.value;
    renderTraceabilityRequirements();
  });
  document.querySelector("#traceability-refresh")?.addEventListener("click", () => {
    loadTraceability().catch((error) => setMessage(error.message, true));
  });
  document.querySelector("#traceability-batch-waive")?.addEventListener("click", () => traceabilityRunBatch("waive"));
  document.querySelector("#traceability-batch-unlink")?.addEventListener("click", () => traceabilityRunBatch("unlink"));
  document.querySelector("#traceability-batch-reopen")?.addEventListener("click", () => traceabilityRunBatch("reopen"));
  document.querySelector("#traceability-batch-clear")?.addEventListener("click", () => {
    traceabilityState.selected.clear();
    renderTraceabilityRequirements();
  });
  document.querySelector("#traceability-import")?.addEventListener("click", () => {
    const input = document.querySelector("#traceability-import-file");
    const file = input?.files?.[0];
    if (!file) {
      setMessage("Choisis d’abord un export JSON du registre.", true);
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const parsed = JSON.parse(String(reader.result || "{}"));
        const payload = traceabilityImportPayload(parsed);
        const result = await api("/api/career/traceability/import", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        const invalid = (result.invalid || []).length;
        setMessage(
          `Import terminé : ${result.count} exigence${result.count > 1 ? "s" : ""} importée${result.count > 1 ? "s" : ""}, ` +
          `${(result.skipped || []).length} déjà présente${(result.skipped || []).length > 1 ? "s" : ""}` +
          (invalid ? `, ${invalid} illisible${invalid > 1 ? "s" : ""}.` : ".")
        );
        await loadTraceability();
      } catch (error) {
        setMessage(error.message || "Ce fichier n’est pas un export du registre.", true);
      }
    };
    reader.onerror = () => setMessage("Le fichier n’a pas pu être lu.", true);
    reader.readAsText(file);
  });
}

if (typeof document !== "undefined") {
  initTraceabilityView();
}

if (typeof window !== "undefined") {
  window.TraceabilityUI = {
    load: loadTraceability,
    state: traceabilityState,
    sortTraces: traceabilitySortTraces,
    filterQuery: traceabilityFilterQuery,
    batchTargets: traceabilityBatchTargets,
    coverageBlock: traceabilityCoverageBlock,
    historyEntries: traceabilityHistoryEntries,
    matchesSearch: traceabilityMatchesSearch,
    importPayload: traceabilityImportPayload,
  };
}
