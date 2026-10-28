/* Côme IA — cockpit local.
   Toutes les données viennent de l'API locale (127.0.0.1) : aucune requête externe. */
(() => {
  "use strict";
  window.__appState = null;

  const THEME_STORAGE_KEY = "nage-app-theme-v2";
  const THEMES = new Set(["terminal", "studio"]);

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

  const state = window.__appState = {
    view: "today",
    dashboard: null,
    pipeline: null,
    jobs: null,
    overview: null,
    missions: null,
    filter: "",
    tracker: null,
    chat: [],
    chatMode: "offline",
    sending: false,
    kitLanguage: "en",
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
    today: { title: "Aujourd’hui", subtitle: "Les prochaines étapes utiles, au même endroit" },
    applications: { title: "Mes candidatures", subtitle: "Chaque dossier, son avancement et sa prochaine action" },
    tracking: { title: "Suivi", subtitle: "Tes envois, réponses et relances à venir" },
    offers: { title: "Offres", subtitle: "Les opportunités à examiner et à préparer" },
    assistant: { title: "Assistant", subtitle: "Un espace privé pour analyser et préparer tes candidatures" },
    missions: { title: "Atelier", subtitle: "État technique et améliorations de NAGE" },
    memory: { title: "Mémoire", subtitle: "Les sources locales utilisées pour t’aider" },
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
    setStatus(failed === 0 ? "online" : failed >= results.length ? "offline" : "pending",
      failed === 0 ? "Local · 127.0.0.1" : `${results.length - failed}/${results.length} sources`);
    renderBadges();
    render(state.view);
  }

  async function refresh() {
    const button = $("#refreshBtn");
    button.disabled = true;
    try {
      await loadAll();
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
    else if (view === "tracking") renderTracking();
    else if (view === "offers") renderOffers();
    else if (view === "assistant") renderAssistant();
    else if (view === "missions") renderMissions();
    else if (view === "memory") renderMemory();
    const key = { today: "dashboard", applications: "pipeline", tracking: "tracker", offers: "jobs", missions: "missions", memory: "overview" }[view];
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
  const loading = () => el("div", { class: "card skeleton" }, el("i"), el("i"), el("i"));

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
    if (target === "discover") window.open("/career#career/stagehunter", "_blank", "noopener");
    else if (target === "profile") window.open("/career#career/profile", "_blank", "noopener");
    else if (target === "applications") setView("applications");
  }

  function missionStrip() {
    const m = state.missions;
    if (!m?.available) return emptyState("Flotte indisponible", "Le registre des missions n’est pas lisible.");
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
          el("a", { class: "ghost-btn", href: "/career#career/stagehunter", target: "_blank", rel: "noopener" }, "Rechercher des offres"),
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
        el("a", { class: "inline-link", href: "/career", target: "_blank", rel: "noopener" }, "Ouvrir Career pour agir →")),
    );
  }

  function renderOffers() {
    const host = $("#view-offers");
    const jobs = state.jobs?.jobs;
    if (!jobs) { host.replaceChildren(unavailable("jobs")); return; }
    const filter = state.filter.trim().toLowerCase();
    const filtered = filter
      ? jobs.filter((job) => `${job.company} ${job.title} ${job.city} ${job.job_family}`.toLowerCase().includes(filter))
      : jobs;
    host.replaceChildren(
      ...(jobs.length ? [] : [el("div", { class: "onboarding-card" },
        el("span", { class: "eyebrow" }, "Première étape"),
        el("h2", {}, "Ajoute des offres qui te correspondent"),
        el("p", {}, "NAGE privilégie les stages accessibles à ton niveau, tout en conservant les opportunités plus ambitieuses. Les critères inconnus restent signalés, jamais supposés compatibles."),
        el("a", { class: "ghost-btn primary", href: "/career#career/stagehunter", target: "_blank", rel: "noopener" }, "Ouvrir la recherche guidée"),
      )]),
      el("div", { class: "section-title no-gap" },
        el("h2", {}, jobs.length ? "Toutes les offres" : "Offres enregistrées"),
        el("span", { class: "hint" }, `${filtered.length} / ${jobs.length}`)),
      el("div", { class: "card" }, filtered.length
        ? filtered.slice(0, 120).map((job) => el("div", {
            class: "offer-row", role: "button", tabindex: "0",
            "aria-label": `Préparer ${job.title} en ${LANGUAGES[state.kitLanguage]}`,
            onclick: () => showApplyKit(job.id, job.title),
            onkeydown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showApplyKit(job.id, job.title); } },
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
        : emptyState(jobs.length ? "Aucune correspondance" : "Aucune offre enregistrée", jobs.length ? "Modifie le filtre pour retrouver une offre." : "Les offres ajoutées depuis la recherche guidée apparaîtront ici.")),
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
      const blocked = kit.readiness !== 100 || kit.block_reasons?.length || !kit.deep_link;
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
          el("ul", {}, (kit.block_reasons || []).map((reason) => el("li", {}, reason))),
          el("a", { class: "inline-link", href: "/career#career/profile", target: "_blank", rel: "noopener" }, "Vérifier le profil et les critères dans Career ↗")) : null,
        el("div", { class: "document-grid" }, preview("CV", draft.cv_markdown), preview("Lettre de motivation", draft.letter_markdown)),
        el("div", { class: "download-links", "aria-label": "Télécharger les documents relus" },
          Object.entries(kit.export_urls || {}).map(([key, url]) => el("a", { class: "ghost-btn", href: url, download: "" }, exportNames[key] || key))),
        el("details", { class: "kit-details" }, el("summary", {}, "Corriger le CV ou la lettre"),
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

  function emptyState(title, detail) {
    return el("div", { class: "empty" }, el("strong", {}, title), el("span", {}, detail));
  }

  /* ---------- Démarrage ---------- */

  for (const button of document.querySelectorAll(".nav-item")) {
    button.addEventListener("click", () => setView(button.dataset.view));
  }
  $("#themeSelect").addEventListener("change", (event) => applyTheme(event.target.value));
  $("#kitLanguage").addEventListener("change", (event) => { state.kitLanguage = event.target.value; render(state.view); });
  $("#refreshBtn").addEventListener("click", refresh);
  $("#searchInput").addEventListener("input", (event) => {
    state.filter = event.target.value;
    renderOffers();
  });

  const initial = (location.hash || "#today").slice(1);
  setView(VIEWS[initial] ? initial : "today");
  window.addEventListener("hashchange", () => {
    const requested = (location.hash || "#today").slice(1);
    if (VIEWS[requested] && requested !== state.view) setView(requested);
  });
  loadAll();
  setInterval(() => {
    if (state.view === "today" || state.view === "missions") {
      loaders.missions().then(() => { renderBadges(); render(state.view); }).catch(() => {});
    }
  }, 60000);
})();
