# MISSION CODEX — Stage Hunter élargi + candidature 1-clic + coach CV (2026-10-20)

> **✅ MISSION LIVRÉE & FUSIONNÉE (2026-10-20)** — le candidat sur la branche
> `codex/career-cv-boost` (commits `fd51bdd`, `7834e45`) a été relu, validé
> (1145 tests verts) et fusionné dans `main` (fusion `e3c77f4`, 1147 tests
> verts, tag `v1-cvboost-2026-10-20`). Les suites du chantier sont cadrées
> par `docs/agent_missions/CAREER_CV_BOOST_10_BUILD_PROMPTS_2026-10-20.md`
> (missions 01 à 09, en cours d'exécution par d'autres agents) ; l'intégration
> finale est la Mission 10.

## 0. Contexte du dépôt (lis d'abord, dans cet ordre)

1. `README.md` (règles produit), `CODEX_READY.md` (workflow), `docs/ARCHITECTURE.md`
2. `HANDOFF_CODEX_MISSION_2026-10-20.md` (mission « radar de relances » : elle reste valable, traite-la comme le chantier 3 ci-dessous si elle n'est pas déjà faite)
3. Code : `career/service.py` (monolithe 3 858 lignes — NE PAS le réécrire, y greffer proprement), `career/stage_search.py`, `career/application_prep.py`, `career/application_studio.py`, `career/document_export.py`, `career/scoring.py`, `career/offer_qualification.py`, `career/connectors/`, `career/discovery.py`, `career/models.py`
4. UI : `career_static/index.html`, `career_static/career.js` (vue stagehunter + applications), `career_static/career.css` (tokens existants `--ink/--muted/--accent/--border/--canvas…`)

Ton rôle : tu implémentes. L'utilisateur relit mes diffs ensuite. Travaille sur une
branche dédiée, diff petits, commits atomiques avec messages français descriptifs.

## 1. CHANTIER A — Élargir le vivier de stages (max de choix, qualité gardée)

Objectif : l'utilisateur (étudiant finance, stages janvier–mars, ≥ 6 mois,
voulu international) doit voir **plus d'offres pertinentes** sans bruit.

1. **Audit des connecteurs** (`career/connectors/`, `career/source_registry.py`) :
   liste les sources actives, leurs limites (pagination, période, geographie)
   et documente-les dans `docs/agent-reports/C50-SOURCES-STATE.md`.
2. **Ajoute 2–4 sources publiques légales** de stage finance si elles manquent
   (ex. JobTeaser public, Welcome to the Jungle flux publics, offrii/university
   boards publics) — UNIQUEMENT via le mécanisme `connectors`/`sources`
   existant, avec `UserFacingError` propre si une source échoue (déjà le
   pattern : « Les offres déjà enregistrées sont conservées »).
3. **Déduplication robuste** : deux offres identiques d'une autre source ne
   doivent PAS doubler la liste (clé : entreprise + titre normalisé + URL
   officielle canonique). Vérifie le comportement existant et complète-le.
4. **Filtre de pertinence réglable** dans le brief Stage Hunter (djà stocké
   `career_settings` clé `stage_search_brief`, PAS de migration) : ajoute
   « durée minimale », « période », « remote/lieu » s'ils n'existent pas.
5. **Tri explicable** : chaque fiche affiche déjà un score — assure que le
   `scoring.reasons` liste TOUJOURS au moins 3 raisons concrets (durent,
   période, compétences), jamais de texte vague.
6. **Anti-aveugle** : si moins de 10 offres passent les filtres, l'UI le dit
   et propose d'élargir (bouton « élargir la recherche » = relance avec
   filtres assouplis, à conférer côté service).

## 2. CHANTIER B — Candidater en 1 minute (facilité maximale, envoi TOUJOURS manuel)

1. Depuis une fiche d'offre : bouton **« Candidater »** qui enchaîne :
   création du suivi (application) → pré-remplissage du dossier Studio
   (CV + lettre adaptés à CETTE offre via `application_studio.py` +
   `application_prep.py`) → export `.docx`/`.pdf` local (`document_export.py`
   existe) → ouverture de l'onglet candidature.
2. **Kit de candidature** : pour chaque application, un panneau « Kit » qui
   réunit : CV adapté, lettre adaptée, réponses types (motivation courte,
   disponibilité, prétentions) et les champs à copier-coller (titre, société,
   référence, URL) — copie presse-papiers via `navigator.clipboard`,
   jamais d'envoi automatique (interdit : `automated_submission = false`).
3. **Checklist de candidature** : 5 cases cochables locales (CV lu ? lettre
   personnalisée ? documents PDF vérifiés ? deadline vérifiée ? relance
   prévue ?) persistées dans `applications`/`application_events` SANS
   changement de schéma (event_type `checklist` + JSON dans `detail`).
4. **Export agenda** : il existe (`calendar_export.py`) — vérifie qu'une
   deadline d'offre ajoute bien un événement, sinon complète.

## 3. CHANTIER C — Meilleurs conseils CV (expliqués, factuels, locaux)

1. **Analyse CV ↔ offre** : pour un dossier, liste locale et objective :
   compétences demandées par l'offre absentes du CV (mots-clés exacts),
   réalisations du profil qui manquent de chiffres, sections trop longues
   (>3 pages = alerte), jargon/ATS (formules bizarres, colonnes dans le Word).
2. **Chaque conseil porte sa preuve** : « l'offre demande X (ligne N de la
   fiche) — ton CV ne le mentionne pas (fichier .docx, section Y) ». Jamais
   d'invention : si l'info manque, dire « à compléter avec toi ».
3. **Note de préparation** (0–100) par offre = combinaison expliquée de
   `scoring.py` + complétude du dossier + checklist — toujours affichée avec
   ses 3 facteurs principaux.
4. Un bouton « appliquer ce conseil » ouvre le Studio pré-rempli — ne
   modifie JAMAIS le CV source importé (il est dans `data/`, lecture seule).

## 4. Contraintes NON NÉGOCIABLES

- 100 % local sauf connecteurs existants ; tout nouveau fetch réseau passe
  par le mécanisme `connectors` et NEVER par une URL codée en dur dans le
  service. Aucun envoi d'un CV/lettre vers un service tiers.
- AUCUNE modification de `SCHEMA_VERSION` (7) ni de tables existantes.
- Pas de `window.prompt` (garde statique `tests/test_career_v5_ux_guards.py`).
- Pas de secret, pas de données réelles dans les fixtures, pas d'appel à une
  IA cloud non consentie (consentement signé `consent_guard` obligatoire).
- Style : erreurs en français via `UserFacingError`, `clean_text` pour toute
  entrée, réutiliser `_connection()`/`_lock` existants.
- Interdits git : `reset --hard`, `clean`, force-push, commit direct sur `main`.

## 5. Validation avant « terminé » (bloquant)

```bash
./checklist_codex.sh                      # lint + contrôles
.venv/bin/python -m pytest -q             # 100 % vert (baseline : 1141 passed)
```

+ tests nouveaux obligatoires (fixtures synthétiques uniquement) :
- déduplication 2 sources → 1 offre ;
- kit de candidature : champs pré-remplis exacts depuis l'offre ;
- checklist persistée et rejouable ;
- conseils CV : chaque item cite sa preuve, aucun inventé ;
- élargissement de recherche : filtres assouplis, annonce honnête.

## 6. Livrables

1. Branche `agent/stages-cv-boost` (partir de `main` à jour).
2. Code + tests + docs mises à jour (`README_CAREER*` si flux changé).
3. `docs/agent-reports/C50-STAGES-CV.md` : ce qui a changé, chiffres de
   couverture sources, limites restantes, suggestions de suite.
4. Si un remote GitHub est configuré : push + PR, laisse la CI arbitrer.
