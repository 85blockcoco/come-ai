# SPEC-SK10 — Profil candidat avec preuves approuvées

**Mission** : CVBOOST-31 — SK-10 — profil candidat structuré, contrôlé par l'utilisateur
**Branche** : `agent/spec-sk10-candidate-profile` (worktree dédié `AI-Excel-Agent-worker-cvboost-31-1792607995`)
**Base** : `main` (`f5b22f2`)
**Date** : 2026-10-21
**Auteur** : Worker Mission CVBOOST-31

---

## 1. Problème traité

Le profil Career est aujourd'hui un formulaire plat : la personne y recopie ce qu'elle veut bien
déclarer. Rien ne relie une ligne du formulaire au document qui l'a produite, et rien n'empêche
qu'une information extraite par erreur (surtout après un OCR) soit utilisée pour justifier une
candidature.

SK-10 introduit un **profil fait de faits, validés un par un**, chacun garde la preuve exacte de
sa source :

```
PDF / DOCX / TXT / texte collé
  → extraction locale (parser Mission 01)
  → OCR local si la couche de texte est absente
  → propositions de faits (compétence, expérience, diplôme, langue, date, coordonnée)
  → provenance exacte (page, offsets, citation)
  → approbation champ par champ
  → profil actif (seuls les faits approuvés)
```

**Règle centrale :** l'extraction ne décide jamais. Un fait qui n'a pas été approuvé par
l'utilisateur ne peut pas justifier une candidature.

---

## 2. Fichiers

### Créés

| Fichier | Rôle |
|---------|------|
| `career/candidate_profile.py` | Modèle pur : statuts, types de faits, provenance, transitions, fait actif, export |
| `career/profile_builder.py` | Pipeline local : lecture du document, OCR de repli, propositions avec offsets exacts |
| `career/profile_store.py` | Persistance locale (SQLite) : documents, faits, décisions de l'utilisateur |
| `career_static/js/profile-builder.js` | Interface de relecture champ par champ (approbation, correction, rejet, mise de côté, suppression, export) |
| `tests/test_candidate_profile.py` | 37 tests synthétiques (modèle, pipeline, formats réels, store, HTTP, interface) |
| `tests/fixtures/candidate_profile/cv_synthetique.txt` | CV synthétique FR (personne, sociétés, téléphones inventés) |
| `tests/fixtures/candidate_profile/cv_synthetique_en.txt` | CV synthétique EN |
| `tests/fixtures/candidate_profile/expected_facts.json` | Faits attendus des deux fixtures |
| `scripts/candidate_profile_manual_check.py` | Essai manuel sur un document réel **hors dépôt** |
| `docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md` | Ce rapport |

### Modifiés

| Fichier | Modification |
|---------|--------------|
| `career/cv_quality/parser.py` | Ajout de `ExtractedPage` et `extract_pages_from_bytes(...)` : le texte de chaque page est désormais adressable (régression : `extract_text_from_bytes` produit exactement le même texte qu'avant) |
| `career/router.py` | 11 endpoints `/api/career/profile-facts/...` + effacement du profil lors de la suppression globale des données |
| `career_static/index.html` | Chargement du script `js/profile-builder.js` (une ligne) |

`career/service.py` **n'est pas modifié** : le profil candidat vit dans ses deux propres tables,
créées à la demande (`CREATE TABLE IF NOT EXISTS`), ce qui garde SK-10 fusionnable en parallèle des
autres missions Spec Kit.

---

## 3. Le modèle (`career/candidate_profile.py`)

### 3.1 Les cinq statuts

| Statut | Sémantique | Justifiable ? |
|--------|------------|---------------|
| `proposed` | Extrait automatiquement, en attente de validation | non |
| `approved` | Validé par l'utilisateur | **oui** |
| `rejected` | Rejeté par l'utilisateur (erreur OCR, hors sujet) | non |
| `modified` | Corrigé par l'utilisateur (date, niveau de langue…) | **oui** |
| `suspended` | Mis de côté temporairement | non |

Les transitions sont explicites (`ALLOWED_TRANSITIONS`) : un fait rejeté ne revient pas directement
« approuvé », il repasse par la relecture (`proposed`). Le passage `modified` conserve la valeur
précédente (`previous_value`) et **ne touche jamais à la provenance**.

### 3.2 La provenance

```python
@dataclass(frozen=True, slots=True)
class Provenance:
    source_id: str        # document d'origine
    filename: str
    filetype: str
    page: int | None      # page 1-based, None si le format n'a pas de page
    start_offset: int     # début de la citation dans le texte du document
    end_offset: int       # fin (exclue)
    quote: str            # le passage, VERBATIM
    extraction: str       # "text_layer" | "ocr"
    source_sha256: str
```

Invariant vérifiable : `document.text[start_offset:end_offset] == quote`. Il est contrôlé par
`verify_fact()` / `verify_profile()`, qui renormalisent aussi le checksum du document d'origine.

### 3.3 Le fait actif

```python
build_justification(facts) -> {
    "justifiable": {kind: [{fact_id, label, value, status, attributes, provenance}, ...]},
    "fact_ids": [...],
    "count": n,
}
```

Seuls les faits `approved` et `modified` y figurent. C'est le contrat que **SK-11** devra consommer
à la place d'une lecture brute des faits.

---

## 4. Le pipeline (`career/profile_builder.py`)

1. **Lecture locale** : `extract_pages_from_bytes()` (parser Mission 01) donne le texte et la page
   de chaque page. Le texte complet est l'adhérence exacte des pages, séparées par une ligne vide :
   tout offset du texte complet se rattache à une page.
2. **OCR local de repli** : si la couche de texte fait moins de 120 caractères, l'OCR local est
   appelé. Le document est alors marqué `extraction="ocr"`, et les faits lus portent
   `ocr=True`. Le fournisseur d'OCR est injecté : les tests n'utilisent jamais le Vision d'Apple.
3. **Détection des rubriques** : `compétences`, `expérience`, `formation`, `langues` (et leurs
   variantes FR/EN), repérées par ligne ou en tête de ligne (`COMPETENCES : Excel, Python`).
4. **Découpage en faits** :
   - compétences : un fait par item, séparateurs `,` `;` `|` `•` ;
   - langues : `Anglais — C1` → fait « Anglais » + attribut `level=C1` ;
   - expérience / formation : un fait par ligne, plus **un fait par date** trouvée (critère 2 de la
     mission : une date garde sa source) ;
   - coordonnées : e-mail, téléphone, LinkedIn, hors rubrique.
5. **Propositions** : chaque fait est créé avec le statut `proposed` et sa provenance exacte. Rien
   n'est approuvé, jamais, à aucun moment du pipeline.

Les identifiants de faits sont déterministes (`make_fact_id` = hash du type + libellé normalisé +
document + offset) : relire le même document **repose** les mêmes faits au lieu de les dupliquer.

---

## 5. Le store local (`career/profile_store.py`)

Deux tables créées à la demande dans la base Career locale :

- `candidate_profile_documents` (document, texte, pages, extraction, checksum) ;
- `candidate_profile_facts` (fait, statut, provenance, attributs, valeur précédente).

Garanties :

- **la décision de l'utilisateur gagne** : relire un document déjà relu actualise la preuve mais ne
  touche ni au statut `approved`/`modified`, ni à la valeur corrigée ;
- `approve(..., actor="system")` sur un fait OCR lève `AutoApprovalError` : une machine ne peut pas
  approuver un fait lu par OCR ;
- `DELETE /api/career/data` (suppression globale) efface aussi le profil candidat ;
- l'export est portable : JSON (`come-candidate-profile/1`) avec les faits, leurs statuts, leur
  provenance et, en option, le texte source ; `CandidateProfile.from_dict()` relit cet export et la
  provenance reste vérifiable.

---

## 6. Les endpoints

| Méthode | Route | Rôle |
|---------|-------|------|
| `POST` | `/api/career/profile-facts/import` | Dépose un document (PDF/DOCX/TXT) → faits proposés |
| `POST` | `/api/career/profile-facts/import-text` | Dépose un texte collé → faits proposés |
| `GET` | `/api/career/profile-facts` | Tous les faits, les compteurs, les documents, le profil actif |
| `GET` | `/api/career/profile-facts/active` | **Uniquement** les faits approuvés/corrigés |
| `GET` | `/api/career/profile-facts/export` | Profil portable (JSON), `include_source=false` pour alléger |
| `POST` | `/api/career/profile-facts/{id}/approve` | Approuver un fait |
| `POST` | `/api/career/profile-facts/{id}/reject` | Rejeter un fait |
| `POST` | `/api/career/profile-facts/{id}/suspend` | Mettre un fait de côté |
| `POST` | `/api/career/profile-facts/{id}/modify` | Corriger la valeur d'un fait (source conservée) |
| `DELETE` | `/api/career/profile-facts/{id}` | Supprimer un fait |
| `DELETE` | `/api/career/profile-facts/documents/{id}` | Supprimer un document et les faits qu'il a produits |

---

## 7. L'interface (`career_static/js/profile-builder.js`)

Le script se monte dans l'onglet « Mon profil » et affiche, pour chaque fait proposé : le type, le
libellé, la valeur, **la page et la citation exacte**, le statut, et cinq actions (Approuver,
Corriger, Rejeter, Mettre de côté, Supprimer). Une section « Profil actif » ne liste que les faits
approuvés ou corrigés. L'export JSON se télécharge depuis la même section.

Le script ne décide jamais seul : il envoie une décision explicite au serveur et recharge l'état
retourné par le serveur.

---

## 8. Les critères non négociables, et où ils sont prouvés

| # | Critère | Preuve |
|---|---------|--------|
| 1 | **Résultat OCR jamais automatiquement approuvé** | `test_a_scanned_document_is_read_by_the_local_ocr_and_never_auto_approved`, `test_the_store_refuses_to_approve_an_ocr_fact_with_a_machine`, `test_an_ocr_fact_can_only_be_approved_by_a_user` (le modèle lève `AutoApprovalError`) |
| 2 | **Chaque compétence, expérience, date, diplôme garde sa source** | `test_every_fact_keeps_the_exact_passage_it_comes_from` (offsets + citation + page), `test_a_pdf_keeps_the_page_of_every_fact`, `test_the_expected_facts_are_proposed_for_both_synthetic_documents` (dates comprises) |
| 3 | **Suppression et export fonctionnent** | `test_deleting_a_fact_disappears_from_the_active_profile`, `test_deleting_a_document_deletes_the_facts_it_produced`, `test_the_export_is_portable_and_keeps_the_provenance`, `test_deleting_a_fact_and_a_document_works`, `test_the_export_endpoint_returns_the_portable_profile` |
| 4 | **Aucun document réel dans les tests** | fixtures 100 % synthétiques (`Camille Exemple`, `Groupe Fictif`, `Université Fictive`, adresses `@example.test`) ; le script manuel **refuse** de lire un fichier situé dans le dépôt |
| 5 | **Faits non approuvés ≠ justifier une candidature** | `test_only_approved_and_modified_facts_are_justifiable`, `test_justification_only_contains_the_facts_the_user_approved`, `test_importing_a_text_proposes_facts_without_approving_any` (`active.count == 0`), `test_rejecting_and_suspending_a_fact_keeps_it_out_of_the_active_profile` |
| 6 | **Vrais essais utilisateur séparés des fixtures Git** | `scripts/candidate_profile_manual_check.py` : lit un document réel **hors dépôt**, n'écrit rien, n'approuve rien, refuse un fichier du dépôt (protocole au § 11) |

---

## 9. Validation

| Commande | Résultat |
|----------|----------|
| `./checklist_codex.sh` | **TOUT VERT** (seules alertes : worktrees mémoire / study-coach absents du worktree dédié) |
| `.venv/bin/python -m pytest -q tests/test_candidate_profile.py` | **37 passed** |
| `.venv/bin/python -m pytest -q tests/test_cv_quality_structure.py` | **39 passed** (aucune régression du parser) |
| `.venv/bin/python -m pytest -q` (suite complète) | **1461 passed, 1 skipped** (base 1424 + 37 nouveaux) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `git diff --check` | propre |
| Clone frais du commit poussé | **1461 passed, 1 skipped** |

> Le worktree n'a pas de `.venv` propre : la validation utilise le Python du dépôt principal
> (`/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python`), en pointant sur le code du worktree
> (`sys.path[0]` = racine du worktree, vérifié par `career.__file__`).

---

## 10. Hors périmètre (assumé, et pourquoi)

- **Aucun changement de `career/service.py`** : pas de migration du schéma applicatif, pas de
  nouvelle colonne dans `candidate_profile`. Le profil candidat a ses propres tables, ce qui garde
  la mission fusionnable en parallèle de SK-01 → SK-09.
- **Aucun branchement du profil actif au matching ni à la candidature** : c'est la mission SK-11.
  SK-10 livre le contrat (`GET /api/career/profile-facts/active` et `build_justification()`) ; les
  écrans de matching continuent d'utiliser le formulaire de profil tant que SK-11 n'est pas
  intégré. C'est un choix explicite : brancher le matching ici aurait fait dépendre les offres
  d'un module en cours de revue.
- **Le formulaire de profil existant n'est pas remplacé** : il reste l'affichage « profil » de
  l'application. La section de relecture s'ajoute à côté.
- **L'OCR n'est testé qu'avec un fournisseur injecté** : le Vision d'Apple exige un PDF réel et
  les outils de ligne de commande ; le contrat (jamais auto-approuvé, provenance, page inconnue)
  est lui entièrement testé.

---

## 11. Essais utilisateur réels (hors Git)

Les fixtures Git ne contiennent que des données synthétiques. Pour un vrai CV, hors dépôt :

```bash
# 1. Copier le CV hors du dépôt
cp ~/Documents/mon-cv.pdf ~/Documents/essais-cv/

# 2. Lire localement et voir ce qui serait proposé (rien n'est écrit, rien n'est approuvé)
.venv/bin/python scripts/candidate_profile_manual_check.py ~/Documents/essais-cv/mon-cv.pdf

# 3. Dans l'application : Mon profil → section « Profil candidat — relecture champ par champ »
#    Importer le document, puis approuver / corriger / rejeter chaque fait.
# 4. Exporter : « Exporter le profil (JSON) » → le JSON contient chaque fait, son statut et sa
#    provenance (page + citation). C'est le fichier à relire avant toute candidature.
```

Le script refuse un fichier situé dans le dépôt : un document réel ne doit jamais y entrer.

---

## 12. Ce que SK-11 devra consommer

```python
from career.candidate_profile import build_justification

justification = build_justification(store.active_facts())
# justification["justifiable"]["skill"] → uniquement des faits approuvés
# justification["justifiable"]["experience"] → idem
```

Règle à reprendre tel quel côté matching / candidature : **un fait `proposed`, `rejected` ou
`suspended` ne peut pas être cité comme preuve**. Si l'offre exige une compétence absente du profil
actif, la réponse honnête est « à vérifier », pas une compétence inventée.
