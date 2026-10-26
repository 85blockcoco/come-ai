"use strict";

/*
 * CVBOOST-03 — « Plan précis pour ton CV » : filtres, priorités et navigation.
 *
 * Données 100 % locales (career/application_prep.py, schémas compatibles avec
 * les enrichissements futurs des lots cv_quality et offer_requirements :
 * modality, category, provenance). Aucun appel réseau, aucun consentement
 * cloud, aucune modification du CV source : seules les marques « revu » sont
 * conservées dans le stockage local du navigateur.
 *
 * Ce module ne touche pas au DOM au chargement : il expose des fonctions
 * appelées depuis career_static/career.js (accroche renderStagePrep) et des
 * helpers de préselection du Studio partagés avec career.js.
 */

const cvPlanFilters = [
  { key: "all", label: "Tous" },
  { key: "highlight", label: "À mettre en avant" },
  { key: "verify", label: "À vérifier" },
  { key: "blocking", label: "Bloquants" },
];

const cvPlanFilterLabels = {
  all: "Tous",
  highlight: "À mettre en avant",
  verify: "À vérifier",
  blocking: "Bloquants",
};

/* Ordre déterministe : blocage factuel, exigence obligatoire, amélioration,
   préférence. Rien n'est trié par une « pertinence » estimée. */
const cvPlanRankKeys = ["blocking", "required", "improvement", "preference"];

const cvPlanRankMeta = {
  blocking: { className: "cv-plan-rank-blocking", badge: "Blocage factuel" },
  required: { className: "cv-plan-rank-required", badge: "Exigence obligatoire" },
  improvement: { className: "cv-plan-rank-improvement", badge: "Amélioration" },
  preference: { className: "cv-plan-rank-preference", badge: "Préférence" },
};

const cvPlanFilterByRankKey = { blocking: "blocking", required: "highlight", improvement: "verify", preference: "verify" };

/* Rubriques et catégories (CVBOOST-02) converties en minuscules sans accents
   pour un ciblage stable : chaque cible reste un élément réel de l'interface
   locale — rubrique du profil, disponibilité (Réglages) ou villes du Stage
   Hunter. Aucune rubrique du CV source n'est modifiable par ces raccourcis. */
const cvPlanProfileTargets = {
  competences: { view: "profile", field: "profile-skills" },
  "competence technique": { view: "profile", field: "profile-skills" },
  "technical skill": { view: "profile", field: "profile-skills" },
  experiences: { view: "profile", field: "profile-experience" },
  "experience professionnelle": { view: "profile", field: "profile-experience" },
  experience: { view: "profile", field: "profile-experience" },
  formation: { view: "profile", field: "profile-education" },
  education: { view: "profile", field: "profile-education" },
  langues: { view: "profile", field: "profile-languages" },
  langue: { view: "profile", field: "profile-languages" },
  language: { view: "profile", field: "profile-languages" },
  "informations complementaires": { view: "profile", field: "profile-eligibility" },
  eligibility: { view: "profile", field: "profile-eligibility" },
  "autorisation de travail": { view: "profile", field: "profile-eligibility" },
  disponibilite: { view: "settings", field: "availability-start" },
  mobilite: { view: "stagehunter", field: "stagehunter-cities" },
};

function cvPlanNormalizeLabel(label) {
  return String(label || "")
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function cvPlanPriorityIndex(priority) {
  return priority === "high" ? 0 : priority === "medium" ? 1 : 2;
}

function cvPlanNeedsEvidence(item) {
  return item?.status === "needs_evidence" || item?.evidence_quality === "missing";
}

function cvPlanRankKey(item) {
  if (item?.blocking === true) return "blocking";
  if (item?.source === "cv_structure") return cvPlanNeedsEvidence(item) ? "blocking" : "improvement";
  const modality = cvPlanNormalizeLabel(item?.modality);
  if (modality === "preferred" || modality === "contextual") return "preference";
  if (cvPlanNeedsEvidence(item)) return "blocking";
  if (modality === "preferred") return "preference";
  if (item?.evidence_quality === "needs_quantification" || item?.evidence_quality === "unknown") return "improvement";
  return "required";
}

function cvPlanRank(item) {
  return cvPlanRankKeys.indexOf(cvPlanRankKey(item)) < 0 ? 1 : cvPlanRankKeys.indexOf(cvPlanRankKey(item));
}

function cvPlanItemFilterKey(item) {
  // Keep a missing or partial proof in the factual-blocker filter even when
  // the backend's source-level hint says "verify". Its rank and its filter
  // must agree: the person can still verify the fact, but cannot claim it in
  // the dossier until the evidence is complete.
  if (cvPlanRankKey(item) === "blocking") return "blocking";
  if (item && typeof item === "object" && cvPlanFilterLabels[item.filter]) return item.filter;
  return cvPlanFilterByRankKey[cvPlanRankKey(item)] || "highlight";
}

/* Écarte toute ambiguïté : rang, puis priorité backend, puis ordre d'arrivée. */
function cvPlanCompareEntries(entries) {
  entries.sort((left, right) => {
    if (left.rank !== right.rank) return left.rank - right.rank;
    if (left.priorityIndex !== right.priorityIndex) return left.priorityIndex - right.priorityIndex;
    return left.order - right.order;
  });
  return entries;
}

function cvPlanPrepareItems(prep) {
  const rawItems = Array.isArray(prep?.cv_action_plan) ? prep.cv_action_plan : [];
  return cvPlanCompareEntries(
    rawItems.map((item, order) => {
      const rankKey = cvPlanRankKey(item);
      return {
        item: item || {},
        rankKey,
        rank: cvPlanRankKeys.indexOf(rankKey),
        filterKey: cvPlanItemFilterKey(item),
        priorityIndex: cvPlanPriorityIndex(item?.priority),
        order,
      };
    }),
  );
}

function cvPlanCountByFilter(entries) {
  const counts = { all: entries.length, highlight: 0, verify: 0, blocking: 0 };
  entries.forEach((entry) => {
    if (counts[entry.filterKey] !== undefined) counts[entry.filterKey] += 1;
  });
  return counts;
}

/* ——— Stockage local tolérant (Safari privé, stockage désactivé) ——— */

function cvPlanStorable() {
  try {
    const probe = "cv-plan-probe";
    window.localStorage.setItem(probe, probe);
    window.localStorage.removeItem(probe);
    return true;
  } catch (error) {
    return false;
  }
}

function cvPlanReviewedStorageKey(jobKey) {
  return `career_cv_plan_reviewed_${jobKey}`;
}

function cvPlanLoadReviewed(jobKey) {
  if (!cvPlanStorable()) return new Set();
  try {
    const raw = window.localStorage.getItem(cvPlanReviewedStorageKey(jobKey));
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return new Set();
    return new Set(Object.keys(parsed).filter((key) => parsed[key] === true || parsed[key] === 1));
  } catch (error) {
    return new Set();
  }
}

function cvPlanSaveReviewed(jobKey, itemKey, reviewed) {
  if (!cvPlanStorable()) return;
  try {
    const raw = window.localStorage.getItem(cvPlanReviewedStorageKey(jobKey));
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
    if (reviewed) parsed[itemKey] = true;
    else delete parsed[itemKey];
    window.localStorage.setItem(cvPlanReviewedStorageKey(jobKey), JSON.stringify(parsed));
  } catch (error) {
    /* Stockage indisponible : la marque reste valable pour la session en cours. */
  }
}

function cvPlanJobKey(job) {
  return String(job?.id || job?.title || "offre").replace(/[^\w-]+/g, "_");
}

function cvPlanItemKey(item, fallbackIndex) {
  const identity = String(item?.id || "").trim();
  if (identity) return identity;
  const requirement = String(item?.requirement || "").trim().slice(0, 80);
  if (!requirement) return `item_${fallbackIndex}`;
  return `requirement_${cvPlanNormalizeLabel(requirement).replace(/[^\w]+/g, "_")}`;
}

function cvPlanProvenanceText(item) {
  const parts = [];
  const provenance = item?.provenance;
  if (provenance && typeof provenance === "object") {
    const field = provenance.field || provenance.source_field || "";
    const line = provenance.line == null ? provenance.line_number : provenance.line;
    if (field || line != null) {
      parts.push(`Provenance : champ « ${field || "offre"} »${line != null ? `, ligne ${line}` : ""}.`);
    }
    const quote = provenance.quote || provenance.excerpt;
    if (quote) parts.push(`Passage source : « ${String(quote).slice(0, 240)} ».`);
  }
  return parts.join(" ");
}

function cvPlanModalityLabel(item) {
  const modality = cvPlanNormalizeLabel(item?.modality);
  if (!modality) return "";
  if (modality === "required") return "obligatoire selon l’offre";
  if (modality === "preferred") return "préférée selon l’offre";
  if (modality === "contextual") return "précision contextuelle de l’offre";
  return "";
}

/* ——— Préselection du Studio partagée avec career.js ——— */

function cvPlanStudioLanguages() {
  return ["fr", "en", "it", "de"];
}

function saveStudioPrefill(job, language, mode) {
  const normalizedLanguage = cvPlanStudioLanguages().includes(language) ? language : "";
  if (!cvPlanStorable()) return;
  try {
    window.localStorage.setItem(
      "career_studio_prefill",
      JSON.stringify({
        job_id: job && job.id ? String(job.id) : "",
        language: normalizedLanguage,
        /* Le mode restauré reste toujours le gabarit local factuel. */
        mode: "local",
      }),
    );
  } catch (error) {
    /* Stockage indisponible : la préselection reste valable pour la session. */
  }
}

function loadStudioPrefill() {
  try {
    if (!cvPlanStorable()) return { job_id: "", language: "", mode: "" };
    const raw = window.localStorage.getItem("career_studio_prefill");
    if (!raw) return { job_id: "", language: "", mode: "" };
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return { job_id: "", language: "", mode: "" };
    return {
      job_id: typeof parsed.job_id === "string" ? parsed.job_id : "",
      language: cvPlanStudioLanguages().includes(parsed.language) ? parsed.language : "",
      /* Jamais de mode IA restauré : la préselection reste locale. */
      mode: parsed.mode === "local" ? "local" : "",
    };
  } catch (error) {
    return { job_id: "", language: "", mode: "" };
  }
}

/* ——— Rendu ——— */

function renderCvPlanSection(target, prep, job) {
  if (!target) return null;
  const entries = cvPlanPrepareItems(prep);
  const coverage = prep?.cv_coverage || {};
  const hasCoverage = Number.isFinite(coverage.requirements_total);
  if (!entries.length && !hasCoverage) return null;

  const jobKey = cvPlanJobKey(job);
  const reviewed = cvPlanLoadReviewed(jobKey);
  const section = make("section", "", "cv-plan");
  section.append(make("h4", "Plan précis pour ton CV"));

  section.append(
    make(
      "p",
      hasCoverage
        ? `Couverture documentaire : ${coverage.supported || 0}/${coverage.requirements_total || 0} exigences appuyées par des preuves suffisantes · ${coverage.coverage_percent || 0} % confirmées · ${coverage.to_verify || 0} à vérifier · ${coverage.unsupported || 0} écart(s) établi(s) · ${coverage.contradicted || 0} contradiction(s) · langue cible ${coverage.target_language || "à confirmer"}.`
        : "Analyse locale en cours : aucune exigence détectée n’est encore comptabilisée.",
      "scoring-title cv-plan-summary",
    ),
  );
  section.append(
    make(
      "p",
      "Ce n’est pas une probabilité d’embauche : c’est un contrôle des preuves actuellement présentes dans ton profil.",
      "scoring-disclaimer",
    ),
  );

  if (entries.length) {
    const help = make("details", "", "cv-plan-coverage-help");
    help.append(make("summary", "Que mesure la couverture documentaire ?"));
    const helpList = make("ul", "", "job-reasons");
    [
      "Le pourcentage compte les exigences dont une preuve approuvée a été jugée suffisante par la comparaison locale entre l’offre et ton profil. Un simple mot-clé commun ou une preuve partielle ne suffit pas à les déclarer couvertes.",
      "« À vérifier » signifie que les faits enregistrés ne suffisent pas à conclure. Un écart établi ou une contradiction reste visible et ne compte jamais comme une exigence satisfaite.",
      "Les marques « revu » restent dans ce navigateur uniquement ; ton CV source et ton profil ne sont jamais modifiés par ce plan.",
    ].forEach((text) => helpList.append(make("li", text)));
    help.append(helpList);
    section.append(help);

    const filtersGroup = make("div", "", "cv-plan-filters");
    filtersGroup.setAttribute("role", "group");
    filtersGroup.setAttribute("aria-label", "Filtres du plan CV");
    const counts = cvPlanCountByFilter(entries);
    const status = make("p", "", "cv-plan-live");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    const list = make("ol", "", "cv-plan-list");
    entries.forEach((entry) =>
      list.append(renderCvPlanItem(entry, job, coverage, reviewed, { jobKey, status })),
    );
    let activeFilter = "all";
    const empty = make("p", "", "cv-plan-empty scoring-disclaimer");
    empty.hidden = true;

    const filterButtons = cvPlanFilters.map(({ key, label }) => {
      const button = make("button", `${label} · ${counts[key] ?? 0}`, "cv-plan-filter");
      button.type = "button";
      button.dataset.filter = key;
      button.setAttribute("aria-pressed", key === activeFilter ? "true" : "false");
      button.addEventListener("click", () => {
        activeFilter = key;
        filterButtons.forEach((other) =>
          other.setAttribute("aria-pressed", other.dataset.filter === key ? "true" : "false"),
        );
        let visible = 0;
        entries.forEach((entry, index) => {
          const itemNode = list.children[index];
          const matches = key === "all" || entry.filterKey === key;
          itemNode.hidden = !matches;
          if (matches) visible += 1;
        });
        empty.hidden = visible > 0;
        empty.textContent =
          visible === 0 && entries.length
            ? `Aucun conseil dans « ${cvPlanFilterLabels[key]} » pour le moment.`
            : "";
        status.textContent = `Filtre « ${cvPlanFilterLabels[key]} » : ${visible} conseil${
          visible > 1 ? "s" : ""
        } affiché${visible > 1 ? "s" : ""} sur ${entries.length}.`;
      });
      filtersGroup.append(button);
      return button;
    });

    section.append(filtersGroup);
    section.append(status);
    list.setAttribute("aria-label", "Plan d’actions CV ordonné par priorité déterministe");
    list.addEventListener("keydown", (event) => cvPlanHandleListNavigation(event, list));
  section.append(list);
    section.append(empty);
    status.textContent = `Plan affiché avec le filtre « Tous » : ${entries.length} conseil${
      entries.length > 1 ? "s" : ""
    }.`;
  }

  return section;
}

function renderCvPlanItem(entry, job, coverage, reviewed, context) {
  const { item, rankKey, order } = entry;
  const meta = cvPlanRankMeta[rankKey];
  const itemKey = cvPlanItemKey(item, order);
  const isReviewed = reviewed.has(itemKey);

  const row = make("li", "", `cv-plan-item ${meta.className}${isReviewed ? " cv-plan-item-reviewed" : ""}`);
  row.dataset.itemKey = itemKey;
  row.dataset.rank = rankKey;

  const copy = make("article", "", "cv-plan-copy");
  const head = make("div", "", "cv-plan-head");
  head.append(make("span", meta.badge, "cv-plan-badge"));
  const modalityLabel = cvPlanModalityLabel(item);
  if (modalityLabel) head.append(make("span", modalityLabel, "cv-plan-modality"));
  if (isReviewed) head.append(make("span", "Revu localement", "cv-plan-reviewed-badge"));
  copy.append(head);
  copy.append(make("strong", `${item.action_label || "Action CV"} · ${item.section || "Section à déterminer"}`, "cv-plan-title"));

  const provenanceBits = [
    item.offer_reference,
    item.profile_reference ||
      (cvPlanNeedsEvidence(item) ? "Aucune preuve trouvée dans le profil local" : "profil à vérifier"),
  ]
    .filter(Boolean)
    .join(" · ");
  if (provenanceBits) copy.append(make("p", provenanceBits, "application-meta"));
  const provenanceText = cvPlanProvenanceText(item);
  if (provenanceText) copy.append(make("p", provenanceText, "application-meta cv-plan-provenance"));
  if (item.requirement) copy.append(make("p", `Exigence de l’offre : ${item.requirement}`));
  if (item.profile_evidence) {
    copy.append(make("p", `Preuve déjà présente : « ${item.profile_evidence} »`, "cv-plan-evidence"));
  }
  if ((item.missing_keywords || []).length) {
    copy.append(
      make("p", `Mots-clés non étayés à vérifier : ${item.missing_keywords.join(", ")}.`, "cv-plan-missing"),
    );
  }
  if (item.suggested_change) copy.append(make("p", `À faire : ${item.suggested_change}`));
  if (item.evidence_quality === "needs_quantification") {
    copy.append(
      make(
        "p",
        "Amélioration possible : ajoute un résultat chiffré uniquement si tu peux le prouver ; sinon conserve la formulation actuelle.",
        "scoring-disclaimer",
      ),
    );
  }
  if (rankKey === "blocking") {
    copy.append(
      make(
        "p",
        item.blocking_note ||
          (item.profile_evidence
            ? "Une preuve liée à cette exigence existe, mais elle ne la couvre pas entièrement. Présente uniquement les faits prouvés et ne la reformule pas comme une conformité."
            : "Blocage factuel : n’inscris pas cette exigence dans ton CV tant qu’aucune preuve vérifiable n’existe côté profil."),
        "scoring-disclaimer cv-plan-blocking-note",
      ),
    );
  }
  if (item.why) copy.append(make("p", item.why, "scoring-disclaimer"));
  row.append(copy);

  const actions = make("div", "", "cv-plan-actions");
  const studioButton = make(
    "button",
    rankKey === "blocking" ? "Compléter puis préparer" : "Préparer dans le Studio",
    "secondary-button cv-plan-action-studio",
  );
  studioButton.type = "button";
  studioButton.addEventListener("click", () => openStudioForJob(job, coverage?.target_language));
  actions.append(studioButton);

  if (rankKey !== "required") {
    const completeButton = make("button", "Compléter mon profil", "quiet-button cv-plan-action-profile");
    completeButton.type = "button";
    completeButton.addEventListener("click", () => openCvPlanProfileTarget(cvPlanProfileTarget(item)));
    actions.append(completeButton);
  }

  const reviewedButton = make(
    "button",
    isReviewed ? "Marquer comme non revu" : "Marquer comme revu",
    "quiet-button cv-plan-action-reviewed",
  );
  reviewedButton.type = "button";
  reviewedButton.setAttribute("aria-pressed", isReviewed ? "true" : "false");
  reviewedButton.addEventListener("click", () => {
    const nextReviewed = !cvPlanLoadReviewed(context.jobKey).has(itemKey);
    cvPlanSaveReviewed(context.jobKey, itemKey, nextReviewed);
    row.classList.toggle("cv-plan-item-reviewed", nextReviewed);
    const badge = row.querySelector(".cv-plan-reviewed-badge");
    if (nextReviewed) {
      if (!badge) row.querySelector(".cv-plan-head").append(make("span", "Revu localement", "cv-plan-reviewed-badge"));
      reviewedButton.textContent = "Marquer comme non revu";
      context.status.textContent =
        "Conseil marqué comme revu localement. Ton CV source et ton profil n’ont pas été modifiés.";
    } else {
      badge?.remove();
      reviewedButton.textContent = "Marquer comme revu";
      context.status.textContent = "Conseil de nouveau marqué à revoir.";
    }
    reviewedButton.setAttribute("aria-pressed", nextReviewed ? "true" : "false");
  });
  actions.append(reviewedButton);
  row.append(actions);
  return row;
}

function cvPlanProfileTarget(item) {
  return (
    cvPlanProfileTargets[cvPlanNormalizeLabel(item?.section)] ||
    cvPlanProfileTargets[cvPlanNormalizeLabel(item?.category)] || {
      view: "profile",
      field: "",
    }
  );
}

function openCvPlanProfileTarget(target) {
  if (typeof showView === "function") showView(target.view, { focus: false });
  window.setTimeout(() => {
    let field = null;
    if (target.field) field = document.getElementById(target.field);
    if (!field) field = $("#profile-form")?.querySelector("input, textarea") || null;
    if (!field) return;
    field.focus();
    if (typeof reveal === "function") reveal(field, "center");
  }, 0);
}

/* Navigation clavier dans la liste : flèches haut/bas entre les conseils,
   Home/End pour les extrémités. Les boutons restent normalement accessibles
   via Tab ; les flèches accélèrent le parcours d’une liste dense. */
function cvPlanHandleListNavigation(event, list) {
  const directions = { ArrowDown: 1, ArrowUp: -1 };
  if (!directions[event.key] && event.key !== "Home" && event.key !== "End") return;
  const rows = [...list.children].filter((row) => !row.hidden);
  if (!rows.length) return;
  const activeRow = event.target instanceof Element ? event.target.closest(".cv-plan-item") : null;
  const currentIndex = rows.indexOf(activeRow);
  let nextIndex;
  if (event.key === "Home") nextIndex = 0;
  else if (event.key === "End") nextIndex = rows.length - 1;
  else if (currentIndex === -1) nextIndex = 0;
  else nextIndex = currentIndex + directions[event.key];
  const targetRow = rows[(nextIndex + rows.length) % rows.length];
  event.preventDefault();
  targetRow?.querySelector(".cv-plan-actions button")?.focus();
}
