/* A local reading and practice workspace. No model call is made by this module. */
"use strict";
const vcStudio = { ready: false, loading: false, course: null, progress: null, lessonId: null, library: [], source: null };
const vcNode = (id) => document.getElementById(id);
const vcAllLessons = () => (vcStudio.course?.chapters || []).flatMap((chapter) => chapter.lessons);
function vcMessage(message) { const node = vcNode("vcStatusMessage"); node.textContent = message; node.hidden = !message; }
function vcStored(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; } }
function vcSave(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* optional preference storage */ } }

function vcRefreshProgress() {
  const progress = vcStudio.progress;
  if (!progress) return;
  vcNode("vcReadCount").textContent = `${progress.read} / ${progress.total}`;
  vcNode("vcReadProgress").max = progress.total;
  vcNode("vcReadProgress").value = progress.read;
  vcNode("vcCheckpointCount").textContent = `${progress.passed} checkpoints passed`;
  vcNode("vcReviewCount").textContent = `${progress.review_later.length} to revisit`;
  const next = vcRecommendedLesson();
  if (next) {
    vcNode("vcNextTitle").textContent = next.title;
    const chapter = vcStudio.course.chapters.find((item) => item.id === next.chapter_id);
    vcNode("vcNextDescription").textContent = `${chapter.title} · about ${next.minutes} minutes · original pages ${next.pages[0]}–${next.pages[1]}`;
    vcNode("revStartNow").innerHTML = `${progress.read ? "Continue learning" : "Start learning"} <span aria-hidden="true">→</span>`;
  }
  vcRenderContents();
}
function vcRecommendedLesson() {
  const lessons = vcAllLessons();
  const state = vcStudio.progress?.lessons || {};
  const last = lessons.find((lesson) => lesson.id === vcStudio.progress?.last_lesson && !state[lesson.id]?.read_at);
  return last || lessons.find((lesson) => !state[lesson.id]?.read_at) || lessons.find((lesson) => state[lesson.id]?.review_later) || lessons[0];
}
function vcRenderContents() {
  const normalise = (text) => text.toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const query = normalise(vcNode("vcLessonSearch").value).split(/\s+/).filter(Boolean);
  const onlyReview = vcNode("vcOnlyReview").checked;
  let matches = 0;
  vcNode("vcChapterList").innerHTML = vcStudio.course.chapters.map((chapter, index) => {
    const lessons = chapter.lessons.filter((lesson) => {
      const state = vcStudio.progress.lessons[lesson.id] || {};
      return (!onlyReview || state.review_later) && (!query.length || query.every((word) => normalise(`${chapter.title} ${lesson.title} ${lesson.why} ${lesson.key_points.join(" ")} ${lesson.explain.join(" ")} ${lesson.formula} ${lesson.example.context} ${lesson.trap}`).includes(word)));
    });
    matches += lessons.length;
    if (!lessons.length) return "";
    const studied = chapter.lessons.filter((lesson) => vcStudio.progress.lessons[lesson.id]?.read_at).length;
    const current = chapter.lessons.some((lesson) => lesson.id === vcStudio.lessonId);
    return `<details class="vc-chapter" ${current || query.length || onlyReview ? "open" : ""}><summary><span class="vc-chapter-number">${index + 1}</span><span>${revEsc(chapter.title)}<small>${studied}/${chapter.lessons.length} studied</small></span></summary><div class="vc-chapter-lessons">${lessons.map((lesson) => {
      const state = vcStudio.progress.lessons[lesson.id] || {};
      return `<button type="button" data-course-lesson="${revEsc(lesson.id)}" ${lesson.id === vcStudio.lessonId ? 'aria-current="page"' : ""}><span class="vc-lesson-dot ${state.last_score >= 80 ? "checked" : state.read_at ? "read" : ""}" aria-label="${state.last_score >= 80 ? "Checkpoint passed" : state.read_at ? "Studied" : "Not yet studied"}">${state.last_score >= 80 ? "✓" : state.read_at ? "•" : ""}</span><span>${revEsc(lesson.title)}</span>${state.review_later ? '<span class="vc-bookmark" aria-label="In your review list">↺</span>' : ""}</button>`;
    }).join("")}</div></details>`;
  }).join("") || '<p class="quiet-status">No matching lessons. Try another concept or clear the review filter.</p>';
  vcNode("vcChapterList").querySelectorAll("[data-course-lesson]").forEach((button) => button.addEventListener("click", () => vcOpenLesson(button.dataset.courseLesson, true)));
  vcNode("vcChapterList").setAttribute("aria-label", `Course contents: ${matches} matching lessons`);
}
function vcDiagram(kind) {
  const node = (label, description) => `<div><b>${label}</b><small>${description}</small></div>`;
  if (kind === "valuation") return `<div class="vc-illustration vc-value-diagram" role="img" aria-label="Eight million pre-money plus two million new investment equals ten million post-money"><div><span>$8m</span><small>Pre-money</small></div><b>+</b><div><span>$2m</span><small>New investment</small></div><b>=</b><div><span>$10m</span><small>Post-money</small></div></div>`;
  if (kind === "matrix") return `<div class="vc-matrix" aria-label="Venture evaluation matrix"><span></span><b>Customer</b><b>Company</b><b>Entrepreneur</b><b>Value</b><span>Need</span><span>Solution</span><span>Team</span><b>Industry</b><span>Market</span><span>Competition</span><span>Network</span><b>Strategy</b><span>Sales</span><span>Production</span><span>Organisation</span></div>`;
  if (kind === "process") return `<div class="vc-illustration vc-flow">${node("Fit", "Find the right partner")}${node("Invest", "Design the deal")}${node("Ride", "Build and govern")}${node("Exit", "Realise the investment")}</div>`;
  if (kind === "funding") return `<div class="vc-illustration vc-flow">${node("LPs", "Commit capital")}${node("VC fund", "Select and support")}${node("Startups", "Build and scale")}</div>`;
  if (kind === "dilution") return `<div class="vc-illustration vc-flow">${node("Starting stake", "Before new financing")}${node("× (1 − dilution)", "Apply each round")}${node("Remaining stake", "Check the final share base")}</div>`;
  if (kind === "waterfall") return `<div class="vc-illustration vc-flow">${node("Preferred rights", "Calculate the contractual payout")}${node("Conversion", "Calculate common-equity value")}${node("Compare", "Apply participation, cap and thresholds")}</div>`;
  return "";
}
function vcRenderLesson() {
  const lessons = vcAllLessons();
  const lesson = lessons.find((item) => item.id === vcStudio.lessonId);
  if (!lesson) return;
  const chapter = vcStudio.course.chapters.find((item) => item.id === lesson.chapter_id);
  const index = lessons.indexOf(lesson);
  const state = vcStudio.progress.lessons[lesson.id] || {};
  const questions = lesson.quiz.map((question, i) => `<fieldset class="vc-check-question"><legend><span>${i + 1}</span>${revEsc(question.prompt)}</legend>${question.kind === "mcq" ? `<div class="vc-mcq-options">${question.choices.map((choice, j) => `<label><input type="radio" name="${revEsc(question.id)}" value="${j}" required><span class="vc-choice-letter" aria-hidden="true">${String.fromCharCode(65 + j)}</span><span class="vc-choice-text">${revEsc(choice)}</span></label>`).join("")}</div>` : `<label class="vc-number-answer"><input name="${revEsc(question.id)}" inputmode="decimal" autocomplete="off" placeholder="Your answer" required><span>${revEsc(question.unit || "")}</span></label>`}</fieldset>`).join("");
  vcNode("vcLesson").innerHTML = `<div class="vc-lesson-topline"><span>CHAPTER ${vcStudio.course.chapters.indexOf(chapter) + 1} · LESSON ${index + 1} OF ${lessons.length}</span><button type="button" class="vc-quiet-button" data-print-lesson>Print lesson</button></div><h2 class="vc-lesson-title" tabindex="-1">${revEsc(lesson.title)}</h2><p class="vc-lesson-objective">${revEsc(lesson.why)}</p><div class="vc-lesson-meta"><span>About ${lesson.minutes} min</span><button type="button" data-open-lesson-source>Course pp. ${lesson.pages[0]}–${lesson.pages[1]} ↗</button>${state.last_score != null ? `<span>Last checkpoint: ${state.last_score}%</span>` : ""}</div>
    <section id="vcCoreExplanation" class="vc-lesson-section"><p class="vc-mini-label">FIRST, UNDERSTAND THE IDEA</p>${lesson.explain.map((paragraph) => `<p>${revEsc(paragraph)}</p>`).join("")}${vcDiagram(lesson.diagram)}${lesson.formula ? `<div class="vc-formula"><span>THE RELATIONSHIP TO REMEMBER</span><p>${revEsc(lesson.formula)}</p></div>` : ""}<h3>What to take away</h3><ul class="vc-takeaways">${lesson.key_points.map((point) => `<li>${revEsc(point)}</li>`).join("")}</ul></section>
    <section class="vc-worked-example"><div class="vc-example-heading"><span class="vc-example-symbol" aria-hidden="true">↗</span><div><p class="vc-mini-label">SEE IT IN ACTION</p><h3>${revEsc(lesson.example.label)}</h3></div></div><p>${revEsc(lesson.example.context)}</p><ol>${lesson.example.steps.map((step) => `<li>${revEsc(step)}</li>`).join("")}</ol><div class="vc-example-result"><b>The result</b><span>${revEsc(lesson.example.result)}</span></div></section>
    <aside class="vc-trap"><b>A trap to avoid</b><p>${revEsc(lesson.trap)}</p></aside>
    <section class="vc-checkpoint" id="vcCurrentCheckpoint"><p class="vc-mini-label">NOW, TRY WITHOUT LOOKING BACK</p><h3>Your two-question checkpoint</h3><p>Use your own reasoning first. The correction explains the method after you submit.</p><form id="vcCheckpointForm">${questions}<button class="vc-primary" type="submit">Check my understanding</button></form><div id="vcCheckpointResult" class="vc-checkpoint-result" hidden></div></section>
    <section class="vc-lesson-finish"><h3>What would help you next?</h3><div class="vc-finish-actions"><button id="vcMarkRead" class="vc-primary" type="button">${state.read_at ? "✓ Studied" : "I've studied this lesson"}</button><button id="vcPracticeLesson" class="vc-secondary" type="button">Practise this concept</button><button id="vcReviewLesson" class="vc-secondary" type="button" aria-pressed="${!!state.review_later}">${state.review_later ? "✓ In my review list" : "Add to review list"}</button></div><div class="vc-extra-actions"><button id="vcAskLesson" class="vc-quiet-button" type="button">I need another explanation</button><button id="vcMorePractice" class="vc-quiet-button" type="button">More exercises & past papers →</button></div></section>
    <footer class="vc-lesson-footer"><button id="vcPreviousLesson" type="button" class="vc-quiet-button" ${index === 0 ? "disabled" : ""}>← Previous lesson</button><span>${index + 1} / ${lessons.length}</span><button id="vcNextLesson" type="button" class="vc-quiet-button" ${index === lessons.length - 1 ? "disabled" : ""}>Next lesson →</button></footer>`;
  vcNode("vcLesson").querySelector("[data-open-lesson-source]").addEventListener("click", () => vcOpenSource(chapter.source_id, chapter.filename, lesson.pages[0]));
  vcNode("vcLesson").querySelector("[data-print-lesson]").addEventListener("click", () => window.print());
  vcNode("vcMarkRead").addEventListener("click", async () => { const alreadyRead = !!vcStudio.progress.lessons[lesson.id]?.read_at; if (await vcSetLessonState(alreadyRead ? "unread" : "read")) { vcNode("vcMarkRead").textContent = alreadyRead ? "I've studied this lesson" : "✓ Studied"; vcMessage(alreadyRead ? "Study mark removed. Your checkpoint score is unchanged." : "Lesson marked as studied. Your checkpoint score is tracked separately."); } });
  vcNode("vcReviewLesson").addEventListener("click", async () => {
    const action = vcStudio.progress.lessons[lesson.id]?.review_later ? "clear-review" : "revisit";
    if (await vcSetLessonState(action)) { const selected = !!vcStudio.progress.lessons[lesson.id]?.review_later; vcNode("vcReviewLesson").textContent = selected ? "✓ In my review list" : "Add to review list"; vcNode("vcReviewLesson").setAttribute("aria-pressed", String(selected)); }
  });
  vcNode("vcPracticeLesson").addEventListener("click", () => { vcNode("vcCurrentCheckpoint").scrollIntoView({ behavior: "smooth", block: "start" }); vcNode("vcCheckpointForm").querySelector("input")?.focus({ preventScroll: true }); });
  vcNode("vcAskLesson").addEventListener("click", () => { revSelectTab("revLearn"); vcNode("revTutorTopic").value = lesson.topic_ids[0] || ""; vcNode("revTutorInput").value = `I am studying ${lesson.title}. Explain the key idea again in simpler English, using the relevant course materials. Ask me one small question at a time.`; vcNode("revTutorInput").focus(); });
  vcNode("vcMorePractice").addEventListener("click", () => { const available = (rev.topics || []).find((item) => lesson.topic_ids.includes(item.topic_id) && item.has_drill); if (available) vcNode("revDrillTopic").value = available.topic_id; revSelectTab("revPractice"); vcSetTrainingMode(available ? "drills" : "papers"); document.querySelector(".vc-training-switch").scrollIntoView({ behavior: "smooth", block: "start" }); });
  vcNode("vcPreviousLesson").addEventListener("click", () => { if (index > 0) vcOpenLesson(lessons[index - 1].id, true); });
  vcNode("vcNextLesson").addEventListener("click", () => { if (index < lessons.length - 1) vcOpenLesson(lessons[index + 1].id, true); });
  vcNode("vcCheckpointForm").addEventListener("submit", vcSubmitCheckpoint);
}
async function vcOpenLesson(id, scroll = false) {
  if (!vcAllLessons().some((lesson) => lesson.id === id)) return;
  vcStudio.lessonId = id;
  revSelectTab("revCourse");
  vcRenderContents(); vcRenderLesson();
  if (window.matchMedia("(max-width: 760px)").matches) { vcNode("vcContentsBody").classList.remove("expanded"); vcNode("vcToggleContents").setAttribute("aria-expanded", "false"); }
  if (scroll) { vcNode("vcLesson").scrollIntoView({ block: "start", behavior: "smooth" }); vcNode("vcLesson").querySelector("h2").focus({ preventScroll: true }); }
  await vcSetLessonState("opened");
}
async function vcSetLessonState(action) {
  try {
    vcStudio.progress = await revApi("/api/vc/course/state", { method: "POST", body: JSON.stringify({ lesson_id: vcStudio.lessonId, action }) });
    vcRefreshProgress(); return true;
  } catch (error) { vcMessage(`Could not save this step: ${error.message}. You can keep reading.`); return false; }
}
async function vcSubmitCheckpoint(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const lesson = vcAllLessons().find((item) => item.id === vcStudio.lessonId);
  const lessonId = lesson.id;
  const answers = Object.fromEntries(new FormData(form).entries());
  submit.disabled = true;
  try {
    const result = await revApi("/api/vc/course/quiz", { method: "POST", body: JSON.stringify({ lesson_id: lessonId, answers }) });
    vcMessage("");
    vcStudio.progress = result.progress; vcRefreshProgress();
    if (vcStudio.lessonId !== lessonId) return;
    const box = vcNode("vcCheckpointResult");
    box.hidden = false;
    box.innerHTML = `<div class="vc-result-title"><strong>${result.score}%</strong><div><h4>${result.passed ? "You have the key idea." : "Now you know what to revisit."}</h4><p>${result.passed ? "Try explaining the method without the example before moving on." : "Read the correction, then try the checkpoint again in a few minutes."}</p></div></div>${result.results.map((item) => `<div class="vc-answer-feedback ${item.correct ? "correct" : "revisit"}"><b>${item.correct ? "✓ Correct" : "↗ Revisit this step"}</b><p>${revEsc(item.explanation)}</p>${item.correct ? "" : `<small>Expected: ${revEsc(item.expected)}</small>`}</div>`).join("")}<button type="button" id="vcBackToExplanation" class="vc-quiet-button">↑ Read the explanation again</button>`;
    vcNode("vcBackToExplanation").addEventListener("click", () => vcNode("vcCoreExplanation").scrollIntoView({ block: "start", behavior: "smooth" }));
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) { vcMessage(`The checkpoint could not be checked: ${error.message}`); } finally { submit.disabled = false; }
}
function vcSetTrainingMode(mode) {
  document.querySelectorAll("[data-training-mode]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.trainingMode === mode)));
  document.querySelectorAll("[data-training-panel]").forEach((panel) => { panel.hidden = panel.dataset.trainingPanel !== mode; });
}
async function vcOpenLibrary() {
  vcNode("vcLibraryDialog").showModal();
  try {
    const library = await revApi("/api/vc/course/library");
    vcStudio.library = library.sources;
    const pages = library.sources.reduce((sum, source) => sum + (source.pages || 0), 0);
    vcNode("vcLibrarySummary").textContent = `${library.sources.length} local files · ${pages.toLocaleString("en")} PDF pages · ${library.primary_pages_mapped} main lecture pages mapped to lessons. Supplementary readings and workbooks remain available in full.`;
    vcRenderLibrary();
  } catch (error) { vcNode("vcLibrarySummary").textContent = `Could not load the source folder: ${error.message}`; }
}
function vcRenderLibrary() {
  const query = vcNode("vcLibrarySearch").value.toLowerCase().trim();
  const files = vcStudio.library.filter((source) => !query || source.name.toLowerCase().includes(query));
  vcNode("vcLibraryList").innerHTML = files.map((source) => `<article class="vc-library-file"><span class="vc-file-type">${source.kind.toUpperCase()}</span><div><h3>${revEsc(source.name)}</h3><p>${source.primary ? "Main lecture · " : ""}${source.pages ? `${source.pages} pages` : `${source.sheets?.length || 0} sheets`}</p></div><button class="vc-secondary" type="button" data-source-id="${source.id}">Read</button></article>`).join("") || '<p class="quiet-status">No source files match your search.</p>';
  vcNode("vcLibraryList").querySelectorAll("[data-source-id]").forEach((button) => button.addEventListener("click", () => {
    const source = vcStudio.library.find((item) => item.id === button.dataset.sourceId);
    if (source) vcOpenSource(source.id, source.name, 1, source.kind);
  }));
}
async function vcOpenSource(id, name, page = 1, kind = "pdf") {
  vcStudio.source = { id, name, page, pages: null, kind };
  vcNode("vcSourceTitle").textContent = name;
  vcNode("vcOriginalLink").href = `/api/vc/course/source/${encodeURIComponent(id)}`;
  vcNode("vcSourcePageNumber").textContent = "Loading…";
  vcNode("vcSourceDialog").showModal();
  if (kind === "xlsx") {
    vcNode("vcPagePrevious").disabled = true; vcNode("vcPageNext").disabled = true;
    try {
      const data = await revApi(`/api/vc/course/workbook/${id}`);
      vcNode("vcSourcePageNumber").textContent = `${data.sheets.length} sheets`;
      vcRenderWorkbook(data);
    } catch (error) { vcNode("vcSourceBody").textContent = error.message; }
  } else await vcLoadSourcePage(page);
}
function vcRenderWorkbook(data, showFormulas = false) {
  vcNode("vcSourceBody").innerHTML = `<p class="quiet-status">${revEsc(data.notice)}</p><label class="vc-workbook-toggle"><input id="vcWorkbookFormulas" type="checkbox" ${showFormulas ? "checked" : ""}> Show formulas instead of saved values</label>${data.sheets.map((sheet) => `<details class="vc-sheet" open><summary>${revEsc(sheet.name)} · ${sheet.total_rows} rows × ${sheet.total_columns} columns${sheet.truncated ? " · preview limited" : " · complete table"}</summary><div class="vc-table-scroll"><table><tbody>${(showFormulas ? sheet.formula_rows : sheet.rows).map((row, i) => `<tr><th>${sheet.row_numbers[i]}</th>${row.map((cell) => `<td>${revEsc(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`).join("")}`;
  vcNode("vcWorkbookFormulas").addEventListener("change", (event) => vcRenderWorkbook(data, event.target.checked));
}
async function vcLoadSourcePage(page) {
  const source = vcStudio.source;
  vcNode("vcSourceBody").innerHTML = '<p class="quiet-status">Opening the original page…</p>';
  vcNode("vcPagePrevious").disabled = true; vcNode("vcPageNext").disabled = true;
  try {
    const data = await revApi(`/api/vc/course/source/${source.id}/page/${page}`);
    if (vcStudio.source !== source) return;
    source.page = page; source.pages = data.pages;
    vcNode("vcSourcePageNumber").textContent = `Page ${page} of ${data.pages}`;
    vcNode("vcPagePrevious").disabled = page <= 1; vcNode("vcPageNext").disabled = page >= data.pages;
    vcNode("vcSourceBody").innerHTML = `<img class="vc-source-page" src="${revEsc(data.image_url)}" alt="Original course page ${page}: ${revEsc(source.name)}"><details class="vc-source-transcript"><summary>Read the page as text</summary><pre>${revEsc(data.text || "This page contains a chart or image. Use the original page above.")}</pre></details>`;
    vcNode("vcSourceBody").querySelector("img").addEventListener("error", (event) => { event.target.hidden = true; vcNode("vcSourceBody").querySelector("details").open = true; });
  } catch (error) { vcNode("vcSourceBody").textContent = `Could not open the page: ${error.message}. Use “Open original file” above.`; }
}
window.vcStudioContinue = function () { if (!vcStudio.ready) return; const lesson = vcRecommendedLesson(); if (lesson) vcOpenLesson(lesson.id, true); };
window.initVcStudio = async function () {
  if (vcStudio.ready || vcStudio.loading) return;
  vcStudio.loading = true;
  try {
    const data = await revApi("/api/vc/course");
    vcStudio.course = data.course; vcStudio.progress = data.progress;
    vcStudio.lessonId = data.progress.last_lesson && vcAllLessons().some((lesson) => lesson.id === data.progress.last_lesson) ? data.progress.last_lesson : vcAllLessons()[0].id;
    vcStudio.ready = true; vcRefreshProgress(); vcRenderLesson();
    vcNode("vcLessonSearch").addEventListener("input", vcRenderContents);
    vcNode("vcOnlyReview").addEventListener("change", vcRenderContents);
    vcNode("vcOpenLibrary").addEventListener("click", vcOpenLibrary);
    vcNode("vcLibrarySearch").addEventListener("input", vcRenderLibrary);
    document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => vcNode(button.dataset.closeDialog).close()));
    vcNode("vcPagePrevious").addEventListener("click", () => { if (vcStudio.source?.page > 1) vcLoadSourcePage(vcStudio.source.page - 1); });
    vcNode("vcPageNext").addEventListener("click", () => { if (vcStudio.source?.page < vcStudio.source?.pages) vcLoadSourcePage(vcStudio.source.page + 1); });
    document.querySelectorAll("[data-training-mode]").forEach((button) => button.addEventListener("click", () => vcSetTrainingMode(button.dataset.trainingMode)));
    vcNode("vcToggleContents").addEventListener("click", () => { const open = vcNode("vcContentsBody").classList.toggle("expanded"); vcNode("vcToggleContents").setAttribute("aria-expanded", String(open)); });
    const focus = vcStored("nage-vc-focus", "off") === "on";
    vcNode("revisionsView").classList.toggle("vc-focus-on", focus);
    vcNode("vcFocusToggle").setAttribute("aria-pressed", String(focus)); vcNode("vcFocusToggle").textContent = focus ? "Exit focus mode" : "Focus mode";
    vcNode("vcFocusToggle").addEventListener("click", () => { const enabled = vcNode("revisionsView").classList.toggle("vc-focus-on"); vcNode("vcFocusToggle").setAttribute("aria-pressed", String(enabled)); vcNode("vcFocusToggle").textContent = enabled ? "Exit focus mode" : "Focus mode"; vcSave("nage-vc-focus", enabled ? "on" : "off"); });
  } catch (error) { vcMessage(`Your course could not load: ${error.message}. Reload this page to try again.`); } finally { vcStudio.loading = false; }
};
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { if (!vcNode("revisionsView").hidden) window.initVcStudio(); });
else if (!vcNode("revisionsView").hidden) window.initVcStudio();
