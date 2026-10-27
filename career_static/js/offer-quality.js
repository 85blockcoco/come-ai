/* SPEC-006 — Badges de fraîcheur, de complétude et de source d'une offre.
 *
 * Le module est local et déterministe : il lit le contrat
 * `GET /api/career/offer-quality/{offer_id}` et affiche trois badges
 * (fraîcheur, complétude, confiance de la source).  Il ne modifie jamais
 * une offre et ne déclare jamais une source « vérifiée » de son propre
 * chef : le statut vient toujours du serveur, qui applique SPEC-SK-01.
 *
 * Usage :
 *   window.CareerOfferQuality.decorate(cardElement, job)  // badges
 *   window.CareerOfferQuality.refresh([jobId], true)       // rafraîchissement
 */
(function () {
  "use strict";

  const FRESHNESS_LABELS = {
    fresh: {label: "Fraîche", tone: "good"},
    aging: {label: "Fraîcheur à revérifier", tone: "warning"},
    stale: {label: "Fraîcheur périmée", tone: "danger"},
    expired: {label: "Offre expirée", tone: "danger"},
    unknown: {label: "Fraîcheur inconnue", tone: "warning"},
  };

  const TRUST_LABELS = {
    verified: {label: "Source officielle vérifiée", tone: "good"},
    unverified: {label: "Source liée, non vérifiée", tone: "warning"},
    contradictory: {label: "Source contradictoire", tone: "danger"},
    missing: {label: "Source officielle absente", tone: "warning"},
  };

  const TIER_LABELS = {
    1: "Page officielle entreprise",
    2: "ATS officiel",
    3: "Plateforme partenaire",
    4: "Agrégateur",
    5: "Saisie manuelle",
  };

  const cache = new Map();
  const pending = new Map();

  function chip(label, tone) {
    const element = document.createElement("span");
    element.className = `job-chip${tone ? ` ${tone}` : ""}`;
    element.textContent = label;
    return element;
  }

  function freshnessChip(freshness) {
    const decision = FRESHNESS_LABELS[freshness?.status] || FRESHNESS_LABELS.unknown;
    let label = decision.label;
    if (typeof freshness?.days_until_deadline === "number") {
      const days = freshness.days_until_deadline;
      label += days < 0 ? " (date limite dépassée)" : ` (J${days})`;
    }
    return chip(label, decision.tone);
  }

  function completenessChip(completeness) {
    const score = Number(completeness?.score);
    const missing = Array.isArray(completeness?.missing_fields) ? completeness.missing_fields.length : 0;
    const tone = !Number.isFinite(score) ? "warning" : score >= 80 ? "good" : score >= 50 ? "warning" : "danger";
    const label = Number.isFinite(score) ? `Complétude ${score}/100` : "Complétude inconnue";
    return missing ? chip(`${label} · ${missing} manquante(s)`, tone) : chip(label, tone);
  }

  function trustChip(trust) {
    const decision = TRUST_LABELS[trust?.status] || TRUST_LABELS.missing;
    const tier = Number(trust?.tier || 0);
    const label = tier && TIER_LABELS[tier] ? `${decision.label} · ${TIER_LABELS[tier]}` : decision.label;
    return chip(label, decision.tone);
  }

  function badges(quality) {
    if (!quality) return [];
    const row = document.createElement("div");
    row.className = "job-chips";
    row.dataset.offerQuality = quality.offer_id || "";
    row.append(freshnessChip(quality.freshness));
    row.append(completenessChip(quality.completeness));
    row.append(trustChip(quality.source_trust));
    const duplicates = Number(quality.deduplication?.duplicate_count || 0);
    if (duplicates > 0) {
      row.append(chip(`${duplicates} source(s) dupliquée(s)`, "warning"));
    }
    return Array.from(row.children);
  }

  async function fetchQuality(offerId) {
    if (!offerId) return null;
    if (cache.has(offerId)) return cache.get(offerId);
    if (pending.has(offerId)) return pending.get(offerId);
    const request = fetch(`/api/career/offer-quality/${encodeURIComponent(offerId)}`, {
      headers: {Accept: "application/json"},
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (payload) cache.set(offerId, payload);
        return payload;
      })
      .catch(() => null)
      .finally(() => pending.delete(offerId));
    pending.set(offerId, request);
    return request;
  }

  function decorate(card, job) {
    if (!card || !job || !job.id) return;
    const row = document.createElement("div");
    row.className = "job-chips offer-quality-badges";
    row.dataset.offerQualityFor = job.id;
    card.append(row);
    fetchQuality(job.id).then((quality) => {
      if (!quality) {
        row.remove();
        return;
      }
      badges(quality).forEach((badge) => row.append(badge));
    });
  }

  async function refresh(offerIds, force) {
    const ids = (Array.isArray(offerIds) ? offerIds : [offerIds]).filter(Boolean);
    if (!ids.length) return null;
    const response = await fetch("/api/career/offer-quality/refresh", {
      method: "POST",
      headers: {"Content-Type": "application/json", Accept: "application/json"},
      body: JSON.stringify({offer_ids: ids, force: Boolean(force)}),
    });
    if (!response.ok) return null;
    const payload = await response.json();
    ids.forEach((offerId) => cache.delete(offerId));
    return payload;
  }

  window.CareerOfferQuality = {
    fetchQuality,
    decorate,
    badges,
    refresh,
    freshnessChip,
    completenessChip,
    trustChip,
    labels: {freshness: FRESHNESS_LABELS, trust: TRUST_LABELS, tier: TIER_LABELS},
  };
})();
