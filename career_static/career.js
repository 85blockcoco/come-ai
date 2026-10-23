"use strict";

const state = {
  preferences: null,
  jobs: [],
  applications: [],
  applicationDashboard: null,
  profileImports: [],
  activeProfileImport: null,
  intake: null,
  applicationDrafts: [],
  activeApplicationDraft: null,
  studioJobs: [],
  pendingStudioJob: null,
  pendingStudioLanguage: "",
  discoverySources: [],
  stageMatches: [],
  stageDetailIndex: 0,
  coachSessions: [],
  activeCoachSession: null,
  pendingKitApplicationId: "",
};
const $ = (selector) => document.querySelector(selector);
const elements = {
  main: $("#career-main"),
  health: $("#career-health"),
  loading: $("#career-loading"),
  message: $("#career-message"),
  metrics: $("#dashboard-metrics"),
  dashboardContent: $("#dashboard-content"),
  todayProfileReadiness: $("#today-profile-readiness"),
  dashboardActionPlanPanel: $("#dashboard-action-plan-panel"),
  dashboardActionPlan: $("#dashboard-action-plan"),
  dashboardActionPlanEmpty: $("#dashboard-action-plan-empty"),
  dashboardActionPlanLoading: $("#dashboard-action-plan-loading"),
  dashboardActionPlanError: $("#dashboard-action-plan-error"),
  dashboardActionPlanStatus: $("#dashboard-action-plan-status"),
  dashboardRecommendations: $("#dashboard-recommendations"),
  dashboardRecommendationsEmpty: $("#dashboard-recommendations-empty"),
  dashboardDeadlines: $("#dashboard-deadlines"),
  dashboardDeadlinesEmpty: $("#dashboard-deadlines-empty"),
  profileForm: $("#profile-form"),
  profileDocumentForm: $("#profile-document-form"),
  profileTextForm: $("#profile-text-form"),
  profileImportReview: $("#profile-import-review"),
  profileImportReviewTitle: $("#profile-import-review-title"),
  profileImportReviewHelp: $("#profile-import-review-help"),
  profileImportWarnings: $("#profile-import-warnings"),
  profileImportApplyForm: $("#profile-import-apply-form"),
  profileImportPreview: $("#profile-import-preview"),
  profileImportHistory: $("#profile-import-history-list"),
  profileImportHistoryEmpty: $("#profile-import-history-empty"),
  intakeChat: $("#career-intake-chat"),
  intakeForm: $("#career-intake-form"),
  intakeAnswer: $("#career-intake-answer"),
  intakeSubmit: $("#career-intake-submit"),
  preferencesForm: $("#preferences-form"),
  jobForm: $("#job-form"),
  discoverySourceForm: $("#discovery-source-form"),
  discoverySourceSubmit: $("#discovery-source-submit"),
  discoverySources: $("#discovery-sources"),
  discoverySourcesEmpty: $("#discovery-sources-empty"),
  discoverySearch: $("#discovery-search"),
  discoveryForceSearch: $("#discovery-force-search"),
  jobFamily: $("#job-family"),
  jobs: $("#jobs-list"),
  jobsEmpty: $("#jobs-empty"),
  shortlist: $("#shortlist-list"),
  shortlistEmpty: $("#shortlist-empty"),
  applications: $("#applications-list"),
  applicationsEmpty: $("#applications-empty"),
  applicationsCounters: $("#applications-counters"),
  applicationsRadar: $("#applications-radar"),
  applicationsHonesty: $("#applications-honesty"),
  applicationsFilterStage: $("#applications-filter-stage"),
  applicationsFilterReceipt: $("#applications-filter-receipt"),
  applicationsFilterDeadline: $("#applications-filter-deadline"),
  applicationsFilterAction: $("#applications-filter-action"),
  familyPreferences: $("#family-preferences"),
  locationPreferences: $("#location-preferences"),
  filters: $("#job-filters"),
  applicationDraftForm: $("#application-draft-form"),
  applicationDraftJob: $("#application-draft-job"),
  applicationDraftLanguage: $("#application-draft-language"),
  applicationDraftMode: $("#application-draft-mode"),
  applicationDraftConsentRow: $("#application-draft-consent-row"),
  applicationDraftConsent: $("#application-draft-consent"),
  applicationDraftSubmit: $("#application-draft-submit"),
  applicationDraftPreview: $("#application-draft-preview"),
  applicationDraftPreviewTitle: $("#application-draft-preview-title"),
  applicationDraftMeta: $("#application-draft-meta"),
  applicationDraftChecks: $("#application-draft-checks"),
  applicationDraftCv: $("#application-draft-cv"),
  applicationDraftLetter: $("#application-draft-letter"),
  applicationDraftCvDownloads: $("#application-draft-cv-downloads"),
  applicationDraftLetterDownloads: $("#application-draft-letter-downloads"),
  applicationDraftHistory: $("#application-draft-history"),
  applicationDraftHistoryEmpty: $("#application-draft-history-empty"),
  coachSessionForm: $("#coach-session-form"),
  coachMode: $("#coach-mode"),
  coachDifficulty: $("#coach-difficulty"),
  coachLanguage: $("#coach-language"),
  coachJob: $("#coach-job"),
  coachSession: $("#coach-session"),
  coachSessionTitle: $("#coach-session-title"),
  coachProgress: $("#coach-progress"),
  coachProgressDetail: $("#coach-progress-detail"),
  coachQuestionTopic: $("#coach-question-topic"),
  coachQuestionPrompt: $("#coach-question-prompt"),
  coachAnswerForm: $("#coach-answer-form"),
  coachAnswer: $("#coach-answer"),
  coachAnswerSubmit: $("#coach-answer-submit"),
  coachFeedback: $("#coach-feedback"),
  coachHistory: $("#coach-history"),
  coachHistoryEmpty: $("#coach-history-empty"),
};

const stageLabels = {
  to_review: "À examiner",
  to_prepare: "À préparer",
  ready_to_apply: "Prête",
  approved_for_manual_submission: "Approuvée pour dépôt manuel",
  deferred: "Reportée",
  rejected: "Rejetée par moi",
  refused: "Refusée",
  withdrawn: "Retirée",
  receipt_unknown: "Réception inconnue",
  submitted: "Envoyée",
  submitted_confirmed: "Réception confirmée",
  response_received: "Réponse reçue",
  interview: "Entretien",
  offer_received: "Offre reçue",
};
const editableStages = [
  "to_review",
  "to_prepare",
  "ready_to_apply",
  "deferred",
  "rejected",
  "refused",
  "withdrawn",
  "receipt_unknown",
  "submitted",
  "response_received",
  "interview",
  "offer_received",
];
const stagesAfterConfirmedReceipt = ["response_received", "interview", "offer_received", "rejected", "refused", "withdrawn"];
const calendarClasses = {
  compatible: "good",
  partial: "warning",
  potentially_incompatible: "warning",
  incompatible: "danger",
  to_verify: "warning",
};
const calendarLabels = {
  compatible: "Compatible",
  partial: "Partiellement compatible",
  potentially_incompatible: "Potentiellement incompatible",
  incompatible: "Incompatible",
  to_verify: "À vérifier",
};

async function api(url, options = {}) {
  const formData = options.body instanceof FormData;
  const response = await fetch(url, {
    headers: options.body && !formData ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  let body = {};
  if (contentType.includes("application/json")) {
    try { body = await response.json(); } catch (_) { body = {}; }
  }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "L’action Career n’a pas abouti.";
    const suffix = body.error_id ? ` (référence ${body.error_id})` : "";
    throw new Error(detail + suffix);
  }
  return body;
}

function setMessage(value = "", error = false) {
  elements.message.textContent = String(value || "");
  elements.message.classList.toggle("error", error);
  elements.message.setAttribute("role", error ? "alert" : "status");
}

function setLoading(loading, label = "Chargement de ton espace Career local…") {
  elements.main?.setAttribute("aria-busy", String(loading));
  if (!elements.loading) return;
  elements.loading.hidden = !loading;
  if (loading) elements.loading.textContent = label;
}

function reducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function reveal(element, block = "nearest") {
  element?.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block });
}

function labelForView(viewName) {
  return {
    dashboard: "Tableau de bord",
    discover: "Découvrir",
    stagehunter: "Stage Hunter",
    shortlist: "Ma shortlist",
    studio: "Application Studio",
    applications: "Candidatures",
    interviews: "Coach d’entretien",
    profile: "Mon profil",
    settings: "Réglages",
  }[viewName] || "Career";
}

function make(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function formObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function metric(value, label) {
  const node = make("article", "", "metric");
  node.append(make("strong", String(value)), make("span", label));
  return node;
}

function organiseViews() {
  const profilePanel = document.querySelector(".profile-panel");
  const profileContent = $("#profile-content");
  const settingsContent = $("#settings-content");
  if (profilePanel && profileContent && profilePanel.parentElement !== profileContent) {
    profileContent.append(profilePanel);
  }
  if (profilePanel && settingsContent) {
    [profilePanel.querySelector(".preferences-details"), profilePanel.querySelector(".privacy-details")]
      .filter(Boolean)
      .forEach((section) => settingsContent.append(section));
  }
  if (elements.metrics && elements.dashboardContent && elements.metrics.parentElement !== elements.dashboardContent) {
    elements.dashboardContent.append(elements.metrics);
  }
}

const careerViews = new Set(["dashboard", "discover", "stagehunter", "shortlist", "studio", "applications", "interviews", "profile", "settings"]);
let internalHashChange = false;

function refreshView(viewName) {
  const loaders = {
    dashboard: loadDashboard,
    stagehunter: loadStageHunter,
    shortlist: loadShortlist,
    studio: loadStudio,
    applications: loadApplications,
    interviews: loadCoach,
  };
  loaders[viewName]?.().catch((error) => setMessage(error.message, true));
}

function showView(viewName, { focus = true, updateHash = true } = {}) {
  const selectedView = document.querySelector(`#view-${viewName}`);
  if (!selectedView) return;
  if (viewName !== "applications") {
    // Quitter l'onglet Candidatures referme le kit automatiquement ouvert.
    state.pendingKitApplicationId = "";
  }
  document.querySelectorAll(".career-tab").forEach((tab) => {
    const active = tab.dataset.view === viewName;
    tab.classList.toggle("active", active);
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  document.querySelectorAll(".career-view").forEach((view) => {
    view.hidden = view.id !== `view-${viewName}`;
  });
  refreshView(viewName);
  if (viewName === "profile") {
    window.careerProfileBuilder?.refresh?.();
  }
  document.title = `${labelForView(viewName)} — Côme AI Career`;
  if (updateHash && window.location.hash !== `#career/${viewName}`) {
    internalHashChange = true;
    window.location.hash = `career/${viewName}`;
  }
  if (focus) {
    const heading = selectedView.querySelector("h2");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
    reveal(selectedView, "start");
  }
}

function renderFamilyOptions() {
  const families = state.preferences?.families || [];
  elements.jobFamily.replaceChildren();
  elements.jobFamily.append(new Option("À préciser", "À préciser"));
  families.forEach((family) => elements.jobFamily.append(new Option(family.label, family.label)));
  const filter = $("#filter-family");
  filter.replaceChildren(new Option("Tous les métiers", ""));
  families.forEach((family) => filter.append(new Option(family.label, family.label)));
}

function renderPreferenceRows(container, items) {
  container.replaceChildren();
  items.forEach((item) => {
    const row = make("div", "", "preference-row");
    row.dataset.key = item.key;
    row.dataset.label = item.label;
    row.dataset.scope = item.scope;
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = Boolean(item.enabled);
    enabled.className = "pref-enabled";
    const label = make("span", item.label);
    label.title = item.label;
    const priorityLabel = make("label", "Priorité");
    const priority = document.createElement("input");
    priority.type = "number";
    priority.min = "0";
    priority.max = "1000";
    priority.value = String(item.priority);
    priority.className = "pref-priority";
    priorityLabel.append(priority);
    row.append(enabled, label, priorityLabel);
    container.append(row);
  });
}

function preferencePayload(container) {
  return [...container.querySelectorAll(".preference-row")].map((row) => ({
    key: row.dataset.key,
    label: row.dataset.label,
    scope: row.dataset.scope,
    enabled: row.querySelector(".pref-enabled").checked,
    priority: Number(row.querySelector(".pref-priority").value || 0),
  }));
}

async function loadHealth() {
  try {
    const health = await api("/api/career/health");
    elements.health.className = "status-badge ready";
    const ocr = health.ocr?.available ? "OCR macOS prêt" : "OCR à préparer";
    const discovery = health.discovery?.enabled ? "boards officiels sur demande" : "recherche manuelle";
    elements.health.textContent = `${health.module} · ${ocr} · ${discovery} · aucune candidature envoyée`;
  } catch (error) {
    elements.health.className = "status-badge warn";
    elements.health.textContent = "Le module Career local est indisponible.";
  }
}

async function loadProfile() {
  const profile = await api("/api/career/profile");
  $("#profile-display-name").value = profile.display_name || "";
  $("#profile-contact-email").value = profile.contact_email || "";
  $("#profile-contact-phone").value = profile.contact_phone || "";
  $("#profile-linkedin-url").value = profile.linkedin_url || "";
  $("#profile-education").value = profile.education || "";
  $("#profile-experience").value = profile.experience || "";
  $("#profile-skills").value = profile.skills || "";
  $("#profile-languages").value = profile.languages || "";
  $("#profile-eligibility").value = profile.eligibility || "unknown";
  $("#profile-companies").value = profile.target_companies || "";
  $("#profile-notes").value = profile.notes || "";
  renderProfileReadiness(profile.readiness || {});
}

function renderProfileReadiness(readiness) {
  const title = $("#profile-readiness-title");
  const score = $("#profile-readiness-score");
  const next = $("#profile-readiness-next");
  if (!title || !score || !next) return;
  const value = Number.isFinite(readiness.score_out_of_20) ? readiness.score_out_of_20 : 0;
  title.textContent = readiness.label || "Profil à compléter";
  score.textContent = `Profil prêt à ${value}/20 · ${readiness.disclaimer || "Note locale de complétude, pas une probabilité d’embauche."}`;
  next.replaceChildren();
  (readiness.next_actions || []).forEach((action) => next.append(make("li", action)));
}

const profileImportFieldLabels = {
  display_name: "Nom d’affichage",
  contact_email: "E-mail de contact",
  contact_phone: "Téléphone",
  linkedin_url: "Profil LinkedIn public",
  education: "Formation",
  experience: "Expériences factuelles",
  skills: "Compétences factuelles",
  languages: "Langues déclarées",
};
const profileImportAppendableFields = new Set(["education", "experience", "skills", "languages"]);
const profileImportLongFields = new Set(["education", "experience", "skills", "languages"]);
const profileImportSourceLabels = {
  cv: "CV personnel",
  linkedin_export: "Export LinkedIn fourni par toi",
  linkedin_text: "Texte de profil collé par toi",
  profile_document: "Autre document de profil",
};

function profileImportSourceLabel(kind) {
  return profileImportSourceLabels[kind] || "Document de profil local";
}

function createProfileImportField(field, value, evidence = []) {
  const row = make("div", "", "profile-import-field");
  row.dataset.field = field;
  const selected = document.createElement("input");
  selected.type = "checkbox";
  selected.checked = true;
  selected.id = `profile-import-select-${field}`;
  selected.className = "profile-import-select";
  const content = make("div", "", "profile-import-field-content");
  const title = document.createElement("label");
  title.className = "profile-import-field-title";
  title.htmlFor = selected.id;
  title.textContent = profileImportFieldLabels[field] || field;
  content.append(title);
  if (Array.isArray(evidence) && evidence.length) {
    content.append(make("p", `Trouvé localement : ${evidence[0]}`, "profile-import-field-meta"));
  }
  const controls = make("div", "", "profile-import-field-controls");
  const mode = document.createElement("select");
  mode.className = "profile-import-mode";
  mode.append(new Option("Remplacer ce champ", "replace"));
  if (profileImportAppendableFields.has(field)) mode.append(new Option("Ajouter au champ", "append"));
  const input = profileImportLongFields.has(field) ? document.createElement("textarea") : document.createElement("input");
  input.className = "profile-import-value";
  input.value = value;
  input.maxLength = field === "experience" ? 6000 : field === "education" ? 1000 : field === "skills" ? 4000 : field === "languages" ? 2000 : field === "linkedin_url" ? 2000 : field === "contact_email" ? 320 : field === "contact_phone" ? 80 : 160;
  if (input.tagName === "TEXTAREA") input.rows = 3;
  if (field === "contact_email") input.type = "email";
  if (field === "contact_phone") input.type = "tel";
  if (field === "linkedin_url") input.type = "url";
  controls.append(mode, input);
  content.append(controls);
  row.append(selected, content);
  return row;
}

function renderProfileImportDraft(profileImport) {
  state.activeProfileImport = profileImport;
  elements.profileImportReview.hidden = false;
  elements.profileImportReviewTitle.textContent = profileImport.original_name || "Document importé";
  const fields = profileImport.suggested_fields || [];
  const extraction = profileImport.extraction_method === "macos_vision"
    ? ` OCR macOS Vision effectué${profileImport.ocr_pages ? ` sur ${profileImport.ocr_pages} page${profileImport.ocr_pages > 1 ? "s" : ""}` : ""}.`
    : "";
  elements.profileImportReviewHelp.textContent = fields.length
    ? `${fields.length} proposition${fields.length > 1 ? "s" : ""} trouvée${fields.length > 1 ? "s" : ""} dans ${profileImportSourceLabel(profileImport.source_kind).toLowerCase()}.${extraction} Rien n’est enregistré tant que tu ne cliques pas sur le bouton ci-dessous.`
    : "Aucune rubrique certaine n’a été trouvée. Tu peux fermer ce brouillon et compléter ton profil manuellement.";
  elements.profileImportWarnings.replaceChildren();
  [...new Set([...(profileImport.ocr_warnings || []), ...(profileImport.suggestions?.warnings || [])])].forEach((warning) => {
    elements.profileImportWarnings.append(make("p", warning, "profile-import-warning"));
  });
  const cvQuality = profileImport.cv_quality;
  if (cvQuality) {
    const quality = make("section", "", "profile-import-quality");
    quality.append(make("h4", "Diagnostic CV local"));
    const summary = cvQuality.risk_count
      ? `${cvQuality.risk_count} risque${cvQuality.risk_count > 1 ? "s" : ""} structurel${cvQuality.risk_count > 1 ? "s" : ""} prioritaire${cvQuality.risk_count > 1 ? "s" : ""}.`
      : "Aucun risque structurel détecté automatiquement — une relecture humaine reste nécessaire.";
    quality.append(make("p", summary, "profile-import-field-meta"));
    if ((cvQuality.actions || []).length) {
      const actions = make("ol", "", "profile-import-quality-actions");
      cvQuality.actions.forEach((action) => actions.append(make("li", action.message)));
      quality.append(actions);
    }
    quality.append(make("p", cvQuality.disclaimer || "", "profile-import-field-meta"));
    elements.profileImportWarnings.append(quality);
  }
  elements.profileImportApplyForm.replaceChildren();
  const values = profileImport.suggestions?.values || {};
  const evidence = profileImport.suggestions?.evidence || {};
  Object.keys(profileImportFieldLabels).forEach((field) => {
    if (!values[field]) return;
    const row = createProfileImportField(field, values[field], evidence[field]);
    if (profileImport.status !== "pending") {
      row.querySelectorAll("input, textarea, select").forEach((control) => { control.disabled = true; });
    }
    elements.profileImportApplyForm.append(row);
  });
  if (profileImport.status === "pending" && fields.length) {
    const actions = make("div", "", "profile-import-actions");
    const apply = make("button", "Appliquer les champs cochés", "primary-button");
    apply.type = "submit";
    const note = make("span", "Les champs décochés ne sont pas modifiés.", "profile-import-field-meta");
    actions.append(apply, note);
    elements.profileImportApplyForm.append(actions);
  }
  elements.profileImportPreview.textContent = profileImport.preview || "Aucun extrait disponible.";
  elements.profileImportApplyForm.onsubmit = applyActiveProfileImport;
  reveal(elements.profileImportReview);
}

async function loadProfileImports() {
  const payload = await api("/api/career/profile-imports");
  state.profileImports = payload.profile_imports || [];
  elements.profileImportHistory.replaceChildren();
  elements.profileImportHistoryEmpty.hidden = state.profileImports.length > 0;
  state.profileImports.forEach((profileImport) => {
    const item = make("article", "", "profile-import-history-item");
    const copy = make("div", "", "profile-import-history-copy");
    copy.append(make("p", profileImport.original_name || "Texte de profil", "profile-import-history-name"));
    const fields = profileImport.suggested_fields?.length || 0;
    const extraction = profileImport.extraction_method === "macos_vision"
      ? ` · OCR macOS${profileImport.ocr_pages ? ` (${profileImport.ocr_pages} p.)` : ""}`
      : "";
    copy.append(make("p", `${profileImportSourceLabel(profileImport.source_kind)} · ${profileImport.status === "applied" ? "appliqué" : "à vérifier"} · ${fields} proposition${fields > 1 ? "s" : ""}${profileImport.has_local_file ? " · fichier local" : ""}${extraction}`, "profile-import-history-meta"));
    const actions = make("div", "", "profile-import-history-actions");
    const review = make("button", profileImport.status === "applied" ? "Voir" : "Relire", "quiet-button");
    review.type = "button";
    review.addEventListener("click", () => openProfileImport(profileImport.id));
    const remove = make("button", "Supprimer", "danger-button");
    remove.type = "button";
    remove.addEventListener("click", () => deleteProfileImport(profileImport));
    actions.append(review, remove);
    item.append(copy, actions);
    elements.profileImportHistory.append(item);
  });
}

function intakeMessage(text, tone, helpText = "") {
  const bubble = make("div", "", `intake-message ${tone}`);
  bubble.append(make("div", text));
  if (helpText) bubble.append(make("div", helpText, "intake-message-help"));
  return bubble;
}

function renderIntake(intake) {
  state.intake = intake;
  elements.intakeChat.replaceChildren();
  (intake.transcript || []).forEach((turn) => {
    elements.intakeChat.append(intakeMessage(turn.question, "question", turn.help_text || ""));
    if (turn.answer) elements.intakeChat.append(intakeMessage(turn.answer, "answer"));
  });
  if (intake.completed) {
    elements.intakeChat.append(intakeMessage("Entretien terminé. Tes réponses sont conservées localement et pourront cibler tes brouillons.", "question"));
  }
  const question = intake.current_question;
  elements.intakeAnswer.disabled = !question;
  elements.intakeSubmit.disabled = !question;
  elements.intakeAnswer.placeholder = question ? "Ta réponse…" : "Entretien terminé — recommence pour modifier tes réponses.";
  elements.intakeSubmit.textContent = question ? `Répondre (${Math.min((intake.step_index || 0) + 1, intake.total_steps || 6)}/${intake.total_steps || 6})` : "Terminé";
  if (!question) elements.intakeAnswer.value = "";
}

async function loadIntake() {
  renderIntake(await api("/api/career/intake"));
}

async function openProfileImport(importId) {
  try {
    renderProfileImportDraft(await api(`/api/career/profile-imports/${encodeURIComponent(importId)}`));
  } catch (error) { setMessage(error.message, true); }
}

async function applyActiveProfileImport(event) {
  event.preventDefault();
  const profileImport = state.activeProfileImport;
  if (!profileImport || profileImport.status !== "pending") {
    setMessage("Ce brouillon ne peut plus être appliqué.", true);
    return;
  }
  const updates = [...elements.profileImportApplyForm.querySelectorAll(".profile-import-field")]
    .filter((row) => row.querySelector(".profile-import-select").checked)
    .map((row) => ({
      field: row.dataset.field,
      mode: row.querySelector(".profile-import-mode").value,
      value: row.querySelector(".profile-import-value").value.trim(),
    }));
  if (!updates.length) {
    setMessage("Coche au moins un champ à appliquer, ou ferme le brouillon.", true);
    return;
  }
  try {
    const result = await api(`/api/career/profile-imports/${encodeURIComponent(profileImport.id)}/apply`, {
      method: "POST",
      body: JSON.stringify({ updates, base_profile_updated_at: profileImport.base_profile_updated_at || "" }),
    });
    state.activeProfileImport = null;
    elements.profileImportReview.hidden = true;
    setMessage("Profil local mis à jour à partir des champs que tu as validés. Aucun document n’a été envoyé à un fournisseur IA.");
    await Promise.all([loadProfile(), loadProfileImports()]);
    return result;
  } catch (error) { setMessage(error.message, true); }
}

async function deleteProfileImport(profileImport) {
  if (!window.confirm(`Supprimer définitivement la source locale « ${profileImport.original_name || "texte de profil"} » et son brouillon ?`)) return;
  try {
    await api(`/api/career/profile-imports/${encodeURIComponent(profileImport.id)}`, { method: "DELETE" });
    if (state.activeProfileImport?.id === profileImport.id) {
      state.activeProfileImport = null;
      elements.profileImportReview.hidden = true;
    }
    setMessage("Source de profil supprimée localement.");
    await loadProfileImports();
  } catch (error) { setMessage(error.message, true); }
}

async function loadPreferences() {
  state.preferences = await api("/api/career/preferences");
  const availability = state.preferences.availability || {};
  $("#availability-start").value = availability.availability_start || "2027-01-01";
  $("#availability-end").value = availability.availability_end || "2027-06-30";
  $("#duration-min").value = availability.minimum_duration_months || "3";
  $("#duration-max").value = availability.maximum_duration_months || "6";
  renderPreferenceRows(elements.familyPreferences, state.preferences.families || []);
  renderPreferenceRows(elements.locationPreferences, state.preferences.locations || []);
  renderFamilyOptions();
}

function formatVerification(value) {
  if (!value) return "jamais vérifié";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "heure inconnue" : date.toLocaleString("fr-FR");
}

function sourceCard(source) {
  const item = make("article", "", "discovery-source-item");
  const copy = make("div", "", "discovery-source-copy");
  copy.append(make("p", source.company || "Board public", "discovery-source-name"));
  const metadata = [
    "Greenhouse officiel",
    source.enabled ? "actif" : "désactivé",
    `${source.jobs_stored || 0} offre${Number(source.jobs_stored || 0) > 1 ? "s" : ""} conservée${Number(source.jobs_stored || 0) > 1 ? "s" : ""}`,
    `vérifié : ${formatVerification(source.last_success_at)}`,
  ];
  if (source.last_error_code) metadata.push(`dernière erreur : ${source.last_error_code}`);
  copy.append(make("p", metadata.join(" · "), "discovery-source-meta"));
  const actions = make("div", "", "discovery-source-actions");
  const official = make("a", "Voir le board", "quiet-button external-link");
  official.href = source.public_url;
  official.target = "_blank";
  official.rel = "noopener noreferrer";
  official.setAttribute("aria-label", `Ouvrir le board officiel de ${source.company || "cette entreprise"} dans un nouvel onglet`);
  const toggle = make("button", source.enabled ? "Désactiver" : "Activer", "quiet-button");
  toggle.type = "button";
  toggle.addEventListener("click", async () => {
    try {
      await api(`/api/career/discovery-sources/${encodeURIComponent(source.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !source.enabled }),
      });
      setMessage(source.enabled ? "Board désactivé : aucune requête ne lui sera envoyée." : "Board activé pour la prochaine recherche manuelle.");
      await loadDiscoverySources();
    } catch (error) { setMessage(error.message, true); }
  });
  actions.append(official, toggle);
  item.append(copy, actions);
  return item;
}

function renderDiscoverySources() {
  elements.discoverySources.replaceChildren();
  elements.discoverySourcesEmpty.hidden = state.discoverySources.length > 0;
  state.discoverySources.forEach((source) => elements.discoverySources.append(sourceCard(source)));
  const active = state.discoverySources.some((source) => source.enabled);
  elements.discoverySearch.disabled = !active;
  elements.discoveryForceSearch.disabled = !active;
}

async function loadDiscoverySources() {
  const payload = await api("/api/career/discovery-sources");
  state.discoverySources = payload.sources || [];
  renderDiscoverySources();
}

async function addDiscoverySource(event) {
  event.preventDefault();
  const submit = elements.discoverySourceSubmit;
  submit.disabled = true;
  submit.textContent = "Enregistrement…";
  try {
    const source = await api("/api/career/discovery-sources", {
      method: "POST",
      body: JSON.stringify(formObject(elements.discoverySourceForm)),
    });
    elements.discoverySourceForm.reset();
    setMessage(`Board officiel « ${source.company} » enregistré localement. Clique sur Rechercher pour le lire.`);
    await loadDiscoverySources();
  } catch (error) { setMessage(error.message, true); }
  finally {
    submit.disabled = false;
    submit.textContent = "Ajouter ce board officiel";
  }
}

async function runDiscovery(force = false) {
  const trigger = force ? elements.discoveryForceSearch : elements.discoverySearch;
  const sibling = force ? elements.discoverySearch : elements.discoveryForceSearch;
  trigger.disabled = true;
  sibling.disabled = true;
  const previousLabel = trigger.textContent;
  trigger.textContent = "Recherche en cours…";
  try {
    const result = await api("/api/career/discovery/search", {
      method: "POST",
      body: JSON.stringify({ force }),
    });
    const outcomes = result.outcomes || [];
    const errors = outcomes.filter((outcome) => outcome.status === "error");
    const refreshed = outcomes.filter((outcome) => outcome.status === "success" || outcome.status === "partial");
    const cached = outcomes.filter((outcome) => outcome.status === "cached");
    const summary = [
      refreshed.length ? `${refreshed.length} board${refreshed.length > 1 ? "s" : ""} vérifié${refreshed.length > 1 ? "s" : ""}` : "",
      cached.length ? `${cached.length} résultat${cached.length > 1 ? "s" : ""} récent${cached.length > 1 ? "s" : ""} conservé${cached.length > 1 ? "s" : ""}` : "",
      errors.length ? `${errors.length} source${errors.length > 1 ? "s" : ""} en erreur` : "",
    ].filter(Boolean).join(" · ");
    const detail = errors.map((outcome) => `${outcome.company} : ${outcome.message}`).join(" ");
    setMessage(`${summary || "Recherche terminée."}${detail ? ` ${detail}` : ""}`, errors.length > 0 && refreshed.length === 0);
    await Promise.all([loadDiscoverySources(), loadJobs(), loadShortlist(), loadDashboard(), loadStudio(), refreshStageHunterIfVisible()]);
  } catch (error) { setMessage(error.message, true); }
  finally {
    trigger.textContent = previousLabel;
    await loadDiscoverySources().catch(() => {});
  }
}

function dashboardActionPriority(priority) {
  if (priority <= 20) return { label: "À traiter maintenant", tone: "urgent" };
  if (priority <= 50) return { label: "Priorité haute", tone: "high" };
  if (priority <= 80) return { label: "À planifier", tone: "normal" };
  return { label: "Prochaine étape", tone: "" };
}

function setDashboardActionPlanBusy(busy) {
  elements.dashboardActionPlanPanel?.setAttribute("aria-busy", String(busy));
}

function hasDashboardActionPlanItems() {
  return [...(elements.dashboardActionPlan?.children || [])]
    .some((item) => !item.classList.contains("action-plan-skeleton"));
}

function renderDashboardActionPlanLoading() {
  const { dashboardActionPlan: target, dashboardActionPlanEmpty: empty, dashboardActionPlanLoading: loading, dashboardActionPlanError: error, dashboardActionPlanStatus: status } = elements;
  if (!target || !empty || !loading || !error) return;
  setDashboardActionPlanBusy(true);
  error.hidden = true;
  error.textContent = "";
  empty.hidden = true;
  target.hidden = false;
  loading.hidden = false;
  loading.textContent = "Mise à jour de ton plan d’action…";
  if (!hasDashboardActionPlanItems()) {
    target.replaceChildren(...Array.from({ length: 3 }, () => {
      const skeleton = make("li", "", "action-plan-skeleton");
      skeleton.setAttribute("aria-hidden", "true");
      return skeleton;
    }));
  }
  if (status) status.textContent = "Mise à jour du plan d’action en cours.";
}

function renderDashboardActionPlanError() {
  const { dashboardActionPlan: target, dashboardActionPlanEmpty: empty, dashboardActionPlanLoading: loading, dashboardActionPlanError: error, dashboardActionPlanStatus: status } = elements;
  if (!target || !empty || !loading || !error) return;
  target.querySelectorAll(".action-plan-skeleton").forEach((item) => item.remove());
  const hasItems = hasDashboardActionPlanItems();
  setDashboardActionPlanBusy(false);
  loading.hidden = true;
  error.hidden = false;
  error.textContent = "Le plan d’action ne peut pas être actualisé pour le moment. Tes données locales n’ont pas été modifiées ; réessaie dans un instant.";
  target.hidden = !hasItems;
  empty.hidden = true;
  if (status) status.textContent = "Le plan d’action est momentanément indisponible.";
}

function renderDashboardActionPlan(actions) {
  const { dashboardActionPlan: target, dashboardActionPlanEmpty: empty, dashboardActionPlanLoading: loading, dashboardActionPlanError: error, dashboardActionPlanStatus: status } = elements;
  if (!target || !empty || !loading || !error) return;
  const plan = (Array.isArray(actions) ? actions : [])
    .map((action, index) => ({
      action,
      index,
      priority: Number.isFinite(Number(action?.priority)) ? Number(action.priority) : 999,
    }))
    .filter(({ action }) => action && typeof action === "object")
    .sort((left, right) => left.priority - right.priority || left.index - right.index);

  target.replaceChildren();
  setDashboardActionPlanBusy(false);
  loading.hidden = true;
  error.hidden = true;
  error.textContent = "";
  if (!plan.length) {
    target.hidden = true;
    empty.hidden = false;
    empty.textContent = "Ton suivi est à jour pour le moment. Tu peux continuer à explorer des offres ou lancer un entraînement.";
    if (status) status.textContent = "Aucune nouvelle étape prioritaire dans ton plan d’action.";
    return;
  }

  target.hidden = false;
  empty.hidden = true;
  plan.forEach(({ action, priority }, index) => {
    const title = typeof action.title === "string" && action.title.trim() ? action.title.trim() : "Étape Career";
    const detail = typeof action.detail === "string" ? action.detail.trim() : "";
    const targetView = typeof action.target_view === "string" && careerViews.has(action.target_view) ? action.target_view : "";
    const priorityMeta = dashboardActionPriority(priority);
    const item = make("li", "", "action-plan-item");
    const order = make("span", String(index + 1).padStart(2, "0"), "action-plan-number");
    order.setAttribute("aria-hidden", "true");
    const copy = make("div", "", "action-plan-copy");
    const meta = make("div", "", "action-plan-meta");
    meta.append(make("span", priorityMeta.label, `action-plan-priority${priorityMeta.tone ? ` ${priorityMeta.tone}` : ""}`));
    if (targetView) meta.append(make("span", `Dans ${labelForView(targetView)}`, "action-plan-destination"));
    copy.append(meta, make("h4", title));
    if (detail) copy.append(make("p", detail));
    item.append(order, copy);
    if (targetView) {
      const open = make("button", "Ouvrir", "quiet-button action-plan-button");
      open.type = "button";
      open.setAttribute("aria-label", `Ouvrir ${labelForView(targetView)} pour : ${title}`);
      open.addEventListener("click", () => {
        showView(targetView);
        setMessage(`Ouverture de ${labelForView(targetView)} pour : ${title}`);
      });
      item.append(open);
    }
    target.append(item);
  });
  if (status) status.textContent = `${plan.length} étape${plan.length > 1 ? "s" : ""} prioritaire${plan.length > 1 ? "s" : ""} disponible${plan.length > 1 ? "s" : ""} dans ton plan d’action.`;
}

async function loadDashboard() {
  renderDashboardActionPlanLoading();
  let dashboard;
  try {
    dashboard = await api("/api/career/dashboard");
    const profile = await api("/api/career/profile");
    renderTodayProfileReadiness(profile?.readiness || {});
  } catch (error) {
    renderDashboardActionPlanError();
    throw error;
  }
  elements.metrics.replaceChildren(
    metric(dashboard.jobs_total, "offres importées"),
    metric(dashboard.jobs_open, "annonces ouvertes"),
    metric(dashboard.shortlisted, "dans la shortlist"),
    metric(dashboard.to_review, "calendriers à vérifier"),
    metric(dashboard.applications_total, "suivis créés"),
    metric(dashboard.drafts_total || 0, "brouillons créés"),
    metric(dashboard.interviews_active || 0, "séances actives"),
    metric(dashboard.receipt_unknown, "réceptions inconnues"),
  );
  renderDashboardActionPlan(dashboard.action_plan);
  const jobs = state.jobs.length ? state.jobs : (await api("/api/career/jobs")).jobs || [];
  renderDashboardList(
    elements.dashboardRecommendations,
    elements.dashboardRecommendationsEmpty,
    jobs.filter((job) => job.scoring?.is_recommendable && job.deadline_status !== "closed").slice(0, 4),
    "recommendation",
  );
  renderDashboardList(
    elements.dashboardDeadlines,
    elements.dashboardDeadlinesEmpty,
    (dashboard.upcoming_deadlines || []).slice(0, 4),
    "deadline",
  );
}

function renderTodayProfileReadiness(readiness) {
  const target = elements.todayProfileReadiness;
  if (!target) return;
  const score = Number.isFinite(Number(readiness.score_out_of_20)) ? Number(readiness.score_out_of_20) : 0;
  const maximum = Number.isFinite(Number(readiness.maximum_score)) ? Number(readiness.maximum_score) : 20;
  const label = readiness.label || "Profil à compléter";
  const actions = Array.isArray(readiness.next_actions) ? readiness.next_actions : [];
  target.replaceChildren(
    make("strong", `${label} · ${score}/${maximum}`),
    make("span", actions.length ? `Prochaine amélioration : ${actions[0]}` : "Ton profil contient les éléments essentiels.", "today-profile-next"),
  );
}

function renderDashboardList(target, empty, jobs, kind) {
  if (!target || !empty) return;
  target.replaceChildren();
  empty.hidden = jobs.length > 0;
  jobs.forEach((job) => {
    const item = make("article", "", "dashboard-item");
    const heading = make("div", "", "dashboard-item-copy");
    heading.append(make("strong", job.title || "Offre"), make("span", job.company || "Entreprise"));
    const meta = kind === "deadline"
      ? `Date limite : ${job.deadline_date || "à vérifier"}`
      : `Pertinence ${job.scoring?.score ?? "à vérifier"}/100`;
    heading.append(make("small", meta));
    const open = make("button", kind === "deadline" ? "Suivre" : "Voir", "quiet-button");
    open.type = "button";
    open.addEventListener("click", () => showView(kind === "deadline" ? "applications" : "discover"));
    item.append(heading, open);
    target.append(item);
  });
}

function chip(label, tone = "") {
  return make("span", label, `job-chip${tone ? ` ${tone}` : ""}`);
}

function jobCard(job, mode = "discover", qualification = null) {
  const card = make("article", "", "job-card");
  const header = make("div", "", "job-card-header");
  const titleBlock = make("div");
  titleBlock.append(make("h3", job.title), make("p", job.company, "job-company"));
  const calendarTone = calendarClasses[job.calendar_status] || "warning";
  const qualificationLabels = {conforming:"Conforme aux critères sélectionnés", to_verify:"À vérifier", non_conforming:"Non conforme"};
  header.append(titleBlock, qualification
    ? chip(qualificationLabels[qualification.target_status] || "À vérifier", qualification.target_status === "conforming" ? "good" : "warning")
    : chip(calendarLabels[job.calendar_status] || "À vérifier", calendarTone));
  card.append(header);

  const chips = make("div", "", "job-chips");
  if (job.job_family) chips.append(chip(job.job_family));
  if (job.city || job.country) chips.append(chip([job.city, job.country].filter(Boolean).join(", ")));
  const availabilityTone = job.deadline_status === "closed" ? "danger" : job.source_status === "open" ? "good" : "warning";
  chips.append(chip(job.deadline_status === "closed" ? "Annonce fermée / échue" : job.source_status === "open" ? "Annonce ouverte" : "Statut à vérifier", availabilityTone));
  const scoring = qualification ? {} : (job.scoring || {});
  const scoreTone = scoring.blocking_constraints?.length ? "danger" : scoring.is_recommendable ? "good" : "warning";
  if (Number.isFinite(scoring.score)) chips.append(chip(`Pertinence ${scoring.score}/100`, scoreTone));
  if (job.shortlisted) chips.append(chip("Shortlist", "good"));
  card.append(chips);

  const details = make("div", "", "job-details");
  if (job.deadline_date) details.append(make("p", `Date limite : ${job.deadline_date}`));
  if (job.start_date || job.end_date || job.duration_months) {
    details.append(make("p", `Période annoncée : ${[job.start_date, job.end_date].filter(Boolean).join(" → ") || "dates non précisées"}${job.duration_months ? ` · ${job.duration_months} mois` : ""}`));
  }
  if (qualification) {
    const month = qualification.start_month ? new Date(2000, qualification.start_month - 1, 1).toLocaleString("fr-FR", {month:"long"}) : "non précisé";
    details.append(make("p", `Début annoncé : ${qualification.start_date || `${month} ${qualification.provenance?.start_year?.value || "(année à vérifier)"}`}`));
    const minimum = qualification.duration_min_months, maximum = qualification.duration_max_months;
    details.append(make("p", `Durée annoncée : ${minimum == null ? "non précisée" : minimum === maximum ? `${minimum} mois` : `${minimum} à ${maximum} mois`}`));
    const sourceDate = qualification.provenance?.start_month;
    if (sourceDate?.source === "description_passage") details.append(make("p", `Passage source du début : « ${sourceDate.quote} »`));
    const geographyLabels = {
      allowed: "Lieu hors zone exclue confirmé",
      excluded: "Lieu exclu : France ou Paris",
      mixed: "Plusieurs lieux dont un lieu exclu — à vérifier",
      unknown: "Pays inconnu — à vérifier",
      not_filtered: "Aucune exclusion géographique appliquée",
    };
    if (qualification.geography_status) {
      details.append(make("p", `Contrôle géographique : ${geographyLabels[qualification.geography_status] || "à vérifier"}`));
    }
  } else if (!job.deadline_date && !job.start_date && !job.end_date && !job.duration_months) details.append(make("p", "Dates non renseignées."));
  if (job.source_name && job.source_name !== "manual") {
    details.append(make("p", `Source officielle : ${job.source_name} · vérifiée : ${formatVerification(job.last_verified_at)}`));
  }
  card.append(details);
  if (!qualification && (job.calendar_reasons || []).length) {
    const reasons = make("ul", "", "job-reasons");
    job.calendar_reasons.forEach((reason) => reasons.append(make("li", reason)));
    card.append(reasons);
  }
  if (job.description_original) {
    const description = make("details");
    description.append(make("summary", "Description source conservée localement"));
    description.append(make("p", job.description_original));
    card.append(description);
  }
  const scoreBlock = make("section", "", `scoring-summary${scoring.blocking_constraints?.length ? " blocked" : ""}`);
  const scoreTitle = make("p", scoring.label || "Pertinence à calculer", "scoring-title");
  scoreBlock.append(scoreTitle);
  if (scoring.disclaimer) scoreBlock.append(make("p", scoring.disclaimer, "scoring-disclaimer"));
  if ((scoring.reasons || []).length) {
    const list = make("ul", "", "scoring-list good-list");
    scoring.reasons.slice(0, 3).forEach((reason) => list.append(make("li", reason)));
    scoreBlock.append(list);
  }
  if ((scoring.unknowns || []).length) {
    const list = make("ul", "", "scoring-list review-list");
    scoring.unknowns.slice(0, 3).forEach((reason) => list.append(make("li", `À vérifier : ${reason}`)));
    scoreBlock.append(list);
  }
  if ((scoring.blocking_constraints || []).length) {
    const list = make("ul", "", "scoring-list blocked-list");
    scoring.blocking_constraints.forEach((reason) => list.append(make("li", `Blocage : ${reason}`)));
    scoreBlock.append(list);
  }
  if (!qualification) card.append(scoreBlock);

  const actions = make("div", "", "job-actions");
  const shortlist = make("button", job.shortlisted ? "Retirer de la shortlist" : "Ajouter à la shortlist", "secondary-button");
  shortlist.type = "button";
  shortlist.addEventListener("click", () => toggleShortlist(job));
  actions.append(shortlist);
  const application = make("button", job.application ? "Voir le suivi" : "Créer un suivi", "secondary-button");
  application.type = "button";
  application.addEventListener("click", () => createOrShowApplication(job));
  actions.append(application);
  const editNote = make("button", "Note personnelle", "quiet-button");
  editNote.type = "button";
  editNote.addEventListener("click", () => updateJobNote(job, card));
  actions.append(editNote);
  if (job.official_url) {
    const official = make("a", "Ouvrir l’offre officielle", "secondary-button external-link");
    official.href = job.official_url;
    official.target = "_blank";
    official.rel = "noopener noreferrer";
    official.setAttribute("aria-label", `Ouvrir l’offre officielle « ${job.title} » chez ${job.company} dans un nouvel onglet`);
    actions.append(official);
  }
  if (mode === "shortlist") {
    const note = job.personal_note ? make("p", `Note : ${job.personal_note}`, "job-details") : null;
    if (note) card.append(note);
  }
  card.append(actions);
  return card;
}

function renderJobs(jobs, target, empty, mode) {
  target.replaceChildren();
  empty.hidden = jobs.length > 0;
  jobs.forEach((job) => target.append(jobCard(job, mode)));
}

async function loadJobs() {
  const query = $("#filter-query").value.trim();
  const family = $("#filter-family").value;
  const sourceStatus = $("#filter-status").value;
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (family) params.set("family", family);
  if (sourceStatus) params.set("source_status", sourceStatus);
  const payload = await api(`/api/career/jobs?${params.toString()}`);
  state.jobs = payload.jobs || [];
  renderJobs(state.jobs, elements.jobs, elements.jobsEmpty, "discover");
}

async function loadShortlist() {
  const payload = await api("/api/career/jobs?shortlisted=true");
  renderJobs(payload.jobs || [], elements.shortlist, elements.shortlistEmpty, "shortlist");
}

async function toggleShortlist(job) {
  try {
    // Aucune invite bloquante : la note optionnelle reste modifiable inline ensuite.
    await api(`/api/career/jobs/${encodeURIComponent(job.id)}/shortlist`, {
      method: "POST",
      body: JSON.stringify({ shortlisted: !job.shortlisted, note: job.personal_note ?? "" }),
    });
    setMessage(job.shortlisted ? "Offre retirée de la shortlist." : "Offre ajoutée à la shortlist. Ajoute une note via « Note personnelle » si besoin.");
    await Promise.all([loadDashboard(), loadJobs(), loadShortlist(), refreshStageHunterIfVisible()]);
  } catch (error) { setMessage(error.message, true); }
}

// The Stage Hunter tab refreshes itself only when it is on screen, so other
// views keep their current cost.
async function refreshStageHunterIfVisible() {
  if (window.location.hash !== "#career/stagehunter") return;
  await loadStageHunter().catch(() => {});
}

// Éditeur de note inline (pas de dialogue bloquant) : accessible au clavier,
// user stays in context, and the destructive-data typed confirmation remains
// the only prompt of this file.
function openNoteEditor(job, card, onSaved) {
  const existing = card.querySelector(".job-note-editor");
  if (existing) existing.remove();
  const editor = make("form", "", "job-note-editor");
  const label = make("label", "Note personnelle (locale)", "job-note-label");
  const input = document.createElement("textarea");
  input.rows = 3;
  input.value = job.personal_note || "";
  input.id = `job-note-${job.id}`;
  input.maxLength = 2000;
  label.htmlFor = input.id;
  const save = make("button", "Enregistrer", "primary-button");
  save.type = "submit";
  const cancel = make("button", "Annuler", "quiet-button");
  cancel.type = "button";
  editor.append(label, input, cancel, save);
  editor.addEventListener("submit", (event) => {
    event.preventDefault();
    editor.remove();
    onSaved(input.value);
  });
  cancel.addEventListener("click", () => editor.remove());
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      editor.remove();
    }
  });
  card.append(editor);
  input.focus();
}

async function updateJobNote(job, card) {
  if (!card) {
    setMessage("Ouvre la note depuis la carte de l’offre.", true);
    return;
  }
  openNoteEditor(job, card, async (note) => {
    try {
      await api(`/api/career/jobs/${encodeURIComponent(job.id)}/note`, { method: "PATCH", body: JSON.stringify({ note }) });
      setMessage("Note personnelle enregistrée.");
      await Promise.all([loadJobs(), loadShortlist()]);
    } catch (error) { setMessage(error.message, true); }
  });
}

async function createOrShowApplication(job) {
  try {
    if (!job.application) {
      await api("/api/career/applications", { method: "POST", body: JSON.stringify({ job_id: job.id }) });
      setMessage("Suivi de candidature créé. Aucun envoi n’a été effectué.");
      await Promise.all([loadDashboard(), loadJobs(), loadShortlist(), loadApplications(), refreshStageHunterIfVisible()]);
    }
    showView("applications");
  } catch (error) { setMessage(error.message, true); }
}

function applicationCard(application) {
  const card = make("article", "", "application-card");
  card.dataset.applicationId = application.id;
  const header = make("div", "", "application-card-header");
  const title = make("div");
  title.append(make("h3", application.title), make("p", `${application.company}${application.city ? ` · ${application.city}` : ""}`, "job-company"));
  header.append(title, chip(stageLabels[application.stage] || application.stage, application.receipt_status === "unknown" ? "warning" : application.receipt_status === "confirmed" ? "good" : ""));
  card.append(header);
  const meta = make("p", "", "application-meta");
  meta.textContent = `Réception : ${application.receipt_status === "confirmed" ? "confirmée" : application.receipt_status === "unknown" ? "inconnue — ne pas renvoyer automatiquement" : "non déclarée"}.`;
  card.append(meta);  if (application.confirmation_reference) card.append(make("p", `Référence : ${application.confirmation_reference}`, "application-meta"));
  const actions = make("div", "", "application-actions");
  const select = document.createElement("select");
  const currentLabel = stageLabels[application.stage] || application.stage;
  select.append(new Option(currentLabel, "", true, true));
  const permittedStages = application.receipt_status === "confirmed" ? stagesAfterConfirmedReceipt : editableStages;
  permittedStages.forEach((stage) => {
    if (stage !== application.stage) select.append(new Option(stageLabels[stage], stage));
  });
  select.setAttribute("aria-label", `Statut de ${application.title}`);
  actions.append(select);
  const kitButton = make("button", "Ouvrir le kit de candidature", "secondary-button");
  kitButton.type = "button";
  const kitContainer = make("div", "", "application-kit");
  kitContainer.dataset.applicationId = application.id;
  kitContainer.dataset.jobId = application.job_id;
  kitContainer.hidden = true;
  kitButton.addEventListener("click", () => openApplicationKit(application, kitContainer));
  actions.append(kitButton);
  // SK-11 : le dossier vérifiable est une action distincte du kit — il applique
  // le vérificateur de faits et refuse l'export tant qu'une affirmation n'est
  // pas prouvée. Il reste entièrement local et n'envoie rien.
  const dossierButton = make("button", "Ouvrir le dossier vérifiable", "secondary-button");
  dossierButton.type = "button";
  const dossierContainer = make("div", "", "application-dossier");
  dossierContainer.dataset.applicationId = application.id;
  dossierContainer.hidden = true;
  dossierButton.addEventListener("click", () => openApplicationDossier(application, dossierContainer));
  actions.append(dossierButton);
  const noteLabel = make("label", "Note de suivi (facultative)");
  const noteInput = document.createElement("input");
  noteInput.type = "text";
  noteInput.maxLength = 1000;
  noteLabel.append(noteInput);
  actions.append(noteLabel);
  const save = make("button", "Mettre à jour", "secondary-button");
  save.type = "button";
  save.addEventListener("click", async () => {
    if (!select.value) return;
    try {
      await api(`/api/career/applications/${encodeURIComponent(application.id)}`, { method: "PATCH", body: JSON.stringify({ stage: select.value, note: noteInput.value || "" }) });
      setMessage("Statut de suivi mis à jour.");
      await Promise.all([loadApplications(), loadDashboard(), refreshStageHunterIfVisible()]);
    } catch (error) { setMessage(error.message, true); }
  });
  actions.append(save);
  if (!application.approval_granted) {
    const approvalLabel = make("label");
    const approvalCheck = document.createElement("input");
    approvalCheck.type = "checkbox";
    approvalLabel.append(approvalCheck, document.createTextNode("J’approuve le dépôt manuel pour cette offre uniquement. Rien n’est envoyé par Côme AI."));
    actions.append(approvalLabel);
    const approve = make("button", "Approuver pour dépôt manuel", "quiet-button");
    approve.type = "button";
    approve.addEventListener("click", () => approveApplication(application, approvalCheck.checked));
    actions.append(approve);
  }
  if (application.approval_granted && application.receipt_status !== "confirmed") {
    const referenceLabel = make("label", "Référence de réception (preuve reçue après dépôt manuel)");
    const referenceInput = document.createElement("input");
    referenceInput.type = "text";
    referenceInput.maxLength = 1000;
    referenceLabel.append(referenceInput);
    actions.append(referenceLabel);
    const confirm = make("button", "Confirmer la réception", "quiet-button");
    confirm.type = "button";
    confirm.addEventListener("click", () => confirmReceipt(application, referenceInput.value));
    actions.append(confirm);
  }
  const unknown = make("button", "Réception inconnue", "quiet-button");
  unknown.type = "button";
  unknown.addEventListener("click", () => markReceiptUnknown(application, noteInput.value));
  actions.append(unknown);
  if (application.official_url) {
    const link = make("a", "Ouvrir l’offre officielle", "secondary-button external-link");
    link.href = application.official_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.append(link);
  }
  card.append(actions);
  if (!application.approval_granted && application.receipt_status !== "confirmed") {
    card.append(make("p", "L’approbation locale pour cette offre précise est requise avant de consigner une réception confirmée.", "application-meta"));
  }
  card.append(kitContainer);
  card.append(dossierContainer);
  return card;
}

const applicationChecklistItems = [
  { key: "cv_reviewed", label: "CV relu pour cette offre" },
  { key: "letter_customized", label: "Lettre personnalisée" },
  { key: "documents_checked", label: "Documents vérifiés (PDF, formats)" },
  { key: "deadline_verified", label: "Date limite vérifiée à la source" },
  { key: "followup_planned", label: "Relance locale prévue" },
];

const radarBucketLabels = {
  followup: "Relance",
  deadline_close: "Échéance proche",
  deadline_passed: "Échéance dépassée",
  review: "Dossier à reprendre",
  interview_preparation: "Entretien",
};

async function copyTextToClipboard(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.classList.add("clipboard-fallback");
  document.body.append(area);
  area.select();
  try { document.execCommand("copy"); } finally { area.remove(); }
}

function radarEntryText(entry) {
  // Composante pure testée par gardes Node : textes honnêtes du radar.
  const bucket = entry.bucket || "review";
  const waiting = entry.waiting_days;
  const dateText = entry.suggested_date || "";
  let heading;
  if (bucket === "deadline_close") heading = `Finalise : date limite connue — suggestion : ${dateText}.`;
  else if (bucket === "deadline_passed") heading = "Échéance dépassée : vérifie l’offre avant de relancer.";
  else if (bucket === "followup") {
    heading = entry.status === "upcoming"
      ? `Aucune relance conseillée avant le ${dateText}.`
      : (waiting === null || waiting === undefined
        ? "Relance suggérée : brouillon prêt, aucun e-mail envoyé."
        : `${waiting} jours sans réponse : brouillon de relance prêt, aucun e-mail envoyé.`);
  } else heading = "Reprise locale du dossier suggérée.";
  const note = "Brouillon local à copier : Côme AI n’envoie aucun e-mail, aucun message ni candidature, jamais.";
  return { heading, note };
}

function applicationFilterQuery() {
  const params = new URLSearchParams();
  const stage = elements.applicationsFilterStage?.value || "";
  const receipt = elements.applicationsFilterReceipt?.value || "";
  const deadline = elements.applicationsFilterDeadline?.value || "";
  if (stage) params.set("stage", stage);
  if (receipt) params.set("receipt", receipt);
  if (deadline) params.set("deadline", deadline);
  if (elements.applicationsFilterAction?.checked) params.set("action_required", "true");
  const text = params.toString();
  return text ? `?${text}` : "";
}

function renderApplicationCounters(dash) {
  if (!elements.applicationsCounters) return;
  elements.applicationsCounters.replaceChildren();
  Object.entries(dash.counts_by_stage || {}).forEach(([stage, count]) => {
    const item = make("button", `${stageLabels[stage] || stage} : ${count}`, "stage-counter");
    item.type = "button";
    item.setAttribute("role", "listitem");
    item.setAttribute("aria-pressed", String(elements.applicationsFilterStage?.value === stage));
    item.setAttribute("aria-label", `${stageLabels[stage] || stage} : ${count} candidatures`);
    item.addEventListener("click", () => {
      if (!elements.applicationsFilterStage) return;
      elements.applicationsFilterStage.value = elements.applicationsFilterStage.value === stage ? "" : stage;
      loadApplications();
    });
    elements.applicationsCounters.append(item);
  });
}

function renderApplicationRadar(radar) {
  if (!elements.applicationsRadar) return;
  elements.applicationsRadar.replaceChildren();
  if (!radar || !radar.length) {
    elements.applicationsRadar.append(make("p", "Aucune relance en attente. Rien n’est envoyé automatiquement, jamais.", "empty-state compact-empty"));
    return;
  }
  radar.forEach((entry) => {
    const copy = radarEntryText(entry);
    const card = make("article", "", "radar-entry");
    const title = make("div", "", "radar-entry-title");
    title.append(
      make("h3", `${entry.title} — ${entry.company}`),
      chip(radarBucketLabels[entry.bucket] || entry.bucket, entry.status === "due" ? "warning" : "")
    );
    card.append(title, make("p", copy.heading, "radar-entry-heading"));
    if (entry.receipt_unknown) {
      card.append(make("p", "Réception non confirmée : ne renvoie pas automatiquement.", "radar-entry-warning"));
    }
    if (entry.draft_ready && entry.draft) {
      const copyButton = make("button", "Copier le brouillon de relance", "secondary-button");
      copyButton.type = "button";
      copyButton.setAttribute("aria-label", `Copier le brouillon de relance de ${entry.title} — aucun envoi automatique`);
      copyButton.addEventListener("click", async () => {
        try {
          await copyTextToClipboard(entry.draft);
          setMessage("Brouillon copié. Envoie-le toi-même : aucune relance n’est transmise par Côme AI.");
        } catch (error) {
          setMessage(error.message || "Copie impossible dans ce navigateur.", true);
        }
      });
      card.append(copyButton);
    }
    card.append(make("p", copy.note, "radar-entry-note"));
    elements.applicationsRadar.append(card);
  });
}

function applicationPrepBlock(entry) {
  const details = make("details", "", "prep-score");
  const prep = entry.prep || {};
  const incomplete = prep.score === null || prep.score === undefined;
  details.append(make("summary", incomplete ? "Note de préparation : incomplète (facteurs inconnus)" : `Note de préparation : ${prep.score}/100`, "prep-score-summary"));
  const body = make("div", "", "prep-score-body");
  body.append(make("p", prep.formula || "", "prep-formula"));
  Object.entries(prep.factors || {}).forEach(([name, factor]) => {
    body.append(make("p", `${name} : ${factor.percent}/100 — ${factor.detail}`, "prep-factor"));
    const missing = factor.quantifiable_missing || [];
    if (missing.length) {
      body.append(make("p", `Résultats mesurables à ajouter uniquement si vérifiables : ${missing.join(" · ")}`, "prep-factor-unknown"));
    }
  });
  (prep.unknowns || []).forEach((unknown) => {
    body.append(make("p", `Inconnu (${unknown.factor}) : ${unknown.reason}`, "prep-factor-unknown"));
  });
  body.append(make("p", prep.disclaimer || "", "prep-disclaimer"));
  details.append(body);
  return details;
}

function applicationChecklistBlock(application, checkedKeys) {
  const details = make("details", "", "application-checklist");
  details.append(make("summary", "Checklist locale (5 cases)"));
  const list = make("div", "", "application-checklist-items");
  const checked = () => applicationChecklistItems
    .filter((item) => list.querySelector(`input[data-checkkey="${item.key}"]`)?.checked)
    .map((item) => item.key);
  applicationChecklistItems.forEach((item) => {
    const label = make("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.dataset.checkkey = item.key;
    box.checked = checkedKeys.includes(item.key);
    box.addEventListener("change", async () => {
      try {
        await api(`/api/career/applications/${encodeURIComponent(application.id)}/checklist`, {
          method: "POST",
          body: JSON.stringify({ checked: checked() }),
        });
        setMessage("Checklist locale mise à jour (aucun envoi effectué).");
      } catch (error) { setMessage(error.message, true); }
    });
    label.append(box, document.createTextNode(item.label));
    list.append(label);
  });
  details.append(list);
  return details;
}

function applicationTimelineBlock(entry) {
  const details = make("details", "", "application-timeline");
  details.append(make("summary", "Chronologie locale"));
  (entry.timeline || []).forEach((event) => {
    const when = event.at ? String(event.at).slice(0, 19).replace("T", " ") : "date inconnue";
    details.append(make("p", `${when} · ${event.event_type}${event.detail ? ` — ${event.detail}` : ""}`, "timeline-event"));
  });
  return details;
}

function renderApplicationDashboard(dash) {
  state.applicationDashboard = dash;
  if (elements.applicationsHonesty && dash.honesty) elements.applicationsHonesty.textContent = dash.honesty;
  renderApplicationCounters(dash);
  renderApplicationRadar(dash.radar || []);
  const byId = new Map((dash.entries || []).map((entry) => [entry.application_id, entry]));
  elements.applications.replaceChildren();
  state.applications.forEach((application) => {
    const entry = byId.get(application.id);
    const card = applicationCard(application);
    if (entry) {
      card.append(
        applicationPrepBlock(entry),
        applicationChecklistBlock(application, entry.checklist?.checked_keys || []),
        applicationTimelineBlock(entry),
      );
    }
    elements.applications.append(card);
  });
  elements.applicationsEmpty.hidden = state.applications.length > 0;
}

async function loadApplications() {
  const suffix = applicationFilterQuery();
  const [listing, dash] = await Promise.all([
    api("/api/career/applications"),
    api(`/api/career/applications/dashboard${suffix}`),
  ]);
  state.applications = listing.applications || [];
  renderApplicationDashboard(dash);
  await consumePendingKit();
}

const coachModeLabels = {
  technical: "Technique",
  behavioral: "Comportement / motivation",
  case: "Étude de cas",
  company: "Offre ou entreprise",
};
const coachDifficultyLabels = {
  beginner: "Débutant",
  intermediate: "Intermédiaire",
  advanced: "Avancé",
  investment_banking: "Investment Banking",
  private_equity: "Private Equity",
  highly_competitive: "Très sélectif",
};
const coachInterfaceCopy = {
  fr: {
    feedback: "Retour structuré",
    exerciseScore: "Score exercice",
    precision: "Précision",
    structure: "Structure",
    clarity: "Clarté",
    answered: "Réponses",
    average: "Moyenne",
    topics: "Sujets travaillés",
    priorities: "Priorités de révision",
    active: "Séance active",
    completed: "Séance terminée",
    getFeedback: "Obtenir un retour structuré",
    completeSession: "Terminer la séance",
    historyActive: "en cours",
    historyCompleted: "terminée",
  },
  en: {
    feedback: "Structured feedback",
    exerciseScore: "Exercise score",
    precision: "Precision",
    structure: "Structure",
    clarity: "Clarity",
    answered: "Answers",
    average: "Average",
    topics: "Topics practised",
    priorities: "Revision priorities",
    active: "Active session",
    completed: "Completed session",
    getFeedback: "Get structured feedback",
    completeSession: "Complete session",
    historyActive: "in progress",
    historyCompleted: "completed",
  },
  it: {
    feedback: "Feedback strutturato",
    exerciseScore: "Punteggio dell’esercizio",
    precision: "Precisione",
    structure: "Struttura",
    clarity: "Chiarezza",
    answered: "Risposte",
    average: "Media",
    topics: "Argomenti esercitati",
    priorities: "Priorità di ripasso",
    active: "Sessione attiva",
    completed: "Sessione conclusa",
    getFeedback: "Ricevi un feedback strutturato",
    completeSession: "Termina la sessione",
    historyActive: "in corso",
    historyCompleted: "conclusa",
  },
  de: {
    feedback: "Strukturiertes Feedback",
    exerciseScore: "Übungspunktzahl",
    precision: "Präzision",
    structure: "Struktur",
    clarity: "Klarheit",
    answered: "Antworten",
    average: "Durchschnitt",
    topics: "Geübte Themen",
    priorities: "Wiederholungsprioritäten",
    active: "Aktive Sitzung",
    completed: "Sitzung beendet",
    getFeedback: "Strukturiertes Feedback erhalten",
    completeSession: "Sitzung beenden",
    historyActive: "läuft",
    historyCompleted: "beendet",
  },
};

function coachCopy(language) {
  return coachInterfaceCopy[language] || coachInterfaceCopy.fr;
}

function coachSessionLanguage(session) {
  const latestFeedback = (session?.turns || []).at(-1)?.feedback;
  const language = session?.language || session?.progress?.language || latestFeedback?.language;
  return coachInterfaceCopy[language] ? language : "fr";
}

function renderCoachJobOptions(jobs) {
  const current = elements.coachJob.value;
  elements.coachJob.replaceChildren(new Option("Entraînement général", ""));
  jobs.forEach((job) => {
    const location = [job.city, job.country].filter(Boolean).join(", ");
    elements.coachJob.append(new Option(`${job.company} — ${job.title}${location ? ` (${location})` : ""}`, job.id));
  });
  if (jobs.some((job) => job.id === current)) elements.coachJob.value = current;
}

function coachScoreChip(label, value) {
  const chipNode = make("span", `${label} ${value ?? "—"}`, "job-chip");
  return chipNode;
}

function renderCoachFeedback(turn) {
  const feedback = turn?.feedback;
  elements.coachFeedback.replaceChildren();
  elements.coachFeedback.hidden = !feedback;
  if (!feedback) return;
  const copy = coachCopy(feedback.language);
  const scoreLabels = feedback.score_labels || {};
  const feedbackLabels = feedback.feedback_labels || {};
  const heading = make("div", "", "coach-feedback-heading");
  heading.append(make("h3", copy.feedback));
  const scores = make("div", "", "coach-score-list");
  const values = feedback.scores || {};
  scores.append(
    coachScoreChip(scoreLabels.overall || copy.exerciseScore, values.overall),
    coachScoreChip(scoreLabels.precision || copy.precision, values.precision),
    coachScoreChip(scoreLabels.structure || copy.structure, values.structure),
    coachScoreChip(scoreLabels.clarity || copy.clarity, values.clarity),
  );
  heading.append(scores);
  elements.coachFeedback.append(heading);
  const sections = [
    [feedbackLabels.strengths || "Points solides", feedback.strengths || [], "good-list"],
    [feedbackLabels.gaps || "À retravailler", feedback.gaps || [], "review-list"],
    [feedbackLabels.reference_answer || "Réponse de référence", feedback.reference_answer || [], "reference-list"],
  ];
  sections.forEach(([label, items, className]) => {
    if (!items.length) return;
    const block = make("section", "", "coach-feedback-block");
    block.append(make("h4", label));
    const list = make("ul", "", className);
    items.forEach((item) => list.append(make("li", item)));
    block.append(list);
    elements.coachFeedback.append(block);
  });
  if (feedback.coaching) {
    const coaching = make("section", "", "coach-feedback-block");
    coaching.append(make("h4", feedbackLabels.coaching || "Conseil de coaching"), make("p", feedback.coaching, "coach-coaching"));
    elements.coachFeedback.append(coaching);
  }
  if (feedback.disclaimer) elements.coachFeedback.append(make("p", feedback.disclaimer, "scoring-disclaimer"));
}

function renderCoachProgressDetail(progress, language) {
  const target = elements.coachProgressDetail;
  if (!target) return;
  target.replaceChildren();
  const copy = coachCopy(language);
  const labels = progress.labels || {};
  const topics = Object.keys(progress.topics_practised || {}).filter(Boolean);
  if (topics.length) {
    target.append(make("p", `${labels.topics_practised || copy.topics} : ${topics.slice(0, 4).join(" · ")}`, "coach-progress-topics"));
  }
  const priorities = Array.isArray(progress.revision_priorities) ? progress.revision_priorities.filter(Boolean) : [];
  if (priorities.length) {
    const list = make("ul", "", "coach-progress-priorities");
    list.dataset.label = labels.revision_priorities || copy.priorities;
    priorities.slice(0, 4).forEach((priority) => list.append(make("li", priority)));
    target.append(list);
  }
  if (progress.disclaimer) target.append(make("p", progress.disclaimer, "coach-progress-disclaimer"));
  target.hidden = target.childElementCount === 0;
}

function renderCoachSession(session) {
  state.activeCoachSession = session;
  elements.coachSession.hidden = !session;
  if (!session) {
    elements.coachFeedback.replaceChildren();
    elements.coachFeedback.hidden = true;
    if (elements.coachProgressDetail) elements.coachProgressDetail.replaceChildren();
    return;
  }
  const question = session.current_question || {};
  const progress = session.progress || {};
  const language = coachSessionLanguage(session);
  const copy = coachCopy(language);
  const progressLabels = progress.labels || {};
  elements.coachSessionTitle.textContent = `${coachModeLabels[session.mode] || session.mode} · ${coachDifficultyLabels[session.difficulty] || session.difficulty}`;
  elements.coachQuestionTopic.textContent = question.topic_label || question.topic || "Question";
  elements.coachQuestionPrompt.textContent = question.prompt || "La prochaine question locale est indisponible.";
  elements.coachProgress.replaceChildren(
    coachScoreChip(progressLabels.answered_count || copy.answered, progress.answered_count || 0),
    coachScoreChip(progressLabels.average_score || copy.average, progress.average_score ?? "—"),
    coachScoreChip(session.status === "active" ? copy.active : copy.completed, ""),
  );
  renderCoachProgressDetail(progress, language);
  const lastTurn = (session.turns || []).at(-1);
  renderCoachFeedback(lastTurn);
  const active = session.status === "active";
  elements.coachAnswer.disabled = !active;
  elements.coachAnswerSubmit.disabled = !active;
  elements.coachAnswerSubmit.textContent = active ? copy.getFeedback : copy.completed;
  const complete = $("#coach-session-complete");
  complete.hidden = !active;
  complete.textContent = copy.completeSession;
}

function renderCoachHistory() {
  elements.coachHistory.replaceChildren();
  elements.coachHistoryEmpty.hidden = state.coachSessions.length > 0;
  state.coachSessions.forEach((session) => {
    const item = make("article", "", "coach-history-item");
    const copy = make("div", "", "coach-history-copy");
    const target = [session.company, session.title].filter(Boolean).join(" — ");
    copy.append(make("p", `${coachModeLabels[session.mode] || session.mode}${target ? ` · ${target}` : ""}`, "application-draft-history-name"));
    const progress = session.progress || {};
    const language = coachSessionLanguage(session);
    const interfaceCopy = coachCopy(language);
    const labels = progress.labels || {};
    const average = progress.average_score;
    copy.append(make("p", `${labels.answered_count || interfaceCopy.answered} : ${progress.answered_count || 0} · ${labels.average_score || interfaceCopy.average} : ${average ?? "—"}/100 · ${session.status === "active" ? interfaceCopy.historyActive : interfaceCopy.historyCompleted}`, "application-draft-history-meta"));
    const actions = make("div", "", "inline-actions");
    const open = make("button", session.status === "active" ? "Reprendre" : "Voir", "quiet-button");
    open.type = "button";
    open.addEventListener("click", () => openCoachSession(session.id));
    const remove = make("button", "Supprimer", "danger-button");
    remove.type = "button";
    remove.addEventListener("click", () => deleteCoachSession(session));
    actions.append(open, remove);
    item.append(copy, actions);
    elements.coachHistory.append(item);
  });
}

async function loadCoach() {
  try {
    const [sessionsPayload, jobsPayload] = await Promise.all([
      api("/api/career/interview-sessions"),
      api("/api/career/jobs"),
    ]);
    state.coachSessions = sessionsPayload.interview_sessions || [];
    renderCoachHistory();
    renderCoachJobOptions(jobsPayload.jobs || []);
    const current = state.activeCoachSession && state.coachSessions.find((session) => session.id === state.activeCoachSession.id);
    if (!current) {
      state.activeCoachSession = null;
      const active = state.coachSessions.find((session) => session.status === "active");
      if (active) await openCoachSession(active.id);
      else renderCoachSession(null);
    }
  } catch (error) { setMessage(error.message, true); }
}

async function openCoachSession(sessionId) {
  try {
    renderCoachSession(await api(`/api/career/interview-sessions/${encodeURIComponent(sessionId)}`));
    reveal(elements.coachSession);
  } catch (error) { setMessage(error.message, true); }
}

async function deleteCoachSession(session) {
  if (!window.confirm("Supprimer définitivement cette séance locale et ses réponses ?")) return;
  try {
    await api(`/api/career/interview-sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
    if (state.activeCoachSession?.id === session.id) {
      state.activeCoachSession = null;
      elements.coachSession.hidden = true;
    }
    setMessage("Séance d’entretien supprimée localement.");
    await loadCoach();
  } catch (error) { setMessage(error.message, true); }
}

const draftLanguageLabels = { fr: "Français", en: "English", it: "Italiano", de: "Deutsch" };

function renderStudioJobOptions(jobs) {
  const current = elements.applicationDraftJob.value;
  elements.applicationDraftJob.replaceChildren(new Option("Choisir une offre…", ""));
  jobs.forEach((job) => {
    const location = [job.city, job.country].filter(Boolean).join(", ");
    elements.applicationDraftJob.append(new Option(`${job.company} — ${job.title}${location ? ` (${location})` : ""}`, job.id));
  });
  if (state.pendingStudioJob && !jobs.some((job) => job.id === state.pendingStudioJob.id)) {
    elements.applicationDraftJob.append(new Option(`${state.pendingStudioJob.company} — ${state.pendingStudioJob.title}`, state.pendingStudioJob.id));
  }
  const selected = state.pendingStudioJob?.id || current || loadStudioPrefill().job_id;
  if ([...elements.applicationDraftJob.options].some((option) => option.value === selected)) {
    elements.applicationDraftJob.value = selected;
  }
  const prefill = loadStudioPrefill();
  if (["fr", "en", "it", "de"].includes(state.pendingStudioLanguage)) {
    elements.applicationDraftLanguage.value = state.pendingStudioLanguage;
  } else if (prefill.language) {
    elements.applicationDraftLanguage.value = prefill.language;
  }
  const restoredFromStorage = !current && !state.pendingStudioJob && prefill.job_id && [...elements.applicationDraftJob.options].some((option) => option.value === selected);
  if (restoredFromStorage) {
    elements.applicationDraftMode.value = "local";
    elements.applicationDraftConsent.checked = false;
    updateDraftModeUI();
  }
}

function openStudioForJob(job, language = "") {
  state.pendingStudioJob = job;
  state.pendingStudioLanguage = ["fr", "en", "it", "de"].includes(language) ? language : "";
  elements.applicationDraftMode.value = "local";
  elements.applicationDraftConsent.checked = false;
  if (typeof saveStudioPrefill === "function") saveStudioPrefill(job, state.pendingStudioLanguage, "local");
  updateDraftModeUI();
  showView("studio");
}

function renderDraftHistory() {
  elements.applicationDraftHistory.replaceChildren();
  elements.applicationDraftHistoryEmpty.hidden = state.applicationDrafts.length > 0;
  state.applicationDrafts.forEach((draft) => {
    const item = make("article", "", "application-draft-history-item");
    const copy = make("div", "", "application-draft-history-copy");
    copy.append(make("p", `${draft.company} — ${draft.title}`, "application-draft-history-name"));
    const mode = draft.generation_mode === "ai" ? `IA · ${draft.provider}` : "gabarit local";
    copy.append(make("p", `${draftLanguageLabels[draft.language] || draft.language} · ${mode} · ${new Date(draft.created_at).toLocaleString("fr-FR")}`, "application-draft-history-meta"));
    const actions = make("div", "", "inline-actions");
    const open = make("button", "Ouvrir", "quiet-button");
    open.type = "button";
    open.addEventListener("click", () => openApplicationDraft(draft.id));
    const remove = make("button", "Supprimer", "danger-button");
    remove.type = "button";
    remove.addEventListener("click", () => deleteApplicationDraft(draft));
    actions.append(open, remove);
    item.append(copy, actions);
    elements.applicationDraftHistory.append(item);
  });
}

function draftDownloadLink(draft, kind, exportFormat) {
  const labels = {
    html: "Télécharger HTML",
    md: "Télécharger Markdown",
    docx: "Télécharger Word",
    pdf: "Télécharger PDF",
  };
  const label = labels[exportFormat] || "Télécharger";
  const link = make("a", label, "secondary-button link-button");
  link.href = `/api/career/application-drafts/${encodeURIComponent(draft.id)}/download/${kind}/${exportFormat}`;
  link.download = "";
  link.setAttribute("aria-label", `${label} du ${kind === "cv" ? "CV" : "la lettre de motivation"}`);
  return link;
}

function renderApplicationDraft(draft) {
  state.activeApplicationDraft = draft;
  elements.applicationDraftPreview.hidden = false;
  elements.applicationDraftPreviewTitle.textContent = `${draft.company} — ${draft.title}`;
  const mode = draft.generation_mode === "ai" ? `amélioré par ${draft.provider}` : "gabarit local factuel";
  elements.applicationDraftMeta.textContent = `${draftLanguageLabels[draft.language] || draft.language} · ${mode}. Relis et corrige le contenu avant toute utilisation : Côme AI ne soumet aucune candidature.`;
  elements.applicationDraftChecks.replaceChildren();
  (draft.checks || []).forEach((check) => elements.applicationDraftChecks.append(make("p", check, "draft-check")));
  elements.applicationDraftCv.textContent = draft.cv_markdown || "";
  elements.applicationDraftLetter.textContent = draft.letter_markdown || "";
  elements.applicationDraftCvDownloads.replaceChildren(draftDownloadLink(draft, "cv", "docx"), draftDownloadLink(draft, "cv", "pdf"), draftDownloadLink(draft, "cv", "html"), draftDownloadLink(draft, "cv", "md"));
  elements.applicationDraftLetterDownloads.replaceChildren(draftDownloadLink(draft, "letter", "docx"), draftDownloadLink(draft, "letter", "pdf"), draftDownloadLink(draft, "letter", "html"), draftDownloadLink(draft, "letter", "md"));
  reveal(elements.applicationDraftPreview);
}

async function loadApplicationDrafts() {
  const payload = await api("/api/career/application-drafts");
  state.applicationDrafts = payload.application_drafts || [];
  renderDraftHistory();
}

async function openApplicationDraft(draftId) {
  try {
    renderApplicationDraft(await api(`/api/career/application-drafts/${encodeURIComponent(draftId)}`));
  } catch (error) { setMessage(error.message, true); }
}

async function deleteApplicationDraft(draft) {
  if (!window.confirm(`Supprimer définitivement ce brouillon pour ${draft.company} — ${draft.title} ?`)) return;
  try {
    await api(`/api/career/application-drafts/${encodeURIComponent(draft.id)}`, { method: "DELETE" });
    if (state.activeApplicationDraft?.id === draft.id) {
      state.activeApplicationDraft = null;
      elements.applicationDraftPreview.hidden = true;
    }
    setMessage("Brouillon de candidature supprimé localement.");
    await loadApplicationDrafts();
  } catch (error) { setMessage(error.message, true); }
}

function updateDraftModeUI() {
  const ai = elements.applicationDraftMode.value === "ai";
  elements.applicationDraftConsentRow.hidden = !ai;
  elements.applicationDraftConsent.required = ai;
  if (!ai) elements.applicationDraftConsent.checked = false;
}

async function loadStudio() {
  try {
    const [jobsPayload] = await Promise.all([
      api("/api/career/jobs"),
      loadApplicationDrafts(),
    ]);
    state.studioJobs = jobsPayload.jobs || [];
    renderStudioJobOptions(state.studioJobs);
    updateDraftModeUI();
  } catch (error) { setMessage(error.message, true); }
}

async function approveApplication(application, explicitlyApproved = false) {
  if (!explicitlyApproved) {
    setMessage("Coche d’abord l’approbation explicite pour cette offre uniquement.", true);
    return;
  }
  try {
    await api(`/api/career/applications/${encodeURIComponent(application.id)}/approve`, { method: "POST", body: JSON.stringify({ approved: true, note: "Approbation explicite dans l’interface locale" }) });
    setMessage("Dépôt manuel approuvé pour cette offre uniquement. Rien n’a été envoyé.");
    await Promise.all([loadApplications(), refreshStageHunterIfVisible()]);
  } catch (error) { setMessage(error.message, true); }
}

async function confirmReceipt(application, reference = "") {
  const confirmationReference = reference.trim();
  if (confirmationReference.length < 2 || confirmationReference.length > 1000) {
    setMessage("Indique une référence de réception réelle (2 à 1 000 caractères).", true);
    return;
  }
  try {
    await api(`/api/career/applications/${encodeURIComponent(application.id)}/confirm-receipt`, { method: "POST", body: JSON.stringify({ confirmation_reference: confirmationReference }) });
    setMessage("Réception confirmée dans le suivi local. Aucun envoi n’a été effectué par Côme AI.");
    await Promise.all([loadApplications(), loadDashboard(), refreshStageHunterIfVisible()]);
  } catch (error) { setMessage(error.message, true); }
}

async function markReceiptUnknown(application, note = "") {
  try {
    await api(`/api/career/applications/${encodeURIComponent(application.id)}/receipt-unknown`, { method: "POST", body: JSON.stringify({ note }) });
    setMessage("Réception marquée inconnue. Career Agent ne renverra aucune candidature automatiquement.");
    await Promise.all([loadApplications(), loadDashboard(), refreshStageHunterIfVisible()]);
  } catch (error) { setMessage(error.message, true); }
}

// ---------------------------------------------------------------------------
// Kit de candidature local (CVBOOST-05)
//
// Prérempli depuis l'offre enregistrée : CV adapté, lettre, motivation courte,
// disponibilité et champs à copier-coller (titre, entreprise, référence, URL
// officielle). Tout texte reste modifiable avant export ; la copie presse-
// papiers n'a lieu qu'après un clic explicite ; l'envoi reste strictement
// manuel et aucune route d'envoi n'existe côté serveur.
// ---------------------------------------------------------------------------

function copyKitValue(value, statusNode) {
  const text = String(value || "");
  if (!text) {
    if (statusNode) statusNode.textContent = "Rien à copier : ce champ est à compléter.";
    return;
  }
  if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
    if (statusNode) statusNode.textContent = "Copie indisponible (CSP ou navigateur) : sélectionne le texte et copie-le avec Ctrl/Cmd+C.";
    return;
  }
  navigator.clipboard.writeText(text).then(() => {
    if (statusNode) statusNode.textContent = "Copié.";
  }, () => {
    if (statusNode) statusNode.textContent = "Copie refusée par le navigateur : sélectionne le texte et copie-le manuellement.";
  });
}

function kitFactRow(labelKey, value, missingLabel) {
  const labels = {
    title: "Poste",
    company: "Entreprise",
    reference: "Référence offre",
    official_url: "URL officielle",
    deadline_date: "Date limite",
  };
  const display = value || missingLabel || "À compléter";
  const row = make("div", "", "application-kit-fact");
  row.append(
    make("span", labels[labelKey] || labelKey, "application-kit-fact-label"),
    make("code", display, "application-kit-fact-value"),
  );
  const status = make("span", "", "kit-copy-status");
  const copy = make("button", "Copier", "quiet-button");
  copy.type = "button";
  copy.setAttribute("aria-label", `Copier ${labels[labelKey] || labelKey}`);
  // La copie n'a lieu qu'après ce clic utilisateur explicite : jamais au
  // chargement de la vue, jamais en boucle.
  copy.addEventListener("click", () => copyKitValue(value, status));
  row.append(copy, status);
  return row;
}

function kitTextEditor(label, currentValue, maxLength, onSave) {
  const form = make("form", "", "application-kit-editor");
  const textLabel = make("label", label);
  const textarea = document.createElement("textarea");
  textarea.rows = label.startsWith("Motivation") ? 8 : 3;
  textarea.maxLength = maxLength;
  textarea.value = currentValue;
  textLabel.append(textarea);
  const actions = make("div", "", "inline-actions");
  const status = make("span", "", "kit-copy-status");
  const save = make("button", "Enregistrer ce texte", "secondary-button");
  save.type = "submit";
  actions.append(save, status);
  form.append(textLabel, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = textarea.value.trim();
    if (!value) {
      status.textContent = "Le texte est vide : rien à enregistrer.";
      return;
    }
    save.disabled = true;
    try {
      await onSave(value);
      status.textContent = "Enregistré localement (les versions précédentes restent dans l’historique du suivi).";
    } catch (error) {
      status.textContent = "";
      setMessage(error.message, true);
    } finally {
      save.disabled = false;
    }
  });
  return form;
}

const KIT_TEXT_LIMITS = { motivation_short: 1200, availability: 400 };

async function saveKitTexts(application, patch, statusNode) {
  await api(`/api/career/applications/${encodeURIComponent(application.id)}/kit`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (statusNode) statusNode.textContent = "Enregistré localement.";
}

function renderApplicationKit(kit, container) {
  container.replaceChildren();
  container.hidden = false;
  const application = kit.application || {};
  container.append(make("h4", "Kit de candidature local", "kit-heading"));
  container.append(make("p", `${kit.disclaimer || ""}`, "application-kit-disclaimer"));

  const stageLine = make("p", "", "application-meta");
  stageLine.textContent = `Suivi : ${stageLabels[application.stage] || application.stage} · réception : ${application.receipt_status === "confirmed" ? "confirmée" : application.receipt_status === "unknown" ? "inconnue" : "non déclarée"}.`;
  container.append(stageLine);

  const facts = kit.job || {};
  const factsBlock = make("div", "", "application-kit-facts");
  [
    ["title", facts.title],
    ["company", facts.company],
    ["reference", facts.reference],
    ["official_url", facts.official_url],
    ["deadline_date", facts.deadline_date],
  ].forEach(([key, value]) => factsBlock.append(kitFactRow(key, value, "À compléter (voir l’offre officielle)")));
  if (facts.official_url) {
    const link = make("a", "Ouvrir l’offre officielle conservée", "secondary-button external-link");
    link.href = facts.official_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const linkRow = make("div", "", "application-kit-fact");
    linkRow.append(link);
    factsBlock.append(linkRow);
  }
  container.append(factsBlock);

  const documents = make("section", "", "application-kit-documents");
  documents.append(make("h5", "Documents du kit", "kit-subheading"));
  const draft = kit.draft;
  if (draft) {
    const meta = make("p", "", "application-meta");
    const mode = draft.generation_mode === "ai" ? `amélioré par ${draft.provider}` : "gabarit local factuel";
    meta.textContent = `Dossier en ${draftLanguageLabels[draft.language] || draft.language} · ${mode} · créé le ${new Date(draft.created_at).toLocaleString("fr-FR")}.`;
    documents.append(meta);
    const cvLabel = make("label", "CV adapté (modifiable avant export)");
    const cvArea = document.createElement("textarea");
    cvArea.rows = 12;
    cvArea.maxLength = 18000;
    cvArea.value = draft.cv_markdown || "";
    cvLabel.append(cvArea);
    const letterLabel = make("label", "Lettre de motivation (modifiable avant export)");
    const letterArea = document.createElement("textarea");
    letterArea.rows = 12;
    letterArea.maxLength = 18000;
    letterArea.value = draft.letter_markdown || "";
    letterLabel.append(letterArea);
    const draftActions = make("div", "", "inline-actions");
    const saveDraft = make("button", "Enregistrer les corrections du dossier", "secondary-button");
    saveDraft.type = "button";
    const draftStatus = make("span", "", "kit-copy-status");
    saveDraft.addEventListener("click", async () => {
      if (!cvArea.value.trim() || !letterArea.value.trim()) {
        draftStatus.textContent = "Le CV et la lettre ne peuvent pas être vides.";
        return;
      }
      saveDraft.disabled = true;
      try {
        await api(`/api/career/application-drafts/${encodeURIComponent(draft.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ cv_markdown: cvArea.value, letter_markdown: letterArea.value }),
        });
        draftStatus.textContent = "Corrections enregistrées localement ; les exports utilisent cette version relue.";
      } catch (error) {
        draftStatus.textContent = "";
        setMessage(error.message, true);
      } finally {
        saveDraft.disabled = false;
      }
    });
    draftActions.append(saveDraft, draftStatus);
    documents.append(cvLabel, letterLabel, draftActions);
    const downloads = make("div", "", "inline-actions");
    downloads.append(
      draftDownloadLink(draft, "cv", "docx"),
      draftDownloadLink(draft, "cv", "pdf"),
      draftDownloadLink(draft, "letter", "docx"),
      draftDownloadLink(draft, "letter", "pdf"),
    );
    documents.append(downloads);
    const targetedArtifacts = kit.artifacts || {};
    if (Object.keys(targetedArtifacts).length) {
      const artifactList = make("ul", "", "job-reasons variant-specific");
      [
        ["cv", "CV ciblé DOCX"],
        ["cover_letter", "Lettre ciblée DOCX"],
        ["prep_sheet", "Fiche de préparation"],
      ].forEach(([key, label]) => {
        if (targetedArtifacts[key]) {
          artifactList.append(make("li", `${label} — ${targetedArtifacts[key]}`));
        }
      });
      documents.append(
        make("p", `Variante générée : ${kit.variant_label || kit.variant}`, "application-meta"),
        artifactList,
      );
    }
  } else {
    documents.append(make("p", "Aucun dossier local n’est encore rattaché à ce suivi.", "application-meta"));
    const create = make("button", "Créer le dossier local (CV + lettre)", "secondary-button");
    create.type = "button";
    create.addEventListener("click", async () => {
      create.disabled = true;
      try {
        const refreshed = await api("/api/career/application-kits", {
          method: "POST",
          body: JSON.stringify({ job_id: application.job_id, language: kit.language || "fr" }),
        });
        renderApplicationKit(refreshed, container);
        setMessage("Dossier local créé. Relis-le avant tout usage : l’envoi reste manuel.");
      } catch (error) {
        setMessage(error.message, true);
      } finally {
        create.disabled = false;
      }
    });
    documents.append(create);
  }
  container.append(documents);

  const texts = kit.kit_texts || {};
  const textsBlock = make("section", "", "application-kit-texts");
  textsBlock.append(make("h5", "Réponses types (à relire avant usage)", "kit-subheading"));
  textsBlock.append(kitTextEditor(
    "Motivation courte",
    texts.motivation_short || "",
    KIT_TEXT_LIMITS.motivation_short,
    (value) => saveKitTexts(application, { motivation_short: value }),
  ));
  textsBlock.append(kitTextEditor(
    "Disponibilité",
    texts.availability || "",
    KIT_TEXT_LIMITS.availability,
    (value) => saveKitTexts(application, { availability: value }),
  ));
  container.append(textsBlock);

  const factChecks = kit.fact_checks || {};
  const warnings = make("section", "", "application-kit-checks");
  warnings.append(make("h5", "Vérificateur de faits local", "kit-subheading"));
  const placeholderList = make("ul", "", "job-reasons");
  (factChecks.placeholders || []).forEach((marker) => placeholderList.append(make("li", `À compléter avant usage : ${marker}`)));
  (factChecks.unverified_requirements || []).forEach((item) => {
    placeholderList.append(make("li", `${item.requirement} — ${item.note}`));
  });
  if (placeholderList.children.length) warnings.append(placeholderList);
  else warnings.append(make("p", "Aucun marqueur ouvert : le kit ne contient plus de champ à compléter signalé automatiquement.", "application-meta"));
  const checksList = make("ul", "", "job-reasons blocked-list");
  (kit.checks || []).forEach((line) => checksList.append(make("li", line)));
  warnings.append(checksList);
  if (placeholderList.children.length) {
    const profileAction = make("button", "Ajouter preuve au profil", "secondary-button");
    profileAction.type = "button";
    profileAction.addEventListener("click", () => showView("profile"));
    warnings.append(profileAction);
  }
  container.append(warnings);
}

async function openApplicationKit(application, container) {
  if (!container) return;
  container.textContent = "Chargement du kit local…";
  container.hidden = false;
  try {
    const kit = await api(`/api/career/applications/${encodeURIComponent(application.id)}/kit`);
    renderApplicationKit(kit, container);
  } catch (error) {
    container.hidden = true;
    setMessage(error.message, true);
  }
}

async function showKitInApplications(kit) {
  // Le kit est rouvert (avec des données fraîches) après chaque rendu de la
  // liste des candidatures tant que l'utilisateur reste sur cette vue : un
  // rechargement ou une mise à jour du suivi ne referme pas le kit ouvert.
  state.pendingKitApplicationId = kit.application?.id || "";
  showView("applications");
  await loadApplications();
}

async function startApplicationKitFlow(jobId, language, variant = "") {
  try {
    const kit = await api("/api/career/application-kits", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, language, variant }),
    });
    setMessage("Kit de candidature prêt localement. L’envoi reste strictement manuel.");
    await showKitInApplications(kit);
  } catch (error) { setMessage(error.message, true); }
}

async function consumePendingKit() {
  const applicationId = state.pendingKitApplicationId;
  if (!applicationId) return;
  const target = elements.applications.querySelector(
    `.application-kit[data-application-id="${CSS.escape(applicationId)}"]`
  );
  if (target) {
    await openApplicationKit({ id: applicationId }, target);
    reveal(target, "start");
  }
}


elements.profileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/career/profile", { method: "PUT", body: JSON.stringify(formObject(elements.profileForm)) });
    setMessage("Profil enregistré localement.");
  } catch (error) { setMessage(error.message, true); }
});

elements.profileDocumentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const fileInput = $("#profile-document-file");
  if (!fileInput.files?.length) {
    setMessage("Choisis un PDF, DOCX, TXT ou fichier Markdown avant de l’importer.", true);
    return;
  }
  const submit = $("#profile-document-submit");
  submit.disabled = true;
  submit.textContent = "Lecture locale en cours…";
  try {
    const profileImport = await api("/api/career/profile-imports", {
      method: "POST",
      body: new FormData(elements.profileDocumentForm),
    });
    elements.profileDocumentForm.reset();
    renderProfileImportDraft(profileImport);
    setMessage(profileImport.duplicate ? "Ce document était déjà présent : son brouillon local a été rouvert." : "Document lu localement. Vérifie les propositions avant de les appliquer.");
    await loadProfileImports();
  } catch (error) { setMessage(error.message, true); }
  finally {
    submit.disabled = false;
    submit.textContent = "Lire localement et préparer la relecture";
  }
});

elements.profileTextForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("#profile-text-value").value.trim();
  if (!text) {
    setMessage("Colle le texte de ton profil avant de l’importer.", true);
    return;
  }
  const submit = $("#profile-text-submit");
  submit.disabled = true;
  submit.textContent = "Préparation locale…";
  try {
    const profileImport = await api("/api/career/profile-imports/text", {
      method: "POST",
      body: JSON.stringify({ source_kind: "linkedin_text", text, original_name: "texte-profil-linkedin" }),
    });
    elements.profileTextForm.reset();
    renderProfileImportDraft(profileImport);
    setMessage(profileImport.duplicate ? "Ce texte était déjà présent : son brouillon local a été rouvert." : "Texte préparé localement. Vérifie les propositions avant de les appliquer.");
    await loadProfileImports();
  } catch (error) { setMessage(error.message, true); }
  finally {
    submit.disabled = false;
    submit.textContent = "Préparer la relecture du texte";
  }
});

elements.intakeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const answer = elements.intakeAnswer.value.trim();
  if (!answer) {
    setMessage("Écris une réponse avant de continuer le mini-entretien Career.", true);
    return;
  }
  elements.intakeSubmit.disabled = true;
  try {
    renderIntake(await api("/api/career/intake/answers", { method: "POST", body: JSON.stringify({ answer }) }));
    elements.intakeAnswer.value = "";
    setMessage("Réponse Career enregistrée localement.");
  } catch (error) { setMessage(error.message, true); }
  finally { if (!state.intake?.completed) elements.intakeSubmit.disabled = false; }
});

$("#reset-career-intake").addEventListener("click", async () => {
  if (!window.confirm("Recommencer le mini-entretien et effacer ses réponses locales ?")) return;
  try {
    renderIntake(await api("/api/career/intake", { method: "DELETE" }));
    setMessage("Mini-entretien Career réinitialisé localement.");
  } catch (error) { setMessage(error.message, true); }
});

elements.applicationDraftMode.addEventListener("change", updateDraftModeUI);

/* CVBOOST-03 : la préselection du Studio (offre, langue, gabarit local) reste
   valable après un rechargement. Rien concernant le mode IA n'est persisté, et
   le consentement cloud n'est jamais réactivé automatiquement. */
elements.applicationDraftJob.addEventListener("change", () => {
  const selectedJob = state.studioJobs.find((job) => job.id === elements.applicationDraftJob.value) || { id: elements.applicationDraftJob.value, company: "", title: "" };
  if (typeof saveStudioPrefill === "function") saveStudioPrefill(selectedJob, elements.applicationDraftLanguage.value, "local");
});
elements.applicationDraftLanguage.addEventListener("change", () => {
  const selectedJob = state.studioJobs.find((job) => job.id === elements.applicationDraftJob.value) || { id: elements.applicationDraftJob.value, company: "", title: "" };
  if (typeof saveStudioPrefill === "function") saveStudioPrefill(selectedJob, elements.applicationDraftLanguage.value, "local");
});

elements.applicationDraftForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const jobId = elements.applicationDraftJob.value;
  const mode = elements.applicationDraftMode.value;
  if (!jobId) {
    setMessage("Choisis d’abord une offre enregistrée.", true);
    return;
  }
  if (mode === "ai" && !elements.applicationDraftConsent.checked) {
    setMessage("Confirme l’envoi au fournisseur IA avant d’utiliser le mode IA, ou choisis le mode local.", true);
    return;
  }
  elements.applicationDraftSubmit.disabled = true;
  elements.applicationDraftSubmit.textContent = mode === "ai" ? "Préparation IA en cours…" : "Création locale en cours…";
  try {
    const draft = await api("/api/career/application-drafts", {
      method: "POST",
      body: JSON.stringify({
        job_id: jobId,
        language: elements.applicationDraftLanguage.value,
        mode,
        consent_external: Boolean(elements.applicationDraftConsent.checked),
      }),
    });
    renderApplicationDraft(draft);
    setMessage(mode === "ai" ? "Brouillon IA créé : relis-le avant toute utilisation." : "Brouillon local créé à partir des faits enregistrés.");
    await loadApplicationDrafts();
  } catch (error) { setMessage(error.message, true); }
  finally {
    elements.applicationDraftSubmit.disabled = false;
    elements.applicationDraftSubmit.textContent = "Créer le dossier de candidature";
  }
});

$("#delete-application-draft").addEventListener("click", () => {
  if (state.activeApplicationDraft) deleteApplicationDraft(state.activeApplicationDraft);
});

elements.preferencesForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    availability: {
      availability_start: $("#availability-start").value,
      availability_end: $("#availability-end").value,
      minimum_duration_months: Number($("#duration-min").value),
      maximum_duration_months: Number($("#duration-max").value),
    },
    families: preferencePayload(elements.familyPreferences),
    locations: preferencePayload(elements.locationPreferences),
  };
  try {
    await api("/api/career/preferences", { method: "PUT", body: JSON.stringify(payload) });
    setMessage("Préférences enregistrées. Les calendriers locaux et le score de pertinence ont été recalculés.");
    await loadPreferences();
  } catch (error) { setMessage(error.message, true); }
});

elements.jobForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formObject(elements.jobForm);
  payload.duration_months = payload.duration_months ? Number(payload.duration_months) : null;
  try {
    const job = await api("/api/career/jobs/import", { method: "POST", body: JSON.stringify(payload) });
    elements.jobForm.reset();
    renderFamilyOptions();
    setMessage(job.duplicate ? "Offre déjà connue : les informations de source ont été actualisées sans créer de doublon." : "Offre enregistrée localement.");
    await Promise.all([loadDashboard(), loadJobs(), loadShortlist()]);
  } catch (error) { setMessage(error.message, true); }
});

elements.discoverySourceForm.addEventListener("submit", addDiscoverySource);
elements.discoverySearch.addEventListener("click", () => runDiscovery(false));
elements.discoveryForceSearch.addEventListener("click", () => runDiscovery(true));

elements.coachSessionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const start = $("#coach-session-start");
  start.disabled = true;
  start.textContent = "Préparation de la question…";
  try {
    const session = await api("/api/career/interview-sessions", {
      method: "POST",
      body: JSON.stringify({
        mode: elements.coachMode.value,
        difficulty: elements.coachDifficulty.value,
        language: elements.coachLanguage.value,
        job_id: elements.coachJob.value,
      }),
    });
    elements.coachAnswer.value = "";
    renderCoachSession(session);
    setMessage("Séance d’entraînement locale démarrée. Le retour porte sur cet exercice, pas sur tes chances de recrutement.");
    await Promise.all([loadCoach(), loadDashboard()]);
  } catch (error) { setMessage(error.message, true); }
  finally {
    start.disabled = false;
    start.textContent = "Commencer une séance";
  }
});

elements.coachAnswerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const session = state.activeCoachSession;
  const answer = elements.coachAnswer.value.trim();
  if (!session?.id) {
    setMessage("Commence ou rouvre une séance avant de répondre.", true);
    return;
  }
  if (!answer) {
    setMessage("Écris une réponse avant de demander le retour du coach.", true);
    return;
  }
  elements.coachAnswerSubmit.disabled = true;
  elements.coachAnswerSubmit.textContent = "Analyse locale…";
  try {
    const updated = await api(`/api/career/interview-sessions/${encodeURIComponent(session.id)}/answers`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    });
    elements.coachAnswer.value = "";
    renderCoachSession(updated);
    setMessage("Retour structuré enregistré localement. La question suivante est prête.");
    await Promise.all([loadCoach(), loadDashboard()]);
  } catch (error) { setMessage(error.message, true); }
  finally {
    if (state.activeCoachSession?.status === "active") {
      elements.coachAnswerSubmit.disabled = false;
      elements.coachAnswerSubmit.textContent = "Obtenir un retour structuré";
    }
  }
});

$("#coach-session-complete").addEventListener("click", async () => {
  const session = state.activeCoachSession;
  if (!session?.id || session.status !== "active") return;
  try {
    const completed = await api(`/api/career/interview-sessions/${encodeURIComponent(session.id)}/complete`, { method: "POST" });
    renderCoachSession(completed);
    setMessage("Séance terminée et conservée uniquement dans tes données Career locales.");
    await Promise.all([loadCoach(), loadDashboard()]);
  } catch (error) { setMessage(error.message, true); }
});

elements.filters.addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await loadJobs(); } catch (error) { setMessage(error.message, true); }
});
$("#clear-job-filters").addEventListener("click", async () => {
  $("#filter-query").value = "";
  $("#filter-family").value = "";
  $("#filter-status").value = "";
  try { await loadJobs(); } catch (error) { setMessage(error.message, true); }
});

$("#toggle-profile").addEventListener("click", () => {
  const panel = $(".profile-panel");
  const form = $("#profile-form");
  const hidden = !form.hidden;
  form.hidden = hidden;
  [
    panel.querySelector(".profile-import-details"),
    panel.querySelector(".profile-import-history"),
    panel.querySelector(".career-intake-details"),
  ].filter(Boolean).forEach((section) => { section.hidden = hidden; });
  elements.profileImportReview.hidden = hidden || !state.activeProfileImport;
  $("#toggle-profile").textContent = hidden ? "Développer" : "Réduire";
  $("#toggle-profile").setAttribute("aria-expanded", String(!hidden));
});

$("#close-profile-import-review").addEventListener("click", () => {
  state.activeProfileImport = null;
  elements.profileImportReview.hidden = true;
});

$("#delete-career-data").addEventListener("click", async () => {
  const confirmation = window.prompt("Pour supprimer uniquement les données Career locales, tape exactement : SUPPRIMER MES DONNÉES CAREER");
  if (!confirmation) return;
  try {
    await api("/api/career/data", { method: "DELETE", body: JSON.stringify({ confirmation }) });
    setMessage("Les données Career ont été supprimées. Les fichiers d’analyse Côme AI sont restés intacts.");
    await bootstrap();
  } catch (error) { setMessage(error.message, true); }
});

// ------------------------------------------------------------------
// Stage Hunter: the person's own search brief, the explainable ranking of
// stored offers, and the factual preparation panel. All logic stays on the
// server: this view only displays what the local Career endpoints return.
// ------------------------------------------------------------------

function stageHunterListValue(selector) {
  const element = $(selector);
  return element ? element.value.split(/[,;\n]/).map((item) => item.trim()).filter(Boolean) : [];
}

function renderStageBrief(payload) {
  const brief = payload.brief || {};
  const domainsTarget = $("#stagehunter-domains");
  const contractsTarget = $("#stagehunter-contract-types");
  const monthsTarget = $("#stagehunter-start-months");
  const rankingTarget = $("#stagehunter-ranking");
  if (!domainsTarget || !contractsTarget || !monthsTarget || !rankingTarget) return;
  domainsTarget.replaceChildren();
  (payload.vocabulary?.domains || []).forEach((domain) => {
    const label = make("label", "", "stagehunter-domain");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = domain;
    box.checked = (brief.domains || []).includes(domain);
    label.append(box, document.createTextNode(domain));
    domainsTarget.append(label);
  });
  contractsTarget.replaceChildren();
  (payload.vocabulary?.contract_types || []).forEach((contract) => {
    const label = make("label", "", "stagehunter-domain");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = contract.key;
    box.checked = (brief.contract_types || []).includes(contract.key);
    label.append(box, document.createTextNode(contract.label));
    contractsTarget.append(label);
  });
  monthsTarget.replaceChildren();
  (payload.vocabulary?.months || []).forEach((month) => {
    const label = make("label", "", "stagehunter-domain");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = String(month.value);
    box.checked = (brief.start_months || []).includes(month.value);
    label.append(box, document.createTextNode(month.label));
    monthsTarget.append(label);
  });
  $("#stagehunter-quarter-one").checked = [1, 2, 3].every((month) => (brief.start_months || []).includes(month));
  $("#stagehunter-quarter-one").onchange = (event) => {
    monthsTarget.querySelectorAll("input").forEach((box) => {
      if (["1", "2", "3"].includes(box.value)) box.checked = event.target.checked;
    });
  };
  monthsTarget.querySelectorAll("input").forEach((box) => {
    box.onchange = () => {
      $("#stagehunter-quarter-one").checked = ["1", "2", "3"].every((month) =>
        [...monthsTarget.querySelectorAll("input")].some((input) => input.value === String(month) && input.checked));
    };
  });
  $("#stagehunter-min-stage-duration").value = brief.minimum_stage_duration_months ?? 6;
  $("#stagehunter-other-domains").value = (brief.other_domains || []).join(", ");
  $("#stagehunter-roles").value = (brief.roles || []).join(", ");
  $("#stagehunter-countries").value = (brief.countries || []).join(", ");
  $("#stagehunter-cities").value = (brief.cities || []).join(", ");
  $("#stagehunter-excluded-countries").value = (brief.excluded_countries || ["France"]).join(", ");
  $("#stagehunter-excluded-cities").value = (brief.excluded_cities || ["Paris"]).join(", ");
  $("#stagehunter-require-known-location").checked = brief.require_known_location !== false;
  $("#stagehunter-level").value = brief.study_level || "";
  $("#stagehunter-education-preference").value = brief.education_preference || "bachelor_m1_then_m2";
  $("#stagehunter-languages").value = (brief.languages || []).join(", ");
  $("#stagehunter-constraints").value = brief.constraints || "";
  rankingTarget.replaceChildren();
  (payload.vocabulary?.ranking_criteria || []).forEach((criterion) => {
    const label = make("label", "", "stagehunter-weight");
    label.append(document.createTextNode(criterion.label));
    const input = document.createElement("input");
    input.type = "number";
    input.min = String(payload.vocabulary?.ranking_min ?? 0.5);
    input.max = String(payload.vocabulary?.ranking_max ?? 2);
    input.step = "0.1";
    input.value = String(brief.ranking?.[criterion.key] ?? 1);
    input.dataset.criterion = criterion.key;
    label.append(input);
    rankingTarget.append(label);
  });
  $("#stagehunter-brief-note").textContent = payload.stored_brief_invalid
    ? "Tes critères enregistrés n’ont pas pu être relus (vocabulaire ou format devenu invalide) : le formulaire est reparti vide. Enregistre-les à nouveau pour corriger."
    : payload.disclaimer || "";
}

function renderStageTerms(payload) {
  const target = $("#stagehunter-terms");
  if (!target) return;
  target.replaceChildren();
  const terms = payload.search_terms || [];
  if (!terms.length) {
    target.append(make("p", "Sélectionne des domaines à l’étape A pour afficher des termes de recherche suggérés.", "fixed-period-note"));
    return;
  }
  terms.forEach((entry) => {
    const block = make("div", "", "stagehunter-terms-block");
    block.append(make("strong", entry.domain));
    const list = make("ul", "", "job-reasons");
    (entry.terms || []).forEach((term) => list.append(make("li", term)));
    block.append(list);
    target.append(block);
  });
  target.append(make("p", "Ces termes sont des repères locaux pour tes recherches manuelles sur les sites officiels : aucune requête n’est envoyée depuis ici.", "fixed-period-note"));
}

function formatStageDate(value) {
  if (!value) return "À vérifier";
  const text = String(value).trim();
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(text) ? `${text}T12:00:00Z` : text;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return text;
  return parsed.toLocaleDateString("fr-FR", {day:"numeric", month:"short", year:"numeric", timeZone:"UTC"});
}

function stageContractLabel(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  return {
    internship: "Stage", stage: "Stage", intern: "Stage",
    fixed_term: "CDD", cdd: "CDD", fixed_term_contract: "CDD",
    permanent: "CDI", cdi: "CDI", permanent_contract: "CDI",
    vie: "VIE", v_i_e: "VIE",
    apprenticeship: "Alternance — hors critères", alternance: "Alternance — hors critères",
    ambiguous: "À vérifier", unknown: "À vérifier",
  }[normalized] || (value ? String(value) : "À vérifier");
}

function stageOfferFactValue(job, qualification, key) {
  const facts = qualification && Object.keys(qualification).length
    ? qualification : (job.qualification_facts || {});
  if (key === "contract") return stageContractLabel(facts.contract_type || job.employment_type);
  if (key === "location") return [job.city || facts.city, job.country || facts.country].filter(Boolean).join(", ") || "À vérifier";
  if (key === "publication") return formatStageDate(job.posted_date || facts.posted_date);
  if (key === "start") {
    if (job.start_date || facts.start_date) return formatStageDate(job.start_date || facts.start_date);
    if (Number.isInteger(facts.start_month) && facts.start_month >= 1 && facts.start_month <= 12) {
      const month = new Date(Date.UTC(2000, facts.start_month - 1, 1)).toLocaleDateString("fr-FR", {month:"long", timeZone:"UTC"});
      return `${month} · année à vérifier`;
    }
    return "À vérifier";
  }
  if (key === "end") return formatStageDate(job.end_date || facts.end_date);
  if (key === "duration") {
    if (Number.isFinite(Number(job.duration_months)) && Number(job.duration_months) > 0) return `${Number(job.duration_months)} mois`;
    const minimum = Number(facts.duration_min_months);
    const maximum = Number(facts.duration_max_months);
    if (Number.isFinite(minimum) && minimum > 0) {
      return Number.isFinite(maximum) && maximum > 0 && maximum !== minimum
        ? `${minimum} à ${maximum} mois` : `${minimum} mois`;
    }
    return "À vérifier";
  }
  if (key === "deadline") return formatStageDate(job.deadline_date);
  if (key === "language") return job.languages_required || facts.language || "À vérifier";
  return "À vérifier";
}

function stageRequirementSnippets(job) {
  const source = [job.requirements, job.languages_required, job.eligibility_requirement]
    .filter(Boolean).join("\n");
  if (!source) return [];
  return [...new Set(source.split(/\n+|[;•]+/).map((item) => item.trim()).filter(Boolean))].slice(0, 4);
}

function stageOfferOverview(job, qualification) {
  const panel = make("section", "", "stage-offer-overview");
  const factDefinitions = [
    ["Contrat", "contract", "briefcase"], ["Localisation", "location", "pin"],
    ["Publication", "publication", "calendar"], ["Début", "start", "play"],
    ["Fin", "end", "finish"], ["Durée", "duration", "clock"],
    ["Candidater avant", "deadline", "deadline"], ["Langue", "language", "language"],
  ];
  const grid = make("dl", "", "stage-offer-facts");
  const missing = [];
  factDefinitions.forEach(([label, key, icon]) => {
    const value = stageOfferFactValue(job, qualification, key);
    const fact = make("div", "", `stage-offer-fact${value === "À vérifier" ? " is-missing" : ""}`);
    fact.dataset.icon = icon;
    fact.append(make("dt", label), make("dd", value));
    grid.append(fact);
    if (value === "À vérifier" || value.includes("année à vérifier")) missing.push(label.toLowerCase());
  });
  panel.append(grid);

  const trust = make("div", "", "stage-offer-trust");
  if (job.official_url && job.source_name && job.source_name !== "manual") {
    trust.append(chip("Source officielle liée", "good"));
    trust.append(make("span", `${job.source_name} · vérifiée ${formatVerification(job.last_verified_at)}`));
  } else if (job.official_url) {
    trust.append(chip("Lien fourni · origine à vérifier", "warning"));
  } else {
    trust.append(chip("Lien officiel manquant", "warning"));
  }
  const knownCount = factDefinitions.length - missing.length;
  trust.append(make("span", `${knownCount}/${factDefinitions.length} informations essentielles renseignées`));
  panel.append(trust);

  const requirements = stageRequirementSnippets(job);
  if (requirements.length) {
    const block = make("div", "", "stage-offer-requirements");
    block.append(make("strong", "Prérequis repérés dans l’offre"));
    const list = make("ul");
    requirements.forEach((item) => list.append(make("li", item)));
    block.append(list);
    panel.append(block);
  }
  if (missing.length) {
    panel.append(make("p", `Informations manquantes : ${missing.join(", ")}. Elles restent à vérifier et ne sont jamais inventées.`, "stage-offer-missing"));
  }
  return panel;
}

function renderStageResultSummary(matches) {
  const target = $("#stagehunter-result-summary");
  if (!target) return;
  target.replaceChildren();
  const counts = {conforming:0, to_verify:0, non_conforming:0, sourced:0};
  matches.forEach((match) => {
    const status = (match.stage_match || match.qualification || {}).qualification_status
      || (match.qualification || {}).target_status || "to_verify";
    counts[status] = (counts[status] || 0) + 1;
    if (match.job?.official_url && match.job?.source_name && match.job.source_name !== "manual") counts.sourced += 1;
  });
  const items = [
    [matches.length, "offres affichées", ""], [counts.conforming, "conformes", "good"],
    [counts.to_verify, "à vérifier", "warning"], [counts.non_conforming, "non conformes", "danger"],
    [counts.sourced, "avec source officielle liée", ""],
  ];
  items.forEach(([value, label, tone]) => {
    const item = make("div", "", `stagehunter-summary-item${tone ? ` ${tone}` : ""}`);
    item.append(make("strong", String(value)), make("span", label));
    target.append(item);
  });
  target.hidden = matches.length === 0;
}

function stageMatchBlock(stageMatch) {
  const profileScoring = stageMatch._profileScoring || null;
  const block = make("section", "", "stage-match-block");
  const header = make("div", "", "stage-match-header");
  const scoreText = Number.isFinite(stageMatch.score) ? `${stageMatch.score}/100` : "non calculé";
  const tone = stageMatch.qualification_status === "conforming"
    && Number.isFinite(stageMatch.score) && stageMatch.score >= 70 ? "good" : "warning";
  header.append(make("p", `Pertinence selon tes critères : ${scoreText}`, "scoring-title"), chip(stageMatch.label || "", tone));
  block.append(header);
  const eligibility = {
    conforming: "Conforme à tes critères contractuels et de période",
    to_verify: "À vérifier : informations ou critères incomplets",
    non_conforming: "Non conforme à tes critères sélectionnés",
  }[stageMatch.qualification_status];
  if (eligibility) block.append(make("p", eligibility, stageMatch.qualification_status === "conforming" ? "eligibility-good" : "fixed-period-note"));
  if (profileScoring && Number.isFinite(profileScoring.score_out_of_20)) {
    const confidence = profileScoring.confidence || "à vérifier";
    block.append(make("p", `Compatibilité avec ton profil : ${profileScoring.score_out_of_20}/20 · confiance ${confidence}`, "scoring-title"));
    block.append(make("p", "Cette note compare uniquement les faits déclarés localement avec les éléments de l’offre ; elle ne prédit pas une embauche.", "scoring-disclaimer"));
  }
  const education = stageMatch.education_access;
  if (education) {
    block.append(make("p", `Niveau demandé : ${education.reason}`, "fixed-period-note"));
    (education.evidence || []).slice(0, 2).forEach((proof) =>
      block.append(make("p", `Passage source (${proof.field}) : « ${proof.passage} »`, "scoring-disclaimer")));
  }
  if (stageMatch.disclaimer) block.append(make("p", stageMatch.disclaimer, "scoring-disclaimer"));
  const good = make("ul", "", "scoring-list good-list");
  const review = make("ul", "", "scoring-list review-list");
  (stageMatch.components || []).forEach((component) => {
    const target = component.status === "match" ? good : review;
    target.append(make("li", `${component.label} : ${component.reason}`));
  });
  if (good.children.length) block.append(good);
  if (review.children.length) block.append(review);
  if ((stageMatch.warnings || []).length) {
    const warnings = make("ul", "", "scoring-list blocked-list");
    stageMatch.warnings.forEach((warning) => warnings.append(make("li", `À vérifier : ${warning}`)));
    block.append(warnings);
  }
  return block;
}

function stageMatchScore(match) {
  return Number((match.stage_match || match.qualification || {}).score ?? (match.stage_match || {}).score ?? 0);
}

function stageMatchEligibilityRank(match) {
  const status = (match.stage_match || match.qualification || {}).qualification_status
    || (match.qualification || {}).target_status;
  return {conforming: 0, to_verify: 1, non_conforming: 2}[status] ?? 1;
}

function renderStageMap(matches) {
  const map = $("#stagehunter-map");
  if (!map) return;
  map.replaceChildren();
  const counts = new Map();
  matches.forEach((match) => {
    const job = match.job || {};
    const key = [job.city, job.country].filter(Boolean).join(", ") || "Lieu non précisé";
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const title = make("p", "Carte des offres disponibles (par ville)", "stagehunter-map-title");
  map.append(title);
  const list = make("ul", "", "stagehunter-map-list");
  [...counts.entries()].sort((a, b) => b[1] - a[1]).forEach(([city, count]) => {
    list.append(make("li", `${city} : ${count} offre${count > 1 ? "s" : ""}`));
  });
  map.append(list);
}

function renderStageMatches(payload) {
  const target = $("#stagehunter-matches");
  const empty = $("#stagehunter-matches-empty");
  if (!target || !empty) return;
  target.replaceChildren();
  const matches = payload.matches || [];
  state.stageMatches = matches;
  const direction = localStorage.getItem("stagehunter_sort") || "desc";
  const sortSelect = $("#stagehunter-sort");
  if (sortSelect) sortSelect.value = direction;
  const sorted = [...matches].sort((a, b) => {
    const eligibilityDelta = stageMatchEligibilityRank(a) - stageMatchEligibilityRank(b);
    if (eligibilityDelta) return eligibilityDelta;
    return direction === "asc" ? stageMatchScore(a) - stageMatchScore(b) : stageMatchScore(b) - stageMatchScore(a);
  });
  renderStageMap(sorted);
  renderStageResultSummary(sorted);
  empty.hidden = sorted.length > 0;
  sorted.forEach((match) => {
    const wrapper = make("div", "", "stagehunter-match");
    if (match.job?.id) wrapper.dataset.jobId = match.job.id;
    if (match.stage_match || match.qualification) {
      const displayedMatch = {
        ...(match.stage_match || {
          label: "Critères par défaut", qualification_status: match.qualification.target_status,
          education_access: match.education_access,
        }),
        _profileScoring: match.job?.scoring,
      };
      wrapper.append(stageMatchBlock(displayedMatch));
    }
    const card = jobCard(match.job, "discover", match.qualification);
    card.classList.add("stagehunter-offer-card");
    const chips = card.querySelector(".job-chips");
    const qualificationFacts = {
      ...(match.job?.qualification_facts || {}),
      ...(match.qualification || {}),
    };
    chips?.after(stageOfferOverview(match.job || {}, qualificationFacts));
    const actions = card.querySelector(".job-actions");
    const prep = make("button", "Préparer cette candidature", "secondary-button");
    prep.type = "button";
    prep.addEventListener("click", () => loadStagePrep(match.job.id));
    actions?.append(prep);
    const detail = make("button", "Détail", "secondary-button");
    detail.type = "button";
    detail.addEventListener("click", () => loadStageDetail(match.job.id));
    actions?.append(detail);
    wrapper.append(card);
    target.append(wrapper);
  });
  $("#stagehunter-matches-note").textContent = payload.configured
    ? "Classement calculé localement à partir de tes critères ; chaque composante est expliquée ci-dessus."
    : "Les contrats et mois sélectionnés par défaut sont appliqués. Ajoute tes préférences à l’étape A pour affiner le classement.";
}

async function loadStageDetail(jobId) {
  const container = $("#stagehunter-detail");
  const empty = $("#stagehunter-detail-empty");
  if (!container || !empty) return;
  container.replaceChildren();
  empty.hidden = true;
  state.stageDetailIndex = state.stageMatches.findIndex((m) => m.job?.id === jobId);
  container.textContent = "Chargement…";
  // Montrer immédiatement où va le résultat : la fiche est en bas de la vue,
  // sans feedback le bouton paraît mort (surtout sur mobile).
  document.querySelectorAll(".stagehunter-match.is-selected")
    .forEach((node) => node.classList.remove("is-selected"));
  const target = document.querySelector(`.stagehunter-match[data-job-id="${CSS.escape(jobId)}"]`);
  target?.classList.add("is-selected");
  reveal(container, "start");
  try {
    const selectedMatch = state.stageMatches.find((match) => match.job?.id === jobId) || {};
    const prep = await api(`/api/career/jobs/${encodeURIComponent(jobId)}/prep`);
    container.replaceChildren();
    // The preparation endpoint deliberately exposes a bounded job subset.
    // Merge it over the already-loaded local offer so the detail view keeps
    // dates, location and qualification evidence without another fetch.
    const job = {...(selectedMatch.job || {}), ...(prep.job || {})};
    try { container.focus({ preventScroll: true }); } catch (_) { /* focus non essentiel */ }
    container.id = container.id || "stagehunter-detail";
    container.setAttribute("tabindex", "-1");
    const hero = make("header", "", "stage-detail-hero");
    const heading = make("div");
    heading.append(make("p", job.company || "Entreprise à vérifier", "stage-detail-company"));
    heading.append(make("h4", job.title || "Intitulé à vérifier"));
    heading.append(make("p", [job.city, job.country].filter(Boolean).join(", ") || "Localisation à vérifier", "stage-detail-location"));
    hero.append(heading);
    if (job.official_url) {
      const official = make("a", "Voir l’offre officielle ↗", "primary-button external-link");
      official.href = job.official_url;
      official.target = "_blank";
      official.rel = "noopener noreferrer";
      hero.append(official);
    }
    container.append(hero);
    const qualification = {
      ...(job.qualification_facts || {}),
      ...(selectedMatch.qualification || {}),
      ...(prep.qualification || {}),
    };
    container.append(stageOfferOverview(job, qualification));
    const stageMatch = prep.stage_match || selectedMatch.stage_match || {};
    if (Number.isFinite(stageMatch.score)) {
      container.append(make("p", `Pertinence calculée localement : ${stageMatch.score}/100. Cette note aide au tri et ne prédit pas une embauche.`, "detail-score-callout"));
    }
    if ((stageMatch.reasons || []).length) {
      container.append(make("p", "Pourquoi cette offre est classée ici", "scoring-title"));
      const list = make("ul", "", "detail-reasons");
      stageMatch.reasons.slice(0, 5).forEach((reason) => list.append(make("li", reason)));
      container.append(list);
    }
    if ((prep.requirements || []).length) {
      container.append(make("p", "Compétences et prérequis cités dans l’annonce", "scoring-title"));
      const requirements = make("ul", "", "detail-requirements");
      prep.requirements.slice(0, 10).forEach((item) => {
        const text = item?.text || String(item || "");
        const source = item?.source ? ` · source : ${item.source}` : "";
        requirements.append(make("li", `${text}${source}`));
      });
      container.append(requirements);
    } else {
      container.append(make("p", "Compétences et prérequis non structurés : relis l’annonce officielle avant de candidater.", "stage-offer-missing"));
    }
    // Résumé structuré (local déterministe) + IA optionnelle avec consentement.
    try {
      const summary = await api(`/api/career/jobs/${encodeURIComponent(jobId)}/summary`);
      if (summary?.missions?.length && !(prep.requirements || []).length) {
        const title = make("p", "Missions / prérequis extraits", "scoring-title");
        container.append(title);
        const list = make("ul", "", "detail-reasons");
        summary.missions.forEach((mission) => list.append(make("li", mission)));
        container.append(list);
      }
      if (summary?.ai_summary) {
        const aiTitle = make("p", "Résumé IA (consentement cloud)", "scoring-title");
        container.append(aiTitle);
        const aiBox = make("div", "", "detail-row");
        aiBox.textContent = typeof summary.ai_summary === "string" ? summary.ai_summary : JSON.stringify(summary.ai_summary);
        container.append(aiBox);
      } else if (summary?.ai_error) {
        container.append(make("p", summary.ai_error, "fixed-period-note"));
      }
      const aiButton = make("button", "Résumé IA (consentement cloud)", "secondary-button");
      aiButton.type = "button";
      aiButton.addEventListener("click", async () => {
        if (!confirm("Autoriser une transmission unique et bornée de cette offre vers le fournisseur IA configuré ?")) return;
        try {
          const aiSummary = await api(`/api/career/jobs/${encodeURIComponent(jobId)}/summary`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({mode: "ai", consent_external: true}),
          });
          const box = make("div", "", "detail-row");
          if (aiSummary?.ai_summary) {
            box.textContent = typeof aiSummary.ai_summary === "string" ? aiSummary.ai_summary : JSON.stringify(aiSummary.ai_summary);
          } else {
            box.textContent = aiSummary?.ai_error || "Résumé IA indisponible ; repli local conservé.";
          }
          container.append(make("p", "Résumé IA (consentement cloud)", "scoring-title"));
          container.append(box);
        } catch (error) {
          container.append(make("p", error?.message ? `Résumé IA indisponible : ${error.message} (repli local conservé).` : "Résumé IA indisponible ; repli local conservé.", "fixed-period-note"));
        }
      });
      container.append(aiButton);
    } catch (error) {
      // Le résumé est optionnel : la fiche reste utilisable, mais l'échec est affiché.
      container.append(make("p", error?.message ? `Extraction locale indisponible : ${error.message}` : "Extraction locale indisponible.", "fixed-period-note"));
    }
  } catch (error) {
    container.replaceChildren();
    container.textContent = error.message || "Impossible de charger la fiche.";
  }

}

function renderStagePrepSelect() {
  const select = $("#stagehunter-prep-job");
  if (!select) return;
  const current = select.value;
  select.replaceChildren(new Option("Choisir une offre…", ""));
  (state.jobs || []).forEach((job) => select.append(new Option(`${job.title} — ${job.company}`, job.id)));
  if (current) select.value = current;
}

let stageHunterResultMode = "auto";
let stageHunterRunPoll = null;

/* La progression affichée vient du serveur : chaque phase et chaque
   compteur affiché correspond à une étape réellement terminée.  Aucune
   estimation locale ne remplace un compteur du serveur. */
function renderExplorationProgress(state) {
  const progress = window.CareerExplorationProgress;
  const container = $("#stagehunter-progress");
  if (!progress || !container) return null;
  container.hidden = false;
  return progress.renderInto(state);
}

function stopExplorationPolling() {
  if (stageHunterRunPoll) {
    stageHunterRunPoll.stop();
    stageHunterRunPoll = null;
  }
}

/* Reprise après rechargement : le dernier identifiant d'exploration suffit
   pour retrouver l'état réel côté serveur. */
function resumeExplorationIfNeeded() {
  const progress = window.CareerExplorationProgress;
  if (!progress) return;
  const handle = progress.resume({
    onState: (state) => {
      renderExplorationProgress(state);
      if (!progress.isTerminal(state) || state.status !== "completed") return;
      api("/api/career/stage-search/explore").then((report) => {
        stageHunterResultMode = "explore";
        renderStageExploration(report);
        renderExplorationMatches(report);
      }).catch(() => {});
    },
  });
  if (handle) stageHunterRunPoll = handle;
}

function renderStageExploration(payload) {
  const status = $("#stagehunter-explore-status");
  const sources = $("#stagehunter-explore-sources");
  const details = $("#stagehunter-explore-report");
  const coverage = $("#stagehunter-explore-coverage");
  if (!status || !sources || !details || !coverage) return;
  const summary = payload.summary || {};
  const outcomes = payload.outcomes || [];
  sources.replaceChildren();
  details.hidden = outcomes.length === 0;
  const number = (key) => typeof summary[key] === "number" && Number.isFinite(summary[key]) ? summary[key] : "non communiqué";
  if (!outcomes.length) {
    status.textContent = "Aucune entreprise à configurer. Enregistre tes critères et clique sur Explorer les stages ; seules les sources vérifiées du registre seront lues.";
  } else {
    status.textContent = `${number("sources_attempted")} sources consultées sur le réseau · ${number("sources_cached")} en cache · ${number("sources_failed")} en erreur · ${number("raw_count")} annonces dans les flux (cache compris) · ${number("retained_count")} offres retenues lors de la recherche · ${number("displayed_count")} affichées avec tes critères actuels. ${summary.partial ? "Recherche partielle : consulte les limites et les sources ci-dessous." : "Couverture limitée au registre, pas à tout Internet."}`;
    if (payload.criteria_changed) status.textContent += " Critères modifiés depuis cette recherche : relance Explorer pour sélectionner à nouveau les stages.";
  }
  outcomes.forEach((outcome) => {
    const entry = make("section", "", "stagehunter-source-report");
    const labels = {success:"consultée", partial:"partielle", cached:"cache local", error:"échec", skipped:"non consultée", not_queried:"non consultée"};
    entry.append(make("strong", `${outcome.company || "Source"} · ${outcome.provider || "Greenhouse"} · ${labels[outcome.status] || outcome.status || "état inconnu"}`));
    if (outcome.message) entry.append(make("p", outcome.message));
    if (outcome.verified_at) entry.append(make("p", `Dernière lecture réussie : ${formatVerification(outcome.verified_at)}`));
    const specification = (payload.registry || []).find((source) => source.id === outcome.source_id);
    if (specification?.provenance_url) {
      const link = make("a", "Page carrières officielle utilisée pour qualifier cette source", "external-link");
      link.href = specification.provenance_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      entry.append(link);
      entry.append(make("p", `Qualification du registre : ${formatVerification(specification.verified_at)}`));
    }
    sources.append(entry);
  });
  coverage.textContent = `Offres conformes aux critères : ${number("confirmed_count")} · offres à vérifier : ${number("uncertain_count")} · offres exclues : ${number("excluded_count")} · entrées invalides : ${number("invalid_count")}. ${number("sources_not_queried")} sources non consultées. Limite : ${payload.limits?.max_sources ?? "non communiquée"} sources et ${payload.limits?.max_results ?? "non communiqué"} résultats classés. Les dates, la durée et les conditions absentes restent à vérifier. Aucun CV, profil ou critère personnel n’est transmis aux sites. La présence dans un flux public ne garantit pas que le recruteur accepte encore les candidatures.`;
}

function renderExplorationMatches(payload) {
  renderStageMatches({configured: payload.configured, matches: payload.matches || []});
  $("#stagehunter-result-mode").textContent = "Explorer les stages — résultats de cette exploration uniquement. Les autres offres et candidatures restent conservées dans Mes entreprises / Découvrir.";
  const empty = $("#stagehunter-matches-empty");
  empty.textContent = "Aucune offre retenue par cette exploration. Vérifie les sources et tes critères : aucun résultat fictif n’est ajouté pour remplir la liste.";
  (payload.matches || []).forEach((match, index) => {
    const wrapper = $("#stagehunter-matches").children[index];
    if (wrapper && match.qualification) {
      const labels = {internship:"Stage", fixed_term:"CDD", permanent:"CDI", VIE:"VIE", ambiguous:"à vérifier", unknown:"non précisé"};
      wrapper.prepend(make("p", `Type de contrat : ${labels[match.qualification.contract_type] || match.qualification.contract_type}`, "fixed-period-note"));
      const proof = match.qualification.provenance?.contract_type;
      if (proof?.quote) wrapper.prepend(make("p", `Preuve source : « ${proof.quote} »`, "scoring-disclaimer"));
    }
  });
}

function renderStageApplications() {
  const target = $("#stagehunter-applications");
  const empty = $("#stagehunter-applications-empty");
  if (!target || !empty) return;
  target.replaceChildren();
  empty.hidden = state.applications.length > 0;
  state.applications.forEach((application) => target.append(applicationCard(application)));
}

function sprintReadinessLabel(value) {
  return {
    prepare_now: "Prête à préparer",
    profile_to_complete: "Profil à compléter",
    offer_to_verify: "Offre à vérifier",
    candidate_to_verify: "Compatibilité candidat à vérifier",
  }[value] || "À vérifier";
}

function renderApplicationSprint(payload) {
  const target = $("#stagehunter-sprint");
  if (!target) return;
  target.replaceChildren();
  target.hidden = false;
  const stats = payload.stats || {};
  const statsBlock = make("div", "", "sprint-stats");
  [
    [stats.selected || 0, "offres dans la file"],
    [stats.prepare_now || 0, "prêtes à préparer"],
    [stats.profile_to_complete || 0, "profils à renforcer"],
    [stats.offer_to_verify || 0, "offres à vérifier"],
    [stats.candidate_to_verify || 0, "compatibilités à vérifier"],
  ].forEach(([value, label]) => {
    const item = make("article", "", "sprint-stat");
    item.append(make("strong", String(value)), make("span", label));
    statsBlock.append(item);
  });
  target.append(statsBlock);

  const grid = make("div", "", "sprint-grid");
  const queue = make("div", "", "sprint-queue");
  queue.append(make("h4", "Ordre de préparation conseillé"));
  if (!(payload.queue || []).length) {
    queue.append(make("p", "Aucune offre admissible dans les résultats actuels. Relance la recherche ou vérifie tes critères.", "empty-state"));
  }
  (payload.queue || []).forEach((item, index) => {
    const card = make("article", "", `sprint-card ${item.readiness === "prepare_now" ? "is-ready" : "is-review"}`);
    card.append(make("p", `#${index + 1} · ${item.company}`, "sprint-card-company"));
    card.append(make("h4", item.title));
    card.append(make("p", `${item.location} · langue ${item.language} · correspondance ${item.match_score}/100 · CV ${item.coverage_percent} %`, "sprint-card-meta"));
    card.append(chip(sprintReadinessLabel(item.readiness), item.readiness === "prepare_now" ? "good" : "warning"));
    if ((item.candidate_warnings || []).length) {
      const warnings = make("ul", "", "blocked-list");
      item.candidate_warnings.forEach((warning) => warnings.append(make("li", warning)));
      card.append(warnings);
    }
    const actionsList = make("ul");
    (item.next_actions || []).slice(0, 3).forEach((action) => actionsList.append(make("li", action)));
    card.append(actionsList);
    const actions = make("div", "", "job-actions");
    if (item.official_url) {
      const official = make("a", "Ouvrir la source officielle ↗", "secondary-button external-link");
      official.href = item.official_url;
      official.target = "_blank";
      official.rel = "noopener noreferrer";
      actions.append(official);
    }
    const prepare = make("button", "Préparer", "primary-button");
    prepare.type = "button";
    prepare.addEventListener("click", () => loadStagePrep(item.job_id));
    const detail = make("button", "Voir le détail", "secondary-button");
    detail.type = "button";
    detail.addEventListener("click", () => loadStageDetail(item.job_id));
    const kit = make("button", "Créer le kit local", "secondary-button");
    kit.type = "button";
    kit.title = "Prépare localement le CV et la lettre ; aucun dépôt n’est effectué.";
    kit.addEventListener("click", () => {
      const language = String(item.language || "").toLowerCase();
      const languageCode = ["fr", "en", "it", "de"].find((code) => language === code || language.startsWith(`${code}-`));
      if (!languageCode) {
        setMessage("La langue de cette offre doit être confirmée avant de créer le kit.", true);
        loadStagePrep(item.job_id);
        return;
      }
      startApplicationKitFlow(item.job_id, languageCode, item.recommended_variant || "");
    });
    actions.append(prepare, kit, detail);
    if (!item.tracking) {
      const track = make("button", "Créer le suivi", "secondary-button");
      track.type = "button";
      track.addEventListener("click", async () => {
        track.disabled = true;
        try {
          await api("/api/career/applications", {method: "POST", body: JSON.stringify({job_id: item.job_id})});
          setMessage("Suivi local créé. Aucun envoi n’a été effectué.");
          await Promise.all([loadApplications(), loadDashboard(), loadApplicationSprint()]);
        } catch (error) {
          setMessage(error.message, true);
        } finally {
          track.disabled = false;
        }
      });
      actions.append(track);
    } else {
      actions.append(make("span", `Suivi : ${stageLabels[item.tracking.stage] || item.tracking.stage}`, "sprint-card-meta"));
    }
    card.append(actions);
    queue.append(card);
  });

  const cv = make("aside", "", "sprint-cv");
  const verification = payload.verification_summary || [];
  if (verification.length) {
    cv.append(make("h4", "Vérifications groupées"));
    cv.append(make("p", "Confirme ces faits sur les pages officielles pour débloquer plusieurs dossiers à la fois.", "sprint-card-meta"));
    const verificationList = make("ul");
    verification.slice(0, 8).forEach((item) => verificationList.append(make("li", `${item.field} · ${item.offer_count} offre(s)`)));
    cv.append(verificationList);
  }
  cv.append(make("h4", "Priorités CV à fort impact"));
  const priorities = payload.cv_advice?.priorities || [];
  if (!priorities.length) cv.append(make("p", "Aucun manque récurrent détecté sur cette file. Relis malgré tout chaque offre et chaque document.", "sprint-card-meta"));
  priorities.slice(0, 8).forEach((priority) => {
    const block = make("div", "", "sprint-priority");
    block.append(make("strong", `${priority.keyword} · ${priority.offer_count} offre(s)`));
    block.append(make("p", priority.advice));
    cv.append(block);
  });
  const strengths = payload.cv_advice?.strengths || [];
  if (strengths.length) {
    cv.append(make("h4", "Preuves déjà présentes à remonter"));
    const list = make("ul");
    strengths.slice(0, 8).forEach((strength) => list.append(make("li", `${strength.keyword} · repéré dans ${strength.offer_count} correspondance(s)`)));
    cv.append(list);
  }
  grid.append(queue, cv);
  target.append(grid, make("p", payload.disclaimer || "Aucun envoi automatique.", "sprint-disclaimer"));
  reveal(target, "start");
}

async function loadApplicationSprint() {
  const target = $("#stagehunter-sprint");
  if (!target) return;
  target.hidden = false;
  target.replaceChildren(make("p", "Construction locale de la file…"));
  try {
    renderApplicationSprint(await api("/api/career/application-sprint?limit=20"));
  } catch (error) {
    target.replaceChildren(make("p", error.message, "scoring-disclaimer"));
  }
}

function renderApplicationPipeline(payload) {
  const target = $("#stagehunter-pipeline");
  if (!target) return;
  target.replaceChildren();
  target.hidden = false;
  const pipeline = payload.pipeline || [];
  if (!pipeline.length) {
    target.append(make("p", "Aucune offre dans le pipeline.", "empty-state"));
    return;
  }
  const list = make("div", "", "pipeline-list");
  pipeline.forEach((item) => {
    const row = make("article", "", "pipeline-row");
    row.append(
      make("h4", `${item.company} — ${item.title}`),
      make(
        "p",
        `Stade : ${item.stage} · Variante : ${item.variant_label || "non sélectionnée"} · Score : ${item.match_score || 0}`,
        "application-meta",
      ),
    );
    const actions = make("div", "", "job-actions");
    const prepare = make("button", "Préparer", "secondary-button");
    prepare.type = "button";
    prepare.addEventListener("click", () => loadStagePrep(item.job_id));
    actions.append(prepare);
    if (!item.tracking_stage) {
      const track = make("button", "Créer le suivi", "primary-button");
      track.type = "button";
      track.addEventListener("click", async () => {
        await api("/api/career/applications", {
          method: "POST",
          body: JSON.stringify({ job_id: item.job_id }),
        });
        await loadApplicationPipeline();
      });
      actions.append(track);
    }
    row.append(actions);
    list.append(row);
  });
  target.append(list);
}

async function loadApplicationPipeline() {
  const target = $("#stagehunter-pipeline");
  if (!target) return;
  target.hidden = false;
  target.replaceChildren(make("p", "Chargement du pipeline…"));
  try {
    renderApplicationPipeline(await api("/api/career/application-pipeline"));
  } catch (error) {
    target.replaceChildren(make("p", error.message, "scoring-disclaimer"));
  }
}

function renderStagePrepList(target, title, items, renderItem) {
  if (!items.length) return;
  const section = make("section", "", "stagehunter-prep-section");
  section.append(make("h4", title));
  const list = make("ul", "", "job-reasons");
  items.forEach((item) => list.append(renderItem(item)));
  section.append(list);
  target.append(section);
}

function renderVariantFitAnalysis(target, prep) {
  const coverage = prep.coverage || {};
  const section = make("section", "", "stagehunter-prep-section variant-specific");
  section.append(make("h4", "Variante CV recommandée"));
  const recommendation = make(
    "p",
    prep.recommended_variant_label || "Variante à confirmer",
    "application-meta",
  );
  recommendation.title = prep.variant_rationale || "Classification locale déterministe";
  section.append(recommendation);
  if (prep.variant_rationale) {
    section.append(make("p", prep.variant_rationale, "scoring-disclaimer"));
  }

  const coverageList = make("ul", "", "job-reasons");
  coverageList.append(
    make(
      "li",
      `Couverture obligatoire : ${Number(coverage.mandatory_pct || 0).toFixed(1)} % (${coverage.mandatory_covered || 0}/${coverage.mandatory_total || 0})`,
    ),
    make(
      "li",
      `Couverture préférée : ${Number(coverage.preferred_pct || 0).toFixed(1)} % (${coverage.preferred_covered || 0}/${coverage.preferred_total || 0})`,
    ),
  );
  section.append(coverageList);

  const gaps = prep.gaps || [];
  if (gaps.length) {
    section.append(make("h5", "CV actuel → CV adapté"));
    const list = make("ul", "", "job-reasons");
    gaps.forEach((gap) => {
      const citation = gap.provenance || {};
      const source = citation.source || citation.filename || "aucune preuve disponible";
      const quote = citation.quote ? ` — « ${citation.quote} »` : "";
      list.append(
        make(
          "li",
          `${gap.requirement} · ${gap.current_state} → ${gap.adapted_state} · Source : ${source}${quote}`,
        ),
      );
    });
    section.append(list);
  }
  target.append(section);
}

function renderStagePrep(prep) {
  const target = $("#stagehunter-prep");
  if (!target) return;
  target.replaceChildren();
  target.hidden = false;
  const job = prep.job || {};
  target.append(make("h4", `${job.title || "Offre"} — ${job.company || "Entreprise"}`));
  if (job.official_url) {
    const link = make("a", "Ouvrir l’offre officielle conservée", "secondary-button external-link");
    link.href = job.official_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", `Ouvrir l’offre officielle « ${job.title || ""} » dans un nouvel onglet`);
    target.append(link);
  }
  target.append(
    make(
      "p",
      `Source : ${job.source_name || "inconnue"} · statut : ${job.source_status === "open" ? "ouverte" : "à vérifier"} · consultation : ${formatVerification(job.last_verified_at)}`,
      "application-meta",
    ),
  );
  if ((prep.uncertainty || []).length) {
    const warnings = make("ul", "", "scoring-list blocked-list");
    prep.uncertainty.forEach((item) => warnings.append(make("li", item)));
    target.append(warnings);
  }
  renderVariantFitAnalysis(target, prep);
  const cvCoverage = prep.cv_coverage || {};
  if ((typeof renderCvPlanSection === "function") && ((prep.cv_action_plan || []).length || Number.isFinite(cvCoverage.requirements_total))) {
    const planSection = renderCvPlanSection(target, prep, job);
    if (planSection) target.append(planSection);
  }
  renderStagePrepList(target, "Exigences de l’offre (texte source conservé)", prep.requirements || [], (item) => make("li", `${item.text}`));
  if (prep.source_excerpt) {
    const source = make("details", "", "stagehunter-prep-section");
    source.append(make("summary", "Relire un extrait de la description source (jusqu’à 4 000 caractères)"));
    source.append(make("p", prep.source_excerpt));
    target.append(source);
  }
  renderStagePrepList(target, "Éléments pertinents de ton profil", prep.matched_elements || [], (item) => make("li", `« ${item.requirement} » → ton profil (${item.profile_field}) : « ${item.evidence} ».`));
  renderStagePrepList(target, "Non trouvé dans ton profil", prep.unverified_elements || [], (item) => make("li", `${item.requirement} — ${item.note}`));
  renderStagePrepList(target, "Améliorations de CV suggérées", prep.cv_improvements || [], (item) => make("li", item.suggestion));
  renderStagePrepList(target, "Points pour le message de motivation", prep.letter_points || [], (item) => make("li", item.point));
  renderStagePrepList(target, "Garanties d’honnêteté", prep.checks || [], (item) => make("li", `${item.label} — ${item.detail}`));
  if (prep.disclaimer) target.append(make("p", prep.disclaimer, "scoring-disclaimer"));
  const actions = make("div", "", "job-actions");
  const studio = make("button", "Ouvrir l’Application Studio", "secondary-button");
  studio.type = "button";
  studio.addEventListener("click", () => openStudioForJob(job, cvCoverage.target_language));
  actions.append(studio);
  const kitLanguage = make("select", "", "kit-language-select");
  kitLanguage.setAttribute("aria-label", "Langue du kit de candidature");
  ["fr", "en", "it", "de"].forEach((code) => kitLanguage.append(new Option(draftLanguageLabels[code], code)));
  const kitVariant = make("select", "", "kit-variant-select variant-specific");
  kitVariant.setAttribute("aria-label", "Variante CV ciblée");
  const variantCoverage = prep.variant_coverage || {};
  [
    ["m_a", "M&A / Investment Banking"],
    ["markets", "Markets / Quant"],
    ["corporate_finance", "Corporate Finance / FP&A"],
  ].forEach(([id, label]) => {
    const percentage = Number(variantCoverage[id]);
    const comparison = Number.isFinite(percentage) ? ` — ${percentage.toFixed(1)} % obligatoire` : "";
    kitVariant.append(new Option(`${label}${comparison}`, id));
  });
  kitVariant.value = prep.recommended_variant || "m_a";
  kitVariant.title = prep.variant_rationale || "Sélection manuelle possible";
  const kit = make("button", "Préparer le kit de candidature", "primary-button");
  kit.type = "button";
  // Un clic = un kit pour CETTE offre. Aucune boucle de candidature : le
  // suivi et le brouillon local sont créés une fois puis réutilisés.
  kit.addEventListener("click", () => startApplicationKitFlow(job.id, kitLanguage.value, kitVariant.value));
  actions.append(kitLanguage, kitVariant, kit);
  target.append(actions);
}

async function loadStagePrep(jobId) {
  const target = $("#stagehunter-prep");
  if (!target) return;
  target.hidden = false;
  target.replaceChildren(make("p", "Analyse locale en cours…"));
  reveal(target, "start");
  try {
    const prep = await api(`/api/career/jobs/${encodeURIComponent(jobId)}/prep`);
    const select = $("#stagehunter-prep-job");
    if (select) {
      if (![...select.options].some((option) => option.value === jobId)) {
        select.append(new Option(`${prep.job.title} — ${prep.job.company}`, jobId));
      }
      select.value = jobId;
    }
    renderStagePrep(prep);
  } catch (error) {
    target.replaceChildren(make("p", error.message, "scoring-disclaimer"));
  }
}

async function loadStageHunter() {
  const payload = await api("/api/career/stage-search");
  renderStageBrief(payload);
  renderStageTerms(payload);
  const exploration = await api("/api/career/stage-search/explore");
  renderStageExploration(exploration);
  if (stageHunterResultMode === "auto") stageHunterResultMode = (exploration.outcomes || []).length ? "explore" : "saved";
  if (stageHunterResultMode === "explore") {
    renderExplorationMatches({...exploration, configured:payload.configured});
  } else {
    const matches = await api("/api/career/stage-search/matches");
    renderStageMatches(matches);
    $("#stagehunter-result-mode").textContent = "Mes offres enregistrées — tous les types de contrats, avec classement et avertissements. Aucune offre suivie n’a été supprimée.";
    $("#stagehunter-matches-empty").textContent = "Aucune offre enregistrée. Clique sur Explorer les stages pour chercher sans configurer d’entreprise.";
  }
  renderStagePrepSelect();
  const applications = await api("/api/career/applications");
  state.applications = applications.applications || [];
  renderStageApplications();
}

$("#stagehunter-brief-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const ranking = {};
  document.querySelectorAll("#stagehunter-ranking input").forEach((input) => {
    const value = Number.parseFloat(input.value);
    if (Number.isFinite(value)) ranking[input.dataset.criterion] = value;
  });
  const payload = {
    domains: [...document.querySelectorAll("#stagehunter-domains input:checked")].map((box) => box.value),
    other_domains: stageHunterListValue("#stagehunter-other-domains"),
    roles: stageHunterListValue("#stagehunter-roles"),
    countries: stageHunterListValue("#stagehunter-countries"),
    cities: stageHunterListValue("#stagehunter-cities"),
    excluded_countries: stageHunterListValue("#stagehunter-excluded-countries"),
    excluded_cities: stageHunterListValue("#stagehunter-excluded-cities"),
    require_known_location: $("#stagehunter-require-known-location").checked,
    start_date: "",
    duration_months: null,
    contract_types: [...document.querySelectorAll("#stagehunter-contract-types input:checked")].map((box) => box.value),
    start_months: [...document.querySelectorAll("#stagehunter-start-months input:checked")].map((box) => Number.parseInt(box.value, 10)),
    minimum_stage_duration_months: Number.parseInt($("#stagehunter-min-stage-duration").value, 10),
    study_level: $("#stagehunter-level").value.trim(),
    education_preference: $("#stagehunter-education-preference").value,
    languages: stageHunterListValue("#stagehunter-languages"),
    constraints: $("#stagehunter-constraints").value.trim(),
    ranking,
  };
  try {
    const saved = await api("/api/career/stage-search", { method: "PUT", body: JSON.stringify(payload) });
    renderStageBrief(saved);
    renderStageTerms(saved);
    await loadStageHunter();
    setMessage("Critères de stage enregistrés localement ; le classement a été recalculé.");
  } catch (error) { setMessage(error.message, true); }
});

$("#stagehunter-search")?.addEventListener("click", async () => {
  const button = $("#stagehunter-search");
  button.disabled = true;
  const previousLabel = button.textContent;
  button.textContent = "Recherche en cours…";
  try {
    stageHunterResultMode = "saved";
    // runDiscovery owns the success/partial/error summary and refreshes this
    // visible view. Never overwrite its source failure with a success label.
    await runDiscovery(false);
  } catch (error) { setMessage(error.message, true); }
  finally {
    button.disabled = false;
    button.textContent = previousLabel;
  }
});

$("#stagehunter-explore")?.addEventListener("click", async () => {
  const button = $("#stagehunter-explore");
  const cancelButton = $("#stagehunter-explore-cancel");
  const progress = window.CareerExplorationProgress;
  button.disabled = true;
  button.textContent = "Exploration en cours…";
  if (cancelButton) cancelButton.hidden = false;
  try {
    if (!progress) throw new Error("Le suivi de progression de l’exploration est indisponible.");
    const started = await progress.startExploration({force: false});
    renderExplorationProgress(started);
    stageHunterRunPoll = progress.poll(started.run_id, {onState: renderExplorationProgress});
    const result = await stageHunterRunPoll.promise;
    stageHunterRunPoll = null;
    progress.forgetRun();
    renderExplorationProgress(result);
    stageHunterResultMode = "explore";
    const report = await api("/api/career/stage-search/explore");
    renderStageExploration(report);
    renderExplorationMatches(report);
    await Promise.all([loadJobs(), loadApplications(), loadDashboard()]);
    renderStagePrepSelect();
    const failed = Number.isFinite(result.sources_failed) ? result.sources_failed : 0;
    const succeeded = Number.isFinite(result.sources_succeeded) ? result.sources_succeeded : 0;
    if (result.status === "cancelled") {
      setMessage("Exploration arrêtée entre deux sources. Les résultats précédents et tes offres enregistrées sont conservés.", false);
    } else if (failed && !succeeded) {
      setMessage("Les sources n’ont pas pu être lues. Aucun résultat n’a été inventé ; consulte le rapport de recherche.", true);
    } else if (failed) {
      setMessage("Exploration partielle terminée : certaines sources ont échoué. Consulte le rapport de recherche avant de choisir une offre.", false);
    } else {
      setMessage("Exploration terminée sur les sources du registre. Aucun dépôt de candidature n’a été effectué.", false);
    }
  } catch (error) {
    stopExplorationPolling();
    setMessage(error.message, true);
    $("#stagehunter-explore-status").textContent = "L’exploration a échoué. Tes offres et candidatures déjà enregistrées sont conservées.";
  } finally {
    stopExplorationPolling();
    button.disabled = false;
    button.textContent = "Explorer les stages";
    if (cancelButton) cancelButton.hidden = true;
  }
});

$("#stagehunter-explore-cancel")?.addEventListener("click", async () => {
  const button = $("#stagehunter-explore-cancel");
  const progress = window.CareerExplorationProgress;
  const runId = progress?.storedRunId?.();
  if (!progress || !runId) return;
  button.disabled = true;
  try {
    const state = await progress.cancelExploration(runId);
    renderExplorationProgress(state);
    setMessage("Arrêt demandé : l’exploration s’arrête entre deux sources et les résultats précédents sont conservés.", false);
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#stagehunter-my-companies")?.addEventListener("click", () => {
  stageHunterResultMode = "saved";
  $("#stagehunter-personal-boards").open = true;
  loadStageHunter().catch((error) => setMessage(error.message, true));
});

$("#stagehunter-refresh")?.addEventListener("click", () => {
  loadStageHunter().catch((error) => setMessage(error.message, true));
});

$("#stagehunter-prep-submit")?.addEventListener("click", () => {
  const jobId = $("#stagehunter-prep-job")?.value;
  if (!jobId) {
    setMessage("Choisis d’abord une offre à préparer.", true);
    return;
  }
  loadStagePrep(jobId);
});

$("#stagehunter-sprint-build")?.addEventListener("click", () => loadApplicationSprint());
$("#stagehunter-pipeline-refresh")?.addEventListener("click", () => loadApplicationPipeline());

document.querySelectorAll(".career-tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));

(function fillApplicationStageFilter() {
  const select = $("#applications-filter-stage");
  if (!select || select.options.length > 1) return;
  Object.entries(stageLabels).forEach(([value, label]) => select.append(new Option(label, value)));
})();

["applications-filter-stage", "applications-filter-receipt", "applications-filter-deadline"].forEach((id) => {
  $(`#${id}`)?.addEventListener("change", () => loadApplications());
});
$("#applications-filter-action")?.addEventListener("change", () => loadApplications());
document.querySelectorAll("[data-view-action]").forEach((action) => action.addEventListener("click", () => {
  showView(action.dataset.viewAction);
  const targetId = action.dataset.focusTarget;
  if (targetId) window.setTimeout(() => document.getElementById(targetId)?.focus(), 0);
}));
window.addEventListener("hashchange", () => {
  if (internalHashChange) {
    internalHashChange = false;
    return;
  }
  const requested = window.location.hash.replace("#career/", "");
  if (careerViews.has(requested)) showView(requested, { focus: false, updateHash: false });
});

async function bootstrap() {
  setLoading(true);
  try {
    organiseViews();
    await Promise.all([loadHealth(), loadProfile(), loadProfileImports(), loadIntake(), loadPreferences(), loadDiscoverySources(), loadDashboard(), loadJobs(), loadShortlist(), loadApplications()]);
    resumeExplorationIfNeeded();
    const requested = window.location.hash.replace("#career/", "");
    if (careerViews.has(requested)) showView(requested, { focus: false, updateHash: false });
    else document.title = "Tableau de bord — Côme AI Career";
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    setLoading(false);
  }
}

bootstrap();

$("#stagehunter-sort")?.addEventListener("change", (event) => {
  localStorage.setItem("stagehunter_sort", event.target.value);
  renderStageMatches({ matches: state.stageMatches, configured: true });
});

$("#stagehunter-detail-prev")?.addEventListener("click", () => {
  if (!state.stageMatches.length) return;
  state.stageDetailIndex = (state.stageDetailIndex - 1 + state.stageMatches.length) % state.stageMatches.length;
  loadStageDetail(state.stageMatches[state.stageDetailIndex].job.id);
});

$("#stagehunter-detail-next")?.addEventListener("click", () => {
  if (!state.stageMatches.length) return;
  state.stageDetailIndex = (state.stageDetailIndex + 1) % state.stageMatches.length;
  loadStageDetail(state.stageMatches[state.stageDetailIndex].job.id);
});
