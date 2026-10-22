/*
 * SPEC-004 — Espace de revue du CV ciblé.
 *
 * Vue ligne par ligne : la formulation source à gauche, la formulation
 * proposée à droite, le diff coloré entre les deux, la preuve locale sous
 * chaque bloc, et quatre décisions possibles (Accepter / Modifier / Refuser
 * / Revenir à la source).
 *
 * Tout est local : les appels passent par l'API Career de cette machine,
 * aucun fournisseur externe n'est contacté et aucun contenu du CV n'est
 * écrit dans le navigateur (la décision est enregistrée côté Mac).
 *
 * Ce module ne touche pas au DOM au chargement : career.js appelle
 * renderCvReviewSection() pour insérer le panneau dans le kit de
 * candidature.
 */
(function () {
  "use strict";

  const STATUS_LABELS = {
    pending: "En attente de décision",
    verified: "Vérifié par la preuve",
    accepted: "Accepté",
    modified: "Modifié",
    rejected: "Source conservée",
  };

  const BADGES = {
    verified: { mark: "🟢", text: "Vérifié" },
    to_verify: { mark: "🟡", text: "À vérifier" },
    placeholder: { mark: "🔴", text: "Placeholder" },
    decided: { mark: "⚪", text: "Tranché" },
  };

  const STATUS_ACTIONS = {
    accepted: { label: "✅ Accepter", title: "Garder la formulation proposée" },
    modified: { label: "✏️ Modifier", title: "Écrire la formulation que tu retiens" },
    rejected: { label: "❌ Refuser", title: "Refuser l'adaptation : la source est exportée" },
    pending: { label: "↩️ Source", title: "Revenir à la formulation source et re-décider" },
  };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  async function request(url, options) {
    if (typeof window.api === "function") {
      return window.api(url, options);
    }
    const settings = Object.assign({}, options || {});
    const hasBody = settings.body && !(settings.body instanceof FormData);
    settings.headers = Object.assign(
      { "Content-Type": "application/json" },
      settings.headers || {}
    );
    if (!hasBody) delete settings.body;
    const response = await fetch(url, settings);
    const contentType = response.headers.get("content-type") || "";
    let payload = {};
    if (contentType.includes("application/json")) {
      try {
        payload = await response.json();
      } catch (error) {
        payload = {};
      }
    }
    if (!response.ok) {
      const detail =
        typeof payload.detail === "string"
          ? payload.detail
          : "L’action Career n’a pas abouti.";
      throw new Error(detail);
    }
    return payload;
  }

  function baseUrl(applicationId) {
    return `/api/career/applications/${encodeURIComponent(applicationId)}/cv-review`;
  }

  function reviewQuery(settings) {
    const query = [];
    if (settings.language) query.push(`language=${encodeURIComponent(settings.language)}`);
    if (settings.variant) query.push(`variant=${encodeURIComponent(settings.variant)}`);
    return query.length ? `?${query.join("&")}` : "";
  }

  function carriesMarker(text) {
    return /\[[^[\]\n]*[^\W\d_][^[\]\n]*\]/.test(String(text || ""));
  }

  function badgeFor(block) {
    const badge = BADGES[block.evidence_state] || BADGES.to_verify;
    return element("span", "cv-review-badge", `${badge.mark} ${badge.text}`);
  }

  function renderDiffSide(segments, kinds) {
    const side = element("div", "cv-review-side");
    let empty = true;
    segments.forEach((segment) => {
      if (!kinds.includes(segment.kind)) return;
      const span = element("span", `cv-review-diff-${segment.kind}`, segment.text);
      if (segment.kind !== "equal") empty = false;
      side.appendChild(span);
    });
    if (empty) side.appendChild(element("span", "cv-review-empty", "—"));
    return side;
  }

  function renderEvidence(block) {
    const wrapper = element("div", "cv-review-evidence");
    const list = block.evidence || [];
    if (!list.length) {
      wrapper.appendChild(element("span", "cv-review-evidence-none", "Aucune preuve jointe."));
      return wrapper;
    }
    list.forEach((item) => {
      const line = element("div", "cv-review-evidence-item");
      line.appendChild(element("span", "cv-review-evidence-source", item.source));
      line.appendChild(element("span", "cv-review-evidence-quote", `« ${item.quote} »`));
      line.appendChild(element("span", "cv-review-evidence-offset", `position ${item.offset}`));
      wrapper.appendChild(line);
    });
    return wrapper;
  }

  function renderBlock(block, onDecision) {
    const article = element("article", "cv-review-block");
    article.dataset.blockId = block.block_id;
    article.dataset.status = block.status;

    const head = element("header", "cv-review-block-head");
    head.appendChild(element("span", "cv-review-block-label", block.label || block.heading));
    head.appendChild(badgeFor(block));
    head.appendChild(
      element("span", "cv-review-block-status", STATUS_LABELS[block.status] || block.status)
    );
    article.appendChild(head);

    const diff = element("div", "cv-review-diff");
    diff.appendChild(renderDiffSide(block.diff || [], ["equal", "delete"]));
    diff.appendChild(renderDiffSide(block.diff || [], ["equal", "insert"]));
    article.appendChild(diff);

    article.appendChild(renderEvidence(block));

    if (block.placeholder_reason) {
      const warning = element("p", "cv-review-placeholder", block.placeholder_reason);
      article.appendChild(warning);
    }

    const actions = element("div", "cv-review-actions");
    const editor = element("div", "cv-review-editor");
    editor.hidden = true;
    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    textarea.maxLength = 4000;
    textarea.value = block.user_text || "";
    textarea.setAttribute("aria-label", "Texte retenu pour ce bloc");
    const save = element("button", "secondary-button", "Enregistrer ce texte");
    save.type = "button";
    editor.appendChild(textarea);
    editor.appendChild(save);

    Object.keys(STATUS_ACTIONS).forEach((status) => {
      const action = STATUS_ACTIONS[status];
      const button = element("button", "secondary-button", action.label);
      button.type = "button";
      button.title = action.title;
      button.dataset.action = status;
      if (status === "accepted" && carriesMarker(block.proposed_text)) {
        // Accepter une proposition qui contient encore un marqueur ne
        // débloquerait rien : il faut la réécrire ou la refuser.
        button.disabled = true;
        button.title = "Cette proposition contient encore une preuve à compléter : réécris-la ou refuse-la.";
      }
      button.addEventListener("click", () => {
        if (status === "modified") {
          editor.hidden = !editor.hidden;
          if (!editor.hidden) textarea.focus();
          return;
        }
        onDecision(block.block_id, status, "", block.proposed_text);
      });
      actions.appendChild(button);
    });
    save.addEventListener("click", () => {
      const value = textarea.value.trim();
      if (!value) {
        textarea.focus();
        return;
      }
      onDecision(block.block_id, "modified", value, block.proposed_text);
    });
    article.appendChild(actions);
    article.appendChild(editor);
    return article;
  }

  function renderProgress(progress) {
    const wrapper = element("div", "cv-review-progress");
    const bar = element("div", "cv-review-progress-bar");
    const fill = element("span", "cv-review-progress-fill");
    fill.style.width = `${Math.max(0, Math.min(100, Number(progress.pct) || 0))}%`;
    bar.appendChild(fill);
    wrapper.appendChild(bar);
    wrapper.appendChild(
      element(
        "p",
        "cv-review-progress-label",
        `${progress.critical_validated}/${progress.critical_total} blocs critiques validés`
      )
    );
    return wrapper;
  }

  function renderBlockers(payload) {
    const wrapper = element("div", "cv-review-blockers");
    const blockers = payload.export_blockers || [];
    if (!blockers.length) {
      wrapper.appendChild(
        element("p", "cv-review-ok", "Export DOCX autorisé : aucun bloc critique en attente.")
      );
      return wrapper;
    }
    wrapper.appendChild(element("p", "cv-review-ko", "Export DOCX bloqué :"));
    const list = element("ul", "cv-review-blocker-list");
    blockers.forEach((reason) => list.appendChild(element("li", "", reason)));
    wrapper.appendChild(list);
    return wrapper;
  }

  function renderHeader(header) {
    const wrapper = element("div", "cv-review-header");
    wrapper.appendChild(element("span", "cv-review-header-label", "En-tête du CV"));
    const lines = [header.display_name, header.contact_line, header.education_line].filter(
      (value) => value !== undefined && value !== null && String(value).trim() !== ""
    );
    if (!lines.length) {
      wrapper.appendChild(element("span", "cv-review-empty", "—"));
      return wrapper;
    }
    lines.forEach((line) => {
      const item = element("span", "cv-review-header-line", line);
      if (carriesMarker(line)) item.classList.add("cv-review-header-alert");
      wrapper.appendChild(item);
    });
    return wrapper;
  }

  function renderWorkspace(payload, scope, onDecision) {
    const root = element("div", "cv-review-body");
    root.appendChild(renderProgress(payload.progress || {}));
    root.appendChild(renderBlockers(payload));
    root.appendChild(renderHeader(payload.header || {}));

    const warnings = payload.warnings || [];
    if (warnings.length) {
      const warningBox = element("div", "cv-review-warnings");
      warningBox.appendChild(element("p", "", "À savoir avant l’export :"));
      const list = element("ul", "cv-review-warning-list");
      warnings.forEach((line) => list.appendChild(element("li", "", line)));
      warningBox.appendChild(list);
      root.appendChild(warningBox);
    }

    const blocks = element("div", "cv-review-blocks");
    (payload.blocks || []).forEach((block) => {
      blocks.appendChild(renderBlock(block, onDecision));
    });
    root.appendChild(blocks);

    const footer = element("div", "cv-review-footer");
    const exportButton = element("button", "primary-button", "Exporter le CV revu (DOCX)");
    exportButton.type = "button";
    const blockers = payload.export_blockers || [];
    if (blockers.length) {
      exportButton.disabled = true;
      exportButton.title = `Export bloqué : ${blockers.join(" ")}`;
    } else {
      exportButton.title = "Génère le DOCX local avec uniquement les formulations validées.";
    }
    exportButton.addEventListener("click", async () => {
      exportButton.disabled = true;
      try {
        await downloadDocx(scope);
      } catch (error) {
        const notice = element("p", "cv-review-ko", error.message);
        root.insertBefore(notice, root.firstChild);
      } finally {
        exportButton.disabled = blockers.length > 0;
      }
    });
    const historyButton = element("button", "secondary-button", "Historique des décisions");
    historyButton.type = "button";
    const historyBox = element("ol", "cv-review-history");
    historyBox.hidden = true;
    historyButton.addEventListener("click", async () => {
      if (!historyBox.hidden) {
        historyBox.hidden = true;
        return;
      }
      historyBox.hidden = false;
      historyBox.replaceChildren();
      try {
        const payloadHistory = await request(`${baseUrl(scope.applicationId)}/history${reviewQuery(scope)}`);
        const entries = payloadHistory.history || [];
        if (!entries.length) {
          historyBox.appendChild(element("li", "", "Aucune décision enregistrée."));
        }
        entries.forEach((entry) => {
          const item = element("li", "cv-review-history-item");
          item.appendChild(element("span", "cv-review-history-block", entry.block_id));
          item.appendChild(
            element(
              "span",
              "cv-review-history-transition",
              `${entry.from_status} → ${entry.to_status}`
            )
          );
          item.appendChild(element("span", "cv-review-history-date", entry.decided_at));
          historyBox.appendChild(item);
        });
      } catch (error) {
        historyBox.appendChild(element("li", "cv-review-ko", error.message));
      }
    });
    footer.appendChild(exportButton);
    footer.appendChild(historyButton);
    root.appendChild(footer);
    root.appendChild(historyBox);
    return root;
  }

  async function downloadDocx(options) {
    const response = await fetch(`${baseUrl(options.applicationId)}/export${reviewQuery(options)}`, {
      headers: { Accept: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
    });
    if (!response.ok) {
      let detail = "Le CV revu n’a pas pu être exporté.";
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string") detail = payload.detail;
      } catch (error) {
        /* the response carries no JSON body */
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
  }

  function renderCvReviewSection(options) {
    const settings = Object.assign({ applicationId: "", variant: "", language: "fr" }, options || {});
    if (!settings.applicationId) return null;
    const panel = element("section", "cv-review");
    panel.appendChild(element("h5", "cv-review-title", "Revue du CV ciblé"));
    panel.appendChild(
      element(
        "p",
        "cv-review-meta",
        "Chaque adaptation est affichée avec sa preuve locale. Rien n’est envoyé : la décision reste sur ce Mac."
      )
    );
    const body = element("div", "cv-review-loading", "Chargement de la revue…");
    panel.appendChild(body);

    const reload = async () => {
      try {
        const payload = await request(`${baseUrl(settings.applicationId)}${reviewQuery(settings)}`);
        // The decisions, the history and the export always carry the variant
        // that was really displayed: another variant must never receive a
        // decision taken on this one.
        const scope = Object.assign({}, settings, {
          variant: payload.variant_id || settings.variant || "",
        });
        body.replaceChildren(
          renderWorkspace(payload, scope, async (blockId, status, userText, reviewedText) => {
            try {
              await request(`${baseUrl(scope.applicationId)}/decide${reviewQuery(scope)}`, {
                method: "POST",
                body: JSON.stringify({
                  block_id: blockId,
                  status: status,
                  user_text: userText || "",
                  reviewed_text: reviewedText || "",
                }),
              });
              await reload();
            } catch (error) {
              const notice = element("p", "cv-review-ko", error.message);
              body.insertBefore(notice, body.firstChild);
            }
          })
        );
      } catch (error) {
        body.replaceChildren(element("p", "cv-review-ko", error.message));
      }
    };
    reload();
    return panel;
  }

  window.renderCvReviewSection = renderCvReviewSection;
})();
