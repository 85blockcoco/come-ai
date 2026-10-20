"use strict";

const state = {
  files: [],
  selectedFileId: null,
  selectedProjectId: null,
  taskId: null,
  taskTimer: null,
  taskBusy: false,
  chatBusy: false,
  chatMode: "offline",
  chatHistory: [],
  memoryIndexTaskId: null,
  memoryIndexTimer: null,
  memoryIndexBusy: false,
  memoryAvailable: false,
};

const $ = (id) => document.getElementById(id);
const elements = {
  localStatus: $("localStatus"), providerDetails: $("providerDetails"),
  metricFiles: $("metricFiles"), metricMemory: $("metricMemory"), metricTasks: $("metricTasks"),
  fileInput: $("fileInput"), dropZone: $("dropZone"), refreshFiles: $("refreshFiles"), uploadStatus: $("uploadStatus"), fileList: $("fileList"), emptyFiles: $("emptyFiles"),
  selectedFileBadge: $("selectedFileBadge"), chatLog: $("chatLog"), form: $("orchestratorForm"), message: $("messageInput"), allowWrite: $("allowWrite"), send: $("sendButton"), requestStatus: $("requestStatus"),
  chatProvider: $("chatProvider"), chatModel: $("chatModel"), chatModeDescription: $("chatModeDescription"), chatMetrics: $("chatMetrics"), chatModelUsed: $("chatModelUsed"), chatProviderUsed: $("chatProviderUsed"), chatLatency: $("chatLatency"), chatTokens: $("chatTokens"), chatRouteReason: $("chatRouteReason"),
  taskState: $("taskState"), planList: $("planList"), cancelTask: $("cancelTask"), citationsSection: $("citationsSection"), citationList: $("citationList"),
  outputList: $("outputList"), emptyOutputs: $("emptyOutputs"), refreshOutputs: $("refreshOutputs"),
  documentsSelectedName: $("documentsSelectedName"), documentsSelectedMeta: $("documentsSelectedMeta"),
  projectForm: $("projectForm"), projectName: $("projectName"), projectList: $("projectList"), memoryHealth: $("memoryHealth"), memorySelectedFile: $("memorySelectedFile"), indexSelected: $("indexSelected"), cancelMemoryIndex: $("cancelMemoryIndex"), memorySearchForm: $("memorySearchForm"), memorySearchInput: $("memorySearchInput"), memoryActionStatus: $("memoryActionStatus"), memoryResults: $("memoryResults"), refreshMemory: $("refreshMemory"), sourceList: $("sourceList"), emptySources: $("emptySources"),
  storageLibrarySize: $("storageLibrarySize"), storageFiles: $("storageFiles"), storageFreeSpace: $("storageFreeSpace"), storageIndexing: $("storageIndexing"), storageLocation: $("storageLocation"), storageIndexSize: $("storageIndexSize"), storageBackupStatus: $("storageBackupStatus"), storageQueueStatus: $("storageQueueStatus"), storageLargestFiles: $("storageLargestFiles"), emptyLargestFiles: $("emptyLargestFiles"), refreshStorage: $("refreshStorage"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const suffix = body.error_id ? ` (référence ${body.error_id})` : "";
    throw new Error((body.detail || "L’action locale n’a pas pu aboutir.") + suffix);
  }
  return body;
}

function selectedFile() { return state.files.find((file) => file.file_id === state.selectedFileId) || null; }
function formatSize(value) { const kb = Number(value || 0); return kb >= 1024 ? `${(kb / 1024).toFixed(1)} Mo` : `${kb.toFixed(1)} Ko`; }
function formatBytes(value) { const bytes = Number(value || 0); if (!Number.isFinite(bytes) || bytes <= 0) return "0 o"; const units = ["o", "Ko", "Mo", "Go", "To"]; const step = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1); const amount = bytes / (1024 ** step); return `${amount >= 10 || step === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[step]}`; }
function text(node, value) { node.textContent = value == null ? "" : String(value); }

const viewTargets = new Set(["assistantView", "documentsView", "memoryView", "settingsView", "developerView"]);
const viewLabels = { assistantView: "Assistant", documentsView: "Documents & Finance", memoryView: "Mémoire & stockage", settingsView: "Réglages", developerView: "Atelier Développeur" };
let internalHashChange = false;

function requestedHashView() {
  const requested = window.location.hash.replace(/^#v5\//, "");
  return viewTargets.has(requested) ? requested : "";
}

function activateView(id, updateHash = true) {
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== id; view.classList.toggle("active", view.id === id); });
  document.querySelectorAll(".nav-item[data-view-target]").forEach((button) => { const active = button.dataset.viewTarget === id; button.classList.toggle("active", active); if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); });
  if (id === "memoryView") { refreshMemory(); refreshStorage(); }
  document.title = `${viewLabels[id] || id} — Côme AI V5`;
  if (updateHash && window.location.hash !== `#v5/${id}`) {
    internalHashChange = true;
    window.location.hash = `v5/${id}`;
  }
}

function addMessage(kind, content, meta = "") {
  const article = document.createElement("article");
  article.className = `message ${kind}-message`;
  const label = document.createElement("p"); label.className = "message-label";
  label.textContent = kind === "user" ? "Toi" : kind === "error" ? "Erreur locale" : "Côme AI";
  const paragraph = document.createElement("p"); paragraph.textContent = content;
  article.append(label, paragraph);
  if (meta) { const note = document.createElement("p"); note.className = "message-label"; note.textContent = meta; article.append(note); }
  elements.chatLog.append(article); elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function renderFiles() {
  elements.fileList.replaceChildren();
  elements.emptyFiles.hidden = state.files.length > 0;
  for (const file of state.files) {
    const button = document.createElement("button"); button.type = "button"; button.className = `file-item${file.file_id === state.selectedFileId ? " selected" : ""}`; button.setAttribute("role", "listitem");
    const type = document.createElement("span"); type.className = "file-type"; type.textContent = String(file.type || "file").slice(0, 4).toUpperCase();
    const details = document.createElement("span"); details.className = "file-details";
    const name = document.createElement("strong"); name.textContent = file.name; name.title = file.name;
    const info = document.createElement("small"); info.textContent = `${formatSize(file.size_kb)} · ${file.modified}`;
    details.append(name, info); button.append(type, details); button.addEventListener("click", () => { state.selectedFileId = file.file_id; renderFiles(); }); elements.fileList.append(button);
  }
  if (!selectedFile()) state.selectedFileId = null;
  updateSelectedFile();
}

function updateSelectedFile() {
  const file = selectedFile();
  elements.selectedFileBadge.hidden = !file; if (file) text(elements.selectedFileBadge, file.name);
  text(elements.documentsSelectedName, file ? file.name : "Aucun document sélectionné");
  text(elements.documentsSelectedMeta, file ? `${String(file.type || "fichier").toUpperCase()} · ${formatSize(file.size_kb)} · importé dans l’espace contrôlé` : "Retourne dans Assistant pour importer ou sélectionner un fichier.");
  text(elements.memorySelectedFile, file ? file.name : "Aucun document sélectionné");
  elements.indexSelected.disabled = !file || !state.memoryAvailable || state.memoryIndexBusy;
  elements.cancelMemoryIndex.hidden = !state.memoryIndexBusy;
  elements.metricFiles.textContent = state.files.length;
}

async function refreshFiles() {
  try { const data = await api("/api/files"); state.files = data.files || []; renderFiles(); }
  catch (error) { addMessage("error", error.message); }
}

function renderOutputs(outputs) {
  elements.outputList.replaceChildren(); elements.emptyOutputs.hidden = outputs.length > 0;
  for (const output of outputs) {
    const row = document.createElement("div"); row.className = "output-item";
    const icon = document.createElement("span"); icon.textContent = "↓";
    const link = document.createElement("a"); link.href = `/api/outputs/${encodeURIComponent(output.name)}`; link.download = output.name; link.textContent = output.name; link.title = "Télécharger ce rapport";
    const meta = document.createElement("small"); meta.textContent = `${formatSize(output.size_kb)} · ${output.created_at}`;
    row.append(icon, link, meta); elements.outputList.append(row);
  }
}
async function refreshOutputs() { try { const data = await api("/api/outputs"); renderOutputs(data.outputs || []); } catch (error) { addMessage("error", error.message); } }

async function loadOverview() {
  try {
    const data = await api("/api/v5/overview");
    state.memoryAvailable = Boolean(data.memory && data.memory.available);
    elements.localStatus.className = "status-pill ready"; elements.localStatus.textContent = "Interface locale · hybride";
    if (data.memory) { elements.memoryHealth.textContent = data.memory.available ? `${data.memory.source_count || 0} source(s), ${data.memory.chunk_count || 0} extrait(s), index FTS5 local.` : "La mémoire locale n’est pas disponible : consulte les détails dans les réglages."; elements.metricMemory.textContent = data.memory.source_count || 0; }
    if (data.task_queue) elements.metricTasks.textContent = data.task_queue.active_count || 0;
  } catch (error) {
    elements.localStatus.className = "status-pill warn"; elements.localStatus.textContent = "État local indisponible"; text(elements.providerDetails, error.message);
  }
}

async function loadIntelligence() {
  try {
    const data = await api("/api/v5/intelligence");
    const providers = data.providers || {};
    const labels = Object.entries(providers).map(([name, info]) => `${name} : ${info.available === true || info.availability === "available" ? "disponible" : info.availability === "unavailable" ? "indisponible" : info.configured ? "configuré, accès à tester" : "non configuré"}`);
    text(elements.providerDetails, labels.length ? labels.join(" · ") : "Les accès sont vérifiés au lancement de la demande. Aucune génération au chargement de l’interface.");
  } catch (error) { text(elements.providerDetails, error.message); }
}

async function uploadFiles(files) {
  if (!files.length) return;
  text(elements.uploadStatus, `Import de ${files.length} fichier(s)…`);
  const form = new FormData(); files.forEach((file) => form.append("files", file, file.name));
  try {
    const data = await api("/api/files/upload", { method: "POST", body: form });
    const successes = (data.results || []).filter((item) => item.status === "importé"); const failures = (data.results || []).filter((item) => item.error);
    state.files = data.files || []; if (successes.length) state.selectedFileId = successes[successes.length - 1].file_id;
    renderFiles(); text(elements.uploadStatus, failures.length ? `${successes.length} importé(s), ${failures.length} erreur(s).` : `${successes.length} fichier(s) ajouté(s) à l’espace contrôlé.`);
    failures.forEach((item) => addMessage("error", `${item.name || "Fichier"} : ${item.error}`));
  } catch (error) { text(elements.uploadStatus, "Import interrompu."); addMessage("error", error.message); }
  finally { elements.fileInput.value = ""; }
}

function setTaskBusy(busy) {
  state.taskBusy = busy; updateComposerBusy(); elements.cancelTask.hidden = !busy;
  text(elements.requestStatus, busy ? "Exécution locale en cours. Tu peux annuler entre deux étapes." : "L’historique de cette conversation reste dans cet onglet. Les créations de rapports nécessitent ton accord.");
}

function updateComposerBusy() {
  const busy = state.taskBusy || state.chatBusy;
  elements.send.disabled = busy;
  elements.send.textContent = state.chatBusy ? "Réponse en cours…" : state.taskBusy ? "Plan en cours…" : "Envoyer →";
  elements.chatProvider.disabled = busy; elements.chatModel.disabled = busy;
  document.querySelectorAll("[data-chat-mode]").forEach((button) => { button.disabled = busy; });
}

function selectChatMode(mode) {
  if (state.chatBusy || state.taskBusy) return;
  state.chatMode = mode;
  document.querySelectorAll("[data-chat-mode]").forEach((button) => {
    const selected = button.dataset.chatMode === mode;
    button.classList.toggle("active", selected); button.setAttribute("aria-pressed", String(selected));
  });
  const descriptions = {
    offline: "Qwen et outils locaux uniquement. Aucun fournisseur cloud en mode Hors ligne.",
    automatic: "Choix adapté à la demande, avec les outils locaux et les fournisseurs gratuits disponibles.",
    performance: "Priorité à la qualité accessible gratuitement. Le routage ne garantit pas la supériorité d’un modèle sans mesure.",
  };
  text(elements.chatModeDescription, descriptions[mode]);
}

function renderChatResult(result) {
  const usage = result.usage || {};
  const measuredTokens = usage.total_tokens != null ? usage.total_tokens : (usage.input_tokens != null && usage.output_tokens != null ? Number(usage.input_tokens) + Number(usage.output_tokens) : null);
  const latency = Number(result.latency_seconds);
  elements.chatMetrics.hidden = false;
  text(elements.chatModelUsed, result.model || "Aucun modèle — outil local");
  text(elements.chatProviderUsed, result.provider || "Outils locaux");
  text(elements.chatLatency, Number.isFinite(latency) && result.latency_seconds != null ? `${latency.toFixed(1)} s` : "Non mesuré");
  text(elements.chatTokens, measuredTokens == null ? "Inconnus" : measuredTokens);
  text(elements.chatRouteReason, result.route_reason || "Non renseigné");
  const events = result.tool_events || [];
  const plan = events.map((event, index) => ({ step_id: event.step_id || String(index), label: event.label || event.tool || "Outil local", requires_confirmation: false }));
  renderPlan(plan, events.map((event, index) => ({ ...event, step_id: event.step_id || String(index), status: event.status || "done", message: event.message || "Exécuté localement." })));
  renderCitations(result.citations || []);
  elements.taskState.className = "task-state completed";
  text(elements.taskState, result.remote_model_used ? "Réponse du fournisseur gratuit configuré, avec outils contrôlés." : "Réponse locale · aucun fournisseur cloud utilisé.");
}

async function startChat(message) {
  if (state.chatBusy || state.taskBusy) return;
  const file = selectedFile();
  addMessage("user", message, file ? `Document sélectionné : ${file.name}` : "");
  state.chatBusy = true; updateComposerBusy();
  elements.chatMetrics.hidden = true; elements.planList.replaceChildren(); renderCitations([]);
  text(elements.requestStatus, "Préparation et réponse en cours. Une génération locale sur Intel peut prendre du temps.");
  elements.taskState.className = "task-state running"; text(elements.taskState, "Traitement de la demande…");
  try {
    const result = await api("/api/v5/chat", { method: "POST", body: JSON.stringify({
      message, selected_file_ids: file ? [file.file_id] : [], history: state.chatHistory.slice(-10),
      mode: state.chatMode, provider: elements.chatProvider.value, model: elements.chatModel.value.trim() || "auto",
      allow_write: elements.allowWrite.checked, memory_project_id: state.selectedProjectId,
    }) });
    const answer = result.answer || "La demande est terminée sans réponse textuelle.";
    addMessage("assistant", answer, [result.provider, result.model].filter(Boolean).join(" · "));
    state.chatHistory.push({ role: "user", content: message.slice(0, 12000) }, { role: "assistant", content: answer.slice(0, 12000) });
    state.chatHistory = state.chatHistory.slice(-10);
    renderChatResult(result); refreshOutputs();
  } catch (error) {
    elements.taskState.className = "task-state error"; text(elements.taskState, error.message); addMessage("error", error.message);
  } finally {
    state.chatBusy = false; updateComposerBusy();
    text(elements.requestStatus, "L’historique de cette conversation reste dans cet onglet. Les créations de rapports nécessitent ton accord.");
  }
}

function setMemoryIndexBusy(busy) {
  state.memoryIndexBusy = busy;
  elements.cancelMemoryIndex.hidden = !busy;
  updateSelectedFile();
}

function renderPlan(plan = [], events = []) {
  const eventsById = new Map(events.map((event) => [event.step_id, event])); elements.planList.replaceChildren();
  for (const step of plan) {
    const event = eventsById.get(step.step_id); const row = document.createElement("li"); row.className = event ? event.status : "pending";
    const title = document.createElement("strong"); title.textContent = step.label;
    const detail = document.createElement("small"); detail.textContent = event ? event.message : step.requires_confirmation ? "Confirmation nécessaire avant écriture." : "En attente.";
    row.append(title, detail); elements.planList.append(row);
  }
}

function renderCitations(citations = []) {
  elements.citationList.replaceChildren(); elements.citationsSection.hidden = !citations.length;
  for (const citation of citations) {
    const card = document.createElement("div"); card.className = "citation-card";
    const title = document.createElement("strong"); title.textContent = citation.citation || citation.source_title || "Source locale";
    const excerpt = document.createElement("p"); excerpt.textContent = citation.excerpt || "Passage retrouvé dans ta mémoire.";
    card.append(title, excerpt); elements.citationList.append(card);
  }
}

function renderTask(task) {
  const status = task.status || "queued"; const progress = Number(task.progress || 0); const message = task.message || "Tâche locale planifiée.";
  elements.taskState.className = `task-state ${status}`; elements.taskState.textContent = `${status === "running" ? `Exécution ${Math.round(progress * 100)} % · ` : ""}${message}`;
  const result = task.result || {}; renderPlan(result.plan || task.plan || [], result.events || task.events || []); renderCitations(result.citations || []);
  if (status === "completed") { addMessage("assistant", result.answer || "Plan local terminé.", "Mode local orchestré · aucun modèle externe"); refreshOutputs(); }
  if (status === "failed") addMessage("error", task.error || "La tâche locale a échoué.");
  if (status === "cancelled") addMessage("error", "La tâche a été annulée avant sa fin.");
}

async function pollTask() {
  if (!state.taskId) return;
  try {
    const task = await api(`/api/v5/tasks/${encodeURIComponent(state.taskId)}`); renderTask(task);
    if (["completed", "failed", "cancelled"].includes(task.status)) { state.taskId = null; clearTimeout(state.taskTimer); setTaskBusy(false); loadOverview(); return; }
    // Onglet en arrière-plan : ralentir le polling au lieu de sonner toutes les 650 ms.
    state.taskTimer = setTimeout(pollTask, document.hidden ? 2500 : 650);
  } catch (error) { state.taskId = null; setTaskBusy(false); addMessage("error", error.message); }
}

async function startTask(message, { allowWrite = elements.allowWrite.checked } = {}) {
  if (state.taskBusy || state.chatBusy) return;
  const file = selectedFile(); addMessage("user", message, file ? `Document sélectionné : ${file.name}` : "Recherche dans la mémoire locale");
  setTaskBusy(true); elements.planList.replaceChildren(); renderCitations([]); elements.taskState.className = "task-state running"; elements.taskState.textContent = "Préparation d’un plan local…";
  elements.chatMetrics.hidden = true;
  try {
    const task = await api("/api/v5/tasks", { method: "POST", body: JSON.stringify({ message, selected_file_ids: file ? [file.file_id] : [], allow_write: allowWrite, memory_project_id: state.selectedProjectId }) });
    state.taskId = task.task_id; renderTask(task); pollTask();
  } catch (error) { setTaskBusy(false); elements.taskState.className = "task-state error"; elements.taskState.textContent = error.message; addMessage("error", error.message); }
}

async function indexSelected() {
  if (state.memoryIndexBusy) return;
  const file = selectedFile(); if (!file) { text(elements.memoryActionStatus, "Sélectionne d’abord un document dans l’espace de travail."); return; }
  text(elements.memoryActionStatus, "Préparation de l’indexation locale persistante…"); setMemoryIndexBusy(true);
  try {
    const task = await api("/api/v5/memory/index-tasks", { method: "POST", body: JSON.stringify({ file_id: file.file_id, project_id: state.selectedProjectId }) });
    state.memoryIndexTaskId = task.task_id;
    renderMemoryIndexTask(task);
    pollMemoryIndexTask();
  } catch (error) { text(elements.memoryActionStatus, error.message); setMemoryIndexBusy(false); }
}

function renderMemoryIndexTask(task) {
  const status = task.status || "queued";
  const percent = Number(task.progress_percent || Math.round(Number(task.progress || 0) * 100));
  const message = task.message || "Tâche d’indexation locale planifiée.";
  if (status === "queued") text(elements.memoryActionStatus, `Indexation en attente · ${message}`);
  else if (status === "running" || status === "cancelling") text(elements.memoryActionStatus, `Indexation locale ${percent}% · ${message}`);
  else if (status === "completed") text(elements.memoryActionStatus, (task.result || {}).message || "Document indexé dans la mémoire locale.");
  else if (status === "cancelled") text(elements.memoryActionStatus, "Indexation annulée entre deux étapes sûres.");
  else text(elements.memoryActionStatus, task.error || "L’indexation locale n’a pas abouti.");
}

async function pollMemoryIndexTask() {
  if (!state.memoryIndexTaskId) return;
  try {
    const task = await api(`/api/v5/tasks/${encodeURIComponent(state.memoryIndexTaskId)}`);
    renderMemoryIndexTask(task);
    if (["completed", "failed", "cancelled"].includes(task.status)) {
      state.memoryIndexTaskId = null; clearTimeout(state.memoryIndexTimer); setMemoryIndexBusy(false);
      await Promise.all([refreshMemory(), loadOverview()]);
      return;
    }
    // Même politique de ralentissement en arrière-plan.
    state.memoryIndexTimer = setTimeout(pollMemoryIndexTask, document.hidden ? 2500 : 650);
  } catch (error) {
    state.memoryIndexTaskId = null; setMemoryIndexBusy(false); text(elements.memoryActionStatus, error.message);
  }
}

function renderProjects(projects) {
  elements.projectList.replaceChildren();
  const all = document.createElement("button"); all.type = "button"; all.className = `project-button${state.selectedProjectId === null ? " selected" : ""}`; all.textContent = "Toutes les sources"; all.addEventListener("click", () => { state.selectedProjectId = null; renderProjects(projects); }); elements.projectList.append(all);
  for (const project of projects) { const button = document.createElement("button"); button.type = "button"; button.className = `project-button${project.project_id === state.selectedProjectId ? " selected" : ""}`; button.textContent = project.name; button.addEventListener("click", () => { state.selectedProjectId = project.project_id; renderProjects(projects); }); elements.projectList.append(button); }
}

function renderSources(sources) {
  elements.sourceList.replaceChildren(); elements.emptySources.hidden = sources.length > 0;
  for (const source of sources) { const row = document.createElement("div"); row.className = "source-row"; const content = document.createElement("div"); const name = document.createElement("strong"); name.textContent = source.title || "Document"; const meta = document.createElement("small"); meta.textContent = `${source.chunk_count || 0} extrait(s) · ${source.project_name || "sans projet"} · ${source.imported_at || ""}`; content.append(name, meta); const tag = document.createElement("span"); tag.textContent = source.kind || "document"; row.append(content, tag); elements.sourceList.append(row); }
}

function renderMemoryResults(results) {
  elements.memoryResults.replaceChildren();
  if (!results.length) { const none = document.createElement("p"); none.className = "empty-state compact"; none.textContent = "Aucun passage trouvé."; elements.memoryResults.append(none); return; }
  for (const result of results) {
    const card = document.createElement("article"); card.className = "memory-result";
    const label = result.citation || result.source_title || "Source locale";
    const source = document.createElement("strong"); source.textContent = label;
    const excerpt = document.createElement("p"); excerpt.textContent = result.excerpt || "";
    const copyButton = document.createElement("button"); copyButton.type = "button"; copyButton.className = "secondary-button";
    copyButton.textContent = "Copier le passage";
    copyButton.setAttribute("aria-label", `Copier le passage de « ${label} »`);
    const passageText = `${label}\n${result.excerpt || ""}`;
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(passageText);
        copyButton.textContent = "Copié ✓";
      } catch (_error) {
        text(elements.memoryActionStatus, "La copie automatique a été refusée par le navigateur : sélectionne le texte à la main.");
      } finally {
        setTimeout(() => { copyButton.textContent = "Copier le passage"; }, 1500);
      }
    });
    card.append(source, excerpt, copyButton); elements.memoryResults.append(card);
  }
}

function renderStorage(data) {
  if (!data || !data.available) {
    const detail = (data && data.detail) || "Les informations de stockage local ne sont pas disponibles.";
    text(elements.storageLocation, detail);
    [elements.storageLibrarySize, elements.storageFiles, elements.storageFreeSpace, elements.storageIndexing, elements.storageIndexSize, elements.storageBackupStatus, elements.storageQueueStatus].forEach((node) => text(node, "—"));
    elements.storageLargestFiles.replaceChildren(); elements.emptyLargestFiles.hidden = false;
    return;
  }
  const snapshot = data.storage || {}; const storage = snapshot.storage || {}; const disk = snapshot.disk || {}; const database = snapshot.database || {}; const backups = snapshot.backups || {}; const indexing = data.indexing || {};
  text(elements.storageLibrarySize, formatBytes(storage.total_bytes));
  text(elements.storageFiles, (data.memory || {}).source_count || 0);
  text(elements.storageFreeSpace, disk.free_bytes == null ? "Indisponible" : formatBytes(disk.free_bytes));
  text(elements.storageIndexing, `${indexing.active_count || 0} active`);
  const location = snapshot.location || {};
  const scan = storage.scan || {};
  const inventoryNote = scan.complete ? "inventaire local complet" : "inventaire local partiel";
  const locationKind = location.mode === "default_local" ? "stockage local par défaut" : location.is_external ? "stockage externe configuré" : "stockage local configuré";
  text(elements.storageLocation, `${location.display_path || "Emplacement local configuré"} · ${locationKind} · ${inventoryNote}.`);
  text(elements.storageIndexSize, formatBytes(Number(database.bytes || 0) + Number(database.sidecar_bytes || 0)));
  text(elements.storageBackupStatus, backups.exists ? `${backups.file_count || 0} fichier(s)` : "non configurée");
  text(elements.storageQueueStatus, `${indexing.active_count || 0} active · ${indexing.queued_count || 0} en attente`);
  const largest = Array.isArray(storage.largest_files) ? storage.largest_files : [];
  elements.storageLargestFiles.replaceChildren(); elements.emptyLargestFiles.hidden = largest.length > 0;
  for (const item of largest) {
    const row = document.createElement("div"); row.className = "large-file-row";
    const name = document.createElement("strong"); name.textContent = item.relative_path || "Fichier de mémoire";
    const size = document.createElement("small"); size.textContent = formatBytes(item.size_bytes);
    row.append(name, size); elements.storageLargestFiles.append(row);
  }
}

async function refreshStorage() {
  try { renderStorage(await api("/api/v5/memory/storage")); }
  catch (error) { renderStorage({ available: false, detail: error.message }); }
}

async function refreshMemory(includeStorage = true) {
  try {
    // L'inventaire disque (/memory/storage) est coûteux : ne le lancer que
    // pour la vue Mémoire, pas au démarrage de l'Assistant.
    const calls = [api("/api/v5/memory/health"), api("/api/v5/memory/projects"), api("/api/v5/memory/sources")];
    if (includeStorage) calls.push(api("/api/v5/memory/storage"));
    const [health, projectsData, sourcesData, storageData] = await Promise.all(calls);
    state.memoryAvailable = Boolean(health.available); text(elements.memoryHealth, health.available ? `${health.source_count || 0} source(s), ${health.chunk_count || 0} extrait(s), index FTS5 local.` : health.detail || "Mémoire indisponible."); elements.metricMemory.textContent = health.source_count || 0;
    renderProjects(projectsData.projects || []); renderSources(sourcesData.sources || []);
    if (storageData) renderStorage(storageData);
    updateSelectedFile();
  } catch (error) { text(elements.memoryHealth, error.message); }
}

document.querySelectorAll(".nav-item[data-view-target]").forEach((button) => button.addEventListener("click", () => activateView(button.dataset.viewTarget)));
document.querySelectorAll(".suggestion").forEach((button) => button.addEventListener("click", () => { elements.message.value = button.dataset.prompt || ""; elements.message.focus(); }));
document.querySelectorAll(".doc-action").forEach((button) => button.addEventListener("click", () => { const file = selectedFile(); if (!file) { activateView("assistantView"); addMessage("error", "Sélectionne un document avant de lancer cette action."); return; } const action = button.dataset.action; if (action === "inspect") startTask("Inspecte complètement le fichier sélectionné."); if (action === "analyze") startTask("Analyse financière en profondeur le fichier sélectionné."); if (action === "report") { activateView("assistantView"); elements.message.value = "Analyse le fichier sélectionné et crée un rapport."; elements.allowWrite.focus(); } }));
elements.refreshFiles.addEventListener("click", refreshFiles); elements.refreshOutputs.addEventListener("click", refreshOutputs); elements.fileInput.addEventListener("change", (event) => uploadFiles([...event.target.files]));
["dragenter", "dragover"].forEach((eventName) => elements.dropZone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropZone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((eventName) => elements.dropZone.addEventListener(eventName, (event) => { event.preventDefault(); elements.dropZone.classList.remove("dragover"); }));
elements.dropZone.addEventListener("drop", (event) => uploadFiles([...event.dataTransfer.files]));
elements.form.addEventListener("submit", (event) => { event.preventDefault(); const message = elements.message.value.trim(); if (!message || state.chatBusy || state.taskBusy) return; elements.message.value = ""; startChat(message); });
document.querySelectorAll("[data-chat-mode]").forEach((button) => button.addEventListener("click", () => selectChatMode(button.dataset.chatMode)));
elements.message.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); elements.form.requestSubmit(); } });
elements.cancelTask.addEventListener("click", async () => { if (!state.taskId) return; try { await api(`/api/v5/tasks/${encodeURIComponent(state.taskId)}/cancel`, { method: "POST" }); text(elements.taskState, "Annulation demandée : l’étape en cours se termine de façon sûre."); } catch (error) { addMessage("error", error.message); } });
elements.indexSelected.addEventListener("click", indexSelected);
elements.cancelMemoryIndex.addEventListener("click", async () => { if (!state.memoryIndexTaskId) return; try { await api(`/api/v5/tasks/${encodeURIComponent(state.memoryIndexTaskId)}/cancel`, { method: "POST" }); text(elements.memoryActionStatus, "Annulation demandée : l’étape locale en cours se termine de façon sûre."); } catch (error) { text(elements.memoryActionStatus, error.message); } });
elements.projectForm.addEventListener("submit", async (event) => { event.preventDefault(); const name = elements.projectName.value.trim(); if (!name) return; try { const result = await api("/api/v5/memory/projects", { method: "POST", body: JSON.stringify({ name }) }); elements.projectName.value = ""; state.selectedProjectId = result.project.project_id; await refreshMemory(); } catch (error) { text(elements.memoryActionStatus, error.message); } });
elements.memorySearchForm.addEventListener("submit", async (event) => { event.preventDefault(); const query = elements.memorySearchInput.value.trim(); if (!query) return; text(elements.memoryActionStatus, "Recherche locale en cours…"); try { const params = new URLSearchParams({ q: query }); if (state.selectedProjectId) params.set("project_id", state.selectedProjectId); const data = await api(`/api/v5/memory/search?${params}`); renderMemoryResults(data.results || []); text(elements.memoryActionStatus, `${data.count || 0} passage(s) retrouvé(s).${data.note ? ` ${data.note}` : ""}`); } catch (error) { text(elements.memoryActionStatus, error.message); } });
elements.refreshMemory.addEventListener("click", refreshMemory);
elements.refreshStorage.addEventListener("click", refreshStorage);

window.addEventListener("hashchange", () => {
  if (internalHashChange) {
    internalHashChange = false;
    return;
  }
  const requested = requestedHashView();
  if (requested) activateView(requested, false);
});

Promise.all([refreshFiles(), refreshOutputs(), loadOverview(), loadIntelligence(), refreshMemory(false)]).then(() => {
  const requested = requestedHashView();
  if (requested && requested !== "assistantView") activateView(requested, false);
});

// Fenêtre de retour : reprendre le polling immédiatement après la pause d'onglet caché.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (state.taskId) { clearTimeout(state.taskTimer); pollTask(); }
  if (state.memoryIndexTaskId) { clearTimeout(state.memoryIndexTimer); pollMemoryIndexTask(); }
});
