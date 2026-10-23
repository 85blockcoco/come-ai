"use strict";

/*
 * SPEC-012 — « Fraîcheur des preuves » (CVBOOST-47).
 *
 * Module d'interface autonome : il lit et écrit uniquement via
 * `/api/career/evidence-freshness`, en JavaScript simple (aucun framework,
 * aucune étape de build, aucun appel réseau externe). Tout ce qui est affiché
 * vient de faits datés : une date d'échéance, un statut, une alerte. Rien n'est
 * estimé, rien n'est inventé, aucun message n'est envoyé à un tiers.
 *
 * Ce module ne modifie pas career_static/career.js. La table de libellés des
 * onglets de career.js ignore cette vue : le titre de l'onglet est donc
 * réécrit ici, et career.js peut le remettre à « Career — Côme AI Career »
 * juste après : on le réapplique dès que l'onglet redevient actif.
 */

(function () {
  const API_ROOT = "/api/career/evidence-freshness";
  const VIEW_NAME = "evidence-freshness";
  const VIEW_TITLE = "Fraîcheur des preuves — Côme AI Career";

  /* ——— Vocabulaire local (français) ——— */

  const typeLabels = {
    certification: "Certification",
    skill_technical: "Compétence technique",
    skill_soft: "Savoir-être",
    experience: "Expérience",
    education: "Formation",
    language: "Langue",
    tool: "Outil",
    project: "Projet",
  };

  const statusLabels = {
    fresh: "À jour",
    warning: "À renouveler",
    expired: "Expirée",
    archived: "Archivée",
  };

  const coverageLabels = {
    unknown: "Couverture inconnue",
    covered: "Couverture établie",
    warning: "Couverture à vérifier",
    archived: "Couverture archivée",
  };

  const levelLabels = {
    info: "Info",
    warning: "Avertissement",
    critical: "Critique",
  };

  const kindLabels = {
    expired: "Preuve expirée",
    expiring_soon: "Échéance proche",
    entered_warning_zone: "Fenêtre d’avertissement",
    revoked: "Preuve révoquée",
  };

  const cadenceLabels = {
    daily: "Quotidienne",
    weekly: "Hebdomadaire",
    monthly: "Mensuelle",
    quarterly: "Trimestrielle",
  };

  const actionLabels = {
    downgrade_to_warning: "Dégradée en avertissement",
    archive_expired: "Archivée automatiquement",
    expired_no_auto_action: "Expirée sans action automatique",
    to_reverify: "À revérifier",
    revoked: "Révoquée",
    reactivated: "Réactivée",
    extended_expiry: "Échéance prolongée",
    verified: "Vérifiée",
    check_error: "Échec de vérification",
  };

  const statusOrder = { expired: 0, warning: 1, fresh: 2, archived: 3 };
  const levelOrder = { critical: 0, warning: 1, info: 2 };
  const timelineHorizons = ["7", "30", "90"];

  /* ——— Outils ——— */

  const $ = (selector) => document.querySelector(selector);

  function make(tag, text = "", className = "") {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function plural(count, singular, many) {
    return Number(count) === 1 ? singular : many;
  }

  function typeLabel(key) {
    return typeLabels[key] || key || "type inconnu";
  }

  function formatDate(value) {
    if (!value) return "date inconnue";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "date inconnue";
    return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
  }

  function formatShortDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
  }

  function formatDaysLeft(days) {
    if (days === null || days === undefined) return "sans échéance";
    const value = Number(days);
    if (!Number.isFinite(value)) return "sans échéance";
    if (value < 0) return `expirée depuis ${Math.abs(value)} j`;
    if (value === 0) return "expire aujourd’hui";
    return `dans ${value} j`;
  }

  function formatPercent(ratio) {
    const value = Number(ratio);
    if (!Number.isFinite(value)) return "0 %";
    return `${Math.round(value * 100)} %`;
  }

  function statusBadge(text, tone) {
    const badge = make("span", text, "status-badge");
    if (tone === "good") badge.classList.add("ready");
    else if (tone === "warning") badge.classList.add("warn");
    else if (tone === "danger") {
      badge.style.color = "var(--danger)";
      badge.style.background = "var(--danger-soft)";
    }
    return badge;
  }

  function statusTone(status) {
    if (status === "fresh") return "good";
    if (status === "warning") return "warning";
    if (status === "expired") return "danger";
    return "neutral";
  }

  /* ——— Éléments du DOM ——— */

  const elements = {
    view: $("#view-evidence-freshness"),
    tab: $("#tab-evidence-freshness"),
    loading: $("#freshness-loading"),
    error: $("#freshness-error"),
    status: $("#freshness-status"),
    counters: $("#freshness-counters"),
    timeline: $("#freshness-timeline"),
    timelineEmpty: $("#freshness-timeline-empty"),
    alerts: $("#freshness-alerts"),
    alertsEmpty: $("#freshness-alerts-empty"),
    byType: $("#freshness-by-type"),
    byTypeEmpty: $("#freshness-by-type-empty"),
    trends: $("#freshness-trends"),
    trendsEmpty: $("#freshness-trends-empty"),
    schedule: $("#freshness-schedule"),
    scheduleEmpty: $("#freshness-schedule-empty"),
    evidenceList: $("#freshness-evidence-list"),
    evidenceEmpty: $("#freshness-evidence-empty"),
    form: $("#freshness-form"),
    typeInput: $("#freshness-type"),
    titleInput: $("#freshness-title"),
    mandatoryInput: $("#freshness-mandatory"),
    sourceUrlInput: $("#freshness-source-url"),
    notesInput: $("#freshness-notes"),
    policyForm: $("#freshness-policy-form"),
    policyType: $("#freshness-policy-type"),
    policyMaxAge: $("#freshness-policy-max-age"),
    policyWarning: $("#freshness-policy-warning"),
    policyAutoExpire: $("#freshness-policy-auto-expire"),
    policyState: $("#freshness-policy-state"),
    policySave: $("#freshness-policy-save"),
    policyReset: $("#freshness-policy-reset"),
  };

  let pendingLoad = null;
  let lastPayload = null;

  /* ——— Réseau (même origine uniquement) ——— */

  async function api(path, options = {}) {
    const { headers, ...rest } = options;
    const response = await fetch(`${API_ROOT}${path}`, {
      credentials: "same-origin",
      ...rest,
      headers: { "Content-Type": "application/json", ...(headers || {}) },
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
      const detail = typeof body.detail === "string" ? body.detail : "L’action n’a pas abouti.";
      throw new Error(detail);
    }
    return body;
  }

  /* ——— Messages ——— */

  function showError(message) {
    if (!elements.error) return;
    elements.error.textContent = String(message || "L’action n’a pas abouti.");
    elements.error.hidden = false;
  }

  function clearError() {
    if (!elements.error) return;
    elements.error.textContent = "";
    elements.error.hidden = true;
  }

  function setStatus(message) {
    if (!elements.status) return;
    elements.status.textContent = String(message || "");
  }

  function setLoading(loading) {
    if (!elements.loading) return;
    elements.loading.hidden = !loading;
    if (loading) elements.loading.textContent = "Calcul de la fraîcheur de tes preuves…";
  }

  function summaryLine(payload) {
    const totals = payload?.report?.totals || {};
    const total = Number(totals.total || 0);
    const alerts = payload?.report?.alerts || {};
    const active = Number(alerts.active || 0);
    const parts = [
      `${total} ${plural(total, "preuve suivie", "preuves suivies")}`,
      `${Number(totals.fresh || 0)} à jour`,
      `${Number(totals.warning || 0)} à renouveler`,
      `${Number(totals.expired || 0)} expirée${Number(totals.expired || 0) > 1 ? "s" : ""}`,
      `${active} ${plural(active, "alerte active", "alertes actives")}`,
    ];
    const generated = payload?.generated_at ? ` · calculé le ${formatDate(payload.generated_at)}` : "";
    return `${parts.join(" · ")}${generated}.`;
  }

  /* ——— Rendu ——— */

  function renderCounters(report) {
    const container = elements.counters;
    if (!container) return;
    const totals = report?.totals || {};
    const ratios = report?.ratios || {};
    container.replaceChildren();
    ["fresh", "warning", "expired", "archived"].forEach((status) => {
      const card = make("article", "", "metric");
      card.append(make("strong", String(Number(totals[status] || 0))));
      card.append(make("span", `${statusLabels[status]} · ${formatPercent(ratios[status])}`));
      container.append(card);
    });
  }

  function renderTimeline(timeline) {
    const container = elements.timeline;
    if (!container) return;
    const buckets = timeline || {};
    container.replaceChildren();
    let upcoming = 0;
    timelineHorizons.forEach((horizon) => {
      const entries = Array.isArray(buckets[horizon]) ? buckets[horizon] : [];
      if (horizon === "90") upcoming = entries.length;
      const block = make("section", "", "freshness-timeline-block");
      block.append(make("h4", `Sous ${horizon} jours`));
      if (!entries.length) {
        block.append(make("p", "Aucune échéance dans cette fenêtre.", "panel-help"));
        container.append(block);
        return;
      }
      const list = make("ul", "", "dashboard-list");
      list.style.listStyle = "none";
      list.style.margin = "0";
      list.style.padding = "0";
      entries.forEach((entry) => {
        const item = make("li", "", "dashboard-item");
        const copy = make("div", "", "dashboard-item-copy");
        copy.append(make("strong", entry.title || entry.evidence_id || "Preuve"));
        copy.append(
          make(
            "span",
            `${typeLabel(entry.evidence_type)} · expire le ${formatDate(entry.expires_at)}`,
          ),
        );
        copy.append(
          make(
            "small",
            `${formatDaysLeft(entry.days_left)}${entry.mandatory ? " · preuve obligatoire" : ""}`,
          ),
        );
        item.append(copy);
        list.append(item);
      });
      block.append(list);
      container.append(block);
    });
    if (elements.timelineEmpty) elements.timelineEmpty.hidden = upcoming > 0;
  }

  function renderAlerts(alerts) {
    const container = elements.alerts;
    if (!container) return;
    const list = Array.isArray(alerts) ? alerts.slice() : [];
    list.sort((left, right) => {
      const leftLevel = levelOrder[left?.level] ?? 3;
      const rightLevel = levelOrder[right?.level] ?? 3;
      if (leftLevel !== rightLevel) return leftLevel - rightLevel;
      return String(left?.created_at || "").localeCompare(String(right?.created_at || ""));
    });
    container.replaceChildren();
    if (elements.alertsEmpty) elements.alertsEmpty.hidden = list.length > 0;
    list.forEach((alert) => {
      const item = make("article", "", "action-plan-item");
      const badge = statusBadge(
        levelLabels[alert?.level] || alert?.level || "Info",
        alert?.level === "critical" ? "danger" : alert?.level === "warning" ? "warning" : "neutral",
      );
      const copy = make("div", "", "action-plan-copy");
      copy.append(make("h4", alert?.title || "Alerte"));
      copy.append(make("p", alert?.message || ""));
      const meta = make("div", "", "action-plan-meta");
      meta.append(
        make("span", kindLabels[alert?.kind] || alert?.kind || "alerte", "action-plan-priority"),
      );
      meta.append(make("span", typeLabel(alert?.evidence_type), "action-plan-destination"));
      copy.append(meta);
      const actions = make("div", "", "inline-actions");
      const acknowledge = make("button", "Acquitter", "quiet-button");
      acknowledge.type = "button";
      acknowledge.addEventListener("click", () => acknowledgeAlert(alert?.alert_id));
      actions.append(acknowledge);
      item.append(badge, copy, actions);
      container.append(item);
    });
  }

  function renderByType(byType) {
    const container = elements.byType;
    if (!container) return;
    const rows = Object.entries(byType || {});
    container.replaceChildren();
    if (elements.byTypeEmpty) elements.byTypeEmpty.hidden = rows.length > 0;
    if (!rows.length) return;

    const table = make("table");
    table.style.width = "100%";
    table.style.borderCollapse = "collapse";
    const caption = make("caption", "Répartition des preuves par type", "visually-hidden");
    table.append(caption);

    const head = make("thead");
    const headRow = make("tr");
    ["Type", "Total", "À jour", "À renouveler", "Expirées", "Archivées", "Prochaine échéance"].forEach(
      (label) => {
        const cell = make("th", label);
        cell.scope = "col";
        cell.style.textAlign = "left";
        cell.style.padding = "6px 8px";
        cell.style.fontSize = ".72rem";
        cell.style.textTransform = "uppercase";
        cell.style.letterSpacing = ".05em";
        cell.style.color = "var(--muted)";
        headRow.append(cell);
      },
    );
    head.append(headRow);
    table.append(head);

    const body = make("tbody");
    rows.forEach(([evidenceType, bucket]) => {
      const row = make("tr");
      const cells = [
        typeLabel(evidenceType),
        String(Number(bucket?.total || 0)),
        String(Number(bucket?.fresh || 0)),
        String(Number(bucket?.warning || 0)),
        String(Number(bucket?.expired || 0)),
        String(Number(bucket?.archived || 0)),
        bucket?.next_expiry ? formatDate(bucket.next_expiry) : "aucune",
      ];
      cells.forEach((value, index) => {
        const cell = make("td", value);
        cell.style.padding = "6px 8px";
        cell.style.fontSize = ".78rem";
        cell.style.borderTop = "1px solid #e1eee7";
        if (index === 0) cell.style.fontWeight = "720";
        row.append(cell);
      });
      body.append(row);
    });
    table.append(body);
    container.append(table);
  }

  function trendSummary(window, series) {
    if (!series.length) {
      return `Aucun relevé enregistré sur ${window} jours : la tendance ne peut pas être calculée.`;
    }
    const first = series[0];
    const last = series[series.length - 1];
    return `Fraîcheur : ${formatPercent(first.fresh_ratio)} → ${formatPercent(last.fresh_ratio)} sur ${window} j (${series.length} ${plural(series.length, "relevé", "relevés")}).`;
  }

  function renderTrends(trends) {
    const container = elements.trends;
    if (!container) return;
    const windows = Object.entries(trends || {});
    container.replaceChildren();
    if (elements.trendsEmpty) elements.trendsEmpty.hidden = windows.length > 0;
    windows.forEach(([window, data]) => {
      const series = Array.isArray(data?.series) ? data.series : [];
      const block = make("section", "", "freshness-trend");
      block.append(make("h4", `Tendance sur ${window} jours`));
      block.append(make("p", trendSummary(window, series), "panel-help"));
      if (series.length) {
        const chart = make("ul", "", "freshness-trend-bars");
        chart.style.display = "flex";
        chart.style.alignItems = "flex-end";
        chart.style.gap = "8px";
        chart.style.listStyle = "none";
        chart.style.margin = "0";
        chart.style.padding = "0";
        chart.style.overflowX = "auto";
        chart.setAttribute("aria-label", `Évolution de la fraîcheur sur ${window} jours`);
        series.forEach((point) => {
          const ratio = Number(point?.fresh_ratio) || 0;
          const item = make("li", "", "freshness-trend-point");
          item.style.display = "flex";
          item.style.flexDirection = "column";
          item.style.alignItems = "center";
          item.style.gap = "4px";
          const bar = make("span", "", "freshness-trend-bar");
          bar.setAttribute("aria-hidden", "true");
          bar.style.display = "block";
          bar.style.width = "18px";
          bar.style.borderRadius = "4px 4px 0 0";
          bar.style.background = "var(--accent)";
          bar.style.height = `${Math.max(3, Math.round(ratio * 70))}px`;
          const label = make("span", `${formatShortDate(point?.date)} · ${formatPercent(point?.fresh_ratio)}`);
          label.style.fontSize = ".68rem";
          label.style.color = "var(--muted)";
          label.style.whiteSpace = "nowrap";
          item.append(bar, label);
          chart.append(item);
        });
        block.append(chart);
      }
      container.append(block);
    });
  }

  function renderSchedule(schedule) {
    const container = elements.schedule;
    if (!container) return;
    const checks = Array.isArray(schedule) ? schedule.slice() : [];
    checks.sort((left, right) => {
      const leftOverdue = left?.overdue ? 0 : 1;
      const rightOverdue = right?.overdue ? 0 : 1;
      if (leftOverdue !== rightOverdue) return leftOverdue - rightOverdue;
      return Number(left?.days_until_due || 0) - Number(right?.days_until_due || 0);
    });
    container.replaceChildren();
    if (elements.scheduleEmpty) elements.scheduleEmpty.hidden = checks.length > 0;
    checks.forEach((check) => {
      const item = make("article", "", "action-plan-item");
      const badge = statusBadge(
        cadenceLabels[check?.cadence] || check?.cadence || "Contrôle",
        check?.overdue ? "danger" : check?.priority === "high" ? "warning" : "good",
      );
      const copy = make("div", "", "action-plan-copy");
      copy.append(make("h4", check?.title || check?.evidence_id || "Contrôle"));
      copy.append(make("p", check?.reason || "Contrôle planifié."));
      const meta = make("div", "", "action-plan-meta");
      meta.append(make("span", typeLabel(check?.evidence_type), "action-plan-destination"));
      meta.append(
        make(
          "span",
          `Échéance : ${formatDate(check?.due_at)} · ${formatDaysLeft(check?.days_until_due)}`,
          `action-plan-priority${check?.overdue ? " urgent" : ""}`,
        ),
      );
      copy.append(meta);
      const actions = make("div", "", "inline-actions");
      const verify = make("button", "Vérifier", "quiet-button");
      verify.type = "button";
      verify.addEventListener("click", () => checkEvidence(check?.evidence_id));
      actions.append(verify);
      item.append(badge, copy, actions);
      container.append(item);
    });
  }

  function evidenceSort(left, right) {
    const leftOrder = statusOrder[left?.status] ?? 4;
    const rightOrder = statusOrder[right?.status] ?? 4;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    const leftTitle = String(left?.title || "").toLowerCase();
    const rightTitle = String(right?.title || "").toLowerCase();
    if (leftTitle !== rightTitle) return leftTitle < rightTitle ? -1 : 1;
    return String(left?.evidence_id || "").localeCompare(String(right?.evidence_id || ""));
  }

  function renderEvidenceList(evidence) {
    const container = elements.evidenceList;
    if (!container) return;
    const list = Array.isArray(evidence) ? evidence.slice() : [];
    list.sort(evidenceSort);
    container.replaceChildren();
    if (elements.evidenceEmpty) elements.evidenceEmpty.hidden = list.length > 0;
    list.forEach((item) => {
      const row = make("article", "", "dashboard-item freshness-evidence-item");
      const copy = make("div", "", "dashboard-item-copy");
      copy.append(make("strong", item?.title || item?.evidence_id || "Preuve"));
      copy.append(
        make(
          "span",
          `${typeLabel(item?.evidence_type)} · ${
            item?.expires_at ? `expire le ${formatDate(item.expires_at)}` : "sans échéance"
          } (${formatDaysLeft(item?.days_until_expiry)})`,
        ),
      );
      const details = [];
      if (item?.last_verified_at) details.push(`dernière vérification le ${formatDate(item.last_verified_at)}`);
      else details.push("jamais vérifiée");
      details.push(`${Number(item?.checks_count || 0)} ${plural(Number(item?.checks_count || 0), "contrôle", "contrôles")}`);
      details.push(coverageLabels[item?.coverage_status] || item?.coverage_status || "couverture inconnue");
      if (item?.mandatory) details.push("obligatoire");
      copy.append(make("small", details.join(" · ")));
      row.append(copy);

      const side = make("div", "", "freshness-evidence-side");
      side.style.display = "grid";
      side.style.gap = "6px";
      side.style.justifyItems = "end";
      side.append(statusBadge(statusLabels[item?.status] || item?.status || "Statut", statusTone(item?.status)));
      if (Array.isArray(item?.auto_actions) && item.auto_actions.length) {
        const actions = make("small", "", "freshness-evidence-auto");
        actions.style.color = "var(--muted)";
        actions.style.fontSize = ".7rem";
        actions.textContent = item.auto_actions
          .map((action) => actionLabels[action] || action)
          .join(" · ");
        side.append(actions);
      }
      const buttons = make("div", "", "freshness-evidence-actions");
      buttons.style.display = "flex";
      buttons.style.flexWrap = "wrap";
      buttons.style.gap = "6px";
      buttons.style.justifyContent = "flex-end";

      const verify = make("button", "Vérifier", "quiet-button");
      verify.type = "button";
      verify.addEventListener("click", () => checkEvidence(item?.evidence_id));
      buttons.append(verify);

      if (item?.archived) {
        const reactivate = make("button", "Réactiver", "quiet-button");
        reactivate.type = "button";
        reactivate.addEventListener("click", () => reactivateEvidence(item?.evidence_id));
        buttons.append(reactivate);
      } else {
        const archive = make("button", "Archiver", "quiet-button");
        archive.type = "button";
        archive.addEventListener("click", () => archiveEvidence(item?.evidence_id));
        buttons.append(archive);
      }

      const extend = make("button", "Prolonger de 30 jours", "quiet-button");
      extend.type = "button";
      extend.addEventListener("click", () => extendEvidence(item?.evidence_id, 30));
      buttons.append(extend);

      const remove = make("button", "Supprimer", "quiet-button");
      remove.type = "button";
      remove.addEventListener("click", () => deleteEvidence(item?.evidence_id, item?.title));
      buttons.append(remove);

      side.append(buttons);
      row.append(side);
      container.append(row);
    });
  }

  function renderPolicies(policies) {
    const evidenceType = elements.policyType?.value || "";
    const policy = policies?.[evidenceType] || null;
    if (elements.policyMaxAge) {
      elements.policyMaxAge.value =
        policy?.max_age_days === null || policy?.max_age_days === undefined
          ? ""
          : String(policy.max_age_days);
    }
    if (elements.policyWarning) {
      elements.policyWarning.value =
        policy?.warning_days === null || policy?.warning_days === undefined
          ? ""
          : String(policy.warning_days);
    }
    if (elements.policyAutoExpire) {
      elements.policyAutoExpire.checked = Boolean(policy?.auto_expire);
    }
    if (!elements.policyState) return;
    if (!policy) {
      elements.policyState.textContent = "";
      return;
    }
    const validity =
      policy.max_age_days === null || policy.max_age_days === undefined
        ? "aucune durée limite"
        : `valable ${policy.max_age_days} j`;
    const warning =
      policy.warning_days === null || policy.warning_days === undefined
        ? "aucun avertissement programmé"
        : `avertissement ${policy.warning_days} j avant l’échéance`;
    const auto = policy.auto_expire
      ? "dégradation automatique activée"
      : "aucune dégradation automatique";
    const custom = policy.overridden ? " · politique personnalisée" : " · politique par défaut";
    elements.policyState.textContent = `${typeLabel(evidenceType)} : ${validity} · ${warning} · ${auto}${custom}.`;
  }

  function renderAll(payload, audit) {
    const report = payload?.report || {};
    renderCounters(report);
    renderTimeline(report.timeline);
    renderAlerts(payload?.alerts);
    renderByType(report.by_type);
    renderTrends(audit?.trends);
    renderSchedule(payload?.schedule);
    renderEvidenceList(payload?.evidence);
    renderPolicies(payload?.policies);
  }

  /* ——— Chargement ——— */

  async function doLoad() {
    setLoading(true);
    clearError();
    const [statusResult, reportResult] = await Promise.all([
      api("/status").then((value) => ({ ok: true, value })).catch((error) => ({ ok: false, error })),
      api("/report").then((value) => ({ ok: true, value })).catch(() => ({ ok: false, value: null })),
    ]);
    setLoading(false);
    if (!statusResult.ok) {
      showError(statusResult.error?.message || "La fraîcheur des preuves n’a pas pu être calculée.");
      setStatus("Aucun état de fraîcheur n’a pu être calculé.");
      return null;
    }
    lastPayload = statusResult.value;
    renderAll(statusResult.value, reportResult.ok ? reportResult.value : null);
    setStatus(summaryLine(statusResult.value));
    return statusResult.value;
  }

  function loadStatus() {
    if (pendingLoad) return pendingLoad;
    pendingLoad = doLoad().finally(() => {
      pendingLoad = null;
    });
    return pendingLoad;
  }

  async function reloadStatus() {
    if (pendingLoad) {
      try {
        await pendingLoad;
      } catch (_) {
        /* La charge précédente a échoué : une nouvelle tentative est faite. */
      }
    }
    return loadStatus();
  }

  /* ——— Actions ——— */

  async function runMutation(action, successMessage) {
    clearError();
    try {
      await action();
    } catch (error) {
      showError(error?.message || "L’action n’a pas abouti.");
      setStatus("L’action n’a pas abouti : rien n’a été modifié.");
      return false;
    }
    const payload = await reloadStatus();
    setStatus(
      payload
        ? `${successMessage} ${summaryLine(payload)}`
        : "L’action a été appliquée, mais l’actualisation a échoué.",
    );
    return true;
  }

  async function checkEvidence(evidenceId) {
    if (!evidenceId) return;
    await runMutation(
      () =>
        api(`/check/${encodeURIComponent(evidenceId)}`, {
          method: "POST",
          body: JSON.stringify({ method: "manual", result: "unchanged" }),
        }),
      "Vérification manuelle enregistrée.",
    );
  }

  async function acknowledgeAlert(alertId) {
    if (!alertId) return;
    await runMutation(
      () => api(`/acknowledge/${encodeURIComponent(alertId)}`, { method: "POST" }),
      "Alerte acquittée.",
    );
  }

  async function reactivateEvidence(evidenceId) {
    if (!evidenceId) return;
    await runMutation(
      () =>
        api(`/evidence/${encodeURIComponent(evidenceId)}`, {
          method: "PATCH",
          body: JSON.stringify({ reactivate: true }),
        }),
      "Preuve réactivée.",
    );
  }

  async function archiveEvidence(evidenceId) {
    if (!evidenceId) return;
    await runMutation(
      () =>
        api(`/evidence/${encodeURIComponent(evidenceId)}`, {
          method: "PATCH",
          body: JSON.stringify({ archived: true }),
        }),
      "Preuve archivée.",
    );
  }

  async function extendEvidence(evidenceId, days) {
    if (!evidenceId) return;
    await runMutation(
      () =>
        api(`/evidence/${encodeURIComponent(evidenceId)}`, {
          method: "PATCH",
          body: JSON.stringify({ extend_days: Number(days) || 30 }),
        }),
      `Échéance prolongée de ${Number(days) || 30} jours.`,
    );
  }

  async function deleteEvidence(evidenceId, title) {
    if (!evidenceId) return;
    const label = title || evidenceId;
    const confirmed = window.confirm(
      `Supprimer définitivement la preuve « ${label} » ? Cette action est irréversible.`,
    );
    if (!confirmed) return;
    await runMutation(
      () => api(`/evidence/${encodeURIComponent(evidenceId)}`, { method: "DELETE" }),
      "Preuve supprimée.",
    );
  }

  function readNumber(input) {
    if (!input) return null;
    const raw = String(input.value || "").trim();
    if (!raw) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  async function submitEvidence(event) {
    event.preventDefault();
    const evidenceType = elements.typeInput?.value || "";
    const title = String(elements.titleInput?.value || "").trim();
    if (!evidenceType) {
      showError("Choisis un type de preuve.");
      return;
    }
    if (!title) {
      showError("Indique un titre pour la preuve.");
      return;
    }
    const payload = {
      evidence_type: evidenceType,
      title,
      mandatory: Boolean(elements.mandatoryInput?.checked),
      source_url: String(elements.sourceUrlInput?.value || "").trim(),
      notes: String(elements.notesInput?.value || "").trim(),
    };
    const saved = await runMutation(
      () => api("/evidence", { method: "POST", body: JSON.stringify(payload) }),
      `Preuve « ${title} » enregistrée.`,
    );
    if (saved && elements.form?.reset) elements.form.reset();
  }

  async function savePolicy(event) {
    if (event) event.preventDefault();
    const evidenceType = elements.policyType?.value || "";
    if (!evidenceType) {
      showError("Choisis un type de preuve.");
      return;
    }
    const payload = {
      evidence_type: evidenceType,
      max_age_days: readNumber(elements.policyMaxAge),
      warning_days: readNumber(elements.policyWarning),
      auto_expire: Boolean(elements.policyAutoExpire?.checked),
    };
    await runMutation(
      () => api("/policy", { method: "POST", body: JSON.stringify(payload) }),
      `Politique « ${typeLabel(evidenceType)} » appliquée.`,
    );
  }

  async function resetPolicy() {
    const evidenceType = elements.policyType?.value || "";
    if (!evidenceType) {
      showError("Choisis un type de preuve.");
      return;
    }
    await runMutation(
      () =>
        api("/policy", {
          method: "POST",
          body: JSON.stringify({ evidence_type: evidenceType, reset: true }),
        }),
      `Politique « ${typeLabel(evidenceType)} » revenue à sa valeur par défaut.`,
    );
  }

  /* ——— Vue et titre ——— */

  function viewIsActive() {
    return Boolean(elements.view) && !elements.view.hidden;
  }

  function applyViewTitle() {
    if (!viewIsActive()) return;
    if (document.title === VIEW_TITLE) return;
    document.title = VIEW_TITLE;
  }

  function activateView() {
    if (!elements.view) return;
    document.querySelectorAll(".career-view").forEach((view) => {
      view.hidden = view !== elements.view;
    });
    document.querySelectorAll(".career-tab").forEach((tab) => {
      const active = tab.dataset.view === VIEW_NAME;
      tab.classList.toggle("active", active);
      if (active) tab.setAttribute("aria-current", "page");
      else tab.removeAttribute("aria-current");
    });
    applyViewTitle();
    window.setTimeout(applyViewTitle, 60);
    window.setTimeout(applyViewTitle, 400);
  }

  function watchDocumentTitle() {
    if (!("MutationObserver" in window)) return;
    const observer = new window.MutationObserver(() => applyViewTitle());
    observer.observe(document.head, { childList: true, characterData: true, subtree: true });
  }

  /* ——— Démarrage ——— */

  function init() {
    if (!elements.view) return;

    elements.tab?.addEventListener("click", () => {
      activateView();
      loadStatus();
    });

    window.addEventListener("hashchange", () => {
      if (window.location.hash !== `#career/${VIEW_NAME}`) return;
      activateView();
      loadStatus();
    });

    // Rafraîchissement « temps réel » : la vue se met à jour seule quand elle
    // est visible et que l'onglet du navigateur est actif. Aucun appel n'est
    // fait dans le dos de l'utilisateur, et rien n'est envoyé à un tiers.
    window.setInterval(() => {
      if (!viewIsActive()) return;
      if (document.visibilityState && document.visibilityState !== "visible") return;
      loadStatus();
    }, 60000);

    elements.form?.addEventListener("submit", submitEvidence);
    elements.policyForm?.addEventListener("submit", savePolicy);
    elements.policySave?.addEventListener("click", savePolicy);
    elements.policyReset?.addEventListener("click", resetPolicy);
    elements.policyType?.addEventListener("change", () => renderPolicies(lastPayload?.policies));

    watchDocumentTitle();

    if (viewIsActive()) {
      loadStatus();
    } else if (window.location.hash === `#career/${VIEW_NAME}`) {
      activateView();
      loadStatus();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
