# SPEC-027 — Simulateur d’entretien STAR

## Livré

| Fichier | Rôle |
|---|---|
| `career/interview_sim.py` | Générateur déterministe de questions + feuilles STAR + auto-évaluation |
| `tests/test_interview_sim.py` | 29 tests (dont adversarial et smoke API) |
| `tests/fixtures/interview_offers_synthetic.json` | 3 offres synthétiques (finance, data, conseil) |
| `career/router.py` | 3 routes REST locales sous `/api/career/interview-sim/…` |
| `career/service.py` | Capacité `interview_sim` exposée par `/api/career/health` |
| `docs/agent-reports/SPEC-027-interview_sim.md` | Ce rapport |

Aucune migration, aucun changement de `SCHEMA_VERSION`, aucun secret, aucun appel réseau.

## Contrat Python

```python
InterviewQuestion(id, kind, question, evidence_needed)
StarWorksheet(question_id, situation, task, action, result,
              evidence_checked, completeness)   # completeness recalculé

build_question_set(offer, *, seed=0, limit=16, language="fr", count=None) -> list[InterviewQuestion]
build_worksheet(question, *, situation="", …, evidence_checked=()) -> StarWorksheet
evidence_checklist(question, *, checked=()) -> list[{"label", "checked"}]
self_score(worksheet, *, question=None, language="fr") -> dict
```

`count` est un alias de compatibilité de `limit` ; `build_questions`, `generate_question_set`, `get_question_set` et `load_fixtures` restent disponibles pour les appelants existants.

`kind` vaut `behavior`, `technical`, `motivation` ou `company`. Chaque appel retourne **au moins 12 questions** (plafond 40) et les quatre familles sont toujours présentes, y compris pour une offre vide ou incomplète.

## Décisions

1. **Génération locale et fermée.** Les mots-clés techniques proviennent d’une bibliothèque explicite (Excel, Python, SQL, étude de marché…). Un acronyme inconnu de l’offre n’est jamais transformé en question inventée.
2. **Déterminisme.** Même offre + même `seed` ⇒ même liste, même ordre. Le `seed` fait tourner les familles et choisit les mots-clés techniques, sans jamais supprimer une famille. L’ordre d’insertion du dictionnaire d’offre n’a aucun effet.
3. **Aucune invention de preuve.** `evidence_needed` ne contient que des preuves à fournir par la personne (exemple daté, action personnelle, résultat vérifiable). L’API ne fabrique jamais un fait de profil.
4. **Auto-évaluation transparente, pas une prédiction.** La note 0–100 décrit la structure du brouillon :
   - ratios par partie, plafonnés à 10 mots (situation 18, tâche 13, action 27, résultat 32 ⇒ 90 points) ;
   - +6 si le résultat contient un chiffre, +4 si l’action est clairement personnelle ;
   - total plafonné à 100.
   Le libellé et le `disclaimer` rappellent explicitement qu’il ne s’agit pas d’une probabilité de recrutement.
5. **Checklist de preuves séparée du score.** `evidence_coverage` mesure les cases cochées ; elle n’augmente pas artificiellement la note STAR.
6. **API sur offre enregistrée.** Les routes lisent l’offre via `CareerService.get_job()` : aucune donnée d’offre n’est acceptée en bloc non vérifié par l’API.

## API

| Méthode | Route | Effet |
|---|---|---|
| `GET` | `/api/career/interview-sim/questions/{job_id}?seed=0&limit=16` | questions + familles + avertissement |
| `GET` | `/api/career/interview-sim/worksheet/{job_id}/{question_id}?seed=0` | feuille vierge + checklist |
| `POST` | `/api/career/interview-sim/worksheet` | note la structure d’un brouillon STAR |

`limit` est borné à `[12, 40]` (422 hors bornes). Une offre ou une question inconnue renvoie 400 avec un message utilisateur.

`/api/career/health` expose désormais :

```json
"interview_sim": {
  "enabled": true,
  "local_only": true,
  "min_questions_per_offer": 12,
  "kinds": ["behavior", "technical", "motivation", "company"],
  "star_worksheets": true,
  "provider_required": false,
  "recruitment_probability": false
}
```

## Exemples vérifiés

Offre `Banque Synthétique — Stagiaire M&A` (fixture synthétique), `seed=0` : 16 questions, ordre `behavior, technical, motivation, company, …`.

- `behavior:deadline` — « Raconte une situation où tu as dû livrer un travail important sous contrainte de temps… »
- `technical:keyword:excel:practice` — « Comment as-tu utilisé « Excel » concrètement dans un projet ou un stage ?… »
- `motivation:company-choice` — « Pourquoi ce poste chez Banque Synthétique plutôt qu’un poste similaire ailleurs ? »

Feuille STAR complète (4 parties ≥ 10 mots, résultat avec « 2 jours », action avec « J’ai ») :
`score=100`, `completeness=1.0`, `label="Structure solide"`. Avec une seule preuve cochée sur trois : `evidence_coverage=0.333` et les deux preuves manquantes sont listées dans `advice`.

## Validation

```text
pytest -q tests/test_interview_sim.py  → 29 passed
ruff check .                           → All checks passed
git diff --check                       → propre
pytest -q (suite complète)             → 1536 passed, 1 failed, 1 skipped
```

L’unique échec est **préexistant sur le commit de base** `091399c` :
`tests/test_career_agent.py::test_local_storage_profile_preferences_and_persistence`
attend `6` familles alors que le modèle en expose `14`. Il a été reproduit dans un worktree détaché sur `091399c`, sans les changements de cette mission ; il n’est donc pas une régression SPEC-027. Le test ignoré est `tests/test_offer_summary_exhaustiveness.py` (« script ou base absents »).

## Réconciliation de branche

Le commit local `3022372` a été fusionné avec le tip distant `f4c5e8d`
(`agent/spec-027-interview-sim`) dans un commit de merge explicite. Cette
implémentation la remplace volontairement, car elle ajoute la checklist de
preuves, la notation structurelle documentée 0–100 et 29 tests (contre 14), tout
en conservant les alias Python et le chargeur de fixtures du tip distant.

Les routes REST restent volontairement limitées aux trois routes auditées
ci-dessus : elles n’acceptent que des offres enregistrées (`get_job`), afin
qu’aucune offre arbitraire ne soit injectée dans le simulateur. Les alias de
routes du tip distant ne sont pas repris.

## Limites

- La note évalue la **structure** d’un brouillon, pas la véracité des faits ni la qualité perçue par un recruteur.
- Les feuilles ne sont pas persistées : l’API est sans état, conformément au périmètre (pas de migration).
- Deux langues de génération (`fr`, `en`) ; toute autre valeur retombe sur le français.
- Le générateur ne couvre que les mots-clés de sa bibliothèque fermée. Une offre très spécialisée reçoit les questions génériques de son secteur, jamais une question inventée sur un outil inconnu.
- Aucun appel LLM, aucune soumission automatique, aucune donnée réelle dans les fixtures.
