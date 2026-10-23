# SPEC-008 — Centre de preuves unifié (source de vérité des preuves du profil)

Date : 22 octobre 2026
Branche : `worker/cvboost-38-1792642135` (base `f5b22f2`)
Mission : CVBOOST-38 — SPEC-008 « Evidence Center Unifié »
Aucune dépendance ajoutée, aucun schéma de la base Career principale modifié, aucune donnée réelle, aucun appel réseau.

## 1. Le problème que la mission règle

La provenance du candidat existait déjà, mais **éparpillée** :

| Où | Ce qui existe aujourd'hui |
|---|---|
| `career/offer_requirements/` | exigence ↔ champ source ↔ citation (`locator`, `confidence` 0-1) |
| `career/offer_qualification.py` | `FactEvidence(value, source, quote)` par fait d'offre |
| `career/application_studio.py` | `provenance_map` : `{source, quote, offset}` par bloc de kit |
| `career/cv_fit.py` | `EvidenceCitation` par exigence non couverte |
| `career/profile_import.py` | indices de provenance tronqués (360 caractères, 3 par champ) |
| SK-03 / SK-10 (branches non fusionnées) | faits candidats et verdicts d'adéquation, chacun avec leur propre vocabulaire |

Trois manques concrets :

1. **aucun endroit unique** — impossible de répondre à « cette compétence est-elle prouvée ? » ;
2. **aucune décision tracée** — une citation existe, mais rien ne dit si la personne l'a retenue ;
3. **aucun usage suivi** — on ne sait pas si une preuve a déjà servi dans un CV ou une lettre, ni si elle est périmée.

Le module livré est un **centre de preuves** : une source de vérité unique, locale, où chaque
affirmation du profil porte sa source, sa citation, son statut d'approbation, son usage et son
historique de fusion.

## 2. Ce qui a été construit

### 2.1 `career/evidence.py` — le cœur pur (1 056 lignes)

Module **sans effet de bord** : ni réseau, ni modèle, ni inférence. L'horloge est injectable
(`clock=`), donc les tests sont déterministes.

| Symbole | Rôle |
|---|---|
| `EvidenceItem` | le contrat public : `id`, `claim`, `source_document`, `source_location`, `quote`, `evidence_type`, `confidence`, `approved`, `created_at`, `updated_at`, `tags` + `attachments`, `usage`, `blocked`, `expires_at`, `merged_from`, `additional_sources` |
| `EvidenceUsage` | un usage horodaté (`target` ∈ `cv`/`letter`, `context`, `at`) |
| `EvidenceUsageStats` | compteurs globaux : `total_evidence`, `approved`, `used_in_cv`, `used_in_letters`, `expired`, `by_type`, `by_confidence` (+ `blocked`, `unapproved`, `claims`, `proven_claims`, `unproven_claims`, `attachments`) |
| `EvidenceCenter` | **une instance par profil** : CRUD, recherche, regroupement par affirmation, approbation, blocage, expiration, usage, fusion, couverture, statistiques, export |
| `evidence_from_candidate_fact()` | adaptateur **SK-10** : un fait candidat sérialisé → une preuve |
| `evidence_from_fit_verdict()` | adaptateur **SK-03** : un verdict `supported` → une preuve *non approuvée* |

Vocabulaire fermé et explicite :

- `evidence_type` ∈ `experience`, `education`, `skill`, `language`, `project`, `certification` ;
- `confidence` ∈ `direct`, `inferred`, `declared` ;
- `usage.target` ∈ `cv`, `letter`.

### 2.2 `career/evidence_store.py` — persistance locale (446 lignes)

Le module est « bête » : il écrit et relit des documents, il n'analyse rien.

- **base dédiée** : `career_data/evidence/evidence.sqlite3` (répertoire `0700`, fichier `0600`) ;
  la base Career principale **n'est pas migrée** — ajouter des preuves ne force aucune
  migration du schéma existant ni aucune sauvegarde de sécurité ;
- **mode WAL**, comme la base Career principale (un écrivain ne bloque pas les lecteurs) ;
- **tables** : `evidence_items` (index sur `claim_key`, `evidence_type`+`created_at`, `created_at`)
  et `evidence_merges` (historique de fusion : identifiant gardé, identifiants fusionnés,
  instantanés complets, horodatage) ;
- **colonnes JSON bornées** pour `tags`, `attachments`, `usage`, `additional_sources`,
  `merged_from` : des listes courtes et déterministes, pas un modèle relationnel ;
- **fusion atomique** : la preuve gardée, la suppression des preuves absorbées et l'écriture de
  l'historique se font dans **une seule transaction** — une provenance ne peut pas disparaître
  entre deux écritures ;
- **résilience** : un fichier illisible est mis de côté (`.corrupt-<horodatage>`) et le centre
  repart vide ; une erreur SQLite devient un message lisible, pas une erreur 500 ;
- **deux implémentations** de la même interface `EvidenceStore` : `SqliteEvidenceStore` (le service)
  et `InMemoryEvidenceStore` (tests des règles seules, sans fichier). Les deux appliquent les mêmes
  sémantiques de copie : une preuve stockée ne peut pas être modifiée sans passer par `save`.

### 2.3 `career/service.py` — 16 méthodes (additives)

| Méthode | Rôle |
|---|---|
| `evidence_center()` | l'instance unique du centre |
| `list_evidence(...)` | liste filtrée (recherche, type, confiance, approbation, blocage, expiration, usage) |
| `add_evidence(payload)` | création (identifiant `evidence_<12 hex>` généré) — **jamais approuvée d'emblée** |
| `get_evidence(id)` / `update_evidence(id, payload)` / `delete_evidence(id)` | CRUD (la suppression efface aussi les pièces jointes) |
| `mark_evidence_approved(id, approved)` | décision de la personne |
| `set_evidence_blocked(id, blocked)` | blocage de l'usage |
| `record_evidence_usage(id, target, context)` | usage CV / lettre |
| `attach_evidence_document(id, path, original_name)` | copie du document dans le répertoire privé |
| `merge_evidence(ids, keep_id)` | fusion de doublons |
| `evidence_stats()` | compteurs + **couverture des compétences déclarées au profil** |
| `export_evidence(format)` | export portable `json` **ou** `markdown` |
| `ingest_candidate_facts(facts)` | adaptateur SK-10 (import **idempotent**) |
| `ingest_fit_verdicts(verdicts)` | adaptateur SK-03 (import **idempotent**) |
| `evidence_upload_temp_path()` | emplacement opaque et privé pour un téléversement |

Le centre est aussi branché sur deux flux existants :

- `export_personal_data()` ajoute le bloc `evidence` à l'export de confidentialité ;
- `reset_personal_data()` efface les preuves, les pièces jointes, les téléversements et **les
  exports de preuves** (`preuves_candidat_*`), puis recrée un centre vide ;
- `local_capabilities()` expose `evidence_center` (local, sans approbation automatique, sans réseau).

### 2.4 `career/router.py` — 11 endpoints

```
GET    /api/career/evidence                      liste + filtres
POST   /api/career/evidence                      création (201)
GET    /api/career/evidence/stats                compteurs + couverture du profil
GET    /api/career/evidence/export               export portable (json | markdown)
POST   /api/career/evidence/merge                fusion {ids, keep_id}
GET    /api/career/evidence/{evidence_id}        détail
PATCH  /api/career/evidence/{evidence_id}        modification
DELETE /api/career/evidence/{evidence_id}        suppression
POST   /api/career/evidence/{evidence_id}/approve décision d'approbation
POST   /api/career/evidence/{evidence_id}/block   blocage de l'usage
POST   /api/career/evidence/{evidence_id}/usage   usage CV / lettre
POST   /api/career/evidence/{evidence_id}/attach  pièce jointe (téléversement)
```

Les routes littérales (`/stats`, `/export`, `/merge`) sont déclarées **avant** les routes
paramétrées : `/evidence/stats` ne peut jamais être capté par `/evidence/{id}`.
Les erreurs suivent le contrat du dépôt : `UserFacingError` → HTTP 400 via le gestionnaire
global ; seule la validation d'un filtre tri-état renvoie un 422 explicite.

> **Préfixe.** La mission écrit `/evidence` ; le dépôt expose toutes ses routes Career sous
> `/api/career/…`. La convention du dépôt l'emporte : les chemins sont `/api/career/evidence…`.
> Les neuf endpoints demandés existent, plus `/approve`, `/block` et `/usage`, qui portent les
> décisions et le suivi d'usage.

> **Approbation.** Les charges utiles de création et de modification **n'acceptent plus**
> `approved` : la seule voie vers une preuve approuvée est la décision explicite
> (`POST /evidence/{id}/approve`), ou l'import d'un fait que la personne avait déjà approuvé
> ailleurs (SK-10). Une API ne peut donc pas s'auto-approuver.

### 2.5 `career_static/js/evidence-center.js` — l'interface (416 lignes)

Onglet **Preuves** (`#tab-evidence` → `#view-evidence`), sans build step, en JavaScript natif :

- **cartes** : compétences prouvées, non prouvées, expirées, utilisées ;
- **filtres** : recherche, type, confiance, approbation, usage, blocage ;
- **grille** : une ligne par preuve (affirmation, type, confiance, statut, source) avec une case
  de sélection pour la fusion — plusieurs preuves peuvent être cochées ;
- **détail** : citation verbatim, source et emplacement, usage, pièces jointes, historique de fusion ;
- **actions** : ✅ Approuver | 📎 Attacher | 🔗 Fusionner | 🗑️ Supprimer | 🚫 Bloquer l'usage |
  « marquer utilisée dans un CV / dans une lettre » ;
- **formulaire** de création, avec la règle visible : une preuve sans source ni citation est refusée ;
- **recherche saisie au clavier** : un délai de 200 ms et un jeton de séquence — une réponse plus
  ancienne ne peut jamais remplacer une réponse plus récente.

`career_static/career.js` enregistre la vue (`careerViews`) et son chargeur ; `career_static/index.html`
ajoute l'onglet, la section et le `<script>` ; `career_static/career.css` ajoute 30 lignes de style.

### 2.6 `come_ai_web.py` — plafond de téléversement

La route de pièce jointe est protégée par `UploadBodyLimitMiddleware` (10 Mo), comme
l'import de profil : le corps est refusé **avant** d'être analysé et mis en mémoire temporaire.

## 3. Les règles qui ne sont pas des conventions

1. **Rien n'est approuvé automatiquement.** `approved` ne passe à `true` que par une décision
   explicite de la personne : `POST /evidence/{id}/approve`, ou l'import d'un fait SK-10 qu'elle
   avait déjà approuvé. `is_proven()` exige en plus `blocked = false` et une preuve non expirée.
2. **Une absence n'est jamais un échec.** `get_claim_coverage()` renvoie `proven: false` pour
   une affirmation sans preuve ; elle ne renvoie jamais « faux ». C'est la règle SK-03
   (« une donnée manquante n'est pas une exigence non satisfaite ») appliquée au centre.
3. **Une fusion ne perd jamais une provenance.** La preuve gardée absorbe les citations, les
   étiquettes, les pièces jointes et les usages des preuves fusionnées (`additional_sources`,
   `merged_from`), et l'historique `evidence_merges` conserve l'instantané complet des preuves
   absorbées. L'approbation **ne change pas de citation** : une citation absorbée garde son
   propre drapeau `approved` ; l'affirmation reste prouvée parce qu'une source approuvée la
   couvre, et le détail dit laquelle. Le blocage et l'expiration les plus restrictifs sont
   conservés ; la confiance du gardien n'est jamais gonflée.
4. **Aucun chemin d'origine n'est persisté.** Un document attaché est **copié** dans
   `career_data/evidence/attachments/` sous un nom opaque (`0600` posé **avant** l'écriture) ;
   la base ne garde que le nom de fichier, l'empreinte SHA-256 et la taille. Un test vérifie
   qu'aucun chemin du disque ne figure dans l'export.
5. **Supprimer une preuve, c'est tout supprimer.** La ligne, les pièces jointes copiées et les
   exports de preuves disparaissent avec la preuve ; une suppression explicite du Career efface
   l'ensemble, exports compris.
6. **Une faute n'est jamais une favorable décision.** Une date d'expiration illisible est
   refusée à l'écriture (`AAAA-MM-JJ`) : elle ne peut pas signifier « n'expire jamais ».
7. **Un changement refusé ne laisse rien derrière lui.** La modification est préparée sur une
   copie, validée, puis seulement écrite.
8. **Un import rejoué ne pollue pas le centre.** Les adaptateurs SK-03 et SK-10 dérivent un
   identifiant déterministe : réimporter la même source met à jour la même preuve. Un import
   ne révoque jamais une approbation.
9. **La recherche est déterministe.** Trois règles explicites, dans l'ordre : sous-chaîne
   entière, puis préfixe de mot, puis cinq premières lettres communes (« finance » trouve
   « financière », le français insère des voyelles). Aucun score, aucun classement « pertinent » :
   la liste est la même sur chaque machine.
10. **Rien ne quitte la machine.** Aucun appel réseau dans le module, le service, l'API ou
    l'interface ; la fixture de test neutralise les sockets pendant toute la suite.

## 4. Ce qui a été vérifié

```
tests/test_evidence.py → 92 tests (modèle, validation, recherche, couverture, décision,
                         blocage, expiration, usage, pièces jointes, fusion, statistiques,
                         export, persistance SQLite, confidentialité, API, interface,
                         adaptateurs SK-03/SK-10, durcissement, fixture synthétique)
```

Points notables :

- `test_attach_document_never_persists_the_original_path` — le chemin d'origine est absent de
  l'export ;
- `test_deleting_a_proof_erases_its_attached_document` — la copie disparaît avec la preuve ;
- `test_merge_keeps_the_snapshots_of_the_merged_proofs` — la citation de la preuve absorbée
  reste dans l'historique, et l'historique survit à la réouverture de la base ;
- `test_a_refused_update_leaves_the_stored_proof_untouched` — une modification refusée ne
  corrompt pas la preuve ;
- `test_an_invalid_expiry_is_refused` — une date illisible est refusée ;
- `test_the_import_of_a_candidate_fact_is_idempotent` — réimporter ne crée pas de doublon et ne
  révoque pas une approbation ;
- `test_a_damaged_evidence_database_does_not_break_the_career_space` — un fichier illisible est
  mis de côté, l'espace Career démarre quand même ;
- `test_the_service_keeps_the_evidence_directory_private` — répertoire `0700`, fichier `0600` ;
- `test_service_keeps_the_evidence_between_two_runs` — les preuves survivent à la fermeture ;
- `test_reset_personal_data_removes_the_evidence` — une suppression explicite efface tout ;
- `test_the_upload_body_is_capped_before_it_is_parsed` — le plafond s'applique avant l'analyse ;
- `test_the_career_page_links_the_evidence_center` — garde-fou d'interface (onglet, vue, `<script>`).

## 5. Limites assumées et suite proposée

- **SK-03 et SK-10 ne sont pas dans cette base.** Le centre expose des adaptateurs qui lisent
  les *contrats sérialisés* de ces modules (`kind`/`label`/`value`/`status`/`evidence` d'un côté,
  `verdict`/`profile_evidence`/`confidence` de l'autre) : l'intégration se fait quand ces
  branches seront fusionnées, sans réécriture du centre.
- **Le suivi d'usage est déclaratif.** `record_usage` enregistre un usage constaté ; le rattachement
  automatique aux CV et lettres générés par `application_studio.py` reste à câbler côté studio
  (il demande le numéro de dossier, que le studio ne transmet pas encore).
- **Pas d'index FTS5.** La recherche reste en Python sur un jeu personnel de quelques centaines
  de preuves ; le passage à FTS5 n'apporterait rien à cette échelle et ajouterait une
  dépendance au schéma.
- **Une affirmation = une preuve.** Une preuve ne peut pas couvrir deux affirmations : la
  fusion est le chemin explicite pour rapprocher deux doublons.
- **L'export écrit deux fichiers** (JSON et document Markdown) comme le demande la mission ;
  seul le fichier demandé est renvoyé, l'autre reste dans `career_data/exports/` et disparaît
  avec la suppression du Career.

## 6. Fichiers livrés

| Fichier | Statut |
|---|---|
| `career/evidence.py` | nouveau (1 056 lignes) |
| `career/evidence_store.py` | nouveau (446 lignes) |
| `career/service.py` | modifié (+243 lignes) |
| `career/router.py` | modifié (+205 lignes) |
| `come_ai_web.py` | modifié (+7 lignes) |
| `career_static/js/evidence-center.js` | nouveau (416 lignes) |
| `career_static/index.html` | modifié (+127 lignes) |
| `career_static/career.css` | modifié (+30 lignes) |
| `career_static/career.js` | modifié (+4/-2 lignes) |
| `tests/test_evidence.py` | nouveau (92 tests) |
| `tests/fixtures/evidence/synthetic_evidence.json` | nouveau (8 preuves synthétiques) |
