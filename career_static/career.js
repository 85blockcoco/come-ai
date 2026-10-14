"use strict";

const state = {
  preferences: null,
  jobs: [],
  applications: [],
  profileImports: [],
  activeProfileImport: null,
  intake: null,
  applicationDrafts: [],
  activeApplicationDraft: null,
  studioJobs: [],
  discoverySources: [],
  coachSessions: [],
  activeCoachSession: null,
};
const $ = (selector) => document.querySelector(selector);
const elements = {
  main: $("#career-main"),
  health: $("#career-health"),
  loading: $("#career-loading"),
  message: $("#career-message"),
  metrics: $("#dashboard-metrics"),
  dashboardContent: $("#dashboard-content"),
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
    throw new Error(detail);
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

function jobCard(job, mode = "discover") {
  const card = make("article", "", "job-card");
  const header = make("div", "", "job-card-header");
  const titleBlock = make("div");
  titleBlock.append(make("h3", job.title), make("p", job.company, "job-company"));
  const calendarTone = calendarClasses[job.calendar_status] || "warning";
  header.append(titleBlock, chip(calendarLabels[job.calendar_status] || "À vérifier", calendarTone));
  card.append(header);

  const chips = make("div", "", "job-chips");
  if (job.job_family) chips.append(chip(job.job_family));
  if (job.city || job.country) chips.append(chip([job.city, job.country].filter(Boolean).join(", ")));
  const availabilityTone = job.deadline_status === "closed" ? "danger" : job.source_status === "open" ? "good" : "warning";
  chips.append(chip(job.deadline_status === "closed" ? "Annonce fermée / échue" : job.source_status === "open" ? "Annonce ouverte" : "Statut à vérifier", availabilityTone));
  const scoring = job.scoring || {};
  const scoreTone = scoring.blocking_constraints?.length ? "danger" : scoring.is_recommendable ? "good" : "warning";
  if (Number.isFinite(scoring.score)) chips.append(chip(`Pertinence ${scoring.score}/100`, scoreTone));
  if (job.shortlisted) chips.append(chip("Shortlist", "good"));
  card.append(chips);

  const details = make("div", "", "job-details");
  if (job.deadline_date) details.append(make("p", `Date limite : ${job.deadline_date}`));
  if (job.start_date || job.end_date || job.duration_months) {
    details.append(make("p", `Période annoncée : ${[job.start_date, job.end_date].filter(Boolean).join(" → ") || "dates non précisées"}${job.duration_months ? ` · ${job.duration_months} mois` : ""}`));
  }
  if (!job.deadline_date && !job.start_date && !job.end_date && !job.duration_months) details.append(make("p", "Dates non renseignées."));
  if (job.source_name && job.source_name !== "manual") {
    details.append(make("p", `Source officielle : ${job.source_name} · vérifiée : ${formatVerification(job.last_verified_at)}`));
  }
  card.append(details);
  if ((job.calendar_reasons || []).length) {
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
  card.append(scoreBlock);

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
  editNote.addEventListener("click", () => updateJobNote(job));
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
    const note = job.shortlisted ? job.personal_note || "" : window.prompt("Note personnelle facultative pour cette offre :", job.personal_note || "");
    if (note === null && !job.shortlisted) return;
    await api(`/api/career/jobs/${encodeURIComponent(job.id)}/shortlist`, {
      method: "POST",
      body: JSON.stringify({ shortlisted: !job.shortlisted, note: note ?? job.personal_note ?? "" }),
    });
    setMessage(job.shortlisted ? "Offre retirée de la shortlist." : "Offre ajoutée à la shortlist.");
    await Promise.all([loadDashboard(), loadJobs(), loadShortlist(), refreshStageHunterIfVisible()]);
  } catch (error) { setMessage(error.message, true); }
}

// The Stage Hunter tab refreshes itself only when it is on screen, so other
// views keep their current cost.
async function refreshStageHunterIfVisible() {
  if (window.location.hash !== "#career/stagehunter") return;
  await loadStageHunter().catch(() => {});
}

async function updateJobNote(job) {
  const note = window.prompt("Note personnelle (locale) :", job.personal_note || "");
  if (note === null) return;
  try {
    await api(`/api/career/jobs/${encodeURIComponent(job.id)}/note`, { method: "PATCH", body: JSON.stringify({ note }) });
    setMessage("Note personnelle enregistrée.");
    await Promise.all([loadJobs(), loadShortlist()]);
  } catch (error) { setMessage(error.message, true); }
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
  const header = make("div", "", "application-card-header");
  const title = make("div");
  title.append(make("h3", application.title), make("p", `${application.company}${application.city ? ` · ${application.city}` : ""}`, "job-company"));
  header.append(title, chip(stageLabels[application.stage] || application.stage, application.receipt_status === "unknown" ? "warning" : application.receipt_status === "confirmed" ? "good" : ""));
  card.append(header);
  const meta = make("p", "", "application-meta");
  meta.textContent = `Réception : ${application.receipt_status === "confirmed" ? "confirmée" : application.receipt_status === "unknown" ? "inconnue — ne pas renvoyer automatiquement" : "non déclarée"}.`;
  card.append(meta);
  if (application.confirmation_reference) card.append(make("p", `Référence : ${application.confirmation_reference}`, "application-meta"));
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
  return card;
}

async function loadApplications() {
  const payload = await api("/api/career/applications");
  state.applications = payload.applications || [];
  elements.applications.replaceChildren();
  elements.applicationsEmpty.hidden = state.applications.length > 0;
  state.applications.forEach((application) => elements.applications.append(applicationCard(application)));
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
  if (jobs.some((job) => job.id === current)) elements.applicationDraftJob.value = current;
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
  const rankingTarget = $("#stagehunter-ranking");
  if (!domainsTarget || !rankingTarget) return;
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
  $("#stagehunter-other-domains").value = (brief.other_domains || []).join(", ");
  $("#stagehunter-roles").value = (brief.roles || []).join(", ");
  $("#stagehunter-countries").value = (brief.countries || []).join(", ");
  $("#stagehunter-cities").value = (brief.cities || []).join(", ");
  $("#stagehunter-start").value = brief.start_date || "";
  $("#stagehunter-duration").value = brief.duration_months ?? "";
  $("#stagehunter-level").value = brief.study_level || "";
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

function stageMatchBlock(stageMatch) {
  const block = make("section", "", "stage-match-block");
  const header = make("div", "", "stage-match-header");
  const scoreText = Number.isFinite(stageMatch.score) ? `${stageMatch.score}/100` : "non calculé";
  const tone = Number.isFinite(stageMatch.score) && stageMatch.score >= 70 ? "good" : "warning";
  header.append(make("p", `Correspondance stage : ${scoreText}`, "scoring-title"), chip(stageMatch.label || "", tone));
  block.append(header);
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

function renderStageMatches(payload) {
  const target = $("#stagehunter-matches");
  const empty = $("#stagehunter-matches-empty");
  if (!target || !empty) return;
  target.replaceChildren();
  const matches = payload.matches || [];
  empty.hidden = matches.length > 0;
  matches.forEach((match) => {
    const wrapper = make("div", "", "stagehunter-match");
    if (match.stage_match) wrapper.append(stageMatchBlock(match.stage_match));
    const card = jobCard(match.job, "discover");
    const actions = card.querySelector(".job-actions");
    const prep = make("button", "Préparer cette candidature", "secondary-button");
    prep.type = "button";
    prep.addEventListener("click", () => loadStagePrep(match.job.id));
    actions?.append(prep);
    wrapper.append(card);
    target.append(wrapper);
  });
  $("#stagehunter-matches-note").textContent = payload.configured
    ? "Classement calculé localement à partir de tes critères ; chaque composante est expliquée ci-dessus."
    : "Renseigne tes critères à l’étape A pour obtenir un classement expliqué. Aucune préférence n’est supposée.";
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
    status.textContent = `${number("sources_attempted")} sources consultées sur le réseau · ${number("sources_cached")} en cache · ${number("sources_failed")} en erreur · ${number("raw_count")} annonces dans les flux (cache compris) · ${number("retained_count")} stages retenus lors de la recherche · ${number("displayed_count")} affichés avec tes critères actuels. ${summary.partial ? "Recherche partielle : consulte les limites et les sources ci-dessous." : "Couverture limitée au registre, pas à tout Internet."}`;
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
  coverage.textContent = `Stages identifiés dans les flux : ${number("confirmed_count")} · contrats incertains non présentés comme stages : ${number("uncertain_count")} · emplois non admissibles : ${number("excluded_count")} · entrées invalides : ${number("invalid_count")}. ${number("sources_not_queried")} sources non consultées. Limite : ${payload.limits?.max_sources ?? "non communiquée"} sources et ${payload.limits?.max_results ?? "non communiqué"} résultats classés. Les dates, la durée et les conditions absentes restent à vérifier. Aucun CV, profil ou critère personnel n’est transmis aux sites. La présence dans un flux public ne garantit pas que le recruteur accepte encore les candidatures.`;
}

function renderExplorationMatches(payload) {
  renderStageMatches({configured: payload.configured, matches: payload.matches || []});
  $("#stagehunter-result-mode").textContent = "Explorer les stages — résultats de cette exploration uniquement. Les autres offres et candidatures restent conservées dans Mes entreprises / Découvrir.";
  const empty = $("#stagehunter-matches-empty");
  empty.textContent = "Aucun stage retenu par cette exploration. Vérifie les sources et tes critères : aucun résultat fictif ni CDI n’est ajouté pour remplir la liste.";
  (payload.matches || []).forEach((match, index) => {
    const wrapper = $("#stagehunter-matches").children[index];
    if (wrapper && match.internship) {
      wrapper.prepend(make("p", `Stage repéré dans l’annonce : ${match.internship.reason || "indication explicite dans le texte source"}`, "fixed-period-note"));
      (match.internship.evidence || []).slice(0, 3).forEach((evidence) => {
        wrapper.prepend(make("p", `Preuve source (${evidence.field || "annonce"}) : « ${evidence.quote || ""} »`, "scoring-disclaimer"));
      });
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

function renderStagePrepList(target, title, items, renderItem) {
  if (!items.length) return;
  const section = make("section", "", "stagehunter-prep-section");
  section.append(make("h4", title));
  const list = make("ul", "", "job-reasons");
  items.forEach((item) => list.append(renderItem(item)));
  section.append(list);
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
  studio.addEventListener("click", () => showView("studio"));
  actions.append(studio);
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
    start_date: $("#stagehunter-start").value,
    duration_months: $("#stagehunter-duration").value ? Number.parseInt($("#stagehunter-duration").value, 10) : null,
    study_level: $("#stagehunter-level").value.trim(),
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
  button.disabled = true;
  button.textContent = "Exploration en cours…";
  try {
    const result = await api("/api/career/stage-search/explore", {method:"POST", body:JSON.stringify({force:false})});
    stageHunterResultMode = "explore";
    renderStageExploration(result);
    renderExplorationMatches(result);
    await Promise.all([loadJobs(), loadApplications(), loadDashboard()]);
    renderStagePrepSelect();
    const failed = result.summary?.sources_failed || 0;
    const succeeded = (result.summary?.sources_succeeded || 0) + (result.summary?.sources_cached || 0);
    setMessage(failed && !succeeded ? "Les sources n’ont pas pu être lues. Aucun résultat n’a été inventé ; consulte le rapport de recherche." : result.summary?.partial ? "Exploration partielle terminée. Consulte les sources et les limites avant de choisir une offre." : "Exploration terminée sur les sources du registre. Aucun dépôt de candidature n’a été effectué.", Boolean(failed && !succeeded));
  } catch (error) {
    setMessage(error.message, true);
    $("#stagehunter-explore-status").textContent = "L’exploration a échoué. Tes offres et candidatures déjà enregistrées sont conservées.";
  } finally {
    button.disabled = false;
    button.textContent = "Explorer les stages";
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

document.querySelectorAll(".career-tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));
document.querySelectorAll("[data-view-action]").forEach((action) => action.addEventListener("click", () => showView(action.dataset.viewAction)));
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
