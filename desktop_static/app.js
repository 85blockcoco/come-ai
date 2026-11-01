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
    letterStudio: restoreLetterDraft(),
  };

  function restoreLetterDraft() {
    const draft = { jobId: "", language: "fr", tone: "formal", name: "", facts: "", body: "", letterId: "", format: "md", revision: 0, approved: false, check: null, busy: false, message: "", downloadUrl: "" };
    try {
      const saved = JSON.parse(sessionStorage.getItem("nage-letter-draft-v2") || "{}");
      for (const key of ["jobId", "language", "tone", "name", "facts", "body", "letterId", "format"]) {
        if (typeof saved[key] === "string") draft[key] = saved[key].slice(0, 30000);
      }
    } catch { /* Draft stays in memory when browser storage is unavailable. */ }
    return draft;
  }

  function saveLetterDraft() {
    const { jobId, language, tone, name, facts, body, letterId, format } = state.letterStudio;
    try { sessionStorage.setItem("nage-letter-draft-v2", JSON.stringify({ jobId, language, tone, name, facts, body, letterId, format })); }
    catch { state.letterStudio.message = "Le brouillon reste ouvert ; la sauvegarde de cet onglet est indisponible."; }
  }

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
    const studio = renderLetterStudio();
    if (!p) { host.replaceChildren(studio, loading()); return; }
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
    const draft = state.letterStudio;
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
    offer.value = draft.jobId;
    language.value = draft.language;
    tone.value = draft.tone;
    const name = el("input", { id: "letterName", maxlength: "160", "aria-label": "Nom de candidature", placeholder: "Ton nom" });
    name.value = draft.name;
    const facts = el("textarea", { id: "letterFacts", rows: "3", maxlength: "12000", "aria-label": "Faits approuvés du profil", placeholder: "Un fait vérifié par ligne : diplôme, expérience ou compétence." });
    facts.value = draft.facts;
    const useProfile = el("button", { type: "button", class: "ghost-btn" }, "Utiliser mon profil enregistré");
    const preview = el("textarea", { id: "letterPreview", rows: "12", maxlength: "30000", "aria-label": "Aperçu modifiable de la lettre", placeholder: "La lettre apparaîtra ici. Relis-la avant toute approbation." });
    preview.value = draft.body;
    const status = el("div", { class: "letter-status", role: "status", "aria-live": "polite" });
    status.textContent = draft.message;
    const report = el("div", { class: "letter-report" });
    if (draft.check) {
      report.append(el("p", {}, `Contrôle factuel : ${draft.check.facts_score ?? 0}/100 · complétude : ${draft.check.completeness_score ?? 0}/100`),
        el("p", { class: "note" }, "Ce contrôle recherche des écarts avec les faits fournis. Relis aussi les affirmations non vérifiables."),
        el("ul", {}, [...(draft.check.blockers || []), ...(draft.check.warnings || [])].map((warning) => el("li", {}, warning))));
    }
    const generate = el("button", { type: "button", class: "send-btn" }, "Prévisualiser");
    const verify = el("button", { type: "button", class: "ghost-btn" }, "Vérifier les faits");
    const approve = el("button", { type: "button", class: "ghost-btn" }, draft.approved ? "Approuvée" : "Approuver cette version");
    const exportFormat = el("select", { "aria-label": "Format de la lettre" },
      [["md", "Markdown"], ["docx", "Word"], ["pdf", "PDF"], ["txt", "Texte"]].map(([value, label]) => el("option", { value }, label)));
    exportFormat.value = draft.format;
    exportFormat.addEventListener("change", () => { draft.format = exportFormat.value; saveLetterDraft(); });
    const exportButton = el("button", { type: "button", class: "ghost-btn" }, "Créer le fichier");
    const syncButtons = () => {
      generate.disabled = draft.busy || !draft.jobId || !state.jobs;
      useProfile.disabled = draft.busy;
      verify.disabled = draft.busy || !draft.body.trim();
      approve.disabled = draft.busy || !draft.check || Boolean(draft.check.blockers?.length) || !draft.body.trim();
      exportButton.disabled = draft.busy || !draft.approved;
      for (const control of [offer, language, tone, name, facts, preview, exportFormat]) control.disabled = draft.busy;
    };
    const invalidate = () => {
      draft.revision += 1; draft.approved = false; draft.check = null; draft.downloadUrl = "";
      draft.message = "Modification enregistrée dans cet onglet. Vérifie puis approuve cette nouvelle version.";
      approve.textContent = "Approuver cette version"; report.replaceChildren();
      status.textContent = draft.message; download.hidden = true; saveLetterDraft(); syncButtons();
    };
    for (const [control, key] of [[offer, "jobId"], [language, "language"], [tone, "tone"], [name, "name"], [facts, "facts"], [preview, "body"]]) {
      control.addEventListener(control.tagName === "SELECT" ? "change" : "input", () => { draft[key] = control.value; invalidate(); });
    }
    const evidence = () => draft.facts.split("\n").map((line) => line.trim()).filter(Boolean).slice(0, 20);
    const run = async (action) => {
      if (draft.busy) return;
      draft.busy = true; status.textContent = "Traitement local…"; syncButtons();
      try { await action(); }
      catch (error) { draft.message = error.message; }
      finally { draft.busy = false; saveLetterDraft(); renderApplications(); }
    };
    useProfile.addEventListener("click", () => run(async () => {
      const profile = await api("/api/career/profile");
      draft.name = profile.display_name || "";
      draft.facts = [profile.education, profile.experience, profile.skills, profile.languages].filter(Boolean).join("\n");
      invalidate(); draft.message = "Profil chargé localement. Vérifie les faits avant de préparer la lettre.";
    }));
    generate.addEventListener("click", () => run(async () => {
      const job = jobs.find((item) => item.id === offer.value);
      if (!job) { draft.message = "Choisis d’abord une offre."; return; }
      const result = await api("/api/career/letter/render", { method: "POST", body: JSON.stringify({ candidate_name: draft.name, role: job.title, company: job.company, language: draft.language, tone: draft.tone, evidence: evidence() }) });
      draft.body = result.body || ""; draft.letterId = `letter-${job.id}`; invalidate();
      draft.message = (result.warnings || []).join(" · ") || "Brouillon prêt. Relis-le puis lance la vérification.";
    }));
    verify.addEventListener("click", () => run(async () => {
      draft.check = await api("/api/career/letter/check", { method: "POST", body: JSON.stringify({ letter_body: draft.body, evidence: evidence() }) });
      draft.approved = false; draft.message = draft.check.blockers?.length ? "Corrige les blocages ci-dessous avant l’approbation." : "Contrôle terminé. Tu peux approuver cette version après relecture.";
    }));
    approve.addEventListener("click", () => run(async () => {
      if (!draft.check || draft.check.blockers?.length) return;
      if (!draft.letterId) draft.letterId = `letter-local-${Date.now()}`;
      const result = await api("/api/career/letter/approve", { method: "POST", body: JSON.stringify({ letter_id: draft.letterId, letter_body: draft.body, language: draft.language, approved: true, note: "Version relue dans NAGE" }) });
      draft.approved = result.approved === true;
      draft.message = draft.approved ? "Cette version est approuvée. Choisis un format et crée le fichier." : (result.blockers || []).join(" · ");
    }));
    exportButton.addEventListener("click", () => run(async () => {
      if (!draft.approved) return;
      const result = await api("/api/career/letter/export", { method: "POST", body: JSON.stringify({ letter_body: draft.body, title: draft.letterId, language: draft.language, fmt: draft.format }) });
      draft.downloadUrl = result.ok ? result.download_url || "" : "";
      draft.message = result.ok ? "Fichier prêt : utilise le lien de téléchargement." : (result.blockers || []).join(" · ");
    }));
    const download = el("a", { class: "ghost-btn", href: draft.downloadUrl || "#", download: "", hidden: !draft.downloadUrl }, "Télécharger la lettre");
    syncButtons();
    return el("section", { class: "card letter-studio", "aria-labelledby": "letterStudioTitle" },
      el("div", { class: "section-title no-gap" }, el("h2", { id: "letterStudioTitle" }, "Lettre de motivation"), el("span", { class: "hint" }, "locale · révision humaine obligatoire")),
      el("p", { class: "note" }, "Choisis l’offre, la langue et le ton. NAGE prépare un brouillon sans inventer de faits et n’envoie jamais la candidature."),
      !jobs.length ? el("p", { class: "note" }, state.jobs ? "Enregistre une offre pour préparer ta lettre." : "Chargement des offres…") : null,
      el("div", { class: "letter-controls" }, el("label", {}, "Offre", offer), el("label", {}, "Langue", language), el("label", {}, "Ton", tone)),
      el("details", {}, el("summary", {}, "Faits et nom utilisés pour personnaliser la lettre"), el("label", {}, "Nom", name), el("label", {}, "Faits approuvés (un par ligne)", facts), useProfile),
      generate, preview, report,
      el("div", { class: "letter-actions" }, verify, approve, el("label", {}, "Format", exportFormat), exportButton, download), status,
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
    button.setAttribute("aria-label", VIEWS[button.dataset.view]?.title || button.textContent.trim());
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
