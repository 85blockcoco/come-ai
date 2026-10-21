/* Progression réelle d'une exploration Career.
 *
 * Le serveur est seul maître des étapes : ce fichier ne calcule jamais de
 * progression. Il lit l'état renvoyé par
 * GET /api/career/stage-search/explorations/{run_id} et affiche exactement ce
 * que le serveur a réellement terminé (phase, sources terminées, réussies, en
 * erreur, annonces lues, offres qualifiées).
 *
 * Aucun chronomètre local ne remplace un compteur du serveur : si le serveur
 * n'a pas terminé une source, l'interface ne l'annonce pas comme terminée.
 */
(function (root) {
  "use strict";

  var BASE_PATH = "/api/career/stage-search/explorations";
  var STORAGE_KEY = "career.exploration.run_id";
  var POLL_INTERVAL_MS = 1000;
  var TERMINAL_STATUSES = ["completed", "cancelled", "failed", "interrupted"];
  var PHASE_LABELS = {
    preparing: "Préparation des sources",
    consulting: "Consultation des sources",
    normalizing: "Normalisation des annonces",
    qualifying: "Qualification des offres",
    deduplicating: "Déduplication des offres",
    ranking: "Classement des offres",
    persisting: "Enregistrement des offres",
    completed: "Exploration terminée",
  };
  var STATUS_LABELS = {
    running: "en cours",
    completed: "terminée",
    cancelled: "annulée",
    failed: "interrompue",
    interrupted: "interrompue",
  };

  function count(value) {
    return Number.isFinite(value) ? String(value) : "0";
  }

  function isTerminal(state) {
    return Boolean(state) && TERMINAL_STATUSES.indexOf(String(state.status || "")) >= 0;
  }

  function request(path, options) {
    var settings = options || {};
    var init = {
      method: settings.method || "GET",
      headers: settings.body ? { "Content-Type": "application/json" } : {},
    };
    if (settings.body) init.body = settings.body;
    return fetch(path, init).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) {
          var detail = body && typeof body.detail === "string" ? body.detail : "L’exploration Career n’a pas abouti.";
          var error = new Error(detail);
          error.status = response.status;
          throw error;
        }
        return body;
      });
    });
  }

  function startExploration(options) {
    var settings = options || {};
    var body = JSON.stringify({ force: Boolean(settings.force) });
    return request(BASE_PATH, { method: "POST", body: body }).then(function (state) {
      rememberRun(state && state.run_id);
      return state;
    });
  }

  function fetchExploration(runId) {
    if (!runId) return Promise.reject(new Error("Exploration inconnue."));
    return request(BASE_PATH + "/" + encodeURIComponent(runId));
  }

  function cancelExploration(runId) {
    if (!runId) return Promise.reject(new Error("Exploration inconnue."));
    return request(BASE_PATH + "/" + encodeURIComponent(runId) + "/cancel", { method: "POST" });
  }

  function rememberRun(runId) {
    try {
      if (runId && root.localStorage) root.localStorage.setItem(STORAGE_KEY, runId);
    } catch (_) {
      /* Le stockage local peut être indisponible : la reprise se fait alors
         par la liste des explorations du serveur. */
    }
  }

  function forgetRun() {
    try {
      if (root.localStorage) root.localStorage.removeItem(STORAGE_KEY);
    } catch (_) {
      /* Aucun stockage local : sans conséquence. */
    }
  }

  function storedRunId() {
    try {
      return root.localStorage ? root.localStorage.getItem(STORAGE_KEY) : "";
    } catch (_) {
      return "";
    }
  }

  /* The text of the progress bar is built from the server state only. */
  function describe(state) {
    var source = state || {};
    var order = Array.isArray(source.phase_order) && source.phase_order.length
      ? source.phase_order
      : Object.keys(PHASE_LABELS);
    var workPhases = order.filter(function (phase) { return phase !== "completed"; });
    var denominator = workPhases.length || 1;
    var completed = Number.isFinite(source.phases_completed) ? source.phases_completed : 0;
    var percent = Math.max(0, Math.min(100, Math.round(100 * completed / denominator)));
    if (source.status === "completed") percent = 100;
    var phase = source.phase || "preparing";
    var label = PHASE_LABELS[phase] || phase;
    var status = STATUS_LABELS[source.status] || source.status || "";
    var detail = count(source.sources_completed) + "/" + count(source.sources_total)
      + " sources terminées · " + count(source.sources_succeeded) + " réussies · "
      + count(source.sources_failed) + " en erreur · " + count(source.offers_read)
      + " annonces lues · " + count(source.offers_qualified) + " offres qualifiées";
    if (source.cancel_requested) detail += " · annulation demandée";
    if (source.error) detail += " · " + source.error;
    return {
      percent: percent,
      label: label + (status ? " (" + status + ")" : ""),
      detail: detail,
      phase: phase,
      status: source.status || "",
    };
  }

  /* Writes the state into the given elements; no DOM lookup happens here so
     the rendering can be checked without a browser. */
  function renderState(state, target) {
    var elements = target || {};
    var described = describe(state);
    if (elements.label) elements.label.textContent = described.label;
    if (elements.percent) elements.percent.textContent = described.percent + " %";
    if (elements.detail) elements.detail.textContent = described.detail;
    if (elements.bar) {
      elements.bar.setAttribute("aria-valuenow", String(described.percent));
      elements.bar.setAttribute("aria-valuetext", described.detail);
    }
    if (elements.fill && elements.fill.style) elements.fill.style.width = described.percent + "%";
    if (elements.container && elements.container.classList) {
      elements.container.classList.toggle("is-complete", described.status === "completed");
      elements.container.classList.toggle("is-error", described.status === "failed" || described.status === "interrupted");
      elements.container.classList.remove("is-hidden");
      if (elements.container.hasAttribute && elements.container.hasAttribute("hidden")) {
        elements.container.removeAttribute("hidden");
      }
    }
    return described;
  }

  function renderInto(state) {
    var doc = root.document;
    if (!doc) return describe(state);
    var container = doc.getElementById("stagehunter-progress");
    var bar = doc.getElementById("stagehunter-progress-bar");
    return renderState(state, {
      container: container,
      label: doc.getElementById("stagehunter-progress-label"),
      percent: doc.getElementById("stagehunter-progress-percent"),
      detail: doc.getElementById("stagehunter-progress-detail"),
      bar: bar,
      fill: bar ? bar.querySelector(".stagehunter-progress-fill") : null,
    });
  }

  /* Polls the server until the run reaches a terminal state. */
  function poll(runId, options) {
    var settings = options || {};
    var intervalMs = Number.isFinite(settings.intervalMs) ? settings.intervalMs : POLL_INTERVAL_MS;
    var timeoutMs = Number.isFinite(settings.timeoutMs) ? settings.timeoutMs : 20 * 60 * 1000;
    var onState = typeof settings.onState === "function" ? settings.onState : function () {};
    var stopped = false;
    var timer = null;
    var promise = new Promise(function (resolve, reject) {
      var startedAt = Date.now();
      var tick = function () {
        if (stopped) return;
        fetchExploration(runId).then(function (state) {
          if (stopped) return;
          onState(state);
          if (isTerminal(state)) {
            resolve(state);
            return;
          }
          schedule();
        }).catch(function (error) {
          if (stopped) return;
          if (Date.now() - startedAt > timeoutMs) {
            reject(error);
            return;
          }
          schedule();
        });
      };
      var schedule = function () {
        if (stopped) return;
        if (Date.now() - startedAt > timeoutMs) {
          reject(new Error("L’exploration n’a pas rendu la main dans le temps."));
          return;
        }
        timer = setTimeout(tick, intervalMs);
      };
      tick();
    });
    return {
      promise: promise,
      stop: function () {
        stopped = true;
        if (timer) clearTimeout(timer);
      },
    };
  }

  /* Resumes the last run after a page reload: the run identifier is enough. */
  function resume(options) {
    var settings = options || {};
    var runId = settings.runId || storedRunId();
    if (!runId) return null;
    return fetchExploration(runId).then(function (state) {
      if (isTerminal(state)) {
        forgetRun();
        if (typeof settings.onState === "function") settings.onState(state);
        return null;
      }
      if (typeof settings.onState === "function") settings.onState(state);
      return poll(runId, settings);
    }).catch(function () {
      forgetRun();
      return null;
    });
  }

  root.CareerExplorationProgress = {
    BASE_PATH: BASE_PATH,
    TERMINAL_STATUSES: TERMINAL_STATUSES,
    PHASE_LABELS: PHASE_LABELS,
    isTerminal: isTerminal,
    describe: describe,
    renderState: renderState,
    renderInto: renderInto,
    startExploration: startExploration,
    fetchExploration: fetchExploration,
    cancelExploration: cancelExploration,
    rememberRun: rememberRun,
    forgetRun: forgetRun,
    storedRunId: storedRunId,
    poll: poll,
    resume: resume,
  };
})(typeof window !== "undefined" ? window : globalThis);
