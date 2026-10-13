"use strict";

const state = { files: [], selectedFileId: null, busy: false };

const $ = (selector) => document.querySelector(selector);
const elements = {
  fileInput: $("#file-input"),
  dropZone: $("#drop-zone"),
  fileList: $("#file-list"),
  emptyFiles: $("#empty-files"),
  refreshFiles: $("#refresh-files"),
  uploadStatus: $("#upload-status"),
  selectedFileLabel: $("#selected-file-label"),
  selectedContext: $("#selected-context"),
  selectedContextName: $("#selected-context strong"),
  clearSelection: $("#clear-selection"),
  sheetSelect: $("#sheet-select"),
  inspect: $("#inspect-button"),
  analyze: $("#analyze-button"),
  report: $("#report-button"),
  outputList: $("#output-list"),
  emptyOutputs: $("#empty-outputs"),
  providerStatus: $("#provider-status"),
  chatLog: $("#chat-log"),
  message: $("#message-input"),
  allowWrite: $("#allow-write"),
  send: $("#send-button"),
  requestStatus: $("#request-status"),
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : {};
  if (!response.ok) {
    const suffix = data.error_id ? ` (référence ${data.error_id})` : "";
    throw new Error((data.detail || "La requête a échoué.") + suffix);
  }
  return data;
}

function text(element, value) {
  element.textContent = value == null ? "" : String(value);
  return element;
}

function selectedFile() {
  return state.files.find((file) => file.file_id === state.selectedFileId) || null;
}

function formatSize(sizeKb) {
  return sizeKb >= 1024 ? `${(sizeKb / 1024).toFixed(1)} Mo` : `${sizeKb} Ko`;
}

function addMessage(kind, content, meta = "", structured = null) {
  const article = document.createElement("article");
  article.className = `message ${kind}-message`;
  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = kind === "user" ? "Vous" : kind === "local" ? "Calcul local" : kind === "error" ? "Erreur" : "Côme AI";
  article.append(label);
  const paragraph = document.createElement("p");
  paragraph.textContent = content;
  article.append(paragraph);
  if (structured) {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(structured, null, 2);
    article.append(pre);
  }
  if (meta) {
    const footer = document.createElement("p");
    footer.className = "message-meta";
    footer.textContent = meta;
    article.append(footer);
  }
  elements.chatLog.append(article);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function setBusy(busy, label = "") {
  state.busy = busy;
  elements.send.disabled = busy;
  elements.send.textContent = busy ? "Traitement…" : "Envoyer ↗";
  elements.requestStatus.textContent = label || (busy
    ? "Analyse en cours — l’application garde une seule demande IA active pour protéger les quotas."
    : "⌘↩ ou Ctrl↩ pour envoyer · Une demande IA est traitée à la fois pour protéger les quotas.");
}

function renderFiles() {
  elements.fileList.replaceChildren();
  elements.emptyFiles.hidden = state.files.length > 0;
  for (const file of state.files) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `file-item${file.file_id === state.selectedFileId ? " selected" : ""}`;
    button.setAttribute("role", "listitem");
    button.dataset.fileId = file.file_id;
    const type = document.createElement("span");
    type.className = "file-type";
    type.textContent = String(file.type || "file").slice(0, 4).toUpperCase();
    const details = document.createElement("span");
    details.className = "file-details";
    const name = document.createElement("strong");
    name.textContent = file.name;
    name.title = file.name;
    const info = document.createElement("span");
    info.textContent = `${formatSize(file.size_kb)} · ${file.modified}`;
    details.append(name, info);
    button.append(type, details);
    button.addEventListener("click", () => selectFile(file.file_id));
    elements.fileList.append(button);
  }
  if (!selectedFile() && state.selectedFileId) state.selectedFileId = null;
  updateSelectionUI();
}

function updateSelectionUI() {
  const file = selectedFile();
  const enabled = Boolean(file);
  elements.inspect.disabled = !enabled;
  elements.analyze.disabled = !enabled || !isTable(file);
  elements.report.disabled = !enabled || !isTable(file);
  elements.sheetSelect.disabled = !enabled || !isWorkbook(file);
  elements.selectedFileLabel.textContent = file ? file.name : "Sélectionne un fichier";
  elements.selectedContext.hidden = !file;
  if (file) text(elements.selectedContextName, file.name);
}

function isTable(file) {
  return ["xlsx", "xlsm", "xls", "csv", "tsv"].includes(String(file.type).toLowerCase());
}

function isWorkbook(file) {
  return ["xlsx", "xlsm", "xls"].includes(String(file.type).toLowerCase());
}

function resetSheets() {
  elements.sheetSelect.replaceChildren();
  const first = document.createElement("option");
  first.value = "";
  first.textContent = "Première feuille / tableau";
  elements.sheetSelect.append(first);
}

function selectFile(fileId) {
  state.selectedFileId = fileId;
  resetSheets();
  renderFiles();
}

async function refreshFiles() {
  try {
    const data = await api("/api/files");
    state.files = data.files || [];
    renderFiles();
  } catch (error) {
    addMessage("error", error.message);
  }
}

function renderOutputs(outputs) {
  elements.outputList.replaceChildren();
  elements.emptyOutputs.hidden = outputs.length > 0;
  for (const output of outputs) {
    const row = document.createElement("div");
    row.className = "output-item";
    const icon = document.createElement("span");
    icon.className = "output-icon";
    icon.textContent = "↓";
    const link = document.createElement("a");
    link.href = `/api/outputs/${encodeURIComponent(output.name)}`;
    link.textContent = output.name;
    link.title = "Télécharger ce rapport";
    link.download = output.name;
    const meta = document.createElement("small");
    meta.textContent = `${formatSize(output.size_kb)} · ${output.created_at}`;
    row.append(icon, link, meta);
    elements.outputList.append(row);
  }
}

async function refreshOutputs() {
  try {
    const data = await api("/api/outputs");
    renderOutputs(data.outputs || []);
  } catch (error) {
    addMessage("error", error.message);
  }
}

async function loadHealth() {
  try {
    const data = await api("/api/health");
    const gemini = data.providers.gemini;
    const ollama = data.providers.ollama;
    if (gemini.configured) {
      elements.providerStatus.className = "provider-status ready";
      elements.providerStatus.textContent = `Gemini prêt · ${gemini.primary_model}${ollama.configured ? " · Ollama local en secours" : ""}`;
    } else if (ollama.configured) {
      elements.providerStatus.className = "provider-status ready";
      elements.providerStatus.textContent = `Ollama local prêt · ${ollama.model}`;
    } else {
      elements.providerStatus.className = "provider-status warn";
      elements.providerStatus.textContent = "Mode local : analyses disponibles. Configure une clé Gemini ou Ollama pour la conversation IA.";
    }
  } catch (error) {
    elements.providerStatus.className = "provider-status warn";
    elements.providerStatus.textContent = "Configuration des modèles indisponible.";
  }
}

async function uploadFiles(files) {
  if (!files.length) return;
  elements.uploadStatus.textContent = `Import de ${files.length} fichier(s)…`;
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  try {
    const data = await api("/api/files/upload", { method: "POST", body: form });
    const failures = (data.results || []).filter((result) => result.error);
    const successes = (data.results || []).filter((result) => result.status === "importé");
    state.files = data.files || [];
    if (successes.length) state.selectedFileId = successes[successes.length - 1].file_id;
    renderFiles();
    elements.uploadStatus.textContent = failures.length
      ? `${successes.length} importé(s), ${failures.length} erreur(s).`
      : `${successes.length} fichier(s) importé(s) dans l’espace de travail.`;
    for (const failure of failures) addMessage("error", `${failure.name || "Fichier"} : ${failure.error}`);
  } catch (error) {
    elements.uploadStatus.textContent = "Import interrompu.";
    addMessage("error", error.message);
  } finally {
    elements.fileInput.value = "";
  }
}

function actionPayload() {
  const file = selectedFile();
  if (!file) throw new Error("Sélectionne d’abord un fichier.");
  return { file_id: file.file_id, sheet_name: elements.sheetSelect.value || "" };
}

function populateSheets(result) {
  const sheets = result && result.sheets ? Object.keys(result.sheets) : [];
  if (!sheets.length) return;
  resetSheets();
  for (const sheet of sheets) {
    const option = document.createElement("option");
    option.value = sheet;
    option.textContent = sheet;
    elements.sheetSelect.append(option);
  }
  elements.sheetSelect.disabled = false;
}

async function localAction(action) {
  let payload;
  try { payload = actionPayload(); } catch (error) { addMessage("error", error.message); return; }
  const labels = { inspect: "Inspection locale", analyze: "Analyse locale", report: "Rapport créé" };
  const button = elements[action];
  button.disabled = true;
  try {
    const result = await api(`/api/actions/${action}`, { method: "POST", body: JSON.stringify(payload) });
    if (action === "inspect") populateSheets(result);
    const display = action === "report" ? result.analysis : result;
    addMessage("local", labels[action], "Aucune donnée n’a été envoyée à une IA.", display);
    if (action === "report") {
      await refreshOutputs();
      if (result.output_file) addMessage("local", `Rapport prêt : ${result.output_file}`, "Il est disponible dans « Rapports créés » à gauche.");
    }
  } catch (error) {
    addMessage("error", error.message);
  } finally {
    updateSelectionUI();
  }
}

async function sendMessage() {
  if (state.busy) return;
  const message = elements.message.value.trim();
  if (!message) return;
  const file = selectedFile();
  addMessage("user", message, file ? `Fichier ciblé : ${file.name}` : "");
  elements.message.value = "";
  setBusy(true);
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        selected_file_ids: file ? [file.file_id] : [],
        allow_write: elements.allowWrite.checked,
      }),
    });
    const events = result.tool_events && result.tool_events.length ? `Outils : ${result.tool_events.join(", ")}` : "Réponse directe";
    addMessage("assistant", result.answer || "Le modèle n’a pas renvoyé de texte exploitable.", `${result.provider || "IA"} · ${events}`);
    if ((result.tool_events || []).includes("create_analysis_workbook")) await refreshOutputs();
  } catch (error) {
    addMessage("error", error.message);
  } finally {
    elements.allowWrite.checked = false;
    setBusy(false);
    await refreshFiles();
  }
}

elements.fileInput.addEventListener("change", (event) => uploadFiles([...event.target.files]));
elements.refreshFiles.addEventListener("click", refreshFiles);
elements.inspect.addEventListener("click", () => localAction("inspect"));
elements.analyze.addEventListener("click", () => localAction("analyze"));
elements.report.addEventListener("click", () => localAction("report"));
elements.send.addEventListener("click", sendMessage);
elements.clearSelection.addEventListener("click", () => { state.selectedFileId = null; resetSheets(); renderFiles(); });
elements.message.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    sendMessage();
  }
});

["dragenter", "dragover"].forEach((name) => elements.dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  elements.dropZone.classList.add("dragover");
}));
["dragleave", "drop"].forEach((name) => elements.dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  elements.dropZone.classList.remove("dragover");
}));
elements.dropZone.addEventListener("drop", (event) => uploadFiles([...event.dataTransfer.files]));

Promise.all([refreshFiles(), refreshOutputs(), loadHealth()]);
