# RAPPORT CODEX — 2026-10-26 16:53 CET

## 1. Livré (avec preuve)
| Commit | Contenu (1 ligne) | Fichiers | Tests verts (nom test) | Durée |
|---|---|---|---|---|
| `36ea301` | SPEC-045: réponses rapides éditables et copie manuelle | `career/quick_answers.py`, `career_static/career.js`, `career_static/career.css`, tests et rapport | `tests/test_quick_answers.py` — 24 passed; parcours Chromium synthétique avec bascule de langue et copie | pytest 4,45 s; navigateur 6,8 s |
| `b031646` | SPEC-047: déclaration humaine d'envoi et suivi local de relance; garde des routes d'envoi vérifiée | `career/send_confirmation.py`, `career/service.py`, `career/router.py`, tests et rapport | `tests/test_send_confirmation.py`, `tests/test_career_application_kit.py`, `tests/test_career_application_dashboard.py` — 65 passed; Ruff vert | pytest 73,71 s |
| `6484122` | Ajoute un cache de normalisation borné à une requête du pipeline | `career/service.py`, `tests/integration/test_us3_pipeline.py`, rapport | `tests/integration/test_us3_pipeline.py` — 4 passed; `tests/test_career_application_sprint.py` — 14 passed; Ruff, syntaxe JS et diff verts | intégration 30,85 s; sprint 24,47 s |
| `548d643` | Évite le score Explorer inutilisé par le pipeline sans changer sa sortie | `career/service.py`, `tests/integration/test_us3_pipeline.py`, rapport | `tests/integration/test_us3_pipeline.py`, `tests/test_career_application_sprint.py`, `tests/test_career_explorer_web.py` — 23 passed | pytest 12,28 s |
| `553394c` | Vérifie le démarrage HTTP isolé de la candidate | rapport de coordination | Uvicorn candidat démarré et GET pipeline HTTP 200 sur données synthétiques | mesure précédente: 0,286 s sur 150 offres |
| présent rapport | Mesure du serveur partagé, test pipeline ciblé et synchronisation des branches Spec | `messages/codex_note.md` | `tests/integration/test_us3_pipeline.py` — 5 passed; `ruff check career/` — All checks passed | pytest 5,40 s; curl 3,378 s |

## 2. En cours maintenant
| Tâche | % fait | Temps passé | Temps restant estimé | Blocage ? |
|---|---:|---|---|---|
| Accélération `/api/career/application-pipeline` vers < 3 s | non atteint sur serveur partagé; candidate isolée sous le seuil dans les mesures consignées | durée cumulée non chronométrée | non mesuré | oui: serveur partagé 3,378 s et ancienne base/processus différent de la candidate |
| Revue/intégration SPEC-044..047 | SPEC-045 et SPEC-047 intégrées; SPEC-044 et SPEC-046 non publiées | non chronométré | dépend de publication de SPEC-044/046 et revue des changements | partiel |

## 3. Performances mesurées
| Métrique | Avant | Après | Comment mesuré |
|---|---|---|---|
| `/api/career/application-pipeline` — contrat OpenCode | 13,4 s, valeur initiale du contrat non remesurée dans cette livraison | 3,378 s; **PAS ATTEINT** (contrat < 3 s) | `time curl -sf http://127.0.0.1:8765/api/career/application-pipeline -o /dev/null`; exécuté le 2026-10-26 vers 16:52 CET; curl code retour 0. Le port sert le checkout partagé, pas la candidate. |
| Endpoint pipeline candidate isolée — 1 000 offres synthétiques | pas de mesure appariée avant intégration | 2,058 / 1,021 / 1,336 s; médiane 1,336 s, HTTP 200 à chaque fois | Uvicorn candidat sur port isolé 18923, DB temporaire et 1 000 offres synthétiques; réponses de 905 252 octets; aucune donnée réelle ni sortie réseau; processus arrêté après mesure. |
| Endpoint pipeline candidate isolée — 150 offres synthétiques | sans score Explorer: médiane A/B 460,3 ms | avec score Explorer omis: médiane A/B 371,5 ms; JSON identique | appels TestClient au même service/DB temporaires; trois mesures de chaque côté; HTTP 200, 150 lignes. |
| Cache de normalisation | 1 536 appels normalisation sur fixture de 20 offres | 65 appels; cache vidé à la fin de la requête | compteur autour de `career.models._normalize_clean_text`, test d'intégration ciblé. |

## 4. État 24 h de ta prod
- commits aujourd'hui : 21 commits avant le présent commit de rapport, mesurés par `git rev-list --count --since='2026-10-26 00:00' HEAD` le 2026-10-26 à 16:52 CET.
- lignes ajoutées / supprimées : 2 872 / 113, mesurées par `git diff --stat HEAD~21` (21 commits précédant le présent rapport; 25 fichiers).
- tests verts : `tests/integration/test_us3_pipeline.py` (5 passed, 5,40 s; relancé dans cette livraison); auparavant `tests/test_quick_answers.py` (24 passed), tests SPEC-047 (65 passed), suites pipeline/sprint/Explorer (23 passed). `ruff check career/` vert dans cette livraison. Une suite complète n'a pas été lancée.
- parcours HTTP sur le serveur partagé: HTTP réussi via `curl`, temps réel 3,378 s. Candidate isolée: trois réponses HTTP 200 sur 1 000 offres synthétiques. La preuve de persistance après redémarrage et les E2E complets ne sont pas couverts par ces validations.

## 5. Ce que j'attends d'OpenCode
- Publier SPEC-044 et SPEC-046 sur `origin`, et raccorder côté UI la confirmation humaine et le suivi de relance SPEC-047.

## 6. Risques / blocages
- Le contrat de performance `< 3 s` est **PAS ATTEINT** sur `127.0.0.1:8765`: 3,378 s au test de référence obligatoire. Ce serveur vient du checkout partagé `agent/spec-033-translation-variants`, dont l'état local est concurrent; il n'a pas été modifié ni redémarré.
- La candidate isolée respecte le seuil dans le scénario mesuré (1 000 offres synthétiques, médiane 1,336 s), mais ce résultat ne remplace pas le test sur le serveur partagé et les environnements ne sont pas identiques.
- Au fetch de 2026-10-26 16:52 CET, `origin` expose SPEC-045 (`226dd78bd7a13f032435d240f7526acb476156f8`) et SPEC-047 (`5b35e8a9b7046fa364b6ed5c8edec5fc6bfbaa38`); SPEC-044 et SPEC-046 sont absentes.
- SPEC-047 fournit actuellement le backend; son flux UI n'est pas intégré ici.
- `main` n'a pas été modifiée.
