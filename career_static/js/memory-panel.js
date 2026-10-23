"use strict";

/*
 * Personal style memory panel (SPEC-023).
 *
 * The panel is intentionally additive: it mounts itself in the existing
 * “Réglages” view, uses only same-origin local endpoints, and never sends
 * profile data to a model or a remote service.
 */
(function memoryPanel() {
  const BASE = "/memory";
  const SOURCE_LABELS = {
    manual: "Réglage manuel",
    user_pick: "Choix explicite",
    auto_infer: "Déduit des choix",
  };

  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
      ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    let body = {};
    if (contentType.includes("application/json")) {
      try { body = await response.json(); } catch (_) { body = {}; }
    }
    if (!response.ok) {
      if (response.status === 409) {
        throw new Error("La mémoire de style est illisible : aucune préférence n’est appliquée et aucune génération ne doit être lancée. Réimporte un export valide.");
      }
      throw new Error(typeof body.detail === "string" ? body.detail : "L’action sur la mémoire locale n’a pas abouti.");
    }
    return body;
  }

  function formatDate(value) {
    if (!value) return "date inconnue";
    return String(value).replace("T", " ").replace("Z", " UTC");
  }

  function confidencePercent(value) {
    return `${Math.round(Number(value || 0) * 100)} %`;
  }

  function setStatus(node, text, error = false) {
    node.textContent = String(text || "");
    node.classList.toggle("error", Boolean(error));
    node.setAttribute("role", error ? "alert" : "status");
  }

  function mount() {
    const host = document.querySelector("#settings-content");
    if (!host || document.querySelector("#personal-memory-panel")) return;

    const section = el("section", "panel memory-style-panel");
    section.id = "personal-memory-panel";
    section.setAttribute("aria-labelledby", "personal-memory-title");

    const heading = el("div", "panel-heading");
    const headingText = el("div");
    headingText.append(
      el("p", "eyebrow", "Mémoire personnelle"),
      el("h2", "", "Préférences de style"),
    );
    headingText.querySelector("h2").id = "personal-memory-title";
    heading.append(headingText, el("span", "local-tag", "100 % local"));
    section.append(heading);
    section.append(el(
      "p",
      "panel-help",
      "Career retient les verbes, la tonicité, la longueur et le glossaire que tu choisis. Trois choix identiques rendent une préférence automatique. Chaque choix reste réversible et tout se passe dans un fichier local exportable.",
    ));

    const stats = el("div", "memory-stats");
    stats.setAttribute("aria-live", "polite");
    section.append(stats);

    const status = el("p", "memory-status");
    status.setAttribute("aria-live", "polite");
    section.append(status);

    const constraintsTitle = el("h3", "", "Contraintes injectées dans les reformulations");
    const constraints = el("ul", "memory-constraints");
    section.append(constraintsTitle, constraints);

    const preferencesTitle = el("h3", "", "Préférences enregistrées");
    const preferences = el("div", "memory-pref-list");
    const preferencesEmpty = el("p", "empty-state compact-empty", "Aucune préférence enregistrée pour l’instant.");
    section.append(preferencesTitle, preferences, preferencesEmpty);

    const glossaryTitle = el("h3", "", "Glossaire personnel");
    const glossary = el("div", "memory-glossary");
    const glossaryEmpty = el("p", "empty-state compact-empty", "Aucun terme de glossaire enregistré.");
    section.append(glossaryTitle, glossary, glossaryEmpty);

    const formTitle = el("h3", "", "Ajouter un réglage manuel");
    const form = el("form", "memory-form form-stack");
    const keyLabel = el("label", "", "Clé");
    const keyInput = el("input");
    keyInput.id = "memory-preference-key";
    keyInput.name = "key";
    keyInput.required = true;
    keyInput.maxLength = 80;
    keyInput.placeholder = "js-action-verb";
    keyLabel.append(keyInput);
    const valueLabel = el("label", "", "Valeur");
    const valueInput = el("input");
    valueInput.id = "memory-preference-value";
    valueInput.name = "value";
    valueInput.required = true;
    valueInput.maxLength = 300;
    valueInput.placeholder = "conçu";
    valueLabel.append(valueInput);
    const submit = el("button", "primary-button", "Enregistrer ce réglage");
    submit.type = "submit";
    const formRow = el("div", "form-row");
    formRow.append(keyLabel, valueLabel);
    form.append(formRow, submit);
    section.append(formTitle, form);

    const actions = el("div", "memory-actions");
    const exportButton = el("button", "secondary-button", "Exporter la mémoire (.json)");
    exportButton.type = "button";
    const importLabel = el("label", "secondary-button file-button", "Importer un export");
    const importInput = el("input");
    importInput.type = "file";
    importInput.accept = "application/json,.json";
    importInput.className = "visually-hidden";
    importLabel.append(importInput);
    actions.append(exportButton, importLabel);
    section.append(actions);

    const historyTitle = el("h3", "", "Historique des choix");
    const history = el("div", "memory-history");
    const historyEmpty = el("p", "empty-state compact-empty", "Aucun choix enregistré.");
    section.append(historyTitle, history, historyEmpty);

    host.prepend(section);

    function renderStats(payload) {
      const info = payload.stats || {};
      stats.replaceChildren(
        el("span", "memory-stat", `${info.preferences_count || 0} préférence(s)`),
        el("span", "memory-stat", `${info.auto_applied_count || 0} automatique(s)`),
        el("span", "memory-stat", `${info.glossary_count || 0} terme(s) de glossaire`),
        el("span", "memory-stat", `${info.choices_count || 0} choix · ${info.undone_choices_count || 0} annulé(s)`),
      );
    }

    function renderConstraints(items) {
      constraints.replaceChildren();
      if (!items.length) {
        constraints.append(el("li", "empty-state compact-empty", "Aucune contrainte : la mémoire n’influence pas les reformulations."));
        return;
      }
      items.forEach((item) => {
        const line = el("li");
        line.append(
          el("code", "", `${item.key} = ${item.value}`),
          el("span", item.auto_applied ? "memory-badge auto" : "memory-badge", item.auto_applied ? "appliquée automatiquement" : `confiance ${confidencePercent(item.confidence)}`),
        );
        constraints.append(line);
      });
    }

    function renderPreferences(items) {
      preferences.replaceChildren();
      preferencesEmpty.hidden = items.length > 0;
      items.forEach((item) => {
        const card = el("article", "memory-pref-card");
        const top = el("div", "memory-pref-top");
        top.append(el("strong", "", item.key));
        top.append(el("span", item.auto_applied ? "memory-badge auto" : "memory-badge", item.auto_applied ? "auto" : "proposée"));
        const value = el("p", "memory-pref-value", item.value);
        const bar = el("div", "memory-confidence-bar");
        const fill = el("span");
        fill.style.width = `${Math.max(0, Math.min(100, Math.round(Number(item.confidence || 0) * 100)))}%`;
        bar.append(fill);
        const meta = el(
          "p",
          "memory-pref-meta",
          `${SOURCE_LABELS[item.source] || item.source} · ${item.occurrences || 1} occurrence(s) · confiance ${confidencePercent(item.confidence)} · ${formatDate(item.updated_at)}`,
        );
        const remove = el("button", "quiet-button", "Retirer");
        remove.type = "button";
        remove.addEventListener("click", async () => {
          if (!window.confirm(`Retirer la préférence « ${item.key} » ? L’historique de la purge restera consultable dans l’export.`)) return;
          try {
            await request(`${BASE}/prefs/${encodeURIComponent(item.key)}`, { method: "DELETE" });
            setStatus(status, "Préférence retirée. La purge est tracée dans la mémoire.");
            await load();
          } catch (error) {
            setStatus(status, error.message, true);
          }
        });
        card.append(top, value, bar, meta, remove);
        preferences.append(card);
      });
    }

    function renderGlossary(items) {
      glossary.replaceChildren();
      glossaryEmpty.hidden = items.length > 0;
      items.forEach((item) => {
        const row = el("div", "memory-glossary-item");
        row.append(el("strong", "", item.term), el("span", "", ` — ${item.definition}`));
        glossary.append(row);
      });
    }

    function renderHistory(items) {
      history.replaceChildren();
      historyEmpty.hidden = items.length > 0;
      items.forEach((item) => {
        const card = el("article", `memory-history-item${item.undone ? " undone" : ""}`);
        const summary = Object.entries(item.chosen || {})
          .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
          .slice(0, 3)
          .map(([key, value]) => `${key}: ${value}`)
          .join(" · ");
        card.append(
          el("p", "memory-history-context", `${formatDate(item.created_at)} — ${item.context}`),
          el("p", "memory-history-choice", summary || "Option enregistrée"),
          el("p", "memory-pref-meta", `${(item.evidence_refs || []).length} preuve(s) · ${item.undone ? "annulé" : "actif"}`),
        );
        if (!item.undone) {
          const undo = el("button", "quiet-button", "Annuler ce choix");
          undo.type = "button";
          undo.addEventListener("click", async () => {
            try {
              await request(`${BASE}/back/${encodeURIComponent(item.id)}/undo`, { method: "POST" });
              setStatus(status, "Choix annulé : la préférence correspondante a été recalculée.");
              await load();
            } catch (error) {
              setStatus(status, error.message, true);
            }
          });
          card.append(undo);
        }
        history.append(card);
      });
    }

    async function load() {
      setStatus(status, "Chargement de la mémoire locale…");
      try {
        const [prefs, back, report] = await Promise.all([
          request(`${BASE}/prefs`),
          request(`${BASE}/back?limit=20`),
          request(`${BASE}/report`),
        ]);
        renderStats(prefs);
        renderConstraints(prefs.top_constraints || []);
        renderPreferences(prefs.preferences || []);
        renderGlossary(report.glossary || []);
        renderHistory(back.choices || []);
        setStatus(status, "Mémoire locale chargée. Aucune donnée n’a quitté ce Mac.");
      } catch (error) {
        renderStats({ stats: {} });
        renderConstraints([]);
        renderPreferences([]);
        renderGlossary([]);
        renderHistory([]);
        setStatus(status, error.message, true);
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await request(`${BASE}/prefs`, {
          method: "POST",
          body: JSON.stringify({ key: keyInput.value, value: valueInput.value, source: "manual" }),
        });
        form.reset();
        setStatus(status, "Réglage manuel enregistré avec une confiance élevée.");
        await load();
      } catch (error) {
        setStatus(status, error.message, true);
      }
    });

    exportButton.addEventListener("click", async () => {
      try {
        const response = await fetch(`${BASE}/export`, { method: "POST" });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(typeof body.detail === "string" ? body.detail : "L’export de la mémoire a échoué.");
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "memoire-style.json";
        document.body.append(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        setStatus(status, "Export JSON généré localement.");
      } catch (error) {
        setStatus(status, error.message, true);
      }
    });

    importInput.addEventListener("change", async () => {
      const file = importInput.files && importInput.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        let payload;
        try {
          payload = JSON.parse(text);
        } catch (_) {
          throw new Error("Ce fichier n’est pas un JSON valide.");
        }
        const result = await request(`${BASE}/import`, { method: "POST", body: JSON.stringify(payload) });
        setStatus(status, `Import terminé : ${result.imported || 0} événement(s) ajouté(s), ${result.skipped || 0} déjà présent(s).`);
        await load();
      } catch (error) {
        setStatus(status, error.message, true);
      } finally {
        importInput.value = "";
      }
    });

    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
