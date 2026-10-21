"use strict";
/**
 * Daily digest panel (SK-09).
 *
 * The panel only reads the local digest endpoint.  It never triggers a source
 * refresh on its own: the refresh button is the single explicit action that
 * may read a public source, and it is the user's click that starts it.
 */

const dailyDigestState = {
  loading: false,
  refreshing: false,
  digest: null,
  visitedPayload: "",
};

const dailyDigestLabels = {
  trust: {
    verified: "Source vérifiée",
    unverified: "Source non vérifiée",
    unknown: "Source inconnue",
  },
  status: {
    conforming: "Conforme aux critères",
    to_verify: "À vérifier",
  },
  cache: {
    fresh: "À jour",
    expired: "Cache expiré",
    missing: "Jamais actualisé",
  },
};

function dailyDigestElement(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function dailyDigestDate(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" });
}

function dailyDigestRelative(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  const seconds = Math.round((Date.now() - parsed.getTime()) / 1000);
  if (seconds < 60) return "à l'instant";
  if (seconds < 3600) return `il y a ${Math.round(seconds / 60)} min`;
  if (seconds < 86_400) return `il y a ${Math.round(seconds / 3600)} h`;
  return `il y a ${Math.round(seconds / 86_400)} j`;
}

async function dailyDigestRequest(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  let body = {};
  if (contentType.includes("application/json")) {
    try {
      body = await response.json();
    } catch (_) {
      body = {};
    }
  }
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "L’actualisation Career n’a pas abouti.";
    throw new Error(detail);
  }
  return body;
}

function dailyDigestEmpty(label) {
  return dailyDigestElement("p", label, "empty-state");
}

function dailyDigestItem(title, subtitle, meta) {
  const item = dailyDigestElement("article", "", "dashboard-item");
  const copy = dailyDigestElement("div", "", "dashboard-item-copy");
  copy.append(dailyDigestElement("strong", title));
  copy.append(dailyDigestElement("span", subtitle));
  if (meta) copy.append(dailyDigestElement("small", meta));
  item.append(copy);
  return item;
}

function dailyDigestSection(title, hint, items, emptyLabel) {
  const section = dailyDigestElement("section", "", "daily-digest-section");
  const heading = dailyDigestElement("div", "", "panel-heading compact-heading");
  const left = dailyDigestElement("div");
  left.append(dailyDigestElement("p", "eyebrow", ""));
  left.lastChild.textContent = title;
  heading.append(left);
  const list = dailyDigestElement("div", "", "dashboard-list");
  if (!items.length) {
    list.append(dailyDigestEmpty(emptyLabel));
  } else {
    items.forEach((item) => list.append(item));
  }
  section.append(heading, list);
  if (hint) {
    const help = dailyDigestElement("p", hint, "panel-help");
    section.append(help);
  }
  return section;
}

function dailyDigestRenderSummary(digest) {
  const counts = digest.counts || {};
  const summary = dailyDigestElement("div", "", "daily-digest-summary");
  const metrics = [
    { value: counts.new_offers || 0, label: "nouvelles" },
    { value: counts.updated_offers || 0, label: "mises à jour" },
    { value: counts.expiring_soon || 0, label: "expirent bientôt" },
    { value: counts.unavailable || 0, label: "indisponibles" },
    { value: counts.broken_sources || 0, label: "sources en panne" },
  ];
  metrics.forEach((entry) => {
    const metric = dailyDigestElement("article", "", "metric");
    metric.append(dailyDigestElement("strong", String(entry.value)), dailyDigestElement("span", entry.label));
    summary.append(metric);
  });
  return summary;
}

function dailyDigestRender(digest) {
  const container = document.querySelector("#daily-digest-content");
  const status = document.querySelector("#daily-digest-status");
  if (!container) return;
  container.replaceChildren();

  const notes = Array.isArray(digest.notes) ? digest.notes : [];
  notes.forEach((note) => container.append(dailyDigestElement("p", note, "panel-help")));

  container.append(dailyDigestRenderSummary(digest));

  const newItems = (digest.new_offers || []).map((offer) =>
    dailyDigestItem(
      offer.title || "Intitulé à vérifier",
      `${offer.employer || "Entreprise à vérifier"} · ${offer.location || "Localisation à vérifier"}`,
      [
        offer.published_date ? `Publié le ${offer.published_date}` : "Date de publication inconnue",
        typeof offer.match_score === "number" ? `Pertinence ${offer.match_score}/100` : "Pertinence non calculée",
        dailyDigestLabels.trust[offer.source_trust] || "Source inconnue",
      ].join(" · ")
    )
  );

  const updatedItems = (digest.updated_offers || []).map((offer) =>
    dailyDigestItem(
      offer.title || "Intitulé à vérifier",
      `${offer.employer || "Entreprise à vérifier"}`,
      `Champs modifiés : ${(offer.changed_fields || []).join(", ") || "aucun"}`
    )
  );

  const expiringItems = (digest.expiring_soon || []).map((offer) =>
    dailyDigestItem(
      offer.title || "Intitulé à vérifier",
      `${offer.employer || "Entreprise à vérifier"}`,
      `Date limite ${offer.deadline_date || "à vérifier"} · ${offer.days_left ?? "?"} jour(s) restant(s)`
    )
  );

  const unavailableItems = (digest.unavailable || []).map((offer) =>
    dailyDigestItem(
      offer.title || "Intitulé à vérifier",
      `${offer.employer || "Entreprise à vérifier"}`,
      `${offer.reason || "Offre indisponible"}${offer.detected_at ? ` · ${dailyDigestRelative(offer.detected_at)}` : ""}`
    )
  );

  const topItems = (digest.top_matches || []).map((offer) =>
    dailyDigestItem(
      offer.title || "Intitulé à vérifier",
      `${offer.employer || "Entreprise à vérifier"}`,
      [
        typeof offer.fit_score === "number" ? `Adéquation ${offer.fit_score}/100` : "Adéquation non calculée",
        `${offer.missing_critical_count || 0} information(s) critique(s) manquante(s)`,
        dailyDigestLabels.status[offer.qualification_status] || "À vérifier",
      ].join(" · ")
    )
  );

  const brokenItems = (digest.broken_sources || []).map((source) =>
    dailyDigestItem(
      source.source || "Source inconnue",
      source.error || "Échec non détaillé",
      [
        source.last_failure ? `Dernier échec ${dailyDigestRelative(source.last_failure)}` : "Dernier échec inconnu",
        source.retry_at ? `Nouvelle tentative ${dailyDigestRelative(source.retry_at)}` : "Aucune nouvelle tentative planifiée",
      ].join(" · ")
    )
  );

  container.append(
    dailyDigestSection("Nouveau", "Offres apparues depuis ta dernière visite.", newItems, "Aucune nouvelle offre depuis ta dernière visite."),
    dailyDigestSection("Mises à jour", "Champs réellement modifiés sur une offre déjà connue.", updatedItems, "Aucune offre mise à jour."),
    dailyDigestSection("Échéances", "Une date limite connue qui approche.", expiringItems, "Aucune échéance connue dans les quatorze prochains jours."),
    dailyDigestSection("Indisponibles", "Offres closes ou dont la date limite est passée.", unavailableItems, "Aucune offre devenue indisponible."),
    dailyDigestSection("Meilleures offres", "Classement local selon tes critères enregistrés.", topItems, "Aucune offre conforme à tes critères enregistrés."),
    dailyDigestSection("Sources en panne", "Sources officielles qui n’ont pas pu être lues.", brokenItems, "Aucune source en panne.")
  );

  if (status) {
    const cacheLabel = dailyDigestLabels.cache[digest.cache_status] || "État inconnu";
    const refreshLabel = digest.last_refresh ? `Actualisé ${dailyDigestRelative(digest.last_refresh)}` : "Jamais actualisé";
    status.textContent = `${cacheLabel} · ${refreshLabel}`;
  }
}

async function dailyDigestLoad() {
  const panel = document.querySelector("#daily-digest-panel");
  const error = document.querySelector("#daily-digest-error");
  if (dailyDigestState.loading) return;
  dailyDigestState.loading = true;
  if (panel) panel.setAttribute("aria-busy", "true");
  try {
    const digest = await dailyDigestRequest("/api/career/daily");
    dailyDigestState.digest = digest;
    dailyDigestRender(digest);
    if (error) {
      error.hidden = true;
      error.textContent = "";
    }
    const generatedAt = digest.generated_at || "";
    if (generatedAt && generatedAt !== dailyDigestState.visitedPayload) {
      dailyDigestState.visitedPayload = generatedAt;
      // The visit is recorded after the screen was served, so the next digest
      // reports exactly what appeared since this moment.
      await dailyDigestRequest("/api/career/daily/visit", { method: "POST" }).catch(() => undefined);
    }
  } catch (caught) {
    if (error) {
      error.hidden = false;
      error.textContent = caught.message || "La synthèse du jour n’a pas pu être lue.";
    }
  } finally {
    dailyDigestState.loading = false;
    if (panel) panel.setAttribute("aria-busy", "false");
  }
}

async function dailyDigestRefresh() {
  const button = document.querySelector("#daily-digest-refresh");
  const error = document.querySelector("#daily-digest-error");
  const status = document.querySelector("#daily-digest-status");
  if (dailyDigestState.refreshing) return;
  dailyDigestState.refreshing = true;
  if (button) {
    button.disabled = true;
    button.textContent = "Actualisation en cours…";
  }
  if (status) status.textContent = "Actualisation en cours…";
  try {
    const digest = await dailyDigestRequest("/api/career/daily/refresh", {
      method: "POST",
      body: JSON.stringify({ force: false, include_boards: true, include_curated: true }),
    });
    dailyDigestState.digest = digest;
    dailyDigestState.visitedPayload = digest.generated_at || "";
    dailyDigestRender(digest);
    if (error) {
      error.hidden = true;
      error.textContent = "";
    }
  } catch (caught) {
    if (error) {
      error.hidden = false;
      error.textContent = caught.message || "L’actualisation n’a pas abouti.";
    }
  } finally {
    dailyDigestState.refreshing = false;
    if (button) {
      button.disabled = false;
      button.textContent = "Actualiser les sources";
    }
  }
}

function dailyDigestStart() {
  const button = document.querySelector("#daily-digest-refresh");
  if (button && !button.dataset.dailyDigestBound) {
    button.dataset.dailyDigestBound = "true";
    button.addEventListener("click", () => {
      dailyDigestRefresh();
    });
  }
  const view = document.querySelector("#view-dashboard");
  if (view && !view.dataset.dailyDigestBound) {
    view.dataset.dailyDigestBound = "true";
    // The digest is read once when the panel appears, and again when the
    // person comes back to the dashboard. No source is ever read here.
    new MutationObserver(() => {
      if (!view.hidden) dailyDigestLoad();
    }).observe(view, { attributes: true, attributeFilter: ["hidden"] });
  }
  dailyDigestLoad();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", dailyDigestStart, { once: true });
} else {
  dailyDigestStart();
}
