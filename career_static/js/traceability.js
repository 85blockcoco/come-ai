"use strict";

/**
 * Registre de traçabilité des exigences (SPEC-011).
 *
 * Module local : aucune requête sortante, aucun envoi automatique.  Le
 * registre affiche ce qui est couvert, ce qui ne l'est pas et l'historique
 * de chaque exigence.  Une exigence sans preuve reste visible comme un
 * manque : l'interface ne dessine jamais une couverture qui n'existe pas.
 */

(function () {
  const API = "/api/career/traceability";

  const state = {
    traces: [],
    selected: new Set(),
    detail: null,
    sort: "updated_at",
    loading: false,
  };

  const statusLabels = {
    uncovered: "Non couverte",
    covered: "Couverte",
    partial: "Partielle",
    contradicted: "Contradictoire",
    waived: "Renoncée",
  };
  const criticalityLabels = {
    mandatory: "Obligatoire",
    preferred: "Appréciée",
    nice_to_have: "Bonus",
    contextual: "Contextuelle",
  };
  const categoryLabels = {
    skill: "Compétence",
    experience: "Expérience",
    education: "Formation",
    language: "Langue",
    tool: "Outil",
    certification: "Certification",
    soft_skill: "Soft skill",
    other: "Autre",
  };
  const eventLabels = {
    created: "Création",
    linked: "Preuve liée",
    unlinked: "Preuve retirée",
    status_changed: "Statut modifié",
    category_changed: "Catégorie modifiée",
    criticality_changed: "Criticité modifiée",
    waived: "Renonciation",
    reopened: "Réouverture",
    deleted: "Suppression",
  };
  const statusOrder = ["uncovered", "partial", "covered", "contradicted", "waived"];
  const criticalityOrder = ["mandatory", "preferred", "nice_to_have", "contextual"];

  const q = (selector, root) => (root || document).querySelector(selector);
  const qa = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function setMessage(text, isError) {
    const target = q("#career-message");
    if (!target) return;
    target.textContent = String(text || "");
    target.classList.toggle("error", Boolean(isError));
    target.setAttribute("role", isError ? "alert" : "status");
  }

  async function api(url, options) {
    const settings = options || {};
    const response = await fetch(url, {
      headers: settings.body ? { "Content-Type": "application/json" } : {},
      ...settings,
    });
    let body = {};
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        body = await response.json();
      } catch (_) {
        body = {};
      }
    }
    if (!response.ok) {
      const detail = typeof body.detail === "string" ? body.detail : "L’action n’a pas abouti.";
      throw new Error(detail);
    }
    return body;
  }

  function statusChip(status) {
    const chip = el("span", statusLabels[status] || status, "job-chip");
    chip.dataset.status = status;
    return chip;
  }

  function currentFilters() {
    const filters = {
      status: q("#traceability-filter-status")?.value || "",
      category: q("#traceability-filter-category")?.value || "",
      criticality: q("#traceability-filter-criticality")?.value || "",
      offer_id: q("#traceability-filter-offer")?.value.trim() || "",
      cv_id: q("#traceability-filter-cv")?.value.trim() || "",
      tag: q("#traceability-filter-tag")?.value.trim() || "",
      q: q("#traceability-filter-text")?.value.trim() || "",
    };
    return Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
  }

  function sortTraces(traces) {
    const mode = state.sort;
    const sorted = [...traces];
    sorted.sort((left, right) => {
      if (mode === "criticality") {
        const difference = criticalityOrder.indexOf(left.criticality) - criticalityOrder.indexOf(right.criticality);
        if (difference !== 0) return difference;
      } else if (mode === "status") {
        const difference = statusOrder.indexOf(left.status) - statusOrder.indexOf(right.status);
        if (difference !== 0) return difference;
      }
      const stamp = String(left.updated_at || "").localeCompare(String(right.updated_at || ""));
      return stamp !== 0 ? stamp : String(left.trace_id).localeCompare(String(right.trace_id));
    });
    return sorted;
  }

  async function loadTraces() {
    const target = q("#traceability-table");
    if (target) target.replaceChildren(el("p", "Chargement du registre local…", "scoring-disclaimer"));
    state.loading = true;
    try {
      const filters = currentFilters();
      const query = new URLSearchParams(filters).toString();
      const payload = await api(`${API}/requirements${query ? `?${query}` : ""}`);
      state.traces = payload.traces || [];
      renderList();
      await loadAudit();
    } catch (error) {
      if (target) target.replaceChildren(el("p", error.message, "scoring-disclaimer"));
      setMessage(error.message, true);
    } finally {
      state.loading = false;
    }
  }

  function renderList() {
    const target = q("#traceability-table");
    const empty = q("#traceability-empty");
    const count = q("#traceability-count");
    if (!target) return;
    const traces = sortTraces(state.traces);
    target.replaceChildren();
    if (count) {
      const selected = state.selected.size;
      count.textContent = selected
        ? `${traces.length} exigence(s) affichée(s) · ${selected} sélectionnée(s)`
        : `${traces.length} exigence(s) affichée(s) — registre local, sans envoi automatique.`;
    }
    if (empty) empty.hidden = traces.length > 0;
    traces.forEach((trace) => target.append(traceCard(trace)));
  }

  function traceCard(trace) {
    const card = el("article", "", "job-card");
    const header = el("div", "", "job-card-header");
    const copy = el("div");
    copy.append(el("h3", trace.requirement_text || trace.requirement_id));
    copy.append(el("p", `${trace.source} · ${categoryLabels[trace.category] || trace.category}`, "job-company"));
    header.append(copy, statusChip(trace.status));

    const meta = el("div", "", "inline-actions");
    meta.append(el("span", criticalityLabels[trace.criticality] || trace.criticality, "local-tag"));
    if (trace.evidence_id) {
      meta.append(el("span", `Preuve : ${trace.evidence_id}`, "local-tag"));
    } else {
      meta.append(el("span", "Aucune preuve", "local-tag"));
    }
    if (trace.justification) meta.append(el("span", `Renonciation : ${trace.justification}`, "local-tag"));
    (trace.tags || []).forEach((tag) => meta.append(el("span", `#${tag}`, "job-chip")));

    const selection = el("label", "", "scoring-disclaimer");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = state.selected.has(trace.trace_id);
    box.dataset.traceId = trace.trace_id;
    box.addEventListener("change", () => {
      if (box.checked) state.selected.add(trace.trace_id);
      else state.selected.delete(trace.trace_id);
      renderList();
    });
    selection.append(box, document.createTextNode(" Sélectionner"));

    const actions = el("div", "", "inline-actions job-actions");
    const history = el("button", "Historique", "quiet-button");
    history.type = "button";
    history.addEventListener("click", () => openDetail(trace.trace_id));

    const link = el("button", "Lier une preuve", "quiet-button");
    link.type = "button";
    link.addEventListener("click", () => linkEvidence(trace.trace_id));

    const waive = el("button", "Renoncer", "quiet-button");
    waive.type = "button";
    waive.addEventListener("click", () => waiveRequirement(trace.trace_id));

    const unlink = el("button", "Retirer la preuve", "quiet-button");
    unlink.type = "button";
    unlink.disabled = !trace.evidence_id;
    unlink.addEventListener("click", () => unlinkEvidence(trace.trace_id));

    actions.append(selection, history, link, unlink, waive);
    card.append(header, meta, actions);
    return card;
  }

  async function openDetail(traceId) {
    const panel = q("#traceability-detail");
    const wrapper = q("#traceability-detail-panel");
    if (!panel) return;
    try {
      const trace = await api(`${API}/requirements/${encodeURIComponent(traceId)}`);
      state.detail = trace;
      if (wrapper) wrapper.hidden = false;
      panel.replaceChildren();
      panel.append(el("h3", trace.requirement_text || trace.requirement_id));
      const facts = el("ul", "", "scoring-list");
      [
        ["Identifiant", trace.requirement_id],
        ["Source", trace.source],
        ["Catégorie", categoryLabels[trace.category] || trace.category],
        ["Criticité", criticalityLabels[trace.criticality] || trace.criticality],
        ["Statut", statusLabels[trace.status] || trace.status],
        ["Preuve", trace.evidence_id || "aucune"],
        ["Citation", trace.evidence_quote || "aucune"],
        ["Mise à jour", trace.updated_at],
      ].forEach(([label, value]) => facts.append(el("li", `${label} : ${value}`)));
      panel.append(facts);
      panel.append(el("h4", "Historique"));
      const timeline = el("ul", "", "scoring-list");
      (trace.history || []).forEach((event) => {
        const detail = [eventLabels[event.event_type] || event.event_type, event.timestamp, event.actor];
        if (event.old_value || event.new_value) detail.push(`${event.old_value || "—"} → ${event.new_value || "—"}`);
        if (event.comment) detail.push(event.comment);
        timeline.append(el("li", detail.join(" · ")));
      });
      panel.append(timeline);
      panel.scrollIntoView({ block: "nearest" });
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function linkEvidence(traceId) {
    const evidenceId = window.prompt("Identifiant de la preuve (ex. ev_1234) :");
    if (!evidenceId) return;
    const quote = window.prompt("Citation exacte de la preuve :") || "";
    try {
      await api(`${API}/requirements/${encodeURIComponent(traceId)}/link-evidence`, {
        method: "POST",
        body: JSON.stringify({ evidence_id: evidenceId, evidence_quote: quote, actor: "user" }),
      });
      setMessage("Preuve liée : l’exigence est maintenant couverte.");
      await loadTraces();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function unlinkEvidence(traceId) {
    try {
      await api(`${API}/requirements/${encodeURIComponent(traceId)}/unlink-evidence`, {
        method: "POST",
        body: JSON.stringify({ actor: "user", comment: "Preuve retirée depuis le registre" }),
      });
      setMessage("Preuve retirée : l’exigence n’est plus couverte.");
      await loadTraces();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function waiveRequirement(traceId) {
    const justification = window.prompt("Justification de la renonciation :");
    if (!justification) return;
    try {
      await api(`${API}/requirements/${encodeURIComponent(traceId)}/waive`, {
        method: "POST",
        body: JSON.stringify({ justification, actor: "user" }),
      });
      setMessage("Exigence renoncée : la justification est conservée dans l’historique.");
      await loadTraces();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function applyBatchStatus() {
    const status = q("#traceability-batch-status-value")?.value || "";
    if (!status || state.selected.size === 0) {
      setMessage("Choisis un statut et au moins une exigence avant d’appliquer l’action groupée.", true);
      return;
    }
    const comment = q("#traceability-batch-comment")?.value.trim() || "Action groupée";
    const targets = Array.from(state.selected);
    try {
      for (const traceId of targets) {
        await api(`${API}/requirements/${encodeURIComponent(traceId)}`, {
          method: "PATCH",
          body: JSON.stringify({ status, comment, actor: "user" }),
        });
      }
      state.selected.clear();
      setMessage(`${targets.length} exigence(s) passées en « ${statusLabels[status] || status} ».`);
      await loadTraces();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function applyBatchWaive() {
    const justification = q("#traceability-batch-justification")?.value.trim() || "";
    if (!justification || state.selected.size === 0) {
      setMessage("Écris une justification et sélectionne au moins une exigence.", true);
      return;
    }
    const targets = Array.from(state.selected);
    try {
      for (const traceId of targets) {
        await api(`${API}/requirements/${encodeURIComponent(traceId)}/waive`, {
          method: "POST",
          body: JSON.stringify({ justification, actor: "user" }),
        });
      }
      state.selected.clear();
      setMessage(`${targets.length} exigence(s) renoncée(s) : chaque justification est conservée.`);
      await loadTraces();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function loadAudit() {
    const target = q("#traceability-audit");
    if (!target) return;
    try {
      const [coverage, gaps, waived] = await Promise.all([
        api(`${API}/audit/coverage`),
        api(`${API}/audit/gaps`),
        api(`${API}/audit/waived`),
      ]);
      const summary = coverage.summary || {};
      target.replaceChildren();
      const metrics = el("div", "", "metrics");
      [
        [String(summary.total || 0), "Exigences tracées"],
        [`${summary.covered_pct || 0} %`, "Exigences couvertes"],
        [String(summary.critical_gaps || 0), "Gaps obligatoires"],
        [String(summary.waived || 0), "Renonciations"],
      ].forEach(([value, label]) => {
        const metric = el("article", "", "metric");
        metric.append(el("strong", value), el("span", label));
        metrics.append(metric);
      });
      target.append(metrics);

      const offers = el("ul", "", "scoring-list");
      (coverage.by_offer || []).forEach((offer) => {
        offers.append(
          el(
            "li",
            `${offer.offer_id} — ${offer.covered}/${offer.assessed} couverte(s) (${offer.covered_pct} %), ${offer.partial} partielle(s), ${offer.uncovered} non couverte(s).`,
          ),
        );
      });
      if (offers.childElementCount) {
        target.append(el("h4", "Couverture par offre"));
        target.append(offers);
      }

      if ((gaps.gaps || []).length) {
        target.append(el("h4", "Gaps obligatoires"));
        const list = el("ul", "", "scoring-list");
        gaps.gaps.forEach((gap) => {
          list.append(el("li", `${gap.source} — ${gap.requirement_text} (${gap.status})`));
        });
        target.append(list);
      }

      if ((waived.waived || []).length) {
        target.append(el("h4", "Exigences renoncées"));
        const list = el("ul", "", "scoring-list");
        waived.waived.forEach((item) => {
          list.append(el("li", `${item.source} — ${item.requirement_text} : ${item.justification || "sans justification"}`));
        });
        target.append(list);
      }
    } catch (error) {
      target.replaceChildren(el("p", error.message, "scoring-disclaimer"));
    }
  }

  function fillSelects() {
    const statusSelect = q("#traceability-filter-status");
    if (statusSelect && statusSelect.options.length <= 1) {
      Object.entries(statusLabels).forEach(([value, label]) => statusSelect.append(new Option(label, value)));
    }
    const categorySelect = q("#traceability-filter-category");
    if (categorySelect && categorySelect.options.length <= 1) {
      Object.entries(categoryLabels).forEach(([value, label]) => categorySelect.append(new Option(label, value)));
    }
    const criticalitySelect = q("#traceability-filter-criticality");
    if (criticalitySelect && criticalitySelect.options.length <= 1) {
      Object.entries(criticalityLabels).forEach(([value, label]) => criticalitySelect.append(new Option(label, value)));
    }
    const batchSelect = q("#traceability-batch-status-value");
    if (batchSelect && batchSelect.options.length <= 1) {
      Object.entries(statusLabels).forEach(([value, label]) => batchSelect.append(new Option(label, value)));
    }
  }

  function bind() {
    fillSelects();
    q("#traceability-filters")?.addEventListener("submit", (event) => {
      event.preventDefault();
      loadTraces();
    });
    qa("#traceability-filters select, #traceability-filters input").forEach((field) => {
      field.addEventListener("change", () => loadTraces());
    });
    q("#traceability-sort")?.addEventListener("change", (event) => {
      state.sort = event.target.value;
      renderList();
    });
    q("#traceability-refresh")?.addEventListener("click", () => loadTraces());
    q("#traceability-batch-status")?.addEventListener("click", () => applyBatchStatus());
    q("#traceability-batch-waive")?.addEventListener("click", () => applyBatchWaive());
    q("#traceability-detail-close")?.addEventListener("click", () => {
      const wrapper = q("#traceability-detail-panel");
      if (wrapper) wrapper.hidden = true;
    });
    q("#tab-traceability")?.addEventListener("click", () => loadTraces());
    window.addEventListener("hashchange", () => {
      if (window.location.hash === "#career/traceability") loadTraces();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  window.careerTraceability = { load: loadTraces, state };
})();
