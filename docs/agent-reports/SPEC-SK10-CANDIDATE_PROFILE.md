# SPEC-SK10 — Profil candidat avec preuves approuvées

**Mission** : CVBOOST-31 (SPEC Kit SK-10)
**Branche** : `worker/cvboost-31-1792615600` (alias `agent/spec-sk10-candidate-profile`)
**Base** : `main` — `f5b22f2` (merge ATS diagnostics + targeted CV variants pipeline)
**Date** : 2026-10-21
**Périmètre** : 100 % local, hors ligne, sans modèle et sans appel réseau

---

## 1. Ce qui a été livré

Le CV importé devient un **profil structuré fait de faits reviewables un par un**.
Chaque fait porte sa source (page, offsets exacts, citation) et son statut.
Seuls les faits qu'une personne a **approuvés** ou **corrigés** peuvent
justifier une candidature ; une proposition, un rejet et une mise de côté ne
justifient jamais rien.

```
PDF / DOCX / TXT
  → extraction locale (Mission 01 : career/cv_quality/parser.py)
  → OCR local macOS Vision si le PDF n'a pas de couche texte
  → propositions de faits (compétences, expériences, dates, diplômes, langues…)
  → provenance exacte (page, offsets, quote)
  → approbation champ par champ (UI)
  → profil actif (seuls les faits validés)
```

---

## 2. Fichiers

### 2.1 Nouveaux fichiers

| Fichier | Rôle |
|---------|------|
| `career/candidate_profile.py` | Modèle pur : `CandidateFact`, `CandidateProfile`, `FactProvenance`, les 5 statuts, les transitions autorisées, la validation des invariants, le merge, la sérialisation. |
| `career/profile_builder.py` | Pipeline pur : texte local → propositions avec provenance exacte. Aucune E/S, aucun réseau, aucun modèle. |
| `career_static/js/profile-builder.js` | UI d'approbation champ par champ (script autonome, CSP `script-src 'self'` respecté). |
| `scripts/candidate_profile_manual_check.py` | **Essai utilisateur réel, hors dépôt** : lit un CV que la personne possède, affiche les propositions avec leur passage source, et refuse de lire un fichier stocké dans le dépôt. N'écrit rien, n'envoie rien, n'approuve rien. |
| `tests/test_candidate_profile.py` | 46 tests : modèle, builder, service, HTTP, garde-fous JavaScript (Node), script manuel. |
| `tests/fixtures/candidate_profile/cv_synthetique.txt` | Fixture synthétique FR. |
| `tests/fixtures/candidate_profile/cv_ocr_synthetique.txt` | Fixture synthétique simulant une sortie OCR bruitée. |
| `tests/fixtures/candidate_profile/cv_anglais_synthetique.txt` | Fixture synthétique EN. |
| `tests/fixtures/candidate_profile/expected_facts.json` | Attendu déclaratif de l'extraction : ancrage de régression, pas d'oracle figé dans le code. |
| `docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md` | Ce rapport. |

### 2.2 Fichiers modifiés

| Fichier | Modification |
|---------|--------------|
| `career/cv_quality/parser.py` | Ajout de `PageText` et `extract_pages_from_bytes()` : le texte extrait est désormais accompagné des offsets de chaque page. `_extract_pdf()` a été refactoré sur `_extract_pdf_pages()` **sans changer le texte produit** (mêmes pages vides ignorées, même jointure `"\n\n"`). |
| `career/cv_quality/__init__.py` | Export de `PageText` et `extract_pages_from_bytes`. |
| `career/profile_import.py` | Deux ajouts additifs et publics : `PROFILE_SECTION_ALIASES` et `normalise_heading()`, pour partager un seul vocabulaire de rubriques entre l'ancien parseur plat et le nouveau builder. |
| `career/service.py` | Persistence et règles : 8 méthodes CareerService, la clé `career_settings` `candidate_profile_v1`, l'export JSON du profil, l'ajout du profil structuré à l'export de confidentialité. |
| `career/router.py` | 7 endpoints profil + 2 modèles de payload, l'upload de document, la capacité dans `/api/career/health`. |
| `career_static/index.html` | Panneau « Valider chaque information » dans l'onglet *Mon profil* + chargement du script. |
| `career_static/career.css` | Styles du panneau, des compteurs, des faits et de leurs états. |

### 2.3 Endpoints

| Méthode | Chemin | Rôle |
|---------|--------|------|
| `GET` | `/api/career/candidate-profile` | Profil structuré + état de la relecture. |
| `GET` | `/api/career/candidate-profile/active` | **Profil actif** : uniquement les faits validés, et rien d'autre. |
| `POST` | `/api/career/candidate-profile/proposals` | Propositions depuis un texte collé. |
| `POST` | `/api/career/candidate-profile/proposals/document` | Propositions depuis un document téléversé (OCR local si besoin). |
| `POST` | `/api/career/candidate-profile/facts/{fact_id}/decision` | Une décision humaine explicite sur un fait. |
| `DELETE` | `/api/career/candidate-profile/facts/{fact_id}` | Suppression d'un fait. |
| `DELETE` | `/api/career/candidate-profile` | Suppression du profil et du document source privé. |
| `GET` | `/api/career/candidate-profile/export` | Export JSON portable (`no-store`). |

---

## 3. Les six critères non négociables

| # | Critère | Comment il est tenu | Preuve |
|---|---------|----------------------|--------|
| 1 | **Résultat OCR jamais automatiquement approuvé** | L'OCR ne peut produire qu'une proposition : `propose_profile_facts()` crée toujours les faits en `proposed`, et un fait utilisable exige un `decided_at` (décision humaine horodatée) sinon `validate_profile()` le signale. | `test_an_ocr_document_is_only_ever_proposed`, `test_an_ocr_document_upload_is_only_ever_proposed`, `test_a_profile_with_an_approval_without_a_decision_is_reported` |
| 2 | **Chaque compétence, expérience, date, diplôme garde sa source** | Chaque fait porte `Provenance(page, start_offset, end_offset, quote, source_name, extraction_method)`. Les dates sont des faits à part entière (`kind = date`), avec leur propre offset. Les offsets sont vérifiés dans les tests : le passage `text[start:end]` est exactement la citation stockée. | `test_every_proposal_keeps_the_exact_place_it_was_read_from`, `test_the_offsets_point_at_the_quote_that_is_stored`, `test_the_page_of_a_fact_follows_the_document`, `test_a_date_is_a_fact_of_its_own_with_its_own_source` |
| 3 | **Suppression et export fonctionnent (profil portable)** | Suppression d'un fait, suppression du profil (avec le document source privé), export JSON, et présence du profil structuré dans l'export de confidentialité. | `test_a_fact_can_be_deleted_and_the_profile_can_be_deleted`, `test_the_profile_can_be_exported_as_a_portable_file`, `test_the_private_export_contains_the_structured_profile` |
| 4 | **Aucun document réel dans les tests** | Trois fixtures 100 % synthétiques (noms fictifs, `example.org`, entreprises inventées) + un PDF fabriqué en mémoire. Aucun CV réel, aucune donnée personnelle. | `tests/fixtures/candidate_profile/` |
| 5 | **Faits non approuvés ≠ justifier une candidature (bloquant pour SK-11)** | `usable_facts` / `usable_summary()` / `usable_for_matching` n'exposent que les faits `approved` et `modified`. `require_candidate_profile_evidence()` **refuse** (400) tant que rien n'a été validé : c'est le contrat à consommer par SK-11. | `test_nothing_may_justify_a_candidature_before_a_fact_is_validated`, `test_a_rejected_fact_never_reaches_the_matching_summary`, `test_a_suspended_fact_never_reaches_the_matching_summary` |
| 6 | **Vrais essais utilisateur séparés des fixtures Git** | `scripts/candidate_profile_manual_check.py` lit un CV réel **hors du dépôt** (il refuse explicitement un fichier situé dans le dépôt), affiche les propositions avec leur passage source, et n'approuve rien. Les fixtures Git restent 100 % synthétiques. | `test_the_manual_check_script_refuses_a_file_stored_in_the_repository`, `test_the_manual_check_script_works_outside_the_repository` |

---

## 4. Les cinq statuts

| Statut | Sémantique | Utilisable pour une candidature | Transition sortante |
|--------|------------|-------------------------------|---------------------|
| `proposed` | Extrait automatiquement, en attente de validation | ❌ | → `approved`, `rejected`, `modified`, `suspended` |
| `approved` | Validé par la personne | ✅ | → `rejected`, `modified`, `suspended` |
| `rejected` | Rejeté (erreur OCR, hors sujet) | ❌ | → `proposed`, `modified`, `suspended` |
| `modified` | Corrigé par la personne | ✅ | → `approved`, `rejected`, `suspended` |
| `suspended` | Mis de côté temporairement | ❌ | → `proposed`, `approved`, `rejected`, `modified` |

**Choix explicite : `modified` est utilisable.** La personne a réécrit la
valeur avec ses propres mots : la valeur est la sienne, pas celle de la
machine. La valeur d'origine (`original_value`) est conservée pour l'audit.

**`decided_at` est le verrou.** Un fait `approved` ou `modified` sans
`decided_at` est invalide : `validate_profile()` le signale et
`decide_fact()` refuse de l'obtenir autrement. C'est cette contrainte, et non
une simple convention, qui rend l'approbation automatique impossible.

---

## 5. Découpage technique

### 5.1 `career/candidate_profile.py` — modèle pur

* `CandidateFact` : `id`, `kind`, `label`, `value`, `status`, `provenance`,
  `original_value`, `note`, `decided_at`, `created_at`, `updated_at`, `metadata`.
* `CandidateProfile` : container + `facts_with_status()`, `usable_facts`,
  `pending_facts`, `counts()`, `usable_summary()`, `with_fact()`, `without_fact()`.
* `decide_fact()` : une seule porte d'entrée pour les décisions ; refuse une
  transition interdite, refuse une correction sans valeur, refuse une
  approbation sans valeur.
* `merge_facts()` : un second import ne remplace jamais une décision déjà
  prise (déduplication sur `kind` + valeur normalisée).
* `validate_profile()` : liste les règles cassées (statut inconnu, décision
  humaine absente, source perdue, offsets incohérents).

### 5.2 `career/profile_builder.py` — pipeline pur

* Détection de rubriques réutilisant **un seul vocabulaire** partagé avec
  `career/profile_import.py` (`PROFILE_SECTION_ALIASES` + `normalise_heading`),
  complété des rubriques `Projets` et `Certifications`.
* Le contenu d'une rubrique commence **après** la ligne de titre : un titre
  de rubrique n'est jamais lu comme un fait.
* Découpe :
  * compétences → une par item (`;` `,` `|`, puces) ;
  * langues → une par item, **le niveau reste attaché** (`Anglais - C1`) ;
  * formations / projets / certifications → une par ligne ;
  * expériences → regroupement par ligne d'en-tête datée
    (`2021-2024 | Data Analyst | Banque Horizon`), description incluse,
    `metadata` = `role`, `company`, `start_date`, `end_date`.
* Identité et coordonnées : propositions localisées dans le texte
  (`_locate`), avec un garde-fou `_looks_like_person_name()` qui empêche de
  proposer une phrase comme identité.
* `build_source_pages()` / `page_for_offset()` : attribution de page à partir
  des pages fournies par `extract_pages_from_bytes()`.

### 5.3 `career/service.py` — persistence et règles

* Stockage : `career_settings` clé `candidate_profile_v1` (une valeur JSON).
  **Aucune migration de schéma** : `SCHEMA_VERSION` reste à 8, la base d'un
  utilisateur existant n'est pas touchée, et `reset_personal_data()` efface
  déjà cette table.
* Le document source est stocké sous `career_data/documents/profile_candidat_<uuid><ext>`
  en `0600`. Le nom commence par `profile_` pour que le nettoyage « Supprimer
  mes données Career » l'emporte avec les autres sources privées.
* `require_candidate_profile_evidence()` : garde-fou SK-11, refuse tant que
  rien n'est validé.
* `export_candidate_profile()` : JSON portable dans `career_data/exports/`,
  `0600`, `Cache-Control: no-store` sur la route.

### 5.4 UI

Panneau « Valider chaque information » dans l'onglet *Mon profil* :

* import d'un document ou collage d'un texte ;
* compteur par statut ;
* rappel des **faits utilisables** (ceux qui peuvent justifier une candidature) ;
* une carte par fait : type, statut, badge `OCR`, source dépliable
  (page, citation, offsets), champ de correction, et les cinq décisions ;
* export et suppression du profil.

Le script est autonome : il ne dépend d'aucun autre fichier JS et n'envoie
aucune décision qu'après un clic explicite.

---

## 6. Vérifications

```bash
.venv/bin/python -m pytest -q tests/test_candidate_profile.py   # 46 passed
.venv/bin/python -m pytest -q                                    # 1470 passed, 1 skipped
.venv/bin/python -m ruff check .                                 # All checks passed!
git diff --check                                                 # propre
```

Le contrôleur `checklist_codex.sh` passe aussi (`main`, `lint`, `secrets`,
`devkit` au vert ; les étapes mémoire / studio-coach sont ignorées quand le
worktree correspondant n'existe pas).

---

## 7. Note de relecture : une implémentation parallèle existe

La mission SK-10 a déjà été traitée par une commande antérieure, poussée sur
`agent/spec-sk10-candidate-profile` (commit `2448d28`, base `f5b22f2` — la
même base que cette branche). **Les deux branches touchent les mêmes
fichiers** (`career/candidate_profile.py`, `career/profile_builder.py`,
`career_static/js/profile-builder.js`, `tests/test_candidate_profile.py`,
`docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md`) : **elles ne doivent pas
être fusionnées ensemble**, cela produirait des conflits sur tous ces
fichiers.

Cette branche-ci est **le sur-ensemble** de l'autre :

| Point | `agent/spec-sk10-candidate-profile` (antérieur) | Cette branche |
|-------|--------------------------------------------------|---------------|
| Stockage | 2 tables SQLite dédiées (`career/profile_store.py`) | 1 valeur JSON dans `career_settings` : **aucune** table ajoutée, aucun risque de migration |
| Persistance du texte source | le texte du document est gardé en base | le document privé est gardé en `0600` sur disque, la citation dans chaque fait |
| Verrou d'approbation | acteur `user` / `system` + `AutoApprovalError` | `decided_at` obligatoire + `validate_profile()` : invariant vérifié, pas seulement conventionnel |
| Dates | faits `date` de première classe | faits `date` de première classe |
| Profil actif | `/api/career/profile-facts/active` | `/api/career/candidate-profile/active` |
| Garde-fou SK-11 | — (à faire) | `require_candidate_profile_evidence()` : refus explicite tant que rien n'est validé |
| Export de confidentialité | — | le profil structuré est dans `export_personal_data()` |
| Reset global | traité dans le router | traité par `career_settings` + le motif `profile_*` existant |
| Essai manuel hors dépôt | `scripts/candidate_profile_manual_check.py` | `scripts/candidate_profile_manual_check.py` (équivalent) |
| Tests | 37 | 46 (dont garde-fous Node et essai manuel exécuté) |
| `career/service.py` | non modifié | intégré (persistance + garde-fou + export) |

**Recommandation : n'intégrer que cette branche** (`worker/cvboost-31-1792615600`)
et laisser l'autre de côté. L'autre branche n'a pas été modifiée ni écrasée :
sa destruction n'est pas une décision que l'agent puisse prendre seul.

---

## 8. Limites connues et suite SK-11

1. **Le chemin de candidature existant n'a pas été réécrit.** Il utilise le
   profil *plat* (`candidate_profile`), que la personne remplit à la main :
   ces données sont déjà validées par leur auteur. Le profil *structuré*
   concerne les faits **extraits par la machine**, et c'est lui qui est
   verrouillé. SK-11 doit consommer `require_candidate_profile_evidence()` /
   `usable_summary()` et jamais `facts`.
2. **La proposes-from-document passe par `profile_imports` ?** Non : le
   profil structuré a son propre chemin (`build_candidate_profile_from_document`)
   et son propre fichier privé. Les deux fonctionnalités restent
   indépendantes ; la source plate n'est pas dupliquée.
3. **Heuristiques de lecture** : une mise en page très atypique (colonnes,
   tableaux PDF) peut produire des propositions mal segmentées. C'est
   précisément le rôle de la relecture champ par champ : la personne corrige
   ou rejette. La régression des propositions est couverte par les offsets
   exacts, pas par un score.
4. **Pas d'import de profil structuré** : l'export existe, la réimportation
   n'est pas implémentée. Le format d'export est documenté et stable
   (`profile` / `counts` / `usable` / `exported_at`).
5. **Aucun OCR réel dans les tests** : le moteur macOS Vision n'est pas
   exécutable de façon fiable en CI ; le test injecte un faux OCR et vérifie
   le contrat (propositions uniquement, jamais approuvées).

---

## 9. Points de relecture recommandés

1. `career/candidate_profile.py` — la table des transitions et la règle
   `decided_at`.
2. `career/profile_builder.py` — `_heading_kind()`, `_group_experience_entries()`.
3. `career/service.py` — les 8 méthodes `*_candidate_profile*` et la clé
   `career_settings`.
4. `career/router.py` — les 7 endpoints et `_store_candidate_profile_document()`.
5. `career/cv_quality/parser.py` — le refactor de `_extract_pdf()` :
   **le texte produit est inchangé** (pages vides ignorées, jointure `"\n\n"`),
   seul `extract_pages_from_bytes()` est ajouté.
