"use strict";

/*
 * SPEC-014 — Constitution exécutable : éditeur de règles, dashboard de
 * conformité, graphe règles → entités → tests, historique et audit trail.
 *
 * Tout est local : les appels HTTP restent sur la même origine
 * (/api/constitution/...). Aucun envoi vers un service distant, aucune donnée
 * personnelle ne quitte le navigateur. L'éditeur n'invente jamais une règle : il ne
 * fait que reformuler ce que la Constitution renvoie.
 *
 * Les fonctions pures (analyse d'expression, complétion, diff, graphe) sont
 * exportées pour être testées hors navigateur, comme les autres garde-fous UI
 * du projet.
 */

const CONSTITUTION_ENDPOINTS = {
  health: "/api/constitution/health",
  rules: "/api/constitution/rules",
  rule: (ruleId) => `/api/constitution/rules/${encodeURIComponent(ruleId)}`,
  approve: (ruleId) => `/api/constitution/rules/${encodeURIComponent(ruleId)}/approve`,
  deprecate: (ruleId) => `/api/constitution/rules/${encodeURIComponent(ruleId)}/deprecate`,
  rollback: (ruleId) => `/api/constitution/rules/${encodeURIComponent(ruleId)}/rollback`,
  rulesets: "/api/constitution/rulesets",
  validate: "/api/constitution/validate",
  audit: "/api/constitution/audit",
  drift: "/api/constitution/drift",
  generate: "/api/constitution/test/generate",
  check: "/api/constitution/expression/check",
  preview: "/api/constitution/expression/preview",
};

const CONSTITUTION_SEVERITIES = {
  info: "Information",
  warning: "Avertissement",
  error: "Erreur",
  critical: "Critique",
};

const CONSTITUTION_STATUS_LABELS = {
  draft: "Brouillon",
  active: "Active",
  deprecated: "Dépréciée",
  archived: "Archivée",
};

const CONSTITUTION_ACTION_LABELS = {
  "rule.created": "Règle créée",
  "rule.updated": "Règle modifiée",
  "rule.approved": "Règle approuvée",
  "rule.deprecated": "Règle dépréciée",
  "rule.archived": "Règle archivée",
  "rule.rolled_back": "Règle restaurée",
  "rule.seeded": "Règle de référence",
  "ruleset.created": "Jeu de règles créé",
  "ruleset.rolled_back": "Jeu de règles restauré",
};

const CONSTITUTION_DOMAIN_LABELS = {
  freshness: "Fraîcheur",
  matching: "Matching",
  dedup: "Déduplication",
  privacy: "Confidentialité",
  export: "Export",
};

const CONSTITUTION_ENTITY_LABELS = {
  offer: "Offre",
  profile: "Profil",
  evidence: "Preuve",
  requirement: "Exigence",
  matching: "Matching",
  export: "Export",
};

const CONSTITUTION_IDENTIFIER_CATALOG = [
  { path: "freshness.offer.posted_max_age_days", label: "Âge de l'offre (jours)" },
  { path: "freshness.certification.max_age_days", label: "Âge de la certification (jours)" },
  { path: "matching.score", label: "Score de pertinence" },
  { path: "matching.duration_months", label: "Durée du stage (mois)" },
  { path: "matching.start_month", label: "Mois de début" },
  { path: "matching.contract_type", label: "Type de contrat" },
  { path: "matching.score_weights.total", label: "Somme des poids de scoring" },
  { path: "matching.critical_requirements", label: "Exigences critiques" },
  { path: "dedup.similarity_threshold", label: "Seuil de similarité" },
  { path: "privacy.pii_fields", label: "Champs personnels" },
  { path: "export.docx.max_size_mb", label: "Taille d'export (Mo)" },
];

/* --- Fonctions pures (testables hors navigateur) --------------------------- */

function collectIdentifiers(expression) {
  /* Renvoie les chemins pointés d'une expression (hors variables de macro). */
  const text = String(expression || "");
  const identifiers = [];
  const pattern = /[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+/g;
  let match = pattern.exec(text);
  while (match) {
    if (!identifiers.includes(match[0])) identifiers.push(match[0]);
    match = pattern.exec(text);
  }
  return identifiers;
}

function checkSyntax(expression) {
  /* Vérification syntaxique légère, côté navigateur.

     Elle ne remplace pas la vérification du moteur : elle donne un retour
     immédiat pendant la saisie et signale les erreurs les plus fréquentes
     (parenthèses, accolades, opérateur en fin d'expression).
  */
  const text = String(expression || "").trim();
  if (!text) return { valid: false, error: "L'expression est vide." };
  const pairs = [["(", ")"], ["[", "]"]];
  for (const [open, close] of pairs) {
    const opened = (text.match(new RegExp(`\\${open}`, "g")) || []).length;
    const closed = (text.match(new RegExp(`\\${close}`, "g")) || []).length;
    if (opened !== closed) return { valid: false, error: `Parenthèses ou crochets non appariés (« ${open} » / « ${close} »).` };
  }
  if (/[-+*/%<>=!&|]$/.test(text)) return { valid: false, error: "L'expression se termine par un opérateur." };
  if (text.includes("..")) return { valid: false, error: "Un chemin contient deux points consécutifs." };
  const quotes = (text.match(/'/g) || []).length;
  if (quotes % 2 !== 0) return { valid: false, error: "Une chaîne n'est pas fermée." };
  return { valid: true, error: null };
}

function suggestCompletions(expression, caret, catalog) {
  /* Propose des complétions pour le chemin en cours de saisie. */
  const source = Array.isArray(catalog) ? catalog : CONSTITUTION_IDENTIFIER_CATALOG;
  const text = String(expression || "").slice(0, Number.isInteger(caret) ? caret : String(expression || "").length);
  const match = text.match(/[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/);
  const prefix = match ? match[0] : "";
  const suggestions = [];
  for (const entry of source) {
    if (!prefix || entry.path.startsWith(prefix)) {
      suggestions.push({ path: entry.path, label: entry.label || entry.path });
    }
  }
  return suggestions.slice(0, 12);
}

function diffVersions(previous, current) {
  /* Diff simple entre deux versions d'une règle (champs modifiés). */
  const fields = ["name", "domain", "expression", "severity", "status", "description", "rationale", "dsl_type"];
  const changes = [];
  for (const field of fields) {
    const before = previous ? String(previous[field] ?? "") : "";
    const after = current ? String(current[field] ?? "") : "";
    if (before !== after) changes.push({ field, before, after });
  }
  const beforeScope = (previous && previous.scope) || [];
  const afterScope = (current && current.scope) || [];
  if (beforeScope.join("|") !== afterScope.join("|")) {
    changes.push({ field: "scope", before: beforeScope.join(", "), after: afterScope.join(", ") });
  }
  return changes;
}

function buildGraphModel(rules, results) {
  /* Construit le graphe règles → entités → tests.

     Les nœuds sont des objets simples : le rendu SVG est séparé du modèle pour
     rester testable.
  */
  const nodes = [];
  const edges = [];
  const seen = new Set();
  const ruleList = Array.isArray(rules) ? rules : [];
  const resultList = Array.isArray(results) ? results : [];

  for (const rule of ruleList) {
    const ruleId = String(rule.rule_id || "");
    if (!ruleId) continue;
    const domain = String(rule.domain || "");
    const domainLabel = CONSTITUTION_DOMAIN_LABELS[domain] || domain;
    const domainNode = `domain:${domain}`;
    if (!seen.has(domainNode)) {
      seen.add(domainNode);
      nodes.push({ id: domainNode, kind: "domain", label: domainLabel || domain, column: 0 });
    }
    const ruleNode = `rule:${ruleId}`;
    if (!seen.has(ruleNode)) {
      seen.add(ruleNode);
      nodes.push({
        id: ruleNode,
        kind: "rule",
        label: ruleId,
        column: 1,
        status: String(rule.status || "draft"),
        severity: String(rule.severity || "error"),
        tested: Boolean(rule.has_test),
      });
    }
    edges.push({ from: domainNode, to: ruleNode, kind: "contains" });
    for (const scope of rule.scope || []) {
      const entityNode = `entity:${scope}`;
      if (!seen.has(entityNode)) {
        seen.add(entityNode);
        nodes.push({
          id: entityNode,
          kind: "entity",
          label: CONSTITUTION_ENTITY_LABELS[scope] || scope,
          column: 2,
        });
      }
      edges.push({ from: ruleNode, to: entityNode, kind: "applies" });
    }
  }

  for (const result of resultList) {
    const ruleId = String(result.rule_id || "");
    const ruleNode = `rule:${ruleId}`;
    if (!seen.has(ruleNode)) continue;
    const testNode = `test:${ruleId}`;
    if (!seen.has(testNode)) {
      seen.add(testNode);
      nodes.push({
        id: testNode,
        kind: "test",
        label: result.passed ? "Conforme" : (result.status === "not_evaluable" ? "Non évaluable" : "Non conforme"),
        column: 3,
        severity: String(result.severity || "error"),
      });
    }
    edges.push({ from: ruleNode, to: testNode, kind: "checks" });
  }
  return { nodes, edges };
}

function formatScore(value) {
  /* Score de conformité au format français (une décimale). */
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${(number * 100).toFixed(1).replace(".", ",")} %`;
}

function severityLabel(severity) {
  return CONSTITUTION_SEVERITIES[String(severity || "")] || String(severity || "—");
}

function statusLabel(status) {
  return CONSTITUTION_STATUS_LABELS[String(status || "")] || String(status || "—");
}

function describeAction(action) {
  return CONSTITUTION_ACTION_LABELS[String(action || "")] || String(action || "—");
}

function domainLabel(domain) {
  return CONSTITUTION_DOMAIN_LABELS[String(domain || "")] || String(domain || "—");
}

/* --- Accès HTTP local ------------------------------------------------------ */

async function constitutionFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
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
    const detail = typeof body.detail === "string" ? body.detail : "La Constitution n’a pas pu répondre.";
    throw new Error(detail);
  }
  return body;
}

/* --- Rendu ----------------------------------------------------------------- */

function constitutionState() {
  return {
    rules: [],
    rulesets: [],
    audit: null,
    drift: null,
    health: null,
    report: null,
    results: [],
    selectedRuleId: "",
    versions: [],
  };
}

const state = constitutionState();

function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function clear(node) {
  if (!node) return;
  node.replaceChildren();
}

function renderHealth(health) {
  const container = document.querySelector("#constitution-health");
  if (!container) return;
  clear(container);
  if (!health) {
    container.append(element("p", "Constitution indisponible.", "constitution-empty"));
    return;
  }
  const metrics = [
    [String(health.rules ?? 0), "règles au total"],
    [String(health.active_rules ?? 0), "règles actives"],
    [String((health.rulesets || []).length), "jeux de règles"],
  ];
  for (const [value, label] of metrics) {
    const card = element("div", "", "constitution-metric");
    card.append(element("strong", value), element("span", label));
    container.append(card);
  }
  container.append(element("p", `DSL ${health.dsl || "cel"} · version ${health.version || "—"} · 100 % local`, "constitution-note"));
}

function renderRules(rules) {
  const container = document.querySelector("#constitution-rules");
  if (!container) return;
  clear(container);
  if (!rules.length) {
    container.append(element("p", "Aucune règle ne correspond aux filtres.", "constitution-empty"));
    return;
  }
  const table = element("table", "", "constitution-table");
  const head = element("thead");
  const headRow = element("tr");
  for (const label of ["Règle", "Domaine", "Statut", "Sévérité", "Version", "Test"]) {
    headRow.append(element("th", label));
  }
  head.append(headRow);
  table.append(head);
  const body = element("tbody");
  for (const rule of rules) {
    const row = element("tr");
    const nameCell = element("td");
    const button = element("button", rule.rule_id || "", "constitution-rule-link");
    button.type = "button";
    button.addEventListener("click", () => selectRule(rule.rule_id));
    nameCell.append(button, element("small", rule.description || ""));
    row.append(nameCell);
    row.append(element("td", domainLabel(rule.domain)));
    row.append(element("td", statusLabel(rule.status)));
    row.append(element("td", severityLabel(rule.severity)));
    row.append(element("td", `v${rule.version ?? 1}`));
    row.append(element("td", rule.has_test ? "couvert" : "non couvert"));
    body.append(row);
  }
  table.append(body);
  container.append(table);
}

function renderGraph(rules, results) {
  const container = document.querySelector("#constitution-graph");
  if (!container) return;
  clear(container);
  const model = buildGraphModel(rules, results);
  if (!model.nodes.length) {
    container.append(element("p", "Aucune règle à visualiser.", "constitution-empty"));
    return;
  }
  const namespace = "http://www.w3.org/2000/svg";
  const width = 720;
  const height = Math.max(220, model.nodes.length * 34);
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Graphe des règles, des entités concernées et de la couverture de test");
  svg.classList.add("constitution-svg");

  const positions = new Map();
  const columns = { 0: [], 1: [], 2: [], 3: [] };
  for (const node of model.nodes) {
    (columns[node.column] || columns[1]).push(node);
  }
  for (const [column, nodes] of Object.entries(columns)) {
    nodes.forEach((node, index) => {
      const y = (index + 1) * (height / (nodes.length + 1));
      positions.set(node.id, { x: 60 + Number(column) * 200, y });
    });
  }
  for (const edge of model.edges) {
    const from = positions.get(edge.from);
    const to = positions.get(edge.to);
    if (!from || !to) continue;
    const line = document.createElementNS(namespace, "line");
    line.setAttribute("x1", String(from.x + 70));
    line.setAttribute("y1", String(from.y));
    line.setAttribute("x2", String(to.x - 70));
    line.setAttribute("y2", String(to.y));
    line.setAttribute("class", `constitution-edge constitution-edge-${edge.kind}`);
    svg.append(line);
  }
  for (const node of model.nodes) {
    const position = positions.get(node.id);
    if (!position) continue;
    const group = document.createElementNS(namespace, "g");
    const circle = document.createElementNS(namespace, "circle");
    circle.setAttribute("cx", String(position.x));
    circle.setAttribute("cy", String(position.y));
    circle.setAttribute("r", node.kind === "rule" ? "8" : "6");
    circle.setAttribute("class", `constitution-node constitution-node-${node.kind}`);
    group.append(circle);
    const text = document.createElementNS(namespace, "text");
    text.setAttribute("x", String(position.x + 12));
    text.setAttribute("y", String(position.y + 4));
    text.setAttribute("class", "constitution-label");
    text.textContent = node.label;
    group.append(text);
    svg.append(group);
  }
  container.append(svg);
  const legend = element("p", "Règles → entités concernées → couverture de test.", "constitution-note");
  container.append(legend);
}

function renderDashboard(report, drift) {
  const container = document.querySelector("#constitution-dashboard");
  if (!container) return;
  clear(container);
  if (!report) {
    container.append(element("p", "Aucun rapport de conformité disponible.", "constitution-empty"));
    return;
  }
  const score = element("div", "", "constitution-score");
  score.append(element("strong", formatScore(report.conformity?.rules?.test_coverage ?? 0)));
  score.append(element("span", "couverture de test des règles"));
  container.append(score);

  const alerts = (drift && drift.alerts) || [];
  const alertList = element("ul", "", "constitution-alerts");
  if (!alerts.length) {
    alertList.append(element("li", "Aucune alerte de dérive.", "constitution-ok"));
  }
  for (const alert of alerts) {
    const item = element("li", "", alert.status === "alert" ? "constitution-alert" : "constitution-ok");
    item.append(element("strong", alert.metric || ""), element("span", alert.message || ""));
    alertList.append(item);
  }
  container.append(alertList);

  const violations = (report.entities?.history || []).flatMap((entry) => entry.violations || []);
  const top = violations.slice(0, 5);
  const topList = element("ul", "", "constitution-violations");
  if (!top.length) {
    topList.append(element("li", "Aucune violation enregistrée.", "constitution-ok"));
  }
  for (const violation of top) {
    const item = element("li");
    item.append(element("strong", violation.rule_id || ""), element("span", `${severityLabel(violation.severity)} — ${violation.message || ""}`));
    topList.append(item);
  }
  container.append(element("h3", "Dernières violations", ""), topList);
}

function renderHistory(versions, current) {
  const container = document.querySelector("#constitution-history");
  if (!container) return;
  clear(container);
  if (!versions.length) {
    container.append(element("p", "Aucun historique pour cette règle.", "constitution-empty"));
    return;
  }
  const list = element("ol", "", "constitution-timeline");
  versions.forEach((version, index) => {
    const item = element("li", "", "constitution-timeline-item");
    item.append(element("strong", `v${version.version} — ${statusLabel(version.status)}`));
    item.append(element("span", `${version.created_at || ""} · ${version.created_by || "local"}`));
    if (index === 0 && current) {
      const changes = diffVersions(version, current);
      for (const change of changes) {
        const line = element("p", `${change.field} : ${change.before || "∅"} → ${change.after || "∅"}`, "constitution-diff");
        item.append(line);
      }
    }
    if (version.version > 1) {
      const button = element("button", "Restaurer cette version", "quiet-button");
      button.type = "button";
      button.addEventListener("click", () => rollbackRule(state.selectedRuleId, version.version));
      item.append(button);
    }
    list.append(item);
  });
  container.append(list);
}

function renderAudit(entries) {
  const container = document.querySelector("#constitution-audit");
  if (!container) return;
  clear(container);
  const list = (entries || []).slice(0, 30);
  if (!list.length) {
    container.append(element("p", "Aucun événement d’audit.", "constitution-empty"));
    return;
  }
  const table = element("table", "", "constitution-table");
  const body = element("tbody");
  for (const entry of list) {
    const row = element("tr");
    row.append(element("td", entry.occurred_at || ""));
    row.append(element("td", describeAction(entry.action)));
    row.append(element("td", entry.subject_id || ""));
    row.append(element("td", entry.actor || "local"));
    body.append(row);
  }
  table.append(body);
  container.append(table);
}

/* --- Actions --------------------------------------------------------------- */

async function load() {
  const health = await constitutionFetch(CONSTITUTION_ENDPOINTS.health);
  const rules = await constitutionFetch(CONSTITUTION_ENDPOINTS.rules);
  const audit = await constitutionFetch(CONSTITUTION_ENDPOINTS.audit);
  const drift = await constitutionFetch(CONSTITUTION_ENDPOINTS.drift);
  state.health = health;
  state.rules = rules.rules || [];
  state.audit = audit;
  state.drift = drift;
  state.report = audit;
  renderHealth(health);
  renderRules(state.rules);
  renderGraph(state.rules, state.results);
  renderDashboard(audit, drift);
  renderAudit(audit.conformity?.audit_trail?.recent || []);
  await refreshEditorCatalog();
}

async function refreshEditorCatalog() {
  const datalist = document.querySelector("#constitution-identifiers");
  if (!datalist) return;
  clear(datalist);
  for (const entry of CONSTITUTION_IDENTIFIER_CATALOG) {
    const option = document.createElement("option");
    option.value = entry.path;
    option.label = entry.label || entry.path;
    datalist.append(option);
  }
}

async function selectRule(ruleId) {
  if (!ruleId) return;
  state.selectedRuleId = ruleId;
  const detail = await constitutionFetch(CONSTITUTION_ENDPOINTS.rule(ruleId));
  state.versions = detail.versions || [];
  const rule = detail.rule || {};
  const form = document.querySelector("#constitution-editor");
  if (form) {
    form.rule_id.value = rule.rule_id || "";
    form.name.value = rule.name || "";
    form.domain.value = rule.domain || "matching";
    form.description.value = rule.description || "";
    form.rationale.value = rule.rationale || "";
    form.expression.value = rule.expression || "";
    form.severity.value = rule.severity || "error";
    form.scope.value = (rule.scope || []).join(", ");
    form.tags.value = (rule.tags || []).join(", ");
    form.remediation.value = rule.remediation || "";
  }
  renderHistory(state.versions, rule);
  const status = document.querySelector("#constitution-editor-status");
  if (status) {
    status.textContent = `Version ${rule.version} — ${statusLabel(rule.status)} — signature ${detail.signature_valid ? "valide" : "invalide"}`;
  }
}

async function rollbackRule(ruleId, targetVersion) {
  if (!ruleId || !targetVersion) return;
  await constitutionFetch(CONSTITUTION_ENDPOINTS.rollback(ruleId), {
    method: "POST",
    body: JSON.stringify({ target_version: targetVersion, reason: "Restauration depuis l'historique", actor: "local" }),
  });
  await load();
  await selectRule(ruleId);
}

async function saveRule(event) {
  event?.preventDefault?.();
  const form = document.querySelector("#constitution-editor");
  if (!form) return;
  const payload = {
    rule_id: form.rule_id.value.trim(),
    name: form.name.value.trim(),
    domain: form.domain.value,
    description: form.description.value,
    rationale: form.rationale.value,
    expression: form.expression.value.trim(),
    dsl_type: "cel",
    scope: form.scope.value.split(",").map((item) => item.trim()).filter(Boolean),
    tags: form.tags.value.split(",").map((item) => item.trim()).filter(Boolean),
    severity: form.severity.value,
    remediation: form.remediation.value.trim() || null,
    created_by: form.author.value.trim() || "local",
  };
  const status = document.querySelector("#constitution-editor-status");
  try {
    await constitutionFetch(CONSTITUTION_ENDPOINTS.rules, { method: "POST", body: JSON.stringify(payload) });
    if (status) status.textContent = "Règle enregistrée en brouillon : elle attend une approbation.";
    await load();
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

async function approveSelectedRule() {
  const form = document.querySelector("#constitution-editor");
  if (!form || !state.selectedRuleId) return;
  const status = document.querySelector("#constitution-editor-status");
  try {
    await constitutionFetch(CONSTITUTION_ENDPOINTS.approve(state.selectedRuleId), {
      method: "POST",
      body: JSON.stringify({ approved_by: form.approver.value.trim() || "relecture", note: "" }),
    });
    if (status) status.textContent = "Règle approuvée : elle est maintenant effective.";
    await load();
    await selectRule(state.selectedRuleId);
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

async function previewExpression() {
  const form = document.querySelector("#constitution-editor");
  if (!form) return;
  const output = document.querySelector("#constitution-preview");
  if (!output) return;
  try {
    const context = JSON.parse(form.context.value || "{}");
    const result = await constitutionFetch(CONSTITUTION_ENDPOINTS.preview, {
      method: "POST",
      body: JSON.stringify({ expression: form.expression.value.trim(), context }),
    });
    output.textContent = result.valid ? `Résultat : ${JSON.stringify(result.value)}` : `Erreur : ${result.error}`;
  } catch (error) {
    output.textContent = `Erreur : ${error.message}`;
  }
}

async function checkExpression() {
  const form = document.querySelector("#constitution-editor");
  if (!form) return;
  const output = document.querySelector("#constitution-check");
  if (!output) return;
  const local = checkSyntax(form.expression.value);
  if (!local.valid) {
    output.textContent = `Syntaxe : ${local.error}`;
    return;
  }
  try {
    const result = await constitutionFetch(CONSTITUTION_ENDPOINTS.check, {
      method: "POST",
      body: JSON.stringify({ expression: form.expression.value.trim() }),
    });
    output.textContent = result.valid
      ? `Syntaxe valide — identifiants : ${(result.identifiers || []).join(", ") || "aucun"}`
      : `Syntaxe : ${result.error}`;
  } catch (error) {
    output.textContent = `Erreur : ${error.message}`;
  }
}

async function validateEntity() {
  const form = document.querySelector("#constitution-validator");
  if (!form) return;
  const output = document.querySelector("#constitution-validation-result");
  if (!output) return;
  try {
    const entity = JSON.parse(form.entity.value || "{}");
    const result = await constitutionFetch(CONSTITUTION_ENDPOINTS.validate, {
      method: "POST",
      body: JSON.stringify({
        entity_id: form.entity_id.value.trim(),
        entity_type: form.entity_type.value,
        ruleset_id: form.ruleset_id.value.trim() || "career.core",
        entity,
      }),
    });
    state.results = result.results || [];
    renderGraph(state.rules, state.results);
    const report = result.report || {};
    const lines = [
      `Score de conformité : ${formatScore(report.compliance_score)}`,
      `Règles respectées : ${report.passed}/${report.total_rules} · non évaluables : ${report.not_evaluable}`,
    ];
    for (const violation of report.violations || []) {
      lines.push(`[${severityLabel(violation.severity)}] ${violation.rule_id} — ${violation.message}`);
    }
    output.textContent = lines.join("\n");
  } catch (error) {
    output.textContent = `Erreur : ${error.message}`;
  }
}

async function generateTests() {
  const output = document.querySelector("#constitution-generated");
  if (!output) return;
  try {
    const result = await constitutionFetch(CONSTITUTION_ENDPOINTS.generate, {
      method: "POST",
      body: JSON.stringify({ write: false }),
    });
    output.textContent = `${result.rules} règle(s) — tests générés :\n${(result.content || "").split("\n").slice(0, 12).join("\n")}`;
  } catch (error) {
    output.textContent = `Erreur : ${error.message}`;
  }
}

let constitutionInitialized = false;

function init() {
  if (constitutionInitialized) return load().catch(() => undefined);
  constitutionInitialized = true;
  const editor = document.querySelector("#constitution-editor");
  editor?.addEventListener("submit", saveRule);
  document.querySelector("#constitution-approve")?.addEventListener("click", approveSelectedRule);
  document.querySelector("#constitution-check-expression")?.addEventListener("click", checkExpression);
  document.querySelector("#constitution-preview-expression")?.addEventListener("click", previewExpression);
  document.querySelector("#constitution-validate")?.addEventListener("click", validateEntity);
  document.querySelector("#constitution-generate-tests")?.addEventListener("click", generateTests);
  const expression = document.querySelector("#constitution-expression");
  expression?.addEventListener("input", () => {
    const output = document.querySelector("#constitution-check");
    if (!output) return;
    const result = checkSyntax(expression.value);
    output.textContent = result.valid ? "Syntaxe : analyse en cours…" : `Syntaxe : ${result.error}`;
  });
  expression?.addEventListener("blur", checkExpression);
  return load().catch((error) => {
    const status = document.querySelector("#constitution-editor-status");
    if (status) status.textContent = error.message;
  });
}

if (typeof window !== "undefined") {
  window.ComeConstitution = { init, load, selectRule, rollbackRule, saveRule, checkExpression, previewExpression, validateEntity, generateTests };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    collectIdentifiers,
    checkSyntax,
    suggestCompletions,
    diffVersions,
    buildGraphModel,
    formatScore,
    severityLabel,
    statusLabel,
    describeAction,
    domainLabel,
    CONSTITUTION_IDENTIFIER_CATALOG,
  };
}
