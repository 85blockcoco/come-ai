"use strict";

/**
 * SPEC-012 — Fraîcheur des preuves.
 *
 * Dashboard local : état global, échéances, alertes, répartition par type,
 * tendances et actions groupées.  Tout est calculé sur la machine de la
 * personne : ce module ne contacte aucun service externe.
 */

const freshnessState = {
  status: null,
  evidence: [],
  policies: {},
  selected: new Set(),
  timer: null,
  loading: false,
};

const FRESHNESS_REFRESH_MS = 60000;

const freshnessStatusLabels = {
  fresh: "À jour",
  warning: "À vérifier",
  expired: "Expirée",
  archived: "Archivée",
};

const freshnessAlertLabels = {
  info: "Info",
  warning: "Attention",
  critical: "Critique",
};

const freshnessCoverageLabels = {
  covered: "Utilisable",
  warning: "Dégradée",
  archived: "Archivée",
  to_reverify: "À revérifier",
};

const freshnessTypeLabels = {
  certification: "Certification",
  skill_technical: "Compétence technique",
  skill_soft: "Compétence comportementale",
  experience: "Expérience",
  education: "Formation",
  language: "Langue",
  tool: "Outil",
  project: "Projet",
};

function freshnessElement(selector) {
  return document.querySelector(selector);
}

function freshnessStatusTone(status) {
  if (status === "fresh") return "good";
  if (status === "warning") return "warning";
  if (status === "expired") return "danger";
  return "muted";
}

function freshnessLabel(text, className) {
  const node = document.createElement("span");
  node.className = className || "job-chip";
  node.textContent = text;
  return node;
}

function freshnessFormatDate(value) {
  if (!value) return "Date inconnue";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Date inconnue";
  return parsed.toLocaleDateString("fr-FR", { year: "numeric", month: "long", day: "numeric" });
}

function freshnessFormatRemaining(days) {
  if (days === null || days === undefined) return "Sans échéance";
  if (days < 0) return `Expirée depuis ${Math.abs(days)} jour(s)`;
  if (days === 0) return "Expire aujourd’hui";
  if (days === 1) return "Expire demain";
  return `Expire dans ${days} jour(s)`;
}

function freshnessTypeLabel(type) {
  return freshnessTypeLabels[type] || type || "Type inconnu";
}

function renderFreshnessSummary(status) {
  const container = freshnessElement("#freshness-summary");
  if (!container) return;
  container.replaceChildren();
  const counts = status?.counts || {};
  const ratios = status?.ratios || {};
  const cards = [
    { key: "fresh", label: "À jour" },
    { key: "warning", label: "À vérifier" },
    { key: "expired", label: "Expirées" },
    { key: "archived", label: "Archivées" },
  ];
  cards.forEach((card) => {
    const item = document.createElement("div");
    item.className = `metric freshness-metric freshness-metric-${freshnessStatusTone(card.key)}`;
    const value = document.createElement("strong");
    value.textContent = String(counts[card.key] ?? 0);
    const caption = document.createElement("span");
    caption.textContent = card.label;
    const share = document.createElement("small");
    share.textContent = `${ratios[card.key] ?? 0} % des preuves suivies`;
    item.append(value, caption, share);
    container.append(item);
  });
}

function renderFreshnessGate(status) {
  const container = freshnessElement("#freshness-gate");
  if (!container) return;
  container.replaceChildren();
  const gate = status?.export_gate;
  if (!gate || !gate.blocked) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  const heading = document.createElement("h3");
  heading.textContent = "Export en attente";
  const list = document.createElement("ul");
  list.className = "freshness-gate-list";
  (gate.blockers || []).forEach((blocker) => {
    const item = document.createElement("li");
    item.textContent = blocker.message || blocker.label || "Preuve expirée";
    list.append(item);
  });
  container.append(heading, list);
}

function renderFreshnessTimeline(status) {
  const container = freshnessElement("#freshness-timeline");
  if (!container) return;
  container.replaceChildren();
  const timeline = status?.timeline || {};
  const buckets = timeline.buckets || {};
  const summary = document.createElement("div");
  summary.className = "freshness-buckets";
  [["7d", "7 jours"], ["30d", "30 jours"], ["90d", "90 jours"]].forEach(([key, label]) => {
    const chip = document.createElement("span");
    chip.className = "job-chip freshness-bucket";
    chip.textContent = `${buckets[key] ?? 0} · ${label}`;
    summary.append(chip);
  });
  container.append(summary);

  const upcoming = timeline.upcoming || [];
  if (!upcoming.length) {
    const empty = document.createElement("p");
    empty.className = "panel-help";
    empty.textContent = "Aucune expiration connue dans les 90 prochains jours.";
    container.append(empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "freshness-list";
  upcoming.forEach((item) => {
    const row = document.createElement("li");
    row.className = "freshness-row";
    const copy = document.createElement("div");
    copy.className = "freshness-row-copy";
    const title = document.createElement("strong");
    title.textContent = item.evidence_id;
    const meta = document.createElement("span");
    meta.className = "freshness-row-meta";
    meta.textContent = `${freshnessTypeLabel(item.evidence_type)} · ${freshnessFormatDate(item.expires_at)} · ${freshnessFormatRemaining(item.days_remaining)}`;
    copy.append(title, meta);
    row.append(copy, freshnessLabel(freshnessStatusLabels[item.status] || item.status, `job-chip freshness-chip-${freshnessStatusTone(item.status)}`));
    list.append(row);
  });
  container.append(list);
}

function renderFreshnessAlerts(status) {
  const container = freshnessElement("#freshness-alerts");
  if (!container) return;
  container.replaceChildren();
  const alerts = status?.alerts || [];
  if (!alerts.length) {
    const empty = document.createElement("p");
    empty.className = "panel-help";
    empty.textContent = "Aucune alerte active. Les preuves suivies sont à jour.";
    container.append(empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "freshness-list";
  alerts.forEach((alert) => {
    const row = document.createElement("li");
    row.className = `freshness-row freshness-row-${alert.level}`;
    const copy = document.createElement("div");
    copy.className = "freshness-row-copy";
    const title = document.createElement("strong");
    title.textContent = alert.label || alert.evidence_id;
    const meta = document.createElement("span");
    meta.className = "freshness-row-meta";
    meta.textContent = alert.message || "";
    copy.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "inline-actions";
    actions.append(freshnessLabel(freshnessAlertLabels[alert.level] || alert.level, `job-chip freshness-chip-${alert.level === "critical" ? "danger" : alert.level === "warning" ? "warning" : "muted"}`));
    const acknowledge = document.createElement("button");
    acknowledge.type = "button";
    acknowledge.className = "quiet-button";
    acknowledge.textContent = "Acquitter";
    acknowledge.addEventListener("click", () => acknowledgeFreshnessAlert(alert.alert_id));
    actions.append(acknowledge);
    row.append(copy, actions);
    list.append(row);
  });
  container.append(list);
}

function renderFreshnessByType(status) {
  const container = freshnessElement("#freshness-by-type");
  if (!container) return;
  container.replaceChildren();
  const breakdown = status?.by_type || {};
  const entries = Object.entries(breakdown);
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "panel-help";
    empty.textContent = "Aucune preuve suivie pour le moment.";
    container.append(empty);
    return;
  }
  const table = document.createElement("table");
  table.className = "freshness-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["Type", "À jour", "À vérifier", "Expirées", "Archivées", "Total"].forEach((label) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    headRow.append(cell);
  });
  head.append(headRow);
  const body = document.createElement("tbody");
  entries.forEach(([type, counts]) => {
    const row = document.createElement("tr");
    const label = document.createElement("th");
    label.scope = "row";
    label.textContent = freshnessTypeLabel(type);
    row.append(label);
    ["fresh", "warning", "expired", "archived", "total"].forEach((key) => {
      const cell = document.createElement("td");
      cell.textContent = String(counts[key] ?? 0);
      row.append(cell);
    });
    body.append(row);
  });
  table.append(head, body);
  container.append(table);
}

function renderFreshnessTrends(report) {
  const container = freshnessElement("#freshness-trends");
  if (!container) return;
  container.replaceChildren();
  const trends = report?.trends || {};
  const series = trends["30d"] || trends["90d"] || [];
  if (!series.length) {
    const empty = document.createElement("p");
    empty.className = "panel-help";
    empty.textContent = "Pas encore d’historique : lance la surveillance pour enregistrer un premier point.";
    container.append(empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "freshness-list";
  series.slice(-12).reverse().forEach((point) => {
    const row = document.createElement("li");
    row.className = "freshness-row";
    const copy = document.createElement("div");
    copy.className = "freshness-row-copy";
    const title = document.createElement("strong");
    title.textContent = `${Math.round((point.fresh_ratio || 0) * 100)} % à jour`;
    const meta = document.createElement("span");
    meta.className = "freshness-row-meta";
    meta.textContent = `${freshnessFormatDate(point.at)} · ${point.total} preuve(s) suivie(s)`;
    copy.append(title, meta);
    row.append(copy, freshnessLabel(`${point.expired} expirée(s)`, "job-chip freshness-chip-danger"));
    list.append(row);
  });
  container.append(list);
}

function renderFreshnessEvidence(evidence) {
  const container = freshnessElement("#freshness-evidence");
  if (!container) return;
  container.replaceChildren();
  if (!evidence.length) {
    const empty = document.createElement("p");
    empty.className = "panel-help";
    empty.textContent = "Aucune preuve suivie. Ajoute une certification, une compétence ou une expérience pour la surveiller.";
    container.append(empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "freshness-list";
  evidence.forEach((item) => {
    const freshness = item.freshness || {};
    const row = document.createElement("li");
    row.className = "freshness-row";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "freshness-select";
    check.value = item.id;
    check.checked = freshnessState.selected.has(item.id);
    check.setAttribute("aria-label", `Sélectionner ${item.label}`);
    check.addEventListener("change", () => {
      if (check.checked) freshnessState.selected.add(item.id);
      else freshnessState.selected.delete(item.id);
    });
    const copy = document.createElement("div");
    copy.className = "freshness-row-copy";
    const title = document.createElement("strong");
    title.textContent = item.label;
    const meta = document.createElement("span");
    meta.className = "freshness-row-meta";
    meta.textContent = [
      freshnessTypeLabel(item.type),
      item.expires_at ? `expire le ${freshnessFormatDate(item.expires_at)}` : "sans expiration",
      freshnessCoverageLabels[item.coverage_status] || "Utilisable",
    ].join(" · ");
    copy.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "inline-actions";
    const verify = document.createElement("button");
    verify.type = "button";
    verify.className = "quiet-button";
    verify.textContent = "Vérifier";
    verify.addEventListener("click", () => checkFreshnessEvidence(item.id));
    const reactivate = document.createElement("button");
    reactivate.type = "button";
    reactivate.className = "quiet-button";
    reactivate.textContent = "Réactiver";
    reactivate.addEventListener("click", () => reactivateFreshnessEvidence(item.id));
    actions.append(verify, reactivate, freshnessLabel(freshnessStatusLabels[freshness.status] || "—", `job-chip freshness-chip-${freshnessStatusTone(freshness.status)}`));
    row.append(check, copy, actions);
    list.append(row);
  });
  container.append(list);
}

function renderFreshnessPolicy(status) {
  const container = freshnessElement("#freshness-policies");
  if (!container) return;
  container.replaceChildren();
  const policies = status?.policies || freshnessState.policies || {};
  const table = document.createElement("table");
  table.className = "freshness-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["Type", "Validité (jours)", "Alerte (jours)", "Expiration auto"].forEach((label) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    headRow.append(cell);
  });
  head.append(headRow);
  const body = document.createElement("tbody");
  Object.entries(policies).forEach(([type, policy]) => {
    const row = document.createElement("tr");
    const label = document.createElement("th");
    label.scope = "row";
    label.textContent = freshnessTypeLabel(type);
    row.append(label);
    const maxAge = document.createElement("td");
    maxAge.textContent = policy.max_age_days === null || policy.max_age_days === undefined ? "—" : String(policy.max_age_days);
    const warning = document.createElement("td");
    warning.textContent = policy.warning_days === null || policy.warning_days === undefined ? "—" : String(policy.warning_days);
    const auto = document.createElement("td");
    auto.textContent = policy.auto_expire ? "Oui" : "Non";
    row.append(maxAge, warning, auto);
    body.append(row);
  });
  table.append(head, body);
  container.append(table);
}

async function loadEvidenceFreshness() {
  const view = freshnessElement("#view-freshness");
  if (view?.hidden) return;
  if (freshnessState.loading) return;
  freshnessState.loading = true;
  try {
    const [status, evidence, report] = await Promise.all([
      api("/api/career/evidence-freshness/status"),
      api("/api/career/evidence-freshness/evidence"),
      api("/api/career/evidence-freshness/report"),
    ]);
    freshnessState.status = status;
    freshnessState.evidence = evidence.evidence || [];
    freshnessState.policies = status.policies || {};
    renderFreshnessSummary(status);
    renderFreshnessGate(status);
    renderFreshnessTimeline(status);
    renderFreshnessAlerts(status);
    renderFreshnessByType(status);
    renderFreshnessTrends(report);
    renderFreshnessEvidence(freshnessState.evidence);
    renderFreshnessPolicy(status);
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    freshnessState.loading = false;
  }
}

async function acknowledgeFreshnessAlert(alertId) {
  try {
    await api(`/api/career/evidence-freshness/acknowledge/${encodeURIComponent(alertId)}`, { method: "POST" });
    setMessage("Alerte acquittée.");
    await loadEvidenceFreshness();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function checkFreshnessEvidence(evidenceId) {
  try {
    await api(`/api/career/evidence-freshness/check/${encodeURIComponent(evidenceId)}`, {
      method: "POST",
      body: JSON.stringify({ method: "manual", result: "unchanged" }),
    });
    setMessage("Vérification enregistrée : la preuve est à jour.");
    await loadEvidenceFreshness();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function reactivateFreshnessEvidence(evidenceId) {
  const now = new Date().toISOString();
  try {
    await api(`/api/career/evidence-freshness/evidence/${encodeURIComponent(evidenceId)}`, {
      method: "PATCH",
      body: JSON.stringify({ last_verified_at: now, archived: false, coverage_status: "covered" }),
    });
    setMessage("Preuve réactivée : le compteur de fraîcheur repart de zéro.");
    await loadEvidenceFreshness();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function runFreshnessMonitor() {
  try {
    const result = await api("/api/career/evidence-freshness/monitor", { method: "POST" });
    const changed = (result.changed || []).length;
    setMessage(`Surveillance terminée : ${result.checked} preuve(s) vérifiée(s), ${changed} dégradée(s).`);
    await loadEvidenceFreshness();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function applyFreshnessBatch(event) {
  event.preventDefault();
  const selected = [...freshnessState.selected];
  if (!selected.length) {
    setMessage("Sélectionne au moins une preuve.", true);
    return;
  }
  const action = freshnessElement("#freshness-batch-action")?.value || "reactivate";
  const days = Number.parseInt(freshnessElement("#freshness-batch-days")?.value || "30", 10);
  try {
    for (const evidenceId of selected) {
      const patch = {};
      if (action === "archive") {
        patch.archived = true;
        patch.coverage_status = "archived";
      } else if (action === "extend") {
        const current = freshnessState.evidence.find((item) => item.id === evidenceId);
        const base = current?.expires_at ? new Date(current.expires_at) : new Date();
        base.setDate(base.getDate() + (Number.isFinite(days) ? days : 30));
        patch.expires_at = base.toISOString();
      } else {
        patch.last_verified_at = new Date().toISOString();
        patch.archived = false;
        patch.coverage_status = "covered";
      }
      await api(`/api/career/evidence-freshness/evidence/${encodeURIComponent(evidenceId)}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
    }
    freshnessState.selected.clear();
    setMessage(`${selected.length} preuve(s) mise(s) à jour.`);
    await loadEvidenceFreshness();
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function createFreshnessEvidence(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    evidence_type: freshnessElement("#freshness-type")?.value || "",
    label: freshnessElement("#freshness-label")?.value || "",
    source_url: freshnessElement("#freshness-source")?.value || "",
    last_verified_at: freshnessElement("#freshness-verified")?.value || "",
    mandatory: Boolean(freshnessElement("#freshness-mandatory")?.checked),
    notes: freshnessElement("#freshness-notes")?.value || "",
  };
  try {
    await api("/api/career/evidence-freshness/evidence", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    setMessage("Preuve ajoutée : elle est désormais suivie.");
    await loadEvidenceFreshness();
  } catch (error) {
    setMessage(error.message, true);
  }
}

function startFreshnessTimer() {
  stopFreshnessTimer();
  freshnessState.timer = window.setInterval(() => {
    const view = freshnessElement("#view-freshness");
    if (view && !view.hidden) loadEvidenceFreshness();
  }, FRESHNESS_REFRESH_MS);
}

function stopFreshnessTimer() {
  if (freshnessState.timer) {
    window.clearInterval(freshnessState.timer);
    freshnessState.timer = null;
  }
}

window.CareerEvidenceFreshness = {
  load: loadEvidenceFreshness,
  start: startFreshnessTimer,
  stop: stopFreshnessTimer,
};

document.addEventListener("DOMContentLoaded", () => {
  freshnessElement("#freshness-refresh")?.addEventListener("click", () => loadEvidenceFreshness());
  freshnessElement("#freshness-monitor")?.addEventListener("click", () => runFreshnessMonitor());
  freshnessElement("#freshness-batch-form")?.addEventListener("submit", applyFreshnessBatch);
  freshnessElement("#freshness-create-form")?.addEventListener("submit", createFreshnessEvidence);
  const view = freshnessElement("#view-freshness");
  if (view && !view.hidden) loadEvidenceFreshness();
});
