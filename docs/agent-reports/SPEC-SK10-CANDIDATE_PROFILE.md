# SPEC-SK10 — Profil candidat avec preuves approuvées

**Mission** : CVBOOST-31 (Spec Kit SK-10)
**Branche de livraison** : `worker/cvboost-31-1792617513`
**Base** : `main` — `f5b22f2` (merge ATS diagnostics + targeted CV variants pipeline)
**Date** : 2026-10-21
**Périmètre** : 100 % local, hors ligne, sans modèle et sans appel réseau

> ⚠️ **À lire en premier — cinq implémentations parallèles existent.**
> La mission SK-10 a été traitée plusieurs fois sur la **même base**
> (`f5b22f2`), par des agents concurrents. Les branches touchent les **mêmes
> fichiers** : elles ne doivent **pas** être fusionnées ensemble.
>
> | Branche | Lot | État |
> |---------|-----|-------|
> | `worker/cvboost-31-1792607995` | A | `career/profile_store.py` dédié, sans `career/service.py` |
> | `worker/cvboost-31-1792614191` | B | tables SQLite dédiées, premier câblage du critère 5 |
> | `agent/spec-sk10-candidate-profile` (= `worker/cvboost-31-1792614464`) | C | variante du lot B, **puis audit adversarial complet** (6 défauts corrigés, 58 tests) |
> | `worker/cvboost-31-1792615600` | D | modèle `decided_at`, builder, service, UI, 46 tests |
> | **`worker/cvboost-31-1792617513` (cette branche)** | **E** | **= D + audit adversariale + consolidation** |
>
> **Recommandation : intégrer `agent/spec-sk10-candidate-profile` (lot C
> audité), qui est la branche désignée par le registre.** Cette branche-ci est
> une **alternative complète et verte**, utile comme référence : elle apporte
> trois propriétés que le lot C n'a pas (voir §7), mais elle n'est pas
> nécessaire au livrable. Le détail honnête du comparatif est en §7.
> Aucune des autres branches n'a été modifiée ni écrasée : leur suppression
> n'est pas une décision que l'agent puisse prendre seul.

---

## 1. Ce qui a été livré

Le CV importé devient un **profil structuré fait de faits reviewables un par un**.
Chaque fait porte sa source (page, offsets exacts, citation) et son statut.
**Seuls les faits qu'une personne a approuvés ou corrigés peuvent justifier
une candidature** : une proposition, un rejet et une mise de côté n'y touchent
jamais — pas même le brouillon de CV envoyé à une offre.

```
PDF / DOCX / TXT / MD
  → extraction locale (Mission 01 : career/cv_quality/parser.py)
  → OCR local macOS Vision si le PDF n'a pas de couche texte
  → propositions de faits (compétences, expériences, dates, diplômes, langues…)
  → provenance exacte (page, offsets, citation)
  → approbation champ par champ (UI)
  → profil actif (seuls les faits validés)
  → candidature (uniquement les faits validés)
```

---

## 2. Fichiers

### 2.1 Nouveaux fichiers

| Fichier | Rôle |
|---------|------|
| `career/candidate_profile.py` | Modèle pur : `CandidateFact`, `CandidateProfile`, `FactProvenance`, les 5 statuts, les transitions autorisées, la validation des invariants, la projection sur le profil Career, le merge, la sérialisation. |
| `career/profile_builder.py` | Pipeline pur : texte local → propositions avec provenance exacte. Aucune E/S, aucun réseau, aucun modèle. |
| `career_static/js/profile-builder.js` | UI d'approbation champ par champ (script autonome, CSP `script-src 'self'` respecté). |
| `scripts/candidate_profile_manual_check.py` | **Essai utilisateur réel, hors dépôt** : lit un CV que la personne possède, affiche les propositions avec leur passage source, et refuse de lire un fichier stocké dans le dépôt. N'écrit rien, n'envoie rien, n'approuve rien. |
| `tests/test_candidate_profile.py` | **64 tests** : modèle, builder, service, HTTP, garde-fous JavaScript (Node), essai manuel exécuté. |
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
| `career/candidate_profile.py` | **+ `active_profile_fields()`** : la projection des faits validés sur les champs du profil Career (contrat du critère 5). |
| `career/service.py` | Persistence et règles : 10 méthodes `CareerService`, la clé `career_settings` `candidate_profile_v1`, **la projection des faits validés sur le profil de candidature**, l'export JSON du profil, l'ajout du profil structuré à l'export de confidentialité. |
| `career/router.py` | 8 endpoints profil + 2 modèles de payload, l'upload de document, le contrat `/evidence`, la capacité dans `/api/career/health`. |
| `career/ocr.py` | `OCRResult.page_texts` : l'OCR renvoie désormais le texte **page par page**, pour qu'un fait lu par OCR sache sa page. |
| `career/vision_ocr.m` | Le payload JSON de l'OCR expose `page_texts`. |
| `come_ai_web.py` | Le plafond de taille de corps s'applique aussi à l'upload du profil candidat. |
| `career_static/index.html` | Panneau « Valider chaque information » dans l'onglet *Mon profil* + chargement du script. |
| `career_static/career.css` | Styles du panneau, des compteurs, des faits et de leurs états. |
| `career_static/js/profile-builder.js` | **+ table des transitions** : l'interface n'offre plus une transition que le modèle refuserait. |

### 2.3 Endpoints

| Méthode | Chemin | Rôle |
|---------|--------|------|
| `GET` | `/api/career/candidate-profile` | Profil structuré + état de la relecture + `problems` (invariants cassés). |
| `GET` | `/api/career/candidate-profile/active` | **Profil actif** : uniquement les faits validés, et rien d'autre. |
| `GET` | `/api/career/candidate-profile/evidence` | **Contrat SK-11** : les faits qui peuvent justifier une candidature, sinon refus explicite (400). |
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
| 1 | **Résultat OCR jamais automatiquement approuvé** | L'OCR ne peut produire qu'une proposition : `propose_profile_facts()` crée toujours les faits en `proposed`. Un fait utilisable exige un `decided_at` (décision humaine horodatée) **et** `decide_fact()` refuse d'enregistrer une approbation sans date. `validate_profile()` signale tout fait utilisable sans décision. | `test_an_ocr_document_is_only_ever_proposed`, `test_an_ocr_document_upload_is_only_ever_proposed`, `test_a_validated_decision_without_a_date_is_refused`, `test_a_profile_with_an_approval_without_a_decision_is_reported` |
| 2 | **Chaque compétence, expérience, date, diplôme garde sa source** | Chaque fait porte `Provenance(page, start_offset, end_offset, quote, source_name, extraction_method)`. Les dates sont des faits à part entière (`kind = date`), avec leur propre offset. **Les offsets décrivent toujours exactement la citation affichée** : un passage trop long est coupé *avec* ses offsets, jamais avec des points de suspension. Un fait lu par OCR garde sa page. | `test_every_proposal_keeps_the_exact_place_it_was_read_from`, `test_the_offsets_point_at_the_quote_that_is_stored`, `test_the_quote_is_exactly_the_quoted_passage`, `test_every_quote_describes_its_own_offsets`, `test_the_page_of_a_fact_follows_the_document`, `test_the_page_of_a_fact_survives_normalised_line_endings`, `test_an_ocr_fact_keeps_the_page_it_was_read_from`, `test_a_date_is_a_fact_of_its_own_with_its_own_source` |
| 3 | **Suppression et export fonctionnent (profil portable)** | Suppression d'un fait, suppression du profil (avec le document source privé), export JSON, et présence du profil structuré dans l'export de confidentialité. | `test_a_fact_can_be_deleted_and_the_profile_can_be_deleted`, `test_the_profile_can_be_exported_as_a_portable_file`, `test_the_private_export_contains_the_structured_profile` |
| 4 | **Aucun document réel dans les tests** | Trois fixtures 100 % synthétiques (noms fictifs, `example.org`, entreprises inventées) + un PDF fabriqué en mémoire. Aucun CV réel, aucune donnée personnelle. | `tests/fixtures/candidate_profile/` |
| 5 | **Faits non approuvés ≠ justifier une candidature (bloquant pour SK-11)** | **Câblé, pas seulement documenté** : les faits validés (`approved`/`modified` + `decided_at`) sont projetés sur le profil Career (`active_profile_values()`), et c'est ce profil **projeté** qui alimente le brouillon de candidature (`_application_context`) et la couverture des variantes de CV. Un fait proposé, rejeté ou mis de côté n'est jamais lu. La projection **fusionne** avec ce que la personne a saisi à la main : rien n'est écrasé, rien ne peut rester périmé. `require_candidate_profile_evidence()` refuse (400) tant que rien n'a été validé. | `test_an_unapproved_fact_never_reaches_the_application_draft`, `test_a_rejected_fact_never_reaches_the_application_draft`, `test_a_suspended_fact_never_reaches_the_application_draft`, `test_a_validated_fact_reaches_the_application_draft`, `test_a_corrected_fact_reaches_the_application_draft`, `test_the_matching_profile_carries_only_the_validated_facts`, `test_the_typed_profile_is_never_lost_by_a_validated_fact`, `test_a_validated_fact_already_typed_is_not_written_twice`, `test_the_api_never_justifies_a_candidature_without_a_decision`, `test_the_evidence_contract_serves_the_validated_facts` |
| 6 | **Vrais essais utilisateur séparés des fixtures Git** | `scripts/candidate_profile_manual_check.py` lit un CV réel **hors du dépôt** (il refuse explicitement un fichier situé dans le dépôt), affiche les propositions avec leur passage source, et n'approuve rien. Les fixtures Git restent 100 % synthétiques. | `test_the_manual_check_script_refuses_a_file_stored_in_the_repository`, `test_the_manual_check_script_works_outside_the_repository` |

---

## 4. Les cinq statuts

| Statut | Sémantique | Utilisable pour une candidature | Transition sortante |
|--------|------------|-------------------------------|---------------------|
| `proposed` | Extrait automatiquement, en attente de validation | ❌ | → `approved`, `rejected`, `modified`, `suspended` |
| `approved` | Validé par la personne | ✅ | → `modified`, `rejected`, `suspended` |
| `rejected` | Rejeté (erreur OCR, hors sujet) | ❌ | → `proposed`, `modified`, `suspended` |
| `modified` | Corrigé par la personne | ✅ | → `approved`, `rejected`, `suspended` |
| `suspended` | Mis de côté temporairement | ❌ | → `proposed`, `approved`, `rejected`, `modified` |

**Choix explicite : `modified` est utilisable.** La personne a réécrit la
valeur avec ses propres mots : la valeur est la sienne, pas celle de la
machine. La valeur d'origine (`original_value`) est conservée pour l'audit.

**`decided_at` est le verrou.** Un fait `approved` ou `modified` sans
`decided_at` est inutilisable : `decide_fact()` refuse de produire cet état
et `validate_profile()` le signale. C'est cette contrainte, et non une simple
convention, qui rend l'approbation automatique impossible.

**Le tableau des transitions est partagé.** `career_static/js/profile-builder.js`
miroite `ALLOWED_FACT_TRANSITIONS` : l'interface n'offre jamais une
transition que le modèle refuserait (un clic ne peut pas finir sur un 400),
et un test Node compare les deux tables à chaque exécution.

---

## 5. Découpage technique

### 5.1 `career/candidate_profile.py` — modèle pur

* `CandidateFact` : `id`, `kind`, `label`, `value`, `status`, `provenance`,
  `original_value`, `note`, `decided_at`, `created_at`, `updated_at`, `metadata`.
* `CandidateProfile` : container + `facts_with_status()`, `usable_facts`,
  `pending_facts`, `counts()`, `usable_summary()`, `with_fact()`, `without_fact()`.
* `decide_fact()` : une seule porte d'entrée pour les décisions ; refuse une
  transition interdite, refuse une correction sans valeur, refuse une
  approbation sans valeur **et** sans date de décision.
* `merge_facts()` : un second import ne remplace jamais une décision déjà
  prise (déduplication sur `kind` + valeur normalisée).
* `validate_profile()` : liste les règles cassées (statut inconnu, décision
  humaine absente, source perdue, offsets incohérents).
* **`active_profile_values()` / `active_profile_fields()`** : les valeurs
  validées de chaque champ du profil Career (`display_name`,
  `contact_email`, `contact_phone`, `linkedin_url`, `education`, `experience`,
  `skills`, `languages`). `eligibility` n'y figure **pas** : c'est une
  déclaration de la personne, aucune extraction ne doit la remplir.
* **`merge_profile_field()`** : fusion d'une valeur validée avec ce que la
  personne a saisi à la main. Rien n'est écrasé, une valeur déjà présente
  n'est pas écrite deux fois.

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
* `build_source_pages()` / `page_for_offset()` : attribution de page. Chaque
  page est **localisée dans le texte** plutôt que déduite de sa longueur :
  un document dont les fins de ligne sont normalisées (CRLF) ou dont la
  source a été tronquée garde la bonne page.

### 5.3 `career/service.py` — persistence, règles et projection

* Stockage : `career_settings` clé `candidate_profile_v1` (une valeur JSON).
  **Aucune migration de schéma** : `SCHEMA_VERSION` reste à 8, la base d'un
  utilisateur existant n'est pas touchée, et `reset_personal_data()` efface
  déjà cette table.
* Le document source est stocké sous `career_data/documents/profile_candidat_<uuid><ext>`
  en `0600`. Le nom commence par `profile_` pour que le nettoyage « Supprimer
  mes données Career » l'emporte avec les autres sources privées.
* **`_candidate_profile_overlay()`** : pose les faits validés sur le profil
  utilisé pour la candidature. Un champ couvert par au moins un fait validé
  vient des faits validés seuls ; un champ qu'aucun fait validé ne couvre
  garde la valeur saisie à la main. `get_matching_profile()` expose ce profil
  (c'est le contrat pour SK-11 et pour les variantes de CV).
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
  (page, citation, offsets), champ de correction, et les décisions permises ;
* export et suppression du profil.

Le script est autonome : il ne dépend d'aucun autre fichier JS, n'utilise
que `textContent` (aucun `innerHTML`, donc aucune injection) et n'envoie
aucune décision qu'après un clic explicite.

---

## 6. Audit adversariale : cinq défauts réels corrigés

L'héritage repris (lot D) était propre mais incomplet. La relecture a
trouvé cinq défauts **réels**, tous reproduits par un test qui échoue sur le
code d'origine :

| # | Défaut | Effet | Correction | Test |
|---|--------|-------|------------|------|
| 1 | **Le critère 5 n'était pas câblé** : les faits validés n'alimentaient ni le brouillon de candidature ni le matching. La règle était vraie par construction (les faits n'atteignaient rien) mais vide : même un fait approuvé ne justifiait rien. | La fonctionnalité ne servait à rien en pratique, et SK-11 n'avait aucun contrat réel à consommer. | `active_profile_fields()` + `_candidate_profile_overlay()` + `get_matching_profile()`, appliqué au contexte de candidature et aux variantes de CV. | 8 tests |
| 2 | **Provenance incohérente sur un passage long** : la citation était tronquée avec « … » alors que les offsets continuaient de désigner le passage entier — les offsets pointaient *past* la citation. | La preuve affichée n'était pas celle que les offsets désignaient : le critère 2 n'était pas tenu au sens strict. | `_bounded_span()` : le passage est coupé **avec** ses offsets ; la citation est exactement `text[start:end]` normalisé, sans points de suspension. | `test_the_quote_is_exactly_the_quoted_passage`, `test_every_quote_describes_its_own_offsets` |
| 3 | **Page fausse sur un document CRLF** : les pages étaient déduites de leur longueur, alors que la normalisation des fins de ligne raccourcit le texte → dérive des offsets → un fait de la page 2 était attribué à la page 1. | La provenance de page était fausse sur tout document Windows ou tout `.txt` à fins de ligne CRLF. | `build_source_pages()` localise chaque page **dans** le texte ; une page absente (source tronquée) ne reçoit aucune span plutôt qu'une span fausse. | `test_the_page_of_a_fact_survives_normalised_line_endings`, `test_a_truncated_source_does_not_get_a_wrong_page` |
| 4 | **L'interface offrait des transitions refusées** : « Approuver » était proposé sur un fait déjà approuvé (toujours un 400), et « Mettre de côté » manquait sur un fait rejeté. | Un clic sur un bouton visible échouait toujours. | Table des transitions dans le JS, mirroring du modèle, vérifiée par un test Node qui compare les deux tables. | `test_the_ui_offers_exactly_the_transitions_the_model_allows` |
| 5 | **Une approbation sans date pouvait être enregistrée** : `decide_fact()` acceptait `decided_at=""` et produisait un fait marqué approuvé mais inutilisable — un état à moitié enregistré. | Le verrou d'approbation humaine reposait sur le `decided_at` mais la porte le laissait passer sans date. | `decide_fact()` refuse une décision validée sans date ; `validate_profile()` reste le filet de sécurité pour un profil chargé depuis le disque. | `test_a_validated_decision_without_a_date_is_refused` |

Trois apports des lots parallèles ont été **conservés** parce qu'ils
complétaient le lot D :

* le **plafond de taille de corps** appliqué au nouvel upload
  (`come_ai_web.py`) — sinon un document trop gros n'était refusé qu'au
  moment du parcours, pas avant ;
* les **textes de page de l'OCR** (`career/ocr.py`, `career/vision_ocr.m`) —
  un fait lu par OCR garde ainsi sa page ;
* la **survie des faits au redémarrage** de l'application, désormais prouvée
  par un test (`test_the_facts_survive_a_restart_of_the_local_service`).

---

## 7. Comparatif honnête avec la livraison concurrente (lot C audité)

Pendant cette mission, un autre agent a repris la branche désignée par le
registre (`agent/spec-sk10-candidate-profile`, lot C) et l'a auditée à son tour
(6 défauts corrigés, 58 tests, essai réel contre un serveur uvicorn). Les
deux livraisons sont **complètes et vertes** ; elles ne sont pas fusionnables
(architectures incompatibles sur les mêmes fichiers). Comparatif vérifié
ligne à ligne :

| Point | Lot C audité (`agent/spec-sk10-candidate-profile`) | Cette branche |
|-------|--------------------------------------------------|---------------|
| Anti-approbation automatique | acteur `user` obligatoire + `decided_at` | `decided_at` obligatoire **et** refus d'enregistrer une approbation sans date |
| Provenance | citation verbatim, offsets sur le texte brut (D4) | citation bornée, offsets bornés **avec** elle |
| Page | confiance explicite `exact` / `estimated` (D5) | pages localisées dans le texte (robuste à toute normalisation) |
| Critère 5 | **apply explicite** : le fait validé est écrit dans le profil plat, la ligne exacte est tracée, la décision le retire si besoin (schéma v10) | **projection recalculée** : le profil de candidature est calculé à chaque usage, rien n'est écrit dans le profil plat |
| Saisie manuelle | préservée (l'apply fusionne) | préservée (la projection fusionne) |
| Risque de ligne périmée | possible par construction : d'où leur correctif D1 et les colonnes `applied_field` / `applied_line` | **impossible** : rien n'est écrit, la projection est recalculée |
| Migration de schéma | v9 → v10 (additive, testée) | **aucune** (une valeur JSON dans `career_settings`) |
| Contrat SK-11 | le profil plat après apply | `get_matching_profile()` + `/evidence` + `/active` |
| Tests SK-10 / suite complète | 58 / 1481 | **66 / 1490** |

**Recommandation : intégrer le lot C audité.** Il est déjà sur la branche
désignée par le registre, il a été validé par un essai réel, et son mécanisme
d'apply est **visible** : la personne voit dans « Mon profil » ce qui a été
appliqué, ce que la projection automatique de cette branche ne montre pas.

Cette branche-ci reste utile comme **référence** pour trois choix qui
pourraient être repris : la projection recalculée (aucune ligne périmée
possible), l'absence de migration de schéma, et le contrat SK-11 explicite
(`/evidence` qui refuse tant que rien n'est validé).

---

## 8. Vérifications

```bash
.venv/bin/python -m pytest -q tests/test_candidate_profile.py   # 66 passed
.venv/bin/python -m pytest -q                                    # 1490 passed, 1 skipped
.venv/bin/python -m ruff check .                                 # All checks passed!
git diff --check                                                 # propre
./checklist_codex.sh                                             # TOUT VERT
```

Les étapes mémoire / studio-coach du contrôleur sont ignorées quand le
worktree correspondant n'existe pas (état normal d'un worktree de mission).

---

## 9. Limites connues et suite SK-11

1. **Ce que SK-11 doit consommer** : `get_matching_profile()` (profil
   projeté), `get_active_candidate_profile()` et
   `require_candidate_profile_evidence()` — **jamais** `facts`, qui contient
   les propositions non validées. Le contrat HTTP est
   `GET /api/career/candidate-profile/evidence` (400 tant que rien n'est
   validé) et `GET /api/career/candidate-profile/active`.
2. **Le profil plat reste la source du formulaire « Mon profil »** : il est
   saisi à la main, donc déjà validé par son auteur. `get_profile()` n'est pas
   modifié ; c'est `get_matching_profile()` qui porte la projection. La
   projection est donc visible dans le panneau de relecture (les faits
   utilisables y sont listés) mais pas dans le formulaire du profil : c'est
   le principal écart de confort de cette branche (le lot C audité applique
   les faits **dans** le profil, donc ils y sont visibles).
3. **Réimportation** : l'export existe, la réimportation n'est pas
   implémentée. Le format d'export est documenté et stable
   (`profile` / `counts` / `usable` / `exported_at`).
4. **Heuristiques de lecture** : une mise en page très atypique (colonnes,
   tableaux PDF) peut produire des propositions mal segmentées. C'est
   précisément le rôle de la relecture champ par champ : la personne corrige
   ou rejette. La régression des propositions est couverte par les offsets
   exacts, pas par un score.
5. **Aucun OCR réel dans les tests** : le moteur macOS Vision n'est pas
   exécutable de façon fiable en CI ; le test injecte un faux OCR et vérifie
   le contrat (propositions uniquement, jamais approuvées, page conservée).

---

## 10. Points de relecture recommandés

1. `career/candidate_profile.py` — la table des transitions, la règle
   `decided_at` et `active_profile_fields()`.
2. `career/profile_builder.py` — `_bounded_span()`, `build_source_pages()`,
   `_heading_kind()`, `_group_experience_entries()`.
3. `career/service.py` — `_candidate_profile_overlay()`,
   `_application_context()`, `require_candidate_profile_evidence()`.
4. `career/router.py` — les 8 endpoints et `_store_candidate_profile_document()`.
5. `career/cv_quality/parser.py` — le refactor de `_extract_pdf()` :
   **le texte produit est inchangé** (pages vides ignorées, jointure `"\n\n"`),
   seul `extract_pages_from_bytes()` est ajouté.
