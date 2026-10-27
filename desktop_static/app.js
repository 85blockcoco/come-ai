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

  /* ---------- Accessibilité : annonces et notifications ---------- */

  let announceTimer = null;
  let toastTimer = null;

  /* Région live unique : les changements de vue, filtres, copies et erreurs
     sont annoncés sans déplacer le focus. */
  function announce(message) {
    const node = $("#srAnnounce");
    if (!node || !message) return;
    node.textContent = "";
    clearTimeout(announceTimer);
    announceTimer = setTimeout(() => { node.textContent = String(message); }, 60);
  }

  function notify(message, kind = "info") {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = String(message);
    toast.classList.toggle("error", kind === "error");
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, kind === "error" ? 8000 : 4500);
    announce(message);
  }

  const focusablesIn = (root) => [...root.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((node) => node.getClientRects().length > 0);

  /* ---------- Dialogues accessibles (focus piégé, Échap, restitution) ---------- */

  let dialogSeq = 0;
  let activeDialog = null;

  function mountDialog(overlay, box, options = {}) {
    const heading = box.querySelector("h2");
    const titleId = heading ? `dialog-title-${++dialogSeq}` : null;
    if (heading) heading.id = titleId;
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    if (titleId) box.setAttribute("aria-labelledby", titleId);
    else box.setAttribute("aria-label", options.label || "Fenêtre de dialogue");
    box.setAttribute("tabindex", "-1");

    const previous = document.activeElement;
    const closeButton = el("button", {
      type: "button", class: "ghost-btn modal-close-x", "aria-label": "Fermer la fenêtre",
    }, "✕ Fermer");
    box.prepend(closeButton);

    if (activeDialog) activeDialog.close({ restore: false });
    document.body.append(overlay);
    box.focus();

    let closed = false;
    function close({ restore = true } = {}) {
      if (closed) return;
      closed = true;
      document.removeEventListener("keydown", onKeydown, true);
      overlay.remove();
      if (activeDialog?.overlay === overlay) activeDialog = null;
      if (restore && previous && typeof previous.focus === "function") previous.focus();
      if (typeof options.onClose === "function") options.onClose();
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusablesIn(box);
      if (!items.length) {
        event.preventDefault();
        box.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === first || current === box)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    }

    closeButton.addEventListener("click", () => close());
    overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
    document.addEventListener("keydown", onKeydown, true);
    overlay.__close = close;
    activeDialog = { overlay, close };
    return { overlay, box, close };
  }

  function closeDialogButton(label = "Fermer") {
    return el("button", {
      type: "button", class: "ghost-btn modal-close", onclick: (event) => {
        const overlay = event.currentTarget.closest(".modal-overlay");
        if (overlay?.__close) overlay.__close();
      },
    }, label);
  }

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

  function setView(view, options = {}) {
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
    document.title = `${VIEWS[view].title} — NAGE`;
    render(view);
    history.replaceState(null, "", `#${view}`);
    if (options.focus) {
      $("#viewTitle").focus({ preventScroll: true });
      announce(`${VIEWS[view].title}. ${VIEWS[view].subtitle}`);
    }
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
    $("#main").setAttribute("aria-busy", "true");
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
    $("#main").removeAttribute("aria-busy");
    renderBadges();
    render(state.view);
    announce(failed === 0
      ? "Données chargées."
      : `${results.length - failed} sources sur ${results.length} chargées.`);
  }

  async function refresh() {
    const button = $("#refreshBtn");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    announce("Actualisation des données…");
    try {
      await Promise.allSettled(Object.values(loaders).map(async (load) => {
        await load();
        renderBadges();
        render(state.view);
      }));
      renderBadges();
      render(state.view);
      notify("Données actualisées.");
    } catch (error) {
      notify(`Actualisation partielle : ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
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
    else if (view === "missions") renderMissions();
    else if (view === "memory") renderMemory();
  }

  const loading = () => el("div", {
    class: "card skeleton", role: "status", "aria-label": "Chargement des données",
  }, el("i", { "aria-hidden": "true" }), el("i", { "aria-hidden": "true" }), el("i", { "aria-hidden": "true" }));

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
        onkeydown: (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openTarget(item.target_view);
          }
        },
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
        el("div", {
          class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100",
          "aria-valuenow": String(progress), "aria-label": `Progression du dossier ${item.title || ""}`.trim(),
        }, el("i", { style: `width:${progress}%`, "aria-hidden": "true" })),
        el("small", { "aria-hidden": "true" }, `${progress} %`),
      ),
      el("div", { class: "offer-tags" },
        item.deadline_date ? el("span", { class: "chip amber" }, `échéance ${item.deadline_date}`) : null,
        item.official_url
          ? el("a", {
              class: "chip violet", href: item.official_url, target: "_blank", rel: "noopener",
              "aria-label": `Ouvrir l’offre ${item.title || ""} dans un nouvel onglet`.trim(),
            }, "offre ↗")
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
        ? filtered.slice(0, 120).map((job) => {
            const attrs = { class: "offer-row" };
            if (job.official_url) {
              attrs.role = "link";
              attrs.tabindex = "0";
              attrs["aria-label"] = `${job.title || "Offre"} — ${job.company || "entreprise inconnue"} (ouvre l’offre dans un nouvel onglet)`;
              attrs.onclick = () => window.open(job.official_url, "_blank", "noopener");
              attrs.onkeydown = (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  window.open(job.official_url, "_blank", "noopener");
                }
              };
            }
            return el("div", attrs,
              el("span", { class: "offer-logo", "aria-hidden": "true" }, (job.company || "?").slice(0, 1).toUpperCase()),
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
            );
          })
        : emptyState("Aucune correspondance", "Modifie le filtre pour retrouver une offre.")),
    );
  }

  function renderAssistant() {
    const host = $("#view-assistant");
    if (host.dataset.mounted === "1") return;
    host.dataset.mounted = "1";
    host.replaceChildren(
      el("div", { class: "card assistant-wrap" },
        el("div", {
          class: "chat-log", id: "chatLog", role: "log", "aria-live": "polite",
          "aria-relevant": "additions", "aria-label": "Conversation avec NAGE", tabindex: "0",
        },
          el("div", { class: "msg ai" },
            el("div", { class: "bubble" },
              "NAGE en ligne. Je peux analyser une offre, préparer un dossier, résumer un document ou chercher dans ta mémoire. Le mode Hors ligne est actif par défaut : rien ne quitte ton Mac. La réponse locale peut prendre jusqu’à une minute."),
            el("small", {}, "NAGE · local"),
          ),
        ),
        el("form", { class: "composer", id: "chatForm", "aria-label": "Envoyer un message à NAGE" },
          el("span", { class: "sr-only", id: "chatHint" }, "Entrée pour envoyer, Maj+Entrée pour un retour à la ligne."),
          el("textarea", {
            id: "chatInput", rows: "2", placeholder: "Demande-moi quelque chose… (Entrée pour envoyer)",
            "aria-label": "Message à NAGE", "aria-describedby": "chatHint",
          }),
          el("div", { class: "composer-row" },
            el("div", { class: "modes", role: "group", "aria-label": "Mode de l’assistant" },
              [["offline", "Hors ligne"], ["automatic", "Automatique"]].map(([mode, label]) =>
                el("button", {
                  type: "button", class: mode === "offline" ? "on" : "",
                  "aria-pressed": mode === "offline" ? "true" : "false",
                  onclick: (event) => {
                    state.chatMode = mode;
                    for (const b of event.currentTarget.parentElement.children) {
                      const active = b === event.currentTarget;
                      b.classList.toggle("on", active);
                      b.setAttribute("aria-pressed", active ? "true" : "false");
                    }
                    announce(`Mode assistant : ${label}.`);
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
    const typing = el("div", { class: "msg ai", id: "typing", role: "status", "aria-label": "NAGE réfléchit" },
      el("div", { class: "bubble" },
        el("span", { class: "typing", "aria-hidden": "true" }, el("i"), el("i"), el("i"))),
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
        el("div", { class: "pipeline-progress" },
          el("div", {
            class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100",
            "aria-valuenow": String(Math.min(100, it.progress_percent || 100)),
            "aria-label": `Progression de la candidature ${it.title || ""}`.trim(),
          }, el("i", { style: `width:${Math.min(100, it.progress_percent || 100)}%`, "aria-hidden": "true" })),
          el("small", {}, it.channel || "site")),
        el("div", { class: "offer-tags" }, it.follow_up_draft
          ? el("button", {
              class: "chip green", type: "button",
              "aria-label": `Copier la relance pour ${it.title || "cette candidature"}`,
              onclick: () => copyText(it.follow_up_draft, `Relance copiée pour ${it.title || "cette candidature"}.`),
            }, "copier relance")
          : null),
      )) : emptyState("Aucun envoi confirmé", "Marque une candidature « envoyé » pour la suivre ici.")),
      el("p", { class: "note tight" }, t.honesty || "Sont listées les candidatures déclarées envoyées."),
    );
  }

  async function showApplyKit(jobId, title) {
    let kit;
    try { kit = await api(`/api/career/apply-kit/${jobId}`, { method: "POST", body: "{}" }); }
    catch (e) { notify(`Dossier indisponible : ${e.message}`, "error"); return; }
    const overlay = el("div", { class: "modal-overlay" });
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
        Object.entries(kit.export_urls || {}).map(([k, u]) => el("a", {
          class: "chip green", href: u, target: "_blank", rel: "noopener",
          "aria-label": `Télécharger ${k} dans un nouvel onglet`,
        }, `${k} ↗`))),
      el("div", { class: "section-title" }, el("h2", {}, "Checklist humaine"), el("span", { class: "hint" }, "à valider avant envoi")),
      el("div", { class: "quick-list" }, (kit.checklist || []).map((c) =>
        el("div", { class: "quick-row" },
          el("span", { class: c.done ? "chip green" : "chip amber" }, c.done ? "ok" : "à faire"),
          el("div", { class: "quick-value" }, c.label || c.id || "—"),
          c.note ? el("span", { class: "quick-label" }, c.note) : null,
        ))),
      kit.deep_link ? el("a", { class: "ghost-btn", href: kit.deep_link, target: "_blank", rel: "noopener", style: "margin-top:12px;display:inline-flex" }, "Ouvrir le formulaire officiel ↗") : null,
      closeDialogButton(),
    );
    overlay.append(box);
    mountDialog(overlay, box, { label: "Dossier de candidature prêt" });
  }

  async function showAtsGuide(jobId, title) {
    let g;
    try { g = await api(`/api/career/ats-guide/${jobId}`); }
    catch (e) { notify(`Guide indisponible : ${e.message}`, "error"); return; }
    const overlay = el("div", { class: "modal-overlay" });
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
      closeDialogButton(),
    );
    overlay.append(box);
    mountDialog(overlay, box, { label: "Guide de candidature ATS" });
  }

  async function showQuickAnswers(jobId, title) {
    let data;
    try { data = await api(`/api/career/quick-answers/${jobId}`); }
    catch (e) { notify(`Réponses indisponibles : ${e.message}`, "error"); return; }
    const overlay = el("div", { class: "modal-overlay" });
    const box = el("div", { class: "card modal-box" },
      el("div", { class: "section-title", style: "margin-top:0" }, el("h2", {}, `Réponses types — ${title || "offre"}`), el("span", { class: "hint" }, `${data.answers?.length ?? 0} questions`)),
      el("div", { class: "quick-list" }, (data.answers || []).map((a) =>
        el("div", { class: "quick-row" },
          el("div", { class: "quick-label" }, a.label || a.question || "—"),
          el("div", { class: "quick-value" }, a.value || "(à compléter)"),
          el("button", {
            class: "chip", type: "button",
            "aria-label": `Copier la réponse : ${a.label || a.question || "question"}`,
            onclick: () => copyText(a.value || "", "Réponse copiée."),
          }, "copier"),
          el("span", { class: `chip ${a.confidence === "exact" ? "green" : a.confidence === "derived" ? "amber" : "red"}` }, a.confidence || "—"),
        ))),
      closeDialogButton(),
    );
    overlay.append(box);
    mountDialog(overlay, box, { label: "Réponses types" });
  }

  /* Remplace window.prompt : dialogue étiqueté, focus piégé, Échap = annuler. */
  function askChannel(title) {
    return new Promise((resolve) => {
      const overlay = el("div", { class: "modal-overlay" });
      let settled = false;
      const select = el("select", { id: "channelSelect", name: "channel" },
        el("option", { value: "site" }, "Site de l’entreprise"),
        el("option", { value: "email" }, "E-mail"),
        el("option", { value: "portal" }, "Portail / ATS"),
      );
      const form = el("form", { class: "channel-form" },
        el("label", { for: "channelSelect" }, "Canal d’envoi"),
        select,
        el("div", { class: "channel-actions" },
          el("button", { type: "submit", class: "send-btn" }, "Enregistrer l’envoi"),
          el("button", {
            type: "button", class: "ghost-btn",
            onclick: () => finish(null),
          }, "Annuler"),
        ),
      );
      const box = el("div", { class: "card modal-box" },
        el("div", { class: "section-title", style: "margin-top:0" },
          el("h2", {}, `Marquer envoyé — ${title || "cette offre"}`),
          el("span", { class: "hint" }, "confirmation humaine")),
        el("p", { class: "note tight" },
          "Aucun envoi automatique : cette action enregistre seulement ta confirmation, avec la date du jour."),
        form,
      );
      overlay.append(box);
      const dialog = mountDialog(overlay, box, { onClose: () => finish(null) });
      function finish(value) {
        if (settled) return;
        settled = true;
        dialog.close();
        resolve(value);
      }
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        finish(select.value);
      });
    });
  }

  async function markSent(jobId, title) {
    const channel = await askChannel(title);
    if (!channel) return;
    const iso = new Date().toISOString().slice(0, 19) + "Z";
    try {
      await api(`/api/career/send-confirmation/${jobId}`, { method: "POST", body: JSON.stringify({ channel, sent_at: iso }) });
      await loaders.tracker();
      renderBadges();
      if (state.view === "tracking") renderTracking();
      notify("Envoi enregistré. Tu peux le suivre dans « Suivi ».");
    } catch (e) { notify(`Échec de l’enregistrement : ${e.message}`, "error"); }
  }

  function copyText(text, successMessage = "Texte copié.") {
    if (!text) {
      notify("Rien à copier.", "error");
      return;
    }
    const fallback = () => {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.className = "sr-only";
      document.body.append(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      ta.remove();
      notify(ok ? successMessage : "Copie impossible : sélectionne le texte manuellement.", ok ? "info" : "error");
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(() => notify(successMessage)).catch(fallback);
    } else {
      fallback();
    }
  }

  function emptyState(title, detail) {
    return el("div", { class: "empty" }, el("strong", {}, title), el("span", {}, detail));
  }

  /* ---------- Démarrage ---------- */

  for (const button of document.querySelectorAll(".nav-item")) {
    button.addEventListener("click", () => setView(button.dataset.view, { focus: true }));
  }

  /* Navigation clavier dans la barre latérale : flèches = déplacement du
     focus, Entrée/Espace = activation (comportement natif du bouton). */
  const nav = $(".nav");
  nav?.addEventListener("keydown", (event) => {
    const items = [...nav.querySelectorAll(".nav-item")];
    const index = items.indexOf(document.activeElement);
    if (index === -1) return;
    let next = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % items.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    if (next === null) return;
    event.preventDefault();
    items[next].focus();
  });

  $(".skip-link")?.addEventListener("click", (event) => {
    event.preventDefault();
    const main = $("#main");
    main.focus();
    main.scrollIntoView({ block: "start" });
    announce("Contenu principal.");
  });

  window.addEventListener("hashchange", () => {
    const view = (location.hash || "#today").slice(1);
    if (VIEWS[view] && view !== state.view) setView(view);
  });

  $("#refreshBtn").addEventListener("click", refresh);

  let filterTimer = null;
  $("#searchInput").addEventListener("input", (event) => {
    state.filter = event.target.value;
    renderOffers();
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => {
      const shown = document.querySelectorAll("#view-offers .offer-row").length;
      announce(`${shown} offre${shown > 1 ? "s" : ""} affichée${shown > 1 ? "s" : ""}.`);
    }, 450);
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
