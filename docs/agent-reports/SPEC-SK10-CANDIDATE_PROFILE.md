# SPEC-SK10 — Profil candidat avec preuves approuvées

**Mission** : SK-10 — Transformer le CV importé en **profil structuré contrôlé par l'utilisateur** : des faits proposés automatiquement, chacun avec sa source exacte (page, offsets, citation), que la personne approuve, refuse, corrige ou suspend champ par champ.

**Branche** : `worker/cvboost-31-1792614191`
**Worktree** : `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-31-1792614191`
**Base** : `main` (`f5b22f2`)

---

## 1. Architecture

### Fichiers créés

| Fichier | Rôle |
|---------|------|
| `career/candidate_profile.py` | Modèle pur : `CandidateFact`, `FactProvenance`, `CandidateProfile`, les 5 statuts, les transitions autorisées, la projection « profil actif » |
| `career/profile_builder.py` | Pipeline local : document → faits proposés avec provenance exacte (page, offsets, citation) |
| `career_static/js/profile-builder.js` | UI d'approbation champ par champ (aucun fait n'est approuvé automatiquement) |
| `tests/test_candidate_profile.py` | 39 tests — modèle, builder, service, endpoints, exclusion du matching, garde-fous JS |
| `tests/fixtures/candidate_profile/synthetic_cv_fr.txt` | CV français synthétique (déjà, banque et école fictives) |
| `tests/fixtures/candidate_profile/synthetic_cv_en.txt` | CV anglais synthétique |
| `tests/fixtures/candidate_profile/synthetic_cv_irregular.txt` | CV synthétique à rubriques irrégulières (titres en ligne) |
| `tests/fixtures/candidate_profile/synthetic_cases.json` | Attentes de chaque fixture synthétique |
| `docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md` | Ce rapport |

### Fichiers modifiés

| Fichier | Modification |
|---------|--------------|
| `career/cv_quality/parser.py` | Ajout de l'extraction **paginée** (`PageText`, `PagedDocument`, `extract_paged_text_from_bytes`) — le texte retourné est identique à l'existant, mais chaque page connaît ses offsets exacts |
| `career/cv_quality/__init__.py` | Export de la nouvelle API paginée |
| `career/ocr.py` | `OCRResult.page_texts` : le texte reconnu page par page (provenance page pour l'OCR) |
| `career/vision_ocr.m` | Le helper macOS Vision renvoie désormais `page_texts` |
| `career/profile_import.py` | Vue publique `SECTION_ALIASES` + `normalise_heading()` pour que les deux extracteurs reconnaissent les mêmes rubriques |
| `career/service.py` | Persistance (2 tables additives), revue d'un fait, suppression, export, profil actif, et **branchement du profil approuvé dans le matching et la candidature** |
| `career/router.py` | 7 endpoints profil candidat (CRUD + approbation + export) |
| `career_static/index.html` | Panneau « Profil candidat » dans l'onglet *Mon profil* + chargement du script |
| `career_static/career.css` | Styles du panneau de revue |
| `come_ai_web.py` | Limite de taille d'upload appliquée à la nouvelle route document |

---

## 2. Le modèle

`career/candidate_profile.py` ne contient que de la donnée : aucun réseau, aucun OCR, aucun LLM.

### Les cinq statuts

| Statut | Sémantique | Utilisable pour le matching ? |
|--------|------------|-------------------------------|
| `proposed` | Extrait automatiquement, en attente de validation | **Non** |
| `approved` | Validé par la personne | **Oui** |
| `rejected` | Rejeté par la personne | **Non** |
| `modified` | Corrigé par la personne **après** approbation | **Oui** |
| `suspended` | Mis de côté temporairement | **Non** |

> **Précision importante sur `modified`.** Corriger la valeur d'un fait encore `proposed` **ne l'approuve pas** : le fait reste `proposed`, donc inutilisable. Seul un fait déjà approuvé qui est ensuite corrigé passe en `modified`. C'est ce qui rend la garantie « un fait non approuvé ne justifie jamais une candidature » réellement vérifiable.

### Transitions autorisées

```
proposed  → approved | rejected | suspended | modified
approved  → modified | rejected | suspended
modified  → approved | rejected | suspended
rejected  → proposed
suspended → proposed | approved | rejected
```

Une transition hors de ce tableau est refusée par l'API (HTTP 400).

### Provenance

`FactProvenance` porte la source exacte du fait :

```python
FactProvenance(
    source_document="cv-demo.pdf",   # nom d'origine
    source_kind="cv",                # cv, linkedin_text…
    extraction="text_layer",         # ou "ocr"
    page=2,                          # page 1-based (None si le format n'a pas de page)
    start_offset=1204,               # offset du premier caractère du passage
    end_offset=1231,                 # offset du dernier caractère (exclu)
    quote="2020 - 2023 | Analyste M&A | Banque Démo",  # citation verbatim
)
```

`document.text[start_offset:end_offset]` redonne **exactement** le passage cité : c'est testé.

---

## 3. Le pipeline

```
PDF / DOCX / TXT collé
  → extraction locale (parser Mission 01, pages + offsets)
  → OCR local si le PDF n'a pas de couche texte
  → propositions de faits (compétences, expériences, formation, langues, contacts, identité)
  → provenance : page + offsets + citation
  → approbation champ par champ (UI)
  → profil actif (faits approuvés uniquement)
```

### 3.1 Extraction paginée (Mission 01 réutilisée)

`career/cv_quality/parser.py` gagne `extract_paged_text_from_bytes()`. Le texte produit est **strictement identique** à celui de `extract_text_from_bytes()` — `_extract_pdf` a été refactoré pour partager `_extract_pdf_pages()` — mais chaque page connaît désormais ses bornes dans la chaîne complète. C'est ce qui rend possible la provenance « page + offsets ».

### 3.2 Détection des rubriques

Les rubriques sont reconnues avec les alias FR/EN déjà utilisés par l'import de profil (`SECTION_ALIASES`), y compris en ligne (`Compétences : Excel, R, Power BI`). Une rubrique vide ne produit aucun fait parasite.

### 3.3 Types de faits

| Type | Label | Valeur |
|------|-------|--------|
| `skill` | `Excel` | `Excel` |
| `language` | `Anglais` | `Anglais C1` (le niveau est conservé) |
| `education` | `Licence Économie` | la ligne complète (`2019 - 2022 \| Licence Économie \| Université Démo`) |
| `experience` | `Analyste M&A` | le bloc complet (société, dates, missions) |
| `contact` | `email` / `phone` / `linkedin` | la valeur |
| `identity` | `display_name` | le nom |

### 3.4 L'OCR n'est jamais approuvé automatiquement

- Le builder ne peut produire qu'un statut : `proposed`.
- Un fait lu par OCR porte `requires_review = True` et une confiance plafonnée à 0,4 ; l'UI affiche le bandeau « OCR : à vérifier ».
- Le helper macOS Vision renvoie désormais le texte page par page, donc un fait OCR garde aussi sa page.

---

## 4. Persistance

Deux tables **additives** (`CREATE TABLE IF NOT EXISTS`) créées à chaque initialisation :

- `candidate_profile_documents` — le document source (nom, type, extraction, pages, avertissements, fichier privé).
- `candidate_profile_facts` — un fait par ligne : valeur, statut, provenance complète, `corrected`, `requires_review`, confiance, horodatages.

`SCHEMA_VERSION` reste à **8** : aucune table existante n'est modifiée, aucune migration n'est nécessaire, et une base locale existante continue de fonctionner à l'identique. Les deux tables sont vidées par `reset_personal_data` et incluses dans `export_personal_data`.

---

## 5. Les faits non approuvés sont exclus du matching et de la candidature

C'est le critère bloquant pour SK-11. Trois chemins feeding ont été branchés sur `get_matching_profile()` :

| Chemin | Avant | Après |
|--------|-------|--------|
| `career/service.py:_scoring_context()` (score d'adéquation, panneau de préparation, sprint) | `candidate_profile` (table legacy) | faits approuvés, sinon valeur saisie à la main |
| `career/service.py:_application_context()` (brouillon CV / lettre) | idem | idem |
| `career/service.py:_generate_targeted_kit_files()` (dossier ciblé par variante) | `get_profile()` | `get_matching_profile()` |

Règle appliquée : un champ couvert par **au moins un** fait approuvé prend la valeur de ces faits ; un champ sans fait approuvé garde la valeur saisie à la main. Si aucun profil candidat n'a été construit, le comportement existant est inchangé (aucune régression sur les 1 460 tests existants).

Test de bout en bout : `test_an_application_draft_only_repeats_the_approved_facts` vérifie que le CV généré contient la compétence approuvée et **pas** celle qui est encore en attente.

---

## 6. API

| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/api/career/candidate-profile` | Profil complet : document, faits, compteurs par statut, profil actif |
| `POST` | `/api/career/candidate-profile/document` | Construit le profil depuis un document uploadé (multipart) |
| `POST` | `/api/career/candidate-profile/text` | Construit le profil depuis un texte collé |
| `PATCH` | `/api/career/candidate-profile/facts/{fact_id}` | Une action de revue : `status`, `value`, `note` |
| `DELETE` | `/api/career/candidate-profile/facts/{fact_id}` | Supprime un fait |
| `GET` | `/api/career/candidate-profile/export` | Export JSON portable (provenance comprise) |
| `DELETE` | `/api/career/candidate-profile` | Supprime le profil et son document source privé |

L'upload est streamé dans le dossier privé `career_data/documents` sous un nom opaque, comme l'import de profil existant ; la limite de 10 Mo est appliquée par le middleware.

---

## 7. L'interface

Panneau **« Profil candidat »** ajouté dans l'onglet *Mon profil* (`career_static/index.html`) avec le script `career_static/js/profile-builder.js`.

Chaque fait est une carte qui affiche :

- son libellé et sa valeur ;
- son statut ;
- **sa provenance** : `Page 2 · caractères 1204–1231 · « 2020 - 2023 | Analyste M&A | Banque Démo »` ;
- les actions : *Approuver*, *Refuser*, *Suspendre*, *Corriger*, *Supprimer*.

La correction se fait dans un champ en ligne (jamais de `window.prompt`), le refus et la suspension sont réversibles, et l'export / la suppression du profil sont accessibles dans le même panneau.

Garde-fous du module : pas de `innerHTML`, pas de `eval`, pas de `window.prompt` — le texte du document n'est jamais interprété comme du HTML. Le script est autonome (il ne dépend pas du chargement de `career.js`) et recharge le profil dès que la vue *Mon profil* devient visible.

---

## 8. Tests

```bash
.venv/bin/python -m pytest -q tests/test_candidate_profile.py   # 39 passed
.venv/bin/python -m pytest -q                                    # 1463 passed, 1 skipped
.venv/bin/python -m ruff check .                                 # All checks passed
git diff --check                                                 # propre
```

Couverture :

- **Modèle** — les 5 statuts, les transitions, la correction d'un fait proposé vs approuvé, la sérialisation sans perte, la projection « profil actif ».
- **Builder** — les 3 fixtures synthétiques (nombre de faits par type, libellés, valeurs), **exactitude des offsets et de la citation pour chaque fait**, provenance de page sur un PDF 2 pages fabriqué à la volée, aucun fait approuvé, faits OCR signalés.
- **Service** — persistance et relecture après réouverture de la base, revue unitaire, correction conservant la valeur extraite, suppression d'un fait et du profil, export JSON portable, conservation des approbations lors d'une reconstruction.
- **Matching / candidature** — faits en attente, refusés et approuvés ; brouillon de candidature.
- **Endpoints** — build/review/export/delete, statut inconnu, fait inexistant, upload de document.
- **Confidentialité** — export de confidentialité complet, réinitialisation globale.
- **JS** — garde-fous statiques + comportement réel exécuté sous Node (une carte par fait avec page/offsets/citation, affichage du profil actif et de son état vide, appels `PATCH`/`DELETE` sur les bons endpoints).

> Un de ces tests a trouvé un vrai défaut : `pbRenderSummary` masquait le `document` global par une constante locale, ce qui faisait échouer tout le rendu du panneau dans le navigateur. Le correctif est en place et un garde-fou statique empêche la régression.

**Aucun document réel dans les tests** : les trois CV sont des fixtures synthétiques (`Example Bank`, `Example University`, `Banque Démo`…), et le PDF multi-page est fabriqué octet par octet dans le test.

---

## 9. Limites assumées

- L'extraction reste heuristique et **locale** : elle propose, elle ne décide pas. Un fait mal découpé se corrige en un clic, ou se refuse.
- Un fait `proposed` corrigé reste `proposed` : il faut l'approuver explicitement. C'est volontaire.
- Les offsets portent sur le **texte extrait**, pas sur le PDF binaire : c'est le seul repère vérifiable et affichable de façon fiable.
- L'OCR reste dépendant des outils de ligne de commande Apple ; sans eux, le module refuse le document plutôt que de deviner.

---

## 10. Ce qui a été vérifié, et comment

| Critère de réussite | Preuve |
|----------------------|--------|
| Pipeline complet PDF → propositions → approbation → profil actif | `test_the_router_builds_reviews_and_exports_the_profile`, `test_a_two_page_pdf_gives_the_exact_page_of_each_fact` |
| 5 statuts implémentés | `test_the_five_documented_statuses_exist`, `test_transitions_are_enclosed_by_the_documented_rules` |
| Provenance exacte (page, offsets, quote) | `test_every_fact_keeps_an_exact_provenance` |
| OCR jamais auto-approuvé | `test_ocr_facts_are_flagged_for_review_and_capped_in_confidence`, `test_the_builder_never_approves_a_fact` |
| Suppression / export fonctionnels | `test_the_service_deletes_one_fact_and_the_whole_profile`, `test_the_service_exports_a_portable_json_profile` |
| Tests 100 % synthétiques | `tests/fixtures/candidate_profile/` (3 CV + JSON d'attentes) |
| Faits non approuvés exclus du matching/candidature | `test_unapproved_facts_are_excluded_from_the_matching_profile`, `test_an_application_draft_only_repeats_the_approved_facts` |
| Ruff clean, suite verte, `git diff --check` propre | section 8 |
| Rapport | ce fichier |
