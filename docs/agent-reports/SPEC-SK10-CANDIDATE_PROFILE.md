# SPEC-SK10 — Profil candidat avec preuves approuvées

**Mission** : CVBOOST-31 — SK-10
**Branche** : `worker/cvboost-31-1792617672` → reprise sur `agent/spec-sk10-candidate-profile`
**Base** : `main` (`f5b22f2` — merge(career): ATS diagnostics and targeted CV variants pipeline)
**Suite** : 1482 tests verts (1463 avant mission, +19 tests adversariaux), 1 skip préexistant
**Lint** : `ruff check .` → All checks passed · `git diff --check` → propre

---

## 0. Recherche préalable : ce qui existait déjà

Trois implémentations parallèles de SK-10 existaient avant cette tentative. Aucune
n'a été recopiée à l'aveugle : la plus complète a été relue ligne à ligne, les
autres ont servi de contre-épreuve.

| Tentative | Contenu | Décision |
|-----------|---------|----------|
| `agent/spec-sk10-candidate-profile` (`0502c4b`) | Livraison canonique : modèle, builder, service, UI, 38 tests | **Reprise** (cherry-pick propre, base identique) puis auditée et corrigée |
| `worker/cvboost-31-1792614191` (`3fc6b07`) | Implémentation indépendante, dossier de fixtures différent | Non retenue : structure divergente, moins de garanties |
| `worker/cvboost-31-1792615600` (`c029b15`) | Autre implémentation indépendante, tables et statuts différents | Non retenue : même conclusion |

**Aucune v3 n'a été créée** : les corrections sont faites dans les modules
existants de la livraison canonique.

> **Note de fusion** — pendant ce travail, la branche de mission a avancé
> (`ac72b82` : application des faits de contact approuvés au profil, c'est-à-dire
> D2 ci-dessous). Le travail a été **rebasesé sur cette tête** au lieu de
> l'écraser : la branche `agent/spec-sk10-candidate-profile` avance par
> fast-forward, sans force-push, et le correctif de contact y est conservé.

Cette tentative apporte ce que la livraison précédente ne contenait pas :

- **un audit adversariel** qui a trouvé 6 défauts réels (section 2), tous
  corrigés dans les modules existants ;
- **un apply réversible** : un fait appliqué puis rejeté, mis de côté, rouvert ou
  supprimé **cesse de justifier une candidature** — c'était le défaut le plus
  grave, il touchait le critère bloquant de la mission ;
- **une provenance au caractère près** : la citation stockée est désormais le
  texte source exact (`source[start:end]`), sans espace normalisé en douce ;
- **une page honnête** : un DOCX ou une lecture OCR n'affichent plus une page
  « exacte » qu'ils ne peuvent pas prouver.

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
  → profil actif (seuls faits approuvés)
```

Les six critères non négociables de la mission sont **structurels**, pas des
conventions documentées : ils sont garantis par le code et prouvés par les
tests (section 6).

---

## 2. Audit adversarial : 6 défauts trouvés, 6 corrigés

La livraison reprise a été soumise à une campagne de scénarios-hostiles. Chaque
défaut a été **reproduit** avant d'être corrigé, puis figé en test de
non-régression.

### D1 — Un fait appliqué puis rejeté continuait de justifier une candidature 🔴

**Reproduit** : `build → approve → apply → reject` laissait la ligne dans le
champ `skills` du profil. Le brouillon de candidature affichait donc toujours la
compétence rejetée — exactement ce que le critère 5 interdit.

**Cause** : l'« apply » écrivait dans le profil sans jamais mémoriser ce qu'il
avait écrit. Aucune décision ultérieure ne pouvait donc pas revenir en arrière.

**Correction** : le service retient désormais le champ et la ligne exacte que
chaque fait a écrits (`candidate_facts.applied_field` / `applied_line`, schéma
v10). Un fait rejeté, mis de côté, rouvert ou supprimé voit sa ligne retirée du
profil ; une correction remplace la ligne par la nouvelle ; si une ligne était
partagée avec un autre fait approuvé, elle **change de main** au lieu de
disparaître.

### D2 — Un fait de contact approuvé n'était jamais écrit dans le profil 🟠

**Reproduit** : `merge_usable_facts()` complétait `contact_email`, mais
`apply_candidate_facts()` ne sauvegardait que `education`, `experience`, `skills`
et `languages`. L'e-mail du CV disparaissait, et la réponse affirmait pourtant
« appliqué : 1 ».

> Ce défaut a été corrigé entre-temps sur la branche de mission (`ac72b82`).
> La correction est conservée et complétée ici.

**Correction** : les champs de contact sont persistés, et le résultat distingue
`applied` (faits présents dans le profil), `written` (faits qui y ont réellement
écrit) et `ignored` (faits sans place dans les champs, comme une date).

### D3 — Une rubrique saturée effaçait toutes les autres 🟠

**Reproduit** : au-delà de 60 faits d'un même type, la boucle de bornage
s'interrompait (`break`) : les rubriques **Langues**, **Formation** et
**Expérience** disparaissaient entièrement du bilan de relecture.

**Correction** : une rubrique à son plafond est **sautée**, jamais fatale pour le
reste du document.

### D4 — La citation n'était pas le passage source 🔴

**Reproduit** : sur une ligne contenant des espaces répétés
(`Python   et   SQL`), la citation stockée était `Python et` alors que les
offsets pointaient sur `Python   et   SQL`. La citation n'était donc pas le
passage annoncé par les offsets — le critère 2 n'était pas tenu.

**Correction** : les offsets sont calculés sur le texte **brut** (jamais sur une
version normalisée) et la citation est le texte source verbatim. Le libellé
affiché reste normalisé, la preuve ne l'est jamais.

### D5 — Un DOCX ou une lecture OCR affichait une page « exacte » 🟠

**Reproduit** : un DOCX n'a pas d'information de page ; le module en annonçait
toutefois une, avec la confiance `exact`. Un import OCR pouvait aussi être
relu par le parser au lieu de la lecture OCR réellement montrée à la personne.

**Correction** : un DOCX reste `estimated`, l'OCR garde sa lecture stockée, et
l'interface affiche « (estimée) » quand la page n'est pas prouvée.

### D6 — L'interface ne permettait pas de corriger un fait déjà approuvé 🟡

**Reproduit** : le bouton « Corriger » n'existait que pour un fait `proposed`.
Un fait approuvé — donc déjà dans le profil — ne pouvait plus être rectifié,
alors que la machine à états l'autorise.

**Correction** : « Corriger » est proposé pour un fait approuvé ou corrigé.

---

## 3. Fichiers

### Créés (livraison reprise)

| Fichier | Rôle |
|---------|------|
| `career/candidate_profile.py` | Modèle : `Fact`, `Evidence`, `CandidateProfile`, 5 statuts, transitions, acteur, fusion profil, export portable |
| `career/profile_builder.py` | Pipeline : texte extrait → faits proposés (réutilise `career.cv_quality`) |
| `career_static/js/profile-builder.js` | UI d'approbation champ par champ |
| `scripts/candidate_profile_manual_check.py` | Essai manuel hors dépôt : lit un vrai CV, n'approuve rien, refuse un fichier du dépôt |
| `tests/test_candidate_profile.py` | 58 tests (modèle, builder, service, HTTP, garde-fous UI, script manuel, campagne adversariale) |
| `tests/fixtures/candidate_profile/cv_synthetique.txt` | Fixture synthétique (CV complet) |
| `tests/fixtures/candidate_profile/cv_ocr_synthetique.txt` | Fixture synthétique (lecture OCR plate) |
| `tests/fixtures/candidate_profile/expected_facts.json` | Faits attendus du CV synthétique (golden file) |
| `docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md` | Ce rapport |

### Modifiés

| Fichier | Modification |
|---------|--------------|
| `career/service.py` | Table `candidate_facts` (schéma v9 → **v10** : `applied_field`, `applied_line`), apply réversible, contacts persistés, migration qui répare les profils construits avant v10, export multi-documents, filtre de statut valide |
| `career/candidate_profile.py` | `profile_target()`, `remove_profile_line()`, `merge_usable_facts_with_sources()` (savoir ce que chaque fait a réellement écrit) |
| `career/profile_builder.py` | Offsets exacts sur le texte brut, citation verbatim, bornage par rubrique qui saute au lieu d'interrompre, confiance de page explicite |
| `career/router.py` | 7 endpoints profil candidat + payloads Pydantic |
| `career/cv_quality/parser.py` | `extract_pages_from_bytes()` : le texte par page (offsets → page exacte) |
| `career/cv_quality/__init__.py` | Export de `extract_pages_from_bytes` |
| `career_static/js/profile-builder.js` | « Corriger » disponible pour un fait approuvé ou corrigé |
| `career_static/index.html` | Panneau « Mon profil accepté, fait par fait » + chargement du script |
| `career_static/career.js` | Rafraîchissement du panneau à l'ouverture de l'onglet « Mon profil » |
| `career_static/career.css` | Styles des cartes de faits, compteurs, badges de statut |
| `tests/test_qualification_snapshot_persistence.py` | Version de schéma attendue : 9 → 10 |

---

## 4. Modèle de données

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

La citation est le texte source **au caractère près** : `source[start:end]` donne
exactement la citation, espaces compris. Le test
`test_every_proposed_fact_points_at_its_own_source_passage` le vérifie pour
chaque fait proposé, et `test_the_quote_is_the_verbatim_source_passage` le
vérifie sur un document qui contient des espaces répétés.

### Origine des pages

| Situation | Page | Confiance |
|-----------|------|-----------|
| PDF lu par le parser Mission 01 | page réelle | `exact` |
| TXT avec sauts de page (`\f`) | page réelle | `exact` |
| DOCX (aucune information de page) | bloc unique | `estimated` |
| Lecture OCR (texte aplati, `ocr_pages` connu) | répartition estimation | `estimated` |
| Texte collé | page 1 | `estimated` |

L'interface affiche la mention « (estimée) » quand la page n'est pas certaine :
une page estimée est une indication, jamais une preuve.

---

## 5. Pipeline

### 5.1 Extraction

`career/cv_quality/parser.py::extract_pages_from_bytes()` renvoie la liste des
textes de page. Le texte complet est `"\n\n".join(pages)` : un offset dans le
texte joint se ramène donc exactement à une page.

Quand la source est un import OCR, le service réutilise le texte OCR déjà
stocké (l'OCR aplatit les pages) et répartit le texte sur `ocr_pages` en mode
`estimated`. La lecture proposée est **exactement celle que la personne a vue**
dans l'aperçu de l'import.

### 5.2 Propositions

`career/profile_builder.py::build_fact_proposals()` :

1. `analyze_cv()` (Mission 01) détecte les rubriques `Expérience`, `Formation`,
   `Compétences`, `Langues`, `Projets`, `Certifications` **avec leurs offsets**.
2. Chaque rubrique est découpée en items (une ligne, ou une virgule pour les
   compétences). Les offsets sont calculés sur le texte **brut** : le passage
   `source[start:end]` est toujours l'item lui-même.
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

### 5.3 Décision

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

### 5.4 Profil actif

`merge_usable_facts()` ajoute au profil local **uniquement** les faits
approuvés ou corrigés, sans doublon et dans la limite de chaque champ. Les
faits de contact (`contact_email`, `contact_phone`) complètent un champ vide,
jamais un champ déjà rempli. Le service l'applique à deux endroits :

- `_scoring_context()` → la correspondance (score, couverture, gaps) ;
- `_application_context()` → le brouillon de CV / lettre et le kit de
  candidature.

`merge_usable_facts_with_sources()` retourne en plus **ce que chaque fait a
réellement écrit** : c'est ce qui rend l'« apply » réversible (D1). Une ligne
que la personne avait écrite elle-même n'est jamais attribuée à un fait, donc
jamais retirée par une décision.

Un fait `proposed`, `rejected` ou `suspended` ne peut donc **jamais** justifier
une candidature : il n'entre dans aucun de ces deux chemins, et la ligne qu'il
avait éventuellement écrite dans le profil lui est retirée.

---

## 6. API

| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/api/career/candidate-profile/facts?status=` | Liste des faits + compteurs par statut (statut inconnu → 400) |
| `POST` | `/api/career/candidate-profile/proposals` | Propose les faits d'un import (`import_id`) ou d'un texte collé |
| `PATCH` | `/api/career/candidate-profile/facts/{fact_id}` | Une décision explicite (`decision`, `value`, `note`) |
| `DELETE` | `/api/career/candidate-profile/facts/{fact_id}` | Supprime un fait, sa preuve et sa ligne de profil |
| `GET` | `/api/career/candidate-profile/active` | Profil actif : seuls les faits utilisables + leurs preuves |
| `POST` | `/api/career/candidate-profile/apply` | Applique les faits approuvés aux champs du profil |
| `GET` | `/api/career/candidate-profile/export` | Export portable JSON (tous les faits, statut et preuve) |

L'export reprend le schéma `come-ai-candidate-profile/1` :

```json
{
  "schema": "come-ai-candidate-profile/1",
  "counts": {"proposed": 12, "approved": 4, "rejected": 1, "modified": 0, "suspended": 0},
  "source_documents": ["cv-synthetique.txt"],
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

`source_documents` liste **tous** les documents d'origine : un export ne
prétend jamais venir d'un seul document.

La capability `GET /api/career/health` expose désormais `candidate_profile` :
`local_only: true`, `field_by_field_review: true`, `ocr_auto_approved: false`,
`portable_export: true`, et les 5 statuts.

---

## 7. Critères non négociables → preuves

| # | Critère | Comment il est garanti | Test |
|---|---------|-------------------------|------|
| 1 | **Résultat OCR jamais automatiquement approuvé** | L'insertion SQL écrit le littéral `'proposed'` ; le builder refuse de produire un autre statut ; `apply_decision()` exige `actor="user"` ; seule la décision explicite change un statut | `test_builder_never_approves_anything_even_for_ocr`, `test_an_ocr_import_proposes_facts_without_approving_them`, `test_service_never_writes_an_approved_status_outside_a_decision`, `test_only_the_person_can_decide_a_fact` |
| 2 | **Chaque compétence, expérience, date, diplôme garde sa source** | `Evidence` (page + offsets + citation) est obligatoire et sérialisée ; la citation **est** `source[start:end]`, sans normalisation cachée | `test_builder_keeps_the_exact_source_of_every_fact`, `test_every_proposed_fact_points_at_its_own_source_passage`, `test_the_quote_is_the_verbatim_source_passage`, `test_builder_maps_offsets_to_the_right_page_when_pages_are_known`, `test_a_docx_import_never_claims_an_exact_page` |
| 3 | **Suppression et export fonctionnent** | `DELETE` sur un fait (avec retrait de sa ligne de profil), export JSON portable, export global de Données perso, reset local | `test_service_deletes_one_fact`, `test_a_deleted_fact_leaves_the_profile_it_had_been_applied_to`, `test_service_exports_a_portable_profile`, `test_the_export_lists_every_source_document`, `test_http_export_returns_a_local_json_file`, `test_the_local_reset_erases_the_facts` |
| 4 | **Aucun document réel dans les tests** | Trois fixtures 100 % synthétiques + golden file ; aucun fichier de l'utilisateur | `tests/fixtures/candidate_profile/*` |
| 5 | **Faits non approuvés ≠ justifier une candidature** | `merge_usable_facts()` ne retient que `approved` / `modified` ; l'apply est **réversible** : un fait rejeté, mis de côté, rouvert ou supprimé perd sa ligne de profil | `test_a_proposed_fact_never_reaches_the_candidature_draft`, `test_a_rejected_fact_leaves_the_profile_it_had_been_applied_to`, `test_a_suspended_fact_leaves_the_profile_it_had_been_applied_to`, `test_a_reopened_fact_leaves_the_profile_it_had_been_applied_to`, `test_a_deleted_fact_leaves_the_profile_it_had_been_applied_to`, `test_the_manual_profile_value_is_never_removed_by_a_fact_decision`, `test_a_shared_line_leaves_the_profile_only_with_the_fact_that_justifies_it`, `test_only_approved_facts_reach_the_profile_fields` |
| 6 | **Vrais essais utilisateur séparés des fixtures Git** | Script manuel qui lit un document **hors du dépôt** et refuse un fichier du dépôt ; procédure d'essai en section 9 | `test_the_manual_check_script_refuses_a_document_stored_in_the_repository`, `test_the_manual_check_script_reads_a_document_outside_the_repository` |

Les 5 statuts sont implémentés et testés un par un
(`test_five_statuses_are_declared_and_only_two_are_usable`,
`test_apply_decision_covers_every_status`).

La migration **v9 → v10** répare les profils construits par la version
précédente : la ligne d'un fait qui n'est plus approuvé est retirée du profil
(`test_the_migration_repairs_a_profile_built_before_the_reversible_apply`).

---

## 8. Interface

Panneau **« Mon profil accepté, fait par fait »** dans l'onglet « Mon profil » :

- sélection d'un import local (liste alimentée par `/api/career/profile-imports`)
  ou collage d'un texte ;
- compteur par statut (à vérifier / approuvés / corrigés / mis de côté /
  rejetés) ;
- une carte par fait : type, statut, badge « OCR — validation obligatoire » si
  lecture OCR, page + caractères, citation verbatim ;
- actions : **Approuver**, **Corriger** (champ de saisie), **Rejeter**,
  **Mettre de côté** ; pour un fait déjà décidé : **Corriger**, **Mettre de
  côté**, **Rouvrir**, **Supprimer** ;
- bouton « Appliquer les faits approuvés à mon profil » ;
- bouton « Exporter mon profil » (télécharge le JSON portable).

Le rendu passe par `textContent` uniquement : aucun contenu de document n'est
injecté en HTML (`test_the_profile_panel_exposes_a_field_by_field_review`).

Règle affichée dans l'interface : « Rien n'est validé automatiquement, y compris
ce qui vient de l'OCR. Un fait proposé, rejeté ou mis de côté ne peut pas
justifier une correspondance ni une candidature. »

---

## 9. Essais utilisateur réels (hors dépôt)

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
6. **Retour arrière** — approuver une compétence, l'appliquer au profil, puis la
   **rejeter** : elle doit disparaître du profil *et* du brouillon. C'est le
   scénario que la version précédente ne tenait pas.
7. **Suppression** — supprimer un fait : il disparaît de la liste et du profil.
8. **Export** — exporter le profil, rouvrir le JSON, vérifier que chaque fait
   garde page + offsets + citation.
9. **Reprise** — redémarrer l'application : les faits, leurs statuts et leurs
   preuves sont toujours là.

Retour à consigner hors dépôt : `docs/agent-reports/SPEC-SK10-ESSAIS-<date>.md`
(ne pas versionner un document personnel).

### Essai réel exécuté par le worker (serveur local réel)

Pour ne pas laisser la vérification au seul niveau des tests, le panneau a été
exercé contre un **vrai serveur `uvicorn`** (répertoire de données hors dépôt,
CV synthétique, aucun document réel, aucun envoi externe) :

| Étape | Requête | Résultat observé |
|-------|---------|------------------|
| Propositions | `POST /api/career/candidate-profile/proposals` | HTTP 201 — 17 faits, tous `proposed`, compteurs `{proposed: 17}` |
| Preuve | — | fait « Power BI » : offsets 453–461, citation `Power BI` |
| Approbation | `PATCH …/facts/{id}` `{"decision":"approve"}` | HTTP 200 — `approved`, `usable: true` |
| Application | `POST …/apply` | HTTP 200 — appliqués 1, écrits 1, ignorés 0 — `skills: "Power BI"` |
| Rejet | `PATCH …/facts/{id}` `{"decision":"reject"}` | HTTP 200 — `rejected` |
| **Profil après rejet** | `GET /api/career/profile` | **`skills: ""`** — le fait rejeté ne justifie plus rien (défaut D1 corrigé) |
| Profil actif | `GET …/candidate-profile/active` | 0 fait utilisable, 16 en attente |
| Export | `GET …/candidate-profile/export` | `come-ai-candidate-profile/1`, `source_documents: ["cv-hors-depot.txt"]` |
| Interface | `GET /career`, `GET /career-static/js/profile-builder.js` | HTTP 200 — panneau et script servis |
| Capacité | `GET /api/career/health` | `local_only: true`, `ocr_auto_approved: false`, les 5 statuts |

Avant la correction D1, l'étape « Profil après rejet » renvoyait
`skills: "Power BI"` : le fait rejeté continuait de justifier une candidature.

---

## 10. Validation

```bash
./checklist_codex.sh                                   # → TOUT VERT
.venv/bin/python -m pytest -q tests/test_candidate_profile.py   # 58 passed
.venv/bin/python -m pytest -q                           # 1482 passed, 1 skipped
.venv/bin/python -m ruff check .                       # All checks passed
git diff --check                                       # propre
```

Détail de la suite : 39 tests de la livraison reprise + **19 tests adversariaux**
— apply réversible (6), contacts appliqués (2), honnêteté du résultat d'apply
(1), migration v10 (1), filtre de statut (1), export multi-documents (1),
provenance verbatim (2), bornage par rubrique (1), ligne partagée (1),
confiance de page (2), interface (1).

---

## 11. Limites connues et suite

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
- **Une ligne écrite à la main** qui ressemble exactement à un fait approuvé
  reste la ligne de la personne : aucune décision ne la retire.
- **SK-11 (suite)** : le profil actif est prêt à alimenter la correspondance
  fine et la justification de candidature. Le verrou posé ici (un fait non
  approuvé ne justifie rien, même après avoir été appliqué) est la condition
  d'entrée de SK-11.
- **Extensions possibles** : comparaison de deux versions d'un même CV, export
  PDF du profil portable, détection de faits contradictoires entre deux
  documents.

---

**Rapport généré le** : 2026-10-21
**Agent** : Mission CVBOOST-31 — SK-10 (worker `cvboost-31-1792617672`)
**Statut** : ✅ Complet, audité et corrigé, prêt pour relecture et intégration
