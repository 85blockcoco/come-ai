# HANDOFF — CAREER STAGE HUNTER

Agent : builder Career (branche `feature/career-stage-hunter`).
Destinataire : Codex (intégration). Document autonome : il n'est pas nécessaire de relire la conversation.

---

## A. Objectif initial

Transformer le module Career existant en assistant réel de recherche de stage en finance, avec un parcours complet en 5 étapes :

- **Étape A** — critères de recherche sauvegardables et modifiables (domaines, métiers, pays/villes, date de début, durée, niveau d'études, langues, contraintes, préférences de classement) **sans aucune présomption de préférence** ;
- **Étape B** — offres réelles issues uniquement des connecteurs existants (boards Greenhouse publics configurés par la personne + imports manuels), avec conservation stricte de la source, de l'URL exacte et de la date de consultation, aucun inventeur d'offres, aucun contournement de protections de job-boards ;
- **Étape C** — classement **expliqué** (chaque point motivé), sélection manuelle, déduplication ;
- **Étape D** — préparation de candidature (exigences vs profil, éléments appariés, améliorations de CV, points de message, lien de candidature préservé) **sans invention d'expériences ni de compétences** ;
- **Étape E** — suivi : À examiner / À préparer / Prête / Envoyée / Entretien / Refusée / Offre reçue, avec dates et notes.

Contraintes honorées : fonctionnement **sans IA ni API payante**, aucun envoi automatique sans validation explicite, MVP réutilisant les vues/données/composants existants, isolation Git totale (aucune modification de `main`, aucun fichier de Codex touché).

## B. Fonctionnalités livrées (réellement testées et fonctionnelles)

1. **Critères de recherche** : validation stricte et normalisation (domaines canoniques, poids 0,5–2, dates ISO), persistance JSON dans `career_settings` (clé `stage_search_brief`), inclusion dans l'export de confidentialité, effacement par la réinitialisation. Brief vide = valide (rien n'est supposé).
2. **Vocabulaires locaux** : 8 domaines finance (M&A, Corporate Finance, Private Equity, Transaction Services, Audit financier, Asset Management, FP&A, Autres métiers financiers) avec motifs lexicaux ; termes de recherche suggérés réutilisant `SEARCH_TERMS` existant (aucun nouveau code réseau).
3. **Classement expliqué** : `score_brief_match` produit par composante un couple points/maximum, un statut (match / no_match / review / unknown) et une **raison en clair** ; avertissements pour statut source non confirmé, date limite dépassée, URL officielle absente ; règle conservatrice « l'inconnu ne rapporte aucun point » ; tri stable.
4. **Préparation de candidature déterministe** : extraction des exigences depuis le texte de l'offre + champs structurés (langues, éligibilité, niveau) ; comparaison au profil local ; chaque élément apparié **cite un extrait verbatim d'un champ du profil** (vérifié à la construction) ; les exigences non appariées sont formulées « Non trouvé dans ton profil » (jamais une affirmation sur la personne) ; suggestions de CV conditionnelles ; points de message ; URL officielle préservée ; garanties d'honnêteté listées.
5. **Nouveaux statuts de suivi** : `to_review` (À examiner — les suivis démarrent désormais ici), `submitted` (Envoyée — dépôt manuel déclaré par la personne, **requiert l'approbation locale préalable**, passe la réception en « inconnue »), `refused` (Refusée, distincte de l'existante « Rejetée par moi »), `offer_received` (Offre reçue). Garde-fous existants préservés : réception confirmée non réversible, `submitted_confirmed` inaccessible en PATCH direct, aucun envoi automatique.
6. **Interface** : onglet « Stage Hunter » regroupant les 5 étapes, réutilisant `jobCard`, la shortlist, `applicationCard`, les libellés et la logique de vues existants.
7. **Robustesse** : un brief stocké corrompu ne bloque plus l'onglet (repli + drapeau `stored_brief_invalid` visible dans l'interface).

## C. Fonctionnalités incomplètes / limites assumées

- **Périmètre de découverte** : seuls les **boards Greenhouse publics** ajoutés par la personne et les **imports manuels**. Aucun job-board généraliste (Welcome to the Jungle, LinkedIn…). Choix délibéré : légal, sans contournement de protections, réutilise le connecteur existant.
- **Le classement de l'Étape C** classe les offres **déjà importées** ; il ne prospecte pas au-delà des boards configurés (le bouton « Lancer une recherche » déclenche le discovery existant).
- **Correspondance lexicale** : une annonce au libellé atypique peut être sous-classée ; chaque score affiche ses raisons pour permettre la correction humaine.
- **La préparation ne réécrit pas le CV** : elle indique quoi documenter ; la personne reste l'auteur.
- Aucune IA générative n'est utilisée nulle part dans ce périmètre (le mode IA de l'Application Studio existant reste géré par le routeur de Codex).

## D. Architecture et interfaces

### Nouveaux modules (fichiers créés)

**`career/stage_search.py`** — logique pure et locale, zéro requête réseau.
- `STAGE_DOMAINS: dict[str, tuple[str, ...]]`, `RANKING_CRITERIA: dict[str, str]`, `RANKING_MIN_MULTIPLIER=0.5`, `RANKING_MAX_MULTIPLIER=2.0`
- `default_brief() -> dict` ; `validate_brief(payload) -> dict` (lève `UserFacingError` sur entrée invalide) ; `brief_is_configured(brief) -> bool`
- `vocabulary() -> dict` (`{"domains", "ranking_criteria": [{key,label}], "ranking_min", "ranking_max"}`)
- `search_terms_for(domains) -> list[{"domain", "terms"}]`
- `score_brief_match(brief, job) -> dict` :
  ```json
  {
    "score": 0-100 | null,
    "label": "Correspondance forte | à examiner | faible ou incomplète | Aucun critère renseigné : classement neutre",
    "components": [{"key","label","points","maximum","status","reason"}],
    "weights_applied": {"domaine": 1.5, "...": 1.0},
    "reasons": ["..."], "unknowns": ["..."], "warnings": ["..."],
    "disclaimer": "..."
  }
  ```
  Champs d'entrée du `job` utilisés : `title`, `description_original`, `requirements`, `job_family`, `city`, `country`, `start_date`, `end_date`, `duration_months`, `role_level`, `languages_required`, `deadline_status`, `source_status`, `official_url` (tous déjà présents dans `_serialize_job`).

**`career/application_prep.py`** — analyse factuelle locale.
- `extract_requirements(job) -> list[{"text","source"}]` (borné à 40 items, dédupliqué)
- `prepare_application(profile, intake, job) -> dict` avec `job` (offre sérialisée), `requirements`, `matched_elements` (`{"requirement","profile_field","evidence","matched_on"}` — `evidence` est un extrait verbatim), `unverified_elements` (`{"requirement","note"}`), `cv_improvements`, `letter_points`, `uncertainty`, `checks`, `disclaimer`.
- Champs de profil consultés : `skills`, `experience`, `education`, `languages`, `eligibility` (+ réponses d'intake `strengths`/`missions`). **Les données de contact sont structurellement exclues.**

### Service (`career/service.py`)

- Constante `STAGE_SEARCH_SETTING_KEY = "stage_search_brief"`.
- `get_stage_search() -> {"brief","configured","stored_brief_invalid","vocabulary","search_terms","disclaimer"}` — repli sur brief vide si la valeur stockée est illisible ; `stored_brief_invalid` signale le cas.
- `update_stage_search(payload: dict) -> même forme` — valide, persiste en JSON, journalise `stage_search_updated`.
- `list_stage_matches() -> {ci-dessus + "matches": [{"job": sérialisé, "stage_match": ci-dessus ou null}]}` — tri descendant stable par score ; `stage_match` vaut `null` si le brief n'est pas configuré.
- `get_job_prep(job_id: str) -> dict` — analyse de préparation pour une offre stockée.

### Routeur (`career/router.py`)

- `GET /api/career/stage-search` → forme `get_stage_search`.
- `PUT /api/career/stage-search` — payload `StageSearchPayload` (tous champs optionnels) → `update_stage_search`.
- `GET /api/career/stage-search/matches` → `list_stage_matches`.
- `GET /api/career/jobs/{job_id}/prep` → `get_job_prep` (400 avec `{"detail"}` si offre inconnue).
- `/api/career/health` gagne une clé additionnelle `"stage_search": {"enabled": true, "ai_required": false, "local_only": true, "invented_facts": false}` (additif, non cassant).
- Contrats existants inchangés : approbation (`POST .../approve {approved, note}`), réception (`POST .../confirm-receipt {confirmation_reference}`), statut (`PATCH ... {stage, note}`).

### Frontend (`career_static/`)

- Onglet `data-view="stagehunter"` + section `#view-stagehunter` (5 panneaux Étape A→E).
- `career.js` : `stageLabels`/`editableStages`/`stagesAfterConfirmedReceipt` étendus (`to_review`, `submitted`, `refused`, `offer_received`) ; libellé `ready_to_apply` : « Prête » (était « Prête à déposer ») ; vues `careerViews`/`labelForView`/chargeur `loadStageHunter` ; `refreshStageHunterIfVisible()` appelé par les actions des cartes (shortlist, création de suivi, changement de statut, approbation, réception) uniquement quand l'onglet est à l'écran.

### Dépendances

Aucune nouvelle dépendance externe. Modules existants consommés : `models` (`clean_text`, `normalized_text`, `parse_date`, `JOB_FAMILIES`), `sources.SEARCH_TERMS`, `workspace_core.UserFacingError`. `scoring.py`, `sources.py`, `discovery.py`, `application_studio.py` **non modifiés**.

## E. Fichiers modifiés

| Fichier | Rôle de la modification |
|---|---|
| `career/stage_search.py` | **Créé** — critères, validation, vocabulaires, classement expliqué |
| `career/application_prep.py` | **Créé** — préparation factuelle sans invention |
| `career/models.py` | Ajout de `to_review`, `refused`, `submitted`, `offer_received` à `APPLICATION_STAGES` et `GENERIC_APPLICATION_STAGES` (commentaire expliquant pourquoi `submitted` y figure) |
| `career/service.py` | Imports des nouveaux modules ; clé de settings ; méthodes Stage Hunter ; garde `submitted` exigeant `approval_granted` ; réception confirmée autorise `offer_received`/`refused` ; `receipt_status="unknown"` sur `submitted` ; `POST_SUBMISSION_APPLICATION_STAGES` étendu ; création de suivi par défaut `to_review` (était `to_prepare`) ; `applications_to_prepare` du tableau de bord inclut `to_review` ; capacité `stage_search` |
| `career/calendar_export.py` | `_TERMINAL_APPLICATION_STAGES` += `submitted`, `offer_received`, `refused` (un dépôt n'est plus une échéance actionnable) |
| `career/router.py` | Payload `StageSearchPayload` ; 4 endpoints ; clé `stage_search` dans `/health` |
| `career_static/index.html` | Onglet + `#view-stagehunter` (5 étapes, réutilise les classes existantes) |
| `career_static/career.js` | Libellés/statuts étendus ; registry de vues ; fonctions de rendu Stage Hunter ; rafraîchissement contextuel |
| `career_static/career.css` | Bloc « Stage Hunter » (~20 lignes), réutilisant les variables visuelles existantes |
| `tests/test_career_stage_hunter.py` | **Créé** — 29 tests hors-ligne, fixtures synthétiques explicitement labellisées |
| `HANDOFF_career_stage_hunter.md` | Ce document |

## F. Tests

Python : `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python` (venv existant, aucun créé).

### Exécutés — TOUS RÉUSSIS (dernier lancement : 113 passed, 14,24 s)

```
python -m pytest tests/test_career_stage_hunter.py \
  tests/test_career_agent.py tests/test_career_action_plan.py \
  tests/test_calendar_export.py tests/test_come_ai_v3.py \
  tests/test_hybrid_web.py tests/test_evolution_web.py \
  tests/test_v5_web.py -q
→ 113 passed
```

Détail : `test_career_stage_hunter.py` 29/29 ; régressions carrière 44/44 (32 agent + action plan + calendrier) ; intégration app/web 40/40 (`test_come_ai_v3.py`, `test_hybrid_web.py`, `test_evolution_web.py`, `test_v5_web.py`).

Vérifications syntaxe : `python -m compileall career tests/test_career_stage_hunter.py` ✓ ; `node --check career_static/career.js` ✓ ; `git diff --check` ✓ ; cohérence des IDs HTML/JS vérifiée par script ✓.

### Couverture des 10 zones exigées (`test_career_stage_hunter.py`)

1. Critères : validation stricte, zéro présomption, persistance/redémarrage — **exécuté, réussi**
2. Classement : déterministe, chaque composante expliquée, effet visible des poids, tri — **exécuté, réussi**
3. Déduplication : URL canonique (utm strippés) → une seule opportunité — **exécuté, réussi**
4. Conservation des URLs : identique du classement à la préparation — **exécuté, réussi**
5. Offres indisponibles : signalées, jamais supprimées — **exécuté, réussi**
6. Suivi persistant : parcours complet + rechargement du service ; refus distinct du rejet personnel — **exécuté, réussi**
7. Absence d'invention : preuves = extraits verbatim du profil ; exigence manquante jamais affirmée contre la personne ; profil vide → aucun appariement — **exécuté, réussi**
8. Sans fournisseur IA : endpoints fonctionnels, mode IA refusé avec message clair, brouillon local disponible — **exécuté, réussi** (TestClient = simulation HTTP en processus local, pas un vrai serveur)
9. Protection des données : e-mail/téléphone/Li jamais dans la sortie préparation ; critères exportés et effacés par la réinitialisation — **exécuté, réussi**
10. Non-envoi sans autorisation : approbation requise, envoi refusé sans approbation, réception confirmée non réversible ; modules dépourvus de toute capacité réseau/mail (test de source) — **exécuté, réussi**

Scénario fonctionnel complet : `test_full_http_journey_from_brief_to_offer_received` — parcours 100 % HTTP (critères → import offre → classement → préparation avec profil → création suivi → approbation → envoi déclaré → réception confirmée → offre reçue → persistance après redémarrage) — **exécuté, réussi**.

### Non exécutés (et pourquoi)

- `tests/test_devkit_integration.py` : suite de Codex (périmètre interdit), non affectée par Career (vérifié : aucun import carrière).
- 20 autres fichiers de tests (mémoire, moteur de format, évolution…) : **non compatibles d'intérêt** avec mes changements — vérification par grep : seuls les 9 fichiers listés plus haut importent `career` ou `come_ai_web`. Non lancés pour ne pas interférer avec le travail parallèle de Codex.
- Aucun test réseau réel (interdit par mission) : la découverte Greenhouse n'est testée ici qu'au niveau de la couche existante déjà couverte par `test_career_agent.py`.

## G. Bugs trouvés et corrigés

1. **Brief stocké verrouillant l'onglet (bloquant)** — *Symptôme* : `GET /api/career/stage-search` levait une erreur et l'onglet Stage Hunter devenait inutilisable, sans moyen de récupération via l'interface. *Cause* : `validate_brief` lève `UserFacingError` (hérite de `RuntimeError`), non rattrapé par le `except (JSONDecodeError, TypeError, ValueError)` de `get_stage_search` — survenait si la valeur stockée restait du JSON valide mais devenait invalide (domaine retiré du vocabulaire après mise à jour, édition manuelle de la base). *Correction* : `UserFacingError` ajouté au repli + drapeau `stored_brief_invalid` remonté à l'interface avec message explicite ; le prochain enregistrement corrige. *Test* : `test_corrupt_stored_brief_falls_back_without_locking_the_tab`, `test_valid_json_but_invalid_brief_also_recovers`.
2. **Doublon dans les tokens génériques** — `\"experience\"` listé deux fois dans `_GENERIC_TOKENS` ; supprimé (sans effet comportemental, frozenset).

## H. Bugs connus

Aucun bug connu dans le périmètre livré. Limites fonctionnelles documentées en section C (découverte limitée aux boards Greenhouse configurés + imports manuels ; correspondance lexicale). Point d'attention mineur non corrigé par choix : `extract_requirements` déduplique les exigences par égalité stricte (casefold) — des reformulations très proches peuvent apparaître deux fois dans le panneau ; gêne cosmétique sans impact sur les décisions.

## I. Sécurité

- **Réseau** : aucun module nouveau n'effectue de requête — vérifié par test de source (`requests`, `urllib.request`, `smtplib`, `socket`, `http.client` interdits dans `stage_search.py` et `application_prep.py`). La découverte réutilise le connecteur Greenhouse existant de Codex, inchangé.
- **Envoi** : rien n'est envoyé ; `automated_submission` reste `false` dans `/health` ; l'enregistrement « Envoyée » exige l'approbation locale préalable (testé) ; la réception confirmée exige une référence (testé) et n'est jamais réversible (testé).
- **Données privées** : la préparation exclut structurellement e-mail, téléphone et URL LinkedIn du profil (testé). Les critères de stage vivent dans `career_settings` : inclus dans l'export de données personnelles, effacés par `reset_personal_data` (testé).
- **Secrets** : aucun secret manipulé, aucun fichier hors du répertoire Career écrit, aucune base personnelle ajoutée.
- **`href` XSS** : le lien « offre officielle » de la préparation ne peut contenir que http/https — `canonical_url` valide le schéma à l'import (existant) et refuse identifiants/mot de passe dans l'URL.
- **Risques résiduels** : le texte de l'offre affiché provient de sources externes (import légal) ; il est affiché comme texte (pas de HTML injecté) et ses URLs sont inertes dans l'export calendrier (garantie existante de Codex).

## J. Intégration — ce que Codex doit faire

1. **Revoir le diff** : `git diff main...feature/career-stage-hunter` (12 fichiers, ≈2 100 lignes ajoutées, 20 retirées).
2. **Relancer les tests** : la commande de la section F (113 tests, ≈45 s).
3. **Décision de fusion** : la branche est basée sur `4e203a8`. `main` a avancé jusqu'à `7def985` (9 fichiers modifiés : `usage_ledger.py`, `tests/test_usage_ledger.py`, etc.) — **vérifié : aucun fichier `career/` ni `career_static/` touché, donc aucun conflit attendu**. Merge ou squash au choix ; aucune migration de schéma nécessaire (le brief vit dans `career_settings`).
4. **Points comportementaux à noter lors de la revue** :
   - création de suivi : statut par défaut `to_review` (était `to_prepare`) ;
   - `submitted`/`refused`/`offer_received` ajoutés aux ensembles post-dépôt et terminaux (calendrier) ;
   - `/api/career/health` gagne la clé `stage_search` (additive) ;
   - libellé JS `ready_to_apply` : « Prête ».
5. **Aucun fichier de Codex n'a été modifié** : `hybrid_chat.py`, `intelligence_bridge.py`, `free_ai_router.py`, `come_ai_web.py`, `devkit/`, `evals/`, `usage_ledger.py`, `docs/INTEGRATION_STATUS.md` intacts.

## K. État Git

- **Worktree** : `/Users/comedelavenne/AI-Excel-Agent-career`
- **Branche** : `feature/career-stage-hunter` (isolée depuis `4e203a8`)
- **Commits** :
  - `98a5815` — « Career: Stage Hunter — parcours de candidature en 5 étapes » (10 fichiers, +1 924/−17)
  - `089ea83` — « Career Stage Hunter: corrections de robustesse + tests de passation » (4 fichiers, +173/−3)
  - Ce document : commit de passation séparé.
- **Modifications non commitées** : aucune (hors ce document en cours d'écriture).
- **Fichiers nouveaux suivis** : `career/stage_search.py`, `career/application_prep.py`, `tests/test_career_stage_hunter.py`, `HANDOFF_career_stage_hunter.md`.
- Aucun `git reset --hard`, `git clean`, aucun force-push, aucun merge vers `main`.

## L. Démonstration (vérification en 2 minutes)

1. Démarrer l'app : `python run_come_ai_v3.py` → `http://localhost:8765/career` (port 8765, routeur déjà monté par `run_come_ai_v3.py` ; aucun launcher supplémentaire).
2. Onglet **Stage Hunter** → Étape A : cocher « M&A », villes « Paris », durée 4 → *Enregistrer mes critères* → le note sous le formulaire affiche le rappel « aucun préférences supposées ».
3. Étape D : choisir une offre (ou en importer une via l'onglet Découvrir, champ « URL officielle ») → *Analyser cette offre* → vérifier que chaque « élément pertinent » affiche entre guillemets un extrait **réel** du profil, et qu'une exigence sans équivalent apparaît sous « Non trouvé dans ton profil ».
4. Étape C : *Recalculer le classement* → chaque offre affiche un score avec ses raisons composante par composante.
5. Créer un suivi depuis une carte → **Candidatures** : le suivi démarre à « À examiner » ; tenter « Envoyée » sans approuver affiche le refus explicite ; après *Approuver le dépôt manuel*, « Envoyée » passe et la réception passe à « inconnue » ; confirmer la réception exige une référence ; « Offre reçue » devient disponible.

Test automatisé équivalent : `python -m pytest tests/test_career_stage_hunter.py::test_full_http_journey_from_brief_to_offer_received -q`.

## M. Prochaines étapes (3 prioritaires après intégration)

1. **Expérimentation réelle avec Codex** : lancer l'app, importer 3–5 offres de boards Greenhouse réels configurés par la personne, et vérifier la qualité perçue du classement expliqué (calibrage éventuel des seuils de libellés 70/45).
2. **Extension de découverte** (si demandée) : brancher un second connecteur légal existant sur le même pipeline de déduplication — sans toucher au cœur de scoring.
3. **Parcours Étape E enrichi** : dates de relance et prochaine action par candidature, en réutilisant la table d'événements existante (pas de migration).

---

## ADDENDUM — Sprint final (après `6368817`)

Mise à jour des points de ce document affectés par le sprint final :

- **Section F (« aucun test réseau réel ») : plus exact.** Une vérification réseau réelle a été effectuée avec autorisation explicite de Côme : GET anonymes en lecture seule vers `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` (board public **stripe** : HTTP 200, 722 offres, 5,6 Mo, ~3,9 s). Voir la section « Offres réelles » du rapport de sprint pour les détails. Les tests automatisés restent 100 % hors-ligne.
- **Deux bugs bloquants réels corrigés dans `career/discovery.py`** (détail dans le rapport de sprint) : bundle de certificats (certifi) et plafond de taille 4 Mo → 8 Mo.
- **Synonymes enrichis** (M&A, PE, TS, AM, FP&A) et **avertissement contrat permanent** ajouté au classement.
- **Copies d'interface** : guide 4 points dans l'Étape B + aide explicite du formulaire de source (Découvrir).
- **Guide utilisateur** : `GUIDE_STAGE_HUNTER_5_MINUTES.md` (langage courant).
- **Nouveaux tests** : parcours vierge, transport verrouillé, synonymes FR/EN sur 7 domaines (paramétré), cas difficiles (titre atypique, sans localisation, diplôme supérieur, CDI vs stage, dates hors fenêtre, multi-domaines).
