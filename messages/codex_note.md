# RAPPORT CODEX — 2026-10-27 21:25 CET

## 1. Livré (avec preuve)
| Commit | Contenu (1 ligne) | Fichiers | Tests verts (nom test) | Durée |
|---|---|---|---|---|
| `eff542c` | Préserve les pages d’un CV texte court et les preuves temporelles/provenances lors de la déduplication | `career/service.py`, `career/exploration_service.py`, 2 tests | gate officiel : **6 437 passed, 12 skipped, 0 failed** | **466,46 s** suite complète |
| `741b9ba` | Priorise BBA/Bachelor/Bac+4 sans masquer M2/MBA | Career backend, interface Career et tests | inclus dans la campagne complète | inclus ci-dessous |
| `94dd041` | Sélecteur persistant NAGE Terminal / NAGE Studio et thème professionnel clair | desktop et test UI | inclus dans la campagne complète | inclus ci-dessous |
| `48ca9eb` | Parcours candidature en trois interactions, sans envoi automatique | Career, desktop, rapport P0 | inclus dans la campagne complète | inclus ci-dessous |
| `2a00644` + `f7682ed` | Alignement isolé avec `origin/main`, puis réintégration du P0 et de NAGE Studio | candidate consolidée | inclus dans la campagne complète | inclus ci-dessous |

## 2. En cours maintenant
| Tâche | % fait | Temps passé | Temps restant estimé | Blocage ? |
|---|---:|---|---|---|
| Candidate isolée alignée sur `origin/main` | 100 % techniquement | alignement, corrections et campagne complète | publication et vérification SHA | aucun; `main` reste intacte |
| P0 candidature en trois interactions | 100 % du scénario synthétique défini | HTTP, navigateur, persistance et tests | recette employeur réelle volontairement exclue | aucune soumission automatique autorisée |
| Priorité d’études BBA/Bac+4 | 100 % | classement backend/client + libellés + tests | terminé | M2/MBA restent visibles |
| Édition CV NAGE | 100 % du périmètre local | génération, modification, sauvegarde, revue invalidée et export | terminé | validation humaine requise avant usage externe |

## 3. Performances mesurées
| Métrique | Avant | Après | Comment mesuré |
|---|---|---|---|
| `/api/career/application-pipeline` | 9 990 ms, ancien serveur partagé du 26/10 | **11,646 ms à froid; 10,916 et 8,359 ms à chaud** | `curl` sur serveur Uvicorn isolé, base synthétique vide, port 18929, 27/10 à 21:09 CET |
| Routes applicatives locales | non apparié | `/app` 7,517 ms; `/career` 4,960 ms; HTTP 200 | même serveur isolé |
| Campagne complète actuelle | précédent passage : 6 435 passed, 2 failed, 12 skipped | **6 437 passed, 0 failed, 12 skipped** | gate officiel monolithique, 6 449 cas collectés, 466,46 s |

## 4. État 24 h de ta prod
- commits aujourd’hui avant la mise à jour de ce rapport : 10.
- diff candidate contre `origin/main` après `eff542c` : 154 fichiers, 20 240 ajouts, 397 suppressions (`git diff --shortstat origin/main...HEAD`).
- ascendance : `origin/main...HEAD` = `0 109`; la candidate contient donc le `main` distant observé, sans le modifier.
- tests verts : fichiers racine `744 + 2 095 + 1 266 + 2 206`, contrats/intégration `26`, évaluations `100` = **6 437 passed**. Les **12 skips** sont 9 contrôles connecteurs live désactivés, 2 contrôles géographiques live désactivés et 1 exhaustivité sans script/base disponible.
- gate officiel `scripts/career_release_gate.py` : **PASS** au SHA `7611490`; worktree propre, `compileall`, 1 232 tests matching, 209 contrats de release, Ruff global et suite complète tous verts. Preuve locale : `artifacts/career-release-gate.json`.
- contrôles statiques : `ruff check career tests scripts/career_release_gate.py`, `git diff --check` verts.
- navigateur déjà validé sur la candidate : parcours P0, persistance du style NAGE Studio et zéro avertissement/erreur console après correction du script Constitution.

## 5. Ce que j’attends d’OpenCode
- Aucun travail requis pour cette livraison; éviter toute modification concurrente de la candidate pendant le push et la vérification distante.

## 6. Risques / blocages
- Les 12 contrôles live ignorés ne prouvent pas la disponibilité actuelle des fournisseurs externes; la logique déterministe et les doubles synthétiques sont verts.
- Le benchmark pipeline est réalisé sur une base synthétique vide; le contrat `< 3 s` est atteint très largement, mais un benchmark chargé reste une preuve distincte.
- Aucune candidature réelle, donnée personnelle ni soumission employeur n’a été utilisée.
- Le checkout historique `/Users/comedelavenne/AI-Excel-Agent` est sur `agent/spec-033-translation-variants` avec de nombreux fichiers modifiés/non suivis; il ne doit pas servir directement à la convergence. Après accord, utiliser un worktree propre créé depuis `origin/main`, puis un fast-forward vers le SHA candidat.
- `main` demeure inchangée; sa convergence reste soumise à l’accord explicite de Côme.
