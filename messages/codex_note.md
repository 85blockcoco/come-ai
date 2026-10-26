# RAPPORT CODEX — 2026-10-26 19:11 CET

## 1. Livré (avec preuve)
| Commit | Contenu (1 ligne) | Fichiers | Tests verts (nom test) | Durée |
|---|---|---|---|---|
| `0766122` | SPEC-044 adapté: kit conditionné par qualification et source officielle vérifiée | `career/apply_kit.py`, service/router, tests | `tests/test_apply_kit.py` — 7 passed au lot initial | 21,36 s au rejeu précédent |
| `215b316` | Pipeline: index d'étapes et calcul limité aux données consommées | `career/cv_fit.py`, `career/offer_qualification.py`, `career/service.py`, tests | pipeline/Stage Hunter — 67 passed; qualification/pipeline — 49 passed; Ruff vert | 89,38 s / 39,67 s |
| `33d72c7` | Dossiers à jour, revue liée à la version affichée, ouverture concurrente idempotente et blocage des documents incomplets | `career/application_studio.py`, `career/apply_kit.py`, `career/router.py`, `career/service.py`, tests Apply Kit/Kit | `tests/test_apply_kit.py tests/test_career_application_kit.py tests/test_send_confirmation.py` — 64 passed; Ruff et diff-check verts | 17,49 s |
| `a177000` | Corrige la checklist et le blocage d'échéance (états canoniques open/closed) après constat navigateur | `career/apply_kit.py`, `tests/test_apply_kit.py` | `tests/test_apply_kit.py` — 10 passed après deux régressions rouges; Ruff vert | 3,33 s |

## 2. En cours maintenant
| Tâche | % fait | Temps passé | Temps restant estimé | Blocage ? |
|---|---:|---|---|---|
| Contrat pipeline `< 3 s` | 100 % des 3 dernières mesures partagées sous le seuil (3/3) | commandes chronométrées ci-dessous | stabilité sous charge non estimée | pas d'échec dans ces trois mesures; pas une preuve de stabilité générale |
| Raccordement app P0 / recette trois interactions | 0/1 recette navigateur validée; chaîne HTTP API réussie | non mesuré | estimation de travail actuelle: encore 2–3 h pour le P0, à réviser au prochain commit UI | UI f8344ba: prompt indisponible, Suivi vide, revue/langue absentes |
| Alignement sur le vrai `origin/main` GitHub | non mesuré | merge-tree sans changement d'index effectué | non estimé avant résolution | main `69fc924` non ancêtre; 35 chemins conflictuels constatés, aucun merge appliqué |
| SPEC-046 | 0 branche publiée détectée | non mesuré | dépend de sa livraison | absente du contrôle GitHub courant |

## 3. Performances mesurées
| Métrique | Avant | Après | Comment mesuré |
|---|---|---|---|
| `/api/career/application-pipeline` — serveur partagé `127.0.0.1:8765` | 9 990 ms à 17:41 (ancien relevé, PAS ATTEINT) | 2 230 / 2 360 / 2 230 ms; médiane 2 230 ms; 3/3 sous 3 s | `/usr/bin/time curl -sf http://127.0.0.1:8765/api/career/application-pipeline -o /dev/null`; 26/10 18:44:18–18:44:20 puis 18:46:02–18:46:07 CET; codes 0. Le process partagé n'a pas été redémarré par Codex; la variation n'est pas attribuée au code candidat. |
| `/api/career/apply-kit/{job_id}` — candidate isolée | ancien relevé de réouverture 643 ms (scénario différent) | première requête 245 ms; réouverture 151 ms; HTTP 200 | TestClient FastAPI, SQLite/profil/offre synthétiques temporaires; même draft et même review_token; approbation toujours fausse |
| Pipeline HTTP candidate — 1 000 offres synthétiques | pas de mesure appariée avant le lot perf | 1 452 / 1 308 / 1 227 ms; médiane 1 308 ms | TestClient au lot précédent, 3 réponses 200; cette mesure n'a pas été rejouée après le lot 33d72c7 |

## 4. État 24 h de ta prod
- commits aujourd'hui : 35 avant le commit de ce rapport (`git rev-list --count --since='2026-10-26 00:00:00 +0100' HEAD`).
- lignes ajoutées / supprimées : 4 078 / 162 (`git diff --stat HEAD~35..HEAD`, mesuré avant ce rapport; 33 fichiers).
- tests verts: dernier correctif `tests/test_apply_kit.py` — 10 passed en 3,33 s, Ruff Career et diff-check verts. Lot précédent: `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest tests/test_apply_kit.py tests/test_career_application_kit.py tests/test_send_confirmation.py -q` — 64 passed en 17,49 s. Les régressions de fraîcheur/revue/contrat ont d'abord échoué puis sont passées; les deux nouvelles régressions deadline ont aussi été reproduites rouges puis corrigées. Aucune suite complète lancée.
- preuve GitHub: push puis `git ls-remote --heads origin codex/v3-stable-consolidation` ont confirmé `a17700055e1d7b683ff37516feb8c2aff0e500d0`. `origin` est GitHub; le remote local `coordination` a aussi reçu le push.
- recette réelle consignée dans `docs/agent-reports/P0-UI-CANDIDATE-2026-10-26.md`: API 200/200/201, quatre exports valides et persistance après vrai redémarrage Uvicorn. Navigateur: ouverture du kit réussie, parcours complet en échec. Les captures et journaux sont synthétiques.

## 5. Ce que j'attends d'OpenCode
- Garder la lane UI; Codex ne modifie ni desktop, ni routes app, ni orchestrateur. La recette réelle du modal `f8344ba` a échoué: remplacer prompt/alert par le modal, dispatcher `tracking` vers renderTracking() dans render(view), et utiliser `followup_draft`.
- Afficher/confirmer la langue dès « Préparer »; lire `application.id`, `draft_id`, `language`, `review_token`, `fact_checks.document_placeholders` du POST Apply Kit. Bloquer le passage au dépôt si `block_reasons` n'est pas vide. Montrer le vrai aperçu CV/lettre dans `letter.cv_markdown` / `letter.letter_markdown`.
- Deuxième action: après revue explicite, POST `/api/career/applications/{application_id}/approve` avec `{approved:true,draft_id,review_token}`, puis ouvrir le lien officiel vérifié. Le backend refuse une vue périmée (profil, offre, entretien ou documents changés). Troisième action: déclaration d'envoi humain avec `channel:"website"`, pas `site` (actuellement 422); aucun envoi automatique. Le suivi expose `followup_draft`, pas `follow_up_draft`.
- Attribuer SPEC-046 dans agent_note avant de lancer un autre écrivain backend; ne pas doubler le lot Apply Kit déjà livré par Codex.
- Corriger les noms accessibles des nav-boutons et [hidden], ainsi que la grille checklist: à 325 px scrollWidth=613; à 1460 px le libellé de qualification n'a que 21 px contre 583 pour la note. Vérifier le téléchargement navigateur (l'événement download n'a pas été observé en 10 s; HTTP PDF/DOCX verts).

## 6. Risques / blocages
- Les trois mesures récentes de référence respectent `< 3 s` dans la charge observée; la résistance à une charge variable reste à vérifier. Les requêtes n'ont pas lu de corps de réponse ni exposé de donnée personnelle.
- La preuve précédente de push allait d'abord au clone local. Ce point est corrigé: le push direct GitHub du SHA 33d72c7 est maintenant vérifié. La vérification précédente d'ascendance utilisait aussi le main local; le vrai main GitHub `69fc924` diverge et doit être examiné avant de déclarer la candidate prête à fusionner.
- Les appels historiques d'approbation restent compatibles; le nouveau parcours UI doit transmettre draft_id et review_token pour vérifier la version effectivement relue.
- P0 navigateur NON VALIDÉ: `prompt() is not supported` bloque la confirmation; Suivi reste vide alors que l'API et la DB persistent correctement. Aucun lien ATS synthétique n'a été ouvert et aucune candidature n'a été soumise. Le serveur/onglet de test ont été arrêtés/fermés, le viewport restauré.
- Aucune soumission automatique, aucune donnée personnelle réelle en fixture, aucun changement de schéma SQLite. `main` et le code partagé en cours d'exécution n'ont pas été modifiés par Codex.
