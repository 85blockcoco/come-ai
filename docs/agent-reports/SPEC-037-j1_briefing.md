# SPEC-037 — Briefing J-1 veille d'entretien

> Consolidation de la livraison partielle du 31/10 01:44 (`9d27d50`, module seul,
> sans routes REST, sans fixture, rapport qui listait lui-même ces lacunes comme
> « limites ») — cette revue complète les 4 livrables de la mission sans rien
> réécrire d'autre.

## Livré

- `career/j1_briefing.py` : `BriefingDoc` (contrat must-have), `build_j1_briefing()`,
  `to_dict()`, plus les coutures d'assemblage `company_facts_from_job()`,
  `top_questions_from_job()`, `star_worksheets_from_sessions()`,
  `admin_applicability()`, `admin_blockers_for_job()`, `cv_reread_from_prep()`,
  `briefing_for_application(service, application_id)` et l'export
  `render_markdown()`.
- 2 routes REST dans `career/router.py`, servies par `create_app()` (aucune route
  existante modifiée, `schema_version` et le schéma SQLite intacts) :
  - `GET /api/career/applications/{application_id}/j1-briefing` → le JSON complet
    (fiche sourcée, questions, STAR, administratif, CV, sections à compléter) ;
  - `GET /api/career/applications/{application_id}/j1-briefing.md` → le même
    document en Markdown téléchargeable : **un seul lien d'export**.
- `tests/test_j1_briefing.py` : 34 tests dont **4 adversariaux**, et
  `tests/fixtures/j1_synthetic.json` (fixture synthétique : offre Nexora Labs
  Berlin, panneau d'écarts, 3 séances d'entretien, checklist administrative).

## Décisions

- **Rien n'est jamais masqué** : toute section vide ou incomplète produit une
  entrée `incomplete_sections` préfixée « À COMPLÉTER » (fiche, questions,
  worksheets, checklist SPEC-028 si applicable, revue du CV si le panneau de
  préparation est indisponible). `cv_section_reread=None` (analyse absente) et
  `[]` (rien à relire) sont deux états distincts — le premier est une lacune
  affichée, le second ne l'est pas.
- **Sources de la fiche entreprise** : chaque fait cite `(source : <source_name>,
  <official_url>)` ; seule une URL `http(s)` valide est publiée (test
  adversarial `javascript:`/`data:`/`ftp:`/protocole-relatif → jamais de lien).
- **Complétude STAR sans inventedure** : si une worksheet porte une complétude
  explicite valide (finie, dans [0;1]), elle fait foi ; toute valeur malformée
  (NaN, « 0.95x », booléen, 42, -3) est rejetée et la complétude est recalculée
  sur les 4 volets STAR renseignés, sinon 0 (jamais « prêt »). À défaut de
  worksheets structurées, la complétude d'une séance du coach est le nombre de
  volets STAR (situation/task/action/result, lexique fermé fr/en) détectés dans
  les réponses réelles de la séance — aucune phrase n'est réécrite ni fabriquée.
- **Lecture seule, non bloquante** : `briefing_for_application()` ne fait que des
  lectures (`get_application`, `get_job`, `get_job_prep`, séances) ; une lecture
  secondaire qui échoue devient un marqueur explicite, jamais une erreur 500 et
  jamais une section silencieusement vide. L'historique des séances n'embarque
  pas les réponses : au plus 5 séances sont relues (`get_interview_session`)
  pour évaluer les volets STAR.
- **Aucune écriture, aucun réseau, aucune clé** : module pur + routes de lecture ;
  `automated_submission: false` rappelé dans `meta`.

## Coutures SPEC-027 / 028 / 031 (découplées, testées)

- **SPEC-031 (`career/faq_mining`) est fusionnée sur cette branche** : les
  questions probables en proviennent réellement (`mine_sector_faq()` sur
  description + prérequis de l'offre → `expected_questions()`), testé par
  `test_spec031_faq_mining_drives_questions_when_present` + smoke REST
  (`meta.questions_source == "spec-031"`). Repli local déterministe (4 questions
  dérivées des champs de l'offre) si le module est absent ou échoue →
  `meta.questions_source == "local"` — jamais de section vide.
- **SPEC-027 (`career/interview_sim`, branche `agent/spec-027-interview-sim`,
  non fusionnée ici)** : couture par les champs `star_worksheets`/`worksheets`
  des séances quand ils existent (testée avec worksheets structurées), sinon
  calcul sur les réponses. Aucune dépendance d'import : la fusion ultérieure ne
  casse ni le module ni les tests.
- **SPEC-028 (`career/stage_admin_docs`, branche `agent/spec-028-stage-admin-docs`,
  non fusionnée ici)** : checklist demandée seulement pour un stage à l'étranger
  (pays ≠ France + stage/alternance/apprentissage) ; si le module est présent,
  `blocking_missing` devient `admin_blockers` avec libellés ; sinon
  `admin_applicable=true`, `admin_blockers=[]` et un marqueur « À COMPLÉTER
  SPEC-028 ». Invariant testé (unité + REST) : **soit des blocages, soit un
  marqueur — jamais les deux, jamais rien**. Une candidature française ou un
  CDI à l'étranger ne produit aucun faux blocage.

## Limites

- Les worksheets dérivées des séances mesurent la présence des volets STAR dans
  les réponses, pas la qualité du contenu (SPEC-027 porte l'auto-évaluation
  chiffrée quand il sera fusionné).
- Les secteurs/familles et libellés de checklist viennent des specs voisines :
  aucune redéfinition locale (pas de copie des lexiques SPEC-027/028 ici).
- La fixture n'exerce pas `get_job_prep` réel avec un profil complet : le chemin
  des écarts est couvert par la fixture de panneau + la lecture non bloquante.

## Validation

- `pytest -q tests/test_j1_briefing.py` → **34 passed** (4 adversariaux :
  complétude malformée, URLs non-http, listes géantes bornées, textes
  multilignes/worksheet illisible).
- `ruff check .` → All checks passed !
- `git diff --check` → propre.
- **Base de la branche d'intégration AVANT cette livraison** (mesurée sur
  `350cdf9`, sans mes fichiers) : `pytest -q` interrompu par
  `tests/test_claim_check.py` → `ImportError: ApprovedEvidence` (conflit de la
  mission 77 : `13e8c77` a remplacé `career/claim_check.py` de 1588 lignes par
  une implémentation 145 lignes sans mettre son propre test à jour) ; avec ce
  fichier ignoré : **1 failed, 3238 passed, 1 skipped** — l'échec
  `test_career_agent::test_local_storage_profile_preferences_and_persistence`
  (14 familles ≠ 6) est également préexistant. Aucun de ces deux défauts n'est
  touché par SPEC-037 (ni `career/claim_check.py`, ni les préférences) ; ils
  restent la charge de la mission 77 / du registre.
- **Après livraison** (`pytest -q --ignore=tests/test_claim_check.py`) :
  **1 failed, 3264 passed, 1 skipped** — exactement les 2 défauts préexistants,
  aucun nouveau. Base 3238 → 3264 = +26 tests nets (la version committée du
  fichier n'en avait que 8) : `tests/test_j1_briefing.py` → 34 passed.
- `./checklist_codex.sh main` → `TOUT VERT` (exit 0), idem `lint` et `secrets`.
  **Réserve honnête** : la porte de tests de `run_main` est ineffective — le
  commentaire annonce `pipefail actif` mais le script ne le règle jamais, donc
  `pytest … | tail -3` rend toujours le code de `tail` (0) et le gate passe même
  sur l'erreur de collecte de `tests/test_claim_check.py`. La preuve réelle est
  donc les deux exécutions pytest ci-dessus, pas ce script. `checklist_codex.sh`
  est un outil d'orchestrateur partagé : non modifié ici (hors périmètre).
