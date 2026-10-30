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

---

# RAPPORT CODEX — 2026-10-29 16:05 CET

## 1. Livré (avec preuve)
| Commit | Contenu (1 ligne) | Fichiers | Tests verts (nom test) | Durée |
|---|---|---|---|---|
| en préparation | NAGE unifié : Stage Hunter intégré, qualification stage/langue/dates, espace Devoirs et Study Coach local persistant | 20 fichiers, 1 312 ajouts, 94 suppressions | 602 tests Career/Desktop/Study, puis 12 tests incrémentaux | 185,17 s + 10,1 s |
| correctif CI de ce rapport | Rétrocompatibilité `QualifiedOffer` et reconnaissance explicite des intitulés de stage allemand, italien et espagnol | qualification, corpus gelé et tests | 58 tests ciblés (`offer_exhaustiveness`, `offer_intelligence`, `career_offer_qualification`) | 2,20 s |

## 2. En cours maintenant
| Tâche | % fait | Temps passé | Temps restant estimé | Blocage ? |
|---|---:|---:|---:|---|
| Candidate NAGE Career + Devoirs | 100 % du code et de la recette candidate | session du 29/10 | commit, push, déploiement Bureau et recette de l’instance exacte | aucun blocage code ; Ollama absent au dernier démarrage, outils déterministes disponibles |

## 3. Performances mesurées
| Métrique | Avant | Après | Comment mesuré |
|---|---|---|---|
| `/api/career/application-pipeline` | 13,4 s historique | 389,724 ms à froid ; 14,438 et 21,062 ms à chaud | serveur candidat isolé, port 18933, 29/10 à 16:05 CET |
| `/api/study/overview` | nouvelle route | 17,077 ms à froid ; 5,860 et 5,699 ms à chaud | trois requêtes HTTP locales, base avec TD4 et séances persistées |
| `/app` | non apparié | 9,891 ms à froid ; 3,748 et 3,517 ms à chaud | trois requêtes HTTP locales |

## 4. État 24 h de ta prod
- commits aujourd’hui avant cette livraison : 0 ; la livraison sera un commit atomique.
- diff de travail : 20 fichiers, 1 312 ajouts, 94 suppressions.
- tests verts : 602 tests ciblés Career/Desktop/Study en 183,39 s ; 12 tests incrémentaux Devoirs/Study en 8,12 s ; Ruff, `node --check` et `git diff --check` verts.
- navigateur candidat : 8 documents réels autorisés visibles ; TD4 structuré en 5 sections et 38 tâches ; 9 notions ; séance 5 questions ; correction sourcée ; reprise persistante à la question 2/5 ; QCM sans identifiants techniques.

## 5. Ce que j’attends d’OpenCode
- Aucun travail requis pour cette livraison ; ne pas modifier la candidate pendant le déploiement.

## 6. Risques / blocages
- Le tuteur conversationnel local nécessite un service Ollama disponible ; lecture, structuration, analyse Excel, quiz, corrections et progression restent utilisables sans modèle.
- La première CI complète a exposé 3 régressions sur 6 458 cas ; elles sont corrigées et couvertes avant la seconde CI.
- La seconde CI a confirmé 6 446 tests verts et exposé une unique référence Constitution déplacée vers une ligne vide ; la référence vise de nouveau le code actif et son test dédié passe.
- Aucun original personnel n’est modifié ; les huit documents sont copiés dans les données locales ignorées par Git.
- Aucune soumission de candidature, aucun envoi de document et aucun fournisseur cloud n’est déclenché par ce parcours.

---

# RAPPORT CODEX — 2026-10-29 16:40 CET

## Livraison UX apprentissage

- Le dernier document de travail est désormais mémorisé localement et restauré après chargement; en l’absence d’historique, NAGE privilégie le document possédant déjà un parcours d’apprentissage.
- La bibliothèque Devoirs possède un filtre instantané, un compteur de résultats et un badge `Parcours créé`.
- Un aperçu compact expose documents, parcours, questions travaillées et notions à revoir.
- Le sélecteur `Dossier en` est masqué hors des parcours candidature où il est pertinent.
- Quand Ollama n’est pas configuré, les commandes conversationnelles sont désactivées avec une explication honnête; lecture, analyse, quiz et progression restent accessibles.

## Preuves

- `node --check desktop_static/app.js` : vert.
- `pytest -q tests/test_desktop_app.py tests/test_study_web_integration.py` : **4 passed en 6,14 s**.
- `ruff check tests/test_desktop_app.py` et `git diff --check` : verts.
- Navigateur réel sur la candidate : TD4 restauré, badge de parcours visible, 4 indicateurs de progression, absence de `Dossier en`, tuteur indisponible expliqué, recherche `Eurotech` ramenant la bibliothèque de 8 à 2 documents.

---

# RAPPORT CODEX — 2026-10-30 13:11 CET

## Livraison espace devoirs question par question

- Chaque question détectée possède désormais un état (`À faire`, `En cours`, `À vérifier`, `Terminé`) et des notes de résolution enregistrées localement.
- La progression possède un compteur et une barre d’avancement; les documents originaux ne sont jamais modifiés.
- La progression survit au redémarrage et son fichier local est limité au compte utilisateur (`0600`).
- Une entrée locale partiellement corrompue est ignorée proprement au lieu de casser la page.
- Le libellé du tuteur indique honnêtement `modèle local configuré`, sans promettre sa disponibilité instantanée sous charge.

## Preuves actuelles

- `tests/test_study_web_integration.py` : **3 passed en 15,24 s**.
- `tests/test_desktop_app.py` : **2 passed en 9,79 s**.
- Ruff ciblé, `node --check desktop_static/app.js` et `git diff --check` : verts.
- Navigateur réel sur la candidate : **38 questions** du TD4 affichées; la première a été passée à `À vérifier`, annotée, enregistrée puis relue via l’API.
- Redémarrage déjà vérifié : état et notes conservés.
- Ollama : modèle local `qwen3.5:2b-q4_K_M` configuré; une réponse minimale a fonctionné, mais les demandes documentaires longues restent lentes lorsque les workers OpenCode utilisent le même service.

## Limite explicite

- Cette livraison prouve le suivi question par question et sa persistance. Elle ne prouve pas encore une latence acceptable du tuteur conversationnel avec un document complet sous charge concurrente.

---

# RAPPORT CODEX — 2026-10-30 19:06 CET

## Priorité urgente offres + CV + lettre

- Le dossier de candidature affiche maintenant un audit factuel visible : score sur 100, factualité, preuves du profil, adaptation à l’offre et trois corrections prioritaires.
- Tous les exports et la copie sont visiblement bloqués tant que le profil, l’offre ou l’audit ne permettent pas une candidature sûre; l’export ZIP est également refusé côté serveur si l’audit échoue.
- L’auditeur distingue désormais une citation exacte de l’offre (langue, date, durée, exigence) d’une affirmation personnelle. Exemple vérifié : « Fluent English is required » reste un fait de l’offre; « I have fluent English » exige toujours une preuve du profil.
- Les formules de politesse et les champs à compléter ne polluent plus le score factuel; ils sont traités par leurs contrôles dédiés.
- Le classement BBA/Bachelor/Bac+4 avant M2/MBA reste actif et testé; les offres ambitieuses restent visibles.

## Preuves actuelles

- `pytest -q tests/test_apply_kit_bundle.py tests/test_claim_check.py tests/test_dossier_quality.py tests/test_desktop_app.py tests/test_career_education_access.py tests/test_career_stage_hunter.py tests/test_career_search_ux.py` : **237 passed en 18,99 s**.
- Ruff `career/`, `node --check desktop_static/app.js` et `git diff --check` : verts.
- Navigateur Playwright sur la candidate, port 18940 : carte qualité visible, **5 exports désactivés**, **0 lien de téléchargement actif**, copie désactivée et **0 erreur console** sur le dossier synthétique incomplet.
- API synthétique après correction : 16 citations de l’offre reconnues, 11 éléments de gabarit ignorés, 0 fait candidat inventé attribué à tort.

## Limites et sécurité

- Le profil synthétique de recette est volontairement incomplet : score 0 et export bloqué, comportement attendu.
- Aucun CV personnel, aucune candidature réelle, aucun envoi automatique et aucun fournisseur cloud n’ont été utilisés.

## Déploiement Bureau vérifié

- Branche poussée : `codex/nage-consolidation-20261030`, commit fonctionnel `1700dd3163362c7dadb0cd1049c134929ade28e3`, confirmé par `git ls-remote`.
- Le checkout propre `/Users/comedelavenne/NAGE-release` utilisé par `/Users/comedelavenne/Desktop/NAGE.app` a été positionné sur ce commit; `main` reste inchangée.
- Instance exacte `127.0.0.1:8766` : `/app` et `/career` HTTP 200; Stage Hunter intégré dans l’application; préférence `bachelor_m1_then_m2`; 29 cartes visibles; 30 actions de préparation; aucun débordement horizontal et 0 erreur console.
- Pipeline chargé, trois mesures : **1,80 s**, **1,75 s**, **2,12 s**; objectif `< 3 s` atteint sur les trois appels.

## Classement visible des meilleures offres

- Chaque carte Stage Hunter affiche maintenant son rang (`Choix #N`) et un statut explicite : `Accessible BBA / Bac+4`, `Ambitieux M2 / MBA`, `Niveau à vérifier` ou `Hors préférence`.
- Le résumé compte séparément les offres accessibles et ambitieuses; les M2/MBA restent affichées.
- Preuves : **110 tests** Stage Hunter/éducation/Desktop verts en 16,39 s; navigateur candidate sans erreur console, rang et résumé visibles.
