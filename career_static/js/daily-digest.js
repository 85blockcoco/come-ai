"use strict";

// SPEC-005 — cockpit quotidien local (« Aujourd'hui »).
//
// Ce fichier est un script classique chargé avant career.js : il ne lit aucun
// global de career.js au chargement, seulement au moment de l'appel. Tous les
// noms exposés ici sont préfixés pour ne jamais entrer en collision avec
// career.js ou cv_plan.js.
//
// Règles d'affichage :
//   - aucune donnée n'est écrite dans le DOM sans passer par textContent ;
//   - un champ absent reste un inconnu affiché, jamais un zéro inventé ;
//   - aucune action externe : les relances restent des brouillons locaux.

const DAILY_DIGEST_ENDPOINT = "/api/career/daily";
const DAILY_DIGEST_REFRESH_ENDPOINT = "/api/career/daily/refresh";

const DAILY_DIGEST_LABELS = {
  expiring_offer: "Échéance proche",
  followup_due: "Relance à préparer",
  receipt_unknown: "Réception à vérifier",
  interview_due: "Entretien",
};

const DAILY_DIGEST_TONES = {
  expiring_offer: "danger",
  followup_due: "warning",
  receipt_unknown: "warning",
  interview_due: "good",
};

function dailyDigestElement(id) {
  return document.getElementById(id);
}

function dailyDigestMake(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function dailyDigestRequest(url, options = {}) {
  if (typeof api === "function") return api(url, options);
  const response = await fetch(url, {
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
  });
  if (!response.ok) throw new Error("L’action Career n’a pas abouti.");
  return response.json();
}

function dailyDigestSetError(message) {
  const target = dailyDigestElement("daily-error");
  if (target) {
    target.textContent = String(message || "");
    target.hidden = !message;
  }
  if (typeof setMessage === "function") setMessage(String(message || ""), true);
}

function dailyDigestSetStatus(message) {
  const target = dailyDigestElement("daily-status");
  if (target) target.textContent = String(message || "");
}

function dailyDigestTitle(item) {
  if (!item) return "";
  if (item.type === "expiring_offer") return item.title || "Offre sans intitulé";
  return item.offer_title || item.title || "Candidature suivie";
}

function dailyDigestSubtitle(item) {
  if (!item) return "";
  const parts = [];
  if (item.employer) parts.push(item.employer);
  if (item.location) parts.push(item.location);
  if (item.type === "expiring_offer" && typeof item.days_left === "number") {
    parts.push(item.days_left <= 0 ? "échéance aujourd’hui" : `J-${item.days_left}`);
  }
  if (item.type === "followup_due" && typeof item.days_since_sent === "number") {
    parts.push(`${item.days_since_sent} j sans réponse`);
  }
  if (item.type === "receipt_unknown") parts.push("réception non confirmée");
  if (item.type === "interview_due" && item.interview_date) parts.push(item.interview_date);
  return parts.join(" · ");
}

function dailyDigestBadge(item) {
  let label = DAILY_DIGEST_LABELS[item.type] || "À traiter";
  if (item.type === "followup_due") {
    label = item.status === "upcoming" ? "Relance à préparer" : "Relance due";
  }
  const tone = DAILY_DIGEST_TONES[item.type] || "";
  return tone ? `${label} · ${tone}` : label;
}

function dailyDigestDetail(item) {
  if (!item) return "";
  if (item.type === "expiring_offer") {
    const score = typeof item.match_score === "number" ? ` · score ${item.match_score}` : "";
    return `Date limite : ${item.deadline_date || "inconnue"}${score}`;
  }
  if (item.type === "followup_due") {
    return `Envoyée le ${item.sent_date || "date inconnue"} · relance suggérée le ${item.suggested_followup_date || "à définir"}`;
  }
  if (item.type === "receipt_unknown") {
    return `Déposée le ${item.sent_date || "date inconnue"} · aucune réception confirmée`;
  }
  if (item.type === "interview_due") {
    return `Entretien déclaré le ${item.interview_date || "date inconnue"} · l’heure exacte reste à confirmer`;
  }
  return "";
}

function renderDailyMetrics(target, progression) {
  if (!target) return;
  target.replaceChildren();
  const data = progression || {};
  const entries = [
    [data.prepared_this_week, "Dossiers préparés (7 j)"],
    [data.sent_this_week, "Candidatures envoyées (7 j)"],
    [data.responses_this_week, "Réponses reçues (7 j)"],
    [data.interviews_this_week, "Entretiens (7 j)"],
    [data.rejections_this_week, "Réponses négatives (7 j)"],
    [data.conversion_known ? `${Math.round(Number(data.conversion_rate || 0) * 100)} %` : "—", "Taux de conversion"],
  ];
  entries.forEach(([value, label]) => {
    const card = dailyDigestMake("article", "", "metric");
    card.append(dailyDigestMake("strong", String(value ?? "—")), dailyDigestMake("span", label));
    target.append(card);
  });
}

function renderDailyCards(target, empty, items, { navigate }) {
  if (!target || !empty) return;
  target.replaceChildren();
  const list = Array.isArray(items) ? items : [];
  empty.hidden = list.length > 0;
  list.forEach((item) => {
    const card = dailyDigestMake("article", "", "daily-card");
    const copy = dailyDigestMake("div", "", "daily-card-copy");
    copy.append(dailyDigestMake("strong", dailyDigestTitle(item)));
    copy.append(dailyDigestMake("span", dailyDigestSubtitle(item)));
    const detail = dailyDigestDetail(item);
    if (detail) copy.append(dailyDigestMake("small", detail));
    const meta = dailyDigestMake("div", "", "daily-card-meta");
    const tone = DAILY_DIGEST_TONES[item.type] || "";
    meta.append(dailyDigestMake("span", dailyDigestBadge(item), `job-chip${tone ? ` ${tone}` : ""}`));
    card.append(copy, meta);
    const action = dailyDigestMake("button", item.action_label || "Ouvrir", "quiet-button");
    action.type = "button";
    action.dataset.actionUrl = item.action_url || "";
    action.addEventListener("click", () => navigate(item));
    card.append(action);
    target.append(card);
  });
}

function renderDailyOpportunities(target, empty, items, { navigate }) {
  if (!target || !empty) return;
  target.replaceChildren();
  const list = Array.isArray(items) ? items : [];
  empty.hidden = list.length > 0;
  list.forEach((item) => {
    const card = dailyDigestMake("article", "", "daily-card");
    const copy = dailyDigestMake("div", "", "daily-card-copy");
    copy.append(dailyDigestMake("strong", item.title || "Offre sans intitulé"));
    copy.append(dailyDigestMake("span", [item.employer, item.location].filter(Boolean).join(" · ")));
    const facts = [];
    if (typeof item.match_score === "number") facts.push(`score ${item.match_score}`);
    if (item.mandatory_coverage) facts.push(`couverture ${item.mandatory_coverage}`);
    if (typeof item.published_days_ago === "number") facts.push(`publiée il y a ${item.published_days_ago} j`);
    if (facts.length) copy.append(dailyDigestMake("small", facts.join(" · ")));
    const meta = dailyDigestMake("div", "", "daily-card-meta");
    const trust = item.source_trust === "verified" ? "source vérifiée" : "à vérifier à la source";
    meta.append(dailyDigestMake("span", trust, `job-chip${item.source_trust === "verified" ? " good" : ""}`));
    card.append(copy, meta);
    const action = dailyDigestMake("button", item.action_label || "Préparer", "quiet-button");
    action.type = "button";
    action.dataset.actionUrl = item.action_url || "";
    action.addEventListener("click", () => navigate(item));
    card.append(action);
    target.append(card);
  });
}

function dailyDigestNavigate(item) {
  const type = item && item.type;
  if (typeof showView !== "function") return;
  if (type === "expiring_offer") {
    showView("studio");
    return;
  }
  showView("applications");
}

function renderDailyDigest(payload) {
  const data = payload || {};
  const honesty = dailyDigestElement("daily-honesty");
  if (honesty) {
    const parts = [];
    if (data.disclaimer) parts.push(data.disclaimer);
    if (data.cached) {
      parts.push(`Cache local réutilisé : il expire le ${data.cache_expires_at || "inconnu"}.`);
    }
    honesty.textContent = parts.join(" ");
  }
  renderDailyMetrics(dailyDigestElement("daily-progression-metrics"), data.progression);
  renderDailyCards(
    dailyDigestElement("daily-urgent"),
    dailyDigestElement("daily-urgent-empty"),
    data.urgent,
    { navigate: dailyDigestNavigate },
  );
  renderDailyOpportunities(
    dailyDigestElement("daily-opportunities"),
    dailyDigestElement("daily-opportunities-empty"),
    data.opportunities,
    { navigate: dailyDigestNavigate },
  );
  const notes = dailyDigestElement("daily-notes");
  if (notes) {
    const list = Array.isArray(data.notes) ? data.notes : [];
    notes.textContent = list.length ? list.join(" ") : "";
  }
}

async function dailyDigestLoad({ force = false } = {}) {
  const loading = dailyDigestElement("daily-loading");
  const failure = dailyDigestElement("daily-error");
  if (loading) loading.hidden = false;
  if (failure) {
    failure.textContent = "";
    failure.hidden = true;
  }
  try {
    const payload = force
      ? await dailyDigestRequest(DAILY_DIGEST_REFRESH_ENDPOINT, { method: "POST" })
      : await dailyDigestRequest(DAILY_DIGEST_ENDPOINT);
    renderDailyDigest(payload);
    dailyDigestSetStatus("Cockpit mis à jour.");
    return payload;
  } catch (problem) {
    dailyDigestSetError((problem && problem.message) || "Le cockpit n’a pas pu être calculé.");
    return null;
  } finally {
    if (loading) loading.hidden = true;
  }
}

window.careerDailyDigest = {
  load: () => dailyDigestLoad({ force: false }),
  refresh: () => dailyDigestLoad({ force: true }),
};

const dailyDigestRefreshButton = dailyDigestElement("daily-refresh");
if (dailyDigestRefreshButton) {
  dailyDigestRefreshButton.addEventListener("click", async () => {
    const button = dailyDigestRefreshButton;
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = "Actualisation…";
    try {
      await window.careerDailyDigest.refresh();
    } finally {
      button.disabled = false;
      button.textContent = previous;
    }
  });
}
