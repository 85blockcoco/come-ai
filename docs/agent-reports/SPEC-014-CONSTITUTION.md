# SPEC-014 — Constitution exécutable

Date : 22 octobre 2026
Branche : `worker/cvboost-49-1792684293`
Base : `f5b22f2` (`merge(career): ATS diagnostics and targeted CV variants pipeline`)
Mission : CVBOOST-49
Statut : **TERMINÉE — module, API, UI, CI et tests livrés**

---

## 1. Ce qui est livré

| Fichier | Rôle | Lignes |
| --- | --- | --- |
| `career/constitution.py` | Cœur : DSL CEL restreint (analyseur syntaxique maison), modèles `Rule` / `RuleSet` / `ValidationResult` / `Violation` / `ConformanceReport`, moteur `ConstitutionEngine`, catalogue de règles, génération de tests, CLI | 1 880 |
| `career/constitution_store.py` | Persistance SQLite versionnée, signatures HMAC, audit trail, historique, rollback | 1 182 |
| `career/constitution_audit.py` | Conformité, détection de dérive, rapport Markdown | 303 |
| `career/router.py` | 20 endpoints `/api/constitution/...` (modification additive) | +330 |
| `career_static/js/constitution.js` | Éditeur DSL, dashboard, graphe, historique, audit trail (module autonome, fonctions pures testables hors navigateur) | 763 |
| `career_static/index.html`, `career_static/career.js`, `career_static/career.css` | Onglet « Constitution », section complète, styles | +220 |
| `tests/test_constitution.py` | 76 tests (moteur, gouvernance, dérive, API, CLI, UI) | 1 120 |
| `.github/workflows/constitution.yml` | Validation de la Constitution à chaque PR, blocage si violation critique | 34 |

Aucun appel réseau, aucun envoi de données, aucune dépendance ajoutée : la pile
exigée par `requirements-v3.txt` suffit.

---

## 2. Le DSL : CEL restreint, interprété, jamais exécuté

Le DSL est un sous-ensemble de [CEL](https://cel.dev) écrit pour ce projet :
analyse lexicale → analyse syntaxique descendante récursive → arbre → évaluation
sur un contexte.

**Aucune évaluation de code Python.** Le module ne contient ni `eval`, ni `exec`,
ni `__import__` ; un test le vérifie statiquement
(`test_le_moteur_n_utilise_jamais_eval_ni_exec`) et un second test vérifie
qu'une expression ne peut pas atteindre le disque
(`test_une_expression_ne_peut_pas_lire_le_disque`).

### Ce qui est supporté

```cel
freshness.certification.max_age_days <= 365        // chemin pointé
matching.score >= 0.7                               // comparaison numérique
dedup.similarity_threshold >= 0.92
matching.start_month in [1, 2, 3]                   // appartenance à une liste
privacy.pii_fields.all(field, field.encrypted == true)   // macro
matching.critical_requirements.exists(req, req.covered == true)
has(matching.score) && matching.score >= 45         // prédicat d'existence
size(matching.critical_requirements) > 0            // fonction
!a.value && (b.value || c.value)                    // logique, parenthèses
7 / 2 == 3, 7 % 3 == 1                              // arithmétique entière CEL
```

Macros : `all`, `exists`, `filter`, `map`. Fonctions : `size`, `int`, `double`,
`string`, `bool`, `has`. Types : entiers, flottants, chaînes, booléens, listes,
objets. Comparaisons entre types différents renvoient `false` (pas d'exception),
l'arithmétique entre types non numériques est refusée avec un message explicite.

### La sémantique qui compte

**Une donnée absente n'est pas une violation.** Si l'expression référence un
champ absent du contexte, le résultat est marqué `not_evaluable`, la sévérité
est abaissée en `warning` et la règle **n'entre pas** dans le score ni dans les
violations. Inventorier une donnée manquante reste un travail humain ; la
Constitution ne le transforme pas en échec automatique.

**Une expression non booléenne est une erreur d'écriture**, pas un résultat
faux : le résultat porte `status = "error"` et le motif exact.

### Performance

Les expressions sont compilées une fois puis mises en cache
(`functools.lru_cache`). `test_evaluation_reste_rapide_sous_la_milliseconde_par_regle`
mesure 200 évaluations : la moyenne est très en dessous de 1 ms par règle.

---

## 3. Gouvernance : version, approbation, rollback, signature

| Étape | Comportement implémenté | Test |
| --- | --- | --- |
| Création | `draft` (version 1), jamais active automatiquement | `test_creation_regle_exige_un_brouillon` |
| Modification | Nouvelle version `draft` ; **la version approuvée reste effective** tant que la nouvelle n'est pas approuvée | `test_modification_cree_une_version_et_conserve_l_historique` |
| Approbation | Exige un approbateur **différent de l'auteur** ; la version précédente passe en `deprecated` | `test_approbation_exige_un_tiers_different_de_l_auteur` |
| Dépréciation | `deprecated` : la règle reste applicable pendant la transition | `test_deprecation_puis_archivage` |
| Archivage | `archived` : la règle n'est plus effective | idem |
| Rollback | Restaure une version antérieure en créant une **nouvelle version active** (instantané, tracé) | `test_rollback_restaure_instantanement_une_version_anterieure` |
| Signature | HMAC-SHA256 sur le contenu canonique, clé locale `career_data/constitution.key` (0600) ; toute altération du contenu est détectée | `test_signature_detecte_une_alteration_de_contenu` |
| Audit trail | Chaque action (création, modification, approbation, dépréciation, archive, rollback) est journalisée avec acteur, horodatage UTC et détails | `test_journal_audit_trace_les_actions` |

Le stockage est **séparé** de la base Career métier
(`career_data/constitution.sqlite3`) : une Constitution est un document de
gouvernance, pas une donnée de candidature. Conséquence assumée : la remise à
zéro des données personnelles (`DELETE /api/career/data`) ne supprime pas la
Constitution. Aucune route HTTP de suppression de la Constitution n'est exposée
(la gouvernance passe par la dépréciation et l'archivage).

---

## 4. Le catalogue : ce qui existe déjà, ce qui est proposé

13 règles de référence sont installées au premier démarrage
(`seed_defaults`, idempotent).

**Règles « actives » — elles décrivent un comportement réel du code, et le
champ `source_reference` pointe le fichier exact :**

| Règle | Expression | Source |
| --- | --- | --- |
| `matching.score.minimum_match` | `matching.score >= 45` | `career/service.py:147-149` |
| `matching.score.strong_match` | `matching.score >= 70` | `career/service.py:147-149` |
| `matching.duration_months.minimum` | `matching.duration_months >= 6` | `career/offer_qualification.py:135` |
| `matching.duration_months.maximum` | `matching.duration_months <= 24` | `career/offer_qualification.py:152` |
| `matching.start_month.allowed` | `matching.start_month in [1, 2, 3]` | `career/offer_qualification.py:159` |
| `matching.contract_type.allowed` | `matching.contract_type in ['stage','cdd','cdi','vie']` | `career/offer_qualification.py:163` |
| `matching.score_weights.total` | `matching.score_weights.total == 100` | `career/scoring.py:17` |

**Règles « brouillon » — propositions, inactives tant qu'elles ne sont pas
approuvées :** `freshness.certification.max_age_days`,
`freshness.offer.posted_max_age_days`, `privacy.pii_fields.encrypted`,
`export.docx.max_size_mb`, `matching.critical_requirements.covered`,
`dedup.similarity_threshold`.

> La Constitution ne s'attribue pas le droit d'imposer un seuil qui n'existe pas
> encore dans le produit. Une règle proposée reste un brouillon : elle n'est
> jamais appliquée implicitement. Exemple : la déduplication actuelle compare
> des clés exactes (identifiant de source, URL canonique), pas une similarité ;
> le seuil de 0,92 reste donc une proposition, pas un comportement existant.

Trois tests gardent cette honnêteté vérifiable :

- `test_chaque_reference_de_source_pointe_vers_un_code_reel` : le fichier et
  la ligne cités par chaque règle active existent et ne sont pas vides ;
- `test_les_seuils_mirres_existent_dans_le_code_source` : 45, 70, 6, 24,
  [1, 2, 3], les types de contrat et la somme des poids (100) sont bien ceux
  du code ;
- `test_une_regle_sans_code_equivalent_reste_un_brouillon` : toute règle sans
  référence de code est nécessairement une proposition.

> La Constitution ne s'attribue pas le droit d'imposer un seuil qui n'existe pas
> encore dans le produit. Une règle proposée reste un brouillon : elle n'est
> jamais appliquée implicitement.

Deux jeux de règles sont livrés : `career.core` (règles actives) et
`career.offres` (règles d'offre).

---

## 5. Conformité et dérive

`career/constitution_audit.py` calcule les quatre métriques du contrat et
déclenche les alertes correspondantes :

| Métrique | Seuil | Implémentation |
| --- | --- | --- |
| Dérive des règles | > 5 % modifiées sans relecture | `unreviewed_modification_rate` (version courante en brouillon alors qu'une version approuvée existe) |
| Couverture de tests | < 90 % des règles actives sans test | `test_coverage` (drapeau `has_test` posé par la génération de tests) |
| Violations critiques | > 0 | `critical_violations` (historique de conformité) |
| Ancienneté de relecture | > 365 jours | `stale_reviews` |
| Intégrité des signatures | 0 règle non signée | `unsigned_rules` |

Un rapport Markdown lisible (`render_report_markdown`) est produit pour la
relecture et exposé par `GET /api/constitution/audit`.

---

## 6. API

Toutes les routes sont sous `/api/constitution` (convention du dépôt) :
`/constitution/rules` dans le contrat de mission → `/api/constitution/rules` ici.

| Route | Méthode | Rôle |
| --- | --- | --- |
| `/api/constitution/health` | GET | État du module (nombre de règles, DSL, version) |
| `/api/constitution/rules` | GET | Liste + filtres (`domain`, `status`, `q`, `scope`) |
| `/api/constitution/rules` | POST | Crée une règle en brouillon (201) |
| `/api/constitution/rules/{id}` | GET | Détail, version effective, historique, validité de la signature |
| `/api/constitution/rules/{id}` | PATCH | Nouvelle version (brouillon) |
| `/api/constitution/rules/{id}/approve` | POST | Approbation → active |
| `/api/constitution/rules/{id}/deprecate` | POST | Dépréciation |
| `/api/constitution/rules/{id}/archive` | POST | Archivage |
| `/api/constitution/rules/{id}/rollback` | POST | Restauration d'une version antérieure |
| `/api/constitution/rulesets` | GET / POST | Jeux de règles |
| `/api/constitution/rulesets/{id}` | GET / PATCH | Détail + historique / nouvelle version |
| `/api/constitution/rollback/{ruleset_id}` | POST | Rollback d'un jeu de règles |
| `/api/constitution/validate` | POST | Valide une entité (JSON fourni **ou** `job_id` d'une offre stockée) |
| `/api/constitution/report/{entity_id}` | GET | Rapport de conformité et tendance |
| `/api/constitution/audit` | GET | Audit global + rapport Markdown |
| `/api/constitution/drift` | GET | Dérive et alertes |
| `/api/constitution/test/generate` | POST | Tests pytest générés depuis les règles |
| `/api/constitution/expression/check` | POST | Validation syntaxique d'une expression |
| `/api/constitution/expression/preview` | POST | Prévisualisation sur un contexte |

Les erreurs métier sont levées en `UserFacingError` → HTTP 400 avec un message
exploitable ; une règle inconnue n'est jamais un 500.

---

## 7. Interface (`career_static/js/constitution.js`)

Onglet « Constitution » dans l'espace Career, 100 % local :

- **Éditeur de règles** : formulaire complet (domaine, sévérité, périmètre,
  expression, remédiation, auteur, approbateur) ; le champ expression propose
  une autocomplétion (catalogue des 11 identifiants métier) ;
- **Éditeur DSL** : vérification syntaxique immédiate côté navigateur puis
  vérification autoritaire côté moteur (`/expression/check`), avec la liste des
  identifiants détectés ; prévisualisation du résultat sur un contexte JSON ;
- **Tableau de bord** : score de couverture, alertes de dérive, dernières
  violations ;
- **Graphe** : SVG règles → entités concernées → couverture de test
  (`buildGraphModel` est une fonction pure, testée hors navigateur) ;
- **Historique** : timeline des versions, diff champ par champ, restauration en
  un clic ;
- **Audit trail** : qui a changé quoi, quand, pourquoi.

Le fichier ne contient aucune URL distante (vérifié par test) et n'appelle que
`/api/constitution/...`.

---

## 8. Tests

```text
.venv/bin/python -m pytest -q tests/test_constitution.py   → 76 passed
.venv/bin/python -m pytest -q                               → 1500 passed, 1 skipped
.venv/bin/python -m ruff check .                            → All checks passed!
git diff --check                                            → propre
```

Répartition : 17 tests de DSL et de sécurité, 8 tests de moteur, 13 tests de
gouvernance, 7 tests de référentiel, 6 tests de dérive et d'audit, 13 tests
d'API HTTP, 2 tests de tests générés, 4 tests de CLI, 3 tests d'interface
(dont un test Node qui exécute les fonctions pures du module), 3 tests de
contrat public.

Les tests générés depuis les règles sont eux-mêmes exécutés par pytest dans
`test_tests_generes_sont_executables` : le fichier généré passe.

---

## 9. Intégration

- La Constitution est montée dans `create_career_router`, donc disponible
  dans l'application réelle (`come_ai_web.py`) comme dans les tests.
- `POST /api/constitution/validate` accepte une entité JSON **ou** l'identifiant
  d'une offre réellement importée : le contexte est alors construit depuis
  `career/service.py` (score, durée, mois de début, type de contrat, date de
  publication). Test d'intégration :
  `test_api_validation_une_offre_stockee_par_son_identifiant`.
- `build_entity_context` ne fabrique aucune donnée : un champ absent reste
  absent (test `test_contexte_ne_fabrique_pas_de_donnee_absente`).

---

## 10. Limites assumées

1. **Un seul DSL exécutable.** Le contrat mentionne `rego`, `python`, `sql`,
   `json_logic` : ces types sont **refusés à la création** avec un message
   explicite. Un moteur qui prétendrait les exécuter serait faux.
2. **Les modules n'ont pas encore switched sur la Constitution.** Elle décrit
   les seuils existants (et les propose pour les autres), mais
   `career/service.py`, `career/scoring.py` et `career/offer_qualification.py`
   lisent encore leurs constantes. Brancher les modules sur la Constitution
   (remplacement des constantes par une lecture versionnée) est la suite
   logique : c'est le travail des missions SK-01 → SK-21 et SPEC-011 → 013.
3. **Tests générés simples.** `hypothesis` n'est pas dans l'environnement
   hors ligne : les tests générés vérifient l'évaluabilité, le type de retour
   et la positivité/négativité des comparaisons simples, sans fuzzing complet.
4. **Signature symétrique.** La clé est locale (HMAC-SHA256) : elle protège
   contre l'altération accidentelle et la corruption du fichier, pas contre un
   attaquant ayant accès au fichier de clé.
5. **Séparation des tâches.** L'approbation exige un tiers. En usage local à
   une seule personne, il faut deux identités distinctes : c'est un choix
   assumé (une règle approuvée par son auteur n'aurait aucune valeur de
   relecture).
6. **Pas de chiffrement du stockage.** La Constitution contient des règles, pas
   des données personnelles ; le fichier SQLite est protégé par les permissions
   du dossier (`0700`), comme le reste de `career_data/`.

---

## 11. Pour la relecture

```bash
cd /Users/comedelavenne/AI-Excel-Agent-worker-cvboost-49-1792684293
.venv/bin/python -m pytest -q tests/test_constitution.py
.venv/bin/python -m career.constitution --base-dir /tmp/constitution-demo validate --all
.venv/bin/python -m career.constitution --base-dir /tmp/constitution-demo check --all-entities --fail-on-critical
```

Points d'attention pour la relecture :

1. la sémantique « donnée absente ≠ violation » (`not_evaluable`) ;
2. la séparation auteur/approbateur, et le sort d'une version approuvée quand
   une nouvelle version est proposée ;
3. le périmètre exact du référentiel de règles actives (voir §4) ;
4. le refus explicite des DSL non supportés.
