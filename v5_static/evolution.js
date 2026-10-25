"use strict";
(() => {
  const n = (id) => document.getElementById(id);
  let token = null, running = false, pollTimer = null, activeJobId = null;
  async function request(path, data) {
    const options = {headers: {"X-Workshop-Token": token || ""}};
    if (data !== undefined) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(data); }
    const response = await fetch(`/api/devkit${path}`, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Le cycle n’a pas pu être lancé.");
    return result;
  }
  function show(value) { n("evolutionMessage").textContent = value; }
  function renderRunResult(result) {
    n("evolutionDetails").hidden = false;
    n("evolutionDetails").textContent = JSON.stringify(result, null, 2);
    const review = n("evolutionCandidateReview"); review.replaceChildren();
    const candidateId = typeof result.candidate_id === "string" ? result.candidate_id : "";
    if (candidateId) {
      const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button";
      button.textContent = "Examiner le correctif proposé";
      button.addEventListener("click", () => {
        document.querySelector('[data-view-target="developerView"]').click();
        window.dispatchEvent(new CustomEvent("devkit:open-candidate", {detail: {candidateId}}));
      });
      review.append(button);
    }
  }
  function busy(value) { running = value; n("evolutionRun").disabled = value; n("evolutionDemo").disabled = value; }
  function resumeActiveEvolution(base) {
    const active = (base.active_jobs || []).find((job) =>
      job.kind === "evolution" && ["queued", "running"].includes(job.status)
    );
    if (!active) {
      if (activeJobId) {
        clearTimeout(pollTimer);
        activeJobId = null;
        busy(false);
      }
      return;
    }
    if (activeJobId === active.job_id) return;
    clearTimeout(pollTimer);
    activeJobId = active.job_id;
    busy(true);
    show(active.message || "Reprise du cycle de développement en cours…");
    void poll(active.job_id);
  }
  async function refresh() {
    try {
      const base = await request("/status"); token = base.workshop_token;
      const data = await request("/evolution");
      resumeActiveEvolution(base);
      const settings = data.settings || {}, provider = data.provider || {}, dashboard = data.dashboard || {}, metrics = dashboard.metrics || {};
      n("evolutionState").textContent = running ? "Cycle en cours" : provider.configured ? "Configuré · disponibilité à vérifier" : "Configuration nécessaire";
      n("evolutionProvider").textContent = `${provider.provider_id || settings.provider} · ${provider.model_id || settings.model} · ${provider.reason || "Quota non communiqué."}`;
      n("evolutionProviderChoice").value = settings.provider; n("evolutionModel").value = settings.model; n("evolutionRemote").checked = settings.allow_remote; n("evolutionFree").checked = settings.gemini_free_project_confirmed;
      n("evolutionMode").value = data.mode || "automatic";
      n("evolutionRequests").textContent = metrics.requests || 0;
      const tokens = ((data.usage || {}).all_time || {}).total_tokens || {};
      n("evolutionTokens").textContent = tokens.measured_sum == null ? "Non communiqué" : `${tokens.measured_sum} déclarés`;
      n("evolutionPending").textContent = (dashboard.tasks_by_status || {}).needs_review || 0;
      if (data.latest_demo) n("evolutionActivity").textContent = `Dernière démonstration : ${data.latest_demo.status} · ${data.latest_demo.reason || "résultat enregistré"}`;
      const options = n("evolutionFiles"), selected = new Set([...options.selectedOptions].map((o) => o.value)); options.replaceChildren();
      for (const file of base.source_files || []) { const option = document.createElement("option"); option.value = file.path; option.textContent = file.path; option.selected = selected.has(file.path); options.append(option); }
      n("evolutionBacklog").replaceChildren();
      for (const task of data.tasks || []) {
        const row = document.createElement("p"); row.textContent = `${task.title} · ${task.status}`;
        if (["queued", "waiting_provider", "failed", "cancelled"].includes(task.status)) { const button = document.createElement("button"); button.className = "text-button"; button.textContent = "Lancer / reprendre"; button.addEventListener("click", () => start(false, task.task_id)); row.append(button); }
        n("evolutionBacklog").append(row);
      }
      n("evolutionHistory").replaceChildren();
      for (const run of data.runs || []) { const button = document.createElement("button"); button.className = "text-button"; button.textContent = `${run.created_at} · ${run.model} · ${run.status}`; button.addEventListener("click", async () => { try { const result = await request(`/evolution/runs/${encodeURIComponent(run.run_id)}`); renderRunResult(result); } catch (error) { show(error.message); } }); n("evolutionHistory").append(button); }
      n("evolutionResources").textContent = JSON.stringify({catalogue: data.catalogue, usage: data.usage, independent_review: "En attente : aucun second modèle automatiquement invoqué", scheduling: false, automatic_deployment: false}, null, 2);
    } catch (error) { show(error.message); }
  }
  async function poll(id) {
    try {
      const job = await request(`/jobs/${encodeURIComponent(id)}`); show(job.message);
      if (["completed", "failed"].includes(job.status)) {
        activeJobId = null; busy(false); clearTimeout(pollTimer);
        const result = job.report || {}; renderRunResult(result);
        n("evolutionActivity").textContent = `${result.demo ? "Démonstration isolée" : "Cycle"} · ${result.status || job.status} · ${result.reason || job.message}`;
        await refresh(); return;
      }
      pollTimer = setTimeout(() => poll(id), 1200);
    } catch (error) { activeJobId = null; busy(false); show(error.message); }
  }
  async function start(demo, taskId = null) {
    if (running) return;
    try {
      if (!token) await refresh();
      if (running) return;
      busy(true);
      const job = await request("/evolution/run", {task_id: taskId, demo, max_requests: 2, max_attempts: 2});
      activeJobId = job.job_id;
      poll(job.job_id);
    }
    catch (error) { activeJobId = null; busy(false); show(error.message); }
  }
  document.querySelector('[data-view-target="developerView"]').addEventListener("click", refresh);
  n("evolutionRun").addEventListener("click", () => start(false)); n("evolutionDemo").addEventListener("click", () => start(true));
  n("evolutionStop").addEventListener("click", async () => { try { show((await request("/evolution/stop", {})).message); } catch (error) { show(error.message); } });
  n("evolutionSettings").addEventListener("submit", async (event) => {
    event.preventDefault(); try { await request("/evolution/settings", {provider: n("evolutionProviderChoice").value, model: n("evolutionModel").value, mode: n("evolutionMode").value, allow_remote: n("evolutionRemote").checked, gemini_free_project_confirmed: n("evolutionFree").checked}); show("Réglages enregistrés, aucune génération déclenchée."); await refresh(); } catch (error) { show(error.message); }
  });
  n("evolutionRefreshModels").addEventListener("click", async () => { try { await request("/evolution/catalogue/refresh", {}); show("Catalogue actualisé par requête de métadonnées. Aucun modèle génératif appelé."); await refresh(); } catch (error) { show(error.message); } });
  n("evolutionTaskForm").addEventListener("submit", async (event) => {
    event.preventDefault(); try { await request("/evolution/tasks", {title: n("evolutionTaskTitle").value, description: n("evolutionTaskDescription").value, acceptance: n("evolutionAcceptance").value, selected_files: [...n("evolutionFiles").selectedOptions].map((o) => o.value)}); show("Tâche enregistrée ; lance un cycle pour la traiter."); await refresh(); } catch (error) { show(error.message); }
  });
})();
