# SPEC-011 — Registre de traçabilité des exigences (mission CVBOOST-46)

Date : 22 octobre 2026
Branche : `worker/cvboost-46-1792684168`
Base : `f5b22f2` (`main` au moment du lot)
Statut : **TERMINÉE — livrable, testée et prête pour relecture**

---

## 1. Ce qui a été livré

| Fichier | Rôle |
|---|---|
| `career/traceability.py` | Cœur métier pur : `RequirementTrace`, `TraceEvent`, `TraceabilityRegistry`, règles, adaptateurs SK-02 / SK-21 |
| `career/traceability_store.py` | Persistance SQLite locale (`career_data/traceability.sqlite3`), indexation, requêtes, `TraceabilityLedger` |
| `career/traceability_audit.py` | Les six rapports d'audit (couverture, gaps, dérogations, historique, évolution, synthèse) |
| `career/router.py` | 21 routes du registre, montées sous `/api/career/traceability` **et** sous `/traceability` |
| `career/service.py` | **3 lignes d'intégration** : accès au magasin, effacement des données, export des données personnelles |
| `career_static/js/traceability.js` | Interface du registre : filtres, tri, historique par exigence, actions et actions groupées |
| `career_static/traceability.css` | Styles de la vue |
| `career_static/index.html` | Onglet « Traçabilité » + section `view-traceability` |
| `career_static/career.js` | **2 lignes** : le nouvel onglet dans la liste des vues et son chargeur |
| `tests/test_traceability.py` | 73 tests (règles, persistance, audit, API HTTP, vie privée, garde-fous JS) |
| `docs/agent-reports/SPEC-011-TRACEABILITY.md` | Ce rapport |

---

## 2. La règle centrale : aucune couverture sans preuve citée

Tout le registre tient sur une invariant vérifiable, testée dans les deux sens :

```
statut ∈ {covered, partial, contradicted}  ⟺  evidence_id ET evidence_quote non vides
statut == uncovered                          ⟹  aucune preuve attached
```

Une exigence ne peut donc jamais être déclarée couverte « parce que ça a l'air bon » :
le serveur refuse la demande avec un message explicite. Symétriquement, une
exigence « non couverte » ne peut pas traîner une preuve : la repasser
« non couverte » **délie** la preuve et **journalise** l'opération.

Les six règles du registre :

| # | Règle | Où elle est appliquée |
|---|---|---|
| 1 | Aucune invention : un statut de couverture exige un identifiant **et** une citation | `TraceabilityRegistry._check_evidence_invariant`, `link_evidence`, `register` |
| 2 | Historique immuable : le texte de l'exigence ne change jamais, les événements ne sont jamais réécrits | dataclasses gelées (`frozen=True`), `replace()` uniquement |
| 3 | Traçabilité des actions : `actor` + horodatage ISO 8601 + `origin` + commentaire | `TraceabilityRegistry._apply` |
| 4 | Dérogation justifiée : `waived` exige une justification, impossible via un simple changement de statut | `waive()` / `set_status()` |
| 5 | Liaison automatique non validée : une liaison `auto` démarre `confirmed=False` | `link_evidence(origin="auto")`, `confirm_link()` |
| 6 | Déterminisme : horloge et identifiants injectables | `TraceabilityRegistry(clock=...)`, `event_identifier()` |

La suppression d'une exigence **efface l'exigence mais conserve son journal** :
le journal d'audit survit à ce qu'il décrit (les événements sont dans une table
sans cascade).

---

## 3. Le modèle de données

### RequirementTrace

Les 14 premiers champs respectent l'ordre et le nom du contrat de mission
(`trace_id`, `requirement_id`, `requirement_text`, `source`, `category`,
`criticality`, `evidence_id`, `evidence_quote`, `status`, `created_at`,
`updated_at`, `history`, `tags`). Les champs suivants sont des **extensions
documentées**, toutes à valeur par défaut, qui rendent le contrat
exploitable :

| Extension | Pourquoi |
|---|---|
| `offer_id`, `cv_id` | Rattachement à l'offre et au CV (filtres et rapports par offre / par CV) |
| `locator`, `source_field` | Provenance SK-02 : le champ exact et la position dans le texte |
| `evidence_field`, `evidence_offset` | Provenance de la preuve (section du CV, offset) |
| `link_origin` (`auto` / `manual`) | Une liaison automatique n'est pas une liaison validée |
| `confirmed` | Validation humaine d'une liaison automatique |
| `waiver_reason` | La justification d'une dérogation reste attachée à l'exigence |

### TraceEvent

Les 8 champs du contrat sont respectés (`event_id`, `timestamp`, `event_type`,
`old_value`, `new_value`, `actor`, `comment`), plus deux extensions :
`origin` (auto / manual) et `trace_id` (rattachement à l'exigence dans le
journal global).

Le vocabulaire `EVENT_TYPES` contient les 8 types imposés
(`created`, `linked`, `unlinked`, `status_changed`, `category_changed`,
`criticality_changed`, `waived`, `reopened`) et 5 extensions qui rendent les
opérations réellement traçables : `tags_updated`, `link_confirmed`,
`link_rejected`, `deleted`.

### Identifiants — écart assumé avec le contrat

Le contrat dit « `trace_id` : UUID unique ». L'implémentation utilise
`trc_` + `sha256(source | requirement_id | texte)[:16]`.

**Pourquoi :** la création automatique doit être **idempotente**. Rejouer
l'extraction d'une offre (SK-02) ne doit pas créer un doublon, mais doit
retrouver la trace existante — c'est ce qui permet à l'interface de
recharger le registre sansInvariant de duplication. Un UUID aléatoire
imposerait une recherche par clé secondaire et rouvrirait la porte au
doublon. L'identifiant reste unique, stable et recalculable ; il n'est
simplement pas aléatoire. Même logique pour les événements : l'empreinte
inclut le contenu de l'événement, donc deux événements distincts ne peuvent
pas partager le même identifiant.

---

## 4. API

21 routes, montées **deux fois** par le même code (une seule implémentation
métier, deux adresses) :

| Route (préfixe `/api/career/traceability` **ou** `/traceability`) | Effet |
|---|---|
| `GET /requirements` | Liste filtrée : `status`, `category`, `criticality`, `offer_id`, `cv_id`, `source`, `tag`, `query`, `limit`, `offset` |
| `POST /requirements` | Crée une exigence |
| `POST /requirements/from-offer` | **Création automatique SK-02** à partir d'une offre |
| `POST /requirements/auto-link` | **Liaison automatique SK-21** à partir du matching |
| `GET /requirements/{trace_id}` | Détail complet + historique |
| `PATCH /requirements/{trace_id}` | Modifie statut, preuve, tags, catégorie, criticité, commentaire |
| `DELETE /requirements/{trace_id}` | Supprime l'exigence (le journal reste) |
| `POST /requirements/{trace_id}/link-evidence` | Lie une preuve (identifiant + citation) |
| `POST /requirements/{trace_id}/unlink-evidence` | Délie la preuve |
| `POST /requirements/{trace_id}/waive` | Déroge, justification obligatoire |
| `POST /requirements/{trace_id}/reopen` | Annule la dérogation |
| `POST /requirements/{trace_id}/confirm` | Valide ou rejette une liaison automatique |
| `GET /audit/coverage` | Couverture par offre **et** par CV + synthèse |
| `GET /audit/gaps` | Exigences obligatoires non couvertes |
| `GET /audit/history` | Historique global filtré (trace, type, acteur) |
| `GET /audit/waived` | Exigences dérogées + justifications |
| `GET /audit/evolution` | Couverture dans le temps (une ligne par jour) |
| `GET /audit/report` | Rapport d'audit complet |
| `GET /export` (`?format=json\|csv`) et `GET /export/{format}` | Export complet JSON ou CSV |
| `POST /import` | Restaure un export (`replace=true` pour écraser) |

**Écart de chemin assumé :** le contrat de mission écrit `/traceability/...`
alors que la convention du workspace Career est `/api/career/...`. Les deux
sont servies, donc le contrat est respecté à la lettre et la convention du
repo aussi.

Les erreurs métier reviennent en `400` avec un message lisible en français
(ex. « Une exigence couverte doit porter un identifiant de preuve ET une
citation. »), les erreurs de validation de forme en `422`.

---

## 5. Les rapports d'audit

| Rapport | Contenu | Définition explicite |
|---|---|---|
| Couverture par offre | totaux, `covered`/`partial`/`uncovered`/`contradicted`/`waived`, `applicable`, `coverage_rate`, gaps obligatoires, dérogations | `applicable` = total − dérogées ; `coverage_rate` = `covered / applicable`, **`None`** si rien n'est applicable (jamais `0` ni `1` par défaut) |
| Couverture par CV | idem + `with_evidence` + `pending_validation` | idem |
| Gaps critiques | exigences `mandatory` dont le statut n'est pas `covered` | `partial` et `contradicted` **sont** des gaps : une couverture partielle n'est pas une couverture |
| Exigences dérogées | liste + justification | la justification est obligatoire et affichée |
| Historique des changements | chronologie complète | le journal global fait foi (il contient aussi les exigences supprimées) |
| Évolution dans le temps | une ligne par jour : applicables, couvertes, taux | reconstructible depuis l'historique, pas depuis l'état courant |

Les rapports sont des fonctions pures : mêmes entrées, mêmes chiffres, à
l'horloge près.

---

## 6. Intégrations

### SK-02 — extraction d'exigences (intégrée, aujourd'hui)

`traces_from_offer_analysis(registry, analyze_offer(offer))` crée une trace
par exigence :

- **texte verbatim** de l'exigence (jamais reformulé) ;
- `locator` et `source_field` conservés (provenance au champ près) ;
- catégorie SK-02 → catégorie du registre (`technical_skill` → `skill`,
  `language` → `language`, `availability`/`mobility`/`work_authorization` →
  `other`) ;
- modalité SK-02 → criticité (`required` → `mandatory`, `preferred` →
  `preferred` ou `nice_to_have` si la phrase porte un marqueur « nice to
  have » explicite, `contextual` → `contextual`, `unknown` → `contextual`) ;
- les exigences **`injection_suspect` sont ignorées** : une offre est une
  donnée, jamais une instruction ;
- l'opération est **idempotente** (rejouer l'extraction ne duplique rien).

Exposé en HTTP par `POST /requirements/from-offer` (avec `job_id` d'une offre
enregistrée, ou l'offre brute).

### SK-10 — preuves du profil (interface prête, module non présent sur cette base)

SK-10 n'existe pas dans la base `f5b22f2` (il est sur une autre branche). Le
registre n'a donc **pas de dépendance** : il exige simplement qu'une liaison
apporte un `evidence_id` **et** une `evidence_quote`, et il refuse tout le
reste. Le jour où SK-10 est fusionné, la liaison se fait par
`POST /requirements/{trace_id}/link-evidence` ou par l'adaptateur
`TraceabilityRegistry.link_evidence`, sans changement de contrat.

### SK-21 — matching (interface prête, module non présent sur cette base)

Idem : `auto_link_from_matching(registry, matches)` consomme le résultat du
matching et crée des liaisons `origin="auto"`, **`confirmed=False`**, qui
attendent une validation humaine (`POST .../confirm`). Une correspondance
sans citation est **ignorée** : le registre n'accepte jamais une preuve non
citée. Exposé en HTTP par `POST /requirements/auto-link`.

Le point de raccordement est donc explicite et testable, sans dépendre des
branches non fusionnées.

---

## 7. Vie privée (point sensible, à relire en priorité)

Le registre contient des exigences et des **citations de preuves
personnelles**. Deux garde-fous ont été ajoutés à `career/service.py` :

1. `reset_personal_data()` efface aussi le registre (`traceability_store().reset()`) :
   aucune trace d'exigence ni citation de preuve ne survit à une demande
   d'effacement explicite des données Career ;
2. `export_personal_data()` inclut la section `traceability` : le registre
   fait partie des données personnelles exportables, comme le reste.

La base vit dans `career_data/traceability.sqlite3` (répertoire privé en
`0700`, fichier en `0600`, `PRAGMA secure_delete = ON`), jamais dans
`data/` ni dans l'espace de travail général.

---

## 8. Interface

Nouvel onglet **« Traçabilité »** dans l'espace Career :

- **cartes de synthèse** : exigences, couvertes, sans couverture complète,
  dérogées, taux de couverture ;
- **filtres** : statut, criticité, catégorie, recherche (texte, identifiant,
  citation) ;
- **liste** : texte de l'exigence, catégorie, criticité, offre, tags,
  citation de la preuve (ou « Aucune preuve citée » en ambre), pastille de
  statut — une liaison automatique non validée affiche « Liaison à valider » ;
- **détail** : provenance (source, champ, locator), preuve, dérogation,
  chronologie de l'historique, et les actions (lier / délier une preuve,
  déroger, annuler la dérogation, changer le statut, valider une liaison) ;
- **actions groupées** : sélection multiple → dérogation avec justification
  saisie dans le formulaire (jamais de boîte de dialogue système) ;
- **exports** : JSON et CSV.

L'IHM n'invente rien : elle affiche ce que le serveur autorise. Aucune
injection HTML (`textContent` uniquement, garde-fou testé), aucune donnée
réelle dans les tests.

---

## 9. Validation

| Commande | Résultat |
|---|---|
| `.venv/bin/python -m pytest -q tests/test_traceability.py` | **73 passed** |
| `.venv/bin/python -m pytest -q` | **1497 passed, 1 skipped** (base : 1424 passed, 1 skipped → **+73, aucune régression**) |
| `.venv/bin/python -m ruff check .` | `All checks passed!` |
| `./checklist_codex.sh` | `TOUT VERT` (seuls avertissements : worktrees frères absents de cette machine) |
| `git diff --check` | propre |

Les 73 tests couvrent : le vocabulaire du contrat, les six règles métier
(cas nominaux **et** cas de refus), l'immuabilité de l'historique, la
suppression qui conserve le journal, l'idempotence de la création
automatique, le rejet des `injection_suspect`, la liaison automatique non
validée, la persistance et les filtres du magasin, l'export/import, les six
rapports d'audit, le cycle CRUD complet en HTTP, les deux préfixes de
routes, l'effacement des données et l'export des données personnelles, et
des garde-fous d'interface (présence de la vue, absence d'`innerHTML`,
absence de `window.prompt`, exécution réelle du script dans Node).

---

## 10. Limites assumées et hors périmètre

1. **SK-10 et SK-21 ne sont pas sur cette base.** Les adaptateurs sont
   prêts et testés sur des données synthétiques ; le raccordement réel se
   fera à la fusion de ces SPEC. Le registre n'a de toute façon aucune
   dépendance dure : il exige un identifiant et une citation.
2. **`career/service.py` et `career_static/career.js` sont des fichiers
   partagés** (cf. `scripts/audit_integration.py`). Les modifications y sont
   volontairement minimales (3 lignes et 2 lignes) et indispensables :
   la vie privée du registre et l'onglet de l'interface. L'intégrateur doit
   les autoriser explicitement (commande ci-dessous).
3. **L'interface de liaison d'une preuve est un champ texte** (identifiant
   + citation). Tant que SK-10 n'est pas fusionné, il n'y a pas de sélecteur
   de preuves dans l'UI ; le champ est le point de raccordement.
4. **Pas de score de pertinence.** Le registre mesure une couverture
   factuelle, jamais une probabilité d'embauche.
5. **Pas de réseau, pas de modèle, pas d'horloge cachée** dans le cœur
   métier : l'horloge est injectée, la base est locale.

---

## 11. Commande d'audit d'intégration

```bash
python scripts/audit_integration.py \
  --branch worker/cvboost-46-1792684168 \
  --base f5b22f2 \
  --allow-path career/traceability.py \
  --allow-path career/traceability_store.py \
  --allow-path career/traceability_audit.py \
  --allow-path career/router.py \
  --allow-path career_static/index.html \
  --allow-path career_static/js/traceability.js \
  --allow-path career_static/traceability.css \
  --allow-shared-path career/service.py \
  --allow-shared-path career_static/career.js
```

`tests/` et `docs/agent-reports/` sont hors périmètre mais acceptés d'office
par l'outil.

---

## 12. Ce que je demande à la relecture

1. **La règle 1** (couverture ⇔ preuve identifiée **et** citée) : c'est le
   cœur de la valeur du module. Est-elle trop stricte pour un usage réel ?
   Le cas « preuve identifiée mais citation absente » est aujourd'hui un refus.
2. **La dérogation** : `waived` sort l'exigence du dénominateur de
   couverture. Est-ce le bon choix, ou faut-il garder les dérogées dans le
   dénominateur et les compter à part ?
3. **`trace_id` déterministe** au lieu d'un UUID : accepter l'écart avec le
   contrat de mission pour garantir l'idempotence de la création
   automatique.
4. **Le double préfixe de routes** (`/api/career/traceability` et
   `/traceability`) : 42 routes servies par un seul code. Garder les deux, ou
   n'en garder qu'un ?
5. **Les 3 lignes dans `career/service.py`** (effacement + export) : le
   minimum pour que le registre respecte la promesse de vie privée de
   l'espace Career.
