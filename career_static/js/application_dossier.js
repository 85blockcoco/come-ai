/* SK-11 — dossier de candidature « 1 clic » et vérifiable.
 *
 * L'interface ne fait qu'orchestrer le dossier local : elle appelle l'API
 * Career, affiche le verdict du vérificateur (supported / unsupported /
 * to_verify) et n'exporte jamais rien à la place de la personne.
 *
 * Aucun envoi automatique, aucun appel réseau vers un tiers : seules les
 * routes locales /api/career/... sont utilisées.
 */

const DOSSIER_ARTIFACT_LABELS = {
  cv_recommendations: "Recommandations CV",
  adapted_cv: "CV adapté",
  cover_letter: "Lettre de motivation",
  prep_sheet: "Fiche de préparation",
  interview_questions: "Questions d'entretien",
  checklist: "Checklist avant envoi",
};

const DOSSIER_VERDICT_LABELS = {
  supported: "prouvé",
  unsupported: "non prouvé",
  to_verify: "à vérifier",
};

function dossierSection(title, className) {
  const section = make("section", "", className || "application-dossier-section");
  section.append(make("h5", title, "kit-subheading"));
  return section;
}

function dossierVerificationBlock(dossier) {
  const verification = dossier.verification || {};
  const block = dossierSection("Vérificateur : chaque affirmation est contrôlée", "application-dossier-verification");
  const summary = make("p", "", "application-meta");
  summary.textContent = `${verification.supported_count || 0} prouvée(s) · ${verification.unsupported_count || 0} non prouvée(s) · ${verification.to_verify_count || 0} à vérifier.`;
  block.append(summary);
  if (!dossier.export_allowed) {
    const blocked = make("p", "Export final bloqué : corrige ou prouve les affirmations non prouvées avant d’exporter.", "application-dossier-blocked");
    block.append(blocked);
  }
  const claims = verification.claims || [];
  if (claims.length) {
    const list = make("ul", "", "job-reasons");
    claims.forEach((claim) => {
      const label = DOSSIER_VERDICT_LABELS[claim.verdict] || claim.verdict;
      const item = make("li", "", `dossier-claim dossier-claim-${claim.verdict}`);
      item.append(make("strong", `${label} — `));
      item.append(make("span", claim.text));
      if (claim.fact_id) item.append(make("code", ` ${claim.fact_id}`, "application-meta"));
      list.append(item);
    });
    block.append(list);
  }
  return block;
}

function dossierRecommendationsBlock(dossier) {
  const recommendations = dossier.recommendations || [];
  const block = dossierSection("Recommandations CV", "application-dossier-recommendations");
  if (!recommendations.length) {
    block.append(make("p", "Aucune exigence extraite de cette offre.", "application-meta"));
    return block;
  }
  const list = make("ul", "", "job-reasons");
  recommendations.forEach((item) => {
    const row = make("li");
    row.append(make("strong", `${item.code} — `));
    row.append(make("span", item.requirement));
    if (item.quote) row.append(make("code", ` « ${item.quote} »`, "application-meta"));
    list.append(row);
  });
  block.append(list);
  return block;
}

function dossierDiffBlock(dossier) {
  const diff = dossier.diff || [];
  const block = dossierSection("Comparaison avant / après", "application-dossier-diff");
  if (!diff.length) {
    block.append(make("p", "Aucun CV de départ à comparer.", "application-meta"));
    return block;
  }
  const list = make("ul", "", "job-reasons");
  diff.forEach((item) => {
    const row = make("li");
    row.append(make("strong", `${item.kind} — `));
    row.append(make("span", item.text));
    list.append(row);
  });
  block.append(list);
  return block;
}

function dossierArtifactsBlock(dossier) {
  const block = dossierSection("Livrables du dossier", "application-dossier-artifacts");
  (dossier.artifacts || []).forEach((artifact) => {
    const details = make("details", "", "application-dossier-artifact");
    const summary = make("summary", DOSSIER_ARTIFACT_LABELS[artifact.key] || artifact.key);
    details.append(summary);
    details.append(make("pre", artifact.body, "application-dossier-body"));
    block.append(details);
  });
  return block;
}

function renderApplicationDossier(dossier, container) {
  if (!container) return;
  container.replaceChildren();
  container.hidden = false;
  const header = make("h4", "Dossier de candidature vérifiable", "kit-heading");
  container.append(header);
  const meta = make("p", "", "application-meta");
  const source = dossier.language_source === "user" ? "langue forcée par toi" : "langue annoncée par l’offre";
  meta.textContent = `Version ${dossier.version || 1} · ${(dossier.language || "fr").toUpperCase()} (${source}) · aucun envoi automatique.`;
  container.append(meta);
  container.append(dossierVerificationBlock(dossier));
  container.append(dossierRecommendationsBlock(dossier));
  container.append(dossierDiffBlock(dossier));
  container.append(dossierArtifactsBlock(dossier));

  const exportButton = make("button", "Exporter le dossier (fichiers locaux)", "secondary-button");
  exportButton.type = "button";
  exportButton.addEventListener("click", async () => {
    exportButton.disabled = true;
    try {
      const result = await api(
        `/api/career/applications/${encodeURIComponent(dossier.application_id)}/dossier/export`,
        { method: "POST" },
      );
      const files = Object.values(result.files || {}).join(" · ");
      setMessage(`Dossier exporté localement : ${files}. L’envoi reste manuel.`);
    } catch (error) {
      setMessage(error.message, true);
    } finally {
      exportButton.disabled = false;
    }
  });
  container.append(exportButton);
}

async function openApplicationDossier(application, container) {
  if (!container) return;
  container.textContent = "Génération du dossier vérifiable…";
  container.hidden = false;
  try {
    const dossier = await api(
      `/api/career/applications/${encodeURIComponent(application.id)}/dossier`,
      { method: "POST", body: JSON.stringify({ language: "" }) },
    );
    renderApplicationDossier(dossier, container);
  } catch (error) {
    container.hidden = true;
    setMessage(error.message, true);
  }
}
