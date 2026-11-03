# MISSION SPEC KIT — SPEC-005 : Daily Application Command Center

> **Priorité : P1** — Module indépendant, worktree dédié. Améliore usage quotidien sans modèle IA.

---

## Contexte

Le pipeline existe (offres → matching → kit → candidature). Il manque un **cockpit quotidien** qui dit à l'utilisateur : "Voici ce qui compte aujourd'hui".

---

## Objectif

Créer une page **"Aujourd'hui"** (cockpit) qui agrège les actions urgentes, opportunités et progression, avec export calendrier local.

---

## Nouveaux modules à créer

```
career/daily_digest.py          # Agrégation quotidienne
career/daily_digest_store.py    # Cache TTL, persistence
career/router.py                # GET /career/daily, GET /career/daily/ics
career_static/js/daily-digest.js # UI cartes + actions
tests/test_daily_digest.py
docs/agent-reports/SPEC-005-DAILY_COMMAND_CENTER.md
```

---

## Contrat attendu

### Données retournées (GET /career/daily)

```json
{
  "date": "2026-10-21",
  "urgent": [
    {
      "type": "expiring_offer",
      "offer_id": 123,
      "title": "Goldman Sachs — M&A Analyst",
      "employer": "Goldman Sachs",
      "deadline_date": "2026-10-23",
      "days_left": 2,
      "match_score": 86,
      "action_label": "Candidater avant clôture",
      "action_url": "/career/offers/123/prep"
    },
    {
      "type": "followup_due",
      "application_id": 456,
      "offer_title": "J.P. Morgan — IBD Summer",
      "sent_date": "2026-10-14",
      "days_since_sent": 7,
      "action_label": "Relancer",
      "action_url": "/career/applications/456/followup"
    }
  ],
  "opportunities": [
    {
      "offer_id": 789,
      "title": "Morgan Stanley — Equity Research",
      "employer": "Morgan Stanley",
      "location": "London",
      "match_score": 92,
      "mandatory_coverage": "8/9",
      "source_trust": "verified",
      "published_days_ago": 1
    }
  ],
  "progression": {
    "prepared_this_week": 3,
    "sent_this_week": 1,
    "responses_this_week": 0,
    "interviews_this_week": 1,
    "rejections_this_week": 0,
    "conversion_rate": 0.25
  },
  "last_refresh": "2026-10-21T08:00:00Z",
  "cache_expires_at": "2026-10-21T12:00:00Z"
}
```

### Export calendrier (GET /career/daily/ics)

Fichier `.ics` avec :
- Échéances offres (DTEND = deadline)
- Relances suggérées (DTSTART = suggested_followup_date)
- Entretiens planifiés
- UID déterministes pour mise à jour

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_daily_digest.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `daily_digest.compute_daily(user_id) -> DailyDigest` pure, déterministe
- [ ] Cache TTL (4h par défaut, configurable)
- [ ] Refresh manuel bouton "Actualiser" (invalide cache)
- [ ] Export ICS valide (RRULE pour relances récurrentes)
- [ ] Paris/France exclus par défaut
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-005-DAILY_COMMAND_CENTER.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-005-daily-command-center`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.