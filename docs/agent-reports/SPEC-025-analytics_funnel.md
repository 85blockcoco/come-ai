# SPEC-025 — Analytics funnel candidatures (CVBOOST-60)

## Livré

| Fichier | Rôle |
| --- | --- |
| `career/analytics_funnel.py` | Module pur : `compute_funnel()`, `funnel_by_channel()`, `weakest_stage()`, `FunnelStage`, `FunnelReport` |
| `career/service.py` | `CareerService.analytics_funnel(channel="")` — lecture SQL bornée (5 000 candidatures), sans migration |
| `career/router.py` | `GET /api/career/analytics/funnel?channel=` servi par `create_app()` |
| `tests/test_analytics_funnel.py` | 19 tests (contrat, cas limites, adversarial, intégration service + API) |
| `tests/fixtures/analytics_synthetic.json` | 8 candidatures **synthétiques** (aucune donnée réelle) |

L'entonnoir expose les 7 étapes du contrat — `sent`, `viewed`, `prepped`,
`lettered`, `followed_up`, `interview`, `offer` — avec compteur et conversion
depuis l'étape précédente, une série par semaine ISO, une lecture par canal de
source et l'étape goulot.

## Décisions

1. **Comptes bruts, jamais inventés.** Chaque compteur est le nombre de
   candidatures ayant réellement démontré le jalon :
   - `sent` : statut de dépôt déclaré (`receipt_unknown`, `submitted`,
     `submitted_confirmed`, `response_received`, `interview`, `offer_received`),
     référence de réception confirmée, ou événement structuré d'envoi. **Une
     ligne SQLite ne suffit jamais** : une candidature seulement créée ou
     préparée n'est pas « envoyée ».
   - `viewed` : réception confirmée ou réponse/entretien/offre. C'est un
     **proxy local** : Career ne sait pas si un recruteur a ouvert le dossier.
   - `prepped` : brouillon/kit local, ou checklist (`cv_reviewed`,
     `documents_checked`, `deadline_verified`).
   - `lettered` : lettre matérialisée (brouillon, `kit_content`) ou case
     `letter_customized`.
   - `followed_up` : case `followup_planned` ou événement de relance. Career
     n'envoie aucun e-mail : c'est une **relance planifiée localement**.
   - `interview` / `offer` : statut courant ou événement structuré.

2. **Aucun texte libre interprété.** Le champ `detail` d'une note
   (`« envoyée lundi »`) n'est jamais une preuve ; seuls le statut, les
   événements typés, la checklist et les brouillons comptent.

3. **Jalons logiquement impliqués.** Un statut `interview` ou
   `offer_received` prouve le dépôt et la consultation (on n'obtient pas un
   entretien sans candidature envoyée). Une lettre prouve aussi une
   préparation. Ces implications n'inventent aucun jalon non déductible :
   une offre ne prouve ni relance ni lettre.

4. **Conversions dans `[0, 1]`.** L'ordre imposé par le contrat n'est pas
   strictement séquentiel dans les données locales (une lettre peut précéder
   l'envoi, une relance planifiée peut manquer). Un jalon peut donc concerner
   plus de candidatures que le précédent : la conversion est alors
   **plafonnée à 100 %** plutôt que gonflée. Aucune division par zéro : sans
   étape précédente renseignée, la conversion vaut `0.0`.

5. **Goulot.** Plus faible conversion parmi les transitions observées
   (dénominateur non nul) ; à égalité, la plus grosse perte absolue puis
   l'étape la plus précoce. Entonnoir vide → `bottleneck_stage = ""`
   (aucun goulot inventé).

6. **Semaines et canaux.** Cohorte = semaine ISO de `created_at`, normalisée
   en UTC (un horodatage illisible est exclu, jamais rangé dans une fausse
   semaine). Canal = `jobs.source_name` normalisé (minuscules, espaces
   compactés) ; vide → `unknown`. Le filtre `channel` est insensible à la
   casse ; un canal inconnu renvoie un rapport dégénéré cohérent (200), pas
   une erreur.

7. **Aucune migration.** Le module est une projection pure du journal
   existant. `SCHEMA_VERSION` reste `8` (le prompt mentionnait `7`, obsolète :
   la base est déjà en 8 dans cette base de code) ; `PRAGMA user_version`
   inchangé, vérifié par test.

## Limites

- Pas de tracking d'ouverture réel : `viewed` reste un proxy (réception
  confirmée/réponse).
- `followed_up` mesure une intention locale, pas un message envoyé.
- Le canal dépend de la qualité de `source_name` à l'import ; un import
  manuel apparaît comme `manual`.
- Lecture plafonnée aux 5 000 candidatures les plus anciennes (ordre
  `created_at`) pour borner la mémoire ; aucun échantillonnage aléatoire.
- Les fixtures sont synthétiques ; aucun test ne lit la base réelle.

## Vérifications

```text
pytest -q tests/test_analytics_funnel.py          → 19 passed
pytest -q                                         → 1526 passed, 1 skipped, 1 failed
ruff check career/ analytics tests/test_analytics_funnel.py → All checks passed
git diff --check                                  → CLEAN
```

Le seul échec de la suite complète,
`tests/test_career_agent.py::test_local_storage_profile_preferences_and_persistence`,
est **antérieur et étranger à cette mission** : il échoue de la même façon sur
la base `a093c49` sans aucune modification (préférences par défaut attendues à
6, 14 obtenues). Aucune régression introduite par SPEC-025.
