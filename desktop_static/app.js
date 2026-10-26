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
    filter: "",
    tracker: null,
    chat: [],
    chatMode: "offline",
    sending: false,
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
    else if (view === "tracking") renderTracking();
    else if (view === "offers") renderOffers();
    else if (view === "assistant") renderAssistant();
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
    if (!p.length) {
      host.replaceChildren(el("div", { class: "card" }, emptyState(
        "Aucun dossier", "Ouvre une offre et génère un kit pour créer ton premier dossier.")));
      return;
    }
    const stages = new Map();
    for (const item of p) {
      const key = item.stage_label || item.stage || "Autre";
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
        "Chaque action reste manuelle : rien n’est envoyé sans ta validation. ",
        el("a", { class: "inline-link", href: "/career", target: "_blank", rel: "noopener" }, "Ouvrir Career pour agir →")),
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

  /* ---------- Palette de commandes + raccourcis clavier ---------- */

  const VIEW_ORDER = ["today", "applications", "tracking", "offers", "assistant", "missions", "memory"];
  const GO_KEYS = {
    d: "today", a: "applications", s: "tracking", o: "offers",
    c: "assistant", m: "missions", e: "memory",
  };

  const normalize = (value) => String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();

  function commandEntries() {
    const nav = VIEW_ORDER.map((view, index) => ({
      id: `nav-${view}`,
      group: "Navigation",
      label: VIEWS[view].title,
      detail: VIEWS[view].subtitle,
      key: `Alt+${index + 1}`,
      search: `vue ${view} aller`,
      run: () => setView(view),
    }));
    const actions = [
      {
        id: "action-refresh",
        group: "Actions",
        label: "Actualiser les données",
        detail: "Recharge les sources locales sans rien envoyer",
        key: "R",
        search: "refresh recharger",
        run: () => refresh(),
      },
      {
        id: "action-filter",
        group: "Actions",
        label: "Filtrer les offres",
        detail: "Ouvrir Offres et placer le curseur dans le filtre",
        key: "/",
        search: "recherche chercher",
        run: () => { setView("offers"); focusFilter(); },
      },
      {
        id: "action-shortcuts",
        group: "Actions",
        label: "Afficher les raccourcis clavier",
        detail: "Toutes les combinaisons disponibles",
        key: "?",
        search: "aide help touches",
        run: () => openShortcuts(),
      },
    ];
    const dossiers = (state.pipeline?.pipeline ?? [])
      .filter((item, index, all) => item.job_id
        && item.progress_percent < 100
        && all.findIndex((other) => other.job_id === item.job_id) === index)
      .slice(0, 4)
      .map((item) => ({
        id: `dossier-${item.job_id}`,
        group: "Dossiers en cours",
        label: item.title || "Dossier",
        detail: `${item.company || "—"} · ${item.next_action_label || "préparer le dossier"}`,
        key: "",
        search: "dossier preparer apply kit",
        run: () => showApplyKit(item.job_id, item.title),
      }));
    const links = [
      { id: "link-career", group: "Liens", label: "Ouvrir Career", detail: "Espace candidatures complet", key: "↗", search: "candidatures", run: () => window.open("/career", "_blank", "noopener") },
      { id: "link-v5", group: "Liens", label: "Ouvrir V5", detail: "Mémoire, file de tâches, atelier", key: "↗", search: "memoire taches", run: () => window.open("/v5", "_blank", "noopener") },
      { id: "link-v3", group: "Liens", label: "Ouvrir V3", detail: "Interface historique", key: "↗", search: "historique excel", run: () => window.open("/", "_blank", "noopener") },
    ];
    return [...nav, ...actions, ...dossiers, ...links];
  }

  function commandScore(command, query) {
    if (!query) return 0;
    const label = normalize(command.label);
    if (label.startsWith(query)) return 0;
    if (label.includes(query)) return 1;
    const haystack = normalize(`${command.label} ${command.detail} ${command.group} ${command.search}`);
    if (haystack.includes(query)) return 2;
    let position = 0;
    for (const char of query) {
      position = haystack.indexOf(char, position);
      if (position === -1) return -1;
      position += 1;
    }
    return 3;
  }

  function filterCommands(entries, rawQuery) {
    const query = normalize(String(rawQuery ?? "").trim());
    return entries
      .map((command, index) => ({ command, index, score: commandScore(command, query) }))
      .filter((hit) => hit.score >= 0)
      .sort((a, b) => a.score - b.score || a.index - b.index)
      .map((hit) => hit.command);
  }

  function highlightLabel(label, rawQuery) {
    const query = normalize(String(rawQuery ?? "").trim());
    if (!query) return label;
    const at = normalize(label).indexOf(query);
    if (at === -1) return label;
    return [
      label.slice(0, at),
      el("mark", {}, label.slice(at, at + query.length)),
      label.slice(at + query.length),
    ];
  }

  let paletteEl = null;
  let paletteInput = null;
  let paletteList = null;
  let paletteStatus = null;
  let paletteHits = [];
  let paletteActive = 0;
  let palettePreviousFocus = null;
  let shortcutsEl = null;
  let shortcutsPreviousFocus = null;
  let shortcutsCloseButton = null;
  let goPrefix = false;
  let goTimer = 0;

  function buildPalette() {
    if (paletteEl) return;
    paletteInput = el("input", {
      id: "paletteInput",
      type: "text",
      role: "combobox",
      autocomplete: "off",
      spellcheck: "false",
      placeholder: "Que veux-tu faire ?",
      "aria-autocomplete": "list",
      "aria-expanded": "true",
      "aria-controls": "paletteList",
      "aria-activedescendant": "",
      "aria-label": "Rechercher une commande",
    });
    paletteList = el("div", {
      id: "paletteList", class: "palette-list", role: "listbox", "aria-label": "Commandes disponibles",
    });
    paletteStatus = el("div", {
      class: "visually-hidden", role: "status", "aria-live": "polite",
    });
    paletteEl = el("div", {
      class: "modal-overlay palette-overlay",
      id: "paletteOverlay",
      hidden: true,
      onclick: (event) => { if (event.target === paletteEl) closePalette(); },
    },
      el("div", {
        class: "palette", role: "dialog", "aria-modal": "true", "aria-labelledby": "paletteTitle",
      },
        el("div", { class: "palette-head" },
          el("span", { class: "palette-icon", html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 3a3.5 3.5 0 013.4 4.4l4.7 4.7A3.5 3.5 0 1116 15l-4.7-4.7A3.5 3.5 0 119.5 3zm0 1.8a1.7 1.7 0 100 3.4 1.7 1.7 0 000-3.4zm7 10.4a1.7 1.7 0 100 3.4 1.7 1.7 0 000-3.4z"/></svg>' }),
          el("h2", { id: "paletteTitle", class: "visually-hidden" }, "Palette de commandes"),
          paletteInput,
          el("kbd", { class: "palette-esc", "aria-hidden": "true" }, "esc"),
        ),
        paletteList,
        paletteStatus,
        el("div", { class: "palette-foot" },
          el("span", {}, el("kbd", {}, "↑"), el("kbd", {}, "↓"), " naviguer"),
          el("span", {}, el("kbd", {}, "↵"), " exécuter"),
          el("span", {}, el("kbd", {}, "esc"), " fermer"),
        ),
      ),
    );
    paletteInput.addEventListener("input", () => {
      paletteActive = 0;
      renderPalette();
    });
    paletteInput.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") { event.preventDefault(); movePalette(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); movePalette(-1); }
      else if (event.key === "Home") { event.preventDefault(); setPaletteActive(0); }
      else if (event.key === "End") { event.preventDefault(); setPaletteActive(paletteHits.length - 1); }
      else if (event.key === "Enter") { event.preventDefault(); runPaletteCommand(); }
      else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closePalette(); }
      else if (event.key === "Tab") { event.preventDefault(); }
    });
    document.body.append(paletteEl);
  }

  function renderPalette() {
    if (!paletteEl || paletteEl.hidden) return;
    paletteHits = filterCommands(commandEntries(), paletteInput.value);
    if (paletteStatus) {
      const count = paletteHits.length;
      paletteStatus.textContent = count
        ? `${count} commande${count > 1 ? "s" : ""} disponible${count > 1 ? "s" : ""}`
        : "Aucune commande";
    }
    if (paletteActive >= paletteHits.length) paletteActive = 0;
    paletteList.replaceChildren();
    if (!paletteHits.length) {
      paletteList.append(el("div", { class: "palette-empty" },
        el("strong", {}, "Aucune commande"),
        el("span", {}, "Essaie « offres », « actualiser » ou « raccourcis ».")));
      paletteInput.setAttribute("aria-activedescendant", "");
      return;
    }
    let group = "";
    for (const [index, command] of paletteHits.entries()) {
      if (command.group !== group) {
        group = command.group;
        paletteList.append(el("div", { class: "palette-group", role: "presentation" }, group));
      }
      paletteList.append(el("div", {
        class: "palette-item",
        id: `palette-option-${index}`,
        role: "option",
        "aria-selected": index === paletteActive ? "true" : "false",
        onmousemove: () => { if (paletteActive !== index) setPaletteActive(index); },
        onclick: () => { paletteActive = index; runPaletteCommand(); },
      },
        el("span", { class: "palette-glyph", "aria-hidden": "true" }, "›"),
        el("div", { class: "palette-main" },
          el("strong", {}, highlightLabel(command.label, paletteInput.value)),
          el("small", {}, command.detail || ""),
        ),
        command.key ? el("kbd", { class: "palette-key" }, command.key) : null,
      ));
    }
    setPaletteActive(paletteActive, false);
  }

  function setPaletteActive(index, scroll = true) {
    if (!paletteHits.length) {
      paletteActive = 0;
      paletteInput?.setAttribute("aria-activedescendant", "");
      return;
    }
    paletteActive = (index + paletteHits.length) % paletteHits.length;
    for (const [position, node] of [...paletteList.querySelectorAll(".palette-item")].entries()) {
      const selected = position === paletteActive;
      node.setAttribute("aria-selected", selected ? "true" : "false");
      node.classList.toggle("active", selected);
    }
    paletteInput?.setAttribute("aria-activedescendant", `palette-option-${paletteActive}`);
    if (scroll) document.getElementById(`palette-option-${paletteActive}`)?.scrollIntoView({ block: "nearest" });
  }

  function movePalette(delta) {
    setPaletteActive(paletteActive + delta);
  }

  function runPaletteCommand() {
    const command = paletteHits[paletteActive];
    if (!command) return;
    closePalette();
    try {
      command.run();
    } catch (error) {
      console.error("PALETTE_RUN_FAIL:", error.message);
    }
  }

  function openPalette(query = "") {
    if (shortcutsEl && !shortcutsEl.hidden) closeShortcuts();
    buildPalette();
    if (!paletteEl.hidden && !query) {
      paletteInput.focus();
      return;
    }
    if (paletteEl.hidden) palettePreviousFocus = document.activeElement;
    paletteEl.hidden = false;
    document.body.classList.add("palette-open");
    paletteInput.value = query;
    paletteActive = 0;
    renderPalette();
    paletteInput.focus();
  }

  function closePalette() {
    if (!paletteEl || paletteEl.hidden) return;
    paletteEl.hidden = true;
    document.body.classList.remove("palette-open");
    const target = palettePreviousFocus;
    palettePreviousFocus = null;
    if (target instanceof HTMLElement && target.isConnected) target.focus();
  }

  function togglePalette() {
    if (paletteEl && !paletteEl.hidden) closePalette();
    else openPalette();
  }

  function shortcutRows() {
    return [
      {
        title: "Général",
        rows: [
          ["⌘K / Ctrl+K", "Ouvrir ou fermer la palette"],
          ["?", "Afficher les raccourcis clavier"],
          ["Esc", "Fermer la fenêtre active"],
          ["R", "Actualiser les données"],
          ["/", "Filtrer les offres"],
        ],
      },
      {
        title: "Navigation directe",
        rows: VIEW_ORDER.map((view, index) => [`Alt+${index + 1}`, VIEWS[view].title]),
      },
      {
        title: "Séquences G",
        rows: [
          ["G puis D", "Aujourd’hui"],
          ["G puis A", "Candidatures"],
          ["G puis S", "Suivi"],
          ["G puis O", "Offres"],
          ["G puis C", "Terminal"],
          ["G puis M", "Missions"],
          ["G puis E", "Mémoire"],
        ],
      },
    ];
  }

  function openShortcuts() {
    if (paletteEl && !paletteEl.hidden) closePalette();
    if (!shortcutsEl) {
      shortcutsCloseButton = el("button", {
        class: "ghost-btn", type: "button", onclick: () => closeShortcuts(),
      }, "Fermer");
      shortcutsEl = el("div", {
        class: "modal-overlay",
        id: "shortcutsOverlay",
        hidden: true,
        onclick: (event) => { if (event.target === shortcutsEl) closeShortcuts(); },
      },
        el("div", {
          class: "card modal-box shortcuts-box",
          role: "dialog",
          "aria-modal": "true",
          "aria-labelledby": "shortcutsTitle",
        },
          el("div", { class: "section-title", style: "margin-top:0" },
            el("h2", { id: "shortcutsTitle" }, "Raccourcis clavier"),
            el("span", { class: "hint" }, "aucune souris requise")),
          el("div", { class: "shortcut-grid" }, shortcutRows().map((section) =>
            el("div", { class: "shortcut-section" },
              el("h3", {}, section.title),
              el("dl", {}, section.rows.flatMap(([keys, label]) => [
                el("dt", {}, el("kbd", {}, keys)),
                el("dd", {}, label),
              ])),
            ))),
          el("div", { class: "shortcut-actions" }, shortcutsCloseButton),
        ),
      );
      shortcutsEl.addEventListener("keydown", (event) => {
        if (event.key === "Tab") { event.preventDefault(); shortcutsCloseButton.focus(); }
        else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeShortcuts(); }
      });
      document.body.append(shortcutsEl);
    }
    if (shortcutsEl.hidden) shortcutsPreviousFocus = document.activeElement;
    shortcutsEl.hidden = false;
    shortcutsCloseButton.focus();
  }

  function closeShortcuts() {
    if (!shortcutsEl || shortcutsEl.hidden) return;
    shortcutsEl.hidden = true;
    const target = shortcutsPreviousFocus;
    shortcutsPreviousFocus = null;
    if (target instanceof HTMLElement && target.isConnected) target.focus();
  }

  function overlayOpen() {
    return Boolean(
      (paletteEl && !paletteEl.hidden)
      || (shortcutsEl && !shortcutsEl.hidden)
      || document.querySelector(".modal-overlay:not([hidden])"),
    );
  }

  function closeTopOverlay() {
    if (paletteEl && !paletteEl.hidden) { closePalette(); return true; }
    if (shortcutsEl && !shortcutsEl.hidden) { closeShortcuts(); return true; }
    const overlays = document.querySelectorAll(".modal-overlay:not([hidden])");
    if (overlays.length) { overlays[overlays.length - 1].remove(); return true; }
    return false;
  }

  function focusFilter() {
    const input = $("#searchInput");
    if (!input) return;
    requestAnimationFrame(() => { input.focus(); input.select(); });
  }

  function isTypingTarget(target) {
    if (!(target instanceof Element)) return false;
    const tag = target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.code === "KeyK") {
      event.preventDefault();
      togglePalette();
      return;
    }
    if (event.key === "Escape" || event.code === "Escape") {
      if (closeTopOverlay()) event.preventDefault();
      return;
    }
    if (overlayOpen() || isTypingTarget(event.target)) return;
    if (event.altKey && !event.metaKey && !event.ctrlKey && /^Digit[1-7]$/.test(event.code)) {
      const view = VIEW_ORDER[Number(event.code.slice(5)) - 1];
      if (view) { event.preventDefault(); setView(view); }
      return;
    }
    if (event.metaKey || event.ctrlKey) return;
    if (event.key === "/" || (event.code === "Slash" && !event.shiftKey)) {
      event.preventDefault();
      setView("offers");
      focusFilter();
      return;
    }
    if (event.key === "?" || (event.code === "Slash" && event.shiftKey)) {
      event.preventDefault();
      openShortcuts();
      return;
    }
    if (goPrefix) {
      const view = GO_KEYS[event.key.toLowerCase()];
      goPrefix = false;
      clearTimeout(goTimer);
      if (view) { event.preventDefault(); setView(view); }
      return;
    }
    if (event.key.toLowerCase() === "g" && !event.shiftKey) {
      goPrefix = true;
      clearTimeout(goTimer);
      goTimer = setTimeout(() => { goPrefix = false; }, 1200);
      return;
    }
    if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      refresh();
    }
  });

  window.__nagePalette = {
    open: (query = "") => openPalette(query),
    close: () => closePalette(),
    isOpen: () => Boolean(paletteEl && !paletteEl.hidden),
    commands: () => commandEntries().map(({ id, group, label }) => ({ id, group, label })),
    filter: (query) => filterCommands(commandEntries(), query).map(({ id }) => id),
    openShortcuts: () => openShortcuts(),
    shortcutsOpen: () => Boolean(shortcutsEl && !shortcutsEl.hidden),
  };

  /* ---------- Démarrage ---------- */

  for (const button of document.querySelectorAll(".nav-item")) {
    button.addEventListener("click", () => setView(button.dataset.view));
  }
  $("#paletteBtn").addEventListener("click", () => openPalette());
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
