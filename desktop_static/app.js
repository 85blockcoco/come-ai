/* Côme IA — cockpit local.
   Toutes les données viennent de l'API locale (127.0.0.1) : aucune requête externe. */
(() => {
  "use strict";
  window.__appState = null;

  const savedTheme = localStorage.getItem("nage-theme");
  const savedStyle = localStorage.getItem("nage-style");
  if (savedTheme === "light") document.documentElement.dataset.theme = "light";
  if (savedStyle === "study") document.documentElement.dataset.style = "study";

  const state = window.__appState = {
    view: "today",
    dashboard: null,
    pipeline: null,
    jobs: null,
    overview: null,
    missions: null,
    learning: {
      manifest: null, coverage: null, chapters: [], dashboard: null, plan: null, due: [], srsStats: null, error: "",
      selectedChapter: "TOPIC 3", summary: null, summaryLoading: false, quiz: null, tutor: null,
      quizFeedback: null, srsRevealed: false, srsBusy: false, exam: null, examResult: null,
      examBusy: false, examSubmitting: false, tutorMode: "explanation",
      practiceCases: [], practiceError: "", practiceCaseId: "VC25-Q16", practiceAnswers: {}, practiceResult: null, practiceBusy: false,
      search: [], searchQuery: "", busy: false,
    },
    filter: "",
    tracker: null,
    chat: [],
    chatMode: "offline",
    sending: false,
    letterStudio: { body: "", letterId: "", approved: false, check: null },
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "class") node.className = value;
      else if (key === "html") node.innerHTML = value;
      else if (key === "style") node.style.cssText = value; // CSSOM : autorisé par la CSP
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

  async function api(path, options) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...options,
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
        if (body?.error_id) detail += ` (réf. ${body.error_id})`;
      } catch { /* corps non JSON */ }
      throw new Error(`${detail} (HTTP ${response.status} · ${path})`);
    }
    return response.json();
  }

  /* ---------- Navigation ---------- */

  const VIEWS = {
    today: { title: "Aujourd’hui", subtitle: "état du système · ce qui compte maintenant" },
    applications: { title: "Candidatures", subtitle: "chaque dossier, son étape, sa prochaine action" },
    tracking: { title: "Suivi", subtitle: "envois confirmés · relances à copier" },
    offers: { title: "Offres", subtitle: "offres suivies · filtre instantané" },
    assistant: { title: "Terminal", subtitle: "assistant local · aucun cloud par défaut" },
    learning: { title: "Révision", subtitle: "matière Venture Capital · cours sourcé · entraînement jusqu’à l’examen" },
    missions: { title: "Missions", subtitle: "flotte de construction · preuves vérifiées" },
    memory: { title: "Mémoire", subtitle: "sources locales indexées · citables · supprimables" },
  };

  function setView(view) {
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
    $("#searchBox").hidden = view !== "offers";
    $("#scroll").scrollTop = 0;
    render(view);
    history.replaceState(null, "", `#${view}`);
  }

  /* ---------- Données ---------- */

  const loaders = {
    dashboard: async () => (state.dashboard = await api("/api/career/dashboard")),
    pipeline: async () => (state.pipeline = await api("/api/career/application-pipeline")),
    tracker: async () => (state.tracker = await api("/api/career/apply-tracker")),
    jobs: async () => (state.jobs = await api("/api/career/jobs?limit=300")),
    overview: async () => (state.overview = await api("/api/v5/overview")),
    missions: async () => (state.missions = await api("/api/app/missions")),
    learning: async () => {
      const learning = state.learning;
      learning.error = "";
      try {
        let manifest = await api("/career/manifest");
        if (!manifest.documents?.length) {
          if (!learningIngestPromise) learningIngestPromise = api("/career/ingest", { method: "POST", body: JSON.stringify({}) }).finally(() => { learningIngestPromise = null; });
          const ingestion = await learningIngestPromise;
          manifest = ingestion.manifest || await api("/career/manifest");
        }
        const [coverage, chapters, dashboard, plan, due] = await Promise.all([
          api("/career/coverage"), api("/career/chapters"), api("/career/learning/dashboard"),
          api("/career/plan"), api(`/career/srs/due?limit=8&chapter=${encodeURIComponent(learning.selectedChapter)}`),
        ]);
        let practice = { cases: [] };
        try {
          practice = await api("/career/practice/cases");
          learning.practiceError = "";
        } catch (error) {
          learning.practiceError = error.message;
        }
        learning.manifest = manifest;
        learning.coverage = coverage;
        learning.chapters = chapters.chapters || [];
        learning.dashboard = dashboard;
        learning.plan = plan;
        learning.due = due.cards || [];
        learning.srsStats = due.stats || null;
        learning.practiceCases = practice.cases || [];
        if (!learning.practiceCases.some((item) => item.case_id === learning.practiceCaseId)) {
          learning.practiceCaseId = learning.practiceCases[0]?.case_id || "";
          learning.practiceAnswers = {};
          learning.practiceResult = null;
        } else {
          const selectedCase = learning.practiceCases.find((item) => item.case_id === learning.practiceCaseId);
          if (!learning.practiceResult || learning.practiceResult.case_id !== selectedCase?.case_id) {
            learning.practiceResult = selectedCase?.stats?.latest_result || null;
          }
        }
        return learning;
      } catch (error) {
        learning.error = error.message;
        throw error;
      }
    },
  };

  async function loadAll() {
    setStatus("pending", "Connexion…");
    // Rendu progressif : chaque source s'affiche dès qu'elle arrive (l'API
    // pipeline peut prendre ~13 s ; inutile de bloquer tout l'écran).
    const results = await Promise.allSettled(
      Object.values(loaders).map(async (load) => {
        try { await load(); }
        catch (e) { console.error("LOADER_FAIL:", e.message); throw e; }
        setStatus("online", "Local · 127.0.0.1");
        renderBadges();
        render(state.view);
      }),
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    setStatus(failed === 0 ? "online" : failed >= results.length ? "offline" : "pending",
      failed === 0 ? "Local · 127.0.0.1" : `${results.length - failed}/${results.length} sources`);
    renderBadges();
    render(state.view);
  }

  async function refresh() {
    const button = $("#refreshBtn");
    button.disabled = true;
    try {
      await Promise.allSettled(Object.values(loaders).map(async (load) => {
        await load();
        renderBadges();
        render(state.view);
      }));
      renderBadges();
      render(state.view);
    } finally {
      button.disabled = false;
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
  }

  /* ---------- Rendu ---------- */

  function render(view) {
    if (view === "today") renderToday();
    else if (view === "applications") renderApplications();
    else if (view === "offers") renderOffers();
    else if (view === "assistant") renderAssistant();
    else if (view === "learning") renderLearning();
    else if (view === "missions") renderMissions();
    else if (view === "memory") renderMemory();
  }

  const loading = () => el("div", { class: "card skeleton" }, el("i"), el("i"), el("i"));

  function greeting() {
    const hour = new Date().getHours();
    if (hour < 6) return "Système actif";
    if (hour < 12) return "Bonjour";
    if (hour < 18) return "Bon après-midi";
    return "Bonsoir";
  }

  function renderToday() {
    const host = $("#view-today");
    if (!state.dashboard) {
      host.replaceChildren(loading());
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
          el("h2", {}, `${greeting()} — cap du jour.`),
          el("p", {}, d.action_plan?.[0]
            ? `Priorité : ${d.action_plan[0].title.toLowerCase()}. ${d.action_plan[0].detail || ""}`
            : "Rien d’urgent : avance sur une offre, un dossier ou une mission."),
        ),
        el("div", { class: "hero-side" },
          el("div", {}, el("b", {}, num(d.jobs_total)), el("small", {}, "offres")),
          el("div", {}, el("b", {}, num(active)), el("small", {}, "dossiers en cours")),
          el("div", {}, el("b", {}, `${state.missions?.counts?.done ?? "—"}/${state.missions ? Object.values(state.missions.counts).reduce((a, b) => a + b, 0) : "—"}`), el("small", {}, "missions")),
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
      el("div", { class: "section-title" }, el("h2", {}, "Flotte de missions"),
        el("span", { class: "hint" }, "construit l’app en continu")),
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
    if (target === "discover") window.open("/career", "_blank", "noopener");
    else if (target === "applications") setView("applications");
  }

  function missionStrip() {
    const m = state.missions;
    if (!m?.available) return emptyState("Flotte indisponible", "Le registre des missions n’est pas lisible.");
    const total = Object.values(m.counts).reduce((a, b) => a + b, 0);
    return el("div", { class: "mission-strip" },
      el("div", {}, el("b", {}, `${m.counts.done ?? 0}/${total}`), el("small", {}, "missions livrées")),
      el("div", {}, el("b", {}, String(m.workers)), el("small", {}, "workers actifs")),
      el("div", {}, el("b", {}, String(m.load)), el("small", {}, "charge machine")),
    );
  }

  function pipelineRow(item) {
    const progress = Math.max(0, Math.min(100, Number(item.progress_percent) || 0));
    return el("div", { class: "pipeline-item" },
      el("div", { class: "pipeline-main" },
        el("strong", {}, item.title || "Dossier"),
        el("span", {}, `${item.company || "—"} · ${item.stage_label || item.stage || ""}`),
        item.next_action_label
          ? el("div", { class: "next" }, `Prochaine action : ${item.next_action_label}`)
          : null,
      ),
      el("div", { class: "pipeline-progress" },
        el("div", { class: "bar" }, el("i", { style: `width:${progress}%` })),
        el("small", {}, `${progress} %`),
      ),
      el("div", { class: "offer-tags" },
        item.deadline_date ? el("span", { class: "chip amber" }, `échéance ${item.deadline_date}`) : null,
        item.official_url
          ? el("a", { class: "chip violet", href: item.official_url, target: "_blank", rel: "noopener" }, "offre ↗")
          : null,
        el("button", { class: "chip green", type: "button", title: "Préparer le dossier (CV+lettre+checklist)",
          onclick: (event) => { event.stopPropagation(); showApplyKit(item.job_id, item.title); } }, "préparer"),
        el("button", { class: "chip", type: "button", title: "Guide de candidature (plateforme ATS)",
          onclick: (event) => { event.stopPropagation(); showAtsGuide(item.job_id, item.title); } }, "guide"),
        el("button", { class: "chip green", type: "button", title: "Réponses types copiables",
          onclick: (event) => { event.stopPropagation(); showQuickAnswers(item.job_id, item.title); } }, "réponses"),
        el("button", { class: "chip", type: "button", title: "Marquer envoyé (confirmation humaine)",
          onclick: (event) => { event.stopPropagation(); markSent(item.job_id, item.title); } }, "marqué envoyé"),
      ),
    );
  }

  function renderApplications() {
    const host = $("#view-applications");
    const p = state.pipeline?.pipeline;
    if (!p) { host.replaceChildren(loading()); return; }
    const studio = renderLetterStudio();
    if (!p.length) {
      host.replaceChildren(studio, el("div", { class: "card" }, emptyState(
        "Aucun dossier", "Prépare une lettre ci-dessus ou ouvre une offre pour créer ton premier dossier.")));
      return;
    }
    const stages = new Map();
    for (const item of p) {
      const key = item.stage_label || item.stage || "Autre";
      stages.set(key, (stages.get(key) ?? 0) + 1);
    }
    host.replaceChildren(
      studio,
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
        "Chaque action reste manuelle : rien n’est envoyé sans ta validation. ",
        el("a", { class: "inline-link", href: "/career", target: "_blank", rel: "noopener" }, "Ouvrir Career pour agir →")),
    );
  }

  function renderLetterStudio() {
    const jobs = state.jobs?.jobs || [];
    const offer = el("select", { id: "letterOffer", "aria-label": "Offre pour la lettre" },
      el("option", { value: "" }, "Choisir une offre…"),
      jobs.map((job) => el("option", { value: job.id }, `${job.company || "Entreprise"} — ${job.title || "Offre"}`)),
    );
    const language = el("select", { id: "letterLanguage", "aria-label": "Langue de la lettre" },
      [["fr", "Français"], ["en", "English"], ["de", "Deutsch"], ["es", "Español"]].map(([value, label]) => el("option", { value }, label)),
    );
    const tone = el("select", { id: "letterTone", "aria-label": "Ton de la lettre" },
      [["formal", "Formel"], ["dynamic", "Dynamique"], ["concise", "Concis"]].map(([value, label]) => el("option", { value }, label)),
    );
    const preview = el("textarea", { id: "letterPreview", rows: "12", maxlength: "30000", "aria-label": "Aperçu modifiable de la lettre", placeholder: "La lettre apparaîtra ici. Relis-la avant toute approbation." });
    preview.value = state.letterStudio.body;
    preview.addEventListener("input", () => {
      state.letterStudio.body = preview.value;
      state.letterStudio.approved = false;
    });
    const status = el("div", { class: "letter-status", role: "status", "aria-live": "polite" });
    if (state.letterStudio.check) {
      const check = state.letterStudio.check;
      status.textContent = `Score factuel ${check.facts_score ?? 0} · complétude ${check.completeness_score ?? 0} · ${check.blockers?.length || 0} blocage(s).`;
    }
    const generate = el("button", { type: "button", class: "primary-btn" }, "Prévisualiser");
    const verify = el("button", { type: "button", class: "ghost-btn" }, "Vérifier les faits");
    const approve = el("button", { type: "button", class: "ghost-btn" }, state.letterStudio.approved ? "Approuvée" : "Approuver");
    const exportButton = el("button", { type: "button", class: "ghost-btn" }, "Exporter en Markdown");
    approve.disabled = !state.letterStudio.body || Boolean(state.letterStudio.check?.blockers?.length);
    exportButton.disabled = !state.letterStudio.approved;
    generate.addEventListener("click", async () => {
      const job = jobs.find((item) => item.id === offer.value);
      if (!job) { status.textContent = "Choisis d’abord une offre."; return; }
      generate.disabled = true; status.textContent = "Préparation locale…";
      try {
        const result = await api("/api/career/letter/render", { method: "POST", body: JSON.stringify({ role: job.title, company: job.company, language: language.value, tone: tone.value, evidence: [] }) });
        state.letterStudio = { body: result.body || "", letterId: `letter-${job.id}`, approved: false, check: null };
        renderApplications();
      } catch (error) { status.textContent = error.message; generate.disabled = false; }
    });
    verify.addEventListener("click", async () => {
      if (!preview.value.trim()) { status.textContent = "Prévisualise ou saisis une lettre avant la vérification."; return; }
      verify.disabled = true; status.textContent = "Vérification locale…";
      try {
        state.letterStudio.body = preview.value;
        state.letterStudio.check = await api("/api/career/letter/check", { method: "POST", body: JSON.stringify({ letter_body: preview.value, evidence: [] }) });
        state.letterStudio.approved = false;
        renderApplications();
      } catch (error) { status.textContent = error.message; verify.disabled = false; }
    });
    approve.addEventListener("click", async () => {
      if (!state.letterStudio.letterId) state.letterStudio.letterId = `letter-local-${Date.now()}`;
      approve.disabled = true;
      try {
        await api("/api/career/letter/approve", { method: "POST", body: JSON.stringify({ letter_id: state.letterStudio.letterId, approved: true, note: "Approbation humaine dans NAGE" }) });
        state.letterStudio.approved = true; renderApplications();
      } catch (error) { status.textContent = error.message; approve.disabled = false; }
    });
    exportButton.addEventListener("click", async () => {
      exportButton.disabled = true; status.textContent = "Export local…";
      try {
        const result = await api("/api/career/letter/export", { method: "POST", body: JSON.stringify({ letter_body: state.letterStudio.body, title: state.letterStudio.letterId, language: language.value, fmt: "md", target: `career_data/exports/${state.letterStudio.letterId}.md`, approved: true }) });
        status.textContent = result.ok ? `Export local créé : ${result.path}` : (result.blockers || []).join(" · ");
      } catch (error) { status.textContent = error.message; }
      finally { exportButton.disabled = !state.letterStudio.approved; }
    });
    return el("section", { class: "card letter-studio", "aria-labelledby": "letterStudioTitle" },
      el("div", { class: "section-title no-gap" }, el("h2", { id: "letterStudioTitle" }, "Lettre de motivation"), el("span", { class: "hint" }, "locale · révision humaine obligatoire")),
      el("p", { class: "note" }, "Choisis l’offre, la langue et le ton. NAGE prépare un brouillon sans inventer de faits et n’envoie jamais la candidature."),
      el("div", { class: "letter-controls" }, offer, language, tone, generate), preview,
      el("div", { class: "letter-actions" }, verify, approve, exportButton), status,
    );
  }

  function renderOffers() {
    const host = $("#view-offers");
    const jobs = state.jobs?.jobs;
    if (!jobs) { host.replaceChildren(loading()); return; }
    const filter = state.filter.trim().toLowerCase();
    const filtered = filter
      ? jobs.filter((job) => `${job.company} ${job.title} ${job.city} ${job.job_family}`.toLowerCase().includes(filter))
      : jobs;
    host.replaceChildren(
      el("div", { class: "section-title no-gap" },
        el("h2", {}, "Toutes les offres"),
        el("span", { class: "hint" }, `${filtered.length} / ${jobs.length}`)),
      el("div", { class: "card" }, filtered.length
        ? filtered.slice(0, 120).map((job) => el("div", {
            class: "offer-row", role: "link", tabindex: "0",
            onclick: () => job.official_url && window.open(job.official_url, "_blank", "noopener"),
            onkeydown: (event) => { if (event.key === "Enter" && job.official_url) window.open(job.official_url, "_blank", "noopener"); },
          },
            el("span", { class: "offer-logo" }, (job.company || "?").slice(0, 1).toUpperCase()),
            el("div", { class: "offer-main" },
              el("strong", {}, job.title || "Offre"),
              el("span", {}, [job.company, job.city, job.job_family].filter(Boolean).join(" · ") || "—"),
            ),
            el("div", { class: "offer-tags" },
              job.source_status ? el("span", { class: `chip ${job.source_status === "open" ? "green" : "amber"}` }, job.source_status) : null,
              job.calendar_status && job.calendar_status !== "to_verify"
                ? el("span", { class: "chip" }, job.calendar_status)
                : null,
            ),
          ))
        : emptyState("Aucune correspondance", "Modifie le filtre pour retrouver une offre.")),
    );
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

  const learningTopics = [
    ["TOPIC 1", "Introduction & écosystème"],
    ["TOPIC 2", "Évaluer une startup"],
    ["TOPIC 3", "Valorisation, ownership & returns"],
    ["TOPIC 4", "Term sheets & négociation"],
    ["TOPIC 5", "Gouvernance, suivi & exits"],
  ];

  function renderLearning() {
    const host = $("#view-learning");
    const l = state.learning;
    if (!l.manifest && l.error) {
      host.replaceChildren(el("section", { class: "card padded learning-load-error", role: "alert" },
        el("h2", {}, "Le cours n’a pas pu être indexé"),
        el("p", {}, `${l.error} Les documents restent sur cet appareil; aucune donnée ne part vers un modèle.`),
        el("button", { class: "primary-btn", type: "button", onclick: async () => { l.error = ""; renderLearning(); try { await loaders.learning(); } catch { /* le panneau d'erreur reste visible */ } renderLearning(); } }, "Réessayer l’import local")));
      return;
    }
    if (!l.manifest) { host.replaceChildren(loading()); return; }
    const d = l.dashboard || {};
    const score = Math.round(Number(d.overall_score || 0) * 100);
    const selectedProgress = (d.notions || []).find((item) => item.chapter === l.selectedChapter) || {};
    const cardsTotal = Number(selectedProgress.total || 0);
    const cardsReviewed = Number(selectedProgress.reviewed || 0);
    const revisionProgress = cardsTotal ? Math.min(100, Math.round(cardsReviewed / cardsTotal * 100)) : 0;
    const understoodKey = `nage-learning-understood:${l.selectedChapter}`;
    const understood = localStorage.getItem(understoodKey) === "true";
    const exerciseTarget = Math.max(1, Number(selectedProgress.coverage_required || selectedProgress.attempts_required || 5));
    const exerciseCovered = Number(selectedProgress.covered ?? selectedProgress.attempts ?? 0);
    const exerciseAttempts = Number(selectedProgress.attempts || 0);
    const exerciseProgress = Math.min(100, Math.round(exerciseCovered / exerciseTarget * 100));
    const totalChapters = Number(d.total_count || learningTopics.length);
    const masteredChapters = Number(d.mastered_count || 0);
    const examReadiness = totalChapters ? Math.round(masteredChapters / totalChapters * 100) : 0;
    const completedExams = Number(d.exam?.completed || 0);
    const examProgress = completedExams ? 100 : Math.round(examReadiness / 2);
    const learningProgress = Math.round((revisionProgress + (understood ? 100 : 0) + exerciseProgress + examProgress) / 4);
    const currentStep = [revisionProgress, understood ? 100 : 0, exerciseProgress, examProgress].findIndex((value) => value < 100);
    const scrollToStudyStep = (id) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    const learningPath = el("section", { class: "card padded learning-path", "aria-labelledby": "learningPathTitle" },
      el("div", { class: "learning-path-top" }, el("h2", { id: "learningPathTitle" }, "Ton parcours jusqu’à l’examen"), el("strong", {}, `${learningProgress}%`)),
      el("p", {}, "Révision → apprentissage → exercices → examen blanc. L’avancement suit les activités faites; la maîtrise reste mesurée par tes réponses aux quiz."),
      el("progress", { max: "100", value: String(learningProgress), "aria-label": `Progression du parcours d’étude : ${learningProgress}%` }),
      el("div", { class: "learning-step-grid" }, ...[
        { title: "1. Réviser", progress: revisionProgress, detail: cardsTotal ? `${cardsReviewed}/${cardsTotal} cartes de ce chapitre notées.` : "Génère des cartes sourcées pour commencer.", label: "Voir les cartes", target: "study-revision" },
        { title: "2. Apprendre", progress: understood ? 100 : 0, detail: "Lis la fiche du cours, demande une explication, puis fais ton auto-évaluation.", label: understood ? "À revoir" : "J’ai compris", toggle: true },
        { title: "3. S’exercer", progress: exerciseProgress, detail: `${Math.min(exerciseCovered, exerciseTarget)}/${exerciseTarget} questions distinctes vues · ${Number(selectedProgress.correct || 0)}/${exerciseAttempts || 0} justes.`, label: "Commencer un quiz", target: "study-exercises" },
        { title: "4. Examen blanc", progress: examProgress, detail: completedExams ? `Examen(s) terminé(s) : ${completedExams} · dernier score ${Math.round(Number(d.exam?.last_score || 0) * 100)}%.` : `${masteredChapters}/${totalChapters} chapitres à 80 % pour déverrouiller l’examen complet.`, label: completedExams ? "Revoir l’examen" : "Voir les conditions", target: "study-exam" },
      ].map((step, index) => el("article", { class: "learning-step", "data-current": String(index === currentStep), "aria-current": index === currentStep ? "step" : null },
        el("div", { class: "learning-step-head" }, el("strong", {}, step.title), el("span", {}, `${step.progress}%`)),
        el("p", {}, step.detail),
        el("progress", { max: "100", value: String(step.progress), "aria-label": `Avancement ${step.title}` }),
        step.toggle
          ? el("button", { class: understood ? "ghost-btn" : "primary-btn", type: "button", onclick: () => { localStorage.setItem(understoodKey, String(!understood)); renderLearning(); } }, step.label)
          : el("button", { class: "ghost-btn", type: "button", onclick: () => scrollToStudyStep(step.target) }, step.label),
      ))),
    );
    const chapters = learningTopics.map(([value, label]) => el("option", { value, selected: l.selectedChapter === value }, `${value} · ${label}`));
    const select = el("select", { class: "learning-select", "aria-label": "Chapitre à réviser" }, ...chapters);
    select.addEventListener("change", async () => {
      l.selectedChapter = select.value; l.summary = null; l.quiz = null; l.quizFeedback = null; l.srsRevealed = false;
      await loaders.learning(); renderLearning(); await loadLearningSummary();
    });
    const notionCards = (d.notions || []).map((item) => {
      const accuracy = item.score_percent ?? Math.round((item.score || 0) * 100);
      const required = Math.max(1, Number(item.coverage_required || item.attempts_required || 2));
      const covered = Number(item.covered ?? item.attempts ?? 0);
      const value = Math.round(accuracy * Math.min(1, covered / required));
      return el("article", { class: "learning-chapter" },
        el("div", { class: "learning-chapter-head" }, el("strong", {}, item.chapter), el("b", {}, `${value}%`)),
        el("progress", { max: "100", value: String(value), "aria-label": `Progression vers la maîtrise ${item.chapter}` }),
        el("div", { class: "learning-chapter-foot" }, el("span", {}, `${item.correct || 0}/${item.attempts || 0} justes · ${accuracy}%`), el("span", { class: item.mastered ? "status-good" : "status-low" }, item.mastered ? "Maîtrisé" : "À renforcer")),
        el("small", {}, `${covered}/${required} questions distinctes · ${item.attempts || 0} réponses · ${item.due || 0} cartes dues`));
    });
    const coverage = l.coverage || {};
    const coveragePct = Math.round(Number(coverage.source_coverage || 0) * 100);
    const examObjectives = d.exam_objectives || {};
    const examObjectivesPct = Math.max(0, Math.min(100, Number(examObjectives.percent || 0)));
    const examObjectivePanel = el("div", { class: "card coverage-panel" },
      el("div", { class: "coverage-head" }, el("strong", {}, "Notions du sujet 2025 vues en quiz"), el("span", { class: "hint" }, `${examObjectives.covered || 0}/${examObjectives.total || 0}`)),
      el("progress", { max: "100", value: String(examObjectivesPct), "aria-label": "Notions repérées du sujet VC 2025 vues en quiz" }),
      el("small", {}, "Il s’agit d’un suivi de couverture du sujet historique, pas d’une maîtrise ni d’une simulation des cas libres."),
      (examObjectives.missing_ids || []).length ? el("details", { class: "coverage-details" }, el("summary", {}, "Voir les objectifs encore à pratiquer"), el("p", {}, examObjectives.missing_ids.map((tag) => tag.replace("VC25-Q", "Q")).join(" · "))) : null);
    const citationLocation = (cite) => /\.xlsx$/i.test(cite?.source || "") && cite.section ? `onglet ${cite.section}` : `p.${cite?.page ?? "—"}`;
    const citationDetails = (cite) => cite ? el("details", { class: "citation-details" }, el("summary", {}, `Voir l’extrait · ${cite.source || "cours"} · ${citationLocation(cite)}`), el("p", {}, cite.excerpt || "Extrait indisponible dans le corpus indexé.")) : null;
    const summary = l.summary
      ? el("div", { class: "learning-summary" },
          el("div", { class: "learning-summary-head" }, el("strong", {}, l.summary.chapter), el("a", { class: "chip green", href: `/career/summary/${encodeURIComponent(l.selectedChapter)}/pdf`, target: "_blank", rel: "noopener" }, "Télécharger la fiche PDF ↗")),
          ...[["Définitions", l.summary.definitions], ["Formules", l.summary.formulas], ["À retenir", l.summary.key_points]].map(([title, items]) => el("div", { class: "learning-list" }, el("b", {}, title), ...(items?.slice(0, 4).map((item) => el("p", {}, item)) || [el("p", { class: "note" }, "Aucun élément retrouvé.")]))),
          el("div", { class: "learning-citations" }, "Sources : ", ...(l.summary.citations || []).slice(0, 5).map((cite) => el("span", { class: "chip" }, `${cite.source} · ${citationLocation(cite)}`))))
      : el("div", { class: "empty" }, el("strong", {}, l.summaryLoading ? "Chargement de la fiche…" : "Fiche du chapitre"), el("span", {}, "La fiche est extraite du cours et garde ses références de page."));
    const quiz = l.quiz
      ? el("div", { class: "learning-quiz" }, el("div", { class: "section-title no-gap" }, el("h3", {}, "Quiz progressif"), el("span", { class: "hint" }, l.quiz.difficulty)), el("p", {}, l.quiz.prompt), citationDetails(l.quiz.citation), el("div", { class: "quiz-options" }, ...l.quiz.options.map((option, index) => el("button", { class: "quiz-option", type: "button", disabled: l.busy, onclick: () => answerLearningQuiz(index) }, `${String.fromCharCode(65 + index)}. ${option}`))))
      : el("div", { class: "learning-quiz" }, el("div", { class: "section-title no-gap" }, el("h3", {}, "Quiz progressif"), el("span", { class: "hint" }, "correction sourcée")),
          l.quizFeedback ? el("div", { class: l.quizFeedback.correct ? "quiz-feedback is-correct" : "quiz-feedback is-wrong", role: "status" }, el("strong", {}, l.quizFeedback.correct ? "Bonne réponse" : "À revoir"), el("p", {}, l.quizFeedback.correct_answer), el("p", {}, l.quizFeedback.explanation), citationDetails(l.quizFeedback.citation), el("button", { class: "primary-btn", type: "button", onclick: loadLearningQuiz }, "Question suivante"))
            : el("div", {}, el("p", {}, "Une question à la fois : réponds, lis la correction, puis retente."), el("button", { class: "primary-btn", type: "button", onclick: loadLearningQuiz }, "Lancer une question")));
    const practiceCase = l.practiceCases.find((item) => item.case_id === l.practiceCaseId) || l.practiceCases[0];
    if (practiceCase && practiceCase.case_id !== l.practiceCaseId) l.practiceCaseId = practiceCase.case_id;
    const practiceSelect = el("select", { class: "learning-select", "aria-label": "Exercice chiffré du sujet passé" },
      ...l.practiceCases.map((item) => el("option", { value: item.case_id, selected: item.case_id === practiceCase?.case_id }, `${item.exam_question} · ${item.title}`)));
    practiceSelect.addEventListener("change", () => {
      l.practiceCaseId = practiceSelect.value;
      l.practiceAnswers = {};
      l.practiceResult = l.practiceCases.find((item) => item.case_id === l.practiceCaseId)?.stats?.latest_result || null;
      renderLearning();
    });
    const practiceForm = el("form", { class: "practice-form" });
    if (practiceCase) {
      const groups = [...new Set(practiceCase.steps.map((step) => step.group))];
      for (const group of groups) {
        const fields = practiceCase.steps.filter((step) => step.group === group).map((step) => {
          const savedAnswer = l.practiceAnswers[step.step_id] ?? "";
          const input = step.input_type === "choice"
            ? el("select", { class: "practice-control", "aria-label": step.label, onchange: (event) => { l.practiceAnswers[step.step_id] = event.target.value; } },
                el("option", { value: "", selected: !savedAnswer }, "Choisir Alpha ou Mega"),
                ...step.choices.map((choice) => el("option", { value: choice, selected: savedAnswer === choice }, choice)))
            : el("input", {
                class: "practice-control", type: "text", inputmode: "decimal", autocomplete: "off", spellcheck: "false",
                value: savedAnswer, "aria-label": `${step.label}, en ${step.unit}`,
                oninput: (event) => { l.practiceAnswers[step.step_id] = event.target.value; },
              });
          return el("label", { class: "practice-step" },
            el("span", {}, el("strong", {}, step.label), el("small", {}, `${step.points} pt · ${step.unit}`)), input);
        });
        practiceForm.append(el("fieldset", { class: "practice-group" }, el("legend", {}, group), ...fields));
      }
      practiceForm.append(el("button", { class: "primary-btn", type: "submit", disabled: l.practiceBusy }, l.practiceBusy ? "Correction…" : "Corriger mes calculs"));
      practiceForm.addEventListener("submit", submitLearningCase);
    }
    const practiceResult = l.practiceResult
      ? el("div", { class: "practice-result", role: "status" },
          el("div", { class: "practice-result-head" }, el("strong", {}, `Résultat : ${l.practiceResult.score} / ${l.practiceResult.max_score} points`), el("span", {}, `${l.practiceResult.percent}%`)),
          el("p", { class: "practice-rubric-note" }, l.practiceResult.rubric),
          ...l.practiceResult.steps.map((step) => el("article", { class: `practice-feedback ${step.correct ? "is-correct" : "is-wrong"}` },
            el("div", { class: "practice-feedback-head" }, el("strong", {}, step.label), el("span", {}, `${step.awarded} / ${step.points} pt`)),
            el("p", {}, step.valid_answer ? `Ta réponse : ${step.entered_display}${step.unit && step.input_type !== "choice" ? ` ${step.unit}` : ""}` : step.input_type === "choice" ? "Aucune option valide choisie." : "Aucun nombre exploitable saisi."),
            el("p", {}, `Réponse attendue : ${step.expected_display}`),
            el("p", {}, step.explanation))),
          ...(l.practiceResult.citations || []).map(citationDetails)) : null;
    const practiceScoreCaption = practiceCase
      ? practiceCase.official_question_score > practiceCase.max_score
        ? `${practiceCase.max_score} points indicatifs · ${practiceCase.official_question_score} points au total`
        : `${practiceCase.max_score} points`
      : "";
    const guidedPractice = el("section", { class: "case-practice", "aria-label": "Exercices chiffrés de l’examen passé" },
      el("div", { class: "case-practice-head" }, el("div", {}, el("h3", {}, "Calculs au format de l’épreuve"), el("p", {}, "Entraîne-toi sur les questions 16 à 21. Les points par sous-partie de Q20/Q21 sont indicatifs : le corrigé ne donne qu’un total de 15 points par question.")), practiceSelect),
      practiceCase ? el("div", { class: "case-practice-prompt" }, el("strong", {}, `${practiceCase.exam_question} · ${practiceScoreCaption}`), el("p", {}, practiceCase.prompt), el("small", {}, `Tentatives : ${practiceCase.stats.attempts} · meilleur score : ${practiceCase.stats.best_score == null ? "—" : `${practiceCase.stats.best_score}/${practiceCase.stats.max_score}`}`), ...(practiceCase.citations || []).map(citationDetails)) : el("p", { class: l.practiceError ? "error-note" : "note", role: l.practiceError ? "status" : null }, l.practiceError ? `Les cas guidés Q16–Q21 ne sont pas disponibles sur cette instance (${l.practiceError}). Le quiz et les cartes restent accessibles.` : "Aucun exercice disponible."),
      practiceForm,
      practiceResult);
    const card = l.due[0];
    const srs = card
      ? el("div", { class: "srs-card" }, el("p", { class: "srs-card-question" }, card.question), l.srsRevealed
        ? el("div", { class: "srs-card-answer" }, el("p", {}, card.answer), citationDetails(card.source), el("div", { class: "srs-ratings", role: "group", "aria-label": "Évaluer la carte" }, ...[["again", "Encore"], ["hard", "Difficile"], ["good", "Bien"], ["easy", "Facile"]].map(([rating, label]) => el("button", { class: "ghost-btn", type: "button", disabled: l.srsBusy, onclick: () => reviewLearningCard(rating) }, label))))
        : el("button", { class: "primary-btn", type: "button", onclick: () => { l.srsRevealed = true; renderLearning(); } }, "Révéler la réponse"))
      : el("div", { class: "empty" }, el("strong", {}, l.srsStats?.total ? "Toutes les cartes sont à jour" : "Aucune carte encore"), el("span", {}, l.srsStats?.total ? "Ta prochaine révision est planifiée." : `Génère des cartes sourcées pour ${l.selectedChapter}.`));
    const tutorForm = el("form", { class: "tutor-form" },
      el("textarea", { id: "learningQuestion", rows: "2", maxlength: "4000", placeholder: "Je n’ai pas compris… explique-moi avec le cours.", "aria-label": "Question sur le cours" }),
      el("select", { id: "learningTutorMode", class: "learning-select", "aria-label": "Mode d’explication" }, ...[["explanation", "Expliquer"], ["reformulation", "Reformuler"], ["example", "Exemple du cours"], ["beginner", "Comme à un débutant"], ["did_not_understand", "Je n’ai pas compris"]].map(([value, label]) => el("option", { value, selected: l.tutorMode === value }, label))),
      el("button", { class: "ghost-btn", type: "submit" }, "Demander au tuteur"));
    tutorForm.addEventListener("submit", askLearningTutor);
    $("#learningTutorMode", tutorForm).addEventListener("change", (event) => { l.tutorMode = event.target.value; });
    const searchForm = el("form", { class: "learning-search" }, el("input", { id: "learningSearchInput", type: "search", value: l.searchQuery, placeholder: `Rechercher dans les ${l.manifest.documents?.length || 0} sources…`, "aria-label": "Rechercher dans le cours" }), el("button", { class: "ghost-btn", type: "submit" }, "Chercher"));
    searchForm.addEventListener("submit", searchLearning);
    const tutor = l.tutor ? el("div", { class: "tutor-answer", role: "status" }, el("p", {}, l.tutor.answer || l.tutor.message || "Réponse refusée."), ...((l.tutor.citations || []).map(citationDetails))) : null;
    const searchResults = l.search.length ? el("div", { class: "search-results" }, ...l.search.slice(0, 8).map((hit) => el("div", { class: "search-result" }, el("b", {}, `${hit.source} · ${citationLocation(hit)}`), el("span", {}, hit.excerpt)))) : el("p", { class: "note" }, "Recherche une formule, une notion ou un terme du cours.");
    const planItems = (l.plan?.sessions || []).map((session) => el("div", {}, el("b", {}, session.date), el("span", {}, session.chapter), el("small", {}, session.phase)));
    let exam;
    if (l.examResult) {
      exam = el("section", { class: "exam-panel", "aria-live": "polite" }, el("div", { class: "section-title" }, el("h2", {}, "Correction de l’examen blanc"), el("b", { class: "exam-score" }, `${Math.round(l.examResult.score * 100)}% · ${l.examResult.correct}/${l.examResult.total}`)),
        el("p", {}, l.examResult.status === "timed_out" ? "Temps écoulé ; les réponses enregistrées ont été corrigées." : "Examen terminé. La correction est reliée au cours."),
        l.examResult.remediation?.length ? el("p", { class: "exam-remediation" }, `À retravailler : ${l.examResult.remediation.join(" · ")}`) : el("p", { class: "status-good" }, "Aucun chapitre en remédiation."),
        ...(l.examResult.corrections || []).map((item, index) => el("article", { class: "exam-correction" }, el("strong", {}, `${index + 1}. ${item.chapter} · ${item.correct ? "juste" : "à revoir"}`), el("p", {}, item.prompt), el("p", {}, `Ta réponse : ${item.selected_answer || "sans réponse"}`), el("p", {}, `Réponse attendue : ${item.correct_answer}`), el("p", {}, item.explanation), citationDetails(item.citation))),
        el("button", { class: "ghost-btn", type: "button", onclick: () => { l.examResult = null; renderLearning(); } }, "Fermer la correction"));
    } else if (l.exam?.status === "ready") {
      exam = el("section", { class: "exam-panel" }, el("div", { class: "section-title" }, el("h2", {}, "Examen blanc"), el("b", { id: "examTimer", class: "exam-timer", role: "timer" }, "30:00")), el("p", { class: "note" }, `${Object.keys(l.exam.answers || {}).length}/${l.exam.questions.length} réponses enregistrées · chaque choix est sauvegardé localement.`),
        ...l.exam.questions.map((question, index) => el("article", { class: "exam-question" }, el("strong", {}, `${index + 1}. ${question.chapter}`), el("p", {}, question.prompt), el("div", { class: "quiz-options" }, ...question.options.map((option, optionIndex) => el("button", { class: "quiz-option", type: "button", disabled: l.examBusy || l.examSubmitting, "aria-pressed": String(l.exam.answers[question.question_id] === optionIndex), onclick: () => answerLearningExam(question.question_id, optionIndex) }, `${String.fromCharCode(65 + optionIndex)}. ${option}`))))),
        el("button", { class: "primary-btn", type: "button", disabled: l.examSubmitting, onclick: submitLearningExam }, l.examSubmitting ? "Correction…" : "Terminer et corriger"));
    } else {
      exam = el("section", { class: "exam-panel" }, el("div", { class: "section-title" }, el("h2", {}, "Simulateur d’examen"), el("span", { class: "hint" }, "seuil de maîtrise : 80%")),
        l.exam?.status === "blocked" ? el("div", { class: "exam-gate" }, el("p", {}, l.exam.reason), ...(l.exam.gate?.missing || []).map((item) => el("p", {}, `${item.chapter} · ${Math.round(item.score * 100)}% · ${item.covered || 0}/${item.coverage_required || item.attempts_required} questions distinctes vues`))) : el("p", {}, "Six questions sourcées, avec un accent sur la valorisation et les calculs, correction détaillée et chapitres à retravailler."),
        el("button", { class: "primary-btn", type: "button", disabled: l.examBusy, onclick: startLearningExam }, l.examBusy ? "Préparation…" : "Lancer l’examen blanc"));
    }
    exam.id = "study-exam";
    const learningSubjectNav = el("nav", { class: "learning-subject-nav", "aria-label": "Matière en révision" },
      el("span", { class: "learning-subject-label" }, "Matière"),
      el("button", { class: "learning-subject-tab", type: "button", "aria-current": "page", "aria-label": "Matière active : Venture Capital", onclick: () => scrollToStudyStep("study-revision") },
        el("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" }, el("path", { d: "M5 4.5A2.5 2.5 0 017.5 2H20v16H7.5A2.5 2.5 0 005 20.5v-16zm2.5-.9a.9.9 0 00-.9.9v12.2c.3-.1.6-.2.9-.2h10.9V3.6H7.5zM5 20.5A2.5 2.5 0 017.5 18H20v2H7.5a.5.5 0 00-.5.5H5z" })),
        el("strong", {}, "Venture Capital"), el("span", { class: "learning-subject-active" }, "Actif")),
      el("span", { class: "learning-subject-meta" }, `${learningTopics.length} chapitres · ${num(l.manifest.documents?.length || 0)} supports locaux`));
    const revisionPanel = el("div", { class: "card padded srs-panel", id: "study-revision" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Étape 1 · Révision active"), el("span", { class: "hint" }, `${l.due.length} cartes dues · ${l.selectedChapter}`)), srs, el("button", { class: "ghost-btn", type: "button", disabled: l.srsBusy, onclick: generateLearningCards }, l.srsBusy ? "Génération locale…" : `Générer / compléter les cartes de ${l.selectedChapter}`));
    const learningPanel = el("div", { class: "learning-grid", id: "study-learning" },
      el("div", { class: "card padded" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Étape 2 · Apprendre avec le cours"), el("span", { class: "hint" }, l.selectedChapter)), summary, el("button", { class: "ghost-btn", type: "button", onclick: loadLearningSummary }, "Actualiser la fiche")),
      el("div", { class: "card padded" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Tuteur du cours"), el("span", { class: "hint" }, "réponses bornées au chapitre sélectionné")), tutorForm, tutor));
    const searchPanel = el("div", { class: "card padded" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Recherche dans le cours"), el("span", { class: "hint" }, "tous les supports")), searchForm, searchResults);
    const exercisePanel = el("div", { class: "card padded learning-exercise", id: "study-exercises" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Étape 3 · Exercices progressifs"), el("span", { class: "hint" }, l.quiz?.difficulty || "correction sourcée")), quiz, guidedPractice);
    host.replaceChildren(
      el("div", { class: "card learning-hero" }, el("div", {}, el("h2", {}, "Objectif : arriver prêt à l’examen."), el("p", {}, `${l.manifest.documents?.length || 0} sources locales indexées · ${num(l.manifest.pages || 0)} pages / feuilles · aucune réponse hors corpus.`)), el("div", { class: "learning-score" }, el("b", {}, `${score}%`), el("small", {}, "justesse moyenne observée"))),
      learningSubjectNav,
      learningPath,
      el("div", { class: "card coverage-panel" }, el("div", { class: "coverage-head" }, el("strong", {}, "Couverture des supports"), el("span", { class: coveragePct === 100 ? "status-good" : "status-low" }, coverage.inventory_available ? `${coverage.indexed_sources}/${coverage.expected_sources} fichiers · ${coveragePct}%` : "Inventaire source indisponible")), el("progress", { max: "100", value: String(coveragePct), "aria-label": "Couverture des fichiers de cours" }), el("small", {}, `${num(coverage.covered_content_units || 0)}/${num(coverage.expected_content_units || 0)} pages ou feuilles indexées · local uniquement`), el("details", { class: "coverage-details" }, el("summary", {}, "Voir les fichiers du corpus"), el("ul", {}, ...(coverage.sources || []).map((source) => el("li", { class: source.text_available ? "coverage-ok" : "coverage-missing" }, `${source.text_available ? "✓" : "!"} ${source.name} · ${num(source.indexed_units)}/${num(source.expected_content_units)} unités`))))),
      el("div", { class: "learning-toolbar card" }, select, el("span", { class: "chip green" }, `${d.mastered_count || 0}/${d.total_count || 5} chapitres maîtrisés`), el("span", { class: "chip amber" }, `${d.cards_due ?? l.due.length} cartes dues`), el("a", { class: "ghost-btn", href: "/career/plan", target: "_blank", rel: "noopener" }, "Plan détaillé ↗"), el("a", { class: "ghost-btn", href: "/career/plan/pdf", target: "_blank", rel: "noopener" }, "Plan PDF ↗")),
      examObjectivePanel,
      el("div", { class: "card padded chapter-dashboard" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Progression vers la maîtrise"), el("span", { class: "hint" }, `justesse moyenne observée ${score}%`)), el("div", { class: "chapter-progress-grid" }, ...notionCards)),
      revisionPanel,
      learningPanel,
      searchPanel,
      exercisePanel,
      el("div", { class: "card padded learning-plan" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Plan des prochaines sessions"), el("span", { class: "hint" }, `${l.plan?.start || "—"} → ${l.plan?.until || "—"}`)), el("div", { class: "plan-row" }, ...planItems)),
      exam);
    if (!l.summary && !l.summaryLoading) loadLearningSummary();
  }

  let learningIngestPromise = null;

  async function loadLearningSummary() {
    const l = state.learning;
    l.summaryLoading = true;
    try { l.summary = await api(`/career/summary/${encodeURIComponent(l.selectedChapter)}`); }
    catch (error) { console.error("LEARNING_SUMMARY_FAIL", error.message); }
    finally { l.summaryLoading = false; renderLearning(); }
  }

  async function loadLearningQuiz() {
    const l = state.learning;
    try { const data = await api("/career/quiz/next", { method: "POST", body: JSON.stringify({ chapter: l.selectedChapter }) }); l.quiz = data.question; l.quizFeedback = null; renderLearning(); }
    catch (error) { alert(`Quiz indisponible : ${error.message}`); }
  }

  async function submitLearningCase(event) {
    event.preventDefault();
    const l = state.learning;
    if (!l.practiceCaseId || l.practiceBusy) return;
    l.practiceBusy = true;
    renderLearning();
    try {
      l.practiceResult = await api(`/career/practice/cases/${encodeURIComponent(l.practiceCaseId)}/submit`, {
        method: "POST", body: JSON.stringify({ answers: l.practiceAnswers }),
      });
      try { await loaders.learning(); } catch (error) { console.error("CASE_PRACTICE_REFRESH_FAIL", error.message); }
    } catch (error) {
      console.error("CASE_PRACTICE_FAIL", error.message);
      alert(`Correction indisponible : ${error.message}`);
    } finally {
      l.practiceBusy = false;
      renderLearning();
    }
  }

  async function answerLearningQuiz(index) {
    const l = state.learning;
    if (!l.quiz) return;
    l.busy = true;
    try { renderLearning(); const result = await api("/career/quiz/answer", { method: "POST", body: JSON.stringify({ question_id: l.quiz.question_id, option_index: index }) }); l.quiz = null; l.quizFeedback = result; await loaders.learning(); }
    catch (error) { alert(`Réponse non enregistrée : ${error.message}`); }
    finally { l.busy = false; renderLearning(); }
  }

  async function generateLearningCards() {
    const l = state.learning; l.srsBusy = true; l.srsRevealed = false; renderLearning();
    try {
      await api(`/career/srs/generate?chapter=${encodeURIComponent(l.selectedChapter)}&limit=1000`, { method: "POST" });
      await loaders.learning();
    } catch (error) { alert(`Cartes indisponibles : ${error.message}`); }
    finally { l.srsBusy = false; renderLearning(); }
  }

  async function reviewLearningCard(rating) {
    const l = state.learning; const card = l.due[0]; if (!card) return;
    l.srsBusy = true;
    try {
      await api("/career/srs/review", { method: "POST", body: JSON.stringify({ card_id: card.card_id, rating }) });
      l.srsRevealed = false;
      await loaders.learning();
    } catch (error) { alert(`Révision non enregistrée : ${error.message}`); }
    finally { l.srsBusy = false; renderLearning(); }
  }

  async function startLearningExam() {
    const l = state.learning; l.examBusy = true; l.examResult = null; renderLearning();
    try {
      const exam = await api("/career/exam/start", { method: "POST", body: JSON.stringify({ size: 6, duration_minutes: 30 }) });
      l.exam = exam.status === "ready" ? { ...exam, answers: {} } : exam;
      if (exam.status === "ready") startLearningExamTimer();
    } catch (error) { l.exam = { status: "blocked", reason: error.message }; }
    finally { l.examBusy = false; renderLearning(); }
  }

  function startLearningExamTimer() {
    const l = state.learning;
    if (learningExamTimer) clearInterval(learningExamTimer);
    const expires = Date.parse(l.exam.timer.expires_at);
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((expires - Date.now()) / 1000));
      const timer = $("#examTimer");
      if (timer) timer.textContent = `Temps restant ${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
      if (!remaining) { clearInterval(learningExamTimer); learningExamTimer = null; submitLearningExam(); }
    };
    tick(); learningExamTimer = setInterval(tick, 1000);
  }

  async function answerLearningExam(questionId, optionIndex) {
    const l = state.learning; if (!l.exam || l.examBusy) return;
    l.examBusy = true; l.exam.answers[questionId] = optionIndex; renderLearning();
    try {
      await api("/career/exam/answer", { method: "POST", body: JSON.stringify({ exam_id: l.exam.exam_id, question_id: questionId, option_index: optionIndex }) });
    } catch (error) { delete l.exam.answers[questionId]; alert(`Réponse non enregistrée : ${error.message}`); }
    finally { l.examBusy = false; renderLearning(); }
  }

  async function submitLearningExam() {
    const l = state.learning; if (!l.exam || l.exam.status !== "ready" || l.examSubmitting) return;
    l.examSubmitting = true; renderLearning();
    try {
      l.examResult = await api("/career/exam/submit", { method: "POST", body: JSON.stringify({ exam_id: l.exam.exam_id }) });
      l.exam = null;
      if (learningExamTimer) clearInterval(learningExamTimer); learningExamTimer = null;
      await loaders.learning();
    } catch (error) { alert(`Correction indisponible : ${error.message}`); }
    finally { l.examSubmitting = false; renderLearning(); }
  }

  async function askLearningTutor(event) {
    event.preventDefault();
    const input = $("#learningQuestion");
    if (!input?.value.trim()) return;
    const l = state.learning;
    try { l.tutor = await api("/career/tutor/ask", { method: "POST", body: JSON.stringify({ question: input.value.trim(), mode: l.tutorMode, section: l.selectedChapter }) }); renderLearning(); }
    catch (error) { alert(`Tuteur indisponible : ${error.message}`); }
  }

  async function searchLearning(event) {
    event.preventDefault();
    const input = $("#learningSearchInput");
    const query = input?.value.trim(); if (!query) return;
    const l = state.learning; l.searchQuery = query;
    try { l.search = (await api(`/career/search?q=${encodeURIComponent(query)}&limit=8`)).results || []; renderLearning(); }
    catch (error) { alert(`Recherche indisponible : ${error.message}`); }
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

  function renderMissions() {
    const host = $("#view-missions");
    const m = state.missions;
    if (!m) { host.replaceChildren(loading()); return; }
    if (!m.available) {
      host.replaceChildren(el("div", { class: "card" }, emptyState("Registre illisible", "missions_registry.json est absent ou invalide.")));
      return;
    }
    const total = Object.values(m.counts).reduce((a, b) => a + b, 0);
    host.replaceChildren(
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
          el("div", { class: "kpi-value" }, String(m.workers)),
          el("div", { class: "kpi-foot" }, `charge ${m.load}`),
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
    if (!memory) { host.replaceChildren(loading()); return; }
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
          `Indexation : ${memory.engine || "—"}. Les sources restent sur ce Mac, chaque réponse cite ses passages et une suppression est définitive. `,
          el("a", { class: "inline-link", href: "/v5", target: "_blank", rel: "noopener" }, "Gérer la mémoire dans V5 →")),
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
    if (!t) { host.replaceChildren(loading()); return; }
    const items = t.items ?? [];
    host.replaceChildren(
      el("div", { class: "grid kpi" },
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Envoyés"), el("span", { class: "kpi-chip" }, "✓")), el("div", { class: "kpi-value" }, String(t.totals?.sent_without_response ?? items.length)), el("div", { class: "kpi-foot" }, "sans réponse")),
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "À relancer"), el("span", { class: "kpi-chip" }, "◷")), el("div", { class: "kpi-value" }, String(t.totals?.due ?? 0)), el("div", { class: "kpi-foot" }, "échéance atteinte")),
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "En retard"), el("span", { class: "kpi-chip" }, "!")), el("div", { class: "kpi-value" }, String(t.totals?.overdue ?? 0)), el("div", { class: "kpi-foot" }, "relance urgente")),
      ),
      el("div", { class: "section-title" }, el("h2", {}, "Candidatures envoyées"), el("span", { class: "hint" }, "confirmation humaine · relance à copier")),
      el("div", { class: "card" }, items.length ? items.map((it) => el("div", { class: "pipeline-item" },
        el("div", { class: "pipeline-main" }, el("strong", {}, it.title || "Dossier"), el("span", {}, `${it.company || "—"} · envoyé ${it.sent_at || "—"}`), el("div", { class: "next" }, `relance prévue : ${it.follow_up_due || "—"}`)),
        el("div", { class: "pipeline-progress" }, el("div", { class: "bar" }, el("i", { style: `width:${Math.min(100, it.progress_percent || 100)}%` })), el("small", {}, it.channel || "site")),
        el("div", { class: "offer-tags" }, it.follow_up_draft ? el("button", { class: "chip green", type: "button", onclick: () => copyText(it.follow_up_draft) }, "copier relance") : null),
      )) : emptyState("Aucun envoi confirmé", "Marque une candidature « envoyé » pour la suivre ici.")),
      el("p", { class: "note tight" }, t.honesty || "Sont listées les candidatures déclarées envoyées."),
    );
  }

  async function showApplyKit(jobId, title) {
    let kit;
    try { kit = await api(`/api/career/apply-kit/${jobId}`, { method: "POST", body: "{}" }); }
    catch (e) { alert(`Dossier indisponible : ${e.message}`); return; }
    const overlay = el("div", { class: "modal-overlay", onclick: (ev) => { if (ev.target === overlay) overlay.remove(); } });
    const readiness = Number(kit.readiness || 0);
    const box = el("div", { class: "card modal-box" },
      el("div", { class: "section-title", style: "margin-top:0" }, el("h2", {}, `Dossier prêt — ${title || "offre"}`), el("span", { class: "hint" }, `readiness ${readiness} %`)),
      (kit.block_reasons || []).length ? el("div", { class: "error-note" }, (kit.block_reasons || []).join(" · ")) : null,
      el("div", { class: "grid kpi", style: "margin-top:10px" },
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Readiness"), el("span", { class: "kpi-chip" }, "%")), el("div", { class: "kpi-value" }, String(readiness)), el("div", { class: "kpi-foot" }, "sur 100")),
        el("div", { class: "card kpi-card" }, el("div", { class: "kpi-top" }, el("span", { class: "kpi-label" }, "Checklist"), el("span", { class: "kpi-chip" }, "✓")), el("div", { class: "kpi-value" }, `${(kit.checklist || []).filter((c) => c.done).length}/${(kit.checklist || []).length}`), el("div", { class: "kpi-foot" }, "items validés")),
      ),
      el("div", { class: "section-title" }, el("h2", {}, "Pièces à télécharger"), el("span", { class: "hint" }, "PDF + DOCX")),
      el("div", { class: "offer-tags", style: "flex-wrap:wrap;gap:6px" },
        Object.entries(kit.export_urls || {}).map(([k, u]) => el("a", { class: "chip green", href: u, target: "_blank", rel: "noopener" }, `${k} ↗`))),
      el("div", { class: "section-title" }, el("h2", {}, "Checklist humaine"), el("span", { class: "hint" }, "à valider avant envoi")),
      el("div", { class: "quick-list" }, (kit.checklist || []).map((c) =>
        el("div", { class: "quick-row" },
          el("span", { class: c.done ? "chip green" : "chip amber" }, c.done ? "ok" : "à faire"),
          el("div", { class: "quick-value" }, c.label || c.id || "—"),
          c.note ? el("span", { class: "quick-label" }, c.note) : null,
        ))),
      kit.deep_link ? el("a", { class: "ghost-btn", href: kit.deep_link, target: "_blank", rel: "noopener", style: "margin-top:12px;display:inline-flex" }, "Ouvrir le formulaire officiel ↗") : null,
      el("button", { class: "ghost-btn", type: "button", onclick: () => overlay.remove(), style: "margin-top:12px" }, "Fermer"),
    );
    overlay.append(box);
    document.body.append(overlay);
  }

  async function showAtsGuide(jobId, title) {
    let g;
    try { g = await api(`/api/career/ats-guide/${jobId}`); }
    catch (e) { alert(`Guide indisponible : ${e.message}`); return; }
    const overlay = el("div", { class: "modal-overlay", onclick: (ev) => { if (ev.target === overlay) overlay.remove(); } });
    const box = el("div", { class: "card modal-box" },
      el("div", { class: "section-title", style: "margin-top:0" }, el("h2", {}, `Guide ATS — ${g.title || title || "offre"}`), el("span", { class: "hint" }, `${g.platform || "custom"} · ${g.estimated_minutes || "?"} min`)),
      el("div", { class: "offer-tags", style: "margin-bottom:10px" },
        g.needs_account ? el("span", { class: "chip amber" }, "compte requis") : el("span", { class: "chip green" }, "pas de compte"),
        el("span", { class: "chip violet" }, `${(g.steps || []).length} étapes`),
      ),
      el("div", { class: "quick-list" }, (g.steps || []).map((st, i) =>
        el("div", { class: "quick-row", style: "grid-template-columns: 28px minmax(0,1fr)" },
          el("span", { class: "action-rank" }, String(i + 1)),
          el("div", {}, el("div", { class: "quick-value" }, st.title || st.name || `Étape ${i + 1}`),
            st.fields?.length ? el("div", { class: "quick-label" }, `champs : ${st.fields.join(", ")}`) : null,
            st.tips ? el("div", { class: "note tight", style: "margin-top:4px" }, st.tips) : null),
        ))),
      g.apply_url ? el("a", { class: "ghost-btn", href: g.apply_url, target: "_blank", rel: "noopener", style: "margin-top:12px;display:inline-flex" }, "Ouvrir le formulaire officiel ↗") : null,
      el("button", { class: "ghost-btn", type: "button", onclick: () => overlay.remove(), style: "margin-top:12px" }, "Fermer"),
    );
    overlay.append(box);
    document.body.append(overlay);
  }

  async function showQuickAnswers(jobId, title) {
    let data;
    try { data = await api(`/api/career/quick-answers/${jobId}`); }
    catch (e) { alert(`Réponses indisponibles : ${e.message}`); return; }
    const overlay = el("div", { class: "modal-overlay", onclick: (ev) => { if (ev.target === overlay) overlay.remove(); } });
    const box = el("div", { class: "card modal-box" },
      el("div", { class: "section-title", style: "margin-top:0" }, el("h2", {}, `Réponses types — ${title || "offre"}`), el("span", { class: "hint" }, `${data.answers?.length ?? 0} questions`)),
      el("div", { class: "quick-list" }, (data.answers || []).map((a) =>
        el("div", { class: "quick-row" },
          el("div", { class: "quick-label" }, a.label || a.question || "—"),
          el("div", { class: "quick-value" }, a.value || "(à compléter)"),
          el("button", { class: "chip", type: "button", onclick: () => copyText(a.value || "") }, "copier"),
          el("span", { class: `chip ${a.confidence === "exact" ? "green" : a.confidence === "derived" ? "amber" : "red"}` }, a.confidence || "—"),
        ))),
      el("button", { class: "ghost-btn", type: "button", onclick: () => overlay.remove(), style: "margin-top:12px" }, "Fermer"),
    );
    overlay.append(box);
    document.body.append(overlay);
  }

  async function markSent(jobId, title) {
    const channel = prompt(`Canal d'envoi pour « ${title || "cette offre"} » ?\n(site / email / portal)`, "site");
    if (!channel) return;
    const iso = new Date().toISOString().slice(0, 19) + "Z";
    try {
      await api(`/api/career/send-confirmation/${jobId}`, { method: "POST", body: JSON.stringify({ channel, sent_at: iso }) });
      await loaders.tracker();
      renderBadges();
      if (state.view === "tracking") renderTracking();
      alert("Envoi enregistré. Tu peux le suivre dans « Suivi ».");
    } catch (e) { alert(`Échec : ${e.message}`); }
  }

  function copyText(text) {
    if (!text) return;
    (navigator.clipboard?.writeText ? navigator.clipboard.writeText(text) : Promise.resolve())
      .then(() => {}).catch(() => {});
    const ta = document.createElement("textarea"); ta.value = text; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }

  function emptyState(title, detail) {
    return el("div", { class: "empty" }, el("strong", {}, title), el("span", {}, detail));
  }

  /* ---------- Démarrage ---------- */

  for (const button of document.querySelectorAll(".nav-item")) {
    button.addEventListener("click", () => setView(button.dataset.view));
  }
  $("#refreshBtn").addEventListener("click", refresh);
  $("#themeSelect").value = savedTheme === "light" ? "light" : "dark";
  $("#styleSelect").value = savedStyle === "study" ? "study" : "nage";
  const setWorkMode = (active) => {
    const studyMode = Boolean(active);
    const style = studyMode ? "study" : "nage";
    const root = document.documentElement;
    const toggle = $("#workModeToggle");
    $("#styleSelect").value = style;
    root.dataset.style = studyMode ? "study" : "";
    localStorage.setItem("nage-style", style);
    toggle.setAttribute("aria-pressed", String(studyMode));
    toggle.setAttribute("aria-label", studyMode ? "Désactiver le Work Mode, revenir au style NAGe" : "Activer le Work Mode, style d’étude sobre");
    toggle.classList.toggle("is-active", studyMode);
    $("#workModeStatus").textContent = studyMode ? "Activé" : "Désactivé";
  };
  $("#styleSelect").addEventListener("change", (event) => {
    setWorkMode(event.target.value === "study");
  });
  $("#workModeToggle").addEventListener("click", () => setWorkMode($("#styleSelect").value !== "study"));
  setWorkMode(savedStyle === "study");
  $("#themeSelect").addEventListener("change", (event) => {
    const theme = event.target.value === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = theme === "light" ? "light" : "";
    localStorage.setItem("nage-theme", theme);
  });
  $("#searchInput").addEventListener("input", (event) => {
    state.filter = event.target.value;
    renderOffers();
  });

  const initial = (location.hash || "#today").slice(1);
  setView(VIEWS[initial] ? initial : "today");
  document.addEventListener("keydown", (event) => {
    if (!event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return;
    const shortcut = { "1": "today", "2": "applications", "3": "offers", "4": "assistant", "5": "learning" }[event.key];
    if (shortcut) { event.preventDefault(); setView(shortcut); }
  });
  loadAll();
  setInterval(() => {
    if (state.view === "today" || state.view === "missions") {
      loaders.missions().then(() => { renderBadges(); render(state.view); }).catch(() => {});
    }
  }, 60000);
})();
