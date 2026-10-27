# RAPPORT CODEX — 2026-10-27 16:40 CET

## 1. Livré (avec preuve)
| Commit | Contenu (1 ligne) | Fichiers | Tests verts (nom test) | Durée |
|---|---|---|---|---|
| `94dd041` | Sélecteur persistant NAGE Terminal / NAGE Studio et thème professionnel clair | `desktop_static/index.html`, `desktop_static/app.js`, `desktop_static/app.css`, `tests/test_desktop_app.py` | `tests/test_desktop_app.py` inclus dans le run final | run final ci-dessous |
| `48ca9eb` | Preuve navigateur du parcours candidature en trois interactions, sans envoi automatique | rapport P0, preuve JSON, coordination | 34 tests P0 au lot initial; persistance Uvicorn et console navigateur vérifiées | 13,86 s au lot initial |
| `2a00644` | Alignement isolé de toute la consolidation Career avec `origin/main` | 304 chemins du merge, conflits résolus sélectivement | lots cœur, connecteurs et P0 exécutés avant commit | voir section 3 |
| `f7682ed` | Réintégration des commits P0 et NAGE Studio postérieurs à la base d’alignement | Career, desktop, rapports et tests | run consolidé final: **1 416 passed**; Ruff et contrôles JS verts | **56,54 s** pytest; 57,69 s réel |

## 2. En cours maintenant
| Tâche | % fait | Temps passé | Temps restant estimé | Blocage ? |
|---|---:|---|---|---|
| Candidate unique alignée sur GitHub `origin/main` | 100 % techniquement; publication en cours | deux merges isolés et validation ciblée | quelques minutes pour push/vérification distante | aucun conflit restant; `main` n’est pas modifiée |
| P0 candidature en trois interactions | 100 % du scénario synthétique défini | navigateur + HTTP + redémarrage | recette réelle employeur volontairement hors périmètre | aucune soumission automatique autorisée |
| Style professionnel NAGE Studio | 100 % du lot demandé | implémentation + tests + navigateur | terminé | aucun avertissement/erreur console observé |
| Campagne globale hors Career/P0 | non incluse dans ce lot ciblé | aucune suite complète relancée | à planifier séparément | cette preuve ne couvre pas tous les modules historiques |

## 3. Performances mesurées
| Métrique | Avant | Après | Comment mesuré |
|---|---|---|---|
| `/api/career/application-pipeline` | 9 990 ms, ancien serveur partagé du 26/10 | **11,841 ms à froid; 9,923 et 9,978 ms à chaud** | `curl -sf -o /dev/null -w '%{time_total}' http://127.0.0.1:18928/api/career/application-pipeline`, serveur Uvicorn isolé et base synthétique vide, 27/10 vers 16:38 CET |
| Démarrage/routes locales | non apparié | health 288 ms; `/app` 6,8 ms; `/career` 3,7 ms; HTTP 200 | serveur isolé `create_app(base_dir=/tmp/come-ai-align-…)`, port 18928 |
| Run ciblé consolidé | lots séparés | **1 416 passed** | pytest explicite sur qualification, dates, géographie, déduplication, connecteurs, application kit/pipeline, UX et desktop |

## 4. État 24 h de ta prod
- commits aujourd’hui avant ce rapport : 6.
- diff de la candidate alignée contre `origin/main` : 151 fichiers, 20 136 ajouts, 375 suppressions (`git diff --shortstat origin/main...HEAD`).
- ascendance : `origin/main...HEAD` = `0 106`; la candidate contient donc le `main` GitHub actuel sans le modifier.
- tests verts : **1 416 passed en 56,54 s**; deux tests géographiques ont d’abord reproduit une divergence de contrat, ont été corrigés puis rejoués verts. `ruff check career/`, `node --check career_static/career.js`, `node --check desktop_static/app.js` et `git diff --check` sont verts.
- navigateur réel : `/app#applications` sur 18928, bascule vers NAGE Studio puis rechargement; valeur `studio` persistée, sélecteur toujours sur « NAGE Studio », zéro log console warn/error.

## 5. Ce que j’attends d’OpenCode
- Aucun travail requis pour ce lot. Ne pas modifier concurremment la candidate pendant la publication et la vérification du SHA.

## 6. Risques / blocages
- La mesure pipeline sur base synthétique vide prouve largement le contrat `< 3 s`, mais ne remplace pas un benchmark chargé avec 1 000 offres après cet alignement.
- Le run de 1 416 tests est une campagne ciblée large, pas la suite complète du dépôt.
- Le parcours en trois interactions reste volontairement un scénario synthétique et manuel : aucune candidature réelle, aucune donnée personnelle et aucun formulaire employeur n’ont été envoyés.
- `main` demeure inchangée. Toute convergence de `main` nécessite toujours une décision humaine distincte.
