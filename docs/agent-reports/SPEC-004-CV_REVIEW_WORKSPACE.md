# SPEC-004 — Evidence-backed CV Review Workspace (CVBOOST-34)

Date : 22 octobre 2026
Branche : `worker/cvboost-34-1792639904` (worktree dédié `AI-Excel-Agent-worker-cvboost-34-1792639904`)
Base : `f5b22f2` — *merge(career): ATS diagnostics and targeted CV variants pipeline*
Aucune dépendance ajoutée, aucun schéma SQLite modifié, aucun appel réseau, aucune donnée réelle.

---

## 1. Ce qui a été construit

La mission demandait un **éditeur de révision** entre le CV source et le CV ciblé généré par
SK-11 : chaque adaptation doit être **visible** (diff phrase par phrase), **justifiée** (preuve
exacte ou placeholder explicite), **contrôlée** (accepter / modifier / refuser / revenir à la
source) et **traçable** (historique immuable).

### 1.1 `career/cv_review.py` — cœur pur (667 lignes)

Module **sans effet de bord** : ni réseau, ni disque, ni base. Il transforme des faits locaux
(profil approuvé, offre enregistrée, couverture, variante) en objets de revue.

| Élément | Rôle |
|---|---|
| `ReviewBlock` | Un bloc revu : `block_id`, `section`, `source_text`, `proposed_text`, `status`, `evidence`, `placeholder_reason`, `user_text`, `decided_at`, `decided_by` (contrat exact de la mission). |
| `ReviewWorkspace` | L'état revu d'une candidature : blocs, titres de sections ciblés, horodatages. |
| `EvidenceRef` | Une preuve : `source`, `quote`, `start_offset`, `end_offset` — les offsets pointent **les caractères exacts** de la citation dans le champ source. |
| `DiffSegment` | Un fragment de diff (`equal` / `insert` / `delete`). |
| `build_workspace(application_id, *, job, profile, variant, coverage, language, …)` | Construit le workspace depuis les faits locaux. Fonction **pure et déterministe** (test : deux constructions identiques ⇒ payload identique, entrée non mutée). |
| `diff_segments(source, proposed)` | Diff **phrase par phrase** via `difflib.SequenceMatcher` sur des jetons mots/espaces. |
| `apply_decision(workspace, block_id, status, user_text=…)` | Applique une décision et **renvoie un nouveau workspace** (le workspace d'origine n'est jamais muté). |
| `merge_decisions(workspace, stored)` | Rejoue les décisions persistées ; une décision dont le libellé a bougé est **invalidée** (le bloc repasse à `pending`). |
| `can_export(workspace) -> (bool, list[str])` | Règle de blocage export (voir §1.5). |
| `review_progress`, `status_counts`, `workspace_to_dict` | Compteurs « X/Y blocs critiques validés », badge de preuve, payload JSON. |
| `build_review_markdown(workspace, profile)` | Rend le CV revu en Markdown local (sous-ensemble inerte) pour l'export. |

Statuts implémentés (identiques au contrat) : `pending`, `verified`, `accepted`, `rejected`,
`modified`.

### 1.2 `career/cv_review_store.py` — persistance (314 lignes)

Deux artefacts, tous deux dans le répertoire **privé** `career_data/cv_review/<application_id>/` :

- `workspace.json` — l'état courant de la revue, réécrit **atomiquement** (`mkstemp` + `os.replace`),
  permissions `0600`, répertoire `0700` ;
- `history.jsonl` — le journal **immuable** des décisions : le fichier n'est **qu'ajouté**, jamais
  réécrit. Chaque ligne est un événement complet (`event_id`, `sequence`, `block_id`, `from_status`,
  `to_status`, `user_text`, `decided_at`, `decided_by`). Un test vérifie que les octets déjà écrits
  restent identiques après un nouvel événement (préfixe stable).

Sécurité : `safe_application_id()` **rejette** (au lieu de nettoyer silencieusement) tout
identifiant qui n'est pas `^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$` — aucune traversée de chemin possible
via l'URL.

### 1.3 `career/service.py` — raccords (177 lignes ajoutées)

- `self.review_store = ReviewStore(self.data_dir)` (jamais dans `data/`).
- `_cv_review_context()` : profil local + offre enregistrée + `qualify_offer` + `compute_coverage`
  + variante (celle du dernier brouillon local, sinon `classify_variant`). Aucun appel réseau.
- `_cv_review_workspace()` : reconstruit le workspace, rejoue les décisions persistées et
  n'écrit le fichier que si l'état a changé.
- `get_cv_review()`, `decide_cv_review()`, `get_cv_review_history()`, `export_cv_review()`.

### 1.4 `career/router.py` — quatre endpoints (43 lignes ajoutées)

```
GET  /api/career/cv-review/{application_id}            # workspace complet (blocs, diffs, preuves, progression, blocages)
POST /api/career/cv-review/{application_id}/decide     # {block_id, status, user_text?}
GET  /api/career/cv-review/{application_id}/history     # historique immuable
GET  /api/career/cv-review/{application_id}/export      # DOCX local, refusé (400) tant que l'export est bloqué
```

Le préfixe `/api/career` est imposé par la convention du routeur existant (tous les autres
endpoints Career l'utilisent) ; le segment `cv-review/{application_id}` est celui du contrat.

### 1.5 Règle de blocage export

`can_export()` suit le contrat de la mission :

- **bloqué** si un bloc critique (`experiences`, `skills`) est `pending` **sans preuve** ;
- **bloqué** si un placeholder critique n'est pas confirmé ;
- **ok** si les blocs critiques sont `verified` / `accepted` / `modified`.

Les raisons sont retournées et affichées dans l'interface (« Placeholder critique non confirmé :
Exigence de l'offre non étayée par le profil local : Bloomberg Terminal. »). Un bloc `pending`
**avec** preuve correspond au cas « revenir à la source » : le libellé source est rétabli, il est
donc sûr d'exporter, et le contrat n'exige pas de le bloquer.

### 1.6 Interface — `career_static/js/cv-review.js` (209 lignes)

Module local (même convention que `cv_plan.js`, chargé **avant** `career.js` en `defer`) :

- **vue split** : source à gauche, proposition à droite ;
- **diff coloré** : `cv-review-diff-equal` / `-delete` / `-insert` ;
- **boutons par bloc** : `✅ Accepter`, `✏️ Modifier`, `❌ Refuser`, `↩️ Source` ;
- **badge de preuve** : `🟢 Vérifié`, `🟡 À vérifier`, `🔴 Placeholder` (+ `✅ Accepté`, `✏️ Modifié`, `❌ Refusé`) ;
- **barre de progression** : `role="progressbar"` + `X/Y blocs critiques validés` ;
- **export DOCX** : bouton désactivé + `title` explicatif tant que `can_export` est faux ;
- **aucun dialogue natif** (`prompt`/`confirm`/`alert` interdits) : la modification se fait dans un
  `<textarea>` de la page ; **aucune URL externe** : seul l'API Career locale est appelée.

Raccords UI : nouvelle vue `view-review` (`career_static/index.html`), bouton « Reviser le CV
ciblé » sur chaque candidature, `openCvReview` / `loadCvReview` / `handleCvReviewDecision` dans
`career_static/career.js`, styles appended dans `career_static/career.css` (tokens existants
réutilisés, breakpoint `760px`).

### 1.7 Refactorisation mineure

`career/application_studio.py` : `_variant_text` devient **public** (`variant_text`) pour que le kit
ciblé et la revue partagent **une seule** règle d'adaptation locale (`modeling`/`modelling`,
`optimization`/`optimisation`). Comportement du kit inchangé (sorties DOCX identiques, vérifié par
la suite complète).

---

## 2. Règles de revue (comportement observable)

| Cas | Statut initial | Export |
|---|---|---|
| Ligne reprise mot pour mot du profil approuvé | `verified` (preuve directe, offsets exacts) | bloqué seulement si une autre ligne critique est en attente |
| Ligne réécrite par la variante (ex. `modelling` → `modeling`) | `pending` + preuve (adaptation à confirmer) | la preuve existe : elle ne bloque pas, mais la progression reste incomplète |
| Exigence de l'offre non étayée par le profil | `pending` + `placeholder_reason`, sans preuve | **bloque** si la section est critique |
| Section vide dans le profil | placeholder de section, sans preuve | bloque si la section est critique |
| `✅ Accepter` | `accepted` | le libellé proposé part dans le CV |
| `✏️ Modifier` | `modified` + `user_text` (obligatoire) | le texte écrit part dans le CV |
| `❌ Refuser` | `rejected` | le libellé **source** part dans le CV |
| `↩️ Source` | `pending` | le libellé source est rétabli, le bloc repasse en revue |

Faits d'offre qui ne sont **pas** du contenu de CV (`publication`, `début`, `fin`, `langue`,
`pays`, `ville`, `durée`, `lien officiel valide`, `date limite vérifiable`, …) ne deviennent pas
des blocs : ils suivent la candidature, pas le CV.

---

## 3. Validation

### 3.1 Tests ciblés

```
pytest -q tests/test_cv_review.py   →  20 passed
```

Couverture : construction du workspace et preuve exacte (offsets), pureté et déterminisme,
adaptation de variante, diff phrase par phrase, offsets des lignes de profil, blocage export /
déblocage, décisions (copie, validation, `user_text` obligatoire), fusion des décisions et
invalidation des décisions obsolètes, Markdown sans placeholder non confirmé, round-trip du store,
historique immuable (préfixe stable), identifiants d'application refusés, persistance après
redémarrage du service, wording manuel présent dans le DOCX exporté, les quatre endpoints HTTP
(200 / 400 / 422), rendu du module JS sous Node (vue split, diff, badges, progression, boutons,
tooltip d'export, aucun appel réseau) et gardes statiques (index.html, module local).

### 3.2 Suites automatisées

- `pytest -q` complet : **1444 passed, 1 skipped** (baseline 1424 : +20 nouveaux tests, aucune
  régression) ;
- `ruff check .` : **All checks passed** ;
- `git diff --check` : propre ;
- `./checklist_codex.sh` : **TOUT VERT** (étapes mémoire / Study Coach ignorées : worktrees absents
  de cette machine).

---

## 4. Limites honnêtes

- **`EvidenceCenter` n'existe pas encore** dans le dépôt : la preuve est portée par `EvidenceRef`,
  compatible avec le format de citation déjà utilisé (`{"source", "quote", "offset"}`) par
  `career/cv_fit` et `career/application_studio`. Brancher un EvidenceCenter ne change pas le
  contrat de la revue.
- Le DOCX exporté **reconstruit** le CV revu à partir des blocs validés : il ne réplique pas le
  doublon de section du kit M&A (le kit affichait deux fois les expériences) et il **n'exporte
  jamais** un placeholder non confirmé (la section correspondante est omise, pas laissée vide).
- La progression compte les blocs critiques `verified` / `accepted` / `modified` ; une adaptation
  en attente reste visible dans la barre de progression sans bloquer l'export, conformément au
  contrat (`pending` **sans** preuve).
- La revue porte sur les cinq sections du contrat ; la section « Certifications » du kit n'a pas de
  champ de profil dans l'application et reste hors périmètre.
- L'interface n'a pas été validée dans un navigateur réel (pas de Chrome headless sur cette
  machine) : les garde-fous JS sont exécutés sous Node avec un DOM contrôlé, comme pour
  `cv_plan.js`.

---

## 5. Fichiers

Créés :

```
career/cv_review.py
career/cv_review_store.py
career_static/js/cv-review.js
tests/test_cv_review.py
tests/fixtures/cv_review/profile.json
tests/fixtures/cv_review/offer.json
tests/fixtures/cv_review/workspace.json
docs/agent-reports/SPEC-004-CV_REVIEW_WORKSPACE.md
```

Modifiés :

```
career/service.py          # store + 4 méthodes de service
career/router.py           # 4 endpoints /api/career/cv-review/*
career/application_studio.py  # _variant_text → variant_text (règle de locale partagée)
career_static/index.html   # vue view-review + chargement du module
career_static/career.js    # openCvReview / loadCvReview / handleCvReviewDecision
career_static/career.css   # styles de la vue split
```

---

## 6. Rejeu

```bash
VENV_PY=<venv>/bin/python ./checklist_codex.sh
<venv>/bin/python -m pytest -q tests/test_cv_review.py
<venv>/bin/python -m pytest -q
<venv>/bin/python -m ruff check .
git diff --check
```
