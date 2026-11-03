/* Côme IA — cockpit local.
   Toutes les données viennent de l'API locale (127.0.0.1) : aucune requête externe. */
(() => {
  "use strict";
  window.__appState = null;

  const state = window.__appState = {
    view: "today",
    dashboard: null,
    pipeline: null,
    jobs: null,
    overview: null,
    missions: null,
    learning: {
      manifest: null, chapters: [], dashboard: null, plan: null, due: [],
      selectedChapter: "TOPIC 3", summary: null, quiz: null, tutor: null,
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
      } catch { /* corps non JSON */ }
      throw new Error(detail);
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
    learning: { title: "Réviser VC", subtitle: "cours sourcé · progression · entraînement jusqu’à l’examen" },
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
      const [manifest, chapters, dashboard, plan, due] = await Promise.all([
        api("/career/manifest"), api("/career/chapters"), api("/career/learning/dashboard"),
        api("/career/plan"), api("/career/srs/due?limit=8"),
      ]);
      state.learning.manifest = manifest;
      state.learning.chapters = chapters.chapters || [];
      state.learning.dashboard = dashboard;
      state.learning.plan = plan;
      state.learning.due = due.cards || [];
      return state.learning;
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
    if (!l.manifest) { host.replaceChildren(loading()); return; }
    const chapters = learningTopics.map(([value, label]) => el("option", { value }, `${value} · ${label}`));
    const select = el("select", { class: "learning-select", "aria-label": "Chapitre à réviser" }, chapters);
    select.value = l.selectedChapter;
    select.addEventListener("change", async () => {
      l.selectedChapter = select.value; l.summary = null; l.quiz = null;
      renderLearning();
      await loadLearningSummary();
    });
    const d = l.dashboard || {};
    const score = Math.round(Number(d.overall_score || 0) * 100);
    const docs = l.manifest.documents?.length ?? 0;
    const pages = l.manifest.pages ?? 0;
    const summaryBlock = l.summary
      ? el("div", { class: "learning-summary" },
          el("div", { class: "learning-summary-head" }, el("strong", {}, l.summary.chapter),
            el("a", { class: "chip green", href: `/career/summary/${encodeURIComponent(l.selectedChapter)}/pdf`, target: "_blank", rel: "noopener" }, "fiche PDF ↗")),
          ...[["Définitions", l.summary.definitions], ["Formules", l.summary.formulas], ["À retenir", l.summary.key_points]].map(([title, items]) =>
            el("div", { class: "learning-list" }, el("b", {}, title), ...(items?.slice(0, 4).map((item) => el("p", {}, item)) || [el("p", { class: "note" }, "Aucun élément retrouvé.")]))),
          el("div", { class: "learning-citations" }, "Sources : ", ...(l.summary.citations || []).slice(0, 5).map((cite) => el("span", { class: "chip" }, `${cite.source} · p.${cite.page}`))),
        )
      : el("div", { class: "empty" }, el("strong", {}, "Fiche prête à ouvrir"), el("span", {}, "Choisis un chapitre puis ouvre sa fiche sourcée."));
    const quizBlock = l.quiz
      ? el("div", { class: "learning-quiz" },
          el("div", { class: "section-title no-gap" }, el("h3", {}, "Quiz progressif"), el("span", { class: "hint" }, l.quiz.difficulty || "foundation")),
          el("p", {}, l.quiz.prompt),
          el("div", { class: "quiz-options" }, l.quiz.options.map((option, index) => el("button", { class: "quiz-option", type: "button", onclick: () => answerLearningQuiz(index) }, `${String.fromCharCode(65 + index)}. ${option}`))),
          el("p", { class: "note tight" }, "Chaque réponse reste liée à sa citation. Si tu bloques, ouvre la fiche avant de répondre."),
        )
      : el("div", { class: "learning-quiz" }, el("div", { class: "section-title no-gap" }, el("h3", {}, "Quiz progressif"), el("span", { class: "hint" }, "récupération active")), el("p", {}, "Une question sourcée, puis un retour immédiat sur ta maîtrise."), el("button", { class: "primary-btn", type: "button", onclick: loadLearningQuiz }, "Lancer une question"));
    const tutorAnswer = l.tutor ? el("div", { class: "tutor-answer", role: "status" }, el("p", {}, l.tutor.answer || l.tutor.message || "Réponse refusée."), el("div", { class: "learning-citations" }, ...(l.tutor.citations || []).map((cite) => el("span", { class: "chip green" }, `${cite.source} · p.${cite.page}`)))) : null;
    const tutorForm = el("form", { class: "tutor-form" },
      el("textarea", { id: "learningQuestion", rows: "2", maxlength: "4000", placeholder: "Je n’ai pas compris… explique-moi avec le cours." }),
      el("button", { class: "ghost-btn", type: "submit" }, "Demander au tuteur"),
    );
    tutorForm.addEventListener("submit", askLearningTutor);
    const searchForm = el("form", { class: "learning-search" },
      el("input", { id: "learningSearchInput", type: "search", value: l.searchQuery, placeholder: "Rechercher une notion dans les 28 sources…", "aria-label": "Rechercher dans le cours" }),
      el("button", { class: "ghost-btn", type: "submit" }, "Chercher"),
    );
    searchForm.addEventListener("submit", searchLearning);
    const searchResults = l.search.length
      ? el("div", { class: "search-results" }, l.search.slice(0, 6).map((hit) =>
        el("div", { class: "search-result" },
          el("b", {}, `${hit.source} · p.${hit.page}`),
          el("span", {}, hit.excerpt),
        )))
      : el("p", { class: "note" }, "Recherche une notion, une formule ou un terme de term sheet.");
    const planItems = (l.plan?.sessions || []).slice(0, 5).map((session) =>
      el("div", {}, el("b", {}, session.date), el("span", {}, session.chapter), el("small", {}, session.phase)));
    host.replaceChildren(
      el("div", { class: "card learning-hero" },
        el("div", {}, el("h2", {}, "Objectif : arriver prêt à l’examen."), el("p", {}, `${docs} sources locales · ${num(pages)} pages · aucune réponse hors corpus. Révise en priorité ce qui n’est pas maîtrisé.`)),
        el("div", { class: "learning-score" }, el("b", {}, `${score}%`), el("small", {}, "maîtrise observée")),
      ),
      el("div", { class: "learning-toolbar card" }, select, el("span", { class: "chip green" }, `${d.mastered_count ?? 0}/${d.total_count ?? 5} chapitres maîtrisés`), el("span", { class: "chip amber" }, `${l.due.length} cartes dues`), el("a", { class: "ghost-btn", href: "/career/plan", target: "_blank", rel: "noopener" }, "Plan détaillé ↗")),
      el("div", { class: "learning-grid" },
        el("div", { class: "card padded" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Fiche du chapitre"), el("span", { class: "hint" }, "sourcée page par page")), summaryBlock, el("button", { class: "ghost-btn", type: "button", onclick: loadLearningSummary }, "Actualiser la fiche")),
        el("div", { class: "card padded" }, quizBlock),
      ),
      el("div", { class: "learning-grid" },
        el("div", { class: "card padded" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Tuteur du cours"), el("span", { class: "hint" }, "mode : je n’ai pas compris")), tutorForm, tutorAnswer),
        el("div", { class: "card padded" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Recherche"), el("span", { class: "hint" }, "citations conservées")), searchForm, searchResults),
      ),
      el("div", { class: "card padded learning-plan" }, el("div", { class: "section-title no-gap" }, el("h2", {}, "Plan des prochaines sessions"), el("span", { class: "hint" }, `${l.plan?.start || "—"} → ${l.plan?.until || "—"}`)), el("div", { class: "plan-row" }, planItems)),
    );
    if (!l.summary) loadLearningSummary();
  }

  async function loadLearningSummary() {
    const l = state.learning;
    try { l.summary = await api(`/career/summary/${encodeURIComponent(l.selectedChapter)}`); renderLearning(); }
    catch (error) { console.error("LEARNING_SUMMARY_FAIL", error.message); }
  }

  async function loadLearningQuiz() {
    const l = state.learning;
    try { const data = await api("/career/quiz/next", { method: "POST", body: JSON.stringify({ chapter: l.selectedChapter }) }); l.quiz = data.question; renderLearning(); }
    catch (error) { alert(`Quiz indisponible : ${error.message}`); }
  }

  async function answerLearningQuiz(index) {
    const l = state.learning;
    if (!l.quiz) return;
    try { const result = await api("/career/quiz/answer", { method: "POST", body: JSON.stringify({ question_id: l.quiz.question_id, option_index: index }) }); l.dashboard = { ...(l.dashboard || {}), overall_score: result.mastery?.score || 0 }; l.quiz = null; await loaders.learning(); renderLearning(); }
    catch (error) { alert(`Réponse non enregistrée : ${error.message}`); }
  }

  async function askLearningTutor(event) {
    event.preventDefault();
    const input = $("#learningQuestion");
    if (!input?.value.trim()) return;
    const l = state.learning;
    try { l.tutor = await api("/career/tutor/ask", { method: "POST", body: JSON.stringify({ question: input.value.trim(), mode: "explanation" }) }); renderLearning(); }
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
  $("#searchInput").addEventListener("input", (event) => {
    state.filter = event.target.value;
    renderOffers();
  });

  const initial = (location.hash || "#today").slice(1);
  setView(VIEWS[initial] ? initial : "today");
  loadAll();
  setInterval(() => {
    if (state.view === "today" || state.view === "missions") {
      loaders.missions().then(() => { renderBadges(); render(state.view); }).catch(() => {});
    }
  }, 60000);
})();
