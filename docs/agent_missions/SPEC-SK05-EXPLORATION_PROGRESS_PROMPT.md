# MISSION SPEC KIT — SK-05 : Progression serveur réelle de l'exploration

> **Priorité : P1, avec dette constitutionnelle** — Touche service, routeur, interface. Peut tourner en parallèle SK-01→SK-04 mais pas sur mêmes fichiers.

---

## Contexte

La barre actuelle est une estimation. La constitution demande à terme une **progression fondée sur des étapes réelles** terminées côté serveur.

---

## Architecture recommandée

### API Exploration

```
POST   /api/career/stage-search/explorations
GET    /api/career/stage-search/explorations/{run_id}
POST   /api/career/stage-search/explorations/{run_id}/cancel
```

### État attendu (GET)

```json
{
  "run_id": "...",
  "status": "running",
  "sources_total": 21,
  "sources_completed": 8,
  "sources_succeeded": 7,
  "sources_failed": 1,
  "offers_read": 340,
  "offers_qualified": 57,
  "phase": "qualifying",
  "cancel_requested": false
}
```

### Phases réelles (ordre séquentiel)

1. `preparing` — Initialisation, planification sources
2. `consulting` — Consultation sources (max 2 simultanées)
3. `normalizing` — Normalisation offres brutes
4. `qualifying` — Qualification (dates, prérequis, géo, trust)
5. `deduplicating` — Déduplication multi-sources
6. `ranking` — Classement (geo_score, matching, etc.)
7. `persisting` — Sauvegarde snapshots
8. `completed` — Terminé

---

## Critères non négociables

- **Aucune progression fictive** — chaque incrément = étape réelle terminée
- **Reprise possible** après rechargement page (GET run_id)
- **Annulation coopérative** entre deux sources (cancel_requested)
- **Maximum 2 sources simultanées**
- **Recherche interrompue conserve résultats précédents**
- **Erreurs partielles ne détruisent pas** offres déjà collectées
- **Aucun processus orphelin** — nettoyage garanti

---

## Modules à créer/modifier

```
career/exploration_run.py       # Modèle run, état, persistence
career/exploration_service.py   # Orchestration phases, max 2 sources
career/router.py                # Endpoints POST/GET/CANCEL
career_static/js/exploration-progress.js  # Frontend polling
tests/test_exploration_progress.py
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_exploration_progress.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Endpoints API créés et fonctionnels
- [ ] Phases réelles séquentielles, max 2 sources parallèles
- [ ] État persistant, reprise après rechargement
- [ ] Annulation coopérative entre sources
- [ ] Résultats conservés si interruption
- [ ] Erreurs partielles isolées
- [ ] Frontend polling affiche phase, sources_completed/succeeded/failed, offers_read/qualified
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK05-EXPLORATION_PROGRESS.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk05-exploration-progress`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.