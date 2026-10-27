"use strict";

/*
 * SPEC-008 — Centre de preuves unifié.
 *
 * Interface locale du centre de preuves : une grille de toutes les
 * affirmations documentées, un détail qui montre la citation et la source,
 * et des actions qui restent des décisions explicites de la personne
 * (approuver, attacher, fusionner, supprimer, bloquer l'usage).
 *
 * Règles :
 * - aucun appel réseau : tout passe par l'API locale ``/api/career/evidence`` ;
 * - aucune approbation automatique : le bouton « Approuver » est le seul
 *   chemin vers un statut « approuvé » ;
 * - une affirmation sans preuve reste « non prouvée », jamais « fausse ».
 */

const evidenceTypeLabels = {
  experience: "Expérience",
  education: "Formation",
  skill: "Compétence",
  language: "Langue",
  project: "Projet",
  certification: "Certification",
};

const evidenceConfidenceLabels = {
  direct: "Directe",
  inferred: "Déduite",
  declared: "Déclarée",
};

const evidenceState = {
  items: [],
  stats: {},
  selectedId: "",
  mergeIds: new Set(),
  requestSeq: 0,
  searchTimer: 0,
};

function evidenceById(id) {
  return evidenceState.items.find((item) => item.id === id) || null;
}

function evidenceLabel(value) {
  return evidenceTypeLabels[value] || value || "—";
}

function evidenceConfidenceLabel(value) {
  return evidenceConfidenceLabels[value] || value || "—";
}

function evidenceStatus(item) {
  if (!item) return "inconnue";
  if (item.blocked) return "bloquée pour l’usage";
  if (item.expired) return "expirée";
  if (item.approved) return "approuvée";
  const merged = (item.additional_sources || []).some((source) => source && source.approved);
  if (merged) return "approuvée (source fusionnée)";
  return "non approuvée";
}

function evidenceStatusClass(item) {
  if (!item) return "";
  if (item.blocked) return "danger";
  if (item.expired) return "warning";
  if (item.approved) return "good";
  return "";
}

function evidenceQuery() {
  const params = new URLSearchParams();
  const search = document.getElementById("evidence-search")?.value.trim() || "";
  const type = document.getElementById("evidence-filter-type")?.value || "";
  const confidence = document.getElementById("evidence-filter-confidence")?.value || "";
  const approved = document.getElementById("evidence-filter-approved")?.value || "";
  const used = document.getElementById("evidence-filter-used")?.value || "";
  const blocked = document.getElementById("evidence-filter-blocked")?.value || "";
  if (search) params.set("q", search);
  if (type) params.set("evidence_type", type);
  if (confidence) params.set("confidence", confidence);
  if (approved) params.set("approved", approved);
  if (used) params.set("used", used);
  if (blocked) params.set("blocked", blocked);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function loadEvidenceCenter() {
  const grid = document.getElementById("evidence-grid");
  const sequence = ++evidenceState.requestSeq;
  if (grid) grid.setAttribute("aria-busy", "true");
  try {
    const [list, stats] = await Promise.all([
      api(`/api/career/evidence${evidenceQuery()}`),
      api("/api/career/evidence/stats"),
    ]);
    // Une réponse plus ancienne ne doit jamais remplacer une réponse plus
    // récente : la recherche est saisie au clavier.
    if (sequence !== evidenceState.requestSeq) return;
    evidenceState.items = Array.isArray(list?.evidence) ? list.evidence : [];
    evidenceState.stats = stats || {};
    if (!evidenceById(evidenceState.selectedId)) evidenceState.selectedId = "";
    evidenceState.mergeIds.forEach((id) => {
      if (!evidenceById(id)) evidenceState.mergeIds.delete(id);
    });
    renderEvidenceStats(evidenceState.stats);
    renderEvidenceGrid(evidenceState.items);
    renderEvidenceDetail(evidenceById(evidenceState.selectedId));
  } catch (error) {
    if (sequence === evidenceState.requestSeq && typeof setMessage === "function") setMessage(error.message, true);
  } finally {
    if (grid && sequence === evidenceState.requestSeq) grid.removeAttribute("aria-busy");
  }
}

function renderEvidenceStats(stats) {
  const proven = Number(stats?.proven_claims || 0);
  const unproven = Number(stats?.unproven_claims || 0);
  const expired = Number(stats?.expired || 0);
  const used = Number(stats?.used_in_cv || 0) + Number(stats?.used_in_letters || 0);
  const targets = {
    "evidence-stat-proven": proven,
    "evidence-stat-unproven": unproven,
    "evidence-stat-expired": expired,
    "evidence-stat-used": used,
  };
  Object.entries(targets).forEach(([id, value]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = String(value);
  });
}

function renderEvidenceGrid(items) {
  const grid = document.getElementById("evidence-grid");
  if (!grid) return;
  grid.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "evidence-empty";
    empty.textContent = "Aucune preuve pour l’instant. Ajoute une affirmation avec sa source : une citation sans document ne compte pas comme une preuve.";
    grid.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "evidence-row";
    row.classList.toggle("is-selected", item.id === evidenceState.selectedId);

    const select = document.createElement("input");
    select.type = "checkbox";
    select.className = "evidence-merge-select";
    select.checked = evidenceState.mergeIds.has(item.id);
    select.setAttribute("aria-label", `Sélectionner « ${item.claim} » pour une fusion`);
    select.addEventListener("change", () => {
      if (select.checked) evidenceState.mergeIds.add(item.id);
      else evidenceState.mergeIds.delete(item.id);
      renderEvidenceGrid(evidenceState.items);
      // Le panneau de détail montre l'action de fusion : il doit refléter
      // la sélection sans attendre un rechargement.
      renderEvidenceDetail(evidenceById(evidenceState.selectedId));
    });

    const open = document.createElement("button");
    open.type = "button";
    open.className = "evidence-row-open";
    open.addEventListener("click", () => {
      evidenceState.selectedId = item.id;
      renderEvidenceGrid(evidenceState.items);
      renderEvidenceDetail(item);
    });

    const claim = document.createElement("span");
    claim.className = "evidence-row-claim";
    claim.textContent = item.claim || "(sans affirmation)";

    const meta = document.createElement("span");
    meta.className = "evidence-row-meta";
    meta.textContent = [
      evidenceLabel(item.evidence_type),
      `confiance ${evidenceConfidenceLabel(item.confidence)}`,
      evidenceStatus(item),
      item.source_document ? `source ${item.source_document}` : "sans document",
    ].join(" · ");

    const badge = document.createElement("span");
    badge.className = `job-chip ${evidenceStatusClass(item)}`.trim();
    badge.textContent = item.proven ? "prouvée" : evidenceStatus(item);

    open.append(claim, meta);
    row.append(select, open, badge);
    grid.appendChild(row);
  });
}

function renderEvidenceDetail(item) {
  const detail = document.getElementById("evidence-detail");
  if (!detail) return;
  detail.innerHTML = "";
  if (!item) {
    const empty = document.createElement("p");
    empty.className = "evidence-empty";
    empty.textContent = "Sélectionne une preuve pour voir sa citation, sa source et son usage.";
    detail.appendChild(empty);
    return;
  }

  const title = document.createElement("h4");
  title.className = "evidence-detail-title";
  title.textContent = item.claim || "(sans affirmation)";

  const badges = document.createElement("div");
  badges.className = "inline-actions";
  [
    [evidenceLabel(item.evidence_type), ""],
    [evidenceConfidenceLabel(item.confidence), ""],
    [evidenceStatus(item), evidenceStatusClass(item)],
  ].forEach(([label, variant]) => {
    const chip = document.createElement("span");
    chip.className = `job-chip ${variant}`.trim();
    chip.textContent = label;
    badges.appendChild(chip);
  });

  const quote = document.createElement("blockquote");
  quote.className = "evidence-quote";
  quote.textContent = item.quote || "Aucune citation enregistrée.";

  const source = document.createElement("p");
  source.className = "evidence-source";
  source.textContent = item.source_document
    ? `Source : ${item.source_document}${item.source_location ? ` — ${item.source_location}` : ""}`
    : "Aucune source jointe : cette affirmation reste déclarative.";

  const usage = document.createElement("p");
  usage.className = "evidence-source";
  const usageParts = [];
  if (item.used_in_cv) usageParts.push("utilisée dans un CV");
  if (item.used_in_letters) usageParts.push("utilisée dans une lettre");
  usage.textContent = usageParts.length ? `Usage : ${usageParts.join(", ")}.` : "Usage : aucune utilisation enregistrée.";

  const attachments = document.createElement("p");
  attachments.className = "evidence-source";
  const attached = Array.isArray(item.attachments) ? item.attachments : [];
  attachments.textContent = attached.length
    ? `Pièces jointes : ${attached.map((entry) => entry.original_name || entry.name).join(", ")}.`
    : "Pièces jointes : aucune.";

  const merged = document.createElement("p");
  merged.className = "evidence-source";
  const mergedFrom = Array.isArray(item.merged_from) ? item.merged_from : [];
  merged.textContent = mergedFrom.length
    ? `Fusionnée avec : ${mergedFrom.join(", ")}.`
    : "";

  const actions = document.createElement("div");
  actions.className = "inline-actions evidence-actions";

  const approve = document.createElement("button");
  approve.type = "button";
  approve.className = item.approved ? "quiet-button" : "primary-button";
  approve.textContent = item.approved ? "Retirer l’approbation" : "✅ Approuver";
  approve.addEventListener("click", () => runEvidenceAction(() =>
    api(`/api/career/evidence/${item.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved: !item.approved }),
    })));

  const block = document.createElement("button");
  block.type = "button";
  block.className = "quiet-button";
  block.textContent = item.blocked ? "🔓 Autoriser l’usage" : "🚫 Bloquer l’usage";
  block.addEventListener("click", () => runEvidenceAction(() =>
    api(`/api/career/evidence/${item.id}/block`, {
      method: "POST",
      body: JSON.stringify({ blocked: !item.blocked }),
    })));

  const useCv = document.createElement("button");
  useCv.type = "button";
  useCv.className = "quiet-button";
  useCv.textContent = "Marquer utilisée dans un CV";
  useCv.addEventListener("click", () => runEvidenceAction(() =>
    api(`/api/career/evidence/${item.id}/usage`, {
      method: "POST",
      body: JSON.stringify({ target: "cv", context: "Centre de preuves" }),
    })));

  const useLetter = document.createElement("button");
  useLetter.type = "button";
  useLetter.className = "quiet-button";
  useLetter.textContent = "Marquer utilisée dans une lettre";
  useLetter.addEventListener("click", () => runEvidenceAction(() =>
    api(`/api/career/evidence/${item.id}/usage`, {
      method: "POST",
      body: JSON.stringify({ target: "letter", context: "Centre de preuves" }),
    })));

  const merge = document.createElement("button");
  merge.type = "button";
  merge.className = "quiet-button";
  const mergeTargets = [...evidenceState.mergeIds].filter((id) => id !== item.id);
  merge.textContent = mergeTargets.length ? `🔗 Fusionner (${mergeTargets.length})` : "🔗 Fusionner";
  merge.disabled = mergeTargets.length === 0;
  merge.title = mergeTargets.length
    ? `Fusionner avec ${mergeTargets.map((id) => evidenceById(id)?.claim || id).join(", ")}`
    : "Coche une ou plusieurs autres preuves dans la grille pour les fusionner";
  merge.addEventListener("click", () => {
    const others = mergeTargets.filter((id) => evidenceById(id));
    if (!others.length) return;
    runEvidenceAction(() =>
      api("/api/career/evidence/merge", {
        method: "POST",
        body: JSON.stringify({ ids: [item.id, ...others], keep_id: item.id }),
      }));
  });

  const attachLabel = document.createElement("label");
  attachLabel.className = "quiet-button evidence-attach-label";
  attachLabel.textContent = "📎 Attacher";
  const attachInput = document.createElement("input");
  attachInput.type = "file";
  attachInput.className = "evidence-attach-input";
  attachInput.addEventListener("change", () => {
    const file = attachInput.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    runEvidenceAction(() =>
      api(`/api/career/evidence/${item.id}/attach`, { method: "POST", body: form }));
    attachInput.value = "";
  });
  attachLabel.appendChild(attachInput);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "danger-button";
  remove.textContent = "🗑️ Supprimer";
  remove.addEventListener("click", () => {
    if (!window.confirm(`Supprimer la preuve « ${item.claim} » ?`)) return;
    runEvidenceAction(() => api(`/api/career/evidence/${item.id}`, { method: "DELETE" }));
  });

  actions.append(approve, block, useCv, useLetter, merge, attachLabel, remove);
  detail.append(title, badges, quote, source, usage, attachments, merged, actions);
}

async function runEvidenceAction(call) {
  try {
    await call();
    if (typeof setMessage === "function") setMessage("Preuve mise à jour.", false);
    await loadEvidenceCenter();
  } catch (error) {
    if (typeof setMessage === "function") setMessage(error.message, true);
  }
}

function bindEvidenceCenter() {
  const form = document.getElementById("evidence-create-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const tags = (document.getElementById("evidence-tags")?.value || "")
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
    const payload = {
      claim: document.getElementById("evidence-claim")?.value.trim() || "",
      evidence_type: document.getElementById("evidence-type")?.value || "skill",
      confidence: document.getElementById("evidence-confidence")?.value || "declared",
      source_document: document.getElementById("evidence-source-document")?.value.trim() || "",
      source_location: document.getElementById("evidence-source-location")?.value.trim() || "",
      quote: document.getElementById("evidence-quote")?.value.trim() || "",
      tags,
    };
    try {
      const created = await api("/api/career/evidence", { method: "POST", body: JSON.stringify(payload) });
      form.reset();
      evidenceState.selectedId = created?.id || "";
      if (typeof setMessage === "function") setMessage("Preuve enregistrée.", false);
      await loadEvidenceCenter();
    } catch (error) {
      if (typeof setMessage === "function") setMessage(error.message, true);
    }
  });

  ["evidence-filter-type", "evidence-filter-confidence", "evidence-filter-approved", "evidence-filter-used", "evidence-filter-blocked"]
    .forEach((id) => {
      document.getElementById(id)?.addEventListener("change", () => {
        loadEvidenceCenter().catch((error) => {
          if (typeof setMessage === "function") setMessage(error.message, true);
        });
      });
    });

  // La recherche est saisie au clavier : un délai évite une requête par
  // lettre, et la séquence protège contre une réponse plus ancienne.
  document.getElementById("evidence-search")?.addEventListener("input", () => {
    window.clearTimeout(evidenceState.searchTimer);
    evidenceState.searchTimer = window.setTimeout(() => {
      loadEvidenceCenter().catch((error) => {
        if (typeof setMessage === "function") setMessage(error.message, true);
      });
    }, 200);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindEvidenceCenter);
} else {
  bindEvidenceCenter();
}

if (typeof window !== "undefined") {
  window.loadEvidenceCenter = loadEvidenceCenter;
}
