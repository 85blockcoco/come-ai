"use strict";

/*
 * SPEC-004 — « Revue du CV ciblé » : diff source → proposition, preuve, décision.
 *
 * Données 100 % locales : le workspace de revue est construit et persisté par
 * career/cv_review.py et career/cv_review_store.py. Ce module ne contacte que
 * l'API Career locale (même origine, aucune requête externe, aucun cloud,
 * aucun consentement requis) pour enregistrer les décisions.
 *
 * Le module ne touche pas au DOM au chargement : career.js appelle
 * renderCvReview() avec le workspace reçu de l'API.
 */

const cvReviewStatusLabels = {
  verified: "Vérifié",
  accepted: "Accepté",
  modified: "Modifié",
  rejected: "Refusé",
  pending: "À vérifier",
  placeholder: "Placeholder",
};

const cvReviewBadgeGlyphs = {
  verified: "🟢",
  accepted: "✅",
  modified: "✏️",
  rejected: "❌",
  pending: "🟡",
  placeholder: "🔴",
};

const cvReviewDecisionLabels = {
  accepted: "✅ Accepter",
  modified: "✏️ Modifier",
  rejected: "❌ Refuser",
  pending: "↩️ Source",
};

/* La preuve affichée par bloc : vert quand la proposition est prouvée par le
   profil, jaune quand elle attend une confirmation, rouge quand il s'agit
   d'un placeholder sans preuve. */
function cvReviewBadge(block) {
  const key = block?.badge?.key
    || (block?.placeholder_reason ? "placeholder" : block?.status || "pending");
  const tone = block?.badge?.tone || "warning";
  const label = block?.badge?.label || cvReviewStatusLabels[key] || "À vérifier";
  const glyph = cvReviewBadgeGlyphs[key] || "🟡";
  return { key, tone, label, glyph, text: `${glyph} ${label}` };
}

function cvReviewProgress(workspace) {
  const progress = workspace?.progress || {};
  const total = Number(progress.critical_total || 0);
  const validated = Number(progress.critical_validated || 0);
  const percent = total ? Math.round((validated * 100) / total) : 100;
  return {
    total,
    validated,
    percent,
    label: progress.label || `${validated}/${total} blocs critiques validés`,
  };
}

function cvReviewExportEnabled(workspace) {
  return Boolean(workspace?.can_export) && !(workspace?.export_blockers || []).length;
}

function cvReviewExportTooltip(workspace) {
  if (cvReviewExportEnabled(workspace)) {
    return "Télécharger le CV révisé (DOCX local)";
  }
  const blockers = workspace?.export_blockers || [];
  if (!blockers.length) {
    return "Export bloqué : valide les blocs critiques avant d’exporter.";
  }
  return `Export bloqué : ${blockers.join(" ")}`;
}

function cvReviewExportUrl(applicationId) {
  return `/api/career/cv-review/${encodeURIComponent(applicationId)}/export`;
}

function renderCvReviewDiff(container, segments) {
  container.replaceChildren();
  (segments || []).forEach((segment) => {
    if (!segment || !segment.text) return;
    container.append(make("span", segment.text, `cv-review-diff cv-review-diff-${segment.op}`));
  });
  return container;
}

function renderCvReviewEvidence(block) {
  const evidence = make("div", "", "cv-review-evidence");
  (block.evidence || []).forEach((item) => {
    const row = make("p", "", "cv-review-evidence-item");
    row.append(make("span", item.source, "cv-review-evidence-source"));
    row.append(make("q", item.quote, "cv-review-evidence-quote"));
    evidence.append(row);
  });
  if (block.placeholder_reason) {
    evidence.append(make("p", block.placeholder_reason, "cv-review-placeholder-reason"));
  }
  return evidence;
}

function renderCvReviewBlock(block, handlers) {
  const onDecide = handlers?.onDecide || (() => {});
  const article = make("article", "", "cv-review-block");
  article.dataset.blockId = block.block_id;
  article.dataset.status = block.status;

  const header = make("header", "", "cv-review-block-header");
  header.append(make("span", block.section, "cv-review-block-section"));
  const badge = cvReviewBadge(block);
  header.append(make("span", badge.text, `cv-review-badge cv-review-badge-${badge.tone}`));
  article.append(header);

  const split = make("div", "", "cv-review-split");
  const source = make("div", "", "cv-review-source");
  source.append(make("h4", "Source"));
  source.append(make("p", block.source_text || "—", "cv-review-text"));
  const proposed = make("div", "", "cv-review-proposed");
  proposed.append(make("h4", "Proposition"));
  const proposedText = make("p", "", "cv-review-text cv-review-proposed-text");
  renderCvReviewDiff(proposedText, block.diff);
  proposed.append(proposedText);
  if (block.user_text) {
    proposed.append(make("p", block.user_text, "cv-review-user-text"));
  }
  split.append(source, proposed);
  article.append(split);

  article.append(renderCvReviewEvidence(block));

  const edit = make("textarea", "", "cv-review-edit");
  edit.setAttribute("aria-label", `Ton texte pour ${block.block_id}`);
  edit.rows = 3;
  edit.hidden = true;
  article.append(edit);

  const actions = make("div", "", "cv-review-actions");
  const save = make("button", "Enregistrer la modification", "quiet-button cv-review-action-save");
  save.type = "button";
  save.hidden = true;
  save.addEventListener("click", () => onDecide(block, "modified", edit.value));
  actions.append(save);
  Object.keys(cvReviewDecisionLabels).forEach((status) => {
    const button = make("button", cvReviewDecisionLabels[status], `cv-review-action cv-review-action-${status}`);
    button.type = "button";
    button.setAttribute("aria-label", `${cvReviewDecisionLabels[status]} : ${block.block_id}`);
    button.addEventListener("click", () => {
      if (status === "modified") {
        edit.hidden = false;
        save.hidden = false;
        edit.focus();
        return;
      }
      onDecide(block, status, "");
    });
    actions.append(button);
  });
  article.append(actions);
  return article;
}

function renderCvReview(container, workspace, handlers = {}) {
  if (!container) return null;
  const onDecide = handlers.onDecide || (() => {});
  container.replaceChildren();

  const progress = cvReviewProgress(workspace);
  const progressBar = make("div", "", "cv-review-progress-bar");
  progressBar.setAttribute("role", "progressbar");
  progressBar.setAttribute("aria-label", "Blocs critiques validés");
  progressBar.setAttribute("aria-valuemin", "0");
  progressBar.setAttribute("aria-valuemax", String(progress.total));
  progressBar.setAttribute("aria-valuenow", String(progress.validated));
  const fill = make("div", "", "cv-review-progress-fill");
  fill.style.width = `${progress.percent}%`;
  progressBar.append(fill);
  container.append(make("p", progress.label, "cv-review-progress-label"));
  container.append(progressBar);

  const blockers = workspace?.export_blockers || [];
  if (blockers.length) {
    const list = make("ul", "", "cv-review-blockers");
    blockers.forEach((reason) => list.append(make("li", reason, "cv-review-blocker")));
    container.append(list);
  }

  const blocks = make("div", "", "cv-review-blocks");
  (workspace?.blocks || []).forEach((block) => {
    blocks.append(renderCvReviewBlock(block, { onDecide }));
  });
  container.append(blocks);
  return container;
}

/* Une décision part vers l'API Career locale : rien n'est envoyé ailleurs. */
async function cvReviewDecide(applicationId, blockId, status, userText) {
  const payload = { block_id: blockId, status };
  const text = typeof userText === "string" ? userText.trim() : "";
  if (text) payload.user_text = text;
  return api(`/api/career/cv-review/${encodeURIComponent(applicationId)}/decide`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
