"use strict";

(() => {
  const node = (id) => document.getElementById(id);
  const ui = {
    status: node("developerStatus"), check: node("developerCheck"), export: node("developerExport"), report: node("developerReport"), downloads: node("developerDownloads"),
    issue: node("developerIssueForm"), title: node("developerIssueTitle"), description: node("developerIssueDescription"), errors: node("developerIssueErrors"), files: node("developerIssueFiles"),
    patchForm: node("developerPatchForm"), format: node("developerPatchFormat"), upload: node("developerPatchUpload"), patch: node("developerPatchText"), diff: node("developerDiff"), validate: node("developerValidate"), apply: node("developerApply"), rollback: node("developerRollback"), patchStatus: node("developerPatchStatus"), history: node("developerHistory"),
  };
  let token = null;
  let candidateId = null;
  let transactionId = null;
  let busy = false;
  let pollTimer = null;

  async function request(path, data) {
    const response = await fetch(`/api/devkit${path}`, data === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json", "X-Workshop-Token": token || "" }, body: JSON.stringify(data),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "L’action de maintenance n’a pas abouti.");
    return result;
  }

  function setBusy(value) {
    busy = value;
    ui.check.disabled = value;
    ui.validate.disabled = value || !candidateId;
    ui.patchForm.querySelector("button").disabled = value;
    if (value) ui.apply.disabled = true;
  }

  function renderReport(report, current = true) {
    ui.report.replaceChildren();
    if (!report) { ui.report.textContent = "Aucun diagnostic enregistré. Lance la première vérification."; return; }
    const summary = document.createElement("p");
    summary.className = "developer-report-summary";
    summary.textContent = `Résultat : ${report.status} · ${report.created_at || "date non renseignée"}${current ? "" : " · code modifié depuis ce diagnostic"}`;
    ui.report.append(summary);
    for (const check of report.checks || []) {
      const details = document.createElement("details");
      const title = document.createElement("summary"); title.textContent = `${check.name} · ${check.status}`;
      const output = document.createElement("pre"); output.textContent = check.output || "Aucun détail supplémentaire.";
      details.append(title, output); ui.report.append(details);
    }
  }

  async function openCandidate(requestedId) {
    if (busy || typeof requestedId !== "string" || !requestedId) return;
    try {
      if (!token) { const status = await request("/status"); token = status.workshop_token; }
      const preview = await request(`/candidates/${encodeURIComponent(requestedId)}`);
      candidateId = preview.candidate_id || requestedId;
      ui.diff.hidden = false; ui.diff.textContent = preview.diff;
      ui.validate.disabled = false; ui.apply.disabled = preview.status !== "validated";
      ui.patchStatus.textContent = preview.validated ? "Correctif validé précédemment. L’application recontrôle son empreinte et les conflits." : "Correctif conservé : lance sa validation avant application.";
      ui.diff.scrollIntoView({behavior: "smooth", block: "center"});
    } catch (error) { ui.patchStatus.textContent = error.message; }
  }

  async function refresh() {
    try {
      const result = await request("/status"); token = result.workshop_token;
      renderReport(result.latest_report, result.diagnostics_current);
      const selected = new Set([...ui.files.selectedOptions].map((option) => option.value));
      ui.files.replaceChildren();
      for (const file of result.source_files || []) {
        const option = document.createElement("option"); option.value = file.path; option.textContent = file.path; option.selected = selected.has(file.path); ui.files.append(option);
      }
      ui.history.replaceChildren();
      for (const candidate of result.candidates || []) {
        if (!["staged", "validated"].includes(candidate.status)) continue;
        const button = document.createElement("button"); button.type = "button"; button.className = "text-button";
        button.textContent = `Relire ${candidate.candidate_id.slice(0, 8)} · ${candidate.status}`;
        button.addEventListener("click", () => openCandidate(candidate.candidate_id)); ui.history.append(button);
      }
      for (const transaction of result.transactions || []) {
        if (transaction.status !== "applied") continue;
        const button = document.createElement("button"); button.type = "button"; button.className = "text-button danger";
        button.textContent = `Restaurer ${transaction.transaction_id.slice(0, 8)}`;
        button.addEventListener("click", () => { transactionId = transaction.transaction_id; ui.rollback.hidden = false; ui.rollback.focus(); ui.patchStatus.textContent = "Sauvegarde sélectionnée. Confirme avec « Restaurer les originaux »."; }); ui.history.append(button);
      }
      ui.status.textContent = "Atelier local prêt. Les exports et diagnostics ne font aucun appel à une IA.";
      if (!busy && result.active_jobs && result.active_jobs.length) {
        const job = result.active_jobs[0]; setBusy(true); poll(job.job_id, job.candidate_id);
      }
    } catch (error) { ui.status.textContent = error.message; }
  }

  function addDownload(artifact) {
    const link = document.createElement("a"); link.href = artifact.download_url; link.download = artifact.filename; link.textContent = `↓ ${artifact.filename}`; link.className = "developer-download"; ui.downloads.prepend(link);
  }

  async function poll(jobId, candidate) {
    try {
      const job = await request(`/jobs/${encodeURIComponent(jobId)}`);
      ui.status.textContent = job.message;
      if (candidate) ui.patchStatus.textContent = job.message;
      if (["completed", "failed"].includes(job.status)) {
        setBusy(false); clearTimeout(pollTimer); renderReport(job.report);
        if (candidate) {
          candidateId = candidate;
          ui.validate.disabled = false;
          const preview = await request(`/candidates/${encodeURIComponent(candidate)}`);
          const validated = preview.status === "validated" || preview.validation_status === "passed";
          ui.apply.disabled = !(job.report && job.report.status === "passed" && validated);
          ui.patchStatus.textContent = ui.apply.disabled ? "Validation incomplète ou échouée. Le code principal reste inchangé." : "Le correctif a passé les tests. Relis l’aperçu puis confirme son application.";
        }
        return;
      }
      pollTimer = setTimeout(() => poll(jobId, candidate), 900);
    } catch (error) { setBusy(false); ui.status.textContent = error.message; ui.patchStatus.textContent = error.message; }
  }

  async function check(candidate = null) {
    if (busy) return;
    setBusy(true); ui.status.textContent = "Préparation des diagnostics…";
    try { const job = await request("/diagnostics", { candidate_id: candidate }); poll(job.job_id, candidate); }
    catch (error) { setBusy(false); ui.status.textContent = error.message; }
  }

  document.querySelector('[data-view-target="developerView"]').addEventListener("click", refresh);
  window.addEventListener("devkit:open-candidate", (event) => openCandidate(event.detail?.candidateId));
  ui.check.addEventListener("click", () => check());
  ui.validate.addEventListener("click", () => check(candidateId));
  ui.export.addEventListener("click", async () => {
    ui.export.disabled = true;
    try { if (!token) await refresh(); addDownload(await request("/exports", {})); ui.status.textContent = "Archive du code prête à télécharger. Inspecte son contenu avant de la joindre à une conversation."; }
    catch (error) { ui.status.textContent = error.message; }
    finally { ui.export.disabled = false; }
  });
  ui.issue.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      if (!token) await refresh();
      const result = await request("/issues", { title: ui.title.value, description: ui.description.value, errors: ui.errors.value, selected_files: [...ui.files.selectedOptions].map((option) => option.value) });
      addDownload(result); ui.status.textContent = "Demande prête : ISSUE.md explique le problème et le format de réponse attendu.";
    } catch (error) { ui.status.textContent = error.message; }
  });
  ui.upload.addEventListener("change", async () => {
    const file = ui.upload.files[0]; if (!file) return;
    if (file.size > 500000) { ui.patchStatus.textContent = "Le correctif doit faire moins de 500 Ko."; return; }
    ui.patch.value = await file.text();
    if (file.name.endsWith(".json")) ui.format.value = "files";
  });
  ui.patchForm.addEventListener("submit", async (event) => {
    event.preventDefault(); if (busy) return;
    try {
      if (!token) await refresh();
      const filesMode = ui.format.value === "files";
      const result = await request(filesMode ? "/candidates/files" : "/candidates/patch", filesMode ? { files: JSON.parse(ui.patch.value) } : { patch: ui.patch.value });
      candidateId = result.candidate_id; ui.diff.hidden = false; ui.diff.textContent = result.diff || "Aucune modification."; ui.validate.disabled = false; ui.apply.disabled = true;
      ui.patchStatus.textContent = `Copie préparée · ${(result.changed_files || []).length} fichier(s) modifié(s). Le correctif doit maintenant être testé.`;
    } catch (error) { ui.patchStatus.textContent = error.message; }
  });
  ui.apply.addEventListener("click", async () => {
    if (!candidateId || busy || !window.confirm("Appliquer les modifications de cet aperçu après validation ? Les originaux seront sauvegardés. Redémarre ensuite Côme AI pour charger le nouveau code.")) return;
    ui.apply.disabled = true;
    try {
      const result = await request(`/candidates/${encodeURIComponent(candidateId)}/apply`, { confirmed: true });
      transactionId = result.transaction_id; ui.rollback.hidden = !transactionId; ui.validate.disabled = true;
      ui.patchStatus.textContent = "Correctif appliqué et originaux sauvegardés. Redémarre Côme AI pour utiliser la nouvelle version.";
      refresh();
    } catch (error) { ui.patchStatus.textContent = error.message; }
  });
  ui.rollback.addEventListener("click", async () => {
    if (!transactionId || busy || !window.confirm("Restaurer les originaux sauvegardés ? Toute nouvelle édition des fichiers concernés empêchera l’écrasement.")) return;
    try {
      await request(`/transactions/${encodeURIComponent(transactionId)}/rollback`, { confirmed: true });
      ui.rollback.hidden = true; transactionId = null; ui.patchStatus.textContent = "Originaux restaurés. Redémarre Côme AI pour recharger le code.";
      refresh();
    } catch (error) { ui.patchStatus.textContent = error.message; }
  });
})();
