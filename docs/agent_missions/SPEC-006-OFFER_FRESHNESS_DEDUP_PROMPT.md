# MISSION SPEC KIT — SPEC-006 : Offer Freshness, Deduplication & Source Trust

> **Priorité : P1** — Module indépendant, worktree dédié. Repose sur SK-01, SK-02, SK-06.

---

## Contexte

Les offres peuvent être expirées, incomplètes, dupliquées entre sources, ou provenir de sources non fiables. Un excellent générateur de CV n'est utile que si les offres ciblées sont valides.

---

## Objectif

Créer un **module de fraîcheur et qualité** qui garantit : offres actives, complètes, dédupliquées sans perte de provenance, sources officielles prioritaires.

---

## Nouveaux modules à créer

```
career/offer_quality.py         # Core: fraîcheur, complétude, source_trust
career/offer_quality_store.py   # Cache, historique changements
career/router.py                # GET /offer-quality/{offer_id}, POST /offer-quality/refresh
career_static/js/offer-quality.js # Badges UI fraîcheur/source
tests/test_offer_quality.py
docs/agent-reports/SPEC-006-OFFER_QUALITY.md
```

---

## Contrat attendu

### Qualité d'une offre (GET /offer-quality/{offer_id})

```json
{
  "offer_id": 123,
  "freshness": {
    "last_verified_at": "2026-10-21T08:00:00Z",
    "source_url_status": 200,
    "source_url": "https://boards.greenhouse.io/gs/123",
    "is_active": true,
    "deadline_date": "2026-10-25",
    "days_until_deadline": 4,
    "changes_since_last_check": [
      {"field": "deadline_date", "old": null, "new": "2026-10-25", "detected_at": "2026-10-21T08:00:00Z"}
    ]
  },
  "completeness": {
    "score": 84,
    "missing_fields": ["salary_range", "duration_months"],
    "has_requirements": true,
    "has_location": true,
    "has_dates": true
  },
  "source_trust": {
    "status": "verified",
    "provider": "greenhouse",
    "canonical_host": "boards.greenhouse.io",
    "employer_match": "confirmed"
  },
  "deduplication": {
    "canonical_id": "canon_456",
    "sources": [
      {"provider": "greenhouse", "url": "...", "trust": "verified", "raw_id": "123"},
      {"provider": "company_career", "url": "...", "trust": "verified", "raw_id": null}
    ],
    "merged_from": ["greenhouse:123", "company_career:789"],
    "contradictions": []
  }
}
```

### Rafraîchissement contrôlé (POST /offer-quality/refresh)

```json
{
  "offer_ids": [123, 456],
  "force": false
}
```

Réponse : liste des offres avec changements détectés.

### Historique changements

```json
{
  "offer_id": 123,
  "history": [
    {"detected_at": "2026-10-21T08:00:00Z", "field": "deadline_date", "old": null, "new": "2026-10-25"},
    {"detected_at": "2026-10-20T10:00:00Z", "field": "requirements", "old": "...", "new": "..."}
  ]
}
```

---

## Règles de déduplication multi-source

| Priorité | Source |
|----------|--------|
| 1 | Page officielle entreprise |
| 2 | ATS officiel (Greenhouse, Lever, Ashby, SmartRecruiters) |
| 3 | Plateforme partenaire (WJ, JT, Talent, APEC) |
| 4 | Agrégateur |
| 5 | Saisie manuelle |

**Règle** : Conserver TOUTES les sources sous `sources[]`, désigner `canonical_id` unique. Source prioritaire = source principale pour affichage. Contradictions visibles dans `contradictions[]`.

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_offer_quality.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `offer_quality.assess(offer_id) -> OfferQuality` pure
- [ ] Fraîcheur : dernière vérif, statut URL, actif, deadline, changements
- [ ] Complétude : score 0-100, champs manquants listés
- [ ] Source trust : réutilise SK-01
- [ ] Déduplication : canonical_id, sources[], merged_from[], contradictions[]
- [ ] Rafraîchissement contrôlé : POST /refresh, détection changements
- [ ] Historique changements persistant
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-006-OFFER_QUALITY.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-006-offer-freshness-dedup`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.