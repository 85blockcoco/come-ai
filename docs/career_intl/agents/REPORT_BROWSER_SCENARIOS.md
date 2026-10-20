# Spécification E2E — Scénarios du parcours utilisateur Career (navigateur)

- **Mission** : spécifier les scénarios E2E du parcours utilisateur Career, de l'ouverture à l'absence d'envoi.
- **Statut** : **SPÉCIFICATION LIVRÉE** — aucun code applicatif modifié, aucun appel cloud, aucune donnée personnelle.
- **Date** : 18 octobre 2026.
- **Base observée** : branche `audit/total-v3-2026-10-14`, HEAD `fb46fcf` (non modifiée).
- **Livrable unique** : `docs/career_intl/agents/REPORT_BROWSER_SCENARIOS.md`.
- **Périmètre couvert** : `/career` (espace Career 4.1) servie par `career/router.py` et `career_static/`.

## 0. Conventions de preuve

Comme dans `docs/career_intl/agents/REPORT_CONNECTOR_AUDIT.md`, chaque affirmation porte une marque :

| Marque | Signification |
|---|---|
| **MESURÉ** | fait rejoué dans cette session sur l'application réelle, avec fixtures 100 % synthétiques, clés cloud retirées et sockets sortants bloqués. Précision importante : les mesures ont été faites **au niveau de l'API HTTP**, pas dans un navigateur — aucun navigateur n'était pilotable ici. |
| **LU** | fait lu dans le code source, avec fichier et ligne |
| **JUGÉ** | analyse de l'auditeur, non prouvée par exécution |
| **À RECETTE** | comportement d'interface (rendu, focus, persistance de tri, message affiché) déduit du code mais **non exécuté** : c'est précisément ce que la présente recette doit vérifier dans le navigateur |
| **ÉCART** | le comportement attendu n'existe pas à HEAD ; le scénario documente l'écart au lieu de le simuler |

Aucun chiffre de ce document ne provient d'une source publique réelle. Les couvertures de sources, la fraîcheur et la disponibilité d'un board réel ne sont **pas** mesurées par cette recette.

---

## 1. Environnement de recette (à exécuter avant toute capture)

### 1.1 Interdits

- Ne **jamais** ouvrir `/career` sur l'instance personnelle : elle contient un profil et un suivi réels.
- Ne **jamais** exécuter `scripts/live_source_check.py` ni un bouton qui interroge un board réel pendant cette recette.
- Ne **jamais** cliquer sur « Résumé IA (consentement cloud) », ne pas cocher la case de consentement du dossier, ne pas soumettre le mini-entretien à un fournisseur.
- Ne coller aucun document, CV, export LinkedIn ou texte personnel.

### 1.2 Harnais synthétique disponible

`scripts/criteria_browser_demo.py` (LU : `scripts/criteria_browser_demo.py:22-83`) construit une instance jetable :

- stockage temporaire `tempfile.mkdtemp(prefix="come-criteria-synthetic-")` ;
- `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY` retirées de l'environnement (`scripts/criteria_browser_demo.py:25-26`) ;
- transport Greenhouse remplacé par un flux en mémoire ;
- `socket.socket.connect`, `socket.socket.connect_ex` et `socket.getaddrinfo` réécrits pour rejeter toute destination non locale (`scripts/criteria_browser_demo.py:59-74`) ;
- une source unique `synthetic-fixture`, société `Banque fictive`, URLs en `.test`.

Commande de recette :

```text
env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY HOME=/tmp/codex_home \
  PYTHONDONTWRITEBYTECODE=1 \
  /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m scripts.criteria_browser_demo --port 8916
```

Puis `http://127.0.0.1:8916/career#career/stagehunter`.

**MESURÉ** : la bannière `SYNTHETIC DEMO ONLY — temporary storage: …` s'affiche au démarrage, `GET /career` répond `200` et `GET /api/career/health` répond `200` avec `"automated_submission": false`.

### 1.3 Défaut connu du harnais actuel — à corriger dans la fixture, pas dans l'application

**MESURÉ** : avec le harnais tel quel, l'exploration affiche **zéro** offre, y compris après sélection du domaine « Corporate Finance » :

```text
extrait de "summary" :
{"raw_count": 7, "confirmed_count": 6, "uncertain_count": 0, "excluded_count": 1,
 "relevant_count": 0, "filtered_criteria_count": 6, "displayed_count": 0}
```

Cause : `criteria_admit` (`career/exploration.py:131-168`, LU) exige que la composante `domaine` soit à l'état `match`, donc qu'un terme du domaine choisi apparaisse littéralement dans `title + description_original + requirements`. Les titres du harnais sont `Synthetic Finance …` et sa description dit `Synthetic finance role.`, sans terme de domaine reconnu.

Conséquence pratique : **le fixture de recette doit contenir le terme de domaine dans le texte de l'offre**. Le fixture de référence ci-dessous le fait et produit 6 offres conformes (MESURÉ). Ne pas modifier `career/exploration.py` pour contourner ce comportement : il est correct et testé.

### 1.4 Fixture de référence (données fictives, à utiliser pour les 11 scénarios)

Registre : une source unique, `board_token=synthetic-fixture`, société `Banque fictive`, `verified_at=2026-10-18T00:00:00Z`, URLs `https://careers.example.test/synthetic-<n>`, ville `Paris, France`.

Préfixe commun de chaque description (nécessaire au domaine) :

```text
Corporate finance offer. <CORPS> Requirements: Excel modelling and valuation required.
English C1 required. Bachelor degree or Master 1 degree accepted.
```

| n | Titre | `Employment Type` | CORPS | Attendu (MESURÉ) |
|---|---|---|---|---|
| 1 | Corporate Finance Internship January | Internship | `This internship starts in January 2027. This internship lasts six months.` | `conforming`, mois 1 |
| 2 | Corporate Finance Internship February | Internship | `This internship starts in February 2027. This internship lasts six months.` | `conforming`, mois 2 |
| 3 | Corporate Finance Internship March | Internship | `This internship starts in March 2027. This internship lasts six months.` | `conforming`, mois 3 |
| 4 | Corporate Finance Internship April | Internship | `This internship starts in April 2027. This internship lasts six months.` | `non_conforming` (mois 4 non sélectionné) |
| 5 | Corporate Finance Internship February short | Internship | `This internship starts in February 2027. This internship lasts three months.` | `non_conforming` (durée < 6) |
| 6 | Corporate Finance Internship February no duration | Internship | `This internship starts in February 2027.` | `to_verify` (durée inconnue) |
| 7 | Corporate Finance CDD February | CDD | `The fixed-term contract starts in February 2027.` | `conforming`, `fixed_term` |
| 8 | Corporate Finance CDI March | CDI | `The permanent contract starts in March 2027.` | `conforming`, `permanent` |
| 9 | Corporate Finance VIE January | VIE | `The international mission starts in January 2027.` | `conforming`, `VIE` |
| 10 | Corporate Finance Alternance February | Alternance | `The apprenticeship starts in February 2027.` | `non_conforming` (contrat non sélectionné) |
| 11 | Corporate Finance Internship January with CDI | CDI | `This internship starts in January 2027. This internship lasts six months.` | `ambiguous` → `to_verify` |
| 12 | Corporate Finance Internship London January | Internship | idem n°1, ville `London, United Kingdom` | filtrée par localisation |

Profil fictif (uniquement des faits inventés, aucun contact réel) :

```json
{"display_name":"Candidat fictif","education":"Master 1 finance",
 "experience":"Stage d'analyse en cabinet (données fictives).",
 "skills":"Excel modelling, valuation",
 "languages":"Français natif, anglais C1",
 "eligibility":"compatible"}
```

Critères de départ de la recette :

```json
{"domains":["Corporate Finance"],"cities":["Paris"],
 "contract_types":["stage","cdd","cdi","vie"],"start_months":[1,2,3],
 "minimum_stage_duration_months":6,"education_preference":"bachelor_m1_then_m2"}
```

### 1.5 Grille de capture commune

Pour chaque scénario, déposer dans `docs/career_intl/agents/evidence/` :

| Fichier | Contenu |
|---|---|
| `S<n>_<nom>.png` | capture d'écran pleine page, données fictives visibles |
| `S<n>_<nom>.network.har` | export réseau DevTools (Requests only) |
| `S<n>_<nom>.json` | corps de réponse de l'API citée (collé depuis l'onglet Response) |
| `S<n>_<nom>.console.txt` | sortie console navigateur (doit être vide d'erreur) |
| `S<n>_<nom>.steps.md` | horodatage UTC de chaque action et résultat observé |

Règles de nommage : `S01_ouverture`, `S02_aujourdhui`, `S03_filtres_contrats`, `S04_filtres_mois`, `S05_exclusion_alternance`, `S06_profil_fictif`, `S07_matching`, `S08_dossier`, `S09_suivi`, `S10_relance_suggeree`, `S11_absence_envoi`.

Rappel de preuve déjà mesuré dans ce document : le tableau de bord et le suivi affichent des compteurs ; les captures doivent donc montrer **les compteurs** et **les libellés de statut**, pas seulement l'apparence.

### 1.6 Exécution navigateur déjà réalisée (base de ce document)

Une partie des comportements marqués « à recette » a été **effectivement exécutée** pendant la rédaction, dans Chrome 155 headless piloté par CDP, sur le harnais du §1.2 élargi au fixture §1.4 (source unique `Banque fictive`, 12 offres, sockets sortants bloqués côté serveur).

Faits établis par cette exécution :

- Chargement : 14 requêtes, **0 POST**, **0 requête hors `127.0.0.1`** ; badge « Côme AI Career 4.1 · OCR macOS prêt · boards officiels sur demande · aucune candidature envoyée » ; focus sur `<body>` au chargement, sur le `<h2>` après clic d'onglet.
- Tableau de bord vide : 8 métriques à 0, plan d'action = `Complète ton profil Career`, `Termine les questions de recherche`, `Ajoute une source publique`, `Ajoute une offre à suivre`.
- Après exploration : `confirmed_count=7`, `uncertain_count=2`, `excluded_count=3`, `filtered_criteria_count=1`, `displayed_count=8` ; en-tête de couverture « Offres conformes aux critères : 7 · offres à vérifier : 2 · offres exclues : 3… Limite : 24 sources et 150 résultats classés » ; alternance absente de la liste.
- Première carte : « Pertinence selon tes critères : 100/100 », « Correspondance forte », « Conforme à tes critères contractuels et de période », composantes domaine et localisation.
- Dossier local : `generation_mode=local`, `provider=Local · gabarit factuel`, refus `400` du mode IA sans consentement.
- Absence d'envoi : `400` (sans approbation), `422` (référence trop courte), `400` (retour arrière) ; `automated_submission=false` ; seul hôte contacté sur toute la session : `127.0.0.1:8917`.

Restent à exécuter par le recetteur : la saisie réelle dans les formulaires (cases, tri, approbation), les captures d'écran, l'export HAR, et tout ce que le harnais ne bloque pas encore. Les points corrigés à la suite de cette exécution sont signalés dans les scénarios concernés.

---

## 2. Scénario 1 — Ouverture de l'espace Career

### Préconditions

- Harnais synthétique démarré (§1.2), base vide (première utilisation).
- Navigateur à ≥ 1280 px de large, thème clair, DevTools ouvert onglet Network avec filtre `Fetch/XHR`.
- Aucune clé cloud dans l'environnement du serveur.

### Actions

1. Ouvrir `http://127.0.0.1:8916/career`.
2. Ne rien cliquer ; laisser le chargement se terminer (< 3 s attendu).
3. Attendre la disparition de `#career-loading`.
4. Relever la liste complète des requêtes réseau de la page.
5. Recharger une seconde fois (F5) et comparer la liste.

### Résultat attendu

- **MESURÉ** : `GET /career` → `200`, page `career_static/index.html`.
- **MESURÉ** : zéro appel de transport de source. Le compteur d'appels du connecteur synthétique reste `0` après `GET /career` puis `GET /api/career/stage-search/explore` (voir `tests/test_career_explorer_web.py:43-44`, LU, et reproduction directe).
- **MESURÉ** : `GET /api/career/stage-search/explore` répond `200` sans aucune I/O réseau ; `get_exploration` est explicitement en lecture seule (`career/service.py:2032-2033`, LU).
- **LU** : `bootstrap()` déclenche exactement `loadHealth`, `loadProfile`, `loadProfileImports`, `loadIntake`, `loadPreferences`, `loadDiscoverySources`, `loadDashboard`, `loadJobs`, `loadShortlist`, `loadApplications` (`career_static/career.js:2361-2374`). Aucune de ces fonctions n'appelle `POST /api/career/stage-search/explore`.
- Onglets visibles : Tableau de bord, Découvrir, Stage Hunter, Candidatures, Coach d'entretien, Mon profil, Réglages (`career_static/index.html:39-45`, LU).
- `#career-health` affiche la forme `Côme AI Career 4.1 · … · aucune candidature envoyée` (`career_static/career.js:328-339`, LU).
- **MESURÉ (navigateur)** : au chargement, le focus reste sur `<body>` — aucun déplacement de focus. Le focus ne va sur le `<h2>` **qu'après un clic d'onglet** (mesuré : `BODY` → clic « Stage Hunter » → `H2` « Stage Hunter »). `showView` est appelé au bootstrap avec `focus: false` (`career_static/career.js:2366-2367`, `:254-280`).

### Données utilisées

- Base vide ; aucun fixture n'est nécessaire à ce scénario.
- Uniquement l'index statique et les 10 endpoints de bootstrap.

### Preuves à capturer

1. Capture `S01_ouverture.png` : en-tête, badge « Données locales », les 7 onglets, état vide du tableau de bord.
2. `S01_ouverture.network.har` : liste des requêtes — attendu : uniquement `GET /career`, `/career-static/career.css`, `/career-static/career.js` et des `GET /api/career/*`. **Aucun** `POST`, **aucun** hôte hors `127.0.0.1`.
3. `S01_ouverture.json` : corps de `GET /api/career/health` — `"automated_submission": false`, `"mode": "local par défaut"`.
4. Chronomètre : durée entre `document` load et disparition de `#career-loading`.
5. `S01_ouverture.console.txt` : vide.

---

## 3. Scénario 2 — Écran « Aujourd'hui »

### Préconditions

- Scénario 1 terminé, base toujours vide.
- Pour la seconde moitié : §1.4 appliquée (critères enregistrés + exploration une fois).

### Actions

1. Observer la vue **Tableau de bord** par défaut.
2. Relever les 8 métriques de `#dashboard-metrics`.
3. Relever l'ordre des items de `#dashboard-action-plan` et le texte de chacun.
4. Cliquer le bouton « Ouvrir » du premier item du plan et vérifier la vue atteinte.
5. Recharger la page, puis revenir au tableau de bord.

### Résultat attendu

- **ÉCART — le libellé « Aujourd'hui » n'existe pas à HEAD.** Aucun onglet, route (`/api/career/home`, `/api/career/daily`) ni module `come_today` n'est présent à HEAD : `git grep -l come_today HEAD` ne renvoie rien hors dossier non suivi, et `career/router.py` expose 57 routes sans aucune route d'accueil (`career/router.py:204-574`, LU). Le module `come_today/` existe uniquement sur la branche non intégrée `feature/come-today-connecteurs` (vérifié par `git ls-tree`).
- Écran effectivement tenu lieu d'accueil : **Tableau de bord**, titre « Ce qui mérite ton attention » (`career_static/index.html:51-90`, LU). **Ce scénario vaut recette du tableau de bord ; il devra être re-ciblé si l'accueil « Aujourd'hui » est intégré.**
- **MESURÉ** sur base vide : métriques à `0` (`jobs_total`, `jobs_open`, `shortlisted`, `to_review`, `applications_total`, `drafts_total`, `interviews_active`, `receipt_unknown`) et plan d'action =
  `['profile-completeness', 'intake-completion', 'discover-source', 'discover-jobs']` dans cet ordre.
- **MESURÉ** avec le fixture §1.4 exploré (profil **pas encore** renseigné, puisque le scénario 6 vient après) : `jobs_total=6`, `jobs_open=6`, `to_review=6`, plan = `['offers-verification', 'profile-completeness', 'intake-completion', 'discover-source']`.
- **LU** : le plan est trié par `priority` puis `id`, plafonné à 12 items (`career/service.py:147`, `:3288-3483`), et ne déclenche aucune action externe (`career/service.py:3280-3287`). L'état vide est explicite : « Ton suivi est à jour pour le moment… » (`career_static/career.js:746-751`).
- **À RECETTE** : un clic sur « Ouvrir » ne fait qu'un `showView` + `setMessage`, plus le rechargement de la vue ciblée ; aucune écriture, aucun appel externe (`career_static/career.js:771-780`).

### Données utilisées

- Base vide pour l'état initial ; fixture §1.4 + critères §1.4 pour l'état « après exploration ».
- Aucune donnée réelle ; aucune date limite réelle (le flux Greenhouse synthétique ne fournit pas de `deadline_date`, LU : `career/discovery.py:426-430`).

### Preuves à capturer

1. `S02_aujourdhui.png` : vue complète, métriques, plan d'action ordonné.
2. `S02_aujourdhui.json` : `GET /api/career/dashboard` — les compteurs et `action_plan[].id/target_view`.
3. Note explicite dans `steps.md` : **absence de l'écran « Aujourd'hui » à HEAD**, avec la sortie de `git grep -l come_today HEAD` vide et la liste des 7 onglets de `career_static/index.html:39-45`.
4. `S02_aujourdhui.network.har` pour le clic « Ouvrir » : uniquement le `GET` de la vue ciblée.

---

## 4. Scénario 3 — Filtres Stage, CDD, CDI, VIE

### Préconditions

- Fixture §1.4 monté, onglet **Stage Hunter** ouvert (`#career/stagehunter`).
- Étape A visible : `#stagehunter-brief-form`, avec `#stagehunter-contract-types` rendu depuis le vocabulaire serveur.

### Actions

1. Vérifier l'état initial des 4 cases : `#stagehunter-contract-types input[value=stage|cdd|cdi|vie]`.
2. Vérifier `#stagehunter-min-stage-duration` = 6.
3. Sans rien changer, cliquer « Explorer les stages » (`#stagehunter-explore`).
4. Relever `summary` et la liste de `#stagehunter-matches`.
5. Décocher `cdi`, cliquer « Enregistrer mes critères », puis « Explorer les stages ».
6. Répéter pour `vie` seule, puis pour `stage` seule.
7. Cocher de nouveau les quatre et enregistrer.

### Résultat attendu

- **MESURÉ** : les 4 cases sont cochées par défaut et `minimum_stage_duration_months = 6` (défauts `career/stage_search.py:156-181`, `career/router.py:96-98`, LU ; observé).
- **MESURÉ** (matrice complète, mêmes 12 offres, domaine + ville Paris) :

| Sélection | `confirmed` | `to_verify` | `non_conforming` | `filtered_criteria` | affichées |
|---|---:|---:|---:|---:|---|
| stage + cdd + cdi + vie (défaut) | 7 | 2 | 3 | 1 | 8 |
| stage | 4 | 2 | 6 | 1 | 5 |
| cdd + vie | 2 | 1 | 9 | 0 | 3 |
| cdi | 1 | 1 | 10 | 0 | 2 |

- **MESURÉ** avec le sous-ensemble de 6 offres conformes (n° 1, 2, 3, 7, 8, 9) : les 6 restent affichées, `raw_count=8`, `confirmed_count=6`, `excluded_count=2` (n° 4 avril et n° 10 alternance).
- **MESURÉ** : décocher `cdi` retire l'offre CDI de la liste **et l'offre n'est pas conservée en base** : elle est filtrée avant l'import (`career/discovery.py:455-456`, `continue` sur `target_status == "non_conforming"`). Vérifié : après une exploration sans `cdi`, `GET /api/career/jobs` renvoie 2 offres sur 3 et « Mes offres enregistrées » ne la montre pas. Re-cocher `cdi` puis réexplorer la réimporte (`imported_count=1`). Ce point est contre-intuitif et doit être vérifié explicitement : décocher un contrat ne « désactive » pas une offre déjà connue, il empêche son entrée dans le parcours.
- **LU** : un contrat non sélectionné produit `non_conforming` avec la raison « Le type de contrat X n'est pas sélectionné dans tes critères » (`career/offer_qualification.py:333-335`). CDD, CDI et VIE n'héritent pas du seuil de 6 mois : ce seuil n'est appliqué qu'au bloc `contract_type == "internship"` (`career/offer_qualification.py:325-328` et `:349-354`).
- **MESURÉ (API)** : deux `POST /explore` successifs → le second lit le cache mémoire (10 min) : `sources_cached=1` et compteur d'appels transport inchangé. **À RECETTE** : vérifier que le clic dans l'interface produit le même `summary`.
- Message global attendu après exploration : `Exploration terminée sur les sources du registre. Aucun dépôt de candidature n'a été effectué.` (`career_static/career.js:2321`, LU).

### Données utilisées

- Fixture §1.4 ; sous-ensemble ciblé n° 1, 2, 3, 7, 8, 9 pour le cas nominal.
- Offres n° 7 (CDD février), 8 (CDI mars), 9 (VIE janvier) comme témoins de chaque contrat.
- Aucune source réelle ; `board_token` synthétique uniquement.

### Preuves à capturer

1. `S03_filtres_contrats.png` : bloc « Types de contrat » avec les 4 cases dans les deux états (avant / après décoche).
2. `S03_filtres_contrats.json` : `GET /api/career/stage-search` → `brief.contract_types`, `brief.minimum_stage_duration_months` ; puis `POST /api/career/stage-search/explore` → `summary` des 4 variantes.
3. `S03_filtres_contrats.network.har` : preuve `sources_cached` au second appel (aucune nouvelle requête sortante).
4. `steps.md` : nombre d'offres affichées par variante, avec les titres exacts.

---

## 5. Scénario 4 — Mois janvier, février, mars

### Préconditions

- Scénario 3 terminé avec les 4 contrats re-cochés et enregistrés.
- Bloc « Mois de début possibles » visible : `#stagehunter-start-months` (12 cases) + `#stagehunter-quarter-one`.

### Actions

1. Vérifier l'état initial : janvier, février, mars cochés ; `#stagehunter-quarter-one` coché ; avril à décembre décochés.
2. Enregistrer puis « Explorer les stages » — relevé de référence.
3. Décocher janvier et mars (laisser février), enregistrer, explorer.
4. Ne cocher que mars, enregistrer, explorer.
5. Cocher avril seul, enregistrer, explorer.
6. Revenir à janvier+février+mars, enregistrer, **recharger la page sans explorer** et observer `#stagehunter-explore-status`.

### Résultat attendu

- **MESURÉ** (12 offres, domaine Corporate Finance, ville Paris) :

| Mois cochés | `confirmed` | `to_verify` | `non_conforming` | affichées | Titres affichés |
|---|---:|---:|---:|---:|---|
| 1,2,3 (défaut) | 7 | 2 | 3 | 8 | Internship January, Internship February, Internship March, CDD February, CDI March, VIE January, Internship January with CDI (à vérifier), Internship February no duration (à vérifier) |
| 1 (janvier) | 3 | 1 | 8 | 3 | Internship January, VIE January, Internship January with CDI |
| 2 (février) | 2 | 2 | 8 | 4 | Internship February, CDD February, Internship January with CDI, Internship February no duration |
| 3 (mars) | 2 | 1 | 9 | 3 | Internship March, CDI March, Internship January with CDI |
| 4 (avril) | 1 | 1 | 10 | 2 | Internship April, Internship January with CDI |

- **À RECETTE** : la case « Premier trimestre (janvier à mars) » suit l'état des 3 cases et les co/décoche en bloc ; cocher 1+2+3 doit la cocher, décocher mars doit la décocher (`career_static/career.js:1830-1841`).
- **MESURÉ** : après avoir changé les critères **sans** réexplorer, `GET /api/career/stage-search/explore` renvoie `criteria_changed=true`, `requires_refresh=true`, `displayed_count=0`, et le bandeau se termine par « Tes critères ont changé : relance l'exploration pour couvrir les sources avec ces critères. » (`career/service.py:2079-2094`, LU ; reproduit).
- **MESURÉ (redémarrage)** : critères et profil sont persistés en base et relus par une **instance neuve** du service (équivalent d'un redémarrage du serveur) : `start_months`, `contract_types`, `configured = true`, `display_name` et `skills` identiques. **À RECETTE** : la même vérification via un simple rechargement de page.
- **LU** : un mois non sélectionné donne `non_conforming` avec « Le mois de début (N) n'est pas sélectionné dans tes critères » (`career/offer_qualification.py:344-346`). Une offre sans mois connu reste `to_verify`, jamais conforme (`career/offer_qualification.py:339-340`).

### Données utilisées

- Offres n° 1 (janvier), 2 (février), 3 (mars), 4 (avril) — une par mois, durée 6 mois, contrat `Internship`.
- Témoins contractuels n° 7 (CDD février), 8 (CDI mars), 9 (VIE janvier) pour vérifier que le filtre de mois s'applique aussi aux contrats non-stage.
- Contre-exemples n° 5 (3 mois), 6 (sans durée), 11 (contradiction) pour vérifier qu'aucun ne devient « conforme » par simple coïncidence de mois.

### Preuves à capturer

1. `S04_filtres_mois.png` : les 12 cases + la case « Premier trimestre », état coché/décoché.
2. `S04_filtres_mois.json` : `summary` des 5 variantes + le bloc `criteria_changed/requires_refresh` de l'étape 6.
3. `S04_filtres_mois.network.har` : à l'étape 6, **aucun** `POST /explore` n'est déclenché par la simple sauvegarde.
4. `steps.md` : pour chaque mois, la liste exacte des titres affichés (colonne du tableau ci-dessus).

---

## 6. Scénario 5 — Exclusion de l'alternance

### Préconditions

- Fixture §1.4 ; 4 contrats cochés ; janvier+février+mars cochés.
- L'offre n° 10 (`Alternance`, février) est présente dans le flux.

### Actions

1. Explorer avec la sélection par défaut.
2. Vérifier que l'offre n° 10 est absente de `#stagehunter-matches`.
3. Ouvrir `#stagehunter-explore-report` et lire `#stagehunter-explore-coverage` (compteurs « offres exclues »).
4. Basculer sur « Mes offres enregistrées » via `#stagehunter-my-companies`, puis `#stagehunter-search` pour relancer le classement sur les offres stockées.
5. Vérifier le statut de l'offre n° 10 dans cette vue.
6. Rouvrir `#stagehunter-explore-report`.

### Résultat attendu

- **MESURÉ** : l'alternance n'apparaît **jamais** dans la liste, quel que soit le jeu de mois (l'offre n° 10 n'est présente dans aucun des 5 variantes du scénario 4).
- **MESURÉ** : `qualify_offer` classe l'offre `apprenticeship` en `non_conforming` avec la raison exacte « Le type de contrat apprenticeship n'est pas sélectionné dans tes critères. » (reproduction directe sur le parseur).
- **LU** : le motif de détection est `\b(?:alternance|apprenticeship|apprentice|apprenti(?:e)?)\b` appliqué au `employment_type` puis au titre, avant la description (`career/offer_qualification.py:54`). L'aliasing `stage → internship` est explicite (`career/offer_qualification.py:142`) : `apprenticeship` n'a pas d'alias, donc il ne peut pas être traité comme `stage`.
- **MESURÉ** : `excluded_count` augmente de 1 par rapport à un flux sans alternance ; l'offre reste importable en base mais n'est pas retenue par l'exploration (`career/service.py:2198-2200`).
- **MESURÉ** : dans la vue « Mes offres enregistrées », l'offre n° 10 n'apparaît pas non plus (elle n'a jamais été retenue), et le bandeau `#stagehunter-result-mode` indique « Mes offres enregistrées — tous les types de contrats, avec classement et avertissements. Aucune offre suivie n'a été supprimée. » (`career_static/career.js:2249`, LU).
- **JUGÉ** : l'utilisateur ne peut pas demander explicitement l'alternance depuis l'UI. Le comportement correct et attendu est une exclusion **silencieuse mais justifiée** (compteur « offres exclues »), pas une erreur. Vérifier que le libellé n'accuse pas l'utilisateur d'un échec.

### Données utilisées

- Offre n° 10 : `employment_type = Alternance`, corps `The apprenticeship starts in February 2027.`, titre `Corporate Finance Alternance February`.
- Offres de contrôle n° 4 (avril) et n° 5 (durée 3 mois) pour distinguer les trois motifs d'exclusion dans le compteur.

### Preuves à capturer

1. `S05_exclusion_alternance.png` : la liste sans l'offre n° 10, et le compteur « offres exclues » du rapport d'exploration.
2. `S05_exclusion_alternance.json` : `summary.excluded_count` avant/après ajout de l'alternance au fixture, et pour l'offre n° 10 `qualification.contract_type = "apprenticeship"`, `target_status = "non_conforming"`, `reasons[0]`.
3. `steps.md` : motif exact d'exclusion lu dans la réponse, cité verbatim.

---

## 7. Scénario 6 — Profil fictif

### Préconditions

- Onglet **Mon profil** (`#career/profile`), formulaire `#profile-form` visible.
- Aucune donnée réelle collée.

### Actions

1. Ouvrir `#career/profile`.
2. Remplir les 6 champs factuels du profil fictif (§1.4) et laisser `contact_email`, `contact_phone`, `linkedin_url` **vides** (démonstration volontaire : les coordonnées ne sont pas nécessaires).
3. Cliquer « Enregistrer le profil ».
4. Attendre le message `Profil enregistré localement.`
5. Recharger la page et vérifier que les champs sont toujours remplis.
6. Revenir au Tableau de bord et observer la métrique et le plan d'action.
7. Ouvrir la fiche de préparation de l'offre n° 1 (étape D) et vérifier qu'aucune coordonnée n'y apparaît.

### Résultat attendu

- **MESURÉ** : `PUT /api/career/profile` accepte le payload fictif ; `GET /api/career/profile` renvoie exactement les mêmes valeurs ; le rechargement les restitue dans les champs.
- **MESURÉ** : l'item `profile-completeness` disparaît du plan d'action une fois `display_name`, `education`, `experience`, `skills`, `languages` renseignés (`PROFILE_ACTION_FIELDS`, `career/service.py:148-154`, LU ; observé : le plan passe de `['profile-completeness','intake-completion','discover-source','discover-jobs']` à `['intake-completion','discover-source','discover-jobs']`).
- **MESURÉ** : le mini-entretien reste une action distincte ; répondre aux 6 questions fait disparaître `intake-completion` (`career/intake.py:28-59`, LU ; observé).
- **LU** : aucune donnée de contact n'est utilisée dans une préparation ou un brouillon — le vérificateur « Données de contact exclues » est explicite (`career/application_prep.py` `_CHECKS`, observé dans la réponse de `/prep`).
- **JUGÉ** : ne pas renseigner d'e-mail/téléphone est un choix de recette volontaire ; il prouve que le parcours reste utilisable sans coordonnées et qu'aucun champ de contact n'est requis pour la préparation.

### Données utilisées

- Profil fictif §1.4, sans `contact_email` / `contact_phone` / `linkedin_url`.
- Offre n° 1 pour la vérification d'absence de coordonnées.

### Preuves à capturer

1. `S06_profil_fictif.png` : formulaire rempli, champs de contact vides.
2. `S06_profil_fictif.json` : `GET /api/career/profile` après rechargement ; `GET /api/career/dashboard` avant/après (disparition de `profile-completeness`).
3. `S06_profil_fictif.console.txt` : vide.
4. `steps.md` : mention explicite « aucune coordonnée réelle utilisée ».

---

## 8. Scénario 7 — Matching et classement expliqué

### Préconditions

- Scénarios 3, 4 et 6 terminés (critères + profil fictif enregistrés, exploration faite).
- Onglet **Stage Hunter**, section « Étape C — Classement expliqué de mes offres » visible.

### Actions

1. Cliquer « Recalculer le classement » (`#stagehunter-refresh`) et lire `#stagehunter-matches-note`.
2. Pour la première carte : relever le score, le libellé de statut, la ligne « Conforme / À vérifier / Non conforme ».
3. Déplier la liste des composantes (`scoring-list good-list` et `review-list`) et les avertissements (`blocked-list`).
4. Vérifier `#stagehunter-map` (regroupement par ville).
5. Changer `#stagehunter-sort` de `desc` à `asc`, observer l'ordre, recharger la page, observer l'ordre à nouveau.
6. Cliquer « Précédente » puis « Suivante » sur `#stagehunter-detail`.
7. Cliquer « Détail » sur l'offre n° 6 (à vérifier) et comparer son libellé à celui de l'offre n° 1.

### Résultat attendu

- **MESURÉ** : pour l'offre n° 1 avec `domains=[Corporate Finance]`, `cities=[Paris]` : score **100/100**, libellé `Correspondance forte`, ligne `Conforme à tes critères contractuels et de période`, composantes `domaine 30/30` (« Domaines repérés : Corporate Finance (« corporate finance »). ») et `localisation 20/20` (« Ville correspondante : Paris. »).
- **MESURÉ** : en ajoutant `study_level=Master 1` et `languages=[anglais]`, le même calcul donne **83/100** avec `niveau 0/5 unknown` (« Le niveau demandé n'est pas indiqué ») et `langues 0/5 unknown` (« La source ne précise pas les langues requises ») — le score baisse quand on ajoute un critère, il ne se plafonne pas à 100.
- **MESURÉ** : l'exigence académique est affichée séparément : `education_access.status = "preferred"`, preuve `« Bachelor degree or Master 1 degree accepted. »`, `priority_rank = 0`.
- **LU** : le libellé de présentation est recalculé selon `qualification_status` (`career/service.py:104-120`) : `non_conforming` → « Hors critères obligatoires sélectionnés » ; `to_verify` → « Pertinence élevée — informations obligatoires à vérifier » si score ≥ 70. Le libellé d'origine reste disponible en `fit_label`.
- **MESURÉ — divergence à consigner** : sur la même offre, `POST /explore` renvoie `conforming` / « Correspondance forte », tandis que `GET /api/career/stage-search/matches` renvoie `to_verify` / « Pertinence élevée — informations obligatoires à vérifier », avec la raison « La source officielle ou le lien ne sont pas vérifiés. » (`career/service.py:1818-1832` ne redonne pas `source_verified`, contrairement à `career/service.py:2062-2067` et `:2191-2196`). **Ce comportement est conservateur et correct** (une offre reclassée hors contexte d'exploration n'est pas re-déclarée vérifiée) ; le recetteur doit le constater et le consigner, pas le corriger.
- **À RECETTE** : `#stagehunter-map` affiche une ligne par lieu, sous la forme `Paris, France : 8 offres` avec le fixture §1.4 (tri par volume décroissant) — `renderStageMap`, `career_static/career.js:1931-1948`.
- **MESURÉ (navigateur)** : le tri est piloté par `localStorage["stagehunter_sort"]` et survit au rechargement. Avec `roles: ["CDD"]` ajouté aux critères (pour obtenir des scores réellement différents), l'ordre croissant place le CDD (100/100) en **dernier** et l'ordre décroissant le place en **premier** ; après rechargement, `desc` reste sélectionné et l'ordre inchangé.
  **Piège de recette** : avec les seuls critères domaine + ville, les 8 offres obtiennent **toutes** 100/100, et le tri `asc`/`desc` ne produit aucun changement visible — le test devient vide, sans que le tri soit en cause. Il faut donc introduire un critère discriminant (`roles`, `study_level`, `languages`) avant de conclure quoi que ce soit sur le tri.
- **MESURÉ (navigateur)** : la navigation précédent/suivante boucle sur la liste courante (mesuré : « Précédente » → `Corporate Finance Internship February no duration`, « Suivante » → `Corporate Finance CDD February`) et chaque clic ne déclenche qu'un appel `/prep`.

### Données utilisées

- Offres n° 1 (100/100, conforme), n° 6 (à vérifier), n° 11 (contrat contradictoire → `ambiguous`).
- Profil fictif §1.4 (le matching de critères n'utilise pas le profil ; la préparation, si).
- Pondérations de classement par défaut (aucune pondération personnalisée).

### Preuves à capturer

1. `S07_matching.png` : première carte dépliée (score, statut, composantes, preuve académique) et `#stagehunter-map`.
2. `S07_matching.json` : `stage_match` complet de l'offre n° 1 (`score`, `label`, `fit_label`, `qualification_status`, `components[]`, `education_access`), puis le même objet via `/matches` pour la divergence.
3. `S07_matching_asc.png` : ordre inversé après sélection `asc` + même ordre après F5.
4. `steps.md` : relevé de `localStorage["stagehunter_sort"]` avant/après.

---

## 9. Scénario 8 — Préparation d'un dossier

### Préconditions

- Offres n° 1 et 2 stockées ; profil fictif §1.4 enregistré.
- Sections « Étape D — Préparer une candidature » et onglet **Application Studio** accessibles.

### Actions

1. Sur l'offre n° 1, cliquer « Préparer cette candidature » (ou sélectionner dans `#stagehunter-prep-job` puis « Analyser cette offre »).
2. Relever `#stagehunter-prep` : exigences, éléments pertinents, « Non trouvé dans ton profil », améliorations CV, points de lettre, garanties d'honnêteté.
3. Déplier « Relire un extrait de la description source ».
4. Cliquer « Ouvrir l'Application Studio ».
5. Choisir l'offre n° 1, langue `Français`, mode `Gabarit local factuel`, puis « Créer le dossier de candidature ».
6. Relire `#application-draft-cv`, `#application-draft-letter`, `#application-draft-checks`, `#application-draft-meta`.
7. Télécharger le CV en `.md`, `.html`, et la lettre en `.docx`.
8. Vérifier que le sélecteur de mode IA et sa case de consentement sont bien masqués/ non cochés.

### Résultat attendu

- **MESURÉ** : `GET /api/career/jobs/<id>/prep` renvoie `requirements` (sous-chaînes exactes de la description : « Requirements: Excel modelling and valuation required. », « English C1 required. »), `matched_elements` avec `profile_field = "skills"` et la citation « Excel modelling, valuation », `unverified_elements` avec « English C1 required. », et quatre `checks` (aucun fait inventé, données de contact exclues, analyse locale déterministe, relecture requise).
- **MESURÉ** : `POST /api/career/application-drafts` en `mode=local` renvoie `generation_mode = "local"`, `provider = "Local · gabarit factuel"`, un `cv_markdown` et un `letter_markdown` non vides, tous deux préfixés par des champs `[Nom à compléter]` / `[Coordonnées à compléter]`.
- **MESURÉ** : les téléchargements répondent `200` — `md` → `text/markdown`, `html` → `text/html`, `docx` → type OOXML (`career/router.py:479-496`, LU).
- **MESURÉ** : le `cv_markdown` et la `letter_markdown` produits en mode local commencent par des champs `[Nom à compléter]` et `[Coordonnées à compléter]`, et aucune coordonnée réelle n'y figure.
- **Contrôle manuel attendu** (non automatisé) : relire `cv_markdown` et `letter_markdown` ligne à ligne et vérifier qu'aucune compétence, expérience, date ou chiffre n'apparaît sans être présent dans le profil fictif ou dans la description de l'offre. Un écart ici est un défaut de fidélité à remonter, pas un détail cosmétique.
- **MESURÉ** : en mode `ai` sans consentement, l'API refuse (`400`, « Coche la confirmation avant d'envoyer le profil et l'offre sélectionnés au fournisseur IA configuré. ») et **aucun appel cloud n'a lieu** — vérifié en bloquant `socket.connect`, `socket.connect_ex` et `getaddrinfo` sur tout le processus.
- **LU** : le brouillon IA exige `consent_external = true` et un générateur configuré (`career/router.py:450-468`) ; sans fournisseur, le repli est local.

### Données utilisées

- Offre n° 1 ; profil fictif §1.4 ; langue `fr` ; mode `local`.
- Aucun document importé ; aucun texte de profil collé.

### Preuves à capturer

1. `S08_dossier.png` : panneau de préparation complet (exigences, correspondances, garanties).
2. `S08_dossier_studio.png` : CV + lettre + `#application-draft-checks`.
3. `S08_dossier.json` : corps de `/prep` et du brouillon, avec la preuve que `generation_mode=local`.
4. `S08_dossier.network.har` : **aucune** requête vers un hôte non local sur l'ensemble du scénario ; note sur le refus `400` en mode IA.

---

## 10. Scénario 9 — Ajout au suivi

### Préconditions

- Offre n° 1 affichée dans `#stagehunter-matches` ; aucun suivi existant.
- Onglet **Candidatures** accessible.

### Actions

1. Sur la carte de l'offre n° 1, cliquer « Ajouter à la shortlist » puis « Créer un suivi ».
2. Observer le message global et l'onglet actif.
3. Lire `#applications-list` : statut, réception, actions disponibles.
4. Ouvrir `#stagehunter-applications` (étape E) et vérifier la cohérence.
5. Recharger la page ; vérifier la persistance.
6. Cliquer « Créer un suivi » une seconde fois sur la même offre.

### Résultat attendu

- **MESURÉ** : `POST /api/career/jobs/<id>/shortlist` → `200` ; `GET /api/career/jobs?shortlisted=true` renvoie 1 offre.
- **MESURÉ** : `POST /api/career/applications` crée `stage = "to_review"`, `receipt_status = "not_submitted"`, `approval_granted = false`, et bascule vers la vue Candidatures avec le message « Suivi de candidature créé. Aucun envoi n'a été effectué. » (`career_static/career.js:1000-1009`, LU).
- **MESURÉ** : la carte affiche « Réception : non déclarée. » et propose : statut, note de suivi, « Mettre à jour », case d'approbation + « Approuver pour dépôt manuel », « Réception inconnue », « Ouvrir l'offre officielle » (`career_static/career.js:1011-1087`, LU).
- **MESURÉ (navigateur)** : un second `POST /api/career/applications` sur la **même** `job_id` est idempotent — même `id`, `created = false`, une seule ligne pour cette offre (`career/service.py:3012-3016`). À noter pour le recetteur : une mesure où l'on retrouve l'offre par `title.includes(...)` peut comparer deux offres différentes et donner un faux « non idempotent » ; fixer l'identifiant.
- **MESURÉ (API)** : `applications_total` passe à 1 après création. **À RECETTE** : vérifier la persistance affichée après rechargement de la page.
- **À RECETTE** : l'offre n° 1 apparaît simultanément dans `#stagehunter-applications` (étape E) et dans `#applications-list` — une seule candidature côté serveur, deux points de vue sur les mêmes données ; le second `POST` ne doit pas créer de doublon (`created = false`, mesuré).

### Données utilisées

- Offre n° 1 ; aucune autre candidature.
- Note de suivi facultative : texte fictif court (« Suivi fictif — à relire »).

### Preuves à capturer

1. `S09_suivi.png` : carte de suivi dans l'onglet Candidatures + message global.
2. `S09_suivi.json` : `GET /api/career/applications` après création (statut, réceptions, `approval_granted: false`, `events[0].event_type = "application_created"`).
3. `S09_suivi.network.har` : exactement 3 requêtes (`shortlist`, `applications`, rechargements de vues) — aucune requête sortante.
4. `steps.md` : comparaison avant/après de `GET /api/career/dashboard`.

---

## 11. Scénario 10 — Relance suggérée

### Préconditions

- Scénario 9 terminé : l'offre n° 1 a un suivi `to_review` / `not_submitted`.
- Onglet Candidatures ouvert.

### Actions

1. Cocher l'approbation puis cliquer « Approuver pour dépôt manuel ».
2. Changer le statut en `Envoyée` (« Mettre à jour ») — cela représente le dépôt **que le recetteur ferait lui-même, manuellement, hors application**.
3. Observer la réception devenue `inconnue`.
4. Retourner au Tableau de bord et lire le plan d'action.
5. Cliquer « Réception inconnue » sur la carte de suivi, puis relire le plan d'action.

### Résultat attendu

- **MESURÉ (navigateur)** : `POST /api/career/applications/<id>/approve` avec `approved=true` → `stage = "approved_for_manual_submission"`, `approval_granted = true`.
- **MESURÉ (navigateur)** : `PATCH .../applications/<id>` avec `stage="submitted"` est refusé en `400` si l'approbation manque (« Approuve d'abord le dépôt manuel pour cette offre avant d'enregistrer son envoi. ») ; accepté après approbation, et bascule alors `receipt_status` à `unknown` (`career/service.py:3103-3124`).
- **MESURÉ (navigateur) — séquence exacte du plan d'action**, à ne pas confondre :

| Étape | Contenu du plan d'action |
|---|---|
| avant approbation | `applications-receipt`, `offers-verification`, `draft-review`, `applications-preparation`, `intake-completion`, `discover-source` |
| après approbation, réception encore `not_submitted` | **+ `applications-manual-submission`** (« Effectue les dépôts manuels approuvés… Aucun envoi automatique n'est effectué. ») |
| après passage à `Envoyée` | `applications-manual-submission` **disparaît**, `applications-receipt` reste |
| après clic « Réception inconnue » | plan **inchangé**, `receipt_unknown = 1` |

  Cause : enregistrer `Envoyée` positionne immédiatement `receipt_status = "unknown"` (`career/service.py:3117-3119`) ; l'action « dépôt manuel » n'a de sens que tant que la réception vaut `not_submitted` (`career/service.py:3431-3439`), et l'action « réceptions inconnues » apparaît dès qu'une réception est inconnue (`career/service.py:3418-3429`). **La bascule décisive se produit donc au passage à « Envoyée », pas au clic « Réception inconnue ».**
- **ÉCART — il n'existe pas de module de relance.** À HEAD, aucune route, aucun composant et aucun libellé ne parle de « relance » de candidature : `git grep -n relance HEAD -- career career_static` ne renvoie que des messages d'OCR et le message « relance l'exploration ». **Ce qui est appelé « relance suggérée » à HEAD, c'est donc l'action de plan `applications-receipt` + l'état `receipt_unknown`**, jamais un envoi. Le message utilisateur est explicite : « Réception marquée inconnue. Career Agent ne renverra aucune candidature automatiquement. » (`career_static/career.js:1504-1509`, LU).
- **JUGÉ** : si le besoin métier est une vraie proposition de relance (message rédigé, date, canal), il n'existe pas à HEAD. La spécification ci-dessus décrit donc l'état réel et documente l'écart, plutôt que de simuler une fonctionnalité.

### Données utilisées

- Suivi de l'offre n° 1 ; approbation locale ; note fictive « pas de confirmation reçue (recette synthétique) ».
- Aucune vraie candidature, aucun e-mail, aucune notification système.

### Preuves à capturer

1. `S10_relance_suggeree.png` : carte avec « Réception : inconnue — ne pas renvoyer automatiquement » et le tableau de bord avec l'action prioritaire.
2. `S10_relance_suggeree.json` : `GET /api/career/dashboard` (plan avant/après) et `GET /api/career/applications/<id>` (`stage`, `receipt_status`, `events[]`).
3. `steps.md` : sortie de `git grep -n relance HEAD -- career career_static` + note « aucune fonctionnalité de relance n'existe à HEAD ».

---

## 12. Scénario 11 — Absence d'envoi

### Préconditions

- Tous les scénarios précédents exécutés dans l'ordre, sur le harnais synthétique.
- Sockets sortants bloqués au niveau processus (harnais §1.2).

### Actions

1. Sur la carte de suivi de l'offre n° 1, tenter « Mettre à jour » avec le statut `Envoyée` **sans** avoir coché l'approbation (re-partir d'un suivi neuf pour un test propre).
2. Tenter `POST /api/career/applications/<id>/confirm-receipt` avec une référence de 1 caractère.
3. Tenter un retour arrière : après réception confirmée, repasser le statut à `submitted`.
4. Consulter `GET /api/career/health` et lire le champ `automated_submission`.
5. Rechercher dans DevTools → Sources toute occurrence de `smtplib`, `sendmail`, `fetch(` vers un hôte non local, `XMLHttpRequest` externe.
6. Vérifier dans le code qu'aucune route d'envoi n'existe : lister les 57 routes de `career/router.py`.
7. Relire la checklist d'export du dossier (étape D) et le pied de page de la page.

### Résultat attendu

- **MESURÉ (navigateur)** : statut `submitted` sans approbation → `400` ; `confirm-receipt` avec une référence de 1 caractère → `422` ; réception confirmée puis retour à `submitted` → `400` (« Une candidature dont la réception est confirmée ne peut pas revenir à un statut antérieur. ») (`career/service.py:3087-3132`).
- **MESURÉ (navigateur)** : `GET /api/career/health` → `"automated_submission": false`, `"ai_enhancement": {"available": true, "explicit_consent_required": true}`, `profile_imports.local_only = true`, `linkedin_connection = false`.
- **MESURÉ (navigateur)** : sur toute la session de recette, le **seul** hôte contacté est `127.0.0.1:8917`. Aucun appel sortant n'a abouti : un essai de `POST …/summary` en mode IA sans consentement a été mené avec `socket.connect`, `socket.connect_ex` et `getaddrinfo` neutralisés, sans blocage, et le repli local a été rendu. **À RECETTE** : refaire ce contrôle sur une session qui passe par les boutons de l'interface.
- **MESURÉ (navigateur)** : sur le parcours complet rejoué via l'interface, aucun socket sortant n'a abouti ; le repli local du résumé IA est rendu sans appel externe.
- **LU** : aucune route d'envoi dans `career/router.py` (57 décorateurs, aucune méthode d'envoi) ; la candidature est toujours un dépôt manuel déclaré par la personne.
- **LU** : le test statique `tests/test_career_stage_hunter.py:454-460` interdit `requests`, `urllib.request`, `smtplib`, `socket`, `http.client` dans `career/stage_search.py` et `career/application_prep.py`.
- **MESURÉ** : l'audit statique du paquet `career` ne trouve de `urllib.request` que dans `career/discovery.py` et `career/connectors/public_ats.py`, tous deux limités à des ** lectures GET publiques** de flux ATS, jamais à un envoi.
- **MESURÉ (navigateur)** : le résumé IA sans consentement renvoie `mode = "local"`, `ai_error = "Consentement cloud requis ; résumé local conservé. (repli local)"` — aucun appel cloud.

### Données utilisées

- Suivis fictifs de l'offre n° 1 ; référence de réception fictive `REF-FICTIVE-001` (2 à 1 000 caractères).
- Aucune adresse réelle, aucun e-mail, aucun jeton de fournisseur.

### Preuves à capturer

1. `S11_absence_envoi.network.har` : **toutes** les requêtes de la session, hôte unique `127.0.0.1`.
2. `S11_absence_envoi.json` : corps des 4 réponses d'erreur (400 / 422 / 400) et de `/api/career/health`.
3. `S11_absence_envoi_reseau.png` : panneau Network ne montrant aucune requête hors `127.0.0.1`.
4. `steps.md` : sortie de `grep -c "@router\." career/router.py`, du test statique d'absence d'envoi, et de `grep -n "urllib.request" career/*.py career/connectors/*.py`.
5. `S11_absence_envoi.console.txt` : aucune erreur, aucun avertissement réseau.

---

## 13. Matrice de couverture

| # | Scénario | Écran / sélecteurs | API principalement exercée | Comportement vérifié | Écart à consigner |
|---|---|---|---|---|---|
| 1 | Ouverture | `/career`, onglets | `GET /career`, 10 `GET` de bootstrap | zéro lecture de source au chargement | — |
| 2 | Aujourd'hui | `#view-dashboard`, `#dashboard-action-plan` | `GET /api/career/dashboard` | compteurs, plan trié, état vide | **écart : pas d'écran « Aujourd'hui » à HEAD** |
| 3 | Filtres contrats | `#stagehunter-contract-types` | `PUT/GET /api/career/stage-search`, `POST …/explore` | 4 contrats, exclusions motivées, cache 10 min | — |
| 4 | Mois | `#stagehunter-start-months`, `#stagehunter-quarter-one` | idem | janvier/février/mars, `criteria_changed` | — |
| 5 | Alternance | rapport d'exploration | `POST …/explore` | `apprenticeship` → `non_conforming` | pas de réglage UI « alternance » (JUGÉ) |
| 6 | Profil fictif | `#profile-form` | `PUT/GET /api/career/profile` | persistance, plan d'action, pas de coordonnées | — |
| 7 | Matching | `#stagehunter-matches`, `#stagehunter-sort`, `#stagehunter-detail` | `GET …/matches`, `GET …/explore` | score explicable, tri persistant, libellés par statut | divergence `/matches` vs `/explore` sur `source_verified` |
| 8 | Dossier | `#stagehunter-prep`, `#application-draft-form` | `GET /prep`, `POST /application-drafts` | préparation factuelle, refus du mode IA | — |
| 9 | Suivi | `#applications-list` | `POST /api/career/applications` | `to_review`/`not_submitted`, idempotence | — |
| 10 | Relance | plan d'action, carte de suivi | `POST …/approve`, `POST …/receipt-unknown` | bascule `applications-receipt` | **écart : aucun module de relance** |
| 11 | Absence d'envoi | toute la session | routes d'état + `/health` | 400/422/400, `automated_submission:false`, 0 socket sortant | — |

---

## 14. Vérifications statiques à joindre au dossier

Commandes exécutables, sans réseau, à coller dans `steps.md` :

```text
# Aucune route d'envoi
grep -c "@router\." career/router.py

# Aucun client d'envoi dans les modules de logique Career
grep -n "smtplib\|requests\|http.client" career/stage_search.py career/application_prep.py career/offer_qualification.py

# Lecture réseau limitée aux connecteurs ATS publics
grep -n "urllib.request" career/*.py career/connectors/*.py

# Absence d'écran « Aujourd'hui » à HEAD
git grep -l "come_today" HEAD || echo "absent"
git grep -n "relance" HEAD -- career career_static

# Cohérence JavaScript / état DOM
node --check career_static/career.js

# Suite ciblée (offline, sockets interdits par fixture)
env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY HOME=/tmp/codex_home \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_career_action_plan.py tests/test_career_explorer_web.py \
  tests/test_career_configurable_contract_criteria.py
```

**MESURÉ** dans cette session : cette suite ciblée rend `41 passed in 15.17s`.

---

## 15. Limites de cette spécification

- Elle décrit **l'état de HEAD (`fb46fcf`)**, pas une version à venir. Les scénarios 2 et 10 documentent un écart : si l'accueil « Aujourd'hui » (`career/daily_home.py`) ou un module de relance sont intégrés, ces deux scénarios doivent être re-ciblés avant d'être exécutés.
- Les chiffres d'exclusion (`confirmed_count`, `non_conforming`, `filtered_criteria`) sont des conséquences du fixture §1.4, pas des propriétés d'une source réelle. Une source réelle peut légitimement renvoyer zéro stage conforme.
- La recette ne mesure ni la couverture, ni la fraîcheur, ni la disponibilité d'un board réel. Elle ne prouve aucun droit à une embauche.
- La divergence relevée au scénario 7 (`/matches` vs `/explore`) est un comportement conservateur observé ; elle est consignée, pas corrigée.
- Aucun fichier applicatif n'a été modifié, aucun appel cloud n'a été effectué, aucune donnée personnelle n'a été utilisée ou copiée.