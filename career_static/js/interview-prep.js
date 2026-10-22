"use strict";

/*
 * SPEC-010 — « Assistant d'entretien ciblé ».
 *
 * Le panneau transforme une offre locale et ton profil local en une
 * préparation vérifiable : questions techniques, comportementales et d'écart,
 * questions à poser au recruteur, fiche entreprise limitée à ce que l'offre
 * dit, puis une simulation chronométrée avec un retour structuré.
 *
 * Tout est local et déterministe : aucune donnée n'est envoyée à un service
 * externe, aucune affirmation sur l'entreprise n'est inventée, et le retour
 * décrit la réponse face à l'exercice — jamais une probabilité de recrutement.
 *
 * Ce module ne touche pas au DOM au chargement : il expose des fonctions
 * appelées depuis career_static/career.js (accroche loadCoach).
 */

const interviewPrepState = {
  session: null,
  activeTab: "technical",
  currentQuestionId: null,
  timerId: null,
  startedAt: 0,
  limitSeconds: 0,
};

const interviewPrepTabs = ["technical", "behavioral", "gap", "recruiter", "company"];

const interviewPrepCategoryKey = {
  technical: "technical_questions",
  behavioral: "behavioral_questions",
  gap: "gap_questions",
};

const interviewPrepDifficultyLabels = {
  easy: "Accessible",
  medium: "Intermédiaire",
  hard: "Avancé",
};

const interviewPrepScoreLabels = {
  excellent: "Excellente",
  good: "Bonne",
  needs_improvement: "À retravailler",
  insufficient: "Insuffisante",
};

function interviewPrepElement(selector) {
  return document.querySelector(selector);
}

function interviewPrepFormatSeconds(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function interviewPrepPanelFor(tab) {
  return interviewPrepElement(`#interview-prep-panel-${tab}`);
}

function interviewPrepStopTimer() {
  if (interviewPrepState.timerId !== null) {
    window.clearInterval(interviewPrepState.timerId);
    interviewPrepState.timerId = null;
  }
}

function interviewPrepTick() {
  const elapsed = Math.round((Date.now() - interviewPrepState.startedAt) / 1000);
  const elapsedNode = interviewPrepElement("#interview-prep-timer");
  if (elapsedNode) elapsedNode.textContent = interviewPrepFormatSeconds(elapsed);
  const limit = interviewPrepState.limitSeconds;
  const alertNode = interviewPrepElement("#interview-prep-timer-alert");
  if (alertNode) {
    const overrun = limit > 0 && elapsed > limit;
    alertNode.hidden = !overrun;
    if (overrun) {
      alertNode.textContent = `Temps dépassé : ${interviewPrepFormatSeconds(elapsed - limit)} au-delà du temps conseillé.`;
    }
  }
}

function interviewPrepStartTimer(seconds) {
  interviewPrepStopTimer();
  interviewPrepState.limitSeconds = Math.max(0, Number(seconds) || 0);
  interviewPrepState.startedAt = Date.now();
  const limitNode = interviewPrepElement("#interview-prep-timer-limit");
  if (limitNode) limitNode.textContent = interviewPrepFormatSeconds(interviewPrepState.limitSeconds);
  interviewPrepTick();
  interviewPrepState.timerId = window.setInterval(interviewPrepTick, 1000);
}

function interviewPrepQuestionCard(question) {
  const card = make("article", "", "interview-prep-question");
  const head = make("div", "", "interview-prep-question-head");
  head.append(make("span", interviewPrepDifficultyLabels[question.difficulty] || question.difficulty, "job-chip"));
  head.append(make("span", `Temps conseillé : ${interviewPrepFormatSeconds(question.time_estimate_seconds)}`, "job-chip"));
  if (question.bank_label) head.append(make("span", question.bank_label, "job-chip"));
  card.append(head);
  card.append(make("p", question.question, "interview-prep-question-text"));
  if (question.related_requirement) {
    card.append(make("p", `Exigence liée : ${question.related_requirement}`, "application-meta"));
  }
  if ((question.evidence_quotes || []).length) {
    card.append(make("p", `Preuve de profil : « ${question.evidence_quotes[0]} »`, "application-meta"));
  }
  const elementsList = make("ul", "", "interview-prep-expected");
  (question.expected_elements || []).forEach((element) => elementsList.append(make("li", element)));
  card.append(elementsList);
  if (question.pedagogical_source) {
    card.append(make("p", `Source pédagogique : ${question.pedagogical_source}`, "application-meta"));
  }
  const actions = make("div", "", "inline-actions");
  const train = make("button", "S’entraîner sur cette question", "primary-button");
  train.type = "button";
  train.addEventListener("click", () => interviewPrepStartSimulation(question));
  actions.append(train);
  card.append(actions);
  return card;
}

function interviewPrepRenderQuestions(tab) {
  const panel = interviewPrepPanelFor(tab);
  if (!panel) return;
  panel.replaceChildren();
  const session = interviewPrepState.session;
  if (!session) return;
  const questions = session[interviewPrepCategoryKey[tab]] || [];
  if (!questions.length) {
    panel.append(make("p", "Aucune question dans cette catégorie pour cette offre.", "empty-state compact-empty"));
    return;
  }
  questions.forEach((question) => panel.append(interviewPrepQuestionCard(question)));
}

function interviewPrepRenderRecruiter() {
  const panel = interviewPrepPanelFor("recruiter");
  if (!panel) return;
  panel.replaceChildren();
  const session = interviewPrepState.session;
  if (!session) return;
  const questions = session.recruiter_questions || [];
  if (!questions.length) {
    panel.append(make("p", "Aucune question préparée.", "empty-state compact-empty"));
    return;
  }
  const list = make("ul", "", "interview-prep-list");
  questions.forEach((question) => list.append(make("li", question)));
  panel.append(list);
}

function interviewPrepRenderCompany() {
  const panel = interviewPrepPanelFor("company");
  if (!panel) return;
  panel.replaceChildren();
  const session = interviewPrepState.session;
  if (!session) return;
  const factsheet = session.company_factsheet || {};
  const rows = [
    ["Entreprise", factsheet.name || "Non renseignée"],
    ["Secteur", factsheet.sector || "Non renseigné"],
    ["Taille", factsheet.size || "Non renseignée par l’offre"],
    [
      "Actualités",
      (factsheet.recent_news || []).length
        ? factsheet.recent_news.join(" · ")
        : "Aucune donnée locale disponible : cet outil ne consulte aucun service externe pour cette section.",
    ],
    ["Mots-clés de culture", (factsheet.culture_keywords || []).join(", ") || "aucun mot-clé détecté dans l’offre"],
    [
      "Process d’entretien",
      factsheet.interview_process && factsheet.interview_process.length
        ? factsheet.interview_process.join(" · ")
        : "Non renseigné par l’offre.",
    ],
    ["Sources", (factsheet.sources || []).join(" · ")],
  ];
  const list = make("ul", "", "interview-prep-list");
  rows.forEach(([label, value]) => {
    const item = make("li", "", "interview-prep-fact");
    item.append(make("strong", label));
    item.append(make("span", value));
    list.append(item);
  });
  panel.append(list);
  const sensitive = session.sensitive_points || [];
  const sensitiveBlock = make("section", "", "interview-prep-sensitive");
  sensitiveBlock.append(make("h4", "Points sensibles du CV"));
  if (sensitive.length) {
    const sensitiveList = make("ul", "", "interview-prep-list");
    sensitive.forEach((point) => sensitiveList.append(make("li", point)));
    sensitiveBlock.append(sensitiveList);
  } else {
    sensitiveBlock.append(make("p", "Aucun point sensible détecté à partir des données locales.", "empty-state compact-empty"));
  }
  panel.append(sensitiveBlock);
}

function interviewPrepRenderTabs() {
  interviewPrepTabs.forEach((tab) => {
    const button = interviewPrepElement(`.interview-prep-tab[data-prep-tab="${tab}"]`);
    const panel = interviewPrepPanelFor(tab);
    if (button) {
      const active = tab === interviewPrepState.activeTab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    }
    if (panel) panel.hidden = tab !== interviewPrepState.activeTab;
  });
}

function interviewPrepSelectTab(tab) {
  if (!interviewPrepTabs.includes(tab)) return;
  interviewPrepState.activeTab = tab;
  interviewPrepRenderTabs();
  if (tab === "recruiter") interviewPrepRenderRecruiter();
  if (tab === "company") interviewPrepRenderCompany();
  if (interviewPrepCategoryKey[tab]) interviewPrepRenderQuestions(tab);
}

function interviewPrepRenderFeedback(feedback) {
  const box = interviewPrepElement("#interview-prep-feedback");
  if (!box) return;
  box.replaceChildren();
  box.hidden = !feedback;
  if (!feedback) return;
  const heading = make("div", "", "coach-feedback-heading");
  heading.append(make("h4", interviewPrepScoreLabels[feedback.score] || feedback.score));
  box.append(heading);
  const blocks = [
    ["Points solides", feedback.strengths || [], "good-list"],
    ["À retravailler", feedback.missing_elements || [], "review-list"],
    ["Affirmations non prouvées", feedback.unproven_claims || [], "review-list"],
  ];
  blocks.forEach(([label, items, className]) => {
    if (!items.length) return;
    const section = make("section", "", "coach-feedback-block");
    section.append(make("h5", label));
    const list = make("ul", "", className);
    items.forEach((item) => list.append(make("li", item)));
    section.append(list);
    box.append(section);
  });
  if (feedback.suggested_structure) {
    const section = make("section", "", "coach-feedback-block");
    section.append(make("h5", "Structure suggérée"));
    section.append(make("p", feedback.suggested_structure));
    box.append(section);
  }
  if (feedback.retry_prompt) {
    const section = make("section", "", "coach-feedback-block");
    section.append(make("h5", "Pour une nouvelle tentative"));
    section.append(make("p", feedback.retry_prompt));
    box.append(section);
  }
  if (feedback.pedagogical_source) {
    const section = make("section", "", "coach-feedback-block");
    section.append(make("h5", "Source pédagogique"));
    section.append(make("p", feedback.pedagogical_source));
    box.append(section);
  }
}

function interviewPrepStartSimulation(question) {
  const box = interviewPrepElement("#interview-prep-simulation");
  if (!box) return;
  box.hidden = false;
  interviewPrepState.currentQuestionId = question.id;
  const title = interviewPrepElement("#interview-prep-simulation-question");
  if (title) title.textContent = question.question;
  const expected = interviewPrepElement("#interview-prep-simulation-expected");
  if (expected) {
    expected.replaceChildren();
    (question.expected_elements || []).forEach((element) => expected.append(make("li", element)));
  }
  const answer = interviewPrepElement("#interview-prep-answer");
  if (answer) answer.value = "";
  const feedback = interviewPrepElement("#interview-prep-feedback");
  if (feedback) {
    feedback.replaceChildren();
    feedback.hidden = true;
  }
  interviewPrepElement("#interview-prep-simulation")?.scrollIntoView?.({ block: "nearest" });
  interviewPrepStartTimer(question.time_estimate_seconds);
  answer?.focus?.();
}

async function interviewPrepSubmitSimulation(event) {
  event.preventDefault();
  const session = interviewPrepState.session;
  if (!session) return;
  const answer = interviewPrepElement("#interview-prep-answer");
  const questionId = interviewPrepState.currentQuestionId;
  if (!answer || !questionId) return;
  const submit = interviewPrepElement("#interview-prep-simulate-submit");
  if (submit) submit.disabled = true;
  try {
    const feedback = await api("/api/career/interview-prep/simulate", {
      method: "POST",
      body: JSON.stringify({
        session_id: session.session_id,
        question_id: questionId,
        user_answer: answer.value,
      }),
    });
    interviewPrepRenderFeedback(feedback);
    interviewPrepStopTimer();
    await interviewPrepLoadHistory();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    if (submit) submit.disabled = false;
  }
}

function interviewPrepRenderSession(session) {
  interviewPrepState.session = session;
  const container = interviewPrepElement("#interview-prep-session");
  if (!container) return;
  container.hidden = !session;
  if (!session) return;
  const title = interviewPrepElement("#interview-prep-session-title");
  if (title) {
    const offer = session.offer || {};
    const target = [offer.company, offer.title].filter(Boolean).join(" — ");
    title.textContent = target ? `${target} · mode ${session.mode}` : `Mode ${session.mode}`;
  }
  interviewPrepRenderQuestions(interviewPrepState.activeTab);
  interviewPrepRenderRecruiter();
  interviewPrepRenderCompany();
  interviewPrepRenderTabs();
}

async function interviewPrepLoadHistory() {
  const container = interviewPrepElement("#interview-prep-history");
  const session = interviewPrepState.session;
  if (!container) return;
  container.replaceChildren();
  if (!session) return;
  let history = { simulations: [] };
  try {
    history = await api(`/api/career/interview-prep/${encodeURIComponent(session.session_id)}/history`);
  } catch (error) {
    setMessage(error.message, true);
    return;
  }
  const simulations = history.simulations || [];
  container.append(make("h4", "Historique des simulations"));
  if (!simulations.length) {
    container.append(make("p", "Aucune simulation enregistrée pour cette préparation.", "empty-state compact-empty"));
    return;
  }
  const list = make("ul", "", "interview-prep-list");
  simulations.forEach((entry) => {
    const feedback = entry.feedback || {};
    list.append(
      make(
        "li",
        `${entry.created_at} · ${entry.question_id} · ${interviewPrepScoreLabels[feedback.score] || feedback.score || "—"}`,
      ),
    );
  });
  container.append(list);
}

async function interviewPrepGenerate(event) {
  event.preventDefault();
  const jobSelect = interviewPrepElement("#interview-prep-job");
  const modeSelect = interviewPrepElement("#interview-prep-mode");
  const profileInput = interviewPrepElement("#interview-prep-profile");
  if (!jobSelect || !jobSelect.value) {
    setMessage("Choisis une offre Career pour préparer l’entretien.", true);
    return;
  }
  const submit = interviewPrepElement("#interview-prep-generate");
  if (submit) submit.disabled = true;
  try {
    const session = await api("/api/career/interview-prep/generate", {
      method: "POST",
      body: JSON.stringify({
        offer_id: jobSelect.value,
        profile_id: (profileInput?.value || "user_profile").trim() || "user_profile",
        mode: modeSelect?.value || "standard",
      }),
    });
    interviewPrepRenderSession(session);
    await interviewPrepLoadHistory();
    setMessage("Préparation locale générée.");
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    if (submit) submit.disabled = false;
  }
}

function interviewPrepRenderJobOptions(jobs) {
  const select = interviewPrepElement("#interview-prep-job");
  if (!select) return;
  const current = select.value;
  select.replaceChildren(new Option("Choisis une offre", ""));
  jobs.forEach((job) => {
    const location = [job.city, job.country].filter(Boolean).join(", ");
    select.append(new Option(`${job.company} — ${job.title}${location ? ` (${location})` : ""}`, job.id));
  });
  if (jobs.some((job) => job.id === current)) select.value = current;
}

async function loadInterviewPrep() {
  try {
    const [jobsPayload, sessionsPayload] = await Promise.all([
      api("/api/career/jobs"),
      api("/api/career/interview-prep"),
    ]);
    interviewPrepRenderJobOptions(jobsPayload.jobs || []);
    const sessions = sessionsPayload.sessions || [];
    if (!interviewPrepState.session && sessions.length) {
      try {
        const session = await api(`/api/career/interview-prep/${encodeURIComponent(sessions[0].id)}`);
        interviewPrepRenderSession(session);
        await interviewPrepLoadHistory();
      } catch (error) {
        setMessage(error.message, true);
      }
    }
  } catch (error) {
    setMessage(error.message, true);
  }
}

function interviewPrepWire() {
  const form = interviewPrepElement("#interview-prep-form");
  if (form && !form.dataset.wired) {
    form.dataset.wired = "true";
    form.addEventListener("submit", interviewPrepGenerate);
  }
  const simulationForm = interviewPrepElement("#interview-prep-simulation-form");
  if (simulationForm && !simulationForm.dataset.wired) {
    simulationForm.dataset.wired = "true";
    simulationForm.addEventListener("submit", interviewPrepSubmitSimulation);
  }
  document.querySelectorAll(".interview-prep-tab").forEach((button) => {
    if (button.dataset.wired) return;
    button.dataset.wired = "true";
    button.addEventListener("click", () => interviewPrepSelectTab(button.dataset.prepTab));
  });
  ["md", "pdf"].forEach((format) => {
    const button = interviewPrepElement(`#interview-prep-export-${format}`);
    if (!button || button.dataset.wired) return;
    button.dataset.wired = "true";
    button.addEventListener("click", () => {
      const session = interviewPrepState.session;
      if (!session) {
        setMessage("Génère d’abord une préparation.", true);
        return;
      }
      const link = make("a", "", "");
      link.href = `/api/career/interview-prep/${encodeURIComponent(session.session_id)}/export/${format}`;
      link.download = `preparation-entretien.${format}`;
      document.body.append(link);
      link.click();
      link.remove();
    });
  });
}
