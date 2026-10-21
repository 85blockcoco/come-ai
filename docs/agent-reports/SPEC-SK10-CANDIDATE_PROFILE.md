# SPEC-SK10 — Profil candidat avec preuves approuvées

**Mission** : CVBOOST-31 — SK-10
**Branche** : `worker/cvboost-31-1792614464` → reprise sur `agent/spec-sk10-candidate-profile`
**Base** : `main` (`f5b22f2` — merge(career): ATS diagnostics and targeted CV variants pipeline)
**Suite** : 1463 tests verts (1424 avant mission, +39 nouveaux), 1 skip préexistant
**Lint** : `ruff check .` → All checks passed · `git diff --check` → propre

---

## 0. Comparaison avec la tentative précédente

La branche `agent/spec-sk10-candidate-profile` contenait déjà une implémentation
SK-10 (commit `2448d28`, même base `f5b22f2`). Elle a été relue avant d'écrire
et ses points forts ont été repris :

| Point fort de la tentative précédente | Repris ici |
|----------------------------------------|------------|
| Machine à états explicite des transitions | `ALLOWED_TRANSITIONS` dans `career/candidate_profile.py` |
| Règle « seul un acteur humain approuve » | `actor="user"` exigé par `apply_decision()` |
| Faits de contact (e-mail, téléphone) | kind `contact` + merge dans `contact_email` / `contact_phone` |
| Fixture « faits attendus » (golden file) | `tests/fixtures/candidate_profile/expected_facts.json` |
| Script d'essai manuel hors dépôt | `scripts/candidate_profile_manual_check.py` ( refuse un fichier du dépôt ) |

Ce que cette implémentation apporte en plus :

- **branchement réel au matching et à la candidature** : les faits approuvés
  enrichissent `_scoring_context()` et `_application_context()`, donc la
  couverture d'une offre et le brouillon de CV. La tentative précédente
  restait sur ses propres endpoints, sans toucher aux chemins de candidature ;
- **preuve structurale de non-approbation** : l'insertion SQL écrit le
  littéral `'proposed'`, il n'existe aucun chemin de code qui approuve ;
- **provenance de page exacte** : `extract_pages_from_bytes()` mappe chaque
  offset sur sa page réelle ;
- **migration additive** : schéma v9, les données existantes sont conservées.

---

## 1. Objectif

Transformer le CV importé en **profil structuré contrôlé par la personne** :

```
PDF / DOCX / image
  → extraction locale (parser Mission 01)
  → OCR local si nécessaire
  → propositions de faits (compétences, expériences, formation, langues, dates…)
  → provenance page / passage (offsets exacts)
  → approbation champ par champ (UI)
  → profil actif (seuls les faits approuvés)
```

Les six critères non négociables de la mission sont **structurels**, pas des
conventions documentées : ils sont garantis par le code et prouvés par les
tests (section 6).

---

## 2. Fichiers

### Créés

| Fichier | Rôle |
|---------|------|
| `career/candidate_profile.py` | Modèle : `Fact`, `Evidence`, `CandidateProfile`, 5 statuts, transitions, acteur, fusion profil, export portable |
| `career/profile_builder.py` | Pipeline : texte extrait → faits proposés (réutilise `career.cv_quality`) |
| `career_static/js/profile-builder.js` | UI d'approbation champ par champ |
| `scripts/candidate_profile_manual_check.py` | Essai manuel hors dépôt : lit un vrai CV, n'approuve rien, refuse un fichier du dépôt |
| `tests/test_candidate_profile.py` | 39 tests (modèle, builder, service, HTTP, garde-fous UI, script manuel) |
| `tests/fixtures/candidate_profile/cv_synthetique.txt` | Fixture synthétique (CV complet) |
| `tests/fixtures/candidate_profile/cv_ocr_synthetique.txt` | Fixture synthétique (lecture OCR plate) |
| `tests/fixtures/candidate_profile/expected_facts.json` | Faits attendus du CV synthétique (golden file) |
| `docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md` | Ce rapport |

### Modifiés

| Fichier | Modification |
|---------|--------------|
| `career/service.py` | Table `candidate_facts` (schéma v9), méthodes de service, filtre « faits approuvés » dans le matching et les brouillons, export/reset |
| `career/router.py` | 7 endpoints profil candidat + payloads Pydantic |
| `career/cv_quality/parser.py` | `extract_pages_from_bytes()` : le texte par page (offsets → page exacte) |
| `career/cv_quality/__init__.py` | Export de `extract_pages_from_bytes` |
| `career_static/index.html` | Panneau « Mon profil accepté, fait par fait » + chargement du script |
| `career_static/career.js` | Rafraîchissement du panneau à l'ouverture de l'onglet « Mon profil » |
| `career_static/career.css` | Styles des cartes de faits, compteurs, badges de statut |
| `tests/test_qualification_snapshot_persistence.py` | Version de schéma attendue : 8 → 9 |

---

## 3. Modèle de données

### Statuts par fait

| Statut | Sémantique | Utilisable pour le matching ? |
|--------|------------|--------------------------------|
| `proposed` | Extrait automatiquement, en attente de validation | **Non** |
| `approved` | Validé par la personne | **Oui** |
| `rejected` | Rejeté par la personne (erreur OCR, hors sujet) | **Non** |
| `modified` | Corrigé par la personne (date, niveau de langue, libellé) | **Oui** |
| `suspended` | Mis de côté temporairement | **Non** |

`USABLE_STATUSES = {approved, modified}` — c'est la seule porte d'entrée vers
le matching et les brouillons de candidature.

### Preuve d'un fait

```python
@dataclass(frozen=True)
class Evidence:
    source: str          # embedded_text | ocr | manual
    page: int            # 1-based, 0 = inconnue
    page_confidence: str # exact | estimated | unknown
    start_offset: int    # index du premier caractère dans le texte source
    end_offset: int      # index du dernier caractère (exclu)
    quote: str           # passage verbatim
    filename: str
```

La citation est le texte source **au caractère près** : `source[start:end]`
donne la citation (aux espaces près). Le test
`test_builder_keeps_the_exact_source_of_every_fact` le vérifie pour chaque fait
proposé.

### Origine des pages

| Situation | Page | Confiance |
|-----------|------|-----------|
| PDF/DOCX/TXT lu par le parser Mission 01 | page réelle | `exact` |
| Lecture OCR (texte aplati, `ocr_pages` connu) | répartition estimation | `estimated` |
| Texte collé | page 1 | `estimated` |

L'interface affiche la mention « (estimée) » quand la page n'est pas certaine :
une page estimée est une indication, jamais une preuve.

---

## 4. Pipeline

### 4.1 Extraction

`career/cv_quality/parser.py::extract_pages_from_bytes()` renvoie la liste des
textes de page. Le texte complet est `"\n\n".join(pages)` : un offset dans le
texte joint se ramène donc exactement à une page.

Quand la source est un import OCR, le service réutilise le texte OCR déjà
stocké (l'OCR aplatit les pages) et répartit le texte sur `ocr_pages` en mode
`estimated`.

### 4.2 Propositions

`career/profile_builder.py::build_fact_proposals()` :

1. `analyze_cv()` (Mission 01) détecte les rubriques `Expérience`, `Formation`,
   `Compétences`, `Langues`, `Projets`, `Certifications` **avec leurs offsets**.
2. Chaque rubrique est découpée en items (une ligne, ou une virgule pour les
   compétences).
3. Les expériences sont lues ligne par ligne : une ligne datée ouvre une
   entrée (`rôle | société | dates`), les lignes suivantes portent le
   résultat. Ce parsing est local et déterministe — le moteur de structure de
   Mission 01 est réutilisé pour les rubriques, mais sa récupération
   « Canva » (heuristique de reprise) est écartée ici parce qu'elle ne donne
   pas d'offsets fiables.
4. Chaque fait est créé avec `status="proposed"`, sa preuve et sa page.

Garde-fou structurel : `build_fact_proposals()` lève une exception si un fait
sortait avec un statut autre que `proposed`, et l'insertion SQL du service
écrit le littéral `'proposed'` — **aucun chemin de code n'approuve un fait**.

### 4.3 Décision

| Décision API | Effet |
|--------------|-------|
| `approve` | `approved` — le fait devient utilisable |
| `reject` | `rejected` — le fait est écarté |
| `suspend` | `suspended` — le fait est mis de côté, sans être perdu |
| `modify` | `modified` — le fait est corrigé (valeur obligatoire) |
| `reopen` | `proposed` — le fait revient en relecture |

La machine à états est explicite (`ALLOWED_TRANSITIONS`) : un fait rejeté ou
mis de côté doit être **rouvert** avant de pouvoir être approuvé à nouveau.
`apply_decision()` exige aussi `actor="user"` : aucun chemin automatisé ne peut
statuer sur un fait, et un fait lu par OCR attend donc toujours une décision
humaine.

Une correction remplace le **niveau** quand le fait a une valeur structurée
(niveau de langue) et le **libellé** sinon ; la valeur d'origine est conservée
dans `original_label` / `original_value` pour l'audit.

### 4.4 Profil actif

`merge_usable_facts()` ajoute au profil local **uniquement** les faits
approuvés ou corrigés, sans doublon et dans la limite de chaque champ. Les
faits de contact (`contact_email`, `contact_phone`) complètent un champ vide,
jamais un champ déjà rempli. Le service l'applique à deux endroits :

- `_scoring_context()` → la correspondance (score, couverture, gaps) ;
- `_application_context()` → le brouillon de CV / lettre et le kit de
  candidature.

Un fait `proposed`, `rejected` ou `suspended` ne peut donc **jamais** justifier
une candidature : il n'entre dans aucun de ces deux chemins.

---

## 5. API

| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/api/career/candidate-profile/facts?status=` | Liste des faits + compteurs par statut |
| `POST` | `/api/career/candidate-profile/proposals` | Propose les faits d'un import (`import_id`) ou d'un texte collé |
| `PATCH` | `/api/career/candidate-profile/facts/{fact_id}` | Une décision explicite (`decision`, `value`, `note`) |
| `DELETE` | `/api/career/candidate-profile/facts/{fact_id}` | Supprime un fait et sa preuve |
| `GET` | `/api/career/candidate-profile/active` | Profil actif : seuls les faits utilisables + leurs preuves |
| `POST` | `/api/career/candidate-profile/apply` | Applique les faits approuvés aux champs du profil |
| `GET` | `/api/career/candidate-profile/export` | Export portable JSON (tous les faits, statut et preuve) |

L'export reprend le schéma `come-ai-candidate-profile/1` :

```json
{
  "schema": "come-ai-candidate-profile/1",
  "counts": {"proposed": 12, "approved": 4, "rejected": 1, "modified": 0, "suspended": 0},
  "facts": [
    {
      "id": "fact_…", "kind": "skill", "label": "Excel", "status": "approved",
      "evidence": {"source": "embedded_text", "page": 1, "page_confidence": "exact",
                   "start_offset": 428, "end_offset": 433, "quote": "Excel",
                   "filename": "cv-synthetique.txt"}
    }
  ],
  "active_profile": {"skills": ["Excel"]}
}
```

LaCapability `GET /api/career/health` expose désormais `candidate_profile` :
`local_only: true`, `field_by_field_review: true`, `ocr_auto_approved: false`,
`portable_export: true`, et les 5 statuts.

---

## 6. Critères non négociables → preuves

| # | Critère | Comment il est garanti | Test |
|---|---------|-------------------------|------|
| 1 | **Résultat OCR jamais automatiquement approuvé** | L'insertion SQL écrit le littéral `'proposed'` ; le builder refuse de produire un autre statut ; `apply_decision()` exige `actor="user"` ; seule la décision explicite change un statut | `test_builder_never_approves_anything_even_for_ocr`, `test_an_ocr_import_proposes_facts_without_approving_them`, `test_service_never_writes_an_approved_status_outside_a_decision`, `test_only_the_person_can_decide_a_fact` |
| 2 | **Chaque compétence, expérience, date, diplôme garde sa source** | `Evidence` (page + offsets + citation) est obligatoire et sérialisée ; la citation est le texte source au caractère près | `test_builder_keeps_the_exact_source_of_every_fact`, `test_builder_maps_offsets_to_the_right_page_when_pages_are_known`, `test_the_synthetic_fixture_produces_exactly_the_expected_facts` |
| 3 | **Suppression et export fonctionnent** | `DELETE` sur un fait, export JSON portable, export global de Données perso, reset local | `test_service_deletes_one_fact`, `test_service_exports_a_portable_profile`, `test_http_export_returns_a_local_json_file`, `test_the_local_reset_erases_the_facts` |
| 4 | **Aucun document réel dans les tests** | Trois fixtures 100 % synthétiques + golden file ; aucun fichier de l'utilisateur | `tests/fixtures/candidate_profile/*` |
| 5 | **Faits non approuvés ≠ justifier une candidature** | `merge_usable_facts()` ne retient que `approved` / `modified`, et n'est appelé que par les chemins matching et candidature | `test_a_proposed_fact_never_reaches_the_candidature_draft`, `test_an_approved_fact_reaches_the_candidature_draft`, `test_a_suspended_or_rejected_fact_leaves_the_candidature_draft`, `test_only_approved_facts_reach_the_profile_fields` |
| 6 | **Vrais essais utilisateur séparés des fixtures Git** | Script manuel qui lit un document **hors du dépôt** et refuse un fichier du dépôt ; procédure d'essai en section 8 | `test_the_manual_check_script_refuses_a_document_stored_in_the_repository`, `test_the_manual_check_script_reads_a_document_outside_the_repository` |

Les 5 statuts sont implémentés et testés un par un
(`test_five_statuses_are_declared_and_only_two_are_usable`,
`test_apply_decision_covers_every_status`).

---

## 7. Interface

Panneau **« Mon profil accepté, fait par fait »** dans l'onglet « Mon profil » :

- sélection d'un import local (liste alimentée par `/api/career/profile-imports`)
  ou collage d'un texte ;
- compteur par statut (à vérifier / approuvés / corrigés / mis de côté /
  rejetés) ;
- une carte par fait : type, statut, badge « OCR — validation obligatoire » si
  lecture OCR, page + caractères, citation verbatim ;
- actions : **Approuver**, **Corriger** (champ de saisie), **Rejeter**,
  **Mettre de côté** ; pour un fait déjà décidé : **Rouvrir**, **Supprimer** ;
- bouton « Appliquer les faits approuvés à mon profil » ;
- bouton « Exporter mon profil » (télécharge le JSON portable).

Le rendu passe par `textContent` uniquement : aucun contenu de document n'est
injecté en HTML (`test_the_profile_panel_exposes_a_field_by_field_review`).

Règle affichée dans l'interface : « Rien n'est validé automatiquement, y compris
ce qui vient de l'OCR. Un fait proposé, rejeté ou mis de côté ne peut pas
justifier une correspondance ni une candidature. »

---

## 8. Essais utilisateur réels (hors dépôt)

Ces essais se font **avec le CV de la personne**, sur la machine locale. Aucun
CV réel n'entre dans Git : les fixtures du dépôt restent synthétiques.

**Outil hors dépôt** — `scripts/candidate_profile_manual_check.py` lit un
document réel *hors du dépôt*, affiche les faits proposés avec page, offsets et
citation, et **refuse** un fichier situé dans le dépôt :

```bash
cp ~/Documents/mon-cv.pdf /tmp/mon-cv.pdf      # hors du dépôt
python scripts/candidate_profile_manual_check.py /tmp/mon-cv.pdf
```

Le script n'écrit rien, n'envoie rien et n'approuve aucun fait.

**Dans l'application** (sur le CV de la personne) :

1. **Import** — dans « Mon profil », importer un vrai PDF (texte) et un vrai PDF
   scanné. Vérifier que le second déclenche l'OCR macOS et affiche le badge
   « OCR — validation obligatoire ».
2. **Propositions** — « Proposer des faits à vérifier » depuis l'import. Vérifier
   que chaque carte montre la page et une citation qui correspondent au PDF
   ouvert à côté.
3. **Approbation** — approuver une compétence, corriger une date d'expérience,
   rejeter une ligne d'OCR fausse, mettre une certification de côté.
4. **Effet matching** — ouvrir une offre : la compétence approuvée doit
   apparaître dans la couverture ; la compétence rejetée ne doit apparaître
   nulle part.
5. **Effet candidature** — préparer un brouillon : la section « Compétences »
   contient uniquement les faits approuvés.
6. **Suppression** — supprimer un fait : il disparaît de la liste et du profil.
7. **Export** — exporter le profil, rouvrir le JSON, vérifier que chaque fait
   garde page + offsets + citation.
8. **Reprise** — redémarrer l'application : les faits, leurs statuts et leurs
   preuves sont toujours là.

Retour à consigner hors dépôt : `docs/agent-reports/SPEC-SK10-ESSAIS-<date>.md`
(ne pas versionner un document personnel).

---

## 9. Validation

```bash
./checklist_codex.sh                                   # → TOUT VERT
.venv/bin/python -m pytest -q tests/test_candidate_profile.py   # 39 passed
.venv/bin/python -m pytest -q                           # 1463 passed, 1 skipped
.venv/bin/python -m ruff check .                       # All checks passed
git diff --check                                       # propre
```

Détail de la suite : 39 nouveaux tests —
modèle et statuts (10), construction des propositions (7), service local (13),
séparation matching / candidature (4), API HTTP (3), garde-fous d'interface (2),
essai manuel hors dépôt (2).

---

## 10. Limites connues et suite

- **La page d'un import PDF** dépend de la relecture Mission 01 : le service
  ré-extrait le document stocké avec le parser local. Si la relecture diffère du
  texte affiché dans l'aperçu de l'import, la citation reste vérifiable dans le
  document lui-même, mais pas dans l'aperçu. Comportement signalé dans
  l'interface (confiance « estimée » quand la page n'est pas certaine).
- **Un PDF scanné** ne peut pas être re-lu par le parser : le service réutilise
  alors le texte OCR stocké, avec des pages estimées et une validation
  obligatoire.
- **Supprimer un import** ne supprime pas les faits déjà proposés : leurs
  citations restent dans le profil. C'est un choix — une décision explicite ne
  disparaît pas en silence. Les faits restent supprimables un par un.
- **SK-11 (suite)** : le profil actif est prêt à alimenter la correspondance
  fine et la justification de candidature. Le verrou posé ici (un fait non
  approuvé ne justifie rien) est la condition d'entrée de SK-11.
- **Extensions possibles** : comparaison de deux versions d'un même CV, export
  PDF du profil portable, détection de faits contradictoires entre deux
  documents.

---

**Rapport généré le** : 2026-10-21
**Agent** : Mission CVBOOST-31 — SK-10
**Statut** : ✅ Complet, prêt pour relecture et intégration
