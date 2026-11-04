/* Révisions (Venture Capital) — wires the existing /api/vc engines to the UI.
   All learning content is served in English by the backend; only the chrome
   of this file follows the app's existing language. */
"use strict";

const rev = {
  initialized: false,
  status: null,
  tutorMode: "explain",
  tutorBusy: false,
  tutorHistory: [],
  sheets: [],
  session: null,
  drill: null,
  exam: null,
  examTimerId: null,
  examDeadline: null,
  radar: null,
  topics: [],
  cases: [],
};

function revEl(id) { return document.getElementById(id); }

async function revApi(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* keep status text */ }
    throw new Error(detail);
  }
  return response.json();
}

function revEsc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* Minimal, safe markdown: paragraphs, bold, italics, inline code, line breaks.
   Input comes from the AI tutor, so everything is escaped first. */
function revMarkdown(text) {
  const blocks = revEsc(text).split(/\n{2,}/);
  return blocks.map((block) => {
    let html = block
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
    if (/^#{1,4}\s/.test(html)) html = html.replace(/^#{1,4}\s/, "");
    return `<p>${html}</p>`;
  }).join("");
}

/* ------------------------------------------------------------ navigation */
function revSelectTab(tabId) {
  document.querySelectorAll(".rev-tab").forEach((button) => {
    const active = button.dataset.revTab === tabId;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll(".rev-panel").forEach((panel) => {
    panel.hidden = panel.id !== tabId;
  });
  if (tabId === "revProgress") { revLoadRadar(); revLoadPlan(); revLoadErrors(); }
  if (tabId === "revEvaluate") { revRefreshExamState(); }
  if (tabId === "revSheets") { revLoadSheets(); }
}

/* --------------------------------------------------------------- status */
async function revLoadStatus() {
  try {
    const status = await revApi("/api/vc/status");
    rev.status = status;
    const days = status.days_left;
    revEl("revDaysLeft").textContent = days == null ? "?" : String(days);
    revEl("revLastExam").textContent = status.last_exam
      ? `Last mock: ${Math.round(status.last_exam.score)}%`
      : "No mock yet";
    revEl("revLastExam").classList.toggle("ready", Boolean(status.last_exam));

    const tutor = status.tutor || {};
    const pill = revEl("revTutorStatus");
    if (tutor.mode === "gemini") {
      const count = Number(tutor.gemini_key_count || 1);
      pill.textContent = `Gemini configured · ${count} key${count > 1 ? "s" : ""}${tutor.kilo_enabled ? " · Kilo backup" : ""}`;
      pill.title = `Model: ${tutor.gemini_model || "configured model"}. Provider availability is checked when you send a question.`;
      pill.classList.add("ready"); pill.classList.remove("neutral", "warn");
    } else if (tutor.mode === "degraded") {
      pill.textContent = "Cloud on, no key";
      pill.classList.add("warn"); pill.classList.remove("neutral", "ready");
    } else {
      pill.textContent = "Offline mode";
      pill.classList.add("neutral"); pill.classList.remove("ready", "warn");
    }

    revEl("revisionsLead").textContent = "Understand the course. Practise the method. Walk into your exam prepared.";

    await revLoadRadarSummary();
    await revLoadTutorTopics(status);
  } catch (error) {
    revEl("revisionsLead").textContent = `Could not load revision status: ${error.message}`;
  }
}

async function revLoadRadarSummary() {
  try {
    const radar = await revApi("/api/vc/radar");
    rev.radar = radar;
    const tested = radar.topics.filter((t) => t.status !== "untested");
    revEl("revMastery").textContent = `${tested.length}/${radar.topics.length}`;
    const weak = radar.topics.filter((t) => t.status === "fragile").length;
    const due = radar.topics.reduce((sum, t) => sum + (t.due_cards || 0), 0);
    revEl("revDueCards").textContent = String(due);
    if (weak > 0) {
      revEl("revMastery").title = `${weak} weak topic(s) — see Progress`;
    }
  } catch (_) { /* radar is decorative on the home row */ }
}

async function revLoadTutorTopics(status) {
  const select = revEl("revTutorTopic");
  const drillSelect = revEl("revDrillTopic");
  if (select.options.length > 1) return;
  try {
    const coverage = await revApi("/api/vc/coverage");
    rev.topics = coverage.topics || [];
    for (const topic of coverage.topics) {
      const label = `${topic.topic_id} · ${topic.title || topic.topic_id}`;
      const option = document.createElement("option");
      option.value = topic.topic_id;
      option.textContent = label;
      select.appendChild(option);
      if (topic.has_drill) drillSelect.appendChild(option.cloneNode(true));
    }
  } catch (_) { /* selects stay with their default option */ }
}

/* ---------------------------------------------------------------- tutor */
function revPushChat(role, html, meta) {
  const log = revEl("revTutorLog");
  const wrapper = document.createElement("article");
  wrapper.className = `rev-msg ${role}`;
  const badge = meta
    ? `<span class="rev-badge ${revEsc(meta.kind)}">${revEsc(meta.label)}</span>`
    : "";
  wrapper.innerHTML = `<header>${revEsc(role === "ai" ? "Tutor" : "You")}${badge}</header>${html}`;
  log.appendChild(wrapper);
  log.scrollTop = log.scrollHeight;
}

async function revSendTutor({ check = false } = {}) {
  if (rev.tutorBusy) return;
  const input = revEl("revTutorInput");
  const message = input.value.trim();
  if (!message) return;
  const mode = check ? "correct" : rev.tutorMode;
  rev.tutorBusy = true;
  revEl("revTutorForm").querySelectorAll("button").forEach((button) => { button.disabled = true; });
  const topicId = revEl("revTutorTopic").value || null;

  revPushChat("you", revMarkdown(message));
  input.value = "";
  const thinking = document.createElement("article");
  thinking.className = "rev-msg ai thinking";
  thinking.innerHTML = "<header>Tutor</header><p>Thinking…</p>";
  revEl("revTutorLog").appendChild(thinking);
  revEl("revTutorLog").scrollTop = revEl("revTutorLog").scrollHeight;

  try {
    const payload = await revApi("/api/vc/tutor", {
      method: "POST",
      body: JSON.stringify({
        message,
        mode,
        topic_id: topicId,
        history: rev.tutorHistory.slice(-6),
      }),
    });
    thinking.remove();
    const isAi = payload.source === "ai";
    revPushChat("ai", revMarkdown(payload.text), {
      kind: isAi ? "ai" : "offline",
      label: isAi ? "AI" : "Offline",
    });
    rev.tutorHistory.push({ role: "student", text: message });
    rev.tutorHistory.push({ role: "tutor", text: payload.text });
    revRenderSources(payload.passages || []);
    if (isAi && payload.text) revOfferStudySheet({ question: message, topicId, summary: payload.text, passages: payload.passages || [] });
  } catch (error) {
    thinking.remove();
    revPushChat("ai", revMarkdown(`Request failed: ${error.message}`), {
      kind: "offline", label: "Error",
    });
    if (!input.value.trim()) input.value = message;
  } finally {
    rev.tutorBusy = false;
    revEl("revTutorForm").querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

function revSheetTitle(question, topicId) {
  const compact = String(question || "Tutor revision").replace(/\s+/g, " ").trim();
  const short = compact.length > 88 ? `${compact.slice(0, 85).trim()}…` : compact;
  return topicId ? `${topicId} · ${short}` : short;
}

function revOfferStudySheet({ question, topicId, summary, passages }) {
  const log = revEl("revTutorLog");
  const action = document.createElement("div");
  action.className = "rev-sheet-offer";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "vc-secondary";
  button.textContent = "Save as revision sheet";
  const hint = document.createElement("span");
  hint.textContent = "Saved locally · reopen and practise later";
  action.append(button, hint);
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const data = await revApi("/api/vc/sheets", {
        method: "POST",
        body: JSON.stringify({
          title: revSheetTitle(question, topicId),
          topic_id: topicId,
          question,
          summary,
          sources: passages.map((item) => item.citation).filter(Boolean),
        }),
      });
      button.textContent = "✓ Saved locally";
      hint.textContent = "Open My sheets whenever you want to revise it again.";
      rev.sheets = [data.sheet, ...rev.sheets.filter((sheet) => sheet.sheet_id !== data.sheet.sheet_id)];
    } catch (error) {
      button.disabled = false;
      hint.textContent = `Could not save: ${error.message}`;
    }
  });
  log.appendChild(action);
  log.scrollTop = log.scrollHeight;
}

function revSheetDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Saved locally" : date.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

async function revLoadSheets() {
  const box = revEl("revSheetsList");
  const status = revEl("revSheetsStatus");
  try {
    const data = await revApi("/api/vc/sheets");
    rev.sheets = data.sheets || [];
    status.textContent = rev.sheets.length ? "Stored locally on this Mac." : "";
    revRenderSheets();
  } catch (error) {
    status.textContent = `Could not load saved sheets: ${error.message}`;
    box.innerHTML = "";
  }
}

function revRenderSheets() {
  const box = revEl("revSheetsList");
  const count = revEl("revSheetsCount");
  count.textContent = `${rev.sheets.length} saved`;
  if (!rev.sheets.length) {
    box.innerHTML = '<div class="vc-empty-state"><span aria-hidden="true">▤</span><h3>No saved sheet yet.</h3><p>Ask the tutor about a concept, then use “Save as revision sheet”.</p></div>';
    return;
  }
  box.innerHTML = rev.sheets.map((sheet) => `
    <article class="rev-sheet-card" data-sheet-id="${revEsc(sheet.sheet_id)}">
      <header><span class="rev-chip static">${revEsc(sheet.topic_id || "General")}</span><span class="quiet-status">${revEsc(revSheetDate(sheet.created_at))}</span></header>
      <h3>${revEsc(sheet.title)}</h3>
      ${sheet.question ? `<p class="rev-sheet-question"><strong>Your question:</strong> ${revEsc(sheet.question)}</p>` : ""}
      <div class="rev-sheet-summary">${revMarkdown(sheet.summary)}</div>
      ${sheet.sources?.length ? `<details class="rev-sheet-sources"><summary>Course extracts used (${sheet.sources.length})</summary>${sheet.sources.map((source) => `<p>📄 ${revEsc(source)}</p>`).join("")}</details>` : ""}
      <footer><button type="button" class="vc-secondary" data-sheet-practise="${revEsc(sheet.sheet_id)}">Practise this topic</button><button type="button" class="vc-quiet-button" data-sheet-tutor="${revEsc(sheet.sheet_id)}">Ask again</button><button type="button" class="text-button" data-sheet-delete="${revEsc(sheet.sheet_id)}">Delete</button></footer>
    </article>`).join("");
  box.querySelectorAll("[data-sheet-practise]").forEach((button) => button.addEventListener("click", () => revPractiseSheet(button.dataset.sheetPractise)));
  box.querySelectorAll("[data-sheet-tutor]").forEach((button) => button.addEventListener("click", () => revReopenSheetTutor(button.dataset.sheetTutor)));
  box.querySelectorAll("[data-sheet-delete]").forEach((button) => button.addEventListener("click", () => revDeleteSheet(button.dataset.sheetDelete)));
}

function revSheetById(id) { return rev.sheets.find((sheet) => sheet.sheet_id === id); }

function revPractiseSheet(id) {
  const sheet = revSheetById(id);
  if (!sheet?.topic_id) {
    revEl("revSheetsStatus").textContent = "This general sheet has no single calculation topic. Reopen it with the tutor or choose a topic in Practise.";
    return;
  }
  const select = revEl("revDrillTopic");
  if ([...select.options].some((option) => option.value === sheet.topic_id)) select.value = sheet.topic_id;
  revSelectTab("revPractice");
  if (typeof vcSetTrainingMode === "function") vcSetTrainingMode("drills");
  revDrawDrill();
}

function revReopenSheetTutor(id) {
  const sheet = revSheetById(id);
  if (!sheet) return;
  revSelectTab("revLearn");
  const select = revEl("revTutorTopic");
  if (sheet.topic_id && [...select.options].some((option) => option.value === sheet.topic_id)) select.value = sheet.topic_id;
  revEl("revTutorInput").value = `Help me revise this saved sheet: ${sheet.title}. Ask me one exam-style question at a time.`;
  revEl("revTutorInput").focus();
}

async function revDeleteSheet(id) {
  const sheet = revSheetById(id);
  if (!sheet || !window.confirm(`Delete the local sheet “${sheet.title}”?`)) return;
  try {
    await revApi(`/api/vc/sheets/${encodeURIComponent(id)}`, { method: "DELETE" });
    rev.sheets = rev.sheets.filter((item) => item.sheet_id !== id);
    revEl("revSheetsStatus").textContent = "Sheet deleted locally.";
    revRenderSheets();
  } catch (error) {
    revEl("revSheetsStatus").textContent = `Could not delete sheet: ${error.message}`;
  }
}

function revRenderSources(passages) {
  const box = revEl("revTutorSources");
  if (!passages.length) {
    box.innerHTML = '<p class="quiet-status">No matching course extract found — treat the answer as unverified and check your notes.</p>';
    return;
  }
  box.innerHTML = passages.map((p) =>
    `<div class="rev-source">📄 ${revEsc(p.citation)}</div>`
  ).join("");
}

/* ------------------------------------------------------------ flashcards */
async function revStartCards() {
  const mode = revEl("revCardMode").value;
  const scope = revEl("revCardScope").value;
  try {
    const data = await revApi(`/api/vc/review?minutes=${mode === "long" ? 30 : 10}&mode=${encodeURIComponent(mode)}&scope=${encodeURIComponent(scope)}`);
    rev.session = data.session;
    revRenderCard();
  } catch (error) {
    revEl("revCardArea").innerHTML = `<p class="quiet-status">Could not start session: ${revEsc(error.message)}</p>`;
  }
}

function revRenderCard() {
  const area = revEl("revCardArea");
  const session = rev.session;
  if (!session) { area.innerHTML = '<p class="quiet-status">No active session.</p>'; return; }
  if (!session.current) {
    area.innerHTML = `
      <div class="rev-card done">
        <h3>Session complete. Good work.</h3>
        <p>${session.summary?.seen || session.done || 0} cards reviewed · ${session.summary?.correct || 0} recalled successfully.</p>
        <button class="secondary-button" type="button" data-rev="restart">New session</button>
      </div>`;
    area.querySelector('[data-rev="restart"]').addEventListener("click", revStartCards);
    return;
  }
  const card = session.current;
  const reason = ({ "nouvelle carte": "New card", "carte due": "Due for review" })[card.reason] || card.reason || "";
  area.innerHTML = `
    <div class="rev-card" data-card-id="${revEsc(card.card_id)}">
      <header>
        <span class="rev-chip static">${revEsc(card.topic_id)}</span>
        <span class="quiet-status">${session.done + 1}/${session.total} · ${revEsc(reason)}</span>
      </header>
      <h3>${revEsc(card.question)}</h3>
      <div class="rev-card-answer" hidden></div>
      <div class="rev-card-actions">
        <button class="secondary-button" type="button" data-rev="reveal">Reveal answer</button>
        <div class="rev-grades" hidden>
          <button class="rev-grade again" type="button" data-grade="again">Again</button>
          <button class="rev-grade hard" type="button" data-grade="hard">Hard</button>
          <button class="rev-grade good" type="button" data-grade="good">Good</button>
          <button class="rev-grade easy" type="button" data-grade="easy">Easy</button>
        </div>
      </div>
    </div>`;

  area.querySelector('[data-rev="reveal"]').addEventListener("click", async () => {
    // Fetch the current card with reveal=true (server decides what is exposed).
    try {
      const data = await revApi("/api/vc/review");
      const current = data.session && data.session.current;
      const answerBox = area.querySelector(".rev-card-answer");
      if (current && current.answer) {
        answerBox.innerHTML = `<p><strong>Answer:</strong> ${revEsc(current.answer)}</p>` +
          (current.explanation ? `<p class="quiet-status">${revEsc(current.explanation)}</p>` : "");
      } else {
        answerBox.innerHTML = '<p class="quiet-status">Answer is stored with the card engine; grade yourself honestly below.</p>';
      }
      answerBox.hidden = false;
      area.querySelector('[data-rev="reveal"]').hidden = true;
      area.querySelector(".rev-grades").hidden = false;
    } catch (error) {
      area.querySelector(".rev-card-actions").insertAdjacentHTML("afterbegin",
        `<p class="quiet-status">${revEsc(error.message)}</p>`);
    }
  });

  area.querySelectorAll("[data-grade]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const data = await revApi("/api/vc/review/answer", {
          method: "POST",
          body: JSON.stringify({ grade: button.dataset.grade, duration_seconds: 0 }),
        });
        rev.session = data.session;
        revRenderCard();
        revLoadRadarSummary();
      } catch (error) {
        button.disabled = false;
        area.insertAdjacentHTML("beforeend", `<p class="quiet-status">${revEsc(error.message)}</p>`);
      }
    });
  });
}

window.revRestartCards = revStartCards;

/* ---------------------------------------------------------------- drills */
async function revDrawDrill() {
  const topic = revEl("revDrillTopic").value || null;
  try {
    const data = await revApi("/api/vc/drill/draw", {
      method: "POST",
      body: JSON.stringify({ topic_id: topic, seed: Math.floor(Math.random() * 100000) }),
    });
    rev.drill = data.drill;
    revRenderDrill();
  } catch (error) {
    revEl("revDrillArea").innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
  }
}

function revRenderDrill() {
  const area = revEl("revDrillArea");
  const drill = rev.drill;
  if (!drill) { area.innerHTML = '<p class="quiet-status">Draw an exercise to start.</p>'; return; }
  area.innerHTML = `
    <div class="rev-drill">
      <header>
        <span class="rev-chip static">${revEsc(drill.topic_id)}</span>
        <span class="quiet-status">difficulty ${drill.difficulty || "?"} · unit ${revEsc(drill.answer_unit)}</span>
      </header>
      <p class="rev-drill-prompt">${revEsc(drill.prompt)}</p>${drill.notice ? `<p class="quiet-status">${revEsc(drill.notice)}</p>` : ""}
      <form class="rev-drill-form">
        <label class="sr-only" for="revDrillAnswer">Your answer</label>
        <input id="revDrillAnswer" inputmode="decimal" placeholder="Your answer (${revEsc(drill.answer_unit)})" autocomplete="off">
        <button class="primary-button" type="submit">Grade</button>
        <button class="text-button" type="button" data-rev="skip">Skip</button>
      </form>
      <div class="rev-drill-result" hidden></div>
    </div>`;

  area.querySelector('[data-rev="skip"]').addEventListener("click", revDrawDrill);
  area.querySelector(".rev-drill-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const answer = revEl("revDrillAnswer").value.trim();
    if (!answer) return;
    try {
      const result = await revApi("/api/vc/drill/grade", {
        method: "POST",
        body: JSON.stringify({ drill_id: drill.drill_id, answer }),
      });
      const box = area.querySelector(".rev-drill-result");
      box.hidden = false;
      const ok = result.accepted;
      const steps = (result.steps || []).map((step) =>
        `<li><strong>${revEsc(step.label)}:</strong> ${revEsc(step.expression)} = ${revEsc(step.result)}</li>`
      ).join("");
      box.innerHTML = `
        <p class="rev-verdict ${ok ? "good" : "bad"}">
          <span class="rev-badge verified">Calculated feedback</span>
          ${ok ? "Correct." : `Not correct — ${revEsc(result.message || "")}`}
          ${result.diagnostic ? ` <em>(${revEsc(result.diagnostic)})</em>` : ""}
        </p>
        ${steps ? `<details class="vc-worked-solution"><summary>See the calculation step by step</summary><ol class="rev-steps">${steps}</ol></details>` : ""}
        ${ok ? "" : `<p class="quiet-status">Try the same exercise again with different numbers: press “New exercise”.</p>`}`;
      revLoadRadarSummary();
    } catch (error) {
      area.insertAdjacentHTML("beforeend", `<p class="quiet-status">${revEsc(error.message)}</p>`);
    }
  });
}

/* ---------------------------------------------------------------- papers */
async function revLoadCases() {
  const box = revEl("revCasesList");
  try {
    const data = await revApi("/api/vc/cases");
    rev.cases = data.cases || [];
    revEl("revCaseCount").textContent = `${rev.cases.length} cases`;
    if (!rev.cases.length) {
      box.innerHTML = '<p class="quiet-status">No case studies are currently available.</p>';
      return;
    }
    box.innerHTML = rev.cases.map((item) => `
      <article class="rev-case-card" data-case-id="${revEsc(item.case_id)}">
        <div class="rev-case-summary">
          <div class="rev-case-meta"><span class="rev-chip static">${revEsc(item.topic_id)}</span><span class="quiet-status">Level ${revEsc(item.difficulty)}</span></div>
          <h3>${revEsc(item.title)}</h3>
          <p>${revEsc(item.context)}</p>
          <span class="rev-case-question-count">${item.questions.length} prompts · worked criteria</span>
        </div>
        <button class="secondary-button" type="button" data-case-open="${revEsc(item.case_id)}">Open case</button>
      </article>`).join("");
    box.querySelectorAll("[data-case-open]").forEach((button) => button.addEventListener("click", () => {
      const item = rev.cases.find((entry) => entry.case_id === button.dataset.caseOpen);
      const article = button.closest(".rev-case-card");
      if (item && article) revOpenCase(item, article);
    }));
  } catch (error) {
    box.innerHTML = `<p class="quiet-status">Could not load case studies: ${revEsc(error.message)}</p>`;
    revEl("revCaseCount").textContent = "Cases unavailable";
  }
}

function revOpenCase(item, article) {
  const existing = article.querySelector(".rev-case-work");
  if (existing) { existing.remove(); return; }
  const facts = (item.facts || []).map((fact) =>
    `<span class="rev-case-fact"><strong>${revEsc(fact.label)}</strong> ${revEsc(fact.value)} ${revEsc(fact.unit || "")}</span>`
  ).join("");
  const questions = (item.questions || []).map((question, index) => `
    <label class="rev-case-question" for="revCaseAnswer${revEsc(item.case_id)}_${index}">
      <span><b>${String(index + 1).padStart(2, "0")}</b>${revEsc(question.prompt)}</span>
      <textarea id="revCaseAnswer${revEsc(item.case_id)}_${index}" data-case-question="${revEsc(question.question_id)}" rows="3" maxlength="4000" placeholder="Show your calculation and explain your reasoning…"></textarea>
    </label>`).join("");
  article.insertAdjacentHTML("beforeend", `
    <div class="rev-case-work">
      <div class="rev-case-facts">${facts}</div>
      <form class="rev-case-form">${questions}<button class="primary-button" type="submit">Check my case</button></form>
      <div class="rev-case-result" hidden></div>
    </div>`);
  const work = article.querySelector(".rev-case-work");
  work.querySelector(".rev-case-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = work.querySelector('button[type="submit"]');
    const answers = {};
    work.querySelectorAll("[data-case-question]").forEach((field) => {
      if (field.value.trim()) answers[field.dataset.caseQuestion] = field.value.trim();
    });
    submit.disabled = true;
    try {
      const response = await revApi(`/api/vc/cases/${encodeURIComponent(item.case_id)}/grade`, {
        method: "POST", body: JSON.stringify({ answers }),
      });
      revRenderCaseResult(work.querySelector(".rev-case-result"), response.result);
      revLoadRadarSummary();
    } catch (error) {
      work.querySelector(".rev-case-result").hidden = false;
      work.querySelector(".rev-case-result").innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
    } finally {
      submit.disabled = false;
    }
  });
  work.querySelector("textarea")?.focus({ preventScroll: true });
}

function revRenderCaseResult(box, result) {
  box.hidden = false;
  const criteria = (result.criteria || []).map((criterion) => `
    <li class="${criterion.matched ? "matched" : "missed"}">
      <span>${criterion.matched ? "✓" : "↗"}</span><div><strong>${revEsc(criterion.label)}</strong><small>${revEsc(criterion.model_answer || "Review this criterion in your course notes.")}</small></div>
    </li>`).join("");
  const unsupported = (result.unsupported_numbers || []).length
    ? `<p class="rev-case-warning">Check unsupported figures in your answer: ${result.unsupported_numbers.map(revEsc).join(", ")}</p>`
    : "";
  box.innerHTML = `
    <p class="rev-case-score">Practice checklist: <strong>${Math.round((result.score || 0) * 100)}%</strong><span> · criterion-based feedback</span></p>
    <p class="quiet-status">${revEsc(result.notice || "Use this as practice feedback, not an official grade.")}</p>
    ${unsupported}<h4>Compare your answer with the worked criteria</h4><ul class="rev-case-criteria">${criteria}</ul>
    <details class="rev-case-model"><summary>Read the complete worked answer</summary><p>${revEsc(result.model_answer || "")}</p></details>`;
}

async function revLoadPapers() {
  const box = revEl("revPapersList");
  try {
    const data = await revApi("/api/vc/papers");
    box.innerHTML = data.papers.map((paper) => `
      <article class="rev-paper" data-year="${paper.year}">
        <div>
          <h3>${revEsc(paper.title || `Final exam ${paper.year}`)}</h3>
          <p class="quiet-status">${paper.questions} questions · ${paper.points} points</p>
        </div>
        <div class="rev-actions">
          <button class="text-button" type="button" data-action="show">Open subject</button>
          <button class="text-button" type="button" data-action="solutions">Solutions &amp; key</button>
          <button class="secondary-button" type="button" data-action="practice">Practice & grade</button>
        </div>
      </article>`).join("");
    box.querySelectorAll(".rev-paper").forEach((card) => {
      const year = card.dataset.year;
      card.querySelector('[data-action="show"]').addEventListener("click", () => revOpenPaper(year, false, card));
      card.querySelector('[data-action="solutions"]').addEventListener("click", () => revOpenPaper(year, true, card));
      card.querySelector('[data-action="practice"]').addEventListener("click", () => revPracticePaper(year, card));
    });
  } catch (error) {
    box.innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
  }
}

async function revOpenPaper(year, solutions, card) {
  const mode = solutions ? "solutions" : "subject";
  const previous = card.querySelector(".rev-paper-detail");
  if (previous) { const same = previous.dataset.mode === mode; previous.remove(); if (same) return; }
  try {
    const { paper } = await revApi(`/api/vc/papers/${year}${solutions ? "?solutions=true" : ""}`);
    const questionHtml = paper.questions.map((q) => {
      const choices = (q.choices || []).map((c) => `<li>${revEsc(c.label)}. ${revEsc(c.text)}</li>`).join("");
      const answer = solutions && q.answer ? `<p class="rev-paper-answer"><b>${q.kind === "mcq" ? "Derived MCQ key" : "Worked answer"}:</b> ${revEsc(q.answer)} ${revEsc(q.solution || "")}</p>` : "";
      const parts = (q.parts || []).map((part) => `<li>${revEsc(part.prompt)} <small>(${part.points} points)</small>${solutions ? `<p class="rev-paper-answer">${revEsc(part.answer || "")} ${revEsc(part.solution || "")}</p>` : ""}</li>`).join("");
      return `<li class="vc-paper-view-question"><strong>Question ${q.number} · ${q.points} points</strong><p>${revEsc(q.prompt)}</p>${choices ? `<ol class="rev-choices">${choices}</ol>` : ""}${answer}${parts ? `<ol>${parts}</ol>` : ""}</li>`;
    }).join("");
    card.insertAdjacentHTML("beforeend", `<div class="rev-paper-detail" data-mode="${mode}">${solutions && paper.notice ? `<p class="rev-paper-notice">${revEsc(paper.notice)}</p>` : ""}<ol class="vc-paper-view">${questionHtml}</ol></div>`);
  } catch (error) { card.insertAdjacentHTML("beforeend", `<p role="status" class="quiet-status">${revEsc(error.message)}</p>`); }
}

async function revPracticePaper(year, card) {
  const previous = card.querySelector(".rev-paper-detail");
  if (previous) { const same = previous.dataset.mode === "practice"; previous.remove(); if (same) return; }
  try {
    const { paper } = await revApi(`/api/vc/papers/${year}`);
    const answerField = (id, prompt, kind, points, unit = "") => `<label class="rev-paper-field"><span>${revEsc(prompt)} <small>(${points} points${unit ? ` · ${revEsc(unit)}` : ""})</small></span>${kind === "numeric" ? `<input data-qid="${revEsc(id)}" inputmode="decimal" placeholder="Your numerical answer" autocomplete="off">` : `<textarea data-qid="${revEsc(id)}" rows="4" maxlength="8000" placeholder="Explain your method and reasoning…"></textarea>`}</label>`;
    const fields = paper.questions.map((q) => {
      let content = "";
      if (q.kind === "mcq") {
        content = `<div class="vc-mcq-options">${q.choices.map((choice) => `<label><input type="radio" name="${revEsc(q.id)}" data-qid="${revEsc(q.id)}" value="${revEsc(choice.label)}"><span class="vc-choice-letter" aria-hidden="true">${revEsc(choice.label)}</span><span class="vc-choice-text">${revEsc(choice.text)}</span></label>`).join("")}</div>`;
      } else if (q.parts?.length) {
        content = q.parts.map((part) => answerField(part.id, part.prompt, part.kind, part.points, part.unit)).join("");
      } else {
        content = answerField(q.id, q.kind === "numeric" ? "Your calculation" : "Your reasoning", q.kind, q.points, q.unit);
      }
      return `<fieldset class="vc-paper-question"><legend>Question ${q.number} · Section ${revEsc(q.section)} · ${q.points} points</legend><p>${revEsc(q.prompt)}</p>${content}</fieldset>`;
    }).join("");
    card.insertAdjacentHTML("beforeend", `<div class="rev-paper-detail" data-mode="practice"><p class="quiet-status">Your draft stays in this browser. Numerical parts are checked automatically; written answers are reviewed against the worked solution. MCQ letters use the derived study key.</p><form class="rev-paper-form">${fields}<button class="vc-primary" type="submit">Check my paper</button></form><div class="rev-paper-grade" hidden></div></div>`);
    const detail = card.querySelector(".rev-paper-detail");
    const draftKey = `nage-vc-paper-${year}-draft`;
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey) || "{}");
      detail.querySelectorAll("[data-qid]").forEach((field) => { if (field.type === "radio") field.checked = draft[field.dataset.qid] === field.value; else field.value = draft[field.dataset.qid] || ""; });
    } catch (_) { /* browser storage is optional */ }
    const readAnswers = () => {
      const answers = {};
      detail.querySelectorAll("[data-qid]").forEach((field) => {
        if (field.type === "radio" && !field.checked) return;
        if (field.value.trim()) answers[field.dataset.qid] = field.value.trim();
      });
      return answers;
    };
    detail.addEventListener("input", () => { try { localStorage.setItem(draftKey, JSON.stringify(readAnswers())); } catch (_) { /* keep working */ } });
    detail.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = detail.querySelector('button[type="submit"]');
      submit.disabled = true;
      try {
        const { result } = await revApi(`/api/vc/papers/${year}/grade`, { method: "POST", body: JSON.stringify({ year: Number(year), answers: readAnswers() }) });
        const feedback = (result.items || []).map((item) => `<details class="vc-paper-feedback ${revEsc(item.status)}"><summary>Q${item.number}${item.part_id ? ` · ${revEsc(item.part_id)}` : ""} — ${item.status === "self_assess" ? "Compare your written answer" : `${item.earned}/${item.max} points`}</summary><p>${revEsc(item.part_prompt || item.prompt)}</p><p><strong>Worked answer:</strong> ${revEsc(item.model_answer ?? item.expected ?? "See the solution below.")}</p><p>${revEsc(item.solution || item.message || "")}</p></details>`).join("");
        const box = detail.querySelector(".rev-paper-grade");
        box.hidden = false;
        box.innerHTML = `<h3>Automatically checked: ${result.auto_points}/${result.auto_max} points${result.auto_percent == null ? "" : ` · ${result.auto_percent}%`}</h3><p>${result.self_assessment_points} points require written-answer self-review. This percentage is not a final full-paper grade.</p><p class="quiet-status">${revEsc(result.notice || "")}</p>${feedback}`;
        box.scrollIntoView({ behavior: "smooth", block: "start" });
        revLoadRadarSummary();
      } catch (error) {
        const box = detail.querySelector(".rev-paper-grade"); box.hidden = false; box.textContent = error.message;
      } finally { submit.disabled = false; }
    });
  } catch (error) { card.insertAdjacentHTML("beforeend", `<p role="status" class="quiet-status">${revEsc(error.message)}</p>`); }
}

/* ----------------------------------------------------------------- exam */
async function revRefreshExamState() {
  try {
    const data = await revApi("/api/vc/exam/state");
    if (data.active && data.active.status === "active") {
      rev.exam = data.active;
      revRenderExam();
      revStartExamTimer();
      revEl("revExamStart").hidden = true;
      revEl("revExamSubmit").hidden = false;
    } else {
      revEl("revExamSubmit").hidden = true;
      revStopExamTimer();
    }
  } catch (_) { /* exam panel shows its own empty state */ }
}

async function revStartExam() {
  try {
    const data = await revApi("/api/vc/exam/start", {
      method: "POST",
      body: JSON.stringify({ questions: 20, minutes: 90, new: false }),
    });
    rev.exam = data.active;
    revRenderExam();
    revStartExamTimer();
    revEl("revExamStart").hidden = true;
    revEl("revExamSubmit").hidden = false;
    revEl("revExamResult").hidden = true;
  } catch (error) {
    revEl("revExamArea").innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
  }
}

function revRenderExam() {
  const area = revEl("revExamArea");
  const exam = rev.exam;
  if (!exam) return;
  area.innerHTML = `
    <p class="quiet-status">${exam.total_questions} questions · ${exam.total_points} points · draft answers stay in this browser; results are saved when you submit.</p>
    <ol class="rev-exam-list">
      ${exam.questions.map((q, index) => `
        <li class="rev-exam-q" data-qid="${revEsc(q.question_id)}">
          <header><span>#${index + 1}</span><span class="rev-chip static">${revEsc(q.topic_id)}</span><span>${q.points} pts</span></header>
          <p>${revEsc(q.question)}</p>
          ${q.choices ? `<ol type="A" class="rev-choices">${q.choices.map((c) => `<li>${revEsc(c)}</li>`).join("")}</ol>` : ""}
          <input type="text" autocomplete="off" placeholder="Your answer" aria-label="Answer for question ${index + 1}">
        </li>`).join("")}
    </ol>`;
  const key = `nage-vc-exam-${exam.exam_id}-draft`;
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "{}");
    area.querySelectorAll(".rev-exam-q").forEach((item) => { item.querySelector("input").value = saved[item.dataset.qid] || exam.answers?.[item.dataset.qid] || ""; });
  } catch (_) { /* storage preference does not block the exam */ }
  area.oninput = () => {
    const draft = {};
    area.querySelectorAll(".rev-exam-q").forEach((item) => { draft[item.dataset.qid] = item.querySelector("input").value; });
    try { localStorage.setItem(key, JSON.stringify(draft)); } catch (_) { /* keep working */ }
  };
}

function revStartExamTimer() {
  revStopExamTimer();
  if (!rev.exam) return;
  rev.examDeadline = new Date(rev.exam.deadline);
  const tick = () => {
    const remaining = Math.max(0, Math.floor((rev.examDeadline - Date.now()) / 1000));
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    const timer = revEl("revExamTimer");
    timer.hidden = false;
    timer.textContent = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    timer.classList.toggle("warn", remaining < 300);
    if (remaining <= 0) { revStopExamTimer(); revSubmitExam(true); }
  };
  tick();
  rev.examTimerId = window.setInterval(tick, 1000);
}

function revStopExamTimer() {
  if (rev.examTimerId) { window.clearInterval(rev.examTimerId); rev.examTimerId = null; }
  const timer = revEl("revExamTimer");
  if (timer) timer.hidden = true;
}

async function revSubmitExam(auto = false) {
  if (!rev.exam) return;
  if (!auto && !window.confirm("Submit your copy? Unanswered questions score zero.")) return;
  const answers = {};
  document.querySelectorAll(".rev-exam-q").forEach((item) => {
    const input = item.querySelector("input");
    if (input && input.value.trim()) answers[item.dataset.qid] = input.value.trim();
  });
  revStopExamTimer();
  try {
    const data = await revApi("/api/vc/exam/submit", {
      method: "POST",
      body: JSON.stringify({ exam_id: rev.exam.exam_id, answers }),
    });
    rev.exam = null;
    revEl("revExamStart").hidden = false;
    revEl("revExamSubmit").hidden = true;
    revRenderExamResult(data.result);
    revLoadStatus();
  } catch (error) {
    revEl("revExamResult").hidden = false;
    revEl("revExamResult").innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
  }
}

function revRenderExamResult(result) {
  const box = revEl("revExamResult");
  box.hidden = false;
  const perTopic = Object.entries(result.per_topic || {}).map(([topicId, value]) => {
    const max = value.max || 1;
    const percent = Math.round(((value.earned || 0) / max) * 100);
    const weak = percent < 60;
    return `<li class="${weak ? "weak" : ""}">${revEsc(topicId)} — ${percent}%${weak ? " (weak)" : ""}</li>`;
  }).join("");
  box.innerHTML = `
    <p class="rev-verdict ${result.score >= 60 ? "good" : "bad"}">
      <span class="rev-badge verified">Deterministic grading</span>
      Score: ${Math.round(result.score)}% · ${result.earned_points ?? "?"}/${result.max_points ?? "?"} points
    </p>
    ${result.expired ? '<p class="quiet-status">Time was up: the copy was graded at the deadline.</p>' : ""}
    <h3>By topic</h3>
    <ul class="rev-topic-scores">${perTopic}</ul>
    ${result.remediation && result.remediation.length
      ? `<h3>Recommended next steps</h3><ul>${result.remediation.map((r) => `<li>${revEsc(typeof r === "string" ? r : (r.reason || JSON.stringify(r)))}</li>`).join("")}</ul>`
      : ""}
    <p class="quiet-status">Open the Progress tab to see the updated radar and plan.</p>`;
  revSelectTab("revEvaluate");
}

/* -------------------------------------------------------------- progress */
async function revLoadRadar() {
  const box = revEl("revRadar");
  try {
    const [radar, readinessPayload] = await Promise.all([
      revApi("/api/vc/radar"),
      revApi("/api/vc/readiness"),
    ]);
    const readiness = readinessPayload.readiness || {};
    const priorities = (readiness.priority_topics || []).slice(0, 3);
    const priorityHtml = priorities.length
      ? `<ul class="rev-readiness-priorities">${priorities.map((topic) => `<li><strong>${revEsc(topic.topic_id)}</strong> ${revEsc(topic.title)} <span>${revEsc(topic.status)}</span></li>`).join("")}</ul>`
      : `<p class="quiet-status">No critical topic detected yet.</p>`;
    const readinessHtml = `<div class="rev-readiness-summary"><div><strong>Exam readiness</strong><span>${Number(readiness.score || 0).toFixed(1)}%</span></div><p>${readiness.ready ? "Ready threshold reached." : "Keep practising before attempting the full mock."} ${readiness.official_paper_questions || 0} official paper questions · ${readiness.graded_cases || 0} graded cases.</p>${priorityHtml}</div>`;
    const statusLabel = { untested: "Not tested", fragile: "Revisit first", developing: "Developing", solid: "Strong results" };
    box.innerHTML = readinessHtml + radar.topics.map((topic) => {
      const accuracy = topic.accuracy == null ? "—" : `${Math.round(topic.accuracy * 100)}%`;
      return `
        <div class="rev-radar-row ${revEsc(topic.status)}">
          <span class="rev-chip static">${revEsc(topic.topic_id)}</span>
          <span class="rev-radar-title">${revEsc(topic.title)}</span>
          <span class="rev-radar-status">${revEsc(statusLabel[topic.status] || topic.status)}</span>
          <span class="quiet-status">${topic.attempts} attempts · ${accuracy}</span>
        </div>`;
    }).join("");
  } catch (error) {
    box.innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
  }
}

async function revLoadPlan() {
  const box = revEl("revPlan");
  const minutes = revEl("revPlanMinutes").value;
  try {
    const data = await revApi(`/api/vc/plan?minutes=${encodeURIComponent(minutes)}`);
    const plan = data.plan;
    box.innerHTML = (plan.activities || []).map((activity) => `
      <div class="rev-plan-item">
        <span class="rev-chip static">${revEsc(activity.kind)}</span>
        <span>${revEsc(activity.topic_id || "")}</span>
        <span class="quiet-status">${revEsc(activity.reason || "")}</span>
        <span class="quiet-status">${activity.minutes || ""} min</span>
      </div>`).join("") || '<p class="quiet-status">Nothing scheduled for this duration.</p>';
  } catch (error) {
    box.innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
  }
}

async function revLoadErrors() {
  const box = revEl("revErrors");
  try {
    const data = await revApi("/api/vc/errors");
    const dashboard = data.dashboard;
    if (!dashboard.total_errors) {
      box.innerHTML = '<p class="quiet-status">No recorded mistakes yet. Complete drills, flashcards or a mock exam to populate this.</p>';
      return;
    }
    const categories = (dashboard.categories || []).map((entry) =>
      `<li><strong>${revEsc(entry.category)}</strong>: ${entry.count}</li>`).join("");
    const topics = (dashboard.topics || []).slice(0, 6).map((entry) =>
      `<li>${revEsc(entry.topic_id)} — ${entry.errors}</li>`).join("");
    box.innerHTML = `<ul>${categories}</ul><h4>Topics to fix first</h4><ul>${topics}</ul>`;
  } catch (error) {
    box.innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
  }
}

/* -------------------------------------------------------------- formulas */
async function revToggleFormulas() {
  const box = revEl("revFormulas");
  if (!box.hidden) { box.hidden = true; return; }
  try {
    const data = await revApi("/api/vc/formulas");
    box.innerHTML = (data.sheet.groups || []).map((group) => `
      <div class="rev-formula-group">
        <h4>${revEsc(group.title)}</h4>
        ${group.items.map((item) => `<p><strong>${revEsc(item.name)}:</strong> <code>${revEsc(item.formula)}</code>${item.note ? `<br><span class="quiet-status">${revEsc(item.note)}</span>` : ""}</p>`).join("")}
      </div>`).join("");
    box.hidden = false;
  } catch (error) {
    box.innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
    box.hidden = false;
  }
}

/* ------------------------------------------------------- recommended next */
async function revStartRecommended() {
  if (typeof window.vcStudioContinue === "function") {
    window.vcStudioContinue();
  } else {
    revSelectTab("revCourse");
  }
}

/* ------------------------------------------------------------- bootstrap */
function revBind() {
  document.querySelectorAll(".rev-tab").forEach((button) =>
    button.addEventListener("click", () => { revSelectTab(button.dataset.revTab); document.querySelector(".vc-main-tabs")?.scrollIntoView({ block: "start", behavior: "smooth" }); }));

  document.querySelectorAll("[data-tutor-mode]").forEach((button) =>
    button.addEventListener("click", () => {
      rev.tutorMode = button.dataset.tutorMode;
      document.querySelectorAll("[data-tutor-mode]").forEach((b) =>
        b.classList.toggle("active", b === button));
    }));

  revEl("revTutorForm").addEventListener("submit", (event) => { event.preventDefault(); revSendTutor(); });
  revEl("revTutorCheck").addEventListener("click", () => revSendTutor({ check: true }));
  revEl("revCardsStart").addEventListener("click", revStartCards);
  revEl("revDrillDraw").addEventListener("click", revDrawDrill);
  revEl("revExamStart").addEventListener("click", revStartExam);
  revEl("revExamSubmit").addEventListener("click", () => revSubmitExam(false));
  revEl("revPlanMinutes").addEventListener("change", revLoadPlan);
  revEl("revRefreshRadar").addEventListener("click", revLoadRadar);
  revEl("revLoadFormulas").addEventListener("click", revToggleFormulas);
  revEl("revStartNow").addEventListener("click", revStartRecommended);
  document.querySelectorAll("[data-rev-go]").forEach((button) => button.addEventListener("click", () => revSelectTab(button.dataset.revGo)));
  revLoadCases();
  revLoadPapers();
}

window.initRevisions = function initRevisions() {
  if (rev.initialized) { revLoadStatus(); if (typeof window.initVcStudio === "function") window.initVcStudio(); return; }
  rev.initialized = true;
  revBind();
  revLoadStatus();
  if (typeof window.initVcStudio === "function") window.initVcStudio();
};

/* Deep link: #v5/revisionsView from the browser address bar. */
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { /* activation binds it */ });
}
