# SPEC-010 — Assistant d'entretien ciblé

Date : 22 octobre 2026
Branche : `worker/cvboost-40-1792650659` (worktree dédié
`AI-Excel-Agent-worker-cvboost-40-1792650659`, base `f5b22f2`)
Commande : `cvboost-40-1792650659`

Aucune dépendance ajoutée, aucun modèle, aucun appel réseau, aucune donnée réelle
dans les fixtures.

## 1. Ce qui a été construit

| Fichier | Nature | Contenu |
|---|---|---|
| `career/interview_prep.py` | **nouveau** (1 975 lignes) | Moteur de préparation : dataclasses du contrat, 8 banques finance, génération, simulation, sérialisation, rendu Markdown. |
| `career/interview_store.py` | **nouveau** (323 lignes) | Persistance locale SQLite des sessions et de l'historique de simulation. |
| `career_static/js/interview-prep.js` | **nouveau** (467 lignes) | UI : onglets, mode simulation chronométrée, retour structuré, export. |
| `tests/test_interview_prep.py` | **nouveau** (567 lignes) | 28 tests (dont un test Node qui *exécute* le chrono et le rendu du feedback). |
| `docs/agent-reports/SPEC-010-INTERVIEW_PREP.md` | **nouveau** | Ce rapport. |
| `career/router.py` | modifié | 6 routes `/api/career/interview-prep/…` + 3 payloads Pydantic + accroche du contexte local. |
| `career/service.py` | modifié | 9 méthodes de service, initialisation du store, capacité `interview_prep`, effacement des données. |
| `career_static/index.html` | modifié | Panneau « Assistant d'entretien » (5 onglets + simulation) + balise `<script>`. |
| `career_static/career.js` | modifié | 3 lignes : `interviewPrepWire()` + `loadInterviewPrep()` dans `loadCoach()`. |
| `career_static/career.css` | modifié | 22 lignes de styles réutilisant les tokens existants. |

## 2. Contrat livré

### 2.1 Les dataclasses demandées

Les quatre dataclasses du cahier des charges sont reprises **à l'identique** (mêmes noms,
mêmes champs, mêmes types `Literal`) dans `career/interview_prep.py` :

- `InterviewQuestion(id, category, question, expected_elements, related_evidence,
  related_requirement, difficulty, time_estimate_seconds)` ;
- `CompanyFactsheet(name, sector, size, recent_news, culture_keywords, interview_process, sources)` ;
- `InterviewPrepSession(session_id, offer_id, profile_id, technical_questions,
  behavioral_questions, gap_questions, sensitive_points, recruiter_questions,
  company_factsheet, created_at)` ;
- `SimulationFeedback(question_id, user_answer, score, strengths, missing_elements,
  unproven_claims, suggested_structure, retry_prompt, pedagogical_source)`.

Deux dataclasses **internes** complètent le modèle sans le modifier : `PrepQuestion`
(question publique + clés de correspondance déterministes + source pédagogique) et
`Preparation` (session + enregistrements internes, sérialisable vers/depuis le store).

### 2.2 Point d'entrée

```python
interview_prep.generate(offer_id, profile_id, mode) -> InterviewPrepSession
```

`generate()` délègue à `build_preparation()`, qui accepte soit les enregistrements déjà
chargés (`offer=`, `profile=`), soit un `PrepContext` (deux callables `load_offer` /
`load_profile`), soit le contexte par défaut lié par la couche web
(`interview_prep.bind_default_context(...)`, appelé dans `create_career_router`).
Les trois chemins sont couverts par les tests.

### 2.3 Les endpoints

```
POST /api/career/interview-prep/generate             → InterviewPrepSession (201)
GET  /api/career/interview-prep                       → liste des préparations
GET  /api/career/interview-prep/{session_id}          → InterviewPrepSession
POST /api/career/interview-prep/simulate              → SimulationFeedback
GET  /api/career/interview-prep/{session_id}/history  → historique des simulations
POST /api/career/interview-prep/{session_id}/export   → fichier Markdown ou PDF
GET  /api/career/interview-prep/{session_id}/export/{md|pdf}  → même export, lien direct
DELETE /api/career/interview-prep/{session_id}        → suppression
```

Les routes littérales (`/generate`, `/simulate`) sont enregistrées **avant** la route
paramétrée, pour qu'un identifiant de session ne puisse jamais être lu comme un verbe
(commentaire explicite dans le code, même principe que la route `/applications/dashboard`).
La route `GET …/export/{format}` est un ajout : elle permet au navigateur de télécharger
le fichier par un simple lien, sans construire d'URL `blob:` (la CSP du projet est
`default-src 'self'`).

Les entrées invalides remontent en **HTTP 400** via `UserFacingError` (message français),
les payloads hors contrat en **422**.

### 2.4 Les 8 banques finance

| Banque | Questions | Source pédagogique citée |
|---|---|---|
| M&A | 4 | Rosenbaum & Pearl (*Investment Banking*), partie « M&A Process » / « Due Diligence » ; Damodaran (*Investment Valuation*), « The Dark Side of Valuation » ; Brealey-Myers-Allen, « Mergers and the Market for Corporate Control » |
| Valuation | 4 | Rosenbaum & Pearl, partie « Valuation » ; Damodaran, « Valuing the Firm » et « The Value of Control » |
| LBO | 4 | Rosenbaum & Pearl, partie « Leveraged Buyouts » ; Damodaran, « Valuing Equity in Private Firms » |
| Marchés | 4 | Hull (*Options, Futures and Other Derivatives*), « The Greeks », « The Volatility Smile », « Exotic Options », « Static Replication of Derivatives » |
| Produits dérivés | 3 | Hull, « Forward and Forward Futures », « Swaps », « Options » / « Put-Call Parity » |
| FP&A | 3 | Hilton (*Managerial Accounting*), « Profit Planning » et « Budgeting » ; Kaplan-Atkinson, « Profit Planning and Budgetary Planning » |
| Contrôle de gestion | 3 | Horngren (*Cost Accounting*), « Standard Costs and Variances » ; Kaplan-Atkinson, « Responsibility Accounting and Transfer Pricing » |
| Probabilités | 3 | Mosteller (*Fifty Challenging Problems in Probability*) ; Ross-Westerfield-Jaffe, « Risk and Return » ; Hull, « Simulation Methods » |

Soit **28 questions de banque**, chacune avec ses points attendus, sa difficulté, son temps
conseillé et **sa source pédagogique**. Les banques sont sélectionnées par *affinité
lexicale* avec le texte réel de l'offre (`_bank_affinity`) : une offre M&A/LBO active les
banques M&A, Valuation et LBO.

Le mode standard ne cite pas de banque finance : les questions comportementales renvoient
à Kim, *The Manager's Book of Questions* (méthode STAR). Aucune source n'est inventée :
les références sont les ouvrages canoniques, citées par leur **titre de chapitre ou de
partie** plutôt que par un numéro de chapitre, pour rester vérifiables d'une édition à
l'autre.

### 2.5 Le mode simulation

`simulate(preparation, question_id, user_answer, profile=…)` renvoie un
`SimulationFeedback` :

- **couverture** : chaque point attendu possède un groupe de mots-clés déterministe,
  dérivé de son énoncé (verbes d'ouverture retirés, mots génériques exclus, liste blanche
  pour les sigles courts `lbo`, `dcf`, `irr`, `moic`, `sap`…). Un point est couvert si la
  réponse contient un mot-clé long (≥ 5 caractères) ou deux mots-clés ;
- **structure** : marqueurs de raisonnement bilingues (d'abord / premièrement / … ;
  first / then / finally / …) ;
- **score** : `excellent` (couverture ≥ 80 %, structure ≥ 70, réponse développée),
  `good` (couverture ≥ 50 %), `needs_improvement`, `insufficient` ;
- **affirmations non prouvées** : les phrases qui affirment une réalisation
  (« j'ai dirigé… », « j'ai augmenté de X % », « expert en… », « plus de N ans ») sont
  détectées puis confrontées au profil local ; un chiffre absent du profil ou moins de
  deux signaux de contenu communs font basculer l'affirmation dans
  `unproven_claims` ;
- **structure suggérée** : STAR pour le comportemental, STAR adapté à l'écart, approche
  en quatre temps pour la technique ;
- **retry prompt** : reformule le premier point attendu manquant ;
- **source pédagogique** : reprise de la source de la question (None en standard pour
  les questions issues de l'offre).

### 2.6 L'UI (`career_static/js/interview-prep.js`)

Module classique chargé en `defer` **avant** `career.js` ; il ne touche pas au DOM au
chargement et expose `loadInterviewPrep()` / `interviewPrepWire()` appelées depuis
`loadCoach()`.

- Onglets **Technique | Comportemental | Écart | Recruteur | Entreprise** (rôles
  `tablist`/`tab`/`tabpanel`, `aria-selected`).
- Mode simulation : question → points attendus → zone de réponse → **chrono** (temps
  conseillé, temps réel, alerte « temps dépassé ») → Soumettre → feedback structuré
  (score, forces, manquants, non-prouvés, structure, retry, source pédagogique).
- Export Markdown / PDF par lien direct vers la route d'export.
- Historique des simulations affiché sous le panneau.
- Construction du DOM sans `innerHTML` (helper `make()` de `career.js`), cohérent avec
  `cv_plan.js`.

Le panneau est intégré **dans** l'onglet « Coach d'entretien » existant : aucune nouvelle
vue de premier niveau n'est créée, donc les tests de garde qui énumèrent les
`data-view` restent valides.

## 3. Preuves réelles

Commandes exécutées depuis le worktree
`/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-40-1792650659`
(venv du dépôt principal : `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python`).

```
$ python -m pytest -q tests/test_interview_prep.py
...........................                                             [100%]
28 passed in 6.75s

$ python -m pytest -q
1452 passed, 1 skipped in 96.10s        (SKIPPED : tests/test_offer_summary_exhaustiveness.py — script ou base absents)

$ python -m ruff check .
All checks passed!

$ git diff --check
(propre — aucune sortie)

$ VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python ./checklist_codex.sh
… ✓ main tests passés … ✓ aucun secret tracké … ✓ DevKit vert … All checks passed! … ✓ rappel affiché
TOUT VERT
```

Vérification manuelle de bout en bout (application complète `create_app`) :

```
GET /career                        → 200 (60 777 octets, contient /career-static/js/interview-prep.js)
GET /career-static/js/interview-prep.js → 200 text/javascript (17 600 octets)
GET /api/career/health             → interview_prep : {enabled: true, local_text_only: true,
                                     modes: [standard, finance], finance_banks: 8,
                                     formats: [md, pdf], provider_required: false,
                                     recruitment_probability: false}
```

Preuves statiques incluses dans la suite :

- `tests/test_interview_prep.py::test_the_new_modules_never_reach_the_network` —
  `career/interview_prep.py` et `career/interview_store.py` ne contiennent ni
  `subprocess`, `socket`, `urllib`, `requests`, `httpx`, `eval(`, `exec(` ni `pickle` ;
- `test_the_static_ui_module_is_served_and_wired` — la balise `<script>` est dans
  `index.html`, les 5 onglets sont dans le HTML, aucun `innerHTML` dans le module ;
- `test_the_chrono_and_the_feedback_render_in_a_browser_like_context` — le module JS est
  **exécuté sous Node** avec un DOM stubé : le chrono affiche `1:30` de temps conseillé,
  `0:00` puis `1:35` de temps écoulé, déclenche l'alerte « temps dépassé » et la masque
  une fois revenu dans le temps, et le feedback rend bien score / manquants /
  affirmations non prouvées / structure / retry / source pédagogique.

## 4. Décisions d'architecture

1. **Store SQLite séparé** (`career_data/interview_prep.sqlite3`, mode `0600`) plutôt
   qu'une table dans `career.sqlite3` : ajouter une table aurait imposé un
   `SCHEMA_VERSION = 9` et une migration avec sauvegarde, pour un module indépendant.
   Le fichier dédié garde `career/service.py` et le schéma principal intacts. Il est
   purgé par `reset_personal_data()`.
2. **SK-03 / SK-10 non fusionnés dans cette base** : le moteur d'adéquation disponible
   est `career/application_prep.py` (comparaison exigences ↔ profil, dépôt de preuves
   verbatim) ; les identifiants d'exigence et la provenance viennent de
   `career/offer_requirements.analyze_offer()`. Le code est écrit pour que
   `career/requirements_fit.py` (SK-03) puisse remplacer `prepare_application()` sans
   changer le contrat public : seul le producteur de « gap » est encapsulé.
3. **`profile_id` / `offer_id`** : l'espace local ne connaît qu'un profil (singleton
   `candidate_profile.id = 1`) et des identifiants d'offre de type `job_<uuid4hex>`. Le
   module accepte donc `"user_profile"` (et `""`) comme identifiant de profil, refuse
   toute autre valeur, et lit `offer_id` comme une chaîne. La valeur `123` du cahier
   des charges reste acceptée côté API (elle est convertie en identifiant textuel).
4. **Aucune route de premier niveau ajoutée** dans l'UI : le panneau vit dans
   « Coach d'entretien », ce qui évite de casser les deux tests de garde qui énumèrent
   les vues autorisées.
5. **`recent_news` reste vide** et **`size` vaut « Non renseignée par l'offre »** : aucun
   appel externe n'est possible, donc aucune actualité ni taille de société ne peut être
   affirmée. C'est un choix de conception assumé, pas une fonctionnalité manquante.

## 5. Honnêteté et limites

- Le feedback décrit la réponse **face à l'exercice** ; il ne prédit ni une embauche ni
  un score de recruteur. Le `disclaimer` est renvoyé par l'API et affiché dans l'UI.
- Les questions d'écart se fondent sur « aucune preuve comparable trouvée dans le
  profil » — pas sur « tu ne sais pas faire ». La formulation est explicite.
- Les mots-clés de culture et les fragments de process d'entretien ne sont retenus que
  s'ils figurent **littéralement** dans le texte de l'offre ; sinon la fiche indique
  « non renseigné ».
- La détection d'affirmations non prouvées est lexicale : elle signale un risque, elle ne
  prouve pas un mensonge. Une affirmation peut être signalée à tort si la preuve est
  hors profil.
- La sélection des banques finance est lexicale : une offre dont le texte ne contient
  aucun mot-clé de banque activera les trois premières banques par ordre de déclaration.
- `SK-03` (`career/requirements_fit.py`) et `SK-10` (`career/candidate_profile.py`) ne
  sont pas dans cette base : les ids de preuves sont des identifiants locaux
  déterministes (`ev_<champ>_<sha10>`), pas des ids SK-10.

## 6. Suites possibles

- Basculer le producteur d'écarts sur `career/requirements_fit.py` dès son intégration
  (le point d'entrée est isolé dans `_gap_questions`).
- Ajouter une catégorie « cas » et une grille d'évaluation par poste, à partir des
  `role_level` déjà stockés sur les offres.
- Exporter la préparation en `.docx` : `career/document_export.py` sait déjà le faire,
  il suffirait d'ajouter le format au payload d'export.
