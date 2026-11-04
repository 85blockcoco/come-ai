/* Révisions (Venture Capital) — wires the existing /api/vc engines to the UI.
   All learning content is served in English by the backend; only the chrome
   of this file follows the app's existing language. */
"use strict";

const rev = {
  initialized: false,
  status: null,
  tutorMode: "explain",
  tutorHistory: [],
  session: null,
  drill: null,
  exam: null,
  examTimerId: null,
  examDeadline: null,
  radar: null,
  topics: [],
  cases: [],
};

const revPathLevels = [
  { courseLabel: "COURSE TOPIC 1", title: "The venture capital landscape", subtitle: "Ecosystem, fund economics and financing stages", topics: ["VC01", "VC02", "VC03"], icon: "◈" },
  { courseLabel: "COURSE TOPIC 2", title: "Evaluating startups", subtitle: "Diligence, metrics, financial models and investment thesis", topics: ["VC10", "VC14", "VC15", "VC18"], icon: "◎" },
  { courseLabel: "COURSE TOPIC 3", title: "Valuation, ownership & returns", subtitle: "Pre/post-money, cap tables, dilution and fund returns", topics: ["VC04", "VC05", "VC09"], icon: "↗" },
  { courseLabel: "COURSE TOPIC 4", title: "Term sheets & deal structure", subtitle: "Economics, control rights, downside protection and instruments", topics: ["VC06", "VC07", "VC08", "VC16", "VC19"], icon: "⌁" },
  { courseLabel: "COURSE TOPIC 5", title: "Governance, monitoring & exits", subtitle: "Portfolio support, boards, European context and exit routes", topics: ["VC11", "VC12", "VC13", "VC17", "VC21"], icon: "✳" },
  { courseLabel: "EXAM PRACTICE", title: "Exam technique & past papers", subtitle: "Practise the case method and work through real EDHEC papers", topics: ["VC20"], icon: "★" },
];

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
      pill.textContent = `Gemini online · ${tutor.gemini_model || ""}`;
      pill.classList.add("ready"); pill.classList.remove("neutral", "warn");
    } else if (tutor.mode === "degraded") {
      pill.textContent = "Cloud on, no key";
      pill.classList.add("warn"); pill.classList.remove("neutral", "ready");
    } else {
      pill.textContent = "Offline mode";
      pill.classList.add("neutral"); pill.classList.remove("ready", "warn");
    }

    const dateLabel = status.exam_date ? `exam ${status.exam_date}` : "exam date not set";
    revEl("revisionsLead").textContent =
      `${status.counts.topics} topics · ${status.counts.cards} flashcards · ` +
      `${status.counts.drills} drills · ${status.counts.papers} past papers · ${dateLabel}.`;

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
    const weak = radar.topics.filter((t) => t.status === "weak").length;
    const due = radar.topics.reduce((sum, t) => sum + (t.due_cards || 0), 0);
    revEl("revDueCards").textContent = String(due);
    if (weak > 0) {
      revEl("revMastery").title = `${weak} weak topic(s) — see Progress`;
    }
    revRenderRoadmap();
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
      const drillOption = option.cloneNode(true);
      drillSelect.appendChild(drillOption);
    }
    revRenderRoadmap();
  } catch (_) { /* selects stay with their default option */ }
}

function revRenderRoadmap() {
  const box = revEl("revRoadmap");
  if (!box || !rev.radar) return;
  const radarTopics = rev.radar.topics || [];
  const byId = new Map(radarTopics.map((topic) => [topic.topic_id, topic]));
  const coverageById = new Map(rev.topics.map((topic) => [topic.topic_id, topic]));
  const explored = radarTopics.filter((topic) => topic.status !== "untested").length;
  const mastered = radarTopics.filter((topic) => topic.status === "mastered").length;
  const total = radarTopics.length || 21;
  const percent = total ? Math.round((explored / total) * 100) : 0;
  const coverageLevels = rev.topics.reduce((counts, topic) => {
    counts[topic.level] = (counts[topic.level] || 0) + 1;
    return counts;
  }, {});
  const broad = coverageLevels.full || 0;
  const partial = coverageLevels.partial || 0;
  const thin = coverageLevels.thin || 0;
  revEl("revCoverageSummary").textContent = `${broad} topics have broad practice · ${partial} partial · ${thin} flashcards-only`;
  const paperCount = rev.status?.counts?.papers || 0;
  revEl("revCoverageDetail").textContent = `The activity bank spans ${total} topics and ${paperCount} past papers. This map shows available practice formats; it does not prove every course page is represented or mean a topic is mastered.`;
  const recommendedLevel = revPathLevels.findIndex((level) => {
    const items = level.topics.map((id) => byId.get(id)).filter(Boolean);
    return items.length && !items.every((topic) => ["strong", "mastered"].includes(topic.status));
  });
  revEl("revPathProgressLabel").textContent = `${explored} of ${total} topics explored${mastered ? ` · ${mastered} mastered` : ""}`;
  revEl("revPathProgressPercent").textContent = `${percent}%`;
  const progress = revEl("revPathProgress");
  progress.setAttribute("aria-valuemax", String(total));
  progress.setAttribute("aria-valuenow", String(explored));
  progress.querySelector("span").style.width = `${percent}%`;

  const levels = revPathLevels.map((level) => {
    const topics = level.topics.map((id) => byId.get(id)).filter(Boolean);
    const seen = topics.filter((topic) => topic.status !== "untested").length;
    const strong = topics.filter((topic) => ["strong", "mastered"].includes(topic.status)).length;
    const weak = topics.filter((topic) => topic.status === "weak").length;
    const allStrong = topics.length > 0 && strong === topics.length;
    const levelIndex = revPathLevels.indexOf(level);
    const state = allStrong ? "completed" : levelIndex === recommendedLevel || seen ? "in-progress" : "up-next";
    const nextTopic = topics.find((topic) => topic.status === "weak") || topics.find((topic) => topic.status === "untested") || topics[0];
    const label = allStrong ? "Strong across this level" : seen ? `${seen} of ${topics.length} explored${weak ? ` · ${weak} to revisit` : ""}` : `${topics.length} topics`;
    const topicLabel = nextTopic ? `${nextTopic.topic_id} · ${nextTopic.title || nextTopic.topic_id}` : "Explore this level";
    const safeTitle = revEsc(level.title);
    const syllabus = topics.map((topic) => {
      const coverage = coverageById.get(topic.topic_id) || {};
      const formats = [coverage.cards, coverage.drills, coverage.cases, coverage.exams, coverage.papers].filter((count) => count > 0).length;
      const summary = revTopicActivitySummary(coverage);
      const formatLabel = formats === 1 ? "Flashcards only" : summary;
      return `<button class="rev-syllabus-chip" type="button" data-rev-topic="${revEsc(topic.topic_id)}" data-rev-title="${revEsc(topic.title || topic.topic_id)}" data-rev-coverage="${revEsc(coverage.level || "thin")}" data-rev-papers="${coverage.papers || 0}" data-rev-practice="${Number(coverage.drills || 0) + Number(coverage.cases || 0)}" title="${revEsc(`${topic.topic_id} · ${summary || "No activity listed"}`)}" aria-label="Study ${revEsc(topic.title || topic.topic_id)}. ${revEsc(summary || "No activity listed")}"><span>${revEsc(topic.title || topic.topic_id)}</span><small>${revEsc(formatLabel)}</small></button>`;
    }).join("");
    const levelCoverage = topics.reduce((sum, topic) => {
      const item = coverageById.get(topic.topic_id) || {};
      for (const key of ["cards", "drills", "cases", "exams", "papers"]) sum[key] += Number(item[key] || 0);
      return sum;
    }, { cards: 0, drills: 0, cases: 0, exams: 0, papers: 0 });
    const levelAssets = revTopicActivitySummary(levelCoverage);
    return `<article class="rev-level-card ${state}">
      <div class="rev-level-top"><span class="rev-level-icon" aria-hidden="true">${level.icon}</span><span class="rev-level-number">${revEsc(level.courseLabel)}</span><span class="rev-level-state">${allStrong ? "✓ Strong" : levelIndex === recommendedLevel ? "Your next step" : seen ? "In progress" : "Ready"}</span></div>
      <h3>${safeTitle}</h3><p>${revEsc(level.subtitle)}</p><div class="rev-level-syllabus" aria-label="Topics in this level">${syllabus}</div><p class="rev-level-coverage">${revEsc(levelAssets)}</p>
      <div class="rev-level-bottom"><span class="rev-level-topics">${revEsc(label)}</span><button class="rev-level-open" type="button" data-rev-topic="${nextTopic ? revEsc(nextTopic.topic_id) : ""}" data-rev-title="${safeTitle}" aria-label="Study ${safeTitle}: ${revEsc(topicLabel)}">Study this level <span aria-hidden="true">→</span></button></div>
    </article>`;
  });
  box.innerHTML = levels.join("");
  box.querySelectorAll("[data-rev-topic]").forEach((button) => button.addEventListener("click", () => {
    const topicId = button.dataset.revTopic;
    if (topicId) revPrepareTopicLesson(topicId, button.dataset.revTitle);
    revSelectTab("revLearn");
    revEl("revTutorInput").focus({ preventScroll: true });
  }));
  revFilterRoadmap();
}

function revTopicActivitySummary(topic) {
  if (!topic) return "";
  const parts = [];
  const count = (amount, singular, plural = `${singular}s`) => `${amount} ${amount === 1 ? singular : plural}`;
  if (topic.cards) parts.push(count(topic.cards, "flashcard"));
  if (topic.drills) parts.push(count(topic.drills, "exercise"));
  if (topic.cases) parts.push(count(topic.cases, "case"));
  if (topic.exams) parts.push(count(topic.exams, "exam-bank question"));
  if (topic.papers) parts.push(count(topic.papers, "past-paper question"));
  return parts.join(" · ");
}

function revFilterRoadmap() {
  const query = revEl("revTopicSearch").value.trim().toLowerCase();
  const filter = revEl("revTopicFilter").value;
  let visible = 0;
  document.querySelectorAll(".rev-syllabus-chip").forEach((button) => {
    const matchesText = !query || `${button.textContent} ${button.dataset.revTitle} ${button.dataset.revTopic}`.toLowerCase().includes(query);
    const matchesFilter = filter === "all" ||
      (filter === "more-practice" && button.dataset.revCoverage !== "full") ||
      (filter === "past-paper" && Number(button.dataset.revPapers) > 0) ||
      (filter === "drills" && Number(button.dataset.revPractice) > 0);
    button.hidden = !(matchesText && matchesFilter);
    if (!button.hidden) visible += 1;
  });
  document.querySelectorAll(".rev-level-card").forEach((card) => {
    card.hidden = !card.querySelector(".rev-syllabus-chip:not([hidden])");
  });
  revEl("revTopicEmpty").hidden = visible > 0;
  revEl("revTopicResultCount").textContent = `${visible} ${visible === 1 ? "topic" : "topics"}`;
}

function revPrepareTopicLesson(topicId, title) {
  revEl("revTutorTopic").value = topicId;
  revEl("revDrillTopic").value = topicId;
  const input = revEl("revTutorInput");
  input.placeholder = `Ask a question about ${title || topicId}, or ask for a beginner-friendly explanation…`;
  if (!input.value.trim()) {
    input.value = `Teach me ${title || topicId} from first principles using my Venture Capital course materials. Explain it step by step in clear English, show a worked example if my course supports one, then ask me one short question to check my understanding.`;
  }
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
  const input = revEl("revTutorInput");
  const message = input.value.trim();
  if (!message) return;
  const mode = check ? "correct" : rev.tutorMode;
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
  } catch (error) {
    thinking.remove();
    revPushChat("ai", revMarkdown(`Request failed: ${error.message}`), {
      kind: "offline", label: "Error",
    });
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
  try {
    const data = await revApi(`/api/vc/review?minutes=${mode === "long" ? 30 : 10}&mode=${encodeURIComponent(mode)}`);
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
        <h3>Session complete</h3>
        <p>${revEsc(JSON.stringify(session.summary || {}))}</p>
        <button class="secondary-button" type="button" onclick="window.revRestartCards()">New session</button>
      </div>`;
    return;
  }
  const card = session.current;
  area.innerHTML = `
    <div class="rev-card" data-card-id="${revEsc(card.card_id)}">
      <header>
        <span class="rev-chip static">${revEsc(card.topic_id)}</span>
        <span class="quiet-status">${session.done + 1}/${session.total} · ${revEsc(card.reason || "")}</span>
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
      <p class="rev-drill-prompt">${revEsc(drill.prompt)}</p>
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
          <span class="rev-badge verified">Verified</span>
          ${ok ? "Correct." : `Not correct — ${revEsc(result.message || "")}`}
          ${result.diagnostic ? ` <em>(${revEsc(result.diagnostic)})</em>` : ""}
        </p>
        ${ok || !steps ? "" : `<ol class="rev-steps">${steps}</ol>`}
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
    <label class="rev-case-question" for="revCaseAnswer${index}">
      <span><b>${String(index + 1).padStart(2, "0")}</b>${revEsc(question.prompt)}</span>
      <textarea id="revCaseAnswer${index}" data-case-question="${revEsc(question.question_id)}" rows="3" maxlength="4000" placeholder="Show your calculation and explain your reasoning…"></textarea>
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
  const detail = card.querySelector(".rev-paper-detail");
  if (detail) { detail.remove(); return; }
  try {
    const data = await revApi(`/api/vc/papers/${year}${solutions ? "?solutions=true" : ""}`);
    const paper = data.paper;
    const html = paper.questions.map((q) => {
      let answerLine = "";
      if (solutions && q.answer) {
        // Honesty rule: the official files carry no marked MCQ answers, so
        // MCQ letters are a derived key; worked/numeric solutions are official.
        const isDerivedKey = q.kind === "mcq";
        answerLine = `<p class="rev-paper-answer"><span class="rev-badge ${isDerivedKey ? "ai" : "verified"}">${isDerivedKey ? "Derived key" : "Official"}</span> ${revEsc(q.answer)}${q.solution ? ` — ${revEsc(q.solution)}` : ""}</p>`;
      }
      const choices = (q.choices || []).map((c) =>
        `<li>${revEsc(c.label)}. ${revEsc(c.text)}</li>`).join("");
      return `<li><strong>${revEsc(q.number)}</strong> (${q.points} pts) ${revEsc(q.prompt)}
        ${choices ? `<ol type="A" class="rev-choices">${choices}</ol>` : ""}${answerLine}</li>`;
    }).join("");
    const notice = solutions && paper.notice
      ? `<p class="rev-paper-notice">${revEsc(paper.notice)}</p>`
      : "";
    card.insertAdjacentHTML("beforeend",
      `<div class="rev-paper-detail"><span class="rev-badge ${solutions ? "verified" : "ai"}">${solutions ? "Solutions &amp; answer key" : "Official exam"}</span>${notice}<ol>${html}</ol></div>`);
  } catch (error) {
    card.insertAdjacentHTML("beforeend", `<p class="quiet-status">${revEsc(error.message)}</p>`);
  }
}

async function revPracticePaper(year, card) {
  const detail = card.querySelector(".rev-paper-detail");
  if (detail) { detail.remove(); return; }
  try {
    const data = await revApi(`/api/vc/papers/${year}?solutions=true`);
    const paper = data.paper;
    const fields = paper.questions
      .filter((q) => q.kind === "mcq" || q.kind === "numeric")
      .map((q) => `
        <label class="rev-paper-field">
          <span>${revEsc(q.number)} — ${revEsc(q.prompt.slice(0, 140))}${q.prompt.length > 140 ? "…" : ""} (${q.points} pts)</span>
          ${q.kind === "mcq"
            ? `<input type="text" data-qid="${revEsc(q.id)}" maxlength="8" placeholder="letter">`
            : `<input type="text" data-qid="${revEsc(q.id)}" inputmode="decimal" placeholder="number${q.unit ? " (" + revEsc(q.unit) + ")" : ""}">`}
        </label>`).join("");
    card.insertAdjacentHTML("beforeend", `
      <div class="rev-paper-detail">
        <p class="quiet-status">Answer the auto-graded items; open questions are self-assessed against the worked solutions. MCQ letters come from a derived answer key (the official file marks none), so use MCQ results as practice.</p>
        <form class="rev-paper-form">${fields}
          <button class="primary-button" type="submit">Grade my copy</button>
        </form>
        <div class="rev-paper-grade" hidden></div>
      </div>`);
    card.querySelector(".rev-paper-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const answers = {};
      card.querySelectorAll("[data-qid]").forEach((input) => {
        if (input.value.trim()) answers[input.dataset.qid] = input.value.trim();
      });
      try {
        const result = await revApi(`/api/vc/papers/${year}/grade`, {
          method: "POST",
          body: JSON.stringify({ year: Number(year), answers }),
        });
        const body = result.result;
        const box = card.querySelector(".rev-paper-grade");
        box.hidden = false;
        box.innerHTML = `
          <p class="rev-verdict ${body.auto_percent >= 60 ? "good" : "bad"}">
            <span class="rev-badge ai">Pack answer key</span>
            Auto-graded: ${body.auto_points}/${body.auto_max} (${body.auto_percent}%)
          </p>
          <p class="quiet-status">${revEsc(body.notice || "")}</p>
          ${paper.notice ? `<p class="rev-paper-notice">${revEsc(paper.notice)}</p>` : ""}`;
      } catch (error) {
        card.querySelector(".rev-paper-grade").hidden = false;
        card.querySelector(".rev-paper-grade").innerHTML = `<p class="quiet-status">${revEsc(error.message)}</p>`;
      }
    });
  } catch (error) {
    card.insertAdjacentHTML("beforeend", `<p class="quiet-status">${revEsc(error.message)}</p>`);
  }
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
    <p class="quiet-status">${exam.total_questions} questions · ${exam.total_points} points · answers are saved when you submit.</p>
    <ol class="rev-exam-list">
      ${exam.questions.map((q, index) => `
        <li class="rev-exam-q" data-qid="${revEsc(q.question_id)}">
          <header><span>#${index + 1}</span><span class="rev-chip static">${revEsc(q.topic_id)}</span><span>${q.points} pts</span></header>
          <p>${revEsc(q.question)}</p>
          ${q.choices ? `<ol type="A" class="rev-choices">${q.choices.map((c) => `<li>${revEsc(c)}</li>`).join("")}</ol>` : ""}
          <input type="text" autocomplete="off" placeholder="Your answer" aria-label="Answer for question ${index + 1}">
        </li>`).join("")}
    </ol>`;
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
    const radar = await revApi("/api/vc/radar");
    const statusLabel = { untested: "Not tested", weak: "Weak", learning: "Learning", strong: "Strong", mastered: "Mastered" };
    box.innerHTML = radar.topics.map((topic) => {
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
  try {
    const data = await revApi("/api/vc/next?minutes=30");
    const activity = data.activity;
    if (!activity) {
      const candidate = (rev.radar?.topics || []).find((topic) => topic.status === "weak") ||
        (rev.radar?.topics || []).find((topic) => topic.status === "untested");
      if (candidate) {
        const level = revPathLevels.find((item) => item.topics.includes(candidate.topic_id));
        revPrepareTopicLesson(candidate.topic_id, candidate.title || level?.title || candidate.topic_id);
        revSelectTab("revLearn");
        revEl("revTutorInput").focus({ preventScroll: true });
      } else {
        revSelectTab("revProgress");
      }
      return;
    }
    const kind = String(activity.kind || "");
    const topicId = activity.topic_id || activity.topic || "";
    let activityTopicTitle = topicId;
    if (topicId && revEl("revTutorTopic").querySelector(`option[value="${CSS.escape(topicId)}"]`)) {
      activityTopicTitle = rev.radar?.topics?.find((topic) => topic.topic_id === topicId)?.title || topicId;
      revPrepareTopicLesson(topicId, activityTopicTitle);
    }
    if (kind.includes("drill")) { revSelectTab("revPractice"); revDrawDrill(); return; }
    if (kind.includes("card") || kind.includes("review")) { revSelectTab("revMemorize"); revStartCards(); return; }
    if (kind.includes("exam") || kind.includes("paper")) { revSelectTab("revEvaluate"); return; }
    revSelectTab("revLearn");
    if (topicId) revEl("revTutorInput").focus({ preventScroll: true });
  } catch (error) {
    window.alert(`Could not load a recommendation: ${error.message}`);
  }
}

/* ------------------------------------------------------------- bootstrap */
function revBind() {
  document.querySelectorAll(".rev-tab").forEach((button) =>
    button.addEventListener("click", () => revSelectTab(button.dataset.revTab)));

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
  revEl("revTopicSearch").addEventListener("input", revFilterRoadmap);
  revEl("revTopicFilter").addEventListener("change", revFilterRoadmap);
  revLoadCases();
  revLoadPapers();
}

window.initRevisions = function initRevisions() {
  if (rev.initialized) { revLoadStatus(); return; }
  rev.initialized = true;
  revBind();
  revLoadStatus();
};

/* Deep link: #v5/revisionsView from the browser address bar. */
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { /* activation binds it */ });
}
