# MISSION SPEC KIT — SK-09 : Recherche quotidienne et offres nouvelles

> **Priorité : P1** — Après SK-07 (Offer Intelligence Bridge).

---

## Objectif

Afficher sur l'accueil :
- Nouvelles offres depuis dernière visite
- Offres mises à jour
- Échéances proches
- Offres devenues indisponibles
- Meilleures offres compatibles
- Sources en panne
- Dernière actualisation

---

## Contraintes

- **Cache avec expiration** (TTL configurable)
- **Rafraîchissement manuel d'abord** (pas auto au chargement)
- **Modèle `launchd` documenté**, mais **aucune installation automatique**
- **Maximum 2 sources simultanées** (réutilise SK-05)
- **Reprise après interruption**
- **Pas de remplissage artificiel**
- **Offres déjà rejetées ou vues séparées**
- **Paris et France exclus** par critères actuels

---

## Résultat attendu

L'utilisateur ouvre Côme AI et comprend en **< 30 secondes** :
- Ce qui est **nouveau**
- Ce qui **mérite son attention**
- Ce qui **va expirer**
- Ce qui **reste incertain**

---

## Données à afficher (par catégorie)

```json
{
  "new_offers": [{"offer_id", "title", "employer", "location", "published_date", "match_score", "source_trust"}],
  "updated_offers": [{"offer_id", "title", "changed_fields", "updated_at"}],
  "expiring_soon": [{"offer_id", "title", "deadline_date", "days_left"}],
  "unavailable": [{"offer_id", "title", "reason", "detected_at"}],
  "top_matches": [{"offer_id", "title", "fit_score", "missing_critical_count"}],
  "broken_sources": [{"source", "error", "last_failure", "retry_at"}],
  "last_refresh": "ISO8601",
  "cache_expires_at": "ISO8601"
}
```

---

## Modules

```
career/daily_digest.py           # Agrégation, cache, TTL
career/router.py                 # Endpoint GET /career/daily
career_static/js/daily-digest.js # Frontend
tests/test_daily_digest.py
```

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

- [ ] Cache TTL fonctionnel, refresh manuel
- [ ] 7 catégories affichées
- [ ] launchd documenté (pas auto-install)
- [ ] Max 2 sources simultanées
- [ ] Reprise interruption
- [ ] Paris/France exclus
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK09-DAILY_SEARCH.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk09-daily-search`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.