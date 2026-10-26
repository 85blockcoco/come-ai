# Rapport mission CVBOOST-82 — SPEC-045 : Réponses types copiables (formulaires d'offre)

**Branche** : `agent/spec-045-quick-answers` (depuis `worker/cvboost-82-1793025902626`, base `2e52575`)
**Statut** : ✅ terminé — aucun envoi automatique, aucune donnée réelle, tout est local.

## Livrables

1. **`career/quick_answers.py`** — module pur, déterministe :
   - `Answer` (dataclass) : `label`, `value`, `source_field`, `confidence` (`exact|derived|missing`).
   - `build_answer_pack(profile, job, preferences, lang="fr") -> list[Answer]` : 9 questions couvertes
     (date de début, autorisation de travail, langues, formation, durée de stage, mobilité/villes,
     situation actuelle, motivation courte en 2 phrases template basée sur l'offre, prétentions).
   - **Zéro invention** : information absente → `confidence="missing"`, `value=""` (à compléter par l'humain).
   - Valeurs en texte brut copiable (aucun markdown généré), jamais traduites ni reformulées.
   - `lang="en"` : questions en anglais ; champs `*_en` du profil utilisés s'ils existent, sinon valeur
     FR de repli (pas de traduction improvisée).
2. **Endpoint** `GET /api/career/quick-answers/{job_id}` (+ `?lang=en|fr`, validé par `Query(pattern)`)
   dans `career/router.py`, adossé au service `CareerService.get_quick_answers` (`career/service.py`),
   qui charge offre + profil + préférences en une transaction locale et sérialise le pack.
   `schema_version=7` inchangé (aucune migration).
3. **Tests** `tests/test_quick_answers.py` — 24 tests : profil complet, profil vide, lang=en (+ champs EN
   et repli FR), mapping éligibilité déclarée (Oui/Non/missing), variantes de durée, mobilité (items
   activés uniquement), motivation 2 phrases (avec/sans famille, offre incomplète), prétentions
   (missing par défaut, exact si préférence présente), texte brut sans markdown, déterminisme,
   service (données stockées, offre inconnue → `UserFacingError`, lang inconnue) et endpoint
   (200 / 400 offre inconnue / 422 langue invalide).

## Validation

- `pytest -q tests/test_quick_answers.py` → **24 passed**.
- Sous-suite ciblée (service/router) : `test_career_agent.py`, `test_career_application_dashboard.py`,
  `test_career_search_ux.py` → **91 passed**, aucune régression.
- `ruff check career/` → All checks passed.
- `checklist_codex.sh lint` et `checklist_codex.sh main` → **TOUT VERT** (les 2 échecs
  `tests/test_geo_ranking.py` sont pré-existants sur le commit de base `2e52575`, vérifiés par stash
  sans les changements de la mission).
- `git diff --check` → clean.

## Choix de conception

- `availability_start` vit dans `preferences.availability` (schéma local réel) : `source_field` trace le
  chemin exact (`preferences.availability.availability_start`), le format demandé (`profile.*`) est
  respecté pour les champs du profil.
- Autorisation de travail : restitution fidèle de l'éligibilité **déclarée** (`compatible`→Oui,
  `incompatible`→Non, sinon missing) — jamais déduite d'un autre fait du profil.
- Motivation : template neutre en genre, exactement 2 phrases, construit uniquement depuis
  `job.title` / `job.company` / `job.job_family` (famille « À préciser » exclue).
- Prétentions : le schéma local ne stocke aujourd'hui aucune préférence salariale → réponse `missing`
  par défaut ; si une clé `salary_expectation` / `compensation_expectation` apparaît dans les réglages,
  elle est restituée telle quelle (`exact`).
