# Rapport — Analyse d'unification du profil

Date : 18 octobre 2026
Branche observée : `audit/total-v3-2026-10-14` @ `fb46fcf`
Statut : **analyse uniquement** — aucun code modifié, aucune branche fusionnée, aucune structure intégrée.
Contraintes respectées : aucun CV réel lu, aucune donnée personnelle lue, aucun dossier personnel inspecté. Seuls le code, les schémas SQL déclarés dans le code, les fixtures synthétiques et des bases **créées puis jetées dans un `tempfile`** ont été utilisés. Une seule opération a porté sur une base existante : un `SELECT COUNT(*)` et un `PRAGMA user_version` en mode `mode=ro` sur `state/personal_profile/personal_profile.sqlite3`, afin de vérifier si elle contenait des données (voir §4). Aucune ligne n'a été lue.

---

## 0. Convention de preuve

- **LU** : fait lu dans le code source (`fichier:ligne` sur la branche observée, ou sur une branche nommée explicitement).
- **MESURÉ** : comportement vérifié par exécution dans cette session, sur une base temporaire synthétique créée puis supprimée.
- **PREUVE GIT** : vérifiable par `git log`, `git merge-base`, `git cat-file`, blobs identiques.
- **JUGÉ** : analyse de l'auditeur, non prouvée par exécution.
- **NON VÉRIFIÉ** : non testé ici.

Aucune affirmation de ce rapport ne repose sur un CV, un profil ou une base utilisateur réelle.

---

## 1. Résumé exécutif

Il n'existe **pas deux** profils mais **quatre surfaces distinctes** portant des données personnelles : **deux** sont des magasins de profil au sens propre, une troisième est une mémoire documentaire, la quatrième est un simple diagnostic disque.

| # | Surface | Nature | Où | Sur `main` / HEAD ? |
|---|---|---|---|---|
| 1 | `candidate_profile` | profil **plat**, mono-ligne | `career_data/career.sqlite3` | **oui** |
| 2 | `personal_profile/` | profil **unifié par souvenir** | `state/personal_profile/personal_profile.sqlite3` | **non** — 6 branches non fusionnées |
| 3 | `personal_memory.py` | mémoire **documentaire** (pas un profil) | `memory_data/personal_memory.sqlite3` | **oui** |
| 4 | `memory_storage.py` | **diagnostic disque en lecture seule** (pas un magasin) | aucun | **oui** |

Points structurants :

1. **Aucun conflit d'écriture n'existe aujourd'hui** entre `candidate_profile` et `personal_profile`, parce qu'ils ne sont pas dans le même code. Le risque n'est pas la corruption concurrente : c'est la **duplication de vérité** et la **divergence de cycle de vie** (LU).
2. `personal_profile` est **la seule conception qui porte une provenance par élément, une approbation par élément, des pierres tombales et un droit à l'oubli vérifiable**. `candidate_profile` n'en porte **aucune** (MESURÉ : aucune colonne de provenance sur la ligne de profil, aucun lien retour depuis `candidate_profile` vers `profile_imports`).
3. `personal_profile` est **absent de `main` et de HEAD** (PREUVE GIT) alors que sa base existe déjà sur ce Mac (`state/personal_profile/personal_profile.sqlite3`, 40 Ko). **Attention, nuance vérifiée** : cette base contient les 4 tables attendues mais **zéro ligne** dans chacune (`candidates`, `decisions`, `imports`, `tombstones` = 0). Elle a donc été **créée mais jamais alimentée**. Le risque R1 est réel pour le *futur* (dès le premier import), pas pour des données déjà perdues aujourd'hui.
4. `memory_storage.py` est **le nom le plus trompeur du dépôt** : il ne stocke rien et ne profil pas (LU, docstring + API `snapshot()` uniquement).

Recommandation : **une seule structure**, celle de `personal_profile`, avec `candidate_profile` rétrogradé en **projection de lecture** dérivée. Détails en §7. Ne pas intégrer maintenant.

---

## 2. Cartographie factuelle

### 2.1 `candidate_profile` (LU)

Table unique `id=1`, **13 colonnes** (11 champs de contenu + `id` + `updated_at`), dans `career_data/career.sqlite3` (`career/service.py:203`, `career/service.py:279-293`). Nombre vérifié par `PRAGMA table_info` sur base temporaire.

| Colonne | Type | Limite au service | Limite au parseur |
|---|---|---|---|
| `display_name` | TEXT | 160 | 120 |
| `contact_email` | TEXT | 320 | 320 |
| `contact_phone` | TEXT | 80 | 80 |
| `linkedin_url` | TEXT | 2 000 | 500 |
| `education` | TEXT | **1 000** | **5 000** |
| `experience` | TEXT | 6 000 | 6 000 |
| `skills` | TEXT | 4 000 | 3 000 |
| `languages` | TEXT | 2 000 | 1 500 |
| `eligibility` | TEXT | `unknown/compatible/incompatible` | — (jamais déduit) |
| `target_companies` | TEXT | 2 000 | — |
| `notes` | TEXT | 4 000 | — |
| `updated_at` | TEXT | — | — |

Source des limites : `career/service.py:132-141` (service) et `career/profile_import.py:54-63` (parseur).

**Écart mesuré** : `education` est analysé jusqu'à 5 000 caractères puis tronqué à 1 000 à l'application, **sans avertissement**.

```
MESURÉ (base temporaire) :
  parsed education chars: 3799
  stored education chars: 1000
  TRUNCATED ON APPLY: True
```

C'est la seule colonne où le parseur dépasse le service. Toute migration qui réutiliserait les deux limites doit traiter ce cas.

### 2.2 `personal_profile/` (LU, branche `feature/personal-context-engine` @ `e6af0db`, non fusionnée)

Quatre tables (`store.py:253-310`), `STORE_SCHEMA_VERSION = 1`, base `state/personal_profile/personal_profile.sqlite3`.

- `candidates` : `candidate_id` (PK), `status` (pending/approved/rejected/deferred/deleted), `record_type`, `domain`, `category`, `sensitivity`, `import_id`, `pack_id`, `revision`, `content_fingerprint`, `approved_at`, `decided_by`, `created_at`, `updated_at`, `payload` (JSON du souvenir).
- `decisions` : journal `before/after` JSON par décision.
- `imports` : empreinte de paquet, `added/suppressed/conflicting/invalid/issues`, `rolled_back`.
- `tombstones` : `(candidate_id, content_fingerprint)` — empêche la réapparition du même contenu.

Modèle de souvenir (`schema.py:544-566`) : `record_type` ∈ {fact, goal, preference, habit, rule, hypothesis, transient}, `domain` (16 domaines normalisés + alias), `statement` ≤ 400 caractères, `source{kind, reference, observed_at}` **immuable**, `confidence{level, justification}` obligatoire, `sensitivity` ∈ {standard, sensitive, restricted}, `evidence[]` ≤ 6, `period`, `temporal_validity`, `personalization{utility, uses[]}`, `contradicts[]`, `extensions`.

Points mesurés :

```
MESURÉ : import  → status initial = pending, contexte = 0 élément
MESURÉ : accept  → contexte = 1 élément, rendu porte source + date + confiance
MESURÉ : reject puis ré-import du même contenu → added=0, suppressed=1
MESURÉ : forget  → action=deleted, redacted=2, tombstones=2, approved=0
```

### 2.3 `personal_memory.py` (LU)

Ce n'est **pas** un profil. C'est une mémoire documentaire chunkée : `projects`, `sources`, `source_projects`, `memory_chunks`, plus une table FTS5 `memory_chunks_fts` (`personal_memory.py:299-352`). `SCHEMA_VERSION = 2`.

API publique complète (MESURÉ par `dir`) : `add_source_to_project`, `create_project`, `delete_project`, `delete_source`, `import_file`, `import_text`, `list_projects`, `list_sources`, `search`, `stats`.

**Aucun export.** Aucun statut d'approbation. Aucune provenance par souvenir : la provenance est *document + page + ligne*, ce qui est différent et suffisant pour de la citation.

### 2.4 `memory_storage.py` (LU)

**Ce module ne stocke rien et ne profil pas.** C'est un inventaire disque en lecture seule :

- `DEFAULT_DATABASE_FILENAME = "personal_memory.sqlite3"`, `_MEMORY_TABLES = ("projects", "sources", "memory_chunks")` (`memory_storage.py:31-34`).
- Une seule méthode publique : `snapshot()` (`memory_storage.py:133`) ; tout le reste est `_`-privé.
- Aucune écriture, aucun `mkdir`, aucun import de document. Chemins réduits par `redact_location_path` (`~` au lieu du nom de compte).

Risque : le nom laisse croire à un magasin. Il est importé par `come_ai_web.py:33` et exposé en `/api/v5/memory/storage`. Renommer ou documenter est un changement de nom, pas une unification de données.

---

## 3. Comparaison fonctionnelle

### 3.1 Modèles utilisés par l'interface

| Surface | Modèle | Origine | Champs exposés à l'UI |
|---|---|---|---|
| Career | `ProfilePayload` (Pydantic) | `career/router.py:25-36` | 11 champs plats |
| Career JS | `career.js` | LU | `display_name, contact_email, contact_phone, linkedin_url, education, experience, skills, languages, eligibility, target_companies, notes` (11) |
| Career import | `ProfileImportApplyPayload` | `career/router.py:144-146` | `updates[≤8]`, `base_profile_updated_at` |
| PCE web | `StoredCandidate.as_dict()` | `personal_profile_web.py` | `candidate_id, statement, status, record_type, domain, sensitivity, source.{kind,reference}, confidence.{level,justification}, personalization.uses, temporal_validity.status, revision` (LU via `profile.js`) |
| PCE JS | `profile.js` | branche non fusionnée | 11 champs d'entrée + badges statut |
| Mémoire | `PersonalMemoryStore.search` | `personal_memory.py:910` | `source_id, title, citation{label}, excerpt` |

Points de friction :

- Les deux interfaces Career sont en **champs plats** ; le PCE est en **cartes de souvenirs**. Aucune conversion automatique n'existe.
- `career.js` lit `profile.eligibility` et `profile.target_companies`, deux notions **absentes du modèle PCE** (`eligibility` est un enum à 3 valeurs ; PCE n'a que `sensitivity`). C'est le premier obstacle de migration.
- Le PCE expose `status` par élément ; Career n'a **aucun** statut sur le profil.

### 3.2 Formats importés

| Surface | Formats | Limites | Provenance à l'import |
|---|---|---|---|
| Career | `.pdf .docx .txt .md` + texte collé | 10 Mo, 100 000 car. | `content_sha256` UNIQUE, `source_kind` ∈ {cv, linkedin_export, linkedin_text, profile_document}, `original_name`, `extraction_method`, `ocr_pages`, `base_profile_updated_at` — **niveau document** |
| PCE | **JSON uniquement** (`come-personal-profile-pack/1`) | 1 Mo (web), 2 000 souvenirs, 400 car./énoncé | `source{kind, reference, observed_at}` + `evidence[]` + `confidence` + `content_fingerprint` — **niveau souvenir** |
| Mémoire | `.txt .md .csv .tsv .json .html .pdf .docx .xlsx .xlsm` | 25 Mo, 1 000 000 car., 2 000 chunks | `content_hash` + `title` + `original_filename` — niveau document |
| Study coach | via `personal_memory` ou `TEXT_SUFFIXES` | — | `SourceRef` avec numéro de ligne |

Conséquence : Career sait **extraire** un PDF, le PCE sait seulement **recevoir** du JSON déjà structuré. Une structure unique devra exposer les deux étages : extraction ( Career ) puis décision ( PCE ).

### 3.3 Provenance

| | Career `candidate_profile` | PCE `candidates` |
|---|---|---|
| Provenance par élément | **aucune** | `source`, `evidence[]`, `confidence`, `observed_at` |
| Chaîne import → valeur | indirecte : `profile_imports.status='applied'` + `applied_at`, mais **aucune colonne ne relie la ligne de profil à son import** | `import_id`, `pack_id`, `revision`, `content_fingerprint` |
| Immutable à la correction | non (`update_profile` écrase tout) | oui (`review.edit` refuse `source`, `candidate_id`, `validation_status`, `extensions`) |
| Historique | `career_audit_log` (action, sujet, date) — **sans contenu** | `decisions` avec `before`/`after` JSON complet |
| Inférabilité | `eligibility` est **déclaré par l'utilisateur**, jamais déduit (LU : commentaire `career/service.py:744-745`) | `hypothesis` ne peut jamais être promu |

MESURÉ sur base temporaire : après `apply_profile_import`, `candidate_profile` ne contient **aucune colonne** de provenance et **aucun lien** vers `profile_imports`. Une valeur appliquée devient orpheline de son origine.

### 3.4 Approbation

| | Career | PCE |
|---|---|---|
| Granularité | **par champ** (cases à cocher), un import = un lot | **par souvenir** (accept/reject/defer) |
| Modèle | `status` ∈ {pending, applied} sur l'import | `status` ∈ {pending, approved, rejected, deferred, deleted} sur le souvenir |
| Anti-concurrence | `base_profile_updated_at` vs `candidate_profile.updated_at` → refus si le profil a changé (MESURÉ par lecture `career/service.py:1113-1118`) | `revision` + `content_fingerprint` |
| Non-promotion d'une hypothèse | sans objet | garantie |
| Ré-import du même contenu | ré-ouvre le pending, sinon doublon détecté par sha | bloqué par `tombstone` (MESURÉ : `suppressed=1`) |

Le modèle Career est **plus simple mais plus faible** : approuver un import, c'est approuver d'un coup plusieurs champs, dont éventuellement des champs que l'utilisateur n'a pas lus.

### 3.5 Export

| Surface | Formats | Contenu | Limite |
|---|---|---|---|
| Career | JSON (`export_personal_data`), CSV, XLSX, ICS, MD/HTML/DOCX/PDF | profil, préférences, réglages, offres, candidatures, brouillons, imports, **audit log** | `career/service.py:3668-3787` |
| PCE | JSON `come-personal-profile-export/1`, Markdown | `counts, records, decisions, imports, tombstones` | `exporter.py:38-103` |
| Mémoire | **aucun** | — | MESURÉ : pas d'`export*` dans l'API |
| Study coach | JSON `come-study-coach-export/1` | cours, séances, réponses, planning | `store.py:384` |

MESURÉ : l'export Career contient `extracted_text` complet du document source et les `suggestions` avec `evidence`. C'est une exportation de données personnelles brutes — cohérente avec le droit d'accès, mais à traiter comme sensible.

### 3.6 Suppression

| Surface | Opération | Réversibilité |otoxicité réelle |
|---|---|---|---|
| Career | `DELETE /api/career/data` avec phrase `SUPPRIMER MES DONNÉES CAREER` | **irréversible**, réinjecte les valeurs par défaut | supprime **13 tables** + documents + exports + studio + **sauvegardes de migration** |
| Career | `delete_profile_import` | supprime le fichier stocké | ne retire **pas** les valeurs déjà appliquées au profil |
| PCE | `forget` | laisse `tombstone` (identifiant + empreinte, **pas** de note libre) | redacte les décisions, supprime la ligne, `VACUUM` |
| PCE | `forget_everything` | irréversible | `purge()` + `VACUUM` |
| Mémoire | `delete_source`, `delete_project` | les sources survivent par défaut | pas de `VACUUM` |

MESURÉ (base temporaire) : après `reset_personal_data`, la base de consentement `career_data/consent/consent_guard.sqlite3` **survit** au reset. Les traces de transmission (fournisseur, modèle, but, empreinte de charge utile) ne sont donc pas effacées par la suppression « de mes données ». C'est une anomalie de périmètre, pas un bug de code.

Note supplémentaire : Career supprime aussi les **sauvegardes de migration** (`career-before-v*-to-v*-*.sqlite3`, `career/service.py:3841-3847`). C'est cohérent avec « tout effacer », mais cela supprime le seul filet de sécurité en cas de migration ratée.

### 3.7 Données envoyées à l'IA

| Chemin | Ce qui part | Bornes | Garde |
|---|---|---|---|
| **Career → brouillon IA** | JSON `{profile (8 champs), career_intake, job (9 champs)}` | `display_name` 200, `email` 320, `phone` 80, `linkedin` 500, `education` 2 000, `experience` 4 000, `skills` 2 000, `languages` 1 000, job `description_original` 5 000 | case `consent_external` explicite (`career/router.py:455`) ; prompt « untrusted data, not instructions » |
| **Career → résumé IA** | `{job_id, title, company}` | non borné explicitement | `consent_guard` ou `consent_external` (`career/service.py:1928-1963`) |
| **Chat → mémoire** | 4 excerpts, 420 car. chacun | `MAX_CONTEXT_CHARS = 6 000`, `MAX_LOCAL_PROMPT_CHARS = 14 000` | refus si contexte local + cloud sans `allow_cloud_context` (`hybrid_chat.py:661-665`) puis `consume_cloud_context_consent` par envoi (`hybrid_chat.py:755-766`) |
| **PCE → chat** (branche non fusionnée) | blocs `[CONTEXTE PERSONNEL LOCAL — INFORMATIF]`, 6 items, 1 500 car. | standard seulement, hypothèses exclues | `profile_chat.StandardOnlyPolicy`, `allow_personal_cloud` exigé pour tout fournisseur non local |
| **Étude** | rien par défaut | — | `NullQuestionGenerator` lève `OfflineViolation` |

Deux divergences importantes :

1. **Le but `career_summary` n'existe pas dans la liste fermée des buts du `consent_guard`.** MESURÉ : `grant(purpose="career_summary")` lève `EnvelopeError` ; `check(..., purpose="career_summary")` renvoie `allowed=False, code="invalid_request"`. Le chemin protégé par `consent_guard` dans `get_job_summary` est donc **inopérant tel quel** ; seul le booléen `consent_external` fonctionne. Ce n'est pas une fuite (c'est un refus), mais c'est un contrôle annoncé et non appliqué.

2. **Le PCE n'est pas câblé dans le code de HEAD.** `hybrid_chat.py` de HEAD n'a **aucun** paramètre `personal_context` (vérifié par `grep` : 0 occurrence). Le mécanisme n'existe que sur `integration/career-cv-language-20261017`.

### 3.8 Provenance et cycle de vie — résumé

```
Career :  document → extraction déterministe → suggestions → review par champ → apply → profil plat
                                              ↓                             ↓
                                    profile_imports (garé)         provenance PERDUE

PCE    :  paquet JSON → validation → pending → décision par souvenir → approved
                                              ↓
                                    provenance CONSERVÉE + tombstones + journal
```

---

## 4. État Git : où se trouve quoi

PREUVE GIT (`git merge-base --is-ancestor <branche> main`) :

| Branche | Contient `personal_profile/` | Fusionnée dans `main` |
|---|---|---|
| `feature/personal-context-engine` @ `e6af0db` | oui | **non** |
| `integration/profile-study` @ `c32b284` | oui | **non** |
| `integration/career-cv-language-20261017` @ `ff307ef` | oui | **non** |
| `integration/security-redaction-20261017` @ `67a1159` | oui | **non** |
| `integration/career-international-core` @ `941405b` | oui | **non** |
| `feature/v1-night-profile` @ `255910f` | oui | **non** |
| `feature/profile-integration-v1` @ `ed8a6b9` | **non** | oui |
| `integration/profile-core` @ `ed8a6b9` | **non** (présente seulement dans l'index de travail du worktree) | oui |
| `main` @ `450a286` | **non** | — |
| `HEAD` (`audit/total-v3-2026-10-14`) @ `fb46fcf` | **non** | — |

Les blobs `personal_profile/store.py` (`e43e5cdc`) et `personal_profile/schema.py` (`bfff6eba`) sont **identiques sur les 6 branches** : le moteur n'a pas divergé, il a été dupliqué. Le worktree `.devkit/integration/profile-core` a en plus une modification non commitée de `service.py` qui **réduit** `recent_decisions` à 4 clés, presumably pour ne pas exposer le contenu des souvenirs dans un diagnostic.

Sur cette machine, `state/personal_profile/personal_profile.sqlite3` existe (40 Ko, 15 octobre) alors que ni `main` ni HEAD ne contiennent le code qui l'écrit.

MESURÉ (lecture seule, `mode=ro`, aucun contenu lu) :

```
tables       : ['candidates', 'decisions', 'imports', 'tombstones']
candidates   = 0     decisions = 0
imports      = 0     tombstones = 0
user_version = 1
```

La base est au bon schéma (v1) mais **totalement vide**. Elle prouve que le moteur a été exécuté au moins une fois (le schéma a été créé) sans qu'aucun souvenir n'ait été importé. Le risque de perte est donc **potentiel, pas consommé**.

Écart HEAD ↔ main sur le profil : `main` ajoute `career/profile_readiness.py` (note /20 sur les faits enregistrés) et l'injecte dans `get_profile()`. Toute unification doit préserver ce calcul ou le déplacer.

---

## 5. Migrations nécessaires

Aucune ne doit être exécutée dans ce rapport. Liste et ordre.

### M1 — Fusionner le moteur PCE dans la base de code (préalable bloquant)

Source : `feature/personal-context-engine` @ `e6af0db` (blobs identiques, choisir une seule source). Contenu : `personal_profile/` — **12 modules, 4 652 lignes** — plus `personal_profile_web.py`, `profile_chat.py`, `v5_static/profile.{html,css,js}`, et **13 fichiers de tests** (3 644 lignes).

Précautions :
- `come_ai_web.py`, `hybrid_chat.py`, `workspace_core.py` sont des **fichiers disputés**. `tests/test_consent_guard_isolation.py` les déclare `PROTECTED_PATHS` : un lot qui les touche doit être justifié.
- Le moteur crée `state/personal_profile/` ; s'il est absent, il doit se créer sans lire de configuration et sans réseau.

### M2 — Introduire la provenance dans `candidate_profile` (additif, réversible)

Ajouter des colonnes **nulles par défaut** : `source_kind`, `source_reference`, `source_observed_at`, `source_import_id`, `revision`. Les valeurs existantes restent NULL = « origine inconnue ». Aucun `VACUUM` requis, aucune perte.

Cette étape est réversible et peut être faite **avant** toute décision d'architecture. C'est la seule migration que je recommande de-court terme.

### M3 — Aligner les limites de longueur

Unifier `education` sur une seule limite. MESURÉ : le parseur produit 5 000, le service n'en garde que 1 000, silencieusement. Deux choix : lowers le parseur à 1 000 (perte à l'import, visible) ou monter le service à 5 000 (plus de place en base, cohérent avec `experience`). Le second est préférable, mais change la taille des exports et des prompts IA.

### M4 — Table de correspondance `candidate_profile` ↔ `candidates`

Table de pont, sans modifier les deux moteurs :

```sql
CREATE TABLE profile_field_provenance (
    field_name        TEXT NOT NULL,      -- education, skills, …
    candidate_id      TEXT NOT NULL,      -- -> personal_profile.candidates
    revision          INTEGER NOT NULL,
    strategy          TEXT NOT NULL,      -- 'copied' | 'referenced'
    created_at        TEXT NOT NULL,
    PRIMARY KEY (field_name, candidate_id)
);
```

`strategy='referenced'` (recommandé) : `candidate_profile` n'est plus la source de vérité, seulement un **agrégat de lecture** construit à partir des souvenirs approuvés. `strategy='copied'` crée une deuxième vérité — à éviter.

### M5 — Effectuer la migration des données existantes

Pour chaque champ non vide de `candidate_profile`, créer un souvenir :

| Champ Career | `domain` PCE | `record_type` | `sensitivity` |
|---|---|---|---|
| `display_name` | `personal_preferences` | fact | standard |
| `contact_email`, `contact_phone`, `linkedin_url` | `personal_preferences` | fact | **sensitive** |
| `education`, `experience`, `skills`, `languages` | idem | fact | standard |
| `eligibility` | `logistics` | fact | **sensitive** |
| `target_companies` | `career_goals` | preference | standard |
| `notes` | `other` | transient | **sensitive** |

`source.kind = 'user_declared'`, `source.reference = 'career-migration'`, `source.observed_at = candidate_profile.updated_at`, `confidence.justification = 'Valeur déclarée dans le profil Career avant migration'`.

Statut initial : **`pending`, jamais `approved`**. Une migration ne vaut pas approbation — c'est la règle n°1 du moteur (`README.md` §5) et elle doit s'appliquer aussi à la migration.

`eligibility` et `notes` n'ont pas d'équivalent PCE : ce sont les deux seules données à traiter comme « à sensed degradation » (voir §6, R3).

### M6 — Rediriger les consommateurs Career

Consommateurs actuels de `get_profile()` : `career/scoring.py:314,391,409,425`, `career/application_prep.py:225-263`, `career/application_studio.py:62-132`, `career/service.py:3294,3490`, `career/profile_readiness.py` (sur `main`).

Le point de bascule est `get_profile()` : s'il devient une **lecture dérivée** (souvenirs approuvés → dict plat), les consommateurs ne changent pas. Sinon, il faut toucher 6 fichiers.

### M7 — Unifier le `purpose` du consentement

`career_summary` doit devenir `job_application` (déjà dans `PURPOSES`) ou être ajouté à la liste fermée. MESURÉ : aujourd'hui `check()` refuse systématiquement. Corriger avant de croire que le contrôle est actif.

### M8 — Câbler `personal_context` dans `hybrid_chat`

Sur la branche d'intégration, `ask()` accepte `personal_context` (≤ 1 500 car.) et `allow_personal_cloud`, avec refus si contexte personnel + fournisseur non local sans autorisation. HEAD ne l'a pas. Cette migration touche un fichier disputé (`hybrid_chat.py`, `PROTECTED_PATHS`).

### M9 — Corriger le périmètre de suppression

`reset_personal_data` doit décider explicitement du sort de `career_data/consent/`. MESURÉ : il survit aujourd'hui. Deux options cohérentes : l'inclure (suppression complète) ou le documentiser (les traces de transmission sont conservées 90 jours, TTL du garde-fou).

### M10 — Renommer `memory_storage`

Non une migration de données : `MemoryStorageService` → `MemoryStorageDiagnostics` (ou `MemoryInventory`). Le nom actuel suggère un magasin. Le changer casse `/api/v5/memory/storage` et `tests/test_memory_storage.py` ; prévoir l'alias.

---

## 6. Risques de perte

Classés par gravité. « Perte » = donnée utilisateur disparaît ou devient inaccessible.

### R1 — Moteur PCE absent de la base de code (ÉLEVÉ, MESURÉ)

`state/personal_profile/personal_profile.sqlite3` existe sur ce Mac. Ni `main` ni HEAD ne contiennent `personal_profile/`.

**Nuance vérifiée qui change la gravité** : la base est **vide** (0 ligne dans les 4 tables). Il n'y a donc **aucune donnée à perdre aujourd'hui**. Le risque est *potentiel* : dès qu'un premier souvenir sera importé via une branche non fusionnée, il deviendra inaccessible si cette branche est abandonnée — pas de lecture, pas d'export, pas de suppression par l'application (base en `0600`, dossier en `0700`).

**Mitigation** : fusionner M1 **avant** tout import réel, plutôt qu'extraire une base vide. Si des souvenirs sont importés entre-temps, extraire immédiatement vers `come-personal-profile-export/1` sur support externe.

### R2 — Provenance perdue à l'application (ÉLEVÉ, MESURÉ)

Après `apply_profile_import`, la valeur est écrite dans `candidate_profile` sans lien vers son import. MESURÉ : aucune colonne de provenance, aucun FK.

MESURÉ (scénario complet, base temporaire) : après application puis `delete_profile_import`,

```
valeur encore stockée : Excel
imports restants      : 0
colonnes de provenance : AUCUNE
```

Autrement dit : **la valeur survit, sa justification disparaît.** L'utilisateur ne peut plus répondre à « d'où vient-ce que mes compétences sont Claims Excel ? ». `delete_profile_import` ne revert rien — il ne touche que l'import et son fichier.

**Mitigation** : M2 puis M4 avant toute nouvelle importation.

### R3 — Perte de sémantique à la migration (ÉLEVÉ, JUGÉ)

Deux valeurs Career n'ont pas de place naturelle dans le modèle PCE :

- `eligibility` ∈ {unknown, compatible, incompatible} est un **enum utilisé par le scoring** (`career/scoring.py:391`). Le PCE n'a que `sensitivity` ∈ {standard, sensitive, restricted}. Si on mappe l'un sur l'autre, le scoring Career perd sa sémantique de « conformité déclarée ».
- `notes` (4 000 car.) est un texte libre. `statement` est plafonné à 400 caractères. Une conversion naïve tronque ou force `extensions`.

**Mitigation** : traiter `eligibility` comme un champ à part du socle unifié (colonne dérivée, pas un souvenir), ou accepter une perte explicite et documentée.

### R4 — Perte silencieuse à l'application (MOYEN, MESURÉ)

`education` : 3 799 caractères analysés → 1 000 stockés, sans avertissement. Le même défaut existe probablement pour toute future colonne dont la limite parseur > limite service.

**Mitigation** : M3 + un test de non-régression `len(suggestion) <= len(stored)`.

### R5 — Suppression qui ne supprime pas tout (MOYEN, MESURÉ)

`reset_personal_data` laisse la base de consentement. Un utilisateur qui exercise son droit à l'effacement conserve des traces de transmission (fournisseur, modèle, but, empreinte SHA de charge utile — jamais le contenu).

**Mitigation** : M9.

### R6 — Sauvegardes détruites par la suppression (MOYEN, LU)

`reset_personal_data` supprime `career-before-v*-to-v*-*.sqlite3` (`career/service.py:3841`). Si une migration est ratée et que l'utilisateur relance une suppression, il n'y a plus de filet.

**Mitigation** : exclure les sauvegardes du périmètre de suppression, ou les déplacer hors de `career_data/`.

### R7 — Deux vérités après migration (ÉLEVÉ, JUGÉ)

Si `candidate_profile` reste modifiable après M5, les deux surfaces divergent silencieusement. Le danger n'est pas la corruption, c'est que l'utilisateur croie corriger une fiche et corrige l'autre.

**Mitigation** : après M5, `candidate_profile` devient **lecture seule** dans le code (le `PUT /api/career/profile` écrit dans `candidates`).

### R8 — Régression du scoring Career (MOYEN, JUGÉ)

`career/scoring.py` et `career/application_prep.py` lisent des champs plats. Si `get_profile()` devient dérivé, un souvenir en `pending` ou `rejected` disparaît du scoring — comportement **voulu**, mais qui changera les scores affichés. `career/profile_readiness.py` (sur `main`) compte des champs non vides : son score /20 baissera mécaniquement.

**Mitigation** : figer les scores avant/après sur une base synthétique, et annoncer le changement.

### R9 — Non-déterminisme de la sélection PCE (FAIBLE, LU)

Le sélecteur de contexte classe par domaine, type, confiance, utilité, fraîcheur, requête. Deux souvenirs approuvés de même profil peuvent changer d'ordre selon le texte de la requête. Pour un champ plat Career (concaténation), l'ordre deviendrait visible.

**Mitigation** : concaténer de façon stable (tri par `candidate_id`) lors de la projection.

### R10 — Duplication du moteur (FAIBLE, PREUVE GIT)

6 branches portent les mêmes blobs. Une future correction appliquée à une seule crée deux moteurs divergents.

**Mitigation** : M1 fusionne **une** source et supprime les autres worktrees.

### R11 — `accept()` promeut une hypothèse (MOYEN, MESURÉ)

`ReviewService.accept()` (`review.py:145-160`) passe le statut à `approved` sans vérifier `record_type`. MESURÉ : `accept("h1")` sur une `hypothesis` réussit, alors que le README §5 règle 2 affirme « Une hypothèse n'est pas un fait » et que le §265 interdit explicitement `hypothesis → fact` par correction.

La parade existe : le sélecteur exclut l'hypothèse du contexte malgré son statut (`unapproved_hypothesis`, `context.py:392`), et MESURÉ confirme 0 item rendu. La règle « rien de non approuvé n'entre dans le contexte » tient donc — mais par le second niveau, pas par le premier.

**Pourquoi c'est un risque de perte** : la garantie tient à **un seul appel de filtre** dans un seul chemin d'envoi. Tout nouveau consommateur lisant `status == 'approved'` sans reconsulter `record_type` enverrait des hypothèses à l'IA comme des faits.

**Mitigation** : corriger `accept()` pour refuser une `hypothesis`, et ajouter le test correspondant. Correctif de 3 lignes, à faire avant M1.

---

## 7. Structure unique recommandée

**Recommandation : adopter le modèle `personal_profile` (`come-personal-profile-pack/1`) comme structure canonique unique, et rétrograder `candidate_profile` en projection de lecture.**

Justification (JUGÉE, fondée sur §3) :

| Critère | `candidate_profile` | `personal_profile` |
|---|---|---|
| Provenance par élément | non | oui |
| Approbation par élément | non (par champ d'un lot) | oui |
| Journal avant/après | non | oui |
| Anti-résurrection | non | oui (tombstones) |
| Anti-promotion d'hypothèse | sans objet | **partielle** — voir ci-dessous |
| Export versionné | non | oui |
| Droit à l'oubli vérifiable | non | oui (redaction + VACUUM) |
| Contrat d'import lisible par un tiers | non | oui (Space Bunny) |
| Extensibilité | non (colonnes fixes) | oui (`extensions` + domaines) |

`candidate_profile` garde deux avantages qu'il faut **préserver explicitement** plutôt qu'abandonner : un accès O(1) par champ plat, et des colonnes dérivées utiles au scoring (`eligibility`, `target_companies`).

### Nuance mesurée sur l'anti-promotion d'hypothèse

Le tableau ci-dessus ne dit pas que le moteur est parfait. MESURÉ :

```
invariant 5  : accept("h1") sur une hypothesis  -> SUCCEDE (statut = approved)
invariant 5bis: edit(record_type: hypothesis->fact) -> DecisionError (correct)
invariant 3  : souvenir sans source -> refusé, code 'source_invalid' (correct)
contexte après approbation d'une hypothèse -> 0 item
```

Donc **le statut peut devenir `approved` sur une hypothèse**, contrairement à ce qu'annonce le README (§5, règle 2 : « Une hypothèse n'est pas un fait »). La parade tient : le sélecteur de contexte l'exclut malgré tout (raison `unapproved_hypothesis`, `context.py:392`), et MESURÉ confirme qu'elle n'entre pas dans le contexte rendu.

C'est une **défense en profondeur qui fonctionne** — le garde-fou de deuxième niveau rattrape le premier. Mais le premier niveau ne tient pas, et c'est une fragilité : tout nouveau chemin d'envoi qui lirait `status == approved` sans reconsulter `record_type` ouvrirait une fuite. Le socle unifié devrait **corriger** `accept()` pour refuser une hypothèse, plutôt que compter sur le sélecteur.

### Structure cible proposée

```text
SOURCE UNIQUE
  personal_profile/candidates        (1 ligne = 1 fait déclaré, avec provenance)
      ├── status / sensitivity / confidence / temporal_validity / personalization
      ├── decisions                   (journal avant/après)
      ├── imports                    (traçabilité des paquets)
      └── tombstones                 (anti-résurrection)

PROJECTIONS DE LECTURE (dérivées, jamais écrites par l'utilisateur)
  candidate_profile                  ← souvenirs approuvés, concaténés par domaine
  career.profile_readiness           ← note /20 sur les champs dérivés
  context_for_mission(mission)       ← sélection bornée pour le chat

MAGASINS DISTINCTS (à ne pas fusionner)
  personal_memory                    ← documents + chunks + FTS5  (citations, pas de profil)
  consent_guard                      ← accords de transmission à usage unique
  task_queue / usage_ledger          ← état machine et métriques

DIAGNOSTIC (lecture seule)
  memory_storage                     ← renommer, ne stocke rien
```

Invariants à faire respecter par tout code futur :

1. **Une seule écriture.** `PUT /api/career/profile` écrit dans `candidates`, jamais dans la projection.
2. **Rien n'est approuvé implicitement.** Import, migration et correction produisent `pending`.
3. **Aucune valeur sans provenance.** Un souvenir sans `source` est invalide, pas « ancien format ».
4. **Aucune suppression silencieuse.** `forget` laisse une trace non personnelle (identifiant + empreinte).
5. **Le sélecteur ne promeut rien, et `accept()` doit le garantir.** MESURÉ : `accept()` accepte aujourd'hui une `hypothesis` ; c'est le sélecteur qui l'exclut ensuite. Corriger les deux niveaux.
6. **`personal_memory` n'est pas un profil.** Aucune fusion avec le socle.
7. **`memory_storage` n'est pas un magasin.** Aucun `INSERT` ne doit y apparaître.

### Ce qu'il ne faut pas faire

- **Ne pas** fusionner `personal_memory` dans le socle : ses citations page/ligne et son FTS5 n'ont pas d'équivalent.
- **Ne pas** faire de `candidate_profile` une table de copie : ce serait une deuxième vérité (R7).
- **Ne pas** supprimer `candidate_profile` : 6 consommateurs Career en dépendent ; le retrograder est plus sûr.
- **Ne pas** migrer avant M1 : sans le moteur dans la base de code, M5 écrit dans le vide et les données migrées deviennent inaccessibles (R1).

---

## 8. Séquencement proposé

```text
Lot 0  Sauvegarde de la base PCE                      (R1) — trivial, base actuellement vide
Lot 1  M1 fusion du moteur PCE                        (R1 — préalable bloquant)
Lot 2  M3 alignement des limites + test               (R4)
Lot 3  M2 colonnes de provenance additives            (R2) — réversible
Lot 4  M7 correction du but `career_summary`          (contrôle annoncé mais inopérant)
Lot 5  R11 `accept()` refuse une hypothèse + test      (3 lignes, avant M1)
Lot 6  M9 périmètre de suppression + R6               (droits utilisateur)
Lot 7  M4 + M5 migration des données                  (R3, R7)
Lot 8  M6 redirection des consommateurs Career        (R8)
Lot 9  M8 câblage `personal_context` dans hybrid_chat  (fichier disputé)
Lot 10 M10 renommage de `memory_storage`              (non bloquant)
```

Lots 2, 3, 4, 5, 6 sont indépendants et réversibles. Le lot 0 est peu coûteux aujourd'hui (base vide) mais devient indispensable dès le premier import réel : **il ne faut pas l'écarter pour cette raison**. Le lot 5 est le seul qui corrige un défaut **de sécurité** et devrait précéder toute mise en production du moteur.

---

## 9. Ce que ce rapport ne dit pas

- Il ne mesure pas la qualité desontaneous parsing d'un CV réel : aucun CV n'a été lu.
- Il n'évalue pas `career/profile_readiness.py` en détail (présent sur `main`, absent de HEAD) au-delà de son interaction avec le scoring.
- Il ne tranche pas le sort des 5 autres branches non fusionnées portant `personal_profile` : c'est une décision de versionnage, pas d'architecture.
- Il ne propose aucun code. Aucune migration n'a été exécutée, aucune base réelle n'a été ouverte.