# CVBOOST-10 — INTÉGRATION V2

| Statut | Verdict |
|---|---|
| **INTÉGRATION PARTIELLE — à reprendre** | **MERGE REFUSÉ** |

## Vagues et lots

| Vague | Lots | SHAs sources | Statut |
|---|---|---|---|
| 1 | 01, 02, 03, 04, 05, 06, 07 | `31e7e48`, `95f1855`, `78fdd11`, `92ca179`, `ce7bd27`, `d76ca42`, `e4ec53d` | intégrés |
| 2 | 08, 09, 11, 13, 16, 21 | `f67afef`, `f4a8daa`, `062e2ec`, `d5ff55a`, `88524a3`, `fd8bf07` | intégrés, incompatibilités ouvertes |
| 3 | 22, 23, 24, 25, 26, 27 | `a52d54d`, `a5fbced`, `5da6997`, `128ed7e`, `61bd2b8`, `0bb3784` | intégrés |
| 4 | 28, 29, 30, 31, 32 | `90176ef`, `840f28d`, `c618052`, `0404949`, `5ff2192` | intégrés, incompatibilités ouvertes |
| 5 | 34, 35, 36, 38, 40 | `2b3dc67`, `e9d734f`, `f5f9984`, `6e6d46d`, `b48a5e4` | intégrés, câblages partiels |
| 6 | 41, 42, 43 | `2ef29c3`, `8962615`, `ee9cfdc` | intégrés; vague interrompue après 43 |
| 6-7 | 44, 45, 46, 47, 48, 49, 50, 52, 53, 54, 55, 58 | non mergés | **À REPRENDRE** |

## Branches rejetées / non retenues

| Lot | Branche | Motif |
|---|---|---|
| 52 | `origin/worker/cvboost-52-1792707985` | contient `messages/result.json`, chemin interdit; alternative à réévaluer |
| 48 | workers antérieurs à `origin/worker/cvboost-48-1792709201` | doublons plus anciens |
| 52 | workers autres que candidats 7985/9110 | doublons |

## Conflits arbitraires

| Lots | Fichiers / contrat | Arbitrage |
|---|---|---|
| 01, 05, 06 | `cv_quality/*`, service, routeur, UI | contrats de base plus complets conservés; ajouts orthogonaux gardés |
| 05-07 | sources | registre cumulé; Recruitee documenté mais non activé par défaut |
| 08, 16, 21 | ATS / matching / salaire | modèles cumulés; moteur adversarial 08 conservé; API structurée 21 partielle |
| 11, 13, 27 | géofiltrage / ranking / dédup | filtre amont prioritaire; double contrat collecte/dédup |
| 29, 41 | connecteurs | sécurité et géofiltrage conservés; enrichissement incompatible partiellement |
| 30, 35 | digest quotidien | SK-09 plus récent conservé; alias SPEC-005 ajouté |
| 31, 32 | schéma SQLite | migration additive `SCHEMA_VERSION=12` |
| 34, 36, 38, 40 | routeur/service/UI | noyaux isolés intégrés; câblages centraux non écrasés et donc incomplets |
| 42, 43 | extracteurs | exports cumulés; alias `detect_mission_language` |
| 29, 31, 40 | `messages/result.json` | version candidate conservée; contenu de branche exclu |

## Tests réels

| Étape | Résultat |
|---|---|
| Base `f5b22f2` | 1422 pass, 2 fail, 1 skip |
| Vague 1 finale | 1566 pass, 2 fail, 1 skip |
| Lot 08 ciblé | 1220 pass |
| Lot 21 ciblé | 1060 pass, 172 fail; sous-suite structurée: 29 pass, 22 fail |
| Lots 22-27 ciblés | 66 + 700 + 498 + 30 + 17 + 184 pass |
| Lot 28 ciblé | 81 pass |
| Lot 29 ciblé | 88 pass, 61 fail |
| Lot 30 ciblé | 27 pass |
| Lot 31 ciblé | 58 pass |
| Lot 32 ciblé | 61 pass |
| Lot 35 ciblé | 27 pass |
| Lot 38 ciblé | 68 pass, 24 fail |
| Lot 40 ciblé | 25 pass, 4 fail |
| Lot 41 ciblé | 67 pass |
| Lot 42 ciblé | 123 pass |
| Lot 43 ciblé | 143 pass, 4 fail |
| Suite complète finale | **NON EXÉCUTÉE — intégration partielle** |

## Validation hors budget

| Contrôle | Statut |
|---|---|
| Recette navigateur | **NON VÉRIFIÉ — hors budget** |
| Performance | **NON VÉRIFIÉ — hors budget** |
| Qualité finale / secrets / ruff | **NON VÉRIFIÉ — intégration partielle** |

## Rollback

| Point | SHA candidat |
|---|---|
| Départ | `f5b22f2` |
| Fin vague 1 | `e6ce213` |
| Fin vague 2 | `fac6a20` |
| Fin vague 3 | `4582bea` |
| Fin vague 4 | `f6526c8` |
| Fin vague 5 | `0ee13c2` |
| Arrêt après lot 43 | `de8ed52` |

## Motifs du verdict

| Bloquant | État |
|---|---|
| 12 lots non mergés | bloquant |
| tests ciblés en échec (21, 29, 38, 40, 43) | bloquant |
| suite complète finale absente | bloquant |
| recette/perf non vérifiées par instruction budget | informatif |

