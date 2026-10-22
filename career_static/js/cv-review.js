"use strict";

/*
 * SPEC-004 — Espace de revue du CV ciblé (evidence-backed review workspace).
 *
 * L'utilisateur voit chaque adaptation du CV ciblé à côté de son texte
 * source, avec la preuve qui la soutient, puis décide : accepter, modifier,
 * refuser ou rouvrir le bloc.  L'export DOCX reste désactivé tant que les
 * blocs critiques ne sont pas validés.
 *
 * 100 % local : le module appelle uniquement les endpoints Career locaux
 * (/api/career/cv-review/...), n'envoie rien et n'invente aucune donnée.
 */

const CV_REVIEW_ENDPOINT = "/api/career/cv-review";

const CV_REVIEW_STATUS_LABELS = {
  pending: "À vérifier",
  verified: "Vérifié",
  accepted: "Accepté",
  rejected: "Refusé",
  modified: "Modifié",
};

const CV_REVIEW_STATUS_HINTS = {
  pending: "Aucune décision : le bloc reste à relire.",
  verified: "Preuve directe dans le texte source : accepté automatiquement.",
  accepted: "Validé par toi : la proposition est exportée telle quelle.",
  rejected: "Refusé : la section garde le texte source.",
  modified: "Modifié par toi : ton texte est exporté.",
};

/* Badge de preuve : vert quand une preuve directe existe, rouge quand la
   proposition contient encore un marqueur à compléter, jaune sinon. */
function cvReviewEvidenceBadge(block) {
  if (block.placeholder_reason) {
    return { className: "cv-review-badge-placeholder", label: "🔴 Placeholder" };
  }
  if (block.status === "verified") {
    return { className: "cv-review-badge-verified", label: "🟢 Vérifié" };
  }
  return { className: "cv-review-badge-pending", label: "🟡 À vérifier" };
}

function cvReviewElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

async function cvReviewApi(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = "La revue du CV a échoué.";
    try {
      const payload = await response.json();
      if (payload && payload.detail) detail = String(payload.detail);
    } catch (error) {
      /* La réponse n'était pas du JSON : on garde le message par défaut. */
    }
    throw new Error(detail);
  }
  return response.json();
}

/* --------------------------------------------------------------------- */
/* Rendu                                                                  */
/* --------------------------------------------------------------------- */

function cvReviewRenderDiff(container, block) {
  const diff = Array.isArray(block.diff) ? block.diff : [];
  if (!diff.length) {
    container.appendChild(
      cvReviewElement("p", "cv-review-diff-empty", "Aucune différence entre le source et la proposition.")
    );
    return;
  }
  const list = cvReviewElement("div", "cv-review-diff");
  diff.forEach((segment) => {
    const op = segment && segment.op ? segment.op : "equal";
    const text = segment && segment.text ? segment.text : "";
    if (!text) return;
    list.appendChild(cvReviewElement("span", `cv-review-diff-${op}`, text));
  });
  container.appendChild(list);
}

function cvReviewRenderEvidence(container, block) {
  const evidence = Array.isArray(block.evidence) ? block.evidence : [];
  if (!evidence.length) {
    container.appendChild(
      cvReviewElement(
        "p",
        "cv-review-evidence-none",
        "Aucune preuve directe : cette proposition n'est pas dans ton texte source."
      )
    );
    return;
  }
  const list = cvReviewElement("ul", "cv-review-evidence");
  evidence.forEach((item) => {
    const entry = cvReviewElement("li", `cv-review-evidence-${item.kind || "source"}`);
    const origin = cvReviewElement("span", "cv-review-evidence-origin", item.label || item.source || "");
    const quote = cvReviewElement("q", "cv-review-evidence-quote", item.quote || "");
    const offsets = cvReviewElement(
      "span",
      "cv-review-evidence-offset",
      `offset ${Number(item.offset) || 0} · longueur ${Number(item.length) || 0}`
    );
    entry.appendChild(origin);
    entry.appendChild(quote);
    entry.appendChild(offsets);
    list.appendChild(entry);
  });
  container.appendChild(list);
}

function cvReviewRenderEditor(block, onSave) {
  const editor = cvReviewElement("div", "cv-review-editor");
  editor.hidden = true;
  const textarea = cvReviewElement("textarea", "cv-review-editor-text");
  textarea.rows = 5;
  textarea.maxLength = 6000;
  textarea.value = block.user_text || block.proposed_text || "";
  textarea.setAttribute("aria-label", `Texte proposé pour ${block.heading || block.section}`);
  const actions = cvReviewElement("div", "cv-review-editor-actions");
  const save = cvReviewElement("button", "primary-button", "Enregistrer la modification");
  save.type = "button";
  save.addEventListener("click", () => onSave(textarea.value));
  const cancel = cvReviewElement("button", "secondary-button", "Annuler");
  cancel.type = "button";
  cancel.addEventListener("click", () => {
    editor.hidden = true;
  });
  actions.appendChild(save);
  actions.appendChild(cancel);
  editor.appendChild(textarea);
  editor.appendChild(actions);
  return editor;
}

function cvReviewRenderBlock(block, handlers) {
  const article = cvReviewElement("article", "cv-review-block");
  article.dataset.blockId = block.block_id || "";
  article.dataset.status = block.status || "pending";

  const heading = cvReviewElement("div", "cv-review-block-heading");
  const title = cvReviewElement("h4", "cv-review-block-title", block.heading || block.section || "");
  const badges = cvReviewElement("span", "cv-review-badges");
  const badge = cvReviewEvidenceBadge(block);
  badges.appendChild(cvReviewElement("span", `cv-review-badge ${badge.className}`, badge.label));
  badges.appendChild(
    cvReviewElement(
      "span",
      `cv-review-status cv-review-status-${block.status || "pending"}`,
      CV_REVIEW_STATUS_LABELS[block.status] || block.status || ""
    )
  );
  if (block.critical) {
    badges.appendChild(cvReviewElement("span", "cv-review-badge-critical", "Bloc critique"));
  }
  heading.appendChild(title);
  heading.appendChild(badges);
  article.appendChild(heading);

  if (block.placeholder_reason) {
    const warning = cvReviewElement("p", "cv-review-placeholder", block.placeholder_reason);
    article.appendChild(warning);
  }

  const columns = cvReviewElement("div", "cv-review-columns");
  const sourceColumn = cvReviewElement("div", "cv-review-column cv-review-column-source");
  sourceColumn.appendChild(cvReviewElement("h5", "cv-review-column-title", "Texte source"));
  sourceColumn.appendChild(
    cvReviewElement("pre", "cv-review-text", block.source_text || "(aucun texte source)")
  );
  const proposedColumn = cvReviewElement("div", "cv-review-column cv-review-column-proposed");
  proposedColumn.appendChild(cvReviewElement("h5", "cv-review-column-title", "Proposition ciblée"));
  proposedColumn.appendChild(
    cvReviewElement("pre", "cv-review-text", block.proposed_text || "(aucune proposition)")
  );
  columns.appendChild(sourceColumn);
  columns.appendChild(proposedColumn);
  article.appendChild(columns);

  const diffBox = cvReviewElement("div", "cv-review-diff-box");
  diffBox.appendChild(cvReviewElement("h5", "cv-review-column-title", "Diff phrase par phrase"));
  cvReviewRenderDiff(diffBox, block);
  article.appendChild(diffBox);

  const evidenceBox = cvReviewElement("div", "cv-review-evidence-box");
  evidenceBox.appendChild(cvReviewElement("h5", "cv-review-column-title", "Preuve"));
  cvReviewRenderEvidence(evidenceBox, block);
  article.appendChild(evidenceBox);

  const actions = cvReviewElement("div", "cv-review-actions");
  const accept = cvReviewElement("button", "primary-button", "✅ Accepter");
  accept.type = "button";
  accept.addEventListener("click", () => handlers.decide(block.block_id, "accepted"));
  const modify = cvReviewElement("button", "secondary-button", "✏️ Modifier");
  modify.type = "button";
  modify.addEventListener("click", () => {
    const editor = article.querySelector(".cv-review-editor");
    if (editor) editor.hidden = false;
  });
  const reject = cvReviewElement("button", "secondary-button", "❌ Refuser");
  reject.type = "button";
  reject.title = "Le bloc est refusé : la section garde le texte source.";
  reject.addEventListener("click", () => handlers.decide(block.block_id, "rejected"));
  const reopen = cvReviewElement("button", "quiet-button", "↩️ Source");
  reopen.type = "button";
  reopen.title = "Rouvrir le bloc : la décision est annulée et le texte source reste affiché.";
  reopen.addEventListener("click", () => handlers.decide(block.block_id, "pending"));
  actions.appendChild(accept);
  actions.appendChild(modify);
  actions.appendChild(reject);
  actions.appendChild(reopen);
  article.appendChild(actions);

  const editor = cvReviewRenderEditor(block, (value) => handlers.modify(block.block_id, value));
  article.appendChild(editor);

  const hint = cvReviewElement("p", "cv-review-block-hint", CV_REVIEW_STATUS_HINTS[block.status] || "");
  article.appendChild(hint);
  return article;
}

/* --------------------------------------------------------------------- */
/* Vue                                                                    */
/* --------------------------------------------------------------------- */

function cvReviewSetStatus(message, isError) {
  const status = document.querySelector("#cv-review-status");
  if (!status) return;
  status.textContent = message || "";
  status.classList.toggle("cv-review-status-error", Boolean(isError));
}

function cvReviewRenderWorkspace(payload) {
  const blocks = document.querySelector("#cv-review-blocks");
  const empty = document.querySelector("#cv-review-empty");
  const progress = document.querySelector("#cv-review-progress");
  const progressLabel = document.querySelector("#cv-review-progress-label");
  const progressCount = document.querySelector("#cv-review-progress-count");
  const progressBar = document.querySelector("#cv-review-progress-bar");
  const progressFill = document.querySelector("#cv-review-progress-fill");
  const reasons = document.querySelector("#cv-review-reasons");
  const exportButton = document.querySelector("#cv-review-export");
  if (!blocks) return;

  blocks.innerHTML = "";
  const list = Array.isArray(payload.blocks) ? payload.blocks : [];
  const handlers = {
    decide: (blockId, status) => window.CvReview.decide(blockId, status),
    modify: (blockId, value) => window.CvReview.decide(blockId, "modified", value),
  };
  list.forEach((block) => blocks.appendChild(cvReviewRenderBlock(block, handlers)));

  if (empty) {
    empty.hidden = list.length > 0;
    empty.textContent = list.length
      ? ""
      : "Aucun bloc à relire : le CV ciblé est vide pour cette candidature.";
  }

  const stats = payload.progress || {};
  const percent = Number(stats.percent) || 0;
  if (progress) progress.hidden = false;
  if (progressLabel) {
    progressLabel.textContent = "Blocs critiques validés";
  }
  if (progressCount) {
    progressCount.textContent = `${Number(stats.critical_validated) || 0}/${Number(stats.critical_total) || 0}`;
  }
  if (progressBar) {
    progressBar.setAttribute("aria-valuenow", String(percent));
    progressBar.setAttribute("aria-valuetext", `${percent} %`);
  }
  if (progressFill) {
    progressFill.style.width = `${percent}%`;
  }

  const blocking = Array.isArray(payload.blocking_reasons) ? payload.blocking_reasons : [];
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
  if (reasons) {
    reasons.innerHTML = "";
    const messages = blocking.map((text) => ({ text, className: "cv-review-reason-blocking" }));
    warnings.forEach((text) => messages.push({ text, className: "cv-review-reason-warning" }));
    reasons.hidden = messages.length === 0;
    messages.forEach((message) => {
      reasons.appendChild(cvReviewElement("li", message.className, message.text));
    });
  }

  if (exportButton) {
    const allowed = Boolean(payload.can_export);
    exportButton.disabled = !allowed;
    exportButton.title = allowed
      ? "Exporter le CV révisé en DOCX (local)."
      : `Export bloqué : ${blocking.join(" ") || "les blocs critiques ne sont pas validés."}`;
  }
  window.CvReview.state.workspace = payload;
}

async function cvReviewLoadApplications() {
  const select = document.querySelector("#cv-review-application");
  if (!select) return;
  try {
    const payload = await cvReviewApi("/api/career/applications");
    const applications = (payload && payload.applications) || [];
    const previous = select.value;
    select.innerHTML = "";
    const placeholder = cvReviewElement("option", "", "Choisis une candidature…");
    placeholder.value = "";
    select.appendChild(placeholder);
    applications.forEach((application) => {
      const option = cvReviewElement(
        "option",
        "",
        `${application.company || "(entreprise)"} — ${application.title || "(poste)"}`
      );
      option.value = application.id || "";
      select.appendChild(option);
    });
    if (previous) select.value = previous;
    window.CvReview.state.applications = applications;
  } catch (error) {
    cvReviewSetStatus(error.message, true);
  }
}

async function cvReviewLoadWorkspace(applicationId) {
  if (!applicationId) {
    window.CvReview.state.workspace = null;
    cvReviewRenderWorkspace({ blocks: [], progress: {}, can_export: false, blocking_reasons: [] });
    return;
  }
  cvReviewSetStatus("Chargement de la revue…");
  try {
    const payload = await cvReviewApi(`${CV_REVIEW_ENDPOINT}/${encodeURIComponent(applicationId)}`);
    cvReviewRenderWorkspace(payload);
    cvReviewSetStatus("");
  } catch (error) {
    cvReviewSetStatus(error.message, true);
  }
}

async function cvReviewDecide(blockId, status, userText) {
  const state = window.CvReview.state;
  if (!state.applicationId) {
    cvReviewSetStatus("Choisis d'abord une candidature.", true);
    return;
  }
  cvReviewSetStatus("Enregistrement de la décision…");
  try {
    const payload = await cvReviewApi(`${CV_REVIEW_ENDPOINT}/${encodeURIComponent(state.applicationId)}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block_id: blockId, status, user_text: userText || "" }),
    });
    cvReviewRenderWorkspace(payload);
    cvReviewSetStatus("");
  } catch (error) {
    cvReviewSetStatus(error.message, true);
  }
}

async function cvReviewExport() {
  const state = window.CvReview.state;
  if (!state.applicationId) {
    cvReviewSetStatus("Choisis d'abord une candidature.", true);
    return;
  }
  cvReviewSetStatus("Génération du DOCX…");
  try {
    const response = await fetch(`${CV_REVIEW_ENDPOINT}/${encodeURIComponent(state.applicationId)}/export`);
    if (!response.ok) {
      let detail = "L'export du CV révisé a échoué.";
      try {
        const payload = await response.json();
        if (payload && payload.detail) detail = String(payload.detail);
      } catch (error) {
        /* Réponse non JSON : message par défaut. */
      }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "cv-revu.docx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    cvReviewSetStatus("CV révisé exporté en DOCX.");
  } catch (error) {
    cvReviewSetStatus(error.message, true);
  }
}

/* --------------------------------------------------------------------- */
/* Initialisation                                                          */
/* --------------------------------------------------------------------- */

window.CvReview = {
  state: { applicationId: "", applications: [], workspace: null },
  loadApplications: cvReviewLoadApplications,
  loadWorkspace: cvReviewLoadWorkspace,
  decide: cvReviewDecide,
  export: cvReviewExport,
  render: cvReviewRenderWorkspace,
  badge: cvReviewEvidenceBadge,
};

function cvReviewInit() {
  const select = document.querySelector("#cv-review-application");
  if (select) {
    select.addEventListener("change", () => {
      window.CvReview.state.applicationId = select.value || "";
      cvReviewLoadWorkspace(window.CvReview.state.applicationId);
    });
    select.addEventListener("focus", () => cvReviewLoadApplications());
  }
  const refresh = document.querySelector("#cv-review-refresh");
  if (refresh) {
    refresh.addEventListener("click", () => {
      cvReviewLoadApplications();
      cvReviewLoadWorkspace(window.CvReview.state.applicationId);
    });
  }
  const exportButton = document.querySelector("#cv-review-export");
  if (exportButton) {
    exportButton.addEventListener("click", () => cvReviewExport());
  }
  const view = document.querySelector("#view-applications");
  if (view && typeof MutationObserver === "function") {
    const observer = new MutationObserver(() => {
      if (!view.hidden) cvReviewLoadApplications();
    });
    observer.observe(view, { attributes: true, attributeFilter: ["hidden"] });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", cvReviewInit);
} else {
  cvReviewInit();
}
