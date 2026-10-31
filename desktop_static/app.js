/* Côme IA — cockpit local.
   Toutes les données viennent de l'API locale (127.0.0.1) : aucune requête externe. */
(() => {
  "use strict";
  window.__appState = null;

  const THEME_STORAGE_KEY = "nage-app-theme-v2";
  const LANGUAGE_STORAGE_KEY = "nage-kit-language-v1";
  const DOCUMENT_STORAGE_KEY = "nage-homework-document-v1";
  const REFERENCE_STORAGE_KEY = "nage-homework-reference-v1";
  const THEMES = new Set(["terminal", "studio"]);
  const KIT_LANGUAGES = new Set(["en", "fr", "it", "de"]);

  function readTheme() {
    try {
      const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
      return THEMES.has(saved) ? saved : "studio";
    } catch {
      return "studio";
    }
  }

  function applyTheme(theme, persist = true) {
    const selected = THEMES.has(theme) ? theme : "studio";
    document.body.dataset.theme = selected;
    document.documentElement.dataset.theme = selected;
    const picker = document.querySelector("#themeSelect");
    if (picker) picker.value = selected;
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.content = selected === "studio" ? "light" : "dark";
    if (window.__appState) window.__appState.theme = selected;
    if (persist) {
      try { window.localStorage.setItem(THEME_STORAGE_KEY, selected); } catch { /* stockage local indisponible */ }
    }
    return selected;
  }

  function readKitLanguage() {
    try {
      const saved = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
      return KIT_LANGUAGES.has(saved) ? saved : "en";
    } catch {
      return "en";
    }
  }

  function readSelectedDocumentId() {
    try { return window.localStorage.getItem(DOCUMENT_STORAGE_KEY); }
    catch { return null; }
  }

  function readReferenceDocumentId() {
    try { return window.localStorage.getItem(REFERENCE_STORAGE_KEY); }
    catch { return null; }
  }

  const state = window.__appState = {
    view: "today",
    dashboard: null,
    pipeline: null,
    jobs: null,
    overview: null,
    missions: null,
    specifications: null,
    specificationsLoading: false,
    specificationBusy: null,
    specificationForm: null,
    workshopToken: null,
    filter: "",
    tracker: null,
    chat: [],
    chatMode: "offline",
    sending: false,
    documents: null,
    selectedDocumentId: readSelectedDocumentId(),
    referenceDocumentId: readReferenceDocumentId(),
    documentFilter: "",
    documentInspection: null,
    documentAnalysis: null,
    homeworkTasks: null,
    homeworkTaskBusy: null,
    homeworkChat: [],
    homeworkSending: false,
    homeworkUploading: false,
    studyOverview: null,
    studySyllabus: null,
    studySession: null,
    studyQuestion: null,
    studyCorrection: null,
    studyBusy: false,
    health: null,
    careerSection: "stagehunter",
    kitLanguage: readKitLanguage(),
    theme: readTheme(),
    errors: {},
  };

  applyTheme(state.theme, false);

  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "class") node.className = value;
      else if (key === "html") node.innerHTML = value;
      else if (key === "style") node.style.cssText = value; // CSSOM : autorisé par la CSP
      else if (key === "value") node.value = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value !== null && value !== undefined && value !== false) node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  };

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

  const num = (value) => new Intl.NumberFormat("fr-FR").format(Number(value) || 0);

  let activeRequests = 0;
  let progressTimer = null;

  function beginProgress() {
    activeRequests += 1;
    if (activeRequests !== 1) return;
    progressTimer = window.setTimeout(() => {
      const bar = $("#progressBar");
      if (bar && activeRequests > 0) bar.hidden = false;
    }, 120);
  }

  function endProgress() {
    activeRequests = Math.max(0, activeRequests - 1);
    if (activeRequests) return;
    window.clearTimeout(progressTimer);
    progressTimer = null;
    const bar = $("#progressBar");
    if (bar) bar.hidden = true;
  }

  async function api(path, options) {
    const requestOptions = options || {};
    const isForm = requestOptions.body instanceof FormData;
    beginProgress();
    try {
      const response = await fetch(path, {
        headers: isForm ? undefined : { "Content-Type": "application/json", ...(requestOptions.headers || {}) },
        credentials: "same-origin",
        ...requestOptions,
      });
      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
        } catch { /* corps non JSON */ }
        throw new Error(detail);
      }
      return response.json();
    } finally {
      endProgress();
    }
  }

  /* ---------- Navigation ---------- */

  const VIEWS = {
    today: { title: "Aujourd’hui", subtitle: "Les prochaines étapes utiles, au même endroit" },
    applications: { title: "Mes candidatures", subtitle: "Chaque dossier, son avancement et sa prochaine action" },
    tracking: { title: "Suivi", subtitle: "Tes envois, réponses et relances à venir" },
    offers: { title: "Stage Hunter", subtitle: "Trouver, qualifier et préparer des stages sans quitter NAGE" },
    assistant: { title: "Assistant", subtitle: "Un espace privé pour analyser et préparer tes candidatures" },
    homework: { title: "Devoirs", subtitle: "Comprendre, résoudre et vérifier tes travaux à partir de tes documents" },
    missions: { title: "Atelier", subtitle: "État technique et améliorations de NAGE" },
    memory: { title: "Mémoire", subtitle: "Les sources locales utilisées pour t’aider" },
  };

  function setView(view, historyMode = "push") {
    if (!VIEWS[view]) return;
    state.view = view;
    for (const button of document.querySelectorAll(".nav-item")) {
      if (button.dataset.view === view) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    for (const section of document.querySelectorAll(".view")) {
      section.hidden = section.id !== `view-${view}`;
    }
    $("#viewTitle").textContent = VIEWS[view].title;
    $("#viewSubtitle").textContent = VIEWS[view].subtitle;
    const announcer = $("#srAnnounce");
    if (announcer) announcer.textContent = `${VIEWS[view].title}. ${VIEWS[view].subtitle}`;
    $("#searchBox").hidden = true;
    const languagePicker = document.querySelector(".kit-language");
    if (languagePicker) languagePicker.hidden = !new Set(["today", "applications", "tracking", "offers", "assistant"]).has(view);
    $("#scroll").scrollTop = 0;
    render(view);
    if (view === "missions" && !state.specifications && !state.specificationsLoading) loadSpecifications();
    const activeNav = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (activeNav && window.matchMedia("(max-width: 720px)").matches) {
      window.requestAnimationFrame(() => activeNav.scrollIntoView({ block: "nearest", inline: "center" }));
    }
    const destination = `#${view}`;
    if (historyMode === "replace") history.replaceState(null, "", destination);
    else if (historyMode === "push" && location.hash !== destination) history.pushState(null, "", destination);
  }

  /* ---------- Données ---------- */

  const loaders = {
    dashboard: async () => (state.dashboard = await api("/api/career/dashboard")),
    pipeline: async () => (state.pipeline = await api("/api/career/application-pipeline")),
    tracker: async () => (state.tracker = await api("/api/career/apply-tracker")),
    jobs: async () => (state.jobs = await api("/api/career/jobs?limit=300")),
    overview: async () => (state.overview = await api("/api/v5/overview")),
    missions: async () => (state.missions = await api("/api/app/missions")),
    specifications: async () => state.view === "missions" ? loadSpecifications() : null,
    documents: async () => {
      const payload = await api("/api/files");
      state.documents = payload.files || [];
      if (!state.documents.some((item) => item.file_id === state.selectedDocumentId)) {
        state.selectedDocumentId = state.documents[0]?.file_id || null;
        state.documentInspection = null;
        state.documentAnalysis = null;
      }
      if (!state.documents.some((item) => item.file_id === state.referenceDocumentId) || state.referenceDocumentId === state.selectedDocumentId) {
        const likelyReference = state.documents.find((item) => item.file_id !== state.selectedDocumentId && /corrig|solution|answer|rempli/i.test(item.name));
        state.referenceDocumentId = likelyReference?.file_id || null;
      }
      return state.documents;
    },
    study: async () => (state.studyOverview = await api("/api/study/overview")),
    health: async () => (state.health = await api("/api/health")),
  };

  async function loadAll() {
    setStatus("pending", "Connexion…");
    const results = await Promise.allSettled(
      Object.entries(loaders).map(async ([key, load]) => {
        try { await load(); delete state.errors[key]; }
        catch (e) { state.errors[key] = e.message; throw e; }
        finally { renderBadges(); render(state.view); }
      }),
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    restoreLearningDocument();
    setStatus(failed === 0 ? "online" : failed >= results.length ? "offline" : "pending",
      failed === 0 ? "Local · 127.0.0.1" : `${results.length - failed}/${results.length} sources`);
    renderBadges();
    render(state.view);
  }

  async function refresh() {
    const button = $("#refreshBtn");
    const label = $("span", button);
    const previous = label.textContent;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    label.textContent = "Actualisation…";
    try {
      await loadAll();
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      label.textContent = previous;
    }
  }

  function setStatus(kind, text) {
    const dot = $("#statusDot");
    dot.className = `status-dot ${kind}`;
    $("#statusText").textContent = text;
  }

  function renderBadges() {
    const active = state.pipeline?.pipeline?.length ?? 0;
    const badge = $("#badgeApplications");
    const bt = $("#badgeTracking");
    const due = state.tracker?.totals?.due ?? state.tracker?.totals?.overdue ?? 0;
    bt.hidden = !due; bt.textContent = String(due);
    badge.hidden = !active;
    badge.textContent = String(active);
    const workers = state.missions?.workers ?? 0;
    $("#fleetPulse").hidden = workers <= 0;
    const homework = $("#badgeHomework");
    const documentCount = state.documents?.length ?? 0;
    homework.hidden = documentCount <= 0;
    homework.textContent = String(documentCount);
  }

  /* ---------- Rendu ---------- */

  function render(view) {
    if (view === "today") renderToday();
    else if (view === "applications") renderApplications();
    else if (view === "tracking") renderTracking();
    else if (view === "offers") renderOffers();
    else if (view === "assistant") renderAssistant();
    else if (view === "homework") renderHomework();
    else if (view === "missions") renderMissions();
    else if (view === "memory") renderMemory();
    const key = { today: "dashboard", applications: "pipeline", tracking: "tracker", offers: "jobs", homework: "documents", missions: "missions", memory: "overview" }[view];
    if (key && state.errors[key] && state[key]) {
      $("#view-" + view).prepend(el("p", { class: "error-note", role: "alert" },
        `Actualisation impossible : ${state.errors[key]}. Les dernières données reçues restent affichées. Utilise Actualiser pour réessayer.`));
    }
  }

  const unavailable = (key) => state.errors[key]
    ? el("div", { class: "card padded", role: "alert" },
      el("h2", {}, "Cette source n’a pas répondu"),
      el("p", { class: "note" }, state.errors[key]),
      el("button", { class: "ghost-btn", type: "button", onclick: refresh }, "Réessayer"))
    : loading();
  const loading = () => el("div", { class: "card skeleton", role: "status", "aria-live": "polite" },
    el("span", { class: "sr-only" }, "Chargement en cours"),
    el("i", { "aria-hidden": "true" }), el("i", { "aria-hidden": "true" }), el("i", { "aria-hidden": "true" }));

  function greeting() {
    const hour = new Date().getHours();
    if (hour < 6) return "Bienvenue";
    if (hour < 12) return "Bonjour";
    if (hour < 18) return "Bon après-midi";
    return "Bonsoir";
  }

  function renderToday() {
    const host = $("#view-today");
    if (!state.dashboard) {
      host.replaceChildren(unavailable("dashboard"));
      return;
    }
    const d = state.dashboard;
    const p = state.pipeline?.pipeline ?? [];
    const active = p.filter((item) => item.progress_percent < 100).length;
    const blockers = d.jobs_total ? `${num(d.to_review)} offres à vérifier` : "Aucune offre";

    const kpis = [
      ["Offres actives", num(d.jobs_open), `${blockers}`, "◎"],
      ["Shortlist", num(d.shortlisted), "à qualifier", "★"],
      ["Entretiens actifs", num(d.interviews_active), `${num(d.interviews_total)} au total`, "◈"],
      ["Brouillons", num(d.drafts_total), "à relire avant envoi", "✎"],
    ];

    host.replaceChildren(
      el("div", { class: "card hero" },
        el("div", {},
          el("span", { class: "eyebrow" }, "Ton espace carrière"),
          el("h2", {}, `${greeting()}, voici ton cap du jour.`),
          el("p", {}, d.action_plan?.[0]
            ? `Priorité : ${d.action_plan[0].title.toLowerCase()}. ${d.action_plan[0].detail || ""}`
            : "Rien d’urgent. Tu peux explorer des offres ou avancer sur un dossier."),
          el("div", { class: "hero-actions" },
            el("button", { class: "ghost-btn primary", type: "button", onclick: () => setView("offers") }, "Explorer les offres"),
            el("button", { class: "ghost-btn", type: "button", onclick: () => setView("applications") }, "Voir mes candidatures"),
          ),
        ),
        el("div", { class: "hero-side" },
          el("div", {}, el("b", {}, num(d.jobs_total)), el("small", {}, "offres")),
          el("div", {}, el("b", {}, num(active)), el("small", {}, "dossiers en cours")),
          state.missions?.available
            ? el("div", {}, el("b", {}, `${state.missions.counts?.done ?? 0}/${Object.values(state.missions.counts || {}).reduce((a, b) => a + b, 0)}`), el("small", {}, "missions"))
            : el("div", {}, el("b", {}, "Local"), el("small", {}, "données privées")),
        ),
      ),
      el("div", { class: "grid kpi mt-14" },
        kpis.map(([label, value, foot, glyph]) =>
          el("div", { class: "card kpi-card" },
            el("div", { class: "kpi-top" },
              el("span", { class: "kpi-label" }, label),
              el("span", { class: "kpi-chip" }, glyph),
            ),
            el("div", { class: "kpi-value" }, String(value)),
            el("div", { class: "kpi-foot" }, foot),
          )),
      ),
      el("div", { class: "section-title" }, el("h2", {}, "À faire maintenant"),
        el("span", { class: "hint" }, "priorisé par impact")),
      el("div", { class: "card" }, actionPlan(d)),
      el("div", { class: "section-title" }, el("h2", {}, "Dossiers en cours"),
        el("span", { class: "hint" }, `${active} actifs`)),
      el("div", { class: "card" }, p.length ? p.slice(0, 4).map(pipelineRow) : emptyState(
        "Aucun dossier ouvert", "Génère un kit depuis une offre pour démarrer.")),
      el("div", { class: "section-title technical-section" }, el("h2", {}, "État de l’atelier"),
        el("span", { class: "hint" }, "informations techniques")),
      el("div", { class: "card" }, missionStrip()),
    );
  }

  function actionPlan(d) {
    const plan = (d.action_plan ?? []).slice(0, 4);
    if (!plan.length) return emptyState("Tout est à jour", "Aucune action prioritaire détectée.");
    return el("div", { class: "action-list" }, plan.map((item, index) =>
      el("div", {
        class: "action-row", role: "button", tabindex: "0",
        onclick: () => openTarget(item.target_view),
        onkeydown: (event) => { if (event.key === "Enter" || event.key === " ") openTarget(item.target_view); },
      },
        el("span", { class: "action-rank" }, String(index + 1)),
        el("div", { class: "action-body" },
          el("strong", {}, item.title || "Action"),
          el("span", {}, item.detail || ""),
        ),
        el("span", { class: "action-go" }, "Ouvrir →"),
      )));
  }

  function openTarget(target) {
    if (target === "discover") openCareerWorkspace("stagehunter");
    else if (target === "profile") openCareerWorkspace("profile");
    else if (target === "applications") setView("applications");
  }

  function openCareerWorkspace(section = "stagehunter") {
    state.careerSection = section;
    setView("offers");
  }

  function missionStrip() {
    const m = state.missions;
    if (!m?.available) return emptyState("Atelier au repos", "Aucune mission technique n’est active. Cela n’affecte pas tes candidatures.");
    const total = Object.values(m.counts).reduce((a, b) => a + b, 0);
    return el("div", { class: "mission-strip" },
      el("div", {}, el("b", {}, `${m.counts.done ?? 0}/${total}`), el("small", {}, "missions livrées")),
      el("div", {}, el("b", {}, String(m.workers ?? "—")), el("small", {}, "workers actifs")),
      el("div", {}, el("b", {}, String(m.load ?? "—")), el("small", {}, "charge machine")),
    );
  }

  const LANGUAGES = { en: "anglais", fr: "français", it: "italien", de: "allemand" };
  const sentStages = new Set(["submitted", "submitted_confirmed", "response_received", "interview", "offer", "rejected", "withdrawn"]);

  function pipelineStageLabel(item) {
    const labels = { submitted: "Envoi déclaré", submitted_confirmed: "Réception confirmée", approved_for_manual_submission: "Dossier relu · dépôt manuel", response_received: "Réponse reçue", interview: "Entretien", rejected: "Refus", withdrawn: "Retirée", offer: "Proposition reçue" };
    return labels[item.tracking_stage] || (item.kit_ready ? "Dossier préparé · à relire" : "Dossier à préparer");
  }

  function pipelineRow(item) {
    const sent = sentStages.has(item.tracking_stage || item.stage);
    const progress = Math.max(0, Math.min(100, Number(item.progress_percent) || 0));
    return el("div", { class: "pipeline-item" },
      el("div", { class: "pipeline-main" },
        el("strong", {}, item.title || "Dossier"),
        el("span", {}, `${item.company || "—"} · ${pipelineStageLabel(item)}`),
        item.next_action_label ? el("div", { class: "next" }, item.next_action_label) : null),
      el("div", { class: "pipeline-progress" },
        el("div", { class: "bar" }, el("i", { style: `width:${progress}%` })),
        el("small", {}, `${progress} %`)),
      el("div", { class: "offer-tags" },
        item.deadline_date ? el("span", { class: "chip amber" }, `Échéance ${formatDate(item.deadline_date)}`) : null,
        el("button", { class: "ghost-btn primary", type: "button",
          onclick: () => sent ? setView("tracking") : showApplyKit(item.job_id, item.title) },
          sent ? "Voir le suivi" : `Préparer en ${LANGUAGES[state.kitLanguage]}`)),
    );
  }

  function renderApplications() {
    const host = $("#view-applications");
    const p = state.pipeline?.pipeline;
    if (!p) { host.replaceChildren(unavailable("pipeline")); return; }
    if (!p.length) {
      host.replaceChildren(el("div", { class: "card empty-card" },
        emptyState("Ton espace candidatures est prêt", "Commence par sélectionner une offre. NAGE préparera le dossier, mais rien ne sera envoyé sans toi."),
        el("div", { class: "empty-actions" },
          el("button", { class: "ghost-btn primary", type: "button", onclick: () => setView("offers") }, "Choisir une offre"),
          el("button", { class: "ghost-btn", type: "button", onclick: () => openCareerWorkspace("stagehunter") }, "Rechercher des offres"),
        )));
      return;
    }
    const stages = new Map();
    for (const item of p) {
      const key = pipelineStageLabel(item);
      stages.set(key, (stages.get(key) ?? 0) + 1);
    }
    host.replaceChildren(
      el("div", { class: "grid kpi" }, [...stages.entries()].map(([label, count]) =>
        el("div", { class: "card kpi-card" },
          el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, label), el("span", { class: "kpi-chip" }, "◆")),
          el("div", { class: "kpi-value" }, String(count)),
          el("div", { class: "kpi-foot" }, "dossiers"),
        ))),
      el("div", { class: "section-title" }, el("h2", {}, "Pipeline détaillé"),
        el("span", { class: "hint" }, `${p.length} dossiers`)),
      el("div", { class: "card" }, p.map(pipelineRow)),
      el("p", { class: "note" },
        "Aucun envoi automatique. Les formulaires de l’employeur sont remplis et envoyés par toi. ",
        el("button", { class: "inline-action", type: "button", onclick: () => openCareerWorkspace("stagehunter") }, "Trouver une autre offre dans Stage Hunter →")),
    );
  }

  function renderOffers() {
    const host = $("#view-offers");
    const sectionLabels = {
      stagehunter: ["Stage Hunter", "Recherche internationale, critères et classement explicable"],
      profile: ["Mon profil", "Formation, langues, critères et CV approuvés"],
    };
    const [title, subtitle] = sectionLabels[state.careerSection] || sectionLabels.stagehunter;
    $("#viewTitle").textContent = title;
    $("#viewSubtitle").textContent = subtitle;
    const iframe = el("iframe", {
      class: "career-embed",
      title,
      src: `/career?embed=app#career/${encodeURIComponent(state.careerSection)}`,
      loading: "eager",
    });
    host.replaceChildren(
      el("div", { class: "career-workspace-toolbar", role: "navigation", "aria-label": "Outils Career intégrés" },
        el("button", { class: `ghost-btn ${state.careerSection === "stagehunter" ? "primary" : ""}`, type: "button", onclick: () => openCareerWorkspace("stagehunter") }, "Stage Hunter"),
        el("button", { class: `ghost-btn ${state.careerSection === "profile" ? "primary" : ""}`, type: "button", onclick: () => openCareerWorkspace("profile") }, "Mon profil"),
        el("span", { class: "workspace-note" }, "Tout reste dans NAGE · aucun envoi automatique"),
      ),
      iframe,
    );
  }

  /* ---------- Devoirs & apprentissage ---------- */

  const HOMEWORK_ACCEPT = ".pdf,.docx,.pptx,.xlsx,.xlsm,.xls,.csv,.tsv,.txt,.md";
  const TABLE_TYPES = new Set(["xlsx", "xlsm", "xls", "csv", "tsv"]);

  function selectedDocument() {
    return (state.documents || []).find((item) => item.file_id === state.selectedDocumentId) || null;
  }

  function referenceDocument() {
    return (state.documents || []).find((item) => item.file_id === state.referenceDocumentId) || null;
  }

  function chooseReferenceDocument(fileId) {
    state.referenceDocumentId = fileId && fileId !== state.selectedDocumentId ? fileId : null;
    try {
      if (state.referenceDocumentId) window.localStorage.setItem(REFERENCE_STORAGE_KEY, state.referenceDocumentId);
      else window.localStorage.removeItem(REFERENCE_STORAGE_KEY);
    } catch { /* stockage local indisponible */ }
    renderHomework();
  }

  function formatFileSize(value) {
    const kb = Number(value || 0);
    return kb >= 1024 ? `${(kb / 1024).toFixed(1)} Mo` : `${kb.toFixed(kb >= 10 ? 0 : 1)} Ko`;
  }

  function chooseDocument(fileId) {
    if (state.selectedDocumentId !== fileId) {
      state.selectedDocumentId = fileId;
      state.documentInspection = null;
      state.documentAnalysis = null;
      state.homeworkTasks = null;
      state.homeworkTaskBusy = null;
      state.homeworkChat = [];
      state.studySyllabus = null;
      state.studySession = null;
      state.studyQuestion = null;
      state.studyCorrection = null;
      if (state.referenceDocumentId === fileId) {
        state.referenceDocumentId = null;
        try { window.localStorage.removeItem(REFERENCE_STORAGE_KEY); } catch { /* stockage local indisponible */ }
      }
      try { window.localStorage.setItem(DOCUMENT_STORAGE_KEY, fileId); } catch { /* stockage local indisponible */ }
    }
    renderHomework();
  }

  function restoreLearningDocument() {
    if (readSelectedDocumentId() || !state.documents?.length || !state.studyOverview?.courses?.length) return;
    const courseNames = new Set(state.studyOverview.courses.map((course) => course.title));
    const learningFile = state.documents.find((file) => courseNames.has(file.name));
    if (learningFile) {
      state.selectedDocumentId = learningFile.file_id;
      try { window.localStorage.setItem(DOCUMENT_STORAGE_KEY, learningFile.file_id); } catch { /* stockage local indisponible */ }
    }
  }

  function localTutorStatus() {
    if (!state.health) return { usable: true, label: "État du modèle local en cours de vérification" };
    const ollama = state.health.providers?.ollama;
    if (ollama?.configured && ollama?.model) return { usable: true, label: `Modèle local configuré · ${ollama.model} · une première réponse peut être lente` };
    return { usable: false, label: "Tuteur conversationnel en pause · aucun modèle Ollama configuré" };
  }

  async function uploadHomework(files) {
    const accepted = [...files].slice(0, 12);
    if (!accepted.length || state.homeworkUploading) return;
    state.homeworkUploading = true;
    renderHomework();
    const form = new FormData();
    accepted.forEach((file) => form.append("files", file, file.name));
    try {
      const payload = await api("/api/files/upload", { method: "POST", body: form });
      state.documents = payload.files || [];
      const successful = (payload.results || []).filter((item) => item.file_id);
      const failures = (payload.results || []).filter((item) => item.error);
      if (successful.length) chooseDocument(successful[successful.length - 1].file_id);
      failures.forEach((item) => notify(`${item.name || "Fichier"} : ${item.error}`, true));
      if (successful.length) notify(`${successful.length} copie${successful.length > 1 ? "s" : ""} de travail ajoutée${successful.length > 1 ? "s" : ""}. Les originaux sont intacts.`);
      renderBadges();
    } catch (error) {
      notify(`Import impossible : ${error.message}`, true);
    } finally {
      state.homeworkUploading = false;
      renderHomework();
    }
  }

  async function inspectHomework(analyze = false) {
    const file = selectedDocument();
    if (!file) return;
    const key = analyze ? "documentAnalysis" : "documentInspection";
    state[key] = { loading: true };
    renderHomework();
    try {
      state[key] = await api(analyze ? "/api/actions/analyze" : "/api/actions/inspect", {
        method: "POST",
        body: JSON.stringify({ file_id: file.file_id, sheet_name: "" }),
      });
      if (!analyze && state[key]?.kind === "document") await loadHomeworkTasks(file.file_id);
    } catch (error) {
      state[key] = { error: error.message };
    }
    renderHomework();
  }

  async function loadHomeworkTasks(fileId) {
    try {
      state.homeworkTasks = await api(`/api/study/homework/${encodeURIComponent(fileId)}/tasks`);
    } catch (error) {
      state.homeworkTasks = { error: error.message, tasks: [] };
    }
  }

  async function updateHomeworkTask(taskId, status, notes) {
    const file = selectedDocument();
    if (!file || state.homeworkTaskBusy) return;
    state.homeworkTaskBusy = taskId;
    renderHomework();
    try {
      state.homeworkTasks = await api(`/api/study/homework/${encodeURIComponent(file.file_id)}/tasks/${encodeURIComponent(taskId)}`, {
        method: "PUT",
        body: JSON.stringify({ status, notes }),
      });
      notify("Progression enregistrée localement.");
    } catch (error) {
      notify(`Progression non enregistrée : ${error.message}`, true);
    } finally {
      state.homeworkTaskBusy = null;
      renderHomework();
    }
  }

  function previewTable(rows) {
    if (!Array.isArray(rows) || !rows.length) return el("p", { class: "note" }, "Aucune ligne exploitable dans cet aperçu.");
    const columns = Object.keys(rows[0]).slice(0, 8);
    const head = el("thead", {}, el("tr", {}, columns.map((column) => el("th", {}, column))));
    const body = el("tbody", {}, rows.slice(0, 6).map((row) =>
      el("tr", {}, columns.map((column) => el("td", {},
        row[column] === null || row[column] === undefined ? "—" : String(row[column]),
      ))),
    ));
    return el("div", { class: "homework-table-wrap" }, el("table", { class: "homework-table" },
      head,
      body,
    ));
  }

  function inspectionContent(result) {
    if (!result) return null;
    if (result.loading) return loading();
    if (result.error) return el("p", { class: "error-note", role: "alert" }, result.error);
    if (result.kind === "document") {
      const outline = result.outline || {};
      return el("section", { class: "homework-reading" },
        el("div", { class: "homework-section-heading" }, el("h3", {}, "Lecture locale"), el("span", {}, `${num(result.characters)} caractères lus`)),
        outline.sections?.length ? el("div", { class: "homework-outline" },
          el("h4", {}, `${outline.section_count} section${outline.section_count > 1 ? "s" : ""} repérée${outline.section_count > 1 ? "s" : ""}`),
          el("div", { class: "homework-outline-sections" }, outline.sections.map((section) => el("span", {}, section))),
        ) : null,
        outline.tasks?.length ? el("div", { class: "homework-outline" },
          el("h4", {}, `${outline.task_count} question${outline.task_count > 1 ? "s" : ""} ou tâche${outline.task_count > 1 ? "s" : ""} intégrée${outline.task_count > 1 ? "s" : ""} au plan de travail ci-dessous`),
        ) : null,
        el("details", { class: "homework-source-details" },
          el("summary", {}, "Voir le texte extrait"),
          el("pre", { class: "homework-excerpt" }, result.excerpt || "Aucun texte exploitable. Le PDF est peut-être un scan sans couche texte."),
          result.truncated ? el("p", { class: "note" }, "L’aperçu est raccourci à l’écran. L’assistant local peut rechercher dans le document complet dans la limite de lecture sécurisée.") : null,
        ),
      );
    }
    const sheets = result.sheets || { [result.sheet || "Tableau"]: result };
    return el("section", { class: "homework-reading" },
      el("div", { class: "homework-section-heading" }, el("h3", {}, "Structure du classeur"), el("span", {}, `${Object.keys(sheets).length} feuille${Object.keys(sheets).length > 1 ? "s" : ""}`)),
      Object.entries(sheets).map(([name, sheet]) => el("details", { class: "homework-sheet", open: Object.keys(sheets)[0] === name },
        el("summary", {}, `${name} · ${sheet.rows_sampled ?? sheet.rows ?? "?"} lignes · ${sheet.columns ?? "?"} colonnes`),
        sheet.column_names?.length ? el("p", { class: "note" }, `Colonnes : ${sheet.column_names.join(", ")}`) : null,
        previewTable(sheet.preview),
      )),
    );
  }

  function analysisContent(result) {
    if (!result) return null;
    if (result.loading) return loading();
    if (result.error) return el("p", { class: "error-note", role: "alert" }, result.error);
    const statistics = Object.entries(result.numeric_statistics || {}).slice(0, 12);
    return el("section", { class: "homework-reading" },
      el("div", { class: "homework-section-heading" }, el("h3", {}, `Analyse · ${result.sheet || "tableau"}`), el("span", {}, `${result.rows || 0} lignes · ${result.columns || 0} colonnes`)),
      statistics.length ? el("div", { class: "homework-stats" }, statistics.map(([name, stat]) =>
        el("article", {}, el("strong", {}, name), el("span", {}, `Moyenne ${stat.mean ?? "—"}`), el("small", {}, `Min ${stat.min ?? "—"} · Max ${stat.max ?? "—"} · n=${stat.count ?? "—"}`))))
        : el("p", { class: "note" }, "Aucune colonne numérique n’a été détectée automatiquement."),
      result.note ? el("p", { class: "note" }, result.note) : null,
    );
  }

  function homeworkTaskWorkspace(payload) {
    if (!payload) return null;
    if (payload.error) return el("p", { class: "error-note", role: "alert" }, `Plan de travail indisponible : ${payload.error}`);
    const tasks = payload.tasks || [];
    if (!tasks.length) return null;
    const statuses = [
      ["todo", "À faire"],
      ["doing", "En cours"],
      ["review", "À vérifier"],
      ["done", "Terminé"],
    ];
    const labels = Object.fromEntries(statuses);
    const taskRows = tasks.map((task) => {
      const select = el("select", { "aria-label": `État de la question ${task.index}` }, statuses.map(([value, label]) =>
        el("option", { value, selected: task.status === value }, label)));
      const notes = el("textarea", {
        rows: "4",
        maxlength: "12000",
        placeholder: "Ta démarche, tes calculs, les points à vérifier…",
        "aria-label": `Notes pour la question ${task.index}`,
      });
      notes.value = task.notes || "";
      const busy = state.homeworkTaskBusy === task.id;
      const form = el("form", { class: "homework-task-editor", onsubmit: (event) => {
        event.preventDefault();
        updateHomeworkTask(task.id, select.value, notes.value);
      } },
      el("label", {}, el("span", {}, "État"), select),
      el("label", { class: "task-notes" }, el("span", {}, "Notes de résolution"), notes),
      el("div", { class: "homework-task-actions" },
        el("small", {}, "Enregistré uniquement sur ce Mac"),
        el("button", { class: "ghost-btn primary", type: "submit", disabled: Boolean(state.homeworkTaskBusy) }, busy ? "Enregistrement…" : "Enregistrer"),
      ));
      return el("details", { class: `homework-task ${task.status}`, open: task.status === "doing" || busy },
        el("summary", {},
          el("span", { class: "homework-task-index" }, String(task.index)),
          el("strong", {}, task.label),
          el("em", {}, labels[task.status] || "À faire"),
        ),
        form,
      );
    });
    return el("section", { class: "homework-task-workspace", "aria-label": "Plan de résolution du devoir" },
      el("div", { class: "homework-section-heading" },
        el("div", {}, el("h3", {}, "Plan de résolution"), el("p", {}, "Avance question par question et conserve ta démarche, sans modifier le document original.")),
        el("span", {}, `${payload.completed || 0}/${payload.total || tasks.length} terminée${payload.completed === 1 ? "" : "s"}`),
      ),
      el("div", { class: "homework-task-progress", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(payload.completion_percent || 0) },
        el("i", { style: `width:${Math.max(0, Math.min(100, payload.completion_percent || 0))}%` })),
      el("div", { class: "homework-task-list" }, taskRows),
    );
  }

  function homeworkConversation() {
    if (!state.homeworkChat.length) {
      return el("div", { class: "homework-welcome" },
        el("strong", {}, "Travaille avec NAGE, sans rendre un devoir à ta place."),
        el("p", {}, "Demande une explication, un plan de résolution, un indice ou une vérification. Les réponses doivent rester fondées sur le document sélectionné et signaler ce qui manque."));
    }
    return state.homeworkChat.map((message) => el("div", { class: `msg ${message.role === "user" ? "me" : "ai"}` },
      el("div", { class: "bubble" }, message.content),
      el("small", {}, message.role === "user" ? "Toi" : message.meta || "NAGE · local"),
    ));
  }

  async function askHomework(message) {
    const file = selectedDocument();
    const reference = referenceDocument();
    const prompt = String(message || "").trim();
    if (!file) { notify("Ajoute et sélectionne d’abord un document.", true); return; }
    if (!prompt || state.homeworkSending) return;
    state.homeworkSending = true;
    state.homeworkChat.push({ role: "user", content: prompt });
    renderHomework();
    try {
      const result = await api("/api/v5/chat", { method: "POST", body: JSON.stringify({
        message: prompt,
        selected_file_ids: [file.file_id, reference?.file_id].filter(Boolean),
        history: state.homeworkChat.slice(-9).map(({ role, content }) => ({ role, content })),
        mode: "offline",
        provider: "ollama",
        model: "auto",
        allow_write: false,
        memory_project_id: null,
        allow_cloud_context: false,
      }) });
      state.homeworkChat.push({
        role: "assistant",
        content: result.answer || "La demande est terminée sans réponse textuelle.",
        meta: `NAGE · ${result.provider || "local"}${result.model ? ` · ${result.model}` : ""}`,
      });
    } catch (error) {
      state.homeworkChat.push({ role: "assistant", content: `Je n’ai pas pu répondre localement : ${error.message}`, meta: "Erreur locale" });
    } finally {
      state.homeworkSending = false;
      renderHomework();
    }
  }

  function verifyHomeworkWithReference() {
    const reference = referenceDocument();
    if (!reference) {
      notify("Choisis d’abord le corrigé ou le document de référence.", true);
      return;
    }
    askHomework(
      `Compare méthodiquement le devoir sélectionné avec le document de référence « ${reference.name} ». `
      + "Sépare : 1) résultats confirmés, 2) écarts numériques, 3) erreurs de raisonnement, 4) éléments impossibles à vérifier. "
      + "N’invente aucune valeur, cite les passages ou cellules utilisés, distingue une approximation d’une égalité exacte, "
      + "et termine par les corrections prioritaires. Si un calcul n’est pas vérifiable directement, dis-le explicitement.",
    );
  }

  function studyCourseFor(file) {
    if (!file) return null;
    if (state.studySyllabus?.title === file.name) return state.studySyllabus;
    return (state.studyOverview?.courses || []).find((course) => course.title === file.name) || null;
  }

  function resumableStudySession(course) {
    if (!course) return null;
    return (state.studyOverview?.progress?.sessions || []).find((session) =>
      session.syllabus_id === course.id && !["terminee", "abandonnee"].includes(session.status));
  }

  async function createStudyCourse() {
    const file = selectedDocument();
    if (!file || state.studyBusy) return;
    state.studyBusy = true;
    state.studyCorrection = null;
    renderHomework();
    try {
      state.studySyllabus = await api("/api/study/courses", {
        method: "POST",
        body: JSON.stringify({ file_id: file.file_id, requested_topics: [] }),
      });
      state.studyOverview = await api("/api/study/overview");
      notify(`${state.studySyllabus.notion_count || 0} notion(s) structurée(s) pour la révision.`);
    } catch (error) {
      notify(`Parcours de révision indisponible : ${error.message}`, true);
    } finally {
      state.studyBusy = false;
      renderHomework();
    }
  }

  async function startStudySession(syllabusId) {
    if (!syllabusId || state.studyBusy) return;
    state.studyBusy = true;
    state.studyCorrection = null;
    renderHomework();
    try {
      const session = await api(`/api/study/courses/${encodeURIComponent(syllabusId)}/sessions`, {
        method: "POST", body: JSON.stringify({ size: 5 }),
      });
      state.studySession = { ...session, answered: 0, report: null };
      state.studyQuestion = session.question;
    } catch (error) {
      notify(`Séance impossible : ${error.message}`, true);
    } finally {
      state.studyBusy = false;
      renderHomework();
    }
  }

  async function resumeStudySession(sessionId) {
    if (!sessionId || state.studyBusy) return;
    state.studyBusy = true;
    state.studyCorrection = null;
    renderHomework();
    try {
      const session = await api(`/api/study/sessions/${encodeURIComponent(sessionId)}`);
      state.studySession = { ...session, report: null };
      state.studyQuestion = session.question;
      notify(`Séance reprise à la question ${(session.answered || 0) + 1}.`);
    } catch (error) {
      notify(`Reprise impossible : ${error.message}`, true);
    } finally {
      state.studyBusy = false;
      renderHomework();
    }
  }

  async function submitStudyAnswer(value) {
    const answer = String(value || "").trim();
    if (!answer || !state.studySession || !state.studyQuestion || state.studyBusy) return;
    state.studyBusy = true;
    renderHomework();
    try {
      const payload = await api(`/api/study/sessions/${encodeURIComponent(state.studySession.session_id)}/answers`, {
        method: "POST",
        body: JSON.stringify({ question_id: state.studyQuestion.id, value: answer }),
      });
      state.studyCorrection = payload.correction;
      state.studyQuestion = payload.question;
      state.studySession.answered = (state.studySession.answered || 0) + 1;
      state.studySession.report = payload.report;
      state.studyOverview = await api("/api/study/overview");
    } catch (error) {
      notify(`Réponse non enregistrée : ${error.message}`, true);
    } finally {
      state.studyBusy = false;
      renderHomework();
    }
  }

  function studyPanel(file) {
    const course = studyCourseFor(file);
    const savedSession = resumableStudySession(course);
    const notions = state.studySyllabus?.title === file.name ? (state.studySyllabus.notions || []) : [];
    const session = state.studySession;
    const question = state.studyQuestion;
    const correction = state.studyCorrection;
    const answerInput = el("textarea", { rows: "3", maxlength: "4000", placeholder: "Écris ta réponse ou ton raisonnement…" });
    const questionForm = question ? el("form", { class: "study-question", onsubmit: (event) => { event.preventDefault(); submitStudyAnswer(answerInput.value); } },
      el("div", { class: "study-progress" }, el("span", {}, `Question ${(session?.answered || 0) + 1} sur ${session?.total || "?"}`), el("i", {}, el("b", { style: `width:${Math.min(100, ((session?.answered || 0) / Math.max(1, session?.total || 1)) * 100)}%` }))),
      el("h4", {}, question.prompt || "Question"),
      question.options?.length ? el("div", { class: "study-options" }, question.options.map((option) =>
        el("button", { type: "button", disabled: state.studyBusy, onclick: () => submitStudyAnswer(option.id) }, option.label))) : answerInput,
      question.options?.length ? null : el("button", { class: "ghost-btn primary", type: "submit", disabled: state.studyBusy }, "Vérifier ma réponse"),
      question.source_refs?.[0]?.citation?.label ? el("small", {}, `Source : ${question.source_refs[0].citation.label}`) : null,
    ) : null;
    const correctionCard = correction ? el("article", { class: `study-correction ${correction.status || ""}` },
      el("strong", {}, correction.status === "correct" ? "Correct" : correction.status === "partiel" ? "À compléter" : correction.status === "incorrect" ? "À reprendre" : "À relire avec un humain ou le tuteur"),
      el("p", {}, correction.explanation || "Correction enregistrée."),
      correction.expected_answer ? el("details", {}, el("summary", {}, "Voir la réponse de référence"), el("p", {}, String(correction.expected_answer))) : null,
      correction.errors?.length ? el("ul", {}, correction.errors.map((item) => el("li", {}, item))) : null,
    ) : null;
    const report = session?.report;
    return el("section", { class: "study-panel" },
      el("div", { class: "homework-section-heading" }, el("h3", {}, "Parcours d’apprentissage"), el("span", {}, "local · progression persistante")),
      !course ? el("div", { class: "study-intro" },
        el("div", {}, el("strong", {}, "Transformer ce document en cours révisable"), el("p", {}, "NAGE extrait les notions, crée des questions sourcées et mémorise uniquement ta progression locale.")),
        el("button", { class: "ghost-btn primary", type: "button", disabled: state.studyBusy, onclick: createStudyCourse }, state.studyBusy ? "Structuration…" : "Créer mon parcours"),
      ) : null,
      course && !session ? el("div", { class: "study-ready" },
        el("div", {}, el("strong", {}, course.title), el("p", {}, `${course.notion_count ?? notions.length ?? "?"} notion(s) · séances courtes et corrections vérifiables`)),
        el("div", { class: "study-ready-actions" },
          savedSession ? el("button", { class: "ghost-btn primary", type: "button", disabled: state.studyBusy, onclick: () => resumeStudySession(savedSession.id) }, state.studyBusy ? "Reprise…" : "Reprendre ma séance") : null,
          el("button", { class: `ghost-btn ${savedSession ? "" : "primary"}`, type: "button", disabled: state.studyBusy, onclick: () => startStudySession(course.id) }, state.studyBusy ? "Préparation…" : "Nouvelle séance · 5 questions"),
        ),
      ) : null,
      notions.length ? el("details", { class: "study-notions" }, el("summary", {}, `Voir les ${notions.length} notions détectées`),
        el("ul", {}, notions.slice(0, 24).map((notion) => el("li", {}, el("strong", {}, notion.title), el("span", {}, notion.statement))))) : null,
      correctionCard,
      questionForm,
      report ? el("div", { class: "study-report" }, el("strong", {}, "Séance terminée"), el("p", {}, `${report.answered}/${report.total} réponses enregistrées. Les notions difficiles restent planifiées pour une prochaine révision.`),
        el("button", { class: "ghost-btn", type: "button", onclick: () => { state.studySession = null; state.studyQuestion = null; state.studyCorrection = null; renderHomework(); } }, "Terminer")) : null,
    );
  }

  function renderHomework() {
    const host = $("#view-homework");
    if (!state.documents) { host.replaceChildren(unavailable("documents")); return; }
    const file = selectedDocument();
    const tutor = localTutorStatus();
    const fileInput = el("input", { class: "sr-only", type: "file", multiple: "multiple", accept: HOMEWORK_ACCEPT, id: "homeworkFileInput" });
    fileInput.addEventListener("change", () => { uploadHomework(fileInput.files); fileInput.value = ""; });
    const drop = el("div", { class: `homework-drop${state.homeworkUploading ? " busy" : ""}`, tabindex: "0", role: "button", "aria-label": "Ajouter des documents de devoir" },
      el("strong", {}, state.homeworkUploading ? "Copie locale en cours…" : "Ajouter un devoir ou un cours"),
      el("span", {}, "PDF, Word, PowerPoint, Excel, CSV ou texte · 50 Mo maximum par fichier"),
      el("small", {}, "NAGE travaille sur une copie locale et ne modifie jamais l’original."),
      el("button", { class: "ghost-btn primary", type: "button", disabled: state.homeworkUploading, onclick: (event) => { event.stopPropagation(); fileInput.click(); } }, "Choisir des fichiers"),
      fileInput,
    );
    drop.addEventListener("click", (event) => { if (event.target === drop || event.target.tagName === "STRONG" || event.target.tagName === "SPAN" || event.target.tagName === "SMALL") fileInput.click(); });
    drop.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.click(); } });
    for (const type of ["dragenter", "dragover"]) drop.addEventListener(type, (event) => { event.preventDefault(); drop.classList.add("dragging"); });
    for (const type of ["dragleave", "drop"]) drop.addEventListener(type, (event) => { event.preventDefault(); drop.classList.remove("dragging"); });
    drop.addEventListener("drop", (event) => uploadHomework(event.dataTransfer.files));

    const filterValue = state.documentFilter.trim().toLocaleLowerCase("fr");
    const matchingDocuments = (item) => `${item.name} ${item.type || ""}`.toLocaleLowerCase("fr").includes(filterValue);
    const visibleCount = state.documents.filter(matchingDocuments).length;
    const libraryCount = el("span", {}, filterValue ? `${visibleCount}/${state.documents.length}` : String(state.documents.length));
    const filterInput = el("input", { type: "search", value: state.documentFilter, placeholder: "Rechercher un document…", "aria-label": "Rechercher dans mes documents" });
    const noFilterResult = el("p", { class: "homework-filter-empty", hidden: visibleCount > 0 }, "Aucun document ne correspond à cette recherche.");
    const fileList = state.documents.length ? el("div", { class: "homework-files" }, state.documents.map((item) => {
      const course = studyCourseFor(item);
      return el("button", { class: `homework-file${item.file_id === state.selectedDocumentId ? " selected" : ""}`, type: "button", hidden: !matchingDocuments(item), "data-document-search": `${item.name} ${item.type || ""}`.toLocaleLowerCase("fr"), onclick: () => chooseDocument(item.file_id) },
          el("span", { class: "homework-file-type" }, String(item.type || "doc").slice(0, 4).toUpperCase()),
          el("span", {}, el("strong", {}, item.name), el("small", {}, `${formatFileSize(item.size_kb)} · ${item.modified}`), course ? el("em", { class: "homework-course-badge" }, "Parcours créé") : null),
        );
    })) : emptyState("Aucun document", "Ajoute ton sujet, ton cours ou ton fichier de calcul.");
    filterInput.addEventListener("input", () => {
      state.documentFilter = filterInput.value;
      const query = state.documentFilter.trim().toLocaleLowerCase("fr");
      let count = 0;
      for (const button of fileList.querySelectorAll("[data-document-search]")) {
        const matches = button.dataset.documentSearch.includes(query);
        button.hidden = !matches;
        if (matches) count += 1;
      }
      libraryCount.textContent = query ? `${count}/${state.documents.length}` : String(state.documents.length);
      noFilterResult.hidden = count > 0;
    });
    const library = el("aside", { class: "homework-library", "aria-label": "Documents de travail" },
      el("div", { class: "homework-section-heading" }, el("h2", {}, "Mes documents"), libraryCount),
      state.documents.length ? el("label", { class: "homework-filter" }, el("span", { class: "sr-only" }, "Rechercher dans mes documents"), filterInput) : null,
      fileList,
      state.documents.length ? noFilterResult : null,
    );

    let workspace = el("section", { class: "homework-main" }, emptyState("Sélectionne un document", "NAGE peut lire un PDF ou Word, structurer un classeur Excel et t’aider à raisonner dessus."));
    if (file) {
      const isTable = TABLE_TYPES.has(String(file.type || "").toLowerCase());
      const quickPrompts = [
        ["Comprendre le sujet", "Explique précisément ce que ce devoir demande, les livrables attendus et les informations importantes du document. Signale clairement toute ambiguïté."],
        ["Construire un plan", "Propose un plan de résolution étape par étape. Donne d’abord la méthode et les contrôles à faire, sans inventer de donnée absente."],
        ["M’expliquer le cours", "Explique les concepts indispensables pour réussir ce devoir, avec des exemples simples reliés au document."],
        ["Vérifier mon raisonnement", "Aide-moi à vérifier mon raisonnement. Commence par me demander ma démarche ou mon résultat, puis contrôle chaque étape à partir du document."],
      ];
      const referenceOptions = (state.documents || []).filter((item) => item.file_id !== file.file_id);
      const referenceSelect = el("select", { "aria-label": "Corrigé ou document de référence" },
        el("option", { value: "" }, "Choisir un corrigé ou une référence…"),
        referenceOptions.map((item) => el("option", { value: item.file_id, selected: item.file_id === state.referenceDocumentId }, item.name)));
      referenceSelect.addEventListener("change", () => chooseReferenceDocument(referenceSelect.value));
      const referencePanel = el("section", { class: "homework-reference", "aria-label": "Vérification avec un corrigé" },
        el("div", {},
          el("strong", {}, "Vérifier avec un corrigé"),
          el("p", {}, "NAGe compare les deux copies locales, cite ses sources et signale ce qu’il ne peut pas confirmer. L’analyse reste à relire : ce n’est pas une certification indépendante.")),
        el("div", { class: "homework-reference-actions" },
          referenceSelect,
          el("button", { class: "ghost-btn primary", type: "button", disabled: state.homeworkSending || !state.referenceDocumentId || !tutor.usable, onclick: verifyHomeworkWithReference }, state.homeworkSending ? "Comparaison…" : "Comparer maintenant")),
      );
      const chatInput = el("textarea", { rows: "3", maxlength: "12000", placeholder: "Pose une question sur ce devoir…" });
      const chatForm = el("form", { class: "homework-composer", onsubmit: (event) => { event.preventDefault(); const prompt = chatInput.value; chatInput.value = ""; askHomework(prompt); } },
        chatInput,
        el("div", {}, el("span", {}, "Mode local · aucun document envoyé dans le cloud"), el("button", { class: "send-btn", type: "submit", disabled: state.homeworkSending }, state.homeworkSending ? "Réflexion…" : "Demander")),
      );
      workspace = el("section", { class: "homework-main" },
        el("header", { class: "homework-document-head" },
          el("div", {}, el("span", { class: "eyebrow" }, `${String(file.type || "document").toUpperCase()} · copie locale`), el("h2", {}, file.name), el("p", {}, `${formatFileSize(file.size_kb)} · original conservé sans modification`)),
          el("div", { class: "homework-actions" },
            el("button", { class: "ghost-btn", type: "button", onclick: () => inspectHomework(false) }, "Lire et structurer"),
            isTable ? el("button", { class: "ghost-btn", type: "button", onclick: () => inspectHomework(true) }, "Analyser les chiffres") : null,
          ),
        ),
        el("div", { class: "homework-prompts", "aria-label": "Démarrages rapides" }, quickPrompts.map(([label, prompt]) =>
          el("button", { type: "button", onclick: () => askHomework(prompt), disabled: state.homeworkSending || !tutor.usable, title: tutor.usable ? "" : tutor.label }, label))),
        referencePanel,
        inspectionContent(state.documentInspection),
        homeworkTaskWorkspace(state.homeworkTasks),
        analysisContent(state.documentAnalysis),
        studyPanel(file),
        el("section", { class: "homework-tutor" },
          el("div", { class: "homework-section-heading" }, el("h3", {}, "Tuteur de travail"), el("span", { class: tutor.usable ? "tutor-status ready" : "tutor-status paused" }, tutor.label)),
          !tutor.usable ? el("div", { class: "homework-model-note", role: "status" },
            el("strong", {}, "Les outils d’apprentissage restent disponibles."),
            el("span", {}, "Lecture, analyse Excel, parcours, quiz et progression fonctionnent sans modèle. Démarre Ollama pour les explications libres.")) : null,
          el("div", { class: "homework-chat", "aria-live": "polite" }, homeworkConversation(), state.homeworkSending ? el("div", { class: "msg ai" }, el("div", { class: "bubble" }, "Je lis le document et je prépare une réponse vérifiable…")) : null),
          chatForm,
        ),
      );
      chatInput.disabled = !tutor.usable;
      chatForm.querySelector("button[type=submit]").disabled = state.homeworkSending || !tutor.usable;
    }
    const progress = state.studyOverview?.progress || {};
    const progressStats = progress.stats || {};
    const reviewCount = progress.notions_to_review?.length || 0;
    const documentCount = state.documents.length;
    const courseCount = state.studyOverview?.courses?.length || 0;
    const questionsSeen = progressStats.questions_seen || 0;
    const overview = el("section", { class: "homework-overview", "aria-label": "Aperçu de l’espace d’apprentissage" },
      el("article", {}, el("strong", {}, num(documentCount)), el("span", {}, documentCount === 1 ? "document local" : "documents locaux")),
      el("article", {}, el("strong", {}, num(courseCount)), el("span", {}, courseCount === 1 ? "parcours créé" : "parcours créés")),
      el("article", {}, el("strong", {}, num(questionsSeen)), el("span", {}, questionsSeen === 1 ? "question travaillée" : "questions travaillées")),
      el("article", { class: reviewCount ? "attention" : "" }, el("strong", {}, num(reviewCount)), el("span", {}, reviewCount === 1 ? "notion à revoir" : "notions à revoir")),
    );
    host.replaceChildren(drop, overview, el("div", { class: "homework-layout" }, library, workspace));
    const log = $(".homework-chat", host);
    if (log) log.scrollTop = log.scrollHeight;
  }

  function renderAssistant() {
    const host = $("#view-assistant");
    if (host.dataset.mounted === "1") return;
    host.dataset.mounted = "1";
    host.replaceChildren(
      el("div", { class: "card assistant-wrap" },
        el("div", { class: "chat-log", id: "chatLog" },
          el("div", { class: "msg ai" },
            el("div", { class: "bubble" },
              "NAGE en ligne. Je peux analyser une offre, préparer un dossier, résumer un document ou chercher dans ta mémoire. Le mode Hors ligne est actif par défaut : rien ne quitte ton Mac. La réponse locale peut prendre jusqu’à une minute."),
            el("small", {}, "NAGE · local"),
          ),
        ),
        el("form", { class: "composer", id: "chatForm" },
          el("textarea", { id: "chatInput", rows: "2", placeholder: "Demande-moi quelque chose… (Entrée pour envoyer)" }),
          el("div", { class: "composer-row" },
            el("div", { class: "modes", role: "group", "aria-label": "Mode de l’assistant" },
              [["offline", "Hors ligne"], ["automatic", "Automatique"]].map(([mode, label]) =>
                el("button", {
                  type: "button", class: mode === "offline" ? "on" : "",
                  onclick: (event) => {
                    state.chatMode = mode;
                    for (const b of event.currentTarget.parentElement.children) b.classList.toggle("on", b === event.currentTarget);
                  },
                }, label))),
            el("button", { type: "submit", class: "send-btn" },
              "Envoyer",
              el("span", { html: '<svg viewBox="0 0 24 24"><path d="M3 20.5l18-8.5L3 3.5v6.4L14 12 3 14.1v6.4z"/></svg>' }),
            ),
          ),
        ),
      ),
    );
    $("#chatForm").addEventListener("submit", sendChat);
    const input = $("#chatInput");
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        $("#chatForm").requestSubmit();
      }
    });
  }

  async function sendChat(event) {
    event.preventDefault();
    if (state.sending) return;
    const input = $("#chatInput");
    const message = input.value.trim();
    if (!message) return;
    state.sending = true;
    const sendBtn = $(".send-btn");
    sendBtn.disabled = true;
    appendMessage("me", message, "Toi");
    input.value = "";
    input.style.height = "auto";
    state.chat.push({ role: "user", content: message });
    const typing = el("div", { class: "msg ai", id: "typing" },
      el("div", { class: "bubble" },
        el("span", { class: "typing" }, el("i"), el("i"), el("i"))),
      el("small", {}, "réflexion…"));
    $("#chatLog").append(typing);
    $("#chatLog").scrollTop = $("#chatLog").scrollHeight;

    try {
      const payload = {
        message,
        selected_file_ids: [],
        history: state.chat.slice(-10),
        mode: state.chatMode === "offline" ? "offline" : "automatic",
        provider: state.chatMode === "offline" ? "ollama" : "auto",
        model: "auto",
        allow_write: false,
        memory_project_id: null,
        allow_cloud_context: false,
      };
      const reply = await api("/api/v5/chat", { method: "POST", body: JSON.stringify(payload) });
      const text = reply.answer || reply.response || reply.text || reply.content || "Je n’ai pas de réponse exploitable.";
      state.chat.push({ role: "assistant", content: text });
      typing.remove();
      appendMessage("ai", text, `NAGE · ${reply.provider || "local"}${reply.model ? ` · ${reply.model}` : ""}`);
    } catch (error) {
      typing.remove();
      appendMessage("ai", `Assistant indisponible : ${error.message}\n\nAstuce : le mode Hors ligne utilise Ollama en local. Vérifie qu’Ollama tourne (menu Ollama) et qu’un modèle est installé, ou passe en mode Automatique.`, "erreur");
    } finally {
      state.sending = false;
      sendBtn.disabled = false;
      $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
    }
  }

  function appendMessage(kind, text, meta) {
    const log = $("#chatLog");
    log.append(el("div", { class: `msg ${kind}` },
      el("div", { class: "bubble" }, text),
      el("small", {}, meta || ""),
    ));
    log.scrollTop = log.scrollHeight;
  }

  async function specificationRequest(path, options = {}, download = false) {
    if (!state.workshopToken) {
      const status = await api("/api/devkit/status");
      state.workshopToken = status.workshop_token;
      if (!state.workshopToken) throw new Error("Recharge NAGE pour ouvrir l’atelier local.");
    }
    const requestOptions = {
      ...options,
      headers: { "Content-Type": "application/json", "X-Workshop-Token": state.workshopToken },
    };
    const url = `/api/devkit/specifications${path}`;
    if (!download) return api(url, requestOptions);
    beginProgress();
    try {
      const response = await fetch(url, { ...requestOptions, credentials: "same-origin" });
      if (!response.ok) {
        let message = "Le brief n’a pas pu être téléchargé.";
        try { const error = await response.json(); if (typeof error.detail === "string") message = error.detail; } catch { /* réponse non JSON */ }
        throw new Error(message);
      }
      return response.blob();
    } finally { endProgress(); }
  }

  function specificationFormFrom(template) {
    return {
      templateId: template?.id || "",
      title: template?.title || "",
      objective: template?.objective || "",
      acceptance: (template?.acceptance || []).join("\n"),
      selected_files: (template?.selected_files || []).join("\n"),
      targeted_tests: (template?.targeted_tests || []).join("\n"),
    };
  }

  async function loadSpecifications() {
    if (state.specificationsLoading) return state.specifications;
    state.specificationsLoading = true;
    delete state.errors.specifications;
    try {
      state.specifications = await specificationRequest("");
      if (!state.specificationForm) {
        const templates = state.specifications.templates || [];
        state.specificationForm = specificationFormFrom(templates.find((item) => /career|candidature|stage/i.test(item.id + " " + item.title)) || templates[0]);
      }
    } catch (error) { state.errors.specifications = error.message; }
    finally {
      state.specificationsLoading = false;
      if (state.view === "missions") renderMissions();
    }
    return state.specifications;
  }

  async function specificationAction(id, action, button) {
    if (state.specificationBusy) return;
    state.specificationBusy = id;
    if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); }
    try {
      if (action === "queue") {
        await specificationRequest(`/${encodeURIComponent(id)}/queue`, { method: "POST", body: "{}" });
        await loadSpecifications();
        notify("Mission ajoutée au backlog local. Le lancement reste une étape distincte.");
      } else if (action === "download") {
        const blob = await specificationRequest(`/${encodeURIComponent(id)}/bundle`, {}, true);
        const url = URL.createObjectURL(blob);
        const link = el("a", { href: url, download: `nage-mission-${id}.zip`, hidden: true });
        document.body.append(link); link.click(); link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        notify("Brief téléchargé : spécification, plan, tâches et mission OpenCode.");
      } else {
        const mission = await specificationRequest(`/${encodeURIComponent(id)}`);
        if (document.querySelector("dialog[open]")) return;
        const ui = modal(mission.title || "Brief de développement");
        ui.content.append(el("p", { class: "note" }, mission.objective || ""));
        Object.entries(mission.documents || {}).forEach(([name, content], index) => {
          ui.content.append(el("details", { class: "kit-details", open: index === 0 },
            el("summary", {}, name), documentContent(content)));
        });
      }
    } catch (error) { notify(error.message, true); }
    finally {
      state.specificationBusy = null;
      if (button?.isConnected) { button.disabled = false; button.removeAttribute("aria-busy"); }
      if (action === "queue" && state.view === "missions") renderMissions();
    }
  }

  function renderSpecifications() {
    const data = state.specifications;
    const panel = el("section", { class: "card spec-workshop", "aria-labelledby": "specWorkshopTitle" });
    panel.append(el("div", { class: "spec-workshop-heading" },
      el("div", {}, el("p", { class: "spec-eyebrow" }, "Spec Kit · Développement guidé"),
        el("h2", { id: "specWorkshopTitle" }, "Construire mon NAGE"),
        el("p", {}, "Transforme une amélioration en mission précise : résultat attendu, fichiers concernés, tests et brief pour OpenCode.")),
      el("span", { class: "chip green" }, "Préparation locale")));
    if (state.errors.specifications) panel.append(el("p", { class: "error-note", role: "alert" }, state.errors.specifications),
      el("button", { class: "ghost-btn", type: "button", onclick: loadSpecifications }, "Recharger le Spec Kit"));
    if (!data) {
      if (!state.errors.specifications) panel.append(el("p", { class: "note", role: "status" }, "Ouverture des modèles de mission…"));
      return panel;
    }
    const draft = state.specificationForm || (state.specificationForm = specificationFormFrom(null));
    const templates = data.templates || [];
    if (templates.length) {
      const templatePicker = el("select", { id: "specTemplate", "aria-label": "Modèle de mission", onchange: (event) => {
        state.specificationForm = specificationFormFrom(templates.find((item) => item.id === event.target.value));
        renderMissions();
      } }, templates.map((item) => el("option", { value: item.id }, item.title)));
      templatePicker.value = draft.templateId;
      panel.append(el("label", { class: "spec-field" }, "Partir d’une priorité", templatePicker));
    }
    const field = (tag, label, key, attrs = {}) => el("label", { class: "spec-field" }, label,
      el(tag, { ...attrs, value: draft[key], oninput: (event) => { draft[key] = event.target.value; } }));
    const feedback = el("p", { class: "error-note", role: "alert", hidden: true });
    const submit = el("button", { type: "submit", class: "ghost-btn primary", disabled: !!state.specificationBusy }, "Préparer la mission");
    const form = el("form", { class: "spec-form", onsubmit: async (event) => {
      event.preventDefault();
      if (state.specificationBusy) return;
      state.specificationBusy = "create";
      feedback.hidden = true; submit.disabled = true; submit.setAttribute("aria-busy", "true");
      const lines = (value) => value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      try {
        await specificationRequest("", { method: "POST", body: JSON.stringify({
          title: draft.title.trim(), objective: draft.objective.trim(),
          acceptance: lines(draft.acceptance), selected_files: lines(draft.selected_files), targeted_tests: lines(draft.targeted_tests),
        }) });
        await loadSpecifications();
        notify("Mission préparée et enregistrée. Son brief est prêt pour OpenCode.");
      } catch (error) { feedback.textContent = error.message; feedback.hidden = false; }
      finally {
        state.specificationBusy = null;
        submit.disabled = false; submit.removeAttribute("aria-busy");
        if (!feedback.isConnected && state.view === "missions") renderMissions();
      }
    } },
    field("input", "Nom de l’amélioration", "title", { id: "specTitle", required: true, maxlength: "160", autocomplete: "off" }),
    field("textarea", "Ce que NAGE doit te permettre de faire", "objective", { id: "specObjective", required: true, rows: "3", maxlength: "6000" }),
    field("textarea", "Comment vérifier que c’est réussi · un critère par ligne", "acceptance", { id: "specAcceptance", required: true, rows: "4", maxlength: "4000" }),
    el("details", { class: "spec-technical" }, el("summary", {}, "Périmètre technique et tests ciblés"),
      el("p", { class: "note" }, "Les chemins du modèle délimitent le travail de l’agent. Chaque test est un fichier précis du projet."),
      el("div", { class: "spec-scope-grid" },
        field("textarea", "Fichiers autorisés · un chemin par ligne", "selected_files", { required: true, rows: "4", maxlength: "4000" }),
        field("textarea", "Tests à exécuter · un fichier par ligne", "targeted_tests", { required: true, rows: "4", maxlength: "4000" }))),
    feedback,
    el("div", { class: "spec-form-footer" }, submit,
      el("p", {}, "Cette action prépare les documents et enregistre la mission. Elle ne lance aucun modèle.")));
    panel.append(form);
    const missions = data.missions || [];
    panel.append(el("div", { class: "spec-list-heading" }, el("h3", {}, "Mes missions préparées"),
      el("span", {}, `${missions.length} mission${missions.length > 1 ? "s" : ""}`)));
    if (!missions.length) panel.append(emptyState("Ta première amélioration commence ici", "Choisis une priorité, ajuste le résultat attendu, puis prépare la mission."));
    const statuses = { draft: "Brief prêt", prepared: "Brief prêt", queued: "Dans le backlog local", needs_review: "À relire", staged: "Proposition reçue" };
    missions.forEach((mission) => {
      const queued = !!mission.evolution_task_id;
      const action = (label, kind, disabled = false) => {
        const button = el("button", { type: "button", class: "ghost-btn", disabled: disabled || !!state.specificationBusy,
          onclick: () => specificationAction(mission.id, kind, button) }, label);
        return button;
      };
      panel.append(el("article", { class: "spec-mission" },
        el("div", { class: "spec-mission-heading" }, el("h4", {}, mission.title),
          el("span", { class: `chip ${queued ? "green" : "amber"}` }, statuses[mission.status] || "Brief enregistré")),
        el("p", {}, mission.objective),
        el("p", { class: "spec-mission-meta" }, `${mission.acceptance?.length || 0} critères · ${mission.selected_files?.length || 0} fichiers · ${mission.targeted_tests?.length || 0} tests ciblés`),
        el("div", { class: "spec-mission-actions" }, action("Lire le brief", "preview"), action("Télécharger pour OpenCode", "download"),
          action(queued ? "Déjà dans le backlog local" : "Ajouter au backlog local", "queue", queued))));
    });
    return panel;
  }

  function renderMissions() {
    const host = $("#view-missions");
    const m = state.missions;
    const workshop = renderSpecifications();
    if (!m) { host.replaceChildren(workshop, loading()); return; }
    if (!m.available) {
      host.replaceChildren(workshop, el("div", { class: "card padded" }, emptyState("Historique de flotte indisponible", "Le Spec Kit reste accessible pour préparer les prochaines améliorations.")));
      return;
    }
    const total = Object.values(m.counts).reduce((a, b) => a + b, 0);
    host.replaceChildren(
      workshop,
      el("div", { class: "grid kpi" },
        el("div", { class: "card kpi-card" },
          el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Livrées"), el("span", { class: "kpi-chip" }, "✓")),
          el("div", { class: "kpi-value" }, String(m.counts.done ?? 0)),
          el("div", { class: "kpi-foot" }, `sur ${total} missions`),
        ),
        el("div", { class: "card kpi-card" },
          el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Restantes"), el("span", { class: "kpi-chip" }, "◷")),
          el("div", { class: "kpi-value" }, String(total - (m.counts.done ?? 0))),
          el("div", { class: "kpi-foot" }, "dont les bloquées par dépendance"),
        ),
        el("div", { class: "card kpi-card" },
          el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Workers"), el("span", { class: "kpi-chip" }, "⚙")),
          el("div", { class: "kpi-value" }, String(m.workers ?? "—")),
          el("div", { class: "kpi-foot" }, `charge ${m.load ?? "non mesurée"}`),
        ),
        el("div", { class: "card kpi-card" },
          el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Avancement"), el("span", { class: "kpi-chip" }, "%")),
          el("div", { class: "kpi-value" }, `${Math.round(((m.counts.done ?? 0) / Math.max(total, 1)) * 100)} %`),
          el("div", { class: "kpi-foot" }, "preuves vérifiées"),
        ),
      ),
      el("div", { class: "section-title" }, el("h2", {}, "Missions restantes"),
        el("span", { class: "hint" }, "l’ordre des dépendances est respecté")),
      el("div", { class: "card" }, m.missions.length ? m.missions.map((mission) =>
        el("div", { class: "mission-row" },
          el("span", { class: "mission-id" }, `#${mission.id}`),
          el("div", {}, el("strong", {}, mission.title || "Mission"),
            mission.blocked_by.length
              ? el("span", {}, `bloquée par ${mission.blocked_by.map((id) => `#${id}`).join(", ")}`)
              : el("span", {}, mission.status === "pending" ? "prête à lancer" : mission.status)),
          mission.blocked_by.length
            ? el("span", { class: "chip amber" }, "en attente")
            : el("span", { class: "chip green" }, "prête"),
        )) : emptyState("Toutes les missions sont livrées", "Rien en attente dans le registre.")),
    );
  }

  function renderMemory() {
    const host = $("#view-memory");
    const memory = state.overview?.memory;
    const queue = state.overview?.task_queue;
    if (!memory) { host.replaceChildren(unavailable("overview")); return; }
    host.replaceChildren(
      el("div", { class: "memory-grid" },
        el("div", { class: "card mem-card" }, el("b", {}, num(memory.source_count)), el("small", {}, "sources indexées")),
        el("div", { class: "card mem-card" }, el("b", {}, num(memory.chunk_count)), el("small", {}, "passages citables")),
        el("div", { class: "card mem-card" }, el("b", {}, num(memory.project_count)), el("small", {}, "projets")),
        el("div", { class: "card mem-card" }, el("b", {}, num(queue?.active_count)), el("small", {}, "tâches en file")),
      ),
      el("div", { class: "section-title" }, el("h2", {}, "Moteur"), el("span", { class: "hint" }, "100 % local")),
      el("div", { class: "card padded" },
        el("p", { class: "note tight" },
          `Indexation : ${memory.engine || "—"}. Les sources restent sur ce Mac, chaque réponse cite ses passages et une suppression est définitive.`),
      ),
      el("div", { class: "section-title" }, el("h2", {}, "Confidentialité"), el("span", { class: "hint" }, "par défaut")),
      el("div", { class: "card padded" },
        el("p", { class: "note tight" },
          "Mode Hors ligne actif : Ollama et outils locaux uniquement. Aucun fournisseur cloud n’est appelé sans une autorisation explicite, réutilisable une seule fois."),
      ),
    );
  }

  function renderTracking() {
    const host = $("#view-tracking");
    const t = state.tracker;
    if (!t) { host.replaceChildren(unavailable("tracker")); return; }
    const items = t.items ?? [];
    host.replaceChildren(
      el("div", { class: "grid kpi" },
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Envoyés"), el("span", { class: "kpi-chip" }, "✓")), el("div", { class: "kpi-value" }, String(t.totals?.sent_without_response ?? items.length)), el("div", { class: "kpi-foot" }, "sans réponse")),
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "À relancer"), el("span", { class: "kpi-chip" }, "◷")), el("div", { class: "kpi-value" }, String(t.totals?.due ?? 0)), el("div", { class: "kpi-foot" }, "échéance atteinte")),
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "En retard"), el("span", { class: "kpi-chip" }, "!")), el("div", { class: "kpi-value" }, String(t.totals?.overdue ?? 0)), el("div", { class: "kpi-foot" }, "relance urgente")),
      ),
      el("div", { class: "section-title" }, el("h2", {}, "Candidatures envoyées"), el("span", { class: "hint" }, "confirmation humaine · relance à copier")),
      el("div", { class: "card" }, items.length ? items.map((it) => el("div", { class: "pipeline-item" },
        el("div", { class: "pipeline-main" }, el("strong", {}, it.title || "Dossier"), el("span", {}, `${it.company || "—"} · envoi déclaré le ${formatDate(it.sent_at)}`), el("div", { class: "next" }, `Relance suggérée le ${formatDate(it.follow_up_due)}`)),
        el("div", { class: "pipeline-progress" }, el("div", { class: "bar" }, el("i", { style: `width:${Math.min(100, it.progress_percent || 100)}%` })), el("small", {}, it.channel === "website" ? "Site officiel" : it.channel || "—")),
        el("div", { class: "offer-tags" }, it.followup_draft ? el("button", { class: "chip green", type: "button", onclick: () => copyText(it.followup_draft) }, "copier relance") : null),
      )) : emptyState("Aucun envoi confirmé", "Prépare un dossier, puis confirme ton envoi manuel pour le retrouver ici.")),
      el("p", { class: "note tight" }, t.honesty || "Sont listées les candidatures déclarées envoyées."),
    );
  }

  function formatDate(value) {
    if (!value) return "À vérifier";
    const d = new Date(String(value).slice(0, 10) + "T12:00:00");
    return Number.isNaN(d.getTime()) ? "À vérifier" : new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium" }).format(d);
  }

  function notify(text, error = false) {
    $("#appNotice")?.remove();
    const live = $("#toast");
    if (live) live.textContent = text;
    const notice = el("div", { id: "appNotice", class: `app-notice ${error ? "error-note" : ""}`, role: error ? "alert" : "status" },
      el("span", {}, text), el("button", { type: "button", "aria-label": "Fermer le message", onclick: () => notice.remove() }, "×"));
    document.body.append(notice);
  }

  function modal(title) {
    const previous = document.activeElement;
    const dialog = el("dialog", { class: "application-dialog", "aria-labelledby": "dialogTitle" });
    const close = () => dialog.close();
    const content = el("div", { class: "dialog-content" });
    const feedback = el("p", { class: "error-note", role: "alert", hidden: true });
    dialog.append(
      el("header", { class: "dialog-header" },
        el("h2", { id: "dialogTitle", tabindex: "-1" }, title),
        el("button", { class: "dialog-close", type: "button", "aria-label": "Fermer le dossier", onclick: close }, "×")),
      content, feedback,
    );
    dialog.addEventListener("close", () => { dialog.remove(); if (previous?.isConnected) previous.focus(); });
    dialog.addEventListener("click", (event) => { if (event.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) close();
    } });
    document.body.append(dialog);
    dialog.showModal();
    $("h2", dialog).focus();
    return { dialog, content, feedback, close, error: (message) => { feedback.textContent = message; feedback.hidden = !message; } };
  }

  async function showApplyKit(jobId, title) {
    if (document.querySelector("dialog[open]")) return;
    const ui = modal(`Dossier · ${title || "offre"}`);
    ui.content.replaceChildren(el("p", { role: "status", class: "note" }, `Préparation locale en ${LANGUAGES[state.kitLanguage]}…`));
    ui.dialog.setAttribute("aria-busy", "true");
    let kit;
    const renderKit = async () => {
      ui.error("");
      kit = await api(`/api/career/apply-kit/${encodeURIComponent(jobId)}`, { method: "POST", body: JSON.stringify({ language: state.kitLanguage }) });
      const draft = await api(`/api/career/application-drafts/${encodeURIComponent(kit.draft_id)}`);
      if (!ui.dialog.isConnected) return;
      ui.dialog.removeAttribute("aria-busy");
      const qualityAudit = kit.quality_audit && typeof kit.quality_audit === "object" ? kit.quality_audit : null;
      const qualityBlocked = !qualityAudit || !qualityAudit.export_allowed;
      const blocked = kit.readiness !== 100 || kit.block_reasons?.length || !kit.deep_link || qualityBlocked;
      const sent = sentStages.has(kit.application?.stage);
      let approved = !!kit.application?.approval_granted && !blocked;
      const status = el("p", { class: "flow-status", role: "status" }, approved
        ? "Dossier déjà relu. Après ton envoi sur le site officiel, confirme-le ci-dessous."
        : "Relis les deux documents. Aucun envoi automatique, aucune information ajoutée sans preuve.");
      const send = el("button", { class: "ghost-btn primary", type: "button", disabled: !approved || sent,
        onclick: async () => {
          send.disabled = true; send.textContent = "Enregistrement…"; ui.error("");
          try {
            await api(`/api/career/send-confirmation/${encodeURIComponent(jobId)}`, {
              method: "POST", body: JSON.stringify({ channel: "website", sent_at: new Date().toISOString() }),
            });
            await loaders.tracker();
            // Refresh the pipeline separately: a slow read must not hide a persisted send.
            loaders.pipeline().then(() => { renderBadges(); render(state.view); }).catch((e) => { state.errors.pipeline = e.message; });
            renderBadges(); ui.close(); setView("tracking");
            $("#viewTitle").focus();
            notify("Envoi manuel enregistré. La réception par l’employeur reste à confirmer.");
          } catch (e) { ui.error(`Envoi non confirmé : ${e.message}. Tu peux réessayer sans créer de doublon.`); send.disabled = false; send.textContent = "J’ai envoyé ma candidature"; }
        },
      }, sent ? "Envoi déjà enregistré" : "J’ai envoyé ma candidature");
      const openButton = el("button", { type: "submit", class: "ghost-btn primary", disabled: blocked || sent },
        approved ? "Rouvrir le site officiel ↗" : "J’ai relu mon dossier · Ouvrir le site officiel ↗");
      openButton.type = "button";
      openButton.addEventListener("click", async () => {
        // Open synchronously in the user's click, before the network round trip.
        // Keep a local handle for navigation, remove the reverse opener link.
        const destinationTab = window.open("/app-static/manual-opening.html", "_blank");
        if (!destinationTab) { ui.error("Autorise l’ouverture d’un onglet pour ce site local, puis réessaie. Aucun envoi n’a eu lieu."); return; }
        destinationTab.opener = null;
        openButton.disabled = true; ui.error("");
        status.textContent = "Vérification de la version relue avant l’ouverture du site…";
        try {
          const response = await fetch(`/api/career/applications/${encodeURIComponent(kit.application.id)}/manual-destination`, {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json" },
            body: new URLSearchParams({ approved: "true", draft_id: kit.draft_id, review_token: kit.review_token }),
          });
          if (!response.ok) throw new Error("Le dossier a changé ou comporte des éléments à vérifier. Rouvre sa préparation.");
          const result = await response.json();
          const destination = new URL(result.destination);
          if (destination.protocol !== "https:" || destination.username || destination.password) throw new Error("La destination officielle n’est pas valide.");
          approved = true; send.disabled = false;
          if (destinationTab.closed) throw new Error("L’onglet a été fermé. Rouvre le site officiel pour effectuer ton dépôt manuel.");
          destinationTab.location.replace(destination.href);
          openButton.textContent = "Rouvrir le site officiel ↗";
          status.textContent = "Dossier relu. Remplis et envoie toi-même le formulaire de l’employeur, puis reviens confirmer l’envoi ici.";
        } catch (e) {
          if (!destinationTab.closed) destinationTab.close();
          ui.error(e.message);
          status.textContent = "Ouverture interrompue. Rien n’a été envoyé à l’employeur.";
        } finally { openButton.disabled = blocked || sent; }
      });
      const form = el("div", { class: "manual-destination-form" }, openButton);
      const exportNames = { cv_pdf: "CV · PDF", cv_docx: "CV · Word", letter_pdf: "Lettre · PDF", letter_docx: "Lettre · Word" };
      const preview = (label, text) => el("section", { class: "document-preview" }, el("h3", {}, label), documentContent(text));
      const disabledExport = (label) => el("span", {
        class: "ghost-btn disabled-export", "aria-disabled": "true",
        title: "Corrige les points signalés avant d’exporter.",
      }, label);
      const factorLabels = { factuality: "Faits vérifiables", evidence: "Preuves du profil", argument: "Adaptation à l’offre" };
      const qualityCard = qualityAudit ? el("section", {
        class: `quality-card ${qualityBlocked ? "quality-card-blocked" : "quality-card-ready"}`,
        "aria-labelledby": "qualityTitle",
      },
      el("div", { class: "quality-heading" },
        el("div", {}, el("span", { class: "eyebrow" }, "Contrôle avant export"),
          el("h3", { id: "qualityTitle" }, "Qualité factuelle du dossier")),
        el("strong", { class: "quality-score" }, `${Number(qualityAudit.score || 0)}/100`)),
      el("p", { class: "quality-verdict" }, qualityAudit.verdict_label || (qualityBlocked ? "Corrections requises" : "Prêt à relire et à exporter")),
      el("div", { class: "quality-factors", "aria-label": "Détail du score qualité" },
        ...(qualityAudit.factors || []).map((factor) => el("div", { class: "quality-factor" },
          el("span", {}, factorLabels[factor.key] || factor.label || factor.key),
          el("strong", {}, `${Number(factor.score || 0)}/100`)))),
      (qualityAudit.issues || []).length ? el("div", { class: "quality-priorities" },
        el("strong", {}, "À corriger en premier"),
        el("ul", {}, qualityAudit.issues.slice(0, 3).map((issue) => el("li", {}, issue.suggestion || issue.label || "Vérifier ce passage.")))) :
        el("p", { class: "note tight" }, qualityBlocked
          ? "Aucun fait personnel n’a encore pu être validé. Complète et approuve ton profil avant de finaliser les documents."
          : "Aucune affirmation problématique détectée par les règles locales."),
      qualityBlocked ? el("button", { class: "ghost-btn quality-edit", type: "button", onclick: () => {
        const editor = ui.content.querySelector("details[data-document-editor]");
        if (editor) { editor.open = true; editor.scrollIntoView({ behavior: "smooth", block: "start" }); }
      } }, "Relire et corriger le CV ou la lettre") : null,
      el("p", { class: "quality-disclaimer" }, "Audit local factuel : ce score vérifie les preuves et l’adaptation, pas les chances de recrutement.")) :
        el("section", { class: "quality-card quality-card-blocked", role: "alert" },
          el("h3", {}, "Audit qualité indisponible"),
          el("p", { class: "note tight" }, "L’export reste bloqué tant que le CV et la lettre n’ont pas été contrôlés."));
      const cvEdit = el("textarea", { rows: "12", maxlength: "18000", "aria-label": "Modifier le CV", value: draft.cv_markdown });
      const letterEdit = el("textarea", { rows: "12", maxlength: "18000", "aria-label": "Modifier la lettre", value: draft.letter_markdown });
      const save = el("button", { class: "ghost-btn", type: "button", disabled: sent, onclick: async () => {
        save.disabled = true; ui.error("");
        try {
          await api(`/api/career/application-drafts/${encodeURIComponent(kit.draft_id)}`, { method: "PATCH", body: JSON.stringify({ cv_markdown: cvEdit.value, letter_markdown: letterEdit.value }) });
          await renderKit();
          notify("Corrections enregistrées. Relis cette nouvelle version avant de continuer.");
        } catch (e) { ui.error(`Corrections non enregistrées : ${e.message}`); save.disabled = false; }
      } }, "Enregistrer mes corrections");
      const answers = el("details", { class: "kit-details", ontoggle: async (event) => {
        if (!event.target.open || event.target.dataset.loaded) return;
        const target = $(".answers-content", event.target);
        target.textContent = "Chargement…";
        try {
          const pack = await api(`/api/career/quick-answers/${encodeURIComponent(jobId)}?lang=${kit.language}`);
          target.replaceChildren(...answerRows(pack)); event.target.dataset.loaded = "true";
        } catch (e) { target.textContent = `Réponses indisponibles : ${e.message}. Ferme et rouvre cette section pour réessayer.`; }
      } }, el("summary", {}, "Réponses à copier dans le formulaire"), el("div", { class: "answers-content" }));
      ui.content.replaceChildren(...[
        el("ol", { class: "application-steps", "aria-label": "Les trois actions dans Côme" },
          el("li", { class: "complete" }, "1 · Dossier préparé"), el("li", {}, "2 · Relire et ouvrir"), el("li", {}, "3 · Confirmer l’envoi manuel")),
        el("div", { class: "kit-summary" },
          el("strong", {}, `CV et lettre en ${LANGUAGES[kit.language] || kit.language}`),
          el("span", { class: `chip ${blocked ? "amber" : "green"}` }, blocked ? "À compléter" : "Vérifications locales complètes")),
        el("p", { class: "note" }, "Ces vérifications documentaires ne prédisent pas les chances de recrutement. Le contenu reste à relire et à adapter."),
        blocked ? el("div", { class: "error-note", role: "alert" }, el("strong", {}, "À vérifier avant de continuer"),
          el("ul", {}, [...(kit.block_reasons || []), ...(qualityBlocked ? ["L’audit factuel demande des corrections avant l’export."] : [])]
            .filter((reason, index, reasons) => reasons.indexOf(reason) === index)
            .map((reason) => el("li", {}, reason))),
          el("button", { class: "inline-action", type: "button", onclick: () => { ui.close(); openCareerWorkspace("profile"); } }, "Vérifier mon profil dans NAGE →")) : null,
        qualityCard,
        el("div", { class: "document-grid" }, preview("CV", draft.cv_markdown), preview("Lettre de motivation", draft.letter_markdown)),
        el("div", { class: "download-links", "aria-label": "Télécharger les documents relus" },
          Object.entries(kit.export_urls || {}).map(([key, url]) => blocked
            ? disabledExport(exportNames[key] || key)
            : el("a", { class: "ghost-btn", href: url, download: "" }, exportNames[key] || key)),
          blocked ? disabledExport("tout télécharger (.zip)") : el("a", {
              class: "ghost-btn primary",
              href: `/api/career/apply-kit/${encodeURIComponent(jobId)}/bundle.zip?language=${encodeURIComponent(kit.language || state.kitLanguage)}`,
              download: "",
            }, "tout télécharger (.zip)"),
          el("button", {
            class: "ghost-btn",
            type: "button",
            disabled: blocked,
            onclick: async () => {
              await copyText(kitBundleText(kit, draft, title));
            },
          }, "copier le dossier")),
        el("details", { class: "kit-details", "data-document-editor": "true" }, el("summary", {}, "Corriger le CV ou la lettre"),
          el("p", { class: "note" }, "Garde uniquement des faits exacts. Enregistrer des corrections annule la revue précédente."),
          el("label", {}, "CV", cvEdit), el("label", {}, "Lettre de motivation", letterEdit), save),
        el("details", { class: "kit-details" }, el("summary", {}, "Vérifications et provenance"),
          el("div", { class: "checklist" }, (kit.checklist || []).map((c) => el("div", { class: "checklist-row" },
            el("span", { class: c.done ? "chip green" : "chip amber" }, c.done ? "Vérifié" : "À faire"),
            el("div", {}, el("strong", {}, c.label || c.id), c.note ? el("p", { class: "note" }, c.note) : null)))),
          kit.deep_link ? el("p", { class: "note destination" }, `Destination officielle vérifiée : ${kit.deep_link}`) : null),
        answers,
        kit.ats_guide ? el("details", { class: "kit-details" }, el("summary", {}, "Guide du formulaire de l’employeur"), guideContent(kit.ats_guide)) : null,
        el("footer", { class: "application-footer" }, status,
          el("div", { class: "application-actions" }, form, send),
          el("small", {}, "Le dernier bouton enregistre ta déclaration. Il n’envoie rien à l’employeur et ne confirme pas la réception.")),
      ].filter(Boolean));
    };
    try { await renderKit(); }
    catch (e) {
      ui.dialog.removeAttribute("aria-busy");
      ui.content.replaceChildren(el("p", { class: "error-note", role: "alert" }, `Dossier indisponible : ${e.message}`),
        el("button", { type: "button", class: "ghost-btn", onclick: () => { ui.close(); showApplyKit(jobId, title); } }, "Réessayer"));
    }
  }

  function documentContent(markdown) {
    const root = el("div", { class: "document-text" });
    // Only text nodes and a small, safe subset of Markdown; never insert HTML.
    const inline = (text) => text.split(/(\*\*[^*]+\*\*)/g).map((part) =>
      part.startsWith("**") && part.endsWith("**") ? el("strong", {}, part.slice(2, -2)) : document.createTextNode(part));
    for (const block of String(markdown || "Document indisponible").split(/\n\s*\n/)) {
      const heading = block.match(/^#{1,6}\s+([^\n]+)$/);
      if (heading) root.append(el("h4", {}, ...inline(heading[1])));
      else if (block.split("\n").every((line) => /^[-*]\s+/.test(line)))
        root.append(el("ul", {}, block.split("\n").map((line) => el("li", {}, ...inline(line.replace(/^[-*]\s+/, ""))))));
      else root.append(el("p", {}, ...inline(block)));
    }
    return root;
  }

  function guideContent(g) {
    return el("div", {},
      el("p", { class: "note" }, `${g.platform || "Site de l’employeur"} · durée indicative : ${g.estimated_minutes || "?"} min. ${g.needs_account ? "Un compte peut être demandé." : "La création d’un compte dépend du site."}`),
      (g.warnings || []).map((w) => el("p", { class: "error-note" }, w)),
      el("ol", { class: "guide-steps" }, (g.steps || []).map((st, i) => el("li", {},
        el("strong", {}, st.title || `Étape ${i + 1}`),
        st.tips ? el("p", { class: "note" }, Array.isArray(st.tips) ? st.tips.join(" ") : st.tips) : null))),
      el("p", { class: "note" }, "Les champs et délais peuvent varier. Vérifie les demandes réelles de l’employeur. Aucun formulaire n’est rempli ni envoyé automatiquement."));
  }

  function answerRows(pack) {
    return [el("p", { class: "note" }, "Vérifie chaque réponse avant de la copier. Une donnée manquante reste à compléter, sans invention."),
      ...(pack.answers || []).map((a) => {
        const value = el("textarea", { rows: "2", "aria-label": a.label || a.question || "Réponse", value: a.value || "", placeholder: "À compléter avec un fait exact" });
        const copy = el("button", { type: "button", class: "ghost-btn", onclick: async () => {
          if (await copyText(value.value)) { copy.textContent = "Copié ✓"; }
        } }, "Copier");
        return el("div", { class: "answer-row" }, el("label", {}, a.label || a.question || "Réponse", value),
          el("small", {}, a.confidence === "exact" ? "Profil approuvé" : a.confidence === "derived" ? "À relire" : "À confirmer"), copy);
      })];
  }

  async function copyText(text) {
    if (!text) { notify("Complète la réponse avant de la copier.", true); return false; }
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const ta = el("textarea", { class: "clipboard-fallback", value: text }); document.body.append(ta); ta.select();
        const success = document.execCommand("copy"); ta.remove();
        if (!success) throw new Error("Copie non disponible");
      }
      notify("Texte copié. Rien n’a été envoyé."); return true;
    } catch { notify("Copie indisponible : sélectionne le texte puis utilise ⌘C ou Ctrl+C.", true); return false; }
  }

  function kitBundleText(kit, draft, title) {
    const checklist = Array.isArray(kit.checklist) ? kit.checklist : [];
    const answers = kit.answers && typeof kit.answers === "object" ? kit.answers : {};
    const lines = [
      `DOSSIER DE CANDIDATURE — ${title || "offre"}`,
      "Préparé localement par NAGe · aucun envoi automatique.",
      `État de préparation : ${Number(kit.readiness || 0)} %`,
    ];
    if (kit.deep_link) lines.push(`Lien officiel : ${kit.deep_link}`);
    if ((kit.block_reasons || []).length) {
      lines.push("", "POINTS À VÉRIFIER", ...kit.block_reasons.map((reason) => `- ${reason}`));
    }
    const answerKeys = Object.keys(answers).sort().filter((key) => String(answers[key] || "").trim());
    lines.push("", "RÉPONSES POUR LE FORMULAIRE");
    lines.push(...(answerKeys.length ? answerKeys.map((key) => `- ${key} : ${answers[key]}`) : ["- Aucune réponse enregistrée."]));
    lines.push("", "CV", String(draft?.cv_markdown || "[À compléter]"));
    lines.push("", "LETTRE DE MOTIVATION", String(draft?.letter_markdown || "[À compléter]"));
    lines.push("", "CHECKLIST HUMAINE");
    lines.push(...(checklist.length
      ? checklist.map((item) => `- [${item.done ? "x" : " "}] ${item.label || item.id || "Étape"}${item.note ? ` — ${item.note}` : ""}`)
      : ["- Aucune checklist disponible."]));
    lines.push("", "Relis les documents et dépose toi-même la candidature sur le site officiel.");
    return `${lines.join("\n").trim()}\n`;
  }

  function emptyState(title, detail) {
    return el("div", { class: "empty" }, el("strong", {}, title), el("span", {}, detail));
  }

  /* ---------- Démarrage ---------- */

  for (const button of document.querySelectorAll(".nav-item")) {
    button.addEventListener("click", () => setView(button.dataset.view));
  }
  $("#themeSelect").addEventListener("change", (event) => applyTheme(event.target.value));
  $("#kitLanguage").value = state.kitLanguage;
  $("#kitLanguage").addEventListener("change", (event) => {
    state.kitLanguage = KIT_LANGUAGES.has(event.target.value) ? event.target.value : "en";
    try { window.localStorage.setItem(LANGUAGE_STORAGE_KEY, state.kitLanguage); } catch { /* stockage local indisponible */ }
    render(state.view);
  });
  $("#refreshBtn").addEventListener("click", refresh);
  $("#searchInput").addEventListener("input", (event) => {
    state.filter = event.target.value;
    renderOffers();
  });

  const initial = (location.hash || "#today").slice(1);
  setView(VIEWS[initial] ? initial : "today", "replace");
  window.addEventListener("hashchange", () => {
    const requested = (location.hash || "#today").slice(1);
    if (VIEWS[requested] && requested !== state.view) setView(requested, "none");
  });
  loadAll();
  setInterval(() => {
    if (state.view === "today" || state.view === "missions") {
      loaders.missions().then(() => { renderBadges(); render(state.view); }).catch(() => {});
    }
  }, 60000);
})();
