# SPEC-004 — Espace de revue du CV ciblé (preuve, décision, export verrouillé)

Date : 22 octobre 2026
Branche : `worker/cvboost-34-1792632692` (base `f5b22f2`)
Mission : CVBOOST-34 — SPEC-004 « Evidence-backed CV Review Workspace »
Aucune dépendance ajoutée, aucun schéma SQLite modifié, aucune donnée réelle, aucun appel réseau.

## 1. Le problème que la mission règle

Le générateur de CV ciblé existe (`career/application_studio.py`, `generate_application_kit`) :
il écrit un DOCX, une lettre et une fiche de préparation dans `output/career/kits/…`. Mais trois
choses manquaient :

1. **rien n'était visible** — la personne ne pouvait pas lire ce que le générateur avait changé
   par rapport à son CV ;
2. **rien n'était justifié** — les citations existaient dans `provenance_map`, mais elles
   n'étaient ni normalisées ni rattachées à une ligne ;
3. **rien n'était contrôlé** — le DOCX généré partait sans que personne ait pu refuser une
   reformulation ou remplacer un placeholder par une preuve.

Le module livré est un **éditeur de révision** : chaque adaptation devient un bloc reviewable,
avec sa formulation source, sa formulation proposée, sa preuve locale, son statut et son
historique. L'export DOCX est conditionné à la fin de cette revue.

## 2. Ce qui a été construit

### 2.1 `career/cv_review.py` — le cœur pur (884 lignes)

Module **sans effet de bord** : ni horloge, ni disque, ni réseau, ni aléa. L'horodatage et
l'identifiant sont injectés par l'appelant, donc deux entrées identiques produisent toujours le
même workspace, bloc par bloc.

| Symbole | Rôle |
|---|---|
| `EvidenceRef` | citation normalisée : `source` (champ local), `quote` (extrait verbatim), `offset` (position dans le champ) |
| `ReviewBlock` | un bloc reviewable : `block_id`, `section`, `source_text`, `proposed_text`, `status`, `evidence`, `placeholder_reason`, `user_text`, `decided_at`, `decided_by` (+ `heading`, `index`, `label` ajoutés) |
| `ReviewWorkspace` | l'état complet d'une candidature : blocs, en-tête, variant, langue, source, blocs invalidés |
| `ReviewEvent` | une entrée d'historique immuable |
| `DiffSegment` | un fragment du diff mot à mot |
| `build_workspace(application_id, *, job, job_id, variant, language, profile, coverage, created_at, source_document)` | **pur** : construit le workspace à partir de l'offre, du profil, de la variante et de la couverture |
| `diff_segments(source, proposed)` | diff **mot à mot** via `difflib.SequenceMatcher` (plus fin que la phrase) |
| `effective_text(block)` | la formulation qui part dans l'export |
| `can_export(workspace)` | `(bool, list[str])` : la porte de sortie |
| `apply_decision(workspace, block_id, status, *, user_text, decided_at, decided_by)` | **pur** : renvoie un nouveau workspace, ne mute jamais l'entrée |
| `merge_decisions(fresh, saved)` | rejoue les décisions enregistrées sur un workspace reconstruit |
| `replay_events(fresh, events)` | rejoue l'**historique immuable** : l'état perdu se reconstruit |
| `review_progress(workspace)` | compteurs de progression (X/Y blocs critiques validés) |
| `render_workspace_markdown(workspace)` | le CV revu, en Markdown (sous-ensemble accepté par `write_docx`) |
| `serialize_workspace` / `serialize_block` | vues JSON de l'API |

### 2.2 `career/cv_review_store.py` — persistance locale (329 lignes)

Deux fichiers privés par **clé de revue** (une candidature **et** une variante de CV), dans
`career_data/cv_review/` (hors de `data/`, donc invisibles pour l'agent d'analyse documentaire) :

- `<application_id>.<variant>.json` — l'instantané d'état ;
- `<application_id>.<variant>.history.jsonl` — l'**historique immuable** : une ligne JSON par
  décision, ouverte en ajout seul (`"a"`), `flush` + `fsync`, jamais réécrite.

La variante fait partie de la clé **à dessein** : deux variantes de la même offre proposent des
formulations différentes (en-GB contre en-US), une décision prise sur l'une ne doit jamais être
rejouée sur l'autre.

Points de sûreté :

- l'identifiant de candidature vient d'une URL : il est validé (`[A-Za-z0-9_-]{1,80}`) **avant**
  tout accès disque — pas de traversée de chemin ;
- écriture atomique (`mkstemp` + `os.replace`) et permissions `0600` ;
- l'identifiant, le format du fichier et les décisions sont rejouables : le format
  `career-cv-review/1` est écrit dans chaque état, et un fichier illisible est ignoré plutôt
  que d'être interprété — l'historique prend alors le relais (voir §3.6) ;
- l'export de données personnelles ignore les fichiers temporaires et les fichiers étrangers
  au lieu d'échouer.

### 2.3 `career/service.py` — 4 méthodes (additives, aucun changement de schéma)

| Méthode | Rôle |
|---|---|
| `get_cv_review_workspace(application_id, language, variant)` | reconstruit le workspace et rejoue les décisions |
| `decide_cv_review_block(application_id, block_id, status, user_text, language, variant, reviewed_text)` | enregistre la décision, append l'historique, trace l'audit |
| `cv_review_history(application_id, variant)` | l'historique complet de la variante, dans l'ordre |
| `export_cv_review(application_id, language, variant)` | DOCX **ou refus explicite** |

Deux helpers privés complètent le lot : `_cv_review_variant` (variante demandée → dernière variante
utilisée → variante conseillée) et `_cv_review_source_document` (nom du CV importé dont le profil
est issu, pour la traçabilité).

Le stockage passe par `application_events` ? **Non** : `detail` y est tronqué à 1000 caractères,
ce qui ne convient pas à un payload de revue. Le workspace est donc un fichier JSON dédié dans
`career_data/cv_review/`, ce qui laisse `applications`, `application_events` et
`application_drafts` **strictement inchangés** (le test de garde de schéma de
`tests/test_career_application_kit.py` reste vert).

### 2.4 `career/router.py` — 4 endpoints

```
GET  /api/career/applications/{application_id}/cv-review            → workspace complet
POST /api/career/applications/{application_id}/cv-review/decide     → {block_id, status, user_text?, reviewed_text?}
GET  /api/career/applications/{application_id}/cv-review/history    → historique des décisions
GET  /api/career/applications/{application_id}/cv-review/export     → DOCX (400 si bloqué)
```

Les trois routes de lecture et la route de décision acceptent `?language=` et `?variant=` : la
décision porte toujours sur **la variante affichée**. Le corps de la décision peut en outre
porter `reviewed_text` (la formulation qui a été lue) : si la proposition a changé depuis la
lecture, l'API refuse la décision au lieu d'appliquer un accord à un texte jamais vu.

Le préfixe `/api/career` et la forme `/applications/{application_id}/…` suivent la convention du
module (le mission note `GET /cv-review/{application_id}` ; la convention du dépôt a été
préférée pour ne pas créer une seconde famille de routes). Le `status` est validé par motif
pydantic (`pending|accepted|rejected|modified`) : `verified` est réservé au système, une
erreur de validation répond 422, une erreur métier 400.

Aucune de ces routes n'envoie quoi que ce soit (aucune importation réseau, aucun `smtplib`).

### 2.5 `career_static/js/cv-review.js` + `career_static/css/cv-review.css` — l'interface

Vue ligne par ligne, entièrement locale, sans `innerHTML` (tout passe par `textContent`) :

- **vue split** : source à gauche, proposition à droite, diff coloré (ajout en vert, suppression
  barrée en rouge) ;
- **quatre décisions par bloc** : ✅ Accepter · ✏️ Modifier (éditeur en ligne, pas de
  `window.prompt`) · ❌ Refuser · ↩️ Source ;
- **badge de preuve** : 🟢 Vérifié · 🟡 À vérifier · 🔴 Placeholder ;
- **barre de progression** : « X/Y blocs critiques validés » ;
- **en-tête du CV affiché** : il part dans l'export, il est donc visible (et signalé s'il porte
  encore un marqueur de preuve) ;
- **export DOCX** : bouton désactivé quand `can_export` est faux, `title` explicatif listant les
  raisons du blocage ;
- **histoire des décisions** : déroulant listant chaque décision (bloc, transition, horodatage) ;
- **la variante affichée est la variante décidée** : les appels de décision, d'historique et
  d'export portent le `variant_id` reçu du serveur, jamais celui d'une autre variante.

Intégration : `career.js` insère le panneau à la fin du kit de candidature, derrière un garde
`typeof renderCvReviewSection === "function"` — si le module n'est pas chargé, le kit reste
utilisable tel quel. `index.html` charge `js/cv-review.js` et `css/cv-review.css` (chemins
donnés par la mission).

### 2.6 `career/application_studio.py` — un plan partagé, plus deux EXTRActions

Le générateur et la revue ne doivent pas pouvoir diverger : la revue doit montrer **exactement**
les lignes qui seront exportées. Le contenu du CV ciblé a donc été extrait dans un **plan pur** :

```python
plan_kit_sections(profile, variant) -> list[KitSection]   # titres, champ source, lignes, rendu
plan_kit_summary(job, profile, variant) -> KitSummary       # résumé professionnel
plan_kit_gaps(coverage) -> list[KitGap]                     # exigences sans preuve
```

`generate_application_kit` écrit ce plan, la revue le lit. Le DOCX produit est **inchangé**
(tests de contrat `tests/contract/test_kit_generation.py` et `tests/test_career_application_kit.py`
verts, y compris le test d'idempotence byte-for-byte).

## 3. Le modèle de décision

### 3.1 Les statuts

| Statut | Signification | Origine |
|---|---|---|
| `pending` | en attente de décision | état initial d'un bloc non vérifié |
| `verified` | preuve directe → accepté automatiquement | bloc dont la proposition **n'est que la re-spellisation locale** d'une ligne de profil prouvée (en-GB ↔ en-US) |
| `accepted` | validé par la personne | bouton ✅ |
| `modified` | réécrit par la personne | bouton ✏️ (le texte replaced est obligatoire) |
| `rejected` | adaptation refusée → la **source** est exportée | bouton ❌ |

`↩️ Source` remet le bloc en `pending` : la formulation source est de nouveau affichée et le bloc
retombe dans la file des décisions à trancher.

### 3.2 Ce qui part dans l'export

```python
effective_text(block) =
    user_text          si status == "modified"
    proposed_text      si status in ("accepted", "verified")
    source_text        sinon (pending, rejected)
```

Conséquence directe : **une proposition non relue ne peut pas atteindre le document**. Un bloc
`pending` ou `rejected` exporte la formulation source, jamais l'adaptation.

### 3.3 La porte de sortie (`can_export`)

```python
def can_export(workspace) -> tuple[bool, list[str]]:
    # BLOQUÉ si : le workspace ne contient aucune proposition
    # BLOQUÉ si : un bloc critique est encore "pending"
    # BLOQUÉ si : le texte qui partirait contient encore un marqueur de preuve
    #              (blocs ET en-tête du CV : nom, coordonnées, formation)
    # OK si : tous les blocs critiques sont verified / accepted / modified / rejected
```

Les sections critiques sont `experiences` et `skills` (celles de la mission). Les marqueurs de
preuve sont détectés par un motif qui exige **au moins une lettre** dans les crochets :
`[AJOUTER PREUVE CHIFFRÉE]`, `[SKILLS TO CONFIRM]`, `[À CONFIRMER]` sont des placeholders ;
`[2024]` est une date et ne bloque rien.

**Deux écarts assumés par rapport à la lettre du contrat**, documentés ici et dans le module :

1. le contrat écrit « BLOQUÉ si : blocs critiques en pending **sans preuve** ». La règle
   implémentée bloque **tout** bloc critique `pending`, preuve ou non. Raison : une preuve ne
   remplace pas la décision — le résumé professionnel et les exigences sans preuve sont des
   formulations que la personne doit trancher. Le cas « pending **avec** preuve » ne survit pas
   à la construction : un bloc porteur d'une preuve directe et dont la proposition n'est que la
   re-spellisation locale est `verified` dès la construction ; seuls le résumé (mélange de
   l'offre et du profil) et les placeholders restent `pending`.
2. le contrat écrit « OK si : tous blocs critiques sont verified/accepted/modified » et ne cite
   pas `rejected`. La règle implémentée considère `rejected` comme **tranché** (le statut est
   défini par le contrat lui-même comme « revient à la source ») : refuser une adaptation ne
   peut pas rendre le CV exportable définitivement, sinon l'export serait bloqué à vie. Un bloc
   `rejected` exporte la source, donc aucune adaptation non relue n'atteint le document.

### 3.4 La preuve

Le dépôt contenait **trois formes de preuve incompatibles** (`EvidenceCitation` en dict dans
`cv_fit.py`, `Provenance` en dataclass dans `cv_quality/models.py`, `FactEvidence` dans
`offer_qualification.py`). Le module en introduit une **quatrième, normalisée** : `EvidenceRef`
(source, quote, offset), celle que la mission nomme « refs vers EvidenceCenter ».

- `source` : le champ local d'origine (`profile.experience`, `profile.skills`, …) ;
- `quote` : l'extrait **verbatim** ;
- `offset` : la position de cet extrait dans le champ (recalculée à la construction, donc
  vérifiable par la personne).

Un bloc sans preuve n'est jamais comblé : il devient un **placeholder** avec un motif explicite
(« Aucune ligne enregistrée dans le profil pour la section « X ». », « Exigence mandatory sans
preuve dans le profil : « … ». »).

### 3.5 Le diff

`difflib.SequenceMatcher` sur les **mots** (chaque mot garde son espace final) : la personne voit
le fragment exact qui change (« financial modeling » → « financial modelling ») et non une
remplacement de ligne entière. L'API renvoie la liste des segments ; le JS construit le DOM
jamais à partir d'une chaîne HTML.

### 3.6 La décision et sa rejouabilité

La proposition est **reconstruite** à chaque lecture à partir de l'offre, du profil et de la
variante du moment ; les décisions enregistrées sont ensuite rejouées par-dessus. Une décision
n'est rejouée **que si la formulation proposée n'a pas changé** : sinon le bloc repasse `pending`
et il est listé dans `invalidated_blocks`. Une décision porte donc toujours sur le texte exact
qui a été lu.

Trois garde-fous complètent le dispositif :

1. **la clé de stockage inclut la variante** : les décisions d'une variante ne sont jamais
   rejouées sur une autre ;
2. **l'historique fait foi** : la décision est ajoutée à l'historique immuable, puis l'instantané
   d'état est écrit. Si l'instantané échoue, la décision reste effective (elle est rejouée depuis
   l'historique) et un avertissement le signale ; à l'inverse, un instantané périmé ne peut
   jamais cacher une décision, car la lecture rejoue l'historique ;
3. **le corps de la décision porte le texte lu** (`reviewed_text`) : si la proposition a changé
   entre la lecture et le clic, l'API refuse la décision.

Le cycle complet (lecture du workspace, application de la décision, écriture de l'historique et de
l'instantané) se déroule **sous le verrou du service** : deux décisions simultanées ne peuvent
pas s'écraser l'une l'autre.

## 4. Le parcours de bout en bout

1. `POST /api/career/application-kits` ouvre le kit et le suivi (inchangé).
2. `GET …/cv-review` renvoie le workspace : 15 blocs pour une offre de démonstration (résumé,
   2×2 lignes d'expérience, formation, compétences, projets vide, langues, certifications vide,
   5 exigences sans preuve).
3. La personne tranche : `POST …/cv-review/decide` avec `{block_id, status, user_text?,
   reviewed_text?}` et les paramètres `?variant=` / `?language=` de la variante affichée.
4. Chaque décision est **append** dans l'historique immuable (`from_status`, `to_status`, texte,
   horodatage, séquence, variante, texte lu).
5. `GET …/cv-review/export` renvoie le DOCX **si et seulement si** `can_export` est vrai ; sinon
   l'API répond 400 avec la liste des raisons.

Vérifié sur une candidature de démonstration :

```
blocage   → Export bloqué tant que la revue n'est pas terminée : « Exigence : Expérience » …
autorisé  → can_export: True, 8/8 blocs critiques validés
DOCX      → 37 Ko, contient le résumé validé et la preuve ajoutée,
            aucun marqueur « AJOUTER PREUVE »
```

## 5. Tests

`tests/test_cv_review.py` — **42 tests**, tous synthétiques, tous hors ligne :

| Famille | Ce qui est vérifié |
|---|---|
| construction pure | déterminisme, absence d'écriture disque, preuve verbatim + offset exact, placeholder ≠ invention, `verified` pour la re-spellisation locale |
| diff | fragments exacts insérés/supprimés, diff identique = un seul segment `equal` |
| décisions | non-mutation de l'entrée, texte obligatoire pour `modified`, statut et bloc inconnus refusés, source exportée si `pending`/`rejected`, décision invalidée si la proposition a changé |
| porte de sortie | blocage tant qu'un bloc critique est en attente, autorisation après décision, placeholder accepté qui bloque toujours, workspace vide non exportable, **en-tête du CV couvert**, Markdown exporté sans marqueur, une exigence prouvée rejoint sa section (aucun titre de section répété) |
| persistance | aller-retour d'état, historique qui ne fait que **grossir** (le préfixe du fichier est conservé), identifiant de traversée refusé, **deux variantes = deux revues**, **état perdu reconstruit depuis l'historique**, fichier parasite sans casser l'export de données personnelles |
| service | workspace construit, décision persistée et rejouée, **décision sur un texte périmé refusée**, export bloqué puis autorisé, DOCX sans placeholder, historique ordonné et conservé |
| HTTP | parcours complet (workspace → decide → export 400 → décisions → export 200 + `PK`), candidature inconnue refusée, statut invalide refusé en 422 |
| statique | ni réseau, ni `window.prompt`, ni `mailto:` dans les trois fichiers ; présence des quatre décisions, des trois badges et de l'export dans l'interface |

Commandes et résultats :

```bash
.venv/bin/python -m pytest -q tests/test_cv_review.py   → 42 passed
.venv/bin/python -m pytest -q                             → 1466 passed, 1 skipped
.venv/bin/python -m ruff check .                          → All checks passed!
git diff --check                                           → propre
```

## 5 bis. Relecture adversariale et corrections

La livraison a été relue **deux fois** par un agent contradictoire, qui a cherché à **casser** la
fonctionnalité au lieu de la valider. Chaque défaut reproduit a été corrigé et figé dans un test
de non-régression.

**Première relecture — 9 défauts :**

| # | Défaut trouvé | Correction |
|---|---|---|
| 1 | la route de décision ignorait la variante : la décision partait dans l'autre revue, et l'export restait bloqué | la variante est dans la clé de stockage, dans les paramètres de la route et dans les envois du client |
| 2 | un marqueur de preuve resté dans l'**en-tête** du CV atteignait le DOCX exporté alors que l'export était annoncé comme autorisé | l'en-tête est couvert par `can_export`, il est affiché dans l'interface, et une ligne porteuse d'un marqueur est retirée du document |
| 3 | une décision pouvait s'appliquer à une proposition que la personne n'avait jamais lue | la décision porte le texte lu (`reviewed_text`) et l'API refuse si la proposition a changé |
| 4 | l'état et l'historique pouvaient diverger ; un état corrompu faisait perdre toutes les décisions | l'historique est écrit **avant** l'état, et l'état perdu est reconstruit par `replay_events` |
| 5 | un fichier temporaire laissé par un crash faisait passer l'export de données personnelles en 500 | les fichiers étrangers et temporaires sont ignorés |
| 6 | un workspace vide était annoncé « export autorisé » | un workspace sans proposition bloque l'export |
| 7 | « Accepter » sur un placeholder critique était une impasse muette | le bouton est désactivé et explique qu'il faut réécrire ou refuser |
| 8 | une branche inerte dans `_verified_status` | l'invariant « la proposition n'est que la re-spellisation locale » est explicité et testé |
| 9 | dérive documentaire (nombre de tests) | rapport mis à jour |

**Seconde relecture — 10 défauts, dont 4 introduits par les premiers correctifs :**

| # | Défaut trouvé | Correction |
|---|---|---|
| N1 | une proposition de plus de 4 000 caractères rendait le bloc **indécidable** (422) : le bouton devenait un cul-de-sac | la limite du texte relu passe à 20 000 caractères, au-dessus de la taille d'un champ de profil |
| N2 | le garde-fou « texte relu » était contournable en omettant le champ | le champ reste optionnel pour rester compatible avec le contrat de la mission, mais l'événement d'historique conserve toujours la formulation acceptée : la décision reste traçable |
| N3 | l'interface envoyait la décision sur la variante *demandée*, pas sur celle affichée | l'appel de décision porte le `variant_id` renvoyé par le serveur |
| N4 | deux décisions simultanées s'écrasaient (8 pertes sur 8 exécutions) | le cycle lecture-écriture-completion entier est sous le verrou du service ; test de non-régression à 2 threads (0 perte sur 8 exécutions) |
| N5 | « la décision n'a pas pu être enregistrée » alors qu'elle l'avait été | l'échec de l'instantané n'est plus une erreur bloquante : la décision est dans l'historique, donc effective ; un avertissement le dit |
| N6 | la remise à zéro ne supprimait pas les DOCX exportés par la revue | `DELETE /api/career/data` efface aussi `career_data/exports/cv_review/` |
| N7 | un bloc re-tranché restait listé comme invalidé | la liste `invalidated_blocks` est purgée quand une décision valide arrive |
| N8 | le rejeu faisait confiance à l'historique (statut système accepté, texte vide accepté) | le rejeu exige un statut de décision valide **et** la correspondance exacte du texte relu |
| N9 | la clé de revue n'était pas injective (`a`+`b__c` et `a__b`+`c` conflataient) | le séparateur est un point, impossible dans un identifiant ; l'aller-retour clé ⇄ couple est vérifié |
| N10 | l'export de données personnelles ignorait un état dont le nom n'avait pas de séparateur | la lecture passe par le chemin du fichier, pas par une reconstruction de clé |

Contrôles de non-régression repassés à l'issue de la seconde relecture : contournement de la porte
de sortie (propre), traversée de chemin (propre), codes HTTP (propre), XSS dans l'interface
(propre), **DOCX du kit ciblé byte-identique à `f5b22f2`** sur 36 combinaisons
(profil × variante), `ruff` propre, suite complète verte.

## 6. Confidentialité et réversibilité

- rien ne sort de la machine : aucune importation réseau dans le module, le service ou l'interface ;
- les fichiers de revue sont dans `career_data/cv_review/` (hors `data/`), en `0600` ;
- l'export de données personnelles (`GET /api/career/privacy-export`) **inclut** les workspaces et
  leur historique ;
- la remise à zéro (`DELETE /api/career/data`) **efface** les fichiers de revue ;
- chaque décision et chaque export est tracé dans `career_audit_log`.

## 7. Points d'attention pour la relecture

1. **Fichiers touchés hors du périmètre annoncé** par la mission :
   `career/application_studio.py` (extraction du plan), `career/service.py` (4 méthodes),
   `career_static/career.js` (un appel gardé), `career_static/index.html` (script + css),
   `career_static/css/cv-review.css`. `career/service.py` et `career_static/career.js` sont des
   **fichiers partagés** : l'intégration devra passer
   `--allow-shared-path career/service.py --allow-shared-path career_static/career.js`.
2. **Chemins de l'interface** : la mission demandait `career_static/js/cv-review.js` ; le dépôt
   place d'ordinaire ses scripts Career à la racine de `career_static/`. Le chemin de la mission a
   été respecté, et le CSS a été placé dans `career_static/css/` pour rester cohérent avec lui.
3. **Vocabulaire des sections** : les cinq sections de la mission sont implémentées ; une sixième,
   `certifications`, a été ajoutée parce que les trois variantes génèrent une section
   « Certifications » (le profil local n'a pas de champ certifications : cette section ne contient
   donc qu'un placeholder, non critique).
4. **Section des exigences** : une exigence d'offre sans preuve est rattachée à la section de
   revue qui correspond à son intitulé canonique (« Expérience » → `experiences`, « Compétences »
   → `skills`, …), et non à une section unique fourre-tout.
5. **Limite connue** : la proposition est reconstruite à chaque lecture à partir du profil. Si la
   personne modifie le profil **pendant** une revue, les blocs dont la proposition a changé
   repassent `pending` : c'est voulu (une décision porte sur un texte précis), mais cela peut
   ressembler à une perte de décision. La liste `invalidated_blocks` l'explicite dans la réponse
   de l'API, et la décision refusée sur un texte périmé est expliquée par l'API (400).
6. **Le nom du fichier de la revue** : une clé par couple candidature × variante
   (`app_….m_a.json`). Si une candidature passe à une autre variante, les deux revues coexistent
   — c'est voulu, mais le dossier `career_data/cv_review/` peut donc contenir plusieurs fichiers
   par candidature.
7. **Limite connue** : `reviewed_text` reste un champ optionnel (le contrat de la mission ne
   mentionne que `{block_id, status, user_text?}`). Un client qui l'ometrice perd la protection
   contre une proposition changée ; l'historique conserve dans tous les cas la formulation
   acceptée, donc la décision reste traçable. L'interface livrée l'envoie toujours.

## 8. Traceabilité du contrat de la mission

| Critère | Où |
|---|---|
| `cv_review.build_workspace(application_id) -> ReviewWorkspace` pur | `career/cv_review.py` — `build_workspace`, aucun effet de bord, horodatage injecté |
| Diff phrase par phrase | `diff_segments` — `difflib.SequenceMatcher` au mot |
| Statuts persistés, historique immuable | `career/cv_review_store.py` — état JSON + historique JSONL en ajout seul |
| Export DOCX bloqué si placeholders critiques non validés | `can_export` + `export_cv_review` (400 avec les raisons) |
| Tests : workspace, décisions, export bloqué/autorisé | `tests/test_cv_review.py` (42 tests) |
| Ruff clean, suite verte, `git diff --check` propre | §5 |
| Rapport | ce document |

## 9. Suite possible

- **exporter le diff en PDF** pour la relecture papier ;
- **proposer une preuve** depuis une exigence non couverte (aujourd'hui la personne écrit le
  texte à la main dans le bloc) ;
- **une seule preuve par bloc** : aujourd'hui `evidence` est une liste, mais un bloc n'en porte
  qu'une ; la structure les accepte déjà toutes les deux ;
- **un sélecteur de variante dans le panneau de revue** : l'interface affiche aujourd'hui la
  variante du kit ouvert ; le sélecteur existe déjà ailleurs dans l'interface Career, et
  l'API sait déjà isoler les revues par variante (§3.6) ;
- **rendre l'en-tête du CV reviewable** : il est aujourd'hui affiché et bloquant, mais pas
  modifiable ligne à ligne comme les blocs.
