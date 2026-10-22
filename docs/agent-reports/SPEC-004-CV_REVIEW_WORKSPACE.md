# SPEC-004 — Espace de revue du CV ciblé (preuve, décision, traçabilité)

Date : 22 octobre 2026
Branche : `worker/cvboost-34-1792629155` (mission CVBOOST-34)
Base : `f5b22f2a55b7594fe487f703f8ca8c397c6e6345` (`merge(career): ATS diagnostics and targeted CV
variants pipeline`)

Réseau : aucun. Modèle : aucun. Données réelles : aucune (fixtures synthétiques). Schéma SQLite :
inchangé. Dépendances : inchangées.

---

## 1. Ce qui a été construit

### 1.1 `career/cv_review.py` — cœur pur (932 lignes)

Module **100 % déterministe, sans effet de bord** : ni réseau, ni modèle, ni fichier, ni horloge
(le temps est injecté par l'appelant). Il porte le contrat de la mission.

**Contrat (aligné sur la spec de la mission)**

```python
@dataclass(frozen=True, slots=True)
class ReviewBlock:
    block_id: str
    section: Literal["experiences", "skills", "education", "projects", "languages"]
    source_text: str
    proposed_text: str
    status: Literal["pending", "accepted", "rejected", "modified", "verified"]
    evidence: list[EvidenceRef] | None
    placeholder_reason: str | None
    user_text: str | None
    decided_at: str | None
    decided_by: str
    # champs ajoutés, non contractuels mais nécessaires à l'UI
    heading: str = ""
    section_headings: tuple[str, ...] = ()
    critical: bool = False
    diff: list[DiffSegment] = field(default_factory=list)
```

`EvidenceRef` porte la preuve exacte : `source` (où vit la citation), `quote` (extrait verbatim),
`offset` + `length` (offsets caractère dans le texte source), `kind` (`"source"` = la proposition
est dans la source revu, `"profile"` = la proposition est issue du profil approuvé) et `label`
(origine lisible).

**Construction du workspace**

```python
workspace = build_workspace(
    application_id,
    language=..., variant=...,
    sources=sources,        # {section canonique -> SourceSection}
    proposals=proposals,    # {section canonique -> ProposedSection}
    profile=profile_fields, # pour la provenance
    source_document=..., saved=..., now=...,
)
```

`build_workspace` est **pure** : mêmes entrées ⇒ même sortie (test de déterminisme). Elle produit
un bloc par section canonique (`experiences`, `skills`, `education`, `projects`, `languages`),
dans l'ordre stable `REVIEW_SECTIONS`.

**Diff phrase par phrase** — `difflib.SequenceMatcher` sur des phrases obtenues par
`split_phrases()` :

- découpage sur les fins de phrase **suivies d'une espace** (un `20.5 %` n'est jamais coupé) ;
- découpage additionnel sur le séparateur de champ `|` de la convention CV
  (`2025 | Analyste | Banque Démo`), le séparateur restant attaché au champ qu'il clôt ;
- sortie : `DiffSegment(op="equal" | "insert" | "delete", text=...)`.

**Preuve : ce qui est réellement vérifiable**

Une proposition n'est marquée `verified` (preuve directe ⇒ acceptée automatiquement) que si :

1. chaque paragraphe a une **ligne d'origine** dans le profil approuvé (un gap de preuve n'a
   pas d'origine : il n'est jamais « vérifié ») ;
2. le paragraphe **n'ajoute aucun mot** absent de sa ligne d'origine (comparaison par jetons,
   `modeling`/`modelling` repliés comme le même mot) ;
3. la ligne d'origine est **localisée dans le texte source revu** — la citation est donc un
   extrait réel, avec ses offsets exacts.

Sinon le bloc reste `pending` : il attend une décision humaine.

**Décisions** — `decide_block(workspace, block_id, status, user_text=..., now=...)` renvoie un
**nouveau** workspace (immuabilité) :

| Statut | Effet | Texte exporté |
|---|---|---|
| `pending` | rouvrir le bloc | — (relecture) |
| `verified` | accordé par leconstructeur quand la preuve est directe | proposition |
| `accepted` | validé par l'utilisateur | proposition |
| `rejected` | refusé | **texte source** |
| `modified` | réécrit par l'utilisateur | **texte de l'utilisateur** |

Un texte `modified` qui contient encore un marqueur entre crochets est **refusé** : on ne peut pas
valider une preuve manquante.

**Règle de blocage de l'export** — `can_export(workspace) -> (bool, list[str])` :

- **bloqué** si un bloc critique (`experiences`, `skills`) est `pending` — message distinct si le
  bloc porte un placeholder (« Placeholder critique non confirmé ») ;
- **bloqué** si un placeholder critique n'est pas confirmé ;
- **jamais bloqué** par un bloc critique `rejected` : le bloc retombe sur le texte source de
  l'utilisateur, il ne reste donc aucune affirmation non prouvée ;
- les placeholders des sections **non critiques** ne bloquent pas l'export (rèle de la spec) mais
  sont remontés en `warnings` : l'UI les affiche, l'export n'est pas bloqué.

**Rendu de l'export** — `render_export_markdown()` produit le petit sous-ensemble Markdown
exportable (`#`, `##`, `-`), en utilisant le **texte effectif** de chaque bloc (proposition,
source ou texte utilisateur).

### 1.2 `career/cv_review_store.py` — persistance locale (141 lignes)

Deux fichiers par candidature, dans `career_data/cv_review/` :

- `<application>.json` — le workspace courant, écrit **atomiquement** (fichier temporaire dans le
  même dossier, `fsync`, `os.replace`, permissions `0600`) : un crash ne tronque jamais le
  workspace ;
- `<application>.history.jsonl` — le **journal immuable** des décisions, en ajout seul
  (`append` + `\n`). Une entrée n'est jamais réécrite ni supprimée.

### 1.3 `career/router.py` — quatre endpoints (locaux, sans envoi)

```
GET  /api/career/cv-review/{application_id}            # workspace complet
POST /api/career/cv-review/{application_id}/decide     # {block_id, status, user_text?}
GET  /api/career/cv-review/{application_id}/history    # journal immuable
GET  /api/career/cv-review/{application_id}/export     # DOCX, seulement si can_export=True
```

Conventions du dépôt respectées : factory `create_career_router(service)`, exécution dans un
`run_in_threadpool` puis `to_jsonable`, erreurs métier via `UserFacingError` (HTTP 400),
validation de payload via Pydantic (`status` contraint par motif), téléchargement via
`FileResponse` avec `Cache-Control: no-store`. Le préfixe `/api/career` suit la convention du
workspace (la spec indiquait `/cv-review/...`).

**Garde-fou** : aucune route ne contient `send`, `mail`, `smtp`, `transmit` ou `auto-submit`
(test statique dans `tests/test_cv_review.py`).

### 1.4 `career/service.py` —Branchement local

- `_current_cv_document()` : dernier CV importé (texte + nom de fichier).
- `_cv_review_context()` : profil, offre, couverture et écarts, calculés **en local** à partir des
  faits enregistrés (`compute_coverage` + `generate_diff`).
- `_cv_review_sources()` : **le document importé EST la source revue** quand il existe — l'utilisateur
  compare le CV ciblé avec le CV qu'il envoie vraiment. Une section absente du document est revue
  avec une source vide : les mots ajoutés par la proposition sont donc visibles et doivent être
  acceptés. Sans document importé, la source est le champ de profil approuvé.
- `_cv_review_proposals()` : la proposition vient de `build_targeted_sections()` (voir §2), plus
  les écarts de preuve non couverts, redistribués dans la section où ils atterrissent.
- `_cv_review_sync()` : reconstruit, **rejoue** les décisions explicites, rouvre les blocs dont le
  contenu a changé (avec une entrée `reopened` dans l'historique) et persiste.
- `cv_review_workspace()`, `decide_cv_review()`, `cv_review_history()`, `export_cv_review()`.

### 1.5 `career_static/js/cv-review.js` + `career_static/cv_review.css` (450 + 287 lignes)

Module autonome, chargé en `defer` **avant** `career.js`. Il n'appelle que les endpoints Career
locaux.

- **Vue split** : source à gauche, proposition à droite, une colonne par bloc.
- **Diff coloré** : `equal` / `insert` (vert) / `delete` (rouge barré).
- **Boutons par bloc** : `✅ Accepter` · `✏️ Modifier` (éditeur **en ligne**, jamais
  `window.prompt`) · `❌ Refuser` (le bloc retombe sur la source) · `↩️ Source` (**rouvre** le bloc :
  la décision est annulée, la source reste affichée).
- **Badge de preuve** : `🟢 Vérifié` · `🟡 À vérifier` · `🔴 Placeholder`, plus le statut et la
  mention « Bloc critique ».
- **Preuve** : citation verbatim, origine et offsets (`offset 123 · longueur 42`) pour chaque
  `EvidenceRef`.
- **Barre de progression** : `X/Y blocs critiques validés` (`role="progressbar"`, `aria-valuenow`).
- **Export DOCX** : bouton désactivé quand `can_export=false`, avec un `title` explicatif listant
  les raisons du blocage.
- **Aucune invention** : aucun `mailto:`, aucun `smtp`, aucun envoi, aucune donnée réelle.

`career_static/index.html` : un panneau « Revue du CV ciblé » dans la vue Candidatures (sélecteur de
candidature, progression, raisons, blocs, export) + la feuille `cv_review.css` + le script
`/career-static/js/cv-review.js`.

---

## 2. Une seule source de vérité pour la proposition

`career/application_studio.py` expose désormais **`build_targeted_sections(profile=..., variant=...)`**,
fonction pure qui rend les sections du CV ciblé et **conserve, pour chaque paragraphe, la ligne de
profil dont il est issu** (`source_line`) — l'ancrage qui sert ensuite de preuve.

`generate_application_kit()` a été refactorée pour consommer cette fonction : il n'y a plus deux
copies de la logique de rendu.

**Vérification d'absence de régression, faite par comparaison d'octets** : le `cv.docx` et le
`cover_letter.docx` générés par le code d'origine (`git archive HEAD`) et par le code refactorisé
ont **exactement le même SHA-256** :

```
cover_letter.docx 724ca446fb177058c4779a67…  (identique avant / après)
cv.docx          4f2dd7c37c26af9a617e06a3…  (identique avant / après)
```

(`prep_sheet.md` diffère uniquement par son horodatage `**Generated**`, qui change entre deux
exécutions du code d'origine lui aussi.)

---

## 3. Tests

`tests/test_cv_review.py` — **51 tests** (tous verts), fixtures synthétiques dans
`tests/fixtures/cv_review/` (`candidate_profile.json`, `offer.json`, `source_cv.txt`).

| Famille | Couverture |
|---|---|
| Diff | phrase par phrase, décimales intactes, séparateur `|`, égal/insert/delete |
| Preuve | offsets exacts, insensibilité à la casse et aux espaces, marqueurs détectés |
| Workspace | pureté et déterminisme, un bloc par section, `verified` / `pending`, rejoue une décision, rouvre un bloc dont le contenu a changé, proposition qui ajoute un mot jamais vérifiée |
| Décisions | accept / reject / modify, texte effectif, refus d'un `modified` avec placeholder, bloc et statut inconnus refusés |
| Export | blocage par bloc critique en attente, blocage par placeholder critique, déblocage par acceptation, refus jamais bloquant, workspace vide bloqué, markdown d'export |
| Persistance | aller-retour workspace, historique **ajout seul**, historique cloisonné par candidature |
| Service | workspace réel, décision persistée, décision conservée entre deux lectures, refus explicites, export bloqué / autorisé, document importé = source revue |
| HTTP | workspace, decide, history, export (200 + 400), statut invalide (422), candidature inconnue (400) |
| Garde-fous statiques | 4 routes enregistrées, aucune route d'envoi, contrat UI, aucun `window.prompt` / `mailto:` / `smtp` |

### Validation globale

```bash
./checklist_codex.sh                                  # → TOUT VERT
.venv/bin/python -m pytest -q tests/test_cv_review.py # → 51 passed
.venv/bin/python -m pytest -q                         # → 1475 passed, 1 skipped
.venv/bin/python -m ruff check .                      # → All checks passed!
git diff --check                                       # → propre
```

Le `1 skipped` (`tests/test_offer_summary_exhaustiveness.py`) est préexistant : il exige un
script ou une base absents de cet environnement.

---

## 4. Écarts assumés et limites

1. **Sections du contrat.** La spec limite `section` à cinq valeurs. Les variantes M&A
   comportent deux rubriques d'expérience (`Professional Experience` + `Transaction Experience`) et
   une rubrique `Certifications`. Elles sont **fusionnées** dans un seul bloc
   `experiences` (paragraphes dédupliqués) et `Certifications` est **exclue** du workspace (le
   champ `certifications` n'existe pas dans le profil : la rubrique est toujours vide dans le kit
   ciblé). Le contenu est identique, la relecture est faite une seule fois.
2. **Statut `rejected` et export.** La spec liste « verified / accepted / modified » comme
   condition suffisante. Un bloc `rejected` n'est **pas** traité comme bloquant : il retombe sur
   le texte source de l'utilisateur, donc il ne laisse aucune affirmation non prouvée. Refuser un
   bloc ne peut pas rendre l'export impossible.
3. **Le quatrième bouton.** « Refuser » et « Revenir au source » ne peuvent pas faire la même
   chose. « ❌ Refuser » passe le bloc à `rejected` (l'export garde la source) ; « ↩️ Source »
   **rouvre** le bloc (`pending`, décision annulée, trace conservée dans l'historique).
4. **En-tête de l'export.** Le nom, les contacts et la ligne de ciblage proviennent du profil
   approuvé ; ils ne sont pas des blocs revus (le contrat ne couvre que les cinq sections de
   contenu). Ils sont affichés tels quels dans le DOCX exporté.
5. **`EvidenceCenter`.** Le dépôt n'a pas d'`EvidenceCenter` : `EvidenceRef` est donc le type de
   référence de preuve local, avec `source` / `quote` / `offset` / `length`, prêt à pointer vers un
   centre de preuve futur sans changer le contrat du workspace.
6. **Placeholders hors sections critiques.** Ils ne bloquent pas l'export (règle de la spec) mais
   produisent un `warning` explicite affiché dans l'UI.

---

## 5. Fichiers touchés

**Nouveaux**

- `career/cv_review.py`
- `career/cv_review_store.py`
- `career_static/js/cv-review.js`
- `career_static/cv_review.css`
- `tests/test_cv_review.py`
- `tests/fixtures/cv_review/candidate_profile.json`
- `tests/fixtures/cv_review/offer.json`
- `tests/fixtures/cv_review/source_cv.txt`
- `docs/agent-reports/SPEC-004-CV_REVIEW_WORKSPACE.md`

**Modifiés**

- `career/application_studio.py` — `build_targeted_sections()` + `TargetedSection` /
  `TargetedParagraph`, `generate_application_kit()` refactorée (sortie DOCX inchangée, vérifié par
  SHA-256), marqueur `EVIDENCE_PLACEHOLDER` centralisé.
- `career/models.py` — constante partagée `EVIDENCE_PLACEHOLDER`.
- `career/service.py` — 6 méthodes privées + 4 méthodes publiques de la revue.
- `career/router.py` — payload Pydantic + 4 endpoints.
- `career_static/index.html` — panneau de revue, feuille de style, script.
