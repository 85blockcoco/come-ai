# SPEC-031 — Minage FAQ sectorielle des offres

## Livré

- `career/faq_mining.py`
  - `SectorFaq` (contrat exact : `sector`, `top_terms`, `likely_questions`,
    `profile_answers`) avec `as_dict()` / `to_dict()` JSON-sûrs.
  - `cluster_intents()` : attentes récurrentes par vocabulaire d'intentions
    versionné (`INTENT_KEYWORDS`, `INTENT_LABELS`), comptées **au plus une fois
    par offre** pour qu'une répétition dans une annonce ne gonfle pas le score.
  - `expected_questions()` / `question_for_intent()` : questions probables
    déterministes, ordonnées par fréquence d'intention puis identifiant.
  - `profile_answer_elements()` : extraits **verbatim** du profil ; liste vide
    quand aucune preuve ne correspond (jamais de phrase inventée).
  - `mine_sector_faq()` / `mine_all_sector_faqs()` : regroupement
    secteur/famille de poste, `top_terms` = (terme, fréquence) triés par
    fréquence puis alphabétiquement.
- `tests/test_faq_mining.py` + `tests/fixtures/faq_offers_synthetic.json` :
  13 tests, fixtures 100 % synthétiques (entreprises, offres et profil fictifs).
- Endpoints REST servis par `create_app()` :
  - `POST /api/career/faq-mine` (offres + profil explicites, secteur optionnel) ;
  - `GET /api/career/faq-mine` (offres et profil stockés localement) ;
  - capacité `faq_mining` exposée par `/api/career/health`.
- `CareerService.mine_sector_faq()` : même moteur, sans réseau, utilise
  `list_jobs()` / `get_profile()` quand rien n'est fourni.

## Décisions

- **Local et déterministe** : aucun appel réseau, aucun modèle, aucune horloge.
  Le même jeu d'offres produit toujours la même FAQ (ordre stable garanti par
  les tris `(-count, intent)`, `(-frequence, terme)`).
- **Anti-invention** : les réponses sont des citations du profil fourni. Une
  intention sans preuve donne `[]`. Le texte d'une offre ne peut pas devenir
  une affirmation sur le candidat.
- **Bornes** : `MAX_OFFERS=200`, `MAX_OFFER_TEXT=20 000`, `MAX_TOP_TERMS=100`,
  `MAX_QUESTIONS=50`, `MAX_PROFILE_ITEMS=200` ; `top_n` / `max_questions`
  clampés côté module et validés côté FastAPI (422 hors bornes).
- **Secteur normalisé** : la recherche de secteur ignore casse, accents et
  ponctuation (`m&a / investment banking` = `M&A / Investment Banking`). Un
  secteur connu est restitué sous son **libellé stocké** (deux orthographes
  produisent la même FAQ) ; un secteur inconnu est renvoyé tel quel avec des
  résultats vides plutôt que remplacé silencieusement par le secteur dominant.
- **Compatibilité** : `schema_version` non modifié (8 sur la base d'intégration
  `69b55c6` ; la mission citait 7, version alors en vigueur sur la branche
  d'origine). Aucun schéma SQLite ni migration touchés. Le test REST vérifie
  `PRAGMA user_version` avant/après.

## Validation

```
pytest -q tests/test_faq_mining.py        → 13 passed
ruff check career/faq_mining.py career/router.py career/service.py \
           tests/test_faq_mining.py       → All checks passed
git diff --check                          → propre
```

Suite complète (`pytest -q`) sur le worktree : **2855 passed, 10 skipped,
14 failed**. Les 14 échecs sont **préexistants sur la base `69b55c6`**,
vérifiés en rejouant exactement les mêmes tests dans un worktree propre de la
base (14 failed / 63 passed) ; ils concernent `career/exploration`,
`career/connectors` et `cv_fit`, hors périmètre de cette mission.

`ruff check .` signale **9 erreurs préexistantes** (imports `F401` inutilisés
dans `career/connectors/*.py`), également présentes sur la base. Elles n'ont
pas été corrigées pour ne pas modifier des fichiers hors mission ; les fichiers
livrés ici sont propres.

## Limites

- Heuristique par mots-clés normalisés : pas d'analyse sémantique ni de
  traduction ; une intention non couverte par le vocabulaire n'est pas détectée.
- Le texte d'une offre est lu depuis `requirements`, sinon
  `description_original` / `description` / `notes` (première valeur non vide),
  pas depuis l'ensemble concaténé.
- `likely_questions` reste générique (pas de formulation propre à une
  entreprise) afin de ne jamais affirmer un fait non vérifié.
- `GET /api/career/faq-mine` sans offre locale et sans secteur renvoie `[]` ;
  avec un secteur explicite il renvoie une FAQ vide honnête pour ce secteur.
