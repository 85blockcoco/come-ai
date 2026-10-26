# SPEC-045 — Réponses types copiables pour formulaires d'offre (CVBOOST-82)

**Statut :** livré
**Branche :** `agent/spec-045-quick-answers` (depuis `worker/cvboost-82-1793026610854`)
**Périmètre :** module pur + endpoint REST + tests — aucune soumission automatique, aucune donnée réelle.

## Livré

### 1. `career/quick_answers.py`
- Contrat `Answer` (dataclass figée) : `label`, `value`, `source_field`, `confidence ∈ {exact, derived, missing}`, plus `to_dict()`.
- `build_answer_pack(profile, job, preferences, lang="fr") -> list[Answer]` — 9 réponses dans un ordre stable :
  1. Date de début souhaitée — `profile.availability_start` sinon `preferences.availability.availability_start` (exact).
  2. Autorisation de travail — transcription directe de `profile.eligibility` : compatible→Oui/Yes, incompatible→Non/No (exact) ; `unknown` → missing.
  3. Langues et niveaux — `profile.languages` (exact).
  4. Formation / école en cours — `profile.education` (exact).
  5. Durée de stage souhaitée — plage `minimum/maximum_duration_months` des préférences (« 3 à 6 mois ») ; borne unique acceptée (« À partir de 3 mois » / « Jusqu'à 6 mois ») ; min>max ou valeur non numérique → missing (dérivé).
  6. Mobilité / villes — labels des lieux activés de `preferences.locations`, joints par « , » (dérivé).
  7. Situation actuelle — `profile.education` copié verbatim (dérivé : le tracker n'a pas de champ dédié ; aucune valeur fabriquée).
  8. Motivation courte — template de 2 phrases à partir de `job.title`+`job.company` (dérivé) ; FR et EN.
  9. Prétentions (salaire) — uniquement si une préférence `salary_expectation` (ou alias) est stockée (exact) ; sinon missing.
- **Zéro invention** : pas d'info → `confidence="missing"`, `value=""`. Valeurs en texte brut copiable (pas de markdown).
- `lang="en"` : questions/labels et réponses template en anglais ; les valeurs profil sont prises dans les champs EN s'ils existent, sinon le texte stocké est gardé tel quel. Langue non supportée → `UserFacingError`.
- Aucun appel réseau, aucun modèle IA, déterministe.

### 2. Endpoint REST
- `GET /api/career/quick-answers/{job_id}` (+ `?lang=en`) dans `career/router.py`, délégué à `CareerService.get_quick_answers` (profil + préférences + offre locaux ; `automatic_submission: false` + avertissement « aucune valeur n'est inventée »).
- Offre inconnue ou langue invalide → 400 via `UserFacingError`.

### 3. Tests — `tests/test_quick_answers.py` (12 tests)
- Profil complet : valeurs, confiances et `source_field` exacts pour les 9 réponses.
- Profil vide : 9 × (missing, value=""), chaque réponse tracée.
- Zéro invention : éligibilité `unknown`, réglages de durée incohérents ou invalides, prétentions absentes → toujours missing.
- Traçage : `profile.availability_start` prioritaire sur les préférences.
- `lang=en` : labels EN, template EN, valeurs profil conservées.
- Texte brut : aucun marqueur markdown.
- Smoke REST : 200 + schéma des réponses, `?lang=en`, 400 offre inconnue / langue invalide.

## Preuves
- `.venv/bin/python -m pytest -q tests/test_quick_answers.py` → **12 passed**
- Régression ciblée : `tests/test_career_explorer_web.py tests/test_career_application_kit.py tests/integration/test_us1_prep_panel.py` → **22 passed**
- `.venv/bin/python -m ruff check career/ tests/test_quick_answers.py` → **All checks passed!**
- `schema_version=7` inchangé (aucune migration, aucune table modifiée).

## Hors périmètre respecté
Pas d'UI (branchement écran à venir), pas de soumission automatique, pas de donnée réelle.
