# MISSION SPEC-045 — Réponses types copiables (formulaires d'offre)

> **Priorité : P0** — Réduire le frottement des formulaires ATS (retaper sans cesse les mêmes réponses).

## Contexte
Le profil est déjà stocké (`GET /api/career/profile`, préférences). Côme doit recopier
20 fois par jour : date de début, autorisation, langues, mobilité, école, durée de stage…

## Mission — `career/quick_answers.py`
- `build_answer_pack(profile, job, preferences, lang="fr") -> list[Answer]` :
  questions couvertes (non exhaustif) : disponibilité/date de début, autorisation de travail,
  langues + niveaux, diplôme/école en cours, durée de stage, mobilité/ville, situation actuelle,
  motivation courte (2 phrases template basé sur l'offre), prétentions si préférences présentes.
- Chaque réponse trace `source_field` (ex. `profile.availability_start`) et `confidence` :
  `exact` (profil direct), `derived` (calculée), `missing` (à compléter par l'humain).
  **Jamais inventer une valeur** : pas d'info → confidence=missing, value="".
- Valeurs : texte brut copiable (pas de markdown).
- Endpoints : `GET /api/career/quick-answers/{job_id}` (+ `?lang=en` → questions en anglais,
  réponses depuis les champs EN du profil si disponibles).

## Contrats
```python
@dataclass
class Answer:
    label: str
    value: str
    source_field: str
    confidence: Literal["exact","derived","missing"]
```

## Livrables
1. Module + endpoint, smoke test.
2. Tests `tests/test_quick_answers.py` : profil complet, incomplet, lang=en, zéro invention.
3. Ruff propre ; fixtures synthétiques ; push sur `agent/spec-045-quick-answers`.

## Cadre commun (toutes missions, non négociable)
- Aucune soumission automatique de candidature ; aucune donnée réelle.
- Tests ciblés vert + `ruff check career/` ; ne pas lancer la suite complète pendant les jobs en fond.
- API via le pattern career existant, ne pas casser `schema_version=7`.
- Push UNIQUEMENT sur ta branche dédiée (jamais main) ; preuve = branche poussée + tests rejoués.
- Rapport succinct dans `docs/agent-reports/`.
